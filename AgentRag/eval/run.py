"""Run the agent's steps on the test questions.

    python eval/run.py flow                                # all built steps, focus7 set, the app's model
    python eval/run.py flow --set core4 --until resolve    # stop after: understand, resolve, retrieve, evidence, write, result
    python eval/run.py flow --budget 1500                  # word budget for the evidence step
    python eval/run.py flow q11 v4                         # explicit question ids
    python eval/run.py flow --model google/gemini-2.5-flash --max-cost 0.10
    python eval/run.py flow --reuse 8                      # reuse identical LLM answers from the last 8 hours
    python eval/run.py understand ...                      # shortcut for: flow --until understand
    python eval/run.py compare eval/results/A.json eval/results/B.json

Sets: focus (default), core4, focus7, zelenskyy_pair, project14, understand_stress, all. Uses your OpenRouter key from
AgentRag/.env; by default every run asks the LLM fresh. Each run writes to eval/results/: a JSON file,
a table report (.md), a trace report (_trace.md) that follows each question step by step, and a _ui
folder with each question's result exactly as the UI receives it.
--model is for comparing models only; the app always uses agent.MODEL. The steps run through
pipeline.run(), the same code georag_agent.query() runs.
"""
import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(HERE.parent / ".env")

import agent  # noqa: E402
import harness  # noqa: E402
import pipeline  # noqa: E402
from evidence import render_for_llm  # noqa: E402
from planner import SYSTEM_PROMPT, Area, summarize_history  # noqa: E402
from resolver import PICK_PROMPT  # noqa: E402
from writer import NO_DATA_PROMPT, WRITE_PROMPT  # noqa: E402

BUILT_STEPS = pipeline.STEPS


def describe_map(geo) -> str:
    if not geo:
        return "none"
    if geo["type"] == "point":
        return f"point {geo['coordinates']}" + (f", radius {geo['radius_m']} m" if geo.get("radius_m") else "")
    return f"polygon with {len(geo['coordinates'][0])} corners"


def previous_turn(prev: dict) -> dict:
    """A chat-history entry for a follow-up question: the previous question's result, as the UI would
    send it back. A run that stopped before step 6 falls back to the step-3 places."""
    if prev.get("result"):
        return {"query": prev["text"], "response": prev["result"]}
    places = prev.get("retrieve", {}).get("places", [])
    return {"query": prev["text"], "response": {"answer": "", "sources": [], "geo_locations": [
        {"number": i, "id": h["group"]["id"], "label": h["group"]["id"]} for i, h in enumerate(places, 1)]}}


