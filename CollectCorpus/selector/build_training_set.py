"""Split the approved training pages into paragraphs: the training data of the selector.

    python -m selector.build_training_set            (run from the CollectCorpus folder)

Reads the 20 training pages from selector/training_pages.csv (title, label, and the revision the current
model was trained on), downloads their raw text from Wikipedia, and splits it into paragraphs:
- a paragraph is one line of text inside a section (that's how Wikipedia's raw text separates paragraphs);
- heading lines ("== History ==") are not paragraphs, but give each paragraph its section;
- lines shorter than MIN_CHARS are skipped (list items, "See also" style lines);
- reference-type sections (References, See also, ...) are skipped entirely.
Every paragraph gets its page's label (1 = relevant, 0 = not relevant).

Writes to data/selector/:
    training_pages.json   - the raw text and revision of each page, so the training set can be rebuilt exactly
    paragraphs.csv        - one row per paragraph: page, label, section, text, war_terms, flag
`flag` marks paragraphs that look like they go against their page's label (a word-list heuristic),
for a manual review before training.
"""
import json
import re
import sys
from pathlib import Path

import pandas as pd

from wiki_client import api

sys.stdout.reconfigure(encoding="utf-8")

TRAINING_PAGES = "selector/training_pages.csv"
OUT_DIR = Path("data/selector")
MIN_CHARS = 50
SKIP_SECTIONS = {"References", "See also", "External links", "Further reading", "Notes", "Bibliography",
                 "Sources", "Citations", "Footnotes", "Explanatory notes", "Works cited"}
# Words that suggest a paragraph is about the war / military. Only used to flag paragraphs for review.
WAR_TERMS = re.compile(
    r"\b(war|wartime|invasion|invaded|military|troops|army|armed forces|missiles?|shell(ed|ing)|attacks?|"
    r"battles?|offensive|counteroffensive|occupation|occupied|soldiers?|drones?|front ?line|brigades?|"
    r"regiments?|battalions?|artillery|tanks?|airstrikes?|strikes?|siege|captured|casualties|killed|"
    r"wounded|ceasefire|defen[cs]e|defenders|fighting|combat|weapons?|munitions?|ammunition|"
    r"Russo-Ukrainian|Wagner|separatists?)\b", re.I)


def approved_pages(path=TRAINING_PAGES):
    """[(title, label), ...] of the training pages."""
    df = pd.read_csv(path)
    return list(zip(df.title, df.label.astype(int)))


def fetch_raw(title, lang="en"):
    """Raw text + revision id of the page, in one request."""
    data = api(lang, prop="extracts|revisions", explaintext=1, rvprop="ids", titles=title, redirects=1)
    page = data["query"]["pages"][0]
    return {"title": page["title"], "revid": page["revisions"][0]["revid"], "content": page.get("extract", "")}


def split_paragraphs(content):
    """[(section path, paragraph), ...] following the rules in the module docstring."""
    out, path, skip = [], [], False
    for line in content.split("\n"):
        line = line.strip()
        heading = re.match(r"^(=+)\s*(.*?)\s*=+$", line)
        if heading:
            level = len(heading.group(1)) - 1          # "== X ==" is level 1
            path = path[:level - 1] + [heading.group(2)]
            if level == 1:
                skip = heading.group(2) in SKIP_SECTIONS
            continue
        if not skip and len(line) >= MIN_CHARS:
            out.append((" > ".join(path) or "(intro)", line))
    return out


def build(path=TRAINING_PAGES, out_dir=OUT_DIR, reuse=None):
    """reuse: an earlier training_pages.json; pages found there keep that text (same revision as before)."""
    pages = approved_pages(path)
    print(f"{len(pages)} approved pages: {sum(l for _, l in pages)} relevant, {sum(1 - l for _, l in pages)} not relevant")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cached = json.loads(Path(reuse).read_text(encoding="utf-8")) if reuse else {}

    raw, rows = {}, []
    for title, label in pages:
        if title in cached:
            page = {"title": title, "revid": cached[title]["revid"], "content": cached[title]["content"]}
        else:
            page = fetch_raw(title)
        raw[page["title"]] = {"label": label, "revid": page["revid"], "content": page["content"]}
        for i, (section, text) in enumerate(split_paragraphs(page["content"])):
            terms = len(WAR_TERMS.findall(text))
            rows.append({"page": page["title"], "label": label, "paragraph": i, "section": section,
                         "text": text, "chars": len(text), "war_terms": terms,
                         # goes against the page label? relevant page without war words, or the opposite
                         "flag": (label == 1 and terms == 0) or (label == 0 and terms >= 2)})

    (out_dir / "training_pages.json").write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
    df = pd.DataFrame(rows)
    df.to_csv(out_dir / "paragraphs.csv", index=False, encoding="utf-8-sig")

    summary = df.groupby(["label", "page"]).agg(paragraphs=("text", "size"), flagged=("flag", "sum"))
    print(summary.to_string())
    print(f"\ntotal: {len(df)} paragraphs ({(df.label == 1).sum()} relevant / {(df.label == 0).sum()} not), "
          f"{df.flag.sum()} flagged for review")
    return df


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pages", default=TRAINING_PAGES, help="csv of training pages (title, label)")
    ap.add_argument("--out", default=str(OUT_DIR), help="output folder")
    ap.add_argument("--reuse", default=None, help="earlier training_pages.json to take unchanged pages' text from")
    args = ap.parse_args()
    build(args.pages, args.out, args.reuse)
