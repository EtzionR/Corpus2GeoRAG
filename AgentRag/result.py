"""⑥ Result: the JSON the UI receives. No LLM; everything comes from the graph and the earlier steps.

Every place found goes in, numbered exactly as the answer cites it ([3] is place number 3), with its
point, its data line and its paragraph pointers. The places the answer discusses ("primary") also get
their outline - the graph's polygon or line, simplified so the map can draw it. The answer's
citations ([S2], [L1]) come with their paragraph pointer, article and section; get_source_text()
turns a pointer into the paragraph. The trust boundary from phase 1 holds: no coordinate or source
here comes from the LLM.
"""
from typing import Optional

from evidence import EvidencePack
from geo import bbox, parse_wkt, simplify
from graph_index import GraphIndex
from graph_tools import lead_pointer
from planner import QueryPlan
from resolver import Resolution
from retrieve import Retrieval
from schema import (Alternative, CitationOut, EntityOut, Geometry, MapHint, Meta, PlaceOut, Result)
from writer import Answer, strip_citations

MAX_SHAPES = 10            # outlines for at most this many primary places
MAX_SHAPE_POINTS = 300     # points per outline, after simplification
MAX_PLACE_SOURCES = 10     # paragraph pointers per place
MAX_ENTITIES = 20


def outline(gi: GraphIndex, place_name: str) -> Optional[dict]:
    """The place's polygon or line from the graph, simplified; None for a bare point."""
    shape = parse_wkt(gi.G.nodes[place_name].get("geometry_wkt"))
    if not shape or shape["type"] == "Point":
        return None
    return simplify(shape, MAX_SHAPE_POINTS)


def _place_sources(gi: GraphIndex, hit) -> list[str]:
    """The paragraphs behind a place, best first; a place found by name alone (a place lookup) gets
    its own article's first paragraph."""
    pointers = [f"TEXT_{p.text_id}" for p in hit.pointers[:MAX_PLACE_SOURCES]]
    if not pointers and hit.group.own_article:
        lead = lead_pointer(gi, hit.group.own_article)
        pointers = [f"TEXT_{lead.text_id}"] if lead else []
    return pointers


def _map_hint(places: list[PlaceOut], highlight: list[int]) -> MapHint:
    focus = [p for p in places if p.number in highlight] or places[:10]
    if not focus:
        return MapHint(highlight=highlight)
    xs, ys = [], []
    for p in focus:
        geom = p.shape.model_dump() if p.shape else p.geometry.model_dump()
        if geom["type"] == "Point":
            xs.append(geom["coordinates"][0])
            ys.append(geom["coordinates"][1])
        else:
            w, s, e, n = bbox(geom)
            xs += [w, e]
            ys += [s, n]
    pad_x = max((max(xs) - min(xs)) * 0.1, 0.01)
    pad_y = max((max(ys) - min(ys)) * 0.1, 0.01)
    # kept inside valid coordinates: Russia's outline crosses the 180th meridian and spans every longitude
    return MapHint(bbox=[round(max(min(xs) - pad_x, -180), 5), round(max(min(ys) - pad_y, -90), 5),
                         round(min(max(xs) + pad_x, 180), 5), round(min(max(ys) + pad_y, 90), 5)], highlight=highlight)


def build_result(plan: QueryPlan, res: Resolution, ret: Retrieval, pack: EvidencePack, answer: Answer,
                 gi: GraphIndex, seconds: float = 0.0) -> Result:
    refs = {p.number: p for p in pack.places}
    primary = list(answer.places_discussed)
    if plan.type == "place_lookup" or (not primary and len(pack.places) == 1):
        primary = [p.number for p in pack.places[:1]] + [n for n in primary if n != 1]

    places, shapes = [], 0
    for number, hit in enumerate(ret.places, 1):
        if not hit.group.place:
            continue
        ref = refs.get(number)
        is_primary = number in primary
        shape = None
        if is_primary and shapes < MAX_SHAPES:
            shape = outline(gi, hit.group.place.from_name)
            shapes += shape is not None
        places.append(PlaceOut(
            number=number, id=hit.group.id, label=hit.group.id,
            kind=(ref.kind if ref else hit.group.place.place_type) or "place",
            role="primary" if is_primary else "context",
            geometry=Geometry(type="Point", coordinates=[hit.group.place.lon, hit.group.place.lat]),
            shape=Geometry(**shape) if shape else None,
            why=ref.why if ref else "", uncertain=ref.uncertain if ref else None,
            sources=_place_sources(gi, hit)))

    passages = {p.id: p for p in pack.passages}
    citations = []
    for pid in answer.passages_cited:
        p = passages.get(pid)
        if p:
            citations.append(CitationOut(id=pid, pointer=f"TEXT_{p.text_id}", article=p.article, section=p.section,
                                         spans=[[p.offset + a, p.offset + b] for a, b in p.spans]))

    alternatives = {}
    for e in res.entities:
        for alt in e.alternatives:
            alternatives.setdefault(alt.id, Alternative(id=alt.id, type=alt.type))

    calls = list(plan.llm_calls) + list(res.llm_calls) + list(answer.llm_calls)
    notes = ([f"① {n}" for n in plan.notes] + [f"② {n}" for n in res.notes] + [f"③ {n}" for n in ret.notes]
             + [f"④ {n}" for n in pack.notes] + [f"⑤ {n}" for n in answer.notes])
    return Result(
        answer=answer.text, answer_plain=strip_citations(answer.text), status=answer.status, grounded=answer.grounded, shape=answer.shape,
        geo_locations=places, regions=pack.regions,
        entities=[EntityOut(id=e.id, type=e.type, role=e.role, records=e.records) for e in pack.entities[:MAX_ENTITIES]],
        citations=citations, sources=list(dict.fromkeys(c.pointer for c in citations)),
        map=_map_hint(places, [n for n in primary if n in {p.number for p in places}]),
        follow_ups=answer.follow_ups, did_you_mean=list(alternatives.values()), notes=notes,
        meta=Meta(question_type=plan.type, model=next((c.model for c in reversed(calls) if c.model), None),
                  llm_calls=len(calls), cost_usd=round(sum(c.cost_usd for c in calls), 6), seconds=round(seconds, 2)))
