"""Export a corpus to the team's format: examples/DATA.json, {title: text}.

    python export_corpus.py --name ukraine_war_military

The text is each page's `content` field: the raw text exactly as Wikipedia returns it
("== Heading ==" lines, empty sections kept), which is what examples/DATA.json holds.
The file is written with json.dump defaults, like the original, so the next step (ApplyNER)
reads it without any change. The rich pages.jsonl (sections, coordinates, revisions) stays as it is.

Writes data/<name>/DATA.json.
"""
import argparse
import json
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
    print(f"wrote {path}: {len(data)} pages, {path.stat().st_size / 1e6:.1f} MB")
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True, help="corpus to export (data/<name>/)")
    ap.add_argument("--out-file", default="DATA.json")
    args = ap.parse_args()
    export_data_json(args.name, args.out_file)


if __name__ == "__main__":
    main()
