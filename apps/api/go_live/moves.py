"""A paying client's agents move into its own voice workspace by themselves (D-859).

ThinnestAI documents no way to move an agent between workspaces (a phone number can be moved,
`api-reference/customers.md:185-200`), so an agent moves the way D-693 built: its next publish
recreates it in the client's workspace, re-attaches its knowledge, webhook, in-call actions and
numbers, and retires the old one after the commit, waiting out a live call
(`agents/service.publish_agent`, `workers/engine_workspaces.retire_moved_engine_agent`). This
module decides WHEN that publish runs and records what came of it; it adds no second publish.

WHEN. The workspace becoming active queues one move job (`queue_agent_move`, from
`workers/engine_workspaces._activate`, deduped per tenant and workspace), and a conversion whose
workspace is already active queues it at once. An hourly sweep (`workers/agent_moves`) queues it
again for any active workspace whose tenant still has an agent left behind, which is how a held
agent is retried once the cause is lifted.

WHAT MOVES. Every agent that is live or ready (published and not taking calls) and whose vendor
agent, or a running experiment arm's, is outside the target workspace. A draft has nothing at
the voice platform and is created in the client's workspace when first got ready. An archived
agent is not republished (D-440).

STATE IS KEPT. The publish runs with `take_calls=False`: a ready agent stays ready, and a live
one is republished as live. Nothing is switched on here.

ONE AGENT'S FAILURE NEVER STOPS THE OTHERS. Each agent is published in its own transaction and
its outcome recorded in `agent_workspace_moves`:

* `moved`;
* `held`: refused for a reason a retry cannot change (the plan's agent allowance, a voice the
  client workspace does not list, a Studio set-up, or a refusal about the account). The agent
  keeps working where it is; an operator is alarmed once per cause; the hourly sweep retries.
  What to do about a voice or a plan limit waits on the founder (D-859, decisions 4 and 7).
* `waiting`: owed, or retried after something that may pass;
* `failed`: the job's retries are spent on an unexpected error; alarmed, and the sweep retries.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal
from uuid import UUID

from calevate_shared.engine_scope import scope_of
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.go_live.models import MoveState
from apps.api.reliability.service import enqueue_outbox_once

log = get_logger(__name__)

MOVE_JOB: Final = "move_agents_to_workspace"

#: The workspace is not active (yet, or any more): nothing can be created there, and the
#: activation that makes it so queues the move again. Not an operator's problem.
WAITING_CODES: Final = frozenset({"engine_workspace_not_provisioned", "platform_maintenance"})

#: Refusals the founder decides on once the voice platform answers (D-859 decisions 4 and 7):
#: the plan's agent allowance, and voices the client workspace cannot speak on our plan.
PLAN_OR_VOICE_CODES: Final = frozenset(
    {
        "engine_agent_allowance_used",
        "shared_clone_not_listed",
        "studio_account_not_ready",
        "studio_workspace_not_ready",
        "studio_voice_key_missing",
        "studio_agents_not_kept_off",
        "own_model_account_not_ready",
        "own_model_workspace_not_ready",
    }
)

#: The rows the move walks: live or ready agents with a vendor agent, and the vendor agents of
#: their running experiment arms (`agents/service._VARIANT_CONFIG_SQL`'s join).
_CANDIDATES_SQL: Final = (
    "SELECT a.id, a.engine_agent_ref, COALESCE(array_agg(v.engine_agent_ref) "
    "FILTER (WHERE v.engine_agent_ref IS NOT NULL), '{}') FROM agents a "
    "LEFT JOIN prompt_experiments e ON e.agent_id = a.id AND e.status = 'running' "
    "LEFT JOIN prompt_experiment_variants v ON v.experiment_id = e.id "
    "WHERE a.tenant_id = :tid AND a.deleted_at IS NULL AND a.status IN ('live', 'paused') "
    "AND a.engine_agent_ref IS NOT NULL GROUP BY a.id, a.engine_agent_ref ORDER BY a.id"
)


def left_behind(refs: list[str | None], workspace: str) -> bool:
    """Does any of an agent's vendor agents live outside `workspace`?"""
    return any(ref and scope_of(ref) != workspace for ref in refs)


