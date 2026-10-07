"""Preflight: refuse a bad deploy BEFORE it lands — the environment's VALUES.

Every other guard in this repo asks whether a key is DECLARED. This one is the only
thing that asks whether the value behind it is coherent, and it asks before migrations
run and before a single container is swapped.

WHERE IT SITS, because four guards already stand near it and none of them answers this
question (one way per problem — CLAUDE.md):

  `scripts/check_env_parity.py`   .env.example ⟷ Settings ⟷ direct `os.getenv` reads.
                                  A REPO-SHAPE check that runs in CI and never sees a
                                  real value; it cannot answer "is this DSN pointing at
                                  the database the migration will touch". It gained one
                                  clause for this file: `preflight_contract_failures`
                                  makes every key named below a real Settings field or a
                                  registered exception, so this gate cannot come to demand
                                  a variable nothing reads.
  `scripts/check_bootstrap_keys.py`  the §4 set may only resolve from the environment.
                                  A property of the CODE, not of a deployment.
  `validate_bootstrap_env()`      presence of the bootstrap five + APP_ENV's spelling +
                                  the published dev DB password. In-process, at boot, and
                                  it raises on the FIRST problem because its job is to
                                  convert a Pydantic traceback into one sentence. It is
                                  CALLED from here rather than re-implemented, and its
                                  refusal becomes one finding among the rest.
  `scripts/vps-deploy.sh::preflight`  presence, by `grep`, on the HOST, before the build.
                                  Deliberately left alone: it is the cheap refusal that
                                  saves a ten-minute serial build on a 4GB VPS, and the
                                  host has no Python at all (DEPLOYMENT §2). Presence is
                                  the only question answerable there; every question below
                                  needs the values, so the split is by WHEN it can be
                                  answered, not by two implementations of one check.

HOW IT IS RUN. `scripts/vps-deploy.sh::verify_bootstrap_env` runs it INSIDE THE NEW IMAGE
(`compose run --rm --no-deps --entrypoint python api -m scripts.check_deploy_env`), which
is the same reasoning that step already carried: what matters is what the process about to
serve traffic can read — `.env` as compose's `env_file` delivers it — not what the deploy
user happens to have exported. It runs before `run_migrations` and before any swap, so a
refusal costs a build and nothing else.

EVERY PROBLEM AT ONCE. An operator fixing a `.env` over SSH at 3am should get the whole
list, not one line per fifteen-minute deploy cycle. Findings accumulate; nothing raises.

NO VALUE IS EVER PRINTED. Every message names KEYS and the relationship between them.
Half of these keys are credentials and this output goes to a CI log (hard rule 6).

WHAT DELIBERATELY DOES NOT TRANSFER from the reference implementation this is modelled on
(`raghava-organics-site/backend/scripts/verify-client-bootstrap-env.mjs:62-86`,
docs/evidence/raghava-deploy-teardown.md §2):

  - `REDIS_URL` embedding `REDIS_PASSWORD`. We have no such variable and want none:
    `compose.prod.yml` publishes no host port for redis and it is reachable only from the
    compose network, so the control is network isolation. What DOES transfer is the other
    half of the same failure — a `REDIS_URL` that names a host the container cannot reach.
  - Half-configured vendor integrations (`PAYMENT_PROVIDER=razorpay` with no Razorpay
    keys). Theirs live in `.env`; ours live ENCRYPTED IN THE CONSOLE STORE (D-95), so a
    vendor key absent from the environment is the NORMAL state of a correct deployment and
    refusing on it would refuse every real host. That question belongs to
    `runtime_config_missing_keys` at `/healthz/ready`, which already owns it. The
    exception is a credential that is ENV-ONLY (`ENV_ONLY_REASONS`): the environment is
    its only home, so its absence is a fault this gate can see — `owned_runtime` refuses
    the carrier pair and the claim key on that ground.

Run:
    uv run python -m scripts.check_deploy_env                  # the process environment
    uv run python -m scripts.check_deploy_env --env-file .env  # a file, before placing it
"""

from __future__ import annotations

import argparse
import base64
import binascii
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import SplitResult, urlsplit

# `_LEGACY_KEY_TEMPLATE` is private and is imported anyway, deliberately: it is the exact
# string D-81 demoted to generation 0 of the audit key ring, and the only alternative is a
# second copy of a constant whose whole purpose is that it must never be signed with again.
# A guard that retyped it would go green the day the original changed.
from apps.api.compliance.audit import _LEGACY_KEY_TEMPLATE
from apps.api.core.envelope import _PUBLISHED_LOCAL_KEKS, build_ring
from apps.api.core.errors import ProblemError
from apps.api.core.platform_config import managed_fields
from apps.api.core.settings import (
    BOOTSTRAP_REQUIRED,
    ENVIRONMENTS,
    MIN_HMAC_KEY_BYTES,
    BootstrapError,
    effective_env,
    is_deployable_stream_base,
    is_public_callback_base,
    validate_bootstrap_env,
)
from apps.api.ops.secret_service import manageable_secret_keys
from apps.api.reliability.engine_intake_keys import build_intake_ring
from calevate_shared.carrier import MIN_CALLBACK_SECRET_CHARS, usable_callback_secret
from calevate_shared.config import (
    RETIRED_ENV_KEY_ERROR,
    SDK_OWNED_ENV_KEYS,
    Settings,
    retired_env_key_message,
    retired_env_keys_in,
)
from calevate_shared.worker_api import MIN_CALLER_CLAIM_KEY_BYTES, usable_caller_claim_key
from dotenv import dotenv_values
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_FILE = REPO_ROOT / ".env.example"

