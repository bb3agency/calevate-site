"""How a handover ENDS, and what happens when nobody took the call (D-533).

Decision 3 of the founder's brief was "try the next number, then a call-back". The first
half is not available on this engine — it latches after one handover and answers every
later attempt with "Call transfer already in progress" (VERIFIED-OSS:
`bolna-ai/bolna@cd2e192`, `bolna/agent_manager/task_manager.py:3116-3126`) — so the hunt
list is honoured by CHOOSING before the call and the miss is caught after it, here. These
tests are about the half that ships, and about the two ways it must not misfire:

* it must not overwrite a call-back the CALLER asked for out loud, and
* it must not ring somebody at half past nine at night because the handover failed then.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from apps.api.admin import service as admin_service
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine import reset_engine_cache
from apps.workers.handoff import settle_handoff
from calevate_shared.calling_window import DEFAULT_WINDOW, IST
from calevate_shared.engine import ExecutionSnapshot, HandoffLeg
from sqlalchemy import text
from tests.conftest import accept_agreements

pytestmark = pytest.mark.asyncio


async def _fixture() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, str]:
    """An organisation, an agent, a `calls` row and a handover already at `started`."""
    reset_engine_cache()
    created = await admin_service.create_organization(
        name="Handoff settle",
        slug=f"handoff-set-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    agent_id = uuid.UUID(str(created["agent_id"]))
    await accept_agreements(tenant_id)
    execution_id = f"exec-{uuid.uuid4().hex[:10]}"
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                "  status, from_e164, to_e164) "
                "VALUES (:id, :tid, :aid, :ecid, 'inbound', 'completed', "
                "  '+919000005555', '+911160000001')"
            ),
            {"id": call_id, "tid": tenant_id, "aid": agent_id, "ecid": execution_id},
        )
        await session.execute(
            text(
                "INSERT INTO handoff_attempts (id, tenant_id, agent_id, source_execution_id, "
                "  destination_e164, started_at) "
                "VALUES (:id, :tid, :aid, :ex, '+919000000777', :now)"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "aid": agent_id,
                "ex": execution_id,
                "now": datetime.now(UTC),
            },
        )
    return tenant_id, agent_id, call_id, execution_id


def _snapshot(execution_id: str, leg: HandoffLeg | None) -> ExecutionSnapshot:
    return ExecutionSnapshot(
        engine_call_id=execution_id,
        direction="inbound",
        status="completed",
        raw_status="completed",
        terminal=True,
        billable_ready=True,
        from_e164="+919000005555",
        to_e164="+911160000001",
        handoff=leg,
    )


async def test_a_handover_nobody_took_books_the_caller_a_call_back() -> None:
    """The only failover this engine leaves available, and the whole of decision 3 that
    ships. The call-back is booked at the soonest LAWFUL time — never simply "now", because
    a handover that fails at 21:30 must not ring anybody at 21:31."""
    tenant_id, _agent_id, call_id, execution_id = await _fixture()
    snapshot = _snapshot(
        execution_id,
        HandoffLeg(outcome="unreached", raw_status="no-answer", duration_s=None),
    )
    async with tenant_session(tenant_id) as session:
        outcome = await settle_handoff(
            session, tenant_id=tenant_id, call_id=call_id, snapshot=snapshot
        )
        row = (
            await session.execute(
                text(
                    "SELECT h.outcome, h.raw_status, h.settled_at, h.callback_id, "
                    "  c.requested_at, c.phone_e164, c.status "
                    "FROM handoff_attempts h "
                    "JOIN scheduled_callbacks c ON c.id = h.callback_id "
                    "WHERE h.source_execution_id = :ex"
                ),
                {"ex": execution_id},
            )
        ).first()
    assert outcome == "unreached"
    assert row is not None
    assert row[0] == "unreached"
    assert row[1] == "no-answer", "the vendor's own word is kept for the operator"
    assert row[2] is not None, "a settled row names its ending"
    assert row[5] == "+919000005555", "the CALLER is rung back, never our own header"
    assert row[6] == "scheduled"
    # THE LAWFUL-TIME RULE, asserted as the property rather than as a clock: whatever hour
    # this suite runs at, the promised instant is inside the calling window.
    requested_ist = row[4].astimezone(UTC) + IST
    start, end = DEFAULT_WINDOW
    assert start <= requested_ist.time() < end, (
        "a call-back was booked outside the calling window (TCCCPR; SEC-COMP §3)"
    )


async def test_a_call_back_the_caller_asked_for_out_loud_is_not_overwritten() -> None:
    """`callbacks.book` upserts on the execution and takes the LATER `booked_at`, so an
    unconditional booking here would silently move a time a caller was TOLD ("Tuesday at
    four") to twenty minutes from now. A promise a person heard beats one this system
    inferred."""
    tenant_id, agent_id, call_id, execution_id = await _fixture()
    promised = datetime(2026, 12, 8, 10, 30, tzinfo=UTC)  # 16:00 IST
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO scheduled_callbacks (id, tenant_id, agent_id, "
                "  source_execution_id, phone_e164, requested_at, booked_at) "
                "VALUES (:id, :tid, :aid, :ex, '+919000005555', :at, :at)"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "aid": agent_id,
                "ex": execution_id,
                "at": promised,
            },
        )
        await settle_handoff(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            snapshot=_snapshot(
                execution_id, HandoffLeg(outcome="unreached", raw_status="busy")
            ),
        )
        row = (
            await session.execute(
                text(
                    "SELECT requested_at FROM scheduled_callbacks WHERE source_execution_id = :ex"
                ),
                {"ex": execution_id},
            )
        ).first()
    assert row is not None
    assert row[0] == promised, "the time the caller was told out loud was moved"


async def test_a_handover_that_connected_books_nothing() -> None:
    tenant_id, _agent_id, call_id, execution_id = await _fixture()
    async with tenant_session(tenant_id) as session:
        outcome = await settle_handoff(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            snapshot=_snapshot(
                execution_id,
                HandoffLeg(
                    outcome="connected",
                    raw_status="completed",
                    duration_s=142,
                    recording_present=True,
                    cost_reported=True,
                ),
            ),
        )
        row = (
            await session.execute(
                text(
                    "SELECT outcome, leg_duration_s, leg_recording_present, "
                    "  leg_cost_reported, callback_id FROM handoff_attempts "
                    "WHERE source_execution_id = :ex"
                ),
                {"ex": execution_id},
            )
        ).first()
    assert outcome == "connected"
    assert row is not None
    assert row[0] == "connected" and row[1] == 142
    # THE SECOND RECORDING IS RECORDED AS EXISTING. It is not copied, not retained under our
    # policy and not reached by a DPDP erasure (OPERATIONS §2 gate 46b) — so the one thing
    # this system can honestly do is know that it is there.
    assert row[2] is True
    assert row[3] is True
    assert row[4] is None, "nobody needs ringing back; somebody took the call"


async def test_a_handover_the_platform_never_reported_placing_does_not_sit_at_started() -> None:
    """The agent told the caller it was putting them through and no transfer leg was ever
    reported. `abandoned` rather than `started`, because a row that claims to be in progress
    forever is worse than one that says plainly we do not know what happened."""
    tenant_id, _agent_id, call_id, execution_id = await _fixture()
    async with tenant_session(tenant_id) as session:
        outcome = await settle_handoff(
            session, tenant_id=tenant_id, call_id=call_id, snapshot=_snapshot(execution_id, None)
        )
        row = (
            await session.execute(
                text(
                    "SELECT outcome, settled_at, source_call_id FROM handoff_attempts "
                    "WHERE source_execution_id = :ex"
                ),
                {"ex": execution_id},
            )
        ).first()
    assert outcome == "abandoned"
    assert row is not None and row[0] == "abandoned" and row[1] is not None
    assert row[2] == call_id, "the pointer to the call is filled in once there is one"


async def test_settling_twice_does_not_reopen_an_ending_or_book_a_second_call_back() -> None:
    """The pipeline is driven by both the webhook and the poller, so it runs more than
    once. Idempotent BY PREDICATE — only a row still at `started` is settled — rather than
    by a flag somebody has to remember to check."""
    tenant_id, _agent_id, call_id, execution_id = await _fixture()
    leg = HandoffLeg(outcome="unreached", raw_status="no-answer")
    async with tenant_session(tenant_id) as session:
        first = await settle_handoff(
            session, tenant_id=tenant_id, call_id=call_id, snapshot=_snapshot(execution_id, leg)
        )
        second = await settle_handoff(
            session, tenant_id=tenant_id, call_id=call_id, snapshot=_snapshot(execution_id, leg)
        )
        count = (
            await session.execute(
                text(
                    "SELECT count(*) FROM scheduled_callbacks WHERE source_execution_id = :ex"
                ),
                {"ex": execution_id},
            )
        ).scalar()
    assert first == "unreached"
    assert second == "no_row", "a settled handover was settled again"
    assert count == 1


async def test_a_call_with_no_handover_costs_one_lookup_and_nothing_else() -> None:
    """This runs on EVERY completed call, so the ordinary answer has to be cheap and
    silent."""
    tenant_id, _agent_id, call_id, execution_id = await _fixture()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("DELETE FROM handoff_attempts WHERE source_execution_id = :ex"),
            {"ex": execution_id},
        )
        outcome = await settle_handoff(
            session, tenant_id=tenant_id, call_id=call_id, snapshot=_snapshot(execution_id, None)
        )
    assert outcome == "no_row"
