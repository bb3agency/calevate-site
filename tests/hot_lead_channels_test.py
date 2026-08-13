"""The two hot-lead channels, wired together and kept apart.

FLOWS §6 is one sentence — "status hot OR urgency=emergency ⇒ WhatsApp+email to owner
within 2 min" — and it shipped as two halves that could not both be true:

1. **Nothing called the WhatsApp leg.** `whatsapp.enqueue_hot_lead_whatsapp` existed,
   `notify_hot_lead_whatsapp` was registered with a worker, and no production code path
   ever enqueued it. Finishing the WABA/BSP/template checklist would still have
   delivered zero WhatsApp alerts, because the last inch was missing.
2. **The email side's guards had no channel predicate** while the WhatsApp side's did.
   Wired naively, that is a regression: a delivered WhatsApp row makes the email job
   report `duplicate` without sending, and the email record's UPDATE overwrites the
   WhatsApp row on the same lead+call.

So the properties here are the seam AND the separation:

* the email job queues the WhatsApp leg, in its own transaction, once per lead+call,
  and **whether or not the email itself landed** — WhatsApp is not a fallback for a
  broken mailer, and a lead is "notified" per channel, never on the strength of the
  other one;
* neither channel's row can answer for, satisfy, or overwrite the other's. Every test
  in that section records **both** channels on ONE lead, because a fixture that only
  ever exercises one channel makes the channel predicate unique by construction and
  proves nothing;
* a deployment with no BSP — which is every deployment today — still refuses honestly,
  records the refusal on the lead timeline, and does not raise;
* hard rule 6 survives the new call path.

CONCURRENCY: every test creates its own run-unique tenant and touches no global row, so
this file runs beside the other suites on the same Postgres.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.core.logging import JsonFormatter
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session
from apps.workers import notifications, whatsapp
from arq import Retry
from sqlalchemy import text

# The owner's WhatsApp destination. A documented test number, never a subscriber; it
# exists so the hard-rule-6 test has something to search the log output FOR.
OWNER_TEST_E164 = "+919000000001"
# The CALLER's number, seeded on the call and the lead the same way every other suite
# seeds one. The email body masks it; nothing may log it.
CALLER_TEST_E164 = "+919876500111"


# --------------------------------------------------------------------------------
# Seeding
# --------------------------------------------------------------------------------


async def _hot_lead(
    prefix: str, *, billing_email: str | None = "owner@example.test"
) -> dict[str, Any]:
    created = await admin_service.create_organization(
        name=f"{prefix.title()} Clinic",
        slug=f"hlc-{prefix}-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=billing_email,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = UUID(str(created["id"])), UUID(str(created["agent_id"]))
    call_id, lead_id = uuid.uuid4(), uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "from_e164, to_e164, started_at, ended_at, duration_s, summary, created_at, "
                "updated_at) VALUES (:id, :tid, :aid, :ecid, 'inbound', 'completed', :from_e164, "
                "'+911140000000', now() - make_interval(mins => 2), "
                "now() - make_interval(mins => 2), 95, 'Wants an appointment today', now(), now())"
            ),
            {
                "id": call_id,
                "tid": tenant_id,
                "aid": agent_id,
                "ecid": f"exec_{call_id.hex[:12]}",
                "from_e164": CALLER_TEST_E164,
            },
        )
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status, "
                "data, schema_version, first_call_id, last_call_id, call_count, "
                "is_repeat_caller, created_at, updated_at) VALUES (:id, :tid, :aid, :phone, "
                "'Ravi', 'inbound_call', 'hot', '{}'::jsonb, 1, :cid, :cid, 1, false, now(), now())"
            ),
            {
                "id": lead_id,
                "tid": tenant_id,
                "aid": agent_id,
                "cid": call_id,
                "phone": CALLER_TEST_E164,
            },
        )
    return {
        "tenant_id": str(tenant_id),
        "lead_id": str(lead_id),
        "call_id": str(call_id),
        "triggers": ["urgency"],
    }


async def _add_owner_with_phone(tenant_id: UUID, phone: str) -> None:
    """`users` is global identity (no RLS); `memberships` is tenant-scoped. This is the
    data `whatsapp.resolve_destination` reads for real."""
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, clerk_user_id, email, name, phone, created_at, "
                "updated_at) VALUES (:id, :clerk, :email, 'Owner', :phone, now(), now())"
            ),
            {
                "id": user_id,
                "clerk": f"user_{uuid.uuid4().hex[:16]}",
                "email": f"owner-{uuid.uuid4().hex[:8]}@example.test",
                "phone": phone,
            },
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, 'owner', now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id},
        )


class _EmailTransport:
    """Counts attempts so "did it try again?" is answerable."""

    name = "test"

    def __init__(self, delivered: bool) -> None:
        self.delivered = delivered
        self.attempts = 0

    def send(self, *, to: str, subject: str, body: str) -> bool:
        self.attempts += 1
        return self.delivered


class _WhatsAppTransport:
    name = "test"

    def __init__(self, result: whatsapp.SendResult) -> None:
        self.result = result
        self.attempts = 0

    def send(self, message: whatsapp.WhatsAppMessage) -> whatsapp.SendResult:
        self.attempts += 1
        return self.result


def _email(monkeypatch: pytest.MonkeyPatch, *, delivered: bool = True) -> _EmailTransport:
    transport = _EmailTransport(delivered=delivered)
    monkeypatch.setattr(notifications, "get_transport", lambda: transport)
    return transport


def _channel_on(monkeypatch: pytest.MonkeyPatch, *, on: bool = True) -> None:
    monkeypatch.setattr(get_settings(), "whatsapp_enabled", on)


def _opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stand in for the opt-in column `whatsapp.resolve_destination` documents and this
    milestone does not ship. Patched rather than configured: an opt-in is not something
    a setting may assert on a client's behalf."""
    from datetime import UTC, datetime

    async def _opted_in(session: Any, tenant_id: UUID) -> whatsapp.Destination:
        return whatsapp.Destination(to_e164=OWNER_TEST_E164, opt_in_at=datetime.now(UTC))

    monkeypatch.setattr(whatsapp, "resolve_destination", _opted_in)


