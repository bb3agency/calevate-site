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

Claiming is CAS: `pending → dialing` by conditional UPDATE with SKIP LOCKED, so N
dispatcher processes never double-dial a contact. The claim COMMITS before the first
dial and each dial gets its own transaction — see `_dispatch_for_campaign` for why a
shared one re-rings people a cancelled tick has already called.

COST SHAPE. A tick is one transaction and one query per tenant in
`_dispatchable_tenants()` — tenants with a published agent — plus, per campaign it
actually dials for, one claiming transaction, one per contact dialled, and one to close
the campaign out. The per-contact transactions are the price of not double-dialling,
and they are cheap next to the engine round trip they no longer hold a connection open
across. It used to be one transaction and two queries per
ORGANIZATION (15,941 sessions / 47,825 queries / 44.9s on the development database, for
a job scheduled every 30 seconds). What is left is proportional to tenants that have
ever published an agent, NOT to tenants with a running campaign, because rules 1+2 need
the platform-wide count of active outbound lines and `calls` is FORCE-RLS'd: the count
only exists inside a tenant session. Closing that last gap is a TENANCY change, not a
refactor, and needs a decision-log entry plus a migration — either a GUC that widens
`campaigns`/`calls` by a status-and-count read the way `app.user_id` widens
`memberships`, or an ops-owned global index of (tenant, running campaigns, live lines)
maintained by the campaign lifecycle and the call state transitions. Neither belongs in
this module alone.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text

from apps.api.agents.service import dispatch_call
from apps.api.campaigns.service import campaign_window_open, dispatch_blockers

# Module import (not `from ... import ist_now`) so tests that pin the compliance
# clock pin THIS check too — the campaign window and the per-dial gate must agree
# on what time it is.
from apps.api.compliance import service as compliance_service
from apps.api.compliance.service import check_dispatch
from apps.api.core.alerting import alert, metrics_log, record_compliance_block
from apps.api.core.loadshed import get_platform_status
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.result import rowcount_of
from apps.api.db.session import tenant_session, untenanted_session

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
ACTIVE_CALL_HORIZON = "1 hour"


async def _dispatchable_tenants() -> list[UUID]:
    """Every tenant a tick could possibly dial for, or hold an outbound line for.

    THE SHAPE OF THE TICK IS THIS FUNCTION. It used to be `SELECT id FROM organizations`
    under `admin_session`, because `admin_session` can enumerate tenants but cannot read
    `campaigns` across them — so the tick opened one transaction per ORGANIZATION every
    30 seconds. Measured on the development database: 15,941 tenant sessions, 47,825
    queries, 44.9s — a tick that cannot finish inside its own 30s interval. An overrun
    tick does not dial slowly; the next tick's due contacts pile up behind it and the
    campaign silently stops dialling.

    `engine_agent_routes` is the SAME non-tenant-scoped bridge `_callable_tenants` in
    `dispatcher.py` and `ingest_engine_event` use, and it exists precisely so a
    cross-tenant resolution needs no RLS exemption (hard rule 1, `db/registry.py`). It
    is a proven SUPERSET of what this tick needs, on both counts:

    - a campaign cannot launch unless its agent is `live` (`launch_blockers`'
      `agent_not_live`), and `publish_agent` writes the route row in the SAME
      transaction that sets `status = 'live'` — so every tenant with a running campaign
      has a route;
    - an outbound `calls` row is only ever created for a published agent, so every
      tenant that can occupy a line has a route too, and the platform-wide active count
      (rules 1+2) stays complete.

    Unfiltered on `active`, like `dispatcher.py`: an agent unpublished mid-campaign
    still leaves live calls to count. Ordered so the order in which tenants compete for
    the shared pool is stable across ticks rather than planner-dependent.

    This is a narrowing, not the end state — see the module docstring's note on what a
    tick proportional to RUNNING CAMPAIGNS would still need.
    """
    async with untenanted_session() as session:
        rows = (
            (
                await session.execute(
                    text("SELECT DISTINCT tenant_id FROM engine_agent_routes ORDER BY 1")
                )
            )
            .scalars()
            .all()
        )
    return [UUID(str(row)) for row in rows]


def _outbound_pool() -> int:
    settings = get_settings()
    reserve = max(MIN_INBOUND_RESERVE, int(PLATFORM_LINES_TOTAL * settings.inbound_reserve_ratio))
    return max(0, PLATFORM_LINES_TOTAL - reserve)


