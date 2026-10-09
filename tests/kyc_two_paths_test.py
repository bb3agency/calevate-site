"""D-692: KYC on two paths, the no-cold-calls pledge, and the outbound gate they replace.

The founder decided on 8 Oct 2026 that clients do not register on DLT and that a client
may dial outbound once its KYC is verified and it has accepted a no-cold-calls pledge. The
properties pinned here:

1. **The gate.** Every tier needs KYC + a current pledge; the DLT entity chain and the
   bound DLT-registered number are no longer asked; an admin's "require DigiLocker" holds
   outbound until a run completes after it; inbound is never gated.
2. **The pledge.** Versioned; a version bump forces re-acceptance; a stale screen cannot
   accept; an operator cannot accept for a client; an acceptance cannot be edited.
3. **The files.** Type, size and name limits; bytes encrypted under a per-document DEK
   bound to tenant and row; the owner's ID deleted when a reviewer decides and after 30
   days if nobody does; the business certificate swept on account erasure.
4. **DigiLocker.** The Cashfree adapter against its documented wire shapes; the outcome
   is pulled, never trusted from the push; only a masked ID and a name leave it, and
   nothing of the fetched record is persisted.
5. **Hard rule 1.** Cross-tenant zero rows on both new tables, and the two untenanted read
   arms reach only what they were written for.

Run: uv run pytest -q tests/kyc_two_paths_test.py
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from uuid import UUID

import httpx
import pytest
from apps.api.admin import service as admin_service
from apps.api.compliance import outbound_pledge, tenant_erasure
from apps.api.compliance.kyc import (
    names_match,
    numbering_submission_bundle,
    read_kyc,
    record_digilocker_completion,
    record_kyc,
    set_digilocker_requirement,
)
from apps.api.compliance.kyc_documents import (
    accept_upload,
    current_documents,
    mask_aadhaar,
    mask_pan,
    open_document,
)
from apps.api.compliance.kyc_providers import (
    NO_API_CREDENTIALS,
    VerificationOutcome,
    available_provider,
)
from apps.api.compliance.kyc_providers.cashfree import (
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    CashfreeDigiLocker,
    sign,
)
from apps.api.compliance.kyc_providers.fake import stage_outcome
from apps.api.compliance.service import check_dispatch
from apps.api.core.envelope import seal_bytes, unseal_bytes
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from apps.workers.kyc_owner_id_purge import KycPurgeIncompleteError, purge_due_kyc_documents
from apps.workers.retention import execute_tenant_erasure
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from tests.conftest import (
    PDF_BYTES,
    FakeS3,
    accept_agreements,
    fund_wallet,
    put_business_on_file_for_tests,
    record_autodialer_notice_for_tests,
    verify_kyc_and_pledge_for_tests,
)

pytestmark = [pytest.mark.rls]

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
SECRET = "kyc-webhook-secret-for-tests"
KYC = "/v1/compliance/kyc"
PLEDGE = "/v1/compliance/outbound-pledge"
#: The SHA-256 of `PLEDGE_TEXT` at each version. A wording change without a version bump
#: fails here, which is what keeps an old acceptance from standing for new words.
PINNED_PLEDGE_HASHES = {1: "868220698e23736c2e867cec8c186f0afa19f298d076aa64fd7e64a68820f1a6"}


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _tenant(plan_tier: str = "managed") -> dict[str, Any]:
    created = await admin_service.create_organization(
        name="Two Paths Traders",
        slug=f"kyc2-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    await accept_agreements(UUID(str(created["id"])), kyc_and_pledge=False)
    return created


async def _member(tenant_id: UUID) -> str:
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:id, :email, now(), now())"
            ),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, 'owner', now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id},
        )
    return f"dev:client:{user_id}"


async def _headers(org: dict[str, Any]) -> dict[str, str]:
    token = await _member(UUID(str(org["id"])))
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": str(org["slug"])}


async def _admin_id() -> UUID:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    return admin_id


async def _admin_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer dev:admin:{await _admin_id()}"}


async def _agent(tenant_id: UUID, *, direction: str = "outbound") -> UUID:
    agent_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO agents (id, tenant_id, name, direction, status, language_primary, "
                "disclosure_line, ai_disclosure_line, recording_notice_line, "
                "caller_memory_notice_line, created_at, updated_at) VALUES (:id, :tid, 'D691 "
                "agent', :dir, 'live', 'te-IN', 'This is an AI assistant and this call is "
                "recorded.', 'This is an AI assistant and this call is recorded.', 'This call "
                "is being recorded.', 'I keep a short note of what you ask about.', now(), "
                "now())"
            ),
            {"id": agent_id, "tid": tenant_id, "dir": direction},
        )
    return agent_id


async def _dial(tenant_id: UUID, agent_id: UUID) -> Any:
    async with tenant_session(tenant_id) as session:
        return await check_dispatch(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            phone_e164=f"+9190{uuid.uuid4().int % 10**8:08d}",
        )


async def _ready_tenant() -> tuple[UUID, UUID]:
    """A managed tenant with an outbound agent, the autodialer notice and money — and NO
    DLT registration and NO bound number, which D-692 no longer requires."""
    org = await _tenant()
    tenant_id = UUID(str(org["id"]))
    agent_id = await _agent(tenant_id)
    await record_autodialer_notice_for_tests(tenant_id, kyc_and_pledge=False)
    await fund_wallet(tenant_id)
    return tenant_id, agent_id


async def _verify_kyc_only(tenant_id: UUID) -> None:
    admin_id = await _admin_id()
    async with tenant_session(tenant_id) as session:
        await record_kyc(
            session,
            tenant_id=tenant_id,
            status="verified",
            entity_type="private_limited",
            document_kind="cin",
            document_ref="U74999TG2026PTC654321",
            verified_by_admin_id=admin_id,
        )


def _allowed_or_hours(decision: Any) -> None:
    """Calling hours are the one rule a wall clock can trip; anything else is a defect."""
    assert decision.allowed or decision.rule == "calling_hours", decision


# ============================================================================ the gate


async def test_a_managed_tenant_without_kyc_is_refused_kyc_missing() -> None:
    tenant_id, agent_id = await _ready_tenant()
    decision = await _dial(tenant_id, agent_id)
    assert decision.allowed is False
    assert decision.rule == "kyc_missing"


async def test_a_record_that_only_holds_declared_details_is_still_kyc_missing() -> None:
    tenant_id, agent_id = await _ready_tenant()
    await put_business_on_file_for_tests(tenant_id)
    assert (await _dial(tenant_id, agent_id)).rule == "kyc_missing"


async def test_verified_kyc_without_the_pledge_is_refused_on_the_pledge() -> None:
    tenant_id, agent_id = await _ready_tenant()
    await _verify_kyc_only(tenant_id)
    decision = await _dial(tenant_id, agent_id)
    assert decision.rule == outbound_pledge.PLEDGE_MISSING_RULE
    assert "no-cold-calls" in (decision.reason or "")
    assert "inbound" in (decision.reason or "").lower()


async def test_kyc_and_the_pledge_open_outbound_with_no_dlt_at_all() -> None:
    """The DLT entity chain and the bound DLT-registered number are not asked (D-692):
    this tenant has neither, and dials."""
    tenant_id, agent_id = await _ready_tenant()
    await verify_kyc_and_pledge_for_tests(tenant_id)
    async with tenant_session(tenant_id) as session:
        registrations = (
            await session.execute(text("SELECT count(*) FROM dlt_registrations"))
        ).scalar_one()
        numbers = (await session.execute(text("SELECT count(*) FROM phone_numbers"))).scalar_one()
    assert registrations == 0
    assert numbers == 0
    _allowed_or_hours(await _dial(tenant_id, agent_id))


async def test_a_pledge_version_bump_forces_re_acceptance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _ready_tenant()
    await verify_kyc_and_pledge_for_tests(tenant_id)
    _allowed_or_hours(await _dial(tenant_id, agent_id))
    monkeypatch.setattr(outbound_pledge, "PLEDGE_VERSION", outbound_pledge.PLEDGE_VERSION + 1)
    decision = await _dial(tenant_id, agent_id)
    assert decision.rule == outbound_pledge.PLEDGE_OUTDATED_RULE


async def test_a_required_digilocker_blocks_outbound_until_a_later_run() -> None:
    tenant_id, agent_id = await _ready_tenant()
    await verify_kyc_and_pledge_for_tests(tenant_id)
    admin_id = await _admin_id()
    async with tenant_session(tenant_id) as session:
        await set_digilocker_requirement(
            session, tenant_id=tenant_id, required=True, reason="Deeper check", admin_id=admin_id
        )
    blocked = await _dial(tenant_id, agent_id)
    assert blocked.rule == "kyc_digilocker_required"
    assert "inbound" in (blocked.reason or "").lower()

    # A run that completed BEFORE the requirement does not satisfy it.
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE kyc_records SET digilocker_verified_at = digilocker_required_at - "
                "interval '1 day' WHERE tenant_id = :tid"
            ),
            {"tid": tenant_id},
        )
    assert (await _dial(tenant_id, agent_id)).rule == "kyc_digilocker_required"

    async with tenant_session(tenant_id) as session:
        await record_digilocker_completion(
            session,
            tenant_id=tenant_id,
            verified_name="Ravi Kumar",
            owner_id_type="aadhaar",
            owner_id_masked="XXXX-XXXX-1234",
        )
    _allowed_or_hours(await _dial(tenant_id, agent_id))


async def test_the_admin_requires_and_clears_digilocker_and_both_are_audited() -> None:
    tenant_id, agent_id = await _ready_tenant()
    await verify_kyc_and_pledge_for_tests(tenant_id)
    admin = await _admin_headers()
    path = f"/v1/admin/tenants/{tenant_id}/kyc/digilocker-requirement"
    async with _client() as http:
        no_reason = await http.post(path, headers=admin, json={"required": True})
        assert no_reason.status_code == 422
        set_it = await http.post(
            path, headers=admin, json={"required": True, "reason": "Name mismatch"}
        )
        assert set_it.status_code == 200, set_it.text
        assert set_it.json()["digilocker_outstanding"] is True
        assert (await _dial(tenant_id, agent_id)).rule == "kyc_digilocker_required"
        cleared = await http.post(path, headers=admin, json={"required": False})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["digilocker_required"] is False
    _allowed_or_hours(await _dial(tenant_id, agent_id))
    async with tenant_session(tenant_id) as session:
        actions = (
            (
                await session.execute(
                    text(
                        "SELECT action FROM audit_log WHERE tenant_id = :tid "
                        "AND action LIKE 'kyc.digilocker%' ORDER BY created_at"
                    ),
                    {"tid": tenant_id},
                )
            )
            .scalars()
            .all()
        )
    assert actions == ["kyc.digilocker_required", "kyc.digilocker_cleared"]


async def test_the_requirement_route_404s_a_tenant_that_does_not_exist() -> None:
    async with _client() as http:
        response = await http.post(
            f"/v1/admin/tenants/{uuid.uuid4()}/kyc/digilocker-requirement",
            headers=await _admin_headers(),
            json={"required": False},
        )
    assert response.status_code == 404


async def test_inbound_is_never_gated_by_kyc_pledge_or_digilocker() -> None:
    """An inbound agent stops at `agent_inbound_only` before any of D-692's rules, even
    with every one of them unmet and an admin's DigiLocker requirement outstanding."""
    org = await _tenant()
    tenant_id = UUID(str(org["id"]))
    agent_id = await _agent(tenant_id, direction="inbound")
    async with tenant_session(tenant_id) as session:
        await set_digilocker_requirement(
            session,
            tenant_id=tenant_id,
            required=True,
            reason="Deeper check",
            admin_id=await _admin_id(),
        )
    decision = await _dial(tenant_id, agent_id)
    assert decision.rule == "agent_inbound_only"


