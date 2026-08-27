"""TRD §4's latency budget, and the arithmetic that holds its six numbers together.

**THIS IS A GUARD, NOT A MEASUREMENT, AND THE DIFFERENCE IS THE WHOLE POINT.** Every
figure asserted below is a TARGET — TRD §4a says so of each one in turn, marks it
"unmeasured", and names the slot a measured number may one day be written into. None of
them may ever be computed from the observations they judge: a budget derived from what the
fleet currently does passes by construction and measures nothing, which is why the
declaration lives beside the engine contract and not inside the report that reads it.

So the assertions here are of two kinds, and both are needed:

1. **The literals, against the document.** Each number is pinned to the line of
   `docs/TRD.md` it was read off. This half catches a budget quietly RELAXED — lower the
   TTS leg to 200ms and nothing about the composition breaks, but the product is no longer
   promising what the spec says it promises.
2. **The composition.** 300 + 350 + 300 + 100 = 1050ms of declared pipeline inside an
   1100ms voice-to-voice p50, i.e. 50ms of headroom for everything neither we nor the
   engine measures. This half catches a budget quietly WIDENED without the target that
   pays for it moving too — the failure that has no other witness, because each constant
   on its own still looks reasonable.

A change to any ONE of the six fails at least one of the two halves. That is the property
this file exists to have.
"""

from __future__ import annotations

import pytest
from calevate_shared.engine import (
    LATENCY_BUDGET,
    LLM_TTFT_BUDGET_MS,
    PIPELINE_BUDGET_MS,
    RETRIEVAL_BUDGET_MS,
    STT_BUDGET_MS,
    TTS_TTFA_BUDGET_MS,
    TURN_BUDGET_MS,
    VOICE_TO_VOICE_P50_TARGET_MS,
    VOICE_TO_VOICE_P95_TARGET_MS,
    LatencyBudget,
    latency_budget_composes,
)


def test_every_sub_budget_is_the_number_the_document_states() -> None:
    """The declaration against `docs/TRD.md`, line by line.

    Read this session from the document itself, not from a memory of it and not from a
    prior constant: `docs/TRD.md:281-282` ("STT finalization ≤300ms; LLM TTFT ≤350ms"),
    `:284` ("TTS TTFA ≤300ms streaming; retrieval ≤100ms (see §6)"), `:280`
    ("Voice-to-voice target: **p50 ≤ 1.1s, p95 ≤ 1.8s**"). §4a repeats all four
    sub-budgets at `:330-331` as the register of what is still unmeasured.
    """
    assert STT_BUDGET_MS == 300.0  # docs/TRD.md:281
    assert LLM_TTFT_BUDGET_MS == 350.0  # docs/TRD.md:282
    assert TTS_TTFA_BUDGET_MS == 300.0  # docs/TRD.md:284
    assert RETRIEVAL_BUDGET_MS == 100.0  # docs/TRD.md:284, via §6
    assert VOICE_TO_VOICE_P50_TARGET_MS == 1100.0  # docs/TRD.md:280
    assert VOICE_TO_VOICE_P95_TARGET_MS == 1800.0  # docs/TRD.md:280


def test_the_composed_totals_are_the_sum_of_their_parts_and_not_a_second_literal() -> None:
    """`TURN_BUDGET_MS` is arithmetic over the legs, so it cannot describe the old ones.

    Asserted BOTH ways on purpose: against the expression (which a refactor could
    accidentally satisfy by copying a literal into the module) and against the value 950,
    which is what the three legs the engine actually times add up to today.
    """
    assert TURN_BUDGET_MS == STT_BUDGET_MS + LLM_TTFT_BUDGET_MS + TTS_TTFA_BUDGET_MS
    assert TURN_BUDGET_MS == 950.0
    assert PIPELINE_BUDGET_MS == TURN_BUDGET_MS + RETRIEVAL_BUDGET_MS
    assert PIPELINE_BUDGET_MS == 1050.0


