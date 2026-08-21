"""The whole local stack, and the only line of its output a developer actually needs.

Run: `uv run python -m scripts.dev`  (or `make dev-otp`)

WHAT THIS IS FOR. `make dev` starts four services whose combined output is a few hundred
JSON lines a minute, and buried in it, a few times an hour, is the ONE string that cannot
be obtained any other way: the six-digit code. Admin sign-in is password + emailed code
(D-170), every step-up action asks for another, and the plaintext exists in exactly one
place -- the message body `ConsoleTransport` prints (D-409). It is stored only as a keyed
hash, so grepping the database gets you nothing. In practice a developer either kept a
second terminal running `... | grep dev_message`, or gave up and stopped exercising the
second factor at all -- which is the code path most worth exercising.

So this runs the same four services and prints the codes, and by default prints almost
nothing else.

IT ALSO HEALS WHAT IT NEEDS, which is the other half of why it exists. A dev stack has
three states that all present as "the app is broken" and all have a mechanical fix:
containers down, schema behind head, `reserved_slugs` empty. Each has cost this project
real time; none is worth remembering a command for. So before starting anything this
brings the compose stack up, WAITS for the ports to actually answer (`up -d` returns
several seconds before Postgres accepts a connection), migrates to head and seeds.

It is additive only. It never drops, never resets, never deletes — `make db-reset` is the
destructive one and is meant to be. Both healing steps are idempotent by the contract of
the thing they call, so running this on a healthy stack changes nothing and costs a second.

WHAT "ALMOST" MEANS, because a silent supervisor is a trap. Suppressing routine logs is
the point; suppressing a service that died is how a developer spends twenty minutes
wondering why the console will not load. So four things always reach the terminal: the
banner naming what is running and where, a line when a service exits, everything a dying
service said on its way out, and the codes. `--verbose` passes every line through
unchanged, for when the thing you are debugging IS the log.

THIS IS NOT AN MFA BYPASS AND MUST NEVER BECOME ONE. It reads a log line that already
exists on this machine, in a transport that only `APP_ENV=local` selects. Nothing here
touches `apps/api/authn/`: the challenge is still issued, hashed, rate-limited, attempt-
counted and expired in ten minutes, and the developer still types the code they were sent.
`ConsoleTransport`'s docstring argues the same point at length and is the primary control;
this script is a reader, and if it ever needs to become a writer the answer is no.

WHY PYTHON AND NOT A SHELL SCRIPT. The team develops on Windows, where the `&`-chained
POSIX pipeline in `make dev` does not run at all, and `pnpm` is `pnpm.cmd`. This works on
both, terminates its children on both, and is the same language as the rest of `scripts/`.
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import IO

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The event `ConsoleTransport.send` logs, and the extra it carries the body in. Both are
#: spelled in `apps/workers/transport.py` and nowhere else; if either moves, this script
#: goes quiet rather than wrong, which is why `--verbose` exists and why the banner says
#: what to fall back to.
_EMAIL_EVENT = "email_console"
_BODY_KEY = "dev_message"

#: `Your Calevate code to <what> is:\n\n    123456\n` — `auth_email._body`. Anchored on the
#: sentence rather than on "six digits anywhere", so a request id that happens to be six
#: digits long cannot be printed as a code an operator would then type.
_CODE_RE = re.compile(r"code to .*? is:\s*(\d{4,10})", re.S)

#: The other secret these emails carry: a single-use link (password reset, invitation).
#: Same dev-flow problem — it exists only in the body — so it is surfaced the same way.
_LINK_RE = re.compile(r"(https?://\S+\?token=\S+)")


@dataclass(frozen=True)
class Service:
    name: str
    command: list[str]
    #: Printed in the banner. None for the worker, which listens on nothing.
    url: str | None


def _pnpm() -> str:
    """`pnpm` as this OS spells it.

    `shutil.which` resolves `pnpm.cmd` on Windows, where bare `pnpm` is not an executable
    `CreateProcess` can start. Falling back to the bare name keeps the failure a legible
    "not found" from the OS rather than a `None` crashing this script.
    """
    return shutil.which("pnpm") or "pnpm"


def services() -> list[Service]:
    """The four `make dev` starts, with its reasoning preserved.

    `--app-dir` on voice-runtime because D-18 gave that directory a hyphen, so it is not
    importable as a module path. Kept in step with the Makefile by
    `tests/dev_supervisor_test.py`, which compares the two rather than trusting a comment.
    """
    return [
        Service(
            "api",
            ["uv", "run", "uvicorn", "apps.api.main:app", "--reload", "--port", "8000"],
            "http://localhost:8000",
        ),
        Service(
            "voice-runtime",
            [
                "uv",
                "run",
                "uvicorn",
                "main:app",
                "--reload",
                "--port",
                "8100",
                "--app-dir",
                "apps/voice-runtime",
            ],
            "http://localhost:8100",
        ),
        Service("worker", ["uv", "run", "arq", "apps.workers.settings.WorkerSettings"], None),
        Service("web", [_pnpm(), "-C", "apps/web", "dev"], "http://localhost:3000"),
    ]


# ── the terminal ──────────────────────────────────────────────────────────────────────

# `isatty` ALONE. The `NO_COLOR` convention belongs here on merit, but reading it would
# be a direct `os.environ` read, which `check_env_parity` fails by design: config in
# this repo goes through `Settings` so it fails fast, and a colour preference in a
# local-only dev script does not earn a platform setting. Piping to a file or a pager
# already turns the escapes off, which is the case that actually matters.
_COLOUR = sys.stdout.isatty()


def _paint(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOUR else text


def _stamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


_print_lock = threading.Lock()


def _emit(line: str) -> None:
    """One writer at a time. Four reader threads sharing a stream interleave mid-line
    otherwise, and a six-digit code split across two lines is worse than no code."""
    with _print_lock:
        print(line, flush=True)


def _show_secret(record: dict[str, object]) -> bool:
    """Print the code or link this record carries. False if it carries neither.

    NO RECIPIENT, and not by choice: the transport logs `recipient_domain` rather than the
    mailbox, and even the domain arrives here as `[redacted]` — `redact_mapping` matches
    the `recipient` prefix in `REDACT_KEYS` on the way through `JsonFormatter`. Printing it
    would put a literal "@[redacted]" beside every code, which is exactly the noise this
    script exists to remove. The SUBJECT is not redacted and carries what a developer
    actually needs to tell one code from another — sign-in, authorization, or email
    verification. Found by running the thing, not by reading it.
    """
    body = str(record.get(_BODY_KEY, ""))
    subject = str(record.get("subject", "an email"))

    code = _CODE_RE.search(body)
    if code:
        _emit(
            f"{_paint(_stamp(), '2;37')}  "
            f"{_paint(' ' + code.group(1) + ' ', '30;103;1')}  "
            f"{_paint(subject, '1')}"
        )
        return True

    link = _LINK_RE.search(body)
    if link:
        _emit(
            f"{_paint(_stamp(), '2;37')}  {_paint(' LINK ', '30;106;1')}  "
            f"{_paint(subject, '1')}\n          {link.group(1)}"
        )
        return True
    return False


def _pump(service: Service, stream: IO[str], verbose: bool, tail: list[str]) -> None:
    """Read one service's output forever, printing only what earns the terminal.

    `tail` keeps the last few lines so that a service which dies can say why. Without it
    the quiet mode turns a crash into a bare exit code, which is the trap this script has
    to avoid being.
    """
    for raw in stream:
        line = raw.rstrip("\n")
        tail.append(line)
        del tail[:-30]

        if verbose:
            _emit(f"{_paint(service.name.rjust(13), '2;37')} │ {line}")
            continue

        # Not JSON: uvicorn's reloader banner, Next's build output, a traceback. All
        # routine, all suppressed -- and all still in `tail` if this service then dies.
        if not line.startswith("{"):
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and record.get("msg") == _EMAIL_EVENT:
            _show_secret(record)


def _reachable(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.4)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def _preflight() -> list[str]:
    """The two stores this stack cannot run without, named rather than discovered.

    Every service starts fine with Postgres down and then fails on its first request, so
    the symptom arrives minutes later looking like an application bug. Asking here costs
    two connect attempts. Ports come from `.env` in this deployment (5433/6380) and are
    read from it rather than hardcoded, so a machine that moved them still gets a true
    answer.
    """
    env = REPO_ROOT / ".env"
    text = env.read_text(encoding="utf-8") if env.exists() else ""
    missing = []
    for label, pattern, fallback in (
        ("Postgres", r"(?:DATABASE_URL|ALEMBIC_DATABASE_URL)\s*=\s*\S*?:(\d+)/", 5432),
        ("Redis", r"REDIS_URL\s*=\s*\S*?:(\d+)", 6379),
    ):
        found = re.search(pattern, text)
        port = int(found.group(1)) if found else fallback
        if not _reachable(port):
            missing.append(f"{label} on :{port}")
    return missing


# ── healing ───────────────────────────────────────────────────────────────────────────
#
# What this command is FOR, beyond starting four processes: a dev stack has three states
# that all look like "the app is broken" and all have a mechanical fix. Containers down,
# schema behind, `reserved_slugs` empty. Each has cost this project real time, and none of
# them is a thing worth remembering the command for.
#
# WHAT IT WILL NOT DO. It never drops, never resets, never deletes. `make db-reset` exists
# for that and is destructive on purpose; a "master command" that quietly took a database
# with it would be the worst tool in the repo. Everything below is additive and
# documented-idempotent by the thing it calls: `alembic upgrade head` is a no-op at head,
# and `scripts/seed.py`'s own docstring says "safe to re-run … ON CONFLICT DO NOTHING and
# the script never updates or deletes existing rows".

#: A fresh `pgvector/pgvector:pg16` initialises its data directory before it accepts a
#: connection. Measured at roughly 6-10s cold on this hardware; 90 leaves room for a slow
#: disk and an image pull without ever being reached on a warm start.
_STORE_WAIT_S = 90


def _run_quiet(command: list[str], label: str) -> bool:
    """Run a healing step, showing its output ONLY if it failed.

    The same bargain the log filter makes: a step that worked is one line, a step that did
    not is everything it said. A silent failure here would send a developer to debug the
    application for a problem in its scaffolding.
    """
    print(f"    {label}…", end="", flush=True)
    done = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    if done.returncode == 0:
        print(_paint(" ok", "32"))
        return True
    print(_paint(" failed", "1;31"))
    for line in (done.stdout + done.stderr).strip().splitlines()[-12:]:
        print(f"      {line}")
    return False


def _start_stores(down: list[str]) -> list[str]:
    """`docker compose up -d`, then wait for the ports to answer. Returns what is still down.

    THE WAIT IS THE POINT, not the `up`. `docker compose up -d` returns as soon as the
    containers are CREATED, which is several seconds before Postgres accepts a connection —
    so a version of this that started the containers and went straight on would hand the
    four services a database that is not listening yet, which is the exact failure the
    preflight exists to prevent, arriving by a new route.
    """
    if shutil.which("docker") is None:
        return down
    print(_paint(f"  {' and '.join(down)} down — starting the containers", "2;37"))
    if not _run_quiet(["docker", "compose", "up", "-d"], "docker compose up -d"):
        return down

    print("    waiting for the ports…", end="", flush=True)
    deadline = time.monotonic() + _STORE_WAIT_S
    while time.monotonic() < deadline:
        remaining = _preflight()
        if not remaining:
            print(_paint(" ok", "32"))
            return []
        time.sleep(0.5)
    print(_paint(" timed out", "1;31"))
    return _preflight()


def _heal_schema() -> bool:
    """Bring the database to head and make sure the global rows exist.

    Both unconditionally, because both are cheap and idempotent and the alternative is a
    rule about when to run them that somebody has to remember. `reserved_slugs` is the one
    that bites: `alembic upgrade head` alone leaves it empty, and four tests plus the
    signup path then refuse a slug they have nothing to refuse against (CLAUDE.md says so
    about `make db-reset` for the same reason).
    """
    return _run_quiet(
        ["uv", "run", "alembic", "upgrade", "head"], "alembic upgrade head"
    ) and _run_quiet(["uv", "run", "python", "-m", "scripts.seed"], "seed")


def main() -> int:
    verbose = "--verbose" in sys.argv or "-v" in sys.argv

    # LINE-BUFFERED, because a pipe is not a terminal and Python knows it. Piping this to
    # `tee` or a pager switched stdout to block buffering, so the banner and every code sat
    # in a 8KB buffer until the process exited — and this process is meant to run for
    # hours. The healing lines above pass `flush=True` individually and so looked fine,
    # which is exactly how the rest of the output got missed. Setting it once here is the
    # one place that cannot be forgotten by the next `print`.
    if isinstance(sys.stdout, io.TextIOWrapper):  # not when captured by a test
        sys.stdout.reconfigure(line_buffering=True)

    down = _preflight()
    if down:
        down = _start_stores(down)
    if down:
        # Still down after trying. NOT a generic "`make up`" hint: DEV-SETUP is explicit
        # that a locally installed Postgres is equally supported, so the useful thing to
        # say is which port is silent and that Docker was either absent or did not fix it.
        print(f"Not started — {' and '.join(down)} unreachable.")
        if shutil.which("docker") is None:
            print("  No `docker` on PATH, so the containers could not be started for you.")
        print("  Start them however this machine runs them, then retry.")
        return 2

    if not _heal_schema():
        # A migration that failed is not something to start four services on top of: the
        # app would boot and then answer 500 from a schema that is half a release behind,
        # which reads as an application defect rather than as this.
        print(_paint("  Schema not healed — fix the above before starting.", "1;31"))
        return 2

    procs: list[tuple[Service, subprocess.Popen[str], list[str]]] = []
    print(_paint("  Calevate dev — codes only. Ctrl-C to stop, --verbose for everything.", "1"))
    for service in services():
        # `CREATE_NEW_PROCESS_GROUP` on Windows so Ctrl-C reaches THIS process first and
        # the shutdown below is what stops the children, rather than the console killing
        # them underneath us and leaving orphaned uvicorn reloaders holding the ports.
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        proc = subprocess.Popen(
            service.command,
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=flags,
        )
        tail: list[str] = []
        assert proc.stdout is not None
        threading.Thread(
            target=_pump, args=(service, proc.stdout, verbose, tail), daemon=True
        ).start()
        procs.append((service, proc, tail))
        if service.url:
            print(f"    {service.name.ljust(14)} {_paint(service.url, '4')}")
        else:
            print(f"    {service.name.ljust(14)} {_paint('(no port)', '2;37')}")
    print(_paint("  " + "─" * 68, "2;37"))

    try:
        while True:
            for service, proc, tail in procs:
                if proc.poll() is None:
                    continue
                # A service died. Say so, and say what it said -- the whole reason `tail`
                # is kept. Then stop: three services running without the fourth is a
                # stack that fails in ways nobody should spend time on.
                _emit(
                    _paint(f"\n  {service.name} exited ({proc.returncode}). Last output:", "1;31")
                )
                for line in tail[-15:]:
                    _emit(f"    {line}")
                raise KeyboardInterrupt
            time.sleep(0.4)
    except KeyboardInterrupt:
        print(_paint("\n  stopping…", "2;37"))
    finally:
        for _, proc, _ in procs:
            if proc.poll() is not None:
                continue
            # `CTRL_BREAK` is the only signal a new process group answers on Windows;
            # `terminate()` there is a hard kill that leaves Next's child node process
            # behind, still holding :3000 for the next run.
            if os.name == "nt":
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                proc.terminate()
        for _, proc, _ in procs:
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
