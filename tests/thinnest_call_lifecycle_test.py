"""ThinnestAI's call lifecycle beside Pipecat's (D-678 phase 2, lane B): the workspace's call
ceiling and its 429, the refusals `POST /calls` documents, the recall that must not hang up
a live conversation, the zero-credit script, the recording source, the replay window, the
BYOK check and the charge sweep. Shapes come from the 7 Oct 2026 snapshot of the vendor's
docs (`thinnest-findings/mirror/snapshots/2026-10-07/pages/api-reference/`).

Run: uv run python -m pytest -q tests/thinnest_call_lifecycle_test.py
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import signed_intake  # apps/voice-runtime is on the pytest path (D-18)
from apps.api.agents import engine_choice
from apps.api.agents import service as agents_service
from apps.api.agents.service import dial_was_not_placed
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine import carrier_pacing, reset_engine_cache, vendor_http
from apps.api.engine.fake import FakeEngine
from apps.api.engine.recording_source import RecordingFetchRules
from apps.api.engine.thinnest import BASE_URL, PAUSED_LINE_MESSAGE, ThinnestEngine
from apps.api.engine.vendor_http import (
    RECIPIENT_OPTED_OUT_CODE,
    EngineRateLimitedError,
    EngineRejectedError,
    vendor_request,
)
from apps.workers import engine_charges, storage
from calevate_shared.config import Settings
from calevate_shared.engine import CallContext, ExecutionSnapshot, RecallOutcome
from sqlalchemy import text
from tests.callback_dispatch_test import _dialable_tenant

Handler = Callable[[httpx.Request], httpx.Response]


def _engine(handler: Handler) -> ThinnestEngine:
    return ThinnestEngine(
        api_key="ta_live_test",
        client=httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"Authorization": "Bearer ta_live_test"},
            transport=httpx.MockTransport(handler),
        ),
    )


def _recorder(responses: dict[tuple[str, str], httpx.Response]) -> tuple[Handler, list[Any]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path.removeprefix("/api/v1")
        return responses.get((request.method, path), httpx.Response(404, json={"error": "x"}))

    return handler, seen


def _greeting() -> httpx.Response:
    return httpx.Response(200, json={"id": "ag_1", "greeting": "Idi AI assistant."})


# --- the workspace's call ceiling --------------------------------------------------


@pytest.fixture
def on_thinnest(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(carrier_pacing, "get_engine", lambda: SimpleNamespace(name="thinnest"))
    monkeypatch.setenv("THINNEST_MAX_CONCURRENT_CALLS", "5")
    monkeypatch.setenv("INBOUND_RESERVE_RATIO", "0.3")
    monkeypatch.setenv("CARRIER_CONCURRENCY", "3")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_the_ceiling_defaults_to_the_pay_as_you_go_five() -> None:
    assert Settings.model_fields["thinnest_max_concurrent_calls"].default == 5


def test_on_thinnest_the_pool_is_its_ceiling_less_the_inbound_reserve(on_thinnest: None) -> None:
    assert carrier_pacing.engine_concurrency_cap() == 5
    assert carrier_pacing.outbound_line_pool() == 3


def test_the_carrier_pool_is_unchanged_on_any_other_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(carrier_pacing, "get_engine", lambda: SimpleNamespace(name="pipecat"))
    monkeypatch.setenv("CARRIER_CONCURRENCY", "3")
    monkeypatch.setenv("THINNEST_MAX_CONCURRENT_CALLS", "50")
    get_settings.cache_clear()
    try:
        assert carrier_pacing.engine_concurrency_cap() is None
        assert carrier_pacing.outbound_line_pool() == 2
    finally:
        get_settings.cache_clear()


class _FakeRedis:
    def __init__(self) -> None:
        self.ttl_ms: dict[str, int] = {}

    async def pttl(self, key: str) -> int:
        return self.ttl_ms.get(key, -2)

    async def set(self, key: str, value: str, px: int) -> bool:
        self.ttl_ms[key] = px
        return True


async def test_a_429_holds_every_dial_off_for_at_least_a_minute(
    on_thinnest: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeRedis()
    monkeypatch.setattr(carrier_pacing, "get_redis", lambda: fake)
    assert await carrier_pacing.dial_backoff_remaining_s() == 0.0
    assert await carrier_pacing.start_dial_backoff(None) == carrier_pacing.ENGINE_BACKOFF_DEFAULT_S
    assert await carrier_pacing.dial_backoff_remaining_s() == 60.0
    # A longer hold-off is taken, bounded; a shorter one never shortens a running one.
    assert await carrier_pacing.start_dial_backoff(86_400) == carrier_pacing.ENGINE_BACKOFF_MAX_S
    await carrier_pacing.start_dial_backoff(5)
    assert await carrier_pacing.dial_backoff_remaining_s() == carrier_pacing.ENGINE_BACKOFF_MAX_S


async def test_the_hold_off_is_never_read_on_an_engine_without_a_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(carrier_pacing, "get_engine", lambda: SimpleNamespace(name="pipecat"))

    def _no_redis() -> None:
        raise AssertionError("the carrier path must not read the engine hold-off")

    monkeypatch.setattr(carrier_pacing, "get_redis", _no_redis)
    assert await carrier_pacing.dial_backoff_remaining_s() == 0.0


def test_a_dial_inside_the_hold_off_is_refunded_not_spent() -> None:
    refusal = carrier_pacing.engine_backoff_refusal()
    assert refusal.code == "engine_rate_limited"
    assert dial_was_not_placed(refusal) is True


async def test_a_throttle_carries_the_vendors_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    """place-call.md:454-460: 429 with `Retry-After` in seconds, over the ladder's ceiling."""

    async def _no_sleep(_: float) -> None:
        raise AssertionError("a 60-second Retry-After is not slept through inside the ladder")

    monkeypatch.setattr(vendor_http.asyncio, "sleep", _no_sleep)
    answer = httpx.Response(
        429,
        headers={"Retry-After": "60"},
        json={"error": "Already running 3 calls. Wait for one to finish."},
    )
    async with httpx.AsyncClient(
        base_url=BASE_URL, transport=httpx.MockTransport(lambda _: answer)
    ) as client:
        with pytest.raises(EngineRateLimitedError) as raised:
            await vendor_request(client, "POST", "/calls", engine="thinnest", route="/calls")
    assert raised.value.retry_after_s == 60.0
    assert raised.value.code == "engine_rate_limited"


