import pytest
from pydantic import ValidationError

from contracts import AgentResponse, GeoLocation, PointGeometry, QueryRequest

SQUARE = [[[30.0, 50.0], [31.0, 50.0], [31.0, 51.0], [30.0, 50.0]]]


def test_point_request_keeps_lon_lat_order():
    req = QueryRequest.model_validate({
        "text_prompt": "What happened near here?",
        "geo_location": {"type": "point", "coordinates": [30.52, 50.45], "radius_m": 500},
    })
    assert req.geo_location.coordinates == (30.52, 50.45)
    assert req.geo_location.radius_m == 500


def test_minimal_request_defaults():
    req = QueryRequest.model_validate({"text_prompt": "Where is Moscow?"})
    assert req.geo_location is None and req.chat_history == []


@pytest.mark.parametrize("coords", [[200, 50], [30, 95], [30.5], [30.5, 50.4, 10]])
def test_bad_point_coordinates_are_rejected(coords):
    with pytest.raises(ValidationError):
        QueryRequest.model_validate({"text_prompt": "q", "geo_location": {"type": "point", "coordinates": coords}})


def test_radius_must_be_positive():
    with pytest.raises(ValidationError):
        QueryRequest.model_validate({"text_prompt": "q", "geo_location": {
            "type": "point", "coordinates": [30.5, 50.4], "radius_m": 0}})


def test_polygon_accepts_closed_geojson_rings():
    req = QueryRequest.model_validate({"text_prompt": "q", "geo_location": {"type": "polygon", "coordinates": SQUARE}})
    assert req.geo_location.coordinates[0][0] == (30.0, 50.0)


@pytest.mark.parametrize("rings", [
    [[[30.0, 50.0], [31.0, 50.0], [31.0, 51.0], [30.5, 51.5]]],   # not closed
    [[[30.0, 50.0], [31.0, 50.0], [30.0, 50.0]]],                 # too few positions
    [],                                                            # no rings
])
def test_bad_polygons_are_rejected(rings):
    with pytest.raises(ValidationError):
        QueryRequest.model_validate({"text_prompt": "q", "geo_location": {"type": "polygon", "coordinates": rings}})


def test_radius_is_point_only():
    with pytest.raises(ValidationError):
        QueryRequest.model_validate({"text_prompt": "q", "geo_location": {
            "type": "polygon", "coordinates": SQUARE, "radius_m": 500}})


def test_unknown_fields_are_rejected_so_the_request_cannot_set_the_model():
    with pytest.raises(ValidationError):
        QueryRequest.model_validate({"text_prompt": "q", "model": "openai/gpt-4o"})


@pytest.mark.parametrize("prompt", ["", "   "])
def test_empty_prompt_is_rejected(prompt):
    with pytest.raises(ValidationError):
        QueryRequest.model_validate({"text_prompt": prompt})


def test_chat_history_accepts_a_prior_response_as_returned():
    prior = AgentResponse(answer="According to the corpus...", sources=["doc"], geo_locations=[
        GeoLocation(id="Kyiv", label="Kyiv", kind="place", sources=["doc"],
                    geometry=PointGeometry(coordinates=(30.52, 50.45)))])
    req = QueryRequest.model_validate({"text_prompt": "tell me more about number 1",
                                       "chat_history": [{"query": "q", "response": prior.model_dump(mode="json")}]})
    assert req.chat_history[0].response == prior


def test_response_geometry_serializes_as_geojson_order():
    loc = GeoLocation(id="Kyiv", label="Kyiv", kind="place", geometry=PointGeometry(coordinates=(30.52, 50.45)))
    assert loc.model_dump(mode="json")["geometry"] == {"type": "point", "coordinates": [30.52, 50.45]}
