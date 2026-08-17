"""Negative controls for the deploy preflight (`scripts/check_deploy_env.py`, D-168).

A CHECK THAT CANNOT FAIL IS WORSE THAN NO CHECK — it reports green and nobody asks why.
So every refusal the module declares has a row in `MUTATIONS` below that constructs the
bad environment and proves the refusal bites, and `test_every_declared_refusal_is_reachable`
fails if a code is ever added to `REFUSAL_CODES` without one. The assertions are on the
CODE, never on the prose: a control that matched a message would go green the day somebody
improved the wording, which is the day it stops being a control.

Each row is `(code, mutation)` where the mutation is applied to a KNOWN-GOOD production
environment — so every test also asserts, by construction, that the good environment does
not trip that refusal (`test_good_environment_is_accepted`).

No database, no Redis, no shared state: `evaluate` is pure and the entry point is driven
against a file in `tmp_path`.
"""

from __future__ import annotations

import base64
from collections.abc import Callable, Mapping

import pytest
from calevate_shared.config import Settings
from scripts.check_deploy_env import (
    REFUSAL_CODES,
    REFUSE,
    WARN,
    WARNING_CODES,
    Finding,
    evaluate,
    load_example,
    main,
    settings_constructible,
)

# Base64 of 32 bytes — the shape `core/envelope._decode_kek` demands. A fixed value, not
# `os.urandom`, so a failure is reproducible.
GOOD_KEK = base64.b64encode(b"kek-material-that-is-32-bytes-ok").decode()
OTHER_KEK = base64.b64encode(b"retired-material-also-32-byteslo").decode()
# 32 bytes each, and pairwise distinct — the property `distinct_secrets` is about.
GOOD_HMAC = "audit-chain-key-of-thirty-two-by"
OTHER_HMAC = "idempotency-key-of-thirty-two-by"


def good_env() -> dict[str, str]:
    """A production environment that is coherent in every way this module checks.

    Deliberately NOT a copy of `.env.example`: that file is the local template, and half
    the refusals below exist because copying it onto a host is the commonest way to get a
    deployment that boots and is wrong.
    """
    return {
        "APP_ENV": "prod",
        "DATABASE_URL": "postgresql+psycopg://calevate_app:pw-one@host.docker.internal:5432/calevate",
        "ALEMBIC_DATABASE_URL": "postgresql+psycopg://calevate:pw-two@host.docker.internal:5432/calevate",
        "REDIS_URL": "redis://redis:6379/0",
        "OBJECT_STORE_ENDPOINT": "https://account.r2.cloudflarestorage.com",
        "OBJECT_STORE_BUCKET": "calevate-prod",
        "PLATFORM_KEK": GOOD_KEK,
        "PLATFORM_KEK_RETIRED": "",
        "AWS_ACCESS_KEY_ID": "0123456789abcdef0123456789abcdef",
        "AWS_SECRET_ACCESS_KEY": "fedcba9876543210fedcba9876543210fedcba98",
    }


def refuse_codes(env: Mapping[str, str]) -> set[str]:
    return {f.code for f in evaluate(env, load_example()) if f.severity == REFUSE}


def _drop(key: str) -> Callable[[dict[str, str]], None]:
    def mutate(env: dict[str, str]) -> None:
        env.pop(key, None)

    return mutate


def _set(key: str, value: str) -> Callable[[dict[str, str]], None]:
    def mutate(env: dict[str, str]) -> None:
        env[key] = value

    return mutate


def _both(*mutations: Callable[[dict[str, str]], None]) -> Callable[[dict[str, str]], None]:
    def mutate(env: dict[str, str]) -> None:
        for one in mutations:
            one(env)

    return mutate


