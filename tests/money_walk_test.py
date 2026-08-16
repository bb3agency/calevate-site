"""One rupee, walked from the usage row to the invoice, and the hops that lost paise.

Every piece of the money path had been reasoned about on its own — D-137 the AI quota,
D-140 its refusals, D-92 the money-path float sweep, D-77 the tax invoice, D-82 the
corrections — and the WALK had never been taken. Taking it found the defect class this
file exists for: **a figure quantized twice arrives twice.**

`to_paise` applied independently to the parts of a total does not sum to `to_paise` of
the whole. Two TTS rungs of 5.005 and 4.995 minutes total exactly 10.00; rounded apart
they are 5.01 + 5.00 = 10.01. Three surfaces published both a breakdown and its total
and all three said in a docstring that the parts add up:

* `usage_summary`'s two overage rungs against `overage_minutes`;
* `tier_usage`'s three buckets against `usage_summary`'s `minutes_used`;
* the invoice's per-rung lines against the total the panel already showed the client —
  where `_reconcile_overage` closed the gap by BENDING THE LAST LINE, so the document
  printed "5.00 min at ₹3.75/min" beside an amount of ₹18.69. Six paise adrift of the
  multiplication a client does with a calculator, on the one arithmetic an accountant
  checks first.

The fix is one set of minute figures for the whole system (`_tier_totals` allocates them
once, `allocate_paise`) and one place a rung's money is computed (`overage_rungs`, called
by the panel and by the invoice). Nothing downstream rounds a minute again.

**Every fixture here prices with awkward decimals on purpose.** The suite already had
`tests/billing_audit_test.py`'s "every line multiplies out" assertion and it passed
throughout, because its fixture bills whole minutes at a single rate — a rounding defect
cannot show itself against round numbers.

Run: uv run pytest -q tests/money_walk_test.py
"""

from __future__ import annotations

import ast
import asyncio
import uuid
from collections.abc import Callable, Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing import service as billing
from apps.api.billing.caps import apply_client_caps, lock_tenant_spend_state
from apps.api.billing.charges import SETUP_FEE_KIND
from apps.api.billing.gst import PlaceOfSupply, split_tax
from apps.api.billing.invoice import build_invoice
from apps.api.billing.service import (
    allocate_paise,
    current_billing_month,
    margin_for_tenant,
    tier_usage,
    to_paise,
    usage_summary,
)
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.workers.pipeline import _SPEND_STATE_UPSERT
from sqlalchemy import text

# Deliberately not round. `unit_cost_paid` is NUMERIC(12,4) and a per-second telephony
# price with four significant decimals is what the pipeline actually writes; a fixture at
# ₹0.5000/second would multiply out cleanly at every hop and prove nothing.
_TELEPHONY_UNIT_COST = Decimal("0.0133")
_PREMIUM_RATE = Decimal("7.1250")
_VALUE_RATE = Decimal("3.7500")


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name="Walk Clinic",
        slug=f"walk-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email="pay@example.test",
        language="te-IN",
        created_by=None,
    )
    return created["id"], created["agent_id"]


async def _plan(
    tenant_id: uuid.UUID,
    *,
    monthly_fee: str | None = None,
    included_min: int = 0,
    overage_rate: Decimal = _PREMIUM_RATE,
    overage_rate_value: Decimal | None = _VALUE_RATE,
) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO plans (id, tenant_id, monthly_fee, included_min, overage_rate, "
                "overage_rate_value, concurrency_ceiling, created_at, updated_at) "
                "VALUES (:i, :t, :fee, :inc, :rate, :value_rate, 10, now(), now())"
            ),
            {
                "i": uuid7(),
                "t": tenant_id,
                "fee": Decimal(monthly_fee) if monthly_fee is not None else None,
                "inc": included_min,
                "rate": overage_rate,
                "value_rate": overage_rate_value,
            },
        )


