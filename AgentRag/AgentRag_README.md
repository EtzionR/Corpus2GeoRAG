# GeoRAG agent

> **Using the agent (UI team included): you need your own OpenRouter API key.**
> Create one at https://openrouter.ai/keys. Pass it as `api_key=` to `query()`, or put it in
> `AgentRag/.env` (a copy of `.env.example`). Never put it in `.env.example` or in any `.py`
> file: those are committed. Steps in [Using it](#using-it).
>
> **UI team:** start with [CONNECT_UI.md](CONNECT_UI.md), the short guide to wiring the agent into
> `ui/app.py`. Your current code keeps working; that guide lists what's new.

The project turns warfare-focused Wikipedia text into a geographically aware knowledge graph, so
users can explore it through questions and a map at the same time.

```
Corpus → Texts → NER → Entities → Graph (+ Geocoding) → Agent → UI / Map
```

| Stage | Owner | What the agent gets from it |
|---|---|---|
| Corpus collection | Data team | The articles, split into paragraphs |
| Entity extraction (NER) | NER team | PER / ORG / LOC mentions with their positions |
| Knowledge graph + geocoding | Graph team | `Graph_n_Geocoding/knowledge_graph.json.gz` (Vr6): 120,019 nodes, 64,301 of them paragraphs; 21 typed relations with confidence; points and polygons; the INSIDE hierarchy |
| **Agent (this folder)** | Agent team | Answers questions from the graph only |
| UI + map | UI team | Calls the agent's two Python functions |

## What the agent does

The agent takes a question (plus an optional map selection and the conversation so far), searches
**the graph only**, and returns a written answer with numbered places for the map and the
paragraphs it relied on. Each question goes through six steps:

| Step | File | What happens | LLM? |
|---|---|---|---|
| ① Understand | `planner.py` | The question becomes a plan: its type (where is / list places / who did what / in this area…), names, relations, the map area | one call (simple questions skip it: "Where is Kyiv?") |
| ② Resolve | `resolver.py` | Names become graph entries ("Kiev" → Kyiv, "Zelensky" → Volodymyr Zelenskyy) | only to pick between real candidates |
| ③ Retrieve | `retrieve.py`, `graph_tools.py` | A fixed route per question type walks the graph: places linked to a person, places in a polygon, who attacked whom… | no |
| ④ Evidence | `evidence.py` | Picks the least text that answers: data lines for big lists, the sentences around a relation for "who" questions, article summaries | no |
| ⑤ Write | `writer.py` | Writes the answer, citing places as `[3]` and paragraphs as `[S2]` / `[L1]`; code then removes any citation that points at nothing | one call |
| ⑥ Result | `result.py`, `schema.py` | Builds the JSON below: every place numbered, points and outlines, regions, citations | no |

Coordinates and sources always come from the graph, never from the LLM. `pipeline.py` runs the
steps in order; `georag_agent.query()` and the test harness both use it, so tests see exactly what
the UI gets. Every design choice and its evidence is in [DECISIONS_LOG.md](DECISIONS_LOG.md);
problems found in the graph's data are in [GRAPH_TEAM_ISSUES.md](GRAPH_TEAM_ISSUES.md).

## Using it

### 1. Get your own OpenRouter key

Each person who runs the agent, including the UI team inside their app, needs their **own** key.
Create it at https://openrouter.ai/keys. Then either:

- pass it in each call: `query("...", api_key=your_key)`, e.g. from a key field in the UI; or
- put it in `AgentRag/.env` (`copy .env.example .env` on Windows, `cp` elsewhere) as
  `OPENROUTER_API_KEY=...` and leave `api_key` out.

`.env` is gitignored. A key written into a `.py` file or `.env.example` ends up on GitHub.

### 2. Install

Tested on Python 3.14. Into the environment your app runs in:

```bash
pip install -r AgentRag/requirements.txt
```

The agent reads the graph team's file in place, `Graph_n_Geocoding/knowledge_graph.json.gz`, and
never changes it. It's loaded on the first call (about 15 s) and kept in memory (about 1.1 GB) for
the life of the app. After a `git pull` that updates the graph, restart the app. `GRAPH_PATH` in
`.env` points at a different file.

On loading, the agent leaves out paragraphs from reference sections ("See also", "Sources",
"Further reading", "References"…: 5,021 paragraphs that list titles and books, not prose) and the
names found only there. The file itself is not changed.

### 3. Call it

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "AgentRag"))   # from ui/app.py
from georag_agent import AgentError, get_source_text, query

