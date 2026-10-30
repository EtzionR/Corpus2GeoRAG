# `DATA.json.gz` – the Russia–Ukraine war corpus (military focus)

**Version:** 2026-10-30 · **2,285 English Wikipedia pages** · 26.8M characters (4.2M words) ·
`DATA.json.gz` 9.2 MB (28 MB uncompressed; GitHub doesn't take the uncompressed file)
**Replaces:** the 2026-10-26 upload (2,081 pages) and the earlier `DATA.json` (2026-10-18, 1,602 pages)

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
`summaries/ukraine_war_final/summary.csv`; why each page is in or out: `summaries/ukraine_war_final/zones.csv`.

## What is in it
| | Pages |
|---|---|
| From the earlier corpus (category trees + seed pages, filtered to military categories) | 1,586 |
| New, from the BFS expansion (pages linked from at least 10 corpus pages) | 611 |
| Collected before and removed by the category filter, now accepted by their text | 68 |
| Selector training pages marked as related by hand | 20 |
| **Total** | **2,285** |

By title alone (a rough count): about 680 military units and formations, 160 weapons, ships and aircraft,
95 strikes and attacks, 90 battles and offensives; the rest are mostly commanders and soldiers, places
(cities, oblasts, buildings), organizations and events of the war.

| Page size (characters) | < 1K | 1K–5K | 5K–20K | 20K–50K | > 50K |
|---|---|---|---|---|---|
| Pages | 164 | 1,030 | 725 | 247 | 119 |

Compared with the `DATA.json` of 2026-10-18 (1,602 pages): 1,496 kept, **789 added**, **106 left**
(104 rejected by the selector, 2 selector training pages marked as not related).

## How the pages were chosen
1. **Candidates (5,827 pages):** the earlier corpus (1,910), the pages one link away from it (BFS, depth 1,
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
3. **Two signals.** The share score is low for long pages where the war is one part (cities, organizations,
   people), so pages of the earlier corpus - which passed the military category filter, an independent signal -
   enter when the text is at least partly military, and BFS pages (no category signal) are held to a stricter rule:
   | Rule | Pages |
   |---|---|
   | Accepted by the selector: score ≥ 0.30 | 1,798 |
   | Accepted by the selector: ≥ 7 military paragraphs | 225 |
   | Rule 1: earlier-corpus page in the review zone → enters | 209 |
   | Rule 2: earlier-corpus page rejected but with ≥ 3 military paragraphs → enters (e.g. Kyiv, Donetsk, Sevastopol) | 33 |
   | Rule 3: BFS page accepted only by the 7-paragraph rule but < 10% military → review zone (e.g. International Space Station) | (38 out) |
   | Selector training pages marked as related | 20 |
4. **Manual decisions** are recorded in `selector/manual_decisions.csv` and applied on every rebuild (none yet).
   The 418 "review" pages are kept aside with their full text.

## Quality
The selector, tested on 2,842 pages it was never trained on, against the earlier category-filter labels:
| | EmbeddingGemma 2 (used) | E5 (multilingual-e5-large) |
|---|---|---|
| AUC (page score) | 0.868 | 0.864 |
| "accept" pages that are related | 92.3% | 92.3% |
| Related pages accepted | 1,344 | 1,267 |
| Speed (sec per 1,000 paragraphs, T4 GPU) | 20.9 | 33.3 |

The same corpus built with E5 (same rules) has 2,216 pages (2,078 in common); the pages only one model lets in are
listed in `summaries/ukraine_war_final/compare_e5.csv`.

## Known limitations
* **Borderline pages are in.** 467 pages entered by rules 1–2 or by the 7-paragraph rule alone; a few are only
  loosely military (e.g. Oleksandr Usyk, 2026 Druzhba pipeline dispute). They are listed for a manual check, weakest
  first, and can be removed one by one (`python -m selector.add_reviewed`).
* **Not included:** the 418 review pages (some are clearly military), and related pages linked from fewer than
  10 corpus pages.
* **The 611 pages added by the expansion** (and 2 training pages) have only their text in `pages.jsonl`: no sections,
  categories or coordinates. `DATA.json` is not affected.
* English Wikipedia only; text as of October 2026 (most pages downloaded 2026-10-05 to 2026-10-19).

## Rebuilding
```bash
python -m selector.build_final_corpus     # -> data/ukraine_war_final/DATA.json + DATA.json.gz (scores from Colab, see README)
python -m selector.add_reviewed           # after marking decisions in review_pages.xlsx / cleanup_pages.xlsx
python summarize_corpus.py --name ukraine_war_final
```
