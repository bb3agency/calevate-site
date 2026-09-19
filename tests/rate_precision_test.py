"""Every rate this repository STRIKES survives `usage_events.unit_cost_paid` intact.

THE QUESTION. `unit_cost_paid` is `NUMERIC(12,4)`, so ₹0.0001 per unit of `qty` is the
smallest non-zero figure the ledger holds and anything struck finer is rounded on the way
in. Three times this repository has met that and answered it the same way — scale the UNIT
until the rate fits, giving `ai_assist_ktok_*`, `tts_kchars` and `llm_ktok_*` — and each
time the arithmetic was done by hand, in a comment, at the moment the unit was invented.

Nothing re-did it when a RATE moved underneath a unit that already existed, and the path
for that is live rather than hypothetical: `platform_model_prices` and `platform_tts_prices`
store their figures at `NUMERIC(12,6)`, two decimal places finer than the ledger, so an
operator holding an invoice could enter a rate the column rounds away and never be told.
The next vendor, the next tier and the next promotional discount arrive through exactly
that door.

WHY THIS IS THE DELIVERABLE AND A WIDER COLUMN IS NOT. Every rate below clears the budget
by a wide margin today (worst: `gemini-2.5-flash-lite` input at +0.36%, and the whole TTS
card under 0.01%), so there is no leak to fix — the `k`-prefixed units already closed it.
What did not exist was anything that would NOTICE the next one. Widening `unit_cost_paid`
would be a migration against an append-only ledger's frozen history (hard rule 4) bought
to solve a problem the unit design already solves.

**DERIVED FROM THE REGISTRIES, NOT FROM A TYPED LIST** — `UNIT_TYPES`,
`SELECTABLE_LLM_MODELS`, `EMBEDDING_MODELS` and `TTS_PROVIDERS` — so a unit type, a model
or a voice provider added tomorrow is scored the day it lands. The unit table below is an
EQUALITY assertion against `UNIT_TYPES` for `money_rounding_mode_test`'s reason: an
allowlist lets the eleventh unit slip in unclassified, an equality makes it a red test.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from apps.api.billing.models import UNIT_TYPES
from apps.api.billing.rates import (
    LEDGER_RATE_ERROR_BUDGET,
    MONEY_Q,
    ROUNDING,
    assert_rate_is_meterable,
    ledger_rate_error,
    rate_is_meterable,
    usd_mtok_to_inr_ktok_exact,
)
from apps.api.core.errors import ProblemError
from apps.api.ops.model_pricing import (
    TTS_PROVIDERS,
    _refuse_unmeterable_rate,
    reference_tts_price,
)
from calevate_shared.engine import EMBEDDING_MODELS, LLM_MODELS, SELECTABLE_LLM_MODELS

#: HOW EACH METERED UNIT'S `unit_cost_paid` IS ARRIVED AT. Two shapes and no third:
#:
#: * ``"struck"`` — a RATE per unit of `qty`, from a card or an operator attestation, and
#:   therefore scorable here. This is the population this file exists for.
#: * ``"derived"`` — a vendor's LEG TOTAL divided by the quantity it covers
#:   (`apps/workers/pipeline.py::_unit_price`). There is no struck rate to check: the
#:   figure is whatever the engine charged over whatever duration it reported, so its
#:   precision is a property of one call and not of a card. That path has its own
#:   documented behaviour (half a quantum per unit of `qty`, `ROUND_HALF_UP`, pinned by
#:   `pipeline_partial_failure_test`) and is deliberately NOT re-litigated here.
#:
#: EQUALITY against `UNIT_TYPES`, asserted below. A new unit type has to be classified
#: before this suite is green, which is the whole point of deriving it.
UNIT_RATE_SHAPE: dict[str, str] = {
    # engine leg cost / billable seconds
    "telephony_s": "derived",
    # engine leg cost / minutes, OR the owned runtime's attested per-active-minute figure
    # (`voice_worker/meter.py::_runtime_row`), which is supplied by a human reading an
    # invoice and is not a card this process can enumerate.
    "platform_min": "derived",
    "stt_s": "derived",
    # qty = 1, priced at the whole leg the engine reported.
    "tts_chars": "derived",
    "llm_tok_in": "derived",
    "llm_tok_out": "derived",
    # a compensating entry carries a computed delta, not a rate (billing/cost_unit.py).
    "other": "derived",
    # one month's rental converted at the fx rate of the day (billing/number_rental.py).
    "number_rental": "derived",
    # THE STRUCK ONES — all four are `k`-prefixed, which is not a coincidence but the
    # answer this repository already gave to this file's question.
    "tts_kchars": "struck",
    "llm_ktok_in": "struck",
    "llm_ktok_out": "struck",
    "ai_assist_ktok_in": "struck",
    "ai_assist_ktok_out": "struck",
}


def test_every_metered_unit_is_classified() -> None:
    """An eleventh unit type cannot arrive without saying how its rate is struck."""
    assert set(UNIT_RATE_SHAPE) == set(UNIT_TYPES), (
        "UNIT_RATE_SHAPE and billing/models.UNIT_TYPES disagree about which units exist"
    )
    assert set(UNIT_RATE_SHAPE.values()) == {"struck", "derived"}


@pytest.mark.parametrize("model", sorted(SELECTABLE_LLM_MODELS))
def test_selectable_model_rates_survive_the_ledger(model: str) -> None:
    """`llm_ktok_*` and `ai_assist_ktok_*` are priced from this card, per THOUSAND tokens.

    Both legs, because they are struck decades apart in magnitude: `gpt-4o-mini` output is
    forty times its input, so a budget met on one says nothing about the other.
    """
    price = LLM_MODELS[model].price
    for leg, usd in (("in", price.input_usd_per_mtok), ("out", price.output_usd_per_mtok)):
        if usd is None:
            continue
        rate = usd_mtok_to_inr_ktok_exact(usd)
        error = ledger_rate_error(rate)
        assert error <= LEDGER_RATE_ERROR_BUDGET, (
            f"{model} {leg} leg is struck at Rs {rate}/1k tokens, which the ledger stores "
            f"as {rate.quantize(MONEY_Q, rounding=ROUNDING)} — {error * 100:.2f}% away. "
            "Quote it in a larger unit; do not widen unit_cost_paid."
        )


@pytest.mark.parametrize("model", sorted(EMBEDDING_MODELS))
def test_embedding_rates_survive_the_ledger(model: str) -> None:
    """The encoder catalogue meters on `ai_assist_ktok_in` and is the same question.

    Only the input leg: an embedding model has no output price (migration a3f70c19d84b),
    and the `ai_assist_ktok_out` row it writes carries `qty = 0` at an exact Rs 0.0000.
    """
    rate = usd_mtok_to_inr_ktok_exact(EMBEDDING_MODELS[model].price.input_usd_per_mtok)
    assert rate_is_meterable(rate), f"{model} is struck at Rs {rate}/1k tokens"


@pytest.mark.parametrize("provider", TTS_PROVIDERS)
def test_tts_reference_rates_survive_the_ledger(provider: str) -> None:
    """`tts_kchars` is priced per THOUSAND characters, attested or pre-filled.

    An attested figure cannot be reached from here (it is a database row), so what is
    scored is the console's PRE-FILL — the number an operator is most likely to accept —
    and `_refuse_unmeterable_rate` guards the typed one at the attestation seam. A provider
    with no pre-fill (`None`) is not a gap: it is a vendor whose rate nobody has read, which
    `agents/voice_offer` already refuses to sell a minute on.
    """
    prefill = reference_tts_price(provider)
    if prefill is None:
        return
    assert rate_is_meterable(prefill), (
        f"the {provider} pre-fill is Rs {prefill}/1k characters, which the ledger cannot "
        "hold at that size"
    )


def test_a_rate_quoted_per_character_is_refused() -> None:
    """THE CASE THE `k`-PREFIX EXISTS FOR, stated as an executable fact.

    Gnani publish Rs 27.00 per 10,000 characters, i.e. Rs 0.0027 a character. Per CHARACTER
    the ledger stores Rs 0.0027 — a 0.0% error, which is exactly why this leak is invisible
    until a cheaper vendor arrives; the figure that bites is Cartesia's attested
    Rs 0.0034496 a character, stored as Rs 0.0034, metering our own cost 1.4% light. Per
    THOUSAND both are exact. That difference is the whole of D-547's unit decision.
    """
    per_char = Decimal("0.0034496")
    assert not rate_is_meterable(per_char)
    with pytest.raises(ValueError, match="per thousand"):
        assert_rate_is_meterable(per_char, subject="a Cartesia rate", unit="character")
    assert rate_is_meterable(per_char * 1000)


def test_a_rate_the_ledger_rounds_to_zero_scores_total_loss() -> None:
    """Not an `InvalidOperation` on a division by the stored zero — the worst possible score.

    `gpt-4o-mini` input is about Rs 0.0000143 a token: per TOKEN the whole leg meters free,
    which is the arithmetic `billing/models.py` writes out for `ai_assist_ktok_*`.
    """
    per_token = Decimal("0.0000143")
    assert ledger_rate_error(per_token) == Decimal(1)
    assert not rate_is_meterable(per_token)


def test_a_non_positive_rate_is_refused_rather_than_scored() -> None:
    """Zero and negative are each seam's own refusal, with its own operator-facing message.

    Scoring one here would return a number for an input every caller has already rejected,
    which hides a caller that skipped its own validation.
    """
    for bad in (Decimal(0), Decimal("-1")):
        with pytest.raises(ValueError, match="strictly positive"):
            ledger_rate_error(bad)


def test_the_guard_returns_the_rate_and_does_not_quantize_it() -> None:
    """The quantization belongs to the ledger's INSERT and happens once, at the column.

    A guard that handed back a rounded figure would be a second rounding site and would give
    two callers two spellings of one number.
    """
    rate = Decimal("3.4496")
    assert assert_rate_is_meterable(rate, subject="x", unit="1,000 characters") is rate


def test_the_attestation_seam_refuses_an_unmeterable_rate_in_operator_language() -> None:
    """`ops/model_pricing._refuse_unmeterable_rate` is the same arithmetic, spoken to a human.

    The console is where somebody is holding an invoice, so the refusal has to be a
    `ProblemError` they can act on rather than a 500 on a money form. Exercised directly
    rather than through `attest_price`: the translation is the part with two arms, and the
    three call sites are already walked by the attestation suites with valid figures.
    """
    _refuse_unmeterable_rate(Decimal("3.4496"), subject="a good rate", unit="1,000 characters")
    with pytest.raises(ProblemError) as refused:
        _refuse_unmeterable_rate(
            Decimal("0.0034496"), subject="a per-character rate", unit="character"
        )
    assert refused.value.code == "attested_price_not_meterable"
    assert "unit_cost_paid" in refused.value.detail
