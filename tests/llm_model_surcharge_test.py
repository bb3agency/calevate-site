"""`plans.llm_model_surcharge`: a client's model choice, as a price (D-455).

D-454 gave a client a picker over `AZURE_OPENAI_MODELS` and stamped the resolved model
onto every metered call (`usage_events.meta.llm_model` / `llm_model_source`). It did NOT
move any money: `plans` had no model column, `rates.prepaid_billed_inr` and
`service.priced_overage` price MINUTES at the plan's rate and take no model, so a client
could move their whole account onto a model that costs us 2.7x and their bill moved by
exactly ₹0.00.

The column added by migration `e4a91c6b02d7` closes that, in `overage_rate_value`'s exact
shape and with the same property making it safe on a live schema — the FIRST test here:

1. **NULL bills exactly as before.** Every plan row that existed on the day the column
   landed is NULL, so no client's invoice moved by a paisa. Asserted by pricing one month
   twice, once with the column NULL and once with it set, and requiring the NULL case to
   reproduce the pre-column arithmetic.
2. **PRICED FROM THE LEDGER STAMP, NEVER FROM `agents.llm_model`.** The live columns are
   editable from two screens in two realms; pricing off them would re-price every closed
   month the day a client switched, which is the exact defect the stamp exists to prevent.
3. **A MONTH THAT STRADDLES A SWITCH TOTALS EXACTLY** — some minutes surcharged, some not,
   and the invoice's own subtotal is the sum of the printed lines.
4. **A MODEL THE PLATFORM CHOSE IS NEVER SURCHARGED.** `llm_model_source = 'platform'`
   means nobody on the client's side picked anything, so an operator flipping
   `Settings.azure_openai_model` cannot raise every client's bill on the next call. This
   is the safety property of the whole feature and it is asserted, not assumed.
5. **The SQL and the Python agree about which minutes carry it.** Two spellings of one
   rule exist by necessity (a month is bucketed in the database, one call is bucketed in
   the meter), so they are run against each other over every model x source pair.
6. **No price is invented**, and the schema refuses a negative one.

CONCURRENCY: every test mints its own tenant and touches no global row.

Run: uv run pytest -q tests/llm_model_surcharge_test.py
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from unittest import mock
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing.invoice import build_invoice
from apps.api.billing.models import Plan
from apps.api.billing.rates import (
    BASE_RATE_LLM_MODEL,
    CLIENT_CHOSEN_LLM_SOURCES,
    is_surchargeable_llm_model,
    llm_surcharge_applies,
    llm_surcharge_billed_inr,
    surchargeable_models_are_dearer,
)
from apps.api.billing.service import (
    _SURCHARGED_MODEL_SQL,
    UNSURCHARGED_MODEL,
    _surcharge_binds,
    calling_revenue_inr,
    month_charges_inr,
    priced_llm_surcharge,
    to_paise,
    usage_summary,
)
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from calevate_shared.engine import (
    AZURE_OPENAI_MODELS,
    LLM_MODEL_NAMES,
    LLM_MODELS,
    SELECTABLE_LLM_MODELS,
    LlmModelSpec,
    LlmPrice,
)
from sqlalchemy import text
from tests.smoke_pipeline_test import _seed_tenant

OVERAGE_RATE = Decimal("8.0000")
SURCHARGE = Decimal("1.5000")

#: A model a client can pick that is NOT the one the plan's rate is struck at. `min` over
#: the difference rather than `next(iter(...))`, for `tests/llm_model_metering_test.py`'s
#: reason: string hashing is randomised per process, so an `iter` over a frozenset would
#: make WHICH model this suite exercises vary run to run the day a third one lands.
UPGRADED_MODEL = min(AZURE_OPENAI_MODELS - {BASE_RATE_LLM_MODEL})


async def _tenant() -> UUID:
    created = await admin_service.create_organization(
        name="Surcharge Clinic",
        slug=f"surcharge-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return UUID(str(created["id"]))


async def _plan(tenant_id: UUID, *, included: int, surcharge: Decimal | None) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO plans (id, tenant_id, monthly_fee, included_min, overage_rate, "
                "llm_model_surcharge, concurrency_ceiling, created_at, updated_at) "
                "VALUES (:i, :t, 1000.00, :inc, :rate, :sur, 10, now(), now())"
            ),
            {
                "i": uuid7(),
                "t": tenant_id,
                "inc": included,
                "rate": OVERAGE_RATE,
                "sur": surcharge,
            },
        )


async def _set_surcharge(tenant_id: UUID, surcharge: Decimal | None) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE plans SET llm_model_surcharge = :s WHERE tenant_id = :t"),
            {"s": surcharge, "t": tenant_id},
        )


async def _bill_minutes(
    tenant_id: UUID, *, minutes: int, model: str | None, source: str | None
) -> None:
    """Meter `minutes` of talk time carrying the D-454 stamp the pipeline writes.

    Written straight into `usage_events` rather than through `_meter` on purpose: this
    file is about the READER, and a fixture that could only reach the ledger through the
    writer would stop covering a row shape the writer no longer produces — a call metered
    before D-454 stamped anything, which is `model=None, source=None`.
    """
    async with tenant_session(tenant_id) as session:
        agent_id = uuid7()
        await session.execute(
            text(
                "INSERT INTO agents (id, tenant_id, name, direction, disclosure_line, "
                "ai_disclosure_line, recording_notice_line, status, engine, created_at, "
                "updated_at) VALUES (:a, :t, 'Surcharge', 'outbound', 'Idi AI assistant.', "
                "'Idi AI assistant.', 'This call is being recorded.', 'live', 'fake', now(), "
                "now())"
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
        meta: dict[str, str] = {"tts_tier": "premium", "tts_tier_source": "agent_config"}
        if model is not None:
            meta["llm_model"] = model
        if source is not None:
            meta["llm_model_source"] = source
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
                "meta": _json(meta),
            },
        )


def _json(value: dict[str, str]) -> str:
    import json

    return json.dumps(value)


async def _summary(tenant_id: UUID) -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        return await usage_summary(session, tenant_id=tenant_id)


# ============================================================================
# 1. The column: shape, no default, and NULL changing nothing
# ============================================================================


def test_the_column_is_nullable_money_and_carries_no_default() -> None:
    """A default here would be an invented price. `llm_cost_inr_per_minute` is what the
    dearer model costs US and says in as many words that it is not a client price, so a
    retail surcharge derived from it would be our margin published as a rate."""
    column = Plan.__table__.c.llm_model_surcharge
    assert column.nullable, "NULL is 'this plan quotes no model surcharge'"
    assert column.default is None and column.server_default is None
    assert (column.type.precision, column.type.scale) == (12, 4), (
        "the surcharge is added to `overage_rate`; a different precision beside it is a "
        "rounding argument waiting to happen (hard rule 7)"
    )


async def test_a_null_surcharge_bills_exactly_as_the_month_did_before_the_column() -> None:
    """THE property that makes this shippable. Every plan row in the database is NULL, so
    the same month must price identically with the column unset — including a month where
    every minute ran on the upgraded model, which is the only case that could differ."""
    tenant_id = await _tenant()
    await _plan(tenant_id, included=100, surcharge=None)
    await _bill_minutes(tenant_id, minutes=120, model=UPGRADED_MODEL, source="organization")

    unset = await _summary(tenant_id)
    assert unset["overage_minutes"] == Decimal("20.00")
    assert unset["overage_cost_inr"] == to_paise(Decimal("20") * OVERAGE_RATE)
    assert unset["llm_surcharge_rate_inr"] is None, "no default may be invented"
    assert unset["llm_surcharge_inr"] == Decimal("0.00")
    assert unset["llm_surcharge_minutes"] == Decimal("0.00")
    assert unset["llm_surcharge_models"] == []

    await _set_surcharge(tenant_id, SURCHARGE)
    priced = await _summary(tenant_id)
    # The BASE arithmetic is untouched — a surcharge adds, it does not replace.
    assert priced["overage_cost_inr"] == unset["overage_cost_inr"]
    assert priced["llm_surcharge_minutes"] == Decimal("120.00"), (
        "the surcharge is charged on every minute that ran on the upgraded model, "
        "including the ones inside the included allowance — those minutes cost us 2.7x "
        "too, and a surcharge that vanished under the allowance would leave the whole "
        "defect open for a managed client who never goes into overage"
    )
    assert priced["llm_surcharge_inr"] == to_paise(Decimal("120") * SURCHARGE)
    assert priced["llm_surcharge_models"] == [UPGRADED_MODEL]


async def test_a_zero_surcharge_is_not_the_same_fact_as_an_unquoted_one() -> None:
    """Both charge ₹0.00 and neither prints a line; what differs is the RATE published,
    which is how a screen tells 'we give the upgrade away' from 'nobody has decided'."""
    tenant_id = await _tenant()
    await _plan(tenant_id, included=0, surcharge=Decimal("0"))
    await _bill_minutes(tenant_id, minutes=10, model=UPGRADED_MODEL, source="agent")

    summary = await _summary(tenant_id)
    assert summary["llm_surcharge_rate_inr"] == Decimal("0.00")
    assert summary["llm_surcharge_inr"] == Decimal("0.00")

    await _set_surcharge(tenant_id, None)
    assert (await _summary(tenant_id))["llm_surcharge_rate_inr"] is None


# ============================================================================
# 2. WHICH minutes carry it — the stamp, and the two spellings of the rule
# ============================================================================


def test_only_a_model_the_client_chose_is_surcharged() -> None:
    """The safety property. `platform` means nobody on the client's side picked anything,
    so flipping `Settings.azure_openai_model` must not raise every client's bill."""
    assert llm_surcharge_applies(model=UPGRADED_MODEL, source="agent")
    assert llm_surcharge_applies(model=UPGRADED_MODEL, source="organization")
    assert not llm_surcharge_applies(model=UPGRADED_MODEL, source="platform"), (
        "an upgrade WE imposed is our cost, not a charge — a client who never touched "
        "the picker must not be billed for an operator's console switch"
    )
    assert not llm_surcharge_applies(model=BASE_RATE_LLM_MODEL, source="agent")
    assert not llm_surcharge_applies(model=None, source=None), (
        "a row written before D-454 stamped a model carries neither key, and the absence "
        "of evidence is never evidence of the dearer thing"
    )


