"""The quiet-line alert (D-746): a working forwarded line whose client normally gets calls and
has had none for three days opens ONE episode, which the next call closes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from apps.api.core import alerting
from apps.api.crm.attention import attention_queue
from apps.api.db.session import tenant_session
from apps.api.forwarding import quiet
from sqlalchemy import text
from tests.forwarding_fixtures import add_line, give_calevate_number, make_client

pytestmark = [pytest.mark.rls]


async def _calls(tenant_id: UUID, agent_id: UUID, at: list[datetime]) -> None:
    async with tenant_session(tenant_id) as session:
        for moment in at:
            call_id = uuid.uuid4()
            await session.execute(
                text(
                    "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                    "from_e164, status, started_at, created_at, updated_at) VALUES (:id, :t, :a, "
                    ":e, 'inbound', '+919700000002', 'completed', :at, :at, :at)"
                ),
                {"id": call_id, "t": tenant_id, "a": agent_id, "e": f"in_{call_id}", "at": moment},
            )


async def _working_line(tenant_id: UUID) -> UUID:
    line = await add_line(tenant_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(text("UPDATE forwarded_lines SET status = 'working'"))
    return line.id


@pytest.fixture
def alarms(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    raised: list[tuple[str, str]] = []
    monkeypatch.setattr(
        quiet, "alert", lambda stage, code, **kw: raised.append(("raise", str(kw.get("episode"))))
    )
    monkeypatch.setattr(
        quiet,
        "resolve_alert",
        lambda stage, code, **kw: raised.append(("resolve", str(kw.get("episode")))),
    )
    return raised


async def test_a_busy_line_gone_quiet_opens_one_episode_and_a_call_closes_it(
    alarms: list[tuple[str, str]],
) -> None:
    tenant_id, agent_id, _ = await make_client("quiet")
    await give_calevate_number(tenant_id, agent_id)
    line_id = await _working_line(tenant_id)
    now = datetime.now(UTC)
    # Busy before: seven calls over four days, ending four days ago.
    await _calls(
        tenant_id,
        agent_id,
        [now - timedelta(days=d, hours=h) for d in (4, 5, 6, 7) for h in (1, 2)][:7],
    )
    async with tenant_session(tenant_id) as session:
        assert await quiet.sweep_tenant(session, tenant_id=tenant_id, now=now) == "quiet"
        assert await quiet.sweep_tenant(session, tenant_id=tenant_id, now=now) == "steady"
        queue = await attention_queue(session)
    assert alarms == [("raise", str(line_id))]
    assert queue["counts"].get("forwarded_line_quiet") == 1

    await _calls(tenant_id, agent_id, [now])
    async with tenant_session(tenant_id) as session:
        assert await quiet.sweep_tenant(session, tenant_id=tenant_id, now=now) == "recovered"
        queue = await attention_queue(session)
    assert alarms[-1] == ("resolve", str(line_id))
    assert "forwarded_line_quiet" not in queue["counts"]


async def test_a_business_that_rarely_gets_calls_is_not_alerted(
    alarms: list[tuple[str, str]],
) -> None:
    tenant_id, agent_id, _ = await make_client("rare")
    await give_calevate_number(tenant_id, agent_id)
    await _working_line(tenant_id)
    now = datetime.now(UTC)
    # Two calls in a fortnight is ordinary silence for this business.
    await _calls(tenant_id, agent_id, [now - timedelta(days=5), now - timedelta(days=9)])
    async with tenant_session(tenant_id) as session:
        assert await quiet.sweep_tenant(session, tenant_id=tenant_id, now=now) == "steady"
    assert alarms == []


async def test_an_untested_line_is_not_watched(alarms: list[tuple[str, str]]) -> None:
    tenant_id, agent_id, _ = await make_client("untested")
    await give_calevate_number(tenant_id, agent_id)
    await add_line(tenant_id)
    now = datetime.now(UTC)
    await _calls(tenant_id, agent_id, [now - timedelta(days=d) for d in range(4, 12)])
    async with tenant_session(tenant_id) as session:
        assert await quiet.sweep_tenant(session, tenant_id=tenant_id, now=now) == "no_lines"
    assert alarms == []


def test_the_alarm_is_classified_attention() -> None:
    from apps.api.core.alarm_severity import ALARM_SEVERITY

    assert ALARM_SEVERITY[quiet.ALARM] == "attention"
    assert alerting  # imported for the patch target's module
