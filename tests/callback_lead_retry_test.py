"""A new lead's retry on the call-back tick (D-716).

A retry is booked as soon as the try before it is placed, before anyone knows whether it
was answered, so the tick asks again when it falls due: it stands down once the person
answered, waits while a call with them is still on the line, and otherwise dials through
the gate and books the next try the plan allows.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.callbacks import service as callbacks
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine import reset_engine_cache
from apps.api.ingest import lead_policy
from apps.workers.callbacks import (
    ON_A_CALL_REASON,
    RETRY_NOT_NEEDED_REASON,
    dispatch_due_callbacks,
)
from sqlalchemy import text
from tests.callback_dispatch_test import _dialable_tenant
from tests.follow_ups_support import set_new_lead_call

pytestmark = pytest.mark.anyio

ROOT = "lead-ingest-root"


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    """11:00 IST, so the gate's calling-hours rule never stands in for the retry's own."""
    fixed = datetime(2026, 8, 11, 5, 30, tzinfo=UTC) + timedelta(hours=5, minutes=30)
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: fixed)


@pytest.fixture(autouse=True)
def _fake_engine() -> None:
    reset_engine_cache()


def _phone() -> str:
    """Unique per test: the retry check matches calls by number as well as by lead."""
    return f"+9198{uuid.uuid4().int % 100000000:08d}"


async def _lead(tenant_id: uuid.UUID, agent_id: uuid.UUID, phone: str) -> uuid.UUID:
    lead_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status, "
                "created_at, updated_at) VALUES (:i, :t, :a, :p, 'Asha', 'webhook', 'new', "
                "now(), now())"
            ),
            {"i": lead_id, "t": tenant_id, "a": agent_id, "p": phone},
        )
    return lead_id


async def _first_retry(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, lead_id: uuid.UUID, phone: str
) -> uuid.UUID:
    """Retry 1, booked ten minutes ago and due now."""
    async with tenant_session(tenant_id) as session:
        booked = await callbacks.book(
            session,
            callback_id=uuid7(),
            tenant_id=tenant_id,
            agent_id=agent_id,
            source_call_id=None,
            source_execution_id=lead_policy.retry_key(1, ROOT),
            lead_id=lead_id,
            phone_e164=phone,
            requested_at=datetime.now(UTC) - timedelta(minutes=1),
            booked_at=datetime.now(UTC) - timedelta(minutes=10),
            note="A new enquiry who did not answer the last try",
            language=None,
        )
    assert booked is not None
    return booked[0]


async def _call(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, lead_id: uuid.UUID, phone: str, status: str
) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, lead_id, engine_call_id, direction, "
                "to_e164, status, created_at, updated_at) VALUES (:id, :t, :a, :l, :e, "
                "'outbound', :p, :s, now(), now())"
            ),
            {
                "id": uuid7(),
                "t": tenant_id,
                "a": agent_id,
                "l": lead_id,
                "e": f"out_{uuid.uuid4().hex}",
                "p": phone,
                "s": status,
            },
        )


async def _row(tenant_id: uuid.UUID, callback_id: uuid.UUID) -> dict[str, object]:
    async with tenant_session(tenant_id) as session:
        found = await callbacks.get_callback(session, callback_id)
    assert found is not None
    return found


async def test_a_retry_stands_down_once_the_lead_answered() -> None:
    tenant_id, agent_id = await _dialable_tenant()
    phone = _phone()
    lead_id = await _lead(tenant_id, agent_id, phone)
    callback_id = await _first_retry(tenant_id, agent_id, lead_id, phone)
    await _call(tenant_id, agent_id, lead_id, phone, "completed")

    outcome = await dispatch_due_callbacks(tenant_id, slots=5)

    assert outcome["dialled"] == 0
    row = await _row(tenant_id, callback_id)
    assert (row["status"], row["last_refusal_reason"]) == ("cancelled", RETRY_NOT_NEEDED_REASON)


async def test_a_retry_waits_while_a_call_with_them_is_still_on_the_line() -> None:
    tenant_id, agent_id = await _dialable_tenant()
    phone = _phone()
    lead_id = await _lead(tenant_id, agent_id, phone)
    callback_id = await _first_retry(tenant_id, agent_id, lead_id, phone)
    await _call(tenant_id, agent_id, lead_id, phone, "in_progress")

    outcome = await dispatch_due_callbacks(tenant_id, slots=5)

    assert outcome["dialled"] == 0
    row = await _row(tenant_id, callback_id)
    assert (row["status"], row["last_refusal_rule"], row["last_refusal_reason"]) == (
        "scheduled",
        "lead_on_a_call",
        ON_A_CALL_REASON,
    )


async def test_a_retry_still_wanted_dials_and_books_the_next_try_the_plan_allows() -> None:
    """A retry booked before D-940 retries under "Call new leads"' call step."""
    tenant_id, agent_id = await _dialable_tenant()
    await set_new_lead_call(tenant_id, retries=2, retry_minutes=30)
    phone = _phone()
    lead_id = await _lead(tenant_id, agent_id, phone)
    callback_id = await _first_retry(tenant_id, agent_id, lead_id, phone)

    outcome = await dispatch_due_callbacks(tenant_id, slots=5)

    assert outcome["dialled"] == 1, outcome
    assert (await _row(tenant_id, callback_id))["status"] == "dialing"
    async with tenant_session(tenant_id) as session:
        keys = (
            (
                await session.execute(
                    text(
                        "SELECT source_execution_id FROM scheduled_callbacks "
                        "WHERE lead_id = :l AND status = 'scheduled'"
                    ),
                    {"l": lead_id},
                )
            )
            .scalars()
            .all()
        )
    assert list(keys) == [lead_policy.retry_key(2, ROOT)]
