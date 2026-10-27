"""② Resolve: match the names in a plan to graph nodes (and events to articles).

Matching order for each name (P2-12): exact → normalized spelling → all distinctive words present →
fuzzy. A fuzzy match must have a similar word for every distinctive word of the query, so generic
words alone ("Armed", "Forces") never make a match. Events are matched against article titles,
because in this graph a battle or attack is an article, not a node.

When several different groups match, the strongest wins if it clearly dominates; otherwise a tiny
LLM call picks the one the question means (P2-11, P2-34), and if it can't tell, the strongest wins.
The other candidates always come back as `alternatives` ("did you mean").
"""
import logging
import time
from difflib import get_close_matches
from typing import Literal, Optional

import openai
from pydantic import BaseModel, Field

from graph_index import GraphIndex, Group, distinctive, normalize, similar, words
from llm_calls import LLMCall, structured_call
from planner import QueryPlan

logger = logging.getLogger(__name__)

DOMINANCE = 3.0          # the strongest group wins outright if it has 3x the texts of the next one
FUZZY_CUTOFF = 0.8
WORD_SIMILARITY = 0.8
MAX_ALTERNATIVES = 3
MAX_WORD_MATCHES = 25    # more different groups than this sharing the query's words = too vague

How = Literal["exact", "normalized", "words", "fuzzy", "article", "article_fuzzy"]
PickedBy = Literal["only match", "dominant", "llm", "strongest"]


class ArticleRef(BaseModel):
    title: str
    paragraphs: int
    lead_sentence: Optional[str] = None


class ResolvedName(BaseModel):
    text: str                                  # as the user wrote it
    name: str                                  # as the plan spelled it
    kind: str                                  # PER / ORG / LOC / EVENT / UNKNOWN (from the plan)
    status: Literal["resolved", "not_found"]
    how: Optional[How] = None
    picked_by: Optional[PickedBy] = None
    group: Optional[Group] = None
    article: Optional[ArticleRef] = None
    alternatives: list[Group] = Field(default_factory=list)


class ResolvedConcept(BaseModel):
    text: str
    candidates: list[ResolvedName] = Field(default_factory=list)


class Resolution(BaseModel):
    entities: list[ResolvedName] = Field(default_factory=list)
    concepts: list[ResolvedConcept] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    llm_calls: list[LLMCall] = Field(default_factory=list)
    seconds: float = 0.0


class CandidatePick(BaseModel):
    choice: str = Field(description="The id of the candidate the question means, or 'unsure'.")


PICK_PROMPT = """A question names something that matches several different entries in a knowledge
graph built from Wikipedia articles about the Russia-Ukraine war. Pick the entry the question means,
using only the question's own wording. Answer with the entry's id, or 'unsure' if the question
doesn't make it clear."""


# --- Resolving a plan ------------------------------------------------------------------------

def resolve(plan: QueryPlan, gi: GraphIndex, llm=None) -> Resolution:
    start = time.time()
    res = Resolution()
    for e in plan.entities:
        res.entities.append(resolve_name(e.text, e.name, e.kind, gi, plan.question, llm, res))
    for c in plan.concepts:
        rc = ResolvedConcept(text=c.text)
        for cand in c.candidates:
            # Concept candidates are guesses, so only firm matches count (no fuzzy, no LLM pick).
            r = resolve_name(cand.name, cand.name, cand.kind, gi, plan.question, None, res, allow_fuzzy=False)
            rc.candidates.append(r)
        res.concepts.append(rc)
    if plan.follow_up and plan.follow_up.target_id:
        gid = gi.group_of.get(plan.follow_up.target_id)
        if gid and gid not in {e.group.id for e in res.entities if e.group}:   # not already named
            res.entities.append(ResolvedName(text=plan.follow_up.target_label or gid, name=gid, kind="UNKNOWN",
                                             status="resolved", how="exact", picked_by="only match",
                                             group=gi.group(gid)))
    res.seconds = round(time.time() - start, 2)
    return res


def resolve_name(text: str, name: str, kind: str, gi: GraphIndex, question: str, llm, res: Resolution,
                 allow_fuzzy: bool = True) -> ResolvedName:
    out = ResolvedName(text=text, name=name, kind=kind, status="not_found")
    queries = list(dict.fromkeys([name, text]))   # the plan's spelling first, then the user's own

    if kind == "EVENT":
        if _match_article(out, queries, gi, allow_fuzzy):
            return out
    for q in queries:
        how, groups = _match_nodes(q, gi, kind, allow_fuzzy)
        if groups:
            _pick(out, how, groups, gi, question, llm, res)
            return out
    if kind != "EVENT" and _match_article(out, queries, gi, allow_fuzzy):
        return out
    res.notes.append(f"{text!r}: no graph node or article matches")
    return out


