"""④ Evidence: turn the pointers found in step ③ into the least text that answers. No LLM.

Context levels (DECISIONS_LOG P2-15):
  L0  places only: names, kinds, addresses, counts; no text
  L1  summaries: an article's first paragraph
  L2  sentences: the sentence(s) around each pointer's entity positions
  L3  whole paragraphs: used only when everything found is small (the level slides with size)

Everything is numbered - places [1] [2], summaries [L1], sentences [S1] - so the answer can cite them
and code can check the citations. A word budget caps what the LLM reads; items are filled round-robin
(every top place gets one sentence before any gets a second), and whatever doesn't fit is counted,
never silently dropped. The amounts at every level are measured for each question, so the budget can
be chosen from data (P2-16).
"""
import re
from typing import Literal, Optional

from pydantic import BaseModel, Field

from graph_index import GraphIndex
import graph_tools as T
from graph_tools import Pointer
from planner import QueryPlan
from retrieve import Retrieval

DEFAULT_BUDGET_WORDS = 2000      # provisional until the amounts are reviewed (P2-16)
MAX_PER_ITEM = 50                # rounds of round-robin: with few items, each gets more passages (P2-47)
MAX_SUMMARY_WORDS = 120          # a summary is cut at a sentence end after this many words
MAX_WINDOW_SENTENCES = 3
SMALL_RESULT_SHARE = 0.5         # whole paragraphs if they all fit in half the budget
MAX_PLACES_LISTED = 30           # places listed to the LLM when none is described in a passage
MAX_OTHER_PLACES = 10            # top places listed besides those described in the passages

_ABBREVIATIONS = {"mr", "mrs", "ms", "dr", "gen", "lt", "col", "maj", "capt", "sgt", "st", "jr", "sr", "no",
                  "vs", "approx", "u.s", "u.k", "e.g", "i.e", "etc", "inc", "ltd", "co", "jan", "feb", "mar",
                  "apr", "aug", "sep", "sept", "oct", "nov", "dec", "mt", "ft"}
_BOUNDARY = re.compile(r"[.!?](?=\s+[\"“(\[]?[A-Z0-9])")


class PlaceRef(BaseModel):
    number: int
    id: str
    label: str
    kind: str
    address: Optional[str] = None
    records: int = 0
    uncertain: Optional[str] = None
    why: str = ""                    # one data line: relations, counts, distance (no corpus text)
    in_text: bool = False            # described to the LLM (a passage, or a list answer's data line)


class EntityRef(BaseModel):
    id: str
    type: str
    records: int = 0
    role: Optional[str] = None


class Passage(BaseModel):
    id: str                          # "L1", "S4"
    kind: Literal["summary", "sentence", "paragraph"]
    text: str
    text_id: int
    offset: int = 0                  # where the passage starts in its paragraph
    spans: list[list[int]] = Field(default_factory=list)   # entity positions, relative to the passage
    article: str
    section: Optional[str] = None
    about: list[str] = Field(default_factory=list)   # "[3]" for place 3, an entity id, or a record
    low_confidence: bool = False
    words: int = 0


class Amounts(BaseModel):
    """How much text this question could produce at each level (P2-16)."""
    places_found: int = 0
    entities_found: int = 0
    records_found: int = 0
    pointers: int = 0                # pointers available to step ④ (step ③ keeps at most 50 per item)
    pointers_total: int = 0          # pointers found in the graph overall
    words_summaries: int = 0         # L1
    words_all_sentences: int = 0     # L2, if every available pointer got its sentences
    words_all_paragraphs: int = 0    # L3, if every available pointer got its whole paragraph
    words_included: int = 0
    budget_words: int = 0


class EvidencePack(BaseModel):
    level: str
    shape: str = "explain"                 # list / fact / explain / drilldown (P2-48)
    shape_reason: str = ""
    found_by: str = ""                     # how the places / people were found, in one line
    places: list[PlaceRef] = Field(default_factory=list)
    regions: list[T.RegionNode] = Field(default_factory=list)   # nested overview of big lists (P2-49)
    entities: list[EntityRef] = Field(default_factory=list)
    passages: list[Passage] = Field(default_factory=list)
    amounts: Amounts = Field(default_factory=Amounts)
    needs_area: bool = False               # a question about an area that has none: no place, no map selection
    notes: list[str] = Field(default_factory=list)


