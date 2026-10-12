"""Two CRM read routes at their edges: a lead's captured details through the route, and a
recording download when the object store cannot sign a link."""

from __future__ import annotations

import json
from typing import Any

import pytest
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
