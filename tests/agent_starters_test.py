"""Pick a job, get a ready agent (D-705).

WHAT IS UNDER TEST:

1. **Every starter is a valid script.** Each business type and job compiles through the
   builder's own compiler, round-trips through `CallScript`, and the full engine prompt
   built from it still carries the platform's truthful-answer floor.
2. **The wording rules hold.** No clinic word outside the clinic's starters (the web
   copy guard's regex), no vendor name, no disclosure or recording sentence (the platform
   adds those), and every outbound starter handles "stop calling me".
3. **Creating with a starter** yields a draft with a staged script version (structure and
   compiled body together) and the business type's captured details, direction set by the
   job; a contradicting direction is refused and creates nothing; without a starter the
   create is unchanged.
4. **The preview** answers for the caller's own account only, and a neighbour's agent's
   script and schema rows are invisible (hard rule 1).
"""

from __future__ import annotations

import re
import uuid
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import starters
from apps.api.agents.routes import router as agents_router
from apps.api.compliance.disclosure import (
    AI_DISCLOSURE_TEMPLATES,
    CALLER_MEMORY_NOTICE_TEMPLATES,
    RECORDING_NOTICE_TEMPLATES,
)
from apps.api.copilot.identity import VENDOR_WORDS
from apps.api.core.errors import ProblemError, install_error_handlers
from apps.api.core.rbac import assert_policy_registry_complete
from apps.api.db.session import tenant_session, untenanted_session
from calevate_shared.call_script import (
    STANDARD_VARIABLES,
    CallScript,
    compile_call_script,
    extract_variable_names,
)
from calevate_shared.engine import (
    CONFIDENTIALITY_MARKER,
    TRUTHFUL_ANSWER_MARKER,
    AgentConfig,
    compose_engine_prompt,
)
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from scripts.seed import VERTICAL_TEMPLATES
from sqlalchemy import text
from tests.conftest import accept_agreements

#: `apps/web/tests/genericCopyGuard.test.ts`'s CLINIC_ONLY, plus the Python copy test's
#: "symptom": words that belong to the clinic business type only.
CLINIC_ONLY = re.compile(
    r"\b(?:clinics?|hospitals?|patients?|doctors?|dentists?|dental|appointments?|symptoms?)\b",
    re.IGNORECASE,
)

#: The assistant's banned names plus the voice, telephony and engine vendors (D-679).
_VENDORS = (
    *VENDOR_WORDS,
    "thinnest",
    "thinnestai",
    "gnani",
    "cartesia",
    "pipecat",
    "vobiz",
    "plivo",
    "bolna",
    "exotel",
    "twilio",
)
VENDOR = re.compile(rf"\b(?:{'|'.join(_VENDORS)})\b", re.IGNORECASE)

#: Disclosure-shaped words the platform owns; a starter must leave them to it.
DISCLOSURE_WORDS = re.compile(
    r"\b(?:AI|artificial|robot|bot|recorded|recording|human being)\b", re.IGNORECASE
)

ALL_VERTICALS = {*VERTICAL_TEMPLATES, starters.NEUTRAL_VERTICAL}


# --- 1 and 2: the catalogue ------------------------------------------------------------


def test_the_catalogue_covers_every_business_type_and_job() -> None:
    assert set(starters.CATALOGUE) == {
        (vertical, job) for vertical in ALL_VERTICALS for job in starters.STARTER_JOBS
    }


@pytest.mark.parametrize("key", sorted(starters.CATALOGUE))
def test_every_starter_compiles_and_keeps_the_platform_floor(key: tuple[str, str]) -> None:
    starter = starters.CATALOGUE[key]  # type: ignore[index]
    script = starter.call_script(business="Acme Traders")
    assert CallScript.model_validate(script.model_dump(mode="json")) == script
    assert not script.is_raw
    body = compile_call_script(script)
    assert "[OPENING]\nHello" in body and "Acme Traders" in body
    assert "[TASK FLOW]" in body and "[FAQ]" in body
    assert "{business}" not in body
    assert set(extract_variable_names(body)) <= {key for key, _ in STANDARD_VARIABLES}
    engine_prompt = compose_engine_prompt(
        AgentConfig(
            tenant_id="t",
            agent_id="a",
            name=starter.name_suggestion,
            direction=starters.JOB_DIRECTION[starter.job],
            system_prompt=body,
            opening_line="",
            call_is_recorded=True,
        )
    )
    assert TRUTHFUL_ANSWER_MARKER in engine_prompt


