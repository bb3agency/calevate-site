"""The INR cost model for the LLM legs: TWO models, TWO prices, and no silent default.

D-410 replaced one shipped model (`gemini-2.5-flash`, one price pair) with a pair of
Azure OpenAI models an operator switches between LIVE — `gpt-4o-mini` by default,
`gpt-4.1-mini` one console edit away and 2.7x dearer on both legs. The prices moving is
the boring half of that. The half this file exists for is the ARITY:

**a cost function that prices the DEFAULT model while the deployment runs the OTHER one
is a metering defect with no other detector.** It is not a crash, it does not fail a type
check, it does not look wrong in a diff, and it passes every test that never flips the
switch — while under-reporting the leg by 63% on every call and writing rows onto an
APPEND-ONLY ledger (hard rule 4) that cannot be corrected in place afterwards. The same
shape has already cost this repository twice on the money axis (D-103, D-105): one
identifier changing under a constant nobody re-derived.

So the whole cost chain takes the model EXPLICITLY, none of it defaults, and this file is
what keeps it that way:

1. every model an operator can select is priced, and every price is for a selectable
   model — no `ValueError` at metering time, no price rotting unread;
2. every rupee figure derives from the ONE published dollar price and the ONE exchange
   rate, so a vendor price move is a one-line change;
3. no entry point in the chain has a default for `model` — asserted from the SIGNATURES,
   because that is the property, not a consequence of one;
4. the two models are genuinely priced apart, which is what makes every assertion above
   capable of failing;
5. the assist meter cannot be handed a price at all, so a ledger row's `unit_cost_paid`
   cannot disagree with its own `meta.model`.

Money is `Decimal` end to end (hard rule 7) and this file compares no float.

WHERE THE DB-BACKED HALF LIVES: `tests/ai_quota_test.py`, which meters real assists on
both models and asserts the rows. This file is pure arithmetic and signatures, so it runs
without a database and fails first when the chain is wrong.
"""

from __future__ import annotations

import dataclasses
import inspect
from decimal import Decimal
from typing import Any

import pytest
from apps.api.billing.ai_quota import (
    AiQuota,
    assist_nominal_inr,
    record_ai_assist_usage,
    reference_assist_cost_inr,
)
from apps.api.billing.rates import (
    LIST_PRICE_USD_INR,
    MONEY_Q,
    PRICED_LLM_MODELS,
    ROUNDING,
    llm_cost_inr_per_minute,
    llm_inr_per_ktok,
)
from apps.api.core.settings import get_settings
from calevate_shared.engine import (
    AZURE_LIST_PRICE_USD_PER_MTOK,
    AZURE_OPENAI_DEFAULT_MODEL,
    AZURE_OPENAI_MODELS,
)

#: The published curve, ₹/min at 1, 5 and 10 minutes, per model — the six figures TRD
#: §10.1 quotes and `scripts/check_docs_drift.py` scores the doc against.
#:
#: PINNED AS LITERALS ON PURPOSE, exactly as `tests/ai_quota_test.py` pins the reference
#: assist: this is the number a founder reasons about margin from and the number a doc
#: repeats in prose, so a change to the price table, the exchange rate, the reference
#: conversation or the rounding mode must be a deliberate edit to this block rather than
#: something a derivation quietly absorbs. A test that re-derived the figure would pass on
#: any of those changes and tell nobody the published number had moved.
PUBLISHED_CURVE: dict[str, dict[int, Decimal]] = {
    "gpt-4o-mini": {1: Decimal("0.1021"), 5: Decimal("0.1639"), 10: Decimal("0.2411")},
    "gpt-4.1-mini": {1: Decimal("0.2734"), 5: Decimal("0.4389"), 10: Decimal("0.6457")},
}

