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

from geo import parse_wkt

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

# P2-72: places the graph geocoded wrongly, each mapped to another node of the same graph that has the right
# point. On load the name takes that node's point, outline, place type, address and INSIDE parent, so the
# map, the region overview and the variant groups all use it. The graph file is not changed.
PLACE_FIXES = {
    "Dnipro": "Dnipro City",                     # the river near Chernihiv; the city is 300 km south-east
    "Дніпро": "Dnipro City",
    "Dnipro Oblast": "Dnipropetrovsk Oblast",    # the same river point
    "Zaporizhzhia Oblast": "Zaporizhia Oblast",  # a village called Zaporizhzhia in Kherson Oblast
    "Crimean Oblast": "Autonomous Republic of Crimea",   # a street in Kamianske; the Soviet oblast had the same land
    "Belgorod Oblasts": "Belgorod Oblast",       # Belgorod-18, a locality
    "Kursk Oblasts": "Kursk Oblast",             # a tract in Pskov Oblast
    "Donetsk City": "Donetsk",                   # Donetsk Way in Sheffield
    "U.K.": "United Kingdom",                    # a road in the Netherlands
    "Hrushevskoho Street": "Mykhaila Hrushevskoho Street",   # the Kyiv street, not one in Brovary Raion
    "Oval Office": "White House",                # a road in Alabama
}
# Names geocoded to a wrong spot with no right point anywhere in the graph: better no pin than a wrong one.
# Mostly regions, former states and military districts matched to a shop, plaque or street of that name.
# Found by listing the names in 15+ paragraphs geocoded with importance under 0.1. Applies to every
# spelling in the group ("Soviet Union" is a shop in Romania, "The Soviet Union" a plaque).
NO_POINT = {
    "Eastern Ukraine", "Western Ukraine", "Central Ukraine",
    "Soviet Union", "USSR", "Russian Empire", "RSFSR", "Czechoslovakia", "East Germany", "West Germany",
    "Nazi Germany", "Ottoman Empire", "Lithuanian SSR", "Ukrainian People's Republic",
    "Chechen Republic of Ichkeria", "Nagorno-Karabakh", "Artsakh",
    "Western Military District", "Central Military District", "Moscow Military District", "Kyiv Military District",
    "Eastern Europe", "Central Asia", "Latin America", "Indo-Pacific", "Global South", "Union State",
    "Eastern Front", "Western Front", "Danube Delta", "Taman Peninsula", "Volhynia", "Russia-Ukraine", "SIZO-2",
}
# A region the graph has no outline for, made of the outlines of the places it consists of. Donbas was a
# street in Skopje; its own article says "the Donbas usually refers to Donetsk Oblast and Luhansk Oblast".
COMPOSITE_PLACES = {
    "Donbas": ("Donetsk Oblast", "Luhansk Oblast"),
    "Donbass": ("Donetsk Oblast", "Luhansk Oblast"),
}
GEO_FIELDS = ("latitude", "longitude", "place_type", "importance", "address", "geometry_wkt")


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


def _look_alike(a: str, b: str) -> bool:
    """Two normalized names that share a distinctive word or are spelled almost alike."""
    return bool(set(distinctive(words(a))) & set(distinctive(words(b)))) or bool(a and b and similar(a, b) >= 0.8)


def _spot(d: dict) -> tuple:
    return round(d["latitude"], 5), round(d["longitude"], 5), d.get("place_type")


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


def apply_place_fixes(G: nx.Graph, fixes: dict[str, str] = PLACE_FIXES) -> list[str]:
    """Give each name in `fixes` the point and INSIDE parent of the node it maps to (P2-72). Returns the
    names fixed; a name or source missing from this graph is skipped."""
    fixed = []
    for name, source in fixes.items():
        if name not in G or source not in G or G.nodes[source].get("latitude") is None:
            continue
        for k in GEO_FIELDS:
            G.nodes[name][k] = G.nodes[source].get(k)
        _set_inside_parent(G, name, _inside_parent(G, source), basis="place fix")
        fixed.append(name)
    return fixed


def _multipolygon_wkt(wkts: list[Optional[str]]) -> Optional[str]:
    """The polygons of several WKT outlines side by side, as one MULTIPOLYGON (no union is needed to draw them)."""
    polygons = []
    for shape in (parse_wkt(w) for w in wkts):
        if shape and shape["type"] == "Polygon":
            polygons.append(shape["coordinates"])
        elif shape and shape["type"] == "MultiPolygon":
            polygons += shape["coordinates"]
    if not polygons:
        return None
    ring = lambda r: "(" + ", ".join(f"{x} {y}" for x, y in r) + ")"
    return "MULTIPOLYGON (" + ", ".join("(" + ", ".join(ring(r) for r in p) + ")" for p in polygons) + ")"


def address_country(address: Optional[str]) -> Optional[str]:
    """The last part of a geocoded address, which names the country ("Kharkiv, Kharkiv Oblast, Ukraine")."""
    parts = [p.strip() for p in (address or "").split(",") if p.strip() and not re.fullmatch(r"[\d\- ]+", p.strip())]
    return parts[-1] if parts else None


