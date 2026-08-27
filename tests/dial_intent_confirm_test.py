"""What happens to the intent row when the vendor's handle CANNOT be stamped onto it.

D-181 split one write into two: `dispatch_call` commits a `calls` row keyed on an id we
mint (`local:<uuid>`) BEFORE the engine can seize a line, and `_confirm_dial` then
replaces that id with the vendor's handle in its own transaction. The happy half is
proved everywhere — `lead_dial_routes_test`, `dispatch_budget_test` and
`campaign_dispatch_audit_test` all read a stamped `engine_call_id` back.

The half nobody had executed is the one where the stamp does NOT land, and it is the
half that decides whether a phone that already rang is a call record or a mystery:

1. **The poller got there first.** Bolna is unsigned, so the reconciliation poller is
   the truth (TRD §5) and it creates rows for executions it discovers. It can therefore
   already hold a row for THIS execution by the time we come to stamp ours. The
   `NOT EXISTS` guard is what stops the stamp; without it the unique index would abort a
   transaction whose only job is bookkeeping for a call that is by now really ringing.

2. **The colliding row belongs to somebody else.** `uq_calls_engine_call_id` is GLOBAL —
   one row per vendor handle across the whole platform, because the handle space is the
   vendor's and not ours — while the `NOT EXISTS` guard runs under the dialling tenant's
   own RLS and can only see that tenant's rows. So a handle already held by ANOTHER
   tenant is invisible to the guard and fatal to the index, which is the interleave the
   `except IntegrityError` exists for, made deterministic.

In both cases the contract is the same and it is what these tests pin: `dispatch_call`
RETURNS, because the call is ringing and raising would tell the caller otherwise; OUR
row keeps its `local:` id, so it is visible, `queued`, and settled by the same reaper as
any other unconfirmed dial; and an operator gets `dial_handle_not_stamped` with the id
to reconcile against. Nothing here is allowed to touch the row that won.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import service as agents_service
from apps.api.agents.service import UNCONFIRMED_ENGINE_CALL_PREFIX, unconfirmed_engine_call_id
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine import reset_engine_cache
from apps.api.engine.fake import FakeEngine
from calevate_shared.engine import CallContext
from sqlalchemy import text
from tests.conftest import accept_agreements

_TENANTS: list[uuid.UUID] = []


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    fixed = datetime(2026, 8, 11, 5, 30, tzinfo=UTC) + timedelta(hours=5, minutes=30)
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: fixed)


@pytest.fixture(scope="module", autouse=True)
async def _settle_what_this_module_started() -> AsyncIterator[None]:
    """Every test here leaves a `queued` row on purpose — that is the assertion. Left
    behind, each one spends a line out of the shared outbound pool for an hour and makes
    another suite's budget arithmetic depend on this one having run."""
    yield
    for tenant_id in _TENANTS:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "UPDATE calls SET status = 'completed', updated_at = now() "
                    "WHERE status IN ('queued', 'ringing', 'in_progress')"
                )
            )


async def _dialable_tenant() -> tuple[uuid.UUID, uuid.UUID]:
    """An org whose agent is live, outbound and published — the minimum `dispatch_call`
    will accept. No campaign and no DLT paperwork: the per-dial gate is not on this
    function (its callers run it), and every rule it would ask is proved elsewhere."""
    reset_engine_cache()
    created = await admin_service.create_organization(
        name="Stamp Motors",
        slug=f"stamp-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    # The four agreements, accepted (migration a9d4e70c31b8) — supplied, never assumed
    # away, in the shape `arm_agent_for_outbound` established. Every dial, launch and
    # publish gate now refuses an organisation that has not accepted them, so a fixture
    # without this reports `agreements_not_accepted` in place of the answer under test.
    await accept_agreements(uuid.UUID(str(created["id"])))
    tenant_id = uuid.UUID(str(created["id"]))
    agent_id = uuid.UUID(str(created["agent_id"]))
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agents SET status = 'live', direction = 'outbound', "
                "engine_agent_ref = :ref WHERE id = :a"
            ),
            {"ref": f"fakeagent_stamp_{uuid.uuid4().hex[:8]}", "a": agent_id},
        )
    _TENANTS.append(tenant_id)
    return tenant_id, agent_id


async def _plant_call(tenant_id: uuid.UUID, agent_id: uuid.UUID, handle: str) -> uuid.UUID:
    """A `calls` row already carrying `handle` — what the poller writes for an execution
    it discovered before we could stamp ours."""
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                "to_e164, status, created_at, updated_at) VALUES (:id, :tid, :aid, :ecid, "
                "'outbound', :to_e, 'in_progress', now(), now())"
            ),
            {
                "id": call_id,
                "tid": tenant_id,
                "aid": agent_id,
                "ecid": handle,
                "to_e": "+919876770001",
            },
        )
    return call_id


