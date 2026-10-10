"""Agent intelligence after the first live call (10 Oct 2026): the prompt, script v2, the
in-call model default and its price band, and the pre-launch test conversations.

`docs/evidence/first-call-review-2026-10-10.md` F-2, F-8 and founder decisions 1, 2, 3, 9
and 11. Each test names the failure it guards against.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import lifecycle, test_conversations
from apps.api.agents.engine_choice import (
    MODEL_ABOVE_VOICE_RATE,
    _check_model,
    in_call_default_model,
)
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.api.engine.catalogue import CatalogueModel, EngineCatalogue
from apps.api.engine.test_chat import TestChatTurn
from apps.api.reliability.engine_actions import ACTION_NAMES, OPT_OUT
from calevate_shared.call_script import (
    BUILTIN_END_CALL_RULE,
    GUARDRAILS_BLOCK,
    NO_CALL_BACKS_POLICY,
    CallScript,
    CanvasPosition,
    Capabilities,
    CollectField,
    ConversationStage,
    ExampleLine,
    FaqEntry,
    Objection,
    ScriptPolicies,
    ScriptStep,
    SpeakingStyle,
    StageBranch,
    business_line_of,
    call_backs_withheld,
    compile_call_script,
    native_steps,
    upgrade_to_v2,
    without_outline,
)
from calevate_shared.engine import (
    CANNOT_HELP_HEADER,
    CLIENT_SCRIPT_CLOSE,
    CONFIDENTIALITY_MARKER,
    CONFIDENTIALITY_RULE,
    TRUTHFUL_ANSWER_MARKER,
    AgentConfig,
    HandoffSpec,
    carries_confidentiality_rule,
    carries_truthful_answer_floor,
    compose_engine_prompt,
)
from calevate_shared.spoken_style import example_exchange, register_guidance, style_for
from sqlalchemy import text
from tests.conftest import accept_agreements

V2 = CallScript(
    schema_version=2,
    business_line="An organic produce shop in Kukatpally",
    identity="You answer the phone for the shop and take orders.",
    goal="Answer what they ask and take their order.",
    opening_line="Namaskaram andi, cheppandi.",
    style=SpeakingStyle(
        tone="Warm and quick", address_form="andi", sample_phrases=["Cheppandi andi"]
    ),
    stages=[
        ConversationStage(
            id="need",
            name="Need",
            instruction="Ask what they need.",
            branches=[StageBranch(when="You know.", target="end")],
        )
    ],
    objections=[Objection(objection="Too expensive.", response="Say what is included.")],
    ending="Thank them and say goodbye.",
    faqs=[FaqEntry(question="Sunday delivery?", answer="No, Monday to Saturday.")],
    example_exchange=[
        ExampleLine(speaker="caller", text="మీ దగ్గర ఎండు మిర్చి ఉందా అండి?"),
        ExampleLine(speaker="agent", text="ఒక్క నిమిషం అండి, చూసి చెప్తాను."),
    ],
)


def _cfg(body: str, **extra: Any) -> AgentConfig:
    return AgentConfig(
        tenant_id="t",
        agent_id="a",
        name="Front desk",
        direction="inbound",
        language_primary="te-IN",
        system_prompt=body,
        opening_line="",
        call_is_recorded=True,
        **extra,
    )


# --- the prompt (item 3) ------------------------------------------------------------------


def test_the_knowledge_tool_is_named_and_searched_before_i_dont_know() -> None:
    """F-2 line 5: asked "do you have chilli?", the agent never searched."""
    prompt = compose_engine_prompt(
        _cfg(compile_call_script(V2), facts_in_knowledge=True, knowledge_tool="search_knowledge")
    )
    assert "the search_knowledge tool" in prompt
    assert "always before saying you do not know" in prompt
    # The FAQ is no longer an "answer ONLY from these" fence.
    assert "ONLY from" not in prompt
    assert "win over anything in your knowledge" in prompt


def test_offer_a_call_back_is_said_once_and_never_on_a_trial() -> None:
    """The prompt said "offer a call back" five or six times; a trial agent promised one."""
    body = compile_call_script(V2)
    paying = compose_engine_prompt(_cfg(body))
    assert paying.count("offer a call back") == 2  # the cannot-help rule and nobody-on-duty
    trial = compose_engine_prompt(_cfg(body, callbacks_offered=False))
    assert "Never offer or book a call back" in trial
    assert "offer a call back from the team" not in trial


def test_no_person_on_duty_is_said_and_hand_over_is_only_on_request() -> None:
    nobody = compose_engine_prompt(_cfg(compile_call_script(V2)))
    assert "Nobody can take a call right now" in nobody
    on_duty = compose_engine_prompt(
        _cfg(
            compile_call_script(V2),
            handoff=HandoffSpec(
                destination_e164="+919000000001", trigger="t", spoken_line="Connecting you."
            ),
        )
    )
    assert "never because you do not know an answer" in on_duty


def test_the_floor_and_confidentiality_keep_their_content_and_position() -> None:
    prompt = compose_engine_prompt(_cfg(compile_call_script(V2)))
    assert carries_truthful_answer_floor(prompt) and carries_confidentiality_rule(prompt)
    assert CONFIDENTIALITY_RULE in prompt
    fence = prompt.index(CLIENT_SCRIPT_CLOSE)
    cannot = prompt.index(CANNOT_HELP_HEADER)
    secret = prompt.index(CONFIDENTIALITY_MARKER)
    floor = prompt.index(TRUTHFUL_ANSWER_MARKER)
    assert fence < cannot < secret < floor


def test_the_spoken_register_is_concrete_for_telugu() -> None:
    prompt = compose_engine_prompt(_cfg(compile_call_script(V2)))
    assert "--- SPOKEN REGISTER ---" in prompt
    assert 'not "క్షమించండి" but "sorry అండి"' in prompt
    assert "Never formal or written-style language" in prompt
    assert '"Dr Ravi", never "Dr. Ravi"' in prompt
    assert "Vary your words" in prompt


def test_a_full_v2_prompt_fits_the_engine_and_the_guide_budget() -> None:
    prompt = compose_engine_prompt(
        _cfg(compile_call_script(V2), facts_in_knowledge=True, knowledge_tool="search_knowledge")
    )
    assert len(prompt) < 8_000  # ThinnestAI's console ceiling (D-714)


# --- script v2 (item 4) ---------------------------------------------------------------------


def test_v2_compiles_every_section_once_and_no_platform_rule() -> None:
    body = compile_call_script(V2, collect=[CollectField(label="Name", required=True)])
    for header in (
        "[BUSINESS]",
        "[IDENTITY]",
        "[GOAL]",
        "[OPENING]",
        "[SPEAKING STYLE]",
        "[CONVERSATION]",
        "[WHAT TO COLLECT]",
        "[OBJECTIONS]",
        "[ENDING]",
        "[QUICK FACTS]",
        "[EXAMPLE CALL]",
    ):
        assert body.count(header) == 1, header
    assert GUARDRAILS_BLOCK not in body and BUILTIN_END_CALL_RULE not in body
    assert "When You know: End the call politely." in body
    assert business_line_of(body) == "An organic produce shop in Kukatpally"


def test_a_v1_script_compiles_byte_for_byte_as_before() -> None:
    v1 = CallScript(opening_line="Hello", steps=[ScriptStep(instruction="Ask.")])
    assert compile_call_script(v1) == (
        "[OPENING]\nHello\n\n"
        "[TASK FLOW] Follow these as a loose outline, one thing at a time. They are hints, "
        "not a rigid script — adapt to what the caller actually says.\n1. Ask.\n\n"
        f"[END CALL]\n- {BUILTIN_END_CALL_RULE}\n\n{GUARDRAILS_BLOCK}"
    )
    # Stored v1 JSON has no `schema_version`; it loads as v1.
    assert CallScript.model_validate({"opening_line": "Hello"}).schema_version == 1


def test_v2_sections_on_a_v1_script_are_refused_rather_than_dropped() -> None:
    with pytest.raises(ValueError):
        CallScript(goal="Book visits.")


def test_upgrading_v1_keeps_its_words_and_drops_the_platform_lines() -> None:
    v1 = CallScript(
        opening_line="Hello",
        steps=[ScriptStep(instruction="Ask."), ScriptStep(instruction="Book.")],
        faqs=[FaqEntry(question="Hours?", answer="9 to 6.")],
        end_call_extra_rules=["Thank them."],
    )
    v2 = upgrade_to_v2(v1)
    assert v2.schema_version == 2
    assert [s.instruction for s in v2.stages] == ["Ask.", "Book."]
    assert v2.faqs == v1.faqs and v2.ending == "Thank them." and v2.steps == []
    assert upgrade_to_v2(CallScript(raw_override="text")).raw_override == "text"


def test_withholding_call_backs_in_the_script_reaches_the_platform_rule() -> None:
    body = compile_call_script(
        V2.model_copy(update={"policies": ScriptPolicies(offer_call_backs=False)})
    )
    assert call_backs_withheld(body) and NO_CALL_BACKS_POLICY in body
    assert not call_backs_withheld(compile_call_script(V2))


# --- spoken style data (item 3) -------------------------------------------------------------


def test_every_language_style_is_flagged_for_native_review() -> None:
    for tag in (
        "te-IN",
        "hi-IN",
        "en-IN",
        "ta-IN",
        "kn-IN",
        "ml-IN",
        "mr-IN",
        "bn-IN",
        "gu-IN",
        "pa-IN",
        "or-IN",
    ):
        style = style_for(tag)
        assert style is not None, tag
        assert style.review == "needs_native_review"
        assert example_exchange(tag, None), tag
    assert example_exchange("te-IN", "retail")[0].text.startswith("మీ దగ్గర")
    telugu = style_for("te-IN")
    # One neutral spoken Telugu, no regional picker (founder, 10 Oct 2026).
    assert telugu is not None and telugu.register_name == "Neutral spoken Telugu"
    assert "Telangana and Andhra" in telugu.register
    assert register_guidance("xx-XX") is None


# --- the in-call model (item 1) -------------------------------------------------------------


class _Thinnest:
    name = "thinnest"

    class capabilities:  # noqa: N801 - mirrors the attribute shape
        @staticmethod
        def is_ours(leg: str) -> bool:
            return False


def test_the_in_call_default_is_unset_unless_the_console_sets_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine: Any = _Thinnest()
    assert get_settings().thinnest_in_call_default_model is None
    assert in_call_default_model(engine, voice_id="engine:kavya") is None
    monkeypatch.setattr(get_settings(), "thinnest_in_call_default_model", "gpt-oss-120b")
    assert in_call_default_model(engine, voice_id="engine:kavya") == "gpt-oss-120b"
    # A Studio voice (our voice key) gets it too (D-717); the console write only accepts a
    # model a voice-only BYOK call may run (`resolve_in_call_default`).
    assert in_call_default_model(engine, voice_id="byok:abc") == "gpt-oss-120b"
    # The platform's own model is a different setting and does not move.
    assert get_settings().platform_llm_model == "gemini-2.5-flash-lite"


def test_premium_band_models_need_a_premium_voice_and_unread_ones_are_not_offered() -> None:
    premium = CatalogueModel(
        model_id="gpt-5-mini",
        label="GPT-5 Mini",
        call_capable=True,
        plan_allows=True,
        surcharge="premium",
    )
    catalogue = EngineCatalogue(models=[premium], complete=True)
    every = frozenset({"platform", "standard", "premium", "studio"})
    with pytest.raises(ProblemError) as refused:
        _check_model(
            catalogue,
            "gpt-5-mini",
            attested=every,
            platform="P",
            with_own_voice=False,
            voice_rate_key="standard",
        )
    assert refused.value.code == MODEL_ABOVE_VOICE_RATE
    _check_model(
        catalogue,
        "gpt-5-mini",
        attested=every,
        platform="P",
        with_own_voice=False,
        voice_rate_key="premium",
    )
    from apps.api.agents.engine_catalogue_offer import model_unofferable_reason

    unread = CatalogueModel(model_id="q", label="Qwen3.6 27B", call_capable=True, plan_allows=True)
    assert model_unofferable_reason(unread, attested=every, platform="P", audience="client")


# --- pre-launch test conversations (item 5) -----------------------------------------------


class _ChatEngine:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def test_chat(
        self, ref: str, message: str, *, session: str | None = None
    ) -> TestChatTurn:
        self.sent.append(message)
        if "number" in message or "నంబర్" in message or "number తీసేయండి" in message:
            return TestChatTurn(session="vr_1", reply="సరే అండి.", tools=(ACTION_NAMES[OPT_OUT],))
        if "AI" in message:
            return TestChatTurn(session="vr_1", reply="నేను AI assistant ని అండి.", tools=())
        return TestChatTurn(session="vr_1", reply="చెప్పండి అండి.", tools=())


async def test_the_scenarios_run_in_the_agents_language_and_are_judged() -> None:
    engine = _ChatEngine()

    async def _no_pause() -> None:
        return None

    results = await test_conversations.run_scenarios(
        engine, engine_agent_ref="ag_1", direction="inbound", language="te-IN", pause=_no_pause
    )
    keys = [r.key for r in results]
    assert "objection_price" in keys and "objection_not_interested" not in keys
    assert all(any("ఀ" <= ch <= "౿" for ch in said) for said in engine.sent)
    verdicts = {r.key: r.verdict for r in results}
    assert verdicts["asks_if_ai"] == "passed"
    assert verdicts["says_stop_calling"] == "passed"
    # No search happened, so the product question needs attention with advice.
    product = next(r for r in results if r.key == "asks_about_products")
    assert product.verdict == "attention" and product.advice


def test_the_retired_hand_over_action_fails_a_scenario() -> None:
    scenario = test_conversations.SCENARIOS[4]
    assert (
        test_conversations.judge(scenario, "x", (ACTION_NAMES["handoff"],), knowledge_tool=None)
        == "failed"
    )


@pytest.mark.rls
async def test_one_business_never_sees_anothers_test_runs() -> None:
    async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
        created = await admin_service.create_organization(
            name="Raghava Organics",
            slug=f"tests-{uuid.uuid4().hex[:8]}",
            vertical_template="retail",
            billing_email=None,
            language="te-IN",
            created_by=None,
        )
        tenant_id = uuid.UUID(str(created["id"]))
        await accept_agreements(tenant_id)
        async with tenant_session(tenant_id) as session:
            agent_id = await lifecycle.create_agent(
                session,
                tenant_id=tenant_id,
                name="Front desk",
                direction="outbound",
                language_primary="te-IN",
            )
            await session.execute(
                text(
                    "INSERT INTO agent_test_runs (id, tenant_id, agent_id, status, created_at, "
                    "updated_at) VALUES (:id, :t, :a, 'done', now(), now())"
                ),
                {"id": uuid.uuid4(), "t": tenant_id, "a": agent_id},
            )
        return tenant_id, agent_id

    tenant_a, agent_a = await _tenant()
    tenant_b, _ = await _tenant()
    async with tenant_session(tenant_b) as session:
        seen = (
            await session.execute(
                text("SELECT count(*) FROM agent_test_runs WHERE tenant_id = :a"), {"a": tenant_a}
            )
        ).scalar()
        assert seen == 0
        assert await test_conversations.latest_run(session, agent_a) is None
    async with tenant_session(tenant_a) as session:
        assert (await test_conversations.latest_run(session, agent_a)) is not None


# --- native steps and the instructions budget (production bugs, 10 Oct 2026) --------------


GRAPH = CallScript(
    schema_version=2,
    opening_line="Namaskaram andi.",
    adherence="strict",
    stages=[
        ConversationStage(
            id="need",
            name="Need",
            instruction="Ask what they want to buy.",
            sounds_like="ఏం కావాలి అండి?",
            branches=[
                StageBranch(when="They only want the price", target="price"),
                StageBranch(when="They ask for a person", target="hand_over"),
                StageBranch(when="They want to be called later", target="call_back"),
            ],
            otherwise="price",
            collect=["product"],
            position=CanvasPosition(x=40, y=80),
        ),
        ConversationStage(
            id="price",
            name="Price",
            mode="say",
            instruction="Prices are in our list.",
            otherwise="end",
        ),
    ],
)


def test_the_sections_become_native_steps_and_leave_the_instructions() -> None:
    steps = native_steps(GRAPH, can=Capabilities(call_backs=False, hand_over=False))
    assert [s.title for s in steps] == ["Need", "Price"]
    assert steps[0].branches == (
        ("They only want the price", "Go to 'Price'"),
        ("They ask for a person", "Say nobody can take the call right now"),
        ("They want to be called later", "Say the business will get back to them"),
        ("Otherwise", "Go to 'Price'"),
    )
    assert steps[0].collect == ("product",)
    assert steps[0].detail == 'Ask what they want to buy. It sounds like: "ఏం కావాలి అండి?"'
    assert steps[1].detail == 'Say: "Prices are in our list."'
    assert steps[1].branches == (("Otherwise", "End the call politely"),)
    # With the account able to, the same branches offer what they name.
    able = native_steps(GRAPH, can=Capabilities(call_backs=True, hand_over=True))
    assert able[0].branches[1][1] == "Hand the caller to a person"
    assert able[0].branches[2][1] == "Offer a call back"
    body = compile_call_script(GRAPH)
    assert "[CONVERSATION]" in body and "[CONVERSATION]" not in without_outline(body)
    assert "[OPENING]\nNamaskaram andi." in without_outline(body)
    # The canvas position is layout only.
    assert "80" not in body.split("[CONVERSATION]")[1]


def test_a_branch_to_a_section_that_does_not_exist_is_refused() -> None:
    with pytest.raises(ValueError):
        CallScript(
            schema_version=2,
            stages=[
                ConversationStage(
                    id="a",
                    name="A",
                    instruction="x",
                    branches=[StageBranch(when="y", target="nowhere")],
                )
            ],
        )
    with pytest.raises(ValueError):
        CallScript(
            schema_version=2,
            stages=[
                ConversationStage(id="a", name="A", instruction="x"),
                ConversationStage(id="a", name="B", instruction="y"),
            ],
        )


def test_a_section_detail_fits_the_engines_step() -> None:
    with pytest.raises(ValueError):
        ConversationStage(id="a", name="A", instruction="x" * 500, sounds_like="y" * 150)


def test_the_thinnest_body_carries_steps_and_reads_them_back() -> None:
    from apps.api.engine import thinnest

    steps = native_steps(GRAPH, can=Capabilities(call_backs=True, hand_over=True))
    cfg = _cfg(compile_call_script(GRAPH)).model_copy(update={"script_steps": steps})
    body = thinnest._steps_body(cfg)
    assert body[1] == {
        "title": "Price",
        "detail": 'Say: "Prices are in our list."',
        "branches": [{"when": "Otherwise", "action": "End the call politely"}],
        "collect": [],
    }
    # The vendor's read-back (AgentStep) compared in our shape: equal, then drifted.
    assert thinnest._steps_held(body) == body
    assert thinnest._settings_drift({"steps": body}, {"steps": body}) == []
    assert thinnest._settings_drift({"steps": body}, {"steps": []}) == ["script_steps"]
    with pytest.raises(ProblemError):
        thinnest._refuse_unsaved_steps({"steps": body}, {"steps": []})
    # A script with no structured sections sends `[]`, which clears a held script.
    assert thinnest._steps_body(_cfg("x")) == []


def test_instructions_over_the_console_ceiling_are_refused() -> None:
    from apps.api.agents.engine_limits import PROMPT_TOO_LONG, refuse_over_engine_limits
    from apps.api.engine.thinnest import INSTRUCTIONS_MAX_CHARS
    from tests.thinnest_publish_limits_test import _thinnest

    assert INSTRUCTIONS_MAX_CHARS == 8_000
    with pytest.raises(ProblemError) as refused:
        refuse_over_engine_limits(_thinnest(), _cfg("word " * 1_800))
    assert refused.value.code == PROMPT_TOO_LONG
    assert "8,000" in refused.value.detail


# --- conversion round trip and the draft (founder decisions 4 and 6) -----------------------


def test_a_conversion_shows_what_it_could_not_place() -> None:
    from calevate_shared.call_script import unplaced_lines

    raw = "Greet the caller warmly.\nAsk which product they want.\nNever discuss competitors."
    proposal = CallScript(
        schema_version=2,
        opening_line="Greet the caller warmly.",
        stages=[
            ConversationStage(id="s1", name="Need", instruction="Ask which product they want.")
        ],
    )
    assert unplaced_lines(raw, proposal) == ["Never discuss competitors."]


@pytest.mark.rls
async def test_the_draft_autosaves_without_a_version_and_restores_a_version() -> None:
    from apps.api.agents import script_builder

    created = await admin_service.create_organization(
        name="Raghava Organics",
        slug=f"draft-{uuid.uuid4().hex[:8]}",
        vertical_template="retail",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    await accept_agreements(tenant_id)
    async with tenant_session(tenant_id) as session:
        agent_id = await lifecycle.create_agent(
            session,
            tenant_id=tenant_id,
            name="Front desk",
            direction="inbound",
            language_primary="te-IN",
            starter="answer_calls",
        )
        before = await script_builder.list_versions(session, agent_id)
        await script_builder.save_draft(session, agent_id, V2)
        draft = await script_builder.read_draft(session, agent_id)
        assert draft is not None and draft.script == V2
        # A second tab that loaded no draft cannot overwrite this one silently.
        with pytest.raises(ProblemError) as moved:
            await script_builder.save_draft(session, agent_id, V2, base_saved_at=None)
        assert moved.value.code == "script_changed_elsewhere"
        await script_builder.save_draft(session, agent_id, V2, base_saved_at=draft.saved_at)
        # No version per autosave.
        assert len(await script_builder.list_versions(session, agent_id)) == len(before)
        restored = await script_builder.restore_into_draft(session, agent_id, before[0].version)
        assert restored.script.schema_version == 2
        await script_builder.clear_draft(session, agent_id)
        assert await script_builder.read_draft(session, agent_id) is None
