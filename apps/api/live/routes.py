"""`GET /v1/live` and `GET /v1/admin/live` — the change streams the consoles listen to (D-774).

D-24 chose polling for freshness and named server-sent events as the planned upgrade; this
is that upgrade, and polling stays underneath it as the floor. Each stream sends short
notes — "calls changed", "wallet changed" — and the page refetches the queries that show
those things through their ordinary, authorised routes. Nothing a person could not
already read leaves through here, so the stream needs only the permission every member
of an account holds (`org:read`).

WHAT THE STREAM DOES, in order: wait for this process's Redis subscription (a stream
that cannot hear anything ends at once so the browser keeps polling), send `ready`
(refetch everything — what changed while closed was not announced), then relay notes.
Every `HEARTBEAT_S` it re-checks the caller with `core.auth.still_entitled`, so a
session that is signed out, expired, rotated, deactivated, removed from the account or
demoted stops receiving within one heartbeat; and it ends itself after `MAX_AGE_S` so a
stream never outlives the decisions it was opened under by much. FastAPI writes a
keep-alive comment on every 15 s of silence, which is what keeps nginx's 60 s read
timeout and the edge from closing an idle stream.

NO DATABASE CONNECTION IS HELD. The auth dependency's sessions close before the first
byte, and the re-check opens its own short ones.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import AsyncIterator
from contextlib import suppress
from time import monotonic
from typing import Final
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent

from apps.api.core.auth import requires, still_entitled
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.rbac import Permission, permission_meta
from apps.api.live.hub import Subscription, get_hub
from apps.api.live.schemas import LiveClosed, LiveReady, LiveResync
from apps.api.live.topics import OPERATOR_CHANNEL, tenant_channel

log = get_logger(__name__)

router = APIRouter(prefix="/v1", tags=["live"])

#: How often the caller is re-checked. Under nginx's 60 s read timeout with room to spare.
HEARTBEAT_S: Final = 20.0
#: The longest one stream lives before the server ends it and the browser reopens it.
MAX_AGE_S: Final = 30 * 60
#: How long a new stream waits for this process's Redis subscription.
CONNECT_WAIT_S: Final = 5.0
#: Streams one person may hold open on one process: several tabs, not a runaway loop.
MAX_STREAMS_PER_PERSON: Final = 8
#: Sent as the SSE `retry:` field, for a client that reconnects natively.
RETRY_MS: Final = 3000

PERMISSION: Final[Permission] = "org:read"

_open: Counter[tuple[str, UUID | None]] = Counter()

_DESCRIPTION = """\
A `text/event-stream` of change notes for the caller's own account. Events:

* `ready` · `{"heartbeat_s": 20, "max_age_s": 1800}` — open. Refetch what is on screen.
* `change` · `{"topic": "calls", "at": "<instant>"}` — something in that family changed.
  Refetch the queries that show it. Topics: account, agents, assistant, callbacks, calls,
  campaigns, dnc, healer, integrations, knowledge, knowledge_gaps, leads, numbers,
  quality, wallet.
* `resync` · `{"reason": "subscription_restored"|"fell_behind"}` — notes may have been
  missed. Refetch what is on screen.
* `closed` · `{"reason": "session_ended"|"max_age"|"shutting_down"}` — the server ended
  the stream. Reopen after `max_age`; after `session_ended` the next ordinary request
  says what to do.

A note never carries a row id, a name, a phone number, an amount or any text. Requires
`org:read`; a view-as session receives the viewed account's notes.\
"""

_ADMIN_DESCRIPTION = """\
The operator console's change stream: every account's notes, each with its `tenant_id`,
plus the platform's own topics (`alerts`, `platform`, `healer`, `quality`). Same events and
rules as `GET /v1/live`. Requires an operator session.\
"""


def _admit(principal: Principal) -> Principal:
    """A dependency, not a line in the stream: once an SSE response has started its
    status is sent, so a refusal has to happen before the generator runs."""
    if _open[(principal.realm, principal.user_id)] >= MAX_STREAMS_PER_PERSON:
        raise ProblemError(
            kind="transient",
            code="too_many_live_streams",
            title="Too many open windows",
            detail="This sign-in already has the most live windows open at once.",
            status=429,
            remediation="Close a few Calevate tabs; the others keep updating.",
            headers={"Retry-After": "30"},
        )
    return principal


