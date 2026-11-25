"""What owners and operators see while the voice engine does not answer, and after it does.

Driven through the real vendor ladder (`vendor_http.vendor_request`) over a mock transport
that times out, refuses the connection, then answers, against the real
`platform_engine_state` row: the outage is a fact shared by every process, so a stub of the
state would prove nothing about it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from apps.api.agents import trial_calls
from apps.api.campaigns import notes_live
from apps.api.core.errors import ProblemError
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.session import untenanted_session
from apps.api.engine import health, outage
from apps.api.engine.outage import (
    OUTAGE_MIN_FAILURES,
    PHONE_SERVICE_DOWN_CODE,
    SAVED_GOES_LIVE_LATER_CODE,
    EngineOutage,
    engine_outage,
    is_engine_not_answering,
)
from apps.api.engine.vendor_http import EngineRejectedError, vendor_request
from apps.api.main import app
from apps.api.ops import engine_health_routes
from apps.workers import alerts as alert_sweep
from apps.workers import job_notes_live
from arq import Retry
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.admin_security_test import _make_admin
from tests.first_run_test import _owner, _tenant

ENGINE = "outage-lane"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


@pytest.fixture(autouse=True)
async def _fresh_state(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(health, "alert", lambda *a, **kw: None)
    outage.reset_process_state()
    await _clear()
    yield
    outage.reset_process_state()
    await _clear()


async def _clear() -> None:
    async with untenanted_session() as session:
        for table in ("platform_engine_state", "platform_engine_health"):
            await session.execute(text(f"DELETE FROM {table} WHERE engine = :e"), {"e": ENGINE})


async def _request(handler: Any, route: str = "/calls") -> None:
    async with httpx.AsyncClient(
        base_url="https://api.example.invalid", transport=httpx.MockTransport(handler)
    ) as client:
        await vendor_request(client, "POST", "/calls", engine=ENGINE, route=route)


def _times_out(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("timed out", request=request)


def _refuses(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


def _answers(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"ok": True})


async def _fail(times: int, handler: Any = _times_out, route: str = "/calls") -> None:
    for _ in range(times):
        with pytest.raises(ProblemError) as caught:
            await _request(handler, route)
        assert caught.value.code == "engine_unreachable"


# ------------------------------------------------------------------ the state


async def test_timeouts_make_an_outage_and_the_first_answer_ends_it() -> None:
    await _fail(OUTAGE_MIN_FAILURES - 1)
    assert (await engine_outage(ENGINE)).failing is False
    await _fail(1, route="/agents/{ref}")
    down = await engine_outage(ENGINE)
    assert down.failing is True
    assert down.since is not None
    assert (down.last_kind, down.last_error, down.last_route) == (
        "unreachable",
        "ReadTimeout",
        "/agents/{ref}",
    )

    await _request(_answers)
    up = await engine_outage(ENGINE)
    assert (up.failing, up.since, up.consecutive_failures) == (False, None, 0)
    assert up.recovered_at is not None


async def test_a_refused_connection_and_a_5xx_both_count() -> None:
    await _fail(2, _refuses)

    def bad_gateway(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="bad gateway")

    with pytest.raises(EngineRejectedError) as caught:
        await _request(bad_gateway)
    assert is_engine_not_answering(caught.value)
    state = await engine_outage(ENGINE)
    assert state.failing is True
    assert (state.last_kind, state.last_error) == ("server_error", "HTTP 502")


async def test_an_answer_between_failures_is_not_an_outage() -> None:
    await _fail(2)
    await _request(_answers)
    await _fail(2)
    assert (await engine_outage(ENGINE)).failing is False


async def test_a_4xx_is_an_answer_and_never_waited_out() -> None:
    def not_found(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "no"})

    await _fail(2)
    with pytest.raises(EngineRejectedError) as caught:
        await _request(not_found)
    assert not is_engine_not_answering(caught.value)
    assert (await engine_outage(ENGINE)).consecutive_failures == 0


async def test_a_run_nobody_has_seen_for_five_minutes_is_not_claimed() -> None:
    await _fail(OUTAGE_MIN_FAILURES)
    async with untenanted_session() as session:
        await session.execute(
            text(
                "UPDATE platform_engine_state SET last_failure_at = now() - interval '6 minutes' "
                "WHERE engine = :e"
            ),
            {"e": ENGINE},
        )
    assert (await engine_outage(ENGINE)).failing is False
    # The next failure starts a new run rather than extending the stale one.
    await _fail(1)
    state = await engine_outage(ENGINE)
    assert (state.failing, state.consecutive_failures) == (False, 1)


async def test_another_process_ends_a_run_it_never_saw() -> None:
    """The process that sees the first answer may not be the one that saw the failures."""
    await _fail(OUTAGE_MIN_FAILURES)
    outage.reset_process_state()
    await _request(_answers)
    assert (await engine_outage(ENGINE)).failing is False


async def test_the_owner_reads_plain_words_and_no_provider() -> None:
    with pytest.raises(ProblemError) as caught:
        await _request(_times_out)
    problem = caught.value
    assert problem.title == "Our phone service is not answering"
    assert problem.remediation is not None and "minutes" in problem.remediation
    for word in ("thinnest", "vendor", "platform", "engine"):
        assert word not in f"{problem.title} {problem.detail} {problem.remediation}".lower()


# ------------------------------------------------------------------ the routes


def _down() -> EngineOutage:
    return EngineOutage(
        engine=ENGINE,
        failing=True,
        since=datetime.now(UTC) - timedelta(minutes=2),
        consecutive_failures=7,
        last_failure_at=datetime.now(UTC),
        last_kind="unreachable",
        last_error="ReadTimeout",
        last_route="/calls",
    )


async def test_the_client_banner_read_says_only_whether_calls_go_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = await _tenant()
    headers = await _owner(tenant_id)

    async def down(engine: str | None = None) -> EngineOutage:
        return _down()

    async with _client() as http:
        up = await http.get("/v1/phone-service", headers=headers)
        monkeypatch.setattr(engine_health_routes, "engine_outage", down)
        failing = await http.get("/v1/phone-service", headers=headers)
        anonymous = await http.get("/v1/phone-service")
    assert up.status_code == 200, up.text
    assert up.json()["state"] in ("answering", "not_answering")
    assert failing.json()["state"] == "not_answering"
    assert set(failing.json()) == {"state", "since"}
    assert anonymous.status_code in (401, 403)


async def test_the_operator_panel_shows_the_run_and_its_last_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _fail(OUTAGE_MIN_FAILURES)

    async def ours(engine: str | None = None) -> EngineOutage:
        return await engine_outage(ENGINE)

    monkeypatch.setattr(engine_health_routes, "engine_outage", ours)
    token = await _make_admin()
    async with _client() as http:
        panel = await http.get(
            "/v1/ops/engine-health", headers={"Authorization": f"Bearer {token}"}
        )
    assert panel.status_code == 200, panel.text
    body = panel.json()
    assert body["failing"] is True
    assert body["consecutive_failures"] == OUTAGE_MIN_FAILURES
    assert (body["last_error"], body["last_route"]) == ("ReadTimeout", "/calls")
    assert body["window_unreachable"] == OUTAGE_MIN_FAILURES


async def test_a_test_call_while_down_is_refused_before_any_engine_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = await _tenant()
    headers = await _owner(tenant_id)

    async def down(engine: str | None = None) -> EngineOutage:
        return _down()

    monkeypatch.setattr(trial_calls, "engine_outage", down)
    async with _client() as http:
        refused = await http.post(
            "/v1/trial/calls",
            headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
            json={"agent_id": str(uuid.uuid4()), "number": "+919000000001"},
        )
    assert refused.status_code == 503, refused.text
    assert refused.json()["type"].endswith(f"/{PHONE_SERVICE_DOWN_CODE}")
    assert refused.headers.get("Retry-After") == "60"


# ------------------------------------------------------------------ saves are kept


async def _put_live_messages(tenant_id: uuid.UUID) -> list[dict[str, Any]]:
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT payload FROM outbox_messages WHERE job = :job "
                    "AND payload->>'tenant_id' = :tid"
                ),
                {"job": notes_live.PUT_LIVE_JOB, "tid": str(tenant_id)},
            )
        ).scalars()
        return [dict(row) for row in rows]


async def test_a_save_that_finds_the_engine_down_is_queued_not_lost() -> None:
    tenant_id = await _tenant()
    line_id = uuid.uuid4()

    async def unreachable() -> None:
        await _request(_times_out)

    with pytest.raises(ProblemError) as caught:
        await notes_live.put_live_or_queue(
            tenant_id, "line", line_id, retry="put_live", publish=unreachable
        )
    assert caught.value.code == SAVED_GOES_LIVE_LATER_CODE
    assert caught.value.title == "Saved"
    queued = await _put_live_messages(tenant_id)
    assert queued == [
        {
            "tenant_id": str(tenant_id),
            "jobs": [{"kind": "line", "job_id": str(line_id)}],
            "always": True,
        }
    ]


async def test_a_refusal_that_is_ours_still_asks_for_the_retry() -> None:
    tenant_id = await _tenant()

    async def refused() -> None:
        raise EngineRejectedError(status=400)

    with pytest.raises(EngineRejectedError) as caught:
        await notes_live.put_live_or_queue(tenant_id, "campaign", uuid.uuid4(), publish=refused)
    assert caught.value.title == "Saved, but not on its calls yet"
    assert await _put_live_messages(tenant_id) == []


async def test_the_queued_put_live_waits_the_outage_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = await _tenant()
    line_id = uuid.uuid4()
    payload = {"tenant_id": str(tenant_id), "jobs": [{"kind": "line", "job_id": str(line_id)}]}
    calls: list[tuple[uuid.UUID, bool]] = []
    alarms: list[str] = []
    state = {"answering": False}

    async def put_live(tid: uuid.UUID, kind: str, job_id: uuid.UUID, *, always: bool) -> None:
        calls.append((job_id, always))
        if not state["answering"]:
            raise ProblemError(kind="dependency", code="engine_unreachable", title="x", detail="y")

    async def down(engine: str | None = None) -> EngineOutage:
        return _down()

    monkeypatch.setattr(notes_live, "put_live", put_live)
    monkeypatch.setattr(job_notes_live, "engine_outage", down)
    monkeypatch.setattr(job_notes_live, "alert", lambda stage, code, **kw: alarms.append(code))

    with pytest.raises(Retry):
        await job_notes_live.put_job_notes_live({"job_try": 1}, payload)
    # The ladder ran out while the outage is still on: a fresh ladder, nothing dropped.
    assert await job_notes_live.put_job_notes_live({"job_try": WORKER_MAX_TRIES}, payload) == (
        "waiting:1"
    )
    assert len(await _put_live_messages(tenant_id)) == 1
    state["answering"] = True
    assert await job_notes_live.put_job_notes_live({"job_try": 1}, payload) == "done"
    assert alarms == []
    assert calls[-1] == (line_id, False)


async def test_a_put_live_still_unanswered_after_recovery_alarms_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = await _tenant()
    payload = {
        "tenant_id": str(tenant_id),
        "jobs": [{"kind": "campaign", "job_id": str(uuid.uuid4())}],
    }
    alarms: list[str] = []

    async def put_live(tid: uuid.UUID, kind: str, job_id: uuid.UUID, *, always: bool) -> None:
        raise ProblemError(kind="dependency", code="engine_unreachable", title="x", detail="y")

    async def up(engine: str | None = None) -> EngineOutage:
        return EngineOutage(engine=ENGINE, failing=False)

    monkeypatch.setattr(notes_live, "put_live", put_live)
    monkeypatch.setattr(job_notes_live, "engine_outage", up)
    monkeypatch.setattr(job_notes_live, "alert", lambda stage, code, **kw: alarms.append(code))
    result = await job_notes_live.put_job_notes_live({"job_try": WORKER_MAX_TRIES}, payload)
    assert result == "gave_up:1"
    assert alarms == ["job_put_live_gave_up"]


# ------------------------------------------------------------------ the alarm clears


async def test_the_outage_alarm_clears_when_the_engine_answers_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code = alert_sweep.ENGINE_SPIKE_CODE
    async with untenanted_session() as session:
        await session.execute(
            text(
                "UPDATE platform_alerts SET cleared_at = now() "
                "WHERE code = :c AND cleared_at IS NULL"
            ),
            {"c": code},
        )
        await session.execute(
            text(
                "INSERT INTO platform_alerts (id, fingerprint, code, stage, severity, service, "
                "occurrences, emailed, first_seen_at, last_seen_at) VALUES (:id, :fp, :c, "
                "'CORE_LOGIC', 'page', 'api', 12, false, now() - interval '3 minutes', now())"
            ),
            {"id": uuid.uuid4(), "fp": f"CORE_LOGIC:{code}", "c": code},
        )

    async def still_down(engine: str | None = None) -> EngineOutage:
        return _down()

    monkeypatch.setattr(alert_sweep, "engine_outage", still_down)
    await alert_sweep.sweep_alert_clears({})
    assert await _open(code) == 1

    async def recovered(engine: str | None = None) -> EngineOutage:
        return EngineOutage(engine=ENGINE, failing=False, recovered_at=datetime.now(UTC))

    monkeypatch.setattr(alert_sweep, "engine_outage", recovered)
    await alert_sweep.sweep_alert_clears({})
    assert await _open(code) == 0


async def _open(code: str) -> int:
    async with untenanted_session() as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM platform_alerts "
                        "WHERE code = :c AND cleared_at IS NULL"
                    ),
                    {"c": code},
                )
            ).scalar()
            or 0
        )


async def test_an_unreadable_state_never_invents_an_outage(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode() -> Any:
        raise RuntimeError("no database")

    monkeypatch.setattr("apps.api.db.session.untenanted_session", explode)
    assert (await engine_outage(ENGINE)).failing is False
    await outage.record_answer(ENGINE)