# --- Sentences -------------------------------------------------------------------------------

def sentence_ranges(text: str) -> list[tuple[int, int]]:
    """Sentence start/end offsets. Doesn't split after abbreviations (Gen., U.S.) or initials (V.)."""
    out, start = [], 0
    for m in _BOUNDARY.finditer(text):
        end = m.end()
        last = text[start:end].split()[-1].rstrip(".!?").lower() if text[start:end].split() else ""
        if last in _ABBREVIATIONS or (len(last) == 1 and last.isalpha()):
            continue
        out.append((start, end))
        start = end
        while start < len(text) and text[start].isspace():
            start += 1
    if start < len(text):
        out.append((start, len(text)))
    return out or [(0, len(text))]


def window(text: str, spans: list[list[int]]) -> tuple[int, int]:
    """The sentence range covering the spans: from the first to the last sentence that contains one,
    or only the first such sentence if that would be more than MAX_WINDOW_SENTENCES."""
    ranges = sentence_ranges(text)
    hit = [i for i, (a, b) in enumerate(ranges) if any(a <= s < b or a < e <= b for s, e in spans)] or [0]
    first, last = hit[0], hit[-1]
    if last - first + 1 > MAX_WINDOW_SENTENCES:
        last = first
    return ranges[first][0], ranges[last][1]


def _words(text: str) -> int:
    return len(text.split())


def _cut_summary(text: str) -> str:
    if _words(text) <= MAX_SUMMARY_WORDS:
        return text
    out = ""
    for a, b in sentence_ranges(text):
        if out and _words(out + text[a:b]) > MAX_SUMMARY_WORDS:
            break
        out = text[:b]
    return out or " ".join(text.split()[:MAX_SUMMARY_WORDS]) + " …"


# --- Building the pack -----------------------------------------------------------------------

class _Item:
    """Something to describe (a place, an entity or a relation record) and its pointers, best first."""

    def __init__(self, label: str, pointers: list[Pointer], low_confidence: bool = False):
        self.label, self.low_confidence = label, low_confidence
        self.pointers = sorted(pointers, key=lambda p: -len(p.spans))


def _items(plan: QueryPlan, ret: Retrieval, numbers: dict[str, int], shape: str) -> list[_Item]:
    places = [_Item(f"[{numbers[h.group.id]}]", h.pointers) for h in ret.places]
    entities = [_Item(h.group.id, h.pointers) for h in ret.entities]
    records = [_Item(f"{r.subject or r.other} {r.relation} {r.target if r.subject != r.target else r.other}",
                     [r.pointer], r.low_confidence) for r in ret.records]
    if shape in ("fact", "drilldown"):
        return records or (entities + places)
    if plan.type in ("about", "relation"):
        return records + entities + places
    return places + entities


# --- Answer shapes (P2-48) -------------------------------------------------------------------

Shape = Literal["list", "fact", "explain", "drilldown"]
LIST_TYPES = {"entity_places", "event_places", "event_list", "common", "area", "area_topic"}
LIST_MIN_PLACES = 10       # more places than this, for a list-type question: a list answer (P2-54)
LIST_TOP = 10              # places described (one data line each) in a list answer
SHAPE_BUDGETS = {"list": 500, "fact": 600, "drilldown": 800}   # explain uses the budget passed in
MAX_SUMMARIES = {"list": 1, "fact": 2, "drilldown": 2, "explain": 4}


def choose_shape(plan: QueryPlan, ret: Retrieval) -> tuple[Shape, str]:
    """The answer's shape, from the question type and the result size. Decided by code, not the user."""
    if ret.route.startswith("drill-down"):
        return "drilldown", "one entity at one place"
    if plan.type == "place_lookup":
        return "fact", "where a place is"
    if plan.type == "relation" or (plan.type == "about" and plan.relations):
        return "fact", "who did what"
    if plan.needs == "detailed_text":
        return "explain", "the question asks for detail"
    if plan.type in LIST_TYPES and len(ret.places) > LIST_MIN_PLACES:
        return "list", f"{len(ret.places)} places found: the map carries them, the text stays short"
    return "explain", "a small result or a question about something"