async def test_the_launch_preview_names_kyc_and_the_pledge_and_no_dlt_rule() -> None:
    from apps.api.campaigns import service as campaigns

    org = await _tenant()
    tenant_id = UUID(str(org["id"]))
    agent_id = await _agent(tenant_id)
    campaign_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, classification, "
                "  status, created_at, updated_at) "
                "VALUES (:id, :tid, :aid, 'Offers', 'promotional', 'draft', now(), now())"
            ),
            {"id": campaign_id, "tid": tenant_id, "aid": agent_id},
        )
        rules = {
            b.rule
            for b in await campaigns.launch_blockers(
                session, tenant_id=tenant_id, campaign_id=campaign_id
            )
        }
    assert {"kyc_missing", "outbound_pledge_missing"} <= rules
    assert not rules & {
        "dlt_template_missing",
        "number_missing",
        "number_not_registered",
        "number_series_mismatch",
        "tm_registration_missing",
        "pe_registration_missing",
    }


async def test_a_service_campaign_on_a_verified_account_needs_no_dlt_paperwork() -> None:
    from apps.api.campaigns import service as campaigns

    tenant_id, agent_id = await _ready_tenant()
    await verify_kyc_and_pledge_for_tests(tenant_id)
    campaign_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, classification, "
                "  status, consent_source, consent_collected_at, created_at, updated_at) "
                "VALUES (:id, :tid, :aid, 'Reminders', 'service', 'draft', "
                "  'existing_customer', now() - interval '1 day', now(), now())"
            ),
            {"id": campaign_id, "tid": tenant_id, "aid": agent_id},
        )
        rules = {
            b.rule
            for b in await campaigns.launch_blockers(
                session, tenant_id=tenant_id, campaign_id=campaign_id
            )
        }
    # Only "no contacts" is left — the list is empty — and nothing about KYC, the pledge
    # or DLT.
    assert rules == {"no_contacts"}, rules


