"""AI callback on a needs-follow-up call (D-21, M2 half).

The feature is one button, and almost all of its design is about refusing. A robot
that rings a customer repeatedly because each call ended inconclusively is the harm
TRAI's rules exist to prevent, so these tests spend their attention on the chain
bound, the freshness window, and the outcomes that do NOT warrant a follow-up.

The happy path is deliberately the shortest test here: it re-dispatches the same agent
to the same lead with the previous call's SUMMARY as context — never the transcript.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.admin import service as admin_service
from apps.api.core.errors import ProblemError
from apps.api.crm import service
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine, reset_engine_cache
from sqlalchemy import text
from tests.conftest import accept_agreements


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    """11:00 IST — the gate's calling-hours rule has its own tests; here it must not
    decide the outcome by accident (see lead_ingest_test for how we learned that)."""
    fixed = datetime(2026, 8, 11, 5, 30, tzinfo=UTC) + timedelta(hours=5, minutes=30)
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: fixed)


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    reset_engine_cache()
    created = await admin_service.create_organization(
        name="Callback Clinic",
        slug=f"cb-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    # The four agreements, accepted (migration a9d4e70c31b8) — supplied, never assumed
    # away, in the shape `arm_agent_for_outbound` established. Every dial, launch and
    # publish gate now refuses an organisation that has not accepted them, so a fixture
    # without this reports `agreements_not_accepted` in place of the answer under test.
    await accept_agreements(uuid.UUID(str(created["id"])))
    tenant_id, agent_id = created["id"], created["agent_id"]
    ref = f"fakeagent_cb_{uuid.uuid4().hex[:8]}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agents SET status = 'live', direction = 'outbound', "
                "engine_agent_ref = :r WHERE id = :a"
            ),
            {"r": ref, "a": agent_id},
        )
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('fake', :r, :t, :a, true, now(), now())"
            ),
            {"r": ref, "t": tenant_id, "a": agent_id},
        )
    return tenant_id, agent_id


async def _finished_call(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    status: str = "completed",
    outcome: str | None = "needs_follow_up",
    summary: str | None = "Wanted a quote for a 2BHK but had to hang up.",
    age_days: int = 0,
    parent: uuid.UUID | None = None,
    with_lead: bool = True,
) -> tuple[uuid.UUID, uuid.UUID | None]:
    """One ended call, optionally attached to a lead and to a parent callback."""
    call_id, lead_id = uuid7(), (uuid7() if with_lead else None)
    async with tenant_session(tenant_id) as session:
        if lead_id is not None:
            await session.execute(
                text(
                    "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, "
                    "status, created_at, updated_at) VALUES (:i, :t, :a, :p, 'Priya', "
                    "'inbound_call', 'new', now(), now())"
                ),
                {
                    "i": lead_id,
                    "t": tenant_id,
                    "a": agent_id,
                    "p": f"+9198{uuid.uuid4().int % 100000000:08d}",
                },
            )
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
                "status, outcome_tag, summary, lead_id, callback_of_call_id, created_at, "
                "updated_at) SELECT :i, :t, :a, :e, 'outbound', "
                "  COALESCE((SELECT phone_e164 FROM leads WHERE id = :lid), '+919876500000'), "
                "  :st, :out, :sum, :lid, :parent, now() - CAST(:age AS interval), now()"
            ),
            {
                "i": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": f"exec_{uuid.uuid4().hex[:12]}",
                "st": status,
                "out": outcome,
                "sum": summary,
                "lid": lead_id,
                "parent": parent,
                "age": f"{age_days} days",
            },
        )
    return call_id, lead_id


# ------------------------------------------------------------------ the refusals


async def test_a_resolved_call_is_not_followed_up() -> None:
    """The point of recording an outcome is acting differently on it."""
    tenant_id, agent_id = await _tenant()
    call_id, _ = await _finished_call(tenant_id, agent_id, outcome="resolved")
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as excinfo:
            await service.plan_callback(session, call_id)
    assert excinfo.value.code == "callback_not_needed"


async def test_a_call_still_in_progress_cannot_be_followed_up() -> None:
    tenant_id, agent_id = await _tenant()
    call_id, _ = await _finished_call(tenant_id, agent_id, status="in_progress", outcome=None)
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as excinfo:
            await service.plan_callback(session, call_id)
    assert excinfo.value.code == "callback_call_unfinished"


async def test_a_call_with_no_lead_has_nobody_to_call_back() -> None:
    tenant_id, agent_id = await _tenant()
    call_id, _ = await _finished_call(tenant_id, agent_id, with_lead=False)
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as excinfo:
            await service.plan_callback(session, call_id)
    assert excinfo.value.code == "callback_no_lead"


async def test_a_fortnight_old_call_is_a_cold_call_not_a_follow_up() -> None:
    tenant_id, agent_id = await _tenant()
    call_id, _ = await _finished_call(tenant_id, agent_id, age_days=14)
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as excinfo:
            await service.plan_callback(session, call_id)
    assert excinfo.value.code == "callback_too_old"
    assert "cold call" in (excinfo.value.detail or "")


async def test_the_callback_chain_is_bounded() -> None:
    """The property this feature could most plausibly get wrong: a callback whose own
    outcome is `needs_follow_up` being callable back, forever."""
    tenant_id, agent_id = await _tenant()
    first, _ = await _finished_call(tenant_id, agent_id)
    second, _ = await _finished_call(tenant_id, agent_id, parent=first)
    third, _ = await _finished_call(tenant_id, agent_id, parent=second)

    async with tenant_session(tenant_id) as session:
        assert (await service.plan_callback(session, first)).depth == 0
        assert (await service.plan_callback(session, second)).depth == 1
        with pytest.raises(ProblemError) as excinfo:
            await service.plan_callback(session, third)
    assert excinfo.value.code == "callback_chain_exhausted"
    assert service.MAX_CALLBACK_DEPTH == 2


async def test_an_inbound_only_agent_cannot_place_a_callback() -> None:
    tenant_id, agent_id = await _tenant()
    call_id, _ = await _finished_call(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET direction = 'inbound' WHERE id = :a"), {"a": agent_id}
        )
        with pytest.raises(ProblemError) as excinfo:
            await service.plan_callback(session, call_id)
    assert excinfo.value.code == "callback_agent_inbound_only"


# ------------------------------------------------------------------ the happy path


async def test_a_callback_carries_the_summary_and_never_the_transcript() -> None:
    tenant_id, agent_id = await _tenant()
    call_id, lead_id = await _finished_call(
        tenant_id, agent_id, summary="Asked about the 2BHK price, line dropped."
    )
    async with tenant_session(tenant_id) as session:
        # A transcript exists for this call and must not travel.
        await session.execute(
            text(
                "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, text, "
                "text_redacted, created_at) VALUES (:i, :t, :c, 0, 'caller', "
                "'my aadhaar is 1234', 'my aadhaar is XXXX', now())"
            ),
            {"i": uuid7(), "t": tenant_id, "c": call_id},
        )
        plan = await service.plan_callback(session, call_id)

    assert plan.lead_id == lead_id
    assert plan.agent_id == agent_id
    assert "2BHK price" in plan.context_note, "the agent knows what happened last time"
    assert "aadhaar" not in plan.context_note.lower(), "the transcript stays home"
    assert plan.depth == 0


async def test_a_call_with_no_summary_still_explains_itself() -> None:
    """Extraction can fail or produce nothing; the callback must still be coherent
    rather than opening with the word 'None'."""
    tenant_id, agent_id = await _tenant()
    call_id, _ = await _finished_call(tenant_id, agent_id, summary=None)
    async with tenant_session(tenant_id) as session:
        plan = await service.plan_callback(session, call_id)
    assert "None" not in plan.context_note
    assert "follow-up" in plan.context_note


async def test_the_dispatched_callback_is_linked_to_the_call_it_follows() -> None:
    """Without the link the chain bound is unenforceable, so this is the test that
    keeps the bound honest."""
    from apps.api.agents.service import dispatch_call

    tenant_id, agent_id = await _tenant()
    call_id, lead_id = await _finished_call(tenant_id, agent_id)

    async with tenant_session(tenant_id) as session:
        plan = await service.plan_callback(session, call_id)
        handle = await dispatch_call(
            session,
            tenant_id=tenant_id,
            agent_id=plan.agent_id,
            lead_id=plan.lead_id,
            phone_e164=plan.phone_e164,
            lead_name=plan.lead_name,
            context_note=plan.context_note,
        )
        await service.link_callback(session, handle=handle, parent_call_id=call_id)
        parent = (
            await session.execute(
                text("SELECT callback_of_call_id FROM calls WHERE engine_call_id = :h"),
                {"h": handle},
            )
        ).scalar()
        new_call = (
            await session.execute(
                text("SELECT id FROM calls WHERE engine_call_id = :h"), {"h": handle}
            )
        ).scalar()

    assert parent == call_id
    # The follow-up is itself followable-up ONCE more (depth 1 of 2) — and the call
    # after that is not, which is the bound the link exists to make enforceable.
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE calls SET status = 'completed', outcome_tag = 'needs_follow_up', "
                "summary = 'Still undecided.' WHERE id = :c"
            ),
            {"c": new_call},
        )
        second = await service.plan_callback(session, uuid.UUID(str(new_call)))
        assert second.depth == 1, "one link deep"

        third_id = uuid7()
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
                "status, outcome_tag, summary, lead_id, callback_of_call_id, created_at, "
                "updated_at) VALUES (:i, :t, :a, :e, 'outbound', '+919876500000', 'completed', "
                "'needs_follow_up', 'Still undecided.', :lid, :parent, now(), now())"
            ),
            {
                "i": third_id,
                "t": tenant_id,
                "a": agent_id,
                "e": f"exec_{uuid.uuid4().hex[:12]}",
                "lid": lead_id,
                "parent": new_call,
            },
        )
        with pytest.raises(ProblemError) as excinfo:
            await service.plan_callback(session, third_id)
    assert excinfo.value.code == "callback_chain_exhausted"

    engine = get_engine()
    dispatched = next(iter(engine._calls.values()))  # type: ignore[attr-defined]
    context = dispatched["context"]
    note = context.context_note if hasattr(context, "context_note") else context["context_note"]
    assert "follow-up" in str(note), "the engine really is told this is a follow-up"
