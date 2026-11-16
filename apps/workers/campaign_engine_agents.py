"""Campaign engine agents kept honest, hourly (D-1003).

Two jobs, one walk over the accounts that have an engine agent routed:

* **Retire what a campaign no longer needs.** Stop, completion, Unschedule and Archive give a
  campaign's engine agent back as they happen (`campaigns/engine_agent.end_campaign_agent`);
  this catches any status change that did not pass through them, and the test holder of a
  campaign that never started once it has sat unused for `TEST_HOLDER_IDLE`. Each one held
  is one of the workspace's few agents (`thinnest_agents_per_workspace`). A scheduled
  campaign holds none (D-1010): one published when its start was set, before D-1010, or a
  test holder made while it waits, is retired on the same idle rule, and the start makes
  it again when it fires. `TEST_HOLDER_IDLE` is also what keeps this off a start firing
  now, whose engine agent is minutes old when the campaign turns running.
* **Give an agent its own script back.** Before D-1003, Start put the campaign's script ON
  the agent as a new prompt version noted "Campaign: <name>" and marked the campaign
  `agent_held_at`. Once every campaign going in that agent's voice dials through its own
  engine agent, the agent is rolled back to the newest version from before the campaign's
  (`agents/prompts.rollback_prompt`: a new version, so the campaign's stays in the history
  and the step is undone by rolling back to it), and the marks are cleared. Idempotent: a
  cleared mark is never acted on again, and an agent whose campaign still dials through it
  is left until the campaign has its own.

A campaign running at deploy is not published here: its next dispatch tick does that
(`campaigns/engine_agent.dial_for`), so this never races a dial. Ids and counts in every log
line (hard rule 6).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.opening_notices import WEAVE_NOTE
from apps.api.agents.prompts import rollback_prompt
from apps.api.agents.service import CAMPAIGN_HOLDING_STATUSES, retire_campaign_agent
from apps.api.compliance.audit import write_audit
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.session import tenant_session, untenanted_session
from apps.workers.fleet_walk import WalkBudget, resumed_walk

log = get_logger(__name__)

#: How long a test holder of a campaign that has not started may sit unused before it is
#: retired. An hour covers an owner trying a draft a few times in one sitting; the next test
#: call after it makes one again, and the allowance is not held overnight by a draft.
TEST_HOLDER_IDLE: Final = timedelta(hours=1)

#: The prompt-version note `put_script_live` wrote before D-1003 (`f"Campaign: {name}"`).
CAMPAIGN_VERSION_PREFIX: Final = "Campaign: "
#: Versions the platform writes over whatever script is live, which say nothing about whose
#: script it is: the woven notices (D-971) and a change to what the agent collects.
_AUTOMATIC_NOTES: Final = (WEAVE_NOTE, "Lead details changed: what the agent collects was updated")

#: Accounts with any engine agent routed, read untenanted (`campaigns` is invisible here).
#: Not only those with a campaign route: a campaign that held its agent and ended before
#: D-1003 never gets an engine agent of its own, and its agent, which has a route of its
#: own, still has to be given its script back.
_TENANTS_SQL: Final = (
    "SELECT DISTINCT tenant_id FROM engine_agent_routes "
    "WHERE active AND tenant_id IS NOT NULL ORDER BY tenant_id"
)

#: A campaign's engine agent it no longer needs: archived, ended, or a test holder unused.
_TO_RETIRE_SQL: Final = (
    "SELECT id FROM campaigns WHERE engine_agent_ref IS NOT NULL AND (archived_at IS NOT NULL "
    "OR status IN ('completed', 'cancelled') OR (NOT (status = ANY(:holding)) "
    "AND (engine_agent_at IS NULL OR engine_agent_at < now() - make_interval(secs => :idle)))) "
    "ORDER BY id"
)

#: Agents a campaign put its script on before D-1003, and whether every campaign still going
#: in that voice dials through its own engine agent now.
_HELD_AGENTS_SQL: Final = (
    "SELECT c.agent_id, bool_and(c.engine_agent_ref IS NOT NULL OR c.archived_at IS NOT NULL "
    "OR NOT (c.status = ANY(:holding))) FROM campaigns c "
    "WHERE c.agent_held_at IS NOT NULL GROUP BY c.agent_id ORDER BY c.agent_id"
)

_VERSIONS_SQL: Final = (
    "SELECT pv.version, COALESCE(pv.notes, '') FROM prompt_versions pv "
    "JOIN agents a ON a.id = pv.agent_id AND a.deleted_at IS NULL "
    "WHERE pv.agent_id = :aid AND pv.version <= ("
    "  SELECT lv.version FROM prompt_versions lv "
    "  WHERE lv.id = COALESCE(a.live_prompt_id, a.system_prompt_id)) "
    "ORDER BY pv.version DESC LIMIT 200"
)


def own_script_version(versions: list[tuple[int, str]]) -> int | None:
    """The version to give the agent back, from its versions newest first (the live one
    first): the newest one older than the campaigns' run at the top of the history, or None
    when the live script is not a campaign's or there is nothing older to go back to.

    The run is the live version and the ones under it that a campaign's Start wrote or the
    platform wrote over it; it must contain a campaign's. The version just under the oldest
    campaign version in it is the agent's own, whatever wrote it."""
    oldest_campaign: int | None = None
    for index, (_version, notes) in enumerate(versions):
        if notes.startswith(CAMPAIGN_VERSION_PREFIX):
            oldest_campaign = index
        elif notes not in _AUTOMATIC_NOTES:
            break
    if oldest_campaign is None or oldest_campaign + 1 >= len(versions):
        return None
    return versions[oldest_campaign + 1][0]