async def _metered_call(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    tier: str | None,
    seconds: str,
    legs: dict[str, tuple[str, str]] | None = None,
) -> uuid.UUID:
    """One completed call with a full set of usage rows, shaped like the pipeline's.

    `legs` is `{unit_type: (qty, unit_cost_paid)}` beside the telephony row, so the walk
    below can follow a rupee that entered the ledger on a unit type nobody bills minutes
    on — `stt_s`, `tts_chars`, `llm_tok_out` — and check it still arrives.
    """
    call_id = uuid7()
    meta = "{}" if tier is None else f'{{"tts_tier": "{tier}"}}'
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
                "status, created_at, updated_at) VALUES (:i, :t, :a, :e, 'outbound', "
                "'+919876500001', 'completed', now(), now())"
            ),
            {"i": call_id, "t": tenant_id, "a": agent_id, "e": f"exec_{uuid.uuid4().hex[:12]}"},
        )
        rows = {"telephony_s": (seconds, str(_TELEPHONY_UNIT_COST)), **(legs or {})}
        for unit_type, (qty, cost) in rows.items():
            await session.execute(
                text(
                    "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                    "unit_cost_paid, occurred_at, meta, created_at) VALUES (:i, :t, :c, :u, "
                    ":qty, :cost, now(), CAST(:meta AS jsonb), now())"
                ),
                {
                    "i": uuid7(),
                    "t": tenant_id,
                    "c": call_id,
                    "u": unit_type,
                    "qty": Decimal(qty),
                    "cost": Decimal(cost),
                    "meta": meta,
                },
            )
    return call_id


def _assert_exact_decimal(value: Any, label: str) -> Decimal:
    """Hard rule 7 at every hop: a Decimal, and never a float wearing one."""
    assert isinstance(value, Decimal), f"{label} is {type(value).__name__}, not Decimal: {value!r}"
    assert not isinstance(value, float), f"{label} is a float"
    return value


# ============================================================================
# 1. The walk itself
# ============================================================================


async def test_one_rupee_arrives_at_every_hop_as_the_same_decimal() -> None:
    """OUR cost, followed from `usage_events` to the margin panel and to a closed
    month's client-facing spend figure.

    The three readers are `_tier_totals` (per rung), `margin_for_tenant.cost_inr` and
    `usage_summary.spend_used_inr` for a closed month. They must be the SAME number, not
    three roundings of it: the margin panel and the usage panel are read side by side by
    the same operator on the same tenant.

    The legs are priced so that no product lands on a whole paisa — 1873 seconds of STT
    at ₹0.0083 is ₹15.5459, which a reader that rounded per leg would report as ₹15.55
    and lose half a paisa per call.
    """
    tenant_id, agent_id = await _tenant()
    await _plan(tenant_id, included_min=0)
    await _metered_call(
        tenant_id,
        agent_id,
        tier="premium",
        seconds="1873.0000",
        legs={
            "stt_s": ("1873.0000", "0.0083"),
            "tts_chars": ("1.0000", "1.6217"),
            "llm_tok_out": ("1.0000", "0.0000"),
            "platform_min": ("31.2167", "1.5100"),
        },
    )

    expected = (
        Decimal("1873.0000") * _TELEPHONY_UNIT_COST
        + Decimal("1873.0000") * Decimal("0.0083")
        + Decimal("1.0000") * Decimal("1.6217")
        + Decimal("31.2167") * Decimal("1.5100")
    )
    assert expected == Decimal("89.21571700")
    assert expected != to_paise(expected), (
        "the fixture's legs now sum to a whole number of paise, so a hop that truncated "
        "would still agree with one that rounded — re-price it before trusting a pass"
    )

    async with tenant_session(tenant_id) as session:
        tiers = await tier_usage(session, tenant_id=tenant_id)
        margin = await margin_for_tenant(session, tenant_id=tenant_id)

    cost_from_tiers = _assert_exact_decimal(tiers["cost_premium_inr"], "tier_usage cost")
    cost_from_margin = _assert_exact_decimal(margin["cost_inr"], "margin cost")
    assert cost_from_tiers == cost_from_margin == to_paise(expected) == Decimal("89.22")


