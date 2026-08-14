"""Hot-lead WhatsApp alerts: the transport seam, the delivery record, the retry
classification, and the two properties that make this feature worth having.

Everything runs against the CONSOLE DEV SINK — no credentials, no network, no vendor
account — which is the point of building the transport before the vendor is chosen.
There is no BSP adapter to test because the decision log has not picked one.

The properties under test, in the order they matter:

1. **A message that never went out is heard.** Silence is the failure this feature
   exists to prevent, so every un-delivered outcome must either climb the ladder or
   reach a human.
2. **Not every failure earns a retry.** A transport blip does; an unapproved template,
   a recipient with no recorded opt-in and an unconfigured provider are verdicts —
   retrying only delays the same answer three times over.
3. **The two channels cannot answer for each other.** A delivered email must not make
   the WhatsApp ladder report success, and a WhatsApp attempt must not satisfy the
   email dedupe.
4. **Hard rule 6.** The destination number never reaches a log line.

CONCURRENCY: every test creates its own run-unique tenant, and nothing here touches a
global row, so this file can run beside the other suites on the same Postgres.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import fields
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.core.logging import JsonFormatter
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session
from apps.workers import whatsapp
from apps.workers.whatsapp import (
    ConsoleWhatsAppTransport,
    Destination,
    SendResult,
    SendStatus,
    UnconfiguredWhatsAppTransport,
    WhatsAppMessage,
    enqueue_hot_lead_whatsapp,
    get_whatsapp_transport,
    notify_hot_lead_whatsapp,
    resolve_destination,
)
from arq import Retry
from sqlalchemy import text

# A documented test number in the TRAI-reserved test range shape. It exists so the
# hard-rule-6 test has something to search the log output FOR — it is never a real
# subscriber, and no test here logs it deliberately.
OWNER_TEST_E164 = "+919000000001"


# --------------------------------------------------------------------------------
# Seeding
# --------------------------------------------------------------------------------


async def _tenant_with_agent(prefix: str) -> tuple[UUID, UUID]:
    created = await admin_service.create_organization(
        name=f"{prefix.title()} Clinic",
        slug=f"wa-{prefix}-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email="owner@example.test",
        language="te-IN",
        created_by=None,
    )
    return UUID(str(created["id"])), UUID(str(created["agent_id"]))


async def _completed_call(tenant_id: UUID, agent_id: UUID) -> UUID:
    call_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "from_e164, to_e164, started_at, ended_at, duration_s, summary, created_at, "
                "updated_at) VALUES (:id, :tid, :aid, :ecid, 'inbound', 'completed', "
                "'+919876500111', '+911140000000', now() - make_interval(mins => 2), "
                "now() - make_interval(mins => 2), 95, 'Wants an appointment today', "
                "now(), now())"
            ),
            {"id": call_id, "tid": tenant_id, "aid": agent_id, "ecid": f"exec_{call_id.hex[:12]}"},
        )
    return call_id


async def _hot_lead(prefix: str) -> dict[str, Any]:
    tenant_id, agent_id = await _tenant_with_agent(prefix)
    call_id = await _completed_call(tenant_id, agent_id)
    lead_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status, "
                "data, schema_version, first_call_id, last_call_id, call_count, "
                "is_repeat_caller, created_at, updated_at) VALUES (:id, :tid, :aid, "
                "'+919876500111', 'Ravi', 'inbound_call', 'hot', '{}'::jsonb, 1, :cid, :cid, 1, "
                "false, now(), now())"
            ),
            {"id": lead_id, "tid": tenant_id, "aid": agent_id, "cid": call_id},
        )
    return {
        "tenant_id": str(tenant_id),
        "lead_id": str(lead_id),
        "call_id": str(call_id),
        "triggers": ["urgency"],
    }


async def _add_owner_with_phone(tenant_id: UUID, phone: str | None) -> UUID:
    """`users` is global identity (no RLS); `memberships` is tenant-scoped."""
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
    return user_id


async def _notification_events(payload: dict[str, Any], *, channel: str) -> list[dict[str, Any]]:
    async with tenant_session(UUID(payload["tenant_id"])) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT payload FROM lead_events WHERE lead_id = :lid "
                    "AND type = 'notification' AND payload->>'channel' = :channel"
                ),
                {"lid": UUID(payload["lead_id"]), "channel": channel},
            )
        ).all()
    return [dict(row[0]) for row in rows]


def _capture_alerts(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, Any]]:
    fired: list[tuple[str, str, Any]] = []

    def _record(stage: str, code: str, **kwargs: Any) -> None:
        fired.append((stage, code, kwargs.get("detail")))

    monkeypatch.setattr(whatsapp, "alert", _record)
    return fired


class _Transport:
    """Counts attempts so "did it try again?" is answerable."""

    name = "test"

    def __init__(self, result: SendResult) -> None:
        self.result = result
        self.attempts = 0
        self.last: WhatsAppMessage | None = None

    # `async`, because `WhatsAppTransport.send` is — and both shipped transports and the
    # Meta Cloud API adapter are too. A synchronous stub here type-checks (a Protocol is
    # structural and `Awaitable` is not declared in the annotation) while making the one
    # call site raise `TypeError: object SendResult can't be used in 'await' expression`.
    async def send(self, message: WhatsAppMessage) -> SendResult:
        self.attempts += 1
        self.last = message
        return self.result


def _enable(monkeypatch: pytest.MonkeyPatch, transport: _Transport | None = None) -> _Transport:
    """Turn the feature on for one test, with a recorded opt-in.

    `resolve_destination` is patched rather than a config flag being flipped: the
    opt-in gate is not something a setting may switch off (that would be a compliance
    bypass), it is something that becomes satisfiable when the opt-in column lands.
    Patching the resolver is this test suite standing in for that column.
    """
    monkeypatch.setattr(get_settings(), "whatsapp_enabled", True)
    sink = transport or _Transport(SendResult(SendStatus.DELIVERED))
    monkeypatch.setattr(whatsapp, "get_whatsapp_transport", lambda: sink)

    async def _opted_in(session: Any, tenant_id: UUID) -> Destination:
        return Destination(to_e164=OWNER_TEST_E164, opt_in_at=datetime.now(UTC))

    monkeypatch.setattr(whatsapp, "resolve_destination", _opted_in)
    return sink


# --------------------------------------------------------------------------------
# 1. The transport seam: a dev sink that needs nothing, and no invented vendor
# --------------------------------------------------------------------------------


def test_local_without_a_provider_uses_the_dev_sink(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "whatsapp_provider", None)
    monkeypatch.setattr(settings, "app_env", "local")
    assert isinstance(get_whatsapp_transport(), ConsoleWhatsAppTransport)


async def test_a_named_provider_refuses_rather_than_pretending(monkeypatch: pytest.MonkeyPatch) -> None:
    """No BSP is chosen in the decision log, so no adapter exists. Naming one in config
    must fail loudly — a silent no-op would look exactly like a working integration."""
    settings = get_settings()
    monkeypatch.setattr(settings, "whatsapp_provider", "some-bsp")
    monkeypatch.setattr(settings, "app_env", "prod")
    transport = get_whatsapp_transport()
    result = await transport.send(WhatsAppMessage(OWNER_TEST_E164, "t", "en", ("x",)))
    assert result.status is SendStatus.REJECTED
    assert result.reason.startswith("provider_not_implemented")
    assert result.retryable is False, "a missing adapter is not a blip"


async def test_a_non_local_env_without_a_provider_reports_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The property the whole module exists for: silence is reported, never swallowed."""
    settings = get_settings()
    monkeypatch.setattr(settings, "whatsapp_provider", None)
    monkeypatch.setattr(settings, "app_env", "prod")
    transport = get_whatsapp_transport()
    assert isinstance(transport, UnconfiguredWhatsAppTransport)
    sent = await transport.send(WhatsAppMessage(OWNER_TEST_E164, "t", "en", ("x",)))
    assert sent.delivered is False


