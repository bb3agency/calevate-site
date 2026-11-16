"""Inbound lines (D-997) under the rest of the platform: what a line's engine agent is held to.

1. A line's numbers are attached on a platform with its own number API (ThinnestAI) when the
   line goes live, and a number moved onto a draft line goes back to its voice agent's own.
2. The drift sweep compares a line's engine agent against the line's config, and repairs its
   settings from it, never from the agent's.
3. A line's engine agent carries the agent's in-call actions less the ones it switched off.
4. Every silence on the voice agent reaches its live lines: the credit stop (also for an agent
   that answers only on its lines), a line put live while the stop holds, and the healer.

SHARED DATABASE DISCIPLINE: every organisation is minted here; the engine is the fake.
"""

from __future__ import annotations

from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from apps.api.actions import service as actions_service
from apps.api.agents import engine_settings
from apps.api.agents import service as agents_service
from apps.api.agents.publishing import engine_drift_for
from apps.api.campaigns import engine_numbers
from apps.api.db.session import tenant_session
from apps.api.engine.fake import FakeEngine
from apps.api.inbound import lines
from apps.api.inbound.publish import put_line_live, route_numbers
from apps.api.reliability import engine_actions
from calevate_shared.engine import AgentConfig, EngineAgentRef
from sqlalchemy import text
from tests.agent_lifecycle_test import _fresh_engine, _number
from tests.inbound_lines_test import _attach, _line, _live_agent

pytestmark = pytest.mark.rls


async def _agent_ref(tenant_id: UUID, agent_id: UUID) -> str:
    async with tenant_session(tenant_id) as session:
        return str(
            (
                await session.execute(
                    text("SELECT engine_agent_ref FROM agents WHERE id = :a"), {"a": agent_id}
                )
            ).scalar_one()
        )


async def test_a_line_put_live_attaches_its_numbers_and_a_draft_gives_them_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fresh_engine()
    attached: list[tuple[str, str | None]] = []

    async def attach(number_ref: str, *, agent: str | None, calling_agent: str | None) -> Any:
        attached.append((number_ref, agent))
        return SimpleNamespace(outcome="unchanged", refusal=None)

    monkeypatch.setattr(engine_numbers, "engine_number_provider", lambda: "thinnest")
    monkeypatch.setattr(engine_numbers, "_attach", attach)
    tenant_id, agent_id, _ = await _live_agent()
    number_id = await _number(tenant_id, agent_id, ref="num_hold_1")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE phone_numbers SET provider = 'thinnest' WHERE id = :n"), {"n": number_id}
        )
    first = await _line(tenant_id, agent_id)
    await _attach(tenant_id, first, number_id)

    line_ref = await put_line_live(tenant_id=tenant_id, line_id=first)
    assert attached[-1] == ("num_hold_1", line_ref)

    draft = await _line(tenant_id, agent_id, script=False)
    await _attach(tenant_id, draft, number_id)
    await route_numbers(tenant_id=tenant_id, line_id=draft)
    assert attached[-1] == ("num_hold_1", await _agent_ref(tenant_id, agent_id)), (
        "a number moved onto a draft line stayed on the other line's engine agent"
    )


async def test_the_drift_sweep_compares_a_line_against_the_lines_own_config() -> None:
    _fresh_engine()
    tenant_id, agent_id, _ = await _live_agent()
    line_id = await _line(tenant_id, agent_id)
    line_ref = await put_line_live(tenant_id=tenant_id, line_id=line_id)

    drift = await engine_drift_for(
        tenant_id=tenant_id, agent_id=agent_id, engine_agent_ref=line_ref
    )

    assert drift.engine_agent_ref == line_ref, "the line's route was scored on the agent's"
    assert drift.state == "applied", drift.detail


class _SettingsEngine(FakeEngine):
    def __init__(self) -> None:
        super().__init__()
        self.compared: list[AgentConfig] = []

    async def settings_drift(self, ref: EngineAgentRef, cfg: AgentConfig) -> list[str]:
        self.compared.append(cfg)
        return []

    async def repair_settings(
        self, ref: EngineAgentRef, cfg: AgentConfig, drifted: Sequence[str]
    ) -> None:
        raise AssertionError("nothing drifted")


