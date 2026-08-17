"""Guardrail: .env.example ⟷ Settings parity, all THREE directions
(ENGINEERING-PRACTICES §2; fail-fast config doctrine, DEV-SETUP §4).

Every key in `.env.example` must be a Settings field, every Settings field must appear
in `.env.example` **or be managed in the ops console** — and every environment variable
the code actually READS must be a Settings field, or be in one of the three named
registries below with the reason it cannot be one.

THE SECOND DIRECTION LEARNED A NEW SOURCE OF TRUTH (PLATFORM-CONFIG §12). Before the
console existed, `.env.example` was the only place a key could be declared, so "in
Settings but not in the example" was always a documentation gap. It is not any more: a
key an operator sets at `admin.calevate.tech/ops` is DECLARED THERE, and requiring it in
the example as well would fail this guardrail the day the first key moves — with the
tempting fix being to weaken the guardrail. So a console-managed key is declared, and a
key that is in NEITHER place is still a failure, which is the half that was doing the
work all along.

The BOOTSTRAP SIX are exempt from that allowance in the other direction: they can never
be console-managed (§4), so they must be in `.env.example`, and `check_bootstrap_keys`
is what proves they stayed env-only.

That third direction is the one a worker slips through: a job that
calls `os.getenv("SOME_NEW_KEY")` is config that nobody documented, nobody validates at
boot, and that is simply absent in production until someone notices the feature is off.

A FOURTH direction, added after APP_ENV: a variable the BOOTSTRAP GATE demands must be
one the TYPE demands too. `Settings.app_env` defaulted to `"local"` while
`validate_bootstrap_env` said nothing about it, so a deploy that forgot the variable
booted happily into the one environment where the API accepts a dev token whose subject
the caller chooses. Two guards that should have caught each other, and neither did.
`bootstrap_contract_failures` below is what makes re-adding that default a red CI step
rather than a code review someone has to remember to do.

A FIFTH, for the same reason one step later (D-168): the DEPLOY PREFLIGHT
(`scripts/check_deploy_env.py`) refuses a deploy over the VALUES behind these keys, and
every key it can name must be one this file knows about. A preflight that refuses on
`REDIS_PASSWORD` — a variable this system does not have, inherited from the reference
implementation it was modelled on — would fail every correct deployment, and the tempting
fix would be to delete the check. `preflight_contract_failures` makes that impossible to
introduce quietly: the key set is one expression in one file, and this asks whether every
name in it is a `Settings` field or a registered exception.

Run: uv run python -m scripts.check_env_parity
"""

from __future__ import annotations

import ast
import re
import sys
from collections.abc import Iterator
from pathlib import Path

from calevate_shared.config import Settings

REPO_ROOT = Path(__file__).resolve().parent.parent
SEARCH_DIRS = ("apps", "packages", "scripts")
EXCLUDED_PARTS = ("__pycache__", "check_env_parity.py")

# Process/infra variables that are not application config: they are set by the runtime,
# the CI provider or the container, and have no business being a Settings field.
INFRA_ENV_KEYS: frozenset[str] = frozenset(
    {
        "CI",
        "PATH",
        "HOME",
        "PORT",
        "PYTHONPATH",
        "TZ",
        "GITHUB_SHA",
        "HOSTNAME",
    }
)

