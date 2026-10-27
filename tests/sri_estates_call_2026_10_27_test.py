"""The founder's two Sri Estates test calls of 27 Oct 2026 (D-894).

Outbound, Telugu, agent "Anjali", lead follow-up. To "we are still looking" the agent said
"glad"; it put the same "good"/"OK" before each next question; the caller said he would come
at "six" (the English word) and heard it back as "ఆరు గంటలకు"; it asked two things in one turn
and was talked over; told it spoke too fast and hurriedly, it apologised and asked "anything
else?". The prompt clauses are pinned in `tests/voice_style_prompt_test.py`; here the agent as
the calls had it gets them, and the test loop notes the stock reaction.
"""

from __future__ import annotations

from typing import Any

from apps.api.agents.test_conversations import Scenario, Turn, hard_check
from apps.api.agents.turn_checks import (
    JOB_KINDS,
    SOUND_KINDS,
    STOCK_OPENER_REPLIES,
    conversation_problems,
    opener,
)
from calevate_shared.engine import (
    CONFIDENTIALITY_MARKER,
    TRUTHFUL_ANSWER_MARKER,
    VOICE_STYLE_GUIDANCE,
    AgentConfig,
    compose_engine_prompt,
)

#: Call B's replies, each opened with the same reaction before the next question.
STOCK = (
    Turn("చూస్తున్నామండి ఇంకా.", "మంచిది అండి. ఏ ఏరియా లో చూస్తున్నారు?"),
    Turn("గుంటూరు లోనే.", "మంచిది అండి. ఎన్ని బీహెచ్కే కావాలి?"),
    Turn("త్రీ బీహెచ్కే.", "మంచిది అండి. బడ్జెట్ ఎంత వరకు అనుకుంటున్నారు?"),
)
#: The same conversation as HOW TO SPEAK now asks: a reaction only where it fits.
VARIED = (
    Turn("చూస్తున్నామండి ఇంకా.", "ఏ ఏరియా లో చూస్తున్నారు అండి?"),
    Turn("గుంటూరు లోనే.", "గుంటూరు, ఓకే. ఎన్ని బీహెచ్కే కావాలి?"),
    Turn("త్రీ బీహెచ్కే.", "బడ్జెట్ ఎంత వరకు అనుకుంటున్నారు?"),
)


def _anjali(**over: Any) -> AgentConfig:
    fields: dict[str, Any] = {
        "tenant_id": "t",
        "agent_id": "a",
        "name": "Anjali",
        "business": "Sri Estates",
        "direction": "outbound",
        "language_primary": "te-IN",
        "system_prompt": "Call people who enquired about a property.",
        "opening_line": "నమస్కారం అండి, Sri Estates నుంచి కాల్ చేస్తున్నాను.",
        "call_is_recorded": True,
        "facts_in_knowledge": True,
        "knowledge_tool": "search_knowledge",
    }
    return AgentConfig(**{**fields, **over})


def test_anjalis_prompt_carries_every_fix_and_keeps_the_locked_text() -> None:
    prompt = compose_engine_prompt(_anjali())
    assert VOICE_STYLE_GUIDANCE in prompt
    for clause in (
        "React only if it fits what they said",
        "One question a turn, on one thing, last;",
        "Told you are too fast? Sorry once",
        '("six" stays "six")',
    ):
        assert clause in prompt, clause
    assert CONFIDENTIALITY_MARKER in prompt and TRUTHFUL_ANSWER_MARKER in prompt


def test_a_reaction_is_the_short_lead_before_the_first_mark() -> None:
    assert opener("మంచిది అండి. ఏ ఏరియా లో చూస్తున్నారు?") == "మంచిది అండి"
    assert opener("సరే అండి, ఏ ఏరియా?") == "సరే అండి"
    assert opener("Sure, which area?") == "sure"
    # A reply that leads with its content has no reaction to count.
    assert opener("ఏ ఏరియా లో చూస్తున్నారు అండి?") is None
    assert opener("") is None


def test_the_same_reaction_on_every_reply_is_noted_never_failed() -> None:
    problems = conversation_problems(list(STOCK))
    assert [p.kind for p in problems] == ["same_opening"]
    assert f"opened {STOCK_OPENER_REPLIES} replies" in problems[0].reason
    assert "same_opening" in SOUND_KINDS and "same_opening" not in JOB_KINDS
    scenario = Scenario(
        key="still_looking",
        title="A lead still looking",
        category="flow",
        turns=tuple(t.said for t in STOCK),
        expect="Asks one thing a turn.",
    )
    verdict = hard_check(scenario, list(STOCK), language="te-IN")
    assert verdict.verdict is None
    assert any(p.kind == "same_opening" for p in verdict.sounds)


def test_varied_or_absent_reactions_are_not_noted() -> None:
    assert conversation_problems(list(VARIED)) == []
    # Twice is ordinary speech.
    assert conversation_problems(list(STOCK[:2])) == []
