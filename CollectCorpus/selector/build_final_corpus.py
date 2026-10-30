"""Build the final corpus: the current corpus + the BFS expansion, filtered by the selector v3 (EmbeddingGemma 2).

    python -m selector.build_final_corpus          (run from the CollectCorpus folder)

Pages considered:
  * the corpus behind the old DATA.json (data/ukraine_war_military, 1,910 pages);
  * the BFS pages that were collected before and removed by the category filter (555, content in data/ukraine_war);
  * the BFS pages downloaded for the expansion (3,551, data/expansion/links10/candidates_links10.jsonl).
Scores come from Colab: data/selector/v3/compare_exam_scores.csv (corpus + the 555) and gemma_candidate_scores.csv
(the 3,551), both with the Gemma and the E5 v3 scores. The selector's 40 training pages are decided by their hand
label (related -> in, not related -> out).

Who enters ("two signals", chosen 2026-10-29): the selector's "accept", plus pages of the earlier corpus - which
passed the military category filter, a second, independent signal - that the text shows as at least partly military:
  rule 1: earlier-corpus page in the "review" zone                          -> enters
  rule 2: earlier-corpus page rejected but with >= 3 military paragraphs    -> enters (e.g. cities with a war section)
  rule 3: BFS page accepted only by the 7-paragraph rule, < 10% military    -> review zone (e.g. International Space Station)
Then the manual decisions in selector/manual_decisions.csv (include / exclude / keep / skip) are applied.
The "review" zone is kept aside with its full text. Two Excels with each page's most military paragraphs serve the
manual decisions: review_pages.xlsx (add a page) and cleanup_pages.xlsx (remove a borderline page that got in);
`python -m selector.add_reviewed` records the decisions and rebuilds.
The same corpus is also built with E5 v3 (same rules and decisions), only to compare the two.

Writes:
    data/ukraine_war_final/pages.jsonl, DATA.json     - the corpus (Gemma)
    data/ukraine_war_final/review_pages.jsonl         - the review zone, full text, ready to be added
    summaries/ukraine_war_final/zones.csv             - every page considered, with origin, scores and zone
    summaries/ukraine_war_final/review_pages.xlsx     - the review zone, for a manual decision (add)
    summaries/ukraine_war_final/cleanup_pages.xlsx    - borderline pages in the corpus, for a manual decision (remove)
    summaries/ukraine_war_final/compare_e5.csv        - pages that only one of the two models lets in
    summaries/ukraine_war_final/selector_summary.md   - counts (summary.md / summary.csv: summarize_corpus.py)
    data/ukraine_war_final_e5/pages.jsonl, DATA.json  - the same corpus with E5 v3 (comparison only)
"""
import hashlib
import json
import sys
from datetime import date
from pathlib import Path
from urllib.parse import quote

import numpy as np
import pandas as pd

from build_corpus import corpus_dir, load_pages
from export_corpus import export_data_json
from selector.build_training_set import split_paragraphs
from selector.selector import Selector

sys.stdout.reconfigure(encoding="utf-8")

OUT = "ukraine_war_final"
V3 = Path("data/selector/v3")
MODEL_DIR = V3 / "model_gemma"
CORPUS = "ukraine_war_military"           # the corpus behind the old DATA.json
SEEN = "ukraine_war"                      # every page collected before any filter
EXPANSION = Path("data/expansion/links10/candidates_links10.jsonl")
EXPANSION_SCORES = Path("summaries/expansion_links10/expansion_scores.csv")   # lists the 555 reused pages
TRAINING = Path("selector/training_pages_v3.csv")
ORIGIN = {"corpus": "קורפוס קיים", "bfs_seen": "הרחבה (נאסף בעבר)", "bfs_new": "הרחבה (חדש)", "training": "דף אימון"}
TOP_PARAGRAPHS = 3
MIN_RELATED_REJECTED = 3      # rule 2
MIN_SHARE_QUANTITY = 0.10     # rule 3
DECISIONS = Path("selector/manual_decisions.csv")   # title, decision (include/exclude/keep/skip), date
VECTORS = V3 / "page_vectors_gemma2"                # paragraph vectors per page, for the Excels
REASON = {"share": "התקבל (30%+ צבאי)", "quantity": "התקבל בכלל הכמות (7+ פסקאות צבאיות)",
          "rule1": "קורפוס קודם + אזור ביניים", "rule2": "קורפוס קודם + 3+ פסקאות צבאיות",
          "include": "הוספה ידנית", "training": "דף אימון"}
OLD_DATA = Path("data/ukraine_war_selected/DATA.json")   # the DATA.json the team used until 2026-10 (1,602 pages)


