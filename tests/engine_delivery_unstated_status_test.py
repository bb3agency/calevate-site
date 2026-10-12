"""A signed delivery that states no status is not taken as the call's outcome.

The adapter reads an absent status as `failed`, which is terminal: kept, it would stop the
later `call.analysed` from recording `no_answer`, `busy` or `voicemail`. So the ingest read
asks the engine's fetch instead, and keeps the delivery only when the fetch cannot answer.
"""

from __future__ import annotations

import json
from typing import Any

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


async def test_a_delivery_without_a_status_asks_the_fetch() -> None:
    engine = _Engine(_fetched("missed"))
    snapshot = await engine_delivery.execution_truth(
        engine, CALL, _delivery({"id": CALL, "outcome": "missed"})
    )
    assert engine.fetches == 1
    assert snapshot.status == "busy" and snapshot.raw_status == "missed"


async def test_a_delivery_with_a_status_is_read_without_a_fetch() -> None:
    engine = _Engine(_fetched("missed"))
    snapshot = await engine_delivery.execution_truth(
        engine, CALL, _delivery({"id": CALL, "status": "completed"}, event="call.analysed")
    )
    assert engine.fetches == 0
    assert snapshot.status == "completed"


async def test_when_the_fetch_cannot_answer_the_delivery_stands() -> None:
    engine = _Engine(ProblemError.not_found("Call"))
    snapshot = await engine_delivery.execution_truth(
        engine, CALL, _delivery({"id": CALL, "outcome": "missed"})
    )
    assert engine.fetches == 1
    assert snapshot.raw_status == engine_delivery.UNSTATED_STATUS
