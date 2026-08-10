"""Scaffold sanity checks.

These assert the monorepo wiring itself — that every deployable imports and that
the shared contracts are reachable from the workspace. They are NOT a substitute
for the real smoke test (DEV-SETUP.md §2), which needs a database and a signed
webhook and arrives with ROADMAP M1.
"""

from apps.api.main import app as api_app
from apps.workers.settings import WorkerSettings
from calevate_shared.engine import VoiceEngine
from calevate_shared.events import CallEvent, TranscriptTurn
from fastapi.testclient import TestClient


def test_api_health() -> None:
    with TestClient(api_app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "api"}


def test_worker_settings_retry_policy() -> None:
    """Jobs retry 3 times before the DLQ (TRD §8)."""
    assert WorkerSettings.max_tries == 3


def test_shared_contracts_are_importable() -> None:
    """packages/shared resolves as an editable workspace dependency."""
    assert VoiceEngine is not None
    assert CallEvent.model_fields.keys() >= {"call_id", "tenant_id", "engine"}


def test_transcript_turn_defaults_to_no_redaction() -> None:
    """text_redacted is populated by the pipeline, never assumed present."""
    turn = TranscriptTurn(call_id="c1", idx=0, speaker="caller", text="hello")
    assert turn.text_redacted is None
