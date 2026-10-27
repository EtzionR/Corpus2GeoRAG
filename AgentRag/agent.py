"""The model, the OpenRouter client, and the errors the agent raises.

The question-answering flow itself is in pipeline.py (steps 1-6); georag_agent.py is what the UI
calls. This module is kept small on purpose: MODEL lives here so changing it is one reviewed line.
"""
import os
from typing import Optional


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
# A strong free model, pinned so plans don't depend on which model the free router happens to pick
# (DECISIONS_LOG P2-41); if it's busy or unavailable, OpenRouter falls back to the free router.
# Moving to a paid model is a deliberate code change reviewed through a PR, not a local setting.
MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
FALLBACK_MODELS = ["openrouter/free"]
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def get_llm(api_key: Optional[str] = None, model: Optional[str] = None):
    """An OpenRouter chat client on the caller's key.

    Everyone who runs the agent (including the UI team) uses their OWN OpenRouter key: passed
    as api_key, or else OPENROUTER_API_KEY from AgentRag/.env (copy .env.example). The key is
    never hardcoded, never logged, and never sent anywhere except OpenRouter.

    model: only the evaluation harness passes this, to compare models. The app always uses MODEL,
    with FALLBACK_MODELS behind it; a model chosen for comparison gets no fallback.
    """
    api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise LLMNotConfiguredError(
            "No OpenRouter API key. Pass api_key=... to query(), or copy AgentRag/.env.example "
            "to AgentRag/.env and put your own key in it (https://openrouter.ai/keys).")
    from langchain_openai import ChatOpenAI
    extra = {"usage": {"include": True}}   # OpenRouter reports the cost of each call
    if model is None or model == MODEL:
        extra["models"] = [MODEL, *FALLBACK_MODELS]   # OpenRouter tries these in order
    return ChatOpenAI(model=model or MODEL, api_key=api_key, base_url=OPENROUTER_BASE_URL, temperature=0,
                      extra_body=extra)