def describe_search(plan: QueryPlan, ret: Retrieval) -> str:
    """How the places and people were found, in one line - so the LLM knows what a match means even
    when a list answer carries no corpus text (e.g. 'paragraphs mention: drone')."""
    area = ret.area_used or {}
    if area.get("from") == "point":
        where = f"within {area.get('radius_m', 0):g} m of the map point"
    elif area.get("from") == "map":
        where = "inside the map area"
    elif area.get("from"):
        where = f"inside {area['from']}"
    else:
        where = ""
    route = ret.route.split(":")[0]
    if route == "area_topic":
        found = f"places {where} whose paragraphs mention: {', '.join(plan.keywords) or 'the topic'}"
        return found + (f"; ranked by {', '.join(plan.relations)} records" if plan.relations else "")
    if route == "area":
        return f"places {where}"
    targets = ", ".join(e.name for e in plan.entities) or ", ".join(c.text for c in plan.concepts)
    if route == "entity_places":
        return (f"places linked to {targets} in the text; ranked by relations that put it at the place, "
                f"then by how specific the place is to it")
    if route == "event_places":
        return f"places mentioned in the article about {targets}; ranked by how many of its paragraphs mention them"
    if route == "common":
        return f"places linked to every one of: {targets}"
    if route == "drill-down":
        return f"the records linking {targets}"
    if plan.relations:
        return f"{', '.join(plan.relations)} records of {targets}"
    return ret.route


def _short_address(address: Optional[str]) -> Optional[str]:
    if not address:
        return None
    parts = [p.strip() for p in address.split(",") if p.strip() and not re.fullmatch(r"[\d\- ]+", p.strip())]
    return ", ".join(parts[:2] + parts[-1:]) if len(parts) > 3 else ", ".join(parts)


def why_line(hit) -> str:
    """One line of data about why a place is in the result - no LLM, no text from the corpus."""
    bits = []
    rels = [f"{k} in {v} record{'s' if v != 1 else ''}" for k, v in hit.relations.items() if k != "MENTIONED_WITH"][:3]
    if rels:
        bits.append(", ".join(rels))
    if hit.relations.get("MENTIONED_WITH"):
        bits.append(f"mentioned together in {hit.relations['MENTIONED_WITH']} records")
    if hit.distance_m is not None:
        bits.append(f"{hit.distance_m:,.0f} m away")
    if hit.records:
        bits.append(f"{hit.records} matching paragraphs")
    if hit.specificity:
        bits.append(f"{hit.specificity:.0%} of the place's paragraphs")
    return "; ".join(bits)


# --- Building the pack -----------------------------------------------------------------------

