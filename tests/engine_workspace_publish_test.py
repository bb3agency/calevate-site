"""Agents and voices in a client's own ThinnestAI workspace (D-693).

* A publish creates a NEW vendor agent in the client's own workspace; a tenant with none is
  refused and nothing reaches the vendor.
* An agent made in our developer workspace before D-693 is recreated in the client's
  workspace on its next publish, under a new id: its old route stays live until the commit,
  its knowledge claims go so the D-689 catch-up re-attaches everything, and the old vendor
  agent is deleted only afterwards, by `retire_moved_engine_agent`, never while a call is on it.
* A client agent on one of our clones speaks the shared clone its workspace lists (D-797),
  and is refused when that workspace does not list it under our id.
* On an engine without workspaces none of this is reached.
"""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents import service as agents_service
from apps.api.agents import shared_clones
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine.catalogue import HostedVoice
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
        # A number of the client's own on the agent: no test copy is kept (D-859, option A).
        await session.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, agent_id, e164, series, provider, "
                "direction, dlt_status, engine_owned, created_at, updated_at) VALUES "
                "(:id, :t, :a, :e, 'standard', 'thinnest', 'both', 'pending', true, now(), now())"
            ),
            {
                "id": uuid.uuid4(),
                "t": tenant,
                "a": agent,
                "e": f"+9180{uuid.uuid4().int % 10**8:08d}",
            },
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


