"""A campaign's call-backs follow the campaign (D-914, founder 28 Oct 2026).

Paused: held, not dialled and not run out of time. Resumed: dialled at the next moment the
calling hours allow, its two hours counted from there. Stopped: called off with a reason
the owner reads and an audit row. A call-back outside any campaign is untouched.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from apps.api.callbacks import service as callbacks
from apps.api.callbacks.routes import _view
from apps.api.campaigns import controls
from apps.api.campaigns import service as campaigns
from apps.api.copilot import console_reads
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import reset_engine_cache
from apps.workers.callbacks import dispatch_due_callbacks
from calevate_shared.calling_window import IST
from sqlalchemy import text
from tests.callback_dispatch_test import _dialable_tenant

pytestmark = pytest.mark.anyio

CALLER = "+919812345690"
OTHER = "+919812345691"


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    """11:00 IST for the dial gate, as `callback_dispatch_test` pins it."""
    fixed = datetime(2026, 8, 11, 5, 30, tzinfo=UTC) + IST
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: fixed)
    reset_engine_cache()


async def _campaign(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, *, status: str, hours: Any = None
) -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        campaign_id = await campaigns.create_campaign(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name=f"Hold {uuid.uuid4().hex[:4]}",
            classification="service",
            number_id=None,
            dlt_template_id=None,
            concurrency=3,
            consent_source="existing_customer",
            consent_collected_at=datetime.now(UTC) - timedelta(days=7),
        )
        await session.execute(
            text(
                "UPDATE campaigns SET status = :s, launched_at = now(), "
                "calling_hours = CAST(:h AS jsonb) WHERE id = :c"
            ),
            {"s": status, "c": campaign_id, "h": None if hours is None else json.dumps(hours)},
        )
    return campaign_id


async def _book(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    campaign_id: uuid.UUID | None,
    phone: str = CALLER,
    requested_at: datetime,
) -> uuid.UUID:
    """A call-back promised on a call of `campaign_id` (or on no campaign's call)."""
    async with tenant_session(tenant_id) as session:
        source_call_id = None
        if campaign_id is not None:
            source_call_id = uuid7()
            await session.execute(
                text(
                    "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                    "status, campaign_id, to_e164, created_at, updated_at) VALUES (:id, :t, "
                    ":a, :ref, 'outbound', 'completed', :c, :to, now(), now())"
                ),
                {
                    "id": source_call_id,
                    "t": tenant_id,
                    "a": agent_id,
                    "ref": f"exec_{uuid.uuid4().hex}",
                    "c": campaign_id,
                    "to": phone,
                },
            )
        booked = await callbacks.book(
            session,
            callback_id=uuid7(),
            tenant_id=tenant_id,
            agent_id=agent_id,
            source_call_id=source_call_id,
            source_execution_id=f"exec_{uuid.uuid4().hex[:10]}",
            lead_id=None,
            phone_e164=phone,
            requested_at=requested_at,
            booked_at=datetime.now(UTC),
            note=None,
            language=None,
        )
    assert booked is not None
    return booked[0]


async def _row(tenant_id: uuid.UUID, callback_id: uuid.UUID) -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        found = await callbacks.get_callback(session, callback_id)
    assert found is not None
    return found


async def _set_status(tenant_id: uuid.UUID, campaign_id: uuid.UUID, status: str) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaigns SET status = :s WHERE id = :c"), {"s": status, "c": campaign_id}
        )


