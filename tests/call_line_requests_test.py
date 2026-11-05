"""A client asks for more calls at once; operators are told and answer it (5 Nov 2026).

One open request per client however often it is tapped, only the owner may ask, operators are
told through the outbox, an operator's raise closes it and the client's bell says so, and a
decline carries its reason to the client.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from apps.api.core.console_links import admin_call_lines_link, admin_call_lines_path
from apps.api.core.errors import install_error_handlers
from apps.api.core.rbac import assert_policy_registry_complete
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.notifications import service as bell
from apps.api.tenancy.call_line_requests import OPERATOR_NOTICE_JOB, ask_for_more
from apps.api.tenancy.call_lines_routes import call_lines_confirmation, router
from apps.workers import call_line_requests as worker
from apps.workers.settings import WorkerSettings
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.call_handling_test import _operator, _tenant
from tests.call_lines_test import _on_trial

pytestmark = [pytest.mark.rls]

ASK = "/v1/call-lines/requests"


def _client() -> AsyncClient:
    application = FastAPI()
    install_error_handlers(application)
    application.include_router(router)
    assert_policy_registry_complete(application)
    return AsyncClient(transport=ASGITransport(app=application), base_url="http://api")


async def _notices(tenant_id: uuid.UUID) -> list[dict[str, str]]:
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT payload FROM outbox_messages WHERE job = :job "
                    "AND payload->>'tenant_id' = :tid"
                ),
                {"job": OPERATOR_NOTICE_JOB, "tid": str(tenant_id)},
            )
        ).all()
    return [dict(r[0]) for r in rows]


async def _admin_with_email(role: str) -> str:
    address = f"{role}-{uuid.uuid4().hex[:8]}@example.com"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, email, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', :email, :role, now(), now())"
            ),
            {"id": uuid.uuid4(), "email": address, "role": role},
        )
    return address


class _Mailbox:
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    def send(self, *, to: str, subject: str, body: str, html: str | None = None) -> bool:
        self.sent.append({"to": to, "subject": subject, "body": body})
        return True


async def test_a_second_tap_answers_the_open_request_and_tells_nobody_twice() -> None:
    tenant_id, _agent, owner = await _tenant()
    async with _client() as client:
        first = await client.post(ASK, headers=owner, json={"wanted": 4, "note": " busy mornings "})
        again = await client.post(ASK, headers=owner, json={"wanted": 6})
        mine = await client.get("/v1/call-lines", headers=owner)
    assert first.status_code == 201, first.text
    assert again.status_code == 200, again.text
    assert again.json()["id"] == first.json()["id"]
    assert again.json()["wanted_lines"] == 4, "the open request is answered, not rewritten"
    assert first.json()["status"] == "open" and first.json()["lines_at_request"] == 2
    body = mine.json()
    assert body["request"]["id"] == first.json()["id"] and body["max_lines"] == 50
    notices = await _notices(tenant_id)
    assert notices == [{"tenant_id": str(tenant_id), "request_id": first.json()["id"]}]
    async with tenant_session(tenant_id) as session:
        note = (await session.execute(text("SELECT note FROM call_line_requests"))).scalar_one()
    assert note == "busy mornings"


async def test_two_taps_at_the_same_instant_open_one_request() -> None:
    tenant_id, _agent, owner = await _tenant()
    user_id = uuid.UUID(owner["Authorization"].rsplit(":", 1)[1])

    async def tap() -> tuple[uuid.UUID, bool]:
        async with tenant_session(tenant_id) as session:
            found, created = await ask_for_more(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                lines_now=2,
                on_trial=False,
                wanted=3,
                note=None,
            )
        return found.id, created

    results = await asyncio.gather(tap(), tap())
    assert results[0][0] == results[1][0]
    assert sorted(created for _id, created in results) == [False, True]
    assert len(await _notices(tenant_id)) == 1


async def test_only_the_owner_may_ask() -> None:
    _tenant_id, _agent, staff = await _tenant(role="staff")
    async with _client() as client:
        refused = await client.post(ASK, headers=staff, json={"wanted": 3})
        read = await client.get("/v1/call-lines", headers=staff)
    assert refused.status_code == 403, refused.text
    assert read.status_code == 200 and read.json()["request"] is None


async def test_a_trial_and_an_out_of_range_ask_are_refused() -> None:
    trial, _a, trial_owner = await _tenant()
    await _on_trial(trial)
    _paying, _b, owner = await _tenant()
    async with _client() as client:
        on_trial = await client.post(ASK, headers=trial_owner, json={})
        too_few = await client.post(ASK, headers=owner, json={"wanted": 2})
        too_many = await client.post(ASK, headers=owner, json={"wanted": 51})
    assert on_trial.json()["type"].endswith("/call_lines_request_on_trial")
    assert too_few.json()["type"].endswith("/call_lines_wanted_out_of_range")
    assert too_many.status_code == 422


async def test_one_clients_request_is_invisible_to_another() -> None:
    a, _agent_a, owner_a = await _tenant()
    b, _agent_b, owner_b = await _tenant()
    async with _client() as client:
        await client.post(ASK, headers=owner_a, json={"wanted": 5})
        seen_by_b = await client.get("/v1/call-lines", headers=owner_b)
    assert seen_by_b.json()["request"] is None
    async with tenant_session(b) as session:
        rows = (await session.execute(text("SELECT count(*) FROM call_line_requests"))).scalar()
    assert rows == 0
    async with untenanted_session() as session:
        rows = (await session.execute(text("SELECT count(*) FROM call_line_requests"))).scalar()
    assert rows == 0, "no tenant GUC, no rows"
    async with tenant_session(a) as session:
        rows = (await session.execute(text("SELECT count(*) FROM call_line_requests"))).scalar()
    assert rows == 1


async def test_every_operator_is_emailed_with_a_button_to_the_clients_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mailbox = _Mailbox()
    monkeypatch.setattr(worker, "get_transport", lambda _purpose=None: mailbox)
    boss = await _admin_with_email("superadmin")
    ops = await _admin_with_email("operator")
    tenant_id, _agent, owner = await _tenant()
    async with _client() as client:
        await client.post(ASK, headers=owner, json={"wanted": 4, "note": "festival rush"})
    [payload] = await _notices(tenant_id)
    assert await worker.notify_call_lines_request({}, payload) == "sent"
    sent_to = {m["to"] for m in mailbox.sent}
    assert {boss, ops} <= sent_to, "super admins and admins alike"
    mail = next(m for m in mailbox.sent if m["to"] == ops)
    assert "2 → 4" in mail["subject"]
    assert "festival rush" in mail["body"]
    assert admin_call_lines_link(tenant_id) in mail["body"]


async def test_an_answered_request_is_not_announced(monkeypatch: pytest.MonkeyPatch) -> None:
    mailbox = _Mailbox()
    monkeypatch.setattr(worker, "get_transport", lambda _purpose=None: mailbox)
    tenant_id, _agent, owner = await _tenant()
    headers = {**await _operator(), "X-Confirm-Action": call_lines_confirmation(tenant_id)}
    async with _client() as client:
        await client.post(ASK, headers=owner, json={"wanted": 3})
        await client.put(
            f"/v1/admin/organizations/{tenant_id}/call-lines",
            headers=headers,
            json={"call_lines": 3},
        )
    [payload] = await _notices(tenant_id)
    assert await worker.notify_call_lines_request({}, payload) == "answered"
    assert mailbox.sent == []


async def test_a_raise_closes_the_request_and_the_clients_bell_says_so() -> None:
    tenant_id, _agent, owner = await _tenant()
    operator = await _operator()
    path = f"/v1/admin/organizations/{tenant_id}/call-lines"
    async with _client() as client:
        asked = (
            await client.post(ASK, headers=owner, json={"wanted": 5, "note": "two shops"})
        ).json()
        listed = await client.get("/v1/admin/call-line-requests", headers=operator)
        page = await client.get(path, headers=operator)
        raised = await client.put(
            path,
            headers={**operator, "X-Confirm-Action": call_lines_confirmation(tenant_id)},
            json={"call_lines": 5},
        )
        mine = await client.get("/v1/call-lines", headers=owner)
    assert any(r["tenant_id"] == str(tenant_id) and r["wanted_lines"] == 5 for r in listed.json())
    open_request = page.json()["open_request"]
    assert open_request["id"] == asked["id"] and open_request["note"] == "two shops"
    assert open_request["requested_by"].endswith("@example.com")
    assert raised.json()["open_request"] is None
    assert mine.json()["call_lines"] == 5
    assert mine.json()["request"]["status"] == "done"
    assert mine.json()["request"]["lines_granted"] == 5
    async with tenant_session(tenant_id) as session:
        feed = await bell.feed(session, tenant_id=tenant_id, user_id=None, limit=30)
        audit = (
            (
                await session.execute(
                    text("SELECT action FROM audit_log WHERE object_id = :rid ORDER BY created_at"),
                    {"rid": asked["id"]},
                )
            )
            .scalars()
            .all()
        )
    notice = next(n for n in feed.items if n.source == "call_lines")
    assert notice.title == "You can now have 5 calls at once." and notice.tone == "success"
    assert notice.href == "/phone-number"
    assert audit == ["call_lines_request.opened", "call_lines_request.done"]
    async with _client() as client:
        listed = await client.get("/v1/admin/call-line-requests", headers=operator)
    assert all(r["tenant_id"] != str(tenant_id) for r in listed.json())


async def test_a_raise_the_workspace_holds_closes_only_once_it_is_read_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A7-06: where the client's own workspace holds the cap, the client is not told
    "raised" until that workspace reads the raise back; until then it reads as being
    applied, and the operator's panel says so."""
    from apps.api.tenancy import call_lines as lines_module
    from apps.api.tenancy.call_lines import record_engine_call_lines

    async def _held_by_workspace(*_args: object, **_kwargs: object) -> bool:
        return True

    monkeypatch.setattr(lines_module, "_engine_holds_it", _held_by_workspace)
    tenant_id, _agent, owner = await _tenant()
    operator = await _operator()
    path = f"/v1/admin/organizations/{tenant_id}/call-lines"
    async with _client() as client:
        await client.post(ASK, headers=owner, json={"wanted": 4})
        raised = await client.put(
            path,
            headers={**operator, "X-Confirm-Action": call_lines_confirmation(tenant_id)},
            json={"call_lines": 4},
        )
        mine = await client.get("/v1/call-lines", headers=owner)
    assert raised.json()["engine_state"] == "applying"
    assert raised.json()["open_request"] is not None, "closed before the platform held it"
    assert mine.json()["being_applied"] is True
    assert mine.json()["request"]["status"] == "open"

    async with tenant_session(tenant_id) as session:
        closed = await record_engine_call_lines(session, tenant_id=tenant_id, held=4)
    assert closed is not None and closed.lines_granted == 4
    async with _client() as client:
        page = (await client.get(path, headers=operator)).json()
        mine = (await client.get("/v1/call-lines", headers=owner)).json()
    assert page["engine_state"] == "applied" and page["applied_lines"] == 4
    assert page["open_request"] is None
    assert mine["being_applied"] is False and mine["request"]["status"] == "done"


