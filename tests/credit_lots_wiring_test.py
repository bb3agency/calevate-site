"""Phase B2: every caller that moves credit now moves a LOT with it (D-547).

B1 built the FIFO engine and proved it in isolation (`credit_lots_fifo_test.py` and its
seven siblings). This suite is about the SEAM: that the wallet's callers — the post-call
meter, the Razorpay capture, the four admin credit routes and the dashboard-AI purchase —
each open, draw down or restate the right lot, in the transaction of the ledger row that
paid for it, and that plan §2.3 invariant 1 (`SUM(credits_remaining)` equals the balance)
survives every one of them.

The property under test is never "the number is right" alone: it is that the LEDGER ROW
and the LOTS agree, because the two disagreeing is the failure the whole design exists to
make impossible and it is invisible on any single screen.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from uuid import UUID

import pytest
from apps.api.billing import service as billing
from apps.api.billing.lots import AiAssistDemand, CallDemand, read_open_lots, voice_tier_rates
from apps.api.billing.service import (
    apply_credit_to_lots,
    charge_for_call,
    get_balance,
    granted_lot_rates,
    lot_of_entry,
    lot_rates_for_amount,
    lot_rates_for_purchase,
    record_entry,
    remove_credit_from_lots,
)
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from sqlalchemy import text
from tests.credit_lots_helpers import GROWTH, PLUS, add_lot, credit_entry, lot_rows, make_tenant


async def _balance(tenant_id: UUID) -> Decimal:
    async with tenant_session(tenant_id) as session:
        return (await get_balance(session, tenant_id=tenant_id)).amount_inr


async def _usage_meta(tenant_id: UUID, ref: str) -> dict:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT delta, meta FROM credit_ledger WHERE tenant_id = :t AND ref = :r "
                    "AND reason = 'usage'"
                ),
                {"t": tenant_id, "r": ref},
            )
        ).one()
    return {"delta": Decimal(str(row[0])), "meta": row[1]}


async def _open_remaining(tenant_id: UUID) -> Decimal:
    async with tenant_session(tenant_id) as session:
        return sum(
            (lot.credits_remaining for lot in await read_open_lots(session, tenant_id=tenant_id)),
            Decimal("0"),
        )


# --- the debit: FIFO, two rates, one row ----------------------------------------


async def test_a_call_splits_across_two_lots_and_each_part_is_priced_at_its_own_lot() -> None:
    """The worked example from the plan's definition of done, driven through the seam.

    ₹100 left of a ₹15,000 pack (₹4.70/min) with a ₹2,000 pack (₹5.00/min) behind it, and
    a 30-minute call. The first lot pays for 21.276595 minutes and stops; the rest is
    charged at the SECOND lot's rate. One `usage` row, two splits, and the row's delta is
    the sum of them — which is the invariant every statement is re-derived from.
    """
    tenant_id = await make_tenant()
    await add_lot(tenant_id, credits_inr="100.00", rates=PLUS, pack_id="plus")
    await add_lot(tenant_id, credits_inr="500.00", rates=GROWTH, pack_id="growth")
    call_id = uuid.uuid4()

    async with tenant_session(tenant_id) as session:
        charged = await charge_for_call(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            demand=CallDemand(
                minutes=Decimal("30"),
                voice_tier="sarvam",
                fallback_inr_per_min=Decimal("5.00"),
            ),
        )

    row = await _usage_meta(tenant_id, str(call_id))
    splits = row["meta"]["lots"]
    assert [s["inr_per_min"] for s in splits] == ["4.7000", "5.0000"]
    assert [s["kind"] for s in splits] == ["call", "call"]
    assert [s["voice_tier"] for s in splits] == ["sarvam", "sarvam"]
    # The first lot is spent to the paisa; the remainder is priced at the second's rate.
    assert splits[0]["credits"] == "100.0000"
    assert Decimal(splits[1]["credits"]) == (
        Decimal("30") - Decimal("100.00") / Decimal("4.70")
    ).quantize(Decimal("0.0001")) * Decimal("5.00")
    assert row["delta"] == -charged
    assert charged == sum(Decimal(s["credits"]) for s in splits)
    # Invariant §2.3.1 — the lots and the balance are one statement about one wallet.
    assert await _open_remaining(tenant_id) == await _balance(tenant_id)


async def test_a_cartesia_call_is_priced_at_the_lots_cartesia_column() -> None:
    """The same lot, the other voice: the tier chooses the COLUMN, nothing else moves."""
    tenant_id = await make_tenant()
    await add_lot(tenant_id, credits_inr="1000.00", rates=GROWTH)
    call_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        charged = await charge_for_call(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            demand=CallDemand(
                minutes=Decimal("10"),
                voice_tier="cartesia",
                fallback_inr_per_min=Decimal("5.00"),
            ),
        )
    assert charged == Decimal("70.0000")  # 10 x the growth pack's ₹7.00 Cartesia rate
    splits = (await _usage_meta(tenant_id, str(call_id)))["meta"]["lots"]
    assert splits[0]["voice_tier"] == "cartesia"
    assert splits[0]["inr_per_min"] == "7.0000"


async def test_the_overdraft_is_priced_at_the_lot_that_ran_out() -> None:
    """Plan §0 Q5. ₹10 of a ₹5.00/min lot buys two minutes; the other eight are still
    charged at ₹5.00 and the wallet goes negative, because the call already happened."""
    tenant_id = await make_tenant()
    await add_lot(tenant_id, credits_inr="10.00", rates=GROWTH)
    call_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        charged = await charge_for_call(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            demand=CallDemand(
                minutes=Decimal("10"),
                voice_tier="sarvam",
                # A DIFFERENT fallback, so a test that passed by reading the fallback
                # instead of the exhausted lot's own rate would be visible.
                fallback_inr_per_min=Decimal("99.00"),
            ),
        )
    assert charged == Decimal("50.0000")
    splits = (await _usage_meta(tenant_id, str(call_id)))["meta"]["lots"]
    assert [s.get("lot_id") is None for s in splits] == [False, True]
    assert splits[1]["inr_per_min"] == "5.0000", "the overdraft takes the exhausted lot's rate"
    assert await _balance(tenant_id) == Decimal("-40.0000")
    assert await _open_remaining(tenant_id) == Decimal("0")


async def test_a_wallet_with_no_lots_at_all_is_priced_at_the_callers_fallback() -> None:
    """The other arm of the same rule: no lot ever existed, so there is no rate to
    inherit and the month's list price is what prices the minutes."""
    tenant_id = await make_tenant()
    call_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        charged = await charge_for_call(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            demand=CallDemand(
                minutes=Decimal("4"),
                voice_tier="sarvam",
                fallback_inr_per_min=Decimal("6.00"),
            ),
        )
    assert charged == Decimal("24.0000")
    splits = (await _usage_meta(tenant_id, str(call_id)))["meta"]["lots"]
    assert splits == [
        {
            "kind": "call",
            "credits": "24.0000",
            "minutes": "4.0000",
            "inr_per_min": "6.00",
            "voice_tier": "sarvam",
        }
    ]


