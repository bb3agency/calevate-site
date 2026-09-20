"""A lead dialled long after the customer acted is no longer a transactional call.

WHAT THIS PINS. `ingest_lead` is the one dial path with no campaign, no DLT template of
its own and no series check behind it: what makes ringing the person lawful is that they
themselves asked for it moments ago. A webhook RETRY or a source's BACKFILL arrives on
the same wire as a fresh submission, so without a clock the path would dial a cold list
hours late under a ground that had expired — and report it as a lead answered in two
seconds.

WHY THE UNIT TESTS AND NOT ONLY THE ROUTE. The decision is two pure functions plus one
branch; the parse half has failure modes (an un-offset timestamp, a forged future one,
a hostile string) that are tedious to reach through HTTP and exact to state here.

Run: uv run pytest -q tests/ingest_transactional_window_test.py
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from apps.api.db.session import tenant_session
from apps.api.ingest.service import (
    STALE_SUBMISSION_RULE,
    SUBMITTED_AT_KEY,
    TRANSACTIONAL_WINDOW,
    submission_instant,
    submission_is_stale,
)
from apps.api.main import app
from sqlalchemy import text
from tests.lead_ingest_test import SECRET as INGEST_SECRET
from tests.lead_ingest_test import _tenant_with_ingest

#: A fixed instant to measure against, so no test depends on when it runs.
RECEIVED = datetime(2026, 9, 20, 10, 0, 0, tzinfo=UTC)
RECEIVED_TS = RECEIVED.timestamp()


def _mapped(value: object) -> dict[str, object]:
    return {SUBMITTED_AT_KEY: value}


def test_the_window_is_thirty_minutes() -> None:
    """The figure the whole gate turns on, stated once where a change would be seen."""
    assert timedelta(minutes=30) == TRANSACTIONAL_WINDOW


def test_a_source_that_says_nothing_leaves_the_path_as_it_was() -> None:
    """The overwhelmingly common delivery: no timestamp, and the dial proceeds.

    Pinned because the alternative — treating silence as staleness — would refuse every
    lead from every source that has not been reconfigured, which is all of them.
    """
    assert submission_instant({}, {}) is None
    assert submission_is_stale(None, received_at=RECEIVED_TS) is False


@pytest.mark.parametrize(
    "raw",
    [
        "2026-09-20T09:59:00+00:00",
        "2026-09-20T09:59:00Z",
        "2026-09-20T15:29:00+05:30",
    ],
)
def test_an_offset_timestamp_is_read_whatever_its_spelling(raw: str) -> None:
    """`Z`, a numeric offset and IST all name one instant, and all three arrive in practice."""
    parsed = submission_instant(_mapped(raw), {})
    assert parsed is not None
    assert parsed == datetime(2026, 9, 20, 9, 59, tzinfo=UTC)
    assert submission_is_stale(parsed, received_at=RECEIVED_TS) is False


def test_epoch_seconds_are_read() -> None:
    """A number is unambiguous — it names an instant, not a wall clock."""
    parsed = submission_instant(_mapped(RECEIVED_TS - 60), {})
    assert parsed == RECEIVED - timedelta(minutes=1)


def test_a_timestamp_with_no_offset_is_refused_rather_than_guessed() -> None:
    """THE DELIBERATE GAP, and the reason it is a gap.

    Assume UTC and an Indian form sending local wall-clock time reads 5h30m stale, so
    every legitimate lead is refused; assume IST and a source really sending UTC gets a
    window five and a half hours wide. The string carries no third reading, so it is
    treated as absent and the delivery keeps the behaviour it had before the check.
    """
    assert submission_instant(_mapped("2026-09-20T09:59:00"), {}) is None


@pytest.mark.parametrize("raw", ["", "   ", "yesterday", "2026-13-45T99:99:99Z", None, True])
def test_a_value_we_cannot_read_never_blocks_a_dial(raw: object) -> None:
    """Unparseable is not stale. A source sending junk must not have every lead refused
    on the strength of it — the gate exists to catch late deliveries, not bad forms.

    `True` is in the set because `bool` is an `int` in Python, so a naive numeric branch
    would read it as the epoch and date the submission to 1970.
    """
    assert submission_instant(_mapped(raw), {}) is None


def test_the_payload_is_read_when_a_source_has_no_mapping() -> None:
    """A bare custom POST has no mapping at all, exactly as `phone` is read off the body."""
    assert submission_instant({}, _mapped("2026-09-20T09:59:00Z")) is not None


def test_a_mapped_field_wins_over_the_raw_body() -> None:
    """The mapping is the client's own statement about their form and is authoritative."""
    parsed = submission_instant(_mapped("2026-09-20T09:59:00Z"), _mapped("2020-01-01T00:00:00Z"))
    assert parsed == datetime(2026, 9, 20, 9, 59, tzinfo=UTC)


