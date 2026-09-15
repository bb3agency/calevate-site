"""Score two retrieval arms against each other, so a store is retired on a NUMBER.

WHY THIS EXISTS. `docs/PIPECAT-MIGRATION.md` §6 step 15 retires `kb_chunks` and its lexical
arm in favour of Supermemory. Nothing in this repository could have told anybody whether
that trade is good: the pgvector arm's recall over a known corpus was never measured (the
one recall measurement this tree holds is `tests/in_call_retrieval_recall_test.py`, and it
scores the IN-CALL pack, which §8.1 does not retire), and box 3 has never answered a
question here at all. A retirement argued from "the new one is a purpose-built memory
product" is a preference. This module is what turns it into a table — condition (d) of the
six §8.6 makes step 15 wait on (D-604).

WHAT IT MEASURES, AND WHY THESE THREE:

* **recall@1 and recall@k** — did the arm surface the right DOCUMENT, and was it first.
  `tests/in_call_retrieval_recall_test.py` scores the same way and for the reason recorded
  there: recall over an internal ranking rather than over the passages the caller actually
  received would score a hit nobody heard.
* **MRR** — where in the list it landed when it was not first. Two arms can share a
  recall@3 and be very different to read, and the copilot puts the whole list in front of
  a model that weights the top of it.
* **agreement** — how often the two arms returned the same documents at all. This one is
  not a quality score and must not be read as one: two arms that agree completely tell you
  the swap is safe, and two that disagree tell you nothing about which is RIGHT. Recall
  answers that; agreement answers "how much of the corpus is this decision even about".

THE GRAIN IS THE DOCUMENT, NOT THE CHUNK, and that is a deliberate narrowing. Two arms
chunk differently — `kb_chunks` holds our projection, box 3 holds whatever its own ingester
made — so comparing chunk text would score the chunkers rather than the retrieval. What a
client experiences is "did it find the price list", so `document_key` keys on
`Provenance.source_id`, which both adapters carry because WE minted it
(`kb_documents` stays ours, §8.4) and it is the one identifier that survives the wire.

**A PASSAGE WITH NO `source_id` IS UNKEYABLE AND COUNTS AS A MISS AND AS A DISAGREEMENT.**
It gets a key unique to its ARM AND its position, so it can never match anything —
including an identical passage from the other arm. That is the conservative direction on purpose: an
unlabelled record from box 3 is a record whose provenance we cannot check, and a comparison
that quietly matched two of them would report agreement about citations neither arm can
defend. The count is reported separately (`unkeyed`) so an operator reading a bad
agreement number can tell "the arms disagree" from "box 3 is not sending our metadata".

NO NETWORK, NO CONFIG, NO CLOCK. Everything here takes providers and cases as arguments, so
the same code scores two fakes offline in CI and the two real adapters against a live box 3
once there is one — `scripts/` has nothing to grow and there is one scoring rule, not two.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from calevate_shared.retrieval import (
    Passage,
    RetrievalProvider,
    RetrievalRequest,
    RetrievalResult,
    RetrievalTier,
)
from pydantic import BaseModel, ConfigDict, Field

#: The key an UNKEYABLE passage gets, with its position appended. A prefix rather than
#: `None` so the two halves of a comparison stay plain sets of strings — and a prefix that
#: could never collide with a UUID, so "the arms agreed" can never mean "both were
#: unlabelled".
UNKEYED_PREFIX = "unkeyed:"


def document_key(passage: Passage, *, position: int, side: str = "") -> str:
    """Which DOCUMENT this passage cites, as a string both arms can produce.

    `position` and `side` are used only when there is no `source_id`, and BOTH are needed:
    the position keeps two unkeyable passages from one arm from collapsing into one, and the
    side keeps an unkeyable passage from matching the OTHER arm's unkeyable passage at the
    same rank — which is the case that would otherwise report perfect agreement between two
    citations neither arm can defend.
    """
    source_id = passage.provenance.source_id
    return str(source_id) if source_id is not None else f"{UNKEYED_PREFIX}{side}:{position}"


def document_keys(result: RetrievalResult, *, side: str = "") -> tuple[str, ...]:
    """The result's documents IN RANK ORDER, deduplicated.

    Deduplicated because two chunks of one document are one hit, not two — and rank order
    is kept because recall@1 and MRR are both statements about position. `dict.fromkeys`
    rather than a set for exactly that: a set would lose the ordering the metrics need.
    """
    return tuple(
        dict.fromkeys(document_key(p, position=i, side=side) for i, p in enumerate(result.passages))
    )


class Disagreement(BaseModel):
    """How far apart two arms were on ONE question. The unit the shadow read records.

    Frozen and counts-only: it is written to a log line (hard rule 6), so nothing here may
    be a question, a passage or anything a client wrote. Every field is a number, a
    boolean, or an exception's class name.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    served_n: int = Field(ge=0)
    shadow_n: int = Field(ge=0)
    #: Documents both arms returned.
    overlap: int = Field(ge=0)
    #: Documents in BOTH over documents in EITHER, and 1.0 when both arms returned
    #: nothing — two empty answers are not a disagreement, they are the same answer, and
    #: scoring them 0.0 would fill the log with alarm about questions neither arm was ever
    #: going to answer.
    jaccard: float = Field(ge=0.0, le=1.0)
    #: Did the two arms put the same document first? `None` when either arm was empty,
    #: because "no first document" is not the same fact as "a different first document".
    top1_same: bool | None = None
    #: Passages the arm could not key (no `source_id`), per arm. See the module docstring:
    #: these force a disagreement, so an operator must be able to see that they caused it.
    unkeyed_served: int = Field(default=0, ge=0)
    unkeyed_shadow: int = Field(default=0, ge=0)
    #: The class name of whatever stopped the shadow arm answering, or `None`. Never the
    #: message — an HTTP error body quotes the request, and the request is a person's own
    #: question (`retrieval/supermemory.py::_degrade` makes the same call).
    shadow_error: str | None = None

    @property
    def agreed(self) -> bool:
        """Same documents, same order at the top, and the shadow arm actually answered."""
        return self.shadow_error is None and self.jaccard == 1.0 and self.top1_same is not False


