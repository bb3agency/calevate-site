"""The container entrypoint Pipecat Cloud runs: one process, one call at a time.

**WHY THIS FILE IS AT THE DEPLOYABLE'S ROOT AND IS CALLED `bot.py`.** That is the
platform's convention, not ours, and it is the one thing in this tree named by a vendor:
the scaffold's own Dockerfile ends `COPY ./bot.py bot.py` and its bot module is
`async def bot(runner_args: RunnerArguments)` with a `main()` beside it
(`pipecat/cli/templates/server/Dockerfile.jinja2` and
`cli/templates/server/bot_cascade.py.jinja2:74,131-134`, shipped inside the pinned
`pipecat-ai==1.10.0` and read 15 Sep 2026). Nothing configures that name —
`pcc-deploy.toml` carries an agent name, a secret set, a profile and a scaling floor, and
no entrypoint — so the file is spelled the way the vendor's own tooling spells it.
⚠ **WHETHER THE BASE IMAGE REQUIRES EXACTLY THIS NAME IS UNVERIFIED**: `docs.pipecat.ai`
is egress-blocked here and `dailyco/pipecat-base` cannot be pulled through this
environment's proxy, so the convention is followed rather than proved.

It is a TOP-LEVEL module on `sys.path`, which `voice_worker/__init__.py` warns about for
`apps/voice-runtime`'s generic names (`main`, `config`). `bot` collides with nothing in
this tree today, and the collision that docstring is about is between two deployables'
INTERNAL modules; this one is a name the platform chose.

**WHAT IS COMPLETE HERE AND WHAT IS NOT.** Complete: the boot gate, the process-scoped
runtime, admission control, the readiness state, and the shutdown that settles or records
every in-flight leg. Not complete, each as a NAMED refusal rather than a silent hole:

  * the normalized event writer (`boot.build_event_sink`) — §6 step 11's next wave;
  * turning a ringing number into a tenant, an agent and OUR `call_id`
    (`resolve_call_identity`) — §6 step 6, gated on the Plivo account (BLOCKER-1).

So this container refuses to serve a call today, loudly, at the first thing it cannot do.
That is deliberate: the alternative shapes — a sink that discards, an identity invented
from the dialed number — both produce a container that answers the phone and lies about
what happened on it.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from typing import Any, Final
from uuid import UUID

from calevate_shared.events import CallDirection
from loguru import logger
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams
from pipecat.workers.runner import WorkerRunner
from voice_worker.boot import (
    WorkerConfig,
    WorkerRuntime,
    build_event_sink,
    load_worker_config,
    open_runtime,
    tenant_connection,
)
from voice_worker.config import load_session_config
from voice_worker.lifecycle import ReadinessFile, SessionRegistry, ShutdownSignal
from voice_worker.session import open_session

#: The transport parameter factories `create_transport` selects from by provider. Only the
#: legs this product has: Plivo is the carrier (D-592, §6 step 6) and `websocket` is what a
#: local run without a carrier gets. A key for a provider we do not use would be a
#: transport somebody could reach by accident.
#:
#: `audio_in_enabled` / `audio_out_enabled` are the two the telephony path needs; the
#: serializer and `add_wav_header` are set by `create_transport` itself
#: (`pipecat/runner/utils.py:486-553`), which is why they are absent here.
_TRANSPORT_PARAMS: Final[dict[str, Callable[[], Any]]] = {
    "plivo": lambda: FastAPIWebsocketParams(audio_in_enabled=True, audio_out_enabled=True),
    "websocket": lambda: TransportParams(audio_in_enabled=True, audio_out_enabled=True),
}

#: Process-scoped, built once, guarded by a lock because the platform may — and we cannot
#: verify that it does not — start a session before a previous one's boot has finished.
_runtime: WorkerRuntime | None = None
_registry: SessionRegistry | None = None
_shutdown: Final[ShutdownSignal] = ShutdownSignal()
_runtime_lock: asyncio.Lock | None = None
_drain_task: asyncio.Task[None] | None = None


class CallRoutingNotBuiltError(RuntimeError):
    """We cannot say whose call this is, so we will not answer it.

    The Plivo handshake gives us the carrier's identifiers and the two numbers
    (`CallData.call_id`, `.to_number`, `.from_number`); it cannot give us a tenant, an
    agent or OUR `call_id`, which §1.2 makes ours precisely so the CDR is reconciled
    AGAINST it rather than being its source. The lookup that turns a dialed number into
    those three is §6 step 6 and is gated on the Plivo account (BLOCKER-1).

    Refusing is the only safe branch: an agent picked by a guess would run one client's
    prompt on another client's caller, which is the failure hard rule 1 exists for.
    """


async def container(config: WorkerConfig | None = None) -> tuple[WorkerRuntime, SessionRegistry]:
    """This process's runtime and registry, opened once.

    **THE BOOT GATE RUNS HERE AND NOT AT IMPORT, AND THE REASON IS AN UNKNOWN RATHER THAN
    A PREFERENCE.** Failing at import would be the loudest possible boot failure, and it is
    effectively what `main()` does for every run we control. But whether the platform's
    base image imports this module when the CONTAINER starts or when the first SESSION
    arrives is not something this repository can verify (`docs.pipecat.ai` is
    egress-blocked), and a module that raised at import would, under the second reading,
    turn a configuration fault into a failed call rather than a failed deploy. So the gate
    lives in a function both paths call, and `bot.py --preflight` is the command that
    proves an image before any caller meets it.
    """
    global _runtime, _registry, _runtime_lock, _drain_task
    if _runtime_lock is None:
        _runtime_lock = asyncio.Lock()
    async with _runtime_lock:
        if _runtime is None or _registry is None:
            resolved = config or load_worker_config()
            _runtime = await open_runtime(resolved)
            _registry = SessionRegistry(marker=ReadinessFile(resolved.ready_file))
            # The sink is built at BOOT, not per call: a container with nowhere to write a
            # transcript must not answer a phone. See `boot.EventSinkNotBuiltError`.
            build_event_sink(_runtime.engine)
            _shutdown.install()
            _drain_task = asyncio.create_task(_drain_on_signal())
            _registry.mark_started()
            logger.info("voice worker ready", state=_registry.status().state)
    return _runtime, _registry


async def _drain_on_signal() -> None:
    """The container's answer to SIGTERM, running for the life of the process.

    A BACKGROUND TASK RATHER THAN A `main()` LOOP, because on Pipecat Cloud the process
    belongs to the platform: nothing of ours is sitting at the top of the stack waiting to
    be told to stop. Without this, the only SIGTERM handler in the process would be the
    one `WorkerRunner` installs — which cancels (`lifecycle.ShutdownSignal` argues it) —
    or none at all, and the default disposition for SIGTERM is to die where you stand.
    """
    await _shutdown.wait()
    if _runtime is None or _registry is None:  # pragma: no cover - installed after both
        return
    report = await _registry.drain(_runtime.config.drain_grace_s)
    logger.info("voice worker drained", settled=report.settled, cut=len(report.cut))


async def resolve_call_identity(
    runner_args: RunnerArguments,
) -> tuple[str, UUID, UUID, CallDirection]:
    """(our call_id, tenant, agent, direction) for the session on the wire. Not built."""
    raise CallRoutingNotBuiltError(
        "no route from a dialed number to a tenant and an agent exists yet "
        "(docs/PIPECAT-MIGRATION.md §6 step 6, BLOCKER-1: a Plivo account in the India "
        f"data region). Session {runner_args.session_id!r} refused."
    )


async def bot(runner_args: RunnerArguments) -> None:
    """One session, start to finish. The signature is the platform's.

    **THE CONFIGURATION IS READ BEFORE THE CREDENTIAL IS CHOSEN, AND THAT IS WHY THIS USES
    `load_session_config` + `open_session` RATHER THAN `start_session`.** Which LLM key
    this call spends is decided by the agent's own `ModelConfig.llm_provider`, which is in
    the config version and nowhere else — so `credentials_for` has to run after the read.
    `session.start_session` exists for callers that already know; this one does not, and
    guessing would mean sending a client's caller's words to a vendor their agent does not
    name.
    """
    runtime, registry = await container()
    call_id, tenant_id, agent_id, direction = await resolve_call_identity(runner_args)

    transport = await create_transport(runner_args, _TRANSPORT_PARAMS)
    async with tenant_connection(runtime.engine, tenant_id) as connection:
        config = await load_session_config(
            connection,
            call_id=call_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
            direction=direction,
        )
    call = await open_session(
        config=config,
        credentials=runtime.config.credentials_for(config.models.llm_provider),
        transport=transport,
        sink=build_event_sink(runtime.engine),
        fetcher=runtime.fetcher,
        embedder=runtime.embedder,
    )

    registry.admit(call_id, call)
    try:
        # `handle_sigterm=False` IS THE POINT AND IS ARGUED IN `lifecycle.ShutdownSignal`:
        # the runner's own SIGTERM handler cancels rather than drains, which cuts the
        # caller off mid-sentence and leaves the carrier leg running.
        runner = WorkerRunner(handle_sigint=False, handle_sigterm=False)
        await runner.add_workers(call.worker)
        await runner.run()
    finally:
        registry.release(call_id)


async def _preflight() -> int:
    """Prove this image's configuration without taking a call. Prints, never raises."""
    try:
        runtime, registry = await container()
    except Exception as exc:
        print(f"VOICE WORKER PREFLIGHT: FAIL\n  - {exc}")
        return 1
    try:
        status = registry.status()
        print(
            f"VOICE WORKER PREFLIGHT: OK ({status.state}, "
            f"{status.in_flight}/{status.capacity} sessions, "
            f"llm legs {sorted(runtime.config.llm_api_keys)})"
        )
        return 0
    finally:
        await runtime.aclose()


def main() -> None:
    """Local entry point. `--preflight` proves the configuration and exits.

    Without the flag this hands off to Pipecat's own development runner, which is what
    `docs/PIPECAT-MIGRATION.md` §6 step 4 means by "a local run against a fake transport".
    """
    if "--preflight" in sys.argv:
        raise SystemExit(asyncio.run(_preflight()))
    from pipecat.runner.run import main as runner_main

    runner_main()


if __name__ == "__main__":
    main()
