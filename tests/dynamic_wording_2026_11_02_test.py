"""The founder's Rytu Khata call of 2 Nov 2026: no fixed line reaches a call (D-961..D-963).

The agent told a caller "మీరు ఇంతకు ముందు మా దగ్గర ఎంక్వైరీ చేశారు కదా, ఇంకా కావాలా అండి?",
the ready-made plan's line for every business, with nothing on the call saying he had
enquired; and it offered "the team will call you, tell me your name" on a question its knowledge
answered. Our code keeps the STRUCTURE of a good call; what the person hears is written for the
business, and a claim about the person is said only when the call's own data says so.
"""

from __future__ import annotations

import importlib.util
import re
import uuid
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from apps.api.agents.lifecycle import create_agent
from apps.api.agents.retired_lines import RETIRED_LINES, is_retired_line
from apps.api.agents.script_builder import (
    load_agent_script,
    read_draft,
    rewrite_script,
    save_draft,
)
from apps.api.agents.starters import CATALOGUE, TRADES
from apps.api.agents.trade_playbooks import JOB_SHAPES, playbook_for
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.workers.retired_line_strip import (
    AUDIT_ACTION,
    JOB_NAME,
    strip_retired_example_lines,
)
from apps.workers.script_assist import UnusableAnswerError, drafted_script
from calevate_shared.call_script import CallScript
from calevate_shared.engine import (
    CALL_REASON_RULE,
    NAME_RULE,
    START_OF_CALL_HEADER,
    AgentConfig,
    compose_engine_prompt,
)
from sqlalchemy import create_engine, text
from tests.conftest import create_org_with_receptionist

#: The line the founder heard on 2 Nov 2026: the plan's ready-made reason for every business.
FOUNDERS_LINE = "మీరు ఇంతకు ముందు మా దగ్గర ఎంక్వైరీ చేశారు కదా, ఇంకా కావాలా అండి?"
STEM = "e962a4c1d7b3_retired_example_lines_off_agents"

#: A sentence that says what the person did, which only the call's data may say.
_CLAIM = re.compile(
    r"showed interest|still interested|interest in \{?business|just made an enquiry|"
    r"enquiry they just made|they enquired|left it in an enquiry|asked about .* earlier",
    re.IGNORECASE,
)


def _claims(text: str) -> list[str]:
    """Sentences of `text` that say what the person did without hanging it on THIS CALL."""
    return [
        s for s in re.split(r"(?<=[.?!])\s+", text) if _CLAIM.search(s) and "THIS CALL" not in s
    ]


def _cfg(direction: str, *, opening: str = "") -> AgentConfig:
    return AgentConfig(
        tenant_id="t",
        agent_id="a",
        name="Anjali",
        business="Rytu Khata",
        direction=direction,  # type: ignore[arg-type]
        language_primary="te-IN",
        system_prompt=f"[OPENING]\n{opening}" if opening else "",
        opening_line="",
        call_is_recorded=True,
    )


# --- slice 1: the reason for a call comes from the call's data -----------------------------


def test_no_plan_or_starter_tells_the_agent_what_the_person_did() -> None:
    for trade, basics in TRADES.items():
        for job in JOB_SHAPES:
            plan = playbook_for(trade, job, basics)
            for step in plan.steps:
                assert not _claims(step.instruction), (trade, job, step.title)
            for asked, does in plan.objections:
                assert not _claims(does), (trade, job, asked)
    for key, starter in CATALOGUE.items():
        for said in (starter.identity, starter.goal, starter.outbound_purpose):
            assert not _claims(said), (key, said)


def test_where_did_you_get_my_number_is_answered_from_the_call() -> None:
    plan = playbook_for("custom", "call_leads", TRADES["custom"])
    answer = dict(plan.objections)["Where did you get my number?"]
    assert "THIS CALL" in answer


def test_an_agent_that_places_calls_claims_nothing_the_call_does_not_say() -> None:
    for direction in ("outbound", "both"):
        prompt = compose_engine_prompt(_cfg(direction, opening="నమస్కారం అండి, ఇప్పుడు మాట్లాడొచ్చా?"))
        assert CALL_REASON_RULE in prompt and START_OF_CALL_HEADER in prompt
    assert CALL_REASON_RULE not in compose_engine_prompt(_cfg("inbound", opening="హలో అండి?"))


def test_the_agent_helps_from_its_knowledge_before_a_call_back_or_a_name() -> None:
    prompt = compose_engine_prompt(_cfg("both"))
    assert "Answer what your knowledge holds; being an AI is no reason not to." in prompt
    assert prompt.index("being an AI is no reason") < prompt.index("No answer after searching")
    # Not early, and since D-965 not after the first answer either: only when it is used.
    assert "early" not in NAME_RULE and "first answer" not in NAME_RULE


