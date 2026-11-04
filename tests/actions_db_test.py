"""ACTIONS feature — DB-backed tests: RLS isolation (hard rule 1), the credential envelope
round trip, and the publish-time declaration + master switch.

Needs a migrated database. Each test mints its own tenant and touches no global row, so the
file runs beside the other suites on the shared Postgres.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from uuid import UUID

import pytest
from apps.api.actions import credentials as creds
from apps.api.actions import service
from apps.api.actions.credentials import credential_context
from apps.api.agents import lifecycle as agent_lifecycle
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conftest import create_org_with_receptionist


async def _tenant(slug: str) -> UUID:
    created = await create_org_with_receptionist(
        name="Actions Co",
        slug=f"{slug}-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return UUID(str(created["id"]))


@pytest.mark.asyncio
async def test_credential_envelope_round_trips_and_is_tenant_bound() -> None:
    tenant = await _tenant("cred")
    async with tenant_session(tenant) as s:
        rec = await creds.create_credential(
            s, tenant_id=tenant, kind="aisensy", label="Main key", secret="super-secret-value"
        )
        assert rec.last_four  # a fragment, not the value
        got = await creds.resolve_secret(s, tenant_id=tenant, credential_id=rec.id)
        assert got == "super-secret-value"


@pytest.mark.asyncio
async def test_credential_secret_will_not_unseal_under_a_wrong_tenant_context() -> None:
    tenant = await _tenant("aad")
    async with tenant_session(tenant) as s:
        rec = await creds.create_credential(
            s, tenant_id=tenant, kind="custom_api", label="k", secret="v-123456"
        )
        # The AAD binds ciphertext to (tenant, id); resolving with a different tenant id
        # fails the integrity check rather than returning a value.
        with pytest.raises(ProblemError):
            from apps.api.core.envelope import Envelope, unseal

            row = (
                await s.execute(
                    text(
                        "SELECT ciphertext, nonce, dek_wrapped, dek_nonce, kek_version "
                        "FROM integration_credentials WHERE id = :id"
                    ),
                    {"id": rec.id},
                )
            ).first()
            assert row is not None
            env = Envelope(
                ciphertext=bytes(row[0]),
                nonce=bytes(row[1]),
                dek_wrapped=bytes(row[2]),
                dek_nonce=bytes(row[3]),
                kek_id=int(row[4]),
            )
            unseal(env, context=credential_context(uuid.uuid4(), rec.id))


@pytest.mark.asyncio
async def test_credential_rls_zero_rows_across_tenants() -> None:
    a, b = await _tenant("rls-a"), await _tenant("rls-b")
    async with tenant_session(a) as sa:
        await creds.create_credential(sa, tenant_id=a, kind="interakt", label="A key", secret="x")
    async with tenant_session(b) as sb:
        # Neighbour's credential is invisible under RLS — zero rows, not an error.
        assert await creds.list_credentials(sb) == []


@pytest.mark.asyncio
async def test_action_tool_rls_zero_rows_across_tenants() -> None:
    a, b = await _tenant("tool-a"), await _tenant("tool-b")
    async with tenant_session(a) as sa:
        agent_a = await agent_lifecycle.create_agent(
            sa, tenant_id=a, name="Recept", direction="inbound", language_primary="te-IN"
        )
        await service.create_tool(
            sa,
            tenant_id=a,
            agent_id=agent_a,
            kind="custom_api",
            provider=None,
            name="get_status",
            description="when asked about it",
            trigger="during_call",
            pre_call_message=None,
            credential_id=None,
            params=[{"name": "order_id", "source": "ai", "type": "string", "description": "id"}],
            config={"method": "GET", "url": "https://api.example.com/o"},
        )
    async with tenant_session(b) as sb:
        # RLS: tenant B lists tenant A's agent's tools as zero rows.
        assert await service.list_tools(sb, agent_id=agent_a) == []


@pytest.mark.asyncio
async def test_action_invocation_rls_zero_rows_across_tenants() -> None:
    """D-700's per-action run log is tenant data: a neighbour reads none of it."""
    from apps.workers.action_audit import _record_invocation

    a, b = await _tenant("runs-a"), await _tenant("runs-b")
    async with tenant_session(a) as sa:
        agent_a = await agent_lifecycle.create_agent(
            sa, tenant_id=a, name="Recept", direction="inbound", language_primary="te-IN"
        )
        tool = await service.create_tool(
            sa,
            tenant_id=a,
            agent_id=agent_a,
            kind="custom_api",
            provider=None,
            name="get_status",
            description="when asked about it",
            trigger="during_call",
            pre_call_message=None,
            credential_id=None,
            params=[],
            config={"method": "GET", "url": "https://api.example.com/o"},
        )
        await _record_invocation(
            sa,
            tenant_id=a,
            payload={"tool_id": str(tool.id), "status": "http_200", "source": "test"},
        )
        assert (await sa.execute(text("SELECT count(*) FROM action_invocations"))).scalar_one() == 1
    async with tenant_session(b) as sb:
        assert (await sb.execute(text("SELECT count(*) FROM action_invocations"))).scalar_one() == 0


