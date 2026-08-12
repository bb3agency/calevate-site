"""Does the one alarm that says the DATABASE IS UNRECOVERABLE reach a human?

`scripts/backup/notify.sh` runs on the database host, under systemd, as `postgres` —
outside every Python process. Until this relay existed it wrote to journald and to an
optional `BACKUP_ALERT_COMMAND` that nothing configured, so "WAL archiving stopped" and
"last night's dump failed" were the two alarms in this repository that reached nobody
(D-50), while every application alarm reached an inbox (D-49).

What these tests pin, in the order they matter:

1. **It is routed by default.** A hook that must be configured to work is the defect,
   not the fix: `notify.sh` with NOTHING in its environment must still reach the
   application's alert path.
2. **It survives what it reports.** `alert()` was built to touch neither the database
   nor Redis so that it can report their loss (D-49). The relay is a second process, so
   that property has to be re-proved END TO END: the subprocess tests below point
   `DATABASE_URL` and `REDIS_URL` at a closed port and still require delivery.
3. **A stuck backup does not become an email every fifteen minutes.** `alert()`'s
   per-fingerprint suppression is in-process memory and this process lives for one
   alert, so the window is kept on disk here. Without it a broken chain sends ~96 mails
   a day, the operator filters the sender, and the alarm reaches nobody again — the
   original defect with extra steps.
4. **Hard rule 6** — ids, counts and our own message text; never a phone number.

The dead-man's-switch half is at the bottom: what `backup-health.sh` can now see about
its own schedule, and — stated as a test rather than a hope — what it cannot.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from apps.api.core import alerting
from apps.api.core.settings import get_settings

REPO_ROOT = Path(__file__).resolve().parents[1]
NOTIFY = REPO_ROOT / "scripts" / "backup" / "notify.sh"
RELAY = REPO_ROOT / "scripts" / "backup" / "alert-to-app.sh"
HEALTH = REPO_ROOT / "scripts" / "backup" / "backup-health.sh"
OPERATOR = "sri@calevate.tech"
PLANTED_PHONE = "+919876543210"

# A port nothing listens on. Whatever else these tests prove, they prove the alarm did
# not need a database or a Redis to be delivered.
DEAD_DSN = "postgresql+psycopg://nobody:nobody@127.0.0.1:1/nothing"
DEAD_REDIS = "redis://127.0.0.1:1/0"


# --- helpers ------------------------------------------------------------------


class RecordingTransport:
    """The same stand-in `tests/alert_delivery_test.py` uses, for the same reason."""

    name = "recording"

    def __init__(self, *, succeed: bool = True) -> None:
        self.succeed = succeed
        self.sent: list[dict[str, str]] = []
        self.arrived = threading.Event()

    def send(self, *, to: str, subject: str, body: str) -> bool:
        self.sent.append({"to": to, "subject": subject, "body": body})
        self.arrived.set()
        return self.succeed


@pytest.fixture
def transport(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    from apps.workers import transport as transport_module

    alerting.reset_alerts()
    recorder = RecordingTransport()
    monkeypatch.setattr(transport_module, "get_transport", lambda: recorder)
    monkeypatch.setattr(get_settings(), "alerts_email", OPERATOR)
    monkeypatch.setattr(alerting, "DELIVERY_RETRY_DELAY_S", 0.0)
    monkeypatch.setenv("CALEVATE_ALERT_STATE_DIR", str(tmp_path / "alert-state"))
    yield recorder
    alerting.reset_alerts()


def _relay(**fields: str) -> int:
    """Run the entry point in-process, the way the hook runs it with a JSON line.

    The stamp directory is an argument rather than an environment variable — see
    `host_alert._cli` — so the tests hold it in the env only for their own bookkeeping.
    """
    from scripts import host_alert

    line = {"failure_stage": "HOST_BACKUP", "code": "archive_stale", **fields}
    return host_alert.main(
        io.StringIO(json.dumps(line)), state_dir=Path(os.environ["CALEVATE_ALERT_STATE_DIR"])
    )


def _subprocess_env(**extra: str) -> dict[str, str]:
    """A host with no database, no Redis and no SMTP — only an operator address.

    `APP_ENV=local` selects `ConsoleTransport`, which reports success honestly (the
    message really was delivered — to a terminal). That is the only transport a sandbox
    can exercise, and it is enough: everything between `notify.sh` and
    `transport.send()` is the code under test.
    """
    env = dict(os.environ)
    env.pop("SMTP_HOST", None)
    env.update(
        {
            "APP_ENV": "local",
            "DATABASE_URL": DEAD_DSN,
            "REDIS_URL": DEAD_REDIS,
            "ALERTS_EMAIL": OPERATOR,
        }
    )
    env.update(extra)
    return env


# --- 1. it is routed, and routed BY DEFAULT ------------------------------------


def test_notify_sh_reaches_the_applications_alert_path_with_nothing_configured(
    tmp_path: Path,
) -> None:
    """The whole finding: no `BACKUP_ALERT_COMMAND`, and the alarm still arrives.

    An opt-in hook is how this alarm went unrouted for a whole milestone. The default
    is now the repo's own relay, and an operator who wants a pager overrides it.
    """
    env = _subprocess_env(CALEVATE_ALERT_STATE_DIR=str(tmp_path / "state"))
    env.pop("BACKUP_ALERT_COMMAND", None)
    proc = subprocess.run(
        [str(NOTIFY), "archive_stale", "no WAL segment has been archived recently"],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    # journald's line first — the durable record is never traded for the delivery.
    assert '"code":"archive_stale"' in proc.stderr
    assert "host_alert delivered" in proc.stderr, proc.stderr
    assert "alert_delivery_failed" not in proc.stderr


def test_the_alarm_needs_neither_the_database_nor_redis(tmp_path: Path) -> None:
    """D-49's deliberate property, re-proved across the process boundary.

    A notifier that needs the database is useless for "the database is gone". Both DSNs
    here point at a closed port; a relay that opened either would fail, not pass.
    """
    line = json.dumps(
        {"failure_stage": "HOST_BACKUP", "code": "wal_chain_broken", "detail": "a gap"}
    )
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.host_alert", "--state-dir", str(tmp_path / "state")],
        input=line,
        capture_output=True,
        text=True,
        env=_subprocess_env(CALEVATE_ALERT_STATE_DIR=str(tmp_path / "state")),
        cwd=REPO_ROOT,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert "host_alert delivered" in proc.stderr


def test_the_relay_wrapper_runs_without_the_repository_on_the_path(tmp_path: Path) -> None:
    """`alert-to-app.sh` is what the hook actually executes, from an arbitrary cwd.

    It resolves the interpreter and the repository from its OWN location, because a
    systemd unit's working directory is not the repository and a backup host is not
    where anyone wants a PYTHONPATH argument to be right.
    """
    line = json.dumps({"failure_stage": "HOST_BACKUP", "code": "unit_failed", "detail": "x"})
    proc = subprocess.run(
        [str(RELAY)],
        input=line,
        capture_output=True,
        text=True,
        env=_subprocess_env(CALEVATE_ALERT_STATE_DIR=str(tmp_path / "state")),
        cwd="/",
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert "host_alert delivered" in proc.stderr


# --- 2. the shape that arrives -------------------------------------------------


def test_the_alert_arrives_as_a_host_backup_alert_carrying_the_shell_ids(
    transport: RecordingTransport,
) -> None:
    assert _relay(detail="the archiver has not shipped a segment", host="db1", age_s="1800") == 0
    assert alerting.flush_alerts(timeout=5.0)
    (sent,) = transport.sent
    assert sent["to"] == OPERATOR
    assert "archive_stale" in sent["subject"]
    assert "stage:   HOST_BACKUP" in sent["body"]
    assert "age_s: 1800" in sent["body"]
    assert "host: db1" in sent["body"]


def test_a_stage_this_build_does_not_know_still_gets_through(
    transport: RecordingTransport,
) -> None:
    """Fail towards delivering, the way `backup-health.sh` parses wal-g output.

    The shell and the enum are versioned separately — a host running last release's
    `notify.sh` must not be silenced by a stage name this build has never heard of. The
    declared value rides along as an id so the mismatch is visible in the mail.
    """
    assert _relay(failure_stage="HOST_SOMETHING_NEW", code="archiver_failing") == 0
    assert alerting.flush_alerts(timeout=5.0)
    (sent,) = transport.sent
    assert "stage:   HOST_BACKUP" in sent["body"]
    assert "declared_stage: HOST_SOMETHING_NEW" in sent["body"]


def test_a_line_that_is_not_an_alert_is_refused_rather_than_guessed(
    transport: RecordingTransport,
) -> None:
    from scripts import host_alert

    assert host_alert.main(io.StringIO("not json at all")) == host_alert.EX_USAGE
    assert host_alert.main(io.StringIO('{"detail": "no code"}')) == host_alert.EX_USAGE
    assert transport.sent == []


def test_a_planted_phone_number_does_not_survive_into_the_relayed_alert(
    transport: RecordingTransport,
) -> None:
    """Hard rule 6. The scripts emit ids only, but the relay is the last gate before an
    email leaves the building, so it must hold even when the shell is wrong."""
    assert _relay(detail=f"caller {PLANTED_PHONE} was affected") == 0
    assert alerting.flush_alerts(timeout=5.0)
    (sent,) = transport.sent
    assert PLANTED_PHONE not in sent["body"]
    assert PLANTED_PHONE not in sent["subject"]


# --- 3. the storm bound, which the application's own window cannot supply -------


def test_a_repeat_inside_the_window_is_counted_not_resent(
    transport: RecordingTransport,
) -> None:
    """The health timer fires every 15 minutes and each run is a NEW process, so
    `alert()`'s in-memory window never sees the second occurrence."""
    assert _relay() == 0
    assert _relay() == 0
    assert _relay() == 0
    assert alerting.flush_alerts(timeout=5.0)
    assert len(transport.sent) == 1


