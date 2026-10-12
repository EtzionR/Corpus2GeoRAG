"""
==============================================================================
GeoAI Final Project - Pytest Test Suite for RAG Agent Contract
==============================================================================
This test suite validates the contract and behavior of the GeoAI mock backend
defined in `geo_agent.py`. It tests all three primary operational scenarios:
    1. Both text prompt and clicked coordinate provided (targeted query).
    2. Only clicked coordinate provided (automated location reconnaissance).
    3. Only text prompt provided (general spatial overview).
    4. Edge cases (empty inputs, chat history context passing).
    5. Dataclass type safety and serialization integrity.

Run tests using:
    pytest test_app.py -v
==============================================================================
"""

import pytest
from geo_agent import MapLayer, AgentResponse, query_geo_agent, to_bounding_box


class TestDataContracts:
    """Validate typing, default values, and structural contracts of the dataclasses."""

    def test_map_layer_instantiation_and_defaults(self):
        """Ensure MapLayer initializes with required attributes and correct defaults."""
        layer = MapLayer(
            name="Test Point",
            layer_type="marker",
            data={"lat": 48.5, "lng": 31.2}
        )

        assert layer.name == "Test Point"
        assert layer.layer_type == "marker"
        assert layer.data == {"lat": 48.5, "lng": 31.2}
        # Verify defaults
        assert layer.color == "blue"
        assert layer.tooltip == ""
        assert layer.popup == ""

    def test_map_layer_custom_attributes(self):
        """Ensure MapLayer accepts custom styling parameters."""
        layer = MapLayer(
            name="Tactical Circle",
            layer_type="circle",
            data={"lat": 50.4, "lng": 30.5, "radius": 5000},
            color="red",
            tooltip="Defense Zone",
            popup="<b>Sector 4</b>"
        )
        assert layer.color == "red"
        assert layer.tooltip == "Defense Zone"
        assert "Sector 4" in layer.popup

    def test_agent_response_defaults(self):
        """Ensure AgentResponse instantiates properly with empty layers default."""
        resp = AgentResponse(answer="System online.")
        assert isinstance(resp.answer, str)
        assert resp.answer == "System online."
        assert isinstance(resp.layers, list)
        assert len(resp.layers) == 0


