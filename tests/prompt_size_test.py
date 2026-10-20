"""The instructions' length, counted the way a publish sends them, and never in silence (D-752).

A live agent whose instructions outgrew the calling system's box kept its old ones while
every screen said nothing (`live_apply_runs` failure `engine_prompt_too_long`, 11 Oct 2026).
These pin: the count is the composed prompt's own length, by layer; the meter, the save, the
publish and the pinned facts all refuse with the owner's sentence before anything is stored
or sent; a refused live update is shown on the agent; and the diagnosis tool prints counts,
never text.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from apps.api.agents import live_apply, prompt_size, script_builder
from apps.api.agents.engine_limits import (
    PROMPT_TOO_LONG,
    PromptTooLongError,
    refuse_over_engine_limits,
)
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session, untenanted_session
from calevate_shared.call_script import CallScript, ScriptStep
from calevate_shared.engine import (
    CONFIDENTIALITY_RULE,
    TRUTHFUL_ANSWER_MARKER,
    AgentConfig,
    compose_engine_prompt,
    engine_prompt_layers,
)
from sqlalchemy import text
from tests.thinnest_publish_limits_test import _agent_with_script, _selected, _thinnest

SECRET = "secret-staff-mobile-9876543210"


def _cfg(script: str, **kw: Any) -> AgentConfig:
    base: dict[str, Any] = {
        "tenant_id": "t",
        "agent_id": "a",
        "name": "Raghava Organics receptionist",
        "direction": "outbound",
        "language_primary": "te-IN",
        "system_prompt": script,
        "opening_line": "ఇది Raghava Organics AI assistant.",
        "call_is_recorded": True,
        "facts_in_knowledge": True,
        "knowledge_tool": "search_knowledge",
    }
    return AgentConfig(**{**base, **kw})


SCRIPT = (
    "[BUSINESS]\nRaghava Organics\n\n[OBJECTIONS] In this spirit.\nQ: Too costly.\n"
    f"A: It is organic.\n\n[SPEAKING STYLE]\nTone: warm\nSay these names exactly like this: "
    f'chilli as "మిర్చి"\n\n[QUICK FACTS] These win.\n- {SECRET}'
)


# --- the count is the composed prompt's own length -------------------------------------


@pytest.mark.parametrize(
    "extra",
    [
        {},
        {"languages_extra": ["hi-IN", "en-IN"]},
        {"caller_memory_enabled": True},
        {"forwarded_line": True, "callbacks_offered": False},
        {"system_prompt": ""},
    ],
)
def test_the_layers_are_the_composed_prompt(extra: dict[str, Any]) -> None:
    cfg = _cfg(SCRIPT, **extra)
    prompt = compose_engine_prompt(cfg)
    assert "\n\n".join(t for _k, t in engine_prompt_layers(cfg)) == prompt
    size = prompt_size.measure(cfg, 8_000)
    assert size.total == len(prompt)
    assert sum(p.chars for p in size.layers) == len(prompt)


def test_every_layer_is_counted_and_the_script_adds_up() -> None:
    size = prompt_size.measure(_cfg(SCRIPT, languages_extra=["hi-IN"]), 8_000)
    keys = {p.key for p in size.layers}
    assert {
        "preamble",
        "how_to_speak",
        "languages",
        "spoken_register",
        "business_facts",
        "notices",
        "client_script",
        "what_you_can_do",
        "confidentiality",
        "truthful_answers",
        "separator",
    } <= keys
    script_layer = next(p.chars for p in size.layers if p.key == "client_script")
    assert sum(p.chars for p in size.script_parts) == script_layer
    labels = {p.label for p in size.script_parts}
    assert {"Business line", "Objections", "Speaking style", "Names and how to say them"} <= labels
    assert "Pinned facts" in labels


def test_the_report_carries_counts_and_never_text() -> None:
    size = prompt_size.measure(_cfg(SCRIPT + ("\nmore " * 2_000)), 8_000)
    report = "\n".join(prompt_size.lines(size))
    assert "OVER by" in report and f"{size.total:,}" in report
    for leaked in (SECRET, "Raghava Organics", "Too costly", TRUTHFUL_ANSWER_MARKER):
        assert leaked not in report
    assert CONFIDENTIALITY_RULE.splitlines()[1] not in report


def test_the_report_adds_what_the_calling_system_puts_around_it() -> None:
    """ThinnestAI adds about 4,700 characters of its own rules on every turn, outside the
    box (email of 19 Oct 2026, VENDOR-STATED): the per-turn figure is ours plus theirs, and
    the box verdict still counts ours alone. Its 1,675-character default call rules come on
    top only when it judges the agent has none, so the per-turn figure is a range."""
    cfg = _cfg(SCRIPT)
    size = prompt_size.measure_config(cfg, _thinnest())
    assert size.engine_added == 4_700 and size.engine_default_rules == 1_675
    assert size.per_turn == size.total + 4_700
    assert size.per_turn_with_default_rules == size.total + 4_700 + 1_675
    assert size.over == 0
    report = "\n".join(prompt_size.lines(size))
    assert f"{size.per_turn:,} to {size.per_turn_with_default_rules:,}" in report
    assert "4,700" in report and "1,675" in report
    unknown = prompt_size.measure(cfg, 8_000)
    assert unknown.per_turn is None and unknown.per_turn_with_default_rules is None
    without_defaults = prompt_size.measure(cfg, 8_000, engine_added=4_700)
    last = prompt_size.lines(without_defaults)[-1]
    assert last.endswith(f" {without_defaults.per_turn:>6,}")


# --- the refusal ----------------------------------------------------------------------


def test_the_refusal_is_the_owner_sentence_with_the_longest_parts() -> None:
    cfg = _cfg(SCRIPT + "\n\n[EXAMPLE CALL] style\n" + ("You: hello there\n" * 1_300))
    with pytest.raises(PromptTooLongError) as caught:
        refuse_over_engine_limits(_thinnest(), cfg)
    problem = caught.value
    over = len(compose_engine_prompt(cfg)) - 20_000
    assert problem.code == PROMPT_TOO_LONG
    assert problem.detail == (
        f"Your script is {over:,} characters too long for the calling system; "
        "shorten it to put it live."
    )
    assert "example call" in (problem.remediation or "")
    assert SECRET not in f"{problem.detail} {problem.remediation}"
    recorded = live_apply.failure_detail(problem)
    assert recorded["over_chars"] == over and recorded["limit_chars"] == 20_000
    assert recorded["longest"][0]["label"] == "Example call"
    assert SECRET not in json.dumps(recorded)


def test_a_refused_update_reads_as_a_sentence_for_each_code() -> None:
    too_long = live_apply.held_back_from(
        {
            "code": PROMPT_TOO_LONG,
            "over_chars": 412,
            "longest": [{"label": "Objections", "chars": 900}],
        },
        None,
    )
    assert too_long.message == (
        "Your script is 412 characters too long for the calling system; shorten it to put it live."
    )
    assert too_long.longest == (("Objections", 900),)
    agreements = live_apply.held_back_from({"code": "agreements_not_accepted"}, None)
    assert "agreements" in agreements.message and "Agreements & readiness" in agreements.message
    other = live_apply.held_back_from({"code": "engine_rejected"}, None)
    assert other.message == live_apply.HELD_BACK_GENERIC


# --- the meter, the save and "Put it live", against the database -------------------------


def _long_script(words: int) -> CallScript:
    return CallScript(
        opening_line="Namaskaram, Raghava Organics nunchi.",
        steps=[ScriptStep(instruction="Ask what they need.")],
        end_call_extra_rules=["word " * words],
    )


async def test_the_meter_counts_what_a_publish_sends_and_says_when_it_is_over() -> None:
    tenant_id, agent_id = await _agent_with_script("Greet, then help.")
    with _selected(_thinnest()):
        async with tenant_session(tenant_id) as session:
            fits = await script_builder.compiled_preview(session, agent_id, _long_script(10))
            over = await script_builder.compiled_preview(session, agent_id, _long_script(4_200))
    assert fits.size.fits and fits.instructions_limit == 20_000
    # Everything the calling system receives, not only the client's text.
    assert fits.size.total == fits.instructions_chars > 3_000
    assert not over.size.fits and over.size.over == over.instructions_chars - 20_000
    assert over.size.longest_script_parts()[0].chars > 20_000


async def test_save_and_put_live_refuse_before_anything_is_stored() -> None:
    tenant_id, agent_id = await _agent_with_script("Greet, then help.")
    with _selected(_thinnest()):
        async with tenant_session(tenant_id) as session:
            before = (
                await session.execute(
                    text("SELECT count(*) FROM prompt_versions WHERE agent_id = :a"),
                    {"a": agent_id},
                )
            ).scalar()
            with pytest.raises(PromptTooLongError) as caught:
                await script_builder.refuse_if_too_long(session, agent_id, _long_script(4_200))
            after = (
                await session.execute(
                    text("SELECT count(*) FROM prompt_versions WHERE agent_id = :a"),
                    {"a": agent_id},
                )
            ).scalar()
            await script_builder.refuse_if_too_long(session, agent_id, _long_script(10))
    assert "characters too long for the calling system" in caught.value.detail
    assert before == after


# --- a refused live update is shown on the agent ---------------------------------------


async def test_a_recorded_refusal_is_held_back_until_the_agent_goes_live_again() -> None:
    tenant_id, agent_id = await _agent_with_script("Greet, then help.")
    failure = {
        "tenant_id": str(tenant_id),
        "agent_id": str(agent_id),
        "code": PROMPT_TOO_LONG,
        "at": "2026-10-11T10:00:00+00:00",
        "total_chars": 8_412,
        "limit_chars": 8_000,
        "over_chars": 412,
        "longest": [{"label": "Pinned facts", "chars": 1_400}],
    }
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO live_apply_runs (id, scope, reasons, status, finished_at, "
                "failed, failures) VALUES (:id, 'platform', '[\"platform_prompt:x\"]', "
                "'done', now(), 1, CAST(:f AS jsonb))"
            ),
            {"id": uuid.uuid4(), "f": json.dumps([failure])},
        )
    from datetime import UTC, datetime

    async with untenanted_session() as session:
        held = await live_apply.held_back(session, agent_id=agent_id, since=None)
        later = await live_apply.held_back(
            session, agent_id=agent_id, since=datetime(2026, 10, 11, 11, tzinfo=UTC)
        )
        other = await live_apply.held_back(session, agent_id=uuid.uuid4(), since=None)
    assert held is not None and held.over_chars == 412
    assert held.message.startswith("Your script is 412 characters too long")
    assert held.longest == (("Pinned facts", 1_400),)
    assert later is None and other is None


# --- pinned facts cannot push a live agent over --------------------------------------


async def test_a_pinned_fact_that_would_push_a_live_agent_over_is_refused() -> None:
    from apps.api.teach import pinned as pinned_store

    # `_agent_with_script` resets the engine cache, so agents are made outside `_selected`.
    tenant_id, agent_id = await _agent_with_script("w")
    with _selected(_thinnest()) as engine:
        async with tenant_session(tenant_id) as session:
            size = await prompt_size.measure_agent(
                session, tenant_id=tenant_id, agent_id=agent_id, engine=engine
            )
    # Forty characters short of the box: the fact below does not fit beside it.
    tenant_id, agent_id = await _agent_with_script("w" * (1 + 20_000 - size.total - 40))
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET status = 'live' WHERE id = :a"), {"a": agent_id}
        )
    with _selected(_thinnest()):
        async with tenant_session(tenant_id) as session:
            with pytest.raises(ProblemError) as caught:
                await pinned_store.add_pinned(
                    session,
                    tenant_id=tenant_id,
                    question="Delivery?",
                    answer="Free above one thousand rupees, otherwise fifty rupees.",
                    origin="taught",
                    created_by=None,
                )
    assert caught.value.code == "pinned_facts_too_long_for_agent"
    assert "too long for the calling system" in caught.value.detail


# --- the diagnosis tool --------------------------------------------------------------


async def test_the_tool_prints_counts_for_one_agent_and_never_text(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts import prompt_size as tool

    tenant_id, agent_id = await _agent_with_script(f"[BUSINESS]\n{SECRET}\n" + "word " * 4_200)
    with _selected(_thinnest()):
        code = await tool.one(agent_id)
    out = capsys.readouterr().out
    assert code == 1
    assert "OVER by" in out and "Your script" in out and "Business line" in out
    assert SECRET not in out and TRUTHFUL_ANSWER_MARKER not in out and "word word" not in out
    del tenant_id


async def test_the_tool_lists_live_agents_one_line_each(capsys: pytest.CaptureFixture[str]) -> None:
    from scripts import prompt_size as tool

    tenant_id, agent_id = await _agent_with_script(f"{SECRET} " + "Greet, then help.")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET status = 'live' WHERE id = :a"), {"a": agent_id}
        )
    with _selected(_thinnest()):
        code = await tool.all_live()
    out = capsys.readouterr().out
    line = next(x for x in out.splitlines() if x.startswith(str(agent_id)))
    total, limit, headroom = (int(v) for v in line.split()[1:4])
    assert limit == 20_000 and headroom == limit - total
    assert SECRET not in out
    assert code in (0, 1, 2)