async def test_a_move_that_fails_after_the_create_deletes_the_new_vendor_agent(
    attested: set[str],  # noqa: F811
    no_webhook: None,  # noqa: F811
    hosted_rows: CatalogueRows,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A step after the engine seams failing (here the running arms' republish) rolls back
    every row naming the agent the move created, so that agent is deleted, and the legacy
    one keeps answering with no retirement owed."""
    tenant_id, agent_id = await _agent()
    voice = await hosted_rows.add("engine", vendor_id=f"asha-{uuid.uuid4().hex[:6]}")
    await _set_columns(tenant_id, agent_id, voice, "prana-voice")
    tenant, agent = UUID(str(tenant_id)), UUID(str(agent_id))
    legacy = f"fakeagent_legacy_{uuid.uuid4().hex[:8]}"
    engine = HostingEngine()
    engine._agents[legacy] = AgentConfig(
        tenant_id=str(tenant),
        agent_id=str(agent),
        name="old",
        direction="inbound",
        system_prompt="x",
        opening_line="Hello",
    )
    async with tenant_session(tenant) as session:
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = :r, engine = 'thinnest' WHERE id = :a"),
            {"r": legacy, "a": agent},
        )

    async def _arms_refused(*_: Any, **__: Any) -> int:
        raise ProblemError(
            kind="dependency", code="engine_publish_not_applied", title="x", detail="x"
        )

    monkeypatch.setattr(agents_service, "republish_running_variants", _arms_refused)
    with selected(engine), pytest.raises(ProblemError) as refused:
        await _publish(tenant, agent)

    assert refused.value.code == "engine_publish_not_applied"
    created = [ref for ref in engine._agents if ref != legacy]
    assert engine.deleted == created and len(created) == 1, (
        "the agent the move created was left standing"
    )
    assert await _agent_ref(tenant, agent) == legacy
    assert await _retire_jobs(agent) == []


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


# --- clones (D-797) ---------------------------------------------------------------------
# Inside a customer workspace `GET /voices` lists each of our developer clones with
# `sharedFromDeveloper: true` (snapshots/2026-10-15/pages/api-reference/voices/
# list-voices.md:495-500, :579-589), and its agents speak it directly.


def _shared(voice_id: str, label: str = "Brand voice (from your developer)") -> HostedVoice:
    return HostedVoice(
        voice_id=voice_id,
        label=label,
        source="engine",
        is_custom=True,
        shared_from_developer=True,
        language="en-IN",
        band="studio",
    )


async def _copies(tenant_id: UUID) -> int:
    async with tenant_session(tenant_id) as session:
        return int(
            (
                await session.execute(
                    text("SELECT count(*) FROM engine_voice_clone_copies WHERE tenant_id = :t"),
                    {"t": tenant_id},
                )
            ).scalar_one()
        )


async def test_a_client_agent_on_our_clone_is_published_on_the_shared_clone(
    attested: set[str],  # noqa: F811
    no_webhook: None,  # noqa: F811
    hosted_rows: CatalogueRows,
) -> None:
    tenant_id, agent_id = await _agent()
    vendor = f"clone-{uuid.uuid4().hex[:8]}"
    voice = await hosted_rows.add("engine", vendor_id=vendor, clone_id=f"vc_{vendor}")
    await _set_columns(tenant_id, agent_id, voice, "prana-voice")
    workspace = workspace_of(UUID(str(tenant_id)))
    engine = HostingEngine()
    engine.hosted_in[workspace] = [_shared("anika-standard", "Anika"), _shared(vendor)]
    with selected(engine):
        ref = await _publish(tenant_id, agent_id)
    sent = engine.sent[-1]
    assert (sent.engine_workspace, sent.engine_voice_id) == (workspace, vendor)
    assert scope_of(ref) == workspace
    assert engine.clones == {}, "nothing is cloned in the client's workspace"
    assert await _copies(UUID(str(tenant_id))) == 0


async def test_a_client_agent_on_our_clone_is_refused_when_its_workspace_does_not_share_it(
    attested: set[str],  # noqa: F811
    no_webhook: None,  # noqa: F811
    hosted_rows: CatalogueRows,
) -> None:
    """Under another id the entry may or may not be our clone: no documented field links
    the two, so it is refused rather than guessed at, and nothing reaches the vendor."""
    tenant_id, agent_id = await _agent()
    vendor = f"clone-{uuid.uuid4().hex[:8]}"
    voice = await hosted_rows.add("engine", vendor_id=vendor, clone_id=f"vc_{vendor}")
    await _set_columns(tenant_id, agent_id, voice, "prana-voice")
    engine = HostingEngine()
    engine.hosted_in[workspace_of(UUID(str(tenant_id)))] = [_shared(f"other-{vendor}")]
    with selected(engine), pytest.raises(ProblemError) as refused:
        await _publish(tenant_id, agent_id)
    assert refused.value.code == shared_clones.SHARED_CLONE_NOT_LISTED
    assert engine.sent == [] and engine.clones == {}
    assert await _copies(UUID(str(tenant_id))) == 0


def _listed_shared(vendor: str) -> list[HostedVoice]:
    return [_shared(vendor)]


def _listed_nothing(vendor: str) -> list[HostedVoice]:
    # A plan below Pro lists no Studio voice, shared clones included (list-voices.md:450-453).
    return []


def _listed_other_id(vendor: str) -> list[HostedVoice]:
    return [_shared(f"x-{vendor}")]


def _listed_not_shared(vendor: str) -> list[HostedVoice]:
    return [_shared(vendor).model_copy(update={"shared_from_developer": False})]


@pytest.mark.parametrize(
    ("listed", "resolves"),
    [
        (_listed_shared, True),
        (_listed_nothing, False),
        (_listed_other_id, False),
        (_listed_not_shared, False),
    ],
)
async def test_the_shared_clone_is_resolved_from_the_client_workspaces_own_listing(
    hosted_rows: CatalogueRows,
    listed: Any,
    resolves: bool,
) -> None:
    vendor = f"clone-{uuid.uuid4().hex[:8]}"
    voice = await hosted_rows.add("engine", vendor_id=vendor, clone_id=f"vc_{vendor}")
    # Our developer workspace lists it as ours; only the client workspace's listing counts.
    engine = HostingEngine(hosted=[_shared(vendor)])
    engine.hosted_in["org_shared-test"] = listed(vendor)
    async with tenant_session(uuid.uuid4()) as session:
        if resolves:
            held = await shared_clones.client_voice_id(
                session, engine, voice_id=voice, workspace="org_shared-test"
            )
            assert held == vendor
            return
        with pytest.raises(ProblemError) as refused:
            await shared_clones.client_voice_id(
                session, engine, voice_id=voice, workspace="org_shared-test"
            )
    assert refused.value.code == shared_clones.SHARED_CLONE_NOT_LISTED


async def test_a_voice_that_is_not_our_clone_is_the_same_id_everywhere(
    hosted_rows: CatalogueRows,
) -> None:
    voice = await hosted_rows.add("engine", vendor_id=f"asha-{uuid.uuid4().hex[:6]}")
    async with tenant_session(uuid.uuid4()) as session:
        for catalogue_id in (voice, "engine:not-in-catalogue"):
            assert (
                await shared_clones.client_voice_id(
                    session, HostingEngine(), voice_id=catalogue_id, workspace="org_x"
                )
                is None
            )


class _SettingsEngine(HostingEngine):
    """Holds each agent's voice and call cap as the vendor would, and compares and repairs
    those two. A voice left unset is not compared, as `thinnest._settings_drift` skips it."""

    def __init__(self) -> None:
        super().__init__()
        self.held: dict[str, str | None] = {}
        self.cap: dict[str, int] = {}

    async def settings_drift(self, ref: str, cfg: AgentConfig) -> list[str]:
        drifted = []
        if cfg.engine_voice_id is not None and self.held.get(ref) != cfg.engine_voice_id:
            drifted.append("voice")
        if self.cap.get(ref, cfg.max_call_duration_s) != cfg.max_call_duration_s:
            drifted.append("max_call_seconds")
        return drifted

    async def repair_settings(self, ref: str, cfg: AgentConfig, drifted: Any) -> None:
        if "voice" in drifted:
            self.held[ref] = cfg.engine_voice_id
        if "max_call_seconds" in drifted:
            self.cap[ref] = cfg.max_call_duration_s


async def test_the_drift_sweep_moves_an_agent_off_its_old_copy_and_then_holds_still(
    hosted_rows: CatalogueRows,
) -> None:
    from apps.api.agents.engine_settings import check_agent_settings

    tenant_id, agent_id = await _agent()
    tenant, agent = UUID(str(tenant_id)), UUID(str(agent_id))
    vendor = f"clone-{uuid.uuid4().hex[:8]}"
    voice = await hosted_rows.add("engine", vendor_id=vendor, clone_id=f"vc_{vendor}")
    await _set_columns(tenant_id, agent_id, voice, "prana-voice")
    workspace = workspace_of(tenant)
    ref = f"ag_1@{workspace}"
    engine = _SettingsEngine()
    engine.held[ref] = "copy-made-before-d797"
    engine.hosted_in[workspace] = [_shared(vendor)]
    with selected(engine):
        first = await check_agent_settings(tenant_id=tenant, agent_id=agent, engine_agent_ref=ref)
        second = await check_agent_settings(tenant_id=tenant, agent_id=agent, engine_agent_ref=ref)
        # The workspace stops listing it (the clone was deleted, or the plan lists none): the
        # voice is never "repaired" onto an id that workspace does not hold, and every other
        # setting is still compared and put back.
        engine.hosted_in[workspace] = []
        engine.held[ref] = "standard-voice"
        engine.cap[ref] = 7200
        unlisted = await check_agent_settings(
            tenant_id=tenant, agent_id=agent, engine_agent_ref=ref
        )
    assert first is not None and (first.drifted, first.repaired) == (("voice",), True)
    assert second is not None and second.drifted == ()
    assert unlisted is not None
    assert (unlisted.drifted, unlisted.repaired) == (("max_call_seconds",), True)
    assert engine.held[ref] == "standard-voice"
    assert engine.cap[ref] != 7200


# --- an engine without workspaces is unchanged -------------------------------------------


async def test_an_engine_without_workspaces_never_reads_one_and_its_config_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An engine without workspaces is byte-for-byte unchanged: no resolver read, no
    workspace on the config, the same unscoped refs, the same serialised config."""

    async def _never(*_a: Any, **_k: Any) -> str:
        raise AssertionError("the workspace resolver is never asked on this engine")

    monkeypatch.setattr(agents_service, "resolve_workspace", _never)
    cfg = AgentConfig(
        tenant_id=str(uuid.uuid4()),
        agent_id=str(uuid.uuid4()),
        name="Reception",
        direction="inbound",
        system_prompt="x",
        opening_line="Hello",
    )
    engine = FakeEngine()
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
    assert resolver.engine_has_workspaces("fake") is False
    assert agents_service._moves_workspace("fake:t:a", cfg) is False


async def test_deleting_our_clone_deletes_its_old_copies_and_counts_their_agents(
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
            return 3

    assert await shared_clones.forget_clone(_Deleting(), voice_id=voice_id, sample_key=None) == 3
    assert deleted_in == [(workspace, "vc_copy")]
    assert await _copies(tenant_id) == 0
