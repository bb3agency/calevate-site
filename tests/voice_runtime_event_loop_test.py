"""The two deployment facts the 500ms ack budget actually rests on: uvloop, and N workers.

DEPLOYMENT §2a quotes a measured rate — "**≈250 acks/s per process**" — and derives the
whole worker table from it by Little's Law. That number was measured on a host running
"uvicorn + uvloop, one worker", which the document says in the same sentence. So the
budget does not depend on uvloop as an optimisation; it depends on it as a PREMISE, and
the premise is currently satisfied by accident:

* nothing in the repo names uvloop. It arrives because `apps/voice-runtime` declares
  `uvicorn[standard]`, whose `standard` extra pulls it in on non-Windows CPython;
* nothing selects it either. uvicorn's `--loop` defaults to `auto`, which picks uvloop
  when it is importable and falls back to asyncio, silently, when it is not.

Both of those are fine, and neither is checked anywhere. Drop `[standard]` — a plausible
edit, since the extra also pulls `httptools`, `watchfiles` and `websockets` and this
service wants none of them — and the process still boots, still passes every test, and
answers slower than the table says it will. The failure surfaces as dropped calls under
load, because Bolna's delivery is at-most-once with no retry (D-31), and the last place
anybody would look is a dependency extra.

This file is the check. It asserts the premise rather than the speed: a wall-clock
assertion on a CI box is flaky, and flaky latency assertions get deleted — the same
argument `voice_runtime_import_surface_test` makes for measuring imports instead of
milliseconds.
"""

from __future__ import annotations

import importlib.util
import re
import tomllib
from pathlib import Path

from tests.platform_support import requires_uvloop_platform

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE = REPO_ROOT / "compose.prod.yml"
VOICE_RUNTIME_PYPROJECT = REPO_ROOT / "apps" / "voice-runtime" / "pyproject.toml"
DEPLOYMENT_DOC = REPO_ROOT / "docs" / "DEPLOYMENT.md"


def _voice_runtime_command() -> list[str]:
    """The `command:` list compose runs, without a YAML parser.

    A regex over the one block rather than a dependency on PyYAML: this file asserts a
    handful of flags, and adding a parser to the test suite to read four lines would be
    a heavier answer than the question deserves.
    """
    text = COMPOSE.read_text(encoding="utf-8")
    block = re.search(r"\n  voice-runtime:\n(.*?)(?=\n  [a-z][a-z0-9-]*:\n)", text, re.S)
    assert block, "compose.prod.yml no longer has a `voice-runtime:` service block"
    # COMMENT LINES ARE PART OF THE RUN. The command list is interleaved with the prose
    # explaining each flag — which is the house style and the reason `--workers` carries
    # its derivation — so a pattern matching only `- ` items stops at the first comment
    # and silently returns a truncated list. That is a guard that reads the wrong half of
    # what it is guarding, so the match accepts both and the items are filtered after.
    command = re.search(r"\n    command:\n((?:[ \t]+(?:- .*|#.*)\n)+)", block.group(1))
    assert command, "the voice-runtime service no longer declares a `command:`"
    return [
        line.strip()[2:].strip()
        for line in command.group(1).splitlines()
        if line.strip().startswith("- ")
    ]


@requires_uvloop_platform
def test_uvloop_is_actually_installed() -> None:
    """The premise under DEPLOYMENT §2a's 250 acks/s.

    `find_spec` rather than a plain import: this asserts the module is INSTALLABLE in this
    environment, which is the property, and does not care whether some earlier test
    already imported it.
    """
    assert importlib.util.find_spec("uvloop") is not None, (
        "uvloop is not installed, so uvicorn's `--loop auto` will fall back to asyncio "
        "and DEPLOYMENT §2a's measured ~250 acks/s per process no longer holds — every "
        "number in the worker table is derived from it"
    )


def test_the_extra_that_ships_uvloop_is_still_declared() -> None:
    """`uvicorn[standard]`, in voice-runtime's OWN manifest.

    Named explicitly because the extra is the only reason uvloop is present, and the
    dependency list carries a comment asking for it to be kept "deliberately small" —
    which is a standing invitation to trim exactly this.
    """
    manifest = tomllib.loads(VOICE_RUNTIME_PYPROJECT.read_text(encoding="utf-8"))
    deps = manifest["project"]["dependencies"]
    assert any(dep.startswith("uvicorn[standard]") for dep in deps), (
        f"apps/voice-runtime no longer declares `uvicorn[standard]` (has: {deps}). The "
        "`standard` extra is what installs uvloop; without it the service still boots and "
        "silently answers at asyncio speed"
    )


def test_nothing_overrides_the_loop_back_to_asyncio() -> None:
    """`--loop auto` is the default and the right one; an explicit downgrade is not.

    Checked because `--loop asyncio` is a one-word edit that looks like a debugging aid
    and would quietly halve the throughput the worker count was sized against.
    """
    command = _voice_runtime_command()
    downgraded = [flag for flag in command if flag.startswith("--loop") and "uvloop" not in flag]
    assert not downgraded, (
        f"the voice-runtime command pins the event loop to {downgraded} — DEPLOYMENT §2a's "
        "rate was measured on uvloop, so this silently invalidates the worker table"
    )


def test_the_shipped_worker_count_is_the_one_the_measurement_prescribes() -> None:
    """The config and the document that justifies it, compared.

    D-55 derives `processes = peak in-flight ÷ (0.25 x acks-per-second)` and tabulates 4
    for production. The compose default is where that becomes real, and the two drifting
    apart is the defect class `check_docs_drift` exists for — a documented capacity plan
    nothing implements reads exactly like one that is implemented.
    """
    command = _voice_runtime_command()
    workers = [flag for flag in command if flag.startswith("--workers")]
    assert len(workers) == 1, f"expected exactly one --workers flag, found {workers}"
    assert "VOICE_RUNTIME_WORKERS" in workers[0], (
        f"{workers[0]} hard-codes the worker count; it must stay overridable per "
        "environment — DEPLOYMENT §2a prescribes 2 for staging and 4 for production"
    )
    assert ":-4}" in workers[0], (
        f"{workers[0]} no longer defaults to 4 processes, which is what DEPLOYMENT §2a "
        "derives for production from D-55's measured rate"
    )


def test_the_document_still_says_what_this_file_is_checking() -> None:
    """A guard whose premise has silently moved is worse than no guard.

    If someone re-measures on a different host and rewrites §2a, these assertions should
    be revisited in the same change rather than left pinning a number the document no
    longer claims.
    """
    doc = DEPLOYMENT_DOC.read_text(encoding="utf-8")
    assert "uvloop" in doc, (
        "DEPLOYMENT.md no longer mentions uvloop, but this file pins it as a premise of "
        "the ack budget — re-read §2a and update both together"
    )
    assert "--workers" in doc, "DEPLOYMENT.md no longer prescribes a worker count"