@pytest.mark.asyncio
async def test_declare_respects_master_switch_and_trigger() -> None:
    tenant = await _tenant("decl")
    async with tenant_session(tenant) as s:
        agent = await agent_lifecycle.create_agent(
            s, tenant_id=tenant, name="R", direction="inbound", language_primary="te-IN"
        )
        await service.create_tool(
            s,
            tenant_id=tenant,
            agent_id=agent,
            kind="custom_api",
            provider=None,
            name="get_status",
            description="when asked about an order",
            trigger="during_call",
            pre_call_message="one moment",
            credential_id=None,
            params=[
                {"name": "order_id", "source": "ai", "type": "string", "description": "id"},
                {"name": "caller", "source": "lead_var", "lead_var": "caller_phone"},
            ],
            config={
                "method": "GET",
                "url": "https://api.example.com/o",
                "query": [{"key": "id", "param": "order_id"}],
            },
        )
        # An after-call tool (stored before after-call work moved to Follow-ups) must NOT
        # be declared as an engine function.
        await _legacy_after_call_tool(s, tenant, agent)

        # Master switch OFF (default): nothing declared.
        assert await service.declare(s, agent_id=agent, direction="inbound") == ()

        # Master switch ON: only the during-call tool, declaring only what the model fills.
        await service.set_actions_enabled(s, agent_id=agent, enabled=True)
        specs = await service.declare(s, agent_id=agent, direction="inbound")
        assert len(specs) == 1
        spec = specs[0]
        assert spec.name == "get_status"
        names = {p.name for p in spec.params}
        assert "order_id" in names and "caller" not in names


async def _legacy_after_call_tool(s: AsyncSession, tenant: UUID, agent: UUID) -> UUID:
    """An after-call action as rows stored before new ones were refused still hold it:
    created during the call, then moved by SQL, as no route now can."""
    tool = await service.create_tool(
        s,
        tenant_id=tenant,
        agent_id=agent,
        kind="custom_api",
        provider=None,
        name="log_it",
        description="after the call",
        trigger="during_call",
        pre_call_message=None,
        credential_id=None,
        params=[],
        config={"method": "POST", "url": "https://api.example.com/log"},
    )
    await s.execute(
        text("UPDATE action_tools SET trigger = 'after_call' WHERE id = :id"), {"id": tool.id}
    )
    return tool.id


@pytest.mark.asyncio
async def test_after_call_work_is_refused_on_new_actions_and_kept_on_old_ones() -> None:
    tenant = await _tenant("after")
    async with tenant_session(tenant) as s:
        agent = await agent_lifecycle.create_agent(
            s, tenant_id=tenant, name="R", direction="inbound", language_primary="te-IN"
        )
        common = {
            "kind": "custom_api",
            "provider": None,
            "description": "after the call",
            "pre_call_message": None,
            "credential_id": None,
            "params": [],
            "config": {"method": "POST", "url": "https://api.example.com/log"},
        }
        with pytest.raises(ProblemError) as new:
            await service.create_tool(
                s, tenant_id=tenant, agent_id=agent, name="log_new", trigger="after_call", **common
            )
        assert new.value.code == "action_after_call_moved"

        sheet = {
            "kind": "sheets",
            "provider": None,
            "description": "save the caller's answers",
            "pre_call_message": None,
            "credential_id": None,
            "params": [],
            "config": {"operation": "record", "spreadsheet_id": "a" * 44, "columns": []},
        }
        with pytest.raises(ProblemError) as row:
            await service.create_tool(
                s, tenant_id=tenant, agent_id=agent, name="save_row", trigger="during_call", **sheet
            )
        assert row.value.code == "action_sheet_moved"

        legacy = await _legacy_after_call_tool(s, tenant, agent)
        edited = await service.update_tool(
            s, tool_id=legacy, name="log_it", trigger="after_call", **common
        )
        assert edited.trigger == "after_call"
        moved = await service.update_tool(
            s, tool_id=legacy, name="log_it", trigger="during_call", **common
        )
        assert moved.trigger == "during_call"
        with pytest.raises(ProblemError) as back:
            await service.update_tool(
                s, tool_id=legacy, name="log_it", trigger="after_call", **common
            )
        assert back.value.code == "action_after_call_moved"


