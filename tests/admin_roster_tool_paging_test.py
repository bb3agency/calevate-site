"""The assistant's client roster pays for the accounts it shows, not for the platform.

`tenant_overview` opens one tenant session per account it returns. The `platform_tenants`
tool called it unpaged and sliced the answer to the model's `limit` afterwards, so a
question about the top of the list walked every account on the platform (34,470 nested
sessions on the shared database, `docs/evidence/deepdive-dbscale.md` §6).

FAILS IF: the cap stops being passed into `tenant_overview` — the walk opens a session for
every organization in the database, which is at least the three made here.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.copilot import service as copilot_service
from apps.api.copilot import tools as copilot_tools
from apps.api.db.session import admin_session


async def test_the_roster_tool_opens_a_session_only_for_the_accounts_it_shows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for _ in range(3):
        await admin_service.create_organization(
            name="Roster Paging Shop",
            slug=f"rps-{uuid.uuid4().hex[:8]}",
            vertical_template="clinic",
            billing_email=None,
            created_by=None,
        )

    opened: list[uuid.UUID] = []
    real_tenant_session = admin_service.tenant_session

    @asynccontextmanager
    async def counting_tenant_session(tenant_id: uuid.UUID, *args: Any, **kwargs: Any) -> Any:
        opened.append(tenant_id)
        async with real_tenant_session(tenant_id, *args, **kwargs) as session:
            yield session

    monkeypatch.setattr(admin_service, "tenant_session", counting_tenant_session)

    answer = await copilot_tools.run_read_tool(
        "platform_tenants",
        '{"limit": 2}',
        context=copilot_tools.ToolContext(tenant_id=None, role="operator"),
        registry=copilot_service._read_tool_registry("admin"),
    )

    assert len(opened) == 2, f"opened {len(opened)} tenant sessions for a 2-row answer"
    total = await _directory_total()
    assert f"Showing 2 of {total} accounts" in answer


async def _directory_total() -> int:
    async with admin_session() as session:
        return await admin_service.tenant_directory_total(session)
