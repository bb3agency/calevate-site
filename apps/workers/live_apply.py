"""Bring live agents up to a saved setting (D-720): the walk, the per-agent retry, the resume.

`apps/api/agents/live_apply.queue_live_apply` writes a `live_apply_runs` row and an outbox
message in the transaction that saved the change. Three jobs carry it out:

* `apply_live_settings` — claims the run (a lease, CAS on the row), converges up to
  `BATCH_SIZE` live agents after the run's cursor, moves the cursor after each, and
  re-enqueues itself through the outbox while agents remain. Bounded batches keep a
  platform-wide change from holding a worker for the whole fleet; the cursor makes a killed
  job resume where it stopped rather than from the top.
* `apply_live_agent` — one agent whose attempt in the walk failed on something a retry can
  fix, with a backoff ladder. When it gives up the run records the agent and
  `live_apply_agent_failed` is raised.
* `resume_live_apply` — every five minutes, re-enqueues any open run whose lease lapsed
  without progress (a worker restart, a lost continuation, a maintenance window). It is
  what makes the outbox's at-least-once delivery enough.

Which agents: the active engine's routes (`engine_agent_routes`, readable from an untenanted
session), each confirmed live or ready (D-838, D-876) under its own tenant session before it
is touched.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

from arq import Retry
from calevate_shared.backoff import jittered_delay_s, ladder_delay_s
from sqlalchemy import text

from apps.api.agents.live_apply import (
    BATCH_SIZE,
    LEASE_S,
    MAINTENANCE_CODE,
    MAX_FAILURES_KEPT,
    converge_agent,
    failure_code,
    failure_detail,
    is_permanent,
    queue_agent_retry,
    queue_platform_prompt_apply,
    queue_walk,
    resume_walk,
)
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.platform_config import refresh
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine
from apps.api.ops.spoken_style_store import refresh_spoken_style

log = get_logger(__name__)

#: Seconds before each retry of one agent: a vendor blip, a rate limit, a slow platform.
RETRY_AFTER_S: Final = (30, 120, 600)
#: A maintenance window refuses every publish until it closes; look again after this.
MAINTENANCE_DEFER_S: Final = 600
#: A run whose lease lapsed this long ago with nothing moving is resumed.
STALE_AFTER_S: Final = 120
#: How often `resume_live_apply` runs (`workers/settings.py` registers it on this cadence).
RESUME_INTERVAL_S: Final = 300

_CLAIM: Final = text(
    "UPDATE live_apply_runs SET status = 'running', "
    "lease_until = now() + make_interval(secs => :lease), "
    "started_at = coalesce(started_at, now()), updated_at = now() "
    "WHERE id = :id AND status IN ('pending', 'running') "
    "AND (lease_until IS NULL OR lease_until < now()) "
    "RETURNING scope, tenant_id, agent_id, cursor_tenant_id, cursor_agent_id, total"
)

_ROUTES: Final = (
    "FROM engine_agent_routes WHERE active AND engine = :engine AND agent_id IS NOT NULL "
    "AND (CAST(:tid AS uuid) IS NULL OR tenant_id = CAST(:tid AS uuid)) "
    "AND (CAST(:aid AS uuid) IS NULL OR agent_id = CAST(:aid AS uuid))"
)

_COUNT: Final = text(f"SELECT count(DISTINCT agent_id) {_ROUTES}")

_NEXT: Final = text(
    f"SELECT DISTINCT tenant_id, agent_id {_ROUTES} "
    "AND (CAST(:ct AS uuid) IS NULL OR (tenant_id, agent_id) > "
    "(CAST(:ct AS uuid), CAST(:ca AS uuid))) "
    "ORDER BY tenant_id, agent_id LIMIT :n"
)

# Every progress write is conditional on the run still being OURS to walk: a run another
# save superseded stops at the next agent instead of finishing a stale pass.
_ADVANCE: Final = text(
    "UPDATE live_apply_runs SET cursor_tenant_id = :ct, cursor_agent_id = :ca, "
    "applied = applied + :applied, total = total - :gone, retrying = retrying + :retrying, "
    "lease_until = now() + make_interval(secs => :lease), updated_at = now() "
    "WHERE id = :id AND status = 'running' RETURNING id"
)

_FAILED: Final = text(
    "UPDATE live_apply_runs SET failed = failed + 1, retrying = retrying - :was_retrying, "
    "failures = CASE WHEN jsonb_array_length(failures) < :keep "
    "THEN failures || CAST(:failure AS jsonb) ELSE failures END, updated_at = now() "
    "WHERE id = :id"
)

_RETRY_SETTLED: Final = text(
    "UPDATE live_apply_runs SET applied = applied + :applied, total = total - :gone, "
    "retrying = retrying - 1, updated_at = now() WHERE id = :id"
)

_FINISH: Final = text(
    "UPDATE live_apply_runs SET status = 'done', finished_at = now(), lease_until = NULL, "
    "updated_at = now() WHERE id = :id AND status = 'running' AND walked_at IS NOT NULL "
    "AND retrying = 0"
)


def _ids(row: Any) -> dict[str, Any]:
    return {"tid": row[1], "aid": row[2]}


async def _record_failure(
    run_id: UUID,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    code: str,
    was_retrying: bool,
    detail: dict[str, Any] | None = None,
) -> None:
    failure: dict[str, Any] = {
        "tenant_id": str(tenant_id),
        "agent_id": str(agent_id),
        "code": code,
        # When, so an agent that went live again afterwards stops showing it.
        "at": datetime.now(UTC).isoformat(),
        **(detail or {}),
    }
    async with tenant_session(tenant_id) as session:
        name = (
            await session.execute(text("SELECT name FROM agents WHERE id = :a"), {"a": agent_id})
        ).scalar()
    if name:
        # The agent's display name, so the console can say which one without a lookup.
        failure["agent_name"] = str(name)[:120]
    async with untenanted_session() as session:
        await session.execute(
            _FAILED,
            {
                "id": run_id,
                "was_retrying": 1 if was_retrying else 0,
                "keep": MAX_FAILURES_KEPT,
                "failure": json.dumps([failure]),
            },
        )
        await session.execute(_FINISH, {"id": run_id})
    log.warning(
        "live_apply_agent_failed",
        extra={"run_id": str(run_id), "agent_id": str(agent_id), "reason": code},
    )
    alert(
        "WORKER_TERMINAL",
        "live_apply_agent_failed",
        detail=(
            "A saved setting could not be put on one live agent, so it is still taking calls "
            f"on its previous settings ({code}). The ops console lists it under the change "
            "that was applied. Read the code, fix the cause, then republish the agent."
        ),
        tenant_id=str(tenant_id),
        agent_id=str(agent_id),
        reason=code,
    )


async def _queue_retry(run_id: UUID, *, tenant_id: UUID, agent_id: UUID) -> None:
    async with untenanted_session() as session:
        await queue_agent_retry(session, run_id, tenant_id=tenant_id, agent_id=agent_id)


async def apply_live_settings(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Walk one batch of a run. Idempotent: converging an agent twice changes nothing."""
    del ctx
    run_id = UUID(str(payload["run_id"]))
    # The worker may not yet have re-read a setting saved a second ago; the walk must
    # publish the saved value, not this process's last poll of it. The same for the
    # founder's published spoken style (D-744), which is not a setting.
    await refresh()
    await refresh_spoken_style()
    engine = get_engine().name
    async with untenanted_session() as session:
        run = (await session.execute(_CLAIM, {"id": run_id, "lease": LEASE_S})).first()
        if run is None:
            return "not_claimed"
        params = {**_ids(run), "engine": engine}
        if run[5] is None:
            total = int((await session.execute(_COUNT, params)).scalar() or 0)
            await session.execute(
                text("UPDATE live_apply_runs SET total = :t WHERE id = :id"),
                {"t": total, "id": run_id},
            )
        batch = (
            await session.execute(_NEXT, {**params, "ct": run[3], "ca": run[4], "n": BATCH_SIZE})
        ).all()

    applied = 0
    for tenant_id, agent_id in batch:
        done, gone, retrying = 0, 0, 0
        try:
            outcome, _name = await converge_agent(tenant_id=tenant_id, agent_id=agent_id)
        except Exception as exc:
            if failure_code(exc) == MAINTENANCE_CODE:
                # Every publish waits for the window to close. Stop here without moving
                # the cursor; the resume cron picks the run up once the lease lapses.
                async with untenanted_session() as session:
                    await session.execute(
                        text(
                            "UPDATE live_apply_runs SET lease_until = now() + "
                            "make_interval(secs => :defer), updated_at = now() "
                            "WHERE id = :id AND status = 'running'"
                        ),
                        {"id": run_id, "defer": MAINTENANCE_DEFER_S},
                    )
                return f"maintenance applied={applied}"
            if is_permanent(exc):
                await _record_failure(
                    run_id,
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    code=failure_code(exc),
                    detail=failure_detail(exc),
                    was_retrying=False,
                )
            else:
                await _queue_retry(run_id, tenant_id=tenant_id, agent_id=agent_id)
                retrying = 1
        else:
            done, gone = (1, 0) if outcome == "applied" else (0, 1)
        applied += done
        async with untenanted_session() as session:
            moved = (
                await session.execute(
                    _ADVANCE,
                    {
                        "id": run_id,
                        "ct": tenant_id,
                        "ca": agent_id,
                        "applied": done,
                        "gone": gone,
                        "retrying": retrying,
                        "lease": LEASE_S,
                    },
                )
            ).first()
        if moved is None:
            log.info("live_apply_superseded", extra={"run_id": str(run_id)})
            return f"superseded applied={applied}"

    async with untenanted_session() as session:
        if len(batch) < BATCH_SIZE:
            await session.execute(
                text(
                    "UPDATE live_apply_runs SET walked_at = now(), lease_until = NULL, "
                    "updated_at = now() WHERE id = :id AND status = 'running'"
                ),
                {"id": run_id},
            )
            await session.execute(_FINISH, {"id": run_id})
            log.info("live_apply_walked", extra={"run_id": str(run_id), "applied": applied})
            return f"walked applied={applied}"
        # More to do: release the lease and hand the next batch to the queue, so a
        # platform-wide change takes turns with everything else queued.
        await session.execute(
            text(
                "UPDATE live_apply_runs SET lease_until = NULL, updated_at = now() "
                "WHERE id = :id AND status = 'running'"
            ),
            {"id": run_id},
        )
        await queue_walk(session, run_id)
    return f"continued applied={applied}"


