"""TRD §4's latency budget, and the arithmetic that holds its numbers together.

**THIS IS A GUARD, NOT A MEASUREMENT, AND THE DIFFERENCE IS THE WHOLE POINT.** Every
figure asserted below is a TARGET — TRD §4a says so of each one in turn, marks it
"unmeasured", and names the slot a measured number may one day be written into. None of
them may ever be computed from the observations they judge: a budget derived from what the
fleet currently does passes by construction and measures nothing, which is why the
declaration lives beside the engine contract and not inside the report that reads it.

So the assertions here are of three kinds, and all three are needed:

1. **The literals, against the document.** Each number is pinned to `docs/TRD.md` §4 and,
   through it, to the vendor page the allocation was read off. This half catches a budget
   quietly RELAXED — lower the TTS leg and nothing about the composition breaks, but the
   product is no longer promising what the spec says it promises.
2. **The composition.** 100 + 70 + 150 + 80 + 100 = 500ms of declared pipeline, plus a
   100ms crossing the caller cannot avoid, against a 500ms voice-to-voice target. This half
   catches a budget quietly WIDENED without the target that pays for it moving too.
3. **THE GAP, ASSERTED AS A FACT.** Since 27 Aug 2026 the budget does NOT fit inside the
   target: `latency_budget_composes()` is False and the headroom is -100ms. That is the
   founder's instruction carried out — set the target to 500 and show the gap — so it is
   pinned here, and a session that "fixes" this file by relaxing the target has to delete an
   assertion that says in words why it exists.
"""

from __future__ import annotations

import pytest
from calevate_shared.engine import (
    ENDPOINTING_BUDGET_MS,
    INDIA_US_TRANSIT_FLOOR_MS,
    INHERITED_TURN_DETECTION_MS,
    LATENCY_BUDGET,
    LLM_TTFT_BUDGET_MS,
    PIPELINE_BUDGET_MS,
    RETRIEVAL_BUDGET_MS,
    STT_BUDGET_MS,
    TTS_TTFA_BUDGET_MS,
    TURN_BUDGET_MS,
    VOICE_TO_VOICE_FLOOR_MS,
    VOICE_TO_VOICE_P50_TARGET_MS,
    VOICE_TO_VOICE_P95_TARGET_MS,
    LatencyBudget,
    latency_budget_composes,
    voice_to_voice_gap_ms,
)


def test_every_sub_budget_is_the_number_the_document_states() -> None:
    """The declaration against `docs/TRD.md` §4, leg by leg, with its evidence.

    Each figure is the FASTEST number its vendor publishes for that stage — a floor
    allocation, so that the gap below is the best case rather than an arbitrary cut:

    * endpointing 100ms — *"Decrease toward 100ms for fast-paced sales scripts"*
      (`bolna-findings/mirror/pages/concepts/latency.md:48`).
    * STT 70ms — Sarvam's own *"~70ms matches Sarvam STT processing latency"*
      (`sarvamai/skills`, `voice-agents/SKILL.md:57`), inside the engine's 50-150ms stage.
    * LLM TTFT 150ms — *"OpenAI gpt-4.1-mini | ~150ms"* (`latency.md:66`). UNVERIFIED on
      Azure, which publishes no per-model TTFT at all.
    * TTS TTFA 80ms — the floor of *"Synthesis first chunk (80-200ms)"* (`latency.md:24`).
      PROVISIONAL: no Sarvam streaming figure is readable from this environment.
    * retrieval 100ms — ours, unchanged, and the one leg no vendor bounds.
    """
    assert ENDPOINTING_BUDGET_MS == 100.0
    assert STT_BUDGET_MS == 70.0
    assert LLM_TTFT_BUDGET_MS == 150.0
    assert TTS_TTFA_BUDGET_MS == 80.0
    assert RETRIEVAL_BUDGET_MS == 100.0
    assert INDIA_US_TRANSIT_FLOOR_MS == 100.0
    assert VOICE_TO_VOICE_P50_TARGET_MS == 500.0
    assert VOICE_TO_VOICE_P95_TARGET_MS == 800.0


def test_the_shipped_turn_detection_is_the_vendor_defaults_we_never_overrode() -> None:
    """650ms = `endpointing` 250 + `incremental_delay` 400, both inherited.

    VERIFIED-VENDOR-DOCS, `bolna-findings/mirror/pages/api-reference/agent/v2/create.md`
    `:1055-1058` and `:418-427`. The agent payload sends neither key, so this is what every
    published agent waits before the pipeline it is budgeted against even starts. Asserted
    as a sum so the two halves stay legible: it is one integer each to change.
    """
    assert INHERITED_TURN_DETECTION_MS == 250.0 + 400.0
    assert INHERITED_TURN_DETECTION_MS > ENDPOINTING_BUDGET_MS * 6


def test_the_composed_totals_are_the_sum_of_their_parts_and_not_a_second_literal() -> None:
    """The totals are arithmetic over the legs, so they cannot describe the old ones.

    Asserted BOTH ways on purpose: against the expression (which a refactor could
    accidentally satisfy by copying a literal into the module) and against the value.
    `TURN_BUDGET_MS` is the THREE legs the engine times and deliberately excludes
    endpointing, because the engine reports no endpointing figure and a target must be the
    same quantity as the observation it judges.
    """
    assert TURN_BUDGET_MS == STT_BUDGET_MS + LLM_TTFT_BUDGET_MS + TTS_TTFA_BUDGET_MS
    assert TURN_BUDGET_MS == 300.0
    assert PIPELINE_BUDGET_MS == ENDPOINTING_BUDGET_MS + TURN_BUDGET_MS + RETRIEVAL_BUDGET_MS
    assert PIPELINE_BUDGET_MS == 500.0
    assert VOICE_TO_VOICE_FLOOR_MS == PIPELINE_BUDGET_MS + INDIA_US_TRANSIT_FLOOR_MS
    assert VOICE_TO_VOICE_FLOOR_MS == 600.0


