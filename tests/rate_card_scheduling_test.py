"""SCHEDULING A RATE CARD: thirty days' notice, a withdrawal that is not a DELETE, and the
one property everything rests on — a future card changes NOTHING today (D-550).

The card became operator-editable. What that could have cost, and what each group here
stops:

* **The notice period.** A card is dated at least `CARD_NOTICE_DAYS` ahead, ALWAYS, a price
  CUT included. Predictability beat cleverness: a rule with an exception is a rule an
  operator has to reason about at the console, and "is this really a cut on every rung and
  both voices?" is exactly the question twelve cells make hard to answer under pressure.
* **The dating actually working.** `record_card` used to stamp `clock_timestamp()` and
  nothing else, so "record a card for next month" was not expressible. The tests below
  assert the whole property in both directions: the card in force does not move, a purchase
  made today still opens its lot at today's rates, and the new card starts exactly on its
  instant.
* **Withdrawal as a COMPENSATING ENTRY.** `platform_list_rates` is append-only (hard rule
  4); a scheduled card is un-scheduled by recording that it was, and the rate rows stay
  exactly where they are. The test that matters is the one that counts them afterwards.
* **The refusals, each with its own code**, because "invalid card" is the message an
  operator cannot act on: too soon, below cost, non-monotone, incomplete, duplicated,
  unknown, and money that arrived as a JSON number.

Every rupee figure here is derived from `PACK_CATALOGUE` or from the card under test — a
literal would be a second opinion about the ladder the margin guard scores.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from apps.api.billing.credit_packs import PACK_CATALOGUE
from apps.api.billing.list_rates import (
    CARD_NOTICE_DAYS,
    SELF_SERVE_PER_MIN,
    cancel_card,
    card_is_scheduled,
    card_list_rate,
    card_with_rates,
    notice_refusal,
    pack_rate_key,
    pending_cards,
    record_card,
)
from apps.api.billing.rates import VOICE_TIERS
from apps.api.billing.service import rate_card_at
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.stepup import StepUp
from apps.api.db.session import untenanted_session
from apps.api.main import app
from apps.api.ops.config_routes import (
    RATE_CARD_NOTICE_JOB,
    RateCardCancelIn,
    RateCardIn,
    cancel_rate_card,
    rate_card_cancel_confirmation,
    rate_card_confirmation,
    record_rate_card,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from starlette.requests import Request
from tests.admin_security_test import _make_admin
from tests.conftest import purge_platform_list_rates

PATH = "/v1/ops/rate-card"
CANCEL_PATH = f"{PATH}/cancellations"


@pytest.fixture(autouse=True)
async def _isolated_history() -> AsyncIterator[None]:
    """`platform_list_rates` is GLOBAL and append-only; a row left behind re-prices every
    other prepaid-money suite on this shared database. The owner-role purge lives in
    `tests/conftest.py` and is imported rather than copied."""
    await purge_platform_list_rates()
    yield
    await purge_platform_list_rates()


def _code(response: Any) -> str:
    """The problem's code, from the last segment of `type` — RFC-9457's own carrier, and
    the shape `core/errors.py` documents. There is no `code` member on the wire."""
    return str(response.json()["type"]).rsplit("/", 1)[1]


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _later(days: int = CARD_NOTICE_DAYS + 1) -> datetime:
    """A dateable instant, derived from the rule rather than typed."""
    return datetime.now(UTC) + timedelta(days=days)


def _cells(overrides: dict[tuple[str, str], str] | None = None) -> list[dict[str, str]]:
    """The whole card as the console posts it: twelve cells, money as exact strings."""
    moved = overrides or {}
    return [
        {
            "pack_id": pack.pack_id,
            "voice_tier": voice,
            "inr_per_min": moved.get((pack.pack_id, voice), str(pack.inr_per_min(voice))),
        }
        for pack in PACK_CATALOGUE
        for voice in VOICE_TIERS
    ]


def _rise(paise: str = "0.50") -> dict[tuple[str, str], str]:
    """The whole card, up by one amount. A rise rather than a cut so the card still clears
    every cost floor and the only thing under test is the scheduling."""
    return {
        (pack.pack_id, voice): str(pack.inr_per_min(voice) + Decimal(paise))
        for pack in PACK_CATALOGUE
        for voice in VOICE_TIERS
    }


def _body(at: datetime, overrides: dict[tuple[str, str], str] | None = None) -> dict[str, Any]:
    return {
        "effective_from": at.isoformat(),
        "reason": "annual list price review",
        "cells": _cells(overrides),
    }


def _headers(token: str, at: datetime | None, *, confirm: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if confirm is not None:
        headers["X-Confirm-Action"] = confirm
    elif at is not None:
        headers["X-Confirm-Action"] = rate_card_confirmation(at)
    return headers


async def _post(at: datetime, overrides: dict[tuple[str, str], str] | None = None) -> Any:
    token = await _make_admin()
    async with _client() as http:
        return await http.post(PATH, json=_body(at, overrides), headers=_headers(token, at))


async def _card_row_count() -> int:
    async with untenanted_session() as session:
        return int(
            (await session.execute(text("SELECT count(*) FROM platform_list_rates"))).scalar_one()
        )


# ── the notice period ────────────────────────────────────────────────────────────────


def test_a_date_exactly_the_notice_period_out_is_accepted() -> None:
    """A floor nobody can land on exactly reads as thirty-one days to everyone who tries,
    so the comparison is strict and the boundary is IN."""
    now = datetime.now(UTC)
    assert notice_refusal(now + timedelta(days=CARD_NOTICE_DAYS), now=now) is None


def test_a_date_one_microsecond_inside_the_notice_period_is_refused() -> None:
    """THE RULE, at its edge. The refusal names the date asked for AND the earliest one
    available, because an operator who cannot see the floor retries by guessing."""
    now = datetime.now(UTC)
    asked = now + timedelta(days=CARD_NOTICE_DAYS) - timedelta(microseconds=1)
    refusal = notice_refusal(asked, now=now)
    assert refusal is not None
    assert asked.isoformat() in refusal
    assert (now + timedelta(days=CARD_NOTICE_DAYS)).isoformat() in refusal


def test_the_notice_period_is_measured_from_an_aware_instant_only() -> None:
    """A naive instant would be read in the process's timezone: a UTC container and an IST
    laptop would disagree about whether the same date clears the floor by five and a half
    hours."""
    with pytest.raises(ValueError, match="aware instant"):
        notice_refusal(datetime(2026, 12, 1), now=datetime.now(UTC))
    with pytest.raises(ValueError, match="aware instant"):
        notice_refusal(_later(), now=datetime(2026, 12, 1))


async def test_a_card_starting_sooner_than_the_notice_period_is_refused_and_writes_nothing() -> (
    None
):
    before = await _card_row_count()
    response = await _post(_later(days=CARD_NOTICE_DAYS - 1))
    assert response.status_code == 422, response.text
    assert _code(response) == "rate_card_too_soon"
    assert await _card_row_count() == before


async def test_a_price_cut_gets_the_same_thirty_days_as_a_rise() -> None:
    """THE FOUNDER'S DECISION, PINNED. The obvious exception — "a cut helps everyone, let it
    land immediately" — is refused, because a rule with an exception is a rule an operator
    has to adjudicate, and a twelve-cell card makes "is this a cut for everybody?" a
    question nobody can answer at the console."""
    cut = {
        (pack.pack_id, voice): str(pack.inr_per_min(voice) - Decimal("0.10"))
        for pack in PACK_CATALOGUE
        for voice in VOICE_TIERS
    }
    response = await _post(_later(days=CARD_NOTICE_DAYS - 1), cut)
    assert response.status_code == 422, response.text
    assert _code(response) == "rate_card_too_soon"


# ── the effective dating, which is the whole feature ─────────────────────────────────


async def test_a_future_card_changes_nothing_until_its_date() -> None:
    """**THE PROPERTY EVERYTHING ELSE RESTS ON.** A card recorded for next month must be
    invisible to every reader until then — including `service.rate_card_at`, the one door a
    lot opener uses. If this ever goes green in the wrong direction, an operator's Save
    silently reprices the next purchase every client makes."""
    at = _later()
    assert (await _post(at, _rise())).status_code == 201
    starter = min(PACK_CATALOGUE, key=lambda pack: pack.amount_inr)

    async with untenanted_session() as session:
        today = await rate_card_at(session, at=datetime.now(UTC))
        on_the_day = await rate_card_at(session, at=at)
    # Today: exactly what the platform sold this morning.
    assert today.of_pack(starter).sarvam_inr_per_min == starter.sarvam_inr_per_min
    assert today.of_pack(starter).cartesia_inr_per_min == starter.cartesia_inr_per_min
    # On the day: the new card, and not a moment before it.
    assert on_the_day.of_pack(starter).sarvam_inr_per_min == starter.sarvam_inr_per_min + Decimal(
        "0.50"
    )


async def test_a_purchase_made_today_freezes_todays_rates_even_with_a_card_pending() -> None:
    """The same property said in the currency that matters: what a lot opened NOW would
    freeze. `rate_card_at(now).for_amount(...)` is exactly what `billing/payments.py` and
    `billing/credit_routes.py` call before opening one."""
    at = _later()
    assert (await _post(at, _rise())).status_code == 201
    biggest = max(PACK_CATALOGUE, key=lambda pack: pack.amount_inr)
    async with untenanted_session() as session:
        frozen = (await rate_card_at(session, at=datetime.now(UTC))).for_amount(biggest.amount_inr)
    assert frozen.sarvam_inr_per_min == biggest.sarvam_inr_per_min
    assert frozen.cartesia_inr_per_min == biggest.cartesia_inr_per_min


async def test_the_recorded_card_lands_as_twelve_rows_plus_the_legacy_key_at_one_instant() -> None:
    """One `effective_from` for the whole card — the invariant `record_card` exists for —
    and `SELF_SERVE_PER_MIN` holding the card's OWN list rate rather than the setting's, so
    `self_serve_rate_at` can never answer a rate this card did not sell."""
    at = _later()
    response = await _post(at, _rise())
    assert response.status_code == 201, response.text
    stamped = datetime.fromisoformat(response.json()["effective_from"])

    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT rate_key, inr_amount FROM platform_list_rates "
                    "WHERE effective_from = :at"
                ),
                {"at": stamped},
            )
        ).all()
    published = {row[0]: Decimal(str(row[1])) for row in rows}
    assert len(published) == len(PACK_CATALOGUE) * len(VOICE_TIERS) + 1
    expected = card_with_rates(
        {
            pack.pack_id: {
                voice: pack.inr_per_min(voice) + Decimal("0.50") for voice in VOICE_TIERS
            }
            for pack in PACK_CATALOGUE
        }
    )
    assert published[SELF_SERVE_PER_MIN] == card_list_rate(expected)
    for pack in expected:
        for voice in VOICE_TIERS:
            assert published[pack_rate_key(pack.pack_id, voice)] == pack.inr_per_min(voice)


async def test_recording_a_card_promises_one_notice_per_date() -> None:
    """The promise shares the card's transaction (BACKEND-PATTERNS §4) and is keyed on the
    DATE, so a retried outbox delivery cannot mail the whole book twice."""
    at = _later()
    response = await _post(at, _rise())
    assert response.json()["clients_notified"] is True
    stamped = response.json()["effective_from"]
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT dedupe_key FROM outbox_messages WHERE job = :job "
                    "AND payload->>'effective_from' = :at"
                ),
                {"job": RATE_CARD_NOTICE_JOB, "at": stamped},
            )
        ).all()
    assert [row[0] for row in rows] == [f"rate-card-notice:{stamped}"]


async def test_a_card_is_audited_with_the_operators_address() -> None:
    """§9's row, and `check_audit_ip`'s third property: a human actor reached us over a
    connection we can name. The card's twelve rates are in the summary that goes into the
    hash chain and the log stream; what is queryable is the row itself."""
    at = _later()
    assert (await _post(at, _rise())).status_code == 201
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT object_type, object_id, ip, actor_type FROM audit_log "
                    "WHERE action = 'platform.rate_card_recorded' ORDER BY at DESC LIMIT 1"
                )
            )
        ).first()
    assert row is not None
    assert row[0] == "platform_list_rates"
    assert datetime.fromisoformat(str(row[1])) == at
    assert row[2], "a human-actor audit row carries an address"
    assert row[3] == "admin"


# ── the refusals ─────────────────────────────────────────────────────────────────────


async def test_a_cell_below_its_voices_cost_floor_is_refused() -> None:
    below = {("starter", "sarvam"): "3.0000"}
    response = await _post(_later(), below)
    assert response.status_code == 409, response.text
    assert _code(response) == "rate_card_below_floor"
    assert "starter" in response.json()["detail"]


async def test_a_column_that_is_not_monotone_is_refused() -> None:
    """A bigger pack that buys a dearer minute is arbitrageable by buying the smaller one
    twice — invariant 6, reused from `card_refusals` rather than re-derived here."""
    dearest = max(PACK_CATALOGUE, key=lambda pack: pack.amount_inr)
    response = await _post(_later(), {(dearest.pack_id, "sarvam"): "9.0000"})
    assert response.status_code == 409, response.text
    assert "invariant 6" in response.json()["detail"]


async def test_a_missing_cell_is_refused_rather_than_defaulted() -> None:
    """A missing cell would fall back to the catalogue rate through `card_with_rates` and
    publish a price nobody typed, which is the silent version of the whole defect."""
    token = await _make_admin()
    at = _later()
    body = _body(at)
    dropped = body["cells"].pop()
    async with _client() as http:
        response = await http.post(PATH, json=body, headers=_headers(token, at))
    assert response.status_code == 422, response.text
    assert _code(response) == "rate_card_malformed"
    assert f"{dropped['pack_id']}/{dropped['voice_tier']}" in response.json()["detail"]


async def test_a_duplicated_cell_is_refused_because_there_is_no_way_to_choose() -> None:
    token = await _make_admin()
    at = _later()
    body = _body(at)
    body["cells"].append(dict(body["cells"][0], inr_per_min="7.0000"))
    async with _client() as http:
        response = await http.post(PATH, json=body, headers=_headers(token, at))
    assert response.status_code == 422, response.text
    assert "twice" in response.json()["detail"]


async def test_a_cell_this_card_does_not_have_is_refused_by_name() -> None:
    token = await _make_admin()
    at = _later()
    body = _body(at)
    body["cells"][0] = {"pack_id": "enterprise", "voice_tier": "sarvam", "inr_per_min": "5.0000"}
    async with _client() as http:
        response = await http.post(PATH, json=body, headers=_headers(token, at))
    assert response.status_code == 422, response.text
    assert "enterprise" in response.json()["detail"]


async def test_money_sent_as_a_json_number_is_refused() -> None:
    """Hard rule 7 does not stop at the database. `4.85` is an IEEE double before Pydantic
    sees it, and a card published from 4.8499999999999996 is a card nobody typed."""
    token = await _make_admin()
    at = _later()
    body = _body(at)
    body["cells"][0]["inr_per_min"] = 4.85
    async with _client() as http:
        response = await http.post(PATH, json=body, headers=_headers(token, at))
    assert response.status_code == 422, response.text
    assert "decimal string" in response.text


async def test_money_finer_than_the_column_is_refused_rather_than_rounded() -> None:
    token = await _make_admin()
    at = _later()
    body = _body(at)
    body["cells"][0]["inr_per_min"] = "5.000001"
    async with _client() as http:
        response = await http.post(PATH, json=body, headers=_headers(token, at))
    assert response.status_code == 422, response.text


async def test_money_that_is_not_a_number_at_all_is_refused() -> None:
    token = await _make_admin()
    at = _later()
    body = _body(at)
    body["cells"][0]["inr_per_min"] = "five rupees"
    async with _client() as http:
        response = await http.post(PATH, json=body, headers=_headers(token, at))
    assert response.status_code == 422, response.text


async def test_a_non_positive_rate_is_refused() -> None:
    token = await _make_admin()
    at = _later()
    body = _body(at)
    body["cells"][0]["inr_per_min"] = "0"
    async with _client() as http:
        response = await http.post(PATH, json=body, headers=_headers(token, at))
    assert response.status_code == 422, response.text


async def test_a_naive_effective_from_is_refused() -> None:
    token = await _make_admin()
    at = _later()
    body = _body(at)
    body["effective_from"] = at.replace(tzinfo=None).isoformat()
    async with _client() as http:
        response = await http.post(PATH, json=body, headers=_headers(token, at))
    assert response.status_code == 422, response.text


async def test_a_blank_reason_is_refused() -> None:
    token = await _make_admin()
    at = _later()
    body = _body(at)
    body["reason"] = "   "
    async with _client() as http:
        response = await http.post(PATH, json=body, headers=_headers(token, at))
    assert response.status_code == 422, response.text


async def test_a_second_card_at_the_same_instant_is_refused_not_overwritten() -> None:
    """Rate history is append-only: the instant is the primary key, so the second write is
    a sentence rather than an integrity error rendered as a 500."""
    at = _later()
    assert (await _post(at, _rise())).status_code == 201
    second = await _post(at, _rise("0.60"))
    assert second.status_code == 409, second.text
    assert _code(second) == "rate_card_already_scheduled"


async def test_a_write_without_the_step_up_header_is_refused() -> None:
    token = await _make_admin()
    at = _later()
    async with _client() as http:
        response = await http.post(
            PATH, json=_body(at), headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 403, response.text
    assert _code(response) == "step_up_required"
    # The refusal PRINTS the exact header to send, on purpose: the intent half is not a
    # second factor and never claimed to be one (`core/stepup.py`).
    assert rate_card_confirmation(at) in response.text


async def test_a_step_up_captured_for_another_date_does_not_work_here() -> None:
    """The confirmation is BOUND TO THE DATE: a header captured while scheduling December's
    rise must not be replayable against one that starts next week."""
    token = await _make_admin()
    at = _later()
    async with _client() as http:
        response = await http.post(
            PATH,
            json=_body(at),
            headers=_headers(token, at, confirm=rate_card_confirmation(_later(days=90))),
        )
    assert response.status_code == 403, response.text
    assert _code(response) == "step_up_required"


# ── withdrawing a scheduled card ─────────────────────────────────────────────────────


async def _cancel(at: datetime, *, confirm: str | None = None) -> Any:
    token = await _make_admin()
    headers = {"Authorization": f"Bearer {token}"}
    headers["X-Confirm-Action"] = confirm or rate_card_cancel_confirmation(at)
    async with _client() as http:
        return await http.post(
            CANCEL_PATH,
            json={"effective_from": at.isoformat(), "reason": "recorded in error"},
            headers=headers,
        )


async def test_withdrawing_a_scheduled_card_stops_it_pricing_anything_ever() -> None:
    at = _later()
    stamped = datetime.fromisoformat((await _post(at, _rise())).json()["effective_from"])
    response = await _cancel(stamped)
    assert response.status_code == 200, response.text
    assert response.json()["cancelled"] is True

    starter = min(PACK_CATALOGUE, key=lambda pack: pack.amount_inr)
    async with untenanted_session() as session:
        after = await rate_card_at(session, at=stamped + timedelta(days=365))
        still_pending = await pending_cards(session, at=datetime.now(UTC))
    assert after.of_pack(starter).sarvam_inr_per_min == starter.sarvam_inr_per_min
    assert still_pending == ()


async def test_withdrawing_deletes_nothing_because_the_history_is_append_only() -> None:
    """**THE COMPENSATING-ENTRY TEST.** Hard rule 4: the rate rows stay exactly where they
    are, and what changes is that a second row says they were withdrawn. Counting them is
    the assertion — a `DELETE` implementation would pass every other test in this file."""
    at = _later()
    stamped = datetime.fromisoformat((await _post(at, _rise())).json()["effective_from"])
    before = await _card_row_count()
    assert (await _cancel(stamped)).json()["cancelled"] is True
    assert await _card_row_count() == before
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT reason FROM platform_list_rate_cancellations WHERE effective_from = :at"
                ),
                {"at": stamped},
            )
        ).first()
    assert row is not None and row[0] == "recorded in error"


async def test_withdrawing_twice_is_a_no_op_and_audits_once() -> None:
    at = _later()
    stamped = datetime.fromisoformat((await _post(at, _rise())).json()["effective_from"])
    assert (await _cancel(stamped)).json()["cancelled"] is True
    second = await _cancel(stamped)
    assert second.status_code == 200
    assert second.json()["cancelled"] is False
    async with untenanted_session() as session:
        count = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE action = 'platform.rate_card_cancelled' "
                    "AND object_id = :at"
                ),
                {"at": stamped.isoformat()},
            )
        ).scalar_one()
    assert int(count) == 1


async def test_a_withdrawal_with_a_naive_date_is_refused() -> None:
    """The cancel body carries the instant the read printed, offset and all. A bare one
    would be read in the server's timezone and could name a different card."""
    token = await _make_admin()
    at = _later()
    async with _client() as http:
        response = await http.post(
            CANCEL_PATH,
            json={"effective_from": at.replace(tzinfo=None).isoformat(), "reason": "wrong card"},
            headers={
                "Authorization": f"Bearer {token}",
                "X-Confirm-Action": rate_card_cancel_confirmation(at),
            },
        )
    assert response.status_code == 422, response.text