# ============================================================================ the pledge


async def test_the_pledge_route_reads_accepts_and_refuses_a_stale_screen() -> None:
    org = await _tenant()
    tenant_id = UUID(str(org["id"]))
    headers = await _headers(org)
    async with _client() as http:
        before = await http.get(PLEDGE, headers=headers)
        assert before.status_code == 200
        assert before.json()["is_current"] is False
        assert before.json()["text_sha256"] == outbound_pledge.PLEDGE_TEXT_SHA256
        stale = await http.post(
            PLEDGE,
            headers=headers,
            json={"version": outbound_pledge.PLEDGE_VERSION, "text_sha256": "0" * 64},
        )
        assert stale.status_code == 422
        assert stale.json()["type"].endswith("outbound_pledge_version_stale")
        accepted = await http.post(
            PLEDGE,
            headers=headers,
            json={
                "version": outbound_pledge.PLEDGE_VERSION,
                "text_sha256": outbound_pledge.PLEDGE_TEXT_SHA256,
            },
        )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["is_current"] is True
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT pledge_version, text_sha256, accepted_by_user_id FROM "
                    "outbound_pledge_acceptances WHERE tenant_id = :tid"
                ),
                {"tid": tenant_id},
            )
        ).one()
        audited = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE tenant_id = :tid "
                    "AND action = 'outbound_pledge.accepted'"
                ),
                {"tid": tenant_id},
            )
        ).scalar_one()
    assert row[0] == outbound_pledge.PLEDGE_VERSION
    assert row[1] == outbound_pledge.PLEDGE_TEXT_SHA256
    assert row[2] is not None
    assert audited == 1


async def test_an_operator_cannot_accept_the_pledge_for_a_client() -> None:
    from apps.api.compliance.outbound_pledge_routes import OutboundPledgeIn, accept_outbound_pledge
    from apps.api.core.context import Principal

    org = await _tenant()
    tenant_id = UUID(str(org["id"]))
    operator = Principal(
        user_id=await _admin_id(), tenant_id=tenant_id, role="owner", realm="admin"
    )
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as refused:
            await accept_outbound_pledge(
                OutboundPledgeIn(
                    version=outbound_pledge.PLEDGE_VERSION,
                    text_sha256=outbound_pledge.PLEDGE_TEXT_SHA256,
                ),
                _Request(),
                session,
                operator,
            )
    assert refused.value.code == "outbound_pledge_is_the_clients_own_act"


class _Request:
    """The two attributes `client_request_ip` reads."""

    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.client = None


async def test_a_pledge_acceptance_cannot_be_edited() -> None:
    tenant_id, _ = await _ready_tenant()
    await verify_kyc_and_pledge_for_tests(tenant_id)
    with pytest.raises(DBAPIError):
        async with tenant_session(tenant_id) as session:
            await session.execute(text("UPDATE outbound_pledge_acceptances SET pledge_version = 9"))


def test_the_pledge_hash_is_pinned_to_its_version() -> None:
    assert outbound_pledge.PLEDGE_VERSION in PINNED_PLEDGE_HASHES
    assert (
        PINNED_PLEDGE_HASHES[outbound_pledge.PLEDGE_VERSION] == outbound_pledge.PLEDGE_TEXT_SHA256
    )


# ============================================================================ the files


def test_uploads_are_checked_by_bytes_size_and_name() -> None:
    assert accept_upload(filename="gst.PDF", data=PDF_BYTES).content_type == "application/pdf"
    assert accept_upload(filename="id.jpeg", data=b"\xff\xd8\xff\xe0rest").suffix == "jpg"
    for filename, data, code in (
        ("gst.pdf", b"", "kyc_document_empty"),
        ("gst.pdf", b"%PDF-" + b"0" * (5 * 1024 * 1024), "kyc_document_too_large"),
        ("///", PDF_BYTES, "kyc_document_filename_required"),
        ("a" * 100 + ".pdf", PDF_BYTES, "kyc_document_filename_too_long"),
        ("gst.docx", PDF_BYTES, "kyc_document_type_unsupported"),
        ("gst.png", PDF_BYTES, "kyc_document_content_mismatch"),
    ):
        with pytest.raises(ProblemError) as refused:
            accept_upload(filename=filename, data=data)
        assert refused.value.code == code


def test_ids_are_masked_and_never_kept_whole() -> None:
    assert mask_pan("abcde1234f") == "XXXXX1234X"
    assert mask_aadhaar("1234") == "XXXX-XXXX-1234"
    for bad in ("ABCD1234F", "1234567890"):
        with pytest.raises(ProblemError):
            mask_pan(bad)
    for bad in ("123456789012", "12a4"):
        with pytest.raises(ProblemError):
            mask_aadhaar(bad)
    with pytest.raises(ValueError):
        VerificationOutcome(provider_ref="r", verified=True, masked_id="123456789012")
    with pytest.raises(ValueError):
        VerificationOutcome(provider_ref="r", verified=True, masked_id="ABCDE1234F")


def test_a_sealed_document_opens_only_under_its_own_tenant_and_row() -> None:
    tenant, other, document = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    context = f"kyc_document:{tenant}:{document}"
    sealed = seal_bytes(PDF_BYTES, context=context)
    assert sealed.ciphertext != PDF_BYTES
    assert unseal_bytes(sealed, context=context) == PDF_BYTES
    assert open_document(tenant_id=tenant, document_id=document, envelope=sealed) == PDF_BYTES
    with pytest.raises(ProblemError):
        open_document(tenant_id=other, document_id=document, envelope=sealed)


def test_names_match_is_tolerant_of_order_and_case_and_strict_on_people() -> None:
    assert names_match("Ravi Kumar", "KUMAR RAVI") is True
    assert names_match("Ravi Kumar", "Ravi Kumar Reddy") is True
    assert names_match("Ravi Kumar", "Suresh Babu") is False
    assert names_match("Ravi", "Ravi Kumar") is False
    assert names_match(None, "Ravi") is None
    assert names_match("R", "Ravi") is False


