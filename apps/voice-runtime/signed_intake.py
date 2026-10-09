"""Signed engine deliveries: verify per-agent HMAC, check freshness, key the unit, seal the body.

`engine_intake.verify_source` decides admission before a byte of body is read, which is
right for an engine authenticated by where it calls from and impossible for one that signs
the body. ThinnestAI signs every delivery attempt with the secret of the agent's own
endpoint, and its receiver contract is three steps (VERIFIED-VENDOR-DOCS,
`thinnest-findings/mirror/snapshots/2026-10-08/pages/api-reference/webhooks.md:100-147`):

1. verify `x-thinnest-signature-v2` = `sha256=` + hex HMAC-SHA256 of
   `<x-thinnest-delivered-at>.<raw body>`, constant-time;
2. reject a `x-thinnest-delivered-at` more than five minutes from our clock — NOT `sentAt`,
   which every retry repeats unchanged ("a retry's `sentAt` is hours old by design", :130);
3. dedupe on `x-thinnest-event-id`, the body's `id`, "the same on every retry and re-send".

The v1 header (`x-thinnest-signature`, HMAC of the body alone) is NOT accepted. The page
lets a receiver verify either (:127), and both headers ride every attempt (:100-108), so
requiring v2 refuses no genuine delivery; accepting v1 would let a captured body be
replayed at any time, since nothing it signs says when it was sent.

The secret is selected by the `agent` query parameter our registered url carries
(`reliability/engine_webhooks.agent_webhook_url`), never by a body field, and is opened
with the engine intake key (`reliability/engine_intake_keys.py`) — voice-runtime holds no
`PLATFORM_KEK`.

Light imports only (hard rule 3): stdlib, the shared signature helper, and a session.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

from apps.api.core.envelope import Envelope, KekRing
from apps.api.db.session import untenanted_session
from apps.api.reliability.engine_intake_keys import open_webhook_secret
from calevate_shared.engine_scope import SCOPE_SEPARATOR, scoped_handle, split_handle
from calevate_shared.webhook_signature import (
    signed_time_is_fresh,
    timestamped_sha256_signature_matches,
)
from engine_intake import keyable, scalar_hint
from sqlalchemy import text

#: The post-call ingest job (`apps/workers/pipeline.INGEST_JOB`).
INGEST_JOB: Final = "ingest_engine_event"
#: A person's "do not call me again" heard by the engine's own agent
#: (`apps/workers/engine_signals.ENGINE_OPT_OUT_JOB`).
ENGINE_OPT_OUT_JOB: Final = "ingest_engine_opt_out"
#: A lead taken or a conversation handed to a person by the engine's own agent
#: (`apps/workers/engine_signals.ENGINE_NOTICE_JOB`).
ENGINE_NOTICE_JOB: Final = "ingest_engine_notice"


@dataclass(frozen=True, slots=True)
class SignedEventRoute:
    #: The `data` field naming the call this event is about: the inbox and the job are
    #: keyed on it, so the unit an operator searches for is the call. None for an event
    #: that need not be about a call (a chat escalation), keyed on its event id instead.
    call_field: str | None
    #: The worker job that consumes the event.
    job: str


@dataclass(frozen=True, slots=True)
class SignedIntake:
    signature_header: str
    #: The attempt's send time; the signature covers it.
    delivered_at_header: str
    #: Equal to the body's signed `id`; read only to refuse a disagreement.
    event_id_header: str
    #: 1, 2, 3 … per attempt. Unsigned, so it is recorded and never trusted for a decision.
    attempt_header: str
    events: dict[str, SignedEventRoute]


SIGNED_INTAKES: Final[dict[str, SignedIntake]] = {
    "thinnest": SignedIntake(
        signature_header="x-thinnest-signature-v2",
        delivered_at_header="x-thinnest-delivered-at",
        event_id_header="x-thinnest-event-id",
        attempt_header="x-thinnest-attempt",
        events={
            # `call.completed` the moment a call ends; `call.analysed` once its results are
            # ready, "the same shape as Get Call" (webhooks.md:82-83).
            "call.completed": SignedEventRoute(call_field="id", job=INGEST_JOB),
            "call.analysed": SignedEventRoute(call_field="id", job=INGEST_JOB),
            # `data.phone`, `data.callId`, `data.source` ("call"), `data.optedOutAt`
            # (webhooks.md:85).
            "contact.opted_out": SignedEventRoute(call_field="callId", job=ENGINE_OPT_OUT_JOB),
            # Notices the engine's agent raises (webhooks.md:79-80); their `data` is printed only
            # as `{ … }`, so nothing in it keys the unit.
            "lead.captured": SignedEventRoute(call_field=None, job=ENGINE_NOTICE_JOB),
            "conversation.escalated": SignedEventRoute(call_field=None, job=ENGINE_NOTICE_JOB),
        },
    ),
}

AGENT_QUERY_PARAM: Final = "agent"

#: How far a signed delivery time may be from our clock, either way: the vendor's own
#: figure (webhooks.md:129-131, :144), and Stripe's default replay tolerance.
REPLAY_TOLERANCE: Final = timedelta(minutes=5)

#: Our reasons for refusing a delivery after its signature checked out.
STALE_DELIVERY: Final = "stale delivery"

#: The attempt number recorded when the header is absent or unreadable.
_FIRST_ATTEMPT: Final = 1
#: Six attempts per event plus re-sends (webhooks.md:112-117, :184-185); anything past
#: this is not a count we would store.
_MAX_ATTEMPT: Final = 1000


async def signing_secret(engine: str, engine_agent_ref: str, *, ring: KekRing) -> str | None:
    """The agent's endpoint secret, or None when no ACTIVE route holds one.

    An untenanted read of `engine_agent_routes`, which is the read its RLS exemption grants
    (`db/registry.RLS_EXEMPT_TENANT_COLUMNS`). Raises `ProblemError` when the intake key
    cannot open the envelope — the caller answers that as an outage, not a forgery.
    """
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT webhook_secret_ciphertext, webhook_secret_nonce, "
                    "webhook_secret_dek_wrapped, webhook_secret_dek_nonce, "
                    "webhook_secret_kek_version FROM engine_agent_routes "
                    "WHERE engine = :engine AND engine_agent_ref = :ref AND active "
                    "AND webhook_id IS NOT NULL"
                ),
                {"engine": engine, "ref": engine_agent_ref},
            )
        ).first()
    if row is None:
        return None
    envelope = Envelope(
        ciphertext=bytes(row[0]),
        nonce=bytes(row[1]),
        dek_wrapped=bytes(row[2]),
        dek_nonce=bytes(row[3]),
        kek_id=int(row[4]),
    )
    return open_webhook_secret(
        envelope, engine=engine, engine_agent_ref=engine_agent_ref, ring=ring
    )


def delivery_signature_matches(
    intake: SignedIntake, body: bytes, headers: Mapping[str, str], secret: str
) -> bool:
    return timestamped_sha256_signature_matches(
        body,
        headers.get(intake.signature_header),
        secret,
        signed_at=headers.get(intake.delivered_at_header),
    )


def delivery_is_fresh(intake: SignedIntake, headers: Mapping[str, str], *, now: datetime) -> bool:
    """Was this attempt sent within `REPLAY_TOLERANCE` of our clock? Ask only after the
    signature verified: the time is part of what it signed."""
    return signed_time_is_fresh(
        headers.get(intake.delivered_at_header), now=now, tolerance=REPLAY_TOLERANCE
    )


def delivery_attempt(intake: SignedIntake, headers: Mapping[str, str]) -> int:
    """The vendor's attempt counter for the forensic row, or 1 when it is unreadable."""
    raw = headers.get(intake.attempt_header) or ""
    if not raw.isascii() or not raw.isdigit() or len(raw) > len(str(_MAX_ATTEMPT)):
        return _FIRST_ATTEMPT
    value = int(raw)
    return value if 1 <= value <= _MAX_ATTEMPT else _FIRST_ATTEMPT