async def test_the_client_rupee_arrives_at_the_invoice_unchanged() -> None:
    """What the CLIENT pays, followed from the panel to the document.

    Awkward on both axes: the minutes carry a half-paisa fraction and the rates are not
    whole paise. Every equality below is between two surfaces a client can put side by
    side — the usage panel and their invoice.
    """
    tenant_id, agent_id = await _tenant()
    await _plan(tenant_id, monthly_fee="1234.5600", included_min=0)
    # 5.005 and 4.995 minutes: each on a half-paisa boundary, totalling exactly 10.00.
    await _metered_call(tenant_id, agent_id, tier="premium", seconds="300.3000")
    await _metered_call(tenant_id, agent_id, tier="value", seconds="299.7000")

    async with tenant_session(tenant_id) as session:
        summary = await usage_summary(session, tenant_id=tenant_id)
        invoice = await build_invoice(session, tenant_id=tenant_id)

    minutes = _assert_exact_decimal(summary["minutes_used"], "minutes_used")
    assert minutes == Decimal("10.00")

    premium = _assert_exact_decimal(summary["overage_minutes_premium"], "premium rung")
    value = _assert_exact_decimal(summary["overage_minutes_value"], "value rung")
    assert premium + value == summary["overage_minutes"] == minutes, (
        "the published rungs must add to the minute count the client is charged on"
    )

    overage_lines = [
        item for item in invoice["line_items"] if item["description"].startswith("Extra")
    ]
    assert [line["qty"] for line in overage_lines] == [premium, value], (
        "the invoice must print the rungs the panel published, not a re-derivation"
    )
    for line in overage_lines:
        product = _assert_exact_decimal(line["qty"], "line qty") * _assert_exact_decimal(
            line["unit_inr"], "line unit"
        )
        assert to_paise(product) == line["amount_inr"], f"this line does not multiply out: {line}"

    charged = sum((line["amount_inr"] for line in overage_lines), Decimal("0"))
    assert charged == summary["overage_cost_inr"], (
        "the invoice's overage lines and the panel's overage total are the same rupees"
    )
    assert invoice["subtotal_inr"] == summary["monthly_fee_inr"] + charged
    assert invoice["total_inr"] == invoice["subtotal_inr"] + invoice["gst_inr"]


async def test_the_tier_panel_never_disagrees_with_the_usage_panel_about_a_month() -> None:
    """Three buckets against one total, on seconds that put every bucket on a boundary.

    0.3 seconds is 0.005 minutes exactly. Three such calls total 0.015 minutes → 0.02 on
    the usage panel, and rounding each bucket on its own gives 0.01 three times = 0.03: the tier
    panel reporting fifty percent more minutes than the panel beside it.
    """
    tenant_id, agent_id = await _tenant()
    for tier in ("premium", "value", None):
        await _metered_call(tenant_id, agent_id, tier=tier, seconds="0.3000")

    async with tenant_session(tenant_id) as session:
        summary = await usage_summary(session, tenant_id=tenant_id)
        tiers = await tier_usage(session, tenant_id=tenant_id)

    buckets = tiers["minutes_premium"] + tiers["minutes_value"] + tiers["minutes_unattributed"]
    assert summary["minutes_used"] == Decimal("0.02")
    assert buckets == summary["minutes_used"], (
        f"the tier buckets sum to {buckets} against a usage panel reading {summary['minutes_used']}"
    )
    assert (
        tiers["minutes_billable_premium"] + tiers["minutes_billable_value"]
        == summary["minutes_used"]
    ), "and the BILLABLE split — unattributed folded in with value — adds up too"


# ============================================================================
# 2. The allocation primitive
# ============================================================================


def test_allocate_paise_parts_always_add_to_the_total() -> None:
    """The property the whole fix rests on, over inputs chosen to break it.

    Each case is (parts, total) where the total is `to_paise` of the parts' exact sum —
    which is what every caller has, because the total is what the client is charged on.
    """
    cases: list[tuple[list[Decimal], Decimal]] = [
        ([Decimal("5.005"), Decimal("4.995")], Decimal("10.00")),
        ([Decimal("0.005"), Decimal("0.005"), Decimal("0.005")], Decimal("0.02")),
        ([Decimal("0.004"), Decimal("0.004"), Decimal("0.004")], Decimal("0.01")),
        ([Decimal("1.666666666"), Decimal("1.666666666"), Decimal("1.666666668")], Decimal("5.00")),
        ([Decimal("0"), Decimal("0"), Decimal("0")], Decimal("0.00")),
        ([Decimal("12.50")], Decimal("12.50")),
    ]
    for parts, total in cases:
        allocated = allocate_paise(parts, total)
        assert sum(allocated, Decimal("0")) == total, (parts, total, allocated)
        for part, given in zip(parts, allocated, strict=True):
            assert isinstance(given, Decimal)
            assert abs(given - part) < Decimal("0.01"), (
                f"{given} is more than a paisa from its exact value {part}"
            )
            assert str(given) == str(given.quantize(Decimal("0.01"))), f"{given} is not paise"


