"""The telephony carrier behind the owned runtime: one small interface, one per carrier.

`Settings.carrier` (D-662) picks the implementation; `get_carrier()` is the only branch on
it. Business modules and workers reach a carrier through this module and its normalized
models, never through `apps.api.engine.vobiz` or `apps.api.engine.plivo_carrier`
directly (hard rule 2; the import-linter contract forbids both by name).

Vendor facts behind the Vobiz implementation are in `docs/evidence/vobiz-api-contract.md`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Final, Literal, Protocol, cast, runtime_checkable

from calevate_shared.carrier import CarrierName, is_carrier
from calevate_shared.config import Settings
from calevate_shared.engine import EngineAgentRef, ProvisionedNumber
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


#: How long an outbound dial may ring before the carrier gives up, in seconds. Sent as
#: Vobiz's `ring_timeout`, which their call-create example carries
#: (`vobiz-findings/mirror/pages/call/make-call.md:83`) and their hangup-cause table names as
#: the API knob for code 6010 (`concepts/hangup-causes.md:119`), but which the parameter table
#: omits, so whether it is honoured is UNKNOWN (`docs/evidence/vobiz-api-contract.md` §2).
#:
#: NOT `hangup_on_ring`, which the table does list: "Max duration (in seconds) from start of
#: ringing to hangup" (`make-call.md:72`) reads as a cap on the whole call measured from the
#: first ring, answered or not, and a short value there would cut every conversation.
RING_TIMEOUT_S: Final = 60

#: The ring timeout the carrier applies when none is honoured: "Default is 120 seconds"
#: (`concepts/hangup-causes.md:119`). The line count's ring horizon is built on the longer of
#: the two, so it holds whether or not `ring_timeout` is read.
CARRIER_DEFAULT_RING_TIMEOUT_S: Final = 120

#: What a carrier callback said happened, in our words.
CarrierEventKind = Literal[
    "ringing", "answered", "hangup", "machine", "stream", "recording", "other"
]


@dataclass(frozen=True, slots=True)
class CarrierRecording:
    """A finished carrier-side recording of one call, as its callback reported it.

    `recording_id` is the carrier's opaque id and the only reference we store
    (`calls.carrier_recording_id`); no URL and no number travels with it (hard rule 6).
    """

    recording_id: str
    duration_s: int | None = None
    #: The carrier's reason the recording stopped. Anything but the call ending means the
    #: file may be shorter than the conversation.
    end_reason: str | None = None
    ended_with_call: bool = True


@dataclass(frozen=True, slots=True)
class CarrierRecordingSource:
    """Where to fetch one recording's bytes, and the headers the fetch must carry.

    `auth_hosts` bounds where `auth_headers` may be sent: a redirect to any other host is
    followed WITHOUT them, so a carrier credential never reaches a third party.
    """

    url: str
    auth_headers: Mapping[str, str]
    auth_hosts: frozenset[str]


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
    #: The carrier's numeric hangup code, when the callback carried one.
    hangup_cause_code: int | None = None
    #: On a `recording` event, the finished recording.
    recording: CarrierRecording | None = None


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
    #: The carrier's numeric hangup code, when the record carries one.
    hangup_cause_code: int | None = None
    #: How the call ended in our vocabulary, read by the carrier's own adapter from its
    #: cause name and code (the same mapping its hangup callback uses). None when the
    #: adapter has no mapping to offer.
    status: CallStatus | None = None


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
        ring_timeout_s: int,
    ) -> PlacedCall:
        """`ring_timeout_s` bounds how long an unanswered dial rings; `time_limit_s` bounds
        the answered call."""
        ...

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

    async def find_binding(self, label: str) -> str | None:
        """The binding id `bind_number` created for `label`, or None if there is none."""
        ...

    async def delete_binding(self, binding_id: str) -> bool:
        """Remove a binding no number uses any more. True when it was removed now, False
        when it was already gone."""
        ...

    async def list_numbers(self) -> list[ProvisionedNumber]:
        """Every number the carrier account holds, read from the carrier."""
        ...

    async def probe(self) -> bool:
        """A read-only credential check. True when the credentials authenticate."""
        ...

    def parse_event(self, fields: dict[str, str]) -> CarrierCallEvent | None:
        """A callback's form fields, normalized; None when it names no call."""
        ...

    async def recording_source(
        self, recording_id: str, *, carrier_call_id: str
    ) -> CarrierRecordingSource | None:
        """Where the recording's bytes are, after confirming it belongs to that call.

        None when the carrier no longer holds it (deleted or expired). A recording the
        carrier attributes to a DIFFERENT call is refused, never fetched.
        """
        ...

    async def find_recording(self, carrier_call_id: str) -> str | None:
        """The id of a recording the carrier holds for this call, or None."""
        ...

    async def delete_recording(self, recording_id: str) -> bool:
        """Delete the carrier's copy. True when deleted now, False when already gone."""
        ...

    async def aclose(self) -> None:
        """Release the carrier's HTTP connections. Safe to call more than once."""
        ...


