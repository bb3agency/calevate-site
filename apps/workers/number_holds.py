"""The hold job: a stopped client's rented numbers held, resumed, released, and told (D-860).

    settle_number_holds   outbox, per tenant — queued by a closure, a reopening and a wallet
                          climbing back to zero, so the phone changes at once
    sweep_number_holds    hourly — the same pass over every tenant: a wallet that has been
                          below zero long enough is noticed here, and every due release and
                          reminder happens here
    notify_number_hold    outbox — one email to the account owner per event

The decisions are `campaigns/number_holds.py`'s; this module makes the vendor calls and sends
the email. One pass over one tenant:

1. Stopped? Hold every rented number not yet held. Not stopped? End every open hold and put
   each number back on its agent (`engine_numbers.sync_number_attachment`, which reads our
   record; the hold never touched `phone_numbers.agent_id`).
2. Each new hold: read the platform's rent instant (`since`), set the release date, detach.
3. Each hold whose date has come: release at the platform, in the transaction that ends the
   hold and records the release (`claim_release`), so a top-up landing at the same moment
   either wins outright or finds the number gone.
4. Queue the emails owed, one per event for all the tenant's numbers it concerns.
5. A closed account whose last hold ended in a release has its workspace offboarding queued
   again (`tenancy/engine_workspace.resume_workspace_offboarding`).

Every step is a CAS or idempotent at the platform, so the hourly pass and an outbox pass
meeting on one tenant cost a round trip, not a double release or a second email. One number
failing does not stop the others; failures retry the job and then alarm
`number_hold_unsettled`, because a held number not released before its renewal is a month we
pay for nobody.

Ids and counts in every log line and alarm; no phone number anywhere (hard rule 6), and none
in the email either: a number is named by the agent it was on, and the owner's Phone numbers
page shows the digits.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

from arq import Retry
from calevate_shared.backoff import ladder_delay_s
from sqlalchemy import text

from apps.api.billing.plans import IST
from apps.api.campaigns.engine_number_purchase import release_engine_number
from apps.api.campaigns.engine_numbers import engine_number_provider, sync_number_attachment
from apps.api.campaigns.number_holds import (
    NOTICE_EVENTS,
    NOTICE_RELEASED,
    NOTICE_REMINDER,
    OpenHold,
    apply_hold,
    claim_notices,
    claim_release,
    close_holds_of_released_numbers,
    mark_detached,
    open_holds,
    place_holds,
    release_instant,
    reminder_instant,
    resume_holds,
    stopped_reason,
)
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.core.settings import get_settings
from apps.api.core.transport import get_transport
from apps.api.db.session import admin_session, tenant_session
from apps.api.engine.thinnest_numbers import thinnest_numbers
from apps.api.reliability.service import enqueue_outbox
from apps.api.tenancy.closure import read_closure
from apps.api.tenancy.engine_workspace import resume_workspace_offboarding
from apps.workers.account_closure import account_recipients
from apps.workers.auth_email import CONSOLE_BASE
from apps.workers.email_render import from_text

log = get_logger(__name__)

NOTICE_JOB: Final = "notify_number_hold"

#: The minute past each IST hour the sweep fires on, shared with no other fleet walk.
SWEEP_MINUTE: Final = 23

_RETRY_AFTER_S: Final = (60, 600)
_NOTICE_RETRY_AFTER_S: Final = (60.0, 300.0)

#: Every organization, erased ones included: an erased account's numbers are still ours
#: until released. The one statement here that runs as the admin role.
_DIRECTORY: Final = "SELECT id FROM organizations ORDER BY id"

#: What `sync_number_attachment` answers when the platform now holds what our record says.
_SETTLED: Final = frozenset({"unchanged", "applied", "other_workspace"})


async def _apply(tenant_id: UUID, hold: OpenHold, tally: Counter[str]) -> datetime:
    """Set a new hold's release date from the platform's rent instant, and return it.

    Our own `created_at` is always an anchor too: the client's paid period runs from it, and
    the earliest renewal either implies is the one released before. A platform that cannot
    be read raises, so the pass retries rather than dating the release from our record
    alone; one that answers without `since` leaves our record as the only anchor, said so in
    `anchor_source` and the log.
    """
    if hold.engine_number_ref is None:
        raise ValueError("a held number has no platform handle")
    since = (await thinnest_numbers().get_number(hold.engine_number_ref)).rented_since
    anchors = [hold.recorded_at] if since is None else [hold.recorded_at, since]
    if since is None:
        log.warning("number_hold_rent_day_unread", extra={"number_id": str(hold.number_id)})
    release_at = release_instant(held_at=hold.held_at, anchors=anchors)
    async with tenant_session(tenant_id) as session:
        applied = await apply_hold(
            session,
            hold_id=hold.hold_id,
            release_at=release_at,
            remind_at=reminder_instant(held_at=hold.held_at, release_at=release_at),
            anchor_source="recorded" if since is None else "vendor",
        )
    tally["applied"] += int(applied)
    return release_at


async def _settle_hold(tenant_id: UUID, hold: OpenHold, now: datetime, tally: Counter[str]) -> None:
    release_at = hold.release_at or await _apply(tenant_id, hold, tally)
    if release_at > now:
        if not hold.detached:
            async with tenant_session(tenant_id) as session:
                outcome = await sync_number_attachment(session, number_id=hold.number_id)
                if outcome in _SETTLED:
                    await mark_detached(session, hold_id=hold.hold_id)
                    tally["detached"] += 1
        return
    async with tenant_session(tenant_id) as session:
        if await claim_release(session, hold_id=hold.hold_id):
            await release_engine_number(
                session, tenant_id=tenant_id, number_id=hold.number_id, by_admin=False
            )
            tally["released"] += 1


async def settle_tenant(tenant_id: UUID) -> tuple[Counter[str], int]:
    """One pass over one tenant's holds. Returns what it did and how many numbers failed."""
    now = datetime.now(UTC)
    tally: Counter[str] = Counter()
    async with tenant_session(tenant_id) as session:
        reason = await stopped_reason(session, tenant_id=tenant_id, now=now)
        if reason is not None:
            tally["held"] += len(await place_holds(session, tenant_id=tenant_id, reason=reason))
            resumed: list[UUID] = []
        else:
            resumed = await resume_holds(session)
        tally["closed_elsewhere"] += await close_holds_of_released_numbers(session)
        holds = await open_holds(session)
        erased = (await read_closure(session, tenant_id=tenant_id)).is_erased
    failed = 0
    for number_id in resumed:
        try:
            async with tenant_session(tenant_id) as session:
                await sync_number_attachment(session, number_id=number_id)
            tally["resumed"] += 1
        except Exception as exc:
            # The hold has ended either way; the daily number sweep puts the attachment back
            # (`engine_numbers.reconcile_engine_number_attachments`).
            log.error(
                "number_hold_reattach_failed",
                extra={"number_id": str(number_id), "error": exc.__class__.__name__},
            )
    for hold in holds:
        try:
            await _settle_hold(tenant_id, hold, now, tally)
        except Exception as exc:
            failed += 1
            log.error(
                "number_hold_settle_failed",
                extra={"number_id": str(hold.number_id), "error": exc.__class__.__name__},
            )
    async with tenant_session(tenant_id) as session:
        for event in NOTICE_EVENTS:
            ids = await claim_notices(session, event=event)
            # An erased account has nobody left to tell; the stamp still records the event.
            if ids and not erased:
                await enqueue_outbox(
                    session,
                    job=NOTICE_JOB,
                    payload={
                        "tenant_id": str(tenant_id),
                        "event": event,
                        "hold_ids": [str(i) for i in ids],
                    },
                )
                tally[f"notice_{event}"] += 1
        # A hold ended by a release elsewhere (an operator's) counts too: nothing else
        # queues the offboarding that waited on it.
        ended_by_release = tally["released"] + tally["closed_elsewhere"]
        if ended_by_release and not await open_holds(session):
            tally["offboarding_resumed"] += int(
                await resume_workspace_offboarding(session, tenant_id=tenant_id)
            )
    if any(tally.values()) or failed:
        log.info(
            "number_holds_settled",
            extra={"tenant_id": str(tenant_id), "failed": failed, **dict(tally)},
        )
    return tally, failed


