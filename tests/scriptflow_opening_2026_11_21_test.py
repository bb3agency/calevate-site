"""A placed call's opening says who is calling, from where and why, then asks; the steps
start from the person's yes (Varsha, Rytu Khata app-setup campaign, 20-21 Nov 2026).

The opening on those calls said only "Hello, I am from Rytu Khata, can you talk now?", with no
agent name and no reason, and the person hung up asking who was calling. Evidence:
docs/evidence/script-generation-2026-11-21/FLOW.md. Telugu here is built from code points,
never typed.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from apps.api.agents import script_proposals
from apps.api.agents.call_rules import (
    OPENING_CEILING_CHARS,
    OPENING_LINE_MAX_CHARS,
    OPENING_LINE_RULE,
    PLACED_OPENING_MAX_CHARS,
    PLACED_OPENING_RULE,
    SCRIPT_FLOW_RULE,
    opening_most,
    placed_opening_problems,
    said_line_problem,
)
from apps.api.agents.script_lint import CapabilityManifest, LintContext
from apps.workers import opening_line, script_assist
from apps.workers import script_proposal as proposal_worker
from apps.workers.opening_line import WrittenOpening
from apps.workers.script_assist import ScriptBrief
from calevate_shared.call_script import CallScript
from calevate_shared.opening_notices import NONE_SAID
from tests.conftest import create_org_with_receptionist

AGENT = "Varsha"
BUSINESS = "Rytu Khata"
WHERE = "opening_line"

#: The opening the founder heard on 20-21 Nov 2026, in English.
BARE = "Hello, I am from Rytu Khata, can you talk now?"
GOOD = (
    "Hello {{lead_name}}, I am Varsha from Rytu Khata. I am calling to help you set up the "
    "app. Can you talk now?"
)
#: Who and why in one sentence: the reason has no sentence of its own.
MERGED = "Hello, I am Varsha from Rytu Khata, calling to help you set up the app. Can you talk now?"
#: Telugu words by code point: "now", "tell me", "app", "about".
NOW = "".join(map(chr, (0x0C07, 0x0C2A, 0x0C4D, 0x0C2A, 0x0C41, 0x0C21, 0x0C41)))
TELL = "".join(map(chr, (0x0C1A, 0x0C46, 0x0C2A, 0x0C4D, 0x0C2A, 0x0C02, 0x0C21, 0x0C3F)))
APP = "".join(map(chr, (0x0C2F, 0x0C3E, 0x0C2A, 0x0C4D)))
ABOUT = "".join(map(chr, (0x0C17, 0x0C41, 0x0C30, 0x0C3F, 0x0C02, 0x0C1A, 0x0C3F)))

OUTBOUND = LintContext(
    manifest=CapabilityManifest(direction="outbound"), agent_name=AGENT, business_name=BUSINESS
)


# --- 1. the check -------------------------------------------------------------------------


def test_the_opening_the_founder_heard_is_sent_back_for_who_and_why() -> None:
    """FAILS IF: a placed call may open with no agent name and no reason, as the Varsha
    calls did."""
    found = placed_opening_problems(WHERE, BARE, agent_name=AGENT, business_name=BUSINESS)
    assert [problem.split(";")[0] for problem in found] == [
        "opening_line: does not say who is calling",
        "opening_line: does not say why the call is made",
    ]
    assert AGENT in found[0], "the repair is told the name to say"


def test_who_then_why_then_the_question_passes() -> None:
    assert placed_opening_problems(WHERE, GOOD, agent_name=AGENT, business_name=BUSINESS) == []


def test_who_and_why_in_one_sentence_is_split() -> None:
    found = placed_opening_problems(WHERE, MERGED, agent_name=AGENT, business_name=BUSINESS)
    assert len(found) == 1 and "why the call is made" in found[0]


def test_after_the_agents_introduction_only_the_reason_is_needed() -> None:
    """The engine's AI introduction said who is calling (D-865), so the opening carries the
    reason and the question, and no names."""
    line = "I am calling to help you set up the app. Can you talk now?"
    assert placed_opening_problems(WHERE, line, agent_name=AGENT, introduced=True) == []
    assert placed_opening_problems(WHERE, "Can you talk now?", agent_name=AGENT, introduced=True)


def test_a_greeting_or_a_notice_is_not_a_reason() -> None:
    for line in (
        "Hello {{lead_name}}. I am Varsha from Rytu Khata. Can you talk now?",
        "I am Varsha from Rytu Khata. This call is recorded. Can you talk now?",
    ):
        found = placed_opening_problems(WHERE, line, agent_name=AGENT, business_name=BUSINESS)
        assert [problem.split(";")[0] for problem in found] == [
            "opening_line: does not say why the call is made"
        ], line


def test_the_check_reads_structure_in_any_language() -> None:
    """A Telugu line with the name as written, a reason sentence and a question passes; the
    same line without its reason sentence does not."""
    line = f"{AGENT} {BUSINESS}. {APP} {ABOUT}. {NOW} {TELL}?"
    assert placed_opening_problems(WHERE, line, agent_name=AGENT, business_name=BUSINESS) == []
    short = f"{AGENT} {BUSINESS}. {NOW} {TELL}?"
    assert placed_opening_problems(WHERE, short, agent_name=AGENT, business_name=BUSINESS)


# --- 2. the room it takes -------------------------------------------------------------------


def test_a_placed_opening_has_room_for_its_name_and_reason() -> None:
    long = GOOD + " " + "x" * (PLACED_OPENING_MAX_CHARS - len(GOOD) - 1)
    assert len(long) == PLACED_OPENING_MAX_CHARS > OPENING_LINE_MAX_CHARS
    assert said_line_problem(WHERE, long, opening=True, placed=True) is None
    assert said_line_problem(WHERE, long, opening=True) is not None
    assert opening_line.length_problem(WHERE, long, placed=True) is None
    assert opening_line.length_problem(WHERE, long) is not None


def test_with_notices_woven_it_stays_inside_the_ceiling_answering_lines_reach() -> None:
    both = "I am an AI assistant and this call is recorded."
    assert opening_most(both, placed=True) == OPENING_CEILING_CHARS
    assert opening_most(both) == OPENING_CEILING_CHARS
    assert opening_most("Hello?", placed=True) == PLACED_OPENING_MAX_CHARS


# --- 3. the writers are told it, and hold it ------------------------------------------------


def test_the_writer_is_given_the_agents_name() -> None:
    """The brief never named the agent, so no opening could say who is calling."""
    brief = ScriptBrief(business_name=BUSINESS, agent_name=AGENT, direction="outbound")
    assert f"Agent name: {AGENT}" in brief.user_message()
    assert "Agent name" not in ScriptBrief(business_name=BUSINESS).user_message()


def test_the_rules_say_who_why_then_the_question_and_the_steps_order() -> None:
    assert PLACED_OPENING_RULE in OPENING_LINE_RULE
    assert "first stage starts from their yes" in SCRIPT_FLOW_RULE
    assert "ask, never state, what the call needs to know" in SCRIPT_FLOW_RULE
    assert "check it is done" in SCRIPT_FLOW_RULE
    assert "first stage confirms this is the right person" not in script_assist._SYSTEM_INSTRUCTION
    assert "one reason" in opening_line.OPENING_WRITER_INSTRUCTION
    assert "one reason" in opening_line.PLACED_TASK


def test_the_opening_writer_is_told_the_placed_rule_with_the_name() -> None:
    brief = ScriptBrief(business_name=BUSINESS, agent_name=AGENT, direction="outbound")
    asked = opening_line.opening_request(brief, placed_rules=True)
    assert PLACED_OPENING_RULE in asked and f"the agent's name is {AGENT}" in asked
    assert f"at most {PLACED_OPENING_MAX_CHARS} characters" in asked
    assert PLACED_OPENING_RULE not in opening_line.opening_request(brief)


def _drafted(opening: str, direction: str) -> list[str]:
    return script_assist.language_problems(
        CallScript(schema_version=2, opening_line=opening),
        "en-IN",
        names=(BUSINESS, AGENT),
        lint=OUTBOUND,
        direction=direction,
    )


def test_a_draft_for_an_agent_that_places_calls_is_sent_back_for_the_bare_opening() -> None:
    assert any("why the call is made" in p for p in _drafted(BARE, "outbound"))
    assert any("who is calling" in p for p in _drafted(BARE, "outbound"))
    assert not any("why the call is made" in p for p in _drafted(GOOD, "outbound"))
    # An answering agent's opening greets and offers help; it states no reason.
    assert not any("why the call is made" in p for p in _drafted(BARE, "inbound"))


async def test_the_written_opening_is_checked_only_when_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The opening writer holds a placed line to who and why when its caller asks
    (`placed_rules`); the notice weaver, which keeps the owner's line, does not ask."""
    verdicts: list[bool] = []

    async def ladder(_text: str, _instruction: str, *, parse: Any, **_kwargs: Any) -> Any:
        try:
            parse({"opening_line": BARE})
            verdicts.append(True)
        except script_assist.UnusableAnswerError:
            verdicts.append(False)
        return SimpleNamespace(value=WrittenOpening(line=GOOD, said=NONE_SAID))

    monkeypatch.setattr(opening_line, "ask_json", ladder)
    brief = ScriptBrief(
        business_name=BUSINESS, agent_name=AGENT, direction="outbound", language="en-IN"
    )
    await opening_line.write_opening(brief, placed_rules=True)
    await opening_line.write_opening(brief)
    assert verdicts == [False, True]


