"""Opening a trial brings a silenced client's phone back (D-577, 10 Sep 2026).

THE DEFECT. `compliance.service.credits_exhausted` reads THREE facts — is this account on
a wallet motion, is it inside a funded trial, and is the wallet at or below zero — and
until this change only the third had a publisher. `billing.service.record_entry` enqueues
`apply_inbound_credit_state` on every crossing of zero in either direction, which covers
every movement of money; a trial moves NO money by explicit decision (D-536: the founder
refused "grant them credit and let the ordinary gate honour it", because the ledger would
then assert they were given money nobody gave them). So opening a trial flipped the
predicate to False and told nobody, and a client already silenced for an empty wallet went
on greeting their callers with `agents.service.CREDIT_STOP_MESSAGE` — for as long as it
took somebody to happen to republish one of their agents.

**THAT IS THE RESCUE HALF OF THE EDGE.** An operator opens a trial for an account at zero
precisely BECAUSE the line is down: it is the cheapest answer to "a brand-new client has no
credit and their phone stopped after one call". An edge that fires on the way down and not
on the way up leaves the product able to silence a client and unable to un-silence them.

WHAT THESE TESTS PIN, worst first:

1. **The phone actually comes back** — the end-to-end rescue, driven through the registered
   job exactly as the outbox drives it. Everything else here is a mechanism test for this.
2. **The promise shares the trial row's transaction** (BACKEND-PATTERNS §4), read out of
   `outbox_messages` rather than off a spy: a rolled-back trial must not leave a job
   promising to un-silence a client who is not on a trial.
3. **The two spellings of the job name agree.** `billing/trials.py` restates the constant
   because `billing/service.py` imports FROM it (importing back is a cycle) and because
   `scripts/check_job_wiring.py` resolves a job name only in the file that enqueues it.
   Without this test the outbox would publish a name no worker answers to, and arq drops
   that with a warning nothing reads.
4. **A trial is still not a ledger credit.** The edge must not have been bought by
   quietly making a trial move money — hard rule 7 and D-536 both forbid it.

`tests/inbound_credit_cutover_test.py` is the file this one extends; its helpers are the
shape followed here rather than re-invented.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import prompts
from apps.api.agents import service as agents_service
from apps.api.billing.service import INBOUND_CUTOVER_JOB, record_entry
from apps.api.billing.trials import (
    INBOUND_CUTOVER_JOB as TRIALS_INBOUND_CUTOVER_JOB,
)
from apps.api.billing.trials import (
    end_trial,
    start_trial,
)
from apps.api.compliance.service import credits_exhausted
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine, reset_engine_cache
from apps.api.engine.fake import FakeEngine
from apps.workers.inbound_cutover import apply_inbound_credit_state
from sqlalchemy import text
from tests.conftest import accept_agreements

pytestmark = pytest.mark.asyncio


async def _tenant(*, tier: str = "prepaid") -> tuple[UUID, UUID]:
    """A prepaid tenant with a scripted inbound agent and an empty wallet."""
    reset_engine_cache()
    created = await admin_service.create_organization(
        name="Rescue Clinic",
        slug=f"rescue-{uuid.uuid4().hex[:8]}",
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
            body="[IDENTITY]\nYou are the receptionist for Rescue Clinic.\n",
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


# ============================================================================
# 1. The rescue
# ============================================================================


async def test_opening_a_trial_brings_a_silenced_client_back() -> None:
    """THE TEST THIS FILE EXISTS FOR.

    The operator's whole reason for opening the trial is that the phone has stopped. Before
    D-577 the trial changed the gate's answer and the ENGINE was never told, so the client
    went on turning callers away with an apology while every screen said they were on us.
    """
    tenant_id, agent_id = await _tenant()
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

    # Counted as a DELTA, never as a membership test: the two ledger movements above have
    # already published this same job name twice (down, then nothing back up), so `in`
    # would have passed against the crossing that silenced them.
    before = await _outbox_jobs(tenant_id)
    async with tenant_session(tenant_id) as session:
        await start_trial(session, tenant_id=tenant_id, days=14, actor_user_id=None)

    assert await _outbox_jobs(tenant_id) == [*before, TRIALS_INBOUND_CUTOVER_JOB], (
        "opening a trial promised nobody that the phone should come back, so a rescued "
        "client stays on the credit-stop script until somebody republishes an agent"
    )
    assert await _reconcile(tenant_id) == "silenced=0 restored=1 unchanged=0"
    assert await _live_script(ref) == (own_greeting, own_prompt), (
        "the agent came back saying something other than its own words"
    )


async def test_the_predicate_the_job_re_reads_is_the_one_the_trial_moved() -> None:
    """The job takes no verdict from its payload — it re-asks `credits_exhausted`, which
    is the same predicate the dial gate, the launch gate and the client's own credits
    screen ask. This pins that a trial is what makes that one predicate answer False, so
    the enqueue above is aimed at a question that actually changed."""
    tenant_id, _ = await _tenant()
    async with tenant_session(tenant_id) as session:
        assert await credits_exhausted(session, tenant_id=tenant_id)
        await start_trial(session, tenant_id=tenant_id, days=7, actor_user_id=None)
        assert not await credits_exhausted(session, tenant_id=tenant_id)


# ============================================================================
# 2. The mechanism
# ============================================================================


async def test_the_promise_shares_the_trial_rows_transaction() -> None:
    """BACKEND-PATTERNS §4. A rolled-back trial must leave no job promising to un-silence
    a client who is not on one — read out of `outbox_messages`, because only the row
    proves the transaction was shared."""
    tenant_id, _ = await _tenant()
    async with tenant_session(tenant_id) as session:
        await start_trial(session, tenant_id=tenant_id, days=7, actor_user_id=None)
    assert await _outbox_jobs(tenant_id) == [TRIALS_INBOUND_CUTOVER_JOB]

    # A second open trial is refused BY NAME (409), and the refusal must take the promise
    # with it: the tenant's state did not change, so nothing may claim it did.
    with pytest.raises(ProblemError):
        async with tenant_session(tenant_id) as session:
            await start_trial(session, tenant_id=tenant_id, days=7, actor_user_id=None)
    assert await _outbox_jobs(tenant_id) == [TRIALS_INBOUND_CUTOVER_JOB], (
        "a refused trial still promised to re-decide this client's phone"
    )


async def test_the_trial_module_and_the_ledger_name_the_same_job() -> None:
    """`billing/trials.py` restates the job name as a literal because `billing/service.py`
    imports `read_trial` and `counter_epoch` FROM it — importing back would be a cycle —
    and because `check_job_wiring` resolves a name only in the file that enqueues it. This
    is the test that holds the two spellings in step; without it the enqueue would publish
    a name no worker answers to, which arq drops with a warning nothing reads."""
    assert TRIALS_INBOUND_CUTOVER_JOB == INBOUND_CUTOVER_JOB


async def test_a_trial_ending_still_leaves_the_downward_edge_to_the_backstop() -> None:
    """The direction that was ALREADY covered, pinned so nobody adds a second publisher.

    A trial ending over an empty wallet is caught by `workers/pipeline.py`'s backstop —
    one enqueue at most once per call, whenever a call is metered for a tenant found
    exhausted — and that is the mechanism `workers/inbound_cutover.py` documents by name.
    Publishing here as well would be two publishers for one edge.
    """
    tenant_id, _ = await _tenant()
    async with tenant_session(tenant_id) as session:
        await start_trial(session, tenant_id=tenant_id, days=7, actor_user_id=None)
    before = await _outbox_jobs(tenant_id)
    async with tenant_session(tenant_id) as session:
        await end_trial(session, tenant_id=tenant_id, outcome="stopped", reason="They did not buy.")
    assert await _outbox_jobs(tenant_id) == before, (
        "ending a trial published a second cutover job; the downward edge belongs to the "
        "post-call backstop and having two publishers for it is the duplication D-577 "
        "deliberately did not create"
    )


# ============================================================================
# 3. What the edge did NOT buy
# ============================================================================


async def test_the_edge_did_not_turn_a_trial_into_a_ledger_credit() -> None:
    """D-536's refusal is not weakened by D-577: a trial writes NOTHING to `credit_ledger`
    and the wallet stays exactly where it was. The recovery is published as an OUTBOX
    promise, which is not money and is not append-only evidence."""
    tenant_id, _ = await _tenant()
    async with tenant_session(tenant_id) as session:
        await start_trial(session, tenant_id=tenant_id, days=14, actor_user_id=None)
    assert await _ledger_rows(tenant_id) == 0


async def test_a_managed_client_on_a_trial_costs_one_harmless_job() -> None:
    """The enqueue asks no question here, deliberately — the worker re-reads the predicate
    and `credits_exhausted` is False for a managed client anyway. So a trial for an
    invoiced client publishes a job that finds nothing to do, which is the cheap direction
    of that trade and is asserted rather than left to be discovered."""
    tenant_id, agent_id = await _tenant(tier="managed")
    ref = await _publish(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await start_trial(
            session, tenant_id=tenant_id, days=14, actor_user_id=None, at=datetime.now(UTC)
        )
    assert await _reconcile(tenant_id) == "silenced=0 restored=0 unchanged=1"
    assert agents_service.CREDIT_STOP_MESSAGE not in (await _live_script(ref))[0]