async def test_a_replayed_call_consumes_nothing_a_second_time() -> None:
    """The idempotency guard is the whole reason `consume` runs behind the ledger lookup:
    a second consumption would be silent, permanent and invisible on an append-only row."""
    tenant_id = await make_tenant()
    await add_lot(tenant_id, credits_inr="500.00", rates=GROWTH)
    call_id = uuid.uuid4()
    demand = CallDemand(
        minutes=Decimal("10"), voice_tier="sarvam", fallback_inr_per_min=Decimal("5.00")
    )
    async with tenant_session(tenant_id) as session:
        first = await charge_for_call(session, tenant_id=tenant_id, call_id=call_id, demand=demand)
    async with tenant_session(tenant_id) as session:
        second = await charge_for_call(session, tenant_id=tenant_id, call_id=call_id, demand=demand)
    assert (first, second) == (Decimal("50.0000"), Decimal("0"))
    assert await _open_remaining(tenant_id) == Decimal("450.0000")


async def test_a_call_that_demands_nothing_writes_no_row() -> None:
    """A zero-length call and a negative one both stop before the lock — there is nothing
    to charge, and a ₹0 ledger row is noise on a statement a client reads per entry."""
    tenant_id = await make_tenant()
    await add_lot(tenant_id, credits_inr="500.00", rates=GROWTH)
    async with tenant_session(tenant_id) as session:
        assert await charge_for_call(
            session,
            tenant_id=tenant_id,
            call_id=uuid.uuid4(),
            demand=CallDemand(
                minutes=Decimal("0"), voice_tier="sarvam", fallback_inr_per_min=Decimal("5")
            ),
        ) == Decimal("0")
    assert await _open_remaining(tenant_id) == Decimal("500.0000")


