"""The big red switch's recall arm (D-432, closing the halt half of D-428).

`BolnaEngine.end_call` was implemented, conformance-tested and called by nothing, so the
switch stopped this platform PLACING dials and recalled none the vendor had already
accepted. These are the properties that make the recall trustworthy rather than merely
present, and each one is written as the failure it prevents:

1. the fleet-wide scan is SECURITY INVOKER and really scoped per tenant — the same hard
   rule 1 question `dispatch_scan` answers in `tests/dispatch_scan_rls_test.py`, asked of
   `queued_dial_scan` on DATA rather than on the SQL we think we wrote;
2. it sees a vendor-issued queued dial and skips the three shapes that must never be
   stopped — a `local:` pre-dial intent row, a dial that is already ringing, and one this
   platform has already recalled;
3. the job stops what it finds, stamps it, and a SECOND run stops nothing — the property
   `recall_requested_at` exists for, and the one whose absence would raise "could not stop
   N dials" on work that succeeded;
4. one dial's refusal does not end the run, and the refusals are alarmed;
5. it refuses to run at all when the platform is not halted, because an operator who
   released between the enqueue and the run must not have their campaign torn down.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from apps.api.core import loadshed
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.workers import dial_recall
from sqlalchemy import text

_TENANTS: list[uuid.UUID] = []


@pytest.fixture(autouse=True)
async def _quiet_platform() -> AsyncIterator[None]:
    """Halted for the duration, released after — and the rows this file made settled.

    Both halves matter on a Postgres shared with every other suite: a `queued` outbound
    call spends a line out of the pool, and a platform left halted stops every later
    test's dial. `tests/dispatch_scan_rls_test.py` argues the cleanup pattern at length.
    """
    await loadshed.set_platform_status(
        outbound_halted=True, halt_reason="recall test", actor_id=None
    )
    yield
    await loadshed.set_platform_status(outbound_halted=False, actor_id=None)
    for tenant_id in _TENANTS:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "UPDATE calls SET status = 'completed', updated_at = now() "
                    "WHERE status = 'queued'"
                )
            )
    _TENANTS.clear()


async def _tenant_with_dials(dials: list[dict[str, Any]]) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """A routed tenant holding exactly the dials described.

    Each entry is `{status, engine_call_id, recalled, to}`. Rows rather than the dial path:
    this file is about what the scan and the job see, and a bare organization + agent +
    route + calls is the whole input.
    """
    tenant_id, agent_id = uuid7(), uuid7()
    _TENANTS.append(tenant_id)
    ref = f"recall-{uuid.uuid4().hex[:10]}"
    call_ids: list[uuid.UUID] = []
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO organizations (id, name, slug, status, created_at, updated_at) "
                "VALUES (:id, 'Recall Motors', :slug, 'active', now(), now())"
            ),
            {"id": tenant_id, "slug": ref},
        )
        await session.execute(
            text(
                "INSERT INTO agents (id, tenant_id, name, direction, disclosure_line, "
                "ai_disclosure_line, recording_notice_line, caller_memory_notice_line, status, "
                "engine, engine_agent_ref, created_at, updated_at) VALUES (:id, :tid, 'Rec', "
                "'outbound', 'Idi AI assistant.', 'Idi AI assistant.', 'This call is being "
                "recorded.', 'I keep a short note of what you ask about.', 'live', 'fake', "
                ":ref, now(), now())"
            ),
            {"id": agent_id, "tid": tenant_id, "ref": ref},
        )
        for dial in dials:
            call_id = uuid7()
            call_ids.append(call_id)
            await session.execute(
                text(
                    "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                    "status, to_e164, recall_requested_at, created_at, updated_at) VALUES "
                    "(:id, :tid, :aid, :ec, 'outbound', :st, :to, "
                    "CASE WHEN :recalled THEN now() ELSE NULL END, now(), now())"
                ),
                {
                    "id": call_id,
                    "tid": tenant_id,
                    "aid": agent_id,
                    "ec": dial["engine_call_id"],
                    "st": dial.get("status", "queued"),
                    # `to_e164` is what the DNC recall's scan matches on
                    # (`tests/dnc_recall_test.py`); the halt's scan ignores it. Defaulted
                    # so every case in THIS file keeps describing only what it cares about.
                    "to": dial.get("to", "+919000000000"),
                    "recalled": dial.get("recalled", False),
                },
            )
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('fake', :ref, :tid, :aid, true, now(), "
                "now())"
            ),
            {"ref": ref, "tid": tenant_id, "aid": agent_id},
        )
    return tenant_id, call_ids


class _StubEngine:
    """The engine as this job uses it: credentials, a name, and a stop that can refuse."""

    name = "fake"

    def __init__(self, *, refuse: set[str] | None = None, credentials: bool = True) -> None:
        self.stopped: list[str] = []
        self._refuse = refuse or set()
        self._credentials = credentials

    def holds_credentials(self) -> bool:
        return self._credentials

    async def end_call(self, call_id: str) -> None:
        if call_id in self._refuse:
            raise RuntimeError("vendor refused")
        self.stopped.append(call_id)


async def _dials_for(tenant_id: uuid.UUID) -> list[dial_recall.QueuedDial]:
    found = await dial_recall._queued_dials(dial_recall.RECALL_SCAN_LIMIT)
    return [d for d in found if d.tenant_id == tenant_id]


async def test_the_scan_function_is_security_invoker() -> None:
    """The catalog, not the source file: what runs is what the database installed.

    `SECURITY DEFINER` owned by a role that bypasses RLS is the obvious way to make a
    cross-tenant scan simpler, and it would put a policy-blind role on the path that
    decides which of a client's calls get cancelled. This assertion makes that edit fail a
    build rather than a review — `dispatch_scan`'s test makes the identical argument.
    """
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT p.prosecdef, p.provolatile FROM pg_proc p "
                    "JOIN pg_namespace n ON n.oid = p.pronamespace "
                    "WHERE p.proname = 'queued_dial_scan' AND n.nspname = 'public'"
                )
            )
        ).first()
    assert row is not None, "migration d5c81f30ab47 did not install queued_dial_scan()"
    assert row[0] is False, "queued_dial_scan() must be SECURITY INVOKER (hard rule 1)"
    # VOLATILE for `dispatch_scan`'s reason: it sets a GUC per iteration, so a STABLE
    # marking would licence the planner to fold what is entirely a side effect.
    assert row[1] == "v", "queued_dial_scan() must stay VOLATILE — it sets a GUC per tenant"


async def test_each_tenant_in_the_loop_is_scoped_to_itself() -> None:
    """Two tenants, deliberately different dial counts, one walk.

    A loop whose RLS predicate were evaluated once — a cached plan, a folded
    `current_setting`, or the `set_config` left outside the loop, which is exactly the
    line this migration was first written without — would attribute every dial to the
    first tenant. Different counts is evidence about the running database.
    """
    one, _ = await _tenant_with_dials([{"engine_call_id": f"ex-{uuid.uuid4().hex[:8]}"}])
    four, _ = await _tenant_with_dials(
        [{"engine_call_id": f"ex-{uuid.uuid4().hex[:8]}"} for _ in range(4)]
    )

    found = await dial_recall._queued_dials(dial_recall.RECALL_SCAN_LIMIT)
    by_tenant: dict[uuid.UUID, int] = {}
    for dial in found:
        by_tenant[dial.tenant_id] = by_tenant.get(dial.tenant_id, 0) + 1

    assert by_tenant.get(one) == 1
    assert by_tenant.get(four) == 4


async def test_the_scan_skips_every_dial_that_must_not_be_stopped() -> None:
    """Three shapes, three reasons, one query.

    A `local:` id is the pre-dial intent row (`UNCONFIRMED_ENGINE_CALL_PREFIX`): the
    vendor has not named that dial, so there is nothing to send a stop for and
    `_reap_stuck_dialing` already settles it. An `in_progress` dial cannot be stopped by
    the vendor's own route and stopping it is not what `queued` means. An already-recalled
    dial is the false-alarm case `recall_requested_at` exists for.
    """
    live = f"ex-{uuid.uuid4().hex[:8]}"
    tenant_id, _ = await _tenant_with_dials(
        [
            {"engine_call_id": live},
            {"engine_call_id": f"local:{uuid7()}"},
            {"engine_call_id": f"ex-{uuid.uuid4().hex[:8]}", "status": "in_progress"},
            {"engine_call_id": f"ex-{uuid.uuid4().hex[:8]}", "recalled": True},
        ]
    )

    found = await _dials_for(tenant_id)
    assert [d.engine_call_id for d in found] == [live]


async def test_the_job_stops_what_it_finds_and_a_second_run_stops_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The idempotence `recall_requested_at` buys, sabotage-proved by running twice.

    Without the stamp the second run re-POSTs a stop for every dial the first one already
    stopped, takes the vendor's refusal for an already-stopped execution, and raises
    "could not stop N dials" on work that succeeded — a false alarm on the one control an
    operator reads literally mid-incident.
    """
    refs = [f"ex-{uuid.uuid4().hex[:8]}" for _ in range(3)]
    tenant_id, call_ids = await _tenant_with_dials([{"engine_call_id": r} for r in refs])
    engine = _StubEngine()
    monkeypatch.setattr(dial_recall, "get_engine", lambda: engine)

    await dial_recall.recall_queued_dials({})
    # SCOPED TO THIS TENANT'S REFS, never `== sorted(refs)`. The job is a FLEET-WIDE scan
    # by design, so on a Postgres shared with every other suite it legitimately stops
    # whatever else is queued — and an equality here fails on a neighbour's row rather
    # than on this behaviour. Cost a real red run before it was written this way.
    assert set(refs) <= set(engine.stopped)
    assert await _dials_for(tenant_id) == []

    async with tenant_session(tenant_id) as session:
        stamped = (
            await session.execute(
                text(
                    "SELECT count(*) FROM calls WHERE id = ANY(:ids) "
                    "AND recall_requested_at IS NOT NULL"
                ),
                {"ids": call_ids},
            )
        ).scalar_one()
    assert stamped == 3

    engine.stopped.clear()
    await dial_recall.recall_queued_dials({})
    assert not set(refs) & set(engine.stopped), "the stamp did not survive the second run"


