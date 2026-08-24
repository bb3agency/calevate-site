"""ACTIONS feature — DB-backed tests: RLS isolation (hard rule 1), the credential envelope
round trip, and the publish-time declaration + master switch.

Needs a migrated database. Each test mints its own tenant and touches no global row, so the
file runs beside the other suites on the shared Postgres.
"""

from __future__ import annotations

import uuid
from uuid import UUID

import pytest
from apps.api.actions import credentials as creds
from apps.api.actions import service
from apps.api.actions.credentials import credential_context
from apps.api.admin import service as admin_service
from apps.api.agents import lifecycle as agent_lifecycle
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from sqlalchemy import text


async def _tenant(slug: str) -> UUID:
    created = await admin_service.create_organization(
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
            description="when asked",
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
        # An after-call tool must NOT be declared as an engine function.
        await service.create_tool(
            s,
            tenant_id=tenant,
            agent_id=agent,
            kind="custom_api",
            provider=None,
            name="log_it",
            description="after the call",
            trigger="after_call",
            pre_call_message=None,
            credential_id=None,
            params=[],
            config={"method": "POST", "url": "https://api.example.com/log"},
        )

        # Master switch OFF (default): nothing declared.
        assert await service.declare(s, agent_id=agent, engine="bolna", direction="inbound") == ()

        # Master switch ON: only the during-call tool, with agent-ref injected.
        await service.set_actions_enabled(s, agent_id=agent, enabled=True)
        specs = await service.declare(s, agent_id=agent, engine="bolna", direction="inbound")
        assert len(specs) == 1
        spec = specs[0]
        assert spec.name == "get_status"
        during = next(
            t for t in await service.list_tools(s, agent_id=agent) if t.name == "get_status"
        )
        assert spec.url.endswith(f"/v1/actions/invoke/bolna/{during.id}")
        names = {p.name for p in spec.params}
        assert "order_id" in names and "caller" in names and "_agent_ref" in names


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