# --- slice 2: plans are structure only; their old lines are refused and taken off ----------


def test_the_founders_line_is_retired_and_no_ready_made_script_carries_a_line() -> None:
    assert is_retired_line(f"  {FOUNDERS_LINE} ")
    # Every trade's six lines in three languages, the three shared ones, and the lines the
    # D-888 and D-894 corrections replaced.
    assert len(RETIRED_LINES) == 171
    for starter in CATALOGUE.values():
        for language in ("te-IN", "hi-IN", "en-IN"):
            script = starter.call_script(business="Rytu Khata", language=language)
            assert all(not stage.sounds_like for stage in script.stages)


def _draft_raw(line: str) -> dict[str, Any]:
    return {
        "stages": [
            {"name": "Say why you called", "instruction": "Say why you call.", "sounds_like": line}
        ]
    }


def test_the_writer_is_sent_back_a_retired_line_but_keeps_the_owners() -> None:
    with pytest.raises(UnusableAnswerError, match="ready-made line written for every business"):
        drafted_script(_draft_raw(FOUNDERS_LINE), language="te-IN")
    # The owner's own words, which the script was written from, are theirs to keep.
    kept = drafted_script(_draft_raw(FOUNDERS_LINE), language="te-IN", allowed=FOUNDERS_LINE)
    assert kept.stages[0].sounds_like == FOUNDERS_LINE


async def _account() -> uuid.UUID:
    created = await create_org_with_receptionist(
        name=f"Rytu Khata {uuid.uuid4().hex[:6]}",
        slug=f"rk-{uuid.uuid4().hex[:8]}",
        vertical_template=None,
        billing_email=None,
        created_by=None,
    )
    return uuid.UUID(str(created["id"]))


async def _agent(tenant_id: uuid.UUID) -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        return await create_agent(
            session,
            tenant_id=tenant_id,
            name="Anjali",
            direction="outbound",
            language_primary="te-IN",
            starter="call_leads",
        )


async def _hold(tenant_id: uuid.UUID, agent_id: uuid.UUID, lines: dict[int, str]) -> None:
    """Put `lines` (step index -> line) on the agent's script, as an agent made before
    D-962 holds them, and the same script into its autosaved draft."""
    async with tenant_session(tenant_id) as session:
        script = (await load_agent_script(session, agent_id)).script
        stages = [
            stage.model_copy(update={"sounds_like": lines.get(i, stage.sounds_like)})
            for i, stage in enumerate(script.stages)
        ]
        held = script.model_copy(update={"stages": stages})
        await rewrite_script(
            session, tenant_id=tenant_id, agent_id=agent_id, script=held, notes="test: pre-D-962"
        )
        await save_draft(session, agent_id, held)


