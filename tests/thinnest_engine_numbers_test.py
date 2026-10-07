"""The admin numbers screen for an engine that rents and attaches numbers in its own console.

`GET /v1/admin/numbers/tenants/{tenant_id}/engine` lists what the engine holds that this
client's agents answer or that nobody answers yet, counts (never lists) numbers other
agents answer, names this client's published agents with the id the console shows, and
carries the console steps. On an engine with no such console it reads nothing.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Sequence
from typing import Any

import pytest
from apps.api.admin import number_routes
from apps.api.admin import service as admin_service
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine.fake import FakeEngine
from apps.api.engine.hosted_platform import THINNEST_NUMBER_CONSOLE
from apps.api.main import app
from calevate_shared.engine import ProvisionedNumber
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

OUR_REF = f"ag_{uuid.uuid4().hex[:8]}"


class _NumbersEngine(FakeEngine):
    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self.listed = 0

    async def list_engine_numbers(self) -> Sequence[ProvisionedNumber]:
        self.listed += 1
        return [
            ProvisionedNumber(
                e164="+918012345678",
                provider="ThinnestAI",
                engine_owned=True,
                answering_agent_ref=OUR_REF,
            ),
            ProvisionedNumber(e164="+918012345679", provider="ThinnestAI", engine_owned=True),
            ProvisionedNumber(
                e164="+918012345670",
                provider="vobiz",
                engine_owned=False,
                answering_agent_ref="ag_someone_else",
            ),
        ]


def _selected(instance: FakeEngine) -> Iterator[FakeEngine]:
    import apps.api.engine as engine_module

    previous = dict(engine_module._instances)
    engine_module._instances["fake"] = instance
    try:
        yield instance
    finally:
        engine_module._instances.clear()
        engine_module._instances.update(previous)


@pytest.fixture
def numbers_engine() -> Iterator[_NumbersEngine]:
    yield from _selected(_NumbersEngine())


async def _admin_headers() -> dict[str, str]:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    return {"Authorization": f"Bearer dev:admin:{admin_id}"}


async def _tenant_with_published_agent() -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name="Numbers Clinic",
        slug=f"num-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    async with tenant_session(created["id"]) as session:
        await session.execute(
            text("UPDATE agents SET engine = 'fake', engine_agent_ref = :r WHERE id = :a"),
            {"r": OUR_REF, "a": created["agent_id"]},
        )
    return created["id"], created["agent_id"]


async def _get(tenant_id: uuid.UUID) -> dict[str, Any]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as client:
        response = await client.get(
            f"/v1/admin/numbers/tenants/{tenant_id}/engine", headers=await _admin_headers()
        )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_an_engine_without_a_console_reads_nothing(
    numbers_engine: _NumbersEngine,
) -> None:
    tenant_id, _agent_id = await _tenant_with_published_agent()
    body = await _get(tenant_id)
    assert body["managed_in_engine_console"] is False
    assert body["numbers"] == [] and body["agents"] == [] and body["steps"] == []
    assert numbers_engine.listed == 0


async def test_console_numbers_show_ours_and_the_unassigned_and_hide_the_rest(
    numbers_engine: _NumbersEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        number_routes, "engine_number_console", lambda engine: THINNEST_NUMBER_CONSOLE
    )
    tenant_id, agent_id = await _tenant_with_published_agent()
    body = await _get(tenant_id)

    assert body["managed_in_engine_console"] is True
    assert body["platform"] == "ThinnestAI"
    assert body["steps"] == list(THINNEST_NUMBER_CONSOLE.steps)
    numbers = {n["e164"]: n for n in body["numbers"]}
    assert set(numbers) == {"+918012345678", "+918012345679"}
    assert numbers["+918012345678"]["agent_id"] == str(agent_id)
    assert numbers["+918012345678"]["unassigned"] is False
    assert numbers["+918012345679"]["unassigned"] is True
    assert body["other_numbers"] == 1
    assert body["agents"] == [
        {
            "agent_id": str(agent_id),
            "name": body["agents"][0]["name"],
            "engine_agent_ref": OUR_REF,
            "answers_a_number": True,
        }
    ]