async def test_the_model_surcharge_rides_the_same_row_as_an_ai_assist_split() -> None:
    """D-455's upgrade is rupees, not minutes — so it lands as an `ai_assist` split.

    Its minutes are the call's own and are already counted by the call splits; a second
    `call` split carrying them would double the month's talk time on every reader that
    sums `kind == "call"` (plan ADDENDUM 2 §2.1 is that rule, and this is the case it was
    written for).
    """
    tenant_id = await make_tenant()
    await add_lot(tenant_id, credits_inr="500.00", rates=GROWTH)
    call_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        charged = await charge_for_call(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            demand=CallDemand(
                minutes=Decimal("10"),
                voice_tier="sarvam",
                fallback_inr_per_min=Decimal("5.00"),
            ),
            extra_inr=Decimal("2.50"),
        )
    assert charged == Decimal("52.5000")
    splits = (await _usage_meta(tenant_id, str(call_id)))["meta"]["lots"]
    assert [s["kind"] for s in splits] == ["call", "ai_assist"]
    assert splits[1] == {
        "kind": "ai_assist",
        "credits": "2.5000",
        "lot_id": splits[0]["lot_id"],
    }
    assert sum(Decimal(s["minutes"]) for s in splits if s["kind"] == "call") == Decimal("10.0000")


# --- the credit side: repayment first, then the lot -------------------------------


async def test_a_topup_repays_the_overdraft_before_it_opens_a_lot() -> None:
    """Plan §0 Q5's second half. ₹500 onto a wallet at -₹200 opens a lot of ₹300: the
    overdraft minutes were already spoken and already priced, and they are not re-sold."""
    tenant_id = await make_tenant()
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("-200"),
            reason="usage",
            ref=str(uuid.uuid4()),
            allow_negative=True,
        )
    entry_id = await credit_entry(tenant_id, amount="500.00")
    async with tenant_session(tenant_id) as session:
        credited = await apply_credit_to_lots(
            session,
            tenant_id=tenant_id,
            credits_inr=Decimal("500.00"),
            balance_after=Decimal("300.00"),
            rates=billing.LotRates(Decimal("5.00"), Decimal("8.00")),
            source="topup",
            pack_id=None,
            ledger_entry_id=entry_id,
        )
    assert credited.repaid_overdraft_inr == Decimal("200")
    assert credited.credits_inr == Decimal("300.0000")
    assert await _open_remaining(tenant_id) == await _balance(tenant_id) == Decimal("300.0000")


async def test_a_topup_wholly_absorbed_by_an_overdraft_opens_no_lot_at_all() -> None:
    """The boundary of the same rule: every rupee went to the debt, so there is no
    calling time to sell and a lot of ₹0 is a row the CHECK would refuse anyway."""
    tenant_id = await make_tenant()
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("-500"),
            reason="usage",
            ref=str(uuid.uuid4()),
            allow_negative=True,
        )
    entry_id = await credit_entry(tenant_id, amount="300.00")
    async with tenant_session(tenant_id) as session:
        credited = await apply_credit_to_lots(
            session,
            tenant_id=tenant_id,
            credits_inr=Decimal("300.00"),
            balance_after=Decimal("-200.00"),
            rates=billing.LotRates(Decimal("5.00"), Decimal("8.00")),
            source="topup",
            pack_id=None,
            ledger_entry_id=entry_id,
        )
    assert credited.lot_id is None
    assert credited.repaid_overdraft_inr == Decimal("300.00")
    assert await lot_rows(tenant_id) == []


# --- which rates a purchase freezes (plan §0 Q3 / Q4) -----------------------------


def test_a_free_amount_takes_the_largest_pack_it_could_have_bought() -> None:
    """₹6,000 buys no pack, but it is more than the ₹5,000 rung — so it is sold at that
    rung's rates. Monotone, and it punishes nobody for topping up between the rungs."""
    assert lot_rates_for_amount(Decimal("6000")) == billing.LotRates(
        Decimal("5.00"), Decimal("7.00")
    )