async def agents_to_move(session: AsyncSession, *, tenant_id: UUID, workspace: str) -> list[UUID]:
    """The tenant's agents with a vendor agent outside `workspace`, oldest id first."""
    rows = (await session.execute(text(_CANDIDATES_SQL), {"tid": tenant_id})).all()
    return [
        UUID(str(row[0]))
        for row in rows
        if left_behind([str(row[1]), *[str(ref) for ref in row[2]]], workspace)
    ]


async def queue_agent_move(
    session: AsyncSession, *, tenant_id: UUID, workspace: str, tick: str | None = None
) -> bool:
    """Owe the move of this tenant's agents into `workspace`, in the caller's transaction.

    Once per (tenant, workspace) from an activation; the hourly sweep passes its own `tick` so
    each hour may queue it once more. True when a job was queued now."""
    key = f"agent-move:{tenant_id}:{workspace}" + (f":{tick}" if tick else "")
    queued = await enqueue_outbox_once(
        session,
        job=MOVE_JOB,
        payload={"tenant_id": str(tenant_id), "workspace_id": workspace},
        dedupe_key=key,
    )
    return queued is not None


async def refresh_agents_after_payment(
    session: AsyncSession, *, tenant_id: UUID, reason: str
) -> str:
    """The account's agents brought up to the paid account's settings (call-backs offered,
    D-720) and into its own workspace, in the caller's transaction. Returns what was owed.

    While the workspace is not active nothing is queued: a republish now could not create the
    agent anywhere, and the activation queues the move, whose republish carries the new
    settings. Once active, the agents already there are brought up to date by a live apply and
    those left behind by the move."""
    from apps.api.agents.live_apply import queue_live_apply
    from apps.api.tenancy.engine_workspace import read_workspace_state

    state = await read_workspace_state(session, tenant_id)
    if not state.active or state.workspace_id is None:
        return "on_activation"
    await queue_live_apply(session, scope="tenant", tenant_id=tenant_id, reason=reason)
    await queue_agent_move(session, tenant_id=tenant_id, workspace=state.workspace_id)
    return "queued"


Outcome = Literal["moved", "already", "held", "waiting", "retry", "failed", "gone"]


@dataclass(frozen=True, slots=True)
class _Record:
    status: MoveState
    code: str | None
    alarm: Literal["held", "failed"] | None = None


_UPSERT: Final = (
    "INSERT INTO agent_workspace_moves (id, tenant_id, agent_id, workspace_id, status, "
    "reason_code, attempts, last_attempt_at, moved_at) VALUES (:id, :tid, :aid, :ws, :status, "
    ":code, 1, now(), CASE WHEN :status = 'moved' THEN now() END) "
    "ON CONFLICT (agent_id, workspace_id) DO UPDATE SET status = EXCLUDED.status, "
    "reason_code = EXCLUDED.reason_code, attempts = agent_workspace_moves.attempts + 1, "
    "last_attempt_at = now(), moved_at = EXCLUDED.moved_at, updated_at = now() "
    "RETURNING alarmed_code"
)


