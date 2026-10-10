"""Razorpay operations (D-699) past the happy path: the dispute ledger's edges, the
operator's payments page, the event handlers' unroutable deliveries and the
reconciliation's every finding.

The provider is a fake or a monkeypatched seam throughout; no test reaches Razorpay.
"""

from __future__ import annotations

import io
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing import (
    disputes,
    payment_admin_routes,
    payment_events,
    payments,
    reconciliation,
)
from apps.api.billing.disputes import DisputeFacts, apply_dispute_event, extract_dispute
from apps.api.billing.payment_objects import AUTO_RECHARGE, MANDATE, record_route, verify_order
from apps.api.billing.razorpay_api import ProviderPayment, ProviderRefundRow, ProviderSettlement
from apps.api.billing.service import get_balance
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.core.stepup import StepUp
from apps.api.db.session import tenant_session
from fastapi import Request, UploadFile
from sqlalchemy import text
from starlette.datastructures import Headers

pytestmark = [pytest.mark.rls]

KEY_ID = "rzp_test_ops"


@pytest.fixture(autouse=True)
def _configured(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "payment_provider", payments.PROVIDER)
    monkeypatch.setattr(settings, "razorpay_key_id", KEY_ID)
    monkeypatch.setattr(settings, "razorpay_webhook_secret", "whsec_ops")
    monkeypatch.setattr(settings, "razorpay_key_secret", "rzp_secret_ops")
    monkeypatch.setattr(settings, "razorpay_mode", None)


@pytest.fixture
def alerts(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    raised: list[str] = []

    def _record(_kind: str, code: str, **_: Any) -> None:
        raised.append(code)

    for module in (disputes, payment_events, reconciliation):
        monkeypatch.setattr(module, "alert", _record)
    return raised


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:14]}"


async def _tenant(name: str = "Ops Clinic") -> UUID:
    created = await admin_service.create_organization(
        name=name,
        slug=f"ops-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email="owner@example.com",
        language="te-IN",
        created_by=None,
    )
    return UUID(str(created["id"]))


async def _fund(tenant_id: UUID, payment_id: str, amount: str) -> None:
    async with tenant_session(tenant_id) as session:
        await payments.credit_captured_payment(
            session,
            payment=payments.CapturedPayment(
                payment_id=payment_id,
                tenant_id=tenant_id,
                amount_inr=Decimal(amount),
                currency="INR",
            ),
        )


def _facts(payment_id: str, status: str, amount: str = "400.00", **kw: Any) -> DisputeFacts:
    return DisputeFacts(
        dispute_id=kw.pop("dispute_id", None) or _id("disp"),
        payment_id=payment_id,
        amount_inr=Decimal(amount),
        status=status,
        phase=kw.pop("phase", "chargeback"),
        reason_code=kw.pop("reason_code", "fraud"),
        respond_by=kw.pop("respond_by", None),
    )


async def _ledger(tenant_id: UUID) -> list[tuple[str, Decimal, str | None, Any]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT reason, delta, ref, meta FROM credit_ledger WHERE tenant_id = :t "
                    "ORDER BY occurred_at, id"
                ),
                {"t": tenant_id},
            )
        ).all()
    return [(str(r[0]), Decimal(str(r[1])), r[2], r[3]) for r in rows]


async def _audits(tenant_id: UUID, action: str) -> int:
    async with tenant_session(tenant_id) as session:
        return int(
            (
                await session.execute(
                    text("SELECT count(*) FROM audit_log WHERE tenant_id = :t AND action = :a"),
                    {"t": tenant_id, "a": action},
                )
            ).scalar()
            or 0
        )


# --- disputes -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("envelope", "code"),
    [
        ("not an object", "dispute_payload_unrecognized"),
        ({"payload": {"dispute": {"entity": {"id": "disp_1"}}}}, "dispute_payload_unrecognized"),
        (
            {
                "payload": {
                    "dispute": {
                        "entity": {
                            "id": "disp_1",
                            "payment_id": "pay_1",
                            "status": "open",
                            "currency": "USD",
                            "amount": 100,
                        }
                    }
                }
            },
            "payment_currency_unsupported",
        ),
    ],
)
def test_a_dispute_we_cannot_read_records_nothing(envelope: Any, code: str) -> None:
    with pytest.raises(ProblemError) as refused:
        extract_dispute(envelope)
    assert refused.value.code == code


