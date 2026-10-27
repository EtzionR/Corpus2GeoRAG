"""③ Retrieve: pick the route for the question type and run its graph tools. No LLM.

A route is a fixed recipe of tools (DECISIONS_LOG P2-2). It returns what it found - places for the
map, people and organizations, specific relation records, and summary paragraphs to read - each with
pointers into the text. Nothing is cut: everything found is kept and counted; step ④ chooses how
much of it the LLM reads.

Question types without a route yet (compound questions, follow-ups) go to the LLM tool-loop
fallback, which isn't built yet; the result says so.
"""
import time
from typing import Optional

from pydantic import BaseModel, Field

import graph_tools as T
from graph_index import GraphIndex, Group
from planner import QueryPlan
from resolver import Resolution

WIDEN_STEPS_M = [2000, 5000]    # P2-23: if nothing is within the radius, widen and say so
MAX_SUMMARIES = 4


class ToolStep(BaseModel):
    tool: str
    params: dict = Field(default_factory=dict)
    found: str = ""
    seconds: float = 0.0


class Summary(BaseModel):
    article: str
    about: str                       # the group id or event it summarizes
    pointer: T.Pointer
    preview: str = ""                # the paragraph's opening words, for reading the trace


class Retrieval(BaseModel):
    route: str
    steps: list[ToolStep] = Field(default_factory=list)
    places: list[T.Hit] = Field(default_factory=list)       # for the map: everything found, ranked
    entities: list[T.Hit] = Field(default_factory=list)     # people / organizations, ranked
    records: list[T.Record] = Field(default_factory=list)   # specific relation records (who LEADS, who ATTACKED)
    summaries: list[Summary] = Field(default_factory=list)  # lead paragraphs worth reading
    area_used: Optional[dict] = None                         # the area searched, after any widening
    notes: list[str] = Field(default_factory=list)
    seconds: float = 0.0


class _Run:
    """Runs tools and records each call for the trace."""

    def __init__(self, route: str):
        self.out = Retrieval(route=route)

    def call(self, tool: str, fn, describe, **params):
        start = time.time()
        result = fn()
        self.out.steps.append(ToolStep(tool=tool, params=params, found=describe(result),
                                       seconds=round(time.time() - start, 3)))
        return result

    def summary(self, gi: GraphIndex, article: Optional[str], about: str) -> None:
        if article and len(self.out.summaries) < MAX_SUMMARIES and all(s.article != article for s in self.out.summaries):
            pointer = T.lead_pointer(gi, article)
            text = gi.text(pointer.text_id)["text"]
            self.out.summaries.append(Summary(article=article, about=about, pointer=pointer,
                                              preview=text[:160] + ("…" if len(text) > 160 else "")))


def _n(items, what="items") -> str:
    return f"{len(items)} {what}"


# --- The router ------------------------------------------------------------------------------

def retrieve(plan: QueryPlan, res: Resolution, gi: GraphIndex) -> Retrieval:
    start = time.time()
    route = {"place_lookup": _place_lookup, "area": _area, "area_topic": _area_topic, "about": _about,
             "relation": _about, "entity_places": _entity_places, "event_places": _event_places,
             "event_list": _event_list, "common": _common, "follow_up": _about}.get(plan.type)
    if route is None:
        out = Retrieval(route="none")
        out.notes.append(f"question type {plan.type!r} has no fixed route; it goes to the LLM tool-loop "
                         f"fallback, which isn't built yet")
    else:
        out = route(plan, res, gi)
    if plan.type in LIST_ROUTE_TYPES and out.places:
        out.places = T.tiered(out.places)   # specific places first, then regions, then countries (P2-53)
    out.seconds = round(time.time() - start, 2)
    return out


LIST_ROUTE_TYPES = {"entity_places", "event_places", "event_list", "area", "area_topic", "common"}


def _groups(res: Resolution, types: Optional[set] = None) -> list[Group]:
    return [e.group for e in res.entities if e.group and (not types or e.group.type in types)]


