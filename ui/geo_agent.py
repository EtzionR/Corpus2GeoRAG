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

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


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
            including analytical assessments, spatial context, or situational reports.
        layers (List[MapLayer]): A collection of map layers synthesized or retrieved
            by the agent to be displayed synchronously on the frontend map.
    """
    answer: str
    layers: List[MapLayer] = field(default_factory=list)


# ==============================================================================
# 2. Mock Geo-Agent Routing Function & Bounding Box Utilities
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


def query_geo_agent(
    text_prompt: Optional[str] = None,
    selected_point: Optional[Tuple[float, float]] = None,
    bounding_box: Optional[Tuple[Tuple[float, float], Tuple[float, float]]] = None,
    chat_history: Optional[List[Dict[str, Any]]] = None,
    **kwargs: Any
) -> AgentResponse:
    """
    Route and process user multimodal requests combining free-form text queries,
    interactive map click coordinates, bounding box extents, and conversational context.

    This mock implementation simulates a spatial RAG agent handling key scenarios:
      Scenario A: Both `text_prompt` AND target point or bounding box are provided.
                  Example: User selects bounding box and asks "What units are stationed here?".
                  Response: References query intent and bounding box / target coordinates.
      Scenario B: Only target point or bounding box are provided.
                  Example: User clicks "Run Reconnaissance" on selected bounding box / point.
                  Response: Generic spatial reconnaissance summary for the coordinates.
      Scenario C: Only `text_prompt` is provided.
                  Example: User asks "Show key logistics nodes in central Ukraine".
                  Response: General spatial analysis accompanied by dummy strategic coordinates.

    Args:
        text_prompt (Optional[str]): Natural language prompt input by the user.
        selected_point (Optional[Tuple[float, float]]): Coordinate tuple (latitude, longitude)
            representing a selected point on the map.
        bounding_box (Optional[Tuple[Tuple[float, float], Tuple[float, float]]]): Two-point
            bounding box tuple ((min_lat, min_lng), (max_lat, max_lng)). When provided,
            points are not placed in `selected_point`.
        chat_history (Optional[List[Dict[str, Any]]]): Prior conversation messages for context.

    Returns:
        AgentResponse: Structured object containing synthesis answer text and map layers.
    """
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