async def _record(tenant_id: UUID, agent_id: UUID, workspace: str, record: _Record) -> None:
    """Write the agent's outcome; alarm an operator once per cause."""
    async with tenant_session(tenant_id) as session:
        alarmed = (
            await session.execute(
                text(_UPSERT),
                {
                    "id": uuid7(),
                    "tid": tenant_id,
                    "aid": agent_id,
                    "ws": workspace,
                    "status": record.status,
                    "code": record.code,
                },
            )
        ).scalar()
        if record.alarm is None or alarmed == record.code:
            if record.status == "moved" and alarmed is not None:
                await session.execute(
                    text(
                        "UPDATE agent_workspace_moves SET alarmed_code = NULL "
                        "WHERE agent_id = :aid AND workspace_id = :ws"
                    ),
                    {"aid": agent_id, "ws": workspace},
                )
            return
        await session.execute(
            text(
                "UPDATE agent_workspace_moves SET alarmed_code = :code "
                "WHERE agent_id = :aid AND workspace_id = :ws"
            ),
            {"code": record.code, "aid": agent_id, "ws": workspace},
        )
    if record.alarm == "held":
        decided_later = record.code in PLAN_OR_VOICE_CODES
        alert(
            "CORE_LOGIC",
            "agent_move_held",
            detail=(
                "a paying client's agent could not be moved into its own voice workspace "
                f"({record.code}). It keeps working from our developer workspace and is "
                "retried every hour. "
                + (
                    "This is a plan or voice limit the founder decides on (D-859); "
                    if decided_later
                    else "The client or an operator has to act first; "
                )
                + "see runbooks/agent-workspace-move.md."
            ),
            tenant_id=str(tenant_id),
            agent_id=str(agent_id),
        )
    else:
        alert(
            "WORKER_TERMINAL",
            "agent_move_failed",
            detail=(
                "a paying client's agent could not be moved into its own voice workspace "
                f"after every retry ({record.code}). It keeps working from our developer "
                "workspace and is retried every hour; see runbooks/agent-workspace-move.md."
            ),
            tenant_id=str(tenant_id),
            agent_id=str(agent_id),
        )


def _classify(exc: BaseException, *, final: bool) -> tuple[Outcome, _Record]:
    from apps.api.agents.live_apply import failure_code, is_permanent

    code = failure_code(exc)[:64]
    if isinstance(exc, ProblemError) and code in WAITING_CODES:
        return "waiting", _Record("waiting", code)
    if code in PLAN_OR_VOICE_CODES or is_permanent(exc):
        return "held", _Record("held", code, alarm="held")
    if final:
        return "failed", _Record("failed", code, alarm="failed")
    return "retry", _Record("waiting", code)


_AGENT_REFS: Final = (
    "SELECT a.status, a.engine_agent_ref, COALESCE(array_agg(v.engine_agent_ref) "
    "FILTER (WHERE v.engine_agent_ref IS NOT NULL), '{}') FROM agents a "
    "LEFT JOIN prompt_experiments e ON e.agent_id = a.id AND e.status = 'running' "
    "LEFT JOIN prompt_experiment_variants v ON v.experiment_id = e.id "
    "WHERE a.id = :aid AND a.deleted_at IS NULL GROUP BY a.id"
)


async def _refs_of(session: AsyncSession, agent_id: UUID) -> tuple[str, list[str | None]] | None:
    row = (await session.execute(text(_AGENT_REFS), {"aid": agent_id})).first()
    if row is None:
        return None
    return str(row[0]), [row[1], *row[2]]


async def move_agent(
    *, tenant_id: UUID, agent_id: UUID, workspace: str, final: bool = False
) -> Outcome:
    """Republish one agent so it lives in `workspace`, keeping its state; record the outcome.

    Never raises for the agent's own failure: the caller walks the next agent. `final` is the
    job's last attempt, after which an unexpected error is `failed` rather than retried."""
    from apps.api.agents.service import publish_agent

    try:
        async with tenant_session(tenant_id) as session:
            found = await _refs_of(session, agent_id)
            if found is None or found[0] not in ("live", "paused"):
                return "gone"
            if not left_behind(found[1], workspace):
                return "already"
            # Not taking calls: a ready agent stays ready, a live one is republished live.
            await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id, take_calls=False)
            after = await _refs_of(session, agent_id)
        if after is not None and left_behind(after[1], workspace):
            # Published, but still where it was: the account is not on its own workspace
            # (a trial again, or workspaces switched off). Retried with the next move.
            await _record(tenant_id, agent_id, workspace, _Record("waiting", "not_moved"))
            return "waiting"
    except Exception as exc:
        outcome, record = _classify(exc, final=final)
        log.warning(
            "agent_move_not_done",
            extra={"agent_id": str(agent_id), "outcome": outcome, "code": record.code},
        )
        await _record(tenant_id, agent_id, workspace, record)
        return outcome
    await _record(tenant_id, agent_id, workspace, _Record("moved", None))
    log.info("agent_moved_to_client_workspace", extra={"agent_id": str(agent_id)})
    return "moved"


