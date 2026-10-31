"""⑥ Result: the JSON the UI receives. No LLM; everything comes from the graph and the earlier steps.

Every place found goes in, numbered exactly as the answer cites it ([3] is place number 3), with its
point, its data line and its paragraph pointers. The places the question is about also get their
outline - the graph's polygon or line, simplified so the map can draw it - and the map zooms to
them (P2-73). The answer's
citations ([S2], [L1]) come with their paragraph pointer, article and section; get_source_text()
turns a pointer into the paragraph. The trust boundary from phase 1 holds: no coordinate or source
here comes from the LLM.
"""
from typing import Optional, Sequence

from evidence import EvidencePack
from geo import bbox, parse_wkt, simplify
from graph_index import GraphIndex
from graph_tools import lead_pointer
from planner import QueryPlan
from resolver import Resolution
from retrieve import Retrieval
from schema import (Alternative, CitationOut, EntityOut, Geometry, MapHint, Meta, PlaceOut, Result)
from writer import Answer, strip_citations

MAX_SHAPES = 10            # outlines for at most this many places
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


def _zoom_box(p: PlaceOut) -> tuple[float, float, float, float]:
    """[west, south, east, north] of one place. An outline that crosses the 180th meridian (Russia's
    Chukotka, the Aleutians of the US) spans every longitude, so only its parts on the side of the
    place's point count (P2-76)."""
    lon, lat = p.geometry.coordinates
    if not p.shape:
        return lon, lat, lon, lat
    geom = p.shape.model_dump()
    w, s, e, n = bbox(geom)
    if e - w > 180 and geom["type"] == "MultiPolygon":
        parts = [bbox({"type": "Polygon", "coordinates": c}) for c in geom["coordinates"]]
        near = [b for b in parts if ((b[0] + b[2]) / 2 >= 0) == (lon >= 0)]
        if near:
            w, s, e, n = (min(b[0] for b in near), min(b[1] for b in near),
                          max(b[2] for b in near), max(b[3] for b in near))
    return w, s, e, n


def _map_hint(places: list[PlaceOut], highlight: list[int], zoom_to: Sequence[int] = ()) -> MapHint:
    """Zooms to the places the question is about; with none, to the places the answer discusses."""
    focus = [p for p in places if p.number in (zoom_to or highlight)] or places[:10]
    if not focus:
        return MapHint(highlight=highlight)
    xs, ys = [], []
    for p in focus:
        w, s, e, n = _zoom_box(p)
        xs += [w, e]
        ys += [s, n]
    pad_x = max((max(xs) - min(xs)) * 0.1, 0.01)
    pad_y = max((max(ys) - min(ys)) * 0.1, 0.01)
    # kept inside valid coordinates
    return MapHint(bbox=[round(max(min(xs) - pad_x, -180), 5), round(max(min(ys) - pad_y, -90), 5),
                         round(min(max(xs) + pad_x, 180), 5), round(min(max(ys) + pad_y, 90), 5)], highlight=highlight)


def build_result(plan: QueryPlan, res: Resolution, ret: Retrieval, pack: EvidencePack, answer: Answer,
                 gi: GraphIndex, seconds: float = 0.0) -> Result:
    refs = {p.number: p for p in pack.places}
    primary = list(answer.places_discussed)
    if plan.type == "place_lookup" or (not primary and len(pack.places) == 1):
        primary = [p.number for p in pack.places[:1]] + [n for n in primary if n != 1]
    # the places the question asks about count as discussed even when the answer names them without
    # their number ("Illich refers to the Illich steel plant..."), so they're always on the map
    asked = {e.group.id for e in res.entities if e.group} | (
        {plan.follow_up.target_id} if plan.follow_up and plan.follow_up.target_id else set())
    primary += [n for n, h in enumerate(ret.places, 1) if h.group.id in asked and n not in primary]

    # P2-73: only the places the question is about get an outline, and the map zooms to them; every
    # other place keeps its pin. "What happened in Crimea?" outlined Russia and Ukraine too and zoomed
    # out to the whole world. A list's places are all equal, so a list gets pins only; an area question
    # outlines the named area it searched ("drone attacks in Kharkiv"), never a drawn one (the UI
    # draws the selection itself).
    if plan.type in ("area", "area_topic"):
        area_from = (ret.area_used or {}).get("from")
        about = [n for n, h in enumerate(ret.places, 1) if h.group.id == area_from]
    elif answer.shape == "list":
        about = []
    else:
        looked_up = primary[:1] if plan.type == "place_lookup" else []   # the place, or the event's main place
        about = list(dict.fromkeys(looked_up + [n for n, h in enumerate(ret.places, 1) if h.group.id in asked]))

    places, shapes = [], 0
    for number, hit in enumerate(ret.places, 1):
        if not hit.group.place:
            continue
        ref = refs.get(number)
        is_primary = number in primary
        shape = None
        if number in about and shapes < MAX_SHAPES:
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

    # P2-65: a list or an area answer is about all its places, so the map shows them all. Any other
    # answer (where a place is, who did what, one person at one place, a question about something)
    # shows only the places it discusses: "Tell me about Mariupol" found 552 linked places.
    show_all = answer.shape == "list" or plan.type in ("area", "area_topic")
    shown = places if show_all else ([p for p in places if p.role == "primary"] or places[:1])
    not_shown = len(places) - len(shown)
    places = shown

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
        map=_map_hint(places, [n for n in primary if n in {p.number for p in places}], about).model_copy(
            update={"showing": "all" if show_all else "discussed", "not_shown": not_shown}),
        follow_ups=answer.follow_ups, did_you_mean=list(alternatives.values()), notes=notes,
        meta=Meta(question_type=plan.type, model=next((c.model for c in reversed(calls) if c.model), None),
                  llm_calls=len(calls), cost_usd=round(sum(c.cost_usd for c in calls), 6), seconds=round(seconds, 2)))
