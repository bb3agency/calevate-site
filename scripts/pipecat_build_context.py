"""What a Pipecat Cloud build would upload, computed the way the vendor computes it.

ONE implementation, two callers: `tests/build_context_test.py` asserts properties of it in
CI, and `scripts/deploy/pipecat-worker-setup.sh context` prints it for an operator standing
on the deploy host. Two implementations of "what goes in the tarball" would agree on the day
they were written and drift after that, which is the failure this repository keeps guards
for — and here the drift would be invisible until a deploy OOMed.

⚠ **THESE RULES ARE THE VENDOR'S AND ARE NOT DOCKER'S.** Restated from
`pipecatcloud/_utils/build_utils.py` (version 1.2.0, installed from PyPI and read
16 Sep 2026) because `pipecatcloud` is a CLI the operator installs, not a dependency of this
repository — so it cannot simply be imported. Two differences from Docker's own
`.dockerignore` handling matter:

* **`fnmatch`, against every path COMPONENT as well as the whole relative path**
  (`_should_exclude`). Docker uses Go's `filepath.Match`, whose `*` does not cross a `/`,
  so a root-level `*.md` there matches only root-level files. Here it matches
  `runbooks/alarm-index.md` as well.
* **No negation** (`load_dockerignore`). `!README.md` becomes a literal pattern that matches
  nothing and re-includes nothing; Docker would re-include the file.

The walk PRUNES excluded directories rather than filtering their files, exactly as
`create_deterministic_tarball` does — which is why excluding `.claude` took the context from
78,540 files to 1,269 rather than merely from slow to slower.

If the vendor's matcher changes, this module is stale rather than wrong. Re-read that file
and update the citation with it.
"""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path

__all__ = ["compute_context", "is_excluded", "load_dockerignore"]


def load_dockerignore(root: Path) -> set[str]:
    """Comments and blank lines dropped, a leading `./` and a trailing `/` stripped, and
    everything else kept verbatim — `!` lines included, as literal patterns."""
    patterns: set[str] = set()
    path = root / ".dockerignore"
    if not path.is_file():
        return patterns
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        normalized = stripped.removeprefix("./").rstrip("/")
        if normalized:
            patterns.add(normalized)
    return patterns


def is_excluded(rel: Path, patterns: set[str]) -> bool:
    """Every component first, then the whole relative path."""
    text = str(rel)
    for pattern in patterns:
        if any(fnmatch.fnmatch(part, pattern) for part in rel.parts):
            return True
        if fnmatch.fnmatch(text, pattern):
            return True
    return False


def compute_context(root: Path) -> tuple[set[str], int]:
    """Return the relative paths a cloud build would upload, and their total size."""
    patterns = load_dockerignore(root)
    kept: set[str] = set()
    total = 0
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        dirnames[:] = [
            d for d in sorted(dirnames) if not is_excluded((here / d).relative_to(root), patterns)
        ]
        for name in sorted(filenames):
            rel = (here / name).relative_to(root)
            if is_excluded(rel, patterns):
                continue
            kept.add(str(rel))
            try:
                total += (here / name).stat().st_size
            except OSError:
                # A symlink pointing into a pruned tree. The vendor's `tar.add` skips it
                # the same way; counting it as zero keeps the two in step.
                continue
    return kept, total


def _main() -> int:
    from collections import Counter

    root = Path(__file__).resolve().parents[1]
    kept, total = compute_context(root)
    print(f"  files            {len(kept)}")
    print(f"  uncompressed     {total / 1e6:.1f}MB")
    print("  largest trees")
    counts = Counter(path.split("/")[0] for path in kept)
    for name, count in counts.most_common(8):
        print(f"    {name:<24} {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
