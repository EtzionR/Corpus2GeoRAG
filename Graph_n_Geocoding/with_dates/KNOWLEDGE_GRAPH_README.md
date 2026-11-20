# Knowledge Graph with Dates — README for the RAG

This folder holds a second version of the knowledge graph, **with dates**. The version without dates in
`Graph_n_Geocoding/` stays as it is, so the RAG can be tried on both.

| | `Graph_n_Geocoding/` (without dates) | `Graph_n_Geocoding/with_dates/` (this folder) |
|---|---|---|
| NER file | `post_NER_final.parquet` (`flair/ner-english-large`) | `post_NER_final_plus_date.parquet` (`idoschw3/FlertDate`) |
| Dates | — | `DATE` nodes, `dates` on text nodes, `date` on relation records |
| Size | 154,486 nodes, 798,102 edges | 167,061 nodes, 861,670 edges (9,202 of the nodes are dates) |

**What changed, in short:**

1. **A newer NER model.** FlertDate is the FLERT model fine-tuned on our corpus, with a fifth label, `DATE`. On 100
   paragraphs checked by hand its F1 on people, organizations, locations and other names is 0.913 (the old model: 0.893),
   with fewer wrong names (precision 0.92 instead of 0.87), and 0.877 on dates. The entities are therefore not exactly the same
   as in the version without dates: about 9,000 names are new and 7,000 are gone, mostly fragments the old model cut wrongly.
   Titles are now sometimes part of a name (`President Putin`, `Russian defense ministry`), so some people and
   organizations have one more spelling.
2. **Dates** (section 3): calendar nodes for years, months and days, linked to the texts that mention them; the dates of every
   text; and a date on every relation record, so "who attacked what in 2024" can be answered from the graph.

Everything else (relations, relation fixes, geocoding, INSIDE, weights) is built exactly as in the version without dates.

**Comparing the two versions.** They differ in two things, the NER model and the dates. To see what the dates alone add, use
this graph twice: once ignoring its dates (skip `DATE` nodes and the `date` / `dates` fields: that is the graph without dates
on the new NER), and once with them.

* **Format:** NetworkX *node-link* JSON, undirected graph: `{"directed": false, "multigraph": false, "graph": {}, "nodes": [...], "links": [...]}`.
* **Size:** 167,061 nodes — 89,284 texts, 68,575 entities (18,770 PER, 34,075 ORG, 15,730 LOC) and
  9,202 dates (488 years, 1,332 months, 7,382 days) — and 861,670 edges.
* **File:** `knowledge_graph.json.gz`, 49 MB (gzip). The other files here are the caches the notebook reuses on its next run
  (`geocoding_results.parquet`, `von_results.parquet`, `relation_fixes.parquet`).

---

## 1. Using it in the RAG (AgentRag)

**Point the agent at this graph** in `AgentRag/.env`:

```
GRAPH_PATH=C:/path/to/Corpus2GeoRAG/Graph_n_Geocoding/with_dates/knowledge_graph.json.gz
```

`graph_index.py` reads `GRAPH_PATH`; without it the agent keeps loading the version without dates. Use the full path: a
relative one is read from the folder the app is started in. Restart the app after changing it.

**One line must change.** `GraphIndex` treats every node that is not a text as an entity (`graph_index.py`, `__init__`):

```python
self.entities = [n for n, d in G.nodes(data=True) if d.get("type") != "TEXT"]
```

With this graph that list would include the date nodes, so a name search could return `DATE_2022` as if it were an entity.
Exclude them:

```python
self.entities = [n for n, d in G.nodes(data=True) if d.get("type") not in ("TEXT", "DATE")]
```

Nothing else breaks: date nodes are linked only to texts and to each other, so the tools that walk from an entity to its
neighbours (`entity_records`, `common_neighbors`, `connected_places`, `mentions`) never reach them.

**Using the dates.** The planner already extracts `time_words` from the question ("in 2024", "since February 2022") but
nothing uses them yet. Three ways, from the simplest:

1. **Show dates in answers:** every record has `date` and every text node has `dates`, so the writer can say *when*
   (recipe 6.2).
2. **Filter or rank records by time:** turn the question's time words into a range and keep the records whose `date`
   overlaps it (recipe 6.3). We suggest ranking dated records in the range first rather than dropping undated ones,
   because many records have no date at all.
