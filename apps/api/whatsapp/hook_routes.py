"""Meta's WhatsApp webhook receiver: one callback for every client's WABA (D-784).

`GET /hooks/v1/meta/whatsapp` answers Meta's subscription handshake; `POST` takes the
deliveries. The order is `ingest/routes.meta_leadgen`'s, and for its reasons: bound the body,
verify `X-Hub-Signature-256` over the RAW bytes with Calevate's app secret, only then parse.
The signature helpers are that module's (`ingest/meta.py`), so Meta's two receivers verify
one way.

FAST ACK, WORK LATER. Each event is claimed once in `webhook_inbox_events` (Meta retries for
up to 7 days and asks for deduplication) and handed to the `ingest_whatsapp_event` job; the
handler resolves no tenant and writes nothing else. A queue we cannot reach answers 503 so
Meta's own retries carry the delivery; a claim left `processing` is re-claimed once its
lease lapses.

Hard rule 6: no number, no message body and no template text reach a log line here.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated, Final

from fastapi import APIRouter, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict

from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.queue import enqueue
from apps.api.core.settings import get_settings
from apps.api.db.session import untenanted_session
from apps.api.ingest import meta
from apps.api.reliability.service import claim_inbox_event, mark_inbox_enqueued
from apps.api.whatsapp.webhooks import MAX_EVENTS_PER_DELIVERY, extract_events

log = get_logger(__name__)

router = APIRouter(prefix="/hooks/v1/meta", tags=["whatsapp"])

INGEST_JOB: Final = "ingest_whatsapp_event"
INBOX_PROVIDER: Final = "meta_whatsapp"
#: Activity pings are coalesced per WABA per minute: they only move "last heard from Meta".
ACTIVITY_BUCKET_S: Final = 60


class WhatsAppHookAckOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    received: int
    accepted: int
    duplicate: int


@router.get(
    "/whatsapp",
    response_class=PlainTextResponse,
    summary="Meta's webhook subscription handshake for clients' WhatsApp accounts",
)
async def whatsapp_verify(
    hub_mode: Annotated[str | None, Query(alias="hub.mode", max_length=32)] = None,
    hub_verify_token: Annotated[str | None, Query(alias="hub.verify_token", max_length=512)] = None,
    hub_challenge: Annotated[str | None, Query(alias="hub.challenge", max_length=1024)] = None,
) -> PlainTextResponse:
    expected = get_settings().whatsapp_webhook_verify_token or ""
    if not expected or not meta.handshake_matches(
        mode=hub_mode, token=hub_verify_token, expected=expected
    ):
        log.warning("whatsapp_handshake_rejected")
        raise ProblemError(
            kind="permission",
            code="whatsapp_handshake_rejected",
            title="Verification failed",
            detail="The verify token does not match.",
            status=403,
        )
    if not hub_challenge or len(hub_challenge) > meta.MAX_CHALLENGE_LEN:
        raise ProblemError(
            kind="validation",
            code="whatsapp_challenge_missing",
            title="No challenge",
            detail="The handshake carried no challenge to echo.",
        )
    return PlainTextResponse(hub_challenge)


@router.post(
    "/whatsapp",
    response_model=WhatsAppHookAckOut,
    summary="Clients' WhatsApp account events from Meta, X-Hub-Signature-256 verified",
)
async def whatsapp_events(request: Request) -> WhatsAppHookAckOut:
    raw = await meta.read_bounded_body(request)
    if raw is None:
        raise ProblemError(
            kind="validation",
            code="payload_too_large",
            title="Notification too large",
            detail="The notification body exceeds the accepted size.",
            status=413,
        )
    secret = get_settings().meta_app_secret or ""
    if not meta.verify_signature(
        app_secret=secret, body=raw, header=request.headers.get(meta.SIGNATURE_HEADER)
    ):
        alert("ROUTE_HANDLER", "whatsapp_webhook_signature_rejected")
        raise ProblemError.unauthorized("This notification was not signed by Meta.")
    try:
        payload = json.loads(raw)
    except (ValueError, RecursionError) as exc:
        raise ProblemError(
            kind="validation",
            code="whatsapp_hook_not_json",
            title="Notification is not JSON",
            detail="Only JSON notifications are accepted here.",
        ) from exc

    events = extract_events(payload)[:MAX_EVENTS_PER_DELIVERY]
    accepted = duplicate = 0
    bucket = int(datetime.now(UTC).timestamp()) // ACTIVITY_BUCKET_S
    try:
        for event in events:
            if event.kind == "activity":
                await enqueue(
                    INGEST_JOB,
                    {"event": event.payload()},
                    job_id=f"wa-activity:{event.waba_id}:{bucket}",
                )
                accepted += 1
                continue
            key = event.key()
            # The claim commits BEFORE the job is queued: a worker that ran first would
            # otherwise mark a row it cannot yet see, and the row would then commit as
            # `processing` and be re-marked `enqueued` forever after the work was done.
            async with untenanted_session() as session:
                claim = await claim_inbox_event(
                    session,
                    provider=INBOX_PROVIDER,
                    event_key=key,
                    payload_hash=key,
                    event_name=event.change,
                )
            if claim.state == "duplicate":
                duplicate += 1
                continue
            await enqueue(INGEST_JOB, {"event": event.payload(), "inbox_id": str(claim.row_id)})
            # Guarded on `processing`, so it is a no-op when the worker already finished.
            async with untenanted_session() as session:
                await mark_inbox_enqueued(session, row_id=claim.row_id)
            accepted += 1
    except ProblemError:
        raise
    except Exception as exc:
        # The queue (Redis) or the inbox could not take it. Not a verdict on the delivery:
        # the 503 makes Meta redeliver, and a claim left `processing` is re-claimed by
        # `claim_inbox_event` once its lease lapses.
        log.warning("whatsapp_hook_deferred", extra={"error": type(exc).__name__})
        raise ProblemError(
            kind="transient",
            code="whatsapp_hook_deferred",
            title="Could not queue this notification",
            detail="The notification could not be queued; Meta will redeliver it.",
            remediation="No action is needed.",
        ) from exc
    log.info(
        "whatsapp_hook_received",
        extra={"received": len(events), "accepted": accepted, "duplicate": duplicate},
    )
    return WhatsAppHookAckOut(received=len(events), accepted=accepted, duplicate=duplicate)


__all__ = ["INBOX_PROVIDER", "INGEST_JOB", "router"]
