"""① Understand: turn a question into a plan the code can execute.

The LLM reads only the question (plus the map selection and a short chat summary), never graph
data. A plan is built in one of three ways, tried in order:
  1. fast path         - code recognizes an obvious pattern ("Where is X?"); no LLM call
  2. LLM               - one structured call (PlanDraft); code then applies the rules in _finalize
  3. keyword fallback  - simple keyword rules, used when the LLM call fails, so a question never
                         dies here
The reasons behind each rule are in DECISIONS_LOG.md (P2-7, P2-21 to P2-25).
"""
import logging
import re
from typing import Literal, Optional

import openai
from langchain_core.exceptions import OutputParserException
from pydantic import BaseModel, Field, ValidationError

from llm_calls import LLMCall, structured_call

logger = logging.getLogger(__name__)

QuestionType = Literal[
    "place_lookup",   # "Where is Dnipro?"
    "entity_places",  # "Show me all locations connected to Zelenskyy"
    "event_places",   # "Locations connected to the Siege of Mariupol"
    "event_list",     # "Major battles of the war"
    "about",          # "Tell me about the head of the Russian military"
    "relation",       # "Who attacked Bakhmut?"
    "area",           # map selection + "anything within 500 m?"
    "area_topic",     # map selection + "drone attacks in this box"
    "common",         # "Countries connected to both Russia and Ukraine"
    "follow_up",      # "show more", "tell me about number 2"
    "out_of_scope",   # unrelated to the corpus
    "other",          # anything else; goes to the LLM tool-loop fallback
]
Needs = Literal["locations", "short_text", "detailed_text"]
PlaceKind = Literal["country", "region", "city", "town", "village", "district"]

# The graph's text relations that a question can ask about (graph README, section 4).
# SAME_AS, CO_OCCURS_WITH, INSIDE and IN_THE_TEXT are left out: no question asks for them.
RELATIONS = {
    "BORN_IN": "was born in / comes from",
    "LOCATED_IN": "lived, worked, served, fought or was present in",
    "VISITED": "visited, travelled to, arrived in",
    "FLED_TO": "fled, emigrated, was deported to",
    "DIED_IN": "died, was killed or buried in",
    "LEADS": "holds office of / leads, heads, commands, founded",
    "MEMBER_OF": "member, employee, soldier, deputy, student of",
    "STATED_ABOUT": "is quoted about / is cited as the source of a claim",
    "OPPOSES": "attacked, criticized, sanctioned, accused, arrested",
    "ATTACKED": "attacked, shelled, invaded, struck",
    "CONTROLS": "controls, captured, occupied, annexed",
    "BASED_IN": "headquartered, based, stationed in",
    "OPERATES_IN": "operates, fought, was deployed in",
    "SUPPORTS": "aid, weapons, funding, political support",
    "PART_OF": "unit/branch of; located inside / part of",
    "NEGOTIATED_WITH": "talks, negotiations, agreements between states",
    "RELATIVE_OF": "family",
    "MET_WITH": "met, talked, negotiated",
    "ALLIED_WITH": "allies, colleagues, cooperated, supported each other",
}

DEFAULT_RADIUS_M = 1000   # P2-23: a map point with no distance given anywhere
HISTORY_TURNS = 3         # P2-25: how many previous turns the LLM sees
HISTORY_PLACES = 20       # places listed per previous turn; "number N" is still resolved from the full list
_NOT_A_KEYWORD = re.compile(r"[\d\s.,°+\-\[\]]+")   # numbers and coordinates are not search words


# --- The plan --------------------------------------------------------------------------------

class EntityMention(BaseModel):
    text: str = Field(description="The name exactly as the user wrote it.")
    name: str = Field(description="The name in its common English Wikipedia spelling "
                                  "(e.g. 'Kharkov' -> 'Kharkiv', 'Zelensky' -> 'Volodymyr Zelenskyy').")
    kind: Literal["PER", "ORG", "LOC", "EVENT", "UNKNOWN"] = Field(
        default="UNKNOWN", description="PER person, ORG organization, LOC place, EVENT battle/attack/siege.")


