"""The two stores that had no retention clock at all, against a real database.

**WHAT THIS FILE IS FOR.** `campaign_contacts` and `scheduled_callbacks` were reachable
only by a DPDP §12 erasure — a data principal had to ASK — while every other store of
personal data in this schema ages out on its own. They are also the two whose subjects are
least able to ask: a person on an uploaded list that was never dialled does not know we
hold their number, their name and whatever else their business pasted beside it. DPDP
§8(7) is a duty on the Fiduciary, not a service performed on request.

**NEITHER GOT A CATEGORY OF ITS OWN**, and that decision is half of what is under test
here. A new `retention_policies.data_category` needs a NUMBER, and this repository already
records that the number for an uploaded contact list is a client DPA term the founder
gives; inventing one would be hard rule 11 in the place it costs most. What each table IS
was already decided, so each rides the clock of the thing it is:

* `campaign_contacts` → the `lead` clock (1095 days). A name, a number and the client's own
  pasted columns is the same class of data as `leads.data` — what the client uploaded,
  bought, and keeps using.
* `scheduled_callbacks` → the `transcript` clock (365 days). A model-written note of what
  one caller wanted on one call, which belongs with the words it paraphrases, exactly like
  `calls.summary` and `handoff_attempts.summary`.

**SO THE SECOND TEST MATTERS MORE THAN THE FIRST.** An arm that sweeps both tables is easy
to write and easy to write WRONGLY — under one category, or under whichever one the author
happened to be editing. `test_each_table_rides_its_own_category` moves the two periods
independently and asserts each table follows only its own, which is the assertion that
fails the day somebody merges the arms for tidiness and quietly triples how long a caller's
note is kept.

**AND THE EXPIRY IS NOT THE ERASURE.** The erasure statements over these tables force a
terminal row's status as well as a live one's, because an erasure's job is to leave nothing
claimable and it may rewrite a campaign's history to do it. A retention period elapsing may
not: a contact dialled and completed three years ago is the client's record of their own
campaign. Both tests assert the settled rows keep their endings while losing their words.

`sweep_tenant` and not `apply_retention`, for `retention_caller_memory_test`'s reason: the
nightly entry point resolves its own worklist and would sweep every tenant in a shared
development database. The probe, the arms and the counts are identical.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.workers.retention import ANONYMIZED_PHONE, CALLBACK_EXPIRED_REASON, sweep_tenant
from sqlalchemy import text

pytestmark = pytest.mark.anyio

#: Real details rather than placeholders: what these tests watch disappear is a specific
#: person's name and number sitting in a list they never asked to be on.
UPLOADED = "+919812345001"
UPLOADED_NAME = "Lakshmi Rao"
DIALLED = "+919812345002"
PROMISED = "+919812345003"
NOTE = "wants the Kukatpally site plan and a price for two bedrooms"

#: The seeded periods, restated as literals. Imported from nowhere on purpose: a test that
#: read the tenant's own policy row for its cutoff would pass for whatever number that row
#: happened to hold, including a zero somebody typed by accident.
LEAD_TTL_DAYS = 1095
TRANSCRIPT_TTL_DAYS = 365

_INSERT_CONTACT_SQL = """
INSERT INTO campaign_contacts (
  id, tenant_id, campaign_id, phone_e164, name, custom, status,
  created_at, updated_at)
VALUES (:id, :tenant, :campaign, :phone, :name, CAST(:custom AS jsonb), :status,
        :created, :created)
"""

_INSERT_CALLBACK_SQL = """
INSERT INTO scheduled_callbacks (
  id, tenant_id, agent_id, source_execution_id, phone_e164, requested_at, booked_at,
  status, settled_at, note, created_at, updated_at)
VALUES (:id, :tenant, :agent, :execution, :phone, :requested, :requested,
        :status, :settled, :note, :requested, :requested)
