"""`contact.opted_out` filed on the hearing client's own do-not-call list (D-691).

The delivery is the one voice-runtime sealed (`signed_intake`), shaped as
`thinnest-findings/mirror/snapshots/2026-10-08/pages/api-reference/webhooks.md:85` documents
it: `data.phone`, `data.callId`, `data.source`, `data.optedOutAt`.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
import signed_intake
from apps.api.compliance import optout
from apps.api.compliance.dnc import check_number
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.reliability.engine_intake_keys import seal_delivery
from apps.api.reliability.service import body_hash, claim_inbox_event
from apps.workers import engine_signals
from apps.workers.settings import WorkerSettings
from arq import Retry
from sqlalchemy import text
from tests.smoke_pipeline_test import _seed_tenant

ENGINE = "thinnest"
PHONE = "919876500017"
E164 = "+919876500017"


async def _route() -> tuple[uuid.UUID, uuid.UUID, str]:
    tenant_id, agent_id = await _seed_tenant(f"fakeagent_{uuid.uuid4().hex[:10]}")
    ref = f"ag_{uuid.uuid4()}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('thinnest', :ref, :tid, :aid, true, "
                "now(), now())"
            ),
            {"ref": ref, "tid": tenant_id, "aid": agent_id},
        )
    return tenant_id, agent_id, ref


async def _call(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> tuple[uuid.UUID, str]:
    call_id, engine_call_id = uuid.uuid4(), f"out_{uuid.uuid4()}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
                "status, created_at, updated_at) VALUES (:id, :tid, :aid, :ecid, 'outbound', "
                ":to, 'completed', now(), now())"
            ),
            {"id": call_id, "tid": tenant_id, "aid": agent_id, "ecid": engine_call_id, "to": E164},
        )
    return call_id, engine_call_id


def _payload(ref: str, engine_call_id: str, *, phone: str | None = PHONE) -> dict[str, Any]:
    event_id = f"evt_{uuid.uuid4().hex[:10]}"
    data: dict[str, Any] = {"callId": engine_call_id, "source": "call", "optedOutAt": "2026-10-08"}
    if phone is not None:
        data["phone"] = phone
    body = json.dumps({"id": event_id, "event": "contact.opted_out", "data": data})
    event_name = f"contact.opted_out:{event_id}"
    return {
        "engine": ENGINE,
        "execution_id": engine_call_id,
        "raw_status": "contact.opted_out",
        "engine_agent_ref": ref,
        "delivery": seal_delivery(
            body, engine=ENGINE, execution_id=engine_call_id, event_name=event_name
        ),
    }


async def _inbox_row(engine_call_id: str) -> uuid.UUID:
    key = f"{engine_call_id}:contact.opted_out:{uuid.uuid4().hex[:6]}"
    async with untenanted_session() as session:
        claim = await claim_inbox_event(
            session, provider=ENGINE, event_key=key, payload_hash=body_hash({"k": key})
        )
    return claim.row_id


async def _inbox_status(row_id: uuid.UUID) -> str:
    async with untenanted_session() as session:
        return str(
            (
                await session.execute(
                    text("SELECT status FROM webhook_inbox_events WHERE id = :id"), {"id": row_id}
                )
            ).scalar_one()
        )


@pytest.fixture
def alerts(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    raised: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        engine_signals, "alert", lambda _kind, code, **kw: raised.append((code, kw))
    )
    return raised


def test_the_job_is_named_as_voice_runtime_enqueues_it_and_is_registered() -> None:
    assert engine_signals.ENGINE_OPT_OUT_JOB == signed_intake.ENGINE_OPT_OUT_JOB
    registered = {getattr(fn, "__qualname__", "") for fn in WorkerSettings.functions}
    assert engine_signals.ENGINE_OPT_OUT_JOB in registered


async def test_the_number_is_filed_on_the_hearing_clients_list_only() -> None:
    tenant_id, agent_id, ref = await _route()
    neighbour, _, _ = await _route()
    call_id, engine_call_id = await _call(tenant_id, agent_id)
    payload = _payload(ref, engine_call_id)
    payload["inbox_row_id"] = str(await _inbox_row(engine_call_id))

    assert await engine_signals.ingest_engine_opt_out({}, payload) == "recorded"

    async with tenant_session(tenant_id) as session:
        ours = await check_number(session, tenant_id=tenant_id, raw=E164)
        evidence = (
            await session.execute(
                text(
                    "SELECT evidence, call_id FROM consent_ledger WHERE tenant_id = :tid "
                    "AND phone_e164 = :p AND status = 'withdrawn'"
                ),
                {"tid": tenant_id, "p": E164},
            )
        ).one()
    async with tenant_session(neighbour) as session:
        theirs = await check_number(session, tenant_id=neighbour, raw=E164)
    assert ours.suppressed is True and ours.scope == "tenant"
    assert theirs.suppressed is False
    assert evidence[0]["detected_by"] == optout.DETECTED_BY_ENGINE
    assert evidence[0]["rule"] == engine_signals.ENGINE_OPT_OUT_RULE
    assert evidence[1] == call_id
    assert await _inbox_status(uuid.UUID(payload["inbox_row_id"])) == "processed"

    # A replay files nothing new.
    payload["inbox_row_id"] = None
    assert await engine_signals.ingest_engine_opt_out({}, payload) == "recorded"
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT count(*) FROM consent_ledger WHERE tenant_id = :tid AND "
                    "phone_e164 = :p AND status = 'withdrawn'"
                ),
                {"tid": tenant_id, "p": E164},
            )
        ).scalar_one()
    assert rows == 1


async def test_a_call_we_have_no_row_for_still_files_the_number() -> None:
    tenant_id, _agent_id, ref = await _route()
    payload = _payload(ref, f"out_{uuid.uuid4()}")
    assert await engine_signals.ingest_engine_opt_out({}, payload) == "recorded"
    async with tenant_session(tenant_id) as session:
        assert (await check_number(session, tenant_id=tenant_id, raw=E164)).suppressed


@pytest.mark.parametrize(("ground", "phone"), [("no_route", PHONE), ("no_phone", None)])
async def test_an_opt_out_that_cannot_be_attributed_alarms_and_settles(
    ground: str, phone: str | None, alerts: list[tuple[str, dict[str, Any]]]
) -> None:
    _tenant_id, _agent_id, ref = await _route()
    engine_call_id = f"out_{uuid.uuid4()}"
    payload = _payload(
        ref if ground == "no_phone" else f"ag_{uuid.uuid4()}", engine_call_id, phone=phone
    )
    payload["inbox_row_id"] = str(await _inbox_row(engine_call_id))

    assert await engine_signals.ingest_engine_opt_out({}, payload) == "unattributable"

    [(code, fields)] = alerts
    assert code == "in_call_optout_unattributable"
    assert ground in str(fields.get("detail")) or ground in str(fields)
    assert await _inbox_status(uuid.UUID(payload["inbox_row_id"])) == "processed"


async def test_a_number_that_cannot_be_suppressed_alarms_rather_than_failing(
    alerts: list[tuple[str, dict[str, Any]]],
) -> None:
    _tenant_id, _agent_id, ref = await _route()
    payload = _payload(ref, f"out_{uuid.uuid4()}", phone="not a number")
    assert await engine_signals.ingest_engine_opt_out({}, payload) == "unattributable"
    assert [code for code, _ in alerts] == ["in_call_optout_unattributable"]


async def test_a_blip_is_retried_and_leaves_the_inbox_row_reclaimable(
    monkeypatch: pytest.MonkeyPatch, alerts: list[tuple[str, dict[str, Any]]]
) -> None:
    _tenant_id, _agent_id, ref = await _route()
    engine_call_id = f"out_{uuid.uuid4()}"
    payload = _payload(ref, engine_call_id)
    payload["inbox_row_id"] = str(await _inbox_row(engine_call_id))

    async def _down(*_a: object, **_k: object) -> None:
        raise ConnectionError("db")

    monkeypatch.setattr(engine_signals, "record_call_optout", _down)
    with pytest.raises(Retry):
        await engine_signals.ingest_engine_opt_out({"job_try": 1}, payload)
    assert await _inbox_status(uuid.UUID(payload["inbox_row_id"])) == "failed"
    assert alerts == []

    with pytest.raises(ConnectionError):
        await engine_signals.ingest_engine_opt_out({"job_try": 3}, payload)
    assert [code for code, _ in alerts] == ["engine_optout_abandoned"]


async def test_an_unreadable_delivery_is_abandoned_at_once(
    alerts: list[tuple[str, dict[str, Any]]],
) -> None:
    _tenant_id, _agent_id, ref = await _route()
    engine_call_id = f"out_{uuid.uuid4()}"
    payload = _payload(ref, engine_call_id)
    payload["delivery"] = None
    with pytest.raises(Exception) as raised:
        await engine_signals.ingest_engine_opt_out({"job_try": 1}, payload)
    assert getattr(raised.value, "code", None) == "engine_delivery_unreadable"
    assert [code for code, _ in alerts] == ["engine_optout_abandoned"]

    sealed_garbage = seal_delivery(
        "not json", engine=ENGINE, execution_id=engine_call_id, event_name="x"
    )
    payload["delivery"] = sealed_garbage
    with pytest.raises(Exception) as again:
        await engine_signals.ingest_engine_opt_out({"job_try": 1}, payload)
    assert getattr(again.value, "code", None) == "engine_delivery_unreadable"


# --- the engine's notices ------------------------------------------------------------------


def _notice_payload(ref: str, *, event: str = "conversation.escalated") -> dict[str, Any]:
    event_id = f"evt_{uuid.uuid4().hex[:10]}"
    body = json.dumps(
        {
            "id": event_id,
            "event": event,
            "sentAt": "2026-10-08T09:00:00Z",
            "data": {"agent": {"id": ref}, "callId": "out_n1"},
        }
    )
    return {
        "engine": ENGINE,
        "execution_id": event_id,
        "raw_status": event,
        "engine_agent_ref": ref,
        "delivery": seal_delivery(
            body, engine=ENGINE, execution_id=event_id, event_name=f"{event}:{event_id}"
        ),
    }


@pytest.fixture
def thinnest_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api.engine.thinnest import ThinnestEngine

    monkeypatch.setattr(engine_signals, "get_engine", lambda: ThinnestEngine(api_key="ta_x"))


def test_the_notice_job_is_named_as_voice_runtime_enqueues_it_and_is_registered() -> None:
    assert engine_signals.ENGINE_NOTICE_JOB == signed_intake.ENGINE_NOTICE_JOB
    registered = {getattr(fn, "__qualname__", "") for fn in WorkerSettings.functions}
    assert engine_signals.ENGINE_NOTICE_JOB in registered


@pytest.mark.parametrize(
    ("event", "kind"),
    [("conversation.escalated", "conversation_escalated"), ("lead.captured", "lead_captured")],
)
async def test_a_notice_is_normalised_attributed_and_settled(
    event: str, kind: str, thinnest_adapter: None
) -> None:
    _tenant_id, _agent_id, ref = await _route()
    payload = _notice_payload(ref, event=event)
    payload["inbox_row_id"] = str(await _inbox_row(payload["execution_id"]))

    assert await engine_signals.ingest_engine_notice({}, payload) == kind
    assert await _inbox_status(uuid.UUID(payload["inbox_row_id"])) == "processed"


async def test_a_notice_no_adapter_can_read_is_abandoned_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.engine.fake import FakeEngine

    monkeypatch.setattr(engine_signals, "get_engine", lambda: FakeEngine())
    _tenant_id, _agent_id, ref = await _route()
    payload = _notice_payload(ref)
    payload["inbox_row_id"] = str(await _inbox_row(payload["execution_id"]))

    with pytest.raises(Exception) as raised:
        await engine_signals.ingest_engine_notice({"job_try": 1}, payload)
    assert getattr(raised.value, "code", None) == "engine_delivery_unreadable"
    assert await _inbox_status(uuid.UUID(payload["inbox_row_id"])) == "failed"


async def test_a_notice_delivery_that_is_not_a_notice_is_abandoned(thinnest_adapter: None) -> None:
    _tenant_id, _agent_id, ref = await _route()
    for body in ("not json", json.dumps({"event": "call.analysed", "id": "evt_x"})):
        unit = f"evt_{uuid.uuid4().hex[:8]}"
        payload = {
            "engine": ENGINE,
            "execution_id": unit,
            "engine_agent_ref": ref,
            "delivery": seal_delivery(body, engine=ENGINE, execution_id=unit, event_name="n"),
        }
        with pytest.raises(Exception) as raised:
            await engine_signals.ingest_engine_notice({"job_try": 1}, payload)
        assert getattr(raised.value, "code", None) == "engine_delivery_unreadable"
    with pytest.raises(Exception) as missing:
        await engine_signals.ingest_engine_notice(
            {"job_try": 1}, {"engine": ENGINE, "execution_id": "e", "engine_agent_ref": ref}
        )
    assert getattr(missing.value, "code", None) == "engine_delivery_unreadable"


async def test_a_notice_blip_is_retried(
    monkeypatch: pytest.MonkeyPatch, thinnest_adapter: None
) -> None:
    _tenant_id, _agent_id, ref = await _route()
    payload = _notice_payload(ref)

    async def _down(*_a: object, **_k: object) -> None:
        raise ConnectionError("db")

    monkeypatch.setattr(engine_signals, "_tenant_of", _down)
    with pytest.raises(Retry):
        await engine_signals.ingest_engine_notice({"job_try": 1}, payload)
    with pytest.raises(ConnectionError):
        await engine_signals.ingest_engine_notice({"job_try": 3}, payload)