def _capture_alerts(monkeypatch: pytest.MonkeyPatch, module: Any) -> list[tuple[str, str, Any]]:
    fired: list[tuple[str, str, Any]] = []

    def _record(stage: str, code: str, **kwargs: Any) -> None:
        fired.append((stage, code, kwargs.get("detail")))

    monkeypatch.setattr(module, "alert", _record)
    return fired


async def _events(payload: dict[str, Any], *, channel: str | None = None) -> list[dict[str, Any]]:
    """Every notification row on this lead, unfiltered by channel unless asked — the
    channel is read back from the payload rather than selected on, so a row written
    under the WRONG channel shows up here instead of vanishing from the assertion."""
    async with tenant_session(UUID(payload["tenant_id"])) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT payload FROM lead_events WHERE lead_id = :lid "
                    "AND type = 'notification' ORDER BY created_at"
                ),
                {"lid": UUID(payload["lead_id"])},
            )
        ).all()
    events = [dict(row[0]) for row in rows]
    return [e for e in events if channel is None or e.get("channel") == channel]


async def _queued_whatsapp_payloads(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """The outbox rows the wiring wrote — the queue's own record of the promise."""
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT payload FROM outbox_messages WHERE job = :job "
                    "AND payload->>'lead_id' = :lid ORDER BY created_at"
                ),
                {"job": whatsapp.JOB_NAME, "lid": payload["lead_id"]},
            )
        ).all()
    return [dict(row[0]) for row in rows]


# --------------------------------------------------------------------------------
# 1. The wiring: the email job is what puts the WhatsApp leg on the queue
# --------------------------------------------------------------------------------


async def test_the_email_job_queues_the_whatsapp_leg(monkeypatch: pytest.MonkeyPatch) -> None:
    """Half A. Without this call the whole WhatsApp feature is unreachable: the job is
    registered, the transport seam is built, the delivery record is written — and
    nothing ever enqueues it, so completing the BSP checklist would deliver nothing.

    The payload is asserted key by key because it is a CONTRACT with
    `notify_hot_lead_whatsapp`, which reads all four fields.
    """
    payload = await _hot_lead("wired")
    _channel_on(monkeypatch)
    _email(monkeypatch, delivered=True)

    assert await notifications.notify_hot_lead({"job_try": 1}, payload) == "sent"

    queued = await _queued_whatsapp_payloads(payload)
    assert len(queued) == 1, "the hot-lead email must put its WhatsApp twin on the queue"
    assert queued[0] == {
        "tenant_id": payload["tenant_id"],
        "lead_id": payload["lead_id"],
        "call_id": payload["call_id"],
        "triggers": ["urgency"],
    }


