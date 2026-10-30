"""The evaluation harness: saved answers and the reuse window, cost cap, estimate, reports. No network."""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "eval"))

import harness  # noqa: E402
from planner import SYSTEM_PROMPT, EntityMention, PlanDraft, understand  # noqa: E402

DRAFT = PlanDraft(type="relation", relations=["ATTACKED"],
                  entities=[EntityMention(text="Mariupol", name="Mariupol", kind="LOC")])


class CountingLLM:
    """A fake paid model: counts real calls and charges $0.01 each."""

    def __init__(self, draft=DRAFT):
        self.draft, self.calls = draft, 0

    def with_structured_output(self, schema, **kwargs):
        return self

    def invoke(self, messages):
        self.calls += 1
        args = self.draft.model_dump() if self.draft else {}
        raw = AIMessage(content="", tool_calls=[{"name": "PlanDraft", "args": args, "id": "call_1"}],
                        response_metadata={"model_name": "paid/model", "token_usage": {"cost": 0.01}},
                        usage_metadata={"input_tokens": 1000, "output_tokens": 100, "total_tokens": 1100})
        return {"raw": raw, "parsed": self.draft, "parsing_error": None}


@pytest.fixture
def make_llm(tmp_path):
    def make(inner=None, cap=1.0, model="paid/model", reuse_hours=None):
        inner = inner or CountingLLM()
        return inner, harness.CachedLLM(inner, model, harness.Ledger(cap), cache_dir=tmp_path, reuse_hours=reuse_hours)
    return make


def test_by_default_every_run_asks_fresh_but_the_answer_is_saved(make_llm, tmp_path):
    inner, llm = make_llm()
    understand("Who attacked Mariupol?", llm=llm)
    second = understand("Who attacked Mariupol?", llm=llm)
    assert inner.calls == 2 and not second.llm_calls[0].cached
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_inside_the_reuse_window_an_identical_call_is_free(make_llm):
    inner, llm = make_llm(reuse_hours=8)
    first = understand("Who attacked Mariupol?", llm=llm)
    second = understand("Who attacked Mariupol?", llm=llm)
    assert inner.calls == 1 and llm.ledger.cache_hits == 1
    assert first.llm_calls[0].cost_usd == 0.01 and second.llm_calls[0].cost_usd == 0.0
    assert second.llm_calls[0].cached and second.relations == ["ATTACKED"]
    assert second.llm_calls[0].response == first.llm_calls[0].response   # the raw answer survives reuse


def test_an_answer_older_than_the_window_is_asked_again(make_llm, tmp_path):
    inner, llm = make_llm(reuse_hours=8)
    understand("Who attacked Mariupol?", llm=llm)
    saved_file = next(tmp_path.glob("*.json"))
    saved = json.loads(saved_file.read_text(encoding="utf-8"))
    saved["saved_at"] = (datetime.now() - timedelta(hours=9)).isoformat(timespec="seconds")
    saved_file.write_text(json.dumps(saved), encoding="utf-8")
    understand("Who attacked Mariupol?", llm=llm)
    assert inner.calls == 2


def test_a_different_question_or_prompt_asks_again(make_llm):
    inner, llm = make_llm(reuse_hours=8)
    understand("Who attacked Mariupol?", llm=llm)
    understand("Who attacked Mariupol today?", llm=llm)
    assert inner.calls == 2


def test_a_failed_answer_is_never_saved(make_llm, tmp_path):
    inner, llm = make_llm(CountingLLM(draft=None), reuse_hours=8)
    understand("Who attacked Mariupol?", llm=llm)
    understand("Who attacked Mariupol?", llm=llm)
    assert inner.calls == 4 and not list(tmp_path.glob("*.json"))   # 2 attempts each time


def test_the_cost_cap_stops_paid_calls_but_not_reused_ones(make_llm):
    inner, llm = make_llm(cap=0.015, reuse_hours=8)
    understand("Who attacked Mariupol?", llm=llm)        # $0.01
    understand("Who attacked Kharkiv?", llm=llm)          # $0.02 total: over the cap now
    with pytest.raises(harness.CostCapExceeded):
        understand("Who attacked Kherson?", llm=llm)
    assert understand("Who attacked Mariupol?", llm=llm).llm_calls[0].cached
    assert inner.calls == 2


def test_the_free_router_is_never_capped(make_llm):
    inner, llm = make_llm(cap=0.0, model=harness.FREE_MODEL)
    understand("Who attacked Mariupol?", llm=llm)
    assert inner.calls == 1


