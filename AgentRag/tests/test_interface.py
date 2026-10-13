"""The two functions the UI calls: georag_agent.query() and georag_agent.get_source_text()."""
import pytest

import agent
import georag_agent
from agent import LLMDraft
from georag_agent import AgentError, InvalidRequestError, LLMNotConfiguredError, get_source_text, query


@pytest.fixture(autouse=True)
def stand_in_graph_file(monkeypatch, graph_json_path):
    monkeypatch.setenv("GRAPH_PATH", str(graph_json_path))


def test_query_returns_the_contract_shape_as_plain_dicts(use_fake_llm):
    use_fake_llm(tool_turns=[[("find_entities", {"name": "Kharkov"})], [("get_related", {"entity_id": "Kharkiv"})]],
                 draft=LLMDraft(answer="According to the corpus...", feature_node_ids=["Kharkiv"]))
    result = query("Tell me about Kharkov.",
                   geo_location={"type": "point", "coordinates": [36.23, 49.99], "radius_m": 500})
    assert result == {
        "answer": "According to the corpus...",
        "geo_locations": [{"id": "Kharkiv", "label": "Kharkiv", "kind": "place",
                           "geometry": {"type": "point", "coordinates": [36.2304, 49.9935]},
                           "sources": ["2025_Kharkiv_strikes.txt"]}],
        "sources": ["2025_Kharkiv_strikes.txt"],
    }


def test_a_previous_result_can_be_sent_back_as_chat_history(use_fake_llm):
    use_fake_llm(draft=LLMDraft(answer="According to the corpus...", feature_node_ids=["Kyiv"]))
    first = query("Where is Kyiv?")
    second = query("Tell me more about number 1", chat_history=[{"query": "Where is Kyiv?", "response": first}])
    assert second["answer"]


@pytest.mark.parametrize("kwargs", [
    {"text_prompt": ""},
    {"text_prompt": "q", "geo_location": {"type": "point", "coordinates": [30.5, 95]}},          # lat out of range
    {"text_prompt": "q", "geo_location": {"type": "polygon", "coordinates": [[[30, 50], [31, 50], [30, 50]]]}},
    {"text_prompt": "q", "geo_location": {"type": "bbox", "coordinates": [30, 50, 31, 51]}},     # not a contract type
])
def test_bad_input_raises_invalid_request_before_any_llm_call(kwargs):
    with pytest.raises(InvalidRequestError, match="Invalid request"):
        query(**kwargs)


def test_missing_key_raises_a_readable_agent_error():
    with pytest.raises(LLMNotConfiguredError) as caught:
        query("Where is Moscow?")
    assert isinstance(caught.value, AgentError)
    assert "https://openrouter.ai/keys" in str(caught.value)


def test_api_key_argument_reaches_the_llm_client(monkeypatch, use_fake_llm):
    fake = use_fake_llm(draft=LLMDraft(answer="ok"))
    keys_seen = []

    def fake_get_llm(api_key=None):
        keys_seen.append(api_key)
        return fake

    monkeypatch.setattr(agent, "get_llm", fake_get_llm)
    query("Where is Moscow?", api_key="sk-or-test-key")
    assert keys_seen == ["sk-or-test-key"]


def test_get_source_text_returns_the_passages_for_a_pointer():
    assert get_source_text("Kherson_status_2026.txt") == {
        "text": "Kherson city remains under the control of the Armed Forces of Ukraine as of September 2026.",
        "document": "Kherson_status_2026.txt",
    }
    assert get_source_text("nope.txt") is None


def test_missing_graph_file_raises_agent_error(monkeypatch, tmp_path):
    monkeypatch.setenv("GRAPH_PATH", str(tmp_path / "missing.json"))
    with pytest.raises(AgentError, match="Knowledge graph not found"):
        get_source_text("anything")


def test_graph_is_loaded_once(monkeypatch):
    get_source_text("Kherson_status_2026.txt")
    loaded = georag_agent._graph
    get_source_text("Kyiv_drone_attacks.txt")
    assert georag_agent._graph is loaded
