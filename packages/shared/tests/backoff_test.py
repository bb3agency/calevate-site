"""The shared retry wait: equal jitter around each ladder step, a floor where one is asked for."""

from __future__ import annotations

import pytest
from calevate_shared.backoff import jittered_delay_s, ladder_delay_s

LADDER = (30.0, 120.0)


@pytest.mark.parametrize(("draw", "expected"), [(0.0, 15.0), (0.5, 22.5), (0.999, 29.985)])
def test_a_step_is_spread_over_its_upper_half(draw: float, expected: float) -> None:
    assert jittered_delay_s(30.0, rand=lambda: draw) == pytest.approx(expected)


def test_a_floor_is_never_undercut_and_the_jitter_goes_on_top() -> None:
    assert jittered_delay_s(600.0, floor_s=600.0, rand=lambda: 0.0) == 600.0
    assert jittered_delay_s(600.0, floor_s=600.0, rand=lambda: 0.999) == pytest.approx(899.7)


def test_two_jobs_failing_together_do_not_retry_together() -> None:
    waits = {jittered_delay_s(30.0) for _ in range(50)}
    assert len(waits) > 1
    assert all(15.0 <= wait < 30.0 for wait in waits)


@pytest.mark.parametrize(("attempt", "step"), [(0, 30.0), (1, 30.0), (2, 120.0), (99, 120.0)])
def test_the_ladder_never_indexes_past_its_own_end(attempt: int, step: float) -> None:
    assert ladder_delay_s(LADDER, attempt, rand=lambda: 0.0) == step / 2
