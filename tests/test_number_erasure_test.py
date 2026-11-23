"""A person's erasure takes their number off the account's saved test numbers.

A test call to any number saves it in `organizations.test_numbers` (`campaigns/
workspace_routes.remember_test_number`), where every campaign's and line's Test call offers
it again. The per-subject erasure emptied the test call itself and left the number there,
one tap from ringing the person the certificate said was removed.
"""

from __future__ import annotations

import uuid

from apps.api.compliance.deletion import request_erasure
from apps.api.db.session import tenant_session
from apps.workers.retention import execute_deletion_request
from sqlalchemy import text
from tests.conftest import create_org_with_receptionist


def _phone() -> str:
    return f"+9198761{uuid.uuid4().int % 100000:05d}"


async def _tenant() -> uuid.UUID:
    created = await create_org_with_receptionist(
        name="Test Number Shop",
        slug=f"testnums-{uuid.uuid4().hex[:8]}",
        vertical_template="custom",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return uuid.UUID(str(created["id"]))


async def _test_numbers(tenant_id: uuid.UUID) -> list[str]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT test_numbers FROM organizations WHERE id = :t"), {"t": tenant_id}
            )
        ).one()
    return list(row[0])


async def test_an_erased_persons_number_leaves_the_saved_test_numbers() -> None:
    tenant_id = await _tenant()
    erased, kept = _phone(), _phone()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET test_numbers = :n WHERE id = :t"),
            {"n": [erased, kept], "t": tenant_id},
        )
        record = await request_erasure(session, tenant_id=tenant_id, phone_e164=erased)

    outcome = await execute_deletion_request(
        {}, {"tenant_id": str(tenant_id), "request_id": str(record.id)}
    )

    assert outcome != "not_found"
    assert await _test_numbers(tenant_id) == [kept]


async def test_another_accounts_saved_number_is_untouched() -> None:
    """RLS keeps the arm to the requesting account: the same number saved by a neighbour
    is the neighbour's, and only its own erasure removes it."""
    tenant_id, neighbour_id = await _tenant(), await _tenant()
    phone = _phone()
    for org in (tenant_id, neighbour_id):
        async with tenant_session(org) as session:
            await session.execute(
                text("UPDATE organizations SET test_numbers = :n WHERE id = :t"),
                {"n": [phone], "t": org},
            )
    async with tenant_session(tenant_id) as session:
        record = await request_erasure(session, tenant_id=tenant_id, phone_e164=phone)

    await execute_deletion_request({}, {"tenant_id": str(tenant_id), "request_id": str(record.id)})

    assert await _test_numbers(tenant_id) == []
    assert await _test_numbers(neighbour_id) == [phone]
