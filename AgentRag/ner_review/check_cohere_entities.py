"""A right / wrong column for the NER team's Cohere output table, from the NER-level issues the agent
team found in the knowledge graph (GRAPH_TEAM_ISSUES.md, sections C1 and F). Duplicate names and
merging are the graph team's part and are not checked here.

Reads (never changes) ApplyNER/NER_output/model_evaluation/ground_truth/cohere_entities.parquet and,
for section titles, Graph_n_Geocoding/knowledge_graph.json.gz. Writes cohere_entities_checked.csv
next to this file: the same rows, without the paragraph text (Text) and the empty score column,
plus `check`: "right", or "wrong: <reason>". "right" means none of these checks found a problem; it
is not a human review.

    pip install pyarrow
    python AgentRag/ner_review/check_cohere_entities.py
"""
import csv
import gzip
import json
import re
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parents[2]
TABLE = REPO / "ApplyNER" / "NER_output" / "model_evaluation" / "ground_truth" / "cohere_entities.parquet"
GRAPH = REPO / "Graph_n_Geocoding" / "knowledge_graph.json.gz"
OUT = Path(__file__).resolve().parent / "cohere_entities_checked.csv"

# F1: sections that list article titles or books, not prose (the agent drops them too)
REFERENCE_SECTIONS = {
    "See also", "Sources", "Further reading", "References", "Bibliography", "Works cited", "Links", "Weblinks",
    "External links", "External links and further reading", "Literature", "Sources and literature",
    "Cited sources", "Related literature", "Footnotes", "Citations",
}
NON_LATIN = re.compile("[Ѐ-ӿ]")                       # Cyrillic
LANGUAGES = ("Ukrainian", "Russian", "Belarusian", "Polish", "Crimean Tatar", "Romanian", "Moldovan", "Georgian",
             "Lithuanian", "Latvian", "Estonian", "German", "Hungarian", "Czech", "Slovak", "Bulgarian", "Yiddish")
GLOSS_START = re.compile(r"\((?:" + "|".join(LANGUAGES) + r")\s*:")   # "(Ukrainian: ..., Russian: ...)"
GLOSS_LABEL = re.compile(r"\s*:")                               # "Russian" in "(Russian: ...)" is the label
WEB_DOMAIN = re.compile(r"^[\w.-]+\.[a-z]{2,4}$")              # "tv3.lt": a media outlet, not a common word
ABBREVIATION_END = re.compile(r"(\b[A-Z]\.|\b[A-Z][a-z]?\.|No\.|St\.|Jr\.|Sr\.|Co\.|Inc\.|Ltd\.)$")


def in_gloss(text: str, start: int, end: int) -> bool:
    """The original-language name inside a bracket like "(Ukrainian: ..., Russian: ...)" (or its
    romanized form), not the language label itself."""
    opened, closed = text.rfind("(", 0, start), text.rfind(")", 0, start)
    is_label = text[start:end] in LANGUAGES or GLOSS_LABEL.match(text, end)   # "Polish pronunciation: ..."
    return opened > closed and bool(GLOSS_START.match(text, opened)) and not is_label


def problems(row: dict, section: str | None) -> list[str]:
    word, text, start, end = row["word"], row["Text"], row["start"], row["end"]
    out = []
    if section in REFERENCE_SECTIONS:
        out.append(f"from a reference list ({section}), not prose: skip these sections (F1)")
    if in_gloss(text, start, end):
        out.append("original-language name in a bracketed gloss; the English name before it is already tagged (F2)")
    elif NON_LATIN.search(word):
        out.append("non-English text (e.g. a Russian/Ukrainian citation title or an inflected word) (F2)")
    elif (not any(c.isupper() or c.isdigit() for c in word) and any(c.isalpha() for c in word)
          and not WEB_DOMAIN.match(word)):
        # all lower case and no digits: "regiment", "terrorism"; unit names in lower case keep their number
        out.append("a common word, not a name (F1)")
    if word != word.strip():
        out.append("span starts or ends with a space (C1)")
    if word.endswith(".") and not ABBREVIATION_END.search(word):
        out.append("span includes the sentence's full stop (C1)")
    return out


def main() -> None:
    rows = pq.read_table(TABLE).to_pylist()
    with gzip.open(GRAPH, "rt", encoding="utf-8") as f:
        nodes = json.load(f)["nodes"]
    section = {(n["source"], n["index"]): n.get("title") for n in nodes if n.get("type") == "TEXT"}
    columns = ["entity_group", "word", "start", "end", "Source", "Index", "check"]
    reasons = Counter()
    with open(OUT, "w", encoding="utf-8-sig", newline="") as f:     # utf-8-sig: Excel shows Cyrillic correctly
        writer = csv.writer(f)
        writer.writerow(columns)
        for row in rows:
            found = problems(row, section.get((row["Source"], row["Index"])))
            reasons.update(found)
            row["check"] = "wrong: " + "; ".join(found) if found else "right"
            writer.writerow([row[c] for c in columns])
    wrong = sum(1 for r in rows if r["check"] != "right")
    print(f"{len(rows)} rows: {len(rows) - wrong} right, {wrong} wrong -> {OUT.relative_to(REPO)}")
    for reason, n in reasons.most_common():
        print(f"  {n:4}  {reason}")


if __name__ == "__main__":
    main()
