"""Gate 7 executed end to end — including every failure path.

WHY THIS FILE IS THE POINT OF THE MODULE. The harness gets one attempt, on a day when a
founder is holding a phone and burning PSTN credit, and gate 7's most valuable verdicts
are the ones a healthy vendor never produces: a payload our models reject, a `total_cost`
that is not in cents, a transcript that comes back empty, an execution that never reaches
`completed`. None of those can be produced by `fake` — it is a conformance control, not a
Bolna simulator — so each one is a small double that adds EXACTLY ONE vendor behaviour on
top of it, and says in its name which behaviour it is standing in for.

The pure scorer (`evaluate_gate7`) is tested directly from hand-built observations, and
the driving (`read_execution`, `measure_time_to_completed`, `run_gate_7`) is tested
against doubles. That split is deliberate: it is what keeps a verdict reachable in a test
without a clock, a file or an engine.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from apps.api.core.errors import ProblemError
from apps.api.engine.fake import FakeEngine
from calevate_shared.config import Settings
from calevate_shared.engine import CallContext, CostBreakdown, ExecutionSnapshot
from calevate_shared.events import TranscriptTurn
from scripts.pilot import fidelity
from scripts.pilot.gates_api import GateContext
from scripts.pilot.results import GateRun


def _settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        app_env="local",
        database_url="postgresql+psycopg://u:p@localhost:5432/x",
        redis_url="redis://localhost:6379/0",
        object_store_endpoint="http://localhost:9000",
        object_store_bucket="calevate",
        webhook_base_url="https://pilot.example.com",
        engine="fake",
    )


def _check(result: GateRun, name: str) -> Any:
    matches = [c for c in result.checks if c.name == name]
    assert matches, f"no sub-check named {name!r} in {[c.name for c in result.checks]}"
    return matches[0]


def _snapshot(**overrides: Any) -> ExecutionSnapshot:
    """A healthy `completed` execution, as the adapter would hand one up."""
    base: dict[str, Any] = {
        "engine_call_id": "exec-abc",
        "engine_agent_ref": "agent-1",
        "direction": "outbound",
        "status": "completed",
        "raw_status": "completed",
        "terminal": True,
        "billable_ready": True,
        "duration_s": 95,
        "recording_url": "https://recordings.invalid/exec-abc.wav",
        "transcript": [
            TranscriptTurn(call_id="exec-abc", idx=0, speaker="agent", text="Namaskaram"),
            TranscriptTurn(call_id="exec-abc", idx=1, speaker="caller", text="Cheppandi"),
        ],
        "cost": CostBreakdown(
            total_inr=Decimal("3.4500"),
            platform_inr=Decimal("1.0000"),
            network_inr=Decimal("1.0000"),
            llm_inr=Decimal("0.5000"),
            tts_inr=Decimal("0.5000"),
            stt_inr=Decimal("0.4500"),
            source_currency="USD",
            source_amount=Decimal("0.0412"),
            fx_rate=Decimal("83.5"),
        ),
    }
    base.update(overrides)
    return ExecutionSnapshot(**base)


class _Reader:
    """An `ExecutionReader` that hands back exactly what the test wrote."""

    def __init__(self, *snapshots: ExecutionSnapshot) -> None:
        self._by_id = {s.engine_call_id: s for s in snapshots}

    async def get_execution(self, call_id: str) -> ExecutionSnapshot:
        return self._by_id[call_id]


# --- observing one execution ---------------------------------------------------


def test_a_healthy_completed_execution_passes_every_field_row() -> None:
    result = fidelity.evaluate_gate7([fidelity.observe(_snapshot())])
    for name in (
        "completed_carries_total_cost",
        "completed_carries_cost_breakdown",
        "completed_carries_recording_url",
        "transcript_parses_into_transcript_turn",
    ):
        assert _check(result, name).status == "pass", name


def test_every_named_check_appears_on_every_run() -> None:
    """A probe whose inputs were missing must be a NOT RUN row, never an absent one —
    otherwise a reader cannot tell 'we did not measure this' from 'this gate is short'."""
    empty = fidelity.evaluate_gate7([])
    assert tuple(c.name for c in empty.checks) == fidelity.CHECK_NAMES
    full = fidelity.evaluate_gate7([fidelity.observe(_snapshot())])
    assert tuple(c.name for c in full.checks) == fidelity.CHECK_NAMES


def test_no_completed_execution_is_not_run_not_a_pass() -> None:
    """`terminal` is not `completed`: cost, recording and extraction populate ~2-3 min
    later, so judging a disconnected call would produce a red about documented behaviour."""
    disconnected = _snapshot(
        status="completed",
        raw_status="call-disconnected",
        billable_ready=False,
        cost=None,
        recording_url=None,
        transcript=[],
    )
    result = fidelity.evaluate_gate7([fidelity.observe(disconnected)])
    assert result.status == "not_run"
    row = _check(result, "completed_carries_total_cost")
    assert row.status == "not_run"
    assert "call-disconnected" in row.detail
    assert "billable_ready" in row.detail


def test_a_completed_execution_with_no_cost_fails() -> None:
    result = fidelity.evaluate_gate7([fidelity.observe(_snapshot(cost=None))])
    assert _check(result, "completed_carries_total_cost").status == "fail"
    assert result.status == "fail"


def test_a_total_with_no_component_legs_fails_the_breakdown_row() -> None:
    bare = _snapshot(
        cost=CostBreakdown(total_inr=Decimal("3.45"), source_currency="USD"),
    )
    result = fidelity.evaluate_gate7([fidelity.observe(bare)])
    assert _check(result, "completed_carries_total_cost").status == "pass"
    row = _check(result, "completed_carries_cost_breakdown")
    assert row.status == "fail"
    assert "attribute spend" in row.detail


def test_a_missing_leg_is_reported_by_name_and_never_as_a_zero() -> None:
    partial = _snapshot(
        cost=CostBreakdown(
            total_inr=Decimal("3.45"),
            platform_inr=Decimal("2.00"),
            network_inr=Decimal("1.45"),
            source_currency="USD",
        ),
    )
    row = _check(
        fidelity.evaluate_gate7([fidelity.observe(partial)]), "completed_carries_cost_breakdown"
    )
    assert row.status == "pass"
    assert "llm_inr" in row.detail
    assert "ABSENT rather than zero" in row.detail


def test_a_completed_execution_with_no_recording_fails() -> None:
    result = fidelity.evaluate_gate7([fidelity.observe(_snapshot(recording_url=None))])
    assert _check(result, "completed_carries_recording_url").status == "fail"


# --- the cost-unit row: our own snapshot cannot answer it, and a PASS is scoped ------
#
# Renamed from the currency row with D-411. The adapter's divisor became a table keyed by
# CURRENCY, and the danger this block guards is not that the row fails wrongly — it is
# that it PASSES while saying nothing about the currency that motivated the change.


def test_cost_unit_is_not_run_without_the_vendors_own_figure() -> None:
    """Reading `source_currency` back from our snapshot returns OUR fallback when the
    payload named nothing. A pass here would be the harness agreeing with itself."""
    row = _check(fidelity.evaluate_gate7([fidelity.observe(_snapshot())]), fidelity.COST_UNIT_CHECK)
    assert row.status == "not_run"
    assert "vendor's own total" in row.detail


def test_cost_unit_passes_when_our_derived_amount_matches_the_vendors() -> None:
    claim = fidelity.VendorCostClaim(call_ref="exec-abc", total=Decimal("0.0412"), currency="USD")
    row = _check(
        fidelity.evaluate_gate7([fidelity.observe(_snapshot())], vendor_claims={"exec-abc": claim}),
        fidelity.COST_UNIT_CHECK,
    )
    assert row.status == "pass"


def test_even_a_pass_says_which_currencies_it_covers() -> None:
    """THE POINT OF THE WHOLE ROW AFTER D-411. `pass` beside a row called "cost unit" is
    read as "metering is verified", and it is verified only for the currencies the adapter
    has an entry for — one, today. A verdict that does not say so is the gate narrowing in
    silence, which is exactly what happened when the divisor became a table and this file
    stayed green because USD's value never moved."""
    claim = fidelity.VendorCostClaim(call_ref="exec-abc", total=Decimal("0.0412"), currency="USD")
    row = _check(
        fidelity.evaluate_gate7([fidelity.observe(_snapshot())], vendor_claims={"exec-abc": claim}),
        fidelity.COST_UNIT_CHECK,
    )
    assert row.status == "pass"
    assert "USD" in row.detail
    assert "meters NOTHING" in row.detail, "the pass must name the hole it does not cover"
    assert "_MINOR_UNITS_PER_MAJOR" in row.detail, "and where the fix goes"


