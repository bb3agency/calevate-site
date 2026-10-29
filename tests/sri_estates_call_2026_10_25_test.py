"""The Sri Estates production calls of 25 Oct 2026 (D-888).

Outbound, Telugu, agent "Anjali", a property office in Guntur whose facts name only the town.
Four faults: it invented places, projects and how the caller had enquired ("you enquired on
our website"); at about 8 pm on a Sunday it offered "this weekend, Saturday or Sunday" and
agreed that tomorrow was Thursday; it never asked the caller's name; and it asked "two or three
BHK?" of a caller who wanted five.
"""

from __future__ import annotations

import importlib.util
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

from alembic.migration import MigrationContext
from alembic.operations import Operations
from apps.api.agents.lifecycle import create_agent
from apps.api.agents.script_builder import load_agent_script, rewrite_script
from apps.api.agents.test_conversations import RuleContext, Turn, hard_check, probe_scenario
from apps.api.agents.trade_playbooks import (
    BHK_AND_VISIT_LINES,
    PLAYBOOK_LANGUAGES,
    REPLACED_LINES,
    TRADE_WORDS,
    is_playbook_line,
)
from apps.api.agents.turn_checks import JOB_KINDS, conversation_problems
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.workers.example_line_refresh import JOB_NAME, refresh_example_lines
from calevate_shared.call_script import CallScript, compile_call_script
from calevate_shared.engine import (
    CONFIDENTIALITY_MARKER,
    DAYS_RULE,
    NAME_LINE,
    NAME_RULE,
    THIS_CALL_HEADER,
    TODAY_LINE,
    VOICE_STYLE_GUIDANCE,
    AgentConfig,
    compose_engine_prompt,
    engine_prompt_layers,
    today_value,
)
from sqlalchemy import create_engine, text
from tests.conftest import create_org_with_receptionist

OPENING = "నమస్కారం అండి, Sri Estates నుంచి కాల్ చేస్తున్నాను. ఇప్పుడు రెండు నిమిషాలు మాట్లాడొచ్చా?"
#: "You enquired on our website" — said when the caller asked which project they had seen.
WEBSITE = "మీరు మా వెబ్‌సైట్‌లో ఎంక్వైరీ చేశారు అండి. ఏ ఏరియా లో చూస్తున్నారు?"
STEM = "c8e4a1f7b2d5_real_estate_example_lines"


def _anjali(**over: Any) -> AgentConfig:
    fields: dict[str, Any] = {
        "tenant_id": "t",
        "agent_id": "a",
        "name": "Anjali",
        "business": "Sri Estates",
        "direction": "outbound",
        "language_primary": "te-IN",
        "system_prompt": compile_call_script(CallScript(schema_version=2, opening_line=OPENING)),
        "opening_line": "",
        "call_is_recorded": True,
    }
    return AgentConfig(**{**fields, **over})


# --- 1. say only what the facts or the caller said ---------------------------------------


def test_the_facts_rule_names_places_projects_availability_and_how_they_found_you() -> None:
    facts = dict(engine_prompt_layers(_anjali()))["business_facts"]
    assert "Say only what your facts or the caller said" in facts
    for named in ("a place", "a project", "stock or availability", "how they found you"):
        assert named in facts
    # Not knowing has one way to be said, in the cannot-help rule rather than a second rule.
    can_do = dict(engine_prompt_layers(_anjali()))["what_you_can_do"]
    assert '"the team will share that"' in can_do
    assert '"the team will share that"' not in facts


def test_telling_the_caller_where_they_enquired_fails_the_test() -> None:
    said = [Turn("నేను మీ ఏ ప్రాజెక్ట్ చూశానో గుర్తు లేదు.", WEBSITE)]
    kinds = [p.kind for p in conversation_problems(said)]
    assert kinds == ["invented_source"]
    assert "invented_source" in JOB_KINDS
    verdict = hard_check(probe_scenario("ai", "te-IN"), [Turn(said[0].said, WEBSITE)])
    assert verdict.verdict == "failed" and verdict.fix == "platform"
    assert "named a website or listing" in (verdict.reason or "")


