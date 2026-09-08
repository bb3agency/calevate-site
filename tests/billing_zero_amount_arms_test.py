"""WHEN THERE IS NOTHING TO CHARGE, CHARGE NOTHING — and say nothing, in three places.

Three money surfaces have a guard in front of them for the same reason, and each guard is
a different KIND of "nothing":

1. `rates.prepaid_billed_inr` — nothing to price. Zero (or negative) minutes, or a rate
   this build could not resolve, must not be multiplied out: `-2 x ₹6` is a CREDIT to the
   client, arrived at by arithmetic nobody intended.
2. `service.record_usage_from_lots` — nothing consumed. A demand the lots answered with no
   splits must not append a ledger row: `credit_ledger` is append-only (hard rule 4), so a
   zero-delta `usage` row is permanent noise on the one artefact a client's bill is
   re-derived from, and `record_entry`'s own `allow_zero` default says the same thing from
   the other side.
3. `ops/config_routes._pct` — nothing to render. A rate with no defined margin publishes
   `null`, and `null` is NOT "0.00": zero margin means we sell at cost, and no margin means
   the question does not apply to that cell at all. A screen that prints "0.00%" for the
   second one reports a card in trouble that is not.

Run: uv run pytest -q tests/billing_zero_amount_arms_test.py
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing.lots import AiAssistDemand, CallDemand, LotDemand
from apps.api.billing.rates import (
    MONEY_Q,
    SELF_SERVE_COST_FLOOR_INR_PER_MIN,
    prepaid_billed_inr,
    rate_margin,
)
from apps.api.billing.service import LotRates, get_balance, record_usage_from_lots
from apps.api.db.session import tenant_session
from apps.api.ops.config_routes import _pct
from sqlalchemy import text

_FALLBACK = LotRates(Decimal("5.00"), Decimal("8.00"))


# --- 1: nothing to price ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("minutes", "rate"),
    [
        (Decimal("0"), Decimal("6.00")),
        (Decimal("-1.5"), Decimal("6.00")),
        (Decimal("10"), Decimal("0")),
        (Decimal("10"), Decimal("-6.00")),
    ],
)
def test_a_prepaid_charge_with_no_minutes_or_no_rate_is_zero_and_never_a_credit(
    minutes: Decimal, rate: Decimal
) -> None:
    """The multiplication is SKIPPED, not performed and then clamped.

    Two of these four would otherwise come back NEGATIVE — a debit that pays the client —
    and negative rupees reach the wallet as a credit nobody granted, on an append-only
    ledger where the correction is a second entry for ever.
    """
    charged = prepaid_billed_inr(minutes=minutes, self_serve_rate=rate)
    assert charged == Decimal("0")
    assert charged >= 0, "a charge is never a credit"
    # Quantized like every other figure this function returns, so a caller that formats the
    # result cannot get a bare "0" from one branch and "0.0000" from the other.
    assert charged.as_tuple().exponent == MONEY_Q.as_tuple().exponent
    assert str(charged) == "0.0000"


def test_a_prepaid_charge_with_real_minutes_and_a_real_rate_still_multiplies() -> None:
    """The guard's neighbour, asserted beside it: a guard that swallowed the ordinary case
    would pass every assertion above and bill nobody."""
    assert prepaid_billed_inr(minutes=Decimal("10"), self_serve_rate=Decimal("6.00")) == Decimal(
        "60.0000"
    )


# --- 2: nothing consumed ----------------------------------------------------------------


async def _tenant() -> uuid.UUID:
    created = await admin_service.create_organization(
        name="Zero Clinic",
        slug=f"zero-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id: uuid.UUID = created["id"]
    return tenant_id


@pytest.mark.parametrize(
    ("label", "demand"),
    [
        ("ai_assist", AiAssistDemand(credits=Decimal("0"))),
        ("call", CallDemand(minutes=Decimal("0"), voice_tier="sarvam", fallback_rates=_FALLBACK)),
    ],
)
async def test_a_demand_that_consumed_nothing_writes_no_ledger_row(
    label: str, demand: LotDemand
) -> None:
    """A dashboard-AI answer that cost nothing, and a call whose billable duration rounded
    to no minutes at all, both reach this writer.

    THE ASSERTION THAT MATTERS IS THE ABSENCE. `charged=False` is only the return value;
    what hard rule 4 cares about is that `credit_ledger` — INSERT-only, no UPDATE and no
    DELETE anywhere — did not acquire a permanent row recording that nothing happened.
    """
    tenant_id = await _tenant()
    ref = f"{label}:zero-{uuid.uuid4().hex[:8]}"

    async with tenant_session(tenant_id) as session:
        before = await get_balance(session, tenant_id=tenant_id)
        debit = await record_usage_from_lots(
            session, tenant_id=tenant_id, ref=ref, demand=demand, allow_negative=True
        )
        after = await get_balance(session, tenant_id=tenant_id)

    assert debit.charged is False
    assert debit.credits_inr == Decimal("0")
    assert debit.splits == [], "nothing was drawn, so there is nothing to attribute"
    assert after.amount_inr == before.amount_inr

    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT count(*) FROM credit_ledger WHERE tenant_id = :t AND ref = :r"),
                {"t": tenant_id, "r": ref},
            )
        ).scalar_one()
    assert rows == 0, "an append-only ledger never records a debit that took nothing"


# --- 3: nothing to render ----------------------------------------------------------------


def test_a_cell_with_no_defined_margin_publishes_null_and_not_a_zero() -> None:
    """`RateCardCellOut.gross_margin_pct` is `str | None`, and the two states are different
    facts. `rate_margin` leaves `margin` unset for a non-positive rate — a supplier cost
    cannot be expressed as a fraction of nothing — and this is the formatter that has to
    carry that through to the console instead of inventing a number for it.
    """
    verdict = rate_margin(Decimal("0"), cost=SELF_SERVE_COST_FLOOR_INR_PER_MIN)
    assert verdict.margin is None, "a rate of nothing has no margin to state"
    assert _pct(verdict.margin) is None
    assert _pct(None) is None
    # The ordinary arm, so "returns None" cannot pass by returning None for everything.
    assert _pct(Decimal("0.2")) == "20.00"
    assert _pct(Decimal("0")) == "0.00", "zero margin IS a number, and it is not null"
