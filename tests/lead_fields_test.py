"""Business-neutral lead details (founder decision 15, 10 Oct 2026).

What is under test:

1. **The core.** Every lead carries a fixed set whatever the business; it is composed in on
   read, never stored, and no stored copy can shadow it.
2. **The business types.** One list, no clinic default, a standard set per known type with
   none of its keys colliding with the core, a fixed Leads column or an extraction output.
3. **The one AI draft.** Drafted once, never twice, kept by its owner onto the ticked
   campaigns and lines (D-1029), which by default are only the ones nobody customised, and
   tolerant of a malformed model answer.
4. **Applying a set.** Each job is written under a compare-and-set on the list the screen
   showed; one changed meanwhile refuses the whole apply. An agent's old versions stay
   readable under their old names.
5. **Tenancy (hard rule 1).** One business never sees another's draft, lines or lists.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

import pytest
from apps.api.admin.routes import CreateOrgIn
from apps.api.agents import lead_fields, starters
from apps.api.agents.extraction_routes import validate_fields, write_schema
from apps.api.agents.lead_fields_routes import router as lead_fields_router
from apps.api.campaigns import notes as job_notes
from apps.api.core.errors import ProblemError, install_error_handlers
from apps.api.core.rbac import assert_policy_registry_complete
from apps.api.crm.captured import captured_fields
from apps.api.crm.columns import FIXED_KEYS
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.inbound import lines
from apps.workers import lead_fields_draft
from apps.workers.extraction import (
    PROVIDER_UNAVAILABLE_REASON,
    AssistCapability,
    assist_unavailable,
)
from apps.workers.script_assist import JsonAnswer
from calevate_shared import verticals
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
from pydantic import ValidationError
from sqlalchemy import text
from tests.conftest import accept_agreements, create_org_with_receptionist

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
    assert set(verticals.all_keys()) == {*verticals.templates(), "custom"}
    assert verticals.all_keys()[0] != "clinic"
    # Required, with no default at all (D-722): a default is how a shop became a clinic.
    assert CreateOrgIn.model_fields["vertical_template"].is_required()
    owner = {"name": "Owner", "email": "owner@example.com"}
    for key in verticals.all_keys():
        CreateOrgIn.model_validate({"name": "Shop", "vertical_template": key, "owner": owner})
    with pytest.raises(ValidationError):
        CreateOrgIn.model_validate({"name": "Shop", "vertical_template": "bakery", "owner": owner})
    for new in ("retail", "local_services", "automobile"):
        assert new in verticals.templates()


@pytest.mark.parametrize("vertical", sorted(verticals.templates()))
def test_every_standard_set_is_its_own_and_collides_with_nothing(vertical: str) -> None:
    fields = [ExtractionField.model_validate(f) for f in verticals.templates()[vertical]]
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
    assert starters.captured_fields("custom") == []
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
            {"label": "Alternate number", "type": "text", "reason": "another number to call"},
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
    assert "summary" not in keys and "alternate_number" not in keys
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
    created = await create_org_with_receptionist(
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


async def _agent_id(tenant_id: uuid.UUID) -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        return uuid.UUID(
            str((await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar_one())
        )


async def _line(tenant_id: uuid.UUID, name: str = "Front desk") -> uuid.UUID:
    """An inbound line in the receptionist's voice; it starts with the business's set."""
    async with tenant_session(tenant_id) as session:
        return await lines.create_line(
            session,
            tenant_id=tenant_id,
            agent_id=await _agent_id(tenant_id),
            name=name,
            created_by=None,
        )


async def _job_keys(tenant_id: uuid.UUID) -> list[list[str]]:
    """What each open job notes, by key, in the screen's order."""
    async with tenant_session(tenant_id) as session:
        jobs = await lead_fields.jobs_with_fields(session, starting=[])
    return [[f.key for f in job.fields] for job in jobs]


async def _refs(token: str) -> list[dict[str, str]]:
    """The jobs the screen ticks by default, as an apply sends them."""
    _code, body = await _call("GET", "/v1/lead-fields", token)
    return [
        {"kind": job["kind"], "id": job["id"], "digest": job["digest"]}
        for job in body["jobs"]
        if job["untouched"]
    ]


