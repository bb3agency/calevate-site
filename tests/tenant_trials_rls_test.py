"""Cross-tenant zero rows on `tenant_trials` (hard rule 1, migration a71f3c9e5d84).

The table carries `tenant_id` and the FORCEd `tenant_isolation` policy. What a leak here
would expose is not a caller's data but one business's COMMERCIAL ARRANGEMENT with us —
that they were carried free for thirty days, when it ends, and the date their personal data
becomes erasable. A competitor reading that off another tenant's dashboard is a different
kind of incident from a transcript leak and an equally real one.

The untenanted case is the one that has to hold hardest: the nightly sweep
(`apps/workers/trials.py`) enumerates organisations through `admin_session`, which widens
`USING` on `organizations` ONLY — so if this table were ever readable without the GUC, that
job would silently become a fleet-wide reader of every client's terms.

SHARED DATABASE DISCIPLINE: two organisations minted by this module, every assertion scoped
to their own ids, and nothing counts rows globally.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing.trials import read_trial, start_trial
from apps.api.db.session import tenant_session, untenanted_session
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from tests.conftest import accept_agreements

pytestmark = pytest.mark.asyncio


async def _org_with_trial() -> uuid.UUID:
    created = await admin_service.create_organization(
        name="Trial RLS",
        slug=f"trial-rls-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    await accept_agreements(tenant_id)
    async with tenant_session(tenant_id) as session:
        await start_trial(session, tenant_id=tenant_id, days=30, actor_user_id=None)
    return tenant_id


async def test_a_tenant_sees_only_its_own_trial() -> None:
    """Both rows exist — that is what makes "zero" below a refusal rather than an empty
    table."""
    first = await _org_with_trial()
    second = await _org_with_trial()

    async with tenant_session(first) as session:
        mine = (await session.execute(text("SELECT count(*) FROM tenant_trials"))).scalar()
        theirs = (
            await session.execute(
                text("SELECT count(*) FROM tenant_trials WHERE tenant_id = :t"), {"t": second}
            )
        ).scalar()
    assert mine == 1
    assert theirs == 0


async def test_the_service_reader_cannot_answer_for_another_tenant() -> None:
    """RLS is the mechanism, but the READER is what every surface actually calls — and it
    names `tenant_id` in its predicate as well, so a session handed the wrong scope answers
    None instead of quietly answering about somebody else."""
    first = await _org_with_trial()
    second = await _org_with_trial()
    async with tenant_session(first) as session:
        assert await read_trial(session, tenant_id=first) is not None
        assert await read_trial(session, tenant_id=second) is None


async def test_an_untenanted_session_sees_no_trials_at_all() -> None:
    """FORCE ROW LEVEL SECURITY with no `app.tenant_id` set is zero rows, never all rows.
    The nightly sweep enumerates organisations through `admin_session` and then opens a
    `tenant_session` per client precisely because this is true."""
    await _org_with_trial()
    async with untenanted_session() as session:
        count = (await session.execute(text("SELECT count(*) FROM tenant_trials"))).scalar()
    assert count == 0


async def test_a_tenant_cannot_write_a_trial_onto_another_tenant() -> None:
    """The policy's WITH CHECK half. A read-only leak is bad; a client granting THEMSELVES
    a trial on somebody else's account would be worse, and the standard
    `tenant_id = GUC` policy refuses the insert rather than accepting it silently."""
    first = await _org_with_trial()
    second = await _org_with_trial()
    with pytest.raises(DBAPIError):
        async with tenant_session(first) as session:
            await session.execute(
                text(
                    "INSERT INTO tenant_trials "
                    "(id, tenant_id, days, started_at, ends_at, status) "
                    "VALUES (gen_random_uuid(), :t, 7, now(), now() + interval '7 days', "
                    "'active')"
                ),
                {"t": second},
            )
