"""Publish-verification defects that are OPEN, recorded so they cannot be rediscovered.

Every entry below was found while taking "what does `live` actually claim?" end to end,
is real, and could not be closed from inside this slice. Each names the specific reason
and the specific act that closes it — and unlike the reliability register next door, the
one entry left is genuinely waiting on a VENDOR ACCOUNT rather than on a file. That
distinction is the whole point of naming it: an engineering task has no timeline, and an
external blocker is nobody's to code around.

THE OTHER TWO ENTRIES ARE GONE BECAUSE THE DEFECTS ARE (D-123), and the distinction above
is what predicted which. `no_delete_agent_on_the_protocol` looked vendor-blocked and was
not: Bolna publishes `DELETE /v2/agent/{agent_id}`, so what remained was a Protocol
method, three adapters, a conformance clause and a MARKED ASSUMPTION about the one thing
the docs do not answer (what a repeat delete returns) — an engineering task, done.
`no_scheduled_drift_reconciliation` was never vendor-blocked at all and closed with one
ARQ cron. What is left below is the entry where guessing would ship a fabricated
guarantee, which is the only kind of waiting this file is for.

**THE ASSERTION IS AN EQUALITY**, the shape `tests/reliability_known_gaps_test.py` and
`tests/engine_name_drift_test.py::KNOWN_OPEN_COPIES` established. Each key has a probe
that answers "is this still true?" and the test asserts the still-open set EQUALS the
recorded set. So an entry cannot outlive its defect — closing one turns this file red and
forces the entry's deletion in the same change — and a TODO, which can, is not an option.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from pathlib import Path

from apps.api.engine import bolna, cartesia, fake
from calevate_shared.engine import VoiceEngine

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Gap key → why it is open, and WHAT CLOSES IT.
KNOWN_OPEN_PUBLISH_GAPS: dict[str, str] = {
    "create_agent_is_not_idempotent": (
        "A publish that creates a vendor-side agent and then fails before our write of "
        "`engine_agent_ref` commits leaves an object we are billed for and can no longer "
        "address. `agents/service.py::_reclaim_orphan` now DELETES that object (D-123) "
        "and `_load_agent(for_update=True)` closes the concurrent-publish cause outright "
        "— but neither touches this case, and that is the point: a retry of a create "
        "whose RESPONSE was lost makes a SECOND vendor object whose id we never saw, so "
        "there is nothing for the compensator to name. The standard remedy is an "
        "idempotency key on the create, and "
        "whether either vendor honours one is unknown: every vendor host is refused by "
        "this environment's egress proxy (CONNECT -> 403), so writing the header would be "
        "a guess shipped as a guarantee. "
        "CLOSED BY: a Bolna account (and a Cartesia one) to establish whether "
        "`POST /v2/agent` accepts an idempotency key and what it does with a repeat — "
        "then the header in both adapters and a conformance clause that replays a create."
    ),
}


def _create_agent_carries_no_idempotency_key() -> bool:
    """No adapter's create sends anything that would make a retry safe.

    Read from the SOURCE of the two real adapters rather than from a call, because the
    absence being recorded is the absence of a header on a request we cannot make here.
    """
    sources = [
        inspect.getsource(bolna.BolnaEngine.create_agent),
        inspect.getsource(cartesia.CartesiaEngine.create_agent),
    ]
    return not any("idempotency" in source.lower() for source in sources)


PROBES: dict[str, Callable[[], bool]] = {
    "create_agent_is_not_idempotent": _create_agent_carries_no_idempotency_key,
}


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
    adapters = (fake.FakeEngine, bolna.BolnaEngine, cartesia.CartesiaEngine)
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
