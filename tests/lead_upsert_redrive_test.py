"""Re-running the pipeline for a caller's OLDER call must not count it twice or rewind the lead.

The post-call pipeline is re-runnable by design (TRD §8): a webhook arriving after the
poller resolved the call, an ARQ retry, a `_pipeline_settled` re-drive for a missing
artefact. `_upsert_lead` keyed "is this a new call" on `leads.last_call_id`, which only
recognises a re-run of the caller's MOST RECENT call. A re-drive of an earlier call, after a
later call from the same number had already been filed, counted as a third call, flipped
`last_call_id` back to the older call and merged the older answers over the newer ones.

Scope discipline: every test builds its own tenant and asserts only on rows it created.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.db.session import tenant_session
from apps.workers import pipeline
from calevate_shared.engine import ExecutionSnapshot
from sqlalchemy import text
from tests.smoke_pipeline_test import _seed_tenant

pytestmark = [pytest.mark.rls]


def _snapshot(execution: str, *, caller: str, started_at: datetime) -> ExecutionSnapshot:
    return ExecutionSnapshot(
        engine_call_id=execution,
        direction="inbound",
        status="completed",
        raw_status="completed",
        terminal=True,
        billable_ready=True,
        from_e164=caller,
        to_e164="+911140000000",
        started_at=started_at,
        engine="fake",
    )


async def _call(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, *, caller: str, started_at: datetime
) -> tuple[uuid.UUID, ExecutionSnapshot]:
    snapshot = _snapshot(f"redrive_{uuid.uuid4().hex[:10]}", caller=caller, started_at=started_at)
    call_id = await pipeline._upsert_call(tenant_id, agent_id, snapshot, None)
    return call_id, snapshot


async def _file(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    call_id: uuid.UUID,
    snapshot: ExecutionSnapshot,
    data: dict[str, str],
) -> uuid.UUID | None:
    return await pipeline._upsert_lead(
        tenant_id,
        agent_id,
        call_id,
        snapshot,
        direction="inbound",
        data=data,
        schema_version=1,
    )


async def _lead(tenant_id: uuid.UUID, lead_id: uuid.UUID) -> tuple[object, ...]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT call_count, is_repeat_caller, first_call_id, last_call_id, data "
                    "FROM leads WHERE id = :lid"
                ),
                {"lid": lead_id},
            )
        ).one()
    return tuple(row)


async def test_a_redrive_of_an_older_call_neither_counts_it_again_nor_rewinds_the_lead() -> None:
    tenant_id, agent_id = await _seed_tenant(f"redrive_{uuid.uuid4().hex[:10]}")
    caller = f"+9198{uuid.uuid4().int % 100000000:08d}"
    now = datetime.now(UTC)
    first_id, first = await _call(
        tenant_id, agent_id, caller=caller, started_at=now - timedelta(days=1)
    )
    second_id, second = await _call(tenant_id, agent_id, caller=caller, started_at=now)

    lead_id = await _file(tenant_id, agent_id, first_id, first, {"budget": "old"})
    assert lead_id is not None
    assert await _file(tenant_id, agent_id, second_id, second, {"budget": "new"}) == lead_id
    # The re-drive of the OLDER call.
    assert await _file(tenant_id, agent_id, first_id, first, {"budget": "old"}) == lead_id

    count, repeat, first_call, last_call, data = await _lead(tenant_id, lead_id)
    assert count == 2, "a re-run of an earlier call was counted as a third call"
    assert repeat is True
    assert first_call == first_id
    assert last_call == second_id, "a re-run of an earlier call rewound last_call_id"
    assert data == {"budget": "new"}, "an older call's answer overwrote a newer one"


async def test_calls_filed_out_of_order_still_name_the_true_first_and_last() -> None:
    """The later call's pipeline can finish first (the earlier one stalled on a vendor
    fetch), so the order the rows arrive in is not the order the calls happened in."""
    tenant_id, agent_id = await _seed_tenant(f"ooo_{uuid.uuid4().hex[:10]}")
    caller = f"+9198{uuid.uuid4().int % 100000000:08d}"
    now = datetime.now(UTC)
    early_id, early = await _call(
        tenant_id, agent_id, caller=caller, started_at=now - timedelta(hours=3)
    )
    late_id, late = await _call(tenant_id, agent_id, caller=caller, started_at=now)

    lead_id = await _file(tenant_id, agent_id, late_id, late, {"budget": "new"})
    assert lead_id is not None
    assert await _file(tenant_id, agent_id, early_id, early, {"budget": "old", "area": "x"}) == (
        lead_id
    )

    count, repeat, first_call, last_call, data = await _lead(tenant_id, lead_id)
    assert (count, repeat) == (2, True)
    assert first_call == early_id
    assert last_call == late_id
    # The older call still contributes the fields the newer one did not answer.
    assert data == {"budget": "new", "area": "x"}


async def test_a_redrive_of_the_latest_call_is_still_not_a_second_call() -> None:
    tenant_id, agent_id = await _seed_tenant(f"same_{uuid.uuid4().hex[:10]}")
    caller = f"+9198{uuid.uuid4().int % 100000000:08d}"
    now = datetime.now(UTC)
    call_id, snapshot = await _call(tenant_id, agent_id, caller=caller, started_at=now)

    lead_id = await _file(tenant_id, agent_id, call_id, snapshot, {"budget": "a"})
    assert lead_id is not None
    await _file(tenant_id, agent_id, call_id, snapshot, {"budget": "b"})

    count, repeat, first_call, last_call, data = await _lead(tenant_id, lead_id)
    assert (count, repeat, first_call, last_call) == (1, False, call_id, call_id)
    # The re-run's extraction is the call's own latest answer, so it still applies.
    assert data == {"budget": "b"}
