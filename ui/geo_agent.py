"""
==============================================================================
GeoAI Final Project - Mock Backend Contract & Spatial RAG Agent
==============================================================================
This module defines the data contract and mock reasoning engine for the GeoAI
system. In a production deployment, this acts as the interface to a full
Retrieval-Augmented Generation (RAG) pipeline operating on vector databases,
spatial knowledge graphs, and geocoded intelligence feeds.

Data Models:
    - MapLayer: Represents a geospatial layer (marker, circle, polygon) to render on Folium.
    - AgentResponse: Represents the multimodal output containing structured text and layers.

Function:
    - query_geo_agent: The core routing entrypoint handling all multi-modal queries.
==============================================================================
"""

from __future__ import annotations

import os
import sys
import logging
import functools
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

__all__ = [
    "MapLayer",
    "AgentResponse",
    "to_bounding_box",
    "get_source_text",
    "query_geo_agent",
    "AgentError",
    "InvalidRequestError",
    "LLMNotConfiguredError",
    "LLMRateLimitError",
    "LLMError",
]

# ==============================================================================
# 0. Backend GeoRAG Agent Discovery & Exception Contract
# ==============================================================================

_BACKEND_AVAILABLE = False
_backend_query = None
_backend_get_source_text = None

# Attempt to locate AgentRag dynamically
_current_dir = Path(__file__).resolve().parent
_potential_agent_dirs = [
    _current_dir.parent / "AgentRag",                             # Inside Corpus2GeoRAG repository (standard layout)
    _current_dir / "AgentRag",                                    # Local vendored copy
    _current_dir.parent / "Corpus2GeoRAG" / "AgentRag",           # Sibling project directory
]
if "AGENT_RAG_PATH" in os.environ:
    _potential_agent_dirs.insert(0, Path(os.environ["AGENT_RAG_PATH"]))

for _p in _potential_agent_dirs:
    if (_p / "georag_agent.py").is_file():
        if str(_p) not in sys.path:
            sys.path.insert(0, str(_p))
        break

# Note: AgentRag automatically locates Graph_n_Geocoding/knowledge_graph.json.gz (Vr6)
# relative to its own directory unless GRAPH_PATH is explicitly set in the environment.
# Clear any stale GRAPH_PATH from older sessions pointing to the deleted uncompressed .json file.
if os.environ.get("GRAPH_PATH", "").endswith("knowledge_graph.json"):
    os.environ.pop("GRAPH_PATH", None)

# If an older Phase 1 georag_agent module is cached in sys.modules (pre-Vr6), evict it
if "georag_agent" in sys.modules and not hasattr(sys.modules["georag_agent"], "pipeline"):
    for _stale_mod in ("georag_agent", "agent", "contracts", "graph_client"):
        sys.modules.pop(_stale_mod, None)

try:
    from georag_agent import (
        query as _backend_query,
        get_source_text as _backend_get_source_text,
        AgentError,
        InvalidRequestError,
        LLMNotConfiguredError,
        LLMRateLimitError,
        LLMError,
    )
    _BACKEND_AVAILABLE = True

    # Pre-warm knowledge graph index in a background daemon thread to eliminate the 13.7s freeze on first query
    import threading
    def _warmup_graph_worker():
        try:
            import georag_agent
            if hasattr(georag_agent, "get_graph"):
                georag_agent.get_graph()
        except Exception:
            pass

    _warmup_thread = threading.Thread(target=_warmup_graph_worker, daemon=True, name="GeoAI-GraphPrewarm")
    _warmup_thread.start()
except Exception as _import_err:
    logger.debug("GeoRAG backend not importable directly: %s", _import_err)

    class AgentError(RuntimeError):
        """Base class for every error the agent raises on purpose."""

    class InvalidRequestError(AgentError):
        """The question or location passed in doesn't match the contract."""

    class LLMNotConfiguredError(AgentError):
        """No OpenRouter key was given, or OpenRouter rejected it."""

    class LLMRateLimitError(AgentError):
        """OpenRouter's rate limit was hit (common on free models) - retry shortly."""

    class LLMError(AgentError):
        """OpenRouter failed, or the LLM answered in a shape the agent can't use - retry."""


# ==============================================================================
# 1. Data Contracts (Dataclasses)
# ==============================================================================

