"""The extraction rules every "What it notes" list is held to, and the agent's read-only list.

D-460 gave a client owner the power to write the list of details a call notes; D-1028 moved
that list onto each campaign and inbound line, and D-1029 removed the agent-level writes. The
rules stayed in `agents/extraction_routes._validate_fields`, which `campaigns/notes.save_notes`
applies to every job's list, so they are pinned here through a line's notes route:

1. **Validated, never silently dropped.** A duplicate key, an enum with no values and a key
   that collides with a built-in lead column are each refused with a message the form can act
   on.
2. **The list has a CEILING.** Every detail and its `reason` are folded into the extraction
   prompt on every call the job takes, so the cost is not the row. `MAX_*` is imported rather
   than retyped so the tests move with the constants.
3. **The optional `reason` is optional.** A detail with no reason saves.
4. **The agent's own list is a read.** Its GET still answers (a bare agent reads version 0)
   and a stranger's id is 404.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.agents.extraction_routes import (
    MAX_ENUM_VALUES,
    MAX_EXTRACTION_FIELDS,
    MAX_LABEL_LEN,
    MAX_REASON_LEN,
)
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.inbound import lines
from apps.api.main import app
from calevate_shared.lead_fields import CORE_LEAD_FIELDS
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.conftest import create_org_with_receptionist

pytestmark = [pytest.mark.rls]


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _tenant() -> tuple[uuid.UUID, uuid.UUID, str]:
    """(tenant_id, seeded receptionist id, owner's dev bearer) for a fresh clinic org."""
    created = await create_org_with_receptionist(
        name="Capture Clinic",
        slug=f"cap-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    agent_id = uuid.UUID(str(created["agent_id"]))
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:id, :email, now(), now())"
            ),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, 'owner', now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id},
        )
    return tenant_id, agent_id, f"dev:client:{user_id}"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _line(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        return await lines.create_line(
            session, tenant_id=tenant_id, agent_id=agent_id, name="Front desk", created_by=None
        )


def _variable(key: str, **over: object) -> dict[str, object]:
    """One well-formed detail, so a test differs from a valid one in ONE way."""
    field: dict[str, object] = {
        "key": key,
        "label": "Ok",
        "type": "text",
        "enum_values": None,
        "reason": "",
        "required": False,
    }
    field.update(over)
    return field


async def _put(fields: list[dict[str, object]]) -> Any:
    tenant_id, agent_id, token = await _tenant()
    line_id = await _line(tenant_id, agent_id)
    async with _client() as http:
        return await http.put(
            f"/v1/inbound-lines/{line_id}/notes", json={"fields": fields}, headers=_bearer(token)
        )


async def test_a_detail_with_no_reason_saves() -> None:
    saved = await _put([_variable("budget", reason="how much, in lakhs"), _variable("area")])
    assert saved.status_code == 200, saved.text
    assert [f["key"] for f in saved.json()["fields"]] == ["budget", "area"]


async def test_duplicate_keys_are_refused() -> None:
    refused = await _put([_variable("area"), _variable("area", label="Area again")])
    assert refused.status_code == 422
    assert refused.json()["type"].endswith("/extraction_schema_invalid")


async def test_a_reserved_key_is_refused_by_name() -> None:
    refused = await _put([_variable("status")])
    assert refused.status_code == 422
    body = refused.json()
    assert body["type"].endswith("/extraction_field_reserved_key")
    assert "status" in body["detail"]


async def test_an_enum_with_no_values_is_refused() -> None:
    refused = await _put([_variable("urgency", type="enum", enum_values=[])])
    assert refused.status_code == 422


async def test_a_list_past_the_ceiling_is_refused_and_the_ceiling_saves() -> None:
    refused = await _put([_variable(f"f{i}") for i in range(MAX_EXTRACTION_FIELDS + 1)])
    assert refused.status_code == 422
    at_the_line = await _put([_variable(f"f{i}") for i in range(MAX_EXTRACTION_FIELDS)])
    assert at_the_line.status_code == 200, at_the_line.text


async def test_an_oversized_reason_is_refused_and_names_the_detail() -> None:
    """The `reason` is read on every call, and the message has to name WHICH detail."""
    response = await _put([_variable("symptom", reason="x" * (MAX_REASON_LEN + 1))])
    assert response.status_code == 422
    body = response.json()
    assert body["type"].endswith("/extraction_field_reason_too_long")
    assert "symptom" in body["detail"]


async def test_an_oversized_label_is_refused() -> None:
    response = await _put([_variable("symptom", label="L" * (MAX_LABEL_LEN + 1))])
    assert response.status_code == 422
    assert response.json()["type"].endswith("/extraction_field_label_too_long")


async def test_too_many_choices_on_one_detail_are_refused() -> None:
    response = await _put(
        [
            _variable(
                "urgency", type="enum", enum_values=[f"v{i}" for i in range(MAX_ENUM_VALUES + 1)]
            )
        ]
    )
    assert response.status_code == 422
    assert response.json()["type"].endswith("/extraction_field_choices_invalid")


async def test_an_agent_with_no_schema_reads_empty() -> None:
    from apps.api.agents import lifecycle

    tenant_id, _seeded, token = await _tenant()
    async with tenant_session(tenant_id) as session:
        bare_agent = await lifecycle.create_agent(
            session,
            tenant_id=tenant_id,
            name="Bare",
            direction="inbound",
            language_primary="te-IN",
        )
    async with _client() as http:
        got = await http.get(f"/v1/agents/{bare_agent}/extraction-schema", headers=_bearer(token))
        assert got.status_code == 200
        body = got.json()
        assert {k: body[k] for k in ("fields", "version", "changed")} == {
            "fields": [],
            "version": 0,
            "changed": False,
        }
        assert [f["key"] for f in body["core_fields"]] == [f.key for f in CORE_LEAD_FIELDS]


async def test_get_on_an_unknown_agent_is_404() -> None:
    _tid, _agent, token = await _tenant()
    async with _client() as http:
        r = await http.get(f"/v1/agents/{uuid.uuid4()}/extraction-schema", headers=_bearer(token))
    assert r.status_code == 404