def run_flow(args) -> None:
    until = BUILT_STEPS.index(args.until)
    questions = harness.load_questions(args.ids, args.set)
    model = args.model or agent.MODEL
    price_in, price_out = harness.fetch_prices(model)
    estimate = harness.estimate_understand_cost(len(questions), price_in, price_out, len(SYSTEM_PROMPT))
    if until >= 4:
        estimate += harness.estimate_write_cost(len(questions), price_in, price_out, len(WRITE_PROMPT), args.budget)
    print(f"model {model}: ${price_in * 1e6:.3f} / ${price_out * 1e6:.3f} per 1M tokens in/out; "
          f"{len(questions)} questions; steps: {', '.join(BUILT_STEPS[:until + 1])}; estimate at most "
          f"${estimate:.4f} (cap ${args.max_cost:.2f}); "
          + (f"reusing answers from the last {args.reuse:g} h" if args.reuse else "asking fresh"))
    if estimate > args.max_cost:
        sys.exit("estimate is over the cap: raise --max-cost or run fewer questions")

    meta = {"stage": "+".join(BUILT_STEPS[:until + 1]), "model_requested": model, "cost_cap_usd": args.max_cost,
            "question_set": args.set if not args.ids else "ids", "reuse_hours": args.reuse,
            "started": f"{datetime.now():%Y-%m-%d %H:%M}"}
    gi = None
    if until >= 1:
        from graph_index import GraphIndex
        print("loading the graph (once per run) ...")
        gi = GraphIndex.load()
        meta["graph"] = {"path": Path(gi.path).name, "load_seconds": gi.load_seconds, "index_seconds": gi.index_seconds,
                         "nodes": gi.G.number_of_nodes(), "groups": len(gi.groups), "dropped": gi.dropped}
        print(f"graph ready: loaded {gi.load_seconds} s + indexes {gi.index_seconds} s")

    ledger = harness.Ledger(args.max_cost)
    llm = harness.CachedLLM(agent.get_llm(model=model), model, ledger, reuse_hours=args.reuse)
    results = []
    for q in questions:
        geo = q["geo"]
        if q.get("follows"):   # a follow-up: the previous question's result becomes the chat history
            prev = next((x for x in results if x["id"] == q["follows"]), None)
            q["history"] = [previous_turn(prev)] if prev else []
        area = Area(kind=geo["type"], coordinates=geo["coordinates"]) if geo else None
        start = time.time()
        try:
            out = pipeline.run(q["text"], gi, llm, area=area, history=q["history"],
                               map_radius_m=geo.get("radius_m") if geo else None,
                               until=args.until, budget_words=args.budget)
            plan = out["plan"]
            r = {"id": q["id"], "text": q["text"],
                 "inputs": {"map": describe_map(geo), "history": summarize_history(q["history"])},
                 "plan": plan.model_dump(mode="json", exclude_none=True)}
            for key in ("resolve", "retrieve", "write", "result"):
                if key in out:
                    r[key] = out[key].model_dump(mode="json", exclude_none=True)
            if "evidence" in out:
                r["evidence"] = {**out["evidence"].model_dump(mode="json", exclude_none=True),
                                 "llm_text": render_for_llm(out["evidence"], plan.question)}
        except harness.CostCapExceeded as e:
            meta["stopped_early"] = f"before {q['id']}: {e}"
            print(f"STOPPED: {e}")
            break
        r["seconds"] = round(time.time() - start, 1)
        results.append(r)
        row = dict(zip(harness.COLUMNS, harness.plan_row(r)))
        print(f"{r['id']:4s} {row['source']:16s} {row['type']:13s} "
              f"{row['answer (⑤)'] or row['retrieved (③)'] or row['resolved (②)'] or row['names']}"[:150]
              + (f"  ⑥ {row['result (⑥)']}" if row["result (⑥)"] else "") + f"  {row['s']}s {row['$']}")
    instructions = {"understand": SYSTEM_PROMPT}
    if until >= 1:
        instructions["resolve (picking between candidates)"] = PICK_PROMPT
    if until >= 4:
        instructions["write"] = WRITE_PROMPT
        instructions["write (no graph data)"] = NO_DATA_PROMPT
    path = harness.write_report(results, meta, stage=meta["stage"], instructions=instructions)
    s = harness.summarize(results)
    print(f"\n{s['llm_calls']} LLM calls ({s['cached_calls']} reused), cost ${s['cost_usd']:.4f}, "
          f"answered by {s['answered_by']}")
    print(f"saved {path.relative_to(HERE.parent)}, the table report (.md) and the trace (_trace.md)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, default_until in [("flow", BUILT_STEPS[-1]), ("understand", "understand")]:
        p = sub.add_parser(name, help="run the agent's steps on the test questions")
        p.add_argument("ids", nargs="*", help="question ids (overrides --set)")
        p.add_argument("--set", default=harness.DEFAULT_SET, help=f"question set (default {harness.DEFAULT_SET})")
        p.add_argument("--until", default=default_until, choices=BUILT_STEPS, help="last step to run")
        p.add_argument("--model", help="compare a different model (the app always uses agent.MODEL)")
        p.add_argument("--max-cost", type=float, default=0.25, help="cost cap for this run, in USD (default 0.25)")
        p.add_argument("--budget", type=int, default=2000, help="word budget for step 4's evidence (default 2000)")
        p.add_argument("--reuse", type=float, metavar="HOURS",
                       help="reuse identical LLM answers saved within the last HOURS (default: always ask fresh)")
    c = sub.add_parser("compare", help="show which plans differ between two runs")
    c.add_argument("a")
    c.add_argument("b")
    args = parser.parse_args()
    if args.command in ("flow", "understand"):
        run_flow(args)
    else:
        lines = harness.compare(Path(args.a), Path(args.b))
        print("\n".join(lines) if lines else "no differences")


if __name__ == "__main__":
    main()
