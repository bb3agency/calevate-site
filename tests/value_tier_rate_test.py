"""`plans.overage_rate_value`: the second rung of D-36's ladder, as a price.

`billing/rates.py` already resolves every metered call to a `premium` or `value` TTS
tier and stamps it onto the usage row. Billing could not express it — `plans` quoted one
`overage_rate` — so the ladder existed on the cost side (D-35: Bulbul v2 is live at half
the v3 rate) and nowhere on the revenue side.

The column added by migration b1d5c8e73f04 closes that, and the property that makes it
safe to add to a live schema is the FIRST test here:

1. **NULL bills exactly as before.** Every plan row that existed on the day the column
   landed is NULL, so no client's invoice moved by a paisa. Asserted by pricing the same
   month twice — once with the column NULL, once with it set — and requiring the NULL
   case to reproduce `overage_minutes * overage_rate` exactly.
2. **The included allowance is spent on the DEARER rung first**, which leaves the
   cheaper minutes to be charged for. That is the client's favour, and it is the same
   asymmetry `rates.billable_tier` applies when it bills an unprovable tier as `value`.
3. **The two rung figures always add to `overage_minutes`.** The invoice promises that
   its lines sum to the subtotal and that each line multiplies out; a split computed
   independently of the total could miss it by a paisa, which is a support ticket.
4. **Unattributed minutes are priced at the VALUE rate.** A call we cannot prove got the
   premium voice is never charged the premium rate (SURFACES §2b) — the honesty rule
   `rates.py` states, now applied to revenue and not only to cost.
5. **No price is invented.** The column has no default, and nothing in the codebase
   derives one from TRD §10.1's explicitly unmeasured bands.

CONCURRENCY: every test mints its own tenant and touches no global row.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing.invoice import build_invoice
from apps.api.billing.models import Plan
from apps.api.billing.service import split_overage, to_paise, usage_summary
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from sqlalchemy import text

PREMIUM_RATE = Decimal("8.0000")
VALUE_RATE = Decimal("5.0000")


async def _tenant() -> UUID:
    created = await admin_service.create_organization(
        name="Ladder Clinic",
        slug=f"ladder-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return UUID(str(created["id"]))


async def _plan(tenant_id: UUID, *, included: int, value_rate: Decimal | None) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO plans (id, tenant_id, monthly_fee, included_min, overage_rate, "
                "overage_rate_value, concurrency_ceiling, created_at, updated_at) "
                "VALUES (:i, :t, 1000.00, :inc, :rate, :vrate, 10, now(), now())"
            ),
            {
                "i": uuid7(),
                "t": tenant_id,
                "inc": included,
                "rate": PREMIUM_RATE,
                "vrate": value_rate,
            },
        )


async def _set_value_rate(tenant_id: UUID, rate: Decimal | None) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE plans SET overage_rate_value = :r WHERE tenant_id = :t"),
            {"r": rate, "t": tenant_id},
        )


async def _bill_minutes(tenant_id: UUID, *, tier: str | None, minutes: int) -> None:
    """Meter `minutes` of talk time carrying `tier` in `usage_events.meta` — the exact
    field the post-call pipeline stamps (`tts_tier`). `tier=None` writes no meta at all,
    which is the pre-attribution row shape."""
    async with tenant_session(tenant_id) as session:
        agent_id = uuid7()
        await session.execute(
            text(
                "INSERT INTO agents (id, tenant_id, name, direction, disclosure_line, status, "
                "engine, created_at, updated_at) VALUES (:a, :t, 'Ladder', 'outbound', "
                "'Idi AI assistant.', 'live', 'fake', now(), now())"
            ),
            {"a": agent_id, "t": tenant_id},
        )
        call_id = uuid7()
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
                "unit_cost_paid, occurred_at, meta, created_at) VALUES (:i, :t, :c, "
                "'telephony_s', :qty, 0.5000, now(), CAST(:meta AS jsonb), now())"
            ),
            {
                "i": uuid7(),
                "t": tenant_id,
                "c": call_id,
                "qty": minutes * 60,
                "meta": None if tier is None else f'{{"tts_tier": "{tier}"}}',
            },
        )


async def _summary(tenant_id: UUID) -> dict[str, object]:
    async with tenant_session(tenant_id) as session:
        return await usage_summary(session, tenant_id=tenant_id)


# ============================================================================
# 1. The column exists, has no default, and NULL changes nothing
# ============================================================================


def test_the_column_is_nullable_money_and_carries_no_default() -> None:
    """A default here would be an invented price. TRD §10.1's cost bands are explicitly
    unmeasured (the chars-per-minute ratio and the platform fee are both pilot gates),
    so the schema owes the founder somewhere to put a number, not the number."""
    column = Plan.__table__.c.overage_rate_value
    assert column.nullable is True
    assert column.default is None and column.server_default is None
    assert (column.type.precision, column.type.scale) == (12, 4), "the MONEY precision"


async def test_a_plan_with_no_value_rate_bills_exactly_as_it_did_before() -> None:
    """The equivalence that made this migration safe for every existing client: a NULL
    value rate prices the whole overage at `overage_rate`, whatever the tier mix is."""
    tenant_id = await _tenant()
    await _plan(tenant_id, included=100, value_rate=None)
    await _bill_minutes(tenant_id, tier="premium", minutes=80)
    await _bill_minutes(tenant_id, tier="value", minutes=60)

    summary = await _summary(tenant_id)
    assert summary["minutes_used"] == Decimal("140.00")
    assert summary["overage_minutes"] == Decimal("40.00")
    assert summary["overage_cost_inr"] == to_paise(Decimal("40") * PREMIUM_RATE)
    assert summary["overage_rate_value_inr"] is None, (
        "None, not a repeat of the premium rate — 'one rate' and 'two equal rates' are "
        "different plans and the screen says different things about them"
    )
    # Everything sits on the premium side when there is no second rung to split onto.
    assert summary["overage_minutes_premium"] == Decimal("40.00")
    assert summary["overage_minutes_value"] == Decimal("0.00")


# ============================================================================
# 2 + 3. The split, and the arithmetic promise
# ============================================================================


async def test_the_included_allowance_is_spent_on_the_dearer_rung_first() -> None:
    """80 premium + 60 value, 100 included. The premium minutes are consumed first, so
    the 40 chargeable minutes are 20 premium + 20 value rather than 40 premium — which
    is ₹60 less on the client's bill at these rates."""
    tenant_id = await _tenant()
    await _plan(tenant_id, included=100, value_rate=VALUE_RATE)
    await _bill_minutes(tenant_id, tier="premium", minutes=80)
    await _bill_minutes(tenant_id, tier="value", minutes=60)

    summary = await _summary(tenant_id)
    assert summary["overage_minutes"] == Decimal("40.00")
    assert summary["overage_minutes_premium"] == Decimal("0.00"), "all 80 were included"
    assert summary["overage_minutes_value"] == Decimal("40.00")
    assert summary["overage_cost_inr"] == to_paise(Decimal("40") * VALUE_RATE)
    assert summary["overage_rate_value_inr"] == Decimal("5.00")

    # And the same month priced without the second rung costs the client MORE, which is
    # the whole reason the ladder is worth having.
    await _set_value_rate(tenant_id, None)
    assert (await _summary(tenant_id))["overage_cost_inr"] == to_paise(Decimal("40") * PREMIUM_RATE)


