"""③ Retrieve: graph tools and routes, on the small Vr6-format graph. No LLM anywhere in this step."""
import graph_tools as T
from planner import Area, Concept, ConceptCandidate, EntityMention, QueryPlan
from resolver import resolve
from retrieve import retrieve

KYIV_CENTRE = Area(kind="point", coordinates=[30.5234, 50.4501])
FAR_POINT = Area(kind="point", coordinates=[34.0, 47.0])


def run(gi, qtype, *entities, **plan_fields):
    plan = QueryPlan(question="q", type=qtype, source="llm",
                     entities=[EntityMention(text=t, name=t, kind=k) for t, k in entities], **plan_fields)
    return retrieve(plan, resolve(plan, gi), gi)


# --- tools -----------------------------------------------------------------------------------

def test_confident_relations_count_low_ones_become_mentioned_with(vr6_index):
    recs = T.entity_records(vr6_index, "Bakhmut")
    by_other = {r.other: r for r in recs}
    assert by_other["Wagner Group"].relation == "ATTACKED"           # 0.9
    assert by_other["Telegram"].relation == "MENTIONED_WITH"          # 0.47: only "mentioned together"
    assert by_other["Telegram"].classifier_label == "ATTACKED"


def test_relation_filter_keeps_only_confident_records_of_that_type(vr6_index):
    recs = T.entity_records(vr6_index, "Bakhmut", ["ATTACKED"])
    assert {r.other for r in recs} == {"Wagner Group", "Russian Armed Forces"}   # not Telegram


def test_records_point_at_the_exact_words(vr6_index):
    rec = next(r for r in T.entity_records(vr6_index, "General Staff", ["LEADS"]))
    text = vr6_index.text(rec.pointer.text_id)["text"]
    assert sorted(text[a:b] for a, b in rec.pointer.spans) == ["General Staff", "Valery Gerasimov"]


def test_aggregate_ranks_and_sets_the_role(vr6_index):
    hits = T.aggregate(vr6_index, T.entity_records(vr6_index, "Bakhmut"), set(vr6_index.groups["Bakhmut"]))
    attackers = [h for h in hits if h.group.id in ("Wagner Group", "Russian Armed Forces")]
    assert attackers and all(h.role == "acts" and h.relations.get("ATTACKED") == 1 for h in attackers)
    assert hits[0].score >= hits[-1].score


def test_places_near_and_within(vr6_index):
    near = T.places_near(vr6_index, 30.5234, 50.4501, 500)
    assert [h.group.id for h in near][:2] == ["Maidan Nezalezhnosti", "Kyiv"] and near[0].distance_m < near[1].distance_m
    kyiv_shape = T.shape_of(vr6_index, vr6_index.group("Kyiv"))
    assert {h.group.id for h in T.places_within(vr6_index, kyiv_shape)} == {"Kyiv", "Maidan Nezalezhnosti", "Kyiv City"}


def test_parents_follow_inside(vr6_index):
    assert T.parents(vr6_index, "Bakhmut") == ["Bakhmut", "Ukraine"]


def test_keyword_spans_match_word_starts():
    assert T.keyword_spans("Two drones and a drone-strike", ["drone"]) == [[4, 10], [17, 22]]


def test_article_places_rank_by_paragraphs(vr6_index):
    hits = T.article_places(vr6_index, "Battle of Bakhmut")
    assert [h.group.id for h in hits] == ["Bakhmut", "Soledar"] and hits[0].records == 3


def test_common_neighbors(vr6_index):
    hits = T.common_neighbors(vr6_index, ["Russia", "Ukraine"], {"LOC"}, ["country"])
    assert [h.group.id for h in hits] == ["Belarus"]


# --- routes ----------------------------------------------------------------------------------

def test_place_lookup_returns_the_place_its_parents_and_its_summary(vr6_index):
    out = run(vr6_index, "place_lookup", ("Bakhmut", "LOC"))
    assert [h.group.id for h in out.places] == ["Bakhmut"]
    assert "Bakhmut is inside: Ukraine" in out.notes
    assert out.steps[0].tool == "parents"


def test_place_lookup_reports_an_uncertain_point(vr6_index):
    out = run(vr6_index, "place_lookup", ("Donbas", "LOC"))
    assert any("uncertain" in n for n in out.notes)


def test_area_point_with_radius(vr6_index):
    out = run(vr6_index, "area", area=KYIV_CENTRE, radius_m=500)
    assert out.places[0].group.id == "Maidan Nezalezhnosti" and out.places[0].pointers
    assert out.area_used == {"from": "point", "point": [30.5234, 50.4501], "radius_m": 500}


def test_area_widens_when_nothing_is_near_and_says_so(vr6_index):
    out = run(vr6_index, "area", area=FAR_POINT, radius_m=500)
    assert out.places == [] and any("no places within" in n for n in out.notes)
    assert [s.params["radius_m"] for s in out.steps] == [500, 2000, 5000]


def test_area_topic_in_the_map_polygon(vr6_index):
    box = Area(kind="polygon", coordinates=[[[37, 48], [39, 48], [39, 49], [37, 49], [37, 48]]])
    out = run(vr6_index, "area_topic", area=box, keywords=["drone", "attack"], relations=["ATTACKED"])
    assert [h.group.id for h in out.places] == ["Bakhmut"]          # Soledar has no drone paragraph
    texts = [vr6_index.text(p.text_id)["text"] for p in out.places[0].pointers]
    assert texts == ["Russian Armed Forces launched drone attacks on Bakhmut in 2023."]
    assert out.places[0].relations == {"ATTACKED": 1}   # only the attack record inside a drone paragraph counts
    assert "ignoring the generic attack" in out.notes[0]


