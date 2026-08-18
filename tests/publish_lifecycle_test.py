"""Publishing an agent asks whether the account is still open (D-194).

`publish_agent` is what puts an agent on the phone, and it asked nothing about the
organisation the agent belongs to. Every other key-minting surface already asked —
`admin.service` guards both ends of an invitation with the same predicate — so this was
the loudest of them and the one that did not.

WHY IT MATTERS MORE THAN A TIDINESS FIX. A churned tenant is on a retention clock
(FLOWS §9) and is not taking on new business; an ERASED tenant has a signed certificate
saying its caller data is gone. Republishing either one puts an agent back into service
that answers calls and writes a fresh `calls` row with a raw caller number against it —
which for the erased case makes the certificate false, again, minutes after it was issued.
That is the same shape D-189 found in the erasure path itself, reached from the other end.

`suspended` is NOT refused, and that is asserted here rather than left implied: suspension
stops outbound dialling and nothing else, it is reversible, and an account suspended over
non-payment is exactly when somebody needs the inbound line still answering.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import prompts
from apps.api.agents.service import publish_agent
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from sqlalchemy import text

pytestmark = pytest.mark.asyncio


async def _publishable_tenant() -> tuple[uuid.UUID, uuid.UUID]:
    """A fresh org whose agent can actually be published, so a refusal below is THIS rule."""
    created = await admin_service.create_organization(
        name="Lifecycle Clinic",
        slug=f"lif-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = uuid.UUID(str(created["id"])), uuid.UUID(str(created["agent_id"]))
    async with tenant_session(tenant_id) as session:
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="[IDENTITY]\nYou are the receptionist for Lifecycle Clinic.\n",
            notes=None,
            created_by=None,
        )
    return tenant_id, agent_id


async def _set_lifecycle(tenant_id: uuid.UUID, *, status: str | None, deleted: bool) -> None:
    """Move the org, by the columns `assert_account_open` actually reads.

    Written with SQL rather than through the lifecycle route on purpose: this test is about
    what `publish_agent` refuses, not about how a tenant reaches that state, and driving the
    transition would couple it to a second surface's rules.

    UNDER `tenant_session`, NOT `untenanted_session`, and the difference is not stylistic:
    `organizations`' policy matches on its own `id`, so an untenanted UPDATE matches zero
    rows and reports success. The first draft of this helper did exactly that — the two
    refusal tests then failed with DID NOT RAISE, which read as the fix being absent when
    in fact the fixture had written nothing. A helper that silently does nothing is worse
    than one that throws.
    """
    async with tenant_session(tenant_id) as session:
        if status is not None:
            await session.execute(
                text("UPDATE organizations SET status = :s WHERE id = :t"),
                {"s": status, "t": tenant_id},
            )
        if deleted:
            # `status = 'churned'` IN THE SAME STATEMENT, because the schema says so:
            # `ck_organizations_deleted_implies_churned` refuses a soft-deleted row that is
            # not also churned. Setting `deleted_at` alone raised a CheckViolation — the
            # database refusing a state the product cannot reach, which is the constraint
            # doing its job and this fixture having invented an impossible tenant.
            await session.execute(
                text(
                    "UPDATE organizations SET deleted_at = now(), status = 'churned' WHERE id = :t"
                ),
                {"t": tenant_id},
            )


async def _publish_is_refused(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> ProblemError:
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as exc:
            await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    return exc.value


async def test_a_churned_accounts_agent_cannot_be_put_back_on_the_phone() -> None:
    tenant_id, agent_id = await _publishable_tenant()
    await _set_lifecycle(tenant_id, status="churned", deleted=False)

    problem = await _publish_is_refused(tenant_id, agent_id)

    assert problem.code == "account_closed"
    # And the engine was never reached: the refusal is BEFORE `create_agent`, so there is
    # no agent left at the vendor with nothing in our tree pointing at it.
    async with tenant_session(tenant_id) as session:
        ref = (
            await session.execute(
                text("SELECT engine_agent_ref FROM agents WHERE id = :a"), {"a": agent_id}
            )
        ).scalar()
    assert ref is None


async def test_a_soft_deleted_accounts_agent_cannot_be_put_back_on_the_phone() -> None:
    """The erased case, which is the one that makes a signed certificate false.

    `deleted_at` implies `churned` at the database (see the fixture), so this cannot be a
    state the test above does not already cover — what it adds is the OTHER limb of the
    predicate: `assert_account_open` refuses on `deleted_at IS NOT NULL` independently, so
    a future change that relaxed the status check alone would still be caught here.
    """
    tenant_id, agent_id = await _publishable_tenant()
    await _set_lifecycle(tenant_id, status=None, deleted=True)

    assert (await _publish_is_refused(tenant_id, agent_id)).code == "account_closed"


async def test_a_suspended_account_still_publishes() -> None:
    """The control, and a real product rule rather than a leftover.

    Without it this file would pass just as well against a `publish_agent` that refused
    every non-active account — which would turn a billing stop into an access stop and take
    a paying client's inbound line down over an unpaid invoice.
    """
    tenant_id, agent_id = await _publishable_tenant()
    await _set_lifecycle(tenant_id, status="suspended", deleted=False)

    async with tenant_session(tenant_id) as session:
        ref = await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)

    assert ref, "a suspended account's inbound agent must still publish"


async def test_an_open_account_publishes() -> None:
    """The premise of all three above: nothing here refuses an ordinary publish."""
    tenant_id, agent_id = await _publishable_tenant()

    async with tenant_session(tenant_id) as session:
        assert await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
