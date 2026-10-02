"""The carrier shapes every deployable shares (D-662): names, URL paths, the outbound call
claim and the sealed transfer token."""

from __future__ import annotations

import time

import pytest
from apps.api.core import carrier_token
from calevate_shared.carrier import (
    CARRIERS,
    DEFAULT_CARRIER,
    VOBIZ_CALLBACK_IPS,
    WIRE_FAMILY,
    answer_path,
    events_path,
    is_carrier,
    transfer_path,
)
from calevate_shared.config import Settings
from calevate_shared.worker_api import (
    call_claim_mac,
    caller_claim_mac,
    verify_call_claim,
)

REF = "pipecat:0190a0b0-0000-7000-8000-000000000001:0190a0b0-0000-7000-8000-000000000002"
KEY = b"k" * 32
SECRET = "s" * 40


def test_the_switch_defaults_to_vobiz_and_names_both_carriers() -> None:
    assert DEFAULT_CARRIER == "vobiz"
    assert set(CARRIERS) == {"vobiz", "plivo"}
    assert Settings.model_fields["carrier"].default == "vobiz"
    assert set(WIRE_FAMILY) == set(CARRIERS)
    assert is_carrier("vobiz") and not is_carrier("exotel")


def test_paths_keep_the_ref_one_segment_and_put_the_call_id_in_the_path() -> None:
    assert answer_path("vobiz", REF) == f"/carrier/v1/vobiz/answer/{REF.replace(':', '%3A')}"
    outbound = answer_path("vobiz", REF, call_id="c-1")
    assert outbound.endswith("/outbound/c-1") and "?" not in outbound
    assert events_path("plivo", REF).startswith("/carrier/v1/plivo/events/")
    assert transfer_path("vobiz", "a/b") == "/carrier/v1/vobiz/transfer/a%2Fb"


def test_published_callback_addresses_are_the_three_documented() -> None:
    assert VOBIZ_CALLBACK_IPS == ("15.206.6.156", "35.154.59.246", "15.207.8.226")


def _claim(now: float, **overrides: object) -> dict[str, object]:
    expires = int(now) + 60
    values: dict[str, object] = {
        "ref": REF,
        "call_id": "call-1",
        "direction": "outbound",
        "expires_at": str(expires),
        "mac": call_claim_mac(
            KEY, ref=REF, call_id="call-1", direction="outbound", expires_at=expires
        ),
        "now": now,
    }
    values.update(overrides)
    return values


def test_a_minted_call_claim_verifies() -> None:
    now = time.time()
    assert verify_call_claim(KEY, **_claim(now))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "override",
    [
        {"call_id": "call-2"},
        {"direction": "inbound"},
        {"direction": "sideways"},
        {"ref": REF + "x"},
        {"mac": None},
        {"expires_at": "soon"},
    ],
)
def test_a_changed_or_malformed_call_claim_is_refused(override: dict[str, object]) -> None:
    now = time.time()
    assert not verify_call_claim(KEY, **_claim(now, **override))  # type: ignore[arg-type]


def test_an_expired_call_claim_and_a_missing_key_are_refused() -> None:
    now = time.time()
    stale = {**_claim(now), "now": now + 3600}
    assert not verify_call_claim(KEY, **stale)  # type: ignore[arg-type]
    assert not verify_call_claim(None, **_claim(now))  # type: ignore[arg-type]


def test_a_caller_mac_never_verifies_as_a_call_mac() -> None:
    now = time.time()
    expires = int(now) + 60
    forged = caller_claim_mac(KEY, ref=REF, e164="call-1", expires_at=expires)
    assert not verify_call_claim(KEY, **_claim(now, mac=forged))  # type: ignore[arg-type]


def test_a_sealed_token_round_trips_and_hides_its_payload() -> None:
    token = carrier_token.seal(SECRET, "transfer", {"to": "+919876543210"}, ttl_s=60)
    assert "9876543210" not in token
    opened = carrier_token.open_sealed(SECRET, "transfer", token)
    assert opened is not None and opened["to"] == "+919876543210"


def test_a_sealed_token_is_refused_for_another_purpose_key_expiry_or_tamper() -> None:
    token = carrier_token.seal(SECRET, "transfer", {"to": "+91"}, ttl_s=60)
    assert carrier_token.open_sealed(SECRET, "other", token) is None
    assert carrier_token.open_sealed("t" * 40, "transfer", token) is None
    assert carrier_token.open_sealed(SECRET, "transfer", token, now=time.time() + 120) is None
    flipped = token[:-2] + ("A" if token[-2] != "A" else "B") + token[-1]
    assert carrier_token.open_sealed(SECRET, "transfer", flipped) is None
    assert carrier_token.open_sealed(SECRET, "transfer", "%%%") is None
    assert carrier_token.open_sealed(None, "transfer", token) is None
    assert carrier_token.open_sealed("short", "transfer", token) is None
    assert carrier_token.open_sealed(SECRET, "transfer", "x" * 5000) is None
