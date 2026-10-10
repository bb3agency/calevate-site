"""The monthly platform fee's job: raise each month's fee, and tell the client (D-707).

D-707 replaced the setup fee this job used to issue (setup fees no longer exist) with an
optional platform-wide monthly fee. Every hour, while the ops switch is on, it walks the
live clients and for each one that is not exempt (a free trial, or an operator's waiver):

1. raises this IST month's fee if it has not been raised — `issue_charge` is guarded by a
   unique index on (tenant, month), so a retried or doubled tick raises it once;
2. sends at most three emails per unpaid fee, each claimed on its own stamp BEFORE the
   send so none goes twice: the fee is due, a reminder `REMINDER_BEFORE` the grace period
   ends, and outbound calling is paused once it has ended. The pause itself is not this
   job's: the dispatch gate reads the payments ledger (`billing/platform_fee.py`), so
   paying lifts it on the next dial whether or not this job ever runs again.

Hourly rather than on the 1st alone, because the fee for a client who becomes liable
mid-month (a trial converting, a waiver withdrawn) is raised within the hour, and the
reminder and pause notices are timed by each fee's own grace period, not by the calendar.

A tenant that fails does not stop the others; failures are counted and alarmed. The email
goes to `organizations.billing_email`, the address `wallet_alerts` and `trial_notices`
mail; logs carry ids, never the address (hard rule 6).
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy import text

from apps.api.billing.platform_fee import (
    REMINDER_BEFORE,
    FeeCharge,
    exemption_of,
    fee_switch,
    issue_charge,
    list_charges,
)
from apps.api.billing.service import to_paise
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.transport import get_transport
from apps.api.db.session import admin_session, tenant_session
from apps.workers.auth_email import CONSOLE_BASE
from apps.workers.email_render import from_text
from apps.workers.fleet_walk import WalkBudget
from apps.workers.trial_notices import ist_moment

log = get_logger(__name__)

#: The hourly sweep's minute. No other fleet-wide walk fires at :53
#: (`tests/job_registration_test.py::test_no_two_fleet_wide_walks_share_a_firing_minute`).
FEE_SWEEP_MINUTE: Final = 53

#: The live clients a fee can be raised for. A prospect, an onboarding account, a
#: suspended one and a closed one are not using the platform this month.
_DIRECTORY = (
    "SELECT id FROM organizations WHERE deleted_at IS NULL AND status = 'active' ORDER BY id"
)

Notice = Literal["issued", "reminder", "paused"]

#: The stamp each notice claims. A closed mapping, never interpolated from input.
_STAMP: Final[dict[Notice, str]] = {
    "issued": "issued_notice_sent_at",
    "reminder": "reminder_sent_at",
    "paused": "paused_notice_sent_at",
}

_SUBJECT: Final[dict[Notice, str]] = {
    "issued": "Your monthly platform fee is due",
    "reminder": "Reminder: your monthly platform fee is unpaid",
    "paused": "Outgoing calls are paused: your platform fee is unpaid",
}


def compose(notice: Notice, *, charge: FeeCharge, slug: str) -> str:
    """The email body, in a business owner's words. Incoming calls are always named as
    unaffected, because that is the first thing an owner worries about."""
    amount = f"₹{to_paise(charge.amount_inr):,}"
    pause = ist_moment(charge.grace_ends_at)
    if notice == "issued":
        opening = (
            f"Your platform fee for {charge.period} is {amount}. It is paid separately "
            "from your calling credit, which it never touches."
        )
        after = f"Please pay it by {pause}. After that, outgoing calls pause until it is paid."
    elif notice == "reminder":
        opening = f"Your platform fee for {charge.period} ({amount}) is still unpaid."
        after = f"Outgoing calls pause at {pause} unless it is paid before then."
    else:
        opening = (
            f"Your platform fee for {charge.period} ({amount}) is unpaid, so outgoing "
            "calls are paused."
        )
        after = "They resume as soon as the fee is paid."
    lines = [
        opening,
        "",
        after,
        "Incoming calls keep being answered either way.",
        "",
        "Pay it here:",
        "",
        f"{CONSOLE_BASE}/c/{slug}/billing",
    ]
    return "\n".join(lines)


def notice_due(charge: FeeCharge, *, now: datetime) -> Notice | None:
    """Which notice, if any, this unpaid fee is owed at `now`. The most advanced one
    wins, so a fee first seen after its grace period is told about the pause, not
    reminded about a deadline that has passed."""
    if charge.paid:
        return None
    if now >= charge.grace_ends_at:
        return "paused" if charge.paused_notice_sent_at is None else None
    if now >= charge.grace_ends_at - REMINDER_BEFORE:
        return "reminder" if charge.reminder_sent_at is None else None
    return "issued" if charge.issued_notice_sent_at is None else None


async def _claim(tenant_id: UUID, *, charge_id: UUID, notice: Notice, at: datetime) -> bool:
    column = _STAMP[notice]
    async with tenant_session(tenant_id) as session:
        claimed = (
            await session.execute(
                text(
                    f"UPDATE monthly_fee_charges SET {column} = :at, updated_at = :at "
                    f"WHERE id = :id AND {column} IS NULL RETURNING id"
                ),
                {"at": at, "id": charge_id},
            )
        ).first()
    return claimed is not None


async def _release(tenant_id: UUID, *, charge_id: UUID, notice: Notice) -> None:
    column = _STAMP[notice]
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(f"UPDATE monthly_fee_charges SET {column} = NULL WHERE id = :id"),
            {"id": charge_id},
        )


async def _send(*, address: str, notice: Notice, body: str) -> bool:
    subject = _SUBJECT[notice]
    message = from_text(
        subject=subject,
        preheader="Paid separately from your calling credit.",
        heading=subject,
        text=body,
        cta="Pay the fee",
    )
    transport = get_transport()
    # Off the event loop: the SMTP transport is synchronous (`wallet_alerts`' reason).
    return await asyncio.to_thread(
        lambda: transport.send(to=address, subject=subject, body=message.text, html=message.html)
    )


TenantOutcome = Literal["exempt", "issued", "noticed", "nothing", "no_billing_email", "send_failed"]


async def settle_tenant(tenant_id: UUID, *, amount_inr: Decimal, now: datetime) -> TenantOutcome:
    """One client's month: raise the fee if owed, then send the one notice it is due."""
    async with tenant_session(tenant_id) as session:
        if await exemption_of(session, tenant_id=tenant_id, at=now) is not None:
            return "exempt"
        issued = await issue_charge(session, tenant_id=tenant_id, amount_inr=amount_inr, at=now)
        row = (
            await session.execute(
                text("SELECT billing_email, slug FROM organizations WHERE id = :tid"),
                {"tid": tenant_id},
            )
        ).first()
        charges = await list_charges(session, tenant_id=tenant_id)
    if row is None:
        return "nothing"
    address = str(row[0]) if row[0] else None
    slug = str(row[1])
    due = [(charge, notice) for charge in charges if (notice := notice_due(charge, now=now))]
    if not due:
        return "issued" if issued else "nothing"
    if address is None:
        alert("WORKER_DELIVERY", "platform_fee_notice_no_billing_email")
        log.warning("platform_fee_notice_no_address", extra={"tenant_id": str(tenant_id)})
        return "no_billing_email"
    # The oldest unpaid fee first: it is the one pausing calls.
    charge, notice = due[-1]
    if not await _claim(tenant_id, charge_id=charge.id, notice=notice, at=now):
        return "issued" if issued else "nothing"
    if not await _send(
        address=address, notice=notice, body=compose(notice, charge=charge, slug=slug)
    ):
        await _release(tenant_id, charge_id=charge.id, notice=notice)
        log.warning(
            "platform_fee_notice_send_failed",
            extra={"tenant_id": str(tenant_id), "charge_id": str(charge.id), "notice": notice},
        )
        return "send_failed"
    log.info(
        "platform_fee_notice_sent",
        extra={"tenant_id": str(tenant_id), "charge_id": str(charge.id), "notice": notice},
    )
    return "noticed"


