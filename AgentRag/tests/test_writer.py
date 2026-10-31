"""⑤ Write: citations checked by code, the no-data disclaimer, the template fallback. LLM faked."""
import httpx
import openai
from langchain_core.messages import AIMessage

from evidence import EvidencePack, build_evidence
from planner import Area, EntityMention, QueryPlan
from resolver import resolve
from retrieve import retrieve
from writer import NO_DATA_DISCLAIMER, WriteDraft, check_citations, cut_unfinished, strip_citations, write

UKRAINE_BOX = Area(kind="polygon", coordinates=[[[22, 44], [41, 44], [41, 53], [22, 53], [22, 44]]])


class FakeWriter:
    def __init__(self, draft=None, error=None):
        self.draft, self.error, self.messages = draft, error, None

    def with_structured_output(self, schema, **kwargs):
        assert schema is WriteDraft
        return self

    def invoke(self, messages):
        self.messages = messages
        if self.error:
            raise self.error
        raw = AIMessage(content="", response_metadata={"model_name": "fake/writer", "token_usage": {"cost": 0.001}},
                        usage_metadata={"input_tokens": 800, "output_tokens": 120, "total_tokens": 920})
        return {"raw": raw, "parsed": self.draft, "parsing_error": None}


def evidence_for(gi, qtype, *entities, **fields):
    plan = QueryPlan(question="q?", type=qtype, source="llm",
                     entities=[EntityMention(text=t, name=t, kind=k) for t, k in entities], **fields)
    return plan, build_evidence(plan, retrieve(plan, resolve(plan, gi), gi), gi)


def test_the_llm_reads_exactly_the_evidence_text_and_citations_are_kept(vr6_index):
    plan, pack = evidence_for(vr6_index, "event_places", ("Battle of Bakhmut", "EVENT"))
    fake = FakeWriter(WriteDraft(answer="The battle centred on Bakhmut [1] [L1] and spread to Soledar [2] [S2].",
                                 places_discussed=[1, 2], follow_ups=["Tell me about number 2"]))
    answer = write(plan, pack, fake)
    assert fake.messages[1][1].startswith("QUESTION: q?\nANSWER SHAPE:")
    assert answer.status == "answered" and answer.grounded
    assert answer.passages_cited == ["L1", "S2"] and answer.places_discussed == [1, 2]
    assert answer.removed_citations == [] and answer.llm_calls[0].step == "write"


def test_citations_that_point_at_nothing_are_removed(vr6_index):
    plan, pack = evidence_for(vr6_index, "event_places", ("Battle of Bakhmut", "EVENT"))
    answer = write(plan, pack, FakeWriter(WriteDraft(answer="Bakhmut [1] fell [S99] near Atlantis [42].",
                                                     places_discussed=[1, 42])))
    assert answer.text == "Bakhmut [1] fell near Atlantis."
    assert answer.removed_citations == ["[S99]", "[42]"] and answer.places_discussed == [1]
    assert any("point at nothing" in n for n in answer.notes)


def test_an_answer_cut_off_mid_sentence_loses_the_unfinished_sentence(vr6_index):
    plan, pack = evidence_for(vr6_index, "event_places", ("Battle of Bakhmut", "EVENT"))
    answer = write(plan, pack, FakeWriter(WriteDraft(
        answer="Bakhmut [1] was the centre [L1]. Soledar [2] fell first [S2]. Later it was said that the")))
    assert answer.text == "Bakhmut [1] was the centre [L1]. Soledar [2] fell first [S2]."
    assert any("mid-sentence" in n for n in answer.notes)


def test_cut_unfinished():
    assert cut_unfinished("Done. [S1]") == ("Done. [S1]", False)
    assert cut_unfinished('He said "yes."') == ('He said "yes."', False)
    assert cut_unfinished("No sentence end at all") == ("No sentence end at all", False)
    assert cut_unfinished("One [S1]. Two (in 2022) and") == ("One [S1].", True)


def test_at_most_two_passages_per_claim(vr6_index):
    plan, pack = evidence_for(vr6_index, "event_places", ("Battle of Bakhmut", "EVENT"))
    answer = write(plan, pack, FakeWriter(WriteDraft(answer="It spread [S99, S1, S2, L1] to Soledar [2].")))
    assert answer.text == "It spread [S1, S2] to Soledar [2]."      # an id that points at nothing takes no slot
    assert answer.passages_cited == ["S1", "S2"] and any("dropped L1" in n for n in answer.notes)


def test_strip_citations():
    assert strip_citations("Kyiv [5] is the capital [L1, S2].") == "Kyiv is the capital."
    assert strip_citations("President since 2019 [L1], [S5], [S26]. Kyiv [1] and Lviv [2].") == \
        "President since 2019. Kyiv and Lviv."


def test_check_citations_tidies_spacing():
    pack = EvidencePack(level="x")
    text, passages, places, removed, capped = check_citations("It happened [S3].", pack)
    assert text == "It happened." and removed == ["[S3]"]


def test_nothing_found_gives_a_labelled_llm_only_answer(vr6_index):
    plan, pack = evidence_for(vr6_index, "other")
    fake = FakeWriter(WriteDraft(answer="Generally speaking [S1], this is unknown."))
    answer = write(plan, pack, fake)
    assert answer.status == "no_data" and answer.grounded is False
    assert answer.text == f"{NO_DATA_DISCLAIMER} Generally speaking, this is unknown."
    assert "returned nothing" in fake.messages[0][1]


