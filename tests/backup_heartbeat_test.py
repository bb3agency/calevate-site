"""Does SILENCE page anybody? The external dead-man's switch (D-50's last residual).

Every other alarm in this repository is a MESSAGE: something broke, so something is
sent. All of them run inside the failure domain they watch, so the three failures that
matter most remove the observer along with the observed — the host being off, systemd
being gone, and the alert path being broken beyond us (`infra/backup/README.md` §5).
The fix inverts the polarity: `backup-health.sh` pings a hosted dead-man check when —
and only when — every backup check passed, and somebody else's uptime notices when the
pings stop.

What these tests pin, in the order they matter:

1. **The asymmetry.** A healthy run feeds the dead man; a run with ANY failing check
   feeds it nothing. That second half is the whole mechanism, so it is tested against
   the real script rather than argued in a comment: make the failure path emit and the
   test fails.
2. **A heartbeat is not a backup.** An undelivered ping must not fail the health run —
   the backup really was fine — but it must be loud, because the consequence is a page
   in one grace period's time.
3. **Unconfigured is stated, never silently passed.** No URL is the local, CI and
   pre-launch state; a host that believes it has a dead man and does not is the exact
   defect being closed.
4. **The ping URL is a credential** (anyone holding it can silence the alarm) and never
   reaches an operator log.
5. **It survives what it reports** — no database, no Redis, the property `alerting` was
   built with and that `tests/backup_alert_relay_test.py` proves for the mail path.

The vendor's own semantics (period, grace time, what its dashboard shows) are NOT
tested here — they are somebody else's service. They are proved by hand once, at the
drill (`runbooks/backup-restore-drill.md` §7.8).
"""

from __future__ import annotations

import ast
import http.server
import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

import pytest
from apps.api.core.settings import get_settings

REPO_ROOT = Path(__file__).resolve().parents[1]
HEALTH = REPO_ROOT / "scripts" / "backup" / "backup-health.sh"
HEARTBEAT = REPO_ROOT / "scripts" / "backup" / "heartbeat.sh"

# A distinctive path segment, so "did the credential leak into the log" is a substring
# question with no false positives.
CHECK_TOKEN = "c0ffee00-dead-man-5witch-000000000001"

DEAD_DSN = "postgresql+psycopg://nobody:nobody@127.0.0.1:1/nothing"
DEAD_REDIS = "redis://127.0.0.1:1/0"
# A port nothing listens on — "configured but unreachable", instantly.
CLOSED_PORT_URL = f"http://127.0.0.1:1/{CHECK_TOKEN}"


# --- a stand-in for the vendor -------------------------------------------------


class PingRecorder(http.server.BaseHTTPRequestHandler):
    received: ClassVar[list[tuple[str, str, str]]] = []
    status = 200

    def do_GET(self) -> None:  # BaseHTTPRequestHandler's spelling, not ours
        length = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(length).decode() if length else ""
        type(self).received.append(("GET", self.path, body))
        self.send_response(type(self).status)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, *args: object) -> None:
        """Silence: the stdlib default writes every request to stderr, which is the
        stream these tests read to check what the SCRIPT said."""


@pytest.fixture
def monitor() -> Iterator[type[PingRecorder]]:
    PingRecorder.received = []
    PingRecorder.status = 200
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), PingRecorder)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    PingRecorder.url = f"http://127.0.0.1:{server.server_port}/{CHECK_TOKEN}"  # type: ignore[attr-defined]
    try:
        yield PingRecorder
    finally:
        server.shutdown()
        server.server_close()


# --- a host on which every backup check passes ---------------------------------

# `psql`, `wal-g` and `systemctl` stubbed on PATH, exactly as the alert-relay suite does
# for `systemctl`: what is under test is the SCRIPT's decision, never the tools.
PSQL_HEALTHY = """#!/bin/sh
case "$*" in
  *pg_stat_archiver*) echo "4200|0|30|f" ;;
  *pg_ls_waldir*)     echo "3" ;;
  *)                  echo "" ;;
esac
"""

SYSTEMCTL_ARMED = """#!/bin/sh
echo "LoadState=loaded"
echo "ActiveState=active"
echo "LastTriggerUSec=$(date -u '+%a %Y-%m-%d %H:%M:%S UTC')"
"""

SYSTEMCTL_DISARMED = """#!/bin/sh
echo "LoadState=loaded"
echo "ActiveState=inactive"
echo "LastTriggerUSec=n/a"
"""


