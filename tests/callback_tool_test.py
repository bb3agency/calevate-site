"""The in-call booking tool, and the one thing it refuses to guess (D-510).

**GETTING A TIME WRONG RINGS SOMEBODY AT 4AM.** That single sentence decides the shape of
this endpoint and of every test here. Three controls stack, and only the first two are ours
to enforce:

1. **CONFIRM BEFORE COMMIT, SERVER-SIDE.** The model resolves "Tuesday at four" by talking
   to the caller; we cannot see that conversation and must not assume it happened. So the
   tool refuses to book without an explicit confirmation and hands back the resolved time
   in an unambiguous SPOKEN form for the agent to read out.
2. **THE DANGEROUS HALF OF EVERY AM/PM AMBIGUITY IS UNREACHABLE.** Every hour before 09:00
   is outside the calling window (TCCCPR; SEC-COMP §3) and is refused at BOOKING time as
   well as at dial time, so "four" heard as 04:00 cannot be booked at all. The harmless
   half costs one conversational turn.
3. **AND `resolve_slot` REFUSES RATHER THAN REPAIRS.** No full date, no booking.

The endpoint's other obligations are the opt-out tool's and are asserted the same way
(`tests/call_optout_test.py`): verify the source before a byte of body, ack fast, write
nothing, and name a job the worker actually registers.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
from typing import Any

import pytest
import tool_routes
from apps.workers.callbacks import BOOK_JOB, CANCEL_JOB
from calevate_shared.calling_window import (
    DEFAULT_WINDOW,
    IST,
    MAX_AHEAD,
    SLOT_REFUSALS,
    Slot,
    SlotRefusal,
    resolve_slot,
    within_window,
)
from httpx import ASGITransport, AsyncClient
from main import app as voice_app

pytestmark = pytest.mark.anyio

ENGINE_EGRESS_IP = "198.51.100.7"
EDGE_PROXY_IP = "127.0.0.1"
ATTACKER_IP = "203.0.113.9"
BOOK = "/tools/v1/bolna/callback"
CANCEL = "/tools/v1/bolna/callback/cancel"
HEADERS = {"CF-Connecting-IP": ENGINE_EGRESS_IP}

#: A Tuesday, 16:00 IST — the sentence this whole feature is written around.
NOW = datetime(2026, 9, 2, 6, 0, tzinfo=UTC)  # 11:30 IST on a Wednesday


@pytest.fixture
def _allowlist(source_ip_allowlist: Callable[..., None]) -> None:
    source_ip_allowlist(ENGINE_EGRESS_IP)


def _client(peer_ip: str = EDGE_PROXY_IP) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=voice_app, client=(peer_ip, 44444)),
        base_url="http://runtime",
    )


def test_the_endpoint_and_the_worker_name_the_same_jobs() -> None:
    """`tool_routes` cannot import `apps.workers` (hard rule 3, and the import-surface test
    enforces it), so each job name is spelled twice. This is what stops the two spellings
    drifting into an ack for a job nobody runs — and here that would be an agent telling
    somebody on the phone "booked for Tuesday" with nothing behind it."""
    assert tool_routes.BOOK_CALLBACK_JOB == BOOK_JOB
    assert tool_routes.CANCEL_CALLBACK_JOB == CANCEL_JOB


# --- the slot resolver: pure, and the reason it is allowed on the in-call path ---------


def test_a_time_with_no_full_date_is_refused_and_never_guessed() -> None:
    """ "Tuesday at four" is ambiguous in two directions and both are resolved by the MODEL,
    in conversation, before this is reached. What arrives here is already a decision, and
    this function's job is to refuse the ones we may not act on."""
    for date_text, time_text in (
        (None, "16:00"),
        ("2026-09-08", None),
        ("next tuesday", "16:00"),
        ("2026-09-08", "four in the afternoon"),
    ):
        refusal = resolve_slot(date_text, time_text, now=NOW)
        assert isinstance(refusal, SlotRefusal)
        assert refusal.code == "unreadable_time"


def test_every_hour_before_the_window_opens_is_unbookable() -> None:
    """THE 4AM TEST, and it is structural rather than careful: the model mis-hearing
    "four" as 04:00 produces a time this function cannot book at all, so the expensive half
    of the ambiguity has no path through the product."""
    for hour in range(0, 9):
        refusal = resolve_slot("2026-09-08", f"{hour:02d}:00", now=NOW)
        assert isinstance(refusal, SlotRefusal), f"{hour:02d}:00 IST was bookable"
        assert refusal.code == "outside_calling_hours"
        # AND IT OFFERS A REAL ALTERNATIVE rather than asking an open question the caller
        # has already answered.
        assert refusal.alternative is not None
        assert within_window(refusal.alternative.at_ist, DEFAULT_WINDOW)


