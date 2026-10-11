"""Load a single Wikipedia page and show which fields are available on it."""
import json
import sys
from pathlib import Path

from wiki_client import client, flatten_sections

sys.stdout.reconfigure(encoding="utf-8")


def explore(title, lang="en"):
    page = client(lang).page(title)
    if not page.exists():
        sys.exit(f"page not found: {title}")

    sections = flatten_sections(page.sections)
    print(f"title:       {page.title}")
    print(f"url:         {page.fullurl}")
    print(f"pageid:      {page.pageid}")
    print(f"summary:     {len(page.summary):,} chars (intro before the first heading)")
    print(f"text:        {len(page.text):,} chars (full text; tables and infobox are not included)")
    print(f"sections:    {len(sections)} (with text)")
    print(f"links:       {len(page.links)} (links to other Wikipedia pages)")
    print(f"backlinks:   (available via page.backlinks - pages that link here)")
    print(f"categories:  {len(page.categories)}")
    print(f"langlinks:   {len(page.langlinks)} (the same page in other languages)")
    he = page.langlinks.get("he")
    print(f"hebrew:      {he.title if he else '-'}")

    print(f"\n--- summary ---\n{page.summary[:500]}...")
    print("\n--- sections (path : chars) ---")
    for s in sections[:25]:
        print(f"  {s['path']} : {len(s['text']):,}")
    print(f"  ... ({len(sections)} total)")
    print(f"\n--- sample links ---\n{list(page.links)[:12]}")
    print(f"\n--- sample categories ---\n{list(page.categories)[:8]}")

    out = Path("data") / f"{lang}_{page.title.replace(' ', '_')}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({
        "title": page.title, "url": page.fullurl, "pageid": page.pageid, "lang": lang,
        "summary": page.summary, "sections": sections,
        "links": list(page.links), "categories": list(page.categories),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsaved -> {out}")


if __name__ == "__main__":
    explore(sys.argv[1] if len(sys.argv) > 1 else "Ukraine",
            sys.argv[2] if len(sys.argv) > 2 else "en")
