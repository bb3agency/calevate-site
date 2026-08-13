"""The three things standing between this harness and a very bad afternoon.

This is the only script in the repo that dials a telephone on purpose. It runs on a
founder's laptop, against whatever `.env` happens to be loaded, at the end of a long
day. So the safety properties are not "validation" — they are the feature:

1. **DRY RUN IS THE DEFAULT.** Placing a call needs an explicit opt-in whose name reads
   wrong in a shell history: `--yes-place-real-calls-and-spend-money`. A flag called
   `--live` or `--real` is the kind of thing a tired person adds because the last
   command needed one.
2. **A HARD CAP, AND A COST PRINTED BEFORE THE MONEY MOVES.** `--max-calls` is
   mandatory alongside the opt-in and is enforced in `GateContext.spend_a_call`, at the
   one place a call can actually be placed, not by each gate remembering to count.
3. **IT REFUSES TO RUN AGAINST A PRODUCTION-SHAPED DEPLOYMENT.** Loudly, and with the
   variable to change.

WHAT COUNTS AS "PRODUCTION-SHAPED", AND WHY THESE THREE SIGNALS.
`APP_ENV=prod` is obvious. The other two are the ones that catch the realistic accident,
which is not "someone deliberately ran the pilot against prod" but "someone ran it in a
shell that still had the production `.env` sourced from an hour ago":

* `SELF_SERVE_SIGNUP_ENABLED` — R-11's kill switch is OPEN, so members of the public can
  sign up and dial through this deployment. Whatever else it is, it is serving real
  users.
* `PAYMENT_PROVIDER` — real money can move through this deployment.

Both produce false positives on a thoroughly-configured pilot box, and that is the
correct direction to be wrong in: the cost of a false positive is unsetting one variable
and re-running, and the cost of a false negative is our harness dialling a real client's
customer. Fail closed.

THE FOURTH DEFENCE ISN'T HERE, IT IS AN ABSENCE. `GateContext` holds no database session
and the pilot package imports nothing that could open one, so this harness cannot
enumerate contacts, read a `leads` row, or discover any number other than the single
`--to` the operator typed. `tests/pilot_safety_test.py` asserts that against the package
source, because an absence is exactly the kind of property that quietly stops being true.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from calevate_shared.config import Settings

#: The opt-in. Long, specific, and impossible to type by muscle memory.
LIVE_CALL_FLAG = "--yes-place-real-calls-and-spend-money"

#: Nobody's pilot needs more than this, and a runaway loop needs exactly one more than
#: whatever it was given. A ceiling on the ceiling.
ABSOLUTE_MAX_CALLS = 25

#: Money is Decimal, INR, never float (hard rule 7) — including an estimate, because an
#: estimate printed in the wrong currency is how a budget gets approved twice.
#:
#: LOW: TRD §10's all-in target for the shipped product, ₹3.00/min.
#: HIGH: what a pilot actually pays before any BYOK platform fee is negotiated —
#: Bolna's published bundled rate of 6.00¢/min (TRD §5 commercials) converted at the
#: configured `USD_INR_RATE`, plus the BYOK legs the bundled rate does not cover
#: (Saaras STT ₹0.50 + Bulbul v3 TTS up to ₹1.40 + Sarvam LLM ₹0.00 — TRD §10.1, D-36).
#: Deliberately pessimistic: an estimate that undershoots is worse than useless.
BUNDLED_USD_PER_MIN = Decimal("0.06")
BYOK_INR_PER_MIN = Decimal("1.90")
LOW_INR_PER_MIN = Decimal("3.00")

#: A pilot call is a scripted exchange, not a real consultation. Overridable, because
#: gate 3's ten-utterance Telugu script runs longer than gate 2's "say the nonce".
DEFAULT_MINUTES_PER_CALL = Decimal("3")

_PAISE = Decimal("0.01")


class PilotRefusedError(Exception):
    """Raised instead of running. Its message is what the operator sees, so it names the
    variable to change rather than the rule that was broken."""


@dataclass(frozen=True, slots=True)
class CostEstimate:
    calls: int
    minutes_per_call: Decimal
    low_inr: Decimal
    high_inr: Decimal

    def as_dict(self) -> dict[str, str | int]:
        return {
            "calls": self.calls,
            "minutes_per_call": str(self.minutes_per_call),
            "estimate_inr_low": str(self.low_inr),
            "estimate_inr_high": str(self.high_inr),
        }

    def render(self) -> str:
        return (
            f"COST ESTIMATE — up to {self.calls} call(s) x {self.minutes_per_call} min "
            f"= Rs {self.low_inr} to Rs {self.high_inr} "
            "(low: TRD §10 all-in target; high: Bolna's published bundled rate + BYOK legs)"
        )


def estimate_cost(*, calls: int, minutes_per_call: Decimal, usd_inr_rate: Decimal) -> CostEstimate:
    """What this run may spend, in INR, before it spends any of it."""
    minutes = Decimal(calls) * minutes_per_call
    high_per_min = BUNDLED_USD_PER_MIN * usd_inr_rate + BYOK_INR_PER_MIN
    return CostEstimate(
        calls=calls,
        minutes_per_call=minutes_per_call,
        low_inr=(minutes * LOW_INR_PER_MIN).quantize(_PAISE, rounding=ROUND_HALF_UP),
        high_inr=(minutes * high_per_min).quantize(_PAISE, rounding=ROUND_HALF_UP),
    )


def production_indicators(settings: Settings) -> list[str]:
    """Everything about this configuration that says "real deployment"."""
    signals: list[str] = []
    if settings.app_env == "prod":
        signals.append("APP_ENV=prod")
    if settings.self_serve_signup_enabled:
        signals.append("SELF_SERVE_SIGNUP_ENABLED is on (the public can sign up and dial here)")
    if settings.payment_provider is not None:
        signals.append(f"PAYMENT_PROVIDER={settings.payment_provider} (real money moves here)")
    return signals


def guard(settings: Settings, *, placing_calls: bool) -> None:
    """Refuse, or return. Raises `PilotRefusedError` with an actionable message.

    `APP_ENV=prod` refuses even in dry run. A dry run against prod does nothing harmful
    on its own, but the run that follows it is the one somebody adds a flag to, and a
    tool that has ever said "ok" against production config has taught its operator that
    it is safe there.
    """
    signals = production_indicators(settings)
    if settings.app_env == "prod":
        raise PilotRefusedError(
            "REFUSING TO RUN: APP_ENV=prod. The pilot harness dials real telephones and "
            "must never point at the deployment serving clients. Run it with the pilot "
            "environment loaded (APP_ENV=local or staging) and a pilot Bolna workspace."
        )
    if placing_calls and signals:
        raise PilotRefusedError(
            "REFUSING TO PLACE CALLS: this configuration looks like a live deployment — "
            + "; ".join(signals)
            + ". Unset those in the shell you run the pilot from, or re-run without "
            + LIVE_CALL_FLAG
            + " for a dry run."
        )


def call_budget(*, opted_in: bool, max_calls: int | None) -> int:
    """How many calls this run may place. Zero unless BOTH halves are present."""
    if not opted_in:
        return 0
    if max_calls is None:
        raise PilotRefusedError(
            f"{LIVE_CALL_FLAG} requires --max-calls <n>: an opt-in with no ceiling is not "
            "an opt-in, it is a blank cheque."
        )
    if max_calls < 1:
        raise PilotRefusedError("--max-calls must be at least 1.")
    if max_calls > ABSOLUTE_MAX_CALLS:
        raise PilotRefusedError(
            f"--max-calls {max_calls} exceeds the harness ceiling of {ABSOLUTE_MAX_CALLS}. "
            "OPERATIONS §2 budgets Rs 3-5k for the WHOLE pilot; if a gate genuinely needs "
            "more calls, run it twice and say so on the scorecard."
        )
    return max_calls


__all__ = [
    "ABSOLUTE_MAX_CALLS",
    "BUNDLED_USD_PER_MIN",
    "BYOK_INR_PER_MIN",
    "DEFAULT_MINUTES_PER_CALL",
    "LIVE_CALL_FLAG",
    "LOW_INR_PER_MIN",
    "CostEstimate",
    "PilotRefusedError",
    "call_budget",
    "estimate_cost",
    "guard",
    "production_indicators",
]
