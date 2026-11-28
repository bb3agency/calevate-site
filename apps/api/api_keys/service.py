"""Making, listing, renewing and revoking tenant API keys, and resolving a presented one.

A key carries a SUBSET of its creator's permissions, chosen from `GRANTABLE_SCOPES`, and
that subset is intersected again with the creator's CURRENT role on every request
(`resolve`). So a key can never do more than the person who made it can do today: a
demoted creator narrows every key they made, and a removed or deactivated one stops them.

`calls:read_raw` is not grantable and cannot become so by a role change: raw transcripts
and recordings stay a human act behind a role check and an audit row (hard rule 5).
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.api_keys import tokens
from apps.api.api_keys.models import MAX_AGENTS, MAX_CIDRS
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import ROLE_PERMISSIONS, Permission
from apps.api.db.base import uuid7
from apps.api.db.session import api_key_session, tenant_session

#: What a key may be given. Every permission the public surface checks, and nothing that
#: opens billing, members, settings or raw call content.
GRANTABLE_SCOPES: Final[frozenset[Permission]] = frozenset(
    {
        "org:read",
        "agents:read",
        "calls:read",
        "leads:read",
        "leads:write",
        "leads:dispatch",
        "wallet:read",
    }
)
NEVER_GRANTABLE: Final[frozenset[str]] = frozenset({"calls:read_raw"})
#: Keys expire unless renewed; the console shows the date and a renew button from
#: `RENEW_FROM` before it.
LIFETIME: Final = timedelta(days=90)
RENEW_FROM: Final = timedelta(days=14)
#: Live keys one account may hold, so a leaked creator session cannot mint without bound.
MAX_LIVE_KEYS: Final = 25
#: Keys the console lists, newest first; revoked and expired ones included, so a person
#: can see what stopped working.
LIST_LIMIT: Final = 100


@dataclass(frozen=True, slots=True)
class ResolvedKey:
    """A presented key that is live, with its creator's role read now."""

    id: UUID
    tenant_id: UUID
    created_by: UUID
    role: str
    scopes: frozenset[str]
    agent_ids: frozenset[UUID] | None
    ip_cidrs: tuple[str, ...] | None
    rate_per_minute: int | None
    api_version: str


@dataclass(frozen=True, slots=True)
class KeyRow:
    id: UUID
    name: str
    display_prefix: str
    scopes: list[str]
    agent_ids: list[UUID] | None
    ip_cidrs: list[str] | None
    rate_per_minute: int | None
    api_version: str
    created_by: UUID
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


def _invalid(code: str, detail: str, remediation: str) -> ProblemError:
    return ProblemError(
        kind="auth",
        code=code,
        title="This API key cannot be used",
        detail=detail,
        remediation=remediation,
        headers={"WWW-Authenticate": 'Bearer realm="calevate-api"'},
    )


def key_invalid() -> ProblemError:
    """One answer for a key that is malformed or not ours: which of the two is not the
    caller's business, and saying would help someone guessing."""
    return _invalid(
        "api_key_invalid",
        "The key in the Authorization header is not a Calevate API key.",
        "Send `Authorization: Bearer cvk_live_…` with a key from Integrations → Developers.",
    )


def checked_scopes(requested: list[str], *, creator_role: str) -> list[str]:
    """`requested`, refused if any of it is not grantable or not the creator's own."""
    held = ROLE_PERMISSIONS.get(creator_role, frozenset())
    bad = sorted(s for s in set(requested) if s not in GRANTABLE_SCOPES or s not in held)
    if not requested or bad:
        raise ProblemError(
            kind="validation",
            code="api_key_scope_not_grantable",
            title="That permission cannot go on a key",
            detail=(
                "A key can carry only permissions you hold yourself, from the list this "
                "screen offers." + (f" Not allowed: {', '.join(bad)}." if bad else "")
            ),
            fields=[{"field": "scopes", "rule": "subset", "message": "not grantable"}],
        )
    return sorted(set(requested))


def checked_cidrs(raw: list[str] | None) -> list[str] | None:
    """Each range normalised (`203.0.113.7` → `203.0.113.7/32`), or a validation problem."""
    if not raw:
        return None
    if len(raw) > MAX_CIDRS:
        raise _bad_field("ip_cidrs", f"At most {MAX_CIDRS} address ranges.")
    out: list[str] = []
    for value in raw:
        try:
            out.append(str(ipaddress.ip_network(value.strip(), strict=False)))
        except ValueError:
            raise _bad_field("ip_cidrs", "Each entry must be an address or a range.") from None
    return sorted(set(out))


