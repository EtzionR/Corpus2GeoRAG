"""The two functions the UI calls - georag_agent.query() and get_source_text() - on a small Vr6-format
graph, with the LLM faked (it plans and writes). Covers the whole flow, steps 1-6."""
import gzip
import json

import networkx as nx
import pytest
from langchain_core.messages import AIMessage

import agent
import georag_agent
from conftest import build_vr6_graph
from georag_agent import AgentError, InvalidRequestError, LLMNotConfiguredError, get_source_text, query
from planner import EntityMention, PlanDraft
from writer import WriteDraft


@pytest.fixture(autouse=True)
def vr6_graph_file(monkeypatch, tmp_path):
    path = tmp_path / "knowledge_graph.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(nx.node_link_data(build_vr6_graph(), edges="links"), f)
    monkeypatch.setenv("GRAPH_PATH", str(path))


class FakeAgentLLM:
    """Plans with `plan` and writes with `answer`; records what it was sent."""

    def __init__(self, plan: PlanDraft, answer: WriteDraft):
        self.plan, self.answer, self.sent = plan, answer, []

    def with_structured_output(self, schema, **kwargs):
        fake = self

        class _Call:
            def invoke(self, messages):
                fake.sent.append((schema.__name__, messages))
                raw = AIMessage(content="", response_metadata={"model_name": "fake/model", "token_usage": {"cost": 0.0005}},
                                usage_metadata={"input_tokens": 500, "output_tokens": 50, "total_tokens": 550})
                parsed = fake.plan if schema is PlanDraft else fake.answer
                return {"raw": raw, "parsed": parsed, "parsing_error": None}
        return _Call()


def install(monkeypatch, plan=None, answer=None):
    fake = FakeAgentLLM(plan or PlanDraft(type="other"), answer or WriteDraft(answer="Nothing."))
    monkeypatch.setattr(agent, "get_llm", lambda api_key=None: fake)
    return fake


def test_full_flow_place_lookup(monkeypatch):
    install(monkeypatch, answer=WriteDraft(answer="Kyiv [1] is the capital of Ukraine [L1].", places_discussed=[1]))
    result = query("Where is Kyiv?")   # the fast path plans it; the fake LLM writes
    assert result["status"] == "answered" and result["grounded"] and result["shape"] == "fact"
    assert result["answer_plain"] == "Kyiv is the capital of Ukraine."
    kyiv = result["geo_locations"][0]
    assert (kyiv["number"], kyiv["id"], kyiv["role"]) == (1, "Kyiv", "primary")
    assert kyiv["geometry"] == {"type": "Point", "coordinates": [30.52, 50.45]}
    assert kyiv["shape"]["type"] == "Polygon"                     # the city outline from the graph
    assert result["citations"][0]["id"] == "L1" and result["citations"][0]["article"] == "Kyiv"
    assert result["sources"] == [result["citations"][0]["pointer"]]
    assert kyiv["sources"] == result["sources"]                   # found by name: its own article's lead paragraph
    w, s, e, n = result["map"]["bbox"]
    assert w < 30.52 < e and s < 50.45 < n and result["map"]["highlight"] == [1]
    assert result["meta"]["question_type"] == "place_lookup" and result["meta"]["llm_calls"] == 1


def test_a_list_answer_carries_every_place_and_the_regions(monkeypatch):
    monkeypatch.setattr("evidence.LIST_MIN_PLACES", 1)   # 2 places: a list
    install(monkeypatch, plan=PlanDraft(type="event_places", entities=[
        EntityMention(text="Battle of Bakhmut", name="Battle of Bakhmut", kind="EVENT")]),
        answer=WriteDraft(answer="The battle centred on Bakhmut [1].", places_discussed=[1]))
    result = query("Which places were part of the Battle of Bakhmut?")
    assert result["shape"] == "list" and [p["id"] for p in result["geo_locations"]] == ["Bakhmut", "Soledar"]
    assert [p["role"] for p in result["geo_locations"]] == ["primary", "context"]
    assert not any("shape" in p for p in result["geo_locations"])     # a list gets pins only (P2-73)
    assert result["regions"][0]["id"] == "Ukraine" and result["regions"][0]["count"] == 2


def test_nothing_found_is_labelled(monkeypatch):
    install(monkeypatch, answer=WriteDraft(answer="I don't know."))
    result = query("What is a good pasta recipe?")
    assert result["status"] == "no_data" and result["grounded"] is False
    assert result["answer"].startswith("No data from the graph — answer from the LLM only.")
    assert result["geo_locations"] == []


