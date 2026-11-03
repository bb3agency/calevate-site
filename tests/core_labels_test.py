"""Each client's own names for the core lead details.

What is under test:

1. **The rule.** Only the name changes: unknown keys, blanks, defaults and a name another
   detail already has are never stored, and the extraction spec keeps the platform's names.
2. **The screen.** An owner names the details, sees them under those names on Lead details
   and on a lead, and cannot give two details one name.
3. **The one AI naming.** Queued once a business says what it sells, stored once, never over
   names the owner chose, and free to ask again after a refusal.
4. **Tenancy (hard rule 1).** One client's names never reach another's screens.
"""

from __future__ import annotations

import uuid
from typing import Any, get_args

import pytest
from apps.api.agents import lead_fields
from apps.api.agents.lead_fields_routes import CoreKey
from apps.api.core.errors import ProblemError
from apps.api.crm.captured import captured_fields
from apps.api.db.session import tenant_session
from apps.workers import core_labels as worker
from apps.workers.extraction import AssistCapability
from apps.workers.script_assist import JsonAnswer
from calevate_shared.lead_fields import (
    CORE_KEYS,
    CORE_LABEL_MAX_CHARS,
    CORE_LEAD_FIELDS,
    clean_core_labels,
    core_fields,
    with_core,
)
from sqlalchemy import text
from tests.lead_fields_test import _call, _tenant

DEFAULTS = {f.key: f.label for f in CORE_LEAD_FIELDS}


def test_only_a_new_name_for_a_known_detail_is_kept() -> None:
    named = clean_core_labels(
        {
            "need": "  Crop   issue ",
            "notes": "",
            "language": DEFAULTS["language"],
            "unknown": "Anything",
            "preferred_time": "x" * (CORE_LABEL_MAX_CHARS + 10),
            "other_number": "Name",
        }
    )
    assert named == {"need": "Crop issue", "preferred_time": "x" * CORE_LABEL_MAX_CHARS}


def test_two_details_never_share_a_name() -> None:
    assert clean_core_labels({"need": "Crop issue", "notes": "crop ISSUE"}) == {
        "need": "Crop issue"
    }


def test_only_the_name_changes_and_the_call_reader_keeps_the_platforms() -> None:
    renamed = core_fields({"need": "Crop issue"})
    need = next(f for f in renamed if f.key == "need")
    original = next(f for f in CORE_LEAD_FIELDS if f.key == "need")
    assert need.label == "Crop issue"
    assert (need.key, need.reason, need.type) == (original.key, original.reason, original.type)
    # The extraction spec is built without names, so the model reads the platform's.
    assert with_core([]) == list(CORE_LEAD_FIELDS)


def test_the_route_names_exactly_the_core() -> None:
    assert set(get_args(CoreKey)) == CORE_KEYS


@pytest.mark.rls
async def test_an_owner_names_the_details_and_every_screen_reads_them() -> None:
    tenant_id, token = await _tenant("custom", "Rytu Khata")
    code, body = await _call(
        "PUT", "/v1/lead-fields/core-labels", token, {"labels": {"need": "Crop issue"}}
    )
    assert code == 200, body
    shown = {f["key"]: f["label"] for f in body["core_fields"]}
    assert shown["need"] == "Crop issue" and shown["name"] == DEFAULTS["name"]
    assert body["core_default_labels"] == DEFAULTS

    async with tenant_session(tenant_id) as session:
        captured = await captured_fields(
            session, agent_id=None, schema_version=None, data={"need": "Pest on paddy"}
        )
    assert next(f for f in captured if f.key == "need").label == "Crop issue"

    # Clearing a name shows the platform's again.
    code, body = await _call("PUT", "/v1/lead-fields/core-labels", token, {"labels": {"need": ""}})
    assert code == 200, body
    assert {f["key"]: f["label"] for f in body["core_fields"]}["need"] == DEFAULTS["need"]


@pytest.mark.rls
async def test_two_details_under_one_name_are_refused_by_name() -> None:
    _, token = await _tenant("custom")
    code, body = await _call(
        "PUT",
        "/v1/lead-fields/core-labels",
        token,
        {"labels": {"need": "Crop issue", "notes": "Crop issue"}},
    )
    assert code == 422, body
    assert body["type"].endswith("/core_label_taken"), body
    code, body = await _call(
        "PUT", "/v1/lead-fields/core-labels", token, {"labels": {"phone": "Mobile"}}
    )
    assert code == 422, body


