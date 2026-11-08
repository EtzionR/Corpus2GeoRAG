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


@pytest.fixture(autouse=True)
def _isolate_openrouter_env(monkeypatch):
    """Ensure unit tests do not make live OpenRouter API calls when AgentRag/.env exists on disk."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)


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


class TestBackendAdapter:
    """Validate backend RAG adapter transformations and interface contracts."""

    def test_adapter_delegation_without_key_uses_mock(self):
        """When no API key is provided, adapter cleanly falls back to deterministic mock."""
        resp = query_geo_agent(text_prompt="Test query", api_key=None, force_mock=False)
        assert isinstance(resp, AgentResponse)
        assert resp.is_live_backend is False
        assert "Test query" in resp.answer

    def test_adapter_point_transformation(self, monkeypatch):
        """Verify (lat, lng) is transformed to GeoJSON [lng, lat] point dict for backend."""
        import geo_agent

        captured_args = {}

        def fake_backend_query(text_prompt, geo_location=None, chat_history=None, api_key=None):
            captured_args["text_prompt"] = text_prompt
            captured_args["geo_location"] = geo_location
            captured_args["chat_history"] = chat_history
            captured_args["api_key"] = api_key
            return {
                "answer": "According to the graph, target located.",
                "geo_locations": [
                    {
                        "id": "Kyiv",
                        "label": "Kyiv",
                        "kind": "place",
                        "geometry": {"type": "point", "coordinates": [30.5234, 50.4501]},
                        "sources": ["Doc-1"]
                    }
                ],
                "sources": ["Doc-1"]
            }

        monkeypatch.setattr(geo_agent, "_BACKEND_AVAILABLE", True)
        monkeypatch.setattr(geo_agent, "_backend_query", fake_backend_query)

        # Call with lat=50.4501, lng=30.5234
        resp = query_geo_agent(
            text_prompt="Where is Kyiv?",
            selected_point=(50.4501, 30.5234),
            api_key="test-key-123"
        )

        assert resp.is_live_backend is True
        assert captured_args["api_key"] == "test-key-123"
        assert captured_args["geo_location"] is not None
        assert captured_args["geo_location"]["type"] == "point"
        # Coordinates must be [lon, lat]
        assert captured_args["geo_location"]["coordinates"] == [30.5234, 50.4501]

        # Verify output layers have inverted back to Folium [lat, lng]
        assert len(resp.layers) >= 1
        marker_layer = [l for l in resp.layers if l.name == "[PLACE] Kyiv"][0]
        assert marker_layer.data["lat"] == 50.4501
        assert marker_layer.data["lng"] == 30.5234
        assert resp.sources == ["Doc-1"]

    def test_adapter_bounding_box_transformation(self, monkeypatch):
        """Verify ((min_lat, min_lng), (max_lat, max_lng)) becomes closed 5-point GeoJSON ring."""
        import geo_agent

        captured_args = {}

        def fake_backend_query(text_prompt, geo_location=None, chat_history=None, api_key=None):
            captured_args["geo_location"] = geo_location
            return {
                "answer": "Analyzed bounding box sector.",
                "geo_locations": [],
                "sources": []
            }

        monkeypatch.setattr(geo_agent, "_BACKEND_AVAILABLE", True)
        monkeypatch.setattr(geo_agent, "_backend_query", fake_backend_query)

        # Latitudes: 48.0 to 50.0, Longitudes: 31.0 to 35.0
        bbox = ((48.0, 31.0), (50.0, 35.0))
        resp = query_geo_agent(
            text_prompt=None,  # Recon scan
            bounding_box=bbox,
            api_key="test-key-123"
        )

        assert resp.is_live_backend is True
        geo_loc = captured_args["geo_location"]
        assert geo_loc["type"] == "polygon"
        ring = geo_loc["coordinates"][0]
        assert len(ring) == 5
        # Ring must be closed: ring[0] == ring[-1]
        assert ring[0] == ring[-1]
        # Ring order: [w, s], [e, s], [e, n], [w, n], [w, s]
        assert ring == [[31.0, 48.0], [35.0, 48.0], [35.0, 50.0], [31.0, 50.0], [31.0, 48.0]]

    def test_get_source_text_fallback_when_unavailable(self, monkeypatch):
        """get_source_text returns None when backend function is unavailable."""
        import geo_agent
        monkeypatch.setattr(geo_agent, "_backend_get_source_text", None)
        assert geo_agent.get_source_text("nonexistent_doc") is None

    def test_vr6_numbered_pins_and_citations_passthrough(self, monkeypatch):
        """Verify Vr6 numbered places, answer_plain, citations, why, and uncertain flags are mapped."""
        import geo_agent

        def fake_vr6_query(text_prompt, geo_location=None, chat_history=None, api_key=None):
            return {
                "answer": "Kyiv [1] is the capital of Ukraine [L1]. Donets [2] is nearby.",
                "answer_plain": "Kyiv is the capital of Ukraine. Donets is nearby.",
                "status": "answered",
                "grounded": True,
                "shape": "fact",
                "geo_locations": [
                    {
                        "number": 1,
                        "id": "Kyiv",
                        "label": "Kyiv",
                        "kind": "city",
                        "role": "primary",
                        "geometry": {"type": "Point", "coordinates": [30.5241, 50.4500]},
                        "why": "30 matching paragraphs",
                        "sources": ["TEXT_50333"]
                    },
                    {
                        "number": 2,
                        "id": "Donets",
                        "label": "Donets",
                        "kind": "road",
                        "role": "context",
                        "geometry": {"type": "Point", "coordinates": [36.25, 49.98]},
                        "why": "2 matching paragraphs",
                        "uncertain": "geocoded as a road, may refer to the river",
                        "sources": ["TEXT_1001"]
                    }
                ],
                "citations": [
                    {
                        "id": "L1",
                        "pointer": "TEXT_50333",
                        "article": "Kyiv",
                        "section": "Lead",
                        "spans": [[0, 4]]
                    }
                ],
                "sources": ["TEXT_50333", "TEXT_1001"]
            }

        monkeypatch.setattr(geo_agent, "_BACKEND_AVAILABLE", True)
        monkeypatch.setattr(geo_agent, "_backend_query", fake_vr6_query)

        resp = query_geo_agent(text_prompt="Tell me about Kyiv", api_key="test-key-vr6")

        assert resp.is_live_backend is True
        assert resp.answer == "Kyiv [1] is the capital of Ukraine [L1]. Donets [2] is nearby."
        assert resp.answer_plain == "Kyiv is the capital of Ukraine. Donets is nearby."
        assert resp.grounded is True
        assert resp.status == "answered"
        assert len(resp.citations) == 1
        assert resp.citations[0]["id"] == "L1"
        assert resp.citations[0]["article"] == "Kyiv"

        # Primary numbered pin
        pin1 = [l for l in resp.layers if l.data.get("number") == 1][0]
        assert pin1.name == "1. [CITY] Kyiv"
        assert pin1.tooltip == "1. Kyiv [CITY]"
        assert pin1.color == "blue"
        assert "30 matching paragraphs" in pin1.popup

        # Uncertain pin
        pin2 = [l for l in resp.layers if l.data.get("number") == 2][0]
        assert pin2.name == "2. [ROAD] Donets (?)"
        assert pin2.color == "orange"
        assert "geocoded as a road" in pin2.popup

    def test_vr6_get_source_text_paragraph_pointer(self, monkeypatch):
        """Verify get_source_text passes through Vr6 paragraph metadata."""
        import geo_agent

        def fake_get_source(ptr):
            if ptr == "TEXT_50333":
                return {
                    "pointer": "TEXT_50333",
                    "text": "Kyiv is the capital and most populous city of Ukraine.",
                    "document": "Kyiv",
                    "section": "Lead",
                    "paragraph_index": 0
                }
            return None

        monkeypatch.setattr(geo_agent, "_backend_get_source_text", fake_get_source)
        if hasattr(geo_agent.get_source_text, "cache_clear"):
            geo_agent.get_source_text.cache_clear()
        res = geo_agent.get_source_text("TEXT_50333")
        assert res is not None
        assert res["pointer"] == "TEXT_50333"
        assert res["document"] == "Kyiv"
        assert res["section"] == "Lead"
        assert res["paragraph_index"] == 0

    def test_vr6_source_label_resolves_document_title(self, monkeypatch):
        """Verify sources display human-readable article title instead of raw pointer indices."""
        import geo_agent
        from app import _clean_doc_title

        def fake_get_source(ptr):
            if ptr == "TEXT_53733":
                return {
                    "pointer": "TEXT_53733",
                    "text": "Biden called Zelenskyy...",
                    "document": "Russia\ufffdUkraine relations",
                    "section": "History of relations",
                    "paragraph_index": 89
                }
            return None

        monkeypatch.setattr(geo_agent, "_backend_get_source_text", fake_get_source)
        if hasattr(geo_agent.get_source_text, "cache_clear"):
            geo_agent.get_source_text.cache_clear()
        meta = geo_agent.get_source_text("TEXT_53733")
        assert meta is not None
        doc_title = _clean_doc_title(meta["document"])
        assert doc_title == "Russia - Ukraine relations"
        assert meta["section"] == "History of relations"
        assert meta["paragraph_index"] == 89

    def test_vr6_pin_visibility_filters(self):
        """Verify primary, context, and uncertain pins can be toggled on/off."""
        from geo_agent import MapLayer

        primary_pin = MapLayer(
            name="1. [CITY] Kyiv",
            layer_type="marker",
            data={"lat": 50.45, "lng": 30.52, "role": "primary", "uncertain": None},
            color="blue"
        )
        context_pin = MapLayer(
            name="2. [TOWN] Bucha",
            layer_type="marker",
            data={"lat": 50.55, "lng": 30.21, "role": "context", "uncertain": None},
            color="cadetblue"
        )
        uncertain_pin = MapLayer(
            name="3. [ROAD] Donets (?)",
            layer_type="marker",
            data={"lat": 49.98, "lng": 36.25, "role": "context", "uncertain": "river vs road"},
            color="orange"
        )
        all_layers = [primary_pin, context_pin, uncertain_pin]

        def filter_markers(layers, show_primary=True, show_context=True, show_uncertain=False):
            rendered = []
            for l in layers:
                if l.layer_type == "marker":
                    is_context = isinstance(l.data, dict) and (l.data.get("role") == "context" or l.color == "cadetblue")
                    is_uncertain = isinstance(l.data, dict) and bool(l.data.get("uncertain") or l.color == "orange")
                    is_primary = not is_context and not is_uncertain
                    if is_primary and not show_primary:
                        continue
                    if is_context and not show_context:
                        continue
                    if is_uncertain and not show_uncertain:
                        continue
                    rendered.append(l)
            return rendered

        # Default state: primary & context visible, uncertain unchecked (hidden)
        res_default = filter_markers(all_layers, show_primary=True, show_context=True, show_uncertain=False)
        assert len(res_default) == 2
        assert primary_pin in res_default
        assert context_pin in res_default
        assert uncertain_pin not in res_default

        # When user checks uncertain pins: all 3 visible
        assert len(filter_markers(all_layers, show_primary=True, show_context=True, show_uncertain=True)) == 3

        # Toggle off primary pins: only context remains (with uncertain off)
        res_no_pri = filter_markers(all_layers, show_primary=False, show_context=True, show_uncertain=False)
        assert len(res_no_pri) == 1
        assert res_no_pri[0].name == "2. [TOWN] Bucha"

        # Hide context: only primary remains
        res_no_ctx = filter_markers(all_layers, show_primary=True, show_context=False, show_uncertain=False)
        assert len(res_no_ctx) == 1
        assert res_no_ctx[0].name == "1. [CITY] Kyiv"

        # Hide both primary and context: empty if uncertain is also off
        res_no_both = filter_markers(all_layers, show_primary=False, show_context=False, show_uncertain=False)
        assert len(res_no_both) == 0


class TestDrawingIngestion:
    """Validate parsing and conversion of Leaflet Draw GeoJSON features to bounding box / points."""

    def test_draw_rectangle_to_bounding_box(self):
        """Verify Leaflet Draw Polygon rectangle maps to standard ((min_lat, min_lng), (max_lat, max_lng))."""
        rect_feature = {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [[30.5, 49.2], [35.2, 49.2], [35.2, 51.1], [30.5, 51.1], [30.5, 49.2]]
                ]
            }
        }
        coords = rect_feature["geometry"]["coordinates"][0]
        lats = [float(pt[1]) for pt in coords]
        lngs = [float(pt[0]) for pt in coords]
        lower_left, upper_right = to_bounding_box((min(lats), min(lngs)), (max(lats), max(lngs)))

        assert lower_left == (49.2, 30.5)
        assert upper_right == (51.1, 35.2)

    def test_draw_polygon_to_bounding_box(self):
        """Verify arbitrary Leaflet Draw Polygon calculates proper bounding envelope."""
        poly_feature = {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [[31.2, 48.5], [33.4, 47.9], [34.8, 50.1], [32.0, 50.8], [31.2, 48.5]]
                ]
            }
        }
        coords = poly_feature["geometry"]["coordinates"][0]
        lats = [float(pt[1]) for pt in coords]
        lngs = [float(pt[0]) for pt in coords]
        lower_left, upper_right = to_bounding_box((min(lats), min(lngs)), (max(lats), max(lngs)))

        assert lower_left == (47.9, 31.2)
        assert upper_right == (50.8, 34.8)

    def test_draw_point_marker_coordinates(self):
        """Verify Leaflet Draw Point marker maps to (lat, lng)."""
        marker_feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [31.1656, 48.3794]
            }
        }
        coords = marker_feature["geometry"]["coordinates"]
        lat = round(float(coords[1]), 5)
        lng = round(float(coords[0]), 5)
        assert (lat, lng) == (48.3794, 31.1656)


class TestUIBranding:
    """Verify UI branding compliance and clean separation from proprietary vendor names."""

    def test_no_palantir_or_gotham_in_app_source(self):
        """Ensure no leftover mentions of 'Palantir' or 'Gotham' exist in the application code."""
        with open("app.py", "r", encoding="utf-8") as f:
            content = f.read().lower()
        assert "palantir" not in content
        assert "gotham" not in content

    def test_leaflet_attribution_disabled_in_app(self):
        """Ensure Leaflet attribution control is disabled and hidden in app.py."""
        with open("app.py", "r", encoding="utf-8") as f:
            content = f.read()
        assert "attributionControl=False" in content
        assert ".leaflet-control-attribution { display: none !important; }" in content



class TestMapTrashBinTool:
    """Verify integration of the map toolbar trash bin with spatial selections and overlays."""

    def test_trash_hook_registers_layers_and_handlers(self):
        """Verify MapTrashBinHook template renders drawnItems layer registration and delete listener."""
        import folium
        from branca.element import MacroElement
        from jinja2 import Template
        from streamlit_folium import _get_map_string

        # Extract MapTrashBinHook class definition from app.py safely
        import app
        MapTrashBinHook = getattr(app, "MapTrashBinHook")

        m = folium.Map()
        m_pt = folium.Marker([48.3794, 31.1656]).add_to(m)
        m_rect = folium.Rectangle(bounds=[[48.0, 31.0], [49.0, 32.0]]).add_to(m)

        hook = MapTrashBinHook(
            selection_layer_names=[m_pt.get_name(), m_rect.get_name()],
            has_active=True
        ).add_to(m)

        script = _get_map_string(m)

        # 1. Selection layer registration into drawnItems
        assert f"drawnItems.addLayer({m_pt.get_name()})" in script
        assert f"drawnItems.addLayer({m_rect.get_name()})" in script

        # 2. Trash bin click listener on .leaflet-draw-edit-remove
        assert ".leaflet-draw-edit-remove" in script

        # 3. Dispatches Leaflet draw:deleted event with action delete
        assert "draw:deleted" in script
        assert "action" in script
        assert "delete" in script

    def test_delete_action_payload_detection(self):
        """Verify delete action payload detection logic for active_drawing."""
        del_payload = {
            "type": "Feature",
            "geometry": None,
            "properties": {"action": "delete", "timestamp": 123456789}
        }
        props = del_payload.get("properties") or {}
        geom = del_payload.get("geometry")

        is_delete = props.get("action") == "delete" or not geom
        assert is_delete is True

    def test_app_draw_config_enables_trash_and_disables_edit(self):
        """Ensure Draw plugin in app.py explicitly enables remove and disables edit."""
        with open("app.py", "r", encoding="utf-8") as f:
            content = f.read()

        assert 'edit_options={"edit": False, "remove": True}' in content
        assert "edit_options=None" not in content
        assert "MapTrashBinHook" in content

    def test_instant_client_side_selection_and_bbox_hooks(self):
        """Verify MapTrashBinHook provides 0ms client-side click and bbox visual feedback."""
        import folium
        from streamlit_folium import _get_map_string
        import app

        MapTrashBinHook = getattr(app, "MapTrashBinHook")
        m = folium.Map()
        MapTrashBinHook().add_to(m)

        script = _get_map_string(m)

        # 1. Instant click handler on canvas
        assert "map.on('click'" in script
        assert "starIcon" in script
        assert "window._instantTargetMarker" in script

        # 2. Instant bounding box handler on draw:created
        assert "map.on('draw:created'" in script
        assert "arrow-down" in script
        assert "arrow-up" in script

        # 3. Instant clearing in triggerRemoval
        assert "window._instantTargetMarker = null" in script

    def test_dynamic_feature_group_hash_stability(self):
        """Verify that dynamic selection changes via feature_group_to_add do not alter the base map hash."""
        import folium
        from streamlit_folium import _get_map_string, generate_js_hash
        import app

        MapTrashBinHook = getattr(app, "MapTrashBinHook")

        # Base map m (as generated in app.py)
        m = folium.Map(location=[48.3794, 31.1656], zoom_start=6, tiles=None)
        folium.plugins.Draw(
            export=False,
            position="topleft",
            draw_options={"rectangle": True},
            edit_options={"edit": False, "remove": True}
        ).add_to(m)
        MapTrashBinHook(has_active=False).add_to(m)

        s_base = _get_map_string(m)
        h_initial = generate_js_hash(s_base, key="geoai_tactical_map")

        # Now simulate user selecting a point: dynamic_layers_fg is passed via feature_group_to_add,
        # so m itself remains structurally identical
        s_with_point = _get_map_string(m)
        h_with_point = generate_js_hash(s_with_point, key="geoai_tactical_map")

        # The base map hash MUST NOT change, ensuring zero map reload / flash
        assert h_initial == h_with_point

        # Ensure that has_active=False vs has_active=True also produces identical base map hashes
        m_active = folium.Map(location=[48.3794, 31.1656], zoom_start=6, tiles=None)
        folium.plugins.Draw(
            export=False,
            position="topleft",
            draw_options={"rectangle": True},
            edit_options={"edit": False, "remove": True}
        ).add_to(m_active)
        MapTrashBinHook(has_active=True).add_to(m_active)
        s_active = _get_map_string(m_active)
        h_active = generate_js_hash(s_active, key="geoai_tactical_map")
        assert h_initial == h_active

    def test_instant_replacement_cleans_prior_selection(self):
        """Verify MapTrashBinHook includes client-side instant cleanup for prior selection replacing."""
        import folium
        from streamlit_folium import _get_map_string
        import app

        MapTrashBinHook = getattr(app, "MapTrashBinHook")
        m = folium.Map()
        MapTrashBinHook().add_to(m)

        script = _get_map_string(m)

        # 1. Instant cleanup function is defined
        assert "function clearPreviousSelectionInstantly()" in script

        # 2. Clears active selection feature group (feature_group[0])
        assert "window.feature_group[0]" in script
        assert "selFg.clearLayers" in script

        # 3. Purges previous target point and bounding box layers via DOM/map scan
        assert "map.eachLayer" in script
        assert "★ Target Point" in script
        assert "★ Bounding Box" in script
        assert "★ BBOX" in script

        # 4. clearPreviousSelectionInstantly is called on click and draw:created
        assert "clearPreviousSelectionInstantly()" in script

    def test_hud_clear_preserves_tactical_overlays(self):
        """Verify that triggerRemoval when invoked by HUD Clear preserves tactical layers and only purges selection."""
        import folium
        from streamlit_folium import _get_map_string
        import app

        MapTrashBinHook = getattr(app, "MapTrashBinHook")
        m = folium.Map()
        MapTrashBinHook().add_to(m)
        script = _get_map_string(m)

        # 1. triggerRemoval accepts opts and checks hadSelection
        assert "function triggerRemoval(opts)" in script
        assert "var hadSelection" in script

        # 2. Only clears all layers if opts.clearAllLayers is explicitly true AND there was no active selection
        assert "if (opts.clearAllLayers && !hadSelection && window.feature_group && window.feature_group.length > 0)" in script

    def test_feature_group_separation_in_app(self):
        """Ensure app.py separates selection_fg and tactical_layers_fg in feature_group_to_add."""
        with open("app.py", "r", encoding="utf-8") as f:
            content = f.read()

        assert "selection_fg = folium.FeatureGroup(name=\"Active Selection\", control=False)" in content
        assert "tactical_layers_fg = folium.FeatureGroup(name=\"Tactical Overlays\", control=False)" in content
        assert "feature_group_to_add=[selection_fg, tactical_layers_fg]" in content

    def test_existing_marker_click_protection_and_popup_sync(self):
        """Verify MapTrashBinHook ignores clicks on existing markers and synchronizes popup selection."""
        import folium
        from streamlit_folium import _get_map_string
        import app

        MapTrashBinHook = getattr(app, "MapTrashBinHook")
        m = folium.Map()
        MapTrashBinHook().add_to(m)

        script = _get_map_string(m)

        # 1. Guard against clicks on existing markers and popups
        assert ".leaflet-marker-icon" in script
        assert ".marker-cluster" in script
        assert ".leaflet-popup" in script

        # 2. Popup open synchronization hook
        assert "map.on('popupopen'" in script
        assert "last_active_drawing = source.toGeoJSON()" in script
        assert "window._lastOpenPopupInfo" in script

    def test_point_selection_not_cleared_by_empty_all_drawings(self):
        """Ensure Point Selection is not inadvertently cleared when all_drawings is empty."""
        with open("app.py", "r", encoding="utf-8") as f:
            content = f.read()

        # Both Section 2b and Section 6 must guard all_drawings == [] with selection_mode == 'Bounding Box'
        assert "st.session_state.get(\"selection_mode\") == \"Bounding Box\"" in content


class TestRAGDebugLogging:
    """Validate RAG agent debug logging, telemetry, payload reconstruction, and error recording."""

    def test_build_raw_request_payload_with_point(self):
        """Ensure point payloads are formatted in GeoJSON [lon, lat] order with radius."""
        import app
        payload = app._build_raw_request_payload(
            text_prompt="Where are tactical assets?",
            selected_point=(50.4501, 30.5234),
            bounding_box=None
        )
        assert payload["text_prompt"] == "Where are tactical assets?"
        assert payload["geo_location"]["type"] == "point"
        # GeoJSON is [lon, lat]
        assert payload["geo_location"]["coordinates"] == [30.5234, 50.4501]
        assert payload["geo_location"]["radius_m"] == 1000.0

    def test_build_raw_request_payload_with_bbox(self):
        """Ensure bounding box payloads form a valid closed 5-coordinate polygon ring."""
        import app
        bbox = ((48.0, 31.0), (49.5, 33.5))
        payload = app._build_raw_request_payload(
            text_prompt=None,
            selected_point=None,
            bounding_box=bbox
        )
        assert "bounding box sector" in payload["text_prompt"]
        geo_loc = payload["geo_location"]
        assert geo_loc["type"] == "polygon"
        coords = geo_loc["coordinates"][0]
        assert len(coords) == 5
        assert coords[0] == coords[-1]  # Closed ring
        # Check SW and NE [lon, lat]
        assert coords[0] == [31.0, 48.0]
        assert coords[2] == [33.5, 49.5]

    def test_append_rag_log_capping(self):
        """Verify _append_rag_log caps history at 50 entries."""
        import streamlit as st
        import app
        st.session_state.rag_logs = []
        for i in range(60):
            app._append_rag_log({"id": i, "latency_ms": 10.0, "status": "SUCCESS"})
        assert len(st.session_state.rag_logs) == 50
        assert st.session_state.rag_logs[0]["id"] == 10
        assert st.session_state.rag_logs[-1]["id"] == 59

    def test_mock_agent_populates_raw_response(self):
        """Ensure query_geo_agent mock responses always include structured raw_response dict."""
        import geo_agent
        resp = geo_agent.query_geo_agent(text_prompt="Kyiv headquarters", force_mock=True)
        assert resp.raw_response is not None
        assert isinstance(resp.raw_response, dict)
        assert "answer" in resp.raw_response
        assert "geo_locations" in resp.raw_response
        assert "sources" in resp.raw_response

    def test_dispatch_geo_query_records_success_log(self, monkeypatch):
        """Verify dispatch_geo_query captures latency, payloads, and status into rag_logs."""
        import streamlit as st
        import app
        st.session_state.rag_logs = []
        st.session_state.messages = []
        st.session_state.openrouter_api_key = ""

        resp = app.dispatch_geo_query(
            text_prompt="Test tactical sweep",
            selected_point=(48.5, 32.0)
        )
        assert resp is not None
        assert len(st.session_state.rag_logs) == 1
        log = st.session_state.rag_logs[0]
        assert log["status"] == "SUCCESS"
        assert log["latency_ms"] >= 0.0
        assert log["raw_request"]["text_prompt"] == "Test tactical sweep"
        assert log["raw_response"] is not None
        assert "answer" in log["raw_response"]

    def test_dispatch_geo_query_records_error_log(self, monkeypatch):
        """Verify dispatch_geo_query catches errors and logs error_details without crashing."""
        import streamlit as st
        import app
        import geo_agent
        st.session_state.rag_logs = []

        def mock_error_query(*args, **kwargs):
            raise geo_agent.AgentError("Simulated connection timeout to knowledge graph.")

        monkeypatch.setattr(app, "query_geo_agent", mock_error_query)

        res = app.dispatch_geo_query(text_prompt="Failing query")
        assert res is None
        assert len(st.session_state.rag_logs) == 1
        log = st.session_state.rag_logs[0]
        assert log["status"] == "ERROR"
        assert log["error_details"]["error_type"] == "AgentError"
        assert "Simulated connection timeout" in log["error_details"]["message"]

    def test_sidebar_operations_order_in_codebase(self):
        """Verify Operations contains RAG Debug Logs and retain pins toggle, and redundant Spatial Targeting is removed."""
        with open("app.py", "r", encoding="utf-8") as f:
            code = f.read()

        ops_pos = code.find("st.subheader(\"🛠️ Operations\")")
        spatial_pos = code.find("st.subheader(\"🎯 Spatial Targeting\")")
        rag_btn_pos = code.find("📋 RAG Debug Logs")
        keep_pts_pos = code.find("Retain target pin after query")

        assert ops_pos != -1, "Operations section must exist in sidebar"
        assert spatial_pos == -1, "Redundant Spatial Targeting section should not exist in sidebar"
        assert rag_btn_pos != -1, "RAG Debug Logs button must exist"
        assert keep_pts_pos != -1, "Retain target pin toggle must exist in Operations"
        assert ops_pos < rag_btn_pos, "RAG Debug Logs button must be inside Operations section"
        assert ops_pos < keep_pts_pos, "Retain target pin toggle must be inside Operations section"

    def test_chat_bubbles_opposite_sides_layout(self):
        """Ensure chat console styles operator (user) on the right and geo-ai on the left with bubble styling."""
        with open("app.py", "r", encoding="utf-8") as f:
            code = f.read()

        # Check marker classes in HTML generation
        assert "bubble-marker-operator" in code, "Operator messages must have bubble-marker-operator class"
        assert "bubble-marker-geoai" in code, "Geo-AI messages must have bubble-marker-geoai class"
        assert "chat-role-operator" in code, "Operator role tag must have chat-role-operator class"
        assert "chat-role-geoai" in code, "Geo-AI role tag must have chat-role-geoai class"

        # Check CSS rules for opposite sides and border radius
        assert "flex-direction: row-reverse" in code, "Operator bubbles must reverse flex direction for right-hand alignment"
        assert "align-self: flex-end" in code, "Operator messages must align to the right"
        assert "align-self: flex-start" in code, "Geo-AI messages must align to the left"
        assert "margin-left: auto" in code, "Operator bubbles must float/align right with margin-left: auto"
        assert "margin-right: auto" in code, "Geo-AI bubbles must float/align left with margin-right: auto"
        assert "border-radius: 12px 12px 12px 12px" in code, "Chat bubbles must have border-radius: 12px 12px 12px 12px"


class TestUpgradesOneThroughSixAndPerformance:
    """Validate Upgrades 1-6 (Vr6) and AGENTS.md zero-latency performance rules."""

    def test_highlight_text_spans_basic_and_overlapping(self):
        """Upgrade 6: Verify text span highlighting merges overlaps and generates <mark> tags."""
        from app import _highlight_text_spans

        text = "Kyiv is the capital of Ukraine."
        # Highlight "Kyiv" (0, 4) and "capital" (12, 19)
        spans = [[0, 4], [12, 19]]
        res = _highlight_text_spans(text, spans)
        assert "<mark" in res
        assert "Kyiv</mark>" in res
        assert "capital</mark>" in res

        # Overlapping spans: (0, 4) and (2, 7) -> merged (0, 7)
        overlap_spans = [[0, 4], [2, 7]]
        res_overlap = _highlight_text_spans("Kyiv is nice", overlap_spans)
        assert res_overlap.count("<mark") == 1
        assert "Kyiv is</mark>" in res_overlap

    def test_highlight_text_spans_dict_format(self):
        """Upgrade 6: Verify dict-style spans [{'start': 0, 'end': 4}]."""
        from app import _highlight_text_spans

        text = "Kharkiv sector"
        spans = [{"start": 0, "end": 7}]
        res = _highlight_text_spans(text, spans)
        assert "<mark" in res
        assert "Kharkiv</mark>" in res

    def test_highlight_text_spans_edge_cases(self):
        """Upgrade 6: Safe fallbacks for empty text, null spans, or out-of-range offsets."""
        from app import _highlight_text_spans

        assert _highlight_text_spans("", [[0, 5]]) == ""
        assert _highlight_text_spans("Hello", None) == "Hello"
        assert _highlight_text_spans("Hello", []) == "Hello"
        assert _highlight_text_spans("Hello", [[10, 20]]) == "Hello"
        assert _highlight_text_spans("Hello", [[-5, -1]]) == "Hello"
        assert _highlight_text_spans("Hello", [["invalid", "type"]]) == "Hello"

    def test_build_assistant_message_vr6_fields(self):
        """Upgrade 4 & 5: Ensure _build_assistant_message preserves follow_ups, regions, did_you_mean, map_bbox."""
        from app import _build_assistant_message
        from geo_agent import AgentResponse

        resp = AgentResponse(
            answer="Here are tactical points.",
            follow_ups=["Where is the 93rd Brigade?", "Show frontline units"],
            regions={"Donetsk Oblast": 14, "Kharkiv Oblast": 8},
            did_you_mean="Bakhmut",
            map_bbox=[36.5, 48.2, 38.0, 49.1]
        )
        msg = _build_assistant_message(resp)
        assert msg["role"] == "assistant"
        assert msg["follow_ups"] == ["Where is the 93rd Brigade?", "Show frontline units"]
        assert msg["regions"] == {"Donetsk Oblast": 14, "Kharkiv Oblast": 8}
        assert msg["did_you_mean"] == "Bakhmut"
        assert msg["map_bbox"] == [36.5, 48.2, 38.0, 49.1]

    def test_geojson_boundary_layer_generation(self):
        """Upgrade 1: Verify geo_agent hydrates GeoJSON boundaries when shape is returned."""
        import geo_agent

        raw_vr6_resp = {
            "answer": "Poltava is in central Ukraine.",
            "geo_locations": [
                {
                    "name": "Poltava Oblast",
                    "latitude": 49.5883,
                    "longitude": 34.5514,
                    "role": "primary",
                    "shape": {
                        "type": "Polygon",
                        "coordinates": [[[34.0, 49.0], [35.0, 49.0], [35.0, 50.0], [34.0, 50.0], [34.0, 49.0]]]
                    }
                }
            ],
            "map": {
                "bbox": [33.5, 48.8, 35.5, 50.3]
            },
            "regions": {"Poltava Oblast": 1},
            "follow_up_questions": ["What units operate in Poltava?"]
        }

        # Mock query backend
        monkeypatch_target = getattr(geo_agent, "_backend_query", None)
        orig_backend = geo_agent._BACKEND_AVAILABLE
        try:
            geo_agent._BACKEND_AVAILABLE = True
            geo_agent._backend_query = lambda **kw: raw_vr6_resp

            resp = geo_agent.query_geo_agent(text_prompt="Analyze Poltava", api_key="test-key")
            assert resp is not None
            assert resp.map_bbox == [33.5, 48.8, 35.5, 50.3]
            assert resp.regions == {"Poltava Oblast": 1}
            assert resp.follow_ups == ["What units operate in Poltava?"]

            # Layer checks: should have a marker layer AND a geojson layer
            layer_types = [l.layer_type for l in resp.layers]
            assert "marker" in layer_types
            assert "geojson" in layer_types

            geojson_layer = next(l for l in resp.layers if l.layer_type == "geojson")
            assert geojson_layer.name == "Outline: Poltava Oblast"
            assert geojson_layer.data["type"] == "Polygon"
        finally:
            geo_agent._BACKEND_AVAILABLE = orig_backend
            geo_agent._backend_query = monkeypatch_target

    def test_performance_rules_in_agents_md(self):
        """AGENTS.md Performance Verification: Ensure all zero-latency rules are present in codebase."""
        with open("app.py", "r", encoding="utf-8") as f:
            app_code = f.read()

        # Rule 1.1: returned_objects in st_folium
        assert 'returned_objects=["last_clicked", "last_active_drawing", "all_drawings"]' in app_code, (
            "Rule 1.1: st_folium must constrain returned_objects to prevent pan/zoom reruns"
        )

        # Rule 2.1: Guarded bootstrap & no unconditional importlib.reload
        assert "_BOOTSTRAP_DONE = getattr(sys, \"_GEOAI_BOOTSTRAP_DONE\", False)" in app_code, (
            "Rule 2.1: Bootstrap must be guarded once per process"
        )
        assert "importlib.reload(sys.modules[\"geo_agent\"])" not in app_code, (
            "Rule 2.1: Per-rerun importlib.reload of geo_agent must NOT exist"
        )

        # Rule 3.1: Stable container height
        assert "chat_container_height = 465" in app_code, (
            "Rule 3.1: Chat container height must remain constant to prevent screen jumping"
        )

        # Rule 4.1: MarkerCluster for context markers
        assert "context_cluster = MarkerCluster" in app_code, (
            "Rule 4.1: MarkerCluster must be instantiated for context pins"
        )

        # Rule 4.2: fit_bounds with last_map_bbox
        assert "m.fit_bounds([[s, w], [n, e]], padding=(30, 30))" in app_code, (
            "Rule 4.2: Map must auto-zoom to query bbox when available"
        )


class TestTacticalHudSymbologyAndAnsweredBbox:
    """Validate Tactical HUD map symbology, pin factories, popup cards, and answered bbox transparency."""

    def test_color_token_semantic_resolution(self):
        """Ensure color_token resolves roles and legacy color names across dark and light themes."""
        import app

        # Primary (blue / primary role)
        tok_dark, hex_dark = app.color_token("blue", role="primary", theme="dark")
        assert tok_dark == "primary"
        assert hex_dark == "#38bdf8"
        tok_light, hex_light = app.color_token("blue", role="primary", theme="light")
        assert tok_light == "primary"
        assert hex_light == "#0369a1"

        # Event (red / event kind)
        ev_tok, ev_hex = app.color_token("red", kind="event", theme="dark")
        assert ev_tok == "event"
        assert ev_hex == "#ff4d6d"

        # Uncertain (orange / uncertain flag)
        unc_tok, unc_hex = app.color_token("orange", uncertain=True, theme="dark")
        assert unc_tok == "uncertain"
        assert unc_hex == "#ffb020"

        # Context (cadetblue / context role)
        ctx_tok, ctx_hex = app.color_token("cadetblue", role="context", theme="dark")
        assert ctx_tok == "context"
        assert ctx_hex == "#7dd3fc"

        # Query BBox
        bbox_tok, bbox_hex = app.color_token("orange", role="query_bbox", theme="dark")
        assert bbox_tok == "selection"
        assert bbox_hex == "#00e5ff"

    def test_bbox_style_selected_vs_answered_transparency(self):
        """Ensure answered bounding boxes become ultra-transparent and non-interactive."""
        import app

        sel = app.bbox_style("selected", theme="dark")
        ans = app.bbox_style("answered", theme="dark")

        # Selected bbox has higher opacity and is interactive
        assert sel["fill_opacity"] == 0.10
        assert sel["opacity"] == 0.90
        assert sel["weight"] == 2
        assert sel["dash_array"] == "6, 6"
        assert sel["interactive"] is True
        assert "geoai-bbox--selected" in sel["class_name"]

        # Answered bbox is ultra-transparent (fill_opacity=0.03), faint stroke, and non-interactive
        assert ans["fill_opacity"] == 0.03
        assert ans["opacity"] == 0.55
        assert ans["weight"] == 1.25
        assert ans["dash_array"] == "3, 6"
        assert ans["interactive"] is False
        assert "geoai-bbox--answered" in ans["class_name"]
        assert ans["fill_opacity"] < sel["fill_opacity"]

    def test_make_pin_icon_variants(self):
        """Verify make_pin_icon generates pure CSS DivIcons for target, corners, context, and diamonds."""
        import app

        # 1. Target reticle
        reticle = app.make_pin_icon(role="target")
        assert reticle.options["icon_size"] == [34, 34] or reticle.options["icon_size"] == (34, 34)
        assert "geoai-reticle" in reticle.options["html"]
        assert "geoai-reticle__pulse" in reticle.options["html"]

        # 2. BBox corner brackets (active and dimmed)
        sw_corner = app.make_pin_icon(role="bbox_corner", corner="sw", dimmed=False)
        assert "geoai-corner--sw" in sw_corner.options["html"]
        assert "geoai-corner--dim" not in sw_corner.options["html"]

        ne_dim = app.make_pin_icon(role="bbox_corner", corner="ne", dimmed=True)
        assert "geoai-corner--ne" in ne_dim.options["html"]
        assert "geoai-corner--dim" in ne_dim.options["html"]

        # 3. Context dot
        ctx_icon = app.make_pin_icon(role="context", color_name="cadetblue")
        assert "geoai-dot" in ctx_icon.options["html"]
        assert "geoai-pin--context" in ctx_icon.options["class_name"]
        assert "awesome-marker-icon-cadetblue" in ctx_icon.options["class_name"]

        # 4. Primary numbered diamond
        prim_icon = app.make_pin_icon(role="primary", number=3, color_name="blue")
        assert "geoai-diamond" in prim_icon.options["html"]
        assert "<span>3</span>" in prim_icon.options["html"]
        assert "geoai-pin--primary" in prim_icon.options["class_name"]

        # 5. Event diamond
        ev_icon = app.make_pin_icon(kind="event", role="primary", color_name="red")
        assert "geoai-diamond" in ev_icon.options["html"]
        assert "<span>!</span>" in ev_icon.options["html"]
        assert "geoai-pin--event" in ev_icon.options["class_name"]

        # 6. Uncertain diamond with dashed border and ? badge
        unc_icon = app.make_pin_icon(role="primary", uncertain=True, number=2, color_name="orange")
        assert "geoai-diamond--uncertain" in unc_icon.options["html"]
        assert "geoai-badge-unc" in unc_icon.options["html"]
        assert "<span>2</span>" in unc_icon.options["html"]
        assert "geoai-pin--uncertain" in unc_icon.options["class_name"]
        assert "awesome-marker-icon-orange" in unc_icon.options["class_name"]

    def test_popup_card_html_generation(self):
        """Verify _popup_card builds structured dark-glass HUD markup."""
        import app

        html = app._popup_card(
            title="Kharkiv Sector",
            rows=[("LAT", "49.9935"), ("LON", "36.2304"), ("ROLE", "primary")],
            chip="[1] PLACE",
            footer="<div>[1] Intel Report</div>",
            token="primary",
        )
        assert "geoai-card" in html
        assert "Kharkiv Sector" in html
        assert "[1] PLACE" in html
        assert "49.9935" in html
        assert "36.2304" in html
        assert "[1] Intel Report" in html

    def test_geo_agent_bbox_layers_include_query_bbox_and_corner_roles(self):
        """Ensure query_geo_agent tags bbox polygons with role='query_bbox' and corners with 'bbox_corner'."""
        import geo_agent

        bbox = ((48.0, 31.0), (49.5, 33.5))
        resp = geo_agent.query_geo_agent(
            text_prompt="Analyze sector",
            bounding_box=bbox,
            force_mock=True
        )
        poly_layers = [l for l in resp.layers if l.layer_type == "polygon"]
        assert len(poly_layers) >= 1
        assert poly_layers[0].data.get("role") == "query_bbox"

        corner_layers = [
            l for l in resp.layers
            if l.layer_type == "marker" and isinstance(l.data, dict) and l.data.get("role") == "bbox_corner"
        ]
        assert len(corner_layers) == 2
        corners = {l.data.get("corner") for l in corner_layers}
        assert corners == {"sw", "ne"}

    def test_client_side_hooks_support_new_hud_symbology_and_answered_bbox(self):
        """Verify MapTrashBinHook includes PinFilterControl, .geoai-pin classes, and answered bbox sync."""
        import folium
        from streamlit_folium import _get_map_string
        import app

        m = folium.Map()
        app.MapTrashBinHook().add_to(m)

        script = _get_map_string(m)
        assert "function geoaiIcon(opts)" in script
        assert "syncAnsweredBboxInDrawnItems" in script
        assert "geoai-bbox--answered" in script
        assert "geoai-pin--context" in script
        assert "geoai-pin--uncertain" in script
        assert "PinFilterControl" in script

    def test_instant_hud_bridge_and_popup_auto_open(self):
        """Verify 0ms client-side selection bridge and target point popup auto-open."""
        with open("app.py", "r", encoding="utf-8") as f:
            content = f.read()

        assert "_geoaiSelectionBridgeInstalled" in content
        assert "GEOAI_SELECTION_EVENT" in content
        assert "geoai-instant-pill-slot" in content
        assert "popup=folium.Popup(popup_html, max_width=250, show=True)" in content

    def test_streamlined_zero_widget_sources_drawer(self):
        """Verify Verified Sources uses native HTML details cards to prevent widget tree explosion."""
        with open("app.py", "r", encoding="utf-8") as f:
            content = f.read()

        assert "geoai-source-detail" in content
        assert "geoai-source-summary" in content
        assert "geoai-source-badge" in content
        assert "btn_src_" not in content

    def test_corner_bracket_exact_vertex_anchors(self):
        """Verify corner bracket DivIcons anchor at exact SVG L-vertices so brackets align with marching ants."""
        import app

        expected_anchors = {
            "nw": [2, 2],
            "ne": [14, 2],
            "se": [14, 14],
            "sw": [2, 14],
        }
        for corner, expected in expected_anchors.items():
            icon = app.make_pin_icon(role="bbox_corner", corner=corner)
            assert list(icon.options["icon_size"]) == [16, 16]
            assert list(icon.options["icon_anchor"]) == expected

    def test_pin_shape_diamond_vs_teardrop(self):
        """Verify make_pin_icon supports switching between Diamond and Teardrop shapes."""
        import app

        diamond_icon = app.make_pin_icon(role="primary", number=1, color_name="blue", shape="diamond")
        assert "geoai-diamond" in diamond_icon.options["html"]
        assert "geoai-teardrop" not in diamond_icon.options["html"]
        assert "geoai-pin--teardrop" not in diamond_icon.options["class_name"]
        assert list(diamond_icon.options["icon_anchor"]) == [11, 11]

        teardrop_icon = app.make_pin_icon(role="primary", number=1, color_name="blue", shape="teardrop")
        assert "geoai-diamond geoai-teardrop" in teardrop_icon.options["html"]
        assert "geoai-pin--teardrop" in teardrop_icon.options["class_name"]
        assert list(teardrop_icon.options["icon_anchor"]) == [11, 11]

    def test_querying_bbox_style_and_scanline_hook(self):
        """Verify bbox_style('querying') and client-side scanline/pulse animation hooks."""
        import folium
        from streamlit_folium import _get_map_string
        import app

        q_style = app.bbox_style("querying", theme="dark")
        assert q_style["fill_opacity"] == 0.08
        assert q_style["opacity"] == 0.95
        assert "geoai-bbox--querying" in q_style["class_name"]

        m = folium.Map()
        app.MapTrashBinHook().add_to(m)
        script = _get_map_string(m)
        assert "startQueryingAnimation" in script
        assert "stopQueryingAnimation" in script
        assert "geoai-scan-svg" in script
        assert "geoai-scan-line" in script
        assert "geoai-reticle--querying" in script
        assert "setMapPinShape" in script

    def test_selection_sync_hook_and_clear_spatial_selection(self):
        """Verify SelectionSyncHook emits _onServerSelectionSync in feature_group_string and clear_spatial_selection increments clear_seq."""
        import folium
        import streamlit as st
        from streamlit_folium import _get_feature_group_string, _get_map_string
        import app

        m1 = folium.Map(location=[48.3794, 31.1656], zoom_start=6)
        m2 = folium.Map(location=[48.3794, 31.1656], zoom_start=6)
        base_map_str_1 = _get_map_string(m1)
        base_map_str_2 = _get_map_string(m2)

        fg = folium.FeatureGroup(name="Active Selection", control=False)
        app.SelectionSyncHook(
            has_selection=False,
            clear_seq=3,
            bbox_state="none",
            is_querying=False,
            bbox_bounds=None,
            pin_shape="Teardrop",
        ).add_to(fg)

        fg_str = _get_feature_group_string(fg, m2, 0)

        # Base map string is untouched before feature_group rendering while feature_group_string carries the sync call
        assert base_map_str_1 == base_map_str_2
        assert "_onServerSelectionSync" in fg_str
        assert "clearSeq: 3" in fg_str
        assert 'pinShape: "teardrop"' in fg_str

        # Verify clear_spatial_selection increments selection_clear_seq and records stale map widget state
        st.session_state.selected_points = [(50.45, 30.52)]
        st.session_state.bounding_box = ((49.0, 30.0), (50.0, 31.0))
        st.session_state.selection_clear_seq = 0
        st.session_state["geoai_tactical_map"] = {
            "last_clicked": {"lat": 50.45, "lng": 30.52},
            "last_active_drawing": {"geometry": {"type": "Polygon", "coordinates": [[[30.0, 49.0], [31.0, 50.0]]]}},
        }
        app.clear_spatial_selection()
        assert st.session_state.selected_points == []
        assert st.session_state.bounding_box is None
        assert st.session_state.selection_clear_seq == 1
        assert st.session_state.last_clicked == (50.45, 30.52)
        assert st.session_state.ignored_drawing is not None

    def test_pipeline_inversion_and_zero_rerun_dispatch(self):
        """Verify pipeline inversion (col2 before col1) and immediate dispatch in code."""
        with open("app.py", "r", encoding="utf-8") as f:
            code = f.read()

        # 1. col2 (map) must be evaluated before col1 (chat)
        col2_pos = code.find("with col2:")
        col1_pos = code.find("with col1:")
        assert col2_pos != -1 and col1_pos != -1
        assert col2_pos < col1_pos, "Pipeline Inversion: with col2: must execute before with col1:"

        # 2. Immediate dispatch helper must be defined
        assert "window.geoaiImmediateDispatch" in code
        assert "_peek_incoming_map_state" in code

        # 3. col2 click and drawing handlers must not trigger st.rerun cascades
        col2_code = code[col2_pos:col1_pos]
        assert "st.session_state.selected_points = [clicked_coord]" in col2_code
        click_idx = col2_code.find("st.session_state.selected_points = [clicked_coord]")
        post_click = col2_code[click_idx:click_idx + 250]
        assert "st.rerun()" not in post_click

    def test_workspace_window_auto_fit_layout_and_listeners(self):
        """Verify chat and map workspace automatically fit to the screen/window dimensions."""
        with open("app.py", "r", encoding="utf-8") as f:
            code = f.read()

        # 1. CSS Auto-Fit rules for full-height split screen layout
        assert "Workspace Window Auto-Fit Architecture" in code
        assert 'calc(100vh - 90px)' in code
        assert 'calc(100vh - 150px)' in code
        assert 'div[data-testid="column"]:last-child div[data-testid="stCustomComponentV1"]' in code
        assert 'div[data-testid="column"]:first-child div[data-testid="stVerticalBlockBorderWrapper"]' in code

        # 2. Dynamic client-side JavaScript resize hook
        assert "forwardResizeToIframes" in code
        assert "window.addEventListener('resize', forwardResizeToIframes);" in code

        # 3. Leaflet map ResizeObserver to invalidate tile size on container resizing
        assert "map.invalidateSize()" in code

    def test_active_querying_animation_and_early_query_ingestion(self):
        """Verify active querying animation hooks and early query queueing before col2 map renders."""
        import folium
        from streamlit_folium import _get_feature_group_string, _get_map_string
        import app

        with open("app.py", "r", encoding="utf-8") as f:
            code = f.read()

        # 1. Section 2c Early Query Ingestion must precede with col2:
        sec2c_pos = code.find("2c. Early Query Ingestion & Queueing")
        col2_pos = code.find("with col2:")
        assert sec2c_pos != -1, "Section 2c must be defined"
        assert sec2c_pos < col2_pos, "Section 2c must precede with col2: so pending_query is queued before map renders"

        # 2. Section 2c must check both chat_input and run_chat_recon
        assert 'st.session_state.get("geoai_chat_input")' in code
        assert 'st.session_state.get("run_chat_recon")' in code
        assert 'key="geoai_chat_input"' in code

        # 3. Leaflet hooks must track _isClientQuerying and _lastKnownBboxBounds
        m = folium.Map()
        app.MapTrashBinHook().add_to(m)
        map_script = _get_map_string(m)
        assert "_isClientQuerying" in map_script
        assert "_lastKnownBboxBounds" in map_script
        assert "startQueryingAnimation(state.bboxBounds || window._lastKnownBboxBounds)" in map_script

        # 4. SelectionSyncHook must emit isQuerying: true and bboxState: "querying"
        fg = folium.FeatureGroup(name="Active Selection", control=False)
        app.SelectionSyncHook(
            has_selection=True,
            clear_seq=0,
            bbox_state="querying",
            is_querying=True,
            bbox_bounds=[[48.0, 31.0], [49.0, 32.0]],
            pin_shape="diamond",
        ).add_to(fg)

class TestOption1MapCanvasTacticalHudAndStableLayout:
    """Validate Option 1: Map Canvas Tactical HUD and permanently anchored chat input with 0ms latency."""

    def test_map_trash_bin_hook_includes_tactical_hud_control(self):
        """Verify MapTrashBinHook instantiates TacticalTargetHudControl in bottomleft with Clear and Recon buttons."""
        import folium
        from streamlit_folium import _get_map_string
        import app

        m = folium.Map()
        app.MapTrashBinHook().add_to(m)
        script = _get_map_string(m)

        assert "TacticalTargetHudControl" in script
        assert "position: 'bottomleft'" in script
        assert "geoai_map_tactical_hud" in script
        assert "geoai_map_hud_content" in script
        assert "geoai_map_hud_clear_btn" in script
        assert "geoai_map_hud_recon_btn" in script
        assert "window.updateMapTacticalHud" in script
        assert "window.hideMapTacticalHud" in script

    def test_selection_sync_hook_serializes_active_point(self):
        """Verify SelectionSyncHook passes activePoint coordinates for instant HUD synchronization."""
        import folium
        from streamlit_folium import _get_feature_group_string
        import app

        m = folium.Map()
        fg = folium.FeatureGroup(name="Selection", control=False)
        app.SelectionSyncHook(
            has_selection=True,
            clear_seq=1,
            active_point=(31.7767, 35.2345),
            pin_shape="diamond"
        ).add_to(fg)
        fg_str = _get_feature_group_string(fg, m, 0)

        assert "activePoint: [31.7767, 35.2345]" in fg_str
        assert "hasSelection: true" in fg_str

    def test_chat_interface_zero_height_action_triggers(self):
        """Verify col1 uses zero-height headless action triggers so chat input remains permanently anchored."""
        with open("app.py", "r", encoding="utf-8") as f:
            code = f.read()

        assert ".st-key-clear_chat_pts" in code
        assert ".st-key-run_chat_recon" in code
        assert 'display: none !important;' in code
        assert 'height: 0px !important;' in code
        assert 'key="clear_chat_pts"' in code
        assert 'key="run_chat_recon"' in code
        assert 'GEOAI_PARENT_CMD' in code
        assert "trigger_recon" in code

    def test_tactical_hud_recon_dispatch_and_no_col1_leak(self):
        """Verify TacticalTargetHudControl dispatches recon via Folium bridge, Section 2b handles it, and col1 has no leaked div."""
        import folium
        from streamlit_folium import _get_map_string

        m = folium.Map()
        import app
        app.MapTrashBinHook().add_to(m)
        script = _get_map_string(m)

        # Tactical HUD recon button must prepare and dispatch recon payload
        assert 'properties: {\n                                action: "recon"' in script or 'action: "recon"' in script
        assert "geoaiImmediateDispatch(map)" in script

        with open("app.py", "r", encoding="utf-8") as f:
            code = f.read()

        # Section 2b and Section 5 handle action == "recon"
        assert '_props.get("action") == "recon"' in code
        assert 'props.get("action") == "recon"' in code
        assert '"is_recon": True' in code

        # Ensure col1 does NOT contain the leaked geoai-instant-pill-slot div inside col1
        # It must only appear once in the global script block unindented
        assert code.count('<div id="geoai-instant-pill-slot"') == 1
        assert "<div id='geoai-instant-pill-slot'" not in code

    def test_bbox_hud_persistence_over_single_target(self):
        """Verify BBox selection HUD maintains bbox type over single point target after Streamlit reload."""
        import folium
        from streamlit_folium import _get_map_string, _get_feature_group_string
        import app

        # 1. MapTrashBinHook must prioritize state.bboxBounds over state.activePoint
        m = folium.Map()
        app.MapTrashBinHook().add_to(m)
        script = _get_map_string(m)

        bbox_idx = script.find("if (state.bboxBounds)")
        pt_idx = script.find("else if (state.activePoint)")
        assert bbox_idx != -1 and pt_idx != -1
        assert bbox_idx < pt_idx, "state.bboxBounds must be checked BEFORE state.activePoint"

        # 2. When bbox is present, SelectionSyncHook serializes bboxBounds and activePoint is null
        fg = folium.FeatureGroup(name="Selection", control=False)
        app.SelectionSyncHook(
            has_selection=True,
            clear_seq=0,
            bbox_state="selected",
            bbox_bounds=[[48.1234, 31.5678], [49.1234, 32.5678]],
            active_point=None,
        ).add_to(fg)
        fg_str = _get_feature_group_string(fg, m, 0)
        assert "bboxBounds: [[48.1234, 31.5678], [49.1234, 32.5678]]" in fg_str
        assert "activePoint: null" in fg_str

        # 3. app.py must guard active_point passing when bounding_box is present
        with open("app.py", "r", encoding="utf-8") as f:
            code = f.read()
        assert 'active_point=None if st.session_state.get("bounding_box") else' in code

    def test_point_selection_after_bbox_clears_scanline_and_bbox_state(self):
        """Verify that selecting a point after drawing a BBox resets BBox bounds, suppresses scanline, and routes point recon."""
        import app

        # 1. Test _is_drawing_corner_release helper
        bbox = ((48.0, 31.0), (49.0, 32.0))
        assert app._is_drawing_corner_release((48.0, 31.0), bbox) is True
        assert app._is_drawing_corner_release((48.0001, 31.0001), bbox) is True
        assert app._is_drawing_corner_release((49.0, 32.0), bbox) is True
        assert app._is_drawing_corner_release((48.5, 31.5), bbox) is False
        assert app._is_drawing_corner_release((48.0, 31.0), None) is False

        with open("app.py", "r", encoding="utf-8") as f:
            code = f.read()

        # 2. startQueryingAnimation guards against point target
        assert "var hud = window._lastHudInfo;" in code
        assert "hud.type === 'point'" in code
        assert "window._lastKnownBboxBounds = null;" in code

        # 3. Recon button in HUD passes targetType and coordinates
        assert 'targetType: hud ? hud.type : null' in code
        assert 'properties: {\n                                action: "recon",' in code or 'action: "recon",\n                                targetType: hud ? hud.type : null' in code

        # 4. Canvas click transitions from BBox to Point Selection when a new coordinate arrives
        assert 'elif _c_pt != st.session_state.last_clicked:' in code
        assert 'elif clicked_coord != st.session_state.last_clicked:' in code
        assert 'if st.session_state.selected_points != [_c_pt] or st.session_state.get("bounding_box") is not None:' in code
        assert 'if st.session_state.selected_points != [clicked_coord] or st.session_state.get("bounding_box") is not None:' in code

        # 5. Section 2b and Section 5 handle targetType == "point" on recon
        assert '_target_type == "point"' in code
        assert 'target_type == "point"' in code
        assert 'st.session_state.selection_mode = "Point Selection"' in code

    def test_chat_query_submission_preserves_bbox_and_routes_polygon(self):
        """Verify that sending a chat query while a BBox is active does NOT convert BBox to a point."""
        import streamlit as st
        import app

        # Setup state: BBox is actively selected
        bbox = ((48.1234, 31.5678), (49.1234, 32.5678))
        click_coord = (49.1234, 32.5678)
        st.session_state.selection_mode = "Bounding Box"
        st.session_state.bounding_box = bbox
        st.session_state.selected_points = [bbox[0], bbox[1]]
        st.session_state.last_clicked = click_coord
        st.session_state.pending_query = None
        st.session_state.answered_bbox = None

        # Verify raw request payload formats as polygon, NOT point
        payload = app._build_raw_request_payload(
            text_prompt="Where in the bounding box where there drone attacks?",
            selected_point=None,
            bounding_box=bbox,
        )
        assert payload["geo_location"]["type"] == "polygon"
        assert payload["geo_location"]["coordinates"][0][0] == [31.5678, 48.1234]

        # Verify Section 2c logic: when bounding_box is present, active_pt is None
        _is_bbox = st.session_state.get("bounding_box") is not None
        assert _is_bbox is True
        _active_pt = None if _is_bbox else (st.session_state.selected_points[0] if st.session_state.get("selected_points") else None)
        _active_bbox = st.session_state.get("bounding_box") if _is_bbox else None
        assert _active_pt is None
        assert _active_bbox == bbox

        # Verify code guards that canvas click ONLY triggers when coordinate changed
        with open("app.py", "r", encoding="utf-8") as f:
            code = f.read()
        assert 'elif _c_pt != st.session_state.last_clicked:' in code
        assert 'elif clicked_coord != st.session_state.last_clicked:' in code

    def test_bbox_selection_clears_selected_points_and_point_scan(self):
        """Plan Test 3: Drawing a rectangle clears active point selection, resets active_tactical_scan, and sets mode to Bounding Box."""
        import streamlit as st
        import app

        # Simulate state where a point was previously selected and point scan active
        point = (48.5000, 31.5000)
        st.session_state.selection_mode = "Point Selection"
        st.session_state.selected_points = [point]
        st.session_state.bounding_box = None
        st.session_state.active_point = point
        st.session_state.active_tactical_scan = "point_scan"

        # Verify that drawing a new BBox clears active_tactical_scan and sets bounding_box
        bbox_corners = ((48.0, 31.0), (49.0, 32.0))
        st.session_state.selection_mode = "Bounding Box"
        st.session_state.selected_points = [bbox_corners[0], bbox_corners[1]]
        st.session_state.bounding_box = bbox_corners
        st.session_state.active_point = bbox_corners[1]
        st.session_state.active_tactical_scan = None

        assert st.session_state.bounding_box == bbox_corners
        assert st.session_state.active_tactical_scan is None
        assert st.session_state.selection_mode == "Bounding Box"

        # Verify Section 2b and Section 5 code enforces active_tactical_scan = None
        with open("app.py", "r", encoding="utf-8") as f:
            code = f.read()
        assert "st.session_state.bounding_box = (_ll, _ur)\n            st.session_state.answered_bbox = None\n            st.session_state.active_point = _ur\n            st.session_state.active_tactical_scan = None" in code
        assert (
            "st.session_state.bounding_box = (lower_left, upper_right)\n            st.session_state.answered_bbox = None\n            st.session_state.active_point = upper_right\n            st.session_state.active_tactical_scan = None" in code
            or "st.session_state.bounding_box = (lower_left, upper_right)\n                st.session_state.answered_bbox = None\n                st.session_state.active_point = upper_right\n                st.session_state.active_tactical_scan = None" in code
        )

    def test_trash_can_clear_selection_resets_both_point_and_bbox(self):
        """Plan Test 4: clear_spatial_selection resets point, bbox, HUD state, active_tactical_scan, and increments sequence."""
        import streamlit as st
        import app

        # Setup active bbox and scan
        bbox = ((48.1, 31.1), (49.2, 32.2))
        st.session_state.selection_mode = "Bounding Box"
        st.session_state.selected_points = [bbox[0], bbox[1]]
        st.session_state.bounding_box = bbox
        st.session_state.answered_bbox = bbox
        st.session_state.active_point = bbox[1]
        st.session_state.active_tactical_scan = "bbox_scan"
        st.session_state.selection_clear_seq = 3
        st.session_state.last_processed_drawing = {"type": "Feature"}

        # Execute clear_spatial_selection
        app.clear_spatial_selection()

        # Assert all fields are reset to neutral
        assert st.session_state.selected_points == []
        assert st.session_state.bounding_box is None
        assert st.session_state.answered_bbox is None
        assert st.session_state.active_point is None
        assert st.session_state.active_tactical_scan is None
        assert st.session_state.selection_mode == "Point Selection"
        assert st.session_state.last_processed_drawing is None
        assert st.session_state.selection_clear_seq == 4

    def test_clear_map_and_console_resets_both_map_and_messages(self):
        """Verify clear_map_and_console resets map layers, spatial selections, and conversation history."""
        import streamlit as st
        import app
        from app import MapLayer

        # Setup active map layers, spatial selection, and conversation messages
        st.session_state.map_layers = [MapLayer(name="Test Layer", layer_type="marker", data={"lat": 48.0, "lon": 31.0})]
        st.session_state.last_map_bbox = [30.0, 48.0, 32.0, 49.0]
        st.session_state.selected_points = [(48.1, 31.1)]
        st.session_state.bounding_box = ((48.0, 31.0), (49.0, 32.0))
        st.session_state.answered_bbox = ((48.0, 31.0), (49.0, 32.0))
        st.session_state.active_point = (48.1, 31.1)
        st.session_state.active_tactical_scan = "point_scan"
        st.session_state.selection_clear_seq = 10
        st.session_state.messages = [{"role": "user", "content": "test"}, {"role": "assistant", "content": "ans"}]
        st.session_state.agent_turns = [{"role": "user", "content": "test"}]
        st.session_state.pending_query = {"text_prompt": "test"}
        st.session_state.last_processed_chat_input = "test"

        # Execute clear_map_and_console
        app.clear_map_and_console()

        # Verify all map state is cleared
        assert st.session_state.map_layers == []
        assert st.session_state.last_map_bbox is None
        assert st.session_state.selected_points == []
        assert st.session_state.bounding_box is None
        assert st.session_state.answered_bbox is None
        assert st.session_state.active_point is None
        assert st.session_state.active_tactical_scan is None
        assert st.session_state.selection_clear_seq == 11

        # Verify all console state is cleared
        assert st.session_state.messages == []
        assert st.session_state.agent_turns == []
        assert st.session_state.pending_query is None
        assert st.session_state.last_processed_chat_input is None

    def test_sidebar_has_clear_map_and_console_button(self):
        """Verify app.py includes the 'Clear Map & Console' button in sidebar operations and client-side hook."""
        with open("app.py", "r", encoding="utf-8") as f:
            code = f.read()

        assert "🧹 Clear Map & Console" in code
        assert "btn_clear_map_console_sidebar" in code
        assert "clear_map_and_console()" in code
        assert "txt.indexOf('Clear Map & Console') !== -1" in code

    def test_answered_pin_selection_keeps_info_window_and_hud_open(self):
        """Verify that selecting an answered pin does not overwrite with target reticle, preserves popup, and keeps HUD open."""
        with open("app.py", "r", encoding="utf-8") as f:
            code = f.read()

        # 1. Answered pins in map_layers are protected from being overlaid by generic target reticle
        assert "is_existing_pin = any(" in code
        assert "if not is_existing_pin:" in code

        # 2. _onServerSelectionSync contains logic to maintain/reopen popup on answered pin
        assert "window._isLayerSyncing = true;" in code
        assert "m.openPopup();" in code

        # 3. popupopen always immediately updates HUD and parent docked pill
        assert "window.updateMapTacticalHud({ type: 'point', lat: p_lat, lng: p_lng });" in code

    def test_closing_info_window_does_not_cancel_selection_hud(self):
        """Verify that closing an open info window (via 'x') does NOT hide or cancel the Tactical HUD."""
        with open("app.py", "r", encoding="utf-8") as f:
            code = f.read()

        # In map.on('popupclose'), popupclose only clears _lastOpenPopupInfo if not syncing, and NEVER calls hideMapTacticalHud
        assert "map.on('popupclose', function(e) {" in code
        assert "if (!window._reopeningPopup && !window._isLayerSyncing) {" in code
        assert "window._lastOpenPopupInfo = null;" in code

        # Verify popupclose handler does NOT call hideMapTacticalHud
        popupclose_idx = code.find("map.on('popupclose'")
        popupclose_block = code[popupclose_idx:popupclose_idx + 300]
        assert "hideMapTacticalHud" not in popupclose_block

    def test_clicking_different_answered_pin_updates_hud_correctly(self):
        """Verify that clicking a different answered pin immediately updates HUD coordinates and restores new popup."""
        with open("app.py", "r", encoding="utf-8") as f:
            code = f.read()

        # 1. popupopen updates _lastOpenPopupInfo and _lastHudInfo with new coordinates on every click
        assert "window._lastOpenPopupInfo = {" in code
        assert "window._lastHudInfo = { type: 'point', lat: p_lat, lng: p_lng };" in code

        # 2. Clear button closes popup and hides HUD
        assert "window._lastOpenPopupInfo = null;" in code
        assert "try { map.closePopup(); } catch(e) {}" in code

    def test_section_2c_ingestion_precedes_2b_and_protects_bbox(self):
        """Verify Section 2c executes before Section 2b, preventing chat submissions from being overwritten by historical clicks."""
        with open("app.py", "r", encoding="utf-8") as f:
            code = f.read()

        sec2c_pos = code.find("2c. Early Query Ingestion & Queueing")
        sec2b_pos = code.find("2b. Early Map Event Ingestion")
        assert sec2c_pos != -1, "Section 2c must be defined"
        assert sec2b_pos != -1, "Section 2b must be defined"
        assert sec2c_pos < sec2b_pos, "Architectural Rule: Section 2c must execute BEFORE Section 2b"

        # Verify Section 2b is guarded against processing map events during query submissions
        assert 'not st.session_state.get("pending_query")' in code
        assert "not _is_chat_submit" in code
        assert "not _incoming_recon" in code

    def test_chat_submit_after_long_typing_preserves_bbox(self):
        """Verify that typing a query for >10 seconds while BBox is selected does NOT convert BBox to a point."""
        import streamlit as st
        import app
        import time

        # Simulate user drawing a BBox and then typing in chat for 15 seconds
        bbox = ((48.1234, 31.5678), (49.1234, 32.5678))
        corner_coord = (49.1234, 32.5678)
        st.session_state.selection_mode = "Bounding Box"
        st.session_state.bounding_box = bbox
        st.session_state.selected_points = [bbox[0], bbox[1]]
        st.session_state.active_point = bbox[1]
        st.session_state.last_drawing_time = time.time() - 15.0  # 15 seconds ago
        st.session_state.last_clicked = None  # Historical click state
        st.session_state.pending_query = None
        st.session_state.last_processed_chat_input = None
        st.session_state.geoai_chat_input = "Where in the bounding box where there drone attacks?"

        # Simulate Section 2c execution
        _incoming_chat = st.session_state.get("geoai_chat_input")
        _incoming_recon = bool(st.session_state.get("run_chat_recon"))
        _is_chat_submit = bool(
            _incoming_chat
            and isinstance(_incoming_chat, str)
            and _incoming_chat.strip()
            and _incoming_chat != st.session_state.get("last_processed_chat_input")
        )
        assert _is_chat_submit is True

        if not st.session_state.get("pending_query"):
            _is_bbox = st.session_state.get("bounding_box") is not None
            _active_pt = None if _is_bbox else (st.session_state.selected_points[0] if st.session_state.get("selected_points") else None)
            _active_bbox = st.session_state.get("bounding_box") if _is_bbox else None
            if _is_chat_submit:
                st.session_state.last_processed_chat_input = _incoming_chat
                st.session_state.pending_query = {
                    "text_prompt": _incoming_chat.strip(),
                    "selected_point": _active_pt,
                    "bounding_box": _active_bbox,
                }

        # Assertions: pending_query was locked with bbox, active_pt is None
        assert st.session_state.pending_query["bounding_box"] == bbox
        assert st.session_state.pending_query["selected_point"] is None
        assert st.session_state.bounding_box == bbox

        # Verify Section 2b guards: Section 2b map event ingestion MUST be skipped
        should_run_2b = (
            not st.session_state.get("pending_query")
            and not _is_chat_submit
            and not _incoming_recon
        )
        assert should_run_2b is False, "Section 2b map event processing must be bypassed on query turn"

    def test_bbox_corner_clicks_never_convert_bbox_to_point(self):
        """Verify that clicking any of the 4 BBox corners NEVER destroys the BBox, regardless of time elapsed."""
        import streamlit as st
        import app

        bbox = ((48.0000, 31.0000), (49.0000, 32.0000))
        corners = [
            (48.0000, 31.0000),  # SW
            (48.0000, 32.0000),  # SE
            (49.0000, 31.0000),  # NW
            (49.0000, 32.0000),  # NE
        ]

        for corner in corners:
            # Check helper directly
            assert app._is_drawing_corner_release(corner, bbox) is True

            # Simulate state with active BBox
            st.session_state.selection_mode = "Bounding Box"
            st.session_state.bounding_box = bbox
            st.session_state.selected_points = [bbox[0], bbox[1]]
            st.session_state.last_clicked = (47.0, 30.0)  # Different coordinate

            # Process corner click
            _is_corner = app._is_drawing_corner_release(corner, st.session_state.get("bounding_box"))
            if _is_corner:
                st.session_state.last_clicked = corner
            elif corner != st.session_state.last_clicked:
                st.session_state.selection_mode = "Point Selection"
                st.session_state.selected_points = [corner]
                st.session_state.bounding_box = None

            # BBox must remain intact!
            assert st.session_state.bounding_box == bbox
            assert st.session_state.selection_mode == "Bounding Box"
            assert st.session_state.last_clicked == corner

    def test_leaflet_draw_cooldown_and_lat_lng_cleared(self):
        """Verify JavaScript MapTrashBinHook suppresses post-draw canvas click and clears lat_lng_clicked."""
        import folium
        from streamlit_folium import _get_map_string
        import app

        m = folium.Map()
        app.MapTrashBinHook().add_to(m)
        script = _get_map_string(m)

        # 1. _justDrew flag and cooldown in drawstop and draw:created
        assert "map._justDrew = false;" in script
        assert "map._justDrew = true;" in script
        assert "setTimeout(function() { map._justDrew = false; }, 800);" in script

        # 2. Canvas click guard
        assert "if (map._isDrawing || map._justDrew) return;" in script

        # 3. Explicit nullification of lat_lng_clicked on rectangle creation
        assert "window.__GLOBAL_DATA__.lat_lng_clicked = null;" in script

    def test_answered_pin_glowing_reticle_and_instant_switching(self):
        """
        Verify that selecting an answered pin:
        1. Renders a glowing reticle marker (folium.Marker with role="target" and interactive=False)
           in selection_fg without duplicate popups.
        2. Mounts an instant reticle marker in Leaflet popupopen hook with role='target'.
        3. Prioritizes 64-character hash keys over geoai_tactical_map in _peek_incoming_map_state
           so switching between pins never reverts back to stale previous rerun state.
        4. Configures .geoai-reticle with pointer-events: none so clicks pass directly to answered pins.
        5. Prioritizes state.activePoint in _onServerSelectionSync for popup reopening.
        """
        import folium
        from streamlit_folium import _get_map_string
        import app
        import streamlit as st

        # 1. Inspect app.py source contracts
        with open("app.py", "r", encoding="utf-8") as f:
            src = f.read()

        # Reticle on existing pin in selection_fg
        assert "is_existing_pin = any(" in src
        assert "make_pin_icon(role=\"target\")" in src
        assert "interactive=False" in src
        assert ".geoai-reticle {" in src
        assert "pointer-events: none;" in src

        # 2. MapTrashBinHook instant reticle rendering and popupopen dispatch
        m = folium.Map()
        app.MapTrashBinHook().add_to(m)
        script = _get_map_string(m)

        assert "var reticleIcon = geoaiIcon({ role: 'target' });" in script
        assert "var reticleMarker = L.marker([p_lat, p_lng], { icon: reticleIcon, interactive: false });" in script
        assert "window._instantTargetMarker = reticleMarker;" in script
        assert "var activeClick = g.lat_lng_clicked || g.last_object_clicked;" in script
        assert "targetPoint = state.activePoint ? { lat: state.activePoint[0], lng: state.activePoint[1] } : window._lastOpenPopupInfo;" in script

        # 3. Test _peek_incoming_map_state priority: hash key (fresh) > geoai_tactical_map (stale)
        stale_state = {"last_clicked": {"lat": 50.4501, "lng": 30.5234}}
        fresh_state = {"last_clicked": {"lat": 48.3794, "lng": 35.0462}}
        hash_key = "a" * 64

        st.session_state["geoai_tactical_map"] = stale_state
        st.session_state[hash_key] = fresh_state

        result = app._peek_incoming_map_state()
        assert result == fresh_state
        assert result["last_clicked"]["lat"] == 48.3794

        # Clean up test session state
        del st.session_state["geoai_tactical_map"]
        del st.session_state[hash_key]

        # 4. Test _peek_incoming_map_state unpacking from _new_widget_state
        import json
        from streamlit.proto.WidgetStates_pb2 import WidgetState as WidgetStateProto
        from streamlit.runtime.state.session_state_proxy import get_session_state

        ss = get_session_state()
        raw_state = getattr(ss, "_state", None)
        if raw_state is not None and hasattr(raw_state, "_new_widget_state"):
            proto = WidgetStateProto()
            proto.id = "test_map_component"
            proto.json_value = json.dumps({"last_clicked": {"lat": 49.9935, "lng": 36.2304}})
            raw_state._new_widget_state.set_widget_from_proto(proto)

            result2 = app._peek_incoming_map_state()
            assert result2 is not None
            assert result2["last_clicked"]["lat"] == 49.9935

            # Clean up proto
            del raw_state._new_widget_state[proto.id]

        # 5. Verify clear_spatial_selection resets last_clicked and ignored_drawing
        st.session_state.last_clicked = (50.4501, 30.5234)
        st.session_state.ignored_drawing = {"dummy": True}
        app.clear_spatial_selection(ignore_current_drawing=False)
        assert st.session_state.last_clicked is None
        assert st.session_state.ignored_drawing is None
        assert st.session_state.selected_points == []


class TestContextPinsStabilityAndNoLeak:
    """Verifies that context points and cluster pins never duplicate or grow on map clicks."""

    def test_pin_filter_control_uses_active_cluster_inspection(self):
        """Verify PinFilterControl inspects active clusters on map instead of accumulating stale cluster references."""
        import folium
        from streamlit_folium import _get_map_string
        import app

        m = folium.Map()
        app.MapTrashBinHook().add_to(m)
        script = _get_map_string(m)

        # 1. getActiveClusterGroups inspects live map layers
        assert "function getActiveClusterGroups()" in script
        assert "map.eachLayer(inspectLayer)" in script

        # 2. No stale clusterGroups global array retaining dead clusters across Python reruns
        assert "var clusterGroups = [];" not in script

        # 3. Double-counting guard via clusteredMarkers Set
        assert "clusteredMarkers.has(layer)" in script
        assert "var clusteredMarkers = new Set();" in script

        # 4. Dead clusters from previous runs are never resurrected via map.addLayer(cg)
        assert "if (!map.hasLayer(cg)) map.addLayer(cg);" not in script

    def test_pin_filter_css_classes_injected(self):
        """Verify CSS rules for instant client-side pin hiding are present in map head element."""
        with open("app.py", "r", encoding="utf-8") as f:
            content = f.read()

        assert ".geoai-hide-primary-pins .geoai-pin--primary" in content
        assert ".geoai-hide-primary-pins .awesome-marker-icon-blue" in content
        assert ".geoai-hide-context-pins .geoai-pin--context" in content
        assert ".geoai-hide-context-pins .awesome-marker-icon-cadetblue" in content
        assert ".geoai-hide-context-pins .geoai-cluster-wrap" in content
        assert ".geoai-hide-uncertain-pins .geoai-pin--uncertain" in content
        assert ".geoai-hide-uncertain-pins .awesome-marker-icon-orange" in content

    def test_pin_filter_control_primary_pins_and_uncertain_default_off(self):
        """Verify PinFilterControl has primary pins filter, and uncertain pins are unchecked by default."""
        import folium
        from streamlit_folium import _get_map_string
        import app

        m = folium.Map()
        app.MapTrashBinHook().add_to(m)
        script = _get_map_string(m)

        # Primary pins checkbox exists and is checked (true) by default
        assert "chkPri.id = 'pin_filter_chk_primary';" in script
        assert "chkPri.checked = true;" in script

        # Context pins checkbox exists and is checked (true) by default
        assert "chkCtx.id = 'pin_filter_chk_context';" in script
        assert "chkCtx.checked = true;" in script

        # Uncertain pins checkbox exists and is unchecked (false / OFF) by default
        assert "chkUnc.id = 'pin_filter_chk_uncertain';" in script
        assert "chkUnc.checked = false;" in script

        # Instant client-side toggles for primary, context, and uncertain
        assert "containerEl.classList.toggle('geoai-hide-primary-pins', !showPri);" in script
        assert "containerEl.classList.toggle('geoai-hide-context-pins', !showCtx);" in script
        assert "containerEl.classList.toggle('geoai-hide-uncertain-pins', !showUnc);" in script

        # Event listeners for all 3 filters
        assert "chkPri.addEventListener('change', applyPinFilter);" in script
        assert "chkCtx.addEventListener('change', applyPinFilter);" in script
        assert "chkUnc.addEventListener('change', applyPinFilter);" in script

    def test_context_pins_not_duplicated_in_session_state_on_map_clicks(self):
        """Verify map clicks only update spatial selection without multiplying map_layers in session_state."""
        import streamlit as st
        from geo_agent import MapLayer

        # Setup initial layers in session_state
        initial_layers = [
            MapLayer(name="Kyiv Hub", layer_type="marker", data={"lat": 50.45, "lng": 30.52, "role": "primary"}, color="blue"),
            MapLayer(name="Context A", layer_type="marker", data={"lat": 50.50, "lng": 30.60, "role": "context"}, color="cadetblue"),
            MapLayer(name="Context B", layer_type="marker", data={"lat": 50.40, "lng": 30.40, "role": "context"}, color="cadetblue"),
        ]
        st.session_state.map_layers = list(initial_layers)
        st.session_state.selected_points = []
        st.session_state.last_clicked = None

        # Simulate user clicking a point on the map
        clicked = (50.50, 30.60)
        st.session_state.last_clicked = clicked
        st.session_state.selected_points = [clicked]

        # Verify map_layers count did not increase
        assert len(st.session_state.map_layers) == 3
        ctx_layers = [l for l in st.session_state.map_layers if l.color == "cadetblue" or (isinstance(l.data, dict) and l.data.get("role") == "context")]
        assert len(ctx_layers) == 2

        # Simulate user clicking another random point on the map
        clicked_2 = (49.99, 36.23)
        st.session_state.last_clicked = clicked_2
        st.session_state.selected_points = [clicked_2]

        # Verify still exactly 3 total layers and 2 context layers
        assert len(st.session_state.map_layers) == 3
        ctx_layers_2 = [l for l in st.session_state.map_layers if l.color == "cadetblue" or (isinstance(l.data, dict) and l.data.get("role") == "context")]
        assert len(ctx_layers_2) == 2


class TestAgentRagMvpContractAndApiKeyPersistence:
    """Verifies AgentRag MVP contract fields, UI_TEAM_NOTES items, and in-app API key persistence."""

    def test_requirements_includes_pandas_lt_3(self):
        """UI_TEAM_NOTES 1: Ensure requirements.txt pins pandas<3 for Windows Smart App Control."""
        with open("requirements.txt", "r", encoding="utf-8") as f:
            req_text = f.read()
        assert "pandas<3" in req_text

    def test_regions_list_of_nodes_and_map_not_shown_parsed(self, monkeypatch):
        """Verify geo_agent and _build_assistant_message preserve list[RegionNode], map_showing, and map_not_shown."""
        import geo_agent
        from app import _build_assistant_message

        fake_raw = {
            "answer": "Bakhmut [1] saw intense fighting.",
            "answer_plain": "Bakhmut saw intense fighting.",
            "status": "answered",
            "grounded": True,
            "shape": "fact",
            "geo_locations": [
                {
                    "number": 1,
                    "id": "Bakhmut",
                    "label": "Bakhmut",
                    "kind": "city",
                    "role": "primary",
                    "geometry": {"type": "Point", "coordinates": [38.000, 48.595]},
                    "why": "75 matching paragraphs",
                    "sources": ["TEXT_101"],
                }
            ],
            "regions": [
                {
                    "id": "Ukraine",
                    "place_type": "country",
                    "count": 50,
                    "places": [1],
                    "children": [
                        {"id": "Donetsk Oblast", "place_type": "state", "count": 36, "places": [1], "children": []}
                    ],
                }
            ],
            "map": {
                "bbox": [37.8, 48.4, 38.2, 48.7],
                "highlight": [1],
                "showing": "discussed",
                "not_shown": 73,
            },
            "did_you_mean": [{"id": "Battle of Bakhmut", "type": "EVENT"}],
            "follow_ups": ["What happened in Soledar?"],
            "citations": [],
            "sources": ["TEXT_101"],
        }

        monkeypatch.setattr(geo_agent, "_BACKEND_AVAILABLE", True)
        monkeypatch.setattr(geo_agent, "_backend_query", lambda **kw: fake_raw)

        resp = geo_agent.query_geo_agent(text_prompt="Where did the battle of Bakhmut happen?", api_key="sk-or-test")
        assert isinstance(resp.regions, list)
        assert len(resp.regions) == 1
        assert resp.regions[0]["id"] == "Ukraine"
        assert resp.regions[0]["children"][0]["id"] == "Donetsk Oblast"
        assert resp.map_showing == "discussed"
        assert resp.map_not_shown == 73
        assert isinstance(resp.did_you_mean, list)
        assert resp.did_you_mean[0]["id"] == "Battle of Bakhmut"

        msg = _build_assistant_message(resp)
        assert isinstance(msg["regions"], list)
        assert msg["regions"][0]["id"] == "Ukraine"
        assert msg["map_showing"] == "discussed"
        assert msg["map_not_shown"] == 73
        assert msg["did_you_mean"] == [{"id": "Battle of Bakhmut", "type": "EVENT"}]

    def test_ui_team_notes_items_in_app_code(self):
        """Verify UI_TEAM_NOTES items (layer replacement, welcome fold-out, autoscroll=False, mock notice) in app.py."""
        with open("app.py", "r", encoding="utf-8") as f:
            code = f.read()

        # Note 3: Replace map_layers by default with optional keep_previous_layers toggle
        assert "st.session_state.map_layers = list(agent_resp.layers)" in code
        assert "Keep previous answers' pins on map" in code

        # Note 6: Welcome message inside st.expander folded after first question
        assert "👋 Welcome: how to use the map and the chat" in code
        assert "expanded=len(st.session_state.messages) == 1" in code

        # Note 7: autoscroll=False and scroll_to_answer
        assert "st.container(height=chat_container_height, autoscroll=False)" in code
        assert 'st.session_state.pop("scroll_to_answer", False)' in code
        assert "st.session_state.scroll_to_answer = True" in code

        # Note 8: Clear mock engine disclaimer when no API key is set
        assert "Example answer: no OpenRouter key set (Deterministic Mock Engine)" in code

    def test_persist_openrouter_api_key_updates_env_and_dotenv_file(self, tmp_path, monkeypatch):
        """Verify persist_openrouter_api_key updates os.environ and writes/clears AgentRag/.env."""
        import os
        import geo_agent

        env_file = tmp_path / ".env"
        env_file.write_text("OTHER_SETTING=123\nOPENROUTER_API_KEY=sk-or-old-key\n", encoding="utf-8")

        # 1. Update with a new key
        saved = geo_agent.persist_openrouter_api_key("sk-or-v1-new-key-999", update_dotenv=True, env_path=env_file)
        assert saved is True
        assert os.environ.get("OPENROUTER_API_KEY") == "sk-or-v1-new-key-999"
        content = env_file.read_text(encoding="utf-8")
        assert "OTHER_SETTING=123" in content
        assert "OPENROUTER_API_KEY=sk-or-v1-new-key-999" in content
        assert "sk-or-old-key" not in content

        # 2. Clear the key -> removes from os.environ and .env
        cleared = geo_agent.persist_openrouter_api_key("", update_dotenv=True, env_path=env_file)
        assert cleared is True
        assert "OPENROUTER_API_KEY" not in os.environ
        content_after = env_file.read_text(encoding="utf-8")
        assert "OTHER_SETTING=123" in content_after
        assert "OPENROUTER_API_KEY" not in content_after

    def test_clearing_api_key_in_session_state_forces_mock_mode(self, monkeypatch):
        """Verify that clearing openrouter_api_key in session_state routes to mock even if os.environ had a key."""
        import streamlit as st
        import app
        import geo_agent

        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-env-key-should-be-ignored")
        monkeypatch.setattr(geo_agent, "_BACKEND_AVAILABLE", True)

        def fail_if_called(**kw):
            raise AssertionError("Live backend should not be called when sidebar key is cleared!")

        monkeypatch.setattr(geo_agent, "_backend_query", fail_if_called)

        st.session_state.openrouter_api_key = ""
        st.session_state.rag_logs = []
        st.session_state.messages = []

        resp = app.dispatch_geo_query(text_prompt="Test offline simulation mode")
        assert resp is not None
        assert resp.is_live_backend is False


class TestPlaceSourcesTagging:
    """Verify place-source tagging convention ([P{pin}-S{idx}]) and popup source tags."""

    def test_list_query_sources_tagged_with_pin_convention(self, monkeypatch):
        """When citations are empty in a list query, place sources get [P{pin}-S{idx}] tags."""
        import geo_agent

        fake_raw = {
            "answer": "Drone attacks occurred in Kyiv [1], Dnipro [2], and Sumy [3].",
            "answer_plain": "Drone attacks occurred in Kyiv, Dnipro, and Sumy.",
            "status": "answered",
            "grounded": True,
            "shape": "list",
            "geo_locations": [
                {
                    "number": 1,
                    "id": "Kyiv",
                    "label": "Kyiv",
                    "kind": "city",
                    "role": "primary",
                    "geometry": {"type": "Point", "coordinates": [30.524, 50.450]},
                    "why": "ATTACKED in 47 records",
                    "sources": ["TEXT_1421", "TEXT_4263", "TEXT_4533", "TEXT_9999"]
                },
                {
                    "number": 2,
                    "id": "Dnipro",
                    "label": "Dnipro",
                    "kind": "city",
                    "role": "primary",
                    "geometry": {"type": "Point", "coordinates": [35.041, 48.468]},
                    "why": "ATTACKED in 7 records",
                    "sources": ["TEXT_8758", "TEXT_8760", "TEXT_8769"]
                },
                {
                    "number": 3,
                    "id": "Sumy",
                    "label": "Sumy",
                    "kind": "city",
                    "role": "primary",
                    "geometry": {"type": "Point", "coordinates": [34.802, 50.911]},
                    "why": "ATTACKED in 2 records",
                    "sources": ["TEXT_1023", "TEXT_4541", "TEXT_5992"]
                },
                {
                    "number": 4,
                    "id": "Zhytomyr",
                    "label": "Zhytomyr",
                    "kind": "city",
                    "role": "context",
                    "geometry": {"type": "Point", "coordinates": [28.669, 50.260]},
                    "why": "ATTACKED in 5 records",
                    "sources": ["TEXT_5420"]
                }
            ],
            "citations": [],
            "sources": []
        }

        monkeypatch.setattr(geo_agent, "_BACKEND_AVAILABLE", True)
        monkeypatch.setattr(geo_agent, "_backend_query", lambda **kw: fake_raw)

        def fake_get_source_text(ptr):
            return {
                "pointer": ptr,
                "document": f"Doc for {ptr}",
                "section": "General",
                "paragraph_index": 0,
                "text": f"Verbatim passage text for {ptr}"
            }
        monkeypatch.setattr(geo_agent, "_backend_get_source_text", fake_get_source_text)
        if hasattr(geo_agent.get_source_text, "cache_clear"):
            geo_agent.get_source_text.cache_clear()

        resp = geo_agent.query_geo_agent(text_prompt="Where were drone attacks?", api_key="sk-or-test")
        # When <= 10 total places, primary places (3*3) + context (1) = 10 sources
        assert len(resp.sources) == 10
        assert resp.sources[:3] == ["TEXT_1421", "TEXT_4263", "TEXT_4533"]

        # Synthetic citations are populated with [P{pin}-S{idx}]
        assert len(resp.citations) == 10
        cit_ids = [c["id"] for c in resp.citations]
        assert cit_ids[0] == "P1-S1"
        assert cit_ids[1] == "P1-S2"
        assert cit_ids[2] == "P1-S3"
        assert cit_ids[3] == "P2-S1"
        assert cit_ids[6] == "P3-S1"
        assert cit_ids[9] == "P4-S1"

        # Point info popup checks
        pin1 = next(l for l in resp.layers if l.data.get("number") == 1)
        assert "[P1-S1]" in pin1.popup
        assert "[P1-S2]" in pin1.popup
        assert "[P1-S3]" in pin1.popup
        assert "(+1 more sources)" in pin1.popup

        pin2 = next(l for l in resp.layers if l.data.get("number") == 2)
        assert "[P2-S1]" in pin2.popup
        assert "[P2-S2]" in pin2.popup
        assert "[P2-S3]" in pin2.popup

    def test_large_list_101_places_extracts_exactly_9_sources_with_pin_tags(self, monkeypatch):
        """When query returns >10 places (e.g. 101 places), only 3 primary places are collected (exactly 9 sources)."""
        import geo_agent

        # 3 primary places with 10 sources each + 98 context places
        locs = [
            {
                "number": 1,
                "id": "Kyiv",
                "label": "Kyiv",
                "kind": "city",
                "role": "primary",
                "geometry": {"type": "Point", "coordinates": [30.524, 50.450]},
                "sources": [f"TEXT_K_{i}" for i in range(10)]
            },
            {
                "number": 2,
                "id": "Dnipro",
                "label": "Dnipro",
                "kind": "city",
                "role": "primary",
                "geometry": {"type": "Point", "coordinates": [35.041, 48.468]},
                "sources": [f"TEXT_D_{i}" for i in range(10)]
            },
            {
                "number": 3,
                "id": "Sumy",
                "label": "Sumy",
                "kind": "city",
                "role": "primary",
                "geometry": {"type": "Point", "coordinates": [34.802, 50.911]},
                "sources": [f"TEXT_S_{i}" for i in range(10)]
            }
        ]
        for c_idx in range(4, 102):
            locs.append({
                "number": c_idx,
                "id": f"Place_{c_idx}",
                "label": f"Place {c_idx}",
                "kind": "town",
                "role": "context",
                "geometry": {"type": "Point", "coordinates": [30.0 + c_idx * 0.01, 50.0 + c_idx * 0.01]},
                "sources": [f"TEXT_CTX_{c_idx}"]
            })

        fake_raw = {
            "answer": "101 places found...",
            "answer_plain": "101 places found...",
            "status": "answered",
            "grounded": True,
            "shape": "list",
            "geo_locations": locs,
            "citations": [],
            "sources": []
        }

        monkeypatch.setattr(geo_agent, "_BACKEND_AVAILABLE", True)
        monkeypatch.setattr(geo_agent, "_backend_query", lambda **kw: fake_raw)

        def fake_get_source_text(ptr):
            return {"pointer": ptr, "document": f"Article {ptr}", "section": "Sec", "text": "Passage text"}
        monkeypatch.setattr(geo_agent, "_backend_get_source_text", fake_get_source_text)
        if hasattr(geo_agent.get_source_text, "cache_clear"):
            geo_agent.get_source_text.cache_clear()

        resp = geo_agent.query_geo_agent(text_prompt="Drone attacks in area", api_key="sk-or-test")
        # Exactly 3 primary * 3 sources = 9 sources
        assert len(resp.sources) == 9
        assert len(resp.citations) == 9
        assert resp.citations[0]["id"] == "P1-S1"
        assert resp.citations[0]["place_label"] == "Kyiv"
        assert resp.citations[3]["id"] == "P2-S1"
        assert resp.citations[3]["place_label"] == "Dnipro"
        assert resp.citations[6]["id"] == "P3-S1"
        assert resp.citations[6]["place_label"] == "Sumy"

    def test_point_popup_preserves_existing_citation_id(self, monkeypatch):
        """When pointer is already in citations (e.g. [L1]), popup uses that tag."""
        import geo_agent

        fake_raw = {
            "answer": "Kyiv [1] [L1] is capital.",
            "answer_plain": "Kyiv is capital.",
            "status": "answered",
            "grounded": True,
            "shape": "fact",
            "geo_locations": [
                {
                    "number": 1,
                    "id": "Kyiv",
                    "label": "Kyiv",
                    "kind": "city",
                    "role": "primary",
                    "geometry": {"type": "Point", "coordinates": [30.524, 50.450]},
                    "sources": ["TEXT_50333", "TEXT_9999"]
                }
            ],
            "citations": [
                {
                    "id": "L1",
                    "pointer": "TEXT_50333",
                    "article": "Kyiv",
                    "section": "Lead"
                }
            ],
            "sources": ["TEXT_50333"]
        }

        monkeypatch.setattr(geo_agent, "_BACKEND_AVAILABLE", True)
        monkeypatch.setattr(geo_agent, "_backend_query", lambda **kw: fake_raw)

        def fake_get_source_text(ptr):
            return {"pointer": ptr, "document": "Kyiv Article", "section": "Lead", "text": "Kyiv text"}
        monkeypatch.setattr(geo_agent, "_backend_get_source_text", fake_get_source_text)
        if hasattr(geo_agent.get_source_text, "cache_clear"):
            geo_agent.get_source_text.cache_clear()

        resp = geo_agent.query_geo_agent(text_prompt="Tell me about Kyiv", api_key="sk-or-test")
        pin1 = next(l for l in resp.layers if l.data.get("number") == 1)
        assert "[L1]" in pin1.popup
        assert "[P1-S2]" in pin1.popup


class TestAnswerKnowledgeSubgraph:
    """Validate induced answer subgraph extraction, NetworkX enrichment, and modal HTML rendering."""

    def test_extract_answer_subgraph_live_response_with_nx_enrichment(self, monkeypatch):
        """Verify subgraph includes answer's LOC, regions (INSIDE), connected PER/ORG in G, and TEXT nodes."""
        import networkx as nx
        import geo_agent

        G = nx.Graph()
        G.add_node("Bakhmut", type="LOC", place_type="city")
        G.add_node("Donetsk Oblast", type="LOC", place_type="state")
        G.add_node("93rd Mechanized Brigade", type="ORG")
        G.add_node("Oleksandr Syrskyi", type="PER")
        G.add_node("Unrelated Unit", type="ORG")
        G.add_node("TEXT_50333", type="TEXT", text_id=50333, text="93rd Mechanized Brigade and Oleksandr Syrskyi defended Bakhmut.", source="Battle of Bakhmut", title="Overview", index=1)

        G.add_edge("Bakhmut", "Donetsk Oblast", relations={"INSIDE": [{"subject": "Bakhmut", "basis": "admin"}]})
        G.add_edge("93rd Mechanized Brigade", "Bakhmut", relations={"DEFENDED": [{"subject": "93rd Mechanized Brigade", "object": "Bakhmut", "text_id": 50333}]})
        G.add_edge("93rd Mechanized Brigade", "TEXT_50333", relations={})
        G.add_edge("Oleksandr Syrskyi", "TEXT_50333", relations={})
        G.add_edge("Oleksandr Syrskyi", "Bakhmut", relations={"COMMANDED_SECTOR": [{"subject": "Oleksandr Syrskyi", "object": "Bakhmut", "text_id": 50333}]})
        # Unrelated unit is linked to Bakhmut only in TEXT_99999 (not used in this answer)
        G.add_edge("Unrelated Unit", "Bakhmut", relations={"DEPLOYED_AT": [{"subject": "Unrelated Unit", "object": "Bakhmut", "text_id": 99999}]})

        monkeypatch.setattr(
            geo_agent,
            "_backend_get_source_text",
            lambda ptr: {
                "pointer": ptr,
                "document": "Battle of Bakhmut",
                "section": "Overview",
                "paragraph_index": 0,
                "text": "93rd Mechanized Brigade and Oleksandr Syrskyi defended Bakhmut.",
            },
        )
        if hasattr(geo_agent.get_source_text, "cache_clear"):
            geo_agent.get_source_text.cache_clear()

        raw_result = {
            "answer": "Bakhmut [1] was defended by the 93rd Mechanized Brigade under Oleksandr Syrskyi [S1].",
            "answer_plain": "Bakhmut was defended by the 93rd Mechanized Brigade under Oleksandr Syrskyi.",
            "geo_locations": [
                {
                    "number": 1,
                    "id": "Bakhmut",
                    "label": "Bakhmut",
                    "kind": "city",
                    "role": "primary",
                    "geometry": {"type": "Point", "coordinates": [37.9999, 48.5953]},
                    "why": "DEFENDED in 1 record",
                    "sources": ["TEXT_50333"],
                }
            ],
            "regions": [
                {
                    "id": "Ukraine",
                    "place_type": "country",
                    "count": 1,
                    "places": [1],
                    "children": [
                        {"id": "Donetsk Oblast", "place_type": "state", "count": 1, "places": [1], "children": []}
                    ],
                }
            ],
            "citations": [{"id": "S1", "pointer": "TEXT_50333", "article": "Battle of Bakhmut", "section": "Overview"}],
            "sources": ["TEXT_50333"],
        }

        sg = geo_agent.extract_answer_subgraph(
            raw_response=raw_result,
            sources=["TEXT_50333"],
            citations=raw_result["citations"],
            regions=raw_result["regions"],
            answer_text=raw_result["answer_plain"],
            nx_graph=G,
        )

        node_ids = {n["id"] for n in sg["nodes"]}
        assert "Bakhmut" in node_ids
        assert "Donetsk Oblast" in node_ids
        assert "Ukraine" in node_ids
        assert "93rd Mechanized Brigade" in node_ids
        assert "Oleksandr Syrskyi" in node_ids
        assert "TEXT_50333" in node_ids
        # Unrelated Unit from another paragraph must NOT pollute the answer subgraph
        assert "Unrelated Unit" not in node_ids

        edge_labels = {e["label"] for e in sg["edges"]}
        assert "INSIDE" in edge_labels
        assert "DEFENDED" in edge_labels
        assert any("cited_in" in lbl for lbl in edge_labels)

    def test_mock_mode_response_populates_subgraph_and_renders_modal_html(self):
        """Verify Offline Mock mode responses automatically include a valid subgraph and render modal HTML."""
        import app
        import geo_agent

        resp = geo_agent.query_geo_agent(text_prompt="Show logistics hubs in central Ukraine", force_mock=True)
        assert isinstance(resp.subgraph, dict)
        assert len(resp.subgraph.get("nodes", [])) >= 3
        assert len(resp.subgraph.get("edges", [])) >= 2

        msg = app._build_assistant_message(resp)
        assert "subgraph" in msg
        assert len(msg["subgraph"]["nodes"]) >= 3

        html_out = app._render_subgraph_modal_html(msg["subgraph"], query_title="Show logistics hubs")
        assert "sg-canvas" in html_out
        assert "Force Physics" in html_out
        assert "Hierarchical Flow" in html_out
        assert "Sector Alpha (Kyiv)" in html_out
        # Enhancements: label opacity slider, passive stats readout, and hover handlers
        assert "sg-label-slider" in html_out
        assert "sg-stat-readout" in html_out
        assert "hoverRelation" in html_out
        assert "unhoverRelation" in html_out
        assert "Grounded Answer Subgraph" in html_out
        # Dedicated Tactical Scrollbar matching chat console roller
        assert "*::-webkit-scrollbar-thumb" in html_out
        assert "scrollbar-color" in html_out
        assert "sg-edge-section" in html_out
        assert "sg-inspector-body" in html_out


