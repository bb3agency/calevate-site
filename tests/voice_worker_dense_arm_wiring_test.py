"""The dense retrieval arm is REACHABLE, not merely built.

THE DEFECT THIS PINS. `voice_worker/embedding.py` implements the hybrid arm, `knowledge.py`
gates it, `pipeline.assemble_call`, `session.open_session` and `runtime.WorkerRuntime` all
thread an `embedder` through — and NOTHING IN THE CONTAINER EVER CONSTRUCTED ONE. Every
production path defaulted it to `None`, so `GeminiQueryEmbedder` existed only where a test
instantiated it, and the measured difference it buys — **0.083 recall@1 on Telugu script
against 0.9583** (`tests/voice_worker_hybrid_test.py:17`) — was unreachable on every real
call. "A route nobody mounted, a job nobody registered" is the shape CLAUDE.md names; this
was its fifth form, AN ARM NOBODY BUILT AN ENCODER FOR.

WHY THE ASSERTIONS ARE ON THE BOOTSTRAP AND NOT ON THE RANKING. What the arm DOES once it
has an encoder is proved by `tests/voice_worker_hybrid_test.py`; what those tests cannot see
is whether a container ever hands one over. This file asserts that seam in both directions —
a container with a Google credential has the arm, one without has the complete off state —
and that the arm's failure stays inside the turn.

Run: uv run pytest -q tests/voice_worker_dense_arm_wiring_test.py
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from tests.voice_worker_pipeline_test import (
    CREDENTIALS,
    FakeTransport,
    RecordingSink,
    make_config,
)
from voice_worker import boot, runtime, session
from voice_worker.embedding import EMBEDDING_DIMS, EMBEDDING_MODEL, GeminiQueryEmbedder

#: The boot gate's full environment MINUS any Google credential, so each test says in one
#: line which container it is describing.
ENV_WITHOUT_GOOGLE: dict[str, str] = {
    "PIPECAT_WORKER_API_BASE_URL": "https://api.calevate.tech",
    "PIPECAT_WORKER_API_TOKEN": "a-token-this-deployment-issued-its-worker",
    "OBJECT_STORE_BUCKET": "calevate-prod",
    "OBJECT_STORE_ENDPOINT": "https://account.r2.cloudflarestorage.com",
    "AWS_ACCESS_KEY_ID": "key",
    "AWS_SECRET_ACCESS_KEY": "secret",
    "SARVAM_API_KEY": "sarvam",
    "PLIVO_AUTH_ID": "plivo-id",
    "PLIVO_AUTH_TOKEN": "plivo-token",
    "AZURE_OPENAI_API_KEY": "azure",
}

ENV_WITH_GOOGLE: dict[str, str] = {**ENV_WITHOUT_GOOGLE, "GEMINI_API_KEY": "google"}


def _install(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    """Make this process's environment the container's.

    `ObjectStorePackFetcher.from_env` and `WorkerRuntime.from_env` both read `os.environ`
    rather than take a mapping, so a test that only built a `WorkerConfig` would be
    describing a container the bootstrap cannot actually open.
    """
    for name in (*ENV_WITH_GOOGLE, "AWS_REGION"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)


async def _open(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> boot.WorkerRuntime:
    """The production bootstrap, with the one probe that needs a network turned off.

    `verify=False` is the whole of the difference from what `bot.py:130` runs: it skips
    `api.probe()`, which is a round trip to a host no test may depend on, and skips nothing
    that decides what this container holds.
    """
    _install(monkeypatch, env)
    return await boot.open_runtime(boot.load_worker_config(), verify=False)


async def test_a_container_with_a_google_credential_has_the_dense_arm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE DEFECT, as it was: this was `None`, on every container, for every call.

    Asserted down to the CALL RUNNER and not only to the runtime object, because the runner
    is what `run_call` reads — a bootstrap that stored the embedder on the dataclass and
    passed `None` to `CallRunner` would look wired and answer every turn lexically.
    """
    opened = await _open(monkeypatch, ENV_WITH_GOOGLE)
    try:
        assert isinstance(opened.embedder, GeminiQueryEmbedder), (
            "a container holding GEMINI_API_KEY must build the dense arm: without it a "
            "Telugu-script question scores 0.083 recall@1 against 0.9583"
        )
        # The pack's encoder and the worker's must be one pair or `DenseIndex.usable_with`
        # refuses every comparison and the arm is wired to nothing.
        assert opened.embedder.model == EMBEDDING_MODEL
        assert opened.embedder.dimensions == EMBEDDING_DIMS
        assert opened.calls._embedder is opened.embedder
    finally:
        await opened.aclose()