async def test_the_upload_route_encrypts_and_replaces_and_the_client_reads_metadata(
    s3: FakeS3,
) -> None:
    org = await _tenant()
    tenant_id = UUID(str(org["id"]))
    headers = await _headers(org)
    async with _client() as http:
        first = await http.post(
            f"{KYC}/documents",
            headers=headers,
            data={"slot": "business", "kind": "udyam"},
            files={"file": ("udyam.pdf", PDF_BYTES, "application/pdf")},
        )
        assert first.status_code == 201, first.text
        second = await http.post(
            f"{KYC}/documents",
            headers=headers,
            data={"slot": "business", "kind": "udyam"},
            files={"file": ("udyam-new.pdf", PDF_BYTES, "application/octet-stream")},
        )
        assert second.status_code == 201, second.text
        wrong_kind = await http.post(
            f"{KYC}/documents",
            headers=headers,
            data={"slot": "owner_id", "kind": "passport"},
            files={"file": ("p.pdf", PDF_BYTES, "application/pdf")},
        )
        assert wrong_kind.status_code == 422
        read = await http.get(KYC, headers=headers)
    stored = [key for key in s3.objects if key.startswith(f"kyc-documents/{tenant_id}/")]
    # The replaced file was deleted after the commit; only the current one is held, and it
    # is ciphertext — the plain PDF is nowhere in the bucket.
    assert len(stored) == 1
    assert all(PDF_BYTES not in body for body in s3.objects.values())
    documents = read.json()["documents"]
    assert [(d["slot"], d["filename"], d["held"]) for d in documents] == [
        ("business", "udyam-new.pdf", True)
    ]
    async with tenant_session(tenant_id) as session:
        row = (await current_documents(session, tenant_id=tenant_id))["business"]
    assert (
        open_document(
            tenant_id=tenant_id, document_id=row.id, envelope=row.envelope(s3.objects[stored[0]])
        )
        == PDF_BYTES
    )


async def test_an_operator_cannot_upload_a_clients_documents() -> None:
    from apps.api.compliance.kyc_routes import upload_document
    from apps.api.core.context import Principal

    org = await _tenant()
    tenant_id = UUID(str(org["id"]))
    operator = Principal(
        user_id=await _admin_id(), tenant_id=tenant_id, role="owner", realm="admin"
    )
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as refused:
            await upload_document(
                _Request(),
                session,
                operator,
                None,
                "business",
                "gst",
                None,  # type: ignore[arg-type]
            )
    assert refused.value.code == "kyc_documents_are_the_clients_own"


async def _manual_submission(
    org: dict[str, Any], s3: FakeS3, *, id_type: str = "pan", number: str = "ABCDE1234F"
) -> dict[str, str]:
    headers = await _headers(org)
    owner_kind = "pan_card" if id_type == "pan" else "aadhaar"
    async with _client() as http:
        details = await http.put(
            f"{KYC}/details",
            headers=headers,
            json={
                "entity_type": "private_limited",
                "legal_business_name": "Two Paths Traders Private Limited",
                "gst_registered": True,
                "gstin": "36AABCT1234C1Z5",
                "owner_name": "Ravi Kumar",
            },
        )
        assert details.status_code == 200, details.text
        for slot, kind, name, body in (
            ("business", "gst", "gst.pdf", PDF_BYTES),
            ("owner_id", owner_kind, "id.png", PNG_BYTES),
        ):
            uploaded = await http.post(
                f"{KYC}/documents",
                headers=headers,
                data={"slot": slot, "kind": kind},
                files={"file": (name, body, "application/octet-stream")},
            )
            assert uploaded.status_code == 201, uploaded.text
        submitted = await http.post(
            f"{KYC}/submit",
            headers=headers,
            json={"owner_id_type": id_type, "owner_id_number": number},
        )
    assert submitted.status_code == 200, submitted.text
    return headers


async def test_the_manual_path_submits_reviews_and_deletes_the_owner_id(s3: FakeS3) -> None:
    org = await _tenant()
    tenant_id = UUID(str(org["id"]))
    await _manual_submission(org, s3)
    async with tenant_session(tenant_id) as session:
        record = await read_kyc(session, tenant_id=tenant_id)
    assert (record.status, record.kyc_path) == ("submitted", "manual")
    assert (record.owner_id_type, record.owner_id_masked) == ("pan", "XXXXX1234X")

    admin = await _admin_headers()
    async with _client() as http:
        queue = await http.get("/v1/admin/kyc/reviews", headers=admin)
        assert queue.status_code == 200, queue.text
        mine = [item for item in queue.json() if item["tenant_id"] == str(tenant_id)]
        assert mine and mine[0]["owner_id_type"] == "pan"
        detail = await http.get(f"/v1/admin/tenants/{tenant_id}/kyc", headers=admin)
        owner_doc = next(d for d in detail.json()["documents"] if d["slot"] == "owner_id")
        download = await http.get(
            f"/v1/admin/tenants/{tenant_id}/kyc/documents/{owner_doc['id']}", headers=admin
        )
        assert download.status_code == 200
        assert download.content == PNG_BYTES
        assert download.headers["content-disposition"].startswith("attachment")
        approved = await http.post(
            f"/v1/admin/tenants/{tenant_id}/kyc/review",
            headers=admin,
            json={"decision": "approve"},
        )
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["is_verified"] is True
    assert body["owner_id_masked"] == "XXXXX1234X"
    owner_after = next(d for d in body["documents"] if d["slot"] == "owner_id")
    assert owner_after["held"] is False
    held = [key for key in s3.objects if key.startswith(f"kyc-documents/{tenant_id}/")]
    assert len(held) == 1, "the owner's ID file is deleted; the business certificate stays"
    async with tenant_session(tenant_id) as session:
        record = await read_kyc(session, tenant_id=tenant_id)
        bundle = await numbering_submission_bundle(session, tenant_id=tenant_id)
    assert (record.document_kind, record.document_ref) == ("gstin", "36AABCT1234C1Z5")
    assert bundle is not None
    assert (bundle.legal_business_name, bundle.gst_registered, bundle.document_kind) == (
        "Two Paths Traders Private Limited",
        True,
        "gst",
    )
    assert bundle.object_key in s3.objects


async def test_a_rejection_needs_a_reason_and_also_deletes_the_owner_id(s3: FakeS3) -> None:
    org = await _tenant()
    tenant_id = UUID(str(org["id"]))
    await _manual_submission(org, s3, id_type="aadhaar", number="4321")
    admin = await _admin_headers()
    path = f"/v1/admin/tenants/{tenant_id}/kyc/review"
    async with _client() as http:
        no_reason = await http.post(path, headers=admin, json={"decision": "reject"})
        assert no_reason.status_code == 422
        rejected = await http.post(
            path, headers=admin, json={"decision": "reject", "reason": "Upload the masked copy"}
        )
        assert rejected.status_code == 200, rejected.text
        again = await http.post(path, headers=admin, json={"decision": "approve"})
    assert again.status_code == 422, "a decided record is not waiting for review"
    assert rejected.json()["owner_id_masked"] == "XXXX-XXXX-4321"
    assert rejected.json()["rejection_reason"] == "Upload the masked copy"
    assert not [
        k for k in s3.objects if k.startswith(f"kyc-documents/{tenant_id}/") and k.endswith(".png")
    ]


