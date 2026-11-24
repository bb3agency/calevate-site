"""Stop for one Pip run: who may stop it, how the stop reaches the loop, and what it cancels.

A run is one answer to one question (`service.run_copilot`). The route mints its id, sends it
as the stream's first frame (`event: run`) and holds a `RunControl` for as long as the run
lasts. `POST /v1/copilot/runs/{run_id}/stop` (and its admin twin) asks for the stop; the loop
notices it between model frames and between tool calls and raises `RunStoppedError`, and the
route then ends the stream with `event: stopped` instead of `done`.

WHY REDIS AND A LOCAL EVENT, BOTH. The stop request may land on a different api process
from the one streaming the answer, so the request is written to Redis and every live run
polls its own key (`STOP_POLL_S`). When it lands on the same process, the local event is
set at once and the poll is only the backstop. A pub/sub channel was the alternative and was
rejected: a message published before the run's subscription is ready is lost, and a key
the run reads on its own clock cannot be.

WHO MAY STOP A RUN. Only the person who asked: the owner is written beside the run when it
starts (realm, account and user), and a stop from anyone else is accepted and ignored. The
route answers 202 either way, so a run id reveals nothing about whether it exists, whose it
is, or whether it already finished.

WHAT STOP DOES NOT DO. A tool call already running finishes: a write is one transaction
with its audit row (`write_tools.run_immediate`), and cutting it half-way is worse than
letting it land. Nothing after it runs. A script draft this run started is cancelled
through the canceller the script writer registers (`register_draft_canceller`), because
the draft is written by a worker after the action itself has returned.

Every Redis call here is best effort and never raises: a run whose stop key cannot be read
still answers, and still stops on the local event.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.context import Principal
from apps.api.core.logging import get_logger
from apps.api.core.redis import get_redis
from apps.api.db.session import tenant_session

log = get_logger(__name__)

#: How long a run's owner and stop keys live without being cleared. Longer than the loop's
#: whole wall clock (`service.TOTAL_BUDGET_S`, pinned against this by a test) plus the
#: meter after it, so a run whose cleanup never ran stops being stoppable on its own.
RUN_TTL_S: Final = 150
#: How often a live run reads its stop key. A quarter second is what a person notices as
#: "Stop worked at once" while costing one GET per run per tick.
STOP_POLL_S: Final = 0.25

HolderKind = Literal["campaign", "inbound_line"]
StopReason = Literal["person"]


class RunStoppedError(Exception):
    """The person pressed Stop. Raised between model frames and between tool calls.

    An `Exception` so that the provider-failure arms (`httpx.HTTPError`, `TimeoutError`)
    never catch it as an outage and fall back to another model."""

    def __init__(self, reason: StopReason = "person") -> None:
        super().__init__(reason)
        self.reason: StopReason = reason


@dataclass(frozen=True, slots=True)
class StartedDraft:
    """A script draft this run started: what Stop cancels, and what `event: draft` names."""

    holder_kind: HolderKind
    holder_id: UUID
    proposal_id: UUID


class DraftCanceller(Protocol):
    """Cancels one script draft that is still being written, and returns the holder to its
    previous state; True when it cancelled one. The script writer's
    `campaigns/script_draft.cancel_draft` has this shape. Must be idempotent, because Stop
    may reach a draft that already finished or was already cancelled. It is handed a
    session already scoped to `tenant_id` (`RunControl.cancel_drafts` opens one per draft)."""

    def __call__(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        holder_kind: HolderKind,
        holder_id: UUID,
        proposal_id: UUID,
    ) -> Awaitable[bool]: ...


_CANCELLER: DraftCanceller | None = None


def register_draft_canceller(canceller: DraftCanceller | None) -> None:
    """The script writer's cancel, called for every draft a stopped run started. `None`
    unregisters (tests)."""
    global _CANCELLER
    _CANCELLER = canceller


def draft_canceller() -> DraftCanceller | None:
    """The canceller Stop will call, or None when nothing registered one."""
    return _CANCELLER


def owner_of(principal: Principal) -> str:
    """The run's owner as one comparable string: realm, account and person. The account is
    part of it because a person who belongs to two accounts asks Pip separately in each."""
    return f"{principal.realm}:{principal.tenant_id or '-'}:{principal.user_id or '-'}"


def _owner_key(run_id: UUID) -> str:
    return f"calevate:copilot:run:{run_id}:owner"


def _stop_key(run_id: UUID) -> str:
    return f"calevate:copilot:run:{run_id}:stop"


#: Runs streaming in THIS process, so a stop that lands here takes effect without a poll.
_LOCAL: dict[UUID, RunControl] = {}


class RunControl:
    """One run's stop switch, and the drafts it started. Use as an async context manager
    around the run: entering records the owner and starts the stop poll, leaving clears
    both."""

    def __init__(self, *, owner: str, run_id: UUID, tenant_id: UUID | None) -> None:
        self.run_id = run_id
        self.owner = owner
        self.tenant_id = tenant_id
        self.started_at = datetime.now(UTC)
        self._stop = asyncio.Event()
        self._drafts: list[StartedDraft] = []
        self._unsent: list[StartedDraft] = []
        self._poll: asyncio.Task[None] | None = None

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def stop(self) -> None:
        self._stop.set()

    def check(self) -> None:
        """Raise `RunStoppedError` if the person asked to stop. The loop's checkpoint."""
        if self._stop.is_set():
            raise RunStoppedError()

    async def wait(self) -> None:
        await self._stop.wait()

    def note_draft(self, draft: StartedDraft) -> None:
        self._drafts.append(draft)
        self._unsent.append(draft)

    def take_unsent_drafts(self) -> list[StartedDraft]:
        """The drafts started since the last call, for `event: draft`."""
        unsent, self._unsent = self._unsent, []
        return unsent

    @property
    def drafts(self) -> tuple[StartedDraft, ...]:
        return tuple(self._drafts)

    async def cancel_drafts(self) -> None:
        """Cancel every draft this run started, each in its own transaction under the run's
        tenant. Each failure is logged and the rest still go: one draft that could not be
        cancelled must not keep the others writing."""
        tenant_id = self.tenant_id
        if not self._drafts or tenant_id is None:
            return
        canceller = _CANCELLER
        if canceller is None:
            log.warning("copilot_draft_canceller_missing", extra={"drafts": len(self._drafts)})
            return
        for draft in self._drafts:
            try:
                async with tenant_session(tenant_id) as session:
                    await canceller(
                        session,
                        tenant_id=tenant_id,
                        holder_kind=draft.holder_kind,
                        holder_id=draft.holder_id,
                        proposal_id=draft.proposal_id,
                    )
            except Exception as exc:
                log.warning(
                    "copilot_draft_cancel_failed",
                    extra={"proposal_id": str(draft.proposal_id), "error": type(exc).__name__},
                )

    async def __aenter__(self) -> RunControl:
        await self.open()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def open(self) -> None:
        """Record the owner and start the stop poll. For a route whose `try` already has a
        `finally`, which calls `close`; everything else uses `async with`."""
        _LOCAL[self.run_id] = self
        try:
            await get_redis().set(_owner_key(self.run_id), self.owner, ex=RUN_TTL_S)
        except Exception as exc:
            log.warning("copilot_run_register_failed", extra={"error": type(exc).__name__})
        self._poll = asyncio.create_task(self._watch())

    async def close(self) -> None:
        """Stop polling and forget the run: a stop after this is accepted and does nothing."""
        _LOCAL.pop(self.run_id, None)
        poll, self._poll = self._poll, None
        if poll is not None:
            poll.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await poll
        try:
            await get_redis().delete(_owner_key(self.run_id), _stop_key(self.run_id))
        except Exception as exc:
            log.warning("copilot_run_clear_failed", extra={"error": type(exc).__name__})

    async def _watch(self) -> None:
        """Poll the stop key until it is set or the run ends."""
        while not self._stop.is_set():
            try:
                if await get_redis().get(_stop_key(self.run_id)):
                    self._stop.set()
                    return
            except Exception as exc:
                # One line per failed read would flood the log during a Redis outage; the
                # local event still works, so one warning and a slower poll.
                log.warning("copilot_run_poll_failed", extra={"error": type(exc).__name__})
                await asyncio.sleep(STOP_POLL_S * 8)
                continue
            await asyncio.sleep(STOP_POLL_S)