async def _services(tenant_id: uuid.UUID, services: str) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO business_profiles (id, tenant_id, services) VALUES "
                "(:id, :tid, CAST(:services AS jsonb)) "
                "ON CONFLICT (tenant_id) DO UPDATE SET services = EXCLUDED.services"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "services": services},
        )


async def _with_services(tenant_id: uuid.UUID) -> None:
    await _services(tenant_id, '[{"name": "Crop records"}]')


async def _queued(tenant_id: uuid.UUID) -> int:
    async with tenant_session(tenant_id) as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM outbox_messages WHERE job = :job "
                        "AND payload->>'tenant_id' = :tid"
                    ),
                    {"job": lead_fields.NAME_CORE_JOB, "tid": str(tenant_id)},
                )
            ).scalar_one()
        )


def _answer(labels: dict[str, str]) -> Any:
    async def answered(*_args: Any, **_kwargs: Any) -> JsonAnswer[dict[str, str]]:
        return JsonAnswer(
            value=labels,
            capability=AssistCapability(available=True, provider="gemini"),
            model="gemini-2.5-flash-lite",
        )

    return answered


@pytest.mark.rls
async def test_a_business_is_named_once_and_never_over_its_owners_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, token = await _tenant("custom", "Rytu Khata")
    # Before it says what it sells, a name would be a guess.
    await _services(tenant_id, "[]")
    async with tenant_session(tenant_id) as session:
        assert await lead_fields.maybe_name_core_details(session, tenant_id=tenant_id) is False
    await _with_services(tenant_id)
    async with tenant_session(tenant_id) as session:
        assert await lead_fields.maybe_name_core_details(session, tenant_id=tenant_id) is True
        assert await lead_fields.maybe_name_core_details(session, tenant_id=tenant_id) is False
    assert await _queued(tenant_id) == 1

    monkeypatch.setattr(worker, "ask_json", _answer({"need": "Crop issue"}))
    payload = {"tenant_id": str(tenant_id)}
    assert await worker.name_core_details({}, payload) == "named"
    # Once: a second delivery finds it taken.
    assert await worker.name_core_details({}, payload) == "not_needed"
    code, body = await _call("GET", "/v1/lead-fields", token)
    assert code == 200, body
    assert {f["key"]: f["label"] for f in body["core_fields"]}["need"] == "Crop issue"

    # The owner's names are theirs: a later profile save queues nothing.
    await _call("PUT", "/v1/lead-fields/core-labels", token, {"labels": {"need": "Farm need"}})
    async with tenant_session(tenant_id) as session:
        assert await lead_fields.maybe_name_core_details(session, tenant_id=tenant_id) is False


@pytest.mark.rls
async def test_a_refused_naming_may_be_asked_again(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, _ = await _tenant("custom")
    await _with_services(tenant_id)

    async def refused(*_args: Any, **_kwargs: Any) -> Any:
        raise ProblemError.business_rule("assist_answer_unusable", "Nothing usable came back.")

    monkeypatch.setattr(worker, "ask_json", refused)
    async with tenant_session(tenant_id) as session:
        assert await lead_fields.maybe_name_core_details(session, tenant_id=tenant_id) is True
    assert await worker.name_core_details({}, {"tenant_id": str(tenant_id)}) == "refused"
    # The next change to what it sells asks again; the first message does not block it.
    await _services(tenant_id, '[{"name": "Crop records"}, {"name": "Soil tests"}]')
    async with tenant_session(tenant_id) as session:
        assert await lead_fields.maybe_name_core_details(session, tenant_id=tenant_id) is True
    assert await _queued(tenant_id) == 2


@pytest.mark.rls
async def test_one_client_never_sees_anothers_names() -> None:
    tenant_a, token_a = await _tenant("custom", "Rytu Khata")
    tenant_b, token_b = await _tenant("custom", "Beta Traders")
    await _call("PUT", "/v1/lead-fields/core-labels", token_a, {"labels": {"need": "Crop issue"}})
    code, body = await _call("GET", "/v1/lead-fields", token_b)
    assert code == 200, body
    assert {f["key"]: f["label"] for f in body["core_fields"]}["need"] == DEFAULTS["need"]
    async with tenant_session(tenant_b) as session:
        rows = (
            await session.execute(
                text("SELECT count(*) FROM organizations WHERE id = :tid"), {"tid": tenant_a}
            )
        ).scalar_one()
    assert rows == 0
