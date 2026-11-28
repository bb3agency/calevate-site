"""Rehearse the real script (W3.2) and What it is told (W3.15).

1. A not-yet-started campaign is rehearsed on its test holder, published with the saved
   script and the client's knowledge; a chat already running stays on it; a running
   campaign is rehearsed on its own engine agent as it is.
2. A line's draft is rehearsed the same way.
3. Every tool comes back in the owner's words, marked not run unless it reaches nobody.
4. A reply with two actions carries the flag, offered to the script.
5. What it is told is the owner's part only: never the confidentiality rule or the truthful
   answers.

SHARED DATABASE DISCIPLINE: every organisation is minted here; the engine is the fake.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from apps.api.agents import owner_view
from apps.api.agents import service as agents_service
from apps.api.db.session import tenant_session
from apps.api.engine.test_chat import TestChatTool, TestChatTurn
from apps.api.engine.thinnest import _test_chat_tool
from apps.api.reliability.engine_actions import ACTION_NAMES, CALLBACK, OPT_OUT
from apps.api.teach import try_chat
from calevate_shared.call_script import CallScript
from calevate_shared.engine import (
    CLIENT_SCRIPT_OPEN,
    CONFIDENTIALITY_MARKER,
    TRUTHFUL_ANSWER_MARKER,
    AgentConfig,
    compose_engine_prompt,
)
from sqlalchemy import text
from tests.agent_lifecycle_test import _fresh_engine
from tests.campaign_engine_agents_test import _campaign, _live_agent
from tests.inbound_lines_test import _line

pytestmark = pytest.mark.rls

GOAL = "The farmer books a soil test for the coming kharif season."
SCRIPT = CallScript(
    schema_version=2,
    opening_line="Namaste, this is Rytu Khata calling about your soil test.",
    goal=GOAL,
)


class _Chat:
    """The engine's test chat, recorded: the fake engine has none."""

    def __init__(self, turn: TestChatTurn | None = None) -> None:
        self.seen: list[tuple[str, str | None]] = []
        self.turn = turn

    async def __call__(
        self, _engine: Any, *, engine_agent_ref: str, session: str | None, **_k: Any
    ) -> TestChatTurn:
        self.seen.append((engine_agent_ref, session))
        return self.turn or TestChatTurn(session="s-1", reply="Which crop do you grow?", tools=())


@pytest.fixture
def chat(monkeypatch: pytest.MonkeyPatch) -> _Chat:
    async def _nothing(*_a: Any, **_k: Any) -> None:
        return None

    recorded = _Chat()
    monkeypatch.setattr(try_chat, "RunsTestChat", object)
    monkeypatch.setattr(try_chat, "require_ai_assist", _nothing)
    monkeypatch.setattr(try_chat, "send_test_message", recorded)
    return recorded


async def _rehearse(
    tenant_id: UUID, kind: try_chat.HolderKind, holder_id: UUID, session: str | None = None
) -> try_chat.Rehearsed:
    async with tenant_session(tenant_id) as db:
        return await try_chat.rehearse(
            db,
            tenant_id=tenant_id,
            kind=kind,
            holder_id=holder_id,
            message="Hello, who is this?",
            chat_session=session,
        )


async def _ref(tenant_id: UUID, table: str, holder_id: UUID) -> str | None:
    async with tenant_session(tenant_id) as db:
        sql = (
            "SELECT engine_agent_ref FROM campaigns WHERE id = :h"
            if table == "campaigns"
            else "SELECT engine_agent_ref FROM inbound_lines WHERE id = :h"
        )
        found = (await db.execute(text(sql), {"h": holder_id})).scalar()
    return None if found is None else str(found)