async def test_the_dev_sink_is_refused_outside_local(monkeypatch: pytest.MonkeyPatch) -> None:
    """`WHATSAPP_PROVIDER=console` in staging would report every alert delivered
    forever. Operator error, but the kind that hides the failure it causes."""
    settings = get_settings()
    monkeypatch.setattr(settings, "whatsapp_provider", "console")
    monkeypatch.setattr(settings, "app_env", "staging")
    result = await get_whatsapp_transport().send(
        WhatsAppMessage(OWNER_TEST_E164, "t", "en", ("x",))
    )
    assert result.reason == "dev_sink_refused_outside_local"


def test_the_message_type_cannot_carry_free_text() -> None:
    """The template gate, encoded rather than described: business-initiated WhatsApp
    needs an approved template, so a type with no body field cannot send prose."""
    names = {f.name for f in fields(WhatsAppMessage)}
    assert names == {"to_e164", "template", "locale", "variables"}
    assert "body" not in names


def test_the_template_variable_carries_no_consumer_data() -> None:
    """The lead's name, number and call summary stay behind the client's login. What
    reaches a third-party processor is WHY the lead is hot, drawn from our own trigger
    vocabulary — never caller-supplied text."""
    assert whatsapp._compose_variables(["urgency"]) == ("urgency",)
    assert whatsapp._compose_variables([]) == ("marked hot",)
    assert len(whatsapp._compose_variables(["urgency"])) == whatsapp.TEMPLATE_VARIABLE_COUNT