def test_a_dispute_entity_is_read_with_its_deadline() -> None:
    facts = extract_dispute(
        {
            "payload": {
                "dispute": {
                    "entity": {
                        "id": "disp_1",
                        "payment_id": "pay_1",
                        "status": "open",
                        "currency": "inr",
                        "amount": 40000,
                        "phase": "chargeback",
                        "reason_code": "",
                        "respond_by": 1_700_000_000,
                    }
                }
            }
        }
    )
    assert facts.amount_inr == Decimal("400.00")
    assert facts.reason_code is None
    assert facts.respond_by == datetime.fromtimestamp(1_700_000_000, UTC)


async def test_a_dispute_of_a_whole_purchase_comes_off_the_lots_and_is_recorded_on_the_entry() -> (
    None
):
    tenant_id = await _tenant()
    payment_id = _id("pay")
    await _fund(tenant_id, payment_id, "400.00")
    async with tenant_session(tenant_id) as session:
        outcome = await apply_dispute_event(
            session,
            tenant_id=tenant_id,
            event="payment.dispute.created",
            dispute=_facts(payment_id, "open"),
        )
        balance = (await get_balance(session, tenant_id=tenant_id)).amount_inr
    assert outcome == "held"
    assert balance == Decimal("0")
    hold = [r for r in await _ledger(tenant_id) if r[0] == "adjustment"]
    assert len(hold) == 1
    assert hold[0][1] == Decimal("-400.0000")
    assert hold[0][3]["kind"] == disputes.DISPUTE_HOLD_KIND
    assert hold[0][3]["lots"], "the FIFO splits travel on the hold entry"


async def test_action_required_alerts_and_a_closure_releases_only_once(
    alerts: list[str],
) -> None:
    tenant_id = await _tenant()
    payment_id = _id("pay")
    await _fund(tenant_id, payment_id, "1000.00")
    dispute_id = _id("disp")
    async with tenant_session(tenant_id) as session:
        await apply_dispute_event(
            session,
            tenant_id=tenant_id,
            event="payment.dispute.created",
            dispute=_facts(payment_id, "open", dispute_id=dispute_id),
        )
    async with tenant_session(tenant_id) as session:
        outcome = await apply_dispute_event(
            session,
            tenant_id=tenant_id,
            event="payment.dispute.action_required",
            dispute=_facts(payment_id, "open", dispute_id=dispute_id),
        )
    assert outcome == "recorded", "the hold is placed once"
    assert alerts == ["payment_dispute_opened", "payment_dispute_action_required"]
    async with tenant_session(tenant_id) as session:
        assert (
            await apply_dispute_event(
                session,
                tenant_id=tenant_id,
                event="payment.dispute.closed",
                dispute=_facts(payment_id, "closed", dispute_id=dispute_id),
            )
            == "released"
        )
    async with tenant_session(tenant_id) as session:
        assert (
            await apply_dispute_event(
                session,
                tenant_id=tenant_id,
                event="payment.dispute.closed",
                dispute=_facts(payment_id, "closed", dispute_id=dispute_id),
            )
            == "recorded"
        ), "a replayed closure releases nothing twice"
        balance = (await get_balance(session, tenant_id=tenant_id)).amount_inr
    assert balance == Decimal("1000")


async def test_a_dispute_first_seen_as_won_releases_nothing() -> None:
    tenant_id = await _tenant()
    payment_id = _id("pay")
    await _fund(tenant_id, payment_id, "500.00")
    async with tenant_session(tenant_id) as session:
        outcome = await apply_dispute_event(
            session,
            tenant_id=tenant_id,
            event="payment.dispute.won",
            dispute=_facts(payment_id, "won"),
        )
    assert outcome == "recorded"
    assert [r[0] for r in await _ledger(tenant_id)] == ["topup"]


