"""A call's details are shown under the list its holder noted them with (D-1003).

The post-call pipeline captures what the call's campaign (else its inbound line) asks to
note, when that holder has its own list. The call screen, the call list's chips and the
lead's details must read that same list: labelled from the agent's own fields instead, the
campaign's details sit at the bottom as "earlier" values, the agent's details the call was
never asked to note read as "Not mentioned", and the list's chips show none of them.
"""

from __future__ import annotations

import json
import uuid
from uuid import UUID

import pytest
from apps.api.campaigns import notes
from apps.api.crm import service as crm_service
from apps.api.crm.routes import get_lead_captured
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from calevate_shared.extraction import ExtractionField
from sqlalchemy import text
from tests.agent_lifecycle_test import _tenant

pytestmark = pytest.mark.rls

VISIT_DAY = ExtractionField(key="visit_day", label="Visit day", type="text")
AGENT_FIELD = ExtractionField(key="insurance_plan", label="Insurance plan", type="text")


async def _campaign_call() -> tuple[UUID, UUID, UUID]:
    """(tenant, call, lead): an agent with its own field, a campaign with its own list, and
    one completed campaign call that noted the campaign's detail."""
    tenant_id, agent_id, _token = await _tenant()
    campaign_id, call_id, lead_id = uuid7(), uuid7(), uuid7()
    async with tenant_session(tenant_id) as session:
        schema_id = uuid7()
        await session.execute(
            text(
                "INSERT INTO extraction_schemas (id, tenant_id, agent_id, version, fields, "
                "created_at, updated_at) VALUES (:id, :t, :a, "
                "(SELECT COALESCE(max(version), 0) + 1 FROM extraction_schemas "
                "WHERE agent_id = :a), CAST(:f AS jsonb), now(), now())"
            ),
            {
                "id": schema_id,
                "t": tenant_id,
                "a": agent_id,
                "f": json.dumps([AGENT_FIELD.model_dump(mode="json")]),
            },
        )
        await session.execute(
            text("UPDATE agents SET extraction_schema_id = :s WHERE id = :a"),
            {"s": schema_id, "a": agent_id},
        )
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, classification, status) "
                "VALUES (:id, :t, :a, 'Check-ups', 'service', 'draft')"
            ),
            {"id": campaign_id, "t": tenant_id, "a": agent_id},
        )
        await notes.save_notes(session, campaign_id, [VISIT_DAY], expected_digest=None)
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, campaign_id, engine_call_id, "
                "direction, status, started_at, duration_s, to_e164, created_at, updated_at) "
                "VALUES (:id, :t, :a, :c, :e, 'outbound', 'completed', now(), 60, "
                "'+919800000123', now(), now())"
            ),
            {"id": call_id, "t": tenant_id, "a": agent_id, "c": campaign_id, "e": f"h-{call_id}"},
        )
        data = json.dumps({"visit_day": "Monday"})
        await session.execute(
            text(
                "INSERT INTO call_extractions (id, tenant_id, call_id, schema_version, data, "
                "model, valid, errors, created_at, updated_at) VALUES (:id, :t, :c, "
                "(SELECT version FROM extraction_schemas WHERE id = :s), CAST(:d AS jsonb), "
                "NULL, true, NULL, now(), now())"
            ),
            {"id": uuid.uuid4(), "t": tenant_id, "c": call_id, "s": schema_id, "d": data},
        )
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, source, status, data, "
                "schema_version, first_call_id, last_call_id, call_count, is_repeat_caller, "
                "created_at, updated_at) VALUES (:id, :t, :a, '+919800000123', 'campaign', 'new', "
                "CAST(:d AS jsonb), (SELECT version FROM extraction_schemas WHERE id = :s), "
                ":c, :c, 1, false, now(), now())"
            ),
            {"id": lead_id, "t": tenant_id, "a": agent_id, "d": data, "s": schema_id, "c": call_id},
        )
        await session.execute(
            text("UPDATE calls SET lead_id = :l WHERE id = :c"), {"l": lead_id, "c": call_id}
        )
    return tenant_id, call_id, lead_id


async def test_a_campaign_calls_details_read_under_the_campaigns_own_list() -> None:
    tenant_id, call_id, lead_id = await _campaign_call()
    async with tenant_session(tenant_id) as session:
        detail = await crm_service.get_call(session, call_id)
        listed = await crm_service.list_calls(session, with_previews=True)
        lead = await get_lead_captured(lead_id, session)

    for fields in (detail.captured, lead.fields):
        by_key = {f.key: f for f in fields}
        assert by_key["visit_day"].label == "Visit day"
        assert by_key["visit_day"].value == "Monday"
        assert by_key["visit_day"].current is True
        # The agent's own detail was never asked for on this call.
        assert "insurance_plan" not in by_key

    row = next(c for c in listed if c.id == call_id)
    assert [(chip.label, chip.value) for chip in row.captured_preview] == [("Visit day", "Monday")]


async def test_a_campaigns_leads_offer_the_campaigns_own_details_as_columns() -> None:
    from apps.api.crm.routes import _leads_page
    from apps.api.crm.schemas import LeadSearchIn

    tenant_id, _call_id, _lead_id = await _campaign_call()
    async with tenant_session(tenant_id) as session:
        campaign_id = (await session.execute(text("SELECT id FROM campaigns LIMIT 1"))).scalar_one()
        page = await _leads_page(
            session, LeadSearchIn(campaign_id=campaign_id), tenant_id=tenant_id
        )
        account = await _leads_page(session, LeadSearchIn(), tenant_id=tenant_id)
    offered = {c.key for c in page.available_columns}
    assert "visit_day" in offered
    assert "insurance_plan" not in offered
    # Without the campaign, the table keeps the agent's own list.
    assert "insurance_plan" in {c.key for c in account.available_columns}


async def test_reading_a_campaign_call_again_asks_for_the_campaigns_own_list() -> None:
    from apps.api.crm.assist import load_assist_source

    tenant_id, call_id, _lead_id = await _campaign_call()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, text, "
                "text_redacted, created_at, updated_at) VALUES (:id, :t, :c, 0, 'caller', "
                "'Monday works', 'Monday works', now(), now())"
            ),
            {"id": uuid.uuid4(), "t": tenant_id, "c": call_id},
        )
        source = await load_assist_source(session, call_id)
    keys = {f.key for f in source.spec.fields}
    assert "visit_day" in keys
    assert "insurance_plan" not in keys
