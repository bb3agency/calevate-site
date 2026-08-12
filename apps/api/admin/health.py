"""The client health overview — WHICH account is about to churn or break, this week.

    GET /v1/admin/client-health

An operator with N client businesses cannot open N dashboards on a Monday morning. What
they need is the opposite of a dashboard: a short ranked list of the accounts where
something is wrong, each row naming the one thing to do about it. So this is a WORK
LIST, built the way `admin/holds.py` is, and it is deliberately NOT a second tenant
directory — `/v1/admin/tenants` is the roster (every client, with counters), this is the
exception report (only clients with a live signal, worst first). An account with nothing
wrong does not appear at all.

WHY THESE FIVE SIGNALS, AND NOT A GRID
---------------------------------------
The bar every candidate had to clear: an operator can DO something about it today, and
the platform can observe it HONESTLY. Five cleared it.

1. **`calls_stopped`** — the account's call volume collapsed against its own previous
   week. This is the outcome signal rather than a cause, and it is the one that catches
   the failures nobody thought to instrument: a number that stopped routing, a client who
   quietly went back to answering the phone themselves, a receptionist agent taken off the
   IVR. Every other signal here explains a symptom; this one IS the churn. Its honesty
   caveat is the whole reason `CallVolume.basis` exists — see below.
2. **`outbound_blocked`** — the platform is refusing this client's outbound calls right
   now. Composed from the gates THEMSELVES (`spend_capped`, `credits_exhausted`,
   `kyc_blocker`, `first_campaign_hold_blocker`, `pe_registration_blocker`), never from a
   second copy of their conditions, so the board cannot tell an operator an account is
   fine while the client is staring at a refusal. Reported only for accounts that
   actually dial out (see `_dials_out`): telling the operator of a purely inbound clinic
   that their outbound is blocked is noise about a capability they never bought.
3. **`spend_cap_near`** — the ceiling in force will stop this account before the billing
   month ends. This is the only forward-looking signal on the list, and it is here
   because it is the one blocker an operator can clear BEFORE the client notices: a cap
   raised at 85% is an account that never stops dialling, a cap raised at 100% is a
   support ticket that already happened.
4. **`deliveries_failing`** — leads are not reaching the client's own CRM or spreadsheet.
   The client's experience of this product is "leads appear where I work", so a broken
   delivery reads to them as the product having stopped, and it is invisible until they
   notice absences. `crm/attention.py` already shows this to the CLIENT; nothing showed it
   to us, across clients, which is the gap this closes.
5. **`knowledge_waiting`** — the client uploaded knowledge and WE never approved it. The
   only signal here that is entirely our own fault: `crm/attention.py` deliberately keeps
   `pending_approval` off the client's queue ("waiting for us is not the client's to-do"),
   which means the operator console is the only correct home for it, and until now it had
   none — an operator had to open each account to find it.

CANDIDATES REJECTED, WITH THE REASON (so nobody re-proposes them)
-----------------------------------------------------------------
* **Latency drift / answer-rate dips** (SURFACES §1 asks for both). We cannot observe
  latency honestly. D-52 dropped the per-call latency column (migration f1a7c39d5be2)
  precisely because every span this repo opens is on OUR side of the call, and D-49
  removed the trace config rather than pretend a pipeline exists — so a latency tile here
  would be a fabricated number on the screen operators trust most. (Written without
  naming the dead column: `tests/call_latency_column_test.py` forbids prose in `apps/`
  that points at it, which is the rule working.) Answer rate IS derivable
  (`crm/performance.py::CONNECTED_SQL`) but it moves for reasons an operator cannot act
  on in a week — list quality, time of day — and `calls_stopped` already catches the
  collapse that matters.
* **Margin per client** (D-12, and it exists at `/v1/admin/tenants/{id}/margin`). Real,
  and a commercial review question rather than a "this client breaks this week" question.
  A quarterly number does not belong on a weekly triage list.
* **QA sampling backlog** (SURFACES §1). There is no sampling queue in this codebase to
  count; a signal for it would be a column nothing writes.
* **`no_plan_in_effect`** — a tenant serving calls we cannot bill. Genuinely a defect and
  genuinely money, but it is billing hygiene rather than churn, and it ALREADY has a
  home: `billing/plans.py::warn_no_plan_in_effect` logs it on the money path with the
  tenant id. Adding it here would be a second home for one fact, which is where drift
  starts.
* **The R-11 holds as their own row.** They are on `/admin/holds`, which is a screen with
  its own triage order (oldest signup first). They appear here only as CAUSES of
  `outbound_blocked`, from the same `read_tenant_holds` predicate — because the question
  "can this client dial today" has one true answer and a board that answered it partially
  would be worse than not answering it. The console links the cause names back to that
  queue rather than re-implementing its remedies.

HONESTY: A SIGNAL WE CANNOT OBSERVE MUST NOT RENDER AS ONE WE CAN
------------------------------------------------------------------
`crm/service.py::dashboard` set the precedent with `after_hours_basis`: when a number
came from a guess rather than a fact, the API says which, and the UI says which one it is
holding. The same problem exists here and it is sharper, because the guess would be an
ACCUSATION. "Calls are trending to zero" is only a statement about an account that traded
through the whole comparison window and traded enough for the comparison to mean anything.
A tenant that signed up on Thursday has no previous week; a tenant that made two calls
last week has no baseline. Both would light up as "collapsed" under a naive ratio, and an
operator who phones a four-day-old account to ask why their calls stopped has been lied to
by their own console.

So `CallVolume.basis` is on every row: `measured` (the comparison is entitled to be made),
`too_new` (the account is younger than the comparison window) or `no_baseline` (it traded,
below `TREND_BASELINE_MIN`). `calls_stopped` fires ONLY on `measured`, and the basis
travels to the screen so a row on the board for another reason can say plainly that its
call trend is not yet a fact.

HARD RULE 1 — THE SAME ONE WAY, NOT A SECOND ONE
-------------------------------------------------
This is a cross-tenant read from the admin realm, which is precisely where tenancy gets
broken. It uses the mechanism `admin/service.py::tenant_overview` and `admin/holds.py`
already use, and it widens NOTHING: the DIRECTORY comes from the `app.admin` session
(migration b57e2f9c4a13 widens `organizations` and nothing else), and every per-client
fact is read INSIDE that client's own `tenant_session()`, under ordinary RLS. No policy
changes, no admin DB role in an app path, and no query in this module can see two tenants
at once. `admin/holds.py`'s docstring argues the rejected alternative (widening the
policies) at length; that argument is not repeated here, it is inherited.

QUERY SHAPE, MEASURED RATHER THAN ASSUMED
------------------------------------------
One directory query, then ONE session per candidate tenant. Inside that session the facts
only this module needs are ONE aggregate statement (`_FACTS`, five correlated counts over
already-indexed tenant tables) — not one query per signal, which is the shape that turns
a five-signal board into a five-fold cost.

What is NOT folded into that statement is the compliance and billing half, and that is a
deliberate trade rather than an oversight: `spend_capped`, `credits_exhausted`,
`read_tenant_holds` and `pe_registration_blocker` are the predicates the DIAL GATE asks,
and re-expressing them in this module's SQL would buy a few round trips and pay for it
with a board that drifts away from the refusal the client is actually seeing. So a
candidate tenant costs one aggregate plus those predicates' own small indexed reads, and
the total is bounded by the candidate filter below rather than by the client list.

The candidate filter is what keeps this honest at M1 scale: only LIVE accounts
(`status`, `deleted_at`) are walked, so an archive of churned tenants does not become a
per-poll cost.

**Measured rather than assumed**, because "a handful of fast counts" is the sentence
every N+1 is defended with: on the verification database (11,792 organization rows, most
of them onboarding-state test debris) one full walk takes **77s — about 6.5ms per
account**, end to end, including the predicates. That is linear and it is the number that
matters: at the one-to-a-few-dozen clients this milestone targets it is well under a
second, at a hundred it is under a second, and somewhere in the low thousands it stops
being a page an operator can open. The console polls it every two minutes rather than
every sixty seconds for that reason (`lib/api/admin.ts` states it there too).

Nothing here truncates the list to stay fast, because a triage board that silently
dropped the account at the bottom would be worse than a slow one — the whole promise is
"you do not have to know which client to look at". What it does instead is say so:
`WALK_BUDGET_S` is the point past which the walk is a problem an operator should hear
about BEFORE a colleague reports a hanging console, and exceeding it logs the account
count and the elapsed time. The fix when that line appears is the materialized
`tenant_health` table `admin/service.py::tenant_overview` already names as the escape
hatch. Building it now would be a cache in front of a query nobody has measured as slow.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from time import perf_counter
from typing import Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.admin.holds import read_tenant_holds
from apps.api.billing.caps import read_caps, read_spend_counters
from apps.api.compliance.registration import pe_registration_blocker
from apps.api.compliance.service import credits_exhausted, spend_capped
from apps.api.core.logging import get_logger
from apps.api.db.session import tenant_session

log = get_logger(__name__)

# How far back "this week" reaches, and the length of the window it is compared against.
# Seven days rather than thirty because the board answers "what breaks THIS week", and a
# thirty-day mean hides a collapse that started on Tuesday.
WINDOW_DAYS = 7

# Calls in the PREVIOUS window below which a comparison is not entitled to be made. Five
# is a judgement, not a measurement, and it is deliberately low: this is the threshold at
# which a ratio stops being arithmetic about traffic and starts being arithmetic about
# noise. A client doing four calls a week has a relationship problem the board cannot see
# and an account manager can.
TREND_BASELINE_MIN = 5

# The drop that counts as a decline rather than a quiet week. 60% is a triage heuristic
# in the same family as `WAIT_WARN_HOURS` on the hold queue — it should move the day
# somebody measures what a normal week-to-week swing looks like across real clients.
TREND_DECLINE_PCT = 60

# How much of the ceiling has to be spent before the cap is "about to bite". At 80% there
# is still a working week left to raise it; at 95% the operator is reacting, not acting.
CAP_WARN_PCT = 80

# How long the whole walk may take before it is a problem in its own right. Five seconds
# is the point at which a console page stops feeling loaded and starts feeling broken, and
# at the measured ~6.5ms per account it corresponds to roughly 750 live clients — far
# beyond anything this milestone plans for, which is exactly why crossing it is worth a
# line rather than a truncation. See the module docstring.
WALK_BUDGET_S = 5.0

Severity = Literal["stop", "warn"]
CallBasis = Literal["measured", "too_new", "no_baseline"]


@dataclass(frozen=True, slots=True)
class HealthSignal:
    """One thing wrong with one account.

    `causes` carries the GATES' own rule names (`spend_cap`, `kyc_missing`,
    `pe_registration_missing`, …) and never their `reason` prose. That is the same hard
    rule 6 line `admin/holds.py` draws and for the same reason: the first-campaign
    rejection reason interpolates an operator's free text, and free text can carry
    anything into the widest-read list in the console. The console owns the wording, the
    server owns the facts.
    """

    rule: str
    severity: Severity
    causes: tuple[str, ...] = ()
    # The number behind a countable signal (failed deliveries, sources waiting), or None
    # for a signal that is a state rather than a count. None and 0 are different claims.
    count: int | None = None


@dataclass(frozen=True, slots=True)
class CallVolume:
    """This week's calls against last week's, and whether that comparison is a FACT.

    `basis` is the `after_hours_basis` precedent applied to an accusation rather than a
    tile: see the module docstring. Nothing may render a trend from a `basis` other than
    `measured`.
    """

    calls_7d: int
    calls_prev_7d: int
    basis: CallBasis
    last_call_at: datetime | None


@dataclass(frozen=True, slots=True)
class Account:
    """The directory half of a row — everything `organizations` knows about a client.

    Passed INTO the per-tenant judgement rather than re-read inside it, because the
    directory is the one thing an `app.admin` session can see and a tenant's own session
    can see for itself: re-reading it under the tenant GUC would be a second query for
    facts already in hand, and reading it under the admin session inside the per-tenant
    loop is exactly the cross-tenant drift hard rule 1 exists to prevent.
    """

    tenant_id: UUID
    name: str
    slug: str
    plan_tier: str
    status: str
    # When the account arrived. It decides `CallVolume.basis`: an account younger than
    # the comparison window has no previous week to be compared against.
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ClientHealth:
    """One line of the board — an account with at least one live signal."""

    tenant_id: UUID
    name: str
    slug: str
    plan_tier: str
    status: str
    severity: Severity
    signals: tuple[HealthSignal, ...]
    volume: CallVolume
    # This month's metered spend and the ceiling in force, or None when no ceiling is.
    # NUMERIC all the way here (hard rule 7); the route stringifies at the boundary.
    spend_used_inr: Decimal
    spend_cap_inr: Decimal | None


# Accounts this board has nothing to say about. `churned` has already gone and
# `suspended` was stopped BY US on purpose — every signal here would fire on a suspended
# account and every one of them would be correct and useless. Excluding them is also what
# keeps the walk below proportional to the CLIENT LIST rather than to history.
# `prospect` and `onboarding` stay in: an onboarding client that never places a first
# call is the most churnable account there is, and `CallVolume.basis` is what stops that
# being reported as a collapse.
_ENDED_STATUSES = ("churned", "suspended")

_DIRECTORY = (
    "SELECT id, name, slug, status, plan_tier, created_at FROM organizations "
    "WHERE deleted_at IS NULL AND status <> ALL(:ended) "
    "ORDER BY created_at DESC"
)

# Every fact only this module needs, in ONE statement per tenant. Each subquery runs
# under the tenant's own GUC, so none of them carries a `tenant_id` predicate — the
# policy is the scoping, exactly as it is in `admin/service.py::tenant_overview`.
#
# `webhook_deliveries` is joined through `outbound_webhooks` rather than filtered by
# tenant, because it has no RLS policy of its own by design (migration 4be32bf3d12c) and
# the endpoint is what makes a delivery a tenant's. Copied from
# `crm/attention.py::failed_deliveries` so both readers scope it identically.
_FACTS = """
SELECT
  (SELECT count(*) FROM calls WHERE started_at >= :window_start) AS calls_7d,
  (SELECT count(*) FROM calls
     WHERE started_at >= :prev_start AND started_at < :window_start) AS calls_prev_7d,
  (SELECT max(started_at) FROM calls) AS last_call_at,
  (SELECT count(*) FROM webhook_deliveries d
     JOIN outbound_webhooks w ON w.id = d.endpoint_id
     WHERE d.direction = 'out' AND d.status = 'failed'
       AND d.last_at >= :window_start) AS failed_deliveries,
  (SELECT count(*) FROM kb_sources WHERE status = 'pending_approval') AS kb_waiting,
  (SELECT count(*) FROM agents
     WHERE deleted_at IS NULL AND direction IN ('outbound', 'both')) AS outbound_agents,
  (SELECT count(*) FROM campaigns) AS campaigns