def test_the_baseline_is_the_frozen_constant_and_not_the_live_setting() -> None:
    """If it read `Settings.azure_openai_model`, flipping the platform default would
    silently re-classify every historical minute — throwing away the exact property the
    ledger stamp exists to give."""
    from calevate_shared.engine import AZURE_OPENAI_DEFAULT_MODEL

    assert BASE_RATE_LLM_MODEL == AZURE_OPENAI_DEFAULT_MODEL
    assert not is_surchargeable_llm_model(BASE_RATE_LLM_MODEL)
    assert all(is_surchargeable_llm_model(m) for m in AZURE_OPENAI_MODELS - {BASE_RATE_LLM_MODEL})


def test_every_model_the_surcharge_applies_to_actually_costs_us_more() -> None:
    """The consistency check between two statements of one rule.

    It used to be a TRIPWIRE under a crude predicate — `is_surchargeable_llm_model` tested
    "not the base model", and this was designed to fail the day a cheaper model joined the
    choosable set. One did. The fix was to correct the predicate rather than to widen this,
    so what it now guards is that the predicate and the price table still agree.
    """
    assert surchargeable_models_are_dearer(), (
        "a model the surcharge applies to is not dearer than the base-rate one on both "
        "token legs; `is_surchargeable_llm_model` has stopped meaning 'an upgrade'"
    )


