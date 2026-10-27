"""③ The graph tools: plain functions over the loaded graph. No LLM.

Every tool returns what it found as structured items with **pointers** (a paragraph id plus the
character ranges of the entities involved), never raw paragraphs. Step ④ decides how much text to
take around each pointer (DECISIONS_LOG P2-14).

Relation confidence (P2-13): a typed relation (ATTACKED, LEADS, ...) counts as that relation only at
confidence >= 0.7. Below that, and for CO_OCCURS_WITH, the record still proves the two names appear
together, so it counts as MENTIONED_WITH and ranks after the confident ones.
"""
import re
from typing import Literal, Optional

from pydantic import BaseModel, Field

from geo import distance_m, in_shape, parse_wkt
from graph_index import GraphIndex, Group

MIN_CONFIDENCE = 0.7
MAX_POINTERS = 50          # per item; the full count is kept in pointers_total
NOT_RELATIONS = {"IN_THE_TEXT", "INSIDE", "SAME_AS"}

# What the plan's place kinds mean in the graph's place_type values.
PLACE_KINDS = {
    "country": {"country"},
    "region": {"state", "region", "province", "county"},
    "city": {"city"},
    "town": {"town"},
    "village": {"village", "hamlet"},
    "district": {"city_district", "suburb", "borough", "quarter", "district"},
}


class Pointer(BaseModel):
    text_id: int
    spans: list[list[int]] = Field(default_factory=list)   # [start, end) character ranges in the paragraph


class Record(BaseModel):
    """One place in the text where an entity is linked to another."""
    relation: str                       # a confident typed relation, or MENTIONED_WITH
    classifier_label: Optional[str] = None   # the typed label behind a MENTIONED_WITH, if there was one
    subject: Optional[str] = None       # the name that acts; None = symmetric
    target: str                         # group id of the entity we asked about
    other: str                          # group id of the counterpart
    confidence: Optional[float] = None
    low_confidence: bool = False        # a typed relation accepted below MIN_CONFIDENCE (fallback, P2-45)
    pointer: Pointer


class Hit(BaseModel):
    """An entity or place found, with everything that backs it."""
    group: Group
    score: float = 0.0
    records: int = 0                    # how many records / mentions back it
    relations: dict[str, int] = Field(default_factory=dict)
    role: Optional[Literal["acts", "acted_on", "mutual"]] = None   # relative to the entity asked about
    specificity: Optional[float] = None   # share of this item's paragraphs that link to the entity (P2-44)
    distance_m: Optional[float] = None
    pointers: list[Pointer] = Field(default_factory=list)
    pointers_total: int = 0


# --- Records ---------------------------------------------------------------------------------

def entity_records(gi: GraphIndex, gid: str, relations: Optional[list[str]] = None,
                   other_types: Optional[set[str]] = None, min_confidence: float = MIN_CONFIDENCE) -> list[Record]:
    """Every text record linking any name of group `gid` to another entity. With `relations`, only
    records of those relation types at `min_confidence` or above. Lowering `min_confidence` below
    MIN_CONFIDENCE is the labelled fallback of P2-45: those records come back marked low_confidence."""
    names = set(gi.groups[gid])
    out = []
    for name in names:
        for m in gi.G.neighbors(name):
            if gi.G.nodes[m]["type"] == "TEXT" or m in names:
                continue
            other = gi.group_of[m]
            if other_types and gi.G.nodes[other]["type"] not in other_types:
                continue
            for rel, recs in gi.G[name][m]["relations"].items():
                if rel in NOT_RELATIONS:
                    continue
                for r in recs:
                    conf = r.get("confidence")
                    typed = rel != "CO_OCCURS_WITH" and conf is not None and conf >= min_confidence
                    if relations and not (typed and rel in relations):
                        continue
                    out.append(Record(
                        relation=rel if typed else "MENTIONED_WITH",
                        classifier_label=None if typed or rel == "CO_OCCURS_WITH" else rel,
                        subject=r.get("subject"), target=gid, other=other, confidence=conf,
                        low_confidence=typed and conf < MIN_CONFIDENCE,
                        pointer=Pointer(text_id=r["text_id"],
                                        spans=[[r["source_start"], r["source_end"]], [r["target_start"], r["target_end"]]])))
    return out


