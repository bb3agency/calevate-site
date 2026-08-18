"""The `.env` the DEPLOY DEMANDS must be one `Settings()` can load (D-188).

Three documents and one script agree that a production `.env` carries the bootstrap eight
PLUS the object-store credentials botocore resolves for itself:

  * `docs/DEPLOYMENT.md` §6 tier 1 — "the bootstrap eight, plus the object-store
    credentials botocore reads for itself", with the note that an operator who took the
    old "and nothing else" literally "got a platform that boots ... and cannot write one
    recording".
  * `scripts/vps-deploy.sh::preflight` — greps `.env` for `AWS_ACCESS_KEY_ID` and
    `AWS_SECRET_ACCESS_KEY` by name and ABORTS THE DEPLOY when either is absent.
  * `scripts/check_deploy_env.py` — validates them as `OBJECT_STORE_CREDENTIALS`.
  * `scripts/check_env_parity.py::SDK_ENV_KEYS` — records why they are not, and will
    never be, `Settings` fields.

And `Settings` sets `env_file=".env"` with `extra="forbid"`. pydantic-settings applies
`forbid` to keys read from the DOTENV FILE — unrelated `os.environ` entries are not
affected — so the exact file every one of those four demands was one `Settings()` refused
to construct, with three `extra_forbidden` errors, for any process whose working
directory is the deploy root.

WHY NOBODY HIT IT AND WHY IT STILL MATTERED. The three containers escaped by accident:
`.dockerignore` keeps `.env` out of the image, and compose's `env_file:` delivers the same
values as process environment, which `forbid` does not police. What did NOT escape is
`scripts/bootstrap_admin.py` — the ONLY way to create the first administrator (D-171), run
from the repo root on the VPS by design, with "the same environment `alembic upgrade head`
needs". On a host provisioned exactly as DEPLOYMENT §9 step 4 says, it died before it
reached the database, and the platform had no way in.

The two tests below are the two halves of the fix, and the second is why the fix is an
explicit allow-list rather than `extra="ignore"` or `dotenv_filtering="only_existing"`:
both of those would have made a MISSPELLED key silent, in a file operators hand-edit over
SSH at 3am.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from calevate_shared.config import SDK_OWNED_ENV_KEYS, Settings
from pydantic import ValidationError

#: A minimal, production-SHAPED `.env`: the bootstrap five that `BOOTSTRAP_REQUIRED`
#: names, plus the SDK keys the deploy refuses to proceed without. Values are inert
#: placeholders — this test is about which KEYS the file may contain, never about
#: reaching anything.
_DEPLOY_ENV = {
    "APP_ENV": "prod",
    "DATABASE_URL": "postgresql+psycopg://app:pw@host.docker.internal:5432/calevate",
    "ALEMBIC_DATABASE_URL": "postgresql+psycopg://owner:pw@host.docker.internal:5432/calevate",
    "REDIS_URL": "redis://redis:6379/0",
    "OBJECT_STORE_ENDPOINT": "https://account.r2.cloudflarestorage.com",
    "OBJECT_STORE_BUCKET": "calevate-prod",
    "AWS_ACCESS_KEY_ID": "placeholder-key-id",
    "AWS_SECRET_ACCESS_KEY": "placeholder-secret",
    "AWS_REGION": "auto",
}


@contextmanager
def _dotenv_only(contents: dict[str, str], tmp_path: Path) -> Iterator[None]:
    """Settings reads ONLY the written `.env`, never the developer's shell.

    `os.environ` is cleared rather than monkeypatched for the reason the sibling
    bootstrap-floor test gives: the process environment is layered ON TOP of the dotenv
    file and takes precedence, so a test that left it in place would be asking about the
    machine it runs on. Clearing it is also what makes this test able to fail — with
    `AWS_REGION` exported, the dotenv source is never the one that supplies it.
    """
    saved_environ = dict(os.environ)
    saved_cwd = Path.cwd()
    (tmp_path / ".env").write_text(
        "".join(f"{k}={v}\n" for k, v in contents.items()), encoding="utf-8"
    )
    try:
        os.chdir(tmp_path)
        os.environ.clear()
        yield
    finally:
        os.chdir(saved_cwd)
        os.environ.clear()
        os.environ.update(saved_environ)


def test_a_deployment_shaped_env_file_constructs_settings(tmp_path: Path) -> None:
    """The regression itself: `.env` with the SDK credentials in it must LOAD.

    Fails with three `extra_forbidden` errors before D-188, which is what made
    `scripts/bootstrap_admin.py` unrunnable on a correctly provisioned host.
    """
    with _dotenv_only(_DEPLOY_ENV, tmp_path):
        settings = Settings()
    assert settings.app_env == "prod"


def test_the_sdk_keys_do_not_become_settings_fields() -> None:
    """Dropped from the dotenv source, NOT adopted as configuration.

    botocore owns these three and reads them from the process environment itself
    (`check_env_parity.SDK_ENV_KEYS`). If a future edit "fixes" the load failure by
    declaring them as fields instead, this repo would have two owners for one credential
    and the console would offer to manage a value boto3 never asks it for.
    """
    fields = {name.upper() for name in Settings.model_fields}
    assert not (fields & SDK_OWNED_ENV_KEYS)


def test_a_misspelled_key_in_env_is_still_refused(tmp_path: Path) -> None:
    """The property the allow-list was chosen to KEEP.

    `extra="ignore"` and `dotenv_filtering="only_existing"` would each have made the fix a
    one-word change and would each have swallowed this: `DATABSE_URL` becomes silence, and
    the operator gets a process that starts against the wrong database. The refusal must
    still name the key, because that is the whole of the message.
    """
    with (
        _dotenv_only({**_DEPLOY_ENV, "DATABSE_URL": "postgresql+psycopg://x@y/z"}, tmp_path),
        pytest.raises(ValidationError) as caught,
    ):
        Settings()
    assert "databse_url" in str(caught.value)