def test_the_next_delivery_after_the_window_reports_what_it_swallowed(
    transport: RecordingTransport, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts import host_alert

    assert _relay() == 0
    assert _relay() == 0
    real_now = host_alert._now
    monkeypatch.setattr(
        host_alert, "_now", lambda: real_now() + alerting.ALERT_REPEAT_INTERVAL_S + 1
    )
    # In production each relay is a FRESH process, so `alert()`'s own in-memory window is
    # always empty on arrival — which is precisely why the on-disk one has to exist. Here
    # all three relays share one interpreter, so that window has to be reset to model the
    # process boundary rather than to soften anything.
    alerting.reset_alerts()
    assert _relay() == 0
    assert alerting.flush_alerts(timeout=5.0)
    assert len(transport.sent) == 2
    assert "repeats_suppressed: 1" in transport.sent[1]["body"]


def test_a_different_code_is_a_different_alarm(transport: RecordingTransport) -> None:
    assert _relay(code="archive_stale") == 0
    assert _relay(code="no_base_backup") == 0
    assert alerting.flush_alerts(timeout=5.0)
    assert len(transport.sent) == 2


def test_a_delivery_that_failed_does_not_start_a_window(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The window means "a human has been told". A transport that returned False told
    nobody — the same reason `alerting._forget` exists, applied to the on-disk stamp."""
    from apps.workers import transport as transport_module

    alerting.reset_alerts()
    failing = RecordingTransport(succeed=False)
    monkeypatch.setattr(transport_module, "get_transport", lambda: failing)
    monkeypatch.setattr(get_settings(), "alerts_email", OPERATOR)
    monkeypatch.setattr(alerting, "DELIVERY_RETRY_DELAY_S", 0.0)
    monkeypatch.setenv("CALEVATE_ALERT_STATE_DIR", str(tmp_path / "state"))
    from scripts import host_alert

    assert _relay() == host_alert.EX_UNAVAILABLE
    assert _relay() == host_alert.EX_UNAVAILABLE
    # Two occurrences, two attempts each — `alerting` retries once on the delivery
    # thread. The point of the count is that the SECOND occurrence was attempted at all:
    # a window started by a send that reached nobody would have swallowed it.
    assert len(failing.sent) == 4
    alerting.reset_alerts()


def test_an_unwritable_state_directory_sends_anyway(
    transport: RecordingTransport, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Fail OPEN on the bound, never on the alarm: a duplicate mail is a nuisance, a
    swallowed "the database is unrecoverable" is the incident."""
    blocked = tmp_path / "not-a-dir"
    blocked.write_text("this is a file, not a directory\n")
    monkeypatch.setenv("CALEVATE_ALERT_STATE_DIR", str(blocked / "state"))
    assert _relay() == 0
    alerting.reset_alerts()  # the process boundary these two relays would really have
    assert _relay() == 0
    assert alerting.flush_alerts(timeout=5.0)
    assert len(transport.sent) == 2


# --- 4. the couplings that would rot silently ----------------------------------


def test_an_unconfigured_recipient_fails_loudly_rather_than_silently(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`ALERTS_EMAIL` unset is the pre-launch state (OPERATIONS §8). It must exit
    non-zero so `notify.sh` records `alert_delivery_failed` in the journal, instead of
    a backup host quietly believing it has paging."""
    alerting.reset_alerts()
    monkeypatch.setattr(get_settings(), "alerts_email", None)
    monkeypatch.setenv("CALEVATE_ALERT_STATE_DIR", str(tmp_path / "state"))
    from scripts import host_alert

    assert _relay() == host_alert.EX_CONFIG
    alerting.reset_alerts()


def test_the_relay_reads_delivery_outcomes_that_alerting_actually_emits() -> None:
    """The relay learns whether a human was told by watching the alert logger, because
    `alert()` returns None by design (it is called from a signal handler). That is a
    coupling to event NAMES in a file this change does not own, so it is pinned: rename
    one there and this fails here, rather than the relay reporting success forever."""
    from scripts import host_alert

    source = (REPO_ROOT / "apps" / "api" / "core" / "alerting.py").read_text()
    for event in {host_alert.DELIVERED_EVENT, *host_alert.NOT_DELIVERED_EVENTS}:
        assert f'"{event}"' in source, f"{event} is no longer emitted by alerting.py"


def test_host_backup_is_a_member_of_the_enum_the_relay_passes_to() -> None:
    """`notify.sh`'s comments claimed this was not true. It is (D-50, commit 133e073),
    and the relay depends on it — a stage outside the Literal is a mypy error in every
    caller and a lie in the mail."""
    from typing import get_args

    assert "HOST_BACKUP" in get_args(alerting.FailureStage)


# --- 5. the dead man, and the half of it that cannot live here -----------------


def _run_health(tmp_path: Path, systemctl: str, **env: str) -> subprocess.CompletedProcess[str]:
    """`backup-health.sh` with a stubbed `systemctl` first on PATH.

    There is no systemd in this sandbox (`systemctl` here answers "System has not been
    booted with systemd"), so what is tested is the script's READING of systemd's
    answers — the branch, the threshold and the alert code — never systemd itself. The
    live behaviour is UNVALIDATED and the runbook says so.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / "systemctl"
    stub.write_text(systemctl)
    stub.chmod(0o755)
    environ = dict(os.environ)
    environ.update(
        {
            "PATH": f"{bin_dir}:{environ['PATH']}",
            "HEALTH_STATE_DIR": str(tmp_path / "state"),
            "WAL_VERIFY_STAMP": str(tmp_path / "state" / "wal-verify"),
            **env,
        }
    )
    (tmp_path / "state").mkdir(exist_ok=True)
    return subprocess.run(
        [str(HEALTH)], capture_output=True, text=True, env=environ, cwd=REPO_ROOT, timeout=300
    )


ARMED = """#!/bin/sh
echo "ActiveState=active"
echo "LastTriggerUSec=$(date -u '+%a %Y-%m-%d %H:%M:%S UTC')"
"""

DISARMED = """#!/bin/sh
echo "ActiveState=inactive"
echo "LastTriggerUSec=n/a"
"""

STALE = """#!/bin/sh
echo "ActiveState=active"
echo "LastTriggerUSec=Mon 2026-01-05 21:00:00 UTC"
"""


def test_a_timer_that_is_no_longer_armed_is_reported(tmp_path: Path) -> None:
    """The failure `OnFailure=` cannot see, because nothing ran to fail: a timer that
    was masked, disabled, or lost to a deploy that rewrote /etc/systemd/system."""
    proc = _run_health(tmp_path, DISARMED)
    assert proc.returncode == 1
    assert "backup_timer_inactive" in proc.stderr, proc.stderr


def test_a_timer_that_is_armed_but_has_not_fired_is_reported(tmp_path: Path) -> None:
    """Armed and silent — the shape of a `Persistent=true` timer whose stamp file was
    lost, or a calendar expression edited into never matching."""
    proc = _run_health(tmp_path, STALE)
    assert proc.returncode == 1
    assert "backup_timer_not_firing" in proc.stderr, proc.stderr


def test_an_armed_and_recently_fired_timer_says_nothing(tmp_path: Path) -> None:
    """A check that alerts on a healthy schedule is noise, and noise is how the real
    alert gets filtered."""
    proc = _run_health(tmp_path, ARMED)
    assert "backup_timer_inactive" not in proc.stderr
    assert "backup_timer_not_firing" not in proc.stderr


def test_a_gap_in_the_health_checks_own_schedule_is_reported_once_it_resumes(
    tmp_path: Path,
) -> None:
    """The internal half of the dead man: this run compares its own heartbeat against
    the last one, so a schedule that stopped for six hours is reported the moment it
    comes back — retroactively, which is the most an on-host check can do.

    It is NOT a dead-man's switch. While nothing runs, nothing reports; that residual
    needs an observer outside this host and is stated in `infra/backup/README.md` §5.
    """
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    stale_epoch = int(time.time()) - 6 * 3600
    (state / ".calevate-health-heartbeat").write_text(str(stale_epoch))
    proc = _run_health(tmp_path, ARMED)
    assert "backup_health_gap" in proc.stderr, proc.stderr
    # And the heartbeat is renewed, so the same gap is not re-reported forever.
    assert int((state / ".calevate-health-heartbeat").read_text()) > stale_epoch


def test_the_first_ever_run_does_not_report_a_gap(tmp_path: Path) -> None:
    """No heartbeat means "this host has never run the check", which is what a new
    install looks like — alerting on it would train the operator to ignore it."""
    proc = _run_health(tmp_path, ARMED)
    assert "backup_health_gap" not in proc.stderr
