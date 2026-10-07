"""Summarize a corpus without opening the big pages.jsonl.

    python summarize_corpus.py --name ukraine_war

Writes to summaries/<name>/ (committed to git, unlike data/):
    summary.csv - one row per page: title, source, size, sections, coordinates, last edit, url
    summary.md  - overview: totals, where pages came from, size spread, top categories, largest pages
"""
import argparse
import csv
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from build_corpus import NOISE_CATEGORY_PREFIXES, corpus_dir, load_pages

sys.stdout.reconfigure(encoding="utf-8")


def source_group(source):
    """Collapse sources into a few readable groups."""
    if source == "seed":
        return "seed page"
    if source.startswith("seed-file:"):
        return source  # keep the file name, e.g. seed-file:team_DATA_json_titles.txt
    return "category tree"


def summarize(name):
    """Write summaries/<name>/summary.csv and summary.md."""
    pages = [p for p in load_pages(corpus_dir(name) / "pages.jsonl").values() if p.get("status") != "missing"]
    out_dir = Path("summaries") / name
    out_dir.mkdir(parents=True, exist_ok=True)

    with (out_dir / "summary.csv").open("w", encoding="utf-8-sig", newline="") as f:  # -sig so Excel reads Hebrew/UTF-8
        w = csv.writer(f)
        w.writerow(["title", "source", "chars", "sections", "lat", "lon", "last_edited", "url"])
        for p in sorted(pages, key=lambda p: p["title"]):
            c = p.get("coordinates") or {}
            w.writerow([p["title"], p["source"], len(p["text"]), len(p["sections"]),
                        c.get("lat", ""), c.get("lon", ""), p.get("last_edited", ""), p["url"]])

    sizes = sorted(len(p["text"]) for p in pages)
    groups = Counter(source_group(p["source"]) for p in pages)
    top_sources = Counter(p["source"] for p in pages if source_group(p["source"]) == "category tree")
    top_cats = Counter(c for p in pages for c in p["categories"] if not c.startswith(NOISE_CATEGORY_PREFIXES))
    buckets = [("< 1K", 0, 1_000), ("1K–5K", 1_000, 5_000), ("5K–20K", 5_000, 20_000),
               ("20K–50K", 20_000, 50_000), ("> 50K", 50_000, float("inf"))]

    md = [
        f"# Corpus summary: `{name}`",
        f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC from `pages.jsonl`.",
        "",
        "## Totals",
        "| | |", "|---|---|",
        f"| Pages | {len(pages):,} |",
        f"| Text | {sum(sizes) / 1e6:.1f}M characters |",
        f"| Sections | {sum(len(p['sections']) for p in pages):,} |",
        f"| With coordinates | {sum(bool(p.get('coordinates')) for p in pages):,} |",
        f"| Median page size | {sizes[len(sizes) // 2]:,} characters |",
        f"| Most recent edit | {max(p.get('last_edited') or '' for p in pages)} |",
        "",
        "## Where the pages came from",
        "| Source | Pages |", "|---|---|",
        *[f"| {g} | {n:,} |" for g, n in groups.most_common()],
        "",
        "### Top categories the crawl found pages in",
        "| Category | Pages |", "|---|---|",
        *[f"| {s.replace('Category:', '')} | {n} |" for s, n in top_sources.most_common(20)],
        "",
        "## Page size",
        "| Characters | Pages |", "|---|---|",
        *[f"| {label} | {sum(lo <= s < hi for s in sizes):,} |" for label, lo, hi in buckets],
        "",
        "## Most common categories on the pages",
        "| Category | Pages |", "|---|---|",
        *[f"| {c.replace('Category:', '')} | {n} |" for c, n in top_cats.most_common(25)],
        "",
        "## Largest pages",
        "| Page | Characters |", "|---|---|",
        *[f"| {p['title']} | {len(p['text']):,} |" for p in sorted(pages, key=lambda p: -len(p["text"]))[:15]],
        "",
        "Full per-page list: `summary.csv`.",
    ]
    (out_dir / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"wrote {out_dir / 'summary.csv'} ({len(pages)} rows) and {out_dir / 'summary.md'}")



def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True)
    args = ap.parse_args()

    summarize(args.name)


if __name__ == "__main__":
    main()
