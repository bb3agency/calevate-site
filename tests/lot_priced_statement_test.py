"""A prepaid statement is the LEDGER, not minutes re-multiplied by a list rate (D-547).

THE DEFECT, in one sentence: since lots, a wallet is a QUEUE of purchases each frozen at
the two rates it was sold at — and three surfaces went on pricing a month as
`list_rate x minutes`, which is the right answer for exactly one client (one who bought the
smallest pack and never chose the dearer voice) and wrong for everybody else.

* `usage_summary`'s CLOSED-month `spend_used_inr` and its `month_charges_inr`;
* the admin margin panel's revenue (`margin_for_tenant`);
* `attribution.period_charge`, whose residual is then measured against a total the ledger
  never charged.

Meanwhile the meter charged the SUM OF THE SPLITS. So `UsageTab` rendered the per-voice
charges out of `meta.lots` beside a total derived from a rate, ON THE SAME SCREEN, and they
disagreed for every non-starter wallet — and the same month changed value at IST rollover,
because the open month read the live counter (fed from the lots) and the closed one
re-derived.

THE FIX is that `calling_revenue_inr` takes the splits' sum. `SUM(meta.lots[].credits)` is
the row's own delta by construction (invariant §2.3.5), so the statement, the margin panel
and the itemisation now divide the rupees the wallet was actually debited.

TWO MORE MONEY FIXES ARE PINNED HERE because they live on the same seam:

* **the fallback is a PAIR** — one number cannot price two voices, and the one number it
  was is the SARVAM list price, so a Studio minute on a wallet with no open lot was debited
  at ₹5.00 against a card that sells it at ₹8.00 (cost floor ₹4.36);
* **a lot takes its rates from the dated CARD**, not from the `PACK_CATALOGUE` constant, so
  a card recorded in the ops console is no longer inert.

Run: uv run pytest -q tests/lot_priced_statement_test.py
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from apps.api.billing import service as billing
from apps.api.billing.list_rates import PACK_RATE_KEY_PREFIX, pack_rate_key
from apps.api.billing.lots import AiAssistDemand, CallDemand, consume, credits_of, split_meta
from apps.api.billing.service import (
    LotRates,
    apply_credit_to_lots,
    calling_revenue_inr,
    charge_for_call,
    margin_for_tenant,
    rate_card_at,
    record_entry,
    to_paise,
    usage_summary,
)
from apps.api.core.settings import Settings
from apps.api.db.session import tenant_session, untenanted_session
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from tests.credit_lots_helpers import PLUS, credit_entry, make_tenant

#: The ₹15,000 rung: ₹4.70 Sarvam, ₹6.50 Cartesia. Chosen because BOTH differ from the
#: ₹5.00 list price, so a figure derived from the list rate can never coincide with the
#: ledger's by luck.
PLUS_SARVAM, PLUS_CARTESIA = PLUS

#: The list card's own rates (the smallest pack), which is what a wallet with no lot pays.
LIST_SARVAM, LIST_CARTESIA = Decimal("5.00"), Decimal("8.00")


async def _prepaid(tenant_id: UUID) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = 'self_serve' WHERE id = :i"),
            {"i": tenant_id},
        )


async def _metered_call(session: AsyncSession, *, tenant_id: UUID, minutes: Decimal) -> UUID:
    """A completed call and the `usage_events` row the meter writes for it.

    The row is not decoration: `service._CALL_IN_MONTH` reads a debit's month off it rather
    than off the ledger row's own `occurred_at`, because `record_entry` stamps the moment of
    the INSERT and a LATE-SETTLING call's debit lands in the next month. It is also where
    `minutes_used` comes from, so the charges and the minutes printed beside them are
    counted over one window by construction.
    """
    call_id = uuid.uuid4()
    agent_id = (
        await session.execute(
            text("SELECT id FROM agents WHERE tenant_id = :t LIMIT 1"), {"t": tenant_id}
        )
    ).scalar_one()
    await session.execute(
        text(
            "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
            "status, created_at, updated_at) VALUES (:i, :t, :a, :e, 'outbound', "
            "'+919876500001', 'completed', now(), now())"
        ),
        {"i": call_id, "t": tenant_id, "a": agent_id, "e": f"exec_{uuid.uuid4().hex[:12]}"},
    )
    await session.execute(
        text(
            "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
            "unit_cost_paid, occurred_at, meta, created_at) VALUES (gen_random_uuid(), :tid, "
            ":cid, 'telephony_s', :qty, '0.0100', now(), CAST(:meta AS jsonb), now())"
        ),
        {
            "tid": tenant_id,
            "cid": call_id,
            "qty": minutes * 60,
            "meta": '{"tts_tier": "premium"}',
        },
    )
    return call_id


async def _wallet_at_the_plus_rung(minutes: Decimal) -> tuple[UUID, Decimal]:
    """A prepaid wallet holding one ₹15,000-rung lot, and one call charged out of it.

    Returns the tenant and what the WALLET was actually debited — the figure every
    assertion below is against.
    """
    tenant_id = await make_tenant()
    await _prepaid(tenant_id)
    entry = await credit_entry(tenant_id, amount="15000.00")
    async with tenant_session(tenant_id) as session:
        await apply_credit_to_lots(
            session,
            tenant_id=tenant_id,
            credits_inr=Decimal("15000.00"),
            balance_after=Decimal("15000.00"),
            rates=LotRates(PLUS_SARVAM, PLUS_CARTESIA),
            source="topup",
            pack_id="plus",
            ledger_entry_id=entry,
        )
        call_id = await _metered_call(session, tenant_id=tenant_id, minutes=minutes)
        charged = await charge_for_call(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            demand=CallDemand(
                minutes=minutes,
                voice_tier="sarvam",
                fallback_rates=LotRates(LIST_SARVAM, LIST_CARTESIA),
            ),
        )
    return tenant_id, charged


# --- HIGH 1: every surface prices the month from the ledger -----------------------


async def test_the_statement_reports_what_the_wallet_was_charged_not_the_list_rate() -> None:
    """40 minutes on the ₹15,000 rung is ₹188.00, not the ₹200.00 the list price gives.

    A 6.4% overstatement on the client's own screen, beside per-voice figures that already
    said ₹188.00 — the two disagreeing on one panel is the failure this whole design exists
    to make impossible.
    """
    tenant_id, charged = await _wallet_at_the_plus_rung(Decimal("40"))
    assert charged == Decimal("188.0000"), "40 x ₹4.70, off the lot"

    async with tenant_session(tenant_id) as session:
        summary = await usage_summary(session, tenant_id=tenant_id)

    at_the_list_rate = to_paise(Decimal("40") * LIST_SARVAM)
    assert at_the_list_rate == Decimal("200.00"), "the figure the defect published"
    assert summary["month_charges_inr"] == to_paise(charged)
    assert summary["month_charges_inr"] != at_the_list_rate
    # And the per-voice pair the same screen renders adds to it exactly, which is the
    # property that used to fail.
    assert summary["sarvam_charges_inr"] == to_paise(charged)
    assert summary["cartesia_charges_inr"] == Decimal("0.00")


async def test_a_closed_month_reports_the_ledger_too_so_the_month_does_not_move_at_rollover() -> (
    None
):
    """`spend_used_inr` reads the live counter while a month is open and this figure once
    it closes. Both are now the same arithmetic — the meter fed the counter from the lots —
    so a month cannot change value at 00:00 IST on the 1st."""
    tenant_id, charged = await _wallet_at_the_plus_rung(Decimal("40"))
    # A month that is NOT today's takes `_spend_used`'s closed branch. The call's usage row
    # is stamped now, so this window holds nothing and the honest answer is ₹0.00 — what
    # matters is WHICH arithmetic answered, and the open month below proves it.
    async with tenant_session(tenant_id) as session:
        closed = await usage_summary(session, tenant_id=tenant_id, month="2020-01")
        open_month = await usage_summary(session, tenant_id=tenant_id)
    assert closed["spend_used_inr"] == Decimal("0.00")
    assert closed["minutes_used"] == Decimal("0.00"), "and no minutes either — one window"
    assert open_month["month_charges_inr"] == to_paise(charged)


async def test_the_margin_panel_books_the_revenue_the_ledger_recorded() -> None:
    """Revenue and what the client owes are one number seen from two sides. The panel
    overstated it by the same 6.4% and reported a margin nobody was ever charged."""
    tenant_id, charged = await _wallet_at_the_plus_rung(Decimal("40"))
    async with tenant_session(tenant_id) as session:
        margin = await margin_for_tenant(session, tenant_id=tenant_id)
    assert margin["revenue_inr"] == to_paise(charged)
    assert margin["revenue_inr"] != to_paise(Decimal("40") * LIST_SARVAM)


async def test_the_model_surcharge_is_in_the_calling_total_and_in_neither_voice() -> None:
    """A D-455 surcharge rides the CALL's own row as an `ai_assist` split, because its
    minutes are already counted by the call split beside it (ADDENDUM 2 §2.1). It is
    revenue for calling, so it belongs in the total — and in neither voice's charge, or the
    panel would say a client spoke minutes they did not."""
    tenant_id = await make_tenant()
    await _prepaid(tenant_id)
    entry = await credit_entry(tenant_id, amount="15000.00")
    async with tenant_session(tenant_id) as session:
        await apply_credit_to_lots(
            session,
            tenant_id=tenant_id,
            credits_inr=Decimal("15000.00"),
            balance_after=Decimal("15000.00"),
            rates=LotRates(PLUS_SARVAM, PLUS_CARTESIA),
            source="topup",
            pack_id="plus",
            ledger_entry_id=entry,
        )
        call_id = await _metered_call(session, tenant_id=tenant_id, minutes=Decimal("40"))
        await charge_for_call(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            demand=CallDemand(
                minutes=Decimal("40"),
                voice_tier="sarvam",
                fallback_rates=LotRates(LIST_SARVAM, LIST_CARTESIA),
            ),
            extra_inr=Decimal("12.00"),
        )
        charges = await billing.voice_tier_usage(
            session, tenant_id=tenant_id, month=billing.current_billing_month()
        )
    assert charges.by_voice["sarvam"].charged_inr == Decimal("188.0000")
    assert charges.extra_inr == Decimal("12.00")
    assert charges.total_inr == Decimal("200.0000")


async def test_a_dashboard_ai_block_is_not_charged_as_calling() -> None:
    """The copilot's own debit is an `ai_assist` split on a row of its OWN, with no call
    split beside it. Summing every `ai_assist` split would bill the copilot under the
    heading of the client's phone calls — which is neither what the panel says nor what
    `calling_revenue_inr` has ever meant."""
    tenant_id = await make_tenant()
    await _prepaid(tenant_id)
    entry = await credit_entry(tenant_id, amount="15000.00")
    async with tenant_session(tenant_id) as session:
        await apply_credit_to_lots(
            session,
            tenant_id=tenant_id,
            credits_inr=Decimal("15000.00"),
            balance_after=Decimal("15000.00"),
            rates=LotRates(PLUS_SARVAM, PLUS_CARTESIA),
            source="topup",
            pack_id="plus",
            ledger_entry_id=entry,
        )
        splits = await consume(
            session, tenant_id=tenant_id, demand=AiAssistDemand(credits=Decimal("75.00"))
        )
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=-credits_of(splits),
            reason="usage",
            ref=f"copilot-{uuid.uuid4().hex[:8]}",
            meta={"lots": split_meta(splits)},
        )
        charges = await billing.voice_tier_usage(
            session, tenant_id=tenant_id, month=billing.current_billing_month()
        )
    assert charges.total_inr == Decimal("0")


async def test_a_managed_tenant_still_prices_from_the_plan_and_not_from_a_wallet() -> None:
    """The managed branch is untouched: no wallet, no lots, no splits — the overage the
    caller already priced, plus the surcharge."""
    assert calling_revenue_inr(
        plan_tier="managed",
        prepaid_charged_inr=Decimal("999.00"),
        overage_cost_inr=Decimal("120.00"),
        llm_surcharge_inr=Decimal("15.00"),
    ) == Decimal("135.00")


# --- HIGH 3: the fallback is a pair, resolved by the call's own voice --------------


async def test_the_list_card_prices_both_voices_and_not_just_the_cheaper_one() -> None:
    """`RateCard.list_rates()` is the smallest pack — ₹5.00 Sarvam AND ₹8.00 Cartesia."""
    async with tenant_session(await make_tenant()) as session:
        card = await rate_card_at(session, at=datetime.now(UTC))
    assert card.list_rates() == LotRates(LIST_SARVAM, LIST_CARTESIA)
    assert card.list_rates().rate_for("sarvam") == LIST_SARVAM
    assert card.list_rates().rate_for("cartesia") == LIST_CARTESIA


async def test_a_studio_minute_on_a_wallet_with_no_lot_is_charged_at_the_studio_rate() -> None:
    """THE DEFECT: the pipeline handed `CallDemand` ONE number — the Sarvam list price —
    for both voices, so a Studio minute on an empty or overdrawn wallet (a new tenant
    before their first pack, a wallet after a full reversal, a migrated negative balance)
    was debited at ₹5.00 against a card that sells it at ₹8.00 and a cost floor of ₹4.36.
    Below the card and a hair above cost, on exactly the accounts nobody is watching."""
    tenant_id = await make_tenant()
    await _prepaid(tenant_id)
    async with tenant_session(tenant_id) as session:
        card = await rate_card_at(session, at=datetime.now(UTC))
        call_id = await _metered_call(session, tenant_id=tenant_id, minutes=Decimal("10"))
        charged = await charge_for_call(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            demand=CallDemand(
                minutes=Decimal("10"),
                voice_tier="cartesia",
                fallback_rates=card.list_rates(),
            ),
        )
    assert charged == Decimal("80.0000"), "10 x ₹8.00"
    assert charged != Decimal("50.0000"), "and NOT 10 x the Sarvam list price"


def test_a_demand_cannot_disagree_with_its_own_fallback_rate() -> None:
    """The pair plus `LotRates.rate_for` is what makes the mistake unwritable: the voice on
    the demand is the voice the rate is resolved by, in one place, on the demand itself."""
    rates = LotRates(LIST_SARVAM, LIST_CARTESIA)
    sarvam = CallDemand(minutes=Decimal("1"), voice_tier="sarvam", fallback_rates=rates)
    cartesia = CallDemand(minutes=Decimal("1"), voice_tier="cartesia", fallback_rates=rates)
    assert sarvam.fallback_inr_per_min == LIST_SARVAM
    assert cartesia.fallback_inr_per_min == LIST_CARTESIA


# --- MED 4: the dated card is READ, so recording one is not inert ------------------


async def test_a_recorded_card_prices_the_lot_a_purchase_opens() -> None:
    """`list_rates.card_at` had ZERO callers: every lot took its rates from the
    `PACK_CATALOGUE` constant, so a future-dated card written in the ops console was inert
    and "raise prices later by recording a new card" was false. One reader — `RateCard` —
    and the promise holds.

    The rows are removed as the OWNER afterwards: `platform_list_rates` is append-only ON
    PURPOSE and is shared by every suite on this database, so leaving one behind would
    change what a card resolves to for all of them.
    """
    at = datetime.now(UTC) - timedelta(seconds=1)
    async with untenanted_session() as session:
        admin_id = uuid.uuid4()
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
        await session.execute(
            text(
                "INSERT INTO platform_list_rates (rate_key, effective_from, inr_amount, "
                "recorded_by, source_note) VALUES (:k, :ef, :amt, :by, 'card reader test')"
            ),
            [
                {
                    "k": pack_rate_key("starter", "sarvam"),
                    "ef": at,
                    "amt": Decimal("5.5000"),
                    "by": admin_id,
                },
                {
                    "k": pack_rate_key("starter", "cartesia"),
                    "ef": at,
                    "amt": Decimal("8.7500"),
                    "by": admin_id,
                },
            ],
        )
    try:
        async with tenant_session(await make_tenant()) as session:
            card = await rate_card_at(session, at=datetime.now(UTC))
        assert card.list_rates() == LotRates(Decimal("5.5000"), Decimal("8.7500")), (
            "the card in force, not the catalogue constant"
        )
        # A cell nobody recorded still answers the CATALOGUE, per cell — the only reading
        # that does not silently drop a pack the card predates.
        assert card.for_purchase(pack_id="max", amount_inr=Decimal("50000")) == LotRates(
            Decimal("4.50"), Decimal("6.00")
        )
    finally:
        await _purge_card_rows()


async def _purge_card_rows() -> None:
    """Delete this test's card rows as the OWNER — the only role that can, because the
    table is append-only on purpose. `ENABLE TRIGGER` is not the inverse of `DISABLE`
    (plain ENABLE demotes an `ENABLE ALWAYS` trigger to ORIGIN), so each trigger's mode is
    read first and put back verbatim."""
    owner_url = Settings().alembic_database_url
    assert owner_url, "ALEMBIC_DATABASE_URL required: platform_list_rates is append-only"
    engine = create_async_engine(owner_url)
    try:
        async with engine.begin() as conn:
            modes = (
                await conn.execute(
                    text(
                        "SELECT tgname, tgenabled FROM pg_trigger "
                        "WHERE tgrelid = 'platform_list_rates'::regclass AND NOT tgisinternal"
                    )
                )
            ).all()
            await conn.execute(text("ALTER TABLE platform_list_rates DISABLE TRIGGER USER"))
            await conn.execute(
                text("DELETE FROM platform_list_rates WHERE rate_key LIKE :packs"),
                {"packs": f"{PACK_RATE_KEY_PREFIX}:%"},
            )
            for name, mode in modes:
                verb = {"A": "ENABLE ALWAYS", "R": "ENABLE REPLICA", "D": "DISABLE"}.get(
                    str(mode), "ENABLE"
                )
                await conn.execute(text(f'ALTER TABLE platform_list_rates {verb} TRIGGER "{name}"'))
    finally:
        await engine.dispose()
