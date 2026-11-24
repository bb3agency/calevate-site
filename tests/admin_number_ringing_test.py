"""The admin numbers list says "Answered by" only for a number a call reaches (D-1019).

Since D-1019 an agent holds no engine agent of its own, so a number set to an agent rings only
through one of its live inbound lines; the list used to name the agent for every number set
to it, including one on a draft line that the platform was told nobody answers.
"""

from __future__ import annotations

from typing import Any

from apps.api.admin.number_routes import _ringing


def _row(
    *,
    agent: str | None = "Front desk",
    released: bool = False,
    direction: str = "inbound",
    status: str = "live",
    agent_ref: str | None = None,
    line: str | None = None,
    line_published: bool = False,
    line_ref: str | None = None,
    held: bool = False,
) -> tuple[Any, ...]:
    return (
        "id", "+910000000000", "standard", "na", "thinnest", True, True,
        "agent-id" if agent else None, agent, None, released, "num_1",
        direction, status, agent_ref, line, line_published, line_ref, held,
    )  # fmt: skip


def test_a_number_on_a_live_line_of_a_ref_less_agent_rings() -> None:
    assert _ringing(_row(line="Bookings", line_published=True, line_ref="line_1")) == (True, None)


def test_a_number_on_a_draft_line_does_not_ring_and_says_put_the_line_live() -> None:
    answers, why = _ringing(_row(line="Bookings", line_published=False, line_ref=None))
    assert answers is False
    assert why is not None and "Bookings is not live" in why


def test_a_number_on_no_line_of_a_ref_less_agent_does_not_ring() -> None:
    answers, why = _ringing(_row())
    assert answers is False
    assert why is not None and "on no live inbound line" in why


def test_the_legacy_own_engine_agent_still_rings() -> None:
    assert _ringing(_row(agent_ref="agent_1")) == (True, None)


def test_a_paused_agent_a_held_number_and_a_caller_only_agent_each_say_why() -> None:
    paused = _ringing(_row(status="paused", line="B", line_published=True, line_ref="l"))
    assert paused[0] is False and "not taking calls" in (paused[1] or "")
    held = _ringing(_row(held=True, line="B", line_published=True, line_ref="l"))
    assert held[0] is False and "on hold" in (held[1] or "")
    caller = _ringing(_row(direction="outbound", agent_ref="agent_1"))
    assert caller[0] is False and "only makes calls" in (caller[1] or "")


def test_nobody_set_or_released_gives_no_reason() -> None:
    assert _ringing(_row(agent=None)) == (False, None)
    assert _ringing(_row(released=True, agent_ref="agent_1")) == (False, None)
