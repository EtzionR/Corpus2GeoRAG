# 🌍 GeoAI Defense C2 - Spatial Intelligence Frontend & Vr6 RAG Interface

An interactive, high-performance Streamlit frontend and multi-modal RAG routing interface built for the **GeoAI Tactical Intelligence System**.

The application synchronizes an interactive **Folium map centered over Ukraine** with an **LLM operator console**, connecting directly to the **Vr6 Phase 2 AgentRag backend** (knowledge graph, geocoding, boundary extraction, citation grounding, and automated reconnaissance).

---

## 🚀 Quick Start for Team Members

The frontend environment is **completely self-bootstrapping**. It automatically verifies packages, installs missing dependencies, and discovers the local `AgentRag/` backend.

### Option 1: One-Click Windows Launcher (Recommended)
Double-click the batch file inside the `ui/` folder:
```text
run_app.bat
```
*This automatically checks Python, verifies packages, launches Streamlit, and opens the app in your browser.*

### Option 2: Linux / macOS Launcher
```bash
cd ui
chmod +x run_app.sh
./run_app.sh
```

### Option 3: Manual Command Line Execution
```bash
# From repository root or ui/ directory:
cd ui

# 1. Activate your virtual environment (e.g., Python 3.10 - 3.14)
# On Windows:
.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate

# 2. Install dependencies (UI + AgentRag requirements)
pip install -r requirements.txt
pip install -r ../AgentRag/requirements.txt

# 3. Launch the Streamlit application
streamlit run app.py
```
*(Alternatively, direct execution via `python app.py` will automatically forward execution to the Streamlit runtime).*

---

## 🔑 Connecting to the Live Vr6 AgentRag Backend

The UI operates in two seamless modes:
1. **🟢 Live GeoRAG Agent**: Queries the Vr6 knowledge graph and live LLM pipeline via LangChain / OpenRouter.
2. **🟡 Offline Simulation (Mock Engine)**: Operates 100% offline with zero API keys or external network calls, returning deterministic tactical scenarios for UI testing and demos.