#: The object store's credentials. Not `Settings` fields and never will be — botocore
#: resolves these exact names for itself (`check_env_parity.SDK_ENV_KEYS` carries the full
#: argument) — but they are configuration this deployment reads, so a placeholder in one
#: is the same defect as a placeholder in any other key here.
#:
#: ALIASED, not restated (D-188). The same set is now load-bearing in `Settings` itself,
#: which must DROP these three from the `.env` it reads or refuse to construct at all, so
#: the set stopped being a fact about this gate and became a fact about the config layer.
#: Two spellings of it would let a fourth SDK key be added here and not there, which
#: reads as "the gate accepts it" and means "every repo-root process now crashes".
OBJECT_STORE_CREDENTIALS: frozenset[str] = SDK_OWNED_ENV_KEYS


def config_keys() -> frozenset[str]:
    """The environment variables this deployment READS.

    The scans below are scoped to this rather than to everything in the environment,
    because in the image they run against `os.environ`, which also carries PATH, HOSTNAME
    and PYTHONPATH — a placeholder sweep over those is a false-positive generator.
    `check_env_parity.preflight_contract_failures` asserts every name this gate can refuse
    on is a Settings field or a registered SDK key, so it can never come to demand a
    variable nothing reads.
    """
    return frozenset(name.upper() for name in Settings.model_fields) | OBJECT_STORE_CREDENTIALS


#: The three HMAC secrets, each signing for a DIFFERENT PURPOSE, and the purpose is why
#: they must differ. NIST SP 800-57 Part 1 Rev. 5 §5.2 asks for one key per purpose;
#: `calevate_shared/config.py` argues the split for these three specifically (the audit
#: chain is tamper-evidence, `idempotency_scope_secret` is a PSEUDONYMISATION key under
#: EDPS/AEPD's hashing guidance, `impersonation_grant_secret` is forgeable ACCESS to a
#: client's data). Reusing one across two of them collapses three blast radii into one and
#: welds three rotation schedules together — the same defect their
#: `JWT_REFRESH_SECRET === JWT_SECRET` refusal exists for, in our key names.
HMAC_SECRET_KEYS: tuple[str, ...] = (
    "AUDIT_CHAIN_SECRET",
    "IDEMPOTENCY_SCOPE_SECRET",
    "IMPERSONATION_GRANT_SECRET",
)

#: Pairs where the second is the RETIRED generation of the first (D-86's one rotation
#: story, reused rather than reinvented). Equal values mean the rotation did not happen.
RETIRED_PAIRS: tuple[tuple[str, str], ...] = (
    ("PLATFORM_KEK", "PLATFORM_KEK_RETIRED"),
    ("AUDIT_CHAIN_SECRET", "AUDIT_CHAIN_SECRET_RETIRED"),
    ("VOBIZ_CALLBACK_SECRET", "VOBIZ_CALLBACK_SECRET_RETIRED"),
    ("ENGINE_INTAKE_KEK", "ENGINE_INTAKE_KEK_RETIRED"),
)

#: What the owned runtime's carrier leg reads from this host's environment (`owned_runtime`).
#: The first four are env-only, so the environment is their only home; the last two are
#: console-managed and are checked only when the environment declares them, because a
#: declared value is the one that wins.
CARRIER_CLAIM_KEY = "CARRIER_CLAIM_SECRET"
CARRIER_CREDENTIAL_KEYS: tuple[str, ...] = ("VOBIZ_AUTH_ID", "VOBIZ_AUTH_TOKEN")
VOBIZ_CALLBACK_SECRET_KEY = "VOBIZ_CALLBACK_SECRET"
STREAM_BASE_KEY = "PIPECAT_STREAM_BASE_URL"
CALLBACK_BASE_KEY = "WEBHOOK_BASE_URL"
OWNED_RUNTIME_ENV_KEYS: tuple[str, ...] = (
    CARRIER_CLAIM_KEY,
    *CARRIER_CREDENTIAL_KEYS,
    VOBIZ_CALLBACK_SECRET_KEY,
    STREAM_BASE_KEY,
    CALLBACK_BASE_KEY,
)

#: Set per SERVICE in `compose.prod.yml`, on purpose: DEPLOYMENT §2a's connection budget is
#: arithmetic over the whole cluster, so the pool size cannot be one number in `.env`. It
#: is therefore an environment declaration of a console-managed key that is DELIBERATE, and
#: warning about it would train an operator to ignore the warning that is not.
COMPOSE_INJECTED: frozenset[str] = frozenset({"DB_POOL_SIZE"})

#: Hosts that resolve to the container itself. Every one of them is wrong in the compose
#: topology: Postgres runs on the HOST and is reached at `host.docker.internal` (D-26), and
#: redis is a compose service reached by service name (DEPLOYMENT §1, §6 tier 1). A DSN
#: naming one of these produces a deploy that swaps cleanly and then cannot open a
#: connection — the failure lands after the swap, which is the one place it must not.
LOOPBACK_HOSTS: frozenset[str] = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})

# Text that is a PROMPT rather than a value. Each pattern is here because it is what a
# template, a vendor's docs page or a half-finished paste actually leaves behind; the
# reason travels with the pattern so the refusal can say which one matched without ever
# echoing the value that matched it.
_PLACEHOLDER_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"change[ _-]?me", re.IGNORECASE), "the word 'changeme'"),
    (re.compile(r"replace[ _-]?(with|me|this)", re.IGNORECASE), "the words 'replace with'"),
    (
        re.compile(r"\byour[ _-]?(key|secret|token|password|api)", re.IGNORECASE),
        "prompt text of the 'your-key-here' shape",
    ),
    (re.compile(r"placeholder", re.IGNORECASE), "the word 'placeholder'"),
    (re.compile(r"^<.+>$"), "angle brackets wrapping the whole value"),
    (re.compile(r"x{5,}", re.IGNORECASE), "a run of five or more x's"),
    (re.compile(r"\b(todo|fixme|tbd)\b", re.IGNORECASE), "a TODO marker"),
    (
        re.compile(r"\bexample\.(com|org|net)\b", re.IGNORECASE),
        "an RFC 2606 reserved example domain",
    ),
)

