"""Guardrail: the production image's two stages must agree about WHERE the app lives.

WHY THIS EXISTS, AND WHY IT IS NOT OBVIOUS FROM READING THE DOCKERFILE
---------------------------------------------------------------------
`calevate-shared` is installed into the image's virtualenv as an EDITABLE install, so
site-packages holds no package — it holds `_editable_impl_calevate_shared.pth`, whose
entire content is one ABSOLUTE path to the source tree:

    $ cat .venv/lib/python3.12/site-packages/_editable_impl_calevate_shared.pth
    /app/packages/shared/src

That path is baked at BUILD time, in the builder stage, from that stage's `WORKDIR`. The
runtime stage then copies the tree with `COPY --from=builder /app /app`. It works today
for one reason and one reason only: **both stages say `/app`, so the recorded path still
resolves after the copy.**

Move either of them and nothing complains at build time. `uv sync` succeeds, the image
builds, the layers are all present, `pip list` shows `calevate-shared 0.1.0` — and every
process dies at `import calevate_shared`, which is the first import of all four
entrypoints (api, voice-runtime, workers, and the `compose run` scripts). The failure
surfaces on the VPS, after the build, at `vps-deploy.sh` step 7.

THAT IS D-188'S SHAPE EXACTLY. A bare `uv sync` installed nothing and exited 0, and it
was invisible "because a successful `uv sync` that installs nothing looks exactly like a
cache hit". This is the same class one layer along: a successful build whose venv cannot
import, because the only thing binding the install to the tree is a string in a `.pth`
that no stage re-checks. Both are caught by asking a question of the artefact rather than
trusting that the build exiting 0 means anything.

Changing the runtime `WORKDIR` to `/srv/app`, or copying to a subdirectory, are both
ordinary-looking refactors. Neither is wrong in itself; either one silently breaks the
image. So the constraint gets stated where it can fail a build instead of a deploy.

WHY STATIC PARSING RATHER THAN BUILDING THE IMAGE. CI already builds nothing (the image
is built on the VPS by `scripts/vps-deploy.sh`), and this check has to run in the ~seconds
budget the other guardrails run in. The coupling is fully determined by three lines of
text, so three lines of text are what it reads. It REFUSES rather than passes when it
cannot find them — a check that cannot see its subject must not print OK (the doctrine
`check_wiring` established and `check_metadata_columns` follows).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = REPO_ROOT / "Dockerfile"

#: The stage that runs `uv sync`, and so the stage whose WORKDIR is baked into the `.pth`.
BUILDER_STAGE = "builder"
#: The stage the containers actually run.
RUNTIME_STAGE = "runtime"

_FROM = re.compile(r"^FROM\s+\S+\s+AS\s+(?P<stage>\w+)\s*$", re.IGNORECASE)
_WORKDIR = re.compile(r"^WORKDIR\s+(?P<path>\S+)\s*$", re.IGNORECASE)
_COPY_FROM_BUILDER = re.compile(
    r"^COPY\s+--from=" + BUILDER_STAGE + r"\b(?P<flags>[^\s]*(?:\s+--\S+)*)\s+"
    r"(?P<src>\S+)\s+(?P<dst>\S+)\s*$",
    re.IGNORECASE,
)


def _stages(lines: list[str]) -> dict[str, list[str]]:
    """Dockerfile lines grouped by the named stage they belong to."""
    stages: dict[str, list[str]] = {}
    current: str | None = None
    for raw in lines:
        line = raw.strip()
        match = _FROM.match(line)
        if match:
            current = match.group("stage")
            stages.setdefault(current, [])
            continue
        if current is not None:
            stages[current].append(line)
    return stages


def _last_workdir(lines: list[str]) -> str | None:
    """The WORKDIR in effect at the END of a stage — the one `uv sync` and the copy see."""
    found: str | None = None
    for line in lines:
        match = _WORKDIR.match(line)
        if match:
            found = match.group("path")
    return found


def check() -> list[str]:
    failures: list[str] = []
    if not DOCKERFILE.is_file():
        return [f"REFUSED: {DOCKERFILE} does not exist — nothing to check, so nothing is proved."]

    lines = DOCKERFILE.read_text(encoding="utf-8").splitlines()
    stages = _stages(lines)

    for name in (BUILDER_STAGE, RUNTIME_STAGE):
        if name not in stages:
            failures.append(
                f"REFUSED: no `FROM ... AS {name}` stage in the Dockerfile. This check is "
                "about the agreement between two named stages; renaming one silences it, "
                "so it fails rather than passing over a file it no longer understands."
            )
    if failures:
        return failures

    builder_workdir = _last_workdir(stages[BUILDER_STAGE])
    runtime_workdir = _last_workdir(stages[RUNTIME_STAGE])
    if builder_workdir is None:
        failures.append(
            f"REFUSED: the `{BUILDER_STAGE}` stage declares no WORKDIR, so the path baked "
            "into the editable install cannot be determined from the file."
        )
    if runtime_workdir is None:
        failures.append(f"REFUSED: the `{RUNTIME_STAGE}` stage declares no WORKDIR.")
    if failures:
        return failures

    copies = [
        match
        for match in (_COPY_FROM_BUILDER.match(line) for line in stages[RUNTIME_STAGE])
        if match is not None
    ]
    if not copies:
        return [
            f"REFUSED: the `{RUNTIME_STAGE}` stage copies nothing from `{BUILDER_STAGE}`. "
            "Either the image no longer carries the built tree (in which case it cannot "
            "run) or this check is reading the wrong file."
        ]

    # The copy that brings the virtualenv across is the one whose SOURCE is the builder's
    # WORKDIR. A stage may legitimately copy other things from the builder.
    tree_copies = [match for match in copies if match.group("src").rstrip("/") == builder_workdir]
    if not tree_copies:
        sources = sorted({match.group("src") for match in copies})
        return [
            f"the `{RUNTIME_STAGE}` stage never copies `{builder_workdir}` (the builder's "
            f"WORKDIR, and therefore the tree the editable install points at). It copies "
            f"{sources}. The virtualenv's `_editable_impl_calevate_shared.pth` records an "
            f"ABSOLUTE path under `{builder_workdir}`; if that tree is not in the runtime "
            "image at that exact path, `import calevate_shared` fails at process start "
            "and the image is unrunnable."
        ]

    for match in tree_copies:
        destination = match.group("dst").rstrip("/")
        if destination != builder_workdir:
            failures.append(
                f"the builder builds in `{builder_workdir}` but the runtime stage copies "
                f"that tree to `{destination}`. The editable install baked "
                f"`{builder_workdir}/packages/shared/src` into a `.pth` at build time, so "
                "after this copy nothing resolves it: the build still succeeds, the venv "
                "still lists `calevate-shared`, and every entrypoint dies at "
                "`import calevate_shared` on the VPS."
            )
    if runtime_workdir != builder_workdir:
        failures.append(
            f"the builder's WORKDIR is `{builder_workdir}` and the runtime's is "
            f"`{runtime_workdir}`. PYTHONPATH is set to the runtime WORKDIR so that the "
            "`package = false` workspace members (apps/*) import from source; pointing it "
            "at a directory the tree was not built in breaks those imports the same "
            "silent way."
        )
    return failures


def main() -> int:
    failures = check()
    if failures:
        print("IMAGE PATHS: FAIL")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    lines = DOCKERFILE.read_text(encoding="utf-8").splitlines()
    workdir = _last_workdir(_stages(lines)[BUILDER_STAGE])
    print(
        f"IMAGE PATHS: OK (builder and runtime both build and run at `{workdir}`, so the "
        "editable install's recorded path survives the stage copy)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
