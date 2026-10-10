"""Business-neutral lead details (founder decision 15, 10 Oct 2026).

What is under test:

1. **The core.** Every lead carries a fixed set whatever the business; it is composed in on
   read, never stored, and no stored copy can shadow it.
2. **The business types.** One list, no clinic default, a standard set per known type with
   none of its keys colliding with the core, a fixed Leads column or an extraction output.
3. **The one AI draft.** Queued for a custom business only, never twice, landing only on
   agents that have no fields of their own, and tolerant of a malformed model answer.
4. **Moving a business.** Replacing fields is a new version per agent; the old values stay
   readable under their old names.
5. **Tenancy (hard rule 1).** One business never sees another's draft.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, get_args

import pytest
from apps.api.admin import service as admin_service
from apps.api.admin.routes import CreateOrgIn, Vertical
from apps.api.agents import lead_fields
from apps.api.agents.extraction_routes import validate_fields, write_schema
from apps.api.agents.lead_fields_routes import router as lead_fields_router
from apps.api.core.errors import ProblemError, install_error_handlers
from apps.api.core.rbac import assert_policy_registry_complete
from apps.api.crm.captured import captured_fields
from apps.api.crm.columns import FIXED_KEYS
from apps.api.db.session import tenant_session, untenanted_session
from apps.workers import lead_fields_draft
from calevate_shared.extraction import ExtractionField, is_phone_field
from calevate_shared.lead_fields import (
    CORE_KEYS,
    CORE_LEAD_FIELDS,
    NEED_KEY,
    OUTPUT_KEYS,
    business_only,
    with_core,
)
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from scripts.seed import BUSINESS_TYPE_LABELS, VERTICAL_TEMPLATES
from sqlalchemy import text
from tests.conftest import accept_agreements

CLINICAL = re.compile(
    r"\b(?:clinic|hospital|patients?|doctors?|dentists?|dental|appointments?|symptoms?)\b", re.I
)

# --- 1. the core ------------------------------------------------------------------------


def test_the_core_comes_first_and_a_stored_copy_cannot_shadow_it() -> None:
    stored = [
        {"key": "need", "label": "Old need", "type": "text"},
        {"key": "product", "label": "Product", "type": "text"},
    ]
    composed = with_core(stored)
    assert [f.key for f in composed] == [*(f.key for f in CORE_LEAD_FIELDS), "product"]
    assert next(f for f in composed if f.key == "need").label == "What they want"
    assert [f.key for f in business_only(stored)] == ["product"]
    assert with_core(None) == list(CORE_LEAD_FIELDS)


def test_the_core_names_what_the_caller_wants_and_requires_nothing() -> None:
    assert NEED_KEY in CORE_KEYS
    assert "name" in CORE_KEYS
    # A silent or wrong-number call correctly captures nothing; a required core field would
    # mark every such call's extraction invalid.
    assert not any(f.required for f in CORE_LEAD_FIELDS)
    # Only the other-number field may hold a phone number.
    assert [f.key for f in CORE_LEAD_FIELDS if is_phone_field(f)] == ["other_number"]
    assert not CORE_KEYS & OUTPUT_KEYS


# --- 2. the business types --------------------------------------------------------------


def test_one_list_of_business_types_and_no_clinic_default() -> None:
    assert list(get_args(Vertical)) == list(BUSINESS_TYPE_LABELS)
    assert set(BUSINESS_TYPE_LABELS) == {*VERTICAL_TEMPLATES, "custom"}
    assert next(iter(BUSINESS_TYPE_LABELS)) != "clinic"
    assert CreateOrgIn.model_fields["vertical_template"].default == "custom"
    for new in ("retail", "local_services", "automobile"):
        assert new in VERTICAL_TEMPLATES


@pytest.mark.parametrize("vertical", sorted(VERTICAL_TEMPLATES))
def test_every_standard_set_is_its_own_and_collides_with_nothing(vertical: str) -> None:
    fields = [ExtractionField.model_validate(f) for f in VERTICAL_TEMPLATES[vertical]]
    keys = {f.key for f in fields}
    assert not keys & CORE_KEYS, "a standard set repeats the core"
    assert not keys & FIXED_KEYS
    assert not keys & OUTPUT_KEYS
    if vertical != "clinic":
        for field in fields:
            assert not CLINICAL.search(f"{field.key} {field.label} {field.reason}"), field.key
    if vertical in ("retail", "local_services", "automobile"):
        # A registration plate or an order is not a phone number; a phone field would flag
        # every value as "not a standard Indian mobile".
        assert not any(is_phone_field(f) for f in fields)


def test_a_custom_business_starts_with_the_core_only() -> None:
    assert admin_service.starting_fields("custom") == []
    assert lead_fields.standard_fields("custom") == []
    assert lead_fields.business_type_label(None) == "Something else"
    assert lead_fields.business_type_label("retail") == "Shop, food or produce"


# --- 3a. the draft, without a database --------------------------------------------------


def test_the_draft_prompt_forbids_repeating_the_core_and_sensitive_details() -> None:
    prompt = lead_fields_draft.SYSTEM_PROMPT
    for field in CORE_LEAD_FIELDS:
        assert field.label.lower() in prompt
    assert "Never repeat" in prompt
    for word in ("phone number", "Aadhaar", "caste", "Do not invent"):
        assert word in prompt


def test_a_model_answer_is_cleaned_into_fields_the_editor_accepts() -> None:
    raw: dict[str, Any] = {
        "fields": [
            {"label": "Product", "type": "text", "reason": "what", "required": True},
            {"label": "What they want", "type": "text", "reason": "dup of core"},
            {"label": "Order number", "type": "text", "reason": "a phone-shaped field"},
            {"label": "Pack size", "type": "enum", "choices": ["1 kg"], "required": True},
            {"label": "Product", "type": "text", "reason": "duplicate label"},
            {"label": "Organic", "type": "bool", "reason": "asked for organic"},
            {"label": "Summary", "type": "text"},
            {"label": "", "type": "text"},
            {"label": "Weird", "type": "json"},
            "not an object",
            *({"label": f"Extra {n}", "type": "text"} for n in range(10)),
        ]
    }
    fields = lead_fields_draft.fields_from_model(raw)
    keys = [f.key for f in fields]
    assert keys[:3] == ["product", "pack_size", "organic"]
    assert len(fields) == lead_fields_draft.MAX_DRAFTED_FIELDS
    assert "summary" not in keys and "order_number" not in keys
    # An enum with one choice is not a choice; only the first required survives.
    assert fields[1].type == "text" and fields[1].enum_values is None
    assert [f.key for f in fields if f.required] == ["product"]
    assert lead_fields_draft.fields_from_model({"fields": "nope"}) == []


# --- DB helpers ---------------------------------------------------------------------------


def _app() -> FastAPI:
    application = FastAPI()
    install_error_handlers(application)
    application.include_router(lead_fields_router)
    assert_policy_registry_complete(application)
    return application


async def _tenant(vertical: str, name: str = "Raghava Organics") -> tuple[uuid.UUID, str]:
    created = await admin_service.create_organization(
        name=name,
        slug=f"leadf-{uuid.uuid4().hex[:8]}",
        vertical_template=vertical,
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    await accept_agreements(tenant_id)
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
    return tenant_id, f"dev:client:{user_id}"


async def _call(method: str, path: str, token: str, body: Any = None) -> tuple[int, Any]:
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://api") as http:
        response = await http.request(
            method, path, json=body, headers={"Authorization": f"Bearer {token}"}
        )
    return response.status_code, response.json()


async def _business_keys(tenant_id: uuid.UUID) -> list[list[str]]:
    async with tenant_session(tenant_id) as session:
        agents = await lead_fields.agents_with_fields(session)
    return [[f.key for f in a["fields"]] for a in agents]


DRAFTED = [
    ExtractionField(key="produce", label="Produce", type="text", reason="what", required=True),
    ExtractionField(key="kilos", label="Kilos", type="number", reason="how much"),
]


async def _run_worker(tenant_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch) -> str:
    async def fake_draft(description: str) -> tuple[list[ExtractionField], None, None]:
        assert "Raghava" in description
        return list(DRAFTED), None, None

    monkeypatch.setattr(lead_fields_draft, "_draft", fake_draft)
    return await lead_fields_draft.draft_lead_fields({}, {"tenant_id": str(tenant_id)})


# --- 3b. the draft, end to end ------------------------------------------------------------


@pytest.mark.rls
async def test_a_custom_business_is_drafted_once_and_never_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, token = await _tenant("custom")
    code, body = await _call("GET", "/v1/lead-fields", token)
    assert code == 200, body
    assert body["can_draft"] is True and body["draft"] is None
    assert [f["key"] for f in body["core_fields"]] == [f.key for f in CORE_LEAD_FIELDS]
    assert body["agents"][0]["business_fields"] == []

    code, body = await _call("POST", "/v1/lead-fields/draft", token)
    assert code == 202, body
    assert body["draft"]["status"] == "queued"
    async with tenant_session(tenant_id) as session:
        queued = (
            await session.execute(
                text(
                    "SELECT count(*) FROM outbox_messages WHERE job = :job "
                    "AND payload->>'tenant_id' = :tid"
                ),
                {"job": lead_fields.DRAFT_JOB, "tid": str(tenant_id)},
            )
        ).scalar()
    assert queued == 1
    # Asking again while it is queued is the same draft, not a second one.
    code, body = await _call("POST", "/v1/lead-fields/draft", token)
    assert code == 202 and body["draft"]["status"] == "queued"

    assert await _run_worker(tenant_id, monkeypatch) == "done"
    assert await _business_keys(tenant_id) == [["produce", "kilos"]]
    # A second delivery of the same message finds nothing to claim.
    assert await _run_worker(tenant_id, monkeypatch) == "not_queued"

    code, body = await _call("GET", "/v1/lead-fields", token)
    assert body["draft"]["status"] == "done" and body["can_draft"] is False
    code, body = await _call("POST", "/v1/lead-fields/draft", token)
    assert code == 409, body


@pytest.mark.rls
async def test_a_draft_never_overwrites_fields_somebody_already_chose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _ = await _tenant("custom")
    own = [ExtractionField(key="flavour", label="Flavour", type="text")]
    async with tenant_session(tenant_id) as session:
        agent_id = (await lead_fields.agents_with_fields(session))[0]["id"]
        await write_schema(session, agent_id=agent_id, fields=own)
        await lead_fields.request_draft(session, tenant_id=tenant_id, requested_by=None)
    assert await _run_worker(tenant_id, monkeypatch) == "done"
    assert await _business_keys(tenant_id) == [["flavour"]]
    # The drafted set is still what a new agent of this business starts with.
    async with tenant_session(tenant_id) as session:
        start = await lead_fields.starting_business_fields(
            session, tenant_id=tenant_id, vertical="custom"
        )
    assert [f.key for f in start] == ["produce", "kilos"]


@pytest.mark.rls
async def test_a_failed_draft_may_be_asked_for_again(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, _ = await _tenant("custom")
    async with tenant_session(tenant_id) as session:
        await lead_fields.request_draft(session, tenant_id=tenant_id, requested_by=None)

    async def nothing(description: str) -> tuple[list[ExtractionField], None, None]:
        return [], None, None

    monkeypatch.setattr(lead_fields_draft, "_draft", nothing)
    assert await lead_fields_draft.draft_lead_fields({}, {"tenant_id": str(tenant_id)}) == "failed"
    async with tenant_session(tenant_id) as session:
        draft = await lead_fields.read_draft(session, tenant_id=tenant_id)
        assert draft is not None and draft.status == "failed"
        assert draft.error_code == "no_provider"
        again = await lead_fields.request_draft(session, tenant_id=tenant_id, requested_by=None)
    assert again.status == "queued"


@pytest.mark.rls
async def test_a_known_business_type_is_never_drafted() -> None:
    tenant_id, token = await _tenant("retail")
    assert await _business_keys(tenant_id) == [[f["key"] for f in VERTICAL_TEMPLATES["retail"]]]
    code, body = await _call("GET", "/v1/lead-fields", token)
    assert body["can_draft"] is False and body["has_standard_set"] is True
    assert body["business_type_label"] == "Shop, food or produce"
    code, body = await _call("POST", "/v1/lead-fields/draft", token)
    assert code == 422, body
    async with tenant_session(tenant_id) as session:
        assert not await lead_fields.maybe_request_draft(
            session, tenant_id=tenant_id, requested_by=None
        )


# --- 4. moving a business to new fields ----------------------------------------------------


@pytest.mark.rls
async def test_moving_a_clinic_set_up_shop_keeps_its_old_answers_readable() -> None:
    tenant_id, _ = await _tenant("clinic")
    async with tenant_session(tenant_id) as session:
        agent = (await lead_fields.agents_with_fields(session))[0]
        old_version = agent["version"]
        await session.execute(
            text("UPDATE organizations SET vertical_template = 'retail' WHERE id = :tid"),
            {"tid": tenant_id},
        )
        written = await lead_fields.replace_business_fields(
            session, fields=lead_fields.standard_fields("retail")
        )
        assert [w.changed for w in written] == [True]
        assert written[0].version == old_version + 1
        captured = await captured_fields(
            session,
            agent_id=agent["id"],
            schema_version=old_version,
            data={"symptom": "fever", "need": "chilli", "gone_key": "x"},
        )
    by_key = {c.key: c for c in captured}
    assert captured[0].key == "name" and by_key["need"].label == "What they want"
    assert by_key["need"].value == "chilli" and by_key["need"].core
    # The clinic's field, labelled as it was captured, and marked as no longer captured.
    assert by_key["symptom"].label == "Symptom / reason" and by_key["symptom"].current is False
    assert by_key["gone_key"].label == "Gone key"
    assert await _business_keys(tenant_id) == [[f["key"] for f in VERTICAL_TEMPLATES["retail"]]]


@pytest.mark.rls
async def test_the_core_cannot_be_saved_as_a_business_field() -> None:
    tenant_id, _ = await _tenant("custom")
    async with tenant_session(tenant_id) as session:
        agent_id = (await lead_fields.agents_with_fields(session))[0]["id"]
        result = await write_schema(
            session,
            agent_id=agent_id,
            fields=[*CORE_LEAD_FIELDS, ExtractionField(key="size", label="Size", type="text")],
        )
    assert [f.key for f in result.fields] == ["size"]
    assert [f.key for f in result.core_fields] == [f.key for f in CORE_LEAD_FIELDS]
    with pytest.raises(ProblemError) as refused:
        validate_fields([ExtractionField(key="headline", label="Headline", type="text")])
    assert refused.value.code == "extraction_field_reserved_key"


# --- 5. tenancy -----------------------------------------------------------------------------


@pytest.mark.rls
async def test_one_business_never_sees_anothers_draft() -> None:
    tenant_a, _ = await _tenant("custom")
    async with tenant_session(tenant_a) as session:
        await lead_fields.request_draft(session, tenant_id=tenant_a, requested_by=None)
    tenant_b, _ = await _tenant("custom")
    async with tenant_session(tenant_b) as session:
        rows = (
            await session.execute(
                text("SELECT count(*) FROM lead_field_drafts WHERE tenant_id = :a"),
                {"a": tenant_a},
            )
        ).scalar()
        assert rows == 0
        assert await lead_fields.read_draft(session, tenant_id=tenant_a) is None