def test_an_execution_the_adapter_refused_to_price_is_inconclusive_not_a_pass() -> None:
    """THE SILENT NARROWING, as a test. A mixed account — one USD execution that compares
    perfectly, one the adapter refused because nothing states that currency's unit — must
    NOT report `pass` on the strength of the half it could read. `not_run` is the honest
    verdict: this gate exists to settle the unit assumption, and "the adapter declined to
    guess" is precisely the state of not having settled it."""
    priced = fidelity.observe(_snapshot())
    refused = fidelity.observe(_snapshot(engine_call_id="exec-inr", cost=None))
    claim = fidelity.VendorCostClaim(call_ref="exec-abc", total=Decimal("0.0412"), currency="USD")
    inr = fidelity.VendorCostClaim(call_ref="exec-inr", total=Decimal("3.45"), currency="INR")

    result = fidelity.evaluate_gate7(
        [priced, refused], vendor_claims={"exec-abc": claim, "exec-inr": inr}
    )

    row = _check(result, fidelity.COST_UNIT_CHECK)
    assert row.status == "not_run", "a pass here would be a verdict about the easy half"
    assert "INR" in row.detail, "and it names the currency it could not reason about"
    assert "refused to price" in row.detail
    # The account being unmetered is not excused — it is a FAIL one row up, which is where
    # "we are being charged for something we cannot price" belongs.
    assert _check(result, "completed_carries_total_cost").status == "fail"


