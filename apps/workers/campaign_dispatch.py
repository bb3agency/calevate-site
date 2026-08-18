"""Campaign dispatcher — the loop that turns contact rows into dials (FLOWS §5).

The concurrency doctrine, in the order FLOWS §5 states it, because one client's
campaign must never starve another's inbound receptionist:

1. `platform_lines_total` (engine verification item 8, a config value for now)
2. minus `inbound_reserve` (default 30%, min 4 lines) → the OUTBOUND pool
3. per-tenant `concurrency_ceiling` (plans row, default 10)
4. per-campaign slider ≤ tenant ceiling

Active-call counts come from OUR `calls` table (status queued/ringing/in_progress),
which the webhook receiver and reconciliation poller keep current — the engine's own
view arrives through exactly those paths, so a separate "live count" API call would be
the same data, later.

TWO GATES RUN HERE, and they answer different questions:

- `campaigns.service.dispatch_blockers`, ONCE PER CAMPAIGN, in the claiming
  transaction: the §3 paperwork — Calevate's TM registration, the client's PE
  registration and TM link, the consent provenance of the list, the DLT voice template,
  the calling number's series and header registration. Launch checked all of it once;
  registrars and TSPs withdraw things while campaigns run, and `resume` is a bare CAS
  with no gate on it at all.
- `compliance.service.check_dispatch`, ONCE PER CONTACT: the platform halt, the agent,
  the tenant's cap and wallet, the calling hour, and the DNC list. The launch scrub was
  UX; this is the enforcement — a number can join the DNC list between launch and dial,
  and hard rule 5 says additions propagate before the next dispatch tick. This loop IS
  the dispatch tick.

A THIRD thing happens here, before either gate: **scheduled campaigns start.** A client
can set a one-time start (`campaigns.schedule`, `apps/api/campaigns/scheduling.py`) and
this tick is what fires it — through `launch_campaign`, the same function the Launch
button calls, so the full launch gate runs AT FIRE TIME rather than at the moment a
human picked a date. Starting is not dialling: a campaign started at 22:00 becomes
`running` and dials nothing until `calling_hours` and the per-dial gate agree.

Claiming is CAS: `pending → dialing` by conditional UPDATE with SKIP LOCKED, so N
dispatcher processes never double-dial a contact. The claim COMMITS before the first
dial and each dial gets its own transaction — see `_dispatch_for_campaign` for why a
shared one re-rings people a cancelled tick has already called.

COST SHAPE (D-57). A tick is ONE query — `dispatch_scan()`, the migration
`a8d4f21c9b06` function — plus, per campaign it actually dials for, one tenant session
to read its budget, one claiming transaction, one per contact dialled, and one to close
the campaign out. The per-contact transactions are the price of not double-dialling, and
they are cheap next to the engine round trip they no longer hold a connection open
across.

Two shapes preceded it, both measured on the development database, both for a job
scheduled every 30 seconds:

    one transaction + two queries per ORGANIZATION   15,941 sessions   44.9s
    one transaction + one query per DISPATCHABLE tenant  12,070 sessions   22.9s
    one query, server-side loop (now)                 ~0 + per-campaign  ~0.25s

The middle one is where the previous version stopped, and its own docstring named the
reason it could go no further: rules 1+2 need the PLATFORM-WIDE count of active outbound
lines, `calls` is FORCE-RLS'd, and that count therefore only exists inside a tenant
session — so the tick had to open one for every tenant that could be holding a line,
whether or not it had anything to dial. It called closing that a tenancy change needing
a migration, and proposed two ways: a GUC that widens `campaigns`/`calls`, or an
ops-owned global index of (tenant, running campaigns, live lines).

D-57 took neither. **The loop moved into Postgres instead of the tenancy model moving
at all**: `dispatch_scan()` is SECURITY INVOKER plpgsql that walks the same tenants and
asks the same two questions under the same per-tenant `app.tenant_id`, one `set_config`
per tenant instead of one connection. Nothing is widened, nothing is exempted, no table
was added — what disappeared is the 12,070 connection checkouts, which the measurement
said were two thirds of the cost (see `alembic/versions/a8d4f21c9b06_*.py` for the
full split and for why the rejected `SECURITY DEFINER` version is a hard-rule violation
wearing a function's clothes).

What the scan still cannot see, stated plainly: it is a superset in the same two ways
`engine_agent_routes` is, and it does NOT know whether a running campaign has a contact
DUE — that stays behind RLS inside the claiming transaction, and narrowing on it would
be wrong anyway, because a running campaign with nothing due is exactly the one that
needs a visit to be auto-completed and to have its stranded `dialing` rows reaped.
"""

from __future__ import annotations

import secrets
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, NamedTuple
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.service import (
    UNCONFIRMED_ENGINE_CALL_PREFIX,
    DialUnconfirmedError,
    dispatch_call,
)
from apps.api.billing.plans import NOW_SQL, plan_in_effect_sql
from apps.api.campaigns.complaint_spike import check_complaint_spike
from apps.api.campaigns.scheduling import complete_or_rearm, due_schedules, fire_schedule
from apps.api.campaigns.service import (
    campaign_dialable_now,
    campaign_window_open,
    dispatch_blockers,
)

# Module import (not `from ... import ist_now`) so tests that pin the compliance
# clock pin THIS check too — the campaign window and the per-dial gate must agree
# on what time it is.
from apps.api.compliance import service as compliance_service
from apps.api.compliance.service import PERSON_LEVEL_REFUSALS, check_dispatch
from apps.api.core.alerting import (
    alert,
    record_campaign_dials,
    record_compliance_block,
    record_dispatch_tick,
)
from apps.api.core.errors import InvalidStatusTransitionError
from apps.api.core.loadshed import get_platform_status
from apps.api.core.logging import get_logger
from apps.api.core.redis import get_redis
from apps.api.core.settings import get_settings
from apps.api.db.result import rowcount_of
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.integrations import service as integrations

log = get_logger(__name__)

# Until engine verification item 8 produces the real numbers, the pool is a config
# default sized for the pilot. It lives here as ONE constant so the pilot's measured
# value has exactly one place to land (or move to engine_capacity when that ships).
PLATFORM_LINES_TOTAL = 10
MIN_INBOUND_RESERVE = 4
ACTIVE_STATUSES = ("queued", "ringing", "in_progress")

# What a tenant with no `plans` row is allowed (FLOWS §5 rule 3).
DEFAULT_CONCURRENCY_CEILING = 10

