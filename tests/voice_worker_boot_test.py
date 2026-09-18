"""The container contract: what the worker refuses to start without, and how it goes away.

Three properties, and each one is a production failure this suite makes cheap to have an
opinion about:

1. **The boot gate refuses, once, naming everything.** A container missing three variables
   must not teach an operator about them one deploy at a time.
2. **Readiness is admission control.** One session per instance (evidence:122), so a
   container carrying a call is healthy and unavailable, and the same object must say both.
3. **A shutdown settles or RECORDS every in-flight leg.** A call cut by a deploy that
   leaves an `in_progress` row and no terminal event is a call the post-call pipeline waits
   on for ever — money and a lie in the record.

No database and no network: `load_worker_config` takes a mapping and the drain path is
exercised against a fake worker, which is what `AssembledCall`'s narrow surface (a
`PipelineWorker` and a `NormalizedEventBoundary`) makes possible.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from calevate_shared.engine import ModelConfig
from calevate_shared.events import CallEvent, TranscriptTurn
from voice_worker import boot, lifecycle
from voice_worker.pipeline import AssembledCall, NormalizedEventBoundary, SessionConfig

PROMPT = "You are Calevate's receptionist. You are an AI. This call is recorded."

COMPLETE_ENV: dict[str, str] = {
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


class RecordingSink:
    """Everything that crossed the boundary, and the type check that it was ours."""

    def __init__(self) -> None:
        self.events: list[CallEvent] = []
        self.turns: list[TranscriptTurn] = []

    async def on_call_event(self, event: CallEvent) -> None:
        assert type(event) is CallEvent
        self.events.append(event)

    async def on_transcript_turn(self, turn: TranscriptTurn) -> None:  # pragma: no cover
        self.turns.append(turn)


class FakeWorker:
    """A `PipelineWorker` as far as the drain is concerned: end it, ask if it finished.

    `finishes_on_end=False` is the container being replaced during a turn that will not
    drain in time — the case the whole shutdown path exists for.
    """

    def __init__(self, *, finishes_on_end: bool = True) -> None:
        self.finishes_on_end = finishes_on_end
        self.ended = False
        self.cancelled_with: str | None = None

    async def stop_when_done(self) -> None:
        self.ended = True

    def has_finished(self) -> bool:
        return self.ended and self.finishes_on_end

    async def cancel(self, *, reason: str | None = None) -> None:
        self.cancelled_with = reason


def make_session_config(call_id: str = "call-1") -> SessionConfig:
    return SessionConfig(
        call_id=call_id,
        tenant_id=uuid4(),
        agent_id=uuid4(),
        agent_config_version_id=uuid4(),
        direction="inbound",
        system_prompt=PROMPT,
        prompt_sha256="not-checked-here",
        models=ModelConfig(llm_provider="google", llm_model="gemini-2.5-flash-lite"),
    )


def make_call(sink: RecordingSink, *, call_id: str, finishes_on_end: bool = True) -> Any:
    """An `AssembledCall`-shaped object carrying a REAL boundary over a real sink.

    The boundary is not faked: the claim under test is that a cut call produces a genuine
    terminal `CallEvent`, and a fake boundary would let this suite pass while the real one
    emitted nothing.
    """
    boundary = NormalizedEventBoundary(config=make_session_config(call_id), sink=sink)
    return cast(
        AssembledCall,
        type(
            "FakeAssembledCall",
            (),
            {"worker": FakeWorker(finishes_on_end=finishes_on_end), "boundary": boundary},
        )(),
    )


# --------------------------------------------------------------------------------------
# 1. The boot gate
# --------------------------------------------------------------------------------------


def test_a_complete_environment_loads_with_the_documented_defaults() -> None:
    config = boot.load_worker_config(COMPLETE_ENV)
    assert config.llm_api_keys == {"azure_openai": "azure"}
    assert config.cartesia_api_key is None
    assert config.drain_grace_s == boot.DEFAULT_DRAIN_GRACE_S
    assert config.ready_file is None


def test_an_empty_environment_names_every_missing_variable_at_once() -> None:
    """ONE refusal, not the first one. An operator filling a vendor secret set should not
    learn about eight variables across eight deploys."""
    with pytest.raises(boot.WorkerConfigError) as raised:
        boot.load_worker_config({})
    message = str(raised.value)
    for name in (
        boot.API_BASE_URL_ENV,
        boot.API_TOKEN_ENV,
        boot.AWS_KEY_ENV,
        boot.AWS_SECRET_ENV,
        boot.SARVAM_KEY_ENV,
        boot.PLIVO_AUTH_ID_ENV,
        boot.PLIVO_AUTH_TOKEN_ENV,
        "OBJECT_STORE_BUCKET",
        "OBJECT_STORE_ENDPOINT",
    ):
        assert name in message, f"{name} is required and the refusal did not name it"
    assert "AZURE_OPENAI_API_KEY" in message and "GEMINI_API_KEY" in message


@pytest.mark.parametrize("missing", sorted(COMPLETE_ENV))
def test_each_required_variable_is_individually_required(missing: str) -> None:
    """Non-vacuity for the clause above: every key in the complete set is load-bearing, so
    none of them is a line somebody can delete from the deploy without noticing."""
    env = {k: v for k, v in COMPLETE_ENV.items() if k != missing}
    with pytest.raises(boot.WorkerConfigError) as raised:
        boot.load_worker_config(env)
    assert missing in str(raised.value)


def test_a_blank_value_is_not_a_value() -> None:
    """A secret set filled with an empty string is the shape a copy-paste produces, and it
    must not read as configured."""
    with pytest.raises(boot.WorkerConfigError):
        boot.load_worker_config({**COMPLETE_ENV, "SARVAM_API_KEY": "   "})


@pytest.mark.parametrize("value", ["nonsense", "0", "-1"])
def test_an_unusable_drain_grace_is_refused(value: str) -> None:
    with pytest.raises(boot.WorkerConfigError) as raised:
        boot.load_worker_config({**COMPLETE_ENV, boot.DRAIN_GRACE_ENV: value})
    assert boot.DRAIN_GRACE_ENV in str(raised.value)


def test_credentials_follow_the_agents_provider_and_never_fall_back() -> None:
    """The one place a per-call provider meets a per-container key. A fallback here would
    send a client's caller's words to a vendor their agent does not name."""
    config = boot.load_worker_config({**COMPLETE_ENV, "GEMINI_API_KEY": "gemini"})
    assert config.credentials_for("google").llm_api_key == "gemini"
    assert config.credentials_for("azure_openai").llm_api_key == "azure"
    # Defaulted exactly as `pipeline._build_llm` defaults it, so the two cannot disagree
    # about which key an agent that named nothing spends.
    assert config.credentials_for(None).llm_api_key == "azure"

    with pytest.raises(boot.WorkerConfigError) as raised:
        config.credentials_for("openai")
    assert "OPENAI_API_KEY" in str(raised.value)


def test_an_unknown_provider_is_refused_with_the_legs_this_product_has() -> None:
    config = boot.load_worker_config(COMPLETE_ENV)
    with pytest.raises(boot.WorkerConfigError) as raised:
        config.credentials_for("anthropic")
    assert "azure_openai" in str(raised.value)


def test_the_event_sink_is_built_for_one_call_and_carries_that_call_s_four_ids() -> None:
    """⚠ **THIS CLAUSE USED TO ASSERT A REFUSAL** — `build_event_sink` raised
    `EventSinkNotBuiltError` because the normalized event writer did not exist, and its own
    docstring said "when the writer lands this test is what says so". It landed (D-621), so
    this is that replacement.

    What is asserted is the shape rather than the writing (`voice_worker_sink_test` owns
    that): the sink is built PER CALL, from the four ids of one session, because those four
    ids are what make the identity refusal possible at all. A process-wide sink would have to
    infer a turn's tenant from its call id — i.e. read it back out of the row it is about to
    write.
    """
    from voice_worker.sink import HttpEventSink

    client = cast(Any, object())
    sink = boot.build_event_sink(
        client,
        call_id="call-1",
        tenant_id=uuid4(),
        agent_id=uuid4(),
        direction="inbound",
    )
    assert isinstance(sink, HttpEventSink)


# ⚠ **`test_the_database_connect_bounds_match_the_module_they_were_copied_from` WAS HERE AND
# IS DELETED (D-621).** It pinned `boot._CONNECT_ARGS` to `apps/api/db/session._CONNECT_ARGS`
# so a copy could not rot. There is no copy any more and no database connection to bound:
# this container cannot reach our Postgres (`docs/DEPLOYMENT.md` §12.5 gate 6) and speaks HTTP
# to `apps/api` instead. The bounds that replaced them are `api_client.SESSION_FETCH_BUDGET_S`
# and `WRITE_BUDGET_S`, which are this worker's own and have nothing to be pinned to.


def test_a_container_is_not_ready_before_boot_finishes() -> None:
    registry = lifecycle.SessionRegistry()
    assert registry.status().state == "starting"
    assert not registry.status().ready


def test_one_call_makes_a_healthy_container_unavailable() -> None:
    """Not a bug and not a degradation: the platform runs one session per instance
    (`docs/evidence/engine-replacement-comet-2026-09-06.md:122`), so `busy` is the right
    answer and `ready` would invite a caller this container cannot serve."""
    sink = RecordingSink()
    registry = lifecycle.SessionRegistry()
    registry.mark_started()
    assert registry.status().state == "ready"

    registry.reserve("call-1")

    registry.attach("call-1", make_call(sink, call_id="call-1"))
    assert registry.status().state == "busy"
    with pytest.raises(lifecycle.AtCapacityError):
        registry.reserve("call-2")

        registry.attach("call-2", make_call(sink, call_id="call-2"))

    registry.release("call-1")
    assert registry.status().state == "ready"
    registry.release("call-1")  # idempotent: the drain path may have released it already


def test_the_readiness_marker_appears_and_disappears_with_the_state(tmp_path: Path) -> None:
    """Published as a FILE because a file needs no contract — Pipecat Cloud's probe shape
    is UNKNOWN and an invented HTTP endpoint would be a guess that looks like wiring."""
    marker = tmp_path / "nested" / "ready"
    registry = lifecycle.SessionRegistry(marker=lifecycle.ReadinessFile(marker))
    assert not marker.exists()

    registry.mark_started()
    assert marker.exists()

    registry.reserve("call-1")

    registry.attach("call-1", make_call(RecordingSink(), call_id="call-1"))
    assert not marker.exists(), "a busy container must not advertise itself as ready"

    registry.release("call-1")
    assert marker.exists()


def test_an_unwritable_marker_does_not_stop_a_container_that_can_answer_the_phone(
    tmp_path: Path,
) -> None:
    """The state is held correctly in memory either way; the file is a publication of it.
    Failing a boot over a probe file would be a worse outcome than a missing probe.

    The unwritable path is a marker configured UNDER a regular file, which is what a
    plausible typo in the deploy produces (`/app/ready/marker` where `/app/ready` is a
    file); `mkdir` answers `NotADirectoryError` and the container carries on."""
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("", encoding="utf-8")
    registry = lifecycle.SessionRegistry(marker=lifecycle.ReadinessFile(blocker / "ready"))
    registry.mark_started()
    assert registry.status().ready


# --------------------------------------------------------------------------------------
# 3. Shutdown settles or records every leg
# --------------------------------------------------------------------------------------


async def test_a_drain_ends_a_live_call_the_graceful_way() -> None:
    """`stop_when_done()` queues an `EndFrame`, which drains what is in flight and lets the
    transport close — on the Plivo leg that close is also the hang-up. A `cancel()` here
    would cut the socket and leave the carrier billing a leg nobody is on."""
    sink = RecordingSink()
    registry = lifecycle.SessionRegistry()
    registry.mark_started()
    call = make_call(sink, call_id="call-1")
    registry.reserve("call-1")

    registry.attach("call-1", call)

    report = await registry.drain(grace_s=1.0)

    assert call.worker.ended
    assert call.worker.cancelled_with is None
    assert report.settled == 1
    assert report.clean
    assert not registry.status().ready, "a drained container must never come back ready"


async def test_a_call_that_will_not_drain_is_recorded_before_it_is_cut() -> None:
    """THE REGRESSION THIS FILE EXISTS FOR. A call cut by a container swap that leaves an
    `in_progress` row and no terminal event is a call the post-call pipeline waits on for
    ever. The event is written BEFORE `cancel`, because cancel does not guarantee the
    pipeline's own `on_pipeline_finished` handler ever runs."""
    sink = RecordingSink()
    registry = lifecycle.SessionRegistry()
    registry.mark_started()
    call = make_call(sink, call_id="call-1", finishes_on_end=False)
    await call.boundary.call_started()
    registry.reserve("call-1")

    registry.attach("call-1", call)

    report = await registry.drain(grace_s=0.3)

    assert report.cut == ("call-1",)
    assert call.worker.ended, "the graceful end is still attempted first"
    assert call.worker.cancelled_with == "container shutdown"
    statuses = [event.status for event in sink.events]
    assert statuses == ["in_progress", "failed"], statuses
    assert sink.events[-1].ended_at is not None