def build_evidence(plan: QueryPlan, ret: Retrieval, gi: GraphIndex,
                   budget_words: int = DEFAULT_BUDGET_WORDS) -> EvidencePack:
    shape, reason = choose_shape(plan, ret)
    budget = SHAPE_BUDGETS.get(shape, budget_words)
    numbers = {h.group.id: i for i, h in enumerate(ret.places, 1)}
    pack = EvidencePack(level="", shape=shape, shape_reason=reason, found_by=describe_search(plan, ret), places=[
        PlaceRef(number=numbers[h.group.id], id=h.group.id, label=h.group.id,
                 kind=(h.group.place.place_type if h.group.place else None) or h.group.type,
                 address=_short_address(h.group.place.address) if h.group.place else None, records=h.records,
                 uncertain=h.group.place.uncertain_reason if h.group.place and h.group.place.uncertain else None,
                 why=why_line(h))
        for h in ret.places],
        entities=[EntityRef(id=h.group.id, type=h.group.type, records=h.records, role=h.role) for h in ret.entities],
        needs_area=plan.type in ("area", "area_topic") and ret.area_used is None)
    items = _items(plan, ret, numbers, shape)
    all_items = _items(plan, ret, numbers, "explain")   # amounts are measured over everything found

    windows: dict[tuple[int, int, int], None] = {}
    paragraphs: set[int] = set()
    for item in all_items:
        for p in item.pointers:
            text = gi.text(p.text_id)["text"]
            a, b = window(text, p.spans)
            windows[(p.text_id, a, b)] = None
            paragraphs.add(p.text_id)
    summaries = [(s, _cut_summary(gi.text(s.pointer.text_id)["text"])) for s in ret.summaries][:MAX_SUMMARIES[shape]]
    am = pack.amounts
    am.places_found, am.entities_found, am.records_found = len(ret.places), len(ret.entities), len(ret.records)
    am.pointers = sum(len(i.pointers) for i in all_items)
    am.pointers_total = sum(h.pointers_total for h in ret.places + ret.entities) + len(ret.records)
    am.words_summaries = sum(_words(gi.text(s.pointer.text_id)["text"]) for s in ret.summaries)
    am.words_all_sentences = sum(_words(gi.text(t)["text"][a:b]) for t, a, b in windows)
    am.words_all_paragraphs = sum(_words(gi.text(t)["text"]) for t in paragraphs)
    am.budget_words = budget

    if len(ret.places) > LIST_MIN_PLACES:
        pack.regions = T.region_tree(gi, [(numbers[h.group.id], h) for h in ret.places])

    # Which text, per shape: a list answer has no corpus sentences; a place lookup only its summary.
    if shape == "list" or plan.type == "place_lookup" or not items:
        level, use_text, use_paragraphs = "L0+L1: places and summaries", False, False
    elif am.words_all_paragraphs <= budget * SMALL_RESULT_SHARE:
        level, use_text, use_paragraphs = "L1+L3: summaries and whole paragraphs (small result)", True, True
    else:
        level, use_text, use_paragraphs = "L1+L2: summaries and sentences", True, False
    pack.level = level

    used = 0
    for i, (s, text) in enumerate(summaries, 1):
        node = gi.text(s.pointer.text_id)
        pack.passages.append(Passage(id=f"L{i}", kind="summary", text=text, text_id=s.pointer.text_id,
                                     article=s.article, section=node.get("title"), about=[s.about],
                                     words=_words(text)))
        used += _words(text)
    if shape == "list":
        used += sum(len(f"{p.label} {p.kind} {p.address or ''} {p.why}".split()) for p in pack.places[:LIST_TOP])

    by_window: dict[tuple[int, int, int], Passage] = {}
    skipped_for_budget = 0
    if use_text:
        for rank in range(MAX_PER_ITEM):
            for item in items:
                if rank >= len(item.pointers):
                    continue
                p = item.pointers[rank]
                node = gi.text(p.text_id)
                full = node["text"]
                a, b = (0, len(full)) if use_paragraphs else window(full, p.spans)
                key = (p.text_id, a, b)
                if key in by_window:   # the same passage already describes another item: just note it
                    if item.label not in by_window[key].about:
                        by_window[key].about.append(item.label)
                    continue
                words = _words(full[a:b])
                if used + words > budget:
                    skipped_for_budget += 1
                    continue
                passage = Passage(id=f"S{len(by_window) + 1}", kind="paragraph" if use_paragraphs else "sentence",
                                  text=full[a:b], text_id=p.text_id, offset=a,
                                  spans=[[s - a, e - a] for s, e in p.spans if a <= s and e <= b],
                                  article=node["source"], section=node.get("title"), about=[item.label],
                                  low_confidence=item.low_confidence, words=words)
                by_window[key] = passage
                pack.passages.append(passage)
                used += words
    am.words_included = used

    described = {lbl for p in pack.passages for lbl in p.about}
    for ref in pack.places:
        ref.in_text = (f"[{ref.number}]" in described or ref.id in described
                       or (shape == "list" and ref.number <= LIST_TOP) or plan.type == "place_lookup")
    if pack.places:
        pack.notes.append(f"{len(pack.places)} places found (all go on the map); "
                          f"{sum(1 for r in pack.places if r.in_text)} described to the LLM")
    if shape == "list":
        pack.notes.append("list answer: no corpus sentences by design; each place has a data line, and "
                          "'tell me about number N' gives the details")
    if skipped_for_budget:
        pack.notes.append(f"{skipped_for_budget} more passages didn't fit the {budget}-word budget "
                          f"(available for a 'show more' page)")
    return pack


