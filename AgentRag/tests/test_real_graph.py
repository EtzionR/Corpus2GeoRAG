"""Checks against the graph team's real knowledge graphs - the files the agent reads: the graph with dates
(the default) and the graph without dates (the fallback, GRAPH_PATH in .env).

If one of these starts failing after a `git pull`, the graph's format or content changed in a way the
agent depends on; graph_index.py is the place to adapt to it. Loading a real graph takes ~15 s.
"""
import pytest

import dates as D
import graph_tools as T
from graph_index import DEFAULT_GRAPH_PATH, GRAPH_WITHOUT_DATES, GraphIndex
from resolver import Resolution, resolve_name

pytestmark = pytest.mark.skipif(not DEFAULT_GRAPH_PATH.is_file(), reason=f"real graph not found at {DEFAULT_GRAPH_PATH}")


@pytest.fixture(scope="module", params=["with dates", "without dates"])
def real(request):
    path = DEFAULT_GRAPH_PATH if request.param == "with dates" else GRAPH_WITHOUT_DATES
    if not path.is_file():
        pytest.skip(f"real graph not found at {path}")
    return GraphIndex.load(str(path))


def test_format_is_what_the_agent_expects(real):
    types = {d.get("type") for _, d in real.G.nodes(data=True)}
    assert {"TEXT", "PER", "ORG", "LOC"} <= types <= {"TEXT", "PER", "ORG", "LOC", "DATE"}   # DATE: the graph with dates
    assert not any(real.G.nodes[n].get("type") == "DATE" for n in real.entities)              # a date is not a name
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


def test_no_pin_in_alabama_or_sheffield(real):
    oval = real.group("Oval Office").place
    assert oval is None or "Alabama" not in (oval.address or "")      # P2-79: White House is an ORG in the graph with dates
    if "Donetsk city" in real.G:
        assert "Sheffield" not in (real.G.nodes["Donetsk city"].get("address") or "")


def test_the_graph_with_dates_dates_the_invasion(real):
    if not D.has_dates(real):
        pytest.skip("the graph without dates")
    day = D.parse_period(["24 February 2022"])
    texts = D.texts_in(real, day)
    assert len(texts) > 300                                            # the README: DATE_2022-02-24 has 440 texts
    places, _ = T.names_in_texts(real, texts)
    assert {"Kyiv", "Kharkiv"} <= {h.group.id for h in places[:10]}
