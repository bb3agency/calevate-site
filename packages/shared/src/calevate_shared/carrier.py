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
from urllib.parse import quote, urlencode

CarrierName = Literal["vobiz", "plivo"]

CARRIERS: Final[tuple[CarrierName, ...]] = get_args(CarrierName)

#: Who holds a recorded calling number (`phone_numbers.provider`): one of our carriers, or
#: an engine that rents and attaches numbers on its own account. Wider than `CarrierName`
#: on purpose — nothing dials or binds through `thinnest` as a carrier.
NumberProvider = Literal["vobiz", "plivo", "thinnest"]

#: The provider a number must carry to be presented on an engine that dials on its own
#: account. ThinnestAI calls go out only on ThinnestAI numbers (founder decision, D-678).
ENGINE_NUMBER_PROVIDER: Final[Mapping[str, NumberProvider]] = {"thinnest": "thinnest"}

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


#: The query parameter carrying our shared callback secret on every URL we register with a
#: carrier that has one (D-673, OPERATIONS §2 gate 55). Source addresses alone do not
#: authenticate a Vobiz request: every Vobiz customer sends from the same published
#: addresses, so without this anyone who learns an agent ref can point their own number at
#: our agent.
#:
#: THE QUERY, NOT A PATH SEGMENT. Vobiz signs the callback URL with its query stripped
#: (`vobiz-findings/mirror/pages/concepts/validating-callbacks.md:37,51`), so the V3
#: signature keeps verifying over the same path when signing is switched on, and our
#: routes do not change shape. The vendor's own validation samples read the requested URL
#: and strip a query from it (`:87,118`), and its campaign page documents an `answer_url`
#: carrying one (`campaign-manager/contacts/upload-contacts.md:66`); no page says in words
#: that a query on an answer or hangup URL is sent back unchanged, so the first live call
#: proves it (`runbooks/vobiz-first-live-call.md` §2), and a dropped query fails closed. A
#: path segment would also leak further: nginx, uvicorn, our spans and our error bodies all
#: record the path, and only the query is kept out of them.
CALLBACK_SECRET_PARAM: Final = "callback_key"

#: The shortest callback secret accepted, in characters. `openssl rand -hex 32` gives 64.
MIN_CALLBACK_SECRET_CHARS: Final = 32

#: Per carrier, the `Settings` fields holding the current callback secret and the previous
#: one, which is accepted (never written) during a rotation. A carrier absent here gets no
#: secret on its URLs and no check on its routes: Plivo's request authentication is unread.
CALLBACK_SECRET_SETTINGS: Final[Mapping[str, tuple[str, str]]] = {
    "vobiz": ("vobiz_callback_secret", "vobiz_callback_secret_retired"),
}


def usable_callback_secret(value: str | None) -> str | None:
    """The secret, or `None` when it is absent or shorter than the floor."""
    secret = (value or "").strip()
    return secret if len(secret) >= MIN_CALLBACK_SECRET_CHARS else None


def callback_secret_for(carrier: str, settings: object) -> str | None:
    """The secret to put on URLs registered with `carrier`, or `None` for none."""
    fields = CALLBACK_SECRET_SETTINGS.get(carrier)
    if fields is None:
        return None
    return usable_callback_secret(getattr(settings, fields[0], None))


def accepted_callback_secrets(carrier: str, settings: object) -> tuple[str, ...]:
    """Every secret a request from `carrier` may carry: the current one, then the previous."""
    fields = CALLBACK_SECRET_SETTINGS.get(carrier)
    if fields is None:
        return ()
    found = (usable_callback_secret(getattr(settings, field, None)) for field in fields)
    return tuple(secret for secret in found if secret is not None)


def with_callback_secret(url: str, secret: str | None) -> str:
    """`url` with the secret as its query. Percent-encoded, so a base64 secret's `+`, `/`
    and `=` survive the round trip (a bare `+` would arrive as a space)."""
    if secret is None:
        return url
    return f"{url}?{urlencode({CALLBACK_SECRET_PARAM: secret}, quote_via=quote)}"


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


def fallback_path(carrier: CarrierName) -> str:
    """Path of the document the carrier fetches when the answer URL fails (D-675).

    Names no agent: it must answer when everything an agent's answer depends on is broken,
    and the document it serves is the same for every call.
    """
    return f"{CARRIER_PATH_PREFIX}/{carrier}/fallback"


__all__ = [
    "CALLBACK_SECRET_PARAM",
    "CALLBACK_SECRET_SETTINGS",
    "CARRIERS",
    "CARRIER_EVENT_JOB",
    "CARRIER_PATH_PREFIX",
    "DEFAULT_CARRIER",
    "MIN_CALLBACK_SECRET_CHARS",
    "RECORDED_SEGMENT",
    "VOBIZ_CALLBACK_IPS",
    "WIRE_FAMILY",
    "CarrierName",
    "accepted_callback_secrets",
    "answer_path",
    "callback_secret_for",
    "events_path",
    "fallback_path",
    "is_carrier",
    "transfer_path",
    "usable_callback_secret",
    "with_callback_secret",
]