async def test_the_queued_payload_is_one_the_whatsapp_job_can_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The seam, end to end: what the email job enqueues is fed straight back into the
    job that dequeues it. A wiring test that only counts rows would still pass if the
    two sides disagreed about a key name."""
    payload = await _hot_lead("endtoend")
    _channel_on(monkeypatch)
    _email(monkeypatch, delivered=True)
    await notifications.notify_hot_lead({"job_try": 1}, payload)

    _opt_in(monkeypatch)
    sink = _WhatsAppTransport(whatsapp.SendResult(whatsapp.SendStatus.DELIVERED))
    monkeypatch.setattr(whatsapp, "get_whatsapp_transport", lambda: sink)

    queued = (await _queued_whatsapp_payloads(payload))[0]
    assert await whatsapp.notify_hot_lead_whatsapp({"job_try": 1}, queued) == "sent"
    assert sink.attempts == 1

    whatsapp_rows = await _events(payload, channel="whatsapp")
    assert len(whatsapp_rows) == 1 and whatsapp_rows[0]["delivered"] is True
    assert whatsapp_rows[0]["triggers"] == ["urgency"], "the WHY reached the template"


async def test_the_whatsapp_leg_is_queued_even_when_the_email_never_lands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The partial-delivery decision, pinned. WhatsApp is not a fallback for a broken
    mailer and not a reward for a working one: it is the other half of one sentence in
    FLOWS §6, so it is queued whatever the email did. Gating it on `delivered` would
    let one dead transport silence both channels — the exact silence this feature
    exists to prevent."""
    payload = await _hot_lead("email-down")
    _channel_on(monkeypatch)
    _email(monkeypatch, delivered=False)

    with pytest.raises(Retry):
        await notifications.notify_hot_lead({"job_try": 1}, payload)

    assert len(await _queued_whatsapp_payloads(payload)) == 1


async def test_the_email_ladder_does_not_queue_a_second_whatsapp_alert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The email job is retried with the same payload; the client must be pinged once.
    The outbox row is what says so — it is never deleted from, so it is a durable
    answer to "did a previous attempt already promise this?"."""
    payload = await _hot_lead("ladder")
    _channel_on(monkeypatch)
    _email(monkeypatch, delivered=False)

    for attempt in (1, 2):
        with pytest.raises(Retry):
            await notifications.notify_hot_lead({"job_try": attempt}, payload)

    assert len(await _queued_whatsapp_payloads(payload)) == 1


async def test_the_channel_being_off_queues_nothing_and_costs_the_email_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The state every deployment is in today. The wiring lands before the BSP does, so
    "off" has to be a no-op the email path cannot feel: no outbox row, no timeline row,
    no alert, and the email still sent."""
    payload = await _hot_lead("off")
    _channel_on(monkeypatch, on=False)
    email = _email(monkeypatch, delivered=True)
    fired = _capture_alerts(monkeypatch, notifications)

    assert await notifications.notify_hot_lead({"job_try": 1}, payload) == "sent"

    assert email.attempts == 1
    assert await _queued_whatsapp_payloads(payload) == []
    assert [row["channel"] for row in await _events(payload)] == ["email"]
    assert fired == []


# --------------------------------------------------------------------------------
# 2. The channels cannot answer for each other
#
# Every test below records BOTH channels on ONE lead. A fixture that exercises a single
# channel makes `payload->>'channel'` unique by construction, so it would pass with the
# predicate deleted — which is the state this defect actually shipped in.
# --------------------------------------------------------------------------------


async def _record_whatsapp_attempt(
    payload: dict[str, Any], *, delivered: bool, reason: str
) -> None:
    """A WhatsApp row for this lead+call, written by the WhatsApp module's own recorder
    rather than by hand — the point is to collide with the real shape, not with a shape
    this test invented."""
    async with tenant_session(UUID(payload["tenant_id"])) as session:
        status = whatsapp.SendStatus.DELIVERED if delivered else whatsapp.SendStatus.REJECTED
        await whatsapp._record_attempt(
            session,
            tenant_id=UUID(payload["tenant_id"]),
            lead_id=UUID(payload["lead_id"]),
            call_id=UUID(payload["call_id"]),
            result=whatsapp.SendResult(status, reason=reason),
            attempts=1,
            triggers=["urgency"],
            template="calevate_hot_lead_v1",
        )


