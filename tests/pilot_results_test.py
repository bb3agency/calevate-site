"""The one doctrine the pilot harness cannot get wrong: NOT RUN is not PASS.

A scorecard that renders an unattempted gate as green is the failure this whole slice
exists to prevent — D-31 reopens the engine decision on a red hard gate, so a fabricated
green is a vendor decision made on evidence nobody gathered. These tests pin the three
mechanisms that stop it: the pessimistic roll-up, the mandatory reason, and the fact that
an unmeasured number is absent rather than zero.
"""

from __future__ import annotations

import pytest
from scripts.pilot.results import (
    GateRun,
    NotRunWithoutReasonError,
    SubCheck,
    failed,
    not_run,
    passed,
    rolled_up,
)


def test_a_gate_with_one_unrun_check_is_not_pass() -> None:
    gate = GateRun(
        number=2,
        title="Full API provisioning",
        checks=(
            passed("create_agent", "ok"),
            passed("update_prompt", "ok"),
            not_run("scheduled_at", "not expressible through our contract"),
        ),
    )
    assert gate.status == "not_run"
    assert gate.as_dict()["label"] == "NOT RUN"


def test_a_failure_outranks_an_unrun_check() -> None:
    assert rolled_up([passed("a", "ok"), not_run("b", "why"), failed("c", "broken")]) == "fail"


def test_a_gate_with_no_checks_is_not_pass() -> None:
    """The empty roll-up is the shape a stub gate has, and `all([])` is True — which is
    exactly how an unimplemented gate reports green in a hand-written scorer."""
    assert GateRun(number=13, title="Concurrency ceiling").status == "not_run"


def test_every_check_passing_is_the_only_way_to_pass() -> None:
    gate = GateRun(number=1, title="t", checks=(passed("a", "ok"), passed("b", "ok")))
    assert gate.status == "pass"


def test_not_run_without_a_reason_is_refused() -> None:
    with pytest.raises(NotRunWithoutReasonError):
        not_run("scheduled_at", "   ")
    with pytest.raises(NotRunWithoutReasonError):
        SubCheck(name="scheduled_at", status="not_run", detail="")


def test_blocked_gate_reports_not_run_whatever_its_checks_say() -> None:
    gate = GateRun(
        number=11,
        title="(not implemented)",
        checks=(passed("a", "ok"),),
        blocked="support responsiveness is a human interview",
    )
    assert gate.status == "not_run"


def test_an_unmeasured_number_is_absent_not_zero() -> None:
    """`retries_observed = 0` and "we never looked" are different facts, and a scorecard
    has to be able to tell them apart."""
    never_looked = not_run("no_retry_as_documented", "not observed")
    measured_zero = passed("no_retry_as_documented", "none arrived", retries_observed=0)
    assert "measurements" not in never_looked.as_dict()
    assert measured_zero.as_dict()["measurements"] == {"retries_observed": 0}


def test_attested_facts_are_labelled_as_such() -> None:
    """An operator's word must never read like a measurement."""
    check = SubCheck(name="call_continued", status="pass", detail="observed", attested=True)
    assert check.as_dict()["source"] == "operator_attestation"
    assert "source" not in passed("measured", "by us").as_dict()