def _returning(handle: str) -> object:
    """An engine that answers with a handle WE chose.

    `FakeEngine` derives its handle from the agent ref, the destination and a counter,
    so a collision could only be arranged by replaying a previous dial's exact inputs.
    Naming the handle is what makes both collisions here deterministic rather than
    contrived — which is the difference between a test of the guard and a test of the
    fake.
    """

    async def start_outbound_call(self: FakeEngine, ref: str, to: str, ctx: CallContext) -> str:
        return handle

    return start_outbound_call


async def _row(tenant_id: uuid.UUID, call_id: uuid.UUID) -> tuple[str, str]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT engine_call_id, status FROM calls WHERE id = :id"), {"id": call_id}
            )
        ).first()
    assert row is not None, "the row this test planted is gone, so it proves nothing"
    return str(row[0]), str(row[1])


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.message for r in caplog.records if r.levelno >= logging.WARNING]


async def test_a_handle_the_poller_already_recorded_leaves_our_row_on_its_local_id(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The guard's own scenario, driven rather than argued.

    The poller creating the row first is not an error and must not be reported as one to
    the caller: the call is ringing, and the row the pipeline will use exists. What must
    NOT happen is the poller's row being overwritten, or ours being left pointing at a
    handle two rows claim.
    """
    tenant_id, agent_id = await _dialable_tenant()
    handle = f"fakecall_poller_{uuid.uuid4().hex[:12]}"
    poller_call_id = await _plant_call(tenant_id, agent_id, handle)

    monkeypatch.setattr(FakeEngine, "start_outbound_call", _returning(handle))
    with caplog.at_level(logging.WARNING, logger="calevate.apps.api.agents.service"):
        async with tenant_session(tenant_id) as session:
            returned = await agents_service.dispatch_call(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                lead_id=None,
                phone_e164="+919876770002",
            )

    assert returned == handle, "the caller is told the handle the vendor gave, stamped or not"
    assert await _row(tenant_id, poller_call_id) == (handle, "in_progress"), (
        "the row the poller wrote is the one the pipeline uses and was not overwritten"
    )
    async with tenant_session(tenant_id) as session:
        ours = (
            await session.execute(
                text("SELECT id, engine_call_id, status FROM calls WHERE to_e164 = '+919876770002'")
            )
        ).all()
    assert len(ours) == 1, "one dial, one intent row"
    call_id, engine_call_id, status = ours[0]
    assert engine_call_id == unconfirmed_engine_call_id(uuid.UUID(str(call_id)))
    assert str(engine_call_id).startswith(UNCONFIRMED_ENGINE_CALL_PREFIX)
    assert str(status) == "queued", "left claimable by the reaper, not silently completed"
    assert any("dial_handle_not_stamped" in m for m in _warnings(caplog)), _warnings(caplog)


async def test_a_handle_another_tenant_holds_is_invisible_to_the_guard_and_survived_anyway(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """`uq_calls_engine_call_id` is platform-wide; the guard reads under one tenant's RLS.

    Those two facts cannot both be honoured by a `NOT EXISTS`, which is exactly why the
    `except IntegrityError` is there and why "the guard and the insert can interleave" is
    not the only way to reach it. A cross-tenant handle collision reproduces it with no
    concurrency at all: tenant B holds the handle, tenant A's guard cannot see B's row,
    the UPDATE runs and the index refuses it.

    The requirement is that the refusal costs bookkeeping and nothing else. A dial that
    raised here would tell the caller the call failed while the customer's phone was
    ringing — and on the campaign path that answer is a contact returned to the ladder
    and rung a second time.
    """
    other_tenant, other_agent = await _dialable_tenant()
    tenant_id, agent_id = await _dialable_tenant()
    handle = f"fakecall_crosstenant_{uuid.uuid4().hex[:12]}"
    theirs = await _plant_call(other_tenant, other_agent, handle)

    monkeypatch.setattr(FakeEngine, "start_outbound_call", _returning(handle))
    with caplog.at_level(logging.WARNING, logger="calevate.apps.api.agents.service"):
        async with tenant_session(tenant_id) as session:
            returned = await agents_service.dispatch_call(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                lead_id=None,
                phone_e164="+919876770003",
            )

    assert returned == handle
    assert await _row(other_tenant, theirs) == (handle, "in_progress"), (
        "the other tenant's call record is untouched by a dial it has nothing to do with"
    )
    async with tenant_session(tenant_id) as session:
        ours = (
            await session.execute(
                text("SELECT id, engine_call_id, status FROM calls WHERE to_e164 = '+919876770003'")
            )
        ).all()
    assert len(ours) == 1, "the integrity failure rolled back bookkeeping, not the intent row"
    call_id, engine_call_id, status = ours[0]
    assert engine_call_id == unconfirmed_engine_call_id(uuid.UUID(str(call_id)))
    assert str(status) == "queued"
    assert any("dial_handle_not_stamped" in m for m in _warnings(caplog)), _warnings(caplog)