class ConceptCandidate(BaseModel):
    name: str
    kind: Literal["ORG", "LOC"]


class Concept(BaseModel):
    text: str = Field(description="A thing the question refers to without naming it, "
                                  "e.g. 'the Russian military', 'the Ukrainian government'.")
    candidates: list[ConceptCandidate] = Field(
        default_factory=list,
        description="Names of ORGANIZATIONS or PLACES that could stand for it in a Wikipedia-based "
                    "graph, e.g. 'General Staff', 'Ministry of Defence'. Never a person, and never "
                    "the answer to the question.")


class Area(BaseModel):
    """The user's map selection, in GeoJSON order ([lon, lat])."""
    kind: Literal["point", "polygon"]
    coordinates: list


class FollowUp(BaseModel):
    kind: Literal["more", "item"]
    item_number: Optional[int] = None
    target_id: Optional[str] = None      # the graph id of the item, from the previous result
    target_label: Optional[str] = None


class QueryPlan(BaseModel):
    question: str
    type: QuestionType
    entities: list[EntityMention] = Field(default_factory=list)
    concepts: list[Concept] = Field(default_factory=list)
    relations: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    area: Optional[Area] = None
    radius_m: Optional[float] = None
    radius_source: Optional[Literal["text", "map", "default"]] = None
    place_country: Optional[str] = None            # "Ukrainian cities" -> "Ukraine"
    place_kinds: list[PlaceKind] = Field(default_factory=list)   # "Ukrainian cities" -> ["city"]
    needs: Needs = "short_text"
    time_words: list[str] = Field(default_factory=list)
    follow_up: Optional[FollowUp] = None
    in_scope: bool = True
    source: Literal["fast_path", "llm", "keyword_fallback"]
    notes: list[str] = Field(default_factory=list)
    llm_calls: list[LLMCall] = Field(default_factory=list)   # every call made for this plan, incl. failed ones


# --- What the LLM fills in -------------------------------------------------------------------

class PlanDraft(BaseModel):
    type: QuestionType
    entities: list[EntityMention] = Field(default_factory=list,
        description="Every named person, organization, place or event in the question.")
    concepts: list[Concept] = Field(default_factory=list)
    relations: list[str] = Field(default_factory=list,
        description="Relation names from the list in the instructions that the question asks about.")
    keywords: list[str] = Field(default_factory=list,
        description="Topic words to search the text for, e.g. 'drone', 'missile', 'evacuation'.")
    refers_to_map: bool = Field(default=False,
        description="True if the question is about the user's map selection: 'here', 'this area', "
                    "'this box', 'nearby', or it asks about a place without naming one.")
    radius_m: Optional[float] = Field(default=None,
        description="A distance written in the question, in metres ('within 2 km' -> 2000).")
    place_country: Optional[str] = Field(default=None,
        description="If the question limits the places to one country: 'Ukrainian cities' -> 'Ukraine'.")
    place_kinds: list[PlaceKind] = Field(default_factory=list,
        description="If the question limits the kind of place: 'Ukrainian cities' -> ['city']; "
                    "'oblasts' -> ['region']; 'which countries' -> ['country'].")
    needs: Needs = Field(default="short_text",
        description="locations: only where things are; short_text: a few sentences; "
                    "detailed_text: the user asks for detail.")
    time_words: list[str] = Field(default_factory=list,
        description="Dates or periods in the question, as written ('in 2023', 'since February 2022').")
    follow_up_kind: Optional[Literal["more", "item"]] = Field(default=None,
        description="more: the user wants more of the previous answer; item: the user asks about "
                    "a numbered item from the previous answer.")
    follow_up_item: Optional[int] = Field(default=None, description="The item number, for follow_up_kind=item.")
    in_scope: bool = Field(default=True,
        description="False only if the question has nothing to do with the Russia-Ukraine war, "
                    "the region, its people, organizations, places or history.")


