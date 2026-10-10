"""Refusals on the D-692..D-699 compliance surfaces that the path tests do not reach: the
KYC record's locks and mismatches, the files a reviewer or client can no longer open, a
review with nothing to approve against, a doorbell with no result yet, the dispute pause
in the dial gate, the DLT entity list, and the engine DNC push with nothing to push."""

from __future__ import annotations

import json
import uuid
from typing import Any
from uuid import UUID

import pytest
from apps.api.billing.dispute_hold import DISPUTE_HOLD_REASON
from apps.api.compliance import engine_dnc, registration
from apps.api.compliance.kyc import (
    numbering_submission_bundle,
    read_kyc,
    record_kyc,
    save_business_details,
    submit_for_manual_review,
)
from apps.api.compliance.kyc_providers.cashfree import (
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    CashfreeDigiLocker,
    sign,
)
from apps.api.compliance.kyc_review import decide_kyc_review
from apps.api.compliance.kyc_routes import _discard_unrecorded_upload, _kyc_writer
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from sqlalchemy import text
from tests.conftest import PDF_BYTES, FakeS3, arm_agent_for_outbound
from tests.kyc_two_paths_test import (
    KYC,
    PNG_BYTES,
    _admin_headers,
    _admin_id,
    _client,
    _headers,
    _manual_submission,
    _tenant,
    _verify_kyc_only,
)
from tests.outbound_registration_gate_test import _gate, _tenant_agent
from tests.workspace_support import give_own_workspace

pytestmark = [pytest.mark.rls]

_DETAILS = {
    "entity_type": "llp",
    "legal_business_name": "Edge Traders LLP",
    "gst_registered": False,
    "owner_name": "Ravi Kumar",
}


# --- the client's declaration ----------------------------------------------------------


async def test_details_with_an_unknown_entity_type_or_a_numeric_owner_are_refused() -> None:
    org = await _tenant()
    headers = await _headers(org)
    async with _client() as http:
        unknown = await http.put(
            f"{KYC}/details", headers=headers, json={**_DETAILS, "entity_type": "guild"}
        )
        numeric = await http.put(
            f"{KYC}/details", headers=headers, json={**_DETAILS, "owner_name": "ABCDE1234F"}
        )
    assert unknown.json()["type"].endswith("unknown_entity_type")
    assert numeric.json()["type"].endswith("kyc_owner_name_invalid")
    async with tenant_session(UUID(str(org["id"]))) as session:
        assert (await read_kyc(session, tenant_id=UUID(str(org["id"])))).legal_business_name is None


async def test_an_aggregator_record_keeps_the_entity_type_it_was_run_for() -> None:
    org = await _tenant()
    tenant_id = UUID(str(org["id"]))
    async with tenant_session(tenant_id) as session:
        # A DigiLocker run for a company that our reviewer then rejected: editable again,
        # but the run's branch was taken from "private_limited".
        await record_kyc(
            session,
            tenant_id=tenant_id,
            status="rejected",
            entity_type="private_limited",
            verification_source="aggregator",
            verification_provider="fake",
            verification_reference="clv-run-1",
            verified_name="A Signatory",
            rejection_reason="The registry entry does not match",
        )
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as refused:
            await save_business_details(
                session,
                tenant_id=tenant_id,
                entity_type="llp",
                legal_business_name="Edge Traders LLP",
                gst_registered=False,
                gstin=None,
                owner_name="Ravi Kumar",
            )
    assert refused.value.code == "entity_type_on_file_differs"
    async with tenant_session(tenant_id) as session:
        await save_business_details(
            session,
            tenant_id=tenant_id,
            entity_type="private_limited",
            legal_business_name="Edge Traders Private Limited",
            gst_registered=False,
            gstin=None,
            owner_name="Ravi Kumar",
        )
        assert (await read_kyc(session, tenant_id=tenant_id)).legal_business_name == (
            "Edge Traders Private Limited"
        )


async def test_a_writer_outside_any_tenant_is_not_asked_about_a_trial() -> None:
    operator = Principal(realm="admin", user_id=uuid.uuid4(), tenant_id=None, role="operator")
    assert await _kyc_writer(operator, None) is operator  # type: ignore[arg-type]


# --- documents ------------------------------------------------------------------------


async def test_documents_with_the_review_team_cannot_be_replaced(s3: FakeS3) -> None:
    org = await _tenant()
    headers = await _manual_submission(org, s3)
    async with _client() as http:
        replace = await http.post(
            f"{KYC}/documents",
            headers=headers,
            data={"slot": "business", "kind": "gst"},
            files={"file": ("gst2.pdf", PDF_BYTES, "application/pdf")},
        )
    assert replace.json()["type"].endswith("kyc_documents_locked")
    assert "review team" in replace.json()["detail"]


