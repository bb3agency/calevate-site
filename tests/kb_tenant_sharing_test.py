"""A client's knowledge is shared by every one of its agents (D-689).

The founder's decision of 8 Oct 2026: uploaded documents and web pages belong to the CLIENT.
On an engine whose knowledge is per vendor agent (ThinnestAI) that means one copy per agent,
fanned out at publish, kept in step on every new version and withdrawal, caught up for an
agent published later and taken away with an archived one. On Pipecat it means every
agent's T0 block and in-call pack carry the tenant's sources.

The thinnest-shaped engine here is the fake with ThinnestAI's capabilities, driven through
the real publish paths (`agents.service.publish_agent`, `kb.service.publish_source`).
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import uuid
from pathlib import Path
from typing import Any

import pytest
from apps.api.agents import lifecycle
from apps.api.agents.t0_block import (
    T0_HEADER,
    T0_KNOWLEDGE_MARKER,
    facts_without_knowledge,
)
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine.fake import FakeEngine
from apps.api.kb import orphans
from apps.api.kb import service as kb_service
from apps.api.kb.pack import build_pack, read_entries
from calevate_shared.engine import (
    AccountKBListing,
    AccountKBObject,
    AgentConfig,
    EngineAgentRef,
    EngineKBRef,
    KBSourceRef,
)
from sqlalchemy import text
from tests.conftest import FakeS3
from tests.kb_workflow_test import _tenant_with_published_agent
from tests.thinnest_facts_in_knowledge_test import (
    SCRIPT,
    _agent,
    _KbEngine,
    _priced_and_no_webhook,  # noqa: F401 - the autouse fixture the publish path needs
    _publish,
    _selected,
    _write,
)

PRICES = "A consultation costs 500 rupees, payable at reception before the appointment."
PRICES_V2 = "A consultation costs 600 rupees, payable at reception before the appointment."


class _FailingEngine(_KbEngine):
    """ThinnestAI-shaped, with per-ref refusals switched on by the test."""

    def __init__(self) -> None:
        super().__init__()
        #: Vendor agents that refuse every removal, and single documents that refuse theirs.
        self.refuse_detach: set[str] = set()
        self.refuse_detach_handles: set[str] = set()
        self.refuse_attach: set[str] = set()
        self.refuse_title: str | None = None
        self.events: list[tuple[str, str, str]] = []

    async def attach_kb(
        self, ref: EngineAgentRef, source: KBSourceRef, *, agent: AgentConfig | None = None
    ) -> EngineKBRef:
        refused = ref in self.refuse_attach and source.title != "Business facts"
        if refused or source.title == self.refuse_title:
            raise ProblemError(
                kind="dependency", code="engine_rejected", title="no", detail="refused"
            )
        handle = await super().attach_kb(ref, source, agent=agent)
        self.events.append(("attach", ref, source.title))
        return handle

    async def detach_kb(
        self, ref: EngineAgentRef, kb: EngineKBRef, *, agent: AgentConfig | None = None
    ) -> None:
        if ref in self.refuse_detach or kb in self.refuse_detach_handles:
            raise ProblemError(
                kind="dependency", code="engine_rejected", title="no", detail="refused"
            )
        await super().detach_kb(ref, kb, agent=agent)
        self.events.append(("detach", ref, kb))


class _MintingEngine(_FailingEngine):
    """Mints a NEW handle on every attach, as ThinnestAI does (an attach is a create), so a
    re-publish of one source leaves two handles to reconcile. The base fake reuses one handle
    per (agent, source) and so cannot show a copy left behind on its old content."""

    def __init__(self) -> None:
        super().__init__()
        self._held: dict[str, list[tuple[str, KBSourceRef]]] = {}

    def _sync(self, ref: str) -> None:
        self._kb[ref] = [source for _, source in self._held.get(ref, [])]

    async def attach_kb(
        self, ref: EngineAgentRef, source: KBSourceRef, *, agent: AgentConfig | None = None
    ) -> EngineKBRef:
        handle = f"kb_{uuid.uuid4().hex}"
        self._held.setdefault(ref, []).append((handle, source))
        self._sync(ref)
        self.events.append(("attach", ref, source.title))
        return handle

    async def detach_kb(
        self, ref: EngineAgentRef, kb: EngineKBRef, *, agent: AgentConfig | None = None
    ) -> None:
        held = self._held.get(ref, [])
        if (
            ref in self.refuse_detach
            or kb in self.refuse_detach_handles
            or all(handle != kb for handle, _ in held)
        ):
            raise ProblemError(
                kind="dependency", code="engine_rejected", title="no", detail="refused"
            )
        self._held[ref] = [(handle, source) for handle, source in held if handle != kb]
        self._sync(ref)
        self.events.append(("detach", ref, kb))

    async def list_kb(self, ref: EngineAgentRef) -> list[EngineKBRef]:
        return [handle for handle, _ in self._held.get(ref, [])]


async def _more_agents(tenant_id: uuid.UUID, count: int) -> list[uuid.UUID]:
    made: list[uuid.UUID] = []
    for i in range(count):
        async with tenant_session(tenant_id) as session:
            made.append(
                await lifecycle.create_agent(
                    session,
                    tenant_id=tenant_id,
                    name=f"Desk {i}",
                    direction="inbound",
                    language_primary="te-IN",
                )
            )
        await _write(tenant_id, made[-1], SCRIPT)
    return made


async def _client_with_agents(engine: _KbEngine, extra: int = 2) -> tuple[uuid.UUID, list[Any]]:
    """A client with `1 + extra` agents, each published to the thinnest-shaped engine."""
    tenant_id, first = await _agent(SCRIPT)
    agents = [first, *await _more_agents(tenant_id, extra)]
    refs = [await _publish(tenant_id, agent_id, engine) for agent_id in agents]
    return tenant_id, list(zip(agents, refs, strict=True))


async def _publish_text(
    tenant_id: uuid.UUID, engine: FakeEngine, name: str, body: str
) -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        submitted = await kb_service.submit_source(
            session, tenant_id=tenant_id, name=name, body=body, auto_approve=True
        )
    source_id = uuid.UUID(str(submitted["id"]))
    with _selected(engine):
        async with tenant_session(tenant_id) as session:
            await kb_service.publish_source(session, tenant_id=tenant_id, source_id=source_id)
    return source_id


async def _routes(tenant_id: uuid.UUID, source_id: uuid.UUID) -> dict[uuid.UUID, str]:
    async with tenant_session(tenant_id) as session:
        return dict(await kb_service._routes_of_source(session, source_id))


def _titled(engine: _KbEngine, ref: str) -> list[str]:
    return [s.title for s in engine._kb.get(ref, [])]


# --- fan-out --------------------------------------------------------------------------


async def test_a_published_source_reaches_every_agent_of_the_client() -> None:
    engine = _FailingEngine()
    tenant_id, agents = await _client_with_agents(engine)
    source_id = await _publish_text(tenant_id, engine, "Prices", PRICES)

    routes = await _routes(tenant_id, source_id)
    assert set(routes) == {agent_id for agent_id, _ in agents}
    for agent_id, ref in agents:
        assert "Prices" in _titled(engine, ref)
        assert routes[agent_id] in await engine.list_kb(ref)
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT agent_id, is_active FROM kb_sources WHERE id = :s"),
                {"s": source_id},
            )
        ).one()
    assert row == (None, True), "a source names no agent and is live for the client"


async def test_a_new_version_is_attached_everywhere_before_the_old_one_is_withdrawn() -> None:
    engine = _FailingEngine()
    tenant_id, agents = await _client_with_agents(engine)
    v1 = await _publish_text(tenant_id, engine, "Prices", PRICES)
    v1_routes = await _routes(tenant_id, v1)
    engine.events.clear()

    v2 = await _publish_text(tenant_id, engine, "Prices", PRICES_V2)

    source_events = [
        kind for kind, _, title in engine.events if title == "Prices" or kind == "detach"
    ]
    first_detach = source_events.index("detach")
    assert source_events[:first_detach] == ["attach"] * len(agents), (
        "a superseded copy was withdrawn before the new one was on every agent"
    )
    assert await _routes(tenant_id, v1) == {}
    v2_routes = await _routes(tenant_id, v2)
    for agent_id, ref in agents:
        held = await engine.list_kb(ref)
        assert v2_routes[agent_id] in held and v1_routes[agent_id] not in held
    async with tenant_session(tenant_id) as session:
        versions = (
            await session.execute(
                text("SELECT version, is_active FROM kb_sources WHERE id = ANY(:ids)"),
                {"ids": [v1, v2]},
            )
        ).all()
    assert sorted(versions) == [(1, False), (2, True)], "one tenant-wide version sequence"


async def test_an_attach_refused_on_one_agent_undoes_the_others_and_changes_nothing() -> None:
    engine = _FailingEngine()
    tenant_id, agents = await _client_with_agents(engine)
    v1 = await _publish_text(tenant_id, engine, "Prices", PRICES)
    before = {ref: await engine.list_kb(ref) for _, ref in agents}
    engine.refuse_attach.add(agents[-1][1])

    with pytest.raises(ProblemError):
        await _publish_text(tenant_id, engine, "Prices", PRICES_V2)

    for _, ref in agents:
        assert await engine.list_kb(ref) == before[ref], "a refused fan-out left a copy behind"
    assert set(await _routes(tenant_id, v1)) == {a for a, _ in agents}


async def test_a_withdrawal_refused_on_one_agent_completes_the_rest_and_alerts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raised: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(kb_service, "alert", lambda stage, code, **kw: raised.append((code, kw)))
    engine = _FailingEngine()
    tenant_id, agents = await _client_with_agents(engine)
    v1 = await _publish_text(tenant_id, engine, "Prices", PRICES)
    stuck_agent, _ = agents[0]
    engine.refuse_detach_handles.add((await _routes(tenant_id, v1))[stuck_agent])

    v2 = await _publish_text(tenant_id, engine, "Prices", PRICES_V2)

    assert [code for code, _ in raised] == ["kb_fan_out_incomplete"]
    assert set(await _routes(tenant_id, v1)) == {stuck_agent}, (
        "the copy the refusing agent still holds must stay claimed"
    )
    # Every other agent completed; the refusing one may already have been given v2 by the
    # catch-up its own republish ran, but it still holds v1.
    assert {a for a, _ in agents[1:]} <= set(await _routes(tenant_id, v2))

    # The catch-up converges it once the vendor cooperates.
    engine.refuse_detach_handles.clear()
    with _selected(engine):
        async with tenant_session(tenant_id) as session:
            done = await kb_service.catch_up_agent(
                session, tenant_id=tenant_id, agent_id=stuck_agent
            )
    assert done is not None and done.withdrawn == 1
    assert set(await _routes(tenant_id, v2)) == {a for a, _ in agents}
    assert await _routes(tenant_id, v1) == {}


async def test_a_withdrawal_refused_everywhere_refuses_the_publish() -> None:
    engine = _FailingEngine()
    tenant_id, agents = await _client_with_agents(engine, extra=1)
    v1 = await _publish_text(tenant_id, engine, "Prices", PRICES)
    engine.refuse_detach_handles.update((await _routes(tenant_id, v1)).values())

    with pytest.raises(ProblemError) as refused:
        await _publish_text(tenant_id, engine, "Prices", PRICES_V2)
    assert refused.value.code == "kb_detach_failed"
    for _, ref in agents:
        assert "Prices" in _titled(engine, ref)
        assert len([t for t in _titled(engine, ref) if t == "Prices"]) == 1
    assert set(await _routes(tenant_id, v1)) == {a for a, _ in agents}


# --- an agent that arrives later, and one that leaves ---------------------------------


async def test_an_agent_published_later_receives_every_live_source() -> None:
    engine = _FailingEngine()
    tenant_id, agents = await _client_with_agents(engine, extra=0)
    source_id = await _publish_text(tenant_id, engine, "Prices", PRICES)

    (late,) = await _more_agents(tenant_id, 1)
    late_ref = await _publish(tenant_id, late, engine)

    assert "Prices" in _titled(engine, late_ref)
    assert set(await _routes(tenant_id, source_id)) == {agents[0][0], late}
    async with tenant_session(tenant_id) as session:
        assert await kb_service.recorded_handles_of_agent(session, late) == set(
            await engine.list_kb(late_ref)
        )


async def test_the_sweep_catches_up_an_agent_nobody_republished(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _FailingEngine()
    tenant_id, agents = await _client_with_agents(engine, extra=1)
    agent_id, ref = agents[1]
    # Published while the second agent had no vendor agent, so the fan-out skipped it.
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = NULL WHERE id = :a"), {"a": agent_id}
        )
    source_id = await _publish_text(tenant_id, engine, "Prices", PRICES)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = :r WHERE id = :a"),
            {"r": ref, "a": agent_id},
        )
    assert agent_id not in await _routes(tenant_id, source_id)

    from apps.workers import kb_gloss, kb_ingest

    async def _only_this_tenant() -> list[uuid.UUID]:
        return [tenant_id]

    monkeypatch.setattr(kb_gloss, "tenants_holding_knowledge", _only_this_tenant)
    failures: list[str] = []
    with _selected(engine):
        assert await kb_ingest._catch_up_agents(failures) == 1
    assert failures == []
    assert agent_id in await _routes(tenant_id, source_id)
    assert "Prices" in _titled(engine, ref)


async def _route_digests(tenant_id: uuid.UUID, source_id: uuid.UUID) -> dict[uuid.UUID, str]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT agent_id, digest FROM engine_kb_routes WHERE source_id = :s"),
                {"s": source_id},
            )
        ).all()
    return {uuid.UUID(str(row[0])): str(row[1]) for row in rows}


async def test_the_catch_up_replaces_a_copy_a_republish_left_on_its_old_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A re-publish of the SAME source with new content that one agent refused to finish
    leaves that agent's claim in place on the old digest. The catch-up must see the stale
    digest and swap the copy, not count the claim as settled."""
    raised: list[str] = []
    monkeypatch.setattr(kb_service, "alert", lambda stage, code, **kw: raised.append(code))
    engine = _MintingEngine()
    tenant_id, agents = await _client_with_agents(engine, extra=1)
    source_id = await _publish_text(tenant_id, engine, "Prices", PRICES)
    stuck_agent, stuck_ref = agents[1]
    old_handle = (await _routes(tenant_id, source_id))[stuck_agent]
    old_digest = (await _route_digests(tenant_id, source_id))[stuck_agent]

    # The same source now renders to different bytes (a changed upload, a renderer change).
    payload = kb_service._publish_payload

    async def moved(*args: Any, **kwargs: Any) -> tuple[bytes | None, str | None, str]:
        document, url, digest = await payload(*args, **kwargs)
        return document, url, hashlib.sha256(f"{digest}:moved".encode()).hexdigest()

    monkeypatch.setattr(kb_service, "_publish_payload", moved)
    engine.refuse_detach_handles.add(old_handle)
    with _selected(engine):
        async with tenant_session(tenant_id) as session:
            await kb_service.publish_source(session, tenant_id=tenant_id, source_id=source_id)
    assert raised == ["kb_fan_out_incomplete"]
    digests = await _route_digests(tenant_id, source_id)
    new_digest = digests[agents[0][0]]
    assert new_digest != old_digest
    assert digests[stuck_agent] == old_digest, "the refusing agent kept its old copy"

    engine.refuse_detach_handles.clear()
    with _selected(engine):
        async with tenant_session(tenant_id) as session:
            done = await kb_service.catch_up_agent(
                session, tenant_id=tenant_id, agent_id=stuck_agent
            )
    assert done is not None and (done.replaced, done.attached) == (1, 0)
    assert (await _route_digests(tenant_id, source_id))[stuck_agent] == new_digest
    held = await engine.list_kb(stuck_ref)
    assert old_handle not in held
    assert (await _routes(tenant_id, source_id))[stuck_agent] in held
    assert _titled(engine, stuck_ref).count("Prices") == 1, "never two copies"

    with _selected(engine):
        async with tenant_session(tenant_id) as session:
            settled = await kb_service.catch_up_agent(
                session, tenant_id=tenant_id, agent_id=stuck_agent
            )
    assert settled is not None and (settled.attached, settled.replaced) == (0, 0)