@pytest.mark.parametrize("key", sorted(starters.CATALOGUE))
def test_starter_wording_rules(key: tuple[str, str]) -> None:
    vertical, job = key
    starter = starters.CATALOGUE[key]  # type: ignore[index]
    authored = starter.authored_text()
    if vertical != "clinic":
        assert not CLINIC_ONLY.search(authored), CLINIC_ONLY.search(authored)
    assert not VENDOR.search(authored), VENDOR.search(authored)
    assert not DISCLOSURE_WORDS.search(authored), DISCLOSURE_WORDS.search(authored)
    for marker in (TRUTHFUL_ANSWER_MARKER, CONFIDENTIALITY_MARKER):
        assert marker not in authored
    for templates in (
        AI_DISCLOSURE_TEMPLATES,
        RECORDING_NOTICE_TEMPLATES,
        CALLER_MEMORY_NOTICE_TEMPLATES,
    ):
        for template in templates.values():
            for fragment in template.split("{business}"):
                if len(fragment.strip()) > 10:
                    assert fragment.strip() not in authored
    if job == "call_leads":
        assert "do-not-call tool" in authored
        assert "Do not push" in authored


def test_the_clinic_keeps_its_own_words_and_the_others_their_booking() -> None:
    assert starters.TRADES["clinic"].booking == "an appointment"
    assert starters.TRADES["real_estate"].booking == "a site visit"
    assert starters.TRADES["education"].booking == "a counselling session"
    assert starters.TRADES[starters.NEUTRAL_VERTICAL].booking == "a booking"


def test_captured_details_are_the_onboarding_fields() -> None:
    for vertical in ALL_VERTICALS:
        assert starters.captured_fields(vertical) is admin_service.starting_fields(vertical)


def test_an_unknown_business_type_gets_the_neutral_starter() -> None:
    for unknown in (None, "", "bakery", "constructor"):
        assert starters.vertical_of(unknown) == starters.NEUTRAL_VERTICAL
        assert starters.starter_for(unknown, "answer_calls").vertical == "custom"


def test_the_job_sets_the_direction() -> None:
    assert starters.direction_for("answer_calls", None) == "inbound"
    assert starters.direction_for("call_leads", "outbound") == "outbound"
    with pytest.raises(ProblemError) as refused:
        starters.direction_for("call_leads", "inbound")
    assert refused.value.code == "starter_direction_mismatch"
    with pytest.raises(ProblemError):
        starters.direction_for("answer_calls", "both")


# --- 3 and 4: creation and the preview, against the database ---------------------------


def _app() -> FastAPI:
    application = FastAPI()
    install_error_handlers(application)
    application.include_router(agents_router)
    assert_policy_registry_complete(application)
    return application


def _code(body: dict[str, Any]) -> str:
    return str(body["type"]).rsplit("/", 1)[-1]


