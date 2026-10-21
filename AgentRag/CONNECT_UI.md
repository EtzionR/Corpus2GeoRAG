# Connecting the UI to the GeoRAG agent

For the UI team, and for any AI coding assistant helping you: this file has what you need to call
the agent from `ui/app.py`. Every field is explained in [AgentRag_README.md](AgentRag_README.md).

Please don't edit files inside `AgentRag/`. If something there needs to change, tell the agent
team and we'll change it.

## What changed in this version

The agent now runs on the graph team's new graph (Vr6) and uses the map selection and the chat
history. **Your current integration (`ui/geo_agent.py`) keeps working as is**: the fields it reads
(`answer`, `geo_locations[].geometry.coordinates`, `id`, `label`, `kind`, `sources`) are all still
there, lower-case `"point"` / `"polygon"` are still accepted, and the `agent_turns` you send back as
`chat_history` are exactly the right format.

What's different in the values:

- `sources` are now paragraph pointers like `"TEXT_50333"` (before: article titles).
  `get_source_text()` takes them as before and returns `text` and `document` (the article title),
  plus `section` and `paragraph_index`.
- `kind` is now the place type (`city`, `town`, `village`, `state`, `country`, `road`…), never
  `"event"`.
- A list answer can carry hundreds of places (500 for "places connected to Zelenskyy").
- The first call loads the graph: about 15 s and 1.1 GB of memory, once per app start.
- `ui/geo_agent.py` sets `GRAPH_PATH` to `Graph_n_Geocoding/knowledge_graph.json` if that file
  exists. That's the old graph, now deleted from `main`; if someone still has a local copy, the agent
  would load it and fail. You can remove that block: the agent finds `knowledge_graph.json.gz` by
  itself.

What's new, to use when you're ready: a "Show citations" toggle (section 6) and the other new
fields (section 7).

## 1. Your own OpenRouter key

Create one at https://openrouter.ai/keys. Then either create `AgentRag/.env` (a copy of
`AgentRag/.env.example`) with `OPENROUTER_API_KEY=<your key>`, or pass `api_key=...` to `query()`
(your sidebar key field already does this). Don't create a `.env` inside `ui/`: `ui/.gitignore`
doesn't ignore it. Never write the key into a `.py` file.

## 2. Install

Into the environment Streamlit runs in (for `run_app.bat` that's `ui/.venv`), from the repo root:

```bash
pip install -r AgentRag/requirements.txt
```

## 3. Import and call

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "AgentRag"))
from georag_agent import AgentError, get_source_text, query

try:
    result = query(text_prompt, geo_location=geo_location, chat_history=agent_turns, api_key=key)
except AgentError as e:
    st.error(str(e))     # every agent error has a message you can show as is
```

`text_prompt` is required. For a map selection with no typed question, any default text works
("What is in this area?"); the agent reads the area from `geo_location`.

## 4. Coordinates: the agent uses [lon, lat], Folium markers use [lat, lng]

```python
# selected point (lat, lng) -> agent; radius_m is optional (default 1 km; "within 500 m" in the question wins)
lat, lng = st.session_state.selected_points[0]
geo_location = {"type": "Point", "coordinates": [lng, lat], "radius_m": 1000}

# bounding box ((min_lat, min_lng), (max_lat, max_lng)) -> agent polygon
(s, w), (n, e) = st.session_state.bounding_box
geo_location = {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}