# --- the line count, against the database --------------------------------------------

_TENANTS: list[uuid.UUID] = []


@pytest.fixture
async def _settle_rows() -> AsyncIterator[None]:
    yield
    for tenant_id in _TENANTS:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "UPDATE calls SET status = 'completed', updated_at = now() "
                    "WHERE status = 'queued'"
                )
            )
    _TENANTS.clear()


async def _routed_tenant() -> tuple[uuid.UUID, uuid.UUID]:
    tenant_id, agent_id = uuid7(), uuid7()
    _TENANTS.append(tenant_id)
    ref = f"tlines-{uuid.uuid4().hex[:10]}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO organizations (id, name, slug, status, created_at, updated_at) "
                "VALUES (:id, 'Line Motors', :slug, 'active', now(), now())"
            ),
            {"id": tenant_id, "slug": ref},
        )
        await session.execute(
            text(
                "INSERT INTO agents (id, tenant_id, name, direction, disclosure_line, "
                "ai_disclosure_line, recording_notice_line, caller_memory_notice_line, status, "
                "engine, engine_agent_ref, created_at, updated_at) VALUES (:id, :tid, 'Lines', "
                "'both', 'Idi AI assistant.', 'Idi AI assistant.', 'This call is being "
                "recorded.', 'I keep a short note of what you ask about.', 'live', 'pipecat', "
                ":ref, now(), now())"
            ),
            {"id": agent_id, "tid": tenant_id, "ref": ref},
        )
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('pipecat', :ref, :tid, :aid, true, "
                "now(), now())"
            ),
            {"ref": ref, "tid": tenant_id, "aid": agent_id},
        )
    return tenant_id, agent_id


