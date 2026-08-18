"""The executable half of `runbooks/backup-restore-drill.md`.

**What this is.** Everything in `infra/backup/` and `scripts/backup/` is reviewed and
unapplied — `infra/backup/README.md` §9 says so plainly, and the drill runbook calls the
whole tree a hypothesis. This module converts the part of that hypothesis that does NOT
need a cloud account into a mechanism that runs on every developer's machine: seed a
database, dump it the way `dump-offsite.sh` dumps it, encrypt it with the same `age`
invocation, put it in object storage, take it back out, decrypt it, restore it into a
scratch database, and then *prove the restore is a restore* rather than a process that
exited zero.

**What it is NOT, and this is the whole reason the coverage block below exists.** It does
not test wal-g, R2, the offsite provider, the libsodium key, the age identity in the
secrets manager, the systemd timers, or `rclone`. None of those can be exercised without
a credential. A harness that ran the cheap half and printed "PASS" would manufacture
exactly the false confidence `backup-health.sh` was written to prevent, so this one
prints its own coverage next to its verdict, every run, and its verdict vocabulary
(`GREEN (local scope)`) cannot be mistaken for the runbook's `PASS`.

**Why the checks are the ones they are.** A restore of this product has to prove five
things that "pg_restore exited 0" does not:

1. the schema is at the alembic head the application expects (a restore behind a
   migration is an application that fails in ways that look like bugs);
2. RLS is still ENABLEd *and* FORCEd on every tenant-scoped table, and a cross-tenant
   read still returns zero rows — a restore that silently drops policies is a data
   breach dressed up as a recovery (hard rule 1);
3. the append-only triggers still RAISE on UPDATE and DELETE for every ledger in
   `APPEND_ONLY_TABLES` — an evidential ledger that restores as an ordinary table has
   stopped being evidence (hard rule 4);
4. the audit hash chain still verifies over the restored rows, because the chain is the
   only thing that says nobody edited them in between;
5. the rows that went in came back out, counted.

Every one of those is answered by code this repository already has —
`scripts/check_rls_coverage.py`, `scripts/check_ledger_immutability.py` and
`apps/api/compliance/audit.verify_chain` — invoked against the restored database rather
than reimplemented here. `runbooks/database-restore.md` §7.5 already tells an operator to
run the first two by hand; this runs them for them. Two ways of asking one question is a
defect in this repo even when both work (CLAUDE.md).

**Deliberate non-reuse, said out loud.** Two checks here are NOT delegated, because they
ask something the guardrails structurally cannot:

* `cross_tenant_isolation` connects as the unprivileged `calevate_app` role and reads
  real restored rows under two different `app.tenant_id` values. `check_rls_coverage`
  reads `pg_policy` — it proves the policy *exists and mentions the GUC*, never that it
  *behaves*. On a restored database the second question is the one that matters.
* `append_only_enforced` actually issues an UPDATE and a DELETE against each ledger and
  requires both to raise. `check_ledger_immutability` reads `pg_trigger` and infers.
  Those two are complementary by construction — the guardrail's own docstring says
  check 3 is the backstop for SQL it cannot resolve, and this is what tests the backstop.

  That is why this file contains statements that mutate append-only ledgers. They run
  only against a scratch database whose name this module verified matches
  `SCRATCH_DB_PATTERN`, always inside a transaction that is rolled back, and their table
  names come from `APPEND_ONLY_TABLES` at runtime rather than from literals. That is
  stated here rather than left for the next reader to discover.

**A verifier that has never seen a bad restore is a verifier nobody should trust**, so
the failure modes are executable too: `--sabotage <kind>` breaks exactly one thing
(the stored object, an RLS policy, a ledger trigger, an audit row) and the drill must go
RED naming that specific defect and nothing else. `tests/restore_drill_test.py` pins the
pure parts; the sabotage modes are how the wet parts are proved.

Run:

    make restore-drill                                   # the whole chain, green path
    make restore-drill SABOTAGE=drop-rls-policy          # prove it goes red
    uv run python -m scripts.restore_drill --help
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

from dotenv import dotenv_values

REPO_ROOT = Path(__file__).resolve().parent.parent
DUMP_OFFSITE = REPO_ROOT / "scripts" / "backup" / "dump-offsite.sh"
DEFAULT_RECORD_DIR = REPO_ROOT / "docs" / "evidence"

# Scratch databases this module is allowed to create, restore into, sabotage and drop.
# Every destructive statement in this file checks a database name against this pattern
# first: the drill's worst plausible bug is pointing itself at a real database, and the
# cheapest defence against it is a name shape that no real database has.
SCRATCH_DB_PATTERN = re.compile(r"^calevate_drill_(src|restore)_[0-9]{8}t[0-9]{6}z$")

# The one place the local drill's scope is written down. Each entry names what was NOT
# exercised and the credential or account that would be needed to exercise it, so the
# scorecard can carry it verbatim and a green run can never be read as a full drill.
#
# This list is the deliverable, not a disclaimer. `runbooks/backup-restore-drill.md` §0a
# maps every line of it onto the quarterly drill step that does cover it.
NOT_COVERED: tuple[tuple[str, str, str], ...] = (
    (
        "walg_pitr",
        "Chain A end to end: wal-g backup-push, WAL archiving, wal-fetch, "
        "recovery_target_time replay, and timeline handling. No wal-g command has been "
        "run by this harness or by anything else in this repository.",
        "a wal-g binary on the host, an R2 bucket and its scoped token "
        "(infra/backup/walg.json.template), and a PGDATA to push",
    ),
    (
        "r2_object_store",
        "Cloudflare R2 specifically. MinIO stands in for it here; DEPLOYMENT §7 records "
        "that R2's multipart implementation has rejected uploads other S3 clients "
        "accept, and wal-g #1639 records backup-push hanging after an S3 409. MinIO "
        "passing proves S3 semantics, not R2's.",
        "a Cloudflare account and an R2 bucket + token",
    ),
    (
        "offsite_provider",
        "The non-Cloudflare offsite destination and the rclone remote that reaches it "
        "(dump-offsite.sh's OFFSITE_REMOTE). rclone is not invoked here at all, so "
        "`rclone copy --checksum`, the read-back it performs and "
        "`rclone delete --min-age` retention pruning are all untested.",
        "a Backblaze B2 / S3 / Hetzner Storage Box account and "
        "/etc/calevate/rclone.conf from the secrets manager",
    ),
    (
        "age_identity_retrieval",
        "That the REAL age identity can still be produced from the secrets manager and "
        "still decrypts a real nightly dump. This harness generates a throwaway keypair "
        "per run, so it proves the age INVOCATION, never the key custody — and losing "
        "the identity makes every offsite dump permanently unreadable, which the drill "
        "runbook calls the most serious finding it can make.",
        "the secrets manager and the production age identity",
    ),
    (
        "libsodium_key",
        "WALG_LIBSODIUM_KEY: that chain A's backups are encrypted and that we still "
        "hold the key to decrypt them.",
        "the secrets manager and a wal-g archive to decrypt",
    ),
    (
        "systemd_schedule",
        "The timers themselves (calevate-basebackup, calevate-dump-offsite, "
        "calevate-backup-health), OnFailure= routing, Persistent=true catch-up, and "
        "backup-health.sh's reading of `systemctl show` — which infra/backup/README.md "
        "§9 flags as never exercised against a live systemd.",
        "a host booted under systemd with the units installed",
    ),
    (
        "alert_delivery",
        "That a host alert reaches a human inbox. tests/backup_alert_relay_test.py "
        "covers the relay down to a transport; nothing here or there has put a message "
        "in a real mailbox.",
        "an SMTP provider, ALERTS_EMAIL, and somebody looking at the inbox",
    ),
    (
        "external_dead_man",
        "The external dead-man's switch (heartbeat.sh -> scripts/host_heartbeat.py): "
        "that a healthy run pings, that stopped pings page a human, and that a FAILING "
        "run pings nothing.",
        "BACKUP_HEARTBEAT_URL and the monitoring vendor's account",
    ),
    (
        "recording_bucket",
        "That a recording referenced by a restored `calls` row is still readable. A "
        "database restore does not restore the recordings bucket, and a recording_url "
        "pointing at nothing is a half-recovery nobody notices until a client asks.",
        "the production recordings bucket and its credential",
    ),
    (
        "production_scale",
        "RTO and RPO at production data volume, on production hardware. Every timing "
        "below is a seeded fixture on a laptop and is evidence about the MECHANISM, "
        "never about the 4-hour RTO in OPERATIONS §5.",
        "a scratch host sized to production and a production-sized backup",
    ),
)

SABOTAGE_KINDS = (
    "corrupt-object",
    "drop-rls-policy",
    "disable-append-only-trigger",
    "tamper-audit-row",
)

# Two tenants, so "cross-tenant read returns zero rows" has something to be zero about.
TENANT_A = UUID("aaaaaaaa-0000-4000-8000-000000000001")
TENANT_B = UUID("bbbbbbbb-0000-4000-8000-000000000002")
AGENT_A = UUID("aaaaaaaa-0000-4000-8000-00000000a9e1")
AGENT_B = UUID("bbbbbbbb-0000-4000-8000-00000000a9e2")
USER_A = UUID("aaaaaaaa-0000-4000-8000-00000000c5e1")
USER_B = UUID("bbbbbbbb-0000-4000-8000-00000000c5e2")
ADMIN_ID = UUID("cccccccc-0000-4000-8000-0000000000ad")
LEADS_PER_TENANT = 7
AUDIT_ENTRIES = 6

#: THE MUTATION THE APPEND-ONLY PROBE ATTEMPTS, per ledger — a SET clause, and it must
#: CHANGE THE VALUE rather than write a column back onto itself.
#:
#: The probe used to be `SET tenant_id = tenant_id` for every ledger, which is wrong twice
#: and was never once observed because `verify()` aborted before it (see
#: `_check_audit_chain`). `platform_secrets` is not tenant-scoped, so that statement did
#: not even parse — and `_raises` reads an `UndefinedColumn` as "the database did not
#: refuse", i.e. a correct ledger reported UNPROTECTED. And a no-op write is invisible to
#: the two triggers that compare NEW to OLD (`platform_secrets_forbid_mutation` permits
#: exactly the D-97 KEK re-wrap columns; `calevate_preference_scrub_append_only` permits
#: exactly the `ON DELETE SET NULL` of `campaign_id`), so it would prove nothing about
#: either even where it parsed.
#:
#: A real reassignment of `tenant_id` is also the mutation worth naming: moving a ledger
#: row to another tenant is the specific thing hard rule 4 and hard rule 1 both forbid.
#: The FK it would violate is never reached — these are BEFORE ROW triggers.
_APPEND_ONLY_PROBE_SET = {"platform_secrets": "last_four = last_four || 'x'"}


def _append_only_probe_set(table: str) -> str:
    return _APPEND_ONLY_PROBE_SET.get(table, "tenant_id = gen_random_uuid()")


# --------------------------------------------------------------------------------------
# Result model. A stage that did not run is not a stage that passed, so `Outcome` has a
# third value and the verdict function treats it as such.
# --------------------------------------------------------------------------------------


@dataclass
class Step:
    """One stage or one check: what it asked, what it found, how long it took."""

    name: str
    ok: bool
    detail: str
    seconds: float = 0.0
    #: Free-form measurements an operator or an auditor may want a year later.
    facts: dict[str, Any] = field(default_factory=dict)

    @property
    def mark(self) -> str:
        return "ok  " if self.ok else "FAIL"


@dataclass
class Drill:
    started_at: datetime
    stamp: str
    sabotage: str | None
    stages: list[Step] = field(default_factory=list)
    checks: list[Step] = field(default_factory=list)
    scratch_databases: list[str] = field(default_factory=list)
    bucket: str = ""
    aborted: str | None = None

    @property
    def failures(self) -> list[Step]:
        return [s for s in (*self.stages, *self.checks) if not s.ok]

    @property
    def green(self) -> bool:
        return not self.failures and self.aborted is None

    @property
    def verdict(self) -> str:
        # Deliberately NOT the runbook's PASS/PARTIAL/FAIL vocabulary. This harness
        # covers one chain on local infrastructure; borrowing the quarterly scorecard's
        # words is how a half-drill gets filed as a whole one.
        return "GREEN (local scope)" if self.green else "RED"

    @property
    def total_seconds(self) -> float:
        return sum(s.seconds for s in self.stages)


class DrillError(RuntimeError):
    """A stage could not run at all — as opposed to running and finding a defect."""


# --------------------------------------------------------------------------------------
# Parity with the production script. The drill runs the flags `dump-offsite.sh` runs,
# read out of that file at drill time. If somebody changes the production flags, the
# drill follows them; if somebody removes the command, the drill stops rather than
# quietly testing an invocation production no longer performs.
# --------------------------------------------------------------------------------------

_PGDUMP_CALL = re.compile(r"\bpg_dump\s+(--(?:[^\n]*\\\n)*[^\n]*)")
_AGE_CALL = re.compile(r"\bage\s+(--encrypt(?:[^\n]*\\\n)*[^\n]*)")
_LONG_OPTION = re.compile(r"--[a-z][a-z0-9-]*(?:=\S+)?")

# Options whose VALUE is host state (a path, a DSN) rather than a property of the
# backup. The option NAME is still kept and still required: dropping it entirely is how
# a drill would keep passing after somebody swapped `--recipients-file` (this host can
# write a backup it cannot read) for a passphrase.
_HOST_SPECIFIC = frozenset({"--file", "--dbname", "--output", "--recipients-file"})

# Properties the drill will not proceed without, because each one is load-bearing
# somewhere else in the recovery story.
_REQUIRED_DUMP_OPTIONS = ("--format=custom",)  # `pg_restore --table` (restore §10)
_REQUIRED_AGE_OPTIONS = ("--encrypt", "--recipients-file")  # asymmetric, per §5


def production_dump_options(script: str | None = None) -> list[str]:
    """Every long option `dump-offsite.sh` gives `pg_dump`, host-specific values stripped.

    `--format=custom` is what makes `pg_restore --table` possible and `--compress=6` is
    what the size tripwire's ratios are measured against; a drill that hardcoded either
    would keep passing after production changed it.
    """
    return _options_from(script, _PGDUMP_CALL, "pg_dump", _REQUIRED_DUMP_OPTIONS)


def production_age_options(script: str | None = None) -> list[str]:
    """The same, for `age`.

    Encryption is the stage where substituting a different tool would be a lie: if `age`
    is missing the drill refuses rather than reaching for openssl.
    """
    return _options_from(script, _AGE_CALL, "age --encrypt", _REQUIRED_AGE_OPTIONS)


def _options_from(
    script: str | None, pattern: re.Pattern[str], what: str, required: tuple[str, ...]
) -> list[str]:
    text = script if script is not None else DUMP_OFFSITE.read_text(encoding="utf-8")
    match = pattern.search(text)
    if not match:
        raise DrillError(
            f"no `{what}` invocation found in {DUMP_OFFSITE.name}: the drill cannot claim "
            "parity with a command it cannot find. Fix the extraction or the script."
        )
    options: list[str] = []
    for option in _LONG_OPTION.findall(match.group(1).replace("\\\n", " ")):
        name = option.split("=", 1)[0]
        options.append(name if name in _HOST_SPECIFIC else option)
    missing = [option for option in required if option not in options]
    if missing:
        raise DrillError(
            f"`{what}` in {DUMP_OFFSITE.name} no longer passes {', '.join(missing)}. "
            "That is a change to what a recovery can do, so the drill stops here rather "
            "than testing an invocation production does not perform."
        )
    return options


def apply_options(options: list[str], values: dict[str, str]) -> list[str]:
    """Bind the host-specific options to this drill's own paths.

    Any option not in `values` is passed through exactly as production passes it.
    """
    bound: list[str] = []
    for option in options:
        bound.append(f"{option}={values[option]}" if option in values else option)
    return bound


# --------------------------------------------------------------------------------------
# DSNs. Built from `.env` so the drill can never carry a credential of its own, and
# fenced so it can never point at the database the application uses.
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Dsns:
    """Connection strings for two roles, in the two forms this repo actually uses.

    `owner` runs DDL and the dump (it must bypass RLS — see `dump`); `app` is the
    unprivileged `calevate_app` role the cross-tenant probe needs; `maintenance` is
    `owner` pointed at `postgres` so CREATE/DROP DATABASE has somewhere to run.

    TWO FORMS, and mixing them is a real failure rather than a nicety: `alembic`,
    `check_rls_coverage` and the app build a SQLAlchemy engine, which resolves a bare
    `postgresql://` to **psycopg2** — a driver this project does not install — while
    `pg_dump`, `pg_restore` and `psycopg.connect` take libpq DSNs and reject the
    `+driver` suffix. `url()` is what a child process gets; `dsn()` is what a tool gets.
    """

    owner_template: str
    app_template: str
    protected: frozenset[str]

    def owner_url(self, database: str) -> str:
        return _with_database(self.owner_template, database)

    def app_url(self, database: str) -> str:
        return _with_database(self.app_template, database)

    def owner(self, database: str) -> str:
        return _libpq(self.owner_url(database))

    def app(self, database: str) -> str:
        return _libpq(self.app_url(database))

    @property
    def maintenance(self) -> str:
        return self.owner("postgres")


def load_dsns(env: dict[str, str] | None = None) -> Dsns:
    values = env if env is not None else _env()
    owner = values.get("ALEMBIC_DATABASE_URL") or ""
    app = values.get("DATABASE_URL") or ""
    if not owner or not app:
        raise DrillError(
            "ALEMBIC_DATABASE_URL and DATABASE_URL must both be set (copy .env.example "
            "to .env). The drill derives every connection string from them so that it "
            "holds no credential of its own."
        )
    if (values.get("APP_ENV") or "").strip().lower() == "prod":
        raise DrillError(
            "APP_ENV=prod: refusing to run. This harness creates, corrupts and drops "
            "databases; the quarterly drill on a scratch host is the production "
            "procedure (runbooks/backup-restore-drill.md)."
        )
    return Dsns(
        owner_template=owner,
        app_template=app,
        protected=frozenset({_database_of(owner), _database_of(app)}),
    )


def _libpq(url: str) -> str:
    """Strip the SQLAlchemy driver suffix: libpq does not know what `+psycopg` means."""
    scheme, _, rest = url.partition("://")
    return f"{scheme.split('+', 1)[0]}://{rest}"


def _with_database(url: str, database: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{database}", parts.query, ""))


def _database_of(url: str) -> str:
    return urlsplit(url).path.lstrip("/")


def assert_scratch(name: str, protected: frozenset[str]) -> None:
    """The guard every destructive statement in this module goes through."""
    if name in protected:
        raise DrillError(
            f"{name!r} is a database named in .env. The drill never touches it — "
            "that is the difference between a rehearsal and an outage."
        )
    if not SCRATCH_DB_PATTERN.match(name):
        raise DrillError(
            f"{name!r} does not match the scratch-database pattern "
            f"{SCRATCH_DB_PATTERN.pattern!r}; refusing to operate on it."
        )


def _env() -> dict[str, str]:
    """`.env` overlaid by the real environment, which is the precedence Settings uses."""
    values = {k: v for k, v in dotenv_values(REPO_ROOT / ".env").items() if v is not None}
    values.update({k: v for k, v in os.environ.items() if k in {*values, "APP_ENV"}})
    return values


# --------------------------------------------------------------------------------------
# Small process and SQL helpers.
# --------------------------------------------------------------------------------------


def _run(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
    timeout: int = 900,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        env={**os.environ, **(env or {})},
        cwd=str(cwd or REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _tail(process: subprocess.CompletedProcess[str], lines: int = 6) -> str:
    output = (process.stderr or process.stdout or "").strip().splitlines()
    return " | ".join(output[-lines:]) or "(no output)"


def _connect(dsn: str) -> Any:
    import psycopg  # local: the orchestrator must import cleanly with no database

    return psycopg.connect(dsn, autocommit=True)


def _scalar(dsn: str, sql: str, params: tuple[Any, ...] = ()) -> Any:
    with _connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute(sql, params)
        row = cursor.fetchone()
    return None if row is None else row[0]


def _rows(dsn: str, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    with _connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute(sql, params)
        return list(cursor.fetchall())


def _execute(dsn: str, statements: list[str]) -> None:
    with _connect(dsn) as connection, connection.cursor() as cursor:
        for statement in statements:
            cursor.execute(statement)  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------
# Object storage. boto3 against the MinIO that `docker compose up -d` already runs.
# --------------------------------------------------------------------------------------


def _s3_client(endpoint: str, access_key: str, secret_key: str) -> Any:
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="us-east-1",
        config=Config(signature_version="s3v4", retries={"max_attempts": 2}),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --------------------------------------------------------------------------------------
# The drill.
# --------------------------------------------------------------------------------------


class RestoreDrill:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.dsns = load_dsns()
        stamp = datetime.now(UTC).strftime("%Y%m%dt%H%M%Sz")
        self.record = Drill(
            started_at=datetime.now(UTC),
            stamp=stamp,
            sabotage=args.sabotage,
        )
        self.source_db = f"calevate_drill_src_{stamp}"
        self.restore_db = f"calevate_drill_restore_{stamp}"
        assert_scratch(self.source_db, self.dsns.protected)
        assert_scratch(self.restore_db, self.dsns.protected)
        self.work = Path(tempfile.mkdtemp(prefix=f"calevate-drill-{stamp}-"))
        self.bucket = f"calevate-drill-{stamp}"
        self.record.bucket = self.bucket
        self.artifact = f"calevate-{stamp}.dump.age"
        self.evidence_name = f"calevate-{stamp}.evidence.json"
        day = datetime.now(UTC).strftime("%Y/%m/%d")
        # The layout dump-offsite.sh writes and database-restore.md §10 reads back.
        self.key = f"postgres/{day}/{self.artifact}"
        self.evidence_key = f"postgres/{day}/{self.evidence_name}"
        self.s3: Any = None
        self.bucket_created = False
        self.digest = ""
        self.expected_counts: dict[str, int] = {}
        self.expected_head = ""

    # -- staging -----------------------------------------------------------------

    def stage(self, name: str) -> _StageContext:
        return _StageContext(self, name)

    def check(self, name: str, ok: bool, detail: str, **facts: Any) -> None:
        self.record.checks.append(Step(name=name, ok=ok, detail=detail, facts=facts))
        print(f"    [{'ok  ' if ok else 'FAIL'}] {name}: {detail}", flush=True)

    # -- 1. preflight ------------------------------------------------------------

    def preflight(self) -> None:
        with self.stage("preflight") as step:
            missing = [t for t in ("pg_dump", "pg_restore", "psql", "age") if not shutil.which(t)]
            if missing:
                # age above all: substituting another cipher would make every later
                # stage a test of something we do not deploy.
                raise DrillError(
                    f"required tools missing: {', '.join(missing)}. "
                    "The drill refuses to substitute: `age` is what dump-offsite.sh "
                    "runs, and a drill that encrypts with something else has tested "
                    "something we do not ship."
                )
            endpoint = self.args.s3_endpoint
            self.s3 = _s3_client(endpoint, self.args.s3_access_key, self.args.s3_secret_key)
            try:
                self.s3.list_buckets()
            except Exception as exc:
                raise DrillError(
                    f"no S3-compatible endpoint at {endpoint} ({type(exc).__name__}). "
                    "Start it with `docker compose up -d minio`, or point the drill "
                    "elsewhere with --s3-endpoint. The object-storage leg is not "
                    "optional: skipping it is how a drill 'passes' without ever having "
                    "left the machine."
                ) from exc
            server = _scalar(self.dsns.maintenance, "SHOW server_version")
            step.facts.update(
                {
                    "postgres": str(server),
                    "pg_dump": _tool_version("pg_dump"),
                    "age": _tool_version("age"),
                    "s3_endpoint": endpoint,
                }
            )
            step.detail = f"postgres {server}, age {_tool_version('age')}, s3 at {endpoint}"

    # -- 2. provision the source database ---------------------------------------

    def provision(self) -> None:
        with self.stage("provision-source") as step:
            self._createdb(self.source_db)
            owner = self.dsns.owner(self.source_db)
            migrate = _run(
                ["uv", "run", "alembic", "upgrade", "head"],
                env=self._child_env(self.source_db),
            )
            if migrate.returncode != 0:
                raise DrillError(f"alembic upgrade head failed: {_tail(migrate)}")
            self.expected_head = str(_scalar(owner, "SELECT version_num FROM alembic_version"))
            self._seed(owner)
            self.expected_counts = self._counts(owner)
            step.facts.update({"alembic_head": self.expected_head, **self.expected_counts})
            step.detail = (
                f"{self.source_db} at head {self.expected_head}, "
                f"{self.expected_counts['leads']} leads across 2 tenants, "
                f"{self.expected_counts['audit_log']} audit entries"
            )

    def _createdb(self, name: str) -> None:
        assert_scratch(name, self.dsns.protected)
        _execute(self.dsns.maintenance, [f'CREATE DATABASE "{name}"'])
        self.record.scratch_databases.append(name)

    def _child_env(self, database: str) -> dict[str, str]:
        """Everything a child process needs to be pointed at one scratch database.

        BOTH variables, always. `check_rls_coverage` prefers `ALEMBIC_DATABASE_URL` and
        the application reads `DATABASE_URL`; a child given only one of them falls back
        to `.env` for the other and connects to the database the drill must never touch.
        """
        return {
            "ALEMBIC_DATABASE_URL": self.dsns.owner_url(database),
            "DATABASE_URL": self.dsns.app_url(database),
        }

    def _seed(self, owner_dsn: str) -> None:
        """Tenant data as the owner; audit entries through `write_audit`.

        The ledger rows matter for a reason easy to miss: a row-level trigger only fires
        for a row that matches, so a ledger with no rows would let `append_only_enforced`
        pass against a database whose triggers had been dropped.

        Primary keys are supplied explicitly because `Base.id`'s default is a PYTHON
        default (`uuid7`), not a server default — raw INSERTs get no id from the
        database, and the failure is a NOT NULL violation rather than anything subtle.
        """
        statements = [
            "INSERT INTO organizations (id, name, slug, status) VALUES "
            f"('{TENANT_A}', 'Drill Tenant A', 'drill-tenant-a', 'active'), "
            f"('{TENANT_B}', 'Drill Tenant B', 'drill-tenant-b', 'active')",
            # The three disclosure columns together (D-163): the legacy bundle plus the
            # two halves it splits into. The drill's fixture is a real agent row and has
            # to satisfy the same NOT NULL/non-blank constraints a client's does.
            "INSERT INTO agents (id, tenant_id, name, direction, disclosure_line, "
            "ai_disclosure_line, recording_notice_line) VALUES "
            f"('{AGENT_A}', '{TENANT_A}', 'Drill A', 'inbound', "
            "'This is an AI assistant. This call is being recorded.', "
            "'This is an AI assistant.', 'This call is being recorded.'), "
            f"('{AGENT_B}', '{TENANT_B}', 'Drill B', 'inbound', "
            "'This is an AI assistant. This call is being recorded.', "
            "'This is an AI assistant.', 'This call is being recorded.')",
            # One admin and one user per tenant, seeded ONLY because three of the eight
            # ledgers below cannot exist without them: `platform_secrets.created_by` and
            # `preference_scrub_runs.recorded_by_admin_id` point at `admin_users`, and
            # `whatsapp_alert_optin_ledger.user_id` at `users`. Not fixtures for their own
            # sake — every row here exists to give a row-level trigger something to refuse.
            "INSERT INTO admin_users (id, email, name, role) VALUES "
            f"('{ADMIN_ID}', 'drill-operator@example.invalid', 'Drill Operator', 'operator')",
            "INSERT INTO users (id, email, name) VALUES "
            f"('{USER_A}', 'drill-a@example.invalid', 'Drill User A'), "
            f"('{USER_B}', 'drill-b@example.invalid', 'Drill User B')",
            # PLATFORM_SECRETS is not tenant-scoped, so it is seeded once rather than per
            # tenant. The bytes are literals, not a real wrap: nothing in the drill
            # decrypts this row — its whole job is to be a row the D-97 trigger can refuse
            # a `last_four` rewrite on.
            "INSERT INTO platform_secrets (key, version, ciphertext, nonce, dek_wrapped, "
            "dek_nonce, kek_version, last_four, created_by) VALUES "
            "('DRILL_FIXTURE_KEY', 1, '\\x01'::bytea, '\\x02'::bytea, '\\x03'::bytea, "
            f"'\\x04'::bytea, 1, '0000', '{ADMIN_ID}')",
        ]
        for tenant, agent, user, prefix in (
            (TENANT_A, AGENT_A, USER_A, "9111"),
            (TENANT_B, AGENT_B, USER_B, "9222"),
        ):
            for index in range(LEADS_PER_TENANT):
                statements.append(
                    "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, source, status) "
                    f"VALUES ('{_uuid7()}', '{tenant}', '{agent}', "
                    f"'+9{prefix}00{index:04d}', 'inbound_call', 'new')"
                )
            statements += [
                "INSERT INTO usage_events (id, tenant_id, unit_type, qty, unit_cost_paid) "
                f"VALUES ('{_uuid7()}', '{tenant}', 'platform_min', 12.5000, 6.0000)",
                "INSERT INTO consent_ledger (id, tenant_id, phone_e164, purpose, status) "
                f"VALUES ('{_uuid7()}', '{tenant}', '+9{prefix}000000', 'recording', 'granted')",
                "INSERT INTO credit_ledger (id, tenant_id, delta, reason, balance_after) "
                f"VALUES ('{_uuid7()}', '{tenant}', 1000.0000, 'topup', 1000.0000)",
                "INSERT INTO one_time_charges "
                "(id, tenant_id, kind, ref, description, amount, billing_month) VALUES "
                f"('{_uuid7()}', '{tenant}', 'setup_fee', 'drill-{tenant}', "
                "'Onboarding setup fee', 5000.0000, '2026-08')",
                # A GRANTED opt-in has to satisfy `granted_optin_is_evidenced` and
                # `names_one_recorder`, so the self-serve shape is the only one that is
                # one INSERT: the recorder IS the user, and the notice version is set.
                "INSERT INTO whatsapp_alert_optin_ledger (id, tenant_id, user_id, "
                "phone_e164, status, channel, notice_version, recorded_by_user_id) VALUES "
                f"('{_uuid7()}', '{tenant}', '{user}', '+9{prefix}000001', 'granted', "
                f"'self_serve_console', 'v1', '{user}')",
                # `campaign_id` is left NULL deliberately: the ONE update its trigger
                # permits is the `ON DELETE SET NULL` that clears a non-null campaign, so
                # a NULL here means the probe's `SET tenant_id = tenant_id` meets the
                # RAISE and not the permitted branch.
                "INSERT INTO preference_scrub_runs (id, tenant_id, provider, scrub_ref, "
                "scrubbed_at, expires_at, submitted_count, suppressed_count, "
                "recorded_by_admin_id) VALUES "
                f"('{_uuid7()}', '{tenant}', 'drill-provider', 'drill-ref-{prefix}', "
                "now(), now() + interval '30 days', 10, 2, "
                f"'{ADMIN_ID}')",
            ]
        _execute(owner_dsn, statements)

        # The audit chain is the one fixture that cannot be faked with INSERTs: its
        # hashes have to come from the writer whose output `verify_chain` recomputes.
        written = _run(
            [
                sys.executable,
                "-m",
                "scripts.restore_drill",
                "--internal-write-audit",
                str(AUDIT_ENTRIES),
            ],
            env=self._child_env(self.source_db),
        )
        if written.returncode != 0:
            raise DrillError(f"seeding the audit chain failed: {_tail(written)}")

    def _counts(self, dsn: str) -> dict[str, int]:
        tables = (
            "organizations",
            "agents",
            "leads",
            "usage_events",
            "consent_ledger",
            "credit_ledger",
            "one_time_charges",
            # The three ledgers the seed grew for the append-only probe. Counted for the
            # same reason the other five are: a restore that silently dropped a ledger's
            # rows would otherwise pass `row_counts` and then pass `append_only_enforced`
            # too, because an empty ledger is now skipped rather than probed.
            "whatsapp_alert_optin_ledger",
            "preference_scrub_runs",
            "platform_secrets",
            "audit_log",
        )
        union = " UNION ALL ".join(f"SELECT '{t}', count(*) FROM {t}" for t in tables)
        return {str(name): int(count) for name, count in _rows(dsn, union)}

    # -- 3. dump -----------------------------------------------------------------

    def dump(self) -> Path:
        with self.stage("dump") as step:
            options = production_dump_options()
            target = self.work / f"calevate-{self.record.stamp}.dump"
            # As the OWNER, which for this cluster is a superuser. That is not a hard
            # rule 1 violation and dump-offsite.sh explains why: rule 1 forbids the
            # admin role in APP code paths, and a backup is not one. It is also not
            # optional — see the `pg_dump_under_rls` check below for what a role
            # subject to the policies actually does.
            argv = apply_options(
                options,
                {"--file": str(target), "--dbname": self.dsns.owner(self.source_db)},
            )
            process = _run(["pg_dump", *argv])
            if process.returncode != 0:
                raise DrillError(f"pg_dump failed: {_tail(process)}")
            size = target.stat().st_size
            step.facts.update({"options": " ".join(options), "plaintext_bytes": size})
            step.detail = f"{size} bytes with production flags ({' '.join(options)})"
        return target

    # -- 4. encrypt --------------------------------------------------------------

    def encrypt(self, plaintext: Path) -> Path:
        with self.stage("encrypt") as step:
            identity = self.work / "drill-identity.txt"
            recipients = self.work / "drill-recipients.txt"
            keygen = _run(["age-keygen", "-o", str(identity)])
            if keygen.returncode != 0:
                raise DrillError(f"age-keygen failed: {_tail(keygen)}")
            identity.chmod(0o600)
            public = re.search(r"age1[0-9a-z]+", keygen.stderr or "")
            if not public:
                raise DrillError("age-keygen printed no public key")
            recipients.write_text(public.group(0) + "\n", encoding="utf-8")

            encrypted = plaintext.with_suffix(".dump.age")
            options = production_age_options()
            argv = apply_options(
                options,
                {"--recipients-file": str(recipients), "--output": str(encrypted)},
            )
            process = _run(["age", *argv, str(plaintext)])
            if process.returncode != 0:
                raise DrillError(f"age encryption failed: {_tail(process)}")
            # dump-offsite.sh removes the plaintext immediately: it is every phone number
            # and transcript in the platform, and it exists for seconds. Same here.
            plaintext.unlink()
            self.digest = _sha256(encrypted)
            step.facts.update(
                {
                    "options": " ".join(options),
                    "encrypted_bytes": encrypted.stat().st_size,
                    "sha256": self.digest,
                }
            )
            step.detail = (
                f"age {' '.join(options)} -> {encrypted.stat().st_size} bytes, "
                f"sha256 {self.digest[:16]}…; plaintext removed"
            )
        return encrypted

    # -- 5. upload ---------------------------------------------------------------

    def upload(self, encrypted: Path) -> None:
        with self.stage("upload") as step:
            self.s3.create_bucket(Bucket=self.bucket)
            self.bucket_created = True
            self.s3.upload_file(str(encrypted), self.bucket, self.key)

            # The same evidence document dump-offsite.sh writes, field for field, so the
            # §10 restore path (`sha256sum -c` against the evidence file) is exercised
            # rather than assumed.
            evidence = {
                "artifact": self.artifact,
                "sha256": self.digest,
                "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "pg_version": str(_scalar(self.dsns.maintenance, "SHOW server_version")),
                "plaintext_bytes": self._stage_fact("dump", "plaintext_bytes"),
                "encrypted_bytes": encrypted.stat().st_size,
                "encryption": "age",
            }
            evidence_path = self.work / self.evidence_name
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
            self.s3.upload_file(str(evidence_path), self.bucket, self.evidence_key)

            if self.record.sabotage == "corrupt-object":
                self._corrupt_object()

            step.facts.update({"bucket": self.bucket, "key": self.key})
            step.detail = f"s3://{self.bucket}/{self.key} + evidence json"

    def _corrupt_object(self) -> None:
        """Flip one byte of the stored ciphertext, the way a silently bad copy looks."""
        body = self.s3.get_object(Bucket=self.bucket, Key=self.key)["Body"].read()
        index = len(body) // 2
        mutated = body[:index] + bytes([body[index] ^ 0xFF]) + body[index + 1 :]
        self.s3.put_object(Bucket=self.bucket, Key=self.key, Body=mutated)
        print(f"    [SABOTAGE] flipped byte {index} of s3://{self.bucket}/{self.key}")

    def _stage_fact(self, stage: str, key: str) -> Any:
        for step in self.record.stages:
            if step.name == stage:
                return step.facts.get(key)
        return None

    # -- 6. object-store fidelity -------------------------------------------------

    def probe_object_store(self) -> None:
        """Measure the S3 behaviours that differ between stand-in and real provider.

        Recorded rather than asserted: this stage cannot fail the drill, because what it
        finds is a statement about the stand-in's fidelity, not about our backups. What
        it prevents is the reader concluding that a green MinIO run says anything about
        R2 or about the offsite provider.
        """
        with self.stage("object-store-fidelity") as step:
            facts: dict[str, Any] = {}
            head = self.s3.head_object(Bucket=self.bucket, Key=self.key)
            facts["single_put_etag_is_md5"] = "-" not in head["ETag"].strip('"')

            # Multipart: the ETag stops being a content hash, which is exactly why
            # dump-offsite.sh re-downloads and re-hashes instead of trusting `--checksum`.
            part = b"c" * (5 * 1024 * 1024)
            multipart_key = f"{self.key}.multipart-probe"
            upload = self.s3.create_multipart_upload(Bucket=self.bucket, Key=multipart_key)
            parts = []
            for number in (1, 2):
                result = self.s3.upload_part(
                    Bucket=self.bucket,
                    Key=multipart_key,
                    PartNumber=number,
                    UploadId=upload["UploadId"],
                    Body=part,
                )
                parts.append({"ETag": result["ETag"], "PartNumber": number})
            self.s3.complete_multipart_upload(
                Bucket=self.bucket,
                Key=multipart_key,
                UploadId=upload["UploadId"],
                MultipartUpload={"Parts": parts},
            )
            multipart_etag = self.s3.head_object(Bucket=self.bucket, Key=multipart_key)["ETag"]
            facts["multipart_etag"] = multipart_etag.strip('"')
            facts["multipart_etag_is_content_hash"] = "-" not in multipart_etag.strip('"')

            listed = self.s3.list_objects_v2(Bucket=self.bucket, Prefix="postgres/")
            facts["list_objects_v2"] = f"{listed.get('KeyCount', 0)} keys"

            facts["object_lock"] = _probe(
                lambda: self.s3.get_object_lock_configuration(Bucket=self.bucket)
            )
            facts["additional_checksum_sha256"] = _probe(
                lambda: self.s3.put_object(
                    Bucket=self.bucket,
                    Key=f"{self.key}.checksum-probe",
                    Body=b"probe",
                    ChecksumAlgorithm="SHA256",
                )
            )
            step.facts.update(facts)
            step.detail = (
                f"multipart ETag {'is' if facts['multipart_etag_is_content_hash'] else 'is NOT'} "
                f"a content hash; object-lock: {facts['object_lock']}; "
                f"x-amz-checksum-sha256: {facts['additional_checksum_sha256']}"
            )

    # -- 7. fetch + verify the artifact against its evidence ---------------------

    def fetch(self) -> Path:
        with self.stage("fetch") as step:
            fetched = self.work / "roundtrip.dump.age"
            evidence_path = self.work / "roundtrip.evidence.json"
            self.s3.download_file(self.bucket, self.key, str(fetched))
            self.s3.download_file(self.bucket, self.evidence_key, str(evidence_path))
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            actual = _sha256(fetched)
            step.facts.update({"expected_sha256": evidence["sha256"], "actual_sha256": actual})
            if actual != evidence["sha256"]:
                # database-restore.md §10 tells the operator to run exactly this check
                # before decrypting. It is the one that catches a bucket whose object is
                # not what we uploaded — the case `rclone copy --checksum` can miss on a
                # store that reports a multipart ETag.
                raise DrillError(
                    "artifact digest mismatch: the object in the bucket does not hash to "
                    f"its evidence file ({actual[:16]}… != {evidence['sha256'][:16]}…). "
                    "Treat the backup as absent."
                )
            step.detail = f"downloaded {fetched.stat().st_size} bytes, sha256 matches evidence"
        return fetched

    # -- 8. decrypt + restore ----------------------------------------------------

    def decrypt(self, encrypted: Path) -> Path:
        with self.stage("decrypt") as step:
            plaintext = self.work / "restored.dump"
            process = _run(
                [
                    "age",
                    "--decrypt",
                    "--identity",
                    str(self.work / "drill-identity.txt"),
                    "--output",
                    str(plaintext),
                    str(encrypted),
                ]
            )
            if process.returncode != 0:
                raise DrillError(f"age --decrypt failed: {_tail(process)}")
            step.facts["plaintext_bytes"] = plaintext.stat().st_size
            step.detail = f"{plaintext.stat().st_size} bytes recovered"
        return plaintext

    def restore(self, plaintext: Path) -> None:
        with self.stage("restore") as step:
            self._createdb(self.restore_db)
            process = _run(
                [
                    "pg_restore",
                    f"--dbname={self.dsns.owner(self.restore_db)}",
                    "--jobs=2",
                    str(plaintext),
                ]
            )
            if process.returncode != 0:
                raise DrillError(f"pg_restore failed: {_tail(process, 12)}")
            step.detail = f"restored into {self.restore_db}"
        if self.record.sabotage in {
            "drop-rls-policy",
            "disable-append-only-trigger",
            "tamper-audit-row",
        }:
            self._sabotage_database()

    def _sabotage_database(self) -> None:
        assert_scratch(self.restore_db, self.dsns.protected)
        dsn = self.dsns.owner(self.restore_db)
        kind = self.record.sabotage
        if kind == "drop-rls-policy":
            _execute(dsn, ["DROP POLICY tenant_isolation ON leads"])
            print("    [SABOTAGE] dropped tenant_isolation on leads in the restored copy")
        elif kind == "disable-append-only-trigger":
            table, trigger = self._first_append_only_trigger(dsn)
            _execute(dsn, [f'ALTER TABLE {table} DISABLE TRIGGER "{trigger}"'])
            print(f"    [SABOTAGE] disabled {trigger} on {table} in the restored copy")
        elif kind == "tamper-audit-row":
            table = "audit_log"
            _, trigger = self._first_append_only_trigger(dsn, table=table)
            entry = _scalar(dsn, f"SELECT id FROM {table} ORDER BY at LIMIT 1")
            # An attacker with owner rights would have to do exactly this: the trigger
            # blocks the edit, so it has to come off first and go back on afterwards.
            # The point of the drill is that the hash chain notices anyway.
            #
            # RE-ARMED IN THE MODE IT WAS IN, read from the catalog rather than assumed.
            # Plain `ENABLE TRIGGER` always sets `tgenabled = 'O'` (ORIGIN), so re-arming
            # an `ENABLE ALWAYS` trigger (which every append-only trigger has been since
            # migration a2e9f31c605d) quietly demotes it — the drill would leave the
            # restored copy weaker than the backup it came from, and a subsequent
            # immutability check on that copy would fail for a reason the drill caused.
            mode = _scalar(
                dsn,
                "SELECT tgenabled FROM pg_trigger "
                f"WHERE tgrelid = '{table}'::regclass AND tgname = '{trigger}'",
            )
            rearm = {"A": "ENABLE ALWAYS", "R": "ENABLE REPLICA"}.get(str(mode), "ENABLE")
            _execute(
                dsn,
                [
                    f'ALTER TABLE {table} DISABLE TRIGGER "{trigger}"',
                    f"UPDATE {table} SET action = 'drill.tampered' WHERE id = '{entry}'",
                    f'ALTER TABLE {table} {rearm} TRIGGER "{trigger}"',
                ],
            )
            print(f"    [SABOTAGE] edited {table} row {entry} and re-armed its trigger")

    def _first_append_only_trigger(self, dsn: str, table: str | None = None) -> tuple[str, str]:
        wanted = table or _append_only_tables()[0]
        rows = _rows(
            dsn,
            "SELECT c.relname, t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
            "WHERE NOT t.tgisinternal AND c.relname = %s",
            (wanted,),
        )
        if not rows:
            raise DrillError(f"no non-internal trigger on {wanted} to sabotage")
        return str(rows[0][0]), str(rows[0][1])

    # -- 9. verify ---------------------------------------------------------------

    def verify(self) -> None:
        with self.stage("verify") as step:
            owner = self.dsns.owner(self.restore_db)
            self._check_alembic_head(owner)
            self._check_rls_coverage()
            self._check_cross_tenant(owner)
            self._check_ledger_immutability()
            self._check_append_only_enforced(owner)
            self._check_audit_chain()
            self._check_counts(owner)
            self._check_pg_dump_under_rls()
            failed = [c.name for c in self.record.checks if not c.ok]
            step.ok = not failed
            step.detail = (
                f"{len(self.record.checks)} checks, all green"
                if not failed
                else f"{len(failed)} of {len(self.record.checks)} FAILED: {', '.join(failed)}"
            )

    def _check_alembic_head(self, dsn: str) -> None:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        scripts = ScriptDirectory.from_config(Config(str(REPO_ROOT / "alembic.ini")))
        expected = set(scripts.get_heads())
        actual = str(_scalar(dsn, "SELECT version_num FROM alembic_version"))
        self.check(
            "alembic_head",
            actual in expected and actual == self.expected_head,
            f"restored at {actual}; repo heads {sorted(expected)}; source was {self.expected_head}",
        )

    def _check_rls_coverage(self) -> None:
        """The repository's own guardrail, run against the restored database.

        Reused rather than reimplemented, and reused as a SUBPROCESS because it resolves
        its connection out of the environment — which is precisely what makes it
        re-pointable at a restore. `database-restore.md` §7.5 already tells an operator
        to run it here by hand.
        """
        process = _run(
            [sys.executable, "-m", "scripts.check_rls_coverage"],
            env=self._child_env(self.restore_db),
        )
        self.check(
            "rls_coverage",
            process.returncode == 0,
            (process.stdout or process.stderr).strip().splitlines()[0]
            if (process.stdout or process.stderr).strip()
            else "no output",
            output=(process.stdout or "").strip(),
        )

    def _check_cross_tenant(self, owner_dsn: str) -> None:
        """Behaviour, not catalogue: read restored rows as the unprivileged app role.

        `check_rls_coverage` proves the policy exists and consults the GUC. Only this
        proves it isolates the rows that actually came back.
        """
        app_dsn = self.dsns.app(self.restore_db)
        try:
            seen_a = _tenant_visible_leads(app_dsn, TENANT_A)
            seen_b = _tenant_visible_leads(app_dsn, TENANT_B)
            unset = _tenant_visible_leads(app_dsn, None)
        except Exception as exc:
            self.check("cross_tenant_isolation", False, f"probe could not run: {exc!r}")
            return
        rows_a = _scalar(owner_dsn, "SELECT count(*) FROM leads WHERE tenant_id = %s", (TENANT_A,))
        ok = seen_a == rows_a and seen_b == LEADS_PER_TENANT and unset == 0 and seen_a > 0
        self.check(
            "cross_tenant_isolation",
            ok,
            f"as calevate_app: tenant A sees {seen_a} of its {rows_a} leads, tenant B "
            f"sees {seen_b}, no GUC set sees {unset} (must be 0)",
            tenant_a_visible=seen_a,
            tenant_b_visible=seen_b,
            untenanted_visible=unset,
        )

    def _check_ledger_immutability(self) -> None:
        process = _run(
            [sys.executable, "-m", "scripts.check_ledger_immutability"],
            env=self._child_env(self.restore_db),
        )
        lines = (process.stdout or process.stderr).strip().splitlines()
        self.check(
            "ledger_immutability",
            process.returncode == 0,
            lines[0] if lines else "no output",
            output=(process.stdout or "").strip(),
        )

    def _check_append_only_enforced(self, dsn: str) -> None:
        """Actually try to break each ledger and require the database to refuse.

        Runs as the OWNER, which on this cluster is a superuser: a trigger that stops the
        most privileged role is the only one worth having. Every statement runs inside a
        transaction that is rolled back, and `assert_scratch` has already established
        that this database is a drill artifact.
        """
        import psycopg

        assert_scratch(self.restore_db, self.dsns.protected)
        # AN EMPTY LEDGER PROVES NOTHING, AND MUST NOT LOOK LIKE PROOF. Every one of
        # these triggers is `FOR EACH ROW`, so against a ledger with no rows `UPDATE` and
        # `DELETE` both succeed touching nothing — which `_raises` reads as "the database
        # did not refuse". `_seed`'s own docstring already names the hazard in the other
        # direction ("a ledger with no rows would let this pass against a database whose
        # triggers had been dropped"); what actually happened is the mirror image, because
        # `APPEND_ONLY_TABLES` grew three entries the seed was never taught about. The
        # drill then printed `NOT enforced on: whatsapp_alert_optin_ledger/UPDATE, ...`
        # against a database whose triggers were all present and correct — a RED quarterly
        # drill caused by the drill. Empty is reported as its own sentence so the next
        # ledger added to the registry fails LOUDLY here instead of silently expanding the
        # blind spot.
        empty = [
            table
            for table in _append_only_tables()
            if int(_scalar(dsn, f"SELECT count(*) FROM {table}")) == 0
        ]
        unprotected: list[str] = []
        for table in _append_only_tables():
            if table in empty:
                continue
            mutation = _append_only_probe_set(table)
            for verb, statement in (
                ("UPDATE", f"UPDATE {table} SET {mutation}"),
                ("DELETE", f"DELETE FROM {table}"),
            ):
                with psycopg.connect(dsn) as connection:
                    if not _raises(connection, statement):
                        unprotected.append(f"{table}/{verb}")
                    connection.rollback()
        problems: list[str] = []
        if unprotected:
            problems.append(f"NOT enforced on: {', '.join(unprotected)}")
        if empty:
            problems.append(
                f"UNTESTABLE (no rows to fire a FOR EACH ROW trigger, so this drill "
                f"proves nothing about them — teach `_seed` about them): {', '.join(empty)}"
            )
        self.check(
            "append_only_enforced",
            not problems,
            f"{len(_append_only_tables())} ledgers refused UPDATE and DELETE"
            if not problems
            else "; ".join(problems),
            ledgers=_append_only_tables(),
            untestable=empty,
        )

    def _check_audit_chain(self) -> None:
        process = _run(
            [sys.executable, "-m", "scripts.restore_drill", "--internal-verify-chain"],
            env=self._child_env(self.restore_db),
        )
        if process.returncode != 0 or not process.stdout.strip():
            self.check("audit_chain", False, f"verifier could not run: {_tail(process)}")
            return
        verdict = json.loads(process.stdout.strip().splitlines()[-1])
        # `verdict` IS THE VERIFIER'S OWN JSON and it carries a key called `ok`, which is
        # also `check`'s second POSITIONAL parameter — so `**verdict` raised
        # `TypeError: check() got multiple values for argument 'ok'` on EVERY run, and
        # `verify()` aborted here, before the row-count, recording and object-store checks
        # that follow it. The drill has therefore never once verified an audit chain it
        # restored, and the abort read as "unexpected TypeError" rather than as a defect
        # in this file. Renamed rather than dropped: the verifier's own verdict belongs in
        # the record, under a name that cannot collide with the recorder's signature.
        facts = {key: value for key, value in verdict.items() if key != "ok"}
        self.check(
            "audit_chain",
            bool(verdict["ok"]) and verdict["entries_checked"] == self.expected_counts["audit_log"],
            f"{verdict['entries_checked']} entries recomputed, complete={verdict['complete']}, "
            f"breaks={verdict['breaks_found']} {verdict['breaks'] or ''}".strip(),
            chain_ok=verdict["ok"],
            **facts,
        )

    def _check_counts(self, dsn: str) -> None:
        actual = self._counts(dsn)
        differences = {t: (self.expected_counts[t], actual.get(t)) for t in self.expected_counts}
        wrong = {t: v for t, v in differences.items() if v[0] != v[1]}
        self.check(
            "row_counts",
            not wrong,
            f"{sum(self.expected_counts.values())} rows across "
            f"{len(self.expected_counts)} tables match the source"
            if not wrong
            else f"mismatched: {wrong}",
            **actual,
        )

    def _check_pg_dump_under_rls(self) -> None:
        """What a dump taken by a role subject to the policies actually does.

        This is a check about `dump-offsite.sh`'s premise rather than about the restore,
        and it is here because the drill is the only place it is cheap to ask. It runs
        against the SOURCE database, which still exists at this point.
        """
        target = self.work / "rls-probe.dump"
        process = _run(
            [
                "pg_dump",
                "--format=custom",
                f"--file={target}",
                f"--dbname={self.dsns.app(self.source_db)}",
            ]
        )
        # THE INVARIANT IS "IT REFUSES", NOT "IT REFUSES WITH THIS SENTENCE".
        #
        # This check used to require the string `row-level security` in stderr, and it had
        # never once executed — `_check_audit_chain`, two lines earlier in `verify()`,
        # aborted the stage with a TypeError on every run since both were written in the
        # same commit. Run for the first time, it went RED on a correct database, because
        # pg_dump does not reach a policied table: `05bba2f3c19c` grants `calevate_app`
        # DML on tables, and `c5a9e34b71d0` grants USAGE (deliberately not SELECT) on the
        # one sequence in the schema — so pg_dump dies first on
        #
        #     ERROR:  permission denied for sequence platform_settings_revision_seq
        #
        # and only reaches
        #
        #     ERROR:  query would be affected by row-level security policy for table "…"
        #
        # if that grant is widened. Both were reproduced against pg_dump 16.13 here. Which
        # of the two arrives depends on the order pg_dump happens to walk the schema in,
        # which is not a property `dump-offsite.sh` rests on. What it rests on is that a
        # dump taken by the app role FAILS LOUDLY instead of writing a silently empty
        # backup, and a non-zero exit is exactly that. The reason is recorded rather than
        # required, so a future run that starts refusing for a THIRD reason is legible.
        stderr = process.stderr or ""
        reason = (
            "row-level security"
            if "row-level security" in stderr
            else "insufficient privilege"
            if "permission denied" in stderr
            else "other"
        )
        refused = process.returncode != 0
        self.check(
            "pg_dump_under_rls",
            refused,
            f"pg_dump as calevate_app is REFUSED ({reason}, exit {process.returncode}) "
            "— the loud failure, not a silent empty backup"
            if refused
            else f"pg_dump as calevate_app SUCCEEDED (exit {process.returncode}) — that is "
            "the silent, empty-but-successful backup dump-offsite.sh's tripwire exists for",
            exit_code=process.returncode,
            refusal=reason,
        )

    # -- 10. cleanup -------------------------------------------------------------

    def cleanup(self) -> None:
        with self.stage("cleanup") as step:
            dropped: list[str] = []
            if not self.args.keep:
                for name in list(self.record.scratch_databases):
                    assert_scratch(name, self.dsns.protected)
                    _execute(
                        self.dsns.maintenance,
                        [f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'],
                    )
                    dropped.append(name)
            # Only if we got as far as creating it: a drill that aborted in preflight has
            # no bucket, and reporting "cleanup failed: NoSuchBucket" would bury the real
            # reason it stopped under a second, invented failure.
            emptied = _empty_bucket(self.s3, self.bucket) if self.bucket_created else 0
            # The work directory held a decrypted copy of everything. Runbook §8.
            shutil.rmtree(self.work, ignore_errors=True)
            step.facts.update({"dropped": dropped, "objects_deleted": emptied})
            step.detail = (
                f"dropped {len(dropped)} scratch db(s), deleted {emptied} objects, "
                "removed the decrypted working copy"
                if not self.args.keep
                else f"--keep: {', '.join(self.record.scratch_databases)} LEFT IN PLACE "
                "(they contain a full copy of the seeded data)"
            )

    # -- orchestration -----------------------------------------------------------

    def run(self) -> int:
        print(
            f"restore drill {self.record.stamp}"
            f"{f' [sabotage: {self.record.sabotage}]' if self.record.sabotage else ''}"
        )
        try:
            self.preflight()
            self.provision()
            plaintext = self.dump()
            encrypted = self.encrypt(plaintext)
            self.upload(encrypted)
            self.probe_object_store()
            fetched = self.fetch()
            decrypted = self.decrypt(fetched)
            self.restore(decrypted)
            self.verify()
        except DrillError as exc:
            self.record.aborted = str(exc)
            print(f"\n  DRILL ABORTED: {exc}\n")
        except Exception as exc:
            # An unexpected exception is still a drill result, not a crash: the record
            # has to be written and the scratch resources have to be dropped either way.
            # The traceback goes to stderr so nothing is hidden by the tidier summary.
            traceback.print_exc()
            self.record.aborted = f"unexpected {type(exc).__name__}: {exc}"
        finally:
            try:
                self.cleanup()
            except Exception as exc:
                # The stage context already recorded the FAIL; this only makes sure a
                # cleanup that blew up cannot take the record down with it. Leftover
                # scratch databases are named in the record either way.
                print(f"  cleanup raised: {exc!r}", file=sys.stderr)
        record_path = write_record(self.record, Path(self.args.record_dir))
        print(render_console(self.record, record_path))
        if self.args.json:
            print(json.dumps(as_json(self.record), indent=2))
        return 0 if self.record.green else 1


class _StageContext:
    def __init__(self, drill: RestoreDrill, name: str) -> None:
        self.drill = drill
        self.step = Step(name=name, ok=True, detail="")

    def __enter__(self) -> Step:
        self.started = time.perf_counter()
        print(f"  -> {self.step.name}", flush=True)
        return self.step

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        self.step.seconds = time.perf_counter() - self.started
        if exc is not None:
            self.step.ok = False
            self.step.detail = str(exc)
        self.drill.record.stages.append(self.step)
        print(
            f"     [{self.step.mark}] {self.step.name} {self.step.seconds:.2f}s "
            f"— {self.step.detail}",
            flush=True,
        )
        return False


# --------------------------------------------------------------------------------------
# Helpers used by the stages.
# --------------------------------------------------------------------------------------


def _tool_version(tool: str) -> str:
    process = _run([tool, "--version"], timeout=30)
    lines = (process.stdout or process.stderr or "").strip().splitlines()
    return lines[0] if lines else "?"


def _probe(call: Any) -> str:
    """Run an S3 call for its ANSWER, including the error, which is the interesting half."""
    try:
        call()
    except Exception as exc:
        code = getattr(exc, "response", {}).get("Error", {}).get("Code", type(exc).__name__)
        return f"refused ({code})"
    return "supported"


def _append_only_tables() -> list[str]:
    """The ledger list, from the registry that also drives the guardrails."""
    from apps.api.db.registry import APPEND_ONLY_TABLES

    return list(APPEND_ONLY_TABLES)


def _uuid7() -> Any:
    """The repo's id generator (CLAUDE.md: uuid_v7), not a second one invented here."""
    from apps.api.db.base import uuid7

    return uuid7()