def test_a_model_cheaper_than_the_base_rate_is_not_surcharged() -> None:
    """**THE INVERSION, PINNED — a client must never be charged an upgrade for saving us
    money.**

    This is not hypothetical and it is not a future guard: `gemini-2.5-flash-lite` lists at
    $0.10/$0.40 against the base model's $0.15/$0.60, so it is CHEAPER on both token legs and
    the old "not the base model" predicate would have surcharged it. A charge for an upgrade
    that was a downgrade is not a pricing disagreement — it is a charge for something we did
    not supply.

    **AND THERE IS NO NEGATIVE ARM.** A cheaper model is not a credit either: what a client
    PAYS is a term of their plan set by a founder, never a figure derived from our supplier
    cost (D-455). The surcharge floors at zero and the client keeps their plan's rate.

    FAILS IF: the predicate goes back to comparing identifiers instead of prices, or the
    catalogue loses the model that makes the case real.
    """
    cheaper = [
        model
        for model in SELECTABLE_LLM_MODELS
        if LLM_MODELS[model].price.input_usd_per_mtok
        < LLM_MODELS[BASE_RATE_LLM_MODEL].price.input_usd_per_mtok
    ]
    assert cheaper, (
        "no selectable model is cheaper than the base rate any more, so this test proves "
        "nothing — do not delete it, find out whether the cheap leg was withdrawn"
    )
    for model in cheaper:
        assert not is_surchargeable_llm_model(model), model
        assert not llm_surcharge_applies(model=model, source="agent"), model


def test_a_model_dearer_on_one_leg_and_cheaper_on_the_other_is_not_surcharged() -> None:
    """Both legs must be dearer, not their blend.

    A model cheaper on input and dearer on output is not a straightforward upgrade: which way
    it lands depends on a conversation's shape rather than on a rate card, and that is a
    founder's decision rather than a predicate's. The default is therefore the one that
    cannot overcharge.
    """
    base = LLM_MODELS[BASE_RATE_LLM_MODEL].price
    mixed = LlmModelSpec(
        model="gpt-mixed-fixture",
        provider="azure_openai",
        price=LlmPrice(
            input_usd_per_mtok=base.input_usd_per_mtok / 2,
            output_usd_per_mtok=base.output_usd_per_mtok * 2,
            evidence=base.evidence,
        ),
        traps=(),
        selectable=True,
        withdrawn_reason=None,
    )
    with mock.patch.dict(LLM_MODELS, {mixed.model: mixed}):
        assert not is_surchargeable_llm_model(mixed.model)


