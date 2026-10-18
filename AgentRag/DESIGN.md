# GeoRAG Agent: flow and design decisions

This is for anyone who works on the agent or connects to it: the UI team, the graph team, and
us. [AgentRag_README.md](AgentRag_README.md) covers setup and the interface. This file explains
how one question moves through the code and why it's built this way. The design was first
worked out in a prototype Jupyter notebook; "the notebook" below refers to it.

---

## 1. What the agent does

It takes a user's question, plus an optional map location and the conversation so far. It
searches the **knowledge graph only** (never outside knowledge) and returns two things: a
written answer, and the places the map should show, each with its real coordinates and the
source documents behind it.

## 2. One question, end to end

```
UI code ── query(text_prompt, ..., api_key) ──▶ georag_agent.py
                        │  1. QueryRequest checks the input (InvalidRequestError if it's wrong)
                        │     The graph file is loaded on the first call and kept.
                        ▼
                      agent.run_agent(text_prompt, graph, api_key)
                        │
                        ├─ 2. run_tool_loop         LLM call, repeated (up to 6 rounds)
                        │     The LLM asks for tools: find_entities / get_related / search_mentions.
                        │     Code runs each against the graph, returns the result as text,
                        │     and records which source document backed each entity.
                        │     It stops when the LLM stops asking for tools.
                        │
                        ├─ 3. generate_answer       one more LLM call
                        │     all gathered evidence in ─▶ LLMDraft { answer, feature_node_ids }
                        │
                        └─ 4. build_response        plain code, no LLM
                              For each id the LLM picked: is it in the graph? Does it have
                              coordinates? Coordinates and sources come from the graph and the
                              citation log, never from the LLM.
                        ▼
                      dict { answer, geo_locations, sources } ──▶ UI code

UI code ── get_source_text(pointer) ──▶ graph lookup, no LLM ──▶ { text, document } or None
```

| Step | Code | What it does |
|---|---|---|
| Entry | `georag_agent.py: query, get_source_text` | The only two functions the UI calls |
| Validate | `contracts.py: QueryRequest` | Rejects bad input before any work happens |
| Research | `agent.py: run_tool_loop` | The LLM chooses which tools to call and when to stop |
| Write | `agent.py: generate_answer` | A separate LLM call turns the evidence into an answer and a list of node ids |
| Resolve | `agent.py: build_response` | Code attaches real coordinates and sources (the trust boundary, section 3) |
| Graph access | `graph_client.py: NetworkXGraphClient` | The only code that knows the graph team's raw schema |

**Example: "Where is Kyiv?"** (a real run on the free model, about 8 seconds)

1. `find_entities("Kyiv")` returns `Found: id=Kyiv, type=location, lat=50.4500336, lon=30.5241361`
2. The LLM has enough and stops calling tools
3. `generate_answer` returns `answer: "According to the corpus, Kyiv is located at ..."` and
   `feature_node_ids: ["Kyiv"]`
4. `build_response` looks Kyiv up in the graph and returns
   `geometry: {type: "point", coordinates: [30.5241361, 50.4500336]}`

A question like "Tell me about Kharkov." runs longer: `find_entities` corrects the spelling to
Kharkiv, then `get_related("Kharkiv")` pulls in every connection, with its evidence text and
source document.

## 3. The trust boundary: the LLM picks *what*, code supplies *where*

An LLM can invent a plausible coordinate or an entity that doesn't exist. So the LLM only
writes text and picks node **ids**. `build_response` then:

- drops any id that isn't in the graph, or whose node has no coordinates
- takes coordinates from the graph node, in `[lon, lat]` order
- takes sources from the citation log the tools filled in, not from the LLM's text

This is enforced in code and tested in
`tests/test_agent.py::test_build_response_takes_coordinates_and_sources_only_from_the_graph`.

## 4. Typos and ambiguous names

Resolved in code (`resolve_entity_name`), in one pass, without stopping to ask the user:

| Situation | What happens | Why |
|---|---|---|
| Exact match (any case) | Used directly | Nothing to resolve |
| One clear best match (typo, alternate spelling) | Corrected, with a note the LLM sees | Asking "did you mean Kharkiv?" costs a round trip for no benefit |
| Several names match about equally well | **Not guessed.** The LLM is told to report the ambiguity | A wrong guess is worse than saying so |
| No match | Said plainly | No match means no answer, not an invented one |

## 5. The tools

| Tool | Use | Returns |
|---|---|---|
| `find_entities(name)` | Turn a name into a real graph id. Always called first for a named entity | id, type, coordinates if any, and a correction note |
| `get_related(entity_id, relation="")` | What's connected to an entity | One line per connection, with evidence text and source document |
| `search_mentions(keyword)` | Questions about a *kind* of event ("drone attacks"), since the graph has no event nodes | Every edge whose evidence contains the keyword |