3. **Start from a date:** "what happened on 24 February 2022?" → node `DATE_2022-02-24` → its texts → the entities
   in them (recipe 6.4).

`parse_date()` in the notebook's **Dates** cell turns a written date into a range; the agent can reuse it for the question's
time words.

---

## 2. Loading

```python
import gzip
import json
import networkx as nx

with gzip.open('knowledge_graph.json.gz', 'rt', encoding='utf-8') as f:
    data = json.load(f)

G = nx.node_link_graph(data, edges='links')   # NetworkX >= 3.4
```

---

## 3. Nodes

Every node has an `id` and a `type`: `TEXT`, `PER`, `ORG`, `LOC` or `DATE`.

### 3.1 `TEXT` — a paragraph of the corpus

```json
{"id": "TEXT_43100", "type": "TEXT", "text_id": 43100,
 "text": "On April 24, 2022, Secretary Austin and Secretary of State Antony Blinken visited Kyiv, Ukraine, and met with President Volodymyr Zelenskyy ...",
 "source": "Lloyd Austin", "index": 107, "title": "U.S. Secretary of Defense (2021–2025)", "sub_title": "Tenure",
 "dates": [{"start": 3, "end": 17, "text": "April 24, 2022", "from": "2022-04-24", "to": "2022-04-24",
            "granularity": "day", "year_inferred": false}]}
```

| Field | Meaning |
|---|---|
| `id` | `TEXT_<text_id>` |
| `text_id` | 0 … 89,283, in the order of the NER file; this is the number the relations point to |
| `text` | the paragraph |
| `source` | the Wikipedia article |
| `index` | the paragraph number inside the article |
| `title`, `sub_title` | the section and subsection headings (`null` when the paragraph has none) |
| `dates` | **new:** every DATE mention in the paragraph, in text order (empty list when there is none), see below |

A `dates` item:

| Field | Meaning |
|---|---|
| `start`, `end` | position in the text: `text[start:end]` is the mention |
| `text` | the mention as written |
| `from`, `to` | the calendar range it covers, ISO `YYYY-MM-DD` (`"2022-02-01"`–`"2022-02-28"` for February 2022); `null` when it has no date (see below) |
| `granularity` | `day`, `month`, `year`, `range` (two ends: `24–25 February 2022`, `2014–2015`), `decade`, `century`, or `null` |
| `year_inferred` | `true` when the mention had no year (`24 February`) and the year was taken from the context |

Mentions without a date (`from: null`) are relative (`the next day`, `two weeks later`) or a day or month whose year could
not be taken safely. **Year rule:** the year comes from the closest earlier date with a year in the same paragraph — unless the
month is before that date's month (`December 2021 … 3 January` could be either year); in a paragraph with no year at all, from
the single year of the closest heading that has one (sub-title, title, or the article name, e.g. *Timeline of the Russian
invasion of Ukraine (24 February – 7 April 2022)*). A date the NER split in two (`August 24` + `2022`) is joined back
into one mention.

### 3.2 `PER`, `ORG` — people and organizations

```json
{"id": "Volodymyr Zelenskyy", "type": "PER"}
```

`id` is the entity name as the NER model found it. Each name has one type (the one the NER model gave it most often).

### 3.3 `LOC` — locations, with geocoding (Nominatim / OpenStreetMap)

```json
{"id": "Kyiv", "type": "LOC", "latitude": 50.4500336, "longitude": 30.5241361, "address": "Kyiv, Ukraine",
 "place_type": "city", "importance": 0.7858, "geometry_wkt": "POLYGON ((30.23615 50.42681, 30.24136 50.42458, ..."}
```

| Field | Meaning |
|---|---|
| `latitude`, `longitude` | WGS 84 (EPSG:4326), decimal degrees |
| `address` | the full address in English |
| `place_type` | `country`, `state` (oblast), `city`, `town`, `village`, `city_district`, `peninsula`, `sea`, `road`, … |
| `importance` | 0–1, how prominent the place is in OSM/Wikipedia; a rough confidence for the match |
| `geometry_wkt` | the polygon (or point / line) as WKT. **WKT order is `lon lat`** |

Locations Nominatim did not find have `null` geocoding fields.

### 3.4 `DATE` — a calendar day, month or year (new)

