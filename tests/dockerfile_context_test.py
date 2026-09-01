"""Every `COPY` source in the Dockerfile survives `.dockerignore`.

**THE FAILURE THIS PREVENTS COST A DEPLOY.** D-499's admin copilot reads `runbooks/` at
runtime to answer "what do I do when `engine_error_spike` fires", so the Dockerfile gained
`COPY runbooks runbooks`. `.dockerignore` excluded `runbooks`. A path excluded there is
not in the build context AT ALL, so `docker build` does not ship an empty directory — it
fails outright with `"/runbooks": not found`, at the step, on the VPS, after every gate in
CI had gone green.

**NO EXISTING GATE COULD HAVE CAUGHT IT.** `check_image_paths` asks a different question
(that both stages agree the app lives at `/app`, because an editable install bakes an
absolute path into a `.pth`). Nothing built the image in CI, and nothing compared the
Dockerfile's inputs against the ignore file — the two are edited by different people for
different reasons and had no test binding them together.

Deliberately a STATIC test: it parses both files and needs no Docker daemon, so it runs in
the same suite as everything else rather than in a job that only exists on a machine with
a builder. A `docker build` in CI would also catch this and would cost minutes per run.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

#: Sources that are not repository paths and so cannot be ignored: `--from=` copies read
#: from an earlier stage or a pinned image, never from the build context.
_FROM_ANOTHER_STAGE = re.compile(r"^COPY\s+--from=")


def _copy_sources() -> list[tuple[int, str]]:
    """(line number, source path) for every context-reading COPY in the Dockerfile."""
    found: list[tuple[int, str]] = []
    for number, raw in enumerate((REPO / "Dockerfile").read_text(encoding="utf-8").split("\n"), 1):
        line = raw.strip()
        if not line.startswith("COPY ") or _FROM_ANOTHER_STAGE.match(line):
            continue
        # `COPY a b c dest` — every argument but the last is a source. Flags are dropped.
        parts = [p for p in line.split()[1:] if not p.startswith("--")]
        found.extend((number, source) for source in parts[:-1])
    return found


def _ignore_rules() -> list[tuple[str, bool]]:
    """(pattern, is_negation) in file order. Order matters: the LAST match wins."""
    rules: list[tuple[str, bool]] = []
    for raw in (REPO / ".dockerignore").read_text(encoding="utf-8").split("\n"):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        rules.append((line[1:], True) if line.startswith("!") else (line, False))
    return rules


def _is_excluded(path: str) -> bool:
    """Whether `.dockerignore` keeps `path` out of the build context.

    Docker matches with Go's `filepath.Match` semantics, in which `*` does NOT cross a
    `/` — so a root-level `*.md` rule does not reach `runbooks/incident.md`. That detail
    is why un-excluding a directory is enough and a second `!dir/**` is not needed, and
    getting it wrong in either direction would make this test lie.
    """
    excluded = False
    for pattern, negated in _ignore_rules():
        # A rule matches the path itself or any ancestor directory of it: excluding `docs`
        # excludes `docs/TRD.md` without naming it.
        segments = path.split("/")
        candidates = ["/".join(segments[: i + 1]) for i in range(len(segments))]
        if any(Path(candidate).match(pattern) for candidate in candidates):
            excluded = not negated
    return excluded


def test_every_dockerfile_copy_source_exists_in_the_repository() -> None:
    """A COPY naming a path that is not here fails the build for a different reason, and
    is worth separating from the ignore question so the message names the real cause."""
    missing = [
        f"Dockerfile:{line} COPY {source}"
        for line, source in _copy_sources()
        if not (REPO / source).exists()
    ]
    assert not missing, f"these COPY sources do not exist in the repository: {missing}"


def test_no_dockerfile_copy_source_is_excluded_from_the_build_context() -> None:
    """THE REGRESSION. `.dockerignore` and the Dockerfile must agree about every input."""
    blocked = [
        f"Dockerfile:{line} COPY {source}"
        for line, source in _copy_sources()
        if _is_excluded(source)
    ]
    assert not blocked, (
        "these COPY sources are excluded by .dockerignore, so they are not in the build "
        f"context and `docker build` fails at the step with 'not found': {blocked}. "
        "Either un-exclude the path or stop copying it — an excluded path does NOT ship "
        "as an empty directory."
    )


def test_the_exclusion_check_actually_detects_an_excluded_path() -> None:
    """Non-vacuity, and it earns its place: this whole file is a matcher I wrote, so a
    matcher that quietly answers False for everything would make both clauses above pass
    for ever. `docs` is excluded deliberately and permanently (5.5MB nothing reads at
    runtime), which makes it the stable fixture for 'the checker can see an exclusion'."""
    assert _is_excluded("docs"), "the matcher cannot see a directly named exclusion"
    assert _is_excluded("docs/TRD.md"), "the matcher does not apply an exclusion to descendants"
    assert not _is_excluded("runbooks"), (
        "runbooks is excluded again — the admin copilot's search_runbooks tool reads it at "
        "runtime and the deploy fails at COPY without it"
    )
