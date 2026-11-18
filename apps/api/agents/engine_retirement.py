"""Give each agent's own engine agent to what uses it, or retire it (D-1019, release R2).

An agent is an employee and holds no engine agent in its client's workspace; only its
assignments do: live inbound lines and running or paused campaigns. Agents published before
D-1019 still hold one, and it may be what a number or a campaign actually rings. This job
walks one client's agents that still hold a ref and, per agent, in its own transaction:

1. **A running script test is concluded first**, keeping the control
   (`experiments.conclude(promote_label=None)`, E2): its arms are engine agents of their own
   and per-agent tests are no longer started (E1).
2. **Exactly one draft line with numbers the agent answers** adopts the ref: the line's script
   is refreshed from the agent's applied script if nobody ever edited it, its test holder is
   retired, the agent's knowledge claims become the line's, and `publish_line(adopt_ref=...)`
   updates the same vendor object to the line's config and name tag and reads it back (hard
   rule 5). The numbers stay bound to that object, so nothing is unbound and no caller hears
   a gap; `route_line_numbers` then confirms them against the live line.
3. **Else exactly one running or paused campaign dialling through the agent** adopts it the
   same way, through `publish_campaign_agent(adopt_ref=...)`.
4. **Else nothing uses it**: the agent lets go of it, its knowledge copies go with it, and its
   deletion is owed through the outbox (`service.hand_over_engine_agent`).
5. **Anything else is held** with our reason code and one alarm per cause; the legacy paths
   keep working through the ref. A refusal that may pass (the platform, maintenance, a
   knowledge publish in flight) records `waiting` and the next run tries again.

A ref still in our developer workspace while the engine gives clients workspaces of their
own (a trial agent, or one not yet moved) can be adopted by nothing in the client's
workspace: it is retired when unused and held otherwise.

LOCK ORDER is `publish_line`'s: the tenant's knowledge lock, then the agent row, then the
holder's row (taken inside the publish). Nothing runs while `agents_hold_engine_agent` is on,
because every publish would make the agent a new engine agent of its own again. A dry run
reads the same facts and writes nothing.

Ids and codes in every log line and alarm (hard rule 6).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from uuid import UUID

from calevate_shared.call_script import CallScript
from calevate_shared.engine_scope import scope_of
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import experiments
from apps.api.agents import service as agents_service
from apps.api.agents.models import RetirementOutcome
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.tenancy.engine_workspace import engine_has_workspaces

log = get_logger(__name__)

#: The most agents one run looks at. A client has a handful; the bound keeps one run's
#: length known (`check_list_bounds`).
MAX_AGENTS_PER_RUN: Final = 200

#: Our reason codes for a held agent (`runbooks/alarm-index.md`, `agent_engine_agent_held`).
SEVERAL_USES: Final = "several_uses"
NUMBER_WITHOUT_LINE: Final = "number_without_line"
DEVELOPER_WORKSPACE_IN_USE: Final = "developer_workspace_in_use"
#: The agent's ref changed between the plan and the lock (`waiting`).
REF_CHANGED: Final = "ref_changed"

#: Refusals that may pass on their own, so the agent is `waiting`, not held.
_PASSING_CODES: Final = frozenset(
    {"platform_maintenance", agents_service.KNOWLEDGE_PUBLISH_IN_PROGRESS}
)

_AGENTS_SQL: Final = (
    "SELECT id, engine_agent_ref FROM agents WHERE engine_agent_ref IS NOT NULL "
    "ORDER BY created_at, id LIMIT :cap"
)
_AGENT_SQL: Final = (
    "SELECT engine_agent_ref, direction, deleted_at IS NULL FROM agents WHERE id = :aid"
)
#: Draft lines in the agent's voice holding a number: while the agent answers inbound, those
#: numbers ring the agent's own engine agent (`service.route_line_numbers`).
_DRAFT_LINES_SQL: Final = (
    "SELECT l.id, l.version FROM inbound_lines l WHERE l.agent_id = :aid "
    "AND l.archived_at IS NULL AND l.published_at IS NULL AND EXISTS ("
    "  SELECT 1 FROM phone_numbers n WHERE n.inbound_line_id = l.id AND n.released_at IS NULL) "
    "ORDER BY l.created_at, l.id"
)
_OWN_NUMBERS_SQL: Final = (
    "SELECT count(*) FROM phone_numbers WHERE agent_id = :aid AND released_at IS NULL "
    "AND inbound_line_id IS NULL"
)
#: Campaigns going in the agent's voice with no engine agent of their own: they dial through
#: the agent's (`campaigns/engine_agent.dial_for`).
_CAMPAIGNS_SQL: Final = (
    "SELECT id FROM campaigns WHERE agent_id = :aid AND archived_at IS NULL "
    "AND engine_agent_ref IS NULL AND status = ANY(:holding) ORDER BY created_at, id"
)
_EXPERIMENTS_SQL: Final = (
    "SELECT id FROM prompt_experiments WHERE agent_id = :aid AND status = 'running' ORDER BY id"
)
_APPLIED_SCRIPT_SQL: Final = (
    "SELECT pv.structured_script FROM agents a JOIN prompt_versions pv "
    "ON pv.id = COALESCE(a.live_prompt_id, a.system_prompt_id) WHERE a.id = :aid"
)
_PREVIOUS_SQL: Final = (
    "SELECT outcome, reason FROM agent_engine_retirements WHERE agent_id = :aid AND old_ref = :ref"
)
_RECORD_SQL: Final = (
    "INSERT INTO agent_engine_retirements (id, tenant_id, agent_id, old_ref, outcome, "
    "holder_id, reason) VALUES (:id, :tid, :aid, :ref, :outcome, :holder, :reason) "
    "ON CONFLICT (agent_id, old_ref) DO UPDATE SET outcome = EXCLUDED.outcome, "
    "holder_id = EXCLUDED.holder_id, reason = EXCLUDED.reason, updated_at = now()"
)


@dataclass(frozen=True, slots=True)
class AgentRetirement:
    """What the run did, or in a dry run would do, with one agent's engine agent."""

    agent_id: UUID
    old_ref: str
    outcome: RetirementOutcome
    #: The line or campaign that adopts it.
    holder_id: UUID | None
    reason: str | None
    #: Running script tests concluded first (or, in a dry run, that would be).
    experiments_concluded: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class RetirementRun:
    tenant_id: UUID
    dry_run: bool
    agents: tuple[AgentRetirement, ...]


