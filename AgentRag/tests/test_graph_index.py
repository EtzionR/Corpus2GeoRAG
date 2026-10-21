"""graph_index: loading the Vr6 format, normalization, variant groups, places, articles."""
import gzip
import json

import networkx as nx
import pytest

from graph_index import GraphIndex, normalize
from tests_support import names_of


def test_normalize_handles_case_spaces_punctuation_and_spelling():
    assert normalize("Volodymyr Zelenskyy") == "volodymyr zelenskyy"
    assert normalize(" Putin. ") == "putin"
    assert normalize("The Wagner Group") == "wagner group"
    assert normalize("Ministry of Defense") == normalize("ministry of defence")
    assert normalize("Kyiv’s") == "kyiv's"


def test_spellings_of_one_person_are_one_group(vr6_index):
    group = names_of(vr6_index, "Zelenskyy")
    assert {"Zelenskyy", "Volodymyr Zelenskyy", "Volodomyr Zelenskyy", "Volodymyr Zelensky"} <= group
    assert "of President Zelenskyy" not in group      # a fragment, not a clean name
    assert "Olena Zelenska" not in group              # a different person (and the female form)


def test_a_bare_surname_joins_only_a_dominant_person(vr6_index):
    assert vr6_index.group_of["Gerasimov"] == vr6_index.group_of["Valery Gerasimov"]   # 10 of 11 texts
    assert vr6_index.group_of["Andrei Gerasimov"] != vr6_index.group_of["Valery Gerasimov"]
    assert vr6_index.group_of["Ivanov"] == "Ivanov"   # split between two people: stays alone


def test_organization_name_extras_merge_but_real_differences_dont(vr6_index):
    assert {"Wagner", "Wagner Group", "PMC Wagner"} <= names_of(vr6_index, "Wagner")
    assert "Wagner Orchestra" not in names_of(vr6_index, "Wagner")
    assert "Africa Corps" not in names_of(vr6_index, "Wagner")   # SAME_AS, but no shared word


def test_junk_same_as_is_ignored(vr6_index):
    assert names_of(vr6_index, "NATO") == {"NATO"}


def test_locations_with_the_same_point_and_type_merge(vr6_index):
    assert names_of(vr6_index, "Kiev") == {"Kyiv", "Kiev"}       # "Kyiv City" is a shop elsewhere


def test_group_summary(vr6_index):
    g = vr6_index.group("Kiev")
    assert g.id == "Kyiv" and g.type == "LOC" and g.texts == 25 and g.own_article == "Kyiv"
    assert (g.place.lat, g.place.lon, g.place.place_type, g.place.uncertain) == (50.45, 30.52, "city", False)
    assert vr6_index.group("Novorossiya").place is None


def test_suspicious_geocode_is_flagged_not_hidden(vr6_index):
    place = vr6_index.group("Donbas").place
    assert place.uncertain and "road" in place.uncertain_reason and place.lat == 41.99


def test_articles_and_lead_sentence(vr6_index):
    assert len(vr6_index.articles["Battle of Bakhmut"]) == 3
    assert vr6_index.lead_sentence("Valery Gerasimov") == "Valery Gerasimov is a Russian army general."
    assert vr6_index.lead_sentence("No such article") is None


def test_load_reads_the_gzip_node_link_file(tmp_path):
    from conftest import build_vr6_graph
    path = tmp_path / "knowledge_graph.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(nx.node_link_data(build_vr6_graph(), edges="links"), f)
    gi = GraphIndex.load(str(path))
    assert gi.load_seconds is not None and gi.group("Kiev").id == "Kyiv"


def test_missing_graph_file_is_a_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="GRAPH_PATH"):
        GraphIndex.load(str(tmp_path / "missing.json.gz"))