"""


def _call_volume(
    *,
    calls_7d: int,
    calls_prev_7d: int,
    last_call_at: datetime | None,
    created_at: datetime,
    now: datetime,
) -> CallVolume:
    """The two counts and WHICH claim they support.

    `too_new` is decided on the account's age rather than on its counts, because they are
    different facts that both produce a small number: an account that opened on Thursday
    has no previous week, and saying "no baseline" about it would invite somebody to wait
    for one that has already passed.
    """
    if created_at > now - timedelta(days=WINDOW_DAYS * 2):
        basis: CallBasis = "too_new"
    elif calls_prev_7d < TREND_BASELINE_MIN:
        basis = "no_baseline"
    else:
        basis = "measured"
    return CallVolume(
        calls_7d=calls_7d,
        calls_prev_7d=calls_prev_7d,
        basis=basis,
        last_call_at=last_call_at,
    )


def _volume_signal(volume: CallVolume) -> HealthSignal | None:
    """`calls_stopped`, or nothing at all — never a trend on an unearned basis."""
    if volume.basis != "measured":
        return None
    if volume.calls_7d == 0:
        # Silence with a real baseline behind it. `stop`, because a client whose agent
        # took thirty calls last week and none this week has either lost their routing or
        # lost interest, and both are this week's phone call.
        return HealthSignal(rule="calls_stopped", severity="stop", count=volume.calls_prev_7d)
    dropped_pct = (volume.calls_prev_7d - volume.calls_7d) * 100 // volume.calls_prev_7d
    if dropped_pct >= TREND_DECLINE_PCT:
        return HealthSignal(rule="calls_stopped", severity="warn", count=volume.calls_7d)
    return None


def _dials_out(*, outbound_agents: int, campaigns: int) -> bool:
    """Does outbound mean anything for this account?

    Asked of what the account HAS rather than of its plan tier: a managed clinic that only
    answers the phone has bought no outbound capability, and reporting its DLT paperwork
    as a live problem would be a red row about a thing that is not broken. An outbound or
    both-direction agent, or any campaign ever created, is the account telling us it
    intends to dial — including a DRAFT campaign, because a draft that can never launch is
    exactly the account worth surfacing.
    """
    return outbound_agents > 0 or campaigns > 0


async def _outbound_blocked(session: AsyncSession, *, tenant_id: UUID) -> HealthSignal | None:
    """Can this account place an outbound call today, and if not, on whose desk is it?

    Every condition is asked through the predicate that REFUSES the dial, in the order
    `campaigns.service.launch_blockers` asks them, so the board and the client's own
    launch preview name one condition with one word. Nothing here is re-derived.

    Three of the launch gate's rules are deliberately absent, and each for its own reason:

    * `dnc` and `calling_hours` are properties of a CONTACT and a CLOCK, not of an account.
      A board that went amber on every row every evening at 21:00 IST would train an
      operator to ignore it.
    * `tm_registration_missing` — Calevate's OWN telemarketer registration — is one global
      row in `platform_state`, false for everybody at once. Repeating it on every line of
      this board would be one fact rendered N times while saying nothing about which client
      to look at; it belongs where it already is, on `/admin/ops`, beside the switch that
      sets it.
    * The per-CAMPAIGN rules (`consent_provenance_missing`, `dlt_template_*`,
      `number_not_registered`) need a campaign to be about. They are the launch screen's
      subject and the client can see them there.
    """
    causes: list[str] = []
    # KYC first, and the holds together, because `read_tenant_holds` is the one predicate
    # the hold queue and the tenant directory already share — a third caller must not be
    # a third definition.
    causes.extend((await read_tenant_holds(session, tenant_id=tenant_id)).rules)
    blocked_on_pe = await pe_registration_blocker(session, tenant_id=tenant_id)
    if blocked_on_pe is not None:
        causes.append(blocked_on_pe[0])
    if await spend_capped(session, tenant_id=tenant_id):
        causes.append("spend_cap")
    if await credits_exhausted(session, tenant_id=tenant_id):
        causes.append("no_credits")
    if not causes:
        return None
    return HealthSignal(rule="outbound_blocked", severity="stop", causes=tuple(causes))


def _cap_utilisation(
    *, minutes_used: Decimal, spend_used: Decimal, cap_min: int | None, cap_spend: Decimal | None
) -> int | None:
    """How much of the ceiling in force is gone, as a whole percent — or None if no
    ceiling is in force.

    TWO ceilings bind independently (`billing/caps.py`: minutes and rupees, each the
    stricter of the admin's and the client's), so the account is as close to stopping as
    its NEARER one. Taking the maximum of the two utilisations is what makes a single
    percentage honest; averaging them would hide a minute cap that is one call from
    biting behind a rupee cap that is barely touched.

    Integer arithmetic on Decimals throughout — no float ever touches a rupee (hard
    rule 7), and the answer is a percentage for a screen, not a money value.
    """
    utilisations: list[int] = []
    if cap_min is not None and cap_min > 0:
        utilisations.append(int(minutes_used * 100 // cap_min))
    if cap_spend is not None and cap_spend > 0:
        utilisations.append(int(spend_used * 100 // cap_spend))
    return max(utilisations) if utilisations else None


async def tenant_health(
    session: AsyncSession, *, account: Account, now: datetime | None = None
) -> ClientHealth | None:
    """THE per-account judgement, on the caller's RLS-scoped session — or None when
    there is nothing wrong.

    The same split `admin/holds.py` makes between `read_tenant_holds` (one tenant, the
    caller's session) and `held_tenants` (the walk), and for the same two reasons: the
    judgement is the part worth reading and testing on its own, and keeping it on a
    passed-in session means it cannot acquire a cross-tenant read by accident — it has
    no way to open one.

    `now` is a parameter because the WALK has to pass one: `client_health` takes a single
    clock for the whole board so two accounts judged a second apart cannot be ranked
    against each other across a window boundary. Defaulted rather than required so a
    single-account caller does not have to invent an instant it does not care about.
    """
    now = now or datetime.now(UTC)
    window_start = now - timedelta(days=WINDOW_DAYS)
    prev_start = now - timedelta(days=WINDOW_DAYS * 2)

    facts = (
        await session.execute(
            text(_FACTS), {"window_start": window_start, "prev_start": prev_start}
        )
    ).first()
    assert facts is not None, "an aggregate-only SELECT always returns exactly one row"

    volume = _call_volume(
        calls_7d=int(facts[0] or 0),
        calls_prev_7d=int(facts[1] or 0),
        last_call_at=facts[2],
        created_at=account.created_at,
        now=now,
    )
    signals: list[HealthSignal] = []
    volume_signal = _volume_signal(volume)
    if volume_signal is not None:
        signals.append(volume_signal)

    if _dials_out(outbound_agents=int(facts[5] or 0), campaigns=int(facts[6] or 0)):
        blocked = await _outbound_blocked(session, tenant_id=account.tenant_id)
        if blocked is not None:
            signals.append(blocked)

    counters = await read_spend_counters(session, tenant_id=account.tenant_id)
    caps = await read_caps(session, tenant_id=account.tenant_id)
    cap_spend = caps.effective_cap_spend
    utilisation = _cap_utilisation(
        minutes_used=counters.minutes_used,
        spend_used=counters.spend_used,
        cap_min=caps.effective_cap_min,
        cap_spend=cap_spend,
    )
    # Only the APPROACH is a signal. Having ARRIVED is `outbound_blocked`'s `spend_cap`
    # cause, and reporting both would be one fact wearing two rows.
    if utilisation is not None and utilisation >= CAP_WARN_PCT and not counters.capped:
        signals.append(HealthSignal(rule="spend_cap_near", severity="warn", count=utilisation))

    failed_deliveries = int(facts[3] or 0)
    if failed_deliveries:
        signals.append(
            HealthSignal(rule="deliveries_failing", severity="stop", count=failed_deliveries)
        )
    kb_waiting = int(facts[4] or 0)
    if kb_waiting:
        signals.append(HealthSignal(rule="knowledge_waiting", severity="warn", count=kb_waiting))

    if not signals:
        return None
    return ClientHealth(
        tenant_id=account.tenant_id,
        name=account.name,
        slug=account.slug,
        plan_tier=account.plan_tier,
        status=account.status,
        severity="stop" if any(s.severity == "stop" for s in signals) else "warn",
        signals=tuple(signals),
        volume=volume,
        spend_used_inr=counters.spend_used,
        spend_cap_inr=cap_spend,
    )


async def client_health(directory: AsyncSession) -> list[ClientHealth]:
    """Every live account with at least one signal, worst first.

    `directory` must be an `admin_session()` — the only session that can enumerate
    tenants (b57e2f9c4a13). Each account is then ENTERED with its own GUC, so every fact
    is read under ordinary RLS and this function holds no cross-tenant view of any tenant
    table at any instant.

    One clock for the whole walk, not one per account: two accounts judged a second apart
    against different window boundaries can rank against each other on an edge nobody can
    reproduce.
    """
    now = datetime.now(UTC)
    started = perf_counter()

    rows = (await directory.execute(text(_DIRECTORY), {"ended": list(_ENDED_STATUSES)})).all()

    board: list[ClientHealth] = []
    for org in rows:
        account = Account(
            tenant_id=UUID(str(org[0])),
            name=str(org[1]),
            slug=str(org[2]),
            status=str(org[3]),
            plan_tier=str(org[4]),
            created_at=org[5],
        )
        async with tenant_session(account.tenant_id) as scoped:
            row = await tenant_health(scoped, account=account, now=now)
        if row is not None:
            board.append(row)

    elapsed = perf_counter() - started
    if elapsed > WALK_BUDGET_S:
        # Ids and counts only, never a client name (the same log discipline as
        # `warn_no_plan_in_effect`). An operator reading this has the two numbers that
        # decide the fix, and the remedy is on the line rather than in this module.
        log.warning(
            "client_health_walk_over_budget",
            extra={
                "accounts": len(rows),
                "elapsed_s": round(elapsed, 2),
                "budget_s": WALK_BUDGET_S,
                "remedy": "the client list has outgrown the per-tenant walk — "
                "materialize tenant_health (admin/health.py)",
            },
        )
    return sorted(board, key=_triage_order)


def _triage_order(row: ClientHealth) -> tuple[int, int, str]:
    """Worst first, and explainable in one sentence: the account with the most things
    BROKEN, then the account with the most things about to break, then by name.

    No score. A weighted number would have to be defended every time somebody disagreed
    with the weights, and it would put a figure on the screen that looks measured and is
    not — the same objection `holds.ts` makes to inventing an SLA. Counting is
    arithmetic an operator can check by looking at the row.

    Name is the final tie-break rather than signup date, because the order has to be
    STABLE across polls: two accounts with identical signals swapping places every two
    minutes is a list nobody can keep their place in.
    """
    stops = sum(1 for signal in row.signals if signal.severity == "stop")
    warns = len(row.signals) - stops
    return (-stops, -warns, row.name)


__all__ = [
    "CAP_WARN_PCT",
    "TREND_BASELINE_MIN",
    "TREND_DECLINE_PCT",
    "WALK_BUDGET_S",
    "WINDOW_DAYS",
    "Account",
    "CallBasis",
    "CallVolume",
    "ClientHealth",
    "HealthSignal",
    "Severity",
    "client_health",
    "tenant_health",
]
