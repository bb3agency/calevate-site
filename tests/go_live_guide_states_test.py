"""The go-live guide names the real reason each step waits (e2e audit OB-1, OB-2, OB-8, OB-10).

Pure: `number_state` and `GoLive.current` decide what the owner reads, so they are driven
here without a database. The route and its reads are covered in `go_live_test.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from apps.api.campaigns.engine_number_purchase import PurchaseReadiness, PurchaseStep
from apps.api.go_live.guide import GoLive, GuideMarker, NumberState, number_state
from apps.api.go_live.moves import MoveProgress


def _readiness(step: PurchaseStep, business_status: str | None = None) -> PurchaseReadiness:
    return PurchaseReadiness(
        step=step,
        blocker=None if step == "ready" else step,
        workspace_status="active",
        kyc_status="verified",
        kyc_verified=True,
        business_status=business_status,
        business_can_rent=False,
        business_review_note=None,
        client_inr_per_month=None,
    )


@pytest.mark.parametrize(
    ("step", "status", "expected"),
    [
        ("ready", "accepted", "todo"),
        ("add_credit", None, "add_credit"),
        ("workspace", None, "setting_up"),
        ("verify_business", None, "locked"),
        ("price", "accepted", "not_on_sale"),
        ("business_details", None, "send_details"),
        ("business_details", "none", "send_details"),
        ("business_details", "draft", "send_details"),
        ("business_details", "submitted", "waiting_approval"),
        ("business_details", "accepted", "waiting_approval"),
        ("business_details", "rejected", "needs_attention"),
        ("business_details", "expired", "needs_attention"),
        ("business_details", "suspended", "needs_attention"),
    ],
)
def test_each_purchase_gate_has_its_own_number_state(
    step: PurchaseStep, status: str | None, expected: NumberState
) -> None:
    """A verified business held by the trial, the set-up or the price is never told to
    verify first, and a rejected application is never told it is being approved."""
    assert number_state(_readiness(step, status), numbers=0) == expected


def test_an_owned_number_is_done_whatever_the_gates_say() -> None:
    assert number_state(_readiness("price"), numbers=1) == "done"


def _guide(**overrides: Any) -> GoLive:
    fields: dict[str, Any] = {
        "marker": GuideMarker(owed_at=datetime.now(UTC), finished_at=None, dismissed_at=None),
        "move": MoveProgress(state="moving", agents=(), total=0),
        "verify": "done",
        "agreements": "done",
        "pledge": "done",
        "number": "todo",
        "business_review_note": None,
        "numbers": 0,
        "switch_on": "todo",
        "live_agents": 0,
    }
    fields.update(overrides)
    return GoLive(**fields)


def test_the_move_is_ours_and_never_the_owners_step() -> None:
    assert _guide(verify="todo").current == "verify"
    assert _guide().current == "number"


def test_unaccepted_agreements_hold_the_first_step() -> None:
    """Publishing refuses without them, so the guide must not move on to Switch it on."""
    assert _guide(agreements="todo").current == "verify"


def test_the_pledge_never_holds_the_guide() -> None:
    """It gates outgoing calls only; an agent that only answers needs no pledge."""
    assert _guide(pledge="todo", number="done").current == "switch_on"


@pytest.mark.rls
async def test_a_line_whose_agent_is_under_the_compliance_silence_is_not_switched_on() -> None:
    """The compliance silence unbinds the line's numbers (`route_line_numbers`), so the guide
    must not read Switch it on as done while that number rings nobody."""
    from apps.api.agents import service as agents_service
    from apps.api.db.session import tenant_session
    from apps.api.go_live.guide import read_go_live
    from apps.api.inbound.publish import put_line_live
    from tests.agent_lifecycle_test import _fresh_engine, _number
    from tests.inbound_lines_test import _attach, _line, _live_agent

    engine = _fresh_engine()
    tenant_id, agent_id, _ = await _live_agent()
    number_id = await _number(tenant_id, agent_id, ref="num_guide_truth_1")
    line_id = await _line(tenant_id, agent_id)
    await _attach(tenant_id, line_id, number_id)
    await put_line_live(tenant_id=tenant_id, line_id=line_id)
    async with tenant_session(tenant_id) as session:
        assert (await read_go_live(session, tenant_id=tenant_id)).switch_on == "done"
        await agents_service.reconcile_inbound_truthful_answer(
            session, engine, tenant_id=tenant_id, agent_id=agent_id, truthful_answer_applied=False
        )
    assert engine.inbound_agent_for("num_guide_truth_1") is None
    async with tenant_session(tenant_id) as session:
        guide = await read_go_live(session, tenant_id=tenant_id)
    assert guide.switch_on == "todo", "a silenced line was counted as answering"
    assert guide.live_lines == 0


@pytest.mark.rls
async def test_an_account_without_lines_whose_only_agent_is_silenced_is_not_switched_on() -> None:
    from apps.api.agents import service as agents_service
    from apps.api.db.session import tenant_session
    from apps.api.go_live.guide import read_go_live
    from tests.agent_lifecycle_test import _fresh_engine
    from tests.inbound_lines_test import _live_agent

    engine = _fresh_engine()
    tenant_id, agent_id, _ = await _live_agent()
    async with tenant_session(tenant_id) as session:
        assert (await read_go_live(session, tenant_id=tenant_id)).switch_on == "done"
        await agents_service.reconcile_inbound_truthful_answer(
            session, engine, tenant_id=tenant_id, agent_id=agent_id, truthful_answer_applied=False
        )
    async with tenant_session(tenant_id) as session:
        guide = await read_go_live(session, tenant_id=tenant_id)
    assert guide.switch_on == "todo", "a silenced agent was counted as answering"