async def _in_use(tenant_id: uuid.UUID) -> int:
    async with tenant_session(tenant_id) as session:
        return int(
            (
                await session.execute(
                    agents_service._ENGINE_LINES_IN_USE_SQL,
                    {
                        "statuses": agents_service._ENGINE_LINE_STATUSES,
                        "horizon": carrier_pacing.ENGINE_LINE_HORIZON.total_seconds(),
                    },
                )
            ).scalar_one()
        )


async def test_a_dial_is_refused_once_the_outbound_lines_are_held(
    _settle_rows: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ThinnestAI call row stays `queued` for the whole call, so a queued outbound row is
    a held line; the count is platform-wide, so the pool is set relative to what is there."""
    tenant_id, agent_id = await _routed_tenant()
    before = await _in_use(tenant_id)
    monkeypatch.setattr(agents_service, "outbound_line_pool", lambda: before + 1)
    async with tenant_session(tenant_id) as session:
        await agents_service._hold_engine_line(session)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "created_at, updated_at) VALUES (:id, :tid, :aid, :ecid, 'outbound', 'queued', "
                "now(), now())"
            ),
            {"id": uuid7(), "tid": tenant_id, "aid": agent_id, "ecid": f"out_{uuid.uuid4().hex}"},
        )
    assert await _in_use(tenant_id) == before + 1
    with pytest.raises(ProblemError) as raised:
        async with tenant_session(tenant_id) as session:
            await agents_service._hold_engine_line(session)
    assert raised.value.code == "carrier_lines_busy"
    assert dial_was_not_placed(raised.value) is True


# --- the same two limits, through `dispatch_call` -------------------------------------


@pytest.fixture
def engine_capped(monkeypatch: pytest.MonkeyPatch) -> list[float | None]:
    """`dispatch_call` on an engine that dials on its own account with a call ceiling: no
    carrier of ours, a cap of five. Returns the hold-offs `start_dial_backoff` was asked
    for; the hold-off and the pool are set per test."""
    reset_engine_cache()
    started: list[float | None] = []

    async def _start(retry_after_s: float | None) -> float:
        started.append(retry_after_s)
        return float(retry_after_s or 0)

    async def _clear() -> float:
        return 0.0

    monkeypatch.setattr(agents_service, "outbound_carrier", lambda: None)
    monkeypatch.setattr(agents_service, "engine_concurrency_cap", lambda: 5)
    monkeypatch.setattr(agents_service, "dial_backoff_remaining_s", _clear)
    monkeypatch.setattr(agents_service, "start_dial_backoff", _start)
    monkeypatch.setattr(agents_service, "outbound_line_pool", lambda: 10**6)
    return started


async def _dial(tenant_id: uuid.UUID, agent_id: uuid.UUID, phone: str) -> str:
    async with tenant_session(tenant_id) as session:
        return await agents_service.dispatch_call(
            session, tenant_id=tenant_id, agent_id=agent_id, lead_id=None, phone_e164=phone
        )


async def _call_statuses(tenant_id: uuid.UUID, phone: str) -> list[str]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(text("SELECT status FROM calls WHERE to_e164 = :p"), {"p": phone})
        ).all()
    return [str(row[0]) for row in rows]


def _phone() -> str:
    return f"+9198765{uuid.uuid4().int % 10**5:05d}"


async def test_a_dial_inside_the_hold_off_is_refused_before_its_row_exists(
    engine_capped: list[float | None], monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, agent_id = await _dialable_tenant()

    async def _held() -> float:
        return 30.0

    monkeypatch.setattr(agents_service, "dial_backoff_remaining_s", _held)
    phone = _phone()
    with pytest.raises(ProblemError) as raised:
        await _dial(tenant_id, agent_id, phone)
    assert raised.value.code == "engine_rate_limited"
    assert dial_was_not_placed(raised.value) is True
    assert await _call_statuses(tenant_id, phone) == []


async def test_a_full_engine_pool_refuses_the_dial_before_its_row_exists(
    engine_capped: list[float | None], monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, agent_id = await _dialable_tenant()
    monkeypatch.setattr(agents_service, "outbound_line_pool", lambda: 0)
    phone = _phone()
    with pytest.raises(ProblemError) as raised:
        await _dial(tenant_id, agent_id, phone)
    assert raised.value.code == "carrier_lines_busy"
    assert await _call_statuses(tenant_id, phone) == []


async def test_the_vendors_429_starts_the_hold_off_and_closes_the_row(
    engine_capped: list[float | None], monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, agent_id = await _dialable_tenant()

    async def _throttled(self: object, ref: str, to: str, ctx: object) -> str:
        raise EngineRateLimitedError(retry_after_s=120)

    monkeypatch.setattr(FakeEngine, "start_outbound_call", _throttled)
    phone = _phone()
    with pytest.raises(EngineRateLimitedError):
        await _dial(tenant_id, agent_id, phone)
    assert engine_capped == [120]
    # Nothing rang, so the intent row is closed rather than left holding a line.
    assert await _call_statuses(tenant_id, phone) == ["failed"]


async def test_a_capped_engine_that_dials_holds_a_line_for_the_call(
    engine_capped: list[float | None], _settle_rows: None
) -> None:
    tenant_id, agent_id = await _dialable_tenant()
    _TENANTS.append(tenant_id)
    phone = _phone()
    assert await _dial(tenant_id, agent_id, phone)
    assert await _call_statuses(tenant_id, phone) == ["queued"]
    assert engine_capped == []


# --- what `POST /calls` refuses ------------------------------------------------------


async def test_a_403_naming_the_person_settles_the_contact() -> None:
    """`opted_out` and `do_not_call` are the person; the code, never the sentence, decides
    (snapshots/2026-10-08/pages/api-reference/errors.md:18-37, :113-114)."""
    for code in ("opted_out", "do_not_call"):
        handler, seen = _recorder(
            {
                ("GET", "/agents/ag_1"): _greeting(),
                ("POST", "/calls"): httpx.Response(
                    403, json={"error": "Reworded in any release.", "code": code}
                ),
            }
        )
        with pytest.raises(ProblemError) as raised:
            await _engine(handler).start_outbound_call("ag_1", "+919876543210", CallContext())
        assert raised.value.code == RECIPIENT_OPTED_OUT_CODE
        assert dial_was_not_placed(raised.value) is True
        # No probe of the key: one read of the greeting, one dial.
        assert [r.method for r in seen] == ["GET", "POST"]


async def test_a_403_on_a_key_that_cannot_dial_is_never_read_as_an_opt_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.engine import thinnest

    raised_alarms: list[str] = []
    monkeypatch.setattr(thinnest, "alert", lambda _s, code, **_kw: raised_alarms.append(code))
    for code in ("key_scope_build", "key_scope_read"):
        handler, _ = _recorder(
            {
                ("GET", "/agents/ag_1"): _greeting(),
                ("POST", "/calls"): httpx.Response(
                    403, json={"error": "This API key is a build key.", "code": code}
                ),
            }
        )
        with pytest.raises(EngineRejectedError) as raised:
            await _engine(handler).start_outbound_call("ag_1", "+919876543210", CallContext())
        assert raised.value.vendor_status == 403 and raised.value.vendor_code == code
        # Refunded to the ladder rather than settled: about the account, not the person.
        assert dial_was_not_placed(raised.value) is True
    assert raised_alarms == ["engine_key_cannot_place_calls"] * 2


async def test_a_403_with_no_code_keeps_its_generic_meaning() -> None:
    handler, _ = _recorder(
        {
            ("GET", "/agents/ag_1"): _greeting(),
            ("POST", "/calls"): httpx.Response(403, json={"error": "refused"}),
        }
    )
    with pytest.raises(EngineRejectedError) as raised:
        await _engine(handler).start_outbound_call("ag_1", "+919876543210", CallContext())
    assert raised.value.vendor_code is None and raised.value.request_refused


# --- recall and the paused line -------------------------------------------------------


async def test_a_ringing_call_is_still_pulled_back() -> None:
    handler, seen = _recorder(
        {
            ("GET", "/calls/out_1"): httpx.Response(200, json={"id": "out_1", "status": "ringing"}),
            ("DELETE", "/calls/out_1"): httpx.Response(202, json={"status": "ringing"}),
        }
    )
    assert await _engine(handler).end_call("out_1") == RecallOutcome.ALREADY_RUNNING
    assert [r.method for r in seen] == ["GET", "DELETE"]


async def test_a_pause_switches_the_line_off_and_leaves_the_script_alone() -> None:
    """`answersCalls: false` with the reasonless sentence (snapshots/2026-10-08/pages/
    api-reference/agents/update-agent.md:940-1016): no AI answers, so no 60-second call is
    billed, and the opening (with its recording notice) is not read where nothing records."""
    handler, seen = _recorder({("PATCH", "/agents/ag_1"): httpx.Response(200, json={})})
    await _engine(handler).override_call_script(
        "ag_1", opening_line="This call is recorded. We cannot take your call.", system_prompt="x"
    )
    body = json.loads(seen[0].content)
    assert body["voice"] == {"answersCalls": False, "unavailableMessage": PAUSED_LINE_MESSAGE}
    # The words are replaced as the Protocol requires; nothing speaks them while it is off.
    assert body["greeting"] == "This call is recorded. We cannot take your call."
    assert len(PAUSED_LINE_MESSAGE) <= 300 and PAUSED_LINE_MESSAGE.isascii()


# --- the recording source --------------------------------------------------------------


def _snapshot(**update: Any) -> ExecutionSnapshot:
    base = ExecutionSnapshot(
        engine_call_id="call_ref_1",
        direction="inbound",
        status="completed",
        raw_status="completed",
        terminal=True,
        billable_ready=True,
        engine="thinnest",
    )
    return base.model_copy(update=update)


def test_a_finished_call_is_fetched_from_the_authenticated_endpoint_on_our_host_only() -> None:
    source = _engine(lambda _: httpx.Response(404)).recording_source(_snapshot())
    assert source is not None
    assert source.url == f"{BASE_URL}/calls/call_ref_1/recording"
    assert source.rules.allowed_hosts == frozenset({"app.thinnest.ai"})
    assert source.rules.content_types == frozenset({"audio/mpeg"})
    assert source.auth_hosts == frozenset({"app.thinnest.ai"})
    assert source.auth_headers["Authorization"] == "Bearer ta_live_test"


def test_a_missed_call_with_no_link_has_nothing_to_fetch() -> None:
    engine = _engine(lambda _: httpx.Response(404))
    assert engine.recording_source(_snapshot(raw_status="missed", status="no_answer")) is None
    assert engine.recording_source(_snapshot(terminal=False, raw_status="connected")) is None


_RULES = RecordingFetchRules(
    allowed_hosts=frozenset({"app.thinnest.ai"}),
    content_types=frozenset({"audio/mpeg"}),
    not_ready_status=404,
    gone_status=410,
)


def _answer(status: int, **headers: str) -> httpx.Response:
    return httpx.Response(status, headers=headers)


def test_not_ready_waits_for_the_vendors_delay_without_failing() -> None:
    with pytest.raises(storage.RecordingNotReadyError) as raised:
        storage._apply_source_rules(_answer(404, **{"Retry-After": "60"}), _RULES)
    assert raised.value.defer_score == 60_000


def test_a_call_that_was_not_recorded_is_an_outcome_not_a_retry() -> None:
    with pytest.raises(storage.RecordingUnavailableError) as raised:
        storage._apply_source_rules(_answer(404), _RULES)
    assert raised.value.reason == "not_recorded"


def test_a_deleted_recording_is_terminal() -> None:
    with pytest.raises(storage.RecordingUnavailableError) as raised:
        storage._apply_source_rules(_answer(410), _RULES)
    assert raised.value.reason == "gone"


def test_audio_served_as_anything_but_mp3_is_refused() -> None:
    with pytest.raises(storage.StorageUnavailableError):
        storage._apply_source_rules(_answer(200, **{"Content-Type": "text/html"}), _RULES)
    storage._apply_source_rules(_answer(200, **{"Content-Type": "audio/mpeg"}), _RULES)


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("https://app.thinnest.ai/api/v1/calls/x/recording", True),
        ("https://evil.app.thinnest.ai/x", False),
        ("https://s3.amazonaws.com/x", False),
        ("http://app.thinnest.ai/x", False),
    ],
)
def test_only_the_vendors_own_host_is_fetched(url: str, allowed: bool) -> None:
    assert storage._host_allowed(url, _RULES.allowed_hosts) is allowed


# --- the replay window ----------------------------------------------------------------


_INTAKE = signed_intake.SIGNED_INTAKES["thinnest"]
_NOW = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("delivered_at", "fresh"),
    [
        ("2026-10-07T08:59:58.000Z", True),
        ("2026-10-07T09:04:00Z", True),
        ("2026-10-07T08:54:59Z", False),
        ("2026-10-07T09:05:01Z", False),
        ("yesterday", False),
        ("2026-10-07T09:00:00", False),
        (None, False),
    ],
)
def test_a_delivery_time_outside_five_minutes_is_a_replay(
    delivered_at: str | None, fresh: bool
) -> None:
    """The window is on `x-thinnest-delivered-at`, never `sentAt` (`snapshots/2026-10-08/
    pages/api-reference/webhooks.md:129-131`); an absent or unreadable time is not fresh."""
    headers = {} if delivered_at is None else {"x-thinnest-delivered-at": delivered_at}
    assert signed_intake.delivery_is_fresh(_INTAKE, headers, now=_NOW) is fresh


# --- BYOK, read from the vendor --------------------------------------------------------


@pytest.mark.parametrize(
    ("using", "scope", "own"),
    [
        ("own", "all", True),
        ("developer", "all", True),
        ("none", "all", False),
        # Voice-only BYOK is how Studio is sold, per agent (D-688), not the whole workspace.
        ("own", "voice", False),
    ],
)
async def test_whose_keys_run_the_calls_is_read_from_get_byok(
    using: str, scope: str, own: bool
) -> None:
    handler, _ = _recorder(
        {
            ("GET", "/byok"): httpx.Response(
                200, json={"enabled": using != "none", "using": using, "scope": scope}
            )
        }
    )
    assert await _engine(handler).own_keys_in_use() is own


async def test_an_unreadable_byok_state_is_refused_not_read_as_off() -> None:
    handler, _ = _recorder({("GET", "/byok"): httpx.Response(200, json={"enabled": True})})
    with pytest.raises(ProblemError):
        await _engine(handler).own_keys_in_use()


@pytest.mark.parametrize(("setting", "vendor"), [(True, False), (False, True)])
async def test_a_publish_refuses_when_the_setting_and_the_vendor_disagree(
    setting: bool, vendor: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Keys:
        name = "thinnest"

        async def own_keys_in_use(self) -> bool:
            return vendor

    monkeypatch.setenv("THINNEST_BYOK_ENABLED", "true" if setting else "false")
    get_settings.cache_clear()
    try:
        with pytest.raises(ProblemError) as raised:
            await engine_choice._require_keys_mode_matches(_Keys())  # type: ignore[arg-type]
    finally:
        get_settings.cache_clear()
    assert raised.value.code == engine_choice.KEYS_MODE_MISMATCH


# --- the charge sweep ------------------------------------------------------------------


async def test_the_call_log_is_read_in_rupees_without_a_float() -> None:
    page = {
        "items": [
            {"id": "out_1", "agent": {"id": "ag_1"}, "costMicro": 18_400_000, "currency": "INR"},
            {"id": "call_2", "agent": None, "costMicro": None, "currency": "INR"},
            {"id": "call_3", "agent": {"id": "ag_1"}, "costMicro": 5, "currency": "USD"},
        ],
        "nextCursor": None,
    }
    handler, seen = _recorder({("GET", "/usage/calls"): httpx.Response(200, json=page)})
    listing = await _engine(handler).list_call_charges(since=date(2026, 10, 6))
    assert seen[0].url.params["from"] == "2026-10-06"
    assert [c.charged_inr for c in listing.charges] == [Decimal("18.4"), None]
    assert listing.charges[0].engine_agent_ref == "ag_1"
    assert listing.other_currency == 1
    assert listing.complete is False


@pytest.mark.parametrize(
    ("metered", "charged", "close"),
    [
        ("2.50", "2.50", True),
        ("2.50", "2.55", True),
        ("2.50", "2.75", False),
        ("100.00", "101.50", True),
        ("100.00", "103.00", False),
    ],
)
def test_the_tolerance_is_a_paisa_floor_or_two_percent(
    metered: str, charged: str, close: bool
) -> None:
    assert engine_charges.within_tolerance(Decimal(metered), Decimal(charged)) is close


async def test_the_sweep_is_a_no_op_on_an_engine_without_a_billing_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(engine_charges, "get_engine", lambda: SimpleNamespace(name="pipecat"))
    assert await engine_charges.reconcile_engine_charges({}) == "engine_without_charges"


async def test_the_sweep_alarms_on_a_rate_that_no_longer_matches_the_invoice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.engine.charges import EngineCharge, EngineChargeListing

    class _Engine:
        name = "thinnest"

        def holds_credentials(self) -> bool:
            return True

        async def list_call_charges(self, *, since: date) -> EngineChargeListing:
            return EngineChargeListing(
                charges=[
                    EngineCharge("out_1", "ag_1", Decimal("5.00")),
                    EngineCharge("out_2", "ag_1", Decimal("2.50")),
                    EngineCharge("out_3", "ag_9", Decimal("2.50")),
                    EngineCharge("out_4", "ag_1", None),
                ],
                complete=True,
            )

    metered = {"out_1": Decimal("2.50"), "out_2": Decimal("2.50")}
    tenant = uuid7()

    async def _tenant_of(_engine: str, ref: str | None) -> uuid.UUID | None:
        return tenant if ref == "ag_1" else None

    async def _compare(engine: str, charge: Any, tally: Any) -> None:
        if charge.charged_inr is None:
            return
        tally.compared += 1
        if await _tenant_of(engine, charge.engine_agent_ref) is None:
            tally.unmatched += 1
            return
        tally.matched += 1
        ours = metered[charge.engine_call_id]
        if not engine_charges.within_tolerance(ours, charge.charged_inr):
            tally.mismatched.append((charge.engine_call_id, ours, charge.charged_inr))

    alerts: list[tuple[str, str]] = []
    monkeypatch.setattr(engine_charges, "get_engine", lambda: _Engine())
    monkeypatch.setattr(engine_charges, "_compare", _compare)
    monkeypatch.setattr(
        engine_charges, "alert", lambda kind, code, **_: alerts.append((kind, code))
    )
    outcome = await engine_charges.reconcile_engine_charges({})
    assert "compared=3 matched=2 unmatched=1" in outcome
    assert "mismatched=1" in outcome
    assert alerts == [("WORKER_TERMINAL", "engine_charge_mismatch")]


def test_the_new_alarms_are_registered() -> None:
    from apps.api.core.alarm_severity import ALARM_SEVERITY

    for code in (
        "recording_source_gone",
        "engine_balance_exhausted",
        "engine_key_cannot_place_calls",
        "engine_charge_mismatch",
        "engine_charge_unmatched",
    ):
        assert code in ALARM_SEVERITY


def test_a_vendor_opt_out_is_settled_by_the_campaign_not_re_asked() -> None:
    """Refused before dialling, so no attempt is spent, and recorded under its own rule,
    which `_refuse_contact` settles as `dnc_blocked` rather than putting back on the ladder."""
    from apps.api.engine.vendor_http import recipient_opted_out_error
    from apps.workers import campaign_dispatch

    refusal = recipient_opted_out_error()
    assert campaign_dispatch._refused_on_our_side(refusal) is True
    assert campaign_dispatch._refusal_rule(refusal) == RECIPIENT_OPTED_OUT_CODE
