"""The dial-path seams of D-693..D-701 the flow tests leave alone: every way the healer's
line hold can end (gone, not answering, already silent, forwarded, unsupported, refused
on a republish, nothing to lift), the developer-workspace retirement on closure, numbers
re-pointed at a recreated agent, an experiment arm moved out of our workspace, and the
unregistered calling number."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents import service as agents_service
from apps.api.campaigns import engine_numbers
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from calevate_shared.engine import AgentConfig
from calevate_shared.engine_scope import scope_of
from sqlalchemy import text
from tests.healer_flow_test import _published, _reason
from tests.hosted_voice_fakes import CatalogueRows, HostingEngine, selected
from tests.outbound_registration_gate_test import _bind_number, _tenant_agent
from tests.thinnest_engine_seams_test import (  # noqa: F401 - pytest fixtures
    _agent,
    _set_columns,
    attested,
    no_webhook,
)
from tests.workspace_support import workspace_of

pytestmark = [pytest.mark.rls]


@dataclass
class _Caps:
    records_audio: bool = True
    script_override: bool = False

    def has(self, name: str) -> bool:
        return name == "script_override" and self.script_override


@dataclass
class _PlainEngine:
    """An engine that can neither hand a caller over nor replace an agent's script."""

    capabilities: _Caps = field(default_factory=_Caps)


@dataclass
class _ForwardingEngine:
    capabilities: _Caps = field(default_factory=_Caps)
    forwarded: list[dict[str, Any]] = field(default_factory=list)

    async def forward_line(
        self, ref: str, *, phone_e164: str, line: str, opening_line: str, system_prompt: str
    ) -> None:
        self.forwarded.append(
            {
                "ref": ref,
                "phone": phone_e164,
                "line": line,
                "opening": opening_line,
                "prompt": system_prompt,
            }
        )


@dataclass
class _RefusingEngine:
    capabilities: _Caps = field(default_factory=lambda: _Caps(script_override=True))

    async def override_call_script(self, ref: str, **_: Any) -> None:
        raise RuntimeError("vendor refused the script")


async def _hold(engine: Any, tenant_id: UUID, agent_id: UUID, forward_to: str | None) -> str:
    async with tenant_session(tenant_id) as session:
        return await agents_service.apply_healer_silence(
            session, engine, tenant_id=tenant_id, agent_id=agent_id, forward_to=forward_to
        )


async def test_a_line_is_forwarded_with_both_disclosures_and_the_truthful_answers() -> None:
    tenant_id, agent_id, _ = await _published("fwd")
    engine = _ForwardingEngine()
    assert await _hold(engine, tenant_id, agent_id, "+919000000071") == "forwarded"
    [sent] = engine.forwarded
    assert sent["phone"] == "+919000000071"
    assert sent["line"] == agents_service.HEALER_FORWARD_LINE
    assert sent["opening"].endswith(agents_service.HEALER_FORWARD_LINE)
    assert agents_service.truthful_answer_directive(call_is_recorded=True) in sent["prompt"]
    assert await _reason(tenant_id, agent_id) == agents_service.INBOUND_SILENCE_HEALER


async def test_an_engine_that_can_do_neither_holds_nothing() -> None:
    tenant_id, agent_id, _ = await _published("plain")
    assert await _hold(_PlainEngine(), tenant_id, agent_id, "+919000000071") == "unsupported"
    assert await _reason(tenant_id, agent_id) is None, "nothing is stamped that was not held"


async def test_a_line_that_is_gone_not_answering_or_already_silent_is_left_alone() -> None:
    tenant_id, agent_id, _ = await _published("left")
    engine = _ForwardingEngine()
    assert await _hold(engine, tenant_id, uuid.uuid4(), "+919000000071") == "gone"

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET direction = 'outbound' WHERE id = :a"), {"a": agent_id}
        )
    assert await _hold(engine, tenant_id, agent_id, "+919000000071") == "not_answering"

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET direction = 'inbound' WHERE id = :a"), {"a": agent_id}
        )
        await agents_service._stamp_inbound_silence(
            session, agent_id=agent_id, reason=agents_service.INBOUND_SILENCE_TRUTHFUL_ANSWER
        )
    assert await _hold(engine, tenant_id, agent_id, "+919000000071") == "held"
    assert engine.forwarded == []
    assert await _reason(tenant_id, agent_id) == agents_service.INBOUND_SILENCE_TRUTHFUL_ANSWER


