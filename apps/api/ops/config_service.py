"""Reads and writes for `platform_settings` (PLATFORM-CONFIG §7, §9).

The routes own the HTTP shape and the step-up; this owns the queries, the refusals and
the audit. BACKEND-PATTERNS §1: service.py holds business logic AND queries, no
repository layer.

FIVE PROPERTIES HOLD FOR EVERY WRITE HERE, and each one is a rule from somewhere else
that this module is the local instance of:

1. **The value is validated against the `Settings` model before it is stored** (§7).
   Not against a copy of the field list — against the field's own definition, including
   its `Field(ge=…, le=…)` constraints (`core/platform_config.validate_value`). A value
   the app would reject at boot is refused here, at the boundary, where an operator can
   read why.
2. **A write is CONDITIONAL on the value it is replacing.** Two operators with the
   console open on one key used to both land, last writer winning and the first
   operator's decision vanishing with nothing on any screen. The token is per key (a
   sequence-backed `revision`), the check runs under a per-key advisory lock so
   check-then-write is atomic, and a losing write is REFUSED with the current value in
   the body — never merged.
3. **Writing the value that is already stored is a genuine no-op.** No row is touched,
   so the trigger does not fire, so the sentinel does not move, so no process in the
   fleet re-reads Postgres, and no audit row claims a change nobody made.
4. **The audit row is written in the SAME TRANSACTION as the change** (§8: "money's
   rule, applied to credentials"). `global_db` commits at the end of the request, so the
   row and the record of who moved it land together or neither does.
5. **The sentinel is published after the write** so peers see it on their next poll. The
   BUMP itself is a database trigger, not something written here — see the migration for
   why an application-side bump is the version of this that an operator's psql edit
   walks straight past.

WHAT THIS MODULE REFUSES, in the order it checks:

* a key that is not a `Settings` field at all — a typo, or a field that was renamed;
* a §4 bootstrap key — reading `APP_ENV` from the database would let the database decide
  the security posture;
* a credential-shaped key — those live encrypted in `platform_secrets` (§1), and a
  plaintext row for one is the failure mode the two-table design exists to prevent;
* a key whose stored value could never take effect (`env_only`, e.g. `db_pool_size`) or
  whose effect this build cannot describe (`unclassified`) — storing either produces a
  row an operator believes in and the platform ignores;
* a key the ENVIRONMENT declares — the store cannot win against `os.environ`, so storing
  a row for it would create exactly the field that silently does nothing (§8);
* a value the model rejects;
* a write whose `If-Match` no longer matches the stored revision.

Each refusal names the key and says what to do instead. A generic `invalid_config_key`
would make them all look like the same mistake, and only one of them is a typo.
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
    ENV_ONLY,
    UNCLASSIFIED,
    StoredRow,
    applies_rule,
    etag_for,
    is_secret_key,
    managed_fields,
    publish_version,
    refresh,
    typed_strict,
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
    #: The key's revision after this call — the token the NEXT conditional write sends.
    revision: int
    #: False when the submitted value was ALREADY the stored value and nothing was
    #: written: no row touched, no sentinel bump, no audit row, no fleet re-read. D-82's
    #: convention — "I stored this" and "this was already the value" are different
    #: sentences and a console that collapsed them would report a change nobody made.
    recorded: bool = True


async def read_rows(session: AsyncSession) -> dict[str, StoredRow]:
    """Provenance for every stored key: who set it, when, and why.

    The VALUES are deliberately not read here — the console shows what this process is
    actually using, which comes from `get_settings()` through the resolved snapshot. A
    row whose value failed re-validation would otherwise render as if it were in force.
    """
    rows = (
        await session.execute(
            text(
                "SELECT s.key, s.updated_at, s.note, a.name, a.id, s.revision "
                "FROM platform_settings s "
                "LEFT JOIN admin_users a ON a.id = s.updated_by"
            )
        )
    ).all()
    return {
        str(key): StoredRow(
            # The operator's NAME, not their id: this is read by another operator, and a
            # uuid answers "who changed the calling window" with a second lookup. Falls
            # back to the admin id for an operator with no name on file — it used to fall
            # back to the Clerk id, which D-177 stopped writing, so the fallback would
            # have degraded to a blank cell for every operator created since.
            updated_by=name or (str(admin_id) if admin_id is not None else None),
            updated_at=updated_at.isoformat() if updated_at is not None else None,
            note=note,
            revision=int(revision),
        )
        for key, updated_at, note, name, admin_id, revision in rows
    }


def _refuse_unmanaged(key: str) -> None:
    """The four ways a key can be off-limits, each with its own answer."""
    if key not in Settings.model_fields:
        raise ProblemError(
            kind="not_found",
            code="config_key_unknown",
            title="No such setting",
            detail=f"{key!r} isn't a setting Calevate recognises.",
            remediation=(
                "Check the name against the settings list, which shows every field you "
                "can manage here. A field that used to exist may have been renamed."
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
            detail=f"{key!r} is a credential, so it can't be stored here in plain text.",
            remediation=(
                "Set it under Secrets instead, which stores it encrypted and shows only "
                "its last four characters."
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
    rule = applies_rule(key)
    if rule.applies == ENV_ONLY:
        # A ROW HERE WOULD BE INERT FOREVER, which is worse than the env-shadowed case
        # below: that one becomes live the day the variable is removed, and this one
        # never does. `db_pool_size` is the instance — `db/session.py` builds the engine
        # from a bare `Settings()`, before this store can be read at all — and a console
        # that stored it would report a value the platform has never used.
        raise ProblemError(
            kind="business_rule",
            code="config_key_env_only",
            title="This setting can only take effect from the environment",
            detail=f"{key!r} is never read from here. {rule.caveat}",
            remediation=(
                f"Set {env_var_for(key)} in the deployment's environment. Storing it "
                "here would have no effect, now or after a restart."
            ),
        )
    if rule.applies == UNCLASSIFIED:
        # Fail-closed on a field nobody has classified. The alternative is to guess
        # `live` and let an operator discover the guess was wrong during an incident.
        raise ProblemError(
            kind="business_rule",
            code="config_key_unclassified",
            title="This build cannot say when a change here would take effect",
            detail=(
                f"{key!r} has not been classified yet, so Calevate cannot say "
                "when a change to it would take effect."
            ),
            remediation=(
                "Classify it (live / on_restart / needs_republish / env_only) with the "
                "reason, and ship that with the field. Until then the console will not "
                "offer a change it cannot describe."
            ),
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


def validated_value(key: str, raw: Any) -> Any:
    """Validate a console-supplied value against its own `Settings` field, or refuse.

    PUBLIC, AND THE SECOND CALLER IS WHY. This was `_validated`, private to the
    non-secret write path — and `ops/secret_service.set_secret` had no equivalent, so a
    console-set CREDENTIAL was checked for non-emptiness and nothing else. That is not a
    gap in coverage, it is a constraint that a different code path silently bypasses:
    `azure_openai_api_key` declares `max_length=512` and the secret path would seal a
    megabyte, and the day a credential field grows a `pattern=` the pattern would do
    nothing at all. `core/settings._current_settings` uses `model_copy(update=...)` —
    which does not re-validate — on the stated grounds that everything in the layer was
    validated before storage, and that ground was true for rows and false for secrets.
    One function, both doors.

    NOTHING FROM THE VALUE REACHES THE REFUSAL. Only `type` and `msg` are read off
    `ValidationError.errors()`; the `input` key it also carries is deliberately not
    touched, because on this path the input is a credential and a problem+json body is a
    response, a log line and a screenshot in a support ticket.
    """
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


@dataclass(frozen=True, slots=True)
class _Current:
    """The stored row as the write path needs it: its value and its concurrency token.

    `revision == 0` and `value is None` is the ABSENT row, which is a state a
    conditional write can legitimately be made against ("I believe nobody has set this")
    rather than a missing precondition.
    """

    value: Any
    revision: int


async def _lock_key(session: AsyncSession, key: str) -> None:
    """Serialize writers of ONE key for the rest of this transaction.

    THE VERSION COLUMN ALONE IS NOT ENOUGH, and this is the part a version column
    usually ships without. Two writers that both read revision 7 both satisfy the
    precondition and both write; the second silently wins, which is the bug the
    precondition exists to remove, now with a column to make it look handled. The lock
    makes read-then-write atomic per key, so the second writer reads the FIRST writer's
    revision and is refused.

    Scoped to the key, not the table: an operator changing `alerts_email` must never
    queue behind one changing `usd_inr_rate`. `pg_advisory_xact_lock` is the house
    primitive (BACKEND-PATTERNS §5, `secret_service.set_secret` uses the same shape) and
    is released by COMMIT or ROLLBACK, so there is no TTL to tune and no lock to leak.
    """
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"platform_config:{key}"},
    )


async def _current(session: AsyncSession, key: str) -> _Current:
    row = (
        await session.execute(
            text("SELECT value, revision FROM platform_settings WHERE key = :k"), {"k": key}
        )
    ).first()
    return _Current(value=None, revision=0) if row is None else _Current(row[0], int(row[1]))


async def _revision(session: AsyncSession, key: str) -> int:
    return (await _current(session, key)).revision


def _is_noop(key: str, *, current: _Current, incoming: Any) -> bool:
    """Is this write storing the value that is already stored?

    COMPARED AS TYPED VALUES, NOT AS JSON. Found by a test that expected the opposite:
    `9.5` and `"9.50"` are the same money and validate to the same `Decimal`, but their
    JSON forms are the strings `"9.5"` and `"9.50"`. A byte comparison calls those two
    different values, so a form that formats its number differently from the one that
    stored it would bump the sentinel, make every process in the fleet re-read Postgres
    and write an audit row — for a change nobody made. `Decimal("9.5") == Decimal("9.50")`
    is the comparison the domain actually means.

    A row that no longer PARSES is never a no-op, whatever it compares to: repairing it
    is exactly what the operator is doing, and `typed_value`'s lenient `None` would make
    a broken row look equal to an incoming `null`.
    """
    if current.revision == 0:
        return False
    try:
        stored_value = typed_strict(key, current.value)
    except ValidationError:
        return False
    return bool(stored_value == typed_strict(key, incoming))


async def _refuse_stale(
    session: AsyncSession, key: str, *, expected: int, current: _Current
) -> None:
    """A conditional write whose token no longer matches is REFUSED, never merged.

    412 rather than 409, and the difference is not cosmetic: RFC 9110 §15.5.13 defines
    412 as "one or more conditions given in the request header fields evaluated to
    false", which is exactly what happened, and a typed client can act on it without
    reading prose. 409 is what this repo raises when two resources conflict; a stale
    precondition is a conflict with a KNOWN remedy, and the remedy is in this response.

    THE REFUSAL CARRIES WHAT THE VALUE IS NOW, and that is the whole point. A bare
    "conflict" makes an operator retry blindly, which is last-write-wins with a round
    trip in front of it. This names the current value, who set it and when, and returns
    the fresh token in the `ETag` header so the console can re-arm the form against a
    value the operator has actually seen. Deciding is the operator's job; being able to
    decide is ours.
    """
    if expected == current.revision:
        return
    if current.revision == 0:
        now = "nothing is stored for it any more — it was reverted to its default"
    else:
        # The provenance read happens ONLY here, on the losing path. It is a small join
        # over a table of tens of rows, and putting it on the happy path would make
        # every config write pay for a message almost none of them render.
        row = (await read_rows(session)).get(key)
        who = row.updated_by if row and row.updated_by else "another operator"
        when = f" at {row.updated_at}" if row and row.updated_at else ""
        now = f"it is now {json.dumps(current.value)}, set by {who}{when}"
    raise ProblemError(
        kind="conflict",
        status=412,
        code="config_value_changed",
        title="Somebody else changed this setting first",
        detail=(
            f"{key!r} moved between the value you read and this request, so nothing was "
            f"written — {now}."
        ),
        remediation=(
            "Reload the setting to see the new value, decide whether your change still "
            "applies to it, and save it again with the fresh If-Match token from that "
            "reload. Your value was NOT stored and the other operator's was NOT overwritten."
        ),
        headers={"ETag": etag_for(current.revision)},
        fields=[
            {
                "field": key,
                "rule": "if_match",
                "message": (
                    f"expected revision {expected}, the stored revision is {current.revision}"
                ),
            }
        ],
    )


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
    session: AsyncSession,
    *,
    key: str,
    value: Any,
    note: str,
    actor_id: uuid.UUID,
    expected_revision: int,
) -> WriteResult:
    """Store one setting, CONDITIONALLY on the revision the caller read.

    The caller MUST have step-up confirmed and MUST write the audit row on this same
    session.

    THIS USED TO BE AN UNCONDITIONAL UPSERT, and the comment that defended it said there
    was "no invariant spanning the two writes to protect". There is: the operator decided
    using a value they had read. Two consoles open on `usd_inr_rate`, one operator
    correcting 88 → 91 while another corrects 88 → 84, and the loser's change disappears
    with nothing on any screen and nothing in any log to say a decision was discarded.
    The audit chain records both, which answers the question a WEEK later and not the one
    the operator has NOW.

    Three properties, in the order they are checked:

    1. **Stale token ⇒ refused, never merged** (`_refuse_stale`), with the current value
       in the body and the fresh token in the `ETag` header.
    2. **Identical value ⇒ a genuine no-op.** No row is touched, so the statement trigger
       does not fire, so the sentinel does not move, so no process in the fleet re-reads
       Postgres, and no audit row claims a change nobody made. A double-clicked Save
       costs one SELECT. `recorded=False` says so out loud rather than letting the
       console infer it from an unchanged value.
    3. **Otherwise the write lands**, under the per-key lock taken before the read.

    Note that idempotency is decided on the VALUE and not on the note: rewriting the same
    number with a fresh reason is not a configuration change, and treating it as one
    would put a sentinel bump and a fleet-wide re-read behind an operator fixing a typo
    in their own justification. The note that stays is the one that came with the value
    that is actually in force, which is the honest answer to "why is this value here".
    """
    _refuse_unmanaged(key)
    _refuse_env_shadowed(key)
    stored = validated_value(key, value)
    # The lock comes FIRST — before the read whose result the precondition is checked
    # against — or the check-then-write is not atomic and the precondition is decoration.
    await _lock_key(session, key)
    current = await _current(session, key)
    await _refuse_stale(session, key, expected=expected_revision, current=current)

    if _is_noop(key, current=current, incoming=stored):
        log.info("platform_config_write_noop", extra={"config_key": key})
        return WriteResult(
            key=key,
            old=current.value,
            new=current.value,
            version=await _version(session),
            revision=current.revision,
            recorded=False,
        )

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
    return WriteResult(
        key=key,
        old=current.value,
        new=stored,
        version=await _version(session),
        revision=await _revision(session, key),
    )


async def clear_value(
    session: AsyncSession, *, key: str, actor_id: uuid.UUID, expected_revision: int
) -> WriteResult | None:
    """Revert one setting to its code default. `None` when there was no row to remove.

    `None` rather than a silent success, because the two are different acts and only one
    of them is worth an audit row: reverting a key that was never overridden changed
    nothing, and recording `platform.config_reverted` for it would put a change nobody
    made into a tamper-evident ledger.

    CONDITIONAL FOR THE SAME REASON A SET IS, and arguably a stronger one: a revert puts
    a value nobody has looked at in months back into force, and doing that to a row
    somebody replaced ten seconds ago is the most expensive version of a lost update on
    this surface.
    """
    del actor_id  # the audit row carries the actor; the DELETE has no column for one
    _refuse_unmanaged(key)
    await _lock_key(session, key)
    current = await _current(session, key)
    await _refuse_stale(session, key, expected=expected_revision, current=current)
    if current.revision == 0:
        return None
    await session.execute(text("DELETE FROM platform_settings WHERE key = :k"), {"k": key})
    return WriteResult(
        key=key, old=current.value, new=None, version=await _version(session), revision=0
    )


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
    "validated_value",
]
