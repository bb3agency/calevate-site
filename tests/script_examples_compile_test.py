"""Example-led compile (docs/evidence/script-rebuild-2026-11-26/DESIGN.md §3.5): each step's
examples under its actions, rotated per script, in the call's languages; the legacy
`sounds_like` path; what the call prompt no longer quotes; and the size of a guided,
Rytu-shaped campaign with examples against ThinnestAI's limits.

Every caller-facing line here is an English placeholder: Telugu is written by the step
writer and reviewed by the owner, never typed into a test.
"""

from __future__ import annotations

import pytest
from apps.api.engine.thinnest import INSTRUCTIONS_MAX_CHARS
from calevate_shared.call_script import (
    EXAMPLE_CALL_LEAD,
    EXAMPLE_HEADER,
    OPENING_HEADER,
    PROCEDURE_HEADER,
    PROCEDURE_LEAD,
    STAGE_DETAIL_MAX,
    STEP_EXAMPLES_LEAD,
    STEPS_LEAD,
    TONE_LEAD,
    CallScript,
    CollectField,
    ConversationStage,
    ExampleLine,
    ProcedureStep,
    StageBranch,
    StepExamples,
    StepOutcome,
    compile_call_script,
    examples_pointer,
    first_sentence,
    is_example_led,
    native_steps,
    procedure_pointer,
    without_opening_sections,
    without_outline,
)
from calevate_shared.engine import (
    CONFIDENTIALITY_RULE,
    EXAMPLE_LED_GUIDANCE,
    VOICE_STYLE_GUIDANCE,
    AgentConfig,
    compose_engine_prompt,
    engine_prompt_layers,
    truthful_answer_directive,
)
from calevate_shared.languages import find_language
from calevate_shared.spoken_style import FILLERS_LEAD, style_for

TE = "te-IN"
EN = "en-IN"


def ph(text: str) -> str:
    return f"<TE: {text}>"


def _examples(name: str, *, busy: bool = False) -> StepExamples:
    return StepExamples(
        turns=[ph(f"{name} turn {n}, one action") for n in ("one", "two", "three", "four")],
        confused=ph(f"{name} again, shorter"),
        stuck=ph(f"{name}, one smaller action"),
        busy=ph("When would suit you better?") if busy else "",
    )


INSTALL = [
    ProcedureStep(action="Ask them to open Chrome on their phone", wait_for="the browser is open"),
    ProcedureStep(action="Ask them to type the address and open it", wait_for="they see the page"),
    ProcedureStep(action="Ask them to tap Install", wait_for="the icon is on the home screen"),
]


def _script(**update: object) -> CallScript:
    script = CallScript(
        schema_version=2,
        business_line="A farm accounts app.",
        opening_line=ph("Hello {{lead_name}} garu, calling from the app, is now a good time?"),
        stages=[
            ConversationStage(
                id="intro",
                step=1,
                name="Introduction",
                instruction="Ask whether they registered on the website.",
                examples={TE: _examples("Introduction", busy=True)},
                otherwise="install",
            ),
            ConversationStage(
                id="install",
                step=2,
                name="Install",
                instruction="Help them put the app on their home screen.",
                procedure=INSTALL,
                examples={TE: _examples("Install", busy=True)},
                otherwise="end",
            ),
        ],
        example_exchange=[
            ExampleLine(speaker="caller", text=ph("Hello?")),
            ExampleLine(speaker="agent", text=ph("Did you register?")),
        ],
    )
    return script.model_copy(update=update)


def _cfg(body: str, *, screen: bool = True) -> AgentConfig:
    return AgentConfig(
        tenant_id="t",
        agent_id="a",
        name="Varsha",
        business="Rytu Khata",
        direction="outbound",
        language_primary=TE,
        system_prompt=without_outline(body),
        opening_line=ph("I am Varsha, an AI assistant."),
        call_is_recorded=True,
        facts_in_knowledge=True,
        knowledge_tool="search_knowledge",
        caller_has_screen=screen,
    )


def _block(body: str) -> str:
    start = body.index(f"{PROCEDURE_HEADER} ")
    end = body.find("\n\n[", start)
    return body[start : end if end > 0 else len(body)]


# --- the step blocks ------------------------------------------------------------------------


def test_each_step_carries_intent_actions_and_tagged_examples() -> None:
    body = compile_call_script(_script())
    block = _block(body)
    assert block.startswith(f"{PROCEDURE_HEADER} {STEPS_LEAD}")
    assert PROCEDURE_LEAD not in body
    assert "Install: Help them put the app on their home screen." in block
    assert "1. Ask them to open Chrome on their phone. Done when: the browser is open." in block
    assert block.count(STEP_EXAMPLES_LEAD) == 2
    for n in ("one", "two", "three", "four"):
        assert f'Telugu: "{ph(f"Install turn {n}, one action")}"' in block
    assert f'Telugu, if confused: "{ph("Install again, shorter")}"' in block
    assert f'Telugu, if stuck: "{ph("Install, one smaller action")}"' in block


