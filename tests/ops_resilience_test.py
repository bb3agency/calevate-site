"""Three ops-resilience properties: the halt sticks, the stall alarm can see, the
notification that fails is heard.

Each of these is a safety mechanism that reported success while doing nothing — the
worst failure shape there is, because the dashboard says the system is healthy.

1. **The load-shed cache cannot serve a stale "open" forever.** `set_platform_status`
   invalidates the Redis copy with a best-effort `DELETE` inside a swallowed `except`.
   That delete fails precisely when Redis is flaky, which is when an operator is most
   likely to be pulling the big red switch — and the hash was written with no expiry,
   so every process kept reading the stale value and never consulted the durable row
   again.
2. **`report_stalled_pipeline` queried FORCE-RLS'd tables with no tenant context**, so
   it counted zero stalled calls whatever was sitting in the table. The post-call stall
   alarm had never been able to fire.
3. **A hot-lead email that fails to send was neither retried nor alerted.** The job
   recorded `delivered: false` and returned normally, so no ladder ran and no human
   learned that a lead nobody was told about had been dropped.

CONCURRENCY. Other suites run against this same Postgres and this same Redis, and
`platform_state` is ONE global row shared by all of them. The load-shed tests below
therefore touch neither: they redirect `_REDIS_KEY` to a key private to the test run
and stub `_read_durable` to stand in for the durable row. No concurrent run can observe
a half-applied halt from this file, because this file never applies one. Everything
else is scoped to its own run-unique tenant.
"""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.core import loadshed
from apps.api.core.loadshed import PlatformStatus, get_platform_status
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.core.redis import get_redis
from apps.api.db.session import tenant_session, untenanted_session
from apps.workers import dispatcher, notifications
from arq import Retry
from sqlalchemy import text

# --------------------------------------------------------------------------------
# Shared seeding
# --------------------------------------------------------------------------------


async def _tenant_with_agent(prefix: str, *, billing_email: str | None = None) -> tuple[UUID, UUID]:
    created = await admin_service.create_organization(
        name=f"{prefix.title()} Clinic",
        slug=f"{prefix}-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=billing_email,
        language="te-IN",
        created_by=None,
    )
    return UUID(str(created["id"])), UUID(str(created["agent_id"]))


async def _publish_route(tenant_id: UUID, agent_id: UUID) -> str:
    """What the agent publish path writes: the global bridge from the engine's id space
    to ours. A tenant only ever has calls once this row exists."""
    ref = f"eng_{uuid.uuid4().hex[:12]}"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('fake', :ref, :tid, :aid, true, now(), "
                "now())"
            ),
            {"ref": ref, "tid": tenant_id, "aid": agent_id},
        )
    return ref


async def _completed_call(tenant_id: UUID, agent_id: UUID, *, ended_minutes_ago: int) -> UUID:
    call_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "from_e164, to_e164, started_at, ended_at, duration_s, summary, created_at, "
                "updated_at) VALUES (:id, :tid, :aid, :ecid, 'inbound', 'completed', "
                "'+919876500111', '+911140000000', now() - make_interval(mins => :mins), "
                "now() - make_interval(mins => :mins), 95, 'Wants an appointment today', "
                "now(), now())"
            ),
            {
                "id": call_id,
                "tid": tenant_id,
                "aid": agent_id,
                "ecid": f"exec_{call_id.hex[:12]}",
                "mins": ended_minutes_ago,
            },
        )
    return call_id


# --------------------------------------------------------------------------------
# 1. The big red switch cannot be ignored because one Redis call failed
# --------------------------------------------------------------------------------


def _private_key() -> str:
    return f"calevate:platform_state:test:{uuid.uuid4().hex}"


async def test_filling_the_load_shed_cache_never_leaves_an_immortal_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every write of the cached status must carry an expiry.

    The expiry IS the safety property: `set_platform_status` invalidates the cache with
    a `DELETE` whose failure is swallowed, so without a TTL one failed round trip makes
    the cached value permanent — and the value it makes permanent is whatever the
    platform looked like before the operator intervened.
    """
    key = _private_key()
    monkeypatch.setattr(loadshed, "_REDIS_KEY", key)
    monkeypatch.setattr(loadshed, "_memo", None)
    redis = get_redis()
    try:
        await get_platform_status(force_refresh=True)
        assert await redis.exists(key), "a durable read must repopulate the cache"
        ttl = await redis.ttl(key)
        assert ttl > 0, f"the cached status must expire on its own; TTL was {ttl}"
        assert ttl <= loadshed._CACHE_TTL_S
    finally:
        await redis.delete(key)


async def test_a_stale_cached_open_is_never_served_over_a_durable_halt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reported failure, reproduced: the durable row says halted, a stale hash with
    no expiry says open, and the invalidating delete never landed.

    Serving that hash is the big red switch failing to stop calls — `check_dispatch`
    and `dispatch_campaign_tick` both read this exact function. The durable row is
    STUBBED rather than written, so this reproduction cannot leak a halt into a
    concurrently running suite.
    """
    key = _private_key()
    monkeypatch.setattr(loadshed, "_REDIS_KEY", key)
    monkeypatch.setattr(loadshed, "_memo", None)

    async def _halted() -> PlatformStatus:
        return PlatformStatus(mode="normal", outbound_halted=True)

    monkeypatch.setattr(loadshed, "_read_durable", _halted)
    redis = get_redis()
    try:
        # Exactly what a failed invalidation leaves behind.
        await redis.hset(key, mapping={"mode": "normal", "outbound_halted": "0"})  # type: ignore[misc]
        status = await get_platform_status()
        assert status.outbound_halted is True, "a stale cached open outlived the halt"
        assert await redis.ttl(key) > 0, "the repaired cache entry must itself expire"
    finally:
        await redis.delete(key)


