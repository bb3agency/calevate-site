"""Whether an engine can hand a caller to a person, and what publishing does when it cannot.

The hand-over is the engine's own in-call transfer, from a destination fixed at publish.
An engine without one is not a reason to refuse the publish: `spec_for` publishes NO
destination and the client's screen names the reason, because a number on a platform that
cannot dial it is a promise to a caller nobody can keep.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.agents import handoff
from apps.api.agents.handoff import _UNAVAILABLE_REASONS, spec_for
from apps.api.agents.transfer_providers import PLATFORM_CANNOT_TRANSFER, transfer_blocked_reason
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine.fake import DEFAULT_FAKE_CAPABILITIES, DICTATED_SPEECH_CAPABILITIES, FakeEngine
from sqlalchemy import text
from tests.conftest import (
    INSERT_HANDOFF_MEMBER_SQL,
    SET_BUSINESS_HOURS_SQL,
    accept_agreements,
    create_org_with_receptionist,
)

STAFF = "+919812345601"
ALWAYS_OPEN = (
    "{"
    + ",".join(
        f'"{day}":{{"opens":"00:00","closes":"23:59"}}'
        for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    )
    + "}"
)


async def test_an_engine_with_an_in_call_handover_is_not_blocked() -> None:
    assert transfer_blocked_reason(FakeEngine(capabilities=DEFAULT_FAKE_CAPABILITIES)) is None


async def test_an_engine_without_one_is_blocked_by_name() -> None:
    engine = FakeEngine(capabilities=DICTATED_SPEECH_CAPABILITIES)
    assert engine.capabilities.in_call_handoff is False
    assert transfer_blocked_reason(engine) == PLATFORM_CANNOT_TRANSFER


async def test_the_client_is_given_a_sentence_for_the_platform_reason() -> None:
    """`PLATFORM_CANNOT_TRANSFER` reaches a client's own handover screen, so it owes them
    a sentence and a next step."""
    assert PLATFORM_CANNOT_TRANSFER in _UNAVAILABLE_REASONS
    assert "call-back" in _UNAVAILABLE_REASONS[PLATFORM_CANNOT_TRANSFER]


async def _org_with_roster() -> tuple[uuid.UUID, uuid.UUID]:
    created = await create_org_with_receptionist(
        name="Handover gate",
        slug=f"handover-gate-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="en-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    agent_id = uuid.UUID(str(created["agent_id"]))
    await accept_agreements(tenant_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(INSERT_HANDOFF_MEMBER_SQL),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "aid": agent_id,
                "pos": 0,
                "label": "Priya",
                "phone": STAFF,
            },
        )
        await session.execute(
            text("UPDATE agents SET handoff_enabled = true WHERE id = :aid"), {"aid": agent_id}
        )
        await session.execute(
            text(SET_BUSINESS_HOURS_SQL), {"tid": tenant_id, "hours": ALWAYS_OPEN}
        )
    return tenant_id, agent_id


async def _spec(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> tuple[object, handoff.OnDuty]:
    async with tenant_session(tenant_id) as session:
        agent = dict(
            (
                await session.execute(
                    text(
                        "SELECT a.id, a.handoff_enabled, a.handoff_trigger, "
                        "  bp.hours AS business_hours, a.language_primary FROM agents a "
                        "  LEFT JOIN business_profiles bp ON bp.tenant_id = a.tenant_id "
                        "WHERE a.id = :aid"
                    ),
                    {"aid": agent_id},
                )
            )
            .mappings()
            .one()
        )
        return await spec_for(session, agent)


async def test_a_roster_on_an_engine_that_cannot_transfer_publishes_no_destination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The platform is asked before the roster, and it decides on its own: a staffed,
    always-open roster still publishes nothing, with the reason the client is shown."""
    tenant_id, agent_id = await _org_with_roster()
    monkeypatch.setattr(
        handoff, "get_engine", lambda: FakeEngine(capabilities=DICTATED_SPEECH_CAPABILITIES)
    )
    spec, duty = await _spec(tenant_id, agent_id)
    assert spec is None
    assert duty.member is None
    assert duty.reason == PLATFORM_CANNOT_TRANSFER
    assert duty.remediation is not None


async def test_the_same_roster_on_an_engine_that_can_transfer_publishes_its_destination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _org_with_roster()
    monkeypatch.setattr(
        handoff, "get_engine", lambda: FakeEngine(capabilities=DEFAULT_FAKE_CAPABILITIES)
    )
    spec, duty = await _spec(tenant_id, agent_id)
    assert spec is not None
    assert duty.member is not None
