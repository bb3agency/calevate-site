"""The harness that turns "retire the pgvector path" into a table. Scored offline.

**WHAT THIS FILE IS DEFENDING.** `docs/PIPECAT-MIGRATION.md` §6 step 15 retires `kb_chunks`
and its lexical arm in favour of Supermemory. That is a decision about RECALL — does the
new store still find the client's price list when a client asks about prices — and until
`retrieval/compare.py` existed nothing in this repository could have answered it. A harness
whose own arithmetic is wrong is worse than none, because it produces a number people then
argue from, so every metric below is checked against a hand-worked case first and only then
run over a corpus.

**THE CORPUS IS THE ONE THIS REPO ALREADY HAS**, `tests/fixtures/telugu_gloss_corpus.json`
— the same file `tests/in_call_retrieval_recall_test.py` and `tests/kb_gloss_retrieval_test.
py` score, so nobody has to wonder whether two recall numbers in this tree were measured
over different questions. Only its twelve REAL-ESTATE facts are used here: the arms under
test are fakes, the corpus half is arbitrary, and a fixture about a clinic is not the one to
reach for when either will do.

**NO STORE, NO NETWORK, NO DATABASE, NO CLOCK.** Both arms are in-memory rankers over the
fixture. That is the point: the harness must run in CI, on a laptop, and against a live box
3 the day there is one, and it can only do all three if the scoring knows nothing about
where the passages came from.

WHAT THE TWO FAKE ARMS ARE. One ranks by this repo's own deterministic token overlap
(`retrieval/compiled_facts.score_line`, the ranker the compiled tier really uses) and the
other is that same ranker with its list reversed. The second is not a model of Supermemory
and must not be read as one — it is a deliberately WORSE arm, chosen because a harness that
cannot tell a good arm from a bad one would pass every test written with two good ones.
"""

from __future__ import annotations

import json
import pathlib
import uuid
from typing import Final

import pytest
from apps.api.retrieval.compare import (
    ArmScore,
    ComparisonCase,
    Disagreement,
    compare_arms,
    disagreement,
    document_keys,
    score_arm,
)
from apps.api.retrieval.compiled_facts import score_line, tokens
from calevate_shared.retrieval import (
    Passage,
    Provenance,
    RetrievalCapabilities,
    RetrievalRequest,
    RetrievalResult,
)

_CORPUS: Final = [
    fact
    for fact in json.loads(
        (pathlib.Path(__file__).parent / "fixtures" / "telugu_gloss_corpus.json").read_text()
    )
    if fact["vertical"] == "real_estate"
]

#: One stable document id per fact. `uuid5` rather than `uuid4` so a failure is the same
#: failure twice — the arms are compared on these ids and a random one would make a
#: reproduction of a bad run impossible.
_NAMESPACE: Final = uuid.UUID("2f1c9a3e-6d24-4e1f-9a7b-5c8d0e1f2a3b")


def _source_id(fact_id: str) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, fact_id)


def _passage(fact: dict[str, str]) -> Passage:
    return Passage(
        text=fact["passage_en"],
        provenance=Provenance(
            label=f"{fact['fact_id']} sheet", tier="t3", source_id=_source_id(fact["fact_id"])
        ),
    )


def _cases() -> tuple[ComparisonCase, ...]:
    """Every real-estate fact, asked in English — the form §9.1 step 2 actually emits."""
    return tuple(
        ComparisonCase(
            case_id=fact["fact_id"],
            question=fact["query_en"],
            expected=frozenset({str(_source_id(fact["fact_id"]))}),
        )
        for fact in _CORPUS
    )


class TokenOverlapArm:
    """The repo's own deterministic ranker over the fixture. The incumbent's stand-in."""

    capabilities = RetrievalCapabilities(
        compiled_facts=False,
        semantic_search=True,
        hybrid_search=False,
        reranking=False,
        per_tenant_namespace=True,
        deletion_proof=True,
        max_k=20,
    )

    def __init__(self, name: str, *, worst_first: bool = False) -> None:
        self.name = name
        self._worst_first = worst_first

    async def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        asked = tokens(request.question)
        scored = sorted(
            ((score_line(asked, fact["passage_en"]), fact) for fact in _CORPUS),
            key=lambda pair: pair[0],
            reverse=not self._worst_first,
        )
        return RetrievalResult(
            passages=tuple(_passage(fact) for _score, fact in scored[: request.k]),
            requested_tier=request.tier,
            served_tier="t3",
            provider=self.name,
        )

    async def knowledge_epoch(self, request: RetrievalRequest) -> str:
        return "fixture-epoch"


class BrokenArm:
    """An arm that raises. What a challenger nobody has installed actually does."""

    name = "broken"
    capabilities = TokenOverlapArm.capabilities

    async def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        raise RuntimeError("the store did not answer")

    async def knowledge_epoch(self, request: RetrievalRequest) -> str:
        raise RuntimeError("the store did not answer")


def _result(*source_ids: uuid.UUID | None) -> RetrievalResult:
    """A result carrying one passage per id, `None` meaning a passage with no provenance."""
    return RetrievalResult(
        passages=tuple(
            Passage(
                text="Two-bedroom flats start at 62 lakh.",
                provenance=Provenance(label="Price list", tier="t3", source_id=source_id),
            )
            for source_id in source_ids
        ),
        requested_tier="t3",
        served_tier="t3",
        provider="fixture",
    )


# --- the arithmetic, hand-worked before any corpus is involved -------------------------


