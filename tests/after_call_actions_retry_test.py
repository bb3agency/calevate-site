"""After-call actions retry a transient failure, and the re-run sends nothing twice."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from apps.api.actions.execution import ExecutionResult
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.workers import client_actions
from arq import Retry


class _Session:
    def __init__(self, agent_id: uuid.UUID) -> None:
        self._row = (agent_id, "exec_1", "inbound", "+911140000000", "+911140000001", {})

    async def execute(self, *_a: Any, **_kw: Any) -> Any:
        return SimpleNamespace(first=lambda: self._row)


def _tool(kind: str) -> Any:
    return SimpleNamespace(id=uuid.uuid4(), kind=kind, enabled=True, trigger="after_call")


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    agent_id = uuid.uuid4()
    message, record = _tool("whatsapp"), _tool("crm")
    state: dict[str, Any] = {"sent": [], "crm_fails": 1, "alarms": []}

    @asynccontextmanager
    async def _session(_tenant_id: uuid.UUID) -> AsyncIterator[_Session]:
        yield _Session(agent_id)

    async def _enabled(_s: Any, **_kw: Any) -> bool:
        return True

    async def _tools(_s: Any, **_kw: Any) -> list[Any]:
        return [message, record]

    async def _execute(_s: Any, *, tool: Any, **_kw: Any) -> ExecutionResult:
        state["sent"].append(tool.kind)
        if tool.kind == "crm" and state["crm_fails"]:
            state["crm_fails"] -= 1
            return ExecutionResult(
                ok=False, payload={"error": "crm_error", "status_code": 503}, status="crm_error"
            )
        return ExecutionResult(ok=True, payload={"status": "sent"}, status="delivered")

    monkeypatch.setattr(client_actions, "tenant_session", _session)
    monkeypatch.setattr(client_actions, "actions_enabled", _enabled)
    monkeypatch.setattr(client_actions, "list_tools", _tools)
    monkeypatch.setattr(client_actions, "execute_action", _execute)
    monkeypatch.setattr(
        client_actions, "alert", lambda _st, code, **_kw: state["alarms"].append(code)
    )
    return state


def _payload() -> dict[str, str]:
    return {"tenant_id": str(uuid.uuid4()), "call_id": str(uuid.uuid4())}


async def test_a_transient_failure_retries_and_the_rerun_skips_what_went_out(
    wired: dict[str, Any],
) -> None:
    payload = _payload()
    with pytest.raises(Retry):
        await client_actions.run_after_call_actions({"job_try": 1}, payload)
    assert wired["sent"] == ["whatsapp", "crm"]

    assert await client_actions.run_after_call_actions({"job_try": 2}, payload) == "delivered"
    assert wired["sent"] == ["whatsapp", "crm", "crm"], "the message is not sent twice"
    assert wired["alarms"] == []


async def test_the_last_attempt_alarms_instead_of_retrying(wired: dict[str, Any]) -> None:
    wired["crm_fails"] = WORKER_MAX_TRIES
    result = await client_actions.run_after_call_actions(
        {"job_try": WORKER_MAX_TRIES}, _payload()
    )
    assert result == "delivered,crm_error"
    assert wired["alarms"] == ["client_action_not_completed"]
