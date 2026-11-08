"""Backend audit round 3, lane V2 (9 Nov 2026): the engine adapter's failure handling and
the call-end path.

- V2-01: a list page with no `items` is refused, never read as an empty, complete listing.
- V2-02: a dial whose answer was lost is adopted by the `reference` the engine echoes,
  instead of the call getting a second row and the intent row staying `queued`.
- V2-03: an engine 5xx is retried on the ingest and post-call ladders; a 4xx is not.
- V2-04: the outstanding-call probe never asks the engine about our placeholder ids.
- V2-05: a recall whose status read failed never hangs up a call that may be connected.

Vendor shapes: `thinnest-findings/mirror/snapshots/2026-10-28/pages/api-reference/`.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from apps.api.agents.service import UNCONFIRMED_ENGINE_CALL_PREFIX, unconfirmed_engine_call_id
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine.fake import FakeEngine
from apps.api.engine.thinnest import BASE_URL, ThinnestEngine
from apps.api.engine.vendor_http import EngineRejectedError
from apps.workers import pipeline
from apps.workers.engine_delivery import placed_call_id
from calevate_shared.engine import ExecutionSnapshot, RecallOutcome
from calevate_shared.events import TERMINAL_STATUSES
from sqlalchemy import text
from tests.thinnest_call_lifecycle_test import _routed_tenant


def _engine(answer: dict[str, Any]) -> ThinnestEngine:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=answer)

    return ThinnestEngine(
        api_key="ta_live_test",
        client=httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"Authorization": "Bearer ta_live_test"},
            transport=httpx.MockTransport(handler),
        ),
    )


# --- V2-01 --------------------------------------------------------------------


@pytest.mark.parametrize("answer", [{"nextCursor": None}, {"items": None, "nextCursor": None}])
async def test_a_call_list_page_without_items_is_refused_not_read_as_no_calls(
    answer: dict[str, Any],
) -> None:
    with pytest.raises(ProblemError) as raised:
        await _engine(answer).list_executions(since=datetime.now(UTC) - timedelta(minutes=30))
    assert raised.value.code == "engine_bad_response"


async def test_an_empty_call_list_is_still_a_complete_listing() -> None:
    listing = await _engine({"items": [], "nextCursor": None}).list_executions(
        since=datetime.now(UTC) - timedelta(minutes=30)
    )
    assert listing.complete and listing.snapshots == []


# --- V2-03 --------------------------------------------------------------------


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_an_engine_failing_is_retried(status: int) -> None:
    assert pipeline._is_transient(EngineRejectedError(status=status)) is True


@pytest.mark.parametrize("status", [400, 403, 404, 409])
def test_an_engine_refusing_is_not_retried(status: int) -> None:
    assert pipeline._is_transient(EngineRejectedError(status=status)) is False


# --- V2-02 --------------------------------------------------------------------


def _snapshot(engine_call_id: str, *, document: dict[str, Any] | None = None) -> ExecutionSnapshot:
    now = datetime.now(UTC)
    return ExecutionSnapshot(
        engine_call_id=engine_call_id,
        direction="outbound",
        status="completed",
        raw_status="completed",
        terminal=True,
        billable_ready=True,
        started_at=now - timedelta(seconds=61),
        ended_at=now,
        duration_s=61,
        raw_document=json.dumps(document).encode() if document is not None else None,
    )


def test_the_reference_we_placed_a_call_under_is_read_from_a_fetch_and_a_delivery() -> None:
    engine = ThinnestEngine(api_key="ta_live_test")
    ours = uuid.uuid4()
    fetched = _snapshot("out_a", document={"id": "out_a", "reference": str(ours)})
    delivered = _snapshot(
        "out_a",
        document={"id": "evt_1", "event": "call.completed", "data": {"reference": str(ours)}},
    )
    assert placed_call_id(engine, fetched) == ours
    assert placed_call_id(engine, delivered) == ours
    assert placed_call_id(engine, _snapshot("out_a", document={"reference": "LSQ-42"})) is None
    assert placed_call_id(engine, _snapshot("out_a")) is None
    inbound = _snapshot("in_a", document={"reference": str(ours)}).model_copy(
        update={"direction": "inbound"}
    )
    assert placed_call_id(engine, inbound) is None
    assert placed_call_id(FakeEngine(), fetched) is None


async def _intent_row(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> uuid.UUID:
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
                "status, created_at, updated_at) VALUES (:id, :t, :a, :e, 'outbound', "
                "'+919800000001', 'queued', now(), now())"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": unconfirmed_engine_call_id(call_id),
            },
        )
    return call_id


async def _rows(tenant_id: uuid.UUID) -> dict[str, tuple[uuid.UUID, str]]:
    async with tenant_session(tenant_id) as session:
        rows = (await session.execute(text("SELECT engine_call_id, id, status FROM calls"))).all()
    return {str(r[0]): (uuid.UUID(str(r[1])), str(r[2])) for r in rows}


async def _settle(tenant_id: uuid.UUID) -> None:
    # Queued outbound rows hold platform-wide lines in other tests' counts.
    async with tenant_session(tenant_id) as session:
        await session.execute(text("UPDATE calls SET status = 'completed' WHERE status = 'queued'"))


async def test_a_dial_whose_answer_was_lost_is_adopted_by_its_reference() -> None:
    tenant_id, agent_id = await _routed_tenant()
    try:
        call_id = await _intent_row(tenant_id, agent_id)
        vendor_id = f"out_{uuid.uuid4()}"

        resolved = await pipeline._upsert_call(
            tenant_id, agent_id, _snapshot(vendor_id), None, placed_as=call_id
        )

        assert resolved == call_id
        assert await _rows(tenant_id) == {vendor_id: (call_id, "completed")}
    finally:
        await _settle(tenant_id)


async def test_a_reference_to_a_confirmed_row_never_moves_its_id() -> None:
    tenant_id, agent_id = await _routed_tenant()
    try:
        call_id = await _intent_row(tenant_id, agent_id)
        confirmed = f"out_{uuid.uuid4()}"
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE calls SET engine_call_id = :e WHERE id = :id"),
                {"e": confirmed, "id": call_id},
            )
        other = f"out_{uuid.uuid4()}"

        resolved = await pipeline._upsert_call(
            tenant_id, agent_id, _snapshot(other), None, placed_as=call_id
        )

        rows = await _rows(tenant_id)
        assert resolved != call_id
        assert rows[confirmed][0] == call_id
        assert rows[other][0] == resolved
    finally:
        await _settle(tenant_id)


async def test_another_accounts_call_id_is_never_adopted() -> None:
    owner, owner_agent = await _routed_tenant()
    stranger, stranger_agent = await _routed_tenant()
    try:
        call_id = await _intent_row(owner, owner_agent)
        vendor_id = f"out_{uuid.uuid4()}"

        await pipeline._upsert_call(
            stranger, stranger_agent, _snapshot(vendor_id), None, placed_as=call_id
        )

        assert await _rows(owner) == {
            unconfirmed_engine_call_id(call_id): (call_id, "queued"),
        }
    finally:
        await _settle(owner)
        await _settle(stranger)


# --- V2-04 --------------------------------------------------------------------


async def test_the_outstanding_probe_never_asks_about_a_placeholder_id() -> None:
    tenant_id, agent_id = await _routed_tenant()
    try:
        call_id = await _intent_row(tenant_id, agent_id)
        named = f"out_{uuid.uuid4()}"
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                    "status, created_at, updated_at) VALUES (:id, :t, :a, :e, 'outbound', "
                    "'queued', now(), now())"
                ),
                {"id": uuid7(), "t": tenant_id, "a": agent_id, "e": named},
            )
            await session.execute(
                text("UPDATE calls SET created_at = now() - interval '1 hour'"),
            )
            listed = (
                await session.execute(
                    text(pipeline._OUTSTANDING_CALLS_SQL),
                    {
                        "terminal": sorted(TERMINAL_STATUSES),
                        "after": pipeline.OUTSTANDING_PROBE_AFTER,
                        "horizon": pipeline.OUTSTANDING_PROBE_HORIZON,
                        "cap": 50,
                        "set_aside": [],
                        "unconfirmed": f"{UNCONFIRMED_ENGINE_CALL_PREFIX}%",
                    },
                )
            ).all()
        assert [str(row[0]) for row in listed] == [named]
        assert unconfirmed_engine_call_id(call_id) not in [str(row[0]) for row in listed]
    finally:
        await _settle(tenant_id)


# --- V2-05 --------------------------------------------------------------------


def _routes(responses: dict[tuple[str, str], httpx.Response]) -> tuple[ThinnestEngine, list[str]]:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.method)
        path = request.url.path.removeprefix("/api/v1")
        return responses.get((request.method, path), httpx.Response(404, json={"error": "x"}))

    engine = ThinnestEngine(
        api_key="ta_live_test",
        client=httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"Authorization": "Bearer ta_live_test"},
            transport=httpx.MockTransport(handler),
        ),
    )
    return engine, seen


@pytest.mark.parametrize("status", [500, 503])
async def test_a_recall_that_cannot_read_the_call_never_hangs_up_on_it(status: int) -> None:
    engine, seen = _routes(
        {
            ("GET", "/calls/out_1"): httpx.Response(status, json={"error": "down"}),
            ("DELETE", "/calls/out_1"): httpx.Response(202, json={"status": "connected"}),
        }
    )
    with pytest.raises(ProblemError):
        await engine.end_call("out_1")
    assert seen == ["GET"]


async def test_a_recall_of_a_call_the_platform_does_not_hold_still_asks_to_stop_it() -> None:
    engine, seen = _routes(
        {("DELETE", "/calls/out_1"): httpx.Response(200, json={"status": "cancelled"})}
    )
    assert await engine.end_call("out_1") == RecallOutcome.PREVENTED
    assert seen == ["GET", "DELETE"]