def test_a_free_amount_below_the_first_rung_takes_the_list_rates() -> None:
    """₹500 affords no pack at all. The smallest pack's rates are the floor, which is the
    only answer that is neither a gift nor a punishment."""
    assert lot_rates_for_amount(Decimal("500")) == billing.LotRates(
        Decimal("5.00"), Decimal("8.00")
    )


def test_a_purchase_naming_a_pack_takes_that_packs_rates() -> None:
    assert lot_rates_for_purchase(pack_id="max", amount_inr=Decimal("50000")) == billing.LotRates(
        Decimal("4.50"), Decimal("6.00")
    )


def test_a_purchase_naming_a_pack_this_build_no_longer_offers_falls_to_the_amount() -> None:
    """The money arrived either way, so an unknown pack id is not a failure — it is a
    purchase whose rates come from what was paid (`credit_captured_payment` takes the
    same reading of an unknown pack for the same reason)."""
    assert lot_rates_for_purchase(
        pack_id="retired-pack", amount_inr=Decimal("6000")
    ) == billing.LotRates(Decimal("5.00"), Decimal("7.00"))


def test_a_gift_is_spent_at_the_list_price() -> None:
    """Plan §0 Q4: otherwise a ₹50,000 grant would buy a cheaper minute than a ₹50,000
    purchase, and the card would be a suggestion."""
    assert granted_lot_rates() == billing.LotRates(Decimal("5.00"), Decimal("8.00"))


# --- corrections ------------------------------------------------------------------


async def test_a_partial_correction_restates_the_lot_and_leaves_its_rates_alone() -> None:
    """ADDENDUM 2 §2.2. ₹1,000 taken back off a ₹5,000 purchase with ₹5,000 left: the
    lot is worth ₹4,000 and still sells a ₹5.00 minute, because what was sold at ₹5.00
    was sold at ₹5.00 even when the amount was wrong."""
    tenant_id = await make_tenant()
    entry_id = await credit_entry(tenant_id, amount="5000.00")
    async with tenant_session(tenant_id) as session:
        await apply_credit_to_lots(
            session,
            tenant_id=tenant_id,
            credits_inr=Decimal("5000.00"),
            balance_after=Decimal("5000.00"),
            rates=billing.LotRates(*GROWTH),
            source="topup",
            pack_id="growth",
            ledger_entry_id=entry_id,
        )
        assert (
            await remove_credit_from_lots(
                session,
                tenant_id=tenant_id,
                corrected_entry_id=entry_id,
                amount_inr=Decimal("1000"),
            )
            == []
        )
    (lot,) = await lot_rows(tenant_id)
    assert (lot["credits_total"], lot["credits_remaining"]) == (
        Decimal("4000.0000"),
        Decimal("4000.0000"),
    )
    assert lot["sarvam_inr_per_min"] == Decimal("5.0000")


async def test_a_correction_bigger_than_what_is_left_floors_the_lot_and_overdraws() -> None:
    """The worked example in ADDENDUM 2 §2.2: recorded ₹10,000, the bank moved ₹8,000,
    the client has already spent ₹9,000. The lot cannot go below zero, so the shortfall
    is wallet overdraft — which the next purchase repays before it opens its own lot."""
    tenant_id = await make_tenant()
    entry_id = await credit_entry(tenant_id, amount="10000.00")
    async with tenant_session(tenant_id) as session:
        await apply_credit_to_lots(
            session,
            tenant_id=tenant_id,
            credits_inr=Decimal("10000.00"),
            balance_after=Decimal("10000.00"),
            rates=billing.LotRates(*GROWTH),
            source="topup",
            pack_id="growth",
            ledger_entry_id=entry_id,
        )
        await charge_for_call(
            session,
            tenant_id=tenant_id,
            call_id=uuid.uuid4(),
            demand=CallDemand(
                minutes=Decimal("1800"),
                voice_tier="sarvam",
                fallback_inr_per_min=Decimal("5.00"),
            ),
        )
        await remove_credit_from_lots(
            session, tenant_id=tenant_id, corrected_entry_id=entry_id, amount_inr=Decimal("2000")
        )
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("-2000"),
            reason="adjustment",
            ref=f"adjust:{entry_id}:2000.00",
            allow_negative=True,
        )
    (lot,) = await lot_rows(tenant_id)
    assert lot["credits_total"] == Decimal("8000.0000")
    assert lot["credits_remaining"] == Decimal("0.0000")
    assert lot["closed_at"] is not None
    assert await _balance(tenant_id) == Decimal("-1000.0000")


