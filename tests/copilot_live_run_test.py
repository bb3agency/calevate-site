"""Stop and the Thinking line through the real copilot routes, on both realms.

1. The stream opens with `event: run`; a stopped run ends with `event: stopped` and no
   `done`, and what was said before Stop is kept.
2. A colleague's Stop on somebody else's run answers 202 with the same body and does
   nothing; the owner's Stop ends it.
3. The Thinking line reaches the stream and nothing else: not the transcript, not the
   memory table, not a log line.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
from apps.api.billing import ai_quota
from apps.api.copilot import admin_routes, run_control, service, transcript
from apps.api.copilot.schemas import CopilotThoughtEvent
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.adversarial_pass_test import _make_member
from tests.conftest import make_tenant_with_pip as _make_tenant
from tests.copilot_live_sync_test import BODY, _live_run, _stored

SENTINEL = "Weighing the zebra-quartz leads"


@pytest.fixture(autouse=True)
def _the_platform_brake_is_not_this_suites_business(monkeypatch: pytest.MonkeyPatch) -> None:
    async def not_tripped(*args: Any, **kwargs: Any) -> bool:
        return False

    monkeypatch.setattr(ai_quota, "platform_brake_tripped", not_tripped)


async def _frames(
    http: AsyncClient, path: str, body: dict[str, Any], headers: dict[str, str]
) -> list[tuple[str, Any]]:
    frames: list[tuple[str, Any]] = []
    name = ""
    async with http.stream("POST", path, json=body, headers=headers) as response:
        assert response.status_code == 200, await response.aread()
        async for line in response.aiter_lines():
            if line.startswith("event:"):
                name = line[len("event:") :].strip()
            elif line.startswith("data:"):
                frames.append((name, json.loads(line[len("data:") :])))
    return frames


def _stopping_run(stop: Any) -> Any:
    """A `_run_guarded` that thinks, says part of an answer, has `stop` pressed against it,
    then waits at the loop's checkpoint as a real run does between frames."""

    async def _run(payload: Any, **kwargs: Any) -> AsyncIterator[service.CopilotEvent]:
        control = run_control.current()
        assert control is not None
        yield service.CopilotEvent(thought=CopilotThoughtEvent(delta=f"{SENTINEL}.", turn=0))
        yield service.CopilotEvent(text="Partly said.")
        await stop(control)
        async with asyncio.timeout(5):
            await control.wait()
        run_control.checkpoint()
        yield service.CopilotEvent(text="Never said.")

    return _run


async def test_a_colleagues_stop_does_nothing_and_the_owners_ends_the_stream(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    tenant_id, slug, token = await _make_tenant()
    user_id = UUID(token.rsplit(":", 1)[1])
    await _live_run("client", user_id)
    _colleague, colleague_token = await _make_member(tenant_id)
    owner = {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
    colleague = {"Authorization": f"Bearer {colleague_token}", "X-Org-Slug": slug}
    seen: dict[str, Any] = {}

    async def _stop(control: run_control.RunControl) -> None:
        path = f"/v1/copilot/runs/{control.run_id}/stop"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as h:
            theirs = await h.post(path, headers=colleague)
            await asyncio.sleep(run_control.STOP_POLL_S * 3)
            seen["after_colleague"] = control.stopped
            mine = await h.post(path, headers=owner)
            unknown = await h.post(f"/v1/copilot/runs/{uuid.uuid4()}/stop", headers=owner)
        seen["responses"] = [(r.status_code, r.json()) for r in (theirs, mine)]
        seen["unknown"] = unknown.status_code
        seen["run_id"] = str(control.run_id)

    monkeypatch.setattr(service, "_run_guarded", _stopping_run(_stop))
    caplog.set_level("DEBUG")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        frames = await _frames(http, "/v1/copilot/ask", BODY, owner)

    assert [name for name, _ in frames] == ["run", "thought", "text", "stopped"]
    assert frames[0][1]["run_id"] == seen["run_id"] and frames[0][1]["started_at"]
    assert frames[1][1] == {"delta": f"{SENTINEL}.", "turn": 0}
    assert frames[3][1] == {"reason": "person"}
    assert seen["after_colleague"] is False
    # The same answer whoever asks: nothing says whose run it was or whether it existed.
    assert seen["responses"] == [(202, {"run_id": seen["run_id"]})] * 2
    assert seen["unknown"] == 202
    # What was said before Stop is kept; the Thinking line is stored and logged nowhere.
    turns = await _stored(transcript.CLIENT, user_id, tenant_id)
    assert [(role, content) for _id, role, content in turns] == [
        ("user", BODY["question"]),
        ("assistant", "Partly said."),
    ]
    async with tenant_session(tenant_id) as session:
        remembered = (
            await session.execute(
                text("SELECT count(*) FROM copilot_memories WHERE content LIKE :s"),
                {"s": f"%{SENTINEL}%"},
            )
        ).scalar_one()
    assert remembered == 0
    assert SENTINEL not in caplog.text


async def test_an_operator_stops_their_own_admin_run(monkeypatch: pytest.MonkeyPatch) -> None:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    await _live_run("admin", admin_id)
    headers = {"Authorization": f"Bearer dev:admin:{admin_id}"}

    async def _gate(_session: Any) -> None:
        return None

    async def _stop(control: run_control.RunControl) -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as h:
            response = await h.post(
                f"/v1/admin/copilot/runs/{control.run_id}/stop", headers=headers
            )
        assert response.status_code == 202

    monkeypatch.setattr(admin_routes, "require_platform_ai", _gate)
    monkeypatch.setattr(service, "_run_guarded", _stopping_run(_stop))
    body = {**BODY, "screen": {"route": "/admin/tenants", "title": "Accounts", "realm": "admin"}}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        frames = await _frames(http, "/v1/admin/copilot/ask", body, headers)

    assert [name for name, _ in frames] == ["run", "thought", "text", "stopped"]


async def test_a_run_that_is_not_stopped_opens_with_run_and_ends_with_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _tenant_id, slug, token = await _make_tenant()
    await _live_run("client", UUID(token.rsplit(":", 1)[1]))

    async def _run(payload: Any, **kwargs: Any) -> AsyncIterator[service.CopilotEvent]:
        yield service.CopilotEvent(text="Eleven.")

    monkeypatch.setattr(service, "_run_guarded", _run)
    headers = {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        frames = await _frames(http, "/v1/copilot/ask", BODY, headers)
    assert [name for name, _ in frames] == ["run", "text", "done"]
    # The run is forgotten once it ends: its id stops nothing now.
    assert UUID(frames[0][1]["run_id"]) not in run_control._LOCAL