async def issue_platform_fees(ctx: dict[str, Any]) -> str:
    """Hourly. Raise and notify every live client's monthly platform fee while it is on."""
    del ctx
    switch = fee_switch()
    if not switch.enabled:
        return json.dumps({"enabled": False})
    if switch.amount_inr is None:
        # On without an amount: raising a fee of nothing is not a fee, and guessing one is
        # not ours to do. Nothing is raised until an operator sets the amount.
        alert(
            "WORKER_TERMINAL",
            "platform_fee_unpriced",
            detail="the monthly platform fee is switched on with no amount set",
        )
        return json.dumps({"enabled": True, "priced": False})

    now = datetime.now(UTC)
    async with admin_session() as directory:
        rows = (await directory.execute(text(_DIRECTORY))).all()
    tenant_ids = [UUID(str(row[0])) for row in rows]

    budget = WalkBudget()
    counts: dict[str, int] = {"probed": 0, "issued": 0, "noticed": 0, "exempt": 0, "failed": 0}
    for tenant_id in tenant_ids:
        if budget.spent():
            break
        counts["probed"] += 1
        try:
            outcome = await settle_tenant(tenant_id, amount_inr=switch.amount_inr, now=now)
        except Exception as exc:
            counts["failed"] += 1
            log.warning(
                "platform_fee_tenant_failed",
                extra={"tenant_id": str(tenant_id), "error": type(exc).__name__},
            )
            continue
        if outcome in ("issued", "noticed", "exempt"):
            counts[outcome] += 1
        elif outcome == "send_failed":
            counts["failed"] += 1

    unreached = len(tenant_ids) - counts["probed"]
    log.info("platform_fee_sweep", extra={**counts, "unreached": unreached})
    if unreached:
        alert(
            "WORKER_DELIVERY",
            "platform_fee_sweep_truncated",
            detail=(
                f"the platform fee sweep reached {counts['probed']} of {len(tenant_ids)} "
                "client(s) inside its time budget; the rest are asked again next hour"
            ),
        )
    if counts["failed"]:
        alert(
            "WORKER_TERMINAL",
            "platform_fees_unissued",
            detail=f"{counts['failed']} client(s); retried on the next hourly tick",
        )
    return json.dumps(counts)


__all__ = [
    "FEE_SWEEP_MINUTE",
    "compose",
    "issue_platform_fees",
    "notice_due",
    "settle_tenant",
]
