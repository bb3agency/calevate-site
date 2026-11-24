"""The owner's daily summary and the credit expiry sweep stop inside their time budget.

Both walk the whole directory one `tenant_session` at a time. Past `job_timeout` arq cancels
the tick with `TimeoutError` and never retries it (`fleet_walk`'s docstring), so the accounts
after that point got no summary that evening and kept spendable credit past its expiry.
The budgets are monkeypatched to zero, as `worker_fleet_walk_test` does.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.workers import credit_expiry, owner_digest
from apps.workers.fleet_walk import WalkBudget

_TWO_TENANTS = (
    "SELECT CAST('00000000-0000-7000-8000-00000000a001' AS uuid) "
    "UNION ALL SELECT CAST('00000000-0000-7000-8000-00000000a002' AS uuid)"
)


class _Alerts:
    def __init__(self) -> None:
        self.codes: list[str] = []

    def __call__(self, kind: str, code: str, **_: Any) -> None:
        self.codes.append(code)


def _spent() -> WalkBudget:
    return WalkBudget(timedelta(seconds=0))


async def test_credit_expiry_stops_at_its_budget_and_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alerts = _Alerts()
    visited: list[uuid.UUID] = []

    async def _due(*_: Any, **__: Any) -> list[Any]:
        visited.append(uuid.uuid4())
        return []

    monkeypatch.setattr(credit_expiry, "alert", alerts)
    monkeypatch.setattr(credit_expiry, "WalkBudget", lambda *a, **k: _spent())
    monkeypatch.setattr(credit_expiry, "_ALL_TENANTS", _TWO_TENANTS)
    monkeypatch.setattr(credit_expiry, "due_lots", _due)

    result = await credit_expiry.expire_credit_lots({})

    assert visited == [], "a spent budget must stop the walk before the first tenant session"
    assert "'unreached': 2" in result, result
    assert "credit_expiry_truncated" in alerts.codes, alerts.codes


async def test_owner_digests_retry_when_the_budget_runs_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[uuid.UUID] = []

    async def _send_one(tenant_id: uuid.UUID, **_: Any) -> str:
        sent.append(tenant_id)
        return "sent"

    monkeypatch.setattr(owner_digest, "WalkBudget", lambda *a, **k: _spent())
    monkeypatch.setattr(owner_digest, "_OPTED_IN", _TWO_TENANTS)
    monkeypatch.setattr(owner_digest, "send_one", _send_one)

    with pytest.raises(owner_digest.Retry):
        await owner_digest.send_owner_digests({"job_try": 1})
    assert sent == []


async def test_owner_digests_alert_when_the_last_try_is_still_cut_short(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alerts = _Alerts()

    async def _send_one(tenant_id: uuid.UUID, **_: Any) -> str:
        return "sent"

    monkeypatch.setattr(owner_digest, "alert", alerts)
    monkeypatch.setattr(owner_digest, "WalkBudget", lambda *a, **k: _spent())
    monkeypatch.setattr(owner_digest, "_OPTED_IN", _TWO_TENANTS)
    monkeypatch.setattr(owner_digest, "send_one", _send_one)

    result = await owner_digest.send_owner_digests({"job_try": WORKER_MAX_TRIES})

    assert "unreached=2" in result, result
    assert "owner_digest_incomplete" in alerts.codes, alerts.codes
