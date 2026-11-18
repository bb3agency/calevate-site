"""A paying client's agents moved into its own voice workspace (D-859, `go_live/moves.py`).

* `move_agents_to_workspace` (outbox): walks the tenant's agents left outside its workspace and
  republishes each, one transaction per agent. An agent that may succeed later makes the job
  retry with backoff; the agents already moved are skipped on the retry.
* `sweep_agent_moves` (hourly): queues the job again for every active client workspace whose
  tenant still has an agent left behind, so a held agent is retried once its cause is lifted
  and a lost job is recovered.

Ids and counts in every log line and alarm (hard rule 6).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

from arq import Retry
from calevate_shared.backoff import ladder_delay_s
from calevate_shared.engine_scope import scope_of
from sqlalchemy import text

from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES, job_try
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.go_live.moves import agents_to_move, move_agent, queue_agent_move
from apps.api.tenancy.engine_workspace import (
    active_workspaces,
    engine_has_workspaces,
    read_workspace_state,
)
from apps.workers.fleet_walk import WalkBudget, resumed_walk
from apps.workers.workspace_walk import WalkReport, walk_workspaces

log = get_logger(__name__)

#: Seconds before the job's next attempt after an agent met something that may pass.
_RETRY_AFTER_S: Final = (60.0, 600.0)

#: Workspaces looked at per sweep tick, each costing one tenant session. The walk resumes
#: after the last one visited, so an estate larger than this (Scale allows 1,000) is covered
#: over several ticks rather than the same head of the list every hour.
SWEEP_BUDGET: Final = 200


async def move_agents_to_workspace(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Move every agent of the tenant left outside `workspace_id` into it."""
    tenant_id = UUID(str(payload["tenant_id"]))
    workspace = str(payload["workspace_id"])
    if not engine_has_workspaces():
        return "not_applicable"
    attempt = job_try(ctx)
    async with tenant_session(tenant_id) as session:
        state = await read_workspace_state(session, tenant_id)
        if not state.active or state.workspace_id != workspace:
            # Not this workspace's turn: an activation queues the move again.
            return "workspace_not_active"
        owed = await agents_to_move(session, tenant_id=tenant_id, workspace=workspace)
    final = attempt >= WORKER_MAX_TRIES
    tally: dict[str, int] = {}
    for agent_id in owed:
        outcome = await move_agent(
            tenant_id=tenant_id, agent_id=agent_id, workspace=workspace, final=final
        )
        tally[outcome] = tally.get(outcome, 0) + 1
    summary = " ".join(f"{key}={value}" for key, value in sorted(tally.items()))
    log.info(
        "agent_move_walked",
        extra={"tenant_id": str(tenant_id), "agents": len(owed), "attempt": attempt, **tally},
    )
    if tally.get("retry") and not final:
        raise Retry(defer=ladder_delay_s(_RETRY_AFTER_S, attempt))
    return summary or "nothing_to_move"


#: The client's own numbers in its workspace (any one ends its need for test copies).
_OWN_NUMBERS_SQL: Final = (
    "SELECT engine_number_ref FROM phone_numbers WHERE released_at IS NULL "
    "AND engine_number_ref IS NOT NULL"
)
#: Its test copies, with when each was last of use, whether it holds "Just the business", and
#: whether its agent still holds an engine agent of its own (D-1019).
_COPIES_SQL: Final = (
    "SELECT c.agent_id, c.engine_agent_ref, COALESCE(c.last_used_at, c.created_at) < "
    "now() - make_interval(days => :days), c.business_only, a.engine_agent_ref IS NOT NULL "
    "FROM agent_test_copies c LEFT JOIN agents a ON a.id = c.agent_id ORDER BY c.agent_id"
)


#: Accounts with an engine agent of ours, read untenanted (`engine_agent_routes`' read arm
#: for a session with no tenant): every test copy has a route, and `agent_test_copies`
#: itself is visible only inside its own account.
_ROUTED_TENANTS_SQL: Final = (
    "SELECT DISTINCT tenant_id FROM engine_agent_routes WHERE active AND tenant_id IS NOT NULL"
)