async def test_lifting_a_line_the_healer_does_not_hold_publishes_nothing() -> None:
    tenant_id, agent_id, _ = await _published("nolift")
    async with tenant_session(tenant_id) as session:
        assert not await agents_service.lift_healer_silence(
            session, tenant_id=tenant_id, agent_id=agent_id
        )


async def test_a_hold_the_vendor_refuses_on_republish_is_cleared_and_alarmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id, _ = await _published("refuse")
    raised: list[str] = []
    monkeypatch.setattr(agents_service, "alert", lambda _kind, code, **_: raised.append(code))
    async with tenant_session(tenant_id) as session:
        await agents_service._stamp_inbound_silence(
            session, agent_id=agent_id, reason=agents_service.INBOUND_SILENCE_HEALER
        )
        await agents_service._reapply_healer_silence(
            session, _RefusingEngine(), tenant_id=tenant_id, agent_id=agent_id
        )
    assert raised == ["healer_line_hold_failed"]
    assert await _reason(tenant_id, agent_id) is None, "the column claims no hold it lost"


# --- workspaces -------------------------------------------------------------------------


async def _route(tenant_id: UUID, agent_id: UUID, ref: str) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('thinnest', :r, :t, :a, true, now(), "
                "now())"
            ),
            {"r": ref, "t": tenant_id, "a": agent_id},
        )


async def _retire_jobs(tenant_id: UUID) -> list[str]:
    async with untenanted_session() as session:
        return [
            str(r)
            for r in (
                await session.execute(
                    text(
                        "SELECT payload->>'old_ref' FROM outbox_messages WHERE job = :j "
                        "AND payload->>'tenant_id' = :t ORDER BY 1"
                    ),
                    {"j": agents_service.RETIRE_MOVED_AGENT_JOB, "t": str(tenant_id)},
                )
            ).scalars()
        ]


@dataclass
class _Named:
    name: str = "thinnest"


async def test_a_closing_account_owes_the_deletion_of_its_developer_workspace_agents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _tenant_agent()
    legacy = f"ag_legacy_{uuid.uuid4().hex[:8]}"
    own = f"ag_own_{uuid.uuid4().hex[:8]}@{workspace_of(tenant_id)}"
    await _route(tenant_id, agent_id, legacy)
    await _route(tenant_id, agent_id, own)
    monkeypatch.setattr(agents_service, "engine_has_workspaces", lambda *_: True)
    monkeypatch.setattr(agents_service, "get_engine", _Named)
    async with tenant_session(tenant_id) as session:
        owed = await agents_service.retire_developer_workspace_agents(session, tenant_id=tenant_id)
    assert owed == 1
    assert await _retire_jobs(tenant_id) == [legacy], "the account's own workspace goes whole"


async def test_numbers_bound_to_a_recreated_agent_are_pointed_at_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _tenant_agent()
    synced: list[UUID] = []

    async def _sync(_session: Any, *, number_id: UUID) -> None:
        synced.append(number_id)

    monkeypatch.setattr(engine_numbers, "sync_number_attachment", _sync)
    await _bind_number(tenant_id, agent_id, dlt_status="registered")
    await _bind_number(tenant_id, agent_id, dlt_status="registered")
    async with tenant_session(tenant_id) as session:
        ids = [
            UUID(str(r))
            for r in (
                await session.execute(
                    text(
                        "SELECT id FROM phone_numbers WHERE agent_id = :a ORDER BY created_at, id"
                    ),
                    {"a": agent_id},
                )
            ).scalars()
        ]
        await session.execute(
            text("UPDATE phone_numbers SET released_at = now() WHERE id = :i"), {"i": ids[1]}
        )
        await agents_service._resync_agent_numbers(session, agent_id=agent_id)
    assert synced == [ids[0]], "a released number is not re-pointed"


