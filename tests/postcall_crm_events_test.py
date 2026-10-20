"""What a finished call tells the owner and the client's CRM (D-841).

* A call whose business outcome moves its lead to Hot alerts the owner once per lead per
  call, and the move is recorded on the lead's timeline (`status_change`) like any other.
* A lead a call creates is a `lead.created`; a status a call moves is a `lead.updated`.
* `call.completed` carries the business outcome and its label.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import pytest
from apps.api.db.session import tenant_session
from apps.workers import pipeline
from calevate_shared.extraction import ExtractionOutput
from sqlalchemy import text
from tests.pipeline_audit_test import _completed_call, _outbox_rows, _run_pipeline, _stub_storage

# The recording copy is an environment concern; the stub is `pipeline_audit_test`'s.
_stub_storage = _stub_storage

READY = {
    "key": "ready_to_buy",
    "label": "Ready to buy",
    "meaning": "The caller wants to order now.",
    "lead_status": "hot",
}
BROWSING = {
    "key": "browsing",
    "label": "Just looking",
    "meaning": "The caller asked about prices only.",
    "lead_status": "contacted",
}


async def give_agent_outcomes(tenant_id: UUID, outcomes: list[dict[str, str]]) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agents SET business_outcomes = CAST(:o AS jsonb), "
                "business_outcomes_draft = 'done' WHERE tenant_id = :t"
            ),
            {"o": json.dumps(outcomes), "t": tenant_id},
        )


def reads_as(monkeypatch: pytest.MonkeyPatch, key: str | None) -> None:
    """Every extraction this test runs answers with the business outcome `key`."""

    async def _extraction(*_args: Any, **_kw: Any) -> ExtractionOutput:
        return ExtractionOutput(
            data={"name": "Ravi"},
            summary="The caller asked for two kilos of chilli.",
            sentiment="neutral",
            outcome_tag="answered",
            business_outcome=key,
        )

    monkeypatch.setattr(pipeline, "extract_call", _extraction)


async def subscribe(tenant_id: UUID, events: list[str]) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO outbound_webhooks (id, tenant_id, kind, url, events, active, "
                "created_at, updated_at) VALUES (gen_random_uuid(), :tid, 'webhook', "
                "'https://crm.example.invalid/hook', CAST(:events AS text[]), true, now(), now())"
            ),
            {"tid": tenant_id, "events": events},
        )


async def _lead_of(tenant_id: UUID, call_id: UUID) -> tuple[UUID, str]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT l.id, l.status FROM calls c JOIN leads l ON l.id = c.lead_id "
                    "WHERE c.id = :c"
                ),
                {"c": call_id},
            )
        ).one()
    return UUID(str(row[0])), str(row[1])


async def _status_events(tenant_id: UUID, lead_id: UUID) -> list[str]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT payload->>'status' FROM lead_events WHERE lead_id = :l "
                    "AND type = 'status_change' ORDER BY created_at"
                ),
                {"l": lead_id},
            )
        ).all()
    return [str(r[0]) for r in rows]


async def _events(event: str, matcher: dict[str, Any]) -> list[dict[str, Any]]:
    rows = await _outbox_rows("deliver_outbound_webhook", {"event": event, "data": matcher})
    return [r["data"] for r in rows]


async def test_a_hot_business_outcome_alerts_the_owner_once_and_records_the_move(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, execution_id, call_id = await _completed_call("hotroute")
    await give_agent_outcomes(tenant_id, [READY, BROWSING])
    reads_as(monkeypatch, "ready_to_buy")

    await _run_pipeline(tenant_id, call_id, execution_id)
    await _run_pipeline(tenant_id, call_id, execution_id)

    alerts = await _outbox_rows("notify_hot_lead", {"call_id": str(call_id)})
    assert len(alerts) == 1, "one alert per lead per call, however often the call is re-run"
    assert alerts[0]["triggers"] == ["Ready to buy"], "the alert names the outcome's label"
    lead_id, status = await _lead_of(tenant_id, call_id)
    assert status == "hot"
    assert await _status_events(tenant_id, lead_id) == ["hot"], "the move is on the timeline"


async def test_a_business_outcome_that_is_not_hot_sends_no_alert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, execution_id, call_id = await _completed_call("nothot")
    await give_agent_outcomes(tenant_id, [READY, BROWSING])
    reads_as(monkeypatch, "browsing")

    await _run_pipeline(tenant_id, call_id, execution_id)

    assert await _outbox_rows("notify_hot_lead", {"call_id": str(call_id)}) == []
    _lead_id, status = await _lead_of(tenant_id, call_id)
    assert status == "contacted"


async def test_a_lead_a_call_creates_is_one_lead_created_and_its_moves_are_lead_updated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caller = "+919812300441"
    tenant_id, execution_id, call_id = await _completed_call("leadev", caller=caller)
    await give_agent_outcomes(tenant_id, [READY, BROWSING])
    await subscribe(tenant_id, ["lead.created", "lead.updated", "call.completed"])
    reads_as(monkeypatch, "browsing")

    await _run_pipeline(tenant_id, call_id, execution_id)
    await _run_pipeline(tenant_id, call_id, execution_id)

    lead_id, _status = await _lead_of(tenant_id, call_id)
    created = await _events("lead.created", {"lead_id": str(lead_id)})
    assert [c["status"] for c in created] == ["contacted"], (
        "one lead.created, carrying the status the call moved it to, and no lead.updated "
        "for the move that happened in the same transaction"
    )
    assert await _events("lead.updated", {"lead_id": str(lead_id)}) == []

    # A second call from the same number moves the same lead up: an update, not a creation.
    _t, second_execution, second_call = await _completed_call_for(tenant_id, caller)
    reads_as(monkeypatch, "ready_to_buy")
    await _run_pipeline(tenant_id, second_call, second_execution)

    assert len(await _events("lead.created", {"lead_id": str(lead_id)})) == 1
    updated = await _events("lead.updated", {"lead_id": str(lead_id)})
    assert [u["status"] for u in updated] == ["hot"]


async def test_call_completed_carries_the_business_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, execution_id, call_id = await _completed_call("cceo")
    await give_agent_outcomes(tenant_id, [READY, BROWSING])
    await subscribe(tenant_id, ["call.completed"])
    reads_as(monkeypatch, "ready_to_buy")

    await _run_pipeline(tenant_id, call_id, execution_id)

    [body] = await _events("call.completed", {"call_id": str(call_id)})
    assert body["business_outcome"] == "ready_to_buy"
    assert body["business_outcome_label"] == "Ready to buy"


async def _completed_call_for(tenant_id: UUID, caller: str) -> tuple[UUID, str, UUID]:
    """A second completed inbound call from `caller` to the same tenant's agent."""
    import uuid

    from apps.api.engine import get_engine
    from apps.workers.pipeline import ingest_engine_event

    async with tenant_session(tenant_id) as session:
        agent_ref = (
            await session.execute(
                text("SELECT engine_agent_ref FROM agents WHERE tenant_id = :t LIMIT 1"),
                {"t": tenant_id},
            )
        ).scalar()
    execution_id = f"exec_{uuid.uuid4().hex[:12]}"
    get_engine().seed_inbound_call(  # type: ignore[attr-defined]
        call_id=execution_id,
        agent_ref=str(agent_ref),
        from_e164=caller,
        to_e164="+911140000000",
    )
    await ingest_engine_event(
        {}, {"engine": "fake", "execution_id": execution_id, "engine_agent_ref": agent_ref}
    )
    async with tenant_session(tenant_id) as session:
        call_id = (
            await session.execute(
                text("SELECT id FROM calls WHERE engine_call_id = :e"), {"e": execution_id}
            )
        ).scalar()
    return tenant_id, execution_id, UUID(str(call_id))