### Providing your OpenRouter API Key
To activate the live agent, provide your key (format `sk-or-v1-...` from [openrouter.ai/keys](https://openrouter.ai/keys)) through any of these three methods:
1. **Directly in App Sidebar**: Paste your key into the **"OpenRouter API Key"** password field in the left sidebar.
2. **Via `AgentRag/.env` file**: Create `AgentRag/.env` containing:
   ```env
   OPENROUTER_API_KEY=sk-or-v1-your-key-here
   ```
3. **Via Streamlit Secrets**: Add `OPENROUTER_API_KEY = "..."` into `ui/.streamlit/secrets.toml`.

---

## 🏛️ Architecture & File Structure

```
ui/
├── app.py              # Main Streamlit frontend (Chat, Folium map, Leaflet HUD, layer management)
├── geo_agent.py        # Backend adapter routing between Live AgentRag and Mock Engine
├── test_app.py         # 55 automated pytest unit tests validating contracts, Vr6, and performance
├── AGENTS.md           # Mandatory frontend & Streamlit performance rules (zero-latency guidelines)
├── PULL_REQUEST.md     # Full Pull Request specification detailing connection to AgentRag
├── requirements.txt    # Frontend dependencies specification
├── run_app.bat         # Automated one-click Windows launcher
├── run_tests.bat       # Automated one-click Windows test runner
├── run_app.sh          # Automated Unix/macOS launcher
├── .gitignore          # Git exclusion rules for Python, virtual environments, and caches
└── README.md           # This document
```

---

## 🌟 Core Functionality & Vr6 Feature Breakdown

### 1. Zero-Latency Client-Side Map (Leaflet & Folium)
- **0ms Client-Side Pan & Zoom**: Panning, zooming, and opening marker popups execute 100% on the client side without triggering Python script reruns or dimming the screen (`returned_objects` constraint).
- **Background Pin Clustering (`MarkerCluster`)**: When queries return dense context lists (50–500 places), context places (`role == "context"`) are clustered to prevent browser DOM choke, while primary places (`role == "primary"`) remain standalone prominent pins.
- **Client-Side Pin Filter Controls**: A bottom-right Leaflet control allows operators to toggle visibility of Context pins and Uncertain pins with 0ms delay.
- **Auto-Zoom to Operational Area (`map_bbox`)**: The map automatically calculates and applies `m.fit_bounds()` to frame the operational scope returned by the agent.
- **GeoJSON Boundary Outlines**: When places include boundary polygons (`place["shape"]`), the frontend renders semi-transparent tactical sector outlines (`folium.GeoJson`).
- **Basemap HUD Switcher**: CartoDB Voyager Dark (tactical dark navigation), CartoDB Dark Matter, Esri Dark Gray Canvas, High-Resolution Satellite Imagery, Topographic, and OSM.

### 2. Multi-Modal Spatial Targeting
- **Map Click Target Selection**: Clicking the map selects coordinate targets without triggering immediate backend queries.
- **Area-of-Interest (AOI) Bounding Box Suite**: Draw tactical rectangles using the map toolbar to define spatial envelopes `(lower-left, upper-right)` in GeoJSON `[lon, lat]` order.
- **Reconnaissance Scans**: Click the **🔍 Recon Scan** button (in sidebar or docked chat pill) to run instant multi-modal reconnaissance over points or bounding boxes without typing a question.
- **One-Click Deletion**: Integrated trash bin controls on both the map toolbar and chat docked pill to clear selections instantly.

### 3. Operator Intel Console & Grounded Sources
- **Show Citations Toggle**: Toggle between verified grounding marks (`result["answer"]` with `[1]`, `[S2]`) and clean conversational prose (`result["answer_plain"]`).
- **Verified Source Drawer**: Resolves `TEXT_XXXXX` paragraph pointers into human-readable document titles and section names from the knowledge graph.
- **Character Span Highlighting**: Inspected source passages highlight verbatim entity and concept mentions in styled `<mark>` tags using `citation["spans"]`.
- **Interactive Follow-Up Buttons**: Up to 3 suggested questions (`result["follow_ups"]`) are rendered as clickable buttons (`🔍 {q}`) below assistant answers.
- **Regional Distribution Expander**: Displays region-by-region counts (`result["regions"]`) for broad queries spanning multiple oblasts.
- **Did-You-Mean Notices**: Displays alternative suggestions (`result["did_you_mean"]`) when queries involve ambiguous place names.
- **RAG Telemetry & Debug Dialog**: Click **📋 RAG Debug Logs** in the sidebar to inspect raw JSON request and response payloads, round-trip latency (ms), and grounding evidence.

---

## ⚡ Streamlit Performance Guidelines (`AGENTS.md`)

To keep the application fast, responsive, and free from visual jumping, all agents and developers must adhere to the rules in [`AGENTS.md`](AGENTS.md):
1. **Never allow map pan/zoom to trigger Python reruns**: Always constrain `returned_objects=["last_clicked", "last_active_drawing", "all_drawings"]` in `st_folium()`.
2. **No unconditional module reloads or dependency scans**: Wrap bootstrap checks with `_BOOTSTRAP_DONE` once per process; do not call `importlib.reload(geo_agent)`.
3. **In-memory LRU caching for knowledge graph text**: Wrap `get_source_text()` with `@functools.lru_cache(maxsize=4096)`.
4. **Stable layout container heights**: Keep `chat_container_height = 465` constant to prevent the chat scroll area and input box from bouncing vertically.
5. **Cluster background context pins**: Primary places remain individual pins; context places use `folium.plugins.MarkerCluster`.

---

## 🧪 Automated Testing (`pytest`)

To run the full suite of **55 automated unit tests**:

```bash
# From ui/ directory:
python -m pytest test_app.py -v

# Or double-click (Windows):
run_tests.bat
```

### Test Suite Coverage (55 Tests Passing)
- **Data Contracts**: Validates `MapLayer` and `AgentResponse` typing, defaults, and serialization.
- **Multimodal Routing Scenarios**: Scenario A (text + point), Scenario B (point-only reconnaissance), Scenario C (general text), and Bounding Box AOI scenarios.
- **Vr6 Data Ingestion**: Numbered pin ordering, citation passthrough, document title resolution, and paragraph metadata.
- **Upgrades 1–6 Verification**:
  - `test_highlight_text_spans_basic_and_overlapping`: Character offset interval merging and `<mark>` generation.
  - `test_highlight_text_spans_dict_format`: Handles `{'start': s, 'end': e}` span dictionaries.
  - `test_build_assistant_message_vr6_fields`: Preserves `follow_ups`, `regions`, `did_you_mean`, and `map_bbox`.
  - `test_geojson_boundary_layer_generation`: Verifies hydration of GeoJSON polygons from backend `shape`.
  - `test_auto_zoom_map_bbox_extracted_and_fit`: Validates `map_bbox` extraction and `m.fit_bounds()` integration.
- **Performance Rule Enforcement**: Static codebase verification ensuring all rules in `AGENTS.md` are actively enforced.