@dataclass(frozen=True, slots=True)
class _Plan:
    outcome: RetirementOutcome
    holder_id: UUID | None
    reason: str | None
    line_version: int | None = None


def agents_still_get_their_own() -> bool:
    """Whether a publish still makes an agent an engine agent of its own (WP-B's setting,
    on by default in release R1). While it is, retiring one only has the next publish make
    another, so the job refuses."""
    return bool(getattr(get_settings(), "agents_hold_engine_agent", True))


def _creation_still_on() -> ProblemError:
    return ProblemError.business_rule(
        "agents_still_hold_engine_agents",
        "Agents still get a calling setup of their own when they are published.",
        remediation=(
            "Switch off the platform setting agents_hold_engine_agent first, or run a dry run "
            "to see what this would do."
        ),
    )


async def _plan(session: AsyncSession, *, agent_id: UUID, ref: str) -> _Plan:
    """Decide what happens to `ref`, from the rows as they stand."""
    found = (await session.execute(text(_AGENT_SQL), {"aid": agent_id})).one()
    answers = bool(found[2]) and agents_service.agent_answers_inbound(found[1])
    params = {"aid": agent_id}
    lines = (await session.execute(text(_DRAFT_LINES_SQL), params)).all() if answers else []
    own = (
        int((await session.execute(text(_OWN_NUMBERS_SQL), params)).scalar_one()) if answers else 0
    )
    campaigns = (
        (
            await session.execute(
                text(_CAMPAIGNS_SQL),
                {**params, "holding": list(agents_service.CAMPAIGN_HOLDING_STATUSES)},
            )
        )
        .scalars()
        .all()
    )
    if not lines and not own and not campaigns:
        return _Plan(outcome="retired", holder_id=None, reason=None)
    if engine_has_workspaces() and scope_of(ref) is None:
        return _Plan(outcome="held", holder_id=None, reason=DEVELOPER_WORKSPACE_IN_USE)
    if own:
        return _Plan(outcome="held", holder_id=None, reason=NUMBER_WITHOUT_LINE)
    if len(lines) == 1 and not campaigns:
        line_id, version = lines[0]
        return _Plan(
            outcome="adopted_line",
            holder_id=UUID(str(line_id)),
            reason=None,
            line_version=int(version),
        )
    if not lines and len(campaigns) == 1:
        return _Plan(outcome="adopted_campaign", holder_id=UUID(str(campaigns[0])), reason=None)
    return _Plan(outcome="held", holder_id=None, reason=SEVERAL_USES)


