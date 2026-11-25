"""Starting calls while the voice engine is not answering (`engine/outage.py`).

Seen live on 26 Nov 2026: `POST /calls` read-timed out twice inside a minute. Each such dial
may have rung the person, so it is never re-dialled on a guess; and every dial after it
spent ten seconds of the tick timing out the same way. What this file pins, against a fake
engine whose transport raises the way httpx does and then recovers:

* a connection that was never made proves nobody was rung, so the contact keeps its
  attempt and the rest of the batch waits without asking the vendor again;
* two failed dials in a row hold every dial on the platform, a held dial is refused before
  anything is written, and the tick neither claims nor fires a schedule while held;
* a read probe — never a dial — lifts the hold, and the first ticks after it dial at half;
* a dial whose answer was lost stays `dialing` until the engine, asked by our reference,
  says whether it placed it: found, the call is adopted; not found, the contact is retried
  with the attempt refunded; silent, nothing moves and the campaign cannot complete;
* the same for a call-back.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from apps.api.agents.service import UNCONFIRMED_ENGINE_CALL_PREFIX, dial_was_not_placed
from apps.api.callbacks import service as callbacks
from apps.api.campaigns import service as campaigns
from apps.api.core.errors import ProblemError
from apps.api.core.redis import get_redis
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine import outage
from apps.api.engine.fake import FakeEngine
from apps.api.engine.vendor_http import (
    EngineRejectedError,
    EngineUnreachableError,
    unreachable_error,
    vendor_request,
)
from apps.workers import callbacks as callback_worker
from apps.workers import campaign_dispatch
from apps.workers.campaign_dispatch import ACTIVE_STATUSES
from calevate_shared.engine import CallContext
from sqlalchemy import text
from tests.dispatch_budget_test import _contacts, _dlt_rows, _launched_campaign, _tenant

_MINE: list[uuid.UUID] = []


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    """11:00 IST, so no dial here is refused by the clock."""
    fixed = datetime(2026, 8, 11, 5, 30, tzinfo=UTC) + timedelta(hours=5, minutes=30)
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: fixed)


@pytest.fixture(scope="module", autouse=True)
async def _settle_what_this_module_started() -> AsyncIterator[None]:
    """A `running` campaign or a live call left behind is dialled or counted by every later
    platform-wide tick, so this module's tenants are quietened on the way out."""
    yield
    for tenant_id in _MINE:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE campaigns SET status = 'cancelled' WHERE status = 'running'")
            )
            await session.execute(
                text(
                    "UPDATE calls SET status = 'completed', updated_at = now() "
                    f"WHERE status IN {ACTIVE_STATUSES!r}"
                )
            )


class _Engine(FakeEngine):
    """A fake whose `POST /calls` raises what the shared ladder raises for a transport
    failure, and whose reference search answers from `placed` or fails while `down`."""

    def __init__(self, failure: httpx.HTTPError | None) -> None:
        super().__init__()
        self.failure = failure
        self.down = True
        self.dials = 0
        self.probes = 0
        self.placed: dict[str, str] = {}

    async def start_outbound_call(self, ref: str, to: str, ctx: CallContext) -> str:
        self.dials += 1
        if self.failure is not None:
            raise unreachable_error(self.failure)
        return await super().start_outbound_call(ref, to, ctx)

    async def find_placed_call(self, reference: str) -> str | None:
        self.probes += 1
        if self.down:
            raise unreachable_error(httpx.ConnectError("refused"))
        return self.placed.get(reference)


def _use(monkeypatch: pytest.MonkeyPatch, engine: FakeEngine) -> None:
    for target in (
        "apps.api.agents.service.get_engine",
        "apps.api.engine.outage.get_engine",
        "apps.workers.campaign_dispatch.get_engine",
        "apps.workers.callbacks.get_engine",
    ):
        monkeypatch.setattr(target, lambda: engine)


def _quiet_alarms(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []
    monkeypatch.setattr(outage, "alert", lambda stage, code, **kw: seen.append(code))
    monkeypatch.setattr(outage, "resolve_alert", lambda stage, code, **kw: seen.append(f"-{code}"))
    return seen


async def _campaign(phones: tuple[str, ...]) -> tuple[uuid.UUID, uuid.UUID]:
    tenant_id, agent_id = await _tenant()
    _MINE.append(tenant_id)
    number_id, template_id = await _dlt_rows(tenant_id, agent_id)
    campaign_id = await _launched_campaign(
        tenant_id, agent_id, number_id, template_id, name="Outage", phones=phones
    )
    return tenant_id, campaign_id


async def _calls(tenant_id: uuid.UUID) -> list[tuple[str, str, str | None]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT id, status, not_placed_reason FROM calls "
                    "WHERE direction = 'outbound' ORDER BY created_at, id"
                )
            )
        ).all()
    return [(str(r[0]), str(r[1]), r[2]) for r in rows]