async def test_the_dispute_queue_lists_open_ones_and_names_their_tenant() -> None:
    tenant_id = await _tenant("Queue Clinic")
    payment_id = _id("pay")
    await _fund(tenant_id, payment_id, "1000.00")
    open_id, won_id = _id("disp"), _id("disp")
    async with tenant_session(tenant_id) as session:
        for did, status in ((open_id, "open"), (won_id, "won")):
            await apply_dispute_event(
                session,
                tenant_id=tenant_id,
                event=f"payment.dispute.{status}",
                dispute=_facts(payment_id, status, dispute_id=did),
            )
    assert await disputes.dispute_tenant(open_id) == tenant_id
    assert await disputes.dispute_tenant("disp_nobody") is None

    reader = _admin()
    rows = await payment_admin_routes.read_disputes(reader, include_closed=False, limit=500)
    mine = {r.dispute_id: r for r in rows if r.tenant_id == tenant_id}
    assert set(mine) == {open_id}
    assert mine[open_id].tenant_name == "Queue Clinic"
    assert mine[open_id].hold_inr == Decimal("400.00")
    every = await payment_admin_routes.read_disputes(reader, include_closed=True, limit=500)
    assert {open_id, won_id} <= {r.dispute_id for r in every}


async def test_an_empty_dispute_queue_reads_no_names(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _none(**_: Any) -> list[Any]:
        return []

    monkeypatch.setattr(payment_admin_routes, "list_disputes", _none)
    assert await payment_admin_routes.read_disputes(_admin()) == []


# --- the operator's page --------------------------------------------------------------


def _admin() -> Principal:
    return Principal(realm="admin", user_id=None, tenant_id=None, role="operator")


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/admin/payments",
            "headers": [],
            "query_string": b"",
            "client": ("203.0.113.7", 1234),
        }
    )


FRESH = StepUp(present=True, verified_at=datetime.now(UTC))


async def test_the_status_page_names_the_key_mode_and_only_payment_alarms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)

    def _episode(code: str) -> SimpleNamespace:
        return SimpleNamespace(
            code=code, severity="warning", detail=None, last_seen_at=now, occurrences=2, open=True
        )

    async def _report(_session: Any, **_: Any) -> SimpleNamespace:
        return SimpleNamespace(
            episodes=[_episode("razorpay_refund_failed"), _episode("engine_down")]
        )

    monkeypatch.setattr(payment_admin_routes, "alert_report", _report)
    status = await payment_admin_routes.payment_status(_admin())
    assert status.key_id_mode == "test"
    assert status.key_id_set and status.key_secret_set and status.webhook_secret_set
    assert status.online_payments_available and status.provider_orders_available
    assert status.unavailable_reason is None
    assert status.webhook_path == "/hooks/v1/razorpay"
    assert [a.code for a in status.alarms] == ["razorpay_refund_failed"]

    monkeypatch.setattr(get_settings(), "razorpay_key_id", "rzp_live_ops")
    monkeypatch.setattr(get_settings(), "razorpay_key_secret", None)
    live = await payment_admin_routes.payment_status(_admin())
    assert live.key_id_mode == "live"
    assert live.key_secret_set is False
    assert live.unavailable_reason == payments.NO_API_SECRET_REASON


def _provider_payment(
    payment_id: str,
    *,
    amount: int = 15000,
    status: str = "captured",
    order_id: str | None = None,
    notes: dict[str, str] | None = None,
    currency: str = "INR",
    created_at: int | None = None,
) -> ProviderPayment:
    return ProviderPayment(
        payment_id=payment_id,
        status=status,
        amount_paise=amount,
        currency=currency,
        order_id=order_id,
        method="upi",
        international=False,
        token_id=None,
        customer_id=None,
        notes=notes or {},
        error_code=None,
        created_at=created_at if created_at is not None else int(datetime.now(UTC).timestamp()),
    )