@dataclass(frozen=True, slots=True)
class SignedEvent:
    #: The call the event is about.
    execution_id: str
    #: The inbox unit: `<event>:<event id>`, identical on every retry and re-send.
    event_name: str
    event: str
    job: str


def keyed_event(
    intake: SignedIntake,
    payload: dict[str, Any],
    *,
    engine_agent_ref: str,
    event_id_header: str | None = None,
) -> SignedEvent | str:
    """The keyed unit of a VERIFIED, FRESH delivery, or OUR reason for ignoring it.

    The key is the event id the vendor signed into the body, so a retry after a timeout and
    a re-send from the console both collapse onto the first delivery's inbox row
    (webhooks.md:107, :133-134). A header that names a different id than the body is a
    delivery we cannot key honestly and is ignored.
    """
    if payload.get("test") is True:
        # `POST /webhooks/{id}/test` sends a sample "marked `"test": true`, with obviously
        # fake details" (webhooks.md:199-200): nothing in it is a real event.
        return "test delivery"
    event = scalar_hint(payload.get("event"))
    if event is None or event not in intake.events:
        return "event not consumed"
    route = intake.events[event]
    event_id = keyable(scalar_hint(payload.get("id")) or "")
    if event_id is None:
        return "unusable event id"
    if event_id_header is not None and event_id_header != event_id:
        return "event id mismatch"
    data = payload.get("data")
    if not isinstance(data, dict):
        return "unusable execution key"
    # An agent in a client's own workspace is held as `<id>@<org_…>` (D-693); the body names
    # the vendor's bare ids, so a call is keyed in the agent's workspace — the form every
    # other path stores it in — and the agent is compared without it.
    agent_id, workspace = split_handle(engine_agent_ref)
    if route.call_field is None:
        execution_id = keyable(event_id)
    else:
        raw_call = keyable(scalar_hint(data.get(route.call_field)) or "")
        execution_id = (
            keyable(scoped_handle(raw_call, workspace))
            if raw_call is not None and SCOPE_SEPARATOR not in raw_call
            else None
        )
    if execution_id is None:
        return "unusable execution key"
    agent = data.get("agent")
    named = scalar_hint(agent.get("id")) if isinstance(agent, dict) else None
    if named is not None and named != agent_id:
        # Signed by this agent's secret yet naming another agent: a misregistered endpoint.
        return "agent mismatch"
    event_name = keyable(f"{event}:{event_id}")
    if event_name is None:
        return "unusable execution key"
    return SignedEvent(execution_id=execution_id, event_name=event_name, event=event, job=route.job)


__all__ = [
    "AGENT_QUERY_PARAM",
    "ENGINE_NOTICE_JOB",
    "ENGINE_OPT_OUT_JOB",
    "INGEST_JOB",
    "REPLAY_TOLERANCE",
    "SIGNED_INTAKES",
    "STALE_DELIVERY",
    "SignedEvent",
    "SignedEventRoute",
    "SignedIntake",
    "delivery_attempt",
    "delivery_is_fresh",
    "delivery_signature_matches",
    "keyed_event",
    "signing_secret",
]