#: One row per declared refusal. The comment on each is the failure it prevents, in the
#: field, not a restatement of the code.
MUTATIONS: tuple[tuple[str, Callable[[dict[str, str]], None]], ...] = (
    # A deploy that forgot APP_ENV used to boot into the one environment that accepts a
    # dev token whose subject the caller chooses (D-49).
    ("bootstrap_gate", _drop("APP_ENV")),
    # `alembic/env.py` has no fallback to DATABASE_URL: migrations would run as the
    # unprivileged app role and die on the first CREATE POLICY.
    ("alembic_dsn_missing", _drop("ALEMBIC_DATABASE_URL")),
    ("dsn_unparseable", _set("ALEMBIC_DATABASE_URL", "calevate.db")),
    # Migrate one database, serve another: green deploy, missing table under load.
    (
        "dsn_database_mismatch",
        _set(
            "ALEMBIC_DATABASE_URL",
            "postgresql+psycopg://calevate:pw-two@host.docker.internal:5432/calevate_old",
        ),
    ),
    (
        "dsn_host_mismatch",
        _set(
            "ALEMBIC_DATABASE_URL",
            "postgresql+psycopg://calevate:pw-two@db.internal:5432/calevate",
        ),
    ),
    # One role for both means either migrations run unprivileged or every request runs as
    # the owner — hard rule 1's RLS rests on that separation.
    (
        "dsn_role_collision",
        _set(
            "ALEMBIC_DATABASE_URL",
            "postgresql+psycopg://calevate_app:pw-two@host.docker.internal:5432/calevate",
        ),
    ),
    # Postgres is on the HOST (D-26); a container's localhost is the container.
    (
        "dsn_host_unreachable_from_container",
        _set("DATABASE_URL", "postgresql+psycopg://calevate_app:pw-one@localhost:5432/calevate"),
    ),
    ("redis_url_unparseable", _set("REDIS_URL", "redis")),
    # Redis publishes no host port; localhost reaches nothing and every job stops.
    ("redis_host_unreachable_from_container", _set("REDIS_URL", "redis://127.0.0.1:6379/0")),
    # Not base64 of 32 bytes: every console-managed credential stays ciphertext.
    ("platform_kek_unusable", _set("PLATFORM_KEK", "not-a-key")),
    # A retired slot holding the active value is a rotation that never happened (D-86).
    ("retired_key_equals_active", _set("PLATFORM_KEK_RETIRED", GOOD_KEK)),
    ("hmac_key_too_short", _set("AUDIT_CHAIN_SECRET", "short")),
    # The refusal their JWT_SECRET/JWT_REFRESH_SECRET check is, in our key names.
    (
        "hmac_key_reused_across_purposes",
        _both(_set("AUDIT_CHAIN_SECRET", GOOD_HMAC), _set("IDEMPOTENCY_SCOPE_SECRET", GOOD_HMAC)),
    ),
    # Signing the tamper-evident ledger with a constant printed in this repository (D-81).
    ("audit_chain_secret_is_published_constant", _set("AUDIT_CHAIN_SECRET", "local-dev:prod")),
    # The bucket from `.env.example`: a copied template pointed at somebody's laptop.
    ("example_value_verbatim", _set("OBJECT_STORE_BUCKET", "calevate-dev")),
    ("placeholder_value", _set("SARVAM_API_KEY", "your-key-here")),
)


def test_good_environment_is_accepted() -> None:
    """The positive control. Without it every negative control below is satisfied by a
    module that refuses everything."""
    assert refuse_codes(good_env()) == set()


@pytest.mark.parametrize(("code", "mutate"), MUTATIONS, ids=[code for code, _ in MUTATIONS])
def test_refusal_bites(code: str, mutate: Callable[[dict[str, str]], None]) -> None:
    env = good_env()
    mutate(env)
    assert code in refuse_codes(env)


def test_every_declared_refusal_is_reachable() -> None:
    """`REFUSAL_CODES` is the module's own list of what it can refuse. A code with no row
    above is either dead or unreachable, and both look identical from the outside."""
    covered = {code for code, _ in MUTATIONS} | {"env_file_missing", "settings_unbuildable"}
    assert covered == REFUSAL_CODES