def aggregate(gi: GraphIndex, records: list[Record], target_names: set[str]) -> list[Hit]:
    """Group records by counterpart, ranked: confident typed records count 3, mentions 1."""
    by_other: dict[str, list[Record]] = {}
    for r in records:
        by_other.setdefault(r.other, []).append(r)
    hits = []
    for other, recs in by_other.items():
        rel_counts: dict[str, int] = {}
        acts = acted_on = 0
        for r in recs:
            rel_counts[r.relation] = rel_counts.get(r.relation, 0) + 1
            if r.subject:
                if r.subject in target_names:
                    acted_on += 1
                else:
                    acts += 1
        typed = sum(n for rel, n in rel_counts.items() if rel != "MENTIONED_WITH")
        role = None
        if acts or acted_on:
            role = "acts" if acts > acted_on else "acted_on" if acted_on > acts else "mutual"
        pointers = _unique_pointers([r.pointer for r in recs])
        hits.append(Hit(group=gi.group(other), score=3 * typed + (len(recs) - typed), records=len(recs),
                        relations=dict(sorted(rel_counts.items(), key=lambda kv: -kv[1])), role=role,
                        pointers=pointers[:MAX_POINTERS], pointers_total=len(pointers)))
    hits.sort(key=lambda h: (-h.score, -h.group.texts))
    return hits


def _unique_pointers(pointers: list[Pointer]) -> list[Pointer]:
    """One pointer per paragraph, with every span found in it."""
    by_text: dict[int, list] = {}
    for p in pointers:
        spans = by_text.setdefault(p.text_id, [])
        for s in p.spans:
            if s not in spans:
                spans.append(s)
    return [Pointer(text_id=t, spans=sorted(s)) for t, s in by_text.items()]


# --- Places ----------------------------------------------------------------------------------

def place_kind_ok(group: Group, kinds: Optional[list[str]]) -> bool:
    if not kinds:
        return True
    allowed = set().union(*(PLACE_KINDS.get(k, {k}) for k in kinds))
    return bool(group.place) and group.place.place_type in allowed


# Relations that put someone or something *at* a place. They rank the places linked to an entity
# (P2-44, option c); STATED_ABOUT ("quoted about Ukraine") or LEADS ("holds office of Ukraine") don't.
PLACE_RELATIONS = {"VISITED", "LOCATED_IN", "BORN_IN", "DIED_IN", "FLED_TO",
                   "BASED_IN", "OPERATES_IN", "ATTACKED", "CONTROLS"}


def connected_places(gi: GraphIndex, gid: str, relations: Optional[list[str]] = None,
                     place_kinds: Optional[list[str]] = None) -> list[Hit]:
    """Geocoded places linked to an entity in the text. Ranked (P2-44): confident place relations
    first, then specificity (how much of the place's text links to the entity), then volume."""
    hits = aggregate(gi, entity_records(gi, gid, relations, other_types={"LOC"}), set(gi.groups[gid]))
    hits = [h for h in hits if h.group.place and place_kind_ok(h.group, place_kinds)]
    for h in hits:
        h.specificity = round(h.records / max(h.group.texts, 1), 3)
        h.score = sum(n for rel, n in h.relations.items() if rel in PLACE_RELATIONS)
    hits.sort(key=lambda h: (-h.score, -h.specificity, -h.records))
    return hits


# P2-53 (decided 2026-10-21): in lists, specific places come before regions, and regions before
# countries and continents. Within a tier, the route's own ranking is kept.
REGIONAL_TYPES = {"state", "region", "province", "county", "peninsula", "archipelago"}
BROAD_TYPES = {"country", "continent", "sea", "ocean", "gulf", "bay", "strait"}


def tier(hit: Hit) -> int:
    """0 specific (town, city, village, street, building...), 1 regional (oblast...), 2 broad (country...)."""
    ptype = hit.group.place.place_type if hit.group.place else None
    return 2 if ptype in BROAD_TYPES else 1 if ptype in REGIONAL_TYPES else 0


