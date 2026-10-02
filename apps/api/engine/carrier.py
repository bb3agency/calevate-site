"""The telephony carrier behind the owned runtime: one small interface, one per carrier.

`Settings.carrier` (D-662) picks the implementation; `get_carrier()` is the only branch on
it. Business modules and workers reach a carrier through this module and its normalized
models, never through `apps.api.engine.vobiz` or `apps.api.engine.plivo_carrier`
directly (hard rule 2; the import-linter contract forbids both by name).

Vendor facts behind the Vobiz implementation are in `docs/evidence/vobiz-api-contract.md`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Final, Literal, Protocol

from calevate_shared.carrier import CarrierName
from calevate_shared.config import Settings
from calevate_shared.events import CallDirection, CallStatus

from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings

#: The refusal code for a carrier operation whose vendor surface has not been read. Not
#: `engine_capability_absent`: that says "this platform cannot", and an operator who reads
#: it goes looking for a different platform rather than for one document.
CARRIER_UNVERIFIED_CODE: Final = "engine_capability_unverified"


def capability_unverified(*, title: str, detail: str, remediation: str) -> ProblemError:
    """The one constructor for that refusal, so every raise site names the same code."""
    return ProblemError(
        kind="dependency",
        code=CARRIER_UNVERIFIED_CODE,
        title=title,
        detail=detail,
        remediation=remediation,
    )


#: What a carrier callback said happened, in our words.
CarrierEventKind = Literal["ringing", "answered", "hangup", "machine", "stream", "other"]


@dataclass(frozen=True, slots=True)
class PlacedCall:
    """A dial the carrier ACCEPTED. Accepted is not answered (`call/make-call.md:122-124`)."""

    carrier: CarrierName
    carrier_call_id: str


@dataclass(frozen=True, slots=True)
class CarrierCallEvent:
    """One status or hangup callback, normalized. No phone number is carried."""

    carrier: CarrierName
    carrier_call_id: str
    kind: CarrierEventKind
    #: Our status vocabulary, when the event decides one (`hangup` always does).
    status: CallStatus | None
    raw_event: str
    direction: CallDirection | None = None
    #: The carrier's hangup cause name, for the forensic record only.
    hangup_cause: str | None = None


@dataclass(frozen=True, slots=True)
class CarrierCdr:
    """The carrier's record of one finished call: the authority on the billable minute.

    `total_cost_inr` is None unless the carrier reported the charge in INR; a charge in any
    other currency, or none, never reaches `unit_cost_paid` (hard rule 7).
    """

    carrier: CarrierName
    carrier_call_id: str
    billed_seconds: int
    duration_seconds: int
    total_cost_inr: Decimal | None
    currency: str | None
    answered_at: datetime | None
    ended_at: datetime | None
    hangup_cause: str | None = None
    raw_fields: tuple[str, ...] = field(default=())


class CarrierClient(Protocol):
    """What the platform asks of a carrier. Every method refuses with a named
    `ProblemError` when the carrier cannot do it; none returns a guessed answer."""

    @property
    def name(self) -> CarrierName: ...

    def configured(self) -> bool:
        """True when the credentials this carrier needs are present."""
        ...

    def unavailable(self, operation: str) -> ProblemError | None:
        """The refusal every operation on this carrier gives right now, or None.

        Asked BEFORE a caller assembles a request, so a carrier that cannot act at all is
        refused by its own name rather than by whichever precondition happened to be
        checked first. `operation` completes "This voice platform cannot …".
        """
        ...

    async def place_call(
        self,
        *,
        from_e164: str,
        to_e164: str,
        answer_url: str,
        hangup_url: str,
        ring_url: str,
        time_limit_s: int,
    ) -> PlacedCall: ...

    async def hang_up(self, carrier_call_id: str) -> bool:
        """True when the call was ended now, False when it had already ended."""
        ...

    async def transfer(self, carrier_call_id: str, *, redirect_url: str) -> None: ...

    async def fetch_cdr(self, carrier_call_id: str) -> CarrierCdr | None:
        """None while the carrier has not written the record yet."""
        ...

    async def bind_number(
        self,
        e164: str,
        *,
        answer_url: str,
        hangup_url: str,
        label: str,
        known_binding_id: str | None = None,
    ) -> str:
        """Point a number the account holds at our answer URL. Returns the carrier's
        binding id (Vobiz: the Application id). `known_binding_id` is the id this number
        was last bound to; a carrier may use it only after confirming it is `label`'s."""
        ...

    async def unbind_number(self, e164: str) -> None: ...

    async def probe(self) -> bool:
        """A read-only credential check. True when the credentials authenticate."""
        ...

    def parse_event(self, fields: dict[str, str]) -> CarrierCallEvent | None:
        """A callback's form fields, normalized; None when it names no call."""
        ...


#: The module that implements each carrier. Hard rule 2's import-linter contract forbids
#: each of these to the rest of the tree, and `tests/engine_name_drift_test.py` reads this
#: map to tell a carrier adapter from a stale contract entry.
CARRIER_ADAPTER_MODULES: Final[Mapping[CarrierName, str]] = {
    "vobiz": "apps.api.engine.vobiz",
    "plivo": "apps.api.engine.plivo_carrier",
}


def build_carrier(cfg: Settings, name: CarrierName | None = None) -> CarrierClient:
    """The carrier named (default: the switch), built from these settings."""
    chosen: CarrierName = name or cfg.carrier
    if chosen == "vobiz":
        from apps.api.engine.vobiz import VobizCarrier

        return VobizCarrier.from_settings(cfg)
    from apps.api.engine.plivo_carrier import PlivoCarrier

    return PlivoCarrier()


def get_carrier(name: CarrierName | None = None) -> CarrierClient:
    """The carrier for this request, read from the live settings snapshot."""
    return build_carrier(get_settings(), name)


__all__ = [
    "CARRIER_ADAPTER_MODULES",
    "CARRIER_UNVERIFIED_CODE",
    "CarrierCallEvent",
    "CarrierCdr",
    "CarrierClient",
    "CarrierEventKind",
    "PlacedCall",
    "build_carrier",
    "get_carrier",
]
