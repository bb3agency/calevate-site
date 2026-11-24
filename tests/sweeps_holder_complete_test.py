"""The sweeps over `engine_agent_routes` once an agent holds no engine agent of its own (D-1019).

An agent's former ref stays routed until its deletion runs, and a ref-less agent is reached
only through its lines and campaigns. So every sweep first asks which holder a routed vendor
agent belongs to (`agents.reconciliation.route_holder`) and:

1. the webhook sweep never switches off a route a line, campaign or test copy still holds;
2. the drift sweep stamps a retiring ref `not_published` with no round trip and no repair;
3. the settings check never repairs a ref that is not its holder's own;
4. the knowledge sweep never scores a retiring ref, so it raises no `unaccounted` alarm;
5. a campaign's held script is given back to an agent that holds no engine agent.

SHARED DATABASE DISCIPLINE: every organisation is minted here; the engine is the fake.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents import engine_settings
from apps.api.agents.reconciliation import DriftCandidate, route_holder
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine.fake import FakeEngine
from apps.api.inbound.publish import put_line_live
from apps.api.kb.reconciliation import NOT_HELD, KbDriftCandidate, handles_if_no_publish_in_flight
from apps.workers import engine_reconciliation, kb_reconciliation
from apps.workers.engine_webhooks import _retire_if_orphaned
from calevate_shared.engine import AgentConfig, EngineAgentRef
from sqlalchemy import text
from tests.agent_lifecycle_test import _fresh_engine
from tests.campaign_engine_agents_test import _campaign, _live_body
from tests.campaign_engine_agents_test import _live_agent as _calling_agent
from tests.inbound_lines_test import _line, _live_agent

pytestmark = pytest.mark.rls


async def _own_ref(tenant_id: UUID, agent_id: UUID) -> str:
    async with tenant_session(tenant_id) as session:
        ref = (
            await session.execute(
                text("SELECT engine_agent_ref FROM agents WHERE id = :a"), {"a": agent_id}
            )
        ).scalar_one()
    assert isinstance(ref, str)
    return ref


async def _forget_own_ref(tenant_id: UUID, agent_id: UUID) -> None:
    """What D-1019's retirement leaves: the agent holds no ref, its old route still active."""
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = NULL WHERE id = :a"), {"a": agent_id}
        )


async def _sql(tenant_id: UUID, sql: str, **params: Any) -> Any:
    async with tenant_session(tenant_id) as session:
        return (await session.execute(text(sql), params)).first()


async def _kind(tenant_id: UUID, agent_id: UUID, ref: str) -> str | None:
    async with tenant_session(tenant_id) as session:
        holder = await route_holder(session, agent_id=agent_id, engine_agent_ref=ref)
    return None if holder is None else holder.kind


async def test_each_holder_of_a_routed_vendor_agent_is_named() -> None:
    _fresh_engine()
    tenant_id, agent_id, _ = await _live_agent()
    own = await _own_ref(tenant_id, agent_id)
    line_id = await _line(tenant_id, agent_id)
    line_ref = await put_line_live(tenant_id=tenant_id, line_id=line_id)
    campaign_id = await _campaign(tenant_id, agent_id, status="running")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaigns SET engine_agent_ref = 'ag_campaign_x' WHERE id = :c"),
            {"c": campaign_id},
        )
        await session.execute(
            text(
                "INSERT INTO agent_test_copies (id, tenant_id, agent_id, engine_agent_ref, "
                "business_only) VALUES (:id, :t, :a, 'ag_copy_x', true)"
            ),
            {"id": uuid7(), "t": tenant_id, "a": agent_id},
        )
        line_holder = await route_holder(session, agent_id=agent_id, engine_agent_ref=line_ref)
        copy = await route_holder(session, agent_id=agent_id, engine_agent_ref="ag_copy_x")

    assert await _kind(tenant_id, agent_id, own) == "agent"
    assert line_holder is not None and (line_holder.kind, line_holder.holder_id) == (
        "line",
        line_id,
    )
    assert await _kind(tenant_id, agent_id, "ag_campaign_x") == "campaign"
    assert copy is not None and (copy.kind, copy.business_only) == ("test_copy", True)
    assert await _kind(tenant_id, agent_id, "ag_nobody_x") == "retiring"

    await _forget_own_ref(tenant_id, agent_id)
    assert await _kind(tenant_id, agent_id, own) == "retiring"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE inbound_lines SET archived_at = now() WHERE id = :l"), {"l": line_id}
        )
        await session.execute(
            text("UPDATE agents SET deleted_at = now() WHERE id = :a"), {"a": agent_id}
        )
    assert await _kind(tenant_id, agent_id, line_ref) is None, "a deleted agent holds nothing"


