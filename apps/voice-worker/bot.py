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
number before its tenant is known would be a cross-tenant read, and neither carrier's
stream handshake names one anyway.

**THE TRANSPORT IS BUILT EXPLICITLY, NOT BY `create_transport`.** Pipecat's auto-selection
names a Vobiz socket "plivo" (`runner/utils.py:89-96`) and would hang it up through
Plivo's REST API with credentials this container must not hold. So the stream URL's
`carrier=` claim (or the worker's `CARRIER` setting) chooses the serializer, Pipecat's
detection only checks it, and `carrier.open_carrier_leg` builds the transport.

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
from typing import Final
from urllib.parse import unquote
from uuid import UUID

from calevate_shared.events import CallDirection
from loguru import logger
from pipecat.runner.types import RunnerArguments
from uuid_utils.compat import uuid7
from voice_worker.boot import (
    WorkerConfig,
    WorkerRuntime,
    load_worker_config,
    open_runtime,
)
from voice_worker.carrier import (
    UnroutableCallError,
    call_claim_from_stream_url,
    claim_from_stream_url,
    open_carrier_leg,
    route_of,
)
from voice_worker.lifecycle import ReadinessFile, SessionRegistry, ShutdownSignal

#: Process-scoped, built once, guarded by a lock because the platform may — and we cannot
#: verify that it does not — start a session before a previous one's boot has finished.
_runtime: WorkerRuntime | None = None
_registry: SessionRegistry | None = None
_shutdown: Final[ShutdownSignal] = ShutdownSignal()
_runtime_lock: asyncio.Lock | None = None
_drain_task: asyncio.Task[None] | None = None


#: The direction of a call that carries no valid call claim. Nothing on either carrier's
#: handshake says which way a call went, so only our own signed claim can say "outbound"
#: (`carrier.call_claim_from_stream_url`); without it the call is one that rang us.
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


def _stream_url(runner_args: RunnerArguments) -> str:
    """The whole URL the carrier connected to, query string included, or "".

    Separate from `_route_token` because the two read different halves for different
    reasons: the token is the PATH segment and a call with no token is unroutable, while
    the query carries the control plane's caller claim and its absence is an ordinary
    outcome (`not_read`). A helper that refused on a missing query would refuse every call
    made before the answer leg learned to mint one.
    """
    websocket = getattr(runner_args, "websocket", None)
    url = getattr(websocket, "url", None)
    return "" if url is None else str(url)


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
    *,
    claim_key: bytes | None = None,
    now: float | None = None,
) -> tuple[str, UUID, UUID, CallDirection]:
    """(our call_id, tenant, agent, direction) for the session on the wire.

    **OUR `call_id` IS NEVER THE CARRIER'S** (§1.2). The carrier's CDR is the authority on
    the FACTS of a call and our worker on its CONTENT, and the reconciliation only works if
    the two ids are independent. So the id is either one our own control plane minted —
    an outbound dial's `calls` row, carried on the stream URL under a MAC for this agent
    ref (`carrier.call_claim_from_stream_url`) so the worker's writes land on that row —
    or, with no valid claim, a fresh `uuid7` for an inbound call.
    """
    token = _route_token(runner_args)
    route = route_of(token)
    claimed = call_claim_from_stream_url(
        _stream_url(runner_args), ref=token, claim_key=claim_key, now=now
    )
    if claimed is not None:
        return claimed.call_id, route.tenant_id, route.agent_id, claimed.direction
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
    config = runtime.config
    engine_agent_ref = _route_token(runner_args)
    call_id, tenant_id, agent_id, direction = await resolve_call_identity(
        runner_args, claim_key=config.caller_claim_key
    )

    # THE SLOT IS TAKEN BEFORE ANY IO, and that ordering is the fix rather than a tidy-up.
    # This used to admit only after the transport, the session read and the whole pipeline
    # existed — two network round trips during which the readiness marker still said
    # `ready`, so a one-session container could be handed a second call whose caller then
    # met `AtCapacityError` with a transport and a sink already built and nothing to close
    # them. Refusing costs that caller nothing now.
    registry.reserve(call_id)
    try:
        # WHAT THE CONTROL PLANE SAID, READ OFF THE URL IT MINTED. The whole query is
        # attacker-controlled — anything can open a WebSocket — so a claimed `known`
        # caller is believed only under a MAC for THIS agent ref (`claim_from_stream_url`),
        # and the claimed carrier is checked against Pipecat's detection before it chooses
        # a serializer (`carrier.read_handshake`).
        claim = claim_from_stream_url(
            _stream_url(runner_args), ref=engine_agent_ref, claim_key=config.caller_claim_key
        )
        leg = await open_carrier_leg(
            # Present: `_route_token` above refuses a session with no socket.
            getattr(runner_args, "websocket", None),
            claim=claim,
            default_carrier=config.carrier,
            plivo_credentials=config.plivo_credentials,
        )
        await runtime.calls.run_call(
            call_id=call_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
            direction=direction,
            engine_agent_ref=engine_agent_ref,
            credentials_for=config.credentials_for,
            transport=leg.transport,
            # The claim folded with the handshake's own verdict (`fold_caller_identity`).
            caller=leg.handshake.caller,
            carrier_call_id=leg.handshake.carrier_call_id,
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