#: The migration's own words (05bba2f3c19c). Matching on it rather than on "any error"
#: is the difference between "the trigger refused" and "the statement happened to fail":
#: a typo'd column name also raises, and would otherwise be read as protection.
_APPEND_ONLY_REFUSAL = "append-only"


def _raises(connection: Any, statement: str) -> bool:
    import psycopg

    try:
        with connection.cursor() as cursor:
            cursor.execute(statement)
    except psycopg.errors.RaiseException as exc:
        return _APPEND_ONLY_REFUSAL in str(exc)
    except psycopg.Error:
        return False
    return False


def _tenant_visible_leads(app_dsn: str, tenant: UUID | None) -> int:
    import psycopg

    with psycopg.connect(app_dsn) as connection, connection.cursor() as cursor:
        if tenant is not None:
            cursor.execute("SELECT set_config('app.tenant_id', %s, false)", (str(tenant),))
        cursor.execute("SELECT count(*) FROM leads")
        row = cursor.fetchone()
        connection.rollback()
    return int(row[0]) if row else -1


def _empty_bucket(client: Any, bucket: str) -> int:
    deleted = 0
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket):
        keys = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
        if keys:
            client.delete_objects(Bucket=bucket, Delete={"Objects": keys})
            deleted += len(keys)
    client.delete_bucket(Bucket=bucket)
    return deleted


