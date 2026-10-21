"""The knowledge graph, loaded once, with the lookups the agent needs.

All graph access goes through this module, so switching storage later (e.g. to SQLite, P2-5) only
changes this file. Built for the Vr6 format (Graph_n_Geocoding/KNOWLEDGE_GRAPH_README.md): TEXT /
PER / ORG / LOC nodes, and edges whose `relations` hold records pointing into the texts.

Variant groups (P2-11) are a light, temporary stand-in for the graph team's entity unification:
spellings of one thing are grouped so a question about "Zelenskyy" also sees "Volodymyr Zelenskyy".
The rules are deliberately conservative (DECISIONS_LOG P2-38) and should become mostly unnecessary
once the unified graph arrives.
"""
import gzip
import json
import logging
import os
import re
import time
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

import networkx as nx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
DEFAULT_GRAPH_PATH = HERE.parent / "Graph_n_Geocoding" / "knowledge_graph.json.gz"

# Words that say what kind of thing a name is, not which one. Two names sharing only these
# ("Russian Armed Forces" / "Ukrainian Air Force") are not the same thing.
GENERIC_WORDS = {
    "of", "the", "and", "de", "la", "al", "on", "in", "for", "to", "a", "an",
    "republic", "people's", "peoples", "people", "oblast", "raion", "district", "region", "city", "town",
    "village", "river", "lake", "sea", "mount", "island", "bridge", "street", "square", "airport", "station",
    "armed", "forces", "force", "army", "air", "navy", "naval", "military", "group", "national", "state",
    "ministry", "defence", "federation", "union", "united", "party", "front", "brigade", "battalion",
    "regiment", "division", "corps", "guards", "guard", "company", "council", "committee", "government",
    "office", "international", "security", "service", "special", "operations", "operation", "new", "north",
    "south", "east", "west", "northern", "southern", "eastern", "western", "central", "great", "greater",
    "old", "st", "saint", "university", "church", "museum", "park", "hromada", "urban", "rural",
    "municipality", "administration", "territorial", "community", "president", "general", "staff",
}
# Words that may be added to an organization's name without changing which organization it is.
ORG_NAME_EXTRAS = {"group", "pmc", "pmcs", "company", "private", "military", "corporation", "inc", "ltd"}
SPELLING = {"defense": "defence", "organization": "organisation", "center": "centre"}

# P2-61: sections that list article titles or books, not prose. Their paragraphs are no evidence
# ("Ivanov, Henry, 'Country Briefing: Russia', Jane's Defence Weekly"), and the names NER found in
# them are mostly noise (`Україні`, "in Ukraine", from a Ukrainian citation title, geocoded near
# Maidan). Dropped from the in-memory graph when it loads; the graph file is not changed.
REFERENCE_SECTIONS = {
    "See also", "Sources", "Further reading", "References", "Bibliography", "Works cited", "Links", "Weblinks",
    "External links", "External links and further reading", "Literature", "Sources and literature",
    "Cited sources", "Related literature", "Footnotes", "Citations",
}

UNCERTAIN_PLACE_TYPES = {"road", "amenity", "shop", "tourism", "building"}   # P2-35
UNCERTAIN_IMPORTANCE = 0.4
# P2-64: the point is also doubtful when the graph put a settlement on water: "Dnipro" is geocoded as
# a river near Chernihiv while its own article says "Dnipro is Ukraine's fourth-largest city".
WATER_TYPES = {"river", "stream", "canal", "water", "lake", "reservoir"}
_SETTLEMENT = re.compile(r"\b(?:is|was)\b[^.]{0,100}?\b(?:city|town|village|capital)\b", re.I)
SURNAME_DOMINANCE = 0.8   # a bare surname joins a person's group only if that group has 80 % of its texts


