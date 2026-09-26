"""`VoiceEngine.get_agent` — the fake adapter's read-back tracks its own state.

The conformance suite (`packages/shared/tests/engine_conformance`) holds every adapter to
the contract's behaviour. This file covers what a contract clause cannot: that the `fake`
adapter's read-back really tracks its own store, because a read-back that agrees with the
caller by construction measures nothing (OPERATIONS §2 gate 2).
"""

from __future__ import annotations

import pytest
from apps.api.core.errors import ProblemError
from apps.api.engine.fake import FakeEngine
from calevate_shared.engine import (
    CLIENT_SCRIPT_OPEN,
    PLATFORM_RULES_PREAMBLE,
    TRUTHFUL_ANSWER_DIRECTIVE,
    AgentConfig,
    KBSourceRef,
)


def _cfg(prompt: str = "You are the receptionist for Sunrise Clinic.") -> AgentConfig:
    return AgentConfig(
        tenant_id="0199a0b0-0000-7000-8000-000000000001",
        agent_id="0199a0b0-0000-7000-8000-000000000002",
        name="Sunrise Clinic receptionist",
        direction="inbound",
        system_prompt=prompt,
        opening_line="Idi AI assistant. Ee call record avutundi.",
    )


# --- fake ---------------------------------------------------------------------


async def test_fake_read_back_reflects_the_preceding_update() -> None:
    """The read-back tracks the STORE, not the last argument.

    Two writes to the same agent, and the second must be what comes back. A read-back
    that returned what it was handed most recently would also pass this — which is why
    the conformance suite additionally reads a second, untouched agent — but a read-back
    frozen at creation fails right here, and that is the other way to get this wrong.
    """
    engine = FakeEngine()
    ref = await engine.create_agent(_cfg("Receptionist, revision one."))
    assert (await engine.get_agent(ref)).carries_prompt_marker("revision one") is True

    await engine.update_agent(ref, _cfg("Receptionist, revision two."))
    snapshot = await engine.get_agent(ref)

    assert snapshot.carries_prompt_marker("revision two") is True
    assert snapshot.carries_prompt_marker("revision one") is False


async def test_fake_read_back_carries_the_opening_line_the_way_an_engine_holds_it() -> None:
    """Hard rule 5 is a property of the object the ENGINE holds, not of our config row.
    The fake renders it through `compose_engine_prompt`, exactly as
    `BolnaEngine._agent_body` does — opening line prepended, platform rules appended
    (D-163) — so a caller cannot write an equality check that only ever passes against
    the fake, and cannot get a fake-only agent that answers dishonestly.

    THE FIRST ASSERTION USED TO BE `startswith(cfg.opening_line)` AND WAS LOOSENED
    DELIBERATELY, WHICH IS WORTH READING BEFORE ASSUMING IT WAS WEAKENED. The platform
    rules are now stated FIRST as well as last, because the floor was enforced as
    presence and not as precedence: a client script could tell the agent to deny being an
    AI and every containment check still passed. So the prompt opens with
    `PLATFORM_RULES_PREAMBLE` and the opening line follows it.

    What this test is actually about is unchanged and is now checked more precisely: the
    opening line is CARRIED and sits ahead of the client's script, so the notice a caller
    hears is ours and is not something an author can push down the prompt.
    """
    engine = FakeEngine()
    cfg = _cfg()
    ref = await engine.create_agent(cfg)
    prompt = (await engine.get_agent(ref)).system_prompt
    assert prompt is not None
    assert prompt.startswith(PLATFORM_RULES_PREAMBLE)
    assert cfg.opening_line in prompt
    assert prompt.index(cfg.opening_line) < prompt.index(CLIENT_SCRIPT_OPEN)
    assert prompt.rstrip().endswith(TRUTHFUL_ANSWER_DIRECTIVE.rstrip())


async def test_fake_read_back_tracks_attach_and_detach() -> None:
    """D-41's instrument, exercised where an engine really does clear the reference."""
    engine = FakeEngine()
    ref = await engine.create_agent(_cfg())
    handle = await engine.attach_kb(ref, KBSourceRef(kb_id="kb_1", title="Fees", text="500"))
    assert (await engine.get_agent(ref)).references_kb(handle) is True

    await engine.detach_kb(ref, handle)
    assert (await engine.get_agent(ref)).references_kb(handle) is False


async def test_fake_refuses_to_describe_an_agent_it_never_created() -> None:
    engine = FakeEngine()
    with pytest.raises(ProblemError):
        await engine.get_agent("fakeagent_never_created")
