"""The whole flow for one question, in order: ① understand → ② resolve → ③ retrieve → ④ evidence →
⑤ write → ⑥ result. Used by georag_agent.query() (the app) and eval/run.py (the test harness), so
both run exactly the same steps.
"""
import time
from typing import Optional

from evidence import DEFAULT_BUDGET_WORDS, build_evidence
from graph_index import GraphIndex
from planner import Area, understand
from resolver import resolve
from result import build_result
from retrieve import retrieve
from writer import write

STEPS = ["understand", "resolve", "retrieve", "evidence", "write", "result"]


def run(question: str, gi: GraphIndex, llm, area: Optional[Area] = None, history: Optional[list] = None,
        map_radius_m: Optional[float] = None, until: str = "result",
        budget_words: int = DEFAULT_BUDGET_WORDS) -> dict:
    """Run the steps up to `until` and return each step's output by name."""
    start = time.time()
    last = STEPS.index(until)
    out: dict = {"plan": understand(question, area=area, history=history or [], llm=llm, map_radius_m=map_radius_m)}
    if last >= 1:
        out["resolve"] = resolve(out["plan"], gi, llm=llm)
    if last >= 2:
        out["retrieve"] = retrieve(out["plan"], out["resolve"], gi)
    if last >= 3:
        out["evidence"] = build_evidence(out["plan"], out["retrieve"], gi, budget_words=budget_words)
    if last >= 4:
        out["write"] = write(out["plan"], out["evidence"], llm)
    if last >= 5:
        out["result"] = build_result(out["plan"], out["resolve"], out["retrieve"], out["evidence"], out["write"],
                                     gi, seconds=time.time() - start)
    return out
