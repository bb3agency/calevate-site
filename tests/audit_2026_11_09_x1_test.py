"""Backend audit round 4, lane X1 (9 Nov 2026): money and metering.

- X1-01: a dial the lost-dial sweep closed `failed` / `dial_lost` and the engine then turned
  out to hold is reopened when its record adopts the row, so a call that rang (and, if it
  connected, was charged) never reads "nobody was rung".
- X1-02: a trial's daily test-call cap counts only dials that were placed, as the paid
  test-call cap already did.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.agents.service import unconfirmed_engine_call_id
from apps.api.billing.trials import trial_calls_since
from apps.api.compliance.trial_access import ist_day_start
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.workers import pipeline
from calevate_shared.engine import ExecutionSnapshot
from sqlalchemy import text
from tests.thinnest_call_lifecycle_test import _routed_tenant

# --- X1-01 ----------------------------------------------------------------------------


def _snapshot(engine_call_id: str, *, status: str, reference: uuid.UUID) -> ExecutionSnapshot:
    now = datetime.now(UTC)
    seconds = 61 if status == "completed" else 0
    return ExecutionSnapshot(
        engine_call_id=engine_call_id,
        direction="outbound",
        status=status,  # type: ignore[arg-type]
        raw_status=status,
        terminal=True,
        billable_ready=True,
        started_at=now - timedelta(seconds=seconds),
        ended_at=now,
        duration_s=seconds,
        raw_document=json.dumps({"id": engine_call_id, "reference": str(reference)}).encode(),
    )


async def _lost_dial(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> uuid.UUID:
    """An intent row exactly as `_CLOSE_LOST_DIAL_SQL` leaves it."""
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
                "status, created_at, updated_at) VALUES (:id, :t, :a, :e, 'outbound', "
                "'+919800000001', 'queued', now() - interval '15 minutes', now())"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": unconfirmed_engine_call_id(call_id),
            },
        )
        closed = await session.execute(
            text(pipeline._CLOSE_LOST_DIAL_SQL),
            {"id": call_id, "local": unconfirmed_engine_call_id(call_id)},
        )
        assert closed.rowcount == 1  # type: ignore[attr-defined]
    return call_id


async def _state(tenant_id: uuid.UUID, call_id: uuid.UUID) -> tuple[str, str, str | None]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT engine_call_id, status, not_placed_reason FROM calls WHERE id = :i"),
                {"i": call_id},
            )
        ).one()
    return str(row[0]), str(row[1]), row[2]


@pytest.mark.parametrize("status", ["completed", "no_answer"])
async def test_a_lost_dial_the_engine_later_shows_was_placed_reads_as_the_call_it_was(
    status: str,
) -> None:
    tenant_id, agent_id = await _routed_tenant()
    call_id = await _lost_dial(tenant_id, agent_id)
    vendor_id = f"out_{uuid.uuid4()}"

    resolved = await pipeline._upsert_call(
        tenant_id,
        agent_id,
        _snapshot(vendor_id, status=status, reference=call_id),
        None,
        placed_as=call_id,
    )

    assert resolved == call_id
    assert await _state(tenant_id, call_id) == (vendor_id, status, None), (
        "a call the engine placed under our reference is not 'nobody was rung'"
    )


# --- X1-02 ----------------------------------------------------------------------------


async def test_a_trial_dial_that_rang_nobody_does_not_use_up_a_daily_test_call() -> None:
    tenant_id, agent_id = await _routed_tenant()
    async with tenant_session(tenant_id) as session:
        for not_placed in (None, "lines_full", "dial_lost", "unstated"):
            await session.execute(
                text(
                    "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                    "to_e164, status, trial_call, not_placed_reason, created_at, updated_at) "
                    "VALUES (:id, :t, :a, :e, 'outbound', '+919800000001', :status, true, "
                    ":np, now(), now())"
                ),
                {
                    "id": uuid7(),
                    "t": tenant_id,
                    "a": agent_id,
                    "e": f"out_{uuid.uuid4()}",
                    "status": "completed" if not_placed is None else "failed",
                    "np": not_placed,
                },
            )
        counted = await trial_calls_since(
            session, tenant_id=tenant_id, since=ist_day_start(datetime.now(UTC))
        )

    assert counted == 1, "only the call that was placed counts against today's test calls"
