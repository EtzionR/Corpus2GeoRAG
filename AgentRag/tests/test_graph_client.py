import json

import networkx as nx

from graph_client import NetworkXGraphClient, load_node_link_json


def test_find_nodes_maps_raw_types(graph):
    assert [n.name for n in graph.find_nodes(node_type="location")] == ["Moscow", "Kyiv", "Kharkiv", "Kherson"]
    assert graph.get_node("Vladimir Putin").type == "person"
    assert graph.get_node("Russian Armed Forces").type == "organization"


def test_find_nodes_by_name_is_case_insensitive_substring(graph):
    assert [n.name for n in graph.find_nodes(name="armed forces")] == ["Russian Armed Forces", "Armed Forces of Ukraine"]


def test_get_node_moves_coordinates_out_of_props(graph):
    kyiv = graph.get_node("Kyiv")
    assert (kyiv.lat, kyiv.lon) == (50.4501, 30.5234)
    assert kyiv.props == {"address": "Kyiv, Ukraine"}
    assert graph.get_node("Atlantis") is None


def test_get_neighbors_follows_both_directions(graph):
    pairs = graph.get_neighbors("Kyiv")
    assert {nb.id for _, nb in pairs} == {"Russian Armed Forces", "Volodymyr Zelenskyy"}
    edge, _ = pairs[0]
    assert edge.relation == "CO_OCCURS_WITH"
    assert set(edge.props) == {"evidence", "source_doc"}
    assert graph.get_neighbors("Kyiv", relation="SOMETHING_ELSE") == []


def test_search_evidence_is_case_insensitive(graph):
    hits = graph.search_evidence("DRONE ATTACK")
    assert {(a.id, b.id) for _, a, b in hits} == {("Russian Armed Forces", "Kharkiv"), ("Russian Armed Forces", "Kyiv")}


def test_get_source_passages_returns_each_passage_once():
    G = nx.DiGraph()
    for a, b in [("A", "B"), ("A", "C"), ("B", "C")]:   # one passage, repeated on three edges
        G.add_edge(a, b, relation="CO_OCCURS_WITH", evidence="Same passage.", source_doc="doc1")
    G.add_edge("C", "D", relation="CO_OCCURS_WITH", evidence="Other passage.", source_doc="doc1")
    G.add_edge("D", "E", relation="CO_OCCURS_WITH", evidence="Unrelated.", source_doc="doc2")
    g = NetworkXGraphClient(G)
    assert g.get_source_passages("doc1") == ["Same passage.", "Other passage."]
    assert g.get_source_passages("missing") == []


def test_loader_handles_both_edge_key_names(graph, tmp_path):
    G = graph.G
    for key in ("edges", "links"):
        path = tmp_path / f"{key}.json"
        path.write_text(json.dumps(nx.node_link_data(G, edges=key)), encoding="utf-8")
        loaded = load_node_link_json(str(path))
        assert (loaded.number_of_nodes(), loaded.number_of_edges()) == (8, 5)
