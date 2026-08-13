"""Gate 4's harness, exercised end to end (OPERATIONS §2 gate 4, TRD §4).

The harness gets ONE chance, on a day when a founder is on a phone with a stopwatch and
cannot debug it, so every path that matters runs here: a detected DISAGREEMENT between
vendor-reported and measured latency, a sample too small to support a percentile, a run
with no samples at all, and the redaction that keeps recognised caller speech out of a
committed artefact.

Fixtures deliberately carry SPREAD. A percentile assertion over identical samples is the
trap this repo keeps walking into: every statistic collapses to the same number, so
breaking the statistic changes nothing and the test passes over the corpse of the code
it was guarding.
"""

from __future__ import annotations

import json

import pytest
from scripts.pilot.latency import (
    PASSING_VERDICTS,
    REPORT_PRECISION_MS,
    TARGET_TAIL_MS,
    GreetingSample,
    TurnLatencySample,
    clopper_pearson_lower,
    clopper_pearson_upper,
    compare_turn_latency,
    evaluate_gate4,
    evaluate_tail,
    gate4_from_disk,
    median_confidence_interval,
    parse_latency_data,
    redact_latency_data,
    render_gate4_markdown,
    samples_needed_to_confirm,
    summarize_samples,
    unredacted_text_paths,
)

# The recognised text a real payload carries. It is the caller's words: if any of it
# reaches a result object or the rendered scorecard, hard rules 5 and 6 are broken.
CALLER_SPEECH = "hello who is there"

RAW_LATENCY_DATA = {
    "stream_id": "stream-abc",
    "time_to_first_audio": 980,
    "region": "ap-south-1",
    "transcriber": {
        "time_to_connect": 226,
        "turns": [
            {
                "turn": 1,
                "turn_latency": [
                    {"sequence_id": 1, "audio_to_text_latency": 240.5, "text": CALLER_SPEECH},
                    {"sequence_id": 2, "audio_to_text_latency": 260.0, "text": "hello who is this"},
                ],
            },
            {
                "turn": 2,
                "turn_latency": [
                    {"sequence_id": 1, "audio_to_text_latency": 300.0, "text": "book cheyandi"}
                ],
            },
        ],
    },
    "llm": {
        "time_to_connect": 120,
        "turns": [
            {"turn": 1, "time_to_first_token": 320, "time_to_last_token": 700},
            {"turn": 2, "time_to_first_token": 340, "time_to_last_token": 720},
        ],
    },
    "synthesizer": {
        "time_to_connect": 271,
        "turns": [
            {"turn": 1, "time_to_first_token": 290, "time_to_last_token": 800},
            {"turn": 2, "time_to_first_token": 310, "time_to_last_token": 810},
        ],
    },
}

# Ten voice-to-voice samples with real spread, all under the 1.8s tail threshold but
# straddling the 1.1s p50 target.
CLEAN_TEN = [900, 950, 1000, 1010, 1050, 1100, 1150, 1200, 1300, 1600]

# Ten comfortably fast samples: the whole median interval (x(2)..x(9)) sits under 1.1s,
# which is what a p50 PASS actually requires. Still spread, so a broken statistic moves.
FAST_TEN = [600, 650, 700, 720, 750, 800, 850, 900, 950, 1050]


def _samples(values: list[int], call_ref: str = "pilot-01") -> list[TurnLatencySample]:
    return [
        TurnLatencySample(
            call_ref=call_ref, turn_index=i + 1, voice_to_voice_ms=v, method="stopwatch_human"
        )
        for i, v in enumerate(values)
    ]


# --- the payload carries caller speech; nothing here may keep it ----------------


def test_parse_keeps_timings_and_never_carries_recognised_text():
    parsed = parse_latency_data(RAW_LATENCY_DATA, call_ref="pilot-01")

    assert parsed.time_to_first_audio_ms == 980
    assert parsed.region == "ap-south-1"
    turn1 = parsed.turns_by_index[1]
    # The LAST sequence is the one the orchestrator acted on.
    assert turn1.transcriber_ms == 260.0
    assert turn1.llm_ttft_ms == 320
    assert turn1.tts_ttft_ms == 290
    assert turn1.component_sum_ms == 870.0

    blob = parsed.model_dump_json()
    assert CALLER_SPEECH not in blob
    assert "book cheyandi" not in blob


