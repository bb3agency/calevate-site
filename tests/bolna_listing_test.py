"""What `BolnaEngine.list_executions` asks for, and what it may claim about the answer.

D-31 promotes this call from safety net to GUARANTEE OF RECORD: an execution missing from
it is a call that produces no lead, no usage event, no recording and no error — nobody
ever finds out.

**THIS FILE USED TO TEST A ROUTE THE VENDOR DOES NOT HAVE (D-353).** Its subject was a
global `GET /executions?created_after=`, and a heuristic that inferred truncation from the
row count landing on a conventional page size — both built on the premise, repeated
throughout this repository, that "Bolna publishes no OpenAPI spec". Bolna publishes one
(`bolna-ai/skills@28b24aa references/openapi.yml`, D-350), it has no `/executions`
collection at all, and its per-agent listing has a documented `page_number`/`page_size`/
`has_more` contract. So every clause below is about the REAL endpoint, and the ones that
tested the heuristic are gone rather than ported.

What is pinned here and nowhere else: the URLs and query parameters that actually go out.
The conformance suite asserts the CONTRACT (`complete`, a reason, the rows); this asserts
that the contract is satisfied against the vendor's own routes rather than against a
plausible invention.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from apps.api.core.errors import ProblemError
from apps.api.engine.bolna import (
    _LISTING_MAX_PAGES,
    _LISTING_PAGE_SIZE,
    BASE_URL,
    BolnaEngine,
)
from calevate_shared.engine import ExecutionListing

# RELATIVE TO NOW, NOT A LITERAL DATE. It used to be `datetime(2026, 8, 14, 9, 0)`, which
# was fine on the day it was written and became a time bomb the moment `list_executions`
# grew a `_LISTING_MAX_WINDOW` guard: a fixture pinned to a fixed past instant drifts
# further from `now()` every day until the window it asks for is one the vendor will not
# serve, and the whole file then fails for a reason that has nothing to do with its
# subject. Nothing here asserts the absolute value — only the offset and the ordering.
SINCE = datetime.now(UTC)
AGENT = "agent_1"


def _row(idx: int, agent: str = AGENT) -> dict[str, Any]:
    return {"id": f"exec_{idx}", "agent_id": agent, "status": "completed"}


def _page(rows: list[dict[str, Any]], *, has_more: bool) -> dict[str, Any]:
    return {
        "page_number": 1,
        "page_size": _LISTING_PAGE_SIZE,
        "total": len(rows),
        "has_more": has_more,
        "data": rows,
    }


def _engine(
    executions: dict[str, Any] | None = None,
    *,
    agents: list[str] | None = None,
    agent_pages: dict[int, list[str]] | None = None,
    pages: dict[int, dict[str, Any]] | None = None,
    seen: list[str] | None = None,
) -> BolnaEngine:
    """An engine whose API answers by PATH+QUERY.

    `pages` keys the executions listing by `page_number`, which is the only way to prove
    the walk advanced rather than re-read page one — the exact failure the deleted
    `_next_link` machinery existed to avoid and the new page counter could still commit.

    `agent_pages` does the same for the ROSTER (`GET /v2/agent/all`), which is paginated
    too and was read one page deep (D-421). Keyed on `page_number` for the same reason:
    an adapter that re-requested page one would collect one page of agents forever and,
    because the roster carries no `has_more` to contradict it, report a complete listing.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if seen is not None:
            seen.append(request.url.raw_path.decode())
        if path == "/v2/agent/all":
            if agent_pages is not None:
                number = int(request.url.params.get("page_number", "1"))
                return httpx.Response(200, json=[{"id": a} for a in agent_pages.get(number, [])])
            roster = agents if agents is not None else [AGENT]
            return httpx.Response(200, json=[{"id": a} for a in roster])
        if path.endswith("/executions"):
            if pages is not None:
                number = int(request.url.params.get("page_number", "1"))
                return httpx.Response(200, json=pages[number])
            assert executions is not None
            return httpx.Response(200, json=executions)
        return httpx.Response(404, json={"error": "unexpected url"})

    return BolnaEngine(
        api_key="k",
        fx_rate=Decimal("88.00"),
        client=httpx.AsyncClient(base_url=BASE_URL, transport=httpx.MockTransport(handler)),
    )