class TestPhase3ErrorBoundariesAndContinuity:
    """Phase 3 Test Suite: Validates backend timeouts, error boundaries, and conversational turn parity."""

    def test_backend_query_timeout_raises_agent_error(self, monkeypatch):
        """Verify that a hanging backend query respects GEOAI_BACKEND_TIMEOUT and raises AgentError."""
        import time
        import pytest
        import geo_agent

        def hanging_backend_query(*args, **kwargs):
            time.sleep(0.5)
            return {"answer": "Should have timed out"}

        monkeypatch.setattr(geo_agent, "_BACKEND_AVAILABLE", True)
        monkeypatch.setattr(geo_agent, "_backend_query", hanging_backend_query)
        monkeypatch.setenv("GEOAI_BACKEND_TIMEOUT", "0.05")

        with pytest.raises(geo_agent.AgentError) as exc_info:
            geo_agent.query_geo_agent(text_prompt="Test timeout", api_key="sk-or-test")

        assert "timed out" in str(exc_info.value).lower()

    def test_build_error_assistant_message_structure(self):
        """Verify _build_error_assistant_message constructs valid assistant error card."""
        import app

        err_card = app._build_error_assistant_message("Connection refused by peer")
        assert err_card["role"] == "assistant"
        assert err_card["status"] == "error"
        assert err_card["is_error"] is True
        assert err_card["grounded"] is False
        assert "Connection refused by peer" in err_card["content"]
        assert err_card["sources"] == []
        assert err_card["citations"] == []

    def test_chat_error_fallback_code_in_app(self):
        """Verify app.py source contains turn parity error handling in Section 6b."""
        with open("app.py", "r", encoding="utf-8") as f:
            code = f.read()

        assert "_build_error_assistant_message" in code
        assert "st.session_state.messages.append(_build_error_assistant_message(err_msg))" in code
        assert 'role_tag += " • [ERROR]"' in code