def test_allocate_paise_hands_the_spare_paise_to_the_biggest_fractions_first() -> None:
    """Largest remainder, with ties broken by POSITION so the answer is deterministic.

    A set/dict-ordered tie-break would make one client's panel depend on hash seeding,
    which is the kind of non-determinism that only shows up in a support ticket.
    """
    # 0.019 + 0.011 + 0.010 = 0.040 exactly; floors are 0.01 + 0.01 + 0.01 = 0.03, so one
    # paisa is owed and the biggest discarded fraction (0.009) takes it.
    assert allocate_paise(
        [Decimal("0.019"), Decimal("0.011"), Decimal("0.010")], Decimal("0.04")
    ) == (Decimal("0.02"), Decimal("0.01"), Decimal("0.01"))
    # An exact tie goes to the earlier part, every time it is asked.
    tied = [Decimal("0.005"), Decimal("0.005")]
    assert allocate_paise(tied, Decimal("0.01")) == (Decimal("0.01"), Decimal("0.00"))
    assert allocate_paise(tied, Decimal("0.01")) == allocate_paise(tied, Decimal("0.01"))


def test_allocate_paise_refuses_a_total_that_is_not_the_parts_total() -> None:
    """The guard is PROVED rather than merely present (the shape
    `models.assert_units_are_disjoint` argues for).

    A caller pairing a breakdown with a figure summed somewhere else is the exact defect
    this function was written to end, so it must not be answerable: silently returning
    parts that do not add up would reintroduce it one layer down.
    """
    with pytest.raises(ValueError, match="not the total"):
        allocate_paise([Decimal("1.00"), Decimal("2.00")], Decimal("99.00"))
    with pytest.raises(ValueError, match="not the total"):
        allocate_paise([Decimal("1.00")], Decimal("0.00"))
    # No parts is not an error — it is a month with no usage, and the answer is nothing.
    assert allocate_paise([], Decimal("0.00")) == ()


# ============================================================================
# 3. The IST month roll, with work in flight
# ============================================================================


@pytest.fixture
def rolling_month(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[str], None]]:
    """A clock that crosses the IST month boundary between two readings.

    Not a sleep and not a mock of `datetime`: the subject is how many TIMES the billing
    month is read inside one answer, so the fake advances on every call. A function that
    reads it once is unaffected; a function that reads it twice straddles the roll, which
    is exactly what 00:00:00 IST on the 1st does to a request already in flight.
    """

    def _install(first_month: str) -> None:
        year, mon = int(first_month[:4]), int(first_month[5:])
        following = f"{year + 1}-01" if mon == 12 else f"{year}-{mon + 1:02d}"
        readings = iter([first_month])

        def _clock() -> str:
            return next(readings, following)

        monkeypatch.setattr(billing, "current_billing_month", _clock)

    yield _install


async def test_the_month_roll_cannot_zero_the_spend_on_a_statement(
    rolling_month: Callable[[str], None],
) -> None:
    """The open month's spend is the LIVE counter — the column the cap is enforced
    against — and it must stay that even if the month rolls mid-request.

    `usage_summary` used to read "which month is now" three times: once for the period,
    once inside `read_spend_counters`' staleness test, and once in `_spend_used`. A roll
    between the first and the second makes the counter row look stale (so the live
    figure reads ₹0.00) while the panel is still reporting the month it opened with —
    and the client's own spend panel then contradicts the gate that is capping them.

    The counter and the ledger are seeded to DIFFERENT figures on purpose: with them
    equal, this test would pass whichever source the panel picked.
    """
    tenant_id, agent_id = await _tenant()
    await _plan(tenant_id, included_min=0)
    await _metered_call(tenant_id, agent_id, tier="premium", seconds="600.0000")
    month = current_billing_month()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                # The panel reads `billed_inr` (P1.3), so that is the column this test's
                # subject — "did the live counter survive the month roll" — lives in.
                "INSERT INTO spend_state (tenant_id, month, minutes_used, spend_used, "
                "billed_inr, capped, created_at, updated_at) "
                "VALUES (:t, :m, 10, :spend, :spend, false, now(), now())"
            ),
            {"t": tenant_id, "m": month, "spend": Decimal("41.7700")},
        )

    rolling_month(month)
    async with tenant_session(tenant_id) as session:
        summary = await usage_summary(session, tenant_id=tenant_id)

    assert summary["month"] == month
    assert summary["spend_used_inr"] == Decimal("41.77"), (
        "the panel reported the ledger instead of the live counter — the two readings of "
        "'which month is now' straddled the roll"
    )


