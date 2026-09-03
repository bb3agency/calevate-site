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

**The staleness is a property of the ROW, not of the flag.** `spend_state` is one row
per tenant (PK `tenant_id`), stamped with the month it counts and reset by the meter on
rollover — so `minutes_used` and `spend_used` go stale in exactly the same way `capped`
does, and every reader of any column of that row owes the same check. Three of them were
found taking half of it or none: `usage_summary` month-checked the flag and then read
`spend_used` out of the same row without it, `crm.service.dashboard` selected
`minutes_used` with no month at all, and neither could answer a `?month=` query about a
closed month, which the row cannot answer at all. They all go through
`billing.caps.read_spend_counters` now, which hands back the counters TOGETHER so a
caller cannot take half the check.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from apps.api.admin import service as admin_service
from apps.api.billing.service import current_billing_month, usage_summary
from apps.api.compliance.service import check_dispatch, spend_capped
from apps.api.crm.service import dashboard
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from sqlalchemy import text
from tests.conftest import accept_agreements


async def _capped_tenant(month: str) -> tuple[uuid.UUID, uuid.UUID]:
    """A tenant carrying a `capped` spend_state row stamped with `month`."""
    created = await admin_service.create_organization(
        name="Cap Motors",
        slug=f"cap-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
        # THE MANAGED MOTION, named rather than inherited (D-521 moved the default to
        # `prepaid`). This file's subject is a tenant with NO plan row: what the panel,
        # the cap and the invoice say when nothing quotes a price for their minutes —
        # ₹0, together, with `warn_no_plan_in_effect` making the gap visible. A prepaid
        # month has no plan row EITHER and is still priced, at the published list rate,
        # so on the default tier the "no price anywhere" case cannot be constructed.
        plan_tier="managed",
    )
    # The four agreements, accepted (migration a9d4e70c31b8) — supplied, never assumed
    # away, in the shape `arm_agent_for_outbound` established. Every dial, launch and
    # publish gate now refuses an organisation that has not accepted them, so a fixture
    # without this reports `agreements_not_accepted` in place of the answer under test.
    await accept_agreements(uuid.UUID(str(created["id"])))
    tenant_id, agent_id = created["id"], created["agent_id"]
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET status = 'live', direction = 'outbound' WHERE id = :a"),
            {"a": agent_id},
        )
        await session.execute(
            text(
                "INSERT INTO spend_state (tenant_id, month, minutes_used, spend_used, billed_inr, "
                "capped, created_at, updated_at) VALUES (:t, :m, 500, CAST(:s AS numeric), "
                "CAST(:s AS numeric), true, now(), now())"
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


async def test_the_usage_panel_does_not_report_a_closed_months_spend() -> None:
    """The SAME staleness, one column to the left of the flag.

    `usage_summary` checked the month for `capped` and then read `spend_used` out of the
    same row without it — one predicate applied to one of the two columns it was written
    for. A tenant whose row still carried July was shown July's rupees as August's spend,
    beside a minutes figure correctly read from `usage_events` for August.

    Both now come from `read_spend_counters`, which returns the counters TOGETHER so a
    caller cannot take half the check.
    """
    tenant_id, _agent_id = await _capped_tenant(_last_month())

    async with tenant_session(tenant_id) as session:
        summary = await usage_summary(session, tenant_id=tenant_id)

    assert summary["capped"] is False
    assert summary["spend_used_inr"] == Decimal("0.00"), (
        "a closed month's counter was reported as this month's spend"
    )


async def test_the_usage_panel_reports_a_live_months_spend() -> None:
    """The other direction, so the fix above cannot be satisfied by always saying zero."""
    tenant_id, _agent_id = await _capped_tenant(current_billing_month())

    async with tenant_session(tenant_id) as session:
        summary = await usage_summary(session, tenant_id=tenant_id)

    assert summary["capped"] is True
    assert summary["spend_used_inr"] == Decimal("5000.00")


async def test_a_closed_month_query_is_answered_from_the_ledger_not_the_live_row() -> None:
    """`?month=` on a month that is over.

    `spend_state` is one row per tenant with no history (PK `tenant_id`), so the live
    row's rupees belong to whatever month the meter last stamped — never to the month
    being asked about. The statement for a closed month comes from `usage_events`, the
    same place its minutes already came from.
    """
    tenant_id, _agent_id = await _capped_tenant(current_billing_month())
    closed = _last_month()
    # A ledger row inside the CLOSED month: 120 seconds at ₹0.50/s of supplier cost.
    # `occurred_at` is bucketed by `_IST_MONTH`, so the 15th is safely inside it whatever
    # the timezone offset does at the boundaries.
    async with tenant_session(tenant_id) as session:
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar()
        call_id = uuid7()
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
                "status, duration_s, started_at, created_at, updated_at) VALUES (:i, :t, :a, :e, "
                "'outbound', '+919876500001', 'completed', 120, :at, now(), now())"
            ),
            {
                "i": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": f"exec_{uuid.uuid4().hex[:12]}",
                "at": f"{closed}-15T10:00:00+05:30",
            },
        )
        await session.execute(
            text(
                "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                "unit_cost_paid, occurred_at, created_at) VALUES (:i, :t, :c, 'telephony_s', "
                "120, 0.5000, :at, now())"
            ),
            {
                "i": uuid7(),
                "t": tenant_id,
                "c": call_id,
                "at": f"{closed}-15T10:00:00+05:30",
            },
        )
        summary = await usage_summary(session, tenant_id=tenant_id, month=closed)

    assert summary["month"] == closed
    assert summary["minutes_used"] == Decimal("2.00"), "the minutes come from the ledger"
    # **₹0.00, NOT THE ₹5000 IN THE LIVE ROW AND NOT THE ₹60 THE LEDGER COST US.**
    #
    # The first is what this test is about: `spend_state` is one row per tenant with no
    # history, so its rupees belong to whatever month the meter last stamped and can
    # never be a closed month's answer. ₹5000 here would be the defect.
    #
    # ₹60 was the OLD right answer and is now the wrong one (P1.3): it is 120 seconds at
    # ₹0.50 of SUPPLIER cost, which is what the engine charged us, on the client's own
    # panel. This tenant has no `plans` row, so nothing quotes a price for their minutes
    # and `priced_overage` refuses to invent one — the panel, the cap and the invoice
    # all say ₹0 together, and `warn_no_plan_in_effect` is what makes the missing plan
    # visible instead.
    assert summary["spend_used_inr"] == Decimal("0.00"), (
        "the closed month reported the live row's ₹5000 instead of its own figure"
    )


async def test_the_dashboard_tile_does_not_report_a_closed_months_minutes() -> None:
    """The third reader of the same row, and the one a client looks at daily.

    `crm.service.dashboard` selected `minutes_used FROM spend_state LIMIT 1` — the
    pre-fix predicate, with no month at all — and published it as `minutes_used_month`.
    The tenant this bites is precisely the one that hits a cap: outbound-only, so nothing
    meters until a dial goes out, so the row keeps last month's stamp and the dashboard
    reports last month's minutes beside a call count that correctly says zero.
    """
    tenant_id, _agent_id = await _capped_tenant(_last_month())

    async with tenant_session(tenant_id) as session:
        tile = await dashboard(session)

    assert tile.minutes_used_month == Decimal("0"), (
        "a closed month's minutes were reported as this month's usage"
    )


async def test_the_dashboard_tile_reports_a_live_months_minutes() -> None:
    """And still reports real usage, so the fix above is not "always say zero"."""
    tenant_id, _agent_id = await _capped_tenant(current_billing_month())

    async with tenant_session(tenant_id) as session:
        tile = await dashboard(session)

    assert tile.minutes_used_month == Decimal("500.0000")
