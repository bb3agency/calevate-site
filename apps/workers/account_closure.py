"""Telling a client their account closed, and erasing it when the window runs out (D-536).

Two jobs, deliberately not one. `notify_account_closed` is what the founder asked for —
*"it sends a respective alert also to that client via mail and number"* — and
`sweep_due_erasures` is what makes the grace window in `tenancy/closure.py` a real deadline
rather than a column nobody reads.

═══ WHY THE SWEEP IS A CRON AND THE NOTICE IS AN OUTBOX JOB ═══

The notice belongs to ONE transaction: the closure, its audit row and the promise to tell
the client commit together or not at all (BACKEND-PATTERNS §4). A client told their account
closed by an email whose closure rolled back is worse than not being told, and a closure
that commits with no notice is the thing the founder explicitly asked us not to build.

The sweep belongs to no transaction. Its input is a date that arrives while nobody is
looking, so there is nothing to enqueue it FROM — the next tick is the retry, which is the
property `workers/settings.py` names as the reason its crons need no dead-letter path.

═══ WHAT THE SWEEP DOES AND, MORE IMPORTANTLY, WHAT IT DOES NOT ═══

It files. For each account whose `erase_after` has passed it calls
`compliance.tenant_erasure.request_tenant_erasure`, which is the SAME function the admin
console's immediate-erase button calls, in the same shape, writing the same row and
queueing the same worker. There is no second eraser here and no erase statement of any
kind: this module contains no DELETE and no UPDATE that clears a personal field, and if one
ever appears in it, that is the defect.

A tenant that fails is ONE tenant that failed. `retention.apply_retention` learned that the
hard way (P6.2: one bad row ended the night's sweep for every tenant after it, silently,
because the raise was not `arq.Retry` and `max_tries` defaulted to 1). Same shape here, for
the same reason and with more at stake: a deadline the client has been given a date for.

═══ HARD RULE 6 ═══

The notice carries an email address and a business name into a third party's system. No log
line here holds either: every one carries the tenant id and the recipient's DOMAIN via
`transport._domain`, which exists for exactly this. The WhatsApp leg carries no address at
all — it resolves its own recipient and never returns it.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Final
from uuid import UUID

from arq import Retry
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.compliance.tenant_erasure import request_tenant_erasure
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.core.settings import get_settings
from apps.api.db.session import admin_session, tenant_session
from apps.api.tenancy.closure import due_erasures
from apps.workers.email_render import from_text
from apps.workers.transport import _domain, get_transport
from apps.workers.whatsapp import (
    SendStatus,
    WhatsAppMessage,
    get_whatsapp_transport,
    resolve_destination,
)

log = get_logger(__name__)

NOTICE_JOB: Final = "notify_account_closed"

#: The two things a client is told about their account's closure state. `closed` carries a
#: date; `restored` withdraws one. There is deliberately no `erased` member: the erasure
#: produces a CERTIFICATE (`tenant_erasure.certificate`), which is a document rather than a
#: notification, and mailing "your data is gone" without the certificate attached would be
#: the one message that cannot be actioned.
NOTICE_CLOSED: Final = "closed"
NOTICE_RESTORED: Final = "restored"
NOTICE_EVENTS: Final = (NOTICE_CLOSED, NOTICE_RESTORED)

SUBJECT_CLOSED: Final = "Your Calevate account has been closed"
SUBJECT_RESTORED: Final = "Your Calevate account has been reopened"

#: Seconds before each retry, indexed by the attempt that just failed — one shorter than
#: the budget, because the last attempt has nothing after it. Paced like the hot-lead
#: ladder rather than the auth ladder: nobody is sitting on a screen waiting for this, and
#: a mail provider having a bad two minutes must not consume a notice that carries a legal
#: date.
RETRY_BACKOFF_S: tuple[float, ...] = (15.0, 45.0)

#: How many due accounts one tick will file for. Bounded like every sweep in this fleet:
#: the tick that eventually times out is the unbounded one, and it times out on the night
#: the deadline matters. A backlog longer than this is discharged by the next tick — the
#: cron runs hourly, so nothing waits more than an hour past its date.
SWEEP_BUDGET: Final = 200


def _retry_after(attempt: int) -> float:
    index = min(attempt, len(RETRY_BACKOFF_S)) - 1
    return RETRY_BACKOFF_S[max(index, 0)]


def _compose(*, event: str, business: str, erase_on: str | None, reason: str | None) -> str:
    """The message body, in the client's terms and with nothing they cannot act on.

    **The erasure date is stated, and so is the thing the close does NOT do.** A client
    whose number still rings an answering agent after we told them the account was closed
    would discover that from a caller, and `compliance/tenant_erasure.py`'s register
    already commits us to saying it in the certificate — saying it here too costs one
    paragraph and is the difference between a disclosure and a surprise.

    The operator's `reason` is quoted verbatim when there is one. It is free text an
    operator typed, so it never reaches a log line (hard rule 6) — but it is the answer to
    the only question this email raises, and a closure notice that will not say why is the
    ticket nobody can close.
    """
    if event == NOTICE_RESTORED:
        return (
            f"The Calevate account for {business} has been reopened.\n\n"
            "Everything is back on: your team can sign in again, your agents can be "
            "published again, and the erasure that was scheduled has been cancelled. "
            "Nothing was deleted.\n\n"
            "If you did not expect this, reply to this email straight away."
        )

    lines = [
        f"The Calevate account for {business} has been closed.",
        "",
        "What this means right now: nobody at your business can sign in, no outbound "
        "calls or campaigns will run, and your agents can no longer be published.",
    ]
    if reason:
        lines += ["", f"The reason recorded for the closure is: {reason}"]
    if erase_on:
        lines += [
            "",
            f"Your call records, transcripts and leads are scheduled to be permanently "
            f"erased on {erase_on}. Until that date the closure can be reversed and "
            "nothing has been deleted — if this was a mistake, reply to this email "
            "before then. Afterwards it cannot be undone.",
            "",
            "If you want a copy of your data, ask for it before that date.",
        ]
    else:
        lines += [
            "",
            "No erasure is scheduled: your records are being kept, and they continue to "
            "age out under the retention periods already set on your account.",
        ]
    lines += [
        "",
        "One thing the closure does not do: your telephone number is still pointed at "
        "your agent by your telephony provider, so a caller dialling it may still reach "
        "an answering agent until that number is taken out of service. Tell us if you "
        "need that done and we will arrange it with the provider.",
    ]
    return "\n".join(lines)


async def _recipients(session: AsyncSession, *, tenant_id: UUID) -> list[str]:
    """Every address that must hear about this, de-duplicated case-insensitively.

    Both the billing address on the organisation AND the account's live owners, and the
    union rather than a preference order: the billing address is often an accounts inbox
    nobody reads daily, and the owner is the person who can act on a reversal window with
    a date on it. `notify_hot_lead` reaches for `billing_email` alone because a hot lead is
    a sales nudge; a closure notice is the account itself ending.

    Deactivated users are excluded — a removed owner must not receive the business's
    account notices — and the ordering is stable so a retry composes the same list.
    """
    rows = (
        await session.execute(
            text(
                "SELECT o.billing_email FROM organizations o WHERE o.id = :tid "
                "UNION "
                "SELECT u.email FROM memberships m JOIN users u ON u.id = m.user_id "
                "WHERE m.tenant_id = :tid AND m.role = 'owner' AND u.deactivated_at IS NULL"
            ),
            {"tid": tenant_id},
        )
    ).all()
    seen: dict[str, str] = {}
    for row in rows:
        address = str(row[0] or "").strip()
        if address:
            seen.setdefault(address.lower(), address)
    return [seen[key] for key in sorted(seen)]


async def notify_account_closed(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Tell one client that their account closed — or that it has been reopened.

    **EMAIL IS THE CHANNEL OF RECORD AND IT IS NEVER OPTIONAL** (the founder's decision 3).
    WhatsApp rides beside it where the client has opted in, and is never the only channel:
    a WhatsApp message is a nudge on somebody's phone, and a notice carrying a date after
    which a business's records are destroyed has to leave something they can keep, forward
    to their own counsel and produce later. That artefact is the email in their inbox and
    the `audit_log` row this job appends when it lands — append-only and hash-chained, so
    it is evidence rather than a claim.

    **NO SMS**, deliberately and permanently: SMS would drag the whole DLT/TCCCPR
    registration apparatus in front of a transactional account notice, and D-536 declines
    it (the founder's own decision on the same question).

    Retried on a transport failure and alerted when the ladder is spent. NOT retried when
    there is nobody to write to — that is a data fix, the same row will be just as empty in
    two minutes, and `notify_hot_lead` states the rule this follows.
    """
    tenant_id = UUID(str(payload["tenant_id"]))
    event = str(payload.get("event") or NOTICE_CLOSED)
    if event not in NOTICE_EVENTS:
        # A payload this worker does not understand. Terminal by nature — the same bytes
        # will be just as unreadable on the next attempt — and loud, because it means a
        # producer and this consumer disagree about the contract.
        alert(
            "WORKER_TERMINAL",
            "account_notice_unknown_event",
            detail="closure notice payload named an event this worker does not send",
            tenant_id=str(tenant_id),
        )
        return "unknown_event"

    erase_on = payload.get("erase_on")
    reason = payload.get("reason")
    attempt = int(ctx.get("job_try", 1))
    subject = SUBJECT_CLOSED if event == NOTICE_CLOSED else SUBJECT_RESTORED

    async with tenant_session(tenant_id) as session:
        business = (
            await session.execute(
                text("SELECT name FROM organizations WHERE id = :tid"), {"tid": tenant_id}
            )
        ).scalar()
        if business is None:
            # RLS returned nothing for an id this job was handed. Not retryable: the row
            # is not coming back, and the closure that produced this payload committed in
            # a transaction that could see it.
            alert(
                "WORKER_TERMINAL",
                "account_notice_tenant_missing",
                detail="closure notice queued for an organisation that cannot be read",
                tenant_id=str(tenant_id),
            )
            return "tenant_missing"

        recipients = await _recipients(session, tenant_id=tenant_id)
        if not recipients:
            alert(
                "WORKER_TERMINAL",
                "account_notice_no_channel",
                detail=(
                    "client has no billing address and no active owner, so the closure "
                    "notice cannot be delivered — tell them another way"
                ),
                tenant_id=str(tenant_id),
            )
            return "no_channel"

        body = _compose(
            event=event,
            business=str(business),
            erase_on=str(erase_on) if erase_on else None,
            reason=str(reason) if reason else None,
        )
        email = from_text(
            subject=subject,
            preheader=subject,
            heading=subject,
            text=body,
        )
        transport = get_transport()
        # `to_thread` for the reason `notifications._send_email` documents at length: the
        # SMTP transport is synchronous socket I/O, and returning it directly from an
        # `async def` parks every other job on this worker for the whole timeout —
        # including `dispatch_outbox` on its ten-second schedule.
        delivered = [
            address
            for address in recipients
            if await asyncio.to_thread(
                transport.send,
                to=address,
                subject=email.subject,
                body=email.text,
                html=email.html,
            )
        ]

        if delivered:
            # THE RECORD THE CLIENT CAN POINT AT. Written in the same transaction as
            # nothing else on purpose — the closure itself committed long ago — but
            # written HERE rather than at the enqueue, because what an operator or a
            # regulator later needs to know is that the notice LANDED, not that we meant
            # to send it. Domains and a count, never addresses (hard rule 6).
            await write_audit(
                session,
                action=f"tenant.closure_notice_{event}",
                actor_type="system",
                tenant_id=tenant_id,
                object_type="organization",
                object_id=str(tenant_id),
                summary={
                    "channel": "email",
                    "recipients": len(delivered),
                    "domains": sorted({_domain(address) for address in delivered}),
                    "erase_on": str(erase_on) if erase_on else None,
                },
            )

        # THE SECOND CHANNEL, AND NEVER THE ONLY ONE. Inside the same session block so it
        # reads the opt-in the email leg's transaction saw, and AFTER the email so a
        # WhatsApp failure can never be what stops the channel of record going out.
        whatsapp = await _whatsapp_leg(
            session, tenant_id=tenant_id, event=event, business=str(business)
        )

    if whatsapp:
        # No number, ever (hard rule 6). "I got no WhatsApp" and "we never sent one" have
        # different owners and are otherwise indistinguishable from outside.
        log.info(
            "account_notice_whatsapp", extra={"tenant_id": str(tenant_id), "outcome": whatsapp}
        )

    if delivered:
        log.info(
            "account_notice_sent",
            extra={
                "tenant_id": str(tenant_id),
                "event": event,
                "recipients": len(delivered),
                "attempts": attempt,
            },
        )
        return "sent"

    if attempt < WORKER_MAX_TRIES:
        raise Retry(defer=_retry_after(attempt))

    alert(
        "WORKER_DELIVERY",
        "account_notice_exhausted",
        detail=(
            f"closure notice undelivered after {attempt} attempt(s); the client has not "
            "been told their account state changed"
        ),
        tenant_id=str(tenant_id),
    )
    return f"exhausted after {attempt}"


