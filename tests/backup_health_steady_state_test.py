"""Every backup-health alarm against a HEALTHY steady-state host, and against its failure.

Two production false alarms (wal_chain_broken, 29 Oct 2026; pg_wal_backlog, 30 Oct 2026)
had the same cause: the fixture standing in for "healthy" was not what a healthy host
looks like. So each healthy fixture here is derived from the shipped configuration, at
the WORST instant a healthy host reaches, and each check is pinned on both sides:
healthy steady state raises nothing, the real failure raises the alarm.

The table in `infra/backup/README.md` §5 ("Every alarm is tested against a healthy steady
state") is the prose form of this file.
"""

from __future__ import annotations

import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.backup_heartbeat_test import (
    DAY_TWO_WAL_BYTES,
    REPO_ROOT,
    WAL_LIMIT_BYTES,
    _run_health,
)
from tests.platform_support import requires_posix_shell

BACKUP = REPO_ROOT / "infra" / "backup"
ARCHIVING_CONF = BACKUP / "postgresql-archiving.conf"
BASEBACKUP_TIMER = BACKUP / "systemd" / "calevate-basebackup.timer"
HEALTH_TIMER = BACKUP / "systemd" / "calevate-backup-health.timer"
BASEBACKUP_SH = REPO_ROOT / "scripts" / "backup" / "basebackup.sh"

DAY_S = 86400


def _setting(path: Path, pattern: str) -> str:
    match = re.search(pattern, path.read_text(encoding="utf-8"), re.M)
    assert match, f"{pattern!r} is no longer in {path.name}"
    return match[1]


# --- the shipped configuration, read rather than retyped -------------------------

ARCHIVE_TIMEOUT_S = int(_setting(ARCHIVING_CONF, r"^\s*archive_timeout\s*=\s*(\d+)\s*$"))
STALL_S = 3 * ARCHIVE_TIMEOUT_S
KEEP_FULL = int(_setting(BASEBACKUP_SH, r"KEEP_FULL_BACKUPS:-(\d+)"))
BACKUP_JITTER_S = int(_setting(BASEBACKUP_TIMER, r"^RandomizedDelaySec=(\d+)\s*$"))
HEALTH_INTERVAL_S = 60 * int(_setting(HEALTH_TIMER, r"^OnUnitActiveSec=(\d+)min\s*$"))
#: The script's own allowances, as shipped.
BASEBACKUP_MAX_AGE_S = 129600
HEALTH_TIMER_MAX_AGE_S = 3600
HEALTH_GAP_S = 2700
#: ASSUMPTION, not a measurement: how long a nightly push of this database takes. Only
#: the healthy worst case leans on it, and it is far inside the 12 h of slack.
PUSH_DURATION_S = 15 * 60
#: The newest base backup at the worst healthy instant: just before tonight's finishes.
WORST_HEALTHY_BACKUP_AGE_S = DAY_S + BACKUP_JITTER_S + PUSH_DURATION_S


def test_the_derived_healthy_worst_cases_sit_inside_their_thresholds() -> None:
    """The arithmetic the fixtures below rely on, said once."""
    assert WORST_HEALTHY_BACKUP_AGE_S < BASEBACKUP_MAX_AGE_S
    assert DAY_S + BACKUP_JITTER_S < BASEBACKUP_MAX_AGE_S
    assert HEALTH_INTERVAL_S < HEALTH_TIMER_MAX_AGE_S
    assert HEALTH_INTERVAL_S < HEALTH_GAP_S
    # A busy cluster switches and ships within one interval; the alarm is at three.
    assert ARCHIVE_TIMEOUT_S + HEALTH_INTERVAL_S < STALL_S


# --- stubs ----------------------------------------------------------------------


def _psql(
    *,
    archive_age: int = 600,
    failing: bool = False,
    pending: bool = False,
    last_wal: str = "0000000100000000000000A4",
    archived: int = 35 * 48,
) -> str:
    """PostgreSQL on day 30: ~48 forced switches a day at the shipped interval."""
    row = (
        f"{archived}|0|{archive_age}|{'t' if failing else 'f'}|{'t' if pending else 'f'}|{last_wal}"
    )
    return f"""#!/bin/sh
case "$*" in
  *pg_settings*)             echo "{ARCHIVE_TIMEOUT_S}" ;;
  *pg_stat_archiver*)        echo "{row}" ;;
  *pg_ls_archive_statusdir*) echo "0" ;;
  *pg_ls_waldir*)            echo "{DAY_TWO_WAL_BYTES}|{WAL_LIMIT_BYTES}" ;;
  *)                         echo "" ;;
esac
"""


