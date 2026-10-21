"""② Resolve: names in a plan -> graph groups and articles. The LLM (for picking) is faked."""
from langchain_core.messages import AIMessage

from planner import Concept, ConceptCandidate, EntityMention, FollowUp, QueryPlan
from resolver import CandidatePick, Resolution, resolve, resolve_name


def plan_with(*entities, concepts=(), follow_up=None, question="q"):
    return QueryPlan(question=question, type="about", source="llm", follow_up=follow_up, concepts=list(concepts),
                     entities=[EntityMention(text=t, name=n, kind=k) for t, n, k in entities])


def one(gi, text, name=None, kind="UNKNOWN", llm=None):
    res = Resolution()
    return resolve_name(text, name or text, kind, gi, "q", llm, res), res


class FakePicker:
    def __init__(self, choice):
        self.choice, self.messages = choice, None

    def with_structured_output(self, schema, **kwargs):
        assert schema is CandidatePick
        return self

    def invoke(self, messages):
        self.messages = messages
        raw = AIMessage(content="", response_metadata={"model_name": "fake/model", "token_usage": {"cost": 0.0}},
                        usage_metadata={"input_tokens": 120, "output_tokens": 5, "total_tokens": 125})
        return {"raw": raw, "parsed": CandidatePick(choice=self.choice), "parsing_error": None}


def test_exact_match_returns_the_whole_group(vr6_index):
    r, _ = one(vr6_index, "Zelenskyy", kind="PER")
    assert (r.status, r.how, r.picked_by, r.group.id) == ("resolved", "exact", "only match", "Zelenskyy")
    assert "Volodymyr Zelenskyy" in r.group.names


def test_normalized_spelling(vr6_index):
    r, _ = one(vr6_index, "kyiv", kind="LOC")
    assert (r.how, r.group.id) == ("normalized", "Kyiv")


def test_typed_text_is_tried_when_the_plan_spelling_fails(vr6_index):
    r, _ = one(vr6_index, text="Kiev", name="Kyyiv", kind="LOC")
    assert r.group.id == "Kyiv"


def test_words_match_finds_a_longer_name(vr6_index):
    r, _ = one(vr6_index, "Zelensky")     # only "Volodymyr Zelensky" contains the word
    assert (r.how, r.group.id) == ("normalized", "Zelenskyy") or (r.how, r.group.id) == ("words", "Zelenskyy")


def test_fuzzy_fixes_a_typo(vr6_index):
    r, _ = one(vr6_index, "Kharkov", kind="LOC")
    assert (r.how, r.group.id) == ("fuzzy", "Kharkiv")


def test_fuzzy_never_matches_on_generic_words_alone(vr6_index):
    r, res = one(vr6_index, "Russian Air Force", kind="ORG")
    assert r.status == "not_found"                 # not "Ukrainian Air Force"
    assert "no graph node or article matches" in res.notes[0]


def test_an_event_resolves_to_its_article(vr6_index):
    r, _ = one(vr6_index, "Battle of Bakhmut", kind="EVENT")
    assert (r.how, r.article.title, r.article.paragraphs) == ("article", "Battle of Bakhmut", 3)
    assert r.article.lead_sentence.startswith("The Battle of Bakhmut was a major battle")
    assert r.group is None


def test_the_expected_kind_filters_candidates(vr6_index):
    r, _ = one(vr6_index, "Bakhmut", kind="LOC")
    assert r.group.type == "LOC"


def test_several_comparable_matches_without_an_llm_take_the_strongest(vr6_index):
    r, _ = one(vr6_index, "Avdiivka")     # a plant (6 texts) and an industrial zone (5)
    assert r.picked_by == "strongest" and r.group.id == "Avdiivka Coke Plant"
    assert [g.id for g in r.alternatives] == ["Avdiivka Industrial Zone"]


def test_the_llm_picks_between_comparable_matches(vr6_index):
    picker = FakePicker("Avdiivka Industrial Zone")
    r, res = one(vr6_index, "Avdiivka", llm=picker)
    assert r.picked_by == "llm" and r.group.id == "Avdiivka Industrial Zone"
    assert [g.id for g in r.alternatives] == ["Avdiivka Coke Plant"]
    assert res.llm_calls[0].step == "resolve"
    sent = picker.messages[1][1]
    assert "id: Avdiivka Coke Plant | ORG" in sent and "id: Avdiivka Industrial Zone | LOC, industrial" in sent


def test_an_unsure_llm_falls_back_to_the_strongest(vr6_index):
    r, _ = one(vr6_index, "Avdiivka", llm=FakePicker("unsure"))
    assert r.picked_by == "strongest" and r.group.id == "Avdiivka Coke Plant"


def test_concept_candidates_need_a_firm_match(vr6_index):
    plan = plan_with(concepts=[Concept(text="the Russian military", candidates=[
        ConceptCandidate(name="General Staff", kind="ORG"),
        ConceptCandidate(name="Ministry of Defence of the Russian Federation", kind="ORG")])])
    res = resolve(plan, vr6_index)
    found = {c.name: c.status for c in res.concepts[0].candidates}
    assert found == {"General Staff": "resolved", "Ministry of Defence of the Russian Federation": "not_found"}


def test_a_follow_up_item_becomes_a_resolved_entity(vr6_index):
    plan = plan_with(follow_up=FollowUp(kind="item", item_number=2, target_id="Kiev", target_label="Kiev"))
    res = resolve(plan, vr6_index)
    assert res.entities[0].group.id == "Kyiv"
