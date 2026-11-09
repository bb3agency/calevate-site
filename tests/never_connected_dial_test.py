"""A dial whose answer was lost and that the engine never placed is shown as not connected.

`agents.service.dispatch_call` writes the intent row under our placeholder id and `queued`;
the engine's record adopts it (`pipeline._ADOPT_UNCONFIRMED_DIAL_SQL`). A row nothing adopts
is settled by `pipeline.reconcile_outstanding_calls`: the engine is asked by the reference
we placed the call under (`GET /calls?reference=`, thinnest-findings/mirror/snapshots/
2026-10-29/pages/api-reference/calls/list-calls.md:484-493), and a call it holds is
re-driven through the ingest while none closes the row `failed` / `dial_lost`.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from apps.api.agents import service as agents_service
from apps.api.agents.service import unconfirmed_engine_call_id
from apps.api.core.errors import ProblemError
from apps.api.crm.service import NOT_PLACED_WORDS, get_call
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine import dial_lines
from apps.api.engine.fake import FakeEngine
from apps.api.engine.thinnest import BASE_URL, ThinnestEngine
from apps.api.engine.thinnest_workspace import current_workspace, in_workspace
from apps.workers import pipeline
from apps.workers.engine_delivery import FindsPlacedCalls
from sqlalchemy import text
from tests.thinnest_call_lifecycle_test import _routed_tenant


class _Finder(FakeEngine):
    """The in-memory engine, answering the search by reference as told."""

    def __init__(self, answer: str | Exception | None = None) -> None:
        super().__init__()
        self.answer = answer
        self.asked: list[tuple[str, str | None]] = []
        self.before_answer: Any = None

    async def find_placed_call(self, reference: str) -> str | None:
        self.asked.append((reference, current_workspace()))
        if self.before_answer is not None:
            await self.before_answer()
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


@pytest.fixture
async def tenant() -> AsyncIterator[tuple[uuid.UUID, uuid.UUID]]:
    tenant_id, agent_id = await _routed_tenant()
    yield tenant_id, agent_id
    # A queued outbound row holds a platform-wide line in other tests' counts.
    async with tenant_session(tenant_id) as session:
        await session.execute(text("UPDATE calls SET status = 'completed' WHERE status = 'queued'"))


async def _intent_row(tenant_id: uuid.UUID, agent_id: uuid.UUID, *, minutes_old: int) -> uuid.UUID:
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
                "status, created_at, updated_at) VALUES (:id, :t, :a, :e, 'outbound', "
                "'+919800000001', 'queued', now() - make_interval(mins => :m), now())"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": unconfirmed_engine_call_id(call_id),
                "m": minutes_old,
            },
        )
    return call_id


async def _row(tenant_id: uuid.UUID, call_id: uuid.UUID) -> tuple[str, str, str | None]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT engine_call_id, status, not_placed_reason FROM calls WHERE id = :i"),
                {"i": call_id},
            )
        ).one()
    return str(row[0]), str(row[1]), row[2]


async def _sweep(
    monkeypatch: pytest.MonkeyPatch, engine: FakeEngine, *tenants: uuid.UUID
) -> tuple[str, list[tuple[str, dict[str, Any], str | None]]]:
    queued: list[tuple[str, dict[str, Any], str | None]] = []

    async def _only() -> list[uuid.UUID]:
        return list(tenants)

    async def _enqueue(job: str, payload: dict[str, Any], *, job_id: str | None = None) -> str:
        queued.append((job, payload, job_id))
        return job_id or job

    monkeypatch.setattr(pipeline, "callable_tenants", _only)
    monkeypatch.setattr(pipeline, "get_engine", lambda: engine)
    monkeypatch.setattr(pipeline, "enqueue", _enqueue)
    return await pipeline.reconcile_outstanding_calls({}), queued


async def _lines_in_use(tenant_id: uuid.UUID) -> int:
    async with tenant_session(tenant_id) as session:
        return await agents_service._platform_scalar(
            session,
            agents_service._ENGINE_LINES_IN_USE_SQL,
            {
                "statuses": agents_service._ENGINE_LINE_STATUSES,
                "horizon": dial_lines.ENGINE_LINE_HORIZON.total_seconds(),
            },
        )


# --- the sweep ---------------------------------------------------------------------------


async def test_an_old_dial_the_engine_never_placed_is_closed_as_not_connected(
    tenant: tuple[uuid.UUID, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, agent_id = tenant
    call_id = await _intent_row(tenant_id, agent_id, minutes_old=15)
    held = await _lines_in_use(tenant_id)
    engine = _Finder(answer=None)

    result, queued = await _sweep(monkeypatch, engine, tenant_id)

    assert engine.asked == [(str(call_id), None)]
    assert await _row(tenant_id, call_id) == (
        unconfirmed_engine_call_id(call_id),
        "failed",
        "dial_lost",
    )
    assert "lost_dials_closed=1" in result
    assert queued == [], "nothing is re-driven or billed for a call that never existed"
    assert await _lines_in_use(tenant_id) == held - 1, "the line it held is free again"
    async with tenant_session(tenant_id) as session:
        detail = await get_call(session, call_id)
    assert detail.status == "failed"
    assert detail.not_placed_reason == NOT_PLACED_WORDS["dial_lost"]
    assert detail.live_state is None


async def test_a_young_dial_is_left_alone(
    tenant: tuple[uuid.UUID, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, agent_id = tenant
    call_id = await _intent_row(tenant_id, agent_id, minutes_old=2)
    engine = _Finder(answer=None)

    await _sweep(monkeypatch, engine, tenant_id)

    assert engine.asked == []
    assert (await _row(tenant_id, call_id))[1:] == ("queued", None)


async def test_a_dial_adopted_while_the_engine_was_asked_is_not_touched(
    tenant: tuple[uuid.UUID, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, agent_id = tenant
    call_id = await _intent_row(tenant_id, agent_id, minutes_old=15)
    vendor_id = f"out_{uuid.uuid4()}"

    async def _adopted_meanwhile() -> None:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(pipeline._ADOPT_UNCONFIRMED_DIAL_SQL),
                {
                    "ecid": vendor_id,
                    "placed": call_id,
                    "local": unconfirmed_engine_call_id(call_id),
                },
            )

    engine = _Finder(answer=None)
    engine.before_answer = _adopted_meanwhile

    result, _ = await _sweep(monkeypatch, engine, tenant_id)

    assert await _row(tenant_id, call_id) == (vendor_id, "queued", None)
    assert "lost_dials_closed=0" in result


async def test_a_dial_the_engine_holds_is_re_driven_for_adoption_not_closed(
    tenant: tuple[uuid.UUID, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, agent_id = tenant
    call_id = await _intent_row(tenant_id, agent_id, minutes_old=40)
    vendor_id = f"out_{uuid.uuid4()}"
    engine = _Finder(answer=vendor_id)

    _, queued = await _sweep(monkeypatch, engine, tenant_id)

    assert queued == [
        (
            pipeline.INGEST_JOB,
            {"engine": "fake", "execution_id": vendor_id, "source": "reconciliation"},
            pipeline.job_id_for(pipeline.INGEST_JOB, "fake", vendor_id, "reconcile"),
        )
    ]
    assert (await _row(tenant_id, call_id))[1:] == ("queued", None)

    # Set aside while the ingest adopts it: the next sweep does not ask again.
    await _sweep(monkeypatch, engine, tenant_id)
    assert len(engine.asked) == 1


async def test_an_unreadable_answer_leaves_the_dial_queued_and_alerts(
    tenant: tuple[uuid.UUID, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, agent_id = tenant
    call_id = await _intent_row(tenant_id, agent_id, minutes_old=15)
    alerts: list[str] = []
    monkeypatch.setattr(pipeline, "alert", lambda _kind, name, **_kw: alerts.append(name))

    result, _ = await _sweep(monkeypatch, _Finder(answer=RuntimeError("down")), tenant_id)

    assert (await _row(tenant_id, call_id))[1:] == ("queued", None)
    assert "unreached=1" in result
    assert "outstanding_probe_incomplete" in alerts


async def test_a_dial_whose_campaign_contact_is_still_dialing_is_left_to_the_reaper(
    tenant: tuple[uuid.UUID, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Closed `failed` first, the contact would reach the retry ladder and be rung again."""
    tenant_id, agent_id = tenant
    call_id = await _intent_row(tenant_id, agent_id, minutes_old=15)
    campaign_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, status, classification, "
                "created_at, updated_at) VALUES (:c, :t, :a, 'Recall', 'running', 'service', "
                "now(), now())"
            ),
            {"c": campaign_id, "t": tenant_id, "a": agent_id},
        )
        await session.execute(
            text(
                "INSERT INTO campaign_contacts (id, tenant_id, campaign_id, phone_e164, status, "
                "attempts, last_call_id, created_at, updated_at) VALUES (:i, :t, :c, "
                "'+919800000001', 'dialing', 1, :call, now(), now())"
            ),
            {"i": uuid7(), "t": tenant_id, "c": campaign_id, "call": call_id},
        )
    engine = _Finder(answer=None)

    await _sweep(monkeypatch, engine, tenant_id)

    assert engine.asked == []
    assert (await _row(tenant_id, call_id))[1:] == ("queued", None)


