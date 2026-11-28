"""Alerts you can shape (D-1048): the alert table, quiet hours, the daily cap, the bell's own
sources, the campaign-finished alert, the morning summary and the "message left" kind.

1. The two new tables are tenant data: another account's session reads zero rows (hard rule 1).
2. An always-on cell refuses an API write; an unknown cell is refused; a non-owner cannot change
   the account email, WhatsApp, quiet hours or cap.
3. A hot lead at 23:00 IST with quiet hours on is held and goes out at 08:00 IST in one message.
4. The 13th email of an IST day is folded and goes out with the others as one "and N more".
5. A retried job gets the gate's first answer.
6. The bell shows posted items and hides a row its reader switched off.
7. A finished campaign posts one bell item and one email, figures from its results.
8. The morning summary claims the day before and says "yesterday".
9. A "needs you" call with no call-back request is a message for the owner.

CONCURRENCY: every test makes its own tenant.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from apps.api.billing.plans import IST
from apps.api.db.session import tenant_session
from apps.api.inbound import today as inbound_today
from apps.api.main import app
from apps.api.notifications import campaign_finished, daily_summary, preferences, service
from apps.workers import notifications, owner_digest
from sqlalchemy import text
from tests.api_security_test import _make_tenant


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api")


def _ist(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=IST).astimezone(UTC)


class _Sent:
    def __init__(self) -> None:
        self.mails: list[dict[str, Any]] = []

    def send(self, **kwargs: Any) -> bool:
        self.mails.append(kwargs)
        return True


async def _owner(tenant_id: UUID) -> UUID:
    async with tenant_session(tenant_id) as session:
        value = (
            await session.execute(text("SELECT user_id FROM memberships WHERE role = 'owner'"))
        ).scalar_one()
    return UUID(str(value))


async def _save(tenant_id: UUID, **fields: Any) -> preferences.AlertPreferencesOut:
    user = await _owner(tenant_id)
    async with tenant_session(tenant_id) as session:
        return await preferences.save(
            session,
            tenant_id=tenant_id,
            user_id=user,
            may_manage=True,
            payload=preferences.AlertPreferencesIn(**fields),
        )


async def _gate(tenant_id: UUID, key: str, at: datetime, kind: str = "hot_lead") -> str:
    async with tenant_session(tenant_id) as session:
        return await preferences.gate(
            session,
            tenant_id=tenant_id,
            kind=kind,
            channel="email",
            dedupe_key=key,
            title=f"Alert {key}",
            href="/leads",
            now=at,
        )


async def test_both_tables_read_zero_rows_from_another_account() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    other_id, _other_slug, _other_token = await _make_tenant()
    await _save(tenant_id, off=["milestone:bell"])
    assert await _gate(tenant_id, "rls", datetime.now(UTC)) == "send"
    for table in ("notification_preferences", "notification_deliveries"):
        async with tenant_session(other_id) as session:
            assert (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar() == 0
        async with tenant_session(tenant_id) as session:
            assert (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar() == 1


async def test_the_api_refuses_an_always_on_cell_and_an_unknown_one() -> None:
    _tenant_id, _slug, token = await _make_tenant()
    headers = {"Authorization": f"Bearer {token}"}
    async with _client() as http:
        shown = await http.get("/v1/notifications/preferences", headers=headers)
        assert shown.status_code == 200, shown.text
        body = shown.json()
        assert body["governs_account"] is True and body["account_editable"] is True
        credit = next(k for k in body["kinds"] if k["key"] == "credit_low")
        assert credit["always"] is True and credit["cells"]["email"] == "always"
        assert credit["cells"]["whatsapp"] == "none"

        always = await http.put(
            "/v1/notifications/preferences", headers=headers, json={"off": ["credit_low:email"]}
        )
        assert always.status_code == 422, always.text
        assert always.json()["type"].endswith("/alert_always_on")
        unknown = await http.put(
            "/v1/notifications/preferences", headers=headers, json={"off": ["hot_lead:fax"]}
        )
        assert unknown.status_code == 422
        assert unknown.json()["type"].endswith("/alert_cell_unknown")

        saved = await http.put(
            "/v1/notifications/preferences",
            headers=headers,
            json={"off": ["hot_lead:email"], "quiet_enabled": True, "daily_cap": 5},
        )
        assert saved.status_code == 200, saved.text
        hot = next(k for k in saved.json()["kinds"] if k["key"] == "hot_lead")
        assert hot["cells"] == {"bell": "on", "computer": "on", "email": "off", "whatsapp": "on"}
        assert saved.json()["daily_cap"] == 5


async def test_only_the_governing_owner_changes_the_account_cells() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    staff = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:id, :e, now(), now())"
            ),
            {"id": staff, "e": f"{staff}@example.com"},
        )
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, 'staff', now() + interval '1 second', now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": staff},
        )
    async with tenant_session(tenant_id) as session:
        mine = await preferences.save(
            session,
            tenant_id=tenant_id,
            user_id=staff,
            may_manage=False,
            payload=preferences.AlertPreferencesIn(off=["milestone:bell"]),
        )
        assert mine.governs_account is False and mine.account_editable is False
        with pytest.raises(Exception) as refused:
            await preferences.save(
                session,
                tenant_id=tenant_id,
                user_id=staff,
                may_manage=False,
                payload=preferences.AlertPreferencesIn(off=["hot_lead:email"]),
            )
    assert getattr(refused.value, "code", None) == "alert_owner_only"


async def test_a_hot_lead_at_23_ist_is_held_and_released_at_08(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _slug, _token = await _make_tenant()
    await _save(tenant_id, quiet_enabled=True)
    day = date(2026, 11, 20)
    assert await _gate(tenant_id, "night", _ist(day, 23)) == "held"
    assert await _gate(tenant_id, "night", _ist(day, 23, 5)) == "held"  # a retry: same answer
    async with tenant_session(tenant_id) as session:
        due = (
            await session.execute(
                text("SELECT due_at FROM notification_deliveries WHERE dedupe_key = 'night'")
            )
        ).scalar_one()
    assert due == _ist(day + timedelta(days=1), 8)

    sent = _Sent()
    monkeypatch.setattr(notifications, "get_transport", lambda _purpose: sent)
    assert await notifications.release_one(tenant_id, now=_ist(day + timedelta(days=1), 7)) == (
        "still_quiet"
    )
    assert sent.mails == []
    out = await notifications.release_one(tenant_id, now=_ist(day + timedelta(days=1), 8, 1))
    assert out == "released"
    assert len(sent.mails) == 1  # the owner's address: one message
    assert sent.mails[0]["subject"] == "While you were away: 1 alert"
    assert "Alert night" in sent.mails[0]["body"]
    assert await _gate(tenant_id, "night", _ist(day + timedelta(days=1), 9)) == "released"


async def test_the_thirteenth_email_of_a_day_is_folded(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, _slug, _token = await _make_tenant()
    noon = _ist(date(2026, 11, 21), 12)
    answers = [await _gate(tenant_id, f"busy-{n}", noon + timedelta(minutes=n)) for n in range(14)]
    assert answers[:12] == ["send"] * 12
    assert answers[12:] == ["folded", "folded"]
    sent = _Sent()
    monkeypatch.setattr(notifications, "get_transport", lambda _purpose: sent)
    assert await notifications.release_one(tenant_id, now=noon + timedelta(hours=1)) == (
        "nothing_due"
    )
    assert await notifications.release_one(tenant_id, now=noon + timedelta(hours=13)) == (
        "released"
    )
    assert len(sent.mails) == 1
    assert sent.mails[0]["subject"] == "2 more alerts from today"


def test_the_digest_names_ten_and_counts_the_rest() -> None:
    email = notifications.compose_digest(
        [("Kind", f"Item {n}") for n in range(13)], held=0, folded=13, slug="acme"
    )
    assert "Item 9" in email.text and "Item 10" not in email.text
    assert "And 3 more." in email.text


async def test_an_always_on_kind_is_never_held() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    await _save(tenant_id, quiet_enabled=True)
    assert await _gate(tenant_id, "money", _ist(date(2026, 11, 20), 23), "credit_low") == "send"


async def test_a_switched_off_cell_sends_nothing() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    await _save(tenant_id, off=["campaign_finished:email"])
    assert await _gate(tenant_id, "c", datetime.now(UTC), "campaign_finished") == "off"


async def test_the_bell_shows_posted_items_unless_its_reader_switched_them_off() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    user = await _owner(tenant_id)
    async with tenant_session(tenant_id) as session:
        assert await preferences.post_bell(
            session, tenant_id=tenant_id, kind="campaign_finished", dedupe_key="b1", title="Done"
        )
        assert not await preferences.post_bell(
            session, tenant_id=tenant_id, kind="campaign_finished", dedupe_key="b1", title="Done"
        )
        shown = await service.feed(session, tenant_id=tenant_id, user_id=user, limit=30)
    assert [n.title for n in shown.items if n.source == "posted"] == ["Done"]
    await _save(tenant_id, off=["campaign_finished:bell"])
    async with tenant_session(tenant_id) as session:
        hidden = await service.feed(session, tenant_id=tenant_id, user_id=user, limit=30)
    assert [n for n in hidden.items if n.source == "posted"] == []


async def test_a_finished_campaign_posts_one_bell_item_and_one_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _slug, _token = await _make_tenant()
    campaign_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar_one()
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, classification, status, "
                "concurrency, created_at, updated_at) VALUES (:i, :t, :a, 'Diwali offer', "
                "'service', 'completed', 3, now(), now())"
            ),
            {"i": campaign_id, "t": tenant_id, "a": agent_id},
        )
        await session.execute(
            text("UPDATE organizations SET billing_email = :e"),
            {"e": f"{tenant_id.hex[:8]}@example.com"},
        )
        assert await campaign_finished.queue(session, tenant_id=tenant_id, campaign_id=campaign_id)
        assert not await campaign_finished.queue(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
        finished = (
            await session.execute(
                text("SELECT updated_at FROM campaigns WHERE id = :i"), {"i": campaign_id}
            )
        ).scalar_one()
    sent = _Sent()
    monkeypatch.setattr(notifications, "get_transport", lambda _purpose: sent)
    payload = {
        "tenant_id": str(tenant_id),
        "campaign_id": str(campaign_id),
        "finished_at": finished.isoformat(),
    }
    assert await notifications.notify_campaign_finished({"job_try": 1}, payload) == "sent"
    assert await notifications.notify_campaign_finished({"job_try": 1}, payload) == "sent"
    async with tenant_session(tenant_id) as session:
        bell = (
            (
                await session.execute(
                    text("SELECT title FROM notification_deliveries WHERE channel = 'bell'")
                )
            )
            .scalars()
            .all()
        )
    assert bell == [
        "Diwali offer finished: 0 people called, 0 interested callers, 0 call-backs asked for."
    ]
    assert sent.mails and "+91" not in sent.mails[0]["body"]


async def test_the_morning_summary_claims_yesterday_and_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _slug, _token = await _make_tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(text("UPDATE organizations SET owner_digest_enabled = true"))
        assert await daily_summary.write_slot(session, slot="morning")
        assert not await daily_summary.write_slot(session, slot="morning")
        assert await daily_summary.read_slot(session) == "morning"
    sent = _Sent()
    monkeypatch.setattr(owner_digest, "get_transport", lambda _purpose: sent)
    yesterday = datetime.now(UTC).astimezone(IST).date() - timedelta(days=1)
    # The evening run does not claim an account that chose the morning.
    assert await owner_digest.send_one(tenant_id, day=yesterday) == "not_claimed"
    outcome = await owner_digest.send_one(tenant_id, day=yesterday, slot="morning")
    assert outcome in {"sent", "quiet"}
    assert await owner_digest.send_one(tenant_id, day=yesterday, slot="morning") == "not_claimed"
    async with tenant_session(tenant_id) as session:
        summary = await daily_summary.build_summary(
            session, tenant_id=tenant_id, day=yesterday, slot="morning"
        )
    assert daily_summary.email_subject(summary).startswith("Yesterday:")
    assert "missed yesterday." in daily_summary.email_lines(summary)[0]


def test_a_needs_you_call_with_no_call_back_asked_is_a_message() -> None:
    assert inbound_today._reason("completed", "needs_you", False) == "message"
    assert inbound_today._reason("completed", "needs_you", True) == "asked"
    assert inbound_today._reason("completed", "call_back_booked", None) == "asked"
    assert inbound_today._reason("no_answer", None, None) == "not_answered"


def test_quiet_hours_wrap_midnight() -> None:
    prefs = preferences.Preferences(quiet_enabled=True)
    day = date(2026, 11, 20)
    assert prefs.quiet_at(_ist(day, 22)) and prefs.quiet_at(_ist(day, 3))
    assert not prefs.quiet_at(_ist(day, 8)) and not prefs.quiet_at(_ist(day, 20, 59))
    daytime = preferences.Preferences(quiet_enabled=True, quiet_start_hour=13, quiet_end_hour=15)
    assert daytime.quiet_at(_ist(day, 14)) and not daytime.quiet_at(_ist(day, 15))
    assert daytime.quiet_ends(_ist(day, 14)) == _ist(day, 15)
