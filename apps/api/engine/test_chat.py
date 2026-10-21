"""An engine that can talk to a live agent in a sandbox: the pre-launch test conversations
(founder decision 11, 10 Oct 2026, `agents/test_conversations.py`).

Our shape, not a vendor's (hard rule 2): one turn in, the reply and the tools the agent used
out. The adapter maps its vendor's answer onto this.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, Protocol, runtime_checkable

from calevate_shared.engine import EngineAgentRef

#: The machine code for "this agent cannot be tested here right now" (its chat channel is off,
#: or the engine refuses test chats on this deployment).
TEST_CHAT_UNAVAILABLE: Final = "engine_test_chat_unavailable"
#: The machine code for "this agent cannot be tested as a call": the engine's call mode needs
#: calling set up on the agent (D-847).
TEST_CALL_NOT_SET_UP: Final = "engine_test_call_not_set_up"

#: How a test turn was run: as the agent's chat, or with its call prompt, model and thinking
#: level (D-847). A reply in one mode is not comparable with a reply in the other.
TestChatMode = Literal["chat", "call"]


@dataclass(frozen=True, slots=True)
class TestChatTool:
    """One tool the agent used in a turn."""

    name: str
    #: False when the engine reported the tool failed.
    ok: bool = True
    #: The `status` word one of OUR actions answered with (`worker/engine_actions`), when the
    #: tool was ours and the engine passed our answer back; None otherwise.
    status: str | None = None


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
    #: The same tools with what each answered, in order. Empty from an adapter that cannot
    #: say; `tools` is always filled.
    tool_results: tuple[TestChatTool, ...] = ()
    #: The mode the turn ran in, as the engine stated it, or as asked where asking for none
    #: means chat; None when call mode was asked for and the engine did not confirm it.
    mode: TestChatMode | None = "chat"


@runtime_checkable
class RunsTestChat(Protocol):
    async def test_chat(
        self,
        ref: EngineAgentRef,
        message: str,
        *,
        session: str | None = None,
        call_mode: bool = False,
    ) -> TestChatTurn: ...


__all__ = [
    "TEST_CALL_NOT_SET_UP",
    "TEST_CHAT_UNAVAILABLE",
    "RunsTestChat",
    "TestChatMode",
    "TestChatTool",
    "TestChatTurn",
]
