"""An agent that holds no engine agent of its own (D-1019, release R1).

1. With `agents_hold_engine_agent` off, publishing an agent that holds none creates none: its
   row goes live, its live lines are republished in its voice, nothing is routed to it, and
   the publish returns no handle. An agent already holding one is still updated in place, and
   with the setting on (the default) a publish creates one as before.
2. Its numbers on no live line are released; those on a live line answer with the line.
3. Every silence tolerates it: the credit stop and the maintenance read reach its live lines
   alone, and the compliance silence unbinds and restores its lines' numbers.
4. A number move decides from the client's workspace when the agent holds no engine agent,
   and a line's engine agent counts as one of this client's.
5. The healer repairs each engine agent that holds the agent's work.
6. The agent's "confirmed" answer is the worst verdict over those holders.

SHARED DATABASE DISCIPLINE: every organisation is minted here; the engine is the fake.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from apps.api.agents import lifecycle, publishing
from apps.api.agents import service as agents_service
from apps.api.campaigns import engine_numbers
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.api.inbound.publish import put_line_live
from apps.api.main import app
from apps.workers import healer
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.agent_lifecycle_test import (
    _app,
    _client,
    _code,
    _fresh_engine,
    _move,
    _number,
    _tenant,
    _write_script,
)
from tests.inbound_lines_test import _attach, _line, _live_agent

pytestmark = pytest.mark.rls


@pytest.fixture
def no_own_engine_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "agents_hold_engine_agent", False)


async def _agent_row(tenant_id: UUID, agent_id: UUID) -> Any:
    async with tenant_session(tenant_id) as session:
        return (
            await session.execute(
                text("SELECT status, engine_agent_ref FROM agents WHERE id = :a"), {"a": agent_id}
            )
        ).one()


async def _own_routes(tenant_id: UUID, agent_id: UUID) -> int:
    async with tenant_session(tenant_id) as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM engine_agent_routes WHERE agent_id = :a "
                        "AND tenant_id = :t AND inbound_line_id IS NULL AND campaign_id IS NULL"
                    ),
                    {"a": agent_id, "t": tenant_id},
                )
            ).scalar_one()
        )


async def _publish(tenant_id: UUID, agent_id: UUID) -> str | None:
    async with tenant_session(tenant_id) as session:
        return await agents_service.publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)


# --- 1. publishing --------------------------------------------------------------------------


@pytest.mark.usefixtures("no_own_engine_agent")
async def test_a_publish_with_the_setting_off_creates_no_engine_agent() -> None:
    engine = _fresh_engine()
    tenant_id, agent_id, _ = await _live_agent()

    status, ref = await _agent_row(tenant_id, agent_id)
    assert status == "live"
    assert ref is None, "the agent was given an engine agent of its own"
    assert engine._agents == {}, "a vendor agent was created for the agent"
    assert await _own_routes(tenant_id, agent_id) == 0
    assert await _publish(tenant_id, agent_id) is None


@pytest.mark.usefixtures("no_own_engine_agent")
async def test_a_publish_with_the_setting_off_republishes_the_agents_live_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _fresh_engine()
    tenant_id, agent_id, _ = await _live_agent()
    line_id = await _line(tenant_id, agent_id)
    line_ref = await put_line_live(tenant_id=tenant_id, line_id=line_id)
    republished: list[UUID] = []
    real = agents_service.publish_line

    async def recording(session: Any, **kwargs: Any) -> str:
        republished.append(kwargs["line_id"])
        return await real(session, **kwargs)

    monkeypatch.setattr(agents_service, "publish_line", recording)

    assert await _publish(tenant_id, agent_id) is None

    assert republished == [line_id]
    assert set(engine._agents) == {line_ref}


async def test_an_agent_already_holding_one_is_updated_in_place_with_the_setting_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _fresh_engine()
    tenant_id, agent_id, _ = await _live_agent()
    _, ref = await _agent_row(tenant_id, agent_id)
    assert ref is not None, "with the setting on (the default) a publish creates one"
    monkeypatch.setattr(get_settings(), "agents_hold_engine_agent", False)

    assert await _publish(tenant_id, agent_id) == ref
    assert set(engine._agents) == {ref}


async def test_a_ref_less_publish_racing_a_delete_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fresh_engine()
    monkeypatch.setattr(get_settings(), "agents_hold_engine_agent", False)
    tenant_id, agent_id, _ = await _live_agent()
    real = agents_service.refuse_unpriced_engine

    async with tenant_session(tenant_id) as session:

        async def deleting(sess: Any, engine: Any) -> None:
            await real(sess, engine)
            await sess.execute(
                text("UPDATE agents SET deleted_at = now() WHERE id = :a"), {"a": agent_id}
            )

        monkeypatch.setattr(agents_service, "refuse_unpriced_engine", deleting)
        with pytest.raises(ProblemError) as refused:
            await agents_service.publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    assert refused.value.code == "agent_deleted_during_publish"


# --- 2. numbers ------------------------------------------------------------------------------


@pytest.mark.usefixtures("no_own_engine_agent")
async def test_its_own_numbers_are_released_and_its_line_numbers_answer_with_the_line() -> None:
    engine = _fresh_engine()
    tenant_id, agent_id, _ = await _live_agent()
    own_number = await _number(tenant_id, agent_id, ref="num_own_1")
    line_number = await _number(tenant_id, agent_id, ref="num_line_1")
    line_id = await _line(tenant_id, agent_id)
    await _attach(tenant_id, line_id, line_number)
    line_ref = await put_line_live(tenant_id=tenant_id, line_id=line_id)
    engine._inbound["num_own_1"] = "stale_agent"

    await _publish(tenant_id, agent_id)

    assert engine.inbound_agent_for("num_own_1") is None, "a number on no line kept answering"
    assert engine.inbound_agent_for("num_line_1") == line_ref
    assert own_number != line_number


# --- 3. silences -----------------------------------------------------------------------------


@pytest.mark.usefixtures("no_own_engine_agent")
async def test_the_credit_stop_reaches_only_the_live_lines_of_an_agent_with_no_ref() -> None:
    engine = _fresh_engine()
    tenant_id, agent_id, _ = await _live_agent()
    lone_tenant, lone_agent, _ = await _live_agent()
    line_id = await _line(tenant_id, agent_id)
    line_ref = await put_line_live(tenant_id=tenant_id, line_id=line_id)

    async with tenant_session(tenant_id) as session:
        rows = (await session.execute(agents_service.ANSWERING_AGENTS_STATEMENT)).all()
        assert [row[0] for row in rows] == [agent_id]
        assert await agents_service.answering_refs(session, row=rows[0]) == [line_ref]
        cut = await agents_service.reconcile_inbound_answering(
            session, engine, tenant_id=tenant_id, exhausted=True
        )
    assert cut.silenced == 1 and cut.failed == 0
    assert agents_service.CREDIT_STOP_MESSAGE in engine._agents[line_ref].opening_line

    async with tenant_session(lone_tenant) as session:
        lone = (await session.execute(agents_service.ANSWERING_AGENTS_STATEMENT)).all()
    assert lone == [], "an agent with no ref and no live line was counted as answering"
    assert lone_agent != agent_id


@pytest.mark.usefixtures("no_own_engine_agent")
async def test_the_compliance_silence_unbinds_and_restores_a_ref_less_agents_lines() -> None:
    engine = _fresh_engine()
    tenant_id, agent_id, _ = await _live_agent()
    number_id = await _number(tenant_id, agent_id, ref="num_truth_1")
    line_id = await _line(tenant_id, agent_id)
    await _attach(tenant_id, line_id, number_id)
    line_ref = await put_line_live(tenant_id=tenant_id, line_id=line_id)
    assert engine.inbound_agent_for("num_truth_1") == line_ref

    async with tenant_session(tenant_id) as session:
        silenced = await agents_service.reconcile_inbound_truthful_answer(
            session, engine, tenant_id=tenant_id, agent_id=agent_id, truthful_answer_applied=False
        )
    assert silenced == "silenced"
    assert engine.inbound_agent_for("num_truth_1") is None

    async with tenant_session(tenant_id) as session:
        restored = await agents_service.reconcile_inbound_truthful_answer(
            session, engine, tenant_id=tenant_id, agent_id=agent_id, truthful_answer_applied=True
        )
    assert restored == "restored"
    assert engine.inbound_agent_for("num_truth_1") == line_ref


# --- 4. number moves -------------------------------------------------------------------------


async def test_a_number_move_decides_from_the_clients_workspace_for_a_ref_less_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id, _ = await _tenant()

    async def workspace(session: Any, tid: UUID) -> str | None:
        return "org_client_wpb" if tid == tenant_id else None

    monkeypatch.setattr(engine_numbers, "resolve_workspace", workspace)
    async with tenant_session(tenant_id) as session:
        assert await engine_numbers._agent_in_other_workspace(
            session, number_ref="919000000001", agent_id=agent_id
        ), "a platform-held number was not seen as outside the client's workspace"
        assert not await engine_numbers._agent_in_other_workspace(
            session, number_ref="919000000001@org_client_wpb", agent_id=agent_id
        )
        await engine_numbers.assert_same_workspace(
            session, number_ref="919000000001@org_client_wpb", agent_id=agent_id
        )
        with pytest.raises(ProblemError) as refused:
            await engine_numbers.assert_same_workspace(
                session, number_ref="919000000001", agent_id=agent_id
            )
    assert refused.value.code == "engine_number_other_workspace"

    monkeypatch.setattr(engine_numbers, "resolve_workspace", lambda *_: _none())
    async with tenant_session(tenant_id) as session:
        assert not await engine_numbers._agent_in_other_workspace(
            session, number_ref="919000000001", agent_id=agent_id
        ), "an agent answering nowhere refused a number"


async def _none() -> None:
    return None


@pytest.mark.usefixtures("no_own_engine_agent")
async def test_a_lines_engine_agent_is_this_clients_and_not_another_clients() -> None:
    _fresh_engine()
    tenant_id, agent_id, _ = await _live_agent()
    other_tenant, _other_agent, _ = await _tenant()
    line_ref = await put_line_live(tenant_id=tenant_id, line_id=await _line(tenant_id, agent_id))

    async with tenant_session(tenant_id) as session:
        assert await engine_numbers._is_this_clients_agent(session, line_ref, tenant_id=tenant_id)
    async with tenant_session(other_tenant) as session:
        assert not await engine_numbers._is_this_clients_agent(
            session, line_ref, tenant_id=other_tenant
        )


# --- 5. the healer ---------------------------------------------------------------------------


@pytest.mark.usefixtures("no_own_engine_agent")
async def test_the_healer_repairs_each_engine_agent_holding_a_ref_less_agents_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fresh_engine()
    tenant_id, agent_id, _ = await _live_agent()
    assert await healer.repair_agent_plumbing(tenant_id, agent_id) == "not_published"
    line_ref = await put_line_live(tenant_id=tenant_id, line_id=await _line(tenant_id, agent_id))
    seen: list[str] = []

    async def settings(*, tenant_id: UUID, agent_id: UUID, engine_agent_ref: str) -> None:
        seen.append(engine_agent_ref)

    class _Webhook:
        outcome = "unchanged"

    async def webhook(session: Any, *, engine: str, engine_agent_ref: str) -> _Webhook:
        return _Webhook()

    async def actions(*, tenant_id: UUID, engine: str, engine_agent_ref: str) -> str:
        return "clean"

    monkeypatch.setattr(healer, "check_agent_settings", settings)
    monkeypatch.setattr(healer, "ensure_agent_webhook", webhook)
    monkeypatch.setattr(healer, "check_agent_actions", actions)

    outcome = await healer.repair_agent_plumbing(tenant_id, agent_id)

    assert seen == [line_ref]
    assert outcome == "settings=unchecked webhook=unchanged actions=clean"


# --- 6. the agent's confirmed answer ---------------------------------------------------------


def test_the_worst_holder_verdict_wins_and_nothing_unread_is_rounded_up() -> None:
    worst = publishing.worst_holder_state
    assert worst([]) is None
    assert worst(["applied", "applied"]) == "applied"
    assert worst(["applied", "unverified"]) == "unverified"
    assert worst(["unreadable", "applied", "not_applied"]) == "not_applied"
    assert worst(["not_applied", "truthful_answer_missing"]) == "truthful_answer_missing"
    assert worst(["applied", "a_word_nobody_wrote"]) == "unverified"


@pytest.mark.usefixtures("no_own_engine_agent")
async def test_the_agents_confirmed_answer_is_the_worst_over_its_live_lines() -> None:
    _fresh_engine()
    tenant_id, agent_id, _ = await _live_agent()

    async with tenant_session(tenant_id) as session:
        nothing = await publishing.holders_verification(
            session, tenant_id=tenant_id, agent_id=agent_id
        )
    assert nothing is None, "an agent nothing carries was given a verdict"

    first = await put_line_live(tenant_id=tenant_id, line_id=await _line(tenant_id, agent_id))
    second = await put_line_live(tenant_id=tenant_id, line_id=await _line(tenant_id, agent_id))
    async with tenant_session(tenant_id) as session:
        unread = await publishing.holders_verification(
            session, tenant_id=tenant_id, agent_id=agent_id
        )
        assert unread is not None
        assert (unread.state, unread.confirmed, unread.verified_at) == ("unverified", False, None)
        await session.execute(
            text(
                "UPDATE engine_agent_routes SET drift_state = 'applied', "
                "drift_checked_at = now() WHERE engine_agent_ref = ANY(:refs)"
            ),
            {"refs": [first, second]},
        )
        confirmed = await publishing.holders_verification(
            session, tenant_id=tenant_id, agent_id=agent_id
        )
        assert confirmed is not None
        assert (confirmed.state, confirmed.confirmed) == ("applied", True)
        assert confirmed.verified_at is not None
        await session.execute(
            text(
                "UPDATE engine_agent_routes SET drift_state = 'not_applied' "
                "WHERE engine_agent_ref = :ref"
            ),
            {"ref": second},
        )
        mismatch = await publishing.holders_verification(
            session, tenant_id=tenant_id, agent_id=agent_id
        )
    assert mismatch is not None
    assert (mismatch.state, mismatch.confirmed, mismatch.verified_at) == (
        "not_applied",
        False,
        None,
    )
    assert "not running what we sent" in mismatch.headline


async def test_the_pending_read_carries_the_holders_answer() -> None:
    _fresh_engine()
    tenant_id, agent_id, token = await _tenant()
    await _write_script(tenant_id, agent_id)

    state = await publishing.pending_state_for(tenant_id=tenant_id, agent_id=agent_id)
    assert state.holders_verification is None

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        response = await http.get(
            f"/v1/agents/{agent_id}/pending", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 200, response.text
    assert response.json()["holders_verification"] is None


@pytest.mark.usefixtures("no_own_engine_agent")
async def test_getting_a_draft_ready_with_the_setting_off_creates_no_engine_agent() -> None:
    # "Ready, not taking calls" on a new draft is a first publish; with the setting off it
    # must not take one of the client's workspace slots.
    engine = _fresh_engine()
    tenant_id, agent_id, _ = await _tenant()
    await _write_script(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await lifecycle.prepare_agent(session, tenant_id=tenant_id, agent_id=agent_id)

    status, ref = await _agent_row(tenant_id, agent_id)
    assert status == "paused"
    assert ref is None, "the draft was given an engine agent of its own"
    assert engine._agents == {}
    assert await _own_routes(tenant_id, agent_id) == 0


@pytest.mark.usefixtures("no_own_engine_agent")
async def test_getting_a_draft_with_nothing_to_say_ready_is_still_refused() -> None:
    _fresh_engine()
    tenant_id, _, token = await _tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(text("DELETE FROM business_profiles"))
    async with _client(_app()) as http:
        created = await http.post(
            "/v1/agents",
            json={"name": "Silent", "direction": "inbound"},
            headers={"Authorization": f"Bearer {token}"},
        )
    agent_id = UUID(created.json()["id"])

    code, body = await _move(token, agent_id, "prepare")
    assert code == 422, body
    assert _code(body) == "agent_has_no_script", body