# The examples below are deliberately NOT the project's test questions (eval/questions.json), so the
# test measures how the prompt generalizes rather than whether it memorized the answers (P2-26).
SYSTEM_PROMPT = f"""You are the first step of an agent that answers questions from a knowledge graph
built from Wikipedia articles about the Russia-Ukraine war. Your only job is to describe the
question in the given structure. Do NOT answer it, and do not add facts from your own knowledge.

Question types:
- place_lookup: where a named place is. "Where is Kramatorsk?"
- entity_places: the places connected to a named person or organization. "Show me the places connected to Sergei Shoigu."
- event_places: the places connected to one named event (battle, siege, attack). "Map the places involved in the Battle of Avdiivka."
- event_list: a list of events. "List the main sieges of the war."
- about: information about a person, organization, place, or something described but not named. "Tell me about the Azov Brigade."
- relation: who did what to whom. "Who shelled Kharkiv?" "Who commands the Azov Brigade?"
- area: what is in or near the user's map selection. "What is around this point?"
- area_topic: a topic inside an area (the map selection, or a named place). "Missile strikes inside the selected area."
- common: things connected to two named entities at once. "Which organizations are linked to both Belarus and Russia?"
- follow_up: continues the previous answer. "Next page." "More about the third one."
- out_of_scope: nothing to do with the war, the region, its people or its history. "How do I bake bread?"
- other: none of the above, or a question that needs several steps chained together.

Relations you may list (these exact names):
{chr(10).join(f"- {name}: {meaning}" for name, meaning in RELATIONS.items())}

Rules:
- entities: every proper name in the question (people, organizations, places, named events), even a
  place mentioned in passing ("... in Kherson in 2022"). Write each in its common English Wikipedia
  spelling and keep the user's original text. Descriptions such as "Ukrainian cities", "the army" or
  "Russian generals" are NOT entities.
- concepts: something the question refers to without naming it ("the commander of the Ukrainian
  navy"). Give candidate ORGANIZATION or PLACE names that could stand for it. Never a person's name,
  and never the answer.
- relations: only when the question asks about a specific kind of link. "head of", "leader of",
  "commander of", "in charge of" mean LEADS. Words like "connected", "associated", "linked",
  "related" or "mentioned" ask for no specific relation, so leave relations empty.
- keywords: topic words to search the text for ("missile", "evacuation"). Never names, numbers or
  coordinates.
- place_country / place_kinds: only when the question limits which places count ("Ukrainian cities",
  "towns in Belarus", "which countries").
- refers_to_map: true only when the question is about the map selection ("here", "this area",
  "the selected area", "around this point"). A question that names its own place is about that place.
- Never list examples of what the question asks for: no battles for "major battles", no cities for
  "Ukrainian cities", no countries for "which countries". Finding those is the graph's job.
- Always fill in the structure, even for an unrelated question (type out_of_scope, in_scope false).

Examples:
- "Who shelled Kharkiv?" -> type relation; entities Kharkiv (LOC); relations ATTACKED.
- "Tell me about the commander of the Ukrainian navy." -> type about; concepts "the Ukrainian navy"
  with candidates Ukrainian Navy (ORG), Ministry of Defence of Ukraine (ORG); relations LEADS.
- "Missile strikes inside the selected area in 2024" -> type area_topic; refers_to_map true;
  keywords missile, strike; relations ATTACKED; time_words "in 2024".
- "Shelling in Kherson" (with a map selection somewhere else) -> type area_topic; entities Kherson (LOC);
  refers_to_map false; keywords shelling; relations ATTACKED.
- "Which organizations are linked to both Belarus and Russia?" -> type common; entities Belarus (LOC),
  Russia (LOC); relations empty.
- "Who is the prime minister of Poland?" -> type relation; entities Poland (LOC); relations LEADS.
  (A role "of" a named place or organization is a LEADS question about that name.)
- "Belarusian towns visited by Lukashenko" -> type entity_places; entities Alexander Lukashenko (PER);
  relations VISITED; place_country Belarus; place_kinds town.
- "How do I bake bread?" -> type out_of_scope; in_scope false."""


# --- Building the plan -----------------------------------------------------------------------