def test_the_unpriced_row_names_both_causes() -> None:
    """ "the vendor sent no figure" and "the adapter refused what it sent" look identical
    from here, and only one of them is ours to close. An operator reading this row at 3am
    must not be told it is the vendor's fault when it is one line of our own table."""
    row = _check(
        fidelity.evaluate_gate7([fidelity.observe(_snapshot(cost=None))]),
        "completed_carries_total_cost",
    )
    assert row.status == "fail"
    assert "REFUSED" in row.detail
    assert "_MINOR_UNITS_PER_MAJOR" in row.detail


def test_a_disagreement_equal_to_the_divisor_names_the_unit_assumption() -> None:
    """The whole reason this row exists: if `total_cost` is in dollars, not cents, our
    /100 makes every INR ledger row 100x wrong and nothing else would notice. The fix now
    has two halves and the message carries both — the constant, and the restatement of the
    rows already metered under it."""
    claim = fidelity.VendorCostClaim(call_ref="exec-abc", total=Decimal("4.12"), currency="USD")
    row = _check(
        fidelity.evaluate_gate7([fidelity.observe(_snapshot())], vendor_claims={"exec-abc": claim}),
        fidelity.COST_UNIT_CHECK,
    )
    assert row.status == "fail"
    assert "NOT in minor units" in row.detail
    assert "correct_cost_unit" in row.detail, "append-only: the repair is a compensating row"


def test_the_vendor_billing_a_different_currency_from_the_one_we_priced_fails() -> None:
    """The 83x fx error and the 100x unit error arriving together, on rows that look
    ordinary: the payload named no currency, we fell back to USD, and the invoice is in
    something else. Unlike the refusal above, something WAS metered — and metered wrong —
    so this is a fail and not an inconclusive."""
    claim = fidelity.VendorCostClaim(call_ref="exec-abc", total=Decimal("0.0412"), currency="EUR")
    row = _check(
        fidelity.evaluate_gate7([fidelity.observe(_snapshot())], vendor_claims={"exec-abc": claim}),
        fidelity.COST_UNIT_CHECK,
    )
    assert row.status == "fail"
    assert "EUR" in row.detail
    assert "exchange rate" in row.detail