def tiered(hits: list[Hit]) -> list[Hit]:
    """Stable: re-orders by tier only, keeping the ranking inside each tier."""
    return sorted(hits, key=tier)


def _located(gi: GraphIndex) -> list[tuple[str, float, float]]:
    """(group id, lon, lat) for every geocoded place group that some paragraph mentions; built once.
    (A place kept only for the hierarchy, P2-61, is not a search result.)"""
    if getattr(gi, "_located_cache", None) is None:
        out = []
        for gid, names in gi.groups.items():
            if gi.G.nodes[gid]["type"] != "LOC" or not gi.group(gid).texts:
                continue
            located = [m for m in names if gi.G.nodes[m].get("latitude") is not None]
            if located:
                m = max(located, key=lambda x: gi.G.nodes[x].get("importance") or 0)
                out.append((gid, gi.G.nodes[m]["longitude"], gi.G.nodes[m]["latitude"]))
        gi._located_cache = out
    return gi._located_cache


def places_near(gi: GraphIndex, lon: float, lat: float, radius_m: float) -> list[Hit]:
    hits = []
    for gid, plon, plat in _located(gi):
        d = distance_m(lon, lat, plon, plat)
        if d <= radius_m:
            hits.append(Hit(group=gi.group(gid), distance_m=round(d)))
    hits.sort(key=lambda h: h.distance_m)
    return hits


def places_within(gi: GraphIndex, shape: dict) -> list[Hit]:
    hits = [Hit(group=gi.group(gid)) for gid, plon, plat in _located(gi) if in_shape(plon, plat, shape)]
    hits.sort(key=lambda h: -h.group.texts)
    return hits


def shape_of(gi: GraphIndex, group: Group) -> Optional[dict]:
    """The polygon of a place group (from the graph's geometry_wkt), if it has one."""
    if not group.place:
        return None
    shape = parse_wkt(gi.G.nodes[group.place.from_name].get("geometry_wkt"))
    return shape if shape and shape["type"] in ("Polygon", "MultiPolygon") else None


def parents(gi: GraphIndex, name: str) -> list[str]:
    """The INSIDE chain: place -> its parent -> ... (from the polygons, not the text)."""
    chain = [name]
    while True:
        up = [m for m in gi.G.neighbors(chain[-1])
              if any(r.get("subject") == chain[-1] for r in gi.G[chain[-1]][m]["relations"].get("INSIDE", []))]
        if not up or up[0] in chain:
            return chain
        chain.append(up[0])


REGION_LEVELS = ("country", "state")   # the levels a region overview groups by (state = oblast)


class RegionNode(BaseModel):
    """One region in the overview of a big list of places (P2-49). Nested: countries hold regions."""
    id: str
    place_type: Optional[str] = None
    count: int = 0                                       # found places anywhere inside it
    places: list[int] = Field(default_factory=list)      # numbers of found places directly in it
    children: list["RegionNode"] = Field(default_factory=list)


def region_tree(gi: GraphIndex, numbered: list[tuple[int, Hit]]) -> list[RegionNode]:
    """Group numbered places by country and region, using the graph's INSIDE hierarchy.
    Places with no larger region in the graph go under "(no region in the graph)"."""
    level_of: dict[str, Optional[str]] = {}

    def level(name: str) -> Optional[tuple[str, str]]:
        gid = gi.group_of.get(name)
        if gid is None:
            return None
        if gid not in level_of:   # the same member the group's displayed point comes from
            place = gi.group(gid).place
            level_of[gid] = place.place_type if place else None
        return (gid, level_of[gid]) if level_of[gid] in REGION_LEVELS else None

    roots: dict[str, dict] = {}
    for number, hit in numbered:
        if not hit.group.place:
            continue
        chain = [level(n) for n in parents(gi, hit.group.place.from_name)]
        # country first; each region once (two names in the chain can belong to one group: Donetsk)
        path = list({c[0]: c for c in reversed(chain) if c}.values())
        if path and path[-1][0] == hit.group.id:                  # the place is itself a region
            path = path[:-1]
        level_dict = roots
        if not path:
            path = [("(no region in the graph)", None)]
        node = None
        for gid, ptype in path:
            node = level_dict.setdefault(gid, {"id": gid, "type": ptype, "count": 0, "places": [], "children": {}})
            node["count"] += 1
            level_dict = node["children"]
        node["places"].append(number)

    def build(d: dict) -> list[RegionNode]:
        nodes = [RegionNode(id=v["id"], place_type=v["type"], count=v["count"], places=v["places"],
                            children=build(v["children"])) for v in d.values()]
        return sorted(nodes, key=lambda n: -n.count)
    return build(roots)