# ============================================================================
# 4. Compensating entries reach the document
# ============================================================================


def test_the_tax_heads_sum_to_the_tax_charged_on_a_negative_subtotal() -> None:
    """`split_tax` halves a rate and lets the SECOND head absorb the remainder. On a
    credit the halves are negative, and `to_paise(total - first)` has to stay the
    difference rather than a second independent rounding of it.

    ₹-100.25 at 18% is ₹-18.045 → ₹-18.05 half-up (away from zero, both signs). Nine
    percent of it is ₹-9.0225 → ₹-9.02, so the State head must carry ₹-9.03.
    """
    place = PlaceOfSupply(
        state_code="36", state_name="Telangana", supply_type="intrastate", basis="test"
    )
    heads = split_tax(subtotal_inr=Decimal("-100.25"), rate_pct=Decimal("18"), place=place)
    assert [head.label for head in heads] == ["CGST", "SGST"]
    assert [head.amount_inr for head in heads] == [Decimal("-9.02"), Decimal("-9.03")]
    assert sum((head.amount_inr for head in heads), Decimal("0")) == Decimal("-18.05")


async def test_a_compensating_charge_prints_as_a_credit_and_the_document_still_balances() -> None:
    """Hard rule 4 on the surface a client reads it from.

    A one-time charge that has to be undone is a NEW row with a negative amount under
    its own `ref` — never an edit, never a delete — and the derived statement prints it
    as a credit line. What this pins is the arithmetic AFTER that: the subtotal is still
    the sum of the lines, the GST is still 18% of it, the heads still sum to the GST,
    and the total is still subtotal + GST. A negative rupee is where a rounding mode
    that treats signs asymmetrically shows itself, and ROUND_HALF_UP is "away from
    zero", so ₹-18.045 must be ₹-18.05 and not ₹-18.04.
    """
    tenant_id, _ = await _tenant()
    async with tenant_session(tenant_id) as session:
        for ref, description, amount in (
            ("onboarding", "One-time onboarding & setup", Decimal("100.25")),
            ("onboarding-reversal", "Reversal: onboarding charged in error", Decimal("-200.50")),
        ):
            await session.execute(
                text(
                    "INSERT INTO one_time_charges (id, tenant_id, kind, ref, description, "
                    "amount, billing_month, occurred_at, created_at) VALUES (:i, :t, :k, :r, "
                    ":d, :a, :m, now(), now())"
                ),
                {
                    "i": uuid7(),
                    "t": tenant_id,
                    "k": SETUP_FEE_KIND,
                    "r": ref,
                    "d": description,
                    "a": amount,
                    "m": current_billing_month(),
                },
            )
        invoice = await build_invoice(session, tenant_id=tenant_id)

    lines = invoice["line_items"]
    assert [line["amount_inr"] for line in lines] == [Decimal("100.25"), Decimal("-200.50")]
    assert invoice["subtotal_inr"] == sum((line["amount_inr"] for line in lines), Decimal("0"))
    assert invoice["subtotal_inr"] == Decimal("-100.25")
    # -100.25 * 18% is exactly -18.045. Half-up is away from zero on both signs.
    assert invoice["gst_inr"] == Decimal("-18.05")
    assert (
        sum((component["amount_inr"] for component in invoice["tax_components"]), Decimal("0"))
        == invoice["gst_inr"]
    ), "the tax heads must sum to the tax charged, on a credit too"
    assert invoice["total_inr"] == Decimal("-118.30")


# ============================================================================
# 5. What the client SEES against what we actually charge them
# ============================================================================


