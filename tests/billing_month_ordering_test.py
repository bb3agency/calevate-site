"""Which IST billing month a metered call belongs to, and what a LATE one may move.

Two defects, one seam. `spend_state` is a single row per tenant carrying the month it is
counting, and `apps/workers/pipeline.py::_meter` is what stamps that month from the
call's own `ended_at`. Both halves of that sentence were wrong in a way the money core
audit could not see, because both are about a call whose month is not the month the
counter is already on.

**1. The month was computed by a second, wrong spelling.** `_meter` used a private
`_ist_month(moment)` = `(moment + 5:30).strftime("%Y-%m")`, which is only correct when
`moment` is expressed in UTC. Nothing guarantees that: both engine adapters parse
`ended_at` with `datetime.fromisoformat` and PRESERVE whatever offset the vendor sent
(`apps/api/engine/bolna.py::_parse_dt`, `cartesia.py::_parse_dt` — the `replace(tzinfo=
UTC)` there is for NAIVE values only). A vendor that stamps `+05:30` — an Indian voice
platform is the likely case, not the exotic one — makes every call shift a further 5.5
hours, so a call at 23:00 IST on the last of the month is counted into the NEXT month
while its own `usage_events` row (read back through `billing.service._IST_MONTH`, which
goes through `timestamptz` and is correct) stays in the right one. `plans
.ist_billing_month` already spelled this correctly and refuses a naive instant instead of
guessing at one; `_meter` now calls it.

**2. A call from a CLOSED month could reset the OPEN month's counters.** The upsert's
`CASE WHEN spend_state.month = EXCLUDED.month THEN accumulate ELSE take-the-new-value`
is right in one direction and destructive in the other: a call that settles late — the
reconciliation poller's 30-minute window straddling midnight IST on the 1st, an ARQ retry
ladder crossing it, a vendor that takes minutes to price a call — arrives with LAST
month's stamp, does not match, and therefore REPLACES this month's minutes, spend, billed
rupees and `capped` flag with its own. A tenant one call short of their ceiling is handed
a fresh month's headroom by a call they made in the month before.

Both are proved here against the real meter and the real `spend_state` row.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from apps.api.billing.service import _IST_MONTH
from apps.api.db.session import tenant_session, untenanted_session
from apps.workers.pipeline import _meter
from sqlalchemy import text
from tests.spend_caps_test import _call_row, _plan, _snapshot, _spend_state, _tenant

#: The offset an Indian vendor would stamp on a timestamp. India has no DST, so this is a
#: constant rather than a zoneinfo lookup — the same one `billing/plans.py` declares.
_IST = timezone(timedelta(hours=5, minutes=30))


async def _clean(tenant_id: UUID) -> None:
    """Drop the counter row this file created. `usage_events` and `credit_ledger` are
    append-only (hard rule 4) and are left alone; `spend_state` is a counter table and is
    this suite's to remove."""
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("DELETE FROM spend_state WHERE tenant_id = :t"), {"t": tenant_id}
        )


# ============================================================================
# 1. One spelling of "which IST month is this"
# ============================================================================


async def test_the_metered_month_agrees_with_the_row_the_call_wrote() -> None:
    """A call at 23:00 IST on the last of August is an AUGUST call, however the vendor
    chose to spell the instant.

    The counter's month and the `usage_events` month are one fact read two ways — Python
    in the worker, `_IST_MONTH` in every billing query — and they must not be able to
    disagree about one call. Before the fix this metered into `2026-09` while its own
    ledger rows sat in `2026-08`.
    """
    tenant_id, agent_id, _ref = await _tenant(f"month_agree_{uuid.uuid4().hex[:6]}")
    await _plan(tenant_id, included_min=0)
    ended = datetime(2026, 8, 31, 23, 0, tzinfo=_IST)
    call_id = await _call_row(tenant_id, agent_id)

    await _meter(tenant_id, call_id, _snapshot(seconds=60, spend="1.0000", ended=ended))

    async with tenant_session(tenant_id) as session:
        row_month = (
            await session.execute(
                text(
                    "SELECT DISTINCT to_char(occurred_at + interval '5 hours 30 minutes', "
                    "'YYYY-MM') FROM usage_events WHERE call_id = :c"
                ),
                {"c": call_id},
            )
        ).scalar()
    counter_month, *_ = await _spend_state(tenant_id)
    assert counter_month == row_month == "2026-08"
    await _clean(tenant_id)


# ============================================================================
# 2. A late call from a closed month may not reset the open month
# ============================================================================