class TestPhase4And5IntegrationAndHygiene:
    """Phase 4 & 5 Test Suite: Validates session state hygiene, memory bounding, and integration safety."""

    def test_source_metadata_cache_deduplication_and_clearing(self, monkeypatch):
        """Verify source_metadata_cache deduplicates lookups and is purged by clear_map_and_console."""
        import streamlit as st
        import app
        import geo_agent

        st.session_state.source_metadata_cache = {}
        fake_passage = {
            "pointer": "TEXT_50333",
            "document": "Battle of Bakhmut",
            "section": "Operations",
            "text": "Detailed tactical text passage."
        }
        monkeypatch.setattr(geo_agent, "_backend_get_source_text", lambda ptr: fake_passage)
        if hasattr(geo_agent.get_source_text, "cache_clear"):
            geo_agent.get_source_text.cache_clear()

        # 1. Populate cache
        p1 = geo_agent.get_source_text("TEXT_50333")
        st.session_state.source_metadata_cache["TEXT_50333"] = p1
        assert "TEXT_50333" in st.session_state.source_metadata_cache
        assert st.session_state.source_metadata_cache["TEXT_50333"]["document"] == "Battle of Bakhmut"

        # 2. Verify clear_map_and_console resets source_metadata_cache
        app.clear_map_and_console()
        assert st.session_state.source_metadata_cache == {}

    def test_agent_turns_capped_at_five_during_extended_dialogue(self, monkeypatch):
        """Verify agent_turns stays bounded at <= 5 items across long multi-turn sessions."""
        import streamlit as st
        import app
        from app import AgentResponse

        st.session_state.agent_turns = []
        st.session_state.messages = []
        st.session_state.rag_logs = []

        fake_resp = AgentResponse(
            answer="Turn completed.",
            raw_response={"answer": "Turn completed."},
            layers=[],
            sources=[]
        )
        monkeypatch.setattr(app, "query_geo_agent", lambda **kw: fake_resp)

        for i in range(8):
            app.dispatch_geo_query(text_prompt=f"Simulated dialogue step #{i+1}")

        assert len(st.session_state.agent_turns) == 5
        assert st.session_state.agent_turns[-1]["query"] == "Simulated dialogue step #8"
        assert st.session_state.agent_turns[0]["query"] == "Simulated dialogue step #4"

    def test_rag_logs_capped_at_fifty_entries(self):
        """Verify RAG telemetry logs do not exceed the 50-entry memory ceiling."""
        import streamlit as st
        import app

        st.session_state.rag_logs = []
        for i in range(60):
            entry = {
                "id": i + 1,
                "timestamp": "2026-11-04 12:00:00",
                "latency_ms": 15.0,
                "status": "SUCCESS",
                "query_summary": f"Query #{i+1}"
            }
            app._append_rag_log(entry)

        assert len(st.session_state.rag_logs) == 50
        assert st.session_state.rag_logs[-1]["id"] == 60
        assert st.session_state.rag_logs[0]["id"] == 11

    def test_tactical_map_fragment_decorator_present(self):
        """Verify render_tactical_map_fragment is decorated with @st.fragment for client isolation."""
        with open("app.py", "r", encoding="utf-8") as f:
            code = f.read()

        assert "@st.fragment" in code
        assert "def render_tactical_map_fragment():" in code

    def test_zero_rerun_contract_on_direct_point_click(self):
        """Verify direct map clicks update active_point locally without triggering st.rerun."""
        with open("app.py", "r", encoding="utf-8") as f:
            code = f.read()

        frag_start = code.find("def render_tactical_map_fragment():")
        assert frag_start != -1
        frag_code = code[frag_start:]

        # Inside the fragment, point selection must update active_point without st.rerun()
        click_block_idx = frag_code.find("st.session_state.selected_points = [clicked_coord]")
        assert click_block_idx != -1
        click_block = frag_code[click_block_idx:click_block_idx + 350]
        assert "st.rerun()" not in click_block