def test_a_source_the_caller_or_the_facts_named_or_a_question_is_no_invention() -> None:
    caller_said = [Turn("నేను మీ వెబ్‌సైట్ లో చూశాను.", WEBSITE)]
    assert conversation_problems(caller_said) == []
    facts_say = [Turn("ఏ ప్రాజెక్ట్?", WEBSITE)]
    assert conversation_problems(facts_say, known="Leads come from our website form.") == []
    asked = [Turn("ఎవరు మీరు?", "మీరు మా వెబ్‌సైట్ చూశారా అండి?")]
    assert "invented_source" not in [p.kind for p in conversation_problems(asked)]
    searched = [Turn("ఏ ప్రాజెక్ట్?", WEBSITE, tools=["search_knowledge"])]
    assert conversation_problems(searched) == []


def test_the_test_run_judges_against_what_the_agent_was_given() -> None:
    said = [Turn("ఏ ప్రాజెక్ట్?", WEBSITE)]
    scenario = probe_scenario("ai", "te-IN")
    told = RuleContext(known="Callers usually find us on our website.")
    assert "website or listing" in (hard_check(scenario, said).reason or "")
    assert "website or listing" not in (hard_check(scenario, said, rules=told).reason or "")


# --- 2. today's date and weekday ----------------------------------------------------------


def test_today_is_the_ist_day_with_its_weekday() -> None:
    # 20:00 IST on Sunday 25 Oct 2026, when the agent offered "this weekend".
    assert today_value(datetime(2026, 10, 25, 14, 30, tzinfo=UTC)) == (
        "Sunday, 25 October 2026; then Mon 26 Oct, Tue 27 Oct, Wed 28 Oct, Thu 29 Oct, "
        "Fri 30 Oct, Sat 31 Oct"
    )
    # 19:00 UTC is already Monday in India.
    assert today_value(datetime(2026, 10, 25, 19, 0, tzinfo=UTC)).startswith(
        "Monday, 26 October 2026; then Tue 27 Oct"
    )


def test_every_agent_reads_today_and_the_name_and_the_rules_that_use_them() -> None:
    for direction in ("outbound", "inbound", "both"):
        prompt = compose_engine_prompt(_anjali(direction=direction))
        assert f"{THIS_CALL_HEADER}\n{TODAY_LINE}\n{NAME_LINE}" in prompt
        # The rules sit with the others after the client script, before the floor.
        for rule in (NAME_RULE, DAYS_RULE):
            assert prompt.index(rule) > prompt.index(OPENING)
            assert prompt.index(rule) < prompt.index(CONFIDENTIALITY_MARKER)
    assert "never a past one" in DAYS_RULE and "Ask which" in DAYS_RULE
    assert "Ask theirs, early and once" in NAME_RULE


# --- 3 and 4. open questions for what the caller decides, the next days for a visit -------


def test_choices_are_for_times_and_a_count_is_asked_openly() -> None:
    assert '"morning or evening?"' in VOICE_STYLE_GUIDANCE
    assert "never for counts or amounts" in VOICE_STYLE_GUIDANCE


def test_the_real_estate_plan_asks_the_size_openly_and_offers_the_next_days() -> None:
    words = TRADE_WORDS["real_estate"]
    assert words.details_ask["te-IN"] == "ఎన్ని బీహెచ్కే కావాలి అండి?"
    for said in (words.offer, words.lead_offer):
        for language in PLAYBOOK_LANGUAGES:
            line = said[language].lower()
            assert "weekend" not in line and "వీకెండ్" not in line and "वीकेंड" not in line
            assert "saturday" not in line and "సాటర్డే" not in line
    for old, new in REPLACED_LINES:
        assert set(old) == set(new) == set(PLAYBOOK_LANGUAGES)
        # An agent made with an old line may still take a business's own line in its place.
        assert all(is_playbook_line(line) for line in old.values())


