import httpx
import openai
import pytest

import agent
from agent import (LLMDraft, RetrievalContext, build_response, make_tools, resolve_entity_name,
                   run_agent, run_tool_loop)


# --- resolve_entity_name: the four tiers, same cases as the notebook -------------------------

NAMES = ["Vladimir Putin", "Volodymyr Zelenskyy", "Moscow", "Kyiv", "Kharkiv", "Kherson"]


def test_exact_match_is_case_insensitive():
    assert resolve_entity_name("kyiv", NAMES) == {"status": "resolved", "match": "Kyiv", "note": None}


def test_typo_resolves_to_closest_match_with_a_note():
    res = resolve_entity_name("Kharkov", NAMES)
    assert res["status"] == "resolved" and res["match"] == "Kharkiv"
    assert "closest match" in res["note"]


def test_unique_substring_resolves():
    res = resolve_entity_name("Zelenskyy", NAMES)
    assert res["match"] == "Volodymyr Zelenskyy" and "substring" in res["note"]


def test_unknown_name_is_not_found():
    assert resolve_entity_name("Zzznonexistent", NAMES) == {"status": "not_found", "candidates": []}


def test_colliding_names_are_reported_not_guessed():
    res = resolve_entity_name("Ivan", ["Ivan Ivanov", "Ivan Petrenko", "Kyiv"])
    assert res == {"status": "ambiguous", "candidates": ["Ivan Ivanov", "Ivan Petrenko"]}


# --- the tools -------------------------------------------------------------------------------

def tools_for(graph):
    ctx = RetrievalContext(graph)
    return ctx, {t.name: t for t in make_tools(ctx)}


def test_find_entities_reports_correction_and_coordinates(graph):
    _, tools = tools_for(graph)
    out = tools["find_entities"].invoke({"name": "Kharkov"})
    assert out.startswith("Found: id=Kharkiv, type=location, lat=49.9935, lon=36.2304")
    assert "closest match was 'Kharkiv'" in out
    assert tools["find_entities"].invoke({"name": "Zzz"}) == "No entity found matching 'Zzz'."


def test_get_related_returns_evidence_and_logs_citations(graph):
    ctx, tools = tools_for(graph)
    out = tools["get_related"].invoke({"entity_id": "Kherson"})
    assert "Armed Forces of Ukraine" in out and "source: Kherson_status_2026.txt" in out
    assert ctx.citations == {"Kherson": {"Kherson_status_2026.txt"},
                             "Armed Forces of Ukraine": {"Kherson_status_2026.txt"}}
    assert "Call find_entities first" in tools["get_related"].invoke({"entity_id": "Kharkov"})


def test_search_mentions_logs_citations_for_both_ends(graph):
    ctx, tools = tools_for(graph)
    out = tools["search_mentions"].invoke({"keyword": "drone attack"})
    assert out.count("\n") == 1   # two hits
    assert ctx.citations["Kyiv"] == {"Kyiv_drone_attacks.txt"}
    assert ctx.citations["Russian Armed Forces"] == {"2025_Kharkiv_strikes.txt", "Kyiv_drone_attacks.txt"}


def test_each_request_keeps_its_own_citations(graph):
    """The notebook's global CTX would mix these two up when requests overlap."""
    ctx_a, tools_a = tools_for(graph)
    ctx_b, tools_b = tools_for(graph)
    tools_a["get_related"].invoke({"entity_id": "Moscow"})
    tools_b["get_related"].invoke({"entity_id": "Kherson"})
    assert set(ctx_a.citations) == {"Moscow", "Vladimir Putin"}
    assert set(ctx_b.citations) == {"Kherson", "Armed Forces of Ukraine"}


# --- the tool-calling loop -------------------------------------------------------------------

def test_tool_loop_runs_calls_and_collects_evidence(graph, use_fake_llm):
    fake = use_fake_llm(tool_turns=[[("find_entities", {"name": "Kharkov"})],
                                    [("get_related", {"entity_id": "Kharkiv"})]])
    evidence, citations, transcript = run_tool_loop("Tell me about Kharkov.", graph, fake)
    assert fake.bound_tool_names == ["find_entities", "get_related", "search_mentions"]
    assert [name for name, _, _ in transcript] == ["find_entities", "get_related"]
    assert "[get_related({'entity_id': 'Kharkiv'})]" in evidence
    assert citations["Kharkiv"] == {"2025_Kharkiv_strikes.txt"}


def test_tool_loop_stops_at_max_iterations(graph, use_fake_llm):
    fake = use_fake_llm(tool_turns=[[("find_entities", {"name": "Kyiv"})]] * 10)
    _, _, transcript = run_tool_loop("q", graph, fake, max_iterations=3)
    assert len(transcript) == 3