async def test_an_experiment_arm_in_our_workspace_is_recreated_in_the_clients(
    attested: set[str],  # noqa: F811
    no_webhook: None,  # noqa: F811
    hosted_rows: CatalogueRows,
) -> None:
    tenant_id, agent_id = await _agent()
    tenant, agent = UUID(str(tenant_id)), UUID(str(agent_id))
    voice = await hosted_rows.add("engine", vendor_id=f"asha-{uuid.uuid4().hex[:6]}")
    await _set_columns(tenant, agent, voice, "prana-voice")
    legacy = f"fakeagent_arm_{uuid.uuid4().hex[:8]}"
    engine = HostingEngine()
    engine._agents[legacy] = AgentConfig(
        tenant_id=str(tenant),
        agent_id=str(agent),
        name="old arm",
        direction="inbound",
        system_prompt="x",
        opening_line="Hello",
    )
    with selected(engine):
        async with tenant_session(tenant) as session:
            ref = await agents_service.publish_variant(
                session,
                tenant_id=tenant,
                agent_id=agent,
                variant_id=uuid7(),
                label="B",
                body="Greet in Telugu, then book a visit.",
                disclosure_line="This is an AI assistant from the clinic.",
                existing_ref=legacy,
            )
    assert ref != legacy
    assert scope_of(ref) == workspace_of(tenant)
    assert legacy in engine._agents, "the old arm is retired after the commit, not inside it"
    assert await _retire_jobs(tenant) == [legacy]


def test_the_forward_prompt_hands_over_and_keeps_the_truthful_answers() -> None:
    prompt = agents_service.healer_forward_prompt(call_is_recorded=False)
    assert "hand the caller to a person" in prompt
    assert agents_service.truthful_answer_directive(call_is_recorded=False) in prompt


async def test_lifting_a_forwarded_hold_clears_the_forward_before_the_agent_is_republished(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Republishing first would leave callers ringing the client's phone while the agent
    is already back."""
    tenant_id, agent_id, _ = await _published("liftfwd")
    order: list[str] = []
    real_publish = agents_service.publish_agent

    async def _clear(_session: Any, *, tenant_id: UUID, agent_id: UUID) -> int:
        order.append("clear_forward")
        return 1

    async def _publish(session: Any, **kwargs: Any) -> Any:
        order.append("publish")
        return await real_publish(session, **kwargs)

    monkeypatch.setattr(engine_numbers, "numbers_can_forward", lambda: True)
    monkeypatch.setattr(engine_numbers, "clear_agent_forwards", _clear)
    monkeypatch.setattr(agents_service, "publish_agent", _publish)
    async with tenant_session(tenant_id) as session:
        await agents_service._stamp_inbound_silence(
            session, agent_id=agent_id, reason=agents_service.INBOUND_SILENCE_HEALER
        )
        assert await agents_service.lift_healer_silence(
            session, tenant_id=tenant_id, agent_id=agent_id
        )
    assert order == ["clear_forward", "publish"]
    assert await _reason(tenant_id, agent_id) is None


async def test_lifting_a_hold_leaves_an_agent_the_owner_switched_off_switched_off() -> None:
    tenant_id, agent_id, _ = await _published("liftoff")
    async with tenant_session(tenant_id) as session:
        await agents_service._stamp_inbound_silence(
            session, agent_id=agent_id, reason=agents_service.INBOUND_SILENCE_HEALER
        )
        # The owner's switch-off while the healer held the line leaves the stamp in place.
        await session.execute(
            text("UPDATE agents SET status = 'paused' WHERE id = :a"), {"a": agent_id}
        )
        assert await agents_service.lift_healer_silence(
            session, tenant_id=tenant_id, agent_id=agent_id
        )
    async with tenant_session(tenant_id) as session:
        status = (
            await session.execute(text("SELECT status FROM agents WHERE id = :a"), {"a": agent_id})
        ).scalar_one()
    assert status == "paused"


async def test_a_paying_clients_studio_voice_never_lands_in_our_developer_workspace() -> None:
    """Without a client workspace on the config the Studio switch is refused before any
    vendor write, so our key is never switched on in the developer workspace for it."""
    tenant_id, agent_id = await _tenant_agent()
    engine = HostingEngine()
    config = AgentConfig(
        tenant_id=str(tenant_id),
        agent_id=str(agent_id),
        name="studio",
        direction="inbound",
        system_prompt="x",
        opening_line="Hello",
    )
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as caught:
            await agents_service._studio_in_client_workspace(
                session,
                engine,
                tenant_id=tenant_id,
                rate_key=agents_service.BYOK_VOICE_RATE_KEY,
                config=config,
                trial=False,
            )
    assert caught.value.code == "engine_workspace_not_provisioned"
    assert engine.installed == [] and engine.enabled == 0
