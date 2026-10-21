"""Checks against the graph team's real knowledge_graph.json.gz - the file the agent reads.

If one of these starts failing after a `git pull`, the graph's format or content changed in a way the
agent depends on; graph_index.py is the place to adapt to it. Loading the real graph takes ~15 s.
"""
import pytest

import graph_tools as T
from graph_index import DEFAULT_GRAPH_PATH, GraphIndex
from resolver import Resolution, resolve_name

pytestmark = pytest.mark.skipif(not DEFAULT_GRAPH_PATH.is_file(), reason=f"real graph not found at {DEFAULT_GRAPH_PATH}")


@pytest.fixture(scope="module")
def real():
    return GraphIndex.load(str(DEFAULT_GRAPH_PATH))


def test_format_is_what_the_agent_expects(real):
    types = {d.get("type") for _, d in real.G.nodes(data=True)}
    assert types == {"TEXT", "PER", "ORG", "LOC"}
    sample = next(d for _, d in real.G.nodes(data=True) if d.get("type") == "TEXT")
    assert {"text_id", "text", "source", "index"} <= set(sample)
    u, v, d = next(iter(real.G.edges(data=True)))
    assert isinstance(d.get("relations"), dict)


def test_key_places_resolve_with_coordinates_and_outlines(real):
    for typed, expected in [("Kyiv", "Kyiv"), ("Kharkov", "Kharkiv"), ("Bakhmut", "Bakhmut")]:
        r = resolve_name(typed, typed, "LOC", real, "q", None, Resolution())
        assert r.group.id == expected and r.group.place is not None, typed
    assert T.shape_of(real, real.group("Kyiv"))["type"] in ("Polygon", "MultiPolygon")


def test_events_are_articles_and_people_are_grouped(real):
    assert "Battle of Bakhmut" in real.articles
    assert {"Zelenskyy", "Volodymyr Zelenskyy"} <= set(real.groups[real.group_of["Zelenskyy"]])
