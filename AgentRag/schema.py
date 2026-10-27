"""The agent's input and output contract: what the UI sends to query() and what it gets back.

Coordinates are [longitude, latitude] (GeoJSON order) everywhere, and geometries are standard
GeoJSON ("Point", "Polygon", ...). The README for the UI explains every field.
"""
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from graph_tools import RegionNode

Longitude = Annotated[float, Field(ge=-180, le=180)]
Latitude = Annotated[float, Field(ge=-90, le=90)]
Position = tuple[Longitude, Latitude]


# --- Input -----------------------------------------------------------------------------------

class GeoLocationIn(BaseModel):
    """The user's map selection: a point (with an optional radius) or a polygon."""
    model_config = ConfigDict(extra="forbid")

    type: Literal["Point", "Polygon"]
    coordinates: Any
    radius_m: Optional[float] = Field(default=None, gt=0)

    @field_validator("type", mode="before")
    @classmethod
    def _standard_case(cls, v):
        return {"point": "Point", "polygon": "Polygon"}.get(str(v).lower(), v)   # accept "point" too

    @field_validator("coordinates")
    @classmethod
    def _shape(cls, v, info):
        kind = info.data.get("type")
        if kind == "Point":
            if not (isinstance(v, (list, tuple)) and len(v) == 2):
                raise ValueError("a Point needs [longitude, latitude]")
            _check(v)
        elif kind == "Polygon":
            if not (isinstance(v, list) and v and all(isinstance(r, list) for r in v)):
                raise ValueError("a Polygon needs a list of rings: [[[lon, lat], ...]]")
            for ring in v:
                if len(ring) < 4 or list(ring[0]) != list(ring[-1]):
                    raise ValueError("each ring needs at least 4 positions, the first and last equal")
                for p in ring:
                    _check(p)
        return v


def _check(p) -> None:
    lon, lat = float(p[0]), float(p[1])
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise ValueError(f"[{lon}, {lat}] is not a [longitude, latitude] position")


class ChatTurn(BaseModel):
    query: str
    response: dict = Field(default_factory=dict)   # a previous result, as query() returned it


class QueryInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text_prompt: str = Field(min_length=1)
    geo_location: Optional[GeoLocationIn] = None
    chat_history: list[ChatTurn] = Field(default_factory=list)


# --- Output ----------------------------------------------------------------------------------

class Geometry(BaseModel):
    type: Literal["Point", "Polygon", "MultiPolygon", "LineString", "MultiLineString"]
    coordinates: list


class PlaceOut(BaseModel):
    number: int                         # the [n] the answer cites; also what "tell me about number n" uses
    id: str                             # the graph id; stable for follow-ups
    label: str
    kind: str                           # place type: town, city, state (oblast), country, road, ...
    role: Literal["primary", "context"] # primary = discussed in the answer; context = found, on the map only
    geometry: Geometry                  # a Point, [lon, lat]
    shape: Optional[Geometry] = None    # the outline (simplified), for primary places
    why: str = ""                       # one line of data: why it's in the result
    uncertain: Optional[str] = None     # the graph's point may be wrong, and why
    sources: list[str] = Field(default_factory=list)   # paragraph pointers, best first


class EntityOut(BaseModel):
    id: str
    type: str                           # PER / ORG
    role: Optional[str] = None          # acts / acted_on / mutual, relative to what was asked
    records: int = 0


class CitationOut(BaseModel):
    id: str                             # "S2", "L1" as written in the answer
    pointer: str                        # "TEXT_<id>": get_source_text(pointer) gives the paragraph
    article: str
    section: Optional[str] = None
    spans: list[list[int]] = Field(default_factory=list)   # the entities' positions in the paragraph


class MapHint(BaseModel):
    bbox: Optional[list[float]] = None  # [west, south, east, north] to zoom to
    highlight: list[int] = Field(default_factory=list)   # place numbers the answer discusses


class Alternative(BaseModel):
    id: str
    type: str


class Meta(BaseModel):
    question_type: str
    model: Optional[str] = None         # the model that answered (the last LLM call)
    llm_calls: int = 0
    cost_usd: float = 0.0
    seconds: float = 0.0


class Result(BaseModel):
    answer: str                         # with citation marks: [3] = place 3, [S2] / [L1] = a passage in citations
    answer_plain: str = ""              # the same text without the marks, for showing it plain
    status: Literal["answered", "no_data", "out_of_scope", "llm_failed"]
    grounded: bool                      # False: no graph data; the answer is the LLM's own (with a disclaimer)
    shape: str                          # list / fact / drilldown / explain
    geo_locations: list[PlaceOut] = Field(default_factory=list)
    regions: list[RegionNode] = Field(default_factory=list)
    entities: list[EntityOut] = Field(default_factory=list)
    citations: list[CitationOut] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)   # pointers of everything the answer cites
    map: MapHint = Field(default_factory=MapHint)
    follow_ups: list[str] = Field(default_factory=list)
    did_you_mean: list[Alternative] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    meta: Meta