def _walg_healthy() -> str:
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"""#!/bin/sh
case "$1" in
  wal-verify)  echo '{{"integrity_check":{{"status":"OK"}},"timeline_check":{{"status":"OK"}}}}' ;;
  backup-list) echo '[{{"finish_time":"{now}"}}]' ;;
  *)           exit 1 ;;
esac
"""


def _stub(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text(body)
    path.chmod(0o755)


def _run_health(
    tmp_path: Path,
    *,
    systemctl: str = SYSTEMCTL_ARMED,
    heartbeat_url: str | None,
    **extra: str,
) -> subprocess.CompletedProcess[str]:
    """`backup-health.sh` on a host where everything is stubbed healthy unless a test
    says otherwise. Returns the completed process; stderr is where the script talks."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    _stub(bin_dir, "psql", PSQL_HEALTHY)
    _stub(bin_dir, "wal-g", _walg_healthy())
    _stub(bin_dir, "systemctl", systemctl)
    # The alert path is not the subject here, and the real default relay would start an
    # interpreter per alert. Recording them keeps the failure test honest about WHY it
    # failed without paying for delivery.
    alerts = tmp_path / "alerts.jsonl"
    _stub(bin_dir, "record-alert", f"#!/bin/sh\ncat >> {alerts}\n")
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    walg_config = tmp_path / "walg.json"
    walg_config.write_text("{}")

    env = dict(os.environ)
    env.pop("BACKUP_HEARTBEAT_URL", None)
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "HEALTH_STATE_DIR": str(state),
            "WAL_VERIFY_STAMP": str(state / "wal-verify"),
            "WALG_CONFIG_PATH": str(walg_config),
            "BACKUP_ALERT_COMMAND": str(bin_dir / "record-alert"),
            # `Settings` is one class, so these must be readable — and nothing in the
            # heartbeat path opens either of them. Pointing both at a closed port is how
            # that stays true rather than becoming a claim.
            "DATABASE_URL": DEAD_DSN,
            "REDIS_URL": DEAD_REDIS,
            "APP_ENV": "local",
            "NO_PROXY": "127.0.0.1,localhost",
            "no_proxy": "127.0.0.1,localhost",
        }
    )
    if heartbeat_url is not None:
        env["BACKUP_HEARTBEAT_URL"] = heartbeat_url
    env.update(extra)
    return subprocess.run(
        [str(HEALTH)], capture_output=True, text=True, env=env, cwd=REPO_ROOT, timeout=300
    )


# --- 1. the asymmetry, which IS the mechanism ----------------------------------


def test_a_healthy_run_feeds_the_external_dead_man(
    tmp_path: Path, monitor: type[PingRecorder]
) -> None:
    """The signal is emitted by the EXISTING backup path — no second scheduler — and it
    is a bare GET at the configured URL: no payload (hard rule 6 by construction) and no
    suffix, because `/start` and `/fail` would be a second meaning on one channel."""
    proc = _run_health(tmp_path, heartbeat_url=monitor.url)  # type: ignore[attr-defined]
    assert proc.returncode == 0, proc.stderr
    assert monitor.received == [("GET", f"/{CHECK_TOKEN}", "")], proc.stderr
    assert (tmp_path / "state" / ".calevate-heartbeat-state").read_text() == "sent"


def test_a_run_with_a_failing_check_feeds_the_dead_man_nothing_at_all(
    tmp_path: Path, monitor: type[PingRecorder]
) -> None:
    """THE test. A disarmed backup timer is a real failure (`backup_timer_inactive`),
    and the correct external behaviour is silence — the dead man fires on the missing
    ping, which is also what a dead host, a stopped systemd and a broken mail path
    produce. Ping on failure too and this alarm becomes "the script ran", which is
    green through a completely broken chain.
    """
    proc = _run_health(tmp_path, systemctl=SYSTEMCTL_DISARMED, heartbeat_url=monitor.url)  # type: ignore[attr-defined]
    assert proc.returncode == 1, proc.stderr
    assert "backup_timer_inactive" in proc.stderr
    assert monitor.received == [], "a failing backup run must never feed the dead man"


def test_the_dead_man_is_fed_by_the_backup_path_itself_not_by_a_second_schedule() -> None:
    """One emitter, and it is the health check that already knows the verdict.

    A separate timer pinging on its own schedule would answer "is this host up", not
    "are the backups working" — the two are different questions and only the second is
    worth a page. Pinned as a shape test because the drift is silent: someone adds a
    `heartbeat.timer`, everything looks greener, and the alarm stops meaning anything.
    """
    units = sorted((REPO_ROOT / "infra" / "backup" / "systemd").glob("*.timer"))
    assert [unit.name for unit in units] == [
        "calevate-backup-health.timer",
        "calevate-basebackup.timer",
        "calevate-dump-offsite.timer",
    ]
    health = (REPO_ROOT / "scripts" / "backup" / "backup-health.sh").read_text()
    assert "heartbeat.sh" in health


# --- 2. a heartbeat is not a backup --------------------------------------------


def test_an_undelivered_heartbeat_is_loud_but_does_not_fail_the_backup(
    tmp_path: Path,
) -> None:
    """The backup really was fine. Failing the run would turn one unreachable monitor
    into `basebackup.sh` treating tonight's backup as unproven (it calls this script and
    exits on a non-zero status) — a side channel breaking the thing it observes."""
    proc = _run_health(tmp_path, heartbeat_url=CLOSED_PORT_URL)
    assert proc.returncode == 0, proc.stderr
    assert "backup_heartbeat_undelivered" in proc.stderr
    assert "NOT delivered" in proc.stderr
    assert (tmp_path / "state" / ".calevate-heartbeat-state").read_text() == "failed"


# --- 3. unconfigured is stated, never silently passed --------------------------


def test_an_unconfigured_heartbeat_is_a_no_op_that_says_so(tmp_path: Path) -> None:
    """Local, CI and pre-launch all look like this. It must not crash, must not fail the
    run, and must not look armed."""
    proc = _run_health(tmp_path, heartbeat_url=None)
    assert proc.returncode == 0, proc.stderr
    assert "BACKUP_HEARTBEAT_URL is not set" in proc.stderr
    assert "NO external dead-man" in proc.stderr
    assert (tmp_path / "state" / ".calevate-heartbeat-state").read_text() == "unconfigured"


def test_the_unconfigured_notice_is_a_transition_not_a_drumbeat(tmp_path: Path) -> None:
    """Every 15 minutes forever is how a line stops being read. The state stamp is what
    keeps the journal carrying transitions; the stderr line is per-run by design, since
    that stream belongs to whoever ran the script."""
    first = _run_health(tmp_path, heartbeat_url=None)
    stamp = tmp_path / "state" / ".calevate-heartbeat-state"
    assert stamp.read_text() == "unconfigured"
    second = _run_health(tmp_path, heartbeat_url=None)
    assert first.returncode == second.returncode == 0
    assert stamp.read_text() == "unconfigured"


# --- 4. the ping URL is a credential -------------------------------------------


def test_the_ping_url_never_reaches_the_operator_log(
    tmp_path: Path, monitor: type[PingRecorder]
) -> None:
    """Anyone holding this URL can silence the alarm by pinging it, so it is a bearer
    secret in a repo where secrets never reach a log (hard rule 6's neighbour). A digest
    prefix is printed instead, which still answers "did the URL change"."""
    proc = _run_health(tmp_path, heartbeat_url=monitor.url)  # type: ignore[attr-defined]
    assert CHECK_TOKEN not in proc.stderr
    assert CHECK_TOKEN not in proc.stdout
    assert "host_heartbeat sent check=" in proc.stderr


# --- 5. it survives what it reports --------------------------------------------


def test_the_heartbeat_needs_neither_the_database_nor_redis(
    tmp_path: Path, monitor: type[PingRecorder]
) -> None:
    """Same deliberate property as the alert path, re-proved across the process
    boundary: both DSNs point at a closed port and the ping still lands. A heartbeat
    that needed the database would go quiet for "the database is gone" — the one
    scenario in which its silence is the most important signal we have."""
    env = dict(os.environ)
    env.update(
        {
            "DATABASE_URL": DEAD_DSN,
            "REDIS_URL": DEAD_REDIS,
            "APP_ENV": "local",
            "BACKUP_HEARTBEAT_URL": monitor.url,  # type: ignore[attr-defined]
            "NO_PROXY": "127.0.0.1,localhost",
            "no_proxy": "127.0.0.1,localhost",
        }
    )
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.host_heartbeat"],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert monitor.received == [("GET", f"/{CHECK_TOKEN}", "")]


def test_the_wrapper_runs_from_a_working_directory_that_is_not_the_repository(
    monitor: type[PingRecorder],
) -> None:
    """`heartbeat.sh` is what the health check executes and what an operator runs at the
    drill; like the alert relay it resolves interpreter, root and cwd from its OWN
    location, because a systemd unit's working directory is not the repository."""
    env = dict(os.environ)
    env.update(
        {
            "BACKUP_HEARTBEAT_URL": monitor.url,  # type: ignore[attr-defined]
            "APP_ENV": "local",
            "NO_PROXY": "127.0.0.1,localhost",
            "no_proxy": "127.0.0.1,localhost",
        }
    )
    proc = subprocess.run(
        [str(HEARTBEAT)], capture_output=True, text=True, env=env, cwd="/", timeout=120
    )
    assert proc.returncode == 0, proc.stderr
    assert len(monitor.received) == 1


# --- the module's own contract -------------------------------------------------


def test_a_monitor_answering_anything_but_200_is_not_a_heartbeat(
    monkeypatch: pytest.MonkeyPatch, monitor: type[PingRecorder]
) -> None:
    """A 404 for a deleted check and a 5xx are both "nobody is watching". Reading them
    as success is the silent-pass failure in its final form — and the retries are real,
    because the vendor documents that pings are lost to plain packet loss."""
    from scripts import host_heartbeat

    monitor.status = 503
    # Patched where it is READ. D-408 moved the retry loop into `apps/api/core/heartbeat.py`
    # for a second caller; D-410 deleted that caller (Azure OpenAI takes a static key, so
    # there is no credential-rotation loop to watch) and the extraction was reverted with
    # it, so the loop is back here. A shared module with one caller is indirection, not
    # sharing — and it had put an `apps.api.core` import at module scope in a script whose
    # discipline is to import as little as possible.
    monkeypatch.setattr(host_heartbeat, "PING_BACKOFF_S", 0.0)
    monkeypatch.setattr(get_settings(), "backup_heartbeat_url", monitor.url)  # type: ignore[attr-defined]
    assert host_heartbeat.main() == host_heartbeat.EX_UNAVAILABLE
    assert len(monitor.received) == host_heartbeat.PING_ATTEMPTS


def test_a_blank_url_is_unconfigured_rather_than_a_request_to_nowhere(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import host_heartbeat

    monkeypatch.setattr(get_settings(), "backup_heartbeat_url", "   ")
    assert host_heartbeat.main() == host_heartbeat.EX_CONFIG


def test_there_is_no_failure_signal_anywhere_in_the_heartbeat_path() -> None:
    """The vendor offers `/fail` and `/start`; using either would put two meanings on
    the channel whose entire value is that absence means trouble. Pinned as text because
    the temptation ("ping /fail so we know it broke") is a one-line edit that reads as
    an improvement and silently converts the dead man into a status page.
    """
    # BOTH FILES, and the second one is the point: D-408 moved the request itself into
    # `core/heartbeat.py` and left the argument here. A guard that kept scanning only
    # this file would have gone on passing while the code it was written to watch moved
    # out from under it — and it now also covers the worker's dead man, which pings the
    # same vendor from the same primitives (`vertex_credential._feed_dead_man`).
    # ONE file again. D-408 split the request out and this guard followed it into two
    # more; D-410 deleted both of those (the rotation loop and its shared ping), so the
    # code that puts a URL on the wire is back here alone. The guard must always name
    # every file that can make the request — that is the property, not the count.
    modules = (REPO_ROOT / "scripts" / "host_heartbeat.py",)
    for module in modules:
        tree = ast.parse(module.read_text())
        docstrings = {
            ast.get_docstring(node, clean=False)
            for node in ast.walk(tree)
            if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        }
        literals = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value not in docstrings
        ]
        # The prose ABOVE may name `/fail` — it argues at length about why we do not use
        # it. What must not exist is a string the code can put on the wire.
        for literal in literals:
            assert "/fail" not in literal, (
                f"a failure signal literal appeared in {module.name}: {literal!r}"
            )
        assert "/start" not in literal, f"a start signal literal appeared: {literal!r}"

    for script in (
        REPO_ROOT / "scripts" / "backup" / "heartbeat.sh",
        REPO_ROOT / "scripts" / "backup" / "backup-health.sh",
    ):
        code = "\n".join(
            line for line in script.read_text().splitlines() if not line.lstrip().startswith("#")
        )
        assert "/fail" not in code, f"{script.name} appears to emit a failure signal"
        assert "/start" not in code, f"{script.name} appears to emit a start signal"
