"""Relay a HOST-side alert into the application's alert path.

    scripts/backup/notify.sh  --(one JSON object on stdin)-->  python -m scripts.host_alert
                              --> apps.api.core.alerting.alert() --> workers/transport

WHY THIS FILE EXISTS. `alert()` delivers now (D-49: SMTP transport, per-fingerprint
suppression, an hourly bucket) and `HOST_BACKUP` is a member of its `FailureStage`. But
the backup chain runs on the DATABASE HOST, under systemd, as `postgres`, outside every
Python process — so the one alarm that says *the database is unrecoverable* was still
reaching journald and an optional `BACKUP_ALERT_COMMAND` that nothing configured (D-50).
This is the twenty lines that close that gap, and `notify.sh` now defaults to it rather
than waiting to be pointed at it: a hook that must be configured to fire is the defect,
not the fix.

WHY A SUBPROCESS, AND WHAT IT COSTS. Three shapes were available.

* *SMTP from the shell* — a second delivery mechanism with a second recipient, a second
  timeout and a second dedupe window, which is exactly the "two ways of doing one thing"
  the repo forbids. It would also put SMTP credentials in reach of a shell script on the
  database host. Rejected.
* *A long-lived local receiver* (socket, or a queue the app drains) — a third thing to
  run, to supervise and to be down at 3am, and anything the app drains is a component
  the alarm would then depend on. Rejected: the alarm must not need the platform to be
  healthy.
* *A subprocess into this entry point* — chosen. One implementation of "an alert reaches
  a human", one recipient, one transport, one set of bounds.

The cost, stated because it is real and an operator pays it:

1. **The application tree and its virtualenv must be on the database host.** True by
   construction in this deployment (D-26 puts PostgreSQL on the same VPS as the app),
   and NOT true if the database ever moves to its own box — at which point the honest
   answer is that the hook points at a small forwarder, not that this file grows a
   network protocol.
2. **~150ms of interpreter start per alert**, plus up to `FLUSH_TIMEOUT_S` waiting for
   the SMTP round trip. Paid by a backup script that has already failed, never by the
   voice path.
3. **`Settings` requires `DATABASE_URL`, `REDIS_URL` and the object-store keys to be
   READABLE**, because it is one settings class — so the `postgres` user needs either
   the repo's `.env` or a scoped `EnvironmentFile` (`infra/backup/README.md` §5). Note
   what this does NOT cost: nothing here opens either connection. That property is
   deliberate in `alerting` (it is why alerts do not ride the outbox) and
   `tests/backup_alert_relay_test.py` re-proves it end to end with both DSNs pointed at
   a closed port.

THE WINDOW IS ON DISK, AND THAT IS NOT A SECOND MECHANISM. `alert()` suppresses repeats
of one fingerprint for `ALERT_REPEAT_INTERVAL_S` in process memory. This process lives
for one alert, so that state is empty on every invocation and the suppression it
implements would never fire — while `backup-health.sh` runs every 15 minutes and a
broken chain emits several codes per run. Left alone that is ~96 mails a day, then a
filter rule, then an alarm that reaches nobody again: the original defect with extra
steps. So the window is kept as a stamp file per fingerprint. The NUMBER is imported
from `alerting`, never copied, and the semantics are the same three the application
implements — first occurrence sends, repeats are counted and ride the next delivery, a
FAILED delivery does not start a window (`alerting._forget`'s reasoning: the window
means "a human has been told", and a transport that returned False told nobody).

Exit status is the contract with `notify.sh`, which logs a second journald line when
this exits non-zero:

    0   delivered, or deliberately suppressed as a repeat
    64  the input was not an alert (EX_USAGE)
    69  nothing was delivered — transport failure (EX_UNAVAILABLE)
    78  no operator address is configured; there is nowhere to deliver (EX_CONFIG)

HARD RULE 6. Everything crossing this boundary is ids, counts and our own message text.
`alert()` runs `redact_mapping` over `detail` and every id before composing the mail, so
even a shell that got it wrong cannot put a phone number in an inbox.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
import time
from pathlib import Path
from typing import IO, get_args

from apps.api.core.alerting import (
    ALERT_REPEAT_INTERVAL_S,
    FailureStage,
    alert,
    flush_alerts,
)

# The stage every host-side alarm carries. A backup failure is not a pipeline stage, and
# mislabelling it as the nearest one (`WORKER_TERMINAL`) would make the alert lie about
# where to look — the argument recorded in `alerting.FailureStage` itself.
HOST_STAGE: FailureStage = "HOST_BACKUP"

# `alert()` returns None on purpose (it is reachable from a signal handler), so the only
# report of what happened to a notice is on this logger. Watching it is how this process
# learns whether a human was actually told — and it is a coupling to names in a file this
# change does not own, so `tests/backup_alert_relay_test.py` pins them.
ALERT_LOGGER = "calevate.alert"
DELIVERED_EVENT = "alert_delivered"
NOT_DELIVERED_EVENTS = frozenset(
    {
        "alert_delivery_failed",
        "alert_delivery_crashed",
        "alert_delivery_unconfigured",
        "alert_queue_overflow",
        "alert_dispatch_failed",
    }
)

# `postgres`'s home on a Debian/Ubuntu PostgreSQL host — the same place
# `backup-health.sh` keeps its wal-verify stamp, so there is one directory to reason
# about and one to `chown` when this is installed.
DEFAULT_STATE_DIR = Path("/var/lib/postgresql/.calevate-alert-state")

# Long enough for the transport's own budget — a 15-second SMTP timeout, one retry after
# `DELIVERY_RETRY_DELAY_S` — plus slack. Shorter than this would report "not delivered"
# for mail that was on its way; much longer would hold a systemd unit open on a host
# whose network is the thing that is broken.
FLUSH_TIMEOUT_S = 45.0

EX_USAGE = 64
EX_UNAVAILABLE = 69
EX_CONFIG = 78

# Keys of the JSON line that are the alert itself rather than ids to carry along.
_ENVELOPE = ("failure_stage", "code", "detail")


def _now() -> float:
    """Wall clock, not monotonic: the window survives a reboot, and a function so tests
    can move it. (`alerting` uses monotonic because its state dies with the process;
    this state outlives it, which is the whole point.)"""
    return time.time()


def _stamp(state_dir: Path, fingerprint: str) -> Path:
    """One file per fingerprint, named by digest — a code is free text from a shell and
    has no business becoming a path component."""
    return state_dir / hashlib.sha256(fingerprint.encode()).hexdigest()[:32]


def _read_window(path: Path) -> tuple[float, int]:
    """(last delivery, repeats counted since). Absent or unreadable = never sent."""
    try:
        last, _, count = path.read_text(encoding="utf-8").partition(" ")
        return (float(last), int(count or 0))
    except (OSError, ValueError):
        return (0.0, 0)


def _write_window(path: Path, last: float, count: int) -> bool:
    """Best effort. Returns whether the bound is in force, so failure is VISIBLE.

    Fails OPEN: an unwritable state directory means every occurrence is delivered, which
    is a nuisance. Failing closed would mean silently dropping the alarm this file
    exists to carry.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{last:.0f} {count}")
    except OSError as exc:
        print(f"host_alert: suppression state unavailable ({exc.strerror})", file=sys.stderr)
        return False
    return True


