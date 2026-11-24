"""The step outcomes gate the call (founder, 24 Nov 2026: "not just filling them automatically,
but it should actually do something"): the instructions forbid leaving a step before its
outcome, each engine step says when it may go on, and a campaign's own engine agent carries
the outcomes."""

from __future__ import annotations

import pytest
from apps.api.agents.service import campaign_config
from apps.api.db.session import tenant_session
from calevate_shared.call_script import (
    OUTCOMES_HEADER,
    OUTCOMES_LEAD,
    StepOutcome,
    compile_call_script,
    native_steps,
)
from sqlalchemy import text
from tests.dispatch_budget_test import _tenant
from tests.step_outcomes_test import _campaign, _script


def test_the_instructions_forbid_leaving_a_step_before_its_outcome() -> None:
    """FAILS IF: the outcomes section only says to go on once reached, without forbidding
    going on before, which a model reads as a suggestion."""
    assert "Go on to the next step only when what they say shows the outcome" in OUTCOMES_LEAD
    body = compile_call_script(
        _script([StepOutcome(step=n, outcome=f"Step {n} is done.") for n in (1, 2, 3)])
    )
    assert f"{OUTCOMES_HEADER} {OUTCOMES_LEAD}" in body
    assert "Step 2 (Installs it, Already has it): Step 2 is done." in body


def test_each_engine_step_says_when_it_may_go_on() -> None:
    """FAILS IF: an engine step carries its outcome as a description rather than a gate."""
    steps = native_steps(_script([StepOutcome(step=2, outcome="The app is open.")]))
    assert steps[1].detail.endswith("Go on only when: The app is open.")
    assert steps[2].detail.endswith("Go on only when: The app is open.")
    assert "Go on only when" not in steps[0].detail


@pytest.mark.anyio
async def test_a_campaigns_engine_agent_carries_its_outcomes() -> None:
    """FAILS IF: a campaign's own engine agent is built without the outcomes on its script."""
    tenant_id, agent_id = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id)
    script = _script(
        [StepOutcome(step=n, outcome=f"Outcome of step {n} reached.") for n in (1, 2, 3)]
    )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaigns SET script = CAST(:s AS jsonb) WHERE id = :c"),
            {"s": script.model_dump_json(), "c": campaign_id},
        )
        config = await campaign_config(session, tenant_id=tenant_id, campaign_id=campaign_id)
    sent = config.system_prompt + "\n".join(step.detail for step in config.script_steps)
    assert OUTCOMES_HEADER in config.system_prompt
    for n in (1, 2, 3):
        assert f"Outcome of step {n} reached" in sent