def test_redaction_preserves_shape_and_removes_every_utterance():
    redacted = redact_latency_data(RAW_LATENCY_DATA)

    # Shape survives — the fixture's whole purpose is the shape.
    seq = redacted["transcriber"]["turns"][0]["turn_latency"][0]
    assert seq["sequence_id"] == 1
    assert seq["audio_to_text_latency"] == 240.5
    assert seq["text"] == f"<redacted len={len(CALLER_SPEECH)}>"

    assert unredacted_text_paths(RAW_LATENCY_DATA), "the raw payload must trip the checker"
    assert unredacted_text_paths(redacted) == []


def test_a_phone_shaped_digit_run_anywhere_in_the_payload_is_scrubbed():
    # Not documented to appear in latency_data — which is exactly the kind of assumption
    # D-31/D-32 exist to forbid.
    payload = {"stream_id": "call from 9876543210", "time_to_first_audio": 900}
    assert unredacted_text_paths(payload) == ["$.stream_id"]
    redacted = redact_latency_data(payload)
    assert "9876543210" not in str(redacted)
    assert unredacted_text_paths(redacted) == []


def test_the_rendered_scorecard_block_holds_no_caller_speech():
    vendor = {"pilot-01": parse_latency_data(RAW_LATENCY_DATA, call_ref="pilot-01")}
    result = evaluate_gate4(_samples(CLEAN_TEN), [], vendor)
    rendered = render_gate4_markdown(result)
    assert CALLER_SPEECH not in rendered
    assert "book cheyandi" not in rendered


# --- absent is absent, never zero ---------------------------------------------


def test_a_turn_missing_one_component_yields_no_vendor_sum_and_no_comparison():
    raw = {
        "llm": {"turns": [{"turn": 1, "time_to_first_token": 320}]},
        "synthesizer": {"turns": [{"turn": 1, "time_to_first_token": 290}]},
        # transcriber block absent entirely
    }
    parsed = parse_latency_data(raw, call_ref="pilot-02")
    turn = parsed.turns_by_index[1]
    assert turn.transcriber_ms is None
    assert turn.component_sum_ms is None, "a two-of-three sum is a different quantity"
    assert any("transcriber" in w for w in parsed.warnings)

    finding = compare_turn_latency(_samples([1000], call_ref="pilot-02"), {"pilot-02": parsed})
    assert finding.verdict == "not_comparable"


# --- vendor vs stopwatch: both answers are results -----------------------------


def test_agreement_is_reported_when_the_vendor_sum_lands_inside_the_stopwatch_tolerance():
    vendor = {"pilot-01": parse_latency_data(RAW_LATENCY_DATA, call_ref="pilot-01")}
    # turn 1 vendor sum = 870ms; a stopwatch reading 1,000ms is 130ms away, inside the
    # 250ms human-reaction tolerance.
    samples = [
        TurnLatencySample(
            call_ref="pilot-01", turn_index=1, voice_to_voice_ms=1000, method="stopwatch_human"
        ),
        TurnLatencySample(
            call_ref="pilot-01", turn_index=2, voice_to_voice_ms=1100, method="stopwatch_human"
        ),
    ]
    finding = compare_turn_latency(samples, vendor)
    assert finding.verdict == "agrees"
    assert len(finding.comparisons) == 2


def test_disagreement_is_detected_and_carries_the_signed_bias():
    vendor = {"pilot-01": parse_latency_data(RAW_LATENCY_DATA, call_ref="pilot-01")}
    # The interesting real-world failure: the vendor reports itself far faster than the
    # caller experienced (its components do not span the whole voice-to-voice interval).
    samples = [
        TurnLatencySample(
            call_ref="pilot-01", turn_index=1, voice_to_voice_ms=1800, method="stopwatch_human"
        ),
        TurnLatencySample(
            call_ref="pilot-01", turn_index=2, voice_to_voice_ms=1900, method="stopwatch_human"
        ),
    ]
    finding = compare_turn_latency(samples, vendor)
    assert finding.verdict == "disagrees"
    assert finding.median_delta_ms is not None and finding.median_delta_ms < 0
    assert not all(c.agrees for c in finding.comparisons)


def test_recording_analysis_is_held_to_a_tighter_tolerance_than_a_human_stopwatch():
    vendor = {"pilot-01": parse_latency_data(RAW_LATENCY_DATA, call_ref="pilot-01")}
    # 1,040ms against a 870ms vendor sum: 170ms off — inside the human tolerance (250),
    # outside the recording tolerance (100).
    human = TurnLatencySample(
        call_ref="pilot-01", turn_index=1, voice_to_voice_ms=1040, method="stopwatch_human"
    )
    recorded = human.model_copy(update={"method": "recording_analysis"})
    assert compare_turn_latency([human], vendor).verdict == "agrees"
    assert compare_turn_latency([recorded], vendor).verdict == "disagrees"