REFUSE = "refuse"
WARN = "warn"


@dataclass(frozen=True, slots=True)
class Finding:
    """One reason, named. `code` is what tests assert on.

    A stable code rather than a message match, for the reason `billing/payments.py` gives
    for its reason codes: a negative control that asserted on prose would go green the day
    somebody improved the wording, which is the day it stops being a control at all.
    """

    code: str
    keys: tuple[str, ...]
    message: str
    severity: str = REFUSE

    def render(self) -> str:
        return f"[{self.code}] {', '.join(self.keys)}: {self.message}"


#: Every refusal this module can produce. Declared rather than discovered so
#: `tests/deploy_env_preflight_test.py` can assert that each one is REACHABLE — a refusal
#: no crafted environment can trigger is a check that cannot fail, which is worse than no
#: check (it reports green and nobody asks why).
REFUSAL_CODES: frozenset[str] = frozenset(
    {
        "bootstrap_gate",
        "alembic_dsn_missing",
        "dsn_unparseable",
        "dsn_database_mismatch",
        "dsn_host_mismatch",
        "dsn_role_collision",
        "dsn_host_unreachable_from_container",
        "redis_url_unparseable",
        "redis_host_unreachable_from_container",
        "platform_kek_unusable",
        "platform_kek_is_published_constant",
        "retired_key_equals_active",
        "hmac_key_too_short",
        "hmac_key_reused_across_purposes",
        "audit_chain_secret_is_published_constant",
        "example_value_verbatim",
        "placeholder_value",
        "retired_env_key",
        "carrier_claim_secret_unusable",
        "carrier_credentials_missing",
        "vobiz_callback_secret_unusable",
        "pipecat_stream_base_url_blank",
        "pipecat_stream_base_url_unusable",
        "webhook_base_url_not_public",
        "thinnest_api_key_missing",
        "thinnest_api_key_unusable",
        "thinnest_api_base_url_unusable",
        "engine_intake_kek_missing",
        "engine_intake_kek_unusable",
        "env_file_missing",
        "settings_unbuildable",
    }
)

WARNING_CODES: frozenset[str] = frozenset({"console_managed_key_in_env", "example_file_unreadable"})


# --- the environment under inspection -------------------------------------------------


def read_env_file(path: Path) -> dict[str, str]:
    """A `.env` as pydantic-settings would read it. `dotenv_values`, not a parser of our
    own: `apps/api/core/settings._effective_env` already reads `.env` that way, and a
    second parser is a second set of quoting rules to disagree about."""
    return {key: value for key, value in dotenv_values(path).items() if value is not None}


def _stated_env(env: Mapping[str, str]) -> str:
    """APP_ENV exactly as the process will see it. Never stripped, never defaulted —
    `validate_bootstrap_env` refuses a padded or unknown value and reports it as the
    bootstrap finding; everything below treats an unrecognised value as NOT local, so a
    typo can never turn the non-local checks off."""
    return env.get("APP_ENV", "")


def _present(env: Mapping[str, str], key: str) -> str:
    return (env.get(key) or "").strip()


def _split_dsn(raw: str) -> SplitResult | None:
    try:
        parts = urlsplit(raw)
        _ = parts.port  # raises on a non-numeric port
    except ValueError:
        return None
    return parts if parts.hostname else None


def _is_loopback(host: str | None) -> bool:
    return host is not None and (host in LOOPBACK_HOSTS or host.startswith("127."))


# --- the checks ------------------------------------------------------------------------


def bootstrap_gate(env: Mapping[str, str]) -> list[Finding]:
    """Delegated, never re-implemented: presence of the bootstrap five, APP_ENV's exact
    spelling, and the published `calevate_app:calevate_app` password outside `local`.

    It raises on the first problem, which is right for a boot gate and wrong for a
    preflight, so its refusal is captured as ONE finding and the rest of this file keeps
    going. That is the whole adaptation — the rules stay where they are."""
    try:
        validate_bootstrap_env(dict(env))
    except BootstrapError as exc:
        # The keys are `BOOTSTRAP_REQUIRED` itself rather than a guess at which one it
        # was: the gate's own message names the offender, and a hand-picked pair here
        # would go stale the moment that tuple grows.
        return [Finding("bootstrap_gate", tuple(BOOTSTRAP_REQUIRED), str(exc))]
    return []


