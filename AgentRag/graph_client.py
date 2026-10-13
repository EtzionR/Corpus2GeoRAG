"""GraphClient interface + NetworkXGraphClient, the adapter for the graph team's knowledge graph.

The real graph (Graph_n_Geocoding/knowledge_graph.json) has three node types (PER/LOC/ORG), one
relation (CO_OCCURS_WITH), coordinates only on LOC nodes, and all narrative text on *edges*
(`evidence` + `source_doc`). NetworkXGraphClient is the one place that absorbs those quirks -
everything above it (agent.py) only ever sees clean GraphNode/GraphEdge objects.
"""
import json
from abc import ABC, abstractmethod
from typing import Optional

import networkx as nx

from contracts import GraphEdge, GraphNode

TYPE_MAP = {"PER": "person", "LOC": "location", "ORG": "organization"}


class GraphClient(ABC):
    """What the agent needs from a graph backend. A new backend implements these five methods."""

    @abstractmethod
    def find_nodes(self, name: Optional[str] = None, node_type: Optional[str] = None,
                   **props) -> list[GraphNode]:
        """Nodes whose name contains `name` (case-insensitive), optionally filtered by type/props."""

    @abstractmethod
    def get_node(self, node_id: str) -> Optional[GraphNode]:
        """One node by exact id, or None."""

    @abstractmethod
    def get_neighbors(self, node_id: str,
                      relation: Optional[str] = None) -> list[tuple[GraphEdge, GraphNode]]:
        """(edge, neighbor) pairs for every edge touching node_id, in either direction."""

    @abstractmethod
    def search_evidence(self, keyword: str) -> list[tuple[GraphEdge, GraphNode, GraphNode]]:
        """(edge, node_a, node_b) triples whose evidence text contains keyword."""

    @abstractmethod
    def get_source_passages(self, pointer: str) -> list[str]:
        """The distinct text passages behind a source pointer (a value from a response's sources)."""


class NetworkXGraphClient(GraphClient):
    def __init__(self, G: nx.DiGraph):
        self.G = G

    def _to_graph_node(self, node_id: str) -> GraphNode:
        attrs = dict(self.G.nodes[node_id])
        raw_type = attrs.pop("type", "unknown")
        lat = attrs.pop("latitude", None)
        lon = attrs.pop("longitude", None)
        return GraphNode(id=node_id, type=TYPE_MAP.get(raw_type, raw_type.lower()),
                         name=node_id, lat=lat, lon=lon, props=attrs)

    def _to_graph_edge(self, u: str, v: str, attrs: dict) -> GraphEdge:
        attrs = dict(attrs)
        relation = attrs.pop("relation", "related_to")
        return GraphEdge(source=u, target=v, relation=relation, props=attrs)

    def find_nodes(self, name=None, node_type=None, **props):
        out = []
        for nid in self.G.nodes:
            if name and name.lower() not in nid.lower():
                continue
            node = self._to_graph_node(nid)
            if node_type and node.type != node_type:
                continue
            if any(node.props.get(k) != v for k, v in props.items()):
                continue
            out.append(node)
        return out

    def get_node(self, node_id):
        return self._to_graph_node(node_id) if node_id in self.G.nodes else None

    def get_neighbors(self, node_id, relation=None):
        out = []
        for u, v, attrs in self.G.in_edges(node_id, data=True):
            if relation and attrs.get("relation") != relation:
                continue
            out.append((self._to_graph_edge(u, v, attrs), self._to_graph_node(u)))
        for u, v, attrs in self.G.out_edges(node_id, data=True):
            if relation and attrs.get("relation") != relation:
                continue
            out.append((self._to_graph_edge(u, v, attrs), self._to_graph_node(v)))
        return out

    def search_evidence(self, keyword):
        """Keyword search over edge evidence text - today's substitute for "find events of
        type X", since this schema has no event nodes."""
        keyword = keyword.lower()
        hits = []
        for u, v, attrs in self.G.edges(data=True):
            if keyword in attrs.get("evidence", "").lower():
                hits.append((self._to_graph_edge(u, v, attrs), self._to_graph_node(u), self._to_graph_node(v)))
        return hits

    def get_source_passages(self, pointer):
        """Today a pointer is a `source_doc` value, and the text lives inline on edges - the same
        passage repeated once per edge. Returns each distinct passage once, in graph order."""
        passages = []
        for _, _, attrs in self.G.edges(data=True):
            evidence = attrs.get("evidence")
            if attrs.get("source_doc") == pointer and evidence and evidence not in passages:
                passages.append(evidence)
        return passages


def load_node_link_json(path: str) -> nx.DiGraph:
    """Load a node-link JSON graph. Handles both the "edges" and "links" key names that
    different networkx versions write."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    edges_key = "edges" if "edges" in data else "links"
    return nx.node_link_graph(data, directed=True, multigraph=False, edges=edges_key)