# A call row is only evidence of an occupied LINE while it is fresh. Rows can strand in
# `queued`/`in_progress` when an engine event is lost — the reconciliation poller
# eventually corrects them, but until it does, counting them would let a handful of
# stale rows permanently zero the outbound pool and silently stop every campaign on the
# platform. Nothing we bill for runs an hour, so an hour is comfortably past "live".
#
# A `timedelta` bound as a parameter rather than the SQL literal it used to be: it is
# now read by `dispatch_scan()` too, and a constant that reaches two readers through an
# f-string into SQL is a constant with two chances to drift.
ACTIVE_CALL_HORIZON = timedelta(hours=1)

# How often this tick runs. `settings.py` BUILDS its cron registration from these, so
# the schedule and everything below that reasons about the schedule cannot disagree.
TICK_INTERVAL_S = 30
TICK_SECONDS = frozenset(range(0, 60, TICK_INTERVAL_S))

# ONE tick at a time, platform-wide. See `_tick_lease` for why arq does not give us this
# and why the answer is not `cron(job_id=...)`.
_TICK_LEASE_KEY = "calevate:campaign_dispatch:tick"
# Longer than `WorkerSettings.job_timeout` (300s), which is the longest a tick can run
# before arq cancels it: a lease that expired UNDER a still-running tick would hand the
# shared line pool to a second one, which is the exact failure it exists to prevent.
# `settings.py` asserts the relationship at import so the two numbers cannot drift.
TICK_LEASE_TTL_S = 330


class TenantWork(NamedTuple):
    """One row of `dispatch_scan()`: a tenant that is holding lines, or has work, or both."""

    tenant_id: UUID
    active_outbound: int
    has_running_campaign: bool
    # A scheduled campaign whose start time has ARRIVED. A coarse screen, deliberately:
    # `scheduling.due_schedules()` stays the authority on what a schedule means (the
    # `kind` guard, the offset requirement), and this is a proven superset of it — the
    # same relationship `engine_agent_routes` has with the tick. Migration c7e4b19d3f52
    # argues why a superset here and a subset never.
    has_due_schedule: bool


async def _tenants_with_work() -> list[TenantWork]:
    """The tenants a tick has any reason to touch — ONE query, RLS fully applied.

    THE SHAPE OF THE TICK IS THIS FUNCTION, and it has been rewritten twice. It was
    `SELECT id FROM organizations` under `admin_session` (one transaction per
    ORGANIZATION, 15,941 sessions / 44.9s), then `SELECT DISTINCT tenant_id FROM
    engine_agent_routes` followed by one `tenant_session` per row (12,070 sessions /
    22.9s). Both were a tick that cannot finish inside its own 30s interval, and an
    overrun tick does not dial slowly: the next tick's due contacts pile up behind it
    and the campaign silently stops dialling while the UI still says "running".

    `dispatch_scan()` (migration a8d4f21c9b06) does the SAME walk the second version
    did — `engine_agent_routes`, the global un-RLS'd routing bridge that
    `dispatcher.py` and `ingest_engine_event` also resolve through, so no exemption is
    needed for the enumeration (hard rule 1, `db/registry.py`) — and asks each tenant's
    two screening questions with `app.tenant_id` set to that ONE tenant. The policies
    are the same, the answers are the same; what is gone is a connection checkout per
    tenant, which the measurement said was two thirds of the bill.

    `engine_agent_routes` remains a proven SUPERSET of what a tick needs, on both counts:

    - a campaign cannot launch unless its agent is `live` (`launch_blockers`'
      `agent_not_live`), and `publish_agent` writes the route row in the SAME
      transaction that sets `status = 'live'` — so every tenant with a running campaign
      has a route;
    - an outbound `calls` row is only ever created for a published agent, so every
      tenant that can occupy a line has a route too, and the platform-wide active count
      (rules 1+2) stays complete.

    Unfiltered on `active`, like `dispatcher.py`: an agent unpublished mid-campaign
    still leaves live calls to count. Ordered by tenant id inside the function, so the
    order in which tenants compete for the shared pool is stable across ticks rather
    than planner-dependent.

    **Tenants with neither a live line nor a running campaign are not returned at all**,
    which is what makes the tick's session count proportional to WORK. Their absence is
    not a silent cap: a tenant is omitted only when the database has just answered
    "nothing here" for it under its own policies, and `active_outbound` for an omitted
    tenant is zero by construction, so the platform total below stays exact.
    """
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT scanned_tenant_id, active_outbound, has_running_campaign, "
                    "  has_due_schedule "
                    "FROM dispatch_scan(:statuses, :horizon)"
                ),
                {"statuses": list(ACTIVE_STATUSES), "horizon": ACTIVE_CALL_HORIZON},
            )
        ).all()
    return [TenantWork(UUID(str(row[0])), int(row[1]), bool(row[2]), bool(row[3])) for row in rows]


@asynccontextmanager
async def _tick_lease() -> AsyncIterator[bool]:
    """Single-flight: yields True to the tick that may run, False to one that must not.

    **ARQ DOES NOT PREVENT TWO TICKS OVERLAPPING, and this was a live correctness bug.**
    arq 0.28 gives a cron job the id `f'{name}:{to_unix_ms(next_run)}'`
    (`arq/worker.py::run_cron`), and the in-progress key that dedupes it is that id —
    `arq/constants.py` says so in the comment on `keep_cronjob_progress`: "this can be a
    long time since each cron job has an ID that is unique for the INTENDED EXECUTION
    TIME". So the key stops two WORKERS running the tick scheduled for :30; it does
    nothing about the tick scheduled for :30 starting while the :00 one is still going,
    because those are different ids. arq's own issue #459 confirms the shape and names
    the only built-in alternative — a fixed `cron(job_id=...)` — which we cannot use
    here: a fixed id keeps its in-progress key for `keep_cronjob_progress` = 60s AFTER
    the job ends, so a 30-second tick would silently become a 60-second one.

    What overlap actually breaks is worth being precise about, because the scary version
    is already prevented. Two ticks CANNOT double-dial a person: the claim in
    `_dispatch_for_campaign` is a conditional UPDATE off `status = 'pending'` with
    `FOR UPDATE SKIP LOCKED`, so the second tick skips whatever the first has locked.
    What they can both do is READ-THEN-ACT on the shared line pool — each computes
    `global_budget = pool - total_active` from the same observation and each spends it —
    and the pool is what keeps another client's inbound receptionist answering
    (FLOWS §5 rules 1+2). BACKEND-PATTERNS §5 calls read-then-write the thing to replace
    with a CAS or a lock; there is no row to CAS a platform-wide budget against, so it
    is a lock.

    Redis, not a Postgres advisory lock, for two reasons: a session-scoped advisory lock
    would hold one of the worker's 16 pooled connections for the whole tick, and arq
    already requires Redis to have delivered this job at all — so no Redis means no tick,
    and the lease adds no failure mode that was not already fatal. `SET NX PX` +
    compare-and-delete is the primitive BACKEND-PATTERNS §5 names and
    `compliance/audit.py` already uses; this is that, not a second one.

    FAILS OPEN on a Redis error, like the audit chain's lock: a tick that refuses to run
    because Redis hiccuped is a campaign that stops dialling, and the claim CAS still
    stands between that and a double dial.

    The token is `secrets.token_hex`, not a uuid7 — it exists to make the release safe
    against a lease that has already expired and been retaken, which wants
    unpredictability rather than the repo's time-ordered id convention.
    """
    redis = get_redis()
    token = secrets.token_hex(16)
    held = False
    try:
        held = bool(await redis.set(_TICK_LEASE_KEY, token, nx=True, px=TICK_LEASE_TTL_S * 1000))
    except Exception:
        log.warning("dispatch_tick_lease_unavailable")
        yield True
        return
    try:
        yield held
    finally:
        if held:
            try:
                # Compare-and-delete: never release a lease the NEXT tick now holds.
                await redis.eval(  # type: ignore[misc]
                    "if redis.call('get', KEYS[1]) == ARGV[1] then "
                    "return redis.call('del', KEYS[1]) else return 0 end",
                    1,
                    _TICK_LEASE_KEY,
                    token,
                )
            except Exception:
                log.warning("dispatch_tick_lease_release_failed")


