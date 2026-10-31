"""① Understand: fast path, LLM plan rules, and keyword fallback. No network: the LLM is faked."""
import httpx
import openai
import pytest
from langchain_core.messages import AIMessage

from planner import (DEFAULT_RADIUS_M, Area, Concept, ConceptCandidate, EntityMention, PlanDraft,
                     fast_path, keyword_plan, radius_from_text, summarize_history, understand)

KYIV_POINT = Area(kind="point", coordinates=[30.5234, 50.4501])
DONBAS_BOX = Area(kind="polygon", coordinates=[[[36, 47], [39, 47], [39, 49.5], [36, 49.5], [36, 47]]])
PREVIOUS = [{"query": "Show me the locations of the Battle of Bakhmut",
             "response": {"answer": "...", "sources": [],
                          "geo_locations": [{"id": "Bakhmut", "label": "Bakhmut"},
                                            {"id": "Soledar", "label": "Soledar"}]}}]


def raw_result(parsed):
    """What a LangChain structured call returns with include_raw=True."""
    raw = AIMessage(content="", response_metadata={"model_name": "fake/model", "token_usage": {"cost": 0.0002}},
                    usage_metadata={"input_tokens": 900, "output_tokens": 80, "total_tokens": 980})
    return {"raw": raw, "parsed": parsed, "parsing_error": None}


class FakePlanner:
    """Stands in for the chat model: returns a fixed PlanDraft, or raises."""

    def __init__(self, draft=None, error=None):
        self.draft, self.error, self.messages = draft, error, None

    def with_structured_output(self, schema, method=None, include_raw=False):
        assert schema is PlanDraft and include_raw
        return self

    def invoke(self, messages):
        self.messages = messages
        if self.error:
            raise self.error
        return raw_result(self.draft)


# --- fast path -------------------------------------------------------------------------------

@pytest.mark.parametrize("question, name", [
    ("Where is Dnipro?", "Dnipro"), ("where is Kryvyi Rih", "Kryvyi Rih"), ("Where was the Azovstal plant?", None),
])
def test_where_is_takes_the_fast_path_only_for_clean_names(question, name):
    plan = fast_path(question, None)
    if name is None:   # "plant" is lower case, so it's not obviously just a name: leave it to the LLM
        assert plan is None
    else:
        assert plan.type == "place_lookup" and plan.needs == "locations" and plan.source == "fast_path"
        assert plan.entities[0].name == name and plan.entities[0].kind == "LOC"


def test_where_is_with_a_verb_is_not_a_fast_path():
    assert fast_path("Where was Bakhmut attacked from?", None) is None


def test_locations_connected_to_takes_the_fast_path():
    plan = fast_path("Show me all locations connected to Volodymyr Zelenskyy.", None)
    assert plan.type == "entity_places" and plan.entities[0].name == "Volodymyr Zelenskyy"


def test_locations_of_an_event_is_typed_as_an_event():
    plan = fast_path("Show me all locations connected to the Siege of Mariupol", None)
    assert plan.type == "event_places" and plan.entities[0].kind == "EVENT"
    assert plan.entities[0].name == "Siege of Mariupol"


def test_fast_path_notes_that_a_map_selection_was_not_used():
    plan = fast_path("Where is Dnipro?", KYIV_POINT)
    assert plan.area is None and "map selection not used" in plan.notes[0]


# --- LLM plan rules --------------------------------------------------------------------------

def test_llm_plan_keeps_only_real_relation_names():
    draft = PlanDraft(type="relation", relations=["attacked", "ATTACKS", "Leads"],
                      entities=[EntityMention(text="Bakhmut", name="Bakhmut", kind="LOC")])
    plan = understand("Who attacked and who leads Bakhmut?", llm=FakePlanner(draft))
    assert plan.relations == ["ATTACKED", "LEADS"]
    assert any("ATTACKS" in n for n in plan.notes) and plan.source == "llm"


def test_concepts_carry_only_organization_or_place_candidates():
    draft = PlanDraft(type="about", relations=["LEADS"], concepts=[Concept(
        text="the Russian military",
        candidates=[ConceptCandidate(name="General Staff", kind="ORG"),
                    ConceptCandidate(name="Russian Armed Forces", kind="ORG")])])
    plan = understand("Tell me about the head of the Russian military", llm=FakePlanner(draft))
    assert [c.name for c in plan.concepts[0].candidates] == ["General Staff", "Russian Armed Forces"]
    with pytest.raises(ValueError):   # a person can't even be expressed as a candidate
        ConceptCandidate(name="Valery Gerasimov", kind="PER")


