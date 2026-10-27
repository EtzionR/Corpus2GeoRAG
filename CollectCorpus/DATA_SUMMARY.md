# `DATA.json.gz` – the Russia–Ukraine war corpus (military focus)

**Version:** 2026-10-23 · **2,081 English Wikipedia pages** · 26.9M characters (4.2M words) ·
`DATA.json.gz` 9.3 MB (28 MB uncompressed; GitHub doesn't take the uncompressed file)
**Replaces:** the previous `DATA.json` (2026-10-18, 1,602 pages, 16.4M characters)

## Format
`DATA.json` compressed with gzip. Read it with:
```python
import gzip, json
with gzip.open("DATA.json.gz", "rt", encoding="utf-8") as f:
    data = json.load(f)          # {title: text}, the same dict as DATA.json
```
Inside, exactly the format of `examples/DATA.json`:
```json
{"100th Mechanized Brigade": "The 100th Mechanized Brigade is a ...\n\n\n== History ==\n...", ...}
```
One key per page (its Wikipedia title), the value is the page's raw text as Wikipedia returns it
(`== Heading ==` lines, empty sections kept). Per-page details (source, size, coordinates, link):
`summaries/ukraine_war_final/summary.csv`.

## What is in it
| | Pages |
|---|---|
| From the previous corpus (category trees + seed pages, filtered to military categories) | 1,344 |
| New, from the BFS expansion (pages linked from at least 10 corpus pages) | 643 |
| Collected before and removed by the category filter, now accepted by their text | 74 |
| Selector training pages marked as related by hand | 20 |
| **Total** | **2,081** |

By title alone (a rough count): about 660 military units and formations, 160 weapons, ships and aircraft,
95 strikes and attacks, 90 battles and offensives; the rest are mostly commanders and soldiers, places and
events of the war.

| Page size (characters) | < 1K | 1K–5K | 5K–20K | 20K–50K | > 50K |
|---|---|---|---|---|---|
| Pages | 161 | 913 | 628 | 239 | 140 |

Compared with the previous `DATA.json`: 1,321 pages kept, **760 added**, **281 left** (164 moved to the
review zone, 115 rejected, 2 selector training pages marked as not related).

## How the pages were chosen
1. **Candidates (5,827 pages):** the previous corpus (1,910), the pages one link away from it (BFS, depth 1,
   linked from at least 10 corpus pages; "List of" pages skipped; redirects resolved: 3,543 + 354 collected
   before) and the 40 selector training pages.
2. **The selector (v3)** decides from the text itself:
   ```
   page ─► paragraphs (≥ 50 characters) ─► EmbeddingGemma 2 vectors ─► logistic regression ─► probability per paragraph
        ─► a paragraph is "military" if its probability ≥ 0.7; page score = share of military paragraphs
        ─► accept  if score ≥ 0.30, or ≥ 7 military paragraphs (long pages with a military section)
           review  if 0.10 ≤ score < 0.30          reject  if score < 0.10
   ```
   Trained on 3,009 paragraphs of 40 hand-picked pages (20 related: battles, units, weapons, commanders, strikes;
   20 not: close in topic but not military, or military but another war). 61 paragraphs that contradicted their
   page's label were removed after cross-validation.
3. **Only "accept" is in `DATA.json`** (1,798 by the share rule, 263 by the 7-paragraph rule, plus the 20 related
   training pages). The 589 "review" pages are kept aside with their full text and can be added after a manual
   check (`python -m selector.add_reviewed`).

## Quality
Tested on 2,842 pages it was never trained on, against the earlier category-filter labels:
| | EmbeddingGemma 2 (used) | E5 (multilingual-e5-large) |
|---|---|---|
| AUC (page score) | 0.868 | 0.864 |
| "accept" pages that are related | 92.3% | 92.3% |
| Related pages accepted | 1,344 | 1,267 |
| Speed (sec per 1,000 paragraphs, T4 GPU) | 20.9 | 33.3 |

The same corpus built with E5 has 1,953 pages (1,807 in common); the pages only one model accepts are listed in
`summaries/ukraine_war_final/compare_e5.csv`.

## Known limitations
* **The 7-paragraph rule** lets in some very long pages that are mostly not military (e.g. International Space
  Station, Kosovo War, Royal Navy): 52 of the 263 pages it accepted are less than 10% military.
* **Not included:** the 589 review pages (some are clearly military, e.g. 15th Transport Aviation Brigade), and
  related pages linked from fewer than 10 corpus pages.
* **The 645 pages added by the expansion** (and 2 training pages) have only their text in `pages.jsonl`: no sections,
  categories or coordinates. `DATA.json` is not affected.
* English Wikipedia only; text as of October 2026 (most pages downloaded 2026-10-05 to 2026-10-19).

## Rebuilding
```bash
python -m selector.build_final_corpus     # -> data/ukraine_war_final/DATA.json + DATA.json.gz (scores from Colab, see README)
python summarize_corpus.py --name ukraine_war_final
```
