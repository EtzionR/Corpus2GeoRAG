"""Request/response models - the one source of truth both the agent and the UI code against.

Two groups of models live here:
  - Graph contracts (GraphNode, GraphEdge): what the agent sees of the graph, whatever the
    graph team's raw schema looks like. graph_client.py is the only place that builds them.
  - Interface contracts: what georag_agent.query() and get_source_text() accept and return
    (see README "Interface").

Coordinates are [longitude, latitude] (GeoJSON order) everywhere.
"""
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator


# --- Graph contracts -----------------------------------------------------------------------

class GraphNode(BaseModel):
    id: str
    type: str                      # "person" | "location" | "organization" | anything new, passed through
    name: str
    text: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    props: dict = Field(default_factory=dict)


class GraphEdge(BaseModel):
    source: str
    target: str
    relation: str
    props: dict = Field(default_factory=dict)   # on the real graph: evidence, source_doc


# --- Geometry --------------------------------------------------------------------------------

Longitude = Annotated[float, Field(ge=-180, le=180)]
Latitude = Annotated[float, Field(ge=-90, le=90)]
Position = tuple[Longitude, Latitude]           # [lon, lat] - GeoJSON order


class PointGeometry(BaseModel):
    type: Literal["point"] = "point"
    coordinates: Position


# --- query(): input --------------------------------------------------------------------------

class PointLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["point"]
    coordinates: Position
    radius_m: Optional[float] = Field(default=None, gt=0, description="Search radius in metres.")


class PolygonLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")   # radius_m is point-only, so it's rejected here

    type: Literal["polygon"]
    coordinates: list[list[Position]] = Field(
        min_length=1,
        description="GeoJSON polygon: a list of closed rings, the first is the outer boundary.")

    @field_validator("coordinates")
    @classmethod
    def _rings_are_closed(cls, rings):
        for ring in rings:
            if len(ring) < 4 or ring[0] != ring[-1]:
                raise ValueError("each polygon ring needs at least 4 positions, "
                                 "and its first and last positions must be the same")
        return rings


GeoLocationIn = Annotated[Union[PointLocation, PolygonLocation], Field(discriminator="type")]


# --- query(): output -------------------------------------------------------------------------

class GeoLocation(BaseModel):
    id: str = Field(description="Graph node id - needed to resolve follow-ups like "
                                "'tell me more about number 2' against chat_history.")
    label: str
    geometry: PointGeometry
    kind: Literal["event", "place"]
    sources: list[str] = Field(default_factory=list)


class AgentResponse(BaseModel):
    answer: str
    geo_locations: list[GeoLocation] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list, description="Union across the whole answer.")


class ChatTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    response: AgentResponse        # a prior response, exactly as query() returned it


class QueryRequest(BaseModel):
    # Unknown fields are rejected, so a misspelled field fails loudly instead of being ignored.
    # There is deliberately no model field - MODEL lives in agent.py only.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text_prompt: str = Field(min_length=1)
    geo_location: Optional[GeoLocationIn] = None
    chat_history: list[ChatTurn] = Field(default_factory=list)


# --- get_source_text(): output ---------------------------------------------------------------

class SourceTextResponse(BaseModel):
    text: str
    document: str