@pytest.mark.parametrize("model", [*sorted(LLM_MODEL_NAMES), "", "gpt-retired-9"])
@pytest.mark.parametrize("source", ["agent", "organization", "platform", ""])
async def test_the_sql_and_the_python_bucket_a_row_identically(model: str, source: str) -> None:
    """The twin, guarded rather than trusted.

    `_SURCHARGED_MODEL_SQL` buckets a whole month in the database; `pipeline._meter` has
    to place ONE call in the same buckets in Python before that month is re-read. Two
    spellings of one rule is the defect this repository has paid for repeatedly, so they
    are run against each other over every pair — including a model identifier the
    allow-list no longer carries, which is what a historical row looks like.
    """
    tenant_id = await _tenant()
    meta: dict[str, str] = {}
    if model:
        meta["llm_model"] = model
    if source:
        meta["llm_model_source"] = source
    async with tenant_session(tenant_id) as session:
        answer = (
            await session.execute(
                text(f"SELECT {_SURCHARGED_MODEL_SQL} FROM (SELECT CAST(:m AS jsonb) AS meta) r"),
                # The fragment's own binds, from the one helper the production callers
                # use. Spelling them here instead would make this twin agree with a rule
                # nobody ships — the failure mode the test exists to refuse, one level up.
                {"m": _json(meta), **_surcharge_binds()},
            )
        ).scalar()
    expected = (
        model
        if llm_surcharge_applies(model=model or None, source=source or None)
        else UNSURCHARGED_MODEL
    )
    assert str(answer) == expected, (
        f"SQL and Python disagree about ({model!r}, {source!r}): the month's buckets and "
        "the meter's would drift, and `spend_state.billed_inr` would stop telescoping"
    )


async def test_the_price_comes_from_the_ledger_and_not_from_the_live_agent_row() -> None:
    """Switching model must not re-price a month that has already run.

    The call below is stamped `platform`, so it carries no surcharge. Setting the ACCOUNT
    onto the upgraded model afterwards — which is what a client does on the settings
    screen — must leave that month exactly where it was.
    """
    tenant_id = await _tenant()
    await _plan(tenant_id, included=0, surcharge=SURCHARGE)
    await _bill_minutes(tenant_id, minutes=30, model=BASE_RATE_LLM_MODEL, source="platform")
    before = await _summary(tenant_id)

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET default_llm_model = :m WHERE id = :t"),
            {"m": UPGRADED_MODEL, "t": tenant_id},
        )
    after = await _summary(tenant_id)
    assert after["llm_surcharge_inr"] == before["llm_surcharge_inr"] == Decimal("0.00")
    assert after["llm_surcharge_models"] == before["llm_surcharge_models"] == []


# ============================================================================
# 3. A month that straddles a switch
# ============================================================================


async def test_a_month_that_straddles_a_model_switch_totals_exactly() -> None:
    """The obvious place for a wrong total: some minutes at one surcharge and some at
    another, in one month, on one statement."""
    tenant_id = await _tenant()
    await _plan(tenant_id, included=0, surcharge=SURCHARGE)
    # 40 minutes on the base model, then the client switches and runs 25 more.
    await _bill_minutes(tenant_id, minutes=40, model=BASE_RATE_LLM_MODEL, source="organization")
    await _bill_minutes(tenant_id, minutes=25, model=UPGRADED_MODEL, source="organization")

    summary = await _summary(tenant_id)
    assert summary["minutes_used"] == Decimal("65.00")
    assert summary["llm_surcharge_minutes"] == Decimal("25.00"), (
        "only the minutes after the switch carry it — the ones before ran on the model "
        "the plan's rate is struck at"
    )
    assert summary["llm_surcharge_inr"] == to_paise(Decimal("25") * SURCHARGE)
    assert summary["overage_cost_inr"] == to_paise(Decimal("65") * OVERAGE_RATE), (
        "the base arithmetic prices every minute, surcharged or not"
    )
    # What the client owes for the month's calling, both halves, from the one function
    # that answers it for the invoice and for the margin panel alike.
    assert to_paise(
        calling_revenue_inr(
            plan_tier="managed",
            minutes=summary["minutes_used"],
            overage_cost_inr=summary["overage_cost_inr"],
            llm_surcharge_inr=summary["llm_surcharge_inr"],
        )
    ) == to_paise(Decimal("65") * OVERAGE_RATE + Decimal("25") * SURCHARGE)


async def test_the_surcharged_minutes_are_a_part_of_the_months_own_minutes() -> None:
    """Both partitions of the month are allocated over the SAME total, so the surcharged
    share can never exceed — or fail to be a part of — what the panel publishes."""
    tenant_id = await _tenant()
    await _plan(tenant_id, included=0, surcharge=SURCHARGE)
    # Durations chosen so seconds/60 does not land on a paisa boundary in any bucket.
    for seconds, model in ((7, BASE_RATE_LLM_MODEL), (41, UPGRADED_MODEL), (211, UPGRADED_MODEL)):
        await _bill_seconds(tenant_id, seconds=seconds, model=model)

    summary = await _summary(tenant_id)
    assert Decimal("0") < summary["llm_surcharge_minutes"] < summary["minutes_used"]
    assert summary["llm_surcharge_inr"] == to_paise(summary["llm_surcharge_minutes"] * SURCHARGE), (
        "the published total is the published minutes times the published rate, exactly"
    )


