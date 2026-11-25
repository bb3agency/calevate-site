"""Calls placed or in progress while the voice platform stops answering, and after it.

The platform is the only engine, so an outage is waited out. Every test here takes the
engine down (a request that times out or is refused, `engine_unreachable`), checks that
nothing of ours is closed, failed, set aside or lost while it is down and that the sweeps
stay inside their tick, then brings it back and checks the calls settle.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from apps.api.agents.service import unconfirmed_engine_call_id
from apps.api.core.errors import ProblemError
from apps.api.core.redis import get_redis
from apps.api.crm import live_calls
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine import vendor_http
from apps.api.engine.charges import EngineChargeListing
from apps.api.engine.fake import FakeEngine
from apps.api.engine.thinnest import BASE_URL, ThinnestEngine
from apps.api.engine.thinnest_workspace import current_workspace
from apps.api.engine.vendor_http import EngineRejectedError
from apps.workers import call_timeline, engine_charges, engine_outage, pipeline
from apps.workers.set_aside import set_aside_ids
from apps.workers.settings import WorkerSettings
from arq import Retry
from arq.worker import Function
from calevate_shared.engine import ExecutionListing, ExecutionSnapshot
from sqlalchemy import text
from tests.engine_workspace_test import _two_client_workspaces
from tests.thinnest_call_lifecycle_test import _routed_tenant

RUN = uuid.uuid4().hex[:10]


def _unreachable() -> ProblemError:
    """What `vendor_http` raises for a request the platform never answered."""
    return ProblemError(
        kind="dependency",
        code="engine_unreachable",
        title="Voice engine unreachable",
        detail="The voice platform did not respond.",
        failure_stage="CORE_LOGIC",
    )


class _Alerts:
    def __init__(self) -> None:
        self.raised: list[tuple[str, str | None, dict[str, str]]] = []

    def __call__(self, _stage: str, code: str, *, detail: str | None = None, **ids: str) -> None:
        self.raised.append((code, detail, ids))

    def codes(self) -> list[str]:
        return [code for code, _d, _i in self.raised]


# --- the adapter: a timeout and a refused connection are the platform not answering --------


def _thinnest(handler: Any) -> ThinnestEngine:
    return ThinnestEngine(
        api_key="ta_live_test",
        client=httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"Authorization": "Bearer ta_live_test"},
            transport=httpx.MockTransport(handler),
        ),
    )


@pytest.mark.parametrize(
    "failure",
    [httpx.ReadTimeout("slow"), httpx.ConnectError("refused")],
    ids=["timeout", "refused"],
)
async def test_a_request_the_platform_never_answers_reads_as_an_outage(
    monkeypatch: pytest.MonkeyPatch, failure: httpx.HTTPError
) -> None:
    async def _uncounted(_engine: str, *, kind: str, **_where: str | None) -> None:
        return None

    monkeypatch.setattr(vendor_http, "record_engine_failure", _uncounted)

    def handler(request: httpx.Request) -> httpx.Response:
        raise failure

    with pytest.raises(ProblemError) as raised:
        await _thinnest(handler).get_execution("out_live1")

    assert raised.value.code == "engine_unreachable"
    assert engine_outage.engine_unavailable(raised.value) is True
    assert pipeline._is_transient(raised.value) is True


def test_a_5xx_is_an_outage_and_a_4xx_or_our_own_fault_is_not() -> None:
    assert engine_outage.engine_unavailable(EngineRejectedError(status=502)) is True
    assert engine_outage.engine_unavailable(EngineRejectedError(status=404)) is False
    assert engine_outage.engine_unavailable(RuntimeError("our bug")) is False


def test_an_answer_resets_the_streak_and_a_refusal_counts_as_one() -> None:
    streak = engine_outage.OutageStreak(stop_after=2)
    assert streak.failed(_unreachable()) is True
    streak.answered()
    assert streak.failed(_unreachable()) is True
    assert streak.failed(EngineRejectedError(status=404)) is False
    assert streak.failed(_unreachable()) is True
    assert not streak.stopped
    assert streak.failed(_unreachable()) is True
    assert streak.stopped


# --- calls in progress while the outstanding probe asks about them -------------------------


class _Platform(FakeEngine):
    """Down until `recover()`, then it reports every call ended."""

    def __init__(self) -> None:
        super().__init__()
        self.down = True
        self.asked: list[str] = []
        self.searched: list[str] = []

    def recover(self) -> None:
        self.down = False

    async def get_execution(self, execution_id: str) -> ExecutionSnapshot:
        self.asked.append(execution_id)
        if self.down:
            raise _unreachable()
        return ExecutionSnapshot(
            engine_call_id=execution_id,
            status="completed",
            raw_status="completed",
            terminal=True,
            billable_ready=True,
            engine="fake",
            started_at=datetime.now(UTC) - timedelta(minutes=14),
            ended_at=datetime.now(UTC) - timedelta(minutes=10),
            duration_s=240,
        )

    async def find_placed_call(self, reference: str) -> str | None:
        self.searched.append(reference)
        if self.down:
            raise _unreachable()
        return None


@pytest.fixture
async def tenant() -> AsyncIterator[tuple[uuid.UUID, uuid.UUID]]:
    tenant_id, agent_id = await _routed_tenant()
    yield tenant_id, agent_id
    # A live outbound row holds a platform-wide line in other tests' counts.
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE calls SET status = 'completed' "
                "WHERE status IN ('queued', 'ringing', 'in_progress')"
            )
        )


async def _call(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    status: str,
    age: timedelta,
    placeholder: bool = False,
) -> tuple[uuid.UUID, str]:
    call_id = uuid7()
    handle = unconfirmed_engine_call_id(call_id) if placeholder else f"out-{RUN}-{call_id.hex}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
                "status, created_at, updated_at) VALUES (:id, :t, :a, :e, 'outbound', "
                "'+919800000001', :s, now() - make_interval(secs => :age), now())"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": handle,
                "s": status,
                "age": age.total_seconds(),
            },
        )
    return call_id, handle


async def _status(tenant_id: uuid.UUID, call_id: uuid.UUID) -> tuple[str, str | None]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT status, not_placed_reason FROM calls WHERE id = :i"), {"i": call_id}
            )
        ).one()
    return str(row[0]), row[1]


async def _sweep(
    monkeypatch: pytest.MonkeyPatch, engine: FakeEngine, tenant_id: uuid.UUID, alerts: _Alerts
) -> tuple[str, list[dict[str, Any]]]:
    queued: list[dict[str, Any]] = []

    async def _only() -> list[uuid.UUID]:
        return [tenant_id]

    async def _enqueue(job: str, payload: dict[str, Any], *, job_id: str | None = None) -> str:
        queued.append(payload)
        return job_id or job

    monkeypatch.setattr(pipeline, "callable_tenants", _only)
    monkeypatch.setattr(pipeline, "get_engine", lambda: engine)
    monkeypatch.setattr(pipeline, "enqueue", _enqueue)
    monkeypatch.setattr(pipeline, "alert", alerts)
    return await pipeline.reconcile_outstanding_calls({}), queued


async def test_calls_in_progress_are_left_alone_while_the_platform_is_down_then_settle(
    tenant: tuple[uuid.UUID, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, agent_id = tenant
    live = [
        await _call(tenant_id, agent_id, status="in_progress", age=timedelta(minutes=15 + i))
        for i in range(5)
    ]
    lost_dial, lost_handle = await _call(
        tenant_id, agent_id, status="queued", age=timedelta(minutes=15), placeholder=True
    )
    engine = _Platform()
    alerts = _Alerts()

    outcome, queued = await _sweep(monkeypatch, engine, tenant_id, alerts)

    # Stopped after the streak, not one ten-second timeout per call.
    assert len(engine.asked) + len(engine.searched) == engine_outage.OUTAGE_STOP_AFTER
    assert "engine_unavailable=1" in outcome
    assert queued == []
    for call_id, _handle in live:
        assert await _status(tenant_id, call_id) == ("in_progress", None)
    # Unanswered is not "no such call": the dial is not closed on a guess.
    assert await _status(tenant_id, lost_dial) == ("queued", None)
    # Nothing set aside, so the first tick after the outage asks again.
    aside = set(await set_aside_ids("outstanding_probe"))
    assert not aside & {handle for _id, handle in live} and lost_handle not in aside
    # The outage is paged by the listing sweep and the spike alarm, not here.
    assert alerts.codes() == []

    engine.recover()
    outcome, queued = await _sweep(monkeypatch, engine, tenant_id, alerts)

    assert {p["execution_id"] for p in queued} == {handle for _id, handle in live}
    assert all(p["source"] == "reconciliation" for p in queued)
    assert "repaired=5" in outcome and "engine_unavailable" not in outcome
    # Now the platform has answered that it never placed it.
    assert await _status(tenant_id, lost_dial) == ("failed", "dial_lost")


async def test_one_unanswered_probe_among_answers_is_alarmed_not_waited_out(
    tenant: tuple[uuid.UUID, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, agent_id = tenant
    await _call(tenant_id, agent_id, status="in_progress", age=timedelta(minutes=20))
    engine = _Platform()
    alerts = _Alerts()

    outcome, _ = await _sweep(monkeypatch, engine, tenant_id, alerts)

    assert "engine_unavailable" not in outcome and "unreached=1" in outcome
    assert alerts.codes() == ["outstanding_probe_incomplete"]


async def test_a_call_still_unfinished_past_the_horizon_is_reported_once_even_while_down(
    tenant: tuple[uuid.UUID, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, agent_id = tenant
    stale, _ = await _call(
        tenant_id,
        agent_id,
        status="in_progress",
        age=pipeline.OUTSTANDING_PROBE_HORIZON + timedelta(minutes=5),
    )
    engine = _Platform()
    alerts = _Alerts()

    outcome, _ = await _sweep(monkeypatch, engine, tenant_id, alerts)

    assert "expired=1" in outcome
    [(code, detail, ids)] = alerts.raised
    assert code == "calls_never_finished" and ids["call_id"] == str(stale)
    assert "24h" in (detail or "")
    assert engine.asked == []
    assert await _status(tenant_id, stale) == ("in_progress", None)

    again = _Alerts()
    outcome, _ = await _sweep(monkeypatch, engine, tenant_id, again)
    assert "expired=0" in outcome and again.codes() == []


async def test_a_platform_answering_slowly_stops_the_sweep_inside_its_tick(
    tenant: tuple[uuid.UUID, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, agent_id = tenant
    call_id, _ = await _call(tenant_id, agent_id, status="in_progress", age=timedelta(minutes=20))
    monkeypatch.setattr(pipeline, "OUTSTANDING_PROBE_DEADLINE", timedelta(0))
    engine = _Platform()
    engine.recover()
    alerts = _Alerts()

    outcome, queued = await _sweep(monkeypatch, engine, tenant_id, alerts)

    assert engine.asked == [] and queued == [] and "probed=0" in outcome
    [(code, detail, _ids)] = alerts.raised
    assert code == "outstanding_probe_budget_exhausted" and "slowly" in (detail or "")
    assert await _status(tenant_id, call_id) == ("in_progress", None)


async def test_a_lost_dial_the_platform_cannot_be_asked_about_stays_queued(
    tenant: tuple[uuid.UUID, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, agent_id = tenant
    lost_dial, lost_handle = await _call(
        tenant_id, agent_id, status="queued", age=timedelta(minutes=15), placeholder=True
    )
    engine = _Platform()
    alerts = _Alerts()

    outcome, _ = await _sweep(monkeypatch, engine, tenant_id, alerts)

    assert len(engine.searched) >= 1 and "lost_dials_closed=0" in outcome
    assert await _status(tenant_id, lost_dial) == ("queued", None)
    assert lost_handle not in await set_aside_ids("outstanding_probe")
    assert alerts.codes() == ["outstanding_probe_incomplete"]


async def test_a_slow_platform_stops_the_lost_dial_search_inside_its_tick(
    tenant: tuple[uuid.UUID, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, agent_id = tenant
    lost_dial, _ = await _call(
        tenant_id, agent_id, status="queued", age=timedelta(minutes=15), placeholder=True
    )
    monkeypatch.setattr(pipeline, "OUTSTANDING_PROBE_DEADLINE", timedelta(0))
    engine = _Platform()
    alerts = _Alerts()

    await _sweep(monkeypatch, engine, tenant_id, alerts)

    assert engine.searched == []
    assert alerts.codes() == ["outstanding_probe_budget_exhausted"]
    assert await _status(tenant_id, lost_dial) == ("queued", None)


# --- the listing sweep: an outage longer than its window -----------------------------------


class _Lister:
    def __init__(self, name: str) -> None:
        self.name = name
        self.down = True
        self.since: list[datetime] = []

    async def list_executions(self, *, since: datetime) -> ExecutionListing:
        self.since.append(since)
        if self.down:
            raise _unreachable()
        return ExecutionListing(snapshots=[], complete=True, pages_fetched=1)


@pytest.fixture
async def lister(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[tuple[_Lister, _Alerts]]:
    engine = _Lister(f"outage-{RUN}-{uuid.uuid4().hex[:6]}")
    alerts = _Alerts()
    monkeypatch.setattr(pipeline, "get_engine", lambda: engine)
    monkeypatch.setattr(pipeline, "alert", alerts)
    yield engine, alerts
    await get_redis().delete(pipeline._LISTING_HEARD_KEY.format(engine=engine.name))


async def _heard(engine: _Lister, ago: timedelta) -> None:
    await get_redis().set(
        pipeline._LISTING_HEARD_KEY.format(engine=engine.name),
        str((datetime.now(UTC) - ago).timestamp()),
    )


async def test_after_an_outage_the_listing_starts_where_it_last_heard_the_platform(
    lister: tuple[_Lister, _Alerts],
) -> None:
    engine, alerts = lister
    await _heard(engine, timedelta(hours=3))

    assert await pipeline.reconcile_executions({}) == "engine_unavailable"
    assert await pipeline.reconcile_executions({}) == "engine_unavailable"
    [(code, detail, _ids)] = alerts.raised[:1]
    assert code == "reconciliation_fetch_failed" and "not answering" in (detail or "")

    engine.down = False
    began = time.time()
    assert await pipeline.reconcile_executions({}) == "repaired=0"
    caught_up = engine.since[-1]
    expected = datetime.now(UTC) - timedelta(hours=3) - pipeline.LISTING_OVERLAP
    assert abs((caught_up - expected).total_seconds()) < 60

    # Heard, so the next tick is back to the fixed window.
    await pipeline.reconcile_executions({})
    steady = engine.since[-1]
    assert abs((datetime.now(UTC) - pipeline.LISTING_WINDOW - steady).total_seconds()) < 60
    stored = await get_redis().get(pipeline._LISTING_HEARD_KEY.format(engine=engine.name))
    assert float(stored) >= began - 1
    assert "reconciliation_listing_incomplete" not in alerts.codes()


async def test_a_catch_up_longer_than_the_horizon_is_cut_there_and_alarmed(
    lister: tuple[_Lister, _Alerts],
) -> None:
    engine, alerts = lister
    engine.down = False
    await _heard(engine, timedelta(days=2))

    await pipeline.reconcile_executions({})

    floor = datetime.now(UTC) - pipeline.LISTING_CATCH_UP_MAX
    assert abs((engine.since[-1] - floor).total_seconds()) < 60
    assert alerts.codes() == ["reconciliation_listing_incomplete"]


async def test_a_watermark_redis_cannot_give_falls_back_to_the_window(
    lister: tuple[_Lister, _Alerts], monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, _alerts = lister
    engine.down = False
    await get_redis().set(pipeline._LISTING_HEARD_KEY.format(engine=engine.name), "garbage")

    await pipeline.reconcile_executions({})
    window = datetime.now(UTC) - pipeline.LISTING_WINDOW
    assert abs((engine.since[-1] - window).total_seconds()) < 60

    class _NoRedis:
        async def get(self, _key: str) -> None:
            raise ConnectionError("redis down")

        async def set(self, *_a: Any, **_kw: Any) -> None:
            raise ConnectionError("redis down")

    monkeypatch.setattr(pipeline, "get_redis", lambda: _NoRedis())
    assert await pipeline.reconcile_executions({}) == "repaired=0"
    assert abs((engine.since[-1] - window).total_seconds()) < 60


async def test_a_platform_down_in_every_workspace_stops_the_walk_with_one_alarm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read_in: list[str | None] = []

    class _Down:
        name = "thinnest"

        async def list_executions(self, *, since: Any) -> ExecutionListing:
            read_in.append(current_workspace())
            raise _unreachable()

    alerts = _Alerts()
    _two_client_workspaces(monkeypatch)
    monkeypatch.setattr(pipeline, "get_engine", lambda: _Down())
    monkeypatch.setattr(pipeline, "alert", alerts)
    monkeypatch.setattr(engine_outage, "OUTAGE_STOP_AFTER", 2)
    heard = await get_redis().get(pipeline._LISTING_HEARD_KEY.format(engine="thinnest"))

    assert await pipeline.reconcile_executions({}) == "engine_unavailable"

    assert len(read_in) == engine_outage.OUTAGE_STOP_AFTER
    assert alerts.codes() == ["reconciliation_fetch_failed"]
    # Not heard, so the watermark did not move.
    assert await get_redis().get(pipeline._LISTING_HEARD_KEY.format(engine="thinnest")) == heard


# --- post-call work ------------------------------------------------------------------------


def test_an_ingest_that_gave_up_does_not_hold_its_id() -> None:
    """A kept result refused the vendor's re-send and the poller's re-drive for an hour."""
    [registered] = [
        fn
        for fn in WorkerSettings.functions
        if getattr(fn, "__name__", None) == pipeline.INGEST_JOB
    ]
    assert isinstance(registered, Function) and registered.keep_result_s == 0


async def test_an_ingest_retries_then_says_the_platform_is_not_answering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alerts = _Alerts()
    monkeypatch.setattr(pipeline, "alert", alerts)

    with pytest.raises(Retry):
        await pipeline._abandon_ingest(
            inbox_row_id=None, exc=_unreachable(), attempt=1, execution_id="out_1"
        )
    with pytest.raises(ProblemError):
        await pipeline._abandon_ingest(
            inbox_row_id=None, exc=_unreachable(), attempt=3, execution_id="out_1"
        )
    [(code, detail, _ids)] = alerts.raised
    assert code == "engine_ingest_abandoned" and "re-drive" in (detail or "")


class _Timeline:
    def __init__(self, failure: Exception) -> None:
        self.failure = failure

    async def get_call_timeline(self, call_id: str) -> None:
        raise self.failure


async def _timeline_row() -> tuple[uuid.UUID, uuid.UUID]:
    tenant_id, agent_id = await _routed_tenant()
    call_id, _ = await _call(tenant_id, agent_id, status="completed", age=timedelta(minutes=5))
    return tenant_id, call_id


async def test_a_timeline_fetch_waits_out_the_platform_instead_of_giving_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, call_id = await _timeline_row()
    queued: list[tuple[dict[str, Any], str | None]] = []

    async def _enqueue(job: str, payload: dict[str, Any], **kwargs: Any) -> str:
        queued.append((payload, kwargs.get("job_id")))
        return "queued"

    monkeypatch.setattr(call_timeline, "enqueue", _enqueue)
    payload = {"tenant_id": str(tenant_id), "call_id": str(call_id), "execution_id": "out_t"}

    # A 5xx was read as a refusal and lost the timeline on the first try.
    monkeypatch.setattr(
        call_timeline, "get_engine", lambda: _Timeline(EngineRejectedError(status=503))
    )
    with pytest.raises(Retry):
        await call_timeline.fetch_call_timeline({"job_try": 1}, payload)

    monkeypatch.setattr(call_timeline, "get_engine", lambda: _Timeline(_unreachable()))
    assert await call_timeline.fetch_call_timeline({"job_try": 3}, payload) == "requeued:1"
    [(again, job_id)] = queued
    assert again["outage_round"] == 1 and job_id is not None and job_id.endswith("outage-1")

    spent = {**payload, "outage_round": call_timeline.OUTAGE_ROUNDS}
    outcome = await call_timeline.fetch_call_timeline({"job_try": 3}, spent)
    assert outcome == "unreachable:engine_unreachable" and len(queued) == 1


# --- billing: the charge sweep against a platform that is down -----------------------------


async def test_the_charge_sweep_stops_at_an_unanswering_platform_and_charges_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read_in: list[str | None] = []

    class _Down:
        name = "thinnest"

        def holds_credentials(self) -> bool:
            return True

        async def list_call_charges(self, *, since: Any) -> EngineChargeListing:
            read_in.append(current_workspace())
            raise _unreachable()

    late_checks: list[Any] = []

    async def _late(engine: Any, **_kw: Any) -> int:
        late_checks.append(engine)
        return 0

    alerts = _Alerts()
    _two_client_workspaces(monkeypatch)
    monkeypatch.setattr(engine_outage, "OUTAGE_STOP_AFTER", 2)
    monkeypatch.setattr(engine_charges, "get_engine", lambda: _Down())
    monkeypatch.setattr(engine_charges, "alert", alerts)
    monkeypatch.setattr(engine_charges, "check_late_billing", _late)

    outcome = await engine_charges.reconcile_engine_charges({})

    assert len(read_in) == 2
    assert "compared=0" in outcome and "complete=False" in outcome
    assert late_checks == []
    [(code, detail, _ids)] = alerts.raised
    assert code == "engine_charge_workspace_unreadable" and "stopped answering" in (detail or "")


async def test_the_late_billing_listing_stops_at_an_unanswering_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[str | None] = []

    class _Down:
        name = "thinnest"

        async def list_executions(self, *, since: Any) -> ExecutionListing:
            asked.append(current_workspace())
            raise _unreachable()

    monkeypatch.setattr(engine_outage, "OUTAGE_STOP_AFTER", 2)
    ids = {f"out_{n}@org_w{n}" for n in range(4)}

    rows = await engine_charges.listed_billing(
        _Down(),  # type: ignore[arg-type]
        ids,
        since=datetime.now(UTC),
    )

    assert rows == {} and len(asked) == 2


# --- webhook endpoints: the sweep that re-enables them -------------------------------------


async def test_the_webhook_sweep_stops_at_an_unanswering_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.core.settings import get_settings
    from apps.workers import engine_webhooks as sweep
    from tests.thinnest_webhook_registration_test import _aged, _route

    for index in range(4):
        tenant_id, ref = await _route()
        await _aged(tenant_id, ref, f"1990-01-0{index + 1}")
    asked: list[str] = []

    async def _down(_session: Any, *, engine: str, engine_agent_ref: str) -> Any:
        asked.append(engine_agent_ref)
        raise _unreachable()

    alerts = _Alerts()
    monkeypatch.setattr(sweep, "ensure_agent_webhook", _down)
    monkeypatch.setattr(sweep, "alert", alerts)
    monkeypatch.setattr(get_settings(), "engine", "thinnest")

    await sweep.reconcile_engine_webhooks({})

    assert len(asked) == engine_outage.OUTAGE_STOP_AFTER
    [(code, detail, _ids)] = alerts.raised
    assert code == "engine_webhook_sweep_incomplete" and "stopped answering" in (detail or "")


# --- the call log's live read --------------------------------------------------------------


async def test_the_live_read_asks_once_while_the_platform_is_down_and_keeps_the_rows(
    tenant: tuple[uuid.UUID, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, agent_id = tenant
    ids = [
        (await _call(tenant_id, agent_id, status="in_progress", age=timedelta(minutes=2)))[0]
        for _ in range(6)
    ]
    engine = _Platform()
    monkeypatch.setattr(live_calls, "get_engine", lambda: engine)

    async with tenant_session(tenant_id) as session:
        out = await live_calls.read_live_calls(session, ids)

    assert len(engine.asked) == 1
    assert {row.status for row in out} == {"in_progress"}
    assert {row.live_state for row in out} == {"live"}
    assert all(row.status_source == "call" for row in out)
