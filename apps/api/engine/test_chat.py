"""An engine that can talk to a live agent in a sandbox: the pre-launch test conversations
(founder decision 11, 10 Oct 2026, `agents/test_conversations.py`).

Our shape, not a vendor's (hard rule 2): one turn in, the reply and the names of the tools
the agent used out. The adapter maps its vendor's answer onto this.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Protocol, runtime_checkable

from calevate_shared.engine import EngineAgentRef

#: The machine code for "this agent cannot be tested here right now" (its chat channel is off,
#: or the engine refuses test chats on this deployment).
TEST_CHAT_UNAVAILABLE: Final = "engine_test_chat_unavailable"


@dataclass(frozen=True, slots=True)
class TestChatTurn:
    """What the agent answered to one message."""

    #: Pass back to continue the same conversation.
    session: str
    reply: str
    #: The tool names the agent used, in order, as the engine names them.
    tools: tuple[str, ...]
    #: The reply stopped part-way; `reply` holds what came before.
    failed_part_way: bool = False


@runtime_checkable
class RunsTestChat(Protocol):
    async def test_chat(
        self, ref: EngineAgentRef, message: str, *, session: str | None = None
    ) -> TestChatTurn: ...


__all__ = ["TEST_CHAT_UNAVAILABLE", "RunsTestChat", "TestChatTurn"]
