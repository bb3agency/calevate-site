"""Two CRM read routes at their edges: a lead's captured details through the route, and a
recording download when the object store cannot sign a link."""

from __future__ import annotations

import json
from typing import Any

import pytest
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from calevate_shared.lead_fields import CORE_LEAD_FIELDS
from sqlalchemy import text
from tests.call_translation_test import _audits, _telugu_call
from tests.lead_dial_routes_test import _client, _dialable_tenant, _lead


async def test_a_leads_captured_details_list_the_core_first_then_earlier_answers() -> None:
    tenant_id, agent_id, _slug, headers = await _dialable_tenant()
    lead_id, _phone = await _lead(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE leads SET data = CAST(:d AS jsonb) WHERE id = :i"),
            {
                "d": json.dumps({"need": "A two-bedroom flat", "parking_needed": "yes"}),
                "i": lead_id,
            },
        )

    async with _client() as http:
        response = await http.get(f"/v1/leads/{lead_id}/captured", headers=headers)

    assert response.status_code == 200, response.text
    fields: list[dict[str, Any]] = response.json()["fields"]
    core = [f.key for f in CORE_LEAD_FIELDS]
    assert [f["key"] for f in fields[: len(core)]] == core
    assert all(f["core"] and f["current"] for f in fields[: len(core)])
    by_key = {f["key"]: f for f in fields}
    assert by_key["need"]["value"] == "A two-bedroom flat"
    earlier = by_key["parking_needed"]
    assert (earlier["core"], earlier["current"], earlier["value"]) == (False, False, "yes")


async def test_a_lead_names_its_details_from_any_of_the_account_s_agents_and_its_own_name() -> None:
    """L3-10/L3-11: a value another agent of the account captured is labelled from that
    agent's fields, never from its key ("Bhk size"), and the lead's own name fills an
    empty name field ("Name: Not said" on a lead called Priya)."""
    tenant_id, agent_id, _slug, headers = await _dialable_tenant()
    lead_id, _phone = await _lead(tenant_id, agent_id)
    other = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO agents (id, tenant_id, name, direction, status, language_primary, "
                "disclosure_line, ai_disclosure_line, recording_notice_line, "
                "caller_memory_notice_line, created_at, updated_at) VALUES (:id, :tid, "
                "'Sales', 'outbound', 'draft', 'te-IN', 'This is an AI assistant.', "
                "'This is an AI assistant.', 'This call is recorded.', 'I keep a note.', "
                "now(), now())"
            ),
            {"id": other, "tid": tenant_id},
        )
        await session.execute(
            text(
                "INSERT INTO extraction_schemas (id, tenant_id, agent_id, version, fields, "
                "created_at, updated_at) VALUES (:id, :tid, :aid, 1, CAST(:f AS jsonb), "
                "now(), now())"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "aid": other,
                "f": json.dumps([{"key": "bhk_size", "label": "Flat size", "type": "text"}]),
            },
        )
        await session.execute(
            text("UPDATE leads SET data = CAST(:d AS jsonb) WHERE id = :i"),
            {"d": json.dumps({"bhk_size": "2BHK"}), "i": lead_id},
        )

    async with _client() as http:
        response = await http.get(f"/v1/leads/{lead_id}/captured", headers=headers)

    assert response.status_code == 200, response.text
    by_key = {f["key"]: f for f in response.json()["fields"]}
    assert by_key["bhk_size"]["label"] == "Flat size"
    assert (by_key["name"]["value"], by_key["name"]["source"]) == ("Priya", "lead")


async def test_a_recording_link_that_cannot_be_signed_is_unavailable_and_not_audited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, call_id, _slug, headers = await _telugu_call()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET recording_url = :k WHERE id = :i"),
            {"k": f"recordings/{tenant_id}/{call_id}.mp3", "i": call_id},
        )
    monkeypatch.setattr("apps.workers.storage.presigned_url", lambda *_a, **_k: None)

    async with _client() as http:
        response = await http.get(f"/v1/calls/{call_id}/recording/download", headers=headers)

    assert response.status_code == 503, response.text
    assert response.json()["type"].endswith("/recording_unavailable")
    assert await _audits("recording.download", call_id) == 0, "no copy left our control"
