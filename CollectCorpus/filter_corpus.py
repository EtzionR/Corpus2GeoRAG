"""Filter a corpus by the decisions in filters/category_review.csv -> a new, separate corpus.

    python filter_corpus.py --name ukraine_war --out ukraine_war_military

The original corpus is not touched. Every page has a `source` (the category it was found in).
A page is kept when its source is marked "keep". A page whose source is marked "remove" is still
kept ("rescued") if one of its own categories is a "keep" category: `source` only records the
first category we found the page in, so this stops military pages from being dropped by accident.
A second rule rescues people with a military role: categories like "Russian admirals",
"Ukrainian military personnel ..." or "GRU officers" (see MILITARY_ROLE).
Sources that are not in the review table (new categories after an update) are kept, with a warning.

Writes:
    data/<out>/pages.jsonl                  - the filtered corpus
    summaries/<out>/filter_report.md        - what was removed, rescued, and why
    summaries/<out>/removed.csv             - every removed page and the category it came from
"""
import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

from build_corpus import corpus_dir, load_pages

sys.stdout.reconfigure(encoding="utf-8")

# Page categories that mark a person with a military role, e.g. "Russian colonel generals", "GRU officers"
MILITARY_ROLE = re.compile(r"military personnel|\b(generals|admirals|colonels|officers)\b|naval commanders", re.I)
# ... but not these look-alikes found in the corpus
NOT_MILITARY = re.compile(r"Military World Games|Prosecutors general|police", re.I)


def strip(category):
    return category.replace("Category:", "", 1)


def load_decisions(path):
    """category_review.csv -> {category: "keep" | "remove"}."""
    with open(path, encoding="utf-8-sig") as f:
        return {row["category"]: row["decision"] for row in csv.DictReader(f)}


def classify(page, decisions):
    """-> ("keep" | "rescued" | "remove", reason)."""
    src = strip(page["source"])
    decision = decisions.get(src)
    if decision is None:
        return "keep", f"not in review table: {src}"
    if decision == "keep":
        return "keep", src
    rescue = [strip(c) for c in page["categories"] if decisions.get(strip(c)) == "keep"]
    if rescue:
        return "rescued", rescue[0]
    role = [strip(c) for c in page["categories"] if MILITARY_ROLE.search(c) and not NOT_MILITARY.search(c)]
    if role:
        return "rescued", f"military role: {role[0]}"
    return "remove", src


def filter_corpus(name, out, review="filters/category_review.csv"):
    """Write the pages that pass the review decisions to data/<out>/ and a report to summaries/<out>/."""
    decisions = load_decisions(review)
    pages = [p for p in load_pages(corpus_dir(name) / "pages.jsonl").values() if p.get("status") != "missing"]
    results = [(p, *classify(p, decisions)) for p in pages]

    out_dir = corpus_dir(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "pages.jsonl").open("w", encoding="utf-8") as f:
        for p, status, _ in results:
            if status != "remove":
                f.write(json.dumps(p, ensure_ascii=False) + "\n")

    report_dir = Path("summaries") / out
    report_dir.mkdir(parents=True, exist_ok=True)
    removed = [(p, why) for p, status, why in results if status == "remove"]
    rescued = [(p, why) for p, status, why in results if status == "rescued"]
    unknown = Counter(why for _, status, why in results if why.startswith("not in review"))
    with (report_dir / "removed.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["title", "removed_category", "url"])
        for p, why in sorted(removed, key=lambda r: (r[1], r[0]["title"])):
            w.writerow([p["title"], why, p["url"]])

    kept = len(pages) - len(removed)
    md = [
        f"# Filter report: `{name}` → `{out}`",
        f"Decisions: `{review}`.",
        "",
        "| | Pages |", "|---|---|",
        f"| Before | {len(pages):,} |",
        f"| Removed | {len(removed):,} |",
        f"| Rescued (source removed, but also in a kept category) | {len(rescued):,} |",
        f"| **After** | **{kept:,}** |",
        "",
        "## Removed, by category",
        "| Category | Pages |", "|---|---|",
        *[f"| {c} | {n} |" for c, n in Counter(why for _, why in removed).most_common()],
        "",
        "## Rescued pages (kept because of another category)",
        "| Page | Came from (removed) | Kept by |", "|---|---|---|",
        *[f"| {p['title']} | {strip(p['source'])} | {why} |" for p, why in sorted(rescued, key=lambda r: r[0]["title"])],
    ]
    if unknown:
        md += ["", "## Sources not in the review table (kept)", "| Source | Pages |", "|---|---|",
               *[f"| {w.split(': ', 1)[1]} | {n} |" for w, n in unknown.most_common()]]
    (report_dir / "filter_report.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(f"{len(pages)} pages -> {kept} kept ({len(rescued)} rescued), {len(removed)} removed")
    if unknown:
        print(f"warning: {sum(unknown.values())} pages from {len(unknown)} sources not in the review table were kept")
    print(f"wrote {out_dir / 'pages.jsonl'} and {report_dir}/")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True, help="corpus to filter (data/<name>/)")
    ap.add_argument("--out", required=True, help="name of the filtered corpus (data/<out>/)")
    ap.add_argument("--review", default="filters/category_review.csv", help="decisions table")
    args = ap.parse_args()
    filter_corpus(args.name, args.out, args.review)


if __name__ == "__main__":
    main()
