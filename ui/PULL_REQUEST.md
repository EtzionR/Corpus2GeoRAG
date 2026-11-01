# Pull Request: AgentRag MVP Integration, UI_TEAM_NOTES Fixes, In-App API Key Persistence, Zero-Latency HUD & Tactical Map Design

## 📋 Overview
This pull request updates the interactive Streamlit frontend (`ui/`) to integrate the **AgentRag MVP release** (`AgentRag/UI_TEAM_NOTES.md` and `AgentRag/CONNECT_UI.md`), synchronizes with the one-click `RUN_GEORAG.bat` (`AgentRag/launch.py`) workflow, and delivers major UI/UX, visual tactical styling, and zero-latency performance upgrades across the map and chat workspace.

All UI improvements and backend contract adaptations remain 100% strictly confined to the `ui/` directory in compliance with team architecture rules, making `ui/` fully ready for the team to deprecate or remove `AgentRag/ui_mvp/` whenever desired.

All **98 automated unit tests** in `ui/test_app.py` pass cleanly.

---

## 🚀 Details of All Additions

### 1. `AgentRag/UI_TEAM_NOTES.md` Fixes (Items 1–8)
| Note | Requirement (`AgentRag/UI_TEAM_NOTES.md`) | Implementation in `ui/` |
| :--- | :--- | :--- |
| **1. `pandas<3` for Windows Smart App Control** | `pandas 3.0.2` has an unsigned `.dll` blocked by Windows 11 Smart App Control on fresh PCs. | Pinned `pandas>=2.0.0,<3` in `ui/requirements.txt`. |
| **2. Viewport Fit on Laptop Screens (125%–150% Scaling)** | Previous fixed heights caused a vertical page scrollbar and clipped the chat input bar on 14"–15" laptops. | Added dynamic viewport auto-fit CSS/JS (`calc(100dvh - ...)`), reduced chat wrapper `min-height` to `260px`, and tightened vertical padding so the map, chat log, and chat input fit on one screen without page scrolling. |
| **3. Replace Map Pins per Answer by Default** | Old pins from previous turns remained on the map and blended with the new answer's pins. | `st.session_state.map_layers` now **replaces** previous answer pins on each new query by default (`list(agent_resp.layers)`). Added a **"Keep previous answers' pins on map"** toggle (`keep_previous_layers`, default `False`) in the sidebar Operations panel for users who want cumulative pins. |
| **4. Clean `st_folium` Layer Diffing** | Mutating `MapLayer` objects in place could leave stale client-side markers in `st_folium`. | Every query constructs fresh `MapLayer` instances and replaces `st.session_state.map_layers` cleanly when `keep_previous_layers` is off. |
| **5. Reliable Map-to-Chat Coordinate Selection** | Clicking the map or a pin should reliably populate the spatial selection and allow asking about that location. | Implemented an instant client-side Tactical HUD inside the map canvas plus top-of-script `st_folium` state ingestion (`_pre_map_state`) that captures both **Point** (`lat, lon`) and **Bounding Box (BBox)** selections before rendering the sidebar and chat input. |
| **6. Collapsible Welcome Message** | The initial onboarding guide took up most of the chat area once a conversation started. | Wrapped the initial assistant welcome message (`m_idx == 0`) inside `st.expander("👋 Welcome: how to use the map and the chat", expanded=len(st.session_state.messages) == 1)` so it starts open on launch and automatically collapses after the first question. |
| **7. Scroll to Top of New Answer** | Auto-scrolling to the bottom of a long answer hid the headline answer and forced users to scroll up to read from the beginning. | Set `autoscroll=False` on the chat message container (`_chat_container_kwargs`) and injected a smooth `scrollIntoView({ behavior: "smooth", block: "start" })` hook (`scroll_to_answer`) that scrolls to the **top** of the newly arrived assistant message. |
| **8. Explicit Mock Mode Indicator & `AgentRag/` Discovery** | Users without an API key saw mock answers (e.g., Donetsk/Avdiivka) without realizing the live agent was not running. | Added `_current_dir.parent` (`<repo_root>/AgentRag`) to `_potential_agent_dirs` in `ui/geo_agent.py`. When running in mock mode, answers are badged `[MOCK]` and display an explicit warning banner: `⚠️ Example answer: no OpenRouter key set (Deterministic Mock Engine)`. |

