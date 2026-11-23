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
        await notes.save_notes(session, "campaign", campaign_id, [VISIT_DAY], expected_digest=None)
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
    # Without the campaign, the table offers every job's details (D-1028); the agent's
    # starting list is not one of them.
    account_keys = {c.key for c in account.available_columns}
    assert "visit_day" in account_keys
    assert "insurance_plan" not in account_keys


async def test_an_archived_campaigns_leads_keep_its_details_as_columns() -> None:
    """Archiving keeps a campaign's leads, so the account's Leads table still offers what it
    noted; what open jobs note is unchanged by it, and alerts read only open jobs."""
    from apps.api.crm.routes import _leads_page
    from apps.api.crm.schemas import LeadSearchIn

    tenant_id, _call_id, _lead_id = await _campaign_call()
    async with tenant_session(tenant_id) as session:
        await session.execute(text("UPDATE campaigns SET archived_at = now()"))
        account = await _leads_page(session, LeadSearchIn(), tenant_id=tenant_id)
        open_only = await notes.account_fields(session)
    assert "visit_day" in {c.key for c in account.available_columns}
    assert "visit_day" not in {f.key for f in open_only}


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


async def test_a_campaign_leads_details_are_searchable_under_the_campaigns_list() -> None:
    from apps.api.crm.lead_chunks import discover_lead_chunks, lead_chunk_content

    tenant_id, _call_id, lead_id = await _campaign_call()
    async with tenant_session(tenant_id) as session:
        chunks = [c for c in await discover_lead_chunks(session, 10) if c.subject_id == lead_id]
        content = await lead_chunk_content(session, [(lead_id, c.idx) for c in chunks])
    assert any("Visit day" in c.text and "Monday" in c.text for c in chunks)
    # The claimed re-read projects the same way, so the stored digest matches.
    assert sorted(content.values()) == sorted(c.text for c in chunks)


async def test_a_leads_details_from_an_earlier_line_call_are_still_asked() -> None:
    """A lead met on an Inbound line and then called by a campaign: the line's detail is one a
    job of the lead still notes, so the lead page shows it as asked, not "No longer asked"."""
    budget = ExtractionField(key="budget", label="Budget", type="text")
    tenant_id, call_id, lead_id = await _campaign_call()
    line_id, line_call = uuid7(), uuid7()
    async with tenant_session(tenant_id) as session:
        agent_id = (
            await session.execute(text("SELECT agent_id FROM calls WHERE id = :c"), {"c": call_id})
        ).scalar_one()
        await session.execute(
            text(
                "INSERT INTO inbound_lines (id, tenant_id, name, agent_id, extraction_fields) "
                "VALUES (:id, :t, 'Front desk', :a, CAST(:f AS jsonb))"
            ),
            {
                "id": line_id,
                "t": tenant_id,
                "a": agent_id,
                "f": json.dumps([budget.model_dump(mode="json")]),
            },
        )
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, inbound_line_id, lead_id, "
                "engine_call_id, direction, status, started_at, duration_s, from_e164, "
                "created_at, updated_at) VALUES (:id, :t, :a, :l, :lead, :e, 'inbound', "
                "'completed', now() - interval '1 day', 60, '+919800000123', "
                "now() - interval '1 day', now())"
            ),
            {
                "id": line_call,
                "t": tenant_id,
                "a": agent_id,
                "l": line_id,
                "lead": lead_id,
                "e": f"h-{line_call}",
            },
        )
        await session.execute(
            text(
                "UPDATE leads SET data = data || CAST(:d AS jsonb), call_count = 2 WHERE id = :l"
            ),
            {"l": lead_id, "d": json.dumps({"budget": "50 lakh"})},
        )
        lead = await get_lead_captured(lead_id, session)

    by_key = {f.key: f for f in lead.fields}
    assert (by_key["visit_day"].value, by_key["visit_day"].current) == ("Monday", True)
    assert (by_key["budget"].label, by_key["budget"].value) == ("Budget", "50 lakh")
    assert by_key["budget"].current is True
    # The latest call's job's list comes first.
    business = [f.key for f in lead.fields if not f.core]
    assert business.index("visit_day") < business.index("budget")


async def test_a_call_with_no_job_lists_none_of_the_agents_own_fields_as_not_mentioned() -> None:
    """A call with no campaign or line (an agent's own test call) noted only the core
    (D-1028): the agent's own field it never asked is not `current`, so the screen does not
    list it under "Not mentioned"; a value it holds anyway is still shown."""
    tenant_id, call_id, _lead_id = await _campaign_call()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET campaign_id = NULL, lead_id = NULL WHERE id = :c"),
            {"c": call_id},
        )
        bare = await crm_service.get_call(session, call_id)
        await session.execute(
            text("UPDATE call_extractions SET data = CAST(:d AS jsonb) WHERE call_id = :c"),
            {"c": call_id, "d": json.dumps({"insurance_plan": "Gold"})},
        )
        held = await crm_service.get_call(session, call_id)

    by_key = {f.key: f for f in bare.captured}
    assert by_key["insurance_plan"].value is None
    assert by_key["insurance_plan"].current is False
    assert all(f.current for f in bare.captured if f.core)
    kept = {f.key: f for f in held.captured}["insurance_plan"]
    assert (kept.label, kept.value, kept.current) == ("Insurance plan", "Gold", False)
