"""What a finished call left behind after the founder's 23 Nov 2026 test call.

An outbound call ringing an existing customer to help them install an app. Its summary spelt
the business "Raiṭa Khāta" for "Rytu Khata"; "What they want" (the client's "Help Required")
held the call's own task, cut off before its last steps; "Installation Status captured" sat
on the caller's "Android" and "Setup Progress captured" on their login rather than on the
lines that settled each; and "Not mentioned" listed core details no script ever asked for
(that last is the web's rule, `apps/web/src/lib/leadLabels.expectedButUnsaid`). The
transcripts here are English stand-ins; the code they exercise has no wording for any one
business.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from apps.workers import extraction as extraction_module
from apps.workers import pipeline
from apps.workers.call_language import _prompt as language_pass_prompt
from apps.workers.extraction import CallSetting
from apps.workers.pipeline import extractor_transcript
from calevate_shared.engine import ExecutionSnapshot
from calevate_shared.events import TranscriptTurn
from calevate_shared.extraction import (
    OUTBOUND_NEED_REASON,
    ExtractionSchemaSpec,
    MomentsBrief,
    build_extraction_prompt,
    spell_business_name,
)
from calevate_shared.lead_fields import with_core
from tests.smoke_pipeline_test import _seed_tenant

MARKED = f"Rai{chr(0x1E6D)}a Kh{chr(0x101)}ta"


# --- 1. the business's own spelling -------------------------------------------------------


def test_a_name_heard_with_other_vowels_is_spelt_the_business_way() -> None:
    summary = f'The customer installed the "{MARKED}" app on their Android phone.'
    assert spell_business_name(summary, "Rytu Khata") == (
        'The customer installed the "Rytu Khata" app on their Android phone.'
    )
    assert spell_business_name("Uses Raita Khaata daily.", "Rytu Khata") == (
        "Uses Rytu Khata daily."
    )


def test_a_two_word_name_run_together_is_spelt_the_business_way() -> None:
    assert spell_business_name("Opened Raitukhata on the phone.", "Rytu Khata") == (
        "Opened Rytu Khata on the phone."
    )


def test_words_that_only_share_consonants_are_left_alone() -> None:
    for untouched in (
        "Read the rate kit first.",
        "Rytu alone is not the name.",
        "Rytu Khata",
        "Rita Kitchen sells lunch.",
    ):
        assert spell_business_name(untouched, "Rytu Khata") == untouched


def test_the_language_pass_is_told_the_business_spelling() -> None:
    def prompt(name: str) -> str:
        return language_pass_prompt(
            language="Telugu",
            tag="te-IN",
            turns=[(0, "hello")],
            summary_en="",
            summary_local="local summary",
            want_summaries=True,
            business_name=name,
        )

    told = prompt("Rytu Khata")
    assert 'The business is called "Rytu Khata".' in told
    assert "never with accents or marks" in told
    assert "The business is called" not in prompt("")


# --- 2. key moments sit on the line that settled the value -------------------------------


def test_the_moments_rule_names_the_line_that_settled_a_final_state() -> None:
    prompt = build_extraction_prompt(
        ExtractionSchemaSpec(fields=with_core([])), "caller: hello", moments=MomentsBrief()
    )
    assert "the last caller line the value in your answer\n  rests on" in prompt
    assert "is settled\n  where the caller confirmed that final state" in prompt


# --- 3. what an outbound call's person wants is theirs, not the call's ------------------


def _need_line(prompt: str) -> str:
    return next(line for line in prompt.splitlines() if line.startswith('- "need"'))


def test_an_outbound_call_is_read_as_one_the_business_placed() -> None:
    spec = ExtractionSchemaSpec(fields=with_core([]))
    outbound = build_extraction_prompt(spec, "caller: hello", direction="outbound")
    inbound = build_extraction_prompt(spec, "caller: hello", direction="inbound")
    assert "The business placed this call" in outbound
    assert OUTBOUND_NEED_REASON in _need_line(outbound)
    assert "The business placed this call" not in inbound
    assert "why they called" in _need_line(inbound)
    assert inbound == build_extraction_prompt(spec, "caller: hello"), (
        "no direction reads as inbound, as the golden-transcript harness sends it"
    )


def test_a_list_of_what_the_call_covered_runs_to_its_end() -> None:
    prompt = build_extraction_prompt(ExtractionSchemaSpec(fields=with_core([])), "caller: hi")
    assert "names\n  every item through to the end of the call" in prompt


class _SettingRunner:
    model_name = "fake-model"
    reads_setting = True

    def __init__(self) -> None:
        self.settings: list[CallSetting | None] = []

    async def run(
        self,
        spec: ExtractionSchemaSpec,
        transcript: str,
        *,
        setting: CallSetting | None = None,
    ) -> dict[str, Any]:
        self.settings.append(setting)
        return {}


async def test_the_pipeline_tells_the_reading_the_call_direction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _seed_tenant(f"dir_{uuid.uuid4().hex[:10]}")
    snapshot = ExecutionSnapshot(
        engine_call_id=f"dir_{uuid.uuid4().hex[:10]}",
        direction="outbound",
        status="completed",
        raw_status="completed",
        terminal=True,
        billable_ready=True,
        from_e164="+911140000000",
        to_e164="+919000000001",
        started_at=datetime(2026, 11, 23, 17, 49, tzinfo=UTC),
        engine="fake",
        transcript=[
            TranscriptTurn(call_id="c", idx=0, speaker="agent", text="Is the app open?"),
            TranscriptTurn(call_id="c", idx=1, speaker="caller", text="It is open."),
        ],
    )
    call_id = await pipeline._upsert_call(tenant_id, agent_id, snapshot, None)
    spec, _version, agent_id, direction, _d, _n = await pipeline._load_call_context(
        tenant_id, call_id
    )
    runner = _SettingRunner()
    monkeypatch.setattr(extraction_module, "get_extractor", lambda: runner)
    await pipeline._extract_stage(
        tenant_id,
        call_id,
        snapshot,
        spec=spec,
        agent_id=agent_id,
        transcript_text=extractor_transcript(snapshot.transcript),
        opt_out_signal=None,
        business_outcomes=[],
        direction=direction,
        reuse=False,
    )
    assert direction == "outbound"
    assert [s.direction if s else None for s in runner.settings] == ["outbound"]