"""


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    """A tenant with the shipped retention rows and one agent to hang a campaign on."""
    created = await admin_service.create_organization(
        name="Uploaded List Realty",
        slug=f"ulr-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return uuid.UUID(str(created["id"])), uuid.UUID(str(created["agent_id"]))


async def _campaign(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> uuid.UUID:
    campaign_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, classification, status) "
                "VALUES (:id, :tenant, :agent, 'Winter launch', 'promotional', 'draft')"
            ),
            {"id": campaign_id, "tenant": tenant_id, "agent": agent_id},
        )
        await session.commit()
    return campaign_id


async def _contact(
    tenant_id: uuid.UUID,
    campaign_id: uuid.UUID,
    *,
    phone: str,
    days_ago: int,
    status: str = "pending",
) -> uuid.UUID:
    """One uploaded row: a number, a name and the columns pasted beside them."""
    contact_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(_INSERT_CONTACT_SQL),
            {
                "id": contact_id,
                "tenant": tenant_id,
                "campaign": campaign_id,
                "phone": phone,
                "name": UPLOADED_NAME,
                "custom": '{"site": "Kukatpally", "budget": "60L"}',
                "status": status,
                "created": datetime.now(UTC) - timedelta(days=days_ago),
            },
        )
        await session.commit()
    return contact_id


async def _callback(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    phone: str,
    days_ago: int,
    settled: bool = False,
) -> uuid.UUID:
    """One promised call-back: the number, and the model's note of what it is about."""
    callback_id = uuid7()
    requested = datetime.now(UTC) - timedelta(days=days_ago)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(_INSERT_CALLBACK_SQL),
            {
                "id": callback_id,
                "tenant": tenant_id,
                "agent": agent_id,
                "execution": f"exec-{uuid.uuid4().hex[:10]}",
                "phone": phone,
                "requested": requested,
                "status": "completed" if settled else "scheduled",
                "settled": requested if settled else None,
                "note": NOTE,
            },
        )
        await session.commit()
    return callback_id


async def _contact_state(tenant_id: uuid.UUID, contact_id: uuid.UUID) -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT phone_e164, name, custom, status FROM campaign_contacts WHERE id = :c"
                ),
                {"c": contact_id},
            )
        ).first()
    assert row is not None, "the contact row is gone; this arm anonymizes and never deletes"
    return {
        "anonymized": str(row[0]).startswith(ANONYMIZED_PHONE[:9]),
        "name": row[1],
        "custom": row[2],
        "status": str(row[3]),
    }


async def _callback_state(tenant_id: uuid.UUID, callback_id: uuid.UUID) -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT phone_e164, note, status, settled_at, last_refusal_reason "
                    "  FROM scheduled_callbacks WHERE id = :c"
                ),
                {"c": callback_id},
            )
        ).first()
    assert row is not None, "the call-back row is gone; this arm anonymizes and never deletes"
    return {
        "anonymized": str(row[0]).startswith(ANONYMIZED_PHONE[:9]),
        "note": row[1],
        "status": str(row[2]),
        "settled": row[3] is not None,
        "reason": row[4],
    }


async def _set_ttl(tenant_id: uuid.UUID, category: str, days: int) -> None:
    async with tenant_session(tenant_id) as session:
        result = await session.execute(
            text(
                "UPDATE retention_policies SET ttl_days = :d WHERE data_category = :c RETURNING id"
            ),
            {"d": days, "c": category},
        )
        assert result.first() is not None, f"this tenant has no {category} policy row to set"
        await session.commit()


# ============================================ 1. THE ARMS: both stores now age out


