# ukraine_war_final

Selector v3 with EmbeddingGemma 2 (paragraph >= 0.7; accept >= 0.30 or >= 7 military paragraphs; reject < 0.10), then the two-signal rules: earlier-corpus pages (passed the military category filter) enter from the review zone (rule 1) or when rejected with >= 3 military paragraphs (rule 2); BFS pages accepted only by the 7-paragraph rule with < 10% military go to review (rule 3). Manual decisions: selector/manual_decisions.csv.

* Corpus (Gemma): **2285 pages** | the same with E5 v3: 2216 | in both: 2078 | only Gemma: 207 | only E5: 138
* Review zone kept aside: 418 pages
* Why pages entered (accept): share 1798, quantity 225, rule1 209, rule2 33

## Zones by origin (Gemma)

```
gemma_zone              accept  reject  review  training_related  training_unrelated  total
origin                                                                                     
BFS (collected before)      68     213      73                 0                   0    354
BFS (new)                  611    2587     345                 0                   0   3543
earlier corpus            1586     304       0                 0                   0   1890
training page                0       0       0                20                  20     40
total                     2265    3104     418                20                  20   5827
```