def understand(question: str, area: Optional[Area] = None, history: Optional[list[dict]] = None,
               llm=None, map_radius_m: Optional[float] = None) -> QueryPlan:
    """Turn one question into a QueryPlan.

    area          the user's map selection, or None
    map_radius_m  the radius the UI sent with a map point, if any
    history       [{"query": ..., "response": <a previous result dict>}, ...]
    llm           a chat model; if None, only the fast path and the keyword fallback are used
    """
    question = question.strip()
    history = history or []
    plan = fast_path(question, area)
    if plan is None:
        if llm is None:
            plan = keyword_plan(question, area, history, reason="no LLM available")
        else:
            calls: list[LLMCall] = []
            for attempt in (1, 2):   # the free router picks a model per call; a retry often works
                try:
                    draft, call = structured_call(llm, PlanDraft, _messages(question, area, history, map_radius_m),
                                                  step="understand")
                    calls.append(call)
                    if draft is not None:
                        plan = _finalize(draft, question, area, history, map_radius_m)
                        break
                    reason = "LLM returned no usable plan twice"
                except (ValidationError, OutputParserException, ValueError) as e:
                    reason = f"LLM plan failed twice: {type(e).__name__}"
                except openai.APIError as e:   # rate limit, network: retrying right away won't help
                    reason = f"LLM call failed: {type(e).__name__}"
                    break
                logger.info("understand: attempt %d gave no usable plan", attempt)
            if plan is None:
                logger.warning("understand: %s, using keyword fallback", reason)
                plan = keyword_plan(question, area, history, reason=reason)
            plan.llm_calls = calls
    if plan.type not in ("follow_up", "out_of_scope"):
        apply_role_pattern(plan)
    if plan.source != "llm":   # the LLM path sets the radius from its own reading of the text
        _set_radius(plan, radius_from_text(question), map_radius_m)
    logger.debug("plan: %s", plan.model_dump_json(exclude_none=True))
    return plan


def _messages(question, area, history, map_radius_m) -> list:
    return [
        ("system", SYSTEM_PROMPT),
        ("human", f"Map selection: {_describe_area(area, map_radius_m)}\n"
                  f"Previous turns: {summarize_history(history)}\n\n"
                  f"Question: {question}"),
    ]


def _finalize(draft: PlanDraft, question: str, area: Optional[Area], history: list[dict],
              map_radius_m: Optional[float] = None) -> QueryPlan:
    """Apply the rules that don't depend on the LLM's judgement."""
    notes = []
    relations = []
    for r in draft.relations:
        name = r.strip().upper().replace(" ", "_")
        if name in RELATIONS and name not in relations:
            relations.append(name)
        elif name not in RELATIONS:
            notes.append(f"ignored unknown relation {r!r}")

    qtype = draft.type if draft.in_scope else "out_of_scope"
    refers_to_map = draft.refers_to_map
    follow_up = None
    if (draft.follow_up_kind or qtype == "follow_up") and not history:
        # Nothing to follow up on, so it's a fresh question ("this bounding box" is not "the last answer").
        qtype = ("area_topic" if draft.keywords or draft.relations else "area") if area is not None else "other"
        refers_to_map = area is not None
        notes.append(f"typed as a follow-up, but there is no previous turn: treated as {qtype}")
    elif draft.follow_up_kind or qtype == "follow_up":
        qtype = "follow_up"
        follow_up = _resolve_follow_up(draft.follow_up_kind or "more", draft.follow_up_item, history, notes)

    entities, concepts = _clean_entities(draft.entities, question, notes)
    concepts = _clean_concepts(list(draft.concepts) + concepts, qtype, draft.needs, notes)

    # P2-22: a named place wins; the map selection is used when the question refers to it.
    named_places = [e.name for e in entities if e.kind in ("LOC", "EVENT")]
    use_map = area is not None and (refers_to_map or (qtype in ("area", "area_topic") and not named_places))
    if area is not None and not use_map:
        if named_places and qtype in ("area", "area_topic"):
            notes.append(f"map selection not used: the question names {', '.join(named_places)}, "
                         f"so its own area is used instead")
        elif named_places:
            notes.append(f"map selection not used: the question names {', '.join(named_places)}")
        else:
            notes.append("map selection not used: the question doesn't refer to it")
    if use_map and qtype == "place_lookup" and not entities:
        qtype = "area"   # "What is here?" asks about the selection, not about a named place

    entity_names = {e.name.lower() for e in entities} | {e.text.lower() for e in entities}
    keywords = [k.strip() for k in draft.keywords
                if k.strip() and not _NOT_A_KEYWORD.fullmatch(k.strip()) and k.strip().lower() not in entity_names]

    plan = QueryPlan(
        question=question, type=qtype, entities=entities, concepts=concepts, relations=relations,
        keywords=list(dict.fromkeys(keywords)),
        area=area if use_map else None,
        place_country=draft.place_country.strip() if draft.place_country else None,
        place_kinds=list(dict.fromkeys(draft.place_kinds)),
        needs="locations" if qtype == "place_lookup" else draft.needs,
        time_words=draft.time_words, follow_up=follow_up, in_scope=draft.in_scope,
        source="llm", notes=notes)
    _set_radius(plan, draft.radius_m or radius_from_text(question), map_radius_m)
    return plan