def test_the_stale_window_closes_inside_one_dispatch_tick() -> None:
    """The campaign dispatch tick runs every 30 seconds
    (`cron(dispatch_campaign_tick, second={0, 30})`), and it reads the halt ONCE per
    tick. A cache that can be stale for longer than a tick is a tick that dials
    through the halt, so the two constants are pinned against it here rather than
    left to drift apart."""
    assert loadshed._CACHE_TTL_S + loadshed._MEMO_TTL_S <= 30


# --------------------------------------------------------------------------------
# 2. The stall alarm can actually see a stalled call
# --------------------------------------------------------------------------------


def _capture_alerts(monkeypatch: pytest.MonkeyPatch, module: Any) -> list[tuple[str, str, Any]]:
    fired: list[tuple[str, str, Any]] = []

    def _record(stage: str, code: str, **kwargs: Any) -> None:
        fired.append((stage, code, kwargs.get("detail")))

    monkeypatch.setattr(module, "alert", _record)
    return fired


async def test_a_stalled_call_is_counted_and_alerted(monkeypatch: pytest.MonkeyPatch) -> None:
    """The post-call SLO's alarm. Reading `calls` and `call_extractions` on a session
    with no tenant context returns zero rows forever (FORCE RLS fails closed), so the
    job reported a healthy pipeline while leads were being dropped.

    The count is asserted as `>= 1` because every other suite's data is in the same
    database; the exact-count assertion lives in the per-tenant test below.
    """
    tenant_id, agent_id = await _tenant_with_agent("stall")
    await _publish_route(tenant_id, agent_id)
    await _completed_call(tenant_id, agent_id, ended_minutes_ago=30)

    fired = _capture_alerts(monkeypatch, dispatcher)
    result = await dispatcher.report_stalled_pipeline({})

    # Parsed by KEY, not by position: the job now also reports `unreached`, the tenants
    # its per-tenant isolation could not probe (P6.2), and a positional split reads the
    # next field as part of this number.
    fields = dict(pair.split("=", 1) for pair in result.split())
    count = int(fields["stalled"])
    assert count >= 1, f"a stalled call must be visible to the alarm, got {result}"
    assert fields["unreached"] == "0", f"every tenant should have been probed: {result}"
    assert [code for _stage, code, _detail in fired] == ["postcall_pipeline_stalled"]
    assert fired[0][0] == "WORKER_STALL"


async def test_the_stall_probe_counts_only_calls_the_pipeline_actually_dropped() -> None:
    """Scoped to one tenant, so the numbers are exact.

    A call with an extraction is a call the pipeline finished, and a call that ended a
    minute ago is inside the 10-minute grace — counting either would make the alarm
    fire constantly, which is the same as not firing at all.
    """
    tenant_id, agent_id = await _tenant_with_agent("probe")
    await _publish_route(tenant_id, agent_id)
    stalled_id = await _completed_call(tenant_id, agent_id, ended_minutes_ago=30)
    await _completed_call(tenant_id, agent_id, ended_minutes_ago=1)

    async with tenant_session(tenant_id) as session:
        assert await dispatcher._count_stalled(session) == 1

        await session.execute(
            text(
                "INSERT INTO call_extractions (id, tenant_id, call_id, schema_version, data, "
                "model, valid, errors, created_at, updated_at) VALUES (:id, :tid, :cid, 1, "
                "'{}'::jsonb, NULL, true, NULL, now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "cid": stalled_id},
        )
        assert await dispatcher._count_stalled(session) == 0


# --------------------------------------------------------------------------------
# 3. A hot-lead notification that fails is retried, then heard
# --------------------------------------------------------------------------------


class _Transport:
    """Counts attempts so "did it try again?" is answerable."""

    name = "test"

    def __init__(self, delivered: bool) -> None:
        self.delivered = delivered
        self.attempts = 0

    def send(self, *, to: str, subject: str, body: str, html: str | None = None) -> bool:
        # `html` accepted because `transport.Transport` declares it (the branded
        # alternative, `workers/email_render`). A double whose signature has drifted from
        # the Protocol stops being evidence about the real call — which is what
        # `tests/auth_email_delivery_test` exists to catch.
        self.attempts += 1
        return self.delivered


async def _hot_lead(prefix: str, *, billing_email: str | None) -> dict[str, str]:
    tenant_id, agent_id = await _tenant_with_agent(prefix, billing_email=billing_email)
    call_id = await _completed_call(tenant_id, agent_id, ended_minutes_ago=2)
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
        "triggers": ["urgency"],  # type: ignore[dict-item]
    }


