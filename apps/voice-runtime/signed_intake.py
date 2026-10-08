"""Signed engine deliveries: verify per-agent HMAC, key the unit, seal the body (D-678).

`engine_intake.verify_source` decides admission before a byte of body is read, which is
right for an engine authenticated by where it calls from and impossible for one that signs
the body. ThinnestAI signs each delivery with the secret of the agent's own endpoint:
`x-thinnest-signature: sha256=<HMAC-SHA256 of the raw body>` (`thinnest-findings/mirror/
pages/api-reference/webhooks.md:36-40`, `mcp/own-database.md:74-86`). So for an engine in
`SIGNED_INTAKES` the receiver reads the bounded body first and admits nothing until the
signature over those exact bytes verifies.

The secret is selected by the `agent` query parameter our registered url carries
(`reliability/engine_webhooks.agent_webhook_url`), never by a body field, and is opened
with the engine intake key (`reliability/engine_intake_keys.py`) — voice-runtime holds no
`PLATFORM_KEK`.

The signed body carries its send time, `{event, sentAt, data}` (snapshots/2026-10-07/pages/
api-reference/webhooks/create-webhook.md:159-165), so a delivery outside `REPLAY_TOLERANCE`
is ignored; inside it, the inbox dedupe on `(id, event, attempt, analysedAt|endedAt)` makes
a replay a no-op (THINNEST-INTEGRATION §3.2).

Light imports only (hard rule 3): stdlib, the shared signature helper, and a session.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from apps.api.core.envelope import Envelope, KekRing
from apps.api.db.session import untenanted_session
from apps.api.reliability.engine_intake_keys import open_webhook_secret
from calevate_shared.engine_scope import SCOPE_SEPARATOR, scoped_handle, split_handle
from calevate_shared.webhook_signature import sha256_signature_matches
from engine_intake import keyable, scalar_hint
from sqlalchemy import text


@dataclass(frozen=True, slots=True)
class SignedIntake:
    #: The header carrying `sha256=<hex>`.
    signature_header: str
    #: Event name -> the body field that stamps this delivery of it. One event per try
    #: (get-call.md:71-76), so the stamp is what separates two deliveries of one event.
    events: dict[str, str]


SIGNED_INTAKES: Final[dict[str, SignedIntake]] = {
    "thinnest": SignedIntake(
        signature_header="x-thinnest-signature",
        # `call.completed` "the moment it ends"; `call.analysed` once summary and fields
        # are written (webhooks.md:73-74, get-call.md:54-58).
        events={"call.completed": "endedAt", "call.analysed": "analysedAt"},
    ),
}

AGENT_QUERY_PARAM: Final = "agent"
_NO_STAMP: Final = "-"


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


def delivery_signature_matches(body: bytes, header: str | None, secret: str) -> bool:
    return sha256_signature_matches(body, header, secret)


@dataclass(frozen=True, slots=True)
class SignedEvent:
    execution_id: str
    #: The inbox unit: `<event>:<attempt>:<stamp>`.
    event_name: str
    event: str


#: How far a signed send time may be from our clock, either way. Five minutes is Stripe's
#: default webhook tolerance (stripe.com/docs/webhooks, "Prevent replay attacks"): wide
#: enough for clock skew and a slow hop, narrow enough that a captured body is useless soon.
REPLAY_TOLERANCE: Final = timedelta(minutes=5)

#: Our reason for ignoring a delivery outside `REPLAY_TOLERANCE`.
STALE_DELIVERY: Final = "stale delivery"


def _sent_recently(sent_at: Any, now: datetime) -> bool:
    """Is a delivery's `sentAt` within the tolerance? Absent counts as yes (see
    `keyed_event`); present but unreadable as no, since the vendor signed what it sent."""
    if sent_at is None:
        return True
    if not isinstance(sent_at, str):
        return False
    try:
        sent = datetime.fromisoformat(sent_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if sent.tzinfo is None:
        return False
    return abs(now - sent) <= REPLAY_TOLERANCE


def keyed_event(
    intake: SignedIntake,
    payload: dict[str, Any],
    *,
    engine_agent_ref: str,
    now: datetime | None = None,
) -> SignedEvent | str:
    """The keyed unit of a VERIFIED delivery, or OUR reason for ignoring it.

    A delivery whose signed `sentAt` is more than `REPLAY_TOLERANCE` from our clock, either
    way, is ignored as `stale delivery`: ThinnestAI makes ONE attempt per event and never
    redelivers (snapshots/2026-10-07/pages/api-reference/webhooks/create-webhook.md:
    159-165), so a genuine delivery is seconds old and an old one is a replay. A body with
    no `sentAt` is still keyed, and the inbox dedupe stays the replay guard for it.

    `attempt` and the stamp may be absent — the `call.completed` body is documented only as
    "outcome and duration" (webhooks.md:74), UNVERIFIED beyond that — and then read as a
    fixed placeholder, so an id-bearing delivery is still keyed rather than dropped.
    """
    event = scalar_hint(payload.get("event"))
    if event is None or event not in intake.events:
        return "event not consumed"
    if not _sent_recently(payload.get("sentAt"), now or datetime.now(UTC)):
        return STALE_DELIVERY
    data = payload.get("data")
    if not isinstance(data, dict):
        return "unusable execution key"
    # An agent in an engine sub-account is held as `<id>@<workspace>` (D-687); the body names
    # the bare vendor ids, so the call is scoped to the agent's workspace and the agent is
    # compared without it.
    agent_id, workspace = split_handle(engine_agent_ref)
    raw_call = keyable(scalar_hint(data.get("id")) or "")
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
    attempt = data.get("attempt")
    attempt_part = (
        str(attempt) if isinstance(attempt, int) and not isinstance(attempt, bool) else _NO_STAMP
    )
    stamp = keyable(scalar_hint(data.get(intake.events[event])) or _NO_STAMP) or _NO_STAMP
    event_name = keyable(f"{event}:{attempt_part}:{stamp}")
    if event_name is None:
        return "unusable execution key"
    return SignedEvent(execution_id=execution_id, event_name=event_name, event=event)


__all__ = [
    "AGENT_QUERY_PARAM",
    "REPLAY_TOLERANCE",
    "SIGNED_INTAKES",
    "STALE_DELIVERY",
    "SignedEvent",
    "SignedIntake",
    "delivery_signature_matches",
    "keyed_event",
    "signing_secret",
]
