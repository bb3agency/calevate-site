"""Gate 13's harness, exercised against a fake switchboard (OPERATIONS §2 gate 13).

There is no Bolna account here, so the probes run against an in-memory switchboard that
behaves the way a platform at its ceiling behaves: it accepts dials until its slots are
full and then refuses (or queues) the rest, with real `asyncio` concurrency rather than a
loop pretending to be one. The paths that matter most all execute:

- a probe that HITS the ceiling, and the error shape it recorded there,
- a probe that never hits one (a lower bound, which must not read as a ceiling),
- the spend guard stopping a ramp before it spends the pilot budget,
- an effective ceiling REFUSED because one of the three legs was never recorded.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from pydantic import ValidationError
from scripts.pilot.concurrency import (
    INPUTS_ENV,
    MODEL_LEG,
    PASSING_VERDICTS,
    TRUNK_LEG,
    CeilingLeg,
    ProbeOutcome,
    RateLimitResult,
    dial_through_engine,
    effective_ceiling,
    evaluate_gate13,
    gate13_result,
    hangup_through_engine,
    is_phone_shaped,
    platform_leg_from_probe,
    probe_concurrency_ceiling,
    probe_dispatch_rate_limit,
    render_gate13_markdown,
    run_gate_13,
)


class FakeSwitchboard:
    """A platform with a finite slot pool, refusing or queueing beyond it.

    `dial` yields once before deciding, so a fan-out through `asyncio.gather` really is
    concurrent: every dial of a width is in flight before any of them is answered. That
    is what makes the ceiling assertion an assertion about concurrency rather than about
    a counter.
    """

    def __init__(
        self, ceiling: int, *, over_limit: str = "rejected", rate_limit_rps: float | None = None
    ):
        self.ceiling = ceiling
        self.over_limit = over_limit
        self.rate_limit_rps = rate_limit_rps
        self.active: set[str] = set()
        self.peak_active = 0
        self.dials = 0
        self.hangups: list[str] = []
        self.offered_rps: float | None = None

    async def paced_sleep(self, seconds: float) -> None:
        """Stand in for the probe's pacing, and LEARN the rate it is offering.

        The rate limit is enforced against the interval the probe actually waits, not
        against a counter the test set — so a probe that stopped pacing (or paced at the
        wrong interval) changes what this switchboard does, which is the only way the
        pacing logic is under test at all. No wall-clock cost: one yield keeps the
        ordering, the seconds are the thing being measured, not spent.
        """
        self.offered_rps = 1.0 / seconds if seconds > 0 else None
        await asyncio.sleep(0)

    async def dial(self, probe_ref: str) -> ProbeOutcome:
        self.dials += 1
        await asyncio.sleep(0)
        over_rate = (
            self.rate_limit_rps is not None
            and self.offered_rps is not None
            and self.offered_rps > self.rate_limit_rps
        )
        if len(self.active) >= self.ceiling or over_rate:
            return ProbeOutcome(
                probe_ref=probe_ref,
                kind="rejected" if (over_rate or self.over_limit == "rejected") else "queued",
                elapsed_ms=12,
                error_code="rate_limited" if over_rate else "engine_rejected",
                http_status=429,
                error_title="Too many concurrent calls",
            )
        self.active.add(probe_ref)
        self.peak_active = max(self.peak_active, len(self.active))
        return ProbeOutcome(probe_ref=probe_ref, kind="accepted", elapsed_ms=40)

    async def hangup(self, probe_ref: str) -> None:
        # Suspends before releasing, the way a real teardown does: a slot that freed
        # itself synchronously would let a fan-out of 100 pass through a pool of 1.
        await asyncio.sleep(0)
        self.hangups.append(probe_ref)
        self.active.discard(probe_ref)


async def _no_sleep(_seconds: float) -> None:
    """Pacing without wall-clock cost — one yield keeps the ordering, not the seconds."""
    await asyncio.sleep(0)


# --- the ceiling ---------------------------------------------------------------


async def test_the_probe_finds_the_ceiling_and_records_what_happened_at_it():
    board = FakeSwitchboard(ceiling=4)
    result = await probe_concurrency_ceiling(
        board.dial, widths=[1, 2, 4, 6, 8], hangup=board.hangup, max_dials=100
    )

    assert result.basis == "measured"
    assert result.highest_clean_width == 4
    assert result.first_limited_width == 6
    assert result.ceiling == 4
    assert result.behaviour_at_limit == "reject"
    assert board.peak_active == 4, "the fan-out must really have been concurrent"
    shapes = {(s.error_code, s.http_status) for s in result.error_shapes}
    assert ("engine_rejected", 429) in shapes
    # It stopped at the first limited width instead of buying the rest of the ramp.
    assert result.dials_used == 1 + 2 + 4 + 6


async def test_queueing_at_the_limit_is_not_recorded_as_rejection():
    board = FakeSwitchboard(ceiling=2, over_limit="queued")
    result = await probe_concurrency_ceiling(
        board.dial, widths=[2, 4], hangup=board.hangup, max_dials=50
    )
    assert result.behaviour_at_limit == "queue"
    assert result.observations[-1].queued == 2


async def test_a_ceiling_never_reached_is_a_lower_bound_and_refuses_to_be_a_ceiling():
    board = FakeSwitchboard(ceiling=1000)
    result = await probe_concurrency_ceiling(
        board.dial, widths=[1, 2, 4], hangup=board.hangup, max_dials=50
    )
    assert result.basis == "ceiling_above_probed_max"
    assert result.highest_clean_width == 4
    assert result.ceiling is None, "a lower bound must never be configured as a ceiling"
    assert platform_leg_from_probe(result).source == "absent"


async def test_the_spend_guard_stops_the_ramp_before_it_spends_the_pilot_budget():
    board = FakeSwitchboard(ceiling=1000)
    result = await probe_concurrency_ceiling(
        board.dial, widths=[1, 2, 4, 64], hangup=board.hangup, max_dials=10
    )
    assert result.basis == "aborted_spend_guard"
    assert result.dials_used == 7
    assert board.dials == 7, "no dial may be placed past the guard"
    assert result.ceiling is None


async def test_a_probe_that_raises_is_an_outcome_and_does_not_abort_a_ramp_already_paid_for():
    async def exploding_dial(probe_ref: str) -> ProbeOutcome:
        raise TimeoutError("dialled +919876543210 and gave up")

    result = await probe_concurrency_ceiling(exploding_dial, widths=[2], max_dials=10)
    assert result.observations[0].errors == 2
    assert result.behaviour_at_limit == "error"
    codes = {s.error_code for s in result.error_shapes}
    assert codes == {"TimeoutError"}
    # The exception's message named a number; only the type survived (hard rule 6).
    assert "9876543210" not in result.model_dump_json()


async def test_accepted_dials_are_hung_up_so_a_probe_costs_a_ring_not_a_conversation():
    board = FakeSwitchboard(ceiling=10)
    await probe_concurrency_ceiling(board.dial, widths=[3], hangup=board.hangup, max_dials=10)
    assert len(board.hangups) == 3
    assert board.active == set()


# --- the dispatch rate limit ---------------------------------------------------


async def test_the_dispatch_rate_limit_is_measured_and_becomes_the_dispatcher_config():
    board = FakeSwitchboard(ceiling=1000, rate_limit_rps=6.0)
    result = await probe_dispatch_rate_limit(
        board.dial,
        rates_per_s=[2.0, 5.0, 10.0],
        dials_per_rate=3,
        hangup=board.hangup,
        max_dials=100,
        sleep=board.paced_sleep,
    )
    assert result.basis == "measured"
    assert result.highest_clean_rps == 5.0
    assert result.first_limited_rps == 10.0
    assert result.dispatcher_config_rps == 5.0
    assert any(s.error_code == "rate_limited" for s in result.error_shapes)


async def test_an_unprovoked_rate_limit_yields_no_dispatcher_config_value():
    board = FakeSwitchboard(ceiling=1000)
    result = await probe_dispatch_rate_limit(
        board.dial,
        rates_per_s=[1.0, 2.0],
        dials_per_rate=2,
        max_dials=100,
        sleep=_no_sleep,
    )
    assert result.basis == "ceiling_above_probed_max"
    assert result.highest_clean_rps == 2.0
    assert result.dispatcher_config_rps is None


async def test_the_rate_probe_respects_the_spend_guard_too():
    board = FakeSwitchboard(ceiling=1000)
    result = await probe_dispatch_rate_limit(
        board.dial, rates_per_s=[1.0, 2.0], dials_per_rate=4, max_dials=5, sleep=_no_sleep
    )
    assert result.basis == "aborted_spend_guard"
    assert board.dials == 4


# --- the three ceilings --------------------------------------------------------


def _leg(name: str, value: int) -> CeilingLeg:
    return CeilingLeg(name=name, value=value, source="vendor_written")


async def _measured_platform_leg(ceiling: int) -> CeilingLeg:
    board = FakeSwitchboard(ceiling=ceiling)
    probe = await probe_concurrency_ceiling(
        board.dial, widths=[ceiling, ceiling + 2], hangup=board.hangup, max_dials=1000
    )
    return platform_leg_from_probe(probe)


async def test_the_effective_ceiling_is_the_min_of_all_three_legs():
    legs = [await _measured_platform_leg(100), _leg(MODEL_LEG, 60), _leg(TRUNK_LEG, 30)]
    effective = effective_ceiling(legs)
    assert effective.basis == "measured"
    assert effective.value == 30
    assert effective.binding_leg == TRUNK_LEG


async def test_one_missing_leg_produces_no_number_at_all():
    # The exact trap gate 13 names: the platform says 100, the trunk was never asked,
    # and somebody configures the dispatcher at 100.
    legs = [
        await _measured_platform_leg(100),
        _leg(MODEL_LEG, 60),
        CeilingLeg(name=TRUNK_LEG),
    ]
    effective = effective_ceiling(legs)
    assert effective.value is None
    assert effective.basis == "incomplete"
    assert effective.missing == [TRUNK_LEG]
    assert "MIN of all three" in effective.note


def test_nothing_recorded_is_not_run_rather_than_incomplete():
    effective = effective_ceiling([CeilingLeg(name=MODEL_LEG), CeilingLeg(name=TRUNK_LEG)])
    assert effective.basis == "not_run"
    assert effective.value is None


def test_a_leg_cannot_hold_a_value_without_a_source_or_a_source_without_a_value():
    with pytest.raises(ValidationError):
        CeilingLeg(name=TRUNK_LEG, value=30, source="absent")
    with pytest.raises(ValidationError):
        CeilingLeg(name=TRUNK_LEG, value=None, source="vendor_written")


# --- PII ----------------------------------------------------------------------


def test_a_probe_ref_that_looks_like_a_phone_number_is_refused_at_the_boundary():
    assert is_phone_shaped("+919876543210")
    assert not is_phone_shaped("probe-w16-3")
    with pytest.raises(ValidationError):
        ProbeOutcome(probe_ref="+919876543210", kind="accepted", elapsed_ms=10)


# --- the gate's verdict --------------------------------------------------------


async def test_the_gate_passes_only_when_all_four_answers_exist():
    board = FakeSwitchboard(ceiling=4)
    probe = await probe_concurrency_ceiling(
        board.dial, widths=[2, 4, 6], hangup=board.hangup, max_dials=100
    )
    # A SECOND switchboard for the rate probe: the two limits are different platform
    # behaviours and measuring one through the other's exhausted counters is how a
    # harness reports a rate limit it never provoked.
    rate_board = FakeSwitchboard(ceiling=1000, rate_limit_rps=6.0)
    rate = await probe_dispatch_rate_limit(
        rate_board.dial,
        rates_per_s=[2.0, 10.0],
        dials_per_rate=3,
        hangup=rate_board.hangup,
        max_dials=100,
        sleep=rate_board.paced_sleep,
    )
    result = evaluate_gate13(
        platform_probe=probe,
        rate_limit=rate,
        model_leg=_leg(MODEL_LEG, 60),
        trunk_leg=_leg(TRUNK_LEG, 30),
    )
    assert result.verdict == "PASS"
    assert result.passed
    assert result.effective.value == 4


async def test_a_gate_missing_the_trunk_count_is_inconclusive_not_passed():
    board = FakeSwitchboard(ceiling=4)
    probe = await probe_concurrency_ceiling(
        board.dial, widths=[2, 4, 6], hangup=board.hangup, max_dials=100
    )
    rate_board = FakeSwitchboard(ceiling=1000, rate_limit_rps=6.0)
    rate = await probe_dispatch_rate_limit(
        rate_board.dial,
        rates_per_s=[2.0, 10.0],
        dials_per_rate=3,
        hangup=rate_board.hangup,
        max_dials=100,
        sleep=rate_board.paced_sleep,
    )
    result = evaluate_gate13(
        platform_probe=probe,
        rate_limit=rate,
        model_leg=_leg(MODEL_LEG, 60),
        trunk_leg=CeilingLeg(name=TRUNK_LEG),
    )
    assert result.verdict == "INCONCLUSIVE"
    assert result.verdict not in PASSING_VERDICTS
    rendered = render_gate13_markdown(result)
    assert "**ABSENT**" in rendered
    assert "NOT ESTABLISHED" in rendered


def test_a_gate_that_never_ran_says_so():
    from scripts.pilot.concurrency import CeilingProbeResult

    result = evaluate_gate13(
        platform_probe=CeilingProbeResult(basis="not_run"),
        rate_limit=RateLimitResult(basis="not_run"),
        model_leg=CeilingLeg(name=MODEL_LEG),
        trunk_leg=CeilingLeg(name=TRUNK_LEG),
    )
    assert result.verdict == "NOT RUN"
    assert not result.passed
    rendered = render_gate13_markdown(result)
    assert "VERDICT: NOT RUN" in rendered
    assert "DO NOT CONFIGURE" in rendered


# --- wiring into the shared harness --------------------------------------------


class StubContext:
    """The slice of `GateContext` this gate touches, over the real `fake` adapter.

    Deliberately not a mock of the engine: `FakeEngine` is the conformance control
    (TRD §5), so the dial seam is exercised against the same object the rest of the
    harness runs on.
    """

    def __init__(self, engine, *, calls_remaining: int, agent_ref: str):
        self.engine = engine
        self.calls_remaining = calls_remaining
        self.engine_agent_ref = agent_ref
        self.to_e164 = "+911140000000"
        self.spent = 0

    def spend_a_call(self) -> bool:
        if self.calls_remaining <= 0:
            return False
        self.calls_remaining -= 1
        self.spent += 1
        return True


async def _fake_engine_ctx(budget: int) -> StubContext:
    from apps.api.engine.fake import FakeEngine
    from calevate_shared.engine import AgentConfig

    engine = FakeEngine()
    ref = await engine.create_agent(
        AgentConfig(
            tenant_id="t-pilot",
            agent_id="a-pilot",
            name="pilot probe",
            direction="outbound",
            system_prompt="probe",
            disclosure_line="This call is recorded.",
        )
    )
    return StubContext(engine, calls_remaining=budget, agent_ref=ref)


async def test_the_dial_seam_works_against_the_fake_adapter_and_spends_the_budget():
    ctx = await _fake_engine_ctx(budget=6)
    dial = dial_through_engine(ctx)
    outcome = await dial("probe-0")
    assert outcome.kind == "accepted"
    assert ctx.spent == 1
    # The ref carried forward is the engine execution handle, not the probe label and
    # certainly not the number dialled.
    assert outcome.probe_ref.startswith("fakecall_")
    await hangup_through_engine(ctx)(outcome.probe_ref)


async def test_against_the_fake_adapter_the_ceiling_is_reported_as_not_found():
    # A FINDING made executable: `fake` has no concurrency ceiling, so this half of
    # gate 13 CANNOT be exercised end to end without a real account. The right answer is
    # a refusal, not the widest width the probe happened to reach.
    ctx = await _fake_engine_ctx(budget=8)
    probe = await probe_concurrency_ceiling(
        dial_through_engine(ctx),
        widths=[1, 2, 4],
        hangup=hangup_through_engine(ctx),
        max_dials=8,
    )
    assert probe.basis == "ceiling_above_probed_max"
    assert probe.ceiling is None
    result = gate13_result(
        evaluate_gate13(
            platform_probe=probe,
            rate_limit=RateLimitResult(basis="not_run", note="not probed in this test"),
            model_leg=_leg(MODEL_LEG, 60),
            trunk_leg=_leg(TRUNK_LEG, 30),
        )
    )
    by_name = {c.name: c for c in result.checks}
    assert by_name["platform_concurrency_ceiling"].status == "not_run"
    assert result.status == "not_run"


async def test_the_gate_refuses_without_an_inputs_file(monkeypatch, tmp_path):
    monkeypatch.setenv(INPUTS_ENV, str(tmp_path / "absent.json"))
    result = await run_gate_13(await _fake_engine_ctx(budget=4))
    assert result.status == "not_run"
    assert result.blocked is not None and "inputs file" in result.blocked


async def test_the_gate_refuses_to_dial_on_a_zero_call_budget(monkeypatch, tmp_path):
    path = tmp_path / "gate13.json"
    path.write_text(
        json.dumps(
            {
                "engine_agent_ref": "fakeagent_x",
                "model_concurrency": 60,
                "model_concurrency_source": "vendor_written",
                "trunk_channels": 30,
                "trunk_channels_source": "vendor_written",
            }
        )
    )
    monkeypatch.setenv(INPUTS_ENV, str(path))
    ctx = await _fake_engine_ctx(budget=0)
    result = await run_gate_13(ctx)
    assert result.status == "not_run"
    assert ctx.spent == 0, "a dry run must place no calls"
    # The refusal must be the BUDGET one, not the spend guard tripping inside a ramp
    # that was allowed to start: `basis=not_run` says the probe was never entered.
    # (Asserting only on the words "call budget" was not enough — the spend guard's own
    # note says the same thing, so the assertion passed with the budget check deleted.)
    ceiling_check = next(c for c in result.checks if c.name == "platform_concurrency_ceiling")
    assert "basis=not_run" in ceiling_check.detail
    assert "call budget" in ceiling_check.detail


def test_the_module_contributes_gate_13_to_the_runner_registry():
    from scripts.pilot.concurrency import GATES

    assert set(GATES) == {13}
