# Knowledge graph: issues and questions from the agent team

For the Graph & Geocoding team, and in section F also for the data-collection and NER teams. These
came up while profiling `knowledge_graph.json.gz` (Vr6, 120,019 nodes, 697,333 edges) and running
the agent on it. Each item says what we saw, why it matters
for answering questions, and what would help. We know unification and geocoding fixes are in
progress; we're building as if they will land, and this list is to make sure nothing is missed.

Counts below are from the current file on `main`.

---

## A. Duplicate entities (unification)

**A1. Many spellings of one person, with no `SAME_AS` between them.**
21 person nodes are Zelenskyy: `Zelenskyy`, `Volodymyr Zelenskyy`, `Zelensky`, `Zelenskiy`,
`Volodymyr Zelenskiy`, `Volodomyr Zelenskyy`, `Vlodomir Zelenskyy`, `Volodymyr Zelenskyy`
(with a hidden narrow space), `of President Zelenskyy`, `ZelenskyyUa`, … `Zelenskyy` has no
`SAME_AS` edge at all. (`Putin` – `Vladimir Putin` *is* linked.)
*Why it matters:* "locations connected to Zelenskyy" only sees the variant we look up, so his
connections are split across 21 nodes. (Merged, he connects to 550 geocoded places.)

**A2. Locations with identical coordinates are mostly the same place.**
2,201 location nodes share exact coordinates in 848 groups, e.g.
`Russia` / `Russian Federation` / `RUSSIAN FEDERATION` / `Rossiya` / `Russie` / `Russia.` / `' Russi'`;
`US` / `USA` / `U.S.` / `America` / `AMERICA`; `Kyiv` / `Kiev` / `Kiyev`;
`Dnieper` / `Dnipro River` / `Borysthenes`. Only 120 of the pairs inside these groups have `SAME_AS`.
*Question:* when unification lands, which name becomes the node id, and will the old names be
kept (for example as an `aliases` list)? Users type all of these.

**A3. `SAME_AS` sometimes links different things.**
`Wagner` –`SAME_AS`→ `Africa Corps`, `Chechen Akhmat`; `Kyiv` –`SAME_AS`→ `Sambat`, `Kyivskyi`.
Related, but not the same entity. Is `SAME_AS` meant for exact identity only?

## B. Geocoding

**B1. Well-known places matched to the wrong place.** Most connected first:

| Node | Connections | Matched to | `place_type` |
|---|---|---|---|
| `Donbas` | 3,863 | a street in Skopje, North Macedonia (importance 0.04) | road |
| `Soviet Union` | 2,963 | a street in Slobozia, Romania | amenity |
| `Donetsk People's Republic` | 1,474 | a government building | amenity |
| `USSR` | 1,088 | an address in Russia | amenity |
| `Russian Empire` | 897 | a soldier monument | tourism |
| `Eastern Ukraine` | 493 | a university in Volyn | amenity |
| `Eastern Europe` | 481 | a garden in Malta | park |
| `Nazi Germany` | 401 | a museum in Nuremberg | tourism |
| `Dnipro` | 963 | the **river** near Chernihiv, not the city; `INSIDE` chain: Dnipro → Chernihiv Raion → Ukraine | river |

More on Dnipro: the city's *old* names (`Yekaterinoslav`, `Dnepropetrovsk`, `Днепропетровск`, and
even `Dnipro city`) are geocoded to the **Dnieper river's** point, with `place_type` river, so the
city has no correct point under any of its names.

**B1b. Different places on the same point.** Some names get exactly the coordinates and place type
of another place: `New Russia` (Novorossiya) sits on `Russia`'s country point, and `Kharkov Oblast` /
`Stanislav Oblast` / `Kropyvnytskyi Oblast` share their city's point and type `city`. Identical
coordinates are otherwise a strong hint of the same entity (A2), so these blur the two.

*Why it matters:* "Where is Dnipro?" puts a pin in the wrong region, and every question that
touches Donbas maps to Skopje. The agent now also sends each place's outline to the map, so for
Dnipro the UI draws 5 km of river near Chernihiv while the answer (from the article) correctly says
"a city in eastern Ukraine". Until it's fixed, the agent marks such places as uncertain when the
graph says river/lake but the place's own article says city or town (only Dnipro matches today). Historical states (Soviet Union, Russian Empire) probably should
have no point at all, or a country-level shape.
*Question:* could `place_type` in (`road`, `amenity`, `shop`, `tourism`, `building`) with low
`importance` be treated as "not found" for names that aren't streets or buildings?

