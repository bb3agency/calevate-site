"""A truncated fleet walk resumes where the last one stopped, so the tail is reached.

Every budgeted walk used to start each pass at the top of an id-ordered directory and stop
at the same place, so the clients past the cut were skipped on every pass for as long as
the fleet outgrew one tick. `fleet_walk.resumed_walk` keeps the last tenant a pass reached
and starts the next pass after it.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import pytest
from apps.api.core.redis import get_redis
from apps.workers import fleet_walk, qa_sampling
from apps.workers.fleet_walk import WalkCursor, resumed_walk, rotate_after


class _Budget:
    """Spent after `n` items: the shape of a `WalkBudget` whose clock ran out."""

    def __init__(self, n: int) -> None:
        self.left = n
        self.exhausted = False

    def spent(self) -> bool:
        if self.left <= 0:
            self.exhausted = True
            return True
        self.left -= 1
        return False


def test_rotation_starts_after_the_last_key_and_wraps() -> None:
    assert rotate_after(["a", "b", "c", "d"], "b", key=str) == ["c", "d", "a", "b"]
    assert rotate_after(["a", "b", "c"], None, key=str) == ["a", "b", "c"]
    # A cursor naming a tenant deleted since still places the start.
    assert rotate_after(["a", "c", "d"], "b", key=str) == ["c", "d", "a"]


async def _drain(walk: str, ids: list[uuid.UUID], n: int) -> list[uuid.UUID]:
    return [tid async for tid in resumed_walk(walk, ids, _Budget(n))]  # type: ignore[arg-type]


async def test_consecutive_truncated_passes_cover_the_whole_fleet() -> None:
    walk = f"test-{uuid.uuid4().hex[:8]}"
    ids = sorted((uuid.uuid4() for _ in range(5)), key=str)
    try:
        first = await _drain(walk, ids, 2)
        second = await _drain(walk, ids, 2)
        third = await _drain(walk, ids, 2)
    finally:
        await get_redis().delete(fleet_walk.FLEET_CURSOR_KEY.format(walk=walk))
    assert first == ids[:2]
    assert second == ids[2:4], "the second pass skipped the tail the first one did not reach"
    assert third == [ids[4], ids[0]]


async def test_an_item_whose_body_raised_is_walked_again() -> None:
    walk = f"test-{uuid.uuid4().hex[:8]}"
    ids = sorted((uuid.uuid4() for _ in range(3)), key=str)
    try:
        with pytest.raises(RuntimeError):
            async for tid in resumed_walk(walk, ids, _Budget(3)):  # type: ignore[arg-type]
                if tid == ids[1]:
                    raise RuntimeError("tenant failed")
        assert await WalkCursor(walk).last() == str(ids[0])
        assert await _drain(walk, ids, 1) == [ids[1]]
    finally:
        await get_redis().delete(fleet_walk.FLEET_CURSOR_KEY.format(walk=walk))


async def test_the_weekly_qa_draw_reaches_the_tail_on_its_next_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    drawn: list[uuid.UUID] = []

    async def record(_session: Any, *, tenant_id: uuid.UUID, week_start: date) -> Any:
        drawn.append(tenant_id)

        class _Result:
            inserted = 0
            population = 0

        return _Result()

    monkeypatch.setattr(qa_sampling, "draw_week_sample", record)
    monkeypatch.setattr(qa_sampling, "WalkBudget", lambda: _Budget(1))
    tenants = sorted((uuid.uuid4() for _ in range(2)), key=str)

    class _Session:
        async def __aenter__(self) -> _Session:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr(qa_sampling, "tenant_session", lambda _tid: _Session())
    one = await qa_sampling.draw_for_tenants(tenants, [date(2026, 10, 19)])
    two = await qa_sampling.draw_for_tenants(tenants, [date(2026, 10, 19)])

    assert one["tenants_unreached"] == 1 and two["tenants_unreached"] == 1
    assert set(drawn) == set(tenants), "the second week's draw skipped the same tenant again"
