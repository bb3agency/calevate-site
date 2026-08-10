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

from calevate_shared.config import Settings
from dotenv import dotenv_values

BOOTSTRAP_REQUIRED = ("DATABASE_URL", "REDIS_URL")

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
            "Copy .env.example to .env for local work; in prod these are injected "
            "from the secrets manager at deploy time (DEV-SETUP §4)."
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from env/.env


def runtime_config_missing_keys(settings: Settings | None = None) -> list[str]:
    """Keys that are optional at BOOT but required to actually serve traffic.

    Workers boot tolerantly (§2): a missing provider key must not crash-loop every
    queue. Completeness is enforced here, and `/healthz/ready` is the go-live gate.
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
    return missing


def fail_fast(message: str) -> None:
    """Unhandled-startup path: alert THEN exit, never swallow (§2 step 7)."""
    print(f"FATAL: {message}", file=sys.stderr, flush=True)
    raise SystemExit(1)


__all__ = [
    "BOOTSTRAP_REQUIRED",
    "BootstrapError",
    "fail_fast",
    "get_settings",
    "runtime_config_missing_keys",
    "validate_bootstrap_env",
]