def dsn_pair(env: Mapping[str, str]) -> list[Finding]:
    """The two DSNs describe ONE database reached by TWO roles. All four claims checked.

    `DATABASE_URL` is the app role (NOSUPERUSER NOBYPASSRLS — hard rule 1's RLS rests on
    it) and `ALEMBIC_DATABASE_URL` is the owner role that runs migrations. Nothing in the
    tree has ever checked that they agree about WHICH database, and the failure mode is
    the quietest one there is: migrations succeed against one database, the app serves
    from another, the deploy goes green, and the first symptom is a missing table under
    load. `alembic/env.py` refuses to fall back to `DATABASE_URL`, which is what makes the
    absent case a refusal here rather than a migration running as the wrong role."""
    findings: list[Finding] = []
    stated = _stated_env(env)
    app_raw = _present(env, "DATABASE_URL")
    alembic_raw = _present(env, "ALEMBIC_DATABASE_URL")

    if not alembic_raw:
        if stated != "local":
            findings.append(
                Finding(
                    "alembic_dsn_missing",
                    ("ALEMBIC_DATABASE_URL",),
                    "is not set. Migrations run as the OWNER role and `alembic/env.py` has "
                    "no fallback to DATABASE_URL on purpose — the app role cannot create a "
                    "policy, so the deploy would die mid-migration naming whichever "
                    "statement needed the privilege first (DEPLOYMENT §6 tier 1).",
                )
            )
        return findings

    app_dsn = _split_dsn(app_raw) if app_raw else None
    alembic_dsn = _split_dsn(alembic_raw)
    for key, raw, parsed in (
        ("DATABASE_URL", app_raw, app_dsn),
        ("ALEMBIC_DATABASE_URL", alembic_raw, alembic_dsn),
    ):
        if raw and parsed is None:
            findings.append(
                Finding(
                    "dsn_unparseable",
                    (key,),
                    "is not a URL with a host. Every Python process builds a SQLAlchemy "
                    "engine from it at boot, so this is a crash-loop after the swap rather "
                    "than a refusal before it. Expected "
                    "postgresql+psycopg://<role>:<password>@<host>:<port>/<database>.",
                )
            )
    if app_dsn is None or alembic_dsn is None:
        return findings

    if app_dsn.path != alembic_dsn.path:
        findings.append(
            Finding(
                "dsn_database_mismatch",
                ("DATABASE_URL", "ALEMBIC_DATABASE_URL"),
                "name DIFFERENT databases. Migrations would move a schema the application "
                "never reads: the deploy goes green and the first symptom is a missing "
                "table under load.",
            )
        )
    if (app_dsn.hostname, app_dsn.port) != (alembic_dsn.hostname, alembic_dsn.port):
        findings.append(
            Finding(
                "dsn_host_mismatch",
                ("DATABASE_URL", "ALEMBIC_DATABASE_URL"),
                "name different hosts or ports. Same failure as a database mismatch and "
                "harder to see: one server is migrated, the other serves.",
            )
        )
    if app_dsn.username and app_dsn.username == alembic_dsn.username:
        findings.append(
            Finding(
                "dsn_role_collision",
                ("DATABASE_URL", "ALEMBIC_DATABASE_URL"),
                "carry the SAME role. Two roles is not a convention: migrations need DDL "
                "and policy creation, and the application role is NOSUPERUSER NOBYPASSRLS "
                "because hard rule 1's tenant isolation is only as strong as that "
                "(DEPLOYMENT §9.3a). One role means either migrations run unprivileged, or "
                "every request runs as the owner.",
            )
        )

    if _stated_env(env) != "local":
        for key, parsed in (("DATABASE_URL", app_dsn), ("ALEMBIC_DATABASE_URL", alembic_dsn)):
            if _is_loopback(parsed.hostname):
                findings.append(
                    Finding(
                        "dsn_host_unreachable_from_container",
                        (key,),
                        "points at the container's own loopback. Postgres runs on the HOST "
                        "(D-26) and every Python process — including migrations — runs in a "
                        "container, so the DSNs are written as the CONTAINERS see them: "
                        "host.docker.internal (DEPLOYMENT §6 tier 1).",
                    )
                )
    return findings


def redis_url(env: Mapping[str, str]) -> list[Finding]:
    """`REDIS_URL` must name a host the container can reach.

    Their check is that it embeds `REDIS_PASSWORD`; ours cannot be, and the docstring at
    the top says why. This is the half of that refusal that survives the translation, and
    it is the more expensive half: redis carries the ARQ queue, the webhook dedupe keys
    and the config sentinel, so a loopback URL is a stack that starts and then fails every
    readiness probe and every job at once."""
    stated = _stated_env(env)
    raw = _present(env, "REDIS_URL")
    if not raw or stated == "local":
        return []
    parsed = _split_dsn(raw)
    if parsed is None:
        return [
            Finding(
                "redis_url_unparseable",
                ("REDIS_URL",),
                "is not a URL with a host. Expected redis://redis:6379/0 — the compose "
                "service name (DEPLOYMENT §6 tier 1).",
            )
        ]
    if _is_loopback(parsed.hostname):
        return [
            Finding(
                "redis_host_unreachable_from_container",
                ("REDIS_URL",),
                "points at the container's own loopback. Redis is a compose service with "
                "NO published host port (compose.prod.yml), so it is reachable only by "
                "service name: redis://redis:6379/0.",
            )
        ]
    return []


def platform_kek(env: Mapping[str, str]) -> list[Finding]:
    """The key that opens the credential store — checked by BUILDING THE RING.

    `core/envelope.build_ring` is pure and already owns the encoding rule, the length rule
    and the refusal an operator can act on. Calling it means this file cannot drift from
    the rule it is checking, and it converts every one of them — absent outside `local`,
    not base64, not 32 bytes — into a refusal before the deploy instead of a
    `ProblemError` at the first read of the first vendor credential."""
    configured = env.get("PLATFORM_KEK") or None
    # NAMED SEPARATELY BEFORE `build_ring` RUNS, and only for the RENDERING. The rule
    # itself lives in `envelope.build_ring` and is not restated here — this branch
    # re-derives nothing, it compares against the same frozenset the refusal is built on.
    # What it buys is the message: `_unusable_kek`'s `ProblemError` is deliberately CLIENT
    # prose ("there is nothing for you to fix"), because its other two doors are a shop
    # owner signing in and a client pasting a WhatsApp key, and the operator half of that
    # remediation was moved into the log line. This gate writes no log line and has
    # exactly one reader — the person running the deploy — so it has to say the
    # actionable thing itself.
    if configured and _stated_env(env) != "local":
        try:
            material = base64.b64decode(configured.strip(), validate=True)
        except (binascii.Error, ValueError):
            # Not a base64 problem to report here: `build_ring` below owns that refusal
            # and words it. An empty stand-in simply cannot match the frozenset.
            material = b""
        if material in _PUBLISHED_LOCAL_KEKS:
            return [
                Finding(
                    "platform_kek_is_published_constant",
                    ("PLATFORM_KEK",),
                    "is the development key this repository DERIVES AND PUBLISHES "
                    "(`core/envelope._LOCAL_KEK_SEED`). Anyone who has read this "
                    "repository can compute it, and it is the key that unwraps every DEK "
                    "in `platform_secrets` — so every vendor credential this deployment "
                    "holds would be readable from a checkout. Generate a real one with: "
                    'python -c "import base64,os; '
                    'print(base64.b64encode(os.urandom(32)).decode())"',
                )
            ]
    try:
        build_ring(
            kek=configured,
            retired=env.get("PLATFORM_KEK_RETIRED") or None,
            app_env=_stated_env(env),
        )
    except ProblemError as exc:
        return [
            Finding(
                "platform_kek_unusable",
                ("PLATFORM_KEK",),
                f"{exc.detail} {exc.remediation or ''}".strip(),
            )
        ]
    return []


