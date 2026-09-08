"""Telling an owner their calling credit is running out — BEFORE the calls stop.

The founder's decision of 2 Sep 2026, in one sentence: warn early in the dashboard AND by
email, stop OUTBOUND dialling at zero, and keep ANSWERING the phone whatever the balance
is. This module is the email half. The dashboard half is `billing/wallet_routes.py`, and
the stopping is `compliance.service.credits_exhausted` — which this job does not call,
does not re-derive and cannot influence. Nothing here gates a call.

**WHY THERE IS NO CRON AND NO "ALREADY WARNED" TABLE.**

The obvious build is a sweep that walks every tenant, compares each balance with a
threshold and remembers who it has told. It needs a clock, a fan-out, and durable state
whose only job is to stop the sweep mailing the same client every hour — and that state
then has to be cleared when they top up, by a writer that must not forget.

None of it is necessary, because the interesting thing is not the BALANCE, it is the
MOVEMENT. `billing.service.record_entry` is the single writer of every credit movement in
this product, and it knows both sides of the one it is making. The entry that takes a
wallet from ₹250 to ₹150 is the only entry that will ever cross the warning line going
down, so publishing on the crossing warns exactly once per episode by construction
(`billing.service.crossed_downwards`). Top up and fall again and there is a second
crossing, which is genuinely a second thing to be told about.

It arrives here through the OUTBOX (BACKEND-PATTERNS §4), so the promise to warn shares a
transaction with the ledger row that earned it: a rolled-back charge cannot leave a
warning behind, and a committed one cannot lose it.

**THIS JOB MAY RUN TWICE AND THAT IS ACCEPTED, NOT OVERLOOKED.** The outbox is
at-least-once; a delivery that fails halfway is retried. The cost of a duplicate is one
repeated warning email, and the cost of the alternative — a delivery record written before
the send, so a crash silences the warning — is a client whose calls stop with no notice.
For a warning, the duplicate is the cheaper failure. Nothing in this module writes to the
ledger, so no rupee is at risk either way.

Hard rule 6: the log lines carry the tenant id and the level. Not the balance, not the
address.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from decimal import Decimal
from typing import Any
from uuid import UUID

from arq import Retry
from sqlalchemy import text

from apps.api.billing.rates import PREPAID_TIERS
from apps.api.billing.service import (
    WALLET_LEVEL_EMPTY,
    WALLET_LEVEL_LOW,
    plan_tier_of,
    to_paise,
)
from apps.api.billing.wallet import TierMinutes, tier_minutes
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.db.session import tenant_session
from apps.workers.auth_email import CONSOLE_BASE
from apps.workers.email_render import from_text
from apps.workers.transport import get_transport

log = get_logger(__name__)

#: Seconds to wait before each retry, indexed by the attempt that just failed. One entry
#: shorter than the budget, because the last attempt has nothing after it — the shape
#: `notifications.RETRY_BACKOFF_S` established. Slower than the hot-lead ladder on
#: purpose: this warning has no two-minute SLO behind it, and a mail server that is down
#: is better waited out than hammered.
RETRY_BACKOFF_S: tuple[float, ...] = (60.0, 300.0)

SUBJECT = {
    WALLET_LEVEL_EMPTY: "Your calling credit has run out",
    WALLET_LEVEL_LOW: "Your calling credit is running low",
}

HEADING = {
    WALLET_LEVEL_EMPTY: "Outgoing calls have stopped",
    WALLET_LEVEL_LOW: "Your calling credit is running low",
}

PREHEADER = {
    WALLET_LEVEL_EMPTY: "People calling you still get through. Add credit to start "
    "making calls again.",
    WALLET_LEVEL_LOW: "Add credit before your outgoing calls stop.",
}


def _retry_after(attempt: int) -> float:
    index = min(attempt, len(RETRY_BACKOFF_S)) - 1
    return RETRY_BACKOFF_S[max(index, 0)]


def _runway_sentence(minutes_left: Sequence[TierMinutes]) -> str:
    """The runway clause: "That is about 620 more minutes of calling on Clear, or 430 on
    Studio."

    ONE SENTENCE PER VOICE QUALITY, in the client's own words for them (D-547): a wallet is
    a queue of purchases, each priced at what it was sold at and at a different rate per
    quality, so "N minutes left" is not answerable without saying on WHICH voice. The
    labels arrive already resolved (`billing/rates.voice_tier_label`, through
    `wallet.tier_minutes`) — no vendor name has ever appeared on a client surface and this
    email is not where the first one arrives.

    EMPTY WHEN EVERY FIGURE IS ZERO, rather than promising nothing. A LOW warning quotes a
    balance the client still holds, and "you have ₹150" followed by "about 0 more minutes"
    is a contradiction they cannot act on — it means the lots could not answer, not that
    the money buys nothing. Written generically over the qualities rather than as two
    branches, so a third tier reads correctly the day it exists.
    """
    if not minutes_left or all(tier.minutes == 0 for tier in minutes_left):
        return ""
    first, *rest = minutes_left
    lead = f"{first.minutes:,} more minutes of calling on {first.label}"
    tail = "".join(f", or {tier.minutes:,} on {tier.label}" for tier in rest)
    return f" That is about {lead}{tail}."


def compose(
    *, level: str, balance_inr: Decimal, minutes_left: Sequence[TierMinutes] | None, slug: str
) -> str:
    """The email body, in a business owner's words.

    **THE FIRST SENTENCE OF THE EMPTY-WALLET MAIL IS THE ONE THAT MATTERS**, and it is the
    reassurance rather than the warning: a clinic owner who reads "your credit has run out"
    on a phone at 8pm concludes their phone has stopped being answered, and that is the
    single most expensive wrong belief this product can create. It has not — the founder's
    decision is that inbound is never stopped by a wallet — so the mail says so before it
    says anything else.

    Nothing here is a code, an identifier, or our vocabulary: no "tier", no "ledger", no
    "self_serve", no reason string, and no VENDOR name — a client reads "Clear" and
    "Studio". The reader is a small-business owner, not an operator.
    """
    money = f"₹{to_paise(balance_inr)}"
    lines: list[str] = []
    if level == WALLET_LEVEL_EMPTY:
        lines += [
            "People who call your business still get through — answering calls does not "
            "use your credit, and it never stops.",
            "",
            "What has stopped is your outgoing calls: your calling credit is now "
            f"{money}, so campaigns and call-backs are paused until you add more.",
        ]
    else:
        runway = _runway_sentence(minutes_left or ())
        lines += [
            f"Your calling credit is down to {money}.{runway}",
            "",
            "When it reaches zero your outgoing calls stop. People calling you still get "
            "through — answering calls does not use your credit.",
        ]
    lines += [
        "",
        "Add credit here:",
        f"{CONSOLE_BASE}/c/{slug}/credits",
    ]
    return "\n".join(lines)


async def notify_low_balance(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """One warning email for one crossing.

    Two questions are answered HERE rather than at the ledger, and both for the same
    reason — they are still true a minute later, and asking them on the hottest money
    write in the product would buy nothing:

    1. **Does this tenant have a wallet worth warning about?** A managed client is
       invoiced against a retainer and is never stopped by a balance
       (`compliance.service.credits_exhausted` draws the same line, off the same
       constant), so warning them about one would be a sentence about nothing.
    2. **Is there anyone to warn?** `organizations.billing_email` is the address of
       record. An empty one is a DATA fix — it will be just as empty in five minutes — so
       it is alerted immediately instead of burning the retry ladder to reach the same
       verdict, which is the split `notifications.py` argues for.
    """
    tenant_id = UUID(str(payload["tenant_id"]))
    level = str(payload["level"])
    # The balance AS THE LEDGER WROTE IT, carried as digits and rebuilt as a Decimal —
    # never `float(payload[...])` (hard rule 7). It is the balance at the moment of the
    # crossing rather than a fresh read on purpose: this mail describes the movement that
    # earned it, and re-reading would let a top-up that landed in between produce a
    # warning quoting a balance nobody was ever at.
    balance_inr = Decimal(str(payload["balance_inr"]))
    attempt = int(ctx.get("job_try", 1))

    async with tenant_session(tenant_id) as session:
        tier = await plan_tier_of(session, tenant_id)
        if tier not in PREPAID_TIERS:
            return "not_prepaid"
        row = (
            await session.execute(
                text("SELECT billing_email, slug FROM organizations WHERE id = :tid"),
                {"tid": tenant_id},
            )
        ).first()
        # THE RUNWAY, FROM THE LOTS, on the session that is already open — the same
        # function the credits screen this email links to renders from
        # (`billing/wallet.tier_minutes`), so the two cannot quote different minutes for
        # one wallet.
        #
        # ⚠ **IT IS READ NOW, WHILE THE BALANCE ABOVE IS THE ONE AT THE CROSSING**, and the
        # asymmetry is deliberate. The balance describes the movement that earned this mail
        # and must not be re-read (a top-up landing in between would make it quote a figure
        # nobody was ever at). The minutes are not a figure the crossing fixes: they are
        # what the wallet buys, which depends on which lots are still open — so the honest
        # answer is the current queue. In the ordinary case they are microseconds apart;
        # when they are not, the client has just topped up and the larger runway is the
        # true one.
        runway = await tier_minutes(session, tenant_id=tenant_id) if row is not None else ()
    if row is None:
        # The tenant went away between the ledger write and this send. Nothing to do and
        # nothing wrong: an erasure does exactly this.
        return "tenant_missing"
    billing_email, slug = row

    if not billing_email:
        # NOT a retry. The row will be just as empty in five minutes, and burning the
        # ladder to discover that hides the real problem — which is that a client whose
        # calling is about to stop has no address on file.
        alert("WORKER_DELIVERY", "wallet_alert_no_billing_email")
        log.warning("wallet_alert_no_address", extra={"tenant_id": str(tenant_id)})
        return "no_billing_email"

    body = compose(
        level=level,
        balance_inr=balance_inr,
        minutes_left=runway,
        slug=str(slug),
    )
    message = from_text(
        subject=SUBJECT[level],
        preheader=PREHEADER[level],
        heading=HEADING[level],
        text=body,
        cta="Add credit",
    )
    transport = get_transport()
    # OFF THE EVENT LOOP (`notifications._send_email`'s finding, D-159's class): the SMTP
    # transport is synchronous socket I/O on a timeout budget, and returning it directly
    # from an `async def` reads as deferred while stalling every other job on this worker
    # — including the outbox dispatcher and the campaign tick.
    delivered = await asyncio.to_thread(
        lambda: transport.send(
            to=str(billing_email), subject=SUBJECT[level], body=message.text, html=message.html
        )
    )
    if not delivered:
        # `arq.Retry` and not a plain raise: arq retries a job for `Retry`, `RetryJob` or
        # `CancelledError` and nothing else, so raising anything else here would be
        # terminal on the first attempt and `max_tries` decorative
        # (`apps/workers/outbound_webhooks.py` documents the mechanism).
        log.warning(
            "wallet_alert_send_failed",
            extra={"tenant_id": str(tenant_id), "level": level, "attempt": attempt},
        )
        raise Retry(defer=_retry_after(attempt))

    log.info("wallet_alert_sent", extra={"tenant_id": str(tenant_id), "level": level})
    return "sent"


__all__ = ["RETRY_BACKOFF_S", "compose", "notify_low_balance"]