# --- What the LLM will read ------------------------------------------------------------------

SHAPE_INSTRUCTIONS = {
    "list": "a short overview (2-4 sentences); the map shows every place, so name only the strongest few by number",
    "fact": "a short, direct answer",
    "drilldown": "a focused paragraph about this entity at this place",
    "explain": "a paragraph or two built from the passages, place by place",
}


def _region_lines(regions: list, top_countries: int = 3, top_regions: int = 4) -> list[str]:
    lines = []
    for country in regions[:top_countries]:
        inner = [f"{c.id} {c.count}" for c in country.children[:top_regions]]
        more = f" (+{len(country.children) - top_regions} more regions)" if len(country.children) > top_regions else ""
        lines.append(f"- {country.id}: {country.count} places" + (f" — {', '.join(inner)}{more}" if inner else ""))
    if len(regions) > top_countries:
        lines.append(f"- and {sum(r.count for r in regions[top_countries:])} places in "
                     f"{len(regions) - top_countries} other countries or areas")
    return lines


def render_for_llm(pack: EvidencePack, question: str) -> str:
    """The exact text step ⑤ sends to the LLM. The trace shows the same string."""
    lines = [f"QUESTION: {question}", f"ANSWER SHAPE: {pack.shape} - {SHAPE_INSTRUCTIONS[pack.shape]}"]
    if pack.found_by:
        lines.append(f"FOUND BY: {pack.found_by}")
    lines.append("")
    if pack.places:
        described = [p for p in pack.places if p.in_text]
        if pack.shape == "list":   # the top places with their data lines; the rest is on the map
            others = []
        else:
            others = [p for p in pack.places if not p.in_text][:MAX_OTHER_PLACES if described else MAX_PLACES_LISTED]
        lines.append(f"PLACES FOUND: {len(pack.places)} (all are shown on the map; cite them by number)")
        for p in described + others:
            detail = f"{p.kind}" + (f"; {p.address}" if p.address else "")
            why = f" — {p.why}" if p.why and pack.shape == "list" else ""
            warn = f"  [the graph's point for this place may be wrong: {p.uncertain}]" if p.uncertain else ""
            no_text = "  (on the map; no passage here)" if described and not p.in_text else ""
            lines.append(f"[{p.number}] {p.label} ({detail}){why}{warn}{no_text}")
        if len(pack.places) > len(described) + len(others):
            lines.append(f"... and {len(pack.places) - len(described) - len(others)} more places on the map")
        lines.append("")
    if pack.regions:
        lines.append("BY REGION (from the graph's place hierarchy):")
        lines += _region_lines(pack.regions)
        lines.append("")
    if pack.entities:
        top = pack.entities[:10]
        lines.append(f"PEOPLE AND ORGANIZATIONS FOUND: {len(pack.entities)}"
                     + (f" (top {len(top)} listed)" if len(pack.entities) > len(top) else ""))
        lines += [f"- {e.id} ({e.type}, {e.records} links" + (f", {e.role}" if e.role else "") + ")" for e in top]
        lines.append("")
    if pack.passages:
        lines.append("PASSAGES FROM THE CORPUS:")
        for p in pack.passages:
            where = f'"{p.article}"' + (f" › {p.section}" if p.section else "")
            tag = "summary of " + where if p.kind == "summary" else f"about {', '.join(p.about)}; {where}"
            low = "; LOW-CONFIDENCE relation" if p.low_confidence else ""
            lines.append(f"[{p.id}] ({tag}{low}) {p.text}")
    else:
        lines.append("PASSAGES FROM THE CORPUS: none")
    if pack.notes:
        lines += ["", "NOTES: " + " · ".join(pack.notes)]
    return "\n".join(lines)