async def request_stop(run_id: UUID, *, owner: str) -> None:
    """Stop `run_id` if `owner` started it; otherwise do nothing. Never raises and never
    says which of the two happened: the route answers 202 regardless."""
    local = _LOCAL.get(run_id)
    if local is not None and local.owner == owner:
        local.stop()
    try:
        redis = get_redis()
        if await redis.get(_owner_key(run_id)) == owner:
            await redis.set(_stop_key(run_id), "person", ex=RUN_TTL_S)
    except Exception as exc:
        log.warning("copilot_run_stop_failed", extra={"error": type(exc).__name__})


# --- the run in progress, for code that cannot be handed it ------------------------------

#: The run the current task is answering. Set by `service.run_copilot` for its whole length,
#: so the tool loop's checkpoints and a draft started deep inside an action can find it
#: without a parameter threaded through every tool. `None` outside a run: background jobs,
#: the confirm route and tests that pass no control.
_CURRENT: ContextVar[RunControl | None] = ContextVar("copilot_run_control", default=None)


def current() -> RunControl | None:
    return _CURRENT.get()


def activate(control: RunControl | None) -> Token[RunControl | None]:
    return _CURRENT.set(control)


def deactivate(token: Token[RunControl | None]) -> None:
    # A generator closed by the garbage collector runs its `finally` in another context,
    # where the token is foreign; the variable then dies with the task that set it.
    with contextlib.suppress(ValueError):
        _CURRENT.reset(token)


def checkpoint() -> None:
    """Raise `RunStoppedError` when the current run was stopped; nothing outside a run."""
    control = _CURRENT.get()
    if control is not None:
        control.check()


def note_draft_started(*, holder_kind: HolderKind, holder_id: UUID, proposal_id: UUID) -> None:
    """THE SEAM THE SCRIPT WRITER CALLS when it queues a draft. Inside a Pip run the draft
    is announced (`event: draft`) and cancelled by Stop; anywhere else this does nothing."""
    control = _CURRENT.get()
    if control is not None:
        control.note_draft(
            StartedDraft(holder_kind=holder_kind, holder_id=holder_id, proposal_id=proposal_id)
        )


__all__ = [
    "RUN_TTL_S",
    "STOP_POLL_S",
    "DraftCanceller",
    "HolderKind",
    "RunControl",
    "RunStoppedError",
    "StartedDraft",
    "activate",
    "checkpoint",
    "current",
    "deactivate",
    "draft_canceller",
    "note_draft_started",
    "owner_of",
    "register_draft_canceller",
    "request_stop",
]