async def test_the_manual_submit_refuses_what_it_cannot_review(s3: FakeS3) -> None:
    org = await _tenant()
    headers = await _headers(org)
    async with _client() as http:
        nothing = await http.post(
            f"{KYC}/submit",
            headers=headers,
            json={"owner_id_type": "pan", "owner_id_number": "ABCDE1234F"},
        )
        assert nothing.json()["type"].endswith("kyc_details_missing")
        gst_without_number = await http.put(
            f"{KYC}/details",
            headers=headers,
            json={
                "entity_type": "llp",
                "legal_business_name": "Two Paths LLP",
                "gst_registered": True,
                "owner_name": "Ravi Kumar",
            },
        )
        assert gst_without_number.json()["type"].endswith("kyc_gstin_required")
        await http.put(
            f"{KYC}/details",
            headers=headers,
            json={
                "entity_type": "llp",
                "legal_business_name": "Two Paths LLP",
                "gst_registered": False,
                "owner_name": "Ravi Kumar",
            },
        )
        no_certificate = await http.post(
            f"{KYC}/submit",
            headers=headers,
            json={"owner_id_type": "pan", "owner_id_number": "ABCDE1234F"},
        )
        assert no_certificate.json()["type"].endswith("kyc_business_document_missing")
        await http.post(
            f"{KYC}/documents",
            headers=headers,
            data={"slot": "business", "kind": "gst"},
            files={"file": ("gst.pdf", PDF_BYTES, "application/pdf")},
        )
        gst_doc_not_registered = await http.post(
            f"{KYC}/submit",
            headers=headers,
            json={"owner_id_type": "pan", "owner_id_number": "ABCDE1234F"},
        )
        assert gst_doc_not_registered.json()["type"].endswith("kyc_business_document_kind_mismatch")
        await http.post(
            f"{KYC}/documents",
            headers=headers,
            data={"slot": "business", "kind": "incorporation"},
            files={"file": ("coi.pdf", PDF_BYTES, "application/pdf")},
        )
        no_owner = await http.post(
            f"{KYC}/submit",
            headers=headers,
            json={"owner_id_type": "pan", "owner_id_number": "ABCDE1234F"},
        )
        assert no_owner.json()["type"].endswith("kyc_owner_id_missing")
        await http.post(
            f"{KYC}/documents",
            headers=headers,
            data={"slot": "owner_id", "kind": "aadhaar"},
            files={"file": ("a.png", PNG_BYTES, "image/png")},
        )
        mismatch = await http.post(
            f"{KYC}/submit",
            headers=headers,
            json={"owner_id_type": "pan", "owner_id_number": "ABCDE1234F"},
        )
        assert mismatch.json()["type"].endswith("kyc_owner_id_type_mismatch")
        full_aadhaar = await http.post(
            f"{KYC}/submit",
            headers=headers,
            json={"owner_id_type": "aadhaar", "owner_id_number": "1234"},
        )
        assert full_aadhaar.status_code == 200, full_aadhaar.text
        locked = await http.put(
            f"{KYC}/details",
            headers=headers,
            json={
                "entity_type": "llp",
                "legal_business_name": "Renamed LLP",
                "gst_registered": False,
                "owner_name": "Ravi Kumar",
            },
        )
        assert locked.json()["type"].endswith("kyc_details_locked")
        twice = await http.post(
            f"{KYC}/submit",
            headers=headers,
            json={"owner_id_type": "aadhaar", "owner_id_number": "1234"},
        )
        assert twice.json()["type"].endswith("kyc_already_submitted")


async def test_an_owner_id_nobody_decided_on_is_deleted_after_thirty_days(s3: FakeS3) -> None:
    org = await _tenant()
    tenant_id = UUID(str(org["id"]))
    headers = await _headers(org)
    async with _client() as http:
        uploaded = await http.post(
            f"{KYC}/documents",
            headers=headers,
            data={"slot": "owner_id", "kind": "pan_card"},
            files={"file": ("pan.png", PNG_BYTES, "image/png")},
        )
    assert uploaded.status_code == 201
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE kyc_documents SET created_at = now() - interval '31 days' "
                "WHERE tenant_id = :tid"
            ),
            {"tid": tenant_id},
        )
    assert await purge_due_kyc_documents() >= 1
    assert not [k for k in s3.objects if k.startswith(f"kyc-documents/{tenant_id}/")]
    async with tenant_session(tenant_id) as session:
        owner = (await current_documents(session, tenant_id=tenant_id))["owner_id"]
    assert owner.purged_at is not None


async def _document_state(tenant_id: UUID, slot: str) -> list[tuple[bool, bool, bool]]:
    """(superseded, deletion requested, purged) for every row of a slot, oldest first."""
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT superseded_at IS NOT NULL, delete_requested_at IS NOT NULL, "
                    "purged_at IS NOT NULL FROM kyc_documents "
                    "WHERE tenant_id = :t AND slot = :s ORDER BY created_at, id"
                ),
                {"t": tenant_id, "s": slot},
            )
        ).all()
    return [(bool(r[0]), bool(r[1]), bool(r[2])) for r in rows]


async def test_a_decided_owner_id_whose_delete_failed_is_retried_and_then_purged(
    s3: FakeS3,
) -> None:
    org = await _tenant()
    tenant_id = UUID(str(org["id"]))
    await _manual_submission(org, s3)
    s3.fail = True
    async with _client() as http:
        approved = await http.post(
            f"/v1/admin/tenants/{tenant_id}/kyc/review",
            headers=await _admin_headers(),
            json={"decision": "approve"},
        )
    assert approved.status_code == 200, approved.text
    owner_after = next(d for d in approved.json()["documents"] if d["slot"] == "owner_id")
    assert owner_after["held"] is False, "a decided file is not offered for use"
    assert await _document_state(tenant_id, "owner_id") == [(False, True, False)], (
        "the delete failed, so the row must say requested and NOT purged"
    )
    assert any(k.endswith(".png") for k in s3.objects if f"/{tenant_id}/" in k)

    with pytest.raises(KycPurgeIncompleteError):
        await purge_due_kyc_documents()
    assert await _document_state(tenant_id, "owner_id") == [(False, True, False)]

    s3.fail = False
    assert await purge_due_kyc_documents() >= 1
    assert await _document_state(tenant_id, "owner_id") == [(False, True, True)]
    assert not [k for k in s3.objects if f"/{tenant_id}/" in k and k.endswith(".png")]


