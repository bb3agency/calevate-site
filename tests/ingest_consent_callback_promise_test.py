"""A web form that declines to be phoned calls off a call-back we already promised.

THE THIRD DOOR ONTO ONE HONESTY RULE, and the one a sweep could not see (D-514,
19 Sep 2026). The enforcement half was never in doubt: a `callback`-purpose `declined`
row makes `check_dispatch` refuse the dial as `no_consent`, a PERSON-level refusal read
uncached per number, so the call-back settles refused at its own tick. What was missing
is the sentence on the client's screen in the meantime — it went on naming an hour we
were going to ring somebody who had just said not to.

WHY THIS WRITER WAS MISSED WHEN THE OTHER DOORS WERE CLOSED. `compliance.service
.add_to_dnc`, `dnc.add_numbers` and `consent.record_call_consent` were each given the
cancelling half. `ingest.service._record_dial_consent_declined` was not, because it does
NOT go through `record_call_consent`: it writes the `consent_ledger` row with its own
INSERT, so a sweep looking for callers of that function could not find it. A registry of
"the ways a person can decline" would have; the greps did not.

THE SENTENCE IS THE CONSENT ONE AND NOT THE DNC ONE, deliberately. A number that failed
a form's opt-in question is on nobody's do-not-call list, and telling its owner's client
otherwise sends them looking at a list the number is not on.

Run: uv run pytest -q tests/ingest_consent_callback_promise_test.py
"""

from __future__ import annotations

import uuid

from apps.api.compliance.models import CALLBACK_CONSENT_WITHDRAWN_REASON
from apps.api.db.session import tenant_session
from apps.api.ingest.routes import SECRET_HEADER
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.lead_ingest_test import SECRET, _tenant_with_ingest
from tests.scheduled_callback_test import _book, _row

#: The form's own opt-in question, named in the source's mapping. A source that names no
#: consent field takes a different branch (`no_consent_field_configured`) and is a
#: different support ticket — see `ingest/service.NO_CONSENT_FIELD_RULE`.
_CONSENT_MAPPING = {"phone": "phone", "name": "name", "consent_field": "agree_to_call"}


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _submit(webhook_id: uuid.UUID, *, phone: str, agreed: str) -> dict:
    async with _client() as http:
        response = await http.post(
            f"/hooks/v1/ingest/{webhook_id}",
            json={"phone": phone, "name": "Form Filler", "agree_to_call": agreed},
            headers={SECRET_HEADER: SECRET},
        )
    return dict(response.json())


async def test_a_form_decline_calls_off_the_call_back_it_contradicts() -> None:
    """The defect, as it was: the promise outlived the refusal on the client's screen."""
    tenant_id, agent_id, webhook_id = await _tenant_with_ingest(mapping=_CONSENT_MAPPING)
    phone = "+919876540001"
    promised = await _book(tenant_id, agent_id, phone=phone)

    body = await _submit(webhook_id, phone=phone, agreed="false")

    assert body["blocked"] == "no_form_consent", body
    row = await _row(tenant_id, promised)
    assert row["status"] == "cancelled", (
        "the call-back survived a refusal to be phoned; a client reading their screen "
        "would still see an hour we had promised this person"
    )
    assert row["last_refusal_reason"] == CALLBACK_CONSENT_WITHDRAWN_REASON, (
        "the consent wording, not the DNC one — this number is on no do-not-call list"
    )


async def test_an_affirmed_form_calls_nothing_off() -> None:
    """The negative control, and it is the one that matters: a cancellation that fires on
    every submission would call off every promise this product makes."""
    tenant_id, agent_id, webhook_id = await _tenant_with_ingest(mapping=_CONSENT_MAPPING)
    phone = "+919876540002"
    promised = await _book(tenant_id, agent_id, phone=phone)

    await _submit(webhook_id, phone=phone, agreed="true")

    assert (await _row(tenant_id, promised))["status"] == "scheduled"


async def test_it_stops_only_the_person_who_declined() -> None:
    """Keyed on the number, like every other door. A bystander's promise is untouched."""
    tenant_id, agent_id, webhook_id = await _tenant_with_ingest(mapping=_CONSENT_MAPPING)
    decliner, bystander = "+919876540003", "+919876540004"
    theirs = await _book(tenant_id, agent_id, phone=decliner)
    other = await _book(tenant_id, agent_id, phone=bystander)

    await _submit(webhook_id, phone=decliner, agreed="no")

    assert (await _row(tenant_id, theirs))["status"] == "cancelled"
    assert (await _row(tenant_id, other))["status"] == "scheduled"


async def test_a_dial_already_in_flight_is_left_alone() -> None:
    """`cancel_for_phones` moves `scheduled` rows only. A `dialing` row may be ringing as
    we write, and rewriting it would tell a client a call was called off while their
    lead's phone was in their hand. The gate covers that dial instead."""
    tenant_id, agent_id, webhook_id = await _tenant_with_ingest(mapping=_CONSENT_MAPPING)
    phone = "+919876540005"
    promised = await _book(tenant_id, agent_id, phone=phone)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE scheduled_callbacks SET status = 'dialing' WHERE id = :id"),
            {"id": promised},
        )
        await session.commit()

    await _submit(webhook_id, phone=phone, agreed="false")

    assert (await _row(tenant_id, promised))["status"] == "dialing"


async def test_the_ledger_row_is_still_written() -> None:
    """The cancellation is an ADDITION to this writer, not a replacement of it: the record
    of what the person answered is the point, and it shares the transaction."""
    tenant_id, _agent_id, webhook_id = await _tenant_with_ingest(mapping=_CONSENT_MAPPING)
    phone = "+919876540006"

    await _submit(webhook_id, phone=phone, agreed="false")

    async with tenant_session(tenant_id) as session:
        found = (
            await session.execute(
                text(
                    "SELECT status, purpose FROM consent_ledger WHERE phone_e164 = :p "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"p": phone},
            )
        ).first()
    assert found is not None, "the decline must still be recorded as a fact about a person"
    assert found[0] == "declined" and found[1] == "callback"