The tool docstrings and the two system prompts are copied word for word from the notebook. The
LLM reads them, so changing them changes the agent's behaviour.

---

## 6. Decisions

### 6.1 The agent is two Python functions, not a web service

The UI team imports `georag_agent.py` and calls `query()` and `get_source_text()` directly, on
their own OpenRouter key. There is no server to start and no network call between the UI and
the agent. The UI is a Streamlit app, which is Python, so this is the simplest way to connect:
one `import`, and errors arrive as ordinary Python exceptions.

The trade-off: the UI's environment has to install our requirements, and a UI that isn't written
in Python couldn't call this directly. If that ever happens, a small web wrapper around `query()`
can be added (an earlier version of this port had one) without changing the agent itself.

### 6.2 Each query gets its own citation log (replaces the notebook's global `CTX`)

**The problem.** In the notebook, the tools recorded citations in one shared variable, `CTX`,
which was reset at the start of each question. That's fine when one question runs at a time.
Inside an app, two queries can overlap: Streamlit runs each browser session on its own thread,
so two tabs (or two people using the same running app) can ask at the same moment. With a
single shared `CTX`:

1. Query A asks about Kharkiv. Its tool loop starts and resets `CTX`.
2. While A waits on the LLM, query B asks about Kherson. B's loop resets `CTX` again.
3. A's later tool calls now write into the log B is using.
4. A's answer comes back with missing sources, and B's answer has some of A's sources mixed in.

Nothing crashes. The citations are just wrong, and only sometimes, which makes this very hard
to track down later.

**The fix.** `run_tool_loop` creates a fresh `RetrievalContext` for each query and builds that
query's tools with `make_tools(ctx)`. Each query's tools can only write into its own log. The
tools' names, docstrings and outputs are unchanged. Tested in
`test_each_request_keeps_its_own_citations`.

The POC runs one query at a time, so this wouldn't happen in normal use today. The fix is kept
anyway: it costs nothing, and it covers the cases where two queries do overlap.

### 6.3 The model is a hardcoded constant, on the free router for now

`MODEL = "openrouter/free"` in `agent.py`. It is never read from `.env` or from the caller, and
`query()` has no model argument. While the flow is still being validated, the free router keeps
testing at no cost. Switching to a paid model later is a one-line code change, reviewed through
a PR.

Side effect to keep in mind: `openrouter/free` picks whichever free model is available for each
query, so tool-calling quality can vary between runs, and free models are rate-limited
(`LLMRateLimitError`).

### 6.4 Everyone runs on their own OpenRouter key

Anyone who runs the agent, including the UI team inside their app, creates their own key at
https://openrouter.ai/keys. Nobody needs anyone else's key, and nobody else needs to be online.
There are two ways to provide it, and the first one wins:

1. `query(..., api_key=...)`, for example from a key field in the UI or the UI's own secrets file
2. `OPENROUTER_API_KEY` in `AgentRag/.env` (copy `.env.example`; `.env` is gitignored)

**Why the key isn't a variable at the top of a `.py` file:** that file gets committed. Whoever
fills in the variable has to remember to blank it before every commit, and one slip publishes the
key on GitHub, where automated scanners find leaked keys within minutes. Once credits are added
to an OpenRouter account, a leaked key spends real money. The `api_key` argument is just as easy
to find (it's the first thing in `georag_agent.py`'s docstring) and never lives in a committed file.

How the key is protected:
- It is never written in code, never logged, and never part of an error message.
- Only OpenRouter receives it.
- A test (`test_model_is_the_hardcoded_constant_and_the_key_is_not_exposed`) checks that the LLM
  client's text representation doesn't contain the key.

### 6.5 The graph is read in place from the graph team's folder

`georag_agent.py` loads `../Graph_n_Geocoding/knowledge_graph.json` on the first call and keeps
it for the life of the app. We never edit that file.

- **Picking up the graph team's updates:** the graph changes rarely, so there's no need to pull
  every time. When you know it changed, `git pull` and restart the app.
- **Using a different file** (for example a local build of the graph): set `GRAPH_PATH` in `.env`.
- **No fallback graph.** If the file is missing, `query()` raises an `AgentError`. The notebook fell
  back to a small stand-in graph, but in an app that would quietly answer from 8 made-up nodes and
  look like it works. The stand-in graph now lives only in the tests.
- **Early warning:** `tests/test_real_graph.py` checks the real file has the schema the adapter
  expects (PER/LOC/ORG nodes, coordinates on every LOC, evidence and source on every edge). If it
  fails after a pull, the graph changed, and `NetworkXGraphClient` is the place to adapt.

### 6.6 The result follows the contract, not the notebook's shapes

| Notebook (`AgentResponse`) | Now (`AgentResponse`, returned as a dict) | Why |
|---|---|---|
| `features` | `geo_locations` | Contract name |
| `node_id` | `id` | Contract name |
| `lat`, `lon` | `geometry: {type: "point", coordinates: [lon, lat]}` | GeoJSON order |
| `annotations` | removed | Planned for a later phase |
| `confidence` | removed | Planned for a later phase; the only signal available was the LLM rating itself |