def test_greeting_delay_is_compared_against_time_to_first_audio_separately():
    vendor = {"pilot-01": parse_latency_data(RAW_LATENCY_DATA, call_ref="pilot-01")}
    result = evaluate_gate4(
        _samples(CLEAN_TEN),
        [GreetingSample(call_ref="pilot-01", greeting_delay_ms=1000, method="stopwatch_human")],
        vendor,
    )
    assert result.greeting_agreement.verdict == "agrees"  # |980 - 1000| = 20ms
    # And the cold-start number never entered the turn distribution.
    assert result.turn_summary.n == len(CLEAN_TEN)
    assert result.greeting_summary.n == 1


# --- statistics ----------------------------------------------------------------


def test_the_median_interval_is_the_tightest_order_statistic_pair_reaching_95_percent():
    interval = median_confidence_interval(sorted(CLEAN_TEN))
    assert interval is not None
    assert (interval.low_order_stat, interval.high_order_stat) == (2, 9)
    assert interval.low_ms == 950 and interval.high_ms == 1300
    assert interval.coverage == pytest.approx(0.9785, abs=1e-3)


def test_too_few_samples_gets_no_interval_at_all_rather_than_a_shaky_one():
    assert median_confidence_interval([900, 1000, 1100, 1200, 1300]) is None
    summary = summarize_samples([900, 1000, 1100, 1200, 1300])
    assert summary.basis == "insufficient_samples"
    assert summary.median_ci is None


def test_ten_clean_samples_cannot_confirm_the_p95_leg_and_say_so():
    finding = evaluate_tail(CLEAN_TEN, threshold_ms=TARGET_TAIL_MS)
    assert finding.exceedances == 0
    assert finding.verdict == "INCONCLUSIVE"
    assert finding.verdict not in PASSING_VERDICTS
    # 95% upper bound on the true exceedance rate from ten clean samples is ~25.9%,
    # five times the 5% the target allows.
    assert finding.exceedance_upper_95 == pytest.approx(0.2589, abs=1e-3)
    assert finding.samples_needed_to_confirm == 59


def test_the_p95_leg_can_still_be_refuted_by_ten_calls():
    # Three of ten over 1.8s puts the 95% LOWER bound on the exceedance rate at 8.7%,
    # above the 5% the target allows — beaten on its own terms.
    values = [900, 950, 1000, 1100, 1200, 1300, 1750, 1900, 2400, 3000]
    finding = evaluate_tail(values, threshold_ms=TARGET_TAIL_MS)
    assert finding.exceedances == 3
    assert finding.exceedance_lower_95 == pytest.approx(0.0873, abs=1e-3)
    assert finding.verdict == "FAIL"


def test_two_exceedances_in_ten_is_neither_pass_nor_fail():
    values = [900, 950, 1000, 1100, 1200, 1300, 1400, 1750, 1900, 2400]
    finding = evaluate_tail(values, threshold_ms=TARGET_TAIL_MS)
    assert finding.exceedances == 2
    assert finding.verdict == "INCONCLUSIVE"


def test_a_confirmable_tail_needs_the_sample_size_the_module_names():
    n = samples_needed_to_confirm()
    assert n == 59
    assert clopper_pearson_upper(0, n) <= 0.05
    assert clopper_pearson_upper(0, n - 1) > 0.05
    # And with that many clean samples the leg genuinely passes.
    assert evaluate_tail([1000] * n, threshold_ms=TARGET_TAIL_MS).verdict == "PASS"


def test_bounds_are_exact_rather_than_normal_approximations():
    # The normal approximation at k=0 gives [0, 0] — certainty from ten calls.
    assert clopper_pearson_lower(0, 10) == 0.0
    assert clopper_pearson_upper(0, 10) > 0.25
    assert clopper_pearson_upper(10, 10) == 1.0


def test_nothing_is_printed_finer_than_the_stated_precision():
    summary = summarize_samples([903, 947, 1004, 1013, 1051, 1102, 1149, 1207, 1298, 1603])
    values = [summary.median_ms, summary.min_ms, summary.max_ms]
    assert summary.median_ci is not None
    values += [summary.median_ci.low_ms, summary.median_ci.high_ms]
    for value in values:
        assert value is not None and value % REPORT_PRECISION_MS == 0