#: The WhatsApp template body a human must submit to Meta for approval, kept next to the
#: code that fills it so the two cannot drift — the same construction as
#: `whatsapp.TEMPLATE_MISSED_CALL`, and like that one it is NOT YET APPROVED:
#:
#:     "Calevate: the account for {{1}} has been closed. Check your email for the details
#:      and the date your records are erased."
#:
#: ONE variable, and it is the CLIENT's own business name — Meta requires a
#: business-initiated message to identify who is contacting the recipient. The DATE is
#: deliberately not a variable: a WhatsApp nudge must not be the artefact somebody relies
#: on for a legal deadline, and pointing at the email keeps the record and the notice in
#: one place.
#:
#: ⚠ EXTERNAL BLOCKER, not an engineering one: this template cannot be used until it is
#: submitted and approved in the WhatsApp Business account, which needs a BSP that has not
#: been chosen. Until then `whatsapp_enabled` is off, this leg returns `"disabled"`, and
#: the email is the whole notice — which is why the email is unconditional.
TEMPLATE_ACCOUNT_CLOSED: Final = "calevate_account_closed_v1"


async def _whatsapp_leg(
    session: AsyncSession, *, tenant_id: UUID, event: str, business: str
) -> str | None:
    """The opted-in second channel, or a word saying why there was none.

    Returns `None` when there was nothing to report and a short outcome otherwise, so the
    caller can log it without needing to know the recipient — this function never returns
    a number and never logs one.

    **THREE REFUSALS, AND ALL THREE FAIL CLOSED.** The channel must be switched on; the
    account must have an owner with a number on file; and that person must have a live
    grant in `whatsapp_alert_optin_ledger`, read through `resolve_destination` — the ONE
    implementation of "may we message this person", shared with the settings screen and
    the admin surface that capture it. An absent ledger row is treated as "no", never as
    consent (`Destination.opt_in_at`'s own comment).

    Only the CLOSED notice goes out on this channel. A reopening is good news that costs
    nothing to read a day later in an inbox, and spending a template send — and a client's
    opt-in — on it is not what they granted it for.
    """
    if event != NOTICE_CLOSED:
        return None
    if not get_settings().whatsapp_enabled:
        # Not a failure. The channel is off until a BSP is chosen and this template is
        # approved, and the email above is the whole notice — which is exactly why the
        # email is unconditional and this is not.
        return "disabled"
    transport = get_whatsapp_transport()
    destination = await resolve_destination(session, tenant_id)
    if destination is None:
        return "no_recipient"
    if destination.opt_in_at is None:
        # Meta policy and DPDP land in the same place. Permanent by nature: the same
        # ledger will be just as silent in two minutes, so this is reported and not
        # retried.
        return "not_opted_in"
    # AWAITED, not `to_thread`: `WhatsAppTransport.send` is async by design (it talks
    # HTTP to Meta from inside an already-async worker), unlike the SMTP transport above.
    result = await transport.send(
        WhatsAppMessage(
            to_e164=destination.to_e164,
            template=TEMPLATE_ACCOUNT_CLOSED,
            locale=get_settings().whatsapp_template_locale,
            variables=(business,),
        )
    )
    if result.status is SendStatus.DELIVERED:
        return "delivered"
    # NOT retried, and that is the decision rather than an omission: the email is the
    # channel of record and it has already been sent or has its own ladder. A second
    # ladder for the nudge would double the failure surface of a message whose whole job
    # is to make somebody open the first one.
    return f"undelivered:{result.status}"