async def _running_experiments(session: AsyncSession, agent_id: UUID) -> tuple[UUID, ...]:
    rows = (await session.execute(text(_EXPERIMENTS_SQL), {"aid": agent_id})).scalars()
    return tuple(UUID(str(row)) for row in rows)


async def _refresh_untouched_script(
    session: AsyncSession, *, agent_id: UUID, line_id: UUID
) -> None:
    """A line nobody edited carries the script its agent had live when the line was made
    (migration d8b2f5a7c3e1's backfill); it is brought to the agent's applied script now, so
    adopting it changes nothing callers hear."""
    from apps.api.inbound import lines

    structured = (await session.execute(text(_APPLIED_SCRIPT_SQL), {"aid": agent_id})).scalar()
    if structured:
        await lines.save_script(session, line_id, CallScript.model_validate(structured))


async def _carry_out(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID, ref: str, plan: _Plan
) -> None:
    """The plan's writes and its one publish, in the caller's transaction."""
    if plan.outcome == "adopted_line":
        assert plan.holder_id is not None
        if plan.line_version == 0:
            await _refresh_untouched_script(session, agent_id=agent_id, line_id=plan.holder_id)
        await agents_service.retire_line_test_holder(
            session, tenant_id=tenant_id, line_id=plan.holder_id
        )
        await agents_service.hand_over_engine_agent(
            session, tenant_id=tenant_id, agent_id=agent_id, ref=ref, line_id=plan.holder_id
        )
        await agents_service.publish_line(
            session, tenant_id=tenant_id, line_id=plan.holder_id, adopt_ref=ref
        )
    elif plan.outcome == "adopted_campaign":
        assert plan.holder_id is not None
        await agents_service.hand_over_engine_agent(
            session, tenant_id=tenant_id, agent_id=agent_id, ref=ref, campaign_id=plan.holder_id
        )
        await agents_service.publish_campaign_agent(
            session, tenant_id=tenant_id, campaign_id=plan.holder_id, adopt_ref=ref
        )
    elif plan.outcome == "retired":
        await agents_service.hand_over_engine_agent(
            session, tenant_id=tenant_id, agent_id=agent_id, ref=ref
        )


async def _record(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    ref: str,
    outcome: RetirementOutcome,
    holder_id: UUID | None,
    reason: str | None,
) -> None:
    """Write the outcome; a held agent alarms once per cause, so an hourly rerun is quiet."""
    previous = (await session.execute(text(_PREVIOUS_SQL), {"aid": agent_id, "ref": ref})).first()
    await session.execute(
        text(_RECORD_SQL),
        {
            "id": uuid7(),
            "tid": tenant_id,
            "aid": agent_id,
            "ref": ref,
            "outcome": outcome,
            "holder": holder_id,
            "reason": reason,
        },
    )
    if outcome == "held" and (previous is None or tuple(previous) != ("held", reason)):
        alert(
            "CORE_LOGIC",
            "agent_engine_agent_held",
            detail=(
                "an agent's own engine agent could not be given to what uses it, so the agent "
                f"keeps it and its calls go on as before. Reason: {reason}."
            ),
            tenant_id=str(tenant_id),
            agent_id=str(agent_id),
        )


def _failed(exc: Exception) -> tuple[RetirementOutcome, str]:
    """A refusal that may pass is `waiting`; any other is `held` under its code."""
    if isinstance(exc, ProblemError):
        if exc.kind in ("dependency", "transient") or exc.code in _PASSING_CODES:
            return "waiting", exc.code
        return "held", exc.code
    return "waiting", type(exc).__name__