def _ist(epoch: float) -> str:
    """How `systemctl show` prints a timestamp on a host whose zone is IST."""
    from zoneinfo import ZoneInfo

    return datetime.fromtimestamp(epoch, ZoneInfo("Asia/Kolkata")).strftime(
        "%a %Y-%m-%d %H:%M:%S IST"
    )


def _systemctl(
    *,
    basebackup_last: str | None = None,
    basebackup_armed: str | None = None,
    health_last: str | None = None,
    health_armed: str | None = None,
) -> str:
    now = time.time()
    basebackup_last = (
        basebackup_last if basebackup_last is not None else _ist(now - DAY_S - BACKUP_JITTER_S)
    )
    basebackup_armed = basebackup_armed if basebackup_armed is not None else _ist(now - 30 * DAY_S)
    health_last = health_last if health_last is not None else _ist(now)
    health_armed = health_armed if health_armed is not None else _ist(now - 30 * DAY_S)
    return f"""#!/bin/sh
case "$2" in
  calevate-basebackup.timer) last="{basebackup_last}"; armed="{basebackup_armed}" ;;
  *)                         last="{health_last}"; armed="{health_armed}" ;;
esac
echo "LoadState=loaded"
echo "ActiveState=active"
echo "LastTriggerUSec=$last"
echo "ActiveEnterTimestamp=$armed"
"""


def _rfc3339(epoch: float) -> str:
    """Go's time.Time JSON form, which `backup-list --json` prints (wal-g v3.0.9
    internal/backup_time.go: backup_name, time, wal_file_name, storage_name)."""
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%dT%H:%M:%S.123456789Z")


def _walg(*, newest_backup_age_s: int = WORST_HEALTHY_BACKUP_AGE_S, sleep_s: int = 0) -> str:
    """wal-g against a day-30 archive: KEEP_FULL nightly backups and one unbroken chain."""
    now = time.time()
    backups = [
        {
            "backup_name": f"base_0000000100000000000000{i:02X}",
            "time": _rfc3339(now - newest_backup_age_s - (KEEP_FULL - 1 - i) * DAY_S),
            "wal_file_name": f"0000000100000000000000{i:02X}",
            "storage_name": "default",
        }
        for i in range(KEEP_FULL)
    ]
    verify = {
        "integrity": {
            "status": "OK",
            "details": [
                {
                    "timeline_id": 1,
                    "start_segment": "000000010000000000000001",
                    "end_segment": "0000000100000000000006A3",
                    "segments_count": KEEP_FULL * 48,
                    "status": "FOUND",
                }
            ],
        },
        "timeline": {
            "status": "OK",
            "details": {"current_timeline_id": 1, "highest_storage_timeline_id": 1},
        },
    }
    return f"""#!/bin/sh
{f"exec sleep {sleep_s}" if sleep_s else ""}
case "$1" in
  wal-verify)  echo '{json.dumps(verify)}' ;;
  backup-list) echo '{json.dumps(backups)}' ;;
  *)           exit 1 ;;
esac
"""


def _health(tmp_path: Path, **kwargs: str) -> tuple[int, str]:
    kwargs.setdefault("psql", _psql())
    kwargs.setdefault("systemctl", _systemctl())
    kwargs.setdefault("walg", _walg())
    proc = _run_health(tmp_path, heartbeat_url=None, **kwargs)
    return proc.returncode, proc.stderr


def _alarms(stderr: str) -> set[str]:
    return set(re.findall(r'"code":"([a-z_]+)"', stderr))


def _state(tmp_path: Path, name: str, content: str) -> None:
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    (state / name).write_text(content)


# --- the whole host ---------------------------------------------------------------