def _outbound_pool() -> int:
    settings = get_settings()
    reserve = max(MIN_INBOUND_RESERVE, int(PLATFORM_LINES_TOTAL * settings.inbound_reserve_ratio))
    return max(0, PLATFORM_LINES_TOTAL - reserve)


# The tenant's BUDGET read, asked only of tenants `dispatch_scan()` said have a running
# campaign. Built once at import: `text()` per tenant was measurable client CPU when
# this ran 12,070 times a tick, and it is a constant either way.
#
# The ceiling is a SCALAR SUBQUERY, not a join. `plans` carries
# effective_from/effective_to, so a tenant that ever changed plan has several rows — and
# joining campaigns to plans on tenant_id alone multiplies every campaign by the client's
# billing history, dispatching it once per plan row. The symptom is a campaign dialling
# twice its slider because the client upgraded last month. Newest row wins, which is the
# rule invoice.py already uses for the same table.
#
# The active-line count that used to be this statement's first column is gone: it now
# comes from `dispatch_scan()`, which counted it for the platform total in the same
# breath. Reading it twice would be two observations a few milliseconds apart, and rules
# 1-3 only add up if the tenant's share and the platform total come from ONE of them.
_TENANT_BUDGET_SQL = text(
    # The plan IN EFFECT, not the newest row: a ceiling staged for next month must not
    # throttle this month's dialling, and one whose window has closed must not keep
    # granting lines.
    f"SELECT ({plan_in_effect_sql('concurrency_ceiling', at=NOW_SQL)}), "
    # Same reason this is a SUBQUERY and not a join to the one above: `campaigns` joined
    # to `plans` is exactly the multiplication described above. `ORDER BY` inside the
    # aggregate keeps the oldest-campaign-first rule the tenant budget depends on.
    "  (SELECT coalesce(json_agg(json_build_object("
    "       'id', c.id, 'concurrency', c.concurrency, "
    "       'retry_policy', c.retry_policy, 'calling_hours', c.calling_hours"
    "     ) ORDER BY c.created_at, c.id), '[]'::json) "
    "   FROM campaigns c WHERE c.status = 'running')"
)


async def dispatch_campaign_tick(ctx: dict[str, Any]) -> str:
    """One tick: claim due contacts up to every ceiling, gate each, dial the lawful.

    Runs every `TICK_INTERVAL_S` seconds, ONE AT A TIME — see `_tick_lease` for why arq
    does not guarantee that and what two overlapping ticks would spend twice. The big
    red switch is checked ONCE up front — it halts all tenants (FLOWS §5), so there is no
    reason to walk the campaign list to discover it per contact.

    The lease is taken before anything else so that "one tick at a time" is a property of
    the whole function rather than of the part somebody remembered to guard.
    """
    started = time.perf_counter()
    async with _tick_lease() as held:
        if not held:
            # NOT a silent skip. A refused lease means the previous tick is STILL RUNNING
            # past its own interval, which is the failure this tick's whole cost shape
            # exists to prevent, and it is invisible from the outside: campaigns just
            # dial late. Alerting is the only thing that turns it back into a symptom.
            alert(
                "WORKER_STALL",
                "dispatch_tick_overlap",
                detail=f"previous tick still running after {TICK_INTERVAL_S}s",
            )
            return "skipped_previous_tick_running"
        outcome = await _run_tick()

    elapsed = time.perf_counter() - started
    record_dispatch_tick(elapsed)
    if elapsed > TICK_INTERVAL_S:
        alert(
            "WORKER_STALL",
            "dispatch_tick_overrun",
            detail=f"tick took {elapsed:.1f}s, interval is {TICK_INTERVAL_S}s",
        )
    return outcome


