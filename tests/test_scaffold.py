"""Scaffold sanity checks.

These assert the monorepo wiring itself — that every deployable imports and that the
shared contracts are reachable from the workspace. The real end-to-end proof lives in
`smoke_pipeline_test.py`.

Health is driven through an ASGI transport rather than `TestClient`: the sync client
spins up its own event loop, while the async engine and Redis client are process-level
singletons bound to the session loop (see the pytest config). Sharing one loop is also
what production does.
"""

from apps.api.main import app as api_app
from apps.workers.settings import CRON_JOBS, FUNCTIONS, WorkerSettings
from calevate_shared.engine import VoiceEngine
from calevate_shared.events import CallEvent, TranscriptTurn
from httpx import ASGITransport, AsyncClient


async def test_api_health_reports_its_dependencies() -> None:
    """The wiring proof: the app answers, and it answers "ok", which it can only do
    after reaching Postgres and Redis (`core/health.py`).

    It used to read `degradation_mode` and `checks` off the body. Those are now
    disclosed only to an `ops:manage` caller — an anonymous probe learns the verdict and
    not which of our dependencies is down — so the pair of assertions (hidden here,
    shown to the operator) lives in `tests/health_disclosure_test.py` where the
    credential to prove the second half is set up.
    """
    async with AsyncClient(transport=ASGITransport(app=api_app), base_url="http://api") as client:
        response = await client.get("/healthz")
    body = response.json()
    assert response.status_code == 200, body
    # ONE word for the dashboard (BACKEND-PATTERNS §6).
    assert body == {"status": "ok", "service": "api"}


async def test_liveness_touches_no_dependency() -> None:
    """A DB blip must not get the container killed by the orchestrator."""
    async with AsyncClient(transport=ASGITransport(app=api_app), base_url="http://api") as client:
        response = await client.get("/healthz/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "api"}


def test_worker_settings_retry_policy() -> None:
    """Jobs retry 3 times before the DLQ (TRD §8)."""
    assert WorkerSettings.max_tries == 3


def test_worker_registers_the_pipeline_and_its_crons() -> None:
    """A job that is written but never registered is a job that never runs — the
    reconciliation poller especially, since it is the guarantee of record (D-31)."""
    names = {f.__name__ for f in FUNCTIONS}
    assert {"ingest_engine_event", "run_post_call_pipeline"} <= names
    assert len(CRON_JOBS) >= 4


def test_shared_contracts_are_importable() -> None:
    """packages/shared resolves as an editable workspace dependency."""
    assert VoiceEngine is not None
    assert CallEvent.model_fields.keys() >= {"call_id", "engine", "engine_agent_ref"}


def test_call_event_does_not_require_a_tenant_an_adapter_cannot_know() -> None:
    """An adapter parses a VENDOR payload, which carries no tenant of ours. Requiring
    tenant_id here would push adapters toward inventing one (hard rule 1)."""
    assert CallEvent.model_fields["tenant_id"].default is None
    assert CallEvent.model_fields["agent_id"].default is None


def test_transcript_turn_defaults_to_no_redaction() -> None:
    """text_redacted is populated by the pipeline, never assumed present."""
    turn = TranscriptTurn(call_id="c1", idx=0, speaker="caller", text="hello")
    assert turn.text_redacted is None