def test_the_sub_budgets_still_fit_inside_the_headline_target() -> None:
    """THE GUARD. Move one leg up by more than the headroom and this is what says so.

    50ms is what an 1100ms p50 leaves once TRD §4's four sub-budgets are spent, and it has
    to cover everything nobody here measures — the caller's own network, the carrier leg,
    the orchestrator's hops between the components it times separately. It is published as
    a field (`voice_to_voice_headroom_p50_ms`) rather than left to the reader precisely
    because it is small enough to be alarming.
    """
    assert latency_budget_composes() is True
    assert PIPELINE_BUDGET_MS <= VOICE_TO_VOICE_P50_TARGET_MS
    assert LATENCY_BUDGET.voice_to_voice_headroom_p50_ms == 50.0
    assert VOICE_TO_VOICE_P50_TARGET_MS < VOICE_TO_VOICE_P95_TARGET_MS


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("stt_ms", 700.0),
        ("llm_ttft_ms", 700.0),
        ("tts_ttfa_ms", 700.0),
        ("retrieval_ms", 700.0),
    ],
)
def test_a_leg_widened_past_the_headroom_stops_composing(field: str, value: float) -> None:
    """The guard's own guard: prove `latency_budget_composes` can FAIL.

    A composition check that passed for every input would be the same defect as a budget
    derived from its observations — green forever, measuring nothing. So each leg is
    widened in turn on a throwaway instance and the headroom is asserted to go negative.
    `LATENCY_BUDGET` itself is frozen and untouched; nothing in the product ever
    constructs a `LatencyBudget` with numbers of its own.
    """
    widened = LatencyBudget(**{field: value})
    assert widened.pipeline_ms > widened.voice_to_voice_p50_ms
    assert widened.voice_to_voice_headroom_p50_ms < 0


def test_the_budget_object_declares_nothing_the_constants_do_not() -> None:
    """`LATENCY_BUDGET` is a CARRIER for the wire, never a second declaration."""
    assert LATENCY_BUDGET.stt_ms == STT_BUDGET_MS
    assert LATENCY_BUDGET.llm_ttft_ms == LLM_TTFT_BUDGET_MS
    assert LATENCY_BUDGET.tts_ttfa_ms == TTS_TTFA_BUDGET_MS
    assert LATENCY_BUDGET.retrieval_ms == RETRIEVAL_BUDGET_MS
    assert LATENCY_BUDGET.voice_to_voice_p50_ms == VOICE_TO_VOICE_P50_TARGET_MS
    assert LATENCY_BUDGET.voice_to_voice_p95_ms == VOICE_TO_VOICE_P95_TARGET_MS
    assert LATENCY_BUDGET.turn_ms == TURN_BUDGET_MS
    assert LATENCY_BUDGET.pipeline_ms == PIPELINE_BUDGET_MS


def test_the_composed_totals_reach_the_wire_so_no_browser_adds_them_up() -> None:
    """The derivation is SERIALIZED, not left to the consumer.

    A console that summed the legs itself would be computing a target in the one place
    least able to defend it — `apps/web/src/lib/api/aiQuota.ts` states the doctrine, and
    the engine-latency screen is the surface that has to obey it here.
    """
    wire = LATENCY_BUDGET.model_dump()
    assert wire["turn_ms"] == 950.0
    assert wire["pipeline_ms"] == 1050.0
    assert wire["voice_to_voice_headroom_p50_ms"] == 50.0
    assert set(wire) == {
        "stt_ms",
        "llm_ttft_ms",
        "tts_ttfa_ms",
        "retrieval_ms",
        "voice_to_voice_p50_ms",
        "voice_to_voice_p95_ms",
        "turn_ms",
        "pipeline_ms",
        "voice_to_voice_headroom_p50_ms",
    }


def test_the_budget_cannot_be_edited_in_place() -> None:
    """Frozen, so a caller cannot relax the target it is about to be judged against."""
    with pytest.raises(ValueError):
        LATENCY_BUDGET.llm_ttft_ms = 9000.0  # type: ignore[misc]