async def test_a_replaced_upload_whose_delete_failed_is_retried_by_the_sweep(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.workers import storage

    org = await _tenant()
    tenant_id = UUID(str(org["id"]))
    headers = await _headers(org)

    async def refuse(keys: Any) -> int:
        raise storage.StorageUnavailableError("down")

    async with _client() as http:
        for name in ("udyam.pdf", "udyam-new.pdf"):
            if name == "udyam-new.pdf":
                monkeypatch.setattr(storage, "delete_objects", refuse)
            uploaded = await http.post(
                f"{KYC}/documents",
                headers=headers,
                data={"slot": "business", "kind": "udyam"},
                files={"file": (name, PDF_BYTES, "application/pdf")},
            )
            assert uploaded.status_code == 201, uploaded.text
    monkeypatch.undo()
    monkeypatch.setattr(storage, "_client", lambda: s3)
    assert await _document_state(tenant_id, "business") == [
        (True, True, False),
        (False, False, False),
    ]
    assert len([k for k in s3.objects if f"/{tenant_id}/" in k]) == 2

    assert await purge_due_kyc_documents() >= 1
    assert await _document_state(tenant_id, "business") == [
        (True, True, True),
        (False, False, False),
    ]
    assert len([k for k in s3.objects if f"/{tenant_id}/" in k]) == 1, "the current file stays"


async def test_an_upload_whose_row_cannot_be_written_takes_its_object_down(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api.compliance import kyc_routes

    org = await _tenant()
    tenant_id = UUID(str(org["id"]))

    async def lost_the_race(*args: Any, **kwargs: Any) -> Any:
        raise ProblemError.conflict("kyc_document_raced", "Another upload won.")

    monkeypatch.setattr(kyc_routes, "record_document", lost_the_race)
    async with _client() as http:
        refused = await http.post(
            f"{KYC}/documents",
            headers=await _headers(org),
            data={"slot": "business", "kind": "udyam"},
            files={"file": ("udyam.pdf", PDF_BYTES, "application/pdf")},
        )
    assert refused.status_code == 409, refused.text
    assert not [k for k in s3.objects if f"/{tenant_id}/" in k], "no object without a row"
    assert await _document_state(tenant_id, "business") == []


async def test_the_business_certificate_is_destroyed_by_the_account_erasure(s3: FakeS3) -> None:
    org = await _tenant()
    tenant_id = UUID(str(org["id"]))
    headers = await _headers(org)
    async with _client() as http:
        uploaded = await http.post(
            f"{KYC}/documents",
            headers=headers,
            data={"slot": "business", "kind": "udyam"},
            files={"file": ("udyam.pdf", PDF_BYTES, "application/pdf")},
        )
    assert uploaded.status_code == 201
    assert [k for k in s3.objects if k.startswith(f"kyc-documents/{tenant_id}/")]
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET status = 'churned' WHERE id = :tid"),
            {"tid": tenant_id},
        )
    admin = await _admin_headers()
    async with _client() as http:
        filed = await http.post(
            f"/v1/admin/tenants/{tenant_id}/erasure",
            json={"reason": "Contract ended"},
            headers={
                **admin,
                "X-Confirm-Action": tenant_erasure.tenant_erasure_confirmation(tenant_id),
            },
        )
    assert filed.status_code == 201, filed.text
    await execute_tenant_erasure(
        {}, {"tenant_id": str(tenant_id), "request_id": filed.json()["request_id"]}
    )
    assert not [k for k in s3.objects if k.startswith(f"kyc-documents/{tenant_id}/")]
    prose = " ".join(tenant_erasure.TENANT_ERASURE_LIMITATIONS)
    assert "KYC" in prose


# ======================================================================== DigiLocker


@pytest.fixture
def _fake_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "kyc_verification_provider", "fake", raising=False)
    monkeypatch.setattr(settings, "kyc_verification_webhook_secret", SECRET, raising=False)


@pytest.mark.usefixtures("_fake_provider")
async def test_digilocker_needs_the_business_certificate_first() -> None:
    org = await _tenant()
    async with _client() as http:
        response = await http.post(
            f"{KYC}/verification",
            headers=await _headers(org),
            json={"entity_type": "sole_proprietorship", "id_document": "pan"},
        )
    assert response.json()["type"].endswith("kyc_details_missing")


@pytest.mark.usefixtures("_fake_provider")
async def test_the_return_leg_pulls_the_outcome_and_keeps_only_a_masked_id() -> None:
    org = await _tenant()
    tenant_id = UUID(str(org["id"]))
    await put_business_on_file_for_tests(tenant_id)
    headers = await _headers(org)
    async with _client() as http:
        started = await http.post(
            f"{KYC}/verification",
            headers=headers,
            json={"entity_type": "sole_proprietorship", "id_document": "pan"},
        )
        assert started.status_code == 200, started.text
        ref = started.json()["provider_ref"]
        pending = await http.post(
            f"{KYC}/verification/complete", headers=headers, json={"provider_ref": ref}
        )
        assert pending.json()["status"] == "pending"
        stage_outcome(
            VerificationOutcome(
                provider_ref=ref,
                verified=True,
                verified_name="Ravi Kumar",
                masked_id="XXXXX1234X",
            )
        )
        done = await http.post(
            f"{KYC}/verification/complete", headers=headers, json={"provider_ref": ref}
        )
        stranger = await http.post(
            f"{KYC}/verification/complete",
            headers=await _headers(await _tenant()),
            json={"provider_ref": ref},
        )
    assert done.status_code == 200, done.text
    record = done.json()["record"]
    assert record["is_verified"] is True
    assert (record["owner_id_type"], record["owner_id_masked"], record["name_match"]) == (
        "pan",
        "XXXXX1234X",
        True,
    )
    assert record["kyc_path"] == "digilocker"
    assert stranger.status_code == 404, "another account's run resolves to nothing"


@pytest.mark.usefixtures("_fake_provider")
async def test_a_verified_account_may_start_again_only_when_digilocker_is_required() -> None:
    org = await _tenant()
    tenant_id = UUID(str(org["id"]))
    await put_business_on_file_for_tests(tenant_id, entity_type="private_limited")
    await _verify_kyc_only(tenant_id)
    headers = await _headers(org)
    body = {"entity_type": "private_limited", "id_document": "aadhaar"}
    async with _client() as http:
        refused = await http.post(f"{KYC}/verification", headers=headers, json=body)
        assert refused.json()["type"].endswith("kyc_already_verified")
        async with tenant_session(tenant_id) as session:
            await set_digilocker_requirement(
                session,
                tenant_id=tenant_id,
                required=True,
                reason="Deeper check",
                admin_id=await _admin_id(),
            )
        started = await http.post(f"{KYC}/verification", headers=headers, json=body)
        assert started.status_code == 200, started.text
        ref = started.json()["provider_ref"]
        stage_outcome(
            VerificationOutcome(
                provider_ref=ref, verified=True, verified_name="A Signatory", masked_id=None
            )
        )
        done = await http.post(
            f"{KYC}/verification/complete", headers=headers, json={"provider_ref": ref}
        )
    record = done.json()["record"]
    # Still verified (the company record is not demoted by a signatory run), and the
    # requirement is now satisfied.
    assert record["is_verified"] is True
    assert record["digilocker_outstanding"] is False