def test_a_busy_turn_is_compiled_on_the_first_step_only() -> None:
    block = _block(compile_call_script(_script()))
    assert block.count("Telugu, if busy:") == 1
    intro, install = block.split("\n\nInstall:", 1)
    assert "if busy" in intro and "if busy" not in install


def _order(script: CallScript) -> list[str]:
    block = _block(compile_call_script(script)).split("\n\nInstall:", 1)[1]
    return [line for line in block.splitlines() if line.startswith("Telugu: ")]


def test_the_turn_order_is_fixed_per_script_and_moves_with_it() -> None:
    script = _script()
    assert _order(script) == _order(CallScript.model_validate_json(script.model_dump_json()))
    orders = {tuple(_order(_script(business_line=f"Farm app {n}."))) for n in range(12)}
    # The same four turns each time, in more than one order across scripts.
    assert {frozenset(order) for order in orders} == {frozenset(_order(script))}
    assert len(orders) > 1


def test_only_the_calls_languages_are_compiled() -> None:
    script = _script()
    stages = [
        stage.model_copy(update={"examples": {**stage.examples, EN: _examples(stage.name)}})
        for stage in script.stages
    ]
    both = script.model_copy(update={"stages": stages})
    english = find_language(EN)
    assert english is not None
    label = f'{english.english_name}: "'
    assert label in compile_call_script(both)
    only_te = compile_call_script(both, languages=(TE,))
    assert label not in only_te and 'Telugu: "' in only_te


def test_the_engine_step_carries_its_actions_and_points_at_the_examples() -> None:
    install = native_steps(_script())[1]
    assert "One a turn: 1. Ask them to open Chrome on their phone. Done when:" in install.detail
    assert examples_pointer("Install") in install.detail
    assert len(install.detail) <= STAGE_DETAIL_MAX
    intro = native_steps(_script())[0]
    assert intro.detail.endswith(examples_pointer("Introduction"))


def test_a_list_too_long_for_the_step_stays_a_pointer() -> None:
    long = [ProcedureStep(action="Ask them to tap the next button " + "x" * 120)] * 6
    script = _script()
    stages = [script.stages[0], script.stages[1].model_copy(update={"procedure": long})]
    step = native_steps(script.model_copy(update={"stages": stages}))[1]
    assert examples_pointer("Install", actions=True) in step.detail
    assert "One a turn:" not in step.detail


def test_an_example_led_script_has_no_example_call() -> None:
    body = compile_call_script(_script())
    assert is_example_led(_script())
    assert EXAMPLE_HEADER not in body


# --- the legacy path ------------------------------------------------------------------------


def _legacy() -> CallScript:
    stage = ConversationStage(
        id="install",
        name="Install",
        instruction="Help them put the app on their home screen.",
        sounds_like=ph("OK, open Chrome. Tell me when it is open."),
        procedure=INSTALL,
    )
    return _script(stages=[stage])


def test_a_legacy_line_is_quoted_as_tone_only_its_first_sentence() -> None:
    script = _legacy()
    assert not is_example_led(script)
    detail = native_steps(script)[0].detail
    assert "It sounds like" not in detail
    assert f'{TONE_LEAD} "<TE: OK, open Chrome."' in detail
    assert "Tell me when it is open" not in detail
    assert detail.endswith(procedure_pointer("Install"))
    body = compile_call_script(script)
    assert f"{PROCEDURE_HEADER} {PROCEDURE_LEAD}" in body
    assert STEP_EXAMPLES_LEAD not in body


def test_a_legacy_example_call_is_no_longer_framed_as_a_style_to_copy() -> None:
    body = compile_call_script(_legacy())
    assert f"{EXAMPLE_HEADER} {EXAMPLE_CALL_LEAD}" in body
    assert "Copy the style" not in body


def test_first_sentence() -> None:
    assert first_sentence("  One.  Two? ") == "One."
    assert first_sentence("No stop at all") == "No stop at all"
    assert first_sentence("") == ""


# --- the composed prompt --------------------------------------------------------------------


def test_the_prompt_quotes_no_fillers_no_booking_examples_and_one_opening() -> None:
    for script in (_script(), _legacy()):
        body = compile_call_script(script)
        assert OPENING_HEADER in body  # the engine's greeting still reads it from the body
        prompt = compose_engine_prompt(_cfg(body))
        fence = prompt.split("--- CLIENT SCRIPT", 1)[1]
        assert f"\n{OPENING_HEADER}\n" not in fence
        assert FILLERS_LEAD not in prompt
        assert "How a turn sounds" not in prompt
        assert "It sounds like" not in prompt
    style = style_for(TE)
    assert style is not None and style.fillers
    register = dict(engine_prompt_layers(_cfg(compile_call_script(_script()))))["spoken_register"]
    assert style.fillers[0].text not in register