async def test_a_verified_business_cannot_submit_again() -> None:
    org = await _tenant()
    await _verify_kyc_only(UUID(str(org["id"])))
    async with _client() as http:
        again = await http.post(
            f"{KYC}/submit",
            headers=await _headers(org),
            json={"owner_id_type": "pan", "owner_id_number": "ABCDE1234F"},
        )
    assert again.json()["type"].endswith("kyc_already_verified")


async def test_a_gst_registered_business_must_send_its_gst_certificate(s3: FakeS3) -> None:
    org = await _tenant()
    headers = await _headers(org)
    async with _client() as http:
        await http.put(
            f"{KYC}/details",
            headers=headers,
            json={**_DETAILS, "gst_registered": True, "gstin": "36AABCT1234C1Z5"},
        )
        await http.post(
            f"{KYC}/documents",
            headers=headers,
            data={"slot": "business", "kind": "udyam"},
            files={"file": ("udyam.pdf", PDF_BYTES, "application/pdf")},
        )
        submitted = await http.post(
            f"{KYC}/submit",
            headers=headers,
            json={"owner_id_type": "pan", "owner_id_number": "ABCDE1234F"},
        )
    assert submitted.json()["type"].endswith("kyc_business_document_kind_mismatch")
    assert "GST certificate" in submitted.json()["detail"]


async def test_a_certificate_whose_object_is_gone_is_not_found_for_client_and_reviewer(
    s3: FakeS3,
) -> None:
    org = await _tenant()
    tenant_id = UUID(str(org["id"]))
    headers = await _headers(org)
    admin = await _admin_headers()
    async with _client() as http:
        uploaded = await http.post(
            f"{KYC}/documents",
            headers=headers,
            data={"slot": "business", "kind": "udyam"},
            files={"file": ("udyam.pdf", PDF_BYTES, "application/pdf")},
        )
        assert uploaded.status_code == 201, uploaded.text
        document_id = uploaded.json()["id"]
        for key in [k for k in s3.objects if k.startswith(f"kyc-documents/{tenant_id}/")]:
            del s3.objects[key]
        own = await http.get(f"{KYC}/documents/{document_id}", headers=headers)
        reviewer = await http.get(
            f"/v1/admin/tenants/{tenant_id}/kyc/documents/{document_id}", headers=admin
        )
        unknown = await http.get(
            f"/v1/admin/tenants/{tenant_id}/kyc/documents/{uuid.uuid4()}", headers=admin
        )
    assert (own.status_code, reviewer.status_code, unknown.status_code) == (404, 404, 404)


async def test_a_reviewed_owner_id_is_no_longer_handed_to_the_reviewer(s3: FakeS3) -> None:
    org = await _tenant()
    tenant_id = UUID(str(org["id"]))
    await _manual_submission(org, s3)
    admin = await _admin_headers()
    async with _client() as http:
        detail = await http.get(f"/v1/admin/tenants/{tenant_id}/kyc", headers=admin)
        owner = next(d for d in detail.json()["documents"] if d["slot"] == "owner_id")
        decided = await http.post(
            f"/v1/admin/tenants/{tenant_id}/kyc/review",
            headers=admin,
            json={"decision": "reject", "reason": "The PAN card is unreadable"},
        )
        assert decided.status_code == 200, decided.text
        gone = await http.get(
            f"/v1/admin/tenants/{tenant_id}/kyc/documents/{owner['id']}", headers=admin
        )
    assert gone.status_code == 404