# ------------------------------------------------------------------ Cashfree, on the wire


def _cashfree(handler: Any) -> CashfreeDigiLocker:
    return CashfreeDigiLocker(
        client_id="cf-id",
        client_secret="cf-secret",
        environment="sandbox",
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://sandbox.cashfree.com/verification",
        ),
    )


async def test_cashfree_start_requests_only_the_chosen_record() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"url": "https://digilocker.example/consent", "status": "PENDING"}
        )

    start = await _cashfree(handler).start(
        entity_type="sole_proprietorship",
        redirect_back_url="https://app.example/c/x/verification",
        id_document="pan",
    )
    assert seen["path"].endswith("/digilocker")
    assert seen["headers"]["x-client-id"] == "cf-id"
    assert seen["body"]["document_requested"] == ["PAN"]
    assert seen["body"]["verification_id"] == start.provider_ref
    assert len(start.provider_ref) <= 50
    assert start.redirect_url == "https://digilocker.example/consent"


async def test_cashfree_refusals_become_our_problem_not_a_raw_error() -> None:
    def refused(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "bad key"})

    def no_url(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "PENDING"})

    for handler in (refused, no_url):
        with pytest.raises(ProblemError) as raised:
            await _cashfree(handler).start(
                entity_type="llp", redirect_back_url="https://x", id_document="aadhaar"
            )
        assert raised.value.code == "verification_provider_refused"


@pytest.mark.parametrize(
    ("status", "expected"),
    [("PENDING", None), ("EXPIRED", "link_expired"), ("CONSENT_DENIED", "consent_denied")],
)
async def test_cashfree_status_maps_to_our_outcome(status: str, expected: str | None) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": status, "verification_id": "v1"})

    outcome = await _cashfree(handler).fetch_outcome(provider_ref="v1", id_document="aadhaar")
    if expected is None:
        assert outcome is None
    else:
        assert outcome is not None
        assert (outcome.verified, outcome.failure_reason) == (False, expected)


async def test_cashfree_aadhaar_and_pan_leave_only_a_name_and_a_masked_number() -> None:
    aadhaar_record = {
        "status": "SUCCESS",
        "uid": "xxxxxxxx5647",
        "name": "Mallesh Kumar",
        "dob": "02-02-1995",
        "split_address": {"state": "Karnataka", "pincode": "581115"},
        "photo_link": "https://x/photo",
    }
    pan_record = {"pan": "ABCPV1234D", "name_pan_card": "JOHN DOE", "dob": "02-02-1995"}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/AADHAAR"):
            return httpx.Response(200, json=aadhaar_record)
        if request.url.path.endswith("/PAN"):
            return httpx.Response(200, json=pan_record)
        return httpx.Response(200, json={"status": "AUTHENTICATED"})

    adapter = _cashfree(handler)
    aadhaar = await adapter.fetch_outcome(provider_ref="v1", id_document="aadhaar")
    pan = await adapter.fetch_outcome(provider_ref="v2", id_document="pan")
    assert aadhaar == VerificationOutcome(
        provider_ref="v1", verified=True, verified_name="Mallesh Kumar", masked_id="XXXX-XXXX-5647"
    )
    assert pan == VerificationOutcome(
        provider_ref="v2", verified=True, verified_name="JOHN DOE", masked_id="XXXXX1234X"
    )
    flattened = json.dumps([aadhaar.__repr__(), pan.__repr__()])
    for leaked in ("ABCPV1234D", "1995", "581115", "photo"):
        assert leaked not in flattened


async def test_cashfree_a_record_without_a_name_is_not_a_verification() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/document/" in request.url.path:
            return httpx.Response(200, json={"status": "SUCCESS", "uid": "xxxxxxxx1111"})
        return httpx.Response(200, json={"status": "AUTHENTICATED"})

    outcome = await _cashfree(handler).fetch_outcome(provider_ref="v", id_document="aadhaar")
    assert outcome is not None
    assert (outcome.verified, outcome.failure_reason) == (False, "document_unavailable")


def test_cashfree_webhooks_are_verified_the_documented_way_and_name_only_the_run() -> None:
    adapter = _cashfree(lambda request: httpx.Response(500))
    raw = json.dumps(
        {
            "event_type": "DIGILOCKER_VERIFICATION_SUCCESS",
            "data": {"verification_id": "clv-1", "status": "AUTHENTICATED"},
        }
    ).encode()
    good = {SIGNATURE_HEADER: sign(secret="cf-secret", timestamp="1746427759733", body=raw)}
    good[TIMESTAMP_HEADER] = "1746427759733"
    assert adapter.verify_webhook(raw=raw, headers=good) is True
    assert adapter.verify_webhook(raw=raw + b" ", headers=good) is False
    assert adapter.verify_webhook(raw=raw, headers={SIGNATURE_HEADER: "x"}) is False
    assert adapter.webhook_is_authoritative is False
    assert adapter.parse_outcome(raw=raw).provider_ref == "clv-1"
    with pytest.raises(ValueError):
        adapter.parse_outcome(raw=b"{}")


def test_cashfree_needs_both_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "kyc_verification_provider", "cashfree", raising=False)
    monkeypatch.setattr(settings, "kyc_verification_client_id", "cf-id", raising=False)
    monkeypatch.setattr(settings, "kyc_verification_client_secret", None, raising=False)
    assert available_provider().reason == NO_API_CREDENTIALS
    monkeypatch.setattr(settings, "kyc_verification_client_secret", "cf-secret", raising=False)
    capability = available_provider()
    assert capability.available
    assert capability.provider is not None and capability.provider.name == "cashfree"