async def test_draining_an_idle_container_is_a_no_op() -> None:
    registry = lifecycle.SessionRegistry()
    registry.mark_started()
    report = await registry.drain(grace_s=5.0)
    assert report.settled == 0
    assert report.clean


async def test_a_draining_container_refuses_a_new_call() -> None:
    """Readiness goes false FIRST, before anything is asked to stop, so no session is
    admitted into a container that is on its way out."""
    registry = lifecycle.SessionRegistry()
    registry.mark_started()
    await registry.drain(grace_s=0.1)
    assert registry.status().state == "draining"
    with pytest.raises(lifecycle.AtCapacityError):
        registry.reserve("call-9")

        registry.attach("call-9", make_call(RecordingSink(), call_id="call-9"))


# --------------------------------------------------------------------------------------
# 4. The variables this container reads are ones a person can find
# --------------------------------------------------------------------------------------


def _declared_env_names() -> set[str]:
    """Every environment variable name `boot` declares, DERIVED rather than retyped.

    A second list here would be the drift the registry exists to stop: the guard would go
    on passing about a name nobody reads while the one somebody added stayed invisible.
    """
    names = {
        value
        for name, value in vars(boot).items()
        if name.endswith("_ENV") and isinstance(value, str)
    }
    return names | set(boot.LLM_KEY_ENV_BY_PROVIDER.values())


