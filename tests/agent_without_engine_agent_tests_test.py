"""Test calls, chats and tests of an agent that holds no engine agent of its own (D-1019).

Only an inbound line or a campaign holds an engine agent; the agent itself is tried through its
developer-workspace test copy holding "Just the business" (`agents/business_only`), on the
shared test number, on a trial and on a paid account alike. An agent still holding one keeps
its own path. Driven through `trial_calls.place_trial_call`, `paid_test_calls.line_of`,
`try_chat.send`, the saved-test worker, the copies sweep and the workspace move.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents import paid_test_calls, trial_calls
from apps.api.agents import service as agents_service
from apps.api.agents import test_conversations as tc
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine.test_chat import TestChatTurn as ChatTurn
from apps.api.go_live import moves
from apps.api.teach import try_chat
from apps.workers import agent_moves
from apps.workers import agent_test_cases as case_worker
from sqlalchemy import text
from tests.kb_workflow_test import _tenant_with_published_agent
from tests.trial_call_placement_test import Line, _account, line  # noqa: F401

pytestmark = [pytest.mark.rls]

COPY = "fakeagent_business_copy"


async def _drop_own_ref(tenant_id: UUID, agent_id: UUID) -> None:
    """The agent as `agents_hold_engine_agent` off leaves it: ready, holding no engine agent."""
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = NULL WHERE id = :a"), {"a": agent_id}
        )


# --- which line a paid test call takes ------------------------------------------------------


@pytest.mark.parametrize(
    ("ref", "numbers", "expected"),
    [
        (None, [], "trial_line_copy"),
        (None, ["num_1@org_mine"], "trial_line_copy"),
        ("ag_dev", [], "trial_line_own"),
        ("ag_1@org_mine", ["num_1@org_mine"], "own_number"),
        ("ag_1@org_mine", [], "trial_line_copy"),
        ("ag_1@org_other", ["num_1@org_mine"], "trial_line_copy"),
    ],
)
def test_the_line_of_a_paid_test_call(
    ref: str | None, numbers: list[str], expected: paid_test_calls.PaidLine
) -> None:
    row = ("live", "both", ref, numbers, None)
    assert paid_test_calls.line_of(row, "org_mine") == expected


# --- the test call ---------------------------------------------------------------------------


class _Dials:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.refreshed: list[dict[str, Any]] = []


@pytest.fixture
def dials(monkeypatch: pytest.MonkeyPatch) -> _Dials:
    """Records what the call would dial, after the gate; the dial itself is `dispatch_call`'s
    own tests'."""
    state = _Dials()

    async def _dispatch(_session: Any, **kwargs: Any) -> str:
        state.calls.append(kwargs)
        await kwargs["on_reserved"](None, uuid7())
        return "call_handle"

    async def _refresh(**kwargs: Any) -> str:
        state.refreshed.append(kwargs)
        return COPY

    async def _allowed(*_a: Any, **_k: Any) -> Any:
        return SimpleNamespace(allowed=True, rule=None, reason=None)

    monkeypatch.setattr(agents_service, "dispatch_call", _dispatch)
    monkeypatch.setattr(trial_calls, "refresh_test_copy", _refresh)
    # The gate's answer for an agent with no engine agent is the dial gate's own (WP-C).
    monkeypatch.setattr(trial_calls, "check_dispatch", _allowed)
    return state


def _paid(monkeypatch: pytest.MonkeyPatch, line_kind: str) -> None:
    async def _no_trial(*_a: Any, **_k: Any) -> None:
        return None

    async def _access(*_a: Any, **_k: Any) -> Any:
        return SimpleNamespace(
            blocker=None,
            line=line_kind,
            max_call_seconds=600,
            daily_cap=3,
            day_start=datetime.now(UTC),
        )

    monkeypatch.setattr(trial_calls, "read_trial_access", _no_trial)
    monkeypatch.setattr(trial_calls, "read_paid_test_access", _access)


async def _place(tenant_id: UUID, agent_id: UUID, principal: Any) -> trial_calls.TrialCallResult:
    async with tenant_session(tenant_id) as session:
        return await trial_calls.place_trial_call(
            session,
            principal=principal,
            agent_id=agent_id,
            number="98765 43210",
            idempotency_key=str(uuid.uuid4()),
        )


