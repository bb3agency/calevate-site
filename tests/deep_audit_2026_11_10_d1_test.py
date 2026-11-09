"""Deep audit 10 Nov 2026, D1 (web app), the one backend half it needed.

D1-01 (Z9-N1). The rights desk marked an erasure request answered the moment the erasure
was FILED: the client's data-rights page closed the row from the erasure drawer's success
callback, and `rights_desk._assert_erasure_answers` checked only that the linked erasure
was the same person's. An erasure that had not run yet (or never ran) left the desk saying
"answered" and stopped the 90-day clock on data still held. Now an `erased` answer names a
COMPLETED erasure, and the erasure job closes the person's open erasure rows itself, in the
transaction that writes the certificate.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator

import pytest
from apps.api.compliance import rights_desk
from apps.api.compliance.deletion import DELETION_JOB, request_erasure
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session, untenanted_session
from apps.workers.retention import execute_deletion_request
from sqlalchemy import text
from tests.conftest import create_org_with_receptionist

_TENANTS: list[uuid.UUID] = []


@pytest.fixture(scope="module", autouse=True)
def _empty_the_queue() -> Iterator[None]:
    """The erasure jobs these tests queue must not outlive the module (the outbox is
    claimed oldest-first across the whole table)."""
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
    return f"+9198763{uuid.uuid4().int % 100000:05d}"


async def _tenant() -> uuid.UUID:
    created = await create_org_with_receptionist(
        name="Rights Desk Shop",
        slug=f"d1-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    _TENANTS.append(tenant_id)
    return tenant_id


async def _log(tenant_id: uuid.UUID, kind: str, phone: str) -> rights_desk.RightsRequest:
    async with tenant_session(tenant_id) as session:
        return await rights_desk.log_request(
            session,
            tenant_id=tenant_id,
            kind=kind,
            channel="phone",
            phone_e164=phone,
            received_at=None,
            created_by=None,
        )


async def _row(
    tenant_id: uuid.UUID, request_id: uuid.UUID
) -> tuple[str, str | None, uuid.UUID | None]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT status, outcome, deletion_request_id FROM data_rights_requests "
                    "WHERE id = :id"
                ),
                {"id": request_id},
            )
        ).one()
    return str(row[0]), row[1], row[2]


async def test_an_erasure_still_running_does_not_answer_the_request() -> None:
    tenant_id = await _tenant()
    phone = _phone()
    request = await _log(tenant_id, "erasure", phone)
    async with tenant_session(tenant_id) as session:
        filed = await request_erasure(session, tenant_id=tenant_id, phone_e164=phone)
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as refused:
            await rights_desk.close_request(
                session,
                request_id=request.id,
                status="answered",
                outcome="erased",
                deletion_request_id=filed.id,
                closed_by=None,
            )
    assert refused.value.code == "rights_erasure_not_finished"
    assert (await _row(tenant_id, request.id))[0] == "open"


async def test_the_erasure_answers_the_persons_open_request_when_it_completes() -> None:
    tenant_id = await _tenant()
    phone, other = _phone(), _phone()
    erasure = await _log(tenant_id, "erasure", phone)
    access = await _log(tenant_id, "access", phone)
    stranger = await _log(tenant_id, "erasure", other)
    async with tenant_session(tenant_id) as session:
        filed = await request_erasure(session, tenant_id=tenant_id, phone_e164=phone)
    assert (await _row(tenant_id, erasure.id))[0] == "open", "filing is not answering"

    await execute_deletion_request({}, {"tenant_id": str(tenant_id), "request_id": str(filed.id)})

    assert await _row(tenant_id, erasure.id) == ("answered", "erased", filed.id)
    assert (await _row(tenant_id, access.id))[0] == "open", "only an erasure request is answered"
    assert (await _row(tenant_id, stranger.id))[0] == "open", "another person's request stays open"