```json
{"id": "DATE_2022-02-24", "type": "DATE", "granularity": "day", "from": "2022-02-24", "to": "2022-02-24"}
{"id": "DATE_2022-02",    "type": "DATE", "granularity": "month", "from": "2022-02-01", "to": "2022-02-28"}
{"id": "DATE_2022",       "type": "DATE", "granularity": "year", "from": "2022-01-01", "to": "2022-12-31"}
```

One node per day, month and year that a text mentions, plus the month and year above every day (so the calendar chain is
complete). Decades and centuries have no node; they are only in the texts' `dates`.

---

## 4. Edges

Every edge has exactly four fields: `source`, `target`, `weight`, `relations` (relation name → list of records).

### 4.1 Entity ↔ entity — relations from the text

```json
{"source": "Antony Blinken", "target": "Volodymyr Zelenskyy", "weight": 4.66,
 "relations": {
   "MET_WITH": [{"text_id": 43100, "source_start": 59, "source_end": 73, "target_start": 120, "target_end": 139,
                 "subject": null, "confidence": 0.58,
                 "date": {"text": "April 24, 2022", "from": "2022-04-24", "to": "2022-04-24", "granularity": "day",
                          "nodes": ["DATE_2022-04-24"], "scope": "sentence", "year_inferred": false}}]}}
```

| Field | Meaning |
|---|---|
| `text_id` | the text node `TEXT_<text_id>` |
| `source_start`, `source_end` | position of the **source** entity in that text |
| `target_start`, `target_end` | position of the **target** entity in that text |
| `subject` | the entity the relation reads from, i.e. who acts. `null` = symmetric relation |
| `confidence` | the classifier's score (0–1); `0.77` = changed by the relation fixes; `null` = not classified |
| `date` | **new:** the date of this record, or `null` (below) |

**`date`** is a date mention from the record's text:

* `scope: "sentence"` — the closest date in the same sentence as the two entities (*"On 24 February 2022, Russia attacked
  Kharkiv"*). This is the reliable case.
* `scope: "paragraph"` — the sentence has no date, so this is the last date before the two entities in the paragraph
  (*"On 24 February 2022 … Later that day, Russian troops entered Kharkiv"*). Usually right in narrative paragraphs, weaker
  elsewhere.
* `null` — no usable date before or around the pair.

`from`, `to`, `granularity` and `year_inferred` are as in the text's `dates`; `nodes` are the date nodes of the mention (two
for a range). **Note:** the date is the one *written near* the relation, which is usually but not always the date of the event:
in a sentence like *"Wagner, founded in 2014, captured Bakhmut"* the date of the record Wagner–Bakhmut would be 2014.

Of the typed records (not `CO_OCCURS_WITH`), about 38 % have a date from their sentence, 15 % from their paragraph, and 47 %
none.

The rest is as in the version without dates: one record = one sentence where the two entities appear together (or one per
text when they are never in the same sentence); `weight` $= \max(0.1,\ S \cdot \ln(1 + C_{\text{eff}}))$ measures how strongly
they are connected; relations come from `von` and are then corrected by the relation fixes (junk names, lists, landmarks
and sources, missed patterns, and a second model that checks each relation against its sentence). See
`Graph_n_Geocoding/KNOWLEDGE_GRAPH_README.md` for the details and the accuracy figures, which were measured on the version
without dates.

### 4.2 Entity → text — `IN_THE_TEXT`

```json
{"source": "Kyiv", "target": "TEXT_43100", "weight": 1, "relations": {"IN_THE_TEXT": [{"start": 82, "end": 86}]}}
```

Every entity is linked to every text that mentions it; `weight` = number of mentions.

### 4.3 Date → text — `IN_THE_TEXT` (new)

```json
{"source": "DATE_2022-04-24", "target": "TEXT_43100", "weight": 1,
 "relations": {"IN_THE_TEXT": [{"start": 3, "end": 17, "year_inferred": false}]}}
```

Every date node is linked to every text that mentions it, with the text always as `target`. A range is linked to both of its
ends' nodes.

### 4.4 Location → location, date → date — `INSIDE`

```json
{"source": "Darnytskyi District", "target": "Kyiv", "weight": 0.1,
 "relations": {"INSIDE": [{"subject": "Darnytskyi District", "basis": "geometry"}]}}
{"source": "DATE_2022-04", "target": "DATE_2022-04-24", "weight": 0.1,
 "relations": {"INSIDE": [{"subject": "DATE_2022-04-24", "basis": "calendar"}]}}
```