def test_area_topic_with_only_a_relation_uses_the_relation_records(vr6_index):
    box = Area(kind="polygon", coordinates=[[[37, 48], [39, 48], [39, 49], [37, 49], [37, 48]]])
    out = run(vr6_index, "area_topic", area=box, relations=["ATTACKED"])
    assert [h.group.id for h in out.places] == ["Bakhmut"] and out.places[0].relations == {"ATTACKED": 2}


def test_area_topic_uses_a_named_places_own_polygon(vr6_index):
    out = run(vr6_index, "area_topic", ("Kyiv", "LOC"), keywords=["drone"])
    assert out.area_used == {"from": "Kyiv", "type": "Polygon"}
    assert [h.group.id for h in out.places] == ["Maidan Nezalezhnosti"]


def test_about_with_a_relation_finds_who_leads_from_concept_candidates(vr6_index):
    out = run(vr6_index, "about", relations=["LEADS"], concepts=[Concept(
        text="the Russian military", candidates=[ConceptCandidate(name="General Staff", kind="ORG")])])
    assert [h.group.id for h in out.entities] == ["Valery Gerasimov"] and out.entities[0].role == "acts"
    assert out.records[0].relation == "LEADS"
    assert [s.article for s in out.summaries] == ["Valery Gerasimov"]   # the leader's own article


def test_relation_who_attacked(vr6_index):
    out = run(vr6_index, "relation", ("Bakhmut", "LOC"), relations=["ATTACKED"])
    assert {h.group.id for h in out.entities} == {"Wagner Group", "Russian Armed Forces"}


def test_entity_places_rank_place_relations_first_then_specificity(vr6_index):
    out = run(vr6_index, "entity_places", ("Volodymyr Zelenskyy", "PER"))
    # Kharkiv: VISITED (puts him there). Then by specificity: Kyiv 1 of 25 paragraphs, Ukraine 1 of ~34
    # (Ukraine's link is LEADS - holding office - which doesn't count as being at a place).
    assert [h.group.id for h in out.places] == ["Kharkiv", "Kyiv", "Ukraine"]
    assert out.places[0].relations == {"VISITED": 1} and out.places[0].score == 1
    assert out.places[1].specificity > out.places[2].specificity


def test_who_leads_two_places_interleaves_the_answers(vr6_index):
    out = run(vr6_index, "relation", ("Ukraine", "LOC"), ("Russia", "LOC"), relations=["LEADS"])
    assert [h.group.id for h in out.entities] == ["Petro Poroshenko", "Vladimir Putin", "Zelenskyy"]
    assert all(h.role == "acts" for h in out.entities)


def test_relation_fallback_expands_to_linked_organizations(vr6_index):
    out = run(vr6_index, "about", relations=["LEADS"], concepts=[Concept(
        text="the Russian military", candidates=[ConceptCandidate(name="Russian Armed Forces", kind="ORG")])])
    assert [h.group.id for h in out.entities] == ["Valery Gerasimov"]       # via General Staff
    assert any("most linked to them: General Staff" in n for n in out.notes)
    assert not out.records[0].low_confidence


def test_relation_fallback_accepts_labelled_low_confidence_last(vr6_index):
    out = run(vr6_index, "about", ("Black Sea Fleet", "ORG"), relations=["LEADS"])
    assert [h.group.id for h in out.entities] == ["Viktor Sokolov"]
    assert out.records[0].low_confidence and out.records[0].confidence == 0.45
    assert any("only low-confidence LEADS records" in n for n in out.notes)
    assert [s.params["why"] for s in out.steps] == ["asked", "low-confidence fallback"]


def test_event_places_from_the_article(vr6_index):
    out = run(vr6_index, "event_places", ("Battle of Bakhmut", "EVENT"))
    assert [h.group.id for h in out.places] == ["Bakhmut", "Soledar"]
    assert out.summaries[0].article == "Battle of Bakhmut"


def test_common_route_infers_countries_from_the_question(vr6_index):
    out = run(vr6_index, "common", ("Russia", "LOC"), ("Ukraine", "LOC"), keywords=["same country"])
    assert [h.group.id for h in out.places] == ["Belarus"]
    assert "only countries kept" in out.notes[0]


def test_a_follow_up_naming_the_same_place_twice_is_still_a_drilldown(vr6_index):
    from planner import FollowUp
    plan = QueryPlan(question="Tell me about Zelenskyy in Kharkiv", type="follow_up", source="llm",
                     entities=[EntityMention(text="Zelenskyy", name="Zelenskyy", kind="PER"),
                               EntityMention(text="Kharkiv", name="Kharkiv", kind="LOC")],
                     follow_up=FollowUp(kind="item", item_number=1, target_id="Kharkiv", target_label="Kharkiv"))
    res = resolve(plan, vr6_index)
    assert [e.group.id for e in res.entities] == ["Zelenskyy", "Kharkiv"]   # the follow-up target isn't added twice
    assert retrieve(plan, res, vr6_index).route.startswith("drill-down: what links Zelenskyy and Kharkiv")


def test_types_without_a_route_say_so(vr6_index):
    out = run(vr6_index, "other")
    assert out.route == "none" and "fallback" in out.notes[0]
