"""A call that answered nothing says so — on our side, durably, and where somebody looks.

**THE DEFECT THIS FILE PINS.** When a client's knowledge pack fails to load,
`voice_worker/knowledge.load_session_knowledge` answers `temporarily_unavailable` to every
question for the whole call. That is the right choice — a conversation that dies because
the KB did not load is worse than one where the agent says it cannot verify something right
now — but until `KnowledgeReport` existed the fact reached NOTHING of ours: the only trace
was a loguru line inside a container Pipecat Cloud operates, so from the product nobody
could tell afterwards that a call had answered nothing.

**AND THE MULTIPLIER, WHICH IS THE NASTIER HALF.** Pipecat Cloud reuses a container across
sessions, so one fetch failure is not one bad call — it meets every call that lands on that
container until it is replaced. The last section of this file asserts that N degraded calls
read as N, both in the rows and in the count the operator is handed.

It runs against the real app over `httpx.ASGITransport` (`tests/worker_api_harness.py`) for
`voice_worker_sink_test.py`'s reason: the point of a contract split across two deployables
is that the two halves AGREE, and a mocked transport would only prove one half is
self-consistent.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from apps.api.db.session import tenant_session
from apps.api.worker import service as worker_service
from calevate_shared.engine import pipecat_call_ref
from calevate_shared.events import CallEvent, TranscriptTurn
from calevate_shared.worker_api import (
    DEGRADED_KNOWLEDGE_STATES,
    KNOWLEDGE_STATES,
    KnowledgeReport,
)
from sqlalchemy import text
from tests.worker_api_harness import declare_pipecat_engine, published_agent, worker_client
from voice_worker.api_client import WorkerApiClient, WorkerApiError
from voice_worker.knowledge import SessionKnowledge
from voice_worker.session import knowledge_report
from voice_worker.sink import HttpEventSink

pytestmark = [pytest.mark.rls]

#: A digest-shaped id. The wire pins the shape (lowercase sha256 hex), so a test that made
#: one up out of a short word would pass a 422 off as a finding.
DIGEST = "a" * 64
OTHER_DIGEST = "b" * 64


@pytest.fixture(autouse=True)
def _pipecat_deployment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    yield from declare_pipecat_engine(monkeypatch)


def _capture_alerts(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, dict[str, Any]]]:
    """Every alarm the SERVER raises, with its ids, so the count can be read back.

    The real `alert()` is replaced rather than the delivery thread inspected: what is under
    test is which code is raised with which detail, not the transport that has its own
    tests.
    """
    fired: list[tuple[str, str, dict[str, Any]]] = []
    monkeypatch.setattr(
        worker_service,
        "alert",
        lambda stage, code, **kwargs: fired.append((stage, code, dict(kwargs))),
    )
    return fired


async def _sink(call_id: str, api: Any | None = None) -> tuple[HttpEventSink, uuid.UUID, uuid.UUID]:
    tenant_id, agent_id, _ref = await published_agent()
    sink = HttpEventSink(
        api if api is not None else worker_client(),
        call_id=call_id,
        tenant_id=tenant_id,
        agent_id=agent_id,
        direction="inbound",
        # The timer is off in every test here: a flush must happen because something asked
        # for it, never because a clock happened to fire mid-assertion.
        turn_flush_seconds=0,
    )
    return sink, tenant_id, agent_id


async def _stored_state(tenant_id: uuid.UUID, call_id: str) -> str | None:
    async with tenant_session(tenant_id) as db:
        return (
            await db.execute(
                text("SELECT knowledge_state FROM calls WHERE engine_call_id = :c"),
                {"c": pipecat_call_ref(tenant_id, call_id)},
            )
        ).scalar_one()


def _event(call_id: str, tenant_id: uuid.UUID, agent_id: uuid.UUID, status: str) -> CallEvent:
    return CallEvent(
        call_id=call_id,
        tenant_id=tenant_id,
        agent_id=agent_id,
        direction="inbound",
        status=status,  # type: ignore[arg-type]
        engine="pipecat",
    )


# ---------------------------------------------------------------------------------------
# 1. The vocabulary. One declaration, two deployables, one CHECK constraint.
# ---------------------------------------------------------------------------------------


def test_the_degraded_states_are_exactly_the_states_that_are_not_healthy() -> None:
    """`KnowledgeState` and `KnowledgeUnavailableReason` are declared side by side, and this
    is what stops them drifting: adding a fifth failure to one and not the other would make
    a real outage read as a healthy call."""
    assert DEGRADED_KNOWLEDGE_STATES < KNOWLEDGE_STATES
    assert {"available", "no_pack"} == KNOWLEDGE_STATES - DEGRADED_KNOWLEDGE_STATES


def test_the_worker_reason_is_the_wire_reason_and_not_a_second_spelling() -> None:
    """`voice_worker/knowledge.UnavailableReason` is an ALIAS. A second Literal with the
    same four words would type-check on both sides and diverge on the fifth."""
    from voice_worker import knowledge

    assert knowledge.UnavailableReason is not None
    for reason in DEGRADED_KNOWLEDGE_STATES:
        assert (
            knowledge_report(
                SessionKnowledge(
                    tenant_id=uuid.uuid4(),
                    agent_id=uuid.uuid4(),
                    unavailable_reason=reason,  # type: ignore[arg-type]
                    requested_digest=DIGEST,
                )
            ).state
            == reason
        )


# ---------------------------------------------------------------------------------------
# 2. The three states the worker can be in, and which of them is a degradation.
# ---------------------------------------------------------------------------------------


def test_no_published_knowledge_base_is_a_state_and_not_a_failure() -> None:
    """An agent whose client published nothing says so. Reporting that as an outage would
    make every such agent look broken for ever, which is how a real alarm stops being read."""
    report = knowledge_report(None)
    assert report.state == "no_pack"
    assert report.state not in DEGRADED_KNOWLEDGE_STATES
    assert report.digest == ""


def test_a_pack_that_loaded_reports_available_rather_than_nothing() -> None:
    """NULL must keep meaning "nobody reported". If a healthy call sent no report, an
    operator counting degraded calls could not tell a healthy fleet from a silent one."""
    report = knowledge_report(
        SessionKnowledge(
            tenant_id=uuid.uuid4(),
            agent_id=uuid.uuid4(),
            index=object(),  # type: ignore[arg-type]
            requested_digest=DIGEST,
        )
    )
    assert report.state == "available"
    assert report.digest == DIGEST


# ---------------------------------------------------------------------------------------
# 3. It reaches our side.
# ---------------------------------------------------------------------------------------


async def test_a_failed_fetch_reaches_our_database_and_raises_the_alarm(
    worker_token: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE WHOLE DEFECT, END TO END. A pack that did not load is a word on the call row and
    an alarm on `/admin/ops/alerts`, not a line in somebody else's container."""
    fired = _capture_alerts(monkeypatch)
    call_id = f"kb-{uuid.uuid4().hex[:8]}"
    sink, tenant_id, agent_id = await _sink(call_id)

    sink.report_knowledge(KnowledgeReport(state="fetch_failed", digest=DIGEST))
    await sink.on_call_event(_event(call_id, tenant_id, agent_id, "in_progress"))
    await sink.flush()

    assert await _stored_state(tenant_id, call_id) == "fetch_failed"
    codes = [(stage, code) for stage, code, _ in fired]
    assert ("CORE_LOGIC", "call_ran_without_knowledge") in codes
    ids = next(kw for _, code, kw in fired if code == "call_ran_without_knowledge")
    assert ids["state"] == "fetch_failed"
    assert ids["digest"] == DIGEST
    assert ids["agent_id"] == str(agent_id)