async def test_a_withdrawal_with_a_blank_reason_is_refused() -> None:
    """`platform_list_rate_cancellations.reason` is NOT NULL for the rate table's reason: a
    pricing act with no stated ground cannot be audited afterwards."""
    token = await _make_admin()
    at = _later()
    async with _client() as http:
        response = await http.post(
            CANCEL_PATH,
            json={"effective_from": at.isoformat(), "reason": "   "},
            headers={
                "Authorization": f"Bearer {token}",
                "X-Confirm-Action": rate_card_cancel_confirmation(at),
            },
        )
    assert response.status_code == 422, response.text


async def test_withdrawing_a_card_nobody_scheduled_is_a_404() -> None:
    response = await _cancel(_later(days=200))
    assert response.status_code == 404, response.text
    assert _code(response) == "rate_card_not_scheduled"


async def test_a_card_already_in_force_cannot_be_withdrawn() -> None:
    """Unwinding it would restate lots that are already frozen at its rates — the one thing
    this whole module exists to prevent."""
    admin = await _make_admin()
    actor = UUID(admin.rsplit(":", 1)[1])
    past = datetime.now(UTC) - timedelta(days=1)
    async with untenanted_session() as session:
        await record_card(
            session,
            effective_from=past,
            self_serve_inr_per_min=Decimal("5.0000"),
            recorded_by=actor,
            note="already in force",
        )
    response = await _cancel(past)
    assert response.status_code == 409, response.text
    assert _code(response) == "rate_card_already_in_force"


