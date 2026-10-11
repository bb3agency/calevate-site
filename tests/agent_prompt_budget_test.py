"""The composed instructions fit ThinnestAI's 8,000-character box with room for the client.

ThinnestAI's console showed an agent at "8249/8000 — re-sent on every reply" (founder
screenshot, 10 Oct 2026) while its API reference says 20,000; the lower figure is the
ceiling (`engine/thinnest.INSTRUCTIONS_MAX_CHARS`). Two agents are measured, Raghava
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
from calevate_shared.engine import AgentConfig, compose_engine_prompt

#: Characters a starter leaves for what the owner adds. 1,700 under D-714, 900 after D-739
#: put the turn-shape and spoken-voice rules in every prompt; D-752 tightened the platform
#: layers so a starter leaves at least this again. Lowering it is a founder decision.
OWNER_RESERVE = 1_100

#: Characters the long script below must still leave free (D-752). Thin on purpose: the
#: platform layers are at their floor without dropping a rule (the confidentiality rule and
#: the truthful answers alone are 1,675), so more room needs the box itself to grow (vendor
#: question 12) or the speaking rules to move to `voice.callInstructions` (questions 9 and
#: 14). Until then the Script page meter tells the owner what to shorten.
LONG_MARGIN = 25

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


def test_the_platform_layers_alone_stay_small() -> None:
    cfg = AgentConfig(
        tenant_id="t",
        agent_id="a",
        name="A",
        direction="inbound",
        language_primary="te-IN",
        languages_extra=["hi-IN", "en-IN"],
        system_prompt="",
        opening_line="",
        call_is_recorded=True,
        facts_in_knowledge=True,
        knowledge_tool="search_knowledge",
    )
    platform = len(compose_engine_prompt(cfg))
    print(f"platform layers, three languages: {platform} chars")
    assert platform <= 6_300
