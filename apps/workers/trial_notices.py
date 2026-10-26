"""The emails a client gets about their own trial (D-685): it has started, it ends in about
a day, and (D-697) its free test minutes are used, which ends it early.

The minutes email is promised through the outbox by `workers/trials._end_if_minutes_used`
in the transaction that ends the trial, keyed on the trial (`enqueue_outbox_once`), and the
hourly sweep below asks for that ending first so it lands within the hour. The console's
trial strip already shows the minutes left and "Your free minutes are used up".

The console already says both on every screen (`app/c/[slug]/TrialBanner.tsx`); these
reach the owner who is not looking at it. Both read the trial from `billing/trials.
read_trial`, the row the operator's trial panel writes, and neither carries a figure of any
kind — what the trial costs us is the operator's (`trial_routes.TrialStatusOut`) and no
client surface shows it.

**ONCE EACH, BY A CLAIM ON THE TRIAL ROW.** `start_notice_sent_at` and
`ending_notice_sent_at` are taken with `UPDATE … WHERE <stamp> IS NULL` in a committed
transaction BEFORE the send, so a retried outbox delivery, a second worker or two hourly
ticks cannot mail twice. A send that fails releases the claim and retries. A crash between
the claim and the send loses that one email; the alternative order (send, then stamp) mails
twice on the same crash, and the console strip already says everything the email does.

**ONLY WHILE THE TRIAL IS RUNNING.** Each job re-reads the trial and sends nothing for one
that has ended, been stopped or converted, or (for the start notice) been replaced by a
newer trial — so a trial ended a minute after it opened is not announced as running.

**THE ENDING NOTICE IS AN HOURLY SWEEP**, not a deferred job queued at start: an operator
can stop a trial early or the clock can be wrong at enqueue, and a sweep re-asks the row
every hour, so the email goes out between 24 and 23 hours before `ends_at`. A trial whose
whole length is inside that window (a one-day trial) gets no ending notice: its start
notice already names the end and says what to do before it.

**NO NOTIFICATION PREFERENCE IS CONSULTED** because this product has none for account
email; the address is `organizations.billing_email`, the one `wallet_alerts` and
`rate_card_notice` mail. Hard rule 6: logs carry tenant and trial ids, never the address.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal
from uuid import UUID

from arq import Retry
from calevate_shared.backoff import ladder_delay_s
from calevate_shared.calling_window import IST
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.first_payment import has_paid
from apps.api.billing.rates import PREPAID_TIERS
from apps.api.billing.service import plan_tier_of
from apps.api.billing.trials import TrialState, read_trial
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.transport import get_transport
from apps.api.db.session import admin_session, tenant_session
from apps.workers.auth_email import CONSOLE_BASE
from apps.workers.email_render import from_text
from apps.workers.fleet_walk import WalkBudget, resumed_walk
from apps.workers.trials import _DIRECTORY, close_if_minutes_used

log = get_logger(__name__)

#: The outbox job `billing/trial_routes.open_trial` publishes. Restated there as a literal
#: for `check_job_wiring`; `tests/trial_notices_test.py` holds the two spellings equal.
TRIAL_STARTED_NOTICE_JOB: Final = "notify_trial_started"

#: How long before `ends_at` the ending notice goes out.
ENDING_NOTICE_WINDOW: Final = timedelta(hours=24)

#: The hourly sweep's minute. No other fleet-wide walk fires at :29
#: (`tests/job_registration_test.py::test_no_two_fleet_wide_walks_share_a_firing_minute`).
ENDING_SWEEP_MINUTE: Final = 29

RETRY_BACKOFF_S: tuple[float, ...] = (60.0, 300.0)

Notice = Literal["start", "ending"]

#: The column each notice claims. A closed mapping, never interpolated from input.
_STAMP: Final[dict[Notice, str]] = {
    "start": "start_notice_sent_at",
    "ending": "ending_notice_sent_at",
}


@dataclass(frozen=True, slots=True)
class Recipient:
    billing_email: str | None
    slug: str
    prepaid: bool
    #: Not yet paid, so the trial is the test-calls-only kind (D-697,
    #: `compliance/trial_access.restricting_trial`): no inbound, no calls to leads.
    restricted: bool = False


def ist_moment(instant: datetime) -> str:
    """An instant as `10 Oct 2026, 10:58 pm IST`.

    The repo's fixed-offset convention (`maintenance._ist`), with the zone named because
    the reader may not be in India.
    """
    local = instant.astimezone(UTC) + IST
    stamp = local.strftime("%d %b %Y, %I:%M %p")
    return f"{stamp[:-2]}{stamp[-2:].lower()} IST"


def _days(count: int) -> str:
    return f"{count} day" if count == 1 else f"{count} days"


def _after_the_trial(*, prepaid: bool, ends: str) -> str:
    if prepaid:
        return (
            "When the trial ends, calls are paid from your calling credit. If there is no "
            "credit then, your agents stop making outgoing calls and stop answering incoming "
            f"ones, so add credit before {ends} to keep them going."
        )
    return (
        "When the trial ends, your calls are billed on your monthly invoice as usual. "
        "There is nothing you need to do."
    )


def _link(*, prepaid: bool, slug: str) -> list[str]:
    if prepaid:
        return ["", "Add credit here:", "", f"{CONSOLE_BASE}/c/{slug}/billing?tab=credits"]
    return ["", "Your dashboard:", "", f"{CONSOLE_BASE}/c/{slug}"]


def _go_live(*, prepaid: bool) -> str:
    """How an account that has not paid yet goes live, as `TRIAL_REFUSALS` words it."""
    if prepaid:
        return (
            "Answering your business's calls and calling your leads open once you add "
            "credit and verify your business."
        )
    return (
        "Answering your business's calls and calling your leads open once your account is "
        "set up for billing. Contact us when you are ready."
    )


def _free_minutes(trial: TrialState) -> str | None:
    if trial.free_minutes is None:
        return None
    return f"{trial.free_minutes} free minute" + ("" if trial.free_minutes == 1 else "s")


def compose_started(
    *, trial: TrialState, prepaid: bool, slug: str, restricted: bool = False
) -> str:
    """The start email, in a business owner's words. No figure, no vendor name.

    `restricted` is an account that has not paid: its trial is test calls only, so telling
    it an empty balance "does not stop your agents making or answering calls" promised
    calls it cannot take.
    """
    ends = ist_moment(trial.ends_at)
    if restricted:
        minutes = _free_minutes(trial)
        until = (
            f"{ends}, or until you have used your {minutes} of test calls, whichever comes first"
            if minutes
            else ends
        )
        lines = [
            f"Your free trial has started. It runs for {_days(trial.days)}, until {until}.",
            "",
            "During the trial you can hear your agents for yourself: place test calls from "
            "your dashboard, and they are on us.",
            "",
            f"{_go_live(prepaid=prepaid)} When the trial ends, test calls stop.",
            *_link(prepaid=prepaid, slug=slug),
        ]
        return "\n".join(lines)
    lines = [
        f"Your free trial has started. It runs for {_days(trial.days)}, until {ends}.",
        "",
        "Until then, calls are on us: nothing is taken from your calling credit, and an "
        "empty balance does not stop your agents making or answering calls. Every call "
        "still shows in your usage, so you can see what the trial is doing for you.",
        "",
        _after_the_trial(prepaid=prepaid, ends=ends),
        *_link(prepaid=prepaid, slug=slug),
    ]
    return "\n".join(lines)


def compose_ending(*, trial: TrialState, prepaid: bool, slug: str, restricted: bool = False) -> str:
    """The ending email, sent about a day before `ends_at`."""
    ends = ist_moment(trial.ends_at)
    if restricted:
        minutes = _free_minutes(trial)
        sooner = f", or sooner if your {minutes} of test calls run out first" if minutes else ""
        lines = [
            f"Your free trial ends at {ends}{sooner}.",
            "",
            f"After that, test calls stop. {_go_live(prepaid=prepaid)}",
            *_link(prepaid=prepaid, slug=slug),
        ]
        return "\n".join(lines)
    if prepaid:
        after = (
            "After that, calls are paid from your calling credit. If there is no credit "
            "then, your agents stop making outgoing calls and stop answering incoming ones. "
            "Add credit now so calls carry on without a break."
        )
    else:
        after = (
            "After that, your calls are billed on your monthly invoice as usual. There is "
            "nothing you need to do."
        )
    lines = [
        f"Your free trial ends at {ends}.",
        "",
        after,
        *_link(prepaid=prepaid, slug=slug),
    ]
    return "\n".join(lines)


_COPY: Final[dict[Notice, tuple[str, str, str]]] = {
    # subject, heading, preheader
    "start": (
        "Your free trial has started",
        "Your free trial has started",
        "Calls are on us until your trial ends.",
    ),
    "ending": (
        "Your free trial ends in about a day",
        "Your free trial ends soon",
        "Here is what happens to your calls when it ends.",
    ),
}


async def _recipient(session: AsyncSession, tenant_id: UUID) -> Recipient | None:
    row = (
        await session.execute(
            text("SELECT billing_email, slug FROM organizations WHERE id = :tid"),
            {"tid": tenant_id},
        )
    ).first()
    if row is None:
        return None
    tier = await plan_tier_of(session, tenant_id)
    return Recipient(
        billing_email=str(row[0]) if row[0] else None,
        slug=str(row[1]),
        prepaid=tier in PREPAID_TIERS,
        restricted=not await has_paid(session, tenant_id=tenant_id),
    )


async def _claim(session: AsyncSession, *, trial_id: UUID, notice: Notice, at: datetime) -> bool:
    """Take this notice for this trial, or learn it was already taken. Only an ACTIVE row
    can be claimed, so a trial ended between the read and here sends nothing."""
    column = _STAMP[notice]
    claimed = (
        await session.execute(
            text(
                f"UPDATE tenant_trials SET {column} = :at, updated_at = :at "
                f"WHERE id = :id AND status = 'active' AND {column} IS NULL RETURNING id"
            ),
            {"at": at, "id": trial_id},
        )
    ).first()
    return claimed is not None


async def _release(tenant_id: UUID, *, trial_id: UUID, notice: Notice) -> None:
    column = _STAMP[notice]
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(f"UPDATE tenant_trials SET {column} = NULL WHERE id = :id"),
            {"id": trial_id},
        )


async def _send(*, recipient: Recipient, notice: Notice, body: str) -> bool:
    assert recipient.billing_email is not None
    subject, heading, preheader = _COPY[notice]
    message = from_text(
        subject=subject,
        preheader=preheader,
        heading=heading,
        text=body,
        cta="Add credit" if recipient.prepaid else "Open your dashboard",
    )
    transport = get_transport()
    address = recipient.billing_email
    # Off the event loop: the SMTP transport is synchronous (`wallet_alerts`' reason).
    return await asyncio.to_thread(
        lambda: transport.send(to=address, subject=subject, body=message.text, html=message.html)
    )


def _no_address(tenant_id: UUID, notice: Notice) -> None:
    alert("WORKER_DELIVERY", "trial_notice_no_billing_email")
    log.warning("trial_notice_no_address", extra={"tenant_id": str(tenant_id), "notice": notice})


#: The minutes-used email: subject, heading, preheader.
MINUTES_USED_COPY: Final = (
    "Your free test minutes are used",
    "Your free test minutes are used",
    "Here is how to keep going.",
)


def compose_minutes_used(*, trial: TrialState, prepaid: bool, slug: str, restricted: bool) -> str:
    """The email when a trial's free minutes run out before its end date. No figure beyond
    the minutes the client was given, no vendor name."""
    minutes = _free_minutes(trial) or "free minutes"
    lines = [
        f"You have used the {minutes} of test calls in your free trial, so the trial has ended."
    ]
    if restricted:
        lines += ["", f"To keep going: {_go_live(prepaid=prepaid)}"]
    elif prepaid:
        lines += [
            "",
            "Your calls carry on, paid from your calling credit. If there is no credit, your "
            "agents stop making and answering calls, so add credit to keep them going.",
        ]
    else:
        lines += ["", "Your calls carry on and are billed on your monthly invoice as usual."]
    lines += ["", "If you would like to talk it through first, contact us."]
    return "\n".join([*lines, *_link(prepaid=prepaid, slug=slug)])


async def notify_trial_minutes_used(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """One email when a trial ends because its free minutes are used. Published through the
    outbox by `workers/trials._end_if_minutes_used` in the transaction that ended the trial,
    keyed on the trial (`enqueue_outbox_once`), so it is promised once per trial."""
    tenant_id = UUID(str(payload["tenant_id"]))
    trial_id = UUID(str(payload["trial_id"]))
    attempt = int(ctx.get("job_try", 1))
    async with tenant_session(tenant_id) as session:
        trial = await read_trial(session, tenant_id=tenant_id)
        if trial is None or trial.id != trial_id:
            # Replaced by a newer trial since: this one's ending is no longer the news.
            return "trial_replaced"
        recipient = await _recipient(session, tenant_id)
    if recipient is None:
        return "tenant_missing"
    if not recipient.billing_email:
        alert("WORKER_DELIVERY", "trial_notice_no_billing_email")
        log.warning(
            "trial_notice_no_address", extra={"tenant_id": str(tenant_id), "notice": "minutes"}
        )
        return "no_billing_email"
    subject, heading, preheader = MINUTES_USED_COPY
    body = compose_minutes_used(
        trial=trial,
        prepaid=recipient.prepaid,
        slug=recipient.slug,
        restricted=recipient.restricted,
    )
    message = from_text(
        subject=subject,
        preheader=preheader,
        heading=heading,
        text=body,
        cta="Add credit" if recipient.prepaid else "Open your dashboard",
    )
    transport = get_transport()
    address = recipient.billing_email
    delivered = await asyncio.to_thread(
        lambda: transport.send(to=address, subject=subject, body=message.text, html=message.html)
    )
    if not delivered:
        log.warning(
            "trial_notice_send_failed",
            extra={"tenant_id": str(tenant_id), "notice": "minutes", "attempt": attempt},
        )
        raise Retry(defer=ladder_delay_s(RETRY_BACKOFF_S, attempt))
    log.info("trial_notice_sent", extra={"tenant_id": str(tenant_id), "notice": "minutes"})
    return "sent"


async def notify_trial_started(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """One start email for one trial. Published by `trial_routes.open_trial` through the
    outbox, in the transaction that opened the trial."""
    tenant_id = UUID(str(payload["tenant_id"]))
    trial_id = UUID(str(payload["trial_id"]))
    attempt = int(ctx.get("job_try", 1))
    now = datetime.now(UTC)

    async with tenant_session(tenant_id) as session:
        trial = await read_trial(session, tenant_id=tenant_id)
        if trial is None or trial.id != trial_id or not trial.is_active(at=now):
            return "trial_not_active"
        recipient = await _recipient(session, tenant_id)
        if recipient is None:
            return "tenant_missing"
        if not recipient.billing_email:
            _no_address(tenant_id, "start")
            return "no_billing_email"
        if not await _claim(session, trial_id=trial_id, notice="start", at=now):
            return "already_sent"

    body = compose_started(
        trial=trial,
        prepaid=recipient.prepaid,
        slug=recipient.slug,
        restricted=recipient.restricted,
    )
    if not await _send(recipient=recipient, notice="start", body=body):
        await _release(tenant_id, trial_id=trial_id, notice="start")
        log.warning(
            "trial_notice_send_failed",
            extra={"tenant_id": str(tenant_id), "notice": "start", "attempt": attempt},
        )
        raise Retry(defer=ladder_delay_s(RETRY_BACKOFF_S, attempt))
    log.info("trial_notice_sent", extra={"tenant_id": str(tenant_id), "notice": "start"})
    return "sent"


EndingOutcome = Literal[
    "none", "not_yet", "too_short", "no_billing_email", "already_sent", "sent", "send_failed"
]


async def notify_ending_if_due(tenant_id: UUID, *, now: datetime) -> EndingOutcome:
    """Send this tenant's ending notice if their running trial ends within the window."""
    async with tenant_session(tenant_id) as session:
        trial = await read_trial(session, tenant_id=tenant_id)
        if trial is None or not trial.is_active(at=now):
            return "none"
        if trial.ends_at - now > ENDING_NOTICE_WINDOW:
            return "not_yet"
        if trial.ends_at - trial.started_at <= ENDING_NOTICE_WINDOW:
            return "too_short"
        recipient = await _recipient(session, tenant_id)
        if recipient is None:
            return "none"
        if not recipient.billing_email:
            # Before the claim, so the email still goes out on the next tick inside the
            # window once somebody sets the address.
            _no_address(tenant_id, "ending")
            return "no_billing_email"
        if not await _claim(session, trial_id=trial.id, notice="ending", at=now):
            return "already_sent"

    body = compose_ending(
        trial=trial,
        prepaid=recipient.prepaid,
        slug=recipient.slug,
        restricted=recipient.restricted,
    )
    if not await _send(recipient=recipient, notice="ending", body=body):
        # Released, so the next hourly tick inside the window tries again.
        await _release(tenant_id, trial_id=trial.id, notice="ending")
        log.warning(
            "trial_notice_send_failed", extra={"tenant_id": str(tenant_id), "notice": "ending"}
        )
        return "send_failed"
    log.info("trial_notice_sent", extra={"tenant_id": str(tenant_id), "notice": "ending"})
    return "sent"