def test_a_named_place_wins_over_the_map_selection():
    draft = PlanDraft(type="relation", refers_to_map=False, keywords=["drone"], relations=["ATTACKED"],
                      entities=[EntityMention(text="Kharkiv", name="Kharkiv", kind="LOC")])
    plan = understand("Drone attacks in Kharkiv", area=DONBAS_BOX, llm=FakePlanner(draft))
    assert plan.area is None
    assert plan.notes == ["map selection not used: the question names Kharkiv"]


def test_a_named_place_wins_even_when_the_llm_calls_it_an_area_question():
    draft = PlanDraft(type="area_topic", refers_to_map=False, keywords=["drone"],
                      entities=[EntityMention(text="Kharkiv", name="Kharkiv", kind="LOC")])
    plan = understand("Drone attacks in Kharkiv", area=DONBAS_BOX, llm=FakePlanner(draft))
    assert plan.type == "area_topic" and plan.area is None
    assert plan.notes == ["map selection not used: the question names Kharkiv, so its own area is used instead"]


def test_what_is_here_becomes_an_area_question():
    plan = understand("What is here?", area=KYIV_POINT,
                      llm=FakePlanner(PlanDraft(type="place_lookup", refers_to_map=True)))
    assert plan.type == "area" and (plan.radius_m, plan.radius_source) == (DEFAULT_RADIUS_M, "default")


def test_numbers_coordinates_and_names_are_not_keywords():
    draft = PlanDraft(type="area", refers_to_map=True, keywords=["30.5234,50.4501", "500", "drone", "Kyiv", "drone"],
                      entities=[EntityMention(text="Kyiv", name="Kyiv", kind="LOC")])
    plan = understand("drones near Kyiv here", area=KYIV_POINT, llm=FakePlanner(draft))
    assert plan.keywords == ["drone"]


def test_what_happened_in_a_place_is_a_question_about_the_place():
    # the model typed it as a topic search for the word "happened" (P2-72)
    draft = PlanDraft(type="area_topic", keywords=["happened"],
                      entities=[EntityMention(text="Moscow", name="Moscow", kind="LOC")])
    plan = understand("What happened in Moscow?", llm=FakePlanner(draft))
    assert plan.type == "about" and plan.keywords == []
    assert "area_topic with no topic words: treated as about" in plan.notes


def test_what_happened_here_stays_a_question_about_the_map_selection():
    draft = PlanDraft(type="area_topic", refers_to_map=True, keywords=["events"])
    plan = understand("What happened here?", area=DONBAS_BOX, llm=FakePlanner(draft))
    assert plan.type == "area" and plan.area is not None


def test_a_real_topic_keeps_the_area_topic_type():
    draft = PlanDraft(type="area_topic", keywords=["happened", "shelling"],
                      entities=[EntityMention(text="Kherson", name="Kherson", kind="LOC")])
    plan = understand("What shelling happened in Kherson?", llm=FakePlanner(draft))
    assert plan.type == "area_topic" and plan.keywords == ["shelling"]


@pytest.mark.parametrize("question, expected", [
    ("Show me where the battle of Bakhmut occurred", "place_lookup"),
    ("Where did the Battle of Bakhmut happen?", "place_lookup"),
    ("Where did the Battle of Bakhmut take place?", "place_lookup"),                  # "place" here is no list
    ("Show me all locations where the Battle of Bakhmut was fought", "event_places"),   # asks for the list
    ("Which places were part of the Battle of Bakhmut?", "event_places"),               # no "where"
])
def test_where_one_event_happened_is_a_place_lookup(question, expected):
    draft = PlanDraft(type="event_places",
                      entities=[EntityMention(text="Battle of Bakhmut", name="Battle of Bakhmut", kind="EVENT")])
    assert understand(question, llm=FakePlanner(draft)).type == expected


def test_where_a_topic_happened_is_not_a_place_lookup():
    draft = PlanDraft(type="event_places", keywords=["drone", "attack"],
                      entities=[EntityMention(text="drone attacks", name="drone attacks", kind="EVENT")])
    assert understand("Show me where drone attacks happened", llm=FakePlanner(draft)).type != "place_lookup"


def test_the_map_selection_is_used_when_the_question_refers_to_it():
    draft = PlanDraft(type="area_topic", refers_to_map=True, keywords=["drone"], relations=["ATTACKED"])
    plan = understand("Drone attacks in this bounding box", area=DONBAS_BOX, llm=FakePlanner(draft))
    assert plan.area == DONBAS_BOX and plan.keywords == ["drone"]


