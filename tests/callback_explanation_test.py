"""A call-back that was refused once and then went out must not keep saying it was refused.

`GET /v1/callbacks` explains every row with the stored `last_refusal_reason` when there is
one, falling back to the plain reading of the status. `defer` writes that reason so a
waiting row can say why it is waiting; nothing cleared it when a later attempt was
claimed, so a promise refused at 16:00 for want of credit and then rung at 16:05 read
"This account has no calling credit." forever, beside `status: completed`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.admin import service as admin_service
from apps.api.callbacks import service as callbacks
from apps.api.callbacks.routes import _ENDINGS, _view
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from sqlalchemy import text

pytestmark = pytest.mark.anyio

CALLER = "+919812345679"
NO_CREDIT = "This account has no calling credit."


async def test_a_deferral_reason_does_not_outlive_the_dial_that_followed_it() -> None:
    created = await admin_service.create_organization(
        name="Explained Estates",
        slug=f"cbx-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]

    async with tenant_session(tenant_id) as session:
        booked = await callbacks.book(
            session,
            callback_id=uuid7(),
            tenant_id=tenant_id,
            agent_id=agent_id,
            source_call_id=None,
            source_execution_id=f"exec_{uuid.uuid4().hex[:10]}",
            lead_id=None,
            phone_e164=CALLER,
            requested_at=datetime.now(UTC) - timedelta(minutes=1),
            booked_at=datetime.now(UTC),
            note=None,
            language=None,
        )
        assert booked is not None
        callback_id = booked[0]

        # First tick: refused for a reason a top-up lifts.
        assert [c.id for c in await callbacks.claim_due(session, limit=5)] == [callback_id]
        await callbacks.defer(session, callback_id, rule="no_credits", reason=NO_CREDIT)

        # Second tick, after the retry interval: claimed again and dialled.
        later = datetime.now(UTC) + callbacks.RETRY_AFTER + timedelta(seconds=1)
        assert [c.id for c in await callbacks.claim_due(session, now=later, limit=5)] == [
            callback_id
        ]
        dialing = await callbacks.get_callback(session, callback_id)
        assert dialing is not None
        assert _view(dialing).explanation == _ENDINGS["dialing"]

        call_id = uuid7()
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                "to_e164, status, created_at, updated_at) VALUES (:id, :tid, :aid, :ecid, "
                "'outbound', :to_e, 'completed', now(), now())"
            ),
            {
                "id": call_id,
                "tid": tenant_id,
                "aid": agent_id,
                "ecid": f"exec_{uuid.uuid4().hex[:10]}",
                "to_e": CALLER,
            },
        )
        await callbacks.link_callback_to_call(callback_id)(session, call_id)
        assert await callbacks.settle_dialled(session) == 1
        row = await callbacks.get_callback(session, callback_id)
        await session.commit()

    assert row is not None
    assert row["status"] == "completed"
    assert _view(row).explanation == _ENDINGS["completed"]