def test_two_arms_that_returned_nothing_agree() -> None:
    """Scoring two empty answers 0.0 would fill the log with alarm about questions neither
    arm was ever going to answer. `top1_same` stays None: there is no first document, which
    is a different fact from a different first document."""
    difference = disagreement(_result(), _result())
    assert difference == Disagreement(served_n=0, shadow_n=0, overlap=0, jaccard=1.0)
    assert difference.agreed is True


def test_the_same_documents_in_a_different_order_is_a_disagreement() -> None:
    """The copilot puts the whole list in front of a model that weights the top of it, so
    two arms that agree on the set and differ on the leader are not interchangeable."""
    first, second = uuid.uuid4(), uuid.uuid4()
    difference = disagreement(_result(first, second), _result(second, first))
    assert difference.jaccard == 1.0
    assert difference.top1_same is False
    assert difference.agreed is False


def test_an_arm_that_raised_is_not_an_arm_that_found_nothing() -> None:
    """The distinction the whole comparison rests on: only the second is evidence about
    retrieval quality, and treating them alike would report a clean swap for a store that
    was never reached."""
    failure = RuntimeError("the store did not answer")
    difference = disagreement(_result(uuid.uuid4()), None, error=failure)
    assert difference.shadow_error == "RuntimeError"
    assert difference.agreed is False


def test_a_passage_with_no_source_id_can_never_match_anything() -> None:
    """Two unlabelled records are two citations neither arm can defend. Matching them would
    report agreement about provenance we cannot check, so they are keyed by ARM AND
    position and can never match."""
    difference = disagreement(_result(None), _result(None))
    assert difference.overlap == 0
    assert difference.unkeyed_served == 1
    assert difference.unkeyed_shadow == 1
    assert difference.agreed is False


def test_two_chunks_of_one_document_are_one_hit() -> None:
    """The grain is the document. A client experiences "did it find the price list", and an
    arm that returned three chunks of it did not find three things."""
    source_id = uuid.uuid4()
    assert document_keys(_result(source_id, source_id)) == (str(source_id),)


async def test_an_arm_that_raises_on_every_case_is_reported_rather_than_raised() -> None:
    """A flaky challenger must produce a table saying "flaky", not a traceback saying
    nothing — the run is the measurement, and aborting it loses the whole corpus."""
    cases = _cases()
    score = await score_arm(BrokenArm(), cases, tenant_id=uuid.uuid4())
    assert score == ArmScore(
        arm="broken",
        cases=len(cases),
        recall_at_1=0.0,
        recall_at_k=0.0,
        mrr=0.0,
        empty=0,
        errored=len(cases),
    )


# --- over the corpus this repo already has --------------------------------------------


async def test_the_harness_separates_a_good_arm_from_a_bad_one() -> None:
    """**THE ONE PROPERTY THAT MAKES A NUMBER WORTH ARGUING FROM.**

    A harness written and checked with two good arms passes whatever its arithmetic does.
    The challenger here is the same ranker with its list reversed — the worst possible arm
    over the same corpus — so every metric must move, and in the same direction.
    """
    cases = _cases()
    comparison = await compare_arms(
        TokenOverlapArm("incumbent"),
        TokenOverlapArm("challenger", worst_first=True),
        cases,
        tenant_id=uuid.uuid4(),
    )

    assert comparison.incumbent.cases == comparison.challenger.cases == len(cases)
    assert comparison.incumbent.recall_at_1 > comparison.challenger.recall_at_1
    assert comparison.incumbent.mrr > comparison.challenger.mrr
    assert comparison.recall_at_k_delta < 0.0, "a losing swap must read as a loss"
    assert comparison.agreement == 0.0


async def test_an_arm_compared_with_itself_agrees_on_every_case() -> None:
    """The control. An agreement rate that is not 1.0 here means the comparison is
    measuring something other than the arms — ordering, dedup, or the keying."""
    cases = _cases()
    comparison = await compare_arms(
        TokenOverlapArm("a"), TokenOverlapArm("b"), cases, tenant_id=uuid.uuid4()
    )
    assert comparison.agreement == 1.0
    assert comparison.incumbent.recall_at_k == comparison.challenger.recall_at_k
    assert comparison.recall_at_k_delta == 0.0


async def test_both_columns_are_measured_over_the_same_cases_and_the_same_k() -> None:
    """The defect `compare_arms` exists to prevent: a table whose two columns came from
    different question sets or different `k` looks like a finding and is an artefact."""
    cases = _cases()
    comparison = await compare_arms(
        TokenOverlapArm("a"), BrokenArm(), cases, tenant_id=uuid.uuid4(), k=5
    )
    assert comparison.incumbent.cases == comparison.challenger.cases == len(cases)
    assert comparison.challenger.errored == len(cases)
    # An unreachable challenger agrees with nothing, however empty the incumbent was.
    assert comparison.agreement == 0.0


async def test_the_measurement_asks_the_store_and_never_accepts_a_lower_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`allow_degrade=False`, unlike `service.look_up`.

    The copilot degrades because a client is waiting. A measurement that silently scored
    T0's compiled block as if it were the store's answer would report the wrong arm's
    recall and be worse than no number at all.
    """
    seen: list[RetrievalRequest] = []
    arm = TokenOverlapArm("incumbent")
    original = arm.retrieve

    async def _record(request: RetrievalRequest) -> RetrievalResult:
        seen.append(request)
        return await original(request)

    monkeypatch.setattr(arm, "retrieve", _record)
    await score_arm(arm, _cases(), tenant_id=uuid.uuid4())

    assert seen, "nothing was asked"
    assert all(request.allow_degrade is False for request in seen)
    assert all(request.tier == "t3" for request in seen)
