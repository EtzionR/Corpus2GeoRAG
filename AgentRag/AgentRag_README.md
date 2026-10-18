# GeoRAG — From Corpus into GeoRAG (POC)

> **Using the agent (UI team included): you need your own OpenRouter API key.**
> Free to create at https://openrouter.ai/keys, and it costs nothing with the free
> models this POC uses. Pass it as `api_key=` to `query()`, or put it in
> `AgentRag/.env` (a copy of `.env.example`). Never put it in `.env.example` or in
> any `.py` file — those are committed. Steps in [Using it](#using-it).
>
> **UI team:** start with [CONNECT_UI.md](CONNECT_UI.md), the short guide to wiring
> the agent into `ui/app.py`.

Turns unstructured text (Wikipedia, warfare-focused) into a geographically-aware
knowledge graph, so users can explore it through natural-language questions and
an interactive map at the same time.

```
Corpus → Texts → NER → Entities → Graph (+ Geocoding) → Agent → UI / Map
```

| Stage | Owner | Status |
|---|---|---|
| Corpus collection | Data team | — |
| Entity extraction (NER) | NER team | PER / LOC / ORG, no event typing yet |
| Knowledge graph + geocoding | Graph team | NetworkX DiGraph, `CO_OCCURS_WITH` only, points only |
| **Agent (this folder)** | **You** | **See below** |
| UI + map | UI team | Calls the agent's two Python functions |

## My part: the agent

The agent sits between the graph and the UI. It takes a user's question (plus
optional map location and conversation history), decides how to search the
**graph only** — never outside knowledge — and returns a narrative answer plus
the geographic data the map needs to plot it.

Flow for one query:

1. **Tool-calling loop** (`agent.py: run_tool_loop`) — an LLM call decides which
   graph tools to call (`find_entities`, `get_related`, `search_mentions`) and
   in what order, gathering evidence until it has enough.
2. **Synthesis** (`agent.py: generate_answer`) — a separate LLM call turns the
   gathered evidence into a structured draft: answer text + the node ids to show
   on the map. It never writes a coordinate itself.
3. **Resolve** (`agent.py: build_response`) — plain code looks up every chosen
   node's real coordinates and citation sources from the graph. This is the
   trust boundary: the LLM picks *what*, code supplies *where*.

[DESIGN.md](DESIGN.md) walks through this flow step by step and records the
design decisions behind it (and the known gaps). This README is the quick-start.

## Architecture

```
georag_agent.py    The two functions the UI calls: query() and get_source_text()
contracts.py       Input/output models — the one source of truth both sides
                    code against (see Interface below)
agent.py           MODEL constant, entity resolution, the three tools, the
                    tool-calling loop, synthesis, run_agent
graph_client.py    GraphClient interface + NetworkXGraphClient, which adapts
                    the real graph's schema (PER/LOC/ORG, CO_OCCURS_WITH,
                    evidence + source_doc on edges) to a clean contract
tests/             pytest suite — runs without an API key or network
```

The agent reads the graph team's file in place,
`../Graph_n_Geocoding/knowledge_graph.json`, and never modifies it. It's loaded
once, on the first call; after the graph team updates it, `git pull` and restart
your app. To point at a different file, set `GRAPH_PATH` in `.env`.

## Using it

### 1. Get your own OpenRouter key

Each person who runs the agent — including the UI team, inside their app —
needs their **own** OpenRouter API key. You do not need anyone else's key, and
no one needs to be online for you to run it.

1. Sign up at https://openrouter.ai and create a key at https://openrouter.ai/keys.
2. The agent uses OpenRouter's **free** models for now (see "On the model"
   below), so testing costs nothing. Free models are rate-limited; if you hit
   the limit you get an `LLMRateLimitError` — wait a bit and retry.
3. Give the agent your key in one of two ways:
   - pass it in each call: `query("...", api_key=your_key)` — e.g. from a key
     field in your UI, or from your own secrets file; or
   - put it in `AgentRag/.env` (`cp .env.example .env`, Windows:
     `copy .env.example .env`) as `OPENROUTER_API_KEY=...` and leave `api_key` out.

   Never write the key into a `.py` file or into `.env.example`: both are
   committed, and a key pushed to GitHub is public. `.env` is gitignored.

### 2. Install

Tested on Python 3.14. Install the agent's requirements into the environment
your app runs in:

```bash
git clone https://github.com/EtzionR/Corpus2GeoRAG.git
cd Corpus2GeoRAG
git checkout feature/agentic-rag     # until this is merged to main
pip install -r AgentRag/requirements.txt
```

### 3. Call it

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "AgentRag"))   # from ui/app.py
from georag_agent import AgentError, get_source_text, query

try:
    result = query("Where is Kyiv?", api_key=your_key)   # api_key can be left out if it's in .env
except AgentError as e:
    show_to_user(str(e))      # every agent error has a readable message