def test_how_to_speak_is_trimmed_only_for_an_example_led_script() -> None:
    led = dict(engine_prompt_layers(_cfg(compile_call_script(_script()))))
    old = dict(engine_prompt_layers(_cfg(compile_call_script(_legacy()))))
    assert led["how_to_speak"].startswith(EXAMPLE_LED_GUIDANCE.split("\n", 2)[0])
    assert "after what?" in led["how_to_speak"]
    assert "Read back what you heard" in led["how_to_speak"]
    assert "digit by digit" in led["how_to_speak"]
    assert "Keep the language you greeted in" in led["how_to_speak"]
    assert "never formal or written-style words" in led["how_to_speak"]
    assert len(led["how_to_speak"]) < len(old["how_to_speak"])
    assert "Open with the point" in old["how_to_speak"]
    assert "Open with the point" not in led["how_to_speak"]
    assert VOICE_STYLE_GUIDANCE.split("\n", 2)[1] in old["how_to_speak"]


def test_hard_rule_five_and_confidentiality_are_untouched() -> None:
    prompt = compose_engine_prompt(_cfg(compile_call_script(_script())))
    assert CONFIDENTIALITY_RULE in prompt
    assert truthful_answer_directive(call_is_recorded=True) in prompt


def test_without_opening_sections_keeps_everything_else() -> None:
    body = "[BUSINESS]\nA shop.\n\n[OPENING]\nHello.\n\n[ENDING]\nBye."
    assert without_opening_sections(body) == "[BUSINESS]\nA shop.\n\n[ENDING]\nBye."
    assert without_opening_sections("[BUSINESS]\nA shop.") == "[BUSINESS]\nA shop."


# --- budget: a guided campaign with examples, Rytu-shaped -----------------------------------


def _rytu_with_examples() -> CallScript:
    """The 02-render Rytu Khata campaign shape (9 stages, six with step-by-step lists), each
    step with four turns, a confused and a stuck turn, and a busy turn on the first. Turns are
    80-character placeholders, about a ten-word Telugu turn."""
    names = [
        "Introduction",
        "App on home screen",
        "Login",
        "Language",
        "My Farms",
        "First expense",
        "First sale",
        "Dashboard",
    ]

    def turn(name: str, n: int) -> str:
        return ph(f"{name} turn {n} with one action").ljust(80, ".")

    stages = []
    for i, name in enumerate(names, 1):
        stages.append(
            ConversationStage(
                id=f"s{i}",
                step=i,
                name=name,
                instruction=f"Help them with {name.lower()} on their phone, one action a turn.",
                procedure=INSTALL if i > 1 and i < 8 else [],
                examples={
                    TE: StepExamples(
                        turns=[turn(name, n) for n in range(1, 5)],
                        confused=turn(name, 5),
                        stuck=turn(name, 6),
                        busy=turn(name, 7) if i == 1 else "",
                    )
                },
                branches=[StageBranch(when="Still stuck after every way", target="call_back")],
                otherwise=f"s{i + 1}" if i < len(names) else "s9",
            )
        )
    stages.append(
        ConversationStage(
            id="s9",
            step=9,
            name="Close",
            mode="say",
            instruction="Thank them and close.",
            scripts={TE: ph("Thank you, call us with any doubt.")},
            otherwise="end",
        )
    )
    return CallScript(
        schema_version=2,
        business_line="Rytu Khata is a farm accounts app for farmers in Telangana and Andhra.",
        identity="You are Varsha from Rytu Khata.",
        goal="Help registered farmers install the app and enter their first farm and sale.",
        outbound_purpose="to help them start using the Rytu Khata app",
        opening_line=ph("Hello {{lead_name}} garu, calling from Rytu Khata, a good time?"),
        stages=stages,
        step_outcomes=[
            StepOutcome(step=n, outcome=f"The person says step {n} is done") for n in range(1, 10)
        ],
        ending="Thank them warmly and end the call.",
    )


def test_a_guided_campaign_with_examples_fits_the_engine() -> None:
    script = _rytu_with_examples()
    collect = (CollectField(label="Number of farms"), CollectField(label="Main crop"))
    body = compile_call_script(script, collect=collect, languages=(TE,))
    cfg = _cfg(body).model_copy(update={"script_steps": native_steps(script)})
    prompt = compose_engine_prompt(cfg)
    details = [len(step.detail) for step in native_steps(script)]
    print(f"guided campaign with examples: {len(prompt)} chars, step details {details}")
    # ThinnestAI: instructions up to 20,000 characters through the API, each step's detail
    # up to 600 (thinnest-findings/mirror/snapshots/2026-11-26/pages/agent/behaviour.md:44-46).
    assert len(prompt) <= INSTRUCTIONS_MAX_CHARS - 3_000
    assert max(details) <= STAGE_DETAIL_MAX


# --- a deploy that changes these republishes every live agent -------------------------------


def test_the_example_led_rules_move_the_platform_revision(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api.agents.live_apply import platform_prompt_revision
    from calevate_shared import call_script, engine

    before = platform_prompt_revision()
    for module, name in (
        (engine, "EXAMPLE_LED_GUIDANCE"),
        (call_script, "STEPS_LEAD"),
        (call_script, "EXAMPLES_POINTER"),
    ):
        with monkeypatch.context() as patch:
            patch.setattr(module, name, getattr(module, name) + " x")
            assert platform_prompt_revision() != before, name
