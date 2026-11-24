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
from apps.api.agents import service as agents_service
from apps.api.agents.engine_limits import (
    PROMPT_TOO_LONG,
    PromptTooLongError,
    refuse_over_engine_limits,
)
from apps.api.campaigns import workspace as campaign_workspace
from apps.api.campaigns.notes import JobKind, save_notes
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine
from apps.api.inbound import lines
from calevate_shared.call_script import SCRIPT_SCHEMA_VERSION, CallScript, Objection, ScriptStep
from calevate_shared.engine import (
    CALL_INSTRUCTIONS,
    CONFIDENTIALITY_RULE,
    TRUTHFUL_ANSWER_MARKER,
    AgentConfig,
    compose_engine_prompt,
    engine_prompt_layers,
)
from calevate_shared.extraction import ExtractionField
from sqlalchemy import text
from tests.notes_per_job_test import _campaign
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
    box (email of 19 Oct 2026, VENDOR-STATED), and its 1,675-character default call rules on
    top, because only `voice.callInstructions` replaces them and we send none (email of
    21 Oct 2026, §21): the per-turn figure is one number, and the box verdict still counts
    ours alone."""
    cfg = _cfg(SCRIPT)
    size = prompt_size.measure_config(cfg, _thinnest())
    assert size.engine_added == 4_700 and size.call_rules == 1_675
    assert size.per_turn == size.total + 4_700 + 1_675
    assert size.over == 0
    report = "\n".join(prompt_size.lines(size))
    assert report.splitlines()[-1].endswith(f" {size.per_turn:>6,}")
    assert "4,700" in report and "1,675" in report and " to " not in report.splitlines()[-1]
    unknown = prompt_size.measure(cfg, 8_000)
    assert unknown.per_turn is None
    without_defaults = prompt_size.measure(cfg, 8_000, engine_added=4_700)
    last = prompt_size.lines(without_defaults)[-1]
    assert last.endswith(f" {without_defaults.per_turn:>6,}")


def test_our_call_rules_replace_the_default_ones_in_the_per_turn_figure() -> None:
    """With `thinnest_call_instructions` on, `voice.callInstructions` replaces the 1,675
    default characters (D-850): the per-turn figure counts ours instead, and says so."""
    off = prompt_size.measure_config(_cfg(SCRIPT), _thinnest())
    on = prompt_size.measure_config(_cfg(SCRIPT, engine_call_instructions=True), _thinnest())
    assert on.total == off.total
    assert (on.call_rules, on.call_rules_ours) == (len(CALL_INSTRUCTIONS), True)
    assert on.per_turn == off.total + 4_700 + len(CALL_INSTRUCTIONS)
    assert on.per_turn is not None and off.per_turn is not None and on.per_turn < off.per_turn
    report = "\n".join(prompt_size.lines(on))
    assert "plus our call rules" in report and "default call rules" not in report
    assert CALL_INSTRUCTIONS not in report


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


# --- a campaign or an inbound line is measured as its own engine agent -----------------

#: Enough "What it notes" to add thousands of characters to a job's compiled script.
JOB_NOTES = [
    ExtractionField(
        key=f"detail_{n}", label=f"Detail {n}", type="text", reason="to follow up " * 35
    )
    for n in range(20)
]


async def _job(kind: JobKind, tenant_id: uuid.UUID, agent_id: uuid.UUID) -> uuid.UUID:
    if kind == "campaign":
        return await _campaign(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        return await lines.create_line(
            session, tenant_id=tenant_id, agent_id=agent_id, name="Desk", created_by=None
        )


async def _job_total(
    session: Any, kind: JobKind, tenant_id: uuid.UUID, job_id: uuid.UUID, script: CallScript
) -> int:
    if kind == "campaign":
        config = await agents_service.campaign_config(
            session, tenant_id=tenant_id, campaign_id=job_id, script=script
        )
    else:
        config = await agents_service.line_config(
            session, tenant_id=tenant_id, line_id=job_id, script=script
        )
    return prompt_size.measure_config(config, get_engine()).total


async def _save_script(session: Any, kind: JobKind, job_id: uuid.UUID, script: CallScript) -> None:
    if kind == "campaign":
        await campaign_workspace.save_script(session, job_id, script, author="owner")
    else:
        await lines.save_script(session, job_id, script, author="owner")


def _v2_script(filler: int) -> CallScript:
    """A v2 script (the version that compiles a job's notes) carrying about `filler` more
    characters of objection answers than the bare one."""
    chunks = [950] * (max(filler, 0) // 950) + [max(filler, 0) % 950]
    return CallScript(
        schema_version=SCRIPT_SCHEMA_VERSION,
        opening_line="Namaskaram, Raghava Organics nunchi.",
        goal="Help the caller with what they need.",
        objections=[
            Objection(objection=f"Doubt {n}", response=("word " * (size // 5)).strip() or "Yes.")
            for n, size in enumerate(chunks)
            if size
        ],
    )


def _sized(bare_total: int, target: int) -> CallScript:
    """A script whose measured total lands near `target`, a few characters out per objection."""
    return _v2_script(target - bare_total)


async def _stored(kind: JobKind, tenant_id: uuid.UUID, job_id: uuid.UUID) -> Any:
    sql = {
        "campaign": "SELECT script, extraction_fields FROM campaigns WHERE id = :j",
        "line": "SELECT script, extraction_fields FROM inbound_lines WHERE id = :j",
    }[kind]
    async with tenant_session(tenant_id) as session:
        return (await session.execute(text(sql), {"j": job_id})).one()


@pytest.mark.parametrize("kind", ["campaign", "line"])
async def test_a_jobs_script_save_counts_what_it_notes(kind: JobKind) -> None:
    tenant_id, agent_id = await _agent_with_script("Greet, then help.")
    job_id = await _job(kind, tenant_id, agent_id)
    with _selected(_thinnest()):
        async with tenant_session(tenant_id) as session:
            await save_notes(session, kind, job_id, JOB_NOTES, expected_digest=None)
            agent_bare = (
                await script_builder.compiled_preview(session, agent_id, _v2_script(0))
            ).size.total
            job_bare = await _job_total(session, kind, tenant_id, job_id, _v2_script(0))
            added = job_bare - agent_bare
            assert added > 4_000
            # Fits the agent's own config, over once the job's notes are compiled in: the
            # agent-only measurement let this through to fail at Start or put-live.
            script = _sized(agent_bare, 20_000 - added // 2)
            assert (await script_builder.compiled_preview(session, agent_id, script)).size.fits
        before = (await _stored(kind, tenant_id, job_id)).script
        with pytest.raises(PromptTooLongError) as caught:
            async with tenant_session(tenant_id) as session:
                await _save_script(session, kind, job_id, script)
        assert (await _stored(kind, tenant_id, job_id)).script == before
        async with tenant_session(tenant_id) as session:
            await _save_script(session, kind, job_id, _v2_script(0))
        assert (await _stored(kind, tenant_id, job_id)).script == _v2_script(0).model_dump(
            mode="json"
        )
    assert "characters too long for the calling system" in caught.value.detail


@pytest.mark.parametrize("kind", ["campaign", "line"])
async def test_notes_that_push_a_jobs_saved_script_over_are_refused_and_not_stored(
    kind: JobKind,
) -> None:
    tenant_id, agent_id = await _agent_with_script("Greet, then help.")
    job_id = await _job(kind, tenant_id, agent_id)
    with _selected(_thinnest()):
        async with tenant_session(tenant_id) as session:
            await save_notes(session, kind, job_id, [], expected_digest=None)
            bare = await _job_total(session, kind, tenant_id, job_id, _v2_script(0))
            await save_notes(session, kind, job_id, JOB_NOTES, expected_digest=None)
            added = await _job_total(session, kind, tenant_id, job_id, _v2_script(0)) - bare
            await save_notes(session, kind, job_id, [], expected_digest=None)
            await _save_script(session, kind, job_id, _sized(bare, 20_000 - added // 2))
        with pytest.raises(PromptTooLongError) as caught:
            async with tenant_session(tenant_id) as session:
                await save_notes(session, kind, job_id, JOB_NOTES, expected_digest=None)
        assert (await _stored(kind, tenant_id, job_id)).extraction_fields == []
        async with tenant_session(tenant_id) as session:
            assert await save_notes(session, kind, job_id, JOB_NOTES[:2], expected_digest=None)
    assert caught.value.code == PROMPT_TOO_LONG
    assert caught.value.title.startswith(f"These details make the {kind}'s script too long")
    assert caught.value.remediation is not None
    assert caught.value.remediation.startswith("Note fewer details")


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


@pytest.mark.parametrize(
    ("status", "ref"),
    [
        ("live", None),
        # D-838's ready agent: the recompile republishes it, so it must fit too.
        ("paused", "ag_ready"),
    ],
)
async def test_a_pinned_fact_that_would_push_a_live_agent_over_is_refused(
    status: str, ref: str | None
) -> None:
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
            text(
                "UPDATE agents SET status = :s, "
                "engine_agent_ref = COALESCE(CAST(:r AS text), engine_agent_ref) WHERE id = :a"
            ),
            {"a": agent_id, "s": status, "r": ref},
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