def _bad_field(field: str, detail: str) -> ProblemError:
    return ProblemError(
        kind="validation",
        code="api_key_bad_field",
        title="Check the key's settings",
        detail=detail,
        fields=[{"field": field, "rule": "format", "message": detail}],
    )


async def _agents_visible(session: AsyncSession, agent_ids: list[UUID]) -> None:
    found = (
        await session.execute(
            text("SELECT count(*) FROM agents WHERE id = ANY(:ids) AND deleted_at IS NULL"),
            {"ids": agent_ids},
        )
    ).scalar_one()
    if int(found) != len(agent_ids):
        raise _bad_field("agent_ids", "One of those agents is not in this account.")


async def create_key(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    created_by: UUID,
    creator_role: str,
    name: str,
    scopes: list[str],
    agent_ids: list[UUID] | None,
    ip_cidrs: list[str] | None,
    rate_per_minute: int | None,
    api_version: str,
    now: datetime | None = None,
) -> tuple[KeyRow, str]:
    """The new key's row and its secret. The secret exists only in this return value."""
    granted = checked_scopes(scopes, creator_role=creator_role)
    agents = sorted(set(agent_ids)) if agent_ids else None
    if agents is not None:
        if len(agents) > MAX_AGENTS:
            raise _bad_field("agent_ids", f"At most {MAX_AGENTS} agents.")
        await _agents_visible(session, agents)
    cidrs = checked_cidrs(ip_cidrs)
    live = (
        await session.execute(
            text("SELECT count(*) FROM api_keys WHERE revoked_at IS NULL AND expires_at > now()")
        )
    ).scalar_one()
    if int(live) >= MAX_LIVE_KEYS:
        raise ProblemError.business_rule(
            "api_key_limit",
            f"This account already has {MAX_LIVE_KEYS} working keys.",
            remediation="Revoke a key you no longer use, then make the new one.",
        )
    at = now or datetime.now(UTC)
    secret = tokens.mint()
    key_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO api_keys (id, tenant_id, created_by, name, display_prefix, "
            "secret_sha256, scopes, agent_ids, ip_cidrs, rate_per_minute, api_version, "
            "expires_at, created_at, updated_at) VALUES (:id, :tid, :uid, :name, :prefix, "
            ":digest, :scopes, :agents, CAST(:cidrs AS cidr[]), :rate, :version, :expires, "
            ":at, :at)"
        ),
        {
            "id": key_id,
            "tid": tenant_id,
            "uid": created_by,
            "name": name.strip(),
            "prefix": tokens.display(secret),
            "digest": tokens.digest(secret),
            "scopes": granted,
            "agents": agents,
            "cidrs": cidrs,
            "rate": rate_per_minute,
            "version": api_version,
            "expires": at + LIFETIME,
            "at": at,
        },
    )
    row = await get_key(session, key_id)
    assert row is not None
    return row, secret


_SELECT: Final = (
    "SELECT id, name, display_prefix, scopes, agent_ids, ip_cidrs::text[], rate_per_minute, "
    "api_version, created_by, created_at, expires_at, last_used_at, revoked_at FROM api_keys"
)


def _row(v: Row[Any]) -> KeyRow:
    return KeyRow(
        id=v[0],
        name=v[1],
        display_prefix=v[2],
        scopes=list(v[3]),
        agent_ids=list(v[4]) if v[4] is not None else None,
        ip_cidrs=list(v[5]) if v[5] is not None else None,
        rate_per_minute=v[6],
        api_version=v[7],
        created_by=v[8],
        created_at=v[9],
        expires_at=v[10],
        last_used_at=v[11],
        revoked_at=v[12],
    )


async def get_key(session: AsyncSession, key_id: UUID) -> KeyRow | None:
    row = (await session.execute(text(f"{_SELECT} WHERE id = :id"), {"id": key_id})).first()
    return _row(row) if row is not None else None


async def list_keys(session: AsyncSession) -> list[KeyRow]:
    rows = (
        await session.execute(
            text(f"{_SELECT} ORDER BY created_at DESC, id DESC LIMIT :n"), {"n": LIST_LIMIT}
        )
    ).all()
    return [_row(r) for r in rows]


async def revoke_key(session: AsyncSession, *, key_id: UUID, revoked_by: UUID | None) -> KeyRow:
    """Revoke at once. A second revoke answers the same row rather than an error."""
    await session.execute(
        text(
            "UPDATE api_keys SET revoked_at = now(), revoked_by = :by, updated_at = now() "
            "WHERE id = :id AND revoked_at IS NULL"
        ),
        {"id": key_id, "by": revoked_by},
    )
    row = await get_key(session, key_id)
    if row is None:
        raise ProblemError.not_found("API key")
    return row