@dataclass
class FakeApi:
    payments: list[ProviderPayment] = field(default_factory=list)
    refunds: list[ProviderRefundRow] = field(default_factory=list)
    settlements: list[ProviderSettlement] = field(default_factory=list)
    accepted: list[str] = field(default_factory=list)
    uploads: list[dict[str, Any]] = field(default_factory=list)
    contests: list[dict[str, Any]] = field(default_factory=list)

    async def list_payments(self, **_: Any) -> list[ProviderPayment]:
        return self.payments

    async def list_refunds(self, **_: Any) -> list[ProviderRefundRow]:
        return self.refunds

    async def list_settlements(self, **_: Any) -> list[ProviderSettlement]:
        return self.settlements

    async def accept_dispute(self, dispute_id: str) -> str:
        self.accepted.append(dispute_id)
        return ""

    async def upload_document(self, **kwargs: Any) -> str:
        self.uploads.append(kwargs)
        return _id("doc")

    async def contest_dispute(self, dispute_id: str, **kwargs: Any) -> str:
        self.contests.append({"dispute_id": dispute_id, **kwargs})
        return ""


async def test_recent_payments_are_read_live_and_matched_to_their_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = await _tenant()
    order_id = _id("order")
    async with tenant_session(tenant_id) as session:
        await record_route(
            session,
            tenant_id=tenant_id,
            object_id=order_id,
            kind="order",
            amount_inr=Decimal("123.45"),
        )
    fake = FakeApi(
        payments=[
            _provider_payment(_id("pay"), amount=12345, order_id=order_id),
            _provider_payment(_id("pay")),
            _provider_payment(_id("pay")),
        ]
    )
    monkeypatch.setattr(payment_admin_routes, "razorpay_api", lambda: fake)
    rows = await payment_admin_routes.recent_payments(_admin(), limit=2)
    assert len(rows) == 2
    assert rows[0].tenant_id == tenant_id and rows[0].amount_inr == Decimal("123.45")
    assert rows[1].tenant_id is None


async def test_the_reconcile_route_reports_the_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _report() -> reconciliation.ReconciliationReport:
        return reconciliation.ReconciliationReport(
            window_days=3,
            payments_seen=4,
            credited_late=["pay_a"],
            settlements=1,
            settled_inr=Decimal("99.5"),
        )

    monkeypatch.setattr(payment_admin_routes, "reconcile", _report)
    out = await payment_admin_routes.run_reconciliation(_admin())
    assert out.window_days == 3 and out.payments_seen == 4
    assert out.credited_late == ["pay_a"]
    assert out.settled_inr == Decimal("99.50")


async def _open_dispute(amount: str = "400.00") -> tuple[UUID, str]:
    tenant_id = await _tenant()
    payment_id = _id("pay")
    await _fund(tenant_id, payment_id, "1000.00")
    dispute_id = _id("disp")
    async with tenant_session(tenant_id) as session:
        await apply_dispute_event(
            session,
            tenant_id=tenant_id,
            event="payment.dispute.created",
            dispute=_facts(payment_id, "open", amount, dispute_id=dispute_id),
        )
    return tenant_id, dispute_id


async def test_accepting_needs_the_confirmation_names_the_dispute_and_is_audited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeApi()
    monkeypatch.setattr(payment_admin_routes, "razorpay_api", lambda: fake)
    tenant_id, dispute_id = await _open_dispute()
    confirm = payment_admin_routes.dispute_confirmation(dispute_id, "accept")
    assert confirm == f"dispute_accept:{dispute_id}"

    with pytest.raises(ProblemError) as unconfirmed:
        await payment_admin_routes.accept(dispute_id, _request(), _admin(), FRESH, None)
    assert unconfirmed.value.code == "step_up_required"
    with pytest.raises(ProblemError) as missing:
        await payment_admin_routes.accept(
            "disp_nobody",
            _request(),
            _admin(),
            FRESH,
            payment_admin_routes.dispute_confirmation("disp_nobody", "accept"),
        )
    assert missing.value.code == "not_found"
    assert fake.accepted == []

    out = await payment_admin_routes.accept(dispute_id, _request(), _admin(), FRESH, confirm)
    assert out.status == "lost", "an empty provider answer reads as the documented outcome"
    assert fake.accepted == [dispute_id]
    assert await _audits(tenant_id, "payment.dispute_accepted") == 1