async def _list(engine: BolnaEngine) -> ExecutionListing:
    return await engine.list_executions(since=SINCE - timedelta(minutes=30))


# --- the URLs and parameters that actually go out -----------------------------


async def test_the_listing_is_per_agent_on_the_route_the_vendor_publishes() -> None:
    """THE CLAUSE THIS FILE EXISTS FOR.

    The old implementation issued `GET /executions?created_after=<iso>`. The pinned OAS's
    only `/executions/...` entries are `GET /executions/{execution_id}` and `.../log`; the
    listing lives at `GET /v2/agent/{agent_id}/executions` and its time filter is spelled
    `from`. A 404 there is not a degraded listing — `vendor_request` raises,
    `reconcile_executions` reports `reconciliation_fetch_failed`, and the guarantee of
    record silently never runs.
    """
    seen: list[str] = []
    await _list(_engine(_page([_row(0)], has_more=False), seen=seen))

    assert seen[0].split("?")[0] == "/v2/agent/all", (
        "the fan-out starts by asking which agents exist"
    )
    listing_call = seen[1]
    assert listing_call.startswith(f"/v2/agent/{AGENT}/executions?"), (
        f"the listing must be the vendor's per-agent route, got {listing_call!r}"
    )
    assert "from=" in listing_call, "the vendor's time filter is `from`, not `created_after`"
    assert "created_after" not in listing_call
    assert f"page_size={_LISTING_PAGE_SIZE}" in listing_call
    assert "page_number=1" in listing_call


def test_the_page_size_stays_inside_the_vendors_documented_maximum() -> None:
    """`page_size` is documented as "Maximum allowed is 50". Asking for more is a 400 or a
    silently clamped page, and the second is the dangerous one: it would make every walk
    believe it had read more than it did."""
    assert _LISTING_PAGE_SIZE <= 50


async def test_the_time_filter_is_sent_as_utc_with_an_explicit_offset() -> None:
    """`references/bolna-core.md`: a datetime without a timezone offset "is rejected or
    silently runs in UTC". A listing whose window the vendor reinterprets silently covers
    the wrong half-hour, so the offset is not cosmetic. Both bounds, not just the lower
    one — a `to` the vendor reinterprets truncates the window from the far end, which is
    the end where the newest executions are."""
    seen: list[str] = []
    await _list(_engine(_page([], has_more=False), seen=seen))

    params = httpx.URL(f"{BASE_URL}{seen[1]}").params
    for bound in ("from", "to"):
        assert datetime.fromisoformat(params[bound]).utcoffset() == timedelta(0), (
            f"`{bound}` must carry an explicit UTC offset"
        )


async def test_both_halves_of_the_vendors_required_date_pair_are_sent() -> None:
    """THE PARAMETER THIS POLLER OMITTED, AND IT IS NOT OPTIONAL (D-412).

    `bolna-findings/mirror/pages/api-reference/executions/get_executions.md` states it in
    prose — "The `from` and `to` query parameters are **required** to filter executions by
    date ... Both `from` and `to` are **required** and must be passed **together**" — and
    marks both `required: true` in the OpenAPI block on the same page. D-353 moved this
    poller onto the right route and sent only the lower bound, so every tick was a 400:
    `reconcile_executions` reports `reconciliation_fetch_failed`, and the mechanism D-31
    appointed the GUARANTEE OF RECORD never runs. Same failure shape as the 404 D-353
    fixed, one parameter further along.

    The window must also be the one the caller asked for, in the right order — a `to`
    older than `from` is an empty window that reports itself as a clean, complete listing.
    """
    seen: list[str] = []
    await _list(_engine(_page([], has_more=False), seen=seen))

    params = httpx.URL(f"{BASE_URL}{seen[1]}").params
    assert "from" in params and "to" in params, (
        "the vendor requires the pair; sending one is a 400 on every tick"
    )
    lower = datetime.fromisoformat(params["from"])
    upper = datetime.fromisoformat(params["to"])
    assert lower < upper, "the window must run forwards"
    assert lower == SINCE - timedelta(minutes=30), "the lower bound is the caller's `since`"


