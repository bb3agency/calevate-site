"""The ingest read takes a signed delivery alone only while the call is live or when it is the
call's final record.

A `call.completed` body states the call's `outcome` but carries no `analysedAt` (ThinnestAI's
email of 21 Oct 2026, §23 item 5), so the engine's fetch is asked, which may already hold the
analysed call. A delivery stating no status at all reads as `failed`, which is terminal: kept,
it would stop the later `call.analysed` from recording `no_answer`, `busy` or `voicemail`, so
the fetch is asked for it too. The delivery stands only when the fetch cannot answer.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from apps.api.core.errors import ProblemError
from apps.api.engine.thinnest import ThinnestEngine
from apps.api.reliability.engine_intake_keys import seal_delivery
from apps.workers import engine_delivery
from calevate_shared.engine import ExecutionSnapshot

ENGINE = "thinnest"
CALL = "out_unstated_1"


class _Engine(ThinnestEngine):
    """The real delivery reader with a fetch the test answers."""

    def __init__(self, fetched: ExecutionSnapshot | ProblemError) -> None:
        super().__init__(api_key="ta_x")
        self._fetched = fetched
        self.fetches = 0

    async def get_execution(self, call_id: str) -> ExecutionSnapshot:
        self.fetches += 1
        if isinstance(self._fetched, ProblemError):
            raise self._fetched
        return self._fetched


def _delivery(data: dict[str, Any], event: str = "call.completed") -> dict[str, Any]:
    body = json.dumps({"event": event, "data": data})
    return seal_delivery(body, engine=ENGINE, execution_id=CALL, event_name=f"{event}:1")


def _fetched(status: str) -> ExecutionSnapshot:
    return ThinnestEngine(api_key="ta_x").snapshot_from_delivery(
        {"data": {"id": CALL, "status": status, "hangup": "busy"}}
    )


@pytest.mark.parametrize(
    "data",
    [{"callRef": CALL, "outcome": "missed", "hangup": "no_answer"}, {"callRef": CALL}],
    ids=["call.completed", "no status"],
)
async def test_a_delivery_that_is_not_the_final_record_asks_the_fetch(data: dict[str, Any]) -> None:
    engine = _Engine(_fetched("missed"))
    snapshot = await engine_delivery.execution_truth(engine, CALL, _delivery(data))
    assert engine.fetches == 1
    assert snapshot.status == "busy" and snapshot.raw_status == "missed"


async def test_a_final_or_live_delivery_is_read_without_a_fetch() -> None:
    engine = _Engine(_fetched("missed"))
    analysed = {"id": CALL, "status": "completed", "analysedAt": "2026-10-21T05:00:00Z"}
    snapshot = await engine_delivery.execution_truth(
        engine, CALL, _delivery(analysed, event="call.analysed")
    )
    assert snapshot.status == "completed"
    live = await engine_delivery.execution_truth(
        engine, CALL, _delivery({"id": CALL, "status": "ringing"}, event="call.analysed")
    )
    assert live.status == "ringing"
    assert engine.fetches == 0


async def test_when_the_fetch_cannot_answer_the_delivery_stands_with_its_outcome() -> None:
    engine = _Engine(ProblemError.not_found("Call"))
    snapshot = await engine_delivery.execution_truth(
        engine, CALL, _delivery({"callRef": CALL, "outcome": "missed", "hangup": "voicemail"})
    )
    assert engine.fetches == 1
    assert (snapshot.status, snapshot.raw_status) == ("voicemail", "missed")
    unstated = await engine_delivery.execution_truth(engine, CALL, _delivery({"callRef": CALL}))
    assert unstated.raw_status == engine_delivery.UNSTATED_STATUS
