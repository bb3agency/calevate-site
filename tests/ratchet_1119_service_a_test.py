"""Refusals and repairs in `agents.service`'s publish paths that no other test drives.

1. A line may adopt its agent's engine agent only while it holds none of its own.
2. `in_client` is only for a paying account's test copy.
3. A client-workspace test copy the vendor no longer holds is made again in that workspace.
4. A line's config is never composed for an archived line.
5. A line test holder in the client's workspace, readied for our developer workspace, is
   made again there, and the old one's deletion is owed with its knowledge claims dropped.
6. A line whose read-back proves the platform did not take it gives back the agent it made.
7. A line put live under a credit stop is held only on an engine that can override a
   call's script, and a refused hold alarms without failing the publish.

SHARED DATABASE DISCIPLINE: every organisation is minted here; the engine is the fake.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents import paid_test_calls
from apps.api.agents import service as agents_service
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from sqlalchemy import text
from tests.agent_lifecycle_test import _fresh_engine
from tests.campaign_engine_agents_test import _live_agent
from tests.inbound_lines_test import _line
from tests.trial_call_placement_test import Line, line  # noqa: F401
from tests.workspace_slots_test import _paid_with_a_number_in

pytestmark = pytest.mark.rls


async def _set_line_ref(tenant_id: UUID, line_id: UUID, ref: str | None) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE inbound_lines SET engine_agent_ref = :r WHERE id = :l"),
            {"r": ref, "l": line_id},
        )


async def _line_ref(tenant_id: UUID, line_id: UUID) -> str | None:
    async with tenant_session(tenant_id) as session:
        value = (
            await session.execute(
                text("SELECT engine_agent_ref FROM inbound_lines WHERE id = :l"), {"l": line_id}
            )
        ).scalar_one()
    return None if value is None else str(value)


# --- 1. adoption --------------------------------------------------------------------------


async def test_a_line_holding_its_own_engine_agent_cannot_adopt_the_agents() -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    line_id = await _line(tenant_id, agent_id)
    await _set_line_ref(tenant_id, line_id, "line_own_ref")

    with pytest.raises(ProblemError) as refused:
        async with tenant_session(tenant_id) as session:
            await agents_service.publish_line(
                session, tenant_id=tenant_id, line_id=line_id, adopt_ref="agents_own_ref"
            )

    assert refused.value.code == "engine_agent_not_adoptable"
    assert await _line_ref(tenant_id, line_id) == "line_own_ref", "nothing was changed"


# --- 2. in_client -------------------------------------------------------------------------


async def test_in_client_is_refused_for_anything_but_a_test_copy() -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ValueError, match="in_client is for a paying account's test copy"):
            await agents_service.publish_agent(
                session, tenant_id=tenant_id, agent_id=agent_id, in_client=True
            )


# --- 3. a vanished client copy ------------------------------------------------------------


async def test_a_client_copy_the_vendor_lost_is_made_again_in_the_clients_workspace(
    line: Line,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _fresh_engine()
    tenant_id, agent_id, _principal, workspace = await _paid_with_a_number_in(line, monkeypatch)
    first = await paid_test_calls.refresh_test_copy(
        tenant_id=tenant_id, agent_id=agent_id, in_client=True
    )
    assert first.endswith(f"@{workspace}")

    async def gone(ref: str, _cfg: Any) -> None:
        # The vendor deleted it (by hand, or idle): it is no longer there to find.
        engine._agents.pop(ref, None)
        raise ProblemError.not_found("Agent")

    monkeypatch.setattr(engine, "update_agent", gone)
    again = await paid_test_calls.refresh_test_copy(
        tenant_id=tenant_id, agent_id=agent_id, in_client=True
    )

    # The fake mints a stable id per holder, so the same handle comes back: that it is held
    # again proves it was created again after the vendor dropped it.
    assert again in engine._agents
    assert again.endswith(f"@{workspace}"), "made again where the call rings from"
    async with tenant_session(tenant_id) as session:
        assert await agents_service.test_copy_ref(session, agent_id) == again


# --- 4. an archived line ------------------------------------------------------------------


async def test_no_config_is_composed_for_an_archived_line() -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    line_id = await _line(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE inbound_lines SET archived_at = now() WHERE id = :l"), {"l": line_id}
        )
        with pytest.raises(ProblemError) as refused:
            await agents_service.line_config(session, tenant_id=tenant_id, line_id=line_id)
    assert refused.value.kind == "not_found"


# --- 5. a test holder moved back to our workspace -----------------------------------------


async def test_a_client_workspace_holder_readied_for_our_workspace_is_made_again_here() -> None:
    engine = _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    line_id = await _line(tenant_id, agent_id)
    old = f"holder_{uuid.uuid4().hex[:8]}@org_{uuid.uuid4().hex[:12]}"
    await _set_line_ref(tenant_id, line_id, old)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO engine_kb_routes (engine, engine_kb_ref, tenant_id, agent_id, "
                "source_id, inbound_line_id) VALUES (:e, :r, :t, :a, :s, :l)"
            ),
            {
                "e": engine.name,
                "r": f"kb_{uuid.uuid4().hex}",
                "t": tenant_id,
                "a": agent_id,
                "s": uuid.uuid4(),
                "l": line_id,
            },
        )

    async with tenant_session(tenant_id) as session:
        ref = await agents_service.publish_line(
            session, tenant_id=tenant_id, line_id=line_id, test=True
        )

    assert ref != old and "@" not in ref, "made again in our developer workspace"
    assert await _line_ref(tenant_id, line_id) == ref
    async with tenant_session(tenant_id) as session:
        owed = (
            await session.execute(
                text(
                    "SELECT count(*) FROM outbox_messages WHERE job = :job "
                    "AND payload->>'old_ref' = :old AND payload->>'agent_id' = :a"
                ),
                {"job": agents_service.RETIRE_MOVED_AGENT_JOB, "old": old, "a": str(agent_id)},
            )
        ).scalar_one()
        claims = (
            await session.execute(
                text("SELECT count(*) FROM engine_kb_routes WHERE inbound_line_id = :l"),
                {"l": line_id},
            )
        ).scalar_one()
    assert owed == 1, "the old holder's deletion is owed"
    assert claims == 0, "its knowledge claims went with it"


# --- 6. a refused read-back ---------------------------------------------------------------


async def test_a_line_the_platform_did_not_take_gives_back_the_agent_it_made(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    line_id = await _line(tenant_id, agent_id)
    before = set(engine._agents)

    async def not_applied(*_a: Any, **_k: Any) -> Any:
        return SimpleNamespace(state="not_applied", detail="the greeting did not match")

    monkeypatch.setattr(agents_service, "verify_publish", not_applied)
    with pytest.raises(ProblemError) as refused:
        async with tenant_session(tenant_id) as session:
            await agents_service.publish_line(session, tenant_id=tenant_id, line_id=line_id)

    assert refused.value.code == "engine_publish_not_applied"
    assert set(engine._agents) == before, "the agent it made was deleted, not left billed"
    assert await _line_ref(tenant_id, line_id) is None


# --- 7. the credit-stop hold --------------------------------------------------------------


async def _silenced(tenant_id: UUID, agent_id: UUID) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agents SET inbound_silenced_at = now(), inbound_silence_reason = :r "
                "WHERE id = :a"
            ),
            {"r": agents_service.INBOUND_SILENCE_CREDITS, "a": agent_id},
        )


async def test_a_line_is_not_held_on_an_engine_that_cannot_override_its_script() -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    await _silenced(tenant_id, agent_id)
    asked: list[str] = []

    async def override(*_a: Any, **_k: Any) -> None:
        asked.append("override")

    cannot = SimpleNamespace(
        capabilities=SimpleNamespace(has=lambda capability: capability != "script_override"),
        override_call_script=override,
    )
    async with tenant_session(tenant_id) as session:
        await agents_service._hold_line_if_silenced(
            session, cannot, tenant_id=tenant_id, agent_id=agent_id, ref="line_ref"
        )
    assert asked == []


async def test_a_refused_hold_alarms_and_does_not_fail_the_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    await _silenced(tenant_id, agent_id)
    alarms: list[tuple[str, dict[str, Any]]] = []

    async def refuse(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("vendor said no")

    monkeypatch.setattr(engine, "override_call_script", refuse)
    monkeypatch.setattr(
        agents_service, "alert", lambda _kind, code, **kw: alarms.append((code, kw))
    )
    async with tenant_session(tenant_id) as session:
        await agents_service._hold_line_if_silenced(
            session, engine, tenant_id=tenant_id, agent_id=agent_id, ref="line_ref"
        )

    assert [code for code, _ in alarms] == ["inbound_line_hold_failed"]
    detail = alarms[0][1]
    assert detail["agent_id"] == str(agent_id) and "RuntimeError" in detail["detail"]
