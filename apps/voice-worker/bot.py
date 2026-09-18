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

**WHAT IS COMPLETE HERE.** The boot gate, the process-scoped runtime, admission control,
the readiness state, the normalized event writer, and the shutdown that settles or records
every in-flight leg. ⚠ **THIS SECTION USED TO LIST THE EVENT WRITER AS A NAMED REFUSAL —
TWICE, THE SECOND A COPY-PASTE OF THE FIRST.** `boot.build_event_sink` raised
`EventSinkNotBuiltError` and this container could not serve a call at all; D-621 built it
(`sink.HttpEventSink`, posting to `/v1/worker`), so the refusal and the duplicate line are
gone together.

**`resolve_call_identity` IS NOW BUILT (D-610)** and it is the second half of one design:
the answer document `apps/voice-runtime/carrier_routes.py` serves puts the agent ref in
the stream URL's path, and this reads it back off the socket the carrier connected to.
The route is the URL and NEVER the dialled number (D-603, hard rule 1) — resolving a
number before its tenant is known would be a cross-tenant read, and Pipecat's Plivo parser
leaves `from`/`to` `None` anyway. What still waits on the Plivo account (BLOCKER-1) is
configuration: the carrier credentials `create_transport` reads, a number, and
`PIPECAT_STREAM_BASE_URL`.

So this container still refuses to serve a call it cannot record, loudly, at the first
thing it cannot do — the boot gate now proves the platform API answers AND accepts this
container's token before `container()` returns (`boot.open_runtime`, `verify`). That is
deliberate: the alternative shapes — a sink that discards, an identity invented from the
dialed number — both produce a container that answers the phone and lies about what happened
on it.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from typing import Any, Final
from urllib.parse import unquote
from uuid import UUID

from calevate_shared.events import CallDirection
from loguru import logger
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams
from uuid_utils.compat import uuid7
from voice_worker.boot import (
    WorkerConfig,
    WorkerRuntime,
    load_worker_config,
    open_runtime,
)
from voice_worker.carrier import UnroutableCallError, route_of
from voice_worker.lifecycle import ReadinessFile, SessionRegistry, ShutdownSignal

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


#: The direction of every call this entrypoint can serve today.
#:
#: A CONSTANT RATHER THAN SOMETHING READ OFF THE WIRE, and it is honest rather than lazy:
#: the only way a media stream reaches this process is a carrier answering a ringing
#: number, because the request that PLACES a call is UNKNOWN here and refuses by name
#: (`carrier.OUTBOUND_DIAL_UNKNOWN`). Nothing on the Plivo handshake distinguishes the two
#: directions either (`runner/utils.py:257-262` maps two fields and neither is one), so a
#: value "read" from the wire would be this constant wearing a lookup. When the dial is
#: written it will carry its own direction into the session, exactly as
#: `carrier.start_carrier_call` already takes one.
INBOUND: Final[CallDirection] = "inbound"


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
            # `open_runtime` PROVES the platform API answers this container's token before
            # anything is marked started. That is where "a container with nowhere to write a
            # transcript must not answer a phone" now lives: the sink itself is built per
            # call (it holds one session's four ids), so there is nothing to build at boot —
            # what there is to prove is that the far end is reachable, and `verify` proves it.
            _runtime = await open_runtime(resolved)
            _registry = SessionRegistry(marker=ReadinessFile(resolved.ready_file))
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


def _route_token(runner_args: RunnerArguments) -> str:
    """The last path segment of the URL the carrier connected to, or a refusal.

    **THE TOKEN IS IN THE URL BECAUSE WE PUT IT THERE.** `apps/voice-runtime/
    carrier_routes.py` mints the stream URL with the agent ref as a path segment — the
    form Pipecat's own runner recommends for telephony providers
    (`runner/run.py:1410-1414`), and the one its own `/ws/{token}` route reads
    (`:1480-1483`) — so reading it back here is the other half of one design, not a guess
    about a vendor field.

    ⚠ **UNKNOWN: whether Pipecat Cloud preserves the PATH of the socket it terminates.**
    `docs.pipecat.ai` is egress-blocked from this container, and the platform hands the bot
    a `WebSocketRunnerArguments` with nothing but the socket (`runner/run.py:538`). If the
    path is rewritten, THIS REFUSES — loudly, with a sentence naming the unknown — and no
    call is answered by a guessed agent. That is the safe direction of being wrong, and it
    is the reason no fallback to `call_data.to_number` exists: hard rule 1 (D-603) forbids
    resolving a number before its tenant is known, so the fallback would be the failure.
    """
    websocket = getattr(runner_args, "websocket", None)
    if websocket is None:
        raise UnroutableCallError(
            "this session carries no WebSocket, so there is no stream URL to read an "
            "agent ref from (docs/PIPECAT-MIGRATION.md §6 step 6)"
        )
    path = str(getattr(getattr(websocket, "url", None), "path", "") or "")
    token = unquote(path.rsplit("/", 1)[-1])
    if not token:
        raise UnroutableCallError(
            "the carrier connected to a stream URL with no path segment, so it names no "
            "agent (UNKNOWN: whether Pipecat Cloud preserves the socket's URL path)"
        )
    return token