async def _run_tick() -> str:
    """The tick's actual work, under the lease. Split out so the lease has one owner."""
    platform = await get_platform_status()
    if platform.outbound_halted:
        return "halted_by_big_red_switch"

    pool = _outbound_pool()
    if pool <= 0:
        alert("WORKER_STALL", "outbound_pool_empty", detail="reserve >= total lines")
        return "no_outbound_pool"

    # One query for the whole platform: who is holding an outbound line, and who has a
    # campaign to dial. Tenants with neither are not in the result and cost nothing.
    tenants = await _tenants_with_work()

    # Rules 1+2 are platform-wide, and this sum is exact: a tenant `dispatch_scan()`
    # omitted has zero live outbound calls by the function's own filter.
    total_active = sum(work.active_outbound for work in tenants)

    running: list[tuple[UUID, UUID, int, dict[str, Any]]] = []  # (tenant, campaign, slots, retry)
    started = 0
    for work in tenants:
        if not (work.has_running_campaign or work.has_due_schedule):
            # Holding lines but nothing to dial. It has already been counted into
            # `total_active`; there is nothing a session could add.
            continue
        # Scheduled starts FIRST, so a campaign whose start time arrived this tick dials
        # in this tick rather than the next one — the budget read below then sees it as
        # `running` like any other. The 30 seconds saved are not the point; the point is
        # that "starts at 10:00" and "first dial at 10:00:30" differ by a tick's worth of
        # explaining. Placed after the big red switch check at the top of this function,
        # which is what stops a schedule firing into a halted platform.
        started_here = await _fire_due_schedules(work.tenant_id) if work.has_due_schedule else 0
        started += started_here
        if not (work.has_running_campaign or started_here):
            continue
        async with tenant_session(work.tenant_id) as session:
            row = (await session.execute(_TENANT_BUDGET_SQL, {"tid": work.tenant_id})).first()
            ceiling = int(
                row[0] if row is not None and row[0] is not None else DEFAULT_CONCURRENCY_CEILING
            )
            # The campaign may have been paused between the scan and this read — that is
            # a race the client WINS, and it costs one session, not a dial.
            campaigns: list[dict[str, Any]] = list(row[1] or []) if row is not None else []
            if not campaigns:
                continue

            # Rule 3 is a TENANT budget, spent ONCE across that tenant's campaigns.
            # Computing it per campaign let a tenant with two running campaigns claim
            # twice its ceiling — and the surplus comes out of the shared pool that
            # keeps another tenant's receptionist answering (rule 1's whole point).
            # Oldest campaign first, so which one gets the lines is deterministic
            # rather than whatever order the planner returned.
            tenant_budget = max(0, ceiling - work.active_outbound)

            for campaign in campaigns:
                campaign_id = campaign["id"]
                slider = campaign["concurrency"]
                retry_policy = campaign["retry_policy"]
                calling_hours = campaign["calling_hours"]
                if tenant_budget <= 0:
                    break
                # Per-campaign calling window (narrowing-only; the create path
                # refuses anything outside 09:00-21:00 IST, so this can only ever
                # SHRINK when a campaign dials). Checked BEFORE claiming: a closed
                # window blocks every contact identically, so skipping the campaign
                # outright is cheaper and cleaner than claim-then-refund — no
                # attempts burned, no compensating UPDATE. The per-dial gate still
                # runs for everything claimed below, which keeps the platform
                # window enforced there regardless — defense in depth.
                if not campaign_window_open(calling_hours, compliance_service.ist_now()):
                    continue
                # Rule 4 under rule 3: the slider, bounded by what the tenant has left.
                slots = min(int(slider), tenant_budget)
                if slots > 0:
                    tenant_budget -= slots
                    running.append(
                        (work.tenant_id, UUID(str(campaign_id)), slots, retry_policy or {})
                    )

    if not running:
        # `started` is always reported, even as 0: a ternary here would add a branch to
        # the dial path whose only job is to make a log line shorter, and the ratchet
        # would then be policing a cosmetic decision.
        return f"no_running_campaigns started={started}"

    # Rule 1+2: what is left of the shared pool after everyone's active calls.
    global_budget = max(0, pool - total_active)
    if global_budget == 0:
        return f"pool_saturated active={total_active}"

    dialled, blocked, exhausted = 0, 0, 0
    for tenant_id, campaign_id, slots, retry_policy in running:
        if global_budget <= 0:
            break
        take = min(slots, global_budget)
        results = await _dispatch_for_campaign(tenant_id, campaign_id, take, retry_policy)
        dialled += results["dialled"]
        blocked += results["blocked"]
        exhausted += results["exhausted"]
        global_budget -= results["dialled"]

    if dialled or blocked:
        record_campaign_dials(dialled=dialled, blocked=blocked)
    return f"dialled={dialled} blocked={blocked} exhausted={exhausted} started={started}"


async def _fire_due_schedules(tenant_id: UUID) -> int:
    """Start this tenant's campaigns whose scheduled time has arrived. Returns how many.

    **ONE TRANSACTION PER CAMPAIGN, and that is the whole double-launch defence.**
    `fire_schedule` runs the full launch gate and then CASes `scheduled → running`; the
    CAS is what makes a schedule fire exactly once, and it can only do that job if the
    loser has its own transaction to roll back. Two ticks racing (the tick lease fails
    open on a Redis error — `_tick_lease`) both read the campaign as due, both run the
    gate, and the second one's `UPDATE ... WHERE status IN ('draft','scheduled')` blocks
    on the winner's row lock, re-reads `running`, and returns zero rows. Sharing one
    transaction across the tenant's campaigns would roll the winner's own launch back
    alongside the loser's scrub, and the campaign would fire again next tick.

    `InvalidStatusTransitionError` is therefore the EXPECTED outcome of the loser, not a
    failure: it is the invariant holding. Counted, logged at info, never alerted.

    The clock is read ONCE for the whole tenant so every campaign in this tick is judged
    against the same instant — a schedule due at 10:00:00.4 and one due at 10:00:00.6
    should not depend on which of them we looked at first. A REPEAT needs that same
    instant for a second reason: it decides whether an occurrence is inside its catch-up
    window or has been missed, and two campaigns due together must not fall on opposite
    sides of that line because the loop reached them a millisecond apart.

    `fire_schedule` gains one more outcome for repeats — `skipped`, an occurrence that
    came due too late to still mean what it said. It counts as zero starts here, like
    `blocked`: nothing is running, so there is no budget worth reading for it.
    """
    now = datetime.now(UTC)
    async with tenant_session(tenant_id) as session:
        due = await due_schedules(session, now=now)
    if not due:
        return 0

    started = 0
    for schedule in due:
        try:
            async with tenant_session(tenant_id) as session:
                outcome = await fire_schedule(session, tenant_id=tenant_id, due=schedule, now=now)
        except InvalidStatusTransitionError:
            # Lost the CAS — somebody (another tick, or a client pressing Launch) started
            # this campaign first. The transaction rolled back on the way out of the
            # context manager, so nothing this branch did survives.
            log.info("campaign_schedule_raced", extra={"campaign_id": str(schedule.campaign_id)})
            continue
        if outcome == "fired":
            started += 1
    return started


