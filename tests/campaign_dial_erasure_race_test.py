"""An erasure that lands while a campaign batch is in flight stops the dial, and stays done.

The dispatcher claims a batch, COMMITS the claim, then dials one contact at a time from the
rows the claim returned. A DPDP erasure (`retention.execute_deletion_request`) that runs in
that gap settles the contact `dnc_blocked` and anonymises its number, but it does not add
the number to any suppression list: erasure is not an objection to calls, and the gate has
no other way to know. So the in-memory copy of the claim is the only place the person's
number still exists, and dialling from it rings a person whose certificate says they were
removed from this list.

The same erased row was also reachable from the other side: every writer that settles a
claimed contact (`_record_failure`, `_refuse_contact`, `_exhaust_contact`) wrote by id
alone, so a call ending after the erasure put the anonymised row back to `pending` and the
next tick claimed a placeholder string as a phone number.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.compliance.deletion import request_erasure
from apps.api.db.session import tenant_session
from apps.api.engine.fake import FakeEngine
from apps.workers import campaign_dispatch
from apps.workers.retention import ANONYMIZED_PHONE, execute_deletion_request
from calevate_shared.engine import CallContext
from sqlalchemy import text
from tests.campaign_dispatch_audit_test import (  # noqa: F401 - autouse fixtures
    _calls_placed,
    _daytime,
    _launched,
    _roomy_platform_pool,
    _settle_what_this_module_started,
    _tick_one_campaign,
)

pytestmark = pytest.mark.asyncio


async def _erase(tenant_id: uuid.UUID, phone: str) -> str:
    async with tenant_session(tenant_id) as session:
        record = await request_erasure(session, tenant_id=tenant_id, phone_e164=phone)
    return await execute_deletion_request(
        {}, {"tenant_id": str(tenant_id), "request_id": str(record.id)}
    )


async def test_an_erasure_between_two_dials_stops_the_second_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _, campaign_id, _, _ = await _launched(phones=("9876640001", "9876640002"))
    original = FakeEngine.start_outbound_call
    dialled: list[str] = []

    async def erase_after_first(self: FakeEngine, ref: str, to: str, ctx: CallContext) -> str:
        handle = await original(self, ref, to, ctx)
        dialled.append(to)
        if len(dialled) == 1:
            # Contact #2 exercises DPDP §12 while #1 is ringing. Its own transaction,
            # committed, exactly as the erasure worker runs in production.
            await _erase(tenant_id, "+919876640002")
        return handle

    monkeypatch.setattr(FakeEngine, "start_outbound_call", erase_after_first)
    await _tick_one_campaign(tenant_id, campaign_id)

    assert dialled == ["+919876640001"], f"an erased person was dialled off the claim: {dialled}"
    assert await _calls_placed(tenant_id) == 1
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT phone_e164, status FROM campaign_contacts WHERE campaign_id = :c "
                    "AND left(phone_e164, 9) = :anon"
                ),
                {"c": campaign_id, "anon": ANONYMIZED_PHONE[:9]},
            )
        ).all()
    assert [str(r[1]) for r in rows] == ["dnc_blocked"], (
        "the erased row must stay settled, not be refunded back onto the ladder"
    )


async def _erased_contact() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """(tenant, campaign, contact): claimed and dialled, then erased while `dialing`."""
    tenant_id, _, campaign_id, _, _ = await _launched(phones=("9876650001",))
    await _tick_one_campaign(tenant_id, campaign_id)
    await _erase(tenant_id, "+919876650001")
    async with tenant_session(tenant_id) as session:
        contact_id = (
            await session.execute(
                text("SELECT id FROM campaign_contacts WHERE campaign_id = :c"),
                {"c": campaign_id},
            )
        ).scalar_one()
    return tenant_id, campaign_id, contact_id


async def _state(tenant_id: uuid.UUID, contact_id: uuid.UUID) -> tuple[str, int, object]:
    async with tenant_session(tenant_id) as session:
        status, attempts, due = (
            await session.execute(
                text(
                    "SELECT status, attempts, next_attempt_at FROM campaign_contacts WHERE id = :i"
                ),
                {"i": contact_id},
            )
        ).one()
    return str(status), int(attempts), due


async def test_a_call_ending_after_its_contact_was_erased_leaves_it_settled() -> None:
    tenant_id, _campaign_id, contact_id = await _erased_contact()
    async with tenant_session(tenant_id) as session:
        call_id = (
            await session.execute(
                text("SELECT last_call_id FROM campaign_contacts WHERE id = :i"),
                {"i": contact_id},
            )
        ).scalar_one()
        outcome = await campaign_dispatch.resolve_campaign_contact(
            session, tenant_id=tenant_id, call_id=call_id, call_status="no_answer"
        )
    assert outcome is None, "an erased contact is no longer the call's to settle"
    assert (await _state(tenant_id, contact_id))[0] == "dnc_blocked"


@pytest.mark.parametrize(
    "settle", ["unanswered", "exhausted", "refused_transient", "refused_terminal"]
)
async def test_no_settle_writer_resurrects_an_erased_contact(settle: str) -> None:
    """Each writer that settles a claimed contact, applied to one an erasure has already
    settled, leaves it exactly as the erasure did. The dispatcher reaches these with a
    contact id from a claim that may be seconds old, so none of them may write by id
    alone; and the exhausted one must not queue a follow-up message to the person."""
    tenant_id, campaign_id, contact_id = await _erased_contact()
    before = await _state(tenant_id, contact_id)
    assert before[0] == "dnc_blocked"

    async with tenant_session(tenant_id) as session:
        if settle == "unanswered":
            spent = await campaign_dispatch._record_failure(
                session, contact_id, 1, 3, {}, tenant_id=tenant_id, campaign_id=campaign_id
            )
            assert spent is False
        elif settle == "exhausted":
            spent = await campaign_dispatch._record_failure(
                session, contact_id, 3, 3, {}, tenant_id=tenant_id, campaign_id=campaign_id
            )
            assert spent is False, "nothing was exhausted: the erasure had settled it"
        elif settle == "refused_transient":
            await campaign_dispatch._refuse_contact(session, contact_id, rule="calling_hours")
        else:
            await campaign_dispatch._refuse_contact(session, contact_id, rule="dnc")

    assert await _state(tenant_id, contact_id) == before
    async with tenant_session(tenant_id) as session:
        escalations = (
            await session.execute(
                text("SELECT count(*) FROM outbox_messages WHERE dedupe_key = :k"),
                {"k": f"campaign-escalation:{contact_id}"},
            )
        ).scalar_one()
    assert escalations == 0, "an erased person was queued a follow-up message"
