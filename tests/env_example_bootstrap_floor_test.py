"""`.env.example` is exactly the set a process needs to BOOT (PLATFORM-CONFIG §4, D-95).

The reduction from 58 keys to 8 is only safe if the 8 that remain are, precisely, the
ones without which nothing can start. Two claims, and the pair is the point:

- **sufficient** — copying `.env.example` gives you a `Settings` that constructs. A
  developer who clones the repo, copies the template and gets a process that will not
  start has been handed a broken README; a developer who gets a process that starts with
  a silently wrong value has been handed something worse.
- **minimal** — no key in it could have been left to the console. Every 7-key subset
  must FAIL, which is what turns "these eight are the floor" from a claim in a comment
  into a property a test can lose.

**Why this reads the real file rather than a hardcoded list.** The subject under test IS
`.env.example`; a copy of its keys here would let the two drift and would answer a
question about itself. `check_env_parity` already owns the other direction (every key is
a `Settings` field, every field is discoverable somewhere), so this file owns only the
boot property, which no guardrail could see: parity is about DECLARATION, and this is
about whether `Settings()` returns.

**Why `_settings_env` clears `os.environ` and chdirs.** `Settings` has
`env_file=".env"`, resolved against the CWD, and pydantic-settings layers the process
environment on top. A test that skipped either would be reading the developer's own
machine and would pass on a box with a full `.env` no matter what the template said —
the exact false green this file exists to prevent.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from calevate_shared.config import Settings
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_EXAMPLE = REPO_ROOT / ".env.example"

#: A value for every key, so the test proves "the KEY is missing" and never "the value
#: was empty". `.env.example` ships several keys blank on purpose (PLATFORM_KEK), and an
#: empty string is a legitimate value for those — only ABSENCE is the condition here.
_PLACEHOLDER: dict[str, str] = {
    "APP_ENV": "local",
    "DATABASE_URL": "postgresql+psycopg://calevate_app:x@localhost:5433/calevate",
    "ALEMBIC_DATABASE_URL": "postgresql+psycopg://calevate:x@localhost:5433/calevate",
    "REDIS_URL": "redis://localhost:6380/5",
    "OBJECT_STORE_ENDPOINT": "http://localhost:9000",
    "OBJECT_STORE_BUCKET": "calevate-dev",
}

#: The subset whose ABSENCE `Settings` itself refuses. Derived from the model rather
#: than re-listed, so a future field that gains or loses its default moves this set with
#: it instead of quietly falling out of the minimality proof below.
_TYPE_REQUIRED: list[str] = sorted(
    name.upper() for name, field in Settings.model_fields.items() if field.is_required()
)


def declared_keys() -> list[str]:
    """The KEY= lines of `.env.example`, read through the guardrail's own parser so the
    two cannot disagree about what counts as a declaration."""
    from scripts.check_env_parity import example_keys

    declared, duplicates = example_keys(ENV_EXAMPLE)
    assert duplicates == [], f"declared twice: {duplicates}"
    return sorted(key.upper() for key in declared)


@contextmanager
def _settings_env(env: dict[str, str], tmp_path: Path) -> Iterator[None]:
    """Run with EXACTLY `env` visible to pydantic-settings, from a directory with no
    `.env` in it. No monkeypatch fixture: this has to clear variables the fixture never
    set (the developer's own shell), which is a whole-environment swap, not a patch."""
    saved_environ = dict(os.environ)
    saved_cwd = Path.cwd()
    try:
        os.chdir(tmp_path)
        os.environ.clear()
        os.environ.update(env)
        yield
    finally:
        os.chdir(saved_cwd)
        os.environ.clear()
        os.environ.update(saved_environ)


def test_the_template_is_the_bootstrap_set_and_nothing_else() -> None:
    """The number is in the spec, so it is checkable (§4 states 6; the floor is 8 and
    the file says why). A key added here without a boot reason fails this first."""
    assert declared_keys() == [
        "ALEMBIC_DATABASE_URL",
        "APP_ENV",
        "DATABASE_URL",
        "OBJECT_STORE_BUCKET",
        "OBJECT_STORE_ENDPOINT",
        "PLATFORM_KEK",
        "PLATFORM_KEK_RETIRED",
        "REDIS_URL",
    ]


def test_every_declared_key_has_a_placeholder_or_ships_blank() -> None:
    """Guards the guard: a key added to the template with no entry in `_PLACEHOLDER`
    would be silently supplied as `""` below, and the minimality test would then be
    proving something about empty strings instead of about absence."""
    from scripts.check_env_parity import example_keys

    blank_in_template = {
        line.split("=", 1)[0]
        for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
        if line.strip().endswith("=") and "=" in line and not line.startswith("#")
    }
    unexplained = set(declared_keys()) - set(_PLACEHOLDER) - blank_in_template
    assert not unexplained, f"no placeholder and not blank in the template: {sorted(unexplained)}"
    _ = example_keys  # the parser above is the one this file trusts


def test_copying_the_template_gives_a_process_that_boots(tmp_path: Path) -> None:
    """SUFFICIENT. The whole point of the file: clone, copy, run."""
    env = {key: _PLACEHOLDER.get(key, "") for key in declared_keys()}
    with _settings_env(env, tmp_path):
        settings = Settings()
    assert settings.app_env == "local"
    # Read back two values that come from DIFFERENT sources, so the assertion covers the
    # layering and not just construction: one supplied above, one code default.
    assert settings.object_store_bucket == "calevate-dev"
    assert settings.engine == "fake"


@pytest.mark.parametrize("dropped", _TYPE_REQUIRED)
def test_dropping_a_type_required_key_refuses_by_name(dropped: str, tmp_path: Path) -> None:
    """MINIMAL, for the five keys the TYPE demands. Absence must be refused, and the
    refusal must name the key — an operator reading a 60-field traceback at 3am needs
    the variable's name in it, which is what `validate_bootstrap_env` upgrades to a
    sentence for the three keys it covers.

    OBJECT_STORE_ENDPOINT and OBJECT_STORE_BUCKET are in this list and NOT in
    `BOOTSTRAP_REQUIRED`, which is why the floor is 8 and not 6: they are required by
    the type, so `Settings()` cannot construct without them, so no process can reach the
    store that manages them. Their refusal today is a Pydantic ValidationError rather
    than the named sentence — recorded in `.env.example` as a finding for whoever owns
    the boot gate, and asserted below so this file notices if that changes.
    """
    env = {key: _PLACEHOLDER.get(key, "") for key in declared_keys() if key != dropped}
    with _settings_env(env, tmp_path), pytest.raises(ValidationError) as caught:
        Settings()
    assert dropped.lower() in str(caught.value)


def test_the_three_type_optional_keys_are_declared_for_reasons_the_type_cannot_see(
    tmp_path: Path,
) -> None:
    """PLATFORM_KEK, PLATFORM_KEK_RETIRED and ALEMBIC_DATABASE_URL are in the template
    but are not type-required, and each asymmetry is deliberate rather than an oversight:

    - the two KEK variables are a derived constant locally (§3) and REFUSE AT USE in
      staging/prod, so requiring them at construction would break every local process to
      restate a rule the crypto layer already enforces;
    - `ALEMBIC_DATABASE_URL` is consumed by `alembic/env.py`, not by any deployable, so
      the type could not demand it without every uvicorn worker carrying the migration
      role's DSN.

    Asserting it here stops a future reader from "fixing" the parametrize list above to
    include them and finding the test red for a reason nobody wrote down.
    """
    optional = [key for key in declared_keys() if key not in _TYPE_REQUIRED]
    assert optional == ["ALEMBIC_DATABASE_URL", "PLATFORM_KEK", "PLATFORM_KEK_RETIRED"]
    env = {key: _PLACEHOLDER.get(key, "") for key in declared_keys() if key not in optional}
    with _settings_env(env, tmp_path):
        settings = Settings()
    assert settings.platform_kek in (None, "")
    assert settings.alembic_database_url is None


def test_everything_the_template_dropped_is_manageable_from_the_console() -> None:
    """The claim the header of `.env.example` makes to its reader — "moved, not deleted"
    — checked against the modules that actually SERVE those surfaces. This is what makes
    the reduction reversible knowledge rather than a diff someone has to trust.
    """
    from apps.api.core.platform_config import managed_fields
    from apps.api.core.settings import ENV_ONLY_DISPLAY
    from apps.api.ops.secret_service import manageable_secret_keys

    # THREE surfaces, not two. `ENV_ONLY_DISPLAY` is the third and it is a genuine
    # discovery surface rather than a loophole: `GET /v1/ops/config` renders every entry
    # with its key, its ENVIRONMENT VARIABLE NAME, the reason it cannot be edited here,
    # and whether this host currently declares it. That is strictly more than
    # `.env.example` tells anybody — it says where the value goes AND whether it arrived.
    #
    # It exists because `ENV_ONLY_KEYS` grew a second category: the bootstrap six (which
    # cannot come from the store because the store cannot be read without them) and
    # `resend_api_key` (which must not, because the alert relay on the database host
    # reaches no store at all). A key in the second category is undiscoverable if this
    # test only knows about the first two surfaces — which is exactly what it caught.
    manageable = set(managed_fields()) | set(manageable_secret_keys()) | set(ENV_ONLY_DISPLAY)
    declared = {key.lower() for key in declared_keys()}
    orphans = set(Settings.model_fields) - declared - manageable
    assert not orphans, (
        f"config nobody can discover: {sorted(orphans)} — not in .env.example, not "
        "offered by either console surface, and not explained as env-only"
    )