def _articles(res: Resolution) -> list[str]:
    return [e.article.title for e in res.entities if e.article]


def _concept_groups(res: Resolution) -> list[Group]:
    return [c.group for rc in res.concepts for c in rc.candidates if c.group]


# --- Routes ----------------------------------------------------------------------------------

def _place_lookup(plan, res, gi) -> Retrieval:
    run = _Run("place_lookup: locate each named place")
    for g in _groups(res):
        if not g.place:
            run.out.notes.append(f"{g.id} has no coordinates in the graph")
            continue
        chain = run.call("parents", lambda: T.parents(gi, g.place.from_name),
                         lambda c: " → ".join(c), place=g.place.from_name)
        run.out.places.append(T.Hit(group=g, records=g.texts))
        run.out.notes.append(f"{g.id} is inside: {' → '.join(chain[1:]) or 'nothing larger in the graph'}")
        if g.place.uncertain:
            run.out.notes.append(f"{g.id}'s point is uncertain: {g.place.uncertain_reason}")
        run.summary(gi, g.own_article, g.id)
    if not run.out.places and _articles(res):
        run.out.notes.append("the name is an event (an article), not a place: see event_places")
    return run.out


def _search_area(plan, res, gi, run) -> list[T.Hit]:
    """The map selection, or a named place's own polygon / point (P2-22), with widening for points."""
    named = [g for g in _groups(res, {"LOC"}) if g.place]
    if plan.area is None and named:
        g = named[0]
        shape = T.shape_of(gi, g)
        if shape:
            run.out.area_used = {"from": g.id, "type": shape["type"]}
            return run.call("places_within", lambda: T.places_within(gi, shape), lambda h: _n(h, "places"),
                            area=f"{g.id}'s polygon")
        plan_point, radius = [g.place.lon, g.place.lat], plan.radius_m or 5000
        run.out.notes.append(f"{g.id} has no polygon; using {radius:g} m around its point")
    elif plan.area is not None and plan.area.kind == "polygon":
        shape = {"type": "Polygon", "coordinates": plan.area.coordinates}
        run.out.area_used = {"from": "map", "type": "Polygon"}
        return run.call("places_within", lambda: T.places_within(gi, shape), lambda h: _n(h, "places"),
                        area="the map polygon")
    elif plan.area is not None:
        plan_point, radius = plan.area.coordinates, plan.radius_m or 1000
    else:
        run.out.notes.append("no area: no map selection and no named place with coordinates")
        return []
    lon, lat = plan_point
    for r in [radius] + [w for w in WIDEN_STEPS_M if w > radius]:
        hits = run.call("places_near", lambda: T.places_near(gi, lon, lat, r), lambda h: _n(h, "places"),
                        point=[lon, lat], radius_m=r)
        if hits:
            run.out.area_used = {"from": "point", "point": [lon, lat], "radius_m": r}
            if r != radius:
                run.out.notes.append(f"nothing within {radius:g} m; widened to {r:g} m")
            return hits
    run.out.area_used = {"from": "point", "point": [lon, lat], "radius_m": WIDEN_STEPS_M[-1]}
    run.out.notes.append(f"no places within {max(radius, WIDEN_STEPS_M[-1]):g} m")
    return []


def _area(plan, res, gi) -> Retrieval:
    run = _Run("area: places in the area, and the paragraphs that mention them")
    hits = _search_area(plan, res, gi, run)
    for h in hits:
        ptrs = T.mentions(gi, h.group.id)
        h.records, h.pointers, h.pointers_total = len(ptrs), ptrs[:T.MAX_POINTERS], len(ptrs)
    if not plan.area or plan.area.kind != "point":
        hits.sort(key=lambda h: -h.records)
    run.out.places = hits
    return run.out


