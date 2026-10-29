# ukraine_war_final

Selector v3 with EmbeddingGemma 2 (paragraph >= 0.7; accept >= 0.30 or >= 7 related paragraphs; reject < 0.10). Only accept enters; review is kept aside (review_pages.xlsx).

* Corpus (Gemma): **2081 pages** | the same with E5 v3: 1953 | in both: 1807 | only Gemma: 274 | only E5: 146
* Review zone kept aside: 589 pages

## Zones by origin (Gemma)

```
gemma_zone         accept  reject  review  training_related  training_unrelated  סה"כ
origin                                                                               
דף אימון                0       0       0                20                  20    40
הרחבה (חדש)           643    2587     313                 0                   0  3543
הרחבה (נאסף בעבר)      74     213      67                 0                   0   354
קורפוס קיים          1344     337     209                 0                   0  1890
סה"כ                 2061    3137     589                20                  20  5827
```