async def test_a_paused_campaigns_call_back_is_held_and_rung_once_it_resumes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Promised three hours ago, past the two-hour grace: while the campaign is paused it is
    neither dialled nor missed; once it runs again the next tick dials it."""
    # The release waits for the calling hours on the real clock; this test is about the
    # hold, so the hours are open (`test_a_release_waits_for_the_campaigns_hours` pins them).
    monkeypatch.setattr(
        "apps.api.campaigns.scheduling.first_dial_not_before", lambda start, hours=None: start
    )
    tenant_id, agent_id = await _dialable_tenant()
    campaign_id = await _campaign(tenant_id, agent_id, status="paused")
    callback_id = await _book(
        tenant_id,
        agent_id,
        campaign_id=campaign_id,
        requested_at=datetime.now(UTC) - timedelta(hours=3),
    )

    outcome = await dispatch_due_callbacks(tenant_id, slots=5)
    assert outcome["dialled"] == 0, outcome
    row = await _row(tenant_id, callback_id)
    assert row["status"] == "scheduled"
    assert row["last_refusal_rule"] == callbacks.CAMPAIGN_PAUSED_RULE
    view = _view(row)
    assert view.held is True
    assert view.explanation == callbacks.CAMPAIGN_PAUSED_REASON

    # Pip reads the same hold.
    async with tenant_session(tenant_id) as session:
        listing = await console_reads._callbacks_list(session, None, {"open_only": True})  # type: ignore[arg-type]
    assert callbacks.CAMPAIGN_PAUSED_REASON in listing

    await _set_status(tenant_id, campaign_id, "running")
    outcome = await dispatch_due_callbacks(tenant_id, slots=5)
    assert outcome["dialled"] == 1, outcome
    row = await _row(tenant_id, callback_id)
    assert row["status"] == "dialing"
    assert _view(row).held is False


async def test_a_release_waits_for_the_campaigns_hours_and_its_grace_starts_there() -> None:
    """Resumed at 13:00 IST on a campaign that calls 10:00-12:00: due at 10:00 IST the next
    day, not claimed before, and not missed at 15:00 though promised before the pause."""
    tenant_id, agent_id = await _dialable_tenant()
    campaign_id = await _campaign(
        tenant_id, agent_id, status="paused", hours={"start": "10:00", "end": "12:00"}
    )
    resumed = datetime(2026, 8, 11, 13, 0, tzinfo=UTC) - IST  # 13:00 IST
    callback_id = await _book(
        tenant_id, agent_id, campaign_id=campaign_id, requested_at=resumed - timedelta(hours=4)
    )
    async with tenant_session(tenant_id) as session:
        assert await callbacks.hold_for_paused_campaigns(session) == 1
        assert await callbacks.hold_for_paused_campaigns(session) == 0
        assert await callbacks.expire_stale(session, now=resumed) == 0
        assert await callbacks.claim_due(session, now=resumed, limit=5) == []
    await _set_status(tenant_id, campaign_id, "running")
    async with tenant_session(tenant_id) as session:
        assert await callbacks.release_resumed(session, now=resumed) == 1
        assert await callbacks.claim_due(session, now=resumed + timedelta(hours=2), limit=5) == []
        assert await callbacks.expire_stale(session, now=resumed + timedelta(hours=3)) == 0
    row = await _row(tenant_id, callback_id)
    opens = datetime(2026, 8, 12, 10, 0, tzinfo=UTC) - IST
    async with tenant_session(tenant_id) as session:
        grace_from = (
            await session.execute(
                text("SELECT grace_from, next_attempt_at FROM scheduled_callbacks WHERE id = :i"),
                {"i": callback_id},
            )
        ).one()
        assert grace_from[0] == opens and grace_from[1] == opens
        claimed = await callbacks.claim_due(session, now=opens, limit=5)
        await session.rollback()
    assert [c.id for c in claimed] == [callback_id]
    assert claimed[0].campaign_calling_hours == {"start": "10:00", "end": "12:00"}
    assert row["status"] == "scheduled" and row["last_refusal_rule"] is None


async def test_stopping_a_campaign_calls_off_its_call_backs_and_says_why() -> None:
    """The stop calls off the campaign's waiting call-backs in its own transaction, with an
    audit row; a call-back promised outside any campaign is left as it was."""
    tenant_id, agent_id = await _dialable_tenant()
    campaign_id = await _campaign(tenant_id, agent_id, status="running")
    later = datetime.now(UTC) + timedelta(days=1)
    tied = await _book(tenant_id, agent_id, campaign_id=campaign_id, requested_at=later)
    free = await _book(tenant_id, agent_id, campaign_id=None, phone=OTHER, requested_at=later)

    async with tenant_session(tenant_id) as session:
        assert await controls.stop_campaign(session, campaign_id=campaign_id) is True

    row = await _row(tenant_id, tied)
    assert row["status"] == "cancelled"
    assert _view(row).explanation == callbacks.CAMPAIGN_STOPPED_REASON
    assert (await _row(tenant_id, free))["status"] == "scheduled"
    async with untenanted_session() as session:
        audits = (
            await session.execute(
                text(
                    "SELECT action FROM audit_log WHERE tenant_id = :t AND object_id = :o "
                    "AND action = 'callbacks.called_off'"
                ),
                {"t": tenant_id, "o": str(campaign_id)},
            )
        ).all()
    assert len(audits) == 1
    async with tenant_session(tenant_id) as session:
        listing = await console_reads._callbacks_list(session, None, {})  # type: ignore[arg-type]
    assert callbacks.CAMPAIGN_STOPPED_REASON in listing


async def test_the_tick_calls_off_a_campaign_cancelled_by_any_path() -> None:
    tenant_id, agent_id = await _dialable_tenant()
    campaign_id = await _campaign(tenant_id, agent_id, status="running")
    callback_id = await _book(
        tenant_id,
        agent_id,
        campaign_id=campaign_id,
        requested_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    await _set_status(tenant_id, campaign_id, "cancelled")
    outcome = await dispatch_due_callbacks(tenant_id, slots=5)
    assert outcome["dialled"] == 0 and outcome["settled"] >= 1, outcome
    assert (await _row(tenant_id, callback_id))[
        "last_refusal_rule"
    ] == callbacks.CAMPAIGN_STOPPED_RULE
