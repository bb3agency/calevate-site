"""Withdrawing permission to be TELEPHONED must stop the call-back being advertised.

D-514's two doors again, at the third place a dial stops being permitted. The gate is the
enforcement — `no_consent` is in `PERSON_LEVEL_REFUSALS` and the consent read is per-number
and uncached, so a call-back to somebody who has withdrawn permission settles `refused` on
the next tick whatever else happens. The HONESTY half is what was missing: until this,
`compliance.consent.record_call_consent` could record that a person had withdrawn their
permission to be called while the client's Call-backs screen went on naming the hour we
were going to telephone them.

It is the same defect the do-not-call writers had, found by asking the same question of
every path that stops a dial rather than of the one path that was reported. `record_call_
optout` -> `add_to_dnc` was fixed on 19 Sep 2026; `dnc.add_numbers` before that; the
platform-wide writer and this one were still open.

WHY A SECOND SENTENCE AND NOT `CALLBACK_SUPPRESSED_REASON`: the two are different facts
with different remedies. "This number was added to your do-not-call list" sends the client
to a list the number is not on; what happened here is the person's own later word on an
append-only ledger.

SCOPE IS ASSERTED IN BOTH DIRECTIONS, because a cancellation is destructive to a promise:
a `granted` record cancels nothing, and a `messaging` withdrawal — a different purpose on a
different channel — cancels nothing either.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.compliance import consent
from apps.api.db.session import tenant_session
from sqlalchemy import text
from tests.scheduled_callback_test import _book, _row, _tenant

pytestmark = pytest.mark.anyio


def _number() -> str:
    return f"+9198{uuid.uuid4().int % 100000000:08d}"


async def _record_call_consent(tenant_id: uuid.UUID, phone: str, status: str) -> None:
    async with tenant_session(tenant_id) as session:
        await consent.record_call_consent(
            session,
            tenant_id=tenant_id,
            raw_phone=phone,
            status=status,
            source="web_form_optin" if status == "granted" else "staff_recorded_request",
            evidence={"form": "site enquiry", "field": "call_me"} if status == "granted" else None,
        )
        await session.commit()


async def test_a_withdrawn_permission_stops_the_promise_the_client_is_being_shown() -> None:
    """THE DEFECT. The person withdraws permission to be telephoned; the call-back they
    were promised must stop being advertised in the same transaction."""
    tenant_id, agent_id = await _tenant()
    phone = _number()
    promised = await _book(tenant_id, agent_id, phone=phone)

    await _record_call_consent(tenant_id, phone, "withdrawn")

    row = await _row(tenant_id, promised)
    assert row["status"] == "cancelled"
    reason = str(row["last_refusal_reason"]).lower()
    # The sentence says what happened, and says it about the right thing: this is NOT the
    # do-not-call wording, which would send the client to a list the number is not on.
    assert "permission" in reason and "withdrawn" in reason
    assert "do-not-call" not in reason


async def test_a_declined_permission_stops_it_too() -> None:
    """`DIAL_REFUSING_CONSENT_STATUSES` is the gate's own set and has two members. A door
    that honoured one of them would be honest about half the refusals it causes."""
    tenant_id, agent_id = await _tenant()
    phone = _number()
    promised = await _book(tenant_id, agent_id, phone=phone)

    await _record_call_consent(tenant_id, phone, "declined")

    assert (await _row(tenant_id, promised))["status"] == "cancelled"


async def test_a_granted_permission_cancels_nothing() -> None:
    """The other direction, and the one that matters most: recording that somebody SAID
    YES must never call off the call they said yes to."""
    tenant_id, agent_id = await _tenant()
    phone = _number()
    promised = await _book(tenant_id, agent_id, phone=phone)

    await _record_call_consent(tenant_id, phone, "granted")

    assert (await _row(tenant_id, promised))["status"] == "scheduled"


async def test_a_messaging_withdrawal_cancels_nothing() -> None:
    """Two purposes, never interchangeable (this module's own first sentence). Somebody who
    stops wanting WhatsApp messages has not called off the phone call they asked for."""
    tenant_id, agent_id = await _tenant()
    phone = _number()
    promised = await _book(tenant_id, agent_id, phone=phone)

    async with tenant_session(tenant_id) as session:
        await consent.record_messaging_consent(
            session,
            tenant_id=tenant_id,
            raw_phone=phone,
            status="withdrawn",
            source="staff_recorded_request",
        )
        await session.commit()

    assert (await _row(tenant_id, promised))["status"] == "scheduled"


async def test_it_stops_only_that_persons_promise() -> None:
    """A blanket UPDATE passes every test above and fails this one."""
    tenant_id, agent_id = await _tenant()
    phone = _number()
    withdrawn = await _book(tenant_id, agent_id, phone=phone)
    untouched = await _book(tenant_id, agent_id, phone=_number())

    await _record_call_consent(tenant_id, phone, "withdrawn")

    assert (await _row(tenant_id, withdrawn))["status"] == "cancelled"
    assert (await _row(tenant_id, untouched))["status"] == "scheduled"


async def test_another_tenants_promise_to_the_same_person_is_untouched() -> None:
    """CROSS-TENANT ZERO ROWS (hard rule 1). Consent is a fact one client recorded about a
    person, on that client's own ledger — it is not a platform-wide suppression, and the
    statement that acts on it runs under the recording tenant's own RLS policy. The
    platform-wide instrument is `dnc.add_global_numbers`, which is a different door with a
    different audit trail and a step-up confirmation in front of it."""
    tenant_a, agent_a = await _tenant()
    tenant_b, agent_b = await _tenant()
    phone = _number()
    theirs = await _book(tenant_a, agent_a, phone=phone)
    others = await _book(tenant_b, agent_b, phone=phone)

    await _record_call_consent(tenant_a, phone, "withdrawn")

    assert (await _row(tenant_a, theirs))["status"] == "cancelled"
    assert (await _row(tenant_b, others))["status"] == "scheduled"


async def test_a_dial_already_in_flight_is_left_alone() -> None:
    """`cancel_for_phones`' rule, asserted through this caller too: that dial is ringing or
    has rung, and the fire-time gate is what covers it."""
    tenant_id, agent_id = await _tenant()
    phone = _number()
    promised = await _book(tenant_id, agent_id, phone=phone)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE scheduled_callbacks SET status = 'dialing' WHERE id = :id"),
            {"id": promised},
        )
        await session.commit()

    await _record_call_consent(tenant_id, phone, "withdrawn")

    assert (await _row(tenant_id, promised))["status"] == "dialing"


async def test_the_ledger_row_is_still_written() -> None:
    """The cancellation is an addition to this function, not a replacement of it: the
    record of what the person said is the point, and it shares the transaction."""
    tenant_id, agent_id = await _tenant()
    phone = _number()
    await _book(tenant_id, agent_id, phone=phone)

    await _record_call_consent(tenant_id, phone, "withdrawn")

    async with tenant_session(tenant_id) as session:
        found = (
            (
                await session.execute(
                    text(
                        "SELECT status FROM consent_ledger WHERE phone_e164 = :phone "
                        "AND purpose = 'callback'"
                    ),
                    {"phone": phone},
                )
            )
            .scalars()
            .all()
        )
    assert list(found) == ["withdrawn"]
