"""Negative controls for `scripts/check_image_paths`.

A guard is only worth its line count if it goes red on the thing it claims to catch, so
each test here writes a Dockerfile carrying exactly one of the mistakes and asserts the
refusal names it. The positive control — the REAL Dockerfile — is asserted too, because a
check that fails on everything is as useless as one that passes on everything.

The mutations are the plausible refactors, not invented ones: moving the runtime to
`/srv/app` (an FHS-tidiness change), copying the tree into a subdirectory (a "keep /app
clean" change), and renaming a stage. Each leaves a Dockerfile that BUILDS, and an image
that cannot import `calevate_shared`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts import check_image_paths


def _write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str) -> None:
    path = tmp_path / "Dockerfile"
    path.write_text(body, encoding="utf-8")
    monkeypatch.setattr(check_image_paths, "DOCKERFILE", path)


#: The shape the real file has, reduced to the three lines this check reads.
_GOOD = """\
FROM python:3.12-slim AS builder
WORKDIR /app
RUN uv sync --frozen --no-dev --all-packages

FROM python:3.12-slim AS runtime
WORKDIR /app
COPY --from=builder --chown=calevate:calevate /app /app
ENV PYTHONPATH=/app
"""


def test_the_real_dockerfile_passes() -> None:
    """The positive control. If this fails, the image is already broken."""
    assert check_image_paths.check() == []


def test_a_minimal_correct_file_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(tmp_path, monkeypatch, _GOOD)
    assert check_image_paths.check() == []


def test_a_runtime_workdir_moved_away_from_the_builders_is_caught(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`WORKDIR /srv/app` in the runtime stage: PYTHONPATH then points at a directory the
    tree was never built in, and the `apps/*` source imports break."""
    _write(tmp_path, monkeypatch, _GOOD.replace("WORKDIR /app\nCOPY", "WORKDIR /srv/app\nCOPY"))
    failures = check_image_paths.check()
    assert failures, "a runtime WORKDIR that disagrees with the builder's was accepted"
    assert any("/srv/app" in f for f in failures), failures


def test_the_tree_copied_to_a_different_destination_is_caught(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one that costs the most to debug: the venv is present and complete, lists
    `calevate-shared`, and cannot import it, because the `.pth` still names `/app`."""
    _write(tmp_path, monkeypatch, _GOOD.replace("/app /app\n", "/app /srv/app\n"))
    failures = check_image_paths.check()
    assert failures, "a copy that relocates the built tree was accepted"
    assert any("calevate_shared" in f for f in failures), failures


def test_a_runtime_that_copies_nothing_from_the_builder_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(
        tmp_path,
        monkeypatch,
        _GOOD.replace("COPY --from=builder --chown=calevate:calevate /app /app\n", ""),
    )
    failures = check_image_paths.check()
    assert any("REFUSED" in f for f in failures), failures


def test_a_renamed_stage_refuses_rather_than_passing_over_a_file_it_cannot_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The subtle one. Renaming `runtime` to `final` leaves a perfectly good Dockerfile
    and a check with nothing to compare — which must be a refusal, never an OK. This is
    the `check_wiring` doctrine: a check that cannot see its subject does not get a
    verdict."""
    _write(tmp_path, monkeypatch, _GOOD.replace("AS runtime", "AS final"))
    failures = check_image_paths.check()
    assert any("REFUSED" in f for f in failures), failures


def test_a_missing_dockerfile_is_refused_rather_than_reported_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(check_image_paths, "DOCKERFILE", tmp_path / "nope")
    failures = check_image_paths.check()
    assert any("REFUSED" in f for f in failures), failures
