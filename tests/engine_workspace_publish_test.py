"""Agents and voices in a client's own ThinnestAI workspace (D-693), and Pipecat unchanged.

* A publish creates a NEW vendor agent in the client's own workspace; a tenant with none is
  refused and nothing reaches the vendor.
* An agent made in our developer workspace before D-693 is recreated in the client's
  workspace on its next publish, under a new id: its old route stays live until the commit,
  its knowledge claims go so the D-689 catch-up re-attaches everything, and the old vendor
  agent is deleted only afterwards, by `retire_moved_engine_agent`, never while a call is on it.
* One of our clones is cloned again into the client's workspace from the sealed sample.
* On `ENGINE=pipecat` none of this is reached.
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents import clone_copies
from apps.api.agents import service as agents_service
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine.catalogue import VoiceClone, VoiceCloneSample
from apps.api.engine.fake import FakeEngine
from apps.api.engine.thinnest_workspace import current_workspace
from apps.api.tenancy import engine_workspace as resolver
from apps.workers import engine_workspaces as jobs
from arq import Retry
from calevate_shared.engine import AgentConfig
from calevate_shared.engine_scope import scope_of
from sqlalchemy import text
from tests.hosted_voice_fakes import CatalogueRows, HostingEngine, selected
from tests.thinnest_engine_seams_test import (  # noqa: F401 - pytest fixtures
    _agent,
    _publish,
    _set_columns,
    attested,
    no_webhook,
)
from tests.thinnest_fake_account import FakeAccount
from tests.workspace_support import give_own_workspace, workspace_of

pytestmark = [pytest.mark.rls]


async def _agent_ref(tenant_id: UUID, agent_id: UUID) -> str | None:
    async with tenant_session(tenant_id) as session:
        return (
            await session.execute(
                text("SELECT engine_agent_ref FROM agents WHERE id = :a"), {"a": agent_id}
            )
        ).scalar()


async def _routes(tenant_id: UUID, agent_id: UUID) -> dict[str, bool]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT engine_agent_ref, active FROM engine_agent_routes WHERE agent_id = :a"
                ),
                {"a": agent_id},
            )
        ).all()
    return {str(r[0]): bool(r[1]) for r in rows}


async def _retire_jobs(agent_id: UUID) -> list[dict[str, Any]]:
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT payload FROM outbox_messages WHERE job = 'retire_moved_engine_agent' "
                    "AND payload->>'agent_id' = :a"
                ),
                {"a": str(agent_id)},
            )
        ).scalars()
        return [dict(r) for r in rows]


async def test_a_new_agent_is_created_in_the_clients_own_workspace(
    attested: set[str],  # noqa: F811
    no_webhook: None,  # noqa: F811
    hosted_rows: CatalogueRows,
) -> None:
    tenant_id, agent_id = await _agent()
    voice = await hosted_rows.add("engine", vendor_id=f"asha-{uuid.uuid4().hex[:6]}")
    await _set_columns(tenant_id, agent_id, voice, "prana-voice")
    with selected(HostingEngine()) as engine:
        ref = await _publish(tenant_id, agent_id)
    assert isinstance(engine, HostingEngine)
    assert scope_of(ref) == workspace_of(UUID(str(tenant_id)))
    assert engine.sent[-1].engine_workspace == workspace_of(UUID(str(tenant_id)))
    assert await _retire_jobs(UUID(str(agent_id))) == []


async def test_no_agent_is_published_for_a_tenant_without_its_own_workspace(
    attested: set[str],  # noqa: F811
    no_webhook: None,  # noqa: F811
    hosted_rows: CatalogueRows,
) -> None:
    tenant_id, agent_id = await _agent()
    voice = await hosted_rows.add("engine", vendor_id=f"asha-{uuid.uuid4().hex[:6]}")
    await _set_columns(tenant_id, agent_id, voice, "prana-voice")
    await give_own_workspace(UUID(str(tenant_id)), status="plan_limit")
    with selected(HostingEngine()) as engine, pytest.raises(ProblemError) as refused:
        await _publish(tenant_id, agent_id)
    assert refused.value.code == "engine_workspace_not_provisioned"
    assert isinstance(engine, HostingEngine) and engine.sent == []


async def test_a_legacy_agent_is_recreated_in_the_clients_workspace_and_retired_after(
    attested: set[str],  # noqa: F811
    no_webhook: None,  # noqa: F811
    hosted_rows: CatalogueRows,
) -> None:
    tenant_id, agent_id = await _agent()
    voice = await hosted_rows.add("engine", vendor_id=f"asha-{uuid.uuid4().hex[:6]}")
    await _set_columns(tenant_id, agent_id, voice, "prana-voice")
    tenant, agent = UUID(str(tenant_id)), UUID(str(agent_id))
    legacy = f"fakeagent_legacy_{uuid.uuid4().hex[:8]}"
    engine = HostingEngine()
    legacy_cfg = AgentConfig(
        tenant_id=str(tenant),
        agent_id=str(agent),
        name="old",
        direction="inbound",
        system_prompt="x",
        opening_line="Hello",
    )
    engine._agents[legacy] = legacy_cfg
    async with tenant_session(tenant) as session:
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = :r, engine = 'thinnest' WHERE id = :a"),
            {"r": legacy, "a": agent},
        )
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('thinnest', :r, :t, :a, true, now(), "
                "now())"
            ),
            {"r": legacy, "t": tenant, "a": agent},
        )

    with selected(engine):
        ref = await _publish(tenant, agent)

    assert ref != legacy and scope_of(ref) == workspace_of(tenant)
    assert await _agent_ref(tenant, agent) == ref
    routes = await _routes(tenant, agent)
    assert routes[ref] is True and routes[legacy] is True, "the old route lives until retired"
    assert legacy in engine._agents, "the old vendor agent is not deleted inside the publish"
    [job] = await _retire_jobs(agent)
    assert job == {"tenant_id": str(tenant), "agent_id": str(agent), "old_ref": legacy}

    # A second publish updates the agent where it now lives: no second move.
    with selected(engine):
        assert await _publish(tenant, agent) == ref
    assert len(await _retire_jobs(agent)) == 1


async def test_the_old_agent_waits_for_its_live_call_then_is_deleted(
    account: FakeAccount, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.engine_workspace_test import _tenant

    tenant_id = await _tenant()
    old = f"ag_old_{uuid.uuid4().hex[:10]}"
    async with tenant_session(tenant_id) as session:
        agent_id = (
            await session.execute(
                text("SELECT id FROM agents WHERE tenant_id = :t LIMIT 1"), {"t": tenant_id}
            )
        ).scalar_one()
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('thinnest', :r, :t, :a, true, "
                "now(), now()) ON CONFLICT (engine, engine_agent_ref) DO UPDATE SET "
                "tenant_id = EXCLUDED.tenant_id, agent_id = EXCLUDED.agent_id, active = true"
            ),
            {"t": tenant_id, "a": agent_id, "r": old},
        )

    async def _no_actions(*, agent_id: Any, ref: Any) -> int:
        return 0

    monkeypatch.setattr(jobs, "retire_in_call_actions", _no_actions)
    payload = {"tenant_id": str(tenant_id), "agent_id": str(agent_id), "old_ref": old}
    account.ws(None).live_calls[old] = 1
    with pytest.raises(Retry):
        await jobs.retire_moved_engine_agent({"job_try": 1}, payload)
    assert not [s for s in account.sent if s.method == "DELETE" and s.path == f"/agents/{old}"]

    account.ws(None).live_calls[old] = 0
    assert await jobs.retire_moved_engine_agent({"job_try": 2}, payload) == "retired"
    [delete] = [s for s in account.sent if s.method == "DELETE" and s.path == f"/agents/{old}"]
    assert delete.workspace is None
    async with tenant_session(tenant_id) as session:
        active = (
            await session.execute(
                text("SELECT active FROM engine_agent_routes WHERE engine_agent_ref = :r"),
                {"r": old},
            )
        ).scalar_one()
    assert active is False


# --- clones -----------------------------------------------------------------------------


class _CloningEngine(HostingEngine):
    """Records the workspace each clone was made in, and can refuse at the vendor's limit."""

    def __init__(self) -> None:
        super().__init__()
        self.made_in: list[str | None] = []
        self.where: dict[str, str | None] = {}
        self.at_limit = False

    async def create_voice_clone(self, sample: VoiceCloneSample) -> VoiceClone:
        if self.at_limit:
            raise ProblemError.business_rule("voice_clone_limit_reached", "full")
        clone = await super().create_voice_clone(sample)
        self.made_in.append(current_workspace())
        self.where[clone.voice_id] = current_workspace()
        return clone

    async def list_voice_clones(self) -> list[VoiceClone]:
        here = current_workspace()
        return [c for c in self.clones.values() if self.where.get(c.voice_id) == here]


