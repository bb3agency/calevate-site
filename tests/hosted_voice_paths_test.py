"""The edges of D-687 that are not the voice panel: a Studio delivery keyed by its workspace
at the receiver, read in it by the worker, the drift sweep noticing a deleted clone, and the
preview store.
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
from tests.hosted_voice_fakes import CatalogueRows

INTAKE = SIGNED_INTAKES["thinnest"]


# --- the receiver ------------------------------------------------------------------------


def test_a_studio_delivery_is_keyed_in_its_workspace_and_matched_on_the_bare_agent() -> None:
    payload = {
        "event": "call.analysed",
        "data": {"id": "out_1", "agent": {"id": "ag_9"}, "analysedAt": "T"},
    }
    keyed = keyed_event(INTAKE, payload, engine_agent_ref="ag_9@org_studio")
    assert not isinstance(keyed, str) and keyed.execution_id == "out_1@org_studio"
    ours = keyed_event(INTAKE, payload, engine_agent_ref="ag_9")
    assert not isinstance(ours, str) and ours.execution_id == "out_1"
    assert keyed_event(INTAKE, payload, engine_agent_ref="ag_1@org_studio") == "agent mismatch"


def test_a_call_id_that_already_carries_a_scope_is_not_keyed() -> None:
    payload = {"event": "call.analysed", "data": {"id": "out_1@org_x"}}
    assert keyed_event(INTAKE, payload, engine_agent_ref="ag_9@org_studio") == (
        "unusable execution key"
    )


# --- the worker reads a delivery in the workspace it was keyed in ------------------------


def test_the_worker_reads_a_delivered_document_in_its_workspace() -> None:
    asked: list[str | None] = []

    class _Reads:
        name = "thinnest"

        def snapshot_from_delivery(
            self, payload: dict[str, Any], *, workspace: str | None = None
        ) -> ExecutionSnapshot:
            asked.append(workspace)
            return ExecutionSnapshot(
                engine_call_id=f"out_1@{workspace}",
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
        execution_id="out_1@org_studio",
    )
    assert asked == ["org_studio"] and snapshot.raw_document == document


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
        return SimpleNamespace(state="in_sync", truthful_answer_applied=True)

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
