"""Audit log writer with the tamper-evident hash chain (BACKEND-PATTERNS §7).

Each entry's hash = HMAC(secret, previous_hash + canonical(entry)). The chain head is
cached in Redis behind a short lock so concurrent writers cannot interleave and break
the chain; the durable head is always the last row in `audit_log`, so losing Redis
costs a query, not the chain.

Why it earns its keep: DPDP disputes and support escalations both turn into "prove
nobody edited the record". Detecting tampering costs one HMAC per write.

`audit_log` is INSERT-only (hard rule 4) and NOT tenant-RLS'd — the admin realm reads
it across tenants, and reading it is itself audited.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.context import Principal
from apps.api.core.logging import get_logger, redact_mapping
from apps.api.core.redis import get_redis
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7

log = get_logger(__name__)

_HEAD_KEY = "calevate:audit:head"
_LOCK_KEY = "calevate:audit:lock"
_LOCK_TTL_MS = 3000
GENESIS = "0" * 64


def _chain_secret() -> bytes:
    """Derived from a real secret in prod. Local dev gets a constant so the chain is
    still verifiable end-to-end without a secrets manager."""
    settings = get_settings()
    material = settings.audit_chain_secret or f"local-dev:{settings.app_env}"
    return material.encode()


def _entry_hash(prev_hash: str, entry: dict[str, Any]) -> str:
    canonical = json.dumps(entry, sort_keys=True, separators=(",", ":"), default=str)
    return hmac.new(_chain_secret(), (prev_hash + canonical).encode(), hashlib.sha256).hexdigest()


async def _current_head(session: AsyncSession) -> str:
    try:
        cached = await get_redis().get(_HEAD_KEY)
        if isinstance(cached, str) and len(cached) == 64:
            return cached
    except Exception:
        log.warning("audit_head_cache_unavailable")
    row = (
        await session.execute(
            text("SELECT entry_hash FROM audit_log ORDER BY at DESC, id DESC LIMIT 1")
        )
    ).first()
    return str(row[0]) if row and row[0] else GENESIS


async def write_audit(
    session: AsyncSession,
    *,
    action: str,
    actor: Principal | None = None,
    actor_type: str | None = None,
    tenant_id: UUID | None = None,
    object_type: str | None = None,
    object_id: str | None = None,
    ip: str | None = None,
    summary: dict[str, Any] | None = None,
) -> None:
    """Append one entry IN THE CALLER'S TRANSACTION.

    That is deliberate: the audit row and the thing it describes commit together, so
    there is no window where a raw-transcript read happened but was not recorded.
    """
    resolved_actor_type = actor_type or (
        "admin" if actor and actor.is_admin else "user" if actor else "system"
    )
    entry_id = uuid7()
    payload: dict[str, Any] = {
        "id": str(entry_id),
        "actor_type": resolved_actor_type,
        "actor_id": str(actor.user_id) if actor and actor.user_id else None,
        "tenant_id": str(tenant_id) if tenant_id else None,
        "action": action,
        "object_type": object_type,
        "object_id": object_id,
    }
    if summary:
        # Depth-capped, length-capped, key-pattern-redacted before it leaves the
        # process (§7). It is NOT part of the hashed payload: `audit_log` has no
        # summary column, and hashing a field the row does not carry would make the
        # chain unverifiable. The summary goes to the log stream (the JSONL artifact
        # §7 describes), keyed by the same entry id.
        log.info("audit", extra={"entry_id": str(entry_id), **redact_mapping(summary)})

    redis = get_redis()
    lock_token = entry_id.hex
    have_lock = False
    try:
        have_lock = bool(await redis.set(_LOCK_KEY, lock_token, nx=True, px=_LOCK_TTL_MS))
    except Exception:
        log.warning("audit_lock_unavailable")

    try:
        prev_hash = await _current_head(session)
        entry_hash = _entry_hash(prev_hash, payload)
        await session.execute(
            text(
                "INSERT INTO audit_log (id, actor_type, actor_id, tenant_id, action, "
                "object_type, object_id, ip, at, prev_hash, entry_hash, created_at) "
                "VALUES (:id, :actor_type, :actor_id, :tenant_id, :action, :object_type, "
                ":object_id, :ip, now(), :prev_hash, :entry_hash, now())"
            ),
            {
                "id": entry_id,
                "actor_type": resolved_actor_type,
                "actor_id": actor.user_id if actor else None,
                "tenant_id": tenant_id,
                "action": action,
                "object_type": object_type,
                "object_id": object_id,
                "ip": ip,
                "prev_hash": prev_hash,
                "entry_hash": entry_hash,
            },
        )
        try:
            await redis.set(_HEAD_KEY, entry_hash)
        except Exception:
            log.warning("audit_head_cache_write_failed")
    finally:
        if have_lock:
            try:
                # Compare-and-delete: never release a lock another writer now holds.
                await redis.eval(  # type: ignore[misc]
                    "if redis.call('get', KEYS[1]) == ARGV[1] then "
                    "return redis.call('del', KEYS[1]) else return 0 end",
                    1,
                    _LOCK_KEY,
                    lock_token,
                )
            except Exception:
                log.warning("audit_lock_release_failed")


async def verify_chain(session: AsyncSession, *, limit: int = 1000) -> tuple[bool, str | None]:
    """Walk the chain oldest-first and recompute. Returns (ok, first_bad_entry_id).

    Used by the compliance drill (OPERATIONS §6) and available to support when a
    client disputes a record.
    """
    rows = (
        await session.execute(
            text(
                "SELECT id, actor_type, actor_id, tenant_id, action, object_type, object_id, "
                "prev_hash, entry_hash FROM audit_log ORDER BY at ASC, id ASC LIMIT :limit"
            ),
            {"limit": limit},
        )
    ).all()
    expected_prev = GENESIS
    for row in rows:
        payload = {
            "id": str(row[0]),
            "actor_type": row[1],
            "actor_id": str(row[2]) if row[2] else None,
            "tenant_id": str(row[3]) if row[3] else None,
            "action": row[4],
            "object_type": row[5],
            "object_id": row[6],
        }
        # Two checks: the link (deletion/reordering) and the content (field edits).
        if row[7] != expected_prev or _entry_hash(expected_prev, payload) != row[8]:
            return False, str(row[0])
        expected_prev = str(row[8])
    return True, None


__all__ = ["GENESIS", "verify_chain", "write_audit"]