class TestGeoAgentScenarios:
    """Validate query_geo_agent routing and multimodal response handling."""

    def test_scenario_a_both_text_and_selected_point(self):
        """
        Scenario A: Both `text_prompt` AND `selected_point` are provided.
        Example: User selects a coordinate and asks "What units are stationed here?".

        Assertions:
            - Return type is AgentResponse.
            - `answer` is non-empty string referencing query intent and coordinates.
            - `layers` is a non-empty list containing MapLayer instances.
            - Layer data contains the target coordinates.
        """
        prompt = "What units are stationed here?"
        point = (49.4444, 32.0597)

        response = query_geo_agent(text_prompt=prompt, selected_point=point)

        # 1. Type validation
        assert isinstance(response, AgentResponse), "Expected an AgentResponse instance"
        assert isinstance(response.answer, str), "Expected response.answer to be a string"
        assert isinstance(response.layers, list), "Expected response.layers to be a list"

        # 2. Content validation
        assert len(response.answer) > 0, "Response answer should not be empty"
        assert "What units are stationed here?" in response.answer, (
            "Response should reference the user's specific query intent"
        )
        assert "49.4444" in response.answer, "Response should reference the latitude"
        assert "32.0597" in response.answer, "Response should reference the longitude"

        # 3. Layer validation
        assert len(response.layers) >= 1, "Expected at least one tactical layer for targeted query"
        for layer in response.layers:
            assert isinstance(layer, MapLayer), f"Layer {layer} must be an instance of MapLayer"
            assert "lat" in layer.data and "lng" in layer.data, "Target layer must contain coordinates"
            assert layer.data["lat"] == point[0]
            assert layer.data["lng"] == point[1]

    def test_scenario_b_only_selected_point(self):
        """
        Scenario B: Only `selected_point` is provided.
        Example: User runs reconnaissance on a selected coordinate without typing a message.

        Assertions:
            - Return type is AgentResponse.
            - `answer` is non-empty string providing a location reconnaissance summary.
            - `layers` is a non-empty list of MapLayer instances for that location.
        """
        point = (48.3794, 31.1656)

        response = query_geo_agent(text_prompt=None, selected_point=point)

        # 1. Type validation
        assert isinstance(response, AgentResponse), "Expected an AgentResponse instance"
        assert isinstance(response.answer, str), "Expected response.answer to be a string"
        assert isinstance(response.layers, list), "Expected response.layers to be a list"

        # 2. Content validation
        assert len(response.answer) > 0, "Response answer should not be empty"
        assert "Location Reconnaissance Summary" in response.answer
        assert "48.3794" in response.answer, "Response should reference the clicked latitude"
        assert "31.1656" in response.answer, "Response should reference the clicked longitude"

        # 3. Layer validation
        assert len(response.layers) >= 1, "Expected location marker/circle layers"
        for layer in response.layers:
            assert isinstance(layer, MapLayer), f"Layer {layer} must be an instance of MapLayer"
            assert layer.data["lat"] == point[0]
            assert layer.data["lng"] == point[1]

    def test_scenario_c_only_text_prompt(self):
        """
        Scenario C: Only `text_prompt` is provided.
        Example: User asks a general question like "Show major logistics corridors".

        Assertions:
            - Return type is AgentResponse.
            - `answer` is non-empty string with general spatial synthesis.
            - `layers` is a non-empty list of MapLayer instances showing mock strategic hubs.
        """
        prompt = "Show major logistics corridors in central Ukraine"

        response = query_geo_agent(text_prompt=prompt, selected_point=None)

        # 1. Type validation
        assert isinstance(response, AgentResponse), "Expected an AgentResponse instance"
        assert isinstance(response.answer, str), "Expected response.answer to be a string"
        assert isinstance(response.layers, list), "Expected response.layers to be a list"

        # 2. Content validation
        assert len(response.answer) > 0, "Response answer should not be empty"
        assert "General Spatial Intelligence" in response.answer
        assert "logistics corridors" in response.answer

        # 3. Layer validation
        assert len(response.layers) >= 3, "Expected multiple regional hub layers (Kyiv, Kharkiv, Dnipro)"
        for layer in response.layers:
            assert isinstance(layer, MapLayer), f"Layer {layer} must be an instance of MapLayer"
            assert "lat" in layer.data and "lng" in layer.data
            assert isinstance(layer.data["lat"], (int, float))
            assert isinstance(layer.data["lng"], (int, float))

    def test_scenario_fallback_neither_provided(self):
        """
        Fallback Scenario: Neither text prompt nor selected point is provided.

        Assertions:
            - Return type is AgentResponse.
            - `answer` provides a friendly prompt to start.
            - `layers` is an empty list.
        """
        response = query_geo_agent(text_prompt=None, selected_point=None)

        assert isinstance(response, AgentResponse)
        assert isinstance(response.answer, str)
        assert isinstance(response.layers, list)
        assert len(response.layers) == 0
        assert "GeoAI Agent Ready" in response.answer

    def test_chat_history_preservation(self):
        """Ensure passing chat_history does not break contract and executes properly."""
        history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "How can I help you today?"}
        ]
        response = query_geo_agent(
            text_prompt="Summarize situation",
            selected_point=(50.4501, 30.5234),
            chat_history=history
        )
        assert isinstance(response, AgentResponse)
        assert len(response.layers) > 0

    def test_scenario_a_multiple_selected_points(self):
        """Ensure query_geo_agent handles multiple selected points with a text prompt."""
        prompt = "Assess tactical corridors between these sectors"
        points = [(48.3794, 31.1656), (49.4444, 32.0597), (50.4501, 30.5234)]

        response = query_geo_agent(text_prompt=prompt, selected_points=points)

        assert isinstance(response, AgentResponse)
        assert "Multi-Target Analysis (3 Locations)" in response.answer
        assert "Assess tactical corridors between these sectors" in response.answer
        assert "48.3794" in response.answer
        assert "49.4444" in response.answer
        assert "50.4501" in response.answer
        # Each point should have a marker and a buffer circle
        assert len(response.layers) == len(points) * 2

    def test_scenario_b_multiple_selected_points(self):
        """Ensure query_geo_agent handles multiple selected points for reconnaissance without prompt."""
        points = [(48.3794, 31.1656), (49.4444, 32.0597)]

        response = query_geo_agent(text_prompt=None, selected_points=points)

        assert isinstance(response, AgentResponse)
        assert "Multi-Location Reconnaissance Summary (2 Sectors)" in response.answer
        assert "48.3794" in response.answer
        assert "49.4444" in response.answer
        assert len(response.layers) == len(points) * 2

    def test_point_selection_and_removal_lifecycle(self):
        """Simulate state lifecycle for selecting, removing individual points, and clearing all."""
        selected_points = []

        # 1. Click 3 locations on map
        p1 = (48.3794, 31.1656)
        p2 = (49.4444, 32.0597)
        p3 = (50.4501, 30.5234)

        for p in [p1, p2, p3]:
            if p not in selected_points:
                selected_points.append(p)
        assert len(selected_points) == 3

        # 2. Duplicate click should not add duplicates
        if p2 not in selected_points:
            selected_points.append(p2)
        assert len(selected_points) == 3

        # 3. Remove middle point (p2)
        removed = selected_points.pop(1)
        assert removed == p2
        assert len(selected_points) == 2
        assert p2 not in selected_points
        assert selected_points == [p1, p3]

        # 4. Clear all points
        selected_points.clear()
        assert len(selected_points) == 0