def distinct_secrets(env: Mapping[str, str]) -> list[Finding]:
    """Values that must differ, and the length floor on the ones that sign.

    THREE refusals in one function because they are one question — "is this key doing a
    job another key is already doing" — asked three ways:

    1. a retired generation equal to the active one is a rotation that did not happen. The
       operator believes two generations exist, so the next rotation drops the only key
       that opens the older ciphertext.
    2. one HMAC secret reused across two purposes. This is the refusal their
       `JWT_REFRESH_SECRET === JWT_SECRET` is, in our key names and with a wider blast
       radius: `idempotency_scope_secret` is a pseudonymisation key and rotating it
       re-executes in-flight retries, so welding it to the audit chain's rotation means a
       key change that places a second real phone call.
    3. `AUDIT_CHAIN_SECRET` set to the constant this repository publishes. D-81 demoted
       `local-dev:{app_env}` to generation 0 of the key ring so old rows still verify; a
       deployment that SIGNS with it has a tamper-evident ledger keyed on a string in a
       public file, which is not evidence.

    Absence is never a finding here. All three are console-managed secrets (D-95): a
    correct host keeps them in `platform_secrets`, and `/healthz/ready` is what reports one
    that is missing everywhere."""
    findings: list[Finding] = []

    for active, retired in RETIRED_PAIRS:
        current, previous = _present(env, active), _present(env, retired)
        if current and previous and current == previous:
            findings.append(
                Finding(
                    "retired_key_equals_active",
                    (active, retired),
                    "are the SAME value. The retired slot exists to unwrap or verify what "
                    "the previous generation produced (D-86); set to the active value it "
                    "buys nothing and records a rotation that never happened.",
                )
            )

    present = {key: _present(env, key) for key in HMAC_SECRET_KEYS}
    for key, value in present.items():
        if value and len(value.encode()) < MIN_HMAC_KEY_BYTES:
            findings.append(
                Finding(
                    "hmac_key_too_short",
                    (key,),
                    f"is shorter than {MIN_HMAC_KEY_BYTES} bytes (RFC 2104 §3; NIST SP "
                    "800-107 Rev. 1 §5.3.4; RFC 7518 §3.2). `resolve_hmac_key` refuses it "
                    "at first use — this refuses it before the deploy.",
                )
            )
    for index, first in enumerate(HMAC_SECRET_KEYS):
        for second in HMAC_SECRET_KEYS[index + 1 :]:
            if present[first] and present[first] == present[second]:
                findings.append(
                    Finding(
                        "hmac_key_reused_across_purposes",
                        (first, second),
                        "are the SAME value. One key per purpose (NIST SP 800-57 Part 1 "
                        "Rev. 5 §5.2) — these sign for different purposes with different "
                        "rotation costs, which is why they are separate fields.",
                    )
                )

    audit = present["AUDIT_CHAIN_SECRET"]
    # Every spelling of the published constant, from the template and the environment
    # LIST rather than a hand-typed three: `ENVIRONMENTS` is `get_args(Environment)`, so
    # widening the Literal cannot leave this check behind (the argument `core/settings.py`
    # makes for reading the same tuple off the type).
    published = {_LEGACY_KEY_TEMPLATE.format(app_env=name) for name in ENVIRONMENTS}
    if audit and (audit in published or audit == _LEGACY_KEY_TEMPLATE):
        findings.append(
            Finding(
                "audit_chain_secret_is_published_constant",
                ("AUDIT_CHAIN_SECRET",),
                "is the constant this repository publishes as generation 0 of the key ring "
                "(D-81, `apps/api/compliance/audit.py`). Signing with it produces a "
                "tamper-evident ledger that anyone who has read this repository can forge.",
            )
        )
    return findings


def placeholders(env: Mapping[str, str], example: Mapping[str, str] | None) -> list[Finding]:
    """A value that is still the template's, or that is prompt text rather than a value.

    TWO SCANS, and they are scoped differently on purpose:

    * against `.env.example` itself, so the check cannot go stale the way a hand-written
      list of "known defaults" does. Only outside `local` — the example's values ARE the
      correct local values, which is what the file is for.
    * against a vocabulary of prompt text, in EVERY environment. `SARVAM_API_KEY=<your key
      here>` on a laptop is the same mistake as on a VPS, and D-49's lesson is that the
      cheapest place to catch a class of error is the earliest one.

    Scoped to `config_keys()` because in the image this runs against `os.environ`, which
    also carries PATH and HOSTNAME."""
    findings: list[Finding] = []
    known = config_keys()
    stated = _stated_env(env)

    for key in sorted(known):
        value = (env.get(key) or "").strip()
        if not value:
            continue
        if stated != "local" and example is not None:
            shipped = (example.get(key) or "").strip()
            if shipped and value == shipped:
                findings.append(
                    Finding(
                        "example_value_verbatim",
                        (key,),
                        "is byte-for-byte the value .env.example ships. That file is a "
                        "template of local defaults; a copied one on a real deployment is "
                        "how a host ends up pointing at a database, a bucket or an "
                        "endpoint that belongs to somebody's laptop.",
                    )
                )
                continue
        for pattern, described in _PLACEHOLDER_PATTERNS:
            if pattern.search(value):
                findings.append(
                    Finding(
                        "placeholder_value",
                        (key,),
                        f"still contains {described}. It is SET, so every presence check "
                        "in this repository passes and the failure surfaces at first use.",
                    )
                )
                break
    return findings