@pytest.mark.parametrize(
    ("paid_line", "holds_own", "through_copy", "dial_ref"),
    [
        (None, True, False, None),  # trial, its own developer-workspace agent
        (None, False, True, COPY),  # trial, nothing of its own: the business copy
        ("trial_line_copy", False, True, COPY),  # paid, nothing of its own
        ("trial_line_own", True, False, None),  # paid, not moved yet
        ("own_number", True, False, "own"),  # paid, its own number
    ],
)
async def test_a_plain_test_call_rings_through_the_business_copy_without_an_engine_agent(
    line: Line,  # noqa: F811
    dials: _Dials,
    monkeypatch: pytest.MonkeyPatch,
    paid_line: str | None,
    holds_own: bool,
    through_copy: bool,
    dial_ref: str | None,
) -> None:
    tenant_id, agent_id, principal = await _account(line)
    if paid_line is not None:
        _paid(monkeypatch, paid_line)
    if not holds_own:
        await _drop_own_ref(tenant_id, agent_id)

    placed = await _place(tenant_id, agent_id, principal)

    assert placed.status == "queued", placed
    assert dials.refreshed == (
        [{"tenant_id": tenant_id, "agent_id": agent_id, "business": True}] if through_copy else []
    )
    [call] = dials.calls
    trial = call["trial"]
    if dial_ref == "own":
        assert trial is None, "its own number rings: no shared line"
    else:
        assert trial is not None and trial.from_e164 == get_settings().trial_caller_number
        assert trial.agent_ref == dial_ref
    assert (call["owner_test"] is not None) == (paid_line is not None)
    if through_copy and paid_line is not None:
        # The shared line's per-call limit, never the agent's own longer one.
        assert call["owner_test"].max_call_seconds == get_settings().trial_call_max_seconds


