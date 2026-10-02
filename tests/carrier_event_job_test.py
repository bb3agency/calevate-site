"""`ingest_carrier_event`: a carrier callback becomes a status move and, on hangup, a CDR read.

The carrier itself is a fake behind the `CarrierClient` protocol: how a vendor's form fields
map to a `CarrierCallEvent` is the adapter's contract and has its own suite. What is under
test here is what the job does with a normalized event — tenant resolution through the
route table, the forward-only status rule, the CDR hand-off, the retry ladder for a call row
that does not exist yet, and closing the inbox row last.

Run: uv run python -m pytest -q tests/carrier_event_job_test.py
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine.carrier import CarrierCallEvent, CarrierCdr
from apps.workers import carrier_events
from apps.workers import settings as worker_settings
from apps.workers.carrier_events import (
    CDR_JOB,
    FINALISE_GRACE_S,
    FINALISE_JOB,
    ingest_carrier_event,
    orphan_status,
    statuses_behind,
)
from arq import Retry
from calevate_shared.carrier import CARRIER_EVENT_JOB
from sqlalchemy import text

pytestmark = [pytest.mark.rls]


@dataclass
class FakeCarrier:
    """A carrier whose callbacks are already normalized: `fields` names the outcome."""

    cdr: CarrierCdr | None = None
    fetch_error: Exception | None = None
    reads: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return "vobiz"

    def parse_event(self, fields: dict[str, str]) -> CarrierCallEvent | None:
        if "CallUUID" not in fields:
            return None
        return CarrierCallEvent(
            carrier="vobiz",
            carrier_call_id=fields["CallUUID"],
            kind=fields["kind"],  # type: ignore[arg-type]
            status=fields.get("status") or None,  # type: ignore[arg-type]
            raw_event=fields.get("Event", ""),
            hangup_cause=fields.get("HangupCause"),
        )

    async def fetch_cdr(self, carrier_call_id: str) -> CarrierCdr | None:
        self.reads.append(carrier_call_id)
        if self.fetch_error is not None:
            raise self.fetch_error
        return self.cdr


@dataclass
class Recorder:
    enqueued: list[tuple[str, dict[str, Any], str | None, dict[str, Any]]] = field(
        default_factory=list
    )
    alerts: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    inbox: list[tuple[str, str]] = field(default_factory=list)
    order: list[str] = field(default_factory=list)


def install_fake_carrier(monkeypatch: pytest.MonkeyPatch) -> FakeCarrier:
    fake = FakeCarrier()
    monkeypatch.setattr(carrier_events, "get_carrier", lambda name=None: fake)
    return fake


def install_recorder(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    rec = Recorder()

    async def _enqueue(job: str, payload: dict[str, Any], *, job_id: str | None = None, **kw: Any):
        rec.enqueued.append((job, payload, job_id, kw))
        rec.order.append(f"enqueue:{job}")
        return job_id

    async def _processed(session: Any, *, row_id: uuid.UUID) -> None:
        rec.inbox.append(("processed", str(row_id)))
        rec.order.append("inbox:processed")

    async def _failed(session: Any, *, row_id: uuid.UUID, error: str) -> None:
        rec.inbox.append(("failed", error))
        rec.order.append("inbox:failed")

    monkeypatch.setattr(carrier_events, "enqueue", _enqueue)
    monkeypatch.setattr(carrier_events, "mark_inbox_processed", _processed)
    monkeypatch.setattr(carrier_events, "mark_inbox_failed", _failed)
    monkeypatch.setattr(
        carrier_events,
        "alert",
        lambda stage, code, **kw: rec.alerts.append((stage, code, kw)),
    )
    return rec


@pytest.fixture
def carrier(monkeypatch: pytest.MonkeyPatch) -> FakeCarrier:
    return install_fake_carrier(monkeypatch)


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    return install_recorder(monkeypatch)


# ------------------------------------------------------------------ rows


async def make_tenant() -> tuple[uuid.UUID, uuid.UUID, str]:
    """A tenant, its agent, and the route a carrier callback resolves the tenant through."""
    created = await admin_service.create_organization(
        name="Carrier Clinic",
        slug=f"car-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = uuid.UUID(str(created["id"])), uuid.UUID(str(created["agent_id"]))
    ref = f"agent_car_{uuid.uuid4().hex[:10]}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET status = 'live', engine_agent_ref = :r WHERE id = :a"),
            {"r": ref, "a": agent_id},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES (:e, :r, :t, :a, true, now(), now())"
            ),
            {"e": get_settings().engine, "r": ref, "t": tenant_id, "a": agent_id},
        )
    return tenant_id, agent_id, ref


async def make_call(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    status: str = "queued",
    direction: str = "outbound",
    carrier_call_id: str | None = None,
) -> uuid.UUID:
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, carrier_call_id, "
                "direction, status, created_at, updated_at) VALUES (:i, :t, :a, :e, :c, :d, :s, "
                "now(), now())"
            ),
            {
                "i": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": f"exec_{uuid.uuid4().hex[:12]}",
                "c": carrier_call_id,
                "d": direction,
                "s": status,
            },
        )
    return call_id


async def call_state(tenant_id: uuid.UUID, call_id: uuid.UUID) -> tuple[str, Any, str | None]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT status, ended_at, carrier_call_id FROM calls WHERE id = :i"),
                {"i": call_id},
            )
        ).one()
    return str(row[0]), row[1], row[2]


async def call_carrier(tenant_id: uuid.UUID, call_id: uuid.UUID) -> str | None:
    async with tenant_session(tenant_id) as session:
        return (
            await session.execute(text("SELECT carrier FROM calls WHERE id = :i"), {"i": call_id})
        ).scalar_one()


async def calls_with_carrier_id(tenant_id: uuid.UUID, ccid: str) -> list[tuple[Any, ...]]:
    async with tenant_session(tenant_id) as session:
        return [
            tuple(r)
            for r in (
                await session.execute(
                    text(
                        "SELECT id, agent_id, engine_call_id, direction, status, ended_at, "
                        "carrier FROM calls WHERE carrier_call_id = :c"
                    ),
                    {"c": ccid},
                )
            ).all()
        ]


def payload(
    ref: str,
    ccid: str,
    kind: str,
    status: str | None,
    *,
    call_id: uuid.UUID | None = None,
    inbox_row_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    fields = {"CallUUID": ccid, "kind": kind, "Event": kind}
    if status:
        fields["status"] = status
    return {
        "carrier": "vobiz",
        "carrier_call_id": ccid,
        "event": kind,
        "engine_agent_ref": ref,
        "call_id": str(call_id) if call_id else None,
        "inbox_row_id": str(inbox_row_id) if inbox_row_id else None,
        "fields": fields,
    }


# ------------------------------------------------------------------ wiring


def test_the_job_answers_to_the_name_voice_runtime_enqueues() -> None:
    assert ingest_carrier_event.__name__ == CARRIER_EVENT_JOB
    names = {getattr(fn, "__name__", "") for fn in worker_settings.FUNCTIONS}
    assert {CARRIER_EVENT_JOB, CDR_JOB, FINALISE_JOB} <= names
    assert "cron:reconcile_carrier_cdrs" in worker_settings.WALK_SHAPES


def test_statuses_only_move_forward() -> None:
    assert statuses_behind("ringing") == ["queued"]
    assert statuses_behind("in_progress") == ["queued", "ringing"]
    assert set(statuses_behind("completed")) == {"queued", "ringing", "in_progress"}
    assert statuses_behind("queued") == []


# ------------------------------------------------------------------ mapping per kind


@pytest.mark.parametrize(
    ("kind", "status", "expected", "cdr"),
    [
        ("ringing", "ringing", "ringing", False),
        ("answered", "in_progress", "in_progress", False),
        ("hangup", "completed", "completed", True),
        ("hangup", "busy", "busy", True),
        ("machine", "voicemail", "voicemail", False),
        ("stream", None, "queued", False),
        ("other", None, "queued", False),
    ],
)
async def test_each_kind_moves_the_outbound_call_it_names(
    carrier: FakeCarrier, seen: Recorder, kind: str, status: str | None, expected: str, cdr: bool
) -> None:
    tenant_id, agent_id, ref = await make_tenant()
    call_id = await make_call(tenant_id, agent_id)
    ccid = f"cuuid-{uuid.uuid4().hex}"

    outcome = await ingest_carrier_event(
        {"job_try": 1}, payload(ref, ccid, kind, status, call_id=call_id)
    )

    got, ended_at, stored_ccid = await call_state(tenant_id, call_id)
    assert got == expected
    assert outcome.startswith(kind)
    # The outbound row learns the carrier's id from its first callback.
    assert stored_ccid == ccid
    assert (ended_at is not None) == (expected in {"completed", "busy", "voicemail"})
    cdr_jobs = [e for e in seen.enqueued if e[0] == CDR_JOB]
    if cdr:
        assert len(cdr_jobs) == 1
        _job, body, job_id, kw = cdr_jobs[0]
        assert body == {
            "carrier": "vobiz",
            "carrier_call_id": ccid,
            "tenant_id": str(tenant_id),
            "call_id": str(call_id),
        }
        assert job_id == f"{CDR_JOB}:vobiz:{ccid}"
        assert kw["_defer_by"] == carrier_events.CDR_FIRST_READ_DELAY_S
    else:
        assert cdr_jobs == []
    # Only an answered call owes a worker settlement; a busy dial never reached a worker.
    finalise_jobs = [e for e in seen.enqueued if e[0] == FINALISE_JOB]
    assert len(finalise_jobs) == (1 if (kind, status) == ("hangup", "completed") else 0)
    # Every matched callback stamps the carrier it came from onto a row that had none.
    assert await call_carrier(tenant_id, call_id) == "vobiz"
    assert seen.alerts == []


async def test_an_answered_hangup_defers_the_settlement_backstop_once_per_call(
    carrier: FakeCarrier, seen: Recorder
) -> None:
    tenant_id, agent_id, ref = await make_tenant()
    ccid = f"cuuid-{uuid.uuid4().hex}"
    call_id = await make_call(
        tenant_id, agent_id, status="in_progress", direction="inbound", carrier_call_id=ccid
    )

    # A carrier that calls the end of a live call `failed` still owes the backstop: the
    # row says a worker held it.
    await ingest_carrier_event({"job_try": 1}, payload(ref, ccid, "hangup", "failed"))

    [(_job, body, job_id, kw)] = [e for e in seen.enqueued if e[0] == FINALISE_JOB]
    assert body == {"tenant_id": str(tenant_id), "call_id": str(call_id)}
    assert job_id == f"{FINALISE_JOB}:{call_id}"
    assert kw == {"_defer_by": FINALISE_GRACE_S}


async def test_a_hangup_after_the_settlement_owes_no_backstop(
    carrier: FakeCarrier, seen: Recorder
) -> None:
    tenant_id, agent_id, ref = await make_tenant()
    ccid = f"cuuid-{uuid.uuid4().hex}"
    await make_call(
        tenant_id, agent_id, status="completed", direction="inbound", carrier_call_id=ccid
    )

    await ingest_carrier_event({"job_try": 1}, payload(ref, ccid, "hangup", "completed"))

    assert [e for e in seen.enqueued if e[0] == FINALISE_JOB] == []
    assert len([e for e in seen.enqueued if e[0] == CDR_JOB]) == 1


async def test_a_stored_carrier_is_kept_and_read_from(carrier: FakeCarrier, seen: Recorder) -> None:
    """The CDR read goes to the carrier on the row, not to the one the callback names."""
    tenant_id, agent_id, ref = await make_tenant()
    call_id = await make_call(tenant_id, agent_id, status="in_progress")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET carrier = 'plivo' WHERE id = :i"), {"i": call_id}
        )
    ccid = f"cuuid-{uuid.uuid4().hex}"

    await ingest_carrier_event(
        {"job_try": 1}, payload(ref, ccid, "hangup", "completed", call_id=call_id)
    )

    assert await call_carrier(tenant_id, call_id) == "plivo"
    [(_job, body, job_id, _kw)] = [e for e in seen.enqueued if e[0] == CDR_JOB]
    assert body["carrier"] == "plivo" and job_id == f"{CDR_JOB}:plivo:{ccid}"


async def test_an_inbound_call_is_found_by_the_carrier_id_the_worker_stored(
    carrier: FakeCarrier, seen: Recorder
) -> None:
    tenant_id, agent_id, ref = await make_tenant()
    ccid = f"cuuid-{uuid.uuid4().hex}"
    call_id = await make_call(
        tenant_id, agent_id, status="in_progress", direction="inbound", carrier_call_id=ccid
    )

    await ingest_carrier_event({"job_try": 1}, payload(ref, ccid, "hangup", "completed"))

    assert (await call_state(tenant_id, call_id))[0] == "completed"
    assert [e[1]["call_id"] for e in seen.enqueued if e[0] == CDR_JOB] == [str(call_id)]


# ------------------------------------------------------------------ monotonicity, dedupe


@pytest.mark.parametrize(
    ("current", "late_kind", "late_status"),
    [
        ("completed", "ringing", "ringing"),
        ("in_progress", "ringing", "ringing"),
        # The worker's own terminal verdict stands: the carrier is the authority on the
        # minute, not on how the conversation ended.
        ("failed", "hangup", "completed"),
    ],
)
async def test_a_late_event_never_moves_a_call_backwards(
    carrier: FakeCarrier, seen: Recorder, current: str, late_kind: str, late_status: str
) -> None:
    tenant_id, agent_id, ref = await make_tenant()
    call_id = await make_call(tenant_id, agent_id, status=current)

    outcome = await ingest_carrier_event(
        {"job_try": 1}, payload(ref, "cuuid-late", late_kind, late_status, call_id=call_id)
    )

    assert (await call_state(tenant_id, call_id))[0] == current
    assert ":unchanged" in outcome


async def test_the_same_callback_twice_has_one_effect(carrier: FakeCarrier, seen: Recorder) -> None:
    tenant_id, agent_id, ref = await make_tenant()
    call_id = await make_call(tenant_id, agent_id, status="in_progress")
    body = payload(ref, f"cuuid-{uuid.uuid4().hex}", "hangup", "completed", call_id=call_id)

    first = await ingest_carrier_event({"job_try": 1}, body)
    _, ended_first, _ = await call_state(tenant_id, call_id)
    second = await ingest_carrier_event({"job_try": 1}, body)
    status, ended_second, _ = await call_state(tenant_id, call_id)

    assert first == "hangup:advanced:cdr_enqueued"
    assert second == "hangup:unchanged:cdr_enqueued"
    assert status == "completed" and ended_first == ended_second
    # Both CDR enqueues carry ONE job id, which arq collapses into one read.
    assert len({e[2] for e in seen.enqueued if e[0] == CDR_JOB}) == 1


# ------------------------------------------------------------------ unresolved calls


async def test_an_inbound_hangup_no_worker_recorded_gets_its_row_on_the_last_attempt(
    carrier: FakeCarrier, seen: Recorder
) -> None:
    tenant_id, agent_id, ref = await make_tenant()
    ccid = f"cuuid-{uuid.uuid4().hex}"
    inbox = uuid.uuid4()
    body = payload(ref, ccid, "hangup", "completed", inbox_row_id=inbox)

    for attempt in (1, 2):
        with pytest.raises(Retry):
            await ingest_carrier_event({"job_try": attempt}, body)
    assert await calls_with_carrier_id(tenant_id, ccid) == []
    outcome = await ingest_carrier_event({"job_try": 3}, body)

    assert outcome == "hangup:created:cdr_enqueued"
    [(call_id, row_agent, engine_call_id, direction, status, ended_at, row_carrier)] = (
        await calls_with_carrier_id(tenant_id, ccid)
    )
    assert row_agent == agent_id and direction == "inbound"
    assert engine_call_id == f"pipecat:{tenant_id}:{call_id}"
    # Never `completed`: no worker served it, so no client minute may be billed for it.
    assert status == "failed" and ended_at is not None and row_carrier == "vobiz"
    [(_job, cdr_body, _job_id, _kw)] = [e for e in seen.enqueued if e[0] == CDR_JOB]
    assert cdr_body["call_id"] == str(call_id) and cdr_body["carrier_call_id"] == ccid
    assert [e for e in seen.enqueued if e[0] == FINALISE_JOB] == []
    assert [a[1] for a in seen.alerts] == ["inbound_call_never_reached_worker"]
    assert seen.alerts[0][2]["tenant_id"] == str(tenant_id)
    assert seen.inbox[-1] == ("processed", str(inbox))


async def test_a_redelivered_orphan_hangup_writes_one_row(
    carrier: FakeCarrier, seen: Recorder
) -> None:
    tenant_id, _agent_id, ref = await make_tenant()
    ccid = f"cuuid-{uuid.uuid4().hex}"
    body = payload(ref, ccid, "hangup", "no_answer")

    first = await ingest_carrier_event({"job_try": 3}, body)
    second = await ingest_carrier_event({"job_try": 3}, body)

    assert first == "hangup:created:cdr_enqueued"
    assert second.startswith("hangup:unchanged")
    [row] = await calls_with_carrier_id(tenant_id, ccid)
    assert row[4] == "no_answer"
    assert [a[1] for a in seen.alerts] == ["inbound_call_never_reached_worker"]
    # Both reads collapse into one queued job.
    assert len({e[2] for e in seen.enqueued if e[0] == CDR_JOB}) == 1


def test_an_orphan_row_never_records_a_completed_call() -> None:
    assert orphan_status("completed") == "failed"
    assert orphan_status(None) == "failed"
    assert orphan_status("in_progress") == "failed"
    assert orphan_status("busy") == "busy"
    assert orphan_status("no_answer") == "no_answer"


async def test_an_unknown_inbound_ring_is_parked_quietly(
    carrier: FakeCarrier, seen: Recorder
) -> None:
    _tenant_id, _agent_id, ref = await make_tenant()
    outcome = await ingest_carrier_event(
        {"job_try": 3}, payload(ref, f"cuuid-{uuid.uuid4().hex}", "ringing", "ringing")
    )
    assert outcome == "unresolved"
    assert seen.alerts == []


async def test_another_tenants_call_id_is_never_resolved(
    carrier: FakeCarrier, seen: Recorder
) -> None:
    """Hard rule 1: the tenant comes from the route; a call id from the payload is read
    under that tenant's RLS, so another tenant's call is simply not there."""
    _tenant_a, _agent_a, ref_a = await make_tenant()
    tenant_b, agent_b, _ref_b = await make_tenant()
    foreign = await make_call(tenant_b, agent_b, status="in_progress")

    outcome = await ingest_carrier_event(
        {"job_try": 3}, payload(ref_a, "cuuid-x", "hangup", "completed", call_id=foreign)
    )

    assert outcome == "unresolved"
    assert (await call_state(tenant_b, foreign))[0] == "in_progress"
    assert [a[1] for a in seen.alerts] == ["carrier_event_call_unresolved"]


async def test_a_call_of_another_agent_is_refused(carrier: FakeCarrier, seen: Recorder) -> None:
    tenant_id, agent_id, ref = await make_tenant()
    other_agent = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO agents (id, tenant_id, name, direction, status, disclosure_line, "
                "ai_disclosure_line, recording_notice_line, caller_memory_notice_line, "
                "created_at, updated_at) SELECT :n, tenant_id, 'Second agent', direction, "
                "status, disclosure_line, ai_disclosure_line, recording_notice_line, "
                "caller_memory_notice_line, now(), now() FROM agents WHERE id = :a"
            ),
            {"n": other_agent, "a": agent_id},
        )
    call_id = await make_call(tenant_id, other_agent, status="in_progress")

    outcome = await ingest_carrier_event(
        {"job_try": 1}, payload(ref, "cuuid-y", "hangup", "completed", call_id=call_id)
    )

    assert outcome == "call_mismatch"
    assert (await call_state(tenant_id, call_id))[0] == "in_progress"
    assert [a[1] for a in seen.alerts] == ["carrier_event_call_mismatch"]


async def test_an_unmapped_agent_ref_alarms_and_invents_nothing(
    carrier: FakeCarrier, seen: Recorder
) -> None:
    outcome = await ingest_carrier_event(
        {"job_try": 1}, payload(f"nobody_{uuid.uuid4().hex}", "cuuid-z", "hangup", "completed")
    )
    assert outcome == "unmapped"
    assert [a[1] for a in seen.alerts] == ["engine_agent_unmapped"]


# ------------------------------------------------------------------ failure policy, inbox


async def test_the_inbox_row_is_closed_after_the_cdr_read_is_queued(
    carrier: FakeCarrier, seen: Recorder
) -> None:
    tenant_id, agent_id, ref = await make_tenant()
    call_id = await make_call(tenant_id, agent_id, status="in_progress")
    inbox = uuid.uuid4()

    await ingest_carrier_event(
        {"job_try": 1},
        payload(ref, "cuuid-ib", "hangup", "completed", call_id=call_id, inbox_row_id=inbox),
    )

    assert seen.order == [f"enqueue:{CDR_JOB}", f"enqueue:{FINALISE_JOB}", "inbox:processed"]
    assert seen.inbox == [("processed", str(inbox))]


async def test_a_callback_naming_no_call_is_closed(carrier: FakeCarrier, seen: Recorder) -> None:
    inbox = uuid.uuid4()
    body = payload("r", "c", "other", None, inbox_row_id=inbox)
    body["fields"] = {"Event": "Heartbeat"}
    assert await ingest_carrier_event({"job_try": 1}, body) == "no_call_named"
    assert seen.inbox == [("processed", str(inbox))]


async def test_a_malformed_payload_is_permanent_and_loud(seen: Recorder) -> None:
    with pytest.raises(ProblemError):
        await ingest_carrier_event({"job_try": 1}, {"carrier": "nobody", "fields": {}})
    assert [a[1] for a in seen.alerts] == ["carrier_event_ingest_abandoned"]


async def test_a_transient_fault_takes_the_ladder_then_alarms(
    monkeypatch: pytest.MonkeyPatch, seen: Recorder
) -> None:
    class _Flaky(FakeCarrier):
        def parse_event(self, fields: dict[str, str]) -> CarrierCallEvent | None:
            raise ConnectionError("database blip")

    monkeypatch.setattr(carrier_events, "get_carrier", lambda name=None: _Flaky())
    inbox = uuid.uuid4()
    body = payload("r", "c", "hangup", "completed", inbox_row_id=inbox)

    with pytest.raises(Retry):
        await ingest_carrier_event({"job_try": 1}, body)
    assert seen.inbox == [("failed", "ConnectionError")]
    assert seen.alerts == []
    with pytest.raises(ConnectionError):
        await ingest_carrier_event({"job_try": 3}, body)
    assert [a[1] for a in seen.alerts] == ["carrier_event_ingest_abandoned"]
