"""What `BolnaEngine.list_executions` may and may not claim about a window.

D-31 makes this call the GUARANTEE OF RECORD: Bolna delivers webhooks at most once with
no retry, so an execution missing from this listing is a call that produces no lead, no
usage event, no recording and no error — nobody ever finds out. The method used to issue
one GET, read one page, and hand the poller a bare list; a truncated answer and a quiet
half-hour were the same value.

Bolna publishes no OpenAPI spec and no pagination contract, so these tests pin what the
adapter does with each response shape it might MEET, not what the vendor is known to
send. That is the point: every branch here is a hypothesis, written to be inert when the
key is absent, and the pilot (OPERATIONS §2 gate 6) is what turns one of them into a
fact. The one thing that must hold under every shape is that the adapter never reports
`complete=True` without grounds.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from apps.api.engine.bolna import BASE_URL, BolnaEngine
from calevate_shared.engine import ExecutionListing

SINCE = datetime(2026, 8, 14, 9, 0, tzinfo=UTC)
# Small enough to write out, and a member of the adapter's conventional-page-size set,
# so a response of exactly this length is the "looks like a page" case.
PAGE = 10


def _row(idx: int) -> dict[str, Any]:
    return {"id": f"exec_{idx}", "agent_id": "agent_1", "status": "completed"}


def _engine(responses: dict[str, dict[str, Any]], *, seen: list[str] | None = None) -> BolnaEngine:
    """An engine whose API answers by PATH+QUERY, so a test can pin exactly which URLs
    were fetched — the only way to prove a continuation was followed, or refused."""

    def handler(request: httpx.Request) -> httpx.Response:
        key = request.url.raw_path.decode()
        if seen is not None:
            seen.append(f"{request.url.host}{key}")
        for candidate, payload in responses.items():
            if key.startswith(candidate):
                return httpx.Response(200, json=payload)
        return httpx.Response(404, json={"error": "unexpected url"})

    return BolnaEngine(
        api_key="k",
        fx_rate=Decimal("88.00"),
        client=httpx.AsyncClient(base_url=BASE_URL, transport=httpx.MockTransport(handler)),
    )


async def _list(engine: BolnaEngine) -> ExecutionListing:
    return await engine.list_executions(since=SINCE - timedelta(minutes=30))


# --- the case that has no metadata at all -------------------------------------


async def test_a_short_page_with_no_metadata_is_complete() -> None:
    """The healthy tick. A heuristic that fires here would fire every ten minutes and
    train the operator to ignore the alarm that says calls are being lost."""
    listing = await _list(_engine({"/executions": {"data": [_row(i) for i in range(3)]}}))

    assert [s.engine_call_id for s in listing.snapshots] == ["exec_0", "exec_1", "exec_2"]
    assert listing.complete
    assert listing.incomplete_reason is None
    assert listing.pages_fetched == 1


async def test_a_page_sized_answer_with_no_metadata_refuses_to_claim_completeness() -> None:
    """The defect this slice exists to remove.

    Exactly a conventional page size, no `next`, no `total`: this is what a paginating
    vendor looks like from the outside when it tells you nothing. The adapter cannot know
    it was truncated and must not pretend it was not.
    """
    listing = await _list(_engine({"/executions": {"data": [_row(i) for i in range(PAGE)]}}))

    assert len(listing.snapshots) == PAGE, "the rows we did get are still returned"
    assert not listing.complete
    assert listing.incomplete_reason == "full_page_suspected"


# --- the cases where the payload says something -------------------------------


@pytest.mark.parametrize(
    "extra",
    [
        {"has_more": True},
        {"has_next": True},
        {"total": 900},
        {"total_count": 900},
        {"next_cursor": "eyJvZmZzZXQiOjUwfQ=="},
        {"next_page_token": "abc"},
    ],
    ids=["has_more", "has_next", "total", "total_count", "next_cursor", "next_page_token"],
)
async def test_a_payload_that_claims_more_is_reported_as_incomplete(
    extra: dict[str, Any],
) -> None:
    """Every one of these keys is a GUESS at a payload nobody has captured. They are
    tested together because the adapter's contract is the same for all of them: if the
    vendor says there is more and we cannot fetch it, the poller must hear about it —
    and if the key never appears, none of this fires and the page-size heuristic is what
    remains."""
    listing = await _list(_engine({"/executions": {"data": [_row(0), _row(1)], **extra}}))

    assert len(listing.snapshots) == 2
    assert not listing.complete
    assert listing.incomplete_reason == "explicit_more"


async def test_a_total_that_matches_what_we_got_is_not_a_claim_of_more() -> None:
    """`total: 2` on two rows is the normal complete answer. Reading every `total` as
    truncation would alert on every healthy tick."""
    listing = await _list(_engine({"/executions": {"data": [_row(0), _row(1)], "total": 2}}))

    assert listing.complete


# --- following a continuation the payload itself hands us ---------------------


async def test_a_next_link_is_followed_and_the_pages_are_merged() -> None:
    """Pagination is supported ONLY in the form that needs no invented parameter name.

    A `next` the payload gives us is self-describing: we GET it as written. Guessing
    `?page=2` against a vendor that ignores it returns page one forever — a loop, or with
    the cap, a listing that claims to have paged and did not.
    """
    seen: list[str] = []
    # The more specific URL first: `_engine` matches by prefix, in insertion order.
    engine = _engine(
        {
            "/executions?created_after=x&page_token=p2": {"data": [_row(2)]},
            "/executions": {
                "data": [_row(0), _row(1)],
                "next": "/executions?created_after=x&page_token=p2",
            },
        },
        seen=seen,
    )

    listing = await _list(engine)

    assert [s.engine_call_id for s in listing.snapshots] == ["exec_0", "exec_1", "exec_2"]
    assert listing.complete, "the continuation ran out — that is a positive completeness claim"
    assert listing.pages_fetched == 2
    assert any("page_token=p2" in url for url in seen), "the continuation was never fetched"


async def test_an_execution_repeated_across_pages_is_returned_once() -> None:
    """A window that keeps receiving calls while we page can legitimately repeat a row.
    Re-driving the same execution twice is wasted engine load and a duplicated repair
    count."""
    engine = _engine(
        {
            "/executions?created_after=x&page_token=p2": {"data": [_row(1), _row(2)]},
            "/executions": {
                "data": [_row(0), _row(1)],
                "next": "/executions?created_after=x&page_token=p2",
            },
        }
    )

    listing = await _list(engine)

    assert [s.engine_call_id for s in listing.snapshots] == ["exec_0", "exec_1", "exec_2"]


async def test_a_next_link_that_repeats_a_page_stops_instead_of_looping() -> None:
    """A malformed continuation is the failure mode that turns "follow the link" into an
    outage against the vendor. Bounded, and the truncation is reported."""
    engine = _engine(
        {
            "/executions": {
                "data": [_row(0)],
                "next": "/executions?page_token=same",
            }
        }
    )

    listing = await _list(engine)

    assert listing.incomplete_reason == "next_link_loop"
    assert not listing.complete
    assert listing.pages_fetched <= 3, "a self-referential link must not be walked repeatedly"


async def test_an_empty_first_page_with_a_next_link_is_not_reported_as_a_loop() -> None:
    """An empty result set is not a pagination bug, and must not be labelled as one.

    The walk used to stop on "no NEW rows" and call every such stop `next_link_loop`.
    A first page of zero executions with a `next` hits that branch: nothing repeated,
    no URL was seen twice, the vendor simply handed back an empty page. An operator
    reading `next_link_loop` goes looking for two identical continuation URLs and finds
    none — the reason has to name what actually happened.
    """
    engine = _engine({"/executions": {"data": [], "next": "/executions?page_token=p2"}})

    listing = await _list(engine)

    assert listing.snapshots == []
    assert not listing.complete, "a continuation we did not follow is never completeness"
    assert listing.incomplete_reason == "empty_page_with_next"
    assert listing.incomplete_reason != "next_link_loop", "an empty page is not a loop"
    assert listing.pages_fetched == 1, "pages_fetched == 1 is how the FIRST page is told"


async def test_a_fresh_link_that_re_serves_known_rows_is_no_progress_not_a_loop() -> None:
    """The third stop, and the reason it is not folded into either neighbour.

    The continuation URL is one we have never fetched, so it is not a loop; the page does
    carry rows, so it is not empty. What it carries is executions we already have — the
    vendor is re-serving content, and the walk has stopped covering new window. Three
    different investigations, so three different labels.
    """
    engine = _engine(
        {
            "/executions?page_token=p2": {"data": [_row(0)], "next": "/executions?page_token=p3"},
            "/executions": {"data": [_row(0)], "next": "/executions?page_token=p2"},
        }
    )

    listing = await _list(engine)

    assert [s.engine_call_id for s in listing.snapshots] == ["exec_0"]
    assert listing.incomplete_reason == "next_link_no_progress"
    assert listing.pages_fetched == 2


async def test_an_empty_page_reached_mid_walk_says_so_with_its_page_count() -> None:
    """The same empty-page stop after a page that DID produce. The label is shared with
    the first-page case on purpose — the fact is identical — and `pages_fetched` is what
    separates "the window was empty" from "the vendor ran dry mid-walk"."""
    engine = _engine(
        {
            "/executions?page_token=p2": {"data": [], "next": "/executions?page_token=p3"},
            "/executions": {"data": [_row(0)], "next": "/executions?page_token=p2"},
        }
    )

    listing = await _list(engine)

    assert [s.engine_call_id for s in listing.snapshots] == ["exec_0"]
    assert listing.incomplete_reason == "empty_page_with_next"
    assert listing.pages_fetched == 2


async def test_an_empty_last_page_with_no_continuation_is_still_complete() -> None:
    """The neighbouring healthy case: zero rows and NO `next` claims nothing, so the
    adapter's positive completeness claim stands and no reason is emitted at all."""
    listing = await _list(_engine({"/executions": {"data": []}}))

    assert listing.snapshots == []
    assert listing.complete
    assert listing.incomplete_reason is None


