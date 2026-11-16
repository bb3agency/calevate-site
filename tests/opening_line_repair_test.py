"""The opening line is written for the business and repaired rather than discarded (D-957).

A drafted opening that broke one rule used to be replaced by the starter's line, the same for
every business. The model legs are replaced at the workers' seams (`write_opening`,
`draft_script`, `ask_json`); nothing here reaches a network.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from apps.api.agents import script_proposals
from apps.workers import opening_line
from apps.workers import script_proposal as proposal_worker
from apps.workers.script_assist import ScriptBrief, UnusableAnswerError
from calevate_shared.call_script import CallScript
from calevate_shared.opening_notices import NONE_SAID
from calevate_shared.spoken_guard import (
    INTRODUCED_NAMES_RULE,
    OWN_LETTERS_RULE,
    QUESTION_END_RULE,
    UNINTRODUCED_RULE,
)
from tests.conftest import create_org_with_receptionist

BUSINESS = "Rytu Khata"
TRADE = "retail"
BRIEF = (
    "We keep accounts for farmers in Guntur: crop loans, fertiliser credit and what each "
    "farmer owes us after the harvest. Farmers call to check their balance."
)
#: A drafted opening with one English-letter word, said after the introduction.
SLIPPED = "మీ balance చూడాలా?"
#: What the fake model returns on the repair: own letters, no greeting, no names, a question.
REPAIRED = "మీ ఖాతాలో బాకీ ఎంత ఉందో చూడాలా?"
#: The placed-call opening of the founder's call of 2 Nov 2026 after the introduction: "can we
#: talk now?" with two words in English letters (D-959).
PLACED_SLIPPED = "నేను రైతు ఖాతా యాప్ గురించి కాల్ చేస్తున్నాను అండి. ఇప్పుడు matladadaniki ok నా అండి?"
PLACED_REPAIRED = "మీ పంట లోన్ బాకీ గురించి కాల్ చేస్తున్నాను అండి, ఇప్పుడు మాట్లాడొచ్చా?"


def _answer(value: str | opening_line.WrittenOpening) -> SimpleNamespace:
    written = (
        opening_line.WrittenOpening(line=value, said=NONE_SAID) if isinstance(value, str) else value
    )
    return SimpleNamespace(
        value=written, capability=SimpleNamespace(disclosure=None), earlier=(), model=None
    )


def test_the_placed_opening_writer_is_told_it_is_for_calls_the_agent_places() -> None:
    brief = ScriptBrief(business_name=BUSINESS, agent_name="Anjali", language="te-IN")
    assert opening_line.PLACED_TASK in opening_line.opening_request(brief, placed=True)
    assert opening_line.PLACED_TASK not in opening_line.opening_request(brief)


def test_the_writer_is_told_the_business_the_rules_and_the_lines_problems() -> None:
    brief = ScriptBrief(
        description=BRIEF,
        business_name=BUSINESS,
        agent_name="Anjali",
        language="te-IN",
        introduced=True,
    )
    problems = opening_line.opening_problems(
        SLIPPED, "te-IN", names=(BUSINESS, "Anjali"), introduced=True
    )
    asked = opening_line.opening_request(brief, line=SLIPPED, problems=problems)

    assert "Guntur" in asked and BUSINESS in asked
    for rule in (QUESTION_END_RULE, OWN_LETTERS_RULE, INTRODUCED_NAMES_RULE):
        assert rule in asked, "the rules in the validator's own words"
    assert SLIPPED in asked and problems[0] in asked
    assert "THIS business" in opening_line.OPENING_WRITER_INSTRUCTION

    said_first = opening_line.opening_request(replace(brief, introduced=False))
    assert UNINTRODUCED_RULE in said_first and "Write the opening_line" in said_first


def test_the_rule_and_the_repairs_sentences_are_one_statement() -> None:
    names = (BUSINESS, "Anjali")
    assert opening_line.opening_problems(REPAIRED, "te-IN", names=names, introduced=True) == []
    assert not opening_line.opening_problems(REPAIRED, "te-IN", names=names, introduced=True)
    found = opening_line.opening_problems(
        "నమస్కారం, Rytu Khata నుంచి", "te-IN", names=names, introduced=True
    )
    assert [problem.split(";")[0] for problem in found] == [
        "opening_line: does not end on a question",
        "opening_line: starts with a greeting",
    ]
    assert opening_line.opening_problems("చెప్పండి, ఏం కావాలి?", "te-IN", names=names)


async def test_the_writer_asks_once_and_sends_back_a_broken_line_with_its_problems(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[Any] = []

    async def ladder(_text: str, _instruction: str, *, parse: Any, **_kwargs: Any) -> Any:
        seen.append("ask")
        with pytest.raises(UnusableAnswerError) as refused:
            parse({"opening_line": SLIPPED})
        assert "“balance”" in refused.value.problems
        return _answer(parse({"opening_line": f"  {REPAIRED} "}))

    monkeypatch.setattr(opening_line, "ask_json", ladder)
    brief = ScriptBrief(
        business_name=BUSINESS, agent_name="Anjali", language="te-IN", introduced=True
    )
    answer = await opening_line.write_opening(brief)
    assert answer.value.line == REPAIRED and seen == ["ask"]


async def _agent() -> tuple[uuid.UUID, uuid.UUID]:
    created = await create_org_with_receptionist(
        name=BUSINESS,
        slug=f"prop-{uuid.uuid4().hex[:8]}",
        vertical_template=TRADE,
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return uuid.UUID(str(created["id"])), uuid.UUID(str(created["agent_id"]))


def _request(base: CallScript, words: str) -> script_proposals.ScriptProposal:
    return script_proposals.ScriptProposal(
        id=uuid.uuid4(),
        mode="change",
        status="drafting",
        request=words,
        answers={},
        base_script=base,
        requested_by=None,
        requested_at=datetime.now(UTC),
    )


async def test_pips_draft_repairs_the_opening_it_wrote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _agent()
    asked: list[dict[str, Any]] = []
    fixed = "నమస్కారం, మీ ఖాతాలో బాకీ చూడాలా?"

    async def write(brief: ScriptBrief, **kwargs: Any) -> SimpleNamespace:
        asked.append(kwargs)
        return _answer(fixed)

    monkeypatch.setattr(proposal_worker, "write_opening", write)
    # Greets, but hands no turn over: no question.
    drafted = CallScript(opening_line="నమస్కారం, మీ ఖాతా చూస్తాను.")
    finished = await proposal_worker.finish_written(
        tenant_id,
        agent_id,
        _request(CallScript(), "Rewrite my opening line for farmers checking their balance."),
        drafted,
        time.monotonic(),
    )
    assert finished.script.opening_line == fixed
    assert any("does not end on a question" in p for p in asked[0]["problems"])
    assert len(finished.opening_spends) == 1, "the repair is handed back to be charged"


async def test_pips_draft_repairs_the_placed_opening_it_wrote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _agent()
    base = CallScript(opening_line="మీ ఖాతా గురించి అడగాలా?")
    asked: list[dict[str, Any]] = []

    async def write(brief: ScriptBrief, **kwargs: Any) -> SimpleNamespace:
        asked.append(kwargs)
        return _answer(PLACED_REPAIRED)

    monkeypatch.setattr(proposal_worker, "write_opening", write)
    finished = await proposal_worker.finish_written(
        tenant_id,
        agent_id,
        _request(base, "Add an opening for the calls it makes about crop loans."),
        CallScript(opening_line=base.opening_line, outbound_opening_line=PLACED_SLIPPED),
        time.monotonic(),
    )
    assert finished.script.outbound_opening_line == PLACED_REPAIRED
    assert [kw["placed"] for kw in asked] == [True], "the answering line it kept is not judged"


def test_a_suggestion_that_drops_an_opening_keeps_the_owners() -> None:
    """ "Fix them first" on Put it live once replaced the owner's opening with nothing: the
    model left it blank and a blank line is never judged."""
    base = CallScript(
        opening_line="Hello, this is the shop.", outbound_opening_line="Hello {{lead_name}}."
    )
    dropped = CallScript(opening_line="  ", outbound_opening_line="")
    kept = proposal_worker.openings_kept(dropped, base)
    assert kept.opening_line == "Hello, this is the shop."
    assert kept.outbound_opening_line == "Hello {{lead_name}}."
    rewritten = CallScript(opening_line="Hi there.")
    assert proposal_worker.openings_kept(rewritten, base).opening_line == "Hi there."