def _alarm_unsettled(failed: int, attempt: int, *, tenant_id: UUID | None = None) -> None:
    alert(
        "WORKER_TERMINAL",
        "number_hold_unsettled",
        detail=(
            f"{failed} held phone number(s) could not be settled after {attempt} attempt(s): "
            "a release date not set, a number not detached, or a release that failed. A held "
            "number not released before its monthly renewal is charged to us for a client "
            "who is paying nothing. The hourly sweep tries again."
        ),
        **({"tenant_id": str(tenant_id)} if tenant_id is not None else {}),
    )


async def settle_number_holds(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """One tenant's pass, from the outbox."""
    tenant_id = UUID(str(payload["tenant_id"]))
    if engine_number_provider() is None:
        return "not_applicable"
    attempt = int(ctx.get("job_try", 1))
    tally, failed = await settle_tenant(tenant_id)
    if failed:
        if attempt < WORKER_MAX_TRIES:
            raise Retry(defer=ladder_delay_s(_RETRY_AFTER_S, attempt))
        _alarm_unsettled(failed, attempt, tenant_id=tenant_id)
    return " ".join(f"{key}={value}" for key, value in sorted(tally.items())) or "nothing"


async def sweep_number_holds(ctx: dict[str, Any]) -> str:
    """Hourly. Every tenant's pass; one tenant failing costs nobody else theirs."""
    if engine_number_provider() is None:
        return "not_applicable"
    attempt = int(ctx.get("job_try", 1))
    async with admin_session() as directory:
        tenants = [UUID(str(t)) for t in (await directory.execute(text(_DIRECTORY))).scalars()]
    totals: Counter[str] = Counter()
    failed = 0
    for tenant_id in tenants:
        try:
            tally, tenant_failed = await settle_tenant(tenant_id)
        except Exception as exc:
            tally, tenant_failed = Counter(), 1
            log.error(
                "number_hold_tenant_failed",
                extra={"tenant_id": str(tenant_id), "error": exc.__class__.__name__},
            )
        totals.update(tally)
        failed += tenant_failed
    summary = {"tenants": len(tenants), "failed": failed, **dict(sorted(totals.items()))}
    log.info("number_holds_swept", extra=summary)
    if failed:
        if attempt < WORKER_MAX_TRIES:
            raise Retry(defer=ladder_delay_s(_RETRY_AFTER_S, attempt))
        _alarm_unsettled(failed, attempt)
    return str(summary)


# --- the emails ---------------------------------------------------------------------------

_NOTICE_ROWS: Final = (
    "SELECT h.reason, h.release_at, h.ended_at, a.name FROM phone_number_holds h "
    "LEFT JOIN agents a ON a.id = h.agent_id WHERE h.id = ANY(:ids) ORDER BY h.release_at, h.id"
)


def ist_day(moment: datetime) -> str:
    """`Monday 23 November 2026`: the IST calendar day of an instant, as the emails say it."""
    day = moment.astimezone(IST)
    return f"{day:%A} {day.day} {day:%B %Y}"


def _which(agent: str | None) -> str:
    return f"The number your agent {agent} answers" if agent else "Your number with no agent on it"


def _why(reason: str, *, days: int) -> str:
    if reason == "account_closed":
        return "your Calevate account has been closed"
    return f"your calling credit has been below zero for {days} days"


def _keep(reason: str, slug: str) -> list[str]:
    if reason == "account_closed":
        return [
            "To keep a number, ask us to reopen your account before that date: reply to this "
            "email. Reopening puts each number back on the agent it was on.",
        ]
    return [
        "To keep a number, add credit so your balance is back to zero or more before that "
        "date. Calls start again straight away, on the same agent as before.",
        "",
        "Add credit here:",
        # Its own paragraph, so `from_text` renders it as the email's button.
        "",
        f"{CONSOLE_BASE}/c/{slug}/credits",
    ]


def compose(
    *, event: str, business: str, slug: str, rows: list[tuple[str, datetime | None, str | None]]
) -> tuple[str, str]:
    """The subject and body of one hold email, in a business owner's words. `rows` is each
    number's `(reason, date, agent name)`: the release date, or for `released` the day it
    was released. No provider name (D-679) and no phone number."""
    reason = rows[0][0]
    days = get_settings().number_hold_after_negative_days
    plural = len(rows) > 1
    dated = [f"{_which(agent)}: {ist_day(at)}." for _r, at, agent in rows if at is not None]
    if event == NOTICE_RELEASED:
        subject = "We have given up your phone number" + ("s" if plural else "")
        lines = [
            f"Because {_why(reason, days=days)}, we have given up "
            + ("these phone numbers" if plural else "this phone number")
            + f" of {business}:",
            "",
            *dated,
            "",
            "A number we give up goes back to the phone company, and anyone can take it. We "
            "cannot get it back. No rent is charged for it any more.",
        ]
        if reason != "account_closed":
            lines += [
                "",
                "Once your credit is above zero you can get a new number from the Phone "
                "numbers page.",
            ]
        return subject, "\n".join(lines)
    lead = (
        f"Because {_why(reason, days=days)}, calls to the phone "
        + ("numbers" if plural else "number")
        + f" {business} rents through us have stopped: nobody answers "
        + ("them" if plural else "it")
        + ", and no rent is charged."
    )
    if event == NOTICE_REMINDER:
        subject = "Your phone number will be given up soon"
        lines = ["This is a reminder. " + lead]
    else:
        subject = "Calls to your phone number have stopped"
        lines = [lead]
    lines += [
        "",
        "We will give up " + ("each number" if plural else "the number") + " on this date:",
        "",
        *dated,
        "",
        "A number we give up goes back to the phone company, and anyone can take it. We "
        "cannot get it back.",
        "",
        *_keep(reason, slug),
    ]
    return subject, "\n".join(lines)


async def notify_number_hold(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """One hold email to the account's billing address and its owners."""
    tenant_id = UUID(str(payload["tenant_id"]))
    event = str(payload.get("event") or "")
    hold_ids = [UUID(str(i)) for i in payload.get("hold_ids") or []]
    if event not in NOTICE_EVENTS or not hold_ids:
        alert(
            "WORKER_DELIVERY",
            "number_hold_notice_undelivered",
            detail="a number hold notice was queued with an event or holds this job cannot send",
            tenant_id=str(tenant_id),
        )
        return "unreadable"
    attempt = int(ctx.get("job_try", 1))
    async with tenant_session(tenant_id) as session:
        org = (
            await session.execute(
                text("SELECT name, slug FROM organizations WHERE id = :tid"), {"tid": tenant_id}
            )
        ).first()
        rows = (await session.execute(text(_NOTICE_ROWS), {"ids": hold_ids})).all()
        recipients = await account_recipients(session, tenant_id=tenant_id)
    if org is None or not rows:
        return "tenant_missing"
    if not recipients:
        alert(
            "WORKER_DELIVERY",
            "number_hold_notice_undelivered",
            detail=(
                "a client whose phone numbers are held has no billing address and no active "
                "owner, so it has not been told the date they will be given up. Tell them "
                "another way."
            ),
            tenant_id=str(tenant_id),
        )
        return "no_channel"
    dates = [(str(r[0]), r[2] if event == NOTICE_RELEASED else r[1], r[3]) for r in rows]
    subject, body = compose(event=event, business=str(org[0]), slug=str(org[1]), rows=dates)
    email = from_text(
        subject=subject,
        preheader=subject,
        heading=subject,
        text=body,
        cta="Add credit" if event != NOTICE_RELEASED else None,
    )
    transport = get_transport()
    delivered = 0
    for address in recipients:
        # Off the event loop: the SMTP transport is synchronous (`notifications._send_email`).
        sent = await asyncio.to_thread(
            transport.send, to=address, subject=email.subject, body=email.text, html=email.html
        )
        delivered += int(bool(sent))
    if delivered:
        log.info(
            "number_hold_notice_sent",
            extra={"tenant_id": str(tenant_id), "event": event, "recipients": delivered},
        )
        return "sent"
    if attempt < WORKER_MAX_TRIES:
        raise Retry(defer=ladder_delay_s(_NOTICE_RETRY_AFTER_S, attempt))
    alert(
        "WORKER_DELIVERY",
        "number_hold_notice_undelivered",
        detail=(
            f"a number hold email ({event}) was not delivered after {attempt} attempt(s); the "
            "client has not been told when its held numbers will be given up"
        ),
        tenant_id=str(tenant_id),
    )
    return f"exhausted after {attempt}"


__all__ = [
    "NOTICE_JOB",
    "SWEEP_MINUTE",
    "compose",
    "ist_day",
    "notify_number_hold",
    "settle_number_holds",
    "settle_tenant",
    "sweep_number_holds",
]
