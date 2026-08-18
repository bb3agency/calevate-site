"""D-31's central claim, under test: **the poller is the guarantee of record.**

Bolna delivers at most once and never retries (D-31, TRD §5), so every call record in
this product rests on `reconcile_executions` being able to recover a call the webhook
layer lost. "Recover" has to mean the whole call — the transcript, the cost, the usage
row, the lead — because a status line with nothing behind it is a call the client cannot
see and we cannot bill.

WHAT THIS FILE FOUND, by dropping a delivery rather than reading the code. Two shapes,
and only one of them worked:

1. **the delivery never arrives at all** — no webhook, no call row. The poller lists the
   execution, finds nothing, re-drives it, and everything lands. This held.
2. **the delivery arrives and the pipeline is then lost** — `ingest_engine_event` writes
   `calls.status = 'completed'` and only afterwards enqueues the post-call job, so a
   Redis refusal, a killed worker or an exhausted retry ladder leaves a completed call
   row with no transcript, no extraction, no lead and no usage event. The probe asked
   only "is there a completed call row", so it skipped that call on every subsequent
   tick. Measured: ten consecutive ticks, `repaired=0`, artefacts still zero. For that
   shape the poller guaranteed the status line and nothing else.

`_pipeline_settled` now asks what the SNAPSHOT implies rather than what calls in general
look like, which is what makes the question answerable without a schema column: the
engine's own record says whether this execution had a transcript and whether it had a
cost, so an absence stops being ambiguous. The tests below are written as the properties
that must hold, including the two that keep the fix from over-correcting into "re-drive
everything" — a re-drive costs a model round trip, and an alarm that fires on healthy
calls is the defect this probe's history is made of.

Scope discipline: other suites share this Postgres and this Redis. Every tenant here is
minted fresh, every execution id carries `RUN`, and nothing counts a whole table.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine, reset_engine_cache
from apps.workers import pipeline
from calevate_shared.engine import ExecutionListing, ExecutionSnapshot
from sqlalchemy import text
from tests.smoke_pipeline_test import _seed_tenant

RUN = uuid.uuid4().hex[:12]


@pytest.fixture(autouse=True)
def _stub_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    """The recording copy needs a bucket; nothing here is about object storage."""

    async def _fake_copy(*, source_url: str, tenant_id: UUID, call_id: UUID) -> str:
        return f"recordings/{tenant_id}/{call_id}.wav"

    monkeypatch.setattr(pipeline, "copy_recording", _fake_copy)


class _Repairs:
    """What the poller queued and what it called each repair.

    The KIND matters as much as the count: `missing_call` is a webhook the vendor never
    delivered and `unfinished_pipeline` is one we received and then dropped on our own
    side. They are different incidents with different runbook entries, and one counter
    for both would hide the second for as long as the first kept happening.
    """

    def __init__(self) -> None:
        self.queued: list[tuple[str, dict[str, Any]]] = []
        self.kinds: list[str] = []

    def executions(self) -> list[str]:
        return [str(p.get("execution_id")) for _job, p in self.queued]

    def forget(self) -> None:
        """Drop everything captured so far, so what follows is measured on its own.

        Not a convenience. A test that stages its call by running `ingest_engine_event`
        leaves that job's OWN post-call enqueue in the capture, and an assertion of the
        form "the poller re-drove this execution" then passes on the staging rather than
        on the poller — which is how a test for a re-drive can be green with the poller
        deleted. Found by writing exactly that mistake.
        """
        self.queued.clear()
        self.kinds.clear()


@pytest.fixture
def repairs(monkeypatch: pytest.MonkeyPatch) -> _Repairs:
    """Intercept the queue so a test can DRIVE what the poller decided to re-drive.

    The jobs are run by `_drain` rather than by a worker because what is under test is
    the poller's VERDICT and the pipeline's output, not arq — `ingest_ordering_test` and
    `reliability_audit_test` are where the retry ladder is measured on a real worker.
    """
    captured = _Repairs()

    async def _capture(job: str, payload: dict[str, Any], **kwargs: Any) -> str:
        captured.queued.append((job, payload))
        return f"{job}:{len(captured.queued)}"

    def _record(*, kind: str) -> None:
        captured.kinds.append(kind)

    monkeypatch.setattr(pipeline, "enqueue", _capture)
    monkeypatch.setattr(pipeline, "record_reconciliation_repair", _record)
    return captured


async def _drain(captured: _Repairs) -> None:
    """Run whatever the poller queued, and whatever that queued in turn."""
    pending = list(captured.queued)
    captured.queued.clear()
    while pending:
        job, payload = pending.pop(0)
        if job == pipeline.INGEST_JOB:
            await pipeline.ingest_engine_event({}, payload)
        elif job == pipeline.POSTCALL_JOB:
            await pipeline.run_post_call_pipeline({}, payload)
        pending.extend(captured.queued)
        captured.queued.clear()


# --------------------------------------------------------------------- staging


async def _staged(label: str, *, schema: bool = True) -> tuple[UUID, str, str]:
    """A provisioned tenant whose engine holds one completed inbound call.

    Returns (tenant_id, agent_ref, execution_id). Nothing has been ingested yet.
    """
    reset_engine_cache()
    agent_ref = f"pollerguard_{label}_{RUN}"
    tenant_id, agent_id = await _seed_tenant(agent_ref)
    if not schema:
        # An agent with NO extraction schema: `needs_extraction` is false for a silent
        # call on one of these, so the pipeline finishes it writing no extraction row.
        # That is the case a naive "no extraction means stalled" probe re-drives forever.
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE agents SET extraction_schema_id = NULL WHERE id = :aid"),
                {"aid": agent_id},
            )
    execution_id = f"exec_{label}_{RUN}"
    get_engine().seed_inbound_call(  # type: ignore[attr-defined]
        call_id=execution_id,
        agent_ref=agent_ref,
        from_e164=f"+9198{uuid.uuid4().int % 100000000:08d}",
        to_e164="+911140000000",
    )
    return tenant_id, agent_ref, execution_id


async def _age(tenant_id: UUID, execution_id: str, *, minutes: int) -> None:
    """Push one call's clock back on BOTH sides of the seam.

    The engine's copy decides whether the listing still shows it (the poller's window is
    30 minutes) and our copy decides whether the pipeline is late (`PIPELINE_STALL_AFTER`
    is 10). Moving only one of them would test a call that cannot exist.
    """
    call = get_engine()._calls[execution_id]  # type: ignore[attr-defined]
    call["started_at"] = datetime.now(UTC) - timedelta(minutes=minutes + 2)
    call["ended_at"] = datetime.now(UTC) - timedelta(minutes=minutes)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE calls SET started_at = now() - make_interval(mins => :start), "
                "ended_at = now() - make_interval(mins => :end) WHERE engine_call_id = :e"
            ),
            {"start": minutes + 2, "end": minutes, "e": execution_id},
        )


async def _artifacts(tenant_id: UUID, execution_id: str) -> dict[str, Any]:
    """Everything the client actually ends up with, by count. Ids and counts only."""
    async with tenant_session(tenant_id) as session:
        call = (
            await session.execute(
                text("SELECT id, status FROM calls WHERE engine_call_id = :e"),
                {"e": execution_id},
            )
        ).first()
        if call is None:
            return {"call": None}
        call_id = call[0]
        counts = (
            await session.execute(
                text(
                    "SELECT "
                    "  (SELECT count(*) FROM transcript_turns WHERE call_id = :c), "
                    "  (SELECT count(*) FROM usage_events WHERE call_id = :c), "
                    "  (SELECT count(*) FROM call_extractions WHERE call_id = :c), "
                    "  (SELECT count(*) FROM leads WHERE tenant_id = :t)"
                ),
                {"c": call_id, "t": tenant_id},
            )
        ).first()
    assert counts is not None
    return {
        "call": call_id,
        "status": call[1],
        "turns": int(counts[0]),
        "usage": int(counts[1]),
        "extractions": int(counts[2]),
        "leads": int(counts[3]),
    }


async def _ingest_only(tenant_id: UUID, agent_ref: str, execution_id: str) -> None:
    """Exactly what a delivered webhook does before the pipeline is lost.

    `ingest_engine_event` writes the call row and then enqueues the post-call job; here
    the enqueue succeeds and the job never runs, which is a killed worker, a flushed
    Redis, or a retry ladder that ran out. The call row is `completed` and NOTHING else
    exists — precisely the state the old probe read as "already done".
    """
    swallowed: list[str] = []

    async def _swallow(job: str, payload: dict[str, Any], **kwargs: Any) -> str:
        swallowed.append(job)
        return "queued-and-lost"

    real = pipeline.enqueue
    pipeline.enqueue = _swallow  # type: ignore[assignment]
    try:
        outcome = await pipeline.ingest_engine_event(
            {}, {"engine": "fake", "execution_id": execution_id, "engine_agent_ref": agent_ref}
        )
    finally:
        pipeline.enqueue = real  # type: ignore[assignment]
    assert outcome == "pipeline_enqueued", outcome
    assert swallowed == [pipeline.POSTCALL_JOB], swallowed
    state = await _artifacts(tenant_id, execution_id)
    assert state["status"] == "completed" and state["turns"] == 0, (
        f"the premise of this test is a completed call row with nothing behind it: {state}"
    )


# ============================================================ 1. a dropped delivery


async def test_a_delivery_dropped_entirely_is_recovered_whole(repairs: _Repairs) -> None:
    """The claim D-31 rests on, asserted on the artefacts rather than on the status.

    No webhook ever arrives. What the client must end up with is not "a call row" but a
    transcript, an extraction, a lead and a usage ledger — a recovery that stopped at
    the status line would leave the call invisible in the dashboard and absent from the
    invoice, and nothing would ever say so.
    """
    tenant_id, _agent_ref, execution_id = await _staged("dropped")

    assert (await _artifacts(tenant_id, execution_id))["call"] is None, (
        "the premise: nothing has been ingested"
    )

    await pipeline.reconcile_executions({})
    assert execution_id in repairs.executions(), "the poller did not even see the lost call"
    assert repairs.kinds == ["missing_call"], repairs.kinds
    await _drain(repairs)

    state = await _artifacts(tenant_id, execution_id)
    assert state["status"] == "completed"
    assert state["turns"] > 0, "a recovered call with no transcript is a call nobody can read"
    assert state["usage"] > 0, "a recovered call with no usage row is a call nobody billed"
    assert state["extractions"] == 1
    assert state["leads"] == 1, "the whole point of the pipeline is the lead"


# ================================================ 2. a delivery whose pipeline was lost


async def test_a_call_whose_pipeline_never_ran_is_repaired_rather_than_skipped(
    repairs: _Repairs,
) -> None:
    """THE DEFECT. The webhook landed, the call row says `completed`, and the post-call
    job was lost — so the transcript, the extraction, the lead and the usage row do not
    exist and never will.

    The probe used to ask "is there a completed call row", which is true here, so the
    poller skipped this execution on every tick until it aged out of the 30-minute
    window. The call was then unrecoverable by any mechanism: the vendor does not
    redeliver (D-31), the ARQ job is gone, and the only trace was a stall alarm that
    reports rather than repairs.
    """
    tenant_id, agent_ref, execution_id = await _staged("lostjob")
    await _ingest_only(tenant_id, agent_ref, execution_id)
    await _age(tenant_id, execution_id, minutes=18)

    await pipeline.reconcile_executions({})

    assert execution_id in repairs.executions(), (
        "a completed call row with no transcript, no extraction and no usage row is a "
        "pipeline that never ran; the poller skipped it"
    )
    assert repairs.kinds == ["unfinished_pipeline"], (
        f"a call we received and dropped is not the same incident as a webhook we never "
        f"received; got {repairs.kinds}"
    )
    await _drain(repairs)

    state = await _artifacts(tenant_id, execution_id)
    assert state["turns"] > 0 and state["usage"] > 0 and state["extractions"] == 1, state
    assert state["leads"] == 1


async def test_the_repair_is_driven_by_the_artifacts_not_by_the_status(
    repairs: _Repairs,
) -> None:
    """The narrower half of the same property, so a fix that merely re-drove every
    completed call would not pass.

    The transcript is present and the usage row is not: the pipeline died between step 2
    and step 5, which is the shape that costs money rather than visibility. The poller
    must notice the ONE missing artefact.
    """
    tenant_id, agent_ref, execution_id = await _staged("halfway")
    await _ingest_only(tenant_id, agent_ref, execution_id)
    await _age(tenant_id, execution_id, minutes=18)

    state = await _artifacts(tenant_id, execution_id)
    async with tenant_session(tenant_id) as session:
        # Stage 2 landed, nothing after it did.
        await session.execute(
            text(
                "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, text, "
                "text_redacted, created_at, updated_at) VALUES (:id, :t, :c, 0, 'agent', "
                "'hello', 'hello', now(), now())"
            ),
            {"id": uuid7(), "t": tenant_id, "c": state["call"]},
        )

    await pipeline.reconcile_executions({})

    assert execution_id in repairs.executions(), (
        "a call the engine charged us for, with no usage row against it, is unbilled work"
    )
    assert repairs.kinds == ["unfinished_pipeline"]


# ======================================================== 3. and it does not over-correct


async def test_a_pipeline_still_inside_its_ladder_is_left_alone(repairs: _Repairs) -> None:
    """The counterweight, and it is not cosmetic.

    A call that hung up thirty seconds ago has a post-call job that is queued or walking
    its retry ladder (`RETRY_BACKOFF_S` is 30s then 120s). Re-driving it would put a
    second extraction — a billed model round trip — beside one that is about to finish,
    and would score a healthy call as a repair, which is exactly how the repair metric
    became meaningless the last time this probe was wrong.
    """
    tenant_id, agent_ref, execution_id = await _staged("inflight")
    await _ingest_only(tenant_id, agent_ref, execution_id)
    # Deliberately NOT aged: the call ended moments ago.

    await pipeline.reconcile_executions({})

    assert execution_id not in repairs.executions(), (
        "the poller raced a pipeline that had not had its SLO budget yet"
    )
    assert repairs.kinds == []


async def test_a_call_the_engine_reports_nothing_for_is_never_re_driven(
    monkeypatch: pytest.MonkeyPatch, repairs: _Repairs
) -> None:
    """The false-positive loop this probe's design exists to avoid.

    A silent call on an agent with no extraction schema legitimately produces no
    transcript, no extraction and — with no cost reported — no usage row. Asked without
    the snapshot, "are the artefacts there" reads that healthy call as stalled on every
    tick, forever, and each tick spends an engine fetch and a model round trip on it.
    Asked WITH the snapshot, nothing was implied, so nothing is missing.
    """
    tenant_id, agent_ref, execution_id = await _staged("bare", schema=False)
    await _ingest_only(tenant_id, agent_ref, execution_id)
    await _age(tenant_id, execution_id, minutes=25)

    bare = ExecutionSnapshot(
        engine_call_id=execution_id,
        engine_agent_ref=agent_ref,
        direction="inbound",
        status="completed",
        raw_status="completed",
        terminal=True,
        billable_ready=True,
        ended_at=datetime.now(UTC) - timedelta(minutes=25),
        transcript=[],
        cost=None,
    )

    class _BareEngine:
        name = "fake"

        async def list_executions(self, *, since: datetime) -> ExecutionListing:
            return ExecutionListing(snapshots=[bare], complete=True)

        async def get_execution(self, call_id: str) -> ExecutionSnapshot:
            # The AUTHORITATIVE read agrees with the listing: this call really is
            # silent and cost-less. Present so the probe's confirmation step (below,
            # and see `_pipeline_settled`) is exercised rather than crashed through —
            # a double that lacks the method would make this clause pass because the
            # sweep swallowed an AttributeError, which is not the property claimed.
            return bare

    monkeypatch.setattr(pipeline, "get_engine", lambda: _BareEngine())

    for _ in range(3):
        await pipeline.reconcile_executions({})

    assert repairs.executions() == [], (
        "a call the engine reports no transcript and no cost for owes nothing; "
        "re-driving it is a model round trip billed for a healthy call, on every tick"
    )


async def test_a_finished_call_stays_finished_however_long_ago_it_ended(
    repairs: _Repairs,
) -> None:
    """The property `pipeline_audit_test` already holds for a fresh call, re-asserted for
    an OLD one — the grace window must not be what is doing the work."""
    tenant_id, agent_ref, execution_id = await _staged("finished")
    await pipeline.ingest_engine_event(
        {}, {"engine": "fake", "execution_id": execution_id, "engine_agent_ref": agent_ref}
    )
    state = await _artifacts(tenant_id, execution_id)
    await pipeline.run_post_call_pipeline(
        {},
        {
            "tenant_id": str(tenant_id),
            "call_id": str(state["call"]),
            "engine": "fake",
            "execution_id": execution_id,
        },
    )
    await _age(tenant_id, execution_id, minutes=25)

    repairs.forget()
    await pipeline.reconcile_executions({})

    assert execution_id not in repairs.executions(), (
        "a call whose pipeline finished must never be re-driven, however old it is"
    )
    assert repairs.kinds == []


async def test_a_summary_listing_row_does_not_certify_a_call_as_finished(
    monkeypatch: pytest.MonkeyPatch, repairs: _Repairs
) -> None:
    """THE SILENT PREMISE UNDER `_expected_artifacts`, and the one shape it cannot see.

    The probe reads what a call was OWED off the snapshot the poller is holding, and
    the poller is holding a row from `list_executions` — which TRD §5 calls a SUMMARY
    ("the poller's listing rows are summaries", `VoiceEngine.get_execution`). Nothing in
    the contract requires a listing row to carry the cost and the transcript, no adapter
    promises it, and Bolna publishes no OpenAPI spec, so whether their `GET /executions`
    rows are as rich as `GET /executions/{id}` is a VENDOR BEHAVIOUR NOBODY HAS VERIFIED
    (D-31/D-32; OPERATIONS §2 gate 6).

    The conformance suite cannot fail on it either: `FakeEngine.list_executions` builds
    its rows with the same `_snapshot_from` as `get_execution`, and the Bolna stub's
    `GET /executions` returns whole `BOLNA_COMPLETED` documents. Both adapters therefore
    make listing rows and fetches indistinguishable, which is precisely the assumption at
    issue.

    If the assumption is wrong, the failure is silent and total for one population:
    a completed call whose pipeline died, on an agent with no extraction schema and a
    tenant with no CRM endpoint, implies NOTHING from a summary row — so the probe
    answers `settled`, the poller never comes back, and the call is never transcribed,
    never metered and never invoiced, with no alert anywhere. D-31 calls this poller the
    guarantee of record; for that shape it would guarantee the status line again.

    So the probe must not conclude "nothing was owed" from an absence in a row that was
    never promised to be complete. It confirms with the authenticated read first.
    """
    tenant_id, agent_ref, execution_id = await _staged("summary", schema=False)
    await _ingest_only(tenant_id, agent_ref, execution_id)
    await _age(tenant_id, execution_id, minutes=25)

    full = await get_engine().get_execution(execution_id)
    assert full.cost is not None and full.transcript, (
        "the premise: the ENGINE holds a cost and a transcript for this call"
    )
    # The same execution as the vendor's LIST endpoint might report it: status and ids,
    # no cost object, no transcript. Nothing else about the call has changed.
    summary = full.model_copy(update={"cost": None, "transcript": [], "raw_document": None})

    class _SummaryListingEngine:
        name = "fake"

        async def list_executions(self, *, since: datetime) -> ExecutionListing:
            return ExecutionListing(snapshots=[summary], complete=True)

        async def get_execution(self, call_id: str) -> ExecutionSnapshot:
            assert call_id == execution_id
            return full

    monkeypatch.setattr(pipeline, "get_engine", lambda: _SummaryListingEngine())

    repairs.forget()
    await pipeline.reconcile_executions({})

    assert repairs.executions() == [execution_id], (
        "a summary listing row was read as proof that this call owed nothing, so the "
        "poller certified a completed call with no transcript and no usage row as done"
    )
    assert repairs.kinds == ["unfinished_pipeline"], repairs.kinds


# ================================================================ 4. the shared threshold


def test_the_alarm_and_the_repair_share_one_deadline() -> None:
    """`report_stalled_pipeline` tells an operator a call was dropped; the poller is what
    repairs it. Two thresholds would mean either an alarm for calls nothing repairs, or a
    repair for calls nothing alarms about — so the dispatcher imports the number rather
    than restating it, and this is the assertion that keeps it that way.
    """
    from apps.workers import dispatcher

    assert pipeline.PIPELINE_STALL_AFTER.total_seconds() == dispatcher.STALL_AFTER_MINUTES * 60


def test_the_repair_deadline_clears_the_pipelines_own_retry_ladder() -> None:
    """The number has to be longer than every delay a healthy pipeline can legitimately
    take, or the poller re-drives calls that are mid-ladder. Derived from the ladder
    rather than compared against a literal: a longer ladder must move this deadline."""
    ladder = sum(pipeline.RETRY_BACKOFF_S)
    assert pipeline.PIPELINE_STALL_AFTER.total_seconds() > ladder * 2, (
        f"the grace ({pipeline.PIPELINE_STALL_AFTER}) leaves no margin over a retry "
        f"ladder of {ladder}s"
    )


# ============================================================= 5. what it must not log


async def test_the_unfinished_pipeline_log_line_carries_no_payload(
    monkeypatch: pytest.MonkeyPatch, repairs: _Repairs
) -> None:
    """Hard rule 6. The one new log line on this path names an execution id and a fixed
    vocabulary of artefact names; a phone number or a transcript reaching it would be a
    breach recorded on every stalled call.
    """
    tenant_id, agent_ref, execution_id = await _staged("logsafe")
    await _ingest_only(tenant_id, agent_ref, execution_id)
    await _age(tenant_id, execution_id, minutes=18)

    lines: list[dict[str, Any]] = []

    def _warning(message: str, *, extra: dict[str, Any] | None = None, **kw: Any) -> None:
        lines.append({"message": message, **(extra or {})})

    monkeypatch.setattr(pipeline.log, "warning", _warning)
    await pipeline.reconcile_executions({})

    unfinished = [line for line in lines if line["message"] == "reconciliation_pipeline_unfinished"]
    assert unfinished, "the repair must say what was missing, or the metric is the only trace"
    rendered = json.dumps(unfinished)
    async with tenant_session(tenant_id) as session:
        phone = (
            await session.execute(
                text("SELECT from_e164 FROM calls WHERE engine_call_id = :e"), {"e": execution_id}
            )
        ).scalar()
    assert phone and phone not in rendered, "a phone number reached the log line"
    assert set(unfinished[0]) == {"message", "execution_id", "missing"}, unfinished[0]
    assert set(unfinished[0]["missing"].split(",")) <= {"transcript", "usage", "extraction"}


# ============================================================ 6. an unmappable execution


async def test_an_execution_we_cannot_map_is_still_handed_on(
    monkeypatch: pytest.MonkeyPatch, repairs: _Repairs
) -> None:
    """Hard rule 1's other edge: never invent a tenant, and never drop the event either.

    An execution whose agent ref resolves to no tenant has no call row to inspect and no
    session to inspect it in, so the probe cannot answer — and "cannot answer" must mean
    re-drive, not skip. `ingest_engine_event` is where an unmapped ref becomes the
    `engine_agent_unmapped` alert, which is how a mis-provisioned agent is noticed on
    day one; a poller that swallowed the execution instead would leave that agent's
    calls disappearing quietly.
    """
    orphan = ExecutionSnapshot(
        engine_call_id=f"exec_orphan_{RUN}",
        engine_agent_ref=f"never_provisioned_{RUN}",
        direction="inbound",
        status="completed",
        raw_status="completed",
        terminal=True,
        billable_ready=True,
        ended_at=datetime.now(UTC) - timedelta(minutes=20),
    )

    class _OrphanEngine:
        name = "fake"

        async def list_executions(self, *, since: datetime) -> ExecutionListing:
            return ExecutionListing(snapshots=[orphan], complete=True)

    monkeypatch.setattr(pipeline, "get_engine", lambda: _OrphanEngine())

    repairs.forget()
    await pipeline.reconcile_executions({})

    assert repairs.executions() == [orphan.engine_call_id], (
        "an execution we cannot map must reach ingest, which is what alerts on it"
    )
    assert repairs.kinds == ["missing_call"]


async def test_the_probe_asks_inside_the_owning_tenants_session(repairs: _Repairs) -> None:
    """Hard rule 1. `calls` is FORCE-RLS'd, so the same question asked without a tenant
    context returns zero rows for every execution ever placed — the poller would then
    score every healthy call as a repair and re-run its pipeline on every tick.

    Asserted by asking the probe DIRECTLY for a call whose pipeline finished: `settled`
    is only reachable through a session that can see the row.
    """
    tenant_id, agent_ref, execution_id = await _staged("session")
    await pipeline.ingest_engine_event(
        {}, {"engine": "fake", "execution_id": execution_id, "engine_agent_ref": agent_ref}
    )
    state = await _artifacts(tenant_id, execution_id)
    await pipeline.run_post_call_pipeline(
        {},
        {
            "tenant_id": str(tenant_id),
            "call_id": str(state["call"]),
            "engine": "fake",
            "execution_id": execution_id,
        },
    )
    await _age(tenant_id, execution_id, minutes=18)

    snapshot = await get_engine().get_execution(execution_id)
    async with untenanted_session() as session:
        blind = (
            await session.execute(
                text("SELECT count(*) FROM calls WHERE engine_call_id = :e"), {"e": execution_id}
            )
        ).scalar()
    assert blind == 0, "the premise: FORCE RLS hides this row from an untenanted session"

    assert await pipeline._pipeline_settled("fake", snapshot) == "settled", (
        "the probe could not see a call that exists, so it would re-drive it forever"
    )


# ==================================================== 7. the alarm the poller now feeds


async def _completed_call_row(tenant_id: UUID, *, with_turns: bool) -> UUID:
    """A completed call that ended 30 minutes ago, on this tenant's own agent."""
    async with tenant_session(tenant_id) as session:
        agent_id = (
            await session.execute(
                text("SELECT id FROM agents WHERE tenant_id = :t LIMIT 1"), {"t": tenant_id}
            )
        ).scalar()
        call_id = uuid7()
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "started_at, ended_at, duration_s, created_at, updated_at) VALUES (:id, :t, :a, "
                ":e, 'inbound', 'completed', now() - interval '32 minutes', "
                "now() - interval '30 minutes', 95, now(), now())"
            ),
            {"id": call_id, "t": tenant_id, "a": agent_id, "e": f"exec_stall_{call_id.hex[:12]}"},
        )
        if with_turns:
            await session.execute(
                text(
                    "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, text, "
                    "text_redacted, created_at, updated_at) VALUES (:id, :t, :c, 0, 'caller', "
                    "'hello', 'hello', now(), now())"
                ),
                {"id": uuid7(), "t": tenant_id, "c": call_id},
            )
    return call_id


