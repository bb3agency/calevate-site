"""APP_ENV must be STATED. A deployment that forgets it must not run.

The defect this file pins: `Settings.app_env` defaulted to `"local"`, and `"local"` is
the one value under which `core/auth.py::_verify_dev_token` accepts
`dev:<realm>:<clerk_user_id>` — a credential whose SUBJECT THE CALLER CHOOSES, i.e.
"sign in as any admin you can name". The same branch is what makes
`runtime_config_missing_keys` skip its Clerk-key checks, so `/healthz/ready` reported a
healthy service while doing it. One variable nobody set turned off the authentication
AND the alarm, and produced no signal anywhere that it had happened.

So the property under test is not "dev tokens are refused in prod" —
`authz_audit_test.py` already owns that, and it always passed, because it MONKEYPATCHES
`app_env` to a stated value. The property here is the one that made that test's
guarantee vacuous in the real world: **the environment cannot be arrived at by
accident.** Every test below is written against the environment a forgetful deploy
actually has, not against a Settings object someone built by hand.
"""

from __future__ import annotations

import pytest
from apps.api.core import auth as auth_module
from apps.api.core.settings import (
    BOOTSTRAP_REQUIRED,
    ENVIRONMENTS,
    BootstrapError,
    runtime_config_missing_keys,
    validate_bootstrap_env,
)
from calevate_shared.config import Settings
from pydantic import ValidationError

# What a production host injects from the secrets manager. Everything a real deploy
# would have EXCEPT the one line this defect is about.
FORGETFUL_PROD_ENV: dict[str, str] = {
    "DATABASE_URL": "postgresql+psycopg://calevate_app:x@db.internal:5432/calevate",
    "REDIS_URL": "redis://redis.internal:6379/0",
    "OBJECT_STORE_ENDPOINT": "https://blr1.digitaloceanspaces.com",
    "OBJECT_STORE_BUCKET": "calevate-prod",
    "CLERK_ADMIN_SECRET_KEY": "",
    "CLERK_CLIENT_SECRET_KEY": "",
}


def _settings_kwargs() -> dict[str, str]:
    return {key.lower(): value for key, value in FORGETFUL_PROD_ENV.items() if value}


# --------------------------------------------------------------- the type refuses


def test_a_config_that_never_names_its_environment_cannot_be_built(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The core assertion, and the one that fails the moment the default comes back.

    `_env_file=None` and a deleted `APP_ENV` between them describe a process whose
    entire configuration is the dict above — which is what a container gets. If
    `Settings` can be constructed from it, the resulting `app_env` is `"local"`, and
    everything downstream of that (dev tokens accepted, Clerk keys unchecked, readiness
    green) follows without anyone choosing it.
    """
    monkeypatch.delenv("APP_ENV", raising=False)
    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None, **_settings_kwargs())  # type: ignore[arg-type]
    assert "app_env" in str(exc.value)


def test_the_same_config_with_the_environment_stated_builds_fine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The control. Requiring the variable must cost a correct deployment nothing —
    otherwise the test above is passing for the wrong reason."""
    monkeypatch.delenv("APP_ENV", raising=False)
    settings = Settings(_env_file=None, app_env="prod", **_settings_kwargs())  # type: ignore[arg-type]
    assert settings.app_env == "prod"


def test_app_env_has_no_default_of_any_kind() -> None:
    """Stated as a property of the FIELD, not of one construction path.

    `Settings` reads `.env` as well as the process environment, and a future source
    (a secrets-manager provider, a settings customisation) could supply a value the
    tests above happen to route around. A required field has no fallback to route to.
    """
    field = Settings.model_fields["app_env"]
    assert field.is_required(), "app_env must have no default — see config.py's comment"


# --------------------------------------------------------------- the gate refuses


def test_the_boot_gate_names_app_env_and_tells_the_operator_what_to_set() -> None:
    """A ValidationError for one field among forty, at 3am, is not an interface.

    BACKEND-PATTERNS §2 step 1 exists to turn it into a sentence, so the sentence is
    asserted: the variable, the allowed values, and why it is not optional.
    """
    with pytest.raises(BootstrapError) as exc:
        validate_bootstrap_env(dict(FORGETFUL_PROD_ENV))
    message = str(exc.value)
    assert "APP_ENV" in message
    for environment in ENVIRONMENTS:
        assert environment in message, f"the operator is not told {environment!r} is legal"


def test_a_typo_is_not_a_statement() -> None:
    """`APP_ENV=prd` passes a presence check and then dies in Pydantic — the traceback
    the gate exists to prevent. Checked where the message can name the allowed set."""
    with pytest.raises(BootstrapError, match="prd"):
        validate_bootstrap_env({**FORGETFUL_PROD_ENV, "APP_ENV": "prd"})


#: Values that are a legal environment with something invisible attached. A trailing
#: newline is the realistic one: `echo APP_ENV=prod >> .env`, a heredoc, a CI secret
#: pasted with a line break.
PADDED_ENVIRONMENTS = ("local ", " prod", "prod\n", "\tstaging")


@pytest.mark.parametrize("value", PADDED_ENVIRONMENTS)
def test_the_gate_refuses_what_pydantic_will_refuse(value: str) -> None:
    """The gate's answer must be the same answer the type gives, or the gate is theatre.

    MEASURED BEFORE THE FIX: `APP_ENV='local '` PASSED `validate_bootstrap_env` — it
    compared `env.get("APP_ENV", "").strip()` — and then `Settings()` raised
    `ValidationError`, because pydantic does not strip. So the one gate whose entire job
    is converting that ValidationError into a sentence waved the value through and let
    the process die in the traceback it exists to prevent, one invisible character in.

    It fails CLOSED either way, which is why this is a legibility defect rather than a
    security one — but the legibility IS the feature (BACKEND-PATTERNS §2 step 1), and
    the operator meeting it has just rolled out.

    Both halves are asserted together on purpose: a gate that refuses a value the type
    would ACCEPT would be the opposite failure and is just as much a defect.
    """
    with pytest.raises(BootstrapError) as raised:
        validate_bootstrap_env({**FORGETFUL_PROD_ENV, "APP_ENV": value})
    assert "whitespace" in str(raised.value), (
        "the message must name what is actually wrong — 'prod\\n' is not a typo, and "
        "telling the operator it is not a known environment sends them to re-read a "
        "word they spelled correctly"
    )
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env=value, **_settings_kwargs())  # type: ignore[arg-type]


