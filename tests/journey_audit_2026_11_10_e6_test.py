"""Journey audit E6 (10 Nov 2026): concurrency and failure.

Each test forces one interleaving between two writers, or a failure between two commits,
and asserts the outcome the code promises.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from apps.api.callbacks import service as callbacks
from apps.api.compliance.deletion import request_erasure
from apps.api.db.session import tenant_session, untenanted_session
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
            await session.execute(
                text("SELECT count(*) FROM leads WHERE phone_e164 = :p"), {"p": "+919876508877"}
            )
        ).scalar_one()
    assert leads == 1, "the enquiry was lost with the failed write"


async def test_a_top_up_landing_while_the_phone_is_being_silenced_still_brings_it_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Job A (queued by the charge that emptied the wallet) is overriding the script when
    a top-up commits and queues job B. B must not decide from A's uncommitted state, or it
    finds nothing to restore, A then commits the silence, and the paid client's phone stays
    off until somebody republishes."""
    import asyncio

    from apps.api.engine.fake import FakeEngine
    from apps.workers.inbound_cutover import apply_inbound_credit_state
    from tests.inbound_credit_cutover_test import _publish, _silenced_at, _spend, _tenant, _topup

    tenant_id, agent_id = await _tenant()
    await _topup(tenant_id, "500")
    await _publish(tenant_id, agent_id)
    await _spend(tenant_id, "-500")

    real_override = FakeEngine.override_call_script
    second: list[asyncio.Task[str]] = []

    async def override_while_topping_up(self: FakeEngine, *args: object, **kwargs: object) -> None:
        await real_override(self, *args, **kwargs)  # type: ignore[arg-type]
        if not second:
            await _topup(tenant_id, "500")
            second.append(
                asyncio.create_task(
                    apply_inbound_credit_state({"job_try": 1}, {"tenant_id": str(tenant_id)})
                )
            )
            # Give job B every chance to finish before A commits.
            await asyncio.wait({second[0]}, timeout=1.0)

    monkeypatch.setattr(FakeEngine, "override_call_script", override_while_topping_up)
    await apply_inbound_credit_state({"job_try": 1}, {"tenant_id": str(tenant_id)})
    await second[0]

    assert await _silenced_at(tenant_id, agent_id) is None, (
        "the client paid, and their phone is still turning callers away"
    )