---

### 2. Full `AgentRag` MVP Contract Support (`AgentRag/CONNECT_UI.md`)
- **Hierarchical `regions` (`list[RegionNode]` & legacy `dict` support)**:
  - Updated `AgentResponse.regions` and `query_geo_agent()` in `ui/geo_agent.py` to preserve the new MVP hierarchical list format (`[{"name": "Donetsk Oblast", "count": 42, "children": [{"name": "Bakhmut Raion", "count": 12}]}]`) while maintaining backward compatibility with flat `{region: count}` dicts.
  - Updated the `🌍 Regional Distribution` expander in `ui/app.py` to render parent regions and indented child sub-regions (`↳ Child: count`).
- **Map Cap Metadata (`map.showing` & `map.not_shown`)**:
  - Hydrated `map_showing: str` and `map_not_shown: int` on `AgentResponse` and persisted them onto assistant chat messages.
  - When a broad query exceeds the map pin cap (`map_not_shown > 0`), displays an informative caption beneath the answer (`📍 Showing N places on map (M additional places omitted for map clarity — see Regional Distribution above)`).
- **Status Badges (`status` & `grounded`)**:
  - Added role header badges for all MVP status codes: `[LIVE RAG]`, `[LLM ONLY]`, `[NO DATA]`, `[OUT OF SCOPE]`, `[LLM FAILED]`, and `[MOCK]`.
- **Structured `did_you_mean` (`list[Alternative]` & `str`)**:
  - Supports both plain string suggestions and structured `list[Alternative]` dicts (`{"name": ..., "oblast": ..., "type": ...}`) in the `💡 Did you mean:` alert.
- **Numbered Primary Pins (`[1]`, `[2]`), Context Clustering (`MarkerCluster`), Uncertain Pins (`?`), GeoJSON Boundaries (`place["shape"]`), Citations (`[S1]`, `[L1]`, span highlighting), and Follow-Up Buttons (`follow_ups`)**:
  - Full hydration and rendering across `ui/geo_agent.py` and `ui/app.py`.

---

### 3. In-App OpenRouter API Key Management & `RUN_GEORAG.bat` (`.env`) Persistence
- **Two-Way Sync with `AgentRag/.env`**:
  - Added `get_agent_env_path()` and `persist_openrouter_api_key(api_key)` in `ui/geo_agent.py`.
  - When launched via `RUN_GEORAG.bat`, `AgentRag/launch.py` saves the key to `AgentRag/.env` and passes `OPENROUTER_API_KEY` in the environment. The sidebar **OpenRouter API Key** input automatically pre-populates from `os.environ["OPENROUTER_API_KEY"]`.
  - Changing the API key in the Streamlit sidebar updates `os.environ["OPENROUTER_API_KEY"]` in real time **and** writes the updated key directly to `AgentRag/.env` so future `RUN_GEORAG.bat` launches use the new key automatically.
  - Clearing the API key in the sidebar removes `OPENROUTER_API_KEY` from both `os.environ` and `AgentRag/.env` and passes `force_mock=True` so the app immediately switches to the deterministic mock engine instead of silently reusing a cached key from disk.

---

### 4. New Tactical Map Design, Symbology & Animated Visual HUD
- **Custom Tactical Pin Symbology (`make_pin_icon`)**:
  - **Diamond vs. Teardrop Shape Toggle**: Operators can toggle between tactical angled diamonds (`geoai-diamond`) and modern teardrops (`geoai-teardrop`) via pure CSS `DivIcon` factories.
  - **Numbered SVG Badges (`[1]`, `[2]`, ...)**: Primary focal places render high-contrast SVG badges directly inside the pin body, creating a 1:1 visual link between assistant citations and map markers.
  - **Specialized Kind Symbology**:
    - **Events (`!`)**: Crimson red pin with high-visibility event exclamation glyph.
    - **Uncertain Pins (`?`)**: Amber/orange pins with dashed border styling and a cautionary badge (`geoai-badge-unc`) for ambiguous geocodings.
    - **Context Dots**: Slate cadetblue minimalist pins clustered into `MarkerCluster`.
  - **Active Target Reticle**: Single-point map clicks display an electric cyan tactical reticle with concentric crosshairs and spinning rings.