async def test_a_catch_up_that_fails_is_recorded_and_the_tick_goes_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _FailingEngine()
    tenant_id, agents = await _client_with_agents(engine, extra=1)
    agent_id, ref = agents[1]
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = NULL WHERE id = :a"), {"a": agent_id}
        )
    await _publish_text(tenant_id, engine, "Prices", PRICES)
    await _publish_text(tenant_id, engine, "Hours", "We open at nine and close at seven daily.")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = :r WHERE id = :a"),
            {"r": ref, "a": agent_id},
        )
    # "Hours" sorts first and is attached; "Prices" is refused, so "Hours" must come down.
    engine.refuse_title = "Prices"

    from apps.workers import kb_gloss, kb_ingest

    async def _only_this_tenant() -> list[uuid.UUID]:
        return [tenant_id]

    monkeypatch.setattr(kb_gloss, "tenants_holding_knowledge", _only_this_tenant)
    monkeypatch.setattr(kb_ingest, "MAX_CATCH_UP_AGENTS_PER_TICK", 5)
    failures: list[str] = []
    with _selected(engine):
        assert await kb_ingest._catch_up_agents(failures) == 0
    assert [f.split(":")[0] for f in failures] == ["catch_up"]
    assert [s.title for s in engine._kb.get(ref, []) if s.title != "Business facts"] == [], (
        "a catch-up that failed part-way left a copy behind"
    )


