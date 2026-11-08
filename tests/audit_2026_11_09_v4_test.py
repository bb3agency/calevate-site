"""Audit round 3, lane V4: time, dates and schedules (D-709, IST is the standard day)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from apps.api.db.base import uuid7
from apps.api.db.session import admin_session, tenant_session
from apps.workers import business_copy as worker
from sqlalchemy import text
from tests.api_security_test import _make_tenant
from tests.business_copy_test import _json, _trial, copy_dict


async def test_a_copy_check_is_queued_once_per_ist_day_across_0530_ist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: the once-a-day key is cut on the UTC date, so the upgrade walk a deploy
    queues at 01:00 IST and the daily walk at 10:44 IST the same Indian day both queue a
    rewrite of one account."""
    _trial(monkeypatch, False)
    tenant_id, _slug, _token = await _make_tenant()
    # 01:00 IST on 10 Nov is 19:30 UTC on 9 Nov; 10:44 IST is 05:14 UTC on 10 Nov.
    early = datetime(2026, 11, 9, 19, 30, tzinfo=UTC)
    daily = datetime(2026, 11, 10, 5, 14, tzinfo=UTC)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO business_copies (id, tenant_id, generated, prompt_version, "
                "last_attempt_at) VALUES (:id, :t, CAST(:g AS jsonb), NULL, :at)"
            ),
            {
                "id": uuid7(),
                "t": tenant_id,
                "g": _json(copy_dict()),
                "at": early - timedelta(days=1),
            },
        )
    assert await worker._due(tenant_id, now=early) is True
    assert await worker._due(tenant_id, now=daily) is True
    async with admin_session() as session:
        keys = (
            (
                await session.execute(
                    text("SELECT dedupe_key FROM outbox_messages WHERE dedupe_key LIKE :k"),
                    {"k": f"business-copy:{tenant_id}:%"},
                )
            )
            .scalars()
            .all()
        )
    assert keys == [f"business-copy:{tenant_id}:2026-11-10"]