def console_managed_in_env(
    env: Mapping[str, str], example: Mapping[str, str] | None
) -> list[Finding]:
    """A key with TWO HOMES, where the environment silently wins.

    `apply_platform_overrides` layers the store UNDER the environment, deliberately
    (DEPLOYMENT §6: pasting a key here is the escape hatch for the night the console is
    what is broken). The cost of that escape hatch is this failure mode: an operator
    rotates a credential on the screen, sees it accepted, and watches the platform keep
    using the old one — `core/settings.ENV_ONLY_REASONS` argues it in those words for the
    one key where it is unavoidable. An empty declaration is the sharper version: pydantic
    hands the process `""` and the console's value is never consulted at all
    (`core/settings.env_declares`).

    A WARNING, not a refusal, because the escape hatch is real and using it is legitimate.
    The bootstrap set is excluded: those keys are in the environment BY DESIGN and warning
    about them would train an operator to ignore this line.

    AND IT IS SILENT UNDER `local`, which was not the first design and had to be measured:
    a developer `.env` written before D-95 moved fifty keys to the console carries a dozen
    of them declared empty, so this printed eleven true warnings about a laptop with no ops
    console in play. Every one of them was correct and none of them was worth reading,
    which is the definition of a warning that gets people to stop reading warnings. The
    whole cost this names — an operator rotating a credential on a screen that cannot
    win — needs a screen to exist."""
    if example is None or _stated_env(env) == "local":
        return []
    manageable = {name.upper() for name in (*managed_fields(), *manageable_secret_keys())}
    declared_by_design = {key.upper() for key in example} | COMPOSE_INJECTED
    findings: list[Finding] = []
    for key in sorted(manageable & (set(env) - declared_by_design)):
        blank = not (env.get(key) or "").strip()
        findings.append(
            Finding(
                "console_managed_key_in_env",
                (key,),
                (
                    "is declared EMPTY in the environment. pydantic hands the process an "
                    "empty string and the console's value is never read (D-95). Remove the "
                    "line — an unset key is what lets the store answer."
                    if blank
                    else "is managed from admin.calevate.tech/ops AND set here. The "
                    "environment wins, so a rotation performed on the screen will be "
                    "accepted and ignored. Deliberate as a break-glass; remove it "
                    "otherwise."
                ),
                severity=WARN,
            )
        )
    return findings


def retired_keys(env: Mapping[str, str]) -> list[Finding]:
    """A key whose field a decision deleted (`calevate_shared.config.RETIRED_ENV_KEYS`).

    `Settings()` refuses these too, but only in the process that constructs it; this is
    what refuses them in a `--env-file` check and names them under their own code. Every
    environment, `local` included: a developer `.env` holding one cannot boot either."""
    return [
        Finding(
            RETIRED_ENV_KEY_ERROR,
            (key,),
            retired_env_key_message(key, "the .env this deploy reads"),
        )
        for key in retired_env_keys_in(env)
    ]


def _vobiz_callback_secret_misused(env: Mapping[str, str]) -> list[Finding]:
    """A callback secret that is set and unusable, in every environment `local` included:
    set but short reads as configured while every reader drops it, and one equal to the
    claim key or the auth token publishes that key in Vobiz's console and call records."""
    secret = _present(env, VOBIZ_CALLBACK_SECRET_KEY)
    if not secret:
        return []
    if usable_callback_secret(secret) is None:
        problem = (
            f"is shorter than {MIN_CALLBACK_SECRET_CHARS} characters, so voice-runtime "
            "treats it as absent and refuses every Vobiz request outside local."
        )
    elif secret in (_present(env, CARRIER_CLAIM_KEY), _present(env, "VOBIZ_AUTH_TOKEN")):
        problem = (
            "equals CARRIER_CLAIM_SECRET or VOBIZ_AUTH_TOKEN. It travels in every URL Vobiz "
            "stores and shows, so a key it doubles as is published with it."
        )
    else:
        return []
    return [Finding("vobiz_callback_secret_unusable", (VOBIZ_CALLBACK_SECRET_KEY,), problem)]


