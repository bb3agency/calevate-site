"""The prepaid wallet, as its owner reads it: how much, how long, where it went.

**WHY THIS MODULE EXISTS AND WHAT IT DELIBERATELY DOES NOT DO.**

The wallet already had an ADMIN read (`credit_routes.read_credits`) and no client one, so
the person whose money it is could not see their own balance, their own ledger, or the
payment that failed last night. This is that read. It is a READ-ONLY module: nothing here
writes, nothing here decides whether a call may be placed, and there is no second credit
check anywhere in it. `compliance.service.credits_exhausted` is the one gate and this
module ASKS it (`WalletSummary.outbound_stopped`) rather than re-deriving the same
comparison a second time — the defect `SELF_SERVE_TIERS` was extracted to end.

**THE THREE NUMBERS AN OWNER ACTUALLY WANTS, and the honesty rule each one carries.**

1. **How long will this last.** A rupee balance means nothing to a clinic owner; "about
   nine days" does. It is computed from THIS ACCOUNT'S OWN DEBITS over a trailing window
   (`BURN_WINDOW_DAYS`) — never from a list rate, never from a fleet average — and when
   there is not enough history to divide by, the answer is `None` and the screen says so.
   A projection invented out of two days of data is worse than no projection, because it
   is the number the owner plans around.

2. **Minutes of calling.** The other half of the same question, and the one that is
   answerable on day one: the balance at the live list rate. It comes from
   `service.prepaid_minutes_left`, which is the SAME function `usage_summary` calls, so
   the runway on this screen and the runway on the usage screen cannot disagree.

3. **Where it went.** The debits of the trailing window, split by what caused them. The
   split is over `credit_ledger` rather than `usage_events` because this screen is about
   the WALLET: what a client wants explained is why the balance moved, and the ledger is
   the only place that is authoritative.

   **THERE ARE EXACTLY THREE OUTGOING BUCKETS, AND MESSAGING IS NOT ONE.** Calls
   (`reason='usage'` with no meta kind — `service.charge_for_call`), AI assistance
   (`reason='usage'` with `meta->>'kind' = ai_quota.OVERAGE_META_KIND` — a block of extra
   dashboard-AI allowance the owner chose to buy), and operator adjustments. Messaging is
   NOT billed to the wallet on this platform — no writer anywhere debits credits for a
   WhatsApp message or an SMS — so a "Messaging" row reading ₹0.00 would be a category
   invented to look complete, and a client who saw it would reasonably conclude they are
   being charged for messages. The screen says which things draw the wallet down instead.

**MONEY NEVER LEAVES THIS PROCESS AS ANYTHING BUT AN EXACT DECIMAL** (hard rule 7). Every
figure below is `Decimal`, summed in SQL over `NUMERIC`, quantized once through
`service.to_paise`, and published as a string. No arithmetic on any of it happens in a
browser — which is why the breakdown is summed here rather than by subtracting rows on a
screen.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.ai_quota import OVERAGE_META_KIND
from apps.api.billing.service import (
    Balance,
    CreditTotals,
    credit_totals,
    get_balance,
    prepaid_minutes_left,
)
from apps.api.billing.trials import TrialState, read_trial
from apps.api.core.logging import get_logger

log = get_logger(__name__)

#: How far back the burn rate and the breakdown look.
#:
#: THIRTY DAYS, NOT A BILLING MONTH, and the difference is the whole point of the number.
#: A billing month answers "what will I be invoiced"; this answers "at the rate I am
#: going, when do I run out", and on the 2nd of a month a month-to-date rate is computed
#: from one day. A trailing window is the same length of evidence on every day of the
#: month, which is what makes the projection stable enough to plan around.
BURN_WINDOW_DAYS: Final = 30

#: The least history that may be divided by.
#:
#: Below this the answer is "not enough yet" and the screen says so. Seven days because
#: calling is WEEKLY-seasonal for the businesses this product sells to — a clinic is busy
#: on Saturday and shut on Sunday — so a window shorter than a week projects the day it
#: happened to cover. It is a floor on the OBSERVATION PERIOD (how long we have been
#: watching), never on the number of entries: an account that made two calls in three
#: weeks has plenty of history and a very low burn, and that is a true answer.
MIN_BURN_HISTORY_DAYS: Final = 7

#: The ceiling put on a projected runway before it is published.
#:
#: An account that spent ₹3 last month and holds ₹5,000 projects to years, and "your
#: credit lasts until 2029" is a true division and a useless sentence — it also invites an
#: owner to stop watching a balance that a single busy week can empty. Beyond this the
#: screen says "more than a year" rather than a figure.
MAX_RUNWAY_DAYS: Final = 365

#: How many top-up attempts and ledger entries one read may return. Bounded because every
#: list in this repository is (`scripts/check_list_bounds.py`); the ledger's own page size
#: matches `credit_routes.DEFAULT_LIMIT` so the client's ledger and the operator's show the
#: same depth of history and a support call is not two different screens.
LEDGER_LIMIT: Final = 50
ATTEMPT_LIMIT: Final = 10

#: How long an attempt with no outcome is still worth showing as "settling" rather than as
#: something that quietly did not happen.
#:
#: Razorpay's own retry ladder for a webhook it could not deliver runs for hours, and a UPI
#: collect request can sit unanswered while the payer finds their phone, so a few minutes
#: would call a live payment dead. A day is past every one of those and is still inside the
#: span in which an owner remembers paying.
PENDING_GRACE_HOURS: Final = 24


@dataclass(frozen=True, slots=True)
class Runway:
    """How long the balance lasts, and how confident we are entitled to be about it.

    `days` is `None` whenever it may not be asserted, and `basis` says WHICH reason —
    because "you have not been using this long enough for us to tell" and "you are not
    spending anything" are different sentences to a person deciding whether to top up.
    """

    #: `projected` — a real division of the balance by an observed daily burn.
    #: `no_burn` — enough history, and nothing has been spent in the window.
    #: `too_new` — fewer than `MIN_BURN_HISTORY_DAYS` of history to divide by.
    #: `empty` — the balance is zero or below; there is no runway to project.
    basis: str
    #: Whole days, floored (a partial day is not a day you can plan a campaign in), or
    #: `None` on every basis but `projected`.
    days: int | None
    #: What this account spent per day over the window, or `None` when it may not be
    #: divided by. Published so the screen can show the working rather than only the
    #: conclusion — an owner who disagrees with "nine days" can see the ₹340 a day it came
    #: from and knows immediately whether the platform or their memory is wrong.
    daily_burn_inr: Decimal | None
    #: How long we have actually been watching, in whole days. It is what makes `too_new`
    #: legible ("we have three days of history; we need seven") instead of a bare refusal.
    history_days: int
    #: True when the honest answer is "longer than we will put a number on"
    #: (`MAX_RUNWAY_DAYS`). `days` is None here too — the screen says "more than a year".
    beyond_horizon: bool


@dataclass(frozen=True, slots=True)
class Drawdown:
    """What took money OFF the wallet in the window, and what put money on.

    Every figure is positive and its DIRECTION is in the field name, not in a sign — a
    screen that had to decide whether `-340.00` meant a debit or a correction of one is a
    screen that will eventually decide wrong. `spent_inr` is the sum of the three outgoing
    buckets exactly, computed here so no browser subtracts rupee strings to find it.
    """

    calls_inr: Decimal
    ai_assist_inr: Decimal
    #: Operator corrections that took credit BACK. A positive adjustment is money added and
    #: is counted in `added_inr` below, where a client will look for it.
    adjustments_inr: Decimal
    spent_inr: Decimal
    #: Payments, pack bonuses and positive adjustments that landed in the window.
    added_inr: Decimal
    #: Money returned to the client's own card or bank in the window.
    refunded_inr: Decimal


@dataclass(frozen=True, slots=True)
class TopUpAttemptRow:
    """One started payment, whatever became of it. NOT money — see `models.TopUpAttempt`."""

    id: UUID
    receipt: str
    provider_order_id: str | None
    provider_payment_id: str | None
    amount_inr: Decimal
    pack_id: str | None
    #: `created` / `captured` / `failed`, as stored.
    status: str
    #: The SCREEN's word, derived here rather than in the browser because it depends on a
    #: clock: a `created` attempt is `settling` inside `PENDING_GRACE_HOURS` and
    #: `unfinished` after it. Deriving it server-side keeps the definition of "old" in one
    #: place and out of a timezone-dependent comparison in a browser.
    outcome: str
    started_at: datetime


@dataclass(frozen=True, slots=True)
class WalletSummary:
    """Everything the credits screen needs about the money, in one read."""

    balance: Balance
    #: `compliance.service.credits_exhausted`'s verdict — ASKED, never re-derived. It is
    #: not `balance.is_exhausted`: that predicate is tier-blind, and a managed client's
    #: dialling does not stop for a wallet they never bought.
    outbound_stopped: bool
    #: Does this account HAVE a wallet at all (`rates.PREPAID_TIERS`)? A managed client is
    #: invoiced against a retainer, and offering them a balance would be a number about
    #: nothing.
    prepaid: bool
    runway: Runway
    minutes_left: int | None
    drawdown: Drawdown
    #: BOUGHT versus GIVEN, over the whole life of the wallet (D-535). The founder's own
    #: guardrail on granting credit out of nothing: *"a client's statement must distinguish
    #: credit they BOUGHT from credit we GAVE"*. Lifetime rather than windowed, unlike
    #: `drawdown` — "how much of this did you fund" is a fact about the relationship, and a
    #: client checking a statement against their own books is adding up every payment they
    #: ever made. `service.credit_totals` is the one definition, shared with the operator's
    #: own wallet panel so two screens cannot disagree about one wallet.
    totals: CreditTotals
    #: Is this client's calling on us right now, and until when (D-536)? `None` for every
    #: account that has never had a trial. When it is present and active, `outbound_stopped`
    #: above is False whatever the balance says — the trial arm lives inside
    #: `credits_exhausted`, so this field EXPLAINS that verdict rather than competing with
    #: it, and no screen has to re-derive why a wallet at zero is still dialling.
    trial: TrialState | None


def _floor_days(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_DOWN))


async def read_runway(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    balance: Balance,
    now: datetime | None = None,
) -> tuple[Runway, Drawdown]:
    """The burn rate, the projection and the breakdown — from ONE pass over the window.

    One query, not four, and that is not only a performance choice: the buckets and the
    burn have to be measured over exactly the same rows, or the screen shows a breakdown
    that does not add up to the spending the projection was computed from. Summed in SQL
    over `NUMERIC` so the addition happens in the one place with an exact decimal type.

    `now` is injectable because a projection is a function of the clock and a test that
    could not fix the clock would be a test of `datetime.now()`.
    """
    at = now or datetime.now(UTC)
    since = at - timedelta(days=BURN_WINDOW_DAYS)

    row = (
        await session.execute(
            text(
                # RLS already scopes this; `tenant_id` is in the predicate as well because
                # it is what makes it an index scan on `ix_credit_ledger_tenant_recent`
                # (the same argument `read_credits` records), and because it makes the
                # answer depend on the argument rather than on which session it was handed.
                #
                # The AI-assist bucket is separated by `meta->>'kind'` rather than by a
                # sixth ledger `reason`, because that is how the writer already
                # distinguishes them (`ai_quota.purchase_extra` writes `reason='usage'`
                # with `kind = 'ai_assist_overage'`). Reading it any other way here would
                # be a second definition of "this row is AI, not a call".
                "SELECT "
                "COALESCE(SUM(-delta) FILTER ("
                "  WHERE delta < 0 AND reason = 'usage'"
                "  AND (meta->>'kind') IS DISTINCT FROM :ai_kind), 0), "
                "COALESCE(SUM(-delta) FILTER ("
                "  WHERE delta < 0 AND reason = 'usage'"
                "  AND (meta->>'kind') = :ai_kind), 0), "
                "COALESCE(SUM(-delta) FILTER (WHERE delta < 0 AND reason = 'adjustment'), 0), "
                # `grant` JOINS THIS FILTER (D-535). It is the fourth way credit lands on
                # a wallet, and a goodwill grant missing from "added" would leave a client
                # watching a balance rise with nothing on the screen accounting for it.
                "COALESCE(SUM(delta) FILTER ("
                "  WHERE delta > 0 AND reason IN ('topup', 'bonus', 'adjustment', 'grant')), 0), "
                "COALESCE(SUM(-delta) FILTER (WHERE delta < 0 AND reason = 'refund'), 0) "
                "FROM credit_ledger "
                "WHERE tenant_id = :tid AND occurred_at >= :since"
            ),
            {"tid": tenant_id, "since": since, "ai_kind": OVERAGE_META_KIND},
        )
    ).first()
    # `Decimal(str(...))` on every column, never `Decimal(...)` — the convention every
    # other NUMERIC read in this tree keeps (`service._newest_balance` argues it): the day
    # a driver hands back a float, `Decimal(340.10)` carries the binary error into a figure
    # a client checks against their own books.
    sums = tuple(Decimal(str(value)) for value in row) if row is not None else (Decimal("0"),) * 5
    calls, ai_assist, adjustments, added, refunded = sums
    drawdown = Drawdown(
        calls_inr=calls,
        ai_assist_inr=ai_assist,
        adjustments_inr=adjustments,
        # Summed HERE, from the three buckets that were just measured, so the total on the
        # screen is by construction the sum of the rows beneath it — the identity
        # `usage_summary` keeps for the same reason, rather than a second aggregate that
        # can round differently from its own parts.
        spent_inr=calls + ai_assist + adjustments,
        added_inr=added,
        refunded_inr=refunded,
    )

    # HOW LONG WE HAVE BEEN WATCHING. The first entry on the wallet, floored to whole days
    # and capped at the window — an account with two years of history has thirty days of
    # EVIDENCE here, because that is all the sum above measured, and dividing thirty days
    # of spending by seven hundred days would report a burn an order of magnitude low.
    first_at = (
        await session.execute(
            text("SELECT MIN(occurred_at) FROM credit_ledger WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
    ).scalar()
    if first_at is None:
        observed_days = 0
    else:
        elapsed = (at - first_at).total_seconds() / 86400.0
        observed_days = min(int(elapsed), BURN_WINDOW_DAYS)

    if balance.is_exhausted:
        # Nothing to project. Said as its own basis rather than as "0 days", because an
        # owner reading a zero wants to know it is empty NOW, not that it will be soon.
        return (
            Runway(
                basis="empty",
                days=None,
                daily_burn_inr=None,
                history_days=observed_days,
                beyond_horizon=False,
            ),
            drawdown,
        )
    if observed_days < MIN_BURN_HISTORY_DAYS:
        return (
            Runway(
                basis="too_new",
                days=None,
                daily_burn_inr=None,
                history_days=observed_days,
                beyond_horizon=False,
            ),
            drawdown,
        )
    if drawdown.spent_inr <= 0:
        return (
            Runway(
                basis="no_burn",
                days=None,
                # ZERO, not None: "we watched for a month and you spent nothing" is a
                # measurement, and it is a different statement from "we could not measure".
                daily_burn_inr=Decimal("0"),
                history_days=observed_days,
                beyond_horizon=False,
            ),
            drawdown,
        )

    daily = drawdown.spent_inr / Decimal(observed_days)
    projected = _floor_days(balance.amount_inr / daily)
    if projected > MAX_RUNWAY_DAYS:
        return (
            Runway(
                basis="projected",
                days=None,
                daily_burn_inr=daily,
                history_days=observed_days,
                beyond_horizon=True,
            ),
            drawdown,
        )
    return (
        Runway(
            basis="projected",
            days=projected,
            daily_burn_inr=daily,
            history_days=observed_days,
            beyond_horizon=False,
        ),
        drawdown,
    )


async def read_attempts(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    now: datetime | None = None,
    limit: int = ATTEMPT_LIMIT,
) -> list[TopUpAttemptRow]:
    """The newest top-up attempts, newest first — including the ones that went nowhere.

    THE POINT OF THIS READ is the rows a ledger cannot hold. A declined card moves no
    money, so it has no `credit_ledger` entry, so before `topup_attempts` existed a client
    whose payment failed came back to a screen indistinguishable from one they had never
    touched. `outcome` is derived against the clock here rather than in the browser, so
    "how old is too old" has one definition (`PENDING_GRACE_HOURS`).
    """
    at = now or datetime.now(UTC)
    rows = (
        await session.execute(
            text(
                "SELECT id, receipt, provider_order_id, provider_payment_id, amount_inr, "
                "pack_id, status, created_at FROM topup_attempts "
                "WHERE tenant_id = :tid ORDER BY created_at DESC, id DESC LIMIT :limit"
            ),
            {"tid": tenant_id, "limit": limit},
        )
    ).all()
    out: list[TopUpAttemptRow] = []
    for row in rows:
        status = str(row[6])
        started = row[7]
        if status == "created":
            aged_out = (at - started) > timedelta(hours=PENDING_GRACE_HOURS)
            outcome = "unfinished" if aged_out else "settling"
        else:
            outcome = status
        out.append(
            TopUpAttemptRow(
                id=UUID(str(row[0])),
                receipt=str(row[1]),
                provider_order_id=str(row[2]) if row[2] is not None else None,
                provider_payment_id=str(row[3]) if row[3] is not None else None,
                amount_inr=Decimal(str(row[4])),
                pack_id=str(row[5]) if row[5] is not None else None,
                status=status,
                outcome=outcome,
                started_at=started,
            )
        )
    return out


async def record_attempt(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    receipt: str,
    amount_inr: Decimal,
    provider_order_id: str | None,
    pack_id: str | None,
) -> None:
    """Remember that a top-up was started. Idempotent on the receipt, by the index.

    `ON CONFLICT … DO UPDATE` rather than `DO NOTHING` for one reason: the intent route is
    idempotent on the receipt and replays a stored response, but a deployment can gain the
    API secret between two clicks in the same 15-minute window, and the second click is
    then the one that has an order id. Filling it in is right; overwriting a status is
    not, so `status` is deliberately absent from the SET list — a captured payment stays
    captured however many times the intent behind it is replayed.

    **THIS IS NOT MONEY AND MAY NOT REFUSE A PAYMENT.** It is called from the intent route
    after the order exists, and a failure to write it must never turn a live order into an
    error the client sees — so the caller runs it in its own session and swallows nothing
    silently: see `payment_routes.create_topup_intent`.
    """
    await session.execute(
        text(
            "INSERT INTO topup_attempts "
            "(id, tenant_id, receipt, provider_order_id, amount_inr, pack_id, status) "
            "VALUES (gen_random_uuid(), :tid, :receipt, :order_id, :amount, :pack, 'created') "
            "ON CONFLICT (tenant_id, receipt) DO UPDATE SET "
            "provider_order_id = COALESCE(EXCLUDED.provider_order_id, "
            "topup_attempts.provider_order_id), "
            "updated_at = now()"
        ),
        {
            "tid": tenant_id,
            "receipt": receipt,
            "order_id": provider_order_id,
            "amount": amount_inr,
            "pack": pack_id,
        },
    )


async def settle_attempt(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    order_id: str | None,
    payment_id: str | None,
    status: str,
) -> None:
    """Mark the attempt behind a provider event `captured` or `failed`.

    Keyed on the ORDER id, which is what both events carry and what our own row already
    holds. A payment we have no attempt row for (an order created before this table
    existed, or a payment made outside our checkout) updates nothing and is not an error:
    the wallet is credited by the ledger either way, and this table is a narrative, not a
    prerequisite.

    **`captured` IS TERMINAL AND `failed` MAY NOT OVERWRITE IT.** Razorpay's own
    documentation for its in-modal retry means a `payment.failed` for one attempt can be
    followed by a success on the same ORDER; the predicate below refuses to move a row out
    of `captured`, so a failed first card never re-labels a paid order as failed. The
    reverse is allowed on purpose — a `created` or `failed` row becoming `captured` is the
    money arriving, and that must always win.
    """
    if order_id is None:
        return
    await session.execute(
        text(
            "UPDATE topup_attempts SET status = :status, "
            "provider_payment_id = COALESCE(:payment_id, provider_payment_id), "
            "updated_at = now() "
            "WHERE tenant_id = :tid AND provider_order_id = :order_id "
            "AND status <> 'captured'"
        ),
        {
            "tid": tenant_id,
            "order_id": order_id,
            "payment_id": payment_id,
            "status": status,
        },
    )


async def read_wallet(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    prepaid: bool,
    outbound_stopped: bool,
    rate_inr_per_min: Decimal,
    now: datetime | None = None,
) -> WalletSummary:
    """The wallet's own facts, from ONE balance read. The two VERDICTS are passed in.

    `outbound_stopped` is `compliance.service.credits_exhausted` and `prepaid` is the tier
    test behind it; both are asked by the ROUTE, once, so that this module cannot become a
    second credit gate — the one thing the founder's decision explicitly forbade.

    `rate_inr_per_min` is passed rather than read from settings for the reason
    `prepaid_minutes_left` takes it as an argument: the caller stays the one deciding
    WHICH rate, and this function stays something a test can pin without a settings
    override. A tenant with no wallet gets no minutes figure at all — a runway quoted to
    an invoiced client would be a number about nothing.
    """
    balance = await get_balance(session, tenant_id=tenant_id)
    runway, drawdown = await read_runway(session, tenant_id=tenant_id, balance=balance, now=now)
    trial = await read_trial(session, tenant_id=tenant_id)
    at = now or datetime.now(UTC)
    return WalletSummary(
        balance=balance,
        outbound_stopped=outbound_stopped,
        prepaid=prepaid,
        runway=runway,
        minutes_left=(
            # A TRIAL SUPPRESSES THE RUNWAY FIGURE (D-536), for `usage_summary`'s reason:
            # the wallet is not what limits this client's calling while we are funding it,
            # so a minutes-left number computed from the balance is a limit they will not
            # meet. `None` is this field's own word for "no answer"; the `trial` block says
            # why, and the screen says it in words.
            prepaid_minutes_left(balance=balance, rate=rate_inr_per_min)
            if prepaid and not (trial is not None and trial.is_active(at=at))
            else None
        ),
        drawdown=drawdown,
        totals=await credit_totals(session, tenant_id=tenant_id),
        trial=trial,
    )


__all__ = [
    "ATTEMPT_LIMIT",
    "BURN_WINDOW_DAYS",
    "LEDGER_LIMIT",
    "MAX_RUNWAY_DAYS",
    "MIN_BURN_HISTORY_DAYS",
    "PENDING_GRACE_HOURS",
    "Drawdown",
    "Runway",
    "TopUpAttemptRow",
    "WalletSummary",
    "read_attempts",
    "read_runway",
    "read_wallet",
    "record_attempt",
    "settle_attempt",
]