def _upload(content: bytes = b"%PDF-1.4", content_type: str = "application/pdf") -> UploadFile:
    return UploadFile(
        file=io.BytesIO(content),
        filename="proof.pdf",
        headers=Headers({"content-type": content_type}),
    )


async def _contest(
    dispute_id: str, files: list[UploadFile], amount: str | None = None
) -> payment_admin_routes.DisputeActionOut:
    return await payment_admin_routes.contest(
        dispute_id,
        _request(),
        _admin(),
        FRESH,
        summary="The customer used every minute they paid for.",
        evidence_kind="billing_proof",
        files=files,
        amount_inr=amount,
        x_confirm_action=payment_admin_routes.dispute_confirmation(dispute_id, "contest"),
    )


@pytest.mark.parametrize(
    ("amount", "files", "code"),
    [
        (None, [], "dispute_evidence_missing"),
        ("abc", None, "dispute_amount_invalid"),
        ("NaN", None, "dispute_amount_invalid"),
        ("0", None, "dispute_amount_invalid"),
        ("400.01", None, "dispute_amount_invalid"),
        (None, "text/plain", "dispute_evidence_invalid"),
    ],
)
async def test_a_contest_is_refused_before_anything_is_submitted(
    monkeypatch: pytest.MonkeyPatch, amount: str | None, files: Any, code: str
) -> None:
    fake = FakeApi()
    monkeypatch.setattr(payment_admin_routes, "razorpay_api", lambda: fake)
    _tenant_id, dispute_id = await _open_dispute()
    if files is None:
        uploads = [_upload()]
    elif isinstance(files, str):
        uploads = [_upload(content_type=files)]
    else:
        uploads = files
    with pytest.raises(ProblemError) as refused:
        await _contest(dispute_id, uploads, amount)
    assert refused.value.code == code
    assert fake.contests == []


async def test_an_oversized_evidence_file_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeApi()
    monkeypatch.setattr(payment_admin_routes, "razorpay_api", lambda: fake)
    _tenant_id, dispute_id = await _open_dispute()
    big = b"x" * (payment_admin_routes._EVIDENCE_MAX_BYTES + 1)
    with pytest.raises(ProblemError) as refused:
        await _contest(dispute_id, [_upload(big)])
    assert refused.value.code == "dispute_evidence_invalid"
    assert fake.uploads == []


async def test_a_contest_uploads_each_document_and_submits_the_disputed_amount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeApi()
    monkeypatch.setattr(payment_admin_routes, "razorpay_api", lambda: fake)
    tenant_id, dispute_id = await _open_dispute()
    out = await _contest(dispute_id, [_upload(), _upload(b"\x89PNG", "image/png")])
    assert out.status == "under_review"
    assert [u["content_type"] for u in fake.uploads] == ["application/pdf", "image/png"]
    contest = fake.contests[0]
    assert contest["amount_paise"] == 40000
    assert len(contest["evidence"]["billing_proof"]) == 2
    assert await _audits(tenant_id, "payment.dispute_contested") == 1

    await _contest(dispute_id, [_upload()], "150.50")
    assert fake.contests[1]["amount_paise"] == 15050


# --- event handlers -----------------------------------------------------------------------