async def sweep_due_erasures(ctx: dict[str, Any]) -> str:
    """Hourly. File the tenant erasure for every account whose grace window has run out.

    Hourly rather than nightly because the window is a PROMISE with a date on it, and the
    same promise is what bounds the other direction: a client who asked us to erase now
    (`bring_erasure_forward`) should not wait until 03:40 for a deadline they set for this
    afternoon. An hour is the coarsest tick that keeps "erased on the date we told you"
    true in both directions.

    **This does not erase anything.** It calls `request_tenant_erasure`, which writes the
    request row and queues `execute_tenant_erasure` in one transaction — the same path the
    console's own button takes, so there is exactly one filing point and exactly one
    eraser. Nothing here duplicates a statement from `workers/retention.py`.

    **Already-filed is a success, not a skip.** `request_tenant_erasure` dedupes on the
    open request under an advisory lock and a partial unique index, so a tick that overlaps
    a slow predecessor converges on one request rather than minting a second. This
    therefore needs no cursor and no lease of its own.

    A tenant that fails does not fail the tick, and the count of failures is alerted
    AFTER the sweep — the shape `apply_retention` was rewritten into, for the reason it
    was: one bad row must not silently postpone every account behind it, and a deadline
    slipping is something an operator has to be told about rather than something they find
    in a log stream.
    """
    async with admin_session() as directory:
        due = await due_erasures(directory, limit=SWEEP_BUDGET)

    filed = 0
    failed = 0
    for tenant_id, reason in due:
        try:
            async with tenant_session(tenant_id) as scoped:
                record = await request_tenant_erasure(
                    scoped,
                    tenant_id=tenant_id,
                    # The operator's own words, carried onto the certificate so it says
                    # WHY this client's data went rather than "scheduled". Falls back to a
                    # sentence rather than an empty string: `tenant_erasure_requests.reason`
                    # is what a person reads next year.
                    reason=reason or "Grace period after account closure elapsed.",
                )
        except ProblemError:
            # `assert_erasable` refused. The common and CORRECT case is an account
            # restored between the read and the write — `tenant_not_closed` — which is the
            # undo working exactly as designed and must not page anybody. It is counted as
            # handled rather than failed for that reason: the row's `erase_after` was
            # cleared by the restore, so the next tick will not see it again.
            log.info("closure_sweep_refused", extra={"tenant_id": str(tenant_id)})
            continue
        except Exception:
            failed += 1
            log.exception("closure_sweep_tenant_failed", extra={"tenant_id": str(tenant_id)})
            continue
        filed += 1
        log.warning(
            "closure_sweep_filed",
            extra={"tenant_id": str(tenant_id), "request_id": str(record.id)},
        )

    totals = {"due": len(due), "filed": filed, "failed": failed}
    log.info("closure_sweep", extra=totals)
    if failed:
        alert(
            "WORKER_TERMINAL",
            "closure_sweep_incomplete",
            detail=(
                f"{failed} of {len(due)} account(s) past their erasure date were not "
                "filed this tick. Their data is still held past the date the client was "
                "given; the sweep runs again in an hour and will retry them."
            ),
        )
    return json.dumps(totals)


__all__ = [
    "NOTICE_CLOSED",
    "NOTICE_EVENTS",
    "NOTICE_JOB",
    "NOTICE_RESTORED",
    "SWEEP_BUDGET",
    "notify_account_closed",
    "sweep_due_erasures",
]
