"""A campaign's own engine agent (D-1003, Phase 2 of `docs/design/CAMPAIGN-WORKER-PLAN.md`).

The campaign is the worker and its agent the voice (founder, 16 Nov 2026). Start used to put
the campaign's script on the agent itself, so a number the agent answered heard the campaign
and a second campaign in the same voice was refused. Each campaign now speaks through an
engine agent of its own, built from its agent's config over its own script and settings
(`agents/service.campaign_config`), the way an inbound line does (D-997):

* Start and Schedule publish it (`put_campaign_live`), Pause keeps it so Resume dials at once,
  and Stop, completion, Unschedule and Archive retire it (`end_campaign_agent`), freeing the
  workspace's agent allowance;
* every dial of the campaign rings through it (`dial_for`), on a number lent to it for the
  call, so the agent's own engine agent and the numbers it answers are never touched;
* the campaign's Test call rings it too (`campaign_test_dial`), published as a test holder.

Why an engine agent per campaign rather than the script sent with each call: a per-call
override holds 4,000 characters and replaces the built-in call rules
(`thinnest-findings/mirror/snapshots/2026-10-07/pages/api-reference/calls/place-call.md:
1283-1289`), while one agent's instructions hold 20,000 (`agents/update-agent.md:426-431`).
The cost is the per-workspace agent allowance, counted before each new one is made
(`agents/service._refuse_if_allowance_full`).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import service as agents_service
from apps.api.agents.service import CAMPAIGN_HOLDING_STATUSES, CampaignDial
from apps.api.compliance.trial_access import refuse_on_trial
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.session import tenant_session

log = get_logger(__name__)


#: A campaign with something of its own to say: its own script (D-992) or its own settings
#: (D-994). One with neither (made before D-992, or a Pip dialling plan) says exactly what
#: its agent says, so it dials through the agent's own engine agent, as it always did, and
#: takes none of the workspace's allowance.
_SPEAKS_ITS_OWN_SQL = (
    "SELECT script IS NOT NULL OR COALESCE(settings_overrides, '{}'::jsonb) <> '{}'::jsonb "
    "FROM campaigns WHERE id = :cid"
)

#: Whether the campaign holds an engine agent now. One that does is republished even when it
#: no longer has anything of its own (its last override cleared while it runs): `dial_for`
#: keeps ringing a held engine agent, so leaving it unpublished would keep the old settings
#: on its calls.
_HOLDS_ONE_SQL = "SELECT engine_agent_ref IS NOT NULL FROM campaigns WHERE id = :cid"


async def speaks_its_own(session: AsyncSession, campaign_id: UUID) -> bool:
    """See `_SPEAKS_ITS_OWN_SQL`."""
    return bool((await session.execute(text(_SPEAKS_ITS_OWN_SQL), {"cid": campaign_id})).scalar())


async def put_campaign_live(*, tenant_id: UUID, campaign_id: UUID) -> str | None:
    """Start's and Schedule's first step: the campaign's own engine agent is created or
    brought up to date and read back, in its own committed transaction, so the dial that
    follows rings what the campaign says now. A free-trial account is refused with the step
    that opens campaigns, before anything reaches the calling platform. None for a campaign
    that says what its agent says (`speaks_its_own`) and holds no engine agent yet."""
    async with tenant_session(tenant_id) as session:
        await refuse_on_trial(session, tenant_id=tenant_id, locked="campaigns")
        if not await speaks_its_own(session, campaign_id) and not (
            (await session.execute(text(_HOLDS_ONE_SQL), {"cid": campaign_id})).scalar()
        ):
            return None
        ref = await agents_service.publish_campaign_agent(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
        # The agent's script version a campaign put live (before D-1003) no longer
        # describes anything: the agent's own script is untouched.
        await session.execute(
            text(
                "UPDATE campaigns SET script_live_version = NULL "
                "WHERE id = :cid AND script_live_version IS NOT NULL"
            ),
            {"cid": campaign_id},
        )
    return ref


async def campaign_test_dial(
    *, tenant_id: UUID, campaign_id: UUID, developer: bool
) -> CampaignDial:
    """Get the campaign's engine agent ready for the owner's test call, in its own committed
    transaction before the dial (`inbound/publish.line_test_dial`'s shape). Published as a
    test holder (`publish_campaign_agent(test=True)`), whatever the campaign's state; with
    `developer` (a free trial, or a paying account with no number yet) in our developer
    workspace, where the shared trial line rings (D-697, D-859)."""
    async with tenant_session(tenant_id) as session:
        ref = await agents_service.publish_campaign_agent(
            session, tenant_id=tenant_id, campaign_id=campaign_id, test=True, developer=developer
        )
    return CampaignDial(ref=ref, campaign_id=campaign_id)


async def dial_for(*, tenant_id: UUID, campaign_id: UUID) -> CampaignDial | None:
    """The engine agent a campaign's next dial rings through, or None for its agent's own.

    A campaign going with none of its own (one running at deploy, before D-1003, or one whose
    Start could not finish) has it published now, in its own transaction. None for a campaign
    that says what its agent says (`speaks_its_own`), and for one that put its script on its
    agent before D-1003 (`campaigns.agent_held_at`) whose own engine agent cannot be made yet
    (the workspace's allowance is full, the platform refused): its agent still speaks its
    script, so it keeps dialling through the agent exactly as before rather than dropping a
    call, and the hourly sweep gives that agent its own script back only once the campaign
    has its own. Any other failure is raised: the campaign does not dial."""
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT engine_agent_ref, status, agent_held_at IS NOT NULL FROM campaigns "
                    "WHERE id = :cid AND archived_at IS NULL"
                ),
                {"cid": campaign_id},
            )
        ).first()
    if row is None:
        raise ProblemError.not_found("Campaign")
    if row[0] and str(row[1]) in CAMPAIGN_HOLDING_STATUSES:
        return CampaignDial(ref=str(row[0]), campaign_id=campaign_id)
    try:
        ref = await put_campaign_live(tenant_id=tenant_id, campaign_id=campaign_id)
        if ref is None:
            return None
    except Exception as exc:
        if not row[2]:
            raise
        log.warning(
            "campaign_dials_through_its_agent_until_its_own",
            extra={
                "campaign_id": str(campaign_id),
                "reason": exc.code if isinstance(exc, ProblemError) else type(exc).__name__,
            },
        )
        return None
    log.info("campaign_engine_agent_published_for_dial", extra={"campaign_id": str(campaign_id)})
    return CampaignDial(ref=ref, campaign_id=campaign_id)


async def held_dial(session: AsyncSession, *, campaign_id: UUID | None) -> CampaignDial | None:
    """The engine agent a call made FOR a campaign rings through when the campaign still
    holds one (a call-back it promised): the campaign's own script, else None for the
    agent's. Read on the caller's session; never publishes."""
    if campaign_id is None:
        return None
    ref = (
        await session.execute(
            text(
                "SELECT engine_agent_ref FROM campaigns WHERE id = :cid AND archived_at IS NULL "
                "AND status = ANY(:holding)"
            ),
            {"cid": campaign_id, "holding": list(CAMPAIGN_HOLDING_STATUSES)},
        )
    ).scalar_one_or_none()
    return CampaignDial(ref=str(ref), campaign_id=campaign_id) if ref else None


async def end_campaign_agent(
    session: AsyncSession, *, campaign_id: UUID, deleting: bool = False
) -> bool:
    """A campaign stopped, completed, unscheduled, archived or about to be deleted gives its
    engine agent back, in the caller's transaction (`agents/service.retire_campaign_agent`).
    True when it had one. A campaign still going keeps it; the hourly sweep
    (`workers/campaign_engine_agents`) retires any a path here missed."""
    row = (
        await session.execute(
            text(
                "SELECT tenant_id, status, archived_at IS NOT NULL, engine_agent_ref IS NOT NULL "
                "FROM campaigns WHERE id = :cid"
            ),
            {"cid": campaign_id},
        )
    ).first()
    if row is None or not row[3]:
        return False
    if not deleting and str(row[1]) in CAMPAIGN_HOLDING_STATUSES and not row[2]:
        return False
    return (
        await agents_service.retire_campaign_agent(
            session, tenant_id=UUID(str(row[0])), campaign_id=campaign_id
        )
        is not None
    )


__all__ = [
    "campaign_test_dial",
    "dial_for",
    "end_campaign_agent",
    "held_dial",
    "put_campaign_live",
]