# Variables read by OPERATOR TOOLING that runs outside the application, with the reason.
#
# These are not application config: no deployable reads them, they never reach a request
# path, and putting them in `Settings` would make every process carry a field only a
# drill script uses — which is the opposite of what the fail-fast doctrine is for. They
# are listed rather than pattern-matched so that adding one is a visible diff.
DRILL_ENV_KEYS: dict[str, str] = {
    "DRILL_S3_ACCESS_KEY": (
        "scripts/restore_drill.py — the scratch bucket's access key, for the same reason "
        "and with the same scope as DRILL_S3_ENDPOINT below. A drill credential is not a "
        "platform credential: it reaches a scratch bucket an operator created for the "
        "drill, no deployable reads it, and it must not become a field every process "
        "carries."
    ),
    "DRILL_S3_SECRET_KEY": (
        "scripts/restore_drill.py — the scratch bucket's secret key. Same scope, same "
        "reasoning: operator tooling that runs outside every deployable, against a "
        "scratch bucket, and deliberately not reusing the application's own credentials."
    ),
    "DRILL_S3_ENDPOINT": (
        "scripts/restore_drill.py — the object-store endpoint the RESTORE DRILL reads "
        "from, as the default for its own `--s3-endpoint` flag. The drill runs against a "
        "scratch database and a scratch bucket, by an operator, outside every deployable; "
        "`Settings.object_store_endpoint` is the application's and is deliberately not "
        "reused, because a drill must be able to point somewhere the app cannot."
    ),
}

# Variables a THIRD-PARTY SDK resolves for itself, which our code may only observe.
#
# This is a different category from both sets above and the distinction is the whole
# justification. `DRILL_ENV_KEYS` are ours and simply out of scope; these are NOT OURS TO
# OWN. botocore reads these exact names out of the environment on every client build, and
# it will keep doing so whatever `Settings` says — so promoting one to a Settings field
# does not make it fail fast, it creates a SECOND value that the SDK ignores. A validated
# field the library never consults is strictly worse than an unvalidated one it does: the
# guardrail would go green while the actual behaviour moved somewhere nobody is looking.
#
# What replaces the fail-fast property, since it genuinely cannot apply here:
# `runtime_config_missing_keys` reports the two credentials by name at `/healthz/ready`
# outside `local`, and `scripts/vps-deploy.sh`'s preflight refuses a `.env` without them.
# Both check the environment, which is the thing botocore will actually read.
#
# NOTE ON COVERAGE: `_env_reads` only sees a literal string argument, so the two
# credentials — read through a tuple in `workers/storage._CREDENTIAL_ENV` and a generator
# in `core/settings.runtime_config_missing_keys` — are invisible to the scan and are
# listed anyway. A registry that recorded only what the AST happens to catch would read,
# to the next person, as though the others had never been considered.
SDK_ENV_KEYS: dict[str, str] = {
    "AWS_REGION": (
        "botocore's own region variable, passed through explicitly by "
        "`workers/storage._client` and `infra/object-lifecycle/apply_lifecycle._client` "
        "so both sign the SAME bucket for the same region. Optional: it defaults to "
        "`auto`, which is what Cloudflare R2 documents for its S3 API (DEPLOYMENT §1), "
        "so absence is the correct state on the production store and there is nothing "
        "for a boot gate to demand."
    ),
    "AWS_ACCESS_KEY_ID": (
        "Resolved by botocore itself — nothing in this repository passes credentials to "
        "boto3. Observed by `workers/storage._client_fingerprint`, so a rotated key "
        "yields a new client rather than a stale one, and by "
        "`runtime_config_missing_keys`, which is where a deployment missing it is told."
    ),
    "AWS_SECRET_ACCESS_KEY": (
        "The other half of the pair above, with the same owner and the same reason."
    ),
}

_KEY_RE = re.compile(r"^([A-Z][A-Z0-9_]*)=")
_ENV_READERS = ("getenv", "environ")


def example_keys(path: Path) -> tuple[set[str], list[str]]:
    """Keys declared in `.env.example`, plus any declared twice (the second wins
    silently when the file is sourced, so a duplicate is a real trap)."""
    seen: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _KEY_RE.match(line.strip())
        if match:
            seen.append(match.group(1).lower())
    duplicates = sorted({key for key in seen if seen.count(key) > 1})
    return set(seen), duplicates


