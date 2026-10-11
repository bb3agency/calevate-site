"""Walk a source tree for the guard scripts, pruning build output and vendored packages.

`Path.rglob` descends into every directory before the pattern is applied, so a guard that
scans `apps/` with it lists a local `apps/web/node_modules` and any built `.next` — hundreds
of thousands of files over a bind mount, which made the guards take longer than the suites
they sit beside. `os.walk` lets the skipped directories be removed from the walk itself.
Neither directory exists where CI runs the backend guards, so pruning them changes no
result there.
"""

from __future__ import annotations

import os
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Final

#: Never source: package installs, framework build output and bytecode caches.
GENERATED_DIRS: Final[frozenset[str]] = frozenset({"node_modules", ".next", "__pycache__"})


def walk_files(
    root: Path, pattern: str = "*", *, skip: frozenset[str] = GENERATED_DIRS
) -> list[Path]:
    """Every file under `root` whose name matches `pattern`, sorted like `sorted(rglob)`.

    A directory whose NAME is in `skip` is not entered, at any depth. `root` itself is
    walked even if its own name is in `skip`; callers that care check that first.
    """
    found: list[Path] = []
    for directory, subdirs, names in os.walk(root):
        subdirs[:] = [d for d in subdirs if d not in skip]
        found.extend(Path(directory, n) for n in names if fnmatchcase(n, pattern))
    return sorted(found)


__all__ = ["GENERATED_DIRS", "walk_files"]
