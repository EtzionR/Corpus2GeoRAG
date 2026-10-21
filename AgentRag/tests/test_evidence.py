"""④ Evidence: sentences, levels, budget, numbering, amounts, and the text the LLM will read."""
from evidence import build_evidence, render_for_llm, sentence_ranges, window
from planner import Area, Concept, ConceptCandidate, EntityMention, QueryPlan
from resolver import resolve
from retrieve import retrieve


def pack_for(gi, qtype, *entities, budget=2000, **fields):
    plan = QueryPlan(question="q?", type=qtype, source="llm",
                     entities=[EntityMention(text=t, name=t, kind=k) for t, k in entities], **fields)
    ret = retrieve(plan, resolve(plan, gi), gi)
    return plan, ret, build_evidence(plan, ret, gi, budget_words=budget)


def test_sentences_ignore_abbreviations_and_initials():
    text = "Gen. Gerasimov met U.S. officials in Kyiv. V. Putin was not there! Then they left."
    assert [text[a:b] for a, b in sentence_ranges(text)] == [
        "Gen. Gerasimov met U.S. officials in Kyiv.", "V. Putin was not there!", "Then they left."]


def test_window_covers_the_spans_sentences():
    text = "First one. Bakhmut was hit. Wagner attacked it. Last one."
    a, b = window(text, [[11, 18], [28, 34]])
    assert text[a:b] == "Bakhmut was hit. Wagner attacked it."


def test_a_small_result_gets_whole_paragraphs_with_numbered_places(vr6_index):
    _, _, pack = pack_for(vr6_index, "event_places", ("Battle of Bakhmut", "EVENT"))
    assert pack.level.startswith("L1+L3")
    assert [p.id for p in pack.passages][:2] == ["L1", "S1"] and pack.passages[0].kind == "summary"
    assert [(p.number, p.id, p.in_text) for p in pack.places] == [(1, "Bakhmut", True), (2, "Soledar", True)]
    soledar = next(p for p in pack.passages if "[2]" in p.about)
    assert "Soledar" in soledar.text and "[1]" in soledar.about   # one passage describes both places


def test_amounts_are_measured_at_every_level(vr6_index):
    _, _, pack = pack_for(vr6_index, "event_places", ("Battle of Bakhmut", "EVENT"))
    am = pack.amounts
    assert am.places_found == 2 and am.pointers >= 4
    assert 0 < am.words_all_sentences <= am.words_all_paragraphs
    assert am.words_included == sum(p.words for p in pack.passages)


def test_a_tight_budget_is_respected_and_the_rest_is_counted(vr6_index):
    box = Area(kind="polygon", coordinates=[[[22, 44], [41, 44], [41, 53], [22, 53], [22, 44]]])
    _, _, pack = pack_for(vr6_index, "area", area=box, budget=20, needs="detailed_text")
    sentences = [p for p in pack.passages if p.kind != "summary"]
    assert sum(p.words for p in sentences) <= 20
    assert any("didn't fit the 20-word budget" in n for n in pack.notes)


def test_every_top_item_gets_a_sentence_before_any_gets_a_second(vr6_index):
    box = Area(kind="polygon", coordinates=[[[22, 44], [41, 44], [41, 53], [22, 53], [22, 44]]])
    _, ret, pack = pack_for(vr6_index, "area", area=box, budget=60, needs="detailed_text")
    first_labels = [p.about[0] for p in pack.passages if p.kind != "summary"][:3]
    assert len(set(first_labels)) == len(first_labels)   # three different places first


def test_relation_question_puts_records_first_and_flags_low_confidence(vr6_index):
    _, _, pack = pack_for(vr6_index, "about", ("Black Sea Fleet", "ORG"), relations=["LEADS"])
    sentence = next(p for p in pack.passages if p.kind != "summary")
    assert sentence.low_confidence and "Viktor Sokolov LEADS Black Sea Fleet" in sentence.about
    assert "LOW-CONFIDENCE relation" in render_for_llm(pack, "Who commands the Black Sea Fleet?")


def test_place_lookup_is_places_and_summary_only_and_warns_on_a_doubtful_point(vr6_index):
    _, _, pack = pack_for(vr6_index, "place_lookup", ("Donbas", "LOC"))
    assert pack.level.startswith("L0+L1") and all(p.kind == "summary" for p in pack.passages)
    text = render_for_llm(pack, "Where is Donbas?")
    assert "[1] Donbas (road; Donbas, Skopje, North Macedonia)" in text
    assert "the graph's point for this place may be wrong: geocoded as a road" in text


def test_the_rendered_text_has_question_places_and_cited_passages(vr6_index):
    plan, _, pack = pack_for(vr6_index, "event_places", ("Battle of Bakhmut", "EVENT"))
    text = render_for_llm(pack, "Show me the places of the Battle of Bakhmut")
    assert text.startswith("QUESTION: Show me the places of the Battle of Bakhmut")
    assert "PLACES FOUND: 2 (all are shown on the map; cite them by number)" in text
    assert '[L1] (summary of "Battle of Bakhmut")' in text and "[S1] (about [1]" in text