async def test_a_container_without_one_is_cleanly_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The off state is a container with no credential, and it must be COMPLETE.

    Not a fallback and not a degradation: no embedder means `SessionKnowledge.answer` is
    exactly `search`, so there is no request, no budget and no spend — which is what a
    deployment whose embedding price nobody attested has to run (hard rule 7).
    """
    opened = await _open(monkeypatch, ENV_WITHOUT_GOOGLE)
    try:
        assert opened.embedder is None
        assert opened.calls._embedder is None
    finally:
        await opened.aclose()


async def test_closing_the_container_releases_the_encoder_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pool this process opened is a pool this process closes.

    The embedder deliberately does not share `WorkerApiClient`'s pool (that one is sized
    against our own API and this budget is a model provider's), so it is the one connection
    pool that would otherwise leak past a container's last call. It OWNS that pool, so the
    container asks it to release rather than reaching into a transport it never opened —
    which is also what keeps `httpx` out of `boot` and `runtime` and the one-door rule in
    `voice_worker_sink_test` honest.
    """
    opened = await _open(monkeypatch, ENV_WITH_GOOGLE)
    embedder = opened.embedder
    assert isinstance(embedder, GeminiQueryEmbedder)
    await opened.aclose()

    assert embedder._client.is_closed


def test_both_production_constructors_agree(monkeypatch: pytest.MonkeyPatch) -> None:
    """`boot.open_runtime` and `runtime.WorkerRuntime.from_env` are two doors onto one
    container, and a container that has the arm through one and not the other is the drift
    the quality bar refuses. They reach the same builder, so this pins that they do."""
    _install(monkeypatch, ENV_WITH_GOOGLE)
    built = runtime.WorkerRuntime.from_env()

    assert isinstance(built._embedder, GeminiQueryEmbedder)


def test_the_off_state_is_the_absent_credential_and_not_a_silent_default() -> None:
    """`build_query_embedder` is the ONE gate, and it reads the LLM leg's own key.

    Pinned because the failure it prevents is invisible: a second spelling of the variable
    — `GOOGLE_API_KEY`, `GEMINI_KEY` — would leave a fully credentialed container running
    the lexical arm with nothing anywhere saying so.
    """
    assert boot.LLM_KEY_ENV_BY_PROVIDER[boot.GOOGLE_LLM_PROVIDER] == "GEMINI_API_KEY"

    config = boot.load_worker_config(ENV_WITHOUT_GOOGLE)
    assert boot.build_query_embedder(config) is None

    embedder = boot.build_query_embedder(boot.load_worker_config(ENV_WITH_GOOGLE))
    assert isinstance(embedder, GeminiQueryEmbedder)


class _NullFetcher:
    """No pack. The arm is threaded either way; what is under test is the threading."""

    async def fetch(self, object_key: str) -> bytes | None:
        return None


async def test_an_encoder_outage_is_a_turn_the_agent_can_speak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wiring the arm must not put a new way for a turn to FAIL on the call path.

    Through the production embedder class against a transport that 500s: `embed` answers
    `None` rather than raising, so the turn ends in a `RetrievalOutcome` the agent has a
    sentence for. An exception here would reach `pipeline._search` as "the function failed
    and returned no result" — no outcome word, and a model free to improvise about a
    client's business.
    """

    def _refuse(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "upstream"})

    embedder = GeminiQueryEmbedder(
        client=httpx.AsyncClient(transport=httpx.MockTransport(_refuse)),
        api_key="google",
    )
    call: Any = await session.open_session(
        config=make_config(),
        credentials=CREDENTIALS,
        transport=FakeTransport(),
        sink=RecordingSink(),
        fetcher=_NullFetcher(),
        embedder=embedder,
    )
    assert call is not None
    assert await embedder.embed("ఈ రోజు ఎన్ని గంటల వరకు తెరిచి ఉంటుంది?") is None