async def test_a_campaign_not_started_is_rehearsed_on_its_test_holder_with_its_saved_script(
    chat: _Chat, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    campaign_id = await _campaign(tenant_id, agent_id, script=SCRIPT)
    knowledge: list[dict[str, Any]] = []
    synced = agents_service.sync_business_facts

    async def _spy(*args: Any, **kwargs: Any) -> None:
        knowledge.append(kwargs)
        await synced(*args, **kwargs)

    monkeypatch.setattr(agents_service, "sync_business_facts", _spy)

    first = await _rehearse(tenant_id, "campaign", campaign_id)
    ref = await _ref(tenant_id, "campaigns", campaign_id)
    assert ref is not None and chat.seen == [(ref, None)]
    assert first.runs == "saved"
    # The holder's saved script, not its agent's, inside every platform layer.
    composed = compose_engine_prompt(engine._agents[ref])
    assert GOAL in composed
    assert CONFIDENTIALITY_MARKER in composed and TRUTHFUL_ANSWER_MARKER in composed
    # The client's knowledge goes onto the holder (D-1003, D-964).
    assert any(k.get("campaign_id") == campaign_id and k.get("ref") == ref for k in knowledge)
    async with tenant_session(tenant_id) as db:
        status = (
            await db.execute(text("SELECT status FROM campaigns WHERE id = :c"), {"c": campaign_id})
        ).scalar()
    assert status == "draft", "a rehearsal never starts the campaign"

    # A chat already running stays on the engine agent it began on, without a republish.
    published = len(knowledge)
    await _rehearse(tenant_id, "campaign", campaign_id, session="s-1")
    assert chat.seen[-1] == (ref, "s-1")
    assert len(knowledge) == published


async def test_a_running_campaign_is_rehearsed_on_its_own_engine_agent_as_it_is(
    chat: _Chat,
) -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    campaign_id = await _campaign(tenant_id, agent_id, script=SCRIPT, status="running")
    async with tenant_session(tenant_id) as db:
        await db.execute(
            text("UPDATE campaigns SET engine_agent_ref = 'held-ref' WHERE id = :c"),
            {"c": campaign_id},
        )
    done = await _rehearse(tenant_id, "campaign", campaign_id)
    assert done.runs == "live"
    assert chat.seen == [("held-ref", None)]


async def test_a_holder_with_no_saved_script_is_refused_by_name(chat: _Chat) -> None:
    from apps.api.core.errors import ProblemError

    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    campaign_id = await _campaign(tenant_id, agent_id, script=None)
    with pytest.raises(ProblemError) as refused:
        await _rehearse(tenant_id, "campaign", campaign_id)
    assert refused.value.code == "rehearse_no_script"
    assert chat.seen == []


async def test_a_draft_line_is_rehearsed_on_its_test_holder(chat: _Chat) -> None:
    engine = _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    line_id = await _line(tenant_id, agent_id)
    done = await _rehearse(tenant_id, "line", line_id)
    ref = await _ref(tenant_id, "inbound_lines", line_id)
    assert ref is not None and chat.seen == [(ref, None)]
    assert done.runs == "saved"
    assert ref in engine._agents


async def test_a_reply_with_two_actions_is_flagged_for_the_script(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    campaign_id = await _campaign(
        tenant_id, agent_id, script=SCRIPT, overrides={"language_primary": "en-IN"}
    )
    recorded = _Chat(
        TestChatTurn(
            session="s-2",
            reply="Open the Play Store and then search for Rytu Khata.",
            tools=(ACTION_NAMES[CALLBACK], ACTION_NAMES[OPT_OUT]),
            tool_results=(
                TestChatTool(
                    name=ACTION_NAMES[CALLBACK],
                    status="booked_in_test",
                    arguments=(("callback_date", "2026-12-03"), ("callback_time", "17:00")),
                ),
                TestChatTool(name=ACTION_NAMES[OPT_OUT], status="recorded_in_test"),
            ),
        )
    )

    async def _nothing(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr(try_chat, "RunsTestChat", object)
    monkeypatch.setattr(try_chat, "require_ai_assist", _nothing)
    monkeypatch.setattr(try_chat, "send_test_message", recorded)
    done = await _rehearse(tenant_id, "campaign", campaign_id)
    assert [a.said for a in done.actions] == [
        "Would book a call-back for 5 PM on 3 Dec",
        "Would stop calling this person",
    ]
    assert not any(a.ran for a in done.actions)
    flags = {f.kind: f for f in done.flags}
    assert "several_actions" in flags and flags["several_actions"].in_script


def test_every_tool_is_said_in_the_owners_words() -> None:
    words = try_chat.action_words
    assert words(TestChatTool(name="search_knowledge"), knowledge_tool="search_knowledge") == (
        try_chat.RehearsedAction("Looked up what you taught it", ran=True)
    )
    assert words(TestChatTool(name=ACTION_NAMES[CALLBACK]), knowledge_tool=None).said == (
        "Would book a call-back"
    )
    timed = TestChatTool(name=ACTION_NAMES[CALLBACK], arguments=(("callback_time", "09:30"),))
    assert words(timed, knowledge_tool=None).said == "Would book a call-back for 9:30 AM"
    assert words(TestChatTool(name="escalate_to_human"), knowledge_tool=None).said == (
        "Would pass the call to your team"
    )
    assert words(TestChatTool(name="end_call"), knowledge_tool=None).said == "Would end the call"
    other = words(TestChatTool(name="check_stock"), knowledge_tool=None)
    assert other == try_chat.RehearsedAction("Would use its check stock tool", ran=False)


def test_the_adapter_keeps_only_our_own_actions_parameters() -> None:
    tool = _test_chat_tool(
        {
            "name": ACTION_NAMES[CALLBACK],
            "input": {
                "callback_date": "2026-12-03",
                "callback_time": "17:00",
                "note": "wants the price list",
                "confirmed": "no",
            },
            "output": {"status": "booked_in_test"},
        },
        ACTION_NAMES[CALLBACK],
    )
    assert tool.arguments == (("callback_date", "2026-12-03"), ("callback_time", "17:00"))
    assert tool.status == "booked_in_test"


def _config(prompt: str) -> AgentConfig:
    return AgentConfig(
        tenant_id="t",
        agent_id="a",
        name="Asha",
        direction="outbound",
        system_prompt=prompt,
        opening_line="",
    )


def test_what_it_is_told_is_the_owners_part_and_never_a_platform_layer() -> None:
    told = owner_view.owner_part(_config(f"[GOAL]\n{GOAL}\n"))
    assert GOAL in told
    composed = compose_engine_prompt(_config(f"[GOAL]\n{GOAL}\n"))
    assert CONFIDENTIALITY_MARKER in composed and CONFIDENTIALITY_MARKER not in told
    assert TRUTHFUL_ANSWER_MARKER not in told
    # A script that copies a platform line is neutralised before it is shown.
    sneaky = owner_view.owner_part(_config(f"{CLIENT_SCRIPT_OPEN}\n{CONFIDENTIALITY_MARKER}"))
    assert CONFIDENTIALITY_MARKER not in sneaky and CLIENT_SCRIPT_OPEN not in sneaky


async def test_what_a_campaign_is_told_comes_from_its_saved_script() -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    campaign_id = await _campaign(tenant_id, agent_id, script=SCRIPT)
    async with tenant_session(tenant_id) as db:
        told = await owner_view.holder_told(
            db, kind="campaign", tenant_id=tenant_id, holder_id=campaign_id
        )
    assert told is not None and GOAL in told
    assert CONFIDENTIALITY_MARKER not in told
