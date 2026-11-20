# GeoAI Frontend & Streamlit Performance Guidelines (AGENTS.md)

This document establishes critical architectural rules and performance requirements for all AI agents and developers working on `GeoAI - Project`.

---

## 1. Streamlit-Folium Interaction & Zero-Latency Rules

### 1.1 Never Allow Map Pan / Zoom / Popup Clicks to Trigger Python Reruns
- `streamlit-folium` by default serializes and returns map bounds, zoom level, center coordinates, and clicked object metadata back to Python on every pan (`moveend`), zoom (`zoomend`), and marker popup click.
- In a Streamlit app, every payload sent back from a custom component forces Streamlit to **re-execute the entire Python script top-to-bottom**, dimming the screen and causing severe visual lag and jumpiness.
- **Rule:** Always explicitly constrain `returned_objects` in `st_folium()`:
  ```python
  map_data = st_folium(
      m,
      feature_group_to_add=[selection_fg, tactical_layers_fg],
      returned_objects=["last_clicked", "last_active_drawing", "all_drawings"],
      key="geoai_tactical_map",
      height=520,
      use_container_width=True,
      return_on_hover=False
  )
  ```
  This ensures map panning, zooming, and reading marker popups execute **100% on the client side with 0 ms latency** and zero Python script reruns.

### 1.2 Client-Side Layer Toggling via Leaflet
- Pin filters, visibility toggles, and layer controls should be implemented as native Leaflet controls (`L.Control`) or custom DOM controls inside the map canvas whenever possible.
- Toggling markers via JavaScript (`layer._icon.style.display = 'none'`) provides immediate visual response without triggering a Python server round-trip or iframe reload.

---

## 2. Python Script Lifecycle & Startup Hygiene

### 2.1 No Unconditional Module Reloading
- **Rule:** Do NOT place `importlib.reload(...)` or dependency installation checks in the global scope of `app.py`.
- Running `find_spec()` or reloading modules on every rerun re-executes module initialization code, re-parses paths, and clears caches on every click.
- Guard dependency bootstrapping so it executes strictly once per process.

### 2.2 In-Memory Caching for Knowledge Graph Text Lookups
- `get_source_text(pointer)` performs paragraph lookups in the knowledge graph.
- **Rule:** Always wrap text retrieval in an LRU cache (`@functools.lru_cache(maxsize=4096)`) so repeated lookups (for display labels, inspect drawers, popups, and logs) take sub-microsecond time:
  ```python
  @functools.lru_cache(maxsize=4096)
  def get_source_text(pointer: str) -> Optional[Dict[str, Any]]:
      ...
  ```

---

## 3. UI Layout Stability & Anti-Jumpiness

### 3.1 Stable Container Heights
- **Rule:** Container heights must remain constant across state changes.
- Never dynamically alter `st.container(height=...)` based on temporary states (e.g., whether points are currently selected or cleared). Variable container heights cause the chat scroll area and input box to physically bounce vertically on the screen.

### 3.2 Guard Against Widget ID Explosion
- When queries return dense context lists (50–500 places), avoid instantiating hundreds of individual Streamlit button widgets (e.g. `st.button("🗑️", key=f"del_layer_{i}")`) on every rerun.
- Aggregate bulk items into single controls or paginated/clustered views to keep Streamlit's delta generator lightweight.

---

## 4. Map Layering & Scalability

### 4.1 Cluster Background Context Pins
- Queries with large geographic scopes return up to 500–1,600 context places, frequently with duplicate coordinates for landmarks within the same town.
- **Rule:** Primary focal places (`role == "primary"`) must be rendered as distinct individual pins and outlines. Context places (`role == "context"`) must be clustered using `folium.plugins.MarkerCluster` to prevent map DOM choking and enable spiderfy de-duplication on click.

### 4.2 Auto-Zoom to Query Bounding Box
- When the backend provides `result["map"]["bbox"]` (`[west, south, east, north]`), use `m.fit_bounds([[south, west], [north, east]], padding=(30, 30))` to automatically frame the operational area for the user upon query completion.

---

## 5. Development & Deployment Workflow

### 5.1 Primary Workspace (`GeoAI - Project`)
- **Rule:** All ongoing development, bug fixes, UI improvements, and test implementations must be conducted strictly within `GeoAI - Project`.
- Always run and verify the test suite locally before any deployment:
  ```bash
  pytest test_app.py -v
  ```