@pytest.mark.asyncio
async def test_tool_name_must_be_snake_case() -> None:
    tenant = await _tenant("name")
    async with tenant_session(tenant) as s:
        agent = await agent_lifecycle.create_agent(
            s, tenant_id=tenant, name="R", direction="inbound", language_primary="te-IN"
        )
        with pytest.raises(ProblemError) as exc:
            await service.create_tool(
                s,
                tenant_id=tenant,
                agent_id=agent,
                kind="custom_api",
                provider=None,
                name="Get Status",
                description="x",
                trigger="during_call",
                pre_call_message=None,
                credential_id=None,
                params=[],
                config={"method": "GET", "url": "https://api.example.com/o"},
            )
        assert exc.value.code == "action_name_invalid"


# --- the URL has to mean what it says ------------------------------------------------
#
# `routes.invoke_action` carried the comment "Also refuse a disabled tool or one belonging
# to a different agent than the ref resolved" above a line that read
# `if tool is None or not tool.enabled`. There was no agent comparison anywhere: the bridge
# query selected `tenant_id` only, and `get_tool` was a bare `WHERE id = :id`. The three
# sibling routes had the same shape — `_assert_agent` proved the AGENT belonged to the
# caller, then the tool was fetched by id, so any agent id paired with any tool id.
#
# RLS kept it inside one tenant, so it was never a cross-tenant hole. What it broke is that
# a tenant-scoped credential could be used through a binding nobody verified, and that a
# comment asserted a control which was never written.


async def _agent_with_tool(session, tenant: UUID, *, name: str) -> tuple[UUID, UUID]:
    agent = await agent_lifecycle.create_agent(
        session, tenant_id=tenant, name=name, direction="inbound", language_primary="te-IN"
    )
    tool = await service.create_tool(
        session,
        tenant_id=tenant,
        agent_id=agent,
        kind="custom_api",
        provider=None,
        name="get_status",
        description="when asked about it",
        trigger="during_call",
        pre_call_message=None,
        credential_id=None,
        params=[{"name": "order_id", "source": "ai", "type": "string", "description": "id"}],
        config={"method": "GET", "url": "https://api.example.com/o"},
    )
    return agent, tool.id


@pytest.mark.asyncio
async def test_a_tool_is_invisible_through_another_agent_of_the_same_tenant() -> None:
    """The binding, as a filter rather than a comparison.

    Same tenant, so RLS is not what is being tested — two agents the same client owns.
    Agent A's tool must not be reachable by naming agent B, and the miss must be the SAME
    `None` a deleted tool returns, so a probe cannot tell "not yours" from "not there".
    """
    tenant = await _tenant("bind")
    async with tenant_session(tenant) as s:
        agent_a, tool_a = await _agent_with_tool(s, tenant, name="Agent A")
        agent_b, _ = await _agent_with_tool(s, tenant, name="Agent B")

        assert await service.get_agent_tool(s, agent_id=agent_a, tool_id=tool_a) is not None
        assert await service.get_agent_tool(s, agent_id=agent_b, tool_id=tool_a) is None