# --------------------------------------------------------------------------------------
# The record. `runbooks/backup-restore-drill.md` §9 asks for something somebody can read
# a year later; this writes it, in the same place and the same shape as the quarterly one.
# --------------------------------------------------------------------------------------


def as_json(record: Drill) -> dict[str, Any]:
    return {
        "kind": "local-restore-drill",
        "stamp": record.stamp,
        "started_at": record.started_at.isoformat(),
        "sabotage": record.sabotage,
        "verdict": record.verdict,
        "aborted": record.aborted,
        "total_seconds": round(record.total_seconds, 2),
        "stages": [
            {
                "name": s.name,
                "ok": s.ok,
                "seconds": round(s.seconds, 3),
                "detail": s.detail,
                "facts": s.facts,
            }
            for s in record.stages
        ],
        "checks": [
            {"name": c.name, "ok": c.ok, "detail": c.detail, "facts": c.facts}
            for c in record.checks
        ],
        "not_covered": [{"id": i, "what": w, "needs": n} for i, w, n in NOT_COVERED],
    }


def render_console(record: Drill, record_path: Path) -> str:
    lines = ["", "=" * 78, f"  VERDICT: {record.verdict}    ({record.total_seconds:.1f}s total)"]
    if record.aborted:
        lines.append(f"  aborted: {record.aborted}")
    for step in record.failures:
        lines.append(f"  FAILED  {step.name}: {step.detail}")
    lines += [
        "",
        "  COVERAGE: chain B (offsite logical dump) simulated on local infrastructure.",
        f"  This run tested {len(record.stages)} stages and {len(record.checks)} checks.",
        f"  It did NOT test {len(NOT_COVERED)} things, each named in the record:",
    ]
    lines += [f"    - {identifier}" for identifier, _, _ in NOT_COVERED]
    lines += [
        "",
        "  A green run here is NOT the quarterly drill and cannot be filed as one",
        "  (runbooks/backup-restore-drill.md §0a).",
        f"  record: {record_path}",
        "=" * 78,
    ]
    return "\n".join(lines)


