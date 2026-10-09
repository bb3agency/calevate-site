"""The operator's payments page (D-699): mode, disputes, reconciliation, recent payments.

    GET  /v1/admin/payments/status                         mode, keys, webhook, alarms
    GET  /v1/admin/payments/recent                         Razorpay's last payments, live
    POST /v1/admin/payments/reconcile                      run the daily reconciliation now
    GET  /v1/admin/payments/disputes                       every client's disputes
    POST /v1/admin/payments/disputes/{id}/accept           accept (irreversible; step-up)
    POST /v1/admin/payments/disputes/{id}/contest          evidence + summary (step-up)

Refunds stay per client, on the credits screen (`payment_routes.refund_router`).
Nothing here returns a secret: the status page says whether each credential is SET and
which mode the key id belongs to, never a value.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, Query, Request, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from apps.api.billing.disputes import dispute_tenant, list_disputes
from apps.api.billing.payment_objects import route_for
from apps.api.billing.payments import (
    KEY_ID_PREFIX,
    SUBSCRIBED_EVENTS,
    inr_to_paise,
    payment_capability,
    payment_mode_problem,
    razorpay_api_secret,
)
from apps.api.billing.razorpay_api import EvidenceKind, razorpay_api
from apps.api.billing.reconciliation import reconcile
from apps.api.billing.service import to_paise
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.core.settings import get_settings
from apps.api.core.stepup import StepUpGate
from apps.api.db.session import admin_session, tenant_session, untenanted_session
from apps.api.ops.alerts_service import alert_report

router = APIRouter(prefix="/v1/admin/payments", tags=["admin"])

Reader = Annotated[Principal, Depends(requires("org:read", realm="admin"))]
Operator = Annotated[Principal, Depends(requires("admin:tenants", realm="admin"))]

#: The webhook path to register in the Razorpay dashboard, on the API host.
WEBHOOK_PATH = "/hooks/v1/razorpay"
#: Alarm codes this page shows, by prefix.
_PAYMENT_ALARM_PREFIXES = ("razorpay_", "topup_", "auto_recharge_", "payment_dispute_")
#: Evidence files: what Razorpay's Documents API is documented with (jpg/pdf samples,
#: `api/documents/create.md`); the size limit is ours, as the docs state none.
_EVIDENCE_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png"})
_EVIDENCE_MAX_BYTES = 5 * 1024 * 1024


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PaymentAlarmOut(_Strict):
    code: str
    severity: str
    detail: str | None
    last_seen_at: datetime
    occurrences: int
    open: bool


class PaymentStatusOut(_Strict):
    provider: str | None
    #: `test`, `live` or null (unset).
    mode: Literal["test", "live"] | None
    #: Which mode the key id's prefix says it belongs to, or null if neither.
    key_id_mode: Literal["test", "live"] | None
    key_id_set: bool
    key_secret_set: bool
    webhook_secret_set: bool
    online_payments_available: bool
    provider_orders_available: bool
    #: Our own reason code when payments are unavailable (an operator surface).
    unavailable_reason: str | None
    webhook_path: str
    subscribed_events: list[str]
    alarms: list[PaymentAlarmOut]


@router.get(
    "/status",
    response_model=PaymentStatusOut,
    openapi_extra=permission_meta("org:read"),
    summary="Razorpay mode, which credentials are set, the webhook to register, and alarms",
)
async def payment_status(_principal: Reader) -> PaymentStatusOut:
    settings = get_settings()
    capability = payment_capability()
    key_id = settings.razorpay_key_id or ""
    key_mode: Literal["test", "live"] | None = None
    for mode in ("test", "live"):
        if key_id.startswith(KEY_ID_PREFIX[mode]):
            key_mode = "test" if mode == "test" else "live"
    async with untenanted_session() as session:
        report = await alert_report(session, days=7, limit=500)
    alarms = [
        PaymentAlarmOut(
            code=e.code,
            severity=e.severity,
            detail=e.detail,
            last_seen_at=e.last_seen_at,
            occurrences=e.occurrences,
            open=e.open,
        )
        for e in report.episodes
        if e.code.startswith(_PAYMENT_ALARM_PREFIXES)
    ]
    return PaymentStatusOut(
        provider=settings.payment_provider,
        mode=settings.razorpay_mode,
        key_id_mode=key_mode,
        key_id_set=bool(key_id),
        key_secret_set=razorpay_api_secret() is not None,
        webhook_secret_set=bool(settings.razorpay_webhook_secret),
        online_payments_available=capability.available,
        provider_orders_available=capability.creates_orders,
        unavailable_reason=capability.reason or payment_mode_problem() or capability.orders_reason,
        webhook_path=WEBHOOK_PATH,
        subscribed_events=list(SUBSCRIBED_EVENTS),
        alarms=alarms,
    )


class RecentPaymentOut(_Strict):
    payment_id: str
    status: str
    amount_inr: Decimal
    method: str | None
    international: bool
    tenant_id: UUID | None
    created_at: int


@router.get(
    "/recent",
    response_model=list[RecentPaymentOut],
    openapi_extra=permission_meta("org:read"),
    summary="Razorpay's payments of the last three days, read live, with the client each is for",
)
async def recent_payments(
    _principal: Reader, limit: Annotated[int, Query(ge=1, le=100)] = 100
) -> list[RecentPaymentOut]:
    now = int(datetime.now().timestamp())
    payments = await razorpay_api().list_payments(since=now - 3 * 86400, until=now)
    out: list[RecentPaymentOut] = []
    for p in payments[:limit]:
        route = await route_for(p.order_id)
        out.append(
            RecentPaymentOut(
                payment_id=p.payment_id,
                status=p.status,
                amount_inr=to_paise(Decimal(p.amount_paise) / 100),
                method=p.method,
                international=p.international,
                tenant_id=None if route is None else route.tenant_id,
                created_at=p.created_at,
            )
        )
    return out


class ReconcileOut(_Strict):
    window_days: int
    payments_seen: int
    refunds_seen: int
    credited_late: list[str]
    refunds_recorded_late: list[str]
    unexplained: list[str]
    settlements: int
    settled_inr: Decimal


@router.post(
    "/reconcile",
    response_model=ReconcileOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Run the Razorpay reconciliation now (it also runs daily)",
)
async def run_reconciliation(_principal: Operator) -> ReconcileOut:
    report = await reconcile()
    return ReconcileOut(
        window_days=report.window_days,
        payments_seen=report.payments_seen,
        refunds_seen=report.refunds_seen,
        credited_late=report.credited_late,
        refunds_recorded_late=report.refunds_recorded_late,
        unexplained=report.unexplained,
        settlements=report.settlements,
        settled_inr=to_paise(report.settled_inr),
    )


class DisputeOut(_Strict):
    tenant_id: UUID
    tenant_name: str | None
    dispute_id: str
    payment_id: str
    amount_inr: Decimal
    hold_inr: Decimal
    status: str
    phase: str | None
    reason_code: str | None
    respond_by: datetime | None
    action_required: bool
    created_at: datetime


@router.get(
    "/disputes",
    response_model=list[DisputeOut],
    openapi_extra=permission_meta("org:read"),
    summary="Every client's disputed payments, open ones first",
)
async def read_disputes(
    _principal: Reader,
    include_closed: bool = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[DisputeOut]:
    rows = await list_disputes(include_closed=include_closed, limit=limit)
    names: dict[UUID, str] = {}
    if rows:
        async with admin_session() as session:
            found = (
                await session.execute(
                    text("SELECT id, name FROM organizations WHERE id = ANY(:ids)"),
                    {"ids": list({r.tenant_id for r in rows})},
                )
            ).all()
        names = {UUID(str(i)): str(n) for i, n in found}
    return [
        DisputeOut(
            tenant_id=r.tenant_id,
            tenant_name=names.get(r.tenant_id),
            dispute_id=r.dispute_id,
            payment_id=r.payment_id,
            amount_inr=r.amount_inr,
            hold_inr=r.hold_inr,
            status=r.status,
            phase=r.phase,
            reason_code=r.reason_code,
            respond_by=r.respond_by,
            action_required=r.action_required,
            created_at=r.created_at,
        )
        for r in rows
    ]


def dispute_confirmation(dispute_id: str, act: Literal["accept", "contest"]) -> str:
    """The `X-Confirm-Action` for accepting or contesting ONE dispute."""
    return f"dispute_{act}:{dispute_id}"


class DisputeActionOut(_Strict):
    dispute_id: str
    status: str


async def _tenant_or_404(dispute_id: str) -> UUID:
    tenant_id = await dispute_tenant(dispute_id)
    if tenant_id is None:
        raise ProblemError.not_found("Dispute")
    return tenant_id


@router.post(
    "/disputes/{dispute_id}/accept",
    response_model=DisputeActionOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Accept a dispute: the customer is refunded and the dispute is lost (irreversible)",
)
async def accept(
    dispute_id: str,
    request: Request,
    principal: Operator,
    step_up: StepUpGate,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> DisputeActionOut:
    step_up.require(x_confirm_action, dispute_confirmation(dispute_id, "accept"))
    tenant_id = await _tenant_or_404(dispute_id)
    status = await razorpay_api().accept_dispute(dispute_id)
    async with tenant_session(tenant_id) as session:
        await write_audit(
            session,
            action="payment.dispute_accepted",
            actor=principal,
            tenant_id=tenant_id,
            object_type="payment_disputes",
            object_id=dispute_id,
            ip=client_request_ip(request),
            summary={"provider_status": status},
        )
    return DisputeActionOut(dispute_id=dispute_id, status=status or "lost")


@router.post(
    "/disputes/{dispute_id}/contest",
    response_model=DisputeActionOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Contest a dispute with evidence documents and a summary",
    description=(
        "Uploads each file to the payment provider as dispute evidence (PDF, JPEG or PNG, "
        "5 MB each), then submits the contest. At least one document is required."
    ),
)
async def contest(
    dispute_id: str,
    request: Request,
    principal: Operator,
    step_up: StepUpGate,
    summary: Annotated[str, Form(min_length=10, max_length=1000)],
    evidence_kind: Annotated[EvidenceKind, Form()],
    files: Annotated[list[UploadFile], File()],
    amount_inr: Annotated[str | None, Form()] = None,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> DisputeActionOut:
    step_up.require(x_confirm_action, dispute_confirmation(dispute_id, "contest"))
    tenant_id = await _tenant_or_404(dispute_id)
    if not files:
        raise ProblemError.business_rule(
            "dispute_evidence_missing",
            "Contesting a dispute needs at least one document.",
            remediation="Attach a receipt, the call records or our terms as a PDF or image.",
        )
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT amount_inr FROM payment_disputes WHERE dispute_id = :did"),
                {"did": dispute_id},
            )
        ).first()
    assert row is not None
    disputed = Decimal(str(row[0]))
    try:
        amount = Decimal(amount_inr) if amount_inr else disputed
    except ArithmeticError as exc:
        raise ProblemError.business_rule(
            "dispute_amount_invalid",
            "The contested amount must be a rupee amount.",
            remediation='Send it as digits, for example "1500.00".',
        ) from exc
    if not amount.is_finite() or amount <= 0 or amount > disputed:
        raise ProblemError.business_rule(
            "dispute_amount_invalid",
            "The contested amount must be more than zero and at most the disputed amount.",
            remediation="Leave it empty to contest the whole amount.",
        )
    api = razorpay_api()
    doc_ids: list[str] = []
    for upload in files:
        content = await upload.read()
        if upload.content_type not in _EVIDENCE_TYPES or len(content) > _EVIDENCE_MAX_BYTES:
            raise ProblemError.business_rule(
                "dispute_evidence_invalid",
                "Evidence must be a PDF, JPEG or PNG of at most 5 MB.",
                remediation="Convert or shrink the file and try again.",
            )
        doc_ids.append(
            await api.upload_document(
                filename=upload.filename or "evidence",
                content=content,
                content_type=str(upload.content_type),
            )
        )
    status = await api.contest_dispute(
        dispute_id,
        summary=summary,
        amount_paise=inr_to_paise(to_paise(amount)),
        evidence={evidence_kind: doc_ids},
    )
    async with tenant_session(tenant_id) as session:
        await write_audit(
            session,
            action="payment.dispute_contested",
            actor=principal,
            tenant_id=tenant_id,
            object_type="payment_disputes",
            object_id=dispute_id,
            ip=client_request_ip(request),
            summary={
                "documents": str(len(doc_ids)),
                "evidence_kind": evidence_kind,
                "amount_inr": str(to_paise(amount)),
                "provider_status": status,
            },
        )
    return DisputeActionOut(dispute_id=dispute_id, status=status or "under_review")


__all__ = ["WEBHOOK_PATH", "dispute_confirmation", "router"]
