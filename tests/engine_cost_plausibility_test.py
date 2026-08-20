"""A per-call cost that is orders of magnitude wrong must not need a human to notice.

`engine/bolna.py` derives every rupee figure in `usage_events` from two things nothing
first-party states outright: which CURRENCY the vendor's number is in, and which UNIT of
that currency it is quoted in. `CostBreakdown.currency_stated` records which of those were
assumed. Nothing recorded whether the number they produced was the right SIZE — and the
way an assumption of this shape fails is not by a few percent but by 100x (the divisor) or
by ~90x (the fx rate applied to a figure already in rupees).

Neither failure raises, returns a 4xx or breaks a test. A call meters, a row lands, and
every panel downstream is quietly wrong in the direction that flatters us: no spend cap
arms, the margin panel reads as though the engine were free, and the first human to notice
is whoever reconciles the vendor invoice.

So the adapter scores its own output against what a minute of a phone call costs this
business and pages when it is orders of magnitude out. This file is that alarm's contract:
what it fires on, and — at least as important — what it must stay silent about, because an
alarm an operator learns to ignore is worse than no alarm at all.

Run: uv run pytest -q tests/engine_cost_plausibility_test.py
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from apps.api.core import alerting
from apps.api.engine import bolna
from apps.api.engine.bolna import BolnaEngine

FX = Decimal("83.50")


@pytest.fixture(autouse=True)
def _fresh_alert_state() -> None:
    """Per-fingerprint suppression is 15 minutes wide, so a second test asserting the same
    code would read the first test's window and see nothing. Reset before each."""
    alerting.reset_alerts()


def _engine() -> BolnaEngine:
    return BolnaEngine(api_key="k", fx_rate=FX)


def _payload(**over: object) -> dict[str, object]:
    """A 100-second `completed` execution costing 10 US cents — ₹8.35, i.e. ₹5.01/min,
    which is squarely inside the ₹0.5-6/min the adapter expects (BRD unit economics)."""
    return {
        "id": "exec-plausible",
        "status": "completed",
        "agent_id": "agent-1",
        "conversation_duration": 100,
        "total_cost": 10,
        **over,
    }


def _codes(caplog: pytest.LogCaptureFixture) -> list[str]:
    """The alert path writes ONE `log.error("alert", ...)` per firing, with the code in
    `extra`. Read codes, never messages: the message is prose, the code is the contract."""
    return [
        str(record.__dict__.get("code")) for record in caplog.records if record.message == "alert"
    ]


# --- what it must NOT fire on -------------------------------------------------