# --- Texts -----------------------------------------------------------------------------------

def mentions(gi: GraphIndex, gid: str) -> list[Pointer]:
    """Every paragraph that mentions any name of the group, with the mention positions."""
    out = []
    for name in gi.groups[gid]:
        for m in gi.G.neighbors(name):
            if gi.G.nodes[m]["type"] == "TEXT":
                recs = gi.G[name][m]["relations"].get("IN_THE_TEXT", [])
                out.append(Pointer(text_id=gi.G.nodes[m]["text_id"], spans=[[r["start"], r["end"]] for r in recs]))
    return _unique_pointers(out)


def keyword_spans(text: str, keywords: list[str]) -> list[list[int]]:
    """Where the keywords occur, matching word starts ('drone' finds 'drones', 'drone-strike')."""
    spans = []
    for k in keywords:
        for m in re.finditer(rf"\b{re.escape(k.lower())}\w*", text.lower()):
            spans.append([m.start(), m.end()])
    return spans


def article_places(gi: GraphIndex, title: str) -> list[Hit]:
    """Geocoded places mentioned in an article, ranked by how many of its paragraphs mention them."""
    by_group: dict[str, list[Pointer]] = {}
    for tid in gi.articles[title]:
        node = f"TEXT_{tid}"
        for m in gi.G.neighbors(node):
            if gi.G.nodes[m]["type"] == "LOC":
                recs = gi.G[node][m]["relations"].get("IN_THE_TEXT", [])
                by_group.setdefault(gi.group_of[m], []).append(
                    Pointer(text_id=tid, spans=[[r["start"], r["end"]] for r in recs]))
    hits = []
    for gid, ptrs in by_group.items():
        g = gi.group(gid)
        if g.place:
            ptrs = _unique_pointers(ptrs)
            hits.append(Hit(group=g, score=len(ptrs), records=len(ptrs), pointers=ptrs[:MAX_POINTERS],
                            pointers_total=len(ptrs)))
    hits.sort(key=lambda h: (-h.records, -h.group.texts))
    return hits


def lead_pointer(gi: GraphIndex, article: str) -> Optional[Pointer]:
    """The article's first paragraph (its summary)."""
    return Pointer(text_id=gi.articles[article][0]) if article in gi.articles else None


def common_neighbors(gi: GraphIndex, gids: list[str], other_types: set[str],
                     place_kinds: Optional[list[str]] = None) -> list[Hit]:
    """Entities linked (in the text) to every group in `gids`, ranked by combined strength."""
    per_target = []
    for gid in gids:
        hits = {h.group.id: h for h in aggregate(gi, entity_records(gi, gid, other_types=other_types),
                                                set(gi.groups[gid]))}
        per_target.append(hits)
    shared = set(per_target[0]).intersection(*per_target[1:]) - set(gids)
    out = []
    for other in shared:
        parts = [t[other] for t in per_target]
        group = parts[0].group
        if place_kinds and not place_kind_ok(group, place_kinds):
            continue
        if "LOC" in other_types and not group.place:
            continue
        pointers = _unique_pointers([p for h in parts for p in h.pointers])
        out.append(Hit(group=group, score=min(h.score for h in parts), records=sum(h.records for h in parts),
                       pointers=pointers[:MAX_POINTERS], pointers_total=sum(h.pointers_total for h in parts)))
    out.sort(key=lambda h: (-h.score, -h.records))
    return out