@runtime_checkable
class RetiresAgentBindings(Protocol):
    """An engine adapter that can remove what the carrier holds for a retired agent.

    Not on `VoiceEngine`: only an adapter whose carrier keeps a per-agent routing object
    (Vobiz's Application) has anything to remove, and `agents.lifecycle.archive_agent`
    asks by `isinstance` rather than every adapter growing a no-op.
    """

    async def retire_agent_bindings(self, ref: EngineAgentRef) -> bool:
        """True when a carrier object was removed now, False when there was none."""
        ...


#: The module that implements each carrier. Hard rule 2's import-linter contract forbids
#: each of these to the rest of the tree, and `tests/engine_name_drift_test.py` reads this
#: map to tell a carrier adapter from a stale contract entry.
CARRIER_ADAPTER_MODULES: Final[Mapping[CarrierName, str]] = {
    "vobiz": "apps.api.engine.vobiz",
    "plivo": "apps.api.engine.plivo_carrier",
}


def build_carrier(cfg: Settings, name: CarrierName | None = None) -> CarrierClient:
    """A NEW carrier client for the carrier named (default: the switch), from these settings.

    Uncached, for a caller that hands in a `Settings` of its own (readiness, the credential
    probe's candidate pair) and must not be answered by a client built from another. Such a
    caller owns the client and closes it (`aclose`) if it made a request; every other caller
    goes through `get_carrier`.
    """
    chosen: CarrierName = name or cfg.carrier
    if chosen == "vobiz":
        from apps.api.engine.vobiz import VobizCarrier

        return VobizCarrier.from_settings(cfg)
    from apps.api.engine.plivo_carrier import PlivoCarrier

    return PlivoCarrier()


def carrier_of_record(recorded: str | None) -> CarrierName:
    """The carrier a call is on: the one stamped on its `calls.carrier`, or the switch for a
    row that predates the column. Every operation on an existing call resolves through this,
    so moving `Settings.carrier` never redirects a hang-up or a call-record read to an
    account that does not hold the call."""
    if recorded is not None and is_carrier(recorded):
        return cast(CarrierName, recorded)
    return get_settings().carrier


#: One client per carrier, with the identity it was built from. Keyed by carrier NAME so a
#: rotated credential or a moved base URL REPLACES the entry rather than adding one beside
#: it; the replaced client is dropped without `aclose` (a sync caller cannot await it), which
#: leaves at most one idle connection pool per rotation for the garbage collector.
_clients: dict[CarrierName, tuple[tuple[object, ...], CarrierClient]] = {}


def _identity(cfg: Settings, name: CarrierName) -> tuple[object, ...]:
    """What a client is built from, plus the event loop it will run on.

    The loop is part of the key because an `httpx.AsyncClient`'s pooled connections belong to
    the loop that opened them: one process runs one loop, but a test suite runs one per test,
    and a client reused across them fails on a closed loop.
    """
    try:
        loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if name == "vobiz":
        # The last two build the fallback answer URL the client registers (D-675).
        return (
            loop,
            cfg.vobiz_auth_id,
            cfg.vobiz_auth_token,
            cfg.vobiz_api_base_url,
            cfg.webhook_base_url,
            cfg.vobiz_callback_secret,
        )
    return (loop,)


def get_carrier(name: CarrierName | None = None) -> CarrierClient:
    """The carrier named (default: the switch), from the live settings snapshot.

    Memoised per carrier, so the CDR reader, transfers and every dial share one HTTP client
    instead of each opening a pool nothing ever closes. The switch is read on every call, so
    moving `Settings.carrier` takes effect on the next operation without a restart.
    """
    cfg = get_settings()
    chosen: CarrierName = name or cfg.carrier
    identity = _identity(cfg, chosen)
    held = _clients.get(chosen)
    if held is not None and held[0] == identity:
        return held[1]
    client = build_carrier(cfg, chosen)
    _clients[chosen] = (identity, client)
    return client


__all__ = [
    "CARRIER_ADAPTER_MODULES",
    "CARRIER_DEFAULT_RING_TIMEOUT_S",
    "CARRIER_UNVERIFIED_CODE",
    "RING_TIMEOUT_S",
    "CarrierCallEvent",
    "CarrierCdr",
    "CarrierClient",
    "CarrierEventKind",
    "CarrierRecording",
    "CarrierRecordingSource",
    "PlacedCall",
    "RetiresAgentBindings",
    "build_carrier",
    "carrier_of_record",
    "get_carrier",
]