@dataclass
class MapLayer:
    """
    Represents an individual geospatial visual layer to be rendered on the Folium map.

    Attributes:
        name (str): Human-readable name or identifier for the layer.
        layer_type (str): Geometry type, such as 'marker', 'circle', 'polygon', or 'geojson'.
        data (Dict[str, Any] | List[Any] | Any): The spatial payload. Typically a dict
            with keys like 'lat', 'lng', 'radius', or GeoJSON features.
        color (str): Hex color or standard Folium/Leaflet color name (e.g., 'blue', 'red', 'green').
        tooltip (str): Quick text displayed when hovering over the element.
        popup (str): Rich HTML or text displayed when clicking the element.
    """
    name: str
    layer_type: str
    data: Any
    color: str = "blue"
    tooltip: str = ""
    popup: str = ""


@dataclass
class AgentResponse:
    """
    Standardized response contract returned by the GeoAI Agent.

    Attributes:
        answer (str): Natural language synthesis answering the user's inquiry,
            including citation marks ([1], [S2], [L1]).
        layers (List[MapLayer]): A collection of map layers synthesized or retrieved
            by the agent to be displayed synchronously on the frontend map.
        sources (List[str]): Source paragraph pointers (e.g. 'TEXT_50333') backing the answer.
        raw_response (Optional[Dict[str, Any]]): Original response dictionary from the backend.
        is_live_backend (bool): Whether the response was produced by the live GeoRAG agent.
        answer_plain (str): Clean version of the answer with citation marks stripped.
        citations (List[Dict[str, Any]]): Structured citation metadata ({id, pointer, article, section, spans}).
        grounded (bool): True when backed by graph evidence; False if LLM-only fallback.
        status (str): Backend status ('answered', 'no_data', 'out_of_scope', 'llm_failed').
    """
    answer: str
    layers: List[MapLayer] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)
    raw_response: Optional[Dict[str, Any]] = None
    is_live_backend: bool = False
    answer_plain: str = ""
    citations: List[Dict[str, Any]] = field(default_factory=list)
    grounded: bool = True
    status: str = "answered"
    shape: str = "fact"
    map_bbox: Optional[List[float]] = None
    follow_ups: List[str] = field(default_factory=list)
    regions: List[Dict[str, Any]] = field(default_factory=list)
    did_you_mean: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self):
        if not self.answer_plain:
            self.answer_plain = self.answer


# ==============================================================================
# 2. Bounding Box & Source Utilities
# ==============================================================================

def to_bounding_box(
    p1: Tuple[float, float],
    p2: Tuple[float, float]
) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """
    Computes a standardized two-point bounding box (lower-left, upper-right) from two coordinates.
    Lower-left = (min_lat, min_lng) [South-West corner]
    Upper-right = (max_lat, max_lng) [North-East corner]

    Args:
        p1 (Tuple[float, float]): First coordinate (latitude, longitude).
        p2 (Tuple[float, float]): Second coordinate (latitude, longitude).

    Returns:
        Tuple[Tuple[float, float], Tuple[float, float]]: ((min_lat, min_lng), (max_lat, max_lng))
    """
    lower_left = (round(min(p1[0], p2[0]), 5), round(min(p1[1], p2[1]), 5))
    upper_right = (round(max(p1[0], p2[0]), 5), round(max(p1[1], p2[1]), 5))
    return (lower_left, upper_right)


