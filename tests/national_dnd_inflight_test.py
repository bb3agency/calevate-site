"""A contact the national preference scrub blocks while its call is ringing stays blocked.

`record_scrub_run` marks the provider's blocked numbers on the campaign's list, and marked
only `pending` rows. A contact whose call was in flight at that moment was `dialing`, so
it kept its status; when the call went unanswered the retry ladder returned it to
`pending`, and the next tick dialled a number the scrub it was running under had just
said not to. The campaign-level gate cannot see it: the scrub is current and the contact
predates it.
"""

from __future__ import annotations

import pytest
from apps.api.compliance.preference_scrub import national_dnd_blocker
from apps.api.db.session import tenant_session
from apps.workers import campaign_dispatch
from sqlalchemy import text
from tests.campaign_dispatch_audit_test import (  # noqa: F401 - autouse fixtures
    _daytime,
    _launched,
    _roomy_platform_pool,
    _settle_what_this_module_started,
    _tick_one_campaign,
)
from tests.national_dnd_test import record_test_scrub

pytestmark = pytest.mark.asyncio


async def test_a_number_the_scrub_blocks_mid_call_is_not_redialled() -> None:
    tenant_id, _, campaign_id, _, _ = await _launched(phones=("9876680001",))
    await _tick_one_campaign(tenant_id, campaign_id)

    async with tenant_session(tenant_id) as session:
        recorded = await record_test_scrub(session, campaign_id, blocked_numbers=["+919876680001"])
        call_id = (
            await session.execute(
                text("SELECT last_call_id FROM campaign_contacts WHERE campaign_id = :c"),
                {"c": campaign_id},
            )
        ).scalar_one()
    assert recorded.suppressed == 1, "the in-flight contact is on the provider's list"

    async with tenant_session(tenant_id) as session:
        await campaign_dispatch.resolve_campaign_contact(
            session, tenant_id=tenant_id, call_id=call_id, call_status="no_answer"
        )
        await session.execute(
            text("UPDATE campaign_contacts SET next_attempt_at = now() WHERE campaign_id = :c"),
            {"c": campaign_id},
        )
    await _tick_one_campaign(tenant_id, campaign_id)

    async with tenant_session(tenant_id) as session:
        status = (
            await session.execute(
                text("SELECT status FROM campaign_contacts WHERE campaign_id = :c"),
                {"c": campaign_id},
            )
        ).scalar_one()
        dials = (
            await session.execute(
                text("SELECT count(*) FROM calls WHERE campaign_id = :c"), {"c": campaign_id}
            )
        ).scalar_one()
    assert status == "dnc_blocked"
    assert dials == 1, "a preference-blocked number was dialled again after the scrub"


async def test_a_scrub_recorded_mid_batch_covers_the_calls_still_ringing() -> None:
    """The other half of the same miscount. `submitted_count` counted only `pending`, so a
    scrub recorded while the batch was out counted none of the contacts being rung; when
    those calls went unanswered and returned to `pending`, the live count exceeded the
    submitted one and the gate refused the whole campaign as carrying numbers the
    provider never scored, although the provider had scored every one of them."""
    tenant_id, _, campaign_id, _, _ = await _launched(phones=("9876690001", "9876690002"))
    await _tick_one_campaign(tenant_id, campaign_id)

    async with tenant_session(tenant_id) as session:
        recorded = await record_test_scrub(session, campaign_id)
        call_ids = (
            (
                await session.execute(
                    text("SELECT last_call_id FROM campaign_contacts WHERE campaign_id = :c"),
                    {"c": campaign_id},
                )
            )
            .scalars()
            .all()
        )
    assert recorded.submitted == 2, "both contacts were on the list the provider scored"

    async with tenant_session(tenant_id) as session:
        for call_id in call_ids:
            await campaign_dispatch.resolve_campaign_contact(
                session, tenant_id=tenant_id, call_id=call_id, call_status="no_answer"
            )
    async with tenant_session(tenant_id) as session:
        blocked = await national_dnd_blocker(
            session, campaign_id=campaign_id, classification="promotional"
        )
    assert blocked is None, blocked