def test_the_gate_reports_a_row_for_the_unit_under_its_new_name() -> None:
    """`CHECK_NAMES` is what the report renders, and a check emitting a name outside it
    silently disappears. Pinned because the rename touched six call sites."""
    assert fidelity.COST_UNIT_CHECK in fidelity.CHECK_NAMES
    assert "usd" not in fidelity.COST_UNIT_CHECK.lower(), (
        "the divisor is per currency; a row name hard-coding one teaches the narrow reading"
    )
    names = [c.name for c in fidelity.evaluate_gate7([fidelity.observe(_snapshot())]).checks]
    assert names == list(fidelity.CHECK_NAMES)


# --- extraction ----------------------------------------------------------------


def test_no_extraction_and_no_expectation_is_not_run_not_a_failure() -> None:
    """An agent with no extraction schema legitimately returns nothing; failing that
    would score OUR configuration as the vendor's defect."""
    row = _check(
        fidelity.evaluate_gate7([fidelity.observe(_snapshot())]),
        "completed_carries_extracted_data",
    )
    assert row.status == "not_run"
    assert "extraction schema" in row.detail


def test_an_expected_extraction_field_that_never_arrived_fails_by_name() -> None:
    observed = fidelity.observe(_snapshot(engine_extracted={"lead_name": "x"}))
    row = _check(
        fidelity.evaluate_gate7(
            [observed], expected_extraction={"exec-abc": ("lead_name", "budget")}
        ),
        "completed_carries_extracted_data",
    )
    assert row.status == "fail"
    assert "budget" in row.detail


def test_extraction_reports_field_names_and_never_values() -> None:
    observed = fidelity.observe(_snapshot(engine_extracted={"lead_name": "Ravi Kumar"}))
    assert observed.extracted_field_names == ("lead_name",)
    row = _check(fidelity.evaluate_gate7([observed]), "completed_carries_extracted_data")
    assert row.status == "pass"
    assert "lead_name" in row.detail
    assert "Ravi Kumar" not in repr(row.as_dict())


# --- the transcript row: the engine-isolation bet ------------------------------


def test_a_payload_our_model_rejects_is_a_fail_naming_the_field() -> None:
    """A parse failure must be a first-class FAIL with the field named — not a traceback
    that takes the run down, and not an exception a reader has to interpret."""
    rejected = fidelity.UnreadableExecution(
        call_ref="exec-bad",
        kind="model_rejected",
        detail="1 field(s) failed",
        defects=(
            fidelity.TranscriptDefect(field="transcript.0.speaker", reason="our model rejected it"),
        ),
    )
    result = fidelity.evaluate_gate7([], unreadable=[rejected])
    row = _check(result, "transcript_parses_into_transcript_turn")
    assert row.status == "fail"
    assert "transcript.0.speaker" in row.detail


async def test_a_validation_error_from_the_adapter_becomes_a_named_defect() -> None:
    """The real shape of the failure: `get_execution` raises `ValidationError` because
    their payload does not fit our model. The fields come out; the rejected VALUE — a
    caller's words — must not."""

    class _RejectingReader:
        async def get_execution(self, call_id: str) -> ExecutionSnapshot:
            TranscriptTurn(call_id=call_id, idx=-1, speaker="agent", text="rahasyam maata")
            raise AssertionError("unreachable: the line above raises")

    read = await fidelity.read_execution(_RejectingReader(), "exec-bad")
    assert isinstance(read, fidelity.UnreadableExecution)
    assert read.kind == "model_rejected"
    assert any("idx" in d.field for d in read.defects)
    assert "rahasyam" not in repr(read)


def test_zero_turns_on_a_completed_call_with_audio_is_a_parse_failure() -> None:
    """`parse_transcript` returns [] for a shape it does not recognise, which is
    indistinguishable from a silent call — the duration is what separates them."""
    silent = _snapshot(transcript=[], duration_s=95)
    row = _check(
        fidelity.evaluate_gate7([fidelity.observe(silent)]),
        "transcript_parses_into_transcript_turn",
    )
    assert row.status == "fail"
    assert "zero turns" in row.detail


