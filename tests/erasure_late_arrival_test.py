"""An erasure that completed while a call was still in flight (D-310).

THE SEQUENCE, and nothing in it is adversarial. A caller is on the phone. Somebody at
the clinic files that caller's DPDP §12 erasure — the moment people actually ask is the
moment they are talking to the business. `execute_deletion_request` runs: the only thing
that exists for the live call is the `calls` row, so it clears the numbers, writes the
proof, and the client hands over a certificate. The call then ends and the ORDINARY
post-call pipeline writes the transcript verbatim, the summary, the extraction, the
recording pointer, the archived vendor document and a `leads` row carrying the number
the certificate says is gone. No replay, no poller, no attacker: two concurrent
processes, one of which had no way to reach forward.

What is asserted here:

1. the late records really do arrive — the failure is real, not theoretical;
2. the pipeline FILES A FRESH ERASURE for that subject, with its outbox job, in the same
   transaction as its own writes;
3. running that erasure destroys the late records — transcript, summary and the lead's
   number — so the standing instruction is honoured end to end;
4. a call the same person places AFTER the erasure completed is NOT re-erased. Erasure is
   not a terminal state for a phone number (`compliance/deletion.py`), and a rule that
   swallowed later calls would destroy records the person's own next call created.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.compliance.deletion import DELETION_JOB, request_erasure
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import reset_engine_cache
from apps.api.engine.fake import FakeEngine
from apps.workers.pipeline import ingest_engine_event, run_post_call_pipeline
from apps.workers.retention import ANONYMIZED_PHONE, REDACTED_MARK, execute_deletion_request
from calevate_shared.engine import ExecutionSnapshot
from calevate_shared.events import TranscriptTurn
from sqlalchemy import text
from tests.campaigns_test import _ready_campaign

CALLER_LINE = "naa peru Ravi"


def _snapshot(execution_id: str, agent_ref: str, to_e164: str) -> ExecutionSnapshot:
    now = datetime.now(UTC)
    return ExecutionSnapshot(
        engine_call_id=execution_id,
        engine_agent_ref=agent_ref,
        direction="outbound",
        status="completed",
        raw_status="completed",
        terminal=True,
        billable_ready=True,
        started_at=now - timedelta(seconds=60),
        ended_at=now,
        duration_s=60,
        from_e164="+911140000000",
        to_e164=to_e164,
        recording_url=None,
        transcript=[
            TranscriptTurn(call_id=execution_id, idx=0, speaker="caller", text=CALLER_LINE),  # type: ignore[arg-type]
            TranscriptTurn(call_id=execution_id, idx=1, speaker="agent", text="dhanyavaadalu"),  # type: ignore[arg-type]
        ],
        cost=None,
        engine="fake",
    )


async def _agent_ref(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> str:
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT engine_agent_ref FROM engine_agent_routes "
                    "WHERE tenant_id = :t AND agent_id = :a AND active"
                ),
                {"t": tenant_id, "a": agent_id},
            )
        ).first()
    assert row is not None, "the campaign fixture publishes a route for its agent"
    return str(row[0])


async def _call_in_flight(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, *, execution_id: str, phone: str
) -> uuid.UUID:
    """The row `dispatch_call` commits before the phone rings, or an inbound `ringing`."""
    call_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "from_e164, to_e164, started_at, created_at, updated_at) "
                "VALUES (:id, :t, :a, :e, 'outbound', 'in_progress', '+911140000000', :phone, "
                "now(), now(), now())"
            ),
            {"id": call_id, "t": tenant_id, "a": agent_id, "e": execution_id, "phone": phone},
        )
    return call_id


async def _erase(tenant_id: uuid.UUID, phone: str) -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        made = await request_erasure(session, tenant_id=tenant_id, phone_e164=phone)
    await execute_deletion_request({}, {"tenant_id": str(tenant_id), "request_id": str(made.id)})
    return made.id


async def _run_pipeline(tenant_id: uuid.UUID, call_id: uuid.UUID, execution_id: str) -> None:
    await ingest_engine_event({}, {"engine": "fake", "execution_id": execution_id})
    await run_post_call_pipeline(
        {},
        {
            "tenant_id": str(tenant_id),
            "call_id": str(call_id),
            "engine": "fake",
            "execution_id": execution_id,
        },
    )


async def _open_requests(tenant_id: uuid.UUID) -> list[uuid.UUID]:
    async with tenant_session(tenant_id) as session:
        return [
            row[0]
            for row in (
                await session.execute(
                    text(
                        "SELECT id FROM deletion_requests WHERE completed_at IS NULL "
                        "ORDER BY requested_at"
                    )
                )
            ).all()
        ]


async def _queued_jobs(request_id: uuid.UUID) -> int:
    """The outbox row that makes the re-filed request an execution rather than a note."""
    async with untenanted_session() as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM outbox_messages WHERE job = :job "
                        "AND payload->>'request_id' = :rid"
                    ),
                    {"job": DELETION_JOB, "rid": str(request_id)},
                )
            ).scalar()
            or 0
        )


async def _records(tenant_id: uuid.UUID, call_id: uuid.UUID, phone: str) -> dict[str, object]:
    async with tenant_session(tenant_id) as session:
        turns = (
            (
                await session.execute(
                    text("SELECT text FROM transcript_turns WHERE call_id = :c ORDER BY idx"),
                    {"c": call_id},
                )
            )
            .scalars()
            .all()
        )
        summary = (
            await session.execute(text("SELECT summary FROM calls WHERE id = :c"), {"c": call_id})
        ).scalar()
        leads = (
            (
                await session.execute(
                    text("SELECT phone_e164 FROM leads WHERE phone_e164 = :p"), {"p": phone}
                )
            )
            .scalars()
            .all()
        )
    return {"turns": list(turns), "summary": summary, "leads": list(leads)}


async def test_records_arriving_after_the_certificate_are_erased_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Red without D-310's re-file: the transcript, the summary and the lead's number
    all come back and stay back, under a certificate that says they are gone."""
    reset_engine_cache()
    subject = f"+9198765{uuid.uuid4().int % 100000:05d}"
    tenant_id, agent_id, _campaign = await _ready_campaign(phones=("9000000001",))
    ref = await _agent_ref(tenant_id, agent_id)
    execution_id = f"exec_{uuid.uuid4().hex[:12]}"

    async def _get(self: FakeEngine, call_id: str) -> ExecutionSnapshot:
        return _snapshot(execution_id, ref, subject)

    monkeypatch.setattr(FakeEngine, "get_execution", _get)

    call_id = await _call_in_flight(tenant_id, agent_id, execution_id=execution_id, phone=subject)
    first = await _erase(tenant_id, subject)
    assert await _open_requests(tenant_id) == [], "the first erasure completed"

    await _run_pipeline(tenant_id, call_id, execution_id)

    # 1 — the records really did come back. If this ever stops being true the rest of
    # this test is proving nothing, which is why it is asserted rather than assumed.
    landed = await _records(tenant_id, call_id, subject)
    assert CALLER_LINE in landed["turns"], landed  # type: ignore[operator]

    # 2 — the pipeline filed a fresh request for the same subject, with its job.
    refiled = await _open_requests(tenant_id)
    assert len(refiled) == 1, f"expected one re-filed erasure, got {refiled}"
    assert refiled[0] != first
    assert await _queued_jobs(refiled[0]) == 1

    # 3 — running it destroys what the late run wrote.
    await execute_deletion_request({}, {"tenant_id": str(tenant_id), "request_id": str(refiled[0])})
    after = await _records(tenant_id, call_id, subject)
    assert after["turns"] == [REDACTED_MARK, REDACTED_MARK], after
    assert after["summary"] is None, after
    assert after["leads"] == [], after
    async with tenant_session(tenant_id) as session:
        anonymized = (
            await session.execute(
                text("SELECT count(*) FROM leads WHERE phone_e164 LIKE :p"),
                {"p": f"{ANONYMIZED_PHONE[:9]}%"},
            )
        ).scalar()
    assert int(anonymized or 0) >= 1, "the lead the late pipeline created was anonymized"