async def test_a_route_a_line_or_test_copy_holds_is_never_switched_off_as_orphaned() -> None:
    engine = _fresh_engine()
    tenant_id, agent_id, _ = await _live_agent()
    own = await _own_ref(tenant_id, agent_id)
    line_id = await _line(tenant_id, agent_id)
    line_ref = await put_line_live(tenant_id=tenant_id, line_id=line_id)
    await _forget_own_ref(tenant_id, agent_id)

    assert not await _retire_if_orphaned(tenant_id, engine.name, line_ref), (
        "the route of a live line of a ref-less agent was switched off"
    )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO agent_test_copies (id, tenant_id, agent_id, engine_agent_ref) "
                "VALUES (:id, :t, :a, :r)"
            ),
            {"id": uuid7(), "t": tenant_id, "a": agent_id, "r": own},
        )
    assert not await _retire_if_orphaned(tenant_id, engine.name, own)

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("DELETE FROM agent_test_copies WHERE agent_id = :a"), {"a": agent_id}
        )
        await session.execute(
            text("UPDATE inbound_lines SET archived_at = now() WHERE id = :l"), {"l": line_id}
        )
    assert await _retire_if_orphaned(tenant_id, engine.name, own)
    assert await _retire_if_orphaned(tenant_id, engine.name, line_ref), (
        "an archived line's vendor agent the vendor no longer has kept its route"
    )


async def test_the_drift_sweep_stamps_a_retiring_ref_and_touches_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _fresh_engine()
    tenant_id, agent_id, _ = await _live_agent()
    own = await _own_ref(tenant_id, agent_id)
    await _forget_own_ref(tenant_id, agent_id)
    touched: list[str] = []

    async def spy(**kw: Any) -> None:
        touched.append(str(kw.get("engine_agent_ref")))

    monkeypatch.setattr(engine_reconciliation, "engine_drift_for", spy)
    monkeypatch.setattr(engine_reconciliation, "check_agent_actions", spy)
    monkeypatch.setattr(engine_reconciliation, "check_call_start", spy)
    monkeypatch.setattr(engine_reconciliation, "check_agent_settings", spy)
    candidate = DriftCandidate(
        tenant_id=tenant_id, agent_id=agent_id, engine_agent_ref=own, drift_checked_at=None
    )

    assert await engine_reconciliation._reconcile_one(engine.name, candidate) is None
    assert touched == [], "a retiring vendor agent was read back or repaired"
    row = await _sql(
        tenant_id,
        "SELECT drift_state, drift_checked_at FROM engine_agent_routes WHERE engine_agent_ref = :r",
        r=own,
    )
    assert row is not None and row[0] == "not_published" and row[1] is not None


class _SettingsProbe(FakeEngine):
    def __init__(self) -> None:
        super().__init__()
        self.compared: list[str] = []

    async def settings_drift(self, ref: EngineAgentRef, cfg: AgentConfig) -> list[str]:
        self.compared.append(ref)
        return ["voice"]

    async def repair_settings(
        self, ref: EngineAgentRef, cfg: AgentConfig, drifted: Sequence[str]
    ) -> None:
        raise AssertionError("a ref the agent does not hold was repaired")


async def test_the_settings_check_never_repairs_a_ref_that_is_not_its_holders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fresh_engine()
    tenant_id, agent_id, _ = await _live_agent()
    own = await _own_ref(tenant_id, agent_id)
    await _forget_own_ref(tenant_id, agent_id)
    probe = _SettingsProbe()
    monkeypatch.setattr(engine_settings, "get_engine", lambda: probe)

    checked = await engine_settings.check_agent_settings(
        tenant_id=tenant_id, agent_id=agent_id, engine_agent_ref=own
    )

    assert checked is None
    assert probe.compared == [], "a retiring vendor agent's settings were read"