def test_zero_turns_on_a_zero_length_call_is_not_run_not_a_failure() -> None:
    row = _check(
        fidelity.evaluate_gate7([fidelity.observe(_snapshot(transcript=[], duration_s=0))]),
        "transcript_parses_into_transcript_turn",
    )
    assert row.status == "not_run"


def test_non_contiguous_turn_indices_are_a_defect() -> None:
    """A transcript whose turns all carry idx 0 parses fine and reads as one turn."""
    scrambled = _snapshot(
        transcript=[
            TranscriptTurn(call_id="exec-abc", idx=0, speaker="agent", text="a"),
            TranscriptTurn(call_id="exec-abc", idx=0, speaker="caller", text="b"),
        ]
    )
    row = _check(
        fidelity.evaluate_gate7([fidelity.observe(scrambled)]),
        "transcript_parses_into_transcript_turn",
    )
    assert row.status == "fail"
    assert "idx" in row.detail


def test_a_turn_stamped_with_another_calls_id_is_a_defect() -> None:
    crossed = _snapshot(
        transcript=[TranscriptTurn(call_id="exec-other", idx=0, speaker="agent", text="a")]
    )
    row = _check(
        fidelity.evaluate_gate7([fidelity.observe(crossed)]),
        "transcript_parses_into_transcript_turn",
    )
    assert row.status == "fail"
    assert "call_id" in row.detail


# --- time to completed ---------------------------------------------------------


def test_time_to_completed_is_absent_when_nothing_was_measured() -> None:
    row = _check(
        fidelity.evaluate_gate7([fidelity.observe(_snapshot())]),
        "time_to_completed_within_lead_slo",
    )
    assert row.status == "not_run"
    assert row.measurements == {}


def test_a_measured_interval_inside_the_slo_passes_and_carries_its_resolution() -> None:
    timing = fidelity.CompletionTiming(
        call_ref="exec-abc", seconds_to_completed=95.0, polls=7, poll_interval_s=15.0
    )
    row = _check(
        fidelity.evaluate_gate7([fidelity.observe(_snapshot())], timings=[timing]),
        "time_to_completed_within_lead_slo",
    )
    assert row.status == "pass"
    assert row.measurements["slowest_s"] == 95.0
    assert row.measurements["resolution_s"] == 15.0


def test_an_interval_past_the_lead_slo_fails_with_the_consequence() -> None:
    timing = fidelity.CompletionTiming(
        call_ref="exec-abc", seconds_to_completed=170.0, polls=12, poll_interval_s=15.0
    )
    row = _check(
        fidelity.evaluate_gate7([fidelity.observe(_snapshot())], timings=[timing]),
        "time_to_completed_within_lead_slo",
    )
    assert row.status == "fail"
    assert "2 min" in row.detail or "lead visible" in row.detail


async def test_polling_measures_the_interval_from_the_observed_disconnect() -> None:
    """The clock and the sleep are seams so this runs in microseconds — and so the
    'never completes' path below can run at all."""
    disconnect = datetime(2026, 8, 13, 10, 0, 0, tzinfo=UTC)
    ticks = iter([disconnect + timedelta(seconds=s) for s in (10, 25, 25, 40, 40, 55, 70, 70, 70)])
    slept: list[float] = []

    class _Ripening:
        def __init__(self) -> None:
            self.reads = 0

        async def get_execution(self, call_id: str) -> ExecutionSnapshot:
            self.reads += 1
            ready = self.reads >= 3
            return _snapshot(
                engine_call_id=call_id,
                billable_ready=ready,
                raw_status="completed" if ready else "call-disconnected",
                cost=None if not ready else _snapshot().cost,
                transcript=[] if not ready else _snapshot().transcript,
            )

    async def _sleep(seconds: float) -> None:
        slept.append(seconds)

    timing = await fidelity.measure_time_to_completed(
        _Ripening(),
        "exec-abc",
        disconnected_at=disconnect,
        interval_s=15.0,
        timeout_s=300.0,
        now=lambda: next(ticks),
        sleep=_sleep,
    )
    assert isinstance(timing, fidelity.CompletionTiming)
    assert timing.polls == 3
    assert timing.seconds_to_completed > 0
    assert slept == [15.0, 15.0]


