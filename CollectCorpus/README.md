# CollectCorpus

Builds the Wikipedia corpus that the rest of the pipeline (NER → graph & geocoding) runs on,
keeps it up to date without re-downloading everything, filters it to military content, and exports
`DATA.json` in exactly the format of `examples/DATA.json` for the next step.

```
build ──► update ──► filter ──► export
pages.jsonl (rich: sections, coordinates, revisions)  ──►  DATA.json ({title: text}, for ApplyNER)
```

**Walkthrough notebook:** [`CollectCorpus.ipynb`](CollectCorpus.ipynb) contains all the code of this folder,
file by file and function by function, with an explanation and a small demo after each part, plus the
corpus summary, a map of the pages with coordinates, and open questions. It runs on its own in Colab.
The scripts' `main()` only parses arguments and calls the same functions
(`build()`, `update()`, `summarize()`, `filter_corpus()`, `export_data_json()`).
[Open in Colab](https://colab.research.google.com/github/arielax-212/Corpus2GeoRAG/blob/main/CollectCorpus/CollectCorpus.ipynb).

**`DATA.json`** in this folder is the output for the next step: the filtered (military) corpus,
`{title: text}`, in exactly the format of `examples/DATA.json`. The richer `pages.jsonl` files
(all pages before filtering, with sections, coordinates, links and revisions) stay in `data/` and are not committed.

## Setup
```bash
pip install -r requirements.txt
```
Run all commands from this folder. Output goes to `data/<corpus name>/` (not committed to git).

## Scripts
| Script | What it does |
|---|---|
| `wiki_client.py` | Shared Wikipedia access (`wikipedia-api` + direct MediaWiki API calls, retry on HTTP 429). |
| `explore_page.py` | Inspect one page: `python explore_page.py Ukraine en` |
| `build_corpus.py` | Collect pages from category trees + seed pages. Resumable. |
| `update_corpus.py` | Incremental update: re-downloads only pages that changed on Wikipedia. |
| `filter_corpus.py` | Keeps military content, by the decisions in `filters/category_review.csv`. Writes a new corpus; the original is not touched. |
| `export_corpus.py` | Writes `DATA.json` (`{title: text}`) in exactly the format of `examples/DATA.json`. |
| `summarize_corpus.py` | Writes `summaries/<name>/summary.md` (overview) and `summary.csv` (one row per page). These are committed, so the team can see what's in the corpus without the data. |

## Building the Russia–Ukraine war corpus
```bash
python build_corpus.py --name ukraine_war --depth 2 \
  --category "Category:Russo-Ukrainian war (2022–present)" \
  --category "Category:Russo-Ukrainian war" \
  --category "Category:Military operations of the Russian invasion of Ukraine@3" \
  --category "Category:Military units and formations of the Russian invasion of Ukraine@3" \
  --category "Category:Military equipment of the Russian invasion of Ukraine@3" \
  --category "Category:Battles of the war in Donbas@0" \
  --category "Category:Oblasts of Ukraine@0" \
  --seed "Ukraine" --seed "Russia" --seed "Russo-Ukrainian war" \
  --seed "Annexation of Crimea by the Russian Federation" --seed "War in Donbas" \
  --seed-file seeds/team_DATA_json_titles.txt \
  --seed-file seeds/recommended_forces_battles_places.txt
```
- The whole tree is walked 2 levels deep. The three military branches go one level deeper (`@3`),
  because battles sit at level 3 (e.g. *Military operations → Battles → Battles by year → Battles … in 2022*).
  Taking the *whole* tree to depth 3 was tested and rejected: it adds ~1,700 mostly unrelated pages
  (sports leagues, TV episodes, sanctioned politicians).
- `seeds/team_DATA_json_titles.txt` holds the 897 titles of `examples/DATA.json`, so this corpus
  contains every page the team already works with.
- `seeds/recommended_forces_battles_places.txt` adds pages the corpus links to often but didn't contain:
  armed forces and units, War in Donbas battles (2014–2021), key places and historical background.
  Seed files ignore blank lines and lines starting with `#`.
- Category names are case-sensitive (`Russo-Ukrainian war`, lowercase "war").

## Keeping it up to date
```bash
python update_corpus.py --name ukraine_war --dry-run    # only report what changed
python update_corpus.py --name ukraine_war --skip-new   # refresh changed pages only
python update_corpus.py --name ukraine_war              # also add pages new in the categories
```
Every saved page has a revision id (`revid`). The update asks Wikipedia for the current `revid` of all
pages (50 per request, a few seconds in total) and re-downloads only the ones that differ.
Renamed pages are re-fetched under the new title, deleted pages are kept and marked `"status": "missing"`.
Every change is logged to `data/<name>/changes.jsonl`.

## Filtering to military content
```bash
python filter_corpus.py --name ukraine_war --out ukraine_war_military
python summarize_corpus.py --name ukraine_war_military
```
- `filters/category_review.csv` lists every category pages came from, with a Hebrew translation,
  a recommendation, the reason, and the `decision` (`keep` / `remove`) that the filter uses.
- A page from a removed category is still kept ("rescued") if it also belongs to a kept category
  (`source` only records the first category it was found in), or if it is a person with a military role
  (categories like *Russian admirals*, *Ukrainian military personnel …*).
- The report is in `summaries/<out>/`: `filter_report.md` (removed / rescued and why) and `removed.csv`.

## Exporting `DATA.json` for the next step
```bash
python export_corpus.py --name ukraine_war_military     # -> data/ukraine_war_military/DATA.json
```
The text of each page is its `content` field: the raw text exactly as Wikipedia returns it
(`== Heading ==` lines, empty sections kept), which is what `examples/DATA.json` holds. The file is written
with `json.dump` defaults like the original, so `ApplyNER` reads it as is.

## Output format: `data/<name>/pages.jsonl`
One JSON object per line, one line per page:

| Field | Meaning |
|---|---|
| `title`, `pageid`, `url`, `lang` | Page identity |
| `revid`, `last_edited` | Wikipedia revision (used by the update) |
| `fetched_at` | When we downloaded it |
| `source` | Category the page was found in, `seed`, or `seed-file:<file>` |
| `coordinates` | `{"lat", "lon"}` when Wikipedia has them, else `null` |
| `summary` | Intro text before the first heading |
| `sections` | `[{"path": "History > World War II", "level": 2, "text": ...}, ...]` |
| `text` | Full plain text of the page |
| `content` | The raw text in Wikipedia's own format (`== Heading ==`), used for `DATA.json` |
| `categories` | Topical categories (maintenance categories removed) |
| `links` | Titles of Wikipedia pages this page links to |

Tables, images and the infobox are not included.
