"""Saved, reusable, envelope-encrypted TENANT credentials for integrations (DATA-MODEL §11).

The plaintext of an integration secret exists in exactly two places: the `secret` argument
to `create_credential`/`rotate_credential`, and the return of `resolve_secret`. Hard rule 6
governs both — never logged, never in a response body — and the shapes here make obeying it
the default: `CredentialRecord` has NO value field, and `resolve_secret` is reachable only
from the execution layer, never from a route.

WHY IN-ROW ENVELOPE AND NOT THE PLATFORM SECRET STORE. `ops/secret_service.py` keys on a
fixed enum of `Settings` field names — the FOUNDER's platform-wide vendor keys. A tenant's
own AiSensy key or Meta token is a different animal: there are many, they are per-tenant,
and a client rotates them. So they live in their own tenant-scoped table, sealed with
`core/envelope.seal` under a per-(tenant, credential) AAD context so one tenant's ciphertext
cannot be swapped into another's row — the same primitive, a different namespace, exactly as
`ops/secret_service.secret_context` says the `tenant_secret:` prefix is reserved for.

ROTATION IS AN UPDATE UNDER CAS, not an append. The founder's requirement is
"rotate-updates-all": a tool references a credential by id, so re-sealing the row in place is
what makes every tool that points at it pick up the new value with no fan-out. `version` is
the optimistic-concurrency guard — a rotate writes `WHERE version = :seen`, so two concurrent
rotations cannot both land (BACKEND-PATTERNS §5). This is the one credential surface that is
NOT append-only, and the trade is deliberate: append-only versioning (as `platform_secrets`
does) would need every tool to resolve "latest version", which is a second lookup on the
in-call path for no benefit a client asked for.

⚠ KEK ROTATION: these rows are re-sealed only when a credential is next written, so a
credential written under a KEK that is later RETIRED stays readable (`unseal` tries the whole
ring) until that KEK is REMOVED. `ops/secret_service.rewrap_all` re-wraps `platform_secrets`
but not this table; extending the rewrap job to tenant credentials is the follow-up that
closes the window, and it needs the KEK-rotation runbook (PLATFORM-CONFIG §13) to say so.
Stated here rather than discovered during a rotation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.actions.models import INTEGRATION_KINDS
from apps.api.core.envelope import Envelope, last_four, seal, unseal
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of

log = get_logger(__name__)


def credential_context(tenant_id: UUID, credential_id: UUID) -> str:
    """The AAD one integration credential is sealed under. ONE definition.

    Binds the ciphertext to its tenant AND its row, so neither a cross-tenant move nor an
    in-tenant swap between two credentials verifies. The `integration_cred:` prefix keeps
    this namespace clear of `platform_secret:` and `tenant_secret:` (see
    `ops/secret_service.secret_context`).
    """
    return f"integration_cred:{tenant_id}:{credential_id}"


@dataclass(frozen=True, slots=True)
class CredentialRecord:
    """What a console may know about a saved credential. NO value, NO ciphertext."""

    id: UUID
    kind: str
    label: str
    last_four: str
    version: int
    non_secret: dict[str, object] | None
    created_at: str
    updated_at: str


def _refuse_bad_kind(kind: str) -> None:
    if kind not in INTEGRATION_KINDS:
        raise ProblemError.business_rule(
            "integration_kind_unknown",
            f"{kind!r} is not an integration Calevate can hold a credential for.",
            remediation=f"Use one of: {', '.join(INTEGRATION_KINDS)}.",
        )


def _refuse_empty(secret: str) -> None:
    if not secret.strip():
        raise ProblemError(
            kind="validation",
            code="integration_secret_empty",
            title="A credential cannot be empty",
            detail="An empty value would save nothing while looking like a credential.",
            remediation="Paste the API key or token from your provider's dashboard.",
        )


def _record(r: Any) -> CredentialRecord:
    """A DB Row → `CredentialRecord`. Positional access matches `_COLUMNS` order."""
    return CredentialRecord(
        id=r[0],
        kind=str(r[1]),
        label=str(r[2]),
        last_four=str(r[3]),
        version=int(r[4]),
        non_secret=r[5],
        created_at=r[6].isoformat(),
        updated_at=r[7].isoformat(),
    )


_COLUMNS = "id, kind, label, last_four, version, non_secret, created_at, updated_at"


async def list_credentials(session: AsyncSession) -> list[CredentialRecord]:
    """Every saved credential for the session's tenant. RLS is the scoping (hard rule 1)."""
    rows = (
        await session.execute(
            text(f"SELECT {_COLUMNS} FROM integration_credentials ORDER BY created_at DESC")
        )
    ).all()
    return [_record(r) for r in rows]


