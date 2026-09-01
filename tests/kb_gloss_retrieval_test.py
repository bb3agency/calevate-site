"""Does the gloss actually make retrieval work — and does the script gate cost anything?

TWO HALVES, AND THE FIRST IS THE MEASUREMENT.

**§1 is a measurement, not an example.** It scores this repo's own ranker
(`retrieval/compiled_facts.score_line`) over the 24-fact corpus a sibling lane built and
published in `docs/evidence/telugu-embedding-quality.md` — the same clinic and real-estate
facts written once in Telugu script and once in English, each asked three ways: Telugu
script, Tenglish (romanised, the form Sarvam's Saaras STT returns), and English. The corpus
travels with this repo as `tests/fixtures/telugu_gloss_corpus.json` so the numbers below
are REPRODUCIBLE rather than quoted, and so a change to the ranker, the gate or the
tokeniser fails here instead of in production.

The spike measured a DENSE ranker (multilingual-e5-large) fused with BM25 and put the
Tenglish cell at 0.250 → 0.750 recall@1. This file measures the ranker this repo ACTUALLY
has, which is deterministic token overlap, and on it the unaided figure is not 0.250 but
**0.000**: a Latin-script question and a Telugu-script line share no tokens at all, so the
tier returns nothing whatsoever. That is a worse starting point than the spike's and the
same fix moves it.

**§2 is the end-to-end proof** through the real ingestion and publish path: a Tenglish
question finds a Telugu-script fact WITH the gloss and finds nothing WITHOUT it, and what
comes back is the client's own approved Telugu — never the machine's English.
"""

from __future__ import annotations

import json
import pathlib
import uuid
from typing import Any

from apps.api.db.session import tenant_session
from apps.api.kb import service as kb_service
from apps.api.kb.gloss import GLOSS_READY, gloss_applies
from apps.api.retrieval.compiled_facts import CompiledFactsRetriever, score_line, tokens
from calevate_shared.retrieval import RetrievalRequest
from sqlalchemy import text
from tests.kb_workflow_test import _tenant_with_published_agent

_CORPUS = json.loads(
    (pathlib.Path(__file__).parent / "fixtures" / "telugu_gloss_corpus.json").read_text()
)

#: THE FLOORS THIS FILE PINS, all MEASURED-HERE on the corpus above. They are floors and
#: not equalities so that an improvement to the tokeniser is not a failure, and they sit
#: one step below the measured figure so a change of a single question is not a red build.
#: The measured values at the commit that wrote this file:
#:
#:   corpus  question    baseline   with gloss (gated)
#:   te      te          0.417      0.417   ← the gate is SHUT; identical by construction
#:   te      tenglish    0.000      0.542
#:   te      en          0.000      0.875
#:
#: The Tenglish row is the product's real case and the reason the column exists.
_TENGLISH_FLOOR = 0.50
_ENGLISH_FLOOR = 0.83


def _rank(question: str, passages: list[tuple[str, str | None]], *, gated: bool) -> list[int]:
    """Indices of the passages this question matches, best first — the adapter's ranking.

    A faithful re-implementation of the loop in `CompiledFactsRetriever.retrieve`, over a
    list instead of over compiled blocks, so that §1 can vary ONE thing (the gate) without
    standing up 24 tenants. §2 is what proves the real adapter agrees with it.
    """
    question_tokens = tokens(question)
    scored: list[tuple[float, int]] = []
    for i, (original, gloss) in enumerate(passages):
        score = score_line(question_tokens, original)
        if gloss is not None and (not gated or gloss_applies(question=question, passage=original)):
            score = max(score, score_line(question_tokens, gloss))
        scored.append((score, i))
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return [i for score, i in scored if score > 0.0]


def _recall_at_1(query_key: str, *, glossed: bool, gated: bool = True) -> float:
    """Share of the 24 questions whose OWN fact is the single top hit, over a Telugu corpus."""
    passages: list[tuple[str, str | None]] = [
        (fact["passage_te"], fact["passage_en"] if glossed else None) for fact in _CORPUS
    ]
    hits = sum(
        1
        for i, fact in enumerate(_CORPUS)
        if _rank(fact[query_key], passages, gated=gated)[:1] == [i]
    )
    return hits / len(_CORPUS)


# --- §1 the measurement ------------------------------------------------------------


