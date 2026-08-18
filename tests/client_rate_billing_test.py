"""The client pays the CLIENT's price, and we stop paying ourselves our own cost.

THE DEFECT (P1.1). `pipeline._meter` called
`charge_for_call(..., amount_inr=cost.total_inr)`, and `cost.total_inr` is what the
ENGINE charges US — converted from USD cents by the Bolna adapter, roughly ₹2/min.
Meanwhile `self_serve_inr_per_min` (₹6.00) was read in exactly ONE place, and only to
render the "about N minutes left" runway string on the client's own screen.

So a self-serve wallet drained at about a third of the advertised rate and Calevate
booked **zero gross margin on the entire self-serve motion** — with `config.py` promising
in as many words that the runway framing and the top-up flow price from the same source
that the debit path never read.

Its twin, P1.3, is one layer up: `spend_state.spend_used` accumulated the same supplier
cost, and three things read it — the compliance gate's ceiling, the client's own cap
route, and the client usage panel. A client who capped at ₹5,000 was stopped at ₹5,000 of
OUR cost, and the figure explaining it to them was our supplier pricing on their screen.
`tests/money_walk_test.py` owns the panel half; this file owns the two WRITES.

WHY BOTH LIVE IN ONE FILE: they are one arithmetic reached from two call sites in the
same transaction, and their whole content is that the two agree. Split across two files,
a change to the rate would be able to move one and not the other.

`client_billed_inr` used to be that one arithmetic for BOTH motions. It is
`prepaid_billed_inr` now and answers for the prepaid one only: a managed month is priced
by `billing.service.priced_overage` — the same function the panel and the invoice use —
because the two rules diverged as soon as a plan quoted `overage_rate_value`
(`tests/two_rung_counter_agrees_test.py`). The managed assertions below therefore test
the month pricing rather than a per-call rate, which is what actually decides the bill.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from apps.api.billing.rates import PREPAID_TIERS, prepaid_billed_inr
from apps.api.billing.service import priced_overage
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.workers.pipeline import _meter
from sqlalchemy import text
from tests.spend_caps_test import _call_row, _plan, _snapshot, _spend_state, _tenant

#: One minute exactly, so every expected figure below is the rate itself and a reader can
#: check the arithmetic without a calculator.
_SIXTY_SECONDS = 60

#: Zero minutes, at the paise scale every figure in this module carries.
_ZERO = Decimal("0.00")

#: What the ENGINE charges us for that minute. Deliberately nothing like the client's
#: rate: if the two were close, every assertion here would pass under the old code.
_SUPPLIER_COST = "1.9000"


async def _set_tier(tenant_id: UUID, tier: str) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = :t WHERE id = :i"),
            {"t": tier, "i": tenant_id},
        )


async def _balance(tenant_id: UUID) -> Decimal:
    """What the wallet has actually moved by, from the ledger rather than from a helper.

    `credit_ledger` is append-only (hard rule 4) and `charge_for_call` writes one row per
    call keyed on `ref = call_id`, so summing `delta` is the whole truth about the debit
    and needs no second opinion.
    """
    async with tenant_session(tenant_id) as session:
        total = (
            await session.execute(
                text("SELECT COALESCE(SUM(delta), 0) FROM credit_ledger WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
        ).scalar()
    return Decimal(str(total))


async def _meter_one_minute(tenant_id: UUID, agent_id: UUID) -> None:
    call_id = await _call_row(tenant_id, agent_id)
    await _meter(
        tenant_id,
        call_id,
        _snapshot(seconds=_SIXTY_SECONDS, spend=_SUPPLIER_COST, ended=datetime.now(UTC)),
    )


# ============================================================================
# 1. The arithmetic, in isolation
# ============================================================================


def test_a_prepaid_minute_is_priced_at_the_list_rate_and_not_at_our_cost() -> None:
    """The one-line statement of P1.1."""
    assert prepaid_billed_inr(minutes=Decimal("10"), self_serve_rate=Decimal("6.00")) == Decimal(
        "60.0000"
    ), "the list price is a prepaid client's price"


def test_a_managed_month_is_priced_at_the_plans_overage_rate() -> None:
    """The managed half, asserted where the decision now lives: `priced_overage` prices
    the whole month, and the meter charges each call the difference it makes to it."""
    assert priced_overage(
        minutes_by_rung={"premium": Decimal("10.00"), "value": _ZERO, "": _ZERO},
        included_min=Decimal("0"),
        rate=Decimal("8.00"),
        rate_value=None,
    ).total_inr == Decimal("80.00")


def test_an_unpriced_managed_tenant_accrues_nothing_rather_than_a_made_up_price() -> None:
    """The deliberate refusal, and the one most likely to be "fixed" by someone who
    reads it as a bug.

    Nothing in this codebase creates a `plans` row, so a managed tenant with no quoted
    rate is a COMMON state and it is tempting to price them at the list rate so their
    cap has something to bite on. That was tried and rejected: the same rate prices the
    panel, the cap AND the invoice, and `b1d5c8e73f04` already settled that this
    repository does not invent a price a plan does not quote. A counter accruing ₹6/min
    beside an invoice charging ₹0 would be two documents about one month.

    `usage_summary` reads a NULL `overage_rate` as `Decimal("0")` and `_meter` does the
    same, so the refusal is spelled as a zero rate here — the value both readers hand in.
    """
    assert priced_overage(
        minutes_by_rung={"premium": Decimal("10.00"), "value": _ZERO, "": _ZERO},
        included_min=Decimal("0"),
        rate=Decimal("0"),
        rate_value=None,
    ).total_inr == Decimal("0.00")


def test_the_prepaid_tier_list_is_what_the_meter_branches_on() -> None:
    """A fourth prepaid tier added to `charge_for_call`'s branch and not to this constant
    would be a wallet that stops draining, silently. Named once, asserted here."""
    assert PREPAID_TIERS == ("self_serve", "trial")


# ============================================================================
# 2. The wallet (P1.1)
# ============================================================================


async def test_a_self_serve_wallet_is_debited_the_list_price_not_the_supplier_cost() -> None:
    """THE MARGIN, asserted as the difference between two numbers that used to be one.

    Before: the wallet moved by `cost.total_inr` (₹1.90 here), so a client who bought
    ₹600 of credit at ₹6.00/min got ~315 minutes instead of the 100 the runway string on
    their own screen promised them, and every one of those minutes earned nothing.
    """
    tenant_id, agent_id, _ = await _tenant("prepaidrate")
    await _set_tier(tenant_id, "self_serve")

    await _meter_one_minute(tenant_id, agent_id)

    rate = get_settings().self_serve_inr_per_min
    assert await _balance(tenant_id) == -rate, (
        "the wallet moved by something other than one minute at the list price"
    )
    assert await _balance(tenant_id) != -Decimal(_SUPPLIER_COST), (
        "the wallet is being debited our supplier cost again (P1.1) — margin is zero"
    )


async def test_a_managed_tenant_wallet_is_untouched() -> None:
    """The control, and the reason `PREPAID_TIERS` is a list rather than a `!=`: a
    managed client is invoiced against a retainer and their wallet must not move at all,
    at either price."""
    tenant_id, agent_id, _ = await _tenant("managedwallet")
    await _plan(tenant_id, included_min=0)

    await _meter_one_minute(tenant_id, agent_id)

    assert await _balance(tenant_id) == Decimal("0")


# ============================================================================
# 3. The counter (P1.3)
# ============================================================================


async def test_the_counter_holds_both_numbers_and_they_are_different() -> None:
    """`spend_used` is ours, `billed_inr` is theirs, and the whole finding is that they
    stopped being one column."""
    tenant_id, agent_id, _ = await _tenant("bothnumbers")
    await _plan(tenant_id, included_min=0)

    await _meter_one_minute(tenant_id, agent_id)

    _month, minutes, spend, _capped, billed = await _spend_state(tenant_id)
    assert minutes == Decimal("1.0000")
    assert spend == Decimal(_SUPPLIER_COST), "our cost must survive — the margin panel reads it"
    assert billed == Decimal("8.0000"), "one minute at the plan's overage rate"


async def test_the_included_allowance_is_spent_before_anything_is_billed() -> None:
    """A managed client's `billed_inr` is their OVERAGE, so the minutes they have already
    paid a retainer for accrue nothing.

    The increment is computed against the month's running total rather than per call, so
    the answer does not depend on the order calls happen to meter in: two minutes into a
    one-minute allowance bills exactly one minute, whether that is one two-minute call or
    two one-minute calls.
    """
    tenant_id, agent_id, _ = await _tenant("allowance")
    await _plan(tenant_id, included_min=1)

    await _meter_one_minute(tenant_id, agent_id)
    _m, _min, _spend, _capped, after_first = await _spend_state(tenant_id)
    assert after_first == Decimal("0.0000"), "the first minute is inside the allowance"

    await _meter_one_minute(tenant_id, agent_id)
    _m, minutes, _spend, _capped, after_second = await _spend_state(tenant_id)
    assert minutes == Decimal("2.0000")
    assert after_second == Decimal("8.0000"), "only the minute past the allowance is billed"


async def test_a_replayed_pipeline_bills_the_client_once() -> None:
    """Hard rule 4's property, restated for the column this change added.

    `_meter` returns early when `usage_events` already holds a row for the call — under
    `lock_call_writes`, so it is a claim rather than a hope — which means the second run
    reaches neither `charge_for_call` nor the `spend_state` upsert. That was already
    proven for the wallet; `billed_inr` is a new accumulator on the same path and would
    be the obvious place for a double-count to reappear.
    """
    tenant_id, agent_id, _ = await _tenant("replaybill")
    await _plan(tenant_id, included_min=0)
    call_id = await _call_row(tenant_id, agent_id)
    snapshot = _snapshot(seconds=_SIXTY_SECONDS, spend=_SUPPLIER_COST, ended=datetime.now(UTC))

    assert await _meter(tenant_id, call_id, snapshot) > 0
    assert await _meter(tenant_id, call_id, snapshot) == 0, "the replay must meter nothing"

    _m, minutes, _spend, _capped, billed = await _spend_state(tenant_id)
    assert minutes == Decimal("1.0000")
    assert billed == Decimal("8.0000"), "the replay billed the client a second time"


async def test_a_month_rollover_resets_the_clients_counter_with_ours() -> None:
    """A client's allowance does not carry into the next month, and neither does their
    accrued spend — the upsert resets all three counters together or none of them, and a
    `billed_inr` left accumulating would cap a client on a month they are not in."""
    tenant_id, agent_id, _ = await _tenant("rollbilled")
    await _plan(tenant_id, included_min=0)
    call_id = await _call_row(tenant_id, agent_id)
    last_month = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
    await _meter(tenant_id, call_id, _snapshot(seconds=120, spend=_SUPPLIER_COST, ended=last_month))
    _m, _min, _spend, _capped, before = await _spend_state(tenant_id)
    assert before == Decimal("16.0000")

    await _meter_one_minute(tenant_id, agent_id)

    month, minutes, _spend, _capped, after = await _spend_state(tenant_id)
    assert month != "2026-07"
    assert minutes == Decimal("1.0000"), "the minutes reset, so the rupees must too"
    assert after == Decimal("8.0000"), "last month's billed spend carried into this one"


async def test_the_recompute_uses_the_clients_column_too() -> None:
    """The THIRD writer of `capped`, and the one no other test could see.

    `billing/caps.py` has three writers — the meter's upsert, the client's own cap route
    and the ops recompute — and the last two both go through `recompute_capped`. The
    whole reason they share `over_cap_sql` is that they cannot disagree about what "over
    cap" means; that guarantee is about the EXPRESSION and says nothing about which
    COLUMN each of them feeds into it, which is exactly where this change could have
    left them split.

    Swapping `_RECOMPUTE_CAPPED` back to `spend_used` passes every other test in the
    suite, because their fixtures put both numbers on the same side of the ceiling. This
    one puts the cap BETWEEN them: ₹1.90 of supplier cost and ₹8.00 billed, capped at
    ₹5.00. Only the client's column crosses it.
    """
    from apps.api.billing.caps import apply_client_caps

    tenant_id, agent_id, _ = await _tenant("recomputecol")
    await _plan(tenant_id, included_min=0)
    await _meter_one_minute(tenant_id, agent_id)

    _month, _min, spend, _capped, billed = await _spend_state(tenant_id)
    assert spend < Decimal("5.00") < billed, "the fixture must straddle the cap to prove anything"

    async with tenant_session(tenant_id) as session:
        result = await apply_client_caps(
            session, tenant_id=tenant_id, cap_min=None, cap_spend=Decimal("5.00")
        )

    assert result.capped_now is True, (
        "the recompute compared the ceiling against our supplier cost — `_RECOMPUTE_CAPPED` "
        "and the meter's upsert are reading different columns (P1.3)"
    )