`LLMDraft` lost `annotations` and `confidence` too, so the LLM isn't asked for output we would
throw away. `query()` returns plain dicts, so the UI never needs to import our models.

### 6.7 Contract details

The contract is locked for this phase and may change in later ones.

- Coordinates are `[longitude, latitude]` everywhere, and out-of-range values raise
  `InvalidRequestError`. Note that a swapped pair inside Ukraine (for example `[50.4, 30.5]`) is
  still a valid coordinate, so it can't be caught. It will just point to the wrong place.
- `geometry.type` and `geo_location.type` are lowercase `"point"` / `"polygon"`. Standard GeoJSON
  writes `"Point"`, so a UI that passes geometry straight to GeoJSON tools has to convert it.
- Polygons use GeoJSON rings: `[[[lon, lat], ...]]`. Each ring has at least 4 positions and ends
  where it starts. A bounding box is a 5-position polygon.
- `radius_m` must be greater than 0, and is allowed for points only.
- Unknown keys in `geo_location` are rejected, so a misspelled key fails loudly instead of being
  ignored.
- Each `chat_history[].response` is validated as an `AgentResponse`, but extra keys inside it are
  ignored, so the UI can store its own fields next to a result it sends back.
- `geo_location` and `chat_history` are accepted and validated, but **not used yet**.

### 6.8 `get_source_text`

The notebook doesn't have this; it's new here. Today a pointer is a `source_doc` value (a
Wikipedia article title). The text lives on graph edges, and the same passage is repeated once
per edge. `get_source_text` returns every distinct passage for that document once, separated by
blank lines, with `document` set to the pointer. An unknown pointer returns `None`.

A pointer-based system (the graph stores a locator, and the text is fetched from the corpus) is
being discussed between the teams. When it lands, it will sit behind the same function, via
`GraphClient.get_source_passages`, so the contract shouldn't change.

### 6.9 Small fixes compared with the notebook

| Notebook behaviour | Now |
|---|---|
| The LLM calls a tool that doesn't exist: `KeyError`, query fails | The LLM gets a message listing the real tools and can recover |
| The LLM passes wrong arguments: validation error, query fails | The LLM gets a message describing the bad arguments |
| The synthesis LLM skips the structured output: crash on `None` | `LLMError` with a clear message |
| The same node id picked twice: duplicate map pins | Each id is used once |
| A node with `lat` but no `lon` would pass | Both are required |
| `search_mentions` checked `hasattr(search_evidence)` | `search_evidence` is part of the `GraphClient` interface |
| A global `llm` object, created once from one key | A client per query, on that query's key |
| `verbose=True` printed traces | Debug logging on the `agent` logger shows the same traces |
| `validate_response` ran after each answer | It became a test of `build_response` |

### 6.10 Errors

Every error the agent raises on purpose is an `AgentError` with a message meant for people, so
the UI can catch that one class and show `str(e)`.

| Exception | When |
|---|---|
| `InvalidRequestError` | An argument to `query()` doesn't match the contract |
| `LLMNotConfiguredError` | No key was given, or OpenRouter rejected it |
| `LLMRateLimitError` | OpenRouter rate limit (common on free models) |
| `LLMError` | OpenRouter failed, or the LLM's answer couldn't be used |
| `AgentError` | The graph file is missing |

Anything else is a bug in our code, and comes through as a normal Python exception.

---

## 7. Known gaps (next phase)

- **`sources` only comes from map locations, and only from some tools.** This is the notebook's
  behaviour, ported as is. If an answer has no `geo_locations`, `sources` is empty even when the
  answer clearly used evidence; the notebook's last test run shows exactly this. `find_entities`
  doesn't record citations at all, so "Where is Kyiv?" also returns no sources. The contract
  says "union across the whole answer". A likely fix: synthesis also returns the source documents
  it relied on, checked against the citation log, the same way node ids are checked.
- **`geo_location` and `chat_history` are not used** (no spatial filter, no follow-up handling).
- **`search_mentions` is substring matching**, so it misses an event described in other words.
- **No retrieval budgeting.** `get_related("Ukraine")` alone returns 122 lines (about 14,600
  words) in one tool result. That can exceed a free model's context window or cause rate-limit
  errors. Most of it is the same passage repeated: only 3,148 of those words are distinct.
- **`kind` is always `"place"` today.** Only LOC nodes have coordinates, and `kind="event"` needs
  event nodes the graph doesn't have yet.
- **Graph data quality** (for the graph team): some LOC nodes aren't places but still have
  coordinates and can show up on the map, for example `.`, `Republic`, `Empire`, `Wikimedia`,
  `IMDb` and `Sheffield Docs`.
