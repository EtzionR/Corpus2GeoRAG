# Our work, explained: the GeoRAG agent

What we set out to do, how we worked, what went wrong and how we fixed it, and why the result is an
honest MVP and not a demo tuned to look good. Written so the agent team can explain and defend the
work. Every claim here has its evidence in [DECISIONS_LOG.md](DECISIONS_LOG.md) (numbered
decisions, P1-x and P2-x) or in a test run under `eval/results/`.

---

## 1. The goal in one paragraph

The project turns war-related Wikipedia articles into a knowledge graph with map coordinates, so a
user can ask questions and see the answers on a map. Four teams build it as a pipeline: the data
team collects the articles, the NER team finds the people, organizations and places in them, the
graph team builds the knowledge graph and geocodes the places, and the UI team builds the map app.
**Our part is the agent in between:** it takes a question (and optionally an area drawn on the map),
finds the answer **in the graph only**, and returns a short written answer with numbered places for
the map and the paragraphs it relied on. The mission we gave ourselves: answers people can trust.
Every claim cites a paragraph; every pin comes from the graph.

```
Corpus (data team) → NER (NER team) → Knowledge graph + geocoding (graph team) → Agent (us) → Map UI (UI team)
```

It's an MVP for a larger system, so the bar was not "the demo questions look good" but "the method
would still be right on a bigger corpus".

---

## 2. How the agent works

Two Python functions are the whole interface: `query(text_prompt, geo_location, chat_history,
api_key)` and `get_source_text(pointer)`. The UI imports them; no server is needed.

Each question goes through six fixed steps. **The LLM is used in only two of them.**

| Step | What happens | LLM? |
|---|---|---|
| ① Understand | The question becomes a plan: its type (where is / which places / who did what / in this area...), the names in it, relation hints, keywords | one call; obvious questions ("Where is Kyiv?") skip it |
| ② Resolve | Names become graph entries: "Kiev" → Kyiv, "Zelensky" → Volodymyr Zelenskyy | only to choose between real candidates |
| ③ Retrieve | A fixed route per question type walks the graph: places linked to a person, places inside a polygon, who attacked whom | no |
| ④ Evidence | Chooses the least text that answers: data lines for big lists, the sentences around a relation, article summaries | no |
| ⑤ Write | The LLM writes the answer, citing places as `[3]` and paragraphs as `[S2]` / `[L1]`; code then removes any citation that points at nothing | one call |
| ⑥ Result | Code builds the JSON: every place numbered with its point and outline, the citations, the map zoom | no |

**The rule behind it:** the LLM chooses words; code supplies every place, point and source. A
question costs about $0.002 and takes 1 to 8 seconds.

---

## 3. How we worked

### The phases

| Phase | Dates | What happened |
|---|---|---|
| 1. Port the notebook | from 2026-10-13 | The prototype notebook became a Python package with the two functions. The LLM ran a tool loop (up to 7 calls per question). Rules set here that never changed: each person uses their own API key, the model is one constant in code, and **the LLM picks ids while code supplies coordinates and sources** (P1-1 to P1-7). |
| 2. Rebuild on the real graph | from 2026-10-20 | The graph team's Vr6 graph (120,019 nodes) replaced the old data. We replaced the LLM loop with fixed routes (7 calls → at most 2), built the test harness, the evidence step, answer shapes and citation checking (P2-1 to P2-64). |
| 3. Final stage (MVP) | from 2026-10-29 | The final graph arrived (149,085 nodes, 83,008 paragraphs, 2,285 articles). The agent owner tested it through the UI team's app; each round of bugs was diagnosed, a fix was proposed, and only approved fixes were built (P2-65 to P2-76). Pushed to main on 2026-10-31 (PR #32) with a one-click launcher for every team. |

### The working method

- **Measure before deciding.** Each decision records the options, the evidence and the outcome.
  The log has about 80 entries.
- **A test harness from the start** (P2-32). Every test run records each LLM call (step, the model
  that actually answered, tokens, cost, time). It has a cost cap and writes a readable report plus a
  trace of every step. It asks the model fresh every time, so we never mistake a cached answer for a
  working one.
- **The app and the tests run the same code** (P2-60), so a test sees exactly what the UI gets.
- **Every fix is a general rule plus a test**, then checked on questions never used before (section 4).
- **Propose, then build.** In the final stage the owner's rule was: diagnose, propose, implement only
  after a yes. Two proposals were built and then reverted on the owner's call (P2-70, P2-71) because
  they went beyond what the MVP should do.