def _set_radius(plan: QueryPlan, text_radius: Optional[float], map_radius: Optional[float]) -> None:
    """P2-23: a distance in the text wins, then the radius the UI sent, then the default."""
    if text_radius:
        plan.radius_m, plan.radius_source = float(text_radius), "text"
    elif plan.area is not None and plan.area.kind == "point":
        if map_radius:
            plan.radius_m, plan.radius_source = float(map_radius), "map"
        else:
            plan.radius_m, plan.radius_source = float(DEFAULT_RADIUS_M), "default"


# "president of Ukraine" is a question about who LEADS Ukraine, not about an organization called
# "President of Ukraine" (P2-50). A code rule, because models read it both ways.
_ROLE = re.compile(r"\b(?:president|prime minister|premier|head|leader|chief|commander(?:-in-chief)?|mayor|"
                   r"governor|chairman|chairwoman|director|king|queen|ruler)\s+of\s+(?:the\s+)?"
                   r"(?P<name>[A-Z][\w'’\-]*(?:\s+(?:of\s+)?[A-Z][\w'’\-]*)*)")
_AFTER_NAME_OK = {"and", "or", "in", "at", "during", "since", "from", "before", "after", "today", "now",
                  "currently", "then", "who", "which", "was", "is", "were", "are"}


def apply_role_pattern(plan: QueryPlan) -> None:
    """'president / prime minister / head / commander of X' -> X as a name, LEADS as the relation, and
    any concept that only restated the role dropped. 'head of the Russian military' is left alone:
    'Russian military' is a description, not a name (P2-27), and stays a concept."""
    found = []
    for m in _ROLE.finditer(plan.question):
        name = m["name"]
        after = re.match(r"\s*([A-Za-z]+)", plan.question[m.end():])
        if after and after.group(1)[0].islower() and after.group(1) not in _AFTER_NAME_OK:
            continue   # "the Russian military": the capitalized word is an adjective
        if name.lower() in _COUNTRY_ADJECTIVES:
            continue
        found.append((m.group(0), name))
    if not found:
        return
    if "LEADS" not in plan.relations:
        plan.relations.append("LEADS")
    known = {e.name.lower() for e in plan.entities} | {e.text.lower() for e in plan.entities}
    for _, name in found:
        if name.lower() not in known:
            plan.entities.append(EntityMention(text=name, name=name, kind="UNKNOWN"))
    plan.concepts = [c for c in plan.concepts if not any(n.lower() in c.text.lower() for _, n in found)]
    if plan.type not in ("area", "area_topic"):   # e.g. a model typed "president of Ukraine and of Russia" as common
        plan.type = "relation"
    plan.notes.append(f"role question: {'; '.join(p for p, _ in found)} → {', '.join(n for _, n in found)} "
                      f"with LEADS (code rule)")


_DISTANCE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(km|kilomet(?:er|re)s?|m|met(?:er|re)s?)\b", re.I)


def radius_from_text(question: str) -> Optional[float]:
    """A distance written in the question, in metres: 'within 500m' -> 500, '2 km' -> 2000."""
    m = _DISTANCE.search(question)
    if not m:
        return None
    value = float(m.group(1).replace(",", "."))
    return value * 1000 if m.group(2).lower().startswith("k") else value