async def test_the_operator_sees_the_account_ceiling_and_what_others_hold() -> None:
    """A7-10: calls at once is granted per client against one account-wide ceiling."""
    tenant_id, _agent, _owner = await _tenant()
    operator = await _operator()
    async with _client() as client:
        page = (
            await client.get(f"/v1/admin/organizations/{tenant_id}/call-lines", headers=operator)
        ).json()
    assert "account_ceiling" in page
    assert isinstance(page["lines_elsewhere_at_most"], int)


async def test_a_decline_carries_its_reason_and_holds_the_next_ask_for_a_day() -> None:
    tenant_id, _agent, owner = await _tenant()
    operator = await _operator()
    async with _client() as client:
        asked = (await client.post(ASK, headers=owner, json={})).json()
        decline = f"/v1/admin/organizations/{tenant_id}/call-lines/requests/{asked['id']}/decline"
        blank = await client.post(decline, headers=operator, json={"reason": "   "})
        declined = await client.post(
            decline, headers=operator, json={"reason": "Let's talk about your plan first."}
        )
        twice = await client.post(decline, headers=operator, json={"reason": "again"})
        again = await client.post(ASK, headers=owner, json={})
        mine = await client.get("/v1/call-lines", headers=owner)
    assert blank.json()["type"].endswith("/call_lines_decline_reason")
    assert declined.status_code == 200 and declined.json()["status"] == "declined"
    assert twice.json()["type"].endswith("/call_lines_request_not_open")
    assert again.json()["type"].endswith("/call_lines_request_too_soon")
    assert mine.json()["request"]["decline_reason"] == "Let's talk about your plan first."
    async with tenant_session(tenant_id) as session:
        feed = await bell.feed(session, tenant_id=tenant_id, user_id=None, limit=30)
    notice = next(n for n in feed.items if n.source == "call_lines")
    assert notice.detail == "Let's talk about your plan first." and notice.tone == "warning"


