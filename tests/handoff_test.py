"""Who a caller is handed to, and when nobody is (D-533).

Four things are worth a test here, and they are the four the founder's brief turns on:

1. **The order is the hunt list.** Position 0 answers; a later position is reached because
   the earlier ones are off duty or switched off — never because one did not pick up, which
   this engine cannot tell us in time to act on (`HandoffSpec`).
2. **Nobody's mobile rings outside hours, and it is enforced by ABSENCE.** The publish
   carries no handoff at all, so the agent has no tool to fire. A test that only checked
   `on_duty` would prove our intent; these check the config that reaches the adapter.
3. **Unknown hours are not open hours.** The one place this module deliberately takes the
   opposite default from FLOWS §3's "24/7 by default", because the thing at stake is a
   named person's private phone rather than whether an AI answers.
4. **The whole roster is one write.** Re-ordering and removing in one PUT, because four
   requests that half-apply put two people at position 1.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import handoff
from apps.api.agents import service as agents_service
from apps.api.agents.prompts import write_prompt_version
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine, reset_engine_cache
from sqlalchemy import text
from tests.conftest import accept_agreements

# The sync half of this module is pure-function work over a clock, so the async mark is
# applied to the two suites separately rather than to the module: a blanket
# `pytest.mark.asyncio` over a sync test is a PytestWarning per test, and a wall of them is
# how a real warning stops being read.

#: Mon-Sun 09:00-18:00 IST, in the shape `agents.business_hours` stores.
OPEN_9_TO_6 = {
    day: {"opens": "09:00", "closes": "18:00"}
    for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
}

#: 10:30 IST on a Wednesday, as the aware UTC instant the DB and `is_after_hours` take.
INSIDE = datetime(2026, 9, 2, 5, 0, tzinfo=UTC)
#: 23:00 IST the same day — the hour the founder's fourth decision is about.
OUTSIDE = datetime(2026, 9, 2, 17, 30, tzinfo=UTC)


def _member(position: int, phone: str, **kw: object) -> handoff.RosterMember:
    return handoff.RosterMember(
        id=uuid.uuid4(),
        position=position,
        label=f"Person {position}",
        phone_e164=phone,
        hours=kw.get("hours"),  # type: ignore[arg-type]
        active=bool(kw.get("active", True)),
        note=None,
    )


def test_the_first_person_on_the_list_who_is_on_duty_is_the_one_who_is_rung() -> None:
    duty = handoff.resolve_on_duty(
        [_member(0, "+919000000001"), _member(1, "+919000000002")],
        enabled=True,
        agent_hours=OPEN_9_TO_6,
        at=INSIDE,
    )
    assert duty.member is not None
    assert duty.member.phone_e164 == "+919000000001"
    assert duty.reason is None


def test_an_inactive_person_is_skipped_and_the_next_one_takes_it() -> None:
    """Somebody on holiday keeps their POSITION and is passed over — coming back is one
    toggle rather than a re-ordering."""
    duty = handoff.resolve_on_duty(
        [_member(0, "+919000000001", active=False), _member(1, "+919000000002")],
        enabled=True,
        agent_hours=OPEN_9_TO_6,
        at=INSIDE,
    )
    assert duty.member is not None
    assert duty.member.phone_e164 == "+919000000002"


def test_a_persons_own_hours_beat_the_agents() -> None:
    """A rota: the first person works evenings only, so at 10:30 the second takes it."""
    evenings = {"wed": {"opens": "18:00", "closes": "22:00"}}
    duty = handoff.resolve_on_duty(
        [_member(0, "+919000000001", hours=evenings), _member(1, "+919000000002")],
        enabled=True,
        agent_hours=OPEN_9_TO_6,
        at=INSIDE,
    )
    assert duty.member is not None
    assert duty.member.phone_e164 == "+919000000002"


def test_nobody_is_on_duty_at_eleven_at_night() -> None:
    """Decision 4. The reason is `outside_hours` and not `hours_unknown`, because the two
    send a client looking in different places."""
    duty = handoff.resolve_on_duty(
        [_member(0, "+919000000001")], enabled=True, agent_hours=OPEN_9_TO_6, at=OUTSIDE
    )
    assert duty.member is None
    assert duty.reason == "outside_hours"
    assert duty.remediation is not None


def test_hours_we_do_not_know_are_not_hours_we_ring_a_mobile_in() -> None:
    """The deliberate inversion of FLOWS §3's 24/7 default, and its own reason code — the
    client is told to record their opening hours rather than left with a dead feature."""
    duty = handoff.resolve_on_duty(
        [_member(0, "+919000000001")], enabled=True, agent_hours=None, at=INSIDE
    )
    assert duty.member is None
    assert duty.reason == "hours_unknown"
    assert "opening hours" in (duty.remediation or "")


def test_the_switch_and_the_empty_list_are_told_apart() -> None:
    off = handoff.resolve_on_duty([], enabled=False, agent_hours=OPEN_9_TO_6, at=INSIDE)
    assert off.reason == "disabled"
    empty = handoff.resolve_on_duty([], enabled=True, agent_hours=OPEN_9_TO_6, at=INSIDE)
    assert empty.reason == "no_members"
    nobody = handoff.resolve_on_duty(
        [_member(0, "+919000000001", active=False)],
        enabled=True,
        agent_hours=OPEN_9_TO_6,
        at=INSIDE,
    )
    assert nobody.reason == "none_active"


def test_a_spec_is_built_only_when_somebody_is_on_duty() -> None:
    """`handoff_spec(None-duty)` is None, which is the whole of decision 4's enforcement:
    the adapter emits no transfer tool for it."""
    nobody = handoff.resolve_on_duty([], enabled=False, agent_hours=None, at=INSIDE)
    assert handoff.handoff_spec(nobody, trigger=None, language="te-IN", brief_url=None) is None

    duty = handoff.resolve_on_duty(
        [_member(0, "+919000000001")], enabled=True, agent_hours=OPEN_9_TO_6, at=INSIDE
    )
    spec = handoff.handoff_spec(duty, trigger="  ", language="te-IN", brief_url=None)
    assert spec is not None
    assert spec.destination_e164 == "+919000000001"
    # A blank trigger falls back to the composed default rather than publishing an empty
    # tool description, which the model would read as "never".
    assert spec.trigger == handoff.HANDOFF_TRIGGER_DEFAULT
    assert spec.spoken_line == handoff.HANDOFF_SPOKEN_TEMPLATES["te-IN"]


def test_an_unknown_language_falls_back_rather_than_going_silent() -> None:
    """A spoken line is what the caller hears while the handover is placed; a KeyError here
    would be dead air on a live call."""
    assert handoff.spoken_line_for("xx-XX") == handoff.HANDOFF_SPOKEN_TEMPLATES["en-IN"]


# ------------------------------------------------------------------ the publish


async def _agent_with_roster(*, enabled: bool, hours: dict[str, object] | None) -> tuple:
    reset_engine_cache()
    created = await admin_service.create_organization(
        name="Handoff publish",
        slug=f"handoff-pub-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    agent_id = uuid.UUID(str(created["agent_id"]))
    await accept_agreements(tenant_id)
    async with tenant_session(tenant_id) as session:
        # A publish refuses an agent with no applied script, which is the state
        # `create_organization` leaves the receptionist in — so the fixture supplies one
        # rather than the test asserting a refusal it is not about.
        await write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="[IDENTITY] Handoff test receptionist.\n",
            notes="fixture",
            created_by=None,
        )
        await session.execute(
            text(
                "UPDATE agents SET handoff_enabled = :en, "
                "business_hours = CAST(:hours AS jsonb) WHERE id = :aid"
            ),
            {
                "en": enabled,
                "hours": None if hours is None else json.dumps(hours),
                "aid": agent_id,
            },
        )
        await session.execute(
            text(
                "INSERT INTO agent_handoff_members "
                "(id, tenant_id, agent_id, position, label, phone_e164) "
                "VALUES (:id, :tid, :aid, 0, 'Owner', '+919000000777')"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "aid": agent_id},
        )
    return tenant_id, agent_id


@pytest.mark.asyncio
async def test_the_publish_carries_the_on_duty_number_all_the_way_to_the_engine() -> None:
    """END TO END, and asserted on what the ENGINE HOLDS rather than on what we sent — an
    adapter that dropped the tool would pass the second kind of check.
    """
    tenant_id, agent_id = await _agent_with_roster(enabled=True, hours=OPEN_9_TO_6)
    async with tenant_session(tenant_id) as session:
        await agents_service.publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
        ref = (
            await session.execute(
                text("SELECT engine_agent_ref FROM agents WHERE id = :aid"), {"aid": agent_id}
            )
        ).scalar()
    snapshot = await get_engine().get_agent(str(ref))
    assert snapshot.handoff_destinations_readable
    # The window is every day 09:00-18:00 IST, so this is time-dependent by construction:
    # the assertion is the one the product makes, and outside those hours it is the OTHER
    # test below that holds. Both are asserted rather than one being made unconditional,
    # because "the number reached the engine" and "no number reached the engine" are the
    # two halves of the same rule.
    on_duty_now = handoff.resolve_on_duty(
        [_member(0, "+919000000777")],
        enabled=True,
        agent_hours=OPEN_9_TO_6,
        at=datetime.now(UTC),
    )
    expected = ("+919000000777",) if on_duty_now.member is not None else ()
    assert snapshot.handoff_destinations == expected


@pytest.mark.asyncio
async def test_an_agent_with_handovers_switched_off_publishes_no_destination() -> None:
    """The safe default, proved on the engine: a client who has not configured this has an
    agent that cannot ring anybody's mobile, whatever the roster table holds."""
    tenant_id, agent_id = await _agent_with_roster(enabled=False, hours=OPEN_9_TO_6)
    async with tenant_session(tenant_id) as session:
        await agents_service.publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
        ref = (
            await session.execute(
                text("SELECT engine_agent_ref FROM agents WHERE id = :aid"), {"aid": agent_id}
            )
        ).scalar()
    snapshot = await get_engine().get_agent(str(ref))
    assert snapshot.handoff_destinations == ()


@pytest.mark.asyncio
async def test_an_agent_with_no_recorded_hours_publishes_no_destination() -> None:
    """The inversion above, proved where it matters. A client who filled in the handover
    list and never recorded their opening hours has an agent that will not ring anyone —
    and `GET /v1/agents/{id}/handoff` tells them exactly that, with the fix.
    """
    tenant_id, agent_id = await _agent_with_roster(enabled=True, hours=None)
    async with tenant_session(tenant_id) as session:
        await agents_service.publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
        ref = (
            await session.execute(
                text("SELECT engine_agent_ref FROM agents WHERE id = :aid"), {"aid": agent_id}
            )
        ).scalar()
    snapshot = await get_engine().get_agent(str(ref))
    assert snapshot.handoff_destinations == ()