async def test_an_off_origin_next_link_is_refused_and_reported_rather_than_fetched() -> None:
    """`next` is vendor-controlled input that would become an outbound request carrying
    our `Authorization` header — the textbook SSRF/credential-leak shape. The
    destination is validated against the configured API host (an allowlist, not a
    denylist), and a refusal degrades to a LOUD incomplete rather than to a request at
    somebody else's host.
    """
    seen: list[str] = []
    engine = _engine(
        {"/executions": {"data": [_row(0)], "next": "https://evil.example.invalid/executions"}},
        seen=seen,
    )

    listing = await _list(engine)

    assert not listing.complete
    assert listing.incomplete_reason == "explicit_more"
    assert all("evil.example.invalid" not in url for url in seen), (
        "the adapter followed a vendor-supplied link to another host, with our API key on it"
    )


async def test_a_same_host_plaintext_next_link_is_refused_too() -> None:
    """The OTHER half of the destination check, and it was the untested half.

    The host allowlist stops a link to somebody else's server. It does nothing about a
    link to the RIGHT host over the wrong scheme: `http://api.bolna.ai/executions` passes
    a host comparison and would put our `Authorization` header on the wire in cleartext,
    for any network path between us and them to read. A downgrade is the classic way an
    allowlist that only checks WHO gets walked past — the check has to be scheme AND
    host, which is why `_next_link` requires both.

    Written because a sabotage found the gap: dropping `parsed.scheme == "https"` from
    that condition left the whole suite green, so the scheme half was decoration. It is
    a real assertion now.
    """
    seen: list[str] = []
    plaintext = f"http://{httpx.URL(BASE_URL).host}/executions?page_token=p2"
    engine = _engine({"/executions": {"data": [_row(0)], "next": plaintext}}, seen=seen)

    listing = await _list(engine)

    assert not listing.complete
    assert listing.incomplete_reason == "explicit_more", (
        "a refused continuation must still be reported as more-exists, not swallowed"
    )
    assert all(not url.startswith("http://") for url in seen), (
        "the adapter downgraded to plaintext on a vendor-supplied link, with our API key on it"
    )


async def test_paging_is_bounded_even_when_the_vendor_keeps_offering_more() -> None:
    """An endless continuation must end at OUR bound, and say that is why it ended."""
    counter = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        counter["n"] += 1
        n = counter["n"]
        return httpx.Response(
            200, json={"data": [_row(n)], "next": f"/executions?page_token=p{n + 1}"}
        )

    engine = BolnaEngine(
        api_key="k",
        fx_rate=Decimal("88.00"),
        client=httpx.AsyncClient(base_url=BASE_URL, transport=httpx.MockTransport(handler)),
    )

    listing = await engine.list_executions(since=SINCE)

    assert listing.incomplete_reason == "page_cap_reached"
    assert not listing.complete
    assert listing.pages_fetched == counter["n"] <= 20