async def _dispatch_for_campaign(
    tenant_id: UUID, campaign_id: UUID, slots: int, retry_policy: dict[str, Any]
) -> dict[str, int]:
    """One campaign's slice of a tick: reap, gate, claim — then dial, one at a time.

    **THE CLAIM COMMITS BEFORE THE FIRST DIAL, AND EVERY DIAL IS ITS OWN TRANSACTION.**
    That split is the whole double-dial defence, and it is not a refactor.

    With one transaction around the batch, anything that escapes the loop after the
    engine has accepted a call rolls the CLAIM back too — the contact returns to
    `pending` although their phone has already rung, and the next tick, thirty seconds
    later, rings them again. `except Exception` around the engine call does not help:
    the escape that matters is `asyncio.CancelledError`, which is a `BaseException` and
    is what a cron tick overrunning `job_timeout` (300s) or a worker caught mid-tick by
    a deploy actually raises — and it is one of the three exceptions arq 0.28 RETRIES.

    With the claim committed first, that same failure leaves the contact in `dialing`,
    pointing at the call row `dispatch_call` committed before it dialled. Nothing
    re-claims it; `_reap_stuck_dialing` settles it after 30 minutes — back on the ladder
    if the vendor named the call, terminally if it never did, because a dial we cannot
    prove did not ring must not be retried. One dial, one attempt, no second ring. The
    split also stops a DB transaction being held open across an engine HTTP round trip.
    """
    max_attempts = int(retry_policy.get("max_attempts", 3))
    dialled = blocked = exhausted = 0

    async with tenant_session(tenant_id) as session:
        await _reap_stuck_dialing(session, campaign_id, tenant_id=tenant_id)

        # THE STANDING COMPLIANCE GATE (hard rule 5), asked in the SAME transaction
        # that claims the contacts, so a registration revoked a moment ago cannot slip
        # between the check and the claim.
        #
        # `check_dispatch` below is per NUMBER and per AGENT; it structurally cannot see
        # the campaign's DLT template, its calling number's header registration, the
        # client's Principal Entity registration or Calevate's own TM registration.
        # Those were verified once, at launch, and every one of them can be withdrawn by
        # a registrar or a TSP while the campaign runs. `resume` makes it worse: it is a
        # bare CAS from `paused` back to `running` with no gate at all.
        #
        # Checked BEFORE claiming, for the same reason the calling window is: it blocks
        # every contact of this campaign identically, so skipping outright costs no
        # attempts and needs no compensating refund.
        standing = await dispatch_blockers(session, tenant_id=tenant_id, campaign_id=campaign_id)
        if standing:
            for blocker in standing:
                record_compliance_block(rule=blocker.rule)
            # Rules and ids only — never a number, never a client's wording (rule 6).
            log.warning(
                "campaign_dispatch_blocked",
                extra={
                    "campaign_id": str(campaign_id),
                    "rules": ",".join(b.rule for b in standing),
                },
            )
            return {"dialled": 0, "blocked": 0, "exhausted": 0}

        # FLOWS §5's OTHER mid-campaign safety, and the one the comment inside the claim
        # below has referred to since D-149 without anything implementing it: too many of
        # this campaign's conversations ending in "never call me again" pauses it and
        # pages a human (`campaigns/complaint_spike.py` argues the three thresholds).
        #
        # Here rather than inside the claim, beside the standing gate, for the identical
        # reason: it is a fact about the CAMPAIGN, so it blocks every contact alike and
        # costs no attempts if it is asked first. It runs in the claiming transaction, so
        # the pause it writes and the refusal to dial commit together — a pause that
        # committed after one more contact had been claimed would be the safety arriving
        # one ring late.
        if await check_complaint_spike(session, tenant_id=tenant_id, campaign_id=campaign_id):
            return {"dialled": 0, "blocked": 0, "exhausted": 0}

        # CAS claim: pending → dialing, oldest first, due-for-retry respected.
        #
        # MATERIALIZED and `ORDER BY created_at, id` are both load-bearing, and the
        # concurrency test is what proved it. Written the obvious way —
        # `WHERE id IN (SELECT ... LIMIT :n FOR UPDATE SKIP LOCKED)` — the planner is
        # free to put the LIMIT subquery on the inner side of a nested-loop semi-join
        # and RESCAN it once per candidate row. `add_contacts` inserts a whole CSV in
        # one transaction, so every contact shares a `created_at` to the microsecond;
        # each rescan then breaks that tie differently and returns a different arbitrary
        # pair, and the union of those pairs is far more than :n rows. The symptom is a
        # campaign dialling past its concurrency slider — i.e. eating the lines another
        # tenant's receptionist is holding. MATERIALIZED forces one evaluation; the
        # tiebreak on `id` makes the order total so the claim is deterministic.
        #
        # The campaign's own status is re-read HERE, inside the claiming transaction.
        # The tick chose this campaign in an earlier, separate transaction; between the
        # two the client may have hit pause — or a complaint spike / cap breach may
        # have auto-paused it (FLOWS §5's mid-campaign safeties). A pause that still
        # dials the contacts the tick had already lined up is a pause the client does
        # not believe in, and those safeties exist precisely for the moment when
        # stopping fast matters.
        claimed = (
            await session.execute(
                text(
                    "WITH picked AS MATERIALIZED ("
                    "  SELECT id FROM campaign_contacts WHERE campaign_id = :cid "
                    "  AND status = 'pending' "
                    "  AND (next_attempt_at IS NULL OR next_attempt_at <= now()) "
                    "  AND EXISTS (SELECT 1 FROM campaigns c WHERE c.id = :cid "
                    "    AND c.status = 'running') "
                    "  ORDER BY created_at, id LIMIT :n FOR UPDATE SKIP LOCKED"
                    ") "
                    "UPDATE campaign_contacts c SET status = 'dialing', "
                    "attempts = c.attempts + 1, last_attempt_at = now(), updated_at = now() "
                    "FROM picked WHERE c.id = picked.id "
                    "RETURNING c.id, c.phone_e164, c.name, c.custom, c.attempts"
                ),
                {"cid": campaign_id, "n": slots},
            )
        ).all()

        agent_id = (
            await session.execute(
                text("SELECT agent_id FROM campaigns WHERE id = :cid"), {"cid": campaign_id}
            )
        ).scalar()
    # The claim is COMMITTED here — see this function's docstring. Everything below
    # runs in its own short transaction, so losing one loses at most one dial's
    # bookkeeping and never un-rings a phone.

    for contact_id, phone, name, _custom, attempts in claimed:
        async with tenant_session(tenant_id) as session:
            # THE CAMPAIGN's own two live facts, re-read per contact for exactly the
            # reason the big red switch is: the claim COMMITTED, and everything after it
            # is a phone ringing. A pause the client pressed — or one of FLOWS §5's
            # auto-pause safeties — must stop the contacts behind the one in flight, and
            # a campaign whose narrowed window closed mid-batch must stop too. Both were
            # decided once per tick, up to a whole dial phase earlier.
            stopped = await campaign_dialable_now(
                session, campaign_id=campaign_id, now_ist=compliance_service.ist_now()
            )
            if stopped is not None:
                await _refuse_contact(session, contact_id, rule=stopped)
                blocked += 1
                continue

            # THE per-dial gate (hard rule 5). This tick is "the next dispatch tick"
            # DNC additions must precede. Its DNC read is uncached and per contact, so
            # an opt-out committed by another connection while this batch is mid-flight
            # blocks the very next contact rather than waiting for the next tick.
            decision = await check_dispatch(
                session, tenant_id=tenant_id, agent_id=UUID(str(agent_id)), phone_e164=phone
            )
            if not decision.allowed:
                await _refuse_contact(session, contact_id, rule=decision.rule or "unknown")
                blocked += 1
                continue

            try:
                # THE LINK IS WRITTEN BEFORE THE PHONE CAN RING, in `dispatch_call`'s
                # intent transaction. `last_call_id` is the ONLY join between a call and
                # the contact it was placed for — `resolve_campaign_contact` matches on
                # it — and writing it after the dial returned meant a lost response left
                # a contact with no link, which `_reap_stuck_dialing` then returned to
                # the ladder and rang a second time.
                await dispatch_call(
                    session,
                    tenant_id=tenant_id,
                    agent_id=UUID(str(agent_id)),
                    lead_id=None,
                    phone_e164=phone,
                    lead_name=name,
                    context_note=None,
                    on_reserved=_link_contact_to_call(contact_id),
                )
            except DialUnconfirmedError as unconfirmed:
                # THE THIRD OUTCOME: the engine may have started this call. Not the
                # ladder — a retry here is a second unsolicited call to somebody whose
                # phone may already have rung, which is the thing the compliance gate
                # exists to prevent. The contact is finished with, the escalation tells
                # the client a human should look, and the unconfirmed `calls` row
                # `dispatch_call` committed is what an operator reconciles against.
                await _settle_unconfirmed_dial(
                    session, contact_id, tenant_id=tenant_id, campaign_id=campaign_id
                )
                log.warning(
                    "campaign_dial_unconfirmed",
                    extra={
                        "campaign_id": str(campaign_id),
                        "call_id": str(unconfirmed.call_id),
                        "code": unconfirmed.code,
                    },
                )
                exhausted += 1
                continue
            except Exception as exc:  # engine refused BEFORE dialling: the retry ladder
                spent = await _record_failure(
                    session,
                    contact_id,
                    attempts,
                    max_attempts,
                    retry_policy,
                    tenant_id=tenant_id,
                    campaign_id=campaign_id,
                )
                log.warning(
                    "campaign_dial_failed",
                    extra={"campaign_id": str(campaign_id), "reason": type(exc).__name__},
                )
                if spent:
                    exhausted += 1
                continue

            # The contact stays `dialing` until the call actually ends — the post-call
            # pipeline calls resolve_campaign_contact() with the outcome. Marking it
            # "connected" here would claim a conversation happened because a dial was
            # accepted, and would complete the campaign while calls were still ringing.
            dialled += 1

    async with tenant_session(tenant_id) as session:
        # Campaign auto-complete: nothing pending and nothing dialing left.
        remaining = (
            await session.execute(
                text(
                    "SELECT count(*) FROM campaign_contacts WHERE campaign_id = :cid "
                    "AND status IN ('pending', 'dialing')"
                ),
                {"cid": campaign_id},
            )
        ).scalar()
        if not remaining:
            # `complete_or_rearm`, not an UPDATE to 'completed': a campaign carrying a
            # REPEAT is not finished when this run is, it is waiting for its next
            # occurrence — and `due_schedules`/`dispatch_scan()` only look at `scheduled`,
            # so completing it would silently retire the repeat after one run. What the
            # column means stays `campaigns.scheduling`'s question.
            settled = await complete_or_rearm(session, campaign_id=campaign_id)
            if settled == "completed":
                # IN THIS TRANSACTION, beside the status write that justifies it — the
                # transactional-outbox property (BACKEND-PATTERNS §4) that makes "the
                # campaign completed but the CRM never heard" and "the CRM heard about a
                # completion that rolled back" both unrepresentable. A tick that dies
                # between the UPDATE and the enqueue rolls both back and the next tick
                # re-completes the campaign, because `complete_or_rearm` is a CAS off
                # `running`.
                await emit_campaign_completed(session, tenant_id=tenant_id, campaign_id=campaign_id)
                log.info("campaign_completed", extra={"campaign_id": str(campaign_id)})
            elif settled == "scheduled":
                log.info("campaign_recurrence_rearmed", extra={"campaign_id": str(campaign_id)})

    return {"dialled": dialled, "blocked": blocked, "exhausted": exhausted}