def test_a_type_valid_but_out_of_bounds_value_is_refused_before_the_swap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`DB_POOL_SIZE=500` is present, non-placeholder, and asks Postgres for 2000 backends
    against a `max_connections` of 200 (DEPLOYMENT §2a). It is a `Settings` bound, so it
    crash-loops every container — after the swap, unless something asks first.

    Also the hard-rule-6 control for THIS path: pydantic renders `input_value` in its own
    string form, so the finding is built from `loc` and `msg` and the offending value must
    not appear.
    """
    monkeypatch.setenv("DB_POOL_SIZE", "500")
    findings = settings_constructible()
    assert [f.code for f in findings] == ["settings_unbuildable"]
    assert "DB_POOL_SIZE" in findings[0].message
    assert "500" not in findings[0].message


def test_settings_constructible_is_quiet_on_a_working_environment() -> None:
    assert settings_constructible() == []


def test_every_declared_warning_is_reachable() -> None:
    """The same rule for the softer half. A warning nothing can emit is a line of
    documentation pretending to be a control."""
    emitted = {
        finding.code
        for env, example in (
            (good_env() | {"RAZORPAY_KEY_SECRET": "break-glass"}, load_example()),
            (good_env(), None),
        )
        for finding in evaluate(env, example)
        if finding.severity == WARN
    }
    assert emitted == WARNING_CODES


def test_two_secrets_that_must_differ_are_only_refused_when_both_are_set() -> None:
    """The retired slot is empty on every deployment that has never rotated, and that is
    the normal state — refusing it would refuse every host."""
    env = good_env()
    env["PLATFORM_KEK_RETIRED"] = OTHER_KEK
    assert "retired_key_equals_active" not in refuse_codes(env)


def test_distinct_hmac_keys_are_accepted() -> None:
    env = good_env()
    env["AUDIT_CHAIN_SECRET"] = GOOD_HMAC
    env["IDEMPOTENCY_SCOPE_SECRET"] = OTHER_HMAC
    assert refuse_codes(env) == set()


def test_absent_console_managed_secret_is_never_a_refusal() -> None:
    """Ours live encrypted in `platform_secrets` (D-95), so absence from the environment
    is what a CORRECT host looks like. This is the half of the reference implementation
    that deliberately did not transfer."""
    env = good_env()
    assert "SARVAM_API_KEY" not in env
    assert refuse_codes(env) == set()


def test_local_keeps_the_template_values() -> None:
    """The example's values ARE the correct local values — the verbatim scan must not fire
    on a developer's machine, or the check gets switched off."""
    example = load_example()
    assert example is not None
    codes = {f.code for f in evaluate(example, example) if f.severity == REFUSE}
    assert codes == set()


def test_placeholder_text_is_refused_even_locally() -> None:
    """Prompt text is a mistake in every environment, and the cheapest place to catch a
    class of error is the earliest one (D-49's lesson, one step earlier)."""
    example = load_example()
    assert example is not None
    env = dict(example) | {"COHERE_API_KEY": "<your-api-key>"}
    assert "placeholder_value" in {f.code for f in evaluate(env, example) if f.severity == REFUSE}


def test_console_managed_key_in_env_warns_and_does_not_refuse() -> None:
    """Pasting a key into `.env` is the documented break-glass (DEPLOYMENT §6), so it is a
    warning. What it costs — the console accepting a rotation the process ignores — is what
    the warning says."""
    env = good_env() | {"RAZORPAY_KEY_SECRET": "rzp-live-secret-value"}
    findings = evaluate(env, load_example())
    warned = [f for f in findings if f.severity == WARN and f.code == "console_managed_key_in_env"]
    assert [f.keys for f in warned] == [("RAZORPAY_KEY_SECRET",)]
    assert refuse_codes(env) == set()


def test_blank_console_managed_key_says_the_store_is_never_consulted() -> None:
    """`SARVAM_API_KEY=` is not "unset": pydantic hands the process an empty string and the
    console's value is never read (`core/settings.env_declares`)."""
    findings = evaluate(good_env() | {"SARVAM_API_KEY": ""}, load_example())
    blank = [f for f in findings if f.code == "console_managed_key_in_env"]
    assert len(blank) == 1
    assert "EMPTY" in blank[0].message


def test_bootstrap_keys_in_env_are_not_warned_about() -> None:
    """They are in the environment BY DESIGN (the bootstrap eight). A warning on those
    would train an operator to ignore the line that matters."""
    findings = evaluate(good_env(), load_example())
    assert [f for f in findings if f.severity == WARN] == []


def test_missing_example_file_is_a_warning_not_a_silent_skip() -> None:
    findings = evaluate(good_env(), None)
    assert "example_file_unreadable" in {f.code for f in findings}