# --------------------------------------------------------------------------------
# 2. Off by default, and quiet about it
# --------------------------------------------------------------------------------


async def test_disabled_is_silent_and_records_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Email is the channel of record until a human finishes the switch-on checklist.
    An alert per hot lead in that state trains everyone to ignore this alert before it
    ever means anything."""
    payload = await _hot_lead("disabled")
    monkeypatch.setattr(get_settings(), "whatsapp_enabled", False)
    fired = _capture_alerts(monkeypatch)

    assert await notify_hot_lead_whatsapp({"job_try": 1}, payload) == "disabled"
    assert fired == []
    assert await _notification_events(payload, channel="whatsapp") == []


# --------------------------------------------------------------------------------
# 3. The delivery record — "I was never told" has to be answerable
# --------------------------------------------------------------------------------


async def test_a_delivered_alert_is_recorded_on_the_lead_timeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = await _hot_lead("delivered")
    sink = _enable(monkeypatch)

    assert await notify_hot_lead_whatsapp({"job_try": 1}, payload) == "sent"

    events = await _notification_events(payload, channel="whatsapp")
    assert len(events) == 1
    assert events[0]["delivered"] is True
    assert events[0]["call_id"] == payload["call_id"]
    assert events[0]["status"] == SendStatus.DELIVERED
    assert events[0]["attempts"] == 1
    assert events[0]["template"] == get_settings().whatsapp_template_hot_lead
    assert sink.last is not None and sink.last.variables == ("urgency",)


async def test_a_delivered_alert_is_never_sent_twice(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = await _hot_lead("once")
    sink = _enable(monkeypatch)

    first = await notify_hot_lead_whatsapp({"job_try": 1}, payload)
    second = await notify_hot_lead_whatsapp({"job_try": 1}, payload)

    assert (first, second) == ("sent", "duplicate")
    assert sink.attempts == 1


async def test_an_undelivered_alert_stays_visible_as_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """The timeline keeps the failure rather than losing it: a client asking "was I
    told?" gets a truthful no."""
    payload = await _hot_lead("undelivered")
    _enable(monkeypatch, _Transport(SendResult(SendStatus.TRANSPORT_FAILED, "connect_timeout")))
    _capture_alerts(monkeypatch)

    with pytest.raises(Retry):
        await notify_hot_lead_whatsapp({"job_try": 1}, payload)

    events = await _notification_events(payload, channel="whatsapp")
    assert events[0]["delivered"] is False
    assert events[0]["reason"] == "connect_timeout"


