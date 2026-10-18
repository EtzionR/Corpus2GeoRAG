"""The agent: entity resolution, the three graph tools, the tool-calling loop, synthesis, run_agent.

Flow for one question (DESIGN.md has the full walkthrough and the reasoning behind each piece):
  1. run_tool_loop   - an LLM call decides which graph tools to call, gathering evidence
  2. generate_answer - a second LLM call writes the answer and picks node ids for the map
  3. build_response  - plain code looks up every chosen node's real coordinates and sources.
                       This is the trust boundary: the LLM picks *what*, code supplies *where*.
"""
import difflib
import logging
import os
from typing import Optional

import openai
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from pydantic import BaseModel, Field, ValidationError

from contracts import AgentResponse, GeoLocation, PointGeometry
from graph_client import GraphClient

logger = logging.getLogger(__name__)


# --- Errors: the UI catches AgentError and shows str(e) -------------------------------------

class AgentError(RuntimeError):
    """Base class for every error the agent raises on purpose. The message is meant for people."""


class InvalidRequestError(AgentError):
    """The question or location passed in doesn't match the contract."""


class LLMNotConfiguredError(AgentError):
    """No OpenRouter key was given, or OpenRouter rejected it."""


class LLMRateLimitError(AgentError):
    """OpenRouter's rate limit was hit (common on free models) - retry shortly."""


class LLMError(AgentError):
    """OpenRouter failed, or the LLM answered in a shape the agent can't use - retry."""


# --- LLM setup -------------------------------------------------------------------------------

# The model for every LLM call. Hardcoded on purpose: never read it from .env or the caller.
# It stays on OpenRouter's free router until the flow is validated, so testing costs nothing;
# moving to a paid model is a deliberate code change reviewed through a PR, not a local setting.
# Note: "openrouter/free" picks an available free model per request, so behaviour can vary
# between runs.
MODEL = "openrouter/free"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def get_llm(api_key: Optional[str] = None):
    """An OpenRouter chat client on the caller's key.

    Everyone who runs the agent (including the UI team) uses their OWN OpenRouter key: passed
    as api_key, or else OPENROUTER_API_KEY from AgentRag/.env (copy .env.example). The key is
    never hardcoded, never logged, and never sent anywhere except OpenRouter.
    """
    api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise LLMNotConfiguredError(
            "No OpenRouter API key. Pass api_key=... to query(), or copy AgentRag/.env.example "
            "to AgentRag/.env and put your own key in it (https://openrouter.ai/keys).")
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(model=MODEL, api_key=api_key, base_url=OPENROUTER_BASE_URL, temperature=0)


# --- Handling imperfect questions: typos and ambiguous names ---------------------------------

def resolve_entity_name(name: str, all_names: list[str]) -> dict:
    """Tiered name resolution: exact -> substring -> fuzzy -> ambiguous/not-found.
    Never silently guesses when two or more candidates are close enough to be unclear."""
    low = name.lower()

    for n in all_names:                              # 1. exact (case-insensitive)
        if n.lower() == low:
            return {"status": "resolved", "match": n, "note": None}

    substr_hits = [n for n in all_names if low in n.lower()]   # 2. substring
    if len(substr_hits) == 1:
        return {"status": "resolved", "match": substr_hits[0],
                "note": f"matched {name!r} to {substr_hits[0]!r} by substring"}
    if len(substr_hits) > 1:
        return {"status": "ambiguous", "candidates": substr_hits}

    close = difflib.get_close_matches(name, all_names, n=3, cutoff=0.6)   # 3. fuzzy
    if len(close) == 1:
        return {"status": "resolved", "match": close[0],
                "note": f"{name!r} not found exactly - closest match was {close[0]!r}"}
    if len(close) > 1:
        scores = [difflib.SequenceMatcher(None, name.lower(), c.lower()).ratio() for c in close]
        if scores[0] - scores[1] > 0.15:              # top match clearly better than the runner-up
            return {"status": "resolved", "match": close[0],
                    "note": f"{name!r} not found exactly - closest match was {close[0]!r}"}
        return {"status": "ambiguous", "candidates": close}   # too close to call

    return {"status": "not_found", "candidates": []}


# --- The toolbox -----------------------------------------------------------------------------

class RetrievalContext:
    """Per-request state the tools write to: which source_doc backed each fact."""

    def __init__(self, g: GraphClient):
        self.g = g
        self.citations: dict[str, set] = {}   # node_id -> set of source_doc filenames

    def log_citation(self, node_id: str, source_doc):
        if source_doc:
            self.citations.setdefault(node_id, set()).add(source_doc)


