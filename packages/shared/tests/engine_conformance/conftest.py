"""Conformance fixtures: every adapter runs the SAME suite.

The suite lives in `packages/shared` on purpose — it tests the CONTRACT, not an
implementation, so it belongs next to the Protocol rather than inside `apps/api`.
Bolna is exercised against a transport stub (`httpx.MockTransport`) fed payload
shapes captured from their docs; the fake engine runs as itself. Neither test touches
the network — `make conformance` must be runnable on a plane.

Adding an engine = adding one entry to `ENGINE_IDS` and a factory below. If the new
adapter cannot pass unchanged, the contract is wrong or the adapter is leaking.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import httpx
import pytest
from apps.api.engine.bolna import BolnaEngine
from apps.api.engine.fake import FakeEngine

ENGINE_IDS = ["fake", "bolna"]

# A completed execution as Bolna documents it: USD-cent costs with a per-leg
# breakdown, prefix-tagged transcript text, recording on their S3.
BOLNA_COMPLETED: dict[str, Any] = {
    "id": "exec_abc123",
    "agent_id": "agent_xyz",
    "status": "completed",
    "direction": "inbound",
    "created_at": "2026-08-10T09:15:00Z",
    "ended_at": "2026-08-10T09:16:35Z",
    "conversation_duration": 95,
    "total_cost": 8.5,
    "cost_breakdown": {
        "platform": 5.0,
        "network": 1.5,
        "llm": 0.0,
        "synthesizer": 1.4,
        "transcriber": 0.6,
    },
    "telephony_data": {
        "from_number": "+919876543210",
        "to_number": "+911140000000",
        "recording_url": "https://s3.us-east-1.amazonaws.com/bolna/exec_abc123.wav",
    },
    "transcript": (
        "assistant: Namaskaram, idi Sunrise Clinic AI assistant. Ee call record avutundi.\n"
        "user: Naaku appointment kavali.\n"
        "assistant: Tappakunda, ee roju evening 6 gantalaku doctor available unnaru.\n"
        "user: Sare, naa peru Ravi."
    ),
    "extracted_data": {},
}


def _bolna_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/v2/agent" and request.method == "POST":
        return httpx.Response(200, json={"agent_id": "agent_xyz"})
    if path.startswith("/v2/agent/") and request.method == "PUT":
        return httpx.Response(200, json={"status": "ok"})
    if path == "/call" and request.method == "POST":
        body = json.loads(request.content or b"{}")
        assert body["recipient_phone_number"].startswith("+"), "E.164 only"
        return httpx.Response(200, json={"execution_id": "exec_abc123"})
    if path == "/knowledgebase":
        return httpx.Response(200, json={"rag_id": "kb_1"})
    if path.startswith("/executions/") and path.endswith("/stop"):
        return httpx.Response(200, json={"status": "stopped"})
    if path == "/executions":
        return httpx.Response(200, json={"data": [BOLNA_COMPLETED]})
    if path.startswith("/executions/"):
        return httpx.Response(200, json=BOLNA_COMPLETED)
    return httpx.Response(404, json={"error": "not found"})


def make_engine(engine_id: str):
    if engine_id == "fake":
        return FakeEngine()
    return BolnaEngine(
        api_key="test-key",
        fx_rate=Decimal("88.00"),
        client=httpx.AsyncClient(
            base_url="https://api.bolna.ai",
            transport=httpx.MockTransport(_bolna_handler),
        ),
    )


@pytest.fixture(params=ENGINE_IDS)
def engine(request: pytest.FixtureRequest):
    return make_engine(request.param)


@pytest.fixture
def engine_id(request: pytest.FixtureRequest) -> str:
    return str(request.node.callspec.params["engine"])