async def test_a_signed_cashfree_doorbell_pulls_and_persists_none_of_the_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The webhook names the run; the outcome comes from our authenticated pull, and none
    of the fetched record (DOB, full PAN) reaches a row."""
    settings = get_settings()
    monkeypatch.setattr(settings, "kyc_verification_provider", "cashfree", raising=False)
    monkeypatch.setattr(settings, "kyc_verification_client_id", "cf-id", raising=False)
    monkeypatch.setattr(settings, "kyc_verification_client_secret", "cf-secret", raising=False)

    async def fetch(self: Any, *, provider_ref: str, id_document: str) -> VerificationOutcome:
        assert id_document == "pan"
        return VerificationOutcome(
            provider_ref=provider_ref,
            verified=True,
            verified_name="Ravi Kumar",
            masked_id="XXXXX4321X",
        )

    monkeypatch.setattr(CashfreeDigiLocker, "fetch_outcome", fetch)
    org = await _tenant()
    tenant_id = UUID(str(org["id"]))
    await put_business_on_file_for_tests(tenant_id)
    ref = "clv-" + uuid.uuid4().hex
    from apps.api.compliance.kyc_verification import open_request

    async with tenant_session(tenant_id) as session:
        await open_request(
            session,
            tenant_id=tenant_id,
            provider="cashfree",
            provider_ref=ref,
            entity_type="sole_proprietorship",
            id_document="pan",
        )
    raw = json.dumps({"data": {"verification_id": ref, "status": "AUTHENTICATED"}}).encode()
    async with _client() as http:
        unsigned = await http.post("/hooks/v1/kyc/cashfree", content=raw)
        assert unsigned.status_code == 401
        delivered = await http.post(
            "/hooks/v1/kyc/cashfree",
            content=raw,
            headers={
                SIGNATURE_HEADER: sign(secret="cf-secret", timestamp="17", body=raw),
                TIMESTAMP_HEADER: "17",
            },
        )
    assert delivered.status_code == 200, delivered.text
    assert delivered.json()["status"] == "applied"
    async with tenant_session(tenant_id) as session:
        record = await read_kyc(session, tenant_id=tenant_id)
        dumped = json.dumps(
            [
                str(value)
                for value in (
                    await session.execute(
                        text("SELECT * FROM kyc_records WHERE tenant_id = :tid"), {"tid": tenant_id}
                    )
                ).one()
            ]
        )
    assert record.is_verified
    assert record.owner_id_masked == "XXXXX4321X"
    assert "1995" not in dumped


# ======================================================================= hard rule 1


async def test_tenant_b_sees_none_of_tenant_as_documents_or_pledges() -> None:
    org_a, org_b = await _tenant(), await _tenant()
    tenant_a, tenant_b = UUID(str(org_a["id"])), UUID(str(org_b["id"]))
    await put_business_on_file_for_tests(tenant_a)
    await verify_kyc_and_pledge_for_tests(tenant_a)
    async with tenant_session(tenant_b) as session:
        documents = (
            await session.execute(
                text("SELECT count(*) FROM kyc_documents WHERE tenant_id = :a"), {"a": tenant_a}
            )
        ).scalar_one()
        pledges = (
            await session.execute(
                text("SELECT count(*) FROM outbound_pledge_acceptances WHERE tenant_id = :a"),
                {"a": tenant_a},
            )
        ).scalar_one()
    assert (documents, pledges) == (0, 0)
    async with _client() as http:
        read = await http.get(KYC, headers=await _headers(org_b))
        download = await http.get(f"{KYC}/documents", headers=await _headers(org_b))
    assert read.json()["documents"] == []
    assert download.status_code in (404, 405)


async def test_the_untenanted_read_arms_reach_only_what_they_were_written_for() -> None:
    """The purge sweep sees held owner-ID rows and nothing else; the review queue sees
    records awaiting review and nothing else; a session scoped to another tenant sees
    neither."""
    org = await _tenant()
    tenant_id = UUID(str(org["id"]))
    await put_business_on_file_for_tests(tenant_id)
    await _verify_kyc_only(tenant_id)
    async with untenanted_session() as session:
        business = (
            await session.execute(
                text("SELECT count(*) FROM kyc_documents WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar_one()
        verified = (
            await session.execute(
                text("SELECT count(*) FROM kyc_records WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar_one()
    assert (business, verified) == (0, 0)


async def test_a_kek_rotation_rewraps_kyc_files_and_they_still_open() -> None:
    """The tenant rewrap walk covers the KYC files' envelopes, so a certificate sealed
    under the outgoing key still opens once that key is retired and gone."""
    import base64

    from apps.api.compliance.kyc_documents import (
        document_context,
        new_document_id,
        record_document,
    )
    from apps.api.core.envelope import build_ring
    from apps.api.ops.secret_service import (
        count_tenant_credential_keks,
        rewrap_tenant_credentials,
    )

    def ring(active: bytes, retired: bytes | None = None) -> Any:
        def encode(seed: bytes) -> str:
            return base64.b64encode(seed * 32).decode()

        return build_ring(
            kek=encode(active), retired=encode(retired) if retired else None, app_env="prod"
        )

    org = await _tenant()
    tenant_id = UUID(str(org["id"]))
    owner = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:id, :e, now(), now())"
            ),
            {"id": owner, "e": f"{owner}@example.com"},
        )
    document_id = new_document_id()
    context = document_context(tenant_id, document_id)
    sealed = seal_bytes(PDF_BYTES, context=context, ring=ring(b"\x71"))
    async with tenant_session(tenant_id) as session:
        await record_document(
            session,
            tenant_id=tenant_id,
            document_id=document_id,
            slot="business",
            kind="udyam",
            object_key=f"kyc-documents/{tenant_id}/{document_id}.pdf",
            accepted=accept_upload(filename="udyam.pdf", data=PDF_BYTES),
            sealed=sealed,
            uploaded_by_user_id=owner,
        )

    rotating = ring(b"\x72", retired=b"\x71")
    before = await count_tenant_credential_keks(ring=rotating, tenant_ids=[tenant_id])
    assert (before.total, before.pending) == (1, 1), "the progress count includes KYC files"
    moved = await rewrap_tenant_credentials(ring=rotating, tenant_ids=[tenant_id])
    settled = await count_tenant_credential_keks(ring=rotating, tenant_ids=[tenant_id])
    assert (settled.total, settled.pending) == (1, 0)
    assert moved.unreadable == ()
    assert moved.rewrapped >= 1
    async with tenant_session(tenant_id) as session:
        after = (await current_documents(session, tenant_id=tenant_id))["business"]
    assert after.dek_wrapped != sealed.dek_wrapped
    assert unseal_bytes(after.envelope(sealed.ciphertext), context=context, ring=ring(b"\x72")) == (
        PDF_BYTES
    )


async def test_cashfree_ip_validation_failure_is_an_operator_fix_with_its_own_alarm() -> None:
    """`ip_validation_failed` means our server's IPv4 is not on the account's allow-list
    (Cashfree IP whitelisting page, 8 Oct 2026), so it maps to its own code, which the
    alarm index tells an operator how to clear; and the adapter never sends a signature."""
    from apps.api.core.alarm_severity import ALARM_SEVERITY

    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = dict(request.headers)
        return httpx.Response(403, json={"code": "ip_validation_failed", "message": "IP"})

    with pytest.raises(ProblemError) as raised:
        await _cashfree(handler).start(
            entity_type="llp", redirect_back_url="https://x", id_document="pan"
        )
    assert raised.value.code == "verification_provider_ip_not_whitelisted"
    assert ALARM_SEVERITY["verification_provider_ip_not_whitelisted"] == "attention"
    assert "x-cf-signature" not in seen["headers"]
