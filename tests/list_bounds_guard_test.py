"""The list-bounds guardrail, proved against the states it exists to catch (D-302).

`scripts/check_list_bounds.py` claims that no route in this API can answer with a list
whose length is decided by somebody's row count. A check making that claim while blind to
a violation is the worst outcome available: it puts a green tick beside the endpoint that
takes the process down on the day a client succeeds.

Same three kinds of test the newer guardrails established:

- **wiring** — pointed at the REAL app, so a check that has drifted from the live route
  table fails here rather than reporting on an app nobody serves.
- **detection** — one minimal mutation that IS the violation (an unbounded list route
  mounted on the real app; a registry entry outliving its route; an entry that has
  quietly become false), each asserted to be NAMED rather than merely counted.
- **calibration** — the shapes that legitimately pass, pinned so the rule cannot be
  relaxed into always passing: a bounded `limit` counts, an UNBOUNDED `limit` does not.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from apps.api.main import app
from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict
from scripts import check_list_bounds as guard


class _Row(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int


class _Wrapper(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[_Row]


@pytest.fixture
def mounted() -> Iterator[None]:
    """Four negative-control routes on the REAL app, removed again afterwards.

    The real app rather than a fixture app, for `check_public_routes`'s reason: the
    violation is "somebody adds a route", and the faithful rehearsal of that is adding
    one to the app the process serves.
    """
    before = list(app.router.routes)
    router = APIRouter()

    @router.get("/v1/negative-control/bare-list", response_model=list[_Row])
    async def _bare() -> list[_Row]:  # pragma: no cover - never called
        return []

    @router.get("/v1/negative-control/nested-list", response_model=_Wrapper)
    async def _nested() -> _Wrapper:  # pragma: no cover - never called
        return _Wrapper(items=[])

    @router.get("/v1/negative-control/unbounded-limit", response_model=list[_Row])
    async def _unbounded(limit: int = Query(50, ge=1)) -> list[_Row]:  # pragma: no cover
        return []

    @router.get("/v1/negative-control/bounded", response_model=list[_Row])
    async def _bounded(limit: int = Query(50, ge=1, le=200)) -> list[_Row]:  # pragma: no cover
        return []

    app.include_router(router)
    app.openapi_schema = None
    try:
        yield None
    finally:
        app.router.routes = before
        app.openapi_schema = None


# --- wiring --------------------------------------------------------------------------


def test_the_check_is_reading_the_live_route_table() -> None:
    """Non-vacuity, the same clause the check itself refuses on: a walk that finds no
    list routes would report a clean sweep of nothing."""
    routes = guard.list_routes(app)
    assert len(routes) >= 60, f"only {len(routes)} list routes found — the walk is broken"
    # The two shapes the walk has to see: a bare `list[...]` response and a list nested
    # inside a declared model. One of each, off the live app.
    assert "GET /v1/agents" in routes
    assert "GET /v1/leads" in routes


def test_the_live_app_passes() -> None:
    assert guard.audit(app) == []


# --- detection -----------------------------------------------------------------------


def test_an_unbounded_bare_list_route_is_named(mounted: None) -> None:
    problems = guard.audit(app)
    assert any("/v1/negative-control/bare-list" in problem for problem in problems), problems


def test_a_list_nested_in_a_response_model_is_not_missed(mounted: None) -> None:
    """The walk that only looked at the top-level annotation is the one that misses
    `LeadListOut.items` — i.e. every paginated panel in the product."""
    problems = guard.audit(app)
    assert any("/v1/negative-control/nested-list" in problem for problem in problems), problems


def test_a_limit_with_no_upper_bound_does_not_count(mounted: None) -> None:
    """The clause that makes this rule mean something. `limit: int = Query(50)` reads as
    a page size and is a parameter the caller sets to a million — which is the ONE
    request that turns a bounded route back into an unbounded one."""
    problems = guard.audit(app)
    assert any("/v1/negative-control/unbounded-limit" in problem for problem in problems), problems


def test_a_stale_registry_entry_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    """An entry outliving its route is a standing exemption waiting for a path to be
    reused (`check_public_routes` clause 2, same argument)."""
    monkeypatch.setitem(
        guard.BOUNDED_LISTS,
        "GET /v1/there-is-no-such-route",
        guard.BoundedByConstruction(by="a reason long enough to clear the forty-character floor"),
    )
    problems = guard.audit(app)
    assert any("/v1/there-is-no-such-route" in problem for problem in problems), problems


def test_an_entry_that_became_false_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    """A route that GAINED a `limit` keeps a registry entry saying it needs none, and the
    next reader believes it. `GET /v1/calls` is bounded today, so declaring it here is
    exactly that lie."""
    monkeypatch.setitem(
        guard.BOUNDED_LISTS,
        "GET /v1/calls",
        guard.BoundedByConstruction(by="a reason long enough to clear the forty-character floor"),
    )
    problems = guard.audit(app)
    named = [p for p in problems if "GET /v1/calls" in p and "false statement" in p]
    assert named, problems


def test_a_thin_reason_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """ "it is small" is the belief the check exists to stop trusting, so a reason has to
    be long enough to name a mechanism."""
    monkeypatch.setitem(
        guard.BOUNDED_LISTS, "GET /v1/me", guard.BoundedByConstruction(by="it is small")
    )
    problems = guard.audit(app)
    named = [p for p in problems if "GET /v1/me" in p and "characters" in p]
    assert named, problems


# --- calibration ---------------------------------------------------------------------


def test_a_bounded_limit_passes(mounted: None) -> None:
    problems = guard.audit(app)
    assert not any("/v1/negative-control/bounded" in problem for problem in problems), problems


def test_a_route_with_no_list_at_all_is_not_asked_for_a_limit() -> None:
    """`GET /v1/agents/{agent_id}/engine-state` returns one object with no list in it —
    the check must not demand a page size from every route in the app."""
    assert "GET /v1/agents/{agent_id}/engine-state" not in guard.list_routes(app)