async def test_the_database_refuses_a_past_withdrawal_even_without_the_route() -> None:
    """The route's check has a better sentence; this is the copy no second writer can route
    around. `cancel_card` returns False rather than writing a row."""
    admin = await _make_admin()
    actor = UUID(admin.rsplit(":", 1)[1])
    past = datetime.now(UTC) - timedelta(days=1)
    async with untenanted_session() as session:
        await record_card(
            session,
            effective_from=past,
            self_serve_inr_per_min=Decimal("5.0000"),
            recorded_by=actor,
            note="already in force",
        )
    async with untenanted_session() as session:
        assert (
            await cancel_card(session, effective_from=past, cancelled_by=actor, reason="too late")
            is False
        )


def _anonymous_operator() -> Principal:
    """An admin-realm principal carrying no `admin_users` row — the shape a session has
    while its mirror row has not landed. Reached through the ROUTE FUNCTION rather than
    over HTTP, deliberately: the auth dependency will not mint one, which is exactly why
    the handler's guard is invisible to every request-level test in this file.
    `platform_list_rates.recorded_by` is NOT NULL, so the guard is what turns this into a
    sentence rather than an integrity error rendered as a 500."""
    return Principal(realm="admin", user_id=None, tenant_id=None, role=None)


def _bare_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": PATH,
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 1234),
        }
    )