DRAFTED = [
    ExtractionField(key="produce", label="Produce", type="text", reason="what", required=True),
    ExtractionField(key="kilos", label="Kilos", type="number", reason="how much"),
]


async def _run_worker(tenant_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch) -> str:
    async def fake_draft(description: str, tenant_leg: object) -> JsonAnswer[list[ExtractionField]]:
        assert "Raghava" in description
        return JsonAnswer(
            value=list(DRAFTED),
            capability=AssistCapability(available=True, provider="sarvam"),
            model="sarvam-105b",
        )

    monkeypatch.setattr(lead_fields_draft, "_draft", fake_draft)
    return await lead_fields_draft.draft_lead_fields({}, {"tenant_id": str(tenant_id)})


# --- 3b. the draft, end to end ------------------------------------------------------------


async def _request(tenant_id: uuid.UUID) -> str:
    """Asking for the draft is Pip's (`lead_fields_draft`, D-821); its executor is this."""
    async with tenant_session(tenant_id) as session:
        draft = await lead_fields.request_draft(session, tenant_id=tenant_id, requested_by=None)
    return draft.status


@pytest.mark.rls
async def test_a_custom_business_is_drafted_once_and_kept_by_its_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, token = await _tenant("custom")
    line_id = await _line(tenant_id)
    code, body = await _call("GET", "/v1/lead-fields", token)
    assert code == 200, body
    assert body["can_draft"] is True and body["draft"] is None
    assert [f["key"] for f in body["core_fields"]] == [f.key for f in CORE_LEAD_FIELDS]
    (job,) = body["jobs"]
    assert job["kind"] == "line" and job["id"] == str(line_id)
    assert job["fields"] == [] and job["untouched"] is True

    assert await _request(tenant_id) == "queued"
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
    assert await _request(tenant_id) == "queued"

    assert await _run_worker(tenant_id, monkeypatch) == "done"
    # A second delivery of the same message finds nothing to claim.
    assert await _run_worker(tenant_id, monkeypatch) == "not_queued"
    # Drafted, and on no line until the owner keeps it (D-821).
    assert await _job_keys(tenant_id) == [[]]
    code, body = await _call("GET", "/v1/lead-fields", token)
    assert body["draft"]["status"] == "done" and body["draft"]["reviewed"] is False
    assert [f["key"] for f in body["draft"]["fields"]] == ["produce", "kilos"]
    assert body["can_draft"] is False

    code, body = await _call(
        "POST",
        "/v1/lead-fields/draft/review",
        token,
        {"keep": ["produce"], "jobs": await _refs(token)},
    )
    assert code == 200, body
    assert body == {"fields_kept": 1, "jobs_changed": 1, "jobs_waiting": 0}
    assert await _job_keys(tenant_id) == [["produce"]]
    code, body = await _call("GET", "/v1/lead-fields", token)
    assert body["draft"]["reviewed"] is True
    assert [f["key"] for f in body["draft"]["fields"]] == ["produce"]
    assert [f["key"] for f in body["starting_fields"]] == ["produce"]
    # Reviewed once, never again, and never redrafted.
    code, body = await _call(
        "POST", "/v1/lead-fields/draft/review", token, {"keep": ["kilos"], "jobs": []}
    )
    assert code == 409, body
    with pytest.raises(ProblemError) as again:
        await _request(tenant_id)
    assert again.value.code == "lead_fields_already_drafted"
    async with tenant_session(tenant_id) as session:
        audited = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE action = 'lead_fields.draft_reviewed' "
                    "AND tenant_id = :t"
                ),
                {"t": tenant_id},
            )
        ).scalar_one()
    assert audited == 1


@pytest.mark.rls
async def test_a_discarded_draft_reaches_no_line_and_new_ones_start_from_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, token = await _tenant("custom")
    await _line(tenant_id)
    await _request(tenant_id)
    assert await _run_worker(tenant_id, monkeypatch) == "done"
    code, body = await _call(
        "POST", "/v1/lead-fields/draft/review", token, {"keep": [], "jobs": await _refs(token)}
    )
    assert code == 200 and body == {"fields_kept": 0, "jobs_changed": 0, "jobs_waiting": 0}
    assert await _job_keys(tenant_id) == [[]]
    async with tenant_session(tenant_id) as session:
        start = await lead_fields.starting_business_fields(
            session, tenant_id=tenant_id, vertical="custom"
        )
    assert start == lead_fields.standard_fields(lead_fields.CUSTOM)