async def test_the_catch_up_leaves_an_agent_holding_unaccounted_knowledge_alone() -> None:
    engine = _FailingEngine()
    tenant_id, agents = await _client_with_agents(engine, extra=0)
    agent_id, ref = agents[0]
    await engine.attach_kb(ref, KBSourceRef(kb_id="hand-made", title="Console", text="x"))
    async with tenant_session(tenant_id) as session:
        await kb_service.submit_source(
            session, tenant_id=tenant_id, name="Prices", body=PRICES, auto_approve=True
        )
        await session.execute(text("UPDATE kb_sources SET is_active = true, published_at = now()"))
    with _selected(engine):
        async with tenant_session(tenant_id) as session:
            result = await kb_service.converge_agent_knowledge(
                session, engine, tenant_id=tenant_id, agent_id=agent_id, ref=ref
            )
    assert result.skipped_unaccounted
    assert "Prices" not in _titled(engine, ref)


async def test_archiving_an_agent_takes_its_copies_with_it() -> None:
    engine = _FailingEngine()
    tenant_id, agents = await _client_with_agents(engine, extra=1)
    source_id = await _publish_text(tenant_id, engine, "Prices", PRICES)
    gone_agent, gone_ref = agents[1]
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET status = 'paused' WHERE id = :a"), {"a": gone_agent}
        )
    with _selected(engine):
        async with tenant_session(tenant_id) as session:
            await lifecycle.archive_agent(session, tenant_id=tenant_id, agent_id=gone_agent)

    assert "Prices" not in _titled(engine, gone_ref)
    assert set(await _routes(tenant_id, source_id)) == {agents[0][0]}

    # A later publish does not fan out to the archived agent.
    v2 = await _publish_text(tenant_id, engine, "Prices", PRICES_V2)
    assert set(await _routes(tenant_id, v2)) == {agents[0][0]}