def test_the_budget_does_not_fit_inside_the_target_and_says_so() -> None:
    """THE FINDING, pinned. 500ms was set; 600ms is the floor; the gap is 100ms.

    Every stage is already at the fastest figure its vendor publishes, so this is not a
    tuning problem with a tuning answer — TRD §4 "What would have to change" is the written
    version. The assertion is deliberately in the shape of a fact rather than of a target
    to fix: a session that makes `latency_budget_composes()` return True by widening the
    p50 has to delete this test and explain why.
    """
    assert latency_budget_composes() is False
    assert voice_to_voice_gap_ms() == 100.0
    assert LATENCY_BUDGET.composes is False
    assert LATENCY_BUDGET.voice_to_voice_headroom_p50_ms == -100.0
    assert VOICE_TO_VOICE_P50_TARGET_MS < VOICE_TO_VOICE_P95_TARGET_MS


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("endpointing_ms", 700.0),
        ("stt_ms", 700.0),
        ("llm_ttft_ms", 700.0),
        ("tts_ttfa_ms", 700.0),
        ("retrieval_ms", 700.0),
        ("india_us_transit_floor_ms", 700.0),
    ],
)
def test_every_declared_stage_moves_the_headroom(field: str, value: float) -> None:
    """Each stage is really IN the composition — including the two that were not.

    Endpointing was absent from this budget until 27 Aug 2026 and the crossing was hidden
    in the headroom; both are declared now, so both have to be able to move the total. Run
    on throwaway instances: `LATENCY_BUDGET` is frozen and nothing in the product ever
    constructs a `LatencyBudget` with numbers of its own.
    """
    widened = LatencyBudget(**{field: value})
    assert widened.voice_to_voice_headroom_p50_ms < LATENCY_BUDGET.voice_to_voice_headroom_p50_ms
    assert widened.composes is False


def test_the_composition_check_can_still_pass() -> None:
    """The guard's own guard, in the direction that now needs proving.

    A check that returned False for every input would be as useless as one that returned
    True for every input — and since today's answer is False, the falsifiable half is
    whether it can EVER say yes. Given a target big enough to hold the stages, it does. The
    numbers here are a hypothetical on a throwaway instance and are not a proposal.
    """
    generous = LatencyBudget(voice_to_voice_p50_ms=1_000.0)
    assert generous.voice_to_voice_headroom_p50_ms == 400.0
    assert generous.composes is True


def test_the_budget_object_declares_nothing_the_constants_do_not() -> None:
    """`LATENCY_BUDGET` is a CARRIER for the wire, never a second declaration."""
    assert LATENCY_BUDGET.endpointing_ms == ENDPOINTING_BUDGET_MS
    assert LATENCY_BUDGET.stt_ms == STT_BUDGET_MS
    assert LATENCY_BUDGET.llm_ttft_ms == LLM_TTFT_BUDGET_MS
    assert LATENCY_BUDGET.tts_ttfa_ms == TTS_TTFA_BUDGET_MS
    assert LATENCY_BUDGET.retrieval_ms == RETRIEVAL_BUDGET_MS
    assert LATENCY_BUDGET.india_us_transit_floor_ms == INDIA_US_TRANSIT_FLOOR_MS
    assert LATENCY_BUDGET.inherited_turn_detection_ms == INHERITED_TURN_DETECTION_MS
    assert LATENCY_BUDGET.voice_to_voice_p50_ms == VOICE_TO_VOICE_P50_TARGET_MS
    assert LATENCY_BUDGET.voice_to_voice_p95_ms == VOICE_TO_VOICE_P95_TARGET_MS
    assert LATENCY_BUDGET.turn_ms == TURN_BUDGET_MS
    assert LATENCY_BUDGET.pipeline_ms == PIPELINE_BUDGET_MS
    assert LATENCY_BUDGET.voice_to_voice_floor_ms == VOICE_TO_VOICE_FLOOR_MS


def test_the_composed_totals_reach_the_wire_so_no_browser_adds_them_up() -> None:
    """The derivation is SERIALIZED, not left to the consumer — the verdict included.

    A console that summed the legs itself would be computing a target in the one place
    least able to defend it — `apps/web/src/lib/api/aiQuota.ts` states the doctrine, and
    the engine-latency screen is the surface that has to obey it here. `composes` ships for
    the same reason: the screen states the shortfall, it does not derive it.
    """
    wire = LATENCY_BUDGET.model_dump()
    assert wire["turn_ms"] == 300.0
    assert wire["pipeline_ms"] == 500.0
    assert wire["voice_to_voice_floor_ms"] == 600.0
    assert wire["voice_to_voice_headroom_p50_ms"] == -100.0
    assert wire["composes"] is False
    assert set(wire) == {
        "endpointing_ms",
        "stt_ms",
        "llm_ttft_ms",
        "tts_ttfa_ms",
        "retrieval_ms",
        "india_us_transit_floor_ms",
        "inherited_turn_detection_ms",
        "voice_to_voice_p50_ms",
        "voice_to_voice_p95_ms",
        "turn_ms",
        "pipeline_ms",
        "voice_to_voice_floor_ms",
        "voice_to_voice_headroom_p50_ms",
        "composes",
    }


def test_the_budget_cannot_be_edited_in_place() -> None:
    """Frozen, so a caller cannot relax the target it is about to be judged against."""
    with pytest.raises(ValueError):
        LATENCY_BUDGET.llm_ttft_ms = 9000.0  # type: ignore[misc]
