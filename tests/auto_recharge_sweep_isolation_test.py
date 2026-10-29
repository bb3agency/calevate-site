"""One tenant's failure in the auto-recharge sweep does not stop the other tenants'."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from apps.workers import razorpay_jobs


async def test_a_crash_for_one_tenant_is_counted_and_the_rest_still_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, second = uuid.uuid4(), uuid.uuid4()
    refreshed: list[UUID] = []

    async def _expire(_tenant_id: UUID) -> int:
        raise RuntimeError("database went away")

    async def _mandates() -> list[tuple[UUID, str, str]]:
        return [(first, "cust_1", "tok_1"), (second, "cust_2", "tok_2")]

    async def _refresh(tenant_id: UUID, _customer: str, _token: str) -> bool:
        if tenant_id == first:
            raise RuntimeError("socket closed")
        refreshed.append(tenant_id)
        return True

    async def _due() -> list[UUID]:
        return []

    monkeypatch.setattr(
        razorpay_jobs, "payment_capability", lambda: SimpleNamespace(creates_orders=True)
    )
    monkeypatch.setattr(razorpay_jobs, "expire_unanswered", _expire)
    monkeypatch.setattr(razorpay_jobs, "pending_mandates", _mandates)
    monkeypatch.setattr(razorpay_jobs, "refresh_pending_mandate", _refresh)
    monkeypatch.setattr(razorpay_jobs, "due_tenants", _due)
    alarms: list[str] = []
    monkeypatch.setattr(razorpay_jobs, "alert", lambda _stage, code, **_kw: alarms.append(code))

    result: dict[str, Any] = await razorpay_jobs.sweep_auto_recharge({})

    assert refreshed == [second]
    assert result["refreshed"] == 1
    assert result["failed"] >= 1
    # Swallowed per tenant, so the job wrapper never sees it: the sweep must raise it.
    assert alarms == ["auto_recharge_sweep_crashed"]
