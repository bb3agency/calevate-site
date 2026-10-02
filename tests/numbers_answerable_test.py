"""`GET /v1/campaigns/numbers`'s `answerable` is the whole chain a call follows (PG6).

It used to be `engine_number_ref IS NOT NULL` alone, so a number with no agent on it, or
one the carrier had never been told to send to our answer URL, said "Ready to answer" to
the client about to forward their clinic's line to it.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from sqlalchemy import text
from tests.campaign_route_wrappers_test import (
    NUMBERS,
    _client,
    _headers,
    _leave_the_platform_quiet,  # noqa: F401  — the module's cleanup, applied here too
    _tenant,
)


async def _number(
    tenant_id: uuid.UUID,
    *,
    agent_id: uuid.UUID | None,
    engine_ref: str | None,
    binding_id: str | None,
) -> str:
    number_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, agent_id, e164, series, dlt_status, "
                "engine_number_ref, carrier_binding_id, created_at, updated_at) "
                "VALUES (:id, :tid, :aid, :e, 'standard', 'registered', :ref, :bind, "
                "now(), now())"
            ),
            {
                "id": number_id,
                "tid": tenant_id,
                "aid": agent_id,
                "e": f"+9180{uuid.uuid4().int % 10**8:08d}",
                "ref": engine_ref,
                "bind": binding_id,
            },
        )
    return str(number_id)


@pytest.mark.parametrize(
    ("with_agent", "engine_ref", "binding_id", "answerable"),
    [
        (True, "vz-num-1", "app-1", True),
        (False, "vz-num-1", "app-1", False),
        (True, None, "app-1", False),
        (True, "vz-num-1", None, False),
    ],
    ids=["whole-chain", "no-agent", "no-engine-record", "no-carrier-binding"],
)
async def test_answerable_needs_every_link(
    with_agent: bool, engine_ref: str | None, binding_id: str | None, answerable: bool
) -> None:
    tenant_id, agent_id, slug = await _tenant()
    number_id = await _number(
        tenant_id,
        agent_id=agent_id if with_agent else None,
        engine_ref=engine_ref,
        binding_id=binding_id,
    )
    async with _client() as http:
        response = await http.get(NUMBERS, headers=await _headers(tenant_id, slug))
    assert response.status_code == 200, response.text
    rows = {row["id"]: row for row in response.json()}
    assert rows[number_id]["answerable"] is answerable