async def resolve_call_identity(
    runner_args: RunnerArguments,
) -> tuple[str, UUID, UUID, CallDirection]:
    """(our call_id, tenant, agent, direction) for the session on the wire.

    **OUR `call_id` IS MINTED HERE AND READ FROM NOWHERE** (§1.2). The carrier's CDR is
    the authority on the FACTS of a call and our worker on its CONTENT, and the
    reconciliation only works if the two ids are independent: an id taken from the
    carrier's handshake would make our record a copy of theirs rather than a second
    witness. `uuid7` so the id sorts by time, which is what every other id in this tree
    does (`sink.py` mints the call ref from it).

    `async` although nothing here awaits: this is the seam a future outbound path enters
    through, and a caller that has already written `await` does not have to be edited when
    it does. Changing it back would be a change to `bot()` for no behaviour.
    """
    route = route_of(_route_token(runner_args))
    return str(uuid7()), route.tenant_id, route.agent_id, INBOUND


async def bot(runner_args: RunnerArguments) -> None:
    """One session, start to finish. The signature is the platform's.

    **THE AGENT REF IS READ OFF THE SOCKET ONCE AND USED TWICE** — `resolve_call_identity`
    parses it into ids, and `load_session_config` presents the ref itself to the platform API,
    which resolves the tenant from it and reads under that tenant's RLS (D-621). Both come
    from the same `_route_token`, so a call cannot be routed as one agent and configured as
    another; `load_session_config` refuses the mismatch anyway, because a check that costs a
    comparison should not rest on two call sites staying in step.

    ⚠ **THIS FUNCTION USED TO ASSEMBLE THE CALL ITSELF, AND THAT SECOND COPY OF
    `runtime.WorkerRuntime.run_call` IS WHY THE FIRST REAL CALL WOULD HAVE BEEN LOST
    (found 18 Sep 2026).** The copy built the sink and the session but built no `CallMeter`,
    passed no `observers=`, never called `sink.settle(...)` and never called
    `sink.aclose()`. On this engine the settlement is the ONLY producer of the post-call
    outbox row — there is no poller behind it (`worker/service.py:540-560`) — so every call
    would have ended with no extraction, no CRM columns and no lead, silently and for ever,
    plus one leaked flush task per call. It survived review because the tested path
    (`tests/voice_worker_runtime_test.py`) was not the shipped one.

    So the assembly lives in ONE place now and this is a thin entrypoint over it: ids, the
    transport the platform handed us, and the slot. `credentials_for` is passed as a
    FUNCTION because which vendor key this call spends is decided by the agent's own
    `ModelConfig.llm_provider`, which is read inside `run_call`; resolving it out here is
    what forced the duplicate in the first place.
    """
    runtime, registry = await container()
    engine_agent_ref = _route_token(runner_args)
    call_id, tenant_id, agent_id, direction = await resolve_call_identity(runner_args)

    # THE SLOT IS TAKEN BEFORE ANY IO, and that ordering is the fix rather than a tidy-up.
    # This used to admit only after the transport, the session read and the whole pipeline
    # existed — two network round trips during which the readiness marker still said
    # `ready`, so a one-session container could be handed a second call whose caller then
    # met `AtCapacityError` with a transport and a sink already built and nothing to close
    # them. Refusing costs that caller nothing now.
    registry.reserve(call_id)
    try:
        transport = await create_transport(runner_args, _TRANSPORT_PARAMS)
        await runtime.calls.run_call(
            call_id=call_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
            direction=direction,
            engine_agent_ref=engine_agent_ref,
            credentials_for=runtime.config.credentials_for,
            transport=transport,
            on_assembled=lambda call: registry.attach(call_id, call),
        )
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
