"""A lead that arrives when it cannot be called is called when the next window opens (D-666).

Outside 09:00-21:00 IST, during a maintenance drain or under the platform halt, the gate
refuses the dial. The lead was always kept; now the call is booked as a call-back for the
next allowed time instead of being dropped:

* calling hours: the next 09:00 IST;
* a drain: the window's announced end, moved into calling hours;
* the halt: a re-check one `callbacks.service.RETRY_AFTER` later.

Nothing is bypassed: the call-back fires through `check_dispatch` like every other one, and
a refusal about the PERSON (DNC, consent) is still a plain refusal with no call-back.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from apps.api.callbacks.service import RETRY_AFTER
from apps.api.compliance.service import (
    BIG_RED_SWITCH_RULE,
    CALLING_HOURS_RULE,
    MAINTENANCE_DRAIN_RULE,
    add_to_dnc,
)
from apps.api.core import loadshed
from apps.api.db.session import tenant_session
from apps.api.ingest import service as ingest_service
from apps.api.ingest.routes import SECRET_HEADER
from apps.api.ingest.service import INGEST_CALLBACK_PREFIX, next_allowed_dial
from sqlalchemy import text
from tests.lead_ingest_test import SECRET, _client, _tenant_with_ingest

IST = timedelta(hours=5, minutes=30)


def _utc_at_ist(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC) - IST


def _pin_gate_clock(monkeypatch: pytest.MonkeyPatch, utc: datetime) -> None:
    """The gate's clock, which ingest also computes the slot from."""
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: utc + IST)


def _platform(monkeypatch: pytest.MonkeyPatch, status: loadshed.PlatformStatus) -> None:
    async def _status(*_a: object, **_k: object) -> loadshed.PlatformStatus:
        return status

    # The gate and the slot both read it; the HTTP middleware keeps the real one, so the
    # request itself is not shed.
    monkeypatch.setattr("apps.api.compliance.service.get_platform_status", _status)
    monkeypatch.setattr(ingest_service, "get_platform_status", _status)


async def _post(webhook_id: Any, phone: str) -> dict[str, Any]:
    async with _client() as http:
        response = await http.post(
            f"/hooks/v1/ingest/{webhook_id}",
            json={"phone_number": phone, "full_name": "Night Lead"},
            headers={SECRET_HEADER: SECRET},
        )
    assert response.status_code == 202, response.text
    body: dict[str, Any] = response.json()
    return body


async def _callbacks(tenant_id: Any, e164: str) -> list[Any]:
    async with tenant_session(tenant_id) as session:
        return list(
            (
                await session.execute(
                    text(
                        "SELECT requested_at, status, source_execution_id, lead_id "
                        "FROM scheduled_callbacks WHERE phone_e164 = :p ORDER BY created_at"
                    ),
                    {"p": e164},
                )
            ).all()
        )