def _env_reads(tree: ast.AST) -> Iterator[tuple[int, str]]:
    """`os.getenv("X")`, `os.environ["X"]`, `os.environ.get("X")` — the ways config
    gets read without going through Settings."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            receiver = getattr(func, "value", None)
            is_environ_get = (
                name == "get" and isinstance(receiver, ast.Attribute) and receiver.attr == "environ"
            )
            if name == "getenv" or is_environ_get:
                for arg in node.args[:1]:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        yield node.lineno, arg.value
        elif isinstance(node, ast.Subscript):
            value = node.value
            if isinstance(value, ast.Attribute) and value.attr == "environ":
                key = node.slice
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    yield node.lineno, key.value


def direct_env_reads(root: Path | None = None) -> dict[str, list[str]]:
    """key -> where it is read. Pure enough to test: point it at any tree."""
    root = root or REPO_ROOT
    found: dict[str, list[str]] = {}
    for directory in SEARCH_DIRS:
        for path in (root / directory).rglob("*.py"):
            if any(part in str(path) for part in EXCLUDED_PARTS):
                continue
            if not any(reader in path.read_text(encoding="utf-8") for reader in _ENV_READERS):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for lineno, key in _env_reads(tree):
                found.setdefault(key, []).append(f"{path.relative_to(root)}:{lineno}")
    return found


def bootstrap_contract_failures(declared: set[str]) -> list[str]:
    """Every `BOOTSTRAP_REQUIRED` key is a REQUIRED Settings field and is in the example.

    Two separate claims, and the pair is the point:

    - *required field* — the gate refusing to boot without a variable means nothing if
      the type quietly supplies one. `app_env: Environment = "local"` was exactly that:
      a fallback that is convenient locally and is unauthenticated admin in production.
      Anything the gate demands must have no default, so the two agree by construction
      instead of by coincidence.
    - *declared in `.env.example`* — a variable a developer cannot discover by copying
      the template is one every new machine and every new deployment fails on once,
      loudly, for no reason.
    """
    from apps.api.core.settings import BOOTSTRAP_REQUIRED

    failures: list[str] = []
    fields = Settings.model_fields
    for key in BOOTSTRAP_REQUIRED:
        name = key.lower()
        field = fields.get(name)
        if field is None:
            failures.append(
                f"{key} is in BOOTSTRAP_REQUIRED but is not a Settings field — the boot "
                "gate demands a variable nothing reads"
            )
            continue
        if not field.is_required():
            failures.append(
                f"{key} is in BOOTSTRAP_REQUIRED but Settings.{name} has a default "
                f"({field.default!r}) — the gate refuses to start without it and the "
                "type hands one out anyway, so a deployment that forgets it runs on the "
                "default. Drop the default (apps/api/core/settings.py explains why for "
                "APP_ENV) or take the key out of BOOTSTRAP_REQUIRED."
            )
        if name not in declared:
            failures.append(f"{key} is in BOOTSTRAP_REQUIRED but not in .env.example")
    return failures


def preflight_contract_failures(settings_fields: set[str]) -> list[str]:
    """Every key the DEPLOY PREFLIGHT can refuse on is config this deployment reads.

    `scripts/check_deploy_env.py` is the only guard in this repo that looks at a VALUE,
    and it runs where nobody is watching — inside the new image, mid-deploy. Its key set
    is therefore the one place where a name that means nothing here could sit unnoticed
    and either refuse every correct host or, worse, silently check nothing. The three
    object-store credentials are legitimately not `Settings` fields (botocore owns them —
    `SDK_ENV_KEYS` above carries the whole argument), so they are allowed by name and by
    that registry rather than by exception.
    """
    from scripts.check_deploy_env import (
        HMAC_SECRET_KEYS,
        OBJECT_STORE_CREDENTIALS,
        RETIRED_PAIRS,
        config_keys,
    )

    named = (
        config_keys()
        | set(HMAC_SECRET_KEYS)
        | {key for pair in RETIRED_PAIRS for key in pair}
        | OBJECT_STORE_CREDENTIALS
    )
    unknown = sorted(
        key
        for key in named
        if key.lower() not in settings_fields
        and key not in SDK_ENV_KEYS
        and key not in INFRA_ENV_KEYS
    )
    return [
        f"{key} can be refused by scripts/check_deploy_env but is not a Settings field "
        "and is in none of this file's registries — the deploy preflight is guarding a "
        "variable nothing reads, which fails a correct host and checks nothing on a "
        "broken one"
        for key in unknown
    ]


def console_managed() -> set[str]:
    """Keys an operator can set without an SSH session (PLATFORM-CONFIG §7).

    Imported from the modules that actually SERVE those surfaces, not re-listed: this
    check has to be asking "is it declared somewhere a person can find it", and a second
    copy of the managed set would answer a question about itself.
    """
    from apps.api.core.platform_config import managed_fields
    from apps.api.core.settings import ENV_ONLY_DISPLAY
    from apps.api.ops.secret_service import manageable_secret_keys

    # THREE surfaces. The third is not a loophole: `GET /v1/ops/config` renders every
    # `ENV_ONLY_DISPLAY` entry with its key, its ENVIRONMENT VARIABLE NAME, the reason it
    # cannot be edited here, and whether this host currently declares it — strictly more
    # than `.env.example` tells anybody, because it says both where the value goes and
    # whether it arrived.
    #
    # It matters now because `ENV_ONLY_KEYS` has a second category. The bootstrap six
    # cannot come from the store because the store cannot be READ without them;
    # `resend_api_key` can be, and must not be, because `scripts/host_alert.py` runs on
    # the database host with no database connection and can only read it from the
    # environment. Without this clause that key is undiscoverable to this check — which
    # is exactly what it reported.
    return set(managed_fields()) | set(manageable_secret_keys()) | set(ENV_ONLY_DISPLAY)


def evaluate(
    declared: set[str],
    settings_fields: set[str],
    reads: dict[str, list[str]],
    duplicates: list[str] | None = None,
    managed: set[str] | None = None,
) -> list[str]:
    failures: list[str] = []
    manageable = console_managed() if managed is None else managed
    only_example = sorted(declared - settings_fields)
    # A field is DECLARED if a person can find it: in the template, or on the console.
    # Anything in neither is config nobody can discover.
    only_settings = sorted(settings_fields - declared - manageable)
    if only_example:
        failures.append(f"in .env.example but not Settings: {only_example}")
    if only_settings:
        failures.append(
            f"in Settings, not in .env.example, and not manageable from the ops console: "
            f"{only_settings} — nobody can discover these"
        )
    for key in duplicates or []:
        failures.append(f"{key.upper()} is declared twice in .env.example")
    for key, sites in sorted(reads.items()):
        if (
            key in INFRA_ENV_KEYS
            or key in DRILL_ENV_KEYS
            or key in SDK_ENV_KEYS
            or key.lower() in settings_fields
        ):
            continue
        failures.append(
            f"{key} is read directly from the environment ({', '.join(sorted(sites))}) "
            "but is not a Settings field — config that never fails fast"
        )
    return failures


def main() -> int:
    declared, duplicates = example_keys(REPO_ROOT / ".env.example")
    settings_fields = set(Settings.model_fields)
    reads = direct_env_reads()

    failures = evaluate(declared, settings_fields, reads, duplicates)
    failures.extend(bootstrap_contract_failures(declared))
    failures.extend(preflight_contract_failures(settings_fields))
    if failures:
        print("ENV PARITY: FAIL")
        for failure in failures:
            print(f"  - {failure}")
        print(
            "\nA new key goes in BOTH .env.example and calevate_shared.config.Settings, "
            "and is read through Settings — never os.getenv (DEV-SETUP §4)."
        )
        return 1
    print(
        f"ENV PARITY: OK ({len(settings_fields)} keys aligned, "
        f"{len(reads)} direct environment reads accounted for)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
