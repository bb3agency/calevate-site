"""The forwarding verification call, in our terms (D-746).

Two agents in the developer workspace place the test legs, one per platform number, because
the voice platform refuses a second live call from one agent to the same number (409
`call_in_progress`, place-call.md:541-544 in snapshots/2026-10-08) and a number is lent to one
calling agent at a time (update-phone-number.md:144-145). They are found by fixed names, never
recorded in `agents`, and answer nothing: they are only ever a number's calling agent.

What a person hears if they pick up the published phone is `TEST_CALL_PURPOSE`, the first
thing the callee hears (place-call.md:657-676). It names no vendor and says what the call is.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Protocol, runtime_checkable

#: Indexed by leg: leg 1 rings from the shared trial number, leg 2 from the second number.
FORWARDING_TEST_AGENT_NAMES: Final = (
    "Calevate forwarding test, line 1 (automated)",
    "Calevate forwarding test, line 2 (automated)",
)

#: Truthful and plain (hard rule 5): an automated test from the business's call service,
#: checking forwarding, nobody needs to stay on. At most 300 characters (place-call.md:660).
TEST_CALL_PURPOSE: Final = (
    "This is an automated test call from your business's call service, checking that call "
    "forwarding works. No one needs to answer. You can hang up now."
)

#: This call's instructions only (`overrides.callInstructions`, ≤4000, place-call.md:1103-1137).
TEST_CALL_INSTRUCTIONS: Final = (
    "You are an automated test call checking that a business's call forwarding works. You "
    "have already said why you are calling. Say nothing more unless someone asks you "
    "something. If anyone asks whether you are a person or an AI, say you are an automated "
    "test call and no person is on this line. If anyone asks whether the call is recorded, "
    "say it may be recorded. Do not ask questions and do not offer anything."
)

#: The shortest per-call limit the platform takes (60 to 1200 seconds, place-call.md:1103-1126).
#: We hang the legs up ourselves well before it.
TEST_CALL_MAX_SECONDS: Final = 60


@dataclass(frozen=True, slots=True)
class ForwardingLegReport:
    """What the platform says about one leg."""

    ended: bool
    #: True once the far end picked up: a person, voicemail, or the forwarded agent.
    answered: bool | None
    seconds: int | None


@runtime_checkable
class PlacesForwardingTests(Protocol):
    """An engine that can place the forwarding verification call."""

    async def converge_forwarding_test_agent(self, leg: int) -> str: ...

    async def place_forwarding_test_call(
        self, *, agent_ref: str, from_e164: str, to_e164: str, reference: str
    ) -> str: ...

    async def read_forwarding_leg(self, handle: str) -> ForwardingLegReport: ...

    async def hang_up_forwarding_leg(self, handle: str) -> None: ...


__all__ = [
    "FORWARDING_TEST_AGENT_NAMES",
    "TEST_CALL_INSTRUCTIONS",
    "TEST_CALL_MAX_SECONDS",
    "TEST_CALL_PURPOSE",
    "ForwardingLegReport",
    "PlacesForwardingTests",
]
