"""Saving an in-call action on a free-trial account, through the real route (D-697, D-700).

A trial agent lives in our developer workspace (its handle carries no `@org_…`), and the
save pushes the agent's actions to the voice platform straight away. Whatever that push
meets, the client's save must stand: the action is written and the drift sweep retries.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.actions import credentials as creds
from apps.api.billing.trials import start_trial
from apps.api.db.session import tenant_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.api_security_test import _make_tenant
from tests.thinnest_in_call_actions_test import vendor  # noqa: F401 — the fixture

pytestmark = [pytest.mark.rls]

#: What the Actions form sends for "Book a time" with one AI-filled parameter.
BOOK_A_TIME: dict[str, Any] = {
    "kind": "calendar",
    "provider": "google",
    "name": "book_a_slot",
    "description": "Check free times, then book once the caller agrees to one.",
    "trigger": "during_call",
    "pre_call_message": None,
    "params": [{"name": "time", "source": "ai", "description": "time of booking"}],
    "config": {
        "operation": "book",
        "calendar_id": "primary",
        "start_param": "time",
        "end_param": None,
        "duration_min": 60,
        "summary_param": None,
    },
}


async def _trial_agent_on_the_platform() -> tuple[uuid.UUID, uuid.UUID, str, str, uuid.UUID]:
    tenant_id, slug, token = await _make_tenant()
    async with tenant_session(tenant_id) as session:
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar_one()
        await start_trial(session, tenant_id=tenant_id, days=7, actor_user_id=None)
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('thinnest', :ref, :tid, :aid, true, "
                "now(), now())"
            ),
            {"ref": f"ag_{uuid.uuid4()}", "tid": tenant_id, "aid": agent_id},
        )
        calendar = await creds.create_credential(
            session,
            tenant_id=tenant_id,
            kind="google_calendar",
            label="Google Calendar",
            secret="1//test-refresh-token",
            non_secret={},
        )
    return tenant_id, agent_id, slug, token, calendar.id


async def test_a_trial_account_saves_a_calendar_booking_action(vendor: Any) -> None:  # noqa: F811
    tenant_id, agent_id, slug, token, calendar_id = await _trial_agent_on_the_platform()
    body = {**BOOK_A_TIME, "credential_id": str(calendar_id)}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        saved = await http.post(
            f"/v1/agents/{agent_id}/actions",
            json=body,
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug},
        )
    assert saved.status_code == 201, saved.text
    async with tenant_session(tenant_id) as session:
        kinds = (await session.execute(text("SELECT kind FROM action_tools"))).scalars().all()
    assert kinds == ["calendar"]


def test_a_log_extra_with_a_record_attribute_name_is_renamed_not_raised() -> None:
    """The defect behind the 500: an audit summary carrying `name` overwrote a LogRecord
    attribute and the stdlib raised KeyError after the change was written."""
    import logging

    from apps.api.core.logging import safe_extra

    extra = safe_extra({"name": "book_a_slot", "module": "x", "kind": "calendar"})
    assert extra == {"name_": "book_a_slot", "module_": "x", "kind": "calendar"}
    logging.getLogger("tests.safe_extra").info("audit", extra=extra)
