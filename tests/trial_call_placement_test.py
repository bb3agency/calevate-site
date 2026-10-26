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
from datetime import UTC, datetime
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
from apps.api.db.session import long_running_statements, tenant_session
from apps.api.engine import get_engine
from apps.api.engine.vendor_http import EngineRejectedError
from apps.api.main import app
from calevate_shared.engine import CallContext
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.first_run_test import _owner
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


async def test_a_ready_answer_only_agent_places_a_test_call_from_the_shared_number(
    line: Line,
) -> None:
    """D-853: an agent that only answers calls, got ready and not taking calls, rings the
    owner through the same lend and dial as any test call; its greeting opens the call."""
    from apps.api.agents import lifecycle

    tenant_id, agent_id, principal = await _account(line, direction="inbound")
    async with tenant_session(tenant_id) as session:
        await lifecycle.prepare_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    placed = await _place(principal, agent_id, str(uuid.uuid4()))
    assert placed.status == "queued", placed
    assert len(line.lent_to) == 1


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


async def test_a_dial_refused_for_our_own_set_up_says_so_plainly_and_frees_the_key(
    line: Line, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The client can fix nothing here and the alarm has paged us, so the sentence says the
    problem is ours and names no provider (D-679)."""
    _tenant_id, agent_id, principal = await _account(line)

    async def _not_set_up(*_: Any, **__: Any) -> str:
        refused = EngineRejectedError(
            status=409, refused_statuses=frozenset({409}), vendor_code="calling_not_set_up"
        )
        refused.setup_refused = True
        raise refused

    monkeypatch.setattr(agents_service, "dispatch_call", _not_set_up)
    key = str(uuid.uuid4())
    with pytest.raises(ProblemError) as refused:
        await _place(principal, agent_id, key)
    problem = refused.value
    assert problem.code == trial_calls.TRIAL_CALL_NOT_PLACED
    assert "on our side" in problem.detail
    assert "thinnest" not in f"{problem.title} {problem.detail}".lower()
    with pytest.raises(ProblemError) as again:
        await _place(principal, agent_id, key)
    assert again.value.code == trial_calls.TRIAL_CALL_NOT_PLACED


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


async def test_the_own_number_tick_lets_the_placed_call_be_recorded(line: Line) -> None:
    """D-863. "Call me now" on the first run sends `number_is_mine`, whose audit row takes the
    audit chain's advisory lock (`compliance.audit.lock_chain`). Written on the request's
    own transaction, that lock was held until the response, so the call's own audit row,
    written in a separate transaction after the dial, waited on it until `statement_timeout`
    cancelled it: a rung phone answered 503 `database_busy`. A short budget reproduces the
    cancel in seconds rather than ten."""
    tenant_id, agent_id, _principal = await _account(line)
    headers = await _owner(tenant_id)
    with long_running_statements(timeout_ms=2_000):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
            placed = await http.post(
                "/v1/trial/calls",
                headers={
                    **headers,
                    "Idempotency-Key": uuid.uuid4().hex,
                },
                json={"agent_id": str(agent_id), "number": "98765 43210", "number_is_mine": True},
            )
    assert placed.status_code == 200, placed.text
    assert placed.json()["status"] == "queued"
    async with tenant_session(tenant_id) as session:
        actions = sorted(
            (
                await session.execute(
                    text(
                        "SELECT action FROM audit_log WHERE tenant_id = :t "
                        "AND action LIKE 'trial.%'"
                    ),
                    {"t": tenant_id},
                )
            ).scalars()
        )
    assert actions == ["trial.number_attested", "trial.test_call_placed"]


async def test_at_night_only_a_number_attested_as_the_owners_own_is_rung(
    line: Line, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Founder, 23 Oct 2026: an owner trying Calevate at 1 am gets their test call, because
    they attested the number as their own; an unattested number still waits for 09:00."""
    monkeypatch.setattr(compliance_service, "within_calling_hours", lambda *a, **k: False)
    _tenant_id, agent_id, principal = await _account(line)
    blocked = await _place(principal, agent_id, str(uuid.uuid4()))
    assert (blocked.status, blocked.blocked_rule) == ("blocked", "calling_hours")
    assert line.lent_to == []

    assert principal.tenant_id is not None
    async with tenant_session(principal.tenant_id) as session:
        placed = await trial_calls.place_trial_call(
            session,
            principal=principal,
            agent_id=agent_id,
            number="98765 43210",
            idempotency_key=str(uuid.uuid4()),
            own_number_attested=True,
        )
    assert placed.status == "queued"
    assert len(line.lent_to) == 1


@pytest.mark.parametrize("attested", [True, False])
async def test_only_the_own_number_test_call_reaches_the_engine_without_calling_hours(
    line: Line, monkeypatch: pytest.MonkeyPatch, attested: bool
) -> None:
    """D-872: the attested call is the one dial the engine is told may ring at any hour;
    any other test call carries the window like every dial."""
    engine = get_engine()
    contexts: list[CallContext] = []
    dial = engine.start_outbound_call

    async def _recording(ref: str, to: str, ctx: CallContext) -> str:
        contexts.append(ctx)
        return await dial(ref, to, ctx)

    monkeypatch.setattr(engine, "start_outbound_call", _recording)
    _tenant_id, agent_id, principal = await _account(line)
    assert principal.tenant_id is not None
    async with tenant_session(principal.tenant_id) as session:
        placed = await trial_calls.place_trial_call(
            session,
            principal=principal,
            agent_id=agent_id,
            number="98765 43210",
            idempotency_key=str(uuid.uuid4()),
            own_number_attested=attested,
        )
    assert placed.status == "queued"
    assert [ctx.rings_at_any_hour for ctx in contexts] == [attested]


async def test_a_dial_that_is_not_a_test_call_cannot_ask_to_ring_at_any_hour() -> None:
    with pytest.raises(ValueError):
        await agents_service.dispatch_call(
            None,  # type: ignore[arg-type]
            tenant_id=uuid.uuid4(),
            agent_id=uuid.uuid4(),
            lead_id=None,
            phone_e164="+919876543210",
            rings_at_any_hour=True,
        )


async def test_attesting_something_that_is_not_a_phone_number_is_refused() -> None:
    principal = Principal(
        realm="client", user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), role="owner"
    )
    with pytest.raises(ProblemError):
        await trial_calls.attest_own_number(principal=principal, number="not a number", ip=None)


