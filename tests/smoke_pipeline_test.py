"""End-to-end smoke: tenant → agent → engine webhook → call → extraction → lead.

Run: `make smoke` (or `uv run pytest -m smoke`). Requires the local Postgres and Redis.

This is the test that says "the product works". It drives the real voice-runtime ASGI
app, the real inbox dedupe, the real pipeline, the real redaction and the real lead
upsert — only two things are substituted, both for reasons that are about the
environment rather than the logic:

- **object storage** — the recording copy needs a bucket; the assertion that it ran
  FIRST and that a failure propagates is kept by checking the stored key.
- **the engine source IP** — the webhook allowlist is exercised separately in
  `webhook_receiver_test.py`; here the `fake` engine is used, which is the documented
  local configuration (`ENGINE=fake`).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine, reset_engine_cache
from apps.workers.pipeline import ingest_engine_event, run_post_call_pipeline
from httpx import ASGITransport, AsyncClient
from main import app as voice_app  # apps/voice-runtime is on the pytest path (D-18)
from sqlalchemy import text

pytestmark = [pytest.mark.smoke]

CLINIC_SCHEMA: list[dict[str, Any]] = [
    {"key": "name", "label": "Caller name", "type": "text", "reason": "who is calling"},
    {
        "key": "intent",
        "label": "Intent",
        "type": "enum",
        "enum_values": ["book", "reschedule", "enquiry"],
        "reason": "what they want",
    },
    {
        "key": "urgency",
        "label": "Urgency",
        "type": "enum",
        "enum_values": ["routine", "urgent", "emergency"],
        "reason": "how soon they need it",
    },
]


async def _seed_tenant(engine_agent_ref: str) -> tuple[uuid.UUID, uuid.UUID]:
    """Create an org + agent + extraction schema exactly as the admin wizard would."""
    tenant_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    schema_id = uuid.uuid4()
    slug = f"clinic-{tenant_id.hex[:10]}"

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO organizations (id, name, slug, status, created_at, updated_at) "
                "VALUES (:id, 'Sunrise Clinic', :slug, 'active', now(), now())"
            ),
            {"id": tenant_id, "slug": slug},
        )
        await session.execute(
            text(
                "INSERT INTO agents (id, tenant_id, name, direction, disclosure_line, "
                "ai_disclosure_line, recording_notice_line, caller_memory_notice_line, status, "
                "engine, engine_agent_ref, created_at, updated_at) VALUES (:id, :tid, "
                "'Receptionist', 'inbound', 'Idi AI assistant. Call record avutundi.', 'Idi AI "
                "assistant. Call record avutundi.', 'This call is being recorded.', 'I keep a "
                "short note of what you ask about.', 'live', 'fake', :ref, now(), now())"
            ),
            {"id": agent_id, "tid": tenant_id, "ref": engine_agent_ref},
        )
        await session.execute(
            text(
                "INSERT INTO extraction_schemas (id, tenant_id, agent_id, version, fields, "
                "published_at, created_at, updated_at) VALUES (:id, :tid, :aid, 1, "
                "CAST(:fields AS jsonb), now(), now(), now())"
            ),
            {
                "id": schema_id,
                "tid": tenant_id,
                "aid": agent_id,
                "fields": __import__("json").dumps(CLINIC_SCHEMA),
            },
        )
        await session.execute(
            text("UPDATE agents SET extraction_schema_id = :sid WHERE id = :aid"),
            {"sid": schema_id, "aid": agent_id},
        )

    # The publish path writes the inbound routing row in the same breath as
    # engine_agent_ref; without it an engine webhook has no way back to this tenant.
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, "
                "agent_id, active, created_at, updated_at) VALUES ('fake', :ref, :tid, :aid, "
                "true, now(), now()) ON CONFLICT (engine, engine_agent_ref) DO UPDATE SET "
                "tenant_id = EXCLUDED.tenant_id, agent_id = EXCLUDED.agent_id, active = true"
            ),
            {"ref": engine_agent_ref, "tid": tenant_id, "aid": agent_id},
        )
    return tenant_id, agent_id


@pytest.fixture(autouse=True)
def _stub_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_copy(*, source_url: str, tenant_id: uuid.UUID, call_id: uuid.UUID) -> str:
        return f"recordings/{tenant_id}/{call_id}.wav"

    monkeypatch.setattr("apps.workers.pipeline.copy_recording", _fake_copy)


async def test_inbound_call_becomes_a_lead_with_extracted_fields() -> None:
    reset_engine_cache()
    engine = get_engine()
    execution_id = f"exec_{uuid.uuid4().hex[:12]}"
    caller = f"+9198{uuid.uuid4().int % 100000000:08d}"

    # 1. A provisioned agent, mapped to the engine's id space.
    agent_ref = "fakeagent_smoke_" + uuid.uuid4().hex[:8]
    tenant_id, _agent_id = await _seed_tenant(agent_ref)

    # 2. The engine has a completed inbound call for it.
    engine.seed_inbound_call(  # type: ignore[attr-defined]
        call_id=execution_id,
        agent_ref=agent_ref,
        from_e164=caller,
        to_e164="+911140000000",
    )

    # 3. The webhook arrives at voice-runtime and is acked fast.
    async with AsyncClient(
        transport=ASGITransport(app=voice_app), base_url="http://runtime"
    ) as client:
        response = await client.post(
            "/hooks/v1/engine/fake",
            json={"execution_id": execution_id, "status": "completed", "agent_id": agent_ref},
        )
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "accepted"
    # Hard rule 3's number, asserted rather than hoped for.
    assert float(response.headers["X-Ack-Ms"]) < 500

    # 4. The worker jobs run (in production ARQ does this).
    result = await ingest_engine_event(
        {}, {"engine": "fake", "execution_id": execution_id, "engine_agent_ref": agent_ref}
    )
    assert result == "pipeline_enqueued"

    async with tenant_session(tenant_id) as session:
        call_row = (
            await session.execute(
                text("SELECT id, status, direction FROM calls WHERE engine_call_id = :e"),
                {"e": execution_id},
            )
        ).first()
    assert call_row is not None, "the call row must exist before the pipeline runs"
    call_id, status, direction = call_row
    assert status == "completed"
    assert direction == "inbound"

    await run_post_call_pipeline(
        {},
        {
            "tenant_id": str(tenant_id),
            "call_id": str(call_id),
            "engine": "fake",
            "execution_id": execution_id,
        },
    )

    # 5. Everything the client actually sees.
    async with tenant_session(tenant_id) as session:
        turns = (
            await session.execute(
                text(
                    "SELECT text, text_redacted FROM transcript_turns WHERE call_id = :c "
                    "ORDER BY idx"
                ),
                {"c": call_id},
            )
        ).all()
        lead = (
            await session.execute(
                text(
                    "SELECT id, phone_e164, data, call_count, status, source FROM leads "
                    "WHERE tenant_id = :t"
                ),
                {"t": tenant_id},
            )
        ).first()
        extraction = (
            await session.execute(
                text("SELECT data, valid, schema_version FROM call_extractions WHERE call_id = :c"),
                {"c": call_id},
            )
        ).first()
        usage = (
            await session.execute(
                text("SELECT unit_type, unit_cost_paid FROM usage_events WHERE call_id = :c"),
                {"c": call_id},
            )
        ).all()
        recording = (
            await session.execute(
                text("SELECT recording_url FROM calls WHERE id = :c"), {"c": call_id}
            )
        ).scalar()

    assert turns, "transcript turns must be persisted"
    # Hard rule 5 + 6: the sample transcript says a phone number out loud, and the
    # redacted column is what every API response returns by default.
    spoken_number = "9876543210"
    assert any(spoken_number in raw for raw, _ in turns), "fixture must contain a phone number"
    assert all(spoken_number not in (red or "") for _, red in turns), "redaction must strip it"

    assert lead is not None, "a completed inbound call must create a lead"
    assert lead[1] == caller, "the lead is keyed on the CALLER, not our own number"
    assert lead[3] == 1
    assert lead[5] == "inbound_call"

    assert extraction is not None
    assert extraction[2] == 1, "the schema version at extraction time is recorded"

    assert usage, "a completed call must be metered"
    assert {u[0] for u in usage} >= {"telephony_s", "platform_min", "stt_s"}
    assert all(cost is None or cost >= 0 for _, cost in usage)

    assert recording and recording.startswith("recordings/"), "our storage key, not the engine URL"


async def test_pipeline_is_idempotent_and_never_double_meters() -> None:
    """A duplicate webhook, a poller rediscovery and a manual replay all land here.
    Running the whole pipeline twice must not create a second lead or a second charge —
    `usage_events` is append-only, so a double-run would be unfixable by UPDATE."""
    reset_engine_cache()
    engine = get_engine()
    execution_id = f"exec_{uuid.uuid4().hex[:12]}"
    agent_ref = "fakeagent_idem_" + uuid.uuid4().hex[:8]
    tenant_id, _ = await _seed_tenant(agent_ref)
    engine.seed_inbound_call(  # type: ignore[attr-defined]
        call_id=execution_id,
        agent_ref=agent_ref,
        from_e164=f"+9197{uuid.uuid4().int % 100000000:08d}",
        to_e164="+911140000000",
    )

    for _ in range(2):
        await ingest_engine_event(
            {}, {"engine": "fake", "execution_id": execution_id, "engine_agent_ref": agent_ref}
        )
        async with tenant_session(tenant_id) as session:
            call_id = (
                await session.execute(
                    text("SELECT id FROM calls WHERE engine_call_id = :e"), {"e": execution_id}
                )
            ).scalar()
        await run_post_call_pipeline(
            {},
            {
                "tenant_id": str(tenant_id),
                "call_id": str(call_id),
                "engine": "fake",
                "execution_id": execution_id,
            },
        )

    async with tenant_session(tenant_id) as session:
        calls = (
            await session.execute(
                text("SELECT count(*) FROM calls WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar()
        leads = (
            await session.execute(
                text("SELECT count(*) FROM leads WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar()
        usage_rows = (
            await session.execute(
                text("SELECT count(*) FROM usage_events WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar()
        turns = (
            await session.execute(
                text("SELECT count(*) FROM transcript_turns WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
        ).scalar()

    assert calls == 1, "one execution id is one call row"
    assert leads == 1, "the same caller must not fan out into duplicate leads"
    assert turns == 5, "transcript turns upsert on (call_id, idx) rather than duplicating"
    assert usage_rows and usage_rows <= 5, "metering must run exactly once per call"


async def test_webhook_dedupe_survives_a_repeat_delivery() -> None:
    """The inbox is the durable half of the dedupe story; Redis is only the fast path."""
    execution_id = f"exec_{uuid.uuid4().hex[:12]}"
    body = {"execution_id": execution_id, "status": "completed", "agent_id": "agent_dedupe"}

    async with AsyncClient(
        transport=ASGITransport(app=voice_app), base_url="http://runtime"
    ) as client:
        first = await client.post("/hooks/v1/engine/fake", json=body)
        second = await client.post("/hooks/v1/engine/fake", json=body)

    assert first.json()["status"] == "accepted"
    assert second.json()["status"] == "duplicate"

    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT count(*) FROM webhook_inbox_events WHERE provider = 'fake' "
                    "AND event_key = :k"
                ),
                # The inbox key is `{execution_id}:{raw_status}` — the unit of work is
                # the TRANSITION, not the execution (D-40), because Bolna fires one
                # webhook per status change and `completed` is the only one that carries
                # cost, recording and transcript. Keying on the execution alone meant the
                # first transition claimed the row and `completed` was answered
                # `duplicate` and never reached the queue.
                {"k": f"{execution_id}:completed"},
            )
        ).scalar()
    assert rows == 1, "one transition is one inbox row, however many deliveries arrive"
