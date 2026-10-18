"""Shared fixtures. No test here calls OpenRouter or needs an API key.

The stand-in graph is the notebook's small graph, built exactly the way the graph team's script
builds the real one (PER/LOC/ORG nodes, CO_OCCURS_WITH edges with evidence + source_doc). It's
used here so tests stay stable when the real graph changes; the agent itself never falls back
to it.
"""
import json
import sys
from pathlib import Path

import networkx as nx
import pytest
from langchain_core.messages import AIMessage

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # the AgentRag folder

import agent
import georag_agent
from graph_client import NetworkXGraphClient


def build_stand_in_graph() -> nx.DiGraph:
    G = nx.DiGraph()
    G.add_node("Vladimir Putin", type="PER")
    G.add_node("Volodymyr Zelenskyy", type="PER")
    G.add_node("Moscow", type="LOC", latitude=55.7558, longitude=37.6173, address="Moscow, Russia")
    G.add_node("Kyiv", type="LOC", latitude=50.4501, longitude=30.5234, address="Kyiv, Ukraine")
    G.add_node("Kharkiv", type="LOC", latitude=49.9935, longitude=36.2304, address="Kharkiv, Ukraine")
    G.add_node("Kherson", type="LOC", latitude=46.6354, longitude=32.6169, address="Kherson, Ukraine")
    G.add_node("Russian Armed Forces", type="ORG")
    G.add_node("Armed Forces of Ukraine", type="ORG")

    G.add_edge("Vladimir Putin", "Moscow", relation="CO_OCCURS_WITH",
               evidence="Putin is based in Moscow, the capital of Russia.", source_doc="Vladimir_Putin.txt")
    G.add_edge("Russian Armed Forces", "Kharkiv", relation="CO_OCCURS_WITH",
               evidence="A drone attack struck Kharkiv overnight, launched by Russian forces.",
               source_doc="2025_Kharkiv_strikes.txt")
    G.add_edge("Russian Armed Forces", "Kyiv", relation="CO_OCCURS_WITH",
               evidence="Kyiv was targeted in a drone attack early Tuesday.", source_doc="Kyiv_drone_attacks.txt")
    G.add_edge("Volodymyr Zelenskyy", "Kyiv", relation="CO_OCCURS_WITH",
               evidence="Zelenskyy addressed the nation from Kyiv.", source_doc="Zelenskyy_address.txt")
    G.add_edge("Armed Forces of Ukraine", "Kherson", relation="CO_OCCURS_WITH",
               evidence="Kherson city remains under the control of the Armed Forces of Ukraine as of September 2026.",
               source_doc="Kherson_status_2026.txt")
    return G


@pytest.fixture
def graph() -> NetworkXGraphClient:
    return NetworkXGraphClient(build_stand_in_graph())


@pytest.fixture
def graph_json_path(tmp_path):
    path = tmp_path / "stand_in_graph.json"
    path.write_text(json.dumps(nx.node_link_data(build_stand_in_graph(), edges="edges")), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def no_real_llm(monkeypatch):
    """Make sure no test can reach OpenRouter, even if the developer has a real .env."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def fresh_graph_cache(monkeypatch):
    """georag_agent keeps the loaded graph for the life of the process; tests start without it."""
    monkeypatch.setattr(georag_agent, "_graph", None)


class FakeLLM:
    """Stands in for the OpenRouter client. Replays scripted tool-call turns for the tool loop,
    then returns a fixed LLMDraft from the synthesis step."""

    def __init__(self, tool_turns=(), draft=None, error=None):
        self.tool_turns = [list(turn) for turn in tool_turns]   # each turn: [(tool_name, args), ...]
        self.draft = draft
        self.error = error
        self.synthesis_input = None

    def bind_tools(self, tools):
        self.bound_tool_names = [t.name for t in tools]
        return self

    def invoke(self, messages):
        if self.error:
            raise self.error
        calls = self.tool_turns.pop(0) if self.tool_turns else []
        return AIMessage(content="" if calls else "done",
                         tool_calls=[{"name": n, "args": a, "id": f"call_{i}"} for i, (n, a) in enumerate(calls)])

    def with_structured_output(self, schema, method=None):
        fake = self

        class _Structured:
            def invoke(self, messages):
                fake.synthesis_input = messages
                return fake.draft

        return _Structured()


@pytest.fixture
def use_fake_llm(monkeypatch):
    """Install a FakeLLM in place of OpenRouter: use_fake_llm(tool_turns=[...], draft=LLMDraft(...)).
    Returns it, so it can also be passed straight to run_tool_loop / generate_answer."""
    def install(**kwargs):
        fake = FakeLLM(**kwargs)
        monkeypatch.setattr(agent, "get_llm", lambda api_key=None: fake)
        return fake
    return install