def _unkeyed(keys: Sequence[str]) -> int:
    return sum(1 for key in keys if key.startswith(UNKEYED_PREFIX))


def disagreement(
    served: RetrievalResult, shadow: RetrievalResult | None, *, error: Exception | None = None
) -> Disagreement:
    """Compare one served answer with what the other arm would have said.

    `shadow=None` with an `error` is the arm that did not answer — reported as a
    disagreement with `shadow_error` set rather than as an empty result, because "box 3 is
    down" and "box 3 found nothing" are different facts and only the second one is evidence
    about retrieval quality.
    """
    served_keys = document_keys(served, side="served")
    shadow_keys = document_keys(shadow, side="shadow") if shadow is not None else ()
    served_set, shadow_set = set(served_keys), set(shadow_keys)
    union = served_set | shadow_set
    overlap = served_set & shadow_set
    return Disagreement(
        served_n=len(served_keys),
        shadow_n=len(shadow_keys),
        overlap=len(overlap),
        jaccard=1.0 if not union else len(overlap) / len(union),
        top1_same=(served_keys[0] == shadow_keys[0] if served_keys and shadow_keys else None),
        unkeyed_served=_unkeyed(served_keys),
        unkeyed_shadow=_unkeyed(shadow_keys),
        shadow_error=type(error).__name__ if error is not None else None,
    )


class ComparisonCase(BaseModel):
    """One question and the documents a correct answer contains. The harness's input.

    `expected` is a SET because a question can have more than one right document and
    because the order we happen to write them in is not a fact about retrieval.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str = Field(min_length=1, max_length=120)
    question: str = Field(min_length=1, max_length=2000)
    expected: frozenset[str] = Field(min_length=1)


class ArmScore(BaseModel):
    """One arm's numbers over one case set. What the retirement decision is argued from."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    arm: str = Field(min_length=1)
    cases: int = Field(ge=0)
    #: An expected document was ranked first.
    recall_at_1: float = Field(ge=0.0, le=1.0)
    #: An expected document appeared anywhere in the `k` returned.
    recall_at_k: float = Field(ge=0.0, le=1.0)
    #: Mean reciprocal rank of the FIRST expected document, 0 for a case that missed.
    mrr: float = Field(ge=0.0, le=1.0)
    #: Cases where the arm returned no passages at all. Separate from a miss: an arm that
    #: returns three wrong documents and an arm that returns nothing fail a client
    #: differently, and only the second one is visibly broken.
    empty: int = Field(ge=0)
    #: Cases the arm could not be asked — it raised. Never folded into `empty`, for
    #: `Disagreement.shadow_error`'s reason.
    errored: int = Field(ge=0)


def _rank_of_expected(keys: Sequence[str], expected: frozenset[str]) -> int | None:
    """1-based rank of the first expected document, or None."""
    for rank, key in enumerate(keys, start=1):
        if key in expected:
            return rank
    return None


class _Tally:
    """One arm's running counts. A small mutable thing so the corpus is walked ONCE.

    The alternative — `score_arm` per arm plus a third pass for agreement — asks every arm
    every question twice, which on a real run is double the embedding spend (hard rule 7's
    money is being spent per question here) and, worse, lets the two passes disagree if the
    store changed underneath them.
    """

    def __init__(self, arm: str) -> None:
        self.arm = arm
        self.hits_1 = 0
        self.hits_k = 0
        self.reciprocal = 0.0
        self.empty = 0
        self.errored = 0

    def record(self, keys: Sequence[str], expected: frozenset[str]) -> None:
        if not keys:
            self.empty += 1
            return
        rank = _rank_of_expected(keys, expected)
        if rank is None:
            return
        self.hits_k += 1
        self.hits_1 += 1 if rank == 1 else 0
        self.reciprocal += 1.0 / rank

    def score(self, cases: int) -> ArmScore:
        return ArmScore(
            arm=self.arm,
            cases=cases,
            recall_at_1=self.hits_1 / cases if cases else 0.0,
            recall_at_k=self.hits_k / cases if cases else 0.0,
            mrr=self.reciprocal / cases if cases else 0.0,
            empty=self.empty,
            errored=self.errored,
        )


