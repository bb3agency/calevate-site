"""The number-provisioning provider set, observed through the one selector.

`campaigns/provisioning.py::KNOWN_PROVIDERS` is the set of carriers a CLIENT may hold
their own connection with, and a name outside it resolves to `provider_not_implemented` —
"we do not support that vendor at all". So the membership of that tuple is a behavioural
claim and not a note: naming a supported carrier must never produce that refusal, because
it sends an operator to change a setting that was right.

What refuses a supported carrier is the legal gate — no written VNO/reseller status is
recorded (D-537) — which is a different fact with a different fix, and asserting it here
is what stops the two being confused.
"""

from __future__ import annotations

import pytest
from apps.api.campaigns.provisioning import (
    KNOWN_PROVIDERS,
    NOT_AUTHORIZED_REASON,
    PROVIDER_NOT_IMPLEMENTED_REASON,
    number_provisioning_capability,
)
from apps.api.core.settings import get_settings


@pytest.mark.parametrize("carrier", KNOWN_PROVIDERS)
def test_a_known_carrier_refuses_on_the_legal_gate_and_not_as_an_unknown_vendor(
    monkeypatch: pytest.MonkeyPatch, carrier: str
) -> None:
    """Read through the ONE selector rather than asserted against the tuple: a tuple can
    contain a name and the selector still classify it wrongly."""
    monkeypatch.setattr(get_settings(), "number_provider", carrier)
    capability = number_provisioning_capability()

    assert capability.available is False, "no deployment has recorded a reseller authorisation"
    assert capability.reason == NOT_AUTHORIZED_REASON, (
        f"carrier {carrier!r} must refuse on the LEGAL gate — the thing that is actually "
        f"missing — got {capability.reason!r}"
    )
    assert not str(capability.reason).startswith(PROVIDER_NOT_IMPLEMENTED_REASON), (
        f"carrier {carrier!r} reported as an unsupported vendor"
    )


def test_an_unknown_carrier_is_reported_as_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-vacuity: without it the check above could pass on a selector that never refuses
    a vendor by name."""
    monkeypatch.setattr(get_settings(), "number_provider", "twilio")
    capability = number_provisioning_capability()
    assert capability.reason == f"{PROVIDER_NOT_IMPLEMENTED_REASON}:twilio"