class _OutcomeWatcher(logging.Handler):
    """Collects the alert logger's event names for the life of one relay."""

    def __init__(self) -> None:
        super().__init__(level=logging.NOTSET)
        self.events: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.events.append(str(record.msg))

    @property
    def delivered(self) -> bool:
        return DELIVERED_EVENT in self.events

    @property
    def refused(self) -> bool:
        return any(event in NOT_DELIVERED_EVENTS for event in self.events)

    @property
    def unconfigured(self) -> bool:
        return "alert_delivery_unconfigured" in self.events


def _parse(stream: IO[str]) -> tuple[str, str, str | None, dict[str, str]] | None:
    """The JSON line `notify.sh` builds, or None if it is not an alert.

    Refuses rather than guesses on a missing `code`: the code IS the alarm's identity —
    it is the dedupe key, the mail subject and the thing an operator greps — and an
    alert called "unknown" is worse than a loud parse failure in the journal.
    """
    try:
        payload = json.load(stream)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    code = payload.get("code")
    if not isinstance(code, str) or not code.strip():
        return None
    detail = payload.get("detail")
    declared = str(payload.get("failure_stage") or HOST_STAGE)
    ids = {
        str(key): str(value)
        for key, value in payload.items()
        if key not in _ENVELOPE and value is not None
    }
    return (declared, code.strip(), str(detail) if detail is not None else None, ids)