async def test_a_self_serve_wallet_is_debited_at_our_cost_not_at_the_price_we_quote() -> None:
    """**AN OPEN FINDING, PINNED SO IT CANNOT BE HALF-FIXED.**

    A self-serve client's wallet IS their bill (D-39, and `record_tier_correction` says
    so in as many words: "the call was debited at metered cost"). The debit is
    `charge_for_call(amount_inr=cost.total_inr)` from `apps/workers/pipeline.py` — OUR
    SUPPLIER COST. The runway the same client reads on their usage panel is
    `balance ÷ settings.self_serve_inr_per_min` — the LIST PRICE, ₹6.00/min by default.

    So the two numbers on one screen come from different places: we quote a price and we
    charge a cost, and the margin on every self-serve minute is exactly zero. D-34
    specifies the motion as "prepaid credits, per-minute talk-time" against a list price,
    and `self_serve_inr_per_min`'s own docstring says the runway framing and the top-up
    flow "price from the SAME source" — today it has exactly one reader, the runway.

    NOT fixed here, and the reason is not that it is hard: the writer is
    `apps/workers/pipeline.py`, and switching self-serve billing from cost to list price
    changes what every self-serve client pays by roughly two-fold. That is a commercial act,
    not a refactor. This test states today's behaviour precisely so the change arrives as
    a deliberate edit to a red test rather than as a silent re-pricing.
    """
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = 'self_serve' WHERE id = :t"),
            {"t": tenant_id},
        )
    call_id = await _metered_call(tenant_id, agent_id, tier="premium", seconds="600.0000")

    metered_cost = to_paise(Decimal("600.0000") * _TELEPHONY_UNIT_COST)
    assert metered_cost == Decimal("7.98")

    async with tenant_session(tenant_id) as session:
        await billing.record_entry(
            session, tenant_id=tenant_id, delta=Decimal("1000.00"), reason="topup", ref="UTR-WALK"
        )
        # Exactly what the pipeline does: debit the metered cost, keyed by the call.
        await billing.charge_for_call(
            session, tenant_id=tenant_id, call_id=call_id, amount_inr=metered_cost
        )
        summary = await usage_summary(session, tenant_id=tenant_id)
        balance = await billing.get_balance(session, tenant_id=tenant_id)

    assert balance.amount_inr == Decimal("1000.00") - metered_cost
    list_price = get_settings().self_serve_inr_per_min
    would_have_charged = to_paise(Decimal("10") * list_price)
    assert metered_cost < would_have_charged, (
        "the fixture no longer distinguishes cost from list price, so this pin proves "
        "nothing — re-price it before trusting a green run"
    )
    # The runway on the client's own panel is priced at the LIST rate…
    assert summary["minutes_left"] == int(balance.amount_inr / list_price)
    # …while the wallet actually bought `balance / metered rate` minutes, which is more.
    assert summary["minutes_left"] < int(balance.amount_inr / (metered_cost / Decimal("10")))


def test_a_zero_minute_field_still_crosses_the_wire_as_two_decimals() -> None:
    """The shape trap in the fix, pinned where it can be seen.

    Money and minutes leave this API as the digits `str(Decimal)` produces, so
    `Decimal("0")` and `Decimal("0.00")` are the same number and two different strings
    on a field a browser prints verbatim. `max(Decimal("0"), x)` returns its FIRST
    argument when the two are equal, so a bare zero in a floor expression is enough to
    turn "0.00 min" into "0 min" on a client's panel — a regression no arithmetic
    assertion in this suite would catch, because the arithmetic is right.
    """
    unused, spare = billing.split_overage(
        overage_min=Decimal("0.00"),
        billable_premium=Decimal("0.00"),
        billable_value=Decimal("0.00"),
        included_min=Decimal("100"),
        rate=_PREMIUM_RATE,
        rate_value=None,
    )
    assert str(unused) == "0.00" and str(spare) == "0.00"


async def test_a_month_inside_the_included_minutes_publishes_paise_shaped_zeroes() -> None:
    """The same trap end to end: the commonest month there is — a client comfortably
    inside their allowance — must not be the one that changes field shapes."""
    tenant_id, agent_id = await _tenant()
    await _plan(tenant_id, monthly_fee="9999.00", included_min=100)
    await _metered_call(tenant_id, agent_id, tier="premium", seconds="600.0000")

    async with tenant_session(tenant_id) as session:
        summary = await usage_summary(session, tenant_id=tenant_id)

    for field in (
        "minutes_used",
        "overage_minutes",
        "overage_minutes_premium",
        "overage_minutes_value",
        "overage_cost_inr",
        "spend_used_inr",
    ):
        assert str(summary[field]).endswith(("0", "1", "2", "3", "4", "5", "6", "7", "8", "9"))
        assert len(str(summary[field]).split(".")[-1]) == 2, (
            f"{field} is {summary[field]!r} — not two decimals on the wire"
        )


