"""The drift sweep reads every engine holder against the config that holder was published with.

Hard rule 5 asks for the truthful answers verified "on every publish and every drift sweep".
An inbound line's own engine agent (D-997) and an agent's "Just the business" test copy
(D-1000) each hold a config that is not the agent's own: the line's script, or the agent with
no job's script. Compared against the agent's config, each reads as `not_applied` on every
tick, so the alarm rings for objects that are exactly right and a real edit in the vendor's
console is indistinguishable from the noise.
"""

from __future__ import annotations

import pytest
from apps.api.agents import paid_test_calls
from apps.api.agents.publishing import engine_drift_for
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.api.engine.fake import FakeEngine
from apps.api.inbound.publish import put_line_live
from sqlalchemy import text
from tests.agent_business_only_test import _with_training
from tests.inbound_lines_test import _line, _live_agent
from tests.kb_workflow_test import _tenant_with_published_agent

pytestmark = [pytest.mark.rls]


async def test_a_live_line_is_compared_against_its_own_script() -> None:
    tenant_id, agent_id, _token = await _live_agent()
    line_id = await _line(tenant_id, agent_id)
    ref = await put_line_live(tenant_id=tenant_id, line_id=line_id)

    drift = await engine_drift_for(tenant_id=tenant_id, agent_id=agent_id, engine_agent_ref=ref)

    assert drift.engine_agent_ref == ref
    assert drift.state == "applied", drift.detail
    assert drift.truthful_answer_applied is True


async def test_a_line_edited_in_the_vendors_console_reads_as_drift() -> None:
    tenant_id, agent_id, _token = await _live_agent()
    line_id = await _line(tenant_id, agent_id)
    ref = await put_line_live(tenant_id=tenant_id, line_id=line_id)
    engine = get_engine()
    assert isinstance(engine, FakeEngine)
    held = engine._agents[ref]
    engine._agents[ref] = held.model_copy(update={"system_prompt": "Something nobody approved."})

    drift = await engine_drift_for(tenant_id=tenant_id, agent_id=agent_id, engine_agent_ref=ref)

    assert drift.state == "not_applied"


async def test_an_archived_lines_engine_agent_is_not_compared() -> None:
    tenant_id, agent_id, _token = await _live_agent()
    line_id = await _line(tenant_id, agent_id)
    ref = await put_line_live(tenant_id=tenant_id, line_id=line_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE inbound_lines SET archived_at = now() WHERE id = :l"), {"l": line_id}
        )

    drift = await engine_drift_for(tenant_id=tenant_id, agent_id=agent_id, engine_agent_ref=ref)

    assert drift.state == "not_published"


async def test_a_business_only_copy_is_compared_against_just_the_business() -> None:
    tenant_id, agent_id = await _tenant_with_published_agent()
    await _with_training(tenant_id)
    ref = await paid_test_calls.refresh_test_copy(
        tenant_id=tenant_id, agent_id=agent_id, business=True
    )

    drift = await engine_drift_for(tenant_id=tenant_id, agent_id=agent_id, engine_agent_ref=ref)

    assert drift.state == "applied", drift.detail
    assert drift.truthful_answer_applied is True
