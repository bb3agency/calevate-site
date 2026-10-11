"""No account is a clinic unless somebody chose it (D-722, founder 11 Oct 2026).

What is under test:

1. **No default.** The operator wizard and signup refuse a body with no business type.
2. **Unconfirmed accounts run neutral.** An account given `clinic` by default loses the clinic
   lead details and the script that asked for them, keeps the caller-memory refusal, and
   gets ONE AI suggestion that changes nothing by itself.
3. **Confirming applies the type.** The type's lead details land on agents that have none or
   still carry the clinic default; details somebody chose are kept.
4. **Raghava's repair.** A shop set to its type gets the shop's details in place of the
   clinic default.
5. **Tenancy (hard rule 1).** The read and the confirm act on the named client only.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.admin import business_type
from apps.api.admin import service as admin_service
from apps.api.admin.routes import CreateOrgIn
from apps.api.agents import lead_fields
from apps.api.agents.extraction_routes import write_schema
from apps.api.agents.starters import apply_starter
from apps.api.compliance.caller_memory import memory_enabled
from apps.api.crm import assist as crm_assist
from apps.api.db.session import admin_session, tenant_session
from apps.api.main import app
from apps.api.tenancy.signup_routes import SignupIn
from apps.workers import business_type as worker
from apps.workers.script_assist import JsonAnswer
from calevate_shared.extraction import ExtractionField
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from scripts.seed import VERTICAL_TEMPLATES
from sqlalchemy import text

CLINIC_KEYS = [f["key"] for f in VERTICAL_TEMPLATES["clinic"]]
RETAIL_KEYS = [f["key"] for f in VERTICAL_TEMPLATES["retail"]]


# --- 1. no default ----------------------------------------------------------------------


def test_every_create_path_requires_a_business_type() -> None:
    with pytest.raises(ValidationError):
        CreateOrgIn.model_validate({"name": "Raghava Organics", "owner": {"email": "o@x.in"}})
    with pytest.raises(ValidationError):
        SignupIn.model_validate({"business_name": "Raghava Organics"})
    assert (
        CreateOrgIn.model_validate(
            {
                "name": "Raghava Organics",
                "owner": {"email": "o@x.in"},
                "vertical_template": "retail",
            }
        ).vertical_template
        == "retail"
    )


# --- unit: what the worker recognises -------------------------------------------------------


def test_the_clinic_default_is_recognised_whole_or_trimmed_and_nothing_else() -> None:
    def fields(*keys: str) -> list[ExtractionField]:
        return [ExtractionField(key=k, label=k.title(), type="text") for k in keys]

    assert worker.carries_clinic_default(fields(*CLINIC_KEYS))
    assert worker.carries_clinic_default(fields("symptom", "insurance"))
    assert not worker.carries_clinic_default([])
    assert not worker.carries_clinic_default(fields("symptom", "chilli_variety"))


def test_a_suggestion_names_a_type_we_offer_or_nothing() -> None:
    assert worker.suggestion_from_model(
        {"business_type": "retail", "reason": " sells  chilli "}
    ) == (
        "retail",
        "sells chilli",
    )
    assert worker.suggestion_from_model({"business_type": "bakery", "reason": "x"}) is None
    assert worker.suggestion_from_model({}) is None


def test_the_suggestion_prompt_offers_every_type_and_no_default() -> None:
    for key in VERTICAL_TEMPLATES:
        assert key in worker.SUGGEST_INSTRUCTION
    assert "custom" in worker.SUGGEST_INSTRUCTION


# --- helpers ------------------------------------------------------------------------------


async def _tenant(vertical: str, name: str = "Raghava Organics") -> uuid.UUID:
    created = await admin_service.create_organization(
        name=name,
        slug=f"btype-{uuid.uuid4().hex[:8]}",
        vertical_template=vertical,
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return uuid.UUID(str(created["id"]))


async def _given_clinic_by_default(tenant_id: uuid.UUID) -> None:
    """What migration d7a3c91e5b20 does to an account that had clinic."""
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE organizations SET unconfirmed_business_type = vertical_template, "
                "vertical_template = NULL WHERE id = :tid"
            ),
            {"tid": tenant_id},
        )


async def _business_keys(tenant_id: uuid.UUID) -> list[list[str]]:
    async with tenant_session(tenant_id) as session:
        agents = await lead_fields.agents_with_fields(session)
    return [[f.key for f in a["fields"]] for a in agents]


async def _first_agent(tenant_id: uuid.UUID) -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        return uuid.UUID(str((await lead_fields.agents_with_fields(session))[0]["id"]))


def _suggests(monkeypatch: pytest.MonkeyPatch, answer: str | None) -> list[str]:
    asked: list[str] = []

    async def fake_ask_json(description: str, instruction: str, **kwargs: Any) -> JsonAnswer[Any]:
        asked.append(description)
        if answer is None:
            from apps.api.core.errors import ProblemError

            raise ProblemError.business_rule("assist_unavailable", "no model")
        value = kwargs["parse"]({"business_type": answer, "reason": "sells chilli powder"})
        return JsonAnswer(value=value, capability=None, usage=None)  # type: ignore[arg-type]

    async def no_meter(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(worker, "ask_json", fake_ask_json)
    monkeypatch.setattr(crm_assist, "meter_assist", no_meter)
    return asked


async def _apply(tenant_id: uuid.UUID, *, replace: bool = True) -> str:
    return await worker.apply_business_type(
        {}, {"tenant_id": str(tenant_id), "replace_clinic_default": replace}
    )


async def _operator() -> dict[str, str]:
    admin_id = uuid.uuid4()
    async with admin_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops Anand', 'operator', now(), now())"
            ),
            {"id": admin_id},
        )
    return {"Authorization": f"Bearer dev:admin:{admin_id}"}


async def _http(method: str, path: str, headers: dict[str, str], body: Any = None) -> Any:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        return await http.request(method, path, json=body, headers=headers)


# --- 2. unconfirmed accounts run neutral ---------------------------------------------------


@pytest.mark.rls
async def test_an_account_given_clinic_by_default_runs_on_the_core_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = await _tenant("clinic")
    agent_id = await _first_agent(tenant_id)
    async with tenant_session(tenant_id) as session:
        # A script whose "what to collect" was compiled from the clinic fields.
        await apply_starter(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            job="answer_calls",
            vertical_template="clinic",
            business="Raghava Organics",
            created_by=None,
        )
        await session.execute(
            text("UPDATE agents SET caller_memory_enabled = true WHERE id = :aid"),
            {"aid": agent_id},
        )
    await _given_clinic_by_default(tenant_id)
    asked = _suggests(monkeypatch, "retail")

    assert await _apply(tenant_id) == "done"

    assert await _business_keys(tenant_id) == [[]]
    async with tenant_session(tenant_id) as session:
        body = (
            await session.execute(
                text(
                    "SELECT pv.body FROM agents a JOIN prompt_versions pv "
                    "ON pv.id = a.system_prompt_id WHERE a.id = :aid"
                ),
                {"aid": agent_id},
            )
        ).scalar_one()
        state = await business_type.read_state(session, tenant_id=tenant_id)
        # An unconfirmed clinic is refused cross-call memory exactly as a confirmed one is.
        assert not await memory_enabled(session, agent_id=agent_id)
    for label in ("Symptom", "Preferred doctor", "Insurance"):
        assert label not in body
    assert state.business_type is None
    assert state.unconfirmed is not None and state.unconfirmed.given == "clinic"
    assert state.unconfirmed.suggested == "retail"
    assert state.unconfirmed.reason == "sells chilli powder"
    # The model is not handed the default it is meant to question.
    assert len(asked) == 1 and "Clinic" not in asked[0] and "Raghava Organics" in asked[0]

    # A second delivery asks the model nothing more and writes nothing more.
    assert await _apply(tenant_id) == "done"
    assert len(asked) == 1


@pytest.mark.rls
async def test_no_model_leaves_the_account_unconfirmed_without_a_suggestion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = await _tenant("clinic")
    await _given_clinic_by_default(tenant_id)
    _suggests(monkeypatch, None)
    assert await _apply(tenant_id) == "done"
    async with tenant_session(tenant_id) as session:
        state = await business_type.read_state(session, tenant_id=tenant_id)
    assert state.unconfirmed is not None and state.unconfirmed.suggested is None


# --- 3. confirming ----------------------------------------------------------------------------


@pytest.mark.rls
async def test_confirming_applies_the_type_to_agents_with_no_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = await _tenant("clinic")
    await _given_clinic_by_default(tenant_id)
    _suggests(monkeypatch, "retail")
    await _apply(tenant_id)
    assert await _business_keys(tenant_id) == [[]]

    headers = await _operator()
    path = f"/v1/admin/tenants/{tenant_id}/business-type"
    read = await _http("GET", path, headers)
    assert read.status_code == 200, read.text
    assert read.json()["unconfirmed"]["given_label"] == "Clinic or health"
    assert read.json()["unconfirmed"]["suggested_label"] == "Shop, food or produce"

    confirmed = await _http("POST", f"{path}/confirm", headers, {"business_type": "retail"})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["business_type"] == "retail"
    assert confirmed.json()["unconfirmed"] is None
    async with tenant_session(tenant_id) as session:
        queued = (
            await session.execute(
                text(
                    "SELECT count(*) FROM outbox_messages WHERE job = :job "
                    "AND payload->>'tenant_id' = :tid"
                ),
                {"job": business_type.APPLY_JOB, "tid": str(tenant_id)},
            )
        ).scalar()
        audited = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE tenant_id = :tid "
                    "AND action = 'organization.business_type_confirmed'"
                ),
                {"tid": tenant_id},
            )
        ).scalar()
    assert queued == 1 and audited == 1

    await _apply(tenant_id)
    assert await _business_keys(tenant_id) == [RETAIL_KEYS]

    refused = await _http("POST", f"{path}/confirm", headers, {"business_type": "bakery"})
    assert refused.status_code == 422


@pytest.mark.rls
async def test_details_somebody_chose_are_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = await _tenant("clinic")
    async with tenant_session(tenant_id) as session:
        await write_schema(
            session,
            agent_id=await _first_agent(tenant_id),
            fields=[ExtractionField(key="chilli_variety", label="Chilli variety", type="text")],
        )
    await _given_clinic_by_default(tenant_id)
    _suggests(monkeypatch, "retail")
    await _apply(tenant_id)
    assert await _business_keys(tenant_id) == [["chilli_variety"]]


@pytest.mark.rls
async def test_a_chosen_clinic_is_left_exactly_as_it_is(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = await _tenant("clinic")
    asked = _suggests(monkeypatch, "retail")
    await _apply(tenant_id)
    assert await _business_keys(tenant_id) == [CLINIC_KEYS]
    assert asked == []


# --- 4. Raghava's repair --------------------------------------------------------------------


@pytest.mark.rls
async def test_a_shop_set_to_its_type_gets_the_shop_details_in_place_of_the_clinic_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = await _tenant("clinic")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET vertical_template = 'retail' WHERE id = :tid"),
            {"tid": tenant_id},
        )
    asked = _suggests(monkeypatch, "retail")
    await _apply(tenant_id)
    assert await _business_keys(tenant_id) == [RETAIL_KEYS]
    assert asked == []


# --- 5. tenancy ----------------------------------------------------------------------------------


@pytest.mark.rls
async def test_one_clients_confirm_touches_no_other_client(monkeypatch: pytest.MonkeyPatch) -> None:
    mine = await _tenant("clinic")
    theirs = await _tenant("clinic", name="Sri Lakshmi Traders")
    await _given_clinic_by_default(mine)
    await _given_clinic_by_default(theirs)
    headers = await _operator()
    response = await _http(
        "POST",
        f"/v1/admin/tenants/{mine}/business-type/confirm",
        headers,
        {"business_type": "retail"},
    )
    assert response.status_code == 200, response.text
    async with tenant_session(theirs) as session:
        state = await business_type.read_state(session, tenant_id=theirs)
    assert state.business_type is None and state.unconfirmed is not None
    missing = await _http("GET", f"/v1/admin/tenants/{uuid.uuid4()}/business-type", headers)
    assert missing.status_code == 404
