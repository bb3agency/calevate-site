"""The console's values, in every process, without a restart (PLATFORM-CONFIG §6).

`get_settings()` is read on every request in four processes — api, voice-runtime,
workers and the pilot CLI — and **voice-runtime must not pay a database round trip on
its request path** (hard rule 3: ack under 500ms). So the read path here does no IO at
all: it hands back a dict that is already in memory, and everything that touches
Postgres or Redis happens on a background poll.

## The three layers, cheapest first

    read path      core.settings.get_settings()   in-memory, lru_cached, zero IO
    poll (~3s)     Redis GET of one integer       sub-millisecond, no DB connection
    on a change    Postgres SELECT of ~N rows     once per version bump, per process

This is `core/loadshed.py`'s shape — durable truth in Postgres, Redis as the cheap
shared cache, an in-process memo in front of both — reused rather than reinvented,
because two ways to propagate one global fact is how the two end up disagreeing. What
differs is the trigger: load-shed re-reads on a TTL, and this re-reads on a SENTINEL,
because the config payload is 50 rows rather than two booleans and re-reading it every
15 seconds in every process would be a database poll pretending to be a cache.

## The sentinel, and why the DATABASE bumps it

`platform_config_version` holds one integer. Every process remembers which version its
snapshot was built from; a poll compares. Equal — and that is the overwhelmingly common
case — costs one Redis GET and nothing else.

**The migration bumps it with a TRIGGER on `platform_settings`, not the application.**
An application-side bump is correct exactly as long as every writer remembers, and the
writers are not only ours: PLATFORM-CONFIG's own done-when for this phase is "a value
changed in psql reaches all four processes in <10s", and an operator editing a row at
3am is precisely the writer who will not run our bump. A trigger cannot be forgotten,
cannot be bypassed by a second code path, and makes the version a statement ABOUT the
data rather than a claim beside it.

## The propagation arithmetic (target: under 10 seconds)

* the writer bumps the row (trigger) and, after COMMIT, publishes the new integer to
  Redis — so peers usually see it on their very next poll, ≤ `_POLL_INTERVAL_S`;
* if that publish is lost (Redis down, process died between commit and publish), the
  Redis copy expires after `_SENTINEL_TTL_S` and the next poll reads Postgres;
* worst case is therefore `_SENTINEL_TTL_S + _POLL_INTERVAL_S` = 8s, with the normal
  case at 3s. The margin is deliberate: a target met only on the happy path is not met.

## When the store is unreachable

**The last good snapshot keeps serving, and the process alerts.** A config lookup must
never be able to take the phone system down (§6). Two states are told apart because an
operator's next move differs:

* `degraded` — we had a snapshot and cannot refresh it. The values in force are real
  ones, just possibly stale; the risk is that a change made in the console has not
  landed everywhere.
* `never_loaded` — a COLD START that has never reached the store. There is no "last
  good" to serve, so the process runs on `os.environ` + code defaults.

The second is the one that needed a decision, and the decision is: **serve, loudly.**
The alternative — refuse to boot without the store — would make `platform_settings` a
new single point of failure in front of a phone system that has never needed one, and
would do it for a table that is EMPTY on every deployment today. Env plus code defaults
is exactly the configuration every process ran on before this feature existed, the §4
bootstrap set is env-only regardless, and no security posture depends on a store value
(`ENV_ONLY_KEYS` is what guarantees that). So the failure direction is "the platform
runs as it did last release", which is safe, and it is announced with
`platform_config_never_loaded` rather than discovered.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from calevate_shared.config import Settings
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import text

from apps.api.core.alerting import alert
from apps.api.core.logging import REDACT_KEYS, get_logger
from apps.api.core.redis import get_redis
from apps.api.core.settings import (
    ENV_ONLY_KEYS,
    apply_platform_overrides,
    effective_env,
    env_declares,
    env_var_for,
)
from apps.api.db.session import untenanted_session

if TYPE_CHECKING:  # a cycle at runtime, a plain name to the type checker
    from apps.api.ops.secret_service import ResolvedSecrets

log = get_logger(__name__)

#: How often a process asks whether the config changed. See the arithmetic above.
_POLL_INTERVAL_S = 3.0
#: How long the shared sentinel may live in Redis without anyone re-reading Postgres.
#: It is a BACKSTOP, not the mechanism — the writer publishes through on every change —
#: so its only job is bounding staleness when that publish is lost.
_SENTINEL_TTL_S = 5
_SENTINEL_KEY = "calevate:platform_config_version"

#: The version of a database that has never had a config change. Also what a cold start
#: with no store reports, so `version == 0` reads as "nothing from the store yet".
_UNKNOWN_VERSION = 0


# --- what may be managed from the console -------------------------------------
#
# Derived from the `Settings` model itself. There is deliberately NO hand-kept list of
# managed keys: a second list is exactly the drift this repo keeps finding, and it would
# have to be updated by whoever adds a field — which is the person who does not know
# this file exists.

#: `REDACT_KEYS` entries that are about PII IN A LOG PAYLOAD rather than about a
#: credential in a CONFIG FIELD NAME. Subtracted rather than the whole list being
#: re-typed, so extending `REDACT_KEYS` with a new credential pattern extends this too.
#:
#: Each of these would be a false positive here, and two of them are ones we actively
#: want managed: `alerts_email` (where operator alerts go — an operational value, and
#: the one an incident makes you want to change fastest) and `notifications_from`.
_PII_ONLY_REDACT_KEYS: frozenset[str] = frozenset(
    {
        "phone",
        "e164",
        "recipient",
        "transcript",
        "text",
        "body",
        "extraction",
        "payload",
        "email",
    }
)

#: Field-name fragments that mark a value as a CREDENTIAL, and therefore as something
#: `platform_settings` may never hold in plaintext. Those keys are phase 4's business
#: and live encrypted in `platform_secrets`; a plaintext row for one of them is the
#: exact failure mode §1 rejects the single-table design over.
#:
#: The base is `core/logging.REDACT_KEYS` minus the PII-only entries above — the same
#: patterns that decide what must never reach a log line decide what must never reach
#: this table, because both answer one question ("would disclosing this hurt?"). The
#: four additions are the ones a log line does not care about and a plaintext store must:
#:
#:   dsn          `SENTRY_DSN` embeds a project key in a URL.
#:   credential   the naming a future field is likely to use.
#:   private_key  likewise, and it is the one nobody would forgive.
#:   _json        `GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON` is a signing key in a JSON blob.
#:   heartbeat    `BACKUP_HEARTBEAT_URL` is a credential and says so in its own comment:
#:                anyone holding it can silence the backup alarm by pinging it. It is
#:                named specifically because nothing about its SHAPE gives it away.
#:
#: A false POSITIVE costs a key that must be set in the environment (annoying); a false
#: NEGATIVE puts an API key in a plaintext table (catastrophic). The patterns are broad
#: on purpose, and the asymmetry is the reason.
_SECRET_NAME_FRAGMENTS: tuple[str, ...] = tuple(
    sorted(
        (set(REDACT_KEYS) - _PII_ONLY_REDACT_KEYS)
        | {"dsn", "credential", "private_key", "_json", "heartbeat"}
    )
)

#: Keys whose value is consumed ONCE, when the process starts, with the reason.
#:
#: These are still managed — hiding them would be worse — but the console has to say
#: that changing one does nothing until a restart. §8's rule is that "a field that
#: silently does nothing is worse than no field", and a field that quietly does nothing
#: *for six hours* is the same defect wearing a delay. This is the one classification
#: here that cannot be derived from a type, because it is a fact about WHERE the value
#: is read, not about what it is; it is small, it is reasoned per key, and a field
#: omitted from it defaults to "live", which is true of anything read through
#: `get_settings()` at the point of use — the overwhelmingly common shape in this repo.
APPLIES_ON_RESTART: dict[str, str] = {
    "db_pool_size": (
        "the SQLAlchemy engine is built once per process (db/session.py holds it in "
        "`_engine`), so the pool keeps whatever size it was created with"
    ),
    "otel_exporter_otlp_endpoint": (
        "tracing is initialised once at boot (`init_tracing` returns early when a "
        "provider already exists) — a second provider would double every span"
    ),
    "otel_traces_sample_ratio": (
        "the sampler is fixed when the tracer provider is built, for the same reason"
    ),
}

#: Keys that take effect immediately but do NOT retroactively change what already
#: exists, with what the operator has to do about it. Distinct from the above: the value
#: IS live, the leftover is elsewhere.
APPLIES_WITH_FOLLOW_UP: dict[str, str] = {
    "webhook_base_url": (
        "new agent publishes use it immediately, but every agent already published "
        "carries the OLD URL in its engine-side config — they must be re-published or "
        "their webhooks keep going to the previous address"
    ),
}

#: How a value is rendered and edited in the console. Derived from the annotation, never
#: hand-mapped: a field whose type changes changes its editor with it.
ValueKind = str


@dataclass(frozen=True, slots=True)
class ConfigField:
    """One managed key, as the console needs to see it.

    `source` is the load-bearing field. §4's resolution order puts the environment above
    the store, so a key set in `.env` CANNOT be changed from the console — and a form
    that offered to change it anyway would be "a field that silently does nothing", which
    §8 calls worse than no field. `editable` is computed from it here, once, rather than
    re-derived by the console.
    """

    key: str
    env_var: str
    #: The value in force in THIS process, in its JSON form.
    value: Any
    #: `env` | `db` | `default` — where that value came from.
    source: str
    #: The code default, so the console can say what reverting would restore. `None`
    #: when there is none — read `has_default` to tell that apart from a default that
    #: genuinely IS null, which most optional fields here have.
    default: Any
    #: False for a REQUIRED field (`object_store_endpoint`). Such a field cannot be
    #: reverted — there is nothing to revert to — and in practice is always `env`
    #: sourced, because a process whose environment lacks it cannot construct `Settings`
    #: and therefore cannot boot.
    has_default: bool
    kind: ValueKind
    #: The allowed values, for a `Literal` field. Empty for everything else.
    options: tuple[str, ...]
    editable: bool
    #: `live` | `on_restart` — when a change to this key actually takes effect.
    applies: str
    #: What the operator still has to do after changing it, or `None`. Carries the
    #: reason for `on_restart`, and the follow-up for a key like `webhook_base_url`
    #: whose new value is live but whose old value is baked into things already
    #: published. Rendered beside the field, because a caveat in a runbook reaches
    #: nobody at the moment they are typing into the box.
    caveat: str | None
    #: Who last set it in the store, and when. Both `None` unless `source == "db"`.
    updated_by: str | None
    updated_at: str | None
    note: str | None


@dataclass(frozen=True, slots=True)
class ConfigSnapshot:
    """What the store contributed, and how much that answer can be trusted."""

    version: int
    overrides: Mapping[str, Any]
    #: `monotonic()` of the last SUCCESSFUL store read; `None` on a cold start that has
    #: never reached it. The two are not the same state — see the module docstring.
    loaded_at: float | None
    #: True when the last refresh attempt failed. `loaded_at is not None and degraded`
    #: is "stale but real"; `loaded_at is None` is "never loaded".
    degraded: bool


_snapshot = ConfigSnapshot(version=_UNKNOWN_VERSION, overrides={}, loaded_at=None, degraded=False)
# One rebuild at a time per process. Not a distributed lock and not trying to be: a
# stampede across processes would be N small SELECTs on a version bump, which is not a
# stampede. What this prevents is the in-process version — the poll loop and a
# write-through refresh arriving together and both rebuilding, which would double the
# work and could install the OLDER of two reads last.
_refresh_lock = asyncio.Lock()
_refresher: asyncio.Task[None] | None = None


def snapshot() -> ConfigSnapshot:
    """The current snapshot. Synchronous, zero IO — safe on any request path."""
    return _snapshot


# --- typing a jsonb value back onto a Settings field --------------------------


def managed_fields() -> tuple[str, ...]:
    """Every `Settings` field the console may manage, computed from the model.

    Three exclusions, each structural rather than listed:

    1. **§4's bootstrap set** (`ENV_ONLY_KEYS`) — the keys whose relocation would be a
       security-posture inversion.
    2. **Anything whose NAME says credential** — see `_SECRET_NAME_FRAGMENTS`. These are
       phase 4's business and live encrypted in `platform_secrets`; a plaintext row for
       one of them is the failure mode §1 rejects the single-table design over.
    3. Nothing else. Every remaining field is a candidate, which is what makes ".env goes
       from ~54 keys to 6" a checkable claim rather than an aspiration.
    """
    return tuple(
        name
        for name in Settings.model_fields
        if name not in ENV_ONLY_KEYS and not is_secret_key(name)
    )


def is_secret_key(name: str) -> bool:
    """Does this field's NAME mark it as a credential?

    Substring matching, like the log redactor it borrows from: `clerk_admin_secret_key`,
    `smtp_password` and `meta_page_access_tokens` all have to be caught by a rule nobody
    maintains per field. A false POSITIVE here costs a key that has to be set in the
    environment (annoying); a false NEGATIVE puts an API key in a plaintext table
    (catastrophic). The asymmetry is why the patterns are deliberately broad.
    """
    lowered = name.lower()
    return any(fragment in lowered for fragment in _SECRET_NAME_FRAGMENTS)


def _adapter(field: str) -> TypeAdapter[Any]:
    """A validator for ONE `Settings` field, built from that field's own definition.

    THIS IS THE ANSWER TO "how do you type a jsonb value back onto a Pydantic field
    without a second copy of the field list". `FieldInfo.rebuild_annotation()` returns
    `Annotated[<annotation>, *<constraints>]` — the annotation AND the `Field(ge=…, le=…)`
    metadata, which is the half a bare `TypeAdapter(field.annotation)` would silently
    drop, so `otel_traces_sample_ratio = 5.0` would be stored and then rejected at the
    next boot. That is precisely the failure §7 says must be refused at the boundary.

    Not cached: `TypeAdapter` construction is cheap, this runs on writes and on snapshot
    rebuilds rather than per request, and a cache keyed on a field name would go stale
    against a reloaded model in exactly the tests that matter.

    WHAT THIS DOES NOT COVER, stated because a validator that implies more than it checks
    is worse than none: a cross-field `@model_validator` on `Settings` would not run
    here. There are none today. If one is added, this has to become a whole-model
    validation — and `platform_config_test` pins the field count so that adding one is
    visible.
    """
    return TypeAdapter(Settings.model_fields[field].rebuild_annotation())


def validate_value(field: str, raw: Any) -> Any:
    """Validate a candidate against the `Settings` model and return its JSON form.

    Returns what should be STORED: `dump_python(mode="json")` of the validated value, so
    a `Decimal` lands in `jsonb` as the string `"88.50"` rather than as a JSON double
    that is not 88.50 (hard rule 7). Reading it back through the same adapter recovers
    the `Decimal` exactly.

    Raises `ValidationError` — the caller turns it into problem+json with the field's own
    message, because "engine must be one of fake, bolna, cartesia" is a sentence an
    operator can act on and "invalid value" is not.
    """
    adapter = _adapter(field)
    return adapter.dump_python(adapter.validate_python(raw), mode="json")


def _typed(field: str, stored: Any) -> Any:
    """A stored JSON value as the Python value `Settings` expects, or `None` if it no
    longer validates (a row written by an older build against a field that has since
    narrowed)."""
    try:
        return _adapter(field).validate_python(stored)
    except ValidationError:
        return None


def typed_value(field: str, stored: Any) -> Any:
    """The public spelling of `_typed`, for a caller that has just validated a write.

    Same function, exported because the write path needs to project its own change onto
    a `Settings` copy before its transaction commits, and reaching into a private name
    from another module is how two definitions of "what does this jsonb mean" appear.
    """
    return _typed(field, stored)


def project(overrides: Mapping[str, Any]) -> tuple[Settings, ConfigSnapshot]:
    """What this process WOULD be running with exactly these overrides in force.

    Exists for one caller and one moment: a config write renders its response BEFORE the
    request's transaction commits, so re-reading the snapshot would report the value the
    operator has just replaced. Projecting is honest — this is the configuration one
    commit from now — and it keeps the write path from having to reproduce `describe`'s
    source logic in a second place.

    It changes NO module state. The real snapshot moves when the refresh does.
    """
    base = Settings()
    effective = base.model_copy(update=dict(overrides)) if overrides else base
    return effective, replace(snapshot(), overrides=dict(overrides))


def _kind_of(field: str) -> tuple[ValueKind, tuple[str, ...]]:
    """How the console should render this field, from its annotation.

    Derived rather than declared for the same reason `managed_fields` is: a per-field
    editor table is a second list, and the first field somebody adds without touching it
    renders as a text box that stores a string into an integer.
    """
    schema = _adapter(field).json_schema(mode="serialization")
    # `str | None` produces an anyOf; the interesting half is the non-null branch.
    variants = [v for v in schema.get("anyOf", [schema]) if v.get("type") != "null"]
    head = variants[0] if variants else schema
    if "enum" in head:
        return "enum", tuple(str(v) for v in head["enum"])
    kind = str(head.get("type", "string"))
    # A `Decimal` serializes as a string with a numeric pattern; it is money and must
    # stay exact, so it is its own kind rather than a number the browser could round.
    if kind == "string" and "pattern" in head and head.get("format") != "date-time":
        return "decimal", ()
    return kind, ()


# --- reading the store --------------------------------------------------------


async def _read_version() -> int:
    async with untenanted_session() as session:
        row = (
            await session.execute(text("SELECT version FROM platform_config_version WHERE id"))
        ).first()
    # No row = a database whose migration seeded nothing, which is a fresh install, not
    # an emergency: the settings table is empty too, so the honest version is "nothing".
    return int(row[0]) if row is not None else _UNKNOWN_VERSION


async def _read_rows() -> dict[str, Any]:
    async with untenanted_session() as session:
        rows = (await session.execute(text("SELECT key, value FROM platform_settings"))).all()
    return {str(key): value for key, value in rows}


async def _read_secrets() -> ResolvedSecrets:
    """Decrypt the current version of every stored credential, for this process.

    A LOCAL import, and deliberately: `ops.secret_service` imports this module for
    `is_secret_key`, so a module-level import here would be a cycle. Keeping the
    dependency one-way at module level and reaching down inside the one function that
    needs it is the same judgement `apps/api/main.py` makes about its routers — and it
    means a process that never refreshes never imports the crypto path at all.
    """
    from apps.api.ops.secret_service import resolve_secrets

    async with untenanted_session() as session:
        return await resolve_secrets(session)


async def _sentinel() -> int:
    """The current config version, from Redis when it is there and Postgres when it is not.

    Redis is a COST optimisation, never the truth: a miss, a flush or an outage costs one
    small Postgres read and changes no answer. That ordering is what makes a Redis
    incident invisible to config propagation instead of freezing it.
    """
    try:
        cached = await get_redis().get(_SENTINEL_KEY)
        if cached is not None:
            return int(cached)
    except Exception:
        log.warning("platform_config_sentinel_cache_unavailable")
    version = await _read_version()
    await publish_version(version)
    return version


async def publish_version(version: int) -> None:
    """Put the version in Redis with an expiry. Best effort, always expiring.

    Every write of this key carries a TTL — the same rule `core/loadshed` learned the
    hard way: a cached value with no expiry, plus one lost invalidation, is a stale
    answer that outlives the incident that caused it.
    """
    try:
        await get_redis().set(_SENTINEL_KEY, str(version), ex=_SENTINEL_TTL_S)
    except Exception:
        log.warning("platform_config_sentinel_publish_failed")


def _resolve(rows: Mapping[str, Any], environ: Mapping[str, str]) -> dict[str, Any]:
    """Store rows → the override layer, applying §4's resolution order.

    `os.environ` → `platform_settings` → code default. The environment winning is
    implemented HERE, by not offering the key at all, rather than by the settings layer
    preferring one source over another: a value that is never offered cannot be applied
    by a future caller who did not read this comment.

    Rows that no longer belong are dropped with a log line rather than raising: this runs
    on a background refresh in every process, and a single bad row must not be able to
    stop a fleet from picking up the good ones.
    """
    resolved: dict[str, Any] = {}
    managed = set(managed_fields())
    for key, stored in rows.items():
        if key not in managed:
            # A field that was renamed or removed, or a key somebody inserted by hand
            # that the model has never had. Loud, and skipped.
            log.warning("platform_config_row_unmanaged", extra={"config_key": key})
            continue
        if env_declares(key, environ):
            # The escape hatch doing its job (§4): the environment wins, and the console
            # renders this key read-only with that as the reason.
            continue
        value = _typed(key, stored)
        if value is None and stored is not None:
            log.warning("platform_config_row_invalid", extra={"config_key": key})
            continue
        resolved[key] = value
    return resolved


async def refresh(*, force: bool = False) -> ConfigSnapshot:
    """Poll the sentinel and, if it moved, rebuild the snapshot. Safe to call anywhere.

    Never raises. Every caller is either a background loop or a post-write write-through,
    and both have the same correct behaviour on failure: keep the last good snapshot and
    make some noise.
    """
    global _snapshot
    async with _refresh_lock:
        try:
            version = await _sentinel()
            # Double-checked inside the lock: a caller that queued behind a rebuild for
            # the same version has nothing to do.
            if not force and version == _snapshot.version and _snapshot.loaded_at is not None:
                if _snapshot.degraded:
                    _snapshot = replace(_snapshot, degraded=False)
                return _snapshot
            rows = await _read_rows()
            secrets = await _read_secrets()
        except Exception as exc:
            _snapshot = replace(_snapshot, degraded=True)
            if _snapshot.loaded_at is None:
                # COLD START WITH NO SNAPSHOT — the case the module docstring decides.
                # The process serves env + code defaults and says so; it does not refuse
                # to run, and it does not pretend the store was empty.
                alert(
                    "CORE_LOGIC",
                    "platform_config_never_loaded",
                    detail=(
                        "This process has never read platform_settings, so it is running "
                        "on environment variables and code defaults. Console changes are "
                        "NOT in force here."
                    ),
                    reason=type(exc).__name__,
                )
            else:
                alert(
                    "CORE_LOGIC",
                    "platform_config_stale",
                    detail=(
                        "platform_settings could not be re-read; the last known values "
                        "are still in force. A console change may not have propagated."
                    ),
                    reason=type(exc).__name__,
                )
            return _snapshot

        overrides = _resolve(rows, effective_env())
        # SECRETS RIDE THE SAME SENTINEL AND THE SAME LAYER. §6 proposed resolving them
        # lazily on a shorter TTL of their own; one mechanism is strictly better here —
        # the sentinel is FASTER than any TTL (a rotation propagates in ≤8s rather than
        # in a TTL's worth of luck), it is one thing to reason about rather than two, and
        # a rotation is precisely the change that must not wait. `_read_secrets` already
        # applied §4's precedence, so a key the environment declares never appears.
        #
        # `overrides` now holds live credentials. It is applied to `Settings` and dropped;
        # nothing logs it, nothing serializes it, and `ConfigFieldOut` cannot carry one
        # because `managed_fields()` excludes every credential-shaped key by name.
        overrides.update(secrets.values)
        if secrets.unreadable:
            # A row exists and no configured KEK opens it. The platform keeps running on
            # whatever the environment or the previous snapshot gave it — but an operator
            # has to know, because the symptom otherwise presents as "the vendor is
            # rejecting our key" and sends them to the wrong system entirely.
            alert(
                "CORE_LOGIC",
                "platform_secret_unreadable",
                detail=(
                    "Stored credentials could not be decrypted with this deployment's "
                    "PLATFORM_KEK. Put the outgoing key in PLATFORM_KEK_RETIRED if this "
                    "follows a rotation."
                ),
                keys=",".join(secrets.unreadable),
            )
        apply_platform_overrides(overrides)
        _snapshot = ConfigSnapshot(
            version=version,
            overrides=overrides,
            loaded_at=time.monotonic(),
            degraded=False,
        )
        log.info(
            "platform_config_loaded",
            extra={"config_version": version, "override_count": len(overrides)},
        )
        return _snapshot


async def _poll_forever() -> None:
    # Refresh FIRST, then sleep: a process that has just started is the one most likely
    # to be running on defaults, and making it wait a full interval before its first
    # read would put every deploy through `_POLL_INTERVAL_S` of stale config for no
    # reason. `refresh` never raises, so this loop cannot die.
    while True:
        await refresh()
        await asyncio.sleep(_POLL_INTERVAL_S)


def start_config_refresher() -> None:
    """Begin polling in this process. Idempotent — call it from any lifespan, once or ten
    times.

    THIS IS THE WHOLE ADOPTION SURFACE. A deployable that calls it picks up console
    changes within `_POLL_INTERVAL_S`; one that does not runs on env + defaults, exactly
    as it does today. That is what keeps voice-runtime's adoption a one-line change
    (hard rule 3 forbids putting anything else on its request path) and what lets the
    pilot CLI opt in without inheriting a background task it does not want.

    The first refresh happens INSIDE the loop rather than being awaited here: this is
    called during app startup, and blocking the boot of the latency-critical service on
    a database read is the opposite of the fail-safe direction chosen above. The task
    reference is held in a module global, so it cannot be garbage-collected mid-flight.
    """
    global _refresher
    if _refresher is not None and not _refresher.done():
        return
    _refresher = asyncio.get_event_loop().create_task(_poll_forever())


async def stop_config_refresher() -> None:
    """Cancel the poll. For shutdown and for tests that must not leak a task."""
    global _refresher
    if _refresher is None:
        return
    _refresher.cancel()
    with suppress(asyncio.CancelledError):
        await _refresher
    _refresher = None


def reset_for_test() -> None:
    """Drop the snapshot and the override layer. Test seam, named as one."""
    global _snapshot
    _snapshot = ConfigSnapshot(
        version=_UNKNOWN_VERSION, overrides={}, loaded_at=None, degraded=False
    )
    apply_platform_overrides({})


# --- the console's view -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StoredRow:
    """One `platform_settings` row's provenance, as the console shows it."""

    updated_by: str | None
    updated_at: str | None
    note: str | None