async def retire_agent(
    *, tenant_id: UUID, agent_id: UUID, ref: str, dry_run: bool
) -> AgentRetirement:
    """One agent, in its own transaction; see the module docstring."""
    async with tenant_session(tenant_id) as session:
        running = await _running_experiments(session, agent_id)
        plan = await _plan(session, agent_id=agent_id, ref=ref)
    if dry_run:
        return AgentRetirement(
            agent_id=agent_id,
            old_ref=ref,
            outcome=plan.outcome,
            holder_id=plan.holder_id,
            reason=plan.reason,
            experiments_concluded=running,
        )
    concluded: list[UUID] = []
    try:
        for experiment_id in running:
            await experiments.conclude(
                tenant_id=tenant_id,
                agent_id=agent_id,
                experiment_id=experiment_id,
                promote_label=None,
            )
            concluded.append(experiment_id)
        async with tenant_session(tenant_id) as session:
            # Imported here: `kb.service` imports `agents.t0`, which imports `agents.service`.
            from apps.api.kb.service import lock_tenant_knowledge

            await lock_tenant_knowledge(session, tenant_id=tenant_id)
            held = (
                await session.execute(
                    text("SELECT engine_agent_ref FROM agents WHERE id = :aid FOR UPDATE"),
                    {"aid": agent_id},
                )
            ).scalar_one()
            if held != ref:
                # Another publish moved it meanwhile; the next run plans from the new ref.
                plan = _Plan(outcome="waiting", holder_id=None, reason=REF_CHANGED)
            else:
                plan = await _plan(session, agent_id=agent_id, ref=ref)
                await _carry_out(
                    session, tenant_id=tenant_id, agent_id=agent_id, ref=ref, plan=plan
                )
            await _record(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                ref=ref,
                outcome=plan.outcome,
                holder_id=plan.holder_id,
                reason=plan.reason,
            )
    except Exception as exc:
        outcome, reason = _failed(exc)
        log.warning(
            "agent_engine_retirement_failed",
            extra={"agent_id": str(agent_id), "outcome": outcome, "reason": reason},
        )
        plan = _Plan(outcome=outcome, holder_id=None, reason=reason)
        async with tenant_session(tenant_id) as session:
            await _record(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                ref=ref,
                outcome=outcome,
                holder_id=None,
                reason=reason,
            )
    if plan.outcome == "adopted_line" and plan.holder_id is not None:
        # After the commit, as `inbound/publish.put_line_live` routes a line's numbers: the
        # same object answers them, so this re-confirms each binding and unbinds none.
        from apps.api.inbound.publish import route_numbers

        await route_numbers(tenant_id=tenant_id, line_id=plan.holder_id)
    log.info(
        "agent_engine_retirement",
        extra={"agent_id": str(agent_id), "outcome": plan.outcome, "reason": plan.reason},
    )
    return AgentRetirement(
        agent_id=agent_id,
        old_ref=ref,
        outcome=plan.outcome,
        holder_id=plan.holder_id,
        reason=plan.reason,
        experiments_concluded=tuple(concluded),
    )


async def retire_for_tenant(*, tenant_id: UUID, dry_run: bool) -> RetirementRun:
    """Every agent of the client that still holds an engine agent of its own."""
    if not dry_run and agents_still_get_their_own():
        raise _creation_still_on()
    async with tenant_session(tenant_id) as session:
        rows = (await session.execute(text(_AGENTS_SQL), {"cap": MAX_AGENTS_PER_RUN})).all()
    done = [
        await retire_agent(
            tenant_id=tenant_id, agent_id=UUID(str(agent_id)), ref=str(ref), dry_run=dry_run
        )
        for agent_id, ref in rows
    ]
    log.info(
        "agent_engine_retirement_run",
        extra={"tenant_id": str(tenant_id), "dry_run": dry_run, "agents": len(done)},
    )
    return RetirementRun(tenant_id=tenant_id, dry_run=dry_run, agents=tuple(done))


__all__ = [
    "DEVELOPER_WORKSPACE_IN_USE",
    "MAX_AGENTS_PER_RUN",
    "NUMBER_WITHOUT_LINE",
    "REF_CHANGED",
    "SEVERAL_USES",
    "AgentRetirement",
    "RetirementRun",
    "agents_still_get_their_own",
    "retire_agent",
    "retire_for_tenant",
]
