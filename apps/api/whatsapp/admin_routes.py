"""The operator's view of clients' WhatsApp (D-784): Meta's weekly onboarding count against
the limit, whether Calevate's Meta app is configured, and each client's accounts, templates
and webhook health.

The directory is an `admin_session()`; each client is then read under its OWN tenant session
(`admin/onboarding.py`'s pattern), so no cross-tenant view of a tenant table is opened. The
candidate list is every live client; one with no account is left out.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.rbac import permission_meta
from apps.api.core.settings import get_settings
from apps.api.db.session import admin_session, tenant_session
from apps.api.whatsapp import accounts, signup

router = APIRouter(prefix="/v1/admin/whatsapp", tags=["whatsapp"])
Operator = Annotated[Principal, Depends(requires("admin:tenants", realm="admin"))]

#: Clients shown, most recently heard from first when more have WhatsApp. Far above Meta's
#: 200-a-week ceiling for any span an operator reads here. It bounds the answer, never the
#: walk: capping the directory instead hid every WhatsApp client whose name sorted after the
#: first 200 accounts, with or without WhatsApp.
MAX_CLIENTS: Final = 200


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AdminWhatsAppAccountOut(Strict):
    id: UUID
    status: str
    onboarding: str
    display_phone_number: str | None
    verified_name: str | None
    name_status: str | None
    quality_rating: str | None
    messaging_limit: str | None
    setup_error: str | None
    account_alert: str | None
    last_send_error: str | None
    last_event_at: datetime | None
    connected_at: datetime | None
    templates_approved: int
    templates_pending: int
    templates_rejected: int


class AdminWhatsAppClientOut(Strict):
    tenant_id: UUID
    name: str
    slug: str
    accounts: list[AdminWhatsAppAccountOut]


class AdminWhatsAppOut(Strict):
    configured: bool
    app_secret_set: bool
    verify_token_set: bool
    coexistence: bool
    week_count: int
    weekly_limit: int
    #: When Meta last delivered anything for any client's account.
    last_event_at: datetime | None
    callback_path: str
    clients: list[AdminWhatsAppClientOut]


@router.get(
    "",
    response_model=AdminWhatsAppOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Clients' WhatsApp: weekly onboarding count, accounts, templates and webhook health",
)
async def whatsapp_admin(_: Operator) -> AdminWhatsAppOut:
    s = get_settings()
    async with admin_session() as directory:
        setup = await signup.signup_setup(directory)
        candidates = (
            await directory.execute(
                text(
                    "SELECT id, name, slug FROM organizations WHERE deleted_at IS NULL "
                    "ORDER BY name"
                )
            )
        ).all()
    clients: list[AdminWhatsAppClientOut] = []
    latest: datetime | None = None
    for org in candidates:
        tenant_id = UUID(str(org[0]))
        async with tenant_session(tenant_id) as scoped:
            rows = await accounts.list_accounts(scoped, include_disconnected=True)
            counts = (
                await scoped.execute(
                    text(
                        "SELECT account_id, status, count(*) FROM whatsapp_templates "
                        "GROUP BY account_id, status"
                    )
                )
            ).all()
        by_account: dict[str, dict[str, int]] = {}
        for account_id, status, n in counts:
            by_account.setdefault(str(account_id), {})[str(status)] = int(n)
        out: list[AdminWhatsAppAccountOut] = []
        for a in rows:
            tally = by_account.get(str(a.id), {})
            if a.last_event_at is not None and (latest is None or a.last_event_at > latest):
                latest = a.last_event_at
            out.append(
                AdminWhatsAppAccountOut(
                    id=a.id,
                    status=a.status,
                    onboarding=a.onboarding,
                    display_phone_number=a.display_phone_number,
                    verified_name=a.verified_name,
                    name_status=a.name_status,
                    quality_rating=a.quality_rating,
                    messaging_limit=a.messaging_limit,
                    setup_error=a.setup_error,
                    account_alert=a.account_alert,
                    last_send_error=a.last_send_error,
                    last_event_at=a.last_event_at,
                    connected_at=a.connected_at,
                    templates_approved=tally.get("approved", 0),
                    templates_pending=tally.get("pending", 0) + tally.get("draft", 0),
                    templates_rejected=sum(
                        tally.get(k, 0) for k in ("rejected", "paused", "disabled", "submit_failed")
                    ),
                )
            )
        if not out:
            continue
        clients.append(
            AdminWhatsAppClientOut(
                tenant_id=tenant_id, name=str(org[1]), slug=str(org[2]), accounts=out
            )
        )
    if len(clients) > MAX_CLIENTS:
        never = datetime.min.replace(tzinfo=UTC)

        def heard(client: AdminWhatsAppClientOut) -> datetime:
            return max((a.last_event_at or never for a in client.accounts), default=never)

        kept = {c.tenant_id for c in sorted(clients, key=heard, reverse=True)[:MAX_CLIENTS]}
        # Still in name order, as the screen lists them.
        clients = [c for c in clients if c.tenant_id in kept]
    return AdminWhatsAppOut(
        configured=setup.reason != "not_configured",
        app_secret_set=bool(s.meta_app_secret),
        verify_token_set=bool(s.whatsapp_webhook_verify_token),
        coexistence=s.whatsapp_coexistence_enabled,
        week_count=setup.week_count,
        weekly_limit=setup.weekly_limit,
        last_event_at=latest,
        callback_path="/hooks/v1/meta/whatsapp",
        clients=clients,
    )


__all__ = ["router"]
