"""Every test message to a live agent goes through here, so the opt-out can tell a test from a
caller (founder, 10 Oct 2026).

THE PROBLEM. A test chat runs the agent's real actions (test-chat.md:7, "your own actions
still run for real"), with no call behind it: the platform fills `{{call.id}}` only on a call
and sends `X-Call-Id` only when it knows one (agent/custom-api.md:92-114). Our opt-out action
finds no call, writes nothing and tells the agent to apologise that it could not be done, so
a test of "stop calling me" showed the agent refusing the caller, which is not what a caller
on a real call hears.

THE MARKER. Before each test message we open a short window for the agent in Redis. The
opt-out action, when it names no call AND the agent's window is open, answers as a recorded
opt-out does and writes nothing (`worker/engine_actions.engine_action`). A request that names
a call never reaches that branch, so the real opt-out path is unchanged (hard rule 5). With
no call there is no caller number, so nothing could have been written anyway: the window
changes only what the agent is told to say.

The vendor sends no test marker of its own on an action call (none is documented in
test-chat.md or custom-api.md), which is why the marker is ours. Redis being unreachable
leaves the window closed: the test then shows the apology, never a false write.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from apps.api.core.logging import get_logger
from apps.api.core.redis import get_redis
from apps.api.core.settings import get_settings
from apps.api.engine.test_chat import RunsTestChat, TestChatTurn

log = get_logger(__name__)

#: Long enough to cover one reply (the engine answers within its own request timeout), short
#: enough that a window left open by a crashed run closes within two minutes.
WINDOW_S: Final = 120

_KEY: Final = "agent_test_window:{agent_id}"


async def open_window(agent_id: UUID) -> None:
    try:
        await get_redis().set(_KEY.format(agent_id=agent_id), "1", ex=WINDOW_S)
    except Exception as failure:  # a closed window is the safe outcome
        log.warning("agent_test_window_unset", extra={"error": type(failure).__name__})


async def window_open(agent_id: UUID) -> bool:
    try:
        return bool(await get_redis().exists(_KEY.format(agent_id=agent_id)))
    except Exception as failure:  # unreadable means closed
        log.warning("agent_test_window_unread", extra={"error": type(failure).__name__})
        return False


async def send_test_message(
    engine: RunsTestChat,
    *,
    agent_id: UUID,
    engine_agent_ref: str,
    message: str,
    session: str | None = None,
) -> TestChatTurn:
    """One test message to the live agent, with its test window open, in call mode while the
    console switch is on (`Settings.thinnest_test_chat_call_mode`, D-847): every test path
    asks in the same mode, so no two results of one moment are from different modes."""
    await open_window(agent_id)
    return await engine.test_chat(
        engine_agent_ref,
        message,
        session=session,
        call_mode=get_settings().thinnest_test_chat_call_mode,
    )


__all__ = ["WINDOW_S", "open_window", "send_test_message", "window_open"]
