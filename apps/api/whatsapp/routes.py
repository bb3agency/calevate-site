"""The client's WhatsApp screen: connect through Meta, see the account, manage templates
(D-784).

Reads are `org:read`; every write is `org:manage` and the owner's own act: an operator
viewing the account is refused (`integrations.connect`, D-587), as for every other account
connection. Each write is audited. No response carries a token; the two-step verification
PIN is returned once, by the request that set it, and is never stored.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Final, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.core.auth import assert_view_as_may, client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.whatsapp import accounts, signup, templates
from apps.api.whatsapp.signup import CONNECTED_ACTION

router = APIRouter(prefix="/v1/whatsapp", tags=["whatsapp"])
Session = Annotated[AsyncSession, Depends(db)]

#: Meta's own pricing pages, which the client reads instead of a rate we would have to keep
#: current. Both read 15 Oct 2026; India's INR figures are in Meta's rate-card download.
PRICING_URL: Final = (
    "https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing"
)
PAYMENT_METHOD_URL: Final = "https://business.facebook.com/wa/manage/home/"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WhatsAppSetupOut(Strict):
    available: bool
    #: `not_configured` (Calevate has not finished Meta's set-up) or `weekly_limit`.
    reason: str | None
    coexistence: bool
    pricing_url: str
    payment_method_url: str


class WhatsAppAccountOut(Strict):
    id: UUID
    status: str
    onboarding: str
    display_phone_number: str | None
    verified_name: str | None
    name_status: str | None
    quality_rating: str | None
    messaging_limit: str | None
    registered: bool
    webhooks_subscribed: bool
    setup_error: str | None
    templates_submitted: bool
    account_alert: str | None
    last_send_error: str | None
    last_event_at: datetime | None
    connected_at: datetime | None


class WhatsAppOverviewOut(Strict):
    setup: WhatsAppSetupOut
    accounts: list[WhatsAppAccountOut]


class WhatsAppSignupIn(Strict):
    choice: Literal["new", "business_app", "grant_access"]


class WhatsAppSignupOut(Strict):
    state: str
    app_id: str
    config_id: str
    graph_version: str
    #: The `extras` object for Meta's FB.login, decided here so the browser holds no rule.
    extras: dict[str, Any]


class WhatsAppConnectIn(Strict):
    state: str = Field(min_length=1, max_length=2048)
    code: str = Field(min_length=1, max_length=2048)
    event: str = Field(min_length=1, max_length=64)
    waba_id: str = Field(min_length=1, max_length=64, pattern=r"^[0-9]+$")
    phone_number_id: str | None = Field(default=None, max_length=64, pattern=r"^[0-9]*$")
    business_id: str | None = Field(default=None, max_length=64, pattern=r"^[0-9]*$")


class WhatsAppConnectOut(Strict):
    account: WhatsAppAccountOut
    #: The number's two-step verification PIN: shown once, never stored by Calevate.
    pin: str | None
    failed_step: str | None


class WhatsAppTemplateVariableIn(Strict):
    label: str = Field(min_length=1, max_length=60)
    example: str = Field(min_length=1, max_length=200)


class WhatsAppTemplateIn(Strict):
    account_id: UUID
    name: str = Field(min_length=1, max_length=512)
    language: str = Field(min_length=2, max_length=16)
    category: Literal["UTILITY", "MARKETING"]
    body: str = Field(min_length=1, max_length=1024)
    variables: list[WhatsAppTemplateVariableIn] = Field(default_factory=list, max_length=10)


class WhatsAppTemplateOut(Strict):
    id: UUID
    account_id: UUID
    name: str
    language: str
    category: str
    body: str
    variables: list[dict[str, str]]
    origin: str
    purpose: str | None
    status: str
    rejection_code: str | None
    category_changed_to: str | None
    submitted_at: datetime | None
    decided_at: datetime | None


def _account_out(a: accounts.Account) -> WhatsAppAccountOut:
    return WhatsAppAccountOut(
        id=a.id,
        status=a.status,
        onboarding=a.onboarding,
        display_phone_number=a.display_phone_number,
        verified_name=a.verified_name,
        name_status=a.name_status,
        quality_rating=a.quality_rating,
        messaging_limit=a.messaging_limit,
        registered=a.registered,
        webhooks_subscribed=a.webhooks_subscribed,
        setup_error=a.setup_error,
        templates_submitted=a.templates_seeded_at is not None,
        account_alert=a.account_alert,
        last_send_error=a.last_send_error,
        last_event_at=a.last_event_at,
        connected_at=a.connected_at,
    )


def _owner(principal: Principal) -> tuple[UUID, UUID]:
    assert principal.tenant_id is not None
    assert_view_as_may(principal, "integrations.connect")
    if principal.client_user_id is None:
        raise ProblemError.business_rule(
            "whatsapp_owner_only", "Only the account owner can connect WhatsApp."
        )
    return principal.tenant_id, principal.client_user_id


def extras_for(choice: str) -> dict[str, Any]:
    """FB.login `extras` for each choice. v4 sends `{setup: {}}` (embedded-signup/
    implementation.md); the coexistence flow adds `featureType:
    whatsapp_business_app_onboarding` and `sessionInfoVersion: "3"`
    (onboarding-business-app-users, read 15 Oct 2026). How v4 selects "app-only install"
    for an existing account is not documented (only a v3 snippet exists): the standard flow
    is opened and the client picks their existing account inside it (OPERATIONS gate W-5).
    """
    if choice == "business_app":
        return {
            "setup": {},
            "featureType": "whatsapp_business_app_onboarding",
            "sessionInfoVersion": "3",
        }
    return {"setup": {}}


@router.get(
    "",
    response_model=WhatsAppOverviewOut,
    openapi_extra=permission_meta("org:read"),
    summary="This account's WhatsApp: whether Meta signup is available, and connected numbers",
)
async def overview(
    session: Session, _: Principal = Depends(requires("org:read"))
) -> WhatsAppOverviewOut:
    setup = await signup.signup_setup(session)
    return WhatsAppOverviewOut(
        setup=WhatsAppSetupOut(
            available=setup.available,
            reason=setup.reason,
            coexistence=setup.coexistence,
            pricing_url=PRICING_URL,
            payment_method_url=PAYMENT_METHOD_URL,
        ),
        accounts=[_account_out(a) for a in await accounts.list_accounts(session)],
    )


@router.post(
    "/signup",
    response_model=WhatsAppSignupOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Begin connecting WhatsApp through Meta's Embedded Signup",
)
async def begin_signup(
    payload: WhatsAppSignupIn,
    session: Session,
    principal: Principal = Depends(requires("org:manage")),
) -> WhatsAppSignupOut:
    tenant_id, user_id = _owner(principal)
    setup, state = await signup.start(session, tenant_id=tenant_id, user_id=user_id)
    if payload.choice == "business_app" and not setup.coexistence:
        raise ProblemError.business_rule(
            "whatsapp_coexistence_off",
            "Keeping the WhatsApp Business app on the same number is not available yet.",
            remediation="Use another mobile number for WhatsApp with Calevate.",
        )
    return WhatsAppSignupOut(
        state=state,
        app_id=str(setup.app_id),
        config_id=str(setup.config_id),
        graph_version=setup.graph_version,
        extras=extras_for(payload.choice),
    )


@router.post(
    "/connect",
    response_model=WhatsAppConnectOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Finish connecting WhatsApp: exchange Meta's code, register the number",
)
async def connect(
    payload: WhatsAppConnectIn,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("org:manage")),
) -> WhatsAppConnectOut:
    tenant_id, user_id = _owner(principal)
    outcome = await signup.connect(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        payload=signup.ConnectIn(
            state=payload.state,
            code=payload.code,
            event=payload.event,
            waba_id=payload.waba_id,
            phone_number_id=payload.phone_number_id or None,
            business_id=payload.business_id or None,
        ),
    )
    account = await accounts.get_account(session, outcome.account_id)
    await write_audit(
        session,
        action=CONNECTED_ACTION,
        actor=principal,
        tenant_id=tenant_id,
        object_type="whatsapp_account",
        object_id=str(account.id),
        ip=client_request_ip(request),
        summary={
            "onboarding": account.onboarding,
            "status": account.status,
            "failed_step": outcome.failed_step or "",
        },
    )
    return WhatsAppConnectOut(
        account=_account_out(account), pin=outcome.pin, failed_step=outcome.failed_step
    )


@router.post(
    "/accounts/{account_id}/finish",
    response_model=WhatsAppConnectOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Retry the WhatsApp set-up steps that did not finish",
)
async def finish(
    account_id: UUID,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("org:manage")),
) -> WhatsAppConnectOut:
    tenant_id, _ = _owner(principal)
    outcome = await accounts.finish_setup(session, tenant_id=tenant_id, account_id=account_id)
    account = await accounts.get_account(session, account_id)
    await write_audit(
        session,
        action="whatsapp.setup_retried",
        actor=principal,
        tenant_id=tenant_id,
        object_type="whatsapp_account",
        object_id=str(account_id),
        ip=client_request_ip(request),
        summary={"status": account.status, "failed_step": outcome.failed_step or ""},
    )
    return WhatsAppConnectOut(
        account=_account_out(account), pin=outcome.pin, failed_step=outcome.failed_step
    )


@router.post(
    "/accounts/{account_id}/disconnect",
    response_model=WhatsAppAccountOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Stop sending from this WhatsApp account and delete its key",
)
async def disconnect(
    account_id: UUID,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("org:manage")),
) -> WhatsAppAccountOut:
    tenant_id, _ = _owner(principal)
    account = await accounts.disconnect(session, account_id=account_id)
    await write_audit(
        session,
        action="whatsapp.disconnected",
        actor=principal,
        tenant_id=tenant_id,
        object_type="whatsapp_account",
        object_id=str(account_id),
        ip=client_request_ip(request),
    )
    return _account_out(account)


_TEMPLATE_COLUMNS: Final = (
    "id, account_id, name, language, category, body, variables, origin, purpose, status, "
    "rejection_code, category_changed_to, submitted_at, decided_at"
)


def _template_out(r: Any) -> WhatsAppTemplateOut:
    return WhatsAppTemplateOut(
        id=UUID(str(r[0])),
        account_id=UUID(str(r[1])),
        name=str(r[2]),
        language=str(r[3]),
        category=str(r[4]),
        body=str(r[5]),
        variables=[
            {"label": str(v.get("label", "")), "example": str(v.get("example", ""))}
            for v in (r[6] or [])
            if isinstance(v, dict)
        ],
        origin=str(r[7]),
        purpose=r[8],
        status=str(r[9]),
        rejection_code=r[10],
        category_changed_to=r[11],
        submitted_at=r[12],
        decided_at=r[13],
    )


@router.get(
    "/templates",
    response_model=list[WhatsAppTemplateOut],
    openapi_extra=permission_meta("org:read"),
    summary="Message templates in this account's connected WhatsApp accounts",
)
async def list_templates(
    session: Session, _: Principal = Depends(requires("org:read"))
) -> list[WhatsAppTemplateOut]:
    rows = (
        await session.execute(
            text(
                f"SELECT {_TEMPLATE_COLUMNS} FROM whatsapp_templates "
                "WHERE status <> 'deleted' ORDER BY origin, name, language LIMIT :n"
            ),
            {"n": templates.MAX_TEMPLATES_PER_ACCOUNT * accounts.MAX_ACCOUNTS_PER_TENANT},
        )
    ).all()
    return [_template_out(r) for r in rows]


@router.post(
    "/templates",
    response_model=WhatsAppTemplateOut,
    status_code=201,
    openapi_extra=permission_meta("org:manage"),
    summary="Write a message template and send it to Meta for review",
)
async def create_template(
    payload: WhatsAppTemplateIn,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("org:manage")),
) -> WhatsAppTemplateOut:
    tenant_id, _ = _owner(principal)
    account = await accounts.get_account(session, payload.account_id)
    if account.status != "connected":
        raise ProblemError.business_rule(
            "whatsapp_account_not_ready",
            "This WhatsApp account is not ready yet.",
            remediation="Finish connecting it first.",
        )
    examples = [v.example for v in payload.variables]
    templates.check_template(
        name=payload.name,
        language=payload.language,
        category=payload.category,
        body=payload.body,
        examples=examples,
    )
    count = (
        await session.execute(
            text("SELECT count(*) FROM whatsapp_templates WHERE account_id = :a"),
            {"a": account.id},
        )
    ).scalar_one()
    if count >= templates.MAX_TEMPLATES_PER_ACCOUNT:
        raise ProblemError.business_rule(
            "whatsapp_template_limit",
            f"An account may keep at most {templates.MAX_TEMPLATES_PER_ACCOUNT} templates here.",
        )
    template_id = await templates.insert_template(
        session,
        tenant_id=tenant_id,
        account_id=account.id,
        name=payload.name,
        language=payload.language,
        category=payload.category,
        body=payload.body.strip(),
        variables=[v.model_dump() for v in payload.variables],
        origin="client",
        purpose=None,
    )
    if template_id is None:
        raise ProblemError.conflict(
            "whatsapp_template_exists",
            "A template with this name and language already exists.",
            remediation="Choose another name.",
        )
    token = await accounts.account_token(session, tenant_id=tenant_id, account=account)
    await templates.submit(session, template_id=template_id, waba_id=account.waba_id, token=token)
    await write_audit(
        session,
        action="whatsapp.template_submitted",
        actor=principal,
        tenant_id=tenant_id,
        object_type="whatsapp_template",
        object_id=str(template_id),
        ip=client_request_ip(request),
        summary={"category": payload.category, "language": payload.language},
    )
    row = (
        await session.execute(
            text(f"SELECT {_TEMPLATE_COLUMNS} FROM whatsapp_templates WHERE id = :id"),
            {"id": template_id},
        )
    ).one()
    return _template_out(row)


__all__ = ["PAYMENT_METHOD_URL", "PRICING_URL", "extras_for", "router"]
