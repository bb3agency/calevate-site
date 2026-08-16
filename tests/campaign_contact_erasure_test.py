"""An erased person is not on a campaign list, and cannot be dialled off one.

THE DEFECT (P3.1). The string `campaign_contacts` appeared in NONE of
`workers/retention.py`, `compliance/deletion.py`, `compliance/tenant_erasure.py` or
`compliance/deletion_proof.py` — while the table carries `phone_e164 NOT NULL`, `name`,
and a `custom` JSONB holding **every other column the client pasted from their CSV**.
Three consequences, and the middle one is the one that is not merely a records gap:

1. the per-subject DPDP §12 erasure located its subject through `calls` and `leads` only,
   so a contact uploaded and never dialled was invisible to it;
2. **the row stayed `status='pending'` with a live number, so the next dispatch tick
   would have rung a person whose certificate said they had been removed**;
3. both certificates claim exhaustive enumeration — seven exceptions on one register,
   eight on the other, ten stores in the proof's `actions` map — and named none of this.

WHY THE DIAL IS THE SHARP EDGE. The campaign dispatcher reads `status`, not the phone
number, so anonymizing the number alone would have left the row perfectly dialable under
a value nobody could trace back. `dnc_blocked` is what actually stops it, and it is the
status the compliance gate's own refusal already writes — so a settled campaign reports
the row exactly as it reports one the DNC list stopped.

WHAT IS STILL OPEN, and it is deliberately not here: `retention_policies.data_category`
admits no category an uploaded contact list can be swept under, so with no erasure request
the list is kept indefinitely. That is a DPA commitment rather than an engineering
default, and it is recorded with its probe in `tests/dpdp_known_gaps_test.py`.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from apps.api.admin import service as admin_service
from apps.api.compliance.deletion import request_erasure
from apps.api.compliance.tenant_erasure import certificate, request_tenant_erasure
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.workers.retention import (
    ANONYMIZED_PHONE,
    execute_deletion_request,
    execute_tenant_erasure,
)
from sqlalchemy import text


def _phone() -> str:
    """A fresh subject per test: several suites share this database."""
    return f"+9198760{uuid.uuid4().int % 100000:05d}"


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name="Contact Clinic",
        slug=f"contacts-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return created["id"], created["agent_id"]


async def _campaign_with_contact(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, *, phone: str, name: str = "Padma"
) -> tuple[uuid.UUID, uuid.UUID]:
    """One campaign holding one contact, shaped exactly as `campaigns/service.py` writes
    it — including the `custom` blob and the `dedupe_hash` that is a bare sha256 of the
    number."""
    import hashlib

    campaign_id, contact_id = uuid7(), uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, status, "
                "classification, created_at, updated_at) VALUES (:c, :t, :a, "
                "'Winter recall', 'draft', 'service', now(), now())"
            ),
            {"c": campaign_id, "t": tenant_id, "a": agent_id},
        )
        await session.execute(
            text(
                "INSERT INTO campaign_contacts (id, tenant_id, campaign_id, phone_e164, "
                "name, custom, status, attempts, dedupe_hash, created_at, updated_at) "
                "VALUES (:i, :t, :c, :p, :n, CAST(:custom AS jsonb), 'pending', 0, :h, "
                "now(), now())"
            ),
            {
                "i": contact_id,
                "t": tenant_id,
                "c": campaign_id,
                "p": phone,
                "n": name,
                "custom": json.dumps({"city": "Warangal", "last_visit": "2026-03-02"}),
                "h": hashlib.sha256(phone.encode()).hexdigest()[:16],
            },
        )
    return campaign_id, contact_id


async def _contact(tenant_id: uuid.UUID, contact_id: uuid.UUID) -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT phone_e164, name, custom, dedupe_hash, status, next_attempt_at "
                    "FROM campaign_contacts WHERE id = :i"
                ),
                {"i": contact_id},
            )
        ).first()
    assert row is not None, "the row must survive — a DELETE would break the campaign's own totals"
    return {
        "phone_e164": row[0],
        "name": row[1],
        "custom": row[2],
        "dedupe_hash": row[3],
        "status": row[4],
        "next_attempt_at": row[5],
    }


async def _erase_subject(tenant_id: uuid.UUID, phone: str) -> str:
    async with tenant_session(tenant_id) as session:
        record = await request_erasure(session, tenant_id=tenant_id, phone_e164=phone)
    return await execute_deletion_request(
        {}, {"tenant_id": str(tenant_id), "request_id": str(record.id)}
    )


async def _churn(tenant_id: uuid.UUID) -> None:
    """The precondition `assert_erasable` enforces: a tenant erasure is the end of a
    commercial relationship, so the account has to be closed before its data can go."""
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET status = 'churned' WHERE id = :t"), {"t": tenant_id}
        )


# ============================================================================
# 1. The per-subject erasure (DPDP §12)
# ============================================================================


async def test_a_subject_with_no_call_and_no_lead_is_still_found_on_a_campaign_list() -> None:
    """THE SHAPE THE OLD CODE COULD NOT SEE AT ALL.

    `execute_deletion_request` located its subject through `calls` and `leads`. A contact
    uploaded from a CSV and not yet dialled is in neither, so this person's number, name
    and pasted columns were untouched by an erasure that certified them removed — and the
    row was `pending`, so the campaign would have called them next.
    """
    tenant_id, agent_id = await _tenant()
    phone = _phone()
    _campaign_id, contact_id = await _campaign_with_contact(tenant_id, agent_id, phone=phone)

    result = await _erase_subject(tenant_id, phone)

    assert "campaign_contacts=1" in result, result
    row = await _contact(tenant_id, contact_id)
    assert row["phone_e164"].startswith(ANONYMIZED_PHONE[:9]), row["phone_e164"]
    assert phone not in row["phone_e164"]
    assert row["name"] is None
    assert row["custom"] is None, "the pasted CSV columns are the client's own free text"
    assert row["dedupe_hash"] is None, (
        "sha256(phone)[:16] is unsalted over a ~10^9 space — leaving it leaves the number"
    )


async def test_the_erased_person_cannot_be_dialled_off_the_list() -> None:
    """The consequence that is not a records gap. `status` is what the dispatcher reads."""
    tenant_id, agent_id = await _tenant()
    phone = _phone()
    _campaign_id, contact_id = await _campaign_with_contact(tenant_id, agent_id, phone=phone)

    before = await _contact(tenant_id, contact_id)
    assert before["status"] == "pending", "the fixture must start dialable or it proves nothing"

    await _erase_subject(tenant_id, phone)

    row = await _contact(tenant_id, contact_id)
    assert row["status"] == "dnc_blocked", (
        "an erased person is still queued for a call — anonymizing the number does not "
        "stop the dispatcher, which reads status"
    )
    assert row["next_attempt_at"] is None


async def test_only_this_subject_is_erased() -> None:
    """The scoping, because the statement takes a bare phone predicate: somebody else on
    the same campaign must be left exactly as they were."""
    tenant_id, agent_id = await _tenant()
    subject, bystander = _phone(), _phone()
    campaign_id, subject_contact = await _campaign_with_contact(tenant_id, agent_id, phone=subject)
    other_contact = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO campaign_contacts (id, tenant_id, campaign_id, phone_e164, "
                "name, status, attempts, created_at, updated_at) VALUES (:i, :t, :c, :p, "
                "'Ravi', 'pending', 0, now(), now())"
            ),
            {"i": other_contact, "t": tenant_id, "c": campaign_id, "p": bystander},
        )

    await _erase_subject(tenant_id, subject)

    assert (await _contact(tenant_id, subject_contact))["status"] == "dnc_blocked"
    untouched = await _contact(tenant_id, other_contact)
    assert untouched["phone_e164"] == bystander
    assert untouched["name"] == "Ravi"
    assert untouched["status"] == "pending"


async def test_the_certificate_names_the_contact_list() -> None:
    """SEC-COMP §4: what the erasure did is enumerated in the certificate rather than
    left to inference. A count of zero is as much a claim as a count of five, so the key
    is present either way."""
    tenant_id, agent_id = await _tenant()
    phone = _phone()
    await _campaign_with_contact(tenant_id, agent_id, phone=phone)

    async with tenant_session(tenant_id) as session:
        record = await request_erasure(session, tenant_id=tenant_id, phone_e164=phone)
    await execute_deletion_request({}, {"tenant_id": str(tenant_id), "request_id": str(record.id)})

    async with tenant_session(tenant_id) as session:
        proof = (
            await session.execute(
                text("SELECT proof FROM deletion_requests WHERE id = :r"), {"r": record.id}
            )
        ).scalar()
    assert isinstance(proof, dict)
    sentence = proof["actions"]["campaign_contacts"]
    assert sentence.startswith("1 uploaded campaign contact row(s)"), sentence
    assert "dnc_blocked" in sentence, "the certificate must say the row can no longer be dialled"


async def test_a_re_run_erases_nothing_a_second_time() -> None:
    """The anonymized-prefix guard, which is what makes the statement safe to re-run —
    and `execute_deletion_request` is re-run by arq on any storage failure."""
    tenant_id, agent_id = await _tenant()
    phone = _phone()
    _campaign_id, contact_id = await _campaign_with_contact(tenant_id, agent_id, phone=phone)

    await _erase_subject(tenant_id, phone)
    anonymized = (await _contact(tenant_id, contact_id))["phone_e164"]

    # A SECOND request for the same number: the first one cleared it, so this one finds
    # nothing — which is the correct answer and must not be an error.
    second = await _erase_subject(tenant_id, phone)
    assert "campaign_contacts=0" in second, second
    assert (await _contact(tenant_id, contact_id))["phone_e164"] == anonymized


# ============================================================================
# 2. The tenant-wide erasure (FLOWS §9)
# ============================================================================


async def test_a_tenant_erasure_clears_every_uploaded_contact() -> None:
    """The other path, which had the same hole. Three contacts across two campaigns, so
    the assertion is about the tenant rather than about one list."""
    tenant_id, agent_id = await _tenant()
    first, second = await _campaign_with_contact(tenant_id, agent_id, phone=_phone())
    third_campaign, third = await _campaign_with_contact(tenant_id, agent_id, phone=_phone())
    assert first != third_campaign

    await _churn(tenant_id)
    async with tenant_session(tenant_id) as session:
        record = await request_tenant_erasure(
            session, tenant_id=tenant_id, reason="engagement ended"
        )
    result = await execute_tenant_erasure(
        {}, {"tenant_id": str(tenant_id), "request_id": str(record.id)}
    )

    assert "campaign_contacts=2" in result, result
    for contact_id in (second, third):
        row = await _contact(tenant_id, contact_id)
        assert row["phone_e164"].startswith(ANONYMIZED_PHONE[:9])
        assert row["name"] is None and row["custom"] is None and row["dedupe_hash"] is None
        assert row["status"] == "dnc_blocked"


async def test_the_tenant_certificate_counts_them_as_a_first_class_fact() -> None:
    """On the certificate's `scope`, not only in a sentence.

    A document that enumerates calls, transcripts and leads by count and is silent about
    the CSV of numbers the client pasted in is the "claims exhaustive enumeration and is
    not" defect the register exists against. `_SCOPE_COUNTS` is a whitelist, so a count
    the worker records and the renderer does not name is a count nobody ever sees.
    """
    tenant_id, agent_id = await _tenant()
    await _campaign_with_contact(tenant_id, agent_id, phone=_phone())

    await _churn(tenant_id)
    async with tenant_session(tenant_id) as session:
        record = await request_tenant_erasure(
            session, tenant_id=tenant_id, reason="engagement ended"
        )
    await execute_tenant_erasure({}, {"tenant_id": str(tenant_id), "request_id": str(record.id)})

    async with tenant_session(tenant_id) as session:
        proof = (
            await session.execute(
                text("SELECT proof FROM tenant_erasure_requests WHERE id = :r"), {"r": record.id}
            )
        ).scalar()
    rendered = certificate(proof)
    assert rendered is not None
    assert rendered["scope"]["campaign_contacts_erased"] == 1, rendered["scope"]
    assert "dnc_blocked" in rendered["actions"]["campaign_contacts"]