# The `data` keys a `campaign.completed` outbound event carries (docs/WEBHOOKS.md §1.2),
# in the order `integrations.service.DEFAULT_SHEET_COLUMNS` lays them out in a
# spreadsheet. AGGREGATES AND THE CAMPAIGN'S OWN NAME ONLY — not one contact's number,
# not one contact's name. That is not squeamishness about a third party: it is what makes
# this the one event `integrations.service.body_subject` can name no subject for, so the
# forensic body is deliberately not retained and there is nothing here for a DPDP erasure
# to have to find. A per-contact roster would reverse all three of those facts.
#
# `updated_at` IS the completion instant: `complete_or_rearm`'s UPDATE wrote it with
# `now()` in this same transaction, so `completed_at` is read from the row rather than
# stamped a second time from the clock — two stamps for one event is two answers to
# "when did it finish".
_CAMPAIGN_COMPLETED_SQL = text(
    "SELECT c.name, c.updated_at, count(cc.id) AS total, "
    "  count(cc.id) FILTER (WHERE cc.status = 'connected') AS reached "
    "FROM campaigns c LEFT JOIN campaign_contacts cc ON cc.campaign_id = c.id "
    "WHERE c.id = :cid GROUP BY c.id, c.name, c.updated_at"
)


async def emit_campaign_completed(session: Any, *, tenant_id: UUID, campaign_id: UUID) -> int:
    """Tell every subscribed endpoint that a campaign finished (D-23, `campaign.completed`).

    **This event was subscribable and nothing produced it.** `campaign.completed` has
    been in `EVENT_TYPES`, in the endpoint route's `EventName` and in the integrations
    screen's checkbox list ("A campaign finishes") since D-23, and no line of code ever
    enqueued one — so a client could tick the box, see the endpoint saved, and wait
    forever. Its sibling `lead.updated` had the identical defect and was closed by
    `crm.service.emit_lead_updated`; this one waited because the only place that knows a
    campaign finished is this dispatcher.

    **Called with the CALLER'S session on purpose, and never given one of its own.** The
    outbox row has to commit with the terminal `status = 'completed'` write or the two
    can disagree, and a helper that opened its own `tenant_session` would guarantee they
    eventually do. `tests/campaign_completed_event_test.py` proves the coupling by
    failing the enqueue and asserting the campaign is still `running`.

    `contacts_reached` counts `connected` and only `connected`: that is the status
    `resolve_campaign_contact` writes when a call reached its end with `completed`, i.e.
    the customer was actually spoken to. `no_answer`, `failed` and `dnc_blocked` are
    contacts we dialled or refused to dial, and folding any of them in would report a
    reach rate the client's own call log contradicts.

    Returns the number of outbox rows written — the number of subscribed endpoints.
    """
    # `.one()` rather than `.first()` plus a defensive `if row is None: return 0`. The
    # row was UPDATEd to its terminal status in THIS transaction, so an empty result is
    # not a case to handle — it means the invariant broke, and the honest response is to
    # fail the transaction rather than silently skip an event a client subscribed to and
    # is waiting for. A branch that cannot be reached is also a branch no test can cover,
    # and the coverage ratchet counts a `pragma: no cover` as uncovered precisely so that
    # suppressing it is not an escape (D-29).
    row = (await session.execute(_CAMPAIGN_COMPLETED_SQL, {"cid": campaign_id})).one()
    return await integrations.enqueue_event(
        session,
        tenant_id=tenant_id,
        event="campaign.completed",
        data={
            "campaign_id": str(campaign_id),
            "name": row[0],
            "contacts_total": int(row[2]),
            "contacts_reached": int(row[3]),
            "completed_at": row[1].isoformat(),
        },
    )