`subject` is the inner node. For locations (`basis: "geometry"`) the other end is the smallest location whose polygon contains
it; for dates (`basis: "calendar"`) a day is inside its month and a month inside its year.

---

## 5. Relation vocabulary

Unchanged from the version without dates (`Graph_n_Geocoding/KNOWLEDGE_GRAPH_README.md`, section 4). `INSIDE` now also links
dates (`basis: "calendar"`), and `IN_THE_TEXT` also links dates to texts.

---

## 6. Recipes

### 6.1 Entities, texts and dates around an entity
```python
entity = 'Kharkiv'
neighbours = [n for n in G.neighbors(entity) if G.nodes[n]['type'] not in ('TEXT', 'DATE')]
texts = [n for n in G.neighbors(entity) if G.nodes[n]['type'] == 'TEXT']
dates = sorted({d['from'] for t in texts for d in G.nodes[t]['dates'] if d['from']})   # dates in its texts
```

### 6.2 The evidence of a relation, with its date
```python
def evidence(G, u, v):
    for relation, records in G[u][v]['relations'].items():
        for r in records:
            if 'text_id' not in r:          # INSIDE: no text
                continue
            node = G.nodes[f"TEXT_{r['text_id']}"]
            text = node['text']
            yield {'relation': relation, 'subject': r['subject'], 'confidence': r['confidence'],
                   'words': (text[r['source_start']:r['source_end']], text[r['target_start']:r['target_end']]),
                   'date': r['date']['text'] if r['date'] else None, 'article': node['source'], 'text': text}
```

### 6.3 Records in a period
```python
def overlaps(date, start, end):
    """date: a record's `date` (or None); start, end: ISO strings, e.g. '2024-01-01', '2024-12-31'."""
    return date is not None and date['from'] <= end and date['to'] >= start

attacks_2024 = [(u, v, r['subject'], r['date']['text'])
                for u, v, d in G.edges(data=True)
                for r in d['relations'].get('ATTACKED', [])
                if overlaps(r.get('date'), '2024-01-01', '2024-12-31')]
# Stricter: also require r['date']['scope'] == 'sentence' and not r['date']['year_inferred']
```

ISO strings compare correctly as text, so no date parsing is needed.

### 6.4 Texts and entities of a date
```python
def texts_of(G, date_node):
    """Texts that mention the date or any day/month inside it (2022-02 -> its days too)."""
    nodes, todo = {date_node}, [date_node]
    while todo:
        n = todo.pop()
        for m in G.neighbors(n):
            if G.nodes[m]['type'] == 'DATE' and any(r['subject'] == m for r in G[n][m]['relations'].get('INSIDE', [])):
                nodes.add(m); todo.append(m)
    return {t for n in nodes for t in G.neighbors(n) if G.nodes[t]['type'] == 'TEXT'}

texts = texts_of(G, 'DATE_2022-02-24')
entities = {e for t in texts for e in G.neighbors(t) if G.nodes[e]['type'] in ('PER', 'ORG', 'LOC')}
```

### 6.5 The graph without its dates (to compare with the version without dates)
```python
H = G.copy()
H.remove_nodes_from([n for n, t in G.nodes(data='type') if t == 'DATE'])
# and ignore the 'dates' field of text nodes and the 'date' field of records
```

---

## 7. Things to know

* **How many dates:** 74,565 DATE mentions in 43,611 texts. 67,539 are linked to a date node
  (8,219 of them with an inferred year); 6,064 have no date (relative, or no safe year).
* **Relation records with a date:** 125,515 from their sentence, 290,698 from their paragraph, 355,518 without
  — about 54 % of the records have a date.
* **Big dates:** the largest date nodes are years: `DATE_2022` is linked to 2,168 texts, and to 8,181 with its months and days
  (recipe 6.4). The largest day is `DATE_2022-02-24` (440 texts). Dates are linked only to texts, so they do not crowd entity
  neighbourhoods.
* **Date accuracy:** the NER's F1 on dates is 0.877 on 100 hand-checked paragraphs. The conversion to calendar ranges covers
  98 % of the DATE mentions; the rest are fragments such as `late` or `p.m`.
* **Same entity, several names:** spellings are not unified yet (`Kyiv`, `Kiyev`, `Putin`, `President Putin`). The agent's
  variant groups join many of them.
