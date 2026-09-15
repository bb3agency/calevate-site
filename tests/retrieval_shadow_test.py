"""The shadow read: it compares two stores and it may never change what a client sees.

**THE PROPERTY UNDER TEST IS A NEGATIVE ONE**, which is why the assertions below are shaped
the way they are. A shadow read is worth building only if it is provably inert — the moment
a reviewer has to reason about whether the challenger could leak into an answer, the safe
move is to not run it at all, and the comparison never happens. So the first group asserts
OBJECT IDENTITY on the served result, not equality: a future edit that merges, re-ranks or
even faithfully rebuilds the result fails here.

The four groups:

* **Inert** — the primary's own object comes back, whatever the shadow arm did, including
  when it raised. Nothing about the served answer moves.
* **Recorded** — a comparison was made and written down, with counts only (hard rule 6).
  An arm that did not answer is `shadow_error`, never "found nothing": those are different
  facts and only the second is evidence about retrieval quality.
* **Money and consent** — the shadow arm costs an embedding per question, so a tenant
  nobody enrolled is never shadowed and the arm is never even asked.
* **The switch** — `retrieval_shadow_arm` is LIVE (`core/platform_config`), so the
  comparison starts and stops between two requests with nothing redeployed. That is the
  rollback `docs/PIPECAT-MIGRATION.md` §8.6 requires of every step before step 15 may run.

NO NETWORK AND NO STORE. Both arms are fakes here: what is under test is the wrapper's
promise, and a real store would only make the promise harder to see.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import pytest
from apps.api.db.session import tenant_session
from apps.api.retrieval import service as retrieval_service
from apps.api.retrieval.compiled_facts import CompiledFactsRetriever
from apps.api.retrieval.pgvector import PgVectorRetriever
from apps.api.retrieval.shadow import (
    ShadowArmUnavailableError,
    ShadowReadRetriever,
    UnavailableArm,
    shadowed_tenants,
)
from calevate_shared.retrieval import (
    Passage,
    Provenance,
    RetrievalRequest,
    RetrievalResult,
)
from tests.kb_workflow_test import _tenant_with_published_agent


def _passage(source_id: uuid.UUID, *, label: str = "Price list") -> Passage:
    """One passage, keyed by the source id both arms carry because WE minted it."""
    return Passage(
        text="Two-bedroom flats start at 62 lakh, all inclusive.",
        provenance=Provenance(label=label, tier="t3", source_id=source_id),
        score=0.8,
    )


class FakeArm:
    """A store, without a store. Answers what it was told; or raises what it was told."""

    capabilities = CompiledFactsRetriever.capabilities

    def __init__(
        self,
        name: str,
        *,
        passages: tuple[Passage, ...] = (),
        raises: Exception | None = None,
    ) -> None:
        self.name = name
        self._passages = passages
        self._raises = raises
        self.asked: list[RetrievalRequest] = []
        #: The exact object this arm last handed back, so a caller can assert IDENTITY.
        self.answered: RetrievalResult | None = None

    async def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        self.asked.append(request)
        if self._raises is not None:
            raise self._raises
        self.answered = RetrievalResult(
            passages=self._passages,
            requested_tier=request.tier,
            served_tier="t3",
            provider=self.name,
        )
        return self.answered

    async def knowledge_epoch(self, request: RetrievalRequest) -> str:
        return f"{self.name}-epoch"


#: Stands in for a configured embedding deployment. Only its truthiness is read.
_CONFIGURED_LEG = object()


def _request(tenant_id: uuid.UUID) -> RetrievalRequest:
    return RetrievalRequest(
        tenant_id=tenant_id, question="what do flats cost", tier="t3", allow_degrade=True
    )


def _compared(caplog: pytest.LogCaptureFixture) -> logging.LogRecord:
    """The one comparison record, or fail saying none was written."""
    records = [r for r in caplog.records if r.getMessage() == "retrieval_shadow_compared"]
    assert len(records) == 1, f"expected one comparison, got {len(records)}"
    return records[0]


# --- inert: the served answer is the primary's, always -------------------------------


async def test_the_served_result_is_the_primary_arms_own_object() -> None:
    """IDENTITY, not equality. The shadow arm's passages must not reach a client.

    The two arms here return DIFFERENT documents on purpose, so a wrapper that merged them
    or preferred the challenger would return something a client can see, and this assertion
    is the one line a reviewer has to read to know it cannot.
    """
    tenant_id = uuid.uuid4()
    served = _passage(uuid.uuid4())
    primary = FakeArm("pgvector", passages=(served,))
    shadow = FakeArm("supermemory", passages=(_passage(uuid.uuid4()),))
    retriever = ShadowReadRetriever(primary, shadow=shadow, tenants=frozenset({tenant_id}))

    result = await retriever.retrieve(_request(tenant_id))

    assert result is primary.answered
    assert result.passages == (served,)
    assert shadow.asked, "the comparison never ran, so this proves nothing"


async def test_a_shadow_arm_that_raises_does_not_reach_the_caller(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The challenger is not trusted yet, so EVERY exception it can produce stops here.

    This is the failure mode that makes a shadow read worth running against an adapter
    written from assumptions (`retrieval/supermemory_wire.ASSUMED_CONTRACT`): the shape we
    guessed wrong raises, and a client whose question the primary already answered must
    never learn that happened.
    """
    tenant_id = uuid.uuid4()
    served = _passage(uuid.uuid4())
    primary = FakeArm("pgvector", passages=(served,))
    shadow = FakeArm("supermemory", raises=ShadowArmUnavailableError("box 3 is down"))
    retriever = ShadowReadRetriever(primary, shadow=shadow, tenants=frozenset({tenant_id}))

    with caplog.at_level(logging.INFO):
        result = await retriever.retrieve(_request(tenant_id))

    assert result is primary.answered
    assert result.passages == (served,)
    assert _compared(caplog).shadow_error == "ShadowArmUnavailableError"


