"""GeoRAG agent - the two functions the UI calls. Everything else in this folder is internals.

Setup, once per machine:
    pip install -r AgentRag/requirements.txt
    Get your OWN OpenRouter key at https://openrouter.ai/keys. Then either pass it as api_key=...
    to query(), or put it in AgentRag/.env (copy .env.example). Never write the key into a .py file.

Use from the UI (e.g. ui/app.py):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "AgentRag"))
    from georag_agent import AgentError, get_source_text, query

    try:
        result = query("Show me Kyiv", api_key=your_key)        # api_key can be left out if it's in .env
    except AgentError as e:
        print(e)                     # a readable message: missing key, bad input, ...

    result["answer"]                 # the written answer; [3] cites place 3, [S2] cites a passage
    result["geo_locations"]          # every place found: number, id, label, kind, role, geometry (Point),
                                     #   shape (outline, for the places the answer discusses), why, sources
    result["regions"]                # nested overview of big lists: country -> region -> place numbers
    result["citations"]              # what [S2] / [L1] point to: pointer, article, section, spans
    get_source_text("TEXT_123")      # the paragraph behind a pointer

Follow-ups: pass previous turns back as chat_history=[{"query": ..., "response": <the result dict>}];
"tell me about number 13" then means place 13 of the previous result.

Coordinates are [longitude, latitude] (GeoJSON order) everywhere. Full field list: AgentRag_README.md.
"""
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")   # before anything reads os.environ

from pydantic import ValidationError

import agent
import pipeline
from agent import (AgentError, InvalidRequestError, LLMError, LLMNotConfiguredError,
                   LLMRateLimitError)
from graph_index import DEFAULT_GRAPH_PATH, GraphIndex
from planner import Area
from schema import QueryInput

__all__ = ["query", "get_source_text", "AgentError", "InvalidRequestError",
           "LLMNotConfiguredError", "LLMRateLimitError", "LLMError"]

_graph: Optional[GraphIndex] = None


def get_graph() -> GraphIndex:
    """The knowledge graph (Graph_n_Geocoding/knowledge_graph.json.gz), loaded on first use and kept
    for the life of the app (about 15 s and 1.1 GB, once). Restart the app to pick up a new graph.
    GRAPH_PATH in .env points somewhere else."""
    global _graph
    if _graph is None:
        try:
            _graph = GraphIndex.load()
        except FileNotFoundError as e:
            raise AgentError(str(e)) from e
    return _graph


def query(text_prompt: str, geo_location: Optional[dict] = None,
          chat_history: Optional[list] = None, api_key: Optional[str] = None) -> dict:
    """Answer one question from the knowledge graph.

    text_prompt   the user's question
    geo_location  None, {"type": "Point", "coordinates": [lon, lat], "radius_m": 500}
                  or {"type": "Polygon", "coordinates": [[[lon, lat], ...]]}
    chat_history  [{"query": "...", "response": <a dict query() returned earlier>}, ...]
    api_key       your OpenRouter key; if left out, OPENROUTER_API_KEY from AgentRag/.env

    Returns the result dict (see AgentRag_README.md). Raises AgentError (or a subclass) with a
    message you can show to the user.
    """
    try:
        req = QueryInput(text_prompt=text_prompt, geo_location=geo_location, chat_history=chat_history or [])
    except ValidationError as e:
        raise InvalidRequestError(f"Invalid request: {e}") from e
    geo = req.geo_location
    area = Area(kind=geo.type.lower(), coordinates=geo.coordinates) if geo else None
    llm = agent.get_llm(api_key)
    out = pipeline.run(req.text_prompt, get_graph(), llm, area=area,
                       history=[t.model_dump() for t in req.chat_history],
                       map_radius_m=geo.radius_m if geo else None)
    return out["result"].model_dump(mode="json", exclude_none=True)


def get_source_text(pointer) -> Optional[dict]:
    """The paragraph behind a pointer ("TEXT_123", from a result's sources or citations). No LLM.
    Returns {"pointer", "text", "document", "section", "paragraph_index"}, or None if unknown."""
    text_id = str(pointer).removeprefix("TEXT_")
    if not text_id.isdigit():
        return None
    gi = get_graph()
    node = gi.G.nodes.get(f"TEXT_{text_id}")
    if not node or node.get("type") != "TEXT":
        return None
    return {"pointer": f"TEXT_{text_id}", "text": node["text"], "document": node["source"],
            "section": node.get("title"), "paragraph_index": node.get("index")}
