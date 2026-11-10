"""Journey audit E7 (10 Nov 2026): a person's data across its whole life.

Each test failed before its fix.
"""

from __future__ import annotations

import json
import uuid

from apps.api.compliance.export import build_subject_export
from apps.api.compliance.export_routes import SubjectExportOut
from apps.api.db.session import tenant_session
from sqlalchemy import text
from tests.conftest import create_org_with_receptionist


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    created = await create_org_with_receptionist(
        name="E7 Shop",
        slug=f"e7-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return created["id"], created["agent_id"]


def _phone() -> str:
    return f"+9198{uuid.uuid4().int % 10**8:08d}"


async def _call_with_extraction(tenant_id: uuid.UUID, agent_id: uuid.UUID, phone: str) -> str:
    call_id = uuid.uuid4()
    insights = {
        "outcome": "not_interested",
        "no_reason": "price",
        "objections": [{"text": "too costly for me, call +919811122233", "kind": "price"}],
        "issues": [],
        "next_step": None,
    }
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "from_e164, to_e164, started_at, ended_at, duration_s, goal_reason, insights, "
                "created_at, updated_at) VALUES (:id, :t, :a, :e, 'inbound', 'completed', "
                ":phone, '+911140000000', now(), now(), 60, :why, CAST(:ins AS jsonb), "
                "now(), now())"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": f"e7_{call_id.hex[:12]}",
                "phone": phone,
                "why": "Said the price was too high",
                "ins": json.dumps(insights),
            },
        )
        await session.execute(
            text(
                "INSERT INTO call_extractions (id, tenant_id, call_id, schema_version, data, "
                "model, valid, unlisted, created_at, updated_at) VALUES (:id, :t, :c, 1, "
                "CAST(:data AS jsonb), NULL, true, CAST(:unlisted AS jsonb), now(), now())"
            ),
            {
                "id": uuid.uuid4(),
                "t": tenant_id,
                "c": call_id,
                "data": json.dumps({"address": "12 Old Market Road", "need": "rice"}),
                "unlisted": json.dumps({"budget": "around five thousand"}),
            },
        )
    return str(call_id)


async def test_a_subject_export_discloses_what_each_call_captured_about_the_person() -> None:
    """E7-01. §12 empties `call_extractions.data`/`unlisted` and `calls.goal_reason`/
    `insights` for this person; the client's own call screen shows all four. The §11 export
    carried none of them, so an address captured on an earlier call and since overwritten on
    the lead, the caller's own words for a choice field, and their objections were held and
    shown to the business but withheld from the person asking what is held about them."""
    tenant_id, agent_id = await _tenant()
    phone = _phone()
    call_id = await _call_with_extraction(tenant_id, agent_id, phone)
    async with tenant_session(tenant_id) as session:
        document = await build_subject_export(session, tenant_id=tenant_id, phone_e164=phone)

    model = SubjectExportOut.model_validate(document)
    assert model.model_dump(mode="json") == document
    (call,) = document["calls"]
    assert call["call_id"] == call_id
    assert call.get("captured") == {"address": "12 Old Market Road", "need": "rice"}
    assert call.get("said") == {"budget": "around five thousand"}
    assert call.get("goal_reason") == "Said the price was too high"
    insights = call.get("insights")
    assert insights is not None and insights["outcome"] == "not_interested"
    objection = insights["objections"][0]["text"]
    assert objection.startswith("too costly for me")
    # Another person's number inside the caller's words is masked like every summary.
    assert "+919811122233" not in json.dumps(document)


async def test_a_subject_export_discloses_the_follow_ups_the_person_is_in() -> None:
    """E7-02. §12 stops and forgets a person's Follow-up runs (`_erase_follow_up_runs`): a
    record that this number is enrolled in an automated sequence of calls and messages. The
    §11 export never listed them, so a person being worked through a sequence, even one with
    no lead record, was told nothing about it."""
    tenant_id, _agent_id = await _tenant()
    phone = _phone()
    follow_up_id, version_id = uuid.uuid4(), uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO follow_ups (id, tenant_id, name, status, trigger, settings) VALUES "
                "(:f, :t, 'Payment reminders', 'draft', '{\"kind\": \"manual\"}'::jsonb, "
                "'{}'::jsonb)"
            ),
            {"f": follow_up_id, "t": tenant_id},
        )
        await session.execute(
            text(
                "INSERT INTO follow_up_versions (id, tenant_id, follow_up_id, number, steps, "
                "trigger, settings) VALUES (:v, :t, :f, 1, '[]'::jsonb, "
                "'{\"kind\": \"manual\"}'::jsonb, '{}'::jsonb)"
            ),
            {"v": version_id, "t": tenant_id, "f": follow_up_id},
        )
        await session.execute(
            text(
                "INSERT INTO follow_up_runs (id, tenant_id, follow_up_id, version_id, lead_id, "
                "phone_e164, status, step_id, trigger_ref, started_at) VALUES "
                "(gen_random_uuid(), :t, :f, :v, NULL, :phone, 'waiting', 's1', "
                "'manual:e7', now())"
            ),
            {"t": tenant_id, "f": follow_up_id, "v": version_id, "phone": phone},
        )
        document = await build_subject_export(session, tenant_id=tenant_id, phone_e164=phone)

    model = SubjectExportOut.model_validate(document)
    assert model.model_dump(mode="json") == document
    follow_ups = document.get("follow_ups")
    assert follow_ups is not None and len(follow_ups) == 1, "the enrolment was not disclosed"
    assert follow_ups[0]["follow_up_name"] == "Payment reminders"
    assert follow_ups[0]["status"] == "waiting"
    assert document["counts"].get("follow_ups") == 1