```

A real run of that call takes a few seconds and returns:

```python
{
  "answer": "According to the corpus, Kyiv is located at latitude 50.4500336, longitude 30.5241361.",
  "geo_locations": [{"id": "Kyiv", "label": "Kyiv", "kind": "place", "sources": [],
                     "geometry": {"type": "point", "coordinates": [30.5241361, 50.4500336]}}],
  "sources": []
}
```

To see every tool call the agent makes, turn on debug logging for it:
`logging.basicConfig(); logging.getLogger("agent").setLevel(logging.DEBUG)`.

### 4. Run the tests

```bash
cd AgentRag
pip install pytest
python -m pytest
```

The tests use a small stand-in graph and a fake LLM, so they need no key and
cost nothing. `tests/test_real_graph.py` also checks that the graph team's real
file still has the schema the agent expects.

**On the model:** `MODEL` is a hardcoded constant in `agent.py`, not something
set through `.env` or the caller. This is intentional — it stays on a free/cheap
model until the design is validated, and changing it is a deliberate code change
reviewed through a PR, not a per-person setting. Please don't override it locally
in a way that gets committed. Today it is `openrouter/free`, which picks an
available free model per request, so answers can vary a little between runs.

## Interface

Coordinates are `[longitude, latitude]` (GeoJSON order) everywhere. Inputs and
outputs are plain Python dicts and lists — no need to import our models.

### `query(text_prompt, geo_location=None, chat_history=None, api_key=None) -> dict`

```jsonc
// arguments
text_prompt   "Where did drone attacks happen near this point?"
geo_location  {
                "type": "point",              // "point" | "polygon", or None for no location
                "coordinates": [30.52, 50.45],
                "radius_m": 500               // optional, point only
              }
chat_history  [ { "query": "...", "response": { /* a dict query() returned earlier, as is */ } } ]
api_key       "your OpenRouter key"           // optional if OPENROUTER_API_KEY is in AgentRag/.env

// returns
{
  "answer": "According to the corpus, ...",
  "geo_locations": [
    {
      "id": "Kharkiv",              // graph node id - needed to resolve follow-ups like
                                     // "tell me more about number 2" against chat_history
      "label": "Kharkiv",
      "geometry": { "type": "point", "coordinates": [36.23, 49.99] },
      "kind": "event",              // "event" | "place"
      "sources": ["pointer-or-doc-id", "..."]
    }
  ],
  "sources": ["pointer-or-doc-id", "..."]   // union across the whole answer
}
```

Input rules (breaking one raises `InvalidRequestError` saying which field is wrong):

- `text_prompt` is required and can't be empty.
- A polygon uses GeoJSON rings — `"coordinates": [[[lon, lat], [lon, lat], [lon, lat], [lon, lat]]]`
  — with at least 4 positions per ring, the last equal to the first. `radius_m`
  is not allowed on a polygon. A bounding box from two map clicks is a polygon
  with 5 positions: `[[[w, s], [e, s], [e, n], [w, n], [w, s]]]`.
- Longitude must be within ±180 and latitude within ±90. Note `type` is
  lowercase (`"point"`), unlike standard GeoJSON's `"Point"`.
- Unknown keys in `geo_location` are rejected, so a misspelled key fails loudly
  instead of being silently ignored.

### `get_source_text(pointer) -> dict | None`

A separate lookup so the main result stays small — call it only when the user
actually asks to see a source. No LLM involved.

```jsonc
// argument: any value from a result's "sources"
// returns
{ "text": "the actual corpus passage", "document": "which document it came from" }
```

Today a pointer is a source document title, and `text` is every distinct
passage from that document found in the graph, separated by blank lines. An
unknown pointer returns `None`.

### Errors

Every error the agent raises on purpose is an `AgentError` with a readable
message, so `except AgentError` catches them all. The subclasses, if you want
to handle one differently:

| Exception | Meaning |
|---|---|
| `InvalidRequestError` | An argument doesn't match the contract |
| `LLMNotConfiguredError` | No key given, or OpenRouter rejected it |
| `LLMRateLimitError` | OpenRouter rate limit (common on free models) — retry shortly |
| `LLMError` | OpenRouter failed, or the LLM's answer couldn't be used — retry |

## Current status / known limitations

- **Spatial filtering (point/radius, bounding box) is not built yet** — `geo_location`
  is part of the locked contract, but the agent doesn't act on it yet. Needed
  before "what happened near this point" / "drone attacks in this box" type
  questions work.
- **Conversation history is not wired in yet** — `chat_history` is accepted and
  validated, but the agent answers each question on its own, so follow-ups like
  "tell me more about number 2" don't work yet.
- **`sources` only covers the map locations, and only from some tools.** If an
  answer has no `geo_locations`, or the agent only used `find_entities` (as in
  the Kyiv example above), `sources` comes back empty. This is the notebook's
  behaviour, ported as is; see DESIGN.md §7.
- **`kind` is always `"place"` today** — only location nodes have coordinates;
  `"event"` needs event nodes the graph doesn't have yet.
- **`search_mentions` is plain substring matching** over edge evidence text, not
  semantic search — it won't find an event mentioned without those exact words.
- **No retrieval budgeting yet.** A broad question against a large graph can
  return a lot of raw evidence; this hasn't been capped or summarized yet.
- **Text currently lives inline on graph edges (`evidence`)**, duplicated once per
  edge. A pointer-based system (graph stores a locator, agent fetches text from
  the corpus on demand) is planned to fix this, behind the same
  `get_source_text()` — the contract shouldn't need to change when that lands.
- **No `confidence` field** in the response — deliberately cut for now; the only
  signal available (the LLM's own self-rating) wasn't grounded in anything
  measurable. On the wishlist for later, once there's a real basis for it
  (source count, whether resolution needed a fuzzy match, etc.). Per-location
  `annotations` were cut for the same phase.