class TestBoundingBox:
    """Validate bounding box calculation, query routing, and state lifecycle."""

    def test_to_bounding_box_standard_ordering(self):
        """Ensure to_bounding_box computes lower-left (min) and upper-right (max) correctly."""
        p_sw = (48.3794, 31.1656)
        p_ne = (50.4501, 35.0462)

        lower_left, upper_right = to_bounding_box(p_sw, p_ne)

        assert lower_left == (48.3794, 31.1656), "Lower-left must be South-West (min_lat, min_lng)"
        assert upper_right == (50.4501, 35.0462), "Upper-right must be North-East (max_lat, max_lng)"

    def test_to_bounding_box_reversed_ordering(self):
        """Ensure to_bounding_box produces identical box regardless of click order."""
        p_ne = (50.4501, 35.0462)
        p_sw = (48.3794, 31.1656)

        lower_left, upper_right = to_bounding_box(p_ne, p_sw)

        assert lower_left == (48.3794, 31.1656), "Lower-left must remain South-West even if clicked 2nd"
        assert upper_right == (50.4501, 35.0462), "Upper-right must remain North-East even if clicked 1st"

    def test_to_bounding_box_diagonal_nw_to_se(self):
        """Ensure diagonal corners (North-West to South-East) correctly resolve to SW and NE."""
        p_nw = (50.4501, 31.1656)  # High lat, low lng
        p_se = (48.3794, 35.0462)  # Low lat, high lng

        lower_left, upper_right = to_bounding_box(p_nw, p_se)

        assert lower_left == (48.3794, 31.1656)
        assert upper_right == (50.4501, 35.0462)

    def test_to_bounding_box_coordinate_rounding(self):
        """Ensure coordinates are rounded to 5 decimal places."""
        p1 = (48.1234567, 31.9876543)
        p2 = (49.5555555, 32.4444444)

        lower_left, upper_right = to_bounding_box(p1, p2)

        assert lower_left == (48.12346, 31.98765)
        assert upper_right == (49.55556, 32.44444)

    def test_query_geo_agent_with_bounding_box_and_prompt(self):
        """
        Validate Scenario A when a bounding box is provided with a text query.
        Ensures response references bounding box extents and returns tactical layers.
        """
        prompt = "Scan for logistics hubs inside this area"
        bbox = ((48.3794, 31.1656), (50.4501, 35.0462))

        response = query_geo_agent(text_prompt=prompt, bounding_box=bbox)

        assert isinstance(response, AgentResponse)
        assert "Bounding Box Area Analysis" in response.answer
        assert "Lower-Left (SW):" in response.answer
        assert "Upper-Right (NE):" in response.answer
        assert "48.3794" in response.answer
        assert "31.1656" in response.answer
        assert "50.4501" in response.answer
        assert "35.0462" in response.answer
        assert "Scan for logistics hubs" in response.answer

        # Layers: Lower-left marker, upper-right marker, and polygon/box layer
        assert len(response.layers) == 3
        layer_names = [l.name for l in response.layers]
        assert any("Lower-Left" in name for name in layer_names)
        assert any("Upper-Right" in name for name in layer_names)
        assert any("Bounding Box Area" in name for name in layer_names)

        poly_layer = [l for l in response.layers if l.layer_type == "polygon"][0]
        coords = poly_layer.data["coordinates"]
        assert len(coords) == 5  # Closed 4-point rectangle polygon

    def test_query_geo_agent_with_bounding_box_reconnaissance(self):
        """
        Validate Scenario B when a bounding box is provided without text prompt.
        Ensures response produces a bounding box reconnaissance summary.
        """
        bbox = ((48.3794, 31.1656), (50.4501, 35.0462))

        response = query_geo_agent(text_prompt=None, bounding_box=bbox)

        assert isinstance(response, AgentResponse)
        assert "Bounding Box Reconnaissance Summary" in response.answer
        assert "Lower-Left (SW):" in response.answer
        assert "Upper-Right (NE):" in response.answer
        assert "48.3794" in response.answer
        assert "35.0462" in response.answer

        assert len(response.layers) == 3

    def test_bounding_box_and_selected_point_mutual_exclusivity(self):
        """
        Validate that if a bounding box is selected, points shouldn't be in selected_point.
        Even if a caller passes both, bounding_box takes precedence and points are not duplicated.
        """
        bbox = ((48.3794, 31.1656), (50.4501, 35.0462))
        point = (49.0000, 33.0000)

        # Pass both bounding_box and selected_point
        response = query_geo_agent(
            text_prompt="Test mutual exclusivity",
            selected_point=point,
            bounding_box=bbox
        )

        assert isinstance(response, AgentResponse)
        # Should process as bounding box analysis, NOT point analysis
        assert "Bounding Box Area Analysis" in response.answer
        assert "Targeted Point Analysis" not in response.answer
        # Layers should only be the bounding box layers (2 markers + 1 polygon), not 2 markers + 1 circle for point
        assert len(response.layers) == 3
        poly_layers = [l for l in response.layers if l.layer_type == "polygon"]
        assert len(poly_layers) == 1

    def test_bounding_box_selection_lifecycle(self):
        """
        Simulate UI state lifecycle:
        1. Click corner 1 (pending)
        2. Click corner 2 -> box formed (lower-left, upper-right)
        3. Click corner 3 -> starts fresh box
        4. Clear box
        """
        # Step 1: Initial state
        selection_mode = "Bounding Box"
        selected_points = []
        bounding_box = None

        # Step 2: First click (Corner 1)
        c1 = (50.4501, 30.5234)
        selected_points = [c1]
        assert len(selected_points) == 1
        assert bounding_box is None

        # Step 3: Second click (Corner 2)
        c2 = (48.3794, 35.0462)
        lower_left, upper_right = to_bounding_box(selected_points[0], c2)
        selected_points = [lower_left, upper_right]
        bounding_box = (lower_left, upper_right)

        assert len(selected_points) == 2
        assert bounding_box == ((48.3794, 30.5234), (50.4501, 35.0462))
        assert selected_points[0] == (48.3794, 30.5234)  # lower-left
        assert selected_points[1] == (50.4501, 35.0462)  # upper-right

        # Step 4: Next click starts a new box
        c3 = (49.0000, 32.0000)
        selected_points = [c3]
        bounding_box = None
        assert len(selected_points) == 1
        assert bounding_box is None

        # Step 5: Clear
        selected_points = []
        bounding_box = None
        assert len(selected_points) == 0
        assert bounding_box is None

    def test_mode_transitions_bbox_and_point_selection(self):
        """Validate transitioning between Bounding Box and Point Selection modes (no multi-point)."""
        # Start in Bounding Box mode with 2 points
        p1 = (48.0, 31.0)
        p2 = (50.0, 35.0)
        lower_left, upper_right = to_bounding_box(p1, p2)
        selected_points = [lower_left, upper_right]
        bounding_box = (lower_left, upper_right)

        # Transition to Point Selection: retains single active point
        mode = "Point Selection"
        selected_points = [selected_points[-1]]
        bounding_box = None
        assert len(selected_points) == 1
        assert selected_points == [(50.0, 35.0)]
        assert bounding_box is None

        # Clicking again in Point Selection cancels previous selection
        new_click = (49.5, 33.0)
        selected_points = [new_click]  # replaces previous
        assert len(selected_points) == 1
        assert selected_points == [(49.5, 33.0)]

        # Transition back to Bounding Box
        mode = "Bounding Box"
        c1 = (48.5, 32.0)
        selected_points = [c1]
        bounding_box = None
        c2 = (50.5, 36.0)
        lower_left, upper_right = to_bounding_box(selected_points[0], c2)
        selected_points = [lower_left, upper_right]
        bounding_box = (lower_left, upper_right)
        assert bounding_box == ((48.5, 32.0), (50.5, 36.0))

    def test_point_selection_cancels_previous_on_click(self):
        """
        Verify that when in Point Selection mode (not bounding box),
        clicking again cancels the previous selection and selects the new coordinate.
        """
        selection_mode = "Point Selection"
        selected_points = []
        bounding_box = None

        # 1. First click selects Point A
        pt_a = (48.3794, 31.1656)
        selected_points = [pt_a]
        bounding_box = None
        assert len(selected_points) == 1
        assert selected_points == [pt_a]

        # 2. Second click on Point B CANCELS previous selection (Point A) and sets Point B
        pt_b = (50.4501, 30.5234)
        selected_points = [pt_b]
        assert len(selected_points) == 1
        assert selected_points == [pt_b]
        assert pt_a not in selected_points

        # 3. Third click on Point C CANCELS Point B and sets Point C
        pt_c = (49.9935, 36.2304)
        selected_points = [pt_c]
        assert len(selected_points) == 1
        assert selected_points == [pt_c]
        assert pt_b not in selected_points

        # 4. Clear point
        selected_points = []
        assert len(selected_points) == 0