@pytest.mark.parametrize("environment", ENVIRONMENTS)
def test_every_environment_the_type_allows_passes_the_gate(environment: str) -> None:
    """The gate reads its allowed set off the `Environment` Literal, so widening the
    type cannot leave the gate behind — and cannot lock out a legal value either."""
    validate_bootstrap_env({**FORGETFUL_PROD_ENV, "APP_ENV": environment})


def test_app_env_is_in_the_bootstrap_contract() -> None:
    assert "APP_ENV" in BOOTSTRAP_REQUIRED


# ------------------------------------------------- what the defect actually bought


def test_the_dev_token_path_is_reachable_only_from_a_stated_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole chain in one test, from the environment to the credential.

    `_verify_dev_token` accepts a caller-chosen subject when and only when `app_env ==
    "local"`. That was previously reachable with an EMPTY environment; it is now
    reachable only from a configuration in which somebody wrote `local`.
    """
    monkeypatch.delenv("APP_ENV", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **_settings_kwargs())  # type: ignore[arg-type]

    stated_local = Settings(_env_file=None, app_env="local", **_settings_kwargs())  # type: ignore[arg-type]
    monkeypatch.setattr(auth_module, "get_settings", lambda: stated_local)
    accepted = auth_module._verify_dev_token("dev:admin:anyone_at_all", "admin")
    assert accepted is not None and accepted.clerk_user_id == "anyone_at_all", (
        "the local dev path must keep working — the fix is about how 'local' is "
        "arrived at, not about removing it"
    )


def test_readiness_still_demands_the_clerk_keys_outside_local() -> None:
    """The alarm half of the pair.

    `runtime_config_missing_keys` skips the Clerk checks under `app_env == "local"`,
    which is correct — and was catastrophic only because `local` could be the answer
    nobody gave. Pinned here so the two halves stay coupled: if this branch is ever
    keyed on something other than a stated environment, this fails.
    """
    prod = Settings(_env_file=None, app_env="prod", **_settings_kwargs())  # type: ignore[arg-type]
    missing = runtime_config_missing_keys(prod)
    assert "CLERK_ADMIN_SECRET_KEY" in missing
    assert "CLERK_CLIENT_SECRET_KEY" in missing

    local = Settings(_env_file=None, app_env="local", **_settings_kwargs())  # type: ignore[arg-type]
    assert runtime_config_missing_keys(local) == []


# ------------------------------------------------------------- the parity guardrail


def test_env_parity_refuses_a_bootstrap_key_that_has_a_default() -> None:
    """The regression guard, exercised on the exact mistake it exists to catch.

    `check_env_parity` now asserts that everything the boot gate demands is a REQUIRED
    Settings field. Re-adding `app_env: Environment = "local"` therefore turns a CI
    guardrail red, rather than depending on a reviewer noticing a one-word diff.
    """
    from scripts import check_env_parity

    declared, _ = check_env_parity.example_keys(check_env_parity.REPO_ROOT / ".env.example")
    assert check_env_parity.bootstrap_contract_failures(declared) == []

    class _Field:
        default = "local"

        def is_required(self) -> bool:
            return False

    patched = dict(Settings.model_fields)
    patched["app_env"] = _Field()  # type: ignore[assignment]
    original = Settings.model_fields
    try:
        Settings.model_fields = patched  # type: ignore[misc]
        failures = check_env_parity.bootstrap_contract_failures(declared)
    finally:
        Settings.model_fields = original  # type: ignore[misc]
    assert any("APP_ENV" in failure and "default" in failure for failure in failures), failures