async def test_the_premium_rung_is_charged_once_the_allowance_runs_out() -> None:
    """150 premium + 50 value, 100 included: 50 premium and 50 value are chargeable."""
    tenant_id = await _tenant()
    await _plan(tenant_id, included=100, value_rate=VALUE_RATE)
    await _bill_minutes(tenant_id, tier="premium", minutes=150)
    await _bill_minutes(tenant_id, tier="value", minutes=50)

    summary = await _summary(tenant_id)
    assert summary["overage_minutes_premium"] == Decimal("50.00")
    assert summary["overage_minutes_value"] == Decimal("50.00")
    assert summary["overage_cost_inr"] == to_paise(
        Decimal("50") * PREMIUM_RATE + Decimal("50") * VALUE_RATE
    )


def test_the_two_rungs_always_add_to_the_overage_total() -> None:
    """Pinned as an identity over awkward inputs, because it is what the invoice's
    "every line multiplies out and the lines sum to the subtotal" promise rests on."""
    cases = [
        (Decimal("40"), Decimal("80"), Decimal("60"), Decimal("100")),
        (Decimal("0"), Decimal("10"), Decimal("10"), Decimal("100")),
        (Decimal("200"), Decimal("0"), Decimal("200"), Decimal("0")),
        # Tier sums that disagree with the total in the last place — two roundings of
        # the same seconds. The TOTAL is the number that was priced, so it wins.
        (Decimal("40.00"), Decimal("80.01"), Decimal("59.99"), Decimal("100")),
        (Decimal("40.00"), Decimal("0"), Decimal("0"), Decimal("100")),
    ]
    for overage, premium, value, included in cases:
        a, b = split_overage(
            overage_min=overage,
            billable_premium=premium,
            billable_value=value,
            included_min=included,
            rate=PREMIUM_RATE,
            rate_value=VALUE_RATE,
        )
        assert a + b == overage, (overage, premium, value, included)
        assert a >= 0 and b >= 0


def test_the_dearer_rung_is_decided_by_price_not_by_label() -> None:
    """Written as "the dearer rung" rather than "the premium rung" so the allocation
    stays client-favourable even if a value rate is ever quoted ABOVE the premium one.
    The rule is about price; the labels are just names."""
    inverted = split_overage(
        overage_min=Decimal("40"),
        billable_premium=Decimal("80"),
        billable_value=Decimal("60"),
        included_min=Decimal("100"),
        rate=Decimal("5.0000"),
        rate_value=Decimal("8.0000"),
    )
    assert inverted == (Decimal("40"), Decimal("0")), (
        "with value the dearer rung, the allowance covers VALUE minutes first and the "
        "cheaper premium minutes are what gets charged"
    )