def test_estimate_is_zero_for_free_and_positive_for_paid():
    assert harness.estimate_understand_cost(27, 0.0, 0.0, 6000) == 0
    est = harness.estimate_understand_cost(27, 0.15e-6, 0.60e-6, 6000)
    assert 0.005 < est < 0.05   # gpt-4o-mini prices: a cent or two for the whole set


def test_free_models_need_no_price_lookup():
    assert harness.fetch_prices("openrouter/free") == (0.0, 0.0)
    assert harness.fetch_prices("some/model:free") == (0.0, 0.0)


def test_reports_trace_and_compare(tmp_path, monkeypatch, make_llm):
    monkeypatch.setattr(harness, "RESULTS_DIR", tmp_path / "results")
    _, llm = make_llm()
    plan = understand("Who attacked Mariupol?", llm=llm)
    results = [{"id": "v4", "text": "Who attacked Mariupol?", "seconds": 1.2,
                "inputs": {"map": "none", "history": "none"}, "plan": plan.model_dump(mode="json")}]
    meta = {"stage": "understand", "model_requested": "paid/model", "cost_cap_usd": 0.25, "started": "2026-10-20 16:00"}
    path_a = harness.write_report(results, meta, instructions={"understand": SYSTEM_PROMPT})

    table = path_a.with_suffix(".md").read_text(encoding="utf-8")
    assert "**Cost:** $0.0100" in table and "| v4 | Who attacked Mariupol? | llm | relation |" in table

    trace = Path(f"{path_a.with_suffix('')}_trace.md").read_text(encoding="utf-8")
    for expected in ["## v4 · Who attacked Mariupol?", "Instructions sent to the LLM for <b>understand</b>",
                     "Message sent:", "Question: Who attacked Mariupol?", "The LLM's raw answer, before any code rules:",
                     '"relations": [\n    "ATTACKED"', "**Plan handed to the next step:**", "- **type:** `relation`",
                     "### ② Resolve: names in the plan → graph nodes — *not run*"]:
        assert expected in trace, expected

    changed = json.loads(path_a.read_text(encoding="utf-8"))
    changed["results"][0]["plan"]["type"] = "place_lookup"
    path_b = tmp_path / "b.json"
    path_b.write_text(json.dumps(changed), encoding="utf-8")
    assert harness.compare(path_a, path_b) == ["v4 (Who attacked Mariupol?):\n    type: 'relation' -> 'place_lookup'"]


def test_trace_shows_the_resolve_step(tmp_path, monkeypatch, vr6_index):
    from resolver import resolve
    monkeypatch.setattr(harness, "RESULTS_DIR", tmp_path / "results")
    plan = understand("Where is Kiev?")                       # fast path
    street = understand("Where is Hrushevsky Street?")
    results = [{"id": qid, "text": p.question, "seconds": 0.1, "inputs": {},
                "plan": p.model_dump(mode="json"), "resolve": resolve(p, vr6_index).model_dump(mode="json")}
               for qid, p in [("a", plan), ("b", street)]]
    meta = {"stage": "understand+resolve", "model_requested": "x", "cost_cap_usd": 0.25, "started": "now",
            "graph": {"path": "g.json.gz", "load_seconds": 1, "index_seconds": 1, "nodes": 10, "groups": 5}}
    path = harness.write_report(results, meta, stage=meta["stage"], instructions={"understand": SYSTEM_PROMPT})
    trace = Path(f"{path.with_suffix('')}_trace.md").read_text(encoding="utf-8")
    assert "### ② Resolve: names in the plan → graph nodes\n" in trace
    assert "→ **found** `Kyiv` (LOC) · 25 paragraphs · also written: Kiev · by exact" in trace
    assert "**uncertain: geocoded as a road with importance 0.04**" in trace
    assert "### ③ Retrieve: route → tools → graph data — *not run*" in trace
    table = path.with_suffix(".md").read_text(encoding="utf-8")
    assert "Kiev → Kyiv (exact, 25 texts)" in table


