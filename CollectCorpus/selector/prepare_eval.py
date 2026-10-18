"""The exam set for choosing the selector's thresholds: the existing corpus, minus the training pages.

    python -m selector.prepare_eval            (run from the CollectCorpus folder)

Each page keeps the label from the category filter (data/model_filter/dataset.csv): 1 = kept in the
military corpus, 0 = removed. These pages are only used for testing, never for training.
Writes data/selector/eval_pages.jsonl: one page per line {title, label, label_status, content}.
"""
import json
import sys

import pandas as pd

from build_corpus import corpus_dir, load_pages
from selector.build_training_set import OUT_DIR, split_paragraphs

sys.stdout.reconfigure(encoding="utf-8")


def prepare(name="ukraine_war"):
    labels = pd.read_csv("data/model_filter/dataset.csv", encoding="utf-8-sig").set_index("title")
    training = set(json.loads((OUT_DIR / "training_pages.json").read_text(encoding="utf-8")))
    pages = load_pages(corpus_dir(name) / "pages.jsonl")
    n = paragraphs = 0
    with (OUT_DIR / "eval_pages.jsonl").open("w", encoding="utf-8") as f:
        for title, page in pages.items():
            if title in training or title not in labels.index or page.get("status") == "missing":
                continue
            row = labels.loc[title]
            f.write(json.dumps({"title": title, "label": int(row.label), "label_status": row.label_status,
                                "content": page["content"]}, ensure_ascii=False) + "\n")
            n += 1
            paragraphs += len(split_paragraphs(page["content"]))
    print(f"wrote {OUT_DIR / 'eval_pages.jsonl'}: {n} pages, {paragraphs} paragraphs "
          f"(training pages excluded: {len(training & set(pages))})")


if __name__ == "__main__":
    prepare()
