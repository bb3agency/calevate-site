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
    return missing


def fail_fast(message: str) -> None:
    """Unhandled-startup path: alert THEN exit, never swallow (§2 step 7)."""
    print(f"FATAL: {message}", file=sys.stderr, flush=True)
    raise SystemExit(1)


__all__ = [
    "BOOTSTRAP_REQUIRED",
    "ENVIRONMENTS",
    "BootstrapError",
    "fail_fast",
    "get_settings",
    "runtime_config_missing_keys",
    "validate_bootstrap_env",
]