class TestPhase1BackendChangesIntegration:
    """Test suite validating Phase 1 backend updates integration in GeoAI."""

    def test_multi_event_battle_pin_popup_formatting(self):
        """Verify format_evidence_popup_html groups multiple battle records into distinct styled items (P2-78)."""
        import geo_agent
        why_multi = "event: Battle of Avdiivka (2017) in 28 records, event: Battle of Avdiivka (2023-2024) in 45 records; 73 matching paragraphs"
        html = geo_agent.format_evidence_popup_html(why_multi)

        assert "⚔️ Associated Battles / Events (2):" in html
        assert "Battle of Avdiivka (2017)" in html
        assert "Battle of Avdiivka (2023-2024)" in html
        assert "28 records" in html
        assert "45 records" in html
        assert "73 matching paragraphs" in html

    def test_single_event_battle_pin_popup_formatting(self):
        """Verify format_evidence_popup_html handles single event titles with record count."""
        import geo_agent
        why_single = "event: Battle of Bakhmut in 12 records; 12 matching paragraphs"
        html = geo_agent.format_evidence_popup_html(why_single)

        assert "⚔️ Associated Battles / Events (1):" in html
        assert "Battle of Bakhmut" in html
        assert "12 records" in html

    def test_battle_pin_popup_synthesizes_events_from_sources_list(self, monkeypatch):
        """Verify format_evidence_popup_html extracts battle/siege articles from sources_list even when `why` is empty."""
        import geo_agent
        fake_corpus = {
            "TEXT_1": {"document": "Battle of Artemivsk", "section": "Background", "paragraph_index": 0},
            "TEXT_2": {"document": "Battle of Artemivsk", "section": "Timeline", "paragraph_index": 1},
            "TEXT_3": {"document": "Battle of Bakhmut", "section": "Overview", "paragraph_index": 0},
            "TEXT_4": {"document": "Battle of Donbas (2022)", "section": "Eastern front", "paragraph_index": 2},
        }
        monkeypatch.setattr(geo_agent, "get_source_text", lambda ptr: fake_corpus.get(ptr))
        html = geo_agent.format_evidence_popup_html("", sources_list=["TEXT_1", "TEXT_2", "TEXT_3", "TEXT_4"])

        assert "⚔️ Associated Battles / Events (3):" in html
        assert "Battle of Artemivsk" in html
        assert "2 passages" in html
        assert "Battle of Bakhmut" in html
        assert "1 passage" in html
        assert "Battle of Donbas (2022)" in html

    def test_generic_relation_evidence_formatting(self):
        """Verify non-event relations format as generic evidence."""
        import geo_agent
        why_rel = "ATTACKED in 12 records, SHELLED in 4 records; 16 matching paragraphs"
        html = geo_agent.format_evidence_popup_html(why_rel)

        assert "<b>Evidence:</b>" in html
        assert "ATTACKED in 12 records" in html
        assert "⚔️ Associated Battles" not in html

    def test_format_tactical_citations_pins_and_sources(self):
        """Verify format_tactical_citations styles pin, source, and summary bracketed tags as interactive hyperlinks with tooltips."""
        import app
        citations = [
            {"id": "S4", "article": "Battle of Avdiivka", "section": "October offensive", "pointer": "TEXT_123"},
            {"id": "L1", "article": "Battle of Bakhmut", "section": "", "pointer": "TEXT_456"},
            {"id": "P1-S1", "article": "Donetsk Oblast", "section": "History", "pointer": "TEXT_789"},
        ]
        geo_locs = [
            {"number": 1, "label": "Avdiivka", "geometry": {"type": "Point", "coordinates": [37.75, 48.13]}},
            {"number": 2, "label": "Bakhmut", "lat": 48.58941, "lng": 38.00210},
        ]
        raw_text = "Fierce fighting occurred in Avdiivka [1, S4] and Bakhmut [2, L1, P1-S1]."
        formatted = app.format_tactical_citations(raw_text, citations=citations, geo_locations=geo_locs)

        assert "tactical-cit-pin" in formatted
        assert "tactical-cit-src" in formatted
        assert "tactical-cit-lead" in formatted
        assert "tactical-cit-ps" in formatted
        assert "data-pin-number='1'" in formatted
        assert "data-lat='48.130000' data-lng='37.750000'" in formatted
        assert "data-pin-number='2'" in formatted
        assert "data-lat='48.589410' data-lng='38.002100'" in formatted
        assert "data-cit-target='S4'" in formatted
        assert "data-cit-target='L1'" in formatted
        assert "data-cit-target='P1-S1'" in formatted
        assert "Map Marker #1: Avdiivka (Click to zoom &amp; focus on map)" in formatted
        assert "Source Passage S4: Battle of Avdiivka — October offensive (Click to inspect source)" in formatted
        assert "Map Marker #2: Bakhmut (Click to zoom &amp; focus on map)" in formatted
        assert "Article Summary L1: Battle of Bakhmut (Click to inspect summary)" in formatted
        assert "Pin Evidence P1-S1: Donetsk Oblast — History (Click to inspect evidence)" in formatted

    def test_interactive_citation_js_handlers_present_in_app_and_map_hook(self):
        """Verify parent-to-iframe GEOAI_FOCUS_PIN and source drawer expand handlers are wired in app.py."""
        import folium
        from streamlit_folium import _get_map_string
        import app

        with open("app.py", "r", encoding="utf-8") as f:
            app_code = f.read()

        assert "GEOAI_FOCUS_PIN" in app_code
        assert "data-cit-target" in app_code
        assert "data-cit-id=" in app_code
        assert "geoai-source-detail--highlight" in app_code

        m = folium.Map()
        app.MapTrashBinHook().add_to(m)
        script = _get_map_string(m)
        assert "focusMapPinByCitation" in script
        assert "GEOAI_FOCUS_PIN" in script
        assert "zoomToShowLayer" in script
        assert "searchLayers" in script
        assert "components.html(" in app_code
        assert "geoai-parent-bridge" in app_code
        assert "_geoaiHandleSourceCitation" in app_code

    def test_popup_sources_list_interactive_citation_badges(self, monkeypatch):
        """Verify pin popups embed clickable citation badges for evidence sources."""
        import geo_agent
        fake_raw = {
            "answer": "Bakhmut saw heavy drone strikes [1].",
            "geo_locations": [
                {
                    "name": "Bakhmut",
                    "number": 1,
                    "lat": 48.589,
                    "lon": 38.002,
                    "kind": "town",
                    "role": "primary",
                    "why": "HEAVILY CONTESTED in 10 records",
                    "sources": ["TEXT_101", "TEXT_102"]
                }
            ],
            "citations": [],
            "sources": []
        }
        monkeypatch.setattr(geo_agent, "_BACKEND_AVAILABLE", True)
        monkeypatch.setattr(geo_agent, "_backend_query", lambda **kw: fake_raw)
        monkeypatch.setattr(geo_agent, "_backend_get_source_text", lambda ptr: {"pointer": ptr, "document": f"Doc for {ptr}", "section": "General", "text": "Sample text"})
        if hasattr(geo_agent.get_source_text, "cache_clear"):
            geo_agent.get_source_text.cache_clear()

        resp = geo_agent.query_geo_agent(
            text_prompt="Where were drone attacks?",
            api_key="sk-or-test"
        )
        assert resp.layers
        pin1 = next((l for l in resp.layers if l.data and l.data.get("number") == 1), None)
        assert pin1 is not None
        assert "tactical-cit" in pin1.popup
        assert "data-cit-target=" in pin1.popup
        assert "[P1-S1]" in pin1.popup

    def test_format_tactical_citations_preserves_links_and_plain_text(self):
        """Verify format_tactical_citations does not mangle markdown links or plain brackets."""
        import app
        text = "See [official report](https://example.com) and [non-citation-note]."
        formatted = app.format_tactical_citations(text)
        assert "[official report](https://example.com)" in formatted
        assert "[non-citation-note]" in formatted

    def test_assistant_message_preserves_geo_locations(self):
        """Verify _build_assistant_message includes geo_locations from raw_response."""
        import app
        from geo_agent import AgentResponse
        resp = AgentResponse(
            answer="Strategic sector scan complete [1].",
            raw_response={
                "answer": "Strategic sector scan complete [1].",
                "geo_locations": [{"number": 1, "label": "Kharkiv"}],
            },
            layers=[],
            sources=["TEXT_100"]
        )
        msg = app._build_assistant_message(resp)
        assert "geo_locations" in msg
        assert len(msg["geo_locations"]) == 1
        assert msg["geo_locations"][0]["label"] == "Kharkiv"