# --------------------------------------------------------------------------------
# 4. Retry classification
# --------------------------------------------------------------------------------


async def test_a_transport_failure_asks_for_the_retry_ladder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`arq.Retry`, not a bare raise and not a quiet return. arq 0.28 retries only for
    `Retry`/`RetryJob`/`CancelledError`, so this is the ONLY way the ladder runs."""
    payload = await _hot_lead("blip")
    sink = _enable(monkeypatch, _Transport(SendResult(SendStatus.TRANSPORT_FAILED, "http_502")))
    fired = _capture_alerts(monkeypatch)

    with pytest.raises(Retry):
        await notify_hot_lead_whatsapp({"job_try": 1}, payload)

    assert sink.attempts == 1
    assert fired == [], "a blip inside the budget is not an incident yet"


async def test_a_retry_re_sends_instead_of_being_deduped_away(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The trap in the idempotence check: a recorded ATTEMPT must not satisfy it, or
    every retry returns `duplicate` and the ladder is decorative."""
    payload = await _hot_lead("second-try")
    _enable(monkeypatch, _Transport(SendResult(SendStatus.TRANSPORT_FAILED, "http_502")))
    with pytest.raises(Retry):
        await notify_hot_lead_whatsapp({"job_try": 1}, payload)

    succeeding = _enable(monkeypatch)
    assert await notify_hot_lead_whatsapp({"job_try": 2}, payload) == "sent"

    assert succeeding.attempts == 1, "the retry must reach the transport again"
    events = await _notification_events(payload, channel="whatsapp")
    assert len(events) == 1, "one record per lead+call, whatever it took to deliver"
    assert events[0]["delivered"] is True


async def test_a_rejection_is_terminal_and_told_to_a_human_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unapproved template is a verdict. Three retries reach the same answer two
    minutes later, so the ladder is skipped — but the lead is just as un-notified, so
    someone is told at once."""
    payload = await _hot_lead("rejected")
    sink = _enable(
        monkeypatch, _Transport(SendResult(SendStatus.REJECTED, "template_not_approved"))
    )
    fired = _capture_alerts(monkeypatch)

    result = await notify_hot_lead_whatsapp({"job_try": 1}, payload)

    assert result == "rejected template_not_approved"
    assert sink.attempts == 1
    assert [(stage, code) for stage, code, _ in fired] == [
        ("WORKER_TERMINAL", "hot_lead_whatsapp_rejected")
    ]


async def test_a_recipient_with_no_recorded_opt_in_is_refused_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Meta policy and DPDP both land here, and both are permanent conditions. The
    transport is never even reached: we do not hand a number to a processor to find out
    whether we were allowed to."""
    payload = await _hot_lead("noptin")
    monkeypatch.setattr(get_settings(), "whatsapp_enabled", True)
    sink = _Transport(SendResult(SendStatus.DELIVERED))
    monkeypatch.setattr(whatsapp, "get_whatsapp_transport", lambda: sink)

    async def _no_opt_in(session: Any, tenant_id: UUID) -> Destination:
        return Destination(to_e164=OWNER_TEST_E164, opt_in_at=None)

    monkeypatch.setattr(whatsapp, "resolve_destination", _no_opt_in)
    fired = _capture_alerts(monkeypatch)

    result = await notify_hot_lead_whatsapp({"job_try": 1}, payload)

    assert result == "rejected recipient_not_opted_in"
    assert sink.attempts == 0
    assert [code for _s, code, _d in fired] == ["hot_lead_whatsapp_rejected"]
    events = await _notification_events(payload, channel="whatsapp")
    assert events[0]["delivered"] is False


