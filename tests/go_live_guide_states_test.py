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