async def test_a_late_call_from_a_closed_month_does_not_wipe_this_months_counters() -> None:
    """The reconciliation poller's window straddles midnight IST on the 1st.

    Call A is the new month's first call and stamps the counter. Call B ended BEFORE the
    roll and settles afterwards. Before the fix the upsert saw `month <> EXCLUDED.month`,
    took the ELSE branch and replaced ten minutes of September with ten minutes of
    August — the month, the totals and the cap flag all going backwards.
    """
    tenant_id, agent_id, _ref = await _tenant(f"late_call_{uuid.uuid4().hex[:6]}")
    await _plan(tenant_id, cap_spend="10000.0000", included_min=0)

    # Deliberately UTC-stamped and hours clear of the boundary, so this test measures the
    # UPSERT's ordering rule and not the month helper the test above owns. Either defect
    # alone reproduces here; spelling both into one fixture would let one mask the other,
    # which is exactly what a first draft of this file did (both instants landed in
    # September under the old helper and the wipe never fired).
    open_month_call = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    closed_month_call = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)

    call_a = await _call_row(tenant_id, agent_id)
    await _meter(tenant_id, call_a, _snapshot(seconds=600, spend="5.0000", ended=open_month_call))
    month_after_a, minutes_after_a, _spend_a, _capped_a, billed_after_a = await _spend_state(
        tenant_id
    )
    assert month_after_a == "2026-09"
    assert Decimal(str(minutes_after_a)) == Decimal("10")

    call_b = await _call_row(tenant_id, agent_id)
    await _meter(tenant_id, call_b, _snapshot(seconds=600, spend="5.0000", ended=closed_month_call))
    month_after_b, minutes_after_b, _spend_b, _capped_b, billed_after_b = await _spend_state(
        tenant_id
    )

    assert month_after_b == "2026-09", "a closed month's call must not roll the counter back"
    assert Decimal(str(minutes_after_b)) == Decimal(str(minutes_after_a)), (
        "the open month's minutes must survive a late call from the month before"
    )
    assert Decimal(str(billed_after_b)) == Decimal(str(billed_after_a))
    await _clean(tenant_id)


async def test_the_month_still_rolls_forward_when_the_new_month_arrives() -> None:
    """The guard is one-directional: a call in a LATER month still resets, which is the
    behaviour the rollover depends on and the one thing the fix must not cost."""
    tenant_id, agent_id, _ref = await _tenant(f"roll_fwd_{uuid.uuid4().hex[:6]}")
    await _plan(tenant_id, cap_spend="10000.0000", included_min=0)

    call_a = await _call_row(tenant_id, agent_id)
    await _meter(
        tenant_id,
        call_a,
        _snapshot(seconds=600, spend="5.0000", ended=datetime(2026, 8, 15, 12, 0, tzinfo=UTC)),
    )
    call_b = await _call_row(tenant_id, agent_id)
    await _meter(
        tenant_id,
        call_b,
        _snapshot(seconds=120, spend="1.0000", ended=datetime(2026, 9, 15, 12, 0, tzinfo=UTC)),
    )
    month, minutes, _spend, _capped, _billed = await _spend_state(tenant_id)
    assert month == "2026-09"
    assert Decimal(str(minutes)) == Decimal("2"), "the new month starts from this call alone"
    await _clean(tenant_id)


# ============================================================================
# 3. The SQL half of the same fact does not depend on the session's TimeZone
# ============================================================================


async def test_the_sql_billing_month_is_the_same_under_any_session_timezone() -> None:
    """`_IST_MONTH` is interpolated into every query that buckets `usage_events` by
    month, and it used to be `to_char(occurred_at + interval '5 hours 30 minutes', ...)`.

    `to_char` on a `timestamptz` renders the instant in the SESSION's `TimeZone`, so
    shifting first and formatting second is the IST month only while that setting is UTC.
    It IS UTC on this database and nothing in `apps/` sets it — which is precisely why
    this is a test rather than a comment: the property was held by an environment
    variable, and the failure it hid is silent and moves money.

    23:00 IST on the last of August is an August call under every session zone.
    """
    august_evening_ist = "timestamptz '2026-08-31 17:30:00+00'"
    async with untenanted_session() as session:
        for zone in ("UTC", "Asia/Kolkata", "America/New_York"):
            # `SET LOCAL` so the change dies with this transaction and no sibling suite
            # sharing this database ever sees it.
            await session.execute(text(f"SET LOCAL TimeZone = '{zone}'"))
            expression = _IST_MONTH.replace("occurred_at", august_evening_ist)
            month = (await session.execute(text(f"SELECT {expression}"))).scalar()
            assert month == "2026-08", f"the billing month moved under TimeZone={zone}"
