"""An in-call action runs once per call, action and meaningful arguments: ThinnestAI's
backup model can re-run a turn and call the same action again (ThinnestAI's email of 11 Oct
2026, VENDOR-STATED). A repeat answers with the first answer; a booking, a message and a
payment link are each made once.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from apps.api.actions import in_call
from apps.api.actions.execution import CallFacts, ExecutionResult
from apps.api.reliability import in_call_once
from apps.api.reliability.in_call_once import IN_HAND_SAY, once_key, once_per_call


def _ref() -> str:
    return f"out_{uuid.uuid4()}"


async def test_a_repeat_answers_with_the_first_answer_and_runs_nothing() -> None:
    ran: list[int] = []

    async def run() -> dict[str, Any]:
        ran.append(1)
        return {"status": "booked", "say": "Booked.", "at": str(len(ran))}

    call = _ref()
    first = await once_per_call(call_ref=call, action="callback", args={"t": "11:00"}, run=run)
    again = await once_per_call(call_ref=call, action="callback", args={"t": "11:00"}, run=run)
    assert first == again == {"status": "booked", "say": "Booked.", "at": "1"}
    assert ran == [1]


def test_wording_case_and_spacing_do_not_make_a_new_request() -> None:
    call = _ref()
    assert once_key(call, "a", {"name": "Asha  Menon"}) == once_key(
        call, "a", {"name": "asha menon"}
    )
    assert once_key(call, "a", {"t": "11:00"}) != once_key(call, "a", {"t": "12:00"})
    assert once_key(call, "a", {}) != once_key(_ref(), "a", {})


async def test_an_answer_meaning_nothing_was_done_is_not_kept() -> None:
    answers = iter([{"status": "unavailable", "say": "no"}, {"status": "delivered", "say": "sent"}])

    async def run() -> dict[str, Any]:
        return next(answers)

    call = _ref()
    assert (await once_per_call(call_ref=call, action="w", args={}, run=run))["status"] == (
        "unavailable"
    )
    assert (await once_per_call(call_ref=call, action="w", args={}, run=run))["status"] == (
        "delivered"
    )


async def test_a_repeat_while_the_first_is_running_waits_for_its_answer() -> None:
    release = asyncio.Event()
    ran: list[int] = []

    async def slow() -> dict[str, Any]:
        ran.append(1)
        await release.wait()
        return {"status": "link_sent", "say": "sent"}

    call = _ref()
    first = asyncio.create_task(once_per_call(call_ref=call, action="p", args={}, run=slow))
    await asyncio.sleep(0.1)
    second = asyncio.create_task(once_per_call(call_ref=call, action="p", args={}, run=slow))
    await asyncio.sleep(0.3)
    release.set()
    assert (await first) == (await second) == {"status": "link_sent", "say": "sent"}
    assert ran == [1]


async def test_a_repeat_past_the_wait_is_told_it_is_in_hand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(in_call_once, "WAIT_S", 0.2)
    release = asyncio.Event()

    async def slow() -> dict[str, Any]:
        await release.wait()
        return {"status": "booked", "say": "ok"}

    call = _ref()
    first = asyncio.create_task(once_per_call(call_ref=call, action="b", args={}, run=slow))
    await asyncio.sleep(0.05)
    second = await once_per_call(call_ref=call, action="b", args={}, run=slow)
    assert second == {"status": "in_hand", "say": IN_HAND_SAY}
    release.set()
    await first


async def test_a_failure_forgets_the_claim_so_a_retry_runs() -> None:
    attempts: list[int] = []

    async def flaky() -> dict[str, Any]:
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("boom")
        return {"status": "booked", "say": "ok"}

    call = _ref()
    with pytest.raises(RuntimeError):
        await once_per_call(call_ref=call, action="b", args={}, run=flaky)
    assert (await once_per_call(call_ref=call, action="b", args={}, run=flaky))[
        "status"
    ] == "booked"


async def test_without_redis_the_action_still_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken() -> Any:
        raise ConnectionError("redis down")

    monkeypatch.setattr(in_call_once, "get_redis", broken)

    async def run() -> dict[str, Any]:
        return {"status": "booked", "say": "ok"}

    assert (await once_per_call(call_ref=_ref(), action="b", args={}, run=run))[
        "status"
    ] == "booked"


# --- the client's actions through the one in-call door ---------------------------------------


class _Tool:
    def __init__(self, kind: str) -> None:
        self.id = uuid.uuid4()
        self.kind = kind
        self.config: dict[str, Any] = {}


@pytest.mark.parametrize(
    ("kind", "status"),
    [("calendar", "booked"), ("whatsapp", "delivered"), ("payment_link", "link_sent")],
)
async def test_a_repeated_client_action_is_done_once(
    monkeypatch: pytest.MonkeyPatch, kind: str, status: str
) -> None:
    tool = _Tool(kind)
    done: list[dict[str, Any]] = []

    async def in_call_tool(_session: Any, *, agent_id: uuid.UUID, name: str) -> _Tool:
        return tool

    async def execute_action(_session: Any, **kwargs: Any) -> ExecutionResult:
        done.append(kwargs["received"])
        return ExecutionResult(ok=True, payload={"ref": f"r{len(done)}"}, status=status)

    monkeypatch.setattr(in_call, "in_call_tool", in_call_tool)
    monkeypatch.setattr(in_call, "execute_action", execute_action)
    call = CallFacts(call_ref=_ref(), caller_e164="+919876500001", direction="inbound")
    tenant, agent = uuid.uuid4(), uuid.uuid4()
    args = {"start": "2026-10-12T11:00", "amount": "500"}
    first = await in_call.run_in_call_action(
        tenant_id=tenant, agent_id=agent, name="act", args=args, call=call
    )
    # The backup model re-runs the turn: the same action, the same values, its own spacing.
    again = await in_call.run_in_call_action(
        tenant_id=tenant,
        agent_id=agent,
        name="act",
        args={"start": " 2026-10-12T11:00 ", "amount": "500"},
        call=call,
    )
    assert len(done) == 1
    assert first.body() == again.body() and first.status == status


async def test_the_per_call_message_cap_still_applies_to_new_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = _Tool("whatsapp")

    async def in_call_tool(_session: Any, *, agent_id: uuid.UUID, name: str) -> _Tool:
        return tool

    async def execute_action(_session: Any, **kwargs: Any) -> ExecutionResult:
        return ExecutionResult(ok=True, payload={}, status="delivered")

    monkeypatch.setattr(in_call, "in_call_tool", in_call_tool)
    monkeypatch.setattr(in_call, "execute_action", execute_action)
    call = CallFacts(call_ref=_ref(), caller_e164="+919876500002", direction="inbound")
    tenant, agent = uuid.uuid4(), uuid.uuid4()
    statuses = [
        (
            await in_call.run_in_call_action(
                tenant_id=tenant, agent_id=agent, name="wa", args={"t": str(i)}, call=call
            )
        ).status
        for i in range(3)
    ]
    assert statuses == ["delivered", "delivered", "limit_reached"]