def test_entry_point_fails_the_deploy_and_names_every_problem(
    tmp_path: object, capsys: pytest.CaptureFixture[str]
) -> None:
    """The deploy runs THIS, not `evaluate`. Two properties: a non-zero exit, and — the one
    that matters at 3am — every problem in one pass rather than one per deploy cycle."""
    from pathlib import Path

    assert isinstance(tmp_path, Path)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "APP_ENV=prod\n"
        "DATABASE_URL=postgresql+psycopg://calevate_app:pw@localhost:5432/calevate\n"
        "ALEMBIC_DATABASE_URL=postgresql+psycopg://calevate:pw@host.docker.internal:5432/other\n"
        "REDIS_URL=redis://localhost:6379/0\n"
        "OBJECT_STORE_ENDPOINT=http://localhost:9000\n"
        "OBJECT_STORE_BUCKET=calevate-dev\n"
        "PLATFORM_KEK=changeme\n",
        encoding="utf-8",
    )

    assert main(["--env-file", str(env_file)]) == 1
    out = capsys.readouterr().out
    for code in (
        "dsn_database_mismatch",
        "dsn_host_mismatch",
        "dsn_host_unreachable_from_container",
        "redis_host_unreachable_from_container",
        "platform_kek_unusable",
        "example_value_verbatim",
        "placeholder_value",
    ):
        assert code in out, f"{code} was not reported in the same pass"


def test_entry_point_accepts_a_good_file(
    tmp_path: object, capsys: pytest.CaptureFixture[str]
) -> None:
    from pathlib import Path

    assert isinstance(tmp_path, Path)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "".join(f"{key}={value}\n" for key, value in good_env().items()), encoding="utf-8"
    )
    assert main(["--env-file", str(env_file)]) == 0
    assert "DEPLOY ENV: OK" in capsys.readouterr().out


def test_a_missing_env_file_is_refused_by_name(
    tmp_path: object, capsys: pytest.CaptureFixture[str]
) -> None:
    from pathlib import Path

    assert isinstance(tmp_path, Path)
    assert main(["--env-file", str(tmp_path / "nope")]) == 1
    assert "env_file_missing" in capsys.readouterr().out


def test_no_secret_value_ever_reaches_the_output(
    tmp_path: object, capsys: pytest.CaptureFixture[str]
) -> None:
    """Hard rule 6. This output goes to a CI log, and half these keys are credentials —
    every message names KEYS and relationships, never a value."""
    from pathlib import Path

    assert isinstance(tmp_path, Path)
    secret = "SUPERSECRETVALUE-do-not-print"
    env_file = tmp_path / ".env"
    env_file.write_text(
        "".join(f"{key}={value}\n" for key, value in good_env().items())
        + f"AUDIT_CHAIN_SECRET={secret[:10]}\n"
        + f"IMPERSONATION_GRANT_SECRET={secret}\n"
        + f"IDEMPOTENCY_SCOPE_SECRET={secret}\n",
        encoding="utf-8",
    )
    assert main(["--env-file", str(env_file)]) == 1
    out = capsys.readouterr().out
    assert "hmac_key_reused_across_purposes" in out
    assert secret not in out
    assert secret[:10] not in out


def test_finding_renders_its_code_first() -> None:
    """The rendering is the interface an operator greps. Pinned so it stays greppable."""
    rendered = Finding("some_code", ("A_KEY",), "went wrong").render()
    assert rendered.startswith("[some_code] A_KEY: ")


# --- the contract with check_env_parity, and the control that proves it bites -----------


def test_the_parity_guardrail_accepts_this_gate_as_it_stands() -> None:
    from scripts.check_env_parity import preflight_contract_failures

    assert preflight_contract_failures(set(Settings.model_fields)) == []


def test_the_parity_guardrail_refuses_a_key_this_system_does_not_have(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The failure it exists for, made real.

    `HMAC_SECRET_KEYS` and `RETIRED_PAIRS` are literals — the one part of this gate's key
    set that is typed rather than derived — so they are where a name from the reference
    implementation (`JWT_REFRESH_SECRET`) could be copied in and then guard nothing. The
    check that catches it lives in `check_env_parity` because that file already owns "is
    this a variable anything reads"; this is the control proving it does.
    """
    import scripts.check_deploy_env as preflight
    from scripts.check_env_parity import preflight_contract_failures

    monkeypatch.setattr(preflight, "HMAC_SECRET_KEYS", ("JWT_REFRESH_SECRET",))
    failures = preflight_contract_failures(set(Settings.model_fields))
    assert len(failures) == 1
    assert "JWT_REFRESH_SECRET" in failures[0]