async def test_a_full_reversal_spends_the_queue_because_a_lot_may_not_reach_zero_total() -> None:
    """`credits_total > 0` is a CHECK, so a purchase reversed IN FULL cannot be restated
    to nothing — and that is the headline case of the adjustment route ("₹50,000 to the
    wrong client"). The credit comes off the queue at face value instead, which drains the
    same lot and keeps the balance and the lots one statement."""
    tenant_id = await make_tenant()
    entry_id = await credit_entry(tenant_id, amount="5000.00")
    async with tenant_session(tenant_id) as session:
        await apply_credit_to_lots(
            session,
            tenant_id=tenant_id,
            credits_inr=Decimal("5000.00"),
            balance_after=Decimal("5000.00"),
            rates=billing.LotRates(*GROWTH),
            source="topup",
            pack_id="growth",
            ledger_entry_id=entry_id,
        )
        splits = await remove_credit_from_lots(
            session, tenant_id=tenant_id, corrected_entry_id=entry_id, amount_inr=Decimal("5000")
        )
    assert [s.kind for s in splits] == ["ai_assist"]
    assert await _open_remaining(tenant_id) == Decimal("0")


async def test_a_correction_of_an_entry_that_opened_no_lot_spends_the_queue() -> None:
    """A credit written before lots existed — the migration's own case — has no lot to
    restate, so the correction is spent oldest-first like any other debit. Without this
    arm the lots would hold credit the balance no longer says is there."""
    tenant_id = await make_tenant()
    await add_lot(tenant_id, credits_inr="1000.00", rates=GROWTH)
    lotless = await credit_entry(tenant_id, amount="400.00")
    async with tenant_session(tenant_id) as session:
        assert await lot_of_entry(session, ledger_entry_id=lotless) is None
        splits = await remove_credit_from_lots(
            session, tenant_id=tenant_id, corrected_entry_id=lotless, amount_inr=Decimal("400")
        )
    assert [s.credits for s in splits] == [Decimal("400.00")]
    assert await _open_remaining(tenant_id) == Decimal("600.0000")


# --- the dashboard-AI debit (plan §4.B.7) ------------------------------------------


async def test_an_ai_assist_debit_carries_no_rate_and_no_voice() -> None:
    """Face value, ₹1 = 1 credit. The absent keys are the assertion: a `null` voice_tier
    is the tri-state a reader has to interpret, and ADDENDUM 2 §2.1 refuses one."""
    tenant_id = await make_tenant()
    await add_lot(tenant_id, credits_inr="500.00", rates=GROWTH)
    async with tenant_session(tenant_id) as session:
        debit = await billing.record_usage_from_lots(
            session,
            tenant_id=tenant_id,
            ref="ai:2026-09",
            demand=AiAssistDemand(credits=Decimal("120.00")),
            meta={"kind": "ai_overage"},
        )
    assert debit.credits_inr == Decimal("120.00")
    row = await _usage_meta(tenant_id, "ai:2026-09")
    assert row["meta"]["kind"] == "ai_overage"
    (split,) = row["meta"]["lots"]
    assert set(split) == {"kind", "credits", "lot_id"}
    assert split["kind"] == "ai_assist"


async def test_a_purchase_the_wallet_cannot_afford_refuses_and_consumes_nothing() -> None:
    """`allow_negative=False` is what separates a PURCHASE from the record of a cost
    already incurred. The lot decrements are in the same transaction as the ledger row, so
    a refusal takes them with it — this proves the rollback rather than assuming it."""
    tenant_id = await make_tenant()
    await add_lot(tenant_id, credits_inr="50.00", rates=GROWTH)
    with pytest.raises(ProblemError) as raised:
        async with tenant_session(tenant_id) as session:
            await billing.record_usage_from_lots(
                session,
                tenant_id=tenant_id,
                ref="ai:2026-10",
                demand=AiAssistDemand(credits=Decimal("500.00")),
                allow_negative=False,
            )
    assert raised.value.code == "insufficient_credits"
    assert await _open_remaining(tenant_id) == Decimal("50.0000")


