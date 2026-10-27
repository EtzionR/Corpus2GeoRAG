"""Evaluation harness: run the agent's steps on the test questions, with a cost cap and reports.

- Saved answers: every LLM answer is saved under eval/cache/, keyed by model + structure + exact
  messages. By default a run always asks the LLM fresh. With a reuse window (`--reuse HOURS`), an
  identical call answered within that window is reused for free, e.g. while tuning a later step
  on the same questions during one working session (P2-32).
- Cost cap: a run refuses to start if its estimate is over the cap, and stops if real spending
  reaches it (partial results are still saved).
- Reports: each run writes a JSON file (for comparing), a table report (one row per question) and
  a trace report (each question followed step by step) to eval/results/.
"""
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from langchain_core.messages import AIMessage

from geo import count_points
from llm_calls import prompt_version   # the AgentRag folder is on the path (eval/run.py, tests/conftest.py)

HERE = Path(__file__).resolve().parent
CACHE_DIR = HERE / "cache"
RESULTS_DIR = HERE / "results"
FREE_MODEL = "openrouter/free"


class CostCapExceeded(RuntimeError):
    """The run has spent its cost cap; no more paid calls."""


class Ledger:
    def __init__(self, cap_usd: float):
        self.cap_usd, self.spent_usd, self.calls, self.cache_hits = cap_usd, 0.0, 0, 0


class CachedLLM:
    """Wraps a chat model: saves every answer, reuses one only inside the reuse window, records
    spend, enforces the cap. reuse_hours=None (the default) means always ask fresh."""

    def __init__(self, llm, model: str, ledger: Ledger, cache_dir: Path = CACHE_DIR,
                 reuse_hours: Optional[float] = None):
        self.llm, self.model, self.ledger, self.cache_dir = llm, model, ledger, cache_dir
        self.reuse_hours = reuse_hours

    def with_structured_output(self, schema, **kwargs):
        return _CachedStructured(self, schema, kwargs)


class _CachedStructured:
    def __init__(self, owner: CachedLLM, schema, kwargs: dict):
        self.owner, self.schema, self.kwargs = owner, schema, kwargs

    def _key(self, messages) -> str:
        blob = json.dumps({"model": self.owner.model, "schema": self.schema.model_json_schema(),
                           "kwargs": sorted((k, str(v)) for k, v in self.kwargs.items()),
                           "messages": [list(m) if isinstance(m, tuple) else str(m) for m in messages]},
                          sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]

    def _fresh_saved(self, path: Path) -> Optional[dict]:
        if self.owner.reuse_hours is None or not path.exists():
            return None
        saved = json.loads(path.read_text(encoding="utf-8"))
        age = datetime.now() - datetime.fromisoformat(saved["saved_at"])
        return saved if age <= timedelta(hours=self.owner.reuse_hours) else None

    def invoke(self, messages):
        owner = self.owner
        path = owner.cache_dir / f"{self._key(messages)}.json"
        saved = self._fresh_saved(path)
        if saved is not None:
            owner.ledger.cache_hits += 1
            raw = AIMessage(content=saved["raw"]["content"], tool_calls=saved["raw"].get("tool_calls", []),
                            response_metadata={**saved["raw"]["response_metadata"], "cached": True},
                            usage_metadata=saved["raw"]["usage_metadata"])
            return {"raw": raw, "parsed": self.schema.model_validate(saved["parsed"]), "parsing_error": None}

        if owner.ledger.spent_usd >= owner.ledger.cap_usd and owner.model != FREE_MODEL:
            raise CostCapExceeded(f"cost cap ${owner.ledger.cap_usd:.2f} reached "
                                  f"(spent ${owner.ledger.spent_usd:.4f})")
        result = owner.llm.with_structured_output(self.schema, **self.kwargs).invoke(messages)
        raw, parsed = result.get("raw"), result.get("parsed")
        meta = getattr(raw, "response_metadata", None) or {}
        owner.ledger.calls += 1
        owner.ledger.spent_usd += float((meta.get("token_usage") or {}).get("cost") or 0.0)
        if parsed is not None:   # always save (reuse is decided per run); never save a failure
            owner.cache_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({
                "saved_at": datetime.now().isoformat(timespec="seconds"), "model": owner.model,
                "raw": {"content": raw.content, "response_metadata": meta,
                        "tool_calls": [{"name": t["name"], "args": t["args"], "id": t.get("id")}
                                       for t in (getattr(raw, "tool_calls", None) or [])],
                        "usage_metadata": dict(getattr(raw, "usage_metadata", None) or {})},
                "parsed": parsed.model_dump(mode="json")}, ensure_ascii=False, indent=1, default=str),
                encoding="utf-8")
        return result


# --- Questions -------------------------------------------------------------------------------

