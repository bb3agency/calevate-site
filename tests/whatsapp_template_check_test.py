"""A template left pending at Meta is read back directly, and alarms if it stays pending."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from apps.api.db.session import tenant_session
from apps.api.whatsapp import graph, templates
from apps.workers import whatsapp_meta
from sqlalchemy import text
from tests.conftest import create_org_with_receptionist


async def _template(*, submitted_hours_ago: float) -> tuple[UUID, UUID]:
    created = await create_org_with_receptionist(
        name="Template Shop",
        slug=f"wa-tpl-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        created_by=None,
    )
    tenant_id = UUID(str(created["id"]))
    account_id, template_id = uuid.uuid4(), uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO whatsapp_accounts (id, tenant_id, waba_id, onboarding, status) "
                "VALUES (:i, :t, '1' || abs(hashtext(CAST(:i AS text)))::text, 'new', "
                "'connected')"
            ),
            {"i": account_id, "t": tenant_id},
        )
        await session.execute(
            text(
                "INSERT INTO whatsapp_templates (id, tenant_id, account_id, name, language, "
                "category, body, variables, origin, status, meta_template_id, submitted_at, "
                "created_at, updated_at) VALUES (:id, :t, :a, 'thanks', 'en', 'UTILITY', "
                "'Thank you', '[]'::jsonb, 'client', 'pending', '123456789', :at, now(), now())"
            ),
            {
                "id": template_id,
                "t": tenant_id,
                "a": account_id,
                "at": datetime.now(UTC) - timedelta(hours=submitted_hours_ago),
            },
        )
    return tenant_id, template_id


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"word": "APPROVED", "scheduled": [], "alarms": []}

    async def _token(*_a: Any, **_kw: Any) -> str:
        return "token"

    async def _status(*, template_id: str, token: str) -> tuple[str | None, str | None]:
        return state["word"], None

    async def _enqueue(job: str, payload: dict[str, Any], **kw: Any) -> str:
        state["scheduled"].append((job, payload["check"], kw["_defer_until"]))
        return "job"

    monkeypatch.setattr(whatsapp_meta.accounts, "account_token", _token)
    monkeypatch.setattr(graph, "template_status", _status)
    monkeypatch.setattr(whatsapp_meta, "enqueue", _enqueue)
    monkeypatch.setattr(
        whatsapp_meta, "alert", lambda _st, code, **_kw: state["alarms"].append(code)
    )
    return state


def _payload(tenant_id: UUID, template_id: UUID, check: int = 0) -> dict[str, Any]:
    return {"tenant_id": str(tenant_id), "template_id": str(template_id), "check": check}


async def _status_of(tenant_id: UUID, template_id: UUID) -> str:
    async with tenant_session(tenant_id) as session:
        return str(
            (
                await session.execute(
                    text("SELECT status FROM whatsapp_templates WHERE id = :id"),
                    {"id": template_id},
                )
            ).scalar_one()
        )


async def test_a_check_before_review_is_over_waits_for_it(wired: dict[str, Any]) -> None:
    tenant_id, template_id = await _template(submitted_hours_ago=1)
    result = await whatsapp_meta.check_whatsapp_template({}, _payload(tenant_id, template_id))
    assert result == "scheduled"
    ((job, check, due),) = wired["scheduled"]
    assert job == templates.TEMPLATE_CHECK_JOB
    assert check == 0
    assert due > datetime.now(UTC) + timedelta(hours=23)


async def test_a_lost_verdict_is_read_from_meta_and_recorded(wired: dict[str, Any]) -> None:
    tenant_id, template_id = await _template(submitted_hours_ago=30)
    result = await whatsapp_meta.check_whatsapp_template({}, _payload(tenant_id, template_id))
    assert result == "approved"
    assert await _status_of(tenant_id, template_id) == "approved"
    assert wired["alarms"] == []


async def test_still_pending_after_the_last_check_alarms(wired: dict[str, Any]) -> None:
    wired["word"] = "PENDING"
    tenant_id, template_id = await _template(submitted_hours_ago=100)
    early = await whatsapp_meta.check_whatsapp_template({}, _payload(tenant_id, template_id))
    assert early == "still_pending"
    assert [check for _, check, _ in wired["scheduled"]] == [1]

    last = whatsapp_meta.TEMPLATE_CHECKS - 1
    result = await whatsapp_meta.check_whatsapp_template(
        {}, _payload(tenant_id, template_id, check=last)
    )
    assert result == "stuck_pending"
    assert wired["alarms"] == ["whatsapp_templates_stuck_pending"]


async def test_submitting_a_pending_template_queues_its_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, template_id = await _template(submitted_hours_ago=0)

    async def _create(**_kw: Any) -> tuple[str, str]:
        return "987654321", "PENDING"

    monkeypatch.setattr(graph, "create_template", _create)
    async with tenant_session(tenant_id) as session:
        status = await templates.submit(
            session, template_id=template_id, waba_id="1", token="token"
        )
    assert status == "pending"
    async with tenant_session(tenant_id) as session:
        queued = (
            await session.execute(
                text(
                    "SELECT count(*) FROM outbox_messages WHERE job = :job "
                    "AND payload->>'template_id' = :tid"
                ),
                {"job": templates.TEMPLATE_CHECK_JOB, "tid": str(template_id)},
            )
        ).scalar_one()
    assert queued == 1