@pytest.mark.parametrize("text_radius, map_radius, expected", [
    (500, None, (500, "text")), (None, 250, (250, "map")), (None, None, (DEFAULT_RADIUS_M, "default")),
    (2000, 250, (2000, "text")),
])
def test_radius_text_beats_map_beats_default(text_radius, map_radius, expected):
    draft = PlanDraft(type="area", refers_to_map=True, radius_m=text_radius)
    plan = understand("Anything near here?", area=KYIV_POINT, llm=FakePlanner(draft), map_radius_m=map_radius)
    assert (plan.radius_m, plan.radius_source) == expected


def test_out_of_scope_is_kept_as_a_type_not_a_refusal():
    plan = understand("What's a good pasta recipe?", llm=FakePlanner(PlanDraft(type="other", in_scope=False)))
    assert plan.type == "out_of_scope" and plan.in_scope is False


def test_follow_up_item_is_resolved_against_the_previous_result():
    draft = PlanDraft(type="follow_up", follow_up_kind="item", follow_up_item=2)
    plan = understand("Tell me about number 2", history=PREVIOUS, llm=FakePlanner(draft))
    assert plan.type == "follow_up"
    assert (plan.follow_up.target_id, plan.follow_up.target_label) == ("Soledar", "Soledar")


def test_follow_up_without_history_is_noted():
    plan = understand("Show more", llm=FakePlanner(PlanDraft(type="follow_up", follow_up_kind="more")))
    assert plan.type == "other" and plan.follow_up is None
    assert "no previous turn: treated as other" in plan.notes[0]


def test_the_llm_sees_the_map_and_a_short_history_but_no_graph_data():
    fake = FakePlanner(PlanDraft(type="follow_up", follow_up_kind="more"))
    understand("Show more", area=KYIV_POINT, history=PREVIOUS, llm=fake, map_radius_m=500)
    human = fake.messages[1][1]
    assert "a point at [lon, lat] [30.5234, 50.4501], radius 500 m" in human
    assert "1. Bakhmut, 2. Soledar" in human


# --- guards against the LLM supplying the answer (P2-27) -------------------------------------

def test_names_the_llm_expanded_from_one_phrase_are_dropped():
    cities = [EntityMention(text="Ukrainian city", name=n, kind="LOC") for n in ("Kyiv", "Lviv", "Odesa")]
    plan = understand("Show me Ukrainian cities connected to Russian military operations.",
                      llm=FakePlanner(PlanDraft(type="other", entities=cities)))
    assert plan.entities == []
    assert any("expansion" in n or "not in the question" in n for n in plan.notes)


def test_a_name_that_is_not_in_the_question_is_dropped():
    draft = PlanDraft(type="follow_up", follow_up_kind="more",
                      entities=[EntityMention(text="Battle of Bakhmut", name="Battle of Bakhmut", kind="EVENT")])
    plan = understand("show more", history=PREVIOUS, llm=FakePlanner(draft))
    assert plan.entities == [] and "not in the question" in plan.notes[0]


def test_a_description_becomes_a_concept():
    draft = PlanDraft(type="other", entities=[
        EntityMention(text="Russian military commanders", name="Russian military commanders", kind="UNKNOWN")])
    plan = understand("Show me Ukrainian locations connected to Russian military commanders.", llm=FakePlanner(draft))
    assert plan.entities == [] and plan.concepts[0].text == "Russian military commanders"


@pytest.mark.parametrize("text, name, kept", [
    ("bucha massacre", "Bucha massacre", True),
    ("Kharkiv counteroffensive", "2022 Kharkiv counteroffensive", True),
    ("drone attacks", "drone attacks", False),          # an event-like description stays a concept
])
def test_an_event_title_with_lower_case_words_is_a_name(text, name, kept):
    draft = PlanDraft(type="event_places", entities=[EntityMention(text=text, name=name, kind="EVENT")])
    plan = understand(f"Show me all locations connected to the {text}", llm=FakePlanner(draft))
    assert ([e.name for e in plan.entities] == [name]) is kept
    assert (plan.concepts == []) is kept


def test_place_candidates_are_dropped_when_the_question_asks_for_places():
    draft = PlanDraft(type="event_list", concepts=[Concept(text="major battles", candidates=[
        ConceptCandidate(name="Battle of Kyiv", kind="LOC"), ConceptCandidate(name="Battle of Bakhmut", kind="LOC")])])
    plan = understand("Show me the locations of major battles", llm=FakePlanner(draft))
    assert plan.concepts[0].candidates == []
    assert "the places must come from the graph" in plan.notes[0]


