"""Build a topical Wikipedia corpus: collect pages from category trees + seed pages, save as JSONL.

Example:
    python build_corpus.py --name ukraine_war --depth 2 \
        --category "Category:Russo-Ukrainian war (2022–present)" \
        --category "Category:Military operations of the Russian invasion of Ukraine@3" \
        --seed "Russo-Ukrainian war" --seed-file seeds/team_DATA_json_titles.txt

A category may end with "@N" to give it its own depth instead of --depth
(useful to go deeper only in specific branches). --seed-file: one page title per line;
blank lines and lines starting with # are ignored.

Output (data/<name>/):
    config.json  - the categories/seeds/depth used (update_corpus.py re-uses them)
    titles.txt   - every page title that was selected
    pages.jsonl  - one page per line (title, revid, url, summary, sections, coordinates, ...)

Re-running is safe: pages already in pages.jsonl are skipped, so an interrupted run resumes.
To refresh pages that changed on Wikipedia, use update_corpus.py.
"""
import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from wiki_client import client, flatten_sections, page_meta

sys.stdout.reconfigure(encoding="utf-8")

# Maintenance categories that say nothing about the topic
NOISE_CATEGORY_PREFIXES = (
    "Category:All ", "Category:Articles ", "Category:CS1", "Category:Webarchive ",
    "Category:Wikipedia ", "Category:Use ", "Category:Short description", "Category:Pages ",
    "Category:Commons ", "Category:Coordinates ", "Category:Official website",
)


def corpus_dir(name):
    return Path("data") / name


def load_pages(path):
    """pages.jsonl -> {title: record}, in file order."""
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return {r["title"]: r for r in map(json.loads, filter(str.strip, f))}


def parse_category(spec, default_depth):
    """"Category:X@3" -> ("Category:X", 3); "Category:X" -> ("Category:X", default_depth)."""
    name, sep, depth = spec.rpartition("@")
    return (name, int(depth)) if sep and depth.isdigit() else (spec, default_depth)


def collect_titles(wiki, categories, seeds):
    """BFS over each category tree down to its own depth.

    categories: [(name, depth), ...]; seeds: {title: source}. Returns {title: source},
    where source is the category the page was found in (or the seed label).
    Each root gets its own BFS, so a branch reached shallowly from one root is still
    walked to full depth from another root that asks for more.
    """
    titles = dict(seeds)
    members = {}  # category -> its members, so shared subcategories are fetched once
    for root, depth in categories:
        seen, frontier = set(), [root]
        for d in range(depth + 1):
            nxt = []
            for cat in frontier:
                if cat in seen:
                    continue
                seen.add(cat)
                if cat not in members:
                    members[cat] = wiki.page(cat).categorymembers
                for name, member in members[cat].items():
                    if member.ns == 0:
                        titles.setdefault(name, cat)
                    elif member.ns == 14 and d < depth:
                        nxt.append(name)
            frontier = nxt
        print(f"  {root} (depth {depth}): {len(seen)} categories, {len(titles)} pages so far")
    return titles


def titles_from_config(wiki, config):
    """Collect titles using a saved config.json (shared by build and update)."""
    seeds = {t: "seed" for t in config["seeds"]}
    for path in config.get("seed_files", []):
        for t in Path(path).read_text(encoding="utf-8").splitlines():
            t = t.strip()
            if t and not t.startswith("#"):  # blank lines and "# comments" are ignored
                seeds.setdefault(t, f"seed-file:{Path(path).name}")
    categories = [parse_category(c, config["depth"]) for c in config["categories"]]
    return collect_titles(wiki, categories, seeds)


def fetch_page(wiki, meta, source, with_links):
    """Download one page. `meta` comes from page_meta() and carries revid + coordinates."""
    page = wiki.page(meta["title"])
    return {
        "title": meta["title"],
        "pageid": meta["pageid"],
        "revid": meta["revid"],
        "last_edited": meta["last_edited"],
        "url": page.fullurl,
        "lang": wiki.language,
        "source": source,
        "coordinates": meta["coordinates"],
        "summary": page.summary,
        "sections": flatten_sections(page.sections),
        "text": page.text,
        "categories": [c for c in page.categories if not c.startswith(NOISE_CATEGORY_PREFIXES)],
        "links": list(page.links) if with_links else [],
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def fetch_many(wiki, items, with_links, workers, on_record):
    """Download [(meta, source), ...] in parallel; calls on_record(rec) for each page (in one thread)."""
    count, start = 0, time.time()
    with ThreadPoolExecutor(workers) as pool:
        futures = {pool.submit(fetch_page, wiki, m, s, with_links): m["title"] for m, s in items}
        for fut in as_completed(futures):
            try:
                rec = fut.result()
            except Exception as e:  # one bad page shouldn't kill a long run
                print(f"  ! {futures[fut]}: {e}")
                continue
            on_record(rec)
            count += 1
            if count % 25 == 0:
                print(f"  {count}/{len(items)}  ({time.time() - start:.0f}s)")
    return count


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True, help="corpus name -> data/<name>/")
    ap.add_argument("--category", action="append", default=[],
                    help='root category (repeatable); add "@N" for its own depth')
    ap.add_argument("--seed", action="append", default=[], help="extra page title (repeatable)")
    ap.add_argument("--seed-file", action="append", default=[], help="file with one title per line (repeatable)")
    ap.add_argument("--depth", type=int, default=1, help="default subcategory levels to descend")
    ap.add_argument("--lang", default="en")
    ap.add_argument("--limit", type=int, default=0, help="fetch at most N pages (0 = all)")
    ap.add_argument("--workers", type=int, default=4, help="parallel requests (keep it small)")
    ap.add_argument("--no-links", action="store_true", help="skip outgoing links (faster)")
    args = ap.parse_args()

    out_dir = corpus_dir(args.name)
    out_dir.mkdir(parents=True, exist_ok=True)
    pages_path = out_dir / "pages.jsonl"
    config = {
        "categories": args.category, "depth": args.depth, "seeds": args.seed,
        "seed_files": args.seed_file, "lang": args.lang, "with_links": not args.no_links,
    }
    (out_dir / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    wiki = client(args.lang)

    print("1) collecting titles")
    titles = titles_from_config(wiki, config)
    (out_dir / "titles.txt").write_text("\n".join(sorted(titles)), encoding="utf-8")

    done = set(load_pages(pages_path))
    todo = [t for t in titles if t not in done]
    if args.limit:
        todo = todo[: args.limit]

    print(f"2) checking versions of {len(todo)} pages")
    items, seen = [], set(done)
    for title, meta in page_meta(todo, args.lang).items():
        if meta and meta["title"] not in seen:  # skip missing pages and redirects to pages we have
            seen.add(meta["title"])
            items.append((meta, titles[title]))

    print(f"3) fetching {len(items)} pages ({len(done)} already saved)")
    lock = threading.Lock()
    with pages_path.open("a", encoding="utf-8") as f:
        def save(rec):
            with lock:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
        count = fetch_many(wiki, items, not args.no_links, args.workers, save)

    print(f"done: {count} new pages -> {pages_path} (total {len(done) + count})")


if __name__ == "__main__":
    main()
