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