def test_organization_candidates_stay_and_are_capped():
    orgs = [ConceptCandidate(name=f"Org {i}", kind="ORG") for i in range(5)]
    draft = PlanDraft(type="about", concepts=[Concept(text="the Russian military", candidates=orgs)])
    plan = understand("Tell me about the head of the Russian military", llm=FakePlanner(draft))
    assert [c.name for c in plan.concepts[0].candidates] == ["Org 0", "Org 1", "Org 2"]


class FlakyPlanner(FakePlanner):
    """Returns nothing on the first call, a real plan on the second."""

    def __init__(self, draft):
        super().__init__(draft)
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        return raw_result(None if self.calls == 1 else self.draft)


def test_one_retry_when_the_model_returns_no_structure():
    fake = FlakyPlanner(PlanDraft(type="place_lookup",
                                  entities=[EntityMention(text="dnipro", name="Dnipro", kind="LOC")]))
    plan = understand("where is dnipro", llm=fake)
    assert fake.calls == 2 and plan.source == "llm" and plan.entities[0].name == "Dnipro"
    assert [c.ok for c in plan.llm_calls] == [False, True]   # the failed attempt is recorded too


def test_every_llm_call_is_recorded_with_model_tokens_and_cost():
    plan = understand("Who attacked Mariupol?", llm=FakePlanner(PlanDraft(
        type="relation", relations=["ATTACKED"], entities=[EntityMention(text="Mariupol", name="Mariupol", kind="LOC")])))
    call = plan.llm_calls[0]
    assert (call.step, call.model, call.input_tokens, call.output_tokens, call.cost_usd, call.cached) == \
        ("understand", "fake/model", 900, 80, 0.0002, False)


def test_fast_path_makes_no_llm_calls():
    assert understand("Where is Dnipro?", llm=FakePlanner(error=AssertionError("must not be called"))).llm_calls == []


def test_a_follow_up_without_history_is_a_fresh_question():
    draft = PlanDraft(type="follow_up", follow_up_kind="more", keywords=["drone"], relations=["ATTACKED"])
    plan = understand("Drone attacks in this bounding box", area=DONBAS_BOX, llm=FakePlanner(draft))
    assert plan.type == "area_topic" and plan.area == DONBAS_BOX and plan.follow_up is None
    assert "no previous turn: treated as area_topic" in plan.notes[0]


def test_place_filter_is_carried_into_the_plan():
    draft = PlanDraft(type="entity_places", place_country="Ukraine", place_kinds=["city", "city"],
                      entities=[EntityMention(text="Russian military", name="Russian Armed Forces", kind="ORG")])
    plan = understand("Show me Ukrainian cities connected to the Russian military", llm=FakePlanner(draft))
    assert (plan.place_country, plan.place_kinds) == ("Ukraine", ["city"])


# --- role questions: "president of X" (P2-50) ------------------------------------------------

def test_president_of_a_named_place_becomes_the_place_with_leads():
    draft = PlanDraft(type="about", concepts=[   # what a model actually returned on 2026-10-20
        Concept(text="the president of Ukraine", candidates=[ConceptCandidate(name="President of Ukraine", kind="ORG")]),
        Concept(text="the president of Russia", candidates=[ConceptCandidate(name="President of Russia", kind="ORG")])])
    plan = understand("Who is the president of Ukraine and the president of Russia?", llm=FakePlanner(draft))
    assert plan.type == "relation" and plan.relations == ["LEADS"]
    assert [e.name for e in plan.entities] == ["Ukraine", "Russia"] and plan.concepts == []
    assert any(n.startswith("role question:") for n in plan.notes)


def test_role_rule_overrides_a_common_typing():
    draft = PlanDraft(type="common", entities=[EntityMention(text="Ukraine", name="Ukraine", kind="LOC"),
                                                EntityMention(text="Russia", name="Russia", kind="LOC")])
    plan = understand("Who is the president of Ukraine and the president of Russia?", llm=FakePlanner(draft))
    assert plan.type == "relation" and plan.relations == ["LEADS"]


def test_a_role_of_a_description_is_left_to_the_concept():
    draft = PlanDraft(type="about", relations=["LEADS"], concepts=[Concept(
        text="the Russian military", candidates=[ConceptCandidate(name="General Staff", kind="ORG")])])
    plan = understand("Tell me about the head of the Russian military", llm=FakePlanner(draft))
    assert plan.entities == [] and plan.concepts[0].text == "the Russian military" and plan.type == "about"