DEFAULT_SET = "focus"    # P2-4 + q15 and the Zelenskyy follow-up pair (z1, z2)


def load_questions(ids: Optional[list[str]] = None, set_name: Optional[str] = None) -> list[dict]:
    """The test questions, with fixtures (map selections, chat history) filled in. Explicit ids
    win; otherwise a named set from questions.json ("all" for everything; default focus7)."""
    spec = json.loads((HERE / "questions.json").read_text(encoding="utf-8"))
    fixtures = spec["fixtures"]
    if not ids:
        set_name = set_name or DEFAULT_SET
        if set_name != "all" and set_name not in spec["sets"]:
            raise ValueError(f"unknown question set {set_name!r}; sets: all, {', '.join(spec['sets'])}")
        ids = None if set_name == "all" else spec["sets"][set_name]
    out = []
    for q in spec["questions"]:
        if ids and q["id"] not in ids:
            continue
        geo = fixtures[q["geo_location"]] if q.get("geo_location") else None
        out.append({**q, "geo": geo, "history": fixtures[q["chat_history"]] if q.get("chat_history") else []})
    return out


# --- Cost estimate ---------------------------------------------------------------------------

def estimate_understand_cost(n_questions: int, price_in: float, price_out: float, prompt_chars: int) -> float:
    """A cautious upper estimate: every question goes to the LLM, about 4 characters per token,
    300 output tokens, and one retry for one question in five."""
    tokens_in = prompt_chars / 4 + 150
    calls = n_questions * 1.2
    return calls * (tokens_in * price_in + 300 * price_out)


def estimate_write_cost(n_questions: int, price_in: float, price_out: float, prompt_chars: int,
                        budget_words: int) -> float:
    """A cautious upper estimate for step 5: every answer reads a full budget (about 1.3 tokens per
    word) plus the instructions, and writes 500 tokens."""
    tokens_in = prompt_chars / 4 + budget_words * 1.3 + 300
    return n_questions * (tokens_in * price_in + 500 * price_out)


def fetch_prices(model: str) -> tuple[float, float]:
    """USD per token (input, output) from OpenRouter's public model list; no key needed."""
    if model == FREE_MODEL or model.endswith(":free"):
        return 0.0, 0.0
    import httpx
    for m in httpx.get("https://openrouter.ai/api/v1/models", timeout=30).json()["data"]:
        if m["id"] == model:
            return float(m["pricing"]["prompt"]), float(m["pricing"]["completion"])
    raise ValueError(f"model {model!r} is not on OpenRouter's model list")


# --- Reports ---------------------------------------------------------------------------------

def all_calls(r: dict) -> list[dict]:
    """Every LLM call made for one question, across the steps that ran."""
    return (list(r["plan"].get("llm_calls", [])) + list(r.get("resolve", {}).get("llm_calls", []))
            + list(r.get("write", {}).get("llm_calls", [])))


def summarize(results: list[dict]) -> dict:
    calls = [c for r in results for c in all_calls(r)]
    answered_by: dict[str, int] = {}
    for c in calls:
        answered_by[c.get("model") or "?"] = answered_by.get(c.get("model") or "?", 0) + 1
    llm_seconds = [r["seconds"] for r in results if all_calls(r)]
    sources: dict[str, int] = {}
    for r in results:
        sources[r["plan"]["source"]] = sources.get(r["plan"]["source"], 0) + 1
    return {
        "questions": len(results), "llm_calls": len(calls),
        "cached_calls": sum(1 for c in calls if c.get("cached")),
        "failed_calls": sum(1 for c in calls if not c.get("ok", True)),
        "cost_usd": round(sum(c.get("cost_usd", 0) for c in calls), 6),
        "tokens_in": sum(c.get("input_tokens", 0) for c in calls),
        "tokens_out": sum(c.get("output_tokens", 0) for c in calls),
        "answered_by": answered_by, "plan_sources": sources,
        "avg_seconds_llm_questions": round(sum(llm_seconds) / len(llm_seconds), 1) if llm_seconds else 0,
        "max_seconds": max((r["seconds"] for r in results), default=0),
    }


def _cell(value) -> str:
    return str(value).replace("|", "/").replace("\n", " ") if value not in (None, "", []) else ""


