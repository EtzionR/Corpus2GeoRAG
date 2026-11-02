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
    place = vr6_index.group("Hrushevsky Street").place
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


def test_a_place_fix_takes_the_point_and_parent_of_the_right_node():
    import graph_tools as T
    from conftest import build_vr6_graph
    from graph_index import GraphIndex
    G = build_vr6_graph()
    G.add_node("Chernihiv Raion", type="LOC", latitude=51.5, longitude=31.3, place_type="county", importance=0.5,
               address="Chernihiv Raion, Ukraine", geometry_wkt="POINT (31.3 51.5)")
    G.add_node("Dnipro Raion", type="LOC", latitude=48.4, longitude=35.0, place_type="county", importance=0.5,
               address="Dnipro Raion, Ukraine", geometry_wkt="POINT (35 48.4)")
    G.add_node("Dnipro", type="LOC", latitude=51.55, longitude=30.61, place_type="river", importance=0.67,
               address="Dnipro, Chernihiv Raion", geometry_wkt="POINT (30.61 51.55)")
    G.add_node("Dnipro City", type="LOC", latitude=48.47, longitude=35.04, place_type="city", importance=0.66,
               address="Dnipro, Dnipro Raion, Ukraine", geometry_wkt="POLYGON ((34.9 48.4, 35.1 48.4, 35.1 48.5, 34.9 48.4))")
    for i, name in enumerate(["Dnipro", "Dnipro City"]):
        G.add_node(f"TEXT_{8100 + i}", type="TEXT", text_id=8100 + i, text=f"{name} was shelled.", source="Dnipro",
                   index=i, title=None, sub_title=None)
        G.add_edge(name, f"TEXT_{8100 + i}", weight=1, relations={"IN_THE_TEXT": [{"start": 0, "end": len(name)}]})
    G.add_edge("Dnipro", "Chernihiv Raion", weight=0.1, relations={"INSIDE": [{"subject": "Dnipro", "basis": "geometry"}]})
    G.add_edge("Dnipro City", "Dnipro Raion", weight=0.1,
               relations={"INSIDE": [{"subject": "Dnipro City", "basis": "geometry"}]})
    gi = GraphIndex(G)
    assert gi.place_fixes == ["Dnipro"]
    place = gi.group("Dnipro").place
    assert (place.lon, place.lat, place.place_type, place.uncertain) == (35.04, 48.47, "city", False)
    assert T.parents(gi, "Dnipro") == ["Dnipro", "Dnipro Raion"]       # no longer inside Chernihiv Raion
    assert not gi.G.has_edge("Dnipro", "Chernihiv Raion")
    assert "Dnipro City" in gi.group("Dnipro").names                  # same point now: one group


def test_a_parent_in_another_country_is_replaced_by_the_own_country():
    import graph_tools as T
    from conftest import build_vr6_graph
    from graph_index import GraphIndex
    G = build_vr6_graph()
    G.add_node("Central Russian Upland", type="LOC", latitude=52.0, longitude=37.0, place_type="natural",
               importance=0.5, address="Central Russian Upland, Russia", geometry_wkt="POINT (37 52)")
    G.add_node("Kharkiv Oblast", type="LOC", latitude=49.6, longitude=36.5, place_type="state", importance=0.6,
               address="Kharkiv Oblast, Ukraine", geometry_wkt="POINT (36.5 49.6)")
    G.add_node("Izium", type="LOC", latitude=49.2, longitude=37.3, place_type="town", importance=0.4,
               address="Izium, Kharkiv Oblast, Ukraine", geometry_wkt="POINT (37.3 49.2)")
    for i, name in enumerate(["Kharkiv Oblast", "Izium"]):
        G.add_node(f"TEXT_{8200 + i}", type="TEXT", text_id=8200 + i, text=f"{name} was shelled.", source="Kharkiv",
                   index=i, title=None, sub_title=None)
        G.add_edge(name, f"TEXT_{8200 + i}", weight=1, relations={"IN_THE_TEXT": [{"start": 0, "end": len(name)}]})
    for inner, outer in [("Izium", "Kharkiv Oblast"), ("Kharkiv Oblast", "Central Russian Upland"),
                         ("Central Russian Upland", "Russia")]:
        G.add_edge(inner, outer, weight=0.1, relations={"INSIDE": [{"subject": inner, "basis": "geometry"}]})
    gi = GraphIndex(G)
    assert T.parents(gi, "Izium") == ["Izium", "Kharkiv Oblast", "Ukraine"]   # the address says Ukraine
    assert T.parents(gi, "Central Russian Upland") == ["Central Russian Upland", "Russia"]   # same country: kept


