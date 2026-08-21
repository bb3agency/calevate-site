"""A suppression reaches the queue — D-428(b), the half D-432 left open.

The halt half is best-effort and its tests measure that it stops what it can. This half is
different in the only way that matters: it may have to be DEFENDED. "Prove this number was
not called after we were told to stop" is a question a TSP or a regulator can ask, so the
properties below are about what the job is allowed to CLAIM, not only about what it does:

1. a suppression finds the dials queued to that number and no others — a recall that
   swept a tenant's whole queue because one number was suppressed would be a far worse
   defect than not sweeping at all;
2. a GLOBAL entry reaches every tenant, because it outranks every tenant's own list;
3. `PREVENTED` is recorded only when the engine says it caught the dial before it rang,
   and everything else — already running, or a stop that said nothing — is reported as
   undetermined and alarmed;
4. the enqueue is in the suppression's own transaction, so a rolled-back DNC insert
   leaves no recall behind;
5. the two spellings of the job name, API side and worker side, are the same string.

`_tenant_with_dials` is imported from the halt half's file rather than copied: the input
is the same shape, and two fixtures building a routed tenant would drift the day one of
them learned about a new column.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.compliance import dnc_recall as api_dnc_recall
from apps.api.db.session import tenant_session
from apps.workers import dnc_recall
from calevate_shared.engine import RecallOutcome
from sqlalchemy import text
from tests.dial_recall_test import _TENANTS, _quiet_platform, _tenant_with_dials

# Re-exported so pytest applies the halt file's autouse fixture here too: it settles the
# `queued` rows these cases create, which otherwise spend a line out of the outbound pool
# for every later suite on a shared Postgres.
__all__ = ["_quiet_platform"]

SUPPRESSED = "+919812345678"
OTHER = "+919887654321"


class _StubEngine:
    """The engine as THIS job uses it — a stop that returns a verdict.

    Deliberately not the halt file's stub: that one returns `None`, which is what
    `end_call` used to be, and the whole subject here is the verdict. A shared stub would
    have to satisfy both and would quietly let a `None` through as a falsy non-verdict.
    """

    name = "fake"

    def __init__(
        self,
        *,
        outcomes: dict[str, RecallOutcome] | None = None,
        refuse: set[str] | None = None,
    ) -> None:
        self.stopped: list[str] = []
        self._outcomes = outcomes or {}
        self._refuse = refuse or set()

    def holds_credentials(self) -> bool:
        return True

    async def end_call(self, call_id: str) -> RecallOutcome:
        if call_id in self._refuse:
            raise RuntimeError("vendor refused: already in progress")
        self.stopped.append(call_id)
        return self._outcomes.get(call_id, RecallOutcome.PREVENTED)


async def _run(
    monkeypatch: pytest.MonkeyPatch,
    engine: _StubEngine,
    *,
    phones: list[str],
    tenant_id: uuid.UUID | None,
) -> tuple[str, list[tuple[str, str]]]:
    fired: list[tuple[str, str]] = []
    monkeypatch.setattr(dnc_recall, "get_engine", lambda: engine)
    monkeypatch.setattr(dnc_recall, "alert", lambda stage, code, **kw: fired.append((stage, code)))
    result = await dnc_recall.recall_dials_for_dnc(
        {},
        {"phones": phones, "tenant_id": str(tenant_id) if tenant_id else None},
    )
    return result, fired


async def _stamped(tenant_id: uuid.UUID, call_ids: list[uuid.UUID]) -> int:
    async with tenant_session(tenant_id) as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM calls WHERE id = ANY(:ids) "
                        "AND recall_requested_at IS NOT NULL"
                    ),
                    {"ids": call_ids},
                )
            ).scalar_one()
        )


async def test_the_job_name_is_one_string_on_both_sides() -> None:
    """The API names the job and the worker answers to it; a typo is a silent drop.

    `check_job_wiring` proves the registered name matches the enqueued one, and it reads
    the API's constant to do it. This pins the reason the API has its own copy at all —
    `apps/api` must not import a worker module to name a job — so the duplication is
    deliberate and this is what stops it drifting.
    """
    assert api_dnc_recall.DNC_RECALL_JOB == dnc_recall.DNC_RECALL_JOB


async def test_a_suppression_recalls_that_number_and_leaves_the_rest_queued(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE CORE PROPERTY, and the one whose failure would be worse than doing nothing.

    A recall that swept everything a tenant had queued because ONE number was suppressed
    would tear down a running campaign on a compliance action — so the scan's filter is
    asserted on data, from the other side: the untouched dial must still be dialable.
    """
    target = f"ex-{uuid.uuid4().hex[:8]}"
    spare = f"ex-{uuid.uuid4().hex[:8]}"
    tenant_id, call_ids = await _tenant_with_dials(
        [
            {"engine_call_id": target, "to": SUPPRESSED},
            {"engine_call_id": spare, "to": OTHER},
        ]
    )
    engine = _StubEngine()

    result, fired = await _run(monkeypatch, engine, phones=[SUPPRESSED], tenant_id=tenant_id)

    assert target in engine.stopped
    assert spare not in engine.stopped, (
        "a suppression of one number recalled a dial to a different one — this would tear "
        "down a running campaign on a compliance action"
    )
    assert "prevented=1" in result
    assert fired == [], "a clean recall must not alarm"
    assert await _stamped(tenant_id, call_ids) == 1