@requires_posix_shell
def test_a_day_30_host_at_its_worst_healthy_instant_raises_nothing(tmp_path: Path) -> None:
    """Every check at once: the previous run one interval ago, last night's backup as old
    as it gets before tonight's finishes, both timers armed for a month."""
    _state(tmp_path, ".calevate-health-heartbeat", str(int(time.time()) - HEALTH_INTERVAL_S))
    code, stderr = _health(tmp_path)
    assert _alarms(stderr) == set(), stderr
    assert code == 0, stderr


# --- 1 + 2. archiver -----------------------------------------------------------------


@requires_posix_shell
def test_a_quiet_night_with_nothing_archived_for_hours_is_not_stale(tmp_path: Path) -> None:
    """An idle cluster switches nothing, so last_archived_time ages all night. Nothing is
    waiting, so nothing is late."""
    code, stderr = _health(tmp_path, psql=_psql(archive_age=8 * 3600, pending=False))
    assert "archive_stale" not in stderr, stderr
    assert code == 0, stderr


@requires_posix_shell
def test_the_first_write_after_a_quiet_night_is_not_stale(tmp_path: Path) -> None:
    """The write that ends a quiet night waits up to one interval for its switch, while
    the last archive is hours old. Seen pending for the first time: the clock starts."""
    _, stderr = _health(tmp_path, psql=_psql(archive_age=8 * 3600, pending=True))
    assert "archive_stale" not in stderr, stderr
    stamp = (tmp_path / "state" / ".calevate-wal-pending-since").read_text().split()
    assert stamp[0] == "0000000100000000000000A4"


@requires_posix_shell
@pytest.mark.parametrize(("pending_for", "stale"), [(STALL_S - 60, False), (STALL_S + 60, True)])
def test_wal_waiting_behind_the_same_segment_for_three_intervals_is_stale(
    tmp_path: Path, pending_for: int, stale: bool
) -> None:
    last = "0000000100000000000000A4"
    _state(tmp_path, ".calevate-wal-pending-since", f"{last} {int(time.time()) - pending_for}\n")
    _, stderr = _health(
        tmp_path, psql=_psql(archive_age=pending_for + 300, pending=True, last_wal=last)
    )
    assert ("archive_stale" in _alarms(stderr)) is stale, stderr


@requires_posix_shell
def test_a_busy_cluster_that_keeps_archiving_never_accumulates(tmp_path: Path) -> None:
    """Pending on every run is normal while writes continue; each archive moves the key."""
    _state(
        tmp_path,
        ".calevate-wal-pending-since",
        f"0000000100000000000000A3 {int(time.time()) - 10 * STALL_S}\n",
    )
    _, stderr = _health(tmp_path, psql=_psql(pending=True, last_wal="0000000100000000000000A4"))
    assert "archive_stale" not in stderr, stderr


@requires_posix_shell
def test_nothing_pending_clears_the_clock(tmp_path: Path) -> None:
    _state(tmp_path, ".calevate-wal-pending-since", "0000000100000000000000A4 1\n")
    _health(tmp_path, psql=_psql(pending=False))
    assert not (tmp_path / "state" / ".calevate-wal-pending-since").exists()


@requires_posix_shell
def test_counters_reset_by_a_crash_are_not_never_succeeded(tmp_path: Path) -> None:
    """An unclean shutdown resets pg_stat_archiver: NULL last_archived_time on a working
    archiver, until the next segment leaves."""
    _, stderr = _health(
        tmp_path, psql=_psql(archive_age=-1, pending=True, last_wal="none", archived=0)
    )
    assert "archiver_never_succeeded" not in stderr, stderr


@requires_posix_shell
def test_an_archiver_that_never_succeeds_alarms_after_the_threshold(tmp_path: Path) -> None:
    _state(tmp_path, ".calevate-wal-pending-since", f"none {int(time.time()) - STALL_S - 60}\n")
    _, stderr = _health(
        tmp_path, psql=_psql(archive_age=-1, pending=True, last_wal="none", archived=0)
    )
    assert "archiver_never_succeeded" in _alarms(stderr), stderr


@requires_posix_shell
def test_one_failed_attempt_the_archiver_retries_is_not_an_alarm(tmp_path: Path) -> None:
    code, stderr = _health(tmp_path, psql=_psql(failing=True))
    assert "archiver_failing" not in stderr, stderr
    assert code == 0
    assert (tmp_path / "state" / ".calevate-archiver-failing-since").exists()