try:
    result = query("Show me Kyiv", api_key=your_key)   # api_key can be left out if it's in .env
except AgentError as e:
    show_to_user(str(e))                                # every agent error has a readable message
```

A real run (Gemini 2.5 Flash, 2.2 s; the outline is shortened here):

```jsonc
{
  "answer": "Kyiv [1], also spelled Kiev, is the capital and most populous city of Ukraine. It is located in the north-central part of the country, straddling both banks of the Dnieper River [L1]. As of January 2022, Kyiv had a population of 2,952,301, making it the seventh-most populous city in Europe [L1].",
  "answer_plain": "Kyiv, also spelled Kiev, is the capital and most populous city of Ukraine. It is located in ...",
  "status": "answered",
  "grounded": true,
  "shape": "fact",
  "geo_locations": [
    {
      "number": 1, "id": "Kyiv", "label": "Kyiv", "kind": "city", "role": "primary",
      "geometry": {"type": "Point", "coordinates": [30.5241361, 50.4500336]},
      "shape": {"type": "Polygon", "coordinates": [[ /* 189 [lon, lat] points */ ]]},
      "why": "2231 matching paragraphs",
      "sources": ["TEXT_50333"]
    }
  ],
  "regions": [],
  "entities": [],
  "citations": [{"id": "L1", "pointer": "TEXT_50333", "article": "Kyiv", "spans": []}],
  "sources": ["TEXT_50333"],
  "map": {"bbox": [30.17713, 50.17558, 30.88538, 50.62856], "highlight": [1]},
  "follow_ups": ["Tell me more about Kyiv's history.", "What are some of Kyiv's historical landmarks?",
                 "What is the Kyiv Metro?"],
  "did_you_mean": [],
  "notes": ["③ Kyiv is inside: Ukraine.", "④ 1 places found (all go on the map); 1 described to the LLM"],
  "meta": {"question_type": "place_lookup", "model": "google/gemini-2.5-flash", "llm_calls": 2,
           "cost_usd": 0.000896, "seconds": 2.23}
}
```

A question takes 1–6 s with Gemini 2.5 Flash in our tests, plus the graph load on the first call.
Free models are usually slower and rate-limited.

### 4. Run the tests

```bash
cd AgentRag
pip install pytest
python -m pytest
```

The tests use a small stand-in graph and a fake LLM: no key, no cost, about 20 s.
`tests/test_real_graph.py` also checks that the graph team's real file still has the format the
agent expects (it's skipped if the file is missing).

`eval/run.py` runs the real flow on the project's test questions with your key and writes to
`eval/results/`: a table, a step-by-step trace (`_trace.md`), and a `_ui` folder with each
question's result exactly as `query()` returns it (`python eval/run.py --help`). It has a cost cap;
ten questions on Gemini 2.5 Flash cost about $0.02.

**On the model:** `MODEL` is a hardcoded constant in `agent.py`, never read from `.env` or from the
caller. This is intentional: changing it is a deliberate, reviewed code change, not a per-person
setting. Today it's a free model (`nvidia/nemotron-3-ultra-550b-a55b:free`), with OpenRouter's free
router as backup when it's busy, so answers can vary a little between runs.

## Interface

Coordinates are `[longitude, latitude]` (GeoJSON order) everywhere. Inputs and outputs are plain
Python dicts and lists.

### `query(text_prompt, geo_location=None, chat_history=None, api_key=None) -> dict`

| Argument | Value |
|---|---|
| `text_prompt` | The question. Required, not empty. English. |
| `geo_location` | `None`; a point `{"type": "Point", "coordinates": [lon, lat], "radius_m": 500}` (a distance in the question, like "within 2 km", wins; then `radius_m`; then 1 km); or a polygon `{"type": "Polygon", "coordinates": [[[lon, lat], ...]]}`. Lower-case `"point"` / `"polygon"` are accepted too. |
| `chat_history` | Previous turns, oldest first: `[{"query": "...", "response": <a dict query() returned>}, ...]`. Keep each result dict as it came. |
| `api_key` | Your OpenRouter key; optional if `OPENROUTER_API_KEY` is in `AgentRag/.env`. |

Input rules (breaking one raises `InvalidRequestError` naming the field):

- A polygon uses GeoJSON rings: at least 4 positions per ring, the last equal to the first. A box
  from two map clicks is `[[[w, s], [e, s], [e, n], [w, n], [w, s]]]`.
- Longitude within ±180, latitude within ±90.
- Unknown keys are rejected, so a misspelled key fails loudly.

### What comes back

| Field | Meaning |
|---|---|
| `answer` | The written answer, with citation marks (see [Citations](#citations)). |
| `answer_plain` | The same answer without the marks, for showing it plain. |
| `status` | `answered`; `no_data` (nothing in the graph); `out_of_scope` (not about the corpus); `llm_failed` (the write call failed: the places are still there; retry). |
| `grounded` | `false` when the graph had nothing: the answer then starts with "No data from the graph — answer from the LLM only." |
| `shape` | How the answer is written: `list` (more than 10 places: the strongest few and the regions), `fact` (where is / who is), `drilldown` (one person at one place), `explain` (a short result described place by place, a question about something, or a request for detail). |
| `geo_locations` | **Every place found**, strongest first, numbered as the answer cites them. Big lists can hold hundreds (500 for "places connected to Zelenskyy"). |
| `regions` | For lists: country → oblast tree, each with `count` (places inside) and `places` (numbers directly in it). Empty for short answers. |
| `entities` | People and organizations involved (id, `PER`/`ORG`, role relative to the question, record count). |
| `citations` | One per `[S2]` / `[L1]` in the answer: `pointer`, `article`, `section`, and `spans` (character positions of the entities in that paragraph, for highlighting). |
| `sources` | The pointers of everything the answer cites. |
| `map` | `bbox` `[west, south, east, north]` to zoom to (around the places the answer discusses), and `highlight` (their numbers). |
| `follow_ups` | Up to 3 suggested next questions, ready to send as typed. |
| `did_you_mean` | Other graph entries the question's names could have meant. |
| `notes` | What each step noticed (prefixed ①–⑤), e.g. "Kyiv is inside: Ukraine", "the map point may be wrong". For debugging and transparency. |
| `meta` | Question type, model, number of LLM calls, cost in USD, seconds. |

Each entry of `geo_locations`:

| Field | Meaning |
|---|---|
| `number` | The `[n]` in the answer, and what "tell me about number n" refers to. |
| `id`, `label` | The graph's name for the place. |
| `kind` | The geocoder's place type: `city`, `town`, `village`, `state` (an oblast), `country`, `road`, `building`… |
| `role` | `primary`: the answer discusses it. `context`: found, for the map only. |
| `geometry` | Always a GeoJSON Point. |
| `shape` | The outline (Polygon / MultiPolygon / LineString), simplified to at most 300 points. Only for primary places, at most 10 per answer. |
| `why` | One line of data on why it's there, e.g. "ATTACKED in 12 records; 118 matching paragraphs". |
| `uncertain` | Present when the graph's point may be wrong, e.g. "geocoded as a road with importance 0.04", or "geocoded as a river, but its own article describes a city or town" (Dnipro). |
| `sources` | Up to 10 paragraph pointers, best first. |

### Citations

The marks in `answer` say where each statement comes from:

- `[3]`: place number 3 in `geo_locations` (a pin on the map).
- `[S2]`: a passage from the corpus; `citations` gives its pointer, article and section, and
  `get_source_text(pointer)` gives the paragraph.
- `[L1]`: the same, for an article's opening summary.

Code checks every mark before the answer is returned: a mark that points at nothing is removed, and
at most two passages are kept per statement. A UI can turn the marks into clickable links (a pin, a
paragraph), or show `answer_plain` instead.

### Follow-ups

Send previous results back in `chat_history`. "Tell me about number 13" then means place 13 of
the previous result, including places on the map that the answer didn't discuss. "What about
Soledar?" or "Tell me about Zelenskyy in the White House" work as well.

### `get_source_text(pointer) -> dict | None`

The paragraph behind a pointer (`"TEXT_50333"`, from `sources`, `citations` or a place's `sources`).
No LLM, instant.

```python
{"pointer": "TEXT_50333", "text": "Kyiv, also spelt Kiev, is the capital and most populous city of Ukraine. ...",
 "document": "Kyiv", "section": None, "paragraph_index": 0}
