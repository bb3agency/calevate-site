"""Clerk → our Postgres mirror (D-37).

The decision this implements, stated plainly: **Clerk authenticates; it does not own
our data model.** Every user and organization is mirrored into our tables so
`organizations`/`users` stay OUR system of record and RLS keys off OUR `tenant_id`. If
Clerk is ever replaced, the tenancy model does not move — only the token verification
does.

Clerk signs webhooks with **Svix** (an actual HMAC signature, unlike the engine's
unsigned callbacks — D-31), so authenticity here is real cryptography rather than a
source-IP hint. The verification is implemented directly rather than pulling in the
`svix` SDK: it is thirty lines of HMAC over a documented payload format, and the
alternative is a dependency in the auth path.

Signature scheme (svix-webhooks docs):
    signed_content = f"{svix_id}.{svix_timestamp}.{body}"
    expected       = base64(HMAC_SHA256(secret_bytes, signed_content))
    svix-signature = "v1,<sig> v1,<other-sig>"   # space-separated, versioned
`secret` arrives as `whsec_<base64>`; the bytes after the prefix are the key.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from fastapi import APIRouter, Request
from sqlalchemy import text

from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import untenanted_session
from apps.api.reliability.service import (
    body_hash,
    claim_inbox_event,
    mark_inbox_failed,
    mark_inbox_processed,
)

log = get_logger(__name__)

router = APIRouter(prefix="/hooks/v1", tags=["clerk-webhooks"])

# Reject anything older than this even if the signature is valid — a captured request
# must not be replayable forever.
MAX_SKEW_S = 5 * 60


def verify_svix(*, secret: str, headers: dict[str, str], body: bytes) -> bool:
    svix_id = headers.get("svix-id")
    svix_timestamp = headers.get("svix-timestamp")
    svix_signature = headers.get("svix-signature")
    if not (svix_id and svix_timestamp and svix_signature):
        return False

    try:
        sent_at = int(svix_timestamp)
    except ValueError:
        return False
    if abs(time.time() - sent_at) > MAX_SKEW_S:
        return False

    key = base64.b64decode(secret.removeprefix("whsec_"))
    # Assemble the signed content as BYTES. Decoding the body to build a str first
    # raises on anything that is not UTF-8, and an unverifiable request must come back
    # as a refusal, never as an unhandled exception on an unauthenticated route.
    signed = f"{svix_id}.{svix_timestamp}.".encode() + body
    expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()

    # The header carries every currently-valid signature (secret rotation), so any
    # match is a pass — compared in constant time.
    for candidate in svix_signature.split():
        _, _, value = candidate.partition(",")
        if hmac.compare_digest(value, expected):
            return True
    return False


async def _mirror_user(payload: dict[str, Any], deleted: bool) -> str:
    clerk_id = payload.get("id")
    if not isinstance(clerk_id, str):
        return "ignored"

    if deleted:
        # Soft: `deactivated_at` is what the auth guard re-checks on every request, so
        # this takes effect on the very next call. A hard delete would orphan
        # memberships and audit rows that must survive (hard rule 4).
        async with untenanted_session() as session:
            await session.execute(
                text(
                    "UPDATE users SET deactivated_at = now(), updated_at = now() "
                    "WHERE clerk_user_id = :cid AND deactivated_at IS NULL"
                ),
                {"cid": clerk_id},
            )
        return "deactivated"

    emails = payload.get("email_addresses") or []
    primary_id = payload.get("primary_email_address_id")
    email = next(
        (e.get("email_address") for e in emails if e.get("id") == primary_id),
        next((e.get("email_address") for e in emails), None),
    )
    if not email:
        return "ignored"
    name = " ".join(
        part for part in (payload.get("first_name"), payload.get("last_name")) if part
    ).strip()

    async with untenanted_session() as session:
        # `deactivated_at` is deliberately NOT in the SET list. Svix does not guarantee
        # ordering, so a `user.updated` can land after the `user.deleted` for the same
        # id — and clearing the flag there would restore a revoked account's access to
        # every tenant it belonged to, because the auth guard re-reads exactly this
        # column on every request. Clerk never reuses a user id, so a later event for a
        # deleted one is always stale: the mirror reflects the deletion, it does not
        # get to overrule it. Nothing else in the codebase clears this column, so
        # reinstating an account would be a deliberate admin action, not a side effect
        # of whatever order the webhooks happened to arrive in.
        await session.execute(
            text(
                "INSERT INTO users (id, clerk_user_id, email, name, created_at, updated_at) "
                "VALUES (:id, :cid, :email, :name, now(), now()) "
                "ON CONFLICT (clerk_user_id) DO UPDATE SET email = EXCLUDED.email, "
                "name = COALESCE(EXCLUDED.name, users.name), updated_at = now()"
            ),
            {"id": uuid7(), "cid": clerk_id, "email": email, "name": name or None},
        )
    return "mirrored"


@router.post(
    "/clerk",
    status_code=202,
    summary="Clerk user/organization mirror — Svix-signed (D-37: our DB is the record)",
)
async def clerk_webhook(request: Request) -> dict[str, str]:
    settings = get_settings()
    secret = settings.clerk_webhook_secret
    raw = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}

    if not secret:
        # Fail CLOSED. An unverifiable identity feed is worse than no feed: it would
        # let anyone create users in the table RLS keys its membership off.
        alert("ROUTE_HANDLER", "clerk_webhook_unconfigured")
        raise ProblemError(
            kind="dependency",
            code="webhook_not_configured",
            title="Webhook is not configured",
            detail="This deployment cannot verify identity webhooks.",
        )
    if not verify_svix(secret=secret, headers=headers, body=raw):
        alert("ROUTE_HANDLER", "clerk_webhook_bad_signature")
        raise ProblemError.unauthorized("Signature verification failed.")

    try:
        envelope = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        envelope = {}
    event_type = str(envelope.get("type") or "")
    payload = envelope.get("data") or {}
    if not isinstance(payload, dict):
        payload = {}

    # Same durable dedupe as the engine receiver: Clerk retries on non-2xx, so an event
    # can legitimately arrive several times.
    event_key = headers.get("svix-id") or body_hash(envelope)
    async with untenanted_session() as session:
        claim = await claim_inbox_event(
            session,
            provider="clerk",
            event_key=event_key,
            payload_hash=body_hash(envelope),
            event_name=event_type,
        )
        if claim.state == "duplicate":
            return {"status": "duplicate"}

    try:
        if event_type in ("user.created", "user.updated"):
            result = await _mirror_user(payload, deleted=False)
        elif event_type == "user.deleted":
            result = await _mirror_user(payload, deleted=True)
        else:
            # Organizations are created by OUR onboarding wizard, not by Clerk (D-10:
            # flat tenancy, admin-driven onboarding). Acknowledge and ignore rather
            # than invent a tenant from an upstream event.
            result = "ignored"
    except Exception as exc:
        # The claim was taken BEFORE the work, so a row left `processing` answers every
        # subsequent Clerk retry with "duplicate" and the event is lost for good — for
        # `user.deleted` that is a revoked account that stays live in our mirror.
        # Marking it failed makes the key re-claimable (reliability §4). The exception
        # type only: an error string can carry payload content, and this row is
        # persisted (hard rule 6).
        async with untenanted_session() as session:
            await mark_inbox_failed(session, row_id=claim.row_id, error=type(exc).__name__)
        alert("ROUTE_HANDLER", "clerk_mirror_failed", event_type=event_type)
        raise

    async with untenanted_session() as session:
        await mark_inbox_processed(session, row_id=claim.row_id)
    log.info("clerk_event", extra={"event_type": event_type, "result": result})
    return {"status": result, "event": event_type}


__all__ = ["MAX_SKEW_S", "router", "verify_svix"]
