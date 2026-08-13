"""The harness spends real money and dials real telephones. These are its brakes.

Every test here corresponds to an accident that is entirely plausible on a founder's
laptop at the end of a long day: the production `.env` still sourced in the shell, a
`--max-calls` forgotten, a loop that keeps dialling.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from calevate_shared.config import Settings
from scripts.pilot import safety
from scripts.pilot.gates_api import GateContext


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "app_env": "local",
        "database_url": "postgresql+psycopg://u:p@localhost:5432/x",
        "redis_url": "redis://localhost:6379/0",
        "object_store_endpoint": "http://localhost:9000",
        "object_store_bucket": "calevate",
        "engine": "bolna",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


# --- dry run is the default ---------------------------------------------------


def test_no_calls_without_the_opt_in() -> None:
    assert safety.call_budget(opted_in=False, max_calls=10) == 0


def test_the_opt_in_flag_reads_wrong_by_design() -> None:
    """Named, not spelled out in prose, so renaming it to something forgettable breaks
    a test rather than quietly making an accident easier."""
    assert safety.LIVE_CALL_FLAG == "--yes-place-real-calls-and-spend-money"


def test_opt_in_without_a_ceiling_is_refused() -> None:
    with pytest.raises(safety.PilotRefusedError, match="blank cheque"):
        safety.call_budget(opted_in=True, max_calls=None)


def test_the_ceiling_has_a_ceiling() -> None:
    with pytest.raises(safety.PilotRefusedError, match="ceiling"):
        safety.call_budget(opted_in=True, max_calls=safety.ABSOLUTE_MAX_CALLS + 1)
    assert safety.call_budget(opted_in=True, max_calls=2) == 2


def test_the_cap_is_enforced_where_the_call_is_placed() -> None:
    """Not by each gate remembering to count — a budget checked by whoever remembers to
    check it is not a budget."""
    ctx = GateContext(engine=None, settings=_settings(), calls_remaining=2)  # type: ignore[arg-type]
    assert ctx.spend_a_call() is True
    assert ctx.spend_a_call() is True
    assert ctx.spend_a_call() is False
    assert ctx.calls_remaining == 0


# --- production refusal --------------------------------------------------------


def test_prod_is_refused_even_in_dry_run() -> None:
    with pytest.raises(safety.PilotRefusedError, match="APP_ENV=prod"):
        safety.guard(_settings(app_env="prod"), placing_calls=False)


def test_open_self_serve_signup_blocks_calls() -> None:
    live = _settings(self_serve_signup_enabled=True)
    with pytest.raises(safety.PilotRefusedError, match="sign up and dial"):
        safety.guard(live, placing_calls=True)
    # ...and does NOT block a dry run: the point is to stop the dialling, not to stop
    # an operator learning what is missing.
    safety.guard(live, placing_calls=False)


def test_a_configured_payment_provider_blocks_calls() -> None:
    with pytest.raises(safety.PilotRefusedError, match="real money"):
        safety.guard(_settings(payment_provider="razorpay"), placing_calls=True)


def test_a_pilot_shaped_environment_is_allowed_to_dial() -> None:
    safety.guard(_settings(app_env="staging"), placing_calls=True)
    assert safety.production_indicators(_settings()) == []


# --- the cost estimate ---------------------------------------------------------


def test_the_estimate_is_decimal_inr_and_bounds_the_run() -> None:
    estimate = safety.estimate_cost(
        calls=4, minutes_per_call=Decimal("3"), usd_inr_rate=Decimal("88.00")
    )
    assert isinstance(estimate.low_inr, Decimal)
    # 12 minutes at the TRD §10 all-in target.
    assert estimate.low_inr == Decimal("36.00")
    # 12 minutes at 6.00c/min x 88 + Rs 1.90 BYOK = Rs 7.18/min.
    assert estimate.high_inr == Decimal("86.16")
    assert estimate.high_inr > estimate.low_inr
    # Money serializes as a STRING: an estimate that round-trips through a JSON float
    # has already been rounded by someone who was not asked (hard rule 7).
    assert estimate.as_dict()["estimate_inr_low"] == "36.00"


def test_a_dry_run_estimates_nothing_because_it_spends_nothing() -> None:
    estimate = safety.estimate_cost(
        calls=0, minutes_per_call=Decimal("3"), usd_inr_rate=Decimal("88.00")
    )
    assert estimate.high_inr == Decimal("0.00")


# --- the fourth defence, which is an absence ----------------------------------

_PILOT_PACKAGE = Path(__file__).resolve().parent.parent / "scripts" / "pilot"

#: Anything that could hand the harness a number it was not given on the command line.
#: The point is not import hygiene, it is that this process must be structurally unable
#: to discover a real client's contact.
_FORBIDDEN_IMPORTS = (
    "apps.api.db",
    "apps.api.crm",
    "apps.api.campaigns",
    "apps.api.tenancy",
    "sqlalchemy",
)


def test_the_harness_cannot_reach_a_database_or_a_contact_list() -> None:
    """The worst outcome available to this harness must be dialling the ONE number the
    operator typed. It gets that property by having no way to look up any other."""
    offenders: list[str] = []
    for path in sorted(_PILOT_PACKAGE.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for line in source.splitlines():
            stripped = line.strip()
            if not (stripped.startswith("import ") or stripped.startswith("from ")):
                continue
            for banned in _FORBIDDEN_IMPORTS:
                if banned in stripped:
                    offenders.append(f"{path.name}: {stripped}")
    assert offenders == [], (
        "the pilot harness must not be able to enumerate contacts: " + "; ".join(offenders)
    )
