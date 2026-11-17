"""An account whose first copy failed on our side is retried daily at our cost.

A failed first run (`answer_unusable`) left `generated` NULL, and only a copy written under an
older prompt counted as behind, so such an account waited 15 days between tries, or for ever
on a trial (the scheduled refresh skips trials).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from apps.api.db.base import uuid7
from apps.api.db.session import admin_session, tenant_session
from apps.workers import business_copy as worker
from sqlalchemy import text
from tests.api_security_test import _make_tenant
from tests.business_copy_test import _json, _trial, copy_dict
from tests.conftest import make_tenant_with_pip


async def _row(
    tenant_id: UUID,
    *,
    generated: str | None,
    attempted: datetime,
    stop_reason: str | None = "answer_unusable",
) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO business_copies (id, tenant_id, generated, prompt_version, "
                "last_attempt_at, stop_reason) VALUES (:id, :t, CAST(:g AS jsonb), :v, :at, "
                ":stop)"
            ),
            {
                "id": uuid7(),
                "t": tenant_id,
                "g": generated,
                "v": None if generated is None else worker.PROMPT_VERSION,
                "at": attempted,
                "stop": stop_reason,
            },
        )


async def test_a_missing_copy_stopped_by_a_used_up_allowance_waits_like_any_other(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The client's own limit, not our failure: no free daily retry."""
    _trial(monkeypatch, False)
    tenant_id, _slug, _token = await _make_tenant()
    now = datetime(2026, 11, 10, 5, 14, tzinfo=UTC)
    await _row(
        tenant_id,
        generated=None,
        attempted=now - timedelta(days=1),
        stop_reason="allowance_used_up",
    )
    assert await worker._due(tenant_id, now=now) is False


async def test_a_trial_account_with_no_copy_is_due_the_day_after_its_failed_first_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _trial(monkeypatch, True)
    tenant_id, _slug, _token = await _make_tenant()
    now = datetime(2026, 11, 10, 5, 14, tzinfo=UTC)
    await _row(tenant_id, generated=None, attempted=now - timedelta(days=1))
    assert await worker._due(tenant_id, now=now) is True


async def test_a_prompt_bump_after_the_days_check_still_queues_the_rewrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production, 9 Nov 2026: the 10:44 walk spent the day's key on the old prompt's check,
    the deploy's upgrade walk found it taken, and the account was not rewritten that day."""
    _trial(monkeypatch, False)
    tenant_id, _slug, _token = await make_tenant_with_pip()
    now = datetime(2026, 11, 10, 8, 0, tzinfo=UTC)
    await _row(tenant_id, generated=None, attempted=now - timedelta(days=20), stop_reason=None)
    assert await worker._due(tenant_id, now=now) is True
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE business_copies SET generated = CAST(:g AS jsonb), prompt_version = :v, "
                "stop_reason = NULL"
            ),
            {"g": _json(copy_dict()), "v": worker.PROMPT_VERSION - 1},
        )
    assert await worker._due(tenant_id, now=now) is True
    async with admin_session() as session:
        keys = set(
            (
                await session.execute(
                    text("SELECT dedupe_key FROM outbox_messages WHERE dedupe_key LIKE :k"),
                    {"k": f"business-copy:{tenant_id}:%"},
                )
            )
            .scalars()
            .all()
        )
    day = f"business-copy:{tenant_id}:2026-11-10"
    assert keys == {day, f"{day}:v{worker.PROMPT_VERSION}"}


async def test_a_current_copy_tried_yesterday_is_not_due(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _trial(monkeypatch, False)
    tenant_id, _slug, _token = await _make_tenant()
    now = datetime(2026, 11, 10, 5, 14, tzinfo=UTC)
    await _row(tenant_id, generated=_json(copy_dict()), attempted=now - timedelta(days=1))
    assert await worker._due(tenant_id, now=now) is False


async def test_the_scheduled_retry_of_a_missing_copy_is_ours_to_pay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _trial(monkeypatch, False)
    tenant_id, _slug, _token = await _make_tenant()
    await _row(tenant_id, generated=None, attempted=datetime.now(UTC) - timedelta(days=1))
    held = await worker.claim(tenant_id, "scheduled")
    assert held is not None and held.behind is True
    assert await worker._absorbed(tenant_id, "scheduled", behind=held.behind) is True