async def resolve_campaign_contact(
    session: Any, *, tenant_id: UUID, call_id: UUID, call_status: str
) -> str | None:
    """Close the loop: a finished call decides its contact's fate (FLOWS §5).

    Called from the post-call pipeline, so `dialing` is a real state with an end, not a
    label the dispatcher writes optimistically. `completed` → connected; anything else
    (no_answer, busy, failed) → the retry ladder, which may exhaust into `failed`.

    Returns the new contact status, or None when the call was not part of a campaign —
    the overwhelmingly common case, so it costs one indexed lookup and stops.
    """
    row = (
        await session.execute(
            text(
                "SELECT cc.id, cc.attempts, c.retry_policy, cc.campaign_id "
                "FROM campaign_contacts cc "
                "JOIN campaigns c ON c.id = cc.campaign_id "
                "WHERE cc.last_call_id = :cid AND cc.status = 'dialing'"
            ),
            {"cid": call_id},
        )
    ).first()
    if row is None:
        return None
    contact_id, attempts, retry_policy, campaign_id = row
    policy: dict[str, Any] = retry_policy or {}

    if call_status == "completed":
        await session.execute(
            text(
                "UPDATE campaign_contacts SET status = 'connected', updated_at = now() "
                "WHERE id = :id AND status = 'dialing'"
            ),
            {"id": contact_id},
        )
        return "connected"

    spent = await _record_failure(
        session,
        contact_id,
        int(attempts or 0),
        int(policy.get("max_attempts", 3)),
        policy,
        tenant_id=tenant_id,
        campaign_id=UUID(str(campaign_id)),
    )
    log.info(
        "campaign_contact_unanswered",
        extra={"tenant_id": str(tenant_id), "call_status": call_status},
    )
    return "failed" if spent else "pending"


async def _refuse_contact(session: Any, contact_id: UUID, *, rule: str) -> None:
    """Settle one claimed contact the gate would not let us dial.

    TERMINAL or BACK ON THE LADDER, and the difference is `PERSON_LEVEL_REFUSALS` —
    owned by the gate module, not decided here. A refusal about the PERSON (`dnc`,
    `no_consent`) will not become false by waiting, so the contact is finished with;
    everything else — the halt, the account's lifecycle, the agent, the caps, the hour,
    the campaign's own pause or window — is a condition that clears, so the contact goes
    back to `pending` with its attempt refunded and a thirty-minute wait.

    The refund is what makes the retry ladder mean "we tried to reach this person and
    could not" rather than "we were not allowed to try": a blocked dial never rang a
    phone, and burning a rung for it would exhaust a reachable lead into `failed` on
    three refusals that were about us.

    `record_compliance_block` fires HERE, on the per-dial refusal, and it did not
    before — `runbooks/campaign-stall.md` §8 tells an operator that "a blocked dial
    increments the tick's `blocked=` count and the `compliance_blocks` metric (labelled
    by rule)", and only the first half of that sentence was true. The rule label is the
    whole diagnostic value of the metric on this path: `blocked=7` says a campaign is
    stalled, `compliance_blocks{rule="dnc"}` versus `{rule="spend_cap"}` says which desk
    it belongs on. One writer, both refusal shapes, so they can never diverge again.
    """
    record_compliance_block(rule=rule)
    terminal = rule in PERSON_LEVEL_REFUSALS
    await session.execute(
        text("UPDATE campaign_contacts SET status = :status, updated_at = now() WHERE id = :id"),
        {"status": "dnc_blocked" if terminal else "pending", "id": contact_id},
    )
    if not terminal:
        await session.execute(
            text(
                "UPDATE campaign_contacts SET next_attempt_at = now() + interval '30 minutes', "
                "attempts = attempts - 1, updated_at = now() WHERE id = :id"
            ),
            {"id": contact_id},
        )


def _link_contact_to_call(
    contact_id: UUID,
) -> Callable[[AsyncSession, UUID], Awaitable[None]]:
    """`dispatch_call`'s `on_reserved` hook: point the contact at the intent row.

    Runs INSIDE the transaction that inserts the `calls` row and commits with it, which
    is both what the FK needs (`campaign_contacts.last_call_id → calls.id`) and the whole
    point: the pointer is durable before the vendor can seize a line.
    """

    async def link(session: AsyncSession, call_id: UUID) -> None:
        await session.execute(
            text(
                "UPDATE campaign_contacts SET last_call_id = :call, updated_at = now() "
                "WHERE id = :id"
            ),
            {"call": call_id, "id": contact_id},
        )

    return link


async def _settle_unconfirmed_dial(
    session: Any, contact_id: UUID, *, tenant_id: UUID, campaign_id: UUID
) -> None:
    """A dial we cannot prove did not ring: terminal, and the client is told.

    NOT `_record_failure`'s ladder, and not `_refuse_contact`'s refund. Both of those end
    in another dial to the same person, and the one fact we have here is that this person
    may already have been called. `failed` with the escalation is the same ending an
    exhausted ladder gets — the state the client's screen already explains and the
    follow-up message already covers — so this outcome needs no vocabulary of its own on
    a screen; what tells the two apart is the `calls` row, which is `queued` with an
    `engine_call_id` we minted (`agents.service.UNCONFIRMED_ENGINE_CALL_PREFIX`).
    """
    await _exhaust_contact(session, contact_id, tenant_id=tenant_id, campaign_id=campaign_id)


