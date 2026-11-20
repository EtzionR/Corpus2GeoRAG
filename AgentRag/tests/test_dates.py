"""Dates (P2-80): the question's time words, the date route, the period first, and each passage's date. No LLM."""
from conftest import build_vr6_graph

import dates as D
from evidence import build_evidence, render_for_llm
from graph_index import GraphIndex
from planner import PlanDraft, _finalize
from resolver import resolve
from retrieve import retrieve

DAY = {"granularity": "day", "from": "2022-02-24", "to": "2022-02-24", "year_inferred": False}


def _dated(text: str, mention: str, when: dict) -> dict:
    start = text.index(mention)
    return {"start": start, "end": start + len(mention), "text": mention, **when}


def graph_with_dates() -> GraphIndex:
    """The test graph plus three dated paragraphs, as in Graph_n_Geocoding/with_dates."""
    G = build_vr6_graph()
    paragraphs = [
        ("On 24 February 2022, Russian forces struck Kyiv and Kharkiv. Wagner Group fighters waited.",
         "24 February 2022", DAY, ["Kyiv", "Kharkiv", "Wagner Group"]),
        ("Kyiv was quiet in 2019. Fighting reached Bakhmut in May 2023.",
         "May 2023", {"granularity": "month", "from": "2023-05-01", "to": "2023-05-31", "year_inferred": False},
         ["Kyiv", "Bakhmut"]),
        ("The war began in 2022 in Kyiv.", "2022",
         {"granularity": "year", "from": "2022-01-01", "to": "2022-12-31", "year_inferred": False}, ["Kyiv"]),
    ]
    for i, (text, mention, when, names) in enumerate(paragraphs):
        tid = 9500 + i
        G.add_node(f"TEXT_{tid}", type="TEXT", text_id=tid, text=text, source="Timeline", index=i, title=None,
                   sub_title=None, dates=[_dated(text, mention, when)])
        for name in names:
            s = text.index(name)
            G.add_edge(name, f"TEXT_{tid}", weight=1, relations={"IN_THE_TEXT": [{"start": s, "end": s + len(name)}]})
    G.add_node("DATE_2022-02-24", type="DATE", granularity="day", **{"from": "2022-02-24", "to": "2022-02-24"})
    G.add_edge("DATE_2022-02-24", "TEXT_9500", weight=1, relations={"IN_THE_TEXT": [{"start": 3, "end": 19}]})
    return GraphIndex(G)


def plan_for(question: str, time_words: list[str], entities=()):
    from planner import EntityMention
    draft = PlanDraft(type="about", time_words=time_words,
                      entities=[EntityMention(text=n, name=n, kind=k) for n, k in entities])
    return _finalize(draft, question, None, [])


def test_time_words_become_a_calendar_range():
    cases = {("on 24 February 2022",): ("2022-02-24", "2022-02-24", "24 February 2022"),
             ("February 24th, 2022",): ("2022-02-24", "2022-02-24", "24 February 2022"),
             ("in February 2022",): ("2022-02-01", "2022-02-28", "February 2022"),
             ("in 2023",): ("2023-01-01", "2023-12-31", "2023"),
             ("since February 2022",): ("2022-02-01", D.FAR_FUTURE, "since February 2022"),
             ("before 2014",): (D.FAR_PAST, "2014-12-31", "up to 2014"),
             ("from March to May 2022",): ("2022-03-01", "2022-05-31", "March – May 2022"),
             ("24–25 February 2022",): ("2022-02-24", "2022-02-25", "24–25 February 2022"),
             ("in 2022", "in 2023"): ("2022-01-01", "2023-12-31", "2022 – 2023")}
    for words, expected in cases.items():
        p = D.parse_period(list(words))
        assert (p.start, p.end, p.label) == expected, words
    assert D.parse_period(["in February"]) is None and D.parse_period(["recently"]) is None   # no year: no range


def test_a_coarser_date_does_not_count_inside_a_day():
    day = D.parse_period(["24 February 2022"])
    assert D.within(DAY, day) and not D.within({"from": "2022-01-01", "to": "2022-12-31"}, day)


def test_a_passage_takes_its_own_dates_or_the_last_one_before_it():
    text = "On 24 February 2022, Russia attacked. Later that day, troops entered Kharkiv."
    node = {"text": text, "dates": [_dated(text, "24 February 2022", DAY)]}
    assert D.passage_dates(node, 0, 37) == (node["dates"], "passage")
    assert D.passage_dates(node, 38, len(text)) == (node["dates"], "paragraph")
    assert D.describe(node["dates"]) == "24 February 2022"


def test_only_a_date_named_goes_to_the_date_route():
    plan = plan_for("What happened on 24 February 2022?", ["24 February 2022"])
    assert plan.type == "date" and plan.period.label == "24 February 2022"
    with_place = plan_for("What happened in Kyiv on 24 February 2022?", ["on 24 February 2022"], [("Kyiv", "LOC")])
    assert with_place.type == "about" and with_place.period.start == "2022-02-24"   # a place named: about it, by date
    assert plan_for("Tell me about Kyiv", [], [("Kyiv", "LOC")]).period is None


def test_the_date_route_reads_the_names_in_the_dated_sentence():
    gi = graph_with_dates()
    plan = plan_for("What happened on 24 February 2022?", ["24 February 2022"])
    ret = retrieve(plan, resolve(plan, gi), gi)
    # Kyiv and Kharkiv share the date's sentence; Wagner Group is in the next one, and the "2022" paragraph doesn't count
    assert [h.group.id for h in ret.places] == ["Kyiv", "Kharkiv"] and ret.entities == []
    assert {p.text_id for h in ret.places for p in h.pointers} == {9500}
    pack = build_evidence(plan, ret, gi)
    assert pack.shape == "explain" and pack.passages[0].date == "24 February 2022"
    text = render_for_llm(pack, plan.question)
    assert "PERIOD ASKED: 24 February 2022" in text and "date: 24 February 2022)" in text


def test_a_period_puts_the_paragraphs_dated_in_it_first():
    gi = graph_with_dates()
    plan = plan_for("What happened in Bakhmut in 2023?", ["in 2023"], [("Bakhmut", "LOC")])
    ret = retrieve(plan, resolve(plan, gi), gi)
    bakhmut = ret.places[0]
    assert bakhmut.group.id == "Bakhmut" and [p.text_id for p in bakhmut.pointers] == [9501]   # its 2023 paragraph
    pack = build_evidence(plan, ret, gi)
    dated = [p for p in pack.passages if p.text_id == 9501]
    assert dated and dated[0].date == "May 2023" and dated[0].date_scope == "passage"
    assert pack.passages.index(dated[0]) == next(i for i, p in enumerate(pack.passages) if p.kind != "summary")


def test_the_graph_without_dates_answers_a_date_question_with_no_data():
    gi = GraphIndex(build_vr6_graph())
    plan = plan_for("What happened on 24 February 2022?", ["24 February 2022"])
    ret = retrieve(plan, resolve(plan, gi), gi)
    assert ret.places == [] and any("no dates" in n for n in ret.notes)
    assert not D.has_dates(gi) and build_evidence(plan, ret, gi).passages == []
