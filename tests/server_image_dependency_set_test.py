"""The server image installs the server's dependencies (D-667).

The root `Dockerfile` syncs the workspace ROOT with `--group errors`, so what the image
holds is the closure of the root's `dependencies` plus the root `errors` group, as written
in `uv.lock`. The way that set goes wrong silently at build time is that it SHRINKS: the
root stops depending on a member the image runs. That is D-188: a root with no
dependencies made `uv sync` install nothing and exit 0, and every service died on its
first import.

Static, like `dockerfile_context_test.py`: it reads the lockfile and the Dockerfile and
needs neither Docker nor a resolver.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Final

REPO = Path(__file__).resolve().parents[1]

ROOT_PROJECT = "calevate"
SERVER_MEMBERS = frozenset({"calevate-api", "calevate-voice-runtime", "calevate-workers"})
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


#: Third-party parsers the worker runs on a client's uploaded file, with the oldest release
#: carrying the fixes for the published advisories on crafted input. `pypdf` was declared only
#: in the root `dev` group while `apps/workers/kb_read.py` imported it, so `--no-dev` shipped
#: a worker that could not read a PDF at all.
UPLOAD_PARSER_FLOORS: Final = {"pypdf": (6, 21, 2)}


def _release(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", version)[:3])


def test_the_image_carries_every_upload_parser_at_its_security_floor() -> None:
    lock = _lock()
    image = _server_image_set(lock)
    for name, floor in UPLOAD_PARSER_FLOORS.items():
        assert name in image, (
            f"{name} parses client uploads in the worker but is not in the server image's "
            "dependency closure; declare it in apps/workers/pyproject.toml, not a dev group"
        )
        locked = _release(str(lock[name]["version"]))
        assert locked >= floor, f"{name} {locked} is below its security floor {floor}"


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
            "`--all-packages` installs every workspace member rather than the root's server set: "
            + command
        )
        assert "--package" not in flags, (
            "a `--package` target cannot take the ROOT `errors` group, and a repeated one "
            "needs uv >= 0.9.8 while the image pins 0.8.17: " + command
        )