def test_who_question_with_two_places(vr6_index):
    _, _, pack = pack_for(vr6_index, "relation", ("Ukraine", "LOC"), ("Russia", "LOC"), relations=["LEADS"])
    abouts = [a for p in pack.passages for a in p.about]
    assert "Vladimir Putin LEADS Russia" in abouts and "Petro Poroshenko LEADS Ukraine" in abouts


# --- answer shapes (P2-48) and the region overview (P2-49) ----------------------------------

UKRAINE_BOX = Area(kind="polygon", coordinates=[[[22, 44], [41, 44], [41, 53], [22, 53], [22, 44]]])


def test_many_places_give_a_list_answer_with_data_lines_and_no_sentences(vr6_index, monkeypatch):
    monkeypatch.setattr("evidence.LIST_MIN_PLACES", 6)   # the small test graph has only ~8 places here
    _, ret, pack = pack_for(vr6_index, "area", area=UKRAINE_BOX)
    assert pack.shape == "list" and len(ret.places) > 6
    assert all(p.kind == "summary" for p in pack.passages)          # no corpus sentences
    assert all(p.why for p in pack.places[:10])                     # one data line each
    text = render_for_llm(pack, "What is in Ukraine?")
    assert "ANSWER SHAPE: list" in text and "BY REGION (from the graph's place hierarchy):" in text


def test_region_overview_nests_places_under_their_country(vr6_index, monkeypatch):
    monkeypatch.setattr("evidence.LIST_MIN_PLACES", 6)
    _, _, pack = pack_for(vr6_index, "area", area=UKRAINE_BOX)
    ukraine = next(r for r in pack.regions if r.id == "Ukraine")
    numbers = {p.id: p.number for p in pack.places}
    assert {numbers[n] for n in ("Bakhmut", "Kharkiv", "Kyiv", "Soledar") if n in numbers} <= set(ukraine.places)
    assert ukraine.count == len(ukraine.places) + sum(c.count for c in ukraine.children)


def test_a_region_appears_once_in_the_overview(vr6_index, monkeypatch):
    import graph_tools as T
    # two names of one group in the INSIDE chain (the real graph: Donetsk inside Donetsk)
    monkeypatch.setattr(T, "parents", lambda gi, name: [name, "Ukraine", "Ukraine"])
    tree = T.region_tree(vr6_index, [(1, T.Hit(group=vr6_index.group("Soledar")))])
    assert [(n.id, n.places, n.children) for n in tree] == [("Ukraine", [1], [])]


def test_who_question_is_a_fact_answer(vr6_index):
    _, _, pack = pack_for(vr6_index, "relation", ("Ukraine", "LOC"), ("Russia", "LOC"), relations=["LEADS"])
    assert pack.shape == "fact" and pack.amounts.budget_words == 600
    assert all(p.kind == "summary" or "LEADS" in p.about[0] for p in pack.passages)


def test_place_lookup_is_a_fact_answer(vr6_index):
    _, _, pack = pack_for(vr6_index, "place_lookup", ("Kyiv", "LOC"))
    assert pack.shape == "fact" and pack.places[0].in_text and pack.passages[0].article == "Kyiv"


def test_an_entity_at_a_place_is_a_drilldown(vr6_index):
    _, ret, pack = pack_for(vr6_index, "about", ("Zelenskyy", "PER"), ("Kharkiv", "LOC"))
    assert ret.route.startswith("drill-down: what links Zelenskyy and Kharkiv")
    assert pack.shape == "drilldown" and [r.relation for r in ret.records] == ["VISITED"]
    sentence = next(p for p in pack.passages if p.kind != "summary")
    assert "Zelenskyy visited Kharkiv" in sentence.text


def test_found_by_says_what_a_match_means(vr6_index):
    box = Area(kind="polygon", coordinates=[[[37, 48], [39, 48], [39, 49], [37, 49], [37, 48]]])
    _, _, pack = pack_for(vr6_index, "area_topic", area=box, keywords=["drone"], relations=["ATTACKED"])
    assert pack.found_by == "places inside the map area whose paragraphs mention: drone; ranked by ATTACKED records"
    assert "FOUND BY: places inside the map area whose paragraphs mention: drone" in render_for_llm(pack, "q")



def test_a_short_list_is_described_place_by_place(vr6_index):
    _, ret, pack = pack_for(vr6_index, "area", area=UKRAINE_BOX)   # <= 10 places
    assert len(ret.places) <= 10 and pack.shape == "explain"
    assert any(p.kind != "summary" for p in pack.passages)


def test_list_routes_put_specific_places_before_regions_and_countries(vr6_index):
    _, ret, _ = pack_for(vr6_index, "area", area=UKRAINE_BOX)
    import graph_tools as T
    tiers = [T.tier(h) for h in ret.places]
    assert tiers == sorted(tiers) and tiers[-1] == 2      # Ukraine (a country) comes last
    assert ret.places[-1].group.id == "Ukraine"
