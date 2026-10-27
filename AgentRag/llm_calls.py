"""Structured LLM calls, with a record of what each one cost.

Every LLM call in the agent goes through structured_call(), so each answer can report which model
actually answered (the free router picks one per call), how many tokens it used, what it cost, and
how long it took. The evaluation harness relies on these records for its cost cap and reports.
"""
import hashlib
import time
from typing import Optional

import openai
from pydantic import BaseModel

from agent import LLMNotConfiguredError


class LLMCall(BaseModel):
    step: str                       # "understand", "write", ...
    model: Optional[str] = None     # the model that actually answered
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0           # as reported by OpenRouter; 0 for a reused answer
    seconds: float = 0.0
    cached: bool = False            # reused from the harness's saved answers; no request made
    ok: bool = True                 # False: the model answered but not in the requested structure
    prompt_version: Optional[str] = None   # short hash of the instructions (system message)
    request: Optional[str] = None          # the message sent after the instructions
    response: Optional[dict] = None        # the model's raw structured answer, before any code rules
    raw_text: Optional[str] = None         # what the model wrote instead, when it skipped the structure


def prompt_version(system_text: str) -> str:
    return hashlib.sha256(system_text.encode("utf-8")).hexdigest()[:8]


def structured_call(llm, schema: type[BaseModel], messages: list, step: str):
    """Ask for `schema`. Returns (parsed or None, LLMCall). API errors (rate limit, network) are
    raised to the caller; an answer that doesn't fit the structure comes back as None. A rejected
    key stops the whole question with a readable LLMNotConfiguredError: no step can work without it."""
    start = time.time()
    try:
        result = llm.with_structured_output(schema, method="function_calling", include_raw=True).invoke(messages)
    except openai.AuthenticationError as e:
        raise LLMNotConfiguredError("OpenRouter rejected the API key. Check the key you passed, "
                                    "or OPENROUTER_API_KEY in AgentRag/.env.") from e
    seconds = time.time() - start
    raw, parsed = result.get("raw"), result.get("parsed")
    meta = getattr(raw, "response_metadata", None) or {}
    usage = getattr(raw, "usage_metadata", None) or {}
    tool_calls = getattr(raw, "tool_calls", None) or []
    cached = bool(meta.get("cached"))
    system = next((text for role, text in messages if role == "system"), "")
    call = LLMCall(
        step=step, model=meta.get("model_name"),
        input_tokens=usage.get("input_tokens", 0), output_tokens=usage.get("output_tokens", 0),
        cost_usd=0.0 if cached else float((meta.get("token_usage") or {}).get("cost") or 0.0),
        seconds=round(seconds, 2), cached=cached, ok=parsed is not None,
        prompt_version=prompt_version(system), request=messages[-1][1],
        response=tool_calls[0]["args"] if tool_calls else (parsed.model_dump() if parsed is not None else None),
        raw_text=(raw.content[:2000] if parsed is None and isinstance(getattr(raw, "content", None), str)
                  and raw.content.strip() else None))
    return parsed, call