async def test_a_later_call_from_the_same_person_is_not_re_erased(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half of the rule, and the one a careless fix breaks. Erasure is not a
    terminal state for a number: a call the person places AFTER their erasure completed
    is lawfully collected new data, and re-filing on it would destroy records nobody
    asked us to destroy."""
    reset_engine_cache()
    subject = f"+9198765{uuid.uuid4().int % 100000:05d}"
    tenant_id, agent_id, _campaign = await _ready_campaign(phones=("9000000002",))
    ref = await _agent_ref(tenant_id, agent_id)

    await _erase(tenant_id, subject)

    execution_id = f"exec_{uuid.uuid4().hex[:12]}"

    async def _get(self: FakeEngine, call_id: str) -> ExecutionSnapshot:
        return _snapshot(execution_id, ref, subject)

    monkeypatch.setattr(FakeEngine, "get_execution", _get)

    # Started AFTER the erasure completed — the person rang back.
    call_id = await _call_in_flight(tenant_id, agent_id, execution_id=execution_id, phone=subject)
    await _run_pipeline(tenant_id, call_id, execution_id)

    assert await _open_requests(tenant_id) == [], "a later call must not re-file an erasure"
    landed = await _records(tenant_id, call_id, subject)
    assert CALLER_LINE in landed["turns"], landed  # type: ignore[operator]