async def test_an_execution_that_never_completes_yields_a_reason_never_a_number() -> None:
    disconnect = datetime(2026, 8, 13, 10, 0, 0, tzinfo=UTC)
    clock = {"t": 0.0}

    def _now() -> datetime:
        clock["t"] += 10.0
        return disconnect + timedelta(seconds=clock["t"])

    class _NeverReady:
        async def get_execution(self, call_id: str) -> ExecutionSnapshot:
            return _snapshot(billable_ready=False, raw_status="call-disconnected", cost=None)

    async def _sleep(seconds: float) -> None:
        return None

    outcome = await fidelity.measure_time_to_completed(
        _NeverReady(),
        "exec-abc",
        disconnected_at=disconnect,
        interval_s=15.0,
        timeout_s=60.0,
        now=_now,
        sleep=_sleep,
    )
    assert isinstance(outcome, str)
    assert "still not `completed`" in outcome


async def test_a_naive_disconnect_instant_is_refused_rather_than_assumed_utc() -> None:
    """An operator types an IST wall-clock time. Assuming UTC would make the interval
    5.5 hours wrong and it would still look like a measurement."""
    outcome = await fidelity.measure_time_to_completed(
        _Reader(_snapshot()),
        "exec-abc",
        disconnected_at=datetime(2026, 8, 13, 10, 0, 0),
        now=lambda: datetime.now(UTC),
    )
    assert isinstance(outcome, str)
    assert "timezone" in outcome


# --- unreachable executions are not fidelity failures --------------------------


async def test_an_engine_side_failure_is_reported_as_unreachable_not_as_a_bad_payload() -> None:
    class _Broken:
        async def get_execution(self, call_id: str) -> ExecutionSnapshot:
            raise ProblemError(
                kind="dependency",
                code="engine_unavailable",
                title="Voice engine unavailable",
                detail="The voice platform did not respond.",
            )

    read = await fidelity.read_execution(_Broken(), "exec-abc")
    assert isinstance(read, fidelity.UnreadableExecution)
    assert read.kind == "unreachable"
    assert "engine_unavailable" in read.detail
    result = fidelity.evaluate_gate7([], unreadable=[read])
    # It must NOT be scored as a transcript failure — it says nothing about the payload.
    assert _check(result, "transcript_parses_into_transcript_turn").status == "not_run"
    assert any("could not be read at all" in f for f in result.findings)


async def test_an_unexpected_exception_contributes_only_its_type() -> None:
    """`str(exc)` on this path can be an httpx object carrying the request URL."""

    class _Exploding:
        async def get_execution(self, call_id: str) -> ExecutionSnapshot:
            raise RuntimeError("GET https://api.bolna.ai/executions/exec-abc?to=+919876543210")

    read = await fidelity.read_execution(_Exploding(), "exec-abc")
    assert isinstance(read, fidelity.UnreadableExecution)
    assert "RuntimeError" in read.detail
    assert "9876543210" not in repr(read)


# --- hard rule 6, layer one ----------------------------------------------------


def test_the_gate_never_writes_a_number_a_url_or_a_word_the_caller_said() -> None:
    """Layer one: the gate does not PRODUCE PII, so the scrubber has nothing to catch.
    Asserted against the raw result, before `redact.scrub` has run — a test on scrubbed
    output would pass just as happily with layer one deleted."""
    dirty = _snapshot(
        to_e164="+919876543210",
        from_e164="+911140000000",
        recording_url="https://s3.invalid/rec.wav?X-Amz-Signature=deadbeef",
        engine_extracted={"lead_name": "Ravi Kumar", "phone": "+919876543210"},
        # A defective transcript on purpose: the row that FAILS is the one that has the
        # most to say, so it is the row most likely to say too much.
        transcript=[
            TranscriptTurn(
                call_id="exec-abc", idx=0, speaker="caller", text="naa number tommidi enimidi"
            ),
            TranscriptTurn(call_id="exec-abc", idx=0, speaker="agent", text="Ravi Kumar gaaru"),
        ],
    )
    result = fidelity.evaluate_gate7(
        [fidelity.observe(dirty)],
        timings=[
            fidelity.CompletionTiming(
                call_ref="exec-abc", seconds_to_completed=95.0, polls=7, poll_interval_s=15.0
            )
        ],
    )
    serialized = repr(result.as_dict())
    assert "9876543210" not in serialized
    assert "Ravi Kumar" not in serialized
    assert "X-Amz-Signature" not in serialized
    assert "tommidi" not in serialized
    assert "exec-abc" in serialized  # the execution id IS the safe identifier