# --- what the owner reads ---------------------------------------------------------------

#: The go-live guide lists at most this many agents; a client with more sees the count.
MAX_LISTED_AGENTS: Final = 50

AgentMoveView = Literal["moving", "moved", "finishing"]


@dataclass(frozen=True, slots=True)
class AgentMoveRow:
    agent_id: UUID
    name: str
    state: AgentMoveView


@dataclass(frozen=True, slots=True)
class MoveProgress:
    #: `waiting_for_account`: the client's own workspace is not active yet. `moving`: agents
    #: are still to move. `finishing`: one or more is held or failed (an operator has been
    #: told). `done`: nothing is left behind.
    state: Literal["waiting_for_account", "moving", "finishing", "done"]
    agents: tuple[AgentMoveRow, ...]
    total: int


_PROGRESS_SQL: Final = (
    "SELECT a.id, a.name, a.engine_agent_ref, COALESCE(array_agg(v.engine_agent_ref) "
    "FILTER (WHERE v.engine_agent_ref IS NOT NULL), '{}'), m.status FROM agents a "
    "LEFT JOIN prompt_experiments e ON e.agent_id = a.id AND e.status = 'running' "
    "LEFT JOIN prompt_experiment_variants v ON v.experiment_id = e.id "
    "LEFT JOIN agent_workspace_moves m ON m.agent_id = a.id AND m.workspace_id = :ws "
    "WHERE a.tenant_id = :tid AND a.deleted_at IS NULL AND ("
    "(a.status IN ('live', 'paused') AND a.engine_agent_ref IS NOT NULL) OR m.id IS NOT NULL) "
    "GROUP BY a.id, a.name, a.engine_agent_ref, m.status ORDER BY a.created_at, a.id"
)


async def read_move_progress(
    session: AsyncSession, *, tenant_id: UUID, workspace: str | None
) -> MoveProgress:
    """The move as the owner reads it, from the agents themselves and the move records. With
    no active workspace every agent with a vendor agent is still to move."""
    rows = (
        await session.execute(text(_PROGRESS_SQL), {"tid": tenant_id, "ws": workspace or ""})
    ).all()
    listed: list[AgentMoveRow] = []
    for agent_id, name, ref, arms, status in rows:
        refs = [ref, *arms]
        behind = workspace is None or left_behind(refs, workspace)
        if not behind and status is None and all(r and scope_of(r) == workspace for r in refs):
            # Made in the client's own workspace: it never had to move.
            continue
        if not behind:
            state: AgentMoveView = "moved"
        elif status in ("held", "failed"):
            state = "finishing"
        else:
            state = "moving"
        listed.append(AgentMoveRow(agent_id=UUID(str(agent_id)), name=str(name), state=state))
    if workspace is None:
        overall: Literal["waiting_for_account", "moving", "finishing", "done"] = (
            "waiting_for_account"
        )
    elif any(row.state == "finishing" for row in listed):
        overall = "finishing"
    elif any(row.state == "moving" for row in listed):
        overall = "moving"
    else:
        overall = "done"
    return MoveProgress(state=overall, agents=tuple(listed[:MAX_LISTED_AGENTS]), total=len(listed))


__all__ = [
    "MAX_LISTED_AGENTS",
    "MOVE_JOB",
    "PLAN_OR_VOICE_CODES",
    "WAITING_CODES",
    "AgentMoveRow",
    "MoveProgress",
    "Outcome",
    "agents_to_move",
    "left_behind",
    "move_agent",
    "queue_agent_move",
    "read_move_progress",
]
