"""The "save our number" WhatsApp (founder, 11 Oct 2026; D-746).

When a caller books an appointment or a call-back, Calevate can send them one WhatsApp:
"Reminders from <business> come from <the number our agent calls from>. Please save it." so
they pick up the reminder call instead of ignoring an unknown number. A per-client switch,
off by default.

WHO SENDS IT, AND THEREFORE WHAT IT SAYS. It goes from Calevate's own WhatsApp business
account (the hot-lead alert's sender, `workers/whatsapp.py`), never from the calling number,
so the message names the calling number in full. The in-call WhatsApp action is the
client's own provider and account; that is a client feature they configure, not ours to
send from.

WHAT MUST HOLD BEFORE IT IS SENT, in the worker (`workers/forwarding.send_save_number`):
the switch is on; this caller of this client has never been sent one (`save_number_messages`
is unique on a keyed hash of the number, so "once ever" is the database's answer); the dial
gate's do-not-call, halt and account checks (`check_dispatch`, as the WhatsApp
follow-up asks them); and the caller's own messaging opt-in
(`compliance.consent.read_messaging_consent`). A caller who booked has not thereby opted in
to WhatsApp, so in practice it reaches only callers whose opt-in is on file: that is the
consent rule working, not a gap to code around.

WHO PAYS. We do. It is our account and our template, so it is metered as `whatsapp_msg`,
absorbed, at the operator-attested per-message price (`Settings.whatsapp_message_inr`), the
way Calevate's other sends are ours. The client pays nothing for it.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings, resolve_hmac_key
from apps.api.reliability.service import enqueue_outbox_once

SEND_JOB: Final = "send_save_number_message"

#: Pre-approved utility templates, one per language; a template name only means something
#: beside the body approved for it, so they are constants. Body (all three carry the same two
#: variables, the business name and the calling number):
#:   en "Reminders from {{1}} come from {{2}}. Please save this number."
#:   hi "{{1}} के reminder {{2}} से आएंगे। कृपया यह नंबर save कर लें।"
#:   te "{{1}} నుండి reminders {{2}} నుండి వస్తాయి. దయచేసి ఈ నంబర్‌ను save చేసుకోండి."
TEMPLATE: Final = "calevate_save_our_number_v1"
LOCALES: Final = ("en", "hi", "te")

_READ_SQL: Final = "SELECT save_number_message_enabled FROM organizations"
_LOCK_SQL: Final = "SELECT save_number_message_enabled FROM organizations FOR UPDATE"
_WRITE_SQL: Final = (
    "UPDATE organizations SET save_number_message_enabled = :enabled, updated_at = now()"
)


async def read_switch(session: AsyncSession) -> bool:
    """RLS scopes it to the session's account (`organizations` matches on `id`)."""
    row = (await session.execute(text(_READ_SQL))).first()
    if row is None:
        raise ProblemError.not_found("Organization")
    return bool(row[0])


async def write_switch(session: AsyncSession, *, enabled: bool) -> bool:
    """Set the switch; True when it moved. The row is locked first (BACKEND-PATTERNS §5)."""
    row = (await session.execute(text(_LOCK_SQL))).first()
    if row is None:
        raise ProblemError.not_found("Organization")
    await session.execute(text(_WRITE_SQL), {"enabled": enabled})
    return bool(row[0]) != enabled


def caller_ref(tenant_id: UUID, phone_e164: str) -> str:
    """A keyed hash of one caller of one client: the number is never stored. Keyed with
    the idempotency-scope secret, which never rotates, so the same caller always maps to the
    same row (an unkeyed hash of an Indian number is reversible by enumeration)."""
    settings = get_settings()
    material = resolve_hmac_key(
        settings.idempotency_scope_secret,
        env_var="IDEMPOTENCY_SCOPE_SECRET",
        purpose="save-our-number caller references",
        code="idempotency_not_configured",
        title="Idempotent requests are not configured",
        local_fallback=f"calevate-local-dev-idempotency-scope-key:{settings.app_env}",
        app_env=settings.app_env,
    )
    message = f"save-number:{tenant_id}:{phone_e164}".encode()
    return hmac.new(material, message, hashlib.sha256).hexdigest()


def locale_for(language: str | None) -> str:
    """The caller's language, from the call's reading (`calls.summary_language`, BCP-47,
    NULL on an English call)."""
    head = (language or "").split("-")[0].lower()
    return head if head in LOCALES else "en"


async def queue_if_booked(session: AsyncSession, *, tenant_id: UUID, call_id: UUID) -> bool:
    """Queue the message for a completed call in which a call-back or appointment was
    booked, when the switch is on. Once per call (the outbox key); once per caller is the
    worker's, against `save_number_messages`. Called in the pipeline's last transaction."""
    row = (
        await session.execute(
            text(
                "SELECT o.save_number_message_enabled, c.forwarding_test_id IS NULL, "
                "(c.outcome_tag = 'call_back_booked' OR EXISTS (SELECT 1 FROM "
                "action_invocations i WHERE i.call_ref = c.engine_call_id "
                "AND i.status = 'booked')) "
                "FROM calls c JOIN organizations o ON o.id = c.tenant_id WHERE c.id = :cid"
            ),
            {"cid": call_id},
        )
    ).first()
    if row is None or not row[0] or not row[1] or not row[2]:
        return False
    queued = await enqueue_outbox_once(
        session,
        job=SEND_JOB,
        payload={"tenant_id": str(tenant_id), "call_id": str(call_id)},
        dedupe_key=f"save-number:{call_id}",
    )
    return queued is not None


__all__ = [
    "LOCALES",
    "SEND_JOB",
    "TEMPLATE",
    "caller_ref",
    "locale_for",
    "queue_if_booked",
    "read_switch",
    "write_switch",
]