**B1c. The `INSIDE` hierarchy puts Kharkiv Oblast inside Russia.** Grouping Zelenskyy's 500 linked
places by their `INSIDE` chain counted 23 of them under Russia → Kharkiv Oblast. Kharkiv Oblast is in
Ukraine. Possibly the oblast's polygon overlaps the border, or a variant name (`Kharkov Oblast`) was
matched to a polygon in Russia. *Why it matters:* we build region overviews ("Ukraine: 186 places —
Donetsk 145…") from `INSIDE`, so the error shows up in answers and on the map.

**B2. Important places with no coordinates.** `Luhansk People's Republic` (1,081 connections),
`Ukrainian SSR` (540), `Novorossiya` (300), `Kakhovka Dam` (214), `Savur-Mohyla` (157),
`Mayorsk`, `Verkhnyotoretske`, `Novotoshkivke`. Kakhovka Dam and the villages are real points
on the map and appear in our test questions' territory.

**B3. Very large polygons.** `geometry_wkt` reaches 290,081 characters (`Graham Land`);
states up to 157,296, rivers up to 141,753. Fine for us (we'll simplify before sending to the
UI); just flagging in case you planned a size limit.

## C. Names and types

**C1. Name fragments.** 30 names start or end with spaces (`' Dmitry Pesko'`, `' HR'`,
`' Hospital No. 3'`); 405 end with `.` (`Russia.`, `Ukraine.`, `Donetsk.`, `265th Guards.`).
Note `INSIDE` chains end at `Ukraine.` / `Donetsk.` rather than `Ukraine` / `Donetsk Oblast`.

**C2. Types.** `Kremlin`, `Azovstal` and `Donbas` are `LOC`, which works for us. Just confirming
that each name always has exactly one type (README 2.2), so `Wagner` can never also be a `PER`.

## D. Relations

**D1. Classifier accuracy.** README says 60–65 %. We're hand-checking a sample by confidence band
to choose a threshold. Typical wrong ones: `Telegram` ATTACKED `Bakhmut` (0.47, from "Prigozhin
claimed on Telegram…"), `Brovary` ATTACKED `Russia` (0.66). We'll send our labelled sample back;
it may help you retrain.

**D2. "Head of the Russian military" depends on which organization.** `LEADS` → `Russian Armed
Forces` returns only `Yeltsin` (1 record), while `LEADS` → `General Staff` returns
`Valery Gerasimov` / `Gerasimov`. Nothing wrong in the graph; noting it because it's one of our
four core question types.

**D3. Coverage.** Entity–entity relations reference 44,464 of the 64,301 texts. We assume the
other ~20k paragraphs mention fewer than two entities. Is that right, or is part of the corpus
missing relations?

## E. Questions for you

1. **Dates.** Is anything planned for dates (per text, or per relation record)? For now we read
   dates out of the sentence text.
2. **Events.** Battles and attacks exist as *articles* (`Battle of Bakhmut`, `Siege of Mariupol`;
   55 "Battle/Siege of" articles), not as nodes. Will there ever be event nodes, or should we keep
   treating the article as the event?
3. **Stability of ids.** We will use `TEXT_<text_id>` as the source pointer returned to the UI.
   Will `text_id` stay stable across graph versions, or should the pointer be article + paragraph
   index?
4. **Article titles.** Is `TEXT.source` always exactly the Wikipedia article title?
5. **Next version.** Will the next upload keep the same file name and format (`.json.gz`,
   node-link, `links`)? Our loader depends on it.
6. **Missing files.** `KNOWLEDGE_GRAPH_README.md` mentions `knowledge_graph_examples_real_format.json`,
   `knowledge_graph_examples.json` and `PIPELINE.md`, but they aren't in `Graph_n_Geocoding/` on
   `main`. Could you add them? The small samples would make good test fixtures.

## F. Reference sections and native-language names (data collection, NER, graph)

**F1. Reference sections are collected as text.** 5,021 of the 64,301 paragraphs (7.8 %) come from
sections that list article titles or books, not prose: "See also" (3,669), "Sources" (536),
"Further reading" (420), "References" (157), "Bibliography" (148), "Works cited", "Links"… For
example: `Ivanov, Henry, "Country Briefing: Russia—Austere Deterrence", Jane's Defence Weekly, 28
April 2006`. NER then finds "entities" in them: 2,212 entities are mentioned *only* there (`Andy`,
`Anti-Terrorist`, `Aviation`, `Battle`, `Belarus.`…), and they carry 8,339 relation records.
*What we do now:* the agent drops these paragraphs, their records and those entities when it loads
the graph (18 are kept because other places sit INSIDE them, see F3). The file is not changed.
*What would help:* the data-collection step skipping these sections, or NER ignoring them, or a flag
on the paragraph.

**F2. Native-language names in brackets become entities.** English articles give the original name
in brackets: `(Ukrainian: Закон України «Про засудження … в Україні …»)`. NER takes words from them
as entities: 1,458 entities have Cyrillic names (443 LOC, 542 PER, 473 ORG), 933 of them mentioned
outside reference sections (`область` = "oblast", `Кутузова`, `Российской Федерации`). The worst
case: `Україні` ("in Ukraine") is a LOC geocoded as an office near Maidan, so "what is within 500 m
of Maidan?" lists it as a place. *The agent doesn't filter these yet.* *What would help:* NER
skipping bracketed native-language names, or linking them to the English name (SAME_AS).

**F3. The INSIDE hierarchy hangs Russia's regions from `РФ`.** `Kursk Oblast` → … →
`Central Federal District` → `РФ` (Russian for "RF"), a name of Russia mentioned only in Russian
citation titles. Dropping reference sections (F1) removed it and cut every Russian region off from
Russia, until we kept such containers. *What would help:* INSIDE pointing at the main node
(`Russia`), which has the text.