async def _bill_seconds(tenant_id: UUID, *, seconds: int, model: str) -> None:
    """A call of an awkward length, so the paise allocation actually has a remainder."""
    async with tenant_session(tenant_id) as session:
        agent_id = uuid7()
        await session.execute(
            text(
                "INSERT INTO agents (id, tenant_id, name, direction, disclosure_line, "
                "ai_disclosure_line, recording_notice_line, status, engine, created_at, "
                "updated_at) VALUES (:a, :t, 'Surcharge', 'outbound', 'Idi AI assistant.', "
                "'Idi AI assistant.', 'This call is being recorded.', 'live', 'fake', now(), "
                "now())"
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
                "qty": seconds,
                "meta": _json(
                    {
                        "tts_tier": "premium",
                        "tts_tier_source": "agent_config",
                        "llm_model": model,
                        "llm_model_source": "organization",
                    }
                ),
            },
        )


# ============================================================================
# 4. The invoice says which choice caused the number
# ============================================================================


async def test_the_invoice_carries_its_own_line_naming_the_model() -> None:
    """A client seeing a bigger number must be able to see the line that caused it — and
    the line has to multiply out, because that is the first arithmetic anyone checks."""
    tenant_id = await _tenant()
    await _plan(tenant_id, included=10, surcharge=SURCHARGE)
    await _bill_minutes(tenant_id, minutes=50, model=UPGRADED_MODEL, source="agent")

    async with tenant_session(tenant_id) as session:
        invoice = await build_invoice(session, tenant_id=tenant_id)

    upgrade = [item for item in invoice["line_items"] if "AI model upgrade" in item["description"]]
    assert len(upgrade) == 1, "one surcharge rate means one line, whatever models ran"
    (line,) = upgrade
    assert UPGRADED_MODEL in line["description"], "the client's own choice, named"
    assert line["qty"] == Decimal("50.00")
    assert line["unit_inr"] == SURCHARGE
    assert line["amount_inr"] == to_paise(Decimal("50") * SURCHARGE)
    assert to_paise(line["qty"] * line["unit_inr"]) == line["amount_inr"], (
        "every line multiplies out — the promise `billing/invoice.py` makes in its module docstring"
    )
    # Rule 46(g): the SAC is on every line, so the document stays a valid tax invoice.
    assert {item["sac"] for item in invoice["line_items"]} == {invoice["supplier"]["sac"]}
    assert invoice["subtotal_inr"] == to_paise(
        sum((item["amount_inr"] for item in invoice["line_items"]), Decimal("0"))
    ), "the subtotal is the sum of the lines and nothing else"
    assert invoice["total_inr"] == to_paise(invoice["subtotal_inr"] + invoice["gst_inr"])


async def test_an_unsurcharged_month_prints_no_upgrade_line() -> None:
    """A ₹0.00 line invites a dispute about nothing — the same rule the overage follows."""
    tenant_id = await _tenant()
    await _plan(tenant_id, included=0, surcharge=None)
    await _bill_minutes(tenant_id, minutes=5, model=UPGRADED_MODEL, source="agent")
    async with tenant_session(tenant_id) as session:
        invoice = await build_invoice(session, tenant_id=tenant_id)
    assert not [i for i in invoice["line_items"] if "AI model upgrade" in i["description"]]


# ============================================================================
# 5. The counter the cap is judged on moves with the bill
# ============================================================================