async def test_a_lines_settings_are_checked_against_the_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fresh_engine()
    tenant_id, agent_id, _ = await _live_agent()
    line_id = await _line(tenant_id, agent_id)
    line_ref = await put_line_live(tenant_id=tenant_id, line_id=line_id)
    probe = _SettingsEngine()
    monkeypatch.setattr(engine_settings, "get_engine", lambda: probe)

    await engine_settings.check_agent_settings(
        tenant_id=tenant_id, agent_id=agent_id, engine_agent_ref=line_ref
    )

    assert [cfg.holder for cfg in probe.compared] == [str(line_id)]


async def test_a_lines_engine_agent_carries_only_the_actions_it_keeps_on() -> None:
    tenant_id, agent_id, _ = await _live_agent()
    line_id = await _line(tenant_id, agent_id)
    line_ref = f"ag_line_{line_id.hex}"
    async with tenant_session(tenant_id) as session:
        await actions_service.set_actions_enabled(session, agent_id=agent_id, enabled=True)
        for name in ("get_status", "get_price"):
            await actions_service.create_tool(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                kind="custom_api",
                provider=None,
                name=name,
                description="when asked about it",
                trigger="during_call",
                pre_call_message=None,
                credential_id=None,
                params=[],
                config={"method": "GET", "url": "https://api.example.com/o"},
            )
        await lines.set_actions_off(session, line_id, ["get_price"])
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "inbound_line_id, active, created_at, updated_at) VALUES ('thinnest', "
                ":ref, :t, :a, :l, true, now(), now())"
            ),
            {"ref": line_ref, "t": tenant_id, "a": agent_id, "l": line_id},
        )
        on_line = await engine_actions.client_definitions(session, "thinnest", line_ref, agent_id)
        on_agent = await engine_actions.client_definitions(
            session, "thinnest", f"{line_ref}_agent", agent_id
        )

    assert {d.name for d in on_line} == {"get_status"}
    assert {d.name for d in on_agent} == {"get_status", "get_price"}


async def test_the_credit_stop_reaches_live_lines_and_a_line_put_live_keeps_it() -> None:
    engine = _fresh_engine()
    tenant_id, agent_id, _ = await _live_agent()
    line_id = await _line(tenant_id, agent_id)
    line_ref = await put_line_live(tenant_id=tenant_id, line_id=line_id)

    async with tenant_session(tenant_id) as session:
        cut = await agents_service.reconcile_inbound_answering(
            session, engine, tenant_id=tenant_id, exhausted=True
        )
    assert cut.silenced == 1
    assert agents_service.CREDIT_STOP_MESSAGE in engine._agents[line_ref].opening_line

    await put_line_live(tenant_id=tenant_id, line_id=line_id)
    assert agents_service.CREDIT_STOP_MESSAGE in engine._agents[line_ref].opening_line, (
        "putting the line live again undid the credit stop"
    )


async def test_an_agent_answering_only_on_its_lines_is_stopped_on_them_alone() -> None:
    engine = _fresh_engine()
    tenant_id, agent_id, _ = await _live_agent()
    line_id = await _line(tenant_id, agent_id)
    line_ref = await put_line_live(tenant_id=tenant_id, line_id=line_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET direction = 'outbound' WHERE id = :a"), {"a": agent_id}
        )
    own_ref = await _agent_ref(tenant_id, agent_id)
    own_before = engine._agents[own_ref].opening_line

    async with tenant_session(tenant_id) as session:
        cut = await agents_service.reconcile_inbound_answering(
            session, engine, tenant_id=tenant_id, exhausted=True
        )

    assert cut.silenced == 1
    assert agents_service.CREDIT_STOP_MESSAGE in engine._agents[line_ref].opening_line
    assert engine._agents[own_ref].opening_line == own_before, "its outbound agent was paused"


async def test_the_healer_holds_the_agents_live_lines_too() -> None:
    engine = _fresh_engine()
    tenant_id, agent_id, _ = await _live_agent()
    line_id = await _line(tenant_id, agent_id)
    line_ref = await put_line_live(tenant_id=tenant_id, line_id=line_id)

    async with tenant_session(tenant_id) as session:
        held = await agents_service.apply_healer_silence(
            session, engine, tenant_id=tenant_id, agent_id=agent_id, forward_to=None
        )

    assert held == "paused"
    assert agents_service.CREDIT_STOP_MESSAGE in engine._agents[line_ref].opening_line