def owned_runtime(env: Mapping[str, str]) -> list[Finding]:
    """The carrier leg's preconditions that live in this host's environment.

    The same states `/healthz/ready` reports under `ENGINE=pipecat`
    (`core/settings.owned_runtime_missing_keys`, `webhook_receiver_missing_keys`), refused
    before the swap instead of discovered after it. This gate cannot read the console, so
    it cannot see which engine is selected there: the leg is assumed live unless the
    environment itself declares another `ENGINE`, because the owned runtime is what this
    product runs and a host that is not running it can say so in one line.

    A claim key under the floor is refused everywhere, `local` included: it is set, so it
    looks configured, and the answer leg silently treats it as absent.
    """
    findings: list[Finding] = []
    claim = _present(env, CARRIER_CLAIM_KEY)
    if claim and usable_caller_claim_key(claim) is None:
        findings.append(
            Finding(
                "carrier_claim_secret_unusable",
                (CARRIER_CLAIM_KEY,),
                f"is shorter than {MIN_CALLER_CLAIM_KEY_BYTES} bytes. voice-runtime and the "
                "worker both treat it as absent, so no caller is identified and an outbound "
                "call is taken for an inbound one.",
            )
        )
    findings.extend(_vobiz_callback_secret_misused(env))
    declared_engine = _present(env, "ENGINE")
    if _stated_env(env) == "local" or (declared_engine and declared_engine != "pipecat"):
        return findings

    declared_carrier = _present(env, "CARRIER")
    if not _present(env, VOBIZ_CALLBACK_SECRET_KEY) and declared_carrier in ("", "vobiz"):
        findings.append(
            Finding(
                "vobiz_callback_secret_unusable",
                (VOBIZ_CALLBACK_SECRET_KEY,),
                "is not set. voice-runtime refuses every Vobiz request without it, so no "
                "call is answered and no hangup is recorded; it is what stops another Vobiz "
                "customer pointing their number at our agents. Generate one with "
                "`openssl rand -hex 32` (DEPLOYMENT §12.6).",
            )
        )

    if not claim:
        findings.append(
            Finding(
                "carrier_claim_secret_unusable",
                (CARRIER_CLAIM_KEY,),
                "is not set. It is env-only (voice-runtime never opens the credential "
                "store) and signs the caller and call claims on every stream URL; without "
                "it no caller is identified and an outbound call is taken for an inbound "
                "one. Generate "
                "at least 32 random bytes and put the SAME value in the Pipecat worker's "
                "secret set (DEPLOYMENT §12.2).",
            )
        )
    if not all(_present(env, key) for key in CARRIER_CREDENTIAL_KEYS):
        findings.append(
            Finding(
                "carrier_credentials_missing",
                CARRIER_CREDENTIAL_KEYS,
                "are not both set. They are env-only and are the carrier's only "
                "credential on this host: without them no call is placed, no number is "
                "bound and no call record is read (DEPLOYMENT §12.6).",
            )
        )
    if STREAM_BASE_KEY in env and not _present(env, STREAM_BASE_KEY):
        findings.append(
            Finding(
                "pipecat_stream_base_url_blank",
                (STREAM_BASE_KEY,),
                "is declared EMPTY. The environment wins over the console, so the answer "
                "route reads an empty worker address and refuses every call. Remove the "
                "line and set it in the ops console, or set the worker's wss:// base here.",
            )
        )
    elif STREAM_BASE_KEY in env and not is_deployable_stream_base(env[STREAM_BASE_KEY]):
        findings.append(
            Finding(
                "pipecat_stream_base_url_unusable",
                (STREAM_BASE_KEY,),
                "is not a wss:// URL on Pipecat Cloud's regional host. The region-less "
                "api.pipecat.daily.co routes every stream to us-west, where the worker is "
                "not deployed. Use wss://ap-south.api.pipecat.daily.co/ws/plivo?serviceHost="
                "<agent>.<org> (runbooks/first-deploy.md §9a step 4), or remove the line "
                "and set it in the ops console.",
            )
        )
    callback = _present(env, CALLBACK_BASE_KEY)
    if callback and not is_public_callback_base(callback):
        findings.append(
            Finding(
                "webhook_base_url_not_public",
                (CALLBACK_BASE_KEY,),
                "is not an https:// URL on a host the carrier can reach. Every answer, "
                "hangup and status URL the carrier is given is built on it, so a call "
                "would ring and nothing would answer. Set it to the public hooks origin.",
            )
        )
    return findings


THINNEST_KEY = "THINNEST_API_KEY"
THINNEST_BASE_KEY = "THINNEST_API_BASE_URL"
INTAKE_KEK_KEY = "ENGINE_INTAKE_KEK"
INTAKE_KEK_RETIRED_KEY = "ENGINE_INTAKE_KEK_RETIRED"


def thinnest(env: Mapping[str, str]) -> list[Finding]:
    """The ThinnestAI engine's environment (D-678): both keys are env-only.

    The engine is console-managed, so like `owned_runtime` this can only act on an `ENGINE`
    the environment itself declares. A widget key in the API key's place is refused in
    every environment: it is the documented confusion between the two
    (`thinnest-findings/mirror/pages/api-reference/authentication.md:17-24`), and it would
    fail every request.
    """
    findings: list[Finding] = []
    key = _present(env, THINNEST_KEY)
    if key.startswith("pk_"):
        findings.append(
            Finding(
                "thinnest_api_key_unusable",
                (THINNEST_KEY,),
                "holds a public widget key (`pk_…`), not an API key. Create a full-access "
                "API key under Settings → API keys in ThinnestAI.",
            )
        )
    intake = _present(env, INTAKE_KEK_KEY)
    if _stated_env(env) != "local" and intake:
        # The ring's own rules (base64, 32 bytes, not the published development key),
        # applied by building it rather than restated here.
        try:
            build_intake_ring(intake, _present(env, INTAKE_KEK_RETIRED_KEY) or None, "prod")
        except ProblemError as exc:
            findings.append(
                Finding(
                    "engine_intake_kek_unusable",
                    (INTAKE_KEK_KEY,),
                    f"{exc.detail} {exc.remediation or ''}".strip(),
                )
            )
    if _stated_env(env) == "local" or _present(env, "ENGINE") != "thinnest":
        return findings
    if not intake:
        findings.append(
            Finding(
                "engine_intake_kek_missing",
                (INTAKE_KEK_KEY,),
                "is not set while ENGINE=thinnest. voice-runtime opens each agent's webhook "
                "signing secret with it, so without it every ThinnestAI delivery is refused. "
                "Set the SAME base64 32-byte value for api, workers and voice-runtime.",
            )
        )
    if not key:
        findings.append(
            Finding(
                "thinnest_api_key_missing",
                (THINNEST_KEY,),
                "is not set while ENGINE=thinnest. It is env-only, so the environment is its "
                "only home; without it no agent is published and no call is placed.",
            )
        )
    base = _present(env, THINNEST_BASE_KEY)
    if base and not base.startswith("https://"):
        findings.append(
            Finding(
                "thinnest_api_base_url_unusable",
                (THINNEST_BASE_KEY,),
                "is not an https:// URL, so the API key would travel in the clear. Remove the "
                "line to use ThinnestAI's own API.",
            )
        )
    callback = _present(env, CALLBACK_BASE_KEY)
    if callback and not is_public_callback_base(callback):
        findings.append(
            Finding(
                "webhook_base_url_not_public",
                (CALLBACK_BASE_KEY,),
                "is not an https:// URL on a public host. ThinnestAI sends every call result "
                "to it and refuses an address it cannot reach.",
            )
        )
    return findings