async def test_the_stall_alarm_ignores_a_call_that_was_never_owed_an_extraction() -> None:
    """`report_stalled_pipeline` counted every completed call with no `call_extractions`
    row. A SILENT call on an agent with no schema fields legitimately has none —
    `needs_extraction` is false for it and the pipeline finishes writing nothing — so
    those calls sat inside the 24-hour window for the whole 24 hours and the alarm fired
    on healthy traffic twice an hour, forever.

    It matters more now than it did: the poller repairs the calls this alarm used to be
    the only sign of, so what is left in it should be the residue that needs a human. An
    alarm whose entire population is false positives is one nobody reads on the night a
    real stall arrives.
    """
    from apps.workers import dispatcher

    tenant_id, _agent_ref, _execution_id = await _staged("stallbare", schema=False)
    await _completed_call_row(tenant_id, with_turns=False)

    async with tenant_session(tenant_id) as session:
        assert await dispatcher._count_stalled(session) == 0, (
            "a silent call on a schema-less agent owes no extraction, and counting it "
            "makes the alarm permanent"
        )


async def test_the_stall_alarm_still_counts_a_call_the_pipeline_really_dropped() -> None:
    """The counterweight, so the fix above cannot become "count nothing". A call with a
    transcript is a call `needs_extraction` was true for, whatever the agent's schema
    says — the pipeline owed it an extraction and did not write one."""
    from apps.workers import dispatcher

    tenant_id, _agent_ref, _execution_id = await _staged("stallreal", schema=False)
    await _completed_call_row(tenant_id, with_turns=True)

    async with tenant_session(tenant_id) as session:
        assert await dispatcher._count_stalled(session) == 1