def test_the_window_is_half_open_at_both_ends() -> None:
    """D-311's boundary, and a third comparison written the obvious way would have put it
    back one function along: 09:00:00 is inside, 21:00:00 is the first forbidden instant."""
    start, end = DEFAULT_WINDOW
    assert start == time(9, 0) and end == time(21, 0)
    assert isinstance(resolve_slot("2026-09-08", "09:00", now=NOW), Slot)
    assert isinstance(resolve_slot("2026-09-08", "20:59", now=NOW), Slot)
    refusal = resolve_slot("2026-09-08", "21:00", now=NOW)
    assert isinstance(refusal, SlotRefusal) and refusal.code == "outside_calling_hours"


def test_a_time_already_gone_and_a_time_a_year_away_are_both_refused() -> None:
    past = resolve_slot("2026-09-01", "16:00", now=NOW)
    assert isinstance(past, SlotRefusal) and past.code == "too_soon"
    far = resolve_slot((NOW + MAX_AHEAD + timedelta(days=2)).strftime("%Y-%m-%d"), "16:00", now=NOW)
    assert isinstance(far, SlotRefusal) and far.code == "too_far_ahead"


def test_the_spoken_form_a_caller_hears_back_cannot_be_misread() -> None:
    """A numeric date is the 9th of August to half the world, and a 24-hour clock is not
    what the caller said. Weekday and month NAME, 12-hour clock with AM/PM."""
    slot = resolve_slot("2026-09-08", "16:00", now=NOW)
    assert isinstance(slot, Slot)
    assert slot.spoken == "Tuesday 8 September at 4:00 PM"
    # UTC in, IST out (repo convention). 16:00 IST is 10:30 UTC.
    assert slot.at_utc == datetime(2026, 9, 8, 10, 30, tzinfo=UTC)
    assert slot.at_ist == slot.at_utc + IST


def test_the_refusal_vocabulary_is_closed() -> None:
    """The tool route, these tests and the agent's function description have to be
    provably talking about one set — a route that invented a fifth code would be a code
    nobody had written a sentence for."""
    seen = {
        resolve_slot(*args, now=NOW).code  # type: ignore[union-attr]
        for args in (
            (None, "16:00"),
            ("2026-09-01", "16:00"),
            ((NOW + MAX_AHEAD + timedelta(days=2)).strftime("%Y-%m-%d"), "16:00"),
            ("2026-09-08", "04:00"),
        )
    }
    assert seen == SLOT_REFUSALS


# --- the endpoint --------------------------------------------------------------------