def url(title):
    return "https://en.wikipedia.org/wiki/" + quote(title.replace(" ", "_"))


def collect():
    """{title: page record} for every page considered, and a table with its origin and both models' zones."""
    corpus = load_pages(corpus_dir(CORPUS) / "pages.jsonl")
    seen = load_pages(corpus_dir(SEEN) / "pages.jsonl")
    reused = pd.read_csv(EXPANSION_SCORES)
    reused = set(reused[reused.origin.str.startswith("נבדק")].title)
    training = pd.read_csv(TRAINING).set_index("title").label
    raw_training = json.loads((V3 / "training_pages.json").read_text(encoding="utf-8"))

    pages, rows = {}, []
    exam = pd.read_csv(V3 / "compare_exam_scores.csv").set_index("title")
    for title in list(corpus) + sorted(reused - set(corpus)):
        origin = "corpus" if title in corpus else "bfs_seen"
        pages[title] = corpus.get(title) or seen[title]
        if title in training.index:
            continue                                    # decided below, by its hand label
        s = exam.loc[title]
        rows.append({"title": title, "origin": origin, "paragraphs": s.paragraphs,
                     **{f"{m}_{k}": s[f"{m}_{k}"] for m in ["gemma", "e5"] for k in ["score", "related", "zone"]}})

    cand_scores = pd.read_csv(V3 / "gemma_candidate_scores.csv").set_index("title")
    with EXPANSION.open(encoding="utf-8") as f:
        for line in f:
            p = json.loads(line)
            if p["title"] in training.index:            # 8 training pages were also found by the BFS
                continue
            pages[p["title"]] = {"title": p["title"], "revid": p["revid"], "url": url(p["title"]),
                                 "source": "bfs-links10", "links_from_corpus": p["links_from_corpus"],
                                 "content": p["content"]}
            s = cand_scores.loc[p["title"]]
            rows.append({"title": p["title"], "origin": "bfs_new", "paragraphs": s.paragraphs,
                         **{f"{m}_{k}": s[f"{m}_{k if k != 'zone' else 'decision'}"]
                            for m in ["gemma", "e5"] for k in ["score", "related", "zone"]}})

    for title, label in training.items():
        if title not in pages:
            pages[title] = {"title": title, "revid": raw_training[title]["revid"], "url": url(title),
                            "source": "selector-training", "content": raw_training[title]["content"]}
        zone = "training_related" if label == 1 else "training_unrelated"
        rows.append({"title": title, "origin": "training", "gemma_zone": zone, "e5_zone": zone})
    return pages, pd.DataFrame(rows)


def load_decisions():
    """{title: decision} from selector/manual_decisions.csv (the latest decision per title wins)."""
    if not DECISIONS.exists():
        return {}
    d = pd.read_csv(DECISIONS, encoding="utf-8-sig")
    return dict(zip(d.title, d.decision))


def record_decisions(new):
    """Append {title: decision} to selector/manual_decisions.csv."""
    rows = pd.DataFrame({"title": list(new), "decision": list(new.values()), "date": date.today().isoformat()})
    rows.to_csv(DECISIONS, mode="a", header=not DECISIONS.exists(), index=False, encoding="utf-8-sig")


def final_zones(df, model, decisions):
    """(zone, reason) per page after the two-signal rules and the manual decisions.
    zone: accept / review / reject / excluded (manual) / training_related / training_unrelated."""
    zone, score, related = df[f"{model}_zone"].copy(), df[f"{model}_score"], df[f"{model}_related"]
    backed = df.origin == "corpus"          # passed the military category filter
    reason = pd.Series("", index=df.index)
    accepted = zone == "accept"
    reason[accepted] = np.where(score[accepted] >= 0.30, "share", "quantity")
    r1 = backed & (zone == "review")
    r2 = backed & (zone == "reject") & (related >= MIN_RELATED_REJECTED)
    r3 = ~backed & (df.origin != "training") & accepted & (score < MIN_SHARE_QUANTITY)
    zone[r1 | r2] = "accept"
    reason[r1], reason[r2] = "rule1", "rule2"
    zone[r3], reason[r3] = "review", ""
    reason[zone.str.startswith("training")] = "training"
    dec = df.title.map(decisions)
    zone[dec == "include"], reason[dec == "include"] = "accept", "include"
    zone[dec == "exclude"], reason[dec == "exclude"] = "excluded", ""
    return zone, reason


def write_corpus(name, pages, titles):
    out = corpus_dir(name)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "pages.jsonl").open("w", encoding="utf-8") as f:
        for t in titles:
            f.write(json.dumps(pages[t], ensure_ascii=False) + "\n")
    export_data_json(name)


