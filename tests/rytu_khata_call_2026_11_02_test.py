"""The founder's Rytu Khata call of 2 Nov 2026 (D-965): a farmer following app steps on his
phone. The agent took a one-word "no" to "can we talk now?" as a yes, asked a question after
every "హా" that only acknowledged a step, closed on a caller who did not know which crop to
pick, asked his name before helping, and said who was calling twice. The code keeps the
call's structure only; no spoken line here is ours to put on a call (D-915)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from apps.api.agents import script_builder, script_proposals
from apps.api.crm import assist as crm_assist
from apps.api.db.session import tenant_session
from apps.workers import script_proposal as worker
from apps.workers.opening_line import WrittenOpening, rewrite_problem
from calevate_shared.call_script import (
    RETIRED_FAQ_FALLBACK,
    CallScript,
    FaqEntry,
    compile_call_script,
)
from calevate_shared.engine import (
    CALLER_MEMORY_GUIDANCE,
    ENGINE_MEMORY_RULE,
    NAME_RULE,
    OPENING_CONTINUES_RULE,
    VOICE_STYLE_GUIDANCE,
    AgentConfig,
    compose_engine_prompt,
    compose_first_utterance,
    introduction_names,
    join_first_words,
)
from calevate_shared.opening_notices import NONE_SAID
from tests.conftest import create_org_with_receptionist

AI_NOTICE = "నేను రైతు ఖాతా నుండి లక్ష్మిని, ఏఐ అసిస్టెంట్‌ని మాట్లాడుతున్నాను అండి."
INTRO = "నమస్కారం అండి, రైతు ఖాతా నుండి మాట్లాడుతున్నాను."
QUESTION = "ఏ పంట గురించి తెలుసుకోవాలి అండి?"


def _cfg(**over: Any) -> AgentConfig:
    fields: dict[str, Any] = {
        "tenant_id": "t",
        "agent_id": "a",
        "name": "లక్ష్మి",
        "business": "రైతు ఖాతా",
        "direction": "inbound",
        "language_primary": "te-IN",
        "system_prompt": compile_call_script(
            CallScript(schema_version=2, opening_line=f"{INTRO} {QUESTION}")
        ),
        "opening_line": AI_NOTICE,
        "ai_notice": AI_NOTICE,
        "call_is_recorded": True,
    }
    return AgentConfig(**{**fields, **over})


# --- 1. a no to "can we talk now?" is not a yes -------------------------------------------


def test_only_a_hello_or_yes_goes_on_and_a_no_asks_when_or_closes() -> None:
    rule = OPENING_CONTINUES_RULE
    assert "a word or two" not in rule.lower()
    assert "A hello or yes, in any language, is a yes" in rule
    assert "A no, busy or later? Ask when suits them, or close politely." in rule
    assert "re-ask if now suits" in rule, "asking when is not asking again whether now"


# --- 2. a bare OK after a step means go on ------------------------------------------------


def test_a_bare_ok_asks_again_only_after_a_question() -> None:
    assert 'Unclear, or a bare "OK" to your question? Ask one thing again' in VOICE_STYLE_GUIDANCE
    assert '"OK" after one: the next.' in VOICE_STYLE_GUIDANCE
    assert 'A bare "OK"? Ask one thing' not in VOICE_STYLE_GUIDANCE


# --- 3. never an invented earlier conversation ---------------------------------------------


def test_an_engine_that_recaps_still_carries_the_no_invented_past_rule() -> None:
    kept = compose_engine_prompt(_cfg(caller_memory_enabled=True, caller_memory_in_engine=True))
    assert ENGINE_MEMORY_RULE in kept
    assert CALLER_MEMORY_GUIDANCE not in kept
    assert "never invent one" in ENGINE_MEMORY_RULE
    assert ENGINE_MEMORY_RULE not in compose_engine_prompt(_cfg())


# --- 4. one introduction -------------------------------------------------------------------


def test_an_opening_that_introduces_loses_that_sentence_after_the_ai_introduction() -> None:
    spoken = compose_first_utterance(_cfg())
    assert spoken.count("రైతు ఖాతా") == 1, spoken
    assert AI_NOTICE in spoken, "the notice sentence is said as written (hard rule 5)"
    assert spoken.endswith(QUESTION)


def test_without_the_introduction_the_opening_is_said_whole() -> None:
    spoken = compose_first_utterance(_cfg(opening_line="", ai_notice=""))
    assert spoken == f"{INTRO} {QUESTION}"


def test_a_one_sentence_opening_keeps_its_question() -> None:
    names = introduction_names(name="లక్ష్మి", business="రైతు ఖాతా", body=None)
    line = "రైతు ఖాతా యాప్ గురించి ఏమి తెలుసుకోవాలి అండి?"
    joined = join_first_words(AI_NOTICE, line, ai_notice=AI_NOTICE, language="te-IN", names=names)
    assert joined.endswith(line)


# --- 5. the name only when it will be used -------------------------------------------------


def test_the_name_is_asked_for_a_booking_call_back_hand_over_or_at_the_close() -> None:
    assert "first answer" not in NAME_RULE
    assert "to book, call back or hand over, or at the close" in NAME_RULE


# --- 6. not knowing an answer is not doubt about going ahead ------------------------------


def test_hesitating_closes_but_not_knowing_an_answer_gets_help() -> None:
    assert "Hesitant to go ahead or not interested? Offer once, then close politely." in (
        VOICE_STYLE_GUIDANCE
    )
    assert "Unsure of an answer? Explain or offer choices." in VOICE_STYLE_GUIDANCE
    prompt = compose_engine_prompt(_cfg())
    assert "or no clear reply twice to one question: say so" in prompt


# --- 9. no fixed call-back promise in a v1 FAQ ---------------------------------------------


def _faq_body(fallback: str | None) -> str:
    faqs = [FaqEntry(question="Do you deliver?", answer="Yes.")]
    script = (
        CallScript(faqs=faqs) if fallback is None else CallScript(faqs=faqs, faq_fallback=fallback)
    )
    return compile_call_script(script)


def test_a_v1_faq_promises_no_call_back_of_its_own() -> None:
    for body in (_faq_body(None), _faq_body(RETIRED_FAQ_FALLBACK)):
        assert RETIRED_FAQ_FALLBACK not in body
        assert "do what the PLATFORM RULES say" in body
        assert "—" not in body.split("[FAQ]", 1)[1].split("\n", 1)[0]
    own = "We will check and tell you."
    assert f'say: "{own}"' in _faq_body(own), "the owner's own words stay"


# --- 10 and 11. openings written for the business, never ready-made ------------------------


@pytest.mark.rls
async def test_a_written_suggestion_rewrites_the_opening_for_the_business(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = await create_org_with_receptionist(
        name="Rytu Shop",
        slug=f"rytu-{uuid.uuid4().hex[:8]}",
        vertical_template="retail",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = uuid.UUID(str(created["id"])), uuid.UUID(str(created["agent_id"]))
    async with tenant_session(tenant_id) as session:
        base = await script_proposals.working_script(session, agent_id)
        await script_builder.save_draft(
            session, agent_id, base.model_copy(update={"opening_line": "Hello, how can I help?"})
        )
        asked = await script_proposals.request_written_opening(
            session, tenant_id=tenant_id, agent_id=agent_id, requested_by=None
        )
    seen: dict[str, Any] = {}

    async def write(brief: Any, **kwargs: Any) -> Any:
        seen["line"] = kwargs["line"]
        seen["problems"] = kwargs["problems"]
        return SimpleNamespace(
            value=WrittenOpening(line="ఏ పంట గురించి అండి?", said=NONE_SAID),
            capability=SimpleNamespace(disclosure=None),
            usage=None,
            model="gemini-2.5-flash-lite",
            earlier=(),
        )

    async def meter(_session: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(worker, "write_opening", write)
    monkeypatch.setattr(crm_assist, "meter_earlier", meter)
    monkeypatch.setattr(crm_assist, "meter_assist", meter)
    payload = {"tenant_id": str(tenant_id), "agent_id": str(agent_id), "proposal_id": str(asked.id)}
    assert await worker.draft_script_proposal({}, payload) == "ready"
    async with tenant_session(tenant_id) as session:
        stored = await script_proposals.read_proposal(session, agent_id)
    assert stored is not None and stored.mode == "written" and stored.script is not None
    assert stored.script.opening_line == "ఏ పంట గురించి అండి?"
    assert seen["line"] == "Hello, how can I help?"
    assert rewrite_problem("opening_line") in seen["problems"]