async def test_the_live_counter_accrues_the_surcharge_the_invoice_charges() -> None:
    """`spend_state.billed_inr` is what the compliance gate's ceiling is compared against.
    If the surcharge reached the invoice and not the counter, a client's stop button would
    stop them later than their bill justified — the P1.3 shape, on a new rate.

    Metered through the real pipeline, because the counter is the writer's output.
    """
    from apps.workers.pipeline import _meter
    from tests.llm_model_metering_test import _snapshot

    tenant_id, agent_id = await _seed_tenant(f"fakeagent_sur_{uuid.uuid4().hex[:8]}")
    await _plan(tenant_id, included=0, surcharge=SURCHARGE)
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET llm_model = CAST(:m AS text) WHERE id = :a"),
            {"m": UPGRADED_MODEL, "a": agent_id},
        )
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                "to_e164, status, created_at, updated_at) VALUES (:i, :t, :a, :e, 'outbound', "
                "'+919876500001', 'completed', now(), now())"
            ),
            {"i": call_id, "t": tenant_id, "a": agent_id, "e": f"exec_{uuid.uuid4().hex[:12]}"},
        )
    await _meter(tenant_id, call_id, _snapshot())

    async with tenant_session(tenant_id) as session:
        billed = (
            await session.execute(
                text("SELECT billed_inr FROM spend_state WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar()
        summary = await usage_summary(session, tenant_id=tenant_id)
    assert summary["llm_surcharge_inr"] > Decimal("0"), "the fixture call ran the upgrade"
    assert Decimal(str(billed)) == to_paise(
        summary["overage_cost_inr"] + summary["llm_surcharge_inr"]
    ), "the counter and the statement must be about the same rupees"


async def test_the_counter_telescopes_across_a_model_switch_mid_month() -> None:
    """TWO calls, a model switch between them, metered through the real pipeline.

    `month_increment` computes the surcharge as a DIFFERENCE of two month totals rather
    than as `this call's minutes x the rate`, exactly like the overage beside it, and this
    is the property that buys: however many calls meter and in whatever order, the running
    `spend_state.billed_inr` equals the month's own figure — the one the invoice prints.
    A per-call product would drift from it by the accumulated paise-allocation remainder,
    and the drift only ever grows within a month.
    """
    from apps.workers.pipeline import _meter
    from tests.llm_model_metering_test import _snapshot

    tenant_id, agent_id = await _seed_tenant(f"fakeagent_tel_{uuid.uuid4().hex[:8]}")
    await _plan(tenant_id, included=0, surcharge=SURCHARGE)

    async def _one_call(model: str | None) -> None:
        call_id = uuid7()
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE agents SET llm_model = CAST(:m AS text) WHERE id = :a"),
                {"m": model, "a": agent_id},
            )
            await session.execute(
                text(
                    "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                    "to_e164, status, created_at, updated_at) VALUES (:i, :t, :a, :e, "
                    "'outbound', '+919876500001', 'completed', now(), now())"
                ),
                {"i": call_id, "t": tenant_id, "a": agent_id, "e": f"exec_{uuid.uuid4().hex[:12]}"},
            )
        await _meter(tenant_id, call_id, _snapshot())

    # One call on the base model — the agent names none, so the account default (none)
    # falls through to the PLATFORM, which is never surcharged.
    await _one_call(None)
    # The client then puts this agent on the upgrade. Only the SECOND call carries it.
    await _one_call(UPGRADED_MODEL)

    async with tenant_session(tenant_id) as session:
        billed = (
            await session.execute(
                text("SELECT billed_inr FROM spend_state WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar()
        summary = await usage_summary(session, tenant_id=tenant_id)

    assert summary["llm_surcharge_minutes"] < summary["minutes_used"], (
        "only the call after the switch carries the surcharge"
    )
    assert summary["llm_surcharge_models"] == [UPGRADED_MODEL]
    assert Decimal(str(billed)) == to_paise(
        summary["overage_cost_inr"] + summary["llm_surcharge_inr"]
    ), "the running counter is the month's own figure, not a sum of per-call products"


# ============================================================================
# 6. Isolation, refusals, and the decision nobody made for the founder
# ============================================================================


async def test_a_second_tenant_can_neither_read_nor_write_this_tenants_surcharge() -> None:
    """A column is not a separate security object, so `plans`' FORCEd `tenant_isolation`
    policy covers it — asserted rather than assumed (hard rule 1)."""
    mine = await _tenant()
    theirs = await _tenant()
    await _plan(mine, included=0, surcharge=SURCHARGE)

    async with tenant_session(theirs) as session:
        rows = (
            await session.execute(
                text("SELECT llm_model_surcharge FROM plans WHERE tenant_id = :t"), {"t": mine}
            )
        ).all()
        assert rows == []
        result = await session.execute(
            text("UPDATE plans SET llm_model_surcharge = 99 WHERE tenant_id = :t"), {"t": mine}
        )
        assert result.rowcount == 0

    async with tenant_session(mine) as session:
        still = (
            await session.execute(
                text("SELECT llm_model_surcharge FROM plans WHERE tenant_id = :t"), {"t": mine}
            )
        ).scalar()
    assert Decimal(str(still)) == SURCHARGE


@pytest.mark.parametrize("value", ["-0.0001", "-1"])
async def test_a_negative_surcharge_is_refused_by_the_schema(value: str) -> None:
    """`ck_plans_llm_model_surcharge_nonnegative`. A negative surcharge is not a discount
    for choosing the expensive model — it is a typo that would read as one, and it would
    let a model choice price a minute below the plan's own rate."""
    from sqlalchemy.exc import IntegrityError

    tenant_id = await _tenant()
    await _plan(tenant_id, included=0, surcharge=None)
    with pytest.raises(IntegrityError):
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE plans SET llm_model_surcharge = :s WHERE tenant_id = :t"),
                {"s": Decimal(value), "t": tenant_id},
            )


def test_nothing_in_the_codebase_derives_a_retail_model_surcharge() -> None:
    """The founder decision this slice deliberately does NOT make. Deleting this test is
    the moment somebody has to say where the number came from."""
    from pathlib import Path

    repo = Path(__file__).resolve().parent.parent
    offenders = []
    for path in (repo / "apps").rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#") or "llm_model_surcharge" not in stripped:
                continue
            if "llm_model_surcharge = " in stripped and "Decimal(" in stripped:
                offenders.append(f"{path}:{number}")
    assert offenders == [], f"a retail model surcharge must be a founder decision: {offenders}"


def test_the_pricing_function_refuses_to_charge_for_an_unsurcharged_bucket() -> None:
    """`UNSURCHARGED_MODEL` holds every minute the plan does not surcharge, and it is
    handed IN so the surcharged share is visibly a part of the month — it must never be
    charged for."""
    priced = priced_llm_surcharge(
        minutes_by_model={UNSURCHARGED_MODEL: Decimal("500.00"), UPGRADED_MODEL: Decimal("10.00")},
        surcharge=SURCHARGE,
    )
    assert priced.minutes == Decimal("10.00")
    assert priced.models == (UPGRADED_MODEL,)
    assert priced.total_inr == to_paise(Decimal("10") * SURCHARGE)


def test_the_client_chosen_sources_are_exactly_the_two_that_mean_a_client_chose() -> None:
    """Read off `agents/llm_models.LlmModelSource` rather than retyped: a fourth level
    (a campaign override, a per-lane choice) must be classified deliberately, not
    inherited by whichever set happens to list it."""
    from apps.api.agents.llm_models import LLM_MODEL_SOURCES

    assert set(LLM_MODEL_SOURCES) > CLIENT_CHOSEN_LLM_SOURCES, (
        "every surcharge-bearing source must be a real resolution level, and at least one "
        "level (`platform`) must stay outside it"
    )
    assert set(LLM_MODEL_SOURCES) - CLIENT_CHOSEN_LLM_SOURCES == {"platform"}


@pytest.mark.parametrize(
    ("minutes", "surcharge", "expected"),
    [
        # THE ARM THE RATCHET FOUND UNCOVERED, and the reason it matters: this is the only
        # line in the surcharge path that MULTIPLIES money. Everything above it returns a
        # quantized zero, so a defect in the product itself — a lost paisa, a float, a
        # rounding mode — would have been invisible while every other test passed.
        ("10.00", "1.5000", "15.0000"),
        # A third of a rupee against a third of a minute: neither operand is representable
        # in binary floating point, so `float` arithmetic answers 0.11110000000000001 here.
        # Decimal answers exactly, and the quantize is the only rounding that happens.
        ("0.3333", "0.3333", "0.1111"),
        # The rounding mode, pinned by a case that DISTINGUISHES it rather than one any
        # mode would pass. 1.00005 is exactly half a paisa: ROUND_HALF_UP — what this repo
        # quantizes money with, and the convention Indian invoicing expects — answers
        # 1.0001, where ROUND_HALF_EVEN would answer 1.0000 because the preceding digit is
        # even. A run that started answering 1.0000 here would have changed the rounding
        # of every client's money without failing anything else.
        ("1.0000", "1.00005", "1.0001"),
    ],
)
def test_a_real_surcharge_multiplies_exactly_and_rounds_the_way_the_invoice_does(
    minutes: str, surcharge: str, expected: str
) -> None:
    """`llm_surcharge_billed_inr`'s non-zero arm, driven for the first time.

    `apps/workers/pipeline.py` calls this on the prepaid wallet debit, so the value it
    returns is money leaving a client's balance. The three zero arms below are cheap to
    reach and were already covered; this one costs a client real paise and was not.

    FAILS IF: the multiply goes through a float, the quantize is dropped, or the rounding
    mode moves off ROUND_HALF_UP.
    """
    answer = llm_surcharge_billed_inr(minutes=Decimal(minutes), surcharge=Decimal(surcharge))
    assert answer == Decimal(expected)
    assert str(answer) == expected, "the scale itself is the contract, not just the value"


@pytest.mark.parametrize(
    ("minutes", "surcharge"),
    [
        ("10.00", None),  # the plan quotes none
        ("10.00", "0.0000"),  # the plan gives the upgrade away
        ("0.00", "1.5000"),  # nothing ran
        ("-5.00", "1.5000"),  # a correction that took minutes back off the month
    ],
)
def test_nothing_is_billed_when_there_is_no_surcharge_or_no_minutes(
    minutes: str, surcharge: str | None
) -> None:
    """All four refusals answer a quantized ZERO rather than `Decimal(0)`.

    The scale matters downstream: these values are summed with quantized siblings and
    handed to `to_paise`, and a bare `Decimal("0")` would make an invoice line's scale
    depend on whether a plan happened to quote a surcharge.
    """
    answer = llm_surcharge_billed_inr(
        minutes=Decimal(minutes),
        surcharge=None if surcharge is None else Decimal(surcharge),
    )
    assert answer == Decimal("0")
    assert str(answer) == "0.0000"


@pytest.mark.parametrize(
    ("fee", "overage", "surcharge", "expected"),
    [
        # The shipped shape: a managed plan, no surcharge quoted anywhere yet.
        ("4999.00", "10159.00", "0.0000", "15158.0000"),
        # The case D-455 exists for, and the one a browser sum got wrong for a while: an
        # account INSIDE its allowance whose own model choice still costs it money. The
        # total is neither zero nor the retainer.
        ("4999.00", "0.00", "180.7500", "5179.7500"),
        # Mid-onboarding: no plan row, so no retainer. None is not zero and must not be
        # read as one — the total is then the calling alone.
        (None, "0.00", "60.0000", "60.0000"),
    ],
)
def test_the_month_total_is_the_three_published_components_and_nothing_else(
    fee: str | None, overage: str, surcharge: str, expected: str
) -> None:
    """`month_charges_inr` on the managed motion, where `calling_revenue_inr` passes the
    overage straight through.

    WHY THIS TEST IS HERE AND NOT ONLY IN A SCREEN TEST. Until this function existed the
    addition happened in the BROWSER, over the three fields the panel publishes — and a
    total computed in a language with one numeric type is a second implementation of a
    bill. The arithmetic now has one home and this is what pins it: the three components a
    client can read off their own panel must add to the figure printed beside them, exactly,
    with no fourth term and nothing dropped.

    FAILS IF: a component stops being included (the retainer and the surcharge have each
    been omitted from a "spend this month" figure in this repo's history), a `None` fee is
    read as anything but nothing, or the sum starts rounding before its caller asks it to.
    """
    answer = month_charges_inr(
        monthly_fee_inr=None if fee is None else Decimal(fee),
        plan_tier="managed",
        minutes=Decimal("120.50"),
        overage_cost_inr=Decimal(overage),
        llm_surcharge_inr=Decimal(surcharge),
    )
    assert answer == Decimal(expected)


def test_the_client_total_and_the_admin_revenue_are_the_same_expression() -> None:
    """What a client owes and what we book are one number seen from two sides.

    They were two expressions in two modules — `usage_summary` published components and no
    total while `margin_for_tenant` summed its own revenue — which is precisely how a
    panel and a margin report come to disagree about a month. `margin_for_tenant` now
    calls this function, and this asserts the identity directly so that stays true if
    somebody re-inlines it.
    """
    fee, overage, surcharge = Decimal("4999.00"), Decimal("10159.00"), Decimal("60.0000")
    assert month_charges_inr(
        monthly_fee_inr=fee,
        plan_tier="managed",
        minutes=Decimal("120.50"),
        overage_cost_inr=overage,
        llm_surcharge_inr=surcharge,
    ) == fee + calling_revenue_inr(
        plan_tier="managed",
        minutes=Decimal("120.50"),
        overage_cost_inr=overage,
        llm_surcharge_inr=surcharge,
    )


def test_the_total_is_unquantized_so_its_two_callers_can_round_once_each() -> None:
    """The panel quantizes to paise; the margin panel subtracts a cost first and divides.

    A pre-rounded return would round twice on the margin path and could move a paisa —
    the same argument `calling_revenue_inr` makes one function down about
    `prepaid_billed_inr`. Driven with a fee carrying a sub-paise fraction, which is
    ordinary rather than exotic: `MONEY_Q` is four decimals.
    """
    answer = month_charges_inr(
        monthly_fee_inr=Decimal("0.0001"),
        plan_tier="managed",
        minutes=Decimal("1.00"),
        overage_cost_inr=Decimal("0.0002"),
        llm_surcharge_inr=Decimal("0.0000"),
    )
    assert answer == Decimal("0.0003"), "the fraction survives the addition"


@pytest.fixture(autouse=True)
def _gst_registered_supplier(monkeypatch: pytest.MonkeyPatch):
    """Register a specimen GST supplier for this suite.

    These tests assert the TAX-INVOICE arithmetic (18% GST split into heads), which is only
    lawful once Calevate is GST-registered. An UNregistered supplier now issues a bill of
    supply with no tax (CGST s.32, Rule 49; billing/invoice.py), so without a registered
    supplier ``gst_inr`` would be zero and these arithmetic assertions would test nothing.
    The specimen GSTIN is Telangana (36) so an intra-State supply splits into CGST+SGST.
    """
    from apps.api.core.settings import get_settings

    monkeypatch.setenv("GST_SUPPLIER_LEGAL_NAME", "Calevate")
    monkeypatch.setenv("GST_SUPPLIER_ADDRESS", "Plot 42, Madhapur, Hyderabad 500081")
    monkeypatch.setenv("GST_SUPPLIER_GSTIN", "36AABCC1234D1Z5")
    monkeypatch.setenv("GST_SUPPLY_SAC", "998315")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