async def _tenant(vertical: str, name: str) -> tuple[uuid.UUID, str]:
    """(tenant_id, owner bearer) for a fresh account of this business type."""
    created = await admin_service.create_organization(
        name=name,
        slug=f"starter-{uuid.uuid4().hex[:8]}",
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


async def _create(token: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://api") as http:
        response = await http.post(
            "/v1/agents", json=body, headers={"Authorization": f"Bearer {token}"}
        )
    return response.status_code, response.json()


async def _starters(token: str, query: str = "") -> tuple[int, dict[str, Any]]:
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://api") as http:
        response = await http.get(
            f"/v1/agents/starters{query}", headers={"Authorization": f"Bearer {token}"}
        )
    return response.status_code, response.json()


async def _agent_rows(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> Any:
    async with tenant_session(tenant_id) as session:
        return (
            await session.execute(
                text(
                    "SELECT a.direction, a.status, a.system_prompt_id, a.live_prompt_id, "
                    "pv.body, pv.structured_script, pv.version, es.fields "
                    "FROM agents a "
                    "LEFT JOIN prompt_versions pv ON pv.id = a.system_prompt_id "
                    "LEFT JOIN extraction_schemas es ON es.id = a.extraction_schema_id "
                    "WHERE a.id = :aid"
                ),
                {"aid": agent_id},
            )
        ).first()


@pytest.mark.rls
async def test_creating_with_a_starter_writes_a_draft_script_and_captured_details() -> None:
    tenant_id, token = await _tenant("real_estate", "Skyline Homes")
    code, body = await _create(token, {"name": "Front desk", "starter": "answer_calls"})
    assert code == 201, body
    assert body["status"] == "draft"
    assert body["direction"] == "inbound"
    row = await _agent_rows(tenant_id, uuid.UUID(body["id"]))
    assert row is not None
    direction, status, draft_id, live_id, stored_body, structured, version, fields = row
    assert (direction, status, version) == ("inbound", "draft", 1)
    # A draft agent has nothing live to protect, so the version is applied to both pointers
    # exactly as a builder save on a draft is; no caller hears it until it is published.
    assert draft_id is not None and draft_id == live_id
    expected = starters.starter_for("real_estate", "answer_calls").call_script(
        business="Skyline Homes"
    )
    assert CallScript.model_validate(structured) == expected
    assert stored_body == compile_call_script(expected)
    assert [f["key"] for f in fields] == [f["key"] for f in VERTICAL_TEMPLATES["real_estate"]]


@pytest.mark.rls
async def test_call_my_leads_makes_an_outbound_agent_without_being_told() -> None:
    tenant_id, token = await _tenant("custom", "Sri Traders")
    code, body = await _create(token, {"name": "Follow-ups", "starter": "call_leads"})
    assert code == 201, body
    assert body["direction"] == "outbound"
    row = await _agent_rows(tenant_id, uuid.UUID(body["id"]))
    assert row is not None
    assert "do-not-call tool" in row[4]
    assert not CLINIC_ONLY.search(row[4])
    assert [f["key"] for f in row[7]] == ["need", "preferred_time"]

    code, body = await _create(
        token, {"name": "Also fine", "starter": "call_leads", "direction": "outbound"}
    )
    assert code == 201, body


@pytest.mark.rls
async def test_a_direction_that_contradicts_the_job_is_refused_and_creates_nothing() -> None:
    tenant_id, token = await _tenant("education", "Vidya Centre")
    async with tenant_session(tenant_id) as session:
        before = (await session.execute(text("SELECT count(*) FROM agents"))).scalar_one()
    code, body = await _create(
        token, {"name": "Wrong way", "starter": "answer_calls", "direction": "outbound"}
    )
    assert code == 422, body
    assert _code(body) == "starter_direction_mismatch", body
    code, body = await _create(token, {"name": "Unknown", "starter": "sell_things"})
    assert code == 422, body
    async with tenant_session(tenant_id) as session:
        after = (await session.execute(text("SELECT count(*) FROM agents"))).scalar_one()
    assert after == before


@pytest.mark.rls
async def test_without_a_starter_the_create_is_unchanged() -> None:
    tenant_id, token = await _tenant("clinic", "Sunrise Care")
    code, body = await _create(token, {"name": "Blank", "direction": "outbound"})
    assert code == 201, body
    assert body["direction"] == "outbound"
    row = await _agent_rows(tenant_id, uuid.UUID(body["id"]))
    assert row is not None
    assert row[2] is None, "an agent created without a starter came with a script"
    assert row[7] is None


@pytest.mark.rls
async def test_the_preview_is_the_callers_own_business_type() -> None:
    _, token = await _tenant("real_estate", "Skyline Homes")
    code, body = await _starters(token)
    assert code == 200, body
    assert body["vertical"] == "real_estate"
    assert [s["job"] for s in body["starters"]] == ["answer_calls", "call_leads"]
    receptionist = body["starters"][0]
    assert receptionist["direction"] == "inbound"
    assert "Skyline Homes" in receptionist["opening_line"]
    assert receptionist["step_titles"][3] == "Offer a site visit"
    assert receptionist["captured_details"] == [
        f["label"] for f in VERTICAL_TEMPLATES["real_estate"]
    ]

    code, one = await _starters(token, "?job=call_leads")
    assert code == 200, one
    assert [s["job"] for s in one["starters"]] == ["call_leads"]
    assert one["starters"][0]["direction"] == "outbound"

    # No request parameter names another business type: a stray one is ignored.
    code, same = await _starters(token, "?vertical=clinic")
    assert code == 200 and same["vertical"] == "real_estate"
    code, refused = await _starters(token, "?job=sell_things")
    assert code == 422, refused


@pytest.mark.rls
async def test_a_neighbour_sees_none_of_the_starter_rows() -> None:
    tenant_a, token_a = await _tenant("clinic", "Alpha Care")
    tenant_b, token_b = await _tenant("custom", "Beta Traders")
    code, body = await _create(token_a, {"name": "Alpha desk", "starter": "answer_calls"})
    assert code == 201, body
    agent_id = uuid.UUID(body["id"])
    async with tenant_session(tenant_b) as session:
        versions = (
            await session.execute(
                text("SELECT count(*) FROM prompt_versions WHERE agent_id = :aid"),
                {"aid": agent_id},
            )
        ).scalar_one()
        schemas = (
            await session.execute(
                text("SELECT count(*) FROM extraction_schemas WHERE agent_id = :aid"),
                {"aid": agent_id},
            )
        ).scalar_one()
    assert (versions, schemas) == (0, 0)
    async with tenant_session(tenant_a) as session:
        own = (
            await session.execute(
                text("SELECT count(*) FROM prompt_versions WHERE agent_id = :aid"),
                {"aid": agent_id},
            )
        ).scalar_one()
    assert own == 1
    code, preview = await _starters(token_b)
    assert code == 200, preview
    assert preview["vertical"] == "custom"
    assert all("Alpha Care" not in s["opening_line"] for s in preview["starters"])
    assert all("Beta Traders" in s["opening_line"] for s in preview["starters"])