def _payment_envelope(
    *,
    payment_id: str,
    order_id: str | None,
    amount: int,
    notes: Any,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entity: dict[str, Any] = {
        "id": payment_id,
        "amount": amount,
        "currency": "INR",
        "status": "captured",
        "notes": notes,
        **(extra or {}),
    }
    if order_id is not None:
        entity["order_id"] = order_id
    return {"payload": {"payment": {"entity": entity}}}


async def test_a_captured_authorisation_payment_records_the_mandates_token() -> None:
    tenant_id = await _tenant()
    order_id, token_id = _id("order"), _id("token")
    async with tenant_session(tenant_id) as session:
        await record_route(
            session,
            tenant_id=tenant_id,
            object_id=order_id,
            kind="order",
            purpose=MANDATE,
            amount_inr=Decimal("1.00"),
        )
        await session.execute(
            text(
                "INSERT INTO auto_recharge_settings (id, tenant_id, enabled, threshold_inr, "
                "amount_inr, monthly_cap_inr, customer_id, mandate_method, mandate_status, "
                "mandate_order_id) VALUES (:id, :t, false, 500, 2000, 6000, 'cust_1', 'upi', "
                "'pending', :o)"
            ),
            {"id": uuid.uuid4(), "t": tenant_id, "o": order_id},
        )
    result = await payment_events.apply_captured(
        _payment_envelope(
            payment_id=_id("pay"),
            order_id=order_id,
            amount=100,
            notes=[],
            extra={"token_id": token_id},
        ),
        event="payment.captured",
        event_id=None,
    )
    assert result.status == "credited" and result.amount_inr == Decimal("1.00")
    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(
                text("SELECT token_id FROM auto_recharge_settings WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
        ).scalar()
    assert stored == token_id


async def test_a_payment_whose_notes_name_another_client_than_its_order_is_refused() -> None:
    owner, other = await _tenant(), await _tenant()
    order_id = _id("order")
    async with tenant_session(owner) as session:
        await record_route(
            session, tenant_id=owner, object_id=order_id, kind="order", amount_inr=Decimal("100")
        )
    with pytest.raises(ProblemError) as refused:
        await payment_events.apply_captured(
            _payment_envelope(
                payment_id=_id("pay"),
                order_id=order_id,
                amount=10000,
                notes={payments.NOTES_TENANT_KEY: str(other)},
            ),
            event="payment.captured",
            event_id=None,
        )
    assert refused.value.code == "payment_order_mismatch"
    for tenant in (owner, other):
        async with tenant_session(tenant) as session:
            assert (await get_balance(session, tenant_id=tenant)).amount_inr == 0
    verify_order(
        payments.CapturedPayment(
            payment_id="pay_x", tenant_id=owner, amount_inr=Decimal("1"), currency="INR"
        ),
        None,
    )


async def test_a_failed_auto_recharge_debit_fails_its_charge() -> None:
    tenant_id = await _tenant()
    order_id = _id("order")
    async with tenant_session(tenant_id) as session:
        await record_route(
            session,
            tenant_id=tenant_id,
            object_id=order_id,
            kind="order",
            purpose=AUTO_RECHARGE,
            amount_inr=Decimal("2000.00"),
        )
        await session.execute(
            text(
                "INSERT INTO auto_recharge_settings (id, tenant_id, enabled, threshold_inr, "
                "amount_inr, monthly_cap_inr) VALUES (:id, :t, false, 500, 2000, 6000)"
            ),
            {"id": uuid.uuid4(), "t": tenant_id},
        )
        await session.execute(
            text(
                "INSERT INTO auto_recharge_charges (id, tenant_id, order_id, amount_inr, status) "
                "VALUES (:id, :t, :o, 2000, 'pending')"
            ),
            {"id": uuid.uuid4(), "t": tenant_id, "o": order_id},
        )
    result = await payment_events.apply_payment_state(
        _payment_envelope(
            payment_id=_id("pay"),
            order_id=order_id,
            amount=200000,
            notes=[],
            extra={"error_code": "BAD_REQUEST_ERROR"},
        ),
        event="payment.failed",
        failed=True,
    )
    assert result.status == "failed"
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT status, failure_code FROM auto_recharge_charges WHERE order_id = :o"),
                {"o": order_id},
            )
        ).one()
    assert tuple(row) == ("failed", "BAD_REQUEST_ERROR")


@pytest.mark.parametrize(
    "envelope",
    [
        "not an object",
        {"payload": {"token": {"entity": {"recurring_details": {}}}}},
        {"payload": {"token": {"entity": {"id": "token_nobody"}}}},
    ],
)
async def test_a_token_event_we_cannot_place_is_acked_and_ignored(envelope: Any) -> None:
    result = await payment_events.apply_token(envelope, event="token.confirmed")
    assert result.status == "ignored"


async def test_an_unknown_token_event_name_is_ignored() -> None:
    result = await payment_events.apply_token(
        {"payload": {"token": {"entity": {"id": "token_1"}}}}, event="token.created"
    )
    assert result.status == "ignored"


