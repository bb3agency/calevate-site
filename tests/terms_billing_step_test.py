"""The Terms state the billing step as a figure, which is a promise clients accept; it must
be the step we actually bill, so changing `CLIENT_PULSE_SECONDS` forces a Terms revision."""

from __future__ import annotations

from pathlib import Path

from apps.api.billing.rates import CLIENT_PULSE_SECONDS

TERMS = Path(__file__).resolve().parents[1] / "apps" / "web" / "src" / "lib" / "legal" / "terms.ts"


def test_the_terms_state_the_billing_step_we_bill() -> None:
    assert f"billed in {int(CLIENT_PULSE_SECONDS)}-second steps" in TERMS.read_text(
        encoding="utf-8"
    )
