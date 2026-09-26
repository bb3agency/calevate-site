"""Publish-verification defects that are OPEN, recorded so they cannot be rediscovered.

Every entry is found while taking "what does `live` actually claim?" end to end, is
real, and cannot be closed from inside the slice that found it. Each names the specific
reason and the specific act that closes it.

THE REGISTER IS EMPTY, AND THE MACHINERY STAYS FOR THE NEXT ENTRY. Its last entry,
`create_agent_is_not_idempotent`, was about a publish that creates a VENDOR-SIDE agent and
fails before our write of `engine_agent_ref` commits. D-639 deleted the one adapter that
did that: Cartesia refuses `create_agent` by name (its agents are deployed programs), and
the owned runtime's agent is a row in our own database, written in the publish's own
transaction.

Two earlier entries closed with D-123 (`no_delete_agent_on_the_protocol`,
`no_scheduled_drift_reconciliation`); `test_the_two_gaps_that_closed_are_provably_closed`
keeps their probes as assertions in the opposite direction.

**THE ASSERTION IS AN EQUALITY**, the shape `tests/reliability_known_gaps_test.py` and
`tests/engine_name_drift_test.py::KNOWN_OPEN_COPIES` established. Each key has a probe
that answers "is this still true?" and the test asserts the still-open set EQUALS the
recorded set. So an entry cannot outlive its defect — closing one turns this file red and
forces the entry's deletion in the same change — and a TODO, which can, is not an option.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from apps.api.engine import cartesia, fake, pipecat
from calevate_shared.engine import VoiceEngine

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Gap key → why it is open, and WHAT CLOSES IT.
KNOWN_OPEN_PUBLISH_GAPS: dict[str, str] = {}

#: Gap key → a probe answering "is this still true?".
PROBES: dict[str, Callable[[], bool]] = {}


def test_the_two_gaps_that_closed_are_provably_closed() -> None:
    """The negative half of D-123, kept because deleting an entry is not evidence.

    `no_delete_agent_on_the_protocol` and `no_scheduled_drift_reconciliation` were entries
    in the register above, each with a probe that answered "is this still true?". Both are
    now false, so both entries had to go — the equality below is what forced that. What
    would ALSO satisfy the equality is deleting the entries and never doing the work, so
    the two probes survive here as assertions in the opposite direction.

    They are the cheap structural half. The behaviour is proved in
    `packages/shared/tests/engine_conformance/contract_test.py` (delete removes the agent
    it names, on every adapter) and `tests/engine_drift_reconciliation_test.py` (the sweep
    finds both drifts a publish-time check cannot).
    """
    adapters = (fake.FakeEngine, cartesia.CartesiaEngine, pipecat.PipecatEngine)
    assert hasattr(VoiceEngine, "delete_agent"), "an orphan is un-compensable again"
    for adapter in adapters:
        assert hasattr(adapter, "delete_agent"), f"{adapter.__name__} cannot remove an agent"

    workers = REPO_ROOT / "apps" / "workers"
    assert any(
        "engine_drift_for" in path.read_text(encoding="utf-8") for path in workers.glob("*.py")
    ), "no worker reaches the reconciliation read, so drift is found only by looking again"


def test_every_recorded_gap_has_a_probe_and_every_probe_a_record() -> None:
    """A key with no probe is a claim nobody can check; a probe with no key is a defect
    with no remedy written down. Neither is allowed to exist."""
    assert set(PROBES) == set(KNOWN_OPEN_PUBLISH_GAPS)


def test_the_open_gaps_are_exactly_the_recorded_ones() -> None:
    """The equality that makes the register honest in BOTH directions: an entry added
    without a defect fails here, and a defect fixed without deleting its entry fails
    here too."""
    still_open = {key for key, probe in PROBES.items() if probe()}
    assert still_open == set(KNOWN_OPEN_PUBLISH_GAPS), (
        "closed: "
        + str(sorted(set(KNOWN_OPEN_PUBLISH_GAPS) - still_open))
        + " / undocumented: "
        + str(sorted(still_open - set(KNOWN_OPEN_PUBLISH_GAPS)))
    )


def test_every_entry_names_what_closes_it() -> None:
    """A register entry without a remedy is a TODO with better formatting."""
    for key, why in KNOWN_OPEN_PUBLISH_GAPS.items():
        assert "CLOSED BY:" in why, f"{key} does not say what closes it"