async def test_an_account_with_its_agreements_waiting_is_refused_before_the_copy_is_touched(
    line: Line,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The first test call of a trial account: the dial gate asks the agreements before
    anything is published, so the copy's own `assert_agreements_accepted` is never the
    refusal the owner reads."""
    from apps.api.compliance import service as compliance_service

    tenant_id, agent_id, principal = await _account(line)
    refreshed: list[Any] = []

    async def _waiting(*_a: Any, **_k: Any) -> tuple[str, str]:
        return ("agreements_not_accepted", "Accept the agreements first.")

    async def _refresh(**kwargs: Any) -> str:
        refreshed.append(kwargs)
        return COPY

    monkeypatch.setattr(compliance_service, "agreements_blocker", _waiting)
    monkeypatch.setattr(trial_calls, "refresh_test_copy", _refresh)
    async with tenant_session(tenant_id) as session:
        placed = await trial_calls.place_trial_call(
            session,
            principal=principal,
            agent_id=agent_id,
            number="98765 43210",
            idempotency_key=str(uuid.uuid4()),
            business=True,
        )
    assert (placed.status, placed.blocked_rule) == ("blocked", "agreements_not_accepted")
    assert refreshed == [] and line.lent_to == []


@pytest.mark.xfail(
    strict=True,
    reason=(
        "D-1019 WP-C: check_dispatch must let a ready agent with no engine agent place its "
        "test-copy call (compliance/service.py:1205), and dispatch_call must take its ref "
        "from trial.agent_ref (agents/service.py:5424-5435)"
    ),
)
async def test_from_onboarding_to_the_first_test_call_without_an_engine_agent(
    line: Line,  # noqa: F811
) -> None:
    """A new trial account, its agent got ready with no engine agent of its own, rings the
    owner through the real gate and dial, from the shared number, through its business copy."""
    tenant_id, agent_id, principal = await _account(line)
    await _drop_own_ref(tenant_id, agent_id)

    placed = await _place(tenant_id, agent_id, principal)

    assert placed.status == "queued", placed
    async with tenant_session(tenant_id) as session:
        copy = (
            await session.execute(
                text("SELECT engine_agent_ref, business_only FROM agent_test_copies")
            )
        ).one()
    assert copy.business_only
    assert line.lent_to == [copy.engine_agent_ref]


# --- the chat and the saved tests ------------------------------------------------------------


def _turn(session: str = "s-1") -> Any:
    return ChatTurn(session=session, reply="Hello.", tools=())


async def test_try_chat_without_an_engine_agent_talks_to_the_business_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _tenant_with_published_agent()
    await _drop_own_ref(tenant_id, agent_id)
    seen: list[tuple[str, str | None]] = []

    async def _nothing(*_a: Any, **_k: Any) -> None:
        return None

    async def _send(_engine: Any, *, engine_agent_ref: str, session: str | None, **_k: Any) -> Any:
        seen.append((engine_agent_ref, session))
        return _turn()

    monkeypatch.setattr(try_chat, "RunsTestChat", object)
    monkeypatch.setattr(tc, "RunsTestChat", object)
    monkeypatch.setattr(try_chat, "require_ai_assist", _nothing)
    monkeypatch.setattr(try_chat, "send_test_message", _send)
    async with tenant_session(tenant_id) as session:
        for said, chat in (("When are you open?", None), ("And on Sunday?", "s-1")):
            await try_chat.send(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                message=said,
                chat_session=chat,
            )
        copy = (
            await session.execute(
                text("SELECT engine_agent_ref, business_only FROM agent_test_copies")
            )
        ).one()
    assert copy.business_only
    assert seen == [(copy.engine_agent_ref, None), (copy.engine_agent_ref, "s-1")]


async def test_a_draft_with_no_engine_agent_is_not_testable_and_a_ready_one_is(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _tenant_with_published_agent()
    await _drop_own_ref(tenant_id, agent_id)
    monkeypatch.setattr(tc, "RunsTestChat", object)
    async with tenant_session(tenant_id) as session:
        assert (await tc.readiness(session, agent_id)).available
        await session.execute(
            text("UPDATE agents SET status = 'draft' WHERE id = :a"), {"a": agent_id}
        )
        unready = await tc.readiness(session, agent_id)
    assert not unready.available and unready.reason and "Get it ready" in unready.reason


async def test_saved_tests_of_an_agent_with_no_engine_agent_run_on_the_business_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _tenant_with_published_agent()
    await _drop_own_ref(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO agent_test_cases (id, tenant_id, agent_id, title, caller_lines, "
                "expected, status) VALUES (:i, :t, :a, 'Hours', '[\"When do you open?\"]'::jsonb, "
                "'Says nine', 'queued')"
            ),
            {"i": uuid.uuid4(), "t": tenant_id, "a": agent_id},
        )
    talked_to: list[str] = []

    class _Chat:
        async def test_chat(self, ref: str, message: str, **_k: Any) -> ChatTurn:
            talked_to.append(ref)
            return _turn()

    async def _no_pause() -> None:
        return None

    monkeypatch.setattr(case_worker, "get_engine", lambda: _Chat())
    monkeypatch.setattr(case_worker, "RunsTestChat", object)
    monkeypatch.setattr(case_worker, "_pause", _no_pause)
    monkeypatch.setattr(
        case_worker, "hosted_agent_limits", lambda _e: SimpleNamespace(knowledge_tool=None)
    )
    payload = {"tenant_id": str(tenant_id), "agent_id": str(agent_id)}
    assert await case_worker.run_agent_test_cases({}, payload) == "done"
    async with tenant_session(tenant_id) as session:
        copy = (
            await session.execute(
                text("SELECT engine_agent_ref, business_only FROM agent_test_copies")
            )
        ).one()
    assert copy.business_only
    assert talked_to == [copy.engine_agent_ref]


async def test_a_copy_under_a_live_call_is_tested_as_it_is(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _tenant_with_published_agent()
    ref = await paid_test_calls.refresh_test_copy(
        tenant_id=tenant_id, agent_id=agent_id, business=True
    )

    async def _live(*_a: Any) -> bool:
        return True

    async def _never(**_k: Any) -> str:
        raise AssertionError("a copy under a call is not republished")

    monkeypatch.setattr(paid_test_calls, "copy_call_live", _live)
    monkeypatch.setattr(paid_test_calls, "refresh_test_copy", _never)
    assert (
        await paid_test_calls.agent_test_ref(tenant_id=tenant_id, agent_id=agent_id, own_ref=None)
        == ref
    )
    assert (
        await paid_test_calls.agent_test_ref(tenant_id=tenant_id, agent_id=agent_id, own_ref="own")
        == "own"
    )


# --- copies and moves ------------------------------------------------------------------------


async def test_the_sweep_keeps_the_copy_of_an_agent_with_no_engine_agent_once_numbered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _tenant_with_published_agent()
    await _drop_own_ref(tenant_id, agent_id)
    retired: list[str] = []
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO agent_test_copies (id, tenant_id, agent_id, engine_agent_ref, "
                "business_only) VALUES (:i, :t, :a, :r, false)"
            ),
            {"i": uuid7(), "t": tenant_id, "a": agent_id, "r": f"ref_{uuid.uuid4().hex}"},
        )

        async def _retire(_session: Any, *, ref: str, **_k: Any) -> None:
            retired.append(ref)

        monkeypatch.setattr(agents_service, "retire_engine_agent", _retire)
        monkeypatch.setattr(agent_moves, "_OWN_NUMBERS_SQL", "SELECT 'num@org_own'")
        monkeypatch.setattr(agent_moves, "scope_of", lambda _ref: "org_own")
        await agent_moves._retire_test_copies(session, tenant_id=tenant_id, workspace="org_own")
    assert retired == []


async def test_nothing_moves_once_agents_hold_no_engine_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _tenant_with_published_agent()
    async with tenant_session(tenant_id) as session:
        assert await moves.agents_to_move(session, tenant_id=tenant_id, workspace="org_x") == [
            agent_id
        ]
        monkeypatch.setattr(moves, "agents_hold_engine_agent", lambda: False)
        assert await moves.agents_to_move(session, tenant_id=tenant_id, workspace="org_x") == []
        progress = await moves.read_move_progress(session, tenant_id=tenant_id, workspace="org_x")
    assert progress.state == "done" and progress.agents == ()
    assert await moves.move_agent(tenant_id=tenant_id, agent_id=agent_id, workspace="org_x") == (
        "already"
    )


async def test_an_agent_with_no_engine_agent_is_not_a_move_candidate() -> None:
    tenant_id, agent_id = await _tenant_with_published_agent()
    await _drop_own_ref(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        assert await moves.agents_to_move(session, tenant_id=tenant_id, workspace="org_x") == []
    assert await moves.move_agent(tenant_id=tenant_id, agent_id=agent_id, workspace="org_x") == (
        "already"
    )
