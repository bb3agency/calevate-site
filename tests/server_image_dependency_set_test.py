"""The server image installs the server's dependencies and not the voice worker's (D-667).

The root `Dockerfile` syncs the workspace ROOT with `--group errors`, so what the image
holds is the closure of the root's `dependencies` plus the root `errors` group, as written
in `uv.lock`. Two ways that set can go wrong, both silent at build time:

* it SHRINKS — the root stops depending on a member the image runs. That is D-188: a root
  with no dependencies made `uv sync` install nothing and exit 0, and every service died
  on its first import.
* it GROWS — the root, or a server member, starts reaching `calevate-pipecat-worker` or
  its pipecat/onnxruntime/numpy tree, which nothing in api, voice-runtime or workers
  imports and which then ships to the hosts that hold PLATFORM_KEK.

Static, like `dockerfile_context_test.py`: it reads the lockfile and the Dockerfile and
needs neither Docker nor a resolver.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]

ROOT_PROJECT = "calevate"
SERVER_MEMBERS = frozenset({"calevate-api", "calevate-voice-runtime", "calevate-workers"})
VOICE_WORKER = "calevate-pipecat-worker"

#: Named so a failure reads as the packages the audit found, not only as a derived set.
#: Each one is also asserted to BE in the voice worker's tree, so this list cannot go
#: stale into checking for names that no longer exist anywhere.
NAMED_VOICE_WORKER_ONLY = frozenset(
    {"pipecat-ai", "pipecat-gnani", "onnxruntime", "numpy", "sympy", "sarvamai"}
)

Lock = Mapping[str, Mapping[str, Any]]


def _load_lock(text: str) -> Lock:
    return {package["name"]: package for package in tomllib.loads(text)["package"]}


def _closure(lock: Lock, roots: Iterable[str], *, groups: Iterable[str] = ()) -> set[str]:
    """Every package reachable from `roots`, following extras, plus `groups` of the roots.

    Markers are ignored, which over-approximates: a package behind a platform marker counts
    as reachable. That is the safe direction for a test that asserts what is ABSENT.
    """
    seen: set[str] = set()
    seen_extras: set[tuple[str, str]] = set()
    pending: list[dict[str, Any]] = [{"name": name} for name in roots]
    for name in roots:
        for group in groups:
            pending.extend(lock[name].get("dev-dependencies", {}).get(group, []))
    while pending:
        edge = pending.pop()
        name = edge["name"]
        package = lock[name]
        if name not in seen:
            seen.add(name)
            pending.extend(package.get("dependencies", []))
        for extra in edge.get("extra", []):
            if (name, extra) not in seen_extras:
                seen_extras.add((name, extra))
                pending.extend(package.get("optional-dependencies", {}).get(extra, []))
    return seen


def _server_image_set(lock: Lock) -> set[str]:
    return _closure(lock, [ROOT_PROJECT], groups=["errors"])


def _voice_worker_only(lock: Lock) -> set[str]:
    return _closure(lock, [VOICE_WORKER]) - _closure(lock, sorted(SERVER_MEMBERS))


def _lock() -> Lock:
    return _load_lock((REPO / "uv.lock").read_text(encoding="utf-8"))


def test_the_image_set_reaches_every_member_the_image_runs_and_sentry() -> None:
    image = _server_image_set(_lock())
    missing = (SERVER_MEMBERS | {"calevate-shared", "sentry-sdk"}) - image
    assert missing == set(), (
        f"the root's dependency closure no longer reaches {sorted(missing)}, so the root "
        "Dockerfile's `uv sync --no-dev --group errors` would ship an image missing them "
        "(D-188's empty-venv shape). Root pyproject `dependencies` must list the three "
        "server members, and the `errors` group must stay a ROOT group."
    )


def test_the_image_set_holds_nothing_only_the_voice_worker_needs() -> None:
    lock = _lock()
    leaked = _server_image_set(lock) & (_voice_worker_only(lock) | {VOICE_WORKER})
    assert leaked == set(), (
        f"the server image would install {sorted(leaked)}, which only the voice worker "
        "needs. Something on the root's path depends on `calevate-pipecat-worker` or on "
        "its tree (D-667)."
    )


def test_the_named_audit_packages_are_really_voice_worker_only() -> None:
    lock = _lock()
    assert NAMED_VOICE_WORKER_ONLY <= _voice_worker_only(lock)
    assert NAMED_VOICE_WORKER_ONLY.isdisjoint(_server_image_set(lock))


def test_a_root_that_reaches_the_voice_worker_is_caught() -> None:
    """Negative control: the same lock with the root re-pointed at the voice worker."""
    lock = {name: dict(package) for name, package in _lock().items()}
    root = dict(lock[ROOT_PROJECT])
    root["dependencies"] = [*root.get("dependencies", []), {"name": VOICE_WORKER}]
    lock[ROOT_PROJECT] = root
    assert NAMED_VOICE_WORKER_ONLY <= _server_image_set(lock) & _voice_worker_only(lock)


def test_a_root_with_no_dependencies_is_caught() -> None:
    """Negative control for D-188: an empty root reaches no member at all."""
    lock = {name: dict(package) for name, package in _lock().items()}
    lock[ROOT_PROJECT] = {**lock[ROOT_PROJECT], "dependencies": []}
    assert _server_image_set(lock).isdisjoint(SERVER_MEMBERS)


def _uv_sync_commands(dockerfile: str) -> list[str]:
    """Each `uv sync` invocation, with backslash continuations joined."""
    joined = re.sub(r"\\\n", " ", dockerfile)
    return [
        line.strip()
        for line in joined.splitlines()
        if "uv sync" in line and not line.lstrip().startswith("#")
    ]


def test_the_root_dockerfile_syncs_the_root_target_with_the_errors_group() -> None:
    commands = _uv_sync_commands((REPO / "Dockerfile").read_text(encoding="utf-8"))
    assert len(commands) == 2, commands
    for command in commands:
        flags = command[command.index("uv sync") :].split()
        assert "--frozen" in flags and "--no-dev" in flags, command
        assert "--group" in flags and flags[flags.index("--group") + 1] == "errors", command
        assert "--all-packages" not in flags, (
            "`--all-packages` installs the voice worker's tree into the server image: "
            + command
        )
        assert "--package" not in flags, (
            "a `--package` target cannot take the ROOT `errors` group, and a repeated one "
            "needs uv >= 0.9.8 while the image pins 0.8.17: " + command
        )


def test_the_voice_worker_dockerfile_still_targets_only_its_own_member() -> None:
    commands = _uv_sync_commands(
        (REPO / "apps" / "voice-worker" / "Dockerfile").read_text(encoding="utf-8")
    )
    assert commands
    assert all(f"--package {VOICE_WORKER}" in command for command in commands), commands