async def send_trial_ending_notices(ctx: dict[str, Any]) -> str:
    """Hourly. One `tenant_session` per organisation, under a time budget, as
    `trials.sweep_trials` walks; a failing tenant does not stop the rest."""
    del ctx
    now = datetime.now(UTC)
    async with admin_session() as directory:
        rows = (await directory.execute(text(_DIRECTORY))).all()
    tenant_ids = [UUID(str(row[0])) for row in rows]

    budget = WalkBudget()
    sent = failed = probed = 0
    async for tenant_id in resumed_walk("trial_notices", tenant_ids, budget):
        probed += 1
        try:
            # First, so a trial whose free minutes ran out is ended (and its one email
            # promised) within the hour rather than at the next daily trial sweep.
            if await close_if_minutes_used(tenant_id, now=now):
                continue
            outcome = await notify_ending_if_due(tenant_id, now=now)
        except Exception:
            failed += 1
            log.exception("trial_ending_notice_failed", extra={"tenant_id": str(tenant_id)})
            continue
        if outcome == "sent":
            sent += 1
        elif outcome == "send_failed":
            failed += 1

    unreached = len(tenant_ids) - probed
    log.info(
        "trial_ending_sweep",
        extra={"sent": sent, "failed": failed, "probed": probed, "unreached": unreached},
    )
    if unreached:
        alert(
            "WORKER_DELIVERY",
            "trial_ending_sweep_truncated",
            detail=(
                f"the trial-ending notice sweep reached {probed} of {len(tenant_ids)} "
                "tenant(s) inside its time budget; the rest are asked again next hour"
            ),
        )
    if failed:
        alert("WORKER_DELIVERY", "trial_ending_notice_failed", detail=f"{failed} tenants")
    return f"sent={sent} failed={failed} probed={probed}"


__all__ = [
    "ENDING_NOTICE_WINDOW",
    "ENDING_SWEEP_MINUTE",
    "TRIAL_STARTED_NOTICE_JOB",
    "compose_ending",
    "compose_minutes_used",
    "compose_started",
    "ist_moment",
    "notify_ending_if_due",
    "notify_trial_minutes_used",
    "notify_trial_started",
    "send_trial_ending_notices",
]
