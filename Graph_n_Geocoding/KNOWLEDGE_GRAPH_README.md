# Knowledge Graph — README for the RAG

`knowledge_graph.json.gz` is the knowledge graph built from the Corpus2GeoRAG corpus (Wikipedia articles about the
Russia–Ukraine war), compressed with gzip. It links people, organizations and locations to each other and to the texts they come from, so every
relation can be traced back to the exact words in a source text.

* **Format:** NetworkX *node-link* JSON, undirected graph: `{"directed": false, "multigraph": false, "graph": {}, "nodes": [...], "links": [...]}`.
* **Size:** 120,019 nodes — 64,301 texts and 55,718 entities (19,266 PER, 23,317 ORG, 13,135 LOC) — and 697,333 edges.
* **File:** `knowledge_graph.json.gz`, 37 MB (gzip, lossless; the JSON inside is 228 MB). Python reads it directly (section 1);
  to look inside by hand, decompress it with 7-Zip.

---

## 1. Loading

```python
import gzip
import json
import networkx as nx

with gzip.open('knowledge_graph.json.gz', 'rt', encoding='utf-8') as f:   # gzip is part of the standard library
    data = json.load(f)

G = nx.node_link_graph(data, edges='links')   # NetworkX >= 3.4
```

Compression only saves disk space and download time: once loaded, the graph takes the same memory as the plain JSON
(about 3 seconds to decompress and parse).

You can also work on `data['nodes']` / `data['links']` directly — every edge there has an explicit `source` and `target`
(see the note on direction in 3.1).

---

## 2. Nodes

Every node has an `id` and a `type`. There are four types.

### 2.1 `TEXT` — a paragraph of the corpus

```json
{"id": "TEXT_29876", "type": "TEXT", "text_id": 29876,
 "text": "Lobau was buried at the Powązki Military Cemetery in Warsaw.",
 "source": "Eduard Lobau", "index": 6, "title": "Death", "sub_title": null}
```

| Field | Meaning |
|---|---|
| `id` | `TEXT_<text_id>` |
| `text_id` | 0 … 64,300, in the order of the corpus file; this is the number the relations point to |
| `text` | the paragraph |
| `source` | the Wikipedia article |
| `index` | the paragraph number inside the article |
| `title`, `sub_title` | the section and subsection headings (`null` when the paragraph has none) |

### 2.2 `PER`, `ORG` — people and organizations

```json
{"id": "Lobau", "type": "PER"}
```

`id` is the entity name as the NER model found it. Each name has one type (the one the NER model gave it most often).

### 2.3 `LOC` — locations, with geocoding (Nominatim / OpenStreetMap)

```json
{"id": "Kyiv", "type": "LOC", "latitude": 50.4500336, "longitude": 30.5241361, "address": "Kyiv, Ukraine",
 "place_type": "city", "importance": 0.7858, "geometry_wkt": "POLYGON ((30.23615 50.42681, 30.24136 50.42458, ..."}
```