def _resolve_follow_up(kind, item, history, notes) -> FollowUp:
    follow_up = FollowUp(kind=kind, item_number=item)
    if not history:
        notes.append("follow-up question, but there is no previous turn")
        return follow_up
    if kind == "item" and item:
        locations = _response_of(history[-1]).get("geo_locations", [])
        # Results carry each place's number (all places, not only those in the text), so "number 13"
        # finds place 13 on the map; older results without numbers fall back to the position.
        target = next((g for g in locations if g.get("number") == item), None)
        if target is None and 1 <= item <= len(locations) and "number" not in locations[0]:
            target = locations[item - 1]
        if target:
            follow_up.target_id, follow_up.target_label = target.get("id"), target.get("label")
        else:
            notes.append(f"the previous answer has no item number {item}")
    return follow_up


PLACE_SEEKING = {"place_lookup", "entity_places", "event_places", "event_list", "area", "area_topic", "common"}
MAX_CANDIDATES = 3


def _norm(s: str) -> str:
    return " ".join(s.lower().replace("’", "'").replace("–", "-").split())


def _is_description(name: str) -> bool:
    """'Russian military commanders' is a description; 'Siege of Mariupol' and 'Dnipro' are names."""
    words = [w.strip(".,;:()'\"") for w in name.split()]
    return any(w and w[0].islower() and w not in _CONNECTORS and not w.startswith("'s") for w in words)


def _clean_entities(entities: list[EntityMention], question: str, notes: list[str]):
    """P2-27: names must come from the question. Returns (entities, concepts made from descriptions)."""
    q = _norm(question)
    by_text: dict[str, list[EntityMention]] = {}
    for e in entities:
        e = EntityMention(text=e.text.strip(), name=e.name.strip(), kind=e.kind)
        if e.name and e.name.lower() not in {x.name.lower() for g in by_text.values() for x in g}:
            by_text.setdefault(_norm(e.text), []).append(e)
    kept, concepts = [], []
    for text, group in by_text.items():
        names = ", ".join(e.name for e in group)
        if not text or text not in q:
            notes.append(f"dropped {names}: not in the question")
        elif len(group) > 1:   # one phrase turned into several names = the LLM's own list
            notes.append(f"dropped {names}: the LLM's expansion of {group[0].text!r}")
            concepts.append(Concept(text=group[0].text))
        elif _is_description(group[0].name):
            notes.append(f"{group[0].text!r} is a description, not a name: moved to concepts")
            concepts.append(Concept(text=group[0].text))
        else:
            kept.append(group[0])
    return kept, concepts


def _clean_concepts(concepts: list[Concept], qtype: str, needs: str, notes: list[str]) -> list[Concept]:
    """P2-27: the LLM may suggest the subject (an organization), never the answer set (the places)."""
    asks_for_places = qtype in PLACE_SEEKING or needs == "locations"
    out = []
    for c in concepts:
        candidates = c.candidates
        if asks_for_places and any(x.kind == "LOC" for x in candidates):
            notes.append(f"dropped place candidates for {c.text!r}: the places must come from the graph")
            candidates = [x for x in candidates if x.kind != "LOC"]
        out.append(Concept(text=c.text, candidates=candidates[:MAX_CANDIDATES]))
    return out


# --- Fast path (no LLM) ----------------------------------------------------------------------

_CONNECTORS = {"of", "the", "de", "del", "la", "le", "al", "on", "upon", "and", "na", "pod"}
_WHERE = re.compile(r"^\s*where\s+(?:is|are|was|were)\s+(?:the\s+)?(?P<name>.+?)\s*[?.!]*\s*$", re.I)
_PLACES_OF = re.compile(
    r"^\s*(?:show\s+me\s+)?(?:all\s+)?(?:the\s+)?(?:locations|places)\s+"
    r"(?:connected\s+to|associated\s+with|linked\s+to|related\s+to)\s+(?:the\s+)?(?P<name>.+?)\s*[?.!]*\s*$", re.I)
