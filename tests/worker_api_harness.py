"""The two halves of D-621's wire, joined in one process so a test can drive both.

**WHY THIS IS A HELPER MODULE AND NOT PART OF `worker_api_test.py`.** Four test files need
it — the API routes, the worker's sink, the session read and the carrier path — and the
worker-side ones are also where `worker_api_test` gets its own fixtures from
(`_agent_config`, `_tenant_with_published_agent`). Keeping the harness here is what breaks
that cycle; `ack_harness.py` and `voice_fixture.py` are the same shape in this suite.

The `worker_token` fixture that configures the server side of this pair lives in
`tests/conftest.py`, where its own docstring says why: a fixture with six consumers is one
tests should be able to take as a parameter without importing a name ruff then calls a
redefinition.

**THE CLIENT IS THE REAL ONE AND THE SERVER IS THE REAL APP**, joined by
`httpx.ASGITransport`: no socket, no mock, no second implementation of either half. That is
the only arrangement that proves the property a contract split across two deployables
actually has — that the two ENDS agree, on the same `calevate_shared.worker_api` models, the
same routes, the same Bearer check and the same RLS. A mocked transport would prove only
that one end is self-consistent.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import httpx
import pytest
from apps.api.core.settings import get_settings
from apps.api.main import app as api_app
from calevate_shared.engine import pipecat_call_ref
from voice_worker.api_client import WorkerApiClient

#: The credential this deployment issued its own worker. A literal, because `conftest.
#: _no_ambient_credentials` strips the real ones and because "no token configured" is itself
#: one of the behaviours under test.
TOKEN = "a-token-this-deployment-issued-its-worker"


def declare_pipecat_engine(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Configure this deployment as one that RUNS the engine the worker writes for (D-627).

    **A HELPER RATHER THAN A FIXTURE IN `conftest`, AND THE REASON IS MEASURED.** The three
    MUTATING `/v1/worker` routes answer 409 on a deployment whose `ENGINE` is something else,
    because everything they write is reconciled by the process-wide engine and
    `workers/pipeline._post_call_target` never reads the engine the settlement names in its
    own payload. Folding this into `worker_token` would set `ENGINE=pipecat` for every file
    that fixture reaches — including the ones whose agents are minted by the FAKE engine and
    then published through `kb/service.publish_source`, which on the Pipecat adapter re-enters
    `tenant_session` from inside the caller's transaction and blocks on its own `agents` lock.
    That is a real defect in `engine/pipecat._PipecatStore.publish` and it is not this seam's
    to fix; what it means here is that only the files that actually WRITE through these routes
    may declare the engine.

    A generator so the caller's own autouse fixture can `yield from` it and the settings cache
    is cleared on both sides — `conftest.worker_token`'s shape, for its reason.
    """
    monkeypatch.setenv("ENGINE", "pipecat")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def worker_client(token: str = TOKEN) -> WorkerApiClient:
    """The real client against the real app, in process, over ASGI.

    `from_config` rather than the injecting constructor, so the client OWNS its pool and
    `async with` really closes it — see `WorkerApiClient.from_config`, where the `transport`
    seam is declared for exactly this caller.
    """
    return WorkerApiClient.from_config(
        base_url="http://api",
        token=token,
        transport=httpx.ASGITransport(app=api_app, client=("127.0.0.1", 44444)),
    )


async def published_agent() -> tuple[uuid.UUID, uuid.UUID, str]:
    """A tenant whose agent has the runtime row a real call starts from, and its ref.

    `PipecatEngine.create_agent` is what mints `agent_config_versions` and `pipecat_agents`,
    so the rows under test are the ones the control plane really writes rather than ones a
    test inserted in the shape it hoped for.

    The imports are INSIDE the function on purpose: this module is imported by the same test
    files it borrows those fixtures from, and a module-level import would reintroduce the
    cycle this module exists to break.
    """
    from apps.api.engine.pipecat import PipecatEngine, engine_agent_ref_for
    from tests.kb_workflow_test import _tenant_with_published_agent
    from tests.voice_worker_session_test import _agent_config

    tenant_id, agent_id = await _tenant_with_published_agent()
    tenant_id, agent_id = uuid.UUID(str(tenant_id)), uuid.UUID(str(agent_id))
    await PipecatEngine().create_agent(_agent_config(tenant_id, agent_id))
    return tenant_id, agent_id, engine_agent_ref_for(str(tenant_id), str(agent_id))


def call_ref(tenant_id: uuid.UUID) -> tuple[str, str]:
    """`(our call id, the engine-space ref)` — the pair `sink.HttpEventSink` mints.

    The ref is what the worker addresses a call by and the only handle it ever sends: the
    server parses the tenant back out of it (`tenant_of_pipecat_ref`) and reads under that
    tenant's RLS, which is what lets a worker address a call without holding a `calls.id`.
    """
    call_id = f"call-{uuid.uuid4().hex[:10]}"
    return call_id, pipecat_call_ref(tenant_id, call_id)


__all__ = ["TOKEN", "call_ref", "declare_pipecat_engine", "published_agent", "worker_client"]