def _no_dial(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    dialled: list[object] = []

    async def _dial(*args: object, **kwargs: object) -> str:
        dialled.append(kwargs)
        return "should-not-dial"

    monkeypatch.setattr(ingest_service, "dispatch_call", _dial)
    return dialled


# ------------------------------------------------------------------ the slot, on its own


async def test_outside_calling_hours_the_slot_is_the_next_nine_am_ist() -> None:
    late = _utc_at_ist(2026, 10, 3, 22, 15)
    early = _utc_at_ist(2026, 10, 4, 6, 40)
    assert await next_allowed_dial(CALLING_HOURS_RULE, now=late) == _utc_at_ist(2026, 10, 4, 9)
    assert await next_allowed_dial(CALLING_HOURS_RULE, now=early) == _utc_at_ist(2026, 10, 4, 9)


async def test_a_drain_waits_for_the_windows_end_inside_calling_hours(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = _utc_at_ist(2026, 10, 3, 14)
    ends = _utc_at_ist(2026, 10, 3, 15, 30)
    _platform(
        monkeypatch,
        loadshed.PlatformStatus(
            mode="normal", outbound_halted=False, maintenance="draining", maintenance_ends_at=ends
        ),
    )
    assert await next_allowed_dial(MAINTENANCE_DRAIN_RULE, now=now) == ends

    # A window that ends at night does not make the night a lawful time to ring anybody.
    late_end = _utc_at_ist(2026, 10, 3, 23, 30)
    _platform(
        monkeypatch,
        loadshed.PlatformStatus(
            mode="normal",
            outbound_halted=False,
            maintenance="draining",
            maintenance_ends_at=late_end,
        ),
    )
    assert await next_allowed_dial(MAINTENANCE_DRAIN_RULE, now=now) == _utc_at_ist(2026, 10, 4, 9)


async def test_a_drain_with_no_future_end_is_rechecked_shortly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = _utc_at_ist(2026, 10, 3, 14)
    _platform(
        monkeypatch,
        loadshed.PlatformStatus(
            mode="normal",
            outbound_halted=False,
            maintenance="draining",
            maintenance_ends_at=now - timedelta(minutes=1),
        ),
    )
    assert await next_allowed_dial(MAINTENANCE_DRAIN_RULE, now=now) == now + RETRY_AFTER


async def test_a_halt_is_rechecked_after_the_retry_interval_inside_calling_hours() -> None:
    now = _utc_at_ist(2026, 10, 3, 14)
    assert await next_allowed_dial(BIG_RED_SWITCH_RULE, now=now) == now + RETRY_AFTER
    near_close = _utc_at_ist(2026, 10, 3, 20, 58)
    assert await next_allowed_dial(BIG_RED_SWITCH_RULE, now=near_close) == _utc_at_ist(
        2026, 10, 4, 9
    )


# ----------------------------------------------------------------- through the route


async def test_a_night_lead_is_kept_and_booked_for_nine_am(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_gate_clock(monkeypatch, _utc_at_ist(2026, 10, 3, 23, 10))
    dialled = _no_dial(monkeypatch)
    tenant_id, _agent_id, webhook_id = await _tenant_with_ingest()

    body = await _post(webhook_id, "9876507711")

    assert body["dispatched"] is False
    assert body["blocked"] == CALLING_HOURS_RULE
    assert body["callback_at"] is not None
    assert dialled == [], "nothing may ring at night"
    rows = await _callbacks(tenant_id, "+919876507711")
    assert len(rows) == 1
    requested_at, status, execution_id, lead_id = rows[0]
    assert requested_at == _utc_at_ist(2026, 10, 4, 9)
    assert status == "scheduled"
    assert str(execution_id).startswith(INGEST_CALLBACK_PREFIX)
    assert lead_id is not None


async def test_the_same_person_twice_overnight_is_one_call_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_gate_clock(monkeypatch, _utc_at_ist(2026, 10, 3, 23, 10))
    _no_dial(monkeypatch)
    tenant_id, _agent_id, webhook_id = await _tenant_with_ingest()

    await _post(webhook_id, "9876507712")
    _pin_gate_clock(monkeypatch, _utc_at_ist(2026, 10, 4, 1, 45))
    await _post(webhook_id, "9876507712")

    assert len(await _callbacks(tenant_id, "+919876507712")) == 1


async def test_a_lead_during_a_drain_is_booked_for_the_windows_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = _utc_at_ist(2026, 10, 3, 14)
    ends = _utc_at_ist(2026, 10, 3, 15, 30)
    _pin_gate_clock(monkeypatch, now)
    _platform(
        monkeypatch,
        loadshed.PlatformStatus(
            mode="normal", outbound_halted=False, maintenance="draining", maintenance_ends_at=ends
        ),
    )
    dialled = _no_dial(monkeypatch)
    tenant_id, _agent_id, webhook_id = await _tenant_with_ingest()

    body = await _post(webhook_id, "9876507713")

    assert body["blocked"] == MAINTENANCE_DRAIN_RULE
    assert dialled == []
    rows = await _callbacks(tenant_id, "+919876507713")
    assert [row[0] for row in rows] == [ends]


async def test_a_lead_under_the_halt_is_booked_for_a_recheck(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = _utc_at_ist(2026, 10, 3, 14)
    _pin_gate_clock(monkeypatch, now)
    _platform(monkeypatch, loadshed.PlatformStatus(mode="normal", outbound_halted=True))
    dialled = _no_dial(monkeypatch)
    tenant_id, _agent_id, webhook_id = await _tenant_with_ingest()

    body = await _post(webhook_id, "9876507714")

    assert body["blocked"] == BIG_RED_SWITCH_RULE
    assert dialled == []
    rows = await _callbacks(tenant_id, "+919876507714")
    assert [row[0] for row in rows] == [now + RETRY_AFTER]


async def test_a_refusal_about_the_person_books_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DNC is a fact about the person, not the clock: no call-back, ever."""
    _pin_gate_clock(monkeypatch, _utc_at_ist(2026, 10, 3, 11))
    _no_dial(monkeypatch)
    tenant_id, _agent_id, webhook_id = await _tenant_with_ingest()
    async with tenant_session(tenant_id) as session:
        await add_to_dnc(session, tenant_id=tenant_id, phone_e164="+919876507715", source="request")

    body = await _post(webhook_id, "9876507715")

    assert body["blocked"] == "dnc"
    assert body["callback_at"] is None
    assert await _callbacks(tenant_id, "+919876507715") == []
