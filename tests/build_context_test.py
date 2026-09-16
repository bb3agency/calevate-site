"""Guardrail: what a Pipecat Cloud build actually uploads, computed rather than assumed.

**WHY THIS EXISTS.** On 16 Sep 2026 the cloud-build context for this repository was
measured for the first time — with the vendor's own exclusion code, not by eye — and it
came to **78,540 files / 2.3GB**. `.dockerignore` had never heard of `.claude/worktrees/`
(a full checkout per agent) or `mergewt/`, both of which `.gitignore` knows perfectly well.

That is not a slow build, it is a failed one, and the reason is specific to this build
path: `docker build` STREAMS its context to a local daemon and mostly survives a fat one,
while `pipecatcloud` builds the whole tarball **in memory** before uploading it
(`pipecatcloud/_utils/build_utils.py::create_deterministic_tarball`, version 1.2.0, read
16 Sep 2026). The same oversight is a shrug locally and an OOM on the path we now deploy
through.

**WHAT THIS ASSERTS, AND WHY IT IS THE CLASS AND NOT THE INSTANCE.** Adding two names to
`.dockerignore` fixes the two we found. The defect is that `.gitignore` and `.dockerignore`
had silently drifted: anything git-ignored in a working directory is by definition not
source, and it still ships unless `.dockerignore` names it. So the third clause below asks
git what it ignores and requires the intersection with the build context to be empty.

The rules themselves live in `scripts/pipecat_build_context.py`, which restates the
vendor's matcher (it is NOT Docker's — component-wise `fnmatch`, and `!` negation does
nothing) and carries the citation. This file asserts properties; that one computes.

One consequence is worth knowing here: under their matcher a root-level `*.md` also matches
`runbooks/alarm-index.md`, which Docker's own `filepath.Match` would not. This tree gets
away with it today only because the voice-worker Dockerfile COPYs no `.md` at all — clause 1
is what notices the day that stops being true.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
from scripts.pipecat_build_context import compute_context

_ROOT = Path(__file__).resolve().parents[1]
_DOCKERFILE = _ROOT / "apps" / "voice-worker" / "Dockerfile"

#: Ceilings, not measurements. The context measured 1,268 files / 29.2MB on 16 Sep 2026;
#: these sit far enough above that ordinary growth never trips them, and low enough that a
#: whole second checkout appearing in the tree does. A failure here is a question ("what
#: got in?"), not a number to raise.
MAX_FILES = 6_000
MAX_BYTES = 150 * 1024 * 1024


@pytest.fixture(scope="module")
def context() -> tuple[set[str], int]:
    """The file set a cloud build would upload. Computed by the module the operator's
    `pipecat-worker-setup.sh context` also runs, so what CI asserts and what a human reads
    on the deploy host cannot diverge."""
    return compute_context(_ROOT)


def test_every_file_the_dockerfile_copies_is_in_the_context(context: tuple[set[str], int]) -> None:
    """**A COPY OF AN EXCLUDED PATH DOES NOT SHIP AN EMPTY DIRECTORY, IT FAILS THE BUILD**
    with `/x: not found` — and this repository has already paid for that once, when
    `.dockerignore` excluded the `runbooks` tree the API Dockerfile copies (the reason its
    entry carries a paragraph). Reading the COPY lines rather than listing paths here means
    a new COPY is covered the day it is written."""
    kept, _ = context
    sources: list[str] = []
    for line in _DOCKERFILE.read_text().splitlines():
        if not line.startswith("COPY "):
            continue
        parts = re.split(r"\s+", line.strip())[1:]
        sources.extend(p for p in parts[:-1] if not p.startswith("--"))

    assert sources, "no COPY sources parsed out of the Dockerfile; this guard asserts nothing"
    for src in sources:
        path = _ROOT / src
        if path.is_dir():
            present = any(k == src or k.startswith(f"{src}/") for k in kept)
            assert present, f"COPY {src}: the whole directory is excluded from the context"
        else:
            assert src in kept, f"COPY {src}: excluded from the build context"


def test_nothing_git_ignores_reaches_the_build_context(context: tuple[set[str], int]) -> None:
    """The drift clause. `.gitignore` already knows what is not source; this makes
    `.dockerignore` agree with it.

    ⚠ **VACUOUS ON A FRESH CLONE, AND THAT IS FINE.** CI clones the repo, so no ignored
    file exists to catch — the run where this bites is a developer's or the deploy host's,
    which is exactly where a 2.3GB context was born. A guard that is quiet in CI and loud
    on the machine that has the problem is doing its job.
    """
    kept, _ = context
    listed = subprocess.run(
        ["git", "ls-files", "--others", "--ignored", "--exclude-standard"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if listed.returncode != 0:  # not a git checkout (a release tarball, say)
        pytest.skip("not a git working tree")

    ignored = {line for line in listed.stdout.splitlines() if line}
    leaked = sorted(ignored & kept)[:20]
    assert not leaked, (
        "git ignores these, and .dockerignore does not — they would be uploaded to the "
        f"vendor's builder: {leaked}"
    )


def test_the_context_stays_small_enough_to_hold_in_memory(context: tuple[set[str], int]) -> None:
    """The vendor tars and gzips the whole context into a `bytes` before uploading, so the
    peak is the tree plus its compressed copy, on whatever machine runs the deploy."""
    kept, total = context
    assert len(kept) <= MAX_FILES, (
        f"{len(kept)} files in the build context (ceiling {MAX_FILES}). Something large "
        "joined the tree; exclude it rather than raising this."
    )
    assert total <= MAX_BYTES, (
        f"{total / 1e6:.0f}MB in the build context (ceiling {MAX_BYTES / 1e6:.0f}MB). "
        "Exclude it rather than raising this."
    )