_EVENT_NAME = re.compile(r"^(?:Battle|Siege|Offensive|Invasion|Massacre|Bombing|Capture|Liberation|"
                         r"Occupation|Annexation)\s+of\b", re.I)


def _looks_like_name(s: str) -> bool:
    """Conservative: 1-6 words, the first capitalized, the rest capitalized or connectors.
    'Kryvyi Rih' and 'Siege of Mariupol' pass; 'Bakhmut attacked from' does not."""
    words = s.split()
    if not 1 <= len(words) <= 6 or not words[0][:1].isupper():
        return False
    return all(w[:1].isupper() or w[:1].isdigit() or w.lower() in _CONNECTORS for w in words)


def fast_path(question: str, area: Optional[Area]) -> Optional[QueryPlan]:
    """Plans for obvious patterns, with no LLM call. Returns None if the question isn't one."""
    m = _WHERE.match(question)
    if m and _looks_like_name(m["name"]):
        name = m["name"].strip()
        notes = ["map selection not used: the question names a place"] if area else []
        return QueryPlan(question=question, type="place_lookup", needs="locations",
                         entities=[EntityMention(text=name, name=name, kind="LOC")],
                         source="fast_path", notes=notes)
    m = _PLACES_OF.match(question)
    if m and _looks_like_name(m["name"]):
        name = m["name"].strip()
        is_event = bool(_EVENT_NAME.match(name))
        notes = ["map selection not used: the question names what to look for"] if area else []
        return QueryPlan(question=question, type="event_places" if is_event else "entity_places",
                         needs="locations",
                         entities=[EntityMention(text=name, name=name, kind="EVENT" if is_event else "UNKNOWN")],
                         source="fast_path", notes=notes)
    return None


# --- Keyword fallback (no LLM) ---------------------------------------------------------------

_KEYWORD_RELATIONS = [
    (r"\battack|\bstrik|\bshell|\bbomb|\bmissile|\bdrone|\binvad", "ATTACKED"),
    (r"\bcontrol|\bcaptur|\boccup|\bannex", "CONTROLS"),
    (r"\blead|\bhead\b|\bcommand|\bchief\b|\bfounded", "LEADS"),
    (r"\bvisit|\btravel", "VISITED"),
    (r"\bbased\b|\bheadquarter|\bstationed", "BASED_IN"),
    (r"\bfought\b|\bdeployed|\boperat", "OPERATES_IN"),
    (r"\bborn\b", "BORN_IN"),
    (r"\bdied\b|\bkilled\b|\bburied\b", "DIED_IN"),
    (r"\bmet\b|\bmeeting", "MET_WITH"),
    (r"\bnegotiat|\btalks\b|\bagreement", "NEGOTIATED_WITH"),
    (r"\bsupport|\baid\b|\bweapons\b", "SUPPORTS"),
]
_TOPIC_WORDS = ["drone", "missile", "airstrike", "shelling", "battle", "siege", "offensive", "evacuation",
                "refugee", "massacre", "occupation", "sanction", "protest", "explosion", "attack"]
_CAPITALIZED = re.compile(r"\b([A-Z][\w'’-]+(?:\s+(?:of|the|de|on)?\s*[A-Z][\w'’-]+)*)")
_QUESTION_WORDS = {"Where", "What", "Who", "Which", "When", "Show", "Tell", "How", "Is", "Are", "Was",
                   "Were", "Do", "Does", "Did", "Can", "Could", "List", "Give", "Find", "Anything", "The", "I", "Me"}
_COUNTRY_ADJECTIVES = {"ukrainian": "Ukraine", "russian": "Russia", "belarusian": "Belarus",
                       "polish": "Poland", "moldovan": "Moldova"}
_PLACE_KIND_WORDS = {"cities": "city", "city": "city", "towns": "town", "town": "town", "villages": "village",
                     "village": "village", "oblasts": "region", "regions": "region", "countries": "country"}
# Ordinary words that are capitalized only because they start the sentence (compared without a final "s").
_COMMON_STARTS = {w.rstrip("s") for w in _TOPIC_WORDS} | {"location", "place", "countrie", "citie", "town",
                                                          "village", "anything", "something", "all", "major"}


