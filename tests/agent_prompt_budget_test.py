"""The composed instructions fit ThinnestAI's 8,000-character box with room for the client.

ThinnestAI's console showed an agent at "8249/8000 — re-sent on every reply" (founder
screenshot, 10 Oct 2026) while its API reference says 20,000; the lower figure is the
ceiling (`engine/thinnest.INSTRUCTIONS_MAX_CHARS`). A typical agent — a starter script for
Raghava Organics, Telugu, facts in knowledge, stages sent as native steps — must leave most
of the box for what the owner adds. The measured lengths are printed for the report.
"""

from __future__ import annotations

from apps.api.agents.starters import starter_for
from apps.api.engine.thinnest import INSTRUCTIONS_MAX_CHARS
from calevate_shared.call_script import (
    CollectField,
    compile_call_script,
    native_steps,
    without_outline,
)
from calevate_shared.engine import AgentConfig, compose_engine_prompt

COLLECT = [
    CollectField(label="Name", required=True),
    CollectField(label="What they want to buy"),
    CollectField(label="Quantity"),
    CollectField(label="Pick up or delivery"),
    CollectField(label="Delivery area"),
]


def _composed(job: str) -> tuple[int, int, int]:
    script = starter_for("retail", job).call_script(business="Raghava Organics", language="te-IN")  # type: ignore[arg-type]
    body = compile_call_script(script, collect=COLLECT)
    steps = native_steps(script)
    cfg = AgentConfig(
        tenant_id="t",
        agent_id="a",
        name="Raghava Organics receptionist",
        direction="inbound" if job == "answer_calls" else "outbound",
        language_primary="te-IN",
        system_prompt=without_outline(body),
        opening_line="Idi Raghava Organics AI assistant.",
        call_is_recorded=True,
        facts_in_knowledge=True,
        knowledge_tool="search_knowledge",
        script_steps=steps,
    )
    prompt = compose_engine_prompt(cfg)
    return len(prompt), len(without_outline(body)), len(steps)


def test_a_typical_agent_leaves_room_in_the_instructions_box() -> None:
    for job in ("answer_calls", "call_leads"):
        total, script_chars, steps = _composed(job)
        print(f"{job}: composed {total} chars, client script {script_chars}, {steps} steps")
        assert steps > 0
        # At least 1,700 characters left for what the owner adds.
        assert total <= INSTRUCTIONS_MAX_CHARS - 1_700, (job, total)


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
    assert platform <= 5_700
