"""Clients are billed in 30-second steps, rounded up, on every engine (D-681).

One rule in two spellings — `rates.client_billed_minutes` for the call being metered, and
`rates.CLIENT_BILLED_SECONDS_SQL` for every reader that sums a month off the ledger — so
the wallet debit, the managed counter, the usage panel and the statement agree to the paisa.
The ledger's `telephony_s` row keeps the measured seconds.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from apps.api.billing.credit_packs import PACK_CATALOGUE
from apps.api.billing.plans import ist_billing_month
from apps.api.billing.rates import (
    CLIENT_BILLED_SECONDS_SQL,
    CLIENT_PULSE_EFFECTIVE_FROM,
    CLIENT_PULSE_SECONDS,
    client_billed_minutes,
    client_billed_seconds,
)
from apps.api.billing.service import (
    prepaid_call_statement_lines,
    usage_summary,
    voice_tier_usage,
)
from apps.api.db.session import tenant_session, untenanted_session
from apps.workers.pipeline import _meter
from sqlalchemy import text
from tests.client_rate_billing_test import _balance, _set_tier
from tests.spend_caps_test import _call_row, _plan, _snapshot, _spend_state, _tenant

#: The managed overage rate `spend_caps_test._plan` writes.
_OVERAGE = Decimal("8.00")

#: An instant under the increment, and one just before it began.
_AFTER = CLIENT_PULSE_EFFECTIVE_FROM
_BEFORE = CLIENT_PULSE_EFFECTIVE_FROM - timedelta(microseconds=1)


@pytest.mark.parametrize(
    ("seconds", "minutes"),
    [
        (0, "0"),
        (1, "0.5"),
        (30, "0.5"),
        (31, "1.0"),
        (60, "1.0"),
        (182, "3.5"),
        (-5, "0"),
    ],
)
def test_a_call_is_billed_in_whole_30_second_steps(seconds: int, minutes: str) -> None:
    assert client_billed_minutes(Decimal(seconds), at=_AFTER) == Decimal(minutes)
    assert client_billed_seconds(Decimal(seconds), at=_AFTER) == Decimal(minutes) * 60


def test_a_call_before_the_increment_began_keeps_its_measured_seconds() -> None:
    """A closed month is never re-priced: a call that ended before 7 Oct 2026 00:00 IST was
    billed by the second and is still read that way."""
    assert datetime(2026, 10, 6, 18, 30, tzinfo=UTC) == CLIENT_PULSE_EFFECTIVE_FROM
    assert client_billed_seconds(Decimal(31), at=_BEFORE) == Decimal(31)
    assert client_billed_minutes(Decimal(90), at=_BEFORE) == Decimal("1.5")


def test_the_increment_is_thirty_seconds() -> None:
    assert Decimal("30") == CLIENT_PULSE_SECONDS


async def test_the_sql_spelling_rounds_exactly_as_the_python_one() -> None:
    durations = [0, 1, 29, 30, 31, 59, 60, 61, 95, 182, 3847]
    expression = (
        f"SELECT {CLIENT_BILLED_SECONDS_SQL} FROM (SELECT CAST(:s AS numeric) AS qty, "
        "CAST(:at AS timestamptz) AS occurred_at) AS one_row"
    )
    async with untenanted_session() as session:
        for at in (_AFTER, _BEFORE):
            for seconds in durations:
                got = (
                    await session.execute(text(expression), {"s": seconds, "at": at})
                ).scalar_one()
                expected = client_billed_seconds(Decimal(seconds), at=at)
                assert Decimal(str(got)) == expected, (seconds, at)


async def _meter_seconds(tenant_id: UUID, agent_id: UUID, seconds: int) -> UUID:
    call_id = await _call_row(tenant_id, agent_id)
    await _meter(
        tenant_id, call_id, _snapshot(seconds=seconds, spend="0.5000", ended=datetime.now(UTC))
    )
    return call_id


async def test_the_wallet_is_debited_whole_steps_and_the_ledger_keeps_the_seconds() -> None:
    tenant_id, agent_id, _ = await _tenant("pulsewallet")
    await _set_tier(tenant_id, "self_serve")
    rate = PACK_CATALOGUE[0].clear_inr_per_min

    call_id = await _meter_seconds(tenant_id, agent_id, 31)
    assert await _balance(tenant_id) == -(rate * Decimal("1.0"))

    await _meter_seconds(tenant_id, agent_id, 1)
    assert await _balance(tenant_id) == -(rate * Decimal("1.5"))

    async with tenant_session(tenant_id) as session:
        measured = (
            await session.execute(
                text(
                    "SELECT qty FROM usage_events WHERE call_id = :c AND unit_type = 'telephony_s'"
                ),
                {"c": call_id},
            )
        ).scalar_one()
    assert Decimal(str(measured)) == Decimal(31), "the ledger keeps the measured seconds"


async def test_a_call_with_no_talk_time_costs_nothing() -> None:
    tenant_id, agent_id, _ = await _tenant("pulsezero")
    await _set_tier(tenant_id, "self_serve")
    await _meter_seconds(tenant_id, agent_id, 0)
    assert await _balance(tenant_id) == Decimal("0")


async def test_the_panel_and_the_statement_match_the_debits() -> None:
    tenant_id, agent_id, _ = await _tenant("pulsestatement")
    await _set_tier(tenant_id, "self_serve")
    for seconds in (31, 1, 95):  # 1.0 + 0.5 + 2.0 billed minutes
        await _meter_seconds(tenant_id, agent_id, seconds)

    debited = -await _balance(tenant_id)
    month = ist_billing_month(datetime.now(UTC))
    async with tenant_session(tenant_id) as session:
        summary = await usage_summary(session, tenant_id=tenant_id, month=month)
        charges = await voice_tier_usage(session, tenant_id=tenant_id, month=month)
        lines = await prepaid_call_statement_lines(session, tenant_id=tenant_id, month=month)

    assert summary["minutes_used"] == Decimal("3.50")
    assert charges.by_voice["clear"].minutes == Decimal("3.5")
    assert charges.total_inr == debited
    assert sum((line["amount_inr"] for line in lines), Decimal("0")) == debited
    assert [line["qty"] for line in lines] == [Decimal("3.50")]


async def test_a_managed_month_counts_whole_steps_against_the_allowance_and_overage() -> None:
    tenant_id, agent_id, _ = await _tenant("pulsemanaged")
    await _plan(tenant_id, included_min=0)

    await _meter_seconds(tenant_id, agent_id, 31)
    _m, minutes, _spend, _capped, billed = await _spend_state(tenant_id)
    assert minutes == Decimal("1.0000")
    assert billed == _OVERAGE * Decimal("1.0")

    await _meter_seconds(tenant_id, agent_id, 1)
    _m, minutes, _spend, _capped, billed = await _spend_state(tenant_id)
    assert minutes == Decimal("1.5000")
    assert billed == _OVERAGE * Decimal("1.5")

    async with tenant_session(tenant_id) as session:
        summary = await usage_summary(
            session, tenant_id=tenant_id, month=ist_billing_month(datetime.now(UTC))
        )
    assert summary["minutes_used"] == Decimal("1.50"), "the panel reads what the counter holds"