async def renew_key(session: AsyncSession, *, key_id: UUID, now: datetime | None = None) -> KeyRow:
    """Push a live key's expiry to `LIFETIME` from now. Refused once revoked or expired:
    a key that stopped is replaced, never brought back."""
    at = now or datetime.now(UTC)
    row = await get_key(session, key_id)
    if row is None:
        raise ProblemError.not_found("API key")
    if row.revoked_at is not None or row.expires_at <= at:
        raise ProblemError.business_rule(
            "api_key_not_renewable",
            "This key has stopped working, so it cannot be renewed.",
            remediation="Make a new key and put it where the old one was.",
        )
    await session.execute(
        text("UPDATE api_keys SET expires_at = :exp, updated_at = now() WHERE id = :id"),
        {"id": key_id, "exp": at + LIFETIME},
    )
    renewed = await get_key(session, key_id)
    assert renewed is not None
    return renewed


_LOOKUP: Final = (
    "SELECT id, tenant_id, created_by, scopes, agent_ids, ip_cidrs::text[], rate_per_minute, "
    "api_version, expires_at, revoked_at FROM api_keys WHERE secret_sha256 = :digest"
)
# The creator's role in the key's own account, read now. A deactivated person, a closed
# account or a removed membership is no row, and no row stops the key.
_CREATOR_ROLE: Final = (
    "SELECT m.role FROM memberships m JOIN users u ON u.id = m.user_id "
    "JOIN organizations o ON o.id = m.tenant_id WHERE m.user_id = :uid "
    "AND m.tenant_id = :tid AND u.deactivated_at IS NULL AND o.deleted_at IS NULL "
    "AND o.status <> 'churned'"
)


async def resolve(token: str, *, now: datetime | None = None) -> ResolvedKey:
    """The live key `token` names, or the 401 that says why it is not."""
    if not tokens.well_formed(token):
        raise key_invalid()
    async with api_key_session(tokens.digest(token)) as session:
        row = (await session.execute(text(_LOOKUP), {"digest": tokens.digest(token)})).first()
    if row is None:
        raise key_invalid()
    at = now or datetime.now(UTC)
    if row[9] is not None:
        raise _invalid(
            "api_key_revoked",
            "This key was revoked.",
            "Make a new key in Integrations → Developers.",
        )
    if row[8] <= at:
        raise _invalid(
            "api_key_expired",
            "This key passed its expiry date.",
            "Make a new key in Integrations → Developers, or renew keys before they expire.",
        )
    tenant_id = UUID(str(row[1]))
    async with tenant_session(tenant_id) as session:
        role = (
            await session.execute(text(_CREATOR_ROLE), {"uid": row[2], "tid": tenant_id})
        ).scalar_one_or_none()
    if role is None:
        raise _invalid(
            "api_key_creator_gone",
            "The person who made this key is no longer in this account.",
            "Ask someone in the account to make a new key.",
        )
    held = ROLE_PERMISSIONS.get(str(role), frozenset())
    return ResolvedKey(
        id=UUID(str(row[0])),
        tenant_id=tenant_id,
        created_by=UUID(str(row[2])),
        role=str(role),
        scopes=frozenset(s for s in row[3] if s in held and s not in NEVER_GRANTABLE),
        agent_ids=frozenset(UUID(str(a)) for a in row[4]) if row[4] is not None else None,
        ip_cidrs=tuple(row[5]) if row[5] is not None else None,
        rate_per_minute=row[6],
        api_version=str(row[7]),
    )


def address_allowed(cidrs: tuple[str, ...] | None, address: str | None) -> bool:
    """True when the key has no address binding, or the caller is inside one of its ranges.
    An address we cannot establish is outside every range."""
    if cidrs is None:
        return True
    if address is None:
        return False
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(ip in ipaddress.ip_network(c, strict=False) for c in cidrs)


async def touch_last_used(tenant_id: UUID, key_id: UUID) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE api_keys SET last_used_at = now() WHERE id = :id"), {"id": key_id}
        )


__all__ = [
    "GRANTABLE_SCOPES",
    "LIFETIME",
    "LIST_LIMIT",
    "MAX_LIVE_KEYS",
    "NEVER_GRANTABLE",
    "RENEW_FROM",
    "KeyRow",
    "ResolvedKey",
    "address_allowed",
    "checked_cidrs",
    "checked_scopes",
    "create_key",
    "get_key",
    "key_invalid",
    "list_keys",
    "renew_key",
    "resolve",
    "revoke_key",
    "touch_last_used",
]
