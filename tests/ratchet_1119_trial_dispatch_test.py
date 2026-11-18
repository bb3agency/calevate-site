"""Test calls and campaign dial-through on the edges the 19 Nov ratchet found untested.

A test call names one thing to ring through; a paid line test needs one of its own numbers;
a full client workspace with no shared number says what holds its setups; a shared-line test
whose number was cleared after the readiness check refuses rather than dial from nothing;
and a running campaign whose engine agent cannot be made alarms and places nothing.
"""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents import service as agents_service
from apps.api.agents import trial_calls
from apps.api.agents.workspace_slots import ENGINE_AGENT_ALLOWANCE_FULL_RULE
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.api.inbound import lines
from apps.workers import campaign_dispatch
from tests.campaign_engine_agents_test import _campaign
from tests.trial_call_placement_test import Line, _account, line  # noqa: F401
from tests.workspace_slots_test import SCRIPT, _fill, _number, _paid_with_a_number_in


async def _draft_line(tenant_id: UUID, agent_id: UUID) -> UUID:
    async with tenant_session(tenant_id) as session:
        line_id = await lines.create_line(
            session, tenant_id=tenant_id, agent_id=agent_id, name="Front desk", created_by=None
        )
        await lines.save_script(session, line_id, SCRIPT)
    return line_id


async def _place_line_test(
    tenant_id: UUID, agent_id: UUID, principal: Any, line_id: UUID, key: str | None = None
) -> trial_calls.TrialCallResult:
    async with tenant_session(tenant_id) as session:
        return await trial_calls.place_trial_call(
            session,
            principal=principal,
            agent_id=agent_id,
            number="98765 43210",
            idempotency_key=key or str(uuid.uuid4()),
            line_id=line_id,
        )


async def test_a_test_call_names_one_thing_to_ring_through(line: Line) -> None:  # noqa: F811
    tenant_id, agent_id, principal = await _account(line)
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ValueError, match="one of them"):
            await trial_calls.place_trial_call(
                session,
                principal=principal,
                agent_id=agent_id,
                number="98765 43210",
                idempotency_key=str(uuid.uuid4()),
                business=True,
                line_id=uuid.uuid4(),
            )


async def test_a_line_test_in_a_full_workspace_with_no_shared_number_names_the_setups(
    line: Line,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id, principal, workspace = await _paid_with_a_number_in(line, monkeypatch)
    await _number(tenant_id, workspace)
    await _fill(tenant_id, agent_id, workspace)
    line_id = await _draft_line(tenant_id, agent_id)
    monkeypatch.setattr(trial_calls, "trial_calling_ready", lambda: False)

    refused = await _place_line_test(tenant_id, agent_id, principal, line_id)

    assert (refused.status, refused.blocked_rule) == ("blocked", ENGINE_AGENT_ALLOWANCE_FULL_RULE)
    assert refused.blocked_reason is not None
    assert refused.blocked_reason.startswith("Test calls need a free calling setup.")
    assert line.lent_to == [], "nothing rang from the shared number"


async def test_a_paid_line_test_with_none_of_its_own_numbers_says_get_a_number(
    line: Line,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id, principal, workspace = await _paid_with_a_number_in(line, monkeypatch)
    await _number(tenant_id, workspace)
    line_id = await _draft_line(tenant_id, agent_id)

    async def no_lines(*_a: Any, **_k: Any) -> list[Any]:
        return []

    monkeypatch.setattr(agents_service, "caller_lines", no_lines)
    refused = await _place_line_test(tenant_id, agent_id, principal, line_id)

    assert (refused.status, refused.blocked_rule, refused.blocked_reason) == (
        "blocked",
        trial_calls.LINE_TEST_NO_NUMBER_RULE,
        trial_calls.LINE_TEST_NO_NUMBER_REASON,
    )


async def test_a_failed_number_read_on_a_line_test_frees_the_attempt_to_be_tried_again(
    line: Line,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id, principal, workspace = await _paid_with_a_number_in(line, monkeypatch)
    await _number(tenant_id, workspace)
    line_id = await _draft_line(tenant_id, agent_id)
    real = agents_service.caller_lines

    async def broken(*_a: Any, **_k: Any) -> list[Any]:
        raise RuntimeError("numbers unreadable")

    monkeypatch.setattr(agents_service, "caller_lines", broken)
    key = str(uuid.uuid4())
    with pytest.raises(RuntimeError, match="numbers unreadable"):
        await _place_line_test(tenant_id, agent_id, principal, line_id, key)

    # The idempotency claim was released, so the same attempt is placed, not replayed.
    monkeypatch.setattr(agents_service, "caller_lines", real)
    again = await _place_line_test(tenant_id, agent_id, principal, line_id, key)
    assert again.status == "queued", again


async def test_a_shared_line_test_whose_number_was_cleared_meanwhile_refuses(
    line: Line,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id, principal = await _account(line)
    # Readiness was answered before the number went: the dial still has nothing to ring from.
    monkeypatch.setattr(get_settings(), "trial_caller_number", None)
    async with tenant_session(tenant_id) as session:
        refused = await trial_calls.place_trial_call(
            session,
            principal=principal,
            agent_id=agent_id,
            number="98765 43210",
            idempotency_key=str(uuid.uuid4()),
        )
    assert (refused.status, refused.blocked_rule) == ("blocked", trial_calls.NOT_READY_RULE)
    assert line.lent_to == []


async def test_a_campaign_whose_engine_agent_cannot_be_made_alarms_and_dials_nothing(
    line: Line,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id, _principal = await _account(line)
    campaign_id = await _campaign(tenant_id, agent_id, status="running")
    alarms: list[tuple[str, str]] = []

    async def refused(**_k: Any) -> Any:
        raise ProblemError.business_rule(ENGINE_AGENT_ALLOWANCE_FULL_RULE, "No free setup.")

    def record(stage: str, code: str, **_k: Any) -> None:
        alarms.append((stage, code))

    monkeypatch.setattr(campaign_dispatch, "dial_for", refused)
    monkeypatch.setattr(campaign_dispatch, "alert", record)

    dial, rule = await campaign_dispatch._campaign_dial(tenant_id, campaign_id)

    assert (dial, rule) == (None, ENGINE_AGENT_ALLOWANCE_FULL_RULE)
    assert alarms == [("CORE_LOGIC", "campaign_engine_agent_unavailable")]