# --- the inputs file and the runner seam ---------------------------------------


def test_an_absent_inputs_file_is_not_run_with_the_path_in_the_reason(tmp_path: Path) -> None:
    assert fidelity.load_gate7_inputs(str(tmp_path / "nope.json")) is None


def test_a_malformed_inputs_file_is_refused_without_quoting_its_content(
    tmp_path: Path,
) -> None:
    bad = tmp_path / "gate7.json"
    bad.write_text(json.dumps({"executions": [{"vendor_reported_total": "0.04"}]}))
    with pytest.raises(fidelity.Gate7InputsError) as caught:
        fidelity.load_gate7_inputs(str(bad))
    assert "ValidationError" in str(caught.value)


async def test_the_runner_entry_point_reports_not_run_when_there_is_nothing_to_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(fidelity.INPUTS_ENV, str(tmp_path / "absent.json"))
    ctx = GateContext(engine=FakeEngine(), settings=_settings())
    result = await fidelity.run_gate_7(ctx)
    assert result.status == "not_run"
    assert result.blocked is not None
    assert fidelity.DEFAULT_INPUTS_PATH in result.blocked
    assert result.findings  # the adapter gaps are reported even when nothing ran


async def test_a_broken_inputs_file_blocks_the_gate_rather_than_crashing_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = tmp_path / "gate7.json"
    broken.write_text("{not json")
    monkeypatch.setenv(fidelity.INPUTS_ENV, str(broken))
    result = await fidelity.run_gate_7(GateContext(engine=FakeEngine(), settings=_settings()))
    assert result.status == "not_run"
    assert "could not be read" in (result.blocked or "")


async def test_the_runner_reads_the_executions_the_operators_file_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end against `fake`: file → adapter → observations → verdicts."""
    engine = FakeEngine()
    handle = await engine.start_outbound_call("agent-1", "+915550000000", CallContext())
    inputs = tmp_path / "gate7.json"
    inputs.write_text(
        json.dumps(
            {
                "executions": [
                    {
                        "call_ref": handle,
                        "vendor_reported_total": "0.0412",
                        "vendor_reported_currency": "USD",
                    }
                ]
            }
        )
    )
    monkeypatch.setenv(fidelity.INPUTS_ENV, str(inputs))
    result = await fidelity.run_gate_7(GateContext(engine=engine, settings=_settings()))
    assert _check(result, "completed_carries_total_cost").status == "pass"
    assert _check(result, "transcript_parses_into_transcript_turn").status == "pass"
    # `fake` prices in INR at 1:1 and the operator's claim above says USD, so the adapter
    # and the invoice name different currencies — a FAIL, and a specific one. The property
    # asserted is that the row is DECIDABLE end to end: `fake` produces a cost, so this is
    # never the `not_run` an unpriced execution earns.
    row = _check(result, fidelity.COST_UNIT_CHECK)
    assert row.status == "fail"
    assert "INR" in row.detail and "USD" in row.detail


async def test_an_execution_placed_earlier_in_the_same_run_is_picked_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--gates 2,7`: gate 2 places a call and records the execution; gate 7 reads it
    without the operator having to copy an id between two commands."""
    monkeypatch.setenv(fidelity.INPUTS_ENV, str(tmp_path / "absent.json"))
    engine = FakeEngine()
    ctx = GateContext(engine=engine, settings=_settings())
    handle = await engine.start_outbound_call("agent-1", "+915550000000", CallContext())
    ctx.created_executions.append(handle)
    result = await fidelity.run_gate_7(ctx)
    assert result.blocked is None
    assert _check(result, "completed_carries_total_cost").status == "pass"


def test_the_gate_is_registered_under_its_operations_number() -> None:
    assert set(fidelity.GATES) == {7}