# --- what the picker is shown -----------------------------------------------------


async def test_the_picker_reads_the_oldest_open_lot_and_counts_what_is_behind_it() -> None:
    """The rate a client is shown before choosing a voice must be the rate their next
    call is charged, which is the oldest OPEN lot's — not the card's."""
    tenant_id = await make_tenant()
    await add_lot(tenant_id, credits_inr="100.00", rates=PLUS, pack_id="plus")
    await add_lot(tenant_id, credits_inr="200.00", rates=GROWTH, pack_id="growth")
    async with tenant_session(tenant_id) as session:
        tiers = await voice_tier_rates(session, tenant_id=tenant_id)
    assert [(t.provider, t.inr_per_min, t.further_open_lots) for t in tiers] == [
        ("sarvam", Decimal("4.7000"), 1),
        ("cartesia", Decimal("6.5000"), 1),
    ]


async def test_the_picker_says_nothing_rather_than_quoting_a_card_it_has_not_sold() -> None:
    """An empty wallet has no rate to quote. `None` is the answer; a card figure would be
    a guess about what the client's next purchase will cost."""
    tenant_id = await make_tenant()
    async with tenant_session(tenant_id) as session:
        tiers = await voice_tier_rates(session, tenant_id=tenant_id)
    assert [(t.provider, t.inr_per_min, t.further_open_lots) for t in tiers] == [
        ("sarvam", None, 0),
        ("cartesia", None, 0),
    ]


# --- what a month's panel says each voice cost (plan §4.D.4) ----------------------


async def test_a_month_splits_its_minutes_and_charges_by_the_voice_that_spoke() -> None:
    """The panel's per-voice figures come out of `meta.lots`, which is the whole reason
    the splits are written: the charges are the rupees actually taken off the wallet, not
    minutes re-multiplied by a rate, so the panel and the ledger cannot disagree.

    The `ai_assist` split on the second call is deliberately there — a D-455 surcharge
    rides a call's own row — and must NOT reach either voice's minutes, because those
    minutes are already counted by the call split beside it.
    """
    tenant_id = await make_tenant()
    await add_lot(tenant_id, credits_inr="10000.00", rates=GROWTH)
    async with tenant_session(tenant_id) as session:
        await charge_for_call(
            session,
            tenant_id=tenant_id,
            call_id=uuid.uuid4(),
            demand=CallDemand(
                minutes=Decimal("10"),
                voice_tier="sarvam",
                fallback_inr_per_min=Decimal("5.00"),
            ),
        )
        await charge_for_call(
            session,
            tenant_id=tenant_id,
            call_id=uuid.uuid4(),
            demand=CallDemand(
                minutes=Decimal("4"),
                voice_tier="cartesia",
                fallback_inr_per_min=Decimal("5.00"),
            ),
            extra_inr=Decimal("9.00"),
        )
        month = billing.current_billing_month()
        voices = await billing.voice_tier_usage(session, tenant_id=tenant_id, month=month)
    assert voices["sarvam"].minutes == Decimal("10.0000")
    assert voices["sarvam"].charged_inr == Decimal("50.0000")
    assert voices["cartesia"].minutes == Decimal("4.0000")
    # 4 x ₹7.00 — the surcharge is NOT in it.
    assert voices["cartesia"].charged_inr == Decimal("28.0000")


async def test_a_wallet_that_spoke_nothing_reports_both_voices_at_zero() -> None:
    """A tier that is absent from the answer and a tier that was not used are the same
    screen, so both are always present. A MANAGED tenant reads this too: they take no
    wallet debit at all, which is not a gap."""
    tenant_id = await make_tenant()
    async with tenant_session(tenant_id) as session:
        voices = await billing.voice_tier_usage(
            session, tenant_id=tenant_id, month=billing.current_billing_month()
        )
    assert {tier: (v.minutes, v.charged_inr) for tier, v in voices.items()} == {
        "sarvam": (Decimal("0"), Decimal("0")),
        "cartesia": (Decimal("0"), Decimal("0")),
    }