def test_the_corpus_is_the_one_the_evidence_doc_measured() -> None:
    """n=24, two verticals, three question forms. A shrunken corpus would silently make
    every threshold below easier."""
    assert len(_CORPUS) == 24
    assert {fact["vertical"] for fact in _CORPUS} == {"clinic", "real_estate"}
    for fact in _CORPUS:
        assert fact["passage_te"] and fact["passage_en"]
        assert fact["query_te"] and fact["query_tenglish"] and fact["query_en"]


def test_without_a_gloss_a_tenglish_question_retrieves_absolutely_nothing() -> None:
    """THE DEFECT THE COLUMN EXISTS FOR, stated as a number.

    Tenglish is what Saaras returns, so this is not a corner: it is what every Telugu
    caller's question looks like by the time it reaches us. On token overlap the failure is
    not degraded ranking, it is silence — which is why the spike's 0.250 understates it
    here.
    """
    assert _recall_at_1("query_tenglish", glossed=False) == 0.0
    assert _recall_at_1("query_en", glossed=False) == 0.0


def test_the_gloss_turns_that_silence_into_usable_retrieval() -> None:
    assert _recall_at_1("query_tenglish", glossed=True) >= _TENGLISH_FLOOR
    assert _recall_at_1("query_en", glossed=True) >= _ENGLISH_FLOOR


def test_the_gate_leaves_same_script_retrieval_exactly_where_it_was() -> None:
    """THE SIBLING'S TRAP, checked on our own ranker.

    `docs/evidence/telugu-embedding-quality.md` §4b measured an UNGATED hybrid making
    cross-script recall WORSE (0.708 → 0.375), because an arm that matches nothing still
    contributes its ranking. The gate is what forecloses that. On a Telugu question against
    a Telugu corpus it is shut, so the score must be bit-for-bit the pre-gloss score — and
    this asserts EQUALITY, not "no worse", because anything else would mean a gloss had
    leaked into a same-script ranking.
    """
    for query_key in ("query_te",):
        assert _recall_at_1(query_key, glossed=True) == _recall_at_1(query_key, glossed=False)


def test_the_gate_costs_nothing_on_this_ranker_and_that_is_recorded_not_assumed() -> None:
    """HONEST FINDING: on THIS ranker the gate changes no outcome, in any cell.

    It cannot, and the reason is worth writing down rather than discovering later. Every
    gloss is English and only Telugu-script chunks have one, so the one cell where the gate
    could bite — a gloss read for a question in its passage's own script — is a Telugu
    question scored against English text, which token overlap already scores 0.0. `max()`
    with a zero is the identity.

    The gate is kept anyway, for two reasons that are not this measurement: it makes
    "same-script retrieval is unperturbed" a STRUCTURAL guarantee rather than a property
    that happens to hold today, and it is the seam where a dense arm gets gated when the
    D-28 provider lands — which is exactly the arm the spike measured going 0.708 → 0.375
    ungated. This test exists so that the day the two columns disagree, somebody is told.
    """
    for query_key in ("query_te", "query_tenglish", "query_en"):
        assert _recall_at_1(query_key, glossed=True, gated=True) == _recall_at_1(
            query_key, glossed=True, gated=False
        )


# --- §2 end to end, through the real path ------------------------------------------


