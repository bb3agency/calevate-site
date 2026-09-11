"""Moving a client between billing motions brings their phone with it (D-579, 10 Sep 2026).

THE DEFECT. `compliance.service.credits_exhausted` reads THREE facts — the plan tier, is a
trial running, and the wallet balance — and each is a way an account can start or stop being
exhausted. Two of the three publish `apply_inbound_credit_state` so
`agents.service.reconcile_inbound_answering` can tell the ENGINE: the BALANCE on every
crossing of zero in either direction (`billing.service.record_entry`) and the TRIAL on
`billing.trials.start_trial` (D-577). The TIER published nothing.

**AND THE BACKSTOP CANNOT STAND IN FOR IT IN THE DIRECTION THAT MATTERS.**
`workers/pipeline.py` enqueues the cutover only when it finds the tenant EXHAUSTED, which a
`managed` tenant never is — `credits_exhausted` returns False for any tier outside
`PREPAID_TIERS` before it looks at anything else. So a client silenced for an empty wallet
and then moved onto the invoiced retainer — the move whose entire point is that nothing
should stop their phone — stayed on `agents.service.CREDIT_STOP_MESSAGE` INDEFINITELY,
until somebody happened to republish one of their agents. That is the failure nobody
notices: the operator's screen says `changed: true`, the account is on a retainer, and the
callers go on being turned away.

WHAT THESE TESTS PIN, worst first:

1. **The phone actually comes back** when an operator moves a silenced client to `managed`,
   driven through the registered job exactly as the outbox drives it.
2. **A no-op click promises nothing.** `set_plan_tier` is idempotent by `plan_tier <> :tier`
   and returns None; the enqueue must sit behind that, or the outbox stops being a record
   of what happened.
3. **The promise shares the tier write's transaction** (BACKEND-PATTERNS §4), read out of
   `outbox_messages` rather than off a spy.
4. **The four spellings of the job name agree.** `admin/service.py` restates the constant
   because `scripts/check_job_wiring.py` resolves a job name only in the file that enqueues
   it; without this test the outbox would publish a name no worker answers to, and arq
   drops that with a warning nothing reads.
5. **Nothing was bought with a ledger entry.** A tier move is not money (hard rule 4/7).

`tests/inbound_credit_cutover_test.py` and `tests/trial_inbound_recovery_test.py` are the
files this one extends; their helpers are the shape followed here rather than re-invented.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.admin.service import INBOUND_CUTOVER_JOB as ADMIN_INBOUND_CUTOVER_JOB
from apps.api.agents import prompts
from apps.api.agents import service as agents_service
from apps.api.billing.service import INBOUND_CUTOVER_JOB, record_entry
from apps.api.compliance.service import credits_exhausted
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine, reset_engine_cache
from apps.api.engine.fake import FakeEngine
from apps.workers.inbound_cutover import apply_inbound_credit_state
from sqlalchemy import text
from tests.conftest import accept_agreements

pytestmark = pytest.mark.asyncio


async def _tenant(*, tier: str = "prepaid") -> tuple[UUID, UUID]:
    """A tenant on `tier` with a scripted inbound agent and an empty wallet."""
    reset_engine_cache()
    created = await admin_service.create_organization(
        name="Retainer Clinic",
        slug=f"retainer-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = UUID(str(created["id"])), UUID(str(created["agent_id"]))
    await accept_agreements(tenant_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = :t WHERE id = :i"),
            {"t": tier, "i": tenant_id},
        )
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="[IDENTITY]\nYou are the receptionist for Retainer Clinic.\n",
            notes=None,
            created_by=None,
        )
    return tenant_id, agent_id


async def _publish(tenant_id: UUID, agent_id: UUID) -> str:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET direction = 'inbound' WHERE id = :a"), {"a": agent_id}
        )
        return await agents_service.publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)


async def _live_script(ref: str) -> tuple[str, str]:
    """What the ENGINE is holding, read back through the Protocol."""
    engine = get_engine()
    assert isinstance(engine, FakeEngine)
    snapshot = await engine.get_agent(ref)
    return str(snapshot.greeting), str(snapshot.system_prompt)


async def _reconcile(tenant_id: UUID) -> str:
    """The registered job, driven exactly as the outbox drives it."""
    return await apply_inbound_credit_state({"job_try": 1}, {"tenant_id": str(tenant_id)})


async def _outbox_jobs(tenant_id: UUID) -> list[str]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT job FROM outbox_messages "
                    "WHERE payload->>'tenant_id' = :t ORDER BY created_at, id"
                ),
                {"t": str(tenant_id)},
            )
        ).all()
    return [str(row[0]) for row in rows]


async def _tier(tenant_id: UUID) -> str:
    async with tenant_session(tenant_id) as session:
        return str(
            (
                await session.execute(
                    text("SELECT plan_tier FROM organizations WHERE id = :i"), {"i": tenant_id}
                )
            ).scalar()
        )


async def _ledger_rows(tenant_id: UUID) -> int:
    async with tenant_session(tenant_id) as session:
        return int(
            (
                await session.execute(
                    text("SELECT count(*) FROM credit_ledger WHERE tenant_id = :t"),
                    {"t": tenant_id},
                )
            ).scalar()
            or 0
        )


async def _silence(tenant_id: UUID, agent_id: UUID) -> tuple[str, str, str]:
    """Fund, publish, drain: the account an operator is about to rescue.

    Returns the engine ref and the agent's OWN script, so the restore can be asserted as
    equality against the words this agent actually has rather than merely "not the stop
    message".
    """
    async with tenant_session(tenant_id) as session:
        await record_entry(session, tenant_id=tenant_id, delta=Decimal("500"), reason="topup")
    ref = await _publish(tenant_id, agent_id)
    own_greeting, own_prompt = await _live_script(ref)
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("-500"),
            reason="usage",
            allow_negative=True,
        )
    await _reconcile(tenant_id)
    assert agents_service.CREDIT_STOP_MESSAGE in (await _live_script(ref))[0], (
        "the control failed: this client was never silenced, so the rescue below proves nothing"
    )
    return ref, own_greeting, own_prompt


# ============================================================================
# 1. The rescue
# ============================================================================


async def test_moving_a_silenced_client_to_managed_brings_the_phone_back() -> None:
    """THE TEST THIS FILE EXISTS FOR.

    `managed` means invoiced against a retainer: there is no wallet, the credits screen
    says so, and nothing is supposed to stop this client's phone. Before D-579 the column
    moved and the ENGINE was never told, and the post-call backstop could not tell it
    either — it only fires for a tenant it finds EXHAUSTED, which this tenant no longer is.
    """
    tenant_id, agent_id = await _tenant()
    ref, own_greeting, own_prompt = await _silence(tenant_id, agent_id)

    # Counted as a DELTA, never as a membership test: the two ledger movements in `_silence`
    # have already published this same job name, so `in` would pass against the crossing
    # that silenced them.
    before = await _outbox_jobs(tenant_id)
    async with tenant_session(tenant_id) as session:
        previous = await admin_service.set_plan_tier(
            session, tenant_id=tenant_id, plan_tier="managed"
        )
    assert previous == "prepaid"

    assert await _outbox_jobs(tenant_id) == [*before, ADMIN_INBOUND_CUTOVER_JOB], (
        "moving a client onto the invoiced retainer promised nobody that the phone should "
        "come back, so a client nothing should stop stays on the credit-stop script"
    )
    assert await _reconcile(tenant_id) == "silenced=0 restored=1 unchanged=0"
    assert await _live_script(ref) == (own_greeting, own_prompt), (
        "the agent came back saying something other than its own words"
    )


async def test_the_predicate_the_job_re_reads_is_the_one_the_tier_moved() -> None:
    """The job takes no verdict from its payload — it re-asks `credits_exhausted`, the same
    predicate the dial gate, the launch gate and the client's own credits screen ask. This
    pins that the TIER is what makes that one predicate answer False, so the enqueue is
    aimed at a question that actually changed."""
    tenant_id, _ = await _tenant()
    async with tenant_session(tenant_id) as session:
        assert await credits_exhausted(session, tenant_id=tenant_id)
        await admin_service.set_plan_tier(session, tenant_id=tenant_id, plan_tier="managed")
        assert not await credits_exhausted(session, tenant_id=tenant_id)


async def test_moving_onto_prepaid_at_zero_silences_without_waiting_for_a_call() -> None:
    """The other direction, which HAD a mechanism and now has a publisher.

    `workers/pipeline.py`'s backstop catches this one — but only after an inbound call has
    already been answered by an agent that should have been silent. Publishing here closes
    the same edge at the moment the operator makes the decision, and the backstop stays
    exactly where it is (`enqueue_outbox_once`, keyed per call) as the belt to this braces.
    """
    tenant_id, agent_id = await _tenant(tier="managed")
    ref = await _publish(tenant_id, agent_id)
    assert agents_service.CREDIT_STOP_MESSAGE not in (await _live_script(ref))[0]

    before = await _outbox_jobs(tenant_id)
    async with tenant_session(tenant_id) as session:
        assert (
            await admin_service.set_plan_tier(session, tenant_id=tenant_id, plan_tier="prepaid")
            == "managed"
        )
    assert await _outbox_jobs(tenant_id) == [*before, ADMIN_INBOUND_CUTOVER_JOB]
    assert await _reconcile(tenant_id) == "silenced=1 restored=0 unchanged=0"
    assert agents_service.CREDIT_STOP_MESSAGE in (await _live_script(ref))[0]


# ============================================================================
# 2. The mechanism
# ============================================================================


async def test_a_no_op_click_promises_nothing() -> None:
    """`set_plan_tier` is idempotent by `plan_tier <> :tier` and returns None when the
    account was already on the tier — which the route reports as `changed: false` and for
    which it writes no audit row. The enqueue sits behind the same test: a promise about a
    state nobody moved would be cheap to honour and would still cost the outbox the one
    property it has, that a row in it means something happened."""
    tenant_id, _ = await _tenant(tier="prepaid")
    before = await _outbox_jobs(tenant_id)
    async with tenant_session(tenant_id) as session:
        assert (
            await admin_service.set_plan_tier(session, tenant_id=tenant_id, plan_tier="prepaid")
            is None
        )
    assert await _outbox_jobs(tenant_id) == before, (
        "setting the tier an account is already on published a cutover job about a change "
        "that did not happen"
    )


async def test_the_promise_shares_the_tier_writes_transaction() -> None:
    """BACKEND-PATTERNS §4. A rolled-back tier write must leave no job promising to
    re-decide a phone whose account did not move — read out of `outbox_messages`, because
    only the row proves the transaction was shared."""
    tenant_id, _ = await _tenant()
    boom = RuntimeError("the operator's audit row failed after the column moved")
    with pytest.raises(RuntimeError):
        async with tenant_session(tenant_id) as session:
            await admin_service.set_plan_tier(session, tenant_id=tenant_id, plan_tier="managed")
            raise boom
    assert await _tier(tenant_id) == "prepaid", "the control failed: the tier write survived"
    assert await _outbox_jobs(tenant_id) == [], (
        "a rolled-back tier move still promised to re-decide this client's phone"
    )


async def test_the_admin_service_and_the_ledger_name_the_same_job() -> None:
    """`admin/service.py` restates the job name as a literal because
    `scripts/check_job_wiring.py` resolves a name only in the file that enqueues it, and
    because importing it from `billing.service` would drag billing into the onboarding
    wizard's import graph for one string. This holds the spellings in step —
    `tests/inbound_credit_cutover_test.py` does it for the pipeline's copy and
    `tests/trial_inbound_recovery_test.py` for the trials copy."""
    assert ADMIN_INBOUND_CUTOVER_JOB == INBOUND_CUTOVER_JOB


# ============================================================================
# 3. What the edge did NOT buy
# ============================================================================


async def test_the_edge_did_not_turn_a_tier_move_into_a_ledger_entry() -> None:
    """A plan tier is not money. The recovery is published as an OUTBOX promise, which is
    neither a credit nor append-only evidence — hard rules 4 and 7 both say a tier move
    may not touch `credit_ledger`, in either direction."""
    tenant_id, _ = await _tenant()
    async with tenant_session(tenant_id) as session:
        await admin_service.set_plan_tier(session, tenant_id=tenant_id, plan_tier="managed")
    async with tenant_session(tenant_id) as session:
        await admin_service.set_plan_tier(session, tenant_id=tenant_id, plan_tier="prepaid")
    assert await _ledger_rows(tenant_id) == 0
