"""Notification delivery (post-call pipeline step 5, FLOWS §6).

Email first, WhatsApp beside it — that ORDERING is from ROADMAP M1 and it is a
deliberate scope cut, not an oversight: WhatsApp needs a template approval cycle that
client #1 does not have to wait for. Email is therefore the channel of record and this
job owns it; the WhatsApp leg is queued from here (`whatsapp.enqueue_hot_lead_whatsapp`)
and delivered by its OWN job, so the two cannot short-circuit each other's dedupe or
each other's retry ladder. Until a BSP is chosen `whatsapp_enabled` is off and that
enqueue is a no-op — the wiring exists so that switching the channel on is the whole
change, rather than a missing call nobody discovers until the checklist is finished.

Both channels write `lead_events` rows of `type = 'notification'` — the type column is
a fixed CHECK enum with no per-channel member — so `payload->>'channel'` is the
discriminator, and EVERY query on either side is scoped by it. A query that is not is
a channel answering for the other one.

Every notification arrives here through the OUTBOX, so this function may be retried
with the same payload at any time. It therefore has to be safe to run twice — the
dedupe key is the lead event row it writes, and that row is a DELIVERED notification,
never merely an attempted one (see `_already_delivered`).

**A send that fails is retried, and an exhausted ladder is alerted.** This job used to
record `delivered: false`, return `"queued_no_channel"` and raise nothing: no ladder
ran, no operator heard, and a hot lead the client was never told about was
indistinguishable from one that arrived. That is the exact failure this notification
exists to prevent, so silence is the one outcome that is not allowed. The signal is
`arq.Retry` — arq 0.28 retries a job for `Retry`, `RetryJob` or `CancelledError` and
NOTHING else, so a plain raise here would be terminal on the first attempt and
`max_tries` decorative (`apps/workers/outbound_webhooks.py` documents the mechanism).

Not every failure earns a retry, though. A transport that could not deliver is a blip
worth another go; a tenant with no billing email is a DATA fix — the same row will be
just as empty in two minutes — so that one alerts immediately instead of burning the
ladder to reach the same verdict.

Hard rule 6 applies with full force: a notification is the easiest place to
accidentally put a phone number into a log line or a third-party API. The alerts below
carry ids, never addresses; and the BODY keeps the caller's number masked and the call
summary redacted even though D-436 unmasked both classes on the dashboard — `_compose`
carries that decision and the reason it is not an inconsistency.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import UUID

from arq import Retry
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of
from apps.api.db.session import tenant_session
from apps.workers.auth_email import CONSOLE_BASE
from apps.workers.email_render import from_text
from apps.workers.redaction import redact
from apps.workers.transport import get_transport
from apps.workers.whatsapp import enqueue_hot_lead_whatsapp

log = get_logger(__name__)

HOT_LEAD_SUBJECT = "Hot lead from your AI receptionist"

# The channel discriminator written into every `lead_events.notification` row this
# module creates, and the predicate every query here is scoped by.
#
# `lead_events.type` is a fixed CHECK enum (`crm/models.py: LEAD_EVENT_TYPES`) with no
# per-channel member, so both notification channels write `type = 'notification'` and
# the channel lives in the payload — `crm/service._project_event` already reads
# `payload->>'channel'` to decide whether to render "sent by email" or "sent by
# WhatsApp", so this is the discriminator the whole system already agrees on, not a new
# convention invented here. Its value has been on every row this module ever wrote
# (commit dddfc29 introduced `_record_attempt` with it), so scoping the queries by it
# cannot orphan an existing row.
CHANNEL = "email"

# Seconds to wait before each retry, indexed by the attempt that just failed. One entry
# shorter than the budget, because the last attempt has nothing after it. Same shape
# and the same reasoning as `outbound_webhooks.RETRY_BACKOFF_S`, but tighter: this is
# the 2-minute hot-lead SLO, so the ladder has to finish inside a useful window rather
# than pace itself for a receiver that may be down for a while.
RETRY_BACKOFF_S: tuple[float, ...] = (15.0, 45.0)


def _retry_after(attempt: int) -> float:
    index = min(attempt, len(RETRY_BACKOFF_S)) - 1
    return RETRY_BACKOFF_S[max(index, 0)]


async def notify_hot_lead(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    tenant_id = UUID(str(payload["tenant_id"]))
    lead_id = UUID(str(payload["lead_id"]))
    call_id = UUID(str(payload["call_id"]))
    triggers: list[str] = list(payload.get("triggers") or [])
    attempt = int(ctx.get("job_try", 1))

    async with tenant_session(tenant_id) as session:
        if await _already_delivered(session, lead_id=lead_id, call_id=call_id):
            return "duplicate"

        row = (
            await session.execute(
                text(
                    "SELECT l.name, l.phone_e164, l.status, c.summary, o.billing_email, o.slug "
                    "FROM leads l JOIN calls c ON c.id = :cid "
                    "JOIN organizations o ON o.id = l.tenant_id WHERE l.id = :lid"
                ),
                {"lid": lead_id, "cid": call_id},
            )
        ).first()
        if row is None:
            return "lead_missing"
        # `slug` rides along on the SELECT that was already joining `organizations` for
        # the address — the deep link in the body needs it and a second round trip to
        # fetch one column would be one more thing to fail inside the 2-minute SLO.
        name, phone, status, summary, billing_email, slug = row

        if billing_email:
            body = _compose(name, phone, status, summary, triggers, slug=slug, lead_id=lead_id)
            # INSIDE the transaction, DELIBERATELY, and the finding that produced the
            # `to_thread` above recommended moving it out as well. It is not moved, and
            # the reason is the atomicity the next block argues for at length: the
            # delivery record and the WhatsApp enqueue must land together or a crash
            # leaves an email recorded and its twin lost, and the dedupe check at the top
            # of this transaction is what stops two concurrent runs both sending.
            # Splitting the session in three would trade a real invariant for a smaller
            # one.
            #
            # What the open transaction actually costs here is ONE pooled connection for
            # the length of the send — the pool is 16 for ten concurrent jobs, and the
            # statements above are plain SELECTs, so no row lock is held while we wait.
            # What it used to cost was the event loop, which is every job in the process.
            # Those are not the same order of problem, and `to_thread` closes the one
            # that is.
            delivered = await _send_email(billing_email, HOT_LEAD_SUBJECT, body)
        else:
            # Nothing to attempt: `_send_email` would only report the same thing back.
            delivered = False

        # Recorded whatever happened, and recorded ONCE per lead+call however many
        # attempts it takes — the timeline shows the outcome, not the ladder.
        await _record_attempt(
            session,
            tenant_id=tenant_id,
            lead_id=lead_id,
            call_id=call_id,
            delivered=delivered,
            attempts=attempt,
            triggers=triggers,
        )

        # The second channel of FLOWS §6 ("WhatsApp+email to owner within 2 min"),
        # promised in the SAME transaction as the delivery record above — the outbox
        # doctrine of BACKEND-PATTERNS §4, so a crash cannot leave an email recorded
        # and its WhatsApp twin lost. A no-op returning False while `whatsapp_enabled`
        # is off, which is why it is safe to call here before a BSP exists.
        #
        # UNCONDITIONAL on `delivered`, and that is the design decision: WhatsApp is
        # not a fallback for a broken mailer. Queueing it only when the email failed
        # would make the nudge appear on exactly the leads whose client is already
        # being alerted about, and never on the ordinary ones it was asked for;
        # queueing it only when the email succeeded would let one dead transport
        # silence both channels at once. Each channel therefore answers for itself —
        # its own record, its own ladder, its own alert — and a lead is "notified" only
        # per channel: a landed WhatsApp nudge does not make a lost email acceptable,
        # because the client asked for the ping AND the inbox trail.
        whatsapp_queued = await enqueue_hot_lead_whatsapp(
            session,
            tenant_id=tenant_id,
            lead_id=lead_id,
            call_id=call_id,
            triggers=triggers,
        )

    if whatsapp_queued:
        # Ids only (hard rule 6) — this path never touches the destination number; the
        # WhatsApp job resolves its own recipient and logs none of it either. Logged
        # because "I got no WhatsApp" and "we never queued one" have different owners
        # and are otherwise indistinguishable from outside.
        log.info("hot_lead_whatsapp_queued", extra={"lead_id": str(lead_id)})

    if delivered:
        # Ids only (hard rule 6). `attempts` is here because "delivered on the third
        # try" and "delivered immediately" are the same outcome and very different
        # health signals for a 2-minute SLO.
        log.info("hot_lead_notified", extra={"lead_id": str(lead_id), "attempts": attempt})
        return "sent"

    if not billing_email:
        # A data fix, not a blip. Retrying cannot conjure an address, so the ladder is
        # skipped and a human is told straight away — the lead is un-notified either
        # way, and only a person can close that.
        alert(
            "WORKER_TERMINAL",
            "hot_lead_no_channel",
            detail="tenant has no billing email; hot lead cannot be delivered",
            tenant_id=str(tenant_id),
            lead_id=str(lead_id),
        )
        return "no_channel"

    if attempt < WORKER_MAX_TRIES:
        # The one exception type arq treats as "not finished". The attempt row is
        # already committed — the session closed above — so the retry starts from a
        # recorded attempt rather than from nothing.
        raise Retry(defer=_retry_after(attempt))

    alert(
        "WORKER_DELIVERY",
        "hot_lead_notification_exhausted",
        detail=f"hot-lead email undelivered after {attempt} attempt(s)",
        tenant_id=str(tenant_id),
        lead_id=str(lead_id),
    )
    return f"exhausted after {attempt}"


async def _already_delivered(session: AsyncSession, *, lead_id: UUID, call_id: UUID) -> bool:
    """Has the EMAIL for this lead+call actually REACHED someone?

    A recorded attempt is not an answer to that question. Treating one as a duplicate
    is what would make the retry ladder decorative: the second attempt would find the
    `delivered: false` row it wrote itself, report `duplicate`, and leave a timeline
    that claims the client was told.

    Scoped to `channel = 'email'`, the mirror of `whatsapp._already_delivered`'s scope,
    so the two channels can never answer for each other. Without it a delivered
    WhatsApp row on the same lead+call makes this job return `duplicate` having sent
    nothing — a client with a working WhatsApp alert and a silently dead mailer, and a
    timeline that reads as if both landed.
    """
    row = (
        await session.execute(
            text(
                "SELECT 1 FROM lead_events WHERE lead_id = :lid AND type = 'notification' "
                "AND payload->>'channel' = :channel AND payload->>'call_id' = :cid "
                "AND payload->>'delivered' = 'true' LIMIT 1"
            ),
            {"lid": lead_id, "cid": str(call_id), "channel": CHANNEL},
        )
    ).first()
    return row is not None


async def _record_attempt(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    lead_id: UUID,
    call_id: UUID,
    delivered: bool,
    attempts: int,
    triggers: list[str],
) -> None:
    """One timeline row per (lead, call, channel), updated in place as the ladder walks.

    Update-then-insert rather than `ON CONFLICT`, because `lead_events` has no unique
    key for this shape (same pattern as `pipeline._persist_extraction` and
    `whatsapp._record_attempt`). `lead_events` is a timeline, not one of the
    append-only ledgers of hard rule 4, so flipping `delivered` to true when a retry
    finally lands is the honest record — and a notification that never landed stays
    visible as one instead of disappearing.

    Note the `channel` predicate on the UPDATE, the mirror of the one on
    `whatsapp._record_attempt`: without it this rewrites the WhatsApp path's row for
    the same call — same lead, same `call_id`, different channel — so the client's
    timeline would show one channel's outcome twice and lose the other's entirely.
    The two spellings are kept deliberately symmetric rather than factored into a
    shared helper: this repo already writes this update-then-insert inline in three
    places, and a shared "notification record" module would have to live outside both
    modules to avoid an import cycle with the enqueue call in `notify_hot_lead`.
    """
    body = _json(
        {
            "call_id": str(call_id),
            "channel": CHANNEL,
            "delivered": delivered,
            "attempts": attempts,
            "triggers": triggers,
        }
    )
    updated = await session.execute(
        text(
            "UPDATE lead_events SET payload = CAST(:payload AS jsonb), updated_at = now() "
            "WHERE lead_id = :lid AND type = 'notification' "
            "AND payload->>'channel' = :channel AND payload->>'call_id' = :cid"
        ),
        {"payload": body, "lid": lead_id, "cid": str(call_id), "channel": CHANNEL},
    )
    if rowcount_of(updated) == 0:
        await session.execute(
            text(
                "INSERT INTO lead_events (id, tenant_id, lead_id, type, payload, actor, "
                "created_at, updated_at) VALUES (:id, :tid, :lid, 'notification', "
                "CAST(:payload AS jsonb), 'system', now(), now())"
            ),
            {"id": uuid7(), "tid": tenant_id, "lid": lead_id, "payload": body},
        )


def _compose(
    name: str | None,
    phone: str,
    status: str,
    summary: str | None,
    triggers: list[str],
    *,
    slug: str,
    lead_id: UUID,
) -> str:
    """THE NUMBER STAYS MASKED HERE, AND D-436 IS THE REASON IT NEEDED RE-DECIDING.

    D-436 unmasked the client's own customer contact data on every SCREEN, on the
    argument that a client who cannot read back their customer's number cannot ring
    them. That argument is about a surface where somebody signed in: the dashboard's
    full number sits behind an authenticated session, a role that holds `leads:read`,
    RLS, and — for a Calevate operator in a view-as session — a verified impersonation
    grant and an `audit_log` row. Four controls.

    THIS EMAIL HAS NONE OF THE FOUR, and the deciding fact is about our own schema
    rather than about email in general: the recipient is `organizations.billing_email`,
    ONE column on the org row, collected to send invoices to. It is not a `memberships`
    row. It carries no role, so nothing about it says its reader may see leads; it is
    routinely a shared alias (accounts@, info@) or an accountant outside the business;
    and it is the one address on this platform that a `leads:read` check has never been
    applied to. Putting a consumer's phone number there is a disclosure to an
    unauthenticated party that we chose, not one the client asked for.

    Current guidance says the same thing from the other direction and it is what a
    reviewer will check this against: transactional mail is held to data minimisation —
    send the minimum the message needs — and the recommended shape for anything more is
    a NOTIFICATION PLUS A LINK to a place the recipient must authenticate into, rather
    than the data itself (kiteworks.com/gdpr-compliance/email-pii, "Best practices to
    avoid sending PII"; the same pattern the DPDP Rules' breach-notice guidance assumes
    for a fiduciary's own contact detail). Mail also leaves our control completely: we
    cannot revoke it, we cannot see who forwarded it, and it is retained on a server we
    do not hold — which is exactly the set of properties the dashboard does not have.

    SO THE TWO SURFACES ARE CONSISTENT IN PRINCIPLE, WHICH IS THE ONLY CONSISTENCY
    WORTH HAVING: the number is shown wherever a role check stands behind the reader,
    and nowhere else. What was actually broken was not the mask — it was that the mask
    had no way out. The body said "Open the lead in your Calevate dashboard" and gave
    no link, so honouring the alert meant finding the row by hand, which is how a
    2-minute SLO turns into a five-minute one and how a masked number reads as an
    obstruction rather than a control. It now carries the deep link, and the link lands
    on the screen D-436 unmasked.

    Rejected: sending the number and relying on the client's inbox security. That makes
    the weakest link in the chain somebody else's mail provider for a benefit — a
    tap-to-dial in a notification — that one extra tap already buys.

    The summary stays redacted for a different rule entirely: it is transcript-derived
    prose (`crm.service.redacted_summary`), hard rule 5, and D-436 does not touch it.
    The NAME is sent whole, and deliberately: it is what makes the alert recognisable
    at a glance, it is not a contact identifier — nobody can ring it — and an alert
    that says only "a lead was marked hot" is one nobody opens.
    """
    masked = redact(phone).text
    lines = [
        f"A lead was marked {status} by your AI receptionist.",
        "",
        f"Name: {name or 'not captured'}",
        f"Phone: {masked}",
    ]
    if triggers:
        lines.append(f"Triggered by: {', '.join(triggers)}")
    if summary:
        lines += ["", "Call summary:", redact(summary).text]
    lines += [
        "",
        "Open the lead to see the full number and call back:",
        f"{CONSOLE_BASE}/c/{slug}/leads/{lead_id}",
    ]
    return "\n".join(lines)


async def _send_email(to: str, subject: str, body: str) -> bool:
    """Delivery goes through the configured transport (`workers/transport.py`).

    Returns whether it landed; the CALLER decides what a failure costs, because only
    the caller knows which attempt this is. The no-address case never reaches here —
    it is a data fix and is alerted as one.

    **OFF THE EVENT LOOP (P6.3).** `SmtpTransport.send` is plain `smtplib.SMTP` with
    `starttls()` and `login()` on a `SMTP_TIMEOUT_S` budget — synchronous socket I/O, and
    this `async def` used to `return` it directly. So the call site READ as deferred while
    doing nothing of the kind, and up to `SMTP_TIMEOUT_S` of network wait stopped the
    whole worker: all ten concurrent jobs, including `dispatch_outbox` on its 10-second
    schedule and `dispatch_campaign_tick` on its 30-second one — and hard rule 5's DNC
    deadline is "before the next dispatch tick".

    This repository already stated the rule twice and broke it here. `transport.py` says
    callers on a latency budget defer rather than adapt the transport, and `alerting.py`
    does defer; `whatsapp.py` says of the WhatsApp twin of this exact call, on the same
    lead, in the same transaction, that a blocking send "would park the loop … and stall
    every other job on the same worker". D-159 fixed the same class in `storage.py`.
    """
    # BRANDED, and the text is untouched. `_compose_body` is what `redact()` runs through
    # and what `tests/hot_lead_channels_test` asserts on; `from_text` wraps that exact
    # string rather than composing a second one, so nothing reaches an inbox that the
    # redaction did not see. The console link in it becomes the button — this alert has a
    # two-minute SLO and its reader is on a phone.
    message = from_text(
        subject=subject,
        preheader="A lead your AI receptionist marked hot is waiting for a call back.",
        heading="A lead is waiting for you",
        text=body,
        cta="Open the lead",
    )
    transport = get_transport()
    return await asyncio.to_thread(
        lambda: transport.send(to=to, subject=subject, body=message.text, html=message.html)
    )


def _json(value: Any) -> str:
    return json.dumps(value, default=str)


__all__ = ["notify_hot_lead"]