async def _tenant_knowing_in_telugu(
    name: str, body: str, gloss: str | None
) -> tuple[uuid.UUID, uuid.UUID]:
    """A live agent whose published Telugu knowledge carries (or does not carry) a gloss.

    Submitted, approved and published through `kb.service` — never inserted — because what
    makes a fact retrievable is the approval gate, and a fixture that wrote the compiled
    block directly would prove the ranker works on knowledge no human approved. Only the
    gloss is written directly, standing in for the sweep that `tests/kb_gloss_test.py`
    drives end to end.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    async with tenant_session(tenant_id) as session:
        submitted = await kb_service.submit_source(
            session, tenant_id=tenant_id, agent_id=agent_id, name=name, body=body
        )
        if gloss is not None:
            await session.execute(
                text(
                    "UPDATE kb_documents SET gloss = :g, gloss_model = 'test-model', "
                    "gloss_state = :s WHERE source_id = :sid"
                ),
                {"g": gloss, "s": GLOSS_READY, "sid": submitted["id"]},
            )
        await kb_service.approve_source(session, source_id=submitted["id"], approved_by=None)
        await kb_service.publish_source(
            session, tenant_id=tenant_id, source_id=uuid.UUID(str(submitted["id"]))
        )
    return uuid.UUID(str(tenant_id)), uuid.UUID(str(agent_id))


async def _ask(tenant_id: uuid.UUID, question: str) -> list[Any]:
    async with tenant_session(tenant_id) as session:
        result = await CompiledFactsRetriever(session).retrieve(
            RetrievalRequest(
                tenant_id=tenant_id, question=question, k=3, tier="t0", allow_degrade=True
            )
        )
    return list(result.passages)


TELUGU_FACT = "సన్‌రైజ్ క్లినిక్ ఆదివారం ఉదయం 9 గంటల నుండి మధ్యాహ్నం 12 గంటల వరకు మాత్రమే తెరిచి ఉంటుంది."
ENGLISH_GLOSS = "Sunrise Clinic is open on Sunday only from 9 am to 12 noon."
TENGLISH_QUESTION = "Sunday roju clinic enni gantala varaku open untundi?"


async def test_a_tenglish_question_finds_a_telugu_fact_only_because_of_the_gloss() -> None:
    """THE REGRESSION TEST. Both directions in one place, through the real publish path.

    Delete `kb_documents.gloss`, or stop reading it in `compiled_facts.py`, and the second
    half of this test still passes while the first goes to zero passages — which is exactly
    what a client's Telugu caller would experience, and exactly what nothing else in this
    suite would notice.
    """
    with_gloss, _ = await _tenant_knowing_in_telugu("Hours", TELUGU_FACT, ENGLISH_GLOSS)
    without_gloss, _ = await _tenant_knowing_in_telugu("Hours", TELUGU_FACT, None)

    found = await _ask(with_gloss, TENGLISH_QUESTION)
    assert found, "a Tenglish question found nothing despite a gloss being on file"

    assert not await _ask(without_gloss, TENGLISH_QUESTION), (
        "the same question matched without a gloss — this test is not testing the gloss"
    )


async def test_what_comes_back_is_the_clients_approved_telugu_and_never_the_machines_english() -> (
    None
):
    """THE APPROVAL-GATE PROPERTY, and the reason the gloss needs no review of its own.

    The gloss is a retrieval KEY. A mistranslation can therefore cost a wrong MATCH — the
    client's own approved words returned for a question they do not answer — and can never
    cost a wrong SENTENCE. If this assertion ever fails, a machine translation has become
    something the product says on a client's behalf, and it needs a human gate before it
    ships.
    """
    tenant_id, _ = await _tenant_knowing_in_telugu("Hours", TELUGU_FACT, ENGLISH_GLOSS)
    passages = await _ask(tenant_id, TENGLISH_QUESTION)
    assert passages
    for passage in passages:
        assert TELUGU_FACT in passage.text
        assert ENGLISH_GLOSS not in passage.text


async def test_a_telugu_question_is_answered_exactly_as_it_was_before_glosses_existed() -> None:
    """The gate, end to end: same script, so the gloss is never consulted and the ranking
    of a glossed tenant is identical to that of an unglossed one."""
    with_gloss, _ = await _tenant_knowing_in_telugu("Hours", TELUGU_FACT, ENGLISH_GLOSS)
    without_gloss, _ = await _tenant_knowing_in_telugu("Hours", TELUGU_FACT, None)
    question = "ఆదివారం క్లినిక్ ఎన్ని గంటల వరకు తెరిచి ఉంటుంది?"

    glossed = [(p.text, p.score) for p in await _ask(with_gloss, question)]
    plain = [(p.text, p.score) for p in await _ask(without_gloss, question)]
    assert glossed and glossed == plain


async def test_an_english_chunk_with_no_gloss_keeps_working_exactly_as_today() -> None:
    """ADDITIVE, asserted rather than assumed. Every chunk in this repository before the
    migration is `pending` with a NULL gloss, and none of them may change behaviour."""
    tenant_id, _ = await _tenant_knowing_in_telugu(
        "Fees", "A consultation costs 500 rupees at reception.", None
    )
    passages = await _ask(tenant_id, "what does a consultation cost")
    assert passages and "500 rupees" in passages[0].text
