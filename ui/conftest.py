"""
==============================================================================
GeoAI - Pytest Configuration, Performance Benchmarks & State Fixtures
==============================================================================
Provides reusable fixtures and performance assertion utilities for `test_app.py`:
1. Environment & Knowledge-Graph Isolation (`_isolate_test_environment`)
2. Micro-Benchmark & Latency Ceiling Enforcement (`assert_latency_ceiling`, `benchmark_op`)
3. High-Volume Spatial & RAG Payload Generators (`high_volume_rag_payload_factory`, `bbox_input_factory`)
4. Single-Pass Streamlit Session State Simulator (`StreamlitStateSimulator`, `streamlit_state_simulator`)
==============================================================================
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import math
import statistics
import time
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple

import pytest

import geo_agent
from geo_agent import AgentResponse, MapLayer, to_bounding_box


# ==============================================================================
# 1. Global Test Isolation
# ==============================================================================
@pytest.fixture(autouse=True)
def _isolate_test_environment(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """
    Isolate unit and performance tests from external network calls and
    unintended 70s disk decompression of `knowledge_graph.json.gz`.
    Tests that specifically test `_backend_get_source_text` can still
    monkeypatch `geo_agent._backend_get_source_text` inside the test body.
    """
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(geo_agent, "_backend_get_source_text", None, raising=False)
    if hasattr(geo_agent.get_source_text, "cache_clear"):
        geo_agent.get_source_text.cache_clear()
    yield
    if hasattr(geo_agent.get_source_text, "cache_clear"):
        geo_agent.get_source_text.cache_clear()


# ==============================================================================
# 2. Execution Timing & Latency Ceiling Utilities
# ==============================================================================
@dataclass
class LatencyMeasurement:
    """Result of a single timed execution block."""
    label: str
    elapsed_ms: float = 0.0
    ceiling_ms: float = 0.0
    passed: bool = False


@dataclass
class BenchmarkStats:
    """Statistical summary of a multi-iteration micro-benchmark."""
    label: str
    iterations: int
    min_ms: float
    mean_ms: float
    median_ms: float
    p95_ms: float
    max_ms: float
    total_ms: float
    samples_ms: List[float] = field(default_factory=list)


@contextmanager
def assert_latency_ceiling(max_ms: float, label: str = "operation") -> Generator[LatencyMeasurement, None, None]:
    """
    Context manager that measures wall-clock execution time via `time.perf_counter()`
    and fails the test immediately if elapsed time exceeds `max_ms`.
    """
    measurement = LatencyMeasurement(label=label, ceiling_ms=float(max_ms))
    t0 = time.perf_counter()
    try:
        yield measurement
    finally:
        measurement.elapsed_ms = (time.perf_counter() - t0) * 1000.0

    measurement.passed = measurement.elapsed_ms <= max_ms
    assert measurement.passed, (
        f"[LATENCY REGRESSION] '{label}' took {measurement.elapsed_ms:.3f}ms, "
        f"exceeding strict ceiling of {max_ms:.3f}ms."
    )


def benchmark_op(
    fn: Callable[..., Any],
    *args: Any,
    iterations: int = 20,
    warmup: int = 2,
    max_mean_ms: Optional[float] = None,
    max_p95_ms: Optional[float] = None,
    max_total_ms: Optional[float] = None,
    label: Optional[str] = None,
    **kwargs: Any,
) -> BenchmarkStats:
    """
    Execute `fn(*args, **kwargs)` across `warmup` + `iterations` passes using
    `time.perf_counter()` and assert optional mean, P95, and total latency ceilings.
    """
    op_label = label or getattr(fn, "__name__", "benchmark_op")
    for _ in range(max(0, warmup)):
        fn(*args, **kwargs)

    samples: List[float] = []
    for _ in range(max(1, iterations)):
        t0 = time.perf_counter()
        fn(*args, **kwargs)
        samples.append((time.perf_counter() - t0) * 1000.0)

    sorted_samples = sorted(samples)
    p95_idx = min(len(sorted_samples) - 1, max(0, math.ceil(0.95 * len(sorted_samples)) - 1))
    stats = BenchmarkStats(
        label=op_label,
        iterations=len(samples),
        min_ms=sorted_samples[0],
        mean_ms=statistics.fmean(sorted_samples),
        median_ms=statistics.median(sorted_samples),
        p95_ms=sorted_samples[p95_idx],
        max_ms=sorted_samples[-1],
        total_ms=sum(sorted_samples),
        samples_ms=samples,
    )

    if max_mean_ms is not None:
        assert stats.mean_ms <= max_mean_ms, (
            f"[LATENCY REGRESSION] '{op_label}' mean {stats.mean_ms:.3f}ms "
            f"> ceiling {max_mean_ms:.3f}ms (p95={stats.p95_ms:.3f}ms, n={stats.iterations})."
        )
    if max_p95_ms is not None:
        assert stats.p95_ms <= max_p95_ms, (
            f"[LATENCY REGRESSION] '{op_label}' P95 {stats.p95_ms:.3f}ms "
            f"> ceiling {max_p95_ms:.3f}ms (mean={stats.mean_ms:.3f}ms, n={stats.iterations})."
        )
    if max_total_ms is not None:
        assert stats.total_ms <= max_total_ms, (
            f"[LATENCY REGRESSION] '{op_label}' total {stats.total_ms:.3f}ms "
            f"> ceiling {max_total_ms:.3f}ms (n={stats.iterations})."
        )
    return stats


@pytest.fixture
def latency_ceiling():
    """Fixture exposing `assert_latency_ceiling(max_ms, label)`."""
    return assert_latency_ceiling


@pytest.fixture
def micro_benchmark():
    """Fixture exposing `benchmark_op(...)` for multi-pass latency benchmarking."""
    return benchmark_op


# ==============================================================================
# 3. High-Volume RAG & Spatial Payload Fixtures
# ==============================================================================
def build_high_volume_rag_payload(
    n_points: int = 250,
    primary_count: int = 12,
    uncertain_count: int = 8,
    include_shapes: bool = True,
    duplicate_coord_ratio: float = 0.25,
) -> Dict[str, Any]:
    """
    Generate a deterministic high-volume backend RAG response payload with `n_points`
    spatial features, primary polygon outlines, duplicate town coordinates (for
    MarkerCluster testing), citations, and bounding box metadata.
    """
    geo_locations: List[Dict[str, Any]] = []
    citations: List[Dict[str, Any]] = []
    sources: List[str] = []

    base_lat = 48.0
    base_lng = 31.0

    for idx in range(n_points):
        place_id = f"PLACE_{idx + 1:04d}"
        text_id = f"TEXT_{(idx % 40) + 1000}"
        if text_id not in sources:
            sources.append(text_id)

        if idx < primary_count:
            role = "primary"
            number = idx + 1
            uncertain = False
            lat = round(base_lat + (idx * 0.12), 5)
            lng = round(base_lng + (idx * 0.15), 5)
        elif idx < primary_count + uncertain_count:
            role = "primary"
            number = idx + 1
            uncertain = True
            lat = round(base_lat + (idx * 0.08), 5)
            lng = round(base_lng - (idx * 0.09), 5)
        else:
            role = "context"
            number = None
            uncertain = False
            # Intentionally create duplicate coordinates for a subset of context pins
            # to exercise Folium MarkerCluster spiderfy & clustering under load
            cluster_bucket = int(idx * (1.0 - duplicate_coord_ratio))
            lat = round(base_lat + ((cluster_bucket % 50) * 0.05), 5)
            lng = round(base_lng + ((cluster_bucket // 50) * 0.06), 5)

        loc_entry: Dict[str, Any] = {
            "id": place_id,
            "number": number,
            "name": f"Settlement_{idx + 1}",
            "label": f"Settlement_{idx + 1}",
            "lat": lat,
            "lon": lng,
            "geometry": {
                "type": "Point",
                "coordinates": [lng, lat],
            },
            "role": role,
            "uncertain": uncertain,
            "kind": "place" if not uncertain else "event",
            "why": f"event: Battle of Settlement_{idx + 1} in 3 records",
            "sources": [text_id],
        }

        if include_shapes and role == "primary" and not uncertain:
            d = 0.015
            loc_entry["shape"] = {
                "type": "Polygon",
                "coordinates": [[
                    [lng - d, lat - d],
                    [lng + d, lat - d],
                    [lng + d, lat + d],
                    [lng - d, lat + d],
                    [lng - d, lat - d],
                ]],
            }
            loc_entry["bbox"] = [lng - d, lat - d, lng + d, lat + d]

        geo_locations.append(loc_entry)

        if number is not None:
            citations.append({
                "id": f"P{number}-S1",
                "index": number,
                "number": number,
                "pointer": text_id,
                "place_id": place_id,
                "place_label": f"Settlement_{idx + 1}",
                "place_number": number,
                "article": f"Archive Document {idx + 1}",
                "section": "Operations",
                "snippet": f"Archival evidence for [{number}] Settlement_{idx + 1}.",
            })

    cited_refs = " ".join(f"[{i + 1}]" for i in range(min(primary_count, 6)))
    return {
        "answer": f"High-volume spatial intelligence synthesis covering {n_points} locations {cited_refs}.",
        "geo_locations": geo_locations,
        "regions": [
            {
                "id": "Central Operational Sector",
                "name": "Central Operational Sector",
                "bbox": [30.5, 47.5, 35.5, 51.5],
                "count": n_points,
                "places": list(range(1, primary_count + 1)),
            }
        ],
        "citations": citations,
        "sources": sources,
        "map": {
            "center": [49.2, 32.4],
            "zoom": 7,
            "bbox": [30.5, 47.5, 35.5, 51.5],
            "showing": "all",
            "not_shown": 0,
        },
    }


@pytest.fixture
def high_volume_rag_payload_factory():
    """Fixture returning `build_high_volume_rag_payload` for 200-500 point tests."""
    return build_high_volume_rag_payload


@pytest.fixture
def bbox_input_factory():
    """
    Fixture providing normalized bounding box generators, corner permutations
    (as `(lat, lng)` tuples matching `geo_agent.to_bounding_box`), and Leaflet Draw
    GeoJSON Polygon/Point payloads.
    """
    def _make_leaflet_polygon(west: float, south: float, east: float, north: float) -> Dict[str, Any]:
        return {
            "type": "Feature",
            "properties": {},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [west, south],
                    [east, south],
                    [east, north],
                    [west, north],
                    [west, south],
                ]],
            },
        }

    def _make_leaflet_point(lat: float, lng: float) -> Dict[str, Any]:
        return {
            "type": "Feature",
            "properties": {},
            "geometry": {
                "type": "Point",
                "coordinates": [lng, lat],
            },
        }

    def _make_corner_permutations(west: float, south: float, east: float, north: float) -> List[Tuple[Tuple[float, float], Tuple[float, float]]]:
        return [
            ((south, west), (north, east)),  # SW -> NE
            ((north, west), (south, east)),  # NW -> SE
            ((north, east), (south, west)),  # NE -> SW
            ((south, east), (north, west)),  # SE -> NW
        ]

    return {
        "make_leaflet_polygon": _make_leaflet_polygon,
        "make_leaflet_point": _make_leaflet_point,
        "make_corner_permutations": _make_corner_permutations,
        "to_bounding_box": to_bounding_box,
    }


# ==============================================================================
# 4. Single-Pass Streamlit Session State Simulator
# ==============================================================================
class SessionStateDict(dict):
    """Dict supporting both item (`st.session_state['k']`) and attribute (`st.session_state.k`) access."""
    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value


class StreamlitStateSimulator:
    """
    Deterministic simulator for the GeoAI Streamlit inverted execution lifecycle:
      Section 2c (early chat lock) -> Section 2b (early map event ingestion) ->
      col2 (`render_tactical_map_fragment`) -> col1 (chat console) -> Section 6b (`pending_query` execution).

    Tracks `rerun_count` and verifies that map clicks, bounding-box draws, corner release
    clicks, and chat submissions execute in a single pass without orphan secondary reruns.
    """

    def __init__(self) -> None:
        self.state = SessionStateDict()
        self.rerun_count = 0
        self.execution_passes = 0
        self.reset()

    def reset(self) -> None:
        """Initialize session state with the exact keys from `app.py` Section 2."""
        self.state.clear()
        self.state.update({
            "messages": [
                {
                    "role": "assistant",
                    "content": "Welcome to the **GeoAI Tactical Intelligence Console**.",
                }
            ],
            "agent_turns": [],
            "selection_mode": "Point Selection",
            "selected_points": [],
            "bounding_box": None,
            "answered_bbox": None,
            "active_point": None,
            "active_tactical_scan": None,
            "map_layers": [],
            "rag_logs": [],
            "pending_query": None,
            "last_clicked": None,
            "last_processed_drawing": None,
            "ignored_drawing": None,
            "last_drawing_time": 0.0,
            "selection_clear_seq": 0,
            "source_metadata_cache": {},
            "geoai_chat_input": "",
            "last_processed_chat_input": None,
            "run_chat_recon": False,
        })
        self.rerun_count = 0
        self.execution_passes = 0

    def record_rerun(self) -> None:
        """Hook for `st.rerun()` calls."""
        self.rerun_count += 1

    def _run_section_2c(self) -> Tuple[bool, bool]:
        """Execute Section 2c (early query ingestion & queueing) before Section 2b."""
        incoming_chat = self.state.get("geoai_chat_input")
        incoming_recon = bool(self.state.get("run_chat_recon"))
        is_chat_submit = bool(
            incoming_chat
            and isinstance(incoming_chat, str)
            and incoming_chat.strip()
            and incoming_chat != self.state.get("last_processed_chat_input")
        )

        if not self.state.get("pending_query"):
            is_bbox = self.state.get("bounding_box") is not None
            active_pt = None if is_bbox else (self.state["selected_points"][0] if self.state.get("selected_points") else None)
            active_bbox = self.state.get("bounding_box") if is_bbox else None

            if is_chat_submit:
                self.state["last_processed_chat_input"] = incoming_chat
                self.state["pending_query"] = {
                    "text_prompt": incoming_chat.strip(),
                    "selected_point": active_pt,
                    "bounding_box": active_bbox,
                }
            elif incoming_recon:
                self.state["pending_query"] = {
                    "text_prompt": None,
                    "selected_point": active_pt,
                    "bounding_box": active_bbox,
                    "is_recon": True,
                }
        return is_chat_submit, incoming_recon

    def simulate_point_click(
        self,
        lat: float,
        lng: float,
        feature_props: Optional[Dict[str, Any]] = None,
        now_ts: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Simulate a single map click pass inside Section 2b / `render_tactical_map_fragment`.
        """
        import app

        self.execution_passes += 1
        self._run_section_2c()

        now = now_ts if now_ts is not None else time.time()
        c_pt = (round(float(lat), 5), round(float(lng), 5))

        if feature_props and feature_props.get("action") == "delete":
            self.state["selected_points"] = []
            self.state["bounding_box"] = None
            self.state["active_point"] = None
            self.state["last_clicked"] = c_pt
            self.state["last_processed_drawing"] = None
            self.state["last_drawing_time"] = now
            return dict(self.state)

        if feature_props and feature_props.get("action") == "recon":
            target_type = feature_props.get("targetType") or feature_props.get("type")
            if target_type == "bbox":
                sw = feature_props.get("sw") or (feature_props["south"], feature_props["west"])
                ne = feature_props.get("ne") or (feature_props["north"], feature_props["east"])
                bbox_tuple = (
                    (round(float(sw[0]), 5), round(float(sw[1]), 5)),
                    (round(float(ne[0]), 5), round(float(ne[1]), 5)),
                )
                self.state["selection_mode"] = "Bounding Box"
                self.state["selected_points"] = [bbox_tuple[0], bbox_tuple[1]]
                self.state["bounding_box"] = bbox_tuple
                self.state["active_point"] = bbox_tuple[1]
                self.state["pending_query"] = {
                    "text_prompt": None,
                    "selected_point": None,
                    "bounding_box": bbox_tuple,
                    "is_recon": True,
                }
            else:
                pt_tuple = (
                    round(float(feature_props.get("lat", lat)), 5),
                    round(float(feature_props.get("lng", lng)), 5),
                )
                self.state["selection_mode"] = "Point Selection"
                self.state["selected_points"] = [pt_tuple]
                self.state["bounding_box"] = None
                self.state["active_point"] = pt_tuple
                self.state["pending_query"] = {
                    "text_prompt": None,
                    "selected_point": pt_tuple,
                    "bounding_box": None,
                    "is_recon": True,
                }
            self.record_rerun()
            return dict(self.state)

        # Standard map click handling (matches Section 2b lines 5157-5172)
        is_corner = app._is_drawing_corner_release(c_pt, self.state.get("bounding_box"), tolerance=0.02)
        just_drew = (now - self.state.get("last_drawing_time", 0.0)) < 0.8

        # Check if click matches an existing tactical marker
        clicked_existing_pin = any(
            layer.layer_type == "marker"
            and isinstance(layer.data, dict)
            and abs(layer.data.get("lat", 0.0) - c_pt[0]) < 1e-4
            and abs(layer.data.get("lng", 0.0) - c_pt[1]) < 1e-4
            for layer in self.state.get("map_layers", [])
        )

        if is_corner or (just_drew and self.state.get("bounding_box") is not None) or clicked_existing_pin:
            self.state["last_clicked"] = c_pt
        elif c_pt != self.state.get("last_clicked"):
            self.state["last_clicked"] = c_pt
            if self.state.get("selected_points") != [c_pt] or self.state.get("bounding_box") is not None:
                self.state["selection_mode"] = "Point Selection"
                self.state["selected_points"] = [c_pt]
                self.state["bounding_box"] = None
                self.state["answered_bbox"] = None
                self.state["active_point"] = c_pt
                self.state["active_tactical_scan"] = None

        return dict(self.state)

    def simulate_bbox_draw(
        self,
        west: float,
        south: float,
        east: float,
        north: float,
        now_ts: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Simulate drawing/resizing a rectangle AOI on the map (zero `st.rerun()` calls)."""
        self.execution_passes += 1
        self._run_section_2c()

        now = now_ts if now_ts is not None else time.time()
        active_draw = {
            "type": "Feature",
            "properties": {},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [west, south],
                    [east, south],
                    [east, north],
                    [west, north],
                    [west, south],
                ]],
            },
        }

        if active_draw != self.state.get("last_processed_drawing"):
            self.state["last_processed_drawing"] = active_draw
            self.state["ignored_drawing"] = None
            ring = active_draw["geometry"]["coordinates"][0]
            lats = [float(pt[1]) for pt in ring]
            lngs = [float(pt[0]) for pt in ring]
            ll, ur = to_bounding_box((min(lats), min(lngs)), (max(lats), max(lngs)))
            self.state["selection_mode"] = "Bounding Box"
            self.state["selected_points"] = [ll, ur]
            self.state["bounding_box"] = (ll, ur)
            self.state["answered_bbox"] = None
            self.state["active_point"] = ur
            self.state["active_tactical_scan"] = None
            self.state["last_drawing_time"] = now

        return dict(self.state)

    def simulate_trash_delete(self) -> Dict[str, Any]:
        """Simulate clearing active drawings via Leaflet Draw trash bin (zero `st.rerun()` calls)."""
        self.execution_passes += 1
        self._run_section_2c()
        self.state["selected_points"] = []
        self.state["bounding_box"] = None
        self.state["answered_bbox"] = None
        self.state["active_point"] = None
        self.state["selection_mode"] = "Point Selection"
        self.state["last_processed_drawing"] = None
        self.state["last_clicked"] = None
        self.state["selection_clear_seq"] = self.state.get("selection_clear_seq", 0) + 1
        return dict(self.state)

    def simulate_chat_submit(
        self,
        prompt: str,
        agent_fn: Optional[Callable[..., AgentResponse]] = None,
    ) -> AgentResponse:
        """
        Simulate a complete single-cycle user chat submission:
        1. User enters text in `geoai_chat_input`.
        2. Section 2c locks `pending_query` with current `selected_point`/`bounding_box` BEFORE Section 2b.
        3. Section 6b executes `query_geo_agent` (or `agent_fn`), updates `messages`, `agent_turns` (<=5),
           `map_layers`, `rag_logs` (<=50), clears spatial selection, and triggers 1 rerun.
        """
        import app

        self.execution_passes += 1
        self.state["geoai_chat_input"] = prompt
        self._run_section_2c()

        pq = self.state.get("pending_query")
        assert pq is not None, "Section 2c failed to queue pending_query on chat submit"
        self.state["pending_query"] = None

        user_msg = pq["text_prompt"] or "Recon Scan"
        self.state["messages"].append({"role": "user", "content": user_msg})

        runner = agent_fn or geo_agent.query_geo_agent
        response = runner(
            text_prompt=pq["text_prompt"],
            selected_point=pq["selected_point"],
            bounding_box=pq["bounding_box"],
            agent_turns=self.state["agent_turns"],
        )

        assistant_msg = app._build_assistant_message(response)
        self.state["messages"].append(assistant_msg)
        self.state["agent_turns"].append({"query": user_msg, "response": response.raw_response or {"answer": response.answer}})
        if len(self.state["agent_turns"]) > 5:
            self.state["agent_turns"] = self.state["agent_turns"][-5:]

        self.state["map_layers"] = list(response.layers)
        self.state["rag_logs"].append({
            "id": len(self.state["rag_logs"]) + 1,
            "timestamp": "2026-11-08 12:00:00",
            "latency_ms": 12.5,
            "status": "SUCCESS",
            "query_summary": user_msg,
            "sources": response.sources,
            "layers_count": len(response.layers),
        })
        if len(self.state["rag_logs"]) > 50:
            self.state["rag_logs"] = self.state["rag_logs"][-50:]

        # Post-query cleanup (matches Section 6b)
        self.state["selected_points"] = []
        self.state["bounding_box"] = None
        self.state["active_point"] = None
        self.state["last_clicked"] = None
        self.state["last_processed_drawing"] = None
        self.record_rerun()
        return response


@pytest.fixture
def streamlit_state_simulator() -> StreamlitStateSimulator:
    """Fixture providing a fresh `StreamlitStateSimulator` instance for state loop tests."""
    return StreamlitStateSimulator()