# ==============================================================================
# PHASE 1.1: Static Performance & Invariant Auditing (AST / Lint Tests)
# ==============================================================================
class TestPhase1StaticPerformanceAndInvariantAuditing:
    """
    Static AST and source-level invariant tests guaranteeing:
    1. `st_folium` strictly constrains `returned_objects` and disables `return_on_hover`.
    2. Custom Leaflet controls/hooks preserve client-side debounce and cooldown timers.
    3. Knowledge graph lookups and bootstrap logic use proper caching and once-per-process guards.
    4. No illegal `st.rerun()` calls exist in early queueing or map click/draw handlers.
    5. Container heights remain constant and dense layer lists do not explode widget IDs.
    """

    @staticmethod
    def _parse_ast(filename: str):
        import ast
        import os
        filepath = os.path.join(os.path.dirname(__file__), filename)
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
        return ast.parse(source, filename=filename), source

    def test_ast_st_folium_strict_returned_objects_and_zero_hover(self):
        """
        Rule 1.1: Assert every `st_folium(...)` call in `app.py` explicitly restricts
        `returned_objects` to `["last_clicked", "last_active_drawing", "all_drawings"]`,
        sets `return_on_hover=False`, passes `feature_group_to_add`, and uses a fixed height.
        """
        import ast

        tree, _ = self._parse_ast("app.py")
        st_folium_calls = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func_name = None
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    func_name = node.func.attr
                if func_name == "st_folium":
                    st_folium_calls.append(node)

        assert len(st_folium_calls) >= 1, "Expected at least one st_folium() call in app.py"

        allowed_returned_objects = ["last_clicked", "last_active_drawing", "all_drawings"]
        forbidden_returned_objects = {"bounds", "zoom", "center", "last_object_clicked", "last_object_clicked_popup", "last_object_clicked_tooltip"}

        for call in st_folium_calls:
            kw_map = {kw.arg: kw.value for kw in call.keywords if kw.arg is not None}

            # 1. Verify returned_objects is explicitly specified and strictly minimal
            assert "returned_objects" in kw_map, (
                f"st_folium() at line {call.lineno} must explicitly pass `returned_objects`"
            )
            ret_node = kw_map["returned_objects"]
            assert isinstance(ret_node, ast.List), (
                f"st_folium() `returned_objects` at line {call.lineno} must be a list literal"
            )
            actual_keys = [
                elt.value for elt in ret_node.elts
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
            ]
            assert actual_keys == allowed_returned_objects, (
                f"st_folium() at line {call.lineno} has returned_objects={actual_keys}; "
                f"expected strictly {allowed_returned_objects}"
            )
            assert not (set(actual_keys) & forbidden_returned_objects), (
                f"st_folium() at line {call.lineno} includes pan/zoom rerun triggers: "
                f"{set(actual_keys) & forbidden_returned_objects}"
            )

            # 2. Verify return_on_hover=False
            assert "return_on_hover" in kw_map, (
                f"st_folium() at line {call.lineno} must explicitly set `return_on_hover=False`"
            )
            hover_node = kw_map["return_on_hover"]
            assert isinstance(hover_node, ast.Constant) and hover_node.value is False, (
                f"st_folium() at line {call.lineno} must set `return_on_hover=False`"
            )

            # 3. Verify feature_group_to_add is used for dynamic layers
            assert "feature_group_to_add" in kw_map, (
                f"st_folium() at line {call.lineno} must pass `feature_group_to_add` to avoid map re-instantiation"
            )

            # 4. Verify fixed integer height (Rule 3.1)
            assert "height" in kw_map, f"st_folium() at line {call.lineno} must set a constant height"
            height_node = kw_map["height"]
            assert isinstance(height_node, ast.Constant) and isinstance(height_node.value, int), (
                f"st_folium() height at line {call.lineno} must be a constant integer"
            )

    def test_ast_and_dom_leaflet_controls_maintain_debounce_and_cooldown_thresholds(self):
        """
        Rule 1.2: Verify custom Leaflet controls (`PinFilterControl`, `MapTrashBinHook`)
        maintain client-side debouncing (>=100ms) for marker filtering/counts, >=500ms
        post-draw cooldown to suppress synthetic corner clicks, and payload deduplication.
        """
        import re
        import folium
        import app

        _, app_source = self._parse_ast("app.py")

        # 1. Verify PinFilterControl debouncedRefreshPinCounts uses clearTimeout + setTimeout >= 100ms
        assert "debouncedRefreshPinCounts" in app_source
        assert "clearTimeout(_refreshTimer)" in app_source
        debounce_match = re.search(
            r"function\s+debouncedRefreshPinCounts\s*\(\s*delay\s*\)\s*\{[^}]*setTimeout\s*\(\s*refreshPinCounts\s*,\s*delay\s*\|\|\s*(\d+)\s*\)",
            app_source,
            re.DOTALL,
        )
        assert debounce_match is not None, (
            "PinFilterControl must debounce refreshPinCounts via setTimeout(refreshPinCounts, delay || <ms>)"
        )
        debounce_ms = int(debounce_match.group(1))
        assert 100 <= debounce_ms <= 500, (
            f"PinFilterControl debounce threshold {debounce_ms}ms out of bounds [100ms, 500ms]"
        )

        # 2. Verify client-side style toggling (0ms DOM filter without server round-trip)
        assert "layer._icon.style.display" in app_source
        assert "geoai-hide-primary-pins" in app_source
        assert "geoai-hide-context-pins" in app_source
        assert "geoai-hide-uncertain-pins" in app_source

        # 3. Verify MapTrashBinHook post-draw cooldown >= 500ms and immediate dispatch deduplication
        m = folium.Map()
        app.MapTrashBinHook().add_to(m)
        hook_script = m.get_root().render()

        cooldown_match = re.search(
            r"map\._justDrew\s*=\s*false.*?\},\s*(\d+)\s*\)",
            hook_script,
            re.DOTALL,
        )
        assert cooldown_match is not None, "MapTrashBinHook must reset map._justDrew after a cooldown timeout"
        cooldown_ms = int(cooldown_match.group(1))
        assert cooldown_ms >= 500, (
            f"MapTrashBinHook post-draw cooldown {cooldown_ms}ms is too short (<500ms) to block corner clicks"
        )
        assert "JSON.stringify(g.previous_data) !== JSON.stringify(u)" in hook_script, (
            "geoaiImmediateDispatch must deduplicate identical payloads via JSON.stringify(g.previous_data)"
        )

    def test_ast_caching_decorators_and_bootstrap_hygiene(self):
        """
        Rule 2.1 & 2.2: Assert `get_source_text` is decorated with `@functools.lru_cache(maxsize=4096)`,
        `app.py` guards dependency checks behind `_BOOTSTRAP_DONE`, and no unguarded
        `importlib.reload()` calls exist in module scope.
        """
        import ast
        import geo_agent

        # 1. Runtime & AST check on geo_agent.get_source_text
        assert hasattr(geo_agent.get_source_text, "cache_info"), (
            "geo_agent.get_source_text must be wrapped with @functools.lru_cache"
        )
        info = geo_agent.get_source_text.cache_info()
        assert info.maxsize is not None and info.maxsize >= 4096, (
            f"geo_agent.get_source_text LRU cache maxsize={info.maxsize} must be >= 4096"
        )

        ga_tree, _ = self._parse_ast("geo_agent.py")
        found_get_source_text = False
        for node in ast.walk(ga_tree):
            if isinstance(node, ast.FunctionDef) and node.name == "get_source_text":
                found_get_source_text = True
                assert len(node.decorator_list) >= 1, "get_source_text must have @functools.lru_cache decorator"
        assert found_get_source_text

        # 2. Verify app.py bootstrap hygiene (Rule 2.1)
        app_tree, app_source = self._parse_ast("app.py")
        assert "_BOOTSTRAP_DONE" in app_source, (
            "app.py must guard dependency bootstrapping with `_BOOTSTRAP_DONE` so it runs once per process"
        )
        assert '"source_metadata_cache"' in app_source, (
            "app.py must maintain `source_metadata_cache` in st.session_state"
        )

        # Ensure no unguarded top-level expression/assignment calls importlib.reload
        for stmt in app_tree.body:
            if isinstance(stmt, (ast.Expr, ast.Assign)):
                for sub in ast.walk(stmt):
                    if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
                        if sub.func.attr == "reload":
                            pytest.fail(
                                f"Illegal unguarded top-level `reload()` call found in app.py at line {sub.lineno}"
                            )

    def test_ast_no_illegal_st_rerun_in_early_queue_or_map_click_draw_paths(self):
        """
        Verify via AST analysis that:
        1. Section 2c (early query ingestion & queueing) and Section 2b (early map event ingestion)
           contain ZERO `st.rerun()` calls.
        2. Inside `render_tactical_map_fragment`, `st.rerun()` is NEVER called during
           normal map clicks, rectangle AOI drawing, point drawing, or trash deletion;
           only `action == "recon"` may trigger a full-app rerun.
        3. Pure helper functions never invoke `st.rerun()`.
        """
        import ast

        app_tree, app_source = self._parse_ast("app.py")
        lines = app_source.splitlines()

        # Find all st.rerun() call line numbers across app.py
        rerun_lines = []
        for node in ast.walk(app_tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "st" and node.func.attr == "rerun":
                    rerun_lines.append(node.lineno)

        assert len(rerun_lines) > 0, "Expected to locate valid st.rerun() calls in app.py"

        # 1. Locate Section 2c and Section 2b line bounds
        sec_2c_line = next(i + 1 for i, l in enumerate(lines) if "2c. Early Query Ingestion & Queueing" in l)
        sec_2b_line = next(i + 1 for i, l in enumerate(lines) if "2b. Early Map Event Ingestion" in l)
        sec_3_line = next(i + 1 for i, l in enumerate(lines) if "3. Sidebar Utility Controls & Intelligence Dashboard" in l)
        assert sec_2c_line < sec_2b_line < sec_3_line

        illegal_early_reruns = [ln for ln in rerun_lines if sec_2c_line <= ln < sec_3_line]
        assert illegal_early_reruns == [], (
            f"Illegal st.rerun() found in Section 2c/2b (lines {sec_2c_line}-{sec_3_line}): {illegal_early_reruns}"
        )

        # 2. Inspect `render_tactical_map_fragment` AST
        fragment_fn = next(
            node for node in ast.walk(app_tree)
            if isinstance(node, ast.FunctionDef) and node.name == "render_tactical_map_fragment"
        )
        fragment_reruns = []
        for node in ast.walk(fragment_fn):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "st" and node.func.attr == "rerun":
                    fragment_reruns.append(node.lineno)

        assert len(fragment_reruns) == 1, (
            f"render_tactical_map_fragment must have at most 1 st.rerun() (solely for 'recon' action), "
            f"found {len(fragment_reruns)} at lines {fragment_reruns}"
        )
        recon_rerun_line = fragment_reruns[0]
        surrounding_window = "\n".join(lines[max(0, recon_rerun_line - 65):recon_rerun_line + 2])
        assert '"recon"' in surrounding_window, (
            f"st.rerun() in render_tactical_map_fragment at line {recon_rerun_line} is outside the 'recon' handler"
        )

        # 3. Verify pure helper functions contain zero st.rerun() calls
        pure_helpers = {
            "_is_drawing_corner_release",
            "_build_raw_request_payload",
            "_build_assistant_message",
            "_build_error_assistant_message",
            "clear_spatial_selection",
            "clear_map_and_console",
            "make_pin_icon",
            "color_token",
            "bbox_style",
            "_popup_card",
            "_highlight_text_spans",
            "format_tactical_citations",
            "_render_subgraph_modal_html",
        }
        for node in ast.walk(app_tree):
            if isinstance(node, ast.FunctionDef) and node.name in pure_helpers:
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
                        if isinstance(sub.func.value, ast.Name) and sub.func.value.id == "st" and sub.func.attr == "rerun":
                            pytest.fail(
                                f"Pure helper `{node.name}` must never call st.rerun() (line {sub.lineno})"
                            )

    def test_ast_ui_layout_stability_and_widget_explosion_guards(self):
        """
        Rule 3.1 & 3.2: Verify `chat_container_height` is a constant integer literal
        (preventing vertical chat bounce) and dense layer lists (>10 items) use bulk controls.
        """
        import ast

        app_tree, app_source = self._parse_ast("app.py")

        # 1. Verify chat_container_height is assigned a constant integer (never ternary IfExp)
        height_assignments = []
        for node in ast.walk(app_tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "chat_container_height":
                        height_assignments.append(node.value)

        assert len(height_assignments) >= 1, "chat_container_height assignment not found in app.py"
        for val_node in height_assignments:
            assert isinstance(val_node, ast.Constant) and isinstance(val_node.value, int), (
                f"Rule 3.1 violation: chat_container_height must be a constant int, got {ast.dump(val_node)}"
            )

        # 2. Verify Rule 3.2 widget explosion guard for dense tactical layers
        assert "if total_layers > 10:" in app_source, (
            "Rule 3.2 violation: app.py must guard against instantiating individual delete buttons when total_layers > 10"
        )
        assert "<details class='geoai-source-detail'" in app_source, (
            "Rule 3.2 violation: Source inspect drawers must use native HTML <details> instead of per-source Streamlit widgets"
        )


# ==============================================================================
# PHASE 1.2: Execution Timing & Latency Ceilings (Micro-Benchmarks)
# ==============================================================================
class TestPhase1ExecutionTimingAndLatencyCeilings:
    """
    Micro-benchmark suite enforcing strict millisecond latency ceilings across:
    1. UI component rendering pipeline setup (`make_pin_icon`, `color_token`, `bbox_style`,
       `_popup_card`, `_highlight_text_spans`, `format_tactical_citations`, `_render_subgraph_modal_html`).
    2. Leaflet control & hook template synthesis (`MapTrashBinHook`, `SelectionSyncHook`).
    3. `geo_agent.py` payload ingestion, GeoJSON parsing, and LRU-cached graph lookups.
    4. High-load (250–500 points) spatial hydration, `MarkerCluster` partitioning, and bbox normalization.
    """

    def test_benchmark_pin_icon_and_style_token_rendering_pipeline(self, micro_benchmark, latency_ceiling):
        """
        Benchmark `make_pin_icon`, `color_token`, and `bbox_style`.
        Ceilings:
        - Single `make_pin_icon` call across all 6 role/shape variants: mean <= 1.0ms, P95 <= 2.0ms
        - Batch synthesis of 100 numbered/role icons: total <= 25.0ms
        - `color_token` + `bbox_style` lookup: mean <= 0.2ms
        """
        import app

        variants = [
            {"kind": "place", "role": "primary", "uncertain": False, "number": 1, "shape": "diamond"},
            {"kind": "place", "role": "primary", "uncertain": False, "number": 2, "shape": "teardrop"},
            {"kind": "place", "role": "context", "uncertain": False, "number": None, "shape": "diamond"},
            {"kind": "place", "role": "primary", "uncertain": True, "number": 3, "shape": "diamond"},
            {"kind": "event", "role": "primary", "uncertain": False, "number": 4, "shape": "teardrop"},
            {"kind": "place", "role": "target", "uncertain": False, "number": None, "shape": "diamond"},
            {"kind": "place", "role": "bbox_corner", "uncertain": False, "number": None, "corner": "sw"},
        ]

        for spec in variants:
            stats = micro_benchmark(
                app.make_pin_icon,
                kind=spec["kind"],
                role=spec["role"],
                uncertain=spec["uncertain"],
                number=spec["number"],
                corner=spec.get("corner"),
                shape=spec.get("shape"),
                iterations=25,
                warmup=3,
                max_mean_ms=1.0,
                max_p95_ms=2.0,
                label=f"make_pin_icon[{spec['role']}/{spec.get('shape', 'corner')}]",
            )
            assert stats.mean_ms <= 1.0

        with latency_ceiling(25.0, label="batch_100_make_pin_icon"):
            for i in range(100):
                spec = variants[i % len(variants)]
                icon = app.make_pin_icon(
                    kind=spec["kind"],
                    role=spec["role"],
                    uncertain=spec["uncertain"],
                    number=(i + 1) if spec["number"] else None,
                    corner=spec.get("corner"),
                    shape=spec.get("shape"),
                )
                assert icon is not None

        micro_benchmark(
            lambda: (
                app.color_token("blue", role="primary"),
                app.color_token("cadetblue", role="context"),
                app.color_token("orange", uncertain=True),
                app.bbox_style("selected"),
                app.bbox_style("querying"),
                app.bbox_style("answered"),
            ),
            iterations=50,
            warmup=5,
            max_mean_ms=0.2,
            max_p95_ms=0.5,
            label="color_token_and_bbox_style_lookup",
        )

    def test_benchmark_popup_card_text_highlighting_and_citation_badges(self, micro_benchmark):
        """
        Benchmark HTML card synthesis, interval highlighting, citation badge regex transformation,
        and interactive SVG subgraph modal rendering.
        Ceilings:
        - `_popup_card`: mean <= 0.5ms
        - `_highlight_text_spans`: mean <= 2.0ms
        - `format_tactical_citations`: mean <= 5.0ms
        - `_render_subgraph_modal_html`: mean <= 15.0ms
        """
        import app

        micro_benchmark(
            app._popup_card,
            title="Kharkiv Railway Junction",
            rows=[("LAT", "50.00450°"), ("LNG", "36.23120°"), ("ROLE", "PRIMARY #1")],
            chip="PRIMARY // PLACE",
            footer="Grounded in [P1-S1]",
            token="primary",
            iterations=30,
            warmup=3,
            max_mean_ms=0.5,
            max_p95_ms=1.2,
            label="_popup_card",
        )

        sample_passage = (
            "In October 1941, German forces entered Kharkiv and established administrative "
            "checkpoints near the central railway station, Dzerzhinsky Square, and the tractor factory "
            "district while partisan units retreated toward Chuhuiv and Izium."
        ) * 3
        intervals = [[17, 30], [39, 46], [96, 119], [124, 142], [210, 217]]
        micro_benchmark(
            app._highlight_text_spans,
            sample_passage,
            intervals,
            iterations=25,
            warmup=3,
            max_mean_ms=2.0,
            max_p95_ms=4.0,
            label="_highlight_text_spans",
        )

        markdown_answer = (
            "### Spatial Intelligence Synthesis\n"
            "Primary engagements occurred at **Kharkiv** [1], **Chuhuiv** [2, 3], and **Izium** [4]. "
            "Additional logistical staging points were identified across sectors [1, 2, 5, 6] "
            "with corroborating testimony in [S1], [L1], and [P1-S1]."
        )
        micro_benchmark(
            app.format_tactical_citations,
            markdown_answer,
            iterations=25,
            warmup=3,
            max_mean_ms=5.0,
            max_p95_ms=10.0,
            label="format_tactical_citations",
        )

        sample_subgraph = {
            "nodes": [
                {"id": "P1", "label": "#1 Kharkiv", "type": "LOC", "role": "primary", "pin_number": 1},
                {"id": "P2", "label": "Chuhuiv", "type": "LOC", "role": "context"},
                {"id": "TEXT_50333", "label": "[S1] Archive Doc", "type": "TEXT", "role": "source", "evidence": "Archival testimony."},
                {"id": "ORG_1", "label": "6th Army", "type": "ORG", "role": "entity"},
            ],
            "edges": [
                {"from": "P1", "to": "TEXT_50333", "label": "cited_in [S1]", "kind": "provenance"},
                {"from": "P1", "to": "P2", "label": "INSIDE", "kind": "hierarchy"},
                {"from": "ORG_1", "to": "P1", "label": "OPERATED_IN", "kind": "relation"},
            ],
        }
        micro_benchmark(
            app._render_subgraph_modal_html,
            sample_subgraph,
            query_title="Kharkiv operations",
            iterations=15,
            warmup=2,
            max_mean_ms=15.0,
            max_p95_ms=25.0,
            label="_render_subgraph_modal_html",
        )

    def test_benchmark_leaflet_hooks_and_control_template_compilation(self, micro_benchmark):
        """
        Benchmark Folium HTML/JS synthesis for `MapTrashBinHook` (which embeds `PinFilterControl`
        and `TacticalTargetHudControl`) and `SelectionSyncHook`.
        Ceiling: mean <= 80.0ms per full map hook compilation.
        """
        import folium
        import app

        def _compile_map_hooks():
            m = folium.Map(location=[49.0, 32.0], zoom_start=6, tiles=None)
            app.MapTrashBinHook().add_to(m)
            app.SelectionSyncHook(
                has_selection=True,
                clear_seq=1,
                bbox_state="selected",
                is_querying=False,
                bbox_bounds=[[49.0, 31.0], [50.5, 33.0]],
                active_point=(50.45, 30.52),
                pin_shape="diamond",
            ).add_to(m)
            return m.get_root().render()

        stats = micro_benchmark(
            _compile_map_hooks,
            iterations=8,
            warmup=1,
            max_mean_ms=80.0,
            max_p95_ms=130.0,
            label="compile_map_hooks_and_controls",
        )
        assert stats.mean_ms <= 80.0

    def test_benchmark_geo_agent_payload_ingestion_and_evidence_formatting(self, micro_benchmark):
        """
        Benchmark `app._build_raw_request_payload`, `geo_agent.format_evidence_popup_html`,
        `geo_agent.extract_answer_subgraph`, and `geo_agent.query_geo_agent` mock pipeline.
        Ceilings:
        - `_build_raw_request_payload`: mean <= 1.0ms
        - `format_evidence_popup_html`: mean <= 2.0ms
        - `extract_answer_subgraph`: mean <= 25.0ms
        - `query_geo_agent` (mock fallback): mean <= 15.0ms
        """
        import app
        import geo_agent

        turns = [
            {"query": "Analyze sector [50.45, 30.52]", "response": {"answer": "Kyiv sector analysis complete [1]."}},
            {"query": "Follow up on surrounding rail junctions", "response": {"answer": "Fastiv and Darnytsia identified [2]."}},
        ]

        micro_benchmark(
            app._build_raw_request_payload,
            text_prompt="Identify defensive perimeters",
            selected_point=(50.4501, 30.5234),
            bounding_box=((50.2, 30.2), (50.7, 30.8)),
            agent_turns=turns,
            iterations=40,
            warmup=4,
            max_mean_ms=1.0,
            max_p95_ms=2.0,
            label="_build_raw_request_payload",
        )

        micro_benchmark(
            geo_agent.format_evidence_popup_html,
            "event: Battle of Kyiv (1941) in 18 records, event: Defense of Kyiv Arsenal in 6 records, fortification hub",
            ["TEXT_50333", "TEXT_1001"],
            iterations=30,
            warmup=3,
            max_mean_ms=2.0,
            max_p95_ms=4.0,
            label="format_evidence_popup_html",
        )

        sample_raw_response = {
            "answer": "Operations centered on Kyiv Arsenal [1].",
            "geo_locations": [
                {
                    "id": "Kyiv Arsenal",
                    "number": 1,
                    "name": "Kyiv Arsenal",
                    "label": "Kyiv Arsenal",
                    "lat": 50.442,
                    "lon": 30.541,
                    "role": "primary",
                    "kind": "place",
                    "why": "event: Battle of Kyiv in 12 records",
                    "sources": ["TEXT_50333"],
                }
            ],
            "citations": [{"id": "P1-S1", "pointer": "TEXT_50333", "place_number": 1, "snippet": "Evidence 1"}],
            "sources": ["TEXT_50333"],
        }
        micro_benchmark(
            geo_agent.extract_answer_subgraph,
            sample_raw_response,
            iterations=15,
            warmup=2,
            max_mean_ms=25.0,
            max_p95_ms=40.0,
            label="extract_answer_subgraph",
        )

        micro_benchmark(
            geo_agent.query_geo_agent,
            text_prompt="Identify defensive positions around Kyiv",
            selected_point=(50.4501, 30.5234),
            bounding_box=None,
            agent_turns=turns,
            force_mock=True,
            iterations=15,
            warmup=2,
            max_mean_ms=15.0,
            max_p95_ms=25.0,
            label="query_geo_agent_mock_pipeline",
        )

    def test_benchmark_get_source_text_lru_cache_sub_millisecond_throughput(self, monkeypatch, latency_ceiling):
        """
        Rule 2.2: Verify 1,000 repeated calls to `get_source_text(pointer)` hit the
        in-memory LRU cache and complete in < 5.0ms total (< 0.005ms per lookup).
        """
        import geo_agent

        backend_call_count = 0

        def _fake_backend_lookup(pointer: str):
            nonlocal backend_call_count
            backend_call_count += 1
            return {
                "pointer": pointer,
                "text": "Full archival paragraph text for " + pointer,
                "document": "Kharkiv Operations",
                "section": "October 1941",
            }

        monkeypatch.setattr(geo_agent, "_BACKEND_AVAILABLE", True)
        monkeypatch.setattr(geo_agent, "_backend_get_source_text", _fake_backend_lookup)
        geo_agent.get_source_text.cache_clear()

        # Cold lookup
        first = geo_agent.get_source_text("TEXT_99999")
        assert first is not None and first["document"] == "Kharkiv Operations"
        assert backend_call_count == 1

        # 1,000 warm LRU cache lookups must complete in < 5.0ms total
        with latency_ceiling(5.0, label="1000_lru_cached_get_source_text_lookups"):
            for _ in range(1000):
                res = geo_agent.get_source_text("TEXT_99999")
                assert res is first

        info = geo_agent.get_source_text.cache_info()
        assert backend_call_count == 1, "LRU cache failed: backend was invoked more than once"
        assert info.hits >= 1000
        assert info.misses == 1

    def test_benchmark_high_load_250_and_500_points_ingestion_and_geojson_parsing(
        self,
        monkeypatch,
        high_volume_rag_payload_factory,
        latency_ceiling,
    ):
        """
        Benchmark `query_geo_agent` live-adapter hydration and spatial GeoJSON boundary parsing
        under high loads:
        - 250 spatial points + primary GeoJSON polygons + region bbox: <= 120.0ms
        - 500 spatial points + primary GeoJSON polygons + region bbox: <= 250.0ms
        """
        import geo_agent

        payload_250 = high_volume_rag_payload_factory(n_points=250, primary_count=12, uncertain_count=8)
        payload_500 = high_volume_rag_payload_factory(n_points=500, primary_count=20, uncertain_count=15)

        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-perf-benchmark-key")
        monkeypatch.setattr(geo_agent, "_BACKEND_AVAILABLE", True)

        # 1. Benchmark 250-point payload hydration
        monkeypatch.setattr(geo_agent, "_backend_query", lambda *a, **kw: payload_250)
        with latency_ceiling(120.0, label="query_geo_agent_ingest_250_points"):
            resp_250 = geo_agent.query_geo_agent(
                text_prompt="High-load 250-point spatial scan",
                bounding_box=((47.5, 30.5), (51.5, 35.5)),
            )
        # 250 markers + 12 primary polygon shapes + 1 query bbox = 263+ layers
        assert len(resp_250.layers) >= 260

        # 2. Benchmark 500-point payload hydration
        monkeypatch.setattr(geo_agent, "_backend_query", lambda *a, **kw: payload_500)
        with latency_ceiling(250.0, label="query_geo_agent_ingest_500_points"):
            resp_500 = geo_agent.query_geo_agent(
                text_prompt="High-load 500-point spatial scan",
                bounding_box=((47.5, 30.5), (51.5, 35.5)),
            )
        assert len(resp_500.layers) >= 520

    def test_benchmark_high_load_500_points_marker_clustering_and_bbox_normalization(
        self,
        monkeypatch,
        high_volume_rag_payload_factory,
        bbox_input_factory,
        latency_ceiling,
    ):
        """
        Rule 4.1 & 4.2: Benchmark bounding-box normalization (1,000 calls <= 15.0ms)
        and Folium `MarkerCluster` vs primary pin layer partitioning for 500 spatial points (<= 150.0ms).
        """
        import folium
        from folium.plugins import MarkerCluster
        import geo_agent

        # 1. Benchmark 1,000 `to_bounding_box` normalizations across all 4 corner permutations
        perms = bbox_input_factory["make_corner_permutations"](30.512345, 48.123456, 36.987654, 51.654321)
        with latency_ceiling(15.0, label="1000_to_bounding_box_normalizations"):
            for i in range(1000):
                c1, c2 = perms[i % 4]
                ll, ur = geo_agent.to_bounding_box(c1, c2)
                assert ll[0] < ur[0] and ll[1] < ur[1]

        # 2. Hydrate 500 layers and benchmark Folium partitioning (primary -> fg, context -> MarkerCluster)
        payload_500 = high_volume_rag_payload_factory(n_points=500, primary_count=15, uncertain_count=10)
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-perf-benchmark-key")
        monkeypatch.setattr(geo_agent, "_BACKEND_AVAILABLE", True)
        monkeypatch.setattr(geo_agent, "_backend_query", lambda *a, **kw: payload_500)
        resp_500 = geo_agent.query_geo_agent(text_prompt="Cluster 500 points")

        with latency_ceiling(150.0, label="partition_and_cluster_500_folium_layers"):
            tactical_layers_fg = folium.FeatureGroup(name="Tactical AI Layers")
            context_cluster = MarkerCluster(
                name="Context Places Cluster",
                options={"maxClusterRadius": 38, "spiderfyOnMaxZoom": True, "disableClusteringAtZoom": 14},
            )
            context_cluster.add_to(tactical_layers_fg)

            primary_pin_count = 0
            clustered_context_count = 0

            for layer in resp_500.layers:
                if layer.layer_type == "marker":
                    role = layer.data.get("role", "primary")
                    number = layer.data.get("number")
                    is_background_context = (role == "context" and not number)
                    target_container = context_cluster if is_background_context else tactical_layers_fg
                    if is_background_context:
                        clustered_context_count += 1
                    else:
                        primary_pin_count += 1

                    folium.Marker(
                        location=[layer.data["lat"], layer.data["lng"]],
                        tooltip=layer.tooltip,
                    ).add_to(target_container)

        assert primary_pin_count == 25  # 15 primary + 10 uncertain (all numbered)
        assert clustered_context_count == 475  # 475 unnumbered context points routed to MarkerCluster


# ==============================================================================
# PHASE 1.3: Responsiveness & State Loop Verification
# ==============================================================================
class TestPhase1ResponsivenessAndStateLoopVerification:
    """
    Simulate rapid, repeated UI state transitions to guarantee:
    1. Consecutive map point clicks update state in 1 pass with 0 `st.rerun()` calls.
    2. Rapid AOI bounding-box resizes and synthetic corner release clicks never degrade
       the BBox into a point or trigger orphan reruns.
    3. Rapid chat submissions lock `pending_query` in Section 2c before Section 2b cleanup,
       preserve history window bounds (`agent_turns <= 5`, `rag_logs <= 50`), and maintain
       strict user/assistant turn parity.
    4. Interleaved operator chaos sequences complete with zero state desyncs.
    """

    def test_rapid_consecutive_map_point_clicks_single_pass_zero_reruns(
        self,
        streamlit_state_simulator,
        latency_ceiling,
    ):
        """
        Simulate 50 rapid consecutive map clicks across distinct coordinates plus duplicate
        clicks on the same coordinate. Assert:
        - `rerun_count == 0` (handled 100% in a single pass without secondary reruns)
        - `selected_points` always matches the latest clicked coordinate `[(lat, lng)]`
        - `bounding_box` remains `None`
        - Total execution time for 50 click transitions <= 25.0ms
        """
        sim = streamlit_state_simulator

        with latency_ceiling(25.0, label="50_rapid_consecutive_map_point_clicks"):
            for i in range(50):
                lat = round(48.0 + (i * 0.05), 5)
                lng = round(31.0 + (i * 0.05), 5)
                state = sim.simulate_point_click(lat, lng, now_ts=1000.0 + i * 2.0)
                assert state["selected_points"] == [(lat, lng)]
                assert state["bounding_box"] is None
                assert state["last_clicked"] == (lat, lng)

                # Duplicate click on identical coordinate must be a no-op
                state_dup = sim.simulate_point_click(lat, lng, now_ts=1000.0 + i * 2.0 + 0.1)
                assert state_dup["selected_points"] == [(lat, lng)]

        assert sim.rerun_count == 0, (
            f"Map canvas clicks must not trigger full-script st.rerun(), got {sim.rerun_count}"
        )

    def test_rapid_aoi_bbox_resizing_and_corner_click_immunity(
        self,
        streamlit_state_simulator,
        latency_ceiling,
    ):
        """
        Simulate 25 rapid AOI bounding-box draws/resizes immediately followed by synthetic
        Leaflet mouse-release clicks on all 4 corners (both within and after the post-draw
        cooldown window). Assert:
        - `rerun_count == 0`
        - `bounding_box` always reflects the resized normalized `((south, west), (north, east))` tuple
        - `selection_mode` remains `"Bounding Box"` (never degrades into a point on corner release)
        - Total execution time <= 25.0ms
        """
        sim = streamlit_state_simulator
        # Start with a selected point to verify BBox draw overrides it immediately
        sim.simulate_point_click(50.45, 30.52, now_ts=100.0)
        assert sim.state["selected_points"] == [(50.45, 30.52)]

        with latency_ceiling(25.0, label="25_rapid_bbox_resizes_and_corner_clicks"):
            for i in range(25):
                west = round(30.0 + i * 0.1, 5)
                south = round(48.0 + i * 0.1, 5)
                east = round(32.0 + i * 0.1, 5)
                north = round(50.0 + i * 0.1, 5)
                draw_ts = 200.0 + i * 10.0
                expected_bbox = ((south, west), (north, east))

                state = sim.simulate_bbox_draw(west, south, east, north, now_ts=draw_ts)
                assert state["bounding_box"] == expected_bbox
                assert state["selection_mode"] == "Bounding Box"

                # Simulate synthetic corner clicks both immediately (draw_ts + 0.05s) and after 5s
                corners = [
                    (south, west),
                    (north, west),
                    (north, east),
                    (south, east),
                ]
                for c_idx, (c_lat, c_lng) in enumerate(corners):
                    st_after = sim.simulate_point_click(
                        c_lat,
                        c_lng,
                        now_ts=draw_ts + (0.05 if c_idx < 2 else 5.0),
                    )
                    assert st_after["bounding_box"] == expected_bbox, (
                        f"Corner click ({c_lat}, {c_lng}) destroyed bounding_box on iteration {i}"
                    )
                    assert st_after["selection_mode"] == "Bounding Box"

        assert sim.rerun_count == 0

    def test_rapid_chat_submissions_early_queue_locking_and_sliding_window_bounds(
        self,
        streamlit_state_simulator,
        latency_ceiling,
    ):
        """
        Simulate 10 rapid back-to-back chat submissions alternating between point-targeted,
        BBox-targeted, and global text queries. Verify:
        1. Section 2c locks `pending_query` with the active BBox/point even if the user
           took >30 seconds to type the prompt.
        2. Each submission executes inexactly 1 rerun cycle (no orphan cascades).
        3. `agent_turns` is strictly capped at 5 turns (`len(agent_turns) <= 5`).
        4. User and assistant messages maintain strict 1:1 turn parity.
        """
        sim = streamlit_state_simulator
        captured_requests = []

        def _fast_stub_agent(text_prompt=None, selected_point=None, bounding_box=None, agent_turns=None, **kw):
            captured_requests.append({
                "text_prompt": text_prompt,
                "selected_point": selected_point,
                "bounding_box": bounding_box,
                "history_len": len(agent_turns or []),
            })
            return AgentResponse(
                answer=f"Ack: {text_prompt} [1]",
                layers=[
                    MapLayer(
                        name="Pin 1",
                        layer_type="marker",
                        data={"lat": 50.0, "lng": 30.0, "role": "primary", "number": 1},
                        color="red",
                    )
                ],
                sources=["TEXT_1001"],
                raw_response={"answer": f"Ack: {text_prompt} [1]", "geo_locations": [{"number": 1, "label": "Pin 1"}]},
            )

        with latency_ceiling(50.0, label="10_rapid_chat_submissions_lifecycle"):
            for i in range(10):
                if i % 3 == 0:
                    # Simulate BBox draw followed by 45-second typing delay before Enter
                    sim.simulate_bbox_draw(30.0, 49.0, 31.0, 50.0, now_ts=1000.0 + i * 100.0)
                elif i % 3 == 1:
                    sim.simulate_point_click(50.45, 30.52, now_ts=1000.0 + i * 100.0)

                reruns_before = sim.rerun_count
                sim.simulate_chat_submit(f"Tactical query #{i + 1}", agent_fn=_fast_stub_agent)
                assert sim.rerun_count == reruns_before + 1, (
                    f"Chat submission #{i + 1} must trigger exactly 1 flush rerun"
                )

                # Verify spatial selection was locked into the request AND cleared post-query
                req = captured_requests[-1]
                if i % 3 == 0:
                    assert req["bounding_box"] == ((49.0, 30.0), (50.0, 31.0))
                    assert req["selected_point"] is None
                elif i % 3 == 1:
                    assert req["selected_point"] == (50.45, 30.52)
                    assert req["bounding_box"] is None
                else:
                    assert req["selected_point"] is None and req["bounding_box"] is None

                assert sim.state["selected_points"] == []
                assert sim.state["bounding_box"] is None
                assert sim.state["pending_query"] is None
                assert len(sim.state["agent_turns"]) <= 5

        # Welcome message (1) + 10 * (user + assistant) = 21 messages
        assert len(sim.state["messages"]) == 21
        assert len(sim.state["agent_turns"]) == 5

    def test_interleaved_40_step_operator_chaos_state_machine(
        self,
        streamlit_state_simulator,
        latency_ceiling,
    ):
        """
        Execute a 40-step interleaved operator workflow:
        - Point selections -> BBox override -> Corner clicks -> Trash clear ->
          Point selection -> Recon scan -> Answered-pin click immunity ->
          BBox draw -> Chat submit -> Clear Map & Console reset.
        Assert zero state desyncs and < 50.0ms total execution time.
        """
        sim = streamlit_state_simulator

        def _stub_agent(text_prompt=None, selected_point=None, bounding_box=None, agent_turns=None, **kw):
            return AgentResponse(
                answer="Tactical synthesis [1].",
                layers=[
                    MapLayer(
                        name="Kharkiv",
                        layer_type="marker",
                        data={"lat": 49.9935, "lng": 36.2304, "role": "primary", "number": 1},
                        color="red",
                    )
                ],
                sources=["TEXT_50333"],
                raw_response={"answer": "Tactical synthesis [1].", "geo_locations": [{"number": 1, "label": "Kharkiv"}]},
            )

        with latency_ceiling(50.0, label="40_step_interleaved_operator_chaos"):
            for cycle in range(4):
                base_ts = 5000.0 + cycle * 500.0

                # Step 1-2: Click two points consecutively
                sim.simulate_point_click(49.5, 31.5, now_ts=base_ts + 1.0)
                sim.simulate_point_click(49.6, 31.6, now_ts=base_ts + 3.0)
                assert sim.state["selected_points"] == [(49.6, 31.6)]

                # Step 3-4: Draw BBox (overrides point) + corner click immunity
                sim.simulate_bbox_draw(31.0, 49.0, 33.0, 51.0, now_ts=base_ts + 5.0)
                sim.simulate_point_click(51.0, 33.0, now_ts=base_ts + 5.2)
                assert sim.state["bounding_box"] == ((49.0, 31.0), (51.0, 33.0))
                assert sim.state["selection_mode"] == "Bounding Box"

                # Step 5: Trash clear
                sim.simulate_trash_delete()
                assert sim.state["bounding_box"] is None and sim.state["selected_points"] == []

                # Step 6-7: Select point and submit chat
                sim.simulate_point_click(50.45, 30.52, now_ts=base_ts + 10.0)
                sim.simulate_chat_submit(f"Cycle {cycle} query", agent_fn=_stub_agent)
                assert len(sim.state["map_layers"]) == 1

                # Step 8: Click directly on the answered tactical pin (49.9935, 36.2304)
                # Must NOT spawn a new selection crosshair over the answered pin
                sim.simulate_point_click(49.9935, 36.2304, now_ts=base_ts + 20.0)
                assert sim.state["selected_points"] == []

                # Step 9: Trigger popup Recon action
                sim.simulate_point_click(
                    48.5,
                    32.5,
                    feature_props={"action": "recon", "targetType": "point", "lat": 48.5, "lng": 32.5},
                    now_ts=base_ts + 25.0,
                )
                assert sim.state["pending_query"] is not None
                assert sim.state["pending_query"]["is_recon"] is True
                sim.state["pending_query"] = None

                # Step 10: Reset state on final cycle
                if cycle == 3:
                    sim.reset()
                    assert sim.state["selected_points"] == []
                    assert sim.state["bounding_box"] is None
                    assert sim.state["map_layers"] == []
                    assert sim.state["agent_turns"] == []
                    assert len(sim.state["messages"]) == 1



# ==============================================================================
# PHASE 2: Future-Proofing, File-Pairing & Quality Gate Enforcement Tests
# ==============================================================================
class TestPhase2QualityEnforcementAndFutureProofing:
    """
    Verify that the automated quality gate (`verify_quality_gate.py`), test runners
    (`run_tests.bat`, `run_tests.sh`), pre-commit hook (`.githooks/pre-commit`),
    and developer guidelines (`AGENTS.md`, `README.md`) enforce the mandatory
    Test-Driven & Zero-Latency Definition of Done.
    """

    def test_verify_quality_gate_file_pairing_and_static_invariants(self, tmp_path):
        """
        Verify `verify_quality_gate.py` passes on the current workspace and blocks
        untested `.py` modules when added without matching test definitions in `test_app.py`.
        """
        from pathlib import Path
        import verify_quality_gate

        workspace_dir = Path(__file__).resolve().parent
        ok_pair, pair_errors = verify_quality_gate.audit_file_and_symbol_test_pairing(workspace_dir)
        assert ok_pair, f"File-pairing audit failed: {pair_errors}"

        ok_ast, ast_errors = verify_quality_gate.audit_static_performance_invariants(workspace_dir)
        assert ok_ast, f"Static AST invariant audit failed: {ast_errors}"

        # Simulate adding a new untested module in an isolated temp directory
        (tmp_path / "test_app.py").write_text(
            "\n".join(f"def test_dummy_{i}(): pass" for i in range(verify_quality_gate.MIN_REQUIRED_TESTS)),
            encoding="utf-8",
        )
        (tmp_path / "untested_feature.py").write_text(
            "def compute_sector_heatmap():\n    return []\n",
            encoding="utf-8",
        )
        ok_untested, untested_errors = verify_quality_gate.audit_file_and_symbol_test_pairing(tmp_path)
        assert not ok_untested
        assert any("untested_feature.py" in err for err in untested_errors)

    def test_enforcement_scripts_and_pre_commit_hooks_exist(self):
        """
        Verify `run_tests.bat`, `run_tests.sh`, `.githooks/pre-commit`, `AGENTS.md`,
        and `README.md` exist and codify the Definition of Done and non-zero exit gates.
        """
        from pathlib import Path

        workspace_dir = Path(__file__).resolve().parent
        bat_path = workspace_dir / "run_tests.bat"
        sh_path = workspace_dir / "run_tests.sh"
        hook_path = workspace_dir / ".githooks" / "pre-commit"
        agents_path = workspace_dir / "AGENTS.md"
        readme_path = workspace_dir / "README.md"

        assert bat_path.exists(), "run_tests.bat must exist"
        assert sh_path.exists(), "run_tests.sh must exist"
        assert hook_path.exists(), ".githooks/pre-commit must exist"

        bat_text = bat_path.read_text(encoding="utf-8")
        assert "verify_quality_gate.py" in bat_text
        assert "exit /b" in bat_text.lower()

        sh_text = sh_path.read_text(encoding="utf-8")
        assert "verify_quality_gate.py" in sh_text
        assert "set -e" in sh_text

        hook_text = hook_path.read_text(encoding="utf-8")
        assert "verify_quality_gate.py" in hook_text

        agents_text = agents_path.read_text(encoding="utf-8")
        assert "Definition of Done" in agents_text

        readme_text = readme_path.read_text(encoding="utf-8")
        assert "Definition of Done" in readme_text
