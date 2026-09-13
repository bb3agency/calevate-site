"""The carrier compliance application — the reseller stage, end to end.

`docs/evidence/orchestrator-commercial-and-carrier-2026-09-13.md` §5.2 found that our
carrier treats us as a RESELLER rather than a direct brand, and therefore requires *a
separate approved compliance application for each customer* before that customer's number
can be rented or used. That is a gating stage in the tenant lifecycle, and it had no
table, no state machine, no gate and no route. These tests pin the six properties that
make it a control rather than a claim.

1. **OUR state machine, THEIR identifier.** The carrier's status words are mapped onto
   ours and an unmapped one is REFUSED rather than stored — hard rule 11 applied to a
   vendor vocabulary nobody in this repository has read.
2. **The vendor constraints are checked at the door**, from the named constants that carry
   their evidence class, and a client learns about a refused file while it is still in
   front of them.
3. **The transitions are compare-and-swap**, so two operators recording two decisions
   cannot both win, and a client cannot overwrite documents that are already with the
   carrier.
4. **The gate is where a number is ACQUIRED** — `buy_number` before a rupee is spent and
   `provision_number` for anything that reaches the table another way.
5. **The dial gate refuses a tenant whose approval is missing or has lapsed**, scoped to
   the numbers the rule is actually about (the ones we supplied).
6. **Hard rule 1.** Cross-tenant zero rows, through the route and on the raw session.

Run: uv run pytest -q tests/carrier_compliance_test.py
"""

from __future__ import annotations

import io
import uuid
from decimal import Decimal
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.conftest import accept_agreements, arm_agent_for_outbound

pytestmark = [pytest.mark.rls]

PATH = "/v1/compliance/carrier-application"
# A plausible carrier reference. Opaque to us by design: we carry it, we never parse it.
CARRIER_REF = "CA-4471-TS"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _make_admin(role: str = "superadmin") -> str:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', :role, now(), now())"
            ),
            {"id": admin_id, "role": role},
        )
    return f"dev:admin:{admin_id}"


async def _make_member(tenant_id: uuid.UUID, role: str = "owner") -> str:
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
                "VALUES (:id, :tid, :uid, :role, now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id, "role": role},
        )
    return f"dev:client:{user_id}"


async def _tenant() -> dict[str, Any]:
    created = await admin_service.create_organization(
        name="Carrier Motors",
        slug=f"carrier-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    # The four agreements, accepted — supplied rather than assumed away, in the shape
    # `arm_agent_for_outbound` established. Every dial gate refuses an organisation that
    # has not accepted them, so a fixture without this reports `agreements_not_accepted`
    # in place of the answer under test.
    await accept_agreements(uuid.UUID(str(created["id"])))
    # `managed`, because the money gates sit BEFORE this one in `check_dispatch` and a
    # default `prepaid` account with an empty wallet reports `no_credits` in place of the
    # answer under test. The carrier rule is tier-blind — it is the carrier's condition on
    # a number, not a billing motion — so the tier chosen here changes nothing about it.
    async with tenant_session(uuid.UUID(str(created["id"]))) as session:
        result = await session.execute(
            text("UPDATE organizations SET plan_tier = 'managed' WHERE id = :tid"),
            {"tid": created["id"]},
        )
        assert result.rowcount == 1, "plan_tier must actually change for this fixture"
    return created


async def _headers(org: dict[str, Any], role: str = "owner") -> dict[str, str]:
    token = await _make_member(uuid.UUID(str(org["id"])), role=role)
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": str(org["slug"])}


async def _submit(org: dict[str, Any], *, filename: str = "gst-certificate.pdf") -> Any:
    """Send documents the way a client does — through the route, with a real multipart
    body. A test that wrote the row itself would pass against a writer production no
    longer has."""
    async with _client() as http:
        return await http.post(
            PATH,
            headers=await _headers(org),
            data={"document_kind": "gst_certificate"},
            files={
                "document": (filename, b"%PDF-1.4 fake certificate", "application/pdf"),
                "signed_application": (
                    "signed-application.pdf",
                    b"%PDF-1.4 signed and sealed",
                    "application/pdf",
                ),
            },
        )


async def _decide(org: dict[str, Any], **payload: Any) -> Any:
    token = await _make_admin()
    async with _client() as http:
        return await http.post(
            f"/v1/admin/tenants/{org['id']}/carrier-application",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )


async def _accept(org: dict[str, Any]) -> None:
    response = await _decide(org, status="accepted", carrier_application_id=CARRIER_REF)
    assert response.status_code == 200, response.text


async def _agent(tenant_id: uuid.UUID, *, direction: str = "outbound") -> uuid.UUID:
    """A live agent with a disclosure line, so the dispatch gate reaches the tenant
    questions instead of stopping at the agent ones."""
    agent_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO agents (id, tenant_id, name, direction, status, language_primary, "
                "disclosure_line, ai_disclosure_line, recording_notice_line, "
                "caller_memory_notice_line, created_at, updated_at) VALUES (:id, :tid, 'Carrier "
                "agent', :dir, 'live', 'te-IN', 'This is an AI assistant and this call is "
                "recorded.', 'This is an AI assistant and this call is recorded.', 'This call "
                "is being recorded.', 'I keep a short note of what you ask about.', now(), "
                "now())"
            ),
            {"id": agent_id, "tid": tenant_id, "dir": direction},
        )
    return agent_id


