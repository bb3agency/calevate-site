"""The two trial emails (D-685): "your trial has started" and "it ends in about a day".

Pinned: each is sent once and only once (a claim on the trial row, not a memory of having
sent it); the ending notice goes out only inside its 24-hour window; nothing is sent for a
trial that has ended or been stopped; one tenant's job cannot see or claim another's
trial; and neither email carries a rupee figure or what the trial costs us.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing import trial_routes
from apps.api.billing.trial_routes import router as trial_router
from apps.api.billing.trial_routes import start_trial_confirmation
from apps.api.billing.trials import end_trial, start_trial
from apps.api.core.errors import install_error_handlers
from apps.api.db.session import tenant_session, untenanted_session
from apps.workers import trial_notices
from apps.workers.trial_notices import (
    TRIAL_STARTED_NOTICE_JOB,
    ist_moment,
    notify_ending_if_due,
    notify_trial_started,
)
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

pytestmark = [pytest.mark.rls]


class Recorder:
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    def send(self, *, to: str, subject: str, body: str, html: str | None = None) -> bool:
        self.sent.append({"to": to, "subject": subject, "body": body, "html": html or ""})
        return True


@pytest.fixture
def mailbox(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    recorder = Recorder()
    monkeypatch.setattr(trial_notices, "get_transport", lambda: recorder)
    return recorder


async def _tenant(plan_tier: str = "self_serve", email: str | None = "owner@example.test") -> UUID:
    created = await admin_service.create_organization(
        name="Raghava Organics",
        slug=f"trialmail-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=email,
        language="te-IN",
        created_by=None,
    )
    tenant_id = UUID(str(created["id"]))
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = :tier WHERE id = :i"),
            {"tier": plan_tier, "i": tenant_id},
        )
    return tenant_id


async def _open(tenant_id: UUID, *, days: int, at: datetime | None = None) -> UUID:
    async with tenant_session(tenant_id) as session:
        state = await start_trial(
            session, tenant_id=tenant_id, days=days, actor_user_id=None, at=at
        )
    return state.id


async def _started_payloads(tenant_id: UUID) -> list[dict[str, Any]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT payload FROM outbox_messages WHERE job = :job "
                    "AND payload->>'tenant_id' = :t"
                ),
                {"job": TRIAL_STARTED_NOTICE_JOB, "t": str(tenant_id)},
            )
        ).all()
    return [dict(row[0]) for row in rows]


async def _admin_token() -> str:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'operator', now(), now())"
            ),
            {"id": admin_id},
        )
    return f"dev:admin:{admin_id}"


async def _open_through_the_route(tenant_id: UUID, days: int = 3) -> str:
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(trial_router)
    token = await _admin_token()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        posted = await http.post(
            f"/v1/admin/tenants/{tenant_id}/trial",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Confirm-Action": start_trial_confirmation(tenant_id, days),
            },
            json={"days": days, "reason": "Founder promised three days.", "free_minutes": 30},
        )
    assert posted.status_code == 201, posted.text
    return str(posted.json()["trial_id"])


def _assert_no_money(body: str) -> None:
    lowered = body.lower()
    assert "₹" not in body and "inr" not in lowered
    assert "cost" not in lowered


# --- the start notice --------------------------------------------------------------


def test_the_api_and_the_worker_name_the_same_job() -> None:
    assert trial_routes.TRIAL_STARTED_NOTICE_JOB == TRIAL_STARTED_NOTICE_JOB


async def test_starting_a_trial_promises_one_email_and_it_is_sent_once(mailbox: Recorder) -> None:
    tenant_id = await _tenant()
    trial_id = await _open_through_the_route(tenant_id, days=3)

    payloads = await _started_payloads(tenant_id)
    assert payloads == [{"tenant_id": str(tenant_id), "trial_id": trial_id}]

    first = await notify_trial_started({"job_try": 1}, payloads[0])
    again = await notify_trial_started({"job_try": 2}, payloads[0])

    assert (first, again) == ("sent", "already_sent")
    assert len(mailbox.sent) == 1
    mail = mailbox.sent[0]
    assert mail["to"] == "owner@example.test"
    assert mail["subject"] == "Your free trial has started"
    assert "It runs for 3 days, until " in mail["body"] and " IST." in mail["body"]
    assert "calls are on us" in mail["body"]
    assert "/billing?tab=credits" in mail["body"], "a prepaid client gets a top-up link"
    _assert_no_money(mail["body"])


async def test_an_invoiced_client_is_told_their_invoice_carries_on(mailbox: Recorder) -> None:
    tenant_id = await _tenant(plan_tier="managed")
    trial_id = await _open(tenant_id, days=5)

    await notify_trial_started({}, {"tenant_id": str(tenant_id), "trial_id": str(trial_id)})

    body = mailbox.sent[0]["body"]
    assert "billed on your monthly invoice as usual" in body
    assert "calls are paid from your calling credit" not in body
    assert "/billing?tab=credits" not in body
    _assert_no_money(body)


async def test_no_start_email_for_a_trial_that_already_ended(mailbox: Recorder) -> None:
    tenant_id = await _tenant()
    trial_id = await _open(tenant_id, days=5)
    async with tenant_session(tenant_id) as session:
        await end_trial(session, tenant_id=tenant_id, outcome="stopped", reason="Opened in error.")

    outcome = await notify_trial_started(
        {}, {"tenant_id": str(tenant_id), "trial_id": str(trial_id)}
    )

    assert outcome == "trial_not_active"
    assert mailbox.sent == []


async def test_no_start_email_without_an_address_and_nothing_is_claimed(
    mailbox: Recorder,
) -> None:
    tenant_id = await _tenant(email=None)
    trial_id = await _open(tenant_id, days=5)

    outcome = await notify_trial_started(
        {}, {"tenant_id": str(tenant_id), "trial_id": str(trial_id)}
    )

    assert outcome == "no_billing_email"
    assert mailbox.sent == []


# --- the ending notice -------------------------------------------------------------


async def test_the_ending_email_goes_once_inside_the_window(mailbox: Recorder) -> None:
    tenant_id = await _tenant()
    now = datetime.now(UTC)
    # Opened two days ago for three: it ends 24 hours from now.
    await _open(tenant_id, days=3, at=now - timedelta(days=2))

    first = await notify_ending_if_due(tenant_id, now=now)
    later = await notify_ending_if_due(tenant_id, now=now + timedelta(hours=1))

    assert (first, later) == ("sent", "already_sent")
    assert len(mailbox.sent) == 1
    mail = mailbox.sent[0]
    assert mail["subject"] == "Your free trial ends in about a day"
    assert "Your free trial ends at " in mail["body"] and " IST." in mail["body"]
    assert "Add credit now so calls carry on" in mail["body"]
    assert "/billing?tab=credits" in mail["body"]
    _assert_no_money(mail["body"])


async def test_no_ending_email_before_the_window(mailbox: Recorder) -> None:
    tenant_id = await _tenant()
    now = datetime.now(UTC)
    await _open(tenant_id, days=3, at=now)

    assert await notify_ending_if_due(tenant_id, now=now) == "not_yet"
    assert await notify_ending_if_due(tenant_id, now=now + timedelta(hours=47)) == "not_yet"
    assert mailbox.sent == []


async def test_a_one_day_trial_gets_no_ending_email(mailbox: Recorder) -> None:
    """Its whole length is inside the window, and its start email already names the end."""
    tenant_id = await _tenant()
    now = datetime.now(UTC)
    await _open(tenant_id, days=1, at=now)

    assert await notify_ending_if_due(tenant_id, now=now + timedelta(hours=1)) == "too_short"
    assert mailbox.sent == []


async def test_no_ending_email_for_a_stopped_or_lapsed_trial(mailbox: Recorder) -> None:
    stopped = await _tenant()
    now = datetime.now(UTC)
    await _open(stopped, days=3, at=now - timedelta(days=2))
    async with tenant_session(stopped) as session:
        await end_trial(session, tenant_id=stopped, outcome="converted", reason="They bought.")
    assert await notify_ending_if_due(stopped, now=now) == "none"

    lapsed = await _tenant()
    await _open(lapsed, days=3, at=now - timedelta(days=4))
    # Past its end, not yet swept: still `active` in the row, over by the clock.
    assert await notify_ending_if_due(lapsed, now=now) == "none"

    assert mailbox.sent == []


async def test_the_invoiced_ending_email_asks_for_nothing(mailbox: Recorder) -> None:
    tenant_id = await _tenant(plan_tier="managed")
    now = datetime.now(UTC)
    await _open(tenant_id, days=4, at=now - timedelta(days=3, hours=1))

    assert await notify_ending_if_due(tenant_id, now=now) == "sent"
    body = mailbox.sent[0]["body"]
    assert "billed on your monthly invoice as usual" in body
    assert "Add credit" not in body
    _assert_no_money(body)


# --- tenancy -----------------------------------------------------------------------


async def test_one_tenant_cannot_see_or_claim_another_tenants_trial(mailbox: Recorder) -> None:
    owner = await _tenant()
    neighbour = await _tenant()
    now = datetime.now(UTC)
    trial_id = await _open(owner, days=3, at=now - timedelta(days=2))

    # The neighbour's sweep step finds no trial at all.
    assert await notify_ending_if_due(neighbour, now=now) == "none"
    # A start payload naming the owner's trial under the neighbour's tenant sends nothing.
    assert (
        await notify_trial_started({}, {"tenant_id": str(neighbour), "trial_id": str(trial_id)})
        == "trial_not_active"
    )
    # And RLS refuses the claim itself from the neighbour's session.
    async with tenant_session(neighbour) as session:
        claimed = (
            await session.execute(
                text(
                    "UPDATE tenant_trials SET ending_notice_sent_at = now() "
                    "WHERE id = :id RETURNING id"
                ),
                {"id": trial_id},
            )
        ).first()
    assert claimed is None
    assert mailbox.sent == []

    # The owner's own notice is untouched by any of that.
    assert await notify_ending_if_due(owner, now=now) == "sent"


def test_the_end_time_is_written_in_ist() -> None:
    assert ist_moment(datetime(2026, 10, 10, 17, 28, tzinfo=UTC)) == "10 Oct 2026, 10:58 pm IST"
    assert ist_moment(datetime(2026, 10, 10, 3, 5, tzinfo=UTC)) == "10 Oct 2026, 08:35 am IST"