def test_follow_up_by_number_uses_the_previous_results_numbers(monkeypatch):
    fake = install(monkeypatch, plan=PlanDraft(type="follow_up", follow_up_kind="item", follow_up_item=2),
                   answer=WriteDraft(answer="Soledar [1] is near Bakhmut."))
    previous = {"answer": "...", "geo_locations": [{"number": 1, "id": "Bakhmut", "label": "Bakhmut"},
                                                   {"number": 2, "id": "Soledar", "label": "Soledar"}]}
    result = query("Tell me about number 2", chat_history=[{"query": "q", "response": previous}])
    assert result["geo_locations"][0]["id"] == "Soledar"
    sent_plan = next(m for name, m in fake.sent if name == "PlanDraft")
    assert "1. Bakhmut, 2. Soledar" in sent_plan[1][1]
    # the writer reads the place's name, not "number 2": in the new answer Soledar is [1], not [2]
    sent_write = next(m for name, m in fake.sent if name == "WriteDraft")
    assert sent_write[1][1].startswith("QUESTION: Tell me about Soledar\n")


def test_a_topic_with_no_area_asks_for_one(monkeypatch):
    fake = install(monkeypatch, plan=PlanDraft(type="area_topic", keywords=["drone"]))
    result = query("Show me where drone attacks happened")         # no place named, nothing selected
    assert result["answer"].startswith("There is no area to search")
    assert 'name a place (for example "drone in Kharkiv")' in result["answer"]
    assert result["status"] == "no_data" and result["geo_locations"] == []
    assert not any(name == "WriteDraft" for name, _ in fake.sent)        # no LLM call to say so


def test_a_number_the_previous_answer_doesnt_have_gets_a_plain_reply(monkeypatch):
    fake = install(monkeypatch, plan=PlanDraft(type="follow_up", follow_up_kind="item", follow_up_item=4))
    previous = {"answer": "...", "geo_locations": [{"number": 1, "id": "Kyiv", "label": "Kyiv"}]}
    result = query("Tell me about number 4", chat_history=[{"query": "Where is Kyiv?", "response": previous}])
    assert result["answer"].startswith("The previous answer has no place number 4.")
    assert not any(name == "WriteDraft" for name, _ in fake.sent)        # no LLM call to say so


def test_the_map_shows_only_the_discussed_places_unless_the_answer_is_a_list(monkeypatch):
    install(monkeypatch, plan=PlanDraft(type="about", entities=[
        EntityMention(text="Zelenskyy", name="Zelenskyy", kind="PER")]),
        answer=WriteDraft(answer="Zelenskyy visited Kharkiv [2].", places_discussed=[2]))
    result = query("Tell me about Zelenskyy")              # finds Ukraine, Kharkiv, Kyiv
    assert result["shape"] != "list" and [(p["number"], p["id"]) for p in result["geo_locations"]] == [(2, "Kharkiv")]
    assert result["map"]["showing"] == "discussed" and result["map"]["not_shown"] == 2


def test_only_the_asked_place_is_outlined_and_zoomed_to(monkeypatch):
    from graph_index import GraphIndex
    G = build_vr6_graph()
    G.nodes["Russia"]["geometry_wkt"] = "POLYGON ((27 41, 180 41, 180 82, 27 82, 27 41))"
    monkeypatch.setattr(georag_agent, "_graph", GraphIndex(G))
    install(monkeypatch, plan=PlanDraft(type="about", entities=[EntityMention(text="Ukraine", name="Ukraine", kind="LOC")]),
            answer=WriteDraft(answer="Ukraine borders Russia [2] and Belarus [3].", places_discussed=[1, 2, 3]))
    result = query("Tell me about Ukraine")
    assert [(p["id"], "shape" in p) for p in result["geo_locations"]] == [
        ("Ukraine", True), ("Russia", False), ("Belarus", False)]       # Russia and Belarus: pins only
    w, s, e, n = result["map"]["bbox"]
    assert 20 < w and e < 43 and 43 < s and n < 54                  # Ukraine, not Russia's 150 degrees