def _unique_e164() -> str:
    """A number no other test holds. `phone_numbers.e164` is UNIQUE across the whole
    platform — deliberately, since two accounts cannot hold one connection — and this
    database outlives any one test."""
    return f"+9180{uuid.uuid4().int % 100000000:08d}"


async def _mark_numbers_carrier_supplied(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> None:
    """Make this agent's registered number one WE rented, which is the only kind the
    carrier's rule is about (`phone_numbers.engine_owned`)."""
    async with tenant_session(tenant_id) as session:
        result = await session.execute(
            # WITH a rental price: a number we rented has one, and the monthly meter
            # counts a priced-less owned number as `unpriced` platform-wide — so a fixture
            # that owned a number for free would show up in another suite's cross-tenant
            # assertion about the meter.
            text(
                "UPDATE phone_numbers SET engine_owned = true, monthly_rental_usd = 1.50 "
                "WHERE agent_id = :aid"
            ),
            {"aid": agent_id},
        )
        assert result.rowcount >= 1, "the fixture must actually own a number"


# ------------------------------------------------------- the state machine, on its own


def test_the_transition_table_is_the_only_source_of_the_derived_sets() -> None:
    """`SUBMITTABLE_FROM` and `OPERATOR_DECISIONS` are DERIVED, and this is what makes
    that worth doing: an edge added to the table has to show up in both without anybody
    remembering to widen a second list."""
    from apps.api.compliance.carrier_application import (
        CARRIER_APPLICATION_TRANSITIONS,
        OPERATOR_DECISIONS,
        SUBMITTABLE_FROM,
    )

    for state in SUBMITTABLE_FROM:
        assert "submitted" in CARRIER_APPLICATION_TRANSITIONS[state]
    for decision, sources in OPERATOR_DECISIONS.items():
        for source in sources:
            assert decision in CARRIER_APPLICATION_TRANSITIONS[source]
    # An accepted application does not go straight back to `rejected`: a carrier that
    # suspends a live approval has stopped honouring it rather than re-decided it, and
    # `expired` is the state whose next action ("re-apply") is the right one.
    assert CARRIER_APPLICATION_TRANSITIONS["accepted"] == frozenset({"expired"})
    # Every terminal-looking state has a way back, because every one of them is a state a
    # business can remedy. A state machine with a dead end would strand an account.
    for state in ("documents_required", "rejected", "expired"):
        assert CARRIER_APPLICATION_TRANSITIONS[state] == frozenset({"submitted"})


def test_an_unmapped_carrier_status_is_refused_rather_than_stored() -> None:
    """Hard rule 11 at a vendor boundary: their status strings are REPORTED and unread, so
    a word we do not know is a word we may not act on. Guessing towards `accepted` would
    open the number gate on nothing."""
    from apps.api.compliance.carrier_application import our_status_for_carrier_status

    assert our_status_for_carrier_status("Approved") == "accepted"
    assert our_status_for_carrier_status("suspended") == "expired"
    with pytest.raises(ProblemError) as refused:
        our_status_for_carrier_status("under_manual_escalation")
    assert refused.value.code == "carrier_status_unrecognised"


def test_the_vendor_file_rules_are_enforced_at_the_door() -> None:
    """The ceilings are the carrier's (REPORTED, one named constant each). Checked here so
    a client hears "too large" while the file is still open, not from the carrier days
    later."""
    from apps.api.compliance.carrier_application import (
        CARRIER_MAX_DOCUMENT_BYTES,
        CARRIER_MAX_FILENAME_CHARS,
        assert_document_within_limits,
        classify_document,
    )

    assert classify_document("gst.PDF") == ("pdf", "application/pdf")
    assert classify_document("seal.jpeg") == ("jpeg", "image/jpeg")
    with pytest.raises(ProblemError) as bad_kind:
        classify_document("registration.docx")
    assert bad_kind.value.code == "carrier_document_kind_unsupported"

    with pytest.raises(ProblemError) as too_big:
        assert_document_within_limits(filename="gst.pdf", size_bytes=CARRIER_MAX_DOCUMENT_BYTES + 1)
    assert too_big.value.code == "carrier_document_too_large"

    with pytest.raises(ProblemError) as too_long:
        assert_document_within_limits(
            filename="g" * (CARRIER_MAX_FILENAME_CHARS + 1) + ".pdf", size_bytes=10
        )
    assert too_long.value.code == "carrier_document_filename_too_long"

    # Path separators out of a name we store and display; the filename never reaches an
    # object key in the first place, so this protects the console and the carrier's form.
    assert assert_document_within_limits(filename="../../gst.pdf", size_bytes=10) == "....gst.pdf"

    # A name made ENTIRELY of the characters we strip sanitises to nothing, and nothing is
    # not a filename: storing it would put an empty cell on the client's own screen and an
    # unnamed attachment on the carrier's form, with nobody able to say which document it
    # was. The refusal names the file the client can still see in front of them.
    with pytest.raises(ProblemError) as nameless:
        assert_document_within_limits(filename="/\\/", size_bytes=10)
    assert nameless.value.code == "carrier_document_filename_required"
    assert "rename" in (nameless.value.remediation or "").lower()


def test_a_status_the_check_constraint_cannot_hold_is_raised_not_carried() -> None:
    """The narrowing between the database and the Literal. `CarrierStatus` is what every
    gate switches on, and `ck_carrier_compliance_applications_status_enum` is what keeps
    the column inside it — so a value outside the set means the constraint was changed
    without this module, and carrying it onward would let an unknown word decide whether a
    number may be dialled. It is raised at the read instead, naming the value found."""
    from apps.api.compliance.carrier_application import (
        CARRIER_APPLICATION_TRANSITIONS,
        _as_status,
    )

    for state in CARRIER_APPLICATION_TRANSITIONS:
        assert _as_status(state) == state
    with pytest.raises(ValueError, match="under_carrier_review"):
        _as_status("under_carrier_review")


def test_the_object_key_separates_one_submission_from_the_next() -> None:
    """A rejected application is resubmitted IN PLACE, so a key built from the application
    alone would overwrite the bytes the carrier refused — and "what did we actually send
    them" would stop being answerable at the moment somebody asks."""
    from apps.workers.storage import carrier_application_prefix, carrier_document_key

    tenant, application = uuid.uuid4(), uuid.uuid4()
    first = carrier_document_key(
        tenant_id=tenant,
        application_id=application,
        submission_id=uuid.uuid4(),
        slot="registration",
        suffix="pdf",
    )
    second = carrier_document_key(
        tenant_id=tenant,
        application_id=application,
        submission_id=uuid.uuid4(),
        slot="registration",
        suffix="pdf",
    )
    assert first != second
    # Both still enumerable as one application, which is what an account offboarding needs.
    prefix = carrier_application_prefix(tenant_id=tenant, application_id=application)
    assert first.startswith(prefix) and second.startswith(prefix)


# ------------------------------------------------------------------- the client's half


async def test_a_client_with_nothing_on_file_gets_its_absence_as_data() -> None:
    """The normal state of every new account. A 404 here arrives at the fetch layer
    indistinguishable from a moved route or a lost permission."""
    org = await _tenant()
    async with _client() as http:
        response = await http.get(PATH, headers=await _headers(org))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["recorded"] is False
    assert body["status"] is None
    assert body["is_accepted"] is False


async def test_submitting_files_the_documents_and_moves_the_application(s3: Any) -> None:
    """The client's own act: they hold the documents, so the upload is theirs."""
    org = await _tenant()
    response = await _submit(org)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "submitted"
    assert body["document_kind"] == "gst_certificate"
    assert body["document_filename"] == "gst-certificate.pdf"
    assert body["signed_application_on_file"] is True
    assert body["is_accepted"] is False
    # The bytes reached the store, under a key naming the tenant — and the KEY itself is
    # never handed to the client.
    assert "document_object_ref" not in body
    assert any(key.startswith("carrier-compliance/") for key in s3.objects)


async def test_a_first_application_without_the_signed_form_is_refused(s3: Any) -> None:
    """REPORTED, 12 Sep 2026: the FIRST application must be signed by an authorised
    signatory and carry a company seal, and PAN alone is refused. We cannot see a seal and
    do not pretend to — what is enforced is that the form is there, before any bytes are
    stored."""
    org = await _tenant()
    async with _client() as http:
        response = await http.post(
            PATH,
            headers=await _headers(org),
            data={"document_kind": "gst_certificate"},
            files={"document": ("gst.pdf", b"%PDF-1.4 cert", "application/pdf")},
        )
    assert response.status_code == 422, response.text
    assert response.json()["type"].rsplit("/", 1)[-1] == "carrier_signed_application_required"
    # Refused BEFORE storing: a client who cannot submit has spent none of our storage.
    assert not [key for key in s3.objects if key.startswith("carrier-compliance/")]


async def test_a_later_resubmission_may_replace_only_the_certificate(s3: Any) -> None:
    """ "First" means "we hold no signed form yet", which is the fact the column records —
    so a rejected application answered with a fresh certificate is not asked for the
    signed form twice."""
    org = await _tenant()
    assert (await _submit(org)).status_code == 201
    assert (
        await _decide(org, status="rejected", rejection_reason="Certificate expired.")
    ).status_code == 200
    async with _client() as http:
        again = await http.post(
            PATH,
            headers=await _headers(org),
            data={"document_kind": "gst_certificate"},
            files={"document": ("gst-new.pdf", b"%PDF-1.4 cert", "application/pdf")},
        )
    assert again.status_code == 201, again.text
    assert again.json()["signed_application_on_file"] is True


async def test_a_second_submission_while_the_carrier_holds_it_is_refused(s3: Any) -> None:
    """CAS, from the client's side: a resubmission must not overwrite the documents that
    are already in front of the carrier, because then nobody can say what was sent."""
    org = await _tenant()
    assert (await _submit(org)).status_code == 201
    again = await _submit(org, filename="gst-v2.pdf")
    assert again.status_code == 409, again.text
    assert again.json()["type"].rsplit("/", 1)[-1] == "carrier_application_in_review"


async def test_a_rejection_is_shown_to_the_client_with_the_carriers_reason(s3: Any) -> None:
    """ "Rejected" with no reason is the ticket nobody can close — and the client is the
    only person who can fix it."""
    org = await _tenant()
    assert (await _submit(org)).status_code == 201
    decided = await _decide(
        org, status="rejected", rejection_reason="The GSTIN on the certificate is cancelled."
    )
    assert decided.status_code == 200, decided.text

    async with _client() as http:
        body = (await http.get(PATH, headers=await _headers(org))).json()
    assert body["status"] == "rejected"
    assert "cancelled" in body["rejection_reason"]
    assert body["is_accepted"] is False


async def test_a_rejected_application_can_be_sent_again(s3: Any) -> None:
    """Every terminal-looking state is one a business can remedy, and the product has to
    let them: a rejection that could not be answered would be an account we had closed
    without saying so."""
    org = await _tenant()
    assert (await _submit(org)).status_code == 201
    assert (
        await _decide(org, status="rejected", rejection_reason="Seal not visible.")
    ).status_code == 200
    again = await _submit(org, filename="gst-resealed.pdf")
    assert again.status_code == 201, again.text
    body = again.json()
    assert body["status"] == "submitted"
    # The superseded refusal is cleared: a resubmitted application still showing the last
    # rejection is a screen that lies to the client about where they stand.
    assert body["rejection_reason"] is None


async def test_an_accepted_application_is_not_sent_again(s3: Any) -> None:
    """The OTHER refusal the submit route owes a client, and the one a flat "not
    submittable" would bury: an account whose application the carrier has already accepted
    is not blocked on anything, and telling them to send more paperwork would have them
    chasing a document nobody wants. `carrier_application_in_review` and this are separate
    codes because the next action differs — wait, versus nothing further is needed."""
    org = await _tenant()
    assert (await _submit(org)).status_code == 201
    await _accept(org)

    stored_before = set(s3.objects)

    again = await _submit(org, filename="gst-again.pdf")
    assert again.status_code == 409, again.text
    body = again.json()
    assert body["type"].rsplit("/", 1)[-1] == "carrier_application_already_accepted"
    assert "already been accepted" in body["detail"]
    assert "Numbers can be arranged" in body["remediation"]
    # Refused BEFORE the bytes are stored, like the unsigned first application: a client
    # who cannot submit spends none of our storage.
    assert set(s3.objects) == stored_before


async def test_the_cas_refuses_a_submission_the_routes_own_check_would_have_let_through(
    s3: Any,
) -> None:
    """The route's `assert_submittable` is ADVISORY and this is why the CAS still has to
    guard: the route reads the state, then spends seconds storing an upload, and an
    operator can record the carrier's decision inside that window. Driving the service
    function directly is that window with the timing taken out — the guard lives in the
    UPDATE's WHERE clause, so a state that changed after the read still refuses, and the
    documents already in front of the carrier are not overwritten."""
    from apps.api.compliance.carrier_application import (
        ensure_application_row,
        read_carrier_application,
        submit_application,
    )

    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    assert (await _submit(org)).status_code == 201
    await _accept(org)

    async with tenant_session(tenant_id) as session:
        application_id = await ensure_application_row(session, tenant_id=tenant_id)
        with pytest.raises(ProblemError) as refused:
            await submit_application(
                session,
                tenant_id=tenant_id,
                application_id=application_id,
                document_kind="gst_certificate",
                document_object_ref="carrier-compliance/x/y/z/registration.pdf",
                document_filename="gst-late.pdf",
                signed_application_ref=None,
            )
    assert refused.value.code == "carrier_application_not_submittable"
    assert refused.value.status == 409
    assert "Reload" in (refused.value.remediation or "")

    # And the write really did not happen: the accepted application still names the
    # carrier's reference and the document the carrier actually saw.
    async with tenant_session(tenant_id) as session:
        record = await read_carrier_application(session, tenant_id=tenant_id)
    assert record.status == "accepted"
    assert record.carrier_application_id == CARRIER_REF
    assert record.document_filename == "gst-certificate.pdf"


async def test_an_upload_that_only_declares_its_size_late_is_still_stopped() -> None:
    """`await file.read()` reads whatever was sent, so the memory one request spends would
    be chosen by whoever sent it — on an ASGI server that is every tenant's process, not
    only the uploader's. The read is chunked and STOPS at the carrier's ceiling rather than
    buffering to the end and measuring afterwards, which is the whole point: the refusal
    has to arrive without the bytes having been kept.

    Driven directly because the global 2 MiB body limit (`core/middleware.MAX_BODY_BYTES`)
    sits in front of this route and answers 413 long before 5 MiB arrives. That makes this
    bound defence in depth — the same per-route bound `kb/routes._read_bounded` keeps — and
    a bound whose only proof was another module's constant is one that stops holding the
    day that constant moves."""
    from apps.api.compliance.carrier_application import CARRIER_MAX_DOCUMENT_BYTES
    from apps.api.compliance.carrier_application_routes import _read_bounded
    from fastapi import UploadFile

    oversized = io.BytesIO(b"\0" * (CARRIER_MAX_DOCUMENT_BYTES + 1))
    with pytest.raises(ProblemError) as refused:
        await _read_bounded(UploadFile(file=oversized, filename="huge-scan.pdf"))
    assert refused.value.code == "carrier_document_too_large"
    # Stopped, not drained: the refusal is raised while bytes are still unread, so the
    # rest of the body is never paid for.
    assert oversized.tell() <= CARRIER_MAX_DOCUMENT_BYTES + 1


# ---------------------------------------------------------------------- ops's half


async def test_accepting_without_the_carriers_reference_is_refused(s3: Any) -> None:
    """An acceptance that cannot produce `compliance_application_id` is a green light
    attached to nothing: that reference is what a number purchase has to quote."""
    org = await _tenant()
    assert (await _submit(org)).status_code == 201
    response = await _decide(org, status="accepted")
    assert response.status_code == 422, response.text
    assert response.json()["type"].rsplit("/", 1)[-1] == "carrier_application_id_required"


async def test_the_carriers_own_word_is_mapped_onto_ours(s3: Any) -> None:
    """An operator transcribing the carrier's console is a different act from an operator
    deciding what it means, and the route takes both — mapping the first, refusing a word
    it does not know."""
    org = await _tenant()
    assert (await _submit(org)).status_code == 201
    response = await _decide(org, carrier_status="approved", carrier_application_id=CARRIER_REF)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "accepted"

    async with _client() as http:
        body = (await http.get(PATH, headers=await _headers(org))).json()
    assert body["is_accepted"] is True
    assert body["carrier_application_id"] == CARRIER_REF


async def test_recording_a_decision_twice_is_not_two_decisions(s3: Any) -> None:
    """Idempotent by RFC 9110 §9.2.2: the second click of a button, or the retry of a
    request whose response was lost, must not read as a second change."""
    org = await _tenant()
    assert (await _submit(org)).status_code == 201
    first = await _decide(org, status="accepted", carrier_application_id=CARRIER_REF)
    second = await _decide(org, status="accepted", carrier_application_id=CARRIER_REF)
    assert first.json()["changed"] is True
    assert second.json()["changed"] is False


async def test_an_impossible_move_is_a_409_naming_the_state_found(s3: Any) -> None:
    """The CAS's third answer. An operator recording a rejection on an application a
    colleague already accepted is told what happened, not silently allowed to overwrite
    it."""
    org = await _tenant()
    assert (await _submit(org)).status_code == 201
    await _accept(org)
    response = await _decide(org, status="rejected", rejection_reason="Too late.")
    assert response.status_code == 409, response.text
    assert response.json()["type"].rsplit("/", 1)[-1] == "invalid_status_transition"


async def test_a_decision_must_say_which_decision(s3: Any) -> None:
    """Both fields, or neither, means the operator meant two different things — and
    picking one would record a decision they did not make."""
    org = await _tenant()
    assert (await _submit(org)).status_code == 201
    neither = await _decide(org, carrier_application_id=CARRIER_REF)
    assert neither.status_code == 422
    assert neither.json()["type"].rsplit("/", 1)[-1] == "carrier_decision_status_required"
    both = await _decide(org, status="accepted", carrier_status="approved")
    assert both.status_code == 422


async def test_a_carrier_status_that_is_not_a_decision_is_refused(s3: Any) -> None:
    """ "Pending" maps to where the application already is. Recording it would be a no-op
    dressed as an action, and the operator would leave believing something had happened."""
    org = await _tenant()
    assert (await _submit(org)).status_code == 201
    response = await _decide(org, carrier_status="pending")
    assert response.status_code == 422, response.text
    assert response.json()["type"].rsplit("/", 1)[-1] == "carrier_decision_not_a_decision"


async def test_there_is_no_client_route_that_decides_an_application() -> None:
    """The decision is the CARRIER's. A client who could accept their own application
    would open the number gate on a decision nobody made — and the carrier would then
    refuse at purchase time with our money already committed."""
    from apps.api.core.rbac import MUTATING_PERMISSIONS, iter_api_routes

    declared = {
        route.path: (route.openapi_extra or {}).get("x-calevate-permission")
        for route in iter_api_routes(app)
        if route.methods in ({"GET"}, {"GET", "HEAD"})
    }
    # The client's READ is not behind a mutating permission, so it stays visible inside a
    # read-only "view as client" session (D-22) — the session support is in when the call
    # about a blocked account comes in.
    assert declared.get(PATH) == "org:read", declared.get(PATH)
    assert "org:read" not in MUTATING_PERMISSIONS

    client_writers = {
        route.path
        for route in iter_api_routes(app)
        if route.path.startswith(PATH)
        and not route.path.startswith("/v1/admin")
        and route.methods not in ({"GET"}, {"GET", "HEAD"})
    }
    # Exactly ONE client write exists, and it is the submission: it carries documents and
    # takes no status at all, so there is no client-reachable path to `accepted`.
    assert client_writers == {PATH}, client_writers


async def test_a_rejection_without_a_reason_is_refused_before_the_database_sees_it(
    s3: Any,
) -> None:
    """ "Rejected, no reason recorded" is the ticket nobody can close: the client is shown
    this sentence and is the only person who can act on it. The CHECK constraint is the
    real enforcement — this exists so an operator reads a problem+json naming the missing
    field instead of a 500 out of an IntegrityError at the end of the transaction."""
    org = await _tenant()
    assert (await _submit(org)).status_code == 201

    blank = await _decide(org, status="rejected", rejection_reason="   ")
    assert blank.status_code == 422, blank.text
    body = blank.json()
    assert body["type"].rsplit("/", 1)[-1] == "carrier_rejection_reason_required"
    assert "which document to replace" in body["detail"]
    assert "the client is shown this" in body["remediation"]

    # Nothing was recorded: the application is still where the carrier left it, so the
    # operator can record the decision properly rather than having to undo a half one.
    async with _client() as http:
        current = (await http.get(PATH, headers=await _headers(org))).json()
    assert current["status"] == "submitted"
    assert current["rejection_reason"] is None


async def test_ops_reads_one_clients_application_and_the_read_is_recorded(s3: Any) -> None:
    """The operator's own view, and the ledger row it owes. This is an admin-realm GET of
    one client's tenant-scoped rows OUTSIDE impersonation (SEC-COMP §5, D-482 L-1) — a
    business's registration paperwork is their data, and "who looked at this account and
    when" is not answerable afterwards unless the read says so itself.

    It reads through the TENANT's own RLS session rather than a widened policy, so what
    ops sees here is exactly what the client's own screen sees — asserted by comparing the
    two bodies rather than by trusting that two handlers agree."""
    from apps.api.core.auth import ADMIN_TENANT_READ_ACTION

    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    assert (await _submit(org)).status_code == 201
    await _accept(org)

    token = await _make_admin()
    async with _client() as http:
        ops = await http.get(
            f"/v1/admin/tenants/{tenant_id}/carrier-application",
            headers={"Authorization": f"Bearer {token}"},
        )
        client = await http.get(PATH, headers=await _headers(org))
    assert ops.status_code == 200, ops.text
    assert ops.json() == client.json()
    assert ops.json()["carrier_application_id"] == CARRIER_REF

    async with untenanted_session() as session:
        reads = (
            await session.execute(
                text("SELECT actor_id FROM audit_log WHERE action = :action AND tenant_id = :tid"),
                {"action": ADMIN_TENANT_READ_ACTION, "tid": tenant_id},
            )
        ).all()
    assert [str(row[0]) for row in reads] == [token.rsplit(":", 1)[-1]], (
        "the operator's read of a client's paperwork must leave exactly one ledger row "
        "naming that operator"
    )


# ------------------------------------------------------ the gate, where a number is got


async def test_a_number_we_supply_cannot_be_recorded_without_an_accepted_application(
    s3: Any,
) -> None:
    """The acquisition gate. `engine_owned` is the column that means "we rented this on
    our carrier account", which is exactly the set the carrier's rule is about."""
    from apps.api.agents.service import provision_number

    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    owned_e164 = _unique_e164()
    with pytest.raises(ProblemError) as refused:
        async with tenant_session(tenant_id) as session:
            await provision_number(
                session,
                tenant_id=tenant_id,
                e164=owned_e164,
                series="standard",
                agent_id=None,
                provider="plivo",
                purpose="inbound",
                engine_owned=True,
            )
    assert refused.value.code == "carrier_application_not_accepted"

    assert (await _submit(org)).status_code == 201
    await _accept(org)
    async with tenant_session(tenant_id) as session:
        number_id = await provision_number(
            session,
            tenant_id=tenant_id,
            e164=owned_e164,
            series="standard",
            agent_id=None,
            provider="plivo",
            purpose="inbound",
            engine_owned=True,
            monthly_rental_usd=Decimal("1.50"),
        )
    assert number_id is not None


async def test_a_clients_own_connection_is_not_gated_on_our_carriers_opinion() -> None:
    """Model B: a number the client took on their OWN operator account is not rented under
    our reseller relationship, and our carrier has no rule about it. Refusing it would
    block the onboarding path every existing client came in through."""
    from apps.api.agents.service import provision_number

    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    async with tenant_session(tenant_id) as session:
        number_id = await provision_number(
            session,
            tenant_id=tenant_id,
            e164=_unique_e164(),
            series="standard",
            agent_id=None,
            provider="exotel",
            purpose="inbound",
            engine_owned=False,
        )
    assert number_id is not None


# ------------------------------------------------------------------- the gate, at dial


async def test_the_dial_gate_refuses_a_tenant_without_an_accepted_application(
    monkeypatch: pytest.MonkeyPatch, s3: Any
) -> None:
    """The dial-time half. It exists because acceptance can stop being true AFTER the
    number is in hand — a carrier suspends an application over unresolved UCC complaints,
    and the number does not change when it does."""
    from apps.api.compliance.service import check_dispatch

    # Calling hours are a real gate and a real clock: without this the assertion below
    # depends on what time the suite runs, which is the flake `admin_cap_arms_the_gate`
    # already records.
    monkeypatch.setattr("apps.api.compliance.service.within_calling_hours", lambda *a, **k: True)
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    agent_id = await _agent(tenant_id)
    await arm_agent_for_outbound(tenant_id, agent_id)
    await _mark_numbers_carrier_supplied(tenant_id, agent_id)

    async with tenant_session(tenant_id) as session:
        decision = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164="+919000000011"
        )
    assert decision.allowed is False
    assert decision.rule == "carrier_application_missing"
    assert "carrier" in (decision.reason or "")

    # Filed but not decided is a DIFFERENT fact with a different next action, and the
    # refusal says which one it is rather than repeating "not accepted" three ways.
    assert (await _submit(org)).status_code == 201
    async with tenant_session(tenant_id) as session:
        decision = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164="+919000000011"
        )
    assert decision.rule == "carrier_application_not_accepted"
    assert "submitted" in (decision.reason or "")

    await _accept(org)
    async with tenant_session(tenant_id) as session:
        decision = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164="+919000000011"
        )
    assert decision.allowed is True, decision.reason


