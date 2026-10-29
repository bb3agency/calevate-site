"""The emails that close a client's wait (D-932): a payment dispute's outcome and a KYC
review's decision, and the alarm when a KYC review waits too long."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from apps.api.billing import payments
from apps.api.compliance.kyc import save_business_details, submit_for_manual_review
from apps.api.compliance.kyc_review import (
    KYC_DECISION_NOTICE_JOB,
    WaitingReview,
    decide_kyc_review,
    waiting_reviews,
)
from apps.api.db.session import admin_session, tenant_session, untenanted_session
from apps.workers import kyc_notices, razorpay_jobs
from sqlalchemy import text
from tests.conftest import create_org_with_receptionist

pytestmark = [pytest.mark.rls]


@dataclass
class Mailbox:
    sent: list[dict[str, str]] = field(default_factory=list)

    def send(self, *, to: str, subject: str, body: str, html: str | None = None) -> bool:
        self.sent.append({"to": to, "subject": subject, "body": body})
        return True


async def _tenant() -> tuple[UUID, str]:
    slug = f"wait-{uuid.uuid4().hex[:8]}"
    created = await create_org_with_receptionist(
        name="Waiting Traders",
        slug=slug,
        vertical_template="real_estate",
        billing_email="accounts@example.com",
        language="te-IN",
        created_by=None,
    )
    tenant_id = UUID(str(created["id"]))
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:id, :email, now(), now())"
            ),
            {"id": user_id, "email": f"owner-{user_id.hex[:8]}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, 'owner', now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id},
        )
    return tenant_id, slug


# --- a dispute's outcome --------------------------------------------------------------


async def test_a_won_dispute_tells_the_owners_their_credit_is_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, slug = await _tenant()
    async with tenant_session(tenant_id) as session:
        await payments.credit_captured_payment(
            session,
            payment=payments.CapturedPayment(
                payment_id=f"pay_{uuid.uuid4().hex[:12]}",
                tenant_id=tenant_id,
                amount_inr=Decimal("1000.00"),
                currency="INR",
            ),
        )
    mailbox = Mailbox()
    monkeypatch.setattr(razorpay_jobs, "get_transport", lambda _purpose=None: mailbox)
    payload = {"tenant_id": str(tenant_id), "kind": "dispute_won", "amount_inr": "400.00"}
    assert await razorpay_jobs.send_payment_notice({}, payload) == "sent"

    recipients = sorted(m["to"] for m in mailbox.sent)
    assert recipients[0] == "accounts@example.com"
    assert len(recipients) == 2 and recipients[1].startswith("owner-"), "owners are told too"
    body = mailbox.sent[0]["body"]
    assert "₹400 we held is back in your calling credit" in body
    assert "Your balance is now ₹1,000." in body
    assert "Outbound calls are back on." in body
    assert f"/c/{slug}/billing" in body
    assert "razorpay" not in body.lower()


def test_a_lost_dispute_says_the_amount_stays_deducted_and_another_keeps_the_pause() -> None:
    body = razorpay_jobs.compose_dispute(
        "dispute_lost",
        amount_inr="400.00",
        balance_inr="600.00",
        still_paused=True,
        slug="acme",
    )
    assert "₹400 we held stays removed from your calling credit" in body
    assert "Your balance is now ₹600." in body
    assert "outbound calls stay paused" in body
    fee = razorpay_jobs.compose_dispute(
        "dispute_won", amount_inr="0.00", balance_inr="50.00", still_paused=False, slug="acme"
    )
    assert "Your calling credit did not change." in fee


# --- a KYC decision -------------------------------------------------------------------


async def _submitted(tenant_id: UUID, *, at: datetime | None = None) -> None:
    async with tenant_session(tenant_id) as session:
        await save_business_details(
            session,
            tenant_id=tenant_id,
            entity_type="llp",
            legal_business_name="Waiting Traders LLP",
            gst_registered=False,
            gstin=None,
            owner_name="Ravi Kumar",
        )
        await submit_for_manual_review(
            session, tenant_id=tenant_id, owner_id_type="pan", owner_id_masked="XXXXX1234X"
        )
        if at is not None:
            await session.execute(
                text("UPDATE kyc_records SET submitted_at = :at WHERE tenant_id = :t"),
                {"at": at, "t": tenant_id},
            )


async def _admin_id() -> UUID:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    return admin_id


async def _decision_notices(tenant_id: UUID) -> list[str]:
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT payload->>'decision' FROM outbox_messages WHERE job = :j "
                    "AND payload->>'tenant_id' = :t"
                ),
                {"j": KYC_DECISION_NOTICE_JOB, "t": str(tenant_id)},
            )
        ).all()
    return [str(r[0]) for r in rows]


async def test_a_rejection_emails_the_reason_and_the_screen_to_fix_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, slug = await _tenant()
    await _submitted(tenant_id)
    async with tenant_session(tenant_id) as session:
        await decide_kyc_review(
            session,
            tenant_id=tenant_id,
            decision="reject",
            document_ref=None,
            reason="The name on the PAN card does not match the owner name you gave.",
            pan_checked=False,
            admin_id=await _admin_id(),
        )
    assert await _decision_notices(tenant_id) == ["reject"]

    mailbox = Mailbox()
    monkeypatch.setattr(kyc_notices, "get_transport", lambda _purpose=None: mailbox)
    payload = {"tenant_id": str(tenant_id), "decision": "reject"}
    assert await kyc_notices.notify_kyc_decision({}, payload) == "sent"
    assert len(mailbox.sent) == 2
    message = mailbox.sent[0]
    assert message["subject"] == "We could not verify your business"
    assert "does not match the owner name you gave" in message["body"]
    assert f"/c/{slug}/verify-business" in message["body"]

    # A decision the client has already answered with a new submission is not announced.
    await _submitted(tenant_id)
    assert await kyc_notices.notify_kyc_decision({}, payload) == "superseded"
    assert len(mailbox.sent) == 2


def test_an_approval_email_is_short_and_links_the_screen() -> None:
    body = kyc_notices.compose_decision("approve", reason=None, slug="acme")
    assert body.startswith("We checked your documents. Your business is verified.")
    assert body.endswith("/c/acme/verify-business")


# --- a KYC review left waiting ----------------------------------------------------------


async def test_the_review_walk_finds_a_waiting_submission() -> None:
    tenant_id, _slug = await _tenant()
    await _submitted(tenant_id, at=datetime.now(UTC) - timedelta(hours=30))
    async with admin_session() as session:
        found = [w for w in await waiting_reviews(session) if w.tenant_id == tenant_id]
    assert [w.status for w in found] == ["submitted"]


def _waiting(hours: float) -> WaitingReview:
    return WaitingReview(
        tenant_id=uuid.uuid4(),
        name="x",
        slug="x",
        status="submitted",
        kyc_path="manual",
        owner_id_type="pan",
        digilocker_required=False,
        submitted_at=datetime.now(UTC) - timedelta(hours=hours),
    )


@pytest.mark.parametrize(
    ("ages", "alarmed"),
    [([], False), ([2.0, 23.0], False), ([30.0, 2.0], True)],
)
async def test_a_review_waiting_past_a_day_raises_the_alarm(
    monkeypatch: pytest.MonkeyPatch, ages: list[float], alarmed: bool
) -> None:
    raised: list[dict[str, Any]] = []

    async def _reviews(_session: Any) -> list[WaitingReview]:
        return [_waiting(h) for h in ages]

    monkeypatch.setattr(kyc_notices, "waiting_reviews", _reviews)
    monkeypatch.setattr(
        kyc_notices, "alert", lambda stage, code, **kw: raised.append({"code": code, **kw})
    )
    await kyc_notices.alarm_overdue_kyc_reviews({})
    assert [r["code"] for r in raised] == (["kyc_review_overdue"] if alarmed else [])
    if alarmed:
        assert (
            "1 KYC review(s) have waited more than 24 hours; the oldest 30 hours"
            in (raised[0]["detail"])
        )