# Words that, in a war corpus, match almost everything; ignored when a more specific word is given
# ("drone attacks" searches for "drone", not for every "attack").
GENERIC_TOPIC_WORDS = {"attack", "attacks", "strike", "strikes", "war", "battle", "battles", "fighting", "fight",
                       "operation", "operations", "conflict", "military", "location", "locations", "place", "places",
                       "event", "events", "incident", "incidents", "activity"}


def topic_words(keywords: list[str]) -> list[str]:
    specific = [k for k in keywords if k.lower() not in GENERIC_TOPIC_WORDS]
    return specific or keywords


def _area_topic(plan, res, gi) -> Retrieval:
    run = _Run("area_topic: places in the area × paragraphs about the topic")
    hits = _search_area(plan, res, gi, run)
    keywords = topic_words(plan.keywords)
    if keywords != plan.keywords:
        run.out.notes.append(f"searching for {', '.join(keywords)}; ignoring the generic "
                             f"{', '.join(k for k in plan.keywords if k not in keywords)}")
    if not keywords and not plan.relations:
        run.out.notes.append("no keywords or relations to filter by: every place in the area kept")
        run.out.places = hits
        return run.out
    found = []
    for h in hits:
        rel_recs = T.entity_records(gi, h.group.id, plan.relations) if plan.relations else []
        if keywords:   # the topic decides which paragraphs count; the relation only ranks (P2-43)
            ptrs = []
            for p in T.mentions(gi, h.group.id):
                kw = T.keyword_spans(gi.text(p.text_id)["text"], keywords)
                if kw:
                    ptrs.append(T.Pointer(text_id=p.text_id, spans=sorted(p.spans + kw)))
            matched = {p.text_id for p in ptrs}
            rel_recs = [r for r in rel_recs if r.pointer.text_id in matched]
        else:          # no topic words: the relation records are the topic
            ptrs = [r.pointer for r in rel_recs]
        ptrs = T._unique_pointers(ptrs)
        if ptrs:
            h.records, h.pointers, h.pointers_total = len(ptrs), ptrs[:T.MAX_POINTERS], len(ptrs)
            if rel_recs:
                h.relations = {rel: sum(1 for r in rel_recs if r.relation == rel) for rel in plan.relations}
            h.score = len(ptrs) + 2 * len(rel_recs)
            found.append(h)
    run.out.steps.append(_filter_step("topic filter", {"keywords": keywords, "relations (rank only)": plan.relations},
                                      f"{len(found)} of {len(hits)} places have matching paragraphs"))
    found.sort(key=lambda h: (-h.score, -h.group.texts))
    run.out.places = found
    return run.out


def _filter_step(tool, params, found) -> ToolStep:
    return ToolStep(tool=tool, params=params, found=found)


EXPAND_TO = 3     # P2-45 (b): how many of the most-linked organizations to search when a relation finds nothing
LOW_CONFIDENCE_FLOOR = 0.4   # P2-45 (a): the lowest classifier confidence accepted, labelled, as a last resort


def _relation_records(run, gi, targets: list[Group], rels: list[str]) -> list:
    """Records of the asked relation; if none, the fallback of P2-45 (c): (b) the organizations most
    linked to the targets, then (a) lower-confidence records, labelled low_confidence."""
    def search(groups, min_conf, label):
        found = []
        for g in groups:
            found += run.call("entity_records", lambda: T.entity_records(gi, g.id, rels, min_confidence=min_conf),
                              lambda r: _n(r, "records"), entity=g.id, relations=rels,
                              min_confidence=min_conf, why=label)
        return found

    records = search(targets, T.MIN_CONFIDENCE, "asked")
    if records:
        return records
    target_ids = {g.id for g in targets}
    linked = []
    for g in targets:
        orgs = T.aggregate(gi, T.entity_records(gi, g.id, other_types={"ORG"}), set(gi.groups[g.id]))
        linked += [h.group for h in orgs if h.group.id not in target_ids][:EXPAND_TO]
    linked = list({g.id: g for g in linked}.values())
    run.out.notes.append(f"no confident {', '.join(rels)} records; also searching the organizations most "
                         f"linked to them: {', '.join(g.id for g in linked) or 'none'}")
    records = search(linked, T.MIN_CONFIDENCE, "expanded")
    if records:
        return records
    records = search(targets + linked, LOW_CONFIDENCE_FLOOR, "low-confidence fallback")
    if records:
        run.out.notes.append(f"only low-confidence {', '.join(rels)} records exist (classifier confidence "
                             f"{LOW_CONFIDENCE_FLOOR}–{T.MIN_CONFIDENCE}); they are labelled so the answer can say so")
    return records