# agent place -> Folium marker
lon, lat = place["geometry"]["coordinates"]
folium.Marker([lat, lon], tooltip=f'{place["number"]}. {place["label"]}').add_to(m)
```

Outlines (`place["shape"]`) are GeoJSON, which is already [lon, lat]: give them to `folium.GeoJson`
as they are, no swapping.

## 5. Follow-ups

Keep sending previous results back as `chat_history` (`[{"query": ..., "response": <result>}]`), as
you do now. Then "tell me about number 13" means place 13 of the previous result, including places
on the map that the answer didn't mention. Showing each pin's number makes this usable.

## 6. Citations: a "Show citations" toggle

Every answer comes in two versions:

```python
result["answer"]        # "Zelenskyy is the President of Ukraine [1, S4, S13]. ..."
result["answer_plain"]  # "Zelenskyy is the President of Ukraine. ..."   (same text, no marks)
```

Please add a **Show citations** toggle (on by default): on shows `answer`, off shows
`answer_plain`. The marks say where each statement comes from:

- `[3]`: place 3 on the map (pin number 3).
- `[S2]`: a passage from the corpus. Find `id == "S2"` in `result["citations"]`; its `pointer` goes
  to `get_source_text(pointer)`, which returns the paragraph (`spans` are the names' positions in it,
  for highlighting).
- `[L1]`: the same, for the opening summary of a Wikipedia article.

The agent checks every mark before returning the answer: each points at a real pin or paragraph,
with at most two passages per statement. A short text you can show users next to the toggle:

> Numbers in brackets show where each statement comes from: [3] is pin 3 on the map; [S2] and [L1]
> are paragraphs from the source articles. Click one to read it.

Making the marks clickable is a nice extra: `[3]` highlights pin 3, `[S2]` opens the paragraph.

## 7. New in the result (optional)

```python
result["status"]      # "answered" | "no_data" | "out_of_scope" | "llm_failed"
result["grounded"]    # False: nothing in the graph; the answer starts with
                      # "No data from the graph — answer from the LLM only." Worth a visible badge.
result["shape"]       # "list" | "fact" | "drilldown" | "explain"

for place in result["geo_locations"]:   # every place found, strongest first
    place["number"]   # the [n] in the answer
    place["role"]     # "primary" (the answer discusses it) or "context" (map only)
    place["shape"]    # outline, only on primary places (at most 10 per answer, <= 300 points each)
    place["why"]      # one line, e.g. "ATTACKED in 12 records; 118 matching paragraphs"
    place["uncertain"]  # present when the point may be wrong: show it greyed or with a "?"

result["regions"]     # lists only: [{"id": "Ukraine", "count": 50, "places": [...], "children": [...]}]
result["citations"]   # one per [S2] / [L1] in the answer: {"id", "pointer", "article", "section", "spans"}
result["map"]         # {"bbox": [west, south, east, north], "highlight": [numbers]}
result["follow_ups"]  # up to 3 suggested questions, ready to send as typed
result["did_you_mean"]  # other entries the question's names could mean
```

Suggestions, all optional:

- **Many places:** draw primary places as big highlighted markers (plus their outlines) and context
  places small, inside a `folium.plugins.MarkerCluster`. Clustering also untangles places that sit
  on the same spot (Washington, the White House and the Oval Office).
- **Zoom:** `m.fit_bounds([[s, w], [n, e]])` with `w, s, e, n = result["map"]["bbox"]`.
- **Outline:** `folium.GeoJson({"type": "Feature", "geometry": place["shape"], "properties": {}})`.
- **Doubtful points:** `place["uncertain"]` says why the graph's point may be wrong ("geocoded as a
  river, but its own article describes a city or town"). Show those pins greyed or with a "?".
- **Regions:** show `result["regions"]` as an expandable tree ("Ukraine 50 → Donetsk 36 …"); the
  numbers in `places` match the pins.
- **Follow-ups:** buttons that send the text as a new question.

## 8. Good to know

- With the model we tested on (Gemini 2.5 Flash), a question takes 1–6 s. The app's default is a
  free model: slower, rate-limited, and answers vary a little.
- A rate limit or network failure doesn't raise: you get `status: "llm_failed"` (or a short
  template answer for lists) with the places still filled in. Retrying usually works.
- Errors that do raise are all `AgentError`: `InvalidRequestError` (bad argument),
  `LLMNotConfiguredError` (missing or rejected key), or a missing graph file.
- After a `git pull` that updates the graph, restart the app.
