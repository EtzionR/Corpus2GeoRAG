"""Find new pages one link away from the corpus (BFS, depth 1) and download them for the selector.

    python -m selector.expand_bfs --min-links 10                 (run from the CollectCorpus folder)
    python -m selector.expand_bfs --min-links 10 --plan-only     (only count the candidates)

1. Candidates: every page the corpus links to (the `links` saved with each page), that is not in the corpus,
   is a real article (no Category:/Template:/... pages), and is linked from at least --min-links corpus pages.
2. Wikipedia resolves redirects and alternative names (50 titles per request): a link to "Russian invasion of
   Ukraine" is the same page as one we have, so it is dropped. Pages that no longer exist are dropped.
3. Pages we already collected and scored before (removed earlier by a filter) are not downloaded again:
   their score is in data/selector/eval_scores_v2.csv.
4. The rest are downloaded (raw text, one request per page) to data/expansion/<name>/candidates.jsonl,
   one page per line, appended as they arrive, so an interrupted run continues where it stopped.
The selector then scores candidates.jsonl on Colab (GPU).
"""
import argparse
import json
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from build_corpus import corpus_dir, load_pages
from selector.build_training_set import fetch_raw
from wiki_client import page_meta

sys.stdout.reconfigure(encoding="utf-8")

SOURCE = "ukraine_war_selected"     # the current corpus (DATA.json)
SEEN = "ukraine_war"                # every page collected so far, before any filter
SCORES = "data/selector/eval_scores_v2.csv"
NON_ARTICLE = re.compile(r"^(Category|Template|Wikipedia|Help|Portal|File|Module|Talk|User|Draft|Special|MOS|"
                         r"Book|TimedText|Image|Media)( talk)?:")


def candidates(min_links, skip_lists, source=SOURCE):
    """{canonical title: number of corpus pages linking to it} for new articles, after resolving redirects."""
    corpus = load_pages(corpus_dir(source) / "pages.jsonl")
    count = Counter(l for p in corpus.values() for l in set(p["links"]))
    titles = [t for t, n in count.items() if n >= min_links and t not in corpus and not NON_ARTICLE.match(t)]
    lists = [t for t in titles if t.startswith("List of")]
    if skip_lists:
        titles = [t for t in titles if not t.startswith("List of")]
    print(f"linked from >= {min_links} corpus pages, not in the corpus: {len(titles) + (len(lists) if skip_lists else 0)} "
          f"({len(lists)} 'List of' pages{', skipped' if skip_lists else ''})")
    print(f"resolving redirects for {len(titles)} titles ({len(titles) // 50 + 1} requests)...")
    meta = page_meta(titles)
    out = Counter()
    for t in titles:
        m = meta[t]
        if m is None:                         # page doesn't exist
            continue
        if m["title"] in corpus:              # a redirect / other name of a page we already have
            continue
        if skip_lists and m["title"].startswith("List of"):
            continue
        out[m["title"]] += count[t]
    print(f"after redirects: {len(out)} new pages "
          f"({len(titles) - len(out)} were other names of corpus pages, duplicates or missing)")
    return out


def plan(min_links, skip_lists):
    cands = candidates(min_links, skip_lists)
    seen = set(load_pages(corpus_dir(SEEN) / "pages.jsonl"))
    import pandas as pd
    scored = set(pd.read_csv(SCORES).title)
    reuse = {t for t in cands if t in seen and t in scored}
    todo = {t: n for t, n in cands.items() if t not in reuse}
    print(f"already collected and scored before (reuse their score): {len(reuse)} | to download: {len(todo)}")
    return todo, reuse


def download(todo, out_path, workers=2, limit=0):
    """Append {title, revid, links_from_corpus, content} per page; skips pages already in the file."""
    done = set()
    if out_path.exists():
        with out_path.open(encoding="utf-8") as f:
            done = {json.loads(l)["title"] for l in f if l.strip()}
    queue = [t for t in sorted(todo, key=lambda t: -todo[t]) if t not in done]   # most-linked first
    if limit:
        queue = queue[:limit]
    print(f"downloading {len(queue)} pages ({len(done)} already in {out_path})")
    start, ok, failed = time.time(), 0, 0

    def fetch(title):
        try:
            return title, fetch_raw(title)
        except Exception as e:            # one failing page doesn't stop the run; next run retries it
            return title, e

    with out_path.open("a", encoding="utf-8") as f, ThreadPoolExecutor(workers) as pool:
        for title, page in pool.map(fetch, queue):
            if isinstance(page, Exception):
                failed += 1
                print(f"  ! {title}: {page}")
                continue
            f.write(json.dumps({"title": page["title"], "revid": page["revid"], "links_from_corpus": todo[title],
                                "content": page["content"]}, ensure_ascii=False) + "\n")
            f.flush()
            ok += 1
            if ok % 100 == 0:
                rate = ok / (time.time() - start) * 3600
                print(f"  {ok}/{len(queue)}  ({rate:.0f} pages/hour, ~{(len(queue) - ok) / max(rate, 1):.1f} h left)")
    print(f"done: {ok} downloaded, {failed} failed, {time.time() - start:.0f}s")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min-links", type=int, default=10, help="linked from at least this many corpus pages")
    ap.add_argument("--keep-lists", action="store_true", help="also check 'List of ...' pages (skipped by default)")
    ap.add_argument("--plan-only", action="store_true", help="only count the candidates, download nothing")
    ap.add_argument("--limit", type=int, default=0, help="download at most N pages (a trial run)")
    args = ap.parse_args()

    todo, reuse = plan(args.min_links, skip_lists=not args.keep_lists)
    out_dir = Path("data/expansion") / f"links{args.min_links}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "plan.json").write_text(json.dumps({"min_links": args.min_links, "skip_lists": not args.keep_lists,
                                                    "to_download": todo, "reuse_scores": sorted(reuse)},
                                                   ensure_ascii=False, indent=1), encoding="utf-8")
    if not args.plan_only:
        download(todo, out_dir / "candidates.jsonl", limit=args.limit)


if __name__ == "__main__":
    main()