async def test_our_clone_is_cloned_again_into_a_clients_workspace_from_the_kept_sample(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.workers.storage as storage

    stored: dict[str, bytes] = {}

    async def _store(*, key: str, data: bytes) -> str:
        stored[key] = data
        return key

    async def _read(key: str) -> bytes | None:
        return stored.get(key)

    monkeypatch.setattr(storage, "store_voice_clone_sample", _store)
    monkeypatch.setattr(storage, "read_voice_clone_sample", _read)
    voice_id = f"engine:clone-{uuid.uuid4().hex[:8]}"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO platform_voice_catalog (voice_id, engine_voice_id, label, tts_model, "
                "provider, synced_at, engine_clone_id, is_custom) VALUES (:v, 'dev-voice', "
                "'Founder voice', 'engine', 'thinnest', now(), 'vc_dev', true)"
            ),
            {"v": voice_id},
        )
        key = await clone_copies.keep_clone_sample(
            session,
            voice_id=voice_id,
            filename="me.mp3",
            content_type="audio/mpeg",
            language="te",
            data=b"RECORDING-OF-A-VOICE",
        )
    assert b"RECORDING-OF-A-VOICE" not in stored[key], "kept sealed, never in clear"
    assert json.loads(stored[key])["content_type"] == "audio/mpeg"

    from tests.engine_workspace_test import _tenant

    tenant_id = await _tenant()
    workspace = await give_own_workspace(tenant_id)
    engine = _CloningEngine()
    async with tenant_session(tenant_id) as session:
        copy = await clone_copies.workspace_voice_id(
            session, engine, tenant_id=tenant_id, voice_id=voice_id, workspace=workspace
        )
        again = await clone_copies.workspace_voice_id(
            session, engine, tenant_id=tenant_id, voice_id=voice_id, workspace=workspace
        )
    assert copy is not None and copy == again
    assert engine.made_in == [workspace], "made once, in the client's own workspace"
    [made] = engine.clones.values()
    assert made.label == clone_copies.copy_name("Founder voice", voice_id)
    assert len(made.label) <= clone_copies.NAME_MAX

    other_tenant = await _tenant()
    other_ws = await give_own_workspace(other_tenant)
    engine.at_limit = True
    async with tenant_session(other_tenant) as session:
        with pytest.raises(ProblemError) as refused:
            await clone_copies.workspace_voice_id(
                session, engine, tenant_id=other_tenant, voice_id=voice_id, workspace=other_ws
            )
    assert refused.value.code == "voice_clone_workspace_limit"