def test_out_of_scope_is_labelled_too(vr6_index):
    plan = QueryPlan(question="Pasta recipe?", type="out_of_scope", source="llm", in_scope=False)
    answer = write(plan, EvidencePack(level=""), FakeWriter(WriteDraft(answer="Boil water.")))
    assert answer.status == "out_of_scope" and answer.text.startswith(NO_DATA_DISCLAIMER)


def test_a_failed_list_answer_falls_back_to_a_template(vr6_index, monkeypatch):
    monkeypatch.setattr("evidence.LIST_MIN_PLACES", 6)   # the small test graph has only ~8 places here
    plan, pack = evidence_for(vr6_index, "area", area=UKRAINE_BOX)
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    fake = FakeWriter(error=openai.RateLimitError("busy", response=httpx.Response(429, request=request), body=None))
    answer = write(plan, pack, fake)
    assert pack.shape == "list" and answer.status == "answered"
    assert answer.text.startswith(f"{len(pack.places)} places were found; the strongest are")
    assert "All of them are on the map." in answer.text
    assert any("template answer" in n for n in answer.notes)


def test_a_failed_fact_answer_says_so(vr6_index):
    plan, pack = evidence_for(vr6_index, "place_lookup", ("Kyiv", "LOC"))
    answer = write(plan, pack, FakeWriter(draft=None))
    assert answer.status == "llm_failed" and answer.places_discussed == [1]


def test_follow_ups_are_capped(vr6_index):
    plan, pack = evidence_for(vr6_index, "place_lookup", ("Kyiv", "LOC"))
    answer = write(plan, pack, FakeWriter(WriteDraft(answer="Kyiv [1] is the capital [L1].",
                                                     follow_ups=["Tell me about Kyiv [1].", "Who attacked Kyiv?", " ",
                                                                 "What was the", "What happened in Kyiv?",
                                                                 "Kyiv again?"])))
    # whole questions, no citation marks, at most 3
    assert answer.follow_ups == ["Tell me about Kyiv.", "Who attacked Kyiv?", "What happened in Kyiv?"]


def test_follow_ups_must_name_something_in_the_material(vr6_index):
    plan, pack = evidence_for(vr6_index, "place_lookup", ("Kyiv", "LOC"))
    answer = write(plan, pack, FakeWriter(WriteDraft(answer="Kyiv [1] is the capital [L1].", follow_ups=[
        "What is the population of Kyiv?", "What is the capital of France?", "Tell me more about it."])))
    assert answer.follow_ups == ["What is the population of Kyiv?"]   # the prompt discourages the kind; code checks names
    assert any("name nothing in the material" in n for n in answer.notes)


def test_grouped_citations_are_checked_id_by_id(vr6_index):
    plan, pack = evidence_for(vr6_index, "event_places", ("Battle of Bakhmut", "EVENT"))
    answer = write(plan, pack, FakeWriter(WriteDraft(answer="It spread [S1, S99, L1] to Soledar [2; 77].")))
    assert answer.text == "It spread [S1, L1] to Soledar [2]."
    assert answer.passages_cited == ["S1", "L1"] and answer.removed_citations == ["[S99]", "[77]"]


class FlakyWriter(FakeWriter):
    def __init__(self, draft):
        super().__init__(draft)
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        out = super().invoke(messages)
        return {**out, "parsed": None} if self.calls == 1 else out


class PlainTextWriter(FakeWriter):
    """A model that writes its answer as plain text instead of filling in the structure."""

    def __init__(self, text):
        super().__init__(None)
        self.text = text

    def invoke(self, messages):
        out = super().invoke(messages)
        out["raw"] = AIMessage(content=self.text, response_metadata=out["raw"].response_metadata,
                               usage_metadata=out["raw"].usage_metadata)
        return out


def test_a_plain_text_answer_is_used_and_still_checked(vr6_index):
    plan, pack = evidence_for(vr6_index, "place_lookup", ("Kyiv", "LOC"))
    answer = write(plan, pack, PlainTextWriter("Kyiv [1] is the capital of Ukraine [L1] [S77]."))
    assert answer.status == "answered" and answer.text == "Kyiv [1] is the capital of Ukraine [L1]."
    assert answer.llm_calls[0].raw_text.startswith("Kyiv [1]") and answer.removed_citations == ["[S77]"]
    assert any("plain text" in n for n in answer.notes)


def test_json_written_as_text_is_read_as_the_structure(vr6_index):
    plan, pack = evidence_for(vr6_index, "place_lookup", ("Kyiv", "LOC"))
    text = '```json\n{"answer": "Kyiv [1] is the capital [L1].", "places_discussed": [1], "follow_ups": ["More on Kyiv?"]}\n```'
    answer = write(plan, pack, PlainTextWriter(text))
    assert answer.text == "Kyiv [1] is the capital [L1]." and answer.follow_ups == ["More on Kyiv?"]


def test_the_write_step_retries_once(vr6_index):
    plan, pack = evidence_for(vr6_index, "place_lookup", ("Kyiv", "LOC"))
    fake = FlakyWriter(WriteDraft(answer="Kyiv [1] is the capital [L1]."))
    answer = write(plan, pack, fake)
    assert fake.calls == 2 and answer.status == "answered" and answer.passages_cited == ["L1"]
