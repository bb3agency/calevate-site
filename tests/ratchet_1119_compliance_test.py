"""The dial gate on a campaign with no script of its own: it is judged on the opening its
agent speaks, exactly as the agent's own call would be (D-1003)."""

from __future__ import annotations

from apps.api.compliance import service as compliance_service
from apps.api.db.session import tenant_session
from tests.campaign_engine_agents_test import _campaign
from tests.trial_call_placement_test import Line, _account, line  # noqa: F401


async def test_a_campaign_with_no_script_is_gated_on_its_agents_own_opening(
    line: Line,  # noqa: F811
) -> None:
    tenant_id, agent_id, _principal = await _account(line)
    campaign_id = await _campaign(tenant_id, agent_id, script=None)

    async with tenant_session(tenant_id) as session:
        assert (
            await compliance_service._campaign_opening_body(
                session, campaign_id=campaign_id, agent_id=agent_id
            )
            is None
        )
        through_campaign = await compliance_service.check_dispatch(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            phone_e164="+919876543210",
            trial_call=True,
            through_line=True,
            campaign_id=campaign_id,
        )
        through_agent = await compliance_service.check_dispatch(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            phone_e164="+919876543210",
            trial_call=True,
            through_line=True,
        )

    assert through_campaign.rule != compliance_service.DISCLOSURE_NOT_SAID_RULE
    assert (through_campaign.allowed, through_campaign.rule) == (
        through_agent.allowed,
        through_agent.rule,
    )
