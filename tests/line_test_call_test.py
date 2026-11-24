"""An inbound line's test call (Phase 3b): the owner hears a line, draft or live, on its own
engine agent, through every gate a test call has.

1. A draft line with no number, in the voice of an agent never published, rings the owner
   from the shared trial line through the line's own test holder, and stays a draft.
2. The call carries the line, is listed under the line's Test call, and not as a call taken.
3. A refused gate is an answer and readies nothing; a line with no script is refused by
   name with the key freed.

The engine is the test deployment's fake; the shared number's lend is the recorder
`trial_call_placement_test` uses.
"""

from __future__ import annotations

import uuid
from uuid import UUID

import pytest
from apps.api.agents import trial_calls
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.inbound import lines
from apps.api.inbound import routes as inbound_routes
from calevate_shared.call_script import CallScript
from sqlalchemy import text
from tests.trial_call_placement_test import Line, _account, line  # noqa: F401

pytestmark = [pytest.mark.rls]

SCRIPT = CallScript(opening_line="Namaste, Trial Tea House. How can I help you today?")


async def _draft_line(tenant_id: UUID, agent_id: UUID, *, script: bool = True) -> UUID:
    async with tenant_session(tenant_id) as session:
        line_id = await lines.create_line(
            session, tenant_id=tenant_id, agent_id=agent_id, name="Front desk", created_by=None
        )
        if script:
            await lines.save_script(session, line_id, SCRIPT, author="owner")
    return line_id


async def _ring(
    principal: Principal, agent_id: UUID, line_id: UUID, key: str
) -> trial_calls.TrialCallResult:
    assert principal.tenant_id is not None
    async with tenant_session(principal.tenant_id) as session:
        return await trial_calls.place_trial_call(
            session,
            principal=principal,
            agent_id=agent_id,
            number="98765 43210",
            idempotency_key=key,
            line_id=line_id,
        )


async def test_a_draft_line_with_no_number_is_heard_and_stays_a_draft(line: Line) -> None:  # noqa: F811
    tenant_id, agent_id, principal = await _account(line, direction="inbound")
    line_id = await _draft_line(tenant_id, agent_id)

    placed = await _ring(principal, agent_id, line_id, str(uuid.uuid4()))

    assert placed.status == "queued", placed
    async with tenant_session(tenant_id) as session:
        held = await lines.read_line(session, line_id)
        agent_ref = (
            await session.execute(
                text("SELECT engine_agent_ref FROM agents WHERE id = :a"), {"a": agent_id}
            )
        ).scalar_one()
        call = (
            await session.execute(
                text("SELECT inbound_line_id, trial_call FROM calls WHERE id = :c"),
                {"c": placed.call_id},
            )
        ).one()
        route = (
            await session.execute(
                text("SELECT inbound_line_id FROM engine_agent_routes WHERE engine_agent_ref = :r"),
                {"r": held.engine_agent_ref},
            )
        ).scalar_one()
    assert agent_ref is None, "the agent itself was never published"
    assert held.engine_agent_ref is not None and held.published_at is None and not held.live
    assert line.lent_to == [held.engine_agent_ref], "rung through the line's own engine agent"
    assert (call.inbound_line_id, call.trial_call) == (line_id, True)
    assert route == line_id

    async with tenant_session(tenant_id) as session:
        listed = await inbound_routes.line_test_calls(line_id, session, principal)
        taken = await inbound_routes.line_calls(line_id, session, principal)
    assert [item.call_id for item in listed] == [placed.call_id]
    assert taken.calls == [], "a test call is not a call the line took"


async def test_a_refused_gate_readies_nothing(line: Line) -> None:  # noqa: F811
    tenant_id, agent_id, principal = await _account(line, direction="inbound", pledged=False)
    line_id = await _draft_line(tenant_id, agent_id)
    placed = await _ring(principal, agent_id, line_id, str(uuid.uuid4()))
    assert placed.status == "blocked" and placed.blocked_rule
    async with tenant_session(tenant_id) as session:
        held = await lines.read_line(session, line_id)
    assert held.engine_agent_ref is None and line.lent_to == []


async def test_a_line_with_no_script_is_refused_by_name_and_frees_the_key(line: Line) -> None:  # noqa: F811
    tenant_id, agent_id, principal = await _account(line, direction="inbound")
    line_id = await _draft_line(tenant_id, agent_id, script=False)
    key = str(uuid.uuid4())
    with pytest.raises(ProblemError) as refused:
        await _ring(principal, agent_id, line_id, key)
    assert refused.value.code == "line_has_no_script"
    async with tenant_session(tenant_id) as session:
        await lines.save_script(session, line_id, SCRIPT, author="owner")
    placed = await _ring(principal, agent_id, line_id, key)
    assert placed.status == "queued", "the same key may try again once the line has a script"
