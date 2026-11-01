"""The opening line is written for the business and repaired rather than discarded (D-957).

A drafted opening that broke one rule used to be replaced by the starter's line, the same for
every business. The model legs are replaced at the worker's seams (`write_opening`,
`draft_script`, `ask_json`); nothing here reaches a network.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import script_proposals
from apps.api.agents.script_builder import load_agent_script
from apps.api.agents.starters import CATALOGUE, starter_opening
from apps.api.core.errors import ProblemError
from apps.api.crm import assist as crm_assist
from apps.api.db.session import tenant_session
from apps.api.first_run import service as first_run
from apps.workers import first_run as worker
from apps.workers import opening_line
from apps.workers import script_proposal as proposal_worker
from apps.workers.script_assist import ScriptBrief, UnusableAnswerError
from calevate_shared.call_script import CallScript
from calevate_shared.spoken_guard import (
    INTRODUCED_NAMES_RULE,
    OWN_LETTERS_RULE,
    QUESTION_END_RULE,
    UNINTRODUCED_RULE,
)
from sqlalchemy import text
from tests.conftest import create_org_with_receptionist

BUSINESS = "Rytu Khata"
#: Any trade with a starter; the opening under test is written from the brief, not the trade.
TRADE = "retail"
BRIEF = (
    "We keep accounts for farmers in Guntur: crop loans, fertiliser credit and what each "
    "farmer owes us after the harvest. Farmers call to check their balance."
)
#: A drafted opening with one English-letter word, said after the introduction.
SLIPPED = "మీ balance చూడాలా?"
#: What the fake model returns on the repair: own letters, no greeting, no names, a question.
REPAIRED = "మీ ఖాతాలో బాకీ ఎంత ఉందో చూడాలా?"


async def _no_voice(_tenant_id: uuid.UUID, _language: str) -> None:
    return None


async def _ready(
    language: str = "te-IN", jobs: tuple[str, ...] = ("answer_calls",)
) -> tuple[uuid.UUID, Any]:
    created = await admin_service.create_organization(
        name=BUSINESS,
        slug=f"open-{uuid.uuid4().hex[:8]}",
        vertical_template=TRADE,
        billing_email=None,
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    async with tenant_session(tenant_id) as session:
        await first_run.save_job(
            session,
            tenant_id=tenant_id,
            jobs=list(jobs),
            language_primary=language,
            languages_extra=[],
        )
        await first_run.save_brief(session, tenant_id=tenant_id, brief=BRIEF)
        await first_run.request_build(session, tenant_id=tenant_id, user_id=None)
        run = (await session.execute(text("SELECT * FROM first_runs"))).one()
    return tenant_id, run


def _drafted(opening: str, seen: list[ScriptBrief] | None = None, placed: str = "") -> Any:
    script = CATALOGUE[("custom", "answer_calls")].call_script(business=BUSINESS, language="te-IN")
    script = script.model_copy(update={"outbound_opening_line": placed})

    async def drafted(brief: ScriptBrief, **_kwargs: Any) -> SimpleNamespace:
        if seen is not None:
            seen.append(brief)
        return SimpleNamespace(
            script=script.model_copy(update={"opening_line": opening}),
            capability=SimpleNamespace(disclosure=None),
            earlier=(),
            model=None,
            usage=None,
        )

    return drafted


def _answer(value: str) -> SimpleNamespace:
    return SimpleNamespace(
        value=value, capability=SimpleNamespace(disclosure=None), earlier=(), model=None
    )


async def _build(tenant_id: uuid.UUID, run: Any) -> tuple[Any, str]:
    payload = {"tenant_id": str(tenant_id), "run_id": str(run.id), "build": 1}
    assert await worker.build_first_agent({}, payload) == "built"
    async with tenant_session(tenant_id) as session:
        after = (await session.execute(text("SELECT * FROM first_runs"))).one()
        line = (await load_agent_script(session, after.agent_id)).script.opening_line
    return after, line


def asked_description(asked: list[dict[str, Any]]) -> str:
    return str(asked[0]["brief"].description)


def _spends(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    spent: list[Any] = []

    async def meter(_session: Any, _tenant_id: uuid.UUID, what: Any) -> None:
        spent.append(what)

    monkeypatch.setattr(worker, "_meter", meter)
    return spent


async def test_a_drafted_opening_with_one_english_word_is_repaired_and_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, run = await _ready()
    asked: list[dict[str, Any]] = []

    async def write(brief: ScriptBrief, **kwargs: Any) -> SimpleNamespace:
        asked.append({"brief": brief, **kwargs})
        return _answer(REPAIRED)

    drafts: list[ScriptBrief] = []
    monkeypatch.setattr(worker, "pick_voice", _no_voice)
    monkeypatch.setattr(worker, "draft_script", _drafted(SLIPPED, drafts))
    monkeypatch.setattr(worker, "write_opening", write)
    spent = _spends(monkeypatch)

    after, line = await _build(tenant_id, run)

    # The script writer is asked for a line about this business, under the same rules.
    assert "what callers of this business usually want" in drafts[0].description
    assert OWN_LETTERS_RULE in drafts[0].description
    assert INTRODUCED_NAMES_RULE in drafts[0].description
    # The opening writer states the rules itself, for the form it is asked for.
    assert OWN_LETTERS_RULE not in asked_description(asked)
    assert after.build_steps["greeting"] == {"state": "repaired"}
    assert line == REPAIRED, "the repaired line, not the starter's"
    assert len(asked) == 1, "one writer call per greeting step"
    assert asked[0]["line"] == SLIPPED
    assert any("“balance”" in problem for problem in asked[0]["problems"])
    assert "Guntur" in asked[0]["brief"].description, "the business's own words reach it"
    assert asked[0]["brief"].introduced
    # The script's draft and the opening's repair are both charged.
    assert len(spent) == 2 and spent[1].value == REPAIRED


async def test_after_the_writer_refuses_no_ready_made_line_is_put_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-963: the drafted line, the business's own, stays and the step says why; the
    starter's line for every business of the type is never put in its place."""
    tenant_id, run = await _ready()
    calls: list[str] = []

    async def refuse(_brief: ScriptBrief, **_kwargs: Any) -> None:
        calls.append("asked")
        raise ProblemError.business_rule("assist_answer_unusable", "Not cleanly.")

    monkeypatch.setattr(worker, "pick_voice", _no_voice)
    monkeypatch.setattr(worker, "draft_script", _drafted(SLIPPED))
    monkeypatch.setattr(worker, "write_opening", refuse)
    spent = _spends(monkeypatch)

    after, line = await _build(tenant_id, run)

    assert after.build_steps["greeting"] == {
        "state": "unwritten",
        "reason": "assist_answer_unusable",
    }
    ready_made = {
        starter_opening(
            TRADE, ("answer_calls",), business=BUSINESS, language="te-IN", introduced=form
        )
        for form in (True, False)
    }
    assert line == SLIPPED and line not in ready_made
    assert calls == ["asked"], "bounded: one writer call"
    assert isinstance(spent[-1], ProblemError), "the refusal is metered too"


