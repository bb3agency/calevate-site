"""The result vocabulary every pilot gate reports in — the SEAM between gate modules.

`scripts/pilot/` is written by several hands (this module's author owns the runner and
the API-executable trust gates 1/2/6; latency, concurrency, knowledge, fixture-recording
and scorecard rendering are separate slices). They all need one answer shape, so it lives
here and is re-exported from `scripts.pilot`:

    from scripts.pilot import GateRun, GateStatus, SubCheck

**WHY THIS IS `GateRun` AND `scorecard.GateResult` IS SOMETHING ELSE.** There are two
types here on purpose, at two levels, and they were briefly both called `GateResult` —
which forced every consumer to alias one on import, the reliable tell that two things are
wearing one name. A `GateRun` is what a HARNESS EXECUTION produced: sub-checks, three
statuses, built and thrown away by the runner. A `scorecard.GateResult` is what the
COMMITTED EVIDENCE records: a verdict, who observed it and when, an attestation with a
written source, four states because an artifact must distinguish "we tried and could not
tell" from "we never tried". A run is not evidence until a person stands behind it, and
`scorecard.from_runner_result()` is the single crossing between them — it is a boundary,
not duplication, and a pass on a human gate is DOWNGRADED as it crosses.

THE ONE RULE THIS FILE EXISTS TO ENFORCE: **NOT RUN is not PASS.**

A pilot scorecard that renders an unattempted gate as green is the single failure this
whole slice exists to prevent — D-31 reopens the engine decision on a red hard gate, so
a fabricated green is a vendor decision made on evidence that was never gathered. Hence:

* three statuses only (`pass` / `fail` / `not_run`), never a boolean;
* `not_run` REQUIRES a reason — the constructor refuses without one;
* a gate's status is DERIVED from its sub-checks (`GateRun.rolled_up`), and the
  roll-up is pessimistic: any fail ⇒ fail, else any not_run ⇒ not_run. A gate with one
  unexecuted sub-check can never report pass;
* `measurements` holds only numbers that were actually measured. A field that was not
  measured is ABSENT, never zero — "0 retries observed" and "we never looked" are
  different facts and a scorecard has to be able to tell them apart;
* `attested` marks a fact a HUMAN observed rather than something the harness measured
  (killing a receiver mid-call cannot be automated). Carried separately so no reader can
  mistake an operator's word for a measurement.

HARD RULE 6 APPLIES TO EVERYTHING HERE. These objects are serialized into an evidence
artefact that gets committed to git forever. Field NAMES, ids and counts go in; phone
numbers, transcript text and extraction payloads never do. `scripts/pilot/redact.py`
holds the outbound guard and `tests/pilot_redaction_test.py` proves it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

GateStatus = Literal["pass", "fail", "not_run"]

#: Printed forms. `NOT RUN` is spelled out rather than abbreviated because the whole
#: point is that a skim cannot mistake it for anything else.
STATUS_LABEL: dict[GateStatus, str] = {
    "pass": "PASS",
    "fail": "FAIL",
    "not_run": "NOT RUN",
}


class NotRunWithoutReasonError(ValueError):
    """Raised when a gate or sub-check reports `not_run` with nothing to say.

    A bare "not run" is how an unattempted gate becomes indistinguishable from a skipped
    one, and three weeks later nobody can say which. The reason is the artefact.
    """


@dataclass(frozen=True, slots=True)
class SubCheck:
    """One decidable question inside a gate.

    Gates in OPERATIONS §2 are written as prose paragraphs carrying three or four
    independent claims ("create agent → update prompt → attach number → start call ...
    `user_data` round-trips ... `scheduled_at` works"). Scoring that as one boolean loses
    exactly the information the pilot exists to produce: WHICH half of gate 2 our adapter
    cannot do. So each claim is its own row and the gate is their roll-up.
    """

    name: str
    status: GateStatus
    detail: str
    #: Non-PII numbers this check actually produced. Absent ≠ zero.
    measurements: dict[str, int | float | str | Decimal] = field(default_factory=dict)
    #: True when the fact came from a human's observation, not from our measurement.
    attested: bool = False

    def __post_init__(self) -> None:
        if self.status == "not_run" and not self.detail.strip():
            raise NotRunWithoutReasonError(f"sub-check {self.name!r} is not_run with no reason")

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "status": self.status,
            "label": STATUS_LABEL[self.status],
            "detail": self.detail,
        }
        if self.measurements:
            payload["measurements"] = {k: _plain(v) for k, v in self.measurements.items()}
        if self.attested:
            payload["source"] = "operator_attestation"
        return payload


@dataclass(frozen=True, slots=True)
class GateRun:
    """One row of the OPERATIONS §2 table, as an object.

    `findings` is the output this slice values most: a place our ADAPTER (or our
    contract) cannot do what the gate asks. Those are not failures of the vendor and
    must not be scored as one — they are work items for us, and they are exactly the
    thing a pilot discovers that no amount of reading the docs would have.
    """

    number: int
    title: str
    checks: tuple[SubCheck, ...] = ()
    #: Adapter/contract gaps found while running. Never scored; always reported.
    findings: tuple[str, ...] = ()
    #: Set only when the gate could not even begin (no engine, no credentials).
    blocked: str | None = None

    @property
    def status(self) -> GateStatus:
        if self.blocked is not None:
            return "not_run"
        return rolled_up(self.checks)

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "gate": self.number,
            "title": self.title,
            "status": self.status,
            "label": STATUS_LABEL[self.status],
            "checks": [c.as_dict() for c in self.checks],
        }
        if self.blocked is not None:
            payload["blocked"] = self.blocked
        if self.findings:
            payload["findings"] = list(self.findings)
        return payload


def rolled_up(checks: tuple[SubCheck, ...] | list[SubCheck]) -> GateStatus:
    """Pessimistic roll-up: fail beats not_run beats pass.

    The rejected alternative was "pass if nothing failed", which is the same sentence
    with the not_run rung deleted — and it is how a gate whose only executed sub-check
    was the trivial one reports green. A gate is only as run as its least-run part.
    """
    if not checks:
        return "not_run"
    if any(c.status == "fail" for c in checks):
        return "fail"
    if any(c.status == "not_run" for c in checks):
        return "not_run"
    return "pass"


def not_run(name: str, reason: str, **measurements: int | float | str | Decimal) -> SubCheck:
    """Constructor that makes the reason non-optional at the call site."""
    if not reason.strip():
        raise NotRunWithoutReasonError(f"sub-check {name!r} needs a reason to be not_run")
    return SubCheck(name=name, status="not_run", detail=reason, measurements=dict(measurements))


def passed(name: str, detail: str, **measurements: int | float | str | Decimal) -> SubCheck:
    return SubCheck(name=name, status="pass", detail=detail, measurements=dict(measurements))


def failed(name: str, detail: str, **measurements: int | float | str | Decimal) -> SubCheck:
    return SubCheck(name=name, status="fail", detail=detail, measurements=dict(measurements))


def _plain(value: int | float | str | Decimal) -> int | float | str:
    """Decimals serialize as STRINGS (hard rule 7): money that round-trips through a
    JSON float is money that has already been rounded by someone who was not asked."""
    return str(value) if isinstance(value, Decimal) else value


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