async def test_archiving_survives_a_vendor_that_will_not_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raised: list[str] = []
    monkeypatch.setattr(kb_service, "alert", lambda stage, code, **kw: raised.append(code))
    engine = _FailingEngine()
    tenant_id, agents = await _client_with_agents(engine, extra=1)
    source_id = await _publish_text(tenant_id, engine, "Prices", PRICES)
    gone_agent, gone_ref = agents[1]
    engine.refuse_detach.add(gone_ref)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET status = 'paused' WHERE id = :a"), {"a": gone_agent}
        )
    with _selected(engine):
        async with tenant_session(tenant_id) as session:
            result = await lifecycle.archive_agent(
                session, tenant_id=tenant_id, agent_id=gone_agent
            )
    assert result.status == "archived"
    assert raised == ["kb_retired_agent_copy_left"]
    assert gone_agent in await _routes(tenant_id, source_id), "the copy left behind stays claimed"


async def _waiting_on_an_advisory_lock(timeout_s: float = 10.0) -> None:
    """Return once some backend is queued behind an advisory lock, or fail."""
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        async with untenanted_session() as probe:
            waiting = (
                await probe.execute(
                    text(
                        "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted"
                    )
                )
            ).scalar_one()
        if waiting:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("nothing queued behind the tenant's knowledge lock")