async def test_the_knowledge_sweep_never_scores_a_retiring_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _fresh_engine()
    tenant_id, agent_id, _ = await _live_agent()
    own = await _own_ref(tenant_id, agent_id)
    await _forget_own_ref(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE engine_agent_routes SET kb_drift_state = 'unaccounted', "
                "kb_drift_detected_at = now() WHERE engine_agent_ref = :r"
            ),
            {"r": own},
        )
        assert (
            await handles_if_no_publish_in_flight(
                session, tenant_id=tenant_id, agent_id=agent_id, engine_agent_ref=own
            )
            == NOT_HELD
        )
    listed: list[str] = []

    async def never_listed(candidate: KbDriftCandidate) -> list[str]:
        listed.append(candidate.engine_agent_ref)
        return ["doc_nobody_approved"]

    monkeypatch.setattr(kb_reconciliation, "engine_list_kb", never_listed)
    candidate = KbDriftCandidate(
        tenant_id=tenant_id, agent_id=agent_id, engine_agent_ref=own, kb_drift_checked_at=None
    )

    assert await kb_reconciliation._observe_one(engine.name, candidate) is None
    assert listed == [], "a retiring vendor agent's knowledge was listed"
    row = await _sql(
        tenant_id,
        "SELECT kb_drift_state, kb_drift_detected_at, kb_drift_checked_at "
        "FROM engine_agent_routes WHERE engine_agent_ref = :r",
        r=own,
    )
    assert row is not None and (row[0], row[1]) == (None, None), "an old alarm stayed"
    assert row[2] is not None, "the retiring route keeps the head of the queue"


async def test_an_agent_with_no_engine_agent_gets_a_held_script_back_at_once() -> None:
    from apps.api.agents.prompts import insert_prompt_version
    from apps.workers.campaign_engine_agents import _restore_held

    _fresh_engine()
    tenant_id, agent_id = await _calling_agent()
    own = await _live_body(tenant_id, agent_id)
    campaign_id = await _campaign(tenant_id, agent_id, status="running")
    async with tenant_session(tenant_id) as session:
        await insert_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="[IDENTITY]\nYou call people about their check-up.\n",
            notes="Campaign: Check-ups",
            created_by=None,
            apply_live=True,
        )
        await session.execute(
            text("UPDATE campaigns SET agent_held_at = now() WHERE id = :c"), {"c": campaign_id}
        )
    await _forget_own_ref(tenant_id, agent_id)

    async with tenant_session(tenant_id) as session:
        # Its running campaign has no engine agent of its own, yet nothing can be dialling
        # through an agent that holds none.
        assert await _restore_held(session, tenant_id=tenant_id) == (1, 0)
    assert await _live_body(tenant_id, agent_id) == own


class _ReconciledError(Exception):
    pass


async def test_a_sound_test_copy_never_lifts_a_silence_another_route_still_earns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ref-less agent whose line's engine agent lost the truthful answer: its test copy
    reading back sound says nothing about the line, so it must not hand the numbers back."""
    from types import SimpleNamespace

    from apps.api.agents import service as agents_service
    from apps.api.agents.reconciliation import TRUTHFUL_ANSWER_MISSING

    engine = _fresh_engine()
    tenant_id, agent_id, _ = await _live_agent()
    line_id = await _line(tenant_id, agent_id)
    line_ref = await put_line_live(tenant_id=tenant_id, line_id=line_id)
    await _forget_own_ref(tenant_id, agent_id)
    copy_ref = f"ag_copy_{uuid7().hex}"
    async with tenant_session(tenant_id) as session:
        await agents_service._record_test_copy(
            session, engine, tenant_id=tenant_id, agent_id=agent_id, ref=copy_ref
        )
        await session.execute(
            text("UPDATE engine_agent_routes SET drift_state = :s WHERE engine_agent_ref = :r"),
            {"s": TRUTHFUL_ANSWER_MISSING, "r": line_ref},
        )

    async def sound(**_: Any) -> Any:
        return SimpleNamespace(state="applied", truthful_answer_applied=True)

    seen: list[bool | None] = []

    async def reconcile(_session: Any, _engine: Any, **kw: Any) -> str:
        seen.append(kw["truthful_answer_applied"])
        raise _ReconciledError

    monkeypatch.setattr(engine_reconciliation, "engine_drift_for", sound)
    monkeypatch.setattr(engine_reconciliation, "reconcile_inbound_truthful_answer", reconcile)
    candidate = DriftCandidate(
        tenant_id=tenant_id, agent_id=agent_id, engine_agent_ref=copy_ref, drift_checked_at=None
    )
    with pytest.raises(_ReconciledError):
        await engine_reconciliation._reconcile_one(engine.name, candidate)
    assert seen == [None], "a sound test copy was allowed to lift the line's silence"

    await _sql(
        tenant_id,
        "UPDATE engine_agent_routes SET drift_state = 'applied' WHERE engine_agent_ref = :r "
        "RETURNING 1",
        r=line_ref,
    )
    with pytest.raises(_ReconciledError):
        await engine_reconciliation._reconcile_one(engine.name, candidate)
    assert seen == [None, True], "with every route sound, the copy's verdict may lift it"
