"""D-694: the assistant is free to the account, up to a daily fair-use cap counted on the
existing AI ledger; over it the client is told plainly and an operator is alarmed once."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from tests.api_security_test import _make_tenant

from apps.api.billing.ai_quota import new_assist_ref, read_ai_quota
from apps.api.billing.models import FREE_ASSIST_FEATURES
from apps.api.copilot import fair_use
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.crm.assist import ASSIST_FEATURE_COPILOT
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session


async def _copilot_usage(tenant_id: UUID, *, ktok: str = "1.000") -> None:
    """One metered assistant answer: the in/out pair `record_ai_assist_usage` writes."""
    ref = new_assist_ref()
    meta = json.dumps({"kind": "ai_assist", "model": "m", "feature": "copilot", "ref": ref})
    async with tenant_session(tenant_id) as session:
        for unit in ("ai_assist_ktok_in", "ai_assist_ktok_out"):
            await session.execute(
                text(
                    "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                    "unit_cost_paid, ref, occurred_at, meta, created_at) VALUES (:id, :tid, "
                    "NULL, :unit, :qty, 0.5, :ref, now(), CAST(:meta AS jsonb), now())"
                ),
                {
                    "id": uuid7(),
                    "tid": tenant_id,
                    "unit": unit,
                    "qty": Decimal(ktok),
                    "ref": ref,
                    "meta": meta,
                },
            )


def test_the_free_feature_is_the_copilots_own_name() -> None:
    assert FREE_ASSIST_FEATURES == (ASSIST_FEATURE_COPILOT,)


async def test_under_the_cap_the_assistant_answers() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    await _copilot_usage(tenant_id)
    async with tenant_session(tenant_id) as session:
        usage = await fair_use.require_copilot_fair_use(session, tenant_id=tenant_id)
    assert usage.messages == 1
    assert usage.ktok == Decimal("2.000")
    assert usage.reached is False


async def test_over_the_cap_it_refuses_plainly_and_alarms_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _slug, _token = await _make_tenant()
    monkeypatch.setattr(get_settings(), "copilot_daily_message_cap", 2)
    fired: list[dict[str, Any]] = []
    monkeypatch.setattr(
        fair_use, "alert", lambda stage, code, **kw: fired.append({"code": code, **kw})
    )
    await _copilot_usage(tenant_id)
    await _copilot_usage(tenant_id)

    for _ in range(2):
        async with tenant_session(tenant_id) as session:
            with pytest.raises(ProblemError) as refused:
                await fair_use.require_copilot_fair_use(session, tenant_id=tenant_id)
        assert refused.value.code == "copilot_daily_limit_reached"
        # Plain words, from the client's side: no internals named.
        for word in ("tenant", "token", "ledger", "API"):
            assert word not in (refused.value.detail or "")
    assert [entry["code"] for entry in fired] == ["copilot_fair_use_reached"]
    assert fired[0]["tenant_id"] == str(tenant_id)


async def test_assistant_use_draws_nothing_from_the_monthly_allowance() -> None:
    """Free means free: the rows stay on the ledger (the brake and the cap read them), but
    the allowance panel — and the overage purchase it drives — never counts them."""
    tenant_id, _slug, _token = await _make_tenant()
    await _copilot_usage(tenant_id, ktok="100.000")
    async with tenant_session(tenant_id) as session:
        quota = await read_ai_quota(session, tenant_id=tenant_id)
    assert quota.used_inr == Decimal("0")
    assert quota.requests_used == 0


def test_the_ist_day_is_the_day() -> None:
    from datetime import UTC, datetime

    day, start, end = fair_use.ist_day_bounds(datetime(2026, 10, 9, 20, 0, tzinfo=UTC))
    # 20:00 UTC is 01:30 IST on the NEXT day.
    assert day == "2026-10-10"
    assert start == datetime(2026, 10, 9, 18, 30, tzinfo=UTC)
    assert (end - start).total_seconds() == 86_400