async def _notification_events(payload: dict[str, str]) -> list[dict[str, Any]]:
    async with tenant_session(UUID(payload["tenant_id"])) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT payload FROM lead_events WHERE lead_id = :lid AND type = 'notification'"
                ),
                {"lid": UUID(payload["lead_id"])},
            )
        ).all()
    return [dict(row[0]) for row in rows]


async def test_a_failed_send_asks_for_the_retry_ladder(monkeypatch: pytest.MonkeyPatch) -> None:
    """`arq.Retry`, not a bare raise and not a quiet return.

    arq 0.28 retries a job only for `Retry`/`RetryJob`/`CancelledError`, so this is the
    ONLY way the ladder runs. Returning normally — what this job used to do — spends
    the whole retry budget on the first attempt and calls it a success.
    """
    payload = await _hot_lead("retryable", billing_email="owner@example.test")
    transport = _Transport(delivered=False)
    monkeypatch.setattr(notifications, "get_transport", lambda: transport)

    with pytest.raises(Retry):
        await notifications.notify_hot_lead({"job_try": 1}, payload)

    assert transport.attempts == 1
    events = await _notification_events(payload)
    assert len(events) == 1, "the attempt is recorded on the lead timeline"
    assert events[0]["delivered"] is False


async def test_a_retry_actually_re_sends_instead_of_being_deduped_away(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The trap in the idempotence check: a failed attempt must not satisfy it.

    If the recorded `delivered: false` counted as "already notified", every retry would
    return `duplicate` and the ladder would be decorative — a hot lead nobody was told
    about, with a timeline row claiming we handled it.
    """
    payload = await _hot_lead("second-try", billing_email="owner@example.test")
    failing = _Transport(delivered=False)
    monkeypatch.setattr(notifications, "get_transport", lambda: failing)
    with pytest.raises(Retry):
        await notifications.notify_hot_lead({"job_try": 1}, payload)

    succeeding = _Transport(delivered=True)
    monkeypatch.setattr(notifications, "get_transport", lambda: succeeding)
    result = await notifications.notify_hot_lead({"job_try": 2}, payload)

    assert result == "sent"
    assert succeeding.attempts == 1, "the retry must reach the transport again"
    events = await _notification_events(payload)
    assert len(events) == 1, "one notification per lead+call, whatever it took to deliver"
    assert events[0]["delivered"] is True


async def test_a_delivered_notification_is_never_sent_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = await _hot_lead("once", billing_email="owner@example.test")
    transport = _Transport(delivered=True)
    monkeypatch.setattr(notifications, "get_transport", lambda: transport)

    first = await notifications.notify_hot_lead({"job_try": 1}, payload)
    second = await notifications.notify_hot_lead({"job_try": 1}, payload)

    assert first == "sent"
    assert second == "duplicate"
    assert transport.attempts == 1


async def test_the_last_attempt_tells_a_human(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exhaustion is the end of the ladder, not the end of the story. A hot lead the
    client was never told about is the exact failure this notification exists to
    prevent, so the budget running out has to reach an operator."""
    payload = await _hot_lead("exhausted", billing_email="owner@example.test")
    monkeypatch.setattr(notifications, "get_transport", lambda: _Transport(delivered=False))
    fired = _capture_alerts(monkeypatch, notifications)

    result = await notifications.notify_hot_lead({"job_try": WORKER_MAX_TRIES}, payload)

    assert "exhausted" in result
    assert [code for _stage, code, _detail in fired] == ["hot_lead_notification_exhausted"]
    events = await _notification_events(payload)
    assert events[0]["delivered"] is False, "the timeline keeps the failure visible"


async def test_a_tenant_with_no_email_is_alerted_not_retried_forever(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing billing email is a data fix, not a blip: the same row will be just as
    empty in two minutes, so the ladder cannot help and must not run. Someone still has
    to be told, because the lead is just as un-notified either way."""
    payload = await _hot_lead("nochannel", billing_email=None)
    transport = _Transport(delivered=True)
    monkeypatch.setattr(notifications, "get_transport", lambda: transport)
    fired = _capture_alerts(monkeypatch, notifications)

    result = await notifications.notify_hot_lead({"job_try": 1}, payload)

    assert result != "sent"
    assert transport.attempts == 0, "there is nowhere to send it"
    assert [code for _stage, code, _detail in fired] == ["hot_lead_no_channel"]
    assert all("@" not in str(detail) for _s, _c, detail in fired), "hard rule 6: no PII"