async def test_a_ready_made_line_comes_off_when_none_can_be_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, run = await _ready()

    async def refuse(_brief: Any, **_kwargs: Any) -> None:
        raise ProblemError.business_rule("assist_answer_unusable", "Not cleanly.")

    monkeypatch.setattr(worker, "pick_voice", _no_voice)
    monkeypatch.setattr(worker, "draft_script", refuse)
    monkeypatch.setattr(worker, "write_opening", refuse)
    _spends(monkeypatch)

    after, line = await _build(tenant_id, run)

    assert after.build_steps["greeting"] == {
        "state": "unwritten",
        "reason": "assist_answer_unusable",
    }
    assert line == ""


async def test_a_ready_made_scripts_line_is_replaced_by_one_written_for_the_business(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, run = await _ready()
    asked: list[dict[str, Any]] = []

    async def no_draft(_brief: Any, **_kwargs: Any) -> None:
        raise ProblemError.business_rule("assist_answer_unusable", "Not cleanly.")

    async def write(brief: ScriptBrief, **kwargs: Any) -> SimpleNamespace:
        asked.append(kwargs)
        return _answer(REPAIRED)

    monkeypatch.setattr(worker, "pick_voice", _no_voice)
    monkeypatch.setattr(worker, "draft_script", no_draft)
    monkeypatch.setattr(worker, "write_opening", write)
    _spends(monkeypatch)

    after, line = await _build(tenant_id, run)

    assert after.build_steps["script"]["state"] == "ready_made"
    assert after.build_steps["greeting"] == {"state": "written"}
    assert [(kw["line"], tuple(kw["problems"])) for kw in asked] == [("", ())]
    assert line == REPAIRED


async def test_with_no_time_left_the_writer_is_not_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, run = await _ready()

    async def never(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("the writer must not start past its latest point")

    monkeypatch.setattr(worker, "pick_voice", _no_voice)
    monkeypatch.setattr(worker, "draft_script", _drafted(SLIPPED))
    monkeypatch.setattr(worker, "write_opening", never)
    monkeypatch.setattr(worker, "OPENING_WRITER_LATEST_S", -1.0)
    _spends(monkeypatch)

    after, _line = await _build(tenant_id, run)

    assert after.build_steps["greeting"] == {"state": "unwritten", "reason": "no_time"}


#: The placed-call opening of the founder's call of 2 Nov 2026 after the introduction: "can we
#: talk now?" with two words in English letters (D-959).
PLACED_SLIPPED = "నేను రైతు ఖాతా యాప్ గురించి కాల్ చేస్తున్నాను అండి. ఇప్పుడు matladadaniki ok నా అండి?"
PLACED_REPAIRED = "మీ పంట లోన్ బాకీ గురించి కాల్ చేస్తున్నాను అండి, ఇప్పుడు మాట్లాడొచ్చా?"


async def test_a_both_agents_placed_opening_with_english_letters_is_repaired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, run = await _ready(jobs=("answer_calls", "call_new_leads"))
    asked: list[dict[str, Any]] = []

    async def write(brief: ScriptBrief, **kwargs: Any) -> SimpleNamespace:
        asked.append(kwargs)
        return _answer(PLACED_REPAIRED if kwargs.get("placed") else REPAIRED)

    monkeypatch.setattr(worker, "pick_voice", _no_voice)
    monkeypatch.setattr(worker, "draft_script", _drafted(REPAIRED, placed=PLACED_SLIPPED))
    monkeypatch.setattr(worker, "write_opening", write)
    spent = _spends(monkeypatch)

    after, _line = await _build(tenant_id, run)

    assert after.build_steps["placed_opening"] == {"state": "repaired"}
    placed = [kw for kw in asked if kw.get("placed")]
    assert len(placed) == 1, "one bounded writer call for the placed opening"
    assert placed[0]["line"] == PLACED_SLIPPED
    assert any("“matladadaniki”" in problem for problem in placed[0]["problems"])
    async with tenant_session(tenant_id) as session:
        script = (await load_agent_script(session, after.agent_id)).script
    assert script.outbound_opening_line == PLACED_REPAIRED
    assert any(getattr(s, "value", None) == PLACED_REPAIRED for s in spent), "metered"


async def test_a_both_agent_with_no_placed_opening_gets_one_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-963: the placed-call opening is required, so a script without one gets one written
    for the business rather than the language's line naming only the business."""
    tenant_id, run = await _ready(jobs=("answer_calls", "call_new_leads"))
    asked: list[dict[str, Any]] = []

    async def write(brief: ScriptBrief, **kwargs: Any) -> SimpleNamespace:
        asked.append(kwargs)
        return _answer(PLACED_REPAIRED if kwargs.get("placed") else REPAIRED)

    monkeypatch.setattr(worker, "pick_voice", _no_voice)
    monkeypatch.setattr(worker, "draft_script", _drafted(REPAIRED))
    monkeypatch.setattr(worker, "write_opening", write)
    _spends(monkeypatch)

    after, _line = await _build(tenant_id, run)

    assert after.build_steps["placed_opening"] == {"state": "written"}
    assert [(kw["line"], tuple(kw["problems"])) for kw in asked if kw.get("placed")] == [("", ())]
    async with tenant_session(tenant_id) as session:
        script = (await load_agent_script(session, after.agent_id)).script
    assert script.outbound_opening_line == PLACED_REPAIRED


async def test_an_unrepaired_placed_opening_is_cleared_and_said_unwritten(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, run = await _ready(jobs=("answer_calls", "call_new_leads"))

    async def refuse(_brief: ScriptBrief, **kwargs: Any) -> SimpleNamespace:
        if kwargs.get("placed"):
            raise ProblemError.business_rule("assist_answer_unusable", "Not cleanly.")
        return _answer(REPAIRED)

    monkeypatch.setattr(worker, "pick_voice", _no_voice)
    monkeypatch.setattr(worker, "draft_script", _drafted(REPAIRED, placed=PLACED_SLIPPED))
    monkeypatch.setattr(worker, "write_opening", refuse)
    _spends(monkeypatch)

    after, _line = await _build(tenant_id, run)

    assert after.build_steps["placed_opening"] == {
        "state": "unwritten",
        "reason": "assist_answer_unusable",
    }
    async with tenant_session(tenant_id) as session:
        script = (await load_agent_script(session, after.agent_id)).script
    assert script.outbound_opening_line == ""


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
    assert worker.greeting_fits(REPAIRED, "te-IN", names=names, introduced=True)
    found = opening_line.opening_problems(
        "నమస్కారం, Rytu Khata నుంచి", "te-IN", names=names, introduced=True
    )
    assert [problem.split(";")[0] for problem in found] == [
        "opening_line: does not end on a question",
        "opening_line: starts with a greeting",
    ]
    assert not worker.greeting_fits("చెప్పండి, ఏం కావాలి?", "te-IN", names=names)


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
    assert answer.value == REPAIRED and seen == ["ask"]


async def test_pips_proposal_repairs_the_opening_it_wrote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = await create_org_with_receptionist(
        name=BUSINESS,
        slug=f"prop-{uuid.uuid4().hex[:8]}",
        vertical_template=TRADE,
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = uuid.UUID(str(created["id"])), uuid.UUID(str(created["agent_id"]))
    async with tenant_session(tenant_id) as session:
        proposal = await script_proposals.request_proposal(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            mode="change",
            change="Rewrite my opening line for farmers checking their balance.",
            answers={},
            requested_by=uuid.uuid4(),
        )

    async def drafted(*_args: Any) -> Any:
        # Greets, but hands no turn over: no question.
        return SimpleNamespace(
            script=CallScript(opening_line="నమస్కారం, మీ ఖాతా చూస్తాను."),
            earlier=(),
            model="gemini-2.5-flash-lite",
            capability=SimpleNamespace(disclosure=None),
        )

    asked: list[dict[str, Any]] = []
    fixed = "నమస్కారం, మీ ఖాతాలో బాకీ చూడాలా?"

    async def write(brief: ScriptBrief, **kwargs: Any) -> SimpleNamespace:
        asked.append(kwargs)
        return _answer(fixed)

    metered: list[Any] = []

    async def meter(_session: Any, **kwargs: Any) -> None:
        metered.append(kwargs.get("result"))

    monkeypatch.setattr(proposal_worker, "_draft", drafted)
    monkeypatch.setattr(proposal_worker, "write_opening", write)
    monkeypatch.setattr(crm_assist, "meter_assist", meter)
    payload = {
        "tenant_id": str(tenant_id),
        "agent_id": str(agent_id),
        "proposal_id": str(proposal.id),
    }
    assert await proposal_worker.draft_script_proposal({}, payload) == "ready"

    async with tenant_session(tenant_id) as session:
        stored = await script_proposals.read_proposal(session, agent_id)
    assert stored is not None and stored.script is not None
    assert stored.script.opening_line == fixed
    assert any("does not end on a question" in p for p in asked[0]["problems"])
    assert len(metered) == 2, "the draft and the repair are both charged"


async def test_pips_proposal_repairs_the_placed_opening_it_wrote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = await create_org_with_receptionist(
        name=BUSINESS,
        slug=f"prop-{uuid.uuid4().hex[:8]}",
        vertical_template=TRADE,
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = uuid.UUID(str(created["id"])), uuid.UUID(str(created["agent_id"]))
    async with tenant_session(tenant_id) as session:
        proposal = await script_proposals.request_proposal(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            mode="change",
            change="Add an opening for the calls it makes about crop loans.",
            answers={},
            requested_by=uuid.uuid4(),
        )
        base = proposal.base_script.opening_line

    async def drafted(*_args: Any) -> Any:
        return SimpleNamespace(
            script=CallScript(opening_line=base, outbound_opening_line=PLACED_SLIPPED),
            earlier=(),
            model="gemini-2.5-flash-lite",
            capability=SimpleNamespace(disclosure=None),
        )

    asked: list[dict[str, Any]] = []

    async def write(brief: ScriptBrief, **kwargs: Any) -> SimpleNamespace:
        asked.append(kwargs)
        return _answer(PLACED_REPAIRED)

    monkeypatch.setattr(proposal_worker, "_draft", drafted)
    monkeypatch.setattr(proposal_worker, "write_opening", write)

    async def meter(_session: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(crm_assist, "meter_assist", meter)
    payload = {
        "tenant_id": str(tenant_id),
        "agent_id": str(agent_id),
        "proposal_id": str(proposal.id),
    }
    assert await proposal_worker.draft_script_proposal({}, payload) == "ready"

    async with tenant_session(tenant_id) as session:
        stored = await script_proposals.read_proposal(session, agent_id)
    assert stored is not None and stored.script is not None
    assert stored.script.outbound_opening_line == PLACED_REPAIRED
    assert [kw["placed"] for kw in asked] == [True], "the answering line it kept is not judged"
