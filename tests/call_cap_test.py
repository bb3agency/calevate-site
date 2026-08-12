"""The cost-runaway guard (SURFACES §2b:107) — a per-agent max call length.

    "a per-agent max call length (their default 10 min, adjustable). We have no
     equivalent today and should."

WHERE IT IS ENFORCED, and why the tests are shaped the way they are
-------------------------------------------------------------------
The honest answer is **the engine's agent config at publish time**, with OUR side
owning the value and refusing to record one it has not delivered. The reasoning, each
half of which has a test below:

- **Only the engine can hang up.** We are not in the audio path — hard rule 3 keeps
  `voice-runtime` to acking a webhook — so no code of ours can end a call in progress.
  A dispatch-side "enforcement" would be a number in a variable while the robot keeps
  talking to a voicemail greeting.
- **Dispatch-only protects nothing that matters most.** A runaway INBOUND call is
  never dispatched by us at all; it arrives. Enforcing at `dispatch_call` would leave
  the receptionist agent — the product's default motion — completely unguarded.
- **Vendor-side-only would let our row lie.** So the setter publishes in the SAME
  transaction for a live agent: if the engine push fails, the column write rolls back
  with it and we never claim a cap the engine does not hold.

What we cannot promise, stated rather than papered over: if the vendor silently
ignores its own field, this guard degrades from prevention to detection — the breach
is visible in `calls.duration_s` against the agent's cap, and a detector belongs in
the post-call pipeline (`apps/workers`), which this wave does not own.

NULL IS NOT UNLIMITED
---------------------
NULL means "the platform default" (600s = §2b's ten minutes). Zero and negative are
refused by the CHECK, and so is anything under a minute or over an hour. There is no
value of the column, and no absence of one, that publishes an uncapped agent — which
is the property `test_no_agent_can_be_published_without_a_cap` exists to pin.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import prompts, publishing
from apps.api.agents.models import CALL_CAP_DEFAULT_S, CALL_CAP_MAX_S, CALL_CAP_MIN_S
from apps.api.agents.service import effective_call_cap, publish_agent
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine, reset_engine_cache
from apps.api.engine.fake import FakeEngine
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

SCRIPT = "The receptionist script this clinic approved before anyone touched the cap."


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name="Runaway Clinic",
        slug=f"cap-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return created["id"], created["agent_id"]


async def _plan(tenant_id: uuid.UUID, overage_rate: Decimal | None) -> None:
    """The tenant's plan row. `overage_rate` is what a runaway minute costs THEM, so
    it is the only honest input to a worst-case quote."""
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO plans (id, tenant_id, overage_rate, concurrency_ceiling, "
                "created_at, updated_at) VALUES (:i, :t, :rate, 10, now(), now())"
            ),
            {"i": uuid7(), "t": tenant_id, "rate": overage_rate},
        )


async def _live(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> tuple[str, FakeEngine]:
    reset_engine_cache()
    async with tenant_session(tenant_id) as session:
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body=SCRIPT,
            notes=None,
            created_by=None,
        )
    ref = f"fakeagent_cap_{uuid.uuid4().hex[:8]}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = :r, status = 'live' WHERE id = :a"),
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
    engine = get_engine()
    assert isinstance(engine, FakeEngine)
    return ref, engine


# --- the sentinel ------------------------------------------------------------


def test_null_resolves_to_the_platform_default_and_never_to_unlimited() -> None:
    assert effective_call_cap(None) == CALL_CAP_DEFAULT_S == 600, "§2b's ten minutes"
    assert effective_call_cap(300) == 300


async def test_no_agent_can_be_published_without_a_cap() -> None:
    """The property that makes the guard a guard: whatever the column says — a value,
    or nothing at all — the config that reaches the engine carries a ceiling."""
    reset_engine_cache()
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body=SCRIPT,
            notes=None,
            created_by=None,
        )
        ref = await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)

    engine = get_engine()
    assert isinstance(engine, FakeEngine)
    assert engine._agents[ref].max_call_duration_s == CALL_CAP_DEFAULT_S


# --- the range ---------------------------------------------------------------


@pytest.mark.parametrize("value", [0, -1, CALL_CAP_MIN_S - 1, CALL_CAP_MAX_S + 1])
async def test_the_database_refuses_a_cap_outside_the_range(value: int) -> None:
    """Zero and negative are not "unlimited"; they are an agent that hangs up on
    everyone. The CHECK is the floor under every writer, including one that skips the
    service layer."""
    tenant_id, agent_id = await _tenant()
    with pytest.raises(IntegrityError):
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE agents SET max_call_duration_s = :v WHERE id = :a"),
                {"v": value, "a": agent_id},
            )


@pytest.mark.parametrize("value", [0, -1, 30, 7200])
async def test_the_service_refuses_the_same_values_with_a_usable_error(value: int) -> None:
    """RFC-9457, machine code in the last segment of `type`, no `code` key. The DB
    would refuse it anyway; a 500 from an IntegrityError is not an answer a client can
    act on."""
    tenant_id, agent_id = await _tenant()
    with pytest.raises(ProblemError) as exc:
        await publishing.set_call_cap(
            tenant_id=tenant_id, agent_id=agent_id, max_call_duration_s=value
        )
    assert exc.value.code == "call_cap_out_of_range"
    problem = exc.value.as_problem()
    assert problem["type"].endswith("/call_cap_out_of_range")
    assert "code" not in problem


# --- the fast lane -----------------------------------------------------------


async def test_setting_a_cap_on_a_live_agent_reaches_the_engine_immediately() -> None:
    """A cap changes conduct, not content, so §2b puts it on the side that applies
    immediately. "Immediately" means the engine, not our table."""
    tenant_id, agent_id = await _tenant()
    ref, engine = await _live(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    assert engine._agents[ref].max_call_duration_s == CALL_CAP_DEFAULT_S

    result = await publishing.set_call_cap(
        tenant_id=tenant_id, agent_id=agent_id, max_call_duration_s=300
    )

    assert result.engine_synced is True
    assert engine._agents[ref].max_call_duration_s == 300


async def test_clearing_the_cap_returns_the_agent_to_the_platform_default() -> None:
    tenant_id, agent_id = await _tenant()
    ref, engine = await _live(tenant_id, agent_id)
    await publishing.set_call_cap(tenant_id=tenant_id, agent_id=agent_id, max_call_duration_s=300)

    result = await publishing.set_call_cap(
        tenant_id=tenant_id, agent_id=agent_id, max_call_duration_s=None
    )

    assert result.effective_call_cap_s == CALL_CAP_DEFAULT_S
    assert result.is_platform_default is True
    assert engine._agents[ref].max_call_duration_s == CALL_CAP_DEFAULT_S


async def test_a_cap_change_does_not_drag_a_staged_script_onto_a_live_agent() -> None:
    """The fast lane is only safe because `publish_agent` reads the APPLIED pointer.
    Without that, "apply the cap now" would also apply an unapproved script."""
    tenant_id, agent_id = await _tenant()
    ref, engine = await _live(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="A draft nobody has approved, staged behind the Apply button.",
            notes=None,
            created_by=None,
        )

    await publishing.set_call_cap(tenant_id=tenant_id, agent_id=agent_id, max_call_duration_s=120)

    assert engine._agents[ref].max_call_duration_s == 120
    assert engine._agents[ref].system_prompt == SCRIPT, "the cap change leaked the draft script"


async def test_setting_a_cap_on_a_draft_agent_touches_no_engine() -> None:
    reset_engine_cache()
    tenant_id, agent_id = await _tenant()
    result = await publishing.set_call_cap(
        tenant_id=tenant_id, agent_id=agent_id, max_call_duration_s=900
    )
    assert result.engine_synced is False
    assert result.effective_call_cap_s == 900


# --- what it costs them ------------------------------------------------------


async def test_the_cap_is_quoted_as_the_worst_case_cost_of_one_call() -> None:
    """ "What does this cost me" is the question a cap is really asking, so the API
    answers it: billed minutes are whole (`plans.overage_rate` is per minute), so the
    worst case is ceil(cap / 60) x rate, in NUMERIC INR (hard rule 7)."""
    tenant_id, agent_id = await _tenant()
    await _plan(tenant_id, Decimal("8.50"))

    await publishing.set_call_cap(tenant_id=tenant_id, agent_id=agent_id, max_call_duration_s=330)
    state = await publishing.pending_state_for(tenant_id=tenant_id, agent_id=agent_id)

    assert state.effective_call_cap_s == 330
    # 330s bills as 6 whole minutes, never 5.5.
    assert state.worst_case_call_cost_inr == Decimal("51.00")
    assert not isinstance(state.worst_case_call_cost_inr, float)


async def test_a_tenant_with_no_plan_rate_is_quoted_nothing_rather_than_zero() -> None:
    """A missing rate is "we cannot tell you", not "it is free". Quoting ₹0.00 for a
    ten-minute call is the one wrong answer here."""
    tenant_id, agent_id = await _tenant()
    await _plan(tenant_id, None)
    state = await publishing.pending_state_for(tenant_id=tenant_id, agent_id=agent_id)
    assert state.worst_case_call_cost_inr is None


# --- tenancy -----------------------------------------------------------------


async def test_another_tenant_cannot_set_our_cap() -> None:
    tenant_id, agent_id = await _tenant()
    other_id, _ = await _tenant()
    with pytest.raises(ProblemError) as exc:
        await publishing.set_call_cap(
            tenant_id=other_id, agent_id=agent_id, max_call_duration_s=120
        )
    assert exc.value.kind == "not_found"

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT max_call_duration_s FROM agents WHERE id = :a"), {"a": agent_id}
            )
        ).first()
    assert row is not None and row[0] is None, "our cap was written from another tenant's scope"


# --- the seam between the two caps ----------------------------------------------------
#
# Two caps landed in the same wave from different slices, and they are NOT two answers to
# one question: this one bounds a SINGLE call's length, `plans.client_cap_*` bounds a
# MONTH's spend. Where they meet is the worst-case quote, which multiplies this cap by a
# rate — and the billing slice made "the rate" ambiguous by adding a second one.


async def _plan_rates(tenant_id: uuid.UUID, *, premium: str | None, value: str | None) -> None:
    """A plan quoting BOTH rungs (D-36). `_plan` above predates the value column."""
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO plans (id, tenant_id, overage_rate, overage_rate_value, "
                "concurrency_ceiling, created_at, updated_at) "
                "VALUES (:i, :t, :p, :v, 10, now(), now())"
            ),
            {
                "i": uuid7(),
                "t": tenant_id,
                "p": Decimal(premium) if premium is not None else None,
                "v": Decimal(value) if value is not None else None,
            },
        )


async def test_the_worst_case_quote_uses_the_dearer_of_the_two_rates() -> None:
    """A ceiling computed from the cheaper rung promises a number the next call exceeds.

    Which rung a call bills at is decided by the voice that actually ran, which is not
    knowable when the quote is rendered — so the only honest ceiling is the dearer rate.
    """
    tenant_id, agent_id = await _tenant()
    await _plan_rates(tenant_id, premium="8.00", value="4.00")

    await publishing.set_call_cap(tenant_id=tenant_id, agent_id=agent_id, max_call_duration_s=600)
    state = await publishing.pending_state_for(tenant_id=tenant_id, agent_id=agent_id)

    assert state.worst_case_call_cost_inr == Decimal("80.00"), (
        "quoted the value rung; ten minutes on the premium voice costs the client 80"
    )


async def test_the_dearer_rate_is_taken_by_price_not_by_column_name() -> None:
    """Guards the convention, not today's data. `billing.service.split_overage` spends
    the included allowance on the dearer rung BY PRICE for the same reason: the columns
    are named for the rungs they price today, and a plan that ever quoted them the other
    way round would invert every guarantee that read the label instead of the number."""
    tenant_id, agent_id = await _tenant()
    await _plan_rates(tenant_id, premium="4.00", value="9.00")

    await publishing.set_call_cap(tenant_id=tenant_id, agent_id=agent_id, max_call_duration_s=60)
    state = await publishing.pending_state_for(tenant_id=tenant_id, agent_id=agent_id)

    assert state.worst_case_call_cost_inr == Decimal("9.00")


async def test_a_plan_quoting_only_one_rate_still_answers() -> None:
    """GREATEST ignores NULLs, so a plan with no value rate — every plan today — quotes
    its single rate rather than going silent."""
    tenant_id, agent_id = await _tenant()
    await _plan_rates(tenant_id, premium="6.50", value=None)

    await publishing.set_call_cap(tenant_id=tenant_id, agent_id=agent_id, max_call_duration_s=120)
    state = await publishing.pending_state_for(tenant_id=tenant_id, agent_id=agent_id)

    assert state.worst_case_call_cost_inr == Decimal("13.00")
