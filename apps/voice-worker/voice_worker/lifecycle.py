"""Alive, ready, and going away: the three container states this deployable has.

**WHY A MODULE RATHER THAN A FEW LINES IN THE ENTRYPOINT.** Two of the three are
correctness, not operations. A container replaced mid-call decides what the caller hears
and whether the record of that call is true; a container that says READY while it is
already carrying its one session invites a scheduler to hand it a second caller it cannot
serve. Both are decisions with a right answer, so they are written down where a test can
hold them rather than inside a `main()` nobody re-reads.

**LIVENESS IS THE PROCESS, AND WE DO NOT SIMULATE IT.** This container has no HTTP
surface of its own and does not want one: what would answer a liveness probe is the same
event loop that carries the audio, so a probe that succeeded while the loop was wedged
would be worse than no probe. The honest liveness contract is the one every runtime
already has — the process exits non-zero, immediately, on anything it cannot serve calls
without (`boot.load_worker_config`, `boot.open_runtime`, `boot.build_event_sink`) — and a
process that is alive is one the runtime can see is alive. ⚠ **WHETHER PIPECAT CLOUD
PROBES A CONTAINER AT ALL, AND IN WHAT SHAPE, IS UNKNOWN** (`docs.pipecat.ai` is
egress-blocked from this container; the vendor material that ships inside
`pipecat-ai==1.10.0` — `cli/agent_templates/AGENTS.md` and
`cli/templates/server/Dockerfile.jinja2` — describes the deploy and the secret set and
says nothing about health). Nothing here is invented to fill that gap.

**READY MEANS "SEND ME A CALL", WHICH ON THIS DEPLOYABLE IS NOT A SYNONYM FOR HEALTHY.**
The platform runs one session per instance
(`docs/evidence/engine-replacement-comet-2026-09-06.md:122`), so a container in the middle
of a conversation is perfectly healthy and has nothing to offer. `SessionRegistry` is
therefore both the admission control and the readiness answer — one object, so the two
can never disagree, which is the failure mode a separate `is_ready` flag has.

**PUBLISHED AS A FILE, BECAUSE A FILE NEEDS NO CONTRACT.** `ReadinessFile` writes a marker
when the container can take a call and removes it the instant it cannot. An exec probe
(`test -f`), a sidecar or a human with a shell can all read it, and it costs nothing when
nobody does. It is deliberately NOT an HTTP endpoint: a port and a path are a contract
with a platform whose contract we have not read, and inventing one would be a guess that
looks like an integration.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from loguru import logger

from voice_worker.boot import MAX_CONCURRENT_SESSIONS
from voice_worker.pipeline import AssembledCall

#: How often `drain` re-asks whether the pipeline has finished. Small enough that a call
#: that ends in its first second is not held for a tenth of the grace, large enough that
#: the wait is not a spin on the loop carrying the audio.
_DRAIN_POLL_S: Final[float] = 0.1


class AtCapacityError(RuntimeError):
    """This container cannot take the session it was handed, and says which state it is in.

    RAISED rather than queued. A queued call is a caller listening to silence while a
    container finishes somebody else's conversation, and the platform — which owns the
    scheduling — can put the session on another instance in less time than our queue would
    hold it.
    """


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    """Whether this container can take a call, and the one word for why not."""

    ready: bool
    #: `starting` | `ready` | `busy` | `draining`. Four words, because an operator looking
    #: at a container that is not taking calls needs to know which of them it is: three are
    #: correct and transient, and one (`starting`, long after boot) is a fault.
    state: str
    in_flight: int
    capacity: int


@dataclass(frozen=True, slots=True)
class DrainReport:
    """What a shutdown did to the calls this container was carrying.

    Both numbers matter and they are different facts: `settled` drained on their own and
    ended the way any call ends, `cut` ran out of grace and were terminated by us with a
    `failed` event written for each. A shutdown that reports `cut` is not a failure of this
    code — it is the honest outcome of replacing a container mid-conversation — but it is
    the number that should be zero on a quiet deploy and is worth an operator's attention
    when it is not.
    """

    settled: int
    cut: tuple[str, ...]

    @property
    def clean(self) -> bool:
        return not self.cut


class ReadinessFile:
    """The readiness marker on disk. Never raises: a probe file is not worth a call.

    **A FAILURE TO WRITE IT IS LOGGED AND SWALLOWED, WHICH IS THE OPPOSITE OF THIS REPO'S
    USUAL POSTURE AND IS RIGHT HERE.** The file is an OPTIONAL publication of a state the
    process already holds correctly in memory; a read-only filesystem or a bad path must
    not stop a container that can otherwise answer the phone. The state itself — admission
    control — is `SessionRegistry`'s and fails loudly.
    """

    __slots__ = ("_path",)

    def __init__(self, path: str | os.PathLike[str] | None) -> None:
        self._path = Path(path) if path is not None else None

    @property
    def enabled(self) -> bool:
        return self._path is not None

    def publish(self, report: ReadinessReport) -> None:
        """Marker present exactly when the container would accept a call."""
        if self._path is None:
            return
        try:
            if report.ready:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                self._path.write_text(report.state, encoding="utf-8")
            else:
                self._path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("readiness marker not written", reason=type(exc).__name__)


class SessionRegistry:
    """The calls this container is carrying, its admission control, and its readiness.

    One object for all three because they are one fact. A container is ready IFF it is
    past boot, not draining, and has room — and "has room" is the same counter `admit`
    enforces. Two objects here would be two answers to one question, and the one a
    scheduler reads would be the one nobody updated.
    """

    __slots__ = ("_capacity", "_draining", "_marker", "_sessions", "_started")

    def __init__(
        self,
        *,
        capacity: int = MAX_CONCURRENT_SESSIONS,
        marker: ReadinessFile | None = None,
    ) -> None:
        self._capacity = capacity
        self._sessions: dict[str, AssembledCall] = {}
        self._draining = False
        self._started = False
        self._marker = marker or ReadinessFile(None)

    # -- state ---------------------------------------------------------------------------

    def mark_started(self) -> None:
        """Boot finished: every dependency is open and proven. Called once, by the
        entrypoint, AFTER `open_runtime` — never from a constructor, because a registry
        that reported ready the moment it was built would be reporting on nothing."""
        self._started = True
        self._publish()

    def status(self) -> ReadinessReport:
        in_flight = len(self._sessions)
        if self._draining:
            state = "draining"
        elif not self._started:
            state = "starting"
        elif in_flight >= self._capacity:
            state = "busy"
        else:
            state = "ready"
        return ReadinessReport(
            ready=state == "ready",
            state=state,
            in_flight=in_flight,
            capacity=self._capacity,
        )

    @property
    def draining(self) -> bool:
        return self._draining

    def _publish(self) -> None:
        self._marker.publish(self.status())

    # -- admission -----------------------------------------------------------------------

    def admit(self, call_id: str, call: AssembledCall) -> None:
        """Take responsibility for one call, or refuse with the state that refused it."""
        status = self.status()
        if not status.ready:
            raise AtCapacityError(
                f"this container is {status.state} ({status.in_flight}/{status.capacity} "
                f"sessions) and cannot take call {call_id}"
            )
        self._sessions[call_id] = call
        self._publish()

    def release(self, call_id: str) -> None:
        """Give up a call. Idempotent — the entrypoint releases in a `finally`, and the
        drain path may have released the same call already."""
        if self._sessions.pop(call_id, None) is not None:
            self._publish()

    # -- shutdown ------------------------------------------------------------------------

    async def drain(self, grace_s: float) -> DrainReport:
        """Stop taking calls, let the ones in flight end, then settle whatever is left.

        **THE ORDER IS THE CORRECTNESS.** Readiness goes false FIRST, before anything is
        asked to stop, so no call is admitted into a container that is on its way out.
        Then every live session is asked to end the graceful way — `stop_when_done()`
        queues an `EndFrame`, which drains what is already in flight and lets the transport
        close normally (`pipecat/pipeline/worker.py:765-772`). On the Plivo leg that close
        is also what HANGS UP: `PlivoFrameSerializer` answers an `EndFrame` with
        `DELETE /v1/Account/{auth_id}/Call/{call_id}/` (`pipecat/serializers/plivo.py:
        118-135`, `:172-192`), which is why `boot` refuses to start without those
        credentials. A `cancel()` here instead would cut the socket, and the carrier would
        keep the leg — and the meter — running on a call nobody is on.

        **WHAT HAPPENS TO THE RECORD, WHICH IS THE PART THAT IS NOT AN OPS NICETY.** A
        session that drains inside the grace ends the way every call ends: the pipeline's
        own `on_pipeline_finished` fires and the boundary emits `completed`, which by its
        own definition means "our pipeline drained" and never "the call connected and
        lasted N seconds" (§1.2 gives the billable facts to the carrier). A session that
        does NOT drain in time is ended by us, and we write the terminal event OURSELVES,
        as `failed`, BEFORE cancelling — because `cancel()` does not guarantee that
        handler runs, and a call with an `in_progress` row and no terminal event is a call
        the post-call pipeline waits on for ever. `NormalizedEventBoundary.call_ended` is
        idempotent, so whichever of the two arrives first is the one recorded and the
        other is a no-op.

        **WHAT THIS CANNOT DO, SAID PLAINLY: IT CANNOT SETTLE THE LEDGER.**
        `meter.CallMeter.metered_rows` requires a `CarrierCdr` and a `RuntimeUsage` and
        REFUSES without them (`CarrierFactsMissingError`, `RuntimePriceUnknownError`), and
        neither exists at the moment a container is being replaced — the CDR is the
        carrier's and arrives after the leg ends. So the ledger for a cut call is settled
        later, from the CDR, against the `call_id` this process already wrote. What a
        shutdown owes the money path is exactly the terminal event that makes that
        reconciliation possible, and that is what it writes.
        """
        self._draining = True
        self._publish()
        live = dict(self._sessions)
        if not live:
            return DrainReport(settled=0, cut=())

        logger.info("voice worker draining", sessions=len(live), grace_s=grace_s)
        for call_id, call in live.items():
            try:
                # The vendor's own signature carries no return annotation, which mypy
                # strict reads as an untyped call. Ignored at the one site rather than
                # widened to `Any`, so every other member of `PipelineWorker` this module
                # touches stays checked.
                await call.worker.stop_when_done()  # type: ignore[no-untyped-call]
            except Exception as exc:
                logger.warning("graceful end refused", call_id=call_id, reason=type(exc).__name__)

        deadline = asyncio.get_running_loop().time() + grace_s
        while asyncio.get_running_loop().time() < deadline:
            live = {cid: call for cid, call in live.items() if not call.worker.has_finished()}
            if not live:
                break
            await asyncio.sleep(_DRAIN_POLL_S)

        settled = len(self._sessions) - len(live)
        for call_id, call in live.items():
            # The record first, the cancel second. See this method's docstring.
            await call.boundary.call_ended(status="failed")
            logger.error(
                "call cut by container shutdown",
                call_id=call_id,
                grace_s=grace_s,
            )
            try:
                await call.worker.cancel(reason="container shutdown")
            except Exception as exc:
                logger.warning("cancel refused", call_id=call_id, reason=type(exc).__name__)

        for call_id in list(self._sessions):
            self._sessions.pop(call_id, None)
        self._publish()
        return DrainReport(settled=settled, cut=tuple(sorted(live)))


@dataclass(slots=True)
class ShutdownSignal:
    """A SIGTERM that has arrived, as something a coroutine can wait on.

    **WE INSTALL OUR OWN HANDLER RATHER THAN TAKING PIPECAT'S, AND THAT IS THE ONE
    DECISION IN THIS FILE THAT IS NOT OBVIOUS.** `WorkerRunner(handle_sigterm=True)`
    answers SIGTERM with `cancel()` — `_sig_handler` -> `_sig_cancel` -> `self.cancel(
    reason="interrupt signal")` (`pipecat/workers/runner.py:558-566`, `:347`) — and
    `cancel` is the immediate path: it cuts the pipeline wherever it is, with no drain and
    no `EndFrame`. On a deploy that means the caller's line goes dead mid-sentence, the
    Plivo leg is never hung up by the serializer, and the terminal event may never be
    written. Every one of those is the failure this module exists to prevent, so the
    runner is constructed with `handle_sigterm=False` and this object owns the signal.
    """

    event: asyncio.Event = field(default_factory=asyncio.Event)

    def install(self, *signals: int) -> None:
        """Route the given signals here. Idempotent per signal; safe on a loop that has
        no signal support (Windows, a thread), where it simply does nothing."""
        import signal as signal_module

        loop = asyncio.get_running_loop()
        for number in signals or (signal_module.SIGTERM, signal_module.SIGINT):
            try:
                loop.add_signal_handler(number, self.event.set)
            except (NotImplementedError, RuntimeError, ValueError):
                logger.warning("signal handler not installed", signal=int(number))

    async def wait(self) -> None:
        await self.event.wait()


__all__ = [
    "AtCapacityError",
    "DrainReport",
    "ReadinessFile",
    "ReadinessReport",
    "SessionRegistry",
    "ShutdownSignal",
]
