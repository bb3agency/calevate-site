"""An action parameter bound to one of the agent's captured details (`field:<key>`).

The binding is validated against THAT agent's extraction schema on write, and resolved at
call time from what the agent already captured about the caller (`leads.data`), under RLS.
"""

from __future__ import annotations

import json
import uuid
from uuid import UUID

import pytest
from apps.api.actions import service
from apps.api.actions.execution import CallFacts, captured_values, lead_values
from apps.api.actions.schema import ParamSpec, lead_field_key
from apps.api.admin import service as admin_service
from apps.api.agents import lifecycle as agent_lifecycle
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from sqlalchemy import text

PHONE = "+919876543210"


def test_field_binding_shape_is_accepted_and_others_refused() -> None:
    spec = ParamSpec.model_validate(
        {"name": "budget", "source": "lead_var", "lead_var": "field:budget"}
    )
    assert lead_field_key(spec.lead_var) == "budget"
    assert lead_field_key("caller_phone") is None
    for bad in ("field:Budget", "field:", "budget", "field:a-b"):
        with pytest.raises(ValueError):
            ParamSpec.model_validate({"name": "x", "source": "lead_var", "lead_var": bad})


def test_call_variables_ignore_field_bindings() -> None:
    params = [
        {"name": "who", "source": "lead_var", "lead_var": "caller_phone"},
        {"name": "budget", "source": "lead_var", "lead_var": "field:budget"},
    ]
    out = lead_values(params, CallFacts(call_ref="c1", caller_e164=PHONE, direction="inbound"))
    assert out == {"who": PHONE}


async def _tenant(slug: str) -> UUID:
    created = await admin_service.create_organization(
        name="Lead Fields Co",
        slug=f"{slug}-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return UUID(str(created["id"]))


async def _agent_with_schema(session, tenant: UUID) -> UUID:  # type: ignore[no-untyped-def]
    agent = await agent_lifecycle.create_agent(
        session, tenant_id=tenant, name="Desk", direction="inbound", language_primary="te-IN"
    )
    fields = [{"key": "budget", "label": "Budget", "type": "string"}]
    await session.execute(
        text(
            "INSERT INTO extraction_schemas (id, tenant_id, agent_id, version, fields, "
            "created_at, updated_at) VALUES (:id, :tid, :aid, "
            "(SELECT COALESCE(MAX(version), 0) + 1 FROM extraction_schemas WHERE agent_id = :aid), "
            "CAST(:f AS jsonb), now(), now())"
        ),
        {"id": uuid7(), "tid": tenant, "aid": agent, "f": json.dumps(fields)},
    )
    return agent


async def _tool(session, tenant: UUID, agent: UUID, lead_var: str):  # type: ignore[no-untyped-def]
    return await service.create_tool(
        session,
        tenant_id=tenant,
        agent_id=agent,
        kind="custom_api",
        provider=None,
        name="send_budget",
        description="when the caller asks for a quote",
        trigger="during_call",
        pre_call_message=None,
        credential_id=None,
        params=[{"name": "budget", "source": "lead_var", "lead_var": lead_var}],
        config={"method": "GET", "url": "https://api.example.com/quote"},
    )


@pytest.mark.asyncio
async def test_unknown_captured_detail_is_refused_on_write() -> None:
    tenant = await _tenant("lf-unknown")
    async with tenant_session(tenant) as s:
        agent = await _agent_with_schema(s, tenant)
        with pytest.raises(ProblemError) as caught:
            await _tool(s, tenant, agent, "field:not_captured")
        assert caught.value.code == "action_param_field_unknown"


@pytest.mark.asyncio
async def test_captured_detail_resolves_from_the_callers_lead() -> None:
    tenant = await _tenant("lf-resolve")
    async with tenant_session(tenant) as s:
        agent = await _agent_with_schema(s, tenant)
        tool = await _tool(s, tenant, agent, "field:budget")
        await s.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, source, status, data, "
                "created_at, updated_at) VALUES (:id, :tid, :aid, :p, 'inbound_call', 'new', "
                "CAST(:d AS jsonb), now(), now())"
            ),
            {"id": uuid7(), "tid": tenant, "aid": agent, "p": PHONE, "d": '{"budget": "40k"}'},
        )
        known = CallFacts(call_ref="c1", caller_e164=PHONE, direction="inbound")
        assert await captured_values(s, tool=tool, call=known) == {"budget": "40k"}
        stranger = CallFacts(call_ref="c2", caller_e164="+919876500000", direction="inbound")
        assert await captured_values(s, tool=tool, call=stranger) == {"budget": None}

    # A neighbour cannot read this tenant's lead through the same binding (RLS).
    other = await _tenant("lf-other")
    async with tenant_session(other) as s:
        assert await captured_values(s, tool=tool, call=known) == {"budget": None}