- **We never edit other teams' work.** The graph file is read as is; corrections happen in memory
  when it loads. Problems go back to their owners as written notes: GRAPH_TEAM_ISSUES.md,
  MISSING_PAGES.md, UI_TEAM_NOTES.md, ner_review/, DATA_TEAM_DROPPED_ARTICLES.csv.
- **209 automated tests**, plus the 10-question run before each commit.

---

## 4. Why this is an honest MVP (no cheating)

This is the section to know well. The risk with any question-answering demo is that it looks right
because the model answers from its own knowledge, or because it was tuned to the test questions. Here
is what prevents each of those, and the evidence.

### 4.1 The graph is the only source of facts

- **Coordinates and sources never come from the LLM.** The LLM never sees a coordinate. Places,
  points, outlines and paragraph pointers are attached by code from the graph (P1-4).
- **The LLM can't slip answers into the plan** (P2-27). In an early run, asked about "major battles",
  the model listed battles from its own memory, and the graph would only have "confirmed" its picks.
  Since then, code (not the prompt) enforces:
  1. every name in the plan must appear in the question;
  2. several names produced from one phrase are the model's own list, and are dropped;
  3. a description ("Russian military commanders") becomes a concept to look up, not a name;
  4. when the question asks for places, the model may not propose any.
- **Citations are checked by code.** Every `[S2]` or `[L1]` in the answer must point to a paragraph
  in the evidence the model was given; anything else is removed.
- **Anyone can check a citation.** The UI's Inspect button calls `get_source_text("TEXT_123")`, which
  reads the paragraph straight from the graph. No LLM, no cost.
- **When the graph has nothing, the answer says so.** It starts with "No data from the graph —
  answer from the LLM only." and is marked `grounded: false` (P2-8). The agent never presents model
  knowledge as graph knowledge.
- **Doubtful data is labelled, not hidden.** A point the graph may have wrong carries an `uncertain`
  note (P2-35, P2-64).

### 4.2 Not tuned to the test questions

- **The prompt's examples are never the test questions** (P2-26), and a test fails if a test
  question ever appears in the prompt. This was found and fixed early: the first prompt happened to
  use test questions as examples, which would have inflated the score.
- **Fixes are rules about the kind of question, not about specific names**, and each was checked on
  questions it was not built for:

  | Fix | Built from | Also checked on (never used before) |
  |---|---|---|
  | A list opens with the subject's own summary (P2-55) | Battle of Bakhmut | Siege of Mariupol, Battle of Avdiivka, Wagner Group, Azov Brigade |
  | "What happened in X" is about the place, not the word "happened" (P2-72) | Moscow | Dnipro, Bakhmut in 2023 |
  | Event titles with lower-case words are names (P2-72) | Kharkiv counteroffensive | Bucha massacre, Wagner Group rebellion |
  | "Where did <event> happen" gives one place (P2-74) | Battle of Bakhmut | Siege of Mariupol, Bucha massacre, Battle of Avdiivka |

- **The full project question list, not just our 10** (2026-10-31, rerun 2026-11-01 after the q4 fix, about $0.02 a run):

  | Question | Result |
  |---|---|
  | q1 Zelenskyy, q2 Putin, q6 Wagner Group, q8 NATO | answered: 536, 638, 323, 488 places; the first three open with the subject's own summary |
  | q3 Battle of Bakhmut, q7 Siege of Mariupol | answered: 75 and 49 places with the article summary |
  | q5 Ukrainian cities connected to Russian military operations | answered: 41 places, filtered to Ukraine |
  | q11 the presidents of Ukraine and Russia | answered, 4 citations |
  | q12 within 500 m, q13 Dnipro, q14 drones in a box | answered |
  | q10 places linked to both Russia and Ukraine "with the same country" | partly: the "country" filter is often lost (1,659 places instead of about 149) |
  | q4 locations of major battles | answered since the 2026-11-01 fix (P2-78): 48 battles, longest articles first; before it, no data |
  | **q9 Ukrainian locations connected to Russian military commanders** | **misread**: lists what is linked to Ukraine or Russia (2,798 places; no data in some runs) |
  | v14, the original q11: "the head of the Russian military" | answered: Gerasimov, Chief of the General Staff, 3 citations |

  We report q9 and q10 as open rather than hide them (section 7).
- **One test question was replaced, openly** (P2-46, 2026-10-20). The original q11, "Tell me about the
  head of the Russian military", failed because every graph record of who leads the Russian
  military has low confidence (0.41 to 0.47, below our 0.7 threshold). We did two things: built a
  general fallback for weak relations, clearly labelled as low confidence (P2-45), and moved the
  question to the variants set (v14) so it is still run. q11 became "Who is the president of Ukraine
  and the president of Russia?". As shown above, v14 is answered today.