async def _age_calls(tenant_id: uuid.UUID, minutes: int) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE calls SET created_at = now() - make_interval(mins => :m) "
                "WHERE direction = 'outbound'"
            ),
            {"m": minutes},
        )


async def _let_probe_run() -> None:
    """The probe interval passing, without waiting thirty seconds."""
    await get_redis().delete(outage._key("probe"))


# ------------------------------------------------------------------ the ladder's half


@pytest.mark.parametrize(
    ("failure", "sent"),
    [
        (httpx.ConnectError("refused"), False),
        (httpx.ConnectTimeout("slow handshake"), False),
        (httpx.PoolTimeout("no connection free"), False),
        (httpx.ReadTimeout("no answer"), True),
        (httpx.RemoteProtocolError("reset mid-response"), True),
    ],
)
async def test_a_transport_failure_says_whether_the_request_could_have_arrived(
    failure: httpx.HTTPError, sent: bool
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise failure

    async with httpx.AsyncClient(
        base_url="https://api.example.invalid", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(EngineUnreachableError) as caught:
            await vendor_request(client, "POST", "/calls", engine="hold-test", route="/calls")
    assert caught.value.code == "engine_unreachable"
    assert caught.value.request_sent is sent
    # Only a request that never left proves nobody was rung.
    assert dial_was_not_placed(caught.value) is not sent


def test_only_the_engines_own_failures_count_toward_the_hold() -> None:
    assert outage.counts_as_engine_down(unreachable_error(httpx.ReadTimeout("t")))
    assert outage.counts_as_engine_down(EngineRejectedError(status=503))
    assert not outage.counts_as_engine_down(EngineRejectedError(status=400))
    assert not outage.counts_as_engine_down(
        ProblemError(kind="transient", code="engine_rate_limited", title="t", detail="d")
    )
    assert not outage.counts_as_engine_down(RuntimeError("ours"))


# ------------------------------------------------------------------ the hold itself


async def test_one_failure_is_a_blip_two_hold_the_platform_and_a_success_resets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _quiet_alarms(monkeypatch)
    await outage.note_dial_failure()
    assert not await outage.hold_is_on()
    await outage.note_dial_success()
    await outage.note_dial_failure()
    assert not await outage.hold_is_on(), "a success between two failures breaks the run"

    await outage.note_dial_failure()
    assert await outage.hold_is_on()
    await outage.note_dial_failure()
    assert seen == ["engine_dial_hold"], "one page per hold, not one per failure"


async def test_a_held_dial_is_refused_and_the_engine_is_probed_at_most_once_an_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _Engine(failure=None)
    _use(monkeypatch, engine)
    seen = _quiet_alarms(monkeypatch)
    await outage.note_dial_failure()
    await outage.note_dial_failure()

    first = await outage.dial_hold_refusal()
    second = await outage.dial_hold_refusal()
    assert first is not None and first.code == "engine_outage_hold"
    assert second is not None
    assert engine.probes == 1, "the second refusal did not ask the vendor again"
    assert dial_was_not_placed(first), "a held dial rang nobody"

    engine.down = False
    await _let_probe_run()
    assert await outage.dial_hold_refusal() is None
    assert not await outage.hold_is_on()
    assert seen == ["engine_dial_hold", "-engine_dial_hold"]
    # Half the lines for the first ticks after it answers, never below one.
    assert await outage.resume_budget(5) == 3
    assert await outage.resume_budget(1) == 1
    assert await outage.resume_budget(0) == 0


async def test_an_engine_that_cannot_be_probed_is_not_held_on_a_guess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use(monkeypatch, FakeEngine())
    _quiet_alarms(monkeypatch)
    await outage.note_dial_failure()
    await outage.note_dial_failure()
    assert await outage.dial_hold_refusal() is None
    assert not await outage.hold_is_on()


async def test_without_redis_the_hold_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Broken:
        def __getattr__(self, name: str) -> Any:
            async def fail(*args: Any, **kwargs: Any) -> Any:
                raise ConnectionError("redis is down")

            return fail

    monkeypatch.setattr(outage, "get_redis", lambda: _Broken())
    await outage.note_dial_failure()
    await outage.note_dial_success()
    assert not await outage.hold_is_on()
    assert await outage.dial_hold_refusal() is None
    assert await outage.resume_budget(4) == 4


async def test_a_probe_that_answers_still_dials_when_the_lift_cannot_be_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _Engine(failure=None)
    engine.down = False
    _use(monkeypatch, engine)
    _quiet_alarms(monkeypatch)
    await outage.note_dial_failure()
    await outage.note_dial_failure()

    async def no_lift() -> None:
        raise ConnectionError("redis went away")

    monkeypatch.setattr(outage, "_lift", no_lift)
    assert await outage.dial_hold_refusal() is None


# ------------------------------------------------------------------ the campaign path


async def test_a_connection_never_made_spends_no_attempt_and_stops_the_batch_asking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, campaign_id = await _campaign(("9876650001", "9876650002", "9876650003"))
    engine = _Engine(failure=httpx.ConnectError("refused"))
    _use(monkeypatch, engine)
    _quiet_alarms(monkeypatch)

    result = await campaign_dispatch._dispatch_for_campaign(
        tenant_id, campaign_id, 3, campaigns.DEFAULT_RETRY_POLICY
    )

    assert result == {"dialled": 0, "blocked": 3, "exhausted": 0}, result
    assert engine.dials == 1, "the rest of the batch waited instead of asking again"
    assert await _contacts(tenant_id, campaign_id) == [("pending", 0)] * 3
    assert [c[1:] for c in await _calls(tenant_id)] == [("failed", "refused")]
    async with tenant_session(tenant_id) as session:
        waits = (
            await session.execute(
                text(
                    "SELECT count(*) FROM campaign_contacts WHERE campaign_id = :c "
                    "AND next_attempt_at BETWEEN now() + interval '30 seconds' "
                    "AND now() + interval '5 minutes'"
                ),
                {"c": campaign_id},
            )
        ).scalar()
    assert waits == 3, "a short wait, not the thirty minutes a refusal about us is given"


async def test_lost_answers_hold_the_platform_and_are_settled_by_reference_once_it_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, campaign_id = await _campaign(("9876650011", "9876650012", "9876650013"))
    engine = _Engine(failure=httpx.ReadTimeout("no answer"))
    _use(monkeypatch, engine)
    seen = _quiet_alarms(monkeypatch)

    result = await campaign_dispatch._dispatch_for_campaign(
        tenant_id, campaign_id, 3, campaigns.DEFAULT_RETRY_POLICY
    )

    # Two dials whose answer was lost, then the hold: the third is refused unasked.
    assert engine.dials == 2
    assert result == {"dialled": 2, "blocked": 1, "exhausted": 0}, result
    assert await _contacts(tenant_id, campaign_id) == [
        ("dialing", 1),
        ("dialing", 1),
        ("pending", 0),
    ], "nobody is marked failed for the vendor's outage"
    assert seen == ["engine_dial_hold"]
    calls = await _calls(tenant_id)
    assert [c[1] for c in calls] == ["queued", "queued"]

    # Held: the tick claims nobody and the campaign is not completed under it.
    outcome = await campaign_dispatch._run_tick()
    assert engine.dials == 2, outcome
    async with tenant_session(tenant_id) as session:
        status = (
            await session.execute(
                text("SELECT status FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar()
    assert status == "running"

    # Asked too soon, or while the engine is still silent, nothing moves.
    await _age_calls(tenant_id, 11)
    assert await campaign_dispatch._resolve_unconfirmed_dials(tenant_id, campaign_id) == 0

    # It answers: the probe lifts the hold, one dial was placed and one never was.
    engine.down = False
    engine.failure = None
    engine.placed = {calls[1][0]: "out_found_1"}
    await _let_probe_run()
    assert await outage.dial_hold_refusal() is None
    queued: list[dict[str, Any]] = []

    async def capture(job: str, payload: dict[str, Any], **kwargs: Any) -> None:
        queued.append(payload)

    monkeypatch.setattr(campaign_dispatch, "enqueue", capture)
    assert await campaign_dispatch._resolve_unconfirmed_dials(tenant_id, campaign_id) == 2

    assert [p["execution_id"] for p in queued] == ["out_found_1"], "the placed call is adopted"
    assert await _contacts(tenant_id, campaign_id) == [
        ("pending", 0),
        ("dialing", 1),
        ("pending", 0),
    ], "the one never placed is retried with its attempt refunded"
    after = await _calls(tenant_id)
    assert after[0][1:] == ("failed", "dial_lost")
    assert after[1][1] == "queued"


async def test_a_stranded_lost_answer_is_never_reaped_onto_the_ladder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, campaign_id = await _campaign(("9876650021",))
    engine = _Engine(failure=httpx.ReadTimeout("no answer"))
    _use(monkeypatch, engine)
    _quiet_alarms(monkeypatch)
    await campaign_dispatch._dispatch_for_campaign(
        tenant_id, campaign_id, 1, campaigns.DEFAULT_RETRY_POLICY
    )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE campaign_contacts SET last_attempt_at = now() - interval '3 hours' "
                "WHERE campaign_id = :c"
            ),
            {"c": campaign_id},
        )
        reaped = await campaign_dispatch._reap_stuck_dialing(
            session,
            campaign_id,
            tenant_id=tenant_id,
            max_attempts=3,
            retry_policy=campaigns.DEFAULT_RETRY_POLICY,
        )
    assert reaped == 0
    assert await _contacts(tenant_id, campaign_id) == [("dialing", 1)]


# ------------------------------------------------------------------ the call-back path


async def _callback_on(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, *, call_status: str, reason: str | None, ecid: str
) -> uuid.UUID:
    phone = "+919876650031"
    async with tenant_session(tenant_id) as session:
        booked = await callbacks.book(
            session,
            callback_id=uuid7(),
            tenant_id=tenant_id,
            agent_id=agent_id,
            source_call_id=None,
            source_execution_id=f"exec_{uuid.uuid4().hex[:10]}",
            lead_id=None,
            phone_e164=phone,
            requested_at=datetime.now(UTC) - timedelta(minutes=1),
            booked_at=datetime.now(UTC),
            note=None,
            language=None,
        )
        assert booked is not None
        callback_id = booked[0]
        assert [c.id for c in await callbacks.claim_due(session, limit=5)] == [callback_id]
        call_id = uuid7()
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                "to_e164, status, not_placed_reason, created_at, updated_at) VALUES "
                "(:id, :tid, :aid, :ecid, 'outbound', :to_e, :st, :why, now(), now())"
            ),
            {
                "id": call_id,
                "tid": tenant_id,
                "aid": agent_id,
                "ecid": ecid.format(call_id=call_id),
                "to_e": phone,
                "st": call_status,
                "why": reason,
            },
        )
        await callbacks.link_callback_to_call(callback_id, phone_e164=phone)(session, call_id)
    return callback_id


async def test_a_call_back_whose_answer_was_lost_waits_on_its_call_rather_than_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.callback_dispatch_test import _book, _dialable_tenant, _row

    tenant_id, agent_id = await _dialable_tenant()
    _MINE.append(tenant_id)
    callback_id = await _book(tenant_id, agent_id)
    engine = _Engine(failure=httpx.ReadTimeout("no answer"))
    _use(monkeypatch, engine)
    _quiet_alarms(monkeypatch)

    outcome = await callback_worker.dispatch_due_callbacks(tenant_id, slots=5)

    assert engine.dials == 1
    assert outcome["dialled"] == 1, "it may hold a line, so the tick's budget counts it"
    row = await _row(tenant_id, callback_id)
    assert row["status"] == "dialing", "not settled failed for the vendor's silence"
    assert row["last_call_id"] is not None


async def test_a_call_back_whose_dial_never_reached_the_engine_is_dialled_again() -> None:
    tenant_id, agent_id = await _tenant()
    _MINE.append(tenant_id)
    callback_id = await _callback_on(
        tenant_id,
        agent_id,
        call_status="failed",
        reason="dial_lost",
        ecid=UNCONFIRMED_ENGINE_CALL_PREFIX + "{call_id}",
    )
    async with tenant_session(tenant_id) as session:
        assert await callbacks.settle_dialled(session, unconfirmed_wait=True) == 1
        row = await callbacks.get_callback(session, callback_id)
    assert row is not None
    assert row["status"] == "scheduled"
    assert row["attempts"] == 0
    assert row["last_refusal_rule"] == "engine_unreachable"


async def test_a_call_back_waiting_on_a_lost_answer_outlives_the_stuck_reaper() -> None:
    tenant_id, agent_id = await _tenant()
    _MINE.append(tenant_id)
    callback_id = await _callback_on(
        tenant_id,
        agent_id,
        call_status="queued",
        reason=None,
        ecid=UNCONFIRMED_ENGINE_CALL_PREFIX + "{call_id}",
    )
    later = datetime.now(UTC) + callbacks.STUCK_DIALING_AFTER + timedelta(minutes=1)
    async with tenant_session(tenant_id) as session:
        assert await callbacks.settle_dialled(session, now=later, unconfirmed_wait=True) == 0
        waiting = await callbacks.get_callback(session, callback_id)
        # An engine that can never say still ends it, as before.
        assert await callbacks.settle_dialled(session, now=later) == 1
        ended = await callbacks.get_callback(session, callback_id)
    assert waiting is not None and waiting["status"] == "dialing"
    assert ended is not None and ended["status"] == "failed"


async def test_a_call_back_refused_by_the_hold_waits_with_a_plain_reason() -> None:
    assert callback_worker._WAIT_REFUSALS["engine_outage_hold"] == (
        callback_worker.ENGINE_DOWN_REASON
    )
    assert callback_worker._WAIT_REFUSALS["engine_unreachable"] == (
        callback_worker.ENGINE_DOWN_REASON
    )