def make_tools(ctx: RetrievalContext) -> list:
    """Build the three graph tools, bound to one request's RetrievalContext.

    The notebook kept this context in a module-level global (CTX). If two queries ever overlap
    (two browser tabs on the same app, say), a shared global would let one query's citations
    land in the other's answer - so every query gets its own context and its own tool instances.
    """

    @tool
    def find_entities(name: str) -> str:
        """Resolve a person/location/organization name to its entity id, handling minor typos
        or alternate spellings. If the name is ambiguous, returns the candidates instead of
        guessing - do not pick one yourself if this happens."""
        res = resolve_entity_name(name, [n.name for n in ctx.g.find_nodes()])
        if res["status"] == "resolved":
            node = ctx.g.get_node(res["match"])
            note = f" ({res['note']})" if res["note"] else ""
            coords = f", lat={node.lat}, lon={node.lon}" if node.lat is not None else ""
            return f"Found: id={node.id}, type={node.type}{coords}{note}"
        elif res["status"] == "ambiguous":
            return (f"Ambiguous - multiple matches: {', '.join(res['candidates'])}. "
                    f"Do not guess - note the ambiguity in the final answer instead.")
        return f"No entity found matching {name!r}."

    @tool
    def get_related(entity_id: str, relation: str = "") -> str:
        """Get entities connected to a given entity id (use find_entities first to get a real id),
        optionally filtered by relation name. Returns the evidence text and source document behind
        each connection - this is where the actual facts live in this graph."""
        node = ctx.g.get_node(entity_id)
        if node is None:
            return f"No entity with id {entity_id!r}. Call find_entities first."
        neighbors = ctx.g.get_neighbors(entity_id, relation=relation or None)
        if not neighbors:
            return f"No connections found for {entity_id!r}."
        lines = []
        for edge, nb in neighbors:
            doc = edge.props.get("source_doc")
            ctx.log_citation(nb.id, doc)
            ctx.log_citation(entity_id, doc)
            lines.append(f"- {entity_id} --{edge.relation}--> {nb.id} ({nb.type}) | "
                         f"evidence: \"{edge.props.get('evidence', '')}\" | source: {doc}")
        return "\n".join(lines)

    @tool
    def search_mentions(keyword: str) -> str:
        """Search all connection evidence text for a keyword (e.g. 'drone attack', 'battle').
        Use this when there's no single named entity to look up - e.g. finding every place
        where a type of event was mentioned, since this graph has no dedicated event nodes."""
        hits = ctx.g.search_evidence(keyword)
        if not hits:
            return f"No mentions of {keyword!r} found."
        lines = []
        for edge, a, b in hits:
            doc = edge.props.get("source_doc")
            for n in (a, b):
                ctx.log_citation(n.id, doc)
            lines.append(f"- {a.id} <-> {b.id} | evidence: \"{edge.props.get('evidence', '')}\" | source: {doc}")
        return "\n".join(lines)

    return [find_entities, get_related, search_mentions]


# --- The tool-calling loop -------------------------------------------------------------------

AGENT_SYSTEM_PROMPT = """You are the research step of an agent answering questions about a
warfare-related knowledge graph. You have three tools:

- find_entities(name): resolve a name to a graph entity. ALWAYS call this before get_related -
  you need a real entity id. If it says "Ambiguous", do not guess which one is meant; move on
  and let the final answer note the ambiguity.
- get_related(entity_id, relation=""): see what is connected to an entity, with the evidence
  text and source document behind each connection.
- search_mentions(keyword): search evidence text across the whole graph for a keyword. Use this
  for questions about a TYPE of event ("drone attacks", "battles") rather than one named thing,
  since this graph has no dedicated event nodes - evidence text is the only place that
  information exists.

Call as many tools as you need. When you have enough evidence - or further calls clearly will
not help - reply with a short note that you are done, with no further tool calls. Do not write
the final answer yourself; a separate step does that from what you gather here."""


def _invoke_tool(tool_map: dict, call: dict) -> str:
    """Run one tool call. A malformed call from the model (unknown tool, wrong arguments) comes
    back as a message it can read and recover from, instead of failing the whole request."""
    t = tool_map.get(call["name"])
    if t is None:
        return f"Unknown tool {call['name']!r}. Available tools: {', '.join(tool_map)}."
    try:
        return t.invoke(call["args"])
    except ValidationError as e:
        return f"Invalid arguments for {call['name']}: {e.errors(include_url=False)}"


