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

Records saved before the `content` field existed get it here (one request per page, only for
pages that didn't change; changed pages are re-downloaded whole anyway).

Every change is appended to data/<name>/changes.jsonl.
Don't run this while build_corpus.py is running on the same corpus.
"""
import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from build_corpus import corpus_dir, fetch_many, load_pages, titles_from_config
from wiki_client import client, page_meta, raw_content

sys.stdout.reconfigure(encoding="utf-8")

CHECKPOINT = 200  # when adding raw content to older records, save after every this many pages


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


def try_raw_content(title, lang):
    """raw_content(), but one failing page doesn't stop a long run: returns None and prints why."""
    try:
        return raw_content(title, lang)
    except Exception as e:
        print(f"  ! {title}: {e}")
        return None


def write_pages(pages, path):
    """Rewrite pages.jsonl atomically (through a temp file), so a crash can't leave it half-written."""
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for rec in pages.values():
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def update(name, dry_run=False, skip_new=False, workers=4):
    """Compare saved revids with Wikipedia and re-download only what changed (see module doc)."""
    out_dir = corpus_dir(name)
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

    # Older records have no raw `content` (needed by export_corpus.py). For unchanged pages the
    # current text is the saved revision, so fetching it now is consistent.
    stale = {t for t, _ in changed} | {t for t, _ in renamed} | set(deleted)
    no_content = [t for t, rec in pages.items() if "content" not in rec and t not in stale and meta[t]]
    added = 0
    if no_content and not dry_run:
        print(f"  adding raw content to {len(no_content)} older records (saved every {CHECKPOINT}, so a stop loses little)")
        with ThreadPoolExecutor(min(workers, 2)) as pool:  # one request per page: go easy on the rate limit
            for i in range(0, len(no_content), CHECKPOINT):
                chunk = no_content[i:i + CHECKPOINT]
                for t, content in zip(chunk, pool.map(lambda t: try_raw_content(t, lang), chunk)):
                    if content is not None:  # failed pages stay without content; the next run retries them
                        pages[t]["content"] = content
                        added += 1
                write_pages(pages, pages_path)
                print(f"    {i + len(chunk)}/{len(no_content)}")

    new = []
    if not skip_new:
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
          f"new: {len(new) if not skip_new else 'skipped'}   backfilled: {backfilled}   "
          f"content added: {added}/{len(no_content)}")
    for t, m in changed[:20]:
        print(f"  ~ {t}  (edited {m['last_edited']})")
    for t, m in renamed:
        print(f"  > {t}  ->  {m['title']}")
    for t in deleted:
        print(f"  - {t}")
    for m, _ in new[:20]:
        print(f"  + {m['title']}")
    if dry_run:
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
        fetch_many(wiki, to_fetch, with_links, workers, lambda r: fetched.__setitem__(r["title"], r))

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

    write_pages(pages, pages_path)

    with (out_dir / "changes.jsonl").open("a", encoding="utf-8") as f:
        for entry in log:
            f.write(json.dumps({"time": now, **entry}, ensure_ascii=False) + "\n")
    print(f"\nsaved {len(pages)} pages; {len(log)} changes logged to changes.jsonl")



def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True)
    ap.add_argument("--dry-run", action="store_true", help="report changes, write nothing")
    ap.add_argument("--skip-new", action="store_true", help="don't look for / add new pages")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    update(args.name, args.dry_run, args.skip_new, args.workers)


if __name__ == "__main__":
    main()
