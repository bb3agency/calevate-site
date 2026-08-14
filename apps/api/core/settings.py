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
from functools import lru_cache
from pathlib import Path
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
BOOTSTRAP_REQUIRED = ("APP_ENV", "DATABASE_URL", "REDIS_URL")

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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # values come from env/.env


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
    if cfg.engine == "bolna" and not cfg.bolna_api_key:
        missing.append("BOLNA_API_KEY")
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
    "BOOTSTRAP_REQUIRED",
    "ENVIRONMENTS",
    "MIN_HMAC_KEY_BYTES",
    "BootstrapError",
    "fail_fast",
    "get_settings",
    "resolve_hmac_key",
    "runtime_config_missing_keys",
    "validate_bootstrap_env",
]
