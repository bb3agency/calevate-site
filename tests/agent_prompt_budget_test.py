"""The composed instructions fit ThinnestAI's 20,000-character box with room for the client.

The box is 20,000 characters in the API, the console and MCP alike (ThinnestAI, 12 Oct 2026;
`engine/thinnest.INSTRUCTIONS_MAX_CHARS`). Two agents are measured, Raghava
Organics in Telugu with facts in knowledge and stages sent as native steps:

* the retail STARTER, which must leave `OWNER_RESERVE` for what the owner adds;
* a LONG script an owner realistically writes on top of it (pinned facts, names and how to
  say them, a tone, another objection, a longer goal), which must still leave `LONG_MARGIN`.

A live agent over the box keeps its old instructions (D-752), so these two numbers are the
budget the platform layers are written against. The measured lengths are printed.
"""

from __future__ import annotations

from apps.api.agents.prompt_size import measure
from apps.api.agents.starters import starter_for
from apps.api.engine.thinnest import INSTRUCTIONS_MAX_CHARS
from apps.api.teach.pinned import MAX_PINNED_CHARS
from calevate_shared.call_script import (
    MAX_PROCEDURE_STEPS,
    PROCEDURE_STEP_MAX,
    PROCEDURE_WAIT_MAX,
    CallScript,
    CollectField,
    Objection,
    ProcedureStep,
    Pronunciation,
    SpeakingStyle,
    compile_call_script,
    native_steps,
    splice_quick_facts,
    without_outline,
)
from calevate_shared.engine import CALL_INSTRUCTIONS, AgentConfig, compose_engine_prompt

#: Characters a starter leaves for what the owner adds: pinned facts at their ceiling plus
#: 7,065 of the owner's own script, the measured room less 20 after the lean rebuild of 25 Nov
#: 2026 (6,920 before it). Lowering it is a founder decision.
OWNER_RESERVE = MAX_PINNED_CHARS + 7_065

#: Characters the long script below must still leave free: room for its pinned facts to grow
#: to their ceiling and 5,945 more of the owner's text, the measured room less 20 after the lean
#: rebuild of 25 Nov 2026 (5,785 before it).
LONG_MARGIN = MAX_PINNED_CHARS + 5_945

COLLECT = [
    CollectField(label="Name", required=True),
    CollectField(label="What they want to buy"),
    CollectField(label="Quantity"),
    CollectField(label="Pick up or delivery"),
    CollectField(label="Delivery area"),
]

#: Eight pinned facts of the length a shop writes: products, prices, delivery, hours.
PINNED = [
    (
        "What do you sell?",
        "Organic chilli, chilli powder, turmeric, jaggery and cold-pressed oils.",
    ),
    (
        "Price of chilli powder?",
        "Six hundred rupees a kg. Half a kg is three hundred and ten rupees.",
    ),
    ("Price of whole chilli?", "Five hundred and forty rupees a kg."),
    ("Do you deliver?", "Yes, in Hyderabad and Secunderabad, within two days of the order."),
    ("Delivery charge?", "Free above one thousand rupees, otherwise fifty rupees."),
    ("Shop hours?", "Nine in the morning to eight at night, every day except Tuesday."),
    ("Is it certified organic?", "Yes, our farm is certified by the state organic board."),
    ("Payment?", "UPI or cash on delivery."),
]


def _config(script: CallScript, job: str, *, pinned: bool = False) -> AgentConfig:
    body = compile_call_script(script, collect=COLLECT)
    if pinned:
        body = splice_quick_facts(body, PINNED)
    steps = native_steps(script)
    return AgentConfig(
        tenant_id="t",
        agent_id="a",
        name="Raghava Organics receptionist",
        business="Raghava Organics",
        direction="inbound" if job == "answer_calls" else "outbound",
        language_primary="te-IN",
        system_prompt=without_outline(body),
        opening_line="ఇది Raghava Organics AI assistant.",
        call_is_recorded=True,
        facts_in_knowledge=True,
        knowledge_tool="search_knowledge",
        script_steps=steps,
    )


def _starter(job: str) -> CallScript:
    return starter_for("retail", job).call_script(business="Raghava Organics", language="te-IN")  # type: ignore[arg-type]


def _long(job: str) -> CallScript:
    script = _starter(job)
    return script.model_copy(
        update={
            "goal": script.goal
            + " Help them choose the right pack size and tell them when it will reach them.",
            "style": SpeakingStyle(
                tone=(
                    "Warm and polite, like the owner of a neighbourhood shop who knows the "
                    "products."
                ),
                address_form="garu or andi, never sir or madam",
                pronunciations=[
                    Pronunciation(word="organic chilli", say_as="ఎండు మిర్చి"),
                    Pronunciation(word="chilli powder", say_as="కారం పొడి"),
                    Pronunciation(word="jaggery", say_as="బెల్లం"),
                ],
            ),
            "objections": [
                *script.objections,
                Objection(
                    objection="It is cheaper in the supermarket.",
                    response="Ours is grown without chemicals on our own farm and ground fresh "
                    "every week, so it keeps its colour and smell longer.",
                ),
            ],
        }
    )