def test_trace_shows_the_write_step(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "RESULTS_DIR", tmp_path / "results")
    plan = understand("Where is Kiev?")
    results = [{"id": "a", "text": "Where is Kiev?", "seconds": 0.1, "inputs": {}, "plan": plan.model_dump(mode="json"),
                "evidence": {"level": "L0+L1", "shape": "fact", "shape_reason": "where a place is", "llm_text": "QUESTION: …",
                             "places": [{"number": 1, "label": "Kyiv"}], "notes": [],
                             "amounts": {"places_found": 1, "entities_found": 0, "records_found": 0, "pointers": 0,
                                         "pointers_total": 0, "words_summaries": 10, "words_all_sentences": 0,
                                         "words_all_paragraphs": 0, "words_included": 10, "budget_words": 600}},
                "write": {"text": "Kyiv [1] is the capital [L1].", "status": "answered", "grounded": True,
                          "shape": "fact", "places_discussed": [1], "passages_cited": ["L1"], "follow_ups": ["More?"],
                          "removed_citations": ["[S9]"], "notes": [],
                          "llm_calls": [{"step": "write", "model": "m", "response": {"answer": "Kyiv [1] [S9]"}}]}}]
    meta = {"stage": "all", "model_requested": "m", "cost_cap_usd": 0.25, "started": "now"}
    path = harness.write_report(results, meta, stage="all", instructions={"understand": SYSTEM_PROMPT})
    trace = Path(f"{path.with_suffix('')}_trace.md").read_text(encoding="utf-8")
    for expected in ["### ⑤ Write: evidence → answer", "**Status:** answered · **grounded in the graph:** yes",
                     "removed citations that point at nothing: [S9]", "> Kyiv [1] is the capital [L1].",
                     "**Places discussed:** [1] Kyiv", "**Suggested follow-ups:** More?"]:
        assert expected in trace, expected
    assert "[answered] Kyiv [1] is the capital [L1]." in path.with_suffix(".md").read_text(encoding="utf-8")


def test_trace_shows_the_result_step(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "RESULTS_DIR", tmp_path / "results")
    plan = understand("Where is Kiev?")
    ring = [[30.2, 50.3], [30.8, 50.3], [30.8, 50.6], [30.2, 50.6], [30.2, 50.3]]
    result = {"answer": "Kyiv [1] is the capital [L1].", "status": "answered", "grounded": True, "shape": "fact",
              "geo_locations": [{"number": 1, "id": "Kyiv", "label": "Kyiv", "kind": "city", "role": "primary",
                                 "geometry": {"type": "Point", "coordinates": [30.52, 50.45]},
                                 "shape": {"type": "Polygon", "coordinates": [ring]}, "why": "capital",
                                 "sources": ["TEXT_1", "TEXT_2", "TEXT_3", "TEXT_4"]}],
              "regions": [{"id": "Ukraine", "level": "country", "count": 1, "places": [1], "children": []}],
              "citations": [{"id": "L1", "pointer": "TEXT_1", "article": "Kyiv", "spans": []}],
              "sources": ["TEXT_1"], "map": {"bbox": [30.1, 50.2, 30.9, 50.7], "highlight": [1]},
              "follow_ups": [], "did_you_mean": [{"id": "Kyiv Oblast", "type": "LOC"}], "notes": [],
              "meta": {"question_type": "place_lookup", "model": "m", "llm_calls": 1, "cost_usd": 0.0001, "seconds": 2.0}}
    results = [{"id": "a", "text": "Where is Kiev?", "seconds": 0.1, "inputs": {}, "plan": plan.model_dump(mode="json"),
                "result": result}]
    meta = {"stage": "all", "model_requested": "m", "cost_cap_usd": 0.25, "started": "now"}
    path = harness.write_report(results, meta, stage="all", instructions={"understand": SYSTEM_PROMPT})
    trace = Path(f"{path.with_suffix('')}_trace.md").read_text(encoding="utf-8")
    for expected in ["### ⑥ Result: the JSON the UI receives", "**Places:** 1 (1 primary, 1 with an outline)",
                     "| 1 | Kyiv | city | primary | [30.52, 50.45] | 5 | 4 | capital |",
                     "- Ukraine (country): 1 places", "[L1] TEXT_1 (Kyiv)", "**Did you mean:** Kyiv Oblast (LOC)",
                     '"shape": "<Polygon, 5 points>"', '"... 1 more"']:
        assert expected in trace, expected
    assert "1 places (1 outlined), 1 regions, 1 citations" in path.with_suffix(".md").read_text(encoding="utf-8")
    assert json.loads(Path(f"{path.with_suffix('')}_ui/a.json").read_text(encoding="utf-8")) == result   # as the UI gets it


def test_question_sets():
    assert [q["id"] for q in harness.load_questions()] == ["q1", "q3", "q10", "q11", "q12", "q13", "q14",
                                                        "q15", "z1", "z2"]
    assert harness.load_questions(["z2"])[0]["follows"] == "z1"
    assert [q["id"] for q in harness.load_questions(set_name="core4")] == ["q11", "q12", "q13", "q14"]
    assert len(harness.load_questions(set_name="all")) == 31
    qs = {q["id"]: q for q in harness.load_questions(["q14", "v9"])}   # explicit ids win over sets
    assert qs["q14"]["geo"]["type"] == "polygon" and qs["v9"]["history"][0]["response"]["geo_locations"]
    with pytest.raises(ValueError):
        harness.load_questions(set_name="nope")
