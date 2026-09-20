"""`scripts/measure_turn_detection.py` — the harness that turns `SMART_TURN_STOP_SECS` from
an inherited number into a measured one.

The expensive half (a real ONNX forward pass) runs here at two trials rather than sixty:
enough to prove the harness measures the real analyzer rather than a stub, without putting
a model load on every suite run for a figure the suite does not assert. The FIGURE is not
pinned — it is a property of whatever CPU the run lands on, and asserting it would make the
gate fail on a contended container instead of on a defect.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
import pytest
from scripts.measure_turn_detection import (
    DECISION_THRESHOLD,
    LATENCY_BUDGET_MS,
    TELEPHONY_SAMPLE_RATE_HZ,
    CorpusResult,
    LatencyResult,
    _read_wav,
    _render,
    measure_corpus,
    measure_latency,
)


def _write_wav(path: Path, *, seconds: float, rate: int, channels: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    samples = (np.random.default_rng(1).standard_normal(int(seconds * rate)) * 3000).astype(
        np.int16
    )
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(samples.tobytes() * channels)


def test_the_harness_runs_the_real_analyzer_at_the_carrier_rate() -> None:
    """A stub would report a latency that means nothing, so this asserts the work happened."""
    result = measure_latency(trials=2)

    assert result.trials == 2
    assert result.p50_ms > 0.0
    assert result.max_ms >= result.p50_ms
    assert TELEPHONY_SAMPLE_RATE_HZ == 8000


def test_a_corpus_recorded_at_the_wrong_rate_is_refused_not_resampled(tmp_path: Path) -> None:
    """Resampling would answer a question about a pipeline we do not run."""
    wrong = tmp_path / "wrong.wav"
    _write_wav(wrong, seconds=0.5, rate=16000)

    with pytest.raises(ValueError, match="16000 Hz"):
        _read_wav(wrong)


def test_a_stereo_clip_is_refused(tmp_path: Path) -> None:
    stereo = tmp_path / "stereo.wav"
    _write_wav(stereo, seconds=0.5, rate=TELEPHONY_SAMPLE_RATE_HZ, channels=2)

    with pytest.raises(ValueError, match="not mono"):
        _read_wav(stereo)


def test_a_clip_at_the_carrier_rate_reads_as_normalised_float(tmp_path: Path) -> None:
    good = tmp_path / "good.wav"
    _write_wav(good, seconds=0.25, rate=TELEPHONY_SAMPLE_RATE_HZ)

    audio = _read_wav(good)

    assert audio.dtype == np.float32
    assert len(audio) == int(0.25 * TELEPHONY_SAMPLE_RATE_HZ)
    assert float(np.abs(audio).max()) <= 1.0


def test_the_corpus_split_counts_the_two_errors_in_opposite_directions(tmp_path: Path) -> None:
    """A clip the caller had not finished, scored above threshold, is the agent talking over
    them — the error M-2 exists to bound. The other direction only costs a slower turn."""
    _write_wav(tmp_path / "complete" / "a.wav", seconds=1.0, rate=TELEPHONY_SAMPLE_RATE_HZ)
    _write_wav(tmp_path / "incomplete" / "b.wav", seconds=1.0, rate=TELEPHONY_SAMPLE_RATE_HZ)

    result = measure_corpus(tmp_path)

    assert result.complete_clips == 1
    assert result.incomplete_clips == 1
    assert result.missed_endpoints + result.false_endpoints <= 2
    assert set(result.probabilities) == {"complete/a.wav", "incomplete/b.wav"}
    assert all(0.0 <= p <= 1.0 for p in result.probabilities.values())


def test_an_absent_corpus_prints_unanswered_rather_than_a_number() -> None:
    """Hard rule 11: a not-finding is never rendered as a finding."""
    latency = LatencyResult(trials=1, p50_ms=10.0, p95_ms=12.0, p99_ms=13.0, max_ms=13.0)

    rendered = _render(latency, None)

    assert "UNANSWERED" in rendered
    assert "cannot be measured from synthetic audio" in rendered
    assert "PASS" in rendered


def test_the_budget_verdict_follows_p95_not_the_worst_case() -> None:
    """A single scheduler stall on a shared container is not a failed budget."""
    assert LatencyResult(
        trials=9, p50_ms=50.0, p95_ms=LATENCY_BUDGET_MS - 1, p99_ms=900.0, max_ms=900.0
    ).within_budget
    assert not LatencyResult(
        trials=9, p50_ms=50.0, p95_ms=LATENCY_BUDGET_MS + 1, p99_ms=120.0, max_ms=120.0
    ).within_budget


def test_the_false_endpoint_rate_is_zero_when_nothing_was_measured() -> None:
    """Division by an empty corpus must not raise inside a reporting path."""
    assert CorpusResult(0, 0, 0, 0).false_endpoint_rate == 0.0
    assert CorpusResult(0, 4, 0, 1).false_endpoint_rate == 0.25
    assert DECISION_THRESHOLD == 0.5