async def test_the_cache_stamp_never_asks_the_shadow_arm() -> None:
    """`knowledge_epoch` runs before the cache on every question, hit or miss.

    Two reasons it must be the primary's alone, and the second is the one that would have
    been visible to clients: asking two stores would double the cost of the path that
    exists to be cheap, and mixing the challenger into the cache key would invalidate every
    cached answer the moment the switch moved.
    """
    tenant_id = uuid.uuid4()
    primary, shadow = FakeArm("pgvector"), FakeArm("supermemory")
    retriever = ShadowReadRetriever(primary, shadow=shadow, tenants=frozenset({tenant_id}))

    assert await retriever.knowledge_epoch(_request(tenant_id)) == "pgvector-epoch"
    assert shadow.asked == []


def test_the_wrapper_reports_the_primarys_name_and_promises() -> None:
    """`name` labels the metric that answers "where did this come from".

    A wrapper name would make `record_retrieval_ms` report a store nobody queried. The
    capabilities matter more: they are what a caller is refused or served against, so the
    challenger must not be able to widen or narrow a single promise made to a client.
    """
    primary = FakeArm("pgvector")
    retriever = ShadowReadRetriever(primary, shadow=UnavailableArm(), tenants=frozenset())

    assert retriever.name == "pgvector"
    assert retriever.capabilities == primary.capabilities


# --- recorded: counts, never content --------------------------------------------------


