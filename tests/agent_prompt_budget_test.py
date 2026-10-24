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
    CallScript,
    CollectField,
    Objection,
    Pronunciation,
    SpeakingStyle,
    compile_call_script,
    native_steps,
    splice_quick_facts,
    without_outline,
)
from calevate_shared.engine import CALL_INSTRUCTIONS, AgentConfig, compose_engine_prompt

#: Characters a starter leaves for what the owner adds: pinned facts at their ceiling plus
#: 7,000 of the owner's own script. Lowering it is a founder decision.
OWNER_RESERVE = MAX_PINNED_CHARS + 7_000

#: Characters the long script below must still leave free: room for its pinned facts to grow
#: to their ceiling and 6,000 more of the owner's text.
LONG_MARGIN = MAX_PINNED_CHARS + 6_000

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


#: What a call reads of OURS on every turn for the agents below: the platform layers of the
#: instructions plus `CALL_INSTRUCTIONS`, which the engine reads on calls in place of its
#: default call rules. The founder's rule of 14 Oct 2026 stands: a prompt change may not grow
#: this past the last cut (quality within budget). Measured as one sum since D-856 moved every
#: call rule but the call frame from `CALL_INSTRUCTIONS` into the instructions, so a call
#: reads each rule once; before it, D-849 left 6,137 + 1,112 = 7,249 (three languages) and
#: 5,160 + 1,112 = 6,272 (one). D-856 cut both by 476 while adding the reaction, half-answer,
#: offer and who-is-calling rules. D-883 (25 Oct 2026) trimmed restatements and added the
#: ambiguous-amount read-back: 6,708 to 6,485 (three) and 5,768 to 5,610 (one).
PER_CALL_MAX = 6_485
PER_CALL_ONE_LANGUAGE_MAX = 5_610


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