async def apply_live_agent(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """One agent's retry ladder. On success or give-up the run's counts settle."""
    run_id = UUID(str(payload["run_id"]))
    tenant_id = UUID(str(payload["tenant_id"]))
    agent_id = UUID(str(payload["agent_id"]))
    attempt = int(ctx.get("job_try", 1) or 1)
    await refresh()
    try:
        outcome, _name = await converge_agent(tenant_id=tenant_id, agent_id=agent_id)
    except Exception as exc:
        code = failure_code(exc)
        if code == MAINTENANCE_CODE:
            # A window is not a failure of this agent and may outlast the ladder: wait it
            # out, and once the ladder is spent start a fresh one rather than give up.
            if attempt < WORKER_MAX_TRIES:
                raise Retry(
                    defer=jittered_delay_s(MAINTENANCE_DEFER_S, floor_s=MAINTENANCE_DEFER_S)
                ) from exc
            await _queue_retry(run_id, tenant_id=tenant_id, agent_id=agent_id)
            return "maintenance"
        if not is_permanent(exc) and attempt < WORKER_MAX_TRIES:
            raise Retry(defer=ladder_delay_s(RETRY_AFTER_S, attempt)) from exc
        await _record_failure(
            run_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
            code=code,
            detail=failure_detail(exc),
            was_retrying=True,
        )
        return "failed"
    async with untenanted_session() as session:
        await session.execute(
            _RETRY_SETTLED,
            {
                "id": run_id,
                "applied": 1 if outcome == "applied" else 0,
                "gone": 0 if outcome == "applied" else 1,
            },
        )
        await session.execute(_FINISH, {"id": run_id})
    return outcome


async def resume_live_apply(ctx: dict[str, Any]) -> str:
    """Re-enqueue the walk of every open run that stopped moving. Bounded to 50 runs."""
    del ctx
    async with untenanted_session() as session:
        stalled = (
            (
                await session.execute(
                    text(
                        "SELECT id FROM live_apply_runs WHERE status IN ('pending', 'running') "
                        "AND walked_at IS NULL AND (lease_until IS NULL OR lease_until < now()) "
                        "AND updated_at < now() - make_interval(secs => :stale) "
                        "ORDER BY created_at LIMIT 50"
                    ),
                    {"stale": STALE_AFTER_S},
                )
            )
            .scalars()
            .all()
        )
    tick = int(time.time()) // RESUME_INTERVAL_S
    for run_id in stalled:
        await resume_walk(run_id, tick=tick)
    if stalled:
        log.warning("live_apply_resumed", extra={"runs": len(stalled)})
    return f"resumed={len(stalled)}"


async def apply_platform_prompt_on_start() -> None:
    """Queue the platform walk for this build's prompt text, at worker start
    (`queue_platform_prompt_apply`). Logged, never raised: a worker that cannot reach the
    database here fails its first job loudly anyway, and the next start queues the walk."""
    try:
        async with untenanted_session() as session:
            run_id = await queue_platform_prompt_apply(session)
    except Exception:
        log.exception("live_apply_platform_prompt_not_queued")
        return
    if run_id is not None:
        log.info("live_apply_platform_prompt_queued", extra={"run_id": str(run_id)})


__all__ = [
    "apply_live_agent",
    "apply_live_settings",
    "apply_platform_prompt_on_start",
    "resume_live_apply",
]