async def test_disagreement_is_recorded_and_agreement_is_recorded_too(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Both outcomes are written, because the retirement is argued from a RATE.

    A log holding only the disagreements has no denominator, so nobody could say whether
    the arms differed on two questions or on two hundred.
    """
    tenant_id = uuid.uuid4()
    shared = uuid.uuid4()
    agreeing = ShadowReadRetriever(
        FakeArm("pgvector", passages=(_passage(shared),)),
        shadow=FakeArm("supermemory", passages=(_passage(shared),)),
        tenants=frozenset({tenant_id}),
    )
    with caplog.at_level(logging.INFO):
        await agreeing.retrieve(_request(tenant_id))
    record = _compared(caplog)
    assert record.agreed is True
    assert record.jaccard == 1.0
    assert record.top1_same is True

    caplog.clear()
    differing = ShadowReadRetriever(
        FakeArm("pgvector", passages=(_passage(uuid.uuid4()),)),
        shadow=FakeArm("supermemory", passages=(_passage(uuid.uuid4()),)),
        tenants=frozenset({tenant_id}),
    )
    with caplog.at_level(logging.INFO):
        await differing.retrieve(_request(tenant_id))
    record = _compared(caplog)
    assert record.agreed is False
    assert record.jaccard == 0.0
    assert record.overlap == 0


async def test_the_comparison_line_carries_no_question_and_no_passage(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Hard rule 6, asserted rather than intended.

    The question is a client's own prose and the passages are their business knowledge. A
    comparison is exactly the situation where it is tempting to log both — "which documents
    did they differ on" is what an operator wants — and it is still not allowed.
    """
    tenant_id = uuid.uuid4()
    retriever = ShadowReadRetriever(
        FakeArm("pgvector", passages=(_passage(uuid.uuid4(), label="Rent card"),)),
        shadow=FakeArm("supermemory", passages=(_passage(uuid.uuid4()),)),
        tenants=frozenset({tenant_id}),
    )

    with caplog.at_level(logging.INFO):
        await retriever.retrieve(_request(tenant_id))

    written = " ".join(str(value) for value in vars(_compared(caplog)).values())
    assert "what do flats cost" not in written
    assert "Rent card" not in written
    assert "62 lakh" not in written


async def test_an_unkeyable_passage_cannot_read_as_agreement(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A record box 3 sent without our `source_id` is a citation we cannot check.

    It is counted as a disagreement on purpose (`retrieval/compare.py`'s module docstring),
    and counted SEPARATELY so an operator reading a bad agreement number can tell "the arms
    disagree" from "box 3 is not sending our metadata back".
    """
    tenant_id = uuid.uuid4()
    unkeyed = Passage(
        text="Two-bedroom flats start at 62 lakh.",
        provenance=Provenance(label="Unlabelled", tier="t3"),
    )
    retriever = ShadowReadRetriever(
        FakeArm("pgvector", passages=(_passage(uuid.uuid4()),)),
        shadow=FakeArm("supermemory", passages=(unkeyed,)),
        tenants=frozenset({tenant_id}),
    )

    with caplog.at_level(logging.INFO):
        await retriever.retrieve(_request(tenant_id))

    record = _compared(caplog)
    assert record.agreed is False
    assert record.unkeyed_shadow == 1
    assert record.unkeyed_served == 0


# --- money and consent: a shadow search is real spend ---------------------------------


async def test_a_tenant_nobody_enrolled_is_never_shadowed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The arm is not even ASKED, which is the assertion that matters: it costs money.

    Both arms buy an embedding per question and meter it against the tenant whose question
    it was, so a shadow read spends a client's AI quota on an experiment they did not ask
    for. Enrolment is per tenant for that reason and for no other.
    """
    retriever = ShadowReadRetriever(
        FakeArm("pgvector", passages=(_passage(uuid.uuid4()),)),
        shadow=(shadow := FakeArm("supermemory")),
        tenants=frozenset({uuid.uuid4()}),
    )

    with caplog.at_level(logging.INFO):
        await retriever.retrieve(_request(uuid.uuid4()))

    assert shadow.asked == []
    assert [r for r in caplog.records if r.getMessage() == "retrieval_shadow_compared"] == []


def test_an_empty_enrolment_list_means_nobody_and_is_the_default() -> None:
    """Turning the arm on by itself must spend nothing. That is the whole safety story."""
    assert shadowed_tenants() == frozenset()


def test_a_malformed_enrolment_entry_costs_a_comparison_and_not_an_answer(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Parsed on the request path, so a typo in the ops console must not raise at a client.

    The good ids still enrol; the bad one is dropped and counted. Raising here would turn a
    mistyped list into an outage on every dashboard question.
    """
    good = uuid.uuid4()
    settings = retrieval_service.get_settings()
    monkeypatch.setattr(settings, "retrieval_shadow_tenant_ids", f" {good} , not-a-uuid,")

    with caplog.at_level(logging.ERROR):
        assert shadowed_tenants() == frozenset({good})

    assert [r for r in caplog.records if r.getMessage() == "retrieval_shadow_tenant_unparseable"]


# --- the switch: live, and reversible without a redeploy ------------------------------


async def test_the_switch_turns_the_comparison_on_and_off_between_two_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**THE ROLLBACK §8.6 REQUIRES.** No restart, no republish, no cache to unwind.

    `get_retriever` is called per request and holds no state, so the assertion is simply
    that building it twice under two settings produces two different shapes. The default is
    asserted first: a deployment that has set nothing is not comparing anything.
    """
    tenant_id, _ = await _tenant_with_published_agent()
    settings = retrieval_service.get_settings()
    monkeypatch.setattr(settings, "retrieval_provider", "pgvector")
    # The two preconditions the pgvector arm is built behind. Faked at the selector's own
    # symbols rather than through `Settings`, because `embedding_leg` reads the Azure
    # credential triple and `tests/conftest._no_ambient_credentials` strips it — this file
    # is about the SWITCH, and the store's own configuration is `retrieval_pgvector_test`'s.
    monkeypatch.setattr(retrieval_service, "embedding_leg", lambda: _CONFIGURED_LEG)
    monkeypatch.setattr(retrieval_service, "embedding_price_is_billable", lambda: True)

    async with tenant_session(tenant_id) as session:
        assert isinstance(retrieval_service.get_retriever(session)._t3, PgVectorRetriever)

        monkeypatch.setattr(settings, "retrieval_shadow_arm", "supermemory")
        monkeypatch.setattr(settings, "retrieval_shadow_tenant_ids", str(tenant_id))
        # Box 3 is not configured on this deployment, so the arm cannot be built — and the
        # selector must still serve, unwrapped, rather than refuse. That is the same
        # tolerant-boot rule `supermemory_t3` follows, applied one layer out.
        assert isinstance(retrieval_service.get_retriever(session)._t3, PgVectorRetriever)

        monkeypatch.setattr(retrieval_service, "_shadow_arm", lambda _s, _a: FakeArm("box3"))
        wrapped = retrieval_service.get_retriever(session)._t3
        assert isinstance(wrapped, ShadowReadRetriever)
        assert wrapped.name == "pgvector"

        monkeypatch.setattr(settings, "retrieval_shadow_arm", "off")
        assert isinstance(retrieval_service.get_retriever(session)._t3, PgVectorRetriever)


async def test_naming_the_store_that_is_already_serving_compares_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An arm compared with itself measures nothing and costs a round trip per question."""
    tenant_id, _ = await _tenant_with_published_agent()
    settings = retrieval_service.get_settings()
    monkeypatch.setattr(settings, "retrieval_provider", "pgvector")
    monkeypatch.setattr(settings, "retrieval_shadow_arm", "pgvector")
    monkeypatch.setattr(settings, "retrieval_shadow_tenant_ids", str(tenant_id))
    # The two preconditions the pgvector arm is built behind. Faked at the selector's own
    # symbols rather than through `Settings`, because `embedding_leg` reads the Azure
    # credential triple and `tests/conftest._no_ambient_credentials` strips it — this file
    # is about the SWITCH, and the store's own configuration is `retrieval_pgvector_test`'s.
    monkeypatch.setattr(retrieval_service, "embedding_leg", lambda: _CONFIGURED_LEG)
    monkeypatch.setattr(retrieval_service, "embedding_price_is_billable", lambda: True)

    async with tenant_session(tenant_id) as session:
        assert isinstance(retrieval_service.get_retriever(session)._t3, PgVectorRetriever)


async def test_the_shadow_copy_of_a_degrading_adapter_refuses_instead_of_degrading() -> None:
    """`UnavailableArm` is why a comparison against box 3 is worth reading.

    On the serving path `SupermemoryRetriever` degrades into the Postgres retriever (§8.5),
    which is correct there and would be a lie here: every request box 3 failed would read
    as "box 3 agrees with pgvector perfectly".
    """
    with pytest.raises(ShadowArmUnavailableError):
        await UnavailableArm().retrieve(_request(uuid.uuid4()))
    with pytest.raises(ShadowArmUnavailableError):
        await UnavailableArm().knowledge_epoch(_request(uuid.uuid4()))


def test_the_shadow_read_is_off_on_a_deployment_that_has_set_nothing() -> None:
    """The shipped default. A feature that spends money is opted into, never inherited."""
    settings: Any = retrieval_service.get_settings()
    assert settings.retrieval_shadow_arm == "off"
    assert settings.retrieval_shadow_tenant_ids is None
