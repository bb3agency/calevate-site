"""Backend audit 10 Nov 2026, lane Z9: compliance and data rights.

Z9-01. A DPDP erasure whose one job failed stayed open for good. `execute_deletion_request`
is queued once, with the request, runs in one transaction and has no `arq.Retry`, so a
run that raises is finished by arq on its first attempt. Filing the erasure again deduped
onto the open request and queued nothing, and the hourly overdue walk only paged. Both now
queue the job again, at most once an hour, and the job locks its request so a re-driven
copy that meets the original runs once.

Z9-02. The subject access export carried one CRM record per number, though a business with
several agents holds one per agent; the others' names and captured details were withheld.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from apps.api.compliance.deletion import (
    DELETION_JOB,
    request_erasure,
)
from apps.api.compliance.export import build_subject_export
from apps.api.compliance.export_routes import SubjectExportOut
from apps.api.db.session import tenant_session, untenanted_session
from apps.workers import dispatcher
from apps.workers.retention import execute_deletion_request
from sqlalchemy import text
from tests.conftest import create_org_with_receptionist

_TENANTS: list[uuid.UUID] = []


@pytest.fixture(scope="module", autouse=True)
def _empty_the_queue() -> Iterator[None]:
    """`outbox_messages` is claimed oldest-first across the whole table, so the jobs these
    tests queue must not outlive the module."""
    yield
    if not _TENANTS:
        return

    async def _drop() -> None:
        async with untenanted_session() as session:
            await session.execute(
                text(
                    "DELETE FROM outbox_messages WHERE job = :job "
                    "AND payload->>'tenant_id' = ANY(:t)"
                ),
                {"job": DELETION_JOB, "t": [str(t) for t in _TENANTS]},
            )

    asyncio.run(_drop())


def _phone() -> str:
    return f"+9198762{uuid.uuid4().int % 100000:05d}"


async def _tenant() -> uuid.UUID:
    created = await create_org_with_receptionist(
        name="Erasure Redrive Shop",
        slug=f"z9-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    _TENANTS.append(tenant_id)
    return tenant_id


async def _age(tenant_id: uuid.UUID, request_id: uuid.UUID, age: timedelta) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE deletion_requests SET requested_at = :ts WHERE id = :id"),
            {"ts": datetime.now(UTC) - age, "id": request_id},
        )


async def _jobs(request_id: uuid.UUID) -> int:
    async with untenanted_session() as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM outbox_messages WHERE job = :job "
                        "AND payload->>'request_id' = :rid"
                    ),
                    {"job": DELETION_JOB, "rid": str(request_id)},
                )
            ).scalar_one()
        )


async def test_refiling_an_erasure_whose_job_died_queues_it_again() -> None:
    tenant_id = await _tenant()
    phone = _phone()
    async with tenant_session(tenant_id) as session:
        first = await request_erasure(session, tenant_id=tenant_id, phone_e164=phone)
    assert await _jobs(first.id) == 1
    await _age(tenant_id, first.id, timedelta(hours=1, minutes=5))

    async with tenant_session(tenant_id) as session:
        again = await request_erasure(session, tenant_id=tenant_id, phone_e164=phone)
    assert again.already_open and again.id == first.id
    assert await _jobs(first.id) == 2, "the re-filing deduped onto a request nothing will run"

    async with tenant_session(tenant_id) as session:
        await request_erasure(session, tenant_id=tenant_id, phone_e164=phone)
    assert await _jobs(first.id) == 2, "one re-drive per hour, not one per click"


async def test_refiling_a_fresh_request_queues_nothing_more() -> None:
    tenant_id = await _tenant()
    phone = _phone()
    async with tenant_session(tenant_id) as session:
        first = await request_erasure(session, tenant_id=tenant_id, phone_e164=phone)
        await request_erasure(session, tenant_id=tenant_id, phone_e164=phone)
    assert await _jobs(first.id) == 1


async def test_the_hourly_overdue_walk_queues_a_stalled_erasure_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = await _tenant()

    async def _only() -> list[uuid.UUID]:
        return [tenant_id]

    monkeypatch.setattr(dispatcher, "_all_tenants", _only)
    alerts: list[tuple[str, str]] = []

    def _alert(kind: str, code: str, *, detail: str = "", **kw: Any) -> None:
        alerts.append((code, detail))

    monkeypatch.setattr(dispatcher, "alert", _alert)
    async with tenant_session(tenant_id) as session:
        record = await request_erasure(session, tenant_id=tenant_id, phone_e164=_phone())
    await _age(tenant_id, record.id, dispatcher.ERASURE_OVERDUE_AFTER + timedelta(minutes=5))

    await dispatcher.report_overdue_erasures({})
    assert await _jobs(record.id) == 2, "the walk paged and left the erasure unrun"
    assert any(code == "erasure_requests_overdue" and "1 job(s)" in d for code, d in alerts)

    await dispatcher.report_overdue_erasures({})
    assert await _jobs(record.id) == 2, "the next tick in the same hour queues it again"


async def test_a_redriven_copy_meeting_the_original_runs_once() -> None:
    """The job locks its request row: a second copy waits for the first to commit and then
    finds the request completed, rather than reading it open and erasing again."""
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        record = await request_erasure(session, tenant_id=tenant_id, phone_e164=_phone())
    payload = {"tenant_id": str(tenant_id), "request_id": str(record.id)}

    holder_has_row = asyncio.Event()
    release = asyncio.Event()

    async def _first_run_completing() -> None:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("SELECT 1 FROM deletion_requests WHERE id = :id FOR UPDATE"),
                {"id": record.id},
            )
            await session.execute(
                text("UPDATE deletion_requests SET completed_at = now() WHERE id = :id"),
                {"id": record.id},
            )
            holder_has_row.set()
            await release.wait()

    holder = asyncio.create_task(_first_run_completing())
    await holder_has_row.wait()
    second = asyncio.create_task(execute_deletion_request({}, payload))
    await asyncio.sleep(0.5)
    release.set()
    await holder
    assert await asyncio.wait_for(second, timeout=30) == "already_completed"


async def test_a_subject_export_discloses_every_lead_record_not_only_the_newest() -> None:
    """Z9-02. `leads` is unique per (tenant, number, agent), so a business with an inbound
    and an outbound agent holds two records for one person. The export carried only the
    newest and a count; the other record's name and captured details were never shown to
    the person asking what is held about them."""
    tenant_id = await _tenant()
    phone = _phone()
    async with tenant_session(tenant_id) as session:
        agent_id = (
            await session.execute(text("SELECT id FROM agents ORDER BY created_at LIMIT 1"))
        ).scalar_one()
        # A second agent of the same business: a copy of the first under a new id.
        other_id = uuid.uuid4()
        await session.execute(
            text(
                "INSERT INTO agents SELECT (jsonb_populate_record(NULL::agents, to_jsonb(a) "
                "|| jsonb_build_object('id', CAST(:new AS text), 'engine_agent_ref', NULL))).* "
                "FROM agents a WHERE a.id = :a"
            ),
            {"new": other_id, "a": agent_id},
        )
        for name, agent, data, age in (
            ("Ravi", agent_id, '{"intent": "book"}', timedelta(days=3)),
            ("Ravi Kumar", other_id, '{"budget": "high"}', timedelta(0)),
        ):
            await session.execute(
                text(
                    "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, "
                    "status, data, call_count, created_at, updated_at) VALUES "
                    "(gen_random_uuid(), :t, :a, :phone, :name, 'inbound_call', 'new', "
                    "CAST(:data AS jsonb), 1, now() - :age, now() - :age)"
                ),
                {
                    "t": tenant_id,
                    "a": agent,
                    "phone": phone,
                    "name": name,
                    "data": data,
                    "age": age,
                },
            )
        document = await build_subject_export(session, tenant_id=tenant_id, phone_e164=phone)

    SubjectExportOut.model_validate(document)
    assert document["counts"]["leads"] == 2
    assert document["lead"]["name"] == "Ravi Kumar"
    assert [lead["name"] for lead in document.get("leads", [])] == ["Ravi Kumar", "Ravi"], (
        "the older record's name and details were left out of the disclosure"
    )
    assert document["leads"][1]["data"] == {"intent": "book"}
