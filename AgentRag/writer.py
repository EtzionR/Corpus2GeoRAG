"""⑤ Write: the evidence text in, the answer out (the second LLM call).

The LLM reads exactly the text step ④ rendered (render_for_llm): the answer shape, the numbered places
with their data lines, the region overview, and the numbered passages. It writes the answer citing
places as [3] and passages as [S2] / [L1]. Code then checks the citations: anything that doesn't exist
in the evidence is removed and noted, so every citation in an answer points at real material.

When the graph returned nothing (or the question is off-topic), the LLM answers briefly from its own
knowledge and the answer is labelled "No data from the graph — answer from the LLM only."
(DECISIONS_LOG P2-8). If the LLM call fails, a list answer falls back to a template built from the
data lines; other shapes report the failure with the sources still listed.
"""
import json
import re
from typing import Literal, Optional

import openai
from langchain_core.exceptions import OutputParserException
from pydantic import BaseModel, Field, ValidationError

from evidence import LIST_TOP, EvidencePack, render_for_llm
from llm_calls import LLMCall, structured_call
from planner import QueryPlan, question_for_answer

NO_DATA_DISCLAIMER = "No data from the graph — answer from the LLM only."
MAX_FOLLOW_UPS = 3
MAX_PASSAGES_PER_CLAIM = 2   # P2-62: "[1, S4, S13, S20, S29]" is unreadable; two clear sources are enough

WRITE_PROMPT = """You write the answer to a question about the Russia-Ukraine war, using ONLY the material
given: the places found, the people and organizations found, the region overview, and the numbered
passages from the corpus (Wikipedia articles). Never add facts from your own knowledge.

The places are listed strongest first (the order already reflects what links them to the question), so
when naming "the strongest few", take them from the top of the list. The data line after each place
holds counts from the graph (paragraphs, relation records), not counts of events: "ATTACKED 12; 118
paragraphs" means 118 paragraphs match and 12 of them record an attack, not that there were 12 attacks.

The FOUND BY line says how the places were found; it tells you what a match means (for example, that
every place has paragraphs mentioning drones), even when no passages are given.

Write ONE answer, in the shape named on the ANSWER SHAPE line only (the others are for other questions):
- list: 2-4 sentences. If a summary passage about the subject is given ([L1]), the FIRST sentence says
  what the subject is, in the summary's own facts, and ends with [L1] (for example: "<subject> was <what,
  when, where and between whom, as the summary says> [L1]."). Only then, in a new sentence, say how many
  places were found, name the strongest few by number, and use the region overview to say where they
  concentrate. The map shows every place; don't list them all.
- fact: a short, direct answer (1-3 sentences) with the passages that support it.
- drilldown: one focused paragraph about this entity at this place, in date order when dates are given.
- explain: one or two paragraphs built from the passages: for each place (or each part of the subject),
  say what its passages say, citing them. Don't stop at naming the places or calling them "the strongest".

Citing: put a place's number in square brackets right after its name, like Kyiv [5], and passage ids
after the claim they support, like [S2] or [L1]. Cite at most two passages per claim (the clearest),
and don't put place numbers and passage ids in the same brackets. Cite only numbers and ids that appear
in the material.
If a passage is marked LOW-CONFIDENCE, say the corpus only suggests it.
If the graph's point for a place may be wrong, mention that.
If the material doesn't answer the question, say so plainly instead of guessing.
In places_discussed, list the numbers of the places your answer talks about.

Suggest up to 3 follow-up questions the user could ask next. Each one must name a place, person,
organization or event that appears in the material above, by its name (not "it" or "number 2"), and be
one of these kinds, which the knowledge graph can answer: "Tell me about <name>", "Which places are
linked to <person, organization or event>?", "Who attacked <place>?", "What happened in <place>?",
"<person> in <place>". Don't ask for facts the material doesn't hold (populations, definitions, capitals)."""

NO_DATA_PROMPT = """The knowledge graph of the Russia-Ukraine war corpus returned nothing for this question.
Answer it briefly (2-3 sentences) from general knowledge, or say you don't know. Don't cite anything."""


class WriteDraft(BaseModel):
    answer: str = Field(description="The answer, with citations like [3] for places and [S2] / [L1] for passages.")
    places_discussed: list[int] = Field(default_factory=list,
                                        description="Numbers of the places the answer talks about.")
    follow_ups: list[str] = Field(default_factory=list, description="Up to 3 short follow-up questions.")


class Answer(BaseModel):
    text: str
    status: Literal["answered", "no_data", "out_of_scope", "llm_failed"]
    grounded: bool                                   # True: built from the graph's material
    shape: str
    places_discussed: list[int] = Field(default_factory=list)
    passages_cited: list[str] = Field(default_factory=list)
    follow_ups: list[str] = Field(default_factory=list)
    removed_citations: list[str] = Field(default_factory=list)   # cited by the LLM but not in the evidence
    llm_calls: list[LLMCall] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