def _interleave(per_target: list[list[T.Hit]]) -> list[T.Hit]:
    """Round-robin across targets, so "presidents of Ukraine and Russia" doesn't list two of one first."""
    out, seen = [], set()
    for rank in range(max((len(x) for x in per_target), default=0)):
        for hits in per_target:
            if rank < len(hits) and hits[rank].group.id not in seen:
                seen.add(hits[rank].group.id)
                out.append(hits[rank])
    return out


def _drilldown(plan, gi, actor: Group, place: Group) -> Retrieval:
    """One entity at one place ("Zelenskyy in the White House"): only the records linking the two."""
    run = _Run(f"drill-down: what links {actor.id} and {place.id}")
    between = run.call("records_between", lambda: [r for r in T.entity_records(gi, actor.id) if r.other == place.id],
                       lambda r: _n(r, "records"), entity=actor.id, place=place.id)
    if plan.relations and any(r.relation in plan.relations for r in between):
        between = [r for r in between if r.relation in plan.relations]
    between.sort(key=lambda r: (r.relation == "MENTIONED_WITH", -(r.confidence or 0)))
    run.out.records = between
    if between:
        rel_counts: dict[str, int] = {}
        for r in between:
            rel_counts[r.relation] = rel_counts.get(r.relation, 0) + 1
        pointers = T._unique_pointers([r.pointer for r in between])
        run.out.places = [T.Hit(group=place, records=len(between), relations=rel_counts,
                                pointers=pointers[:T.MAX_POINTERS], pointers_total=len(pointers))]
        run.out.entities = [T.Hit(group=actor, records=len(between), relations=rel_counts)]
    else:
        run.out.notes.append(f"no paragraph links {actor.id} and {place.id}")
    run.summary(gi, place.own_article, place.id)
    run.summary(gi, actor.own_article, actor.id)
    return run.out


def _about(plan, res, gi) -> Retrieval:
    run = _Run("about / relation: what the graph links to the entity (by relation, if one is asked)")
    targets = list({g.id: g for g in _groups(res) + _concept_groups(res)}.values())   # each group once
    if not targets:
        run.out.notes.append("nothing resolved to look up")
        return run.out
    actors = [g for g in targets if g.type in ("PER", "ORG")]
    places = [g for g in targets if g.type == "LOC"]
    if len(targets) == 2 and len(actors) == 1 and len(places) == 1:   # a drill-down (P2-49)
        return _drilldown(plan, gi, actors[0], places[0])
    if plan.type == "follow_up" and plan.follow_up and plan.follow_up.kind == "more":
        run.out.notes.append("'show more' needs paging, which isn't built yet")
    rels = plan.relations or None
    if rels:
        all_records = _relation_records(run, gi, targets, rels)
    else:
        all_records = []
        for g in targets:
            all_records += run.call("entity_records", lambda: T.entity_records(gi, g.id), lambda r: _n(r, "records"),
                                    entity=g.id, relations="all")
    per_target = []
    for tid in dict.fromkeys(r.target for r in all_records):
        recs = [r for r in all_records if r.target == tid]
        per_target.append(T.aggregate(gi, recs, set(gi.groups[tid])))
    hits = _interleave(per_target)
    if rels:   # a "who" question: the record list itself is the answer's backbone
        run.out.records = sorted(all_records, key=lambda r: (r.low_confidence, -(r.confidence or 0)))
    target_ids = {g.id for g in targets}
    run.out.entities = [h for h in hits if h.group.type in ("PER", "ORG") and h.group.id not in target_ids]
    # A place being asked about ("tell me about Kyiv", "number 2") comes first on the map, then what's linked.
    asked = [T.Hit(group=g, records=g.texts) for g in targets if g.place]
    run.out.places = asked + [h for h in hits if h.group.place and h.group.id not in target_ids]
    # For "who" questions, read about the people found (the place asked about only if none of them
    # has an article); otherwise about the entity asked about, then the strongest links.
    if rels:
        people = [h.group for h in run.out.entities[:3]]
        order = people if any(g.own_article for g in people) else people + targets
    else:
        order = targets + [h.group for h in run.out.entities[:2]]
    for g in order:
        run.summary(gi, g.own_article, g.id)
    if not all_records:
        run.out.notes.append("no matching records for " + ", ".join(g.id for g in targets)
                             + (f" with relation {', '.join(rels)}" if rels else ""))
    return run.out