async def test_the_stall_alarm_counts_a_schema_bearing_agents_silent_call() -> None:
    """And the other half of the same rule: an agent WITH schema fields is owed an
    extraction even for a call that produced no transcript, because that is exactly what
    `needs_extraction` says. Both halves have to hold or the shared SQL fragment is only
    half the pipeline's rule."""
    from apps.workers import dispatcher

    tenant_id, _agent_ref, _execution_id = await _staged("stallschema")
    await _completed_call_row(tenant_id, with_turns=False)

    async with tenant_session(tenant_id) as session:
        assert await dispatcher._count_stalled(session) == 1


# ============================================== 7. the alarm survives one bad tenant


async def test_the_stall_alarm_survives_a_tenant_it_cannot_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P6.2's isolation, DRIVEN rather than read.

    `worker_reliability_test` pins this shape by reading the source — which is the right
    tool for "is the call inside a handler at all" and the wrong one for "does the handler
    work". The coverage ratchet said so in the only way that is not an opinion: the four
    lines of the `except` branch were **uncovered units in the dial-path surface**, on a
    budget of 1, because no test had ever executed them.

    THE FAILURE MODE IS QUIETNESS, WHICH IS WHY IT NEEDS A REAL RUN. The alarm fires on a
    TOTAL, so a sweep that aborted at tenant three produces a SMALLER number and reads
    exactly like a healthy fleet. What must hold is that the tenants AFTER the broken one
    are still counted, and that the alert says how much of the fleet it actually saw —
    neither of which a source scan can tell you.
    """
    from apps.workers import dispatcher

    tenant_id, _agent_ref, _execution_id = await _staged("stalliso")
    await _completed_call_row(tenant_id, with_turns=True)

    real_session = dispatcher.tenant_session
    broken = uuid.UUID(int=0)

    def _session(tid: UUID) -> Any:
        if tid == broken:
            raise RuntimeError("connection reset")
        return real_session(tid)

    async def _broken_first() -> list[UUID]:
        # In FRONT of the healthy one, so this proves the sweep CONTINUES rather than
        # merely that it does not raise.
        return [broken, tenant_id]

    fired: list[tuple[str, str, str]] = []

    def _alert(kind: str, code: str, *, detail: str = "", **kw: Any) -> None:
        fired.append((kind, code, detail))

    monkeypatch.setattr(dispatcher, "tenant_session", _session)
    monkeypatch.setattr(dispatcher, "_callable_tenants", _broken_first)
    monkeypatch.setattr(dispatcher, "alert", _alert)

    result = await dispatcher.report_stalled_pipeline({})

    parsed = dict(part.split("=") for part in result.split())
    assert int(parsed["unreached"]) == 1
    assert int(parsed["stalled"]) == 1, "the tenant after the broken one was not counted"

    body = next(detail for _kind, code, detail in fired if code == "postcall_pipeline_stalled")
    assert "floor rather than a total" in body, (
        "the alert quotes a number that is short by an unknown amount and must say so — "
        "an alarm that fails towards silence is worse than no alarm"
    )


async def test_a_stall_sweep_that_reached_nobody_still_alerts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`if total or unreached:` rather than `if total:`, executed.

    A sweep that reached no tenant has a total of zero, which is indistinguishable from a
    clean fleet — and zero is the reading an operator takes on the one night it is wrong.
    """
    from apps.workers import dispatcher

    tenant_id, _agent_ref, _execution_id = await _staged("stallnone")

    def _session(tid: UUID) -> Any:
        raise RuntimeError("connection reset")

    fired: list[str] = []
    monkeypatch.setattr(dispatcher, "tenant_session", _session)
    monkeypatch.setattr(dispatcher, "_callable_tenants", lambda: _only(tenant_id))
    monkeypatch.setattr(dispatcher, "alert", lambda kind, code, **kw: fired.append(code))

    result = await dispatcher.report_stalled_pipeline({})

    parsed = dict(part.split("=") for part in result.split())
    assert (int(parsed["stalled"]), int(parsed["unreached"])) == (0, 1)
    assert "postcall_pipeline_stalled" in fired, (
        "a sweep that reached nobody reported zero stalled calls and said nothing"
    )


