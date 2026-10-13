"""GeoRAG agent - the two functions the UI calls. Everything else in this folder is internals.

Setup, once per machine:
    pip install -r AgentRag/requirements.txt
    Get your OWN OpenRouter key at https://openrouter.ai/keys (free models cost nothing). Then
    either pass it as api_key=... to query(), or put it in AgentRag/.env (copy .env.example).
    Never write the key into a .py file - it would end up on GitHub with the code.

Use from the UI (e.g. ui/app.py):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "AgentRag"))
    from georag_agent import AgentError, get_source_text, query

    try:
        result = query("Where is Kyiv?", api_key=your_key)   # api_key can be left out if it's in .env
    except AgentError as e:
        print(e)                 # a readable message: missing key, rate limit, bad input, ...

    result["answer"]             # the written answer
    result["geo_locations"]      # [{"id", "label", "geometry": {"type": "point", "coordinates": [lon, lat]},
                                 #   "kind", "sources"}, ...]
    result["sources"]            # source pointers for the whole answer
    get_source_text(result["sources"][0])   # {"text", "document"}, or None if unknown

Coordinates are [longitude, latitude] (GeoJSON order) everywhere.
"""
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")   # before anything reads os.environ

from pydantic import ValidationError

import agent
from agent import (AgentError, InvalidRequestError, LLMError, LLMNotConfiguredError,
                   LLMRateLimitError)
from contracts import QueryRequest, SourceTextResponse
from graph_client import GraphClient, NetworkXGraphClient, load_node_link_json

__all__ = ["query", "get_source_text", "AgentError", "InvalidRequestError",
           "LLMNotConfiguredError", "LLMRateLimitError", "LLMError"]

# The graph team's file, read in place and never modified. GRAPH_PATH in .env overrides it.
DEFAULT_GRAPH_PATH = HERE.parent / "Graph_n_Geocoding" / "knowledge_graph.json"

_graph: Optional[GraphClient] = None


def get_graph() -> GraphClient:
    """The knowledge graph, loaded on first use and kept for the life of the app.
    Restart the app to pick up a new version of the graph file."""
    global _graph
    if _graph is None:
        path = Path(os.environ.get("GRAPH_PATH") or DEFAULT_GRAPH_PATH)
        if not path.is_file():
            # No fallback graph on purpose: answering from a stand-in would look like it works.
            raise AgentError(f"Knowledge graph not found at {path}. "
                             f"Set GRAPH_PATH in AgentRag/.env if it lives somewhere else.")
        _graph = NetworkXGraphClient(load_node_link_json(str(path)))
    return _graph


def query(text_prompt: str, geo_location: Optional[dict] = None,
          chat_history: Optional[list] = None, api_key: Optional[str] = None) -> dict:
    """Answer one question from the knowledge graph.

    text_prompt   the user's question
    geo_location  None, {"type": "point", "coordinates": [lon, lat], "radius_m": 500}
                  or {"type": "polygon", "coordinates": [[[lon, lat], ...]]}
    chat_history  [{"query": "...", "response": <a dict query() returned earlier>}, ...]
    api_key       your OpenRouter key; if left out, OPENROUTER_API_KEY from AgentRag/.env

    Returns {"answer", "geo_locations", "sources"}. Raises AgentError (or a subclass of it)
    with a message you can show to the user.
    """
    try:
        req = QueryRequest(text_prompt=text_prompt, geo_location=geo_location,
                           chat_history=chat_history or [])
    except ValidationError as e:
        raise InvalidRequestError(f"Invalid request: {e}") from e
    # geo_location and chat_history are checked against the contract above, but the agent
    # doesn't act on them yet (see README "Current status").
    return agent.run_agent(req.text_prompt, get_graph(), api_key=api_key).model_dump(mode="json")


def get_source_text(pointer: str) -> Optional[dict]:
    """The text behind one source pointer (any value from a query() result's "sources").
    No LLM involved. Returns {"text", "document"}, or None if the pointer isn't known."""
    passages = get_graph().get_source_passages(pointer)
    if not passages:
        return None
    return SourceTextResponse(text="\n\n".join(passages), document=pointer).model_dump()
