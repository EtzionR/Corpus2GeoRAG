"""Add review-zone pages marked "להוסיף" to the corpus.

    python -m selector.add_reviewed                (run from the CollectCorpus folder, with the Excel closed)

Reads the decision column of summaries/<name>/review_pages.xlsx, takes the marked pages from
data/<name>/review_pages.jsonl (full text, nothing is downloaded), appends them to data/<name>/pages.jsonl and
exports DATA.json again. Pages already in the corpus are skipped, so it can be run after every round of review.
Each run is logged in summaries/<name>/added_from_review.csv.
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from build_corpus import corpus_dir, load_pages
from export_corpus import export_data_json

sys.stdout.reconfigure(encoding="utf-8")


def add_reviewed(name):
    sheet = pd.read_excel(Path("summaries") / name / "review_pages.xlsx")
    marked = sheet[sheet["החלטה"].astype(str).str.strip() == "להוסיף"]["כותרת"].tolist()
    review = load_pages(corpus_dir(name) / "review_pages.jsonl")
    corpus = load_pages(corpus_dir(name) / "pages.jsonl")
    new = [t for t in marked if t not in corpus]
    if not new:
        print(f"nothing new to add ({len(marked)} marked, all already in the corpus)")
        return
    with (corpus_dir(name) / "pages.jsonl").open("a", encoding="utf-8") as f:
        for t in new:
            f.write(json.dumps(review[t], ensure_ascii=False) + "\n")
    export_data_json(name)
    log = Path("summaries") / name / "added_from_review.csv"
    pd.DataFrame({"title": new, "added": date.today().isoformat()}).to_csv(
        log, mode="a", header=not log.exists(), index=False, encoding="utf-8-sig")
    print(f"added {len(new)} pages -> {len(corpus) + len(new)} in the corpus; logged in {log}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", default="ukraine_war_final", help="the corpus (data/<name>/)")
    add_reviewed(ap.parse_args().name)