def test_a_submission_inside_the_window_is_dialled() -> None:
    inside = RECEIVED - TRANSACTIONAL_WINDOW + timedelta(seconds=1)
    assert submission_is_stale(inside, received_at=RECEIVED_TS) is False


def test_a_submission_past_the_window_is_stale() -> None:
    outside = RECEIVED - TRANSACTIONAL_WINDOW - timedelta(seconds=1)
    assert submission_is_stale(outside, received_at=RECEIVED_TS) is True


def test_the_boundary_itself_is_not_stale() -> None:
    """Exactly thirty minutes is WITHIN "within thirty minutes", so the comparison is
    strictly greater-than. Pinned because an off-by-one here refuses lawful calls."""
    assert submission_is_stale(RECEIVED - TRANSACTIONAL_WINDOW, received_at=RECEIVED_TS) is False


def test_staleness_is_measured_against_receipt_and_not_against_now() -> None:
    """Our own queue being slow must not make the sender's punctual lead stale.

    A delivery received long ago but processed now is still judged on the gap the SENDER
    was responsible for, which is why `received_at` is a parameter rather than a clock read.
    """
    long_ago = datetime(2020, 1, 1, 12, 0, tzinfo=UTC)
    punctual = long_ago - timedelta(minutes=1)
    assert submission_is_stale(punctual, received_at=long_ago.timestamp()) is False


def test_a_clock_running_fast_does_not_refuse_the_lead() -> None:
    """A future timestamp is a skewed clock on the client's own form.

    Refusing it would turn that skew into a silent outage on the path that matters most
    to them, to close a gap only a client forging timestamps against their own interest
    could use.
    """
    assert submission_is_stale(RECEIVED + timedelta(hours=3), received_at=RECEIVED_TS) is False


# ------------------------------------------------------ the refusal on the real path


@pytest.mark.asyncio
async def test_a_late_delivery_keeps_the_lead_and_refuses_the_dial() -> None:
    """THE WHOLE POINT, end to end rather than through the two helpers above.

    A retried or backfilled webhook looks identical on the wire to a fresh submission, so
    this is the only shape of test that can show the dial is actually stopped. The lead is
    KEPT: the person's enquiry is real and belongs in the CRM. What lapsed is the ground
    for telephoning them about it without the paperwork an ordinary outbound call needs.
    """
    tenant_id, _agent_id, webhook_id = await _tenant_with_ingest(
        mapping={"phone": "phone_number", "submitted_at": "filled_at"}
    )
    stale = (datetime.now(UTC) - TRANSACTIONAL_WINDOW - timedelta(minutes=5)).isoformat()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://api"
    ) as http:
        response = await http.post(
            f"/hooks/v1/ingest/{webhook_id}",
            json={"phone_number": "9876598765", "filled_at": stale},
            headers={"X-Ingest-Secret": INGEST_SECRET},
        )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["dispatched"] is False
    assert body["blocked"] == STALE_SUBMISSION_RULE

    async with tenant_session(tenant_id) as session:
        kept = (await session.execute(text("SELECT count(*) FROM leads"))).scalar_one()
    assert kept == 1, "the enquiry is real and is kept; only the call is refused"


@pytest.mark.asyncio
async def test_a_punctual_delivery_through_the_same_door_is_not_refused() -> None:
    """The other side of the branch, so the refusal above is the window and not the field.

    Same route, same mapping, same shape of payload — only the timestamp differs — which
    is what makes the pair evidence rather than two unrelated assertions.
    """
    _tenant_id, _agent_id, webhook_id = await _tenant_with_ingest(
        mapping={"phone": "phone_number", "submitted_at": "filled_at"}
    )
    fresh = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://api"
    ) as http:
        response = await http.post(
            f"/hooks/v1/ingest/{webhook_id}",
            json={"phone_number": "9876598766", "filled_at": fresh},
            headers={"X-Ingest-Secret": INGEST_SECRET},
        )
    assert response.status_code == 202, response.text
    assert response.json().get("blocked") != STALE_SUBMISSION_RULE
