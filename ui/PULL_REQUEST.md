# Pull Request: Complete Vr6 AgentRag Integration & Zero-Latency Performance Optimizations

## 📋 Overview
This pull request connects the interactive Streamlit frontend (`ui/`) to the **Vr6 Phase 2 AgentRag backend**, implementing the full specifications outlined in [`AgentRag/CONNECT_UI.md`](../AgentRag/CONNECT_UI.md). 

In addition to hydrating and rendering all new Vr6 data fields (numbered places, boundaries, citations, span highlighting, regional breakdowns, and follow-ups), this PR incorporates critical performance optimizations that eliminate screen dimming, layout jumping, and server round-trips during map interactions.

All **55 automated unit tests** in `ui/test_app.py` pass cleanly.

---

## 🔗 Direct Connection to AgentRag Backend Additions

The table below details how every new field and recommendation from `AgentRag/CONNECT_UI.md` is connected to the frontend interface:

| AgentRag Backend Addition (`AgentRag/CONNECT_UI.md`) | Frontend Implementation in `ui/app.py` & `ui/geo_agent.py` | Operational Impact / User Experience |
| :--- | :--- | :--- |
| **`citations` & `pointer` (`[S2]`, `[L1]`, `TEXT_XXXXX`)** | - Hydrated in `geo_agent.py`<br>- Document & section titles resolved via cached `get_source_text()`<br>- Character `spans` wrapped using `_highlight_text_spans()` | Inspected source citations display the human-readable article title and section name, with referenced text passages highlighted via styled `<mark>` tags. |
| **`answer` vs. `answer_plain`** | - Added **"Show citations"** toggle in sidebar (on by default)<br>- Dynamically toggles between `answer` (with `[1]`, `[S2]`) and `answer_plain` | Operators can switch between fully grounded military/academic citations and clean conversational prose. |
| **`place["shape"]` (GeoJSON Polygons)** | - Converted into `MapLayer(layer_type="geojson")`<br>- Rendered via `folium.GeoJson` with electric cyan border & subtle fill | Primary tactical places (e.g. oblasts, districts, sectors) display their exact administrative and tactical boundaries directly on the map. |
| **`place["role"]` (`"primary"` vs `"context"`)** | - Primary places rendered as distinct, prominent blue pins<br>- Context places rendered as slate cadetblue pins clustered via `folium.plugins.MarkerCluster` | Solves browser DOM choke when queries return 100–500 places (e.g. "places connected to Zelenskyy"). Clusters automatically untangle co-located coordinates. |
| **`place["uncertain"]`** | - Flagged as orange `(?)` markers with cautionary popups<br>- Filterable via bottom-right Leaflet `PinFilterControl` | Distinguishes doubtful geocodings (e.g., roads geocoded where rivers were meant) with 0ms client-side visibility toggling. |
| **`result["map"]["bbox"]`** | - Extracted as `[west, south, east, north]`<br>- Applied via `m.fit_bounds([[south, west], [north, east]], padding=(30, 30))` | The tactical map automatically auto-zooms and frames the query's area of operations upon response arrival. |
| **`result["follow_ups"]`** | - Rendered as interactive buttons (`🔍 {question}`) directly beneath assistant answers | Operators can click any suggested follow-up question to execute it immediately as a subsequent conversational turn. |
| **`result["did_you_mean"]`** | - Rendered as an alert notice (`💡 Did you mean: Bakhmut?`) | Offers alternative suggestions when the operator's query involves ambiguous or misspelled place names. |
| **`result["regions"]`** | - Rendered inside a collapsible `🌍 Regional Distribution` expander | Displays region-by-region counts for broad queries spanning multiple oblasts. |
| **`result["status"]` & `result["grounded"]`** | - Role badge tag updated (`• [LIVE RAG]` / `• [LLM ONLY]`)<br>- Telemetry logged in RAG debug modal | Visual indicator alerts the operator if an answer lacks grounding in the knowledge graph. |
| **Knowledge Graph text lookups (`get_source_text()`)** | - Wrapped with `@functools.lru_cache(maxsize=4096)` | Repeated lookups for passage text, document names, and section titles take sub-microsecond time instead of disk/gzip queries. |

---

## ⚡ Frontend Zero-Latency & Stability Guidelines (`AGENTS.md`)
To address previous app slowness and vertical screen dimming/jumping:
1. **0ms Map Pan/Zoom (Rule 1.1)**: Constrained `st_folium()` using `returned_objects=["last_clicked", "last_active_drawing", "all_drawings"]`. Panning, zooming, and opening popups execute 100% on the client side with **0 Python reruns**.
2. **Double-Rerun Elimination (Section 2b)**: Ingests `geoai_tactical_map` state at the top of the script before sidebar and chat render, updating UI state in **1 single rerun** instead of cascading a second `st.rerun()`.
3. **Debounced Pin Filter Event Loops**: In `MapTrashBinHook`, debounced `refreshPinCounts` to 200 ms, collapsing thousands of $N^2$ Leaflet DOM event loop iterations into a single update.
4. **Widget ID Explosion Protection (Rule 3.2)**: Optimized sidebar layer manager for $> 10$ layers using bulk summaries, quick clear actions, and a selectbox instead of hundreds of individual `st.button` widgets.
5. **Knowledge Graph Background Pre-warming**: Pre-warms `knowledge_graph.json.gz` (1.1 GB) in a background daemon thread upon import, eliminating the 13.7s freeze on user queries.
6. **Source Metadata Negative-Lookup Caching**: Prevents repeated lookups on future reruns for missing or invalid pointer citations.
7. **Stable Chat Heights (Rule 3.1)**: Container height is fixed at `465px`, eliminating the 45px vertical screen bounce when spatial selections change.
8. **Process-Guarded Bootstrap (Rule 2.1)**: Package verification runs once per process; removed unconditional `importlib.reload(geo_agent)`.

---

## 🧪 Automated Testing
Run the test suite from `ui/`:
```bash
pytest test_app.py -v
```
**Results:** `55 passed in 12.73s`
- Dataclass and contract serialization tests.
- Multimodal routing tests (point-only, bbox-only, text-only, multimodal).
- Vr6 numbered pin mapping, citation passthrough, and span highlighting tests.
- GeoJSON boundary layer generation and bbox auto-fit tests.
- `AGENTS.md` static rule compliance verification tests.
