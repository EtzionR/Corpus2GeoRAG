# 🌍 Corpus2GeoRAG

A geographically-aware knowledge graph and Retrieval-Augmented Generation (GeoRAG) intelligence platform for exploring warfare-focused Wikipedia corpora through multi-modal natural language questions and synchronized maps.

```
Corpus Collection ──> NER Extraction ──> Knowledge Graph (+ Geocoding) ──> GeoRAG Agent ──> Tactical C2 UI
```

---

## 🏛️ Repository Architecture

- **`ui/`**: Interactive Streamlit application connecting the conversational operator console with a high-performance Leaflet/Folium map of Ukraine. Features zero-latency client-side pan/zoom, boundary polygon rendering, context marker clustering, and verbatim source inspection with `<mark>` span highlighting.
  - [UI Quick Start & Documentation](ui/README.md)
  - [UI Zero-Latency Performance Rules (AGENTS.md)](ui/AGENTS.md)
  - [UI ↔ AgentRag Integration Specifications](ui/PULL_REQUEST.md)
- **`AgentRag/`**: The Phase 2 (Vr6) agent pipeline that queries the knowledge graph in 6 deterministic steps (understand, resolve, retrieve, evidence, write, result).
  - [AgentRag Documentation](AgentRag/AgentRag_README.md)
  - [UI Connection Contract (CONNECT_UI.md)](AgentRag/CONNECT_UI.md)
- **`Graph_n_Geocoding/`**: The Vr6 knowledge graph (`knowledge_graph.json.gz`) containing 120,000+ nodes, relations, geocoded coordinates, and administrative polygon boundaries.
- **`CollectCorpus/`**: Corpus acquisition scripts and document scrapers.
- **`ApplyNER/`**: Named Entity Recognition (PER / ORG / LOC) pipeline annotating text paragraphs with character spans.

---

## 🚀 Quick Start: Running the Application

To launch the full interactive UI connected to the GeoRAG agent:

### Windows (One-Click)
Double-click:
```text
ui\run_app.bat
```

### Linux / macOS
```bash
cd ui
chmod +x run_app.sh
./run_app.sh
```

### Automated Unit Testing
To run the full suite of 55 UI and integration tests:
```bash
cd ui
python -m pytest test_app.py -v
```
*(On Windows, you can also double-click `ui\run_tests.bat`).*