async def test_a_card_from_a_session_with_no_admin_identity_is_refused() -> None:
    at = _later()
    before = await _card_row_count()
    async with untenanted_session() as session:
        with pytest.raises(ProblemError) as raised:
            await record_rate_card(
                RateCardIn.model_validate(_body(at)),
                session,
                _bare_request(),
                _anonymous_operator(),
                StepUp(present=False, verified_at=None),
                x_confirm_action=rate_card_confirmation(at),
            )
    assert raised.value.code == "config_actor_unknown"
    assert await _card_row_count() == before


async def test_a_withdrawal_from_a_session_with_no_admin_identity_is_refused() -> None:
    at = _later()
    stamped = datetime.fromisoformat((await _post(at, _rise())).json()["effective_from"])
    async with untenanted_session() as session:
        with pytest.raises(ProblemError) as raised:
            await cancel_rate_card(
                RateCardCancelIn(effective_from=stamped, reason="recorded in error"),
                session,
                _bare_request(),
                _anonymous_operator(),
                StepUp(present=False, verified_at=None),
                x_confirm_action=rate_card_cancel_confirmation(stamped),
            )
    assert raised.value.code == "config_actor_unknown"


# ── the read the console builds against ──────────────────────────────────────────────


async def test_the_rate_card_read_lists_pending_cards_and_the_earliest_date() -> None:
    at = _later()
    stamped = (await _post(at, _rise())).json()["effective_from"]
    token = await _make_admin()
    async with _client() as http:
        response = await http.get(PATH, headers={"Authorization": f"Bearer {token}"})
    body = response.json()
    assert body["notice_days"] == CARD_NOTICE_DAYS
    assert datetime.fromisoformat(body["earliest_effective_from"]) > datetime.now(UTC)
    assert [card["effective_from"] for card in body["pending"]] == [stamped]
    starter = min(PACK_CATALOGUE, key=lambda pack: pack.amount_inr)
    # The card in force is unchanged; the pending one carries the new rates.
    in_force = {(c["pack_id"], c["voice_tier"]): c["inr_per_min"] for c in body["cells"]}
    pending = {
        (c["pack_id"], c["voice_tier"]): c["inr_per_min"] for c in body["pending"][0]["cells"]
    }
    assert Decimal(in_force[(starter.pack_id, "sarvam")]) == starter.sarvam_inr_per_min
    assert Decimal(pending[(starter.pack_id, "sarvam")]) == starter.sarvam_inr_per_min + Decimal(
        "0.50"
    )