def plan_row(r: dict) -> list[str]:
    p = r["plan"]
    names = "; ".join(f"{e['name']} ({e['kind']})" + (f" [typed {e['text']!r}]" if e["text"] != e["name"] else "")
                      for e in p.get("entities", []))
    concepts = "; ".join(f"{c['text']} -> {', '.join(x['name'] for x in c.get('candidates', [])) or '-'}"
                         for c in p.get("concepts", []))
    area = p["area"]["kind"] if p.get("area") else ""
    if p.get("radius_m"):
        area += f" {p['radius_m']:g} m ({p.get('radius_source')})"
    place = " ".join(x for x in [p.get("place_country") or "", ",".join(p.get("place_kinds", []))] if x)
    follow = ""
    if p.get("follow_up"):
        follow = f"{p['follow_up']['kind']} {p['follow_up'].get('target_label') or ''}".strip()
    calls = all_calls(r)
    models = ", ".join(sorted({c.get("model") or "?" for c in calls}))
    cost = sum(c.get("cost_usd", 0) for c in calls)
    cached = calls and all(c.get("cached") for c in calls)
    return [r["id"], r["text"], p["source"], p["type"], names, concepts, ",".join(p.get("relations", [])),
            ",".join(p.get("keywords", [])), area, place, follow, p.get("needs"), " | ".join(p.get("notes", [])),
            _resolved_cell(r.get("resolve")), _retrieved_cell(r.get("retrieve")), _answer_cell(r.get("write")),
            _result_cell(r.get("result")), models + (" (cached)" if cached else ""), f"{r['seconds']:.1f}", f"{cost:.5f}" if cost else ""]


def _answer_cell(ans: Optional[dict]) -> str:
    if not ans:
        return ""
    text = ans["text"] if len(ans["text"]) <= 160 else ans["text"][:157] + "…"
    return f"[{ans['status']}] {text}"


def _json_kb(value) -> float:
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8")) / 1024


def _result_cell(res: Optional[dict]) -> str:
    if not res:
        return ""
    places = res.get("geo_locations", [])
    outlines = sum(1 for g in places if g.get("shape"))
    return (f"{len(places)} places ({outlines} outlined), {len(res.get('regions', []))} regions, "
            f"{len(res.get('citations', []))} citations, {_json_kb(res):.0f} KB")


def _retrieved_cell(ret: Optional[dict]) -> str:
    if not ret:
        return ""
    route = ret["route"].split(":")[0]
    parts = [f"{len(ret.get(k, []))} {k}" for k in ("places", "entities", "records") if ret.get(k)]
    top = ", ".join(h["group"]["id"] for h in (ret.get("places") or ret.get("entities") or [])[:3])
    return f"{route}: {', '.join(parts) or 'nothing found'}" + (f" (top: {top})" if top else "")


def _resolved_cell(res: Optional[dict]) -> str:
    if not res:
        return ""
    parts = []
    for e in res.get("entities", []):
        if e["status"] != "resolved":
            parts.append(f"{e['text']} → not found")
        elif e.get("article"):
            parts.append(f"{e['text']} → article {e['article']['title']!r}")
        else:
            parts.append(f"{e['text']} → {e['group']['id']} ({e['how']}, {e['group']['texts']} texts)")
    for c in res.get("concepts", []):
        found = [x["name"] for x in c.get("candidates", []) if x["status"] == "resolved"]
        parts.append(f"{c['text']}: {', '.join(found) or 'no candidate in graph'}")
    return "; ".join(parts)


COLUMNS = ["id", "question", "source", "type", "names", "concepts", "relations", "keywords", "area / radius",
           "place filter", "follow-up", "needs", "notes", "resolved (②)", "retrieved (③)", "answer (⑤)",
           "result (⑥)", "model", "s", "$"]