async def test_a_delivered_whatsapp_alert_does_not_satisfy_the_email_dedupe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Half B, first direction. `whatsapp._already_delivered` filters on `channel` and
    says in its docstring that "a recorded WhatsApp attempt must not satisfy the email
    dedupe" — the email side is what has to hold up its end.

    Unfixed, this returns `duplicate` having sent nothing: the client with a working
    WhatsApp alert silently stops receiving hot-lead email, and the timeline reads as
    if both landed.
    """
    payload = await _hot_lead("wa-first")
    await _record_whatsapp_attempt(payload, delivered=True, reason="")
    email = _email(monkeypatch, delivered=True)
    _channel_on(monkeypatch, on=False)  # only the pre-existing WhatsApp row is in play

    assert await notifications.notify_hot_lead({"job_try": 1}, payload) == "sent"

    assert email.attempts == 1, "a delivered WhatsApp row must not mark the email done"
    by_channel = {row["channel"]: row for row in await _events(payload)}
    assert set(by_channel) == {"email", "whatsapp"}, "one row per channel, both kept"
    assert by_channel["email"]["delivered"] is True
    assert by_channel["whatsapp"]["delivered"] is True


async def test_the_email_record_does_not_overwrite_the_whatsapp_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Half B, second direction — the one the dedupe test cannot see.

    The WhatsApp row here is an un-delivered REFUSAL (which is the only kind a
    deployment without a BSP can produce), so the email dedupe is not involved at all
    and only the UPDATE's channel predicate is under test. Without it the email's
    payload lands on the WhatsApp row: the refusal disappears, the client's timeline
    shows the email's outcome twice, and "were we ever told on WhatsApp?" becomes
    unanswerable.
    """
    payload = await _hot_lead("no-clobber")
    await _record_whatsapp_attempt(payload, delivered=False, reason="recipient_not_opted_in")
    _email(monkeypatch, delivered=True)
    _channel_on(monkeypatch, on=False)

    assert await notifications.notify_hot_lead({"job_try": 1}, payload) == "sent"

    by_channel = {row["channel"]: row for row in await _events(payload)}
    assert set(by_channel) == {"email", "whatsapp"}
    assert by_channel["email"]["delivered"] is True
    assert by_channel["whatsapp"] == {
        "call_id": payload["call_id"],
        "channel": "whatsapp",
        "delivered": False,
        "status": "rejected",
        "reason": "recipient_not_opted_in",
        "template": "calevate_hot_lead_v1",
        "attempts": 1,
        "triggers": ["urgency"],
    }, "the WhatsApp refusal must survive the email record untouched"


async def test_each_channel_keeps_its_own_row_across_both_ladders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both jobs, both retried, on one lead: two rows in, two rows out, each updated in
    place by its own channel. This is the shape a real hot lead produces once the
    channel is on, and it is where a missing predicate on either side shows up as a
    lost row rather than as a wrong verdict."""
    payload = await _hot_lead("both-ladders")
    _channel_on(monkeypatch)
    _opt_in(monkeypatch)
    _capture_alerts(monkeypatch, notifications)
    _capture_alerts(monkeypatch, whatsapp)

    # Attempt 1: both channels fail.
    _email(monkeypatch, delivered=False)
    monkeypatch.setattr(
        whatsapp,
        "get_whatsapp_transport",
        lambda: _WhatsAppTransport(
            whatsapp.SendResult(whatsapp.SendStatus.TRANSPORT_FAILED, "http_502")
        ),
    )
    with pytest.raises(Retry):
        await notifications.notify_hot_lead({"job_try": 1}, payload)
    queued = (await _queued_whatsapp_payloads(payload))[0]
    with pytest.raises(Retry):
        await whatsapp.notify_hot_lead_whatsapp({"job_try": 1}, queued)

    assert {row["channel"]: row["delivered"] for row in await _events(payload)} == {
        "email": False,
        "whatsapp": False,
    }

    # Attempt 2: both land.
    _email(monkeypatch, delivered=True)
    monkeypatch.setattr(
        whatsapp,
        "get_whatsapp_transport",
        lambda: _WhatsAppTransport(whatsapp.SendResult(whatsapp.SendStatus.DELIVERED)),
    )
    assert await notifications.notify_hot_lead({"job_try": 2}, payload) == "sent"
    assert await whatsapp.notify_hot_lead_whatsapp({"job_try": 2}, queued) == "sent"

    rows = await _events(payload)
    assert len(rows) == 2, "one row per channel, however many attempts it took"
    assert {row["channel"]: row["delivered"] for row in rows} == {"email": True, "whatsapp": True}
    assert len(await _queued_whatsapp_payloads(payload)) == 1, "still one promise"


# --------------------------------------------------------------------------------
# 3. A deployment with no BSP still refuses honestly — the wiring must not change that
# --------------------------------------------------------------------------------


async def test_with_the_channel_on_and_no_opt_in_the_alert_is_refused_and_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Today's real state with the switch flipped: an owner phone exists, the opt-in
    column does not, so `resolve_destination` cannot evidence an opt-in and the send is
    refused permanently — before any number reaches a processor. Recorded on the
    timeline, alerted once, never raised."""
    payload = await _hot_lead("no-optin")
    await _add_owner_with_phone(UUID(payload["tenant_id"]), OWNER_TEST_E164)
    _channel_on(monkeypatch)
    _email(monkeypatch, delivered=True)
    fired = _capture_alerts(monkeypatch, whatsapp)

    await notifications.notify_hot_lead({"job_try": 1}, payload)
    queued = (await _queued_whatsapp_payloads(payload))[0]
    result = await whatsapp.notify_hot_lead_whatsapp({"job_try": 1}, queued)

    assert result == "rejected recipient_not_opted_in"
    row = (await _events(payload, channel="whatsapp"))[0]
    assert row["delivered"] is False and row["reason"] == "recipient_not_opted_in"
    assert [code for _stage, code, _detail in fired] == ["hot_lead_whatsapp_rejected"]


