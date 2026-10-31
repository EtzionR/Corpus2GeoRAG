# NER review: the Cohere output, checked

For the NER team. `cohere_entities_checked.csv` is your table
`ApplyNER/NER_output/model_evaluation/ground_truth/cohere_entities.parquet`, row for row, with one
extra column, `check`: `right`, or `wrong: <reason>`. The paragraph text (`Text`) and the empty
`score` column are left out; `Source` + `Index` identify the paragraph.

The checks are the NER-level issues the agent team found in the knowledge graph (section numbers
refer to [GRAPH_TEAM_ISSUES.md](../GRAPH_TEAM_ISSUES.md)). Duplicate names and merging are the graph
team's part and aren't checked. `right` means none of these checks found a problem; it's not a
human review.

| Reason | Rows | What it means |
|---|---|---|
| from a reference list (See also, Sources, References, Bibliography, Further reading, Footnotes) (F1) | 118 | The paragraph lists titles or books, not prose. The span may be fine; these sections shouldn't be NER input. |
| non-English text (F2) | 18 | Russian/Ukrainian text, mostly from citation titles, including inflected words (`Славянске` = "in Sloviansk"). |
| original-language name in a bracketed gloss (F2) | 15 | `(Ukrainian: Олександр Павенко, Russian: …)` and its romanized forms; the English name right before is already tagged. |
| a common word, not a name (F1) | 9 | `regiment`, `active army`, `terrorism`, `lat` / `code` / `la` (template leftovers). |

146 of 7,326 rows (2 %) are marked wrong; some have two reasons (Cyrillic text inside a "Sources"
section), so the counts above add up to more. The spans themselves are clean: every start/end matches
the word, nothing is invented, and no span cuts a word or carries a stray space or full stop.

To rebuild it: `pip install pyarrow`, then `python AgentRag/ner_review/check_cohere_entities.py`
from the repo root (it also reads the graph file, for section titles).