def test_every_variable_this_container_reads_is_declared_where_someone_can_find_it() -> None:
    """`scripts/check_env_parity.py`'s third direction CANNOT SEE THIS MODULE, which is
    why this test exists rather than a note saying it is covered.

    That guard matches `os.getenv("LITERAL")` in the AST; `boot` reads through a `Mapping`
    argument with the name held in a constant, so the scan finds nothing and would print
    OK over a container full of undocumented configuration. The same question is asked
    here against the same registries, so a new `*_ENV` constant with no home fails a test
    instead of passing unnoticed.
    """
    from calevate_shared.config import Settings
    from scripts.check_env_parity import CONTAINER_ENV_KEYS, SDK_ENV_KEYS

    undeclared = sorted(
        name
        for name in _declared_env_names()
        if name.lower() not in Settings.model_fields
        and name not in CONTAINER_ENV_KEYS
        and name not in SDK_ENV_KEYS
    )
    assert not undeclared, (
        f"{undeclared} are read by apps/voice-worker and are neither Settings fields nor "
        "registered in scripts/check_env_parity.CONTAINER_ENV_KEYS with the reason they "
        "cannot be — config nobody can discover"
    )


def test_the_container_registry_carries_no_variable_the_worker_stopped_reading() -> None:
    """The other direction. A registry entry for a deleted variable is a paragraph of
    reasoning about nothing, and it is how the next reader learns to distrust the list."""
    from scripts.check_env_parity import CONTAINER_ENV_KEYS

    stale = sorted(set(CONTAINER_ENV_KEYS) - _declared_env_names())
    assert not stale, f"{stale} are registered as voice-worker config and nothing reads them"
