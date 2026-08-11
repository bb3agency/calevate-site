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

Per contact, at dial time, the FULL compliance gate runs again. The launch scrub was
UX; this is the enforcement — a number can join the DNC list between launch and dial,
and hard rule 5 says additions propagate before the next dispatch tick. This loop IS
the dispatch tick.

Claiming is CAS: `pending → dialing` by conditional UPDATE with SKIP LOCKED, so N
dispatcher processes never double-dial a contact.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text

from apps.api.agents.service import dispatch_call
from apps.api.campaigns.service import campaign_window_open

# Module import (not `from ... import ist_now`) so tests that pin the compliance
# clock pin THIS check too — the campaign window and the per-dial gate must agree
# on what time it is.
from apps.api.compliance import service as compliance_service
from apps.api.compliance.service import check_dispatch
from apps.api.core.alerting import alert, metrics_log
from apps.api.core.loadshed import get_platform_status
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.result import rowcount_of
from apps.api.db.session import admin_session, tenant_session

log = get_logger(__name__)

# Until engine verification item 8 produces the real numbers, the pool is a config
# default sized for the pilot. It lives here as ONE constant so the pilot's measured
# value has exactly one place to land (or move to engine_capacity when that ships).
PLATFORM_LINES_TOTAL = 10
MIN_INBOUND_RESERVE = 4
ACTIVE_STATUSES = ("queued", "ringing", "in_progress")

# A call row is only evidence of an occupied LINE while it is fresh. Rows can strand in
# `queued`/`in_progress` when an engine event is lost — the reconciliation poller
# eventually corrects them, but until it does, counting them would let a handful of
# stale rows permanently zero the outbound pool and silently stop every campaign on the
# platform. Nothing we bill for runs an hour, so an hour is comfortably past "live".
ACTIVE_CALL_HORIZON = "1 hour"


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

    # Global active count first: the pool is shared across ALL tenants.
    async with admin_session() as directory:
        tenants = (
            (await directory.execute(text("SELECT id FROM organizations WHERE deleted_at IS NULL")))
            .scalars()
            .all()
        )

    total_active = 0
    running: list[tuple[UUID, UUID, int, dict[str, Any]]] = []  # (tenant, campaign, slots, retry)
    for tenant_id in tenants:
        async with tenant_session(tenant_id) as session:
            active = (
                await session.execute(
                    text(
                        "SELECT count(*) FROM calls WHERE direction = 'outbound' "
                        f"AND status IN {ACTIVE_STATUSES!r} "
                        f"AND updated_at > now() - interval '{ACTIVE_CALL_HORIZON}'"
                    )
                )
            ).scalar()
            total_active += int(active or 0)

            campaigns = (
                await session.execute(
                    text(
                        "SELECT c.id, c.concurrency, c.retry_policy, c.calling_hours, "
                        "  COALESCE(p.concurrency_ceiling, 10) AS ceiling "
                        "FROM campaigns c "
                        "LEFT JOIN plans p ON p.tenant_id = c.tenant_id "
                        "WHERE c.status = 'running'"
                    )
                )
            ).all()
            for campaign_id, slider, retry_policy, calling_hours, ceiling in campaigns:
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
                # Rule 3 then rule 4: tenant ceiling bounds the campaign slider.
                tenant_budget = max(0, int(ceiling) - int(active or 0))
                slots = min(int(slider), tenant_budget)
                if slots > 0:
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
    max_attempts = int(retry_policy.get("max_attempts", 3))
    dialled = blocked = exhausted = 0

    async with tenant_session(tenant_id) as session:
        await _reap_stuck_dialing(session, campaign_id)

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
        claimed = (
            await session.execute(
                text(
                    "WITH picked AS MATERIALIZED ("
                    "  SELECT id FROM campaign_contacts WHERE campaign_id = :cid "
                    "  AND status = 'pending' "
                    "  AND (next_attempt_at IS NULL OR next_attempt_at <= now()) "
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

        for contact_id, phone, name, _custom, attempts in claimed:
            # THE per-dial gate (hard rule 5). This tick is "the next dispatch tick"
            # DNC additions must precede.
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
                    # Not lawful right now (hours, caps): try again next window.
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


__all__ = ["PLATFORM_LINES_TOTAL", "dispatch_campaign_tick", "resolve_campaign_contact"]