async def test_a_stranger_cannot_book_a_call_on_a_clients_account(
    _allowlist: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The endpoint is unsigned, so the source check is the whole authenticity control.
    An open one would let anyone make this platform phone an arbitrary number under a
    client's DLT header, from their credit."""
    enqueued: list[str] = []

    async def _spy(job: str, payload: dict[str, Any], **kwargs: Any) -> str:
        enqueued.append(job)
        return "job-1"

    monkeypatch.setattr(tool_routes, "enqueue", _spy)
    async with _client() as client:
        response = await client.post(
            BOOK,
            json={"execution_id": "exec_x", "callback_date": "2026-09-08"},
            headers={"CF-Connecting-IP": ATTACKER_IP},
        )
    assert response.status_code == 401
    assert enqueued == []
    assert "X-Ack-Ms" in response.headers, "a refusal is measured too"


async def test_an_unconfirmed_time_is_not_booked_and_is_handed_back_to_read_out(
    _allowlist: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CONFIRM BEFORE COMMIT. The agent gets the resolved time in the form it must read;
    the caller gets the chance to say "no, four in the afternoon"."""
    enqueued: list[str] = []

    async def _spy(job: str, payload: dict[str, Any], **kwargs: Any) -> str:
        enqueued.append(job)
        return "job-1"

    monkeypatch.setattr(tool_routes, "enqueue", _spy)
    async with _client() as client:
        response = await client.post(
            BOOK,
            json={
                "execution_id": "exec_confirm",
                "callback_date": (datetime.now(UTC) + timedelta(days=2)).strftime("%Y-%m-%d"),
                "callback_time": "16:00",
            },
            headers=HEADERS,
        )
    body = response.json()
    assert body["status"] == "needs_confirmation"
    assert enqueued == [], "a time nobody read back was booked"
    assert "4:00 PM" in body["booked_for"]


async def test_a_confirmed_time_queues_the_booking_and_writes_nothing(
    _allowlist: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hard rule 3: ack fast, defer everything. THE RESOLVED INSTANT crosses the queue and
    never the caller's words — one parser, in one place, with one set of refusals, is what
    stops the endpoint refusing 22:00 and the worker cheerfully booking it."""
    captured: list[tuple[str, dict[str, Any]]] = []

    async def _spy(job: str, payload: dict[str, Any], **kwargs: Any) -> str:
        captured.append((job, payload))
        return "job-1"

    monkeypatch.setattr(tool_routes, "enqueue", _spy)
    day = (datetime.now(UTC) + timedelta(days=2)).strftime("%Y-%m-%d")
    async with _client() as client:
        response = await client.post(
            BOOK,
            json={
                "execution_id": "exec_booked",
                "callback_date": day,
                "callback_time": "16:00",
                "confirmed": True,
                "note": "wants the Gachibowli listing",
            },
            headers=HEADERS,
        )
    body = response.json()
    assert body["status"] == "accepted"
    assert len(captured) == 1
    job, payload = captured[0]
    assert job == BOOK_JOB
    # An INSTANT, not "Tuesday at four": the worker never re-parses a time.
    assert datetime.fromisoformat(payload["requested_at"]).tzinfo is not None
    # THE PAYLOAD CARRIES NO NUMBER AND NO TENANT (D-31): the worker re-derives both from
    # an authenticated fetch, because a payload-supplied number on an unsigned endpoint
    # would let anyone inside the allowlist dial an arbitrary person.
    assert "phone" not in payload and "tenant_id" not in payload


async def test_a_time_outside_calling_hours_is_a_conversation_and_not_an_error(
    _allowlist: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """200 AND NOT A 4xx, deliberately: the vendor's own troubleshooting reads a failing
    tool call as a misconfiguration, so an error would tell the agent OUR API is broken.
    What it needs to hear is what to offer the caller instead."""
    enqueued: list[str] = []

    async def _spy(job: str, payload: dict[str, Any], **kwargs: Any) -> str:
        enqueued.append(job)
        return "job-1"

    monkeypatch.setattr(tool_routes, "enqueue", _spy)
    day = (datetime.now(UTC) + timedelta(days=2)).strftime("%Y-%m-%d")
    async with _client() as client:
        response = await client.post(
            BOOK,
            json={
                "execution_id": "exec_night",
                "callback_date": day,
                "callback_time": "04:00",
                "confirmed": True,
            },
            headers=HEADERS,
        )
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "not_booked"
    assert body["reason"] == "outside_calling_hours"
    assert body["say"], "the agent was given no sentence to work with"
    assert enqueued == []


async def test_only_an_explicit_yes_counts_as_a_confirmation(
    _allowlist: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """NARROW ON PURPOSE. An unrecognised value costs one conversational turn; the other
    direction costs a wrong time. `1`, `"y"` and a non-empty string are all NOT yes."""
    booked: list[Any] = []

    async def _spy(job: str, payload: dict[str, Any], **kwargs: Any) -> str:
        booked.append(payload)
        return "job-1"

    monkeypatch.setattr(tool_routes, "enqueue", _spy)
    day = (datetime.now(UTC) + timedelta(days=2)).strftime("%Y-%m-%d")
    # `(value, is_yes)` pairs rather than a membership test: `1 == True` in Python, so
    # `1 in (True, ...)` is True and the table would have silently agreed with the bug it
    # is here to catch.
    cases: list[tuple[Any, bool]] = [
        (1, False),
        ("y", False),
        ("maybe", False),
        ("", False),
        ("TRUE", True),
        ("yes", True),
        (True, True),
    ]
    for index, (value, is_yes) in enumerate(cases):
        async with _client() as client:
            response = await client.post(
                BOOK,
                json={
                    "execution_id": f"exec_confirm_{index}",
                    "callback_date": day,
                    "callback_time": "16:00",
                    "confirmed": value,
                },
                headers=HEADERS,
            )
        expected = "accepted" if is_yes else "needs_confirmation"
        assert response.json()["status"] == expected, f"{value!r} was read as a yes/no wrongly"
    assert len(booked) == sum(1 for _v, yes in cases if yes)


async def test_calling_a_callback_off_never_depends_on_reading_a_time(
    _allowlist: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cancellation must not be able to fail because a date could not be parsed, which is
    why it is its own function with no time in it at all. It is also NOT the opt-out: "do
    not ring me back on Tuesday" is not "never call me again"."""
    captured: list[tuple[str, dict[str, Any]]] = []

    async def _spy(job: str, payload: dict[str, Any], **kwargs: Any) -> str:
        captured.append((job, payload))
        return "job-1"

    monkeypatch.setattr(tool_routes, "enqueue", _spy)
    async with _client() as client:
        response = await client.post(CANCEL, json={"execution_id": "exec_cancel"}, headers=HEADERS)
    assert response.json()["status"] == "accepted"
    assert [job for job, _ in captured] == [CANCEL_JOB]
    assert tool_routes.OPTOUT_JOB not in [job for job, _ in captured]


async def test_no_phone_number_reaches_a_log_line(
    _allowlist: None, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Hard rule 6, on the path a caller's number is most likely to arrive by accident."""

    async def _spy(job: str, payload: dict[str, Any], **kwargs: Any) -> str:
        return "job-1"

    monkeypatch.setattr(tool_routes, "enqueue", _spy)
    day = (datetime.now(UTC) + timedelta(days=2)).strftime("%Y-%m-%d")
    with caplog.at_level("INFO"):
        async with _client() as client:
            await client.post(
                BOOK,
                json={
                    "execution_id": "exec_log",
                    "callback_date": day,
                    "callback_time": "16:00",
                    "confirmed": True,
                    "note": "call +919812345671 back",
                },
                headers=HEADERS,
            )
    assert "+9198123456" not in caplog.text