async def test_archiving_takes_the_knowledge_lock_before_the_agent_row() -> None:
    """The lock order a knowledge publish relies on: tenant knowledge, then agent rows.

    While the knowledge lock is held, an archive must queue on it WITHOUT having locked
    its agent row — so the holder (standing in for a publish about to rewrite every agent
    row) can still take that row. With the old order the archive held the row first and
    the holder's NOWAIT fails, which is the deadlock with a timer instead of a cycle."""
    engine = _FailingEngine()
    tenant_id, agents = await _client_with_agents(engine, extra=1)
    gone_agent, _ = agents[1]
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET status = 'paused' WHERE id = :a"), {"a": gone_agent}
        )

    async def archive() -> None:
        async with tenant_session(tenant_id) as session:
            await lifecycle.archive_agent(session, tenant_id=tenant_id, agent_id=gone_agent)

    with _selected(engine):
        async with tenant_session(tenant_id) as holder:
            await kb_service.lock_tenant_knowledge(holder, tenant_id=tenant_id)
            archiving = asyncio.create_task(archive())
            await _waiting_on_an_advisory_lock()
            await holder.execute(
                text("SELECT 1 FROM agents WHERE id = :a FOR UPDATE NOWAIT"), {"a": gone_agent}
            )
        await asyncio.wait_for(archiving, timeout=10)

    async with tenant_session(tenant_id) as session:
        status = (
            await session.execute(
                text("SELECT status FROM agents WHERE id = :a"), {"a": gone_agent}
            )
        ).scalar_one()
    assert status == "archived"


