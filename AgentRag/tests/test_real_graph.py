"""Checks against the graph team's real knowledge_graph.json - the file the agent reads.

If one of these starts failing after a `git pull`, the graph's schema or content changed in a
way the agent depends on; NetworkXGraphClient is the place to adapt to it.
"""
import pytest

import georag_agent
from agent import resolve_entity_name
from georag_agent import DEFAULT_GRAPH_PATH
from graph_client import NetworkXGraphClient, load_node_link_json

pytestmark = pytest.mark.skipif(not DEFAULT_GRAPH_PATH.is_file(),
                                reason=f"real graph not found at {DEFAULT_GRAPH_PATH}")


@pytest.fixture(scope="module")
def real_G():
    return load_node_link_json(str(DEFAULT_GRAPH_PATH))


def test_schema_is_what_the_adapter_expects(real_G):
    types = {attrs.get("type") for _, attrs in real_G.nodes(data=True)}
    assert types <= {"PER", "LOC", "ORG"}
    for nid, attrs in real_G.nodes(data=True):
        if attrs.get("type") == "LOC":
            assert attrs.get("latitude") is not None and attrs.get("longitude") is not None, nid
    for u, v, attrs in real_G.edges(data=True):
        assert attrs.get("evidence") and attrs.get("source_doc"), (u, v)


def test_notebook_resolution_cases_still_hold(real_G):
    names = [n.name for n in NetworkXGraphClient(real_G).find_nodes()]
    assert resolve_entity_name("Kyiv", names)["match"] == "Kyiv"
    assert resolve_entity_name("Kharkov", names)["match"] == "Kharkiv"
    assert resolve_entity_name("Zzznonexistent", names)["status"] == "not_found"


def test_agent_reads_the_real_graph_by_default(monkeypatch, real_G):
    monkeypatch.delenv("GRAPH_PATH", raising=False)
    pointer = next(iter(real_G.edges(data=True)))[2]["source_doc"]
    assert georag_agent.get_source_text(pointer)["document"] == pointer
    assert georag_agent.get_graph().G.number_of_nodes() == real_G.number_of_nodes()