def test_reference_sections_are_dropped_with_what_only_they_mention():
    import graph_tools as T
    from conftest import build_vr6_graph
    from graph_index import GraphIndex
    G = build_vr6_graph()
    text = "В Україні створили модель дрона. Kyiv Post"
    G.add_node("TEXT_9000", type="TEXT", text_id=9000, text=text, source="Stuhna Battalion", index=7,
               title="Sources", sub_title=None)
    G.add_node("Україні", type="LOC", latitude=50.4506, longitude=30.5289, place_type="office", importance=0.65,
               address="National Academy of Sciences of Ukraine", geometry_wkt="POINT (30.5289 50.4506)")
    G.add_edge("Україні", "TEXT_9000", weight=1, relations={"IN_THE_TEXT": [{"start": 2, "end": 9}]})
    G.add_edge("Kyiv", "TEXT_9000", weight=1, relations={"IN_THE_TEXT": [{"start": 33, "end": 37}]})
    G.add_edge("Kyiv", "Україні", weight=1, relations={"CO_OCCURS_WITH": [
        {"text_id": 9000, "source_start": 33, "source_end": 37, "target_start": 2, "target_end": 9,
         "subject": None, "confidence": None}]})
    # a container only mentioned in a reference list: the real graph hangs all of Russia's regions from "РФ"
    G.add_node("РФ", type="LOC", latitude=60.0, longitude=90.0, place_type="country", importance=0.9,
               address="Russia", geometry_wkt="POINT (90 60)")
    G.add_edge("РФ", "TEXT_9000", weight=1, relations={"IN_THE_TEXT": [{"start": 0, "end": 1}]})
    G.add_node("Kursk Oblast", type="LOC", latitude=51.7, longitude=36.2, place_type="state", importance=0.6,
               address="Kursk Oblast, Russia", geometry_wkt="POINT (36.2 51.7)")
    G.add_node("TEXT_9001", type="TEXT", text_id=9001, text="Kursk Oblast borders Ukraine.", source="Kursk",
               index=0, title=None, sub_title=None)
    G.add_edge("Kursk Oblast", "TEXT_9001", weight=1, relations={"IN_THE_TEXT": [{"start": 0, "end": 12}]})
    G.add_edge("Kursk Oblast", "РФ", weight=0.1, relations={"INSIDE": [{"subject": "Kursk Oblast", "basis": "geometry"}]})
    gi = GraphIndex(G)
    assert gi.dropped == {"paragraphs": 1, "records": 1, "entities": 1, "kept_for_hierarchy": 1}
    assert "TEXT_9000" not in gi.G and "Україні" not in gi.G      # only mentioned in a reference list
    assert T.parents(gi, "Kursk Oblast") == ["Kursk Oblast", "РФ"]    # the hierarchy holds
    assert "РФ" not in [h.group.id for h in T.places_near(gi, 90.0, 60.0, 1000)]   # but it's no search result
    assert gi.group("Kyiv").texts == 25                             # Kyiv keeps its real paragraphs
    assert "SAME_AS" in gi.G["Kyiv"]["Kiev"]["relations"]           # records from other paragraphs stay


def test_a_city_geocoded_as_a_river_is_flagged():
    from conftest import build_vr6_graph
    from graph_index import GraphIndex
    G = build_vr6_graph()
    for i, (name, ptype, lead) in enumerate([("Dnipro", "river", "Dnipro is Ukraine's fourth-largest city."),
                                             ("Bakhmutka", "river", "The Bakhmutka is a river in Donetsk Oblast.")]):
        G.add_node(name, type="LOC", latitude=51.55, longitude=30.6 + i, place_type=ptype, importance=0.5,
                   address=name, geometry_wkt=f"POINT ({30.6 + i} 51.55)")
        G.add_node(f"TEXT_{8000 + i}", type="TEXT", text_id=8000 + i, text=lead, source=name, index=0,
                   title=None, sub_title=None)
        G.add_edge(name, f"TEXT_{8000 + i}", weight=1, relations={"IN_THE_TEXT": [{"start": 0, "end": len(name)}]})
    gi = GraphIndex(G)
    dnipro = gi.group("Dnipro").place
    assert dnipro.uncertain and dnipro.uncertain_reason == "geocoded as a river, but its own article describes a city or town"
    assert not gi.group("Bakhmutka").place.uncertain               # a real river stays a river