def normalize(name: str) -> str:
    """Case, unicode spaces, quotes, dashes, stray punctuation, a leading 'the', UK/US spelling."""
    s = unicodedata.normalize("NFKC", name)   # also turns narrow no-break spaces into plain spaces
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("–", "-").replace("—", "-")
    s = re.sub(r"\s+", " ", s.lower()).strip(" .,;:'\"()[]")
    s = re.sub(r"^the ", "", s)
    return " ".join(SPELLING.get(w, w) for w in s.split())


def words(norm: str) -> list[str]:
    return [w[:-2] if w.endswith("'s") else w for w in re.findall(r"[\w']+", norm)]


def distinctive(ws: list[str]) -> list[str]:
    return [w for w in ws if w not in GENERIC_WORDS and len(w) >= 3]


def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


class Place(BaseModel):
    lat: float
    lon: float
    place_type: Optional[str] = None
    importance: Optional[float] = None
    address: Optional[str] = None
    from_name: str                       # which name in the group the point comes from
    uncertain: bool = False
    uncertain_reason: Optional[str] = None


class Group(BaseModel):
    id: str                              # the name with the most texts
    type: str                            # PER / ORG / LOC
    names: list[str]
    texts: int                           # paragraphs mentioning any name in the group
    own_article: Optional[str] = None    # a Wikipedia article whose title is one of the names
    place: Optional[Place] = None


def drop_reference_sections(G: nx.Graph) -> dict:
    """Remove reference-section paragraphs (P2-61), the relation records read from them, and the
    entities mentioned nowhere else. Returns what was removed, for the reports."""
    texts = [n for n, d in G.nodes(data=True) if d.get("type") == "TEXT" and d.get("title") in REFERENCE_SECTIONS]
    dropped_ids = {G.nodes[n]["text_id"] for n in texts}
    mentioned = {m for n in texts for m in G.neighbors(n)}
    G.remove_nodes_from(texts)
    records, emptied = 0, []
    for u, v, d in G.edges(data=True):
        rels = d.get("relations") or {}
        before = sum(len(recs) for recs in rels.values())
        for rel in list(rels):
            rels[rel] = [r for r in rels[rel] if r.get("text_id") not in dropped_ids]
            if not rels[rel]:
                del rels[rel]
        removed = before - sum(len(recs) for recs in rels.values())
        records += removed
        if removed and not rels:
            emptied.append((u, v))
    G.remove_edges_from(emptied)
    # every entity in the graph is mentioned in some paragraph; one left with none was only in these lists.
    # Such an entity is removed, unless other places sit INSIDE it: all of Russia's regions hang from
    # "РФ", a name of Russia mentioned only in Russian citation titles. Those stay, as hierarchy only.
    orphans = [m for m in mentioned if not any(G.nodes[x].get("type") == "TEXT" for x in G.neighbors(m))]
    containers = [m for m in orphans if _contains_places(G, m)]
    G.remove_nodes_from(set(orphans) - set(containers))
    return {"paragraphs": len(texts), "records": records, "entities": len(orphans) - len(containers),
            "kept_for_hierarchy": len(containers)}


def _contains_places(G: nx.Graph, name: str) -> bool:
    return any(r.get("subject") == other
               for other in G.neighbors(name)
               for r in (G[name][other].get("relations") or {}).get("INSIDE", []))