def test_a_starter_leaves_room_in_the_instructions_box() -> None:
    for job in ("answer_calls", "call_leads"):
        cfg = _config(_starter(job), job)
        size = measure(cfg, INSTRUCTIONS_MAX_CHARS)
        assert size.total == len(compose_engine_prompt(cfg))
        print(
            f"{job} starter: {size.total} chars, {size.headroom} free, "
            f"{len(cfg.script_steps)} steps"
        )
        assert cfg.script_steps
        assert size.total <= INSTRUCTIONS_MAX_CHARS - OWNER_RESERVE, (job, size.total)


def test_a_long_realistic_script_fits_with_margin() -> None:
    for job in ("answer_calls", "call_leads"):
        cfg = _config(_long(job), job, pinned=True)
        size = measure(cfg, INSTRUCTIONS_MAX_CHARS)
        script = next(p.chars for p in size.layers if p.key == "client_script")
        print(f"{job} long: {size.total} chars (script {script}), {size.headroom} free")
        assert size.total <= INSTRUCTIONS_MAX_CHARS - LONG_MARGIN, (job, size.total)


#: Characters a guided call (the long script plus step-by-step lists of the size a phone
#: walk-through takes) must still leave: pinned facts at their ceiling and 2,350 more, the
#: measured room less 20 after the lean rebuild of 25 Nov 2026 (2,185 before it).
GUIDED_MARGIN = MAX_PINNED_CHARS + 2_350


def _guided(job: str) -> CallScript:
    """The long script with step-by-step lists (D-908) in its first stages: 15 steps in all,
    each written to its full length, as an app-install walk-through takes."""
    script = _long(job)
    step = ProcedureStep(
        action="a" * (PROCEDURE_STEP_MAX - 50), wait_for="w" * (PROCEDURE_WAIT_MAX - 60)
    )
    stages = list(script.stages)
    counts = (6, 5, 4)
    for i, count in enumerate(counts):
        stages[i] = stages[i].model_copy(update={"procedure": [step] * count})
    assert sum(counts) == MAX_PROCEDURE_STEPS
    return script.model_copy(update={"stages": stages})


def test_a_guided_call_with_step_by_step_lists_fits_with_margin() -> None:
    for job in ("answer_calls", "call_leads"):
        cfg = _config(_guided(job), job, pinned=True)
        size = measure(cfg, INSTRUCTIONS_MAX_CHARS)
        lists = next(p.chars for p in size.script_parts if p.label == "Step-by-step lists")
        print(f"{job} guided: {size.total} chars (lists {lists}), {size.headroom} free")
        # The lists ride in the instructions, outside the engine's 600-character steps.
        assert all(len(step.detail) <= 600 for step in cfg.script_steps)
        assert size.total <= INSTRUCTIONS_MAX_CHARS - GUIDED_MARGIN, (job, size.total)


def test_an_inbound_lines_engine_agent_that_places_calls_fits_the_same_margins() -> None:
    """D-1019 D2: a line's engine agent answers AND places its voice's call-backs, so it
    carries the placed-call values and rules on top of the answering script."""
    margins = ((_starter, False, OWNER_RESERVE), (_long, True, LONG_MARGIN))
    for build, pinned, margin in (*margins, (_guided, True, GUIDED_MARGIN)):
        cfg = _config(build("answer_calls"), "answer_calls", pinned=pinned).model_copy(
            update={"places_call_backs": True}
        )
        size = measure(cfg, INSTRUCTIONS_MAX_CHARS)
        print(f"line {build.__name__}: {size.total} chars, {size.headroom} free")
        assert size.total <= INSTRUCTIONS_MAX_CHARS - margin, (build.__name__, size.total)


#: What a call reads of OURS on every turn for the agents below: the platform layers of the
#: instructions plus `CALL_INSTRUCTIONS`, which the engine reads on calls in place of its
#: default call rules. The founder's rule of 14 Oct 2026 stands: a prompt change may not grow
#: this past the last cut (quality within budget). Each limit is the measured size plus 20.
#: Measured 7,621 and 6,847 after the lean rebuild of 25 Nov 2026
#: (`docs/evidence/lean-prompt-2026-11-25.md`; 7,796 and 6,957 before it).
PER_CALL_MAX = 7_641
PER_CALL_ONE_LANGUAGE_MAX = 6_867


def _platform_only(languages_extra: list[str]) -> AgentConfig:
    return AgentConfig(
        tenant_id="t",
        agent_id="a",
        name="A",
        business="Raghava Organics",
        direction="inbound",
        language_primary="te-IN",
        languages_extra=languages_extra,
        system_prompt="",
        opening_line="",
        call_is_recorded=True,
        facts_in_knowledge=True,
        knowledge_tool="search_knowledge",
    )


def test_what_a_call_reads_of_ours_stays_small() -> None:
    three = len(compose_engine_prompt(_platform_only(["hi-IN", "en-IN"]))) + len(CALL_INSTRUCTIONS)
    one = len(compose_engine_prompt(_platform_only([]))) + len(CALL_INSTRUCTIONS)
    print(f"per call turn: three languages {three} chars, one language {one} chars")
    assert three <= PER_CALL_MAX
    assert one <= PER_CALL_ONE_LANGUAGE_MAX