async def _exhaust_contact(
    session: Any, contact_id: UUID, *, tenant_id: UUID | None, campaign_id: UUID | None
) -> None:
    """Terminal `failed` + the once-per-contact escalation. One writer, three callers:
    the spent ladder, an unconfirmed dial, and the reaper's unconfirmed backstop."""
    await session.execute(
        text("UPDATE campaign_contacts SET status = 'failed', updated_at = now() WHERE id = :id"),
        {"id": contact_id},
    )
    if tenant_id is None or campaign_id is None:
        log.info("campaign_contact_exhausted", extra={"escalation_queued": False})
        return
    # Local import: `whatsapp` is a worker peer and a module-level import here would drag
    # the notification stack into the dispatch tick's hot path.
    from apps.workers.whatsapp import enqueue_campaign_escalation

    queued = await enqueue_campaign_escalation(
        session, tenant_id=tenant_id, campaign_id=campaign_id, contact_id=contact_id
    )
    # Ids only, never the contact's number (hard rule 6).
    log.info(
        "campaign_contact_exhausted",
        extra={"campaign_id": str(campaign_id), "escalation_queued": queued},
    )


async def _reap_stuck_dialing(session: Any, campaign_id: UUID, *, tenant_id: UUID) -> int:
    """A dial whose call never produced a terminal event would pin a contact in
    `dialing` forever and the campaign would never complete. After 30 minutes — far
    longer than any call we bill for — it goes back on the ladder.

    EXCEPT when the call it is pinned to is one the vendor never named. That is the
    signature of a dial whose response we lost (`dispatch_call` commits the intent row
    with an `engine_call_id` of its own and stamps the vendor's over it only on a clean
    return), and returning THAT contact to `pending` is exactly the second ring this
    whole path exists to prevent. Those are exhausted instead, with the escalation, and
    the unconfirmed `calls` row is the operator's reconciliation handle.

    This is the backstop rather than the main defence: `_dispatch_for_campaign` settles a
    `DialUnconfirmedError` the moment it happens. What reaches here is the case that outruns
    an `except` clause — a `CancelledError` through the dial, i.e. a worker killed
    mid-tick, which is a `BaseException` and by design not caught there.
    """
    stranded = (
        (
            await session.execute(
                text(
                    "SELECT cc.id FROM campaign_contacts cc "
                    "JOIN calls c ON c.id = cc.last_call_id "
                    "WHERE cc.campaign_id = :cid AND cc.status = 'dialing' "
                    "AND cc.last_attempt_at < now() - interval '30 minutes' "
                    "AND c.engine_call_id LIKE :unconfirmed"
                ),
                {"cid": campaign_id, "unconfirmed": f"{UNCONFIRMED_ENGINE_CALL_PREFIX}%"},
            )
        )
        .scalars()
        .all()
    )
    for contact_id in stranded:
        await _exhaust_contact(
            session, UUID(str(contact_id)), tenant_id=tenant_id, campaign_id=campaign_id
        )
        log.warning(
            "campaign_dial_unconfirmed_reaped",
            extra={"campaign_id": str(campaign_id), "contact_id": str(contact_id)},
        )

    result = await session.execute(
        text(
            "UPDATE campaign_contacts SET status = 'pending', "
            "next_attempt_at = now() + interval '30 minutes', updated_at = now() "
            "WHERE campaign_id = :cid AND status = 'dialing' "
            "AND last_attempt_at < now() - interval '30 minutes'"
        ),
        {"cid": campaign_id},
    )
    return rowcount_of(result) + len(stranded)


async def _record_failure(
    session: Any,
    contact_id: UUID,
    attempts: int,
    max_attempts: int,
    retry_policy: dict[str, Any],
    *,
    tenant_id: UUID | None = None,
    campaign_id: UUID | None = None,
) -> bool:
    """no-answer/busy/failed → the FLOWS §5 retry ladder with spaced delays, and on the
    last rung the ESCALATION (FLOWS §4.5, ROADMAP §3 bullet 1).

    Returns whether this call spent the ladder, so the caller can count exhaustions.

    **Exhaustion used to be the end of the story**: the contact went `failed` and nothing
    else happened — no message, no timeline entry, no operator signal. A lead the client
    paid to generate went cold in silence. The follow-up is queued through the OUTBOX in
    THIS transaction, so it shares the fate of the status that justifies it: a rolled-back
    exhaustion cannot leave a message queued to somebody we are still trying to phone.

    `enqueue_campaign_escalation` is what makes it once-per-contact. The status
    transition cannot: `_reap_stuck_dialing` returns a stranded contact to `pending`
    with its attempts intact and no ceiling, so the same person can reach "exhausted"
    more than once, and the second message would be about the same single enquiry.

    `tenant_id`/`campaign_id` are optional so the two call sites can pass what they have;
    without them the contact is still failed correctly and the escalation is skipped
    with a log line rather than guessed at.
    """
    if attempts >= max_attempts:
        await _exhaust_contact(session, contact_id, tenant_id=tenant_id, campaign_id=campaign_id)
        return True
    backoffs = retry_policy.get("backoff_minutes") or [30, 120]
    minutes = int(backoffs[min(attempts - 1, len(backoffs) - 1)])
    # ONE CLOCK ON THIS COLUMN, and it is the database's. The rung used to be computed in
    # Python (`datetime.now(UTC) + timedelta(...)`) while the claim that reads it back
    # compares against `now()` — and `_refuse_contact` and `_reap_stuck_dialing`, the two
    # other writers of this column, both already used `now() + interval`. A worker host
    # whose clock trails the database's therefore made every rung EARLY by the skew, and
    # an early rung on a retry ladder is a second call to a person sooner than the policy
    # says. `make_interval(mins => :minutes)` is the parameterised form of the interval
    # literal the siblings use (PostgreSQL 9.4+); an interval cannot be built by
    # concatenating a bind parameter into a literal without inviting injection.
    await session.execute(
        text(
            "UPDATE campaign_contacts SET status = 'pending', "
            "next_attempt_at = now() + make_interval(mins => :minutes), "
            "updated_at = now() WHERE id = :id"
        ),
        {"minutes": minutes, "id": contact_id},
    )
    return False


__all__ = [
    "DEFAULT_CONCURRENCY_CEILING",
    "PLATFORM_LINES_TOTAL",
    "TICK_INTERVAL_S",
    "TICK_LEASE_TTL_S",
    "TICK_SECONDS",
    "TenantWork",
    "dispatch_campaign_tick",
    "emit_campaign_completed",
    "resolve_campaign_contact",
]
