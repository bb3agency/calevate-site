"""Tell the client and every super admin about value given with no payment (D-890).

Promised by `billing/comp_notices.owe_comp_notices` in the transaction that granted the credit
or made the account paid. One run, three parts, each safe to repeat:

1. **The client's dashboard notice**: an announcement for this account alone, for
   `NOTICE_DAYS`, unless the same words were already put up for it in the last day (a retry
   after the notice landed but before an email went).
2. **The client's email**, to the account's billing address, as every other account email
   is sent (`trial_notices`, `wallet_alerts`). No address: an operator alarm, and the notice
   above still stands.
3. **Every live super admin's email**: the act, the amount, who did it and why. With one
   super admin this is the trail that stands in for a second approver.

The super admins are emailed before the client. A failed send raises `arq.Retry`, so ARQ
retries the run; the notice is not written twice, and the client's email, being last, is not sent
twice. Nothing is logged but ids, the kind and counts (hard rule 6).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Final, NoReturn
from uuid import UUID

from arq import Retry
from sqlalchemy import text

from apps.api.announcements import service as announcements
from apps.api.announcements.schemas import AnnouncementIn
from apps.api.billing.comp_notices import COMP_NOTICE_JOB
from apps.api.billing.display import display_inr
from apps.api.billing.service import get_balance, to_paise
from apps.api.core.alerting import alert
from apps.api.core.brand import PRODUCT
from apps.api.core.logging import get_logger
from apps.api.core.rbac import SUPERADMIN_ROLE
from apps.api.core.transport import EmailPurpose, get_transport
from apps.api.db.session import admin_session, tenant_session, untenanted_session
from apps.workers.email_render import from_text

log = get_logger(__name__)

JOB_NAME: Final = COMP_NOTICE_JOB

#: How long the dashboard notice stays up.
NOTICE_DAYS: Final = 14


def _inr(value: Decimal) -> str:
    """Client-facing: the one-decimal display rule."""
    return display_inr(value)


def _inr_exact(value: Decimal) -> str:
    """For the operators' email, which records the exact grant."""
    return f"₹{to_paise(value)}"


def notice_text(*, kind: str, amount: Decimal | None) -> str:
    """The dashboard line. Client-facing: plain, no vendor, no internal words."""
    if kind == "grant":
        assert amount is not None
        return f"We added {_inr(amount)} of calling credit to your account. It's on us."
    if amount is not None:
        return (
            "Your account is now a paid account, with "
            f"{_inr(amount)} of calling credit on us. Your trial limits are lifted."
        )
    return "Your account is now a paid account. Your trial limits are lifted."


def client_email(
    *, kind: str, amount: Decimal | None, balance: Decimal, business: str
) -> tuple[str, str]:
    """(subject, body) for the owner."""
    if kind == "grant":
        assert amount is not None
        return (
            f"{_inr(amount)} of credit added to your {PRODUCT} account",
            f"We added {_inr(amount)} of calling credit to {business}'s {PRODUCT} account. "
            "It is a gift: no payment was taken and nothing is owed.\n\n"
            f"Your balance is now {_inr(balance)}. It pays for calls like any other "
            "credit.",
        )
    gift = (
        f"\n\nWe also added {_inr(amount)} of calling credit, on us. Your balance is now "
        f"{_inr(balance)}."
        if amount is not None
        else ""
    )
    return (
        f"Your {PRODUCT} account is now a paid account",
        f"{business}'s {PRODUCT} account is now a paid account. No payment was taken.\n\n"
        "Your trial limits are lifted: you can verify your business, get your own phone "
        "number, answer calls and run campaigns." + gift,
    )


def superadmin_email(
    *,
    kind: str,
    amount: Decimal | None,
    business: str,
    slug: str,
    actor: str,
    reason: str,
) -> tuple[str, str]:
    if kind == "grant" and amount is not None:
        what = f"{_inr_exact(amount)} of credit granted"
    else:
        what = "made a paid account" + (f" with {_inr_exact(amount)} of credit" if amount else "")
    return (
        f"{PRODUCT}: {business} {what}",
        f"{business} (/{slug}): {what}, with no payment, by {actor}.\n\n"
        f"Reason given: {reason}\n\n"
        "Every grant and complimentary conversion is sent to every super admin. If you did "
        "not expect this one, check the client's credits page and the audit log now.",
    )


async def _send(
    address: str, subject: str, body: str, *, cta: str | None, purpose: EmailPurpose
) -> bool:
    message = from_text(subject=subject, preheader=subject, heading=subject, text=body, cta=cta)
    transport = get_transport(purpose)
    # Off the event loop: the SMTP transport is synchronous (`wallet_alerts`' reason).
    return await asyncio.to_thread(
        lambda: transport.send(to=address, subject=subject, body=message.text, html=message.html)
    )