def describe(
    settings: Settings,
    *,
    rows: Mapping[str, StoredRow] | None = None,
    snap: ConfigSnapshot | None = None,
) -> list[ConfigField]:
    """Every managed key with its value, its SOURCE and whether it can be edited.

    The source is computed from the same two facts the RESOLUTION uses — does the
    environment declare it, and did the store contribute it — so the console can never
    be told a key is editable while the layer is refusing to apply it. That symmetry is
    the whole point of §8's read-only-with-the-reason rule.

    `value` is read off the `Settings` object the caller passes rather than recomputed
    from the layers, so what the console displays is literally what this process is
    using. A key whose row exists but whose value failed re-validation therefore shows
    its EFFECTIVE value (the env/default one) with `source: "default"` — which is the
    truth, and is what an operator needs to see when a row has gone bad.

    `rows` carries provenance and is optional: the ops route passes it (it has a
    session), and a caller that only wants values and sources need not open one.
    """
    current = snap or snapshot()
    environ = effective_env()
    provenance = rows or {}
    fields: list[ConfigField] = []
    for key in managed_fields():
        info = Settings.model_fields[key]
        adapter = _adapter(key)
        from_env = env_declares(key, environ)
        source = "env" if from_env else "db" if key in current.overrides else "default"
        # A REQUIRED field has no code default to fall back to, and `PydanticUndefined`
        # is not a value that can be serialized or shown. It reports `None`, and
        # `has_default` is what the console and the revert route read instead of
        # guessing from a null — `null` is a legitimate default for every optional
        # field here, so the two are not the same fact.
        default = None if info.is_required() else info.get_default(call_default_factory=True)
        kind, options = _kind_of(key)
        stored = provenance.get(key) if source == "db" else None
        restart = APPLIES_ON_RESTART.get(key)
        fields.append(
            ConfigField(
                key=key,
                env_var=env_var_for(key),
                value=adapter.dump_python(getattr(settings, key), mode="json"),
                source=source,
                has_default=not info.is_required(),
                default=(None if default is None else adapter.dump_python(default, mode="json")),
                kind=kind,
                options=options,
                editable=not from_env,
                applies="on_restart" if restart else "live",
                caveat=restart or APPLIES_WITH_FOLLOW_UP.get(key),
                updated_by=stored.updated_by if stored else None,
                updated_at=stored.updated_at if stored else None,
                note=stored.note if stored else None,
            )
        )
    return fields


__all__ = [
    "APPLIES_ON_RESTART",
    "APPLIES_WITH_FOLLOW_UP",
    "ConfigField",
    "ConfigSnapshot",
    "StoredRow",
    "describe",
    "is_secret_key",
    "managed_fields",
    "project",
    "publish_version",
    "refresh",
    "reset_for_test",
    "snapshot",
    "start_config_refresher",
    "stop_config_refresher",
    "typed_value",
    "validate_value",
]
