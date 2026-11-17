"""End-to-end smoke of a client's inbound journey through the HTTP API.

Run: `make smoke` (or `uv run pytest -m smoke`). Requires the local Postgres and Redis.

`smoke_pipeline_test.py` proves a webhook becomes a lead. This one walks the client's own
path around it, through the routes the screens call, and checks each answer against the
rows behind it:

1. an Inbound line is started in an agent's voice (a draft, not live);
2. its script is saved, which puts it live on its own engine agent;
3. a caller rings that engine agent: the engine's webhook reaches voice-runtime, the worker
   jobs run, and the call is stamped with the line;
4. the line's Calls taken, the Call logs, the call page and Leads each show that one call
   and its lead, with the transcript redacted by default (hard rule 5).

Everything runs in one process, because the fake engine keeps its calls in memory: a call
staged here is unknown to a separately running worker.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import httpx
import pytest
from apps.api.db.session import tenant_session
from apps.api.main import app as api_app
from apps.workers.pipeline import ingest_engine_event, run_post_call_pipeline
from calevate_shared.call_script import CallScript
from main import app as voice_app  # apps/voice-runtime is on the pytest path (D-18)
from sqlalchemy import text
from tests.agent_lifecycle_test import _fresh_engine, _move, _tenant, _write_script
from tests.smoke_pipeline_test import _stub_storage

pytestmark = [pytest.mark.smoke]

# The recording copy needs a bucket; the stub is `smoke_pipeline_test`'s.
_stub_storage = _stub_storage

SCRIPT = CallScript(opening_line="Namaste, Lifecycle Clinic. How can I help you today?")


def _api() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=api_app), base_url="http://api")


def _as(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _one(tenant_id: uuid.UUID, sql: str, **params: Any) -> Any:
    async with tenant_session(tenant_id) as session:
        return (await session.execute(text(sql), params)).one()


async def test_a_line_put_live_takes_a_call_that_reaches_calls_and_leads() -> None:
    engine = _fresh_engine()
    tenant_id, agent_id, token = await _tenant()
    await _write_script(tenant_id, agent_id)
    code, body = await _move(token, agent_id, "activate")
    assert code == 200, body

    async with _api() as http:
        # 1. Inbound > New line: a draft in the agent's voice.
        created = await http.post(
            "/v1/inbound-lines", json={"agent_id": str(agent_id)}, headers=_as(token)
        )
        assert created.status_code == 201, created.text
        line = created.json()
        line_id = line["id"]
        assert (line["live"], line["script"], line["agent_id"]) == (False, None, str(agent_id))

        # 2. Saving the script puts it live on its own engine agent.
        saved = await http.put(
            f"/v1/inbound-lines/{line_id}/script",
            json={"script": SCRIPT.model_dump(mode="json")},
            headers=_as(token),
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["live"] is True
        listed = await http.get("/v1/inbound-lines", headers=_as(token))
        assert [(row["id"], row["live"]) for row in listed.json()["lines"]] == [(line_id, True)]

    route = await _one(
        tenant_id,
        "SELECT engine_agent_ref FROM engine_agent_routes WHERE inbound_line_id = :l AND active",
        l=line_id,
    )
    line_ref = str(route.engine_agent_ref)
    agent_ref = (await _one(tenant_id, "SELECT engine_agent_ref FROM agents WHERE id = :a", a=agent_id))[0]
    assert line_ref != agent_ref, "a line answers on its own engine agent, never the agent's"

    # 3. A caller rings the line's engine agent; the engine's webhook arrives.
    execution_id = f"exec_{uuid.uuid4().hex[:12]}"
    caller = f"+9198{uuid.uuid4().int % 100000000:08d}"
    engine.seed_inbound_call(  # type: ignore[attr-defined]
        call_id=execution_id, agent_ref=line_ref, from_e164=caller, to_e164="+911140000000"
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=voice_app), base_url="http://runtime"
    ) as runtime:
        started = time.monotonic()
        acked = await runtime.post(
            "/hooks/v1/engine/fake",
            json={"execution_id": execution_id, "status": "completed", "agent_id": line_ref},
        )
        assert time.monotonic() - started < 5
    assert acked.status_code == 202, acked.text
    assert float(acked.headers["X-Ack-Ms"]) < 500

    job = {"engine": "fake", "execution_id": execution_id, "engine_agent_ref": line_ref}
    assert await ingest_engine_event({}, job) == "pipeline_enqueued"
    call_row = await _one(
        tenant_id, "SELECT id FROM calls WHERE engine_call_id = :e", e=execution_id
    )
    call_id = str(call_row.id)
    await run_post_call_pipeline(
        {},
        {
            "tenant_id": str(tenant_id),
            "call_id": call_id,
            "engine": "fake",
            "execution_id": execution_id,
        },
    )

    db_call = await _one(
        tenant_id,
        "SELECT status, direction, inbound_line_id, duration_s FROM calls WHERE id = :c",
        c=call_id,
    )
    assert (db_call.status, db_call.direction, str(db_call.inbound_line_id)) == (
        "completed",
        "inbound",
        line_id,
    )
    db_lead = await _one(
        tenant_id, "SELECT id, phone_e164, call_count FROM leads WHERE last_call_id = :c", c=call_id
    )
    assert db_lead.phone_e164 == caller

    # 4. What each screen reads, against those rows.
    async with _api() as http:
        taken = (await http.get(f"/v1/inbound-lines/{line_id}/calls", headers=_as(token))).json()
        assert [row["id"] for row in taken["calls"]] == [call_id]

        log = (await http.get("/v1/calls", headers=_as(token))).json()
        row = next(entry for entry in log if entry["id"] == call_id)
        assert row["inbound_line"]["id"] == line_id
        assert (row["direction"], row["status"], row["duration_s"]) == (
            "inbound",
            "completed",
            db_call.duration_s,
        )

        page = (await http.get(f"/v1/calls/{call_id}", headers=_as(token))).json()
        assert page["transcript"], "the call page shows what was said"
        turns = await _one(
            tenant_id,
            "SELECT count(*) AS n FROM transcript_turns WHERE call_id = :c",
            c=call_id,
        )
        assert len(page["transcript"]) == turns.n
        redacted = await _one(
            tenant_id,
            "SELECT text_redacted FROM transcript_turns WHERE call_id = :c ORDER BY idx LIMIT 1",
            c=call_id,
        )
        assert page["transcript"][0]["text"] == redacted.text_redacted

        leads = (await http.get("/v1/leads", headers=_as(token))).json()["items"]
        assert [(lead["id"], lead["phone_e164"]) for lead in leads] == [
            (str(db_lead.id), caller)
        ]
        lead = (await http.get(f"/v1/leads/{db_lead.id}", headers=_as(token))).json()
        assert (lead["call_count"], lead["last_call_id"]) == (db_lead.call_count, call_id)