def _gate_allows(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _allowed(*_: Any, **__: Any) -> Any:
        return SimpleNamespace(allowed=True, rule=None, reason=None)

    async def _no_trial(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(trial_calls, "check_dispatch", _allowed)
    monkeypatch.setattr(trial_calls, "read_trial_access", _no_trial)


async def test_with_neither_a_running_trial_nor_paid_access_the_call_is_not_ready(
    line: Line, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gate's answer alone is not enough: something must say which line the call takes."""
    _tenant_id, agent_id, principal = await _account(line)
    _gate_allows(monkeypatch)

    async def _not_paid(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(trial_calls, "read_paid_test_access", _not_paid)

    result = await _place(principal, agent_id, str(uuid.uuid4()))

    assert (result.status, result.blocked_rule) == ("blocked", trial_calls.NOT_READY_RULE)


async def test_a_test_copy_that_cannot_be_refreshed_frees_the_key(
    line: Line, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing was dialled, so the same key may be sent again once the copy can be made."""
    _tenant_id, agent_id, principal = await _account(line)
    _gate_allows(monkeypatch)

    async def _paid(*_: Any, **__: Any) -> Any:
        return SimpleNamespace(
            blocker=None,
            line="trial_line_copy",
            max_call_seconds=60,
            daily_cap=3,
            day_start=datetime.now(UTC),
        )

    async def _refresh_fails(**_: Any) -> str:
        raise RuntimeError("vendor refused the copy")

    monkeypatch.setattr(trial_calls, "read_paid_test_access", _paid)
    monkeypatch.setattr(trial_calls, "refresh_test_copy", _refresh_fails)
    key = str(uuid.uuid4())

    for _ in range(2):  # the second is not `idempotent_request_in_flight`: the key was freed
        with pytest.raises(RuntimeError):
            await _place(principal, agent_id, key)


def test_the_vendor_says_gone_on_a_404_or_our_own_not_found_only() -> None:
    assert agents_service._vendor_says_gone(ProblemError.not_found("Agent"))
    assert not agents_service._vendor_says_gone(ProblemError.conflict("x", "y"))
    assert not agents_service._vendor_says_gone(RuntimeError("boom"))


class _CountingSession:
    """Answers the advisory lock, then today's count of placed test calls."""

    def __init__(self, placed: int) -> None:
        self.placed = placed

    async def execute(self, *_: Any, **__: Any) -> Any:
        return SimpleNamespace(scalar_one=lambda: self.placed)


async def test_a_paid_test_call_past_the_daily_cap_is_refused_under_the_lock() -> None:
    """Counted with this call's own row, so a call at the cap passes and one past it does not;
    two placed at once cannot both slip under."""
    test = agents_service.OwnerTestDial(
        max_call_seconds=60, daily_cap=3, day_start=datetime.now(UTC)
    )
    session: Any = _CountingSession(3)
    await agents_service._hold_paid_test_slot(session, tenant_id=uuid.uuid4(), test=test)

    with pytest.raises(ProblemError) as refused:
        await agents_service._hold_paid_test_slot(
            _CountingSession(4),  # type: ignore[arg-type]
            tenant_id=uuid.uuid4(),
            test=test,
        )
    assert refused.value.code == trial_calls.DAILY_CAP_RULE