async def test_a_publish_that_wrote_its_row_first_is_refused_while_knowledge_publishes() -> None:
    """A settings writer updates the agent row and then publishes. Meeting a knowledge
    publish in flight it must refuse, retryably, rather than wait for the lock while
    holding the row the knowledge publish is about to write."""
    from apps.api.agents.service import KNOWLEDGE_PUBLISH_IN_PROGRESS, publish_agent

    engine = _FailingEngine()
    tenant_id, agents = await _client_with_agents(engine, extra=0)
    agent_id, _ = agents[0]
    with _selected(engine):
        async with tenant_session(tenant_id) as holder:
            await kb_service.lock_tenant_knowledge(holder, tenant_id=tenant_id)
            with pytest.raises(ProblemError) as refused:
                async with tenant_session(tenant_id) as session:
                    await session.execute(
                        text("UPDATE agents SET updated_at = now() WHERE id = :a"),
                        {"a": agent_id},
                    )
                    await asyncio.wait_for(
                        publish_agent(session, tenant_id=tenant_id, agent_id=agent_id),
                        timeout=10,
                    )
    assert refused.value.code == KNOWLEDGE_PUBLISH_IN_PROGRESS
    assert refused.value.status == 409


async def test_withdrawing_a_source_removes_it_from_every_agent() -> None:
    engine = _FailingEngine()
    tenant_id, agents = await _client_with_agents(engine)
    source_id = await _publish_text(tenant_id, engine, "Prices", PRICES)

    with _selected(engine):
        async with tenant_session(tenant_id) as session:
            assert await kb_service.withdraw_source(
                session, tenant_id=tenant_id, source_id=source_id
            )
    for _, ref in agents:
        assert "Prices" not in _titled(engine, ref)
    assert await _routes(tenant_id, source_id) == {}


async def test_a_withdrawal_retried_after_a_partial_failure_completes() -> None:
    engine = _FailingEngine()
    tenant_id, agents = await _client_with_agents(engine)
    source_id = await _publish_text(tenant_id, engine, "Prices", PRICES)
    engine.refuse_detach.add(agents[-1][1])
    with _selected(engine), pytest.raises(ProblemError):
        async with tenant_session(tenant_id) as session:
            await kb_service.withdraw_source(session, tenant_id=tenant_id, source_id=source_id)
    # The first agents' copies are gone at the vendor while our rows rolled back.
    assert set(await _routes(tenant_id, source_id)) == {a for a, _ in agents}

    engine.refuse_detach.clear()
    with _selected(engine):
        async with tenant_session(tenant_id) as session:
            await kb_service.withdraw_source(session, tenant_id=tenant_id, source_id=source_id)
    assert await _routes(tenant_id, source_id) == {}


async def test_a_withdrawal_forgets_a_copy_whose_agent_has_no_vendor_agent() -> None:
    engine = _FailingEngine()
    tenant_id, agents = await _client_with_agents(engine, extra=1)
    source_id = await _publish_text(tenant_id, engine, "Prices", PRICES)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = NULL WHERE id = :a"),
            {"a": agents[1][0]},
        )
    with _selected(engine):
        async with tenant_session(tenant_id) as session:
            await kb_service.withdraw_source(session, tenant_id=tenant_id, source_id=source_id)
    assert await _routes(tenant_id, source_id) == {}


# --- the double push --------------------------------------------------------------------