| Field | Meaning |
|---|---|
| `latitude`, `longitude` | WGS 84 (EPSG:4326), decimal degrees |
| `address` | the full address in English (some parts may be in Ukrainian/Russian when OSM has no English name) |
| `place_type` | `country`, `state` (oblast), `city`, `town`, `village`, `city_district`, `peninsula`, `sea`, `road`, … |
| `importance` | 0–1, how prominent the place is in OSM/Wikipedia; a rough confidence for the match |
| `geometry_wkt` | the polygon (or point / line) as WKT, simplified by size (~0.2 % of the place's size). **WKT order is `lon lat`** |

About 26 % of the LOC entities were not found by Nominatim; their geocoding fields are `null`.

---

## 3. Edges

Every edge has exactly four fields: `source`, `target`, `weight`, `relations`.
`relations` is a dictionary: **relation name → list of records**. There are three kinds of edges.

### 3.1 Entity ↔ entity — relations from the text

```json
{"source": "Lobau", "target": "Powązki Military Cemetery", "weight": 0.6,
 "relations": {
   "DIED_IN": [{"text_id": 29876, "source_start": 0, "source_end": 5, "target_start": 24, "target_end": 49,
                "subject": "Lobau", "confidence": 0.79}]}}
```

One **record** = one place in the corpus where the two entities appear together (one record per sentence; when the two entities
are not in the same sentence, one record per text).

| Field | Meaning |
|---|---|
| `text_id` | the text node `TEXT_<text_id>` |
| `source_start`, `source_end` | position of the **source** entity in that text: `text[source_start:source_end]` is its name |
| `target_start`, `target_end` | position of the **target** entity in that text |
| `subject` | the entity the relation reads from, i.e. who acts: here *Lobau* DIED_IN the cemetery. `null` = symmetric relation |
| `confidence` | the classifier's score (0–1); `null` = the pair was not classified (see below) |

* An edge can hold several relations and many records: `Russia – Ukraine` may have `ATTACKED`, `NEGOTIATED_WITH` and
  `CO_OCCURS_WITH`, each with its own list of records from different texts.
* **Direction:** the graph is undirected; the direction of a relation is given by `subject`, not by `source` / `target`.
  The positions `source_start` / `target_start` belong to the `source` / `target` of the link in the JSON. After loading into
  NetworkX that order is not kept, so get the words by slicing the text (`text[source_start:source_end]`) — see 5.2.
* **`weight`** = how strongly the two entities are connected in the corpus, independent of the relation type:
  $W = \max(0.1,\ S \cdot \ln(1 + C_{\text{eff}}))$, where $S$ = number of different articles and
  $C_{\text{eff}} = \sum e^{-0.01\, d}$ over the texts in which they co-occur ($d$ = distance in characters). Close, repeated,
  multi-article co-occurrence → high weight; a single distant mention → the minimum, 0.1.

**How the relations were found.** Two entities in the same sentence and at most 100 characters apart are classified by a
small model (`von`) from the sentence. Otherwise, and for items of one comma list (`Horlivka, Mariupol, Yenakiieve`), the
relation is `CO_OCCURS_WITH` with `confidence: null`. A classification below 0.4 confidence is also stored as
`CO_OCCURS_WITH` (with its confidence).

### 3.2 Entity → text — `IN_THE_TEXT`

```json
{"source": "Lobau", "target": "TEXT_29876", "weight": 1,
 "relations": {"IN_THE_TEXT": [{"start": 0, "end": 5}]}}
```

Every entity is linked to every text that mentions it; `start` / `end` are the positions of each mention,
`weight` = number of mentions in that text. This is the way from an entity to its texts (and from a text to its entities).

### 3.3 Location → location — `INSIDE` (from the polygons, not from the text)

```json
{"source": "Darnytskyi District", "target": "Kiyev", "weight": 0.1,
 "relations": {"INSIDE": [{"subject": "Darnytskyi District", "basis": "geometry"}]}}
```

`subject` is the inner location; the other end is the **smallest** location whose polygon contains it (its direct parent).
Follow the edges up for the full hierarchy: Darnytskyi District → Kiyev → Ukraine (see 5.4). When the two locations are also connected
by text, `INSIDE` is one more key in the same edge's `relations`, and the weight is the text weight; otherwise it is 0.1.

---

## 4. Relation vocabulary

| Relation | Between | Meaning (`subject` → other) | `subject` |
|---|---|---|---|
| `BORN_IN` | PER–LOC | was born in / comes from | person |
| `LOCATED_IN` | PER–LOC | lived, worked, served, fought or was present in | person |
| `VISITED` | PER–LOC | visited, travelled to, arrived in | person |
| `FLED_TO` | PER–LOC | fled, emigrated, was deported to | person |
| `DIED_IN` | PER–LOC | died, was killed or buried in | person |
| `LEADS` | PER–LOC, PER–ORG | holds office of / leads, heads, commands, founded | person |
| `MEMBER_OF` | PER–ORG | member, employee, soldier, deputy, student of | person |
| `STATED_ABOUT` | PER–LOC, PER–ORG | is quoted about / is cited as the source of a claim | person (PER–LOC); `null` (PER–ORG) |
| `OPPOSES` | all except LOC–LOC | attacked, criticized, sanctioned, accused, arrested | who acts; `null` for ORG–LOC |
| `ATTACKED` | ORG–LOC, LOC–LOC | attacked, shelled, invaded, struck | attacker |
| `CONTROLS` | ORG–LOC, LOC–LOC | controls, captured, occupied, annexed | who controls |
| `BASED_IN` | ORG–LOC | headquartered, based, stationed in | organization |
| `OPERATES_IN` | ORG–LOC | operates, fought, was deployed in | organization |
| `SUPPORTS` | ORG–LOC, LOC–LOC | aid, weapons, funding, political support | `null` |
| `PART_OF` | ORG–ORG, LOC–LOC | unit/branch of; located inside / part of (as stated in the text) | the part |
| `NEGOTIATED_WITH` | LOC–LOC | talks, negotiations, agreements between states | `null` |
| `SAME_AS` | PER–PER, ORG–ORG, LOC–LOC | the same entity under another name, spelling or abbreviation | `null` |
| `RELATIVE_OF` | PER–PER | family | `null` |
| `MET_WITH` | PER–PER | met, talked, negotiated | `null` |
| `ALLIED_WITH` | PER–PER, ORG–ORG | allies, colleagues, cooperated, supported each other | `null` |
| `CO_OCCURS_WITH` | all | mentioned together, no specific relation | `null` |
| `INSIDE` | LOC–LOC | geometric containment (3.3) | inner location |
| `IN_THE_TEXT` | entity–TEXT | the entity is mentioned in the text (3.2) | — |

---

## 5. Recipes

### 5.1 Entities and texts around an entity
```python
entity = 'Kyiv'
neighbours = [n for n in G.neighbors(entity) if G.nodes[n]['type'] != 'TEXT']
texts = [n for n in G.neighbors(entity) if G.nodes[n]['type'] == 'TEXT']
strongest = sorted(neighbours, key=lambda n: G[entity][n]['weight'], reverse=True)[:10]
```

### 5.2 The evidence of a relation: the words and the text
```python
def evidence(G, u, v):
    """Every text record of the edge u - v: relation, subject, confidence, the two words and the text."""
    for relation, records in G[u][v]['relations'].items():
        for r in records:
            if 'text_id' not in r:          # INSIDE: geometric, no text
                continue
            node = G.nodes[f"TEXT_{r['text_id']}"]
            text = node['text']
            yield {'relation': relation, 'subject': r['subject'], 'confidence': r['confidence'],
                   'words': (text[r['source_start']:r['source_end']], text[r['target_start']:r['target_end']]),
                   'article': node['source'], 'section': node['title'], 'text': text}

for e in evidence(G, 'Lobau', 'Powązki Military Cemetery'):
    print(e['relation'], e['subject'], e['confidence'], e['words'], '|', e['text'])
```

### 5.3 All edges with a given relation
```python
attacks = [(u, v, r['subject'], r['confidence'])
           for u, v, d in G.edges(data=True)
           for r in d['relations'].get('ATTACKED', [])]
```

### 5.4 The location hierarchy (INSIDE)
```python
def parents(G, place):
    """place -> its parent -> ... up to the largest containing location."""
    chain = [place]
    while True:
        up = [n for n in G.neighbors(chain[-1])
              if any(r['subject'] == chain[-1] for r in G[chain[-1]][n]['relations'].get('INSIDE', []))]
        if not up:
            return chain
        chain.append(up[0])

parents(G, 'Darnytskyi District')   # ['Darnytskyi District', 'Kiyev', 'Ukraine.']
# 'Kiyev' and 'Ukraine.' are spelling variants of Kyiv / Ukraine with the same polygon (see 6, entity unification)
```

### 5.5 Locations in a map area
```python
import shapely
area = shapely.box(36.0, 47.0, 39.0, 49.5)   # lon_min, lat_min, lon_max, lat_max (Donbas)
inside_area = [n for n, d in G.nodes(data=True)
               if d['type'] == 'LOC' and d.get('latitude') is not None
               and area.contains(shapely.Point(d['longitude'], d['latitude']))]
```

---

## 6. Things to know

* **Classifier accuracy:** text relations other than `CO_OCCURS_WITH` are right about 60–65 % of the time (measured on
  hand-labelled pairs). Use `confidence` to filter, and the positions to show or check the source sentence.
* **Same entity, several names:** spellings are not unified yet (`Kyiv`, `Kiyev`, `Kiev` are separate nodes). A colleague
  is working on entity unification; until then, `SAME_AS` relations and identical coordinates hint at duplicates.
* **NER noise:** some entity names are fragments (`'s Republic`, `92`, ` HR`); they have few connections and low weights.
* **Geocoding mistakes:** some names matched the wrong place (e.g. `Donbas` → a street in Skopje, `place_type: road`).
  `place_type` and `importance` help to spot them.