async def test_another_clients_operator_door_cannot_decline_this_request() -> None:
    a, _agent_a, owner_a = await _tenant()
    b, _agent_b, _owner_b = await _tenant()
    operator = await _operator()
    async with _client() as client:
        asked = (await client.post(ASK, headers=owner_a, json={})).json()
        wrong = await client.post(
            f"/v1/admin/organizations/{b}/call-lines/requests/{asked['id']}/decline",
            headers=operator,
            json={"reason": "no"},
        )
    assert wrong.json()["type"].endswith("/call_lines_request_not_open")
    async with tenant_session(a) as session:
        status = (await session.execute(text("SELECT status FROM call_line_requests"))).scalar_one()
    assert status == "open"


async def test_a_client_cannot_reach_the_operators_list_or_decline() -> None:
    tenant_id, _agent, owner = await _tenant()
    async with _client() as client:
        listed = await client.get("/v1/admin/call-line-requests", headers=owner)
        decline = await client.post(
            f"/v1/admin/organizations/{tenant_id}/call-lines/requests/{uuid.uuid4()}/decline",
            headers=owner,
            json={"reason": "x"},
        )
    assert listed.status_code in (401, 403) and decline.status_code in (401, 403)


def test_the_email_link_opens_a_page_the_console_serves() -> None:
    from pathlib import Path

    page = Path("apps/web/src/app/admin/tenants/[tenantId]/numbers/page.tsx")
    assert page.exists()
    assert admin_call_lines_path("t-1") == "/admin/tenants/t-1/numbers?focus=call-lines"


def test_the_notice_job_is_registered() -> None:
    names = {getattr(f, "name", getattr(f, "__name__", "")) for f in WorkerSettings.functions}
    assert OPERATOR_NOTICE_JOB in names and worker.JOB_NAME == OPERATOR_NOTICE_JOB
