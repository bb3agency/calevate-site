"""Telling every client with a wallet that the credit-pack rates are changing — BEFORE they do.

The founder's decision of 8 Sep 2026, in one sentence: a new rate card is dated at least
thirty days out (`billing/list_rates.CARD_NOTICE_DAYS`), and every client whose top-ups it
would price is told when it is RECORDED, not when it takes effect. A notice that arrives on
the morning the price moves is not notice.

═══ WHAT THE EMAIL HAS TO SAY, AND THE SENTENCE THAT STOPS A SUPPORT CALL ═══

Three things: the new per-minute rates on both voice qualities, the date they start, and —
the part everyone will actually write in about — that credit they have ALREADY BOUGHT keeps
the rates it was bought at. That last one is not reassurance, it is how the product works:
`credit_lots` freezes a purchase's two ₹/min figures onto the lot it opens, and every minute
is debited against the lot it is spent from, so a later card cannot reach money already
paid (Terms §6.1 promises exactly this, and the lot is what makes the promise structural
rather than a policy somebody has to remember).

No rupee figure in this module is a literal. Every rate is read back from the card being
announced (`list_rates.card_at` at that card's own instant), so an email cannot quote a
price the platform will not charge.

═══ WHY TWO JOBS ═══

`fan_out_rate_card_notice` is the promise the ops console makes in the same transaction as
the card (`enqueue_outbox_once`, keyed on the date, so a retried outbox delivery cannot mail
the whole book twice). It enqueues one CHILD promise per client, keyed on the date AND the
tenant, which is what makes the fan-out itself idempotent: a parent that is retried after
enqueuing half its children converges on exactly one notice each, decided by a unique index
rather than by the parent remembering how far it got.

`notify_rate_card_change` sends one email to one client. A client that fails is one client
that failed — `account_closure.sweep_due_erasures`' shape, for its reason: one bad row must
not silently swallow the notice for every account behind it.

═══ WHO IS EXCLUDED, AND ON WHAT EVIDENCE ═══

MANAGED (invoiced) clients. Their rates are negotiated and live in their `plans` row; the
credit-pack card does not price them, so telling them their prices are changing would be
false. The line is drawn with `billing/rates.PREPAID_TIERS` — the same constant
`compliance.service.credits_exhausted` and `wallet_alerts.notify_low_balance` draw it with —
never with a literal, because three copies of "who has a wallet" is how one of them drifts.

═══ HARD RULE 6 ═══

No log line here carries an address, a business name or a rupee figure. Tenant ids and the
recipient's DOMAIN (`transport._domain`), which is what that helper exists for.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Final
from uuid import UUID
from zoneinfo import ZoneInfo

from arq import Retry
from sqlalchemy import text

from apps.api.billing.credit_packs import PACK_CATALOGUE
from apps.api.billing.list_rates import card_at
from apps.api.billing.rates import PREPAID_TIERS, VOICE_TIERS, VoiceTier, voice_tier_label
from apps.api.billing.service import plan_tier_of, to_paise
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.transport import _domain, get_transport
from apps.api.crm.performance import IST_ZONE
from apps.api.db.session import admin_session, tenant_session, untenanted_session
from apps.api.reliability.service import enqueue_outbox_once
from apps.workers.auth_email import CONSOLE_BASE
from apps.workers.email_render import from_text

log = get_logger(__name__)

#: The ARQ function name for the per-client half, registered in
#: `apps/workers/settings.FUNCTIONS`. The outbox dispatcher publishes `job` verbatim, so
#: this string IS the contract with the worker (`scripts/check_job_wiring.py` is the gate).
#: The fan-out's own name is `ops/config_routes.RATE_CARD_NOTICE_JOB`, declared beside the
#: route that enqueues it, exactly as `compliance/tenant_erasure.py` declares its own.
NOTICE_JOB: Final = "notify_rate_card_change"

#: How many clients one fan-out tick will enqueue for. Bounded like every sweep in this
#: fleet. It is a number WE provision — the count of accounts that have signed — not a
#: caller's row count, and a book longer than this is a fact an operator has to know about
#: rather than one a job may quietly truncate, so overflow is ALERTED and not paged past:
#: the notice is a commitment with a date on it and a client silently missed from it is the
#: failure this whole module exists to prevent.
FANOUT_BUDGET: Final = 2000

#: Seconds before each retry, indexed by the attempt that just failed — one shorter than the
#: budget, because the last attempt has nothing after it (`wallet_alerts.RETRY_BACKOFF_S`'
#: shape). Paced slowly: nobody is on a screen waiting for this, and the date it carries is
#: thirty days out.
RETRY_BACKOFF_S: tuple[float, ...] = (60.0, 300.0)

SUBJECT: Final = "Your Calevate calling rates are changing"
HEADING: Final = "New calling rates from {date}"
PREHEADER: Final = "Credit you have already bought is not affected."

_IST_TZ = ZoneInfo(IST_ZONE)

#: Every tenant that has a wallet, with the address of record. Ordered by id so a budget
#: that truncates truncates the same way twice and an operator comparing two ticks is
#: comparing the same list.
_WALLET_TENANTS = (
    "SELECT id, plan_tier FROM organizations "
    "WHERE billing_email IS NOT NULL AND billing_email <> '' "
    "ORDER BY id LIMIT :limit"
)

_ORG = "SELECT billing_email, slug FROM organizations WHERE id = :tid"


@dataclass(frozen=True, slots=True)
class PackRates:
    """One pack rung as the client will read it: what it costs, and the two rates it buys at."""

    amount_inr: Decimal
    rates: tuple[tuple[str, Decimal], ...]


def pack_rates(cells: dict[str, dict[VoiceTier, Decimal]]) -> tuple[PackRates, ...]:
    """The card as rungs, in the order a client buys along — cheapest first.

    The AMOUNT comes from `PACK_CATALOGUE` and the RATES come from the card, and the split
    is not an oversight: `platform_list_rates` dates ₹/min cells and nothing else, so what a
    pack costs is the catalogue's own fact (`billing/service.RateCard` takes the same
    reading). The voice NAMES come from `rates.voice_tier_label` — a client reads "Clear"
    and "Studio", never a vendor name, and this email is not where the first one arrives.
    """
    return tuple(
        PackRates(
            amount_inr=pack.amount_inr,
            rates=tuple(
                (voice_tier_label(voice), cells[pack.pack_id][voice]) for voice in VOICE_TIERS
            ),
        )
        for pack in sorted(PACK_CATALOGUE, key=lambda pack: pack.amount_inr)
    )


def compose(*, starts_on: str, rungs: Sequence[PackRates], slug: str) -> str:
    """The email body, in a business owner's words.

    **THE SECOND PARAGRAPH IS THE ONE THAT MATTERS**, and it is the one that stops the
    support call: a client who reads "your rates are going up" assumes the credit sitting in
    their account just lost value. It has not, and it cannot — every purchase froze its own
    rates when it was made — so the mail says so before it lists anything.

    Nothing here is a code, an identifier or our vocabulary: no "tier", no "pack id", no
    "lot", no vendor name. The reader runs a clinic, not a billing system.
    """
    lines = [
        f"From {starts_on}, the per-minute rates for new calling credit are changing.",
        "",
        "Credit you have already bought is NOT affected. Every top-up keeps the rates it "
        "was bought at for as long as that credit lasts, so nothing you have already paid "
        "for changes price. The new rates below apply only to credit you buy on or after "
        f"{starts_on}.",
        "",
        "The new rates:",
    ]
    for rung in rungs:
        priced = ", ".join(f"₹{to_paise(rate)}/min on {label}" for label, rate in rung.rates)
        lines.append(f"  ₹{to_paise(rung.amount_inr)} of credit — {priced}")
    lines += [
        "",
        f"If you want to buy credit at today's rates, you can do so any time before {starts_on}:",
        f"{CONSOLE_BASE}/c/{slug}/credits",
    ]
    return "\n".join(lines)


def _retry_after(attempt: int) -> float:
    index = min(attempt, len(RETRY_BACKOFF_S)) - 1
    return RETRY_BACKOFF_S[max(index, 0)]


def _starts_on(effective_from: datetime) -> str:
    """The date a client reads: IST, spelled out. UTC in the DB, IST at the edge — and an
    email is an edge. A client in Hyderabad reading "14 October" must not be told "13
    October" because the instant was rendered in the server's zone."""
    return effective_from.astimezone(_IST_TZ).strftime("%-d %B %Y")