def keyword_plan(question: str, area: Optional[Area], history: list[dict], reason: str) -> QueryPlan:
    q = question.lower()
    notes = [f"keyword fallback ({reason})"]
    relations = []
    for pattern, rel in _KEYWORD_RELATIONS:
        if re.search(pattern, q) and rel not in relations:
            relations.append(rel)
    keywords = [w for w in _TOPIC_WORDS if w in q]
    names = []
    for m in _CAPITALIZED.finditer(question):
        words = m.group(1).split()
        if m.start() == 0 and words[0].lower().rstrip("s") in _COMMON_STARTS:
            words = words[1:]   # capitalized only because it starts the sentence ("Drone attacks in ...")
        if words and words[0] not in _QUESTION_WORDS:
            names.append(" ".join(words))
    entities = [EntityMention(text=n, name=n) for n in dict.fromkeys(names)]
    where = _WHERE.match(question)
    if where and not entities and len(where["name"].split()) <= 4:   # "where is dnipro": keep lower case names
        entities = [EntityMention(text=where["name"], name=where["name"].title(), kind="LOC")]

    follow_up = None
    item = re.search(r"\bnumber\s+(\d+)\b|#(\d+)", q)
    if item or re.fullmatch(r"\s*(show\s+)?(me\s+)?(more|next)( please)?[.!?]*\s*", q):
        qtype = "follow_up"
        follow_up = _resolve_follow_up("item" if item else "more",
                                       int(item.group(1) or item.group(2)) if item else None, history, notes)
    elif area is not None and not entities:
        qtype = "area_topic" if keywords else "area"
    elif q.startswith("where"):
        qtype = "place_lookup"
    elif re.search(r"\b(locations|places|map)\b", q) and entities:
        qtype = "entity_places"
    elif re.match(r"\s*(tell me about|who is|who was|what is|what was)\b", q) and (entities or keywords):
        qtype = "about"
    elif re.match(r"\s*who\b", q) and relations:
        qtype = "relation"
    else:
        qtype = "other"   # without the LLM we can't tell "unrelated" from "complex"; the graph decides
    country = next((c for adj, c in _COUNTRY_ADJECTIVES.items() if re.search(rf"\b{adj}\b", q)), None)
    kinds = [k for word, k in _PLACE_KIND_WORDS.items() if re.search(rf"\b{word}\b", q)]
    return QueryPlan(question=question, type=qtype, entities=entities, relations=relations, keywords=keywords,
                     area=area if qtype in ("area", "area_topic") else None,
                     place_country=country if kinds else None, place_kinds=list(dict.fromkeys(kinds)),
                     needs="locations" if qtype == "place_lookup" else "short_text",
                     follow_up=follow_up, source="keyword_fallback", notes=notes)


# --- Helpers ---------------------------------------------------------------------------------

def _response_of(turn) -> dict:
    response = turn.get("response") if isinstance(turn, dict) else getattr(turn, "response", None)
    if response is None:
        return {}
    return response if isinstance(response, dict) else response.model_dump()


def summarize_history(history: list) -> str:
    """P2-25: the last few questions, and the numbered places each answer showed - not whole answers."""
    if not history:
        return "none"
    lines = []
    for turn in history[-HISTORY_TURNS:]:
        query = turn.get("query") if isinstance(turn, dict) else getattr(turn, "query", "")
        places = _response_of(turn).get("geo_locations", [])
        labels = [f"{g.get('number', i)}. {g.get('label')}" for i, g in enumerate(places[:HISTORY_PLACES], 1)]
        more = f" (+{len(places) - HISTORY_PLACES} more on the map)" if len(places) > HISTORY_PLACES else ""
        lines.append(f"Q: {query} | places shown: {', '.join(labels) + more if labels else 'none'}")
    return "\n".join(lines)


def _describe_area(area: Optional[Area], map_radius_m: Optional[float]) -> str:
    if area is None:
        return "none"
    if area.kind == "point":
        radius = f", radius {map_radius_m:g} m" if map_radius_m else ""
        return f"a point at [lon, lat] {area.coordinates}{radius}"
    return "a polygon (area) drawn on the map"
