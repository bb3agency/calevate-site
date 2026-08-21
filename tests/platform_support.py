"""What the HOST must actually provide, for the handful of tests that need a real one.

WHY THIS EXISTS. A red test is a claim that something is broken. Forty-one of this
suite's tests cannot pass on a Windows developer machine for reasons that have nothing
to do with this product — arq installs a POSIX-only signal handler, the deploy scripts
are bash and bash cannot take a `D:\\` path, uvloop ships no Windows wheel, and Windows
has no graceful SIGTERM. Left as failures they are indistinguishable from defects, and
they have already cost one session hours of chasing product bugs that were not there.

SKIPPED, NOT DELETED, AND NOT WEAKENED. Every one of these tests is load-bearing on the
platform that actually runs this system. CI is Linux (`.github/workflows/ci.yml`), so
none of these predicates is ever true there and nothing below can hide a regression from
the gate that matters. The marker is about honesty in local output, not coverage.

WHY FOUR PREDICATES AND NOT ONE `sys.platform == "win32"`. A skip reason is read by
somebody deciding whether to care, so it has to name the missing CAPABILITY rather than
the operating system. `requires_posix_signals` stays correct if arq ever grows Windows
support; a blanket platform check would go on skipping forever and nobody would notice.
Two of the four are still expressed as a platform test rather than a feature probe, and
each says below why the probe would be WRONG.

Follows the one existing precedent in this suite — `object_lifecycle_test`'s skipif,
whose reason names the missing thing and what still applies without it.
"""

from __future__ import annotations

import os
import signal
import sys

import pytest

#: arq's `Worker.close()` calls `self.handle_sig(signal.SIGUSR1)` whenever the worker was
#: built with `handle_signals=False` — which is exactly how every "on a real worker" test
#: here builds it, to keep arq's handlers away from pytest. `signal.SIGUSR1` does not
#: exist outside POSIX, so the worker raises `AttributeError` on close and the test reads
#: as a retry-ladder failure. Verified at source in the installed arq 0.28.0
#: (`arq/worker.py`, `close()`), not inferred from the traceback.
#:
#: A CAPABILITY PROBE, deliberately: the day arq stops using SIGUSR1 as its
#: "closed without a real signal" sentinel, or Windows grows it, these run again with no
#: edit here.
requires_posix_signals = pytest.mark.skipif(
    not hasattr(signal, "SIGUSR1"),
    reason=(
        "arq's Worker.close() raises handle_sig(signal.SIGUSR1) when handle_signals=False, "
        "and SIGUSR1 is POSIX-only; the job's retry behaviour is unchanged and CI (Linux) "
        "still gates it"
    ),
)

#: The deploy and host-hygiene scripts are bash, and the tests hand them repo paths.
#: Git for Windows ships a bash, so `shutil.which("bash")` is TRUE here and would be the
#: wrong probe — that bash receives `D:\Agency\calevate\scripts\...`, reads the backslashes
#: as escapes and reports "No such file or directory". The capability these tests need is
#: a shell that shares the interpreter's path syntax, which is what `os.name` names.
requires_posix_shell = pytest.mark.skipif(
    os.name != "posix",
    reason=(
        "these exercise bash deploy/host scripts with repo paths; a Windows bash cannot "
        "read `D:\\...` as a path (backslash is an escape). They run on the Linux host "
        "these scripts are written for, and in CI"
    ),
)

#: uvloop publishes no Windows wheel and upstream does not support Windows, so the
#: DEPLOYMENT §-level assertion "uvicorn will not silently fall back to asyncio" cannot be
#: made here. NOT probed with `find_spec("uvloop")`: that is precisely the condition the
#: test exists to detect, so a probe would turn a real "uvloop is missing on the server"
#: regression into a silent skip on the platform where it matters.
requires_uvloop_platform = pytest.mark.skipif(
    sys.platform == "win32",
    reason=(
        "uvloop ships no Windows wheel (upstream does not support Windows); the check "
        "still runs on Linux, where a missing uvloop is a real deploy defect"
    ),
)

#: Windows defines `signal.SIGTERM` but gives it no graceful semantics — delivery is
#: `TerminateProcess`, which kills the process rather than letting a handler drain an
#: in-flight request. So `hasattr(signal, "SIGTERM")` is TRUE and useless as a probe; the
#: capability is cooperative termination, and `os.name` is the honest test for it.
requires_graceful_sigterm = pytest.mark.skipif(
    os.name != "posix",
    reason=(
        "Windows delivers SIGTERM as TerminateProcess, so a handler cannot drain an "
        "in-flight request; the drain behaviour is unchanged and CI (Linux) gates it"
    ),
)

__all__ = [
    "requires_graceful_sigterm",
    "requires_posix_shell",
    "requires_posix_signals",
    "requires_uvloop_platform",
]