# --- 4. a campaign's opening is a placed call's, whatever its agent answers ------------------


async def test_a_campaigns_opening_is_repaired_as_a_placed_call_with_its_main_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: a campaign on an answering agent has its opening judged and rewritten as an
    answering line, or the repair is not told the campaign's reason for calling."""
    created = await create_org_with_receptionist(
        name=BUSINESS,
        slug=f"flow-{uuid.uuid4().hex[:8]}",
        vertical_template="retail",
        billing_email=None,
        language="en-IN",
        created_by=None,
    )
    tenant_id, agent_id = uuid.UUID(str(created["id"])), uuid.UUID(str(created["agent_id"]))
    asked: list[tuple[ScriptBrief, dict[str, Any]]] = []

    async def write(brief: ScriptBrief, **kwargs: Any) -> SimpleNamespace:
        asked.append((brief, kwargs))
        return SimpleNamespace(
            value=WrittenOpening(line=GOOD, said=NONE_SAID),
            capability=SimpleNamespace(disclosure=None),
            earlier=(),
            model=None,
        )

    monkeypatch.setattr(proposal_worker, "write_opening", write)
    task = "Help farmers who registered set up the Rytu Khata app."
    request = script_proposals.ScriptProposal(
        id=uuid.uuid4(),
        mode="whole",
        status="drafting",
        request=task,
        answers={},
        base_script=CallScript(),
        requested_by=None,
        requested_at=datetime.now(UTC),
    )
    finished = await proposal_worker.finish_written(
        tenant_id,
        agent_id,
        request,
        CallScript(schema_version=2, opening_line=BARE),
        time.monotonic(),
        direction="outbound",
        purpose=task,
    )
    assert finished.script.opening_line == GOOD
    brief, kwargs = asked[0]
    assert kwargs["placed_rules"] is True
    assert brief.direction == "outbound" and brief.description == task
    assert any("why the call is made" in p for p in kwargs["problems"])