def render_record(record: Drill) -> str:
    when = record.started_at.strftime("%Y-%m-%d %H:%M UTC")
    out = [
        f"# Local restore drill — {record.stamp}",
        "",
        "Produced by `make restore-drill` (`scripts/restore_drill.py`). This is the LOCAL",
        "harness record, not the quarterly drill record required by",
        "`runbooks/backup-restore-drill.md` §9 — see §0a there for how the two relate.",
        "",
        f"- Run at: {when}",
        "- Chain exercised: **B-local** — logical dump, `age`, S3-compatible object store,",
        "  fetch, decrypt, `pg_restore`, verify. The offsite provider is stood in for by the",
        "  MinIO in `docker-compose.yml`.",
        f"- Sabotage mode: {record.sabotage or 'none (green path)'}",
        f"- **Verdict: {record.verdict}**",
        f"- Wall clock: {record.total_seconds:.1f}s",
        "",
        "## Stages",
        "",
        "| stage | result | seconds | detail |",
        "|---|---|---:|---|",
    ]
    for step in record.stages:
        out.append(
            f"| `{step.name}` | {'ok' if step.ok else '**FAIL**'} | {step.seconds:.2f} | "
            f"{step.detail.replace('|', '/')} |"
        )
    out += ["", "## Verification", "", "| check | result | detail |", "|---|---|---|"]
    for check in record.checks:
        out.append(
            f"| `{check.name}` | {'ok' if check.ok else '**FAIL**'} | "
            f"{check.detail.replace('|', '/')} |"
        )
    if record.aborted:
        out += ["", f"**Aborted:** {record.aborted}"]

    facts = next((s.facts for s in record.stages if s.name == "object-store-fidelity"), {})
    if facts:
        out += ["", "## Object store fidelity (measured against the stand-in)", ""]
        out += [f"- `{key}`: {value}" for key, value in sorted(facts.items())]

    out += [
        "",
        "## Coverage — what this run did NOT test",
        "",
        "Each line needs the credential or account beside it. Until they are exercised on",
        "real infrastructure, that part of the backup chain remains a hypothesis",
        "(`infra/backup/README.md` §9).",
        "",
        "| not tested | what it needs |",
        "|---|---|",
    ]
    for identifier, what, needs in NOT_COVERED:
        out.append(f"| **{identifier}** — {what} | {needs} |")
    out += [
        "",
        "## Scratch resources created and destroyed",
        "",
        *[f"- database `{name}`" for name in record.scratch_databases],
        f"- object-store bucket `{record.bucket}`",
        "",
    ]
    return "\n".join(out)


