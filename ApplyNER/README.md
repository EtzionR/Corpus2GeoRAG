# Corpus2GeoRAG — Named Entity Extraction

This document covers the notebook cells responsible for repository setup, corpus loading, preprocessing, model loading, entity extraction, and pushing results. Exploratory observation cells may appear between them. Graph construction is the next stage; it is not implemented by these cells.

## Part 1 — Guide for people

### 1. Where the data comes from

Two repositories have different roles:

| Role | Repository | How it is used |
| --- | --- | --- |
| Personal working fork | [idoschw3/Corpus2GeoRAG](https://github.com/idoschw3/Corpus2GeoRAG) | Clone or update the working checkout; push changes here. |
| Shared upstream and corpus source | [EtzionR/Corpus2GeoRAG](https://github.com/EtzionR/Corpus2GeoRAG) | Fetch the collector's current dataset and page-change CSV; target repository for collaboration through a pull request. |

**The corpus-loading cell fetches the collector's final dataset from EtzionR, regardless of which repository supplied the working checkout.** This applies to both local Windows and hosted Colab.

It retrieves these two files from the same upstream commit:

- `CollectCorpus/DATA.json.gz`
- `CollectCorpus/summaries/ukraine_war_final/pages_vs_2081.csv`

The upstream default branch is resolved through `git fetch ... HEAD`; the code does not hard-code its branch name. The cell prints the fetched commit, extracts both files with `git show`, loads and validates them, and replaces their local copies. Fetching the input files does not merge upstream code into the working branch.

The collector's final dataset (`DATA.json.gz`) is the **input**. The active NER result (`post_NER_final.parquet`) is **generated in this notebook**, using prior results from the working checkout when running incrementally. It is subsequently pushed to the personal fork by the push cell.

To use another update list, change `csv_relative_path` in the data-loading cell. The replacement CSV must correspond to the corpus being loaded and use the same page identifiers.

### 2. What each important cell does

The following is the logical execution order, rather than a claim about notebook cell numbers.

| Cell | Purpose and outputs |
| --- | --- |
| Imports and runtime setup | Imports the Python, Flair, PyTorch, pandas, and PyArrow dependencies. Sets `IS_COLAB_VM`; makes Colab `userdata` available in hosted Colab. This cell imports packages; it does not install them. |
| Clone or synchronize repository | Clones `idoschw3/Corpus2GeoRAG` if the checkout is absent. Otherwise sets `origin` to that fork and pulls the current branch with `--ff-only`. Sets `REPO_PATH` and changes the working directory to the repository root. |
| Load corpus and update list | Fetches both input files from EtzionR at one commit. Loads the compressed JSON into `data` and the CSV into `page_changes_df`. Prints page counts, line counts, source revision, and status counts. |
| Preprocess and audit cutoffs | Processes the entire current corpus. Produces `data_processed`, `paragraph_metadata`, and the cutoff audit dictionaries. Prints extraction and cutoff reports. |
| Load model | Sets `MODEL_Flair = "flair/ner-english-large"`, chooses CUDA when available and CPU otherwise, loads `SequenceTagger`, moves `ner_Flair` to `flair.device`, and prints the device. |
| Apply NER | Uses `model_new`, the update list, existing results, and saved page tracking to select pages. Runs batched inference, archives removals, saves active results and tracking, and creates `df_Flair` for notebook analysis. |
| Commit and push | Stages eligible changes, commits them, pulls/rebases the personal fork's current branch, and pushes to that fork. Uses local Git credentials on Windows or the `GITHUB_TOKEN` Colab Secret. |

The working directory is `Path.home() / "Corpus2GeoRAG"` on Windows and `/content/Corpus2GeoRAG` in Colab. These cells are designed for those two environments.

#### Preprocessing details

The preprocessing cell must receive the **full current dataset**, including unchanged pages. It:

- Splits each page into newline-separated strings.
- Recognizes headings enclosed by matching groups of at least two equals signs.
- Records level-2 headings as `title` and level-3 headings as `sub_title`; a new level-2 heading clears the subtitle. Other heading levels are excluded from paragraph text without updating these fields.
- Stops retaining content at the first heading normalized to `references` or `external links`, at any recognized heading level.
- Excludes heading lines, other lines beginning with `==`, and strings shorter than five characters.
- Preserves the text of retained paragraphs without trimming or rewriting it.
- Keeps every page key, even when its retained paragraph list is empty.

Content after the cutoff is inspected for additional sections at the cutoff's level or higher. This produces `cutoff_audit`, `suspicious_cutoffs`, and aggregate observations; it does not add discarded text back into the corpus. Those audit dictionaries are in memory and are not automatically saved by the supplied preprocessing cell.

#### Incremental and full runs

Set `model_new` at the top of the model-application cell:

| Setting | Behavior |
| --- | --- |
| `False` | Reuse previous results and process the pages requiring inference. An existing final Parquet is required. |
| `True` | Ignore the update list in the application cell and infer every current page with the currently loaded model. Replace the active entity results with the new results. |

On the **first incremental run**, when no matching page-tracking state exists in the legacy output, the CSV supplies the baseline. Pages marked `new` and present in the current corpus are processed; existing results for retained pages are reused. This assumes the old Parquet is a completed run with the same model against the CSV's comparison baseline. The CSV has no separate edited-content status, so this first migration cannot establish whether every retained paragraph is unchanged from the prior inference input.

On **subsequent incremental runs**, saved page snapshots identify newly present pages and changes to paragraph text or headings. Changed pages are processed again even when their CSV status is `unchanged`. Pages still labelled `new` in a reused CSV are skipped once their matching snapshots have been saved, including pages that yielded no entities.

The full current corpus determines which pages remain active. Removed pages' entity rows are excluded from the final output and archived before replacement. In incremental mode, a current page missing from the CSV's `new`/`unchanged` entries causes a validation error rather than being silently discarded.

Set `model_new = True` after changing the model, weights, or inference settings that require fresh predictions. The flag does not load or train a model. Set it back to `False` for later incremental runs. It only changes the application cell; the preceding data-loading cell still retrieves both input files.

Batch size is **32 on CUDA** and **1 on CPU**, based on the loaded model's device. Inference uses Flair `Sentence` objects with tokenization enabled and releases their embeddings after each batch.

### 3. Saved data and its format

All NER artifacts below are relative to `ApplyNER/NER_output/`.

| Artifact | Format | Purpose |
| --- | --- | --- |
| `post_NER_final.parquet` | Parquet with Zstandard compression | Authoritative active entity extraction output for the next graph-construction stage. |
| `post_NER_pages.json.gz` | Gzip-compressed JSON | Page snapshots, fingerprints, processing timestamps, and the run identifier paired with the final Parquet. |
| `page_changes_<stamp>.json` | UTF-8 JSON | Successful-run report containing selected, added, changed, and removed page lists and result counts. |
| `archive/removed_pages_<stamp>/removed_entities.parquet` | Parquet with Zstandard compression | Previous entity rows belonging to removed pages. |
| `archive/removed_pages_<stamp>/removed_pages.json.gz` | Gzip-compressed JSON | Removal timestamp, removed page identifiers, and available previous snapshots. |

`<stamp>` contains the run's UTC date, time, microseconds, and a short UUID suffix. The JSON `removed_at` value records the run time; it is not the time the original source page was deleted or excluded by the collector.

#### Active entity rows

There is one row per detected entity span. Multiple entities in one paragraph produce multiple rows sharing paragraph text and metadata. Pages or paragraphs with no detected entities have no placeholder rows.

| Column | Arrow type | Meaning |
| --- | --- | --- |
| `entity_group` | string | Label emitted by the loaded model. |
| `score` | float64 | Model-reported confidence score. |
| `word` | string | Exact slice `Text[start:end]`. |
| `start` | int64 | Zero-based start character offset within `Text`. |
| `end` | int64 | Exclusive end character offset within `Text`. |
| `Source` | string | Corpus page identifier; matches the input dictionary key and CSV `title`. |
| `Index` | int64 | Zero-based index within that page's filtered paragraph list. |
| `Text` | string | Full retained paragraph used for inference. |
| `title` | string, nullable | Most recent level-2 section heading. |
| `sub_title` | string, nullable | Most recent level-3 section heading under the current level-2 section. |

CSV `title` identifies a page. Output `title` identifies a section; use `Source` to join entity rows to the CSV. `Index` is not an original source line number and can change after preprocessing or page edits.

The input JSON maps page identifiers to full page-text strings. Its in-memory form is `data`. The update CSV has `title` and `status`, with status values `new`, `removed`, and `unchanged`.

#### Tracking and save behavior

`post_NER_pages.json.gz` stores version `1`, a `run_id`, and a `pages` mapping. Each page snapshot includes a SHA-256 fingerprint of its ordered paragraph text and headings, the paragraph records themselves, and `processed_at`. The initial imported legacy pages may have `processed_at: null` because their original inference time is unknown.

The final Parquet stores the matching run identifier in schema metadata under `incremental_flair_run_id`. Keep the active Parquet and its state file together across machines and Colab sessions.

Results are written to temporary files and validated before replacing the active files. If execution stops between replacing the Parquet and its state, the next run can recover the matching pending `.tmp` state. This is not per-batch checkpointing; an interrupted inference run must repeat its unfinished selection.

The code saves a run report even when nothing needs inference. It does not rewrite the active output/state pair for a completely unchanged incremental run. In full mode, `new_pages` and `changed_pages` in the report are empty because those classifications are bypassed; `processed_pages` lists the full selection.

### 4. Why removed pages are archived

**Removed-page archives are retained to help the RAG agent provide evidence-based feedback to the corpus collector. They must not be included in the graph.**

The archive lets a feedback workflow inspect what was previously extracted, identify potentially useful material lost during collection changes, and ask whether exclusions were intended. Removal alone does not prove a collector mistake or prove that the archived content remains current.

On the first incremental migration, the old entity-only Parquet may be the only historical content available. The archive then preserves its entity rows and associated paragraph text, while the page metadata marks `snapshot_unavailable: true`. A removed page with no entity rows may have only its identifier in the archive. After page snapshots have been established, later archives can also preserve the full previously retained paragraph text and headings.

Graph construction must load the explicit active file `post_NER_final.parquet`. It must exclude everything under `archive/`, temporary files, and run reports. If a graph already exists, its update process must also remove contributions from pages no longer active; updating the Parquet does not itself update a graph.

The notebook creates the evidence archives. The separate RAG feedback workflow and graph ingestion rules described here are downstream requirements, not functionality already implemented by these cells.

### 5. Publishing results for collaborators

The push cell targets `idoschw3/Corpus2GeoRAG` on the current working branch. It creates a normal commit when eligible changes exist, pulls with rebase, and pushes. A pull request into `EtzionR/Corpus2GeoRAG` is created separately.

The supplied push cell also:

- Adds a root-level nested `Corpus2GeoRAG/` exclusion and removes that nested path from Git tracking if present.
- Excludes files larger than `100 * 1024 * 1024` bytes, leaving their local bytes on disk. Already-tracked oversized files are removed from the index; prior Git history is not rewritten.
- Stages eligible additions, edits, and deletions throughout the checkout, including refreshed upstream inputs and generated outputs.
- **Unstages `.ipynb` changes and restores tracked notebook files on disk to their committed contents. Save notebook edits separately before running this cell; it does not publish those notebook edits.**
- Stops for unresolved merge/rebase state. Its special `.gitignore` conflict handling proceeds only when both versions are identical after trimming.

Generated outputs and archives reach the fork only if they are eligible for staging and fit the size limit. Check the push output before assuming the active output/state pair or an archive is available on another machine. Notebook changes need a separate publishing step. A GitHub web edit to this README must also be pulled into the working checkout before local edits to the same document are made.

## Part 2 — Contract for AI agents

### Repository and execution contract

1. Use `idoschw3/Corpus2GeoRAG` as the working fork and push destination. Use `EtzionR/Corpus2GeoRAG` as the corpus source and collaboration PR target.
2. Treat the repository setup and corpus loading as separate operations. A copy of the personal fork does not establish that its input corpus is current.
3. Retrieve the JSON and change CSV from the same fetched upstream commit. The current loading cell prints `upstream_commit`; the NER run report does not automatically record it. Preserve that printed revision in separately maintained provenance if needed; do not invent one from the run ID.
4. Preserve established notebook names: `REPO_PATH`, `input_path`, `changes_path`, `data`, `page_changes_df`, `data_processed`, `paragraph_metadata`, `MODEL_Flair`, `ner_Flair`, `BATCH_SIZE`, `df_Flair`, and `ner_run_report`.
5. Preprocess the complete current corpus. Restrict model inference only after establishing the full page inventory.
6. Use the explicitly loaded model. The supplied loader uses `flair/ner-english-large`. Do not silently substitute a model, infer that `model_new` loads one, or assume a DATE label is present.
7. Run one writer against the active output/state paths at a time. The cells do not implement concurrent-write coordination.

### Artifact consumption rules

| Artifact | Permitted role | Graph ingestion |
| --- | --- | --- |
| `post_NER_final.parquet` | Current entity evidence | Allowed input to the next stage. |
| `post_NER_pages.json.gz` | Synchronization state and current page inventory, including zero-entity pages | Not an entity table. May support bookkeeping. |
| `page_changes_<stamp>.json` | Run audit and graph-update planning | Not factual source content. |
| `archive/removed_pages_<stamp>/*` | Historical evidence for collector feedback | Excluded. |
| `*.tmp` | Pending write/recovery state | Excluded. |

Never recursively glob all Parquet files under `NER_output` for the graph: archives have a compatible entity schema and would otherwise silently reintroduce removed content. Archive exclusion is a consumer responsibility; the archive Parquet has no special graph-exclusion column.

### Identity, offsets, and reuse

- Join page-level data using `Source`, equivalent to input page keys and CSV `title`; preserve exact strings.
- Interpret `start:end` as Python character slicing within `Text`, with an exclusive end. These are not UTF-8 byte offsets.
- Treat `(Source, Index)` as a paragraph identifier only within the associated corpus snapshot. Paragraph indices are not stable across revisions.
- Preserve heading nulls and original paragraph text. Do not normalize text after inference without recalculating spans.
- Do not infer processing completeness from entity rows alone. Zero-entity and zero-paragraph pages are tracked in the state file.
- In the legacy first incremental run, reuse depends on the user's completed prior output and the CSV baseline. No previous complete content fingerprint exists to independently establish every reused paragraph's identity.
- On later runs, text/heading fingerprints control reuse. They do not identify model weights. A model change requires a full run through `model_new = True`.
- Treat the model score as its reported confidence, not a validated probability of factual correctness.

### Removal, feedback, and graph boundaries

1. Determine active membership from the full current processed corpus and the applicable tracking information. In incremental mode, validate the update list against current membership.
2. Archive removed entity rows and available prior snapshots before replacing the final output. Preserve existing dated archive directories.
3. Use archives only through a separately scoped feedback retrieval path. Historical archive evidence must not become current graph evidence or be silently included in normal graph-backed answers.
4. A collector-feedback item should identify the page, archive path, removal run time, supporting historical excerpts or entity spans, the reason for review, and a concrete question or suggested action for the collector. Clearly label uncertainty and unavailable text. This is a proposed feedback record structure, not a file the notebook currently emits.
5. Distinguish run time from the collector's actual removal time, and removed membership from factual invalidity. Do not assume removal was erroneous.
6. Do not reintroduce a page into active results or the graph merely because an archive contains it. Reintroduction requires acceptance into the current corpus and processing under the current workflow.
7. For an existing graph, reconcile removed and reprocessed pages so old nodes/edges or evidence contributions do not survive solely because of stale ingestion. No graph-deletion mechanism is implemented in this notebook.

### Save, recovery, and publishing contract

- Incremental reuse requires the matching Parquet/state run identifier once tracking is present. Preserve the schema metadata and sidecar together.
- Recover a matching pending state when available. Do not label missing-state output as safely reusable. Full mode can rebuild tracking without a matching prior state, but unavailable historical snapshots remain unavailable.
- Temporary result checks verify row counts, schema, and state serialization; they do not establish NER accuracy or corpus completeness.
- Do not claim that the current code saves a model checksum, a complete environment specification, or upstream commit provenance in every output. It does not.
- Do not claim per-batch resume support, automatic PR creation, graph construction, or automatic collector feedback.
- Account for the push cell's repository-wide staging, size exclusions, notebook unstaging, and restoration of tracked notebook files. Do not rely on it to preserve uncommitted notebook edits.
- A successful model run is not proof of a successful push. A successful push does not mean all oversized or ignored artifacts were published, and does not mean the upstream PR was merged.
