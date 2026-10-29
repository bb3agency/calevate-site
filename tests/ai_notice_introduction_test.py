"""D-865 (founder, 23 Oct 2026): the AI notice introduces the agent.

In Telugu and Hindi the first turn is the salutation, the AI sentence as the agent's
introduction ("I am <name> from <business>, an AI assistant"), the opening line our writer
wrote (why the call is made, and its question, with no greeting and no names), then the other
notices switched on. With the AI notice off, or in another language, D-861's order stands:
the opening line, then the notices.
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
from apps.api.agents import lifecycle
from apps.api.agents.engine_limits import OPENING_TOO_LONG, refuse_over_engine_limits
from apps.api.agents.starters import starter_opening
from apps.api.agents.test_conversations import Turn
from apps.api.agents.turn_checks import (
    JOB_KINDS,
    SOUND_KINDS,
    conversation_problems,
    opened_again,
)
from apps.api.agents.verification import judge
from apps.api.compliance.disclosure import (
    ai_disclosure_for,
    caller_memory_notice_for,
    is_default_ai_disclosure,
    recording_notice_for,
)
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.api.engine.fake import DICTATED_SPEECH_CAPABILITIES, FakeEngine
from apps.workers.first_run import greeting_fits
from apps.workers.script_assist import INTRODUCED_OPENING_NOTE, ScriptBrief, language_problems
from calevate_shared.call_script import CallScript, compile_call_script
from calevate_shared.engine import (
    AgentConfig,
    AgentSnapshot,
    DisclosurePosture,
    compose_engine_prompt,
    compose_first_utterance,
    join_first_words,
    memory_goodbye_rule,
    notice_fields,
)
from calevate_shared.spoken_style import trial_call_opening
from sqlalchemy import create_engine, text
from tests.conftest import create_org_with_receptionist

BUSINESS = "Sri Estates"
NAME = "Anjali"
TE_AI = f"నేను {BUSINESS} నుండి {NAME}ని, ఏఐ అసిస్టెంట్‌ని మాట్లాడుతున్నాను అండి."
HI_AI_FEMALE = f"मैं {BUSINESS} से {NAME}, एआई असिस्टेंट, बात कर रही हूँ।"
HI_AI_MALE = f"मैं {BUSINESS} से Ravi, एआई असिस्टेंट, बात कर रहा हूँ।"
GREETING_LIMIT = 200


def _posture(
    language: str,
    *,
    ai: bool,
    name: str = NAME,
    gender: Any = None,
    memory: bool = False,
    business: str = BUSINESS,
) -> DisclosurePosture:
    return DisclosurePosture(
        ai_disclosure_line=ai_disclosure_for(
            language=language, business=business, name=name, gender=gender
        ),
        ai_disclosure_enabled=ai,
        recording_notice_line=recording_notice_for(language=language),
        recording_notice_enabled=True,
        caller_memory_notice_line=caller_memory_notice_for(language=language),
        caller_memory_enabled=memory,
    )


def _cfg(
    language: str, direction: str, opening: str, posture: DisclosurePosture, name: str = NAME
) -> AgentConfig:
    return AgentConfig(
        tenant_id=str(uuid.uuid4()),
        agent_id=str(uuid.uuid4()),
        name=name,
        business=BUSINESS,
        direction=direction,  # type: ignore[arg-type]
        language_primary=language,
        system_prompt=compile_call_script(CallScript(opening_line=opening), collect=[]),
        caller_memory_enabled=posture.caller_memory_enabled,
        **notice_fields(posture, call_is_recorded=True),
    )


def _opening(language: str, job: str, *, introduced: bool) -> str:
    return starter_opening(
        "real_estate", job, business=BUSINESS, language=language, introduced=introduced
    )


# --- the sentence ----------------------------------------------------------------------


def test_the_ai_sentence_is_the_founders_introduction() -> None:
    assert ai_disclosure_for(language="te-IN", business=BUSINESS, name=NAME) == TE_AI
    assert ai_disclosure_for(language="hi-IN", business=BUSINESS, name=NAME) == HI_AI_FEMALE
    assert (
        ai_disclosure_for(language="hi-IN", business=BUSINESS, name=NAME, gender="female")
        == HI_AI_FEMALE
    )
    assert (
        ai_disclosure_for(language="hi-IN", business=BUSINESS, name="Ravi", gender="male")
        == HI_AI_MALE
    )
    # Other languages keep their sentence and D-861's order: no founder wording yet.
    assert ai_disclosure_for(language="en-IN", business=BUSINESS, name=NAME) == (
        f"This is the AI assistant for {BUSINESS}."
    )


def test_a_default_sentence_is_recognised_in_either_gender_and_an_edited_one_is_not() -> None:
    for line in (HI_AI_FEMALE, HI_AI_FEMALE.replace("रही", "रहा")):
        assert is_default_ai_disclosure(line, language="hi-IN", business=BUSINESS, name=NAME)
    assert not is_default_ai_disclosure(
        "मैं Sri Estates की एआई सहायक हूँ।", language="hi-IN", business=BUSINESS, name=NAME
    )
    assert not is_default_ai_disclosure(TE_AI, language="te-IN", business=BUSINESS, name="Ravi")


# --- the first turn --------------------------------------------------------------------


def test_the_introduction_comes_after_the_salutation_and_before_the_opening_line() -> None:
    first = join_first_words(
        f"{TE_AI} ఈ కాల్ రికార్డ్ అవుతుంది.",
        "నమస్కారం అండి, ఇప్పుడు రెండు నిమిషాలు మాట్లాడొచ్చా?",
        ai_notice=TE_AI,
        language="te-IN",
    )
    # A greeting left at the opening line's start is dropped: the salutation already said it.
    assert first == (f"నమస్కారం అండి, {TE_AI} ఇప్పుడు రెండు నిమిషాలు మాట్లాడొచ్చా? ఈ కాల్ రికార్డ్ అవుతుంది.")


def test_with_the_ai_notice_off_the_opening_line_keeps_its_greeting_and_comes_first() -> None:
    opening = "నమస్కారం అండి, Sri Estates నుంచి కాల్ చేస్తున్నాను. ఇప్పుడు మాట్లాడొచ్చా?"
    rec = "ఈ కాల్ రికార్డ్ అవుతుంది."
    assert join_first_words(rec, opening, ai_notice="", language="te-IN") == f"{opening} {rec}"


def test_an_owners_sentence_that_greets_by_itself_gets_no_second_salutation() -> None:
    own = "నమస్కారం, ఇది Sri Estates ఏఐ అసిస్టెంట్."
    assert join_first_words(own, "ఏం కావాలి?", ai_notice=own, language="te-IN") == (f"ఏం కావాలి? {own}")


def test_the_prompt_quotes_the_new_first_turn_as_already_said() -> None:
    cfg = _cfg(
        "te-IN",
        "outbound",
        _opening("te-IN", "call_leads", introduced=True),
        _posture("te-IN", ai=True),
    )
    first = compose_first_utterance(cfg)
    assert first.startswith(f"నమస్కారం అండి, {TE_AI} ")
    assert f'Already said for you as your first turn: "{first}".' in compose_engine_prompt(cfg)


# --- the founder's three agents, measured against the 200-character greeting -------------


#: (a) Sri Estates / Anjali, Telugu, calling; (b) the same, answering; (c) Hindi, a man's
#: voice, calling. The opening lines are the starters' reviewed lines; a written one takes the
#: same place.
CASES = (
    ("a_te_calling", "te-IN", "call_leads", "outbound", NAME, None),
    ("b_te_answering", "te-IN", "answer_calls", "inbound", NAME, None),
    ("c_hi_calling_male", "hi-IN", "call_leads", "outbound", "Ravi", "male"),
)


def _first_words(
    case: str, *, ai: bool, memory: bool = False, business: str = BUSINESS
) -> AgentConfig:
    _key, language, job, direction, name, gender = next(c for c in CASES if c[0] == case)
    posture = _posture(language, ai=ai, name=name, gender=gender, memory=memory, business=business)
    opening = starter_opening(
        "real_estate", job, business=business, language=language, introduced=ai
    )
    return _cfg(language, direction, opening, posture, name=name)


def test_the_founders_agents_open_as_decided_and_fit_the_greeting() -> None:
    """The AI and recording notices on, then the AI notice off."""
    rec_te, rec_hi = recording_notice_for(language="te-IN"), recording_notice_for(language="hi-IN")
    expected = {
        # A call it places keeps the founder's "we are calling from" half (D-945).
        ("a_te_calling", True): (
            f"నమస్కారం అండి, {TE_AI} మేము Sri Estates నుండి కాల్ చేస్తున్నాము. "
            f"ఇప్పుడు మీరు మాట్లాడగలరా, ఫ్రీయేనా? {rec_te}"
        ),
        ("b_te_answering", True): (
            f"నమస్కారం అండి, {TE_AI} కాల్ చేసినందుకు థాంక్స్. చెప్పండి, ఏం కావాలి? {rec_te}"
        ),
        ("c_hi_calling_male", True): (
            f"नमस्ते जी, {HI_AI_MALE} हम Sri Estates की ओर से बोल रहे हैं। "
            f"क्या यह आपके लिए सही समय है? {rec_hi}"
        ),
        ("a_te_calling", False): (
            f"హాయ్ అండి, మేము Sri Estates నుండి కాల్ చేస్తున్నాము. ఇప్పుడు మీరు మాట్లాడగలరా, ఫ్రీయేనా? {rec_te}"
        ),
        ("b_te_answering", False): (
            f"నమస్కారం అండి, Sri Estates కి కాల్ చేసినందుకు థాంక్స్. చెప్పండి, ఏం కావాలి? {rec_te}"
        ),
        ("c_hi_calling_male", False): (
            f"नमस्ते, हम Sri Estates की ओर से बोल रहे हैं। क्या यह आपके लिए सही समय है? {rec_hi}"
        ),
    }
    engine = FakeEngine(name="thinnest", capabilities=DICTATED_SPEECH_CAPABILITIES)
    for (case, ai), words in expected.items():
        cfg = _first_words(case, ai=ai)
        assert compose_first_utterance(cfg) == words
        assert len(words) <= GREETING_LIMIT
        refuse_over_engine_limits(engine, cfg)


def test_the_memory_sentence_is_said_with_the_goodbye_never_in_the_opening() -> None:
    """Founder, 23 Oct 2026 (D-865): the opening no longer carries the memory sentence, so a
    Telugu agent with every notice on fits; the prompt tells it to say the sentence, word for
    word, with its goodbye."""
    engine = FakeEngine(name="thinnest", capabilities=DICTATED_SPEECH_CAPABILITIES)
    for case, _language, *_rest in CASES:
        with_memory = _first_words(case, ai=True, memory=True)
        without = _first_words(case, ai=True)
        first = compose_first_utterance(with_memory)
        assert first == compose_first_utterance(without)
        assert len(first) <= GREETING_LIMIT
        refuse_over_engine_limits(engine, with_memory)
        sentence = with_memory.caller_memory_notice
        assert sentence and sentence not in first
        rule = memory_goodbye_rule(with_memory)
        assert f'"{sentence}"' in rule
        prompt = compose_engine_prompt(with_memory)
        assert rule in prompt
        assert memory_goodbye_rule(without) == ""
        assert "Before you end a call with a goodbye" not in compose_engine_prompt(without)


def test_a_long_business_name_is_refused_naming_it() -> None:
    engine = FakeEngine(name="thinnest", capabilities=DICTATED_SPEECH_CAPABILITIES)
    long_business = "Sri Lakshmi Venkateswara Estates and Developers Private Limited"
    cfg = _first_words("a_te_calling", ai=True, business=long_business)
    assert len(compose_first_utterance(cfg)) > GREETING_LIMIT
    with pytest.raises(ProblemError) as refused:
        refuse_over_engine_limits(engine, cfg)
    assert refused.value.code == OPENING_TOO_LONG
    assert "its own name" in str(refused.value.detail)


def test_a_test_call_line_after_the_introduction_says_only_why_it_rings() -> None:
    assert trial_call_opening("te-IN", name=NAME, business=BUSINESS, introduced=True) == (
        "ఇది మీ కొత్త రిసెప్షనిస్ట్ టెస్ట్ కాల్. ఇప్పుడు మాట్లాడొచ్చా?"
    )
    # English has no introduction: its own line, which says who is calling.
    assert NAME in str(trial_call_opening("en-IN", name=NAME, business=BUSINESS, introduced=True))


# --- the writers -----------------------------------------------------------------------


def _script(opening: str) -> CallScript:
    return CallScript(opening_line=opening)


@pytest.mark.parametrize(
    ("opening", "refused"),
    [
        ("నమస్కారం అండి, ఇప్పుడు మాట్లాడొచ్చా?", "greeting"),
        ("Sri Estates నుంచి కాల్ చేస్తున్నాను. ఇప్పుడు మాట్లాడొచ్చా?", "Sri Estates"),
        ("ఇప్పుడు రెండు నిమిషాలు మాట్లాడొచ్చా?", None),
    ],
)
def test_a_written_opening_after_the_introduction_is_sent_back_for_greeting_or_names(
    opening: str, refused: str | None
) -> None:
    names = (BUSINESS, NAME)
    problems = language_problems(_script(opening), "te-IN", names=names, introduced=True)
    if refused is None:
        assert problems == []
        assert greeting_fits(opening, "te-IN", names=names, introduced=True)
    else:
        assert any(refused in problem for problem in problems), problems
        assert not greeting_fits(opening, "te-IN", names=names, introduced=True)
    # Without the introduction the same lines are judged as before.
    assert not any(
        "introduction" in p for p in language_problems(_script(opening), "te-IN", names=names)
    )


def test_without_the_introduction_the_first_run_greeting_must_greet_or_say_who_calls() -> None:
    assert not greeting_fits("ఇప్పుడు రెండు నిమిషాలు మాట్లాడొచ్చా?", "te-IN", names=(BUSINESS, NAME))
    assert greeting_fits(
        _opening("te-IN", "call_leads", introduced=False), "te-IN", names=(BUSINESS, NAME)
    )


def test_the_brief_tells_the_writer_when_the_agent_introduces_itself() -> None:
    assert INTRODUCED_OPENING_NOTE in ScriptBrief(introduced=True).user_message()
    assert INTRODUCED_OPENING_NOTE not in ScriptBrief().user_message()


# --- the practice check ----------------------------------------------------------------


def test_a_reply_that_says_who_it_is_is_not_a_second_greeting() -> None:
    assert opened_again(f"{TE_AI} మీకు ఏ ఏరియాలో ఫ్లాట్ కావాలి?") is None
    assert opened_again("नमस्ते जी, मैं Anjali बात कर रही हूँ।") is not None


# --- a rename, a new voice ---------------------------------------------------------------


async def _agent(language: str) -> tuple[uuid.UUID, uuid.UUID, str]:
    business = f"Rename Estates {uuid.uuid4().hex[:6]}"
    created = await create_org_with_receptionist(
        name=business,
        slug=f"intro-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language=language,
        created_by=None,
    )
    return uuid.UUID(str(created["id"])), uuid.UUID(str(created["agent_id"])), business


async def _lines(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> Any:
    async with tenant_session(tenant_id) as session:
        return (
            await session.execute(
                text(
                    "SELECT name, ai_disclosure_line, disclosure_line, recording_notice_line "
                    "FROM agents WHERE id = :a"
                ),
                {"a": agent_id},
            )
        ).one()


async def test_a_rename_re_renders_the_default_sentence_and_its_bundle() -> None:
    tenant_id, agent_id, business = await _agent("te-IN")
    async with tenant_session(tenant_id) as session:
        await lifecycle.update_agent(session, tenant_id=tenant_id, agent_id=agent_id, name="Priya")
    row = await _lines(tenant_id, agent_id)
    assert row.ai_disclosure_line == ai_disclosure_for(
        language="te-IN", business=business, name="Priya"
    )
    assert row.disclosure_line == f"{row.ai_disclosure_line} {row.recording_notice_line}"


async def test_a_rename_leaves_a_sentence_somebody_wrote_alone() -> None:
    tenant_id, agent_id, _business = await _agent("te-IN")
    own = "ఇది మా ఏఐ అసిస్టెంట్."
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET ai_disclosure_line = :l WHERE id = :a"),
            {"l": own, "a": agent_id},
        )
        await lifecycle.update_agent(session, tenant_id=tenant_id, agent_id=agent_id, name="Priya")
    assert (await _lines(tenant_id, agent_id)).ai_disclosure_line == own


async def test_a_mans_voice_gives_the_hindi_sentence_the_mans_verb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id, business = await _agent("hi-IN")

    async def _male(_session: Any, voice_id: str | None) -> str | None:
        return "male" if voice_id else None

    monkeypatch.setattr(lifecycle, "voice_gender", _male)
    async with tenant_session(tenant_id) as session:
        name = str((await _lines(tenant_id, agent_id)).name)
        await session.execute(
            text("UPDATE agents SET engine_voice_id = 'v-male' WHERE id = :a"), {"a": agent_id}
        )
        await lifecycle._rerender_ai_line(
            session, tenant_id=tenant_id, agent_id=agent_id, old_name=name, old_voice=None
        )
    line = (await _lines(tenant_id, agent_id)).ai_disclosure_line
    assert line == ai_disclosure_for(language="hi-IN", business=business, name=name, gender="male")
    assert line.endswith("बात कर रहा हूँ।")


# --- the migration ---------------------------------------------------------------------

STEM = "f2b7c4e9d815_ai_notice_introduces_agent"


def _revision() -> ModuleType:
    path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / f"{STEM}.py"
    spec = importlib.util.spec_from_file_location(f"_revision_{STEM}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_migrations_shapes_match_todays_templates() -> None:
    revision = _revision()
    assert re.fullmatch(revision.TE_NEW, TE_AI)
    assert re.fullmatch(revision.HI_NEW, HI_AI_FEMALE)
    assert re.fullmatch(revision.HI_NEW, HI_AI_MALE)


_SET = text(
    "UPDATE agents SET name = :name, ai_disclosure_line = :ai, recording_notice_line = :rec, "
    "disclosure_line = :ai || ' ' || :rec, engine_voice_id = :voice, status = 'live', "
    "engine_agent_ref = :ref WHERE id = :id"
)
_ROW = text("SELECT ai_disclosure_line, disclosure_line FROM agents WHERE id = :id")
_RUNS = text(
    "SELECT count(*) FROM live_apply_runs WHERE scope = 'platform' AND reasons ? :reason "
    "AND status = 'pending'"
)


async def test_previous_defaults_take_the_agents_name_edits_are_kept_and_it_reverses() -> None:
    te_agent, hi_agent, hi_male_agent, edited_agent = [(await _agent("te-IN"))[1] for _ in range(4)]
    revision = _revision()
    voice = f"test-male-{uuid.uuid4().hex[:8]}"
    url = (get_settings().alembic_database_url or get_settings().database_url).replace(
        "+asyncpg", "+psycopg"
    )
    te_old = f"ఇది {BUSINESS} ఏఐ అసిస్టెంట్."
    hi_old = f"मैं {BUSINESS} का एआई असिस्टेंट हूँ।"
    edited = f"{BUSINESS} తరఫున మాట్లాడుతున్నది ఏఐ అసిస్టెంట్."
    rec_te, rec_hi = recording_notice_for(language="te-IN"), recording_notice_for(language="hi-IN")
    sync = create_engine(url)
    try:
        with sync.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY"))
                connection.execute(
                    text(
                        "INSERT INTO platform_voice_catalog (voice_id, engine_voice_id, label, "
                        "tts_model, provider, synced_at, gender) VALUES (:v, :v, 'Ravi', 'm', "
                        "'cartesia', now(), 'Male')"
                    ),
                    {"v": voice},
                )
                for agent, name, ai, rec, voice_id in (
                    (te_agent, NAME, te_old, rec_te, None),
                    (hi_agent, NAME, hi_old, rec_hi, None),
                    (hi_male_agent, "Ravi", hi_old, rec_hi, voice),
                    (edited_agent, NAME, edited, rec_te, None),
                ):
                    connection.execute(
                        _SET,
                        {
                            "name": name,
                            "ai": ai,
                            "rec": rec,
                            "voice": voice_id,
                            "ref": f"ref-{agent}",
                            "id": agent,
                        },
                    )
                before = connection.execute(_RUNS, {"reason": revision.REASON}).scalar_one()
                with Operations.context(MigrationContext.configure(connection)):
                    revision.upgrade()
                    connection.execute(text("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY"))

                    def row(agent: uuid.UUID) -> tuple[str, str]:
                        found = connection.execute(_ROW, {"id": agent}).one()
                        return str(found[0]), str(found[1])

                    assert row(te_agent) == (TE_AI, f"{TE_AI} {rec_te}")
                    assert row(hi_agent) == (HI_AI_FEMALE, f"{HI_AI_FEMALE} {rec_hi}")
                    assert row(hi_male_agent) == (HI_AI_MALE, f"{HI_AI_MALE} {rec_hi}")
                    assert row(edited_agent)[0] == edited
                    after = connection.execute(_RUNS, {"reason": revision.REASON}).scalar_one()
                    assert after == before + 1
                    revision.downgrade()
                    connection.execute(text("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY"))
                    assert row(te_agent) == (te_old, f"{te_old} {rec_te}")
                    assert row(hi_agent) == (hi_old, f"{hi_old} {rec_hi}")
                    assert row(hi_male_agent) == (hi_old, f"{hi_old} {rec_hi}")
                    assert row(edited_agent)[0] == edited
                    revision.upgrade()
                    assert row(hi_male_agent)[0] == HI_AI_MALE
            finally:
                transaction.rollback()
    finally:
        sync.dispose()


# --- the memory sentence with the goodbye: read back and practice check (D-865) ----------


def test_the_read_back_refuses_a_prompt_without_the_goodbye_rule() -> None:
    engine = FakeEngine(name="thinnest", capabilities=DICTATED_SPEECH_CAPABILITIES)
    cfg = _first_words("a_te_calling", ai=True, memory=True)
    held = AgentSnapshot(
        engine_agent_ref="ag_1",
        system_prompt=compose_engine_prompt(cfg),
        system_prompt_readable=True,
        greeting=compose_first_utterance(cfg),
        greeting_readable=True,
    )
    assert judge(engine, cfg, held).state != "not_applied"
    dropped = held.model_copy(
        update={"system_prompt": compose_engine_prompt(cfg).replace(memory_goodbye_rule(cfg), "")}
    )
    verdict = judge(engine, cfg, dropped)
    assert verdict.state == "not_applied"
    assert "memory notice" in verdict.detail


MEMORY = caller_memory_notice_for(language="te-IN")


def test_a_goodbye_without_the_memory_sentence_is_noted_not_failed() -> None:
    closing = [Turn(said="సరే, థాంక్స్ అండి.", reply="సరే అండి, బై!")]
    problems = conversation_problems(closing, memory_notice=MEMORY)
    assert [p.kind for p in problems] == ["memory_not_said"]
    assert "memory_not_said" in SOUND_KINDS and "memory_not_said" not in JOB_KINDS
    said = [Turn(said="సరే, థాంక్స్ అండి.", reply=f"సరే అండి, {MEMORY} బై!")]
    assert conversation_problems(said, memory_notice=MEMORY) == []
    # No memory on, or the caller is still asking: nothing to note.
    assert conversation_problems(closing) == []
    asking = [Turn(said="ధర ఎంత?", reply="వన్ ట్వంటీ రూపీస్, బై!")]
    kinds = [p.kind for p in conversation_problems(asking, memory_notice=MEMORY)]
    assert "memory_not_said" not in kinds
