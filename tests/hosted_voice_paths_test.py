"""The edges of D-687/D-688 that are not the voice panel: a delivery keyed by the vendor's own
call id at the receiver and read as it is by the worker, the drift sweep noticing a deleted
clone and repairing an agent's own-voice-key switch, and the preview store.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents.hosted_voices import agent_voice_withdrawn
from apps.api.agents.reconciliation import DriftCandidate
from apps.api.db.session import tenant_session
from apps.workers import engine_delivery, engine_reconciliation, storage
from calevate_shared.engine import ExecutionSnapshot
from signed_intake import SIGNED_INTAKES, keyed_event
from sqlalchemy import text
from tests.hosted_voice_fakes import CatalogueRows, HostingEngine, selected

INTAKE = SIGNED_INTAKES["thinnest"]


# --- the receiver ------------------------------------------------------------------------


def test_a_delivery_is_keyed_by_its_call_id_and_matched_on_the_agent() -> None:
    payload = {
        "id": "evt_1",
        "event": "call.analysed",
        "data": {"id": "out_1", "agent": {"id": "ag_9"}, "analysedAt": "T"},
    }
    keyed = keyed_event(INTAKE, payload, engine_agent_ref="ag_9")
    assert not isinstance(keyed, str) and keyed.execution_id == "out_1"
    assert keyed_event(INTAKE, payload, engine_agent_ref="ag_1") == "agent mismatch"


# --- the worker reads a delivered document as it is --------------------------------------


def test_the_worker_reads_a_delivered_document() -> None:
    class _Reads:
        name = "thinnest"

        def snapshot_from_delivery(self, payload: dict[str, Any]) -> ExecutionSnapshot:
            return ExecutionSnapshot(
                engine_call_id=str(payload["data"]["id"]),
                direction="outbound",
                status="completed",
                raw_status="completed",
                terminal=True,
                billable_ready=True,
                engine="thinnest",
            )

    document = json.dumps({"data": {"id": "out_1"}}).encode()
    snapshot = engine_delivery.snapshot_of_document(
        _Reads(),  # type: ignore[arg-type]
        document,
        execution_id="out_1",
    )
    assert snapshot.raw_document == document


# --- the drift sweep notices a voice the platform no longer has --------------------------


async def _tenant_agent() -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name="Drift Clinic",
        slug=f"dv-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return uuid.UUID(str(created["id"])), uuid.UUID(str(created["agent_id"]))


async def test_an_agent_on_a_withdrawn_voice_is_found(hosted_rows: CatalogueRows) -> None:
    tenant_id, agent_id = await _tenant_agent()
    gone = await hosted_rows.add("engine", withdrawn=True)
    live = await hosted_rows.add("engine")
    for voice, expected in ((live, False), (gone, True), (None, False)):
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE agents SET engine_voice_id = :v WHERE id = :a"),
                {"v": voice, "a": agent_id},
            )
        async with tenant_session(tenant_id) as session:
            assert await agent_voice_withdrawn(session, agent_id=agent_id) is expected


@pytest.mark.parametrize("withdrawn", [True, False])
async def test_the_drift_sweep_alarms_on_a_withdrawn_voice(
    monkeypatch: pytest.MonkeyPatch, withdrawn: bool
) -> None:
    raised: list[str] = []

    async def _drift(**kw: Any) -> Any:
        return SimpleNamespace(
            state="in_sync",
            truthful_answer_applied=True,
            own_voice_key_applied=True,
            own_voice_key_expected=None,
        )

    async def _recorded(*a: Any, **kw: Any) -> bool:
        return True

    async def _silence(*a: Any, **kw: Any) -> str:
        return "unchanged"

    async def _actions(**kw: Any) -> str:
        return "healthy"

    async def _withdrawn(session: Any, *, agent_id: Any) -> bool:
        return withdrawn

    monkeypatch.setattr(engine_reconciliation, "engine_drift_for", _drift)
    monkeypatch.setattr(engine_reconciliation, "record_drift", _recorded)
    monkeypatch.setattr(engine_reconciliation, "reconcile_inbound_truthful_answer", _silence)
    monkeypatch.setattr(engine_reconciliation, "check_agent_actions", _actions)
    monkeypatch.setattr(engine_reconciliation, "agent_voice_withdrawn", _withdrawn)
    monkeypatch.setattr(
        engine_reconciliation, "alert", lambda stage, code, **kw: raised.append(code)
    )
    candidate = DriftCandidate(
        tenant_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        engine_agent_ref="ag_1",
        drift_checked_at=None,
    )
    await engine_reconciliation._reconcile_one("thinnest", candidate)
    assert ("engine_agent_voice_withdrawn" in raised) is withdrawn


def _sweep_doubles(
    monkeypatch: pytest.MonkeyPatch, drift: Any, raised: list[str], *, withdrawn: bool = False
) -> None:
    async def _drift(**kw: Any) -> Any:
        return drift

    async def _recorded(*a: Any, **kw: Any) -> bool:
        return True

    async def _silence(*a: Any, **kw: Any) -> str:
        return "unchanged"

    async def _actions(**kw: Any) -> str:
        return "healthy"

    async def _withdrawn(session: Any, *, agent_id: Any) -> bool:
        return withdrawn

    monkeypatch.setattr(engine_reconciliation, "engine_drift_for", _drift)
    monkeypatch.setattr(engine_reconciliation, "record_drift", _recorded)
    monkeypatch.setattr(engine_reconciliation, "reconcile_inbound_truthful_answer", _silence)
    monkeypatch.setattr(engine_reconciliation, "check_agent_actions", _actions)
    monkeypatch.setattr(engine_reconciliation, "agent_voice_withdrawn", _withdrawn)
    monkeypatch.setattr(
        engine_reconciliation, "alert", lambda stage, code, **kw: raised.append(code)
    )


def _candidate(ref: str = "ag_1") -> DriftCandidate:
    return DriftCandidate(
        tenant_id=uuid.uuid4(), agent_id=uuid.uuid4(), engine_agent_ref=ref, drift_checked_at=None
    )


@pytest.mark.parametrize("expected", [False, True])
async def test_the_drift_sweep_puts_an_agents_own_voice_key_switch_back(
    monkeypatch: pytest.MonkeyPatch, expected: bool
) -> None:
    raised: list[str] = []
    drift = SimpleNamespace(
        state="not_applied",
        truthful_answer_applied=True,
        own_voice_key_applied=False,
        own_voice_key_expected=expected,
    )
    _sweep_doubles(monkeypatch, drift, raised)
    engine = HostingEngine()
    engine.own_voice_key["ag_1"] = not expected
    with selected(engine):
        await engine_reconciliation._reconcile_one("thinnest", _candidate())
    assert engine.own_voice_key["ag_1"] is expected
    assert raised == ["engine_agent_voice_key_repaired"]


async def test_a_switch_repair_the_platform_refuses_is_left_to_the_next_tick(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raised: list[str] = []
    drift = SimpleNamespace(
        state="not_applied",
        truthful_answer_applied=True,
        own_voice_key_applied=False,
        own_voice_key_expected=False,
    )
    _sweep_doubles(monkeypatch, drift, raised)
    engine = HostingEngine()
    engine.own_voice_key["ag_1"] = True
    engine.refuse_switch.add("ag_1")
    with selected(engine):
        await engine_reconciliation._reconcile_one("thinnest", _candidate())
    assert engine.own_voice_key["ag_1"] is True and raised == []


async def test_a_judged_switch_mismatch_is_not_applied_and_names_the_expectation() -> None:
    from apps.api.agents.verification import judge
    from calevate_shared.engine import AgentConfig, AgentSnapshot

    cfg = AgentConfig(
        tenant_id=str(uuid.uuid4()),
        agent_id=str(uuid.uuid4()),
        name="A",
        system_prompt="Be kind.",
        opening_line="Namaste.",
        direction="inbound",
        engine_own_voice_key=False,
    )
    engine = HostingEngine()
    held = AgentSnapshot(engine_agent_ref="ag_1", engine_own_voice_key=True, engine="thinnest")
    unread = held.model_copy(update={"engine_own_voice_key": None})
    assert judge(engine, cfg, held).own_voice_key_applied is False
    assert judge(engine, cfg, unread).own_voice_key_applied is None
    unasked = cfg.model_copy(update={"engine_own_voice_key": None})
    assert judge(engine, unasked, held).own_voice_key_applied is not False


# --- the preview store --------------------------------------------------------------------


def test_a_preview_key_is_a_digest_under_its_own_prefix() -> None:
    key = storage.voice_preview_key("engine:spry__rakesh")
    assert key.startswith(f"{storage.VOICE_PREVIEW_PREFIX}/") and ":" not in key
    assert key == storage.voice_preview_key("engine:spry__rakesh")


async def test_the_preview_store_puts_reads_and_refuses_a_foreign_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    put: list[tuple[str, str]] = []

    async def _put(*, key: str, data: bytes, content_type: str, **kw: Any) -> str:
        put.append((key, content_type))
        return key

    async def _read(key: str) -> bytes | None:
        return b"ID3"

    monkeypatch.setattr(storage, "_put_document", _put)
    monkeypatch.setattr(storage, "read_kb_object", _read)
    key = storage.voice_preview_key("engine:a")
    assert await storage.store_voice_preview(key=key, data=b"x", content_type="audio/mpeg") == key
    assert put == [(key, "audio/mpeg")]
    assert await storage.read_voice_preview(key) == b"ID3"
    with pytest.raises(ValueError):
        await storage.read_voice_preview("kb-uploads/x")


@pytest.mark.parametrize("body", [b"", b"x" * (storage.MAX_VOICE_PREVIEW_BYTES + 1)])
async def test_a_vendor_preview_that_is_empty_or_too_large_is_refused(
    monkeypatch: pytest.MonkeyPatch, body: bytes
) -> None:
    async def _fetch(url: str, **kw: Any) -> bytes:
        return body

    monkeypatch.setattr(storage, "_fetch_recording", _fetch)
    with pytest.raises(storage.RecordingUnavailableError):
        await storage.fetch_voice_preview("https://files.example.com/p.mp3")


async def test_a_vendor_preview_is_fetched(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fetch(url: str, **kw: Any) -> bytes:
        return b"ID3audio"

    monkeypatch.setattr(storage, "_fetch_recording", _fetch)
    assert await storage.fetch_voice_preview("https://files.example.com/p.mp3") == b"ID3audio"
