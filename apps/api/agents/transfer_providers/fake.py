"""The in-house adapter — a REAL adapter over a contract we own, not a mock.

Same role `engine/fake.py` plays for the voice engine and `kyc_providers/fake.py` for the
verification seam, and it exists here for the sharper of the two reasons: NO carrier's
transfer contract is readable from this environment (see `plivo.py`), so without this
adapter the whole handover path — the capability ladder, the caller-ID rule, the whisper,
the attempt row, the four unsuccessful endings and the degradation to a call-back — would
be code nothing has ever executed, on a product where no real call has ever been placed
(BLOCKER-1).

ITS CONTRACT IS OURS AND IS THEREFORE ENFORCEABLE
---------------------------------------------------
It is not a yes-machine. It refuses a `TransferRequest` that breaks a rule this seam
states, because an adapter that accepts anything proves nothing about the code that calls
it:

* an empty whisper — step 2 of the pattern is what makes the difference between a person
  and a voicemail greeting, and a silent whisper is a bridge;
* no accept key — the same rule from the other side;
* a destination equal to the presented header — dialling a number from itself;
* a non-positive ring or whisper timeout — an unbounded wait is the caller's wait.

Every one of those is a mistake the FIRST real adapter could make, which is why they are
asserted against the one adapter that can run.

WHAT IT DOES NOT DO, SAID PLAINLY: it places no telephony leg. It is refused outside a
developer's machine by `registry.available_transfer()` for exactly that reason — a
"transfer" that returns `bridged` and rings nobody is a caller told to hold who is then
holding for nothing, which is the failure the whole accept-before-bridge pattern exists to
make unreachable.
"""

from __future__ import annotations

from uuid import uuid4

from apps.api.agents.transfer_providers.base import (
    TransferOutcome,
    TransferRefusedError,
    TransferRequest,
    TransferStarted,
)


class FakeTransfers:
    """A transfer that behaves exactly as dictated, and records what it was asked to do."""

    def __init__(
        self, *, outcome: TransferOutcome = "bridged", bridged_seconds: int | None = 42
    ) -> None:
        self._outcome = outcome
        self._bridged_seconds = bridged_seconds
        #: Every request handed to this adapter, in order. A test asserts the DESTINATION,
        #: the presented header and the whisper the seam composed — the three things a
        #: caller and a client would otherwise have to discover on a live call.
        self.requests: list[TransferRequest] = []

    @property
    def name(self) -> str:
        return "fake"

    @property
    def contract_verified(self) -> bool:
        # The contract is OURS — `base.py` states it and this module implements it — so
        # there is no vendor page to read and nothing to be wrong about.
        return True

    @property
    def settles_synchronously(self) -> bool:
        # It drives both ends, so there is nothing to wait for.
        return True

    async def start_transfer(self, request: TransferRequest) -> TransferStarted:
        if not request.whisper.strip():
            raise TransferRefusedError("a transfer with no whisper is a blind bridge")
        if not request.accept_key.strip():
            raise TransferRefusedError("a transfer with no accept key cannot be accepted")
        if request.to_e164 == request.present_as:
            raise TransferRefusedError("the second leg would present the number it is dialling")
        if request.ring_timeout_s <= 0 or request.whisper_timeout_s <= 0:
            raise TransferRefusedError("a transfer with no timeout is an unbounded hold")
        self.requests.append(request)
        return TransferStarted(
            provider_ref=f"fake-transfer-{uuid4()}",
            outcome=self._outcome,
            # Only a bridged leg has billable seconds: a leg nobody accepted was torn down
            # before it carried anything.
            bridged_seconds=self._bridged_seconds if self._outcome == "bridged" else None,
            raw_status=f"fake:{self._outcome}",
        )


__all__ = ["FakeTransfers"]