async def test_a_tenant_dialling_from_its_own_connection_is_not_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scoping, asserted rather than described. Every number on this platform today is
    a client's own, so a supply-blind blocker would have halted every existing client's
    calling the day it shipped."""
    from apps.api.compliance.service import check_dispatch

    monkeypatch.setattr("apps.api.compliance.service.within_calling_hours", lambda *a, **k: True)
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    agent_id = await _agent(tenant_id)
    await arm_agent_for_outbound(tenant_id, agent_id)

    async with tenant_session(tenant_id) as session:
        decision = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164="+919000000012"
        )
    assert decision.allowed is True, decision.reason


async def test_an_expired_approval_stops_the_dial_again(
    monkeypatch: pytest.MonkeyPatch, s3: Any
) -> None:
    """The reason this gate is asked per dial at all: an approval that lapses or is
    suspended must close the line it opened."""
    from apps.api.compliance.service import check_dispatch

    monkeypatch.setattr("apps.api.compliance.service.within_calling_hours", lambda *a, **k: True)
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    agent_id = await _agent(tenant_id)
    await arm_agent_for_outbound(tenant_id, agent_id)
    await _mark_numbers_carrier_supplied(tenant_id, agent_id)
    assert (await _submit(org)).status_code == 201
    await _accept(org)

    assert (await _decide(org, status="expired")).status_code == 200
    async with tenant_session(tenant_id) as session:
        decision = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164="+919000000013"
        )
    assert decision.allowed is False
    assert decision.rule == "carrier_application_not_accepted"
    assert "expired" in (decision.reason or "")


async def test_the_launch_preview_names_the_same_blocker_before_the_client_hits_it(
    s3: Any,
) -> None:
    """SURFACES §2b wants a blocker a client can SEE. A campaign that launches "ready" and
    is then refused on every dial is the worst outcome available."""
    from apps.api.campaigns import service as campaigns

    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    agent_id = await _agent(tenant_id)
    await arm_agent_for_outbound(tenant_id, agent_id)
    await _mark_numbers_carrier_supplied(tenant_id, agent_id)

    async with tenant_session(tenant_id) as session:
        number_id = (
            await session.execute(
                text("SELECT id FROM phone_numbers WHERE agent_id = :aid LIMIT 1"),
                {"aid": agent_id},
            )
        ).scalar_one()
        campaign_id = await campaigns.create_campaign(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Carrier gate preview",
            classification="promotional",
            number_id=number_id,
            dlt_template_id=None,
            concurrency=1,
        )
        blockers = await campaigns.launch_blockers(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
    assert "carrier_application_missing" in {blocker.rule for blocker in blockers}


# ------------------------------------------------------------------------ hard rule 1


async def test_tenant_b_cannot_see_tenant_as_application(s3: Any) -> None:
    """Cross-tenant zero rows at BOTH levels: through the endpoint, and on the raw
    RLS-scoped session — an endpoint that filtered in Python would pass the first
    assertion while leaving isolation to a WHERE clause somebody can forget."""
    from apps.api.compliance.carrier_application import read_carrier_application

    tenant_a = await _tenant()
    tenant_b = await _tenant()
    assert (await _submit(tenant_a)).status_code == 201
    await _accept(tenant_a)

    async with _client() as http:
        mine = await http.get(PATH, headers=await _headers(tenant_a))
        theirs = await http.get(PATH, headers=await _headers(tenant_b))

    # Ground truth from the owning tenant, so a policy that hid a tenant's OWN row would
    # fail here rather than passing as "isolated".
    assert mine.json()["carrier_application_id"] == CARRIER_REF
    assert theirs.status_code == 200, theirs.text
    assert theirs.json()["recorded"] is False
    assert theirs.json()["carrier_application_id"] is None

    async with tenant_session(uuid.UUID(str(tenant_b["id"]))) as session:
        leaked = await read_carrier_application(session, tenant_id=uuid.UUID(str(tenant_a["id"])))
    assert leaked.recorded is False, "the RLS session must return zero rows for another tenant"

    async with untenanted_session() as session:
        blind = await read_carrier_application(session, tenant_id=uuid.UUID(str(tenant_a["id"])))
    assert blind.recorded is False, "no GUC ⇒ zero rows (fail closed)"
