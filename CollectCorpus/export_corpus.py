"""Export a corpus to the team's format: examples/DATA.json, {title: text}.

    python export_corpus.py --name ukraine_war_military

The text is each page's `content` field: the raw text exactly as Wikipedia returns it
("== Heading ==" lines, empty sections kept), which is what examples/DATA.json holds.
The file is written with json.dump defaults, like the original, so the next step (ApplyNER)
reads it without any change. The rich pages.jsonl (sections, coordinates, revisions) stays as it is.

Writes data/<name>/DATA.json, and DATA.json.gz: the same file compressed (9 MB instead of 28 MB), small enough for
GitHub. Read it with:  json.load(gzip.open("DATA.json.gz", "rt", encoding="utf-8"))
"""
import argparse
import gzip
import json
import shutil
import sys

from build_corpus import corpus_dir, load_pages

sys.stdout.reconfigure(encoding="utf-8")


def export_data_json(name, out_file="DATA.json"):
    """pages.jsonl -> data/<name>/DATA.json in the exact format of examples/DATA.json."""
    pages = [p for p in load_pages(corpus_dir(name) / "pages.jsonl").values() if p.get("status") != "missing"]
    no_content = [p["title"] for p in pages if "content" not in p]
    if no_content:
        raise ValueError(f"{len(no_content)} pages have no `content` (e.g. {no_content[:3]}); "
                         f"run update_corpus.py on the source corpus first")
    data = {p["title"]: p["content"] for p in pages}
    path = corpus_dir(name) / out_file
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f)
    gz = path.with_name(path.name + ".gz")
    with path.open("rb") as f_in, gz.open("wb") as raw, gzip.GzipFile(path.name, "wb", fileobj=raw, mtime=0) as f_out:
        shutil.copyfileobj(f_in, f_out)        # mtime=0: the same content always gives the same .gz file
    print(f"wrote {path}: {len(data)} pages, {path.stat().st_size / 1e6:.1f} MB ({gz.name}: {gz.stat().st_size / 1e6:.1f} MB)")
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True, help="corpus to export (data/<name>/)")
    ap.add_argument("--out-file", default="DATA.json")
    args = ap.parse_args()
    export_data_json(args.name, args.out_file)


if __name__ == "__main__":
    main()
