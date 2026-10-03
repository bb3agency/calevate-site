"""The telephony carrier, as the deployables that touch it share it.

One switch (`Settings.carrier`) chooses the carrier the platform DIALS and BINDS numbers
on. Every carrier's answer and events routes stay served, so a number already pointed at a
carrier keeps working after the switch moves. What each deployable does with a carrier
lives in its own small seam (`apps/voice-runtime/carrier_routes.py`,
`apps/api/engine/carrier.py`, `apps/voice-worker/voice_worker/carrier.py`); this module
holds only the names and URL shapes all of them must agree on.

The Vobiz facts below are VERIFIED-VENDOR-DOCS, cited into the hash-pinned mirror
`vobiz-findings/mirror/pages/` (see `docs/evidence/vobiz-api-contract.md`).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final, Literal, get_args
from urllib.parse import quote

CarrierName = Literal["vobiz", "plivo"]

CARRIERS: Final[tuple[CarrierName, ...]] = get_args(CarrierName)

#: The carrier for the live in-call testing phase (founder decision, D-662).
DEFAULT_CARRIER: Final[CarrierName] = "vobiz"

#: What pinned Pipecat 1.10.0's auto-detection calls each carrier's WebSocket `start` frame
#: (`pipecat/runner/utils.py:89-96`). Vobiz's `start` carries `start.streamId` and
#: `start.callId` (`xml/stream/stream-events.md:81-97`), the exact keys Pipecat reads as
#: Plivo, so the detection cannot tell the two apart and the control plane's claim decides.
WIRE_FAMILY: Final[Mapping[CarrierName, str]] = {"vobiz": "plivo", "plivo": "plivo"}

CARRIER_PATH_PREFIX: Final = "/carrier/v1"

#: The ARQ job a carrier status/hangup callback is handed to by voice-runtime, and the
#: job `apps/workers` registers under that name. Payload keys: `carrier`, `carrier_call_id`,
#: `event`, `engine_agent_ref`, `call_id` (ours, outbound only, may be None),
#: `inbox_row_id`, `fields` (the callback's form fields minus phone numbers).
CARRIER_EVENT_JOB: Final = "ingest_carrier_event"

#: Vobiz's published source addresses for HTTP callbacks, India
#: (`vobiz-findings/mirror/pages/concepts/ip-whitelisting.md:93-107`, fetched 2 Oct 2026).
#: The vendor says they are "subject to change" (`:27-29`), so
#: `Settings.vobiz_callback_ips` overrides them without a release.
VOBIZ_CALLBACK_IPS: Final[tuple[str, ...]] = (
    "15.206.6.156",
    "35.154.59.246",
    "15.207.8.226",
)


def is_carrier(value: str) -> bool:
    """True when `value` names a carrier this build knows."""
    return value in CARRIERS


def _segment(value: str) -> str:
    # The agent ref contains colons; quoting with no safe characters keeps it one path
    # segment through every proxy and ASGI server in this tree.
    return quote(value, safe="")


#: The last path segment of an answer URL whose agent was PUBLISHED announcing a recording
#: (`AgentConfig.call_is_recorded`). voice-runtime records a call only when its answer URL
#: carries it, so a call is never recorded for an agent whose opening and truthful answer
#: say it is not (hard rule 5), and the route needs no database read to know (hard rule 3).
RECORDED_SEGMENT: Final = "recorded"


def answer_path(
    carrier: CarrierName, ref: str, *, call_id: str | None = None, recorded: bool = False
) -> str:
    """Path of the answer document for one agent; outbound dials add OUR call id.

    The call id and the recorded flag are PATH segments, never query parameters, because
    Vobiz signs the callback URL with its query stripped
    (`concepts/validating-callbacks.md:35-52`): a query value would ride the request
    unauthenticated.
    """
    path = f"{CARRIER_PATH_PREFIX}/{carrier}/answer/{_segment(ref)}"
    if call_id:
        path = f"{path}/outbound/{_segment(call_id)}"
    return f"{path}/{RECORDED_SEGMENT}" if recorded else path


def events_path(carrier: CarrierName, ref: str, *, call_id: str | None = None) -> str:
    """Path of the status/hangup callback for one agent (and one outbound call)."""
    path = f"{CARRIER_PATH_PREFIX}/{carrier}/events/{_segment(ref)}"
    return f"{path}/outbound/{_segment(call_id)}" if call_id else path


def transfer_path(carrier: CarrierName, token: str) -> str:
    """Path of the `<Dial>` document a live transfer is redirected to."""
    return f"{CARRIER_PATH_PREFIX}/{carrier}/transfer/{_segment(token)}"


__all__ = [
    "CARRIERS",
    "CARRIER_EVENT_JOB",
    "CARRIER_PATH_PREFIX",
    "DEFAULT_CARRIER",
    "RECORDED_SEGMENT",
    "VOBIZ_CALLBACK_IPS",
    "WIRE_FAMILY",
    "CarrierName",
    "answer_path",
    "events_path",
    "is_carrier",
    "transfer_path",
]