async def test_a_global_suppression_reaches_every_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    """A global entry outranks every tenant's own list, so `tenant_id=None` is not absent.

    Two tenants, both holding a dial to the same number. A scan scoped to one of them
    would leave the other's ringing, and the number is suppressed platform-wide.
    """
    first = f"ex-{uuid.uuid4().hex[:8]}"
    second = f"ex-{uuid.uuid4().hex[:8]}"
    await _tenant_with_dials([{"engine_call_id": first, "to": SUPPRESSED}])
    await _tenant_with_dials([{"engine_call_id": second, "to": SUPPRESSED}])
    engine = _StubEngine()

    await _run(monkeypatch, engine, phones=[SUPPRESSED], tenant_id=None)

    assert {first, second} <= set(engine.stopped), (
        "a platform-wide suppression did not reach every tenant's queue"
    )


async def test_a_dial_already_running_is_never_recorded_as_prevented(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE CLAIM, and the reason `end_call` was widened to return a verdict at all.

    Three dials, three answers. Only the one the engine says it caught before it rang may
    count as prevented; a stop that said nothing (`UNKNOWN`) and one the vendor refused are
    both "we cannot say this number was not called", and both have to reach a person.
    """
    caught = f"ex-{uuid.uuid4().hex[:8]}"
    running = f"ex-{uuid.uuid4().hex[:8]}"
    silent = f"ex-{uuid.uuid4().hex[:8]}"
    tenant_id, _ = await _tenant_with_dials(
        [
            {"engine_call_id": caught, "to": SUPPRESSED},
            {"engine_call_id": running, "to": SUPPRESSED},
            {"engine_call_id": silent, "to": SUPPRESSED},
        ]
    )
    engine = _StubEngine(
        outcomes={caught: RecallOutcome.PREVENTED, silent: RecallOutcome.UNKNOWN},
        refuse={running},
    )

    result, fired = await _run(monkeypatch, engine, phones=[SUPPRESSED], tenant_id=tenant_id)

    assert "prevented=1" in result, result
    assert "undetermined=2" in result, result
    assert ("WORKER_STALL", "dnc_recall_undetermined") in fired, (
        "two dials to a suppressed number could not be confirmed as prevented and nobody was told"
    )


async def test_a_second_run_stops_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """`recall_requested_at` is shared with the halt path, so neither redoes the other's
    work — and a re-run cannot turn a clean recall into a compliance alarm by collecting
    the vendor's refusals for calls it already stopped."""
    ref = f"ex-{uuid.uuid4().hex[:8]}"
    tenant_id, _ = await _tenant_with_dials([{"engine_call_id": ref, "to": SUPPRESSED}])
    engine = _StubEngine()

    await _run(monkeypatch, engine, phones=[SUPPRESSED], tenant_id=tenant_id)
    engine.stopped.clear()
    result, fired = await _run(monkeypatch, engine, phones=[SUPPRESSED], tenant_id=tenant_id)

    assert ref not in engine.stopped
    assert "found=0" in result
    assert fired == []


async def test_nothing_queued_is_a_clean_answer_not_an_alarm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The overwhelmingly common case: a number is suppressed and nothing was queued to it.

    Asserted because the alternative — alarming on every ordinary opt-out — is how an
    alarm stops being read, and this job's alarm is one somebody has to act on.
    """
    tenant_id, _ = await _tenant_with_dials([{"engine_call_id": f"ex-{uuid.uuid4().hex[:8]}"}])
    engine = _StubEngine()

    result, fired = await _run(monkeypatch, engine, phones=[SUPPRESSED], tenant_id=tenant_id)

    assert result == "found=0"
    assert engine.stopped == []
    assert fired == []


async def test_the_enqueue_shares_the_suppressions_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A DNC insert that rolls back must leave no recall chasing it.

    `enqueue_dnc_recall` writes through the outbox in the caller's session and never
    commits, which is what buys this. Measured by rolling back and counting outbox rows
    rather than by reading the source.
    """
    tenant_id = uuid.uuid4()
    _TENANTS.append(tenant_id)
    async with tenant_session(tenant_id) as session:
        await api_dnc_recall.enqueue_dnc_recall(session, tenant_id=tenant_id, phones=[SUPPRESSED])
        queued: Any = (
            await session.execute(
                text(
                    "SELECT count(*) FROM outbox_messages WHERE job = :job "
                    "AND payload->>'tenant_id' = :tid"
                ),
                {"job": api_dnc_recall.DNC_RECALL_JOB, "tid": str(tenant_id)},
            )
        ).scalar_one()
        assert int(queued) == 1, "the enqueue did not reach the outbox at all"
        await session.rollback()

    async with tenant_session(tenant_id) as session:
        after: Any = (
            await session.execute(
                text(
                    "SELECT count(*) FROM outbox_messages WHERE job = :job "
                    "AND payload->>'tenant_id' = :tid"
                ),
                {"job": api_dnc_recall.DNC_RECALL_JOB, "tid": str(tenant_id)},
            )
        ).scalar_one()
    assert int(after) == 0, (
        "a rolled-back suppression left a recall behind — it would pull dials nobody suppressed"
    )


async def test_an_empty_phone_list_enqueues_nothing() -> None:
    """A bulk re-import of an unchanged list computes no fresh numbers and must cost
    nothing: an outbox row per no-op is noise in the table the dispatcher walks."""
    tenant_id = uuid.uuid4()
    _TENANTS.append(tenant_id)
    async with tenant_session(tenant_id) as session:
        await api_dnc_recall.enqueue_dnc_recall(session, tenant_id=tenant_id, phones=[])
        rows: Any = (
            await session.execute(
                text("SELECT count(*) FROM outbox_messages WHERE job = :job"),
                {"job": api_dnc_recall.DNC_RECALL_JOB},
            )
        ).scalar_one()
        await session.rollback()
    assert int(rows) == 0
