"""`CartesiaEngine._snapshot` / `parse_webhook` — the direction default.

Cartesia's `AgentCall` object carries NO `direction` field (read at source — see
`_snapshot`'s docstring), so whatever the parser falls back to is what EVERY reconciled
and fetched Line call is labelled. That default must be OUTBOUND, for the reasons the
Bolna adapter documents and `tests/bolna_snapshot_test.py` pins for its own parser:
outbound is the compliance-safe side (DNC and calling-hours obligations live there, so a
misclassified call is over-regulated, never under), it is consistent with the
straight-through `from`/`to` mapping the snapshot uses, and it is what this file's own
`parse_webhook` already returns. `_snapshot` used to default INBOUND — the opposite on all
three counts — which this covers.
"""

from __future__ import annotations

from typing import Any

from apps.api.engine.cartesia import CartesiaEngine


def _engine() -> CartesiaEngine:
    return CartesiaEngine(api_key="test-key")


def _completed(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": "cart_call_1",
        "agent_id": "agent_xyz",
        "status": "completed",
        "start_time": "2026-08-10T09:15:00Z",
        "end_time": "2026-08-10T09:16:35Z",
        "telephony_params": {"from": "+911140000000", "to": "+919876543210"},
    }
    payload.update(overrides)
    return payload


def test_a_payload_with_no_direction_field_falls_back_to_outbound() -> None:
    """The real Cartesia shape has no `direction`, so this is the branch every live call
    takes. Outbound is the compliance-safe default and the one consistent with the
    straight-through from/to mapping."""
    snapshot = _engine()._snapshot(_completed())
    assert snapshot.direction == "outbound"


def test_an_explicit_inbound_direction_is_still_honoured() -> None:
    """If the vendor ever does state a direction, it wins over the default."""
    snapshot = _engine()._snapshot(_completed(direction="inbound"))
    assert snapshot.direction == "inbound"


def test_snapshot_and_webhook_agree_on_the_default() -> None:
    """Two code paths, one question: a payload naming no direction must classify the same
    way whether it arrives through the poller (`_snapshot`) or a webhook (`parse_webhook`).
    They defaulted oppositely before the fix."""
    engine = _engine()
    snapshot_direction = engine._snapshot(_completed()).direction
    event_direction = engine.parse_webhook(_completed()).direction
    assert snapshot_direction == event_direction == "outbound"
