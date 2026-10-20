"""The monthly number-rental meter retries a transient failure instead of losing the month.

It runs once a month, so a failure that is only counted and alarmed leaves that month's cost
rows missing for good; the record is idempotent on (number, month), so a retry is free.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.workers import number_rental
from arq import Retry


@pytest.fixture
def failing_meter(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    alarms: list[str] = []

    async def _estate() -> list[tuple[Any, ...]]:
        return [(uuid.uuid4(), uuid.uuid4(), "vobiz", Decimal("1.00"), None)]

    async def _record(*_a: Any, **_kw: Any) -> Any:
        raise RuntimeError("database went away")

    monkeypatch.setattr(number_rental, "_bought_numbers", _estate)
    monkeypatch.setattr(number_rental, "record_number_rental", _record)
    monkeypatch.setattr(number_rental, "alert", lambda _s, code, **_kw: alarms.append(code))
    return alarms


async def test_a_failed_number_is_retried_while_attempts_remain(failing_meter: list[str]) -> None:
    with pytest.raises(Retry):
        await number_rental.meter_number_rentals({"job_try": 1})
    assert failing_meter == []


async def test_the_last_attempt_alarms_instead(failing_meter: list[str]) -> None:
    await number_rental.meter_number_rentals({"job_try": WORKER_MAX_TRIES})
    assert failing_meter == ["number_rentals_incomplete"]