async def test_the_report_leaves_even_when_no_turn_and_no_event_ever_did(
    worker_token: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The empty-flush early return used to swallow it.

    A call whose turns and events had all already been sent would drop the one fact that
    says it answered nothing, because `settle` flushes first and an empty flush returned 0
    without building a batch.
    """
    _capture_alerts(monkeypatch)
    call_id = f"kb-{uuid.uuid4().hex[:8]}"
    sink, tenant_id, _agent_id = await _sink(call_id)

    sink.report_knowledge(KnowledgeReport(state="absent", digest=DIGEST))
    assert await sink.flush() == 0  # no turns went; the report still did

    assert await _stored_state(tenant_id, call_id) == "absent"


async def test_a_successful_call_reports_no_degradation_and_raises_nothing(
    worker_token: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A FALSE POSITIVE HERE WOULD BE WORSE THAN THE SILENCE IT REPLACED: an alarm that
    fires on healthy calls is one an operator learns to close without reading."""
    fired = _capture_alerts(monkeypatch)
    call_id = f"kb-{uuid.uuid4().hex[:8]}"
    sink, tenant_id, agent_id = await _sink(call_id)

    sink.report_knowledge(KnowledgeReport(state="available", digest=DIGEST))
    await sink.on_call_event(_event(call_id, tenant_id, agent_id, "in_progress"))
    await sink.flush()

    assert await _stored_state(tenant_id, call_id) == "available"
    assert [code for _, code, _ in fired if code == "call_ran_without_knowledge"] == []


async def test_an_agent_with_no_knowledge_base_is_not_an_incident(
    worker_token: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    fired = _capture_alerts(monkeypatch)
    call_id = f"kb-{uuid.uuid4().hex[:8]}"
    sink, tenant_id, agent_id = await _sink(call_id)

    sink.report_knowledge(knowledge_report(None))
    await sink.on_call_event(_event(call_id, tenant_id, agent_id, "in_progress"))
    await sink.flush()

    assert await _stored_state(tenant_id, call_id) == "no_pack"
    assert [code for _, code, _ in fired if code == "call_ran_without_knowledge"] == []


async def test_a_later_batch_does_not_blank_the_state_it_already_reported(
    worker_token: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The report rides ONE batch; every batch after it carries `None`. A column that let a
    NULL overwrite the word would lose the fact on the next turn of the same call."""
    _capture_alerts(monkeypatch)
    call_id = f"kb-{uuid.uuid4().hex[:8]}"
    sink, tenant_id, agent_id = await _sink(call_id)

    sink.report_knowledge(KnowledgeReport(state="fetch_failed", digest=DIGEST))
    await sink.on_call_event(_event(call_id, tenant_id, agent_id, "in_progress"))
    turn = TranscriptTurn(call_id=call_id, idx=0, speaker="caller", text="hi")
    await sink.on_transcript_turn(turn)
    await sink.flush()
    await sink.on_call_event(_event(call_id, tenant_id, agent_id, "completed"))

    assert await _stored_state(tenant_id, call_id) == "fetch_failed"


# ---------------------------------------------------------------------------------------
# 4. It is reporting, not a gate.
# ---------------------------------------------------------------------------------------


def test_reporting_is_synchronous_and_cannot_be_awaited_on_the_ring() -> None:
    """`run_call` hands this over between resolving the pack and starting the pipeline —
    the moment the caller is waiting to be greeted. An `await` here would put the platform
    API's latency in front of the first sentence of a call that is already degraded."""
    import inspect

    assert not inspect.iscoroutinefunction(HttpEventSink.report_knowledge)


async def test_a_report_that_cannot_be_sent_costs_the_report_and_never_the_call(
    worker_token: None,
) -> None:
    """A BROKEN PLATFORM API MUST NOT BREAK A LIVE CALL, and must not silently lose the
    fact either: the report stays pending exactly as buffered turns do, and the next flush
    that gets through carries it."""

    class _Broken:
        def __init__(self, real: WorkerApiClient) -> None:
            self._real = real
            self.broken = True

        async def post_observations(self, *args: Any, **kwargs: Any) -> Any:
            if self.broken:
                raise WorkerApiError("connection reset")
            return await self._real.post_observations(*args, **kwargs)

    call_id = f"kb-{uuid.uuid4().hex[:8]}"
    api = _Broken(worker_client())
    sink, tenant_id, _agent_id = await _sink(call_id, api=api)

    # Recording it never touches the network, so it cannot fail however dead the API is.
    sink.report_knowledge(KnowledgeReport(state="fetch_failed", digest=DIGEST))
    with pytest.raises(WorkerApiError):
        await sink.flush()

    api.broken = False
    await sink.flush()
    assert await _stored_state(tenant_id, call_id) == "fetch_failed"


# ---------------------------------------------------------------------------------------
# 5. Hard rule 6.
# ---------------------------------------------------------------------------------------


def test_the_report_carries_ids_and_a_word_and_has_nowhere_to_put_anything_else() -> None:
    """The model FORBIDS extras, so this is a structural property rather than a habit: a
    future edit cannot add a question, a passage or a number to this body by accident."""
    report = KnowledgeReport(state="fetch_failed", digest=DIGEST)
    assert set(report.model_dump().keys()) == {"state", "digest"}
    with pytest.raises(ValueError):
        KnowledgeReport(state="fetch_failed", digest=DIGEST, question="what are your hours")  # type: ignore[call-arg]


def test_a_digest_is_pinned_to_the_shape_a_digest_has() -> None:
    """An object key names a tenant, an agent and a content hash. Anything that is not a
    sha256 is not one, and refusing it at the edge keeps an unmatchable string out of the
    alarm an operator is trying to triage with."""
    with pytest.raises(ValueError):
        KnowledgeReport(state="fetch_failed", digest="+919000000000")


# ---------------------------------------------------------------------------------------
# 6. The warm container: one failure, N calls.
# ---------------------------------------------------------------------------------------


async def test_one_fetch_failure_across_many_calls_reads_as_many_calls(
    worker_token: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE HALF THAT MOTIVATED THE COUNT. A container is reused across sessions, so the
    same dead store meets call after call. Three things have to hold: every call carries
    its own durable row, the alarm is raised for each, and the count an operator is handed
    GROWS — otherwise the third caller's outage looks exactly like the first caller's.
    """
    fired = _capture_alerts(monkeypatch)
    tenant_id, agent_id, ref = await published_agent()
    api = worker_client()
    call_ids = [f"kb-{uuid.uuid4().hex[:8]}" for _ in range(3)]

    for call_id in call_ids:
        sink = HttpEventSink(
            api,
            call_id=call_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
            direction="inbound",
            turn_flush_seconds=0,
        )
        sink.report_knowledge(KnowledgeReport(state="fetch_failed", digest=OTHER_DIGEST))
        await sink.on_call_event(_event(call_id, tenant_id, agent_id, "in_progress"))
        await sink.flush()

    for call_id in call_ids:
        assert await _stored_state(tenant_id, call_id) == "fetch_failed"

    counts = [
        int(kw["calls_affected"]) for _, code, kw in fired if code == "call_ran_without_knowledge"
    ]
    assert len(counts) == 3
    assert counts == sorted(counts) and counts[-1] >= 3

    # And the durable record answers the blast radius after the fact, which is what an
    # operator asks the morning after — `ref` is unused beyond minting the agent.
    assert ref
    async with tenant_session(tenant_id) as db:
        total = (
            await db.execute(
                text(
                    "SELECT count(*) FROM calls WHERE agent_id = :a "
                    "AND knowledge_state = 'fetch_failed'"
                ),
                {"a": agent_id},
            )
        ).scalar_one()
    assert int(total) == 3