def run_tool_loop(question: str, g: GraphClient, llm, max_iterations: int = 6):
    """Let the LLM call graph tools until it has enough evidence (or max_iterations is hit).
    Returns (evidence_text, citation_index, transcript)."""
    ctx = RetrievalContext(g)
    tools = make_tools(ctx)
    tool_map = {t.name: t for t in tools}
    llm_with_tools = llm.bind_tools(tools)
    messages = [SystemMessage(content=AGENT_SYSTEM_PROMPT), HumanMessage(content=question)]
    transcript = []

    for i in range(max_iterations):
        response = llm_with_tools.invoke(messages)
        messages.append(response)
        if not response.tool_calls:
            logger.debug("[iteration %d] model is done - no further tool calls.", i + 1)
            break
        for call in response.tool_calls:
            result = _invoke_tool(tool_map, call)
            logger.debug("[iteration %d] %s(%s) ->\n  %s", i + 1, call["name"], call["args"], result)
            transcript.append((call["name"], call["args"], result))
            messages.append(ToolMessage(content=str(result), tool_call_id=call["id"]))
    else:
        logger.debug("Hit max_iterations (%d) - stopping.", max_iterations)

    evidence_text = "\n\n".join(f"[{name}({args})]\n{result}" for name, args, result in transcript)
    return evidence_text, dict(ctx.citations), transcript


# --- Synthesis: evidence in, structured answer out -------------------------------------------

class LLMDraft(BaseModel):
    answer: str = Field(description="Answer to the question, based ONLY on the evidence gathered. "
                                    "If a name was ambiguous or not found, say so plainly.")
    feature_node_ids: list[str] = Field(default_factory=list,
        description="Ids of entities (from the evidence) to show on the map. Only ids that appear "
                    "in the evidence and have coordinates.")


SYNTHESIS_SYSTEM_PROMPT = """You write the final answer to a question about a warfare-related
knowledge graph, using ONLY the evidence gathered below (tool results from a prior research step).
Never use outside knowledge. Phrase claims as 'According to the corpus...'. If an entity name was
ambiguous or not found during research, say so plainly instead of guessing. Pick map nodes only
by id, from ids that appear in the evidence and have coordinates."""


def generate_answer(question: str, evidence_text: str, llm) -> LLMDraft:
    structured_llm = llm.with_structured_output(LLMDraft, method="function_calling")
    draft = structured_llm.invoke([
        ("system", SYNTHESIS_SYSTEM_PROMPT),
        ("human", f"EVIDENCE GATHERED:\n{evidence_text}\n\nQUESTION: {question}"),
    ])
    if draft is None:   # the model replied without filling in the LLMDraft structure
        raise LLMError("The LLM returned no structured answer. Try again.")
    return draft


def build_response(draft: LLMDraft, g: GraphClient, citation_index: dict) -> AgentResponse:
    """Turn the LLM's draft into the response. Coordinates and sources come only from the
    graph and the tool loop's citations - never from anything the LLM wrote."""
    geo_locations, sources = [], []
    for nid in dict.fromkeys(draft.feature_node_ids):   # de-duplicated, order kept
        node = g.get_node(nid)
        if node is None or node.lat is None or node.lon is None:
            continue   # drop anything the LLM named that isn't a real, located node
        srcs = sorted(citation_index.get(nid, []))
        geo_locations.append(GeoLocation(
            id=nid, label=node.name,
            geometry=PointGeometry(coordinates=(node.lon, node.lat)),   # [lon, lat]
            kind="place" if node.type == "location" else "event",
            sources=srcs))
        for s in srcs:
            if s not in sources:
                sources.append(s)
    return AgentResponse(answer=draft.answer, geo_locations=geo_locations, sources=sources)


# --- Putting it together ---------------------------------------------------------------------

def run_agent(question: str, g: GraphClient, api_key: Optional[str] = None,
              max_iterations: int = 6) -> AgentResponse:
    """A question in, an AgentResponse out. The UI calls this through georag_agent.query()."""
    llm = get_llm(api_key)
    try:
        evidence_text, citation_index, transcript = run_tool_loop(question, g, llm, max_iterations=max_iterations)
        logger.debug("evidence handed to synthesis:\n%s", evidence_text or "(none gathered)")
        draft = generate_answer(question, evidence_text, llm)
    except openai.AuthenticationError as e:
        raise LLMNotConfiguredError("OpenRouter rejected the API key. Check the key you passed, "
                                    "or OPENROUTER_API_KEY in AgentRag/.env.") from e
    except openai.RateLimitError as e:
        raise LLMRateLimitError("OpenRouter rate limit reached (free models are rate-limited). "
                                "Try again shortly.") from e
    except openai.APIError as e:
        raise LLMError(f"The OpenRouter call failed: {e.message}") from e
    logger.debug("LLMDraft:\n%s", draft.model_dump_json(indent=2))
    response = build_response(draft, g, citation_index)
    logger.info("answered with %d tool calls, %d geo_locations, %d sources",
                len(transcript), len(response.geo_locations), len(response.sources))
    return response