async def test_every_agent_in_the_fan_out_is_asked_about_the_same_window() -> None:
    """`to` is evaluated ONCE, before the fan-out.

    Recomputing it per request would give each agent a slightly different upper bound, so
    "this listing covers `since`..`to`" would stop being one true statement about the
    answer — and `complete=True`, which the poller reads as "nothing was missed", is a
    claim about a window. Cheap to get wrong, invisible afterwards.
    """
    seen: list[str] = []
    await _list(
        _engine(
            _page([_row(0)], has_more=False),
            agents=["agent_a", "agent_b", "agent_c"],
            seen=seen,
        )
    )

    windows = {
        (
            httpx.URL(f"{BASE_URL}{call}").params["from"],
            httpx.URL(f"{BASE_URL}{call}").params["to"],
        )
        for call in seen[1:]
    }
    assert len(windows) == 1, f"each agent was asked about a different window: {windows}"


async def test_a_window_wider_than_the_vendor_serves_is_refused_not_silently_narrowed() -> None:
    """Seven days is the vendor's published maximum span, and this refuses rather than clamps.

    `get_executions.md`: "The maximum allowed range between `from` and `to` is **7 days**."
    Quietly moving `from` forward would make `complete=True` a claim about a period nobody
    asked us to skip, and `ListingIncompleteReason` has no member for "our own arithmetic
    moved the window" — its four values are all assertions about VENDOR truncation, so
    borrowing one would put a word in an operator's alert that the runbook defines as
    something else. A caller asking for a window the engine cannot serve is a bug in the
    caller, and it fails there, naming the limit.
    """
    engine = _engine(_page([], has_more=False))

    with pytest.raises(ProblemError) as raised:
        await engine.list_executions(since=datetime.now(UTC) - timedelta(days=8))

    assert raised.value.code == "engine_listing_window_too_wide"
    assert "7 days" in raised.value.detail


async def test_a_window_at_the_documented_limit_is_still_served() -> None:
    """The guard must bound the vendor's limit, not sit inside it.

    An off-by-one that refused at exactly seven days would turn a legal request into an
    engine error, and the poller's only visible symptom is the same alert either way.
    """
    seen: list[str] = []
    engine = _engine(_page([], has_more=False), seen=seen)

    listing = await engine.list_executions(
        since=datetime.now(UTC) - timedelta(days=7) + timedelta(seconds=5)
    )

    assert listing.complete
    assert "to=" in seen[1]


async def test_every_agent_on_the_account_is_walked() -> None:
    """The account holds every tenant's agents and the listing is per agent, so a fan-out
    that stopped at the first would lose every call placed by every other tenant."""
    seen: list[str] = []
    await _list(
        _engine(
            _page([_row(0)], has_more=False),
            agents=["agent_a", "agent_b", "agent_c"],
            seen=seen,
        )
    )

    assert [s.split("?")[0] for s in seen[1:]] == [
        "/v2/agent/agent_a/executions",
        "/v2/agent/agent_b/executions",
        "/v2/agent/agent_c/executions",
    ]


async def test_the_agent_roster_is_asked_for_with_the_vendors_pagination_parameters() -> None:
    """THE SECOND CLAUSE THIS FILE EXISTS FOR (D-421).

    `GET /v2/agent/all` was sent with no parameters at all, and whatever came back was
    treated as the whole account. `bolna-findings/mirror/pages/api-reference/
    pagination.md:9,13-14` documents `page_number` (default `1`) and `page_size` (default
    **20**, maximum 50) on "the endpoints", and the vendor's own CLI client for this exact
    route ships `--page`/`--page-size` with the same defaults
    (`bolna-findings/mirror/pages/cli/commands/agents-list.md:9,24-25`). So an account
    past its 21st agent was handing the poller a PAGE and being read as an ACCOUNT.
    """
    seen: list[str] = []
    await _list(_engine(_page([_row(0)], has_more=False), seen=seen))

    roster_call = httpx.URL(f"{BASE_URL}{seen[0]}")
    assert roster_call.params["page_number"] == "1"
    assert roster_call.params["page_size"] == str(_LISTING_PAGE_SIZE)


