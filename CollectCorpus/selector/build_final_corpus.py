"""Build the final corpus: the current corpus + the BFS expansion, filtered by the selector v3 (EmbeddingGemma 2).

    python -m selector.build_final_corpus          (run from the CollectCorpus folder)

Pages considered:
  * the corpus behind the old DATA.json (data/ukraine_war_military, 1,910 pages);
  * the BFS pages that were collected before and removed by the category filter (555, content in data/ukraine_war);
  * the BFS pages downloaded for the expansion (3,551, data/expansion/links10/candidates_links10.jsonl).
Scores come from Colab: data/selector/v3/compare_exam_scores.csv (corpus + the 555) and gemma_candidate_scores.csv
(the 3,551), both with the Gemma and the E5 v3 scores. The selector's 40 training pages are decided by their hand
label (related -> in, not related -> out).

Only "accept" enters the corpus. The "review" zone is kept aside with its full text, plus an Excel with each page's
most military paragraphs and a decision column; `python -m selector.add_reviewed` adds the pages marked "להוסיף".
The same corpus is also built with E5 v3, only to compare the two.

Writes:
    data/ukraine_war_final/pages.jsonl, DATA.json     - the corpus (Gemma)
    data/ukraine_war_final/review_pages.jsonl         - the review zone, full text, ready to be added
    summaries/ukraine_war_final/zones.csv             - every page considered, with origin, scores and zone
    summaries/ukraine_war_final/review_pages.xlsx     - the review zone, for a manual decision
    summaries/ukraine_war_final/compare_e5.csv        - pages that only one of the two models lets in
    summaries/ukraine_war_final/selector_summary.md   - counts (summary.md / summary.csv: summarize_corpus.py)
    data/ukraine_war_final_e5/pages.jsonl, DATA.json  - the same corpus with E5 v3 (comparison only)
"""
import hashlib
import json
import sys
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


def write_corpus(name, pages, titles):
    out = corpus_dir(name)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "pages.jsonl").open("w", encoding="utf-8") as f:
        for t in titles:
            f.write(json.dumps(pages[t], ensure_ascii=False) + "\n")
    export_data_json(name)


def top_paragraphs(pages, titles, cache_dir):
    """{title: [(probability, paragraph), ...]} - each page's most military paragraphs, by the Gemma selector.
    Vectors are computed on the CPU in chunks saved to cache_dir, so a stopped run continues."""
    selector = Selector.load(MODEL_DIR)
    para_page, para_text = [], []
    for t in titles:
        for _, text in split_paragraphs(pages[t]["content"]):
            para_page.append(t); para_text.append(text)
    key = hashlib.md5("\n".join(para_text).encode("utf-8")).hexdigest()[:8]
    cache_dir = cache_dir / key
    cache_dir.mkdir(parents=True, exist_ok=True)
    parts, chunk = [], 500
    for start in range(0, len(para_text), chunk):
        path = cache_dir / f"{start:06d}.npy"
        if not path.exists():
            np.save(path, selector.embed(para_text[start:start + chunk]))
            print(f"  review paragraphs: vectors {min(start + chunk, len(para_text))}/{len(para_text)}", flush=True)
        parts.append(np.load(path))
    probs = selector.paragraph_scores(None, vectors=np.vstack(parts)) if parts else []
    top = {}
    for t, p, text in zip(para_page, probs, para_text):
        top.setdefault(t, []).append((float(p), text))
    return {t: sorted(v, reverse=True)[:TOP_PARAGRAPHS] for t, v in top.items()}


def review_workbook(df, top, path):
    """The review zone, best scores first: the most military paragraphs and a decision column (להוסיף / לא להוסיף)."""
    from openpyxl.styles import Alignment, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation
    df = df.sort_values("gemma_score", ascending=False)
    old = set(json.loads(OLD_DATA.read_text(encoding="utf-8"))) if OLD_DATA.exists() else set()
    out = pd.DataFrame({"מקור": df.origin.map(ORIGIN), "היה ב-DATA.json הקודם": np.where(df.title.isin(old), "כן", ""),
                        "כותרת": df.title, "ציון": df.gemma_score,
                        "פסקאות": df.paragraphs, "פסקאות צבאיות": df.gemma_related, "קישור": df.title.map(url)})
    for i in range(TOP_PARAGRAPHS):
        out[f"פסקה צבאית {i + 1}"] = [f"({top[t][i][0]:.2f}) {top[t][i][1][:500]}" if len(top.get(t, [])) > i else ""
                                      for t in df.title]
    out["החלטה"] = ""
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        out.to_excel(xw, index=False, sheet_name="אזור ביניים")
        ws = xw.sheets["אזור ביניים"]
        ws.sheet_view.rightToLeft = True
        ws.freeze_panes = "D2"
        ws.auto_filter.ref = ws.dimensions
        last = chr(ord("A") + len(out.columns) - 1)
        for col, w in zip("ABCDEFGHIJK", [16, 10, 40, 7, 8, 11, 8, 60, 60, 60, 13]):
            ws.column_dimensions[col].width = w
        for r in range(2, len(out) + 2):
            cell = ws.cell(r, 7)
            cell.hyperlink, cell.value = cell.value, "פתח"
            for c in range(8, 8 + TOP_PARAGRAPHS):
                ws.cell(r, c).alignment = Alignment(wrap_text=True, vertical="top")
            ws.cell(r, len(out.columns)).fill = PatternFill("solid", fgColor="FFF2CC")
        dv = DataValidation(type="list", formula1='"להוסיף,לא להוסיף"')
        ws.add_data_validation(dv)
        dv.add(f"{last}2:{last}{len(out) + 1}")


def main():
    pages, df = collect()
    rep = Path("summaries") / OUT
    rep.mkdir(parents=True, exist_ok=True)
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
    top = top_paragraphs(pages, review.title.tolist(), V3 / "review_vectors_gemma2")
    review_workbook(review, top, rep / "review_pages.xlsx")

    g, e = set(members["gemma"]), set(members["e5"])
    diff = df[df.title.isin(g ^ e)].assign(only_in=lambda d: np.where(d.title.isin(g), "gemma", "e5"))
    diff = diff[["only_in", "title", "origin", "paragraphs", "gemma_score", "gemma_related", "gemma_zone",
                 "e5_score", "e5_related", "e5_zone"]].sort_values(["only_in", "gemma_score"], ascending=[False, False])
    diff.to_csv(rep / "compare_e5.csv", index=False, encoding="utf-8-sig")

    counts = pd.crosstab(df.origin.map(ORIGIN), df.gemma_zone, margins=True, margins_name="סה\"כ")
    (rep / "selector_summary.md").write_text(
        f"# {OUT}\n\nSelector v3 with EmbeddingGemma 2 (paragraph >= 0.7; accept >= 0.30 or >= 7 related paragraphs; "
        f"reject < 0.10). Only accept enters; review is kept aside (review_pages.xlsx).\n\n"
        f"* Corpus (Gemma): **{len(g)} pages** | the same with E5 v3: {len(e)} | in both: {len(g & e)} | "
        f"only Gemma: {len(g - e)} | only E5: {len(e - g)}\n* Review zone kept aside: {len(review)} pages\n\n"
        f"## Zones by origin (Gemma)\n\n```\n{counts.to_string()}\n```\n", encoding="utf-8")
    print(f"\nGemma {len(g)} | E5 {len(e)} | both {len(g & e)} | only Gemma {len(g - e)} | only E5 {len(e - g)} | "
          f"review aside {len(review)}\nreport in {rep}/")


if __name__ == "__main__":
    main()