async def _retire_unneeded(session: AsyncSession, *, tenant_id: UUID) -> int:
    rows = (
        await session.execute(
            text(_TO_RETIRE_SQL),
            {
                "holding": list(CAMPAIGN_HOLDING_STATUSES),
                "idle": TEST_HOLDER_IDLE.total_seconds(),
            },
        )
    ).scalars()
    retired = 0
    for campaign_id in list(rows):
        if await retire_campaign_agent(
            session, tenant_id=tenant_id, campaign_id=UUID(str(campaign_id))
        ):
            retired += 1
    return retired


async def _restore_held(session: AsyncSession, *, tenant_id: UUID) -> tuple[int, int]:
    """(restored, waiting): agents given their own script back, and agents still waiting for
    a campaign in their voice to dial through its own engine agent."""
    held = (
        await session.execute(text(_HELD_AGENTS_SQL), {"holding": list(CAMPAIGN_HOLDING_STATUSES)})
    ).all()
    restored = waiting = 0
    for agent_id, covered in held:
        agent = UUID(str(agent_id))
        if not covered:
            waiting += 1
            continue
        versions = [
            (int(row[0]), str(row[1]))
            for row in (await session.execute(text(_VERSIONS_SQL), {"aid": agent})).all()
        ]
        target = own_script_version(versions)
        if target is not None:
            try:
                async with session.begin_nested():
                    new_version = await rollback_prompt(
                        session, tenant_id=tenant_id, agent_id=agent, version=target
                    )
            except ProblemError as refused:
                # A maintenance window, a refusal at the platform: tried again next hour.
                log.info(
                    "campaign_hold_restore_deferred",
                    extra={"agent_id": str(agent), "reason": refused.code},
                )
                waiting += 1
                continue
            await write_audit(
                session,
                action="agent.script_given_back",
                actor_type="system",
                tenant_id=tenant_id,
                object_type="agent",
                object_id=str(agent),
                summary={
                    "from_version": str(versions[0][0]),
                    "to_version": str(target),
                    "new_version": str(new_version),
                },
            )
            restored += 1
        await session.execute(
            text(
                "UPDATE campaigns SET agent_held_at = NULL, script_live_version = NULL "
                "WHERE agent_id = :aid AND agent_held_at IS NOT NULL"
            ),
            {"aid": agent},
        )
    return restored, waiting


async def sweep_campaign_engine_agents(ctx: dict[str, Any]) -> str:
    """Hourly. See the module docstring."""
    del ctx
    async with untenanted_session() as directory:
        tenants = [
            UUID(str(row)) for row in (await directory.execute(text(_TENANTS_SQL))).scalars()
        ]
    retired = restored = waiting = failed = 0
    async for tenant_id in resumed_walk("campaign_engine_agents", tenants, WalkBudget()):
        try:
            async with tenant_session(tenant_id) as session:
                retired += await _retire_unneeded(session, tenant_id=tenant_id)
            async with tenant_session(tenant_id) as session:
                done, left = await _restore_held(session, tenant_id=tenant_id)
                restored += done
                waiting += left
        except Exception as exc:
            # One account's failure does not stop the others; it is tried again next hour.
            failed += 1
            log.warning(
                "campaign_engine_agent_sweep_failed",
                extra={"tenant_id": str(tenant_id), "error": type(exc).__name__},
            )
    if failed:
        alert(
            "WORKER_DELIVERY",
            "campaign_engine_agent_sweep_failed",
            detail=f"{failed} account(s) of {len(tenants)}",
        )
    log.info(
        "campaign_engine_agent_sweep",
        extra={
            "tenants": len(tenants),
            "retired": retired,
            "restored": restored,
            "waiting": waiting,
            "failed": failed,
        },
    )
    return f"retired={retired} restored={restored} waiting={waiting} failed={failed}"


__all__ = [
    "TEST_HOLDER_IDLE",
    "own_script_version",
    "sweep_campaign_engine_agents",
]