@pytest.mark.asyncio
async def test_a_mutation_through_the_wrong_agent_changes_nothing() -> None:
    """`set_enabled` and `delete_tool` filter on the agent too, and report the miss.

    A `rowcount` of 0 is what the routes turn into a 404, so the refusal and the
    non-effect are the same fact rather than two that could drift. The read afterwards is
    the half that matters: a mutation that returned False having still written would be
    the worst of both.
    """
    tenant = await _tenant("bind-mut")
    async with tenant_session(tenant) as s:
        agent_a, tool_a = await _agent_with_tool(s, tenant, name="Agent A")
        agent_b, _ = await _agent_with_tool(s, tenant, name="Agent B")

        assert not await service.set_enabled(s, agent_id=agent_b, tool_id=tool_a, enabled=False), (
            "a tool was disabled through an agent that does not own it"
        )
        still = await service.get_agent_tool(s, agent_id=agent_a, tool_id=tool_a)
        assert still is not None and still.enabled, "the wrong-agent update took effect"

        assert not await service.delete_tool(s, agent_id=agent_b, tool_id=tool_a), (
            "a tool was deleted through an agent that does not own it"
        )
        assert await service.get_agent_tool(s, agent_id=agent_a, tool_id=tool_a) is not None

        # The control: through its own agent, both work.
        assert await service.set_enabled(s, agent_id=agent_a, tool_id=tool_a, enabled=False)
        assert await service.delete_tool(s, agent_id=agent_a, tool_id=tool_a)
        assert await service.get_agent_tool(s, agent_id=agent_a, tool_id=tool_a) is None


async def _race(*saves: Callable[[AsyncSession], Awaitable[object]], tenant: UUID) -> list[bool]:
    """Each save in its own transaction, all opened before any of them counts."""
    barrier = asyncio.Barrier(len(saves))

    async def one(save: Callable[[AsyncSession], Awaitable[object]]) -> bool:
        try:
            async with tenant_session(tenant) as s:
                await s.execute(text("SELECT 1"))
                await barrier.wait()
                await save(s)
        except ProblemError:
            return False
        return True

    return list(await asyncio.gather(*(one(save) for save in saves)))


@pytest.mark.asyncio
async def test_two_credentials_racing_for_the_last_place_keep_the_cap() -> None:
    tenant = await _tenant("cred-cap")
    async with tenant_session(tenant) as s:
        for index in range(creds.MAX_CREDENTIALS_PER_TENANT - 1):
            await creds.create_credential(
                s, tenant_id=tenant, kind="custom_api", label=f"k{index}", secret="v-123456"
            )

    def save(label: str) -> Callable[[AsyncSession], Awaitable[object]]:
        return lambda s: creds.create_credential(
            s, tenant_id=tenant, kind="custom_api", label=label, secret="v-123456"
        )

    assert sorted(await _race(save("left"), save("right"), tenant=tenant)) == [False, True]
    async with tenant_session(tenant) as s:
        kept = (await s.execute(text("SELECT count(*) FROM integration_credentials"))).scalar()
    assert kept == creds.MAX_CREDENTIALS_PER_TENANT


@pytest.mark.asyncio
async def test_two_actions_racing_for_the_last_place_keep_the_cap() -> None:
    tenant = await _tenant("tool-cap")
    async with tenant_session(tenant) as s:
        agent, tool = await _agent_with_tool(s, tenant, name="Capped")
        await s.execute(
            text(
                "INSERT INTO action_tools (id, tenant_id, agent_id, kind, provider, name, "
                "description, enabled, trigger, pre_call_message, credential_id, config, "
                "params, created_at, updated_at) SELECT gen_random_uuid(), tenant_id, agent_id, "
                "kind, provider, name || '_' || n, description, enabled, trigger, "
                "pre_call_message, credential_id, config, params, now(), now() "
                "FROM action_tools, generate_series(1, :n) AS n WHERE id = :id"
            ),
            {"id": tool, "n": service.MAX_TOOLS_PER_AGENT - 2},
        )

    def save(name: str) -> Callable[[AsyncSession], Awaitable[object]]:
        return lambda s: service.create_tool(
            s,
            tenant_id=tenant,
            agent_id=agent,
            kind="custom_api",
            provider=None,
            name=name,
            description="when asked about it",
            trigger="during_call",
            pre_call_message=None,
            credential_id=None,
            params=[{"name": "order_id", "source": "ai", "type": "string", "description": "id"}],
            config={"method": "GET", "url": "https://api.example.com/o"},
        )

    assert sorted(await _race(save("get_left"), save("get_right"), tenant=tenant)) == [
        False,
        True,
    ]
    async with tenant_session(tenant) as s:
        kept = (
            await s.execute(
                text("SELECT count(*) FROM action_tools WHERE agent_id = :a"), {"a": agent}
            )
        ).scalar()
    assert kept == service.MAX_TOOLS_PER_AGENT