def _entity_places(plan, res, gi) -> Retrieval:
    run = _Run("entity_places: geocoded places linked to the entity in the text")
    if _articles(res) and not _groups(res):
        return _event_places(plan, res, gi)
    for g in _groups(res):
        hits = run.call("connected_places", lambda: T.connected_places(gi, g.id, plan.relations or None,
                                                                       plan.place_kinds or None),
                        lambda h: _n(h, "places"), entity=g.id, relations=plan.relations or "all",
                        place_kinds=plan.place_kinds or "any")
        run.out.places += hits
        run.summary(gi, g.own_article, g.id)
    run.out.places.sort(key=lambda h: (-h.score, -(h.specificity or 0), -h.records))   # P2-44, as in the tool
    return run.out


def _event_places(plan, res, gi) -> Retrieval:
    run = _Run("event_places: the places the event's article mentions")
    for title in _articles(res):
        hits = run.call("article_places", lambda: T.article_places(gi, title), lambda h: _n(h, "places"),
                        article=title)
        run.out.places += hits
        run.summary(gi, title, title)
    if not _articles(res):
        run.out.notes.append("no event article resolved; trying the entity's linked places instead")
        return _entity_places(plan.model_copy(update={"type": "entity_places"}), res, gi)
    return run.out


def _event_list(plan, res, gi) -> Retrieval:
    run = _Run("event_list: event articles whose titles match, each placed by its most-mentioned place")
    words = [k.lower() for k in plan.keywords] or ["battle", "siege"]
    titles = run.call("find_event_articles",
                      lambda: sorted(t for t in gi.articles if any(t.lower().startswith(w) for w in words)),
                      lambda t: _n(t, "articles"), title_starts_with=words)
    for title in titles:
        top = T.article_places(gi, title)[:1]
        if top:
            hit = top[0]
            hit.relations = {f"event: {title}": hit.records}
            run.out.places.append(hit)
            run.summary(gi, title, title)
    run.out.notes.append(f"{len(titles)} event articles found; {len(run.out.places)} could be placed on the map")
    return run.out


def _common(plan, res, gi) -> Retrieval:
    run = _Run("common: what is linked to every named entity")
    targets = _groups(res)
    if len(targets) < 2:
        run.out.notes.append("needs at least two resolved entities")
        return run.out
    kinds = plan.place_kinds or (["country"] if any("countr" in x.lower() for x in
                                                    plan.keywords + [c.text for c in plan.concepts]) else None)
    hits = run.call("common_neighbors", lambda: T.common_neighbors(gi, [g.id for g in targets], {"LOC"}, kinds),
                    lambda h: _n(h, "places"), entities=[g.id for g in targets], place_kinds=kinds or "any")
    if kinds and not plan.place_kinds:
        run.out.notes.append("the question mentions countries: only countries kept")
    run.out.places = hits
    return run.out