def test_a_name_with_no_right_point_gets_none_and_a_real_place_at_its_spot_keeps_its_own():
    from conftest import build_vr6_graph
    from graph_index import GraphIndex
    G = build_vr6_graph()
    campus = dict(latitude=50.75, longitude=25.34, place_type="amenity", importance=0.38,
                   address="Volyn National University, Lutsk, Ukraine", geometry_wkt="POINT (25.34 50.75)")
    G.add_node("Eastern Ukraine", type="LOC", **campus)   # the region, geocoded as a university
    G.add_node("Volyn National University", type="LOC", **campus)
    G.add_node("Soviet Union", type="LOC", latitude=44.56, longitude=27.36, place_type="amenity", importance=0.0,
               address="Soviet Union, Slobozia, Romania", geometry_wkt="POINT (27.36 44.56)")
    G.add_node("Soviet Union.", type="LOC", latitude=48.7, longitude=44.5, place_type="historic", importance=0.0,
               address="Memorial plaque, Volgograd, Russia", geometry_wkt="POINT (44.5 48.7)")
    for i, name in enumerate(["Eastern Ukraine", "Volyn National University", "Soviet Union", "Soviet Union."]):
        G.add_node(f"TEXT_{8300 + i}", type="TEXT", text_id=8300 + i, text=f"{name} is mentioned.", source="X",
                   index=i, title=None, sub_title=None)
        G.add_edge(name, f"TEXT_{8300 + i}", weight=1, relations={"IN_THE_TEXT": [{"start": 0, "end": len(name)}]})
    gi = GraphIndex(G)
    assert gi.group("Eastern Ukraine").place is None
    assert gi.group("Volyn National University").place.place_type == "amenity"
    assert gi.group_of["Volyn National University"] != gi.group_of["Eastern Ukraine"]
    assert gi.group("Soviet Union").place is None and "Soviet Union." in gi.group("Soviet Union").names


def test_a_composite_region_gets_its_parts_outlines_and_a_middle_point():
    import graph_tools as T
    from conftest import build_vr6_graph
    from graph_index import GraphIndex
    from result import outline
    G = build_vr6_graph()
    for name, lon, lat in [("Donetsk Oblast", 37.8, 47.9), ("Luhansk Oblast", 38.9, 49.3)]:
        G.add_node(name, type="LOC", latitude=lat, longitude=lon, place_type="state", importance=0.67,
                   address=f"{name}, Ukraine",
                   geometry_wkt=f"POLYGON (({lon - 1} {lat - 1}, {lon + 1} {lat - 1}, {lon + 1} {lat + 1}, {lon - 1} {lat - 1}))")
        G.add_edge(name, "Ukraine", weight=0.1, relations={"INSIDE": [{"subject": name, "basis": "geometry"}]})
    G.add_node("Donbas", type="LOC", latitude=42.0, longitude=21.4, place_type="road", importance=0.04,
               address="Donbas, Skopje, North Macedonia", geometry_wkt="POINT (21.4 42)")
    G.add_node("TEXT_8400", type="TEXT", text_id=8400, text="Donbas is mentioned.", source="X", index=0,
               title=None, sub_title=None)
    G.add_edge("Donbas", "TEXT_8400", weight=1, relations={"IN_THE_TEXT": [{"start": 0, "end": 6}]})
    gi = GraphIndex(G)
    place = gi.group("Donbas").place
    assert (place.place_type, round(place.lon, 2), round(place.lat, 2)) == ("region", 38.35, 48.6)
    assert outline(gi, place.from_name)["type"] == "MultiPolygon"
    assert len(outline(gi, place.from_name)["coordinates"]) == 2
    assert T.parents(gi, "Donbas") == ["Donbas", "Ukraine"]


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
