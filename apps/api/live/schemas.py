"""The wire shapes of the live change stream (D-774)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from apps.api.live.topics import Topic


class LiveChange(BaseModel):
    """`event: change` — something in `topic` changed at `at`. Refetch what shows it.

    `tenant_id` is set on the operator stream only, so a cross-client screen can tell
    which account moved; a client's own stream never carries it. No row ids, names,
    numbers, amounts or text, ever (hard rule 6)."""

    model_config = ConfigDict(extra="forbid")

    topic: Topic
    at: datetime
    tenant_id: UUID | None = None


class LiveReady(BaseModel):
    """`event: ready` — the stream is open. Refetch everything on screen: whatever changed
    while it was closed was not announced to this browser."""

    model_config = ConfigDict(extra="forbid")

    heartbeat_s: int
    max_age_s: int


class LiveResync(BaseModel):
    """`event: resync` — notes may have been lost (this server's subscription to Redis
    dropped, or this browser fell behind). Refetch everything on screen."""

    model_config = ConfigDict(extra="forbid")

    reason: Literal["subscription_restored", "fell_behind"]


class LiveClosed(BaseModel):
    """`event: closed` — the server is ending the stream. `session_ended`: do not reopen
    until the session is proved again (the next ordinary request will say how);
    `max_age`: reopen at once."""

    model_config = ConfigDict(extra="forbid")

    reason: Literal["session_ended", "max_age", "shutting_down"]


__all__ = ["LiveChange", "LiveClosed", "LiveReady", "LiveResync"]
