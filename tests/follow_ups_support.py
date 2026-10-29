"""Helpers for tests that need a Follow-up (D-940)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from apps.api.db.session import tenant_session
from apps.api.follow_ups import definition as d
from apps.api.follow_ups import runner, service
from sqlalchemy import text


async def set_new_lead_call(tenant_id: UUID, **call: Any) -> UUID:
    """Publish "Call new leads" with its one call step's fields replaced by `call` (the
    agent, wait and retries the old calling plan held). Returns the Follow-up's id."""
    async with tenant_session(tenant_id) as session:
        await runner.ensure_call_new_leads(session, tenant_id=tenant_id)
        follow_up_id = UUID(
            str(
                (
                    await session.execute(
                        text("SELECT id FROM follow_ups WHERE starter = 'call_new_leads'")
                    )
                ).scalar_one()
            )
        )
        row = await service.get(session, follow_up_id)
        step = {**runner.DEFAULT_NEW_LEAD_STEPS[0], **_jsonable(call)}
        row = await service.save_draft(
            session,
            follow_up_id,
            trigger=row.trigger,
            steps=d.load_steps([step]),
            settings=row.settings,
        )
        await service.publish(
            session,
            follow_up_id,
            tenant_id=tenant_id,
            expected_updated_at=row.updated_at,
            user_id=None,
        )
    return follow_up_id


async def publish(
    tenant_id: UUID,
    *,
    steps: list[dict[str, Any]],
    trigger: dict[str, Any] | None = None,
    settings: dict[str, Any] | None = None,
    name: str = "Test follow-up",
) -> UUID:
    """A new Follow-up, published live. Returns its id."""
    async with tenant_session(tenant_id) as session:
        row = await service.create(
            session,
            tenant_id=tenant_id,
            name=name,
            trigger=d.load_trigger(trigger or {"kind": "manual"}),
            steps=d.load_steps(steps),
            settings=d.load_settings(settings or {}),
            starter=None,
            user_id=None,
        )
        await service.publish(
            session, row.id, tenant_id=tenant_id, expected_updated_at=row.updated_at, user_id=None
        )
    return row.id


def _jsonable(values: dict[str, Any]) -> dict[str, Any]:
    return {k: str(v) if isinstance(v, UUID) else v for k, v in values.items()}


__all__ = ["publish", "set_new_lead_call"]
