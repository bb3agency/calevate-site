"""D-890: only a super admin gives value with no payment behind it.

Founder, 26 Oct 2026: a super admin may make any client account paid without a payment, from
any trial state, and grant any amount of credit; the client is told (email and a dashboard
notice) and every super admin is emailed. These pin: an operator is refused both acts; the
conversion from a running trial, an ended one and none, each unlocking what a payment does
and recorded as complimentary; an already-paid account refused; a grant in the same step
told once; the confirmation bound to the client and the amount; and the notices job, which
emails the super admins before the client and puts the dashboard notice up once.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from apps.api.billing.comp_notices import COMP_NOTICE_JOB
from apps.api.billing.comp_routes import make_paid_confirmation
from apps.api.billing.trials import end_trial, start_trial
from apps.api.compliance.trial_access import restricting_trial
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from apps.workers import comp_notices
from apps.workers.settings import WorkerSettings
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.credit_grant_test import _tenant

pytestmark = pytest.mark.asyncio


async def _admin(role: str, email: str | None = None) -> str:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, email, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', :email, :role, now(), now())"
            ),
            {"id": admin_id, "role": role, "email": email},
        )
    return f"dev:admin:{admin_id}"


async def _post(path: str, token: str, body: dict[str, Any], confirm: str | None) -> Any:
    headers = {"Authorization": f"Bearer {token}"}
    if confirm is not None:
        headers["X-Confirm-Action"] = confirm
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        return await http.post(path, headers=headers, json=body)


async def _get(path: str, token: str) -> Any:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        return await http.get(path, headers={"Authorization": f"Bearer {token}"})


async def _scalar(tenant_id: uuid.UUID, sql: str, **params: Any) -> Any:
    async with tenant_session(tenant_id) as session:
        return (await session.execute(text(sql), {"t": tenant_id, **params})).scalar()


async def _notices(tenant_id: uuid.UUID) -> list[dict[str, Any]]:
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT payload FROM outbox_messages WHERE job = :job "
                    "AND payload->>'tenant_id' = :t ORDER BY created_at"
                ),
                {"job": COMP_NOTICE_JOB, "t": str(tenant_id)},
            )
        ).scalars()
        return [dict(r) for r in rows]


async def _trial(tenant_id: uuid.UUID, *, then: str | None = None) -> None:
    async with tenant_session(tenant_id) as session:
        await start_trial(session, tenant_id=tenant_id, days=14, actor_user_id=None)
        if then is not None:
            await end_trial(session, tenant_id=tenant_id, outcome=then, reason="test")


def _paid_path(tenant_id: uuid.UUID) -> str:
    return f"/v1/admin/tenants/{tenant_id}/paid"


# --- who -----------------------------------------------------------------------------------


async def test_an_operator_may_read_but_never_make_an_account_paid() -> None:
    operator = await _admin("operator")
    tenant_id = await _tenant()
    await _trial(tenant_id)

    read = await _get(_paid_path(tenant_id), operator)
    assert read.status_code == 200, read.text
    assert read.json()["paid"] is False and read.json()["trial"] == "running"

    refused = await _post(
        _paid_path(tenant_id),
        operator,
        {"reason": "signed offline"},
        make_paid_confirmation(tenant_id, None),
    )
    assert refused.status_code == 403, refused.text
    converted = await _post(
        f"/v1/admin/tenants/{tenant_id}/trial/end",
        operator,
        {"outcome": "converted", "reason": "signed offline"},
        f"end_trial:{tenant_id}:converted",
    )
    assert converted.status_code == 403, converted.text
    assert "super admin" in converted.json()["detail"]
    stopped = await _post(
        f"/v1/admin/tenants/{tenant_id}/trial/end",
        operator,
        {"outcome": "stopped", "reason": "no longer interested"},
        f"end_trial:{tenant_id}:stopped",
    )
    assert stopped.status_code == 200, "stopping a trial stays any operator's"
    assert await _scalar(tenant_id, "SELECT first_paid_at FROM organizations WHERE id = :t") is None


# --- from every state -------------------------------------------------------------------------


@pytest.mark.parametrize("state", ["running", "ended", "none"])
async def test_a_super_admin_makes_an_account_paid_from_any_state(state: str) -> None:
    superadmin = await _admin("superadmin")
    tenant_id = await _tenant()
    if state == "running":
        await _trial(tenant_id)
    elif state == "ended":
        await _trial(tenant_id, then="stopped")

    made = await _post(
        _paid_path(tenant_id),
        superadmin,
        {"reason": "signed the annual plan offline"},
        make_paid_confirmation(tenant_id, None),
    )
    assert made.status_code == 200, made.text
    body = made.json()
    assert body["status"]["paid"] is True and body["status"]["via"] == "complimentary"
    assert body["trial_converted"] is (state == "running")
    assert body["grant"] is None

    async with tenant_session(tenant_id) as session:
        assert await restricting_trial(session, tenant_id=tenant_id) is None
    assert await _scalar(tenant_id, "SELECT count(*) FROM go_live_guides") == 1
    if state == "ended":
        assert await _scalar(tenant_id, "SELECT erase_after FROM tenant_trials LIMIT 1") is None, (
            "an ended trial's data is kept once the account is paid"
        )
    assert (
        await _scalar(
            tenant_id,
            "SELECT actor_type FROM audit_log WHERE tenant_id = :t "
            "AND action = 'account.made_paid'",
        )
        == "admin"
    ), "the act is on the tamper-evident trail, with the super admin as its actor"
    assert (
        await _scalar(tenant_id, "SELECT first_paid_reason FROM organizations WHERE id = :t")
        == "signed the annual plan offline"
    ), "the words are kept on the account"
    assert body["status"]["reason"] == "signed the annual plan offline"
    notices = await _notices(tenant_id)
    assert [n["kind"] for n in notices] == ["paid"] and notices[0]["amount_inr"] is None


async def test_an_account_already_paid_is_refused_and_unchanged() -> None:
    superadmin = await _admin("superadmin")
    tenant_id = await _tenant()
    confirm = make_paid_confirmation(tenant_id, None)
    first = await _post(_paid_path(tenant_id), superadmin, {"reason": "deal"}, confirm)
    assert first.status_code == 200
    again = await _post(_paid_path(tenant_id), superadmin, {"reason": "deal"}, confirm)
    assert again.status_code == 409 and again.json()["type"].endswith("/account_already_paid")
    assert len(await _notices(tenant_id)) == 1


async def test_credit_in_the_same_step_is_granted_and_told_once() -> None:
    superadmin = await _admin("superadmin")
    tenant_id = await _tenant()
    await _trial(tenant_id)
    body = {
        "reason": "pilot customer",
        "grant": {"amount_inr": "2500.00", "grant_ref": "PAID-GRANT-1", "reason": "pilot credit"},
    }
    wrong = await _post(
        _paid_path(tenant_id), superadmin, body, make_paid_confirmation(tenant_id, None)
    )
    assert wrong.status_code == 403, "the confirmation is bound to the credit added with it"
    made = await _post(
        _paid_path(tenant_id),
        superadmin,
        body,
        make_paid_confirmation(tenant_id, Decimal("2500")),
    )
    assert made.status_code == 200, made.text
    assert made.json()["grant"]["amount_inr"] == "2500.00"
    assert await _scalar(
        tenant_id, "SELECT sum(delta) FROM credit_ledger WHERE tenant_id = :t AND reason = 'grant'"
    ) == Decimal("2500.0000")
    notices = await _notices(tenant_id)
    assert [(n["kind"], n["amount_inr"]) for n in notices] == [("paid", "2500.00")], (
        "one message about both, not one per act"
    )


async def test_a_large_grant_in_the_same_step_needs_the_amount_typed_again() -> None:
    superadmin = await _admin("superadmin")
    tenant_id = await _tenant()
    body = {
        "reason": "enterprise deal",
        "grant": {"amount_inr": "75000.00", "grant_ref": "PAID-BIG", "reason": "deal credit"},
    }
    refused = await _post(
        _paid_path(tenant_id), superadmin, body, make_paid_confirmation(tenant_id, Decimal("75000"))
    )
    assert refused.status_code == 422 and refused.json()["type"].endswith(
        "/grant_amount_unconfirmed"
    )
    assert await _scalar(tenant_id, "SELECT first_paid_at FROM organizations WHERE id = :t") is None


async def test_a_grant_on_its_own_is_told_once_however_often_it_is_replayed() -> None:
    superadmin = await _admin("superadmin")
    tenant_id = await _tenant()
    path = f"/v1/admin/tenants/{tenant_id}/credits/grants"
    body = {"amount_inr": "400.00", "grant_ref": "GRANT-TOLD", "reason": "outage goodwill"}
    for _ in range(2):
        posted = await _post(path, superadmin, body, "grant_credits:400.00")
        assert posted.status_code == 201, posted.text
    notices = await _notices(tenant_id)
    assert [(n["kind"], n["amount_inr"]) for n in notices] == [("grant", "400.00")]


# --- the notices -------------------------------------------------------------------------------


class _Mailbox:
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    def send(self, *, to: str, subject: str, body: str, html: str | None = None) -> bool:
        self.sent.append({"to": to, "subject": subject, "body": body})
        return True


async def test_the_notices_reach_the_super_admins_first_then_the_client_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mailbox = _Mailbox()
    monkeypatch.setattr(comp_notices, "get_transport", lambda: mailbox)
    boss = f"boss-{uuid.uuid4().hex[:6]}@example.com"
    await _admin("superadmin", email=boss)
    operator_email = f"ops-{uuid.uuid4().hex[:6]}@example.com"
    await _admin("operator", email=operator_email)
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET billing_email = 'owner@example.com' WHERE id = :t"),
            {"t": tenant_id},
        )
    payload = {
        "tenant_id": str(tenant_id),
        "kind": "grant",
        "amount_inr": "1500.00",
        "actor_id": None,
        "reason": "outage goodwill",
    }
    assert await comp_notices.notify_comp({}, payload) == "sent"
    # ARQ re-running the same job counts its tries.
    assert await comp_notices.notify_comp({"job_try": 2}, payload) == "sent"

    recipients = [m["to"] for m in mailbox.sent]
    assert boss in recipients, "every live super admin is emailed"
    assert operator_email not in recipients, "an operator is not"
    first_run = recipients[: len(recipients) // 2]
    assert first_run[-1] == "owner@example.com", "the client's email goes last"
    client_mail = next(m for m in mailbox.sent if m["to"] == "owner@example.com")
    assert "₹1500.00" in client_mail["body"] and "no payment was taken" in client_mail["body"]
    for vendor in ("ThinnestAI", "Gemini", "Sarvam", "Azure", "Cartesia"):
        assert vendor not in client_mail["body"]
    async with untenanted_session() as session:
        posted = (
            await session.execute(
                text("SELECT count(*) FROM platform_announcements WHERE target_tenant_id = :t"),
                {"t": tenant_id},
            )
        ).scalar()
    assert posted == 1, "the dashboard notice goes up once, however often the job runs"

    # A second grant of the same amount the same day is a new job, and its own notice.
    assert await comp_notices.notify_comp({}, payload) == "sent"
    async with untenanted_session() as session:
        posted = (
            await session.execute(
                text("SELECT count(*) FROM platform_announcements WHERE target_tenant_id = :t"),
                {"t": tenant_id},
            )
        ).scalar()
    assert posted == 2


async def test_a_refused_send_is_retried_rather_than_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """arq re-runs a job only for `Retry` (and `RetryJob`/`CancelledError`); any other
    exception is terminal on the first try. The outbox has already marked the promise
    published, so a refused send that did not raise `Retry` lost the client's email."""
    from arq import Retry

    class _Refusing:
        def send(self, *, to: str, subject: str, body: str, html: str | None = None) -> bool:
            return False

    monkeypatch.setattr(comp_notices, "get_transport", lambda: _Refusing())
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET billing_email = 'owner@example.com' WHERE id = :t"),
            {"t": tenant_id},
        )
    payload = {
        "tenant_id": str(tenant_id),
        "kind": "grant",
        "amount_inr": "100.00",
        "actor_id": None,
        "reason": "retry check",
    }
    with pytest.raises(Retry):
        await comp_notices.notify_comp({"job_try": 1}, payload)


def test_the_notice_job_is_registered() -> None:
    names = {getattr(f, "name", getattr(f, "__name__", "")) for f in WorkerSettings.functions}
    assert COMP_NOTICE_JOB in names and comp_notices.JOB_NAME == COMP_NOTICE_JOB


def test_the_dashboard_lines_name_the_gift() -> None:
    assert comp_notices.notice_text(kind="grant", amount=Decimal("500")) == (
        "We added ₹500.00 of calling credit to your account. It's on us."
    )
    assert "paid account" in comp_notices.notice_text(kind="paid", amount=None)