async def _retire_test_copies(session: Any, *, tenant_id: UUID, workspace: str | None) -> int:
    """Owe the retirement of the tenant's developer-workspace test copies (D-859, option A):
    those unused for `paid_test_copy_idle_days`, and once the client has a number of its own
    in its workspace every copy kept for its test calls. A "Just the business" copy
    (`agents/business_only`) is the agent page's chat and test calls whatever numbers the
    client has, so only idleness retires it, and so is the copy of an agent holding no engine
    agent of its own (D-1019), whose own number never rings for its test calls. With no
    `workspace` (an account still on its free trial) only idleness retires any copy. The next
    use makes a copy again."""
    from apps.api.agents.service import retire_engine_agent

    copies = (
        await session.execute(text(_COPIES_SQL), {"days": get_settings().paid_test_copy_idle_days})
    ).all()
    if not copies:
        return 0
    own = workspace is not None and any(
        scope_of(str(ref)) == workspace
        for ref in (await session.execute(text(_OWN_NUMBERS_SQL))).scalars()
    )
    retired = 0
    for agent_id, ref, idle, business_only, holds_own in copies:
        if scope_of(str(ref)) is not None:
            # A copy in the client's own workspace is its test calls from its own number
            # (D-1020), given back after an hour unused by `workers/campaign_engine_agents`.
            continue
        if idle or (own and holds_own and not business_only):
            await retire_engine_agent(
                session, tenant_id=tenant_id, agent_id=UUID(str(agent_id)), ref=str(ref)
            )
            retired += 1
    return retired


async def _retire_copies_outside_workspaces() -> int:
    """Retire the idle test copies of accounts with no active workspace of their own.

    A free-trial account's "Just the business" copy (`agents/business_only`) is made in our
    developer workspace like every test copy, and that workspace's agents count against one
    plan cap shared by every trial; the workspace walk above visits only client workspaces,
    so without this pass those copies would never be retired."""
    async with untenanted_session() as directory:
        routed = {UUID(str(r[0])) for r in (await directory.execute(text(_ROUTED_TENANTS_SQL)))}
    outside = sorted(routed - {row.tenant_id for row in await active_workspaces()})
    retired = 0
    async for tenant_id in resumed_walk("agent_test_copies_outside", outside, WalkBudget()):
        async with tenant_session(tenant_id) as session:
            retired += await _retire_test_copies(session, tenant_id=tenant_id, workspace=None)
    return retired


async def sweep_agent_moves(ctx: dict[str, Any]) -> str:
    """Hourly. Queue the move for each active client workspace with an agent left behind, and
    retire the test copies a client no longer needs."""
    del ctx
    if not engine_has_workspaces():
        return "not_applicable"
    tick = datetime.now(UTC).strftime("%Y%m%d%H")
    queued = behind = copies_retired = 0
    report = WalkReport()
    async for visit in walk_workspaces(
        "agent_moves", budget=SWEEP_BUDGET, include_developer=False, report=report
    ):
        if visit.tenant_id is None or visit.workspace is None:
            continue
        async with tenant_session(visit.tenant_id) as session:
            copies_retired += await _retire_test_copies(
                session, tenant_id=visit.tenant_id, workspace=visit.workspace
            )
            owed = await agents_to_move(
                session, tenant_id=visit.tenant_id, workspace=visit.workspace
            )
            if not owed:
                continue
            behind += 1
            queued += await queue_agent_move(
                session, tenant_id=visit.tenant_id, workspace=visit.workspace, tick=tick
            )
    copies_retired += await _retire_copies_outside_workspaces()
    log.info(
        "agent_move_sweep",
        extra={
            "workspaces": report.visited,
            "deferred": report.deferred,
            "behind": behind,
            "queued": queued,
            "copies_retired": copies_retired,
        },
    )
    return (
        f"workspaces={report.visited} behind={behind} queued={queued} "
        f"copies_retired={copies_retired}"
    )


__all__ = ["SWEEP_BUDGET", "move_agents_to_workspace", "sweep_agent_moves"]
