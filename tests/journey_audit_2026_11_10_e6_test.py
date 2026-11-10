"""Journey audit E6 (10 Nov 2026): concurrency and failure.

Each test forces one interleaving between two writers, or a failure between two commits,
and asserts the outcome the code promises.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.callbacks import service as callbacks
from apps.api.compliance.deletion import request_erasure
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.workers import callbacks as callbacks_worker
from apps.workers.callbacks import dispatch_due_callbacks
from apps.workers.retention import execute_deletion_request
from calevate_shared.engine import CallContext
from sqlalchemy import text
from tests.callback_campaign_hold_test import CALLER as HOLD_CALLER
from tests.callback_campaign_hold_test import OTHER, _campaign, _set_status
from tests.callback_campaign_hold_test import _book as book_on_campaign
from tests.callback_dispatch_test import (  # noqa: F401 - autouse fixtures
    CALLER,
    _book,
    _daytime,
    _dialable_tenant,
    _fake_engine,
    _row,
)

pytestmark = pytest.mark.anyio


async def _erase(tenant_id: uuid.UUID, phone: str) -> None:
    async with tenant_session(tenant_id) as session:
        record = await request_erasure(session, tenant_id=tenant_id, phone_e164=phone)
    await execute_deletion_request({}, {"tenant_id": str(tenant_id), "request_id": str(record.id)})


async def test_an_erasure_after_a_call_back_was_claimed_stops_its_dial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tick commits its claim, then dials from the in-memory copy. An erasure that
    commits in between cancels the row and anonymises its number but adds the number to no
    list the gate reads, so the link to the call is the last place the dial can see it."""
    tenant_id, agent_id = await _dialable_tenant()
    callback_id = await _book(tenant_id, agent_id)

    real_origin = callbacks_worker.call_origin

    async def erase_then_origin(session, **kwargs):  # type: ignore[no-untyped-def]
        await _erase(tenant_id, CALLER)
        return await real_origin(session, **kwargs)

    engine = get_engine()
    original = engine.start_outbound_call
    rung: list[str] = []

    async def dial(ref: str, to: str, ctx: CallContext) -> str:
        rung.append(to)
        return await original(ref, to, ctx)

    monkeypatch.setattr(callbacks_worker, "call_origin", erase_then_origin)
    monkeypatch.setattr(engine, "start_outbound_call", dial)

    outcome = await dispatch_due_callbacks(tenant_id, slots=5)

    assert rung == [], "a person was rung after their erasure committed"
    assert outcome["dialled"] == 0, outcome
    row = await _row(tenant_id, callback_id)
    assert row["status"] == "cancelled"
    assert row["last_call_id"] is None
    async with tenant_session(tenant_id) as session:
        calls = (
            await session.execute(
                text("SELECT count(*) FROM calls WHERE to_e164 = :p"), {"p": CALLER}
            )
        ).scalar_one()
    assert calls == 0, "the erased number was written to a new call row"


async def test_a_pause_landing_behind_the_claim_holds_the_rest_of_the_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tick claims a batch and dials it one call-back at a time. A campaign paused
    while the first is being dialled holds the second (D-914), as the campaign tick
    re-reads its campaign before each contact."""
    tenant_id, agent_id = await _dialable_tenant()
    campaign_id = await _campaign(tenant_id, agent_id, status="running")
    first = await book_on_campaign(
        tenant_id,
        agent_id,
        campaign_id=campaign_id,
        phone=HOLD_CALLER,
        requested_at=datetime.now(UTC) - timedelta(minutes=2),
    )
    second = await book_on_campaign(
        tenant_id,
        agent_id,
        campaign_id=campaign_id,
        phone=OTHER,
        requested_at=datetime.now(UTC) - timedelta(minutes=1),
    )

    engine = get_engine()
    original = engine.start_outbound_call
    rung: list[str] = []

    async def dial_then_pause(ref: str, to: str, ctx: CallContext) -> str:
        handle = await original(ref, to, ctx)
        rung.append(to)
        if len(rung) == 1:
            await _set_status(tenant_id, campaign_id, "paused")
        return handle

    monkeypatch.setattr(engine, "start_outbound_call", dial_then_pause)
    outcome = await dispatch_due_callbacks(tenant_id, slots=5)

    # `UPDATE ... RETURNING` does not keep the claim's ORDER BY, so either may go first.
    assert len(rung) == 1, f"a paused campaign's call-back was dialled: {rung}"
    assert outcome["dialled"] == 1, outcome
    dialled, waiting = (first, second) if rung == [HOLD_CALLER] else (second, first)
    assert (await _row(tenant_id, dialled))["status"] == "dialing"
    held = await _row(tenant_id, waiting)
    assert held["status"] == "scheduled"
    assert held["last_refusal_rule"] == callbacks.CAMPAIGN_PAUSED_RULE
    assert int(held["attempts"]) == 0, "a held call-back was charged an attempt"


async def test_a_lead_rung_inline_is_not_rung_again_when_its_bookkeeping_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The engine accepted the dial, then a write after it failed. Raising would roll back
    the lead and the inbox claim with it, and the form vendor's retry of the same
    submission would ring the person a second time."""
    from apps.api.follow_ups import runner as follow_up_runner
    from apps.api.ingest.routes import SECRET_HEADER
    from sqlalchemy.exc import OperationalError
    from tests.lead_ingest_test import SECRET, _client, _tenant_with_ingest

    tenant_id, _agent_id, webhook_id = await _tenant_with_ingest()
    engine = get_engine()
    original = engine.start_outbound_call
    rung: list[str] = []

    async def dial(ref: str, to: str, ctx: CallContext) -> str:
        rung.append(to)
        return await original(ref, to, ctx)

    real_book_retry = follow_up_runner.book_retry

    async def failing_book_retry(*args: object, **kwargs: object) -> object:
        if len(rung) == 1:
            raise OperationalError("INSERT scheduled_callbacks", {}, ConnectionError("blip"))
        return await real_book_retry(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(engine, "start_outbound_call", dial)
    monkeypatch.setattr(follow_up_runner, "book_retry", failing_book_retry)
    submission = {"phone_number": "9876508877", "full_name": "Rung Once"}
    for _ in range(2):  # the delivery, then the sender's retry of it
        async with _client() as http:
            await http.post(
                f"/hooks/v1/ingest/{webhook_id}", json=submission, headers={SECRET_HEADER: SECRET}
            )

    assert rung == ["+919876508877"], f"the lead was rung {len(rung)} times"
    async with tenant_session(tenant_id) as session:
        leads = (
            await session.execute(text("SELECT count(*) FROM leads WHERE phone_e164 = :p"), {"p": "+919876508877"})
        ).scalar_one()
    assert leads == 1, "the enquiry was lost with the failed write"
