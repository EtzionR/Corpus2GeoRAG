"""Bring an existing corpus up to date without re-downloading everything.

    python update_corpus.py --name ukraine_war --dry-run    # only report what changed
    python update_corpus.py --name ukraine_war --skip-new   # refresh changed pages, don't add new ones
    python update_corpus.py --name ukraine_war              # full update

How it works:
1. Asks Wikipedia for the current revision id of every saved page (50 pages per request).
2. Re-downloads only pages whose revision id differs from the saved one.
3. Pages that were renamed are re-fetched under the new title; deleted pages are
   kept and marked "status": "missing".
4. Re-scans the categories from config.json and adds pages that are new there.

Records saved before revids were stored are backfilled: if the page wasn't edited since we
fetched it, it gets the current revid; otherwise it's re-downloaded.

Every change is appended to data/<name>/changes.jsonl.
Don't run this while build_corpus.py is running on the same corpus.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

from build_corpus import corpus_dir, fetch_many, load_pages, titles_from_config
from wiki_client import client, page_meta

sys.stdout.reconfigure(encoding="utf-8")


def parse_time(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def backfill(pages, meta):
    """Give old records (saved without revid) a revid, without extra requests:
    if the page's last edit is older than our fetch, what we saved *is* the current revision.
    Otherwise leave revid=None, so the page counts as changed and gets re-downloaded."""
    count = 0
    for title, rec in pages.items():
        if "revid" in rec:
            continue
        m = meta[title]
        if m and m["title"] == title and parse_time(m["last_edited"]) <= parse_time(rec["fetched_at"]):
            rec["revid"], rec["last_edited"] = m["revid"], m["last_edited"]
        else:
            rec["revid"] = None
        count += 1
    return count


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True)
    ap.add_argument("--dry-run", action="store_true", help="report changes, write nothing")
    ap.add_argument("--skip-new", action="store_true", help="don't look for / add new pages")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    out_dir = corpus_dir(args.name)
    pages_path = out_dir / "pages.jsonl"
    config = json.loads((out_dir / "config.json").read_text(encoding="utf-8"))
    lang, with_links = config["lang"], config["with_links"]
    wiki = client(lang)
    pages = load_pages(pages_path)
    print(f"loaded {len(pages)} pages from {pages_path}")

    print("1) checking versions")
    meta = page_meta(list(pages), lang)
    backfilled = backfill(pages, meta)
    for title, rec in pages.items():  # older records were saved without coordinates
        if "coordinates" not in rec:
            rec["coordinates"] = meta[title]["coordinates"] if meta[title] else None

    changed, renamed, deleted = [], [], []
    for title, rec in pages.items():
        m = meta[title]
        if m is None:
            if rec.get("status") != "missing":
                deleted.append(title)
        elif m["title"] != title:
            renamed.append((title, m))
        elif m["revid"] != rec.get("revid"):
            changed.append((title, m))

    new = []
    if not args.skip_new:
        print("2) re-scanning categories for new pages")
        titles = titles_from_config(wiki, config)
        known = set(pages) | {m["title"] for m in meta.values() if m}
        candidates = [t for t in titles if t not in known]
        seen = set(known)
        for t, m in page_meta(candidates, lang).items():
            if m and m["title"] not in seen:
                seen.add(m["title"])
                new.append((m, titles[t]))

    print(f"\nchanged: {len(changed)}   renamed: {len(renamed)}   deleted: {len(deleted)}   "
          f"new: {len(new) if not args.skip_new else 'skipped'}   backfilled: {backfilled}")
    for t, m in changed[:20]:
        print(f"  ~ {t}  (edited {m['last_edited']})")
    for t, m in renamed:
        print(f"  > {t}  ->  {m['title']}")
    for t in deleted:
        print(f"  - {t}")
    for m, _ in new[:20]:
        print(f"  + {m['title']}")
    if args.dry_run:
        print("\ndry run: nothing written")
        return

    # Re-download changed + renamed pages, add new ones
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    log = []
    to_fetch = [(m, pages[t]["source"]) for t, m in changed]
    to_fetch += [(m, pages[t]["source"]) for t, m in renamed if m["title"] not in pages]
    to_fetch += new
    old_revid = {t: pages[t].get("revid") for t, _ in changed}
    fetched = {}
    if to_fetch:
        print(f"\n3) fetching {len(to_fetch)} pages")
        fetch_many(wiki, to_fetch, with_links, args.workers, lambda r: fetched.__setitem__(r["title"], r))

    for t, m in changed:
        if m["title"] in fetched:
            pages[t] = fetched.pop(m["title"])
            log.append({"change": "updated", "title": t, "old_revid": old_revid[t], "new_revid": m["revid"]})
    for t, m in renamed:
        del pages[t]
        if m["title"] in fetched:
            pages[m["title"]] = fetched.pop(m["title"])
        log.append({"change": "renamed", "title": t, "new_title": m["title"]})
    for t in deleted:
        pages[t]["status"] = "missing"
        log.append({"change": "deleted", "title": t})
    for title, rec in fetched.items():  # what's left is new pages
        pages[title] = rec
        log.append({"change": "new", "title": title, "new_revid": rec["revid"]})

    # Rewrite atomically so a crash can't leave a half-written file
    tmp = pages_path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for rec in pages.values():
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    os.replace(tmp, pages_path)

    with (out_dir / "changes.jsonl").open("a", encoding="utf-8") as f:
        for entry in log:
            f.write(json.dumps({"time": now, **entry}, ensure_ascii=False) + "\n")
    print(f"\nsaved {len(pages)} pages; {len(log)} changes logged to changes.jsonl")


if __name__ == "__main__":
    main()
