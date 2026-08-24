"""No API surface publishes a rupee AMOUNT at its storage precision (D-375, D-376).

THE DEFECT, TWICE. `billing.service.to_paise` documents itself as "the ONE place a rupee
amount is rounded ... so no two surfaces can round the same number differently", and two
response routes stringified a money `Decimal` straight out of the database instead:

* `crm/routes.py` published `credit_ledger.balance_after` as `credit_balance_inr` (D-375);
* `admin/health_routes.py` published `spend_state.billed_inr` as `spend_used_inr` (D-376).

Both columns are `MONEY` — NUMERIC(12,4) — and four decimals is what they ORDINARILY
hold: a prepaid call is debited `rates.prepaid_billed_inr`, quantized at `MONEY_Q`, so
any `self_serve_inr_per_min` that is not a divisor of 60 produces one on the first call
(95 seconds at ₹6.50/min is ₹10.2917).

**WHY THAT IS A DISAGREEMENT AND NOT A FORMATTING PREFERENCE.** The two ends round in
OPPOSITE directions. `to_paise` is ROUND_HALF_UP — `billing.rates.ROUNDING`, the repo's
one mode, chosen because it is what an Indian tax invoice is checked against — while
`apps/web`'s `formatINR` TRUNCATES the fraction to two digits, deliberately, because it
formats digits without ever parsing them (hard rule 7's frontend shadow: `Number("10159.00")`
is how ₹10,159.00 becomes ₹10,158.999999999998 on a screen a client checks against their
own books). So a balance of ₹489.7050 read ₹489.71 wherever `to_paise` ran and ₹489.70
wherever it did not — one row, one instant, two screens, and the low one was whichever
screen had skipped the function.

WHY A SCAN AND NOT TWO PINS
----------------------------
The same argument `money_rounding_mode_test` makes, and this file is its sibling. D-375
fixed one surface; the sweep that found it did not ask which OTHER surface had the same
shape, and D-376 was found by accident one screen over. A pin on the two lines that were
wrong is satisfied by the commit that fixed them and silent on the third. So the subject
is the decidable property — **does a route module stringify a money-named attribute
without routing it through the one rounding function** — scanned over every route module,
with what may legitimately stay unquantized recorded as an EQUALITY assertion rather than
an allowlist.

WHAT IS DELIBERATELY NOT AN OFFENCE
------------------------------------
* **A RATE is not a rupee amount.** `overage_rate` is NUMERIC(12,4) and a plan may quote
  ₹7.1250/min; quantizing it to paise for display while billing the unrounded rate makes
  the invoice line fail the only arithmetic a client ever does on it (`qty x unit =
  amount`). `rate_to_display` is that path and it is not this one — the scan keys on the
  attribute NAME, and rate fields are named as rates.
* **An AUDIT summary records what happened, not what was shown.** `payments.py` and
  `credit_routes.py` write `balance_after_inr` into an `audit_log` row at full precision
  on purpose: an audit trail that stored a display rounding would be a record of the
  screen rather than of the ledger. Those two are the recorded exceptions below.

Run: uv run pytest -q tests/money_wire_quantization_test.py
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Where a response shape is built. Route modules only: a service may hand back an exact
#: `Decimal` (and should — `_spend_used` and `get_balance` do), because the quantization
#: belongs at the WIRE and not in the arithmetic that feeds it. Quantizing earlier is how
#: a figure gets rounded twice, which is the defect `money_walk_test` exists for.
ROUTE_GLOBS: tuple[str, ...] = (
    "apps/api/**/routes.py",
    "apps/api/**/*_routes.py",
)

#: Attribute names that hold a rupee AMOUNT, as opposed to a rate or a count. Matched on
#: the attribute being stringified, which is the thing whose precision reaches the wire.
_AMOUNT_ATTRS: frozenset[str] = frozenset(
    {"amount_inr", "balance_after", "billed_inr", "spend_used_inr", "spend_cap_inr"}
)

#: `str(<expr>.<amount attr>)` sites that legitimately publish full precision, with the
#: reason. Keyed by file and by the source of the call, never by line number, so an
#: unrelated edit above does not turn this into a maintenance tax.
#:
#: An EQUALITY assertion, not an exemption list: adding a site fails, and REMOVING one of
#: these fails too, so an entry cannot outlive the reason it describes.
UNQUANTIZED_ON_PURPOSE: dict[str, set[str]] = {
    "apps/api/billing/credit_routes.py": {
        # Written into an `audit_log` summary, not into a response model. An audit row
        # records the LEDGER's own figure; storing a display rounding there would make
        # the trail a record of the screen instead of of the money.
        "str(balance.amount_inr)",
    },
    "apps/api/billing/ai_quota_routes.py": {
        # The same reason: an `audit_log` summary of what the person accepted. It is the
        # record of a decision, not a figure any screen renders.
        "str(result.amount_inr)",
    },
    "apps/api/billing/payment_routes.py": {
        # NOT a display at all — this is the `payload_hash` that fingerprints a Razorpay
        # redelivery for `claim_inbox_event`, and quantizing it would be actively wrong.
        # The hash's whole job is that "a different amount under the same payment id is
        # not the same payment"; rounding two distinct amounts to one paisa figure would
        # let a corrected webhook be swallowed as a replay of the original. Precision
        # here is an idempotency property, not a presentation one.
        "str(payment.amount_inr)",
        # The refund webhook branch (D-468) fingerprints its redelivery the same way and
        # for the same reason: a `refund.processed` replay must dedupe, but a corrected
        # refund amount under the same refund id must NOT be swallowed as one. Same
        # idempotency property, same `payload_hash`, so the raw amount is deliberate here
        # too. (The response body one line down quantizes with `to_paise` — this is only
        # the hash.)
        "str(refund.amount_inr)",
    },
}


def _route_modules() -> list[Path]:
    seen: dict[Path, None] = {}
    for pattern in ROUTE_GLOBS:
        for path in sorted(REPO_ROOT.glob(pattern)):
            if "__pycache__" not in path.parts:
                seen.setdefault(path, None)
    return list(seen)


def _unquantized_amount_sites() -> dict[str, set[str]]:
    """Every `str(x.<amount attr>)` in a route module that is not wrapped in `to_paise`.

    Read from the AST, never from source text: a docstring or a comment explaining WHY a
    figure must be quantized — this repo has several, and the two fixed routes now carry
    long ones — must not register as an offence.
    """
    found: dict[str, set[str]] = {}
    for path in _route_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "str"
                and len(node.args) == 1
            ):
                continue
            inner = node.args[0]
            # `str(to_paise(...))` and `str(billing.to_paise(...))` are the fixed shape.
            if isinstance(inner, ast.Call):
                callee = inner.func
                name = (
                    callee.attr
                    if isinstance(callee, ast.Attribute)
                    else callee.id
                    if isinstance(callee, ast.Name)
                    else ""
                )
                if name == "to_paise":
                    continue
            if not (isinstance(inner, ast.Attribute) and inner.attr in _AMOUNT_ATTRS):
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            found.setdefault(rel, set()).add(ast.unparse(node))
    return found


def test_the_route_modules_that_skip_to_paise_are_exactly_the_recorded_ones() -> None:
    """D-375 and D-376, generalised so a third surface cannot appear silently.

    Equality rather than a subset: a NEW route stringifying a rupee amount raw fails
    here, and so does an entry that has quietly been fixed — an exemption that outlives
    its reason is a standing permission waiting to be inherited (the argument
    `response_shape_test._UNMODELLED_SUCCESS` makes about stale registry rows).
    """
    assert _unquantized_amount_sites() == UNQUANTIZED_ON_PURPOSE, (
        "a route is publishing a rupee AMOUNT at its NUMERIC(12,4) storage precision. "
        "`apps/web`'s formatINR truncates where `to_paise` rounds half-up, so this is a "
        "screen that will disagree with every other screen showing the same row by a "
        "paisa (D-375, D-376). Wrap it in `to_paise`, or record it here with the reason "
        "it must keep full precision."
    )


def test_the_scan_actually_reaches_the_two_routes_that_were_wrong() -> None:
    """The guard's own coverage, asserted rather than assumed.

    A scan whose glob has drifted off the modules it is meant to police passes silently
    and forever — which is exactly the failure mode of the assertion it replaces. So:
    the two files D-375 and D-376 fixed must be IN the scanned set, and the set must be
    substantial rather than accidentally empty.
    """
    scanned = {path.relative_to(REPO_ROOT).as_posix() for path in _route_modules()}
    assert "apps/api/crm/routes.py" in scanned, "D-375's route is not being scanned"
    assert "apps/api/admin/health_routes.py" in scanned, "D-376's route is not being scanned"
    assert len(scanned) >= 15, f"only {len(scanned)} route modules found — the glob is broken"
