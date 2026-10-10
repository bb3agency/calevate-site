"""Placing a free-trial test call end to end (D-697): the gate, the idempotency record,
the platform's one trial line, the lend of the shared number and the dial, through
`trial_calls.place_trial_call` and `agents.service.dispatch_call(trial=...)`.

The engine is the test deployment's fake; the shared number's lend is replaced with a
recorder, so no vendor is reached.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents import service as agents_service
from apps.api.agents import trial_calls
from apps.api.campaigns import engine_numbers
from apps.api.compliance import service as compliance_service
from apps.api.compliance.trial_access import TrialAccess
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from sqlalchemy import text
from tests.trial_test_calls_test import TRIAL_NUMBER, _trial_call_row, _trial_tenant

pytestmark = [pytest.mark.rls]


@dataclass
class Line:
    lend: bool = True
    lent_to: list[str] = field(default_factory=list)
    tenants: list[UUID] = field(default_factory=list)


@pytest.fixture
async def line(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Line]:
    state = Line()
    monkeypatch.setattr(trial_calls, "trial_calling_ready", lambda: True)
    monkeypatch.setattr(get_settings(), "trial_caller_number", TRIAL_NUMBER)
    monkeypatch.setattr(compliance_service, "within_calling_hours", lambda *a, **k: True)

    async def _lend(agent_ref: str) -> bool:
        state.lent_to.append(agent_ref)
        return state.lend

    monkeypatch.setattr(engine_numbers, "lend_trial_line", _lend)
    yield state
    # The trial line is platform-wide: end every test call this file started, so no
    # later test finds the line held.
    for tenant_id in state.tenants:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE calls SET status = 'completed' WHERE tenant_id = :t AND trial_call"),
                {"t": tenant_id},
            )


async def _account(line: Line, **kwargs: Any) -> tuple[UUID, UUID, Principal]:
    tenant_id, agent_id = await _trial_tenant(**kwargs)
    line.tenants.append(tenant_id)
    principal = Principal(realm="client", user_id=uuid.uuid4(), tenant_id=tenant_id, role="owner")
    return tenant_id, agent_id, principal


async def _place(
    principal: Principal, agent_id: UUID, key: str, number: str = "98765 43210"
) -> trial_calls.TrialCallResult:
    assert principal.tenant_id is not None
    async with tenant_session(principal.tenant_id) as session:
        return await trial_calls.place_trial_call(
            session, principal=principal, agent_id=agent_id, number=number, idempotency_key=key
        )


async def _trial_calls(tenant_id: UUID) -> list[str]:
    async with tenant_session(tenant_id) as session:
        return [
            str(r)
            for r in (
                await session.execute(
                    text("SELECT status FROM calls WHERE tenant_id = :t AND trial_call"),
                    {"t": tenant_id},
                )
            ).scalars()
        ]


async def test_a_number_that_is_not_indian_is_refused_before_anything_else() -> None:
    principal = Principal(
        realm="client", user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), role="owner"
    )
    with pytest.raises(ProblemError) as refused:
        await trial_calls.place_trial_call(
            None,  # type: ignore[arg-type]
            principal=principal,
            agent_id=uuid.uuid4(),
            number="not a phone",
            idempotency_key="k",
        )
    assert refused.value.code == "trial_call_number_invalid"


async def test_a_test_call_is_placed_from_the_shared_number_and_a_retry_replays_it(
    line: Line,
) -> None:
    tenant_id, agent_id, principal = await _account(line)
    key = str(uuid.uuid4())
    placed = await _place(principal, agent_id, key)
    assert placed.status == "queued"
    assert placed.call_handle
    assert len(line.lent_to) == 1, "the shared number is lent to the dialling agent"
    assert await _trial_calls(tenant_id) != []
    async with tenant_session(tenant_id) as session:
        audited = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE tenant_id = :t "
                    "AND action = 'trial.test_call_placed'"
                ),
                {"t": tenant_id},
            )
        ).scalar()
    assert audited == 1

    again = await _place(principal, agent_id, key)
    assert again == placed, "the same key answers from the stored response"
    assert len(line.lent_to) == 1, "and dials nothing a second time"


async def test_a_refused_gate_is_an_answer_stored_against_the_key(line: Line) -> None:
    tenant_id, agent_id, principal = await _account(line, pledged=False)
    key = str(uuid.uuid4())
    blocked = await _place(principal, agent_id, key)
    assert (blocked.status, blocked.blocked_rule) == ("blocked", "outbound_pledge_missing")
    assert blocked.call_handle is None
    assert await _place(principal, agent_id, key) == blocked
    assert line.lent_to == [] and await _trial_calls(tenant_id) == []


async def test_a_number_the_line_cannot_be_lent_closes_the_dial_and_frees_the_key(
    line: Line,
) -> None:
    tenant_id, agent_id, principal = await _account(line)
    key = str(uuid.uuid4())
    line.lend = False
    with pytest.raises(ProblemError) as refused:
        await _place(principal, agent_id, key)
    assert refused.value.code == "trial_line_unavailable"
    assert "queued" not in await _trial_calls(tenant_id), "the unplaced dial holds no line"

    line.lend = True
    retried = await _place(principal, agent_id, key)
    assert retried.status == "queued", "a dial that never rang may be retried on its key"


async def test_a_busy_line_refuses_and_frees_the_key(line: Line) -> None:
    other, other_agent, _ = await _account(line)
    _tenant_id, agent_id, principal = await _account(line)
    await _trial_call_row(other, other_agent, status="ringing")
    key = str(uuid.uuid4())
    with pytest.raises(ProblemError) as busy:
        await _place(principal, agent_id, key)
    assert busy.value.code == "trial_line_busy"
    assert line.lent_to == []

    async with tenant_session(other) as session:
        await session.execute(
            text("UPDATE calls SET status = 'completed' WHERE tenant_id = :t"), {"t": other}
        )
    assert (await _place(principal, agent_id, key)).status == "queued"


async def test_a_gate_that_fails_frees_the_key(line: Line, monkeypatch: pytest.MonkeyPatch) -> None:
    _tenant_id, agent_id, principal = await _account(line)

    async def _broken(*_: Any, **__: Any) -> Any:
        raise RuntimeError("database went away")

    working = trial_calls.check_dispatch
    monkeypatch.setattr(trial_calls, "check_dispatch", _broken)
    key = str(uuid.uuid4())
    with pytest.raises(RuntimeError):
        await _place(principal, agent_id, key)
    monkeypatch.setattr(trial_calls, "check_dispatch", working)
    assert (await _place(principal, agent_id, key)).status == "queued"


async def test_a_dial_whose_outcome_is_unknown_is_never_retried_on_its_key(
    line: Line, monkeypatch: pytest.MonkeyPatch
) -> None:
    _tenant_id, agent_id, principal = await _account(line)

    async def _unconfirmed(*_: Any, **__: Any) -> str:
        raise agents_service.DialUnconfirmedError(call_id=uuid.uuid4(), code="read_timeout")

    monkeypatch.setattr(agents_service, "dispatch_call", _unconfirmed)
    key = str(uuid.uuid4())
    with pytest.raises(ProblemError) as unknown:
        await _place(principal, agent_id, key)
    assert unknown.value.code == "dial_unconfirmed"
    with pytest.raises(ProblemError) as in_flight:
        await _place(principal, agent_id, key)
    assert in_flight.value.code == "idempotent_request_in_flight"


async def test_a_failure_that_may_have_rung_keeps_the_key(
    line: Line, monkeypatch: pytest.MonkeyPatch
) -> None:
    _tenant_id, agent_id, principal = await _account(line)

    async def _crashed(*_: Any, **__: Any) -> str:
        raise RuntimeError("connection reset after send")

    monkeypatch.setattr(agents_service, "dispatch_call", _crashed)
    key = str(uuid.uuid4())
    with pytest.raises(RuntimeError):
        await _place(principal, agent_id, key)
    with pytest.raises(ProblemError) as in_flight:
        await _place(principal, agent_id, key)
    assert in_flight.value.code == "idempotent_request_in_flight"


@pytest.mark.parametrize(
    ("free_minutes", "used", "expected"),
    [
        (None, 0, 300),
        (30, 0, 300),
        (30, 30 * 60 - 120, 120),
        (30, 30 * 60 - 10, 60),
    ],
)
def test_the_call_limit_is_the_console_limit_or_what_is_left(
    free_minutes: int | None, used: int, expected: int
) -> None:
    access = TrialAccess(
        trial=SimpleNamespace(free_minutes=free_minutes),  # type: ignore[arg-type]
        seconds_used=used,
        calls_today=0,
        daily_cap=5,
        max_call_seconds=300,
        at=None,  # type: ignore[arg-type]
    )
    assert access.call_seconds == expected