# A citation group: [3], [S2], or several ids in one bracket, like [S4, S10] or [2; L1].
_CITATION = re.compile(r"\[\s*((?:[SL]?\d+)(?:\s*[,;]\s*[SL]?\d+)*)\s*\]")
_CITATION_RUN = re.compile(rf"{_CITATION.pattern}(?:\s*[,;]?\s*{_CITATION.pattern})*")


def check_citations(text: str, pack: EvidencePack) -> tuple[str, list[str], list[int], list[str], list[str]]:
    """Keep only citation ids that exist in the evidence; a group like [S4, S99] keeps [S4], and at most
    MAX_PASSAGES_PER_CLAIM passages per group. Returns (text, passages cited, places cited, removed ids,
    ids dropped by the cap)."""
    passage_ids = {p.id for p in pack.passages}
    place_numbers = {p.number for p in pack.places}
    cited_passages, cited_places, removed, capped = [], [], [], []

    def keep(m):
        kept, passages = [], 0
        for token in re.split(r"\s*[,;]\s*", m.group(1)):
            if token[0] in "SL" and token in passage_ids and passages >= MAX_PASSAGES_PER_CLAIM:
                capped.append(token)
            elif token[0] in "SL" and token in passage_ids:
                passages += 1
                cited_passages.append(token)
                kept.append(token)
            elif token.isdigit() and int(token) in place_numbers:
                cited_places.append(int(token))
                kept.append(token)
            else:
                removed.append(f"[{token}]")
        return f"[{', '.join(kept)}]" if kept else ""

    text = _tidy(_CITATION.sub(keep, text))
    return text, list(dict.fromkeys(cited_passages)), list(dict.fromkeys(cited_places)), removed, capped


def grounded_follow_ups(follow_ups: list[str], pack: EvidencePack) -> tuple[list[str], list[str]]:
    """Keep the follow-ups that name something in the material (a place, a person or organization, an
    article), so the next question can be answered from the graph: "What is the capital of Ukraine?"
    with no passage about it goes. Returns (kept, dropped)."""
    names = ({p.label for p in pack.places} | {e.id for e in pack.entities} | {p.article for p in pack.passages}
             | {a for p in pack.passages for a in p.about if not a.startswith("[")})
    names = {n.lower() for n in names if len(n) >= 3}
    kept, dropped = [], []
    for f in follow_ups:
        low = f.lower()
        named = any(re.search(rf"(?<!\w){re.escape(n)}(?!\w)", low) for n in names)
        (kept if named else dropped).append(f)
    return kept, dropped


def strip_citations(text: str) -> str:
    """The text without [3] / [S2] marks: for follow-ups, and for UIs that show the answer plain.
    A run of marks goes with the commas between them ("since 2019 [L1], [S5]." -> "since 2019.")."""
    return _tidy(_CITATION_RUN.sub("", text))


def _tidy(text: str) -> str:
    """Spacing after removing citations: no double spaces, no space before punctuation."""
    return re.sub(r"\s+([.,;:!?])", r"\1", re.sub(r"[ \t]{2,}", " ", text)).strip()


_FINISHED = re.compile(r"([.!?][\"')]*|\])$")                      # ends a sentence, or ends on a citation
_SENTENCE_END = re.compile(r"[.!?][\"')]*(?:\s*\[[^\]]*\])?(?=\s)")


def cut_unfinished(text: str) -> tuple[str, bool]:
    """Models sometimes stop mid-sentence. Cut back to the last whole sentence (if there is one).
    Returns (text, whether something was cut)."""
    body = text.rstrip()
    if not body or _FINISHED.search(body):
        return body, False
    ends = [m.end() for m in _SENTENCE_END.finditer(body)]
    return (body[:ends[-1]], True) if ends else (body, False)


def draft_from_text(text: str) -> Optional[WriteDraft]:
    """A model that skips the structure sometimes writes the JSON as text, or just the answer."""
    body = text.strip()
    fenced = re.search(r"\{.*\}", body, re.S)
    if fenced:
        try:
            return WriteDraft.model_validate(json.loads(fenced.group(0)))
        except (ValueError, ValidationError):
            pass
    return WriteDraft(answer=body) if len(body.split()) >= 5 else None


def is_empty(pack: EvidencePack) -> bool:
    return not pack.places and not pack.entities and not pack.passages


def template_list_answer(pack: EvidencePack) -> str:
    """A list answer without any LLM: built from the data lines and the region overview."""
    top = ", ".join(f"{p.label} [{p.number}]" for p in pack.places[:5])
    text = f"{len(pack.places)} places were found; the strongest are {top}."
    if pack.regions:
        r = pack.regions[0]
        inner = ", ".join(f"{c.id} ({c.count})" for c in r.children[:3])
        text += f" Most are in {r.id} ({r.count})" + (f", especially {inner}" if inner else "") + "."
    return text + " All of them are on the map."


