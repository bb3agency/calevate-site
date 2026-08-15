"""Process-wide Settings accessor + the bootstrap-env validation gate.

BACKEND-PATTERNS §2 locks the order: (1) bootstrap-env validation on the
DATABASE_URL/REDIS_URL class only — fail fast, with a message an operator can act on
— then (2) the full tenant-safe config load. Doing it in that order means a missing
DSN produces "DATABASE_URL is not set" rather than a Pydantic traceback listing every
optional model key.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import get_args

from calevate_shared.config import Environment, Settings
from dotenv import dotenv_values

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger

log = get_logger(__name__)

# The values `APP_ENV` may take, read off the type rather than re-listed here: one
# source of truth, so widening the Literal cannot leave this gate behind.
ENVIRONMENTS: tuple[str, ...] = get_args(Environment)

# Variables that must be present BEFORE anything else runs.
#
# DATABASE_URL/REDIS_URL are here for the reason in the module docstring: a missing DSN
# should produce a sentence, not a traceback.
#
# APP_ENV is here for a different and larger reason. `Settings.app_env` used to default
# to `"local"`, which is the only value under which `_verify_dev_token` accepts
# `dev:<realm>:<clerk_user_id>` — a credential whose subject the caller picks — and
# `runtime_config_missing_keys` skips its Clerk checks under the same branch, so
# `/healthz/ready` still said "ready". A production deploy that simply forgot the
# variable was therefore unauthenticated AND silent about it.
#
# WHY THE BOOTSTRAP GATE AND NOT ONLY THE TYPE. Dropping the default (which we also
# did) already makes `Settings()` raise, so the process cannot serve traffic without
# APP_ENV either way. What the gate adds is the MESSAGE: Pydantic's ValidationError for
# a missing required field arrives as `1 validation error for Settings / app_env /
# Field required`, in a config class with ~40 fields, at 3am, to someone who has just
# rolled out. Step 1 of the locked bootstrap order exists precisely to convert that
# into "APP_ENV is not set; set it to local|staging|prod". Errors are part of the
# interface (CLAUDE.md) — including the interface an operator meets.
# The object-store pair is here for a MECHANICAL reason rather than a §4 one: both are
# type-required `Settings` fields with no default, so their absence already stops the
# process — the only question is whether it stops with a sentence or with a raw
# `pydantic_core.ValidationError` traceback out of `create_app`. Converting the second
# into the first is the entire job of this gate, and leaving them out meant two of the
# eight variables in `.env.example` were the two that failed least legibly.
BOOTSTRAP_REQUIRED = (
    "APP_ENV",
    "DATABASE_URL",
    "REDIS_URL",
    "OBJECT_STORE_ENDPOINT",
    "OBJECT_STORE_BUCKET",
)

# Repo root: apps/api/core/settings.py -> apps/api/core -> apps/api -> apps -> root
_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


def _effective_env() -> dict[str, str]:
    """The environment the app will ACTUALLY see.

    Pydantic Settings reads `.env` as well as the process environment, so a bootstrap
    gate that only looked at `os.environ` would reject a perfectly valid local setup —
    and would do it before the app exists, with no way to see why. Same sources, same
    precedence (process environment wins).
    """
    merged: dict[str, str] = {}
    if _ENV_FILE.exists():
        merged.update({k: v for k, v in dotenv_values(_ENV_FILE).items() if v is not None})
    merged.update(os.environ)
    return merged


class BootstrapError(RuntimeError):
    """Raised before the app exists — there is nothing to serve a problem+json with."""


def validate_bootstrap_env(environ: dict[str, str] | None = None) -> None:
    env = environ if environ is not None else _effective_env()
    missing = [key for key in BOOTSTRAP_REQUIRED if not env.get(key)]
    if missing:
        raise BootstrapError(
            f"Missing required environment: {', '.join(missing)}. "
            + (
                f"APP_ENV must be STATED, never inferred — set it to one of "
                f"{'|'.join(ENVIRONMENTS)}. A deployment that does not say which "
                "environment it is in used to be treated as 'local', where the API "
                "accepts a dev token whose subject the caller chooses. "
                if "APP_ENV" in missing
                else ""
            )
            + "Copy .env.example to .env for local work; in prod these are injected "
            "from the secrets manager at deploy time (DEV-SETUP §4)."
        )
    # A typo is not a statement. `APP_ENV=prd` would pass the presence check above and
    # then fail in Pydantic — the traceback this gate exists to avoid — so the value is
    # checked here, where the message can name the allowed set.
    # `.get`, not `[...]`: presence is guaranteed by the check above only for as long as
    # APP_ENV stays in BOOTSTRAP_REQUIRED, and a KeyError escaping the gate whose whole
    # job is producing a readable failure would be a poor way to learn that it moved.
    stated = env.get("APP_ENV", "").strip()
    if stated not in ENVIRONMENTS:
        raise BootstrapError(
            f"APP_ENV is {stated!r}, which is not an environment this build knows. "
            f"Set it to one of {'|'.join(ENVIRONMENTS)} (DEV-SETUP §4)."
        )


# PLATFORM-CONFIG §4's BOOTSTRAP SET, as Settings field names. These six may NEVER
# resolve from `platform_settings`, and the enforcement lives here — in the one function
# that can put a store value into a `Settings` object — rather than at each call site,
# because a rule every reader has to remember is a rule the seventh key breaks.
#
# Each one, with the reason it cannot move (§4):
#   app_env               decides whether dev tokens are accepted (D-49). Reading it
#                         from the database means the DATABASE decides the security
#                         posture, which is the inversion the guardrail exists to catch.
#   database_url          it is how you reach the store.
#   alembic_database_url  migrations run before the store is guaranteed to exist.
#   platform_kek          it is the key that opens the store.
#   platform_kek_retired  same.
#   redis_url             needed by workers before settings resolve.
#
# The CI guardrail that enforces this list against future edits is `check_bootstrap_keys`
# (PLATFORM-CONFIG §13 phase 6); this constant is what it reads.
#: The same six as DATA, so the console can SHOW them.
#:
#: They are absent from `GET /v1/ops/config` by construction — `managed_fields()` never
#: offers them — and absence is not an explanation. An operator looking for `APP_ENV`
#: found nothing and had no way to tell "this build does not have it" from "this one
#: cannot be changed here". These reasons are what the console renders instead: the key
#: exists, it is real, it is env-only, and here is why. NO VALUE IS EVER PUBLISHED WITH
#: THEM — two of the six are the credentials that open the credential store.
BOOTSTRAP_REASONS: dict[str, str] = {
    "app_env": (
        "it decides whether dev tokens are accepted (D-49). Reading it from the store "
        "would let the DATABASE decide this deployment's security posture."
    ),
    "database_url": "it is how you reach the store.",
    "alembic_database_url": "migrations run before the store is guaranteed to exist.",
    "platform_kek": (
        "it is the key that opens the credential store. A database holding both the "
        "lock and the key is encryption as theatre."
    ),
    "platform_kek_retired": "same — it unwraps DEKs written under the previous KEK.",
    "redis_url": "workers need it before settings resolve.",
}

ENV_ONLY_KEYS: frozenset[str] = frozenset(BOOTSTRAP_REASONS)

# Values resolved from `platform_settings` and layered UNDER the environment.
#
# Module state rather than a parameter because `get_settings()` has ~200 call sites and
# threading a snapshot through all of them would be the change this design exists to
# avoid: the store is meant to reach every process without a code change, so the ONE
# accessor grows the layer instead of every caller learning a second one.
# `core/platform_config.py` owns the IO that fills it; this module owns nothing but the
# holder, so the dependency runs one way (platform_config -> settings) and there is no
# import cycle.
_platform_overrides: dict[str, object] = {}


def platform_overrides() -> Mapping[str, object]:
    """What the store is currently contributing. Read-only view, for reporting."""
    return MappingProxyType(_platform_overrides)


def apply_platform_overrides(values: Mapping[str, object]) -> None:
    """Install the store's contribution and invalidate the cached `Settings`.

    ENVIRONMENT ALWAYS WINS, and it wins in two places rather than one. The caller
    (`platform_config._resolve`) never offers a key the environment declares, so the
    normal path never reaches the filter below; the filter is here anyway because this
    is the only door into the process's effective configuration, and a door with a lock
    on the outside only is not locked. What it refuses unconditionally is §4's bootstrap
    set — the keys whose relocation would be a security-posture inversion.

    Idempotent and cheap: it replaces the mapping and clears one `lru_cache`. The next
    `get_settings()` rebuilds `Settings()` from the environment and re-applies the layer,
    so a value that was reverted in the console disappears rather than lingering.
    """
    global _platform_overrides
    refused = sorted(set(values) & ENV_ONLY_KEYS)
    if refused:
        # Never silently dropped: reaching here means something upstream tried to move a
        # bootstrap key into the store, which is exactly the change CI is meant to stop.
        log.error("platform_override_refused", extra={"keys": ",".join(refused)})
    _platform_overrides = {k: v for k, v in values.items() if k not in ENV_ONLY_KEYS}
    # The real cache, not the accessor's compatibility handle: this is the one place
    # that must not go through a shim, because a refresh that failed to invalidate would
    # leave the fleet reporting a change it never applied.
    #
    # A PIN OPENED BEFORE THIS CALL DELIBERATELY SURVIVES IT. `settings_scope()` holds a
    # `Settings` OBJECT, not a cache slot, so a request already in flight keeps the
    # configuration it started with even though the process has moved on. That is the
    # in-flight guarantee, and it is a consequence of holding the object rather than a
    # second mechanism to keep in step.
    _current_settings.cache_clear()


@lru_cache(maxsize=1)
def _current_settings() -> Settings:
    """The process's settings as of the last refresh. The unpinned answer.

    `lru_cache`d and O(1) with no IO, which is what keeps `get_settings()` legal on
    voice-runtime's request path (hard rule 3): the store's contribution arrives through
    `apply_platform_overrides`, off the request path, and this function only ever reads
    a dict that is already in memory.

    `model_copy(update=...)` rather than re-validating: every value in the layer was
    validated against THIS model's own field definition before it was stored
    (`platform_config.validate_value`) and again when the snapshot was built, so a third
    validation here would be a third place for the rules to differ. `Settings()` itself
    is re-run on each rebuild, so an environment variable that changed under the process
    is picked up at the same moment a store value is.
    """
    base = Settings()  # values come from env/.env
    return base.model_copy(update=dict(_platform_overrides)) if _platform_overrides else base


#: The `Settings` pinned for the unit of work running on this task, if any.
#:
#: A `ContextVar` rather than a parameter for the reason the override layer is module
#: state: `get_settings()` has ~200 call sites and threading a snapshot through them is
#: the change this whole design exists to avoid. A ContextVar is inherited by tasks
#: spawned inside the scope and is invisible to everything outside it, which is exactly
#: the shape a per-request pin needs.
_pinned: ContextVar[Settings | None] = ContextVar("calevate_pinned_settings", default=None)


@contextmanager
def settings_scope() -> Iterator[Settings]:
    """Resolve settings ONCE for this unit of work, and hold that answer to the end.

    THE PROBLEM THIS SOLVES, in the founder's words: "changing the core things and env
    keys might require restart ... and if any calls are happening in that moment they
    will fail". The console makes a change land in every process within ~5 seconds with
    no restart, which is the good half. The bad half is what "within 5 seconds" means to
    work that is ALREADY RUNNING: without a pin, a request that reads `get_settings()`
    twice can read the OLD value the first time and the NEW value the second, because a
    background refresh landed between them. The snapshot swap itself is atomic — a
    single `get_settings()` never returns a half-applied `Settings` — but a unit of work
    is not a single read, and "atomic per read" is not the property anyone needs.

    Two keys that must agree are where this becomes a defect rather than a curiosity: a
    rate and its ceiling, a provider and its credential, `usd_inr_rate` and the price it
    is converting. Half-applied is a wrong number in `usage_events`, not a stale one.

    So: one resolution per request, per job, per tick. Entering is one ContextVar set;
    leaving is one reset. Nested scopes REUSE the outer pin rather than re-resolving —
    an inner unit of work is part of the outer one, and re-resolving would reintroduce
    exactly the straddle this prevents.

    WHAT IS DELIBERATELY *NOT* PINNED, because it must be live-immediate: the big red
    switch and the load-shed mode. They are not `Settings` fields at all — they live in
    `platform_state` and are read through `core/loadshed`, whose TTL is bounded well
    under one dispatch tick. That separation is the design, stated: anything that must
    take effect mid-flight is not configuration, it is STATE, and it goes in the table
    the halt lives in. Everything reachable from `Settings` is pinned for the duration of
    the work that read it.
    """
    existing = _pinned.get()
    if existing is not None:
        yield existing
        return
    token = _pinned.set(_current_settings())
    try:
        yield _pinned.get() or _current_settings()
    finally:
        _pinned.reset(token)


def get_settings() -> Settings:
    """This process's EFFECTIVE settings: `os.environ`/.env → `platform_settings` → code
    default (PLATFORM-CONFIG §4's resolution order, minus the refusal, which belongs to
    whoever consumes a missing value).

    Inside a `settings_scope()` this returns the object pinned when that scope opened,
    so a unit of work cannot straddle a config refresh. Outside one — a script, a test,
    module import — it returns the current answer, which is what it has always done.
    Still O(1) and still IO-free either way (hard rule 3).
    """
    return _pinned.get() or _current_settings()


#: `get_settings.cache_clear()` still works, because thirteen call sites in four test
#: files and one fixture already spell it that way and `get_settings` is no longer the
#: `lru_cache` itself.
#:
#: A COMPATIBILITY HANDLE, NOT A SECOND CACHE. It forwards to `_current_settings`, which
#: is the only cache there is — rewriting those call sites to name a private function, or
#: publishing a second clearing verb, would be the "two ways to do one thing" the repo
#: treats as a defect even when both work. `apply_platform_overrides` deliberately does
#: NOT go through here: the one caller that must never be wrong should not depend on a
#: shim staying attached.
#:
#: `cache_info` is deliberately NOT forwarded: nothing in this repo calls it, and a shim
#: nobody uses is a maintenance cost pretending to be an API.
get_settings.cache_clear = _current_settings.cache_clear  # type: ignore[attr-defined]


def effective_env() -> Mapping[str, str]:
    """The environment the app ACTUALLY sees — process environment over `.env`.

    Published because "did this key come from the environment?" is not answerable from a
    `Settings` object: pydantic-settings records the resolved VALUE, not its source, and
    a value that happens to equal the code default may still have been set explicitly.
    The console has to render an env-sourced key as read-only WITH the reason, so the
    question has to have an answer, and it has to have the same answer pydantic would
    give — hence the same merged view the bootstrap gate uses.
    """
    return _effective_env()


def env_var_for(field: str) -> str:
    """The environment variable name for a `Settings` field.

    `Settings` sets no `env_prefix`, so pydantic-settings looks up the field name
    case-insensitively; upper-case is the spelling `.env.example` and every deploy uses.
    One function so the console, the refusal messages and the source resolution cannot
    disagree about what to tell an operator to set.
    """
    return field.upper()


def env_declares(field: str, environ: Mapping[str, str] | None = None) -> bool:
    """Does the environment set this field? — case-insensitively, like pydantic.

    An EMPTY value counts as declared, deliberately: `SARVAM_API_KEY=` in `.env` is a
    statement that this deployment has no Sarvam key, and pydantic will hand `Settings`
    the empty string rather than falling through to the store. Reporting it as `default`
    and letting the console offer to edit it would produce a field whose value is
    ignored — the exact defect §8 names ("a field that silently does nothing is worse
    than no field").
    """
    env = environ if environ is not None else _effective_env()
    wanted = field.lower()
    return any(name.lower() == wanted for name in env)


#: The floor, in BYTES, for every HMAC key this deployment signs with.
#:
#: 32 is the SHA-256 output size, and three independent authorities land on or under it,
#: so one constant serves every call site rather than each growing its own number:
#:
#:   - RFC 2104 §3 (HMAC itself): a key shorter than L bytes — L being the hash output
#:     length, 32 for SHA-256 — "is strongly discouraged as it would decrease the
#:     security strength of the function". This is the citation that governs the raw
#:     HMAC uses (the audit chain, idempotency fingerprints).
#:   - NIST SP 800-107 Rev. 1 §5.3.4: "The length of the HMAC key shall be at least 128
#:     bits" — an absolute floor, comfortably under 32 bytes. (Rev. 1 is being withdrawn
#:     in favour of SP 800-224, which carries the same 128-bit minimum.)
#:   - RFC 7518 §3.2: an HS256 key must be at least the hash size. This is the citation
#:     `core/impersonation.py` was written against, and it is the strictest of the
#:     three, which is why the number is 32 and not 16.
MIN_HMAC_KEY_BYTES = 32


def resolve_hmac_key(
    secret: str | None,
    *,
    env_var: str,
    purpose: str,
    code: str,
    title: str,
    local_fallback: str,
    app_env: str,
) -> bytes:
    """The HMAC key for one purpose, or a refusal an operator can act on.

    ONE resolver, because this repo now holds three HMAC secrets that each have to make
    the same three decisions — configured, too short, absent — and three copies of that
    ladder is where the fourth one gets it wrong. `core/impersonation.py` reasoned the
    policy out first; this is that policy, extracted rather than re-derived, so a change
    to the floor moves every key at once.

    LENGTH IS PART OF BEING CONFIGURED. A present-but-short secret is refused with the
    SAME code as an absent one, because to a caller they are one condition: "there is no
    usable key here". Failing closed on absence while silently accepting a weak key
    would leave the refusal guarding the easier half of one mistake — an operator who
    pastes a short string into the secrets manager gets a key an attacker can search,
    and the only signal is a log line nobody reads.

    THE LOCAL FALLBACK IS SCOPED TO `local`, and the scoping is the whole point. A
    fallback that applies in every environment is not a development convenience, it is a
    production key with a development name: it ships in the repository, so anybody can
    compute it. Under `local` it buys an offline dev box; anywhere else its absence is
    an outage, which is loud, recoverable and visible at `/healthz/ready` before an
    operator finds out by clicking something.

    Callers pass `app_env` rather than having it read here so this stays a pure function
    of its arguments — the caller has already loaded settings, and a second read would
    be a second thing to keep consistent under test.
    """
    if secret:
        if len(secret.encode()) < MIN_HMAC_KEY_BYTES:
            # Not logged with the secret, obviously, and not with its length as a
            # searchable field beyond the byte count an operator needs to fix it.
            log.error("hmac_key_too_short", extra={"env_var": env_var, "app_env": app_env})
            raise ProblemError(
                kind="dependency",
                code=code,
                title=title,
                detail=f"This deployment's HMAC key for {purpose} is too short.",
                remediation=(
                    f"{env_var} must be at least {MIN_HMAC_KEY_BYTES} bytes "
                    "(RFC 2104 §3; NIST SP 800-107 Rev. 1 §5.3.4); inject a longer one "
                    "from the secrets manager (DEV-SETUP §4)."
                ),
            )
        return secret.encode()
    if app_env != "local":
        log.error("hmac_key_missing", extra={"env_var": env_var, "app_env": app_env})
        raise ProblemError(
            kind="dependency",
            code=code,
            title=title,
            detail=f"This deployment has no HMAC key for {purpose}.",
            remediation=f"Inject {env_var} from the secrets manager (DEV-SETUP §4).",
        )
    return local_fallback.encode()


def runtime_config_missing_keys(settings: Settings | None = None) -> list[str]:
    """Keys that are optional at BOOT but required to actually serve traffic.

    Workers boot tolerantly (§2): a missing provider key must not crash-loop every
    queue. Completeness is enforced here, and `/healthz/ready` is the go-live gate.

    WHAT READINESS DOES WHEN THE ENVIRONMENT IS UNSTATED: it never has to answer,
    because a process in that state does not exist. "A service that cannot say what
    environment it is in is not ready" is the right rule, and the strongest way to
    honour it is to make the state unreachable rather than reportable — `app_env` has
    no default and no `None` in its type, so `Settings()` cannot be built without it
    and `validate_bootstrap_env` refuses before that. Returning `["APP_ENV"]` from here
    instead would have been strictly weaker: the process would already be listening,
    serving `/v1/*` under whatever `app_env` guess it had made, while one endpoint
    reported 503. The gate belongs at boot; this function is for keys that are
    legitimately absent at boot and required to serve.
    """
    cfg = settings or get_settings()
    missing: list[str] = []
    # The engine layer answers for its own vendors (D-104). This was
    # `if cfg.engine == "bolna" and not cfg.bolna_api_key` — one vendor, hardcoded here —
    # so `/healthz/ready` was GREEN on a credential-less `ENGINE=cartesia` deployment: a
    # box that cannot place one call, reporting itself fit for traffic. Imported inside
    # the function because `apps.api.engine` imports this module; the same idiom
    # `capabilities._selected_engine` uses.
    from apps.api.engine import missing_engine_credential_keys

    missing.extend(missing_engine_credential_keys(cfg))
    if cfg.app_env != "local":
        # The canonical D-36 stack is all-Sarvam; Gemini is a configurable fallback,
        # so its absence is not a readiness failure.
        if not cfg.sarvam_api_key:
            missing.append("SARVAM_API_KEY")
        if not cfg.clerk_client_secret_key:
            missing.append("CLERK_CLIENT_SECRET_KEY")
        if not cfg.clerk_admin_secret_key:
            missing.append("CLERK_ADMIN_SECRET_KEY")
        # D-22 view-as signs its grants with this and REFUSES to mint or verify without
        # it outside `local` (`core/impersonation.py::_signing_key`). Reported here so a
        # deploy that forgot it is a red readiness probe, not an operator discovering
        # that "view as client" 502s on the day a client's dashboard looks wrong.
        if not cfg.impersonation_grant_secret:
            missing.append("IMPERSONATION_GRANT_SECRET")
        # The audit chain signs with this and REFUSES to write or verify without it
        # outside `local` (`compliance/audit.py::_active_key`). It used to fall back to
        # `local-dev:{app_env}` everywhere, so a deploy that forgot it produced a
        # tamper-evident ledger keyed on a constant printed in this repository —
        # unverifiable as evidence and, since every audited action writes one, a
        # condition an operator must meet BEFORE the deploy takes traffic rather than
        # discover from the first 503 on a raw-transcript read (hard rule 5).
        if not cfg.audit_chain_secret:
            missing.append("AUDIT_CHAIN_SECRET")
        # Its own key since the audit chain's was split off it — same refusal, different
        # blast radius: without it every idempotent mutation (call-this-lead, campaign
        # launch, KB publish) 503s rather than storing a fingerprint anybody can
        # recompute. AUDIT_CHAIN_SECRET_RETIRED is deliberately NOT here: it is a
        # verification aid, absent on every deployment that has never rotated.
        if not cfg.idempotency_scope_secret:
            missing.append("IDEMPOTENCY_SCOPE_SECRET")
    return missing


def fail_fast(message: str) -> None:
    """Unhandled-startup path: alert THEN exit, never swallow (§2 step 7)."""
    print(f"FATAL: {message}", file=sys.stderr, flush=True)
    raise SystemExit(1)


__all__ = [
    "BOOTSTRAP_REASONS",
    "BOOTSTRAP_REQUIRED",
    "ENVIRONMENTS",
    "ENV_ONLY_KEYS",
    "MIN_HMAC_KEY_BYTES",
    "BootstrapError",
    "apply_platform_overrides",
    "effective_env",
    "env_declares",
    "env_var_for",
    "fail_fast",
    "get_settings",
    "platform_overrides",
    "resolve_hmac_key",
    "runtime_config_missing_keys",
    "settings_scope",
    "validate_bootstrap_env",
]