def settings_constructible() -> list[Finding]:
    """`Settings()` on THIS process's environment — the step this file absorbed.

    `vps-deploy.sh::verify_bootstrap_env` used to run `validate_bootstrap_env(); \
    get_settings()` as an inline `python -c` and then this module as a second
    `compose run`, which meant the bootstrap gate ran twice per deploy and the step had
    two implementations to keep in step. It runs once, here (DEPLOYMENT §4 step 6 is
    still exactly "`validate_bootstrap_env` + `Settings()`", and now some more).

    What it adds over the gate above is the TYPE: `DB_POOL_SIZE=500` and a `GCP_PROJECT_ID`
    that is really a project number are both present, non-placeholder and fatal — every
    container would crash-loop after the swap.

    ONLY THE FIELD NAME AND THE RULE ARE PRINTED. Pydantic's `ValidationError` renders
    `input_value` in its string form, and these fields include credentials (hard rule 6),
    so the summary is built from `loc` and `msg` and the exception is never str()'d.
    """
    try:
        Settings()
    except ValidationError as exc:
        # A retired key is already a `retired_env_key` finding from `evaluate`; reporting
        # it twice would bury it under a second code for the same line.
        errors = [error for error in exc.errors() if error["type"] != RETIRED_ENV_KEY_ERROR]
        if not errors:
            return []
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']).upper()}: {error['msg']}"
            for error in errors
        )
        return [
            Finding(
                "settings_unbuildable",
                tuple(".".join(str(part) for part in error["loc"]).upper() for error in errors),
                f"the process cannot build its configuration: {problems}. Every container "
                "would crash-loop on start, after the swap.",
            )
        ]
    return []


# --- composition -----------------------------------------------------------------------


def evaluate(env: Mapping[str, str], example: Mapping[str, str] | None) -> list[Finding]:
    """Every check, over one environment. Pure — no IO, no process state — which is what
    lets `tests/deploy_env_preflight_test.py` construct a bad `.env` per refusal."""
    findings: list[Finding] = []
    findings.extend(bootstrap_gate(env))
    findings.extend(dsn_pair(env))
    findings.extend(redis_url(env))
    findings.extend(platform_kek(env))
    findings.extend(distinct_secrets(env))
    findings.extend(placeholders(env, example))
    findings.extend(console_managed_in_env(env, example))
    findings.extend(retired_keys(env))
    findings.extend(owned_runtime(env))
    findings.extend(thinnest(env))
    if example is None:
        findings.append(
            Finding(
                "example_file_unreadable",
                (".env.example",),
                f"was not found at {EXAMPLE_FILE}, so the checks that compare this "
                "deployment against the shipped template did not run. They are the ones "
                "that catch a copied file.",
                severity=WARN,
            )
        )
    return findings


def load_example() -> Mapping[str, str] | None:
    """`.env.example`, or None when it is not on disk. Never a silent skip: `evaluate`
    turns the absence into a warning that names the checks that did not run."""
    if not EXAMPLE_FILE.exists():
        return None
    try:
        return read_env_file(EXAMPLE_FILE)
    except OSError:
        return None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="check_deploy_env",
        description="Refuse a deploy whose environment is incoherent. Reports every "
        "problem at once and never prints a value.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="read the environment from this file instead of the process environment "
        "(for checking a .env before it is placed on a host)",
    )
    args = parser.parse_args(argv)

    if args.env_file is not None:
        if not args.env_file.exists():
            missing = Finding(
                "env_file_missing",
                (str(args.env_file),),
                "does not exist. This script never writes one: the file is placed by hand "
                "from the secrets manager (DEPLOYMENT §6 tier 1).",
            )
            print(f"DEPLOY ENV: FAIL\n  - {missing.render()}")
            return 1
        env: Mapping[str, str] = read_env_file(args.env_file)
        source = str(args.env_file)
    else:
        # `effective_env()`, NOT `os.environ`: pydantic-settings reads `.env` as well as
        # the process environment, so a gate that saw only `os.environ` would refuse a
        # perfectly good developer machine and — worse — would answer a different question
        # from the one the app asks. Same merged view, same precedence (process wins) as
        # `validate_bootstrap_env`. In the image there is no `.env` (`.dockerignore`
        # excludes it) so this IS `os.environ`, which is where compose's `env_file` puts
        # the values.
        env = effective_env()
        source = "the environment this process would run with"

    findings = evaluate(env, load_example())
    if args.env_file is None:
        # Only for the REAL environment: a file handed in with `--env-file` may belong to
        # another host, and `Settings()` can only ever be built from this process's own.
        findings.extend(settings_constructible())
    refusals = [f for f in findings if f.severity == REFUSE]
    warnings = [f for f in findings if f.severity == WARN]

    for warning in warnings:
        print(f"  ! {warning.render()}")
    if refusals:
        print(f"DEPLOY ENV: FAIL ({source})")
        for refusal in refusals:
            print(f"  - {refusal.render()}")
        print(
            "\nEvery problem above is in the environment this deploy would run with. "
            "Nothing was built, migrated or swapped. Fix them together — the values live "
            "in the secrets manager, never in git (DEPLOYMENT §6)."
        )
        return 1
    print(f"DEPLOY ENV: OK ({source}; APP_ENV={_stated_env(env) or 'unset'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