def test_role_rule_also_works_without_the_llm():
    plan = understand("Who is the president of Ukraine and the president of Russia?")
    assert "LEADS" in plan.relations and {"Ukraine", "Russia"} <= {e.name for e in plan.entities}


# --- failures fall back to keywords ----------------------------------------------------------

def test_keyword_fallback_reads_a_place_filter():
    plan = understand("Show me Ukrainian cities connected to Russian military operations.")
    assert (plan.place_country, plan.place_kinds) == ("Ukraine", ["city"])

def test_keyword_fallback_keeps_a_lower_case_place_name():
    plan = understand("where is dnipro")
    assert plan.type == "place_lookup" and plan.entities[0].name == "Dnipro"

def _rate_limit():
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    return openai.RateLimitError("rate limited", response=httpx.Response(429, request=request), body=None)


@pytest.mark.parametrize("fake", [FakePlanner(error=_rate_limit()), FakePlanner(draft=None)])
def test_an_llm_failure_falls_back_to_keywords(fake):
    plan = understand("Who attacked Bakhmut?", llm=fake)
    assert plan.source == "keyword_fallback" and plan.type == "relation"
    assert plan.relations == ["ATTACKED"] and plan.entities[0].name == "Bakhmut"


def test_no_llm_means_keyword_plan():
    plan = understand("Drone attacks in this bounding box", area=DONBAS_BOX)
    assert plan.source == "keyword_fallback" and plan.type == "area_topic"
    assert plan.keywords == ["drone", "attack"] and plan.area == DONBAS_BOX


def test_keyword_plan_without_names_is_other_not_about():
    plan = understand("What is a good recipe for pasta?")
    assert plan.type == "other" and plan.source == "keyword_fallback"


def test_prompt_examples_are_not_the_test_questions():
    import json
    from pathlib import Path
    from planner import SYSTEM_PROMPT
    spec = json.loads((Path(__file__).resolve().parent.parent / "eval" / "questions.json").read_text(encoding="utf-8"))
    leaked = [q["text"] for q in spec["questions"] if q["text"].lower().rstrip("?.") in SYSTEM_PROMPT.lower()]
    assert leaked == []


def test_keyword_plan_reads_a_radius_and_follow_ups():
    plan = understand("Anything within 500m?", area=KYIV_POINT)
    assert plan.type == "area" and (plan.radius_m, plan.radius_source) == (500, "text")
    more = keyword_plan("show more", None, PREVIOUS, reason="test")
    assert more.type == "follow_up" and more.follow_up.kind == "more"


# --- helpers ---------------------------------------------------------------------------------

def test_radius_from_text():
    assert [radius_from_text(q) for q in ["within 500m", "2 km away", "1.5 kilometres", "the 93rd brigade"]] \
        == [500, 2000, 1500, None]


def test_history_summary_is_short():
    assert summarize_history([]) == "none"
    assert summarize_history(PREVIOUS) == ("Q: Show me the locations of the Battle of Bakhmut | "
                                           "places shown: 1. Bakhmut, 2. Soledar")


def test_follow_up_number_uses_the_place_numbers_of_the_previous_result():
    previous = [{"query": "q", "response": {"geo_locations": [
        {"number": n, "id": f"P{n}", "label": f"Place {n}"} for n in range(1, 31)]}}]
    plan = understand("Tell me about number 13", history=previous,
                      llm=FakePlanner(PlanDraft(type="follow_up", follow_up_kind="item", follow_up_item=13)))
    assert (plan.follow_up.target_id, plan.follow_up.target_label) == ("P13", "Place 13")


def test_history_summary_lists_at_most_20_places():
    previous = [{"query": "q", "response": {"geo_locations": [
        {"number": n, "id": f"P{n}", "label": f"Place {n}"} for n in range(1, 501)]}}]
    summary = summarize_history(previous)
    assert "20. Place 20 (+480 more on the map)" in summary and "Place 21" not in summary


def test_the_writer_reads_the_place_name_instead_of_the_old_number():
    from planner import FollowUp, QueryPlan, question_for_answer
    plan = QueryPlan(question="Tell me about location number 4", type="follow_up", source="llm",
                     follow_up=FollowUp(kind="item", item_number=4, target_id="Illich", target_label="Illich"))
    assert question_for_answer(plan) == "Tell me about Illich"
    plan.question = "What happened at number four?"
    assert question_for_answer(plan) == "What happened at Illich?"
    plan.question = "And that one?"
    assert question_for_answer(plan) == "And that one? (meaning Illich, from the previous answer)"