def _revision() -> ModuleType:
    path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / f"{STEM}.py"
    spec = importlib.util.spec_from_file_location(f"_revision_{STEM}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_migrations_lines_are_the_shipped_plans() -> None:
    revision = _revision()
    assert revision.JOB == JOB_NAME
    shipped = [
        (old[language], new[language])
        for old, new in BHK_AND_VISIT_LINES
        for language in PLAYBOOK_LANGUAGES
    ]
    assert sorted(revision.REPLACEMENTS) == sorted(shipped)


async def _real_estate_account() -> uuid.UUID:
    created = await create_org_with_receptionist(
        name=f"Guntur Homes {uuid.uuid4().hex[:6]}",
        slug=f"gnt-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        created_by=None,
    )
    return uuid.UUID(str(created["id"]))


async def _caller_agent(tenant_id: uuid.UUID) -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        return await create_agent(
            session,
            tenant_id=tenant_id,
            name="Anjali",
            direction="outbound",
            language_primary="te-IN",
            starter="call_leads",
        )


async def _lines(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> list[str]:
    async with tenant_session(tenant_id) as session:
        loaded = await load_agent_script(session, agent_id)
    return [stage.sounds_like for stage in loaded.script.stages]


async def _put_lines(tenant_id: uuid.UUID, agent_id: uuid.UUID, swap: dict[str, str]) -> None:
    async with tenant_session(tenant_id) as session:
        script = (await load_agent_script(session, agent_id)).script
        stages = [
            stage.model_copy(update={"sounds_like": swap.get(stage.sounds_like, stage.sounds_like)})
            for stage in script.stages
        ]
        await rewrite_script(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            script=script.model_copy(update={"stages": stages}),
            notes="test: the lines an agent made before D-888 holds",
        )


def _back_to_old() -> dict[str, str]:
    return {new["te-IN"]: old["te-IN"] for old, new in BHK_AND_VISIT_LINES}


async def test_an_agent_made_with_the_old_lines_gets_the_new_ones_an_edited_line_is_kept() -> None:
    tenant_id = await _real_estate_account()
    agent_id = await _caller_agent(tenant_id)
    shipped = await _lines(tenant_id, agent_id)
    old_offer = BHK_AND_VISIT_LINES[2][0]["te-IN"]
    assert TRADE_WORDS["real_estate"].lead_offer["te-IN"] in shipped
    await _put_lines(tenant_id, agent_id, _back_to_old())
    held = await _lines(tenant_id, agent_id)
    assert old_offer in held
    # The owner rewrote the qualifying question's line themselves.
    owner_line = "మీ బడ్జెట్ ఎంత అండి?"
    qualify = TRADE_WORDS["real_estate"].qualify_ask["te-IN"]
    await _put_lines(tenant_id, agent_id, {qualify: owner_line})

    payload = {
        "tenant_id": str(tenant_id),
        "replacements": [list(pair) for pair in _revision().REPLACEMENTS],
    }
    assert await refresh_example_lines({}, payload) == "done"
    after = await _lines(tenant_id, agent_id)
    assert old_offer not in after
    assert after == [owner_line if line == qualify else line for line in shipped]
    # A redelivery finds nothing left to change.
    async with tenant_session(tenant_id) as session:
        version = (await load_agent_script(session, agent_id)).version
    assert await refresh_example_lines({}, payload) == "done"
    async with tenant_session(tenant_id) as session:
        assert (await load_agent_script(session, agent_id)).version == version


_QUEUED = text(
    "SELECT payload FROM outbox_messages WHERE job = :job AND status = 'pending' "
    "AND payload ->> 'tenant_id' = :tid"
)


async def test_the_migration_queues_only_accounts_holding_an_old_line() -> None:
    old_tenant = await _real_estate_account()
    await _put_lines(old_tenant, await _caller_agent(old_tenant), _back_to_old())
    new_tenant = await _real_estate_account()
    await _caller_agent(new_tenant)
    revision = _revision()
    url = (get_settings().alembic_database_url or get_settings().database_url).replace(
        "+asyncpg", "+psycopg"
    )
    sync = create_engine(url)
    try:
        with sync.connect() as connection:
            transaction = connection.begin()
            try:

                def queued(tenant: uuid.UUID) -> list[dict[str, Any]]:
                    rows = connection.execute(_QUEUED, {"job": JOB_NAME, "tid": str(tenant)})
                    return [r[0] if isinstance(r[0], dict) else json.loads(r[0]) for r in rows]

                with Operations.context(MigrationContext.configure(connection)):
                    revision.upgrade()
                    forward = queued(old_tenant)
                    assert [p["replacements"] for p in forward] == [
                        [list(pair) for pair in revision.REPLACEMENTS]
                    ]
                    assert queued(new_tenant) == []
                    revision.downgrade()
                    back = queued(new_tenant)
                    assert [p["replacements"] for p in back] == [
                        [[new, old] for old, new in revision.REPLACEMENTS]
                    ]
                    revision.upgrade()
            finally:
                transaction.rollback()
    finally:
        sync.dispose()