def _match_nodes(q: str, gi: GraphIndex, kind: str, allow_fuzzy: bool):
    """Returns (how, [group ids]) for the first matching method, filtered by the expected kind."""
    norm = normalize(q)
    tries = [("exact", lambda: [q] if q in gi.group_of else []),
             ("normalized", lambda: gi.by_norm.get(norm, [])),
             ("words", lambda: _by_words(norm, gi))]
    if allow_fuzzy:
        tries.append(("fuzzy", lambda: _by_fuzzy(norm, gi)))
    for how, find in tries:
        names = find()
        if not names:
            continue
        gids = list(dict.fromkeys(gi.group_of[n] for n in names))
        if how == "words" and len(gids) > MAX_WORD_MATCHES:
            continue   # "russian" alone is in thousands of names: too vague to be a match
        if kind in ("PER", "ORG", "LOC"):
            typed = [g for g in gids if gi.G.nodes[g]["type"] == kind]
            gids = typed or gids
        return how, gids
    return None, []


CONNECTORS = {"of", "the", "and", "a", "an", "de", "la", "al", "in", "on", "for"}


def _by_words(norm: str, gi: GraphIndex) -> list[str]:
    """Names containing every word of the query except connectors ("Zelensky" in "Volodymyr Zelensky").
    All words, not just distinctive ones: "Russian Air Force" must not match "Russian Armed Forces"."""
    ws = [w for w in words(norm) if w not in CONNECTORS]
    if not ws or not distinctive(ws):
        return []
    found = set(gi.by_word.get(ws[0], set()))
    for w in ws[1:]:
        found &= gi.by_word.get(w, set())
    return sorted(found)


def _by_fuzzy(norm: str, gi: GraphIndex) -> list[str]:
    """Close spellings ("Kharkov" -> "Kharkiv"), but every word of the query (except connectors) must
    have a similar word in the candidate - so "Russian Air Force" never becomes "Russian Armed Forces"
    and "Russian Armed Forces" never becomes "Ukrainian Air Force"."""
    qws = [w for w in words(norm) if w not in CONNECTORS]
    if not distinctive(qws):
        return []
    out = []
    for cand in get_close_matches(norm, list(gi.by_norm), n=8, cutoff=FUZZY_CUTOFF):
        cws = words(cand)
        if all(any(similar(q, c) >= WORD_SIMILARITY for c in cws) for q in qws):
            out.extend(gi.by_norm[cand])
    return out


def _match_article(out: ResolvedName, queries: list[str], gi: GraphIndex, allow_fuzzy: bool) -> bool:
    for q in queries:
        title = q if q in gi.articles else gi.article_by_norm.get(normalize(q))
        how = "article"
        if not title and allow_fuzzy:
            close = get_close_matches(normalize(q), list(gi.article_by_norm), n=1, cutoff=0.85)
            title, how = (gi.article_by_norm[close[0]], "article_fuzzy") if close else (None, how)
        if title:
            out.status, out.how, out.picked_by = "resolved", how, "only match"
            out.article = ArticleRef(title=title, paragraphs=len(gi.articles[title]),
                                     lead_sentence=gi.lead_sentence(title))
            return True
    return False


# --- Choosing between several groups (P2-11) -------------------------------------------------

def _pick(out: ResolvedName, how: str, gids: list[str], gi: GraphIndex, question: str, llm, res: Resolution) -> None:
    groups = sorted((gi.group(g) for g in gids), key=lambda g: -g.texts)
    out.status, out.how = "resolved", how
    if len(groups) == 1:
        out.group, out.picked_by = groups[0], "only match"
        return
    chosen, picked_by = groups[0], "strongest"
    if groups[0].texts >= DOMINANCE * max(groups[1].texts, 1):
        picked_by = "dominant"
    elif llm is not None:
        choice = _ask_llm(question, groups[:MAX_ALTERNATIVES + 1], gi, llm, res)
        if choice is not None:
            chosen, picked_by = choice, "llm"
    out.group, out.picked_by = chosen, picked_by
    out.alternatives = [g for g in groups if g.id != chosen.id][:MAX_ALTERNATIVES]


def describe(group: Group, gi: GraphIndex) -> str:
    """One line about a candidate, for the LLM to choose from (P2-34, provisional)."""
    if group.place:
        return f"{group.type}, {group.place.place_type or 'place'}: {group.place.address or ''}"[:250]
    if group.own_article:
        return f"{group.type}; article '{group.own_article}': {gi.lead_sentence(group.own_article) or ''}"[:300]
    return f"{group.type}; mentioned in {group.texts} paragraphs; also written: {', '.join(group.names[1:4]) or '-'}"


def _ask_llm(question: str, groups: list[Group], gi: GraphIndex, llm, res: Resolution) -> Optional[Group]:
    lines = "\n".join(f"- id: {g.id} | {describe(g, gi)}" for g in groups)
    try:
        pick, call = structured_call(llm, CandidatePick, [
            ("system", PICK_PROMPT), ("human", f"Question: {question}\n\nEntries:\n{lines}")], step="resolve")
    except openai.APIError as e:
        res.notes.append(f"candidate pick skipped ({type(e).__name__}); using the strongest")
        return None
    res.llm_calls.append(call)
    if pick is None or pick.choice == "unsure":
        return None
    return next((g for g in groups if g.id == pick.choice), None)
