"""Apply the selector's zones to an existing corpus: keep "accept" + "review", drop "reject".

    python -m selector.apply_to_corpus                                                  (the main corpus)
    python -m selector.apply_to_corpus --out ukraine_war_selected_n7 --min-related 7     (with the quantity rule)
    (run from the CollectCorpus folder)

Uses scores already computed on Colab (data/selector/eval_scores_v2.csv, column all@<paragraph threshold>),
so nothing has to be re-embedded locally. Pages without a score are the selector's own training pages
(clearly related by choice), and are kept.

Writes:
    data/<out>/pages.jsonl                     - the new corpus (rich format)
    data/<out>/DATA.json                       - the same, in the team's format (export_corpus.py)
    summaries/<out>/selector_zones.csv         - every source page with its score and zone
    summaries/<out>/selector_review.xlsx       - the "review" and "reject" pages, for a manual look
"""
import json
import sys
from pathlib import Path
from urllib.parse import quote

import pandas as pd

from build_corpus import corpus_dir, load_pages
from export_corpus import export_data_json

sys.stdout.reconfigure(encoding="utf-8")

SOURCE = "ukraine_war_military"           # the corpus behind the current DATA.json
OUT = "ukraine_war_selected"
SCORES = "data/selector/eval_scores_v2.csv"
CONFIG = "data/selector/model/selector_config.json"


def zones(source=SOURCE, scores_path=SCORES, config_path=CONFIG, min_related=None):
    """Every page of `source` with its score, related-paragraph count and zone.
    min_related: the optional quantity rule (also accept a page with at least this many related paragraphs)."""
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    t, accept, reject = config["paragraph_threshold"], config["accept_threshold"], config["reject_threshold"]
    scores = pd.read_csv(scores_path).set_index("title")
    col = f"all@{t}"
    pages = load_pages(corpus_dir(source) / "pages.jsonl")
    rows = []
    for title, page in pages.items():
        if title in scores.index:
            score, n = float(scores.at[title, col]), int(scores.at[title, "paragraphs"])
            related = round(score * n)
            if score >= accept or (min_related and related >= min_related):
                zone = "accept"
            else:
                zone = "reject" if score < reject else "review"
        else:   # not in the exam: the selector's training pages
            score, n, related, zone = None, None, None, "training"
        rows.append({"title": title, "zone": zone, "score": score, "paragraphs": n,
                     "related_paragraphs": related, "url": page["url"]})
    rule = f" or >= {min_related} related paragraphs" if min_related else ""
    print(f"paragraph threshold {t}: accept >= {accept}{rule}, reject < {reject}")
    return pages, pd.DataFrame(rows)


def review_workbook(df, path):
    """Review + reject pages, sorted by zone and score, with a link and an empty column for a decision."""
    out = df[df.zone.isin(["review", "reject"])].sort_values(["zone", "score"], ascending=[False, False]).copy()
    out["zone"] = out.zone.map({"review": "לבדיקה", "reject": "נדחה"})
    out["link"] = out.url
    out["decision"] = ""
    out = out[["zone", "title", "score", "paragraphs", "related_paragraphs", "link", "decision"]]
    out.columns = ["אזור", "כותרת", "ציון", "פסקאות", "פסקאות צבאיות", "קישור", "החלטה (להשאיר/להוריד)"]
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        out.to_excel(xw, index=False, sheet_name="לבדיקה ונדחו")
        ws = xw.sheets["לבדיקה ונדחו"]
        ws.sheet_view.rightToLeft = True
        for col, w in zip("ABCDEFG", [9, 55, 8, 9, 13, 14, 22]):
            ws.column_dimensions[col].width = w
        for r in range(2, len(out) + 2):    # clickable links
            cell = ws.cell(r, 6)
            cell.hyperlink, cell.value = cell.value, "פתח"
        ws.freeze_panes = "A2"


def apply(source=SOURCE, out=OUT, min_related=None):
    pages, df = zones(source, min_related=min_related)
    keep = set(df[df.zone != "reject"].title)
    out_dir = corpus_dir(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "pages.jsonl").open("w", encoding="utf-8") as f:
        for title, page in pages.items():
            if title in keep:
                f.write(json.dumps(page, ensure_ascii=False) + "\n")
    export_data_json(out)

    rep = Path("summaries") / out
    rep.mkdir(parents=True, exist_ok=True)
    df.to_csv(rep / "selector_zones.csv", index=False, encoding="utf-8-sig")
    review_workbook(df, rep / "selector_review.xlsx")
    print(df.zone.value_counts().reindex(["accept", "review", "training", "reject"]).to_string())
    print(f"{len(pages)} pages -> {len(keep)} kept, {len(pages) - len(keep)} rejected; report in {rep}/")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=OUT, help="name of the new corpus (data/<out>/)")
    ap.add_argument("--min-related", type=int, default=None,
                    help="quantity rule: also accept pages with >= N related paragraphs")
    args = ap.parse_args()
    apply(out=args.out, min_related=args.min_related)