async def test_the_sweep_stops_at_its_budget(
    tenant: tuple[uuid.UUID, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, agent_id = tenant
    first = await _intent_row(tenant_id, agent_id, minutes_old=20)
    second = await _intent_row(tenant_id, agent_id, minutes_old=15)
    monkeypatch.setattr(pipeline, "OUTSTANDING_PROBE_BUDGET", 1)
    alerts: list[str] = []
    monkeypatch.setattr(pipeline, "alert", lambda _kind, name, **_kw: alerts.append(name))

    await _sweep(monkeypatch, _Finder(answer=None), tenant_id)

    assert (await _row(tenant_id, first))[1] == "failed"
    assert (await _row(tenant_id, second))[1] == "queued"
    assert "outstanding_probe_budget_exhausted" in alerts


async def test_an_engine_that_cannot_search_leaves_placeholder_rows_alone(
    tenant: tuple[uuid.UUID, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, agent_id = tenant
    call_id = await _intent_row(tenant_id, agent_id, minutes_old=15)
    assert not isinstance(FakeEngine(), FindsPlacedCalls)

    await _sweep(monkeypatch, FakeEngine(), tenant_id)

    assert (await _row(tenant_id, call_id))[1:] == ("queued", None)


async def test_one_accounts_sweep_never_closes_another_accounts_dial(
    tenant: tuple[uuid.UUID, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, agent_id = tenant
    other_id, other_agent = await _routed_tenant()
    try:
        ours = await _intent_row(tenant_id, agent_id, minutes_old=15)
        theirs = await _intent_row(other_id, other_agent, minutes_old=15)
        engine = _Finder(answer=None)

        await _sweep(monkeypatch, engine, tenant_id)

        assert [asked for asked, _ in engine.asked] == [str(ours)]
        assert (await _row(other_id, theirs))[1] == "queued"
        # The close itself, run in the wrong account's session, reaches nothing.
        async with tenant_session(tenant_id) as session:
            closed = await session.execute(
                text(pipeline._CLOSE_LOST_DIAL_SQL),
                {"id": theirs, "local": unconfirmed_engine_call_id(theirs)},
            )
        assert closed.rowcount == 0  # type: ignore[attr-defined]
        assert (await _row(other_id, theirs))[1] == "queued"
    finally:
        async with tenant_session(other_id) as session:
            await session.execute(
                text("UPDATE calls SET status = 'completed' WHERE status = 'queued'")
            )


async def test_the_engine_is_asked_in_the_clients_workspace_and_ours(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _workspace(_tenant: uuid.UUID) -> str:
        return "org_client1"

    monkeypatch.setattr(pipeline, "workspace_for_tenant", _workspace)
    engine = _Finder(answer=None)
    call_id = uuid7()

    assert await pipeline._placed_call_handle(engine, uuid7(), call_id) is None
    assert engine.asked == [(str(call_id), "org_client1"), (str(call_id), None)]

    engine.answer = "out_9@org_client1"
    engine.asked.clear()
    assert await pipeline._placed_call_handle(engine, uuid7(), call_id) == "out_9@org_client1"
    assert engine.asked == [(str(call_id), "org_client1")]


# --- the adapter's search by reference ---------------------------------------------------


def _engine(answer: httpx.Response, seen: list[httpx.Request]) -> ThinnestEngine:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return answer

    return ThinnestEngine(
        api_key="ta_live_test",
        client=httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"Authorization": "Bearer ta_live_test"},
            transport=httpx.MockTransport(handler),
        ),
    )


async def test_the_adapter_searches_calls_by_our_reference() -> None:
    seen: list[httpx.Request] = []
    ours = str(uuid.uuid4())
    engine = _engine(
        httpx.Response(200, json={"items": [{"id": "out_1", "reference": ours}]}), seen
    )
    assert isinstance(engine, FindsPlacedCalls)

    with in_workspace("org_client1"):
        assert await engine.find_placed_call(ours) == "out_1@org_client1"

    assert seen[0].method == "GET"
    assert seen[0].url.path.endswith("/calls")
    assert seen[0].url.params["reference"] == ours
    assert seen[0].headers["Thinnest-Workspace"] == "org_client1"


async def test_the_adapter_reports_no_call_only_on_an_empty_page() -> None:
    engine = _engine(httpx.Response(200, json={"items": [], "nextCursor": None}), [])
    assert await engine.find_placed_call(str(uuid.uuid4())) is None


@pytest.mark.parametrize(
    "answer",
    [
        {"nextCursor": None},
        {"items": [{"id": "out_1", "reference": "LSQ-42"}]},
        {"items": [{"reference": "REF"}]},
        {"items": ["out_1"]},
    ],
)
async def test_an_answer_the_adapter_cannot_vouch_for_is_refused(answer: dict[str, Any]) -> None:
    engine = _engine(httpx.Response(200, json=answer), [])
    with pytest.raises(ProblemError) as raised:
        await engine.find_placed_call("REF")
    assert raised.value.code == "engine_bad_response"