class GraphIndex:
    """The loaded graph plus lookups. Build once per app start with GraphIndex.load()."""

    def __init__(self, G: nx.Graph):
        start = time.time()
        self.dropped = drop_reference_sections(G)
        self.G = G
        self.entities = [n for n, d in G.nodes(data=True) if d.get("type") != "TEXT"]
        self.text_ids: dict[str, list[int]] = {}
        for n in self.entities:
            self.text_ids[n] = [G.nodes[m]["text_id"] for m in G.neighbors(n) if G.nodes[m].get("type") == "TEXT"]
        self.by_norm: dict[str, list[str]] = defaultdict(list)
        self.by_word: dict[str, set[str]] = defaultdict(set)
        for n in self.entities:
            key = normalize(n)
            if key:
                self.by_norm[key].append(n)
                for w in set(words(key)):
                    self.by_word[w].add(n)
        self._build_articles()
        self._build_groups()
        self.index_seconds = round(time.time() - start, 1)
        self.load_seconds: Optional[float] = None

    # --- loading ----------------------------------------------------------------------------

    @classmethod
    def load(cls, path: Optional[str] = None) -> "GraphIndex":
        path = Path(path or os.environ.get("GRAPH_PATH") or DEFAULT_GRAPH_PATH)
        if not path.is_file():
            raise FileNotFoundError(f"Knowledge graph not found at {path}. Set GRAPH_PATH in AgentRag/.env "
                                    f"if it lives somewhere else.")
        start = time.time()
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as f:
            data = json.load(f)
        G = nx.node_link_graph(data, edges="links" if "links" in data else "edges")
        load_seconds = round(time.time() - start, 1)
        index = cls(G)
        index.load_seconds = load_seconds
        index.path = str(path)
        logger.info("graph loaded from %s in %.1f s (%d nodes, %d edges); indexes in %.1f s; reference sections "
                    "dropped: %s", path, load_seconds, G.number_of_nodes(), G.number_of_edges(), index.index_seconds,
                    index.dropped)
        return index

    # --- articles (events live here: "Battle of Bakhmut" is an article, not a node) ----------

    def _build_articles(self) -> None:
        paragraphs: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for _, d in self.G.nodes(data=True):
            if d.get("type") == "TEXT":
                paragraphs[d["source"]].append((d["index"], d["text_id"]))
        self.articles = {title: [tid for _, tid in sorted(ps)] for title, ps in paragraphs.items()}
        self.article_by_norm = {normalize(t): t for t in self.articles}

    def text(self, text_id: int) -> dict:
        return self.G.nodes[f"TEXT_{text_id}"]

    # --- variant groups (P2-11 light, P2-38) ------------------------------------------------

    def _build_groups(self) -> None:
        parent = {n: n for n in self.entities}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        node = self.G.nodes
        # (a) the same normalized spelling: "Putin" / "Putin." / "Volodymyr Zelenskyy"
        for names in self.by_norm.values():
            by_type = defaultdict(list)
            for n in names:
                by_type[node[n]["type"]].append(n)
            for same in by_type.values():
                for n in same[1:]:
                    union(same[0], n)
        # (b) SAME_AS, only between names that share a distinctive word or are spelled almost alike;
        #     the graph's SAME_AS also links "." to NATO and Wagner to Africa Corps
        for u, v, d in self.G.edges(data=True):
            if "SAME_AS" in d["relations"] and node[u]["type"] == node[v]["type"] != "TEXT":
                nu, nv = normalize(u), normalize(v)
                if set(distinctive(words(nu))) & set(distinctive(words(nv))) or (nu and nv and similar(nu, nv) >= 0.8):
                    union(u, v)
        # (c) locations with identical coordinates and the same place type: Kyiv / Kiev / Kiyev
        spots = defaultdict(list)
        for n in self.entities:
            d = node[n]
            if d["type"] == "LOC" and d.get("latitude") is not None:
                spots[(round(d["latitude"], 5), round(d["longitude"], 5), d.get("place_type"))].append(n)
        for names in spots.values():
            for n in names[1:]:
                union(names[0], n)
        # (d) organizations that differ only by words like Group / PMC: Wagner / Wagner Group / PMC Wagner
        for n in self.entities:
            if node[n]["type"] != "ORG":
                continue
            ws = words(normalize(n))
            core = " ".join(w for w in ws if w not in ORG_NAME_EXTRAS)
            if core and core != " ".join(ws):
                for m in self.by_norm.get(core, []):
                    if node[m]["type"] == "ORG":
                        union(m, n)
        # (e) people: same surname and a similar first name (Volodymyr / Volodomyr Zelenskyy), or the
        #     same first name and a similar surname (Volodymyr Zelensky / Zelenskyy)
        people = [n for n in self.entities if node[n]["type"] == "PER"]
        full = [(n, words(normalize(n))) for n in people if n[:1].isupper() and len(n.split()) >= 2]
        by_last, by_first = defaultdict(list), defaultdict(list)
        for n, ws in full:
            if len(ws) >= 2 and len(ws[-1]) >= 4:
                by_last[ws[-1]].append((n, ws))
            if len(ws) == 2 and len(ws[0]) >= 3:
                by_first[ws[0]].append((n, ws))
        for bucket in by_last.values():
            for i, (a, wa) in enumerate(bucket):
                for b, wb in bucket[i + 1:]:
                    if similar(wa[0], wb[0]) >= 0.75:
                        union(a, b)
        for bucket in by_first.values():
            for i, (a, wa) in enumerate(bucket):
                for b, wb in bucket[i + 1:]:
                    female_form = wa[-1] + "a" == wb[-1] or wb[-1] + "a" == wa[-1]
                    if not female_form and similar(wa[-1], wb[-1]) >= 0.85:
                        union(a, b)
        # (f) a bare surname joins the person who dominates it: "Gerasimov" -> Valery Gerasimov
        for n in people:
            ws = words(normalize(n))
            if len(ws) != 1 or ws[0] not in by_last:
                continue
            totals = defaultdict(int)
            for m, _ in by_last[ws[0]]:
                totals[find(m)] += len(self.text_ids[m])
            best, best_texts = max(totals.items(), key=lambda kv: kv[1])
            if best_texts >= SURNAME_DOMINANCE * sum(totals.values()):
                union(best, n)

        members = defaultdict(list)
        for n in self.entities:
            members[find(n)].append(n)
        self.group_of: dict[str, str] = {}
        self.groups: dict[str, list[str]] = {}
        for names in members.values():
            names.sort(key=lambda m: (-len(self.text_ids[m]), len(m)))
            gid = names[0]
            self.groups[gid] = names
            for m in names:
                self.group_of[m] = gid

    # --- groups -----------------------------------------------------------------------------

    def group(self, name: str) -> Group:
        gid = self.group_of[name]
        names = self.groups[gid]
        texts = len({t for m in names for t in self.text_ids[m]})
        own = next((m for m in names if m in self.articles), None)
        return Group(id=gid, type=self.G.nodes[gid]["type"], names=names, texts=texts,
                     own_article=own, place=self._place(names, own))

    def _place(self, names: list[str], article: Optional[str] = None) -> Optional[Place]:
        located = [m for m in names if self.G.nodes[m].get("latitude") is not None]
        if not located:
            return None
        m = max(located, key=lambda x: (self.G.nodes[x].get("importance") or 0, len(self.text_ids[x])))
        d = self.G.nodes[m]
        reason = None
        if d.get("place_type") in UNCERTAIN_PLACE_TYPES and (d.get("importance") or 0) < UNCERTAIN_IMPORTANCE:
            reason = f"geocoded as a {d.get('place_type')} with importance {d.get('importance') or 0:.2f}"
        elif article and d.get("place_type") in WATER_TYPES and _SETTLEMENT.search(self.lead_sentence(article) or ""):
            reason = f"geocoded as a {d.get('place_type')}, but its own article describes a city or town"
        return Place(lat=d["latitude"], lon=d["longitude"], place_type=d.get("place_type"),
                     importance=d.get("importance"), address=d.get("address"), from_name=m,
                     uncertain=reason is not None, uncertain_reason=reason)

    def lead_sentence(self, article: str) -> Optional[str]:
        """The first sentence of an article's lead paragraph (used to describe a candidate, P2-34)."""
        if article not in self.articles:
            return None
        lead = self.text(self.articles[article][0])["text"]
        m = re.match(r"(.+?[.!?])(\s|$)", lead)
        return (m.group(1) if m else lead)[:300]