#: What the retired `gemini-2.5-flash` leg cost per minute at the same three points, at
#: the same exchange rate ($0.30 in / $2.50 out per 1M tokens). Kept as a literal so the
#: claim D-410 was taken on — "cheaper than Gemini 2.5 Flash on both legs" — is checked
#: rather than repeated, and so a regression that quietly restored the old prices under
#: new identifiers would be named.
RETIRED_GEMINI_CURVE: dict[int, Decimal] = {
    1: Decimal("0.2310"),
    5: Decimal("0.3550"),
    10: Decimal("0.5100"),
}


# --- 1. the price table covers exactly the models the console can select ---------------


def test_every_model_an_operator_can_select_has_a_published_price() -> None:
    """Both directions, and each is a different failure.

    A selectable model with no price is a `ValueError` on the FIRST assist after somebody
    flips `Settings.azure_openai_model` — the worst possible moment, because the switch is
    live and nobody redeployed. A price for a model nobody can select is a number that
    rots unread until it is quoted somewhere by mistake.
    """
    assert PRICED_LLM_MODELS == AZURE_OPENAI_MODELS
    assert set(AZURE_LIST_PRICE_USD_PER_MTOK) == AZURE_OPENAI_MODELS
    assert AZURE_OPENAI_DEFAULT_MODEL in PRICED_LLM_MODELS
    assert set(PUBLISHED_CURVE) == AZURE_OPENAI_MODELS, (
        "a model was added or removed and this file's published curve was not updated"
    )


def test_the_rupee_table_derives_from_the_one_published_dollar_price() -> None:
    """The derivation, not the numbers, so the test survives a price change and the
    numbers do not.

    The defect it exists for: INR literals with the exchange rate already folded in. Two
    surfaces price the same models (the in-call leg and the dashboard assist), the vendor
    publishes dollars, and a constant that has already multiplied cannot be corrected when
    either half moves.
    """
    for model, usd in AZURE_LIST_PRICE_USD_PER_MTOK.items():
        inr = llm_inr_per_ktok(model)
        assert set(inr) == {"in", "out"}, model
        for leg, usd_per_mtok in usd.items():
            expected = (usd_per_mtok * LIST_PRICE_USD_INR / Decimal("1000")).quantize(
                MONEY_Q, rounding=ROUNDING
            )
            assert inr[leg] == expected, f"{model}/{leg}"
            # NUMERIC(12,4) is what `unit_cost_paid` stores; a fifth decimal is a price
            # the ledger would silently round.
            assert inr[leg] == inr[leg].quantize(MONEY_Q)
            assert inr[leg] > 0


def test_the_two_models_are_priced_far_enough_apart_to_be_worth_distinguishing() -> None:
    """THE NON-VACUITY GUARD for everything else in this file.

    Every assertion about "the wrong model was priced" can only fail if the two prices
    differ, so the difference is asserted directly rather than assumed. It is also the
    fact the whole design rests on: at 2.6x, pricing the default while running the other
    model is not a rounding error on a margin table — it is most of the leg.
    """
    cheap = llm_inr_per_ktok(AZURE_OPENAI_DEFAULT_MODEL)
    other = next(iter(AZURE_OPENAI_MODELS - {AZURE_OPENAI_DEFAULT_MODEL}))
    dear = llm_inr_per_ktok(other)
    for leg in ("in", "out"):
        assert dear[leg] / cheap[leg] > Decimal("2.5"), (
            f"the {leg} leg no longer separates the two models; every drift assertion in "
            "this file is now vacuous and the design that made the model explicit needs "
            "re-arguing, not this threshold lowering"
        )


# --- 2. nothing in the chain will price a model it was not given ----------------------

#: Every entry point that turns tokens into rupees. Each must take `model` and none may
#: default it. Listed rather than discovered so that adding a fifth without a decision is
#: a visible edit here.
PRICING_ENTRY_POINTS = (
    llm_inr_per_ktok,
    llm_cost_inr_per_minute,
    reference_assist_cost_inr,
    assist_nominal_inr,
)