# ============================================================================
# 6. Concurrency: the client's stop button against a call finishing
# ============================================================================


async def test_a_call_finishing_cannot_un_press_the_clients_stop_button() -> None:
    """THE INTERLEAVING IS FORCED, not hoped for.

    Two transactions, held open at explicit barriers, in the one order that exposes the
    defect: the client's `PUT /v1/billing/caps` writes the ceiling and arms the flag
    (taking the `spend_state` row lock as it does), the meter's upsert then starts and
    blocks on that row, and the client's transaction commits.

    Before `lock_tenant_spend_state`, the meter unblocked and wrote `capped = false`: the
    row lock let it see the new counters and READ COMMITTED still handed it the OLD
    ceiling out of `plans` (postgresql.org/docs/16/transaction-iso.html §13.2.1 — an
    updating command sees concurrent effects on the rows it is updating, not on other
    rows). The client's outbound calling resumed, mid-runaway-campaign, with the panel
    still showing the cap they had set.

    Running the two sequentially proves nothing here: the defect is entirely in the
    overlap, and every ordering that does not overlap is already correct.
    """
    tenant_id, _ = await _tenant()
    month = current_billing_month()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO plans (id, tenant_id, hard_cap_spend, concurrency_ceiling, "
                "created_at, updated_at) VALUES (:i, :t, 10000, 10, now(), now())"
            ),
            {"i": uuid7(), "t": tenant_id},
        )
        await session.execute(
            text(
                "INSERT INTO spend_state (tenant_id, month, minutes_used, spend_used, "
                "billed_inr, capped, created_at, updated_at) "
                "VALUES (:t, :m, 100, 500, 500, false, now(), now())"
            ),
            {"t": tenant_id, "m": month},
        )

    caps_armed = asyncio.Event()
    meter_running = asyncio.Event()

    async def client_presses_stop() -> None:
        async with tenant_session(tenant_id) as session:
            await apply_client_caps(
                session, tenant_id=tenant_id, cap_min=None, cap_spend=Decimal("100")
            )
            caps_armed.set()
            await meter_running.wait()
            # Long enough for the meter's statement to reach the lock and block on it.
            await asyncio.sleep(0.3)

    async def a_call_finishes() -> None:
        await caps_armed.wait()
        async with tenant_session(tenant_id) as session:
            meter_running.set()
            await lock_tenant_spend_state(session, tenant_id)
            await session.execute(
                text(_SPEND_STATE_UPSERT),
                {
                    "tid": tenant_id,
                    "month": month,
                    "minutes": Decimal("1"),
                    "spend": Decimal("1"),
                    # The client's number, which is the one the cap is compared against
                    # (P1.3). Equal to `spend` here because this test is about the LOCK
                    # and not about the markup — but it has to be supplied, because the
                    # statement no longer accumulates one column and caps on another.
                    "billed": Decimal("1"),
                },
            )

    await asyncio.gather(client_presses_stop(), a_call_finishes())

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT capped, spend_used FROM spend_state WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
        ).first()

    assert row is not None
    assert row[1] == Decimal("501.0000"), "the meter's own counter must still have landed"
    assert row[0] is True, (
        "a call finishing mid-write un-capped a client who had just capped themselves: "
        "the metering upsert paired the new counters with the ceiling from before the "
        "client lowered it"
    )