async def test_one_refusal_does_not_end_the_run_and_is_alarmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The loop is what stops phones ringing.

    A `try` around the whole loop instead of around one stop would abandon the batch at
    the first refusal and report a SMALLER number — which reads healthier than the truth.
    The refused dial keeps a NULL stamp so the next halt tries it again.
    """
    good, bad = f"ex-{uuid.uuid4().hex[:8]}", f"ex-{uuid.uuid4().hex[:8]}"
    tenant_id, _ = await _tenant_with_dials([{"engine_call_id": bad}, {"engine_call_id": good}])
    engine = _StubEngine(refuse={bad})
    monkeypatch.setattr(dial_recall, "get_engine", lambda: engine)
    fired: list[tuple[str, str]] = []
    monkeypatch.setattr(
        dial_recall,
        "alert",
        lambda stage, code, **kw: fired.append((stage, code)),
    )

    await dial_recall.recall_queued_dials({})

    # Membership, not equality, for the reason the previous test spells out: the scan is
    # fleet-wide and a neighbour suite's queued dial is not this test's subject.
    assert good in engine.stopped, "the loop stopped at the refusal instead of carrying on"
    assert bad not in engine.stopped
    assert ("WORKER_STALL", "dial_recall_unstopped") in fired
    remaining = await _dials_for(tenant_id)
    assert [d.engine_call_id for d in remaining] == [bad]


async def test_a_released_platform_recalls_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Halted, then released, then the job runs — and must tear down nothing.

    The window is real: the job is enqueued on the halt edge and runs whenever a worker
    picks it up. An operator who halted by mistake and released two seconds later has a
    campaign that is dialling on purpose.
    """
    tenant_id, _ = await _tenant_with_dials([{"engine_call_id": f"ex-{uuid.uuid4().hex[:8]}"}])
    engine = _StubEngine()
    monkeypatch.setattr(dial_recall, "get_engine", lambda: engine)
    await loadshed.set_platform_status(outbound_halted=False, actor_id=None)

    assert await dial_recall.recall_queued_dials({}) == "skipped_not_halted"
    assert engine.stopped == []
    # Restored for the fixture's teardown, which expects to release a halted platform.
    await loadshed.set_platform_status(
        outbound_halted=True, halt_reason="recall test", actor_id=None
    )
    assert len(await _dials_for(tenant_id)) == 1


async def test_an_engine_with_no_credentials_says_so_rather_than_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Silence is the failure mode: the operator threw the switch and read success."""
    engine = _StubEngine(credentials=False)
    monkeypatch.setattr(dial_recall, "get_engine", lambda: engine)
    fired: list[tuple[str, str]] = []
    monkeypatch.setattr(
        dial_recall,
        "alert",
        lambda stage, code, **kw: fired.append((stage, code)),
    )

    assert await dial_recall.recall_queued_dials({}) == "skipped_no_credentials"
    assert ("WORKER_TERMINAL", "dial_recall_impossible") in fired
