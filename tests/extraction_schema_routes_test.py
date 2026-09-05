"""Editing an agent's extraction VARIABLES over the API (D-460).

Four claims, each a different way the feature could be wrong:

1. **A client owner can rewrite the list, and it takes a new version live.** The whole
   ordered list is the unit; a save inserts a new `extraction_schemas` version and points
   the agent at it, so the NEXT call extracts against it and old leads keep their version.
2. **The write is idempotent and validated.** Re-sending the list on file moves nothing;
   a duplicate key, an enum with no values, and a key that collides with a built-in lead
   column are each refused with a message the form can act on — never silently dropped.
3. **The optional `reason` is optional.** A variable with no reason saves and the model is
   left to work from its name alone (the founder's rule).
4. **The list has a CEILING, and it is the write model's.** D-460 handed this surface to
   a client owner, which makes the length of `fields` caller-controlled — and nothing was
   refusing fifty thousand variables, or one variable whose `reason` is a megabyte. Every
   one of them is folded into the extraction prompt on EVERY call that agent ever takes,
   so the cost is not the row. The four cases below are the ceilings; `MAX_*` is imported
   rather than retyped so the tests move with the constants.
5. **The realm boundary holds.** An owner reaches only their own tenant's agents (a
   neighbour's id is 404, hard rule 1); an operator reaches any tenant by naming it in the
   path (D-22: impersonation is read-only, so the tenant is named, not inferred). Every
   change writes an audit entry carrying the field SHAPE and never a caller's value.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents.extraction_routes import (
    MAX_ENUM_VALUES,
    MAX_EXTRACTION_FIELDS,
    MAX_LABEL_LEN,
    MAX_REASON_LEN,
    ExtractionSchemaOut,
    _audit_summary,
    admin_router,
    router,
)
from apps.api.core.errors import install_error_handlers
from apps.api.core.rbac import assert_policy_registry_complete
from apps.api.db.session import tenant_session, untenanted_session
from calevate_shared.extraction import ExtractionField
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

pytestmark = [pytest.mark.rls]


def _app() -> FastAPI:
    application = FastAPI()
    install_error_handlers(application)
    application.include_router(router)
    application.include_router(admin_router)
    assert_policy_registry_complete(application)
    return application


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _tenant(role: str = "owner") -> tuple[uuid.UUID, uuid.UUID, str]:
    """(tenant_id, seeded receptionist id, client dev bearer) for a fresh clinic org."""
    created = await admin_service.create_organization(
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
                "VALUES (:id, :tid, :uid, :role, now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id, "role": role},
        )
    return tenant_id, agent_id, f"dev:client:{user_id}"


async def _make_admin() -> str:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    return f"dev:admin:{admin_id}"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


_TWO_FIELDS = [
    {
        "key": "budget",
        "label": "Budget",
        "type": "number",
        "enum_values": None,
        "reason": "how much they can spend, in lakhs",
        "required": True,
    },
    # No reason on purpose — the name-alone case must be accepted.
    {
        "key": "area",
        "label": "Area",
        "type": "text",
        "enum_values": None,
        "reason": "",
        "required": False,
    },
]


async def test_owner_can_replace_the_list_and_it_bumps_the_version() -> None:
    tenant_id, agent_id, token = await _tenant()
    app = _app()
    async with _client(app) as http:
        before = await http.get(f"/v1/agents/{agent_id}/extraction-schema", headers=_bearer(token))
        assert before.status_code == 200
        start_version = before.json()["version"]

        put = await http.put(
            f"/v1/agents/{agent_id}/extraction-schema",
            json={"fields": _TWO_FIELDS},
            headers=_bearer(token),
        )
        assert put.status_code == 200, put.text
        body = put.json()
        assert body["changed"] is True
        assert body["version"] == start_version + 1
        assert [f["key"] for f in body["fields"]] == ["budget", "area"]
        # The reason-less field round-trips as an empty string, not a missing key.
        assert body["fields"][1]["reason"] == ""

    # A NEW version row exists and the agent points at it — history is not overwritten.
    async with tenant_session(tenant_id) as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT version FROM extraction_schemas "
                        "WHERE agent_id = :a ORDER BY version"
                    ),
                    {"a": agent_id},
                )
            )
            .scalars()
            .all()
        )
        assert rows == [1, 2] or rows[-1] == start_version + 1
        pointed = (
            await session.execute(
                text(
                    "SELECT es.version FROM agents a "
                    "JOIN extraction_schemas es ON es.id = a.extraction_schema_id "
                    "WHERE a.id = :a"
                ),
                {"a": agent_id},
            )
        ).scalar_one()
        assert pointed == start_version + 1


async def test_re_putting_the_same_list_changes_nothing() -> None:
    _tid, agent_id, token = await _tenant()
    app = _app()
    async with _client(app) as http:
        first = await http.put(
            f"/v1/agents/{agent_id}/extraction-schema",
            json={"fields": _TWO_FIELDS},
            headers=_bearer(token),
        )
        assert first.status_code == 200
        version = first.json()["version"]
        again = await http.put(
            f"/v1/agents/{agent_id}/extraction-schema",
            json={"fields": _TWO_FIELDS},
            headers=_bearer(token),
        )
        assert again.status_code == 200
        assert again.json()["changed"] is False
        assert again.json()["version"] == version


async def test_duplicate_keys_are_refused() -> None:
    _tid, agent_id, token = await _tenant()
    app = _app()
    dup = [
        {
            "key": "x",
            "label": "One",
            "type": "text",
            "enum_values": None,
            "reason": "",
            "required": False,
        },
        {
            "key": "x",
            "label": "Two",
            "type": "text",
            "enum_values": None,
            "reason": "",
            "required": False,
        },
    ]
    async with _client(app) as http:
        r = await http.put(
            f"/v1/agents/{agent_id}/extraction-schema",
            json={"fields": dup},
            headers=_bearer(token),
        )
    assert r.status_code == 422
    assert r.json()["type"].endswith("/extraction_schema_invalid")


async def test_a_reserved_key_is_refused_by_name() -> None:
    _tid, agent_id, token = await _tenant()
    app = _app()
    reserved = [
        {
            "key": "phone",
            "label": "Phone",
            "type": "text",
            "enum_values": None,
            "reason": "",
            "required": False,
        },
    ]
    async with _client(app) as http:
        r = await http.put(
            f"/v1/agents/{agent_id}/extraction-schema",
            json={"fields": reserved},
            headers=_bearer(token),
        )
    assert r.status_code == 422
    assert r.json()["type"].endswith("/extraction_field_reserved_key")
    assert "phone" in r.json()["detail"]


async def test_an_enum_with_no_values_is_refused() -> None:
    _tid, agent_id, token = await _tenant()
    app = _app()
    bad = [
        {
            "key": "urgency",
            "label": "Urgency",
            "type": "enum",
            "enum_values": None,
            "reason": "",
            "required": False,
        },
    ]
    async with _client(app) as http:
        r = await http.put(
            f"/v1/agents/{agent_id}/extraction-schema",
            json={"fields": bad},
            headers=_bearer(token),
        )
    # Rejected at request parse by `ExtractionField._enum_needs_values`.
    assert r.status_code == 422


async def test_the_save_writes_an_audit_entry_of_the_shape_not_the_values() -> None:
    tenant_id, agent_id, token = await _tenant()
    app = _app()
    async with _client(app) as http:
        r = await http.put(
            f"/v1/agents/{agent_id}/extraction-schema",
            json={"fields": _TWO_FIELDS},
            headers=_bearer(token),
        )
        assert r.status_code == 200

    # The audit row is written. `audit_log` carries NO `summary` column by design — the
    # summary reaches the log stream, not the hash-chained row (compliance/audit.py) — so
    # the DB assertion is the action. The "shape, never a value" guarantee is structural:
    # `_audit_summary` builds only {version, changed, field_keys}, so no field VALUE can
    # reach either the row or the log (asserted directly below via the summary builder).
    async with tenant_session(tenant_id) as session:
        action = (
            await session.execute(
                text(
                    "SELECT action FROM audit_log WHERE object_id = :a "
                    "AND action = 'agent.extraction_schema_set' LIMIT 1"
                ),
                {"a": str(agent_id)},
            )
        ).scalar_one_or_none()
    assert action == "agent.extraction_schema_set"

    summary = _audit_summary(
        ExtractionSchemaOut(
            fields=[ExtractionField.model_validate(f) for f in _TWO_FIELDS],
            version=2,
            changed=True,
        )
    )
    assert summary["field_keys"] == ["budget", "area"]
    # No reason text, no label — only the shape.
    assert "how much they can spend" not in str(summary)


async def test_a_neighbours_agent_is_a_404_for_an_owner() -> None:
    _a_tid, agent_a, _a_token = await _tenant()
    _b_tid, _agent_b, token_b = await _tenant()
    app = _app()
    async with _client(app) as http:
        r = await http.put(
            f"/v1/agents/{agent_a}/extraction-schema",
            json={"fields": _TWO_FIELDS},
            headers=_bearer(token_b),
        )
    assert r.status_code == 404


async def test_an_operator_can_edit_a_named_tenants_agent() -> None:
    tenant_id, agent_id, _owner = await _tenant()
    admin_token = await _make_admin()
    app = _app()
    async with _client(app) as http:
        r = await http.put(
            f"/v1/admin/tenants/{tenant_id}/agents/{agent_id}/extraction-schema",
            json={"fields": _TWO_FIELDS},
            headers=_bearer(admin_token),
        )
    assert r.status_code == 200, r.text
    assert r.json()["changed"] is True
    async with tenant_session(tenant_id) as session:
        action = (
            await session.execute(
                text(
                    "SELECT action FROM audit_log WHERE object_id = :a "
                    "AND action = 'admin.agent_extraction_schema_set' LIMIT 1"
                ),
                {"a": str(agent_id)},
            )
        ).scalar_one_or_none()
    assert action == "admin.agent_extraction_schema_set"


async def test_an_agent_with_no_schema_reads_empty_and_first_save_is_version_one() -> None:
    # A fresh agent minted without a schema (extraction_schema_id NULL) — the passthrough
    # state. GET reports version 0 / no variables; the first save becomes version 1.
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
    app = _app()
    async with _client(app) as http:
        got = await http.get(f"/v1/agents/{bare_agent}/extraction-schema", headers=_bearer(token))
        assert got.status_code == 200
        assert got.json() == {"fields": [], "version": 0, "changed": False}
        put = await http.put(
            f"/v1/agents/{bare_agent}/extraction-schema",
            json={"fields": _TWO_FIELDS},
            headers=_bearer(token),
        )
        assert put.status_code == 200, put.text
        assert put.json()["version"] == 1
        assert put.json()["changed"] is True


async def test_get_on_an_unknown_agent_is_404() -> None:
    _tid, _agent, token = await _tenant()
    app = _app()
    async with _client(app) as http:
        r = await http.get(f"/v1/agents/{uuid.uuid4()}/extraction-schema", headers=_bearer(token))
    assert r.status_code == 404


def _variable(key: str, **over: object) -> dict[str, object]:
    """One well-formed variable, so a size test differs from a valid one in ONE way."""
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


async def _put(agent_id: uuid.UUID, token: str, fields: list[dict[str, object]]) -> object:
    app = _app()
    async with _client(app) as http:
        return await http.put(
            f"/v1/agents/{agent_id}/extraction-schema",
            json={"fields": fields},
            headers=_bearer(token),
        )


async def test_a_variable_list_past_the_ceiling_is_refused() -> None:
    """The list length itself. Without the `max_length` this is a 200 and the agent now
    carries a prompt that is paid for on every extraction it ever runs."""
    _tid, agent_id, token = await _tenant()
    too_many = [_variable(f"f{i}") for i in range(MAX_EXTRACTION_FIELDS + 1)]
    refused = await _put(agent_id, token, too_many)
    assert refused.status_code == 422  # type: ignore[attr-defined]

    # And the ceiling itself saves, so the bound is a ceiling and not an off-by-one.
    at_the_line = await _put(
        agent_id, token, [_variable(f"f{i}") for i in range(MAX_EXTRACTION_FIELDS)]
    )
    assert at_the_line.status_code == 200  # type: ignore[attr-defined]


async def test_an_oversized_reason_is_refused_and_names_the_variable() -> None:
    """The `reason` is the instruction the model gets on every call, so its size is a
    per-call cost. The message has to name WHICH variable — a generic 422 against a form
    of fifty rows is not something anybody can act on."""
    _tid, agent_id, token = await _tenant()
    response = await _put(
        agent_id, token, [_variable("symptom", reason="x" * (MAX_REASON_LEN + 1))]
    )
    assert response.status_code == 422  # type: ignore[attr-defined]
    body = response.json()  # type: ignore[attr-defined]
    assert body["type"].endswith("/extraction_field_reason_too_long")
    assert "symptom" in body["detail"]


async def test_an_oversized_label_is_refused() -> None:
    """A label is a Leads column header and a CSV header cell."""
    _tid, agent_id, token = await _tenant()
    response = await _put(agent_id, token, [_variable("symptom", label="L" * (MAX_LABEL_LEN + 1))])
    assert response.status_code == 422  # type: ignore[attr-defined]
    assert response.json()["type"].endswith(  # type: ignore[attr-defined]
        "/extraction_field_label_too_long"
    )


async def test_too_many_choices_on_one_variable_are_refused() -> None:
    """An enum's values reach the prompt, the facet panel and the column chooser."""
    _tid, agent_id, token = await _tenant()
    response = await _put(
        agent_id,
        token,
        [
            _variable(
                "urgency",
                type="enum",
                enum_values=[f"v{i}" for i in range(MAX_ENUM_VALUES + 1)],
            )
        ],
    )
    assert response.status_code == 422  # type: ignore[attr-defined]
    assert response.json()["type"].endswith(  # type: ignore[attr-defined]
        "/extraction_field_choices_invalid"
    )