async def _post_notice(tenant_id: UUID, message: str, *, retry: bool) -> bool:
    """Put the dashboard notice up once. True when this run posted it.

    The notice is posted before any email, so a first attempt always posts; only a retry
    looks for one it may already have posted. Checking on the first attempt too would hide
    a second, identical grant made the same day."""
    async with admin_session() as session:
        already = (
            None
            if not retry
            else (
                await session.execute(
                    text(
                        "SELECT 1 FROM platform_announcements WHERE target_tenant_id = :tid "
                        "AND message = :m AND created_at > now() - interval '1 day'"
                    ),
                    {"tid": tenant_id, "m": message},
                )
            ).first()
        )
        if already is not None:
            return False
        await announcements.create(
            session,
            AnnouncementIn(
                message=message,
                link_url="/billing",
                link_label="See your credit",
                tone="success",
                audience="tenant",
                target_tenant_id=tenant_id,
                ends_at=datetime.now(UTC) + timedelta(days=NOTICE_DAYS),
            ),
            admin_user_id=None,
        )
    return True


#: Seconds before each retry, indexed by the attempt that just failed (`wallet_alerts`).
RETRY_BACKOFF_S: Final[tuple[float, ...]] = (60.0, 300.0)


def _retry(attempt: int, *, tenant_id: UUID, leg: str) -> NoReturn:
    """A send that was not accepted. `arq.Retry`, not a plain raise: arq 0.28 re-runs a job
    only for `Retry`, `RetryJob` or `CancelledError` (`arq/worker.py` `run_job`), so any
    other exception is terminal on the first attempt. Past `max_tries` arq gives up and
    `install_arq_terminal_alerter` raises the alarm."""
    log.warning(
        "comp_notice_send_failed",
        extra={"tenant_id": str(tenant_id), "leg": leg, "attempt": attempt},
    )
    raise Retry(defer=RETRY_BACKOFF_S[max(min(attempt, len(RETRY_BACKOFF_S)) - 1, 0)])


async def notify_comp(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    attempt = int(ctx.get("job_try", 1) or 1)
    tenant_id = UUID(str(payload["tenant_id"]))
    kind = str(payload["kind"])
    amount = Decimal(str(payload["amount_inr"])) if payload.get("amount_inr") else None
    reason = str(payload.get("reason") or "")
    async with tenant_session(tenant_id) as session:
        org = (
            await session.execute(
                text("SELECT name, slug, billing_email FROM organizations WHERE id = :tid"),
                {"tid": tenant_id},
            )
        ).first()
        balance = (await get_balance(session, tenant_id=tenant_id)).amount_inr
    if org is None:
        return "no_account"
    business, slug, billing_email = str(org[0]), str(org[1]), org[2]
    async with untenanted_session() as session:
        actor_row = (
            (
                await session.execute(
                    text("SELECT COALESCE(name, email) FROM admin_users WHERE id = :id"),
                    {"id": payload.get("actor_id")},
                )
            ).first()
            if payload.get("actor_id")
            else None
        )
        supers = [
            str(r[0])
            for r in (
                await session.execute(
                    text(
                        "SELECT email FROM admin_users WHERE role = :role "
                        "AND deactivated_at IS NULL AND email IS NOT NULL"
                    ),
                    {"role": SUPERADMIN_ROLE},
                )
            ).all()
        ]
    actor = str(actor_row[0]) if actor_row and actor_row[0] else "a super admin"

    posted = await _post_notice(tenant_id, notice_text(kind=kind, amount=amount), retry=attempt > 1)

    # Ours first, the client's last: a failure raises and ARQ re-runs the whole job, so
    # whatever went before a failure is sent again. A repeated internal email is noise; a
    # client told twice about one gift reads as two gifts.
    subject, body = superadmin_email(
        kind=kind, amount=amount, business=business, slug=slug, actor=actor, reason=reason
    )
    for address in supers:
        if not await _send(address, subject, body, cta=None, purpose=EmailPurpose.OPERATOR):
            _retry(attempt, tenant_id=tenant_id, leg="superadmin")
    if not supers:
        alert("WORKER_DELIVERY", "comp_notice_no_superadmin_email", tenant_id=str(tenant_id))

    if billing_email:
        subject, body = client_email(kind=kind, amount=amount, balance=balance, business=business)
        if not await _send(
            str(billing_email),
            subject,
            body,
            cta="Open your dashboard",
            purpose=EmailPurpose.BILLING,
        ):
            _retry(attempt, tenant_id=tenant_id, leg="client")
    else:
        alert("WORKER_DELIVERY", "comp_notice_no_billing_email", tenant_id=str(tenant_id))

    log.info(
        "comp_notices_sent",
        extra={
            "tenant_id": str(tenant_id),
            "kind": kind,
            "notice_posted": posted,
            "client_emailed": bool(billing_email),
            "superadmins": len(supers),
        },
    )
    return "sent"


__all__ = [
    "JOB_NAME",
    "NOTICE_DAYS",
    "client_email",
    "notice_text",
    "notify_comp",
    "superadmin_email",
]
