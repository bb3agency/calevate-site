"""`python -m scripts.pilot` — the entry point, and nothing else.

Thin on purpose: everything testable lives in `runner.main(argv)`, which takes its
arguments rather than reading `sys.argv`, so the CLI's own behaviour (refusals, exit
codes, the dry-run default) is exercised by the test suite as a function call instead of
by spawning a process.
"""

from __future__ import annotations

import sys

from scripts.pilot.runner import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
