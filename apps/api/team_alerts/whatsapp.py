"""A team alert on WhatsApp, sent ONLY through the client's own connected WhatsApp account or
provider (founder, 27 Oct 2026; D-904), with a template of theirs.

The request is built by the same builders an in-call WhatsApp action uses
(`actions/whatsapp.build_*`) and put on the wire by `actions/execution.send_prepared`, so there
is one way a WhatsApp template leaves this platform. The recipient is the business's own team
number, verified by a code sent this way, so the caller-consent ledger (which is about the
client's customers) is not asked.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from uuid import UUID

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.actions import whatsapp as wa
from apps.api.actions.credentials import CredentialUnusableError, resolve_credential
from apps.api.actions.execution import REQUEST_TIMEOUT_S, send_prepared
from apps.api.actions.schema import PreparedRequest, WhatsAppConfig
from apps.api.integrations.egress_guard import EgressRefusedError, egress_client

#: The client's own WhatsApp connections a team alert may go through.
PROVIDER_KINDS: Final = ("aisensy", "meta_cloud", "interakt")
#: Providers whose template send names a language.
NEEDS_LANGUAGE: Final = frozenset({"meta_cloud", "interakt"})


@dataclass(frozen=True, slots=True)
class Account:
    id: UUID
    label: str
    provider: str


async def accounts(session: AsyncSession) -> list[Account]:
    """This client's own WhatsApp connections, newest first."""
    rows = (
        await session.execute(
            text(
                "SELECT id, label, kind FROM integration_credentials "
                "WHERE kind = ANY(:kinds) ORDER BY created_at DESC LIMIT 20"
            ),
            {"kinds": list(PROVIDER_KINDS)},
        )
    ).all()
    return [Account(UUID(str(r[0])), str(r[1]), str(r[2])) for r in rows]


async def provider_of(session: AsyncSession, credential_id: UUID) -> str | None:
    row = (
        await session.execute(
            text("SELECT kind FROM integration_credentials WHERE id = :id AND kind = ANY(:kinds)"),
            {"id": credential_id, "kinds": list(PROVIDER_KINDS)},
        )
    ).first()
    return str(row[0]) if row is not None else None


async def send(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    credential_id: UUID,
    number_e164: str,
    template: str,
    language: str | None,
    number_id: str | None,
    body_values: list[str],
) -> bool:
    """Send one template to the team number. False for any failure; nothing is logged with
    the number or the values (hard rule 6)."""
    try:
        cred = await resolve_credential(session, tenant_id=tenant_id, credential_id=credential_id)
    except CredentialUnusableError:
        return False
    if cred is None or cred.kind not in PROVIDER_KINDS:
        return False
    names = [f"v{i}" for i in range(len(body_values))]
    config = WhatsAppConfig(
        recipient_param="to",
        template=template,
        language=language,
        phone_number_id=number_id,
        body_params=names,
    )
    request: PreparedRequest
    if cred.kind == "aisensy":
        request = wa.build_aisensy(
            config, api_key=cred.secret, recipient_e164=number_e164, body_values=body_values
        )
    elif cred.kind == "meta_cloud":
        connected = cred.non_secret.get("phone_number_id")
        request = wa.build_meta_cloud(
            config,
            access_token=cred.secret,
            recipient_e164=number_e164,
            header_value=None,
            body_values=body_values,
            connected_number_id=connected if isinstance(connected, str) else None,
        )
    else:
        request = wa.build_interakt(
            config,
            api_key=cred.secret,
            recipient_e164=number_e164,
            header_value=None,
            body_values=body_values,
        )
    try:
        async with egress_client(timeout=REQUEST_TIMEOUT_S, follow_redirects=False) as client:
            response = await send_prepared(request, client=client)
    except (EgressRefusedError, TimeoutError, httpx.HTTPError):
        return False
    return 200 <= response.status_code < 300


__all__ = ["NEEDS_LANGUAGE", "PROVIDER_KINDS", "Account", "accounts", "provider_of", "send"]