```

`document` is the article title, `section` its section heading (if any). An unknown pointer gives
`None`.

### Errors

Every error the agent raises on purpose is an `AgentError` with a readable message, so
`except AgentError` catches them all:

| Exception | Meaning |
|---|---|
| `InvalidRequestError` | An argument doesn't match the contract |
| `LLMNotConfiguredError` | No key given, or OpenRouter rejected it |
| `LLMRateLimitError`, `LLMError` | Kept so existing `except` clauses still work; `query()` no longer raises them (see below) |
| `AgentError` | The graph file wasn't found |

A rate limit or network failure in the middle of a question doesn't raise: the plan falls back to
a keyword reading, and the answer falls back to a template (lists) or `status: "llm_failed"`, with
the places and sources still filled in.

## Files

```
georag_agent.py   query() and get_source_text(): the only two functions the UI calls
pipeline.py       runs the six steps in order
planner.py        ① understand          resolver.py   ② resolve
retrieve.py       ③ retrieve (routes)   graph_tools.py  graph walks used by the routes
evidence.py       ④ evidence            writer.py     ⑤ write
result.py         ⑥ result              schema.py     the input and output contract
graph_index.py    loads the graph and builds the name indexes
geo.py            distances, point-in-polygon, WKT, outline simplification (plain Python)
llm_calls.py      every LLM call, with its model, tokens, cost and time
agent.py          MODEL, get_llm() and the error classes
eval/             the test harness: questions, runs, reports
tests/            pytest
```

## Known limitations

- **Data issues show through.** Some map points are wrong: "Where is Dnipro?" answers correctly
  (a city in eastern Ukraine) but the map gets a 5 km stretch of river near Chernihiv (marked
  `uncertain`). Kharkiv
  Oblast sits inside Russia in the hierarchy, so region counts inherit it. Words from Ukrainian names
  in brackets became places (`Україні`, near Maidan). Listed for the other teams in
  GRAPH_TEAM_ISSUES.md; places with doubtful points carry `uncertain`.
- **Nested places stack on the map:** Washington, the White House and the Oval Office are separate
  places at almost the same point. Clustering nearby pins helps.
- **Big lists are big:** up to ~500 KB for a question that finds 1,652 places. That's the places
  (about 300 bytes each: number, name, point, data line, a few pointers), not text: the answer is a
  few sentences, and paragraphs are never included, only their pointers. Fine in-process.
- **"Countries where both Russia and Ukraine are mentioned"** isn't understood as a country filter
  yet; it returns every shared place (kept on purpose for now; DECISIONS_LOG P2-51).
- **A bare "number 3" follow-up** gives that place, not the previous question's subject at it. Name
  both ("Zelenskyy in the White House") for that.
- **English only.**
