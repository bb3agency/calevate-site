"""Plivo — selectable by the carrier switch, and every operation refuses by name.

`api.plivo.com` and `www.plivo.com/docs/` are EGRESS-BLOCKED from the build environment
(`curl: (56) CONNECT tunnel failed, response 403`, `docs/evidence/pre-build-blockers-
2026-09-13.md` §10), and the pinned Pipecat wheel holds exactly one Plivo REST endpoint, the
hang-up (`pipecat/serializers/plivo.py:184`). So the method, path and body of every other
carrier call are UNKNOWN, and writing them would invent an API (hard rule 11). Each method
refuses with `engine_capability_unverified`, which says "not read yet" rather than "this
platform cannot".

Hanging a Plivo call up stays the worker serializer's job; nothing here reaches Plivo.
"""

from __future__ import annotations

from typing import Final

from calevate_shared.carrier import CarrierName

from apps.api.core.errors import ProblemError
from apps.api.engine.carrier import (
    CarrierCallEvent,
    CarrierCdr,
    PlacedCall,
    capability_unverified,
)

#: Why every Plivo operation is a refusal, in the words an operator gets.
CARRIER_REMEDIATION: Final = (
    "The telephony leg of this engine is not built yet: its provider's REST surface is "
    "not reachable from the build environment and has not been read. Nothing here is "
    "broken — this half has not been written. See docs/evidence/"
    "pre-build-blockers-2026-09-13.md §10."
)


def carrier_not_written(what: str) -> ProblemError:
    """The named refusal a carrier operation owes its caller.

    `detail` names the operation, so "cannot place calls" and "cannot list its numbers"
    send an operator to different lines of the same document. The code is not in
    `apps.workers.pipeline.TRANSIENT_ENGINE_CODES`: a retry cannot write the missing half.
    """
    return capability_unverified(
        title="The voice platform cannot do that yet",
        detail=what,
        remediation=CARRIER_REMEDIATION,
    )


class PlivoCarrier:
    """`CarrierClient` for Plivo: declared, and refusing every operation by name."""

    @property
    def name(self) -> CarrierName:
        return "plivo"

    def configured(self) -> bool:
        # The adapter is unbuilt, so no credential would make it work.
        return False

    def unavailable(self, operation: str) -> ProblemError:
        return carrier_not_written(
            f"This voice platform cannot {operation} yet: its telephony leg is not built."
        )

    async def place_call(
        self,
        *,
        from_e164: str,
        to_e164: str,
        answer_url: str,
        hangup_url: str,
        ring_url: str,
        time_limit_s: int,
    ) -> PlacedCall:
        raise self.unavailable("place outbound calls")

    async def hang_up(self, carrier_call_id: str) -> bool:
        raise self.unavailable("stop a call in progress")

    async def transfer(self, carrier_call_id: str, *, redirect_url: str) -> None:
        raise self.unavailable("transfer a live call")

    async def fetch_cdr(self, carrier_call_id: str) -> CarrierCdr | None:
        raise self.unavailable("read a call record")

    async def bind_number(
        self,
        e164: str,
        *,
        answer_url: str,
        hangup_url: str,
        label: str,
        known_binding_id: str | None = None,
    ) -> str:
        raise self.unavailable("point a number at an agent")

    async def unbind_number(self, e164: str) -> None:
        raise self.unavailable("release a number's routing")

    async def probe(self) -> bool:
        raise self.unavailable("check its carrier credential")

    def parse_event(self, fields: dict[str, str]) -> CarrierCallEvent | None:
        raise self.unavailable("read a carrier callback")


__all__ = ["CARRIER_REMEDIATION", "PlivoCarrier", "carrier_not_written"]