async def test_the_agent_roster_is_walked_past_its_first_page() -> None:
    """THE FAILURE THIS FIXES, AND IT WAS SILENT — which is what made it worse than the
    wrong route (D-353) or the missing `to` (D-412). Those were 400s and 404s on every
    tick. This one lost every execution belonging to the 21st agent onwards while
    `list_executions` went on answering `complete=True`, because completeness was decided
    per agent and never about the agent list itself. One Bolna account holds every
    tenant's agents, so the ceiling is a handful of clients.
    """
    later = f"agent_{_LISTING_PAGE_SIZE}"
    listing = await _list(
        _engine(
            _page([_row(0)], has_more=False),
            agent_pages={
                1: [f"agent_{i}" for i in range(_LISTING_PAGE_SIZE)],
                2: [later],
            },
            seen=(seen := []),
        )
    )

    walked = {s.split("?")[0] for s in seen if s.split("?")[0].endswith("/executions")}
    assert f"/v2/agent/{later}/executions" in walked, (
        "an agent past the first roster page must still be asked about"
    )
    assert listing.complete, "a roster walked to a short page is a roster we finished"


async def test_a_roster_page_that_repeats_itself_refuses_to_claim_completeness() -> None:
    """The reading where the platform IGNORES `page_number` — the shape a FastAPI handler
    with no declared query model has, and their OSS server is FastAPI. Page two then
    repeats page one, the walk stops rather than looping, and the roster it returns is
    still every agent the vendor was ever going to name. What it may NOT do is claim
    completeness: `GET /v2/agent/all` answers a bare array with no `has_more` and no
    `total` (`bolna-findings/mirror/pages/api-reference/agent/v2/get_all.md:29-51`), so a
    full page is indistinguishable from a truncated one and `complete=True` is a positive
    claim the adapter has no grounds for.
    """
    full = [f"agent_{i}" for i in range(_LISTING_PAGE_SIZE)]
    listing = await _list(_engine(_page([_row(0)], has_more=False), agent_pages={1: full, 2: full}))

    assert not listing.complete
    assert listing.incomplete_reason == "next_link_no_progress"


async def test_the_roster_walk_is_bounded_like_every_other_walk_here() -> None:
    """A roster that keeps offering full pages of new agents must still terminate:
    unbounded, the guarantee of record becomes an unbounded request loop against the
    vendor. `page_cap_reached` is the honest verdict — we stopped, and there was more.
    """
    listing = await _list(
        _engine(
            _page([], has_more=False),
            agent_pages={
                n: [f"agent_{n}_{i}" for i in range(_LISTING_PAGE_SIZE)]
                for n in range(1, _LISTING_MAX_PAGES + 3)
            },
        )
    )

    assert not listing.complete
    assert listing.incomplete_reason == "page_cap_reached"


async def test_a_truncated_roster_survives_a_clean_per_agent_walk() -> None:
    """THE PRECISE SHAPE OF THE OLD DEFECT, pinned so it cannot come back: every agent we
    DID ask about answers `has_more: false`, which is the one shape that earns
    `complete=True` per agent. The listing must still be incomplete, because the thing
    that was truncated is the list of agents rather than any agent's page — and an
    adapter that decided completeness only inside the fan-out would publish the all-clear
    on a roster it never finished.
    """
    full = [f"agent_{i}" for i in range(_LISTING_PAGE_SIZE)]
    listing = await _list(_engine(_page([_row(0)], has_more=False), agent_pages={1: full, 2: full}))

    assert all(s.engine_call_id for s in listing.snapshots)
    assert not listing.complete, (
        "a clean per-agent walk over an unfinished roster is still an unfinished listing"
    )


# --- what may be claimed about the answer -------------------------------------


async def test_a_page_that_says_there_is_no_more_is_complete() -> None:
    """The healthy tick. `has_more: false` is a positive statement by the vendor, so the
    adapter has grounds — this is the one shape where `complete=True` is earned."""
    listing = await _list(_engine(_page([_row(i) for i in range(3)], has_more=False)))

    assert [s.engine_call_id for s in listing.snapshots] == ["exec_0", "exec_1", "exec_2"]
    assert listing.complete
    assert listing.incomplete_reason is None


async def test_a_full_page_with_no_has_more_flag_refuses_to_claim_completeness() -> None:
    """`has_more` is documented, so its absence means we are not talking to the endpoint we
    think we are. Under that uncertainty a FULL page is the one shape that could be hiding
    rows, and the poller must be told."""
    rows = [_row(i) for i in range(_LISTING_PAGE_SIZE)]
    listing = await _list(_engine({"data": rows}))

    assert not listing.complete
    assert listing.incomplete_reason == "full_page_suspected"