def test_a_normal_call_is_silent(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("ERROR"):
        snapshot = _engine()._snapshot(_payload())
    assert snapshot.cost is not None
    assert snapshot.cost.total_inr == Decimal("8.3500")
    assert _codes(caplog) == [], "₹5.01/min is what a call costs; paging on it is noise"


@pytest.mark.parametrize("total_cost", [1, 100])
def test_a_tenfold_price_move_in_either_direction_is_silent(
    total_cost: int, caplog: pytest.LogCaptureFixture
) -> None:
    """The band's whole design. A vendor re-pricing must never page — an operator who is
    paged for a price change learns to ignore the code, and then misses the 100x."""
    with caplog.at_level("ERROR"):
        _engine()._snapshot(_payload(total_cost=total_cost))
    assert _codes(caplog) == []


def test_a_call_with_no_cost_is_left_to_the_alarm_that_owns_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`call_billable_without_cost` is raised by `pipeline._meter`, which knows whether the
    execution was billable. Two alarms for one condition is two pages and one fix."""
    with caplog.at_level("ERROR"):
        snapshot = _engine()._snapshot(_payload(total_cost=None))
    assert snapshot.cost is None
    assert _codes(caplog) == []


def test_a_call_too_short_to_judge_is_not_judged(caplog: pytest.LogCaptureFixture) -> None:
    """A call that rang, connected and dropped inside a few seconds is routinely billed at
    zero. Its implied ₹/min is far below the floor and nothing is wrong — and this is the
    commonest call shape there is, so judging it would page constantly and get the code
    muted. Contrast the 100-second zero below, which IS a claim worth paging on."""
    with caplog.at_level("ERROR"):
        _engine()._snapshot(_payload(conversation_duration=5, total_cost=0))
    assert _codes(caplog) == []


def test_a_call_with_no_duration_is_not_judged(caplog: pytest.LogCaptureFixture) -> None:
    """The vendor omits `conversation_duration` on some shapes. There is no rate to imply
    from a length we do not have, and substituting a nominal one would turn the vendor's
    silence into a page — so the cost here is one that WOULD trip the ceiling at any
    duration a substitute could plausibly be."""
    with caplog.at_level("ERROR"):
        _engine()._snapshot(_payload(conversation_duration=None, total_cost=100_000))
    assert _codes(caplog) == []


# --- what it must fire on -----------------------------------------------------


def test_the_hundredfold_under_read_pages(caplog: pytest.LogCaptureFixture) -> None:
    """THE DEFECT THIS ALARM EXISTS FOR. A figure in MAJOR units divided by 100 anyway:
    ₹0.05/min instead of ₹5.01/min, every cap armed at a hundredth of real spend."""
    with caplog.at_level("ERROR"):
        _engine()._snapshot(_payload(total_cost=Decimal("0.1")))
    assert _codes(caplog) == ["engine_cost_implausible"]


def test_the_hundredfold_over_read_pages(caplog: pytest.LogCaptureFixture) -> None:
    """The other direction — minor units read as major — is the same class and is worse
    for the client: it inflates our recorded cost basis on every call."""
    with caplog.at_level("ERROR"):
        _engine()._snapshot(_payload(total_cost=1000))
    assert _codes(caplog) == ["engine_cost_implausible"]


def test_a_zero_cost_on_a_real_call_pages(caplog: pytest.LogCaptureFixture) -> None:
    """The 100x error's limit case once quantization eats the remainder. `None` means
    "not priced yet" and is silent above; a stated ZERO on a 100-second call is a claim,
    and it is one that would meter the call free for ever."""
    with caplog.at_level("ERROR"):
        _engine()._snapshot(_payload(total_cost=0))
    assert _codes(caplog) == ["engine_cost_implausible"]


def test_the_page_says_which_assumption_to_suspect(caplog: pytest.LogCaptureFixture) -> None:
    """An alarm that cannot be acted on at 3am is a log line. The detail carries the
    implied rate, the band, and which of the two assumptions the ratio points at — and no
    payload, no phone number, no transcript (hard rule 6)."""
    with caplog.at_level("ERROR"):
        _engine()._snapshot(_payload(total_cost=Decimal("0.1")))

    detail = next(
        str(record.__dict__.get("detail")) for record in caplog.records if record.message == "alert"
    )
    assert "per minute" in detail
    assert str(bolna._PLAUSIBLE_INR_PER_MIN_FLOOR) in detail
    assert str(bolna._PLAUSIBLE_INR_PER_MIN_CEILING) in detail
    assert "USD" in detail, "which currency the conversion assumed"


def test_the_band_could_not_hide_a_hundredfold_error() -> None:
    """The property the two literals have to satisfy, asserted rather than eyeballed.

    A band wider than 100x on either side of a real per-minute cost would let the defect
    that motivated the alarm sit inside it. This is what stops a future widening — made to
    quiet a noisy fixture — from silently retiring the alarm.
    """
    real = Decimal("5")  # ₹5/min, mid-range for the launch stack (BRD unit economics)
    assert real / 100 < bolna._PLAUSIBLE_INR_PER_MIN_FLOOR
    assert real * 100 > bolna._PLAUSIBLE_INR_PER_MIN_CEILING