async def _client_caller(principal: Principal = Depends(requires(PERMISSION))) -> Principal:
    if principal.tenant_id is None:
        # `requires` on the `any` realm yields a tenant for a client and for a view-as
        # operator alike, so this is unreachable; refused rather than asserted.
        raise ProblemError.forbidden()
    return _admit(principal)


async def _operator_caller(
    principal: Principal = Depends(requires(PERMISSION, realm="admin")),
) -> Principal:
    return _admit(principal)


def _drain(sub: Subscription) -> None:
    while not sub.queue.empty():
        sub.queue.get_nowait()


async def _stream(
    request: Request, principal: Principal, channel: str
) -> AsyncIterator[ServerSentEvent]:
    hub = get_hub()
    person = (principal.realm, principal.user_id)
    sub = hub.subscribe(channel)
    _open[person] += 1
    try:
        if not await hub.wait_connected(CONNECT_WAIT_S):
            log.warning("live_stream_unavailable", extra={"realm": principal.realm})
            return
        yield ServerSentEvent(
            event="ready",
            data=LiveReady(heartbeat_s=int(HEARTBEAT_S), max_age_s=int(MAX_AGE_S)),
            retry=RETRY_MS,
        )
        opened = monotonic()
        next_check = opened + HEARTBEAT_S
        while True:
            if sub.closing:
                yield ServerSentEvent(event="closed", data=LiveClosed(reason="shutting_down"))
                return
            now = monotonic()
            if now - opened >= MAX_AGE_S:
                yield ServerSentEvent(event="closed", data=LiveClosed(reason="max_age"))
                return
            if now >= next_check:
                if not await still_entitled(request, principal, PERMISSION):
                    log.info("live_stream_session_ended", extra={"realm": principal.realm})
                    yield ServerSentEvent(event="closed", data=LiveClosed(reason="session_ended"))
                    return
                next_check = monotonic() + HEARTBEAT_S
            if sub.resync is not None:
                reason = sub.resync
                sub.resync = None
                _drain(sub)
                yield ServerSentEvent(
                    event="resync",
                    data=LiveResync(
                        reason="fell_behind" if reason == "fell_behind" else "subscription_restored"
                    ),
                )
                continue
            try:
                note = sub.queue.get_nowait()
            except asyncio.QueueEmpty:
                sub.wake.clear()
                wait = max(0.05, min(next_check, opened + MAX_AGE_S) - monotonic())
                with suppress(TimeoutError):
                    await asyncio.wait_for(sub.wake.wait(), timeout=wait)
                continue
            yield ServerSentEvent(event="change", data=note)
    finally:
        hub.unsubscribe(sub)
        _open[person] -= 1
        if _open[person] <= 0:
            del _open[person]


@router.get(
    "/live",
    response_class=EventSourceResponse,
    openapi_extra=permission_meta(PERMISSION),
    summary="Live change notes for this account (server-sent events)",
    description=_DESCRIPTION,
)
async def live_changes(
    request: Request,
    principal: Principal = Depends(_client_caller),
) -> AsyncIterator[ServerSentEvent]:
    async for event in _stream(request, principal, tenant_channel(principal.tenant_id)):
        yield event


@router.get(
    "/admin/live",
    response_class=EventSourceResponse,
    openapi_extra=permission_meta(PERMISSION),
    summary="Live change notes across every account, for the operator console",
    description=_ADMIN_DESCRIPTION,
)
async def admin_live_changes(
    request: Request,
    principal: Principal = Depends(_operator_caller),
) -> AsyncIterator[ServerSentEvent]:
    async for event in _stream(request, principal, OPERATOR_CHANNEL):
        yield event


__all__ = ["HEARTBEAT_S", "MAX_AGE_S", "MAX_STREAMS_PER_PERSON", "router"]