async def test_a_short_page_with_no_has_more_flag_is_still_complete() -> None:
    """The other half of the same judgement, and the one that keeps the alarm meaningful: a
    page shorter than we asked for cannot be concealing anything, whatever metadata is
    missing. An adapter that alerted here would alert on every quiet half-hour."""
    listing = await _list(_engine({"data": [_row(0), _row(1)]}))

    assert listing.complete
    assert listing.incomplete_reason is None


async def test_pages_are_walked_and_merged_in_order() -> None:
    """`has_more: true` means fetch `page_number + 1`. Proven by keying the stub on the page
    number: an adapter that re-requested page one would collect three copies of the same
    rows and, thanks to de-duplication, report a short complete window."""
    listing = await _list(
        _engine(
            pages={
                1: _page([_row(0), _row(1)], has_more=True),
                2: _page([_row(2), _row(3)], has_more=True),
                3: _page([_row(4)], has_more=False),
            }
        )
    )

    assert [s.engine_call_id for s in listing.snapshots] == [f"exec_{i}" for i in range(5)]
    assert listing.complete
    # One `GET /v2/agent/all` plus three listing pages.
    assert listing.pages_fetched == 4


async def test_an_execution_repeated_across_pages_is_returned_once() -> None:
    """The vendor's window shifts under a walk — executions keep arriving while we page —
    so a repeat is legitimate. Re-driving one call twice is wasted engine load, and on the
    append-only usage ledger a double-meter is uncorrectable by construction."""
    listing = await _list(
        _engine(
            pages={
                1: _page([_row(0), _row(1)], has_more=True),
                2: _page([_row(1), _row(2)], has_more=False),
            }
        )
    )

    assert [s.engine_call_id for s in listing.snapshots] == ["exec_0", "exec_1", "exec_2"]
    assert listing.complete


async def test_a_stuck_has_more_flag_stops_rather_than_burning_the_page_cap() -> None:
    """`has_more` that never goes false while the rows repeat is a vendor re-serving
    content. Walking to the cap would spend twenty requests and then report
    `page_cap_reached`, which tells an operator we found rows all the way to our bound —
    the opposite of what happened."""
    listing = await _list(
        _engine(
            pages={n: _page([_row(0)], has_more=True) for n in range(1, _LISTING_MAX_PAGES + 2)}
        )
    )

    assert not listing.complete
    assert listing.incomplete_reason == "next_link_no_progress"
    assert listing.pages_fetched == 3, "the roster, page one, and the page proving no progress"


async def test_paging_is_bounded_even_when_the_vendor_keeps_offering_more() -> None:
    """A `has_more` that stays true on genuinely new rows must still terminate. Unbounded,
    the guarantee of record becomes an unbounded request loop against the vendor."""
    listing = await _list(
        _engine(
            pages={
                n: _page([_row(n * 100 + i) for i in range(2)], has_more=True)
                for n in range(1, _LISTING_MAX_PAGES + 5)
            }
        )
    )

    assert not listing.complete
    assert listing.incomplete_reason == "page_cap_reached"
    assert listing.pages_fetched == _LISTING_MAX_PAGES + 1


async def test_an_account_with_no_agents_lists_nothing_and_says_so_honestly() -> None:
    """Not an error and not an incomplete listing: an account holding no agents has no
    executions, and reporting `complete=False` here would page an operator every ten
    minutes about a correct answer."""
    listing = await _list(_engine(_page([], has_more=False), agents=[]))

    assert listing.snapshots == []
    assert listing.complete


@pytest.mark.parametrize("payload", [{"data": "nonsense"}, {}, {"data": [1, 2, 3]}])
async def test_a_response_we_cannot_read_rows_out_of_yields_no_fabricated_rows(
    payload: dict[str, Any],
) -> None:
    """An unreadable envelope must produce zero snapshots rather than a crash: the poller's
    next tick overlaps this window, so an empty answer self-heals and an exception in the
    guarantee of record does not."""
    listing = await _list(_engine(payload))

    assert listing.snapshots == []