@pytest.mark.parametrize("fn", PRICING_ENTRY_POINTS, ids=lambda f: f.__name__)
def test_no_cost_function_defaults_to_a_model(fn: Any) -> None:
    """READ OFF THE SIGNATURE, because the default's absence IS the property.

    A test that merely called each function with each model would stay green the day
    somebody adds `model: str = AZURE_OPENAI_DEFAULT_MODEL` "for convenience" — and that
    edit is the whole defect: every existing caller keeps compiling, every existing test
    keeps passing, and the callers that should have been updated to pass the live model
    silently price the shipped default instead.
    """
    parameter = inspect.signature(fn).parameters.get("model")
    assert parameter is not None, f"{fn.__name__} does not take a model at all"
    assert parameter.default is inspect.Parameter.empty, (
        f"{fn.__name__} defaults its model to {parameter.default!r} — a caller's silence "
        "must never read as a claim about which model is deployed"
    )


def test_the_per_minute_curve_will_not_be_called_without_a_model() -> None:
    """`model` is KEYWORD-ONLY there as well as undefaulted: `llm_cost_inr_per_minute(10)`
    reads like a complete question and is not one, and a positional third argument at a
    call site would be a model that looks like a duration."""
    assert (
        inspect.signature(llm_cost_inr_per_minute).parameters["model"].kind
        is inspect.Parameter.KEYWORD_ONLY
    )
    with pytest.raises(TypeError):
        llm_cost_inr_per_minute(10)  # type: ignore[call-arg]


def test_an_unpriced_model_is_refused_rather_than_approximated() -> None:
    """Both fallbacks are worse than the error: the default's price under-bills the dearer
    model, and a zero makes a leg look free. The message names what IS priced, because the
    reader hitting this is looking at a model identifier read back off a historical ledger
    row and needs to know the set has moved."""
    for unpriced in ("gemini-2.5-flash", "gpt-4o", "", "GPT-4O-MINI"):
        with pytest.raises(ValueError, match="no published price"):
            llm_inr_per_ktok(unpriced)
        with pytest.raises(ValueError, match="no published price"):
            llm_cost_inr_per_minute(5, model=unpriced)


# --- 3. the published curve --------------------------------------------------------


@pytest.mark.parametrize("model", sorted(AZURE_OPENAI_MODELS))
def test_the_published_per_minute_curve_is_what_the_cost_model_computes(model: str) -> None:
    """The six figures TRD §10.1 quotes, pinned. `scripts/check_docs_drift.py` holds the
    DOC to the function; this holds the FUNCTION to the decision it was published under,
    so a change to the reference conversation or the rounding mode cannot move a number a
    founder has already reasoned from without somebody editing this block."""
    for minutes, expected in PUBLISHED_CURVE[model].items():
        assert llm_cost_inr_per_minute(minutes, model=model) == expected


@pytest.mark.parametrize("model", sorted(AZURE_OPENAI_MODELS))
def test_the_leg_costs_more_per_minute_on_a_longer_call(model: str) -> None:
    """TRD §6.1: the full conversation is resent every turn, so input tokens grow through
    the call and a single "₹x/min" is a blended average a long call skews above. The shape
    is the finding and it is a property of the workload, not of the price — so it holds on
    every model, and a model whose curve went flat would mean the reference conversation
    had lost its history term."""
    curve = [llm_cost_inr_per_minute(n, model=model) for n in (1, 5, 10)]
    assert curve[0] < curve[1] < curve[2], curve
    with pytest.raises(ValueError):
        llm_cost_inr_per_minute(0, model=model)


def test_the_decision_bought_a_cheaper_leg_than_the_one_it_replaced() -> None:
    """D-410's own claim, checked rather than repeated: `gpt-4o-mini` is cheaper than the
    retired `gemini-2.5-flash` at every published point. It is also the guard that would
    notice the old prices returning under a new identifier — the failure that would make
    every margin figure in TRD §10 wrong while every test about derivations passed."""
    for minutes, retired in RETIRED_GEMINI_CURVE.items():
        assert llm_cost_inr_per_minute(minutes, model=AZURE_OPENAI_DEFAULT_MODEL) < retired
    # And no shipped model reproduces the retired curve, which is what "the Gemini-era
    # numbers are gone" means as an assertion rather than as a claim in a commit message.
    for model in AZURE_OPENAI_MODELS:
        assert PUBLISHED_CURVE[model] != RETIRED_GEMINI_CURVE