def test_the_facts_document_carries_the_intake_half_only() -> None:
    block = "\n".join(
        [T0_HEADER, "Hours: mon 09:30-18:00", T0_KNOWLEDGE_MARKER, "- Prices: 500 rupees"]
    )
    assert facts_without_knowledge(block) == f"{T0_HEADER}\nHours: mon 09:30-18:00"
    assert facts_without_knowledge(f"{T0_HEADER}\n{T0_KNOWLEDGE_MARKER}\n- Prices: x") is None
    assert facts_without_knowledge(None) is None


async def test_published_knowledge_reaches_thinnest_once_not_twice() -> None:
    engine = _FailingEngine()
    tenant_id, agents = await _client_with_agents(engine, extra=0)
    await _publish_text(tenant_id, engine, "Prices", PRICES)
    agent_id, ref = agents[0]
    async with tenant_session(tenant_id) as session:
        body = (
            await session.execute(
                text(
                    "SELECT pv.body FROM agents a JOIN prompt_versions pv "
                    "ON pv.id = a.system_prompt_id WHERE a.id = :a"
                ),
                {"a": agent_id},
            )
        ).scalar()
    assert T0_KNOWLEDGE_MARKER in str(body), "our own T0 record keeps the knowledge half"

    texts = [s.text for s in engine._kb.get(ref, []) if s.title == "Business facts"]
    assert texts, "the agent holds its facts document"
    assert all(T0_KNOWLEDGE_MARKER not in t and "500 rupees" not in t for t in texts)
    holding = [s for s in engine._kb.get(ref, []) if "500 rupees" in s.text]
    assert [s.title for s in holding] == ["Prices"], "the source reached the engine twice"


# --- Pipecat: every agent's pack and T0 carry the tenant's sources -----------------------


async def test_every_pipecat_agent_packs_and_compiles_the_tenants_knowledge() -> None:
    tenant_id, first = await _tenant_with_published_agent()
    (second,) = await _more_agents(tenant_id, 1)
    async with tenant_session(tenant_id) as session:
        submitted = await kb_service.submit_source(
            session, tenant_id=tenant_id, name="Prices", body=PRICES, auto_approve=True
        )
        await kb_service.publish_source(
            session, tenant_id=tenant_id, source_id=uuid.UUID(str(submitted["id"]))
        )

    async with tenant_session(tenant_id) as session:
        entries = await read_entries(session, tenant_id=tenant_id)
        assert [e.text for e in entries] == [PRICES]
        for agent_id in (first, second):
            pack = await build_pack(session, tenant_id=tenant_id, agent_id=agent_id)
            assert [e.text for e in pack.entries] == [PRICES]
            compiled = (
                await session.execute(
                    text(
                        "SELECT pv.compiled_t0_context FROM agents a JOIN prompt_versions pv "
                        "ON pv.id = a.system_prompt_id WHERE a.id = :a"
                    ),
                    {"a": agent_id},
                )
            ).scalar()
            assert "- Prices: " in str(compiled), "an agent's T0 lacks the tenant's knowledge"
        knowledge = await kb_service.active_knowledge(session, tenant_id=tenant_id)
    assert [k.name for k in knowledge] == ["Prices"]


async def test_the_sweep_compiles_and_packs_for_an_agent_created_after_the_publish(
    s3: FakeS3,
) -> None:
    tenant_id, _ = await _tenant_with_published_agent()
    async with tenant_session(tenant_id) as session:
        submitted = await kb_service.submit_source(
            session, tenant_id=tenant_id, name="Prices", body=PRICES, auto_approve=True
        )
        await kb_service.publish_source(
            session, tenant_id=tenant_id, source_id=uuid.UUID(str(submitted["id"]))
        )
    (late,) = await _more_agents(tenant_id, 1)

    async with tenant_session(tenant_id) as session:
        done = await kb_service.catch_up_agent(session, tenant_id=tenant_id, agent_id=late)
    assert done is not None
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT pv.compiled_t0_context, a.knowledge_pack_sha256 FROM agents a "
                    "JOIN prompt_versions pv ON pv.id = a.system_prompt_id WHERE a.id = :a"
                ),
                {"a": late},
            )
        ).one()
    assert "- Prices: " in str(row[0])
    assert row[1] is not None, "the late agent was given no in-call pack"