async def dispatch_campaign_tick(ctx: dict[str, Any]) -> str:
    """One tick: claim due contacts up to every ceiling, gate each, dial the lawful.

    Runs every 30 seconds. The big red switch is checked ONCE up front — it halts all
    tenants (FLOWS §5), so there is no reason to walk the campaign list to discover it
    per contact.
    """
    platform = await get_platform_status()
    if platform.outbound_halted:
        return "halted_by_big_red_switch"

    pool = _outbound_pool()
    if pool <= 0:
        alert("WORKER_STALL", "outbound_pool_empty", detail="reserve >= total lines")
        return "no_outbound_pool"

    # Global active count first: the pool is shared across ALL tenants — but only
    # tenants that can hold a line or run a campaign are worth asking (see
    # `_dispatchable_tenants`).
    tenants = await _dispatchable_tenants()

    total_active = 0
    running: list[tuple[UUID, UUID, int, dict[str, Any]]] = []  # (tenant, campaign, slots, retry)
    for tenant_id in tenants:
        async with tenant_session(tenant_id) as session:
            # Active lines, the plan ceiling AND this tenant's running campaigns in ONE
            # round trip. Two statements per tenant was the other half of the cost: the
            # transaction is per tenant either way, so the campaign list rides along as
            # a third scalar subquery instead of a second query.
            #
            # The ceiling is a SCALAR SUBQUERY, not a join. `plans` carries
            # effective_from/effective_to, so a tenant that ever changed plan has
            # several rows — and joining campaigns to plans on tenant_id alone
            # multiplies every campaign by the client's billing history, dispatching
            # it once per plan row. The symptom is a campaign dialling twice its slider
            # because the client upgraded last month. Newest row wins, which is the
            # rule invoice.py already uses for the same table.
            row = (
                await session.execute(
                    text(
                        "SELECT (SELECT count(*) FROM calls WHERE direction = 'outbound' "
                        f"    AND status IN {ACTIVE_STATUSES!r} "
                        f"    AND updated_at > now() - interval '{ACTIVE_CALL_HORIZON}'), "
                        "  (SELECT concurrency_ceiling FROM plans WHERE tenant_id = :tid "
                        "    ORDER BY created_at DESC LIMIT 1), "
                        # Same reason this is a SUBQUERY and not a join to the two
                        # above: `campaigns` joined to `plans` is exactly the multiplication
                        # described above. `ORDER BY` inside the aggregate keeps the
                        # oldest-campaign-first rule the tenant budget below depends on.
                        "  (SELECT coalesce(json_agg(json_build_object("
                        "       'id', c.id, 'concurrency', c.concurrency, "
                        "       'retry_policy', c.retry_policy, 'calling_hours', c.calling_hours"
                        "     ) ORDER BY c.created_at, c.id), '[]'::json) "
                        "   FROM campaigns c WHERE c.status = 'running')"
                    ),
                    {"tid": tenant_id},
                )
            ).first()
            active = int((row[0] if row else 0) or 0)
            ceiling = int(
                row[1] if row is not None and row[1] is not None else DEFAULT_CONCURRENCY_CEILING
            )
            total_active += active
            campaigns: list[dict[str, Any]] = list(row[2] or []) if row is not None else []
            if not campaigns:
                continue

            # Rule 3 is a TENANT budget, spent ONCE across that tenant's campaigns.
            # Computing it per campaign let a tenant with two running campaigns claim
            # twice its ceiling — and the surplus comes out of the shared pool that
            # keeps another tenant's receptionist answering (rule 1's whole point).
            # Oldest campaign first, so which one gets the lines is deterministic
            # rather than whatever order the planner returned.
            tenant_budget = max(0, ceiling - active)

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
                        (UUID(str(tenant_id)), UUID(str(campaign_id)), slots, retry_policy or {})
                    )

    if not running:
        return "no_running_campaigns"

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
        metrics_log.info(
            "metric", extra={"metric": "campaign_dials", "value": dialled, "blocked": blocked}
        )
    return f"dialled={dialled} blocked={blocked} exhausted={exhausted}"


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

    With the claim committed first, that same failure leaves the contact in `dialing`.
    Nothing re-claims it; `_reap_stuck_dialing` returns it to the ladder after 30
    minutes. One dial, one attempt, no second ring. The same split also delivers what
    `agents.service.dispatch_call` already promises in its own docstring — a call row
    that survives even when our side fails afterwards, rather than an invisible charge —
    and it stops a DB transaction being held open across an engine HTTP round trip.
    """
    max_attempts = int(retry_policy.get("max_attempts", 3))
    dialled = blocked = exhausted = 0

    async with tenant_session(tenant_id) as session:
        await _reap_stuck_dialing(session, campaign_id)

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
            # THE per-dial gate (hard rule 5). This tick is "the next dispatch tick"
            # DNC additions must precede. Its DNC read is uncached and per contact, so
            # an opt-out committed by another connection while this batch is mid-flight
            # blocks the very next contact rather than waiting for the next tick.
            decision = await check_dispatch(
                session, tenant_id=tenant_id, agent_id=UUID(str(agent_id)), phone_e164=phone
            )
            if not decision.allowed:
                terminal = decision.rule == "dnc"
                await session.execute(
                    text(
                        "UPDATE campaign_contacts SET status = :status, updated_at = now() "
                        "WHERE id = :id"
                    ),
                    {"status": "dnc_blocked" if terminal else "pending", "id": contact_id},
                )
                if not terminal:
                    # Not lawful right now (hours, caps, a halt pulled mid-batch): try
                    # again next window.
                    await session.execute(
                        text(
                            "UPDATE campaign_contacts SET next_attempt_at = now() + "
                            "interval '30 minutes', attempts = attempts - 1, updated_at = now() "
                            "WHERE id = :id"
                        ),
                        {"id": contact_id},
                    )
                blocked += 1
                continue

            try:
                handle = await dispatch_call(
                    session,
                    tenant_id=tenant_id,
                    agent_id=UUID(str(agent_id)),
                    lead_id=None,
                    phone_e164=phone,
                    lead_name=name,
                    context_note=None,
                )
            except Exception as exc:  # engine refused: schedule the retry ladder
                await _record_failure(session, contact_id, attempts, max_attempts, retry_policy)
                log.warning(
                    "campaign_dial_failed",
                    extra={"campaign_id": str(campaign_id), "reason": type(exc).__name__},
                )
                if attempts >= max_attempts:
                    exhausted += 1
                continue

            # The contact stays `dialing` until the call actually ends — the post-call
            # pipeline calls resolve_campaign_contact() with the outcome. Marking it
            # "connected" here would claim a conversation happened because a dial was
            # accepted, and would complete the campaign while calls were still ringing.
            await session.execute(
                text(
                    "UPDATE campaign_contacts SET updated_at = now(), "
                    "last_call_id = (SELECT id FROM calls WHERE engine_call_id = :h) "
                    "WHERE id = :id"
                ),
                {"h": handle, "id": contact_id},
            )
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
            done = await session.execute(
                text(
                    "UPDATE campaigns SET status = 'completed', updated_at = now() "
                    "WHERE id = :cid AND status = 'running'"
                ),
                {"cid": campaign_id},
            )
            if rowcount_of(done):
                log.info("campaign_completed", extra={"campaign_id": str(campaign_id)})

    return {"dialled": dialled, "blocked": blocked, "exhausted": exhausted}


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
                "SELECT cc.id, cc.attempts, c.retry_policy FROM campaign_contacts cc "
                "JOIN campaigns c ON c.id = cc.campaign_id "
                "WHERE cc.last_call_id = :cid AND cc.status = 'dialing'"
            ),
            {"cid": call_id},
        )
    ).first()
    if row is None:
        return None
    contact_id, attempts, retry_policy = row
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

    await _record_failure(
        session,
        contact_id,
        int(attempts or 0),
        int(policy.get("max_attempts", 3)),
        policy,
    )
    log.info(
        "campaign_contact_unanswered",
        extra={"tenant_id": str(tenant_id), "call_status": call_status},
    )
    return "failed" if int(attempts or 0) >= int(policy.get("max_attempts", 3)) else "pending"


async def _reap_stuck_dialing(session: Any, campaign_id: UUID) -> int:
    """A dial whose call never produced a terminal event would pin a contact in
    `dialing` forever and the campaign would never complete. After 30 minutes — far
    longer than any call we bill for — it goes back on the ladder."""
    result = await session.execute(
        text(
            "UPDATE campaign_contacts SET status = 'pending', "
            "next_attempt_at = now() + interval '30 minutes', updated_at = now() "
            "WHERE campaign_id = :cid AND status = 'dialing' "
            "AND last_attempt_at < now() - interval '30 minutes'"
        ),
        {"cid": campaign_id},
    )
    return rowcount_of(result)


async def _record_failure(
    session: Any, contact_id: UUID, attempts: int, max_attempts: int, retry_policy: dict[str, Any]
) -> None:
    """no-answer/busy/failed → the FLOWS §5 retry ladder with spaced delays."""
    if attempts >= max_attempts:
        await session.execute(
            text(
                "UPDATE campaign_contacts SET status = 'failed', updated_at = now() WHERE id = :id"
            ),
            {"id": contact_id},
        )
        return
    backoffs = retry_policy.get("backoff_minutes") or [30, 120]
    minutes = int(backoffs[min(attempts - 1, len(backoffs) - 1)])
    await session.execute(
        text(
            "UPDATE campaign_contacts SET status = 'pending', next_attempt_at = :next, "
            "updated_at = now() WHERE id = :id"
        ),
        {"next": datetime.now(UTC) + timedelta(minutes=minutes), "id": contact_id},
    )


__all__ = [
    "DEFAULT_CONCURRENCY_CEILING",
    "PLATFORM_LINES_TOTAL",
    "dispatch_campaign_tick",
    "resolve_campaign_contact",
]