async def _lines(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> tuple[list[str], list[str]]:
    async with tenant_session(tenant_id) as session:
        script: CallScript = (await load_agent_script(session, agent_id)).script
        draft = await read_draft(session, agent_id)
    assert draft is not None
    return [s.sounds_like for s in script.stages], [s.sounds_like for s in draft.script.stages]


async def test_a_live_agent_loses_the_retired_lines_and_keeps_the_owners() -> None:
    tenant_id = await _account()
    agent_id = await _agent(tenant_id)
    owners = "మీ పంట ఏంటి అండి?"
    await _hold(tenant_id, agent_id, {1: FOUNDERS_LINE, 2: owners})
    async with tenant_session(tenant_id) as session:
        before = (await load_agent_script(session, agent_id)).version

    assert await strip_retired_example_lines({}, {"tenant_id": str(tenant_id)}) == "done"
    script_lines, draft_lines = await _lines(tenant_id, agent_id)
    for lines in (script_lines, draft_lines):
        assert FOUNDERS_LINE not in lines and lines[1] == "" and lines[2] == owners
    async with tenant_session(tenant_id) as session:
        after = (await load_agent_script(session, agent_id)).version
    assert after is not None and before is not None and after > before
    assert await _audited(tenant_id, agent_id) == 1
    # A redelivery finds nothing left: no new version, no second audit row.
    assert await strip_retired_example_lines({}, {"tenant_id": str(tenant_id)}) == "done"
    async with tenant_session(tenant_id) as session:
        assert (await load_agent_script(session, agent_id)).version == after
    assert await _audited(tenant_id, agent_id) == 1


async def _audited(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> int:
    async with tenant_session(tenant_id) as session:
        return int(
            (
                await session.execute(
                    text("SELECT count(*) FROM audit_log WHERE action = :a AND object_id = :o"),
                    {"a": AUDIT_ACTION, "o": str(agent_id)},
                )
            ).scalar_one()
        )


def _revision() -> ModuleType:
    path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / f"{STEM}.py"
    spec = importlib.util.spec_from_file_location(f"_revision_{STEM}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_QUEUED = text(
    "SELECT count(*) FROM outbox_messages WHERE job = :job AND status = 'pending' "
    "AND payload ->> 'tenant_id' = :tid"
)


async def test_the_migration_queues_only_accounts_whose_agents_have_lines() -> None:
    held = await _account()
    await _hold(held, await _agent(held), {1: FOUNDERS_LINE})
    clean = await _account()
    await _agent(clean)
    revision = _revision()
    assert revision.JOB == JOB_NAME
    url = (get_settings().alembic_database_url or get_settings().database_url).replace(
        "+asyncpg", "+psycopg"
    )
    sync = create_engine(url)
    try:
        with sync.connect() as connection:
            transaction = connection.begin()
            try:
                with Operations.context(MigrationContext.configure(connection)):
                    revision.upgrade()

                    def queued(tenant: uuid.UUID) -> int:
                        return int(
                            connection.execute(
                                _QUEUED, {"job": JOB_NAME, "tid": str(tenant)}
                            ).scalar_one()
                        )

                    assert queued(held) == 1 and queued(clean) == 0
            finally:
                transaction.rollback()
    finally:
        sync.dispose()


# --- slice 3: a ready-made script takes the business's lines, block by block ---------------


def test_a_several_job_script_takes_each_blocks_business_lines_in_order() -> None:
    from apps.api.agents.starters import _line_sets

    assert _line_sets(("answer_calls", "call_new_leads", "call_leads")) == (
        "answer_calls",
        "call_leads",
    )
    assert _line_sets(("call_new_leads", "call_leads")) == ("call_leads",)


def test_a_starter_is_recognised_by_its_structure_whatever_its_words() -> None:
    from apps.api.agents.starters import starter_vertical_of, with_example_lines

    script = CATALOGUE[("retail", "answer_calls")].call_script(
        business="Rytu Khata", language="te-IN"
    )
    worded = with_example_lines(
        script.model_copy(update={"opening_line": "నమస్కారం అండి, రైతు ఖాతా కి కాల్ చేశారా?"}),
        [f"లైన్ {i}" for i in range(len(script.stages))],
    )
    found = starter_vertical_of(
        worded.model_dump(mode="json"), job="answer_calls", business="Rytu Khata", language="te-IN"
    )
    assert found == "retail"
    edited = worded.model_copy(update={"goal": "The owner's own goal."})
    assert (
        starter_vertical_of(
            edited.model_dump(mode="json"),
            job="answer_calls",
            business="Rytu Khata",
            language="te-IN",
        )
        is None
    )


# --- slice 4: openings are written for the business; the ready-made one is a logged gap ----


def test_the_opening_writer_never_claims_what_the_person_did() -> None:
    from apps.workers.opening_line import OPENING_WRITER_INSTRUCTION, PLACED_TASK

    assert "never that the person enquired, asked or showed interest" in (
        OPENING_WRITER_INSTRUCTION
    )
    assert "never that the person enquired or asked" in PLACED_TASK


def test_a_both_agent_without_its_own_placed_opening_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from apps.api.agents.service import dial_first_words

    row: dict[str, Any] = {
        "id": uuid.uuid4(),
        "direction": "both",
        "name": "Anjali",
        "language_primary": "te-IN",
        "business_name": "Rytu Khata",
        "prompt": "[OPENING]\nహలో అండి, ఏం కావాలి?",
        "ai_disclosure_line": "",
        "ai_disclosure_enabled": False,
        "recording_notice_line": "",
        "recording_notice_enabled": False,
        "caller_memory_notice_line": "",
        "caller_memory_enabled": False,
    }
    with caplog.at_level("WARNING"):
        said = dial_first_words(row, test_call=False, call_is_recorded=True)  # type: ignore[arg-type]
    assert said is not None and "Rytu Khata" in said
    assert any(r.getMessage() == "placed_call_opening_ready_made" for r in caplog.records)


# --- slice 5: the platform's illustrations are neutral --------------------------------------


def test_how_to_speak_illustrates_no_trade_or_language() -> None:
    from calevate_shared.engine import VOICE_STYLE_GUIDANCE

    for word in ("kg", "crore"):
        assert word not in VOICE_STYLE_GUIDANCE
