"""The overage rung token is spelled ONCE, and the month's pricing follows that spelling.

WHY THIS FILE EXISTS. `billing/service.BASE_OVERAGE_RUNG` carries the token the post-call
meter stamps on `usage_events.meta.tts_tier`, and its own comment states the rule it
exists for: "spelled once so the writer (`pipeline._meter`) and the reader
(`_ROW_TIER_SQL`) cannot drift apart". On 19 Sep 2026 a THIRD reader was found spelling it
itself — `billing/attribution._rung_rate` compared `tier == "premium"` as a bare literal —
so the month's per-rung revenue was priced from a copy of a token nothing guarantees.

The token is deliberately FROZEN (D-558): `usage_events` is append-only, so re-stamping it
would re-file every closed month into the unattributed bucket, which prices at the CHEAPER
rung. That freeze is what makes a duplicate spelling dangerous rather than untidy — the
day the constant is ever re-pointed (a two-step deprecation, hard rule 8), a literal left
behind goes on pricing a rung nothing stamps, on closed months, in rupees, with nothing
raising.

What is pinned here is therefore not "the answer for 'premium'" — that would pass against
the literal too — but that the function READS THE CONSTANT: re-point the constant and the
rung that used to be the base rung stops being priced as it.

Run: uv run pytest -q tests/billing_rung_spelling_test.py
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from apps.api.billing import attribution
from apps.api.billing.service import (
    BASE_OVERAGE_RUNG,
    OVERAGE_RUNGS,
    SECOND_OVERAGE_RUNG,
    UNATTRIBUTED_RUNG,
)

_RATE = Decimal("6.5000")
_RATE_VALUE = Decimal("4.0000")


def test_the_base_rung_takes_the_base_rate_and_the_other_two_take_the_value_rate() -> None:
    """The rule, over EVERY rung the module declares — no rung answered by omission."""
    priced = {
        rung: attribution._rung_rate(rung, rate=_RATE, rate_value=_RATE_VALUE, surcharge=None)
        for rung in OVERAGE_RUNGS
    }
    assert str(priced[BASE_OVERAGE_RUNG]) == "6.5000"
    # SURFACES §2b: a call we cannot PROVE got the dearer voice is never charged for it.
    assert str(priced[SECOND_OVERAGE_RUNG]) == "4.0000"
    assert str(priced[UNATTRIBUTED_RUNG]) == "4.0000"
    assert set(priced) == set(OVERAGE_RUNGS)


def test_a_plan_quoting_no_second_rate_bills_both_rungs_at_the_base_rate() -> None:
    """`NULL` on `plans.overage_rate_second` means "one rate", never "the value rung is
    free" — the arm that would otherwise have to invent a number."""
    for rung in OVERAGE_RUNGS:
        assert (
            str(attribution._rung_rate(rung, rate=_RATE, rate_value=None, surcharge=None))
            == "6.5000"
        )


def test_the_model_surcharge_is_added_to_whichever_rung_was_chosen() -> None:
    """D-455: the surcharge rides the rung's rate, it does not replace it."""
    surcharge = Decimal("1.2500")
    assert (
        str(
            attribution._rung_rate(
                BASE_OVERAGE_RUNG, rate=_RATE, rate_value=_RATE_VALUE, surcharge=surcharge
            )
        )
        == "7.7500"
    )
    assert (
        str(
            attribution._rung_rate(
                SECOND_OVERAGE_RUNG,
                rate=_RATE,
                rate_value=_RATE_VALUE,
                surcharge=surcharge,
            )
        )
        == "5.2500"
    )


def test_the_pricing_follows_the_constant_rather_than_a_copy_of_its_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE ASSERTION THIS FILE IS FOR, and the one a bare literal cannot pass.

    Re-point the token this module reads. The rung the ledger now calls the base rung must
    take the base rate, and the string that USED to be the base rung must fall to the value
    rate like any other unknown rung. With `tier == "premium"` written out here, the old
    string keeps the dearer rate and the new one never gets it — which is the two-step
    deprecation of a ledger token silently mispricing a closed month.
    """
    monkeypatch.setattr(attribution, "BASE_OVERAGE_RUNG", "studio_rung")
    assert (
        str(
            attribution._rung_rate(
                "studio_rung", rate=_RATE, rate_value=_RATE_VALUE, surcharge=None
            )
        )
        == "6.5000"
    )
    assert (
        str(attribution._rung_rate("premium", rate=_RATE, rate_value=_RATE_VALUE, surcharge=None))
        == "4.0000"
    )
