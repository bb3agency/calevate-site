"""What an AI writes into a script, a test or the business copy keeps the language rules, and
what the owner types never meets them (D-831).

The founder's screenshot of 19 Oct 2026: Pip's whole-script draft wrote the role, the goal and
the reason for calling in Telugu with textbook words (మరియు, వివరాలు, సమాచారం), although the
prompt said instructions are English. A prompt is advice; these checks are the rule, and the
existing single repair re-ask is how the model is told.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import lifecycle, script_builder, turn_checks
from apps.api.agents.script_edits import ScriptEdit, apply_edits
from apps.api.agents.test_conversations import AgentBrief
from apps.api.core import provider_health
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.workers import agent_test_ai, chat, extraction, script_assist
from apps.workers import business_copy as copy_worker
from apps.workers.extraction import TenantModelLeg
from apps.workers.script_assist import ScriptBrief, UnusableAnswerError
from calevate_shared import spoken_guard
from calevate_shared.call_script import CallScript, ConversationStage
from calevate_shared.spoken_style import (
    PackChoice,
    caller_guidance,
    pack_facts_rule,
    pack_lines,
    style_for,
    writer_guidance,
)
from tests.business_copy_test import _inputs, copy_dict
from tests.conftest import accept_agreements

TE = "te-IN"
GEMINI = "gemini-3.1-flash-lite"
GOOGLE_LEG = TenantModelLeg(model=GEMINI, provider="google", serves_dashboard=True)

#: The founder's screenshot, field for field.
ROLE_TE = "Raghava Organics ప్రతినిధిని."
GOAL_TE = "ఎండు మిర్చి గురించి వివరాలు చెప్పి ఆర్డర్ తీసుకోవడం."
PURPOSE_TE = "మా కొత్త కారం పొడి గురించి సమాచారం ఇవ్వడానికి."
ADDRESS_TE = "కస్టమర్లను అండి అని పిలవాలి."
#: Clean spoken Telugu: no word of the spoken-style list.
OPENING = "నమస్తే అండి, Raghava Organics నుంచి, చెప్పండి?"
SOUNDS = "ఏ item కావాలి అండి?"


def _draft(**over: Any) -> dict[str, Any]:
    """A whole-draft answer as the model returns it: English instructions, spoken Telugu."""
    raw: dict[str, Any] = {
        "business_line": "We sell naturally grown dry chillies and chilli powder.",
        "identity": "Answers calls for the shop: products, prices, orders and delivery.",
        "goal": "Answer the question and take the order with the delivery area.",
        "outbound_purpose": "",
        "opening_line": OPENING,
        "tone": "warm and quick",
        "address_form": "andi, never by first name",
        "code_mix": "natural",
        "sample_phrases": ["సరే అండి", "ఒక్క నిమిషం అండి"],
        "pronunciations": [],
        "stages": [
            {
                "name": "Need",
                "instruction": "Ask what they want.",
                "sounds_like": SOUNDS,
                "exit_when": "They say what they want.",
            }
        ],
        "objections": [{"objection": "Too costly", "response": "Say why it is worth it."}],
        "ending": "Confirm the order and say goodbye.",
        "quick_facts": [],
        "example_exchange": [
            {"speaker": "caller", "text": "మిర్చి ఉందా అండి?"},
            {"speaker": "agent", "text": "ఉంది అండి, ఎంత కావాలి?"},
        ],
    }
    return {**raw, **over}


# --- the shared matcher ---------------------------------------------------------------------


def test_the_test_loop_and_every_writer_read_one_word_list() -> None:
    """FAILS IF: the reply check and the writers' guard match words differently, so a word
    the founder adds to the list is caught in one place and not the other."""
    assert turn_checks.formal_swaps is spoken_guard.textbook_words
    style = style_for(TE)
    assert style is not None and style.word_swaps
    for formal, spoken in style.word_swaps:
        assert (formal, spoken) in spoken_guard.textbook_words(f"సరే {formal} అండి", TE)
    found = turn_checks.turn_problems("సరే అండి, మిర్చి మరియు కారం ఉన్నాయి.", language=TE)
    assert any(p.kind == "formal_words" and "“మరియు”" in p.reason for p in found)


def test_the_writers_get_the_guidance_from_one_accessor() -> None:
    """FAILS IF: a writer's spoken guidance drifts from the one accessor the language packs
    plug into."""
    assert spoken_guard.generation_guidance(TE, "retail") == writer_guidance(TE, "retail")
    assert spoken_guard.generation_guidance(TE, "retail", side="caller") == caller_guidance(
        TE, "retail"
    )
    assert "Spoken-style guide" in ScriptBrief(language=TE, business_type="retail").user_message()


# --- the script writer ----------------------------------------------------------------------


def test_an_instruction_in_telugu_is_sent_back_naming_the_field() -> None:
    """FAILS IF: Pip's draft can put the role, the goal, the reason for calling or how it
    addresses callers in Telugu (the founder's screenshot)."""
    with pytest.raises(UnusableAnswerError) as refused:
        script_assist.drafted_script(
            _draft(
                identity=ROLE_TE, goal=GOAL_TE, outbound_purpose=PURPOSE_TE, address_form=ADDRESS_TE
            ),
            language=TE,
        )
    said = refused.value.problems
    for field in ("identity", "goal", "outbound_purpose", "style.address_form"):
        assert f"{field}: write this instruction in plain English" in said
    assert "opening_line" not in said


def test_spoken_lines_in_telugu_are_the_call_language() -> None:
    """FAILS IF: the English rule reaches the lines the agent says."""
    script = script_assist.drafted_script(_draft(), language=TE)
    assert script.opening_line == OPENING
    assert script.stages[0].sounds_like == SOUNDS
    assert script.identity.startswith("Answers calls")


def test_a_spoken_textbook_word_is_named_with_what_people_say() -> None:
    """FAILS IF: a spoken line the model wrote can carry a word on the founder's list."""
    with pytest.raises(UnusableAnswerError) as refused:
        script_assist.drafted_script(
            _draft(
                opening_line="నమస్తే అండి, మిర్చి మరియు కారం ఉన్నాయి.",
                sample_phrases=["మీ వివరాలు చెప్పండి"],
            ),
            language=TE,
        )
    said = refused.value.problems
    assert "opening_line: uses textbook words callers do not say: “మరియు”" in said
    assert (
        "style.sample_phrases.0: uses textbook words callers do not say: “వివరాలు” (say “details”)"
        in said
    )


def test_a_say_step_is_spoken_and_a_guide_step_is_an_instruction() -> None:
    """FAILS IF: a step the agent says word for word is held to English, or a guide step's
    instruction may be Telugu."""
    say = CallScript(
        schema_version=2,
        stages=[ConversationStage(id="s1", name="Greet", mode="say", instruction=OPENING)],
    )
    assert script_assist.language_problems(say, TE) == []
    guide = say.model_copy(
        update={"stages": [ConversationStage(id="s1", name="Greet", instruction=OPENING)]}
    )
    assert script_assist.language_problems(guide, TE) == [
        "stages.0.instruction: write this instruction in plain English; only the lines the "
        "agent says are in the call language"
    ]


def test_an_edit_judges_only_what_the_model_changed() -> None:
    """FAILS IF: an edit is refused for Telugu the OWNER typed into their own role, or a
    textbook word the owner asked for in their change."""
    current = CallScript(schema_version=2, identity=ROLE_TE, opening_line=OPENING)
    edited = script_assist.edited_script(
        {"goal": "Take the order.", "opening_line": "నమస్తే అండి, మరియు చెప్పండి?"},
        current,
        language=TE,
        allowed="Add మరియు to the opening",
    )
    assert edited is not None and edited.identity == ROLE_TE
    with pytest.raises(UnusableAnswerError) as refused:
        script_assist.edited_script({"goal": GOAL_TE}, current, language=TE)
    assert refused.value.problems.startswith("goal: write this instruction in plain English")


def test_a_conversion_keeps_the_owners_own_sentences_in_their_language() -> None:
    """FAILS IF: converting a hand-written Telugu prompt is refused for the owner's own words."""
    owner = "మీరు Raghava Organics ప్రతినిధి. మిర్చి మరియు కారం అమ్ముతాం."
    script = script_assist.drafted_script(
        _draft(identity="మీరు Raghava Organics ప్రతినిధి.", opening_line="మిర్చి మరియు కారం."),
        language=TE,
        allowed=owner,
        instructions=False,
    )
    assert script.identity.startswith("మీరు")
    with pytest.raises(UnusableAnswerError):
        script_assist.drafted_script(
            _draft(opening_line="మీ వివరాలు చెప్పండి"),
            language=TE,
            allowed=owner,
            instructions=False,
        )


# --- the repair, end to end on the real ladder ---------------------------------------------


@pytest.fixture
def gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gemini and Sarvam keyed, no Azure leg: the production shape of the dashboard ladder."""
    settings = get_settings()
    monkeypatch.setattr(settings, "gemini_api_key", "g-test", raising=False)
    monkeypatch.setattr(settings, "sarvam_api_key", "sk-test", raising=False)
    for field in ("azure_openai_resource", "azure_openai_api_key", "azure_openai_deployment"):
        monkeypatch.setattr(settings, field, None, raising=False)

    async def _quiet(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(provider_health, "note_failure", _quiet)
    monkeypatch.setattr(provider_health, "note_success", _quiet)


def _answers(
    monkeypatch: pytest.MonkeyPatch, google: list[dict[str, Any]], sarvam: dict[str, Any]
) -> list[str]:
    """Fake the provider one layer below the ladder; returns each Gemini request's user text."""
    asked: list[str] = []

    async def _complete(leg: chat.ChatLeg, messages: Sequence[Any], **kw: Any) -> Any:
        if leg.dialect == "google":
            asked.append(messages[-1]["content"])
            answer = google[min(len(asked), len(google)) - 1]
        else:
            answer = sarvam
        return chat.ChatOutcome(
            content=json.dumps(answer),
            finish_reason="stop",
            usage=chat.TokenUsage(prompt_tokens=10, output_tokens=5),
        )

    monkeypatch.setattr(chat, "complete", _complete)
    return asked


async def test_a_telugu_role_is_repaired_once_on_the_same_leg(
    gemini: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FAILS IF: Pip's draft with a Telugu role or goal reaches the owner, or the model is not
    told which field to fix."""
    asked = _answers(monkeypatch, [_draft(identity=ROLE_TE, goal=GOAL_TE), _draft()], _draft())
    draft = await script_assist.draft_script(
        ScriptBrief(language=TE, business_type="retail"), tenant_leg=GOOGLE_LEG
    )
    assert draft.script.identity.startswith("Answers calls")
    assert len(asked) == 2
    assert "identity: write this instruction in plain English" in asked[1]
    assert "goal: write this instruction in plain English" in asked[1]


async def test_a_repair_that_is_still_telugu_is_refused_honestly(
    gemini: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FAILS IF: an answer that still breaks the rule after the repair is shown to the owner,
    or the refusal says no assistant answered."""
    bad = _draft(identity=ROLE_TE)
    _answers(monkeypatch, [bad, bad], bad)
    with pytest.raises(extraction.SpentRefusalError) as refused:
        await script_assist.draft_script(ScriptBrief(language=TE), tenant_leg=GOOGLE_LEG)
    assert refused.value.code == script_assist.ANSWER_UNUSABLE_CODE


# --- the improver ---------------------------------------------------------------------------


def _edit(op: str, **fields: Any) -> dict[str, Any]:
    return {
        "op": op,
        "step_id": "",
        "part": "",
        "name": "",
        "objection": "",
        "text": "",
        "because": "k1",
        "why": "Because.",
        **fields,
    }


CURRENT = CallScript(
    schema_version=2,
    stages=[
        ConversationStage(id="s1", name="Need", instruction="Ask what they want."),
        ConversationStage(id="s2", name="Greet", mode="say", instruction=OPENING),
    ],
)


def _proposal(edits: list[dict[str, Any]], *, send_back: bool) -> dict[str, Any] | None:
    return agent_test_ai.proposal_from_model(
        {"edits": edits, "facts": []},
        current=CURRENT,
        keys={"k1"},
        fact_ids=set(),
        language=TE,
        send_back_language=send_back,
    )


def test_the_improver_sends_language_problems_back_once_then_drops_the_edit() -> None:
    """FAILS IF: an improver edit can put Telugu into an instruction or a textbook word into
    a step the agent says, or one such edit throws the good ones away after the repair."""
    edits = [
        _edit("set_part", part="identity", text=ROLE_TE),
        _edit("set_step", step_id="s2", text="నమస్తే అండి, మిర్చి మరియు కారం ఉన్నాయి."),
        _edit("set_part", part="ending", text="Thank them and say goodbye."),
    ]
    with pytest.raises(UnusableAnswerError) as refused:
        _proposal(edits, send_back=True)
    assert "edits.0.text: write this instruction in plain English" in refused.value.problems
    assert "edits.1.text: uses textbook words callers do not say: “మరియు”" in refused.value.problems
    kept = _proposal(edits, send_back=False)
    assert kept is not None
    assert [e["part"] for e in kept["edits"]] == ["ending"]
    assert kept["dropped"] == 2


# --- the practice callers -------------------------------------------------------------------

BRIEF = AgentBrief(
    business_name="Raghava Organics",
    business_type="retail",
    direction="inbound",
    language=TE,
    register="",
    word_swaps=(),
    steps=(("s1", "Need", "Ask what they want."),),
    opening_line=OPENING,
    ending="",
    objections=(),
    pinned_facts=(),
    knowledge_titles=(),
    lead_fields=(),
    hand_over="off",
    call_backs=True,
    call_is_recorded=True,
)


def _scenario(*turns: str) -> dict[str, Any]:
    return {
        "title": "Asks the price",
        "category": "business",
        "probe": "none",
        "caller_turns": list(turns),
        "expect": "It gives the pinned price.",
    }


async def test_practice_callers_with_textbook_words_are_repaired(
    gemini: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FAILS IF: a practice caller says a word no real caller says, so the agent is tested
    against a caller nobody will ever be."""
    stiff = {"scenarios": [_scenario("దయచేసి మిర్చి ధర చెప్పండి"), _scenario("కారం ఉందా?")]}
    clean = {"scenarios": [_scenario("మిర్చి price ఎంత అండి?"), _scenario("కారం ఉందా?")]}
    asked = _answers(monkeypatch, [stiff, clean], clean)
    answer = await agent_test_ai.generate_scenarios(BRIEF, round_key="r1", tenant_leg=GOOGLE_LEG)
    assert [s.turns[0] for s in answer.value] == ["మిర్చి price ఎంత అండి?", "కారం ఉందా?"]
    assert "scenarios.0.caller_turns.0: uses textbook words callers do not say" in asked[1]


async def test_a_practice_caller_still_stiff_after_the_repair_is_left_out(
    gemini: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FAILS IF: one stiff caller after the repair costs the whole generated set."""
    stiff = {"scenarios": [_scenario("దయచేసి మిర్చి ధర చెప్పండి"), _scenario("కారం ఉందా?")]}
    _answers(monkeypatch, [stiff, stiff], stiff)
    answer = await agent_test_ai.generate_scenarios(BRIEF, round_key="r1", tenant_leg=GOOGLE_LEG)
    assert [s.turns for s in answer.value] == [("కారం ఉందా?",)]


# --- the business copy ----------------------------------------------------------------------


def test_a_business_example_line_with_a_textbook_word_is_sent_back() -> None:
    """FAILS IF: the D-827 example lines can teach an owner a word callers do not say."""
    raw = copy_dict()
    raw["steps"][0]["example_line"] = "మీ వివరాలు చెప్పండి అండి"
    with pytest.raises(UnusableAnswerError) as refused:
        copy_worker.parse_answer(raw, inputs=_inputs())
    assert "steps.0.example_line: uses textbook words callers do not say: “వివరాలు”" in (
        refused.value.problems
    )


# --- the owner's own typing -----------------------------------------------------------------


def test_the_owners_kept_edits_are_never_judged() -> None:
    """FAILS IF: the server refuses to apply an edit the owner kept because of its language."""
    script, applied, rejected = apply_edits(
        CURRENT, [ScriptEdit(id="e1", op="set_part", part="identity", text=ROLE_TE)]
    )
    assert applied == ["e1"] and not rejected and script.identity == ROLE_TE


@pytest.mark.rls
async def test_the_owners_own_telugu_in_an_instruction_saves() -> None:
    """FAILS IF: the language rules reach the owner's save: they bind the AI only."""
    created = await admin_service.create_organization(
        name="Raghava Organics",
        slug=f"lang-{uuid.uuid4().hex[:8]}",
        vertical_template="retail",
        billing_email=None,
        language=TE,
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    await accept_agreements(tenant_id)
    owner = CallScript(
        schema_version=2,
        identity=ROLE_TE,
        goal=GOAL_TE,
        opening_line="నమస్కారం అండి, మరియు చెప్పండి?",
        stages=[ConversationStage(id="s1", name="Need", instruction=GOAL_TE)],
    )
    async with tenant_session(tenant_id) as session:
        agent_id = await lifecycle.create_agent(
            session,
            tenant_id=tenant_id,
            name="Front desk",
            direction="inbound",
            language_primary=TE,
            starter="answer_calls",
        )
        await script_builder.save_draft(session, agent_id, owner)
        draft = await script_builder.read_draft(session, agent_id)
    assert draft is not None and draft.script.identity == ROLE_TE


def test_writers_follow_the_language_pack_only_once_it_is_approved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert spoken_guard.generation_guidance("te-IN") == writer_guidance("te-IN", None)

    choice = PackChoice(form="en", avoid="none")
    monkeypatch.setattr(spoken_guard, "shipped_pack_choice", lambda tag: choice)
    guidance = spoken_guard.generation_guidance("te-IN")
    expected = [*pack_lines("te-IN", choice), pack_facts_rule("te-IN", choice)]
    assert guidance == "\n".join(expected)
    assert spoken_guard.generation_guidance("te-IN", side="caller") == caller_guidance(
        "te-IN", None
    )