def _dispute_envelope(*, dispute_id: str, payment: dict[str, Any] | None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "dispute": {
            "entity": {
                "id": dispute_id,
                "payment_id": "pay_disputed",
                "status": "open",
                "currency": "INR",
                "amount": 10000,
            }
        }
    }
    if payment is not None:
        payload["payment"] = {"entity": payment}
    return {"event": "payment.dispute.created", "payload": payload}


async def test_a_dispute_is_placed_by_our_order_and_a_replay_is_a_duplicate(
    alerts: list[str],
) -> None:
    tenant_id = await _tenant()
    order_id = _id("order")
    async with tenant_session(tenant_id) as session:
        await record_route(
            session, tenant_id=tenant_id, object_id=order_id, kind="order", amount_inr=Decimal("1")
        )
    envelope = _dispute_envelope(
        dispute_id=_id("disp"),
        payment={"id": "pay_disputed", "order_id": order_id, "notes": {"x": "not-a-uuid"}},
    )
    first = await payment_events.apply_dispute(
        envelope, event="payment.dispute.created", event_id="evt_dispute_1" + uuid.uuid4().hex
    )
    assert first.status == "dispute"
    replay_id = "evt_dispute_2" + uuid.uuid4().hex
    await payment_events.apply_dispute(
        envelope, event="payment.dispute.created", event_id=replay_id
    )
    again = await payment_events.apply_dispute(
        envelope, event="payment.dispute.created", event_id=replay_id
    )
    assert again.status == "duplicate"
    assert "payment_dispute_opened" in alerts


@pytest.mark.parametrize(
    "payment",
    [None, {"id": "pay_disputed", "notes": {payments.NOTES_TENANT_KEY: "not-a-uuid"}}],
)
async def test_a_dispute_naming_no_client_is_refused_and_alarmed(
    alerts: list[str], payment: dict[str, Any] | None
) -> None:
    with pytest.raises(ProblemError) as refused:
        await payment_events.apply_dispute(
            _dispute_envelope(dispute_id=_id("disp"), payment=payment),
            event="payment.dispute.created",
            event_id=None,
        )
    assert refused.value.code == "not_found"
    assert alerts == ["razorpay_unknown_tenant"]


# --- reconciliation -----------------------------------------------------------------------


async def test_reconciliation_reports_every_kind_of_payment_finding(
    monkeypatch: pytest.MonkeyPatch, alerts: list[str]
) -> None:
    tenant_id = await _tenant()
    notes = {payments.NOTES_TENANT_KEY: str(tenant_id)}
    old = int((datetime.now(UTC) - timedelta(hours=2)).timestamp())
    on_ledger, wrong_amount = _id("pay"), _id("pay")
    await _fund(tenant_id, on_ledger, "150.00")
    await _fund(tenant_id, wrong_amount, "150.00")
    mismatched_order = _id("order")
    async with tenant_session(tenant_id) as session:
        await record_route(
            session,
            tenant_id=tenant_id,
            object_id=mismatched_order,
            kind="order",
            amount_inr=Decimal("500.00"),
        )
    stale, young, ours_elsewhere, failed, foreign = (_id("pay") for _ in range(5))
    refused = _id("pay")
    fake = FakeApi(
        payments=[
            _provider_payment(stale, status="authorized", notes=notes, created_at=old),
            _provider_payment(young, status="authorized", notes=notes),
            _provider_payment(_id("pay"), status="authorized", created_at=old),
            _provider_payment(failed, status="failed", notes=notes),
            _provider_payment(foreign, currency="USD", notes=notes),
            _provider_payment(on_ledger, notes=notes),
            _provider_payment(wrong_amount, amount=99900, notes=notes),
            _provider_payment(refused, order_id=mismatched_order, amount=40000),
            _provider_payment(ours_elsewhere, notes={payments.NOTES_TENANT_KEY: "nope"}),
        ],
        settlements=[
            ProviderSettlement(
                settlement_id="setl_1", amount_paise=12345, status="processed", created_at=0
            ),
            ProviderSettlement(
                settlement_id="setl_2", amount_paise=55, status="processed", created_at=0
            ),
        ],
    )
    monkeypatch.setattr(reconciliation, "razorpay_api", lambda: fake)
    report = await reconciliation.reconcile()
    assert report.payments_seen == 9
    assert report.credited_late == []
    assert sorted(report.unexplained) == sorted(
        [
            f"uncaptured:{stale}",
            f"amount:{wrong_amount}",
            f"payment_order_mismatch:{refused}",
            f"unattributed:{ours_elsewhere}",
        ]
    )
    assert report.settlements == 2 and report.settled_inr == Decimal("124.00")
    assert alerts == ["razorpay_reconciliation_unexplained"]
    assert [r[2] for r in await _ledger(tenant_id)] == [on_ledger, wrong_amount]


