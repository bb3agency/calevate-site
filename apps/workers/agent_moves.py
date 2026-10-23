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

from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.session import tenant_session
from apps.api.go_live.moves import agents_to_move, move_agent, queue_agent_move
from apps.api.tenancy.engine_workspace import (
    active_workspaces,
    engine_has_workspaces,
    read_workspace_state,
)

log = get_logger(__name__)

#: Seconds before the job's next attempt after an agent met something that may pass.
_RETRY_AFTER_S: Final = (60.0, 600.0)

#: Workspaces looked at per sweep tick. The plan's customer cap bounds the estate (PAYG 3,
#: Pro 100, Scale 1,000), and each costs one tenant session.
SWEEP_BUDGET: Final = 200


async def move_agents_to_workspace(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Move every agent of the tenant left outside `workspace_id` into it."""
    tenant_id = UUID(str(payload["tenant_id"]))
    workspace = str(payload["workspace_id"])
    if not engine_has_workspaces():
        return "not_applicable"
    attempt = int(ctx.get("job_try", 1))
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
        raise Retry(defer=_RETRY_AFTER_S[min(attempt, len(_RETRY_AFTER_S)) - 1])
    return summary or "nothing_to_move"


async def sweep_agent_moves(ctx: dict[str, Any]) -> str:
    """Hourly. Queue the move for each active client workspace with an agent left behind."""
    del ctx
    if not engine_has_workspaces():
        return "not_applicable"
    tick = datetime.now(UTC).strftime("%Y%m%d%H")
    queued = behind = 0
    rows = await active_workspaces(limit=SWEEP_BUDGET)
    for row in rows:
        if row.workspace_id is None:
            continue
        async with tenant_session(row.tenant_id) as session:
            owed = await agents_to_move(
                session, tenant_id=row.tenant_id, workspace=row.workspace_id
            )
            if not owed:
                continue
            behind += 1
            queued += await queue_agent_move(
                session, tenant_id=row.tenant_id, workspace=row.workspace_id, tick=tick
            )
    log.info(
        "agent_move_sweep", extra={"workspaces": len(rows), "behind": behind, "queued": queued}
    )
    return f"workspaces={len(rows)} behind={behind} queued={queued}"


__all__ = ["SWEEP_BUDGET", "move_agents_to_workspace", "sweep_agent_moves"]