def write_record(record: Drill, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    suffix = f"-{record.sabotage}" if record.sabotage else ""
    path = directory / f"restore-drill-local-{record.stamp}{suffix}.md"
    path.write_text(render_record(record), encoding="utf-8")
    return path


# --------------------------------------------------------------------------------------
# Internal entry points. They exist so the app-dependent halves run in their OWN process
# with `DATABASE_URL` pointed at a scratch database — the orchestrator itself imports no
# application module and needs no configuration.
# --------------------------------------------------------------------------------------


def _internal_write_audit(count: int) -> int:
    import asyncio

    from apps.api.compliance.audit import write_audit
    from apps.api.db.session import untenanted_session

    async def _write() -> None:
        for index in range(count):
            async with untenanted_session() as session:
                await write_audit(
                    session,
                    action="drill.seed",
                    actor_type="system",
                    tenant_id=TENANT_A if index % 2 == 0 else TENANT_B,
                    object_type="restore_drill",
                    object_id=str(uuid4()),
                )

    asyncio.run(_write())
    return 0


def _internal_verify_chain() -> int:
    import asyncio

    from apps.api.compliance.audit import verify_chain
    from apps.api.db.session import untenanted_session

    async def _verify() -> dict[str, Any]:
        async with untenanted_session() as session:
            verdict = await verify_chain(session)
        return {
            "ok": verdict.ok,
            "entries_checked": verdict.entries_checked,
            "complete": verdict.complete,
            "breaks_found": verdict.breaks_found,
            "breaks": [f"{b.entry_id}:{b.kind}" for b in verdict.breaks],
            "entries_under_retired_key": verdict.entries_under_retired_key,
        }

    print(json.dumps(asyncio.run(_verify())))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="restore_drill",
        description="Run the local half of the backup/restore drill end to end.",
    )
    parser.add_argument(
        "--sabotage",
        choices=SABOTAGE_KINDS,
        help="break exactly one thing and require the drill to go RED naming it",
    )
    parser.add_argument("--keep", action="store_true", help="leave scratch databases in place")
    parser.add_argument("--json", action="store_true", help="also print the record as JSON")
    parser.add_argument("--record-dir", default=str(DEFAULT_RECORD_DIR))
    # Defaults are docker-compose.yml's MinIO service, so a developer who ran `make up`
    # needs no arguments at all. Overridable for a drill against another S3 endpoint.
    parser.add_argument(
        "--s3-endpoint", default=os.environ.get("DRILL_S3_ENDPOINT", "http://127.0.0.1:9000")
    )
    parser.add_argument(
        "--s3-access-key", default=os.environ.get("DRILL_S3_ACCESS_KEY", "calevate")
    )
    parser.add_argument(
        "--s3-secret-key", default=os.environ.get("DRILL_S3_SECRET_KEY", "calevate123")
    )
    parser.add_argument("--internal-write-audit", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--internal-verify-chain", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.internal_write_audit is not None:
        return _internal_write_audit(args.internal_write_audit)
    if args.internal_verify_chain:
        return _internal_verify_chain()

    try:
        return RestoreDrill(args).run()
    except DrillError as exc:
        print(f"restore drill refused to start: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