# ============================================================================
# 4. Unattributed is priced at the value rate
# ============================================================================


async def test_a_call_we_could_not_attribute_is_billed_at_the_value_rate() -> None:
    """SURFACES §2b's honesty rule applied to revenue: billing the premium rate takes
    evidence, and the absence of evidence is not evidence of premium."""
    tenant_id = await _tenant()
    await _plan(tenant_id, included=0, value_rate=VALUE_RATE)
    await _bill_minutes(tenant_id, tier=None, minutes=30)

    summary = await _summary(tenant_id)
    assert summary["overage_minutes_value"] == Decimal("30.00")
    assert summary["overage_minutes_premium"] == Decimal("0.00")
    assert summary["overage_cost_inr"] == to_paise(Decimal("30") * VALUE_RATE)


# ============================================================================
# The invoice follows
# ============================================================================


async def test_the_invoice_shows_one_overage_line_without_a_value_rate() -> None:
    """The shape every invoice had before the column existed, and the shape every plan
    that quotes no value rate still has."""
    tenant_id = await _tenant()
    await _plan(tenant_id, included=0, value_rate=None)
    await _bill_minutes(tenant_id, tier="premium", minutes=10)
    await _bill_minutes(tenant_id, tier="value", minutes=10)

    async with tenant_session(tenant_id) as session:
        invoice = await build_invoice(session, tenant_id=tenant_id)
    overage = [i for i in invoice["line_items"] if "Extra calling" in i["description"]]
    assert len(overage) == 1
    assert overage[0]["amount_inr"] == to_paise(Decimal("20") * PREMIUM_RATE)


async def test_the_invoice_splits_into_two_lines_that_each_multiply_out() -> None:
    tenant_id = await _tenant()
    await _plan(tenant_id, included=0, value_rate=VALUE_RATE)
    await _bill_minutes(tenant_id, tier="premium", minutes=10)
    await _bill_minutes(tenant_id, tier="value", minutes=10)

    async with tenant_session(tenant_id) as session:
        invoice = await build_invoice(session, tenant_id=tenant_id)
        summary = await usage_summary(session, tenant_id=tenant_id)

    overage = [i for i in invoice["line_items"] if "Extra calling" in i["description"]]
    assert len(overage) == 2
    for line in overage:
        assert to_paise(line["qty"] * line["unit_inr"]) == line["amount_inr"], (
            "every line multiplies out — the one arithmetic a client does by hand"
        )
    assert sum(line["amount_inr"] for line in overage) == summary["overage_cost_inr"], (
        "the lines sum to the total the usage panel already showed the client"
    )
    assert invoice["subtotal_inr"] == sum(i["amount_inr"] for i in invoice["line_items"])


async def test_a_rung_with_no_minutes_gets_no_line() -> None:
    """A ₹0.00 line invites a dispute about nothing — the same reason a zero overage
    produces no line at all."""
    tenant_id = await _tenant()
    await _plan(tenant_id, included=0, value_rate=VALUE_RATE)
    await _bill_minutes(tenant_id, tier="value", minutes=15)

    async with tenant_session(tenant_id) as session:
        invoice = await build_invoice(session, tenant_id=tenant_id)
    overage = [i for i in invoice["line_items"] if "Extra calling" in i["description"]]
    assert len(overage) == 1 and "value voice" in overage[0]["description"]


# ============================================================================
# 5. No price is invented
# ============================================================================


def test_nothing_in_the_codebase_derives_a_retail_value_rate() -> None:
    """The founder decision this slice deliberately does NOT make. If a later change
    wants to seed a default it has to delete this test, which is the point: the deletion
    is the moment someone has to say where the number came from."""
    from pathlib import Path

    repo = Path(__file__).resolve().parent.parent
    offenders = []
    for path in (repo / "apps").rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#") or "overage_rate_value" not in stripped:
                continue
            # An assignment of a literal to the column is the shape a made-up default
            # takes. Reading it, storing None, or naming it in SQL is fine.
            if "overage_rate_value = " in stripped and "Decimal(" in stripped:
                offenders.append(f"{path}:{number}")
    assert offenders == [], f"a retail value rate must be a founder decision: {offenders}"


@pytest.mark.parametrize("rate", ["-0.0001", "-1"])
async def test_a_negative_value_rate_is_refused_by_the_schema(rate: str) -> None:
    """`ck_plans_overage_rate_value_nonnegative`. A negative rate is not a discount, it
    is a plan that pays the client to make calls."""
    from sqlalchemy.exc import IntegrityError

    tenant_id = await _tenant()
    await _plan(tenant_id, included=0, value_rate=None)
    with pytest.raises(IntegrityError):
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE plans SET overage_rate_value = :r WHERE tenant_id = :t"),
                {"r": Decimal(rate), "t": tenant_id},
            )
