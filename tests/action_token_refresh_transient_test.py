"""A busy OAuth token endpoint is a retry, not "reconnect your account"."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from apps.api.actions import execution
from apps.api.actions.credentials import ResolvedCredential
from apps.api.actions.schema import PreparedRequest
from apps.api.actions.service import LoadedTool
from apps.workers import client_actions


def _tool() -> LoadedTool:
    return LoadedTool(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        kind="sheets",
        provider="google_sheets",
        name="look_up_caller",
        description="Look the caller up",
        pre_call_message=None,
        trigger="in_call",
        enabled=True,
        credential_id=uuid.uuid4(),
        config={
            "operation": "lookup",
            "spreadsheet_id": "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
            "worksheet": "Sheet1",
            "match_header": "Phone",
            "return_headers": ["Name"],
        },
        params=[],
    )


@pytest.fixture
def token_endpoint(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    answer = {"status": 503}
    execution.reset_access_cache()

    async def _credential(*_a: Any, **_kw: Any) -> ResolvedCredential:
        return ResolvedCredential(kind="google_sheets", secret="refresh", non_secret={}, version=1)

    async def _send(_request: PreparedRequest, *, client: Any) -> httpx.Response:
        return httpx.Response(answer["status"], json={"error": "x"})

    monkeypatch.setattr(execution, "_credential", _credential)
    monkeypatch.setattr(execution, "_send", _send)
    monkeypatch.setattr(
        execution.oauth,
        "refresh_request",
        lambda *_a, **_kw: PreparedRequest(method="POST", url="https://oauth2.example.com/t"),
    )
    return answer


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_a_busy_token_endpoint_is_retried_not_reconnect(
    token_endpoint: dict[str, int], status: int
) -> None:
    token_endpoint["status"] = status
    result = await execution.execute_action(
        None,  # type: ignore[arg-type]
        tool=_tool(),
        received={},
        source="background",
        audit=False,
    )
    assert result.status == "auth_unavailable"
    assert client_actions._transient(result.status, result.payload)


async def test_a_refused_grant_still_asks_to_reconnect(token_endpoint: dict[str, int]) -> None:
    token_endpoint["status"] = 400
    result = await execution.execute_action(
        None,  # type: ignore[arg-type]
        tool=_tool(),
        received={},
        source="background",
        audit=False,
    )
    assert result.status == "auth_failed"
    assert not client_actions._transient(result.status, result.payload)