def test_bad_tool_calls_become_messages_not_crashes(graph, use_fake_llm):
    fake = use_fake_llm(tool_turns=[[("delete_graph", {}), ("get_related", {"wrong_arg": 1})]])
    _, _, transcript = run_tool_loop("q", graph, fake)
    assert transcript[0][2].startswith("Unknown tool 'delete_graph'")
    assert transcript[1][2].startswith("Invalid arguments for get_related")


# --- synthesis and the trust boundary --------------------------------------------------------

def test_build_response_takes_coordinates_and_sources_only_from_the_graph(graph):
    draft = LLMDraft(answer="According to the corpus...",
                     feature_node_ids=["Kharkiv", "Atlantis", "Vladimir Putin", "Kyiv", "Kharkiv"])
    citations = {"Kharkiv": {"b.txt", "a.txt"}, "Kyiv": {"c.txt", "a.txt"}, "Atlantis": {"fake.txt"}}
    resp = build_response(draft, graph, citations)

    # Atlantis isn't in the graph, Putin has no coordinates, the second Kharkiv is a duplicate
    assert [g.id for g in resp.geo_locations] == ["Kharkiv", "Kyiv"]
    kharkiv = resp.geo_locations[0]
    assert kharkiv.geometry.coordinates == (36.2304, 49.9935)   # [lon, lat], from the graph
    assert kharkiv.kind == "place" and kharkiv.sources == ["a.txt", "b.txt"]
    assert resp.sources == ["a.txt", "b.txt", "c.txt"]


def test_generate_answer_rejects_a_missing_draft(use_fake_llm):
    fake = use_fake_llm(draft=None)
    with pytest.raises(agent.LLMError):
        agent.generate_answer("q", "evidence", fake)


def test_run_agent_end_to_end(graph, use_fake_llm):
    fake = use_fake_llm(tool_turns=[[("search_mentions", {"keyword": "drone attack"})]],
                        draft=LLMDraft(answer="According to the corpus, Kharkiv and Kyiv were hit.",
                                       feature_node_ids=["Kharkiv", "Kyiv"]))
    resp = run_agent("Show me where drone attacks took place.", graph)
    assert resp.answer.startswith("According to the corpus")
    assert [g.id for g in resp.geo_locations] == ["Kharkiv", "Kyiv"]
    assert set(resp.sources) == {"2025_Kharkiv_strikes.txt", "Kyiv_drone_attacks.txt"}
    assert "A drone attack struck Kharkiv" in fake.synthesis_input[1][1]   # evidence reached synthesis


# --- LLM setup and errors --------------------------------------------------------------------

def test_missing_key_raises_a_clear_error():
    with pytest.raises(agent.LLMNotConfiguredError, match="api_key"):
        agent.get_llm()


def test_key_comes_from_the_argument_or_else_the_environment(monkeypatch):
    def key_of(llm):
        return llm.openai_api_key.get_secret_value()
    assert key_of(agent.get_llm(api_key="sk-or-test-from-arg")) == "sk-or-test-from-arg"
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-from-env")
    assert key_of(agent.get_llm()) == "sk-or-test-from-env"
    assert key_of(agent.get_llm(api_key="sk-or-test-from-arg")) == "sk-or-test-from-arg"


def test_model_is_the_hardcoded_constant_and_the_key_is_not_exposed(monkeypatch):
    monkeypatch.setenv("MODEL", "some/other-model")
    llm = agent.get_llm(api_key="sk-or-test-not-a-real-key")   # builds the client only, no network call
    assert llm.model_name == agent.MODEL == "openrouter/free"
    assert "sk-or-test-not-a-real-key" not in repr(llm)


def _openai_error(cls, status):
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    if cls is openai.APIConnectionError:
        return cls(request=request)
    return cls("provider says no", response=httpx.Response(status, request=request), body=None)


@pytest.mark.parametrize("error, expected", [
    (_openai_error(openai.AuthenticationError, 401), agent.LLMNotConfiguredError),
    (_openai_error(openai.RateLimitError, 429), agent.LLMRateLimitError),
    (_openai_error(openai.InternalServerError, 500), agent.LLMError),
    (_openai_error(openai.APIConnectionError, None), agent.LLMError),
])
def test_openrouter_errors_become_readable_agent_errors(graph, use_fake_llm, error, expected):
    use_fake_llm(error=error)
    with pytest.raises(expected) as caught:
        run_agent("q", graph)
    assert isinstance(caught.value, agent.AgentError) and str(caught.value)