def write(plan: QueryPlan, pack: EvidencePack, llm) -> Answer:
    """Write the answer for one question from its evidence pack."""
    fu = plan.follow_up
    if fu and fu.kind == "item" and fu.item_number and not fu.target_id:   # "number 4" of a 1-place answer
        return Answer(text=f"The previous answer has no place number {fu.item_number}. Ask about one of the "
                           f"numbered places on the map.", status="no_data", grounded=False, shape=pack.shape)
    if pack.needs_area:   # "Show me where drone attacks happened": ask for the area, don't search everything (P2-75)
        topic = " ".join(plan.keywords)
        example = f' (for example "{topic} in Kharkiv")' if topic else ""
        return Answer(text="There is no area to search: the question names no place with a map location, and "
                           "nothing is selected on the map. Draw a box or pick a point on the map and ask again, "
                           f"or name a place{example}.", status="no_data", grounded=False, shape=pack.shape)
    if plan.type == "out_of_scope" or is_empty(pack):
        return _no_data_answer(plan, pack, llm)
    answer = Answer(text="", status="answered", grounded=True, shape=pack.shape)
    draft = None
    for attempt in (1, 2):   # one retry when the model answers without filling in the structure
        try:
            draft, call = structured_call(llm, WriteDraft, [("system", WRITE_PROMPT),
                                                            ("human", render_for_llm(pack, question_for_answer(plan)))], step="write")
            answer.llm_calls.append(call)
        except (ValidationError, OutputParserException, ValueError) as e:
            answer.notes.append(f"write attempt {attempt} failed ({type(e).__name__})")
        except openai.APIError as e:   # rate limit, network: retrying right away won't help
            answer.notes.append(f"the write call failed ({type(e).__name__})")
            break
        if draft is None and answer.llm_calls and answer.llm_calls[-1].raw_text:
            draft = draft_from_text(answer.llm_calls[-1].raw_text)
            if draft is not None:
                answer.notes.append("the model answered in plain text instead of the structure; that text is used")
        if draft is not None:
            break
    if draft is None:
        return _fallback(answer, pack)
    body, cut = cut_unfinished(draft.answer)
    text, passages, places, removed, capped = check_citations(body, pack)
    numbers = {p.number for p in pack.places}
    answer.text = text
    answer.passages_cited, answer.removed_citations = passages, removed
    answer.places_discussed = list(dict.fromkeys([n for n in draft.places_discussed if n in numbers] + places))
    # a follow-up must be a whole question or request (models sometimes cut the last one off)
    # and reads as a question the user could type: no citation marks ("Tell me about Bakhmut [1].")
    whole = [strip_citations(f) for f in draft.follow_ups if f.strip().endswith(("?", "."))]
    answer.follow_ups, ungrounded = grounded_follow_ups(whole, pack)
    answer.follow_ups = answer.follow_ups[:MAX_FOLLOW_UPS]
    if ungrounded:
        answer.notes.append(f"dropped follow-ups that name nothing in the material: {' | '.join(ungrounded)}")
    if removed:
        answer.notes.append(f"removed citations that point at nothing: {' '.join(removed)}")
    if cut:
        answer.notes.append("the model stopped mid-sentence; the unfinished last sentence was cut")
    if capped:
        answer.notes.append(f"kept at most {MAX_PASSAGES_PER_CLAIM} passages per claim; dropped {' '.join(capped)}")
    if not passages and any(p.kind != "summary" for p in pack.passages):
        answer.notes.append("the answer cites no passage although passages were given")
    return answer


def _fallback(answer: Answer, pack: EvidencePack) -> Answer:
    if pack.shape == "list" and pack.places:
        answer.text = template_list_answer(pack)
        answer.places_discussed = [p.number for p in pack.places[:5]]
        answer.notes.append("template answer (no LLM): built from the data lines")
    else:
        answer.status = "llm_failed"
        answer.text = "The answer couldn't be written this time; the places and sources found are listed."
        answer.places_discussed = [p.number for p in pack.places[:LIST_TOP]]
    return answer


def _no_data_answer(plan: QueryPlan, pack: EvidencePack, llm) -> Answer:
    status = "out_of_scope" if plan.type == "out_of_scope" else "no_data"
    answer = Answer(text="", status=status, grounded=False, shape=pack.shape)
    try:
        draft, call = structured_call(llm, WriteDraft, [("system", NO_DATA_PROMPT),
                                                        ("human", f"QUESTION: {plan.question}")], step="write")
        answer.llm_calls.append(call)
        body = draft.answer.strip() if draft else "I don't know."
    except (openai.APIError, ValidationError, OutputParserException, ValueError) as e:
        body = "No answer is available right now."
        answer.notes.append(f"the write call failed ({type(e).__name__})")
    body = _tidy(_CITATION.sub("", body))   # nothing to cite: the graph gave nothing
    answer.text = f"{NO_DATA_DISCLAIMER} {body}"
    return answer