async def test_the_client_facing_pack_card_publishes_the_next_change_before_it_lands() -> None:
    """E: a client whose next top-up will cost more can see that in the console before the
    day arrives, from the same two functions the ops console reads."""
    at = _later()
    stamped = (await _post(at, _rise())).json()["effective_from"]
    from apps.api.billing.payment_routes import rate_card_out

    async with untenanted_session() as session:
        card = await rate_card_out(session)
    starter = min(PACK_CATALOGUE, key=lambda pack: pack.amount_inr)
    assert card.list_rate_inr_per_min == starter.sarvam_inr_per_min
    assert card.next_change is not None
    assert card.next_change.effective_from == stamped
    changed = {pack.pack_id: pack for pack in card.next_change.packs}
    assert changed[starter.pack_id].sarvam_inr_per_min == starter.sarvam_inr_per_min + Decimal(
        "0.50"
    )


async def test_the_client_facing_card_has_no_next_change_when_none_is_scheduled() -> None:
    from apps.api.billing.payment_routes import rate_card_out

    async with untenanted_session() as session:
        card = await rate_card_out(session)
    assert card.next_change is None


# ── the helpers, at their edges ──────────────────────────────────────────────────────


def test_a_card_built_from_partial_cells_keeps_the_catalogue_rate_for_the_rest() -> None:
    """`card_at`'s per-cell fallback reason, one layer up: the only other reading silently
    DROPS a rung, and a dropped rung is a purchase nobody can price."""
    starter = min(PACK_CATALOGUE, key=lambda pack: pack.amount_inr)
    partial = card_with_rates({starter.pack_id: {"sarvam": Decimal("6.0000")}})
    built = {pack.pack_id: pack for pack in partial}
    assert built[starter.pack_id].sarvam_inr_per_min == Decimal("6.0000")
    assert built[starter.pack_id].cartesia_inr_per_min == starter.cartesia_inr_per_min
    assert len(built) == len(PACK_CATALOGUE)