@requires_posix_shell
def test_an_archiver_still_failing_on_the_next_run_alarms(tmp_path: Path) -> None:
    _state(tmp_path, ".calevate-archiver-failing-since", str(int(time.time()) - HEALTH_INTERVAL_S))
    code, stderr = _health(tmp_path, psql=_psql(failing=True))
    assert "archiver_failing" in _alarms(stderr), stderr
    assert code == 1


@requires_posix_shell
def test_a_recovered_archiver_clears_its_failing_clock(tmp_path: Path) -> None:
    _state(tmp_path, ".calevate-archiver-failing-since", "1")
    _health(tmp_path)
    assert not (tmp_path / "state" / ".calevate-archiver-failing-since").exists()


# --- 3. the destination -------------------------------------------------------------


@requires_posix_shell
def test_a_missed_night_makes_the_base_backup_stale(tmp_path: Path) -> None:
    _, stderr = _health(tmp_path, walg=_walg(newest_backup_age_s=BASEBACKUP_MAX_AGE_S + 60))
    assert "base_backup_stale" in _alarms(stderr), stderr


@requires_posix_shell
def test_a_hung_wal_g_is_reported_and_the_rest_of_the_run_continues(tmp_path: Path) -> None:
    _, stderr = _health(
        tmp_path,
        walg=_walg(sleep_s=30),
        systemctl=_systemctl(basebackup_last="n/a", basebackup_armed=_ist(time.time() - 3 * DAY_S)),
        WALG_TIMEOUT_S="1",
    )
    assert {"wal_verify_failed", "backup_list_failed", "backup_timer_not_firing"} <= _alarms(
        stderr
    ), stderr


# --- 5. the schedule ----------------------------------------------------------------


@requires_posix_shell
def test_a_freshly_installed_nightly_timer_that_has_not_reached_0230_is_not_an_alarm(
    tmp_path: Path,
) -> None:
    now = time.time()
    _, stderr = _health(
        tmp_path,
        systemctl=_systemctl(basebackup_last="n/a", basebackup_armed=_ist(now - 11 * 3600)),
    )
    assert "backup_timer_not_firing" not in stderr, stderr


@requires_posix_shell
def test_the_health_timer_after_a_reboot_has_forgotten_its_last_trigger(tmp_path: Path) -> None:
    """Not Persistent=, so `n/a` until its OnBootSec run; basebackup.sh's catch-up run at
    boot calls the health check in exactly that window."""
    now = time.time()
    _, stderr = _health(
        tmp_path, systemctl=_systemctl(health_last="n/a", health_armed=_ist(now - 120))
    )
    assert "backup_timer_not_firing" not in stderr, stderr


@requires_posix_shell
@pytest.mark.parametrize(
    "systemctl_kwargs",
    [
        pytest.param(
            {"basebackup_last": "n/a", "basebackup_armed": "TS_OLD"}, id="armed-36h-never-fired"
        ),
        pytest.param({"basebackup_last": "TS_OLD"}, id="silent-36h"),
        pytest.param({"basebackup_last": "not a time"}, id="unparseable"),
    ],
)
def test_a_timer_that_stopped_firing_alarms(
    tmp_path: Path, systemctl_kwargs: dict[str, str]
) -> None:
    old = _ist(time.time() - BASEBACKUP_MAX_AGE_S - 600)
    kwargs = {k: (old if v == "TS_OLD" else v) for k, v in systemctl_kwargs.items()}
    _, stderr = _health(tmp_path, systemctl=_systemctl(**kwargs))
    assert "backup_timer_not_firing" in _alarms(stderr), stderr


# --- 6. the gap ---------------------------------------------------------------------


@requires_posix_shell
@pytest.mark.parametrize(
    ("since_s", "alarms"), [(HEALTH_INTERVAL_S + 60, False), (HEALTH_GAP_S + 60, True)]
)
def test_the_health_gap(tmp_path: Path, since_s: int, alarms: bool) -> None:
    _state(tmp_path, ".calevate-health-heartbeat", str(int(time.time()) - since_s))
    _, stderr = _health(tmp_path)
    assert ("backup_health_gap" in _alarms(stderr)) is alarms, stderr
