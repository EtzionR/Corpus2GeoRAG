# CollectCorpus

Builds the Wikipedia corpus that the rest of the pipeline (NER → graph & geocoding) runs on,
and keeps it up to date without re-downloading everything.

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

## Building the Russia–Ukraine war corpus
```bash
python build_corpus.py --name ukraine_war --depth 2 \
  --category "Category:Russo-Ukrainian war (2022–present)" \
  --category "Category:Russo-Ukrainian war" \
  --category "Category:Military operations of the Russian invasion of Ukraine@3" \
  --category "Category:Military units and formations of the Russian invasion of Ukraine@3" \
  --category "Category:Military equipment of the Russian invasion of Ukraine@3" \
  --seed "Ukraine" --seed "Russia" --seed "Russo-Ukrainian war" \
  --seed "Annexation of Crimea by the Russian Federation" --seed "War in Donbas" \
  --seed-file seeds/team_DATA_json_titles.txt
```
- The whole tree is walked 2 levels deep. The three military branches go one level deeper (`@3`),
  because battles sit at level 3 (e.g. *Military operations → Battles → Battles by year → Battles … in 2022*).
  Taking the *whole* tree to depth 3 was tested and rejected: it adds ~1,700 mostly unrelated pages
  (sports leagues, TV episodes, sanctioned politicians).
- `seeds/team_DATA_json_titles.txt` holds the 897 titles of `examples/DATA.json`, so this corpus
  contains every page the team already works with.
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
| `categories` | Topical categories (maintenance categories removed) |
| `links` | Titles of Wikipedia pages this page links to |

Tables, images and the infobox are not included.
