"""A platform AI provider's main leg failing reaches the admin, and keeps reaching them.

The founder's decision (10 Oct 2026), as properties a regression would break:

1. One or two failures alert nobody; three in ten minutes, or three in a row, do.
2. A success ends it: the episode closes and ONE "cleared" line goes out.
3. While it stays open the admin is reminded hourly, not every fifteen minutes and not never.
4. The failure log carries the HTTP status and the error class, never the provider's body.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

import httpx
import pytest
from apps.api.core import alert_admission, alerting, provider_health
from apps.api.core.alarm_severity import REPEAT_WHILE_OPEN_S, severity_of
from apps.api.core.redis import get_redis
from apps.api.core.settings import get_settings
from apps.api.db.session import untenanted_session
from sqlalchemy import text

OPERATOR = "sri@calevate.tech"
CODE = provider_health.ALARM_CODE
PLANTED_BODY = "caller said +919876543210 about the order"


class RecordingTransport:
    name = "recording"

    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []
        self.arrived = threading.Event()

    def send(self, *, to: str, subject: str, body: str, html: str | None = None) -> bool:
        self.sent.append({"to": to, "subject": subject, "body": body})
        self.arrived.set()
        return True


async def _forget_counts() -> None:
    redis = get_redis()
    keys = [key async for key in redis.scan_iter(match=f"{provider_health.KEY_PREFIX}:*")]
    if keys:
        await redis.delete(*keys)


@pytest.fixture
async def transport(monkeypatch: pytest.MonkeyPatch) -> Any:
    from apps.api.core import transport as transport_module

    alerting.reset_alerts()
    await _forget_counts()
    recorder = RecordingTransport()
    monkeypatch.setattr(transport_module, "get_transport", lambda: recorder)
    monkeypatch.setattr(get_settings(), "alerts_email", OPERATOR)
    monkeypatch.setattr(alerting, "DELIVERY_RETRY_DELAY_S", 0.0)
    yield recorder
    alerting.reset_alerts()
    await _forget_counts()


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> dict[str, float]:
    """Both admission clocks, held still (see `alert_delivery_test._freeze_clock`)."""
    state = {"t": 1_000.0}
    monkeypatch.setattr(alerting, "_now", lambda: state["t"])
    monkeypatch.setattr(alert_admission, "_now_ms", lambda: state["t"] * 1000.0)
    return state


def _status_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://provider.invalid/v1/chat/completions")
    response = httpx.Response(status, request=request, text=PLANTED_BODY)
    return httpx.HTTPStatusError(f"{status}", request=request, response=response)


async def _fail(times: int, *, leg: provider_health.AiLeg = "copilot", status: int = 503) -> None:
    for _ in range(times):
        await provider_health.note_failure(leg, "google", _status_error(status))


async def _episodes() -> list[Any]:
    async with untenanted_session() as session:
        return (
            await session.execute(
                text(
                    "SELECT fingerprint, ids, emailed, cleared_at FROM platform_alerts "
                    "WHERE code = :code ORDER BY first_seen_at"
                ),
                {"code": CODE},
            )
        ).all()


def _drain() -> None:
    assert alerting.flush_alerts(timeout=5.0), "alert delivery did not drain"


def test_the_alarm_pages_and_repeats_hourly() -> None:
    assert severity_of(CODE) == "page"
    assert REPEAT_WHILE_OPEN_S[CODE] == 3600.0


async def test_one_or_two_failures_alert_nobody(transport: RecordingTransport) -> None:
    await _fail(2)
    _drain()
    assert transport.sent == []
    assert await _episodes() == []


async def test_three_failures_in_the_window_open_the_episode_and_mail(
    transport: RecordingTransport,
) -> None:
    await _fail(3)
    _drain()

    (message,) = transport.sent
    assert CODE in message["subject"]
    assert "leg: copilot" in message["body"]
    assert "provider: google" in message["body"]
    assert "status: 503" in message["body"]
    (row,) = await _episodes()
    assert row.fingerprint == f"CORE_LOGIC:{CODE}:copilot:google"
    assert row.emailed is True
    assert row.cleared_at is None


async def test_three_in_a_row_open_it_even_when_spread_past_the_window(
    transport: RecordingTransport,
) -> None:
    """The quiet leg: each failure lands after the previous window expired."""
    window_key = provider_health._keys("copilot", "google")[0]
    for _ in range(3):
        await get_redis().delete(window_key)
        await _fail(1)
    _drain()
    assert len(transport.sent) == 1


async def test_a_success_between_failures_resets_the_streak(
    transport: RecordingTransport,
) -> None:
    window_key = provider_health._keys("copilot", "google")[0]
    for step in ("fail", "fail", "ok", "fail"):
        await get_redis().delete(window_key)
        if step == "fail":
            await _fail(1)
        else:
            await provider_health.note_success("copilot", "google")
    _drain()
    assert transport.sent == []


async def test_legs_are_separate_conditions(transport: RecordingTransport) -> None:
    await _fail(2, leg="copilot")
    await _fail(2, leg="embeddings")
    _drain()
    assert transport.sent == []


async def test_a_success_closes_the_episode_and_says_so_once(
    transport: RecordingTransport,
) -> None:
    await _fail(3)
    await provider_health.note_success("copilot", "google")
    _drain()
    # A second success has nothing open to close and must not mail again.
    await provider_health.note_success("copilot", "google")
    _drain()

    assert len(transport.sent) == 2
    cleared = transport.sent[1]
    assert f"{CODE} cleared" in cleared["subject"]
    assert "reported recovery" in cleared["body"]
    (row,) = await _episodes()
    assert row.cleared_at is not None
    # And one fresh failure after recovery is a blip again, not a continuation.
    await _fail(1)
    _drain()
    assert len(transport.sent) == 2


async def test_an_open_episode_reminds_hourly_and_not_more_often(
    transport: RecordingTransport, clock: dict[str, float]
) -> None:
    await _fail(3)
    _drain()
    assert len(transport.sent) == 1

    # Fifteen minutes on: the notice reaches the delivery thread, and is withheld.
    clock["t"] += alerting.ALERT_REPEAT_INTERVAL_S + 1
    await _fail(1)
    _drain()
    assert len(transport.sent) == 1, "a reminder before the hour is the old 26-message thread"

    # An hour after the onset mail: a reminder.
    async with untenanted_session() as session:
        await session.execute(
            text(
                "UPDATE platform_alerts SET emailed_at = now() - interval '61 minutes' "
                "WHERE code = :code"
            ),
            {"code": CODE},
        )
        await session.commit()
    clock["t"] += alerting.ALERT_REPEAT_INTERVAL_S + 1
    await _fail(1)
    _drain()

    assert len(transport.sent) == 2
    reminder = transport.sent[1]
    assert reminder["subject"].endswith("(still open)")
    assert "STILL OPEN" in reminder["body"]
    assert len(await _episodes()) == 1, "a reminder continues the episode, it is not a new one"


async def test_a_code_without_a_repeat_interval_still_mails_once(
    transport: RecordingTransport, clock: dict[str, float]
) -> None:
    alerting.alert("ROUTE_HANDLER", "razorpay_money_unapplied", detail="x")
    _drain()
    async with untenanted_session() as session:
        await session.execute(
            text("UPDATE platform_alerts SET emailed_at = now() - interval '5 hours'")
        )
        await session.commit()
    clock["t"] += alerting.ALERT_REPEAT_INTERVAL_S + 1
    alerting.alert("ROUTE_HANDLER", "razorpay_money_unapplied", detail="x")
    _drain()
    assert len(transport.sent) == 1


def test_the_failure_fields_are_status_and_class_never_the_body() -> None:
    fields = provider_health.failure_fields(_status_error(429))
    assert fields == {"error": "HTTPStatusError", "status": 429}
    assert provider_health.failure_fields(httpx.ReadTimeout("slow")) == {
        "error": "ReadTimeout",
        "status": None,
    }


async def test_the_extraction_failure_log_carries_the_status_and_no_body(
    transport: RecordingTransport, caplog: pytest.LogCaptureFixture
) -> None:
    from apps.workers import extraction
    from calevate_shared.extraction import ExtractionSchemaSpec

    class FailingSarvam(extraction.SarvamExtractor):
        async def run(self, spec: Any, transcript: str) -> dict[str, Any]:
            raise _status_error(429)

    spec = ExtractionSchemaSpec(version=1, fields=[])
    caplog.set_level(logging.WARNING)
    for _ in range(3):
        output = await extraction.extract_call(spec, "hello", extractor=FailingSarvam("key"))
        assert output.errors[extraction.MODEL_FAILURE] == "HTTPStatusError"
    _drain()

    failed = [r for r in caplog.records if r.getMessage() == "extraction_failed"]
    assert len(failed) == 3
    record = failed[0]
    assert record.status == 429
    assert record.provider == "sarvam"
    everything = "\n".join(
        [str(r.__dict__) for r in caplog.records] + [m["body"] for m in transport.sent]
    )
    assert PLANTED_BODY not in everything
    assert "9876543210" not in everything
    (message,) = transport.sent
    assert "leg: extraction" in message["body"]
    assert "status: 429" in message["body"]


async def test_a_redis_outage_never_breaks_the_caller(
    transport: RecordingTransport, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _down(*_: Any, **__: Any) -> Any:
        raise ConnectionError("redis is down")

    monkeypatch.setattr(provider_health, "_eval", _down)
    await _fail(5)
    await provider_health.note_success("copilot", "google")
    with pytest.raises(httpx.HTTPStatusError):
        async with provider_health.watch("embeddings", "azure"):
            raise _status_error(500)
    _drain()
    assert transport.sent == []


def test_the_alarm_wiring_gate_passes() -> None:
    from scripts import check_alarm_wiring

    assert check_alarm_wiring.repeat_failures() == []
    assert check_alarm_wiring.evaluate() == []


def test_the_gate_refuses_a_reminder_on_a_code_that_cannot_mail() -> None:
    from scripts import check_alarm_wiring

    failures = check_alarm_wiring.repeat_failures(
        raised={"fx_rate_stale": {"x"}},
        classified={"fx_rate_stale": "attention"},
        repeating={"fx_rate_stale": 3600.0, "never_raised": 60.0},
    )
    joined = "\n".join(failures)
    assert "REPEATS, NEVER MAILS" in joined
    assert "REPEATS, NEVER RAISED" in joined
    assert "REPEATS TOO OFTEN" in joined
