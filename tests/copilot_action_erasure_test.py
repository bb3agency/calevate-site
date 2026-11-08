"""A caller's erasure reaches Pip's activity log (`copilot_actions`).

Pip names a lead by id, so its rows carry no number for the erasure to match, but they do
carry the person's NAME: "Change this lead's name to ...", the arguments, and the Undo
states that would write the old name back. Every assertion is on the name.
"""

from __future__ import annotations

import json
import uuid

import pytest
from apps.api.compliance.deletion import request_erasure
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.workers.retention import REDACTED_MARK, execute_deletion_request
from sqlalchemy import text
from tests.conftest import create_org_with_receptionist

pytestmark = pytest.mark.anyio

NAME = "Lakshmi Prasanna"
OLD_NAME = "Lakshmi"


def _phone() -> str:
    return f"+9198762{uuid.uuid4().int % 100000:05d}"


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    created = await create_org_with_receptionist(
        name="Pip Log Shop",
        slug=f"piplog-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return created["id"], created["agent_id"]


async def _lead(tenant_id: uuid.UUID, agent_id: uuid.UUID, phone: str) -> uuid.UUID:
    lead_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status) "
                "VALUES (:i, :t, :a, :p, :n, 'inbound_call', 'new')"
            ),
            {"i": lead_id, "t": tenant_id, "a": agent_id, "p": phone, "n": NAME},
        )
    return lead_id


async def _action(tenant_id: uuid.UUID, lead_id: uuid.UUID, *, status: str = "done") -> uuid.UUID:
    action_id = uuid7()
    pending = status == "pending_approval"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO copilot_actions (id, tenant_id, tool, tier, status, source, "
                "object_type, object_id, args_redacted, prior_state, result_state, "
                "pending_args, summary, undoable_until) VALUES (:i, :t, 'lead_rename', "
                "'immediate', :s, 'interactive', 'lead', :o, CAST(:args AS jsonb), "
                "CAST(:prior AS jsonb), CAST(:result AS jsonb), CAST(:pending AS jsonb), "
                ":summary, now() + interval '1 day')"
            ),
            {
                "i": action_id,
                "t": tenant_id,
                "s": status,
                "o": str(lead_id),
                "args": json.dumps({"lead_id": str(lead_id), "name": NAME}),
                "prior": None if pending else json.dumps({"name": OLD_NAME}),
                "result": None if pending else json.dumps({"name": NAME}),
                "pending": json.dumps({"name": NAME}) if pending else None,
                "summary": f"Change this lead's name to “{NAME}”.",
            },
        )
    return action_id


async def _row(tenant_id: uuid.UUID, action_id: uuid.UUID) -> dict[str, object]:
    async with tenant_session(tenant_id) as session:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT status, summary, args_redacted, prior_state, result_state, "
                        "pending_args, undoable_until FROM copilot_actions WHERE id = :i"
                    ),
                    {"i": action_id},
                )
            )
            .mappings()
            .one()
        )
    return dict(row)


async def _erase(tenant_id: uuid.UUID, phone: str) -> None:
    async with tenant_session(tenant_id) as session:
        record = await request_erasure(session, tenant_id=tenant_id, phone_e164=phone)
    await execute_deletion_request({}, {"tenant_id": str(tenant_id), "request_id": str(record.id)})


async def test_the_erasure_removes_the_callers_name_from_pips_activity_log() -> None:
    tenant_id, agent_id = await _tenant()
    phone = _phone()
    lead_id = await _lead(tenant_id, agent_id, phone)
    done = await _action(tenant_id, lead_id)
    waiting = await _action(tenant_id, lead_id, status="pending_approval")

    await _erase(tenant_id, phone)

    row = await _row(tenant_id, done)
    assert NAME not in json.dumps(row, default=str) and OLD_NAME not in json.dumps(row, default=str)
    assert row["summary"] == REDACTED_MARK
    assert row["prior_state"] is None and row["undoable_until"] is None, "Undo would restore it"
    assert row["status"] == "done", "the record that Pip acted stays"

    held = await _row(tenant_id, waiting)
    assert held["status"] == "expired" and held["pending_args"] is None
    assert NAME not in json.dumps(held, default=str)


async def test_another_callers_rows_are_left_alone() -> None:
    tenant_id, agent_id = await _tenant()
    erased_phone, kept_phone = _phone(), _phone()
    await _lead(tenant_id, agent_id, erased_phone)
    kept_lead = await _lead(tenant_id, agent_id, kept_phone)
    kept = await _action(tenant_id, kept_lead)

    await _erase(tenant_id, erased_phone)

    row = await _row(tenant_id, kept)
    assert row["summary"] == f"Change this lead's name to “{NAME}”."
    assert row["prior_state"] == {"name": OLD_NAME}
