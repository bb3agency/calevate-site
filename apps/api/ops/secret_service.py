"""Storing, resolving and re-wrapping platform credentials (PLATFORM-CONFIG §5, §7).

The plaintext of a credential exists in exactly three places in this module and nowhere
else in the repo: the argument to `set_secret`, the return of `resolve_secrets`, and the
value inside a `Settings` object. §3 rule 6 governs all three — never logged, never
traced, never in a response body — and the shapes here are built so that obeying it is
the path of least resistance rather than a rule to remember:

* `SecretRecord` (what the console reads) HAS NO VALUE FIELD. There is nothing to leak.
* `set_secret` takes the plaintext and returns a `SecretRecord`. The value cannot escape
  through its own return type.
* `rewrap_all` never decrypts a secret at all — it re-wraps DEKs, which is the whole
  reason the envelope exists.

THERE IS NO READ-BACK FUNCTION AND THERE WILL NOT BE ONE. `resolve_secrets` exists to
load values into this PROCESS's settings; it is not reachable from any route, and §7
records the argument: a console that can display a credential is a console that leaks
every credential through one screenshot or one compromised session.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from calevate_shared.config import Settings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.envelope import Envelope, KekRing, kek_ring, last_four, rewrap, seal, unseal
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.platform_config import applies_rule, is_secret_key
from apps.api.core.settings import ENV_ONLY_KEYS, env_declares, env_var_for
from apps.api.db.result import rowcount_of
from apps.api.ops.config_service import validated_value

log = get_logger(__name__)


def secret_context(key: str) -> str:
    """The AAD one credential is sealed under. ONE definition.

    It binds the ciphertext to the row it belongs in, so an attacker with database write
    access cannot move the ciphertext of a key they control into ours and have every tag
    still verify (`core/envelope.seal` argues it at length). Derived from the key name
    rather than stored, for the reason `ingest/meta.verify_token_for` derives its verify
    token: a stored copy of a value computed from the primary key is a second thing that
    can drift.

    The `platform_secret:` prefix is what keeps §11's `tenant_secrets` from ever
    colliding with this namespace — a tenant credential seals under
    `tenant_secret:<tenant_id>:<key>` and therefore cannot be swapped in here.
    """
    return f"platform_secret:{key}"


@dataclass(frozen=True, slots=True)
class SecretRecord:
    """What the console may know about an installed credential.

    NO VALUE, NO CIPHERTEXT, NO DEK. `last_four` is the only fragment of the secret this
    type can carry, and `core/envelope.last_four` masks it entirely below eight
    characters. The type is the enforcement: there is no field for a plaintext to be
    accidentally assigned to.
    """

    key: str
    env_var: str
    version: int
    last_four: str
    kek_id: int
    created_at: str
    created_by: str | None
    #: True when the ENVIRONMENT also sets this key. The environment wins (§4), so the
    #: stored value is INERT — the console has to say so, or an operator rotates a key
    #: here and the platform keeps using the one in `.env`.
    shadowed_by_env: bool
    #: How many versions exist, including this one. Rotation history, so an operator can
    #: see that a key has been rotated without being able to read any of it.
    versions: int
    #: `live` | `on_restart` | ... — when a ROTATION actually reaches the code that uses
    #: this credential. From the same `FIELD_APPLIES` table the config panel reads, so
    #: the two surfaces cannot answer one question differently.
    applies: str
    #: What the operator must still do, or `None`. Non-null for everything but `live`.
    caveat: str | None


def manageable_secret_keys() -> tuple[str, ...]:
    """Every `Settings` field that belongs in `platform_secrets`.

    The EXACT COMPLEMENT of `platform_config.managed_fields()` within the non-bootstrap
    fields: a key is managed as plaintext config, or encrypted as a secret, and never
    both. One predicate (`is_secret_key`) decides, so the two surfaces cannot disagree
    about where a key lives and no key can fall between them.
    """
    return tuple(
        name for name in Settings.model_fields if name not in ENV_ONLY_KEYS and is_secret_key(name)
    )


def _refuse_unmanageable(key: str) -> None:
    if key not in Settings.model_fields:
        raise ProblemError(
            kind="not_found",
            code="secret_key_unknown",
            title="No such credential",
            detail=f"{key!r} is not a configuration field this build has.",
            remediation="GET /v1/ops/secrets lists every credential this deployment uses.",
        )
    if key in ENV_ONLY_KEYS:
        raise ProblemError(
            kind="business_rule",
            code="secret_key_bootstrap",
            title="This key can only come from the environment",
            detail=f"{key!r} is a bootstrap key (PLATFORM-CONFIG §4).",
            remediation=(
                f"Set {env_var_for(key)} in the deployment's environment. PLATFORM_KEK in "
                "particular can never live here: it is the key that opens this store."
            ),
        )
    if not is_secret_key(key):
        raise ProblemError(
            kind="business_rule",
            code="secret_key_is_plain_config",
            title="This setting is not a credential",
            detail=f"{key!r} is plain configuration and is readable.",
            remediation=(
                "Set it under Platform configuration, where its value is visible and "
                "revertible. Encrypting a value nobody needs hidden only makes it harder "
                "to audit."
            ),
        )


async def read_secrets(session: AsyncSession) -> list[SecretRecord]:
    """Every credential this deployment could hold, installed or not.

    Returns a row for keys with NO stored version too — as `version=0` with an empty
    `last_four` — because "we have never installed a Sarvam key" is exactly the answer an
    operator needs and an absent row would render as a blank space they have to interpret.
    """
    rows = (
        await session.execute(
            text(
                "SELECT DISTINCT ON (s.key) s.key, s.version, s.last_four, s.kek_version, "
                "s.created_at, a.name, a.id, "
                "(SELECT count(*) FROM platform_secrets c WHERE c.key = s.key) AS versions "
                "FROM platform_secrets s "
                "LEFT JOIN admin_users a ON a.id = s.created_by "
                "ORDER BY s.key, s.version DESC"
            )
        )
    ).all()
    installed = {
        str(r[0]): SecretRecord(
            key=str(r[0]),
            env_var=env_var_for(str(r[0])),
            version=int(r[1]),
            last_four=str(r[2]),
            kek_id=int(r[3]),
            created_at=r[4].isoformat(),
            created_by=r[5] or (str(r[6]) if r[6] is not None else None),
            shadowed_by_env=env_declares(str(r[0])),
            versions=int(r[7]),
            applies=applies_rule(str(r[0])).applies,
            caveat=applies_rule(str(r[0])).caveat,
        )
        for r in rows
    }
    return [
        installed.get(
            key,
            SecretRecord(
                key=key,
                env_var=env_var_for(key),
                version=0,
                last_four="",
                kek_id=0,
                created_at="",
                created_by=None,
                shadowed_by_env=env_declares(key),
                versions=0,
                applies=applies_rule(key).applies,
                caveat=applies_rule(key).caveat,
            ),
        )
        for key in manageable_secret_keys()
    ]


async def set_secret(
    session: AsyncSession, *, key: str, value: str, actor_id: uuid.UUID
) -> SecretRecord:
    """Seal a credential and INSERT it as a new version. Never an UPDATE.

    The caller MUST have step-up confirmed and MUST write the audit row on this same
    session. The plaintext is sealed before anything else touches it and is not held
    beyond this frame.

    `MAX(version) + 1` under an advisory lock on the KEY, not a read-then-write: two
    operators installing the same credential at the same instant would otherwise both
    compute the same next version and one INSERT would fail on the primary key — a 500
    where the honest answer is "you were second, and both attempts are recorded". The
    lock is the house primitive (BACKEND-PATTERNS §5) and is released by COMMIT or
    ROLLBACK, so there is no TTL to tune.
    """
    _refuse_unmanageable(key)
    if not value.strip():
        raise ProblemError(
            kind="validation",
            code="secret_value_empty",
            title="A credential cannot be empty",
            detail="An empty value would install nothing while looking like a rotation.",
            remediation=(
                "To stop using a credential, remove it from the environment and leave "
                "this unset — an empty row would read as installed."
            ),
        )
    # AND AGAINST THE FIELD'S OWN DEFINITION, which this path did not do and the rest of
    # the system assumed it did. `core/settings._current_settings` installs the override
    # layer with `model_copy(update=...)` — no re-validation — and says so, on the stated
    # ground that "every value in the layer was validated against THIS model's own field
    # definition before it was stored". That was true for `config_service.set_value` and
    # false here: emptiness was the only check, so a credential field's constraints were
    # decoration on the one path an operator actually uses. `azure_openai_api_key` carries
    # `max_length=512` today; the sharper case is the next `pattern=` somebody adds to a
    # credential, which would silently do nothing. A constraint a sibling code path
    # bypasses is worse than no constraint, because the model reads as if it holds.
    #
    # `validated_value`, not a second converter: one refusal vocabulary for both console
    # write paths, and it is documented not to echo the input into the problem body.
    validated_value(key, value)

    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"platform_secret:{key}"},
    )
    envelope = seal(value, context=secret_context(key))
    fragment = last_four(value)
    row = (
        await session.execute(
            text(
                "INSERT INTO platform_secrets (key, version, ciphertext, nonce, dek_wrapped, "
                "dek_nonce, kek_version, last_four, created_by) "
                "SELECT :k, COALESCE(MAX(version), 0) + 1, :ct, :n, :dw, :dn, :kek, :l4, :by "
                "FROM platform_secrets WHERE key = :k "
                "RETURNING version, created_at"
            ),
            {
                "k": key,
                "ct": envelope.ciphertext,
                "n": envelope.nonce,
                "dw": envelope.dek_wrapped,
                "dn": envelope.dek_nonce,
                "kek": envelope.kek_id,
                "l4": fragment,
                "by": actor_id,
            },
        )
    ).one()
    # `.one()`, not `.first()` plus a `row is None` guard. `INSERT ... SELECT` over an
    # aggregate always yields exactly one row, so that guard was unreachable and had to be
    # excluded from coverage to keep the ratchet honest — and an excluded branch is a
    # branch nobody will ever see fail. `.one()` deletes the branch instead of hiding it:
    # if the impossible ever happens, SQLAlchemy raises `NoResultFound` here, which the
    # error ladder turns into the same 500 the hand-written `ProblemError` produced, with
    # a traceback that points at this line rather than at a message we invented.
    version = int(row[0])
    # Every PREVIOUS version of this key is retired in the same transaction. Retirement
    # is a fact about which version is live, and leaving it to a later job would mean a
    # window where two versions both look current to anything reading `retired_at`.
    await session.execute(
        text(
            "UPDATE platform_secrets SET retired_at = now() "
            "WHERE key = :k AND version < :v AND retired_at IS NULL"
        ),
        {"k": key, "v": version},
    )
    # Ids and a four-character fragment. No value, no ciphertext (hard rule 6).
    log.info("platform_secret_set", extra={"config_key": key, "secret_version": version})
    return SecretRecord(
        key=key,
        env_var=env_var_for(key),
        version=version,
        last_four=fragment,
        kek_id=envelope.kek_id,
        created_at=row[1].isoformat(),
        created_by=str(actor_id),
        shadowed_by_env=env_declares(key),
        versions=version,
        applies=applies_rule(key).applies,
        caveat=applies_rule(key).caveat,
    )


@dataclass(frozen=True, slots=True)
class ResolvedSecrets:
    """What the store contributed, and what it could not.

    `values` never reaches a response model — `platform_config` applies it to `Settings`
    and drops it. `unreadable` is the operational half: a key whose row exists but which
    no configured KEK opens is a deployment misconfiguration an operator has to be told
    about, and silently omitting it would present as "the vendor rejected our key".
    """

    values: dict[str, str]
    unreadable: tuple[str, ...]


async def resolve_secrets(session: AsyncSession, *, ring: KekRing | None = None) -> ResolvedSecrets:
    """Decrypt the CURRENT version of every stored credential, for this process.

    Called only from the config refresh (`core/platform_config`), never from a route.
    The environment still wins: keys the environment declares are skipped here exactly as
    they are for plain config, so a `.env` value is never shadowed by a stored one.

    A row that will not open does NOT stop the others. One credential written under a KEK
    this deployment no longer has must not be able to blank every other credential in the
    fleet — that would turn a rotation mistake into a total outage, which is the failure
    direction §6 forbids.
    """
    keys = kek_ring() if ring is None else ring
    rows = (
        await session.execute(
            text(
                "SELECT DISTINCT ON (key) key, ciphertext, nonce, dek_wrapped, dek_nonce, "
                "kek_version FROM platform_secrets ORDER BY key, version DESC"
            )
        )
    ).all()
    values: dict[str, str] = {}
    unreadable: list[str] = []
    for key, ciphertext, nonce, dek_wrapped, dek_nonce, kek_version in rows:
        name = str(key)
        if name not in Settings.model_fields or name in ENV_ONLY_KEYS or env_declares(name):
            continue
        envelope = Envelope(
            ciphertext=bytes(ciphertext),
            nonce=bytes(nonce),
            dek_wrapped=bytes(dek_wrapped),
            dek_nonce=bytes(dek_nonce),
            kek_id=int(kek_version),
        )
        try:
            values[name] = unseal(envelope, context=secret_context(name), ring=keys)
        except ProblemError:
            # Named, never valued. The alert is raised by the caller, which knows
            # whether this is a cold start or a degradation.
            log.error("platform_secret_unreadable", extra={"config_key": name})
            unreadable.append(name)
    return ResolvedSecrets(values=values, unreadable=tuple(unreadable))


@dataclass(frozen=True, slots=True)
class RewrapResult:
    """What a KEK rotation actually moved."""

    examined: int
    rewrapped: int
    #: Rows no configured KEK opens. NOT re-wrapped and NOT skipped silently: they are
    #: the rows that will become unreadable if the retired KEK is removed, so the
    #: operator has to see the count before they clean up their environment.
    unreadable: tuple[str, ...]
    kek_id: int


async def rewrap_all(session: AsyncSession, *, ring: KekRing | None = None) -> RewrapResult:
    """Re-wrap EVERY DEK under the active KEK. The rotation half of §13 phase 5.

    ═══ THIS FUNCTION MUST NEVER FILTER ON `kek_version`. ═══

    The obvious optimisation is `WHERE kek_version <> :active` — skip the rows already
    under the current key. Do not add it. `kek_version` is a REPORTING field (D-96): it
    is a fingerprint of the key that wrapped the row, written by whoever wrote the row,
    and the entire reason it is a fingerprint rather than an operator-maintained counter
    is that a LABEL must never decide what work happens. The moment this filters on it,
    a row whose label is wrong for any reason — a bug, a hand-written INSERT, a restore
    from a backup taken mid-rotation — is skipped by every rotation from then on, and the
    rotation AFTER that removes the only KEK that could still open it. That is silent,
    unrecoverable data loss, and it is the exact failure mode the counter design had.

    So: every row, every time. Trial-unwrap over the ring, re-wrap under the active KEK,
    write the fresh fingerprint. The cost is one AES-GCM decrypt and one encrypt of 32
    bytes per secret version — microseconds each, on a table with tens of rows.

    THE PLAINTEXT IS NEVER TOUCHED. `ciphertext` and `nonce` are not read, not written
    and not decrypted; only the DEK is unwrapped and re-wrapped. That is what makes a
    rotation cheap (§3 rule 3) and what keeps this operation safe to run while the
    platform is serving.

    CONCURRENCY. The whole run holds one advisory lock, so two rotations cannot
    interleave, and each row's UPDATE is guarded on the wrapping it read (`WHERE
    dek_wrapped = :old`) — a compare-and-swap, so a `set_secret` that landed a new
    version underneath us loses the race for that row rather than being overwritten. The
    lock is released by COMMIT or ROLLBACK; there is no TTL to tune (BACKEND-PATTERNS §5).
    """
    keys = kek_ring() if ring is None else ring
    active = keys.active
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('platform:kek', 0))"))
    rows = (
        await session.execute(
            text("SELECT key, version, dek_wrapped, dek_nonce FROM platform_secrets ORDER BY key")
        )
    ).all()

    rewrapped = 0
    unreadable: list[str] = []
    for key, version, dek_wrapped, dek_nonce in rows:
        name, number = str(key), int(version)
        context = secret_context(name)
        try:
            # `rewrap` copies the payload through UNREAD — a rotation never decrypts a
            # credential, which is what makes it safe to run against a live platform by
            # an operator who is not entitled to read what they are re-wrapping.
            fresh = rewrap(
                Envelope(
                    ciphertext=b"",
                    nonce=b"",
                    dek_wrapped=bytes(dek_wrapped),
                    dek_nonce=bytes(dek_nonce),
                    kek_id=0,
                ),
                context=context,
                ring=keys,
            )
        except ProblemError:
            log.error(
                "platform_secret_rewrap_unreadable",
                extra={"config_key": name, "secret_version": number},
            )
            unreadable.append(f"{name}#{number}")
            continue
        result = await session.execute(
            text(
                "UPDATE platform_secrets SET dek_wrapped = :dw, dek_nonce = :dn, "
                "kek_version = :kek WHERE key = :k AND version = :v AND dek_wrapped = :old"
            ),
            {
                "dw": fresh.dek_wrapped,
                "dn": fresh.dek_nonce,
                "kek": active.kek_id,
                "k": name,
                "v": number,
                "old": bytes(dek_wrapped),
            },
        )
        # rowcount 0 = another writer moved this row between our read and our write. Not
        # an error: their wrapping is at least as new as ours, and the next run catches
        # anything left (BACKEND-PATTERNS §5 — treat a lost race as a skip, not a fault).
        rewrapped += rowcount_of(result)

    return RewrapResult(
        examined=len(rows),
        rewrapped=rewrapped,
        unreadable=tuple(unreadable),
        kek_id=active.kek_id,
    )


__all__ = [
    "ResolvedSecrets",
    "RewrapResult",
    "SecretRecord",
    "manageable_secret_keys",
    "read_secrets",
    "resolve_secrets",
    "rewrap_all",
    "secret_context",
    "set_secret",
]
