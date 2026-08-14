"""Reads and writes for `platform_settings` (PLATFORM-CONFIG §7, §9).

The routes own the HTTP shape and the step-up; this owns the queries, the refusals and
the audit. BACKEND-PATTERNS §1: service.py holds business logic AND queries, no
repository layer.

THREE PROPERTIES HOLD FOR EVERY WRITE HERE, and each one is a rule from somewhere else
that this module is the local instance of:

1. **The value is validated against the `Settings` model before it is stored** (§7).
   Not against a copy of the field list — against the field's own definition, including
   its `Field(ge=…, le=…)` constraints (`core/platform_config.validate_value`). A value
   the app would reject at boot is refused here, at the boundary, where an operator can
   read why.
2. **The audit row is written in the SAME TRANSACTION as the change** (§8: "money's
   rule, applied to credentials"). `global_db` commits at the end of the request, so the
   row and the record of who moved it land together or neither does.
3. **The sentinel is published after the write** so peers see it on their next poll. The
   BUMP itself is a database trigger, not something written here — see the migration for
   why an application-side bump is the version of this that an operator's psql edit
   walks straight past.

WHAT THIS MODULE REFUSES, in the order it checks:

* a key that is not a `Settings` field at all — a typo, or a field that was renamed;
* a §4 bootstrap key — reading `APP_ENV` from the database would let the database decide
  the security posture;
* a credential-shaped key — those live encrypted in `platform_secrets` (§1), and a
  plaintext row for one is the failure mode the two-table design exists to prevent;
* a key the ENVIRONMENT declares — the store cannot win against `os.environ`, so storing
  a row for it would create exactly the field that silently does nothing (§8);
* a value the model rejects.

Each refusal names the key and says what to do instead. A generic `invalid_config_key`
would make all five look like the same mistake, and only one of them is a typo.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from calevate_shared.config import Settings
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.platform_config import (
    StoredRow,
    is_secret_key,
    managed_fields,
    publish_version,
    refresh,
    validate_value,
)
from apps.api.core.settings import ENV_ONLY_KEYS, env_declares, env_var_for

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class WriteResult:
    """What actually happened, so the audit row and the response describe the same act.

    `old` and `new` are the JSON forms — what was in the column and what is now — and
    `old` is `None` when there was no row. That distinction is the difference between
    "changed 6.00 to 7.25" and "set 7.25 where the code default had been in force", and
    §9 requires the audit trail to be able to tell them apart.
    """

    key: str
    old: Any
    new: Any
    #: The config version AFTER the write, as the trigger set it. Returned so the console
    #: can tell that its change is the one now propagating.
    version: int


async def read_rows(session: AsyncSession) -> dict[str, StoredRow]:
    """Provenance for every stored key: who set it, when, and why.

    The VALUES are deliberately not read here — the console shows what this process is
    actually using, which comes from `get_settings()` through the resolved snapshot. A
    row whose value failed re-validation would otherwise render as if it were in force.
    """
    rows = (
        await session.execute(
            text(
                "SELECT s.key, s.updated_at, s.note, a.name, a.clerk_user_id "
                "FROM platform_settings s "
                "LEFT JOIN admin_users a ON a.id = s.updated_by"
            )
        )
    ).all()
    return {
        str(key): StoredRow(
            # The operator's NAME, not their id: this is read by another operator, and a
            # uuid answers "who changed the calling window" with a second lookup. Falls
            # back to the Clerk id when the admin row is gone (they left; the audit
            # chain still has the id, and `audit_log` is the permanent record).
            updated_by=name or clerk_id,
            updated_at=updated_at.isoformat() if updated_at is not None else None,
            note=note,
        )
        for key, updated_at, note, name, clerk_id in rows
    }


def _refuse_unmanaged(key: str) -> None:
    """The four ways a key can be off-limits, each with its own answer."""
    if key not in Settings.model_fields:
        raise ProblemError(
            kind="not_found",
            code="config_key_unknown",
            title="No such setting",
            detail=f"{key!r} is not a configuration field this build has.",
            remediation=(
                "Check the key against GET /v1/ops/config, which lists every managed "
                "field. A field that used to exist may have been renamed."
            ),
        )
    if key in ENV_ONLY_KEYS:
        raise ProblemError(
            kind="business_rule",
            code="config_key_bootstrap",
            title="This setting can only come from the environment",
            detail=(
                f"{key!r} is a bootstrap key: it is read before, or in order to reach, this store."
            ),
            remediation=(
                f"Set {env_var_for(key)} in the deployment's environment and restart. It "
                "cannot be managed from here — the store cannot hold the key that opens "
                "it, or the value that decides whether this deployment is production."
            ),
        )
    if is_secret_key(key):
        raise ProblemError(
            kind="business_rule",
            code="config_key_is_a_secret",
            title="Credentials are not stored here",
            detail=f"{key!r} is a credential, and this table holds plaintext.",
            remediation=(
                "Set it under Secrets, which stores it encrypted and shows only its "
                "last four characters (PLATFORM-CONFIG §1)."
            ),
        )
    if key not in managed_fields():  # pragma: no cover - the three above are exhaustive
        raise ProblemError(
            kind="business_rule",
            code="config_key_unmanaged",
            title="This setting is not managed here",
            detail=f"{key!r} cannot be set from the console.",
            remediation=f"Set {env_var_for(key)} in the environment instead.",
        )


def _refuse_env_shadowed(key: str) -> None:
    """The environment wins, so a row for an env-declared key would be inert.

    Refused rather than stored-and-ignored, and that is the whole §8 argument in one
    branch: a console that accepted the write, showed the new value and changed nothing
    is worse than one that says no. The refusal names the variable to change instead, so
    an operator who genuinely wants the new value knows exactly where it lives.
    """
    if env_declares(key):
        raise ProblemError(
            kind="conflict",
            code="config_key_set_in_environment",
            title="This setting is fixed by the environment",
            detail=(
                f"{key!r} is set as {env_var_for(key)} on this deployment, and the "
                "environment always wins over the store."
            ),
            remediation=(
                f"Change {env_var_for(key)} in the deployment's environment and restart, "
                "or remove it there to let this console manage the value. Storing it "
                "here would have no effect."
            ),
        )


def _validated(key: str, raw: Any) -> Any:
    try:
        return validate_value(key, raw)
    except ValidationError as exc:
        # The model's OWN message, per field. "engine must be one of fake, bolna,
        # cartesia" is a sentence an operator can act on; "invalid value" is not.
        raise ProblemError(
            kind="validation",
            code="config_value_invalid",
            title="That value would not be accepted at boot",
            detail=f"{key!r} cannot be set to that value.",
            remediation=(
                "This is validated against the same model the application loads at "
                "startup, so a value refused here is one that would have taken the next "
                "deploy down."
            ),
            fields=[
                {
                    "field": key,
                    "rule": str(error.get("type", "value_error")),
                    "message": str(error.get("msg", "")),
                }
                for error in exc.errors()
            ],
        ) from None


async def _current_value(session: AsyncSession, key: str) -> Any:
    row = (
        await session.execute(
            text("SELECT value FROM platform_settings WHERE key = :k"), {"k": key}
        )
    ).first()
    return row[0] if row is not None else None


@dataclass(frozen=True, slots=True)
class Sentinel:
    """The config version, and WHEN it last moved.

    `bumped_at` is read rather than merely written, and it earns its place on one
    question an operator asks while a change is not appearing: is the version I am
    looking at recent? "Version 42, bumped four seconds ago" and "version 42, bumped
    four days ago" are the difference between "my write landed and a peer is behind" and
    "my write never happened". The value comes from the trigger, so it is the database's
    own account of when the configuration last changed — not any row's `updated_at`,
    which a DELETE takes away with the row.
    """

    version: int
    changed_at: str | None


async def read_sentinel(session: AsyncSession) -> Sentinel:
    row = (
        await session.execute(
            text("SELECT version, bumped_at FROM platform_config_version WHERE id")
        )
    ).first()
    if row is None:
        # A database whose migration seeded nothing. The settings table is empty too, so
        # the honest answer is "nothing has ever changed" rather than a fabricated time.
        return Sentinel(version=0, changed_at=None)
    return Sentinel(version=int(row[0]), changed_at=row[1].isoformat() if row[1] else None)


async def _version(session: AsyncSession) -> int:
    return (await read_sentinel(session)).version


async def set_value(
    session: AsyncSession, *, key: str, value: Any, note: str, actor_id: uuid.UUID
) -> WriteResult:
    """Store one setting. The caller MUST have step-up confirmed and MUST write the audit
    row on this same session.

    UPSERT rather than read-then-write: two operators changing the same key at the same
    instant both land, last writer wins, and the audit chain records both attempts in
    order. A compare-and-swap was considered and is the wrong tool here — there is no
    invariant spanning the two writes to protect (unlike a credit balance), and a 409 on
    a config edit would send an operator to re-read a screen whose value they had just
    decided to replace.
    """
    _refuse_unmanaged(key)
    _refuse_env_shadowed(key)
    stored = _validated(key, value)
    old = await _current_value(session, key)

    await session.execute(
        text(
            "INSERT INTO platform_settings (key, value, updated_by, note) "
            "VALUES (:k, CAST(:v AS jsonb), :by, :note) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, "
            "updated_by = EXCLUDED.updated_by, note = EXCLUDED.note, updated_at = now()"
        ),
        # `json.dumps` rather than handing psycopg the Python object: the column is
        # jsonb and the value may be a bare string ("88.50"), which has to arrive as a
        # JSON string rather than as a bare SQL text literal.
        {"k": key, "v": _json(stored), "by": actor_id, "note": note},
    )
    # Read AFTER the write and on the same connection, so it reflects the trigger's bump
    # inside this transaction rather than a version another request produced.
    return WriteResult(key=key, old=old, new=stored, version=await _version(session))


async def clear_value(
    session: AsyncSession, *, key: str, actor_id: uuid.UUID
) -> WriteResult | None:
    """Revert one setting to its code default. `None` when there was no row to remove.

    `None` rather than a silent success, because the two are different acts and only one
    of them is worth an audit row: reverting a key that was never overridden changed
    nothing, and recording `platform.config_reverted` for it would put a change nobody
    made into a tamper-evident ledger.
    """
    del actor_id  # the audit row carries the actor; the DELETE has no column for one
    _refuse_unmanaged(key)
    old = await _current_value(session, key)
    if old is None:
        return None
    await session.execute(text("DELETE FROM platform_settings WHERE key = :k"), {"k": key})
    return WriteResult(key=key, old=old, new=None, version=await _version(session))


def _json(value: Any) -> str:
    """The value as a JSON DOCUMENT, for a `jsonb` parameter.

    Not the Python object: a validated `Decimal` arrives here as the string `"88.50"`,
    and handing psycopg a bare `str` for a jsonb cast produces the SQL text `88.50`,
    which is not valid JSON. `json.dumps` is what puts the quotes on.
    """
    return json.dumps(value)


async def propagate() -> int:
    """Make this process, and every peer, pick the change up.

    Two things, in this order, and both AFTER the caller's transaction has committed:
    this process rebuilds its own snapshot (so the response it is about to return
    describes the configuration it is now actually running), and the new version goes
    into Redis so peers see it on their next poll rather than waiting for the cached
    sentinel to expire.

    Never raises: a config write that succeeded must not report failure because Redis
    was unavailable. The durable truth is the row and the trigger's bump; this is the
    fast path, and the poll finds the change either way (§6).
    """
    snapshot = await refresh(force=True)
    await publish_version(snapshot.version)
    return snapshot.version


__all__ = [
    "Sentinel",
    "WriteResult",
    "clear_value",
    "propagate",
    "read_rows",
    "read_sentinel",
    "set_value",
]