async def _only(tenant_id: UUID) -> list[UUID]:
    return [tenant_id]


# ================================ 8. the prune sweep must not resurrect the poller's work


async def test_a_settled_call_stays_settled_after_its_outbox_rows_are_pruned() -> None:
    """P6.7's coupling, and the reason the CRM probe moved off the outbox entirely.

    `_pipeline_settled` used to answer "was this call fanned out to the client's CRM" by
    containment-scanning `outbox_messages`, on the stated grounds that rows are never
    deleted from it. The nightly prune this release adds makes that premise false: past
    the floor, a published row is gone, and the old probe would have scored every call
    older than the floor as an unfinished pipeline — re-running extraction (a billed model
    round trip) and re-notifying the client, forever, on every tick.

    So the two halves of the fix are tested TOGETHER rather than apart. The call is driven
    to settled, every outbox row it produced is deleted, and the verdict must not move.
    """
    tenant_id, agent_ref, execution_id = await _staged("pruned")
    await pipeline.ingest_engine_event(
        {}, {"engine": "fake", "execution_id": execution_id, "engine_agent_ref": agent_ref}
    )
    state = await _artifacts(tenant_id, execution_id)
    await pipeline.run_post_call_pipeline(
        {},
        {
            "tenant_id": str(tenant_id),
            "call_id": str(state["call"]),
            "engine": "fake",
            "execution_id": execution_id,
        },
    )
    await _age(tenant_id, execution_id, minutes=18)
    snapshot = await get_engine().get_execution(execution_id)
    assert await pipeline._pipeline_settled("fake", snapshot) == "settled", "premise"

    # The prune, at its most destructive for THIS call: every outbox row that names it,
    # aged or not. Scoped by call id rather than `DELETE FROM outbox_messages`, which
    # would delete other suites' pending work on the shared database — the whole-database
    # mutation defect this repo has now found three times.
    async with untenanted_session() as session:
        deleted = rowcount_of(
            await session.execute(
                text(
                    "DELETE FROM outbox_messages WHERE payload::text LIKE :needle "
                    "OR dedupe_key LIKE :needle"
                ),
                {"needle": f"%{state['call']}%"},
            )
        )
    assert deleted > 0, "premise: this call's pipeline wrote outbox rows there were to prune"

    assert await pipeline._pipeline_settled("fake", snapshot) == "settled", (
        "the verdict followed the outbox rather than the call, so forgetting a delivered "
        "promise re-opened a finished call (P6.7)"
    )