- **Pulse Moving Bar & Sweeping Radar Scanline Animation**:
  - **Active Sector Radar Scanline (`geoai-scan-svg` / `geoai-scan-line`)**: When a query or reconnaissance scan is executing over a bounding box, a glowing horizontal laser/scan line continuously sweeps up and down across the sector bounds.
  - **Target Reticle Pulsing (`geoai-reticle--querying`)**: Active point queries pulse the target reticle with an expanding wave ring (`geoai-reticle__pulse`), giving clear visual feedback during LLM generation.
  - **Client-Side Animation Control**: Triggered via `startQueryingAnimation()` and `stopQueryingAnimation()` hooks with zero Python round-trips.
- **Bounding Box Corner Brackets & Answered BBox Transparency**:
  - **Exact Vertex Corner Brackets**: Animated L-brackets (`geoai-corner--nw`, `ne`, `se`, `sw`) anchored to exact SVG pixel coordinates at the corners of active search sectors.
  - **Answered BBox Dimming**: Answered bounding boxes automatically fade to ultra-transparent (`fillOpacity: 0.03`, faint dashed stroke, `interactive: False`), retaining spatial context without obscuring pins.
- **Dark-Glass Popup Cards (`_popup_card`)**:
  - Replaced standard generic Leaflet popups with themed dark-glass HUD cards featuring electric cyan accents, telemetry badges (`LAT`, `LON`, `ROLE`), evidence summaries, and hyperlinked citation titles.

---

### 5. Tactical Map Canvas HUD, Spatial Selection & Zero-Latency Performance
- **0ms Map Pan/Zoom & Popup Interaction (`AGENTS.md` Rule 1.1)**:
  - Constrained `st_folium()` to `returned_objects=["last_clicked", "last_active_drawing", "all_drawings"]` with `return_on_hover=False`, ensuring pan, zoom, and popup inspection execute 100% client-side with zero Python reruns.
- **In-Map Tactical HUD & Instant Selection Bridge**:
  - Embedded a floating Tactical HUD directly inside the Leaflet canvas displaying active Point (`LAT, LON`) or Bounding Box (`AOI BBOX`) coordinates, with instant **Recon Scan** and **Clear (`×`)** actions.
  - Preserves BBox and Point spatial selections across chat query submission and map interactions.
- **Cluster Pin Deduplication & Debounced Pin Filter Control**:
  - Fixed duplicate pin rendering inside `MarkerCluster` and debounced `PinFilterControl` DOM updates (`Primary`, `Context`, `Uncertain`) to 200ms for instant client-side filtering.
- **Single-Rerun Inverted Execution Pipeline**:
  - Processes map clicks and drawing payloads before sidebar and chat rendering, eliminating cascading `st.rerun()` loops and cold-start iframe remounts.
- **Background Knowledge Graph Pre-Warming & `@functools.lru_cache(maxsize=4096)`**:
  - Pre-warms `knowledge_graph.json.gz` in a background daemon thread and caches paragraph lookups (`get_source_text`) for sub-microsecond source inspection.

---

## 🧪 Automated Testing
Run the test suite from `ui/`:
```bash
pytest test_app.py -v
```
**Results:** `98 passed in 32.72s`
- `TestTacticalHudSymbologyAndAnsweredBbox`: Validates color token semantic resolution, answered BBox transparency, diamond vs. teardrop pin variants, numbered SVG badges, dark-glass popup card HTML, corner bracket vertex anchors, and querying scanline/pulse animation hooks.
- `TestOption1MapCanvasTacticalHudAndStableLayout`: Verifies in-map HUD rendering, reconnaissance scan dispatch, BBox preservation during chat queries, and glowing reticle switching.
- `TestAgentRagMvpContractAndApiKeyPersistence`: Verifies `list[RegionNode]` & `dict` region hydration, `map.showing` / `map.not_shown` extraction, `persist_openrouter_api_key()` writing/clearing in `AgentRag/.env`, `pandas<3` constraint, `autoscroll=False`, collapsible welcome message, and default pin replacement (`keep_previous_layers`).
- `TestDuplicateClusterPinPrevention` & `TestZeroRerunPerformanceVerification`: Verifies zero duplicate markers in `MarkerCluster` and strict single-pass execution without cascading reruns.
- Full coverage of dataclasses, multimodal spatial routing (point, bbox, text, combined), citation span highlighting, GeoJSON boundary layers, and `AGENTS.md` architectural rules.