async def test_a_top_up_after_the_pass_decided_does_not_lose_the_number(
    account: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The hold pass decides "stopped" once, then walks the holds. A top-up that commits
    after that decision and before a due hold's release must keep the number: the release
    is permanent and the client has just paid."""
    from apps.api.billing.service import record_entry
    from apps.api.campaigns import number_holds as holds
    from apps.workers import number_holds as jobs
    from tests.number_holds_test import _hold_rows, _no_trial, _overdrawn, _rented
    from tests.number_holds_test import _tenant as hold_tenant

    monkeypatch.setattr(holds, "trial_billing_active", _no_trial)
    tenant_id, agent_id = await hold_tenant()
    _number_id, number, _workspace = await _rented(account, tenant_id, agent_id)  # type: ignore[arg-type]
    await _overdrawn(tenant_id, days=8)
    await jobs.settle_tenant(tenant_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE phone_number_holds SET held_at = now() - interval '2 days', "
                "release_at = now() - interval '1 minute'"
            )
        )

    real_claim = jobs.claim_release

    async def top_up_then_claim(session, *, hold_id):  # type: ignore[no-untyped-def]
        async with tenant_session(tenant_id) as other:
            await record_entry(
                other, tenant_id=tenant_id, delta=Decimal("500.00"), reason="grant", ref="e6-top-up"
            )
        return await real_claim(session, hold_id=hold_id)

    monkeypatch.setattr(jobs, "claim_release", top_up_then_claim)
    tally, failed = await jobs.settle_tenant(tenant_id)

    assert failed == 0
    assert tally["released"] == 0, "a paid client's number was released"
    assert not any(
        s.method == "DELETE" and s.path.endswith(f"/{number}")
        for s in account.sent  # type: ignore[attr-defined]
    )
    [hold] = await _hold_rows(tenant_id)
    assert hold.ended_at is None, "the hold must be left for the resume pass the top-up queued"


async def test_a_grant_notice_whose_client_email_keeps_failing_is_not_posted_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run that ends in `Retry` on its last try is a failed arq run, so the outbox never
    marks the message consumed and re-publishes it two hours later as try 1: the dashboard
    notice went up again (it checks for its own copy only on a retry) and every super admin
    was emailed again, up to five times. The last try ends the job instead, and alarms."""
    from apps.api.core.queue import WORKER_MAX_TRIES
    from apps.workers import comp_notices
    from arq import Retry
    from sqlalchemy import text as sql
    from tests.credit_grant_test import _tenant as grant_tenant

    class _ClientRefuses:
        def send(self, *, to: str, subject: str, body: str, html: str | None = None) -> bool:
            return to != "owner@example.com"

    fired: list[str] = []
    monkeypatch.setattr(comp_notices, "get_transport", lambda _purpose=None: _ClientRefuses())
    monkeypatch.setattr(comp_notices, "alert", lambda _stage, code, **_kw: fired.append(code))
    tenant_id = await grant_tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            sql("UPDATE organizations SET billing_email = 'owner@example.com' WHERE id = :t"),
            {"t": tenant_id},
        )
    payload = {
        "tenant_id": str(tenant_id),
        "kind": "grant",
        "amount_inr": "250.00",
        "actor_id": None,
        "reason": "e6",
    }
    # The superadmin leg must have someone to email, whatever the shared database holds.
    super_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            sql(
                "INSERT INTO admin_users (id, name, role, email, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', :email, now(), now())"
            ),
            {"id": super_id, "email": f"ops-{super_id.hex[:12]}@example.com"},
        )
    try:
        for attempt in range(1, WORKER_MAX_TRIES):
            with pytest.raises(Retry):
                await comp_notices.notify_comp({"job_try": attempt}, payload)

        outcome = await comp_notices.notify_comp({"job_try": WORKER_MAX_TRIES}, payload)
    finally:
        async with untenanted_session() as session:
            await session.execute(
                sql("UPDATE admin_users SET deactivated_at = now() WHERE id = :id"),
                {"id": super_id},
            )

    assert outcome == "undelivered:client", "the last try must end the run, not fail it"
    assert fired == ["comp_notice_undelivered"]


async def test_an_account_closed_while_its_workspace_is_made_still_offboards_it(
    account: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The closure sets the workspace `offboarding` while the provisioning job waits on the
    vendor's create. The job must not then mark it active (the resolver would answer a
    closed client's workspace and offboarding would report nothing owed); it records the
    new workspace so offboarding can delete it."""
    from apps.api.engine.thinnest_customers import ThinnestCustomers
    from apps.api.tenancy import closure
    from apps.api.tenancy import engine_workspace as resolver
    from apps.workers import engine_workspaces as jobs
    from tests.engine_workspace_test import _owed_tenant, _state

    tenant_id = await _owed_tenant()
    real_create = ThinnestCustomers.create

    async def close_during_create(self: ThinnestCustomers, **kwargs: str) -> object:
        made = await real_create(self, **kwargs)
        async with tenant_session(tenant_id) as session:
            await closure.close_account(session, tenant_id=tenant_id, reason="test", closed_by=None)
        return made

    monkeypatch.setattr(ThinnestCustomers, "create", close_during_create)
    await jobs.provision_engine_workspace({}, {"tenant_id": str(tenant_id)})

    state = await _state(tenant_id)
    assert state.status == "offboarding", f"a closed client's workspace is {state.status}"
    assert await resolver.workspace_for_tenant(tenant_id) is None
    assert state.workspace_id is not None

    result = await jobs.offboard_engine_workspace({}, {"tenant_id": str(tenant_id)})
    assert result.startswith("released=0"), result
    assert account.customers[state.workspace_id]["archivedAt"] is not None  # type: ignore[attr-defined]
    assert (await _state(tenant_id)).status == "deleted"
