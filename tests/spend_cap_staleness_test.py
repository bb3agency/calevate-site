"""A cap belonging to a closed billing month is not a cap.

`spend_state.capped` is written by exactly one thing: the post-call pipeline's meter,
which runs when a call COMPLETES. That is fine while calls keep happening — but the flag
it writes is the thing that stops calls happening. So the moment it is set, the only
mechanism that could ever clear it stops running.

For a tenant with inbound traffic this resolves itself: inbound is never gated (the
caller initiated the call, so capping it would be an outage rather than a control), so
inbound calls keep metering and roll the month over. For an **outbound-only tenant** —
a campaign client, which is exactly the kind of tenant that hits a spend cap — it is a
deadlock: capped in July, refused every dial in August, no call able to complete and
clear it, forever.

Both readers of the flag therefore check the month. These tests are the reason that is
not an optimisation.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from apps.api.admin import service as admin_service
from apps.api.billing.service import current_billing_month, usage_summary
from apps.api.compliance.service import check_dispatch, spend_capped
from apps.api.db.session import tenant_session
from sqlalchemy import text


async def _capped_tenant(month: str) -> tuple[uuid.UUID, uuid.UUID]:
    """A tenant carrying a `capped` spend_state row stamped with `month`."""
    created = await admin_service.create_organization(
        name="Cap Motors",
        slug=f"cap-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET status = 'live', direction = 'outbound' WHERE id = :a"),
            {"a": agent_id},
        )
        await session.execute(
            text(
                "INSERT INTO spend_state (tenant_id, month, minutes_used, spend_used, capped, "
                "created_at, updated_at) VALUES (:t, :m, 500, CAST(:s AS numeric), true, now(), "
                "now())"
            ),
            {"t": tenant_id, "m": month, "s": Decimal("5000.0000")},
        )
    return tenant_id, agent_id


def _last_month() -> str:
    year, month = (int(part) for part in current_billing_month().split("-"))
    return f"{year - 1}-12" if month == 1 else f"{year}-{month - 1:02d}"


async def test_this_months_cap_still_refuses_the_dial() -> None:
    """The control has to work before its expiry can be interesting."""
    tenant_id, agent_id = await _capped_tenant(current_billing_month())

    async with tenant_session(tenant_id) as session:
        assert await spend_capped(session, tenant_id=tenant_id) is True
        decision = await check_dispatch(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            phone_e164=f"+9198{uuid.uuid4().int % 100000000:08d}",
        )
    assert not decision.allowed
    assert decision.rule == "spend_cap"


async def test_last_months_cap_does_not_refuse_this_months_dial() -> None:
    """The deadlock. Before the month check, this tenant could never dial again: the
    flag stops every call, and only a completed call could have cleared the flag."""
    tenant_id, agent_id = await _capped_tenant(_last_month())

    async with tenant_session(tenant_id) as session:
        assert await spend_capped(session, tenant_id=tenant_id) is False
        decision = await check_dispatch(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            phone_e164=f"+9198{uuid.uuid4().int % 100000000:08d}",
        )
    assert decision.rule != "spend_cap", "a closed month's cap must not stop a new month"


async def test_the_usage_panel_does_not_report_a_closed_months_cap() -> None:
    """The panel and the gate must agree. Showing "capped, 0 minutes left" to a client
    the gate is now happily dialling for is the UI contradicting the system — and it is
    the client who calls support about it."""
    tenant_id, _agent_id = await _capped_tenant(_last_month())

    async with tenant_session(tenant_id) as session:
        summary = await usage_summary(session, tenant_id=tenant_id)
    assert summary["capped"] is False


async def test_the_panel_and_the_gate_agree_while_the_cap_is_live() -> None:
    """The other direction of the same property, so a future fix cannot satisfy the
    tests above by simply never reporting a cap."""
    tenant_id, _agent_id = await _capped_tenant(current_billing_month())

    async with tenant_session(tenant_id) as session:
        summary = await usage_summary(session, tenant_id=tenant_id)
        gate_says = await spend_capped(session, tenant_id=tenant_id)
    assert summary["capped"] is True
    assert gate_says is True