def fix_cross_border_parents(G: nx.Graph) -> int:
    """P2-72: an INSIDE parent in another country than the place itself, by the two geocoded addresses, is
    replaced by the place's own country. The graph hangs places from landforms that cross borders
    (Kharkiv Oblast -> Central Russian Upland -> Russia; Zakarpattia -> Eastern Carpathians -> Romania) and
    Crimea from Russia's Southern Federal District, while their own addresses say Ukraine. The address is
    taken as the truth. Returns how many links changed."""
    changed = 0
    for n, d in list(G.nodes(data=True)):
        if d.get("type") != "LOC" or d.get("latitude") is None:
            continue
        parent = _inside_parent(G, n)
        if parent is None:
            continue
        own, theirs = address_country(d.get("address")), address_country(G.nodes[parent].get("address"))
        if own and theirs and own != theirs and own in G and G.nodes[own].get("place_type") == "country":
            _set_inside_parent(G, n, None if own == n else own, basis="address country")
            changed += 1
    return changed


def _inside_parent(G: nx.Graph, name: str) -> Optional[str]:
    return next((m for m in G.neighbors(name)
                 if any(r.get("subject") == name for r in G[name][m]["relations"].get("INSIDE", []))), None)


def _set_inside_parent(G: nx.Graph, name: str, parent: Optional[str], basis: str) -> None:
    """Replace the INSIDE parent of `name` (None: no parent)."""
    for m in list(G.neighbors(name)):
        rels = G[name][m]["relations"]
        kept = [r for r in rels.get("INSIDE", []) if r.get("subject") != name]
        if len(kept) < len(rels.get("INSIDE", [])):
            if kept:
                rels["INSIDE"] = kept
            else:
                del rels["INSIDE"]
            if not rels:
                G.remove_edge(name, m)
    if parent and parent != name:
        if not G.has_edge(name, parent):
            G.add_edge(name, parent, weight=0.1, relations={})
        G[name][parent]["relations"].setdefault("INSIDE", []).append({"subject": name, "basis": basis})


def _contains_places(G: nx.Graph, name: str) -> bool:
    return any(r.get("subject") == other
               for other in G.neighbors(name)
               for r in (G[name][other].get("relations") or {}).get("INSIDE", []))


class GraphIndex:
    """The loaded graph plus lookups. Build once per app start with GraphIndex.load()."""

    def __init__(self, G: nx.Graph):
        start = time.time()
        self.dropped = drop_reference_sections(G)
        self.place_fixes = apply_place_fixes(G)
        self.parents_fixed = fix_cross_border_parents(G)
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
        self._clear_wrong_spots(NO_POINT)
        self.composites = self._apply_composites(COMPOSITE_PLACES)
        self._build_groups()
        self.no_point = self._clear_points(NO_POINT)
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
                    "dropped: %s; points fixed: %s; parents fixed: %d; no point: %s; composites: %s", path,
                    load_seconds, G.number_of_nodes(), G.number_of_edges(), index.index_seconds, index.dropped,
                    index.place_fixes, index.parents_fixed, index.no_point, index.composites)
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
                if _look_alike(normalize(u), normalize(v)):
                    union(u, v)
        # (c) locations with identical coordinates and the same place type: Kyiv / Kiev / Kiyev
        spots = defaultdict(list)
        for n in self.entities:
            d = node[n]
            if d["type"] == "LOC" and d.get("latitude") is not None:
                spots[_spot(d)].append(n)
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

    def _clear_wrong_spots(self, names: set[str]) -> None:
        """NO_POINT, before grouping: clear each name, its spellings, and the names at the same wrong spot that
        look like it (Kiev / Kyiv Military District). A real place that only shares the spot keeps its point
        and stays out of the group: "Donbass" sits on the village Novyi Donbas."""
        G = self.G
        spots = defaultdict(list)
        for n in self.entities:
            if G.nodes[n]["type"] == "LOC" and G.nodes[n].get("latitude") is not None:
                spots[_spot(G.nodes[n])].append(n)
        for name in names:
            key = normalize(name)
            variants = [m for m in self.by_norm.get(key, []) if G.nodes[m]["type"] == "LOC"]
            near = {x for m in variants if G.nodes[m].get("latitude") is not None for x in spots[_spot(G.nodes[m])]}
            for m in set(variants) | {x for x in near if _look_alike(normalize(x), key)}:
                G.nodes[m].update(dict.fromkeys(GEO_FIELDS))

    def _apply_composites(self, composites: dict[str, tuple[str, ...]]) -> list[str]:
        """COMPOSITE_PLACES, before grouping: each spelling of the name gets the outlines of its parts together,
        a point at their middle and the first part's parent. Returns the names done."""
        G, done = self.G, []
        for name, parts in composites.items():
            located = [G.nodes[p] for p in parts if p in G and G.nodes[p].get("latitude") is not None]
            if len(located) < len(parts):
                continue
            geo = dict(latitude=sum(d["latitude"] for d in located) / len(located),
                       longitude=sum(d["longitude"] for d in located) / len(located), place_type="region",
                       importance=max(d.get("importance") or 0 for d in located),
                       address=f"{' and '.join(parts)}, {address_country(located[0].get('address'))}",
                       geometry_wkt=_multipolygon_wkt([d.get("geometry_wkt") for d in located]))
            for m in self.by_norm.get(normalize(name), []):
                if G.nodes[m]["type"] == "LOC":
                    G.nodes[m].update(geo)
                    _set_inside_parent(G, m, _inside_parent(G, parts[0]), basis="composite")
            done.append(name)
        return done

    def _clear_points(self, names: set[str]) -> list[str]:
        """After grouping: remove the point of every spelling in the groups of `names` (NO_POINT, P2-72), e.g.
        "The Soviet Union", a plaque elsewhere. Returns the group ids."""
        cleared = []
        for name in sorted(names):
            gid = self.group_of.get(name)
            if gid is None or gid in cleared:
                continue
            for m in self.groups[gid]:
                self.G.nodes[m].update(dict.fromkeys(GEO_FIELDS))
            cleared.append(gid)
        return cleared

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