def test_the_list_rate_is_the_entry_rungs_sarvam_rate() -> None:
    starter = min(PACK_CATALOGUE, key=lambda pack: pack.amount_inr)
    assert card_list_rate(PACK_CATALOGUE) == starter.sarvam_inr_per_min


async def test_pending_cards_are_soonest_first_and_bounded_to_aware_instants() -> None:
    admin = await _make_admin()
    actor = UUID(admin.rsplit(":", 1)[1])
    near, far = _later(days=40), _later(days=80)
    async with untenanted_session() as session:
        for at in (far, near):
            await record_card(
                session,
                effective_from=at,
                self_serve_inr_per_min=Decimal("5.0000"),
                recorded_by=actor,
                note="scheduled",
            )
    async with untenanted_session() as session:
        listed = await pending_cards(session, at=datetime.now(UTC))
        with pytest.raises(ValueError, match="aware instant"):
            await pending_cards(session, at=datetime(2026, 12, 1))
    assert [card.effective_from for card in listed] == [near, far]


async def test_card_is_scheduled_answers_false_for_an_instant_nobody_recorded() -> None:
    async with untenanted_session() as session:
        assert await card_is_scheduled(session, effective_from=_later()) is False
        with pytest.raises(ValueError, match="aware instant"):
            await card_is_scheduled(session, effective_from=datetime(2026, 12, 1))


