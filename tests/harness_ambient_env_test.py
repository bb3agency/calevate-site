"""The test harness must not depend on credentials the machine happens to have.

WHY THIS FILE EXISTS. Two tests passed on every developer machine and failed in CI, and
both failed the same way: they asserted about an environment they had borrowed rather
than one they declared.

  * `platform_secrets_test.test_the_environment_still_wins_over_a_stored_credential`
    proved §4's precedence using `cohere_api_key` — because this repo's `.env` happened
    to carry `COHERE_API_KEY=`. CI has no `.env` at all, so nothing shadowed the key and
    the property it asserts never occurred.
  * `lead_dial_routes_test.test_a_recording_link_is_presigned_and_the_read_is_audited`
    needed botocore to find an access key. It found one in the developer's exported
    `AWS_*` or in `~/.aws`. CI has neither, so `presigned_url` returned None and the
    route correctly answered 502.

Nine consecutive CI runs were red on those two, and because every guardrail is a later
step in the same job, all twelve were reported `skipped` for two days. The individual
fixes are in those files; this one stops the CLASS.

HOW IT IS FIXED, and what was tried first. Grepping test sources for credential names
was the obvious check and it was thrown away: it flagged three files that merely NAME a
credential inside an assertion and caught neither real offender. A check that produces
only false positives is worse than none, because people learn to ignore it.

So the fix is structural instead — `tests/conftest._no_ambient_credentials` strips the
machine's `AWS_*` and redirects `HOME` for the whole session, which makes borrowing
impossible rather than detectable. A test that needs a credential declares it with
`mock.patch.dict(os.environ, ...)`, which is now the only way to have one and puts the
dependency in the test that has it.

This file is the proof that the strip is installed and effective, plus the two structural
facts that keep local and CI the same shape: no committed `.env`, and `.env.example` held
to the bootstrap set (D-95 cut it to eight).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# The one list, imported rather than restated: a second copy here would drift from the
# fixture that does the stripping, and a guard that disagrees with the thing it guards
# is worse than none.
from tests.conftest import AMBIENT_CREDENTIALS

REPO = Path(__file__).resolve().parents[1]
TESTS = REPO / "tests"


def test_the_repo_ships_no_env_file() -> None:
    """A committed `.env` would make every ambient-credential bug permanent and
    invisible: the harness would find the same values everywhere, including CI, and the
    divergence that catches these mistakes would disappear. `.env.example` is the
    contract; `.env` is local and gitignored."""
    tracked = (REPO / ".env").exists() and not _is_ignored(".env")
    assert not tracked, ".env must stay untracked — see this module's docstring"


def test_env_example_is_the_bootstrap_set_only() -> None:
    """D-95 cut the template to the keys a process cannot boot without. If it grows
    back, the harness starts finding values again on a fresh clone and stops matching
    CI — which is exactly the divergence that hid two failures for nine commits."""
    keys = _declared_keys(REPO / ".env.example")
    assert len(keys) <= 8, (
        f".env.example declares {len(keys)} keys; the bootstrap floor is 8 "
        "(PLATFORM-CONFIG §4 plus the two required object-store fields). Everything "
        f"else belongs in the ops console: {sorted(keys)}"
    )


def test_the_suite_cannot_see_the_machines_credentials() -> None:
    """The strip is INSTALLED and EFFECTIVE.

    A grep over test sources was tried first and thrown away: it flagged three files
    that merely name a credential in an assertion and caught neither real offender. So
    `tests/conftest._no_ambient_credentials` removes the values instead, and this is the
    proof that it ran — without it, a test could borrow a credential again and nothing
    would notice until CI, where the guardrails would be skipped by the failure.
    """
    for name in AMBIENT_CREDENTIALS:
        assert name not in os.environ, (
            f"{name} is visible to the suite — the strip in tests/conftest.py is not "
            "installed, and a test can silently depend on this machine again"
        )


def test_the_home_directory_hides_no_aws_profile() -> None:
    """botocore reads `~/.aws/credentials` and `~/.aws/config`, so stripping the
    environment alone would leave a profile the environment no longer names — which is
    exactly how the presign test found a key on this machine and none in CI."""
    assert not (Path(os.environ["HOME"]) / ".aws").exists(), (
        "HOME still resolves an ~/.aws profile; botocore will find it and the suite "
        "stops matching CI"
    )


def test_the_ambient_credentials_list_names_real_variables() -> None:
    """A typo in the list above protects nothing, and would do it silently. Every entry
    must be a variable some part of the tree actually reads — either a `Settings` field
    or one of botocore's documented names."""
    from apps.api.core.settings import Settings

    # botocore's own documented environment names. They are not `Settings` fields and
    # never will be — the app does not read them, the SDK does, which is precisely why
    # they can be picked up off a machine without any of our code mentioning them.
    botocore_names = {
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_PROFILE",
    }
    fields = {name.upper() for name in Settings.model_fields}
    for credential in AMBIENT_CREDENTIALS:
        assert credential in fields or credential in botocore_names, (
            f"{credential} is neither a Settings field nor a botocore variable — "
            "a name nothing reads guards nothing"
        )


def _declared_keys(path: Path) -> set[str]:
    keys: set[str] = set()
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = re.match(r"^([A-Z0-9_]+)=", stripped)
        if match:
            keys.add(match.group(1))
    return keys


def _is_ignored(relative: str) -> bool:
    """`.gitignore` membership, read rather than shelled out for — this test must not
    need a git binary to answer a question about a file."""
    ignore = REPO / ".gitignore"
    if not ignore.exists():
        return False
    patterns = {
        line.strip().lstrip("/")
        for line in ignore.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }
    return relative in patterns or os.path.basename(relative) in patterns


def test_the_strip_reaches_the_vendor_keys_a_dev_env_file_carries() -> None:
    """The widening, and the door it closes (`.env`, not an exported variable).

    `AMBIENT_CREDENTIALS` was written for shell-exported names; `_no_ambient_credentials`
    now also strips `engine.all_credential_env_keys()`. That matters because pydantic
    reads this repo's `.env` into the same `os.environ` the strip clears, so a developer
    holding a real `BOLNA_API_KEY` — which is the normal state of a machine doing vendor
    work — was running a suite in which two tests asserting a key is ABSENT could not
    pass. Same class as the `COHERE_API_KEY` case above, one layer wider.

    Asserted against the DERIVED list rather than a literal, so a fourth engine's key is
    covered here the moment its adapter declares one.
    """
    from apps.api.engine import all_credential_env_keys

    keys = all_credential_env_keys()
    assert keys, "no engine declares a credential key — this assertion would be vacuous"
    for name in keys:
        assert name not in os.environ, (
            f"{name} is visible to the suite. Two readiness tests assert this key is "
            "ABSENT, so a machine holding one runs a different suite from CI"
        )


def test_every_engine_in_the_literal_has_an_entry_in_the_derived_list() -> None:
    """The exhaustiveness check inside `all_credential_env_keys` actually fires.

    It raises rather than returning a short tuple, because a silently-missing engine is a
    key that stops being stripped with nothing going red. This calls it to prove the
    raise is not sitting behind an unreachable branch.
    """
    from typing import get_args

    from apps.api.engine import all_credential_env_keys
    from calevate_shared.config import EngineName

    all_credential_env_keys()  # raises AssertionError if an engine has no entry
    assert len(get_args(EngineName)) >= 3, "the Literal shrank — re-read the mapping"
