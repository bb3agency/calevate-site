"""TRIAL PERIODS — N days on us, and what happens at both ends of them (D-536).

The founder, in their own words: *"any client can be given any no.of days of trail period
where the no.of days can be entered as trail period and for those no.of days we don't bill
anything to the client and everything is on us and their dashboard should show the usage
and all but should not charge them anything and when the trail is lifted or over or
stopped by calevate the numbers should start form 0 again across the client"*.

Five decisions carry it, and each is a thing that could have been built the obvious way
and would have been wrong.

--------------------------------------------------------------------------------
1. A TRIAL IS NOT `plan_tier = 'trial'`
--------------------------------------------------------------------------------
`organizations.plan_tier` already has a `trial` member and it is NOT this. That column
answers two STANDING questions about a motion — does this account pay from a wallet
(`billing/rates.PREPAID_TIERS`) and did a stranger sign it up unattended
(`compliance/service.SELF_SERVE_TIERS`) — and it has no clock in it. This module answers a
third, TEMPORARY one: is this account, right now, inside a period we agreed to fund?

The two are orthogonal in both directions, which is what settles it. A `managed` client on
a retainer can be given a fortnight on us (the founder said "any client"). A `trial`-tier
self-serve signup is a stranger who pays from a wallet and has no funded period at all —
which is precisely the account `SELF_SERVE_TIERS` exists to hold KYC and a first-campaign
review over. Folding the clock into the tier would have made `plan_tier` mean three things,
and the third would have silently changed the answers to the other two: putting a client on
a trial would have withdrawn `prepaid`'s exemption from the KYC and first-campaign gates,
i.e. turned a commercial gift into a compliance regression. Nothing in this module reads or
writes `plan_tier`, and nothing that reads `plan_tier` reads this.

--------------------------------------------------------------------------------
2. IT BYPASSES THE CREDIT GATE. IT IS NOT A GRANT, AND IT IS NOT A COMPLIANCE EXEMPTION
--------------------------------------------------------------------------------
The obvious implementation — grant the client credit and let the ordinary gate honour it —
was put to the founder and REFUSED, on the ground that the ledger would then assert they
were given money nobody gave them. `credit_ledger` is the evidence of what moved; a row
saying "+₹20,000, goodwill" for a period in which no rupee changed hands is a lie about
money, and it would land in the same `granted_inr` figure D-535 built to keep goodwill
credit OUT of revenue. So a trial writes NOTHING to the ledger, and the gate grows an arm.

**THE ARM IS INSIDE `compliance.service.credits_exhausted`, NOT BESIDE IT IN
`check_dispatch`**, and that is the whole of the integration. Putting it in the predicate
rather than in the gate body buys three things a second `if` could not: the gate's ORDER is
untouched (the audit's finding that inbound survives a zero balance rests on
`agent_inbound_only` being answered before any money question, and it still is); every
OTHER reader of the same predicate — the admin health board, `legal/readiness.py`, the
campaign launch gate, the client's own wallet summary — gets the same answer without any of
them learning what a trial is; and there stays exactly one definition of "this account may
not dial for want of money".

**ONLY THE CREDIT GATE.** KYC, the agreements, the spend cap, calling hours, DNC, consent,
the AI disclosure, the India-only destination, the DLT chain and the first-campaign hold
all still bite, unchanged. A trial is a BILLING state. There is no reading of "everything is
on us" that reaches TRAI.

--------------------------------------------------------------------------------
3. USAGE IS METERED AND DISPLAYED. THE WALLET IS NOT DEBITED
--------------------------------------------------------------------------------
`usage_events` records every minute and its `unit_cost_paid` — OUR real supplier cost —
throughout the trial, exactly as it always did. That is not incidental: it is the only
reason anybody can answer "what is this trial costing us", which is the mitigation the
founder chose in place of a spend ceiling (see below). What does not happen is
`billing.service.charge_for_call` against the client's wallet, and the decision is taken in
`apps/workers/pipeline.py` on the CALL'S OWN INSTANT (`trial_covers`) rather than on the
clock at settlement — an ARQ retry ladder or a reconciliation poller can settle a call
hours after it ended, and a client must never be charged for a minute that was free when
they spoke it.

--------------------------------------------------------------------------------
4. NO SPEND CEILING, BY EXPLICIT CHOICE — SO DAYS ARE BOUNDED TWICE AND COST IS PUBLISHED
--------------------------------------------------------------------------------
The unbounded-liability argument was put to the founder and they chose days only. This
module does not add a cap and must not grow one. What it does instead is the other half of
the same sentence: `trial_cost_to_us_inr(...)` sums `usage_events.unit_cost_paid` over the
trial's own window and the admin trial route publishes it, because "no ceiling" and "no
visibility" together is how this becomes expensive silently. `MAX_TRIAL_DAYS` is enforced
at the API boundary AND as a CHECK on the table, because days are the only bound the
arrangement has and a bound that only a route enforces is not a bound against a script.

--------------------------------------------------------------------------------
5. ENDING IS A PERIOD BOUNDARY, AND NOTHING IS DELETED
--------------------------------------------------------------------------------
"When the trail is lifted or over or stopped ... the numbers should start from 0 again."
That is a BILLING PERIOD BOUNDARY, which is how the industry already models the end of a
trial: Stripe's subscription billing cycle anchors by default to the trial end date, i.e.
the moment a trial ends IS the start of a fresh period rather than a mid-period event
(docs.stripe.com/billing/subscriptions/billing-cycle, read via web search summary 4 Sep
2026 — the host is egress-blocked from this container, so what was read is the summary and
not the page; treated as a design precedent, never as a fact about our own system).

So the counters restart the way a fresh month restarts them, and hard rule 4 is untouched:

* **Nothing is deleted from any ledger.** `usage_events`, `credit_ledger`, `audit_log` and
  every other append-only table keep every row. The DB triggers would refuse anyway.
* **The client's own usage figures are FLOORED at the boundary.** `counter_epoch` returns
  the instant the current counting period began — the trial's start while it runs, its end
  once it is over — and `billing.service.usage_summary` and `billing.wallet` pass it as a
  lower bound. Our own margin and cost reads (`billing/attribution.py`, `tier_usage`,
  `margin_for_tenant`, the invoice) are deliberately NOT floored: what a trial cost us must
  stay true and countable for ever.
* **`spend_state` is ZEROED at the boundary**, because it is a live counter that cannot be
  filtered by an epoch — the same act its own month-roll performs on the 1st. It is not a
  ledger and is not in `db/registry.APPEND_ONLY_TABLES`.

Because the epoch moves with the boundary, the money question a client's screen asks
answers itself: every minute counted during a trial is trial-covered, and every minute
counted afterwards is not. No mid-month apportionment exists to get wrong.

--------------------------------------------------------------------------------
AND WHAT HAPPENS TO A CLIENT WHO DOES NOT BUY
--------------------------------------------------------------------------------
`erase_after` is stamped when a NON-CONVERTING trial ends: the grace period the founder
sets, frozen onto the row at that moment so it cannot move under a client already inside
the window. `apps/workers/trials.py` files a TENANT ERASURE through the machinery that
already exists (`compliance/tenant_erasure.py`) — it does not erase anything itself, and
there is deliberately no second eraser in this tree.

A CONVERTING client's `erase_after` stays NULL for ever. Their leads, calls and transcripts
are the value they just built, and one of those callers may be a patient waiting to be rung
back.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7

log = get_logger(__name__)

#: The status of a trial that is still running. Spelled once; four modules compare it.
TRIAL_ACTIVE: Final = "active"

#: How a trial ended. `converted` is the one that keeps the client's data.
TRIAL_CONVERTED: Final = "converted"
TRIAL_EXPIRED: Final = "expired"
TRIAL_STOPPED: Final = "stopped"

#: The outcomes a HUMAN may name when ending a trial early. `expired` is absent on purpose:
#: it is the clock's own verdict and an operator who wants it can simply let the clock run,
#: while accepting it from a route would let a stopped trial be recorded as one that ran its
#: course — a different fact about the same client.
TRIAL_HUMAN_OUTCOMES: Final = (TRIAL_CONVERTED, TRIAL_STOPPED)

#: The bounds on a trial's length. ONE day because a zero-day trial is one nobody got;
#: 365 because past a year the word for the arrangement is a plan and not a trial. Mirrored
#: by `ck_tenant_trials_days_range` — the founder chose days with NO spend ceiling, so the
#: days are the only bound this arrangement has and they are bounded in both places.
MIN_TRIAL_DAYS: Final = 1
MAX_TRIAL_DAYS: Final = 365

#: How long after a NON-CONVERTING trial ends before that client's personal data is erased.
#:
#: A PLATFORM DEFAULT WITH A PER-TRIAL OVERRIDE, rather than a `Settings` field or a column
#: on `organizations`. The founder sets it; what they set is a term of THIS arrangement with
#: THIS client, so it belongs on the trial row and is frozen there when the trial ends — a
#: live setting would move the erasure date of a client already inside their grace window,
#: which is a data-protection promise changing after it was made.
#:
#: THIRTY DAYS because it has to be long enough for a client who is going to buy to actually
#: buy: `wallet.PENDING_GRACE_HOURS` says a payment can still be settling a day later, and a
#: small Indian business deciding on a spend does it over a week or two, not overnight. It
#: is also the horizon the rest of this system already speaks in — `deletion.py` completes an
#: erasure within 30 days of a verified request, and Sarvam's own default content retention
#: is 30 days after last access — so a client's data does not outlive the trial by a period
#: nobody can explain. DPDP §8(7) is the reason there is a deadline at all: once the purpose
#: is served, keeping personal data is a storage-limitation breach in itself.
DEFAULT_ERASURE_GRACE_DAYS: Final = 30

#: The bounds on that grace period, applied wherever an operator may name one.
MIN_ERASURE_GRACE_DAYS: Final = 1
MAX_ERASURE_GRACE_DAYS: Final = 180

#: The `ended_reason` the CLOCK writes. A fixed sentence rather than an empty column: the
#: same field carries an operator's own words when a human ends a trial, and a NULL there
#: would read as "nobody said" rather than "nobody had to".
EXPIRY_REASON: Final = "The trial ran to its end date."

_SELECT = (
    "SELECT id, tenant_id, days, started_at, ends_at, status, ended_at, ended_reason, "
    "erase_after, erasure_filed_at, started_by FROM tenant_trials"
)

#: The newest trial for one tenant. `started_at DESC, id DESC` matches
#: `ix_tenant_trials_tenant_recent`, so the plan walks to one row instead of sorting the
#: account's history — the shape `_newest_balance` takes on the ledger.
_NEWEST = f"{_SELECT} WHERE tenant_id = :tid ORDER BY started_at DESC, id DESC LIMIT 1"


@dataclass(frozen=True, slots=True)
class TrialState:
    """One trial, as every surface reads it. No money and no personal data."""

    id: UUID
    tenant_id: UUID
    days: int
    started_at: datetime
    ends_at: datetime
    status: str
    ended_at: datetime | None
    ended_reason: str | None
    erase_after: datetime | None
    erasure_filed_at: datetime | None
    #: WHO put this client on a trial. Published on the operator's read, because "who
    #: agreed to carry this account for a month" is the first question asked about a trial
    #: nobody remembers, and the `audit_log` row — the durable record — is not on the screen
    #: an operator is looking at. NULL once that person's user row is removed (`SET NULL`):
    #: a leaver must not pin a client's trial history, and the audit row survives them.
    started_by: UUID | None

    def is_active(self, *, at: datetime) -> bool:
        """Is this client inside a funded period at `at`?

        **THE CLOCK IS ASKED AS WELL AS THE STATUS, AND THAT IS NOT BELT-AND-BRACES.** The
        row is moved to `expired` by a sweep that runs once a day, so between the end
        instant and the next tick a row still reads `active`. Trusting the column alone
        would hand out free calling for up to a day per trial, silently, on the one path
        where the mistake is a real cost rather than a stale word. Reading the clock makes
        the sweep a BOOKKEEPING job — it records what already happened — which is the only
        kind of scheduled job whose lateness is harmless.
        """
        return self.status == TRIAL_ACTIVE and at < self.ends_at

    def days_remaining(self, *, at: datetime) -> int | None:
        """Whole days left, or None once the trial is over.

        CEILING, not floor: a client with four hours left has "1 day", because the number
        on their screen is how many more days they may call and rounding it down to zero
        would tell someone with a working service that it has already stopped. Never
        negative — an active row past its end date reads 0, which with `is_active` False
        is the honest pair.
        """
        if not self.is_active(at=at):
            return None
        seconds = (self.ends_at - at).total_seconds()
        return max(0, -int(-seconds // 86400))


def _state(row: Any) -> TrialState:
    """Build the state from `_SELECT`'s column order, in ONE place — every reader below
    shares it so a column added to the SELECT cannot be unpacked two different ways."""
    return TrialState(
        id=UUID(str(row[0])),
        tenant_id=UUID(str(row[1])),
        days=int(row[2]),
        started_at=row[3],
        ends_at=row[4],
        status=str(row[5]),
        ended_at=row[6],
        ended_reason=str(row[7]) if row[7] is not None else None,
        erase_after=row[8],
        erasure_filed_at=row[9],
        started_by=UUID(str(row[10])) if row[10] is not None else None,
    )


async def read_trial(session: AsyncSession, *, tenant_id: UUID) -> TrialState | None:
    """This tenant's NEWEST trial, or None if they have never had one.

    Newest rather than "the open one", because every screen that asks about a trial also
    has to render the one that just ended — "your trial finished on the 3rd" is the
    sentence a client needs, and a reader that could only see open rows would show them
    nothing at all.
    """
    row = (await session.execute(text(_NEWEST), {"tid": tenant_id})).first()
    return _state(row) if row is not None else None


async def trial_billing_active(
    session: AsyncSession, *, tenant_id: UUID, at: datetime | None = None
) -> bool:
    """Is this client's calling on us right now? THE predicate the credit gate asks.

    A function rather than a property on the state so the callers that need only the
    yes/no — the dial gate, the meter — pay for one indexed row read and nothing else, and
    so there is exactly one spelling of the question in the tree.
    """
    trial = await read_trial(session, tenant_id=tenant_id)
    return trial is not None and trial.is_active(at=at or datetime.now(UTC))


async def trial_covers(session: AsyncSession, *, tenant_id: UUID, at: datetime) -> bool:
    """Was this client inside a funded period at instant `at`? THE meter's question.

    Distinct from `trial_billing_active` because the two ask about different instants and
    the difference is money. The gate asks about NOW: may this call be placed. The meter
    asks about THEN: was the call that just settled free when it was spoken. A call can end
    inside a trial and settle after it — an ARQ retry ladder, or the reconciliation poller
    picking up a call the webhook lost — and charging a client for a minute that was free
    when they used it is the one direction of error they will notice and be right about.

    Bounded at BOTH ends by the trial's own instants, so a trial stopped early does not go
    on covering calls placed after the operator stopped it. `ended_at` beats `ends_at`
    whenever a human ended it first; for a trial that ran its course the two are the same
    boundary and `LEAST` picks either.
    """
    trial = await read_trial(session, tenant_id=tenant_id)
    if trial is None:
        return False
    boundary = min(trial.ends_at, trial.ended_at) if trial.ended_at is not None else trial.ends_at
    return trial.started_at <= at < boundary


async def counter_epoch(session: AsyncSession, *, tenant_id: UUID) -> datetime | None:
    """The instant this client's CURRENT counting period began, or None if it is the month.

    THE ONE DEFINITION of the boundary "the numbers start from 0 again" is measured from,
    read by the client's usage panel and by their wallet drawdown and by nothing else.

    * A trial that is RUNNING → its `started_at`. Everything the client has used inside the
      period is what the period shows.
    * A trial that has ENDED → its `ended_at`. A fresh period, exactly as the 1st of a
      month is a fresh period.
    * No trial ever → None, and every client-facing figure is the plain IST billing month
      it has always been. An account that never had a trial must not acquire a second,
      invisible window.

    It returns None rather than the month's own start when there is no trial, because the
    callers already have a month window and this is a FLOOR applied on top of it. Answering
    with the month start would work today and would be a second, duplicate definition of the
    month boundary the moment either moved.
    """
    trial = await read_trial(session, tenant_id=tenant_id)
    if trial is None:
        return None
    return trial.started_at if trial.status == TRIAL_ACTIVE else trial.ended_at


async def trial_cost_to_us_inr(
    session: AsyncSession, *, tenant_id: UUID, trial: TrialState
) -> Decimal:
    """What this trial has cost CALEVATE, from `usage_events.unit_cost_paid`.

    THE OTHER HALF OF "NO SPEND CEILING". The founder was shown the unbounded-liability
    argument and chose days only; this is the visibility that makes that choice survivable,
    and the admin trial route publishes it. It is OUR supplier cost and is never published
    to a client — the client panel has never shown `unit_cost_paid` and must not start here
    (`billing/service.py`: "our supplier pricing is commercially ours").

    Summed in SQL over NUMERIC (hard rule 7), bounded by the trial's own instants rather
    than by a billing month, because the question is about the arrangement and not about
    January.
    """
    end = trial.ended_at or trial.ends_at
    total = (
        await session.execute(
            # `tenant_id` in the predicate as well as in RLS, for `charge_for_call`'s
            # reason: RLS fails the query closed either way, and naming it makes the answer
            # depend on the argument rather than on which session it was handed.
            text(
                "SELECT COALESCE(SUM(unit_cost_paid * qty), 0) FROM usage_events "
                "WHERE tenant_id = :tid AND occurred_at >= :from AND occurred_at < :to"
            ),
            {"tid": tenant_id, "from": trial.started_at, "to": end},
        )
    ).scalar()
    return Decimal(str(total or 0))


async def _lock_tenant_trial(session: AsyncSession, tenant_id: UUID) -> None:
    """Serialize every trial write for this tenant for the rest of the transaction.

    Taken BEFORE the "is one already open?" read, for the reason
    `billing.service.lock_tenant_credits` spells out: a dedupe check outside a lock is the
    check-then-write hole two concurrent requests both walk through. Its own key namespace,
    never the credit lock's — a trial write must not queue behind a busy wallet, and the
    two are never taken together.
    """
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"trial:{tenant_id}"},
    )


async def start_trial(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    days: int,
    actor_user_id: UUID | None,
    erasure_grace_days: int = DEFAULT_ERASURE_GRACE_DAYS,
    at: datetime | None = None,
) -> TrialState:
    """Open a trial. Does not commit — the caller's audit row shares the transaction.

    Refuses a second open trial by NAME (409) rather than letting `ux_tenant_trials_active`
    surface as a 500: an operator who clicks twice must be told the client is already on a
    trial and when it ends, which is the answer they were actually looking for.

    `erasure_grace_days` is carried, not applied: it becomes `erase_after` only if the trial
    ends WITHOUT the client converting, and it is frozen onto the row at that moment (see
    `end_trial`) so it cannot move under a client already inside their window.
    """
    now = at or datetime.now(UTC)
    if not MIN_TRIAL_DAYS <= days <= MAX_TRIAL_DAYS:
        raise ProblemError.business_rule(
            "invalid_trial_days",
            f"A trial runs for between {MIN_TRIAL_DAYS} and {MAX_TRIAL_DAYS} days.",
            remediation="Enter the number of days the client was promised.",
        )
    if not MIN_ERASURE_GRACE_DAYS <= erasure_grace_days <= MAX_ERASURE_GRACE_DAYS:
        raise ProblemError.business_rule(
            "invalid_erasure_grace",
            (
                "The grace period before a non-converting client's data is erased must be "
                f"between {MIN_ERASURE_GRACE_DAYS} and {MAX_ERASURE_GRACE_DAYS} days."
            ),
            remediation="Leave it unset to use the platform default of "
            f"{DEFAULT_ERASURE_GRACE_DAYS} days.",
        )

    await _lock_tenant_trial(session, tenant_id)
    existing = await read_trial(session, tenant_id=tenant_id)
    if existing is not None and existing.status == TRIAL_ACTIVE:
        raise ProblemError.conflict(
            "trial_already_open",
            "This client is already on a trial.",
            remediation=(
                "End the current trial first — convert it if they have bought, or stop it "
                "— and then start a new one if that is what you meant."
            ),
        )

    trial_id = uuid7()
    # Derived from the typed number ONCE, here, so the end date and the days a client was
    # promised cannot disagree. Both are stored: the typed number is what the founder
    # agreed and what an operator will look for when a client quotes it back.
    ends_at = now + timedelta(days=days)
    # THE AGREED GRACE, STAMPED AT START AND NOT AT END. It is a term of THIS arrangement
    # with THIS client, so it must not be re-read from a default at erasure time — a
    # platform default that moved would move the erasure date of a client already inside
    # their window, which is a data-protection promise changing after it was made. Written
    # provisionally against the SCHEDULED end; `end_trial` re-applies the same span from the
    # real end instant, and clears it outright if the client converts.
    row = (
        await session.execute(
            text(
                "INSERT INTO tenant_trials "
                "(id, tenant_id, days, started_at, ends_at, status, erase_after, "
                " started_by, created_at, updated_at) "
                "VALUES (:id, :tid, :days, :start, :end, 'active', :erase_after, :by, "
                " :start, :start) "
                "RETURNING id, tenant_id, days, started_at, ends_at, status, ended_at, "
                "ended_reason, erase_after, erasure_filed_at, started_by"
            ),
            {
                "id": trial_id,
                "tid": tenant_id,
                "days": days,
                "start": now,
                "end": ends_at,
                "erase_after": ends_at + timedelta(days=erasure_grace_days),
                "by": actor_user_id,
            },
        )
    ).first()
    assert row is not None  # RETURNING on a single-row INSERT
    log.info(
        "trial_started",
        extra={
            "tenant_id": str(tenant_id),
            "trial_id": str(trial_id),
            "days": days,
            "erasure_grace_days": erasure_grace_days,
        },
    )
    return _state(row)


async def end_trial(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    outcome: str,
    reason: str,
    at: datetime | None = None,
) -> TrialState:
    """Close the open trial and START A FRESH COUNTING PERIOD. Does not commit.

    Three things happen together, in one transaction, because a client whose trial ended
    and whose counters did not restart is showing a bill for calls we said were free:

    1. The row moves to its terminal status with `ended_at` = the boundary instant. That
       instant is what `counter_epoch` publishes, so every client-facing usage figure is
       floored at it from the next read onwards — nothing is deleted and no ledger is
       touched (hard rule 4).
    2. `erase_after` is FROZEN at `ended_at + the agreed grace` for a non-converting
       client, and CLEARED for a converting one. A client who bought keeps their leads,
       calls and transcripts; that is the value they just built.
    3. `spend_state` is zeroed. It is a live counter that no epoch can filter — the cap
       machinery reads it directly — and zeroing it is exactly what its own month-roll
       does on the 1st. It is not a ledger and is not append-only.

    The grace period is re-derived from what the row already carries (`erase_after` was
    stamped at start from the trial's own end date), so an operator who stops a trial early
    gets the SAME number of grace days they agreed, measured from the real end.
    """
    now = at or datetime.now(UTC)
    if outcome not in (TRIAL_CONVERTED, TRIAL_EXPIRED, TRIAL_STOPPED):
        raise ProblemError.business_rule(
            "invalid_trial_outcome",
            "A trial ends as converted, expired or stopped.",
        )

    await _lock_tenant_trial(session, tenant_id)
    trial = await read_trial(session, tenant_id=tenant_id)
    if trial is None or trial.status != TRIAL_ACTIVE:
        raise ProblemError.conflict(
            "no_open_trial",
            "This client is not on a trial.",
            remediation="Start one first if that is what you meant.",
        )

    # HOW MANY GRACE DAYS WERE AGREED, recovered from the row rather than re-read from the
    # default — a trial started with a 60-day grace must not silently get 30 because it was
    # stopped early. `erase_after` was stamped at start as `ends_at + grace`, so the
    # difference is the agreed period and it is re-applied from the REAL end instant.
    grace = (
        trial.erase_after - trial.ends_at
        if trial.erase_after is not None
        else timedelta(days=DEFAULT_ERASURE_GRACE_DAYS)
    )
    erase_after = None if outcome == TRIAL_CONVERTED else now + grace

    await session.execute(
        text(
            "UPDATE tenant_trials SET status = :status, ended_at = :at, ended_reason = :why, "
            "erase_after = :erase_after, updated_at = :at "
            "WHERE id = :id AND status = 'active'"
        ),
        {
            "status": outcome,
            "at": now,
            "why": reason,
            "erase_after": erase_after,
            "id": trial.id,
        },
    )
    await reset_client_counters(session, tenant_id=tenant_id)
    log.info(
        "trial_ended",
        extra={
            "tenant_id": str(tenant_id),
            "trial_id": str(trial.id),
            "outcome": outcome,
        },
    )
    return TrialState(
        id=trial.id,
        tenant_id=trial.tenant_id,
        days=trial.days,
        started_at=trial.started_at,
        ends_at=trial.ends_at,
        status=outcome,
        ended_at=now,
        ended_reason=reason,
        erase_after=erase_after,
        erasure_filed_at=trial.erasure_filed_at,
        started_by=trial.started_by,
    )


async def reset_client_counters(session: AsyncSession, *, tenant_id: UUID) -> None:
    """Zero the LIVE counters at a period boundary. Deletes nothing.

    `spend_state` is a single derived row per tenant carrying this month's minutes, our
    cost, what the client owes, and whether the cap has bitten. Every one of those is a
    figure the client sees or the gate enforces, none of them is evidence, and the row is
    already reset wholesale when the month rolls (`_counter_increment`'s upsert). Resetting
    it here is the same act at a different boundary.

    **THE APPEND-ONLY LEDGERS ARE NOT TOUCHED AND MUST NOT BE.** `usage_events` and
    `credit_ledger` keep every row; what changes for the client is the WINDOW their screen
    counts over (`counter_epoch`), not the rows. The DB triggers would refuse anyway, which
    is the point of hard rule 4 — this function could not do the wrong thing if it tried.

    `capped` is cleared with the rest deliberately: the flag is derived from counters that
    are now zero, so leaving it set would refuse a client's calls on the strength of a
    ceiling nothing has reached. The next completed call recomputes it from the shared
    `over_cap_sql` like always.
    """
    await session.execute(
        text(
            "UPDATE spend_state SET minutes_used = 0, spend_used = 0, billed_inr = 0, "
            "capped = false WHERE tenant_id = :tid"
        ),
        {"tid": tenant_id},
    )


async def mark_erasure_filed(
    session: AsyncSession, *, trial_id: UUID, at: datetime | None = None
) -> None:
    """Stamp that the tenant erasure for this trial has been FILED.

    What makes the sweep idempotent. The erasure itself is executed and certified by
    `compliance/tenant_erasure.py` and `apps/workers/retention.py`; this column only records
    that we asked, so a sweep that runs again tomorrow does not file a second request
    (`request_tenant_erasure` would return the open one, but a job that re-asks every night
    for ever is a job nobody can tell from a broken one).
    """
    await session.execute(
        text("UPDATE tenant_trials SET erasure_filed_at = :at, updated_at = :at WHERE id = :id"),
        {"at": at or datetime.now(UTC), "id": trial_id},
    )


__all__ = [
    "DEFAULT_ERASURE_GRACE_DAYS",
    "EXPIRY_REASON",
    "MAX_ERASURE_GRACE_DAYS",
    "MAX_TRIAL_DAYS",
    "MIN_ERASURE_GRACE_DAYS",
    "MIN_TRIAL_DAYS",
    "TRIAL_ACTIVE",
    "TRIAL_CONVERTED",
    "TRIAL_EXPIRED",
    "TRIAL_HUMAN_OUTCOMES",
    "TRIAL_STOPPED",
    "TrialState",
    "counter_epoch",
    "end_trial",
    "mark_erasure_filed",
    "read_trial",
    "reset_client_counters",
    "start_trial",
    "trial_billing_active",
    "trial_cost_to_us_inr",
    "trial_covers",
]
