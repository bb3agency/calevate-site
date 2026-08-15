"""Publish-verification defects that are OPEN, recorded so they cannot be rediscovered.

Every entry below was found while taking "what does `live` actually claim?" end to end,
is real, and could not be closed from inside this slice. Each names the specific reason
and the specific act that closes it — and unlike the reliability register next door, TWO
of these are genuinely waiting on a VENDOR ACCOUNT rather than on a file. That
distinction is the whole point of naming it: an engineering task has no timeline, and an
external blocker is nobody's to code around.

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
        "address. `agents/service.py::_orphaned` logs the ref so an operator can delete "
        "it by hand, and `_load_agent(for_update=True)` closes the concurrent-publish "
        "cause outright — but a retry of a create whose RESPONSE was lost still makes a "
        "second object. The standard remedy is an idempotency key on the create, and "
        "whether either vendor honours one is unknown: every vendor host is refused by "
        "this environment's egress proxy (CONNECT -> 403), so writing the header would be "
        "a guess shipped as a guarantee. "
        "CLOSED BY: a Bolna account (and a Cartesia one) to establish whether "
        "`POST /v2/agent` accepts an idempotency key and what it does with a repeat — "
        "then the header in both adapters and a conformance clause that replays a create."
    ),
    "no_delete_agent_on_the_protocol": (
        "There is no way to COMPENSATE an orphan: `VoiceEngine` can create, update and "
        "read an agent, and cannot remove one. So the orphan above is detectable and "
        "un-fixable from code, and a soft-deleted agent's vendor object outlives our row "
        "with nothing that could ever collect it. Adding `delete_agent` means putting a "
        "speculative endpoint on the Protocol that all four adapters must implement and "
        "the conformance suite must exercise, and an unverified vendor behaviour is not a "
        "capability (D-31/D-32). "
        "CLOSED BY: a Bolna account and a Cartesia account to establish that their delete "
        "exists, what it does to executions already recorded against the agent, and "
        "whether it is idempotent — then `delete_agent` on the Protocol, in all four "
        "adapters, with a conformance clause that deletes and re-reads."
    ),
    "no_scheduled_drift_reconciliation": (
        "`agents/publishing.py::engine_drift_for` and "
        "`GET /v1/agents/{agent_id}/engine-state` read the engine back ON DEMAND, so a "
        "drift is found by whoever thinks to look. An agent edited in the vendor's own "
        "dashboard, or one whose publish failed on our side after the vendor committed, "
        "stays wrong until someone opens that screen. The mechanism that should find it "
        "is a periodic sweep, and `apps/workers/**` is outside this slice. "
        "CLOSED BY: an ARQ cron job in `apps/workers` walking published agents through "
        "`engine_drift_for` and alerting on `state != 'applied'` — no vendor account "
        "needed, nothing to decide, one file this slice was not allowed to touch."
    ),
}


def _no_delete_on_the_protocol() -> bool:
    """No adapter can remove a vendor-side agent, so an orphan cannot be compensated."""
    adapters = (fake.FakeEngine, bolna.BolnaEngine, cartesia.CartesiaEngine)
    return not hasattr(VoiceEngine, "delete_agent") and not any(
        hasattr(adapter, "delete_agent") for adapter in adapters
    )


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


def _nothing_sweeps_for_drift() -> bool:
    """No worker calls the reconciliation read, so drift is found only by looking."""
    workers = REPO_ROOT / "apps" / "workers"
    return not any(
        "engine_drift_for" in path.read_text(encoding="utf-8") for path in workers.glob("*.py")
    )


PROBES: dict[str, Callable[[], bool]] = {
    "create_agent_is_not_idempotent": _create_agent_carries_no_idempotency_key,
    "no_delete_agent_on_the_protocol": _no_delete_on_the_protocol,
    "no_scheduled_drift_reconciliation": _nothing_sweeps_for_drift,
}


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