def page_vector_path(page):
    """One file per page, named by its text, so a changed page is computed again."""
    return VECTORS / (hashlib.md5(page["content"].encode("utf-8")).hexdigest()[:16] + ".npy")


def top_paragraphs(pages, titles):
    """{title: [(probability, paragraph), ...]} - each page's most military paragraphs, by the Gemma selector.
    Paragraph vectors are computed on the CPU once per page and saved to VECTORS, so later runs are quick."""
    selector = Selector.load(MODEL_DIR)
    VECTORS.mkdir(parents=True, exist_ok=True)
    todo = [t for t in titles if not page_vector_path(pages[t]).exists()]
    if todo:
        print(f"  computing paragraph vectors for {len(todo)} pages (CPU)...", flush=True)
    for i, t in enumerate(todo, 1):
        paragraphs = [p for _, p in split_paragraphs(pages[t]["content"])]
        np.save(page_vector_path(pages[t]), selector.embed(paragraphs) if paragraphs else np.zeros((0, 768)))
        if i % 25 == 0:
            print(f"    {i}/{len(todo)} pages", flush=True)
    top = {}
    for t in titles:
        paragraphs = [p for _, p in split_paragraphs(pages[t]["content"])]
        if paragraphs:
            probs = selector.paragraph_scores(None, vectors=np.load(page_vector_path(pages[t])))
            top[t] = sorted(zip(probs.tolist(), paragraphs), reverse=True)[:TOP_PARAGRAPHS]
    return top


def lead(page, chars=300):
    """The page's first paragraph: what the page is about."""
    first = next((p for _, p in split_paragraphs(page["content"])), page["content"])
    return first[:chars]


DECISION_WORDS = {"review": ("להוסיף", "לא להוסיף", "include", "skip"),     # Excel words -> manual_decisions.csv
                  "cleanup": ("להוציא", "להשאיר", "exclude", "keep")}


def decision_workbook(df, pages, top, decisions, path, kind):
    """kind="review": the review zone (add a page?); kind="cleanup": borderline pages in the corpus (remove it?).
    Each row: origin, why it is here, score, the page's opening and its most military paragraphs, and a decision
    column with a dropdown, pre-filled with earlier decisions."""
    from openpyxl.styles import Alignment, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation
    yes, no, yes_code, no_code = DECISION_WORDS[kind]
    df = df.sort_values("gemma_score", ascending=kind == "cleanup")      # cleanup: weakest first
    old = set(json.loads(OLD_DATA.read_text(encoding="utf-8"))) if OLD_DATA.exists() else set()
    out = pd.DataFrame({"מקור": df.origin.map(ORIGIN), "היה ב-DATA.json הקודם": np.where(df.title.isin(old), "כן", ""),
                        "כותרת": df.title})
    if kind == "cleanup":
        out["למה נכנס"] = df.reason.map(REASON)
    out["ציון"], out["פסקאות"], out["פסקאות צבאיות"] = df.gemma_score, df.paragraphs, df.gemma_related
    out["קישור"] = df.title.map(url)
    out["פתיחת הדף"] = [lead(pages[t]) for t in df.title]
    for i in range(TOP_PARAGRAPHS):
        out[f"פסקה צבאית {i + 1}"] = [f"({top[t][i][0]:.2f}) {top[t][i][1][:400]}" if len(top.get(t, [])) > i else ""
                                      for t in df.title]
    out["החלטה"] = df.title.map(decisions).map({yes_code: yes, no_code: no}).fillna("")
    sheet = "אזור ביניים" if kind == "review" else "לניקוי"
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        out.to_excel(xw, index=False, sheet_name=sheet)
        ws = xw.sheets[sheet]
        ws.sheet_view.rightToLeft = True
        ws.freeze_panes = "D2"
        ws.auto_filter.ref = ws.dimensions
        widths = {"מקור": 16, "היה ב-DATA.json הקודם": 10, "כותרת": 40, "למה נכנס": 22, "ציון": 7, "פסקאות": 8,
                  "פסקאות צבאיות": 10, "קישור": 7, "פתיחת הדף": 50, "החלטה": 13}
        cols = list(out.columns)
        for i, c in enumerate(cols):
            ws.column_dimensions[chr(ord("A") + i)].width = widths.get(c, 55)
        link, decision = cols.index("קישור") + 1, cols.index("החלטה") + 1
        for r in range(2, len(out) + 2):
            cell = ws.cell(r, link)
            cell.hyperlink, cell.value = cell.value, "פתח"
            for c in range(cols.index("פתיחת הדף") + 1, decision):
                ws.cell(r, c).alignment = Alignment(wrap_text=True, vertical="top")
            ws.cell(r, decision).fill = PatternFill("solid", fgColor="FFF2CC")
        dv = DataValidation(type="list", formula1=f'"{yes},{no}"', allow_blank=True)
        ws.add_data_validation(dv)
        col = chr(ord("A") + decision - 1)
        dv.add(f"{col}2:{col}{len(out) + 1}")