def test_a_question_about_a_person_outlines_no_place(monkeypatch):
    install(monkeypatch, plan=PlanDraft(type="about", entities=[
        EntityMention(text="Zelenskyy", name="Zelenskyy", kind="PER")]),
        answer=WriteDraft(answer="Zelenskyy visited Kharkiv.", places_discussed=[1, 2, 3]))
    result = query("Tell me about Zelenskyy")              # finds Ukraine, Kharkiv, Kyiv
    assert len(result["geo_locations"]) == 3 and not any("shape" in p for p in result["geo_locations"])
    assert result["map"]["bbox"]                           # zooms to the pins


def test_an_outline_across_the_180th_meridian_zooms_to_its_own_side():
    from result import _map_hint
    from schema import Geometry, PlaceOut
    across_180 = Geometry(type="MultiPolygon", coordinates=[[[[-180, 60], [-170, 60], [-170, 70], [-180, 60]]],
                                                           [[[20, 41], [180, 41], [180, 82], [20, 41]]]])
    russia = PlaceOut(number=1, id="Russia", label="Russia", kind="country", role="primary",
                      geometry=Geometry(type="Point", coordinates=[97.7, 64.7]), shape=across_180)
    # Chukotka's part west of the line is left out: Russia, not every longitude; still inside [-180, 180]
    assert _map_hint([russia], [1]).bbox == [4, 36.9, 180, 86.1]


@pytest.mark.parametrize("geo", [
    {"type": "point", "coordinates": [30.52, 50.45]},                       # lower case accepted
    {"type": "Point", "coordinates": [30.52, 50.45], "radius_m": 500},
    {"type": "Polygon", "coordinates": [[[30, 50], [31, 50], [31, 51], [30, 50]]]},
])
def test_valid_map_selections(monkeypatch, geo):
    install(monkeypatch, plan=PlanDraft(type="area", refers_to_map=True))
    assert query("What is here?", geo_location=geo)["status"] in ("answered", "no_data")


@pytest.mark.parametrize("geo", [
    {"type": "Point", "coordinates": [30.52, 95]},                          # latitude out of range
    {"type": "Polygon", "coordinates": [[[30, 50], [31, 50], [30, 50]]]},   # ring too short
    {"type": "Box", "coordinates": [30, 50, 31, 51]},
])
def test_invalid_map_selections(monkeypatch, geo):
    install(monkeypatch)
    with pytest.raises(InvalidRequestError):
        query("What is here?", geo_location=geo)


def test_missing_key_is_a_readable_error():
    with pytest.raises(LLMNotConfiguredError, match="openrouter.ai/keys"):
        query("Where is Kyiv?")


def test_a_rejected_key_is_a_readable_error(monkeypatch):
    import httpx
    import openai

    class RejectingLLM:
        def with_structured_output(self, schema, **kwargs):
            return self

        def invoke(self, messages):
            response = httpx.Response(401, request=httpx.Request("POST", "https://openrouter.ai/api/v1"))
            raise openai.AuthenticationError("No auth credentials found", response=response, body=None)
    monkeypatch.setattr(agent, "get_llm", lambda api_key=None: RejectingLLM())
    with pytest.raises(LLMNotConfiguredError, match="rejected the API key"):
        query("Tell me about the Battle of Bakhmut")


def test_get_source_text():
    out = get_source_text("TEXT_0")
    assert set(out) == {"pointer", "text", "document", "section", "paragraph_index"}
    assert out["pointer"] == "TEXT_0" and out["text"]
    assert get_source_text(0)["pointer"] == "TEXT_0"
    assert get_source_text("TEXT_999999") is None and get_source_text("nonsense") is None


def test_missing_graph_is_an_agent_error(monkeypatch, tmp_path):
    monkeypatch.setenv("GRAPH_PATH", str(tmp_path / "missing.json.gz"))
    with pytest.raises(AgentError, match="Knowledge graph not found"):
        get_source_text("TEXT_0")


def test_graph_is_loaded_once():
    get_source_text("TEXT_0")
    loaded = georag_agent._graph
    get_source_text("TEXT_1")
    assert georag_agent._graph is loaded


def test_the_asked_place_is_on_the_map_even_if_the_answer_forgets_its_number(monkeypatch):
    install(monkeypatch, plan=PlanDraft(type="about", entities=[EntityMention(text="Bakhmut", name="Bakhmut", kind="LOC")]),
            answer=WriteDraft(answer="Bakhmut saw heavy fighting."))      # no [n] at all
    result = query("Tell me about Bakhmut")
    assert result["geo_locations"][0]["id"] == "Bakhmut" and result["geo_locations"][0]["role"] == "primary"
