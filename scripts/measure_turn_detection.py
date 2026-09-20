"""Measure smart turn v3 at the telephony rate, so `SMART_TURN_STOP_SECS` stops being inherited.

`voice_worker.pipeline.SMART_TURN_STOP_SECS` is 650 ms because that is what Bolna's fixed
endpointing cost us, not because anything was measured. `docs/evidence/
pre-build-blockers-2026-09-13.md` §3.6 opens four questions against it — M-1 (decision
latency on 8 kHz), M-2 (false endpoints on అవును/సరే/హా/ఓకే), M-3 (code-switch false
interruptions) and M-5 (whether the ceiling is ever actually reached). This answers the two
that do not need a corpus and refuses to guess at the two that do.

**M-1 IS ANSWERABLE HERE AND M-2 IS NOT, AND THE SPLIT IS NOT A CONVENIENCE.** The model
truncates or pads every input to a fixed 8-second window before inference
(`local_smart_turn_v3.py:139-150`), so the forward pass costs the same whatever the clip
holds — latency is a property of the model and the CPU, and Telugu speech cannot make it
differ from noise. Whether the model FIRES on a two-syllable Telugu affirmative is the
opposite: it is entirely a property of the content, and no synthetic signal stands in for
it. `--corpus` is the only path to an M-2 number, and without one this prints that M-2 is
unanswered rather than a figure that looks like an answer.

Synthesising the corpus with a TTS would be circular — it would measure whether the
endpointer agrees with the synthesiser, on audio with none of the disfluency, clipping or
G.711 damage that makes real PSTN turns hard.

The weights ship inside the wheel as package data (`pipecat/audio/turn/smart_turn/data/
smart-turn-v3.2-cpu.onnx`, 8.7 MB), so this runs with no network and no download — which is
what makes it a gate the founder can re-run rather than a one-off reading.

Usage::

    uv run python -m scripts.measure_turn_detection
    uv run python -m scripts.measure_turn_detection --corpus path/to/clips --json out.json

A corpus is a directory of 8 kHz mono WAV files in two subdirectories, `complete/` (the
speaker had finished) and `incomplete/` (they had not). A file under `incomplete/` that the
model scores above its 0.5 threshold is a false endpoint: the agent talks over the caller.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

import numpy as np

TELEPHONY_SAMPLE_RATE_HZ: Final[int] = 8000

#: The analyzer's own decision threshold, hardcoded at `local_smart_turn_v3.py:174` as
#: `probability > 0.5`. Read here rather than re-declared so a vendor change to it shows up
#: as a failed import instead of a silently wrong verdict.
DECISION_THRESHOLD: Final[float] = 0.5

#: Enough samples for the percentiles to mean something without making the gate slow to
#: re-run. The forward pass is the same work every time, so this measures spread, not warmup.
DEFAULT_TRIALS: Final[int] = 60

#: The budget the decision has to fit inside. `SMART_TURN_STOP_SECS` is the silence a turn
#: may end on; the inference that could have ended it EARLIER has to complete well within
#: that or the model never gets to beat the ceiling it exists to beat.
LATENCY_BUDGET_MS: Final[float] = 100.0


@dataclass(frozen=True)
class LatencyResult:
    """M-1: what one endpoint decision costs, at the rate the carrier actually delivers."""

    trials: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float

    @property
    def within_budget(self) -> bool:
        return self.p95_ms <= LATENCY_BUDGET_MS


@dataclass(frozen=True)
class CorpusResult:
    """M-2/M-3: how often the model is wrong, split by the direction of the error."""

    complete_clips: int
    incomplete_clips: int
    missed_endpoints: int
    false_endpoints: int
    probabilities: dict[str, float] = field(default_factory=dict)

    @property
    def false_endpoint_rate(self) -> float:
        if not self.incomplete_clips:
            return 0.0
        return self.false_endpoints / self.incomplete_clips


def _build_analyzer() -> object:
    """The REAL analyzer at the REAL rate — a stub here would measure nothing.

    Imported inside the function so `--help` works in a checkout whose voice-worker extras
    are not installed, which is most checkouts.
    """
    from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3

    analyzer = LocalSmartTurnAnalyzerV3(sample_rate=TELEPHONY_SAMPLE_RATE_HZ)
    analyzer._sample_rate = TELEPHONY_SAMPLE_RATE_HZ
    return analyzer


def _speech_shaped_noise(seconds: float, *, rng: np.random.Generator) -> np.ndarray:
    """A signal with roughly speech-like energy, for LATENCY only.

    Never used for an accuracy claim: the model pads or truncates to a fixed window before
    inference, so the cost does not depend on what the samples hold, and nothing else here
    reads this.
    """
    samples = int(seconds * TELEPHONY_SAMPLE_RATE_HZ)
    return (rng.standard_normal(samples) * 0.1).astype(np.float32)


def measure_latency(*, trials: int = DEFAULT_TRIALS) -> LatencyResult:
    """M-1. Timed around `_predict_endpoint` because that is the whole decision.

    The public `append_audio` returns early on the silence ceiling without running the model
    at all (`base_smart_turn.py:129-138`), so timing it would average the expensive path with
    a path that does no work and report neither.
    """
    analyzer = _build_analyzer()
    rng = np.random.default_rng(seed=20260920)

    durations = [1.0, 2.5, 4.0, 8.0, 12.0]
    analyzer._predict_endpoint(_speech_shaped_noise(2.0, rng=rng))  # type: ignore[attr-defined]

    timings: list[float] = []
    for index in range(trials):
        audio = _speech_shaped_noise(durations[index % len(durations)], rng=rng)
        started = time.perf_counter()
        analyzer._predict_endpoint(audio)  # type: ignore[attr-defined]
        timings.append((time.perf_counter() - started) * 1000.0)

    ordered = sorted(timings)
    return LatencyResult(
        trials=trials,
        p50_ms=statistics.median(ordered),
        p95_ms=ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))],
        p99_ms=ordered[min(len(ordered) - 1, int(len(ordered) * 0.99))],
        max_ms=ordered[-1],
    )


def _read_wav(path: Path) -> np.ndarray:
    """Refuses a rate that is not the carrier's rather than resampling it.

    A corpus recorded at 16 kHz would answer a question about a pipeline we do not run, and
    resampling it here would hide that in a number nobody could later question.
    """
    with wave.open(str(path), "rb") as handle:
        if handle.getframerate() != TELEPHONY_SAMPLE_RATE_HZ:
            raise ValueError(
                f"{path} is {handle.getframerate()} Hz; the carrier leg is "
                f"{TELEPHONY_SAMPLE_RATE_HZ} Hz and a resampled clip measures the wrong pipeline"
            )
        if handle.getnchannels() != 1:
            raise ValueError(f"{path} is not mono; a PSTN leg carries one channel")
        raw = handle.readframes(handle.getnframes())
    return (np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0).copy()


def measure_corpus(corpus: Path) -> CorpusResult:
    """M-2/M-3. Every clip is scored by the same analyzer the call path builds."""
    analyzer = _build_analyzer()
    probabilities: dict[str, float] = {}
    missed = 0
    false = 0
    complete_clips = 0
    incomplete_clips = 0

    for label in ("complete", "incomplete"):
        for path in sorted((corpus / label).glob("*.wav")):
            result = analyzer._predict_endpoint(_read_wav(path))  # type: ignore[attr-defined]
            probability = float(result["probability"])
            probabilities[f"{label}/{path.name}"] = probability
            fired = probability > DECISION_THRESHOLD
            if label == "complete":
                complete_clips += 1
                missed += 0 if fired else 1
            else:
                incomplete_clips += 1
                false += 1 if fired else 0

    return CorpusResult(
        complete_clips=complete_clips,
        incomplete_clips=incomplete_clips,
        missed_endpoints=missed,
        false_endpoints=false,
        probabilities=probabilities,
    )


def _render(latency: LatencyResult, corpus: CorpusResult | None) -> str:
    lines = [
        "TURN DETECTION MEASUREMENT",
        f"  rate: {TELEPHONY_SAMPLE_RATE_HZ} Hz   threshold: {DECISION_THRESHOLD}",
        "",
        f"M-1 decision latency over {latency.trials} inferences",
        f"  p50 {latency.p50_ms:.1f} ms   p95 {latency.p95_ms:.1f} ms   "
        f"p99 {latency.p99_ms:.1f} ms   max {latency.max_ms:.1f} ms",
        f"  budget {LATENCY_BUDGET_MS:.0f} ms at p95: "
        f"{'PASS' if latency.within_budget else 'FAIL'}",
        "",
    ]
    if corpus is None:
        lines += [
            "M-2 / M-3 false endpoints: UNANSWERED — no corpus supplied.",
            "  These are content-dependent and cannot be measured from synthetic audio.",
            "  Supply --corpus with real 8 kHz Telugu PSTN clips under complete/ and",
            "  incomplete/. Until then SMART_TURN_STOP_SECS stays at its inherited value.",
        ]
    else:
        lines += [
            f"M-2 / M-3 over {corpus.complete_clips} complete + "
            f"{corpus.incomplete_clips} incomplete clips",
            f"  false endpoints (agent talks over caller): {corpus.false_endpoints} "
            f"({corpus.false_endpoint_rate:.1%})",
            f"  missed endpoints (agent waits for the ceiling): {corpus.missed_endpoints}",
        ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--corpus", type=Path, default=None)
    parser.add_argument("--trials", type=int, default=DEFAULT_TRIALS)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)

    latency = measure_latency(trials=args.trials)
    corpus = measure_corpus(args.corpus) if args.corpus else None

    print(_render(latency, corpus))

    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "sample_rate_hz": TELEPHONY_SAMPLE_RATE_HZ,
                    "latency": latency.__dict__,
                    "corpus": None if corpus is None else corpus.__dict__,
                },
                indent=2,
            )
        )

    return 0 if latency.within_budget else 1


if __name__ == "__main__":
    sys.exit(main())