async def test_an_expired_upload_and_an_expired_promise_are_both_forgotten() -> None:
    """Past their periods the details go, the rows stay, and nothing stays callable.

    Asserted on the emptied columns and on the status rather than on a row count: both arms
    keep their rows by design (a running campaign counts its own contacts to know when it
    has finished), so a count assertion would be green against a sweep that did nothing.
    """
    tenant_id, agent_id = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id)

    expired = await _contact(tenant_id, campaign_id, phone=UPLOADED, days_ago=LEAD_TTL_DAYS + 5)
    dialled = await _contact(
        tenant_id, campaign_id, phone=DIALLED, days_ago=LEAD_TTL_DAYS + 5, status="completed"
    )
    fresh = await _contact(tenant_id, campaign_id, phone="+919812345004", days_ago=2)
    promise = await _callback(tenant_id, agent_id, phone=PROMISED, days_ago=TRANSCRIPT_TTL_DAYS + 5)
    recent = await _callback(tenant_id, agent_id, phone="+919812345005", days_ago=2)

    counts = await sweep_tenant(tenant_id)

    assert counts["campaign_contacts"] == 2, counts
    assert counts["scheduled_callbacks"] == 1, counts

    gone = await _contact_state(tenant_id, expired)
    assert gone["anonymized"], "the uploaded number survived its own retention period"
    assert gone["name"] is None
    assert gone["custom"] is None, "the pasted CSV columns are the half nobody inventories"
    assert gone["status"] == "dnc_blocked", (
        "a pending row with a blanked number is one the dispatcher still claims — it would "
        "dial a string that is not a phone number"
    )

    history = await _contact_state(tenant_id, dialled)
    assert history["anonymized"] and history["name"] is None
    assert history["status"] == "completed", (
        "a retention period elapsing must not rewrite the client's own campaign history; "
        "that is the erasure's licence and not this sweep's"
    )

    kept = await _contact_state(tenant_id, fresh)
    assert not kept["anonymized"] and kept["name"] == UPLOADED_NAME

    stopped = await _callback_state(tenant_id, promise)
    assert stopped["anonymized"], "the promised number survived the transcript period"
    assert stopped["note"] is None, "the note is a model's account of what a caller said"
    assert stopped["status"] == "cancelled" and stopped["settled"]
    assert stopped["reason"] == CALLBACK_EXPIRED_REASON, (
        "this person asked us for nothing; telling the client they requested a deletion "
        "would write a false statement about a data principal into the client's console"
    )

    live = await _callback_state(tenant_id, recent)
    assert not live["anonymized"] and live["note"] == NOTE


# ============================================ 2. TWO CLOCKS, AND NEITHER FOLLOWS THE OTHER


async def test_each_table_rides_its_own_category() -> None:
    """The uploaded list is on the CRM clock and the promise is on the transcript's.

    Both directions, because an arm filed under one category is invisible in exactly one of
    them: a sweep that put the call-back on the `lead` clock passes the first test in this
    file and keeps a caller's note for three years.
    """
    tenant_id, agent_id = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id)
    contact = await _contact(tenant_id, campaign_id, phone=UPLOADED, days_ago=800)
    promise = await _callback(tenant_id, agent_id, phone=PROMISED, days_ago=800)

    # The CRM period has not elapsed at 800 days; the transcript period has.
    counts = await sweep_tenant(tenant_id)
    assert counts["campaign_contacts"] == 0, counts
    assert counts["scheduled_callbacks"] == 1, counts
    assert not (await _contact_state(tenant_id, contact))["anonymized"], (
        "the contact aged out on somebody else's clock — the client's agreed CRM period is "
        "1095 days and this row is 800 days old"
    )
    assert (await _callback_state(tenant_id, promise))["anonymized"]

    # Now shorten the CRM period alone. The contact must go; nothing else may move.
    await _set_ttl(tenant_id, "lead", 400)
    counts = await sweep_tenant(tenant_id)
    assert counts["campaign_contacts"] == 1, counts
    assert (await _contact_state(tenant_id, contact))["anonymized"]

    # And lengthening the transcript period must hold a NEW promise back, which is the
    # other direction: the arm reads the tenant's own row rather than a constant.
    await _set_ttl(tenant_id, "transcript", 5000)
    later = await _callback(tenant_id, agent_id, phone="+919812345006", days_ago=900)
    counts = await sweep_tenant(tenant_id)
    assert counts["scheduled_callbacks"] == 0, counts
    assert (await _callback_state(tenant_id, later))["note"] == NOTE