async def test_with_an_opt_in_but_no_bsp_the_alert_is_refused_and_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The state the day the opt-in column lands and the BSP decision has not: the
    channel is on, the recipient has opted in, and there is no adapter. It must refuse
    with `no_provider_configured`, record the refusal where the client can read it, and
    tell an operator — reporting delivered, or returning quietly, would make the
    2-minute SLO look met on every dashboard while nobody was ever pinged."""
    payload = await _hot_lead("no-bsp")
    settings = get_settings()
    _channel_on(monkeypatch)
    monkeypatch.setattr(settings, "whatsapp_provider", None)
    monkeypatch.setattr(settings, "app_env", "prod")  # the dev sink is local-only
    _opt_in(monkeypatch)
    _email(monkeypatch, delivered=True)
    fired = _capture_alerts(monkeypatch, whatsapp)

    await notifications.notify_hot_lead({"job_try": 1}, payload)
    queued = (await _queued_whatsapp_payloads(payload))[0]
    result = await whatsapp.notify_hot_lead_whatsapp({"job_try": 1}, queued)

    assert result == "rejected no_provider_configured"
    row = (await _events(payload, channel="whatsapp"))[0]
    assert row["delivered"] is False and row["reason"] == "no_provider_configured"
    assert [(stage, code) for stage, code, _d in fired] == [
        ("WORKER_TERMINAL", "hot_lead_whatsapp_rejected")
    ]
    assert (await _events(payload, channel="email"))[0]["delivered"] is True


# --------------------------------------------------------------------------------
# 4. Hard rule 6 on the new call path
# --------------------------------------------------------------------------------


async def test_the_wiring_puts_no_phone_number_in_the_logs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The notification path composes a MASKED caller number for the email body and now
    also queues a second channel. Neither the caller's number nor the owner's
    destination may reach a log line — asserted through the real `JsonFormatter`,
    because a record whose extras look clean can still stringify a number into `msg`.
    """
    payload = await _hot_lead("nolog")
    await _add_owner_with_phone(UUID(payload["tenant_id"]), OWNER_TEST_E164)
    _channel_on(monkeypatch)
    _opt_in(monkeypatch)
    _email(monkeypatch, delivered=True)
    monkeypatch.setattr(
        whatsapp,
        "get_whatsapp_transport",
        lambda: _WhatsAppTransport(whatsapp.SendResult(whatsapp.SendStatus.DELIVERED)),
    )

    formatter = JsonFormatter()
    with caplog.at_level(logging.DEBUG):
        await notifications.notify_hot_lead({"job_try": 1}, payload)
        queued = (await _queued_whatsapp_payloads(payload))[0]
        await whatsapp.notify_hot_lead_whatsapp({"job_try": 1}, queued)

    rendered = "\n".join(formatter.format(record) for record in caplog.records)
    assert "hot_lead_whatsapp_queued" in rendered, "the new log line really did run"
    for number in (OWNER_TEST_E164, CALLER_TEST_E164):
        assert number not in rendered
        assert number.lstrip("+") not in rendered
        assert number[-10:] not in rendered, "nor the national digits without the code"


async def test_the_queued_payload_carries_no_caller_data(monkeypatch: pytest.MonkeyPatch) -> None:
    """What the wiring puts on the queue is ids and our own trigger vocabulary. A
    payload that carried the caller's name or number would put PII in
    `outbox_messages` — a table with a retention life of its own — on the way to a
    template that is deliberately incapable of rendering it."""
    payload = await _hot_lead("payload")
    _channel_on(monkeypatch)
    _email(monkeypatch, delivered=True)
    await notifications.notify_hot_lead({"job_try": 1}, payload)

    queued = json.dumps((await _queued_whatsapp_payloads(payload))[0])
    assert CALLER_TEST_E164 not in queued and CALLER_TEST_E164.lstrip("+") not in queued
    assert "Ravi" not in queued