async def test_the_catch_up_steps_over_a_tenant_mid_publish() -> None:
    tenant_id, agent_id = await _tenant_with_published_agent()
    async with tenant_session(tenant_id) as holder:
        await kb_service.lock_tenant_knowledge(holder, tenant_id=tenant_id)
        async with tenant_session(tenant_id) as session:
            assert (
                await kb_service.catch_up_agent(session, tenant_id=tenant_id, agent_id=agent_id)
                is None
            )


async def test_the_catch_up_of_a_retired_agent_is_a_no_op() -> None:
    tenant_id, agent_id = await _tenant_with_published_agent()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET status = 'archived', archived_at = now() WHERE id = :a"),
            {"a": agent_id},
        )
        done = await kb_service.catch_up_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    assert done == kb_service.CatchUp()


# --- tenancy ------------------------------------------------------------------------------


async def test_another_tenant_sees_zero_rows_of_the_shared_knowledge() -> None:
    """Hard rule 1's cross-tenant zero-rows test, for the tenant-level source and its claims."""
    engine = _FailingEngine()
    tenant_a, agents = await _client_with_agents(engine, extra=1)
    source_id = await _publish_text(tenant_a, engine, "Prices", PRICES)
    tenant_b, agent_b = await _tenant_with_published_agent()

    async with tenant_session(tenant_b) as session:
        assert await kb_service.list_sources(session) == []
        # Naming tenant A's id on B's session reaches nothing: RLS, not the argument.
        assert await kb_service.active_knowledge(session, tenant_id=tenant_a) == []
        assert await read_entries(session, tenant_id=tenant_a) == ()
        assert await kb_service._routes_of_source(session, source_id) == []
        for agent_id, _ in agents:
            assert await kb_service.recorded_handles_of_agent(session, agent_id) == set()
        for table in ("kb_sources", "kb_documents", "kb_chunks", "engine_kb_routes"):
            count = (
                await session.execute(
                    text(f"SELECT count(*) FROM {table} WHERE tenant_id = :t"),
                    {"t": tenant_a},
                )
            ).scalar()
            assert count == 0, f"tenant B can see tenant A's {table}"
        assert await kb_service.knowledge_agents(session, tenant_id=tenant_a) == []
    async with untenanted_session() as session:
        claims = (
            await session.execute(
                text("SELECT count(*) FROM engine_kb_routes WHERE source_id = :s"),
                {"s": source_id},
            )
        ).scalar()
    assert claims == len(agents), "the orphan sweep's global read sees one claim per agent"
    del agent_b


async def test_a_claim_cannot_name_another_tenants_agent() -> None:
    engine = _FailingEngine()
    tenant_a, _ = await _client_with_agents(engine, extra=0)
    source_id = await _publish_text(tenant_a, engine, "Prices", PRICES)
    _, agent_b = await _tenant_with_published_agent()
    async with tenant_session(tenant_a) as session:
        await kb_service._remember_engine_kb_ref(session, source_id, agent_b, "stolen")
        assert agent_b not in dict(await kb_service._routes_of_source(session, source_id))


# --- the orphan sweep counts facts documents as ours --------------------------------------


async def test_a_facts_document_is_accounted_for_by_the_orphan_sweep() -> None:
    engine = _FailingEngine()
    tenant_id, agents = await _client_with_agents(engine, extra=0)
    source_id = await _publish_text(tenant_id, engine, "Prices", PRICES)
    _, ref = agents[0]
    handles = await engine.list_kb(ref)
    listing = AccountKBListing(
        objects=[AccountKBObject(handle=h, state="ready") for h in handles], complete=True
    )
    async with untenanted_session() as session:
        report = await orphans.reconcile_account_kb(session, listing, engine=engine.name)
    assert report.unclaimed == 0 and report.unrecorded == 0
    assert report.accounted == len(handles) == 2
    del source_id


# --- the migration ---------------------------------------------------------------------


def test_a_colliding_name_is_disambiguated_by_agent_and_then_by_counter() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "e6b2d9f4a1c3_kb_sources_belong_to_the_tenant.py"
    )
    spec = importlib.util.spec_from_file_location("d689_revision", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration._free_name(set(), "Prices", "Desk") == "Prices (Desk)"
    assert migration._free_name({"Prices (Desk)"}, "Prices", "Desk") == "Prices (Desk) 2"
    long = migration._free_name(set(), "P" * 200, "Desk")
    assert len(long) == 120