### 5.2 Synchronization to `Corpus2GeoRAG\ui` & Remote
- Once changes are tested and verified in `GeoAI - Project`:
  1. Sync the updated files directly into `Corpus2GeoRAG\ui\` (`app.py`, `geo_agent.py`, `test_app.py`, `AGENTS.md`, `README.md`, etc.).
  2. Confirm that changes in `Corpus2GeoRAG` remain 100% confined to the `ui/` directory.
  3. Commit and push the feature branch to the remote (`origin`).
  4. Create or update the pull request against upstream (`EtzionR/Corpus2GeoRAG:main`).
- **Never make unverified direct modifications in `Corpus2GeoRAG\ui\` or outside the `ui/` folder.**


---

## 6. Mandatory Test-Driven & Performance Enforcement Protocol (Definition of Done)

No feature, bug fix, refactor, or UI modification in `ui/` (`GeoAI - Project`) is considered complete unless it satisfies every criterion in this **Definition of Done (DoD)**:

### 6.1 Strict Definition of Done (DoD)
1. **Mandatory Unit Test Pairing:**
   - Every new feature, route, helper function, dataclass, or UI element in `app.py`, `geo_agent.py`, or any new `.py` module **must** include accompanying unit tests in `test_app.py` verifying normal execution and edge cases.
   - `verify_quality_gate.py` automatically audits all `.py` files and public symbols in the workspace and blocks execution if any module or symbol lacks matching test coverage in `test_app.py`.
2. **Mandatory Performance & Latency Ceiling Tests:**
   - Every state mutation, network/adapter call, HTML/SVG renderer, or Folium map interaction **must** include an accompanying micro-benchmark or latency assertion using the fixtures in `conftest.py` (`latency_ceiling`, `micro_benchmark`, `high_volume_rag_payload_factory`, `streamlit_state_simulator`).
   - Enforced synchronous latency ceilings:
     | Operation / Pipeline Path | Ceiling (ms) |
     | :--- | :--- |
     | `make_pin_icon` (single icon across all role/shape variants) | `<= 1.0 ms` mean (`<= 2.0 ms` P95) |
     | `make_pin_icon` (batch of 100 icons) | `<= 25.0 ms` total |
     | `color_token` & `bbox_style` lookups | `<= 0.2 ms` mean |
     | `_popup_card` HTML synthesis | `<= 0.5 ms` mean |
     | `_highlight_text_spans` interval merging & `<mark>` rendering | `<= 2.0 ms` mean |
     | `format_tactical_citations` regex badge linking | `<= 5.0 ms` mean |
     | `_render_subgraph_modal_html` interactive SVG/HTML synthesis | `<= 15.0 ms` mean |
     | `MapTrashBinHook` + `SelectionSyncHook` Folium compilation | `<= 80.0 ms` mean |
     | `_build_raw_request_payload` request serialization | `<= 1.0 ms` mean |
     | `format_evidence_popup_html` popup evidence rendering | `<= 2.0 ms` mean |
     | `extract_answer_subgraph` induced subgraph extraction | `<= 25.0 ms` mean |
     | `get_source_text` (1,000 warm LRU cache lookups) | `<= 5.0 ms` total (`< 0.005 ms` / hit) |
     | `to_bounding_box` (1,000 corner normalizations) | `<= 15.0 ms` total |
     | `query_geo_agent` hydration & GeoJSON parsing (250 points) | `<= 120.0 ms` total |
     | `query_geo_agent` hydration & GeoJSON parsing (500 points) | `<= 250.0 ms` total |
     | Folium `MarkerCluster` vs primary pin partitioning (500 layers) | `<= 150.0 ms` total |
     | 50 rapid consecutive map point clicks (`StreamlitStateSimulator`) | `<= 25.0 ms` total (`0` `st.rerun()`) |
     | 25 rapid AOI BBox resizes + corner release clicks | `<= 25.0 ms` total (`0` `st.rerun()`) |
3. **Zero Regression & Non-Decreasing Coverage:**
   - No commit or PR may reduce the total test count below `MIN_REQUIRED_TESTS` (`139+` tests), weaken AST invariants, or introduce unguarded `st.rerun()` calls inside Section 2c, Section 2b, or map click/draw handlers.

### 6.2 Automated Quality Gate & Pre-Commit Enforcement
- Before any commit or deployment, run the automated enforcement gate:
  ```bash
  python verify_quality_gate.py
  # or via platform runners:
  run_tests.bat --ci
  ./run_tests.sh
  ```
- Enable the repository Git pre-commit hook so commits are automatically blocked on any test failure, missing test pairing, or latency regression:
  ```bash
  git config core.hooksPath .githooks
  ```