@functools.lru_cache(maxsize=4096)
def get_source_text(pointer: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve verbatim source text passages for a given paragraph pointer (e.g. 'TEXT_50333')
    from the knowledge graph.
    Returns {'pointer', 'text', 'document', 'section', 'paragraph_index'} or None if not found.
    Results are cached in memory for sub-microsecond subsequent retrieval.
    """
    if not pointer or not isinstance(pointer, str) or not pointer.startswith("TEXT_"):
        return None
    if _backend_get_source_text is not None:
        try:
            return _backend_get_source_text(pointer)
        except Exception as e:
            logger.warning("Error fetching source text for '%s': %s", pointer, e)
            return None
    return None


# ==============================================================================
# 3. GeoAI Routing Entrypoint (Adapter with Mock Fallback)
# ==============================================================================

def query_geo_agent(
    text_prompt: Optional[str] = None,
    selected_point: Optional[Tuple[float, float]] = None,
    bounding_box: Optional[Tuple[Tuple[float, float], Tuple[float, float]]] = None,
    chat_history: Optional[List[Dict[str, Any]]] = None,
    api_key: Optional[str] = None,
    agent_turns: Optional[List[Dict[str, Any]]] = None,
    force_mock: bool = False,
    **kwargs: Any
) -> AgentResponse:
    """
    Route and process user multimodal requests combining free-form text queries,
    interactive map click coordinates, bounding box extents, and conversational context.

    If an OpenRouter API key is provided (or in OPENROUTER_API_KEY environment variable)
    and the backend agent is available, this routes to the real LangChain/OpenRouter
    GeoRAG agent. Otherwise, it seamlessly delegates to the built-in deterministic
    mock engine.
    """
    effective_key = api_key or os.environ.get("OPENROUTER_API_KEY")

    # If backend agent is available and API key is present, invoke live agent
    if _BACKEND_AVAILABLE and effective_key and not force_mock:
        has_text = bool(text_prompt and text_prompt.strip())
        if bounding_box and len(bounding_box) == 2:
            selected_point = None

        # 1. Format geo_location in GeoJSON [lon, lat] order
        geo_location: Optional[Dict[str, Any]] = None
        if bounding_box and len(bounding_box) == 2:
            (min_lat, min_lng), (max_lat, max_lng) = to_bounding_box(bounding_box[0], bounding_box[1])
            w, s = min_lng, min_lat
            e, n = max_lng, max_lat
            geo_location = {
                "type": "polygon",
                "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]
            }
        elif selected_point:
            lat, lng = selected_point
            geo_location = {
                "type": "point",
                "coordinates": [round(float(lng), 5), round(float(lat), 5)],
                "radius_m": 1000.0
            }

        # 2. Ensure non-empty text prompt (required by backend QueryRequest contract)
        if has_text:
            query_text = text_prompt.strip()
        elif bounding_box:
            query_text = "What is in this bounding box sector?"
        elif selected_point:
            query_text = "What is in this area?"
        else:
            query_text = "What are the major locations in Ukraine?"
        # 3. Prepare chat turns if passed
        turns = agent_turns if isinstance(agent_turns, list) else []

        # 4. Invoke backend query
        raw_result = _backend_query(
            text_prompt=query_text,
            geo_location=geo_location,
            chat_history=turns,
            api_key=effective_key
        )

        # 5. Hydrate MapLayers from backend geo_locations (converting [lon, lat] -> [lat, lon])
        layers: List[MapLayer] = []
        for loc in raw_result.get("geo_locations", []):
            geom = loc.get("geometry", {})
            coords = geom.get("coordinates", []) if isinstance(geom, dict) else []
            if len(coords) >= 2:
                lon, lat = coords[0], coords[1]
            elif "latitude" in loc and "longitude" in loc:
                lat, lon = float(loc["latitude"]), float(loc["longitude"])
            elif "lat" in loc and "lng" in loc:
                lat, lon = float(loc["lat"]), float(loc["lng"])
            elif "lat" in loc and "lon" in loc:
                lat, lon = float(loc["lat"]), float(loc["lon"])
            else:
                continue

            number = loc.get("number")
            kind = loc.get("kind", "place")
            role = loc.get("role", "primary")
            label = loc.get("label") or loc.get("name") or loc.get("id") or "Unknown Node"
            node_id = loc.get("id") or loc.get("name") or ""
            why = loc.get("why", "")
            uncertain = loc.get("uncertain")
            sources_list = loc.get("sources", [])

            if uncertain:
                color = "orange"
            elif kind == "event":
                color = "red"
            elif role == "context":
                color = "cadetblue"
            else:
                color = "blue"

            num_prefix = f"{number}. " if number is not None else ""
            uncertain_tag = " (?)" if uncertain else ""
            layer_name = f"{num_prefix}[{kind.upper()}] {label}{uncertain_tag}"
            tooltip_text = f"{num_prefix}{label} [{kind.upper()}]{uncertain_tag}"

            why_html = f"<br><b>Evidence:</b> {why}" if why else ""
            uncertain_html = f"<br><span style='color:#ff9800;'><b>⚠️ Uncertain:</b> {uncertain}</span>" if uncertain else ""
            src_html = ""
            if sources_list:
                src_titles = []
                for s_ptr in sources_list[:3]:
                    s_text = get_source_text(s_ptr)
                    if s_text and s_text.get("document"):
                        doc_clean = str(s_text["document"]).replace("\ufffd", " - ")
                        src_titles.append(doc_clean)
                    else:
                        src_titles.append(s_ptr)
                src_html = f"<br><b>Sources:</b> {', '.join(src_titles)}{'...' if len(sources_list) > 3 else ''}"
            header_title = f"#{number} {label}" if number is not None else label
            popup_content = (
                f"<div style='font-family:monospace; padding:6px;'>"
                f"<b>★ {header_title}</b><br>"
                f"ID: <code>{node_id}</code><br>"
                f"TYPE: <code>{kind.upper()}</code> ({role})<br>"
                f"LAT: <code>{lat:.5f}°</code><br>"
                f"LNG: <code>{lon:.5f}°</code>"
                f"{why_html}"
                f"{uncertain_html}"
                f"{src_html}"
                f"</div>"
            )
            layers.append(MapLayer(
                name=layer_name,
                layer_type="marker",
                data={
                    "lat": round(lat, 5),
                    "lng": round(lon, 5),
                    "id": node_id,
                    "kind": kind,
                    "number": number,
                    "role": role,
                    "uncertain": uncertain,
                },
                color=color,
                tooltip=tooltip_text,
                popup=popup_content
            ))

            # Upgrade 1: GeoJSON Place Boundary Outlines (place["shape"])
            shape_geom = loc.get("shape")
            if shape_geom and isinstance(shape_geom, dict) and shape_geom.get("coordinates"):
                layers.append(MapLayer(
                    name=f"Outline: {label}",
                    layer_type="geojson",
                    data=shape_geom,
                    color="cyan" if role == "primary" else "cadetblue",
                    tooltip=f"Boundary: {label}",
                    popup=f"<b>★ {label} Boundary</b><br>Type: <code>{shape_geom.get('type', 'Geometry')}</code>"
                ))

        # Add visual search boundary layer
        if bounding_box and len(bounding_box) == 2:
            (min_lat, min_lng), (max_lat, max_lng) = to_bounding_box(bounding_box[0], bounding_box[1])
            bbox_poly = [
                [min_lat, min_lng],
                [max_lat, min_lng],
                [max_lat, max_lng],
                [min_lat, max_lng],
                [min_lat, min_lng]
            ]
            layers.append(MapLayer(
                name=f"Sector BBox [{min_lat:.3f}, {min_lng:.3f}]-[{max_lat:.3f}, {max_lng:.3f}]",
                layer_type="polygon",
                data={"coordinates": bbox_poly},
                color="cyan",
                tooltip="Active Query Bounding Box",
                popup=f"<b>Bounding Box Sector</b><br>SW: ({min_lat:.4f}°, {min_lng:.4f}°)<br>NE: ({max_lat:.4f}°, {max_lng:.4f}°)"
            ))
        elif selected_point:
            layers.append(MapLayer(
                name=f"Target Buffer ({selected_point[0]:.3f}, {selected_point[1]:.3f})",
                layer_type="circle",
                data={"lat": selected_point[0], "lng": selected_point[1], "radius": 5000},
                color="cyan",
                tooltip="Target Buffer (5km)",
                popup=f"<b>Target Coordinate:</b> ({selected_point[0]:.4f}°, {selected_point[1]:.4f}°)"
            ))

        ans_text = raw_result.get("answer", "")
        top_sources = list(raw_result.get("sources", []))
        if not top_sources:
            # In Vr6, 'list' and 'place_lookup' answers store TEXT_ pointers on each place in geo_locations
            seen_ptrs = set()
            geo_locs = raw_result.get("geo_locations", [])
            for loc in geo_locs:
                if loc.get("role", "primary") == "primary" or len(geo_locs) <= 10:
                    for ptr in loc.get("sources", [])[:3]:
                        if ptr not in seen_ptrs:
                            seen_ptrs.add(ptr)
                            top_sources.append(ptr)
                        if len(top_sources) >= 15:
                            break
                if len(top_sources) >= 15:
                    break

        map_meta = raw_result.get("map", {})
        map_bbox = map_meta.get("bbox") if isinstance(map_meta, dict) else None

        return AgentResponse(
            answer=ans_text,
            layers=layers,
            sources=top_sources,
            raw_response=raw_result,
            is_live_backend=True,
            answer_plain=raw_result.get("answer_plain", ans_text),
            citations=raw_result.get("citations", []),
            grounded=raw_result.get("grounded", True),
            status=raw_result.get("status", "answered"),
            shape=raw_result.get("shape", "fact"),
            map_bbox=map_bbox,
            follow_ups=list(raw_result.get("follow_ups") or raw_result.get("follow_up_questions") or []),
            regions=raw_result.get("regions") if isinstance(raw_result.get("regions"), dict) else {},
            did_you_mean=raw_result.get("did_you_mean") or None,
        )

    # Fallback to deterministic mock routing
    mock_resp = _query_mock_agent(
        text_prompt=text_prompt,
        selected_point=selected_point,
        bounding_box=bounding_box,
        chat_history=chat_history,
        **kwargs
    )
    if mock_resp.raw_response is None:
        mock_geo_locs = []
        for ly in mock_resp.layers:
            if isinstance(ly.data, dict) and "lat" in ly.data and "lng" in ly.data:
                mock_geo_locs.append({
                    "id": ly.data.get("id", ly.name),
                    "label": ly.name,
                    "geometry": {
                        "type": "point",
                        "coordinates": [ly.data["lng"], ly.data["lat"]]
                    },
                    "kind": ly.data.get("kind", "place"),
                    "sources": mock_resp.sources
                })
        mock_resp.raw_response = {
            "answer": mock_resp.answer,
            "geo_locations": mock_geo_locs,
            "sources": mock_resp.sources
        }
    return mock_resp


def _query_mock_agent(
    text_prompt: Optional[str] = None,
    selected_point: Optional[Tuple[float, float]] = None,
    bounding_box: Optional[Tuple[Tuple[float, float], Tuple[float, float]]] = None,
    chat_history: Optional[List[Dict[str, Any]]] = None,
    **kwargs: Any
) -> AgentResponse:
    # Normalize inputs
    has_text = bool(text_prompt and text_prompt.strip())

    # Ensure mutual exclusivity: if a bounding box is selected, points shouldn't be in selected_point
    if bounding_box and len(bounding_box) == 2:
        selected_point = None

    # --------------------------------------------------------------------------
    # Scenario: Bounding Box Provided
    # --------------------------------------------------------------------------
    if bounding_box and len(bounding_box) == 2:
        lower_left, upper_right = to_bounding_box(bounding_box[0], bounding_box[1])
        bbox_coords = [
            [lower_left[0], lower_left[1]],
            [upper_right[0], lower_left[1]],
            [upper_right[0], upper_right[1]],
            [lower_left[0], upper_right[1]],
            [lower_left[0], lower_left[1]],
        ]

        if has_text:
            user_query = text_prompt.strip()
            answer_text = (
                f"### 📦 Bounding Box Area Analysis\n\n"
                f"**Query Intent:** \"{user_query}\"\n\n"
                f"**Bounding Box Extents (Two-Point Box):**\n"
                f"- **Lower-Left (SW):** `{lower_left[0]:.4f}° N, {lower_left[1]:.4f}° E`\n"
                f"- **Upper-Right (NE):** `{upper_right[0]:.4f}° N, {upper_right[1]:.4f}° E`\n\n"
                f"**Tactical Assessment:** Geospatial intelligence scan across the defined bounding box sector "
                f"correlating tactical data with *\"{user_query}\"*. Spatial analysis indicates active transit corridors, "
                f"logistical infrastructure, and operational assets within the defined perimeter."
            )
            layers = [
                MapLayer(
                    name=f"Box Lower-Left ({lower_left[0]:.3f}, {lower_left[1]:.3f})",
                    layer_type="marker",
                    data={"lat": lower_left[0], "lng": lower_left[1]},
                    color="red",
                    tooltip=f"Lower-Left (SW): {lower_left[0]:.4f}, {lower_left[1]:.4f}",
                    popup=(
                        f"<b>Bounding Box - Lower-Left (SW)</b><br>"
                        f"LAT: {lower_left[0]:.4f}°<br>"
                        f"LNG: {lower_left[1]:.4f}°<br>"
                        f"Query: {user_query}"
                    )
                ),
                MapLayer(
                    name=f"Box Upper-Right ({upper_right[0]:.3f}, {upper_right[1]:.3f})",
                    layer_type="marker",
                    data={"lat": upper_right[0], "lng": upper_right[1]},
                    color="red",
                    tooltip=f"Upper-Right (NE): {upper_right[0]:.4f}, {upper_right[1]:.4f}",
                    popup=(
                        f"<b>Bounding Box - Upper-Right (NE)</b><br>"
                        f"LAT: {upper_right[0]:.4f}°<br>"
                        f"LNG: {upper_right[1]:.4f}°<br>"
                        f"Query: {user_query}"
                    )
                ),
                MapLayer(
                    name=f"Bounding Box Area [{lower_left[0]:.3f}, {lower_left[1]:.3f}]-[{upper_right[0]:.3f}, {upper_right[1]:.3f}]",
                    layer_type="polygon",
                    data={"coordinates": bbox_coords},
                    color="orange",
                    tooltip=f"Bounding Box Area: {user_query[:25]}...",
                    popup=(
                        f"<b>Bounding Box Sector</b><br>"
                        f"<b>Lower-Left (SW):</b> {lower_left[0]:.4f}°, {lower_left[1]:.4f}°<br>"
                        f"<b>Upper-Right (NE):</b> {upper_right[0]:.4f}°, {upper_right[1]:.4f}°<br>"
                        f"<b>Query:</b> {user_query}"
                    )
                )
            ]
            return AgentResponse(answer=answer_text, layers=layers)
        else:
            answer_text = (
                f"### 📦 Bounding Box Reconnaissance Summary\n\n"
                f"**Sector Extents (Two-Point Box):**\n"
                f"- **Lower-Left (SW):** `{lower_left[0]:.4f}° N, {lower_left[1]:.4f}° E`\n"
                f"- **Upper-Right (NE):** `{upper_right[0]:.4f}° N, {upper_right[1]:.4f}° E`\n\n"
                f"- **Bounded Span:** Latitude `{lower_left[0]:.4f}°` to `{upper_right[0]:.4f}°`, "
                f"Longitude `{lower_left[1]:.4f}°` to `{upper_right[1]:.4f}°`.\n"
                f"- **Relevance Score:** 0.93 (High confidence boundary containment match).\n"
                f"- **Situation Summary:** Tactical surveillance sweep across the defined bounding box complete. "
                f"You can now submit targeted prompts in the chat to analyze units, logistics corridors, or assets within this box."
            )
            layers = [
                MapLayer(
                    name=f"Box Lower-Left ({lower_left[0]:.3f}, {lower_left[1]:.3f})",
                    layer_type="marker",
                    data={"lat": lower_left[0], "lng": lower_left[1]},
                    color="purple",
                    tooltip=f"Lower-Left (SW): {lower_left[0]:.4f}, {lower_left[1]:.4f}",
                    popup=(
                        f"<b>Bounding Box - Lower-Left (SW)</b><br>"
                        f"LAT: {lower_left[0]:.4f}°<br>"
                        f"LNG: {lower_left[1]:.4f}°"
                    )
                ),
                MapLayer(
                    name=f"Box Upper-Right ({upper_right[0]:.3f}, {upper_right[1]:.3f})",
                    layer_type="marker",
                    data={"lat": upper_right[0], "lng": upper_right[1]},
                    color="purple",
                    tooltip=f"Upper-Right (NE): {upper_right[0]:.4f}, {upper_right[1]:.4f}",
                    popup=(
                        f"<b>Bounding Box - Upper-Right (NE)</b><br>"
                        f"LAT: {upper_right[0]:.4f}°<br>"
                        f"LNG: {upper_right[1]:.4f}°"
                    )
                ),
                MapLayer(
                    name=f"Bounding Box Area ({lower_left[0]:.3f}, {lower_left[1]:.3f})",
                    layer_type="polygon",
                    data={"coordinates": bbox_coords},
                    color="purple",
                    tooltip="Bounding Box Reconnaissance Zone",
                    popup=(
                        f"<b>Reconnaissance Bounding Box</b><br>"
                        f"SW: {lower_left[0]:.4f}°, {lower_left[1]:.4f}°<br>"
                        f"NE: {upper_right[0]:.4f}°, {upper_right[1]:.4f}°"
                    )
                )
            ]
            return AgentResponse(answer=answer_text, layers=layers)

    # Consolidate target coordinate(s) from selected_point (or backwards-compatible kwargs)
    points: List[Tuple[float, float]] = []
    if selected_point:
        if isinstance(selected_point, (list, tuple)) and len(selected_point) > 0:
            if isinstance(selected_point[0], (int, float)):
                # Single (lat, lng) coordinate tuple
                points = [selected_point]  # type: ignore
            elif isinstance(selected_point[0], (list, tuple)):
                # List of coordinate tuples
                points = [p for p in selected_point if len(p) == 2]
    elif kwargs.get("selected_points"):
        points = [p for p in kwargs["selected_points"] if len(p) == 2]
    elif kwargs.get("clicked_point"):
        points = [kwargs["clicked_point"]]

    has_point = len(points) > 0

    # --------------------------------------------------------------------------
    # Scenario A: Both text prompt AND point(s) are present
    # --------------------------------------------------------------------------
    if has_text and has_point:
        user_query = text_prompt.strip()

        if len(points) == 1:
            lat, lng = points[0][0], points[0][1]
            answer_text = (
                f"### 🎯 Targeted Point Analysis\n\n"
                f"**Query Intent:** \"{user_query}\"\n\n"
                f"**Target Coordinates:** `{lat:.4f}° N, {lng:.4f}° E`\n\n"
                f"**Tactical Assessment:** Geospatial intelligence scan at this location reveals "
                f"localized activity aligned with your inquiry. Terrain profile indicates moderate "
                f"elevation with primary transit corridors within a 15 km buffer. "
                f"Cross-referencing spatial databases for *\"{user_query}\"* indicates operational "
                f"assets and communication relays active in this sector."
            )

            layers = [
                MapLayer(
                    name=f"Target: {lat:.3f}, {lng:.3f}",
                    layer_type="marker",
                    data={"lat": lat, "lng": lng},
                    color="red",
                    tooltip=f"Query Focus: {user_query[:30]}...",
                    popup=(
                        f"<b>Query:</b> {user_query}<br>"
                        f"<b>Coordinates:</b> {lat:.4f}, {lng:.4f}<br>"
                        f"<b>Status:</b> Active Intelligence Focus"
                    )
                ),
                MapLayer(
                    name=f"Perimeter Buffer ({lat:.3f}, {lng:.3f})",
                    layer_type="circle",
                    data={"lat": lat, "lng": lng, "radius": 15000},  # 15km tactical radius
                    color="orange",
                    tooltip=f"15km Reconnaissance Zone",
                    popup=f"Zone Radius: 15 km centered around ({lat:.4f}, {lng:.4f})"
                )
            ]
            return AgentResponse(answer=answer_text, layers=layers)
        else:
            coords_md = "\n".join([f"- **Point {i+1}:** `{p[0]:.4f}° N, {p[1]:.4f}° E`" for i, p in enumerate(points)])
            answer_text = (
                f"### 🎯 Multi-Target Analysis ({len(points)} Locations)\n\n"
                f"**Query Intent:** \"{user_query}\"\n\n"
                f"**Target Coordinates:**\n{coords_md}\n\n"
                f"**Tactical Assessment:** Geospatial intelligence scan across all {len(points)} selected coordinates "
                f"correlating tactical data with *\"{user_query}\"*. Spatial correlation indicates active transit corridors "
                f"and operational linkages between target sectors with 15 km tactical perimeter zones."
            )

            layers = []
            for i, (plat, plng) in enumerate(points, start=1):
                layers.append(
                    MapLayer(
                        name=f"Target #{i}: {plat:.3f}, {plng:.3f}",
                        layer_type="marker",
                        data={"lat": plat, "lng": plng},
                        color="red",
                        tooltip=f"Target #{i}: {user_query[:25]}...",
                        popup=(
                            f"<b>Target #{i}</b><br>"
                            f"<b>Query:</b> {user_query}<br>"
                            f"<b>Coordinates:</b> {plat:.4f}, {plng:.4f}<br>"
                            f"<b>Status:</b> Active Multi-Target Focus"
                        )
                    )
                )
                layers.append(
                    MapLayer(
                        name=f"Buffer #{i} ({plat:.3f}, {plng:.3f})",
                        layer_type="circle",
                        data={"lat": plat, "lng": plng, "radius": 15000},
                        color="orange",
                        tooltip=f"15km Recon Zone #{i}",
                        popup=f"Zone #{i} Radius: 15 km centered around ({plat:.4f}, {plng:.4f})"
                    )
                )
            return AgentResponse(answer=answer_text, layers=layers)

    # --------------------------------------------------------------------------
    # Scenario B: Only point(s) are present (reconnaissance scan)
    # --------------------------------------------------------------------------
    if has_point and not has_text:
        if len(points) == 1:
            lat, lng = points[0][0], points[0][1]
            answer_text = (
                f"### 📍 Location Reconnaissance Summary\n\n"
                f"**Sector Coordinates:** `{lat:.4f}° N, {lng:.4f}° E`\n\n"
                f"- **Topography:** Lowland plain with agricultural infrastructure.\n"
                f"- **Geodetic Grid:** UTM Zone 36N.\n"
                f"- **Relevance Score:** 0.87 (High confidence spatial match).\n"
                f"- **Situation Summary:** This sector is currently active in the geocoded registry. "
                f"You can now submit follow-up prompts in the chat (e.g., *'What units are stationed here?'* "
                f"or *'Show logistics supply lines'*) to perform contextual spatial retrieval on this point."
            )

            layers = [
                MapLayer(
                    name=f"Sector Pin ({lat:.3f}, {lng:.3f})",
                    layer_type="marker",
                    data={"lat": lat, "lng": lng},
                    color="purple",
                    tooltip=f"Sector: {lat:.4f}, {lng:.4f}",
                    popup=f"<b>Sector Coordinates:</b><br>{lat:.4f}° N, {lng:.4f}° E<br><i>Ready for targeted queries</i>"
                ),
                MapLayer(
                    name=f"Recon Zone ({lat:.3f}, {lng:.3f})",
                    layer_type="circle",
                    data={"lat": lat, "lng": lng, "radius": 8000},  # 8km recon circle
                    color="purple",
                    tooltip="Local 8km Inspection Area",
                    popup="8km radius inspection zone"
                )
            ]
            return AgentResponse(answer=answer_text, layers=layers)
        else:
            coords_md = "\n".join([f"- **Sector {i+1}:** `{p[0]:.4f}° N, {p[1]:.4f}° E`" for i, p in enumerate(points)])
            answer_text = (
                f"### 📍 Multi-Location Reconnaissance Summary ({len(points)} Sectors)\n\n"
                f"**Target Sectors:**\n{coords_md}\n\n"
                f"- **Relevance Score:** 0.91 (High confidence cluster match).\n"
                f"- **Situation Summary:** Reconnaissance scan across all {len(points)} sectors complete. "
                f"You can now submit targeted prompts in the chat to analyze strategic relations between these positions."
            )

            layers = []
            for i, (plat, plng) in enumerate(points, start=1):
                layers.append(
                    MapLayer(
                        name=f"Sector Pin #{i} ({plat:.3f}, {plng:.3f})",
                        layer_type="marker",
                        data={"lat": plat, "lng": plng},
                        color="purple",
                        tooltip=f"Sector #{i}: {plat:.4f}, {plng:.4f}",
                        popup=f"<b>Sector #{i} Coordinates:</b><br>{plat:.4f}° N, {plng:.4f}° E"
                    )
                )
                layers.append(
                    MapLayer(
                        name=f"Recon Zone #{i} ({plat:.3f}, {plng:.3f})",
                        layer_type="circle",
                        data={"lat": plat, "lng": plng, "radius": 8000},
                        color="purple",
                        tooltip=f"Local 8km Inspection Area #{i}",
                        popup=f"8km radius inspection zone #{i}"
                    )
                )
            return AgentResponse(answer=answer_text, layers=layers)

    # --------------------------------------------------------------------------
    # Scenario C: Only text prompt is present (general spatial question)
    # --------------------------------------------------------------------------
    if has_text and not has_point:
        query_clean = text_prompt.strip()

        # Generate dummy strategic points of interest in Ukraine
        mock_poi_layers = [
            MapLayer(
                name="Sector Alpha (Kyiv)",
                layer_type="marker",
                data={"lat": 50.4501, "lng": 30.5234},
                color="blue",
                tooltip="Kyiv Hub",
                popup="<b>Kyiv Operations Hub</b><br>Administrative & Logistical Center"
            ),
            MapLayer(
                name="Sector Bravo (Kharkiv)",
                layer_type="marker",
                data={"lat": 49.9935, "lng": 36.2304},
                color="green",
                tooltip="Kharkiv Sector",
                popup="<b>Kharkiv Sector</b><br>Eastern Industrial & Transit Hub"
            ),
            MapLayer(
                name="Sector Charlie (Dnipro)",
                layer_type="marker",
                data={"lat": 48.4647, "lng": 35.0462},
                color="darkblue",
                tooltip="Dnipro Corridor",
                popup="<b>Dnipro Hub</b><br>Central Logistics Depot"
            ),
            MapLayer(
                name="Regional Operations Zone",
                layer_type="circle",
                data={"lat": 48.4647, "lng": 35.0462, "radius": 25000},  # 25km radius
                color="cadetblue",
                tooltip="25km Central Logistics Buffer",
                popup="Dnipro Defense & Logistics Buffer"
            )
        ]

        answer_text = (
            f"### 🌐 General Spatial Intelligence Synthesis\n\n"
            f"**Inquiry:** \"{query_clean}\"\n\n"
            f"**Regional Overview:** In response to your general spatial query, the system retrieved "
            f"data across central and eastern operational corridors. Key strategic nodes in Kyiv, "
            f"Kharkiv, and Dnipro have been plotted on your map layer with relevant intelligence tags.\n\n"
            f"💡 **Interactive Tip:** Click anywhere on the map to pin a specific coordinate, "
            f"then ask a follow-up question to run a localized pinpoint analysis."
        )
        return AgentResponse(answer=answer_text, layers=mock_poi_layers)

    # --------------------------------------------------------------------------
    # Fallback / Empty Input Scenario
    # --------------------------------------------------------------------------
    fallback_text = (
        "### 🌍 GeoAI Agent Ready\n\n"
        "Please provide a prompt or click any location on the map to initiate a spatial intelligence query."
    )
    return AgentResponse(answer=fallback_text, layers=[])