async def test_an_upload_whose_row_was_never_written_logs_a_delete_that_failed(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from apps.workers import storage

    async def _down(keys: list[str]) -> None:
        raise storage.StorageUnavailableError("store unreachable")

    monkeypatch.setattr(storage, "delete_objects", _down)
    document_id = uuid.uuid4()
    with caplog.at_level("ERROR"):
        await _discard_unrecorded_upload("kyc-documents/t/x.pdf", document_id=document_id)
    assert any(r.getMessage() == "kyc_unrecorded_upload_left" for r in caplog.records)


# --- the reviewer's decision ------------------------------------------------------------


async def _submitted_without_documents(tenant_id: UUID) -> None:
    async with tenant_session(tenant_id) as session:
        await save_business_details(
            session,
            tenant_id=tenant_id,
            entity_type="llp",
            legal_business_name="Edge Traders LLP",
            gst_registered=False,
            gstin=None,
            owner_name="Ravi Kumar",
        )
        await submit_for_manual_review(
            session, tenant_id=tenant_id, owner_id_type="pan", owner_id_masked="XXXXX1234X"
        )


async def test_approving_with_no_certificate_on_file_is_refused() -> None:
    org = await _tenant()
    tenant_id = UUID(str(org["id"]))
    await _submitted_without_documents(tenant_id)
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as refused:
            await decide_kyc_review(
                session,
                tenant_id=tenant_id,
                decision="approve",
                document_ref="AAA-1234",
                reason=None,
                pan_checked=True,
                admin_id=await _admin_id(),
            )
    assert refused.value.code == "kyc_business_document_missing"


async def test_an_llp_is_approved_against_its_llpin_and_needs_the_number(s3: FakeS3) -> None:
    org = await _tenant()
    tenant_id = UUID(str(org["id"]))
    headers = await _headers(org)
    async with _client() as http:
        await http.put(f"{KYC}/details", headers=headers, json=_DETAILS)
        for slot, kind, name, body in (
            ("business", "incorporation", "coi.pdf", PDF_BYTES),
            ("owner_id", "pan_card", "pan.png", PNG_BYTES),
        ):
            uploaded = await http.post(
                f"{KYC}/documents",
                headers=headers,
                data={"slot": slot, "kind": kind},
                files={"file": (name, body, "application/octet-stream")},
            )
            assert uploaded.status_code == 201, uploaded.text
        sent = await http.post(
            f"{KYC}/submit",
            headers=headers,
            json={"owner_id_type": "pan", "owner_id_number": "ABCDE1234F"},
        )
        assert sent.status_code == 200, sent.text
        admin = await _admin_headers()
        path = f"/v1/admin/tenants/{tenant_id}/kyc/review"
        no_number = await http.post(
            path, headers=admin, json={"decision": "approve", "pan_checked": True}
        )
        approved = await http.post(
            path,
            headers=admin,
            json={"decision": "approve", "pan_checked": True, "document_ref": "AAB-1234"},
        )
    assert no_number.json()["type"].endswith("kyc_document_required")
    assert approved.status_code == 200, approved.text
    async with tenant_session(tenant_id) as session:
        record = await read_kyc(session, tenant_id=tenant_id)
    assert (record.document_kind, record.document_ref) == ("llpin", "AAB-1234")


async def test_a_review_after_the_owner_id_was_already_purged_queues_no_delete(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api.compliance import kyc_admin_routes

    deletes: list[Any] = []

    async def _record(tenant_id: UUID, pending: list[Any]) -> None:
        deletes.append(pending)

    monkeypatch.setattr(kyc_admin_routes, "delete_requested_documents", _record)
    org = await _tenant()
    tenant_id = UUID(str(org["id"]))
    await _manual_submission(org, s3)
    # The 30-day sweep got there first: the file is gone before anybody decided.
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE kyc_documents SET delete_requested_at = now(), purged_at = now() "
                "WHERE tenant_id = :t AND slot = 'owner_id' AND superseded_at IS NULL"
            ),
            {"t": tenant_id},
        )
    async with _client() as http:
        decided = await http.post(
            f"/v1/admin/tenants/{tenant_id}/kyc/review",
            headers=await _admin_headers(),
            json={"decision": "reject", "reason": "Please send a clearer copy"},
        )
    assert decided.status_code == 200, decided.text
    assert decided.json()["rejection_reason"] == "Please send a clearer copy"
    assert deletes == [], "nothing is held, so nothing is queued for deletion"


# --- the numbering bundle ---------------------------------------------------------------


async def test_no_bundle_without_a_gst_status_or_a_certificate() -> None:
    org = await _tenant()
    tenant_id = UUID(str(org["id"]))
    async with tenant_session(tenant_id) as session:
        await save_business_details(
            session,
            tenant_id=tenant_id,
            entity_type="private_limited",
            legal_business_name="Edge Traders Private Limited",
            gst_registered=False,
            gstin=None,
            owner_name="Ravi Kumar",
        )
    await _verify_kyc_only(tenant_id)
    async with tenant_session(tenant_id) as session:
        assert (await read_kyc(session, tenant_id=tenant_id)).is_verified
        assert await numbering_submission_bundle(session, tenant_id=tenant_id) is None, (
            "no certificate on file"
        )
        await session.execute(
            text("UPDATE kyc_records SET gst_registered = NULL WHERE tenant_id = :t"),
            {"t": tenant_id},
        )
        assert await numbering_submission_bundle(session, tenant_id=tenant_id) is None, (
            "no GST status on file"
        )


# --- DigiLocker -----------------------------------------------------------------------


