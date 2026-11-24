"""The founder's Telugu campaign call of 24 Nov 2026, 12:15: the in-call prompt and the review.

One filler opened nine of twelve replies; a button and a site were said twice, in the call's
letters and again in English in brackets; a word the register's list names was said; and the
knowledge was never searched although the person said a menu option was missing. The
Telugu below is the call's own transcript, quoted only as what the checks must detect.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from apps.api.agents import service as agents_service
from apps.api.agents.call_mistakes import LESSONS, mistakes_in
from apps.api.agents.mistake_lints import mistake_findings
from apps.api.agents.script_lint import LintContext
from apps.api.agents.turn_checks import turn_problems
from apps.api.db.session import tenant_session
from calevate_shared.call_script import CallScript, ConversationStage
from calevate_shared.engine import (
    STUCK_SEARCH,
    VOICE_STYLE_GUIDANCE,
    AgentConfig,
    compose_engine_prompt,
    engine_prompt_layers,
    screen_steps_bullet,
)
from calevate_shared.spoken_style import FILLERS_LEAD, SWAPS_LEAD, register_guidance, style_for
from tests.notes_per_job_test import _campaign
from tests.thinnest_publish_limits_test import _agent_with_script, _selected, _thinnest


@dataclass(frozen=True)
class _T:
    idx: int
    speaker: str
    text: str


#: Turns 9 to 14 and 21 to 22 of the call, numbered as the call page numbers them.
TURN_10 = "సరే అండి, ఇప్పుడు అడ్రస్ బార్‌లో రైతుఖాతా డాట్ కామ్ (rytukhata.com) అని టైప్ చేసి వెతకండి. సైట్ ఓపెన్ అయిందా అండి?"
TURN_14 = (
    "సరే అండి, ఇప్పుడు అందులో యాడ్ టు హోమ్ స్క్రీన్ (Add to Home screen) అనే ఆప్షన్ కనిపిస్తుంది, "
    "దాన్ని ఎంచుకోండి. అది అయ్యాక చెప్పండి అండి."
)
TURN_22 = "సరే అండి, ఇప్పుడు మీ రిజిస్టర్డ్ మొబైల్ నంబర్ మరియు పాస్వర్డ్ ఎంటర్ చేసి లాగిన్ అవ్వండి. లాగిన్ అయ్యారా అండి?"
CALL = [
    _T(1, "agent", "నమస్కారం, నేను రైతుఖాతా నుంచి మాట్లాడుతున్నాను, ఇప్పుడు మాట్లాడటానికి వీలుందా?"),
    _T(9, "caller", "Aa open chesanandi."),
    _T(10, "agent", TURN_10),
    _T(11, "caller", "Aa open ayindi."),
    _T(12, "agent", "పైన కుడివైపున ఉన్న మూడు చుక్కల మెనూని నొక్కండి. అది ఓపెన్ అయిందా?"),
    _T(13, "caller", "Aa open ayindi."),
    _T(14, "agent", TURN_14),
    _T(21, "caller", "ఆ, సెలెక్ట్ చేశాను."),
    _T(22, "agent", TURN_22),
]


def _cfg(**kw: object) -> AgentConfig:
    base: dict[str, object] = {
        "tenant_id": "t",
        "agent_id": "a",
        "name": "A",
        "direction": "outbound",
        "language_primary": "te-IN",
        "system_prompt": "",
        "opening_line": "",
        "call_is_recorded": True,
    }
    return AgentConfig.model_validate({**base, **kw})


def _filler() -> str:
    style = style_for("te-IN")
    assert style is not None and style.fillers
    return style.fillers[0].text


# --- 1. a filler at most once a call, said at the list ---------------------------------


def test_the_fillers_are_not_quoted_to_the_call_model() -> None:
    # A quoted filler opened nine of twelve replies although capped "once a call each", so the
    # call prompt names none and says the rule of every reaction instead.
    guidance = register_guidance("te-IN")
    assert guidance is not None
    assert FILLERS_LEAD not in guidance and _filler() not in guidance
    assert "never begin or end two replies alike" in VOICE_STYLE_GUIDANCE


# --- 2. a name said once, never with a bracketed repeat -------------------------------


def test_a_screen_agent_names_a_label_once_and_never_in_brackets() -> None:
    bullet = screen_steps_bullet("te-IN")
    assert "name what to tap once" in bullet
    assert "never again in brackets or other letters" in bullet
    assert "say a web address once" in bullet
    layers = dict(engine_prompt_layers(_cfg(caller_has_screen=True)))
    assert "never again in brackets" in layers["how_to_speak"]


def test_the_bracketed_repeat_is_found_on_the_reply_and_on_the_call_page() -> None:
    for reply in (TURN_10, TURN_14):
        assert "brackets" in {p.kind for p in turn_problems(reply, language="te-IN")}
    found = mistakes_in(CALL, language="te-IN")
    assert found["brackets"] == 10
    assert LESSONS["brackets"].label


# --- 5. the register's word list reaches a campaign's call and the review names it ------


def test_a_textbook_word_from_the_list_is_found_on_turn_22() -> None:
    style = style_for("te-IN")
    assert style is not None
    formal = next(f for f, _s in style.prompt_swaps if f in TURN_22)
    problems = [p for p in turn_problems(TURN_22, language="te-IN") if p.kind == "formal_words"]
    assert problems and formal in problems[0].reason
    assert mistakes_in(CALL, language="te-IN")["formal_words"] == 22
    assert LESSONS["formal_words"].label


def test_a_script_line_with_a_textbook_word_is_traced_for_the_healer() -> None:
    script = CallScript(
        schema_version=2,
        opening_line="Hello.",
        stages=[
            ConversationStage.model_validate(
                {"id": "s1", "name": "s1", "instruction": "Log in.", "sounds_like": TURN_22}
            )
        ],
    )
    found = mistake_findings(script, LintContext(language="te-IN"), "formal_words")
    assert [f.partition(": ")[0] for f in found] == ["stages.0.sounds_like"]
    assert mistake_findings(script, LintContext(language="en-IN"), "formal_words") == []


def test_the_word_list_says_a_script_line_is_no_exception() -> None:
    style = style_for("te-IN")
    assert style is not None
    formal = next(f for f, _s in style.prompt_swaps if f in TURN_22)
    guidance = register_guidance("te-IN")
    assert guidance is not None
    assert "even scripted" in SWAPS_LEAD
    assert f'{SWAPS_LEAD} "' in guidance and f'"{formal}" →' in guidance


async def test_a_te_in_campaigns_engine_agent_carries_the_word_list_and_no_filler_list() -> None:
    tenant_id, agent_id = await _agent_with_script("Greet, then help.")
    campaign_id = await _campaign(uuid.UUID(str(tenant_id)), uuid.UUID(str(agent_id)))
    style = style_for("te-IN")
    assert style is not None
    with _selected(_thinnest()):
        async with tenant_session(tenant_id) as session:
            config = await agents_service.campaign_config(
                session,
                tenant_id=uuid.UUID(str(tenant_id)),
                campaign_id=campaign_id,
                script=CallScript(schema_version=2, opening_line="Hello.", goal="Help them."),
            )
    assert config.language_primary == "te-IN"
    assert config.holder == f"campaign:{campaign_id}"
    prompt = compose_engine_prompt(config)
    register = prompt.split("--- SPOKEN REGISTER ---", 1)[1]
    for formal, _spoken in style.prompt_swaps:
        assert f'"{formal}" →' in register
    assert FILLERS_LEAD not in register


# --- 7. the knowledge is searched when a step does not work -----------------------------


def test_an_agent_with_facts_in_knowledge_searches_when_stuck_on_a_step() -> None:
    for inline in (False, True):
        cfg = _cfg(facts_in_knowledge=True, knowledge_tool="search_knowledge", facts_inline=inline)
        layers = dict(engine_prompt_layers(cfg))
        assert STUCK_SEARCH in layers["business_facts"], inline
    without = dict(engine_prompt_layers(_cfg()))
    assert STUCK_SEARCH not in without["business_facts"]
