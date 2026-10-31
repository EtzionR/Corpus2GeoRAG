# Decision log: the GeoRAG agent

A running record of every design choice in the agent: the options we weighed, what we chose, why,
and later what actually happened. Kept for the end-of-project presentation, and so we can see
what worked, what didn't, and why.

**How to read an entry:** *Question* → *Options* → *Decision* → *Why* (with the evidence) →
*Status* (decided / proposed / revisit) → *Outcome* (filled in once we've measured it).

Grouped by part of the flow. Newest phase first.

---

## Phase 2: the agent loop on the Vr6 graph (from 2026-10-20)

### Data findings that drove phase 2

Measured on `knowledge_graph.json.gz` (Vr6), 2026-10-20:

- **Size:** 120,019 nodes (64,301 paragraphs, 55,718 entities) and 697,333 edges; 35.4 MiB
  compressed, 218 MiB of JSON.
- **The text is pointer-ready:** every relation record carries a paragraph id and character positions.
- **Hubs are huge:** Ukraine has 14,200 paragraphs (1.0 M words). Even Bakhmut has 42,806 words.
- **Structure shrinks text without blind cutting.** For Bakhmut: all relations 42,806 words →
  `ATTACKED` 7,603 → confidence ≥ 0.7 3,668 → the single sentence instead of the paragraph 865.
- **Every article's paragraph 0 is a summary** of about 53 words; 790 entities have their own article.
- **Events are articles, not nodes:** 196 event-style titles; 55 "Battle of / Siege of".
- **Data problems** (duplicates, wrong geocodes, noise) are listed in `GRAPH_TEAM_ISSUES.md`.

### Overall approach

**P2-1. Which graph?**
*Decision:* the Vr6 graph only. The phase-1 flow is retired; the UI reconnects through the README
once phase 2 works. *Why:* it's richer, covers far more of the corpus, and is now the main build.
*Status:* decided.

**P2-2. Who picks the tools: fixed routes or an LLM loop?**
*Options:* (A) a fixed route of tools per question type; (B) the LLM picks tools in a loop, as in phase 1.
*Decision:* A first, with B as the fallback for questions that fit no type. Compare A and B again
once we move to a paid model.
*Why:* A is cheap, behaves the same every run, and is testable; free models are unreliable at
choosing tools; B stays available for unusual questions.
*Status:* decided. *Outcome:* —

**P2-3. How many LLM calls per question?**
*Decision:* at most two, in a fixed order:
1. **Understand.** Reads only the question, never graph data. It returns a plan: question type,
   names, relation hints, keywords. Code then picks the route and tools from that plan.
2. **Write.** Reads the evidence the tools gathered and writes the answer.

Simple patterns ("Where is X?") skip the understand call, and a locations-only answer can use a
fixed template instead of the write call. So a question costs 0, 1 or 2 LLM calls, plus a tiny
disambiguation call in the rare case of genuinely different name candidates (P2-11).
*Why:* phase 1 used up to 7 calls per question (a loop). Fewer calls means cheaper, faster and
more predictable.
*Status:* decided (skipping the call for simple patterns: decided; the template answer: to try).

**P2-4. Test focus.**
*Decision:* questions 1–10 are mostly one type ("show the locations connected to X"). We test with
three of them standing in for the group (1: an entity with name variants; 3: an event article;
10: common neighbours) plus the four core types (11–14).
*Why:* to avoid spending test runs on near-duplicates. *Status:* decided.

### Storage and loading

**P2-5. How the agent reads the graph.**
*Options:*
- (a) Load the whole JSON into memory (NetworkX), as in phase 1.
- (b) Ask the graph team for a different format.
- (c) Convert the JSON once into our own SQLite database file and query it from disk.

*Measured (prototype, 2026-10-20):*

| | (a) in memory | (c) SQLite |
|---|---|---|
| Start-up | ~7 s on every app start | 4 ms |
| Memory | 1.1 GB | 23 MB for the whole process |
| Typical lookups | fast | 0.1–5 ms |
| One-time cost | none | an 8 s conversion per machine (needs about 1 GB of memory once), producing a 193 MiB file |

*Recommended:* (c). The agent would build `AgentRag/data/graph.sqlite` automatically the first
time it runs, and rebuild it whenever the graph team's `.gz` changes. The file would be gitignored:
at 193 MiB it's over GitHub's 100 MB file limit anyway.
*Why recommended:* it works on modest UI machines, keeps working as the graph grows, and needs
nothing from the graph team. Their JSON stays the single source of truth. Python includes SQLite,
along with its map-area index (R-tree) and word search (FTS5), so there's nothing extra to install.
Entity unification will shrink the graph somewhat, but most of the bulk is the 723 K relation
records and 275 K mentions, so we shouldn't count on it getting small.
*Decision (2026-10-20):* **(a) for now**: load into memory, as before. The memory question goes to
all the teams first. All graph access sits behind one module, so switching to (c) later only
changes that module.
*Status:* deferred. Revisit after the teams discuss memory limits on the UI machines.
*Outcome:* —

**P2-6. Geometry library.**
*Options:* shapely (suggested in the graph README), or plain Python.
*Decision:* plain Python for distance, point-in-polygon, WKT parsing and polygon simplification.
(A scan over all 9,722 geocoded places takes 8 ms, so no spatial index is needed while the graph
is in memory.)
*Why:* Windows Smart App Control is on on the agent owner's PC and blocks shapely's compiled
files. Reinstalling doesn't help, and turning Smart App Control off is effectively permanent.
UI machines may have the same setting.
*Status:* decided.

### ① Understand

**P2-7. What "understand" produces.**
*Decision:* a structured plan (`QueryPlan` in `planner.py`): question type, names (as typed, plus the
normal spelling), concepts, relations (only the graph's vocabulary), keywords, map area and radius,
place filter, what the answer needs, time words, follow-up, and in scope or not. It's built three
ways, in order: the fast path (code patterns, no LLM), one LLM call, or the keyword fallback.
*Status:* built (Part 1). See P2-21 to P2-30 for the rules and the run results.

**P2-8. Off-topic questions.**
*Options:* reject them; or answer anyway with a clear label.
*Decision:* never reject. If the graph has no data, give a normal LLM answer with the disclaimer
**"No data from the graph — answer from the LLM only."** The result is marked `grounded: false`.
*Why:* a plain refusal is unhelpful; the label keeps corpus facts and model knowledge apart.
*Status:* decided.

**P2-9. Language.** English only for now; Hebrew is on the wish list. *Status:* decided.

**P2-10. Dates.** Read from the sentence text and let the LLM reason about them. The entity team
is working on proper dates. *Status:* decided.

**P2-21. Concepts ("the head of the Russian military").**
*Question:* the graph has no node called "Russian military". How much outside knowledge may the LLM
use to turn the concept into something the graph has?
*Options:* (a) candidate organizations and places only, with the answer coming from the graph; (b)
candidate people too (Gerasimov, Shoigu), with the graph used only to confirm.
*Decision (2026-10-20):* (a). The answer itself (the person) must come from the graph's relations.
Every answer will also report how many graph nodes and sentences it was built from, so we can see
when the graph, not the LLM, is doing the work. Zero nodes means the labelled LLM-only answer (P2-8).
*Why:* the point of the project is that the corpus shapes the answer. If the LLM names the person,
the graph only confirms what the LLM already believes.
*Effect on what we can answer:* a concept the LLM can't map to an organization or place the graph
knows can't be answered from the graph. That is deliberate.
*Status:* decided. *Outcome:* runs 1–3: q11 consistently gives organization candidates (General
Staff, Ministry of Defence, Russian Armed Forces) and no people.

**P2-22. The map selection versus a named place.**
*Decision:* a named place wins. The map selection is used when the question refers to it ("here",
"this area"). For an area question that names its own place ("drone attacks in Kharkiv"), the area
comes from that place's own polygon in the graph. Places the answer talks about get their locations;
if it talks about Kyiv and Moscow, both appear on the map.
*Status:* decided; catalogued so we can check the answers once Part 5 exists.
*Outcome:* run 1 broke this (v11 used the map box, because the LLM called it an area question); fixed
in code. Runs 2–3: correct.

**P2-23. Radius.** A distance written in the question wins, then the radius the UI sends, then a
1 km default. If nothing is found, the search widens step by step and says so (Part 3).
*Status:* decided. *Outcome:* q12 reads "500m" from the text in every run; v10 gets the 1 km default.

**P2-24. Compound questions** (5: "Ukrainian cities connected to Russian military operations", 9:
"Ukrainian locations connected to Russian military commanders") go to the LLM tool-loop fallback
for now, rather than getting their own question types. *Status:* decided.

**P2-25. How much chat history the understand step sees:** the last 3 questions plus the numbered
places each answer showed, not whole answers. *Status:* decided for now; revisit after full runs.
*Outcome:* "tell me about number 2" resolved to Soledar in all runs where the LLM answered.

**P2-26. The prompt's examples are not the test questions.**
*Decision:* the examples in the understand prompt use different questions with the same patterns
("Who shelled Kharkiv?" rather than "Who attacked Mariupol?"). A test fails if a test question ever
appears in the prompt.
*Why:* found during the first rewrite. The first prompt happened to use test questions as examples,
which would make the test score look better than real use.
*Status:* decided.

**P2-27. Guards against the LLM supplying the answer.**
*Found in run 2:* asked "major battles", the LLM listed battles from its own memory. Asked "Ukrainian
cities…", it listed six cities. Asked "…the same country", it listed Belarus, the US and Germany. The
graph would then only have confirmed the LLM's own picks.
*Decision:* enforced in code, not left to the prompt:
1. Every name must appear in the question.
2. Several names from one phrase are the LLM's own list and are dropped.
3. A description ("Russian military commanders") becomes a concept, not a name.
4. When the question asks for places, the LLM may not propose places as candidates. It can still
   name the subject (an organization).

The prompt also says so, but the code is what we rely on.
*Status:* decided. *Outcome:* run 3: q4 and q10 come through without injected answers.
*How we know these came from the LLM's memory:* at this step the LLM sees only the question, never
graph data, so names that aren't in the question can only come from its training. The saved plan
shows it: each of the six cities was recorded with the user's text "Ukrainian city". The names
weren't false (Kyiv is a Ukrainian city), but they weren't from the corpus either. That's a
grounding problem, not a truth problem.
*Why it appeared in run 2 and not run 1:* between the runs the prompt was substantially rewritten
(rules plus six examples, including an invitation to give "candidates"), *and* the free router chose
different models. With both changing at once we can't say which caused it, which is one reason the
guard is in code. It also showed that runs didn't record which model answered; the harness now
does (P2-32).

**P2-28. When the LLM fails.**
*Decision:* if the model returns no usable structure, retry once (the free router picks another model
per call). On a rate limit or network error, don't retry: go straight to the keyword fallback. A
question never fails at this step.
*Outcome:* run 2: 2 of 21 LLM calls returned no structure. Run 3: the retry recovered v1. The
keyword fallback carried the 9 questions that hit the rate limit.

**P2-29. Place filters.** "Ukrainian cities" → country Ukraine, kind city. Carried in the plan for
Part 3 to apply. *Why:* run 3 lost "Ukrainian cities" in q5; the original plan listed a place filter,
but it hadn't been built. *Status:* decided; unit-tested, not yet run live.

#### Part 1 results across runs (free model, `eval/run_understand.py`, 27 questions)

Results are in `eval/results/2026-10-20_*_understand.json`.

| Run | What changed before it | Went right | Went wrong |
|---|---|---|---|
| 1 | first version | 6 of 14 project questions on the fast path (no LLM); typos fixed (Kharkov, dnipro); follow-ups resolved | "who did what" mistyped (v4, v5); q11 missed `LEADS`; coordinates as keywords (q12); v11 used the map box over a named place; v12 got an invented relation; v6 lost Bakhmut; v7 (off-topic) returned no structure |
| 2 | prompt v2 (rules + non-test examples, P2-26); code rules for the map, keywords and the fallback | all the run-1 problems above fixed | **the LLM supplied answers** (q4, q5, q10) → P2-27; 2 calls returned no structure; latency up to 53 s |
| 3 | P2-27 guards; one retry (P2-28) | no injected answers; retry recovered v1 | q5 lost "Ukrainian cities" → P2-29; q14 typed as a follow-up with no history → fixed in code; **the daily free quota ran out** after ~19 calls (see P2-30) |

**P2-30. The free tier allows 50 requests per day.**
*Found in run 3 (2026-10-20):* OpenRouter's key info shows `is_free_tier: true` and a free-model
limit of 50 requests per day (55 used that day). One run of the 27 questions costs about 20 requests
for understand alone, and a full pipeline run will cost about 40.
*Effect:* about one full test run per day.
*Options:* fewer test calls (run subsets; cache LLM answers for unchanged prompts), or raise the
daily limit on the OpenRouter account.
*Decision (2026-10-20):* the agent owner added $10 of credit. The key is no longer free tier; the
free-model limit is now 1,000 requests per day, and the key's $10 spending cap is a hard stop. Also:
finish the test harness first (P2-32), then test through it, and don't spend carelessly.
*Status:* decided.

**P2-31. Which models, and when.**
*Facts (OpenRouter price list, 2026-10-20, USD per 1M tokens, input / output):*

| Model | Price | Note |
|---|---|---|
| `openrouter/free` | $0 / $0 | picks a different model per call, so runs can't be compared |
| `google/gemini-2.5-flash-lite` | $0.10 / $0.40 | Gemini 2.0 Flash is no longer listed; this is its price class |
| `openai/gpt-4o-mini` | $0.15 / $0.60 | |
| `openai/gpt-4.1-nano` | $0.10 / $0.40 | |
| `google/gemini-2.5-flash` | $0.30 / $2.50 | stronger writer, pricier output |

*Cost per call, measured:* one understand call reads about 2,700 tokens (mostly the instructions).
With `gpt-4o-mini` that's about $0.0008 per question, under 2 cents for all 27. A full pipeline run
(understand + write) is estimated at $0.02–0.03 on the cheap models, so $10 is roughly 300 full runs.
*Proposal:*
- compare `openrouter/free`, `gpt-4o-mini` and `gemini-2.5-flash-lite` on step ① (under $0.05);
- compare again for step ⑤ once it exists;
- the app's default becomes one hardcoded constant per step (e.g. `UNDERSTAND_MODEL`, `WRITE_MODEL`),
  still never read from `.env` or the caller.

*Status:* proposed, awaiting your choice.

**P2-32. The test harness** (`eval/harness.py`, `eval/run.py`).
*Decision:* every test run goes through the harness, which:
- records every LLM call: the step, the model that actually answered, tokens, cost, time
  (`llm_calls.py`). The record is also part of the plan, so the app can report it too.
- caches answers in `eval/cache/` (gitignored), keyed by model, structure and exact messages.
  Re-running unchanged questions is free, and changing the prompt asks again automatically. Failed
  answers are never cached.
- caps the cost of each run (default $0.25): it refuses to start if the estimate is over the cap,
  and stops if real spending reaches it, saving partial results. The free router is never capped.
- writes a JSON file and a readable Markdown report per run, and can compare two runs question by
  question.
- takes `--model` to compare models. **The app itself still always uses its hardcoded constant;**
  only the harness can override it.

*Why:* the owner asked for the harness before any paid testing, and a free-router run doesn't say
which model answered.
*Status:* built and tested (offline tests, plus one free run where the second pass came 100 % from
the cache).
*Revised (2026-10-20), after the agent owner's challenge:* reusing saved answers by default would
freeze weak free-model answers, and with the free router it hides the variety we want to see. Now
**every run asks fresh by default**. Answers are still saved, but reused only when a run asks for it
(`--reuse HOURS`), and only answers from that window, e.g. repeating the four core questions during
one working session while tuning a later step. Only LLM answers are ever saved; graph steps always
re-run.

**P2-36. Question sets.** The 27 questions are the project's 14 plus 13 variants (v1–v13) added to
stress the understand step. Runs now pick a named set: `core4` (q11–q14), `focus7` (q1, q3, q10 +
core4, the default, per P2-4), `project14`, `understand_stress` (v1–v13), `all`.

**P2-37. The trace report.**
*Question:* can the agent owner follow one question through the whole flow, the way the notebook did?
*Decision:* every run also writes `<run>_trace.md`. For each question it shows, step by step:
- the inputs
- ① the path taken (fast path / LLM / fallback), the exact message sent, the LLM's raw answer
  before code rules, the rules code applied, and the plan passed on
- then one section per later step (resolve, retrieve, evidence, write, result), marked "not built
  yet" until it exists

The instructions sent to the LLM appear once at the top, with a version hash.
*Why:* the table report compares runs but can't show the reasoning chain; the trace can.
*Status:* built (format to be approved). *Outcome:* first core4 trace, 2026-10-20 18:18.

**P2-31 (update): model order.** Agreed sequence: build on the free router; once the full flow
works, try `google/gemini-2.5-flash` to find weak spots; after improving, try `openai/gpt-4o-mini`;
maybe a stronger model at the final stage. The paid comparison of step ① alone is held: it says
more once the whole flow runs.

*Observed, core4 trace 2026-10-20:* q11 on `nvidia/nemotron-3.5-lightning:free` gave no `LEADS`
relation and one organization (earlier runs: `LEADS` plus 2–3 organizations), and took 48 s
producing 3,540 output tokens (the model reasons at length before answering). It shows why one
model per comparison run matters.

### ② Resolve names

**P2-11. Name variants and ambiguity.**
*Options considered:* (a) answer for the strongest match and offer the rest as "did you mean";
(b) just answer for the closest match; (c) let the LLM decide what the user means.
*Decision (2026-10-20):* combine them, in three steps:
1. **Code merges variants of the same thing silently:** `SAME_AS` between close names, locations
   with identical coordinates, and normalized spellings. For example, the 21 Zelenskyy spellings,
   Russia / Russian Federation, or Wagner / Wagner Group. Most "ambiguity" in this graph is this
   kind and never reaches the LLM.
2. **For genuinely different candidates, the LLM decides.** A small call gets the question plus
   one line per candidate (type, address, or the first sentence of its article) and returns the
   one meant, e.g. Georgia the country vs. the US state.
3. **Safety net:** if the LLM can't tell, answer for the strongest candidate in the graph. The
   other candidates always come back as `did_you_mean` options.

*Why:* the duplicates are real today (`GRAPH_TEAM_ISSUES.md` A1–A3) and unification is coming but
not here yet. The question's context usually tells which candidate is meant, and the LLM is good
at reading context. The call is tiny (about 100 words in, one id out), and the "did you mean"
options let the user correct a wrong pick at no cost.
*Status:* decided. *Outcome:* — (to watch: how often step 2 actually runs, and how often the
LLM picks wrong)

**P2-33. Catching names the LLM missed** (scanning the question for exact graph names).
*Decision (2026-10-20):* skipped for now; kept on the ideas list (end of this file) in case results
need it. *Why:* "the Russia–Ukraine war" would add Russia and Ukraine to many questions; not worth
the noise until we see it matter.

**P2-34. What the LLM sees when picking between genuinely different candidates (P2-11).**
*Decision (provisional):* one line per candidate: the place type and address for places; the first
sentence of the entity's own article, plus the article title, for others.
*Why provisional:* the agent owner wants to see full printed runs first. Some question types (e.g.
"give me information about…") may need more than a sentence. To be planned properly once end-to-end
runs exist.
*Status:* provisional.

**P2-35. Suspicious geocodes.**
*Decision:* mark a location `uncertain` when its place type is road, amenity, shop, tourism or
building and its importance is low (e.g. Donbas → a street in Skopje, importance 0.04). It stays on
the map, flagged, not hidden.
*Status:* decided for now; logged so it can be challenged later.

**P2-38. Variant groups: the rules** (`graph_index.py`; built 2026-10-20).
Checked against the real graph before writing:
- **(a) Same normalized spelling** (case, unicode spaces, trailing ".", UK/US spelling such as
  defence/defense).
- **(b) `SAME_AS`, but only between names that share a distinctive word or are spelled almost
  alike.** Only 299 of the graph's 2,048 `SAME_AS` pairs share any word, and junk nodes are linked to
  real ones (`.` is `SAME_AS` NATO, Reuters, the United Nations).
- **(c) Locations with identical coordinates and the same place type** (Kyiv / Kiev / Київ, Bakhmut /
  Artemivsk).
- **(d) Organizations that differ only by words like Group / PMC:** Wagner, Wagner Group, PMC Wagner
  and Wagner PMC merge (9 names, 623 texts); Wagner Orchestra and PMC Wagner Center don't.
- **(e) People:** the same surname with a similar first name (Volodymyr / Volodomyr Zelenskyy), or the
  same first name with a similar surname (Zelensky / Zelenskyy), excluding the female form (-a).
- **(f) A bare surname joins a person only if that person has 80 % of its texts.** "Gerasimov" →
  Valery Gerasimov (~88 %), "Shoigu" → Sergei Shoigu, "Putin" → Vladimir Putin; "Ivanov" stays alone,
  split across dozens of people.

*Result:* 55,718 entities → 50,498 groups; 3,899 groups have 2+ names. Zelenskyy: 16 spellings,
1,506 texts (was 947 for the main spelling).
*Known imperfections, inherited from geocoding (rule c):*
- the Russia group includes "New Russia" (Novorossiya), placed on Russia's exact point
- the city of Dnipro's old names (Yekaterinoslav, Dnepropetrovsk, "Dnipro city") were geocoded onto
  the Dnieper river's point, so they group with the river, while "Dnipro" itself sits on the river
  near Chernihiv
- some oblasts share their city's point and type (Kharkov Oblast, Stanislav Oblast)

All reported to the graph team.
*Cost:* building the indexes takes ~6 s on top of the ~8 s load, once per app start.
*Status:* built; light by design, to shrink once the graph team's unification lands.

**P2-39. Name matching: the rules** (`resolver.py`).
*Decision:*
- Matching order: exact → normalized → all words present → fuzzy.
- Events are matched to article titles.
- The plan's spelling is tried first, then the user's own text.
- Concept candidates need a firm match (no fuzzy matching, no LLM pick).
- When several groups match: the strongest wins if it has 3× the texts of the next; otherwise the
  LLM picks (P2-11); "did you mean" alternatives are always kept.

*Bug found by the tests and fixed (2026-10-20):* the word match and the fuzzy match first checked only
the *distinctive* words. So "Russian Air Force" matched "Russian Armed Forces", and "Ministry of
Defence of the Russian Federation" matched on "russian" alone. Now **every** word of the query
(except connectors like "of", "the") must be present (word match) or have a similar word (fuzzy).
Also, a word that appears in more than 25 different groups is too vague to count as a match.
*Status:* built.

**P2-40. Filling in obvious relation hints with code** (e.g. "head of" → `LEADS` when the LLM left the
hint empty).
*What it is:* not adding relations to the graph. The plan's `relations` field is a search hint saying
which of the graph's existing relation types to look at. Without it, step ③ looks at all relation
types for the entity: broader and noisier, but not wrong.
*Decision (2026-10-20):* not now. Whether a missing hint hurts answers only shows once step ③ exists.
On the ideas list.

#### Part 2 results (focus7, free router, 2026-10-20 18:44; `eval/results/2026-10-20_184411_*`)

| Question | ② found | Observation |
|---|---|---|
| q1 Zelenskyy | group `Zelenskyy`, 16 spellings, 1,506 texts | variant grouping works |
| q3 Battle of Bakhmut | article "Battle of Bakhmut" | events resolve to articles |
| q10 Russia + Ukraine | `Russia` (11,093 texts), `Ukraine` (14,211) | hubs: step ③ must rank and budget |
| q11 head of the Russian military | candidates Russian Armed Forces (349), Russian Ministry of Defense (45, despite the spelling difference) | the LLM didn't suggest **General Staff**, the organization whose `LEADS` points to Gerasimov, so success depends on the candidate list (see ideas) |
| q13 Dnipro | `Dnipro` · geocoded as a **river** near Chernihiv; own article exists | step ③/④ can use the article ("Ukraine's fourth-largest city") to flag the conflict |
| q12, q14 | answered by `liquid/lfm-2.5-2.6b:free`, a tiny model: keywords "500m", "Ukraine"; q14 lost `ATTACKED` | the free router's quality is a lottery |

**P2-41. Pin one strong free model, with the router as backup?**
*Found:* in this run the free router answered with four different models in five calls, including a
2.6-billion-parameter one; plan quality followed the model. Pinned free models, tested on core4
(step ① only, $0):
- `nvidia/nemotron-3-ultra-550b-a55b:free`: all three LLM plans clean (q11 `about` + `LEADS` +
  organizations; q12 `area` 500 m; q14 `area_topic` + `ATTACKED` + drone), 5–16 s
- `google/gemma-4-31b-it:free`: rate-limited
- `nvidia/nemotron-3-super-120b-a12b:free`: "model not found", although listed

*Proposal:* `MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"`, with OpenRouter's fallback list
(`openrouter/free`) for when it's busy or gone. Still free, but much more consistent.
*Status:* proposed; your decision (it changes the hardcoded constant).

**P2-12. Fuzzy matching.**
*Decision:* fuzzy matches must share a distinctive word, never only generic words.
*Why:* phase 1 matched "Russian Armed Forces" to "Ukrainian Air Force" on generic words.
*Status:* decided.

### ③ Retrieve

**P2-13. Relation confidence.**
*Options:* ignore it; rank by it; filter by it.
*Decision (2026-10-20):* start with the best data. A typed relation (`ATTACKED`, `CONTROLS`,
`LEADS`, …) is trusted only at **confidence ≥ 0.7**. Records below 0.7 aren't thrown away: the
two names really are mentioned together, and only the relation label is doubtful. So they count as
"mentioned together" (like `CO_OCCURS_WITH`) and are ranked after the confident records.
*Why:* the classifier is right 60–65 % of the time (graph README). A sample already shows wrong
labels at 0.47 ("Telegram ATTACKED Bakhmut") and 0.66.
*Status:* decided for now; revisit with the labelled samples (`analysis/confidence_samples.md`).
*Outcome:* —

**P2-14. Tools return pointers, not text.**
*Decision:* every tool returns ranked items with paragraph pointers and character positions. Text
is chosen later, in the evidence step. *Status:* decided.

**P2-42. Tools and routes** (`graph_tools.py`, `retrieve.py`, `geo.py`; built 2026-10-20).
*Decision:* the tools are plain functions over the in-memory graph; the agent's code walks the
graph, never the LLM.

| Tool | Returns |
|---|---|
| `entity_records` | every text record linking an entity's group to others, with pointers |
| `aggregate` | records grouped by counterpart and ranked: a confident typed record counts 3, a mention 1; with each counterpart's role (acts / acted on) |
| `connected_places` | the geocoded places an entity is linked to |
| `places_near` | places within a distance |
| `places_within` | places inside a polygon |
| `shape_of` | a place's own polygon |
| `parents` | the `INSIDE` chain |
| `mentions` | the paragraphs that mention a group |
| `keyword_spans` | where a topic word occurs in a paragraph |
| `article_places` | the places an event article mentions |
| `common_neighbors` | what is linked to several entities at once |
| `lead_pointer` | an article's summary paragraph |

There is one fixed route per question type: `place_lookup`, `area`, `area_topic`, `about`/`relation`,
`entity_places`, `event_places`, `event_list`, `common`. Everything found is kept and counted,
nothing is cut, and step ④ decides what the LLM reads. Each tool call is logged with its parameters
and what it found, so the trace shows the graph traversal step by step. Geometry is plain Python
(P2-6).
*Status:* built; 28 offline tests.

**P2-43. Topic words and relations in area questions.**
*Found (focus7 run, 2026-10-20 19:09):* q14 "Drone attacks in this bounding box" returned 505 places.
The keyword "attack" matches almost every paragraph in a war corpus, and the `ATTACKED` relation was
*adding* places of its own.
*Decision:* generic topic words (attack, strike, war, battle, operation, …) are ignored when a more
specific word is given ("drone"). When topic words exist, they decide which paragraphs count, and
the relation only ranks places. With no topic words at all, the relation records are the topic.
*Outcome:* q14 went from 505 to 192 places, all with paragraphs mentioning drones.

#### Part 3 results (focus7, pinned free model, 2026-10-20 19:09; `eval/results/2026-10-20_190957_*`)

| Question | ③ found | Observation |
|---|---|---|
| q1 Zelenskyy's places | 500 places; top: Ukraine, Russia, US, Kyiv | true but uninformative: countries are linked to everyone. Places specific to him rank lower (White House: 30 of its 108 paragraphs). **Ranking choice open (P2-44).** |
| q3 Battle of Bakhmut | 76 places from the article; Bakhmut first | as intended |
| q10 Russia + Ukraine | nothing: the backup model typed it `other` (no route) | the pinned model was busy for 3 of 5 calls; the free-router backup answered and quality dropped |
| q11 head of the Russian military | 541 people/organizations, 259 places | **the plan had no `LEADS` hint this time, so everything connected came back.** General Staff, Gerasimov and Shoigu are in the top 10 but buried. Evidence for P2-40. |
| q12 within 500 m of Kyiv's centre | 7 places: Maidan, Kyiv, Khreshchatyk Street… | as intended |
| q13 Dnipro | 1 place (the river point near Chernihiv) plus its article's summary | the summary says it's a big city in the east, so step ④/⑤ can expose the conflict |
| q14 drone attacks in the Donbas box | 505 → **192 places** after P2-43 | as intended |

**P2-44. How to rank the places linked to an entity** (open, for the agent owner).
*Options:* (a) most mentioned together (today; countries win); (b) most *specific*: links relative to
how often the place appears overall (White House, Kyiv over Ukraine, Russia); (c) confident typed
relations first (`VISITED`, `LOCATED_IN`), then mentions.
*Status:* open.

**P2-40 (update).** The q11 run above is the evidence asked for: without the `LEADS` hint the route
returns everything linked to the Russian military, with the answer buried. Filling in obvious hints
in code ("head of" → `LEADS`) now looks worth doing; awaiting the owner's decision.

**Gemini 2.5 Flash check (core4, steps ①–③, 2026-10-20 19:13; `eval/results/2026-10-20_191359_*`).**
- **Cost:** 3 LLM calls, **$0.0024** in total (estimate shown before the run: $0.0056, cap $0.10).
- **Speed:** **0.8–1.8 s** per LLM question, against 6–44 s on the free models.
- **Plans:** clean for all three LLM questions; q12 and q14 found the same places as the free run.
- **q11 found nothing, although its plan was perfect** (`about`, `LEADS`, candidates Russian Armed
  Forces and Ministry of Defence of the Russian Federation, both found in the graph). See P2-45.

**P2-45. Why q11 finds no leader, and what to do** (open, for the agent owner).
*Found (2026-10-20):* every `LEADS` record around the Russian military has low confidence. General
Staff → Valery Gerasimov: 0.42 and 0.47; → Gerasimov: 0.41; others: Nikolai Makarov 0.43,
Oleksandr Turchynov 0.43 (Turchynov is Ukrainian: "General Staff" mixes countries). Russian Armed
Forces: one record, Yeltsin, 0.47. With the 0.7 threshold (P2-13) all of these count only as
"mentioned with", so a `LEADS` search returns nothing. Separately, the LLM rarely names General Staff,
though it's the second most linked organization to Russian Armed Forces.
*Options, as a fallback only when a relation search finds nothing:*
- (a) relax: use lower-confidence records of the requested relation, clearly labelled "low
  confidence" so the answer can say so;
- (b) expand: also search the organizations most linked to the candidates (reaches General Staff);
- (c) both, (b) then (a).

*Trade-off:* (a) brings back exactly the records the 0.7 threshold was meant to keep out (the
classifier is right 60–65 % of the time), but labelled. (b) can drift to related but wrong
organizations.
*Status:* open.

**P2-45 (decided 2026-10-20): option (c).** When a relation search finds nothing: (b) search the 3
organizations most linked to the targets, then (a) accept typed records down to confidence 0.4,
marked `low_confidence`. The evidence step marks them, so the answer can say so. Built in `retrieve.py`
(`_relation_records`); tested with an expansion case (Russian Armed Forces → General Staff →
Gerasimov) and a low-confidence case.

**P2-44 (decided 2026-10-20): (c) with (b) as tiebreaker.** Places linked to an entity are ranked by
confident relations that put it *at* the place (`VISITED`, `LOCATED_IN`, `BORN_IN`, `DIED_IN`,
`FLED_TO`; for organizations `BASED_IN`, `OPERATES_IN`, `ATTACKED`, `CONTROLS`). Ties go by specificity
(the share of the place's paragraphs that link to the entity), then by volume.
*Interpretation to challenge:* `STATED_ABOUT` ("quoted about Ukraine") and `LEADS` ("holds office of
Ukraine") don't count as being at a place. Counting them would keep countries on top (Zelenskyy:
`STATED_ABOUT` Ukraine ×164, `LEADS` ×28).
*Outcome:* q1 now starts with White House, Kyiv, Washington (it started with Ukraine, Russia, US).

**P2-46. q11 replaced** (decided 2026-10-20): "Who is the president of Ukraine and the president of
Russia?". It's an easier question that returns two people, and the graph clearly has them. The old
q11 ("Tell me about the head of the Russian military") stays as variant v14: a hard case for
concepts and low-confidence `LEADS` (P2-45).
*First run (2026-10-20 19:45):* it failed for a planning reason. The pinned model read "the
president of Ukraine" as a *concept*, with candidates "President of Ukraine" and "Office of the
President of Ukraine" (title-like organizations in the graph), and gave **no `LEADS` hint**. The
route then listed what's linked to the Office of the President, topped by Andriy Yermak, who heads
that office. "President of Russia" isn't a node at all. The plan that would work is: entities
Ukraine, Russia; relation `LEADS` (in the test graph that finds Zelenskyy, Poroshenko and Putin).
That's P2-40 again.

### ④ Evidence (built 2026-10-20)

**P2-47. How the evidence pack is built** (`evidence.py`).
*Decision:*
- Levels slide with size: place lookups get only places and summaries; a result whose whole
  paragraphs fit in half the budget gets whole paragraphs; otherwise sentences (the sentence(s)
  around each pointer's entity positions, at most 3 in a row).
- Summaries (articles' first paragraphs, cut at about 120 words) come first.
- Then a **round-robin** fill: every item gets one passage before any gets a second, and items are
  ordered records → entities → places for "who" questions, places first otherwise.
- Everything is numbered (places `[n]`, summaries `[Ln]`, sentences `[Sn]`) for citing.
- Low-confidence relations are marked.
- What doesn't fit the budget is counted, and kept for a "show more" page.

*Fixed during the first run:* a cap of 3 passages per item left q12 (7 places) at 529 of 2,000 words.
The round-robin already keeps things fair, so the cap now only stops at 50; q12 fills its budget
(1,997 words).
*Status:* built; 10 offline tests. The exact text the LLM will read is shown in the trace.

#### The amounts (focus7, 2026-10-20 19:46; `eval/results/2026-10-20_194656_*`)

What each question could feed the LLM, in words (a word is about 1.3 tokens):

| | places | pointers (available / total) | summaries | all sentences | all paragraphs | included at 2,000 |
|---|---|---|---|---|---|---|
| q1 Zelenskyy's places | 500 | 1,988 / 3,453 | 0 | 61,110 | 78,166 | 1,999 |
| q3 Battle of Bakhmut | 76 | 229 / 250 | 51 | 6,252 | 7,167 | 1,997 |
| q10 (wrong type from the backup model) | 0 | 0 | 0 | 0 | 0 | 0 |
| q11 presidents (wrong plan, see P2-46) | 55 | 249 / 249 | 101 | 5,236 | 4,010 | 1,993 |
| q12 within 500 m | 7 | 122 / 2,345 | 0 | 3,760 | 14,247 | 1,997 |
| q13 Dnipro | 1 | 0 | 63 | 0 | 0 | 63 |
| q14 drones in the box | 192 | 746 / 814 | 0 | 20,176 | 33,419 | 1,999 |

*Reading it:*
- At 2,000 words the LLM sees about 30 % of q3's sentences, 10 % of q14's and 3 % of q1's; the rest
  goes to paging.
- "All sentences" counts each pointer's sentence window separately, so overlapping windows in one
  paragraph can add up to more than the paragraph (q11).
- "Available" pointers are capped at 50 per item by step ③; "total" is what the graph holds.

*Cost at a 2,000-word budget:* about 2,700 tokens per answer, roughly $0.0008 on Gemini 2.5 Flash or
$0.0004 on GPT-4o mini. Context size isn't the limit (the models take 128 K–1 M tokens); answer
quality and latency are.
*Status:* **budget open (P2-16): 2,000 words provisional**, for the agent owner to choose with this table.

**P2-48. Answer shapes** (discussed and decided 2026-10-21).
*The problem the owner raised:* the amounts table looked like "an insane amount of text". In fact
the LLM only ever gets the budget (2,000 words); the big columns are the size of the haystack. But
the concern was right in another form: **for list questions, text is the wrong vehicle.** The 2,000
words went on sentences about the top 20–30 places when the user asked for a list of 500, and a
bigger context wouldn't help ("lost in the middle").
*Decision:* code picks the shape of the answer from the question type (step ①) and the result size
(step ③). The user never chooses it and no extra LLM call is made; the user's wording still steers it
("tell me in detail" → explain). The shapes are the four archetypes made concrete:

| Shape | When | The LLM reads | Budget |
|---|---|---|---|
| **list** | places-of-X / event places / area / list of events / common, with more than 6 places | the top 10 places, each with a one-line *data* reason built by code (relation counts, paragraphs, share, distance), the region overview, at most 1 summary; **no corpus sentences** | 500 |
| **fact** | where is X; who leads/attacked X | relation sentences plus up to 2 summaries of the people found | 600 |
| **drilldown** | one person or organization at one place ("Zelenskyy in the White House") | only the records linking the two | 800 |
| **explain** | "tell me about", small results, "in detail" | summaries plus sentences (or whole paragraphs if small) | 2,000 |

Every place found still goes on the map (step ⑥), whatever the shape. The full amounts are still
measured, so we can see what each shape leaves out.

**P2-49. Region overview, nested** (decided 2026-10-21; `graph_tools.region_tree`).
*Decision:* for any result with more than 6 places, group them by country and region (oblast) using
the graph's `INSIDE` hierarchy, with counts. It's kept as a nested tree for the UI to draw, and
summarized in one line per country for the LLM ("Ukraine: 186 places — Donetsk 145, Luhansk Oblast
22, …"). Places with no larger region in the graph are counted separately. The UI README will explain
how to show it.
*Bug found on the first run and fixed:* a region's level was taken from an arbitrary member of its
name group, so "Donetsk" (displayed as the oblast) was treated as a city and dropped. Now it uses the
same member as the displayed point.
*Data issue found:* the hierarchy puts Kharkiv Oblast inside **Russia** (reported to the graph team).

**P2-49b. Drill-down route and follow-ups in the harness.** When a question pairs one person or
organization with one place, step ③ returns only the records linking the two. The harness can chain
a follow-up question to the previous one (`"follows"` in `questions.json`), passing its places as chat
history.
*Bug found and fixed:* the follow-up's target was added a second time when the question also named it,
so the drill-down didn't trigger (z2 returned 518 places). Now each group counts once.
*Outcome:* z2 "Tell me about Zelenskyy in the White House" → 30 linking records; the LLM reads 769
words of dated, focused sentences ("Zelenskyy met Trump on 28 February in the White House…").

**P2-50. Role questions** (decided 2026-10-21): "president / prime minister / head / leader /
commander / mayor / governor … of X" becomes X as a name, with `LEADS`, by a code rule in step ①, plus
one analogous prompt example ("prime minister of Poland", not a test question). "Head of the Russian
military" is left alone: "Russian military" is a description, so it stays a concept.
*Outcome:* q11 → Zelenskyy and Putin at the top, fact shape, 600 words, with Putin's summary.

**P2-51. q10 kept as it is** (decided 2026-10-21), so we can see what an odd or no-data answer looks
like with the disclaimer. Its fix is deferred (ideas list). This run it was typed `common` and found
1,656 shared places, with no "country" filter, because the plan didn't say "country".

**P2-46 (update): new questions** (2026-10-21):
- q15 "Show me Kyiv": a place lookup whose answer carries Kyiv's polygon (step ⑥)
- the Zelenskyy pair: z1 "Tell me about locations with Volodymyr Zelenskyy", then z2 "Tell me about
  Zelenskyy in the White House"

The default set is now `focus` (q1, q3, q10, q11–q15, z1, z2).

#### Amounts after the shapes (focus, 2026-10-21 11:10; `eval/results/2026-10-21_111010_*`)

| | shape | places | words the LLM reads (budget) |
|---|---|---|---|
| q1 Zelenskyy's places | list | 500 | 200 (500) |
| q3 Battle of Bakhmut | list | 76 | 134 (500) |
| q10 | list | 1,656 | 73 (500) |
| q11 presidents | fact | — | 600 (600) |
| q12 within 500 m | list | 7 | 91 (500) |
| q13 Dnipro | fact | 1 | 63 (600) |
| q14 drones in the box | list | 192 | 110 (500) |
| q15 Kyiv | fact | 1 | 82 (600) |
| z1 Zelenskyy's places | list | 500 | 200 (500) |
| z2 Zelenskyy in the White House | drilldown | 1 | 769 (800) |

Before the shapes, the list questions used the full 2,000 words each.

### ⑤ Write (built 2026-10-21)

**P2-52. How the answer is written** (`writer.py`).
*Decision:*
- The LLM reads exactly the evidence text of step ④ (shown in the trace), with a "FOUND BY" line
  saying how the places were found.
- It writes ONE answer in the shape named, citing places as `[3]` and passages as `[S2]` / `[L1]`;
  groups like `[S4, S10]` are allowed.
- **Code then checks every citation id**: ids that don't exist are removed and noted. Places discussed
  must be real; at most 3 suggested follow-ups, whole questions only.
- Nothing found, or off-topic: a short LLM-only answer starting with "No data from the graph — answer
  from the LLM only." (P2-8), marked `grounded: false`.
- One retry when the model skips the structure. A plain-text answer is used if it's usable (and still
  checked); if all else fails, a list answer falls back to a template built from the data lines.

*Model for testing:* `google/gemini-2.5-flash`, as the owner agreed. The free backup was flaky;
Flash answers in 1–6 s. A fresh run of the 10 focus questions through all 5 steps costs about
$0.012.

*Found in the first runs (2026-10-21) and fixed:*

| Found | Fix |
|---|---|
| Grouped citations like `[S4, S10, S14]` weren't checked at all | each id in a group is checked; a group keeps only its real ids |
| q11 typed `common` by Flash; the role rule didn't override that type, so the answer listed 1,656 places | the role rule now overrides every type except area types |
| q14: "192 places attacked by drones… Donetsk (12 attacks)", an overclaim; "12" was attack *records* in drone paragraphs | data lines say "ATTACKED in 12 records; 118 matching paragraphs", and the prompt says data lines are graph counts, not event counts |
| q1: the LLM chose "the strongest" by paragraph count (Ukraine, US), ignoring our ranking | the prompt says the list is already ordered strongest first |
| Flash sometimes answers in plain text instead of the structure (q14 fell to the template) | the raw text is now recorded in the call and used if usable |
| q14's list had no way to say what matched, so the model said "no passages about drone attacks" | the FOUND BY line ("places inside the map area whose paragraphs mention: drone") |
| the model wrote one section per shape (list, then drill-down, then explain) | "write ONE answer, in the named shape only" |
| a suggested follow-up was cut off ("What was the") | follow-ups must end with "?" or "." |

#### Part 5 results (focus, Gemini 2.5 Flash, 2026-10-21 11:29; `eval/results/2026-10-21_112914_*`)

All 10 answered; 0 citations removed; no fallbacks.

| | shape | answer, in short |
|---|---|---|
| q1 / z1 Zelenskyy's places | list | 500 places; strongest White House, Kyiv, Washington, UK; by region Ukraine 225, Russia 73, 117 elsewhere |
| q3 Battle of Bakhmut | list | 76 places; strongest Bakhmut, **Ukraine, Russia**, Soledar, Klishchiivka |
| q10 | list | 1,656 places (deferred, P2-51) |
| q11 presidents | fact | Zelenskyy, Ukraine; Putin, Russia since 2012 (and 2000–2008); cited |
| q12 within 500 m | list | 7 places; Maidan, Kyiv |
| q13 Dnipro | fact | "Ukraine's fourth-largest city… eastern Ukraine… 391 km southeast of Kyiv" |
| q14 drones in the box | list | 192 places with drone paragraphs; Donetsk, Avdiivka, Mariupol; mostly Donetsk region, a few in Rostov Oblast |
| q15 Kyiv | fact | capital, north-central, on the Dnieper, population 2,952,301 (Jan 2022) |
| z2 Zelenskyy in the White House | drilldown | dated visits: Feb 2022, Dec 2023 (Biden aid), 28 Feb 2025 (Trump, Vance, contentious), Aug 2025 summit |

*Known gaps from these answers:*
- **q13:** the text is right (an eastern city) but the map point is the river near Chernihiv; the
  answer doesn't notice. This is a data issue (graph team B1). A code check comparing a place's type
  (river) with its summary ("city") could flag it.
- **Event lists rank countries high** (q3: Ukraine and Russia second and third). Ranking choice open
  (P2-53).
- **Region counts inherit the hierarchy error:** "Russia 73" for Zelenskyy includes Kharkiv Oblast
  (graph team B1c).

**P2-53. Ranking in event and area lists** (decided 2026-10-21): should countries and continents
rank after specific places? They're mentioned in almost every article, so they top event lists (q3).
They would still be on the map either way.
*Decision (owner):* three tiers, "a reverse tree": **specific** places first (town, city, village,
street, building…), then **regional** (state/oblast, region, province, county, peninsula,
archipelago), then **broad** (country, continent, sea, ocean, gulf, bay, strait). Within a tier the
route's own ranking stays. Applied to every list route (entity, event, area, area + topic, common);
`graph_tools.tier()` / `tiered()`.
*Outcome:* q3 → Bakhmut, Soledar, Klishchiivka, Orikhovo-Vasylivka (Ukraine and Russia moved to the
end of the list, still on the map).

**P2-41 (update).** Decided: `MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"`, with the free
router as backup (owner: "use whatever free model you want"). First run: the pinned model answered
2 of 5 calls; the backup answered the rest, with lower quality.

#### Owner's notes after Part 5 (2026-10-21)

**P2-54. When a list is a list** (decided 2026-10-21). The list shape now starts at **more than 10
places** (was 6). A shorter result, such as q12's 7 places within 500 m, is explained place by place
with its passages (the explain shape) instead of a bare list.
*Why (owner):* "q12: more text for a short list"; ten names is what a reader takes in at a glance.
*Outcome:* q12 → 7 places, explain shape, 10 passages cited (Maidan, Khreshchatyk, October Palace,
European Square…).

**P2-55. A list answer opens with one summary sentence** (decided 2026-10-21). If the evidence has a
lead summary ([L1], e.g. the Battle of Bakhmut article), the list answer starts with one sentence
from it, then the strongest places and the regions. Lists still get no corpus passages (P2-48).

**P2-56. Suggested follow-ups stay written by the LLM** (decided 2026-10-21). The owner asked where
"What is the population of Dnipro?" came from: the LLM proposed it from the text it read (Dnipro's
lead paragraph). Kept as is; code only checks they're whole questions, at most 3 (P2-52).

**P2-57. Washington, the White House and the Oval Office are separate places** (discussed
2026-10-21). The owner asked whether they should be one entity. They are three nested places (city ⊃
building ⊃ room), each with its own paragraphs, so the agent keeps them apart; merging names is the
graph team's job anyway (P2-38). On the map they sit on top of each other, so the README suggests the
UI cluster nearby pins. Collapsing nested places in a list is on the ideas list.

**P2-58. "Tell me about number 13"** (decided 2026-10-21). The owner asked what happens when the
user asks about a place they see on the map but that the answer didn't discuss.
*Decision:* the answer, the map and follow-ups share one numbering: place 13 on the map is `[13]` in
the result. The UI sends the previous result back in `chat_history`; "number 13" is looked up by the
`number` field in that result, so it works for any place on the map, not only the top 10. Only the
first 20 places of a previous turn are listed to the LLM in step ① (to keep the prompt short), with
"(+N more on the map)"; the number itself is resolved by code from the full list.
*Outcome (tests):* `test_follow_up_by_number_uses_the_previous_results_numbers`; planner tests for
number 13 in a 30-place history.

**P2-17 (update).** The paging token is no longer needed: every place found goes into the result
(P2-18), numbered, so "more" is already on the map and any of it can be asked about by number.

### ⑥ Result (built 2026-10-21)

**P2-59. The result JSON** (`schema.py`, `result.py`). No LLM in this step; nothing in it comes
from the LLM except the answer text and the follow-ups.
*Decision:*
- `answer`, `status` (answered / no_data / out_of_scope / llm_failed), `grounded`, `shape`.
- `geo_locations`: **every place found**, numbered as the answer cites it: id, label, kind, `role`
  (`primary` = the answer discusses it; `context` = found, on the map only), a GeoJSON Point
  `[lon, lat]`, a one-line `why` (the data line), `uncertain` when the graph's point may be wrong, and
  up to 10 paragraph pointers.
- **Outlines** (`shape`) only for primary places, at most 10 per answer, each simplified to at most
  300 points (Douglas–Peucker, plain Python). A state's 150,000-character polygon becomes ~6 KB.
  *Why:* the owner asked whether shapes are for the user or for us: for the user's map. Context places
  stay points so a 1,656-place answer doesn't carry 1,656 polygons.
- `regions`: the country → oblast tree with counts and place numbers (P2-48), for big lists.
- `citations`: what each `[S2]` / `[L1]` points to: pointer `TEXT_<id>`, article, section, and the
  entities' character spans in the paragraph (so the UI can highlight them). `sources` = their pointers.
- `map`: a box to zoom to (around the primary places, padded) and the numbers to highlight.
- `did_you_mean` (other candidates from step ②), `notes` from every step (prefixed ①–⑤), `meta`
  (question type, model, LLM calls, cost, seconds).
- Input: `geo_location` is GeoJSON (`Point` with optional `radius_m`, or `Polygon`); lower-case
  "point" accepted; bad coordinates or rings raise `InvalidRequestError`.

**P2-60. One pipeline for the app and the harness** (`pipeline.py`). `georag_agent.query()` and
`eval/run.py` both call `pipeline.run()`, so a test run is exactly what the UI gets. `query()` keeps
its phase-1 signature (`text_prompt`, `geo_location`, `chat_history`, `api_key`) and `get_source_text()`
now reads the Vr6 graph. The graph is loaded once per app start (~14 s, ~1.1 GB).

*Found while building ⑥ and fixed:*

| Found | Fix |
|---|---|
| "Tell me about Soledar" (a drill-down on a place) left Soledar itself out of the places | the asked place comes first in the `about` route |
| a follow-up by number used the position in the list, not the number shown | looked up by the `number` field (P2-58) |
| Fresh run: q11's map box was [-216, 37, 216, 86]; Russia's outline crosses the 180th meridian | the box is kept inside [-180, 180] × [-90, 90] |
| Fresh run: z2's answer stopped mid-sentence ("asserting that there was"); Flash ended the text early | code cuts an unfinished last sentence and notes it (like follow-ups, P2-52) |
| Fresh run: q3's region tree had Donetsk inside Donetsk: two names in the INSIDE chain belong to one group | each region appears once per path |
| Fresh run: "Show me Kyiv" gave Kyiv no sources (a place found by name has no linking records) | its own article's first paragraph is its source |
| Fresh run: follow-ups like "Tell me about Bakhmut [1]." | citation marks are removed from follow-ups, so the UI can send them back as typed |
| Phase-1 regression: a rejected OpenRouter key no longer raised `LLMNotConfiguredError`; the steps fell back quietly and the answer said "couldn't be written" | a rejected key stops the question with the readable error again |

#### Part 6 results: the fully fresh run (focus, Gemini 2.5 Flash, 2026-10-21 13:52; `eval/results/2026-10-21_135214_*`)

All six steps, nothing reused: 10 of 10 answered, 18 LLM calls, $0.016 in total, 1.0–5.6 s per
question (plus 14 s to load the graph once). No citation removed, no answer cut, no fallback; every
answer ends on a whole sentence; q11's map box is valid; no region nested in itself.

| | shape | places (outlined) | regions | citations | result size |
|---|---|---|---|---|---|
| q1 / z1 Zelenskyy's places | list | 500 (4) | 43 | 0 | 176 KB |
| q3 Battle of Bakhmut | list | 76 (4) | 14 | 1 | 27 KB |
| q10 | list | 1,656 (4) | 94 | 0 | 500 KB |
| q11 presidents | fact | 2 (2) | — | 10 | 11 KB |
| q12 within 500 m | explain | 7 (5) | — | 19 | 12 KB |
| q13 Dnipro | fact | 1 (1) | — | 1 | 2 KB |
| q14 drones in the box | list | 192 (6) | 2 | 0 | 63 KB |
| q15 Kyiv | fact | 1 (1) | — | 1 | 5 KB |
| z2 Zelenskyy in the White House | drilldown | 1 (1) | — | 8 | 4 KB |

Outlines are a small part (at most 12 KB); big results are big because of the places themselves.
Fine for a Python call in the same process; worth revisiting if the agent ever moves behind an HTTP
API.

*Seen in this run, not fixed:* q12 lists `Україні` (place 6), a Ukrainian word from citation titles
in "Sources" sections, geocoded at the Academy of Sciences, and the answer quotes nine of those
titles. Reported to the other teams (F1, F2); reference sections are now left out (P2-61).
q13's map point is still the river (B1).

#### Owner's notes before the push (2026-10-21)

**P2-61. Reference sections are left out** (decided 2026-10-21).
*Question (owner):* why skip them; are they confusing and unrelated to what we need?
*Evidence:* yes. 5,021 paragraphs (7.8 %) are "See also", "Sources", "Further reading",
"References", "Bibliography"… sections: lists of article titles and books ("Ivanov, Henry, 'Country
Briefing: Russia', Jane's Defence Weekly, 28 April 2006"). 2,212 entities are mentioned only there
(`Andy`, `Aviation`, `Battle`, `Belarus.`), with 8,339 relation records. In q12, Ukrainian citation
titles gave a "place" (`Україні`) and nine quoted titles as passages.
*Decision:* the loader drops these paragraphs, the records read from them, and the entities left with
no paragraph (`graph_index.drop_reference_sections`). The file isn't changed. Raised with the
data-collection, NER and graph teams (GRAPH_TEAM_ISSUES F1).
*Bug found on the first run and fixed:* Russia vanished from the region overviews (q1: Russian oblasts
at the top level). The INSIDE hierarchy hangs all of Russia's regions from `РФ`, a name of Russia
mentioned only in citation titles, and the drop removed it. Entities that other places sit INSIDE are
now kept, as hierarchy only (18), and a place no paragraph mentions is never a search result (F3).
*Not filtered (owner to decide):* `Україні` survives with one paragraph, a Ukrainian name in brackets
(F2); 1,458 entities have Cyrillic names.

**P2-62. Citations in the answer** (decided 2026-10-21).
*Question (owner):* what are the numbers in "Zelenskyy is the current President of Ukraine [1, S4,
S13, S20, S29]", and should we keep them?
*Explained:* `[1]` is place 1 on the map, `[S4]` a corpus passage, `[L1]` an article's summary; each
`S`/`L` id resolves to a paragraph pointer in `citations`. They are what makes the answer checkable,
and code verifies every one (P2-52).
*Decision:* keep them, but readable: at most two passages per statement (the prompt asks; code
enforces it after removing ids that point at nothing), and the result also carries `answer_plain`,
the same text without marks, so the UI can choose. *Outcome:* q11 → "[1, S4, S13]".

**P2-55 (update). The list summary sentence.** The owner asked whether the Bakhmut answer has its
summary. It didn't: the model folded it into the count ("The Battle of Bakhmut [L1] involved 76
locations"). The instruction now says the first sentence states what the subject is, in the summary's
facts, ending with [L1]. *Outcome:* "The Battle of Bakhmut was a major battle between the Russian
Armed Forces and the Ukrainian Armed Forces for control of the city of Bakhmut… [L1]. 75 places were
found…". Zelenskyy's lists have no summary because the corpus has no article about him.
*Side effect found and fixed:* the longer list instruction pulled q12 (an explain answer) into list
style, with 0 citations in three runs; the explain instruction now says to build the answer from the
passages, place by place (16–17 citations again).

**P2-63. Phase-1 code removed** (decided 2026-10-21, owner: "we don't need the phase one code").
Removed `graph_client.py`, `contracts.py`, the tool loop in `agent.py`, their tests and `DESIGN.md`
(all in git history). `agent.py` keeps `MODEL`, `get_llm()` and the error classes; all five error
names stay because `ui/geo_agent.py` imports them.

**P2-59 (update). What the UI receives, explained** (owner: "is it 176 KB of answer?"). No: the
result is a Python dict, not a file, and almost all of it is places. For q1 (500 places), 163 KB:
the answer is 40 words (0.2 KB); places 153 KB (~300 bytes each: number, name, kind, role, point,
data line, a few pointers); regions 10 KB. No paragraph text is ever included, only `TEXT_<id>`
pointers. The harness now also saves each question's result as its own file (`<run>_ui/<id>.json`),
so it can be read as the UI gets it rather than through the trace.

**Dnipro's outline** (owner: "will it return a polygon as well?"). It returns what the graph has:
a 25-point line, 5 km of river near Chernihiv (`kind: "river"`), while the answer says "a city in
eastern Ukraine". A data issue (B1).

**P2-64. A city geocoded on water is marked uncertain** (decided 2026-10-21; owner: "if it won't be
messy"). A place whose graph type is river/stream/canal/water/lake/reservoir while its own article's
first sentence says it is a city, town, village or capital gets `uncertain: "geocoded as a river,
but its own article describes a city or town"`. Measured on the real graph first: of all places with
an article, 3 have a settlement article and a non-settlement type (Dnipro: river; the DPR: amenity,
already flagged; Autodrom Chayka: highway, a race track, so a false alarm). Limiting the rule to
water types flags only Dnipro. Fixing the point itself waits (ideas list); the graph team is asked
(B1).

**P2-55 (update 2). The summary is a rule, not a fix for one question.** The owner asked whether
another battle would get a summary too. Retrieval attaches the subject's own article lead as [L1]
for any subject that has an article; the writer opens every list with it. Checked on four questions
never used before (2026-10-21, $0.006): Siege of Mariupol, Battle of Avdiivka, Wagner Group, Azov
Brigade: all four open with their summary, cited [L1]. A subject without an article (Zelenskyy) gets
none. The same check found two other issues (ideas list): "Battle of Avdiivka" picked the 2017
battle, and the Azov Brigade's top places are geocoding noise.

#### Final run before the push (focus, Gemini 2.5 Flash, 2026-10-21 16:33 and 17:10; `eval/results/2026-10-21_171041_*` is the one pushed)

Fresh, all six steps: 10 of 10 answered, 18 LLM calls, $0.015–0.017, 1.1–6.5 s per question. No
citation removed, no answer cut. Regions: Ukraine 224, Russia 74 for Zelenskyy's places (as before
the drop). The 17:10 run repeats it after P2-64, with the same answers; Dnipro's now ends "The
graph's point for Dnipro [1] may be wrong, as it is geocoded as a river but described as a city or
town in its own article."

| | shape | places | citations | answer opens with |
|---|---|---|---|---|
| q1 / z1 Zelenskyy's places | list | 500 | 0 | "connected to 500 locations… White House [1], Kyiv [2]…" |
| q3 Battle of Bakhmut | list | 75 | 1 | the battle's summary [L1], then 75 places |
| q10 | list | 1,652 | 0 | (deferred, P2-51) |
| q11 presidents | fact | 2 | 6 | "Zelenskyy is the current President of Ukraine [1, S4, S13]…" |
| q12 within 500 m | explain | 7 | 17 | Maidan, Khreshchatyk, October Palace… each with its passages |
| q13 Dnipro | fact | 1 | 1 | "Ukraine's fourth-largest city…" (map point wrong, B1) |
| q14 drones in the box | list | 192 | 0 | "192 places… Avdiivka, Mariupol, Bakhmut…" |
| q15 Kyiv | fact | 1 | 1 | the city's summary |
| z2 Zelenskyy in the White House | drilldown | 1 | 8 | dated visits, 2022 to 2025 |

---

## Final stage: the MVP (from 2026-10-29)

**The rebuilt graph on main** (graph team, on the new NER output; not yet the final graph). Loads
with no code change: 87,065 nodes (was 120,019), 47,398 paragraphs (was 64,301), relations for 34,427
paragraphs (a full build, not a check-mode one), load + indexes 6.5 s (was 14). Reference sections
dropped: 3,613 paragraphs, 733 entities (9 kept for the hierarchy). **Lost:** the articles for Kyiv,
Dnipro, Kharkiv, Russia, Ukraine, Crimea and Volodymyr Zelenskyy, so "Show me Kyiv" now has no
summary and "Where is Dnipro?" answers "a river" (GRAPH_TEAM_ISSUES G). Dnipro is no longer flagged
uncertain, because the flag needs the city's article (P2-64).

**Owner's notes after using the agent (2026-10-29):**

**P2-65. Which places go on the map** (decided). *Owner:* "a deep dive should show only the place
we dive into; the map shouldn't get convoluted for every type of question." *Decision:* a list
answer or an area question returns every place found; every other answer (where is, who did what,
drill-down, a question about something) returns only the places it discusses, plus the places the
question asks about even if the answer forgets their number. `map.showing` ("all" / "discussed")
and `map.not_shown` say so. The numbers stay the ones the answer cites. *Why in `geo_locations`
and not a flag:* the UI draws every entry already, so it works without a UI change, and "number N"
follow-ups refer to what the user saw. *Outcome:* "Tell me more about Mariupol" went from 552 pins
to the places its answer names.

**P2-66. "Number 4" answered about place 5** (bug, fixed). *Owner:* "asking about location number
four gives one away, like five." *Cause:* step ① found the right place (number 4 = Illich), but every
answer numbers its places from 1 again; in the follow-up Illich was [1] and Ukraine [4], and the
writer, still reading "location number 4" in the question, took [4] of the new list. *Fix:* the
writer reads the question with the reference replaced by the place's name ("Tell me about Illich"),
`planner.question_for_answer`. A number the previous answer doesn't have gets a plain reply without
an LLM call ("The previous answer has no place number 4"). *Outcome:* "number 4" and "number four"
both answered about Illich.

**P2-67. Suggested follow-ups must be answerable** (decided). *Owner:* "follow-up questions aren't
answered correctly; they came from the text we found, so maybe attach a pointer." *Found:* they
didn't all come from the text: "What is the capital of Ukraine?", "What is the population of
Kyiv?" (no Kyiv article any more) were the model's own ideas, and the graph has nothing to answer
them. *Decision:* the prompt asks for follow-ups that name a place, person, organization or event
from the material, in forms our routes answer ("Tell me about X", "Which places are linked to X?",
"Who attacked X?", "What happened in X?", "X in Y"); code drops any that names nothing in the
material. The name is the pointer: the next question resolves it to the same graph entry. *Outcome:*
"What happened in Azovstal?", "Which places are linked to the 36th Separate Marine Brigade?".

**P2-68. The app runs on Gemini 2.5 Flash** (decided 2026-10-29, owner). `MODEL =
"google/gemini-2.5-flash"`, the free router still behind it. Through the UI: 48 s on the free model,
2–3 s on Flash (first question 9.7 s with the graph load), 0.17 cents a question. Each person's
OpenRouter key now needs a little credit.

**The missing articles, traced** (2026-10-29). Not a graph or NER fault: the data team's selector
(Oct 18) rejects broad pages by their share of war paragraphs (Kyiv 3 of 197). The first Vr6 graph
was built on NER from before it (1,909 articles, Kyiv included); today's graph on the selected corpus
(1,602); the newest corpus (2,081, BFS expansion) brings back Ukraine, Kharkiv and Zelenskyy but not
Kyiv, Dnipro, Russia or Crimea. *Recommendation:* keep the new corpus and force-include anchor pages
(GRAPH_TEAM_ISSUES G), rather than go back to the old one.

**The UI wouldn't render on the owner's PC** (2026-10-29): no map, no chat box. *Cause:* Windows
Smart App Control blocks a compiled file of pandas 3.1 ("An Application Control policy has blocked
this file"); Streamlit imports pandas to draw the page, so the script stopped. Not the UI's code.
*Fix, in our environment only:* `pandas<3` (2.3.3 is allowed). *For the UI team:* pin `pandas<3` in
`ui/requirements.txt`, or anyone with Smart App Control on hits the same blank page.

**Owner's UI testing, round 1 (2026-10-29).** Replayed through `ui/geo_agent.py` with the same chat
history the app sends; history turned out not to matter, the question kind did:

- **P2-69. "Tell me about <event>" found nothing** ("No data from the graph"). The about route looked
  only for people, organizations and places; an event is an article. *Fix:* an about question that
  names only an event uses the event's article (its places, summary and passages); an event named next
  to a person or place adds its summary. *Outcome:* "Tell me about the Siege of Mariupol" → answered
  from the article, 22 places.
- **P2-70. A topic with no place or map had no route** ("Where were drone attacks?" → no data;
  "Show me drone attacks" typed `other`). *Fix:* a corpus-wide topic search, places mentioned in any
  paragraph that mentions the topic, ranked by those paragraphs; `other` with keywords and no names
  goes there. *Outcome:* 1,486 places, Kyiv, Moscow, Belgorod, Odesa first.
  **Reverted (owner, 2026-10-29):** too big a change for the final stage; it swept every paragraph
  in the graph for the word, and the owner wants answers from the graph's structure.
- **No follow-ups:** a consequence of the two above; no-data answers carry none.
- **P2-71. Extra polygons:** the UI adds each answer's layers to the map and never clears them
  (UI_TEAM_NOTES.md). On our side, a non-list answer now outlines only the place it is about, named
  in `map.focus`, so the UI can show the rest behind a toggle. **Reverted (owner, 2026-10-29):** what
  to show by default is the UI's job; the agent returns the places and a hint.
- **Owner's rule from here on:** in the final stage, diagnose and propose; implement only after the
  owner's go.

**The UI, end to end** (2026-10-29). The UI team's app (`ui/app.py`, from main) runs against the
agent unchanged: answer, 52 map layers and follow-ups for the Siege of Mariupol. On the app's free
model the answer took 48 s, against 2–3 s on Gemini 2.5 Flash.

**The final graph (2026-10-30, eb2c6be).** Corpus v3 (2,285 pages), NER of 03d6943, Vr6 notebook
unchanged: 149,085 nodes after the reference drop (83,008 paragraphs, 2,285 articles), 812k edges,
same format, so nothing in our code had to change. 1.4 GB in memory, about 11 s to load and index.
Ukraine, Kyiv, Kharkiv, Donetsk, Luhansk, Zaporizhzhia, Dnipro and Zelenskyy have their own articles
again (242 of the 548 dropped articles are back); Russia, Crimea, Moscow, Odesa and most oblasts are
still out (the selector rejects them: 0–2 military paragraphs each). 180 tests and the 10 questions
pass ($0.017); "Show me Kyiv" now has a description instead of "no passages describing Kyiv".

**P2-72. Fixes found on the final graph** (owner's go, 2026-10-30):

- **"What happened in Moscow?" answered "no data"** although Moscow is in 1,411 paragraphs. The
  question went to the LLM planner (not the fast path), which typed it `area_topic` with the keyword
  "happened", so the retrieve step searched Moscow's paragraphs for that word. *Fix:* the prompt says
  words like "happened", "events", "situation" are no topic (one example added), and a code check
  drops such words; an `area_topic` left with no topic becomes `about` (a named place) or `area` (the
  map selection). *Outcome:* 22 citations; "What happened in Dnipro / Bakhmut in 2023?" answered too.
- **Dnipro on the river near Chernihiv**, 300 km off, though its own article now says "city". The
  graph has the right point under another node, "Dnipro City" (city, with outline). *Fix:*
  `PLACE_FIXES` in `graph_index.py`: on load, a wrongly geocoded name takes the point, outline, place
  type, address and INSIDE parent of the node that has it right; the graph file is not changed.
  Dnipro, Дніпро → Dnipro City; Dnipro Oblast → Dnipropetrovsk Oblast. *Outcome:* the pin is on the
  city, no "uncertain" warning, the region is Dnipropetrovsk Oblast, and Yekaterinoslav / Dnepr /
  Dnepropetrovsk now join Dnipro's group (same point).
- **More wrong points, same fix** (owner: "if we can't fix the location, we don't show a wrong
  point"). Listed by names in 15+ paragraphs geocoded with importance under 0.1 (the "uncertain" flag
  missed some: "Soviet Union" is typed `historic`). Eight more take a right node's point
  (Zaporizhzhia Oblast was a village in Kherson Oblast; Oval Office a road in Alabama → White House).
  36 have no right point anywhere in the graph, mostly regions, former states and military
  districts matched to a shop, plaque or street (Donbas: a street in Skopje); `NO_POINT` clears them
  for every spelling, before grouping too, so a real place at the same spot keeps its own point
  ("Donbass" sat on the village Novyi Donbas). A place lookup with no point still gets its own
  article's lead: "Where is Donbas?" is answered, with no pin.
- **The hierarchy follows the addresses** (owner: "take the graph as the truth"). 173 INSIDE links
  join two places whose addresses name different countries, mostly through landforms that cross
  borders: Kharkiv Oblast → Central Russian Upland → Russia (about 300 places), Zakarpattia → Eastern
  Carpathians → Romania, Crimea → Southern Federal District → Russia (about 240), St Petersburg →
  a bay → Estonia. *Fix:* such a parent is replaced by the place's own address country, when that is
  a country node: 146 links; the 28 left name a sea or a non-country. Crimea's addresses say
  Ukraine, so it sits under Ukraine. "What happened in Crimea?" still tells the 2014 annexation and
  the 2022 advance from occupied Crimea; that comes from the text, not the hierarchy.
- **Event titles with lower-case words were thrown away.** "Show me all locations connected to the
  Kharkiv counteroffensive" → no data, though the article has 96 paragraphs: the P2-27 rule calls a
  name with a lower-case word a description ("Russian generals"), and so also "Bucha massacre",
  "Wagner Group rebellion". The user's own typing never mattered: the rule reads the LLM's spelling
  ("where is ukraine" → Ukraine). *Fix (owner's go):* a name the LLM marks as an event that starts
  with a capital or a year stays a name. *Outcome:* Bucha massacre 52 places, Kharkiv
  counteroffensive 132, Wagner Group rebellion 14 citations; the 10 questions unchanged.

**Owner's UI testing, round 2 (2026-10-31).**

- **"Where is Donbas" showed nothing** once its Skopje street point was removed. Its own article says
  "the Donbas usually refers to Donetsk Oblast and Luhansk Oblast", so `COMPOSITE_PLACES` gives every
  spelling (Donbas, Donbass, ...) the two oblast outlines together, a point between them and
  Ukraine as parent (owner's go). One pin, one outline; the village Novyi Donbas keeps its own.
- **"Show me where the battle of Bakhmut occurred" → no data.** Not the wording: the plan was right
  (where + the event), but the place-lookup route only locates places and an event is an article.
  *Fix:* a place lookup that names only an event is answered from the event's places; the plan stays
  a place lookup, so the map shows the main place (Bakhmut, #1) and the places the answer names, not
  the 74-place list (73 not shown).
- **Inspect** (owner's question): the result carries paragraph pointers; the UI's Inspect button
  calls `get_source_text()` on click, which reads the paragraph from the loaded graph. No LLM, no cost.
- **UI side:** old pins stay on the map (UI_TEAM_NOTES 3, now marked most important: it confuses
  "number N"); a long answer opens at its end (UI_TEAM_NOTES 7, tried on a local copy).
- **"Number N"** works for every place of the last answer (tested 3, 240 and 535 after the
  535-place list), and only for the places on the map after a non-list answer.

**P2-73. Outlines only for the places the question is about** (owner's go, 2026-10-31). Every place
the answer discussed got an outline (up to 10), and the map zoomed to fit them all: "What happened
in Crimea?" outlined Russia and Ukraine too and zoomed to the whole world; "Tell me about number 2"
after the Bakhmut list outlined 10 places, the UK among them. *Rule:* the outline and the zoom go to
the places the question names (or the follow-up's place, or a place lookup's #1: the event's main
place for "where did the battle of Bakhmut happen"); every other place keeps its pin. A list gets
pins only (its places are equal; "Russia and Ukraine with the same country" would outline two
countries); an area question outlines the named area it searched ("drone attacks in Kharkiv"),
never a drawn selection, which the UI draws itself. A question about a person or an event names no
place: pins only, zoom to the pins. *Considered:* sending every outline and letting the UI choose
by `role` / `map.highlight`; the UI draws every `shape` it gets, so that needs a UI change before
the MVP, and nothing reads an outline back (follow-ups use number, id and label). No format change;
answers get smaller.

**P2-74. "Where did <event> happen" asks for one place** (owner's go, 2026-10-31). The P2-72 route
answers a place lookup that names an event, but the LLM typed "Show me where the battle of Bakhmut
occurred" as `event_places` 5 times out of 5, so the map got all 75 places. *Fix:* in `_finalize`,
`event_places` with one event, the word "where" and no list word (all, every, list, locations,
places, cities, ...; "take place" is no list word) becomes a place lookup. *Outcome:* Bakhmut 4 of 4
runs (Bakhmut's pin and outline, zoomed in, 73 not shown), Siege of Mariupol, Bucha massacre,
Battle of Avdiivka the same; "Show me all locations ... Battle of Bakhmut" stays the 75-place list.

**P2-75. A topic with no area asks for one** (owner's go, 2026-10-31). "Show me where drone attacks
happened" names no place and nothing was selected, so the topic search had no area and the answer
was "No data". *Considered:* searching the whole graph's text (measured: 4,300 of 83,008 paragraphs,
1,758 places, 1.2 s; owner: after the MVP), and a default box around the war area (hides a choice
from the user, leaves out Moscow and the Black Sea, and with the per-place search costs about the
same as the whole graph). *Chosen (owner: the better of asking and a default box):* ask. An `area`
or `area_topic` plan with no area gets a fixed reply without the second LLM call: "There is no area
to search ... Draw a box or pick a point on the map and ask again, or name a place (for example
"drone attack in Kharkiv")." A named place with no point (Eastern Ukraine) gets the same.

**P2-76. Russia zooms to Russia.** Its outline crosses the 180th meridian (Chukotka), so the zoom
box spanned every longitude: "Where is Russia?" and q11 showed the whole world. *Fix:* for an
outline more than 180° wide, only its parts on the side of the place's point count: Russia
11°E-180°, the US 180°W-53°W (the Aleutians west of the line left out).

**Also (2026-10-31):** `answer_plain` kept the commas between citation marks ("since 2019,,."); a run
of marks now goes with its commas. **The launcher** (owner: for all teams, in the repo root):
`RUN_GEORAG.bat` finds Python 3.10+, and `AgentRag/launch.py` sets up `AgentRag/venv` once, installs
the packages (with `pandas<3`), asks once for the key (hidden, saved in the git-ignored
`AgentRag/.env`), checks the graph and opens the app. It runs `AgentRag/ui_mvp/`, a copy of `ui/`
with the UI_TEAM_NOTES fixes, until the UI team's own `ui/` has them (owner's idea; the UI team
pushes its final version to `ui/`, then the copy goes). Not an .exe: Smart App Control blocks
unsigned programs, and the graph alone is 42 MB.

### ④ Evidence pack

**P2-15. Choosing the least text that answers.**
*Decision:* five context levels: no text (places only), the article's lead paragraph, the single
sentence around a relation, whole paragraphs (small results only), and targeted sections
(Commanders, Timeline…). The level slides with the size of the result.
*Why:* your idea of using the text next to the title. The lead paragraph is a ready summary of
about 53 words, and the sentence window cut Bakhmut from 42,806 words to 865.
*Status:* decided.

**P2-16. Top X and the word budget.**
*Decision:* rank and take the top X for the LLM, and always tell the user how many were found
versus shown. The budget size is **not decided yet**: first measure, for each test question, how
many items and words each context level produces.
*Status:* open, waiting on those measurements (step M2/M3).

**P2-17. Paging.**
*Decision:* when only part of a result is shown, the result carries a small paging token ("page 2
of the Bakhmut places"). The UI sends it back with `chat_history` when the user asks for more.
*Why:* our functions don't remember anything between calls, so the token has to travel with the
result.
*Status:* decided.

### ⑤ Write

**P2-18. The map versus the text.**
*Decision:* the map shows **all** places found, each numbered and labelled. The written answer
covers the top ones and refers to them by number (`[1]`, `[2]`).
*Why:* putting places on the map costs no LLM tokens; only the text the LLM reads needs a budget.
*Status:* decided.

### ⑥ Result

**P2-19. Sources.**
*Decision:* `sources` are paragraph pointers (`TEXT_<id>`). The text is fetched only on request,
by `get_source_text`, with no LLM call. *Status:* decided.

**P2-20. Geometry format.**
*Decision:* the industry standard, GeoJSON: `"Point"` / `"Polygon"` / `"LineString"` with
`[lon, lat]`. Polygons are included (city limits, oblasts), simplified to a size the UI can draw.
*Status:* decided.

---

## Phase 1: porting the notebook (2026-10-13)

Kept short; the full reasoning was in `DESIGN.md`, removed with the phase-1 code in phase 2 (P2-63;
it's in git history).

| Id | Decision | Why | Outcome |
|---|---|---|---|
| P1-1 | The agent is two Python functions (`query`, `get_source_text`), not a web service | The UI is Streamlit (Python); one import, no server | The UI team integrated it within a week |
| P1-2 | Each person uses their own OpenRouter key: an `api_key` argument or `AgentRag/.env`, never in code | No shared secrets; a key in a committed file leaks | Worked; the UI added a sidebar key field |
| P1-3 | `MODEL` is a hardcoded constant, on the free router | Free while the flow is validated; changes go through review | Kept for phase 2 |
| P1-4 | The trust boundary: the LLM picks ids, code supplies coordinates and sources | LLMs can invent coordinates | Kept for phase 2 |
| P1-5 | Each query gets its own citation log, instead of the notebook's global | Overlapping queries would mix up citations | Kept |
| P1-6 | No fallback graph; read the graph team's file in place | A stand-in would quietly answer from fake data | The file path broke when Vr6 replaced the JSON with `.gz`; superseded by P2-5 |
| P1-7 | Typed errors with readable messages (`AgentError`) | The UI can show `str(e)` | Kept |

---

## Ideas list (set aside, not rejected)

Things we chose not to do yet, kept here so we can pick them up if the results call for them.

| Idea | Where in the flow | Why it's waiting | Logged |
|---|---|---|---|
| Scan the question for exact graph names the LLM missed | ② Resolve | Noise from phrases like "the Russia–Ukraine war"; not needed yet (P2-33) | 2026-10-20 |
| Convert the graph to SQLite (measured: 4 ms start-up, 23 MB of memory) | Storage | The teams are discussing memory limits first (P2-5) | 2026-10-20 |
| Hebrew questions | ① Understand | English only for now (P2-9) | 2026-10-20 |
| More context than one sentence when picking between candidates | ② Resolve | Decide after seeing full printed runs (P2-34) | 2026-10-20 |
| Skip the write step with a template answer for locations-only questions | ⑤ Write | To try once the write step exists (P2-3) | 2026-10-20 |
| Fill in obvious relation hints with code ("head of" → `LEADS`) when the LLM leaves them empty | ① Understand | Decide once step ③ shows whether missing hints hurt (P2-40) | 2026-10-20 |
| Fix q10: break it down as Russia + Ukraine + kind of place "country" (the `common` route exists) | ① / ③ | Kept unfixed for now to show an odd/no-data answer (P2-51) | 2026-10-21 |
| "Tell me about number 3" drill-down: carry the previous question's subject (e.g. Zelenskyy) into the follow-up | ① / ③ | Works today when the follow-up names both; a bare number gives only the place | 2026-10-21 |
| For a concept, also look at organizations connected to the LLM's candidates (e.g. reach General Staff from Russian Armed Forces / Ministry of Defence) | ③ Retrieve | q11's success shouldn't depend on the LLM naming the right organization (Part 2 results) | 2026-10-20 |
| Collapse nested places in a list (Oval Office → White House → Washington) into one line with the inner ones under it | ③ / ⑥ | They're different places with their own text (P2-57); the UI can cluster pins first | 2026-10-21 |
| Fix the place itself when its map point disagrees with its own article (Dnipro: a river near Chernihiv; the article says "city"), e.g. by using the article's coordinates | ② / ⑥ | **Done 2026-10-30 (P2-72)**, from the graph's own "Dnipro City" point, not the article | 2026-10-21 |
| "Battle of Avdiivka" with no year resolves to the 2017 battle, not 2023–2024; check that the other is offered in `did_you_mean`, and whether the newest should win | ② Resolve | Found in the unseen-questions check (P2-55 update) | 2026-10-21 |
| Entity lists ranked first by place relations put geocoding noise on top for some entities (Azov Brigade: "Treasure Island", "United States Government") | ③ Retrieve | Found in the unseen-questions check; needs the unification/geocoding fixes or a noise filter | 2026-10-21 |
| Leaner results for very big lists (e.g. context places without `why`/`sources`, fetched on demand) | ⑥ Result | 500 KB for q10 is fine in-process; matters only behind an HTTP API (P2-59) | 2026-10-21 |
| Ignore entities with non-Latin names (1,458, mostly words from native-language names in brackets, e.g. `Україні`) | Loading | Owner to decide; better fixed in NER (GRAPH_TEAM_ISSUES F2) | 2026-10-21 |
| q10 ("Russia and Ukraine ... the same country") sometimes loses its country filter: 1,659 places instead of about 149 (2 of the last 3 runs) | ① Understand | Model variance; owner: record the answers for the MVP, fix in a later stage | 2026-10-31 |