def _aware(value: str) -> datetime:
    """The payload's instant, re-aware. `datetime.fromisoformat` keeps the offset the route
    wrote; a payload that somehow lost it would resolve a card in the process's timezone,
    so it is refused rather than assumed."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("a rate card notice carries an aware instant")
    return parsed


async def fan_out_rate_card_notice(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """One promise per client with a wallet, for one recorded card.

    **THE FAN-OUT IS ITSELF IDEMPOTENT AND DOES NOT REMEMBER HOW FAR IT GOT.** Each child is
    `enqueue_outbox_once` keyed on `(date, tenant)`, so a parent retried after enqueuing half
    the book converges on exactly one notice each — decided by a unique index rather than by
    a cursor this job would have to keep, and would have to keep correctly across a crash.

    The two stores are touched in SEQUENCE and never at once: `db/session.py` runs
    `max_overflow=0` and is safe only because no path holds two sessions, so the tenant
    directory is read and closed before the outbox is written.
    """
    # PARSED AND DISCARDED, DELIBERATELY: the instant is not needed here (the children
    # carry it verbatim), but a payload whose date is malformed or naive must fail on the
    # PARENT rather than on every one of its children, an hour of retries later.
    _aware(str(payload["effective_from"]))
    async with admin_session() as directory:
        rows = (await directory.execute(text(_WALLET_TENANTS), {"limit": FANOUT_BUDGET})).all()
    prepaid = [UUID(str(row[0])) for row in rows if str(row[1]) in PREPAID_TIERS]
    if len(rows) == FANOUT_BUDGET:
        # NOT a silent truncation. The notice is a commitment with a date on it; a client
        # missed from it is the exact failure this module exists to prevent, so the budget
        # being reached is something an operator is told about rather than something they
        # find by being asked why they were never told.
        alert("WORKER_DELIVERY", "rate_card_notice_fanout_budget_reached")
        log.warning("rate_card_notice_budget", extra={"budget": FANOUT_BUDGET})
    enqueued = 0
    async with untenanted_session() as session:
        for tenant_id in prepaid:
            message = await enqueue_outbox_once(
                session,
                job=NOTICE_JOB,
                payload={"tenant_id": str(tenant_id), "effective_from": payload["effective_from"]},
                dedupe_key=f"rate-card-notice:{payload['effective_from']}:{tenant_id}",
            )
            enqueued += message is not None
    log.info(
        "rate_card_notice_fanned_out",
        extra={"prepaid": len(prepaid), "enqueued": enqueued},
    )
    return f"enqueued:{enqueued}"


async def notify_rate_card_change(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """One notice for one client.

    The plan tier is re-read HERE rather than trusted from the fan-out for
    `wallet_alerts.notify_low_balance`'s reason: it is still true a minute later, and an
    account that moved onto an invoiced plan between the fan-out and this send must not be
    told about a card that does not price them.
    """
    tenant_id = UUID(str(payload["tenant_id"]))
    effective_from = _aware(str(payload["effective_from"]))
    attempt = int(ctx.get("job_try", 1))

    async with tenant_session(tenant_id) as session:
        if await plan_tier_of(session, tenant_id) not in PREPAID_TIERS:
            return "not_prepaid"
        row = (await session.execute(text(_ORG), {"tid": tenant_id})).first()
        if row is None:
            # The tenant went away between the fan-out and this send. Nothing to do and
            # nothing wrong: an erasure does exactly this.
            return "tenant_missing"
        # THE CARD BEING ANNOUNCED, resolved at its OWN instant — not the one in force now,
        # and not the twelve rows the console posted. `card_at` applies carry-forward and
        # the per-cell catalogue fallback, so what the client is quoted is what a purchase
        # made that morning will actually freeze onto its lot.
        cells = await card_at(session, at=effective_from)
    billing_email, slug = row
    if not billing_email:
        # NOT a retry: the row will be just as empty in five minutes, and burning the ladder
        # to discover that hides the real problem — a client whose prices are changing has
        # no address on file (`wallet_alerts` argues the same split).
        alert("WORKER_DELIVERY", "rate_card_notice_no_billing_email")
        log.warning("rate_card_notice_no_address", extra={"tenant_id": str(tenant_id)})
        return "no_billing_email"

    starts_on = _starts_on(effective_from)
    body = compose(
        starts_on=starts_on,
        rungs=pack_rates({pack: dict(voices) for pack, voices in cells.items()}),
        slug=str(slug),
    )
    message = from_text(
        subject=SUBJECT,
        preheader=PREHEADER,
        heading=HEADING.format(date=starts_on),
        text=body,
        cta="View credit",
    )
    transport = get_transport()
    # OFF THE EVENT LOOP (D-159's class): the SMTP transport is synchronous socket I/O on a
    # timeout budget, and awaiting it inline stalls every other job on this worker.
    delivered = await asyncio.to_thread(
        lambda: transport.send(
            to=str(billing_email), subject=SUBJECT, body=message.text, html=message.html
        )
    )
    if not delivered:
        # `arq.Retry` and not a plain raise: arq retries a job for `Retry`, `RetryJob` or
        # `CancelledError` and nothing else, so anything else here is terminal on the first
        # attempt and `max_tries` decorative (`outbound_webhooks.py` documents it).
        log.warning(
            "rate_card_notice_send_failed",
            extra={
                "tenant_id": str(tenant_id),
                "recipient_domain": _domain(str(billing_email)),
                "attempt": attempt,
            },
        )
        raise Retry(defer=_retry_after(attempt))
    log.info("rate_card_notice_sent", extra={"tenant_id": str(tenant_id)})
    return "sent"


__all__ = [
    "FANOUT_BUDGET",
    "NOTICE_JOB",
    "RETRY_BACKOFF_S",
    "PackRates",
    "compose",
    "fan_out_rate_card_notice",
    "notify_rate_card_change",
    "pack_rates",
]