async def test_the_return_leg_is_refused_when_no_provider_is_configured() -> None:
    org = await _tenant()
    async with _client() as http:
        response = await http.post(
            f"{KYC}/verification/complete",
            headers=await _headers(org),
            json={"provider_ref": "clv-" + uuid.uuid4().hex},
        )
    assert response.json()["type"].endswith("self_verification_unavailable")


async def test_a_doorbell_for_a_run_with_no_result_yet_is_acknowledged_as_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.compliance.kyc_verification import open_request

    settings = get_settings()
    monkeypatch.setattr(settings, "kyc_verification_provider", "cashfree", raising=False)
    monkeypatch.setattr(settings, "kyc_verification_client_id", "cf-id", raising=False)
    monkeypatch.setattr(settings, "kyc_verification_client_secret", "cf-secret", raising=False)

    async def _not_yet(self: Any, *, provider_ref: str, id_document: str) -> None:
        return None

    monkeypatch.setattr(CashfreeDigiLocker, "fetch_outcome", _not_yet)
    org = await _tenant()
    tenant_id = UUID(str(org["id"]))
    ref = "clv-" + uuid.uuid4().hex
    async with tenant_session(tenant_id) as session:
        await open_request(
            session,
            tenant_id=tenant_id,
            provider="cashfree",
            provider_ref=ref,
            entity_type="sole_proprietorship",
            id_document="pan",
        )
    raw = json.dumps({"data": {"verification_id": ref, "status": "PENDING"}}).encode()
    async with _client() as http:
        delivered = await http.post(
            "/hooks/v1/kyc/cashfree",
            content=raw,
            headers={
                SIGNATURE_HEADER: sign(secret="cf-secret", timestamp="17", body=raw),
                TIMESTAMP_HEADER: "17",
            },
        )
    assert delivered.status_code == 200, delivered.text
    assert delivered.json() == {"status": "pending"}
    async with tenant_session(tenant_id) as session:
        assert not (await read_kyc(session, tenant_id=tenant_id)).is_verified


# --- the dial gate and the entity list -----------------------------------------------


async def test_an_open_payment_dispute_pauses_outbound() -> None:
    tenant_id, agent_id = await _tenant_agent()
    await arm_agent_for_outbound(tenant_id, agent_id)
    assert (await _gate(tenant_id, agent_id)).allowed  # type: ignore[attr-defined]
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO payment_disputes (id, tenant_id, dispute_id, payment_id, amount_inr, "
                "status, hold_inr, action_required, last_event) VALUES (:id, :t, :d, 'pay_x', "
                "100, 'under_review', 100, false, 'payment.dispute.under_review')"
            ),
            {"id": uuid7(), "t": tenant_id, "d": f"disp_{uuid.uuid4().hex[:12]}"},
        )
    decision: Any = await _gate(tenant_id, agent_id)
    assert (decision.allowed, decision.rule) == (False, "payment_dispute")
    assert decision.reason == DISPUTE_HOLD_REASON


async def test_the_entity_list_names_our_tm_registration_first_and_nothing_when_clear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.outbound_registration_gate_test import _record_pe

    tenant_id, _agent_id = await _tenant_agent()
    await _record_pe(tenant_id, status="active", tm_link_status="active")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE dlt_registrations SET verified_at = now() WHERE tenant_id = :t"),
            {"t": tenant_id},
        )
        assert (await registration.read_tm_registration(session)).is_live
        assert await registration.outbound_entity_blockers(session, tenant_id=tenant_id) == []

    monkeypatch.setattr(registration, "read_tm_registration", _always_down)
    async with tenant_session(tenant_id) as session:
        blockers = await registration.outbound_entity_blockers(session, tenant_id=tenant_id)
    assert [rule for rule, _ in blockers] == ["tm_registration_missing"]


class _Down:
    is_live = False


async def _always_down(_session: Any) -> _Down:
    return _Down()


async def test_nothing_is_pushed_when_no_number_given_is_on_the_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org = await _tenant()
    tenant_id = UUID(str(org["id"]))
    await give_own_workspace(tenant_id)
    monkeypatch.setattr(get_settings(), "engine", "thinnest")
    async with tenant_session(tenant_id) as session:
        queued = await engine_dnc.queue_engine_dnc_push(
            session, tenant_id=tenant_id, phones=["+919876500123"]
        )
        jobs = (
            await session.execute(
                text(
                    "SELECT count(*) FROM outbox_messages WHERE job = :j "
                    "AND payload->>'tenant_id' = :t"
                ),
                {"j": engine_dnc.ENGINE_DNC_PUSH_JOB, "t": str(tenant_id)},
            )
        ).scalar()
    assert queued is False
    assert jobs == 0
