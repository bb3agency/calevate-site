"""A call that showed the business's own number is reached by its caller's erasure.

A client that forwards its line to the agent can deliver a call whose calling party is the
client's published number (D-746): `calls.caller_id_hidden` is set, `from_e164` holds the
business number, and the post-call pipeline files the lead under the call-back number the
caller gave and links the call to it (`calls.lead_id`). No number column on that call is the
person's, so the erasure finds its calls through the person's leads as well.
"""

from __future__ import annotations

import uuid
from typing import Any

from apps.api.compliance.deletion import request_erasure
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.workers.retention import REDACTED_MARK, execute_deletion_request
from sqlalchemy import text
from tests.campaigns_test import _tenant

CALLER_LINE = "please call me back on my own number"
BUSINESS_LINE = "+914012345678"


def _phone() -> str:
    return f"+9198764{uuid.uuid4().int % 100000:05d}"


async def _lead(tenant_id: uuid.UUID, agent_id: uuid.UUID, phone: str) -> uuid.UUID:
    lead_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status) "
                "VALUES (:i, :t, :a, :p, 'Ravi', 'inbound_call', 'new')"
            ),
            {"i": lead_id, "t": tenant_id, "a": agent_id, "p": phone},
        )
    return lead_id


async def _hidden_caller_call(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, lead_id: uuid.UUID
) -> uuid.UUID:
    """A forwarded inbound call showing the business's number, filed under `lead_id`."""
    call_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                "status, from_e164, to_e164, caller_id_hidden, lead_id, started_at, ended_at, "
                "duration_s, summary, created_at, updated_at) "
                "VALUES (:id, :t, :a, :e, 'inbound', 'completed', :biz, :biz, true, :lead, "
                "now() - interval '10 minutes', now(), 60, :sum, now(), now())"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": f"exec_{uuid.uuid4().hex[:12]}",
                "biz": BUSINESS_LINE,
                "lead": lead_id,
                "sum": "The caller asked to be called back.",
            },
        )
        await session.execute(
            text(
                "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, text, "
                "text_redacted, created_at, updated_at) "
                "VALUES (:id, :t, :c, 0, 'caller', :txt, :txt, now(), now())"
            ),
            {"id": uuid.uuid4(), "t": tenant_id, "c": call_id, "txt": CALLER_LINE},
        )
    return call_id


async def _content(tenant_id: uuid.UUID, call_id: uuid.UUID) -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        turns = (
            (
                await session.execute(
                    text("SELECT text FROM transcript_turns WHERE call_id = :c ORDER BY idx"),
                    {"c": call_id},
                )
            )
            .scalars()
            .all()
        )
        summary = (
            await session.execute(text("SELECT summary FROM calls WHERE id = :c"), {"c": call_id})
        ).scalar_one()
    return {"turns": list(turns), "summary": summary}


async def _erase(tenant_id: uuid.UUID, phone: str) -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        made = await request_erasure(session, tenant_id=tenant_id, phone_e164=phone)
    await execute_deletion_request({}, {"tenant_id": str(tenant_id), "request_id": str(made.id)})
    async with tenant_session(tenant_id) as session:
        proof = (
            await session.execute(
                text("SELECT proof FROM deletion_requests WHERE id = :r"), {"r": made.id}
            )
        ).scalar_one()
    return dict(proof)


async def test_a_call_showing_the_business_number_is_erased_through_its_lead() -> None:
    subject, neighbour = _phone(), _phone()
    tenant_id, agent_id = await _tenant()
    mine = await _hidden_caller_call(tenant_id, agent_id, await _lead(tenant_id, agent_id, subject))
    theirs = await _hidden_caller_call(
        tenant_id, agent_id, await _lead(tenant_id, agent_id, neighbour)
    )

    proof = await _erase(tenant_id, subject)

    erased = await _content(tenant_id, mine)
    assert erased["turns"] == [REDACTED_MARK], erased
    assert erased["summary"] is None, erased
    assert len(proof["scope"]["calls"]) == 1, proof["scope"]
    # Another caller whose call showed the same business number is not this person.
    kept = await _content(tenant_id, theirs)
    assert kept["turns"] == [CALLER_LINE], kept


async def test_a_second_erasure_counts_no_turn_the_first_already_erased() -> None:
    """The second request finds the call again through `erased_subject_ref`; its
    certificate must not claim the turns the first one cleared."""
    subject = _phone()
    tenant_id, agent_id = await _tenant()
    await _hidden_caller_call(tenant_id, agent_id, await _lead(tenant_id, agent_id, subject))

    first = await _erase(tenant_id, subject)
    second = await _erase(tenant_id, subject)

    assert first["scope"]["transcript_turns_erased"] == 1, first["scope"]
    assert second["scope"]["transcript_turns_erased"] == 0, second["scope"]