def write_report(results: list[dict], meta: dict, stage: str = "understand",
                 instructions: Optional[dict] = None) -> Path:
    """Save <date>_<time with seconds>_<stage>_<model>.json (everything, every step), .md (table),
    _trace.md (step by step, when the LLM instructions are given) and, once step 6 ran, a _ui folder
    with each question's result exactly as query() returns it, under eval/results/. Returns the
    JSON path."""
    RESULTS_DIR.mkdir(exist_ok=True)
    # no dots in the name: "gemini-2.5-flash" would otherwise be read as a file extension
    slug = meta["model_requested"].replace("/", "-").replace(":", "-").replace(".", "-")
    base = RESULTS_DIR / f"{datetime.now():%Y-%m-%d_%H%M%S}_{stage}_{slug}"
    summary = summarize(results)
    base.with_suffix(".json").write_text(
        json.dumps({**meta, "summary": summary, "results": results}, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = [f"# {stage} run, {meta['started']}", "",
             f"- **Model requested:** `{meta['model_requested']}`; answered by: "
             + ", ".join(f"`{m}` ({n})" for m, n in summary["answered_by"].items()),
             f"- **Questions:** {summary['questions']}; plans from: "
             + ", ".join(f"{k} {v}" for k, v in summary["plan_sources"].items()),
             f"- **LLM calls:** {summary['llm_calls']} ({summary['cached_calls']} from cache, "
             f"{summary['failed_calls']} without a usable answer); tokens in {summary['tokens_in']:,}, "
             f"out {summary['tokens_out']:,}",
             f"- **Cost:** ${summary['cost_usd']:.4f} (cap ${meta['cost_cap_usd']:.2f})",
             f"- **Time:** {summary['avg_seconds_llm_questions']} s on average for questions that needed the LLM; "
             f"slowest {summary['max_seconds']:.1f} s"]
    if meta.get("stopped_early"):
        lines.append(f"- **Stopped early:** {meta['stopped_early']}")
    if any("evidence" in r for r in results):
        lines += ["", "## Amounts of text per question (step ④)", "",
                  "| id | question | " + " | ".join(AMOUNT_COLUMNS) + " |", "|---|---|" + "---|" * len(AMOUNT_COLUMNS)]
        lines += [f"| {r['id']} | {_cell(r['text'])} | " + " | ".join(_amount_cells(r["evidence"])) + " |"
                  for r in results if "evidence" in r]
        lines += ["", "## Plans and results per question"]
    lines += ["", "| " + " | ".join(COLUMNS) + " |", "|" + "---|" * len(COLUMNS)]
    lines += ["| " + " | ".join(_cell(v) for v in plan_row(r)) + " |" for r in results]
    base.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if instructions:
        Path(f"{base}_trace.md").write_text(render_trace(results, meta, summary, instructions), encoding="utf-8")
    if any("result" in r for r in results):
        ui = Path(f"{base}_ui")
        ui.mkdir(exist_ok=True)
        for r in results:
            if "result" in r:
                (ui / f"{r['id']}.json").write_text(json.dumps(r["result"], indent=2, ensure_ascii=False),
                                                    encoding="utf-8")
    return base.with_suffix(".json")


# --- Trace report: each question followed step by step ---------------------------------------

STEPS = [
    ("understand", "①", "Understand", "question → plan"),
    ("resolve", "②", "Resolve", "names in the plan → graph nodes"),
    ("retrieve", "③", "Retrieve", "route → tools → graph data"),
    ("evidence", "④", "Evidence", "graph data → the text the LLM will read"),
    ("write", "⑤", "Write", "evidence → answer"),
    ("result", "⑥", "Result", "the JSON the UI receives"),
]


def _fence(text: str, lang: str = "") -> list[str]:
    return [f"```{lang}", text.rstrip(), "```"]


def _plan_lines(p: dict) -> list[str]:
    def names(es):
        return "; ".join(f"{e['name']} ({e['kind']})" + (f" — typed {e['text']!r}" if e["text"] != e["name"] else "")
                         for e in es) or "—"
    concepts = "; ".join(f"{c['text']} → {', '.join(x['name'] + ' (' + x['kind'] + ')' for x in c.get('candidates', [])) or 'no candidates'}"
                         for c in p.get("concepts", [])) or "—"
    area = (f"{p['area']['kind']} from the map" if p.get("area") else "—")
    if p.get("radius_m"):
        area += f", radius {p['radius_m']:g} m ({p.get('radius_source')})"
    place = " ".join(x for x in [p.get("place_country") or "", ", ".join(p.get("place_kinds", []))] if x) or "—"
    follow = "—"
    if p.get("follow_up"):
        f = p["follow_up"]
        follow = f["kind"] + (f" → item {f.get('item_number')}: {f.get('target_label')} (id {f.get('target_id')})"
                              if f.get("target_id") else "")
    return [f"- **type:** `{p['type']}`  ·  **in scope:** {p.get('in_scope', True)}  ·  **needs:** {p.get('needs')}",
            f"- **names:** {names(p.get('entities', []))}",
            f"- **concepts:** {concepts}",
            f"- **relations:** {', '.join(p.get('relations', [])) or '—'}  ·  **keywords:** {', '.join(p.get('keywords', [])) or '—'}",
            f"- **area:** {area}  ·  **place filter:** {place}",
            f"- **time words:** {', '.join(p.get('time_words', [])) or '—'}  ·  **follow-up:** {follow}"]


def _understand_section(p: dict) -> list[str]:
    calls = p.get("llm_calls", [])
    if p["source"] == "fast_path":
        out = ["**Path:** fast path: code recognized the pattern; no LLM call."]
    elif p["source"] == "keyword_fallback":
        out = ["**Path:** keyword fallback: " + next((n for n in p.get("notes", []) if n.startswith("keyword fallback")),
                                                     "the LLM wasn't available")]
    else:
        out = ["**Path:** one LLM call (after the instructions at the top of this report)."]
    for i, c in enumerate(calls, 1):
        label = f"Attempt {i}" if len(calls) > 1 else "LLM call"
        out += ["", f"**{label}:** model `{c.get('model')}` · {c.get('input_tokens', 0):,} tokens in / "
                    f"{c.get('output_tokens', 0):,} out · {c.get('seconds', 0):.1f} s · ${c.get('cost_usd', 0):.5f}"
                    + (" · reused saved answer" if c.get("cached") else "")
                    + ("" if c.get("ok", True) else " · **no usable answer**")]
        if i == 1 and c.get("request"):
            out += ["", "Message sent:"] + _fence(c["request"], "text")
        if c.get("response") is not None:
            out += ["", "The LLM's raw answer, before any code rules:"] + _fence(
                json.dumps(c["response"], indent=2, ensure_ascii=False), "json")
    rules = [n for n in p.get("notes", []) if not n.startswith("keyword fallback")]
    out += ["", "**Rules code applied:** " + ("none" if not rules else ""), *[f"- {n}" for n in rules]]
    out += ["", "**Plan handed to the next step:**", *_plan_lines(p)]
    return out


def _group_line(g: dict) -> str:
    spellings = g["names"][1:6]
    more = f" (+{len(g['names']) - 6} more)" if len(g["names"]) > 6 else ""
    return (f"`{g['id']}` ({g['type']}) · {g['texts']:,} paragraphs · "
            + (f"also written: {', '.join(spellings)}{more}" if spellings else "one spelling"))


def _resolve_section(res: dict) -> list[str]:
    out = []
    entities, concepts = res.get("entities", []), res.get("concepts", [])
    if not entities and not concepts:
        out.append("Nothing to resolve: the plan names no person, organization, place or event "
                   "(the next step works from the map selection or the keywords).")
    for e in entities:
        typed = f"**{e['text']}**" + (f" (plan spelling {e['name']!r})" if e["name"] != e["text"] else "")
        if e["status"] != "resolved":
            out.append(f"- {typed} [{e['kind']}] → **not found** in the graph")
            continue
        if e.get("article"):
            a = e["article"]
            out.append(f"- {typed} [{e['kind']}] → **article** \"{a['title']}\" ({a['paragraphs']} paragraphs) · "
                       f"by {e['how']}")
            if a.get("lead_sentence"):
                out.append(f"  - first sentence: *{a['lead_sentence']}*")
            continue
        g = e["group"]
        picked = "" if e["picked_by"] == "only match" else f" · picked: {e['picked_by']}"
        out.append(f"- {typed} [{e['kind']}] → **found** {_group_line(g)} · by {e['how']}{picked}")
        if g.get("place"):
            p = g["place"]
            out.append(f"  - place: {p.get('place_type')} · importance {p.get('importance') or 0:.2f} · "
                       f"[lon, lat] [{p['lon']}, {p['lat']}] · {p.get('address') or ''}"
                       + (f" · **uncertain: {p['uncertain_reason']}**" if p.get("uncertain") else ""))
        if g.get("own_article"):
            out.append(f"  - has its own article: \"{g['own_article']}\"")
        for alt in e.get("alternatives", []):
            out.append(f"  - did you mean: {_group_line(alt)}")
    if concepts:
        out += ["", "**Concepts** (the LLM's candidate organizations and places, checked against the graph; "
                    "firm matches only):"]
        for c in concepts:
            cands = [f"{x['name']} → " + (f"found {x['group']['id']} ({x['group']['texts']:,} paragraphs)"
                                          if x["status"] == "resolved" and x.get("group") else "not in the graph")
                     for x in c.get("candidates", [])]
            out.append(f"- \"{c['text']}\": " + ("; ".join(cands) if cands else "no candidates"))
    for c in res.get("llm_calls", []):
        out.append(f"- LLM pick: model `{c.get('model')}` · {c.get('input_tokens', 0):,} tokens in · "
                   f"answer {json.dumps(c.get('response'), ensure_ascii=False)}")
    if res.get("notes"):
        out += ["", "**Notes:**", *[f"- {n}" for n in res["notes"]]]
    out.append(f"\n*{res.get('seconds', 0):.2f} s*")
    return out


TOP_N = 10


def _hit_row(i: int, h: dict) -> str:
    g = h["group"]
    kind = (g.get("place") or {}).get("place_type") or g["type"]
    rels = ", ".join(f"{k} {v}" for k, v in h.get("relations", {}).items())
    dist = f"{h['distance_m']:,.0f} m" if h.get("distance_m") is not None else ""
    ptrs = h.get("pointers", [])
    ptr_cell = ", ".join(f"TEXT_{p['text_id']}" for p in ptrs[:3]) + (f" … ({h.get('pointers_total', len(ptrs))})"
                                                                     if h.get("pointers_total", len(ptrs)) > 3 else "")
    flag = " ⚠ uncertain point" if (g.get("place") or {}).get("uncertain") else ""
    role = f" · {h['role']}" if h.get("role") else ""
    return (f"| {i} | {g['id']}{flag} | {kind} | {h.get('records', 0):,} | {rels}{role} | {dist} | "
            f"{g['texts']:,} | {ptr_cell} |")


def _retrieve_section(ret: dict) -> list[str]:
    out = [f"**Route:** {ret['route']}", "", "**Tools called** (graph traversal by code, no LLM):"]
    for i, s in enumerate(ret.get("steps", []), 1):
        params = "; ".join(f"{k}: {v}" for k, v in s.get("params", {}).items())
        out.append(f"{i}. `{s['tool']}`({params}) → {s['found']}" + (f" · {s['seconds']:.2f} s" if s.get("seconds") else ""))
    if not ret.get("steps"):
        out.append("- none")
    if ret.get("area_used"):
        out += ["", f"**Area searched:** {ret['area_used']}"]
    header = ["| # | name | kind | backed by | relations | distance | texts overall | pointers |",
              "|---|---|---|---|---|---|---|---|"]
    for key, title in [("places", "Places found (all of them go on the map)"),
                       ("entities", "People and organizations found")]:
        items = ret.get(key, [])
        if items:
            shown = min(TOP_N, len(items))
            out += ["", f"**{title}:** {len(items):,}" + (f", top {shown} shown" if len(items) > shown else ""), ""]
            out += header + [_hit_row(i, h) for i, h in enumerate(items[:shown], 1)]
    recs = ret.get("records", [])
    if recs:
        out += ["", f"**Relation records:** {len(recs):,}" + (f", top {TOP_N} shown" if len(recs) > TOP_N else "")]
        for r in recs[:TOP_N]:
            conf = f"{r['confidence']:.2f}" if r.get("confidence") is not None else "—"
            out.append(f"- {r.get('subject') or r['other']} **{r['relation']}** "
                       f"{r['target'] if r.get('subject') != r['target'] else r['other']} · confidence {conf} · "
                       f"TEXT_{r['pointer']['text_id']}")
    if ret.get("summaries"):
        out += ["", "**Summary paragraphs to read** (each article's first paragraph):"]
        out += [f"- \"{s['article']}\" (TEXT_{s['pointer']['text_id']}): *{s.get('preview', '')}*" for s in ret["summaries"]]
    if ret.get("notes"):
        out += ["", "**Notes:**", *[f"- {n}" for n in ret["notes"]]]
    out.append(f"\n*{ret.get('seconds', 0):.2f} s*")
    return out


AMOUNT_COLUMNS = ["shape", "places found", "entities found", "records", "pointers (available / total)",
                  "words: summaries", "words: all sentences", "words: all paragraphs", "words included", "level"]


def _amount_cells(ev: dict) -> list[str]:
    a = ev["amounts"]
    return [ev.get("shape", ""), f"{a['places_found']:,}", f"{a['entities_found']:,}", f"{a['records_found']:,}",
            f"{a['pointers']:,} / {a['pointers_total']:,}", f"{a['words_summaries']:,}",
            f"{a['words_all_sentences']:,}", f"{a['words_all_paragraphs']:,}",
            f"{a['words_included']:,} of {a['budget_words']:,}", ev["level"].split(":")[0]]


def _evidence_section(ev: dict) -> list[str]:
    out = [f"**Answer shape:** {ev.get('shape')} ({ev.get('shape_reason', '')}) · **level:** {ev['level']}", "",
           "**Amounts** (what this question could feed the LLM at each level):", "",
           "| " + " | ".join(AMOUNT_COLUMNS) + " |", "|" + "---|" * len(AMOUNT_COLUMNS),
           "| " + " | ".join(_amount_cells(ev)) + " |", ""]
    if ev.get("notes"):
        out += [f"- {n}" for n in ev["notes"]] + [""]
    out += ["**The text the LLM will read in step ⑤:**"] + _fence(ev.get("llm_text", ""), "text")
    return out


def _write_section(ans: dict, ev: Optional[dict]) -> list[str]:
    labels = {p["number"]: p["label"] for p in (ev or {}).get("places", [])}
    out = [f"**Status:** {ans['status']} · **grounded in the graph:** {'yes' if ans['grounded'] else 'no'} · "
           f"**shape:** {ans['shape']}", ""]
    for c in ans.get("llm_calls", []):
        out += [f"**LLM call:** model `{c.get('model')}` · {c.get('input_tokens', 0):,} tokens in / "
                f"{c.get('output_tokens', 0):,} out · {c.get('seconds', 0):.1f} s · ${c.get('cost_usd', 0):.5f}"
                + (" · reused saved answer" if c.get("cached") else ""),
                "", "Message sent: the text shown in step ④ above." if ans["grounded"] else "Message sent:"]
        if not ans["grounded"] and c.get("request"):
            out += _fence(c["request"], "text")
        if c.get("response") is not None:
            out += ["", "The LLM's raw answer, before the citation check:"] + _fence(
                json.dumps(c["response"], indent=2, ensure_ascii=False), "json")
    checks = ([f"removed citations that point at nothing: {' '.join(ans['removed_citations'])}"]
              if ans.get("removed_citations") else []) + list(ans.get("notes", []))
    out += ["", "**Checks by code:** " + ("all citations point at real material" if not checks else ""),
            *[f"- {c}" for c in checks]]
    out += ["", "**Answer:**", "", *[f"> {line}" for line in ans["text"].splitlines() or [""]], ""]
    if ans.get("places_discussed"):
        out.append("**Places discussed:** " + ", ".join(f"[{n}] {labels.get(n, '?')}" for n in ans["places_discussed"]))
    if ans.get("passages_cited"):
        out.append("**Passages cited:** " + ", ".join(ans["passages_cited"]))
    if ans.get("follow_ups"):
        out.append("**Suggested follow-ups:** " + " · ".join(ans["follow_ups"]))
    return out


RESULT_PLACES_SHOWN = 15


def _short_shapes(res: dict) -> dict:
    """The result with each outline replaced by its size, and long lists cut, for reading."""
    def shrink(g):
        if g.get("shape"):
            g = {**g, "shape": f"<{g['shape']['type']}, {count_points(g['shape'])} points>"}
        return {**g, "sources": g["sources"][:3] + ([f"... {len(g['sources']) - 3} more"] if len(g["sources"]) > 3 else [])}             if g.get("sources") else g
    out = {**res, "geo_locations": [shrink(g) for g in res.get("geo_locations", [])[:5]]}
    if len(res.get("geo_locations", [])) > 5:
        out["geo_locations"].append(f"... {len(res['geo_locations']) - 5} more places")
    if len(res.get("citations", [])) > 3:
        out["citations"] = res["citations"][:3] + [f"... {len(res['citations']) - 3} more citations"]
    if len(res.get("regions", [])) > 3:
        out["regions"] = res["regions"][:3] + [f"... {len(res['regions']) - 3} more regions"]
    return out


def _region_lines(nodes: list[dict], depth: int = 0) -> list[str]:
    out = []
    for n in nodes:
        out.append("  " * depth + f"- {n['id']} ({n.get('level', '?')}): {n.get('count', 0)} places")
        out += _region_lines(n.get("children", []), depth + 1)
    return out


def _result_section(res: dict) -> list[str]:
    places = res.get("geo_locations", [])
    primary = [g for g in places if g["role"] == "primary"]
    m, meta = res.get("map", {}), res.get("meta", {})
    out = [f"**Status:** {res['status']} · **grounded:** {'yes' if res['grounded'] else 'no'} · "
           f"**shape:** {res['shape']} · **size:** {_json_kb(res):.0f} KB "
           f"(outlines {sum(_json_kb(g['shape']) for g in places if g.get('shape')):.0f} KB)", "",
           f"**Places:** {len(places)} ({len(primary)} primary, {sum(1 for g in places if g.get('shape'))} with an "
           f"outline) · **regions:** {len(res.get('regions', []))} top level · **citations:** "
           f"{len(res.get('citations', []))} · **sources:** {len(res.get('sources', []))} · **entities:** "
           f"{len(res.get('entities', []))}", "",
           f"**Map:** zoom to {m.get('bbox')} · highlight {m.get('highlight', [])} · **meta:** "
           f"{meta.get('question_type')}, {meta.get('llm_calls')} LLM calls, ${meta.get('cost_usd', 0):.5f}, "
           f"{meta.get('seconds')} s, model `{meta.get('model')}`", ""]
    if places:
        out += ["| # | place | kind | role | point [lon, lat] | outline points | sources | why |",
                "|---|---|---|---|---|---|---|---|"]
        for g in places[:RESULT_PLACES_SHOWN]:
            pts = count_points(g["shape"]) if g.get("shape") else ""
            out.append(f"| {g['number']} | {_cell(g['label'])} | {g['kind']} | {g['role']} | "
                       f"{g['geometry']['coordinates']} | {pts} | {len(g.get('sources', []))} | "
                       f"{_cell(g.get('why'))}{' · uncertain: ' + _cell(g['uncertain']) if g.get('uncertain') else ''} |")
        if len(places) > RESULT_PLACES_SHOWN:
            out.append(f"| ... | {len(places) - RESULT_PLACES_SHOWN} more | | | | | | |")
        out.append("")
    if res.get("regions"):
        out += ["**Regions** (as the UI can show them):", ""] + _region_lines(res["regions"])[:25] + [""]
    if res.get("citations"):
        out += ["**Citations:** " + " · ".join(f"[{c['id']}] {c['pointer']} ({_cell(c['article'])}"
                                              + (f" / {_cell(c['section'])}" if c.get("section") else "") + ")"
                                              for c in res["citations"]), ""]
    if res.get("did_you_mean"):
        out += ["**Did you mean:** " + ", ".join(f"{a['id']} ({a['type']})" for a in res["did_you_mean"]), ""]
    out += ["<details><summary>The result JSON (outlines shown as their size, long lists cut)</summary>", ""]
    out += _fence(json.dumps(_short_shapes(res), indent=2, ensure_ascii=False), "json") + ["", "</details>"]
    return out


def render_trace(results: list[dict], meta: dict, summary: dict, instructions: dict) -> str:
    lines = [f"# Trace: {meta['stage']} run, {meta['started']}", "",
             f"Model requested `{meta['model_requested']}` · {summary['questions']} questions · "
             f"{summary['llm_calls']} LLM calls · ${summary['cost_usd']:.4f}", ""]
    if meta.get("graph"):
        g = meta["graph"]
        lines += [f"Graph: `{g['path']}` · loaded in {g['load_seconds']} s, indexes built in {g['index_seconds']} s "
                  f"(once per app start) · {g['nodes']:,} nodes · {g['groups']:,} name groups"
                  + (f" · reference sections dropped: {g['dropped']['paragraphs']:,} paragraphs, "
                     f"{g['dropped']['records']:,} records, {g['dropped']['entities']:,} entities"
                     if g.get("dropped") else ""), ""]
    lines += ["Each question is followed through the agent's steps. Steps this run stopped before are marked so. "
              "Step ⑥ shows the result in short; the full JSON the UI receives for each question is in the "
              "`_ui` folder next to this file.", ""]
    for step, text in instructions.items():
        lines += [f"<details><summary>Instructions sent to the LLM for <b>{step}</b> "
                  f"(prompt version {prompt_version(text)})</summary>", ""] + _fence(text, "text") + ["", "</details>", ""]
    for r in results:
        inputs = r.get("inputs", {})
        lines += ["---", "", f"## {r['id']} · {r['text']}", "",
                  f"**Inputs:** map selection: {inputs.get('map', 'none')} · chat history: "
                  f"{inputs.get('history', 'none')}", ""]
        for key, num, name, what in STEPS:
            if key == "understand":
                lines += [f"### {num} {name}: {what}", ""] + _understand_section(r["plan"]) + [""]
            elif key == "resolve" and "resolve" in r:
                lines += [f"### {num} {name}: {what}", ""] + _resolve_section(r["resolve"]) + [""]
            elif key == "retrieve" and "retrieve" in r:
                lines += [f"### {num} {name}: {what}", ""] + _retrieve_section(r["retrieve"]) + [""]
            elif key == "evidence" and "evidence" in r:
                lines += [f"### {num} {name}: {what}", ""] + _evidence_section(r["evidence"]) + [""]
            elif key == "write" and "write" in r:
                lines += [f"### {num} {name}: {what}", ""] + _write_section(r["write"], r.get("evidence")) + [""]
            elif key == "result" and "result" in r:
                lines += [f"### {num} {name}: {what}", ""] + _result_section(r["result"]) + [""]
            else:
                lines += [f"### {num} {name}: {what} — *not run*", ""]
    return "\n".join(lines) + "\n"


# --- Comparing two runs ----------------------------------------------------------------------

COMPARED = ["type", "source", "entities", "concepts", "relations", "keywords", "area", "radius_m",
            "place_country", "place_kinds", "needs", "follow_up"]


def _comparable(plan: dict, field: str):
    value = plan.get(field)
    if field == "entities":
        return sorted(f"{e['name']} ({e['kind']})" for e in value or [])
    if field == "concepts":
        return sorted(f"{c['text']}: {sorted(x['name'] for x in c.get('candidates', []))}" for c in value or [])
    if field == "area":
        return value["kind"] if value else None
    if field == "follow_up":
        return f"{value['kind']} {value.get('target_label')}" if value else None
    if isinstance(value, list):
        return sorted(value)
    return value


def compare(path_a: Path, path_b: Path) -> list[str]:
    """Lines describing every question whose plan differs between two runs."""
    a = {r["id"]: r for r in json.loads(Path(path_a).read_text(encoding="utf-8"))["results"]}
    b = {r["id"]: r for r in json.loads(Path(path_b).read_text(encoding="utf-8"))["results"]}
    lines = []
    for qid in [q for q in a if q in b]:
        diffs = [f"{f}: {_comparable(a[qid]['plan'], f)!r} -> {_comparable(b[qid]['plan'], f)!r}"
                 for f in COMPARED if _comparable(a[qid]["plan"], f) != _comparable(b[qid]["plan"], f)]
        if diffs:
            lines.append(f"{qid} ({a[qid]['text']}):\n    " + "\n    ".join(diffs))
    only = sorted(set(a) ^ set(b))
    if only:
        lines.append(f"in only one run: {', '.join(only)}")
    return lines