async def test_the_last_attempt_tells_a_human(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exhaustion is the end of the ladder, not the end of the story."""
    payload = await _hot_lead("exhausted")
    _enable(monkeypatch, _Transport(SendResult(SendStatus.TRANSPORT_FAILED, "http_502")))
    fired = _capture_alerts(monkeypatch)

    result = await notify_hot_lead_whatsapp({"job_try": WORKER_MAX_TRIES}, payload)

    assert "exhausted" in result
    assert [(stage, code) for stage, code, _ in fired] == [
        ("WORKER_DELIVERY", "hot_lead_whatsapp_exhausted")
    ]
    events = await _notification_events(payload, channel="whatsapp")
    assert events[0]["delivered"] is False


# --------------------------------------------------------------------------------
# 5. The two channels cannot answer for each other
# --------------------------------------------------------------------------------


async def test_a_delivered_email_does_not_satisfy_the_whatsapp_ladder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both channels write `lead_events.type = 'notification'` — the type column is a
    fixed CHECK enum and this milestone ships no migration — so `channel` is the
    discriminator, and every query on both sides must use it."""
    payload = await _hot_lead("crosstalk")
    async with tenant_session(UUID(payload["tenant_id"])) as session:
        await session.execute(
            text(
                "INSERT INTO lead_events (id, tenant_id, lead_id, type, payload, actor, "
                "created_at, updated_at) VALUES (:id, :tid, :lid, 'notification', "
                "CAST(:p AS jsonb), 'system', now(), now())"
            ),
            {
                "id": uuid.uuid4(),
                "tid": UUID(payload["tenant_id"]),
                "lid": UUID(payload["lead_id"]),
                "p": json.dumps(
                    {
                        "call_id": payload["call_id"],
                        "channel": "email",
                        "delivered": True,
                        "attempts": 1,
                    }
                ),
            },
        )
    sink = _enable(monkeypatch)

    assert await notify_hot_lead_whatsapp({"job_try": 1}, payload) == "sent"
    assert sink.attempts == 1, "the email's success must not mark WhatsApp done"

    email_events = await _notification_events(payload, channel="email")
    assert len(email_events) == 1, "the email row must survive untouched"
    assert email_events[0]["delivered"] is True
    assert len(await _notification_events(payload, channel="whatsapp")) == 1


# --------------------------------------------------------------------------------
# 6. Hard rule 6 — the destination never reaches a log line
# --------------------------------------------------------------------------------


async def test_no_phone_number_reaches_the_logs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """`transport.py` can log an email DOMAIN because a domain is shared and is not a
    person. A phone number has no such component, so nothing about the destination is
    logged at all — not masked, not fingerprinted (a truncated hash of a 10-digit
    number is brute-forced in seconds, so it would be a pseudonym, not anonymity).

    Asserted through the real `JsonFormatter`, because that is what production writes:
    a record whose extras look clean can still stringify a number into `msg`.
    """
    payload = await _hot_lead("nolog")
    _enable(monkeypatch)
    formatter = JsonFormatter()

    with caplog.at_level(logging.DEBUG):
        assert await notify_hot_lead_whatsapp({"job_try": 1}, payload) == "sent"
        # ...and the un-delivered path, which is where a "helpful" debug line lands.
        failing = await _hot_lead("nolog-fail")
        _enable(monkeypatch, _Transport(SendResult(SendStatus.TRANSPORT_FAILED, "http_502")))
        _capture_alerts(monkeypatch)
        await notify_hot_lead_whatsapp({"job_try": WORKER_MAX_TRIES}, failing)

    rendered = "\n".join(formatter.format(record) for record in caplog.records)
    assert OWNER_TEST_E164 not in rendered
    assert OWNER_TEST_E164.lstrip("+") not in rendered
    assert "+919876500111" not in rendered, "nor the CALLER's number"


async def test_the_console_sink_logs_the_template_not_the_recipient(
    caplog: pytest.LogCaptureFixture,
) -> None:
    formatter = JsonFormatter()
    with caplog.at_level(logging.DEBUG):
        result = await ConsoleWhatsAppTransport().send(
            WhatsAppMessage(OWNER_TEST_E164, "calevate_hot_lead_v1", "en", ("urgency",))
        )
    assert result.delivered is True, "it really did deliver — to a terminal"
    rendered = "\n".join(formatter.format(record) for record in caplog.records)
    assert OWNER_TEST_E164 not in rendered
    assert "calevate_hot_lead_v1" in rendered


# --------------------------------------------------------------------------------
# 7. Resolution + the enqueue point (the wiring surface)
# --------------------------------------------------------------------------------


async def test_the_owner_is_resolved_from_real_data_but_has_no_recorded_opt_in() -> None:
    """The number exists today (`users.phone` on the owner membership). The opt-in does
    NOT — there is no column — and an opt-in we cannot evidence is not an opt-in. This
    test pins that gap so it cannot be silently assumed away."""
    tenant_id, _agent_id = await _tenant_with_agent("resolve")
    await _add_owner_with_phone(tenant_id, OWNER_TEST_E164)

    async with tenant_session(tenant_id) as session:
        destination = await resolve_destination(session, tenant_id)

    assert destination is not None
    assert destination.to_e164 == OWNER_TEST_E164
    assert destination.opt_in_at is None


async def test_an_owner_without_a_phone_resolves_to_nothing() -> None:
    tenant_id, _agent_id = await _tenant_with_agent("nophone")
    await _add_owner_with_phone(tenant_id, None)

    async with tenant_session(tenant_id) as session:
        assert await resolve_destination(session, tenant_id) is None


async def test_enqueue_is_a_no_op_while_the_feature_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """So the one-line call in `notifications.py` is safe to land before the vendor,
    the template and the opt-in column exist."""
    payload = await _hot_lead("enq-off")
    monkeypatch.setattr(get_settings(), "whatsapp_enabled", False)
    async with tenant_session(UUID(payload["tenant_id"])) as session:
        queued = await enqueue_hot_lead_whatsapp(
            session,
            tenant_id=UUID(payload["tenant_id"]),
            lead_id=UUID(payload["lead_id"]),
            call_id=UUID(payload["call_id"]),
            triggers=["urgency"],
        )
    assert queued is False
    assert await _outbox_count(payload) == 0


async def test_enqueue_writes_one_outbox_row_per_lead_and_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Through the outbox so a worker crash cannot lose it, and once per call so a
    pipeline replay does not promise a second ping."""
    payload = await _hot_lead("enq-on")
    monkeypatch.setattr(get_settings(), "whatsapp_enabled", True)
    async with tenant_session(UUID(payload["tenant_id"])) as session:
        first = await enqueue_hot_lead_whatsapp(
            session,
            tenant_id=UUID(payload["tenant_id"]),
            lead_id=UUID(payload["lead_id"]),
            call_id=UUID(payload["call_id"]),
            triggers=["urgency"],
        )
    async with tenant_session(UUID(payload["tenant_id"])) as session:
        second = await enqueue_hot_lead_whatsapp(
            session,
            tenant_id=UUID(payload["tenant_id"]),
            lead_id=UUID(payload["lead_id"]),
            call_id=UUID(payload["call_id"]),
            triggers=["urgency"],
        )

    assert (first, second) == (True, False)
    assert await _outbox_count(payload) == 1


async def _outbox_count(payload: dict[str, Any]) -> int:
    async with untenanted_session() as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM outbox_messages WHERE job = :job "
                        "AND payload->>'lead_id' = :lid"
                    ),
                    {"job": whatsapp.JOB_NAME, "lid": payload["lead_id"]},
                )
            ).scalar_one()
        )
