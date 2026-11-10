"""Journey audit E9 (10 Nov 2026): one client never sees another client's anything.

E9-01: Pip's "answering" mark was keyed by the PERSON alone, while a client's conversation is
one per person per account (`copilot_conversation_turns` is tenant-scoped). A person who
belongs to two accounts and asked Pip in account A saw "Pip is thinking…" in account B's
panel, where no answer would ever land.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
from apps.api.billing import ai_quota
from apps.api.copilot import live_sync, service
from apps.api.db.session import credential_session, tenant_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.conftest import make_tenant_with_pip

BODY: dict[str, Any] = {
    "screen": {"route": "/c/x/leads", "title": "Leads", "realm": "client"},
    "question": "how many leads came in today",
    "fields": [],
    "facts": [],
    "history": [],
}


@pytest.fixture(autouse=True)
def _the_platform_brake_is_not_this_suites_business(monkeypatch: pytest.MonkeyPatch) -> None:
    async def not_tripped(*args: Any, **kwargs: Any) -> bool:
        return False

    monkeypatch.setattr(ai_quota, "platform_brake_tripped", not_tripped)


async def _live_run(subject: UUID) -> None:
    """A live client sign-in run (`copilot_live_sync_test._live_run`)."""
    async with credential_session() as credentials:
        await credentials.execute(
            text(
                "INSERT INTO auth_sessions (id, family_id, realm, subject_id, token_hash, "
                "last_seen_at, idle_expires_at, absolute_expires_at, created_at, updated_at) "
                "VALUES (:id, :fid, 'client', :sid, :hash, now(), now() + interval '1 hour', "
                "now() + interval '1 hour', now() - interval '1 minute', now())"
            ),
            {
                "id": (session_id := uuid.uuid4()),
                "fid": uuid.uuid4(),
                "sid": subject,
                "hash": session_id.bytes,
            },
        )


async def _join(tenant_id: UUID, user_id: UUID) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, 'owner', now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id},
        )


async def test_pip_answering_in_one_account_is_not_shown_in_the_persons_other_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _tenant_a, slug_a, token = await make_tenant_with_pip()
    tenant_b, slug_b, _ = await make_tenant_with_pip()
    person = UUID(token.rsplit(":", 1)[1])
    await _join(tenant_b, person)
    await _live_run(person)
    seen: dict[str, Any] = {}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        auth = {"Authorization": f"Bearer {token}"}

        async def _run(payload: Any, **kwargs: Any) -> AsyncIterator[service.CopilotEvent]:
            # While Pip answers in account A, the same person opens Pip in account B.
            other = await http.get(
                "/v1/copilot/conversation", headers={**auth, "X-Org-Slug": slug_b}
            )
            same = await http.get(
                "/v1/copilot/conversation", headers={**auth, "X-Org-Slug": slug_a}
            )
            seen["b"], seen["a"] = other.json(), same.json()
            yield service.CopilotEvent(text="Eleven.")

        monkeypatch.setattr(service, "run_copilot", _run)
        async with http.stream(
            "POST", "/v1/copilot/ask", json=BODY, headers={**auth, "X-Org-Slug": slug_a}
        ) as response:
            assert response.status_code == 200, await response.aread()
            async for _line in response.aiter_lines():
                pass

    assert seen["a"]["answering"] is True
    assert seen["b"]["answering"] is False, "account B's panel showed account A's question"
    assert seen["b"]["turns"] == []


def test_a_client_answering_mark_cannot_be_written_without_its_account() -> None:
    with pytest.raises(ValueError):
        live_sync.answering_key("client", uuid.uuid4(), account=None)
    operator = uuid.uuid4()
    assert live_sync.answering_key("admin", operator, account=None).endswith(str(operator))