### 4.3 Data corrections that don't fake anything

The final graph had some wrong map points (geocoding errors), such as Dnipro on a river near
Chernihiv, 300 km away. We fix these **in memory when the graph loads**; the graph file is never
changed. The rules:

- **Only the graph's own data is used.** "Dnipro" takes the point of the graph's own "Dnipro City"
  node. No coordinate comes from outside the graph or from the LLM. 11 names are fixed this way
  (`PLACE_FIXES` in `graph_index.py`).
- **If the graph has no right point anywhere, we show no pin rather than a wrong one** (owner: "if
  we can't fix the location, we don't show a wrong point"). 34 names, mostly regions and former
  states that were matched to a shop, plaque or street ("Soviet Union" was a shop in Romania;
  `NO_POINT`). They still appear in answers, just not on the map.
- **The region hierarchy follows each place's own address** (owner: "take the graph as the truth"):
  146 links that put a place under the wrong country through a landform crossing a border
  (Kharkiv Oblast → Central Russian Upland → Russia) now follow the place's address, which for
  Kharkiv Oblast says Ukraine.
- **Donbas** was a street in Skopje. Its own article says it "usually refers to Donetsk Oblast and
  Luhansk Oblast", so it gets those two oblasts' outlines from the graph.
- **Everything is listed in code, logged at load, tested, and reported** to the graph team
  (GRAPH_TEAM_ISSUES.md), because at full scale these belong in the geocoding step, not in the agent.

### 4.4 No data from outside the pipeline

- **15 major pages are missing from the corpus** (Russia, Crimea, Moscow, Odesa, ...) because the
  data team's selector rejected them. We could have pulled them in ourselves; we didn't. We traced
  why, listed them with counts and wrote how to add them through the pipeline (MISSING_PAGES.md).
  That's why "Where is Russia?" answers only "Russia is a country": an honest gap, not a patched one.
- **A whole-graph keyword sweep was built and then reverted** (P2-70, owner: answers should come from
  the graph's structure). Today a topic question with no place and no map selection asks the user
  to name a place or select one (P2-75), instead of guessing an area.
- **We did not merge the older graph** to recover pages, to keep one source of truth.

### 4.5 Built to scale, not just to demo

- **Predictable cost.** At most two LLM calls per question, about $0.002, on one model set in code
  (Gemini 2.5 Flash, chosen after measuring: 48 s per answer on the free model, 2 to 3 s on Flash).
- **Deterministic routes.** Fixed routes behave the same every run and can be tested; an LLM loop
  can't (P2-2).
- **Big results stay small.** Tools return paragraph pointers, not text (P2-14); the evidence step
  picks the least text that answers (Ukraine alone has a million words in the graph). A list of
  1,659 places still produces a few sentences of answer.
- **Storage can change without touching the rest.** The graph loads into memory (1.4 GB, about 11
  s). A disk-based alternative (SQLite: 4 ms start, 23 MB memory) was measured and kept ready behind
  one module (P2-5).
- **The interface stayed stable for the whole project**, so the UI kept working across every graph
  version.

---

## 5. The main problems and how we solved them

| Problem | Cause | What we did | Result |
|---|---|---|---|
| The phase-1 agent was slow and unpredictable | An LLM tool loop, up to 7 calls per question | Fixed routes per question type; at most 2 LLM calls (P2-2, P2-3) | Same behaviour every run; testable |
| The free model allowed 50 requests a day and took 48 s an answer | Free tier | $10 of credit with a hard cap; a harness with a cost cap; Gemini 2.5 Flash as the one model (P2-30, P2-68) | 2 to 3 s and about $0.002 a question |
| The LLM supplied answers from memory | It listed battles and cities itself | Code guards on the plan (P2-27) | No injected answers since |
| Huge hubs | Ukraine: 14,200 paragraphs, a million words | Pointers instead of text; the evidence step; answer shapes (list / fact / explain / drilldown) chosen by code | Short, cited answers even for 1,000+ places |
| Noise from reference lists | 7.8 % of paragraphs were "See also", "Sources" and the like; 2,212 entities appeared only there | Dropped when loading (P2-61); reported to three teams | Fewer junk places and passages |
| The original q11 failed | Low-confidence leadership records | A labelled low-confidence fallback (P2-45); the question kept as v14 | v14 answered |
| Shapely and pandas 3 blocked on the owner's PC | Windows Smart App Control | Geometry in plain Python (P2-6); `pandas<3` | Runs on locked-down PCs |
| "Number 4" answered about place 5 | Each answer numbers its places from 1 again | The question is rewritten with the place's name (P2-66) | Correct place every time |
| Suggested follow-ups the graph couldn't answer | The model invented them | A follow-up must name something from the material (P2-67) | Follow-ups that work when clicked |
| "What happened in Moscow?" → no data | The word "happened" was searched as a topic | Generic words are no topic (P2-72) | 22 citations |
| Wrong map points (Dnipro 300 km off) | Geocoding errors in the graph | Load-time fixes from the graph's own data; no pin when none is right (P2-72) | 11 fixed, 34 hidden |
| Kharkiv Oblast and Crimea under Russia | Hierarchy links through cross-border landforms | Follow each place's address (P2-72) | 146 links fixed |
| "Where is Donbas?" showed nothing | Its only point was a street in Skopje | The two oblasts' outlines from the graph | One pin, one outline |
| "Where did the battle of Bakhmut happen?" → 75 pins | The model read it as "all the battle's places" | "Where" + one event + no list word → one place (P2-74) | Bakhmut only, zoomed in |
| Five outlines and a world-wide zoom for "What happened in Crimea?" | Every discussed place got an outline | Outline and zoom only for the asked place; pins for the rest (P2-73) | Crimea only |
| Russia zoomed to the whole world | Its border crosses the 180° line | Count only the parts on the side of its own point (P2-76) | Zooms to Russia |
| "Show me where drone attacks happened" → no data | No place named, nothing selected: no area | The agent asks for an area instead of guessing (P2-75) | A clear instruction, without the second LLM call |
| UI: old pins stay, long answers open at the end, the page can't scroll, blank page on some PCs | UI code | Written notes to the UI team; a copy with the fixes in our folder, run by the launcher, until their version had them | The UI team applied them in their own `ui/` (PR #33); the copy is deleted |
| q4 "major battles" → no data | The battle search looked for titles starting with the whole phrase | Read the event kind from each word ("battles" → "Battle of ..."), longest articles first, each at its main specific place, one pin per place (P2-78) | 48 battles; "main sieges" works too |
| "What happened in this area?" (box drawn) → no data | The model read it as a question about a named subject, and none was named | With the selection in use and nothing named, it searches the selection (P2-77) | 70 places in a box around Kharkiv |

---

## 6. The clever points worth highlighting

1. **The LLM in only two of six steps.** The LLM reads the question and writes the answer. Code
   does the finding, ranking, evidence and map. Obvious questions skip even the first call
   ("Where is Dnipro?" costs $0.0006).
2. **One numbering for text and map.** `[3]` in the answer is pin 3 on the map, and "tell me about
   number 3" is that same place. The user moves between the text and the map without confusion.
3. **Pointers, not text.** Every tool returns paragraph ids and character positions. Text is chosen
   at the end, only as much as the answer needs, and Inspect reads any paragraph on demand.
4. **Code decides the shape of the answer** (list / fact / explain / drilldown) from the question
   type and the size of the result, with a word budget for each.
5. **Guards in code, not in the prompt.** A prompt asks; code enforces. The rules that keep the LLM
   from supplying answers are checked in code (P2-27).
6. **A correction layer that leaves the source untouched.** Wrong points, cross-border links and
   reference noise are fixed in memory at load time from the graph's own data. The shared file
   stays the single source of truth, and every correction is listed and reported upstream.
7. **Honest by default.** "No data from the graph" when there is none; `uncertain` on doubtful
   points; no pin rather than a wrong pin; ask for an area rather than guess one.
8. **Measured decisions.** The harness records which model answered, the cost and the time of every
   call, with a cost cap, and saves a trace of every step. Each decision in the log has its numbers.
9. **Plain-Python geometry**, so it runs where compiled libraries are blocked, including zoom
   boxes for shapes that cross the 180° line.
10. **A one-click launcher for every team** (`RUN_GEORAG.bat`): it sets up Python, asks for the key
    once, keeps the key out of git and opens the app.

---

## 7. Honest limits and what comes next

- **q9 (Ukrainian places linked to Russian commanders) is misread**, and we left it for a later
  stage. It has two causes, and it's worth naming both: the graph can't tell who is a commander (people have no role, and commanders such as Gerasimov and Shoigu are only "mentioned with" the Russian Armed Forces, with no command link), and our list route doesn't yet apply the "only places in Ukraine" filter the planner records. The fix is designed
  and measured: about 114 Ukrainian places linked to the Russian Armed Forces instead of 2,798
  (DECISIONS_LOG ideas list).
- **q10 often loses its "same country" filter**, a matter of how the model reads the question
  (recorded; to fix after the MVP).
- **15 missing pages** (MISSING_PAGES.md) limit answers about Russia, Crimea, Moscow and others.
- **A topic with no area** asks for one; a whole-graph topic search is planned for after the MVP.
- **Memory:** the graph takes 1.4 GB in memory; the disk-based option is measured and ready (P2-5).
- **English only.**

---

## 8. Questions you may be asked

**"You fixed Dnipro's location by hand. Isn't that cheating?"**
No. The graph itself has a node, "Dnipro City", with the right point; we use it. No coordinate
comes from outside the graph or from the model. The fixes are listed in code, logged when the graph
loads, tested, and reported to the graph team, because at scale they belong in geocoding. Where the
graph has no right point, we show no pin at all.

**"Is the LLM answering from its own knowledge?"**
Only when the graph has nothing, and then the answer says so first: "No data from the graph —
answer from the LLM only." Otherwise it writes only from the paragraphs we give it, every citation
is checked by code, and every place and point comes from the graph. In an early run the model did
inject its own answers; we found it, explained it (P2-27) and blocked it in code.

**"Did you tune the system to your test questions?"**
The prompt's examples are deliberately different questions, and a test fails if a test question
appears in the prompt (P2-26). Every fix is a rule about the kind of question and was checked on
questions never used before. On the full project list, two questions still have problems (q9 and
q10), and we report them. q4 was fixed by a rule about lists of events, which also answers "List the
main sieges of the war".

**"Why does q9 fail? Is it the graph's fault?"**
Partly. The graph can't tell who is a commander: people have no role in it, and commanders such as
Gerasimov are only "mentioned with" the Russian Armed Forces, with no command link. Bringing in a
list of commanders from outside the graph would be exactly the cheating we avoid. The other part is
ours: the model reads "Ukrainian locations" as the subject, and our list route doesn't yet apply the
"only places in Ukraine" filter. We designed and measured the fix (114 places instead of 2,798) and
left it for the next stage rather than rush it the day before the MVP.

**"You replaced one of the project questions."**
Yes, openly, on 2026-10-20 (P2-46): the original q11 failed because the graph's leadership records
for the Russian military all have low confidence. We built a labelled fallback for that, kept the
original question in the test set as v14, and today it is answered (Gerasimov, 3 citations).

**"Why not let the LLM choose its own tools, like an agent loop?"**
We started that way. It cost up to 7 calls per question, behaved differently each run, and free
models chose tools badly. Fixed routes per question type are cheaper, testable and the same every
run (P2-2). The LLM still understands the question and writes the answer.

**"How do I know a citation is real?"**
Click Inspect: it shows the paragraph from the graph. Code also removes any citation that doesn't
point to a paragraph the model was given.

**"Why are Russia and Crimea answered so thinly?"**
Their articles are missing from the corpus: the data team's selector rejected them. We traced it
and listed the 15 missing pages for the data team instead of adding data ourselves.

**"Would this work on a much bigger graph?"**
The cost per question doesn't grow with the graph (at most two LLM calls on a small evidence pack).
Routes start from the asked entity or area and walk its links; the only full pass, over place
coordinates for a map area, takes milliseconds. Memory is the limit, and a disk-based store is
measured and ready behind one module.

**"What happens when the question is vague?"**
If it names no place and nothing is selected on the map, the agent asks for an area. If a name has
several real matches, it chooses between graph candidates only and lists the others as "did you
mean".

---

## 9. Numbers to remember

| | |
|---|---|
| Final graph | 149,085 nodes, 83,008 paragraphs, 2,285 articles, about 812,000 links |
| LLM calls per question | 0 to 2 (fast path: none for planning) |
| Cost per question | about $0.002; the 10-question run $0.019 |
| Time per answer | 1 to 8 s (11 s for the 2,798-place q9) |
| Automated tests | 209 |
| Recorded decisions | about 80 (DECISIONS_LOG.md) |
| Data corrections at load | 11 points fixed, 34 wrong pins removed, 146 hierarchy links fixed, reference sections dropped |
| Project questions answered well | 12 of 14 (q9 misread, q10 partly), plus the original q11 |

## 10. Where to find more

- [DECISIONS_LOG.md](DECISIONS_LOG.md): every decision, its options, evidence and outcome
- [AgentRag_README.md](AgentRag_README.md): how to run and call the agent, the result format, known limitations
- [GRAPH_TEAM_ISSUES.md](GRAPH_TEAM_ISSUES.md), [MISSING_PAGES.md](MISSING_PAGES.md), [UI_TEAM_NOTES.md](UI_TEAM_NOTES.md): what we reported to the other teams
- `eval/results/`: the latest test run, with a trace of every step