# --- the gate's verdict --------------------------------------------------------


def test_a_gate_that_never_ran_is_never_a_pass():
    result = evaluate_gate4([], [], {})
    assert result.verdict == "NOT RUN"
    assert not result.passed
    assert result.turn_summary.basis == "not_run"
    assert result.tail.verdict == "NOT RUN"
    rendered = render_gate4_markdown(result)
    assert "VERDICT: NOT RUN" in rendered
    assert "PASS" not in rendered.split("###")[0]


def test_ten_fast_calls_pass_the_median_leg_and_still_land_inconclusive_overall():
    result = evaluate_gate4(_samples(FAST_TEN))
    assert result.median_verdict == "PASS"  # the whole median interval is under 1.1s
    assert result.tail.verdict == "INCONCLUSIVE"
    assert result.verdict == "INCONCLUSIVE"
    assert not result.passed


def test_a_median_interval_straddling_the_target_confirms_nothing():
    # CLEAN_TEN's median is 1,075ms — under target — but its 97.9% interval runs to
    # 1,300ms. A point median compared to the threshold would call this a pass.
    result = evaluate_gate4(_samples(CLEAN_TEN))
    assert result.turn_summary.median_ms is not None
    assert result.turn_summary.median_ms < 1100
    assert result.median_verdict == "INCONCLUSIVE"
    assert not result.passed


def test_a_refuted_tail_fails_the_whole_gate():
    values = [900, 950, 1000, 1100, 1200, 1300, 1750, 1900, 2400, 3000]
    result = evaluate_gate4(_samples(values))
    assert result.verdict == "FAIL"
    assert not result.passed


def test_a_slow_median_fails_the_median_leg():
    values = [1900, 1950, 2000, 2100, 2200, 2300, 2400, 2500, 2600, 2700]
    result = evaluate_gate4(_samples(values), target_tail_ms=100_000)
    assert result.median_verdict == "FAIL"
    assert result.verdict == "FAIL"


def test_the_report_states_the_provenance_of_every_number_before_the_numbers():
    result = evaluate_gate4(_samples(CLEAN_TEN))
    rendered = render_gate4_markdown(result)
    provenance = rendered.index("NOT measurable")
    assert provenance < rendered.index("median")
    assert "stopwatch_human=10" in rendered


# --- wiring into the shared harness --------------------------------------------


def test_a_missing_observations_file_blocks_the_gate_rather_than_scoring_it(tmp_path):
    result = gate4_from_disk(str(tmp_path / "absent.json"))
    assert result.status == "not_run"
    assert result.blocked is not None and "no observations file" in result.blocked


def test_an_unreadable_observations_file_blocks_without_quoting_its_contents(tmp_path):
    path = tmp_path / "obs.json"
    path.write_text('{"calls": [{"call_ref": "exec-1", "turns": "+919876543210"}]}')
    result = gate4_from_disk(str(path))
    assert result.status == "not_run"
    assert result.blocked is not None
    assert "9876543210" not in result.blocked


def test_a_full_ledger_scores_into_the_shared_vocabulary_and_never_reads_as_passed(tmp_path):
    path = tmp_path / "obs.json"
    path.write_text(
        json.dumps(
            {
                "calls": [
                    {
                        "call_ref": "exec-1",
                        "greeting_delay_ms": 1000,
                        "turns": [
                            {"turn_index": i + 1, "voice_to_voice_ms": v}
                            for i, v in enumerate(FAST_TEN)
                        ],
                        "latency_data": RAW_LATENCY_DATA,
                    }
                ]
            }
        )
    )
    result = gate4_from_disk(str(path))
    by_name = {c.name: c for c in result.checks}
    assert by_name["voice_to_voice_p50"].status == "pass"
    # The tail leg cannot be confirmed at n=10, so the pessimistic roll-up keeps the
    # whole gate out of green — which is the point of mapping INCONCLUSIVE to not_run.
    assert by_name["voice_to_voice_tail"].status == "not_run"
    assert result.status == "not_run"
    assert by_name["vendor_latency_vs_stopwatch_compared"].status == "pass"
    blob = json.dumps(result.as_dict())
    assert CALLER_SPEECH not in blob
    assert any("n >= 59" in f for f in result.findings)


def test_the_module_contributes_gate_4_to_the_runner_registry():
    from scripts.pilot.latency import GATES

    assert set(GATES) == {4}
