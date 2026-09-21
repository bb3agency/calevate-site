"""Which carrier may transfer a caller on this deployment, and the named reason when none.

THE ANSWER TODAY IS NONE, AND THAT IS THE GATE WORKING RATHER THAN A GAP. Three facts
have to hold, and they are facts about three different things:

1. **The carrier leg is OURS to act on.** Only an `owned_runtime` engine leaves the second
   leg to us: on a rented control plane the vendor holds the call and supplies its own
   in-call handover (`EngineCapabilities.in_call_handoff`), and a second mechanism beside
   it would be two ways to do one thing with a caller in the middle.
2. **That carrier has an adapter.** `plivo` is declared and unimplemented because its
   transfer grammar is unread (`plivo.py`), and a carrier with no adapter at all is a
   refusal rather than a crash.
3. **The adapter's contract was read from the carrier's own documentation.** The in-house
   adapter is the only one that passes, because its contract is ours — and it is refused
   off a developer's machine for the reason its own rung gives below.

**ONE SELECTOR, ASKED BY EVERYONE** — the in-call tool, the publish path and the client's
own handover screen all reach this through `agents/handoff_execution`, so a screen can
never promise what the tool refuses. Same discipline `kyc_providers.available_provider`
and `billing.payment_capability` follow.

**WHICH CARRIER IS NOT AN OPERATOR'S CHOICE AND HAS NO SETTING.** It is decided by the
answer path: one carrier per answer URL, bound to the number (D-610). Making it config
would let a deployment claim a carrier its calls do not arrive on, which is a claim no
screen could check.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from calevate_shared.engine import VoiceEngine

from apps.api.agents.transfer_providers.base import (
    TRANSFER_PROVIDERS,
    CallTransferProvider,
    TransferContractUnverifiedError,
)
from apps.api.agents.transfer_providers.fake import FakeTransfers
from apps.api.agents.transfer_providers.plivo import PlivoTransfers
from apps.api.core.settings import get_settings
from apps.api.engine import get_engine

#: The machine reasons. Client-facing sentences live in `agents/handoff.py` beside the
#: other five, so one condition is never explained in two voices.
NOT_OUR_CARRIER_LEG: Final = "not_our_carrier_leg"
PROVIDER_CONTRACT_UNVERIFIED: Final = "transfer_contract_unverified"
#: The in-house adapter, named on a deployment that is not a developer's machine.
PROVIDER_NOT_LICENSED: Final = "transfer_provider_not_licensed"
#: The whole platform, rather than any one carrier: this engine can hand a caller to a
#: person by NEITHER mechanism. It is what a client's own screen renders, so it lives
#: beside its sentence in `agents/handoff._UNAVAILABLE_REASONS`.
PLATFORM_CANNOT_TRANSFER: Final = "platform_cannot_transfer"


def _carrier_of_engine(engine_name: str) -> str | None:
    """WHICH CARRIER HOLDS THE LEG OF A CALL THIS ENGINE ANSWERED, or None where the call
    is not ours to act on.

    A BRANCH PER ENGINE RATHER THAN A TABLE KEYED BY ENGINE NAME, and the shape is forced:
    a dict literal carrying two engine names is a second spelling of a set with exactly two
    homes, which `tests/engine_name_drift_test.py` fails by name. A factory that branches
    per engine is the sanctioned form — `engine/__init__.build_engine` is the same shape
    for the same reason.

    The answer is derived from the answer path rather than configured: one carrier per
    answer URL, bound to the number (D-610). Config here would let a deployment claim a
    carrier its calls do not arrive on, which is a claim no screen could check.
    """
    if engine_name == "pipecat":
        return "plivo"
    if engine_name == "fake":
        return "fake"
    return None


@dataclass(frozen=True, slots=True)
class TransferCapability:
    """A provider, or the named reason there is none. Never both, never neither."""

    provider: CallTransferProvider | None
    reason: str | None

    @property
    def available(self) -> bool:
        return self.provider is not None


def _build(carrier: str) -> CallTransferProvider:
    """The adapter for one carrier, or a refusal naming what it would take to write it."""
    if carrier == "fake":
        return FakeTransfers()
    if carrier == "plivo":
        return PlivoTransfers()
    raise TransferContractUnverifiedError(
        f"No transfer adapter has been written for {carrier!r}. See "
        "`transfer_providers/plivo.py` for the five facts a carrier adapter needs and the "
        "prompt that fetches them."
    )


def available_transfer(engine: VoiceEngine | None = None) -> TransferCapability:
    """The one selector. Fails CLOSED at every step, with the reason attached."""
    adapter = engine if engine is not None else get_engine()
    if adapter.capabilities.agent_hosting != "owned_runtime":
        return TransferCapability(None, NOT_OUR_CARRIER_LEG)
    carrier = _carrier_of_engine(adapter.name)
    if carrier is None or carrier not in TRANSFER_PROVIDERS:
        return TransferCapability(None, NOT_OUR_CARRIER_LEG)
    if carrier == "fake" and get_settings().app_env != "local":
        # THE ONE ADAPTER THIS LADDER WOULD OTHERWISE ADMIT WITHOUT A CARRIER BEHIND IT.
        # It places no leg, so selecting it anywhere real would answer `bridged` to a
        # caller who has been told to hold and whose phone is connected to nobody — the
        # exact state accept-before-bridge exists to make unreachable, arriving through
        # the configuration instead of the wire. Refused here rather than by deleting the
        # adapter, because it is what proves this seam works at all.
        return TransferCapability(None, PROVIDER_NOT_LICENSED)
    try:
        provider = _build(carrier)
    except TransferContractUnverifiedError:
        # Answered as unavailable rather than raised: the client's own screen asks this
        # selector, and an exception there tells a blocked client nothing they can act on.
        return TransferCapability(None, PROVIDER_CONTRACT_UNVERIFIED)
    # THE SECOND HALF, AND IT IS NOT REDUNDANT — `kyc_providers/registry.py`'s reason:
    # constructing an adapter cannot fail for an unread contract, so without this the
    # registry hands back an object that raises on its first call, which here is a raise
    # with a caller on the line.
    if not provider.contract_verified:
        return TransferCapability(None, PROVIDER_CONTRACT_UNVERIFIED)
    return TransferCapability(provider, None)


def transfer_blocked_reason(engine: VoiceEngine) -> str | None:
    """Can THIS engine hand a caller to a person at all, by any mechanism? None if it can.

    TWO MECHANISMS, ASKED IN THE ORDER THEY EXIST. A rented control plane runs the handover
    itself from a destination fixed at publish (`in_call_handoff`), and where it does, this
    seam must stay out of the way — two ways to transfer one caller is the "one way per
    problem" defect with somebody on the line. Where it does not, the second leg is ours to
    place, and `available_transfer` says whether we can.

    **THIS IS WHAT REPLACED REFUSING THE PUBLISH** (`engine/pipecat.py`'s capability
    descriptor). An agent whose platform cannot transfer is published WITHOUT a handover
    destination and its client is told so on their own screen, rather than being unable to
    publish the agent at all: the roster is not the agent, and refusing the whole
    configuration took a working receptionist off the phone to prevent a promise that the
    in-call tool refuses anyway.
    """
    if engine.capabilities.in_call_handoff:
        return None
    return None if available_transfer(engine).available else PLATFORM_CANNOT_TRANSFER


__all__ = [
    "NOT_OUR_CARRIER_LEG",
    "PLATFORM_CANNOT_TRANSFER",
    "PROVIDER_CONTRACT_UNVERIFIED",
    "PROVIDER_NOT_LICENSED",
    "TransferCapability",
    "available_transfer",
    "transfer_blocked_reason",
]