async def test_the_clients_own_spend_figure_is_their_bill_and_not_our_supplier_cost() -> None:
    """**THE PIN THAT USED TO STATE THE DEFECT, INVERTED BECAUSE IT IS FIXED (P1.3).**

    It read: *"NOT fixed here. Both remedies are product decisions rather than
    refactors — publish the client's BILLED spend beside a cap denominated the same way
    (which needs a billed counter that survives included minutes and two rungs), or drop
    the field from the client realm and leave the cap as an admin instrument. This test
    states today's behaviour so whichever is chosen arrives as a deliberate edit."*

    The first remedy was chosen and this is the deliberate edit. `spend_state.billed_inr`
    is that counter: the meter writes it at the CLIENT's rate — list price for a prepaid
    tier, the plan's marginal rate on the minutes past `included_min` for a managed one —
    `over_cap_sql` compares the cap against it, and `usage_summary` publishes it. Our
    supplier cost stays in `spend_used`, where the admin margin panel reads it.

    The assertion is therefore the exact opposite of the one it replaces: the number a
    client reads as "used so far" and the number they are invoiced must now AGREE. This
    fixture is a managed plan with no included minutes, so every metered minute is
    overage and the panel's figure is exactly the overage the invoice will print.
    """
    tenant_id, agent_id = await _tenant()
    await _plan(tenant_id, monthly_fee="9999.00", included_min=0)
    await _metered_call(tenant_id, agent_id, tier="premium", seconds="600.0000")
    metered_cost = to_paise(Decimal("600.0000") * _TELEPHONY_UNIT_COST)

    async with tenant_session(tenant_id) as session:
        # The meter writes both columns; this fixture writes them by hand because it is
        # about what the PANEL reads, not about how the meter fills them.
        await session.execute(
            text(
                "INSERT INTO spend_state (tenant_id, month, minutes_used, spend_used, "
                "billed_inr, capped, created_at, updated_at) "
                "VALUES (:t, :m, 10, :spend, :billed, false, now(), now())"
            ),
            {
                "t": tenant_id,
                "m": current_billing_month(),
                "spend": metered_cost,
                # 10 minutes of premium overage at the plan's rate — the same arithmetic
                # `_meter` does, and the same one the invoice will do.
                "billed": Decimal("10") * _PREMIUM_RATE,
            },
        )
        summary = await usage_summary(session, tenant_id=tenant_id)

    assert summary["spend_used_inr"] == to_paise(Decimal("10") * _PREMIUM_RATE)
    assert summary["spend_used_inr"] == summary["overage_cost_inr"], (
        "the figure a client reads as 'used so far' is not the overage they will be "
        "invoiced for — the live counter and the ledger are pricing the same minutes "
        "differently"
    )
    assert summary["spend_used_inr"] != metered_cost, (
        "the client panel is publishing our supplier cost again — `usage_summary` reads "
        "`spend_state.spend_used` rather than `billed_inr` (P1.3)"
    )


def test_the_meter_takes_the_spend_state_lock_before_it_reads_the_ceiling() -> None:
    """THE ORDERING, asserted on the source, because the outcome test cannot see it.

    `test_a_call_finishing_cannot_un_press_the_clients_stop_button` drives the upsert
    directly, so it proves the LOCK works and says nothing about the production writer
    taking it — deleting the call from `pipeline._meter` leaves that test green. D-137
    recorded the same trap in the same words ("an outcome-only race test was green and
    the ordering assertion is what caught it"), and the remedy is the same: read the
    order out of the AST rather than out of a run.

    Position, not presence: a lock acquired AFTER the statement that reads `plans` is a
    lock that does nothing, and it is the likelier mistake — somebody moving the line
    while tidying, with every behavioural test still passing.
    """
    source = (Path(__file__).resolve().parents[1] / "apps/workers/pipeline.py").read_text()
    tree = ast.parse(source)
    meter = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_meter"
    )
    lock_at = [
        node.lineno
        for node in ast.walk(meter)
        if isinstance(node, ast.Name) and node.id == "lock_tenant_spend_state"
    ]
    upsert_at = [
        node.lineno
        for node in ast.walk(meter)
        if isinstance(node, ast.Name) and node.id == "_SPEND_STATE_UPSERT"
    ]
    assert lock_at, (
        "pipeline._meter no longer takes `lock_tenant_spend_state`. Its upsert reads the "
        "ceiling from `plans` and writes `spend_state`, so without the lock a client's "
        "own stop button is overwritten by a call that was already finishing "
        "(billing/caps.py::lock_tenant_spend_state)"
    )
    assert upsert_at, "the spend_state upsert moved out of `_meter`; re-point this guard"
    assert min(lock_at) < min(upsert_at), (
        "the lock is taken AFTER the statement it is supposed to protect, which is the "
        "same as not taking it: the ceiling has already been read by then"
    )
