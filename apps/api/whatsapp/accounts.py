"""A client's connected WhatsApp accounts: read, finish set-up, disconnect (D-784).

All under the client's own `tenant_session` (RLS is the scoping). The business token is read
only through `actions/credentials.resolve_credential`, in memory, for one Graph call.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.actions import credentials as creds
from apps.api.core.errors import ProblemError
from apps.api.whatsapp import signup

#: A client with more numbers than this is not a voice-agent SMB.
MAX_ACCOUNTS_PER_TENANT: Final = 10

_COLUMNS: Final = (
    "id, credential_id, waba_id, phone_number_id, business_id, display_phone_number, "
    "verified_name, name_status, quality_rating, messaging_limit, onboarding, status, "
    "registered, webhooks_subscribed, setup_error, templates_seeded_at, last_event_at, "
    "account_alert, account_alert_at, last_send_error, last_send_error_at, connected_at, "
    "disconnected_at, created_at"
)


@dataclass(frozen=True, slots=True)
class Account:
    id: UUID
    credential_id: UUID | None
    waba_id: str
    phone_number_id: str | None
    business_id: str | None
    display_phone_number: str | None
    verified_name: str | None
    name_status: str | None
    quality_rating: str | None
    messaging_limit: str | None
    onboarding: str
    status: str
    registered: bool
    webhooks_subscribed: bool
    setup_error: str | None
    templates_seeded_at: datetime | None
    last_event_at: datetime | None
    account_alert: str | None
    account_alert_at: datetime | None
    last_send_error: str | None
    last_send_error_at: datetime | None
    connected_at: datetime | None
    disconnected_at: datetime | None
    created_at: datetime


def _account(row: Any) -> Account:
    return Account(
        id=UUID(str(row[0])),
        credential_id=UUID(str(row[1])) if row[1] is not None else None,
        waba_id=str(row[2]),
        phone_number_id=row[3],
        business_id=row[4],
        display_phone_number=row[5],
        verified_name=row[6],
        name_status=row[7],
        quality_rating=row[8],
        messaging_limit=row[9],
        onboarding=str(row[10]),
        status=str(row[11]),
        registered=bool(row[12]),
        webhooks_subscribed=bool(row[13]),
        setup_error=row[14],
        templates_seeded_at=row[15],
        last_event_at=row[16],
        account_alert=row[17],
        account_alert_at=row[18],
        last_send_error=row[19],
        last_send_error_at=row[20],
        connected_at=row[21],
        disconnected_at=row[22],
        created_at=row[23],
    )


async def list_accounts(
    session: AsyncSession, *, include_disconnected: bool = False
) -> list[Account]:
    rows = (
        await session.execute(
            text(
                f"SELECT {_COLUMNS} FROM whatsapp_accounts "
                "WHERE (:all OR status <> 'disconnected') ORDER BY created_at DESC LIMIT :n"
            ),
            {"all": include_disconnected, "n": MAX_ACCOUNTS_PER_TENANT * 3},
        )
    ).all()
    return [_account(r) for r in rows]


async def get_account(session: AsyncSession, account_id: UUID) -> Account:
    row = (
        await session.execute(
            text(f"SELECT {_COLUMNS} FROM whatsapp_accounts WHERE id = :id"), {"id": account_id}
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("WhatsApp account")
    return _account(row)


async def account_token(session: AsyncSession, *, tenant_id: UUID, account: Account) -> str:
    """The business token, in memory, for one call. Refused when the credential is gone."""
    if account.credential_id is None:
        raise _reconnect()
    try:
        resolved = await creds.resolve_credential(
            session, tenant_id=tenant_id, credential_id=account.credential_id
        )
    except creds.CredentialUnusableError as exc:
        raise _reconnect() from exc
    if resolved is None:
        raise _reconnect()
    return resolved.secret


def _reconnect() -> ProblemError:
    return ProblemError.business_rule(
        "whatsapp_reconnect_needed",
        "Calevate can no longer reach this WhatsApp account.",
        remediation="Disconnect it here, then press Connect WhatsApp again.",
    )


async def finish_setup(
    session: AsyncSession, *, tenant_id: UUID, account_id: UUID
) -> signup.ConnectOutcome:
    """Re-run the set-up steps that did not finish. A step already done is not repeated."""
    account = await get_account(session, account_id)
    if account.status == "disconnected":
        raise ProblemError.business_rule(
            "whatsapp_account_disconnected", "This WhatsApp account is disconnected."
        )
    token = await account_token(session, tenant_id=tenant_id, account=account)
    outcome = await signup.run_setup_steps(
        session,
        account_id=account.id,
        token=token,
        waba_id=account.waba_id,
        phone_number_id=account.phone_number_id,
        onboarding=account.onboarding,
        registered=account.registered,
        subscribed=account.webhooks_subscribed,
    )
    if outcome.status == "connected" and account.templates_seeded_at is None:
        await signup.queue_templates(session, account_id=account.id, tenant_id=tenant_id)
    return outcome


async def disconnect(session: AsyncSession, *, account_id: UUID) -> Account:
    """Stop using the account: the token is deleted here, the row kept as history.

    Meta keeps our app's access until the owner removes it in Meta Business settings
    (embedded-signup/app-only-install.md describes the owner's side); the screen says so.
    """
    account = await get_account(session, account_id)
    await session.execute(
        text(
            "UPDATE whatsapp_accounts SET status = 'disconnected', disconnected_at = now(), "
            "credential_id = NULL, updated_at = now() WHERE id = :id AND status <> 'disconnected'"
        ),
        {"id": account_id},
    )
    if account.credential_id is not None:
        await creds.delete_credential(session, credential_id=account.credential_id)
    return await get_account(session, account_id)


__all__ = [
    "MAX_ACCOUNTS_PER_TENANT",
    "Account",
    "account_token",
    "disconnect",
    "finish_setup",
    "get_account",
    "list_accounts",
]