@pytest.mark.rls
async def test_only_lists_nobody_chose_are_ticked_and_a_kept_draft_starts_new_ones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The review screen ticks a job whose list is empty or exactly a set the platform
    offered (here the clinic's standard set, from before a type move), never one with its
    owner's own list; and only the ticked jobs change."""
    tenant_id, token = await _tenant("custom")
    own_line = await _line(tenant_id, "Own list")
    clinic_line = await _line(tenant_id, "Old clinic set")
    empty_line = await _line(tenant_id, "Empty")
    own = [ExtractionField(key="flavour", label="Flavour", type="text")]
    async with tenant_session(tenant_id) as session:
        await job_notes.save_notes(session, "line", own_line, own, expected_digest=None)
        await job_notes.save_notes(
            session,
            "line",
            clinic_line,
            lead_fields.standard_fields("clinic"),
            expected_digest=None,
        )
        await job_notes.save_notes(session, "line", empty_line, [], expected_digest=None)
    await _request(tenant_id)
    assert await _run_worker(tenant_id, monkeypatch) == "done"
    _code, body = await _call("GET", "/v1/lead-fields", token)
    ticked = {job["name"]: job["untouched"] for job in body["jobs"]}
    assert ticked == {"Empty": True, "Old clinic set": True, "Own list": False}

    code, body = await _call(
        "POST",
        "/v1/lead-fields/draft/review",
        token,
        {"keep": ["produce", "kilos"], "jobs": await _refs(token)},
    )
    assert code == 200 and body["jobs_changed"] == 2, body
    assert sorted(await _job_keys(tenant_id)) == [
        ["flavour"],
        ["produce", "kilos"],
        ["produce", "kilos"],
    ]
    async with tenant_session(tenant_id) as session:
        start = await lead_fields.starting_business_fields(
            session, tenant_id=tenant_id, vertical="custom"
        )
    assert [f.key for f in start] == ["produce", "kilos"]
    assert await _job_keys_of(tenant_id, await _line(tenant_id, "New")) == ["produce", "kilos"], (
        "a new line starts with the kept set"
    )


async def _job_keys_of(tenant_id: uuid.UUID, line_id: uuid.UUID) -> list[str]:
    async with tenant_session(tenant_id) as session:
        held = await job_notes.read_notes(session, "line", line_id)
    return [f.key for f in held.fields]


@pytest.mark.rls
async def test_an_apply_over_a_list_changed_meanwhile_writes_nothing() -> None:
    tenant_id, token = await _tenant("retail")
    first = await _line(tenant_id, "First")
    second = await _line(tenant_id, "Second")
    refs = await _refs(token)
    assert len(refs) == 2
    async with tenant_session(tenant_id) as session:
        await job_notes.save_notes(
            session,
            "line",
            second,
            [ExtractionField(key="flavour", label="Flavour", type="text")],
            expected_digest=None,
        )
        await job_notes.save_notes(session, "line", first, [], expected_digest=None)
    refs = [r for r in refs if r["id"] == str(second)] + await _refs(token)
    code, body = await _call("POST", "/v1/lead-fields/replace", token, {"jobs": refs})
    assert code == 409, body
    assert body["type"].endswith("line_notes_changed_elsewhere")
    assert sorted(await _job_keys(tenant_id)) == [[], ["flavour"]], "the refusal wrote nothing"

    code, body = await _call("POST", "/v1/lead-fields/replace", token, {"jobs": await _refs(token)})
    assert code == 200 and body == {"jobs_changed": 1, "jobs_unchanged": 0, "jobs_waiting": 0}
    standard = [f["key"] for f in verticals.templates()["retail"]]
    assert sorted(await _job_keys(tenant_id)) == sorted([standard, ["flavour"]])


@pytest.mark.rls
async def test_a_failed_draft_may_be_asked_for_again(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, _ = await _tenant("custom")
    async with tenant_session(tenant_id) as session:
        await lead_fields.request_draft(session, tenant_id=tenant_id, requested_by=None)

    async def nothing(description: str, tenant_leg: object) -> JsonAnswer[list[ExtractionField]]:
        raise assist_unavailable(
            AssistCapability(available=False, reason=PROVIDER_UNAVAILABLE_REASON)
        )

    monkeypatch.setattr(lead_fields_draft, "_draft", nothing)
    assert await lead_fields_draft.draft_lead_fields({}, {"tenant_id": str(tenant_id)}) == "failed"
    async with tenant_session(tenant_id) as session:
        draft = await lead_fields.read_draft(session, tenant_id=tenant_id)
        assert draft is not None and draft.status == "failed"
        assert draft.error_code == "no_provider"
        again = await lead_fields.request_draft(session, tenant_id=tenant_id, requested_by=None)
    assert again.status == "queued"


@pytest.mark.rls
async def test_a_draft_whose_worker_died_reads_failed_and_may_be_asked_for_again() -> None:
    """A job killed or timed out after its claim is not retried, so `running` would stay
    forever and the business could never be drafted."""
    tenant_id, _ = await _tenant("custom")
    await _request(tenant_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE lead_field_drafts SET status = 'running', "
                "updated_at = now() - make_interval(mins => :m)"
            ),
            {"m": lead_fields.DRAFT_STALE_MINUTES + 1},
        )
        draft = await lead_fields.read_draft(session, tenant_id=tenant_id)
        assert draft is not None and draft.status == "failed"
        assert draft.error_code == "draft_crashed"
        again = await lead_fields.request_draft(session, tenant_id=tenant_id, requested_by=None)
    assert again.status == "queued"


@pytest.mark.rls
async def test_a_draft_that_cannot_be_stored_charges_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The charge and the stored draft are one transaction: when either fails, neither is
    kept, so the account never pays for a draft it does not have."""
    tenant_id, _ = await _tenant("custom")
    await _request(tenant_id)
    metered: list[str] = []

    async def earlier(*_args: object, **_kwargs: object) -> None:
        metered.append("earlier")

    async def broken_assist(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("the charge failed")

    monkeypatch.setattr(lead_fields_draft.crm_assist, "meter_earlier", earlier)
    monkeypatch.setattr(lead_fields_draft.crm_assist, "meter_assist", broken_assist)
    assert await _run_worker(tenant_id, monkeypatch) == "failed"
    async with tenant_session(tenant_id) as session:
        draft = await lead_fields.read_draft(session, tenant_id=tenant_id)
    # The draft had been written in the charge's transaction, and went with it.
    assert metered == ["earlier"]
    assert draft is not None and draft.status == "failed" and draft.fields == []


@pytest.mark.rls
async def test_a_known_business_type_is_drafted_from_its_standard_set_as_a_seed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every business is drafted (5 Nov 2026): the type's standard set is the starting point
    the model is shown, and the kept draft replaces it on a line nobody edited."""
    tenant_id, token = await _tenant("retail")
    await _line(tenant_id)
    standard = [f["key"] for f in verticals.templates()["retail"]]
    assert await _job_keys(tenant_id) == [standard]
    code, body = await _call("GET", "/v1/lead-fields", token)
    assert body["can_draft"] is True and body["has_standard_set"] is True
    assert [f["key"] for f in body["starting_fields"]] == standard
    seen: list[str] = []

    async def fake_draft(description: str, tenant_leg: object) -> JsonAnswer[list[ExtractionField]]:
        seen.append(description)
        return JsonAnswer(
            value=list(DRAFTED),
            capability=AssistCapability(available=True, provider="sarvam"),
            model="sarvam-105b",
        )

    assert await _request(tenant_id) == "queued"
    monkeypatch.setattr(lead_fields_draft, "_draft", fake_draft)
    assert await lead_fields_draft.draft_lead_fields({}, {"tenant_id": str(tenant_id)}) == "done"
    assert "Usual details for this type of business" in seen[0]
    code, body = await _call(
        "POST",
        "/v1/lead-fields/draft/review",
        token,
        {"keep": ["produce"], "jobs": await _refs(token)},
    )
    assert code == 200 and body["jobs_changed"] == 1, body
    assert await _job_keys(tenant_id) == [["produce"]]


# --- 4. moving a business to new fields ----------------------------------------------------


@pytest.mark.rls
async def test_an_agents_old_versions_stay_readable_under_their_old_names() -> None:
    tenant_id, _ = await _tenant("clinic")
    agent_id = await _agent_id(tenant_id)
    async with tenant_session(tenant_id) as session:
        old_version = (
            await session.execute(
                text(
                    "SELECT es.version FROM agents a JOIN extraction_schemas es "
                    "ON es.id = a.extraction_schema_id WHERE a.id = :a"
                ),
                {"a": agent_id},
            )
        ).scalar_one()
        written = await write_schema(
            session, agent_id=agent_id, fields=lead_fields.standard_fields("retail")
        )
        assert written.changed and written.version == old_version + 1
        captured = await captured_fields(
            session,
            agent_id=agent_id,
            schema_version=old_version,
            data={"symptom": "fever", "need": "chilli", "gone_key": "x"},
        )
    by_key = {c.key: c for c in captured}
    assert captured[0].key == "name" and by_key["need"].label == "What they want"
    assert by_key["need"].value == "chilli" and by_key["need"].core
    # The clinic's field, labelled as it was captured, and marked as no longer captured.
    assert by_key["symptom"].label == "Symptom / reason" and by_key["symptom"].current is False
    assert by_key["gone_key"].label == "Gone key"


@pytest.mark.rls
async def test_the_core_cannot_be_saved_as_a_business_field() -> None:
    tenant_id, _ = await _tenant("custom")
    async with tenant_session(tenant_id) as session:
        result = await write_schema(
            session,
            agent_id=await _agent_id(tenant_id),
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


@pytest.mark.rls
async def test_one_business_never_lists_or_writes_anothers_lines() -> None:
    tenant_a, _token_a = await _tenant("retail")
    line_a = await _line(tenant_a)
    _tenant_b, token_b = await _tenant("retail")
    _code, body = await _call("GET", "/v1/lead-fields", token_b)
    assert body["jobs"] == []
    code, body = await _call(
        "POST",
        "/v1/lead-fields/replace",
        token_b,
        {"jobs": [{"kind": "line", "id": str(line_a), "digest": "x"}]},
    )
    assert code == 404, body
    standard = [f["key"] for f in verticals.templates()["retail"]]
    assert await _job_keys(tenant_a) == [standard]


@pytest.mark.rls
async def test_an_operator_reads_and_saves_one_clients_line_and_applies_a_type() -> None:
    from apps.api.main import app
    from tests.admin_account_management_test import _operator

    tenant_id, _token = await _tenant("retail")
    line_id = await _line(tenant_id)
    _admin_id, headers = await _operator()
    path = f"/v1/admin/tenants/{tenant_id}/inbound-lines/{line_id}/notes"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        read = await http.get(path, headers=headers)
        assert read.status_code == 200, read.text
        assert read.json()["applied_now"] is False, "a draft line holds no calls"
        saved = await http.put(
            path,
            json={
                "fields": [{"key": "flavour", "label": "Flavour", "type": "text"}],
                "expected_digest": read.json()["digest"],
            },
            headers=headers,
        )
        assert saved.status_code == 200, saved.text
        stale = await http.put(
            path,
            json={"fields": [], "expected_digest": read.json()["digest"]},
            headers=headers,
        )
        assert stale.status_code == 409, stale.text
        listed = await http.get(f"/v1/admin/tenants/{tenant_id}/lead-fields", headers=headers)
        (job,) = listed.json()["jobs"]
        assert job["untouched"] is False
        moved = await http.post(
            f"/v1/admin/tenants/{tenant_id}/lead-fields/replace",
            json={
                "business_type": "clinic",
                "jobs": [{"kind": "line", "id": str(line_id), "digest": job["digest"]}],
            },
            headers=headers,
        )
        assert moved.status_code == 200, moved.text
        assert moved.json() == {"jobs_changed": 1, "jobs_unchanged": 0, "jobs_waiting": 0}
    assert await _job_keys(tenant_id) == [[f["key"] for f in verticals.templates()["clinic"]]]
    async with tenant_session(tenant_id) as session:
        actions = (
            await session.execute(
                text(
                    "SELECT action FROM audit_log WHERE tenant_id = :t "
                    "AND action IN ('admin.job_notes_saved', 'admin.lead_fields_replaced') "
                    "ORDER BY created_at"
                ),
                {"t": tenant_id},
            )
        ).scalars()
        assert list(actions) == ["admin.job_notes_saved", "admin.lead_fields_replaced"]