async def test_the_writers_refuse_a_naive_instant() -> None:
    admin = await _make_admin()
    actor = UUID(admin.rsplit(":", 1)[1])
    async with untenanted_session() as session:
        with pytest.raises(ValueError, match="aware instant"):
            await record_card(
                session,
                effective_from=datetime(2026, 12, 1),
                self_serve_inr_per_min=Decimal("5.0000"),
                recorded_by=actor,
                note="naive",
            )
        with pytest.raises(ValueError, match="aware instant"):
            await cancel_card(
                session, effective_from=datetime(2026, 12, 1), cancelled_by=actor, reason="naive"
            )


async def test_a_withdrawn_card_is_invisible_to_the_legacy_rate_reader_too() -> None:
    """`self_serve_rate_at` shares the resolution rule and must share the exclusion: a
    withdrawn card that still moved the legacy list rate would re-price a closed month from
    a card that never took effect."""
    from apps.api.billing.list_rates import self_serve_rate_at

    admin = await _make_admin()
    actor = UUID(admin.rsplit(":", 1)[1])
    at = _later()
    async with untenanted_session() as session:
        await record_card(
            session,
            effective_from=at,
            self_serve_inr_per_min=Decimal("9.9900"),
            recorded_by=actor,
            note="withdrawn later",
        )
    async with untenanted_session() as session:
        assert await self_serve_rate_at(session, at=at + timedelta(seconds=1)) == Decimal("9.9900")
        assert await cancel_card(session, effective_from=at, cancelled_by=actor, reason="withdrawn")
    async with untenanted_session() as session:
        assert await self_serve_rate_at(session, at=at + timedelta(seconds=1)) != Decimal("9.9900")


async def test_a_withdrawn_card_no_longer_dates_the_console_panel() -> None:
    """`_CARD_EFFECTIVE_FROM` carries the exclusion too — a panel dated by a card nobody
    ever priced with is a panel that reads as authoritative and is not."""
    admin = await _make_admin()
    actor = UUID(admin.rsplit(":", 1)[1])
    past = datetime.now(UTC) - timedelta(days=2)
    async with untenanted_session() as session:
        await record_card(
            session,
            effective_from=past,
            self_serve_inr_per_min=Decimal("5.0000"),
            recorded_by=actor,
            note="in force",
        )
        # Written straight to the table: the route refuses a past withdrawal, and what is
        # under test here is the READER's exclusion rather than the route's rule.
        await session.execute(
            text(
                "INSERT INTO platform_list_rate_cancellations "
                "(effective_from, cancelled_by, reason) VALUES (:at, :by, 'seeded')"
            ),
            {"at": past, "by": actor},
        )
    token = await _make_admin()
    async with _client() as http:
        response = await http.get(PATH, headers={"Authorization": f"Bearer {token}"})
    assert response.json()["effective_from"] is None