async def test_a_voice_that_is_not_our_clone_is_the_same_id_everywhere() -> None:
    from tests.engine_workspace_test import _tenant

    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        assert (
            await clone_copies.workspace_voice_id(
                session,
                HostingEngine(),
                tenant_id=tenant_id,
                voice_id="engine:not-in-catalogue",
                workspace="org_x",
            )
            is None
        )


# --- Pipecat stays as it was --------------------------------------------------------------


class _PipecatNamed(FakeEngine):
    name = "pipecat"


async def test_pipecat_never_reads_a_workspace_and_its_config_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`ENGINE=pipecat` is byte-for-byte unchanged: no resolver read, no workspace on the
    config, the same unscoped refs, the same serialised config."""

    async def _never(*_a: Any, **_k: Any) -> str:
        raise AssertionError("the workspace resolver is never asked on pipecat")

    monkeypatch.setattr(agents_service, "resolve_workspace", _never)
    cfg = AgentConfig(
        tenant_id=str(uuid.uuid4()),
        agent_id=str(uuid.uuid4()),
        name="Reception",
        direction="inbound",
        system_prompt="x",
        opening_line="Hello",
    )
    engine = _PipecatNamed()
    async with tenant_session(uuid.uuid4()) as session:
        out = await agents_service._in_client_workspace(
            session, engine, tenant_id=uuid.uuid4(), agent={}, config=cfg
        )
    assert out is cfg and out.engine_workspace is None
    assert "engine_workspace" not in cfg.model_dump()
    assert "engine_workspace" not in cfg.model_dump_json()
    with_workspace = cfg.model_copy(update={"engine_workspace": "org_x"})
    assert with_workspace.model_dump() == cfg.model_dump(), "excluded from every dump"
    assert "@" not in await engine.create_agent(cfg)
    assert resolver.engine_has_workspaces("pipecat") is False
    assert agents_service._moves_workspace("pipecat:t:a", cfg) is False


async def test_deleting_our_clone_deletes_its_copies_in_client_workspaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.tenancy.engine_workspace as resolver_module
    from apps.api.db.base import uuid7
    from tests.engine_workspace_test import _tenant

    tenant_id = await _tenant()
    workspace = await give_own_workspace(tenant_id)
    voice_id = f"engine:clone-{uuid.uuid4().hex[:8]}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO engine_voice_clone_copies (id, tenant_id, voice_id, workspace_id, "
                "vendor_voice_id, vendor_clone_id, created_at, updated_at) VALUES (:id, :t, :v, "
                ":ws, 'vv', 'vc_copy', now(), now())"
            ),
            {"id": uuid7(), "t": tenant_id, "v": voice_id, "ws": workspace},
        )

    async def _only(**_kw: Any) -> list[resolver.WorkspaceRow]:
        return [resolver.WorkspaceRow(tenant_id=tenant_id, status="active", workspace_id=workspace)]

    monkeypatch.setattr(resolver_module, "active_workspaces", _only)
    deleted_in: list[tuple[str | None, str]] = []

    class _Deleting(HostingEngine):
        async def delete_voice_clone(self, clone_id: str) -> int:
            deleted_in.append((current_workspace(), clone_id))
            return 0

    assert await clone_copies.forget_clone(_Deleting(), voice_id=voice_id, sample_key=None) == 1
    assert deleted_in == [(workspace, "vc_copy")]
    async with tenant_session(tenant_id) as session:
        left = (
            await session.execute(
                text("SELECT count(*) FROM engine_voice_clone_copies WHERE voice_id = :v"),
                {"v": voice_id},
            )
        ).scalar_one()
    assert left == 0
