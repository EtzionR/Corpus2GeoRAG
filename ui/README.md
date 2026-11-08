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
├── app.py                   # Main Streamlit frontend (Chat, Folium map, Leaflet HUD, layer management)
├── geo_agent.py             # Backend adapter routing between Live AgentRag and Mock Engine
├── test_app.py              # 140 automated unit, AST invariant, state-loop & latency benchmark tests
├── conftest.py              # Pytest fixtures for micro-benchmarks, high-load RAG payloads & state simulation
├── verify_quality_gate.py   # Automated DoD enforcer (file-to-test pairing, AST audit & pytest runner)
├── .githooks/pre-commit     # Git pre-commit hook blocking untested code or latency regressions
├── AGENTS.md                # Mandatory frontend & Streamlit performance rules + Definition of Done
├── PULL_REQUEST.md          # Full Pull Request specification detailing connection to AgentRag
├── requirements.txt         # Frontend dependencies specification
├── run_app.bat              # Automated one-click Windows launcher
├── run_tests.bat            # Automated Windows unit & performance quality gate runner
├── run_tests.sh             # Automated POSIX unit & performance quality gate runner
├── run_app.sh               # Automated Unix/macOS launcher
├── .gitignore               # Git exclusion rules for Python, virtual environments, and caches
└── README.md                # This document
```

---

## 🌟 Core Functionality & Vr6 Feature Breakdown

### 1. Zero-Latency Client-Side Map (Leaflet & Folium)
- **0ms Client-Side Pan & Zoom**: Panning, zooming, and opening marker popups execute 100% on the client side without triggering Python script reruns or dimming the screen (`returned_objects` constraint).
- **Background Pin Clustering (`MarkerCluster`)**: When queries return dense context lists (50–500 places), context places (`role == "context"`) are clustered to prevent browser DOM choke, while primary places (`role == "primary"`) remain standalone prominent pins.
- **Client-Side Pin Filter Controls**: A bottom-right Leaflet control allows operators to toggle visibility of Primary, Context, and Uncertain pins and switch pin shapes (Diamond vs. Teardrop) with 0ms delay.
- **Auto-Zoom to Operational Area (`map_bbox`)**: The map automatically calculates and applies `m.fit_bounds()` to frame the operational scope returned by the agent.
- **GeoJSON Boundary Outlines**: When places include boundary polygons (`place["shape"]`), the frontend renders semi-transparent tactical sector outlines (`folium.GeoJson`).
- **Basemap HUD Switcher**: CartoDB Voyager Dark (tactical dark navigation), CartoDB Dark Matter, Esri Dark Gray Canvas, High-Resolution Satellite Imagery, Topographic, and OSM.

### 2. Multi-Modal Spatial Targeting
- **Map Click Target Selection**: Clicking the map selects coordinate targets without triggering immediate backend queries.
- **Area-of-Interest (AOI) Bounding Box Suite**: Draw tactical rectangles using the map toolbar to define spatial envelopes `(lower-left, upper-right)` in GeoJSON `[lon, lat]` order.
- **Reconnaissance Scans**: Click the **🔍 Recon Scan** button (in sidebar, map HUD, or docked chat pill) to run instant multi-modal reconnaissance over points or bounding boxes without typing a question.
- **One-Click Deletion**: Integrated trash bin controls on both the map toolbar and chat docked pill to clear selections instantly.

### 3. Operator Intel Console & Grounded Sources
- **Show Citations Toggle & Interactive Badges**: Toggle between verified grounding marks (`result["answer"]` with clickable `[1]`, `[S2]`, `[L1]`, `[P1-S1]` badges) and clean conversational prose (`result["answer_plain"]`).
- **Verified Source Drawer**: Resolves `TEXT_XXXXX` paragraph pointers into human-readable document titles and section names from the knowledge graph.
- **Character Span Highlighting**: Inspected source passages highlight verbatim entity and concept mentions in styled `<mark>` tags using `citation["spans"]`.
- **Interactive Answer Subgraph Modal**: Inspect the induced entity and provenance knowledge subgraph (`LOC`, `ORG`, `PER`, `TEXT`) for any assistant response.
- **Interactive Follow-Up Buttons**: Up to 3 suggested questions (`result["follow_ups"]`) are rendered as clickable buttons (`🔍 {q}`) below assistant answers.
- **Regional Distribution Expander**: Displays region-by-region counts (`result["regions"]`) for broad queries spanning multiple oblasts.
- **Did-You-Mean Notices**: Displays alternative suggestions (`result["did_you_mean"]`) when queries involve ambiguous place names.
- **RAG Telemetry & Debug Dialog**: Click **📋 RAG Debug Logs** in the sidebar to inspect raw JSON request and response payloads, round-trip latency (ms), and grounding evidence.

---

## ⚡ Streamlit Performance Guidelines (`AGENTS.md`)

To keep the application fast, responsive, and free from visual jumping, all agents and developers must adhere to the rules in [`AGENTS.md`](AGENTS.md):
1. **Never allow map pan/zoom to trigger Python reruns**: Always constrain `returned_objects=["last_clicked", "last_active_drawing", "all_drawings"]` and `return_on_hover=False` in `st_folium()`.
2. **No unconditional module reloads or dependency scans**: Wrap bootstrap checks with `_BOOTSTRAP_DONE` once per process; do not place unguarded `importlib.reload(geo_agent)` calls in global scope.
3. **In-memory LRU caching for knowledge graph text**: Wrap `get_source_text()` with `@functools.lru_cache(maxsize=4096)`.
4. **Stable layout container heights**: Keep `chat_container_height = 465` constant to prevent the chat scroll area and input box from bouncing vertically.
5. **Cluster background context pins**: Primary places remain individual pins; context places use `folium.plugins.MarkerCluster`.

---

## 🧪 Automated Testing, Benchmarks & Definition of Done (`pytest`)

### Definition of Done (DoD)
Every code addition or modification in `ui/` must satisfy the strict **Definition of Done** codified in [`AGENTS.md`](AGENTS.md):
1. **Unit Test Pairing**: Every new feature, route, helper function, or UI element must include accompanying unit tests in `test_app.py`.
2. **Performance & Latency Benchmarks**: Every state mutation, adapter routine, or map interaction must include a micro-benchmark or latency ceiling assertion using the fixtures in `conftest.py` (`latency_ceiling`, `micro_benchmark`, `high_volume_rag_payload_factory`, `bbox_input_factory`, `streamlit_state_simulator`).
3. **Zero Regressions**: No commit or PR may reduce existing test coverage or violate established millisecond latency ceilings.

### Running the Full Test & Quality Gate Suite (140 Tests)
```bash
# Run the complete Quality Gate (File-pairing audit + Static AST checks + 140 pytest tests):
python verify_quality_gate.py

# Or run pytest directly:
python -m pytest test_app.py -v

# Platform test runners:
run_tests.bat          # Windows interactive
run_tests.bat --ci     # Windows CI / non-interactive
./run_tests.sh         # Linux / macOS

# Enable the Git pre-commit enforcement hook:
git config core.hooksPath .githooks
```
