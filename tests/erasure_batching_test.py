"""The subject-erasure arms that no index can help, run as bounded statements.

**THE DEFECT.** Two arms of the §12 erasure compare the last ten DIGITS of a number
against `regexp_replace(<column>, '[^0-9]', '', 'g')` — a per-row function call, so no
index can serve it and none ever will. As a single statement each was a sequential scan
with no `LIMIT`, which on a large tenant is a multi-minute statement holding locks the
whole time.

**WHY A TIMEOUT IS THE WRONG ANSWER, which is the half worth a test.** A
`statement_timeout` is arriving on this deployment; applied to these arms it CANCELS them,
so a §12 request that must complete instead fails for a tenant for being large, and the
transaction rolls back with no certificate. Exempting the erasure job from the timeout
keeps the lock, which is the actual defect. So the arms are batched: each statement is
small enough to finish inside any timeout worth setting, and the loop runs until the
predicate is empty because an erasure may not defer work the way the retention sweep may.

These are unit tests over `_delete_in_batches` with a stub session, deliberately: the
property under test is the LOOP's — that it accumulates, that it stops on a short batch,
and that it raises rather than returning a partial count — and none of that needs a
database to be true.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from apps.workers import retention


@dataclass
class _Result:
    rowcount: int


class _StubSession:
    """Answers each `execute` with the next rowcount, and records what it was asked."""

    def __init__(self, rowcounts: list[int]) -> None:
        self._rowcounts = list(rowcounts)
        self.calls: list[dict[str, Any]] = []

    async def execute(self, _statement: Any, params: dict[str, Any] | None = None) -> _Result:
        self.calls.append(dict(params or {}))
        return _Result(self._rowcounts.pop(0) if self._rowcounts else 0)


async def test_a_full_batch_is_followed_by_another_statement() -> None:
    """A statement that removed exactly its limit may not be the last one: the rows it
    could not reach are rows the certificate would otherwise claim were erased."""
    session = _StubSession([retention.SUBJECT_ERASURE_BATCH, retention.SUBJECT_ERASURE_BATCH, 7])
    erased = await retention._delete_in_batches(session, "DELETE ...", {"digits": "9876543210"})
    assert erased == 2 * retention.SUBJECT_ERASURE_BATCH + 7
    assert len(session.calls) == 3


async def test_the_batch_limit_is_passed_to_every_statement() -> None:
    """The SQL carries `LIMIT :batch`; a caller's params are merged, never replaced."""
    session = _StubSession([0])
    await retention._delete_in_batches(session, "DELETE ...", {"tid": "t-1"})
    assert session.calls == [{"tid": "t-1", "batch": retention.SUBJECT_ERASURE_BATCH}]


async def test_a_short_batch_ends_the_loop() -> None:
    """Termination has no cursor behind it: these are DELETEs, so the rows one statement
    removed cannot match the next. A short batch means the predicate is empty."""
    session = _StubSession([3, 999])
    assert await retention._delete_in_batches(session, "DELETE ...", {}) == 3
    assert len(session.calls) == 1


async def test_an_empty_predicate_costs_one_statement() -> None:
    session = _StubSession([0])
    assert await retention._delete_in_batches(session, "DELETE ...", {}) == 0
    assert len(session.calls) == 1


async def test_a_loop_that_will_not_converge_raises_rather_than_certifying_a_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE ONE FAILURE MODE THAT MUST NOT BE SILENT. A predicate that keeps matching after
    its rows were deleted is a bug, and the tempting response — return what we have — puts
    "we erased everything" on a document that is false. Raising rolls the erasure's whole
    transaction back, so no certificate is written at all.
    """
    monkeypatch.setattr(retention, "_MAX_ERASURE_BATCHES", 3)
    session = _StubSession([retention.SUBJECT_ERASURE_BATCH] * 10)
    with pytest.raises(RuntimeError, match="did not converge"):
        await retention._delete_in_batches(session, "DELETE ...", {})
    assert len(session.calls) == 3


def test_every_batched_arm_actually_carries_the_limit() -> None:
    """The loop is only bounded if the SQL is. A `:batch` the statement ignores would make
    each pass delete everything and the second pass find nothing — a green test over an
    unbounded statement, which is exactly what this file exists to prevent."""
    for sql in (
        retention._COPILOT_TURN_SUBJECT_SQL,
        retention._OUTBOX_SUBJECT_SQL,
        retention._OUTBOX_TENANT_SQL,
    ):
        assert "LIMIT :batch" in sql
        assert sql.strip().upper().startswith("DELETE")


def test_the_unindexable_arms_are_the_batched_ones() -> None:
    """Pins WHICH arms this reasoning applies to. A new digit-matching arm added beside
    these without a `LIMIT` is the regression, and this is what notices."""
    digit_matchers = [
        name
        for name, value in vars(retention).items()
        if isinstance(value, str)
        and "regexp_replace" in value
        and value.strip().startswith("DELETE")
    ]
    assert sorted(digit_matchers) == ["_COPILOT_TURN_SUBJECT_SQL", "_OUTBOX_SUBJECT_SQL"]
    assert all("LIMIT :batch" in getattr(retention, name) for name in digit_matchers)
