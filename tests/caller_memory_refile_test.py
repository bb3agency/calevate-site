"""The repair migration f5a9c3e1d7b2 queues for retired caller notes, and its undo (L5-02).

Notes from outbound calls were filed under the business's own number. Nothing writes notes
now (D-973), but rows already on file are erased and exported by the person's number until
the table is dropped, so they must be filed under the person called.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.compliance.caller_ref import active_caller_ref
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.workers.caller_memory_refile import FILE_UNDER_CALLING_NUMBER, refile_caller_memories
from sqlalchemy import text
from tests.conftest import create_org_with_receptionist, insert_caller_memory

pytestmark = pytest.mark.anyio

#: Our calling number on an outbound call, and the person it rang.
OUR_LINE = "+914012345678"
CALLED = "+919876501234"


async def _outbound_call(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> uuid.UUID:
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                "status, from_e164, to_e164, ended_at, created_at, updated_at) VALUES "
                "(:id, :tid, :aid, :ec, 'outbound', 'completed', :from_e164, :to_e164, "
                ":ended, now(), now())"
            ),
            {
                "id": call_id,
                "tid": tenant_id,
                "aid": agent_id,
                "ec": f"exec_{uuid.uuid4().hex[:10]}",
                "from_e164": OUR_LINE,
                "to_e164": CALLED,
                "ended": datetime.now(UTC) - timedelta(hours=1),
            },
        )
        await session.commit()
    return call_id


async def _filed_under(tenant_id: uuid.UUID) -> str:
    async with tenant_session(tenant_id) as session:
        return str(
            (await session.execute(text("SELECT subject_ref FROM caller_memories"))).scalar_one()
        )


async def test_notes_filed_under_our_own_line_are_moved_to_the_person_and_back() -> None:
    created = await create_org_with_receptionist(
        name="Refile Estates",
        slug=f"refile-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    call_id = await _outbound_call(tenant_id, agent_id)
    await insert_caller_memory(
        tenant_id, agent_id, phone=OUR_LINE, fact="wants a call back", source_call_id=call_id
    )

    payload = {"tenant_id": str(tenant_id)}
    assert await refile_caller_memories({}, payload) == "moved=1 left=0"
    assert await _filed_under(tenant_id) == active_caller_ref(tenant_id, CALLED).ref
    undo = {**payload, "file_under": FILE_UNDER_CALLING_NUMBER}
    await refile_caller_memories({}, undo)
    assert await _filed_under(tenant_id) == active_caller_ref(tenant_id, OUR_LINE).ref