def main(stream: IO[str] | None = None, *, state_dir: Path | None = None) -> int:
    payload = _parse(stream if stream is not None else sys.stdin)
    if payload is None:
        print(
            "host_alert: expected one JSON object with a `code` on stdin "
            "(as built by scripts/backup/notify.sh)",
            file=sys.stderr,
        )
        return EX_USAGE
    declared_stage, code, detail, ids = payload

    # A host running an older `notify.sh` must not be silenced by a stage name this
    # build has never heard of — the same "fail towards reporting" rule `backup-health.sh`
    # applies to wal-g's JSON. The declared value rides along as an id so the mismatch is
    # visible in the mail instead of being quietly normalised away.
    stage: FailureStage = HOST_STAGE
    if declared_stage != HOST_STAGE:
        if declared_stage in get_args(FailureStage):
            stage = declared_stage  # type: ignore[assignment]
        else:
            ids["declared_stage"] = declared_stage

    fingerprint = f"{stage}:{code}"
    stamp = _stamp(state_dir or DEFAULT_STATE_DIR, fingerprint)
    last_sent, repeats = _read_window(stamp)
    now = _now()
    if last_sent and now - last_sent < ALERT_REPEAT_INTERVAL_S:
        _write_window(stamp, last_sent, repeats + 1)
        # journald already carries this occurrence — `notify.sh` logged it before calling
        # here — so nothing is lost by not mailing it.
        print(f"host_alert suppressed code={code} repeats={repeats + 1}", file=sys.stderr)
        return 0
    if repeats:
        ids["repeats_suppressed"] = str(repeats)
    bounded = _write_window(stamp, now, 0)

    watcher = _OutcomeWatcher()
    logger = logging.getLogger(ALERT_LOGGER)
    previous_level = logger.level
    # `alert_delivered` is an INFO record; a relay that could not see it would report
    # failure for every successful delivery.
    logger.setLevel(logging.INFO)
    logger.addHandler(watcher)
    try:
        alert(stage, code, detail=detail, **ids)
        flush_alerts(timeout=FLUSH_TIMEOUT_S)
    finally:
        logger.removeHandler(watcher)
        logger.setLevel(previous_level)

    if watcher.delivered:
        print(f"host_alert delivered code={code} stage={stage}", file=sys.stderr)
        return 0
    # Nothing reached anyone. Undo the window (the same reason `alerting._forget` does),
    # so the next occurrence tries again rather than being suppressed by a send that
    # never landed.
    if bounded:
        _write_window(stamp, last_sent, repeats)
    if watcher.unconfigured:
        print(
            "host_alert: no operator address configured (ALERTS_EMAIL); the alert was "
            "logged and delivered NOWHERE",
            file=sys.stderr,
        )
        return EX_CONFIG
    reason = "transport reported failure" if watcher.refused else "delivery did not complete"
    print(f"host_alert: {reason}; code={code} was NOT delivered", file=sys.stderr)
    return EX_UNAVAILABLE


def _cli(argv: list[str] | None = None) -> int:
    """`--state-dir DIR` and nothing else.

    An ARGUMENT rather than an environment variable on purpose: a Python process in this
    repo reads config through `Settings` or not at all (`scripts/check_env_parity.py`
    enforces it), and a stamp directory is not application config — it is a path the
    caller owns. `alert-to-app.sh` is where the host's own override is read, because a
    shell wrapper is exactly the right place for a host path.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    state_dir: Path | None = None
    if args[:1] == ["--state-dir"] and len(args) == 2:
        state_dir = Path(args[1])
    elif args:
        print("usage: host_alert [--state-dir DIR]  (one JSON alert on stdin)", file=sys.stderr)
        return EX_USAGE
    return main(sys.stdin, state_dir=state_dir)


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess in tests
    raise SystemExit(_cli())


__all__ = [
    "DELIVERED_EVENT",
    "EX_CONFIG",
    "EX_UNAVAILABLE",
    "EX_USAGE",
    "HOST_STAGE",
    "NOT_DELIVERED_EVENTS",
    "main",
]
