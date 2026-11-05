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
import re
import logging
import functools
import concurrent.futures
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

__all__ = [
    "MapLayer",
    "AgentResponse",
    "to_bounding_box",
    "get_source_text",
    "extract_answer_subgraph",
    "get_agent_env_path",
    "persist_openrouter_api_key",
    "format_evidence_popup_html",
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
_DISCOVERED_AGENT_DIR: Optional[Path] = None

# Attempt to locate AgentRag dynamically
_current_dir = Path(__file__).resolve().parent
_potential_agent_dirs = [
    _current_dir.parent / "AgentRag",                             # Inside Corpus2GeoRAG repository (standard layout)
    _current_dir.parent,                                          # AgentRag/ui_mvp: the agent is the parent folder
    _current_dir / "AgentRag",                                    # Local vendored copy
    _current_dir.parent / "Corpus2GeoRAG" / "AgentRag",           # Sibling project directory
    _current_dir.parent.parent / "Corpus2GeoRAG" / "AgentRag",    # Sibling repository from nested sandbox or ui subfolder
    _current_dir.parent.parent / "AgentRag",                      # Parent root from nested subfolder
]
if "AGENT_RAG_PATH" in os.environ:
    _potential_agent_dirs.insert(0, Path(os.environ["AGENT_RAG_PATH"]))

for _p in _potential_agent_dirs:
    if (_p / "georag_agent.py").is_file():
        _DISCOVERED_AGENT_DIR = _p
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
    map_showing: str = "all"
    map_not_shown: int = 0
    follow_ups: List[str] = field(default_factory=list)
    regions: Any = field(default_factory=list)
    did_you_mean: Any = field(default_factory=list)
    subgraph: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.answer_plain:
            self.answer_plain = self.answer


# ==============================================================================
# 2. Bounding Box & Source Utilities
# ==============================================================================

def get_agent_env_path() -> Optional[Path]:
    """
    Locate the AgentRag/.env file used by RUN_GEORAG.bat / AgentRag/launch.py.
    Returns the Path to AgentRag/.env if the AgentRag directory exists, else None.
    """
    candidates: List[Path] = []
    if "AGENT_RAG_PATH" in os.environ:
        candidates.append(Path(os.environ["AGENT_RAG_PATH"]))
    if _DISCOVERED_AGENT_DIR is not None:
        candidates.append(_DISCOVERED_AGENT_DIR)
    candidates.extend(_potential_agent_dirs)

    for cand in candidates:
        try:
            if cand.is_dir() and ((cand / "georag_agent.py").is_file() or (cand / "launch.py").is_file()):
                return cand / ".env"
        except Exception:
            continue
    return None


def persist_openrouter_api_key(
    api_key: Optional[str],
    update_dotenv: bool = True,
    env_path: Optional[Path] = None,
) -> bool:
    """
    Update OPENROUTER_API_KEY in the active process environment (os.environ) and optionally
    persist it to AgentRag/.env so subsequent launches via RUN_GEORAG.bat use the new key.

    When api_key is empty/None, removes OPENROUTER_API_KEY from os.environ (and from AgentRag/.env
    if update_dotenv is True) so the app cleanly enters Offline Simulation (Mock) mode.
    Returns True if AgentRag/.env was updated on disk, False otherwise.
    """
    cleaned = (api_key or "").strip().strip("'\"")
    key_name = "OPENROUTER_API_KEY"

    if cleaned:
        os.environ[key_name] = cleaned
    else:
        os.environ.pop(key_name, None)

    if not update_dotenv:
        return False

    target_env = env_path or get_agent_env_path()
    if target_env is None or not target_env.parent.is_dir():
        return False

    try:
        lines = target_env.read_text(encoding="utf-8-sig").splitlines() if target_env.is_file() else []
        lines = [ln for ln in lines if ln.partition("=")[0].strip() != key_name]
        if cleaned:
            lines.append(f"{key_name}={cleaned}")
        content = ("\n".join(lines) + "\n") if lines else ""
        target_env.write_text(content, encoding="utf-8")
        return True
    except Exception as exc:
        logger.warning("Could not persist %s to %s: %s", key_name, target_env, exc)
        return False


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


def extract_answer_subgraph(
    response_or_msg: Optional[Any] = None,
    *,
    raw_response: Optional[Dict[str, Any]] = None,
    sources: Optional[List[str]] = None,
    citations: Optional[List[Dict[str, Any]]] = None,
    layers: Optional[List[Any]] = None,
    regions: Optional[Any] = None,
    answer_text: Optional[str] = None,
    nx_graph: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Extract an induced knowledge subgraph (nodes and edges) containing strictly the
    locations (LOC), organizations (ORG), persons (PER), and source passages (TEXT)
    that grounded a specific RAG answer.

    Returns:
        Dict[str, Any]: {"nodes": [...], "edges": [...]}
    """
    if isinstance(response_or_msg, AgentResponse):
        raw_response = raw_response if raw_response is not None else (response_or_msg.raw_response or {})
        sources = sources if sources is not None else list(response_or_msg.sources or [])
        citations = citations if citations is not None else list(response_or_msg.citations or [])
        layers = layers if layers is not None else list(response_or_msg.layers or [])
        regions = regions if regions is not None else response_or_msg.regions
        answer_text = answer_text if answer_text is not None else (response_or_msg.answer_plain or response_or_msg.answer or "")
    elif isinstance(response_or_msg, dict):
        if "subgraph" in response_or_msg and isinstance(response_or_msg["subgraph"], dict):
            existing = response_or_msg["subgraph"]
            if existing.get("nodes"):
                return existing
        raw_response = raw_response if raw_response is not None else (response_or_msg.get("raw_response") or response_or_msg)
        sources = sources if sources is not None else list(response_or_msg.get("sources") or [])
        citations = citations if citations is not None else list(response_or_msg.get("citations") or [])
        layers = layers if layers is not None else list(response_or_msg.get("layers") or [])
        regions = regions if regions is not None else response_or_msg.get("regions")
        answer_text = (
            answer_text
            if answer_text is not None
            else (
                response_or_msg.get("content_plain")
                or response_or_msg.get("answer_plain")
                or response_or_msg.get("content")
                or response_or_msg.get("answer")
                or ""
            )
        )

    raw_response = raw_response if isinstance(raw_response, dict) else {}
    sources = list(sources or raw_response.get("sources") or [])
    citations = list(citations or raw_response.get("citations") or [])
    layers = list(layers or [])
    regions = regions if regions is not None else raw_response.get("regions")
    answer_text = str(answer_text or raw_response.get("answer_plain") or raw_response.get("answer") or "")

    nodes_by_id: Dict[str, Dict[str, Any]] = {}
    edges_by_key: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

    def _add_node(
        node_id: str,
        label: str,
        ntype: str,
        role: str = "entity",
        subtitle: str = "",
        summary: str = "",
        evidence: str = "",
        pin_number: Optional[int] = None,
    ) -> None:
        nid = str(node_id).strip()
        if not nid:
            return
        if nid in nodes_by_id:
            existing = nodes_by_id[nid]
            if pin_number is not None and existing.get("pin_number") is None:
                existing["pin_number"] = pin_number
                existing["label"] = label
            if role == "primary" and existing.get("role") != "primary":
                existing["role"] = "primary"
            if subtitle and not existing.get("subtitle"):
                existing["subtitle"] = subtitle
            if summary and not existing.get("summary"):
                existing["summary"] = summary
            if evidence and not existing.get("evidence"):
                existing["evidence"] = evidence
            return
        nodes_by_id[nid] = {
            "id": nid,
            "label": str(label or nid),
            "type": ntype if ntype in ("LOC", "ORG", "PER", "TEXT") else "LOC",
            "role": role,
            "subtitle": str(subtitle or ""),
            "summary": str(summary or ""),
            "evidence": str(evidence or ""),
            "pin_number": pin_number,
        }

    def _add_edge(u: str, v: str, label: str, kind: str = "relation") -> None:
        u_id, v_id = str(u).strip(), str(v).strip()
        if not u_id or not v_id or u_id == v_id:
            return
        lbl = str(label or "related").strip()
        # Avoid duplicate undirected pairs with identical label
        rev_key = (v_id, u_id, lbl)
        if rev_key in edges_by_key and kind != "hierarchy":
            return
        key = (u_id, v_id, lbl)
        if key not in edges_by_key:
            edges_by_key[key] = {
                "from": u_id,
                "to": v_id,
                "label": lbl,
                "kind": kind,
            }

    # 1. Build citation lookup and active TEXT_* pointers
    tag_by_ptr: Dict[str, str] = {}
    cit_by_ptr: Dict[str, Dict[str, Any]] = {}
    for c in citations:
        if isinstance(c, dict) and c.get("pointer"):
            ptr = str(c["pointer"])
            cit_by_ptr[ptr] = c
            if c.get("id"):
                tag_by_ptr[ptr] = str(c["id"])

    active_text_ptrs: List[str] = []
    seen_ptrs = set()
    for ptr in sources:
        if isinstance(ptr, str) and ptr.startswith("TEXT_") and ptr not in seen_ptrs:
            seen_ptrs.add(ptr)
            active_text_ptrs.append(ptr)
            if len(active_text_ptrs) >= 12:
                break

    for c in citations:
        if isinstance(c, dict):
            ptr = c.get("pointer")
            if isinstance(ptr, str) and ptr.startswith("TEXT_") and ptr not in seen_ptrs and len(active_text_ptrs) < 12:
                seen_ptrs.add(ptr)
                active_text_ptrs.append(ptr)

    # 2. Extract LOC nodes from geo_locations (capped to keep subgraph legible)
    geo_locs = [loc for loc in (raw_response.get("geo_locations") or []) if isinstance(loc, dict)]

    # 2a. Session-state recovery if response_or_msg was an unhydrated message dictionary
    if not geo_locs:
        try:
            import streamlit as _st
            for turn in reversed(_st.session_state.get("agent_turns", [])):
                resp_d = (turn.get("response") or {}) if isinstance(turn, dict) else {}
                if resp_d.get("geo_locations"):
                    t_sources = set(resp_d.get("sources", []))
                    if not sources or (t_sources & set(sources)):
                        geo_locs = resp_d.get("geo_locations") or []
                        raw_response = resp_d
                        break
            if not geo_locs:
                for log_e in reversed(_st.session_state.get("rag_logs", [])):
                    resp_d = (log_e.get("raw_response") or {}) if isinstance(log_e, dict) else {}
                    if resp_d.get("geo_locations"):
                        t_sources = set(resp_d.get("sources", []))
                        if not sources or (t_sources & set(sources)):
                            geo_locs = resp_d.get("geo_locations") or []
                            raw_response = resp_d
                            break
        except Exception:
            pass

    primary_locs = [loc for loc in geo_locs if loc.get("role", "primary") != "context"]
    context_locs = [loc for loc in geo_locs if loc.get("role") == "context"]
    selected_locs = primary_locs[:12] + context_locs[: max(0, min(6, 14 - len(primary_locs[:12])))]

    loc_id_by_pin: Dict[int, str] = {}
    loc_sources_map: Dict[str, List[str]] = {}

    for loc in selected_locs:
        loc_id = str(loc.get("id") or loc.get("name") or loc.get("label") or "").strip()
        if not loc_id:
            continue
        loc_label = str(loc.get("label") or loc.get("name") or loc_id).strip()
        pin_num = loc.get("number")
        role = str(loc.get("role") or "primary")
        kind = str(loc.get("kind") or "place")
        why = str(loc.get("why") or "").strip()
        uncertain = loc.get("uncertain")

        geom = loc.get("geometry") if isinstance(loc.get("geometry"), dict) else {}
        coords = geom.get("coordinates") if isinstance(geom.get("coordinates"), (list, tuple)) else []
        coord_str = ""
        if len(coords) >= 2:
            try:
                coord_str = f"{float(coords[1]):.4f}° N, {float(coords[0]):.4f}° E"
            except (TypeError, ValueError):
                coord_str = ""
        elif "lat" in loc and ("lng" in loc or "lon" in loc):
            try:
                lat_v = float(loc["lat"])
                lon_v = float(loc.get("lng", loc.get("lon")))
                coord_str = f"{lat_v:.4f}° N, {lon_v:.4f}° E"
            except (TypeError, ValueError):
                coord_str = ""

        disp_label = f"#{pin_num} {loc_label}" if pin_num is not None else loc_label
        subtitle_parts = [p for p in [coord_str, f"{kind.upper()} ({role})"] if p]
        loc_srcs = [s for s in (loc.get("sources") or []) if isinstance(s, str)]
        loc_sources_map[loc_id] = loc_srcs

        for s_idx, s_ptr in enumerate(loc_srcs[:3]):
            if s_ptr.startswith("TEXT_"):
                if s_ptr not in tag_by_ptr:
                    tag_by_ptr[s_ptr] = f"P{pin_num}-S{s_idx + 1}" if pin_num is not None else f"S{len(tag_by_ptr) + 1}"
                if s_ptr not in seen_ptrs and len(active_text_ptrs) < 12:
                    seen_ptrs.add(s_ptr)
                    active_text_ptrs.append(s_ptr)

        summary_str = f"{'Primary focal' if role != 'context' else 'Context'} {kind} node in the answer."
        if uncertain:
            summary_str += f" (Uncertain: {uncertain})"
        evidence_str = why if why else (
            f"Grounded by {len(loc_srcs)} source passage(s)." if loc_srcs else "Identified in spatial query response."
        )

        _add_node(
            node_id=loc_id,
            label=disp_label,
            ntype="LOC",
            role="primary" if role != "context" else "context",
            subtitle=" • ".join(subtitle_parts),
            summary=summary_str,
            evidence=evidence_str,
            pin_number=pin_num if isinstance(pin_num, int) else None,
        )
        if isinstance(pin_num, int):
            loc_id_by_pin[pin_num] = loc_id

    # 2b. Extract cited locations from citations if geo_locations was sparse
    for c in citations:
        if isinstance(c, dict) and c.get("place_label"):
            p_lbl = str(c["place_label"]).strip()
            p_num = c.get("place_number")
            if p_lbl and p_lbl not in nodes_by_id:
                disp_lbl = f"#{p_num} {p_lbl}" if p_num is not None else p_lbl
                _add_node(
                    node_id=p_lbl,
                    label=disp_lbl,
                    ntype="LOC",
                    role="primary",
                    subtitle="Cited Place",
                    summary=f"Location cited in answer evidence ({f'Pin #{p_num}' if p_num is not None else ''}).",
                    evidence=f"Grounds citation [{c.get('id', '')}].",
                    pin_number=p_num if isinstance(p_num, int) else None,
                )
                if isinstance(p_num, int):
                    loc_id_by_pin[p_num] = p_lbl

    # Fallback to MapLayer markers if geo_locations was empty (e.g. Mock mode)
    if not nodes_by_id and layers:
        for idx, ly in enumerate(layers):
            l_type = getattr(ly, "layer_type", None) or (ly.get("layer_type") if isinstance(ly, dict) else None)
            l_name = getattr(ly, "name", None) or (ly.get("name") if isinstance(ly, dict) else f"Layer {idx + 1}")
            l_data = getattr(ly, "data", None) or (ly.get("data") if isinstance(ly, dict) else {})
            l_tooltip = getattr(ly, "tooltip", "") or (ly.get("tooltip", "") if isinstance(ly, dict) else "")
            if not isinstance(l_data, dict):
                continue
            if l_type == "marker" and "lat" in l_data and "lng" in l_data:
                role = str(l_data.get("role") or "primary")
                lat_v, lng_v = float(l_data["lat"]), float(l_data["lng"])
                nid = str(l_data.get("id") or l_name)
                _add_node(
                    node_id=nid,
                    label=str(l_name),
                    ntype="LOC",
                    role="context" if role == "context" else "primary",
                    subtitle=f"{lat_v:.4f}° N, {lng_v:.4f}° E",
                    summary=f"Spatial marker layer ({role}).",
                    evidence=str(l_tooltip or f"Plotted at ({lat_v:.4f}°, {lng_v:.4f}°)."),
                    pin_number=l_data.get("number"),
                )

    # 3. Extract regional hierarchy (INSIDE edges) from `regions`
    if isinstance(regions, list):
        for reg in regions[:6]:
            if not isinstance(reg, dict) or not reg.get("id"):
                continue
            r_id = str(reg["id"])
            r_type = str(reg.get("place_type") or "region")
            r_cnt = reg.get("count", 0)
            r_places = [p for p in (reg.get("places") or []) if isinstance(p, int)]
            children = [c for c in (reg.get("children") or []) if isinstance(c, dict) and c.get("id")]

            # Include region if it contains any displayed pin, if few regions exist, or if no LOC nodes exist yet
            has_matched_pin = any(p in loc_id_by_pin for p in r_places) or any(
                any(cp in loc_id_by_pin for cp in (c.get("places") or [])) for c in children
            )
            has_other_locs = any(nd["type"] == "LOC" and nd["role"] != "region" for nd in nodes_by_id.values())
            if not has_matched_pin and len(regions) > 4 and has_other_locs:
                continue

            _add_node(
                node_id=r_id,
                label=r_id,
                ntype="LOC",
                role="region",
                subtitle=f" Hierarchy ({r_type.upper()})",
                summary=f"Administrative parent region containing {r_cnt} place(s) in this result.",
                evidence=f"Regional container for pins: {', '.join(f'#{p}' for p in r_places[:8])}" if r_places else "Administrative container.",
            )
            child_covered_pins = set()
            for child in children[:6]:
                c_id = str(child["id"])
                c_type = str(child.get("place_type") or "region")
                c_cnt = child.get("count", 0)
                c_places = [p for p in (child.get("places") or []) if isinstance(p, int)]
                if not any(p in loc_id_by_pin for p in c_places) and len(children) > 3:
                    continue
                _add_node(
                    node_id=c_id,
                    label=c_id,
                    ntype="LOC",
                    role="region",
                    subtitle=f"Hierarchy ({c_type.upper()})",
                    summary=f"Sub-region inside {r_id} ({c_cnt} place(s)).",
                    evidence=f"Contains pins: {', '.join(f'#{p}' for p in c_places[:8])}" if c_places else f"Part of {r_id}.",
                )
                _add_edge(c_id, r_id, "INSIDE", kind="hierarchy")
                for p_num in c_places:
                    if p_num in loc_id_by_pin:
                        child_covered_pins.add(p_num)
                        _add_edge(loc_id_by_pin[p_num], c_id, "INSIDE", kind="hierarchy")

            for p_num in r_places:
                if p_num in loc_id_by_pin and p_num not in child_covered_pins:
                    _add_edge(loc_id_by_pin[p_num], r_id, "INSIDE", kind="hierarchy")

    # 4. Enrich with in-memory NetworkX knowledge graph (if loaded)
    active_text_ids = set()
    for ptr in active_text_ptrs:
        tid_str = ptr.removeprefix("TEXT_")
        if tid_str.isdigit():
            active_text_ids.add(int(tid_str))

    G = nx_graph
    if G is None:
        georag_mod = sys.modules.get("georag_agent")
        gi = getattr(georag_mod, "_graph", None) if georag_mod is not None else None
        if gi is not None and hasattr(gi, "G"):
            G = gi.G

    if G is not None:
        try:
            current_loc_ids = [nid for nid, nd in list(nodes_by_id.items()) if nd["type"] == "LOC"]
            ans_lower = answer_text.lower()
            added_entities = 0

            # 4a. Check direct edges between already-selected LOC nodes and their INSIDE parents or co-cited entities
            for loc_id in current_loc_ids:
                if loc_id not in G:
                    continue
                for nbr in G.neighbors(loc_id):
                    nbr_data = G.nodes[nbr]
                    nbr_type = nbr_data.get("type")
                    if nbr_type == "TEXT":
                        continue
                    edge_data = G[loc_id][nbr]
                    rels = edge_data.get("relations") or {}

                    # Check INSIDE parent in graph
                    if "INSIDE" in rels:
                        for r_rec in rels["INSIDE"]:
                            if isinstance(r_rec, dict) and r_rec.get("subject") == loc_id:
                                if nbr not in nodes_by_id and len(nodes_by_id) < 28:
                                    _add_node(
                                        node_id=nbr,
                                        label=nbr,
                                        ntype="LOC",
                                        role="region",
                                        subtitle=str(nbr_data.get("place_type") or "region").upper(),
                                        summary=f"Administrative parent of {loc_id} in the knowledge graph.",
                                        evidence=f"{loc_id} is located INSIDE {nbr}.",
                                    )
                                if nbr in nodes_by_id:
                                    _add_edge(loc_id, nbr, "INSIDE", kind="hierarchy")

                    # Check semantic relations backed by the answer's TEXT_ paragraphs (or between two selected nodes)
                    for rel_name, recs in rels.items():
                        if rel_name == "INSIDE" or not isinstance(recs, list):
                            continue
                        matched_recs = [
                            r for r in recs
                            if isinstance(r, dict) and (
                                r.get("text_id") in active_text_ids
                                or (not active_text_ids and len(str(nbr)) >= 3 and str(nbr).lower() in ans_lower)
                            )
                        ]
                        if matched_recs or nbr in nodes_by_id:
                            if nbr not in nodes_by_id:
                                if added_entities >= 10:
                                    continue
                                added_entities += 1
                                sample_rec = matched_recs[0] if matched_recs else (recs[0] if recs else {})
                                ev_tid = sample_rec.get("text_id")
                                ev_ptr = f"TEXT_{ev_tid}" if ev_tid is not None else ""
                                _add_node(
                                    node_id=nbr,
                                    label=nbr,
                                    ntype=nbr_type if nbr_type in ("PER", "ORG", "LOC") else "ORG",
                                    role="entity",
                                    subtitle=f"{nbr_type or 'ENTITY'} Node",
                                    summary=f"Connected to {loc_id} via '{rel_name}' relation in the knowledge graph.",
                                    evidence=f"Relation: {sample_rec.get('subject', nbr)} —[{rel_name}]→ {sample_rec.get('object', loc_id)}"
                                    + (f" ({ev_ptr})" if ev_ptr else ""),
                                )
                            if nbr in nodes_by_id:
                                sample_rec = matched_recs[0] if matched_recs else (recs[0] if recs else {})
                                subj = sample_rec.get("subject") if isinstance(sample_rec, dict) else None
                                if subj == nbr:
                                    _add_edge(nbr, loc_id, rel_name, kind="relation")
                                else:
                                    _add_edge(loc_id, nbr, rel_name, kind="relation")
                                for mr in matched_recs[:2]:
                                    mtid = mr.get("text_id")
                                    mptr = f"TEXT_{mtid}" if mtid is not None else ""
                                    if mptr and mptr in seen_ptrs:
                                        tag = tag_by_ptr.get(mptr, mptr)
                                        _add_edge(nbr, mptr, f"cited_in [{tag}]", kind="provenance")

            # 4b. Check PER / ORG entities linked to the answer's TEXT_ nodes and mentioned in the answer text
            if ans_lower and added_entities < 10:
                for ptr in active_text_ptrs:
                    if ptr not in G:
                        continue
                    tag = tag_by_ptr.get(ptr, ptr)
                    for nbr in G.neighbors(ptr):
                        if added_entities >= 10:
                            break
                        nbr_data = G.nodes[nbr]
                        nbr_type = nbr_data.get("type")
                        if nbr_type in ("PER", "ORG") and len(str(nbr)) >= 3 and str(nbr).lower() in ans_lower:
                            if nbr not in nodes_by_id:
                                added_entities += 1
                                _add_node(
                                    node_id=nbr,
                                    label=nbr,
                                    ntype=nbr_type,
                                    role="entity",
                                    subtitle=f"{'Person (PER)' if nbr_type == 'PER' else 'Organization (ORG)'}",
                                    summary=f"Entity mentioned in the answer and grounded in [{tag}] ({ptr}).",
                                    evidence=f"Co-mentioned in paragraph {ptr}.",
                                )
                            _add_edge(nbr, ptr, f"cited_in [{tag}]", kind="provenance")
                            # Link to any existing nodes in our subgraph that share an edge in G
                            for existing_id in list(nodes_by_id.keys()):
                                if existing_id != nbr and existing_id != ptr and G.has_edge(nbr, existing_id):
                                    rels = G[nbr][existing_id].get("relations") or {}
                                    rel_lbl = next((k for k in rels.keys() if k != "INSIDE"), "co_mentioned")
                                    _add_edge(nbr, existing_id, rel_lbl, kind="relation")
        except Exception as exc:
            logger.debug("Subgraph enrichment from NetworkX G skipped: %s", exc)

    # 5. Add TEXT_* source passage nodes and provenance edges
    for s_idx, ptr in enumerate(active_text_ptrs):
        tag = tag_by_ptr.get(ptr) or f"S{s_idx + 1}"
        cit = cit_by_ptr.get(ptr, {})
        passage = get_source_text(ptr) or {}
        doc_title = str(passage.get("document") or cit.get("article") or ptr).replace("\ufffd", " - ").strip()
        sec_title = str(passage.get("section") or cit.get("section") or "").replace("\ufffd", " - ").strip()
        raw_txt = str(passage.get("text") or "").strip()
        snippet = (raw_txt[:240] + "...") if len(raw_txt) > 240 else (
            raw_txt or f"Verbatim corpus source passage {ptr} from '{doc_title}'."
        )
        short_doc = (doc_title[:20] + "…") if len(doc_title) > 21 else doc_title

        _add_node(
            node_id=ptr,
            label=f"[{tag}] {short_doc}",
            ntype="TEXT",
            role="source",
            subtitle=f"{ptr}" + (f" • § {sec_title}" if sec_title else ""),
            summary=f"Source passage [{tag}] from article '{doc_title}'" + (f" ({sec_title})" if sec_title else ""),
            evidence=snippet,
        )

        # Link from citation place_number / place_label if specified
        linked_any = False
        p_num = cit.get("place_number")
        if isinstance(p_num, int) and p_num in loc_id_by_pin:
            _add_edge(loc_id_by_pin[p_num], ptr, f"cited_in [{tag}]", kind="provenance")
            linked_any = True

        # Link from any selected LOC whose sources list includes ptr
        for loc_id, l_srcs in loc_sources_map.items():
            if ptr in l_srcs and loc_id in nodes_by_id:
                _add_edge(loc_id, ptr, f"cited_in [{tag}]", kind="provenance")
                linked_any = True

        # Link from G if available
        if G is not None and ptr in G:
            for existing_id, nd in list(nodes_by_id.items()):
                if nd["type"] != "TEXT" and existing_id in G and G.has_edge(existing_id, ptr):
                    _add_edge(existing_id, ptr, f"cited_in [{tag}]", kind="provenance")
                    linked_any = True

        # If this TEXT_ pointer is a general citation ([S1], [L1]) not yet tied to a specific pin, link to primary LOC(s)
        if not linked_any:
            prim_ids = [nid for nid, nd in nodes_by_id.items() if nd["type"] == "LOC" and nd["role"] == "primary"]
            for pid in prim_ids[:3]:
                _add_edge(pid, ptr, f"cited_in [{tag}]", kind="provenance")

    # 6. Ensure cohesive connectivity for Mock Mode / standalone spatial scans
    loc_nodes = [nid for nid, nd in nodes_by_id.items() if nd["type"] == "LOC"]
    text_nodes = [nid for nid, nd in nodes_by_id.items() if nd["type"] == "TEXT"]
    if loc_nodes and not edges_by_key:
        # Synthesize a grounding source node & operational hub if in Offline Mock mode
        synth_src_id = sources[0] if sources else "TEXT_MOCK_KB"
        if synth_src_id not in nodes_by_id:
            _add_node(
                node_id=synth_src_id,
                label="[S1] Spatial KB Feed",
                ntype="TEXT",
                role="source",
                subtitle="GeoAI Tactical Knowledge Base",
                summary="Grounding spatial intelligence record for this query.",
                evidence=answer_text[:220] + ("..." if len(answer_text) > 220 else ""),
            )
        for lid in loc_nodes:
            _add_edge(lid, synth_src_id, "grounded_by [S1]", kind="provenance")
        if len(loc_nodes) >= 2:
            for i in range(len(loc_nodes) - 1):
                _add_edge(loc_nodes[i], loc_nodes[i + 1], "tactical_corridor", kind="relation")
    elif len(loc_nodes) > 1 and not text_nodes:
        # Connect disconnected LOC components to the first primary LOC
        root_loc = loc_nodes[0]
        connected_ids = {e["from"] for e in edges_by_key.values()} | {e["to"] for e in edges_by_key.values()}
        for lid in loc_nodes[1:]:
            if lid not in connected_ids:
                _add_edge(lid, root_loc, "co_located_in_query", kind="relation")

    return {
        "nodes": list(nodes_by_id.values()),
        "edges": list(edges_by_key.values()),
    }


# ==============================================================================
# 3. GeoAI Routing Entrypoint (Adapter with Mock Fallback)
# ==============================================================================

_EVENT_DOC_TITLE_RE = re.compile(
    r"^(?:Battles?|Sieges?|Offensives?|Attacks?|Bombings?|Strikes?|Skirmish(?:es)?|Campaigns?|Invasions?|Occupation|Liberation|Capture|Fall|Defense|Defence|Massacres?|Raid|Assault)\s+(?:of|for|at|in|on)\s+",
    re.IGNORECASE,
)


def _is_event_article_title(title: Optional[str]) -> bool:
    """Return True if a knowledge graph document title represents a named battle, siege, or military event."""
    if not title or not str(title).strip():
        return False
    t = str(title).strip()
    if _EVENT_DOC_TITLE_RE.match(t):
        return True
    t_low = t.lower()
    return any(
        kw in t_low
        for kw in (
            "battle of ",
            "battles for ",
            "battles of ",
            "siege of ",
            "offensive",
            "counteroffensive",
            "strikes on ",
            "attack on ",
            "bombing of ",
        )
    )


def format_evidence_popup_html(
    why: Optional[str],
    sources_list: Optional[List[str]] = None,
) -> str:
    """
    Format place evidence string and source documents from the backend into rich tactical popup HTML.
    Handles P2-78 multi-event and battle list aggregations (e.g. 'event: Battle of Avdiivka (2017) in 28 records, ...')
    as well as battle/event articles discovered in `sources_list` (for `event_places` / `about` / `area_topic` routes),
    rendering distinct bulleted event entries with record/passage counts.
    """
    why_str = str(why).strip() if why else ""
    events: List[Tuple[str, Optional[str]]] = []
    seen_event_titles: set[str] = set()
    other_bits: List[str] = []

    if why_str:
        pieces = [p.strip() for p in why_str.replace(";", ",").split(",") if p.strip()]
        for piece in pieces:
            if piece.lower().startswith("event:"):
                ev_str = piece[6:].strip()
                match = re.match(r"^(.*?)(?:\s+in\s+(\d+\s+records?))?$", ev_str, re.IGNORECASE)
                if match:
                    title, count = match.groups()
                    clean_t = title.strip().replace("\ufffd", " - ")
                    if clean_t.lower() not in seen_event_titles:
                        seen_event_titles.add(clean_t.lower())
                        events.append((clean_t, count.strip() if count else None))
                else:
                    clean_t = ev_str.replace("\ufffd", " - ")
                    if clean_t.lower() not in seen_event_titles:
                        seen_event_titles.add(clean_t.lower())
                        events.append((clean_t, None))
            else:
                other_bits.append(piece)

    # Also inspect sources_list for battle/event article titles not already listed in `why`
    if sources_list:
        doc_counts: Dict[str, int] = {}
        for s_ptr in sources_list:
            s_text = get_source_text(s_ptr)
            doc_raw = s_text.get("document") if isinstance(s_text, dict) else None
            if doc_raw:
                doc_clean = str(doc_raw).replace("\ufffd", " - ").strip()
                if _is_event_article_title(doc_clean):
                    doc_counts[doc_clean] = doc_counts.get(doc_clean, 0) + 1
        for doc_title, cnt in doc_counts.items():
            if doc_title.lower() not in seen_event_titles:
                seen_event_titles.add(doc_title.lower())
                unit = "passage" if cnt == 1 else "passages"
                events.append((doc_title, f"{cnt} {unit}"))

    if events:
        ev_html_items = []
        for ev_title, ev_count in events:
            count_str = f" <span style='color:#94a3b8; font-size:0.85em;'>({ev_count})</span>" if ev_count else ""
            ev_html_items.append(f"<li style='margin-bottom:3px;'><b>⚔️ {ev_title}</b>{count_str}</li>")

        other_html = f"<div style='color:#94a3b8; font-size:0.85em; margin-top:4px;'><i>Evidence: {', '.join(other_bits)}</i></div>" if other_bits else ""
        return (
            f"<div style='margin-top:6px; padding-top:5px; border-top:1px solid rgba(255,255,255,0.15);'>"
            f"<b style='color:#f59e0b;'>⚔️ Associated Battles / Events ({len(events)}):</b>"
            f"<ul style='margin:3px 0 3px 14px; padding:0; list-style-type:none;'>"
            f"{' '.join(ev_html_items)}"
            f"</ul>"
            f"{other_html}"
            f"</div>"
        )

    if not why_str:
        return ""

    return (
        f"<div style='margin-top:6px; padding-top:5px; border-top:1px solid rgba(255,255,255,0.15); font-size:0.95em;'>"
        f"<b>Evidence:</b> {why_str}"
        f"</div>"
    )


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

        # 4. Invoke backend query with configurable timeout boundary
        timeout_sec = float(os.environ.get("GEOAI_BACKEND_TIMEOUT", "45.0"))
        try:
            if timeout_sec > 0:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(
                        _backend_query,
                        text_prompt=query_text,
                        geo_location=geo_location,
                        chat_history=turns,
                        api_key=effective_key
                    )
                    raw_result = future.result(timeout=timeout_sec)
            else:
                raw_result = _backend_query(
                    text_prompt=query_text,
                    geo_location=geo_location,
                    chat_history=turns,
                    api_key=effective_key
                )
        except concurrent.futures.TimeoutError:
            raise AgentError(f"GeoRAG backend query timed out after {timeout_sec:.1f}s")
        except Exception as e:
            if isinstance(e, AgentError):
                raise
            raise AgentError(f"Backend query execution failed: {e}") from e

        # 5. Build source and citation mappings with structured place tags (e.g. [P1-S1], [S1])
        raw_citations = list(raw_result.get("citations", []))
        tag_by_pointer: Dict[str, str] = {}
        for c in raw_citations:
            if isinstance(c, dict) and c.get("pointer") and c.get("id"):
                tag_by_pointer[c["pointer"]] = c["id"]

        def _select_diverse_place_sources(ptrs: List[str], limit: int = 3) -> List[Tuple[int, str]]:
            """Select up to `limit` (original_index, pointer) pairs prioritizing distinct article titles first."""
            if not ptrs:
                return []
            selected: List[Tuple[int, str]] = []
            seen_docs: set[str] = set()
            # Pass 1: first pointer from each distinct document
            for idx, ptr in enumerate(ptrs):
                s_info = get_source_text(ptr)
                doc_name = str(s_info.get("document") or ptr).strip() if isinstance(s_info, dict) else ptr
                if doc_name not in seen_docs:
                    seen_docs.add(doc_name)
                    selected.append((idx, ptr))
                    if len(selected) >= limit:
                        return selected
            # Pass 2: fill remaining slots in original order
            selected_indices = {i for i, _ in selected}
            for idx, ptr in enumerate(ptrs):
                if idx not in selected_indices:
                    selected.append((idx, ptr))
                    if len(selected) >= limit:
                        break
            return selected

        ans_text = raw_result.get("answer", "")
        top_sources = list(raw_result.get("sources", []))
        if not top_sources:
            # In Vr6, 'list' and 'place_lookup' answers store TEXT_ pointers on each place in geo_locations
            seen_ptrs = set()
            geo_locs = raw_result.get("geo_locations", [])
            for loc in geo_locs:
                if loc.get("role", "primary") == "primary" or len(geo_locs) <= 10:
                    for _, ptr in _select_diverse_place_sources(loc.get("sources", []), limit=3):
                        if ptr not in seen_ptrs:
                            seen_ptrs.add(ptr)
                            top_sources.append(ptr)
                        if len(top_sources) >= 15:
                            break
                if len(top_sources) >= 15:
                    break

        # Register place-source tags [P{pin}-S{idx}] so point info bubbles connect to grounding sources
        synthetic_citations: List[Dict[str, Any]] = []
        seen_synthetic_ptrs = set()

        for loc in raw_result.get("geo_locations", []):
            loc_num = loc.get("number")
            loc_label = loc.get("label") or loc.get("name") or loc.get("id") or ""
            for s_idx, s_ptr in enumerate(loc.get("sources", [])):
                if s_ptr not in tag_by_pointer:
                    if loc_num is not None:
                        tag = f"P{loc_num}-S{s_idx + 1}"
                    else:
                        tag = f"S{len(tag_by_pointer) + 1}"
                    tag_by_pointer[s_ptr] = tag

                if not raw_citations and s_ptr in top_sources and s_ptr not in seen_synthetic_ptrs:
                    seen_synthetic_ptrs.add(s_ptr)
                    text_data = get_source_text(s_ptr) or {}
                    synthetic_citations.append({
                        "id": tag_by_pointer[s_ptr],
                        "pointer": s_ptr,
                        "article": text_data.get("document", ""),
                        "section": text_data.get("section", ""),
                        "place_number": loc_num,
                        "place_label": loc_label,
                        "spans": []
                    })

        final_citations = raw_citations if raw_citations else synthetic_citations

        # 6. Hydrate MapLayers from backend geo_locations (converting [lon, lat] -> [lat, lon])
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

            why_html = format_evidence_popup_html(why, sources_list=sources_list)
            uncertain_html = f"<br><span style='color:#ff9800;'><b>⚠️ Uncertain:</b> {uncertain}</span>" if uncertain else ""
            src_html = ""
            if sources_list:
                src_lines = []
                diverse_sources = _select_diverse_place_sources(sources_list, limit=3)
                doc_freq: Dict[str, int] = {}
                for _, s_ptr in diverse_sources:
                    s_info = get_source_text(s_ptr)
                    d_name = str(s_info.get("document") or s_ptr).strip() if isinstance(s_info, dict) else s_ptr
                    doc_freq[d_name] = doc_freq.get(d_name, 0) + 1

                for s_idx, s_ptr in diverse_sources:
                    tag = tag_by_pointer.get(s_ptr)
                    if not tag:
                        tag = f"P{number}-S{s_idx + 1}" if number is not None else f"S{s_idx + 1}"
                    s_text = get_source_text(s_ptr)
                    if s_text and s_text.get("document"):
                        raw_doc = str(s_text["document"]).strip()
                        doc_clean = raw_doc.replace("\ufffd", " - ")
                        if doc_freq.get(raw_doc, 0) > 1:
                            sec_raw = str(s_text.get("section") or "").replace("\ufffd", " - ").strip()
                            para_idx = s_text.get("paragraph_index")
                            if sec_raw and sec_raw.lower() != doc_clean.lower():
                                doc_clean = f"{doc_clean} <span style='color:#94a3b8; font-size:0.85em;'>› {sec_raw}</span>"
                            elif para_idx is not None:
                                doc_clean = f"{doc_clean} <span style='color:#94a3b8; font-size:0.85em;'>(¶{int(para_idx) + 1})</span>"
                    else:
                        doc_clean = s_ptr
                    src_lines.append(f"<div style='margin-bottom:2px;'>• <b style='color:#00e5ff;'>[{tag}]</b> {doc_clean}</div>")
                more_count = len(sources_list) - len(diverse_sources)
                more_html = f"<div style='color:#94a3b8; font-size:0.85em; margin-top:2px;'><i>(+{more_count} more sources)</i></div>" if more_count > 0 else ""
                src_html = (
                    f"<div style='margin-top:6px; padding-top:4px; border-top:1px solid rgba(255,255,255,0.15); font-size:0.95em;'>"
                    f"<b>Sources:</b><br/>"
                    f"{''.join(src_lines)}"
                    f"{more_html}"
                    f"</div>"
                )
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
                    "why": why,
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
                data={"coordinates": bbox_poly, "role": "query_bbox"},
                color="cyan",
                tooltip="Active Query Bounding Box",
                popup=f"<b>Bounding Box Sector</b><br>SW: ({min_lat:.4f}°, {min_lng:.4f}°)<br>NE: ({max_lat:.4f}°, {max_lng:.4f}°)"
            ))
        elif selected_point:
            layers.append(MapLayer(
                name=f"Target Buffer ({selected_point[0]:.3f}, {selected_point[1]:.3f})",
                layer_type="circle",
                data={"lat": selected_point[0], "lng": selected_point[1], "radius": 5000, "role": "target_buffer"},
                color="cyan",
                tooltip="Target Buffer (5km)",
                popup=f"<b>Target Coordinate:</b> ({selected_point[0]:.4f}°, {selected_point[1]:.4f}°)"
            ))

        map_meta = raw_result.get("map", {})
        map_bbox = map_meta.get("bbox") if isinstance(map_meta, dict) else None
        map_showing = str(map_meta.get("showing", "all") or "all") if isinstance(map_meta, dict) else "all"
        try:
            map_not_shown = int(map_meta.get("not_shown", 0) or 0) if isinstance(map_meta, dict) else 0
        except (TypeError, ValueError):
            map_not_shown = 0

        raw_regions = raw_result.get("regions")
        if isinstance(raw_regions, (list, dict)):
            parsed_regions = raw_regions
        else:
            parsed_regions = []

        ans_plain_text = raw_result.get("answer_plain", ans_text)
        subgraph_data = extract_answer_subgraph(
            raw_response=raw_result,
            sources=top_sources,
            citations=final_citations,
            layers=layers,
            regions=parsed_regions,
            answer_text=ans_plain_text,
        )

        return AgentResponse(
            answer=ans_text,
            layers=layers,
            sources=top_sources,
            raw_response=raw_result,
            is_live_backend=True,
            answer_plain=ans_plain_text,
            citations=final_citations,
            grounded=raw_result.get("grounded", True),
            status=raw_result.get("status", "answered"),
            shape=raw_result.get("shape", "fact"),
            map_bbox=map_bbox,
            map_showing=map_showing,
            map_not_shown=map_not_shown,
            follow_ups=list(raw_result.get("follow_ups") or raw_result.get("follow_up_questions") or []),
            regions=parsed_regions,
            did_you_mean=raw_result.get("did_you_mean") or None,
            subgraph=subgraph_data,
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
            if isinstance(ly.data, dict) and "lat" in ly.data and "lng" in ly.data and ly.layer_type == "marker":
                mock_geo_locs.append({
                    "id": ly.data.get("id", ly.name),
                    "label": ly.name,
                    "geometry": {
                        "type": "point",
                        "coordinates": [ly.data["lng"], ly.data["lat"]]
                    },
                    "kind": ly.data.get("kind", "place"),
                    "role": ly.data.get("role", "primary"),
                    "sources": mock_resp.sources
                })
        mock_resp.raw_response = {
            "answer": mock_resp.answer,
            "geo_locations": mock_geo_locs,
            "sources": mock_resp.sources
        }
    if not mock_resp.subgraph:
        mock_resp.subgraph = extract_answer_subgraph(mock_resp)
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
                    data={"lat": lower_left[0], "lng": lower_left[1], "role": "bbox_corner", "corner": "sw"},
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
                    data={"lat": upper_right[0], "lng": upper_right[1], "role": "bbox_corner", "corner": "ne"},
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
                    data={"coordinates": bbox_coords, "role": "query_bbox"},
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
                    data={"lat": lower_left[0], "lng": lower_left[1], "role": "bbox_corner", "corner": "sw"},
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
                    data={"lat": upper_right[0], "lng": upper_right[1], "role": "bbox_corner", "corner": "ne"},
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
                    data={"coordinates": bbox_coords, "role": "query_bbox"},
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
