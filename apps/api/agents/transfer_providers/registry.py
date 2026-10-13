"""Whether this engine can hand a caller to a person, and the named reason when it cannot.

The hand-over is the engine's own in-call transfer (`EngineCapabilities.in_call_handoff`),
run from a destination fixed at publish. We place no second leg of our own: the call's
telephony is the engine's, so our hand-over action can only tell the caller the truth
(`agents/handoff.HANDOFF_DEGRADED_SAY`) and offer a call-back.
"""

from __future__ import annotations

from typing import Final

from calevate_shared.engine import VoiceEngine

#: Our hand-over action was asked on a call whose telephony leg the engine holds.
NOT_OUR_CARRIER_LEG: Final = "not_our_carrier_leg"
#: This engine can hand a caller to a person by no mechanism. It is what a client's own
#: screen renders, so it lives beside its sentence in `agents/handoff._UNAVAILABLE_REASONS`.
PLATFORM_CANNOT_TRANSFER: Final = "platform_cannot_transfer"


#: Engines whose in-call hand-over is a live transfer only on some carriers' numbers, and the
#: sentence the hand-over screen shows about it. ThinnestAI transfers on numbers it rents and
#: on Plivo or Telnyx numbers; on any other it falls back to flagging the conversation, and its
#: agent says somebody will follow up (thinnest-findings/mirror/snapshots/2026-10-08/pages/
#: channels/voice.md:483-492). Client copy, so no vendor is named (D-679).
CARRIER_LIMITED_TRANSFER_NOTES: Final[dict[str, str]] = {
    "thinnest": (
        "A caller is put through live on numbers rented through Calevate. On a number "
        "brought from another phone company that cannot transfer, the voice platform marks "
        "the request instead and tells the caller somebody will follow up."
    ),
}


def transfer_platform_note(engine: VoiceEngine) -> str | None:
    """What the hand-over screen should say about where live transfer works, or None."""
    if not engine.capabilities.in_call_handoff:
        return None
    return CARRIER_LIMITED_TRANSFER_NOTES.get(engine.name)


def transfer_blocked_reason(engine: VoiceEngine) -> str | None:
    """Can THIS engine hand a caller to a person at all? None if it can.

    An agent whose engine cannot transfer is published WITHOUT a handover destination and
    its client is told so on their own screen, rather than being unable to publish the agent
    at all: the roster is not the agent.
    """
    return None if engine.capabilities.in_call_handoff else PLATFORM_CANNOT_TRANSFER


__all__ = [
    "CARRIER_LIMITED_TRANSFER_NOTES",
    "NOT_OUR_CARRIER_LEG",
    "PLATFORM_CANNOT_TRANSFER",
    "transfer_blocked_reason",
    "transfer_platform_note",
]