# --- 4. the assist chain carries the model with the money -----------------------------


def test_an_assist_cannot_be_metered_at_a_price_that_disagrees_with_its_model() -> None:
    """THE STRUCTURAL FIX, asserted structurally.

    `record_ai_assist_usage` used to take the two per-ktok prices AND the model as three
    independent arguments — three values a caller kept in step by hand. Any caller that
    reached for the default's price while naming the configured model would write
    `unit_cost_paid` disagreeing with its own `meta.model`, on an append-only table, for
    every assist. The price is now derived from the model inside the writer, so that row
    is unrepresentable; this test is what stops a "convenience" override putting the hole
    back.
    """
    parameters = inspect.signature(record_ai_assist_usage).parameters
    assert "model" in parameters
    assert parameters["model"].default is inspect.Parameter.empty
    priced = [name for name in parameters if "price" in name or "cost" in name]
    assert not priced, (
        f"{priced} lets a caller state a price beside a model; the two can then disagree "
        "on a ledger row nobody can UPDATE"
    )


def test_the_assist_estimate_names_the_model_it_was_priced_for() -> None:
    """`AiQuota` carries the model, required, so no quota can publish an "about N assists"
    count without saying which model that count is for.

    The count genuinely moves with it — asserted on ONE allowance so the difference can
    only come from the model — which is what makes the required field worth having rather
    than decorative.
    """
    assert AiQuota.__dataclass_fields__["assist_model"].default is dataclasses.MISSING, (
        "a quota that can be built without a model can publish an estimate 2.6x too "
        "generous and look right"
    )

    def quota(model: str) -> AiQuota:
        return AiQuota(
            month="2026-08",
            plan_tier="self_serve",
            included_inr=Decimal("100.00"),
            used_inr=Decimal("0"),
            requests_used=0,
            extra_purchased_inr=Decimal("0"),
            platform_paused=False,
            assist_model=model,
        )

    cheap = quota(AZURE_OPENAI_DEFAULT_MODEL)
    dear = quota(next(iter(AZURE_OPENAI_MODELS - {AZURE_OPENAI_DEFAULT_MODEL})))
    assert cheap.requests_included > dear.requests_included
    assert cheap.requests_included == int(cheap.allowance_inr // cheap.nominal_assist_inr)
    assert dear.requests_included == int(dear.allowance_inr // dear.nominal_assist_inr)


def test_the_reference_assist_and_its_nominal_move_with_the_model() -> None:
    """The other half of the same chain: what one assist COSTS and what the screen PRICES
    it at, both per model, both derived. The margin is over-statement in the same
    direction on both models — an estimate is allowed to be pleasantly wrong and is never
    allowed to over-promise."""
    for model in AZURE_OPENAI_MODELS:
        cost = reference_assist_cost_inr(model)
        nominal = assist_nominal_inr(model)
        assert isinstance(cost, Decimal) and isinstance(nominal, Decimal)
        assert nominal > cost, f"{model}: the published estimate does not under-promise"
    default = AZURE_OPENAI_DEFAULT_MODEL
    other = next(iter(AZURE_OPENAI_MODELS - {default}))
    assert reference_assist_cost_inr(default) < reference_assist_cost_inr(other)


def test_no_figure_in_the_chain_is_ever_a_float() -> None:
    """Hard rule 7, scanned across the whole chain rather than trusted per function. A
    float here would not be visible in any other assertion in this file — `Decimal` and
    `float` compare equal often enough to pass everything above."""
    values: list[object] = []
    for model in AZURE_OPENAI_MODELS:
        values.extend(AZURE_LIST_PRICE_USD_PER_MTOK[model].values())
        values.extend(llm_inr_per_ktok(model).values())
        values.extend(llm_cost_inr_per_minute(n, model=model) for n in (1, 5, 10))
        values.append(reference_assist_cost_inr(model))
        values.append(assist_nominal_inr(model))
    values.append(LIST_PRICE_USD_INR)
    assert all(isinstance(value, Decimal) for value in values)
    assert not any(isinstance(value, float) for value in values)


# --- our cost is not the client's price, and the two must never be reconciled ---------


def test_no_client_billing_function_takes_a_model() -> None:
    """**A MODEL IDENTIFIER CANNOT REACH A CLIENT'S BILL — ONLY A RATE THE PLAN QUOTES.**

    D-454 gave clients a model picker whose rows carry `llm_cost_inr_per_minute`. That
    figure is what the language leg costs US at list price (`billing/rates.py` says so at
    the function), and it is still not a client price.

    **WHAT D-455 CHANGED, AND WHAT IT DELIBERATELY DID NOT.** This test used to be titled
    "a client's bill does not move when they change model", and it named the condition on
    which that would stop being true: a repricing needs "the plan row, the invoice line
    and the client's consent that a signature change does not come with". All three now
    exist — `plans.llm_model_surcharge`, the `AI model upgrade` line in `build_invoice`,
    and the corrected copy on both pickers — so a client's bill DOES move, and that
    sentence is retired rather than quietly kept.

    The INVARIANT survives it intact and is what this test still holds: none of these
    functions can be told which model ran. They take MINUTES and a RATE, and the rate is a
    term of the plan; the mapping from a model identifier to "does this minute carry the
    surcharge" happens once, in `rates.llm_surcharge_applies`, off the LEDGER's stamp.
    That is what stops the two ways of pricing a month that `priced_overage` was written
    to end from reappearing on a new axis — and what stops `agents.llm_model`, a column
    two screens can edit at any moment, from re-pricing a closed month.

    Asserted from the SIGNATURES rather than from a worked example, for the reason the
    rest of this file asserts signatures: the property is "the model cannot reach the
    client's bill", and an example only shows that it did not on one input.
    """
    from apps.api.billing.rates import llm_surcharge_billed_inr, prepaid_billed_inr
    from apps.api.billing.service import charge_for_call, priced_llm_surcharge, priced_overage

    for function in (
        prepaid_billed_inr,
        priced_overage,
        charge_for_call,
        # D-455's two, held to the same rule: one takes a rate and minutes, the other a
        # rate and a map the LEDGER bucketed. Neither is handed a model to decide with.
        llm_surcharge_billed_inr,
        priced_llm_surcharge,
    ):
        parameters = set(inspect.signature(function).parameters)
        assert not parameters & {"model", "llm_model", "assist_model"}, (
            f"{function.__name__} can now see which language model ran; a client's minute "
            "is billed at their plan's rate and must not vary with a model choice"
        )


def test_our_language_cost_is_nowhere_near_a_clients_per_minute_price() -> None:
    """The two numbers are different KINDS, and a screen that prints one as the other is
    out by more than an order of magnitude.

    `self_serve_inr_per_min` is what a prepaid client is charged for a minute of calling.
    `llm_cost_inr_per_minute` is what one of the several legs inside that minute costs us.
    Even the DEARER model's language leg is a small fraction of the client's rate — so if
    this assertion ever fails, either a vendor price moved by more than an order of
    magnitude or somebody has reconciled the supplier figure with the retail one, and both
    of those need a person rather than a passing test.
    """
    client_rate = get_settings().self_serve_inr_per_min
    for model in AZURE_OPENAI_MODELS:
        ours = llm_cost_inr_per_minute(5, model=model)
        assert isinstance(ours, Decimal) and isinstance(client_rate, Decimal)
        assert ours * 10 < client_rate, (
            f"{model}: our language leg ({ours}/min) is now within an order of magnitude "
            f"of what a client pays for a whole minute ({client_rate}/min) — these are "
            "different numbers and neither is a substitute for the other"
        )