def _request(
    case: ComparisonCase, *, tenant_id: UUID, agent_id: UUID | None, k: int, tier: RetrievalTier
) -> RetrievalRequest:
    """`allow_degrade=False`, deliberately and unlike `service.look_up`.

    The copilot degrades because a client is waiting and a lower tier beats a refusal; a
    MEASUREMENT that silently scored T0's compiled block as if it were the store's answer
    would report the wrong arm's recall and be worse than no number at all.
    """
    return RetrievalRequest(
        tenant_id=tenant_id,
        agent_id=agent_id,
        question=case.question,
        k=k,
        tier=tier,
        allow_degrade=False,
    )


async def _ask(
    provider: RetrievalProvider, request: RetrievalRequest, tally: _Tally
) -> tuple[RetrievalResult | None, Exception | None]:
    """One arm, one question, as `(result, failure)`. **It never raises for the arm.**

    An arm that falls over mid-run is a result, not an aborted measurement: `errored` counts
    it and the rest of the corpus is still scored, so a comparison against a flaky box 3
    produces a table saying "flaky" rather than a traceback saying nothing.

    The FAILURE is handed back rather than swallowed because "the arm raised" and "the arm
    found nothing" must not collapse into one outcome downstream — `disagreement` scores two
    empty answers as agreement, which is right for two arms that both found nothing and
    badly wrong for an arm that was never reached.
    """
    try:
        return await provider.retrieve(request), None
    except Exception as failure:
        tally.errored += 1
        return None, failure


async def score_arm(
    provider: RetrievalProvider,
    cases: Sequence[ComparisonCase],
    *,
    tenant_id: UUID,
    agent_id: UUID | None = None,
    k: int = 3,
    tier: RetrievalTier = "t3",
) -> ArmScore:
    """Ask one arm every case and count what came back."""
    tally = _Tally(provider.name)
    for case in cases:
        request = _request(case, tenant_id=tenant_id, agent_id=agent_id, k=k, tier=tier)
        result, _ = await _ask(provider, request, tally)
        if result is not None:
            tally.record(document_keys(result), case.expected)
    return tally.score(len(cases))


class ArmComparison(BaseModel):
    """Two arms over one corpus, plus how often they agreed. The retirement table."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    incumbent: ArmScore
    challenger: ArmScore
    #: Share of cases where the two arms returned the same documents (`Disagreement.agreed`).
    agreement: float = Field(ge=0.0, le=1.0)

    @property
    def recall_at_k_delta(self) -> float:
        """Challenger minus incumbent. Negative means the swap loses answers."""
        return self.challenger.recall_at_k - self.incumbent.recall_at_k


async def compare_arms(
    incumbent: RetrievalProvider,
    challenger: RetrievalProvider,
    cases: Sequence[ComparisonCase],
    *,
    tenant_id: UUID,
    agent_id: UUID | None = None,
    k: int = 3,
) -> ArmComparison:
    """Score both arms on the SAME cases, in one pass, so nobody compares two corpora.

    One function rather than two `score_arm` calls a caller composes, because the defect
    this is meant to prevent is exactly a table whose two columns were measured over
    different question sets or different `k` — which looks like a finding and is an
    artefact. The arms are asked SEQUENTIALLY, for `retrieval/shadow.py`'s reason: both may
    be holding the caller's one `AsyncSession`, which is not concurrency-safe.
    """
    left, right = _Tally(incumbent.name), _Tally(challenger.name)
    agreed = 0
    for case in cases:
        request = _request(case, tenant_id=tenant_id, agent_id=agent_id, k=k, tier="t3")
        served, _ = await _ask(incumbent, request, left)
        shadow, failure = await _ask(challenger, request, right)
        if served is not None:
            left.record(document_keys(served), case.expected)
        if shadow is not None:
            right.record(document_keys(shadow), case.expected)
        # An incumbent that could not be asked agrees with nothing: there is no served
        # answer to compare, and counting it as agreement would report a clean swap for a
        # corpus half of which was never measured.
        if served is not None and disagreement(served, shadow, error=failure).agreed:
            agreed += 1
    return ArmComparison(
        incumbent=left.score(len(cases)),
        challenger=right.score(len(cases)),
        agreement=agreed / len(cases) if cases else 0.0,
    )


__all__ = [
    "UNKEYED_PREFIX",
    "ArmComparison",
    "ArmScore",
    "ComparisonCase",
    "Disagreement",
    "compare_arms",
    "disagreement",
    "document_key",
    "document_keys",
    "score_arm",
]
