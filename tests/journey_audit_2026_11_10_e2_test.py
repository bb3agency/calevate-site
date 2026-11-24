"""Journey audit E2 (10 Nov 2026): an inbound caller, from the number to the owner's alerts.

Each test failed on the code before its fix.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.team_alerts import service as team_alerts
from apps.workers import extraction_reread, handoff, pipeline
from apps.workers import team_alerts as team_worker
from calevate_shared.engine import HandoffLeg
from calevate_shared.extraction import ExtractionOutput
from sqlalchemy import text
from tests.extraction_reread_test import _failed_call, _payload
from tests.handoff_settlement_test import _fixture as _handoff_fixture
from tests.handoff_settlement_test import _snapshot as _handoff_snapshot
from tests.lead_columns_test import _tenant
from tests.pipeline_audit_test import _completed_call, _run_pipeline, _stub_storage
from tests.team_alerts_test import _call, _mail, _verified_contact

# The recording copy is an environment concern; the stub is `pipeline_audit_test`'s.
_stub_storage = _stub_storage

#: The business's own number, which the network showed in place of the caller's (D-746).
_BUSINESS = "+919900011122"
#: The call-back number the caller gave on the call.
_GIVEN = "+919876543210"


async def _publish(tenant_id: UUID, e164: str = _BUSINESS) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO forwarded_lines (id, tenant_id, e164, line_kind, carrier, mode, "
                "ring_seconds, attested_at) VALUES (:i, :t, :e, 'mobile', 'airtel', "
                "'conditional', 20, now())"
            ),
            {"i": uuid7(), "t": tenant_id, "e": e164},
        )


async def _callbacks(tenant_id: UUID, call_id: UUID) -> list[str]:
    async with tenant_session(tenant_id) as session:
        rows = await session.execute(
            text("SELECT phone_e164 FROM scheduled_callbacks WHERE source_call_id = :c"),
            {"c": call_id},
        )
        return [str(r[0]) for r in rows.all()]


# --- E2-01: a "call me later" heard only by the re-read of a failed reading ---------------


async def test_a_reread_that_hears_call_me_later_books_the_call_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, call_id = await _failed_call("e2cb", monkeypatch)
    assert await _callbacks(tenant_id, call_id) == [], "the failed reading heard nothing"

    async def _asks_to_be_called(*_args: Any, **_kw: Any) -> ExtractionOutput:
        return ExtractionOutput(
            data={"name": "Ravi"},
            summary="The caller asked to be called back tomorrow.",
            sentiment="neutral",
            outcome_tag="needs_you",
            callback_requested=True,
            next_step_by="business",
        )

    monkeypatch.setattr(pipeline, "extract_call", _asks_to_be_called)
    assert (
        await extraction_reread.reread_call_extraction({}, _payload(tenant_id, call_id)) == "reread"
    )

    assert len(await _callbacks(tenant_id, call_id)) == 1, "the caller who asked is rung back"
    async with tenant_session(tenant_id) as session:
        outcome = (
            await session.execute(
                text("SELECT outcome_tag FROM calls WHERE id = :c"), {"c": call_id}
            )
        ).scalar()
    assert outcome == "call_back_booked"


# --- E2-02: the team alert of a forwarded call that hid the caller -----------------------


async def _in_call_alert_body(
    monkeypatch: pytest.MonkeyPatch, *, hidden_marked: bool, lead_phone: str | None
) -> str:
    mail = _mail(monkeypatch)
    t = await _tenant()
    await _publish(t.tenant_id)
    await _verified_contact(t)
    call_id = await _call(t)
    async with tenant_session(t.tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET from_e164 = :b, caller_id_hidden = :h WHERE id = :c"),
            {"b": _BUSINESS, "h": hidden_marked, "c": call_id},
        )
        if lead_phone is not None:
            lead_id = uuid7()
            await session.execute(
                text(
                    "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, source, status, "
                    "data, created_at, updated_at) VALUES (:id, :tid, :aid, :p, "
                    "'inbound_call', 'new', '{}'::jsonb, now(), now())"
                ),
                {"id": lead_id, "tid": t.tenant_id, "aid": t.agent_id, "p": lead_phone},
            )
            await session.execute(
                text("UPDATE calls SET lead_id = :l WHERE id = :c"), {"l": lead_id, "c": call_id}
            )
        await team_alerts.save_in_call(
            session, tenant_id=t.tenant_id, agent_id=t.agent_id, in_call=True
        )
    told = await team_alerts.queue_in_call(
        tenant_id=t.tenant_id, agent_id=t.agent_id, call_id=call_id, problem="Wants a person."
    )
    assert told == "queued"
    async with tenant_session(t.tenant_id) as session:
        payload = (
            await session.execute(
                text(
                    "SELECT payload FROM outbox_messages WHERE job = :job "
                    "AND payload->>'tenant_id' = :tid"
                ),
                {"job": team_alerts.ALERT_JOB, "tid": str(t.tenant_id)},
            )
        ).scalar_one()
    assert await team_worker.deliver_team_alert({"job_try": 1}, dict(payload)) == "sent"
    return mail.sent[0][1]


async def test_a_hidden_caller_is_not_shown_to_the_team_as_the_business_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # While the call is live the pipeline has not marked it yet.
    body = await _in_call_alert_body(monkeypatch, hidden_marked=False, lead_phone=None)
    assert _BUSINESS not in body, "the team would ring the business itself"
    assert f"Phone: {team_worker.HIDDEN_CALLER_PHONE}" in body


async def test_a_hidden_caller_who_gave_a_number_is_shown_by_that_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = await _in_call_alert_body(monkeypatch, hidden_marked=True, lead_phone=_GIVEN)
    assert f"Phone: {_GIVEN}" in body
    assert _BUSINESS not in body


# --- E2-03: a hand-over nobody took, on a forwarded call that hid the caller -------------


async def test_a_handover_nobody_took_never_books_a_call_back_to_the_business() -> None:
    tenant_id, _agent_id, call_id, execution_id = await _handoff_fixture()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET from_e164 = :b, caller_id_hidden = true WHERE id = :c"),
            {"b": _BUSINESS, "c": call_id},
        )
    leg = HandoffLeg(outcome="unreached", raw_status="no-answer")
    snapshot = _handoff_snapshot(execution_id, leg).model_copy(update={"from_e164": _BUSINESS})
    async with tenant_session(tenant_id) as session:
        assert (
            await handoff.settle_handoff(
                session, tenant_id=tenant_id, call_id=call_id, snapshot=snapshot
            )
            == "unreached"
        )
    assert await _callbacks(tenant_id, call_id) == []


async def test_the_pipeline_knows_the_caller_is_hidden_before_the_handover_settles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, execution_id, call_id = await _completed_call("e2order", caller=_BUSINESS)
    await _publish(tenant_id)
    seen: list[bool] = []
    real = pipeline.settle_handoff

    async def _settle(session: Any, **kw: Any) -> str:
        seen.append(
            bool(
                (
                    await session.execute(
                        text("SELECT caller_id_hidden FROM calls WHERE id = :c"),
                        {"c": kw["call_id"]},
                    )
                ).scalar()
            )
        )
        return await real(session, **kw)

    monkeypatch.setattr(pipeline, "settle_handoff", _settle)
    await _run_pipeline(tenant_id, call_id, execution_id)
    assert seen and seen[0] is True, "the hand-over's call back read the call before STEP 1e"