async def test_reconciliation_records_lost_refunds_and_flags_those_it_cannot_place(
    monkeypatch: pytest.MonkeyPatch, alerts: list[str]
) -> None:
    tenant_id = await _tenant()
    notes = {payments.NOTES_TENANT_KEY: str(tenant_id)}
    paid, routed = _id("pay"), _id("pay")
    await _fund(tenant_id, paid, "500.00")
    await _fund(tenant_id, routed, "300.00")

    def _refund(rid: str, payment_id: str, **kw: Any) -> ProviderRefundRow:
        return ProviderRefundRow(
            refund_id=rid,
            payment_id=payment_id,
            amount_paise=kw.get("amount", 10000),
            currency=kw.get("currency", "INR"),
            status=kw.get("status", "processed"),
            notes=kw.get("notes", {}),
        )

    by_notes, by_payment, orphan, no_topup, pending = (_id("rfnd") for _ in range(5))
    fake = FakeApi(
        payments=[_provider_payment(routed, amount=30000, notes=notes)],
        refunds=[
            _refund(by_notes, paid, notes=notes),
            _refund(by_payment, routed, amount=5000),
            _refund(orphan, "pay_unknown"),
            _refund(no_topup, "pay_never_paid", notes=notes),
            _refund(pending, paid, status="pending", notes=notes),
            _refund(_id("rfnd"), paid, currency="USD", notes=notes),
        ],
    )
    monkeypatch.setattr(reconciliation, "razorpay_api", lambda: fake)
    report = await reconciliation.reconcile()
    assert report.refunds_seen == 6
    assert sorted(report.refunds_recorded_late) == sorted([by_notes, by_payment])
    assert sorted(report.unexplained) == sorted([f"refund:{orphan}", f"refund:{no_topup}"])
    assert alerts == ["razorpay_reconciliation_credited", "razorpay_reconciliation_unexplained"]
    async with tenant_session(tenant_id) as session:
        assert (await get_balance(session, tenant_id=tenant_id)).amount_inr == Decimal("650")

    alerts.clear()
    again = await reconciliation.reconcile()
    assert again.refunds_recorded_late == [], "a second pass finds them on the ledger"
    assert alerts == ["razorpay_reconciliation_unexplained"]


async def test_a_webhook_landing_mid_pass_is_not_reported_as_credited_late(
    monkeypatch: pytest.MonkeyPatch, alerts: list[str]
) -> None:
    tenant_id = await _tenant()
    payment_id = _id("pay")
    await _fund(tenant_id, payment_id, "150.00")
    fake = FakeApi(
        payments=[_provider_payment(payment_id, notes={payments.NOTES_TENANT_KEY: str(tenant_id)})]
    )
    monkeypatch.setattr(reconciliation, "razorpay_api", lambda: fake)

    async def _not_yet(*_: Any, **__: Any) -> None:
        return None

    # The pass read the ledger before the webhook's credit committed.
    monkeypatch.setattr(reconciliation, "find_topup", _not_yet)
    report = await reconciliation.reconcile()
    assert report.credited_late == [] and report.unexplained == []
    assert alerts == []
    assert len(await _ledger(tenant_id)) == 1


def test_notes_that_name_no_valid_tenant_attribute_nothing() -> None:
    assert reconciliation._tenant_of_notes({payments.NOTES_TENANT_KEY: "nope"}) is None
    assert reconciliation._tenant_of_notes({}) is None
