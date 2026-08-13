"""The Bolna pilot harness (OPERATIONS §2, ROADMAP gate G0).

    uv run python -m scripts.pilot preflight     # what is missing, before day one
    uv run python -m scripts.pilot run --gates 1,2,6

Thirteen gates decide whether D-31's engine choice survives. Some of them are
conversations with human beings and always will be (the commercials, the support
threads); some are measurements a machine should make identically every time. This
package holds the second kind, and reports the first kind as such rather than leaving a
blank row that a reader will fill in with optimism.

Layout, and who owns what:

    config.py     preflight — the shopping list of credentials and prerequisites
    safety.py     dry-run default, call cap, cost estimate, production refusal
    results.py    the PASS / FAIL / NOT RUN vocabulary — the seam between gate modules
    redact.py     hard rule 6 at the exit; the artefact is committed to git forever
    gates_api.py  gates 1 (webhook trust), 2 (API provisioning), 6 (webhook loss)
    runner.py     the CLI, the gate registry, the exit codes

Other slices contribute gates by exposing a `GATES: dict[int, runner]` mapping from
their own module and returning `GateRun` objects from here; `runner.gate_registry`
picks them up optionally, so a module mid-edit degrades to NOT RUN instead of taking
the harness down on the one day it is needed.
"""

from __future__ import annotations

from scripts.pilot.results import (
    STATUS_LABEL,
    GateRun,
    GateStatus,
    NotRunWithoutReasonError,
    SubCheck,
    failed,
    not_run,
    passed,
    rolled_up,
)

__all__ = [
    "STATUS_LABEL",
    "GateRun",
    "GateStatus",
    "NotRunWithoutReasonError",
    "SubCheck",
    "failed",
    "not_run",
    "passed",
    "rolled_up",
]
