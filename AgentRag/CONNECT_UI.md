# Connecting the UI to the GeoRAG agent

For the UI team, and for any AI coding assistant helping you: this file has everything needed to
call the agent from `ui/app.py`. Full details are in [AgentRag_README.md](AgentRag_README.md).

Please don't edit files inside `AgentRag/`. If something there needs to change, tell the agent
owner and we'll change it.

## 1. Get your own OpenRouter key

Create one at https://openrouter.ai/keys. It's free, and the agent only uses free models for now.

## 2. Give the agent your key

Pick one:

- **Simplest:** create the file `AgentRag/.env` (copy `AgentRag/.env.example`) containing
  `OPENROUTER_API_KEY=<your key>`. `AgentRag/.gitignore` already keeps it out of git.
- **From the UI:** pass `api_key=...` to `query()`, for example from a key field in the sidebar,
  or from `ui/.streamlit/secrets.toml` via `st.secrets` (already in `ui/.gitignore`).

Don't create a `.env` inside `ui/`: `ui/.gitignore` doesn't ignore `.env`, so the key would be
committed. And never write the key into a `.py` file.

## 3. Install the agent's requirements

Into the same environment Streamlit runs in (for `run_app.bat` that's `ui/.venv`), from the
repo root:

```bash
pip install -r AgentRag/requirements.txt
```

## 4. Import and call

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "AgentRag"))
from georag_agent import AgentError, get_source_text, query

try:
    result = query(text_prompt, geo_location=geo_location, chat_history=history)
except AgentError as e:
    st.error(str(e))     # every agent error has a message you can show as is
```

`text_prompt` is required. For a map selection with no typed question ("Run Reconnaissance"),
send a default text such as `"What is at this location?"`.

## 5. Coordinates: the agent uses [lon, lat], Folium uses [lat, lng]

Swap the order in both directions:

```python
# selected point (lat, lng) -> agent
lat, lng = st.session_state.selected_points[0]
geo_location = {"type": "point", "coordinates": [lng, lat], "radius_m": 500}

# bounding box from to_bounding_box(): ((min_lat, min_lng), (max_lat, max_lng)) -> agent polygon
(s, w), (n, e) = st.session_state.bounding_box
geo_location = {"type": "polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}

# agent result -> Folium marker
for loc in result["geo_locations"]:
    lon, lat = loc["geometry"]["coordinates"]
    folium.Marker([lat, lon], tooltip=loc["label"]).add_to(m)
```

## 6. What comes back

```python
{
  "answer": "According to the corpus, ...",
  "geo_locations": [
    {"id": "Kyiv", "label": "Kyiv", "kind": "place",          # kind: "place" or "event"
     "geometry": {"type": "point", "coordinates": [30.52, 50.45]},
     "sources": ["2014 pro-Russian unrest in Ukraine"]}
  ],
  "sources": ["2014 pro-Russian unrest in Ukraine"]           # all sources for the answer
}
```

- **Showing a source:** `get_source_text(pointer)` with any value from `sources` returns
  `{"text": ..., "document": ...}`, or `None` if it's unknown. No LLM call, so it's instant.
- **Chat history:** the agent expects `[{"query": <question>, "response": <result dict>}, ...]`,
  not chat messages. Keep each result dict exactly as `query()` returned it.

## 7. Good to know (POC)

- A query takes a few seconds (about 8 s in testing). The first call also loads the graph.
- `geo_location` and `chat_history` are accepted and checked, but the agent doesn't use them yet,
  so answers don't depend on the map selection for now.
- `sources` can be empty, and `kind` is always `"place"` for now.
- Free models are rate-limited. On `LLMRateLimitError`, wait a bit and retry.
- The error types, if you want to handle one differently: `InvalidRequestError` (bad argument),
  `LLMNotConfiguredError` (missing or rejected key), `LLMRateLimitError`, `LLMError` (retry).
  All of them are an `AgentError`.