async def create_credential(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    kind: str,
    label: str,
    secret: str,
    non_secret: dict[str, object] | None = None,
) -> CredentialRecord:
    """Seal a new credential and INSERT it. Runs under the session's RLS context.

    `tenant_id` is written from the principal, but the INSERT is subject to RLS, so a
    tenant the session does not hold is refused by the policy, not by this line.
    """
    _refuse_bad_kind(kind)
    _refuse_empty(secret)
    if not label.strip():
        raise ProblemError(
            kind="validation",
            code="integration_label_empty",
            title="Give the credential a name",
            detail="A blank name makes it impossible to pick this credential on a tool.",
            remediation="Name it for where it comes from, e.g. 'Main AiSensy key'.",
        )
    cred_id = uuid7()
    env = seal(secret, context=credential_context(tenant_id, cred_id))
    row = (
        await session.execute(
            text(
                "INSERT INTO integration_credentials (id, tenant_id, kind, label, ciphertext, "
                "nonce, dek_wrapped, dek_nonce, kek_version, last_four, version, non_secret, "
                "created_at, updated_at) VALUES (:id, :tid, :kind, :label, :ct, :n, :dw, :dn, "
                ":kek, :l4, 1, CAST(:ns AS jsonb), now(), now()) "
                f"RETURNING {_COLUMNS}"
            ),
            {
                "id": cred_id,
                "tid": tenant_id,
                "kind": kind,
                "label": label.strip(),
                "ct": env.ciphertext,
                "n": env.nonce,
                "dw": env.dek_wrapped,
                "dn": env.dek_nonce,
                "kek": env.kek_id,
                "l4": last_four(secret),
                "ns": json.dumps(non_secret) if non_secret else None,
            },
        )
    ).one()
    # Ids and a four-char fragment only (hard rule 6).
    log.info(
        "integration_credential_created",
        extra={"tenant_id": str(tenant_id), "credential_id": str(cred_id), "kind": kind},
    )
    return _record(row)


async def rotate_credential(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    credential_id: UUID,
    secret: str,
    expected_version: int,
) -> CredentialRecord:
    """Re-seal a credential in place (rotate-updates-all), CAS on `version`.

    The row is re-sealed under the same context (which is fixed by its id), so every tool
    that references it uses the new value on its next call — no fan-out. A stale
    `expected_version` is a conflict: someone rotated it since the client loaded the screen,
    and silently overwriting their change is the read-then-write race CAS exists to refuse.
    """
    _refuse_empty(secret)
    env = seal(secret, context=credential_context(tenant_id, credential_id))
    result = await session.execute(
        text(
            "UPDATE integration_credentials SET ciphertext = :ct, nonce = :n, "
            "dek_wrapped = :dw, dek_nonce = :dn, kek_version = :kek, last_four = :l4, "
            "version = version + 1, updated_at = now() "
            f"WHERE id = :id AND version = :seen RETURNING {_COLUMNS}"
        ),
        {
            "ct": env.ciphertext,
            "n": env.nonce,
            "dw": env.dek_wrapped,
            "dn": env.dek_nonce,
            "kek": env.kek_id,
            "l4": last_four(secret),
            "id": credential_id,
            "seen": expected_version,
        },
    )
    row = result.first()
    if row is None:
        # Either no such credential (RLS-invisible ids included, hard rule 1) or the
        # version moved under us. Distinguish so the message is actionable.
        exists = (
            await session.execute(
                text("SELECT version FROM integration_credentials WHERE id = :id"),
                {"id": credential_id},
            )
        ).first()
        if exists is None:
            raise ProblemError.not_found("Credential")
        raise ProblemError.conflict(
            "integration_credential_stale",
            "This credential was changed since you loaded the screen.",
            remediation="Reload and rotate again.",
        )
    log.info(
        "integration_credential_rotated",
        extra={"tenant_id": str(tenant_id), "credential_id": str(credential_id)},
    )
    return _record(row)


async def delete_credential(session: AsyncSession, *, credential_id: UUID) -> bool:
    """Delete a saved credential. True when a row was removed.

    Tools referencing it are SET NULL by the FK, so they survive as visibly broken
    (`no_credential` at execution) rather than blocking the delete — the client can see
    which tools need a new credential attached.
    """
    result = await session.execute(
        text("DELETE FROM integration_credentials WHERE id = :id"), {"id": credential_id}
    )
    return rowcount_of(result) == 1


async def resolve_secret(
    session: AsyncSession, *, tenant_id: UUID, credential_id: UUID
) -> str | None:
    """The plaintext of one credential, for the EXECUTION layer only. Never a route.

    Returns None when the row is absent (including RLS-invisible), which the caller turns
    into a `no_credential` refusal. The returned value is a hard-rule-6 string: in memory,
    for this call, never logged.
    """
    row = (
        await session.execute(
            text(
                "SELECT ciphertext, nonce, dek_wrapped, dek_nonce, kek_version "
                "FROM integration_credentials WHERE id = :id"
            ),
            {"id": credential_id},
        )
    ).first()
    if row is None:
        return None
    env = Envelope(
        ciphertext=bytes(row[0]),
        nonce=bytes(row[1]),
        dek_wrapped=bytes(row[2]),
        dek_nonce=bytes(row[3]),
        kek_id=int(row[4]),
    )
    return unseal(env, context=credential_context(tenant_id, credential_id))


__all__ = [
    "CredentialRecord",
    "create_credential",
    "credential_context",
    "delete_credential",
    "list_credentials",
    "resolve_secret",
    "rotate_credential",
]