def main():
    pages, df = collect()
    rep = Path("summaries") / OUT
    rep.mkdir(parents=True, exist_ok=True)
    decisions = load_decisions()
    for model in ["gemma", "e5"]:
        df[f"{model}_selector_zone"] = df[f"{model}_zone"]          # the selector alone, before the rules
        df[f"{model}_zone"], df[f"{model}_reason"] = final_zones(df, model, decisions)
    df.to_csv(rep / "zones.csv", index=False, encoding="utf-8-sig")

    members = {}
    for model, name in [("gemma", OUT), ("e5", OUT + "_e5")]:
        zone = df[f"{model}_zone"]
        members[model] = df[zone.isin(["accept", "training_related"])].title.tolist()
        print(f"\n{model}: {len(members[model])} pages in the corpus | " + ", ".join(f"{k} {v}" for k, v in zone.value_counts().items()))
        write_corpus(name, pages, members[model])

    review = df[df.gemma_zone == "review"]
    with (corpus_dir(OUT) / "review_pages.jsonl").open("w", encoding="utf-8") as f:
        for t in review.title:
            f.write(json.dumps(pages[t], ensure_ascii=False) + "\n")
    cleanup = df[(df.gemma_zone == "accept") & (df.gemma_reason != "share")].rename(columns={"gemma_reason": "reason"})

    g, e = set(members["gemma"]), set(members["e5"])
    diff = df[df.title.isin(g ^ e)].assign(only_in=lambda d: np.where(d.title.isin(g), "gemma", "e5"))
    diff = diff[["only_in", "title", "origin", "paragraphs", "gemma_score", "gemma_related", "gemma_zone",
                 "e5_score", "e5_related", "e5_zone"]].sort_values(["only_in", "gemma_score"], ascending=[False, False])
    diff.to_csv(rep / "compare_e5.csv", index=False, encoding="utf-8-sig")

    origin = df.origin.map({"corpus": "earlier corpus", "bfs_seen": "BFS (collected before)", "bfs_new": "BFS (new)",
                            "training": "training page"})
    counts = pd.crosstab(origin, df.gemma_zone, margins=True, margins_name="total")
    why = df[df.gemma_zone == "accept"].gemma_reason.value_counts()
    (rep / "selector_summary.md").write_text(
        f"# {OUT}\n\nSelector v3 with EmbeddingGemma 2 (paragraph >= 0.7; accept >= 0.30 or >= 7 military paragraphs; "
        f"reject < 0.10), then the two-signal rules: earlier-corpus pages (passed the military category filter) enter "
        f"from the review zone (rule 1) or when rejected with >= {MIN_RELATED_REJECTED} military paragraphs (rule 2); "
        f"BFS pages accepted only by the 7-paragraph rule with < {MIN_SHARE_QUANTITY:.0%} military go to review (rule 3). "
        f"Manual decisions: selector/manual_decisions.csv.\n\n"
        f"* Corpus (Gemma): **{len(g)} pages** | the same with E5 v3: {len(e)} | in both: {len(g & e)} | "
        f"only Gemma: {len(g - e)} | only E5: {len(e - g)}\n* Review zone kept aside: {len(review)} pages\n"
        f"* Why pages entered (accept): " + ", ".join(f"{k} {v}" for k, v in why.items()) + "\n\n"
        f"## Zones by origin (Gemma)\n\n```\n{counts.to_string()}\n```\n", encoding="utf-8")
    print(f"\nGemma {len(g)} | E5 {len(e)} | both {len(g & e)} | only Gemma {len(g - e)} | only E5 {len(e - g)} | "
          f"review aside {len(review)} | cleanup list {len(cleanup)}\nreport in {rep}/")

    # the Excels last: a first run computes paragraph vectors on the CPU (slow); the corpus is already written
    top = top_paragraphs(pages, review.title.tolist() + cleanup.title.tolist())
    decision_workbook(review, pages, top, decisions, rep / "review_pages.xlsx", "review")
    decision_workbook(cleanup, pages, top, decisions, rep / "cleanup_pages.xlsx", "cleanup")


if __name__ == "__main__":
    main()
