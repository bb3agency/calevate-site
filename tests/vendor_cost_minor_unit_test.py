"""The vendor-cost minor-unit premise is stated TWICE, and nothing checked they agreed.

`engine/bolna.py::_ASSUMED_MINOR_UNITS_PER_MAJOR` is the divisor `_to_inr` applies to
every figure the engine reports, and `scripts/pilot/fidelity.py::
ASSUMED_MINOR_UNITS_PER_MAJOR` is the value pilot gate 7 SCORES that premise against.
The restatement is deliberate and correct — importing the adapter's constant into the
gate would make the check tautological, exactly as gate 1 argues about the egress IP —
but it is still one money fact living in two files with nothing holding them level.

**WHY THAT MATTERS MORE THAN a normal duplicated constant.** The gate's whole output is
a verdict on the adapter's premise: `fidelity.py` computes the ratio between the vendor's
figure and the invoice's and reports a `hundredfold` when it equals
`ASSUMED_MINOR_UNITS_PER_MAJOR`. If the adapter's divisor moved and the gate's did not,
gate 7 would go GREEN while scoring a premise the adapter no longer holds — a money
assumption marked "verified" against the wrong number. `_ASSUMED_MINOR_UNITS_PER_MAJOR`'s
own docstring puts the cost of being wrong at "every `usage_event` under-values the call
by 100x, so no spend cap ever arms and every margin panel reads near zero".

The same pairing exists for the CURRENCY (`_ASSUMED_CURRENCY` / `ASSUMED_SOURCE_CURRENCY`)
and is asserted here for the same reason.

**AND SINCE D-411 THE DIVISOR IS A TABLE, WHICH IS HOW THIS FILE ALMOST STOPPED BITING.**
The adapter's `_MINOR_UNITS_PER_MAJOR` is keyed by currency; the gate's restatement had to
become one too. The two scalars above still agree — USD's value never moved — so a test
that only compared them would have gone on passing while the gate lost the ability to say
anything about an INR-billed account, the case the whole change was made for. A pin that
survives the thing it was meant to catch is worse than no pin, because it is READ as
coverage. So the VOCABULARIES are pinned in both directions as well: a currency the
adapter learns and the gate does not is a gate scoring an account it cannot reason about,
and a currency the gate claims and the adapter refuses is a gate verifying a premise
nothing holds.

Run: uv run pytest -q tests/vendor_cost_minor_unit_test.py
"""

from __future__ import annotations

from apps.api.engine import bolna
from scripts.pilot import fidelity


def test_the_gate_and_the_adapter_assume_the_same_scale() -> None:
    """`scripts/pilot/fidelity.py` deliberately RESTATES the assumption rather than
    importing it, so the check is not tautological. That is right, and it is also two
    places one number lives — so the two must be equal or gate 7 is scoring a premise the
    adapter does not hold."""
    assert fidelity.ASSUMED_MINOR_UNITS_PER_MAJOR == bolna._ASSUMED_MINOR_UNITS_PER_MAJOR, (
        "the gate scores the adapter's divisor by restating it; a restatement that has "
        "drifted turns gate 7 into a verdict on a premise nothing holds"
    )


def test_the_gate_and_the_adapter_assume_the_same_currency() -> None:
    """The other half of the same pair, and the one that is worth 83x rather than 100x."""
    assert fidelity.ASSUMED_SOURCE_CURRENCY == bolna._ASSUMED_CURRENCY


def test_the_gate_and_the_adapter_know_the_same_currencies() -> None:
    """THE PIN THAT THE SCALAR PAIR ABOVE CANNOT PROVIDE (D-411).

    The divisor is per currency now. If the adapter gains an `INR: 1` entry the day gate 7
    reads an INR-billed execution, and this file is not updated in the same change, the
    gate goes on reporting `pass` for USD and treats every INR execution as an unpriced
    refusal it can say nothing about — green, and blind to the currency that motivated the
    fix. The reverse is the older defect: a currency the GATE thinks has a stated unit and
    the adapter refuses is gate 7 verifying a premise nothing holds.

    Key sets, not values: the divisor for a given currency is asserted one test up through
    the scalar pair, and restating every value here would make the restatement itself the
    thing that drifts.
    """
    assert set(fidelity.STATED_MINOR_UNITS_PER_MAJOR) == set(bolna._MINOR_UNITS_PER_MAJOR), (
        "the adapter and gate 7 disagree about which currencies have a defensible unit; "
        "whichever side is behind, the gate is scoring the wrong set of accounts"
    )


def test_the_divisor_for_every_shared_currency_agrees() -> None:
    """And the values, for the whole vocabulary rather than for USD alone — the scalar pin
    above covers `_ASSUMED_CURRENCY` and would not notice a second entry going wrong."""
    for currency, divisor in bolna._MINOR_UNITS_PER_MAJOR.items():
        assert fidelity.STATED_MINOR_UNITS_PER_MAJOR[currency] == divisor, (
            f"gate 7 scores {currency} at a divisor the adapter does not use"
        )
