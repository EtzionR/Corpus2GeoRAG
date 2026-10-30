# Pages to add to the corpus later

Checked on the final graph (2026-10-30, eb2c6be). Fifteen core places of the war have no article of
their own in the corpus. The corpus selector rejects them: their pages are long and mostly general
(geography, economy, history), so few paragraphs read as military. They are still in the graph as
places, mentioned in other articles' paragraphs; what is missing is their own article, which gives
short answers ("Where is Crimea?") their description.

| Page | Paragraphs that mention it in the graph | Selector: military paragraphs / page paragraphs |
|---|---|---|
| Russia | 11,945 | 2 / 147 |
| Donetsk Oblast | 2,834 | 2 / 30 |
| Crimea | 2,150 | 2 / 105 |
| Moscow | 1,411 | 1 / 233 |
| Odesa | 780 | 2 / 151 |
| Kharkiv Oblast | 561 | 2 / 45 |
| Kursk Oblast | 426 | 1 / 33 |
| Kursk | 387 | 0 / 55 |
| Belgorod Oblast | 370 | 2 / 36 |
| Dnieper | 311 | 1 / 45 |
| Belgorod | 293 | 1 / 41 |
| Kyiv Oblast | 241 | 1 / 65 |
| Melitopol | 213 | 2 / 63 |
| Odesa Oblast | 181 | 0 / 43 |
| Kerch Strait | 129 | 2 / 29 |

Next in line, if there is room: Poland (734), Bryansk Oblast (160), Chernihiv Oblast (144),
Mykolaiv Oblast (139), Zhytomyr Oblast (98). The full list of the 306 pages of the Oct 7 corpus that
are still out is in `DATA_TEAM_DROPPED_ARTICLES.csv` (local).

## How to add them

1. **Data team:** one line per page in `CollectCorpus/selector/manual_decisions.csv`
   (`title,decision,date`, decision `include`), then rebuild the corpus (`python -m selector.add_reviewed`).
2. **NER team:** run on the new pages (the notebook lists them as new pages and reuses the rest).
3. **Graph team:** geocoding and relations for the new entities (cached for the rest), then the graph.

The agent needs no change: a place's own article is found by its title when the graph loads.

## Why not take them from an older graph

The first Vr6 graph had these pages, but it came from another NER run: its paragraph ids clash with
the final graph's, its entities are named and geocoded differently, and its relations were computed
for another set of entities. Merging it in would mix two graphs and give duplicate places, so we
leave the final graph as it is.
