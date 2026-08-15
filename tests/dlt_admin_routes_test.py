"""The five admin routes that record TELECOM FACTS, at the HTTP layer (PLAN part 8).

`POST …/numbers`, `POST …/numbers/{number_id}/dlt-status`, `POST …/dlt-templates`,
`POST …/dlt-templates/{template_id}/status` and `POST …/kyc` are the surface through
which a registrar's verdict and a licensee's identity check enter this system. Between
them they decide whether `campaigns.service.launch_blockers` lets a campaign dial —
`tests/campaign_dispatch_audit_test.py` proves the GATE reads them, and the services
underneath are exercised by that suite and by `kyc_gate_test`. **Nothing drove the
five endpoints**, so the permission dependency, the tenant scoping, the audit row and
the response model were unexercised on the only path an operator can reach.

What is asserted here:

1. **The realm.** All five are `realm="admin"`; a client `owner` — including the owner
   of the very tenant named in the path — is refused 401 `kind: auth`, and no row
   moves. A client that could mark its own KYC verified would be marking the telecom
   gate green on a check nobody performed (`admin/routes.py:1444`).
2. **D-22 is owned elsewhere.** All five declare `admin:tenants`, which is mutating, so
   `realm_boundary_test::test_no_route_declaring_a_mutating_permission_is_reachable_while_impersonating`
   already drives them under a real grant. Not re-asserted here — one way per problem.
3. **The happy path, with the response model's fields READ**, and with the DB row
   read back: `dlt_status` starts `pending` and is never `registered` because we typed
   the number in (`agents/service.py:670`), and a template is created `submitted`,
   never `approved` (`campaigns/service.py:956`).
4. **The audit rows**, with the summary the ledger actually carries — and, for
   `number.provisioned`, that the summary carries the SERIES and NOT the number
   (hard rule 6). That is a line of shipped code with a comment explaining it and
   nothing holding it.
5. **Tenancy.** A number id belonging to another tenant is a 404 rather than a
   cross-tenant write, because the UPDATE runs inside `tenant_session(tenant_id)`.

CONCURRENCY: every case mints its own tenant and asserts only on rows it created.
"""

from __future__ import annotations

import logging
import uuid

import pytest
from apps.api.admin import service as admin_service
from apps.api.db.session import admin_session, tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

NUMBERS = "/v1/admin/tenants/{tenant_id}/numbers"
NUMBER_DLT = "/v1/admin/tenants/{tenant_id}/numbers/{number_id}/dlt-status"
TEMPLATES = "/v1/admin/tenants/{tenant_id}/dlt-templates"
TEMPLATE_STATUS = "/v1/admin/tenants/{tenant_id}/dlt-templates/{template_id}/status"
KYC = "/v1/admin/tenants/{tenant_id}/kyc"

TEMPLATE_BODY = "Namaste, calling from {#var#} about your appointment on {#var#}."


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _e164() -> str:
    """A run-unique number in the +91 block. `phone_numbers.e164` is globally unique
    across tenants (`agents/service.py:673`), so a fixed literal would collide with
    every other suite sharing this Postgres."""
    return f"+9198{uuid.uuid4().int % 100000000:08d}"


async def _make_admin(role: str = "operator") -> str:
    clerk_id = f"admin_{uuid.uuid4().hex[:12]}"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, clerk_user_id, name, role, created_at, updated_at) "
                "VALUES (:id, :cid, 'Ops', :role, now(), now())"
            ),
            {"id": uuid.uuid4(), "cid": clerk_id, "role": role},
        )
    return f"dev:admin:{clerk_id}"


async def _make_member(tenant_id: uuid.UUID, role: str = "owner") -> str:
    user_id = uuid.uuid4()
    clerk_id = f"user_{uuid.uuid4().hex[:12]}"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, clerk_user_id, email, created_at, updated_at) "
                "VALUES (:id, :cid, :email, now(), now())"
            ),
            {"id": user_id, "cid": clerk_id, "email": f"{clerk_id}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, :role, now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id, "role": role},
        )
    return f"dev:client:{clerk_id}"


async def _tenant() -> tuple[uuid.UUID, str]:
    created = await admin_service.create_organization(
        name="DLT Clinic",
        slug=f"dlt-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return uuid.UUID(str(created["id"])), str(created["slug"])


async def _audit(tenant_id: uuid.UUID, action: str) -> list[tuple[str, str, str | None]]:
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT object_type, object_id, ip FROM audit_log "
                    "WHERE tenant_id = :t AND action = :a ORDER BY at, id"
                ),
                {"t": tenant_id, "a": action},
            )
        ).all()
    return [(str(r[0]), str(r[1]), None if r[2] is None else str(r[2])) for r in rows]


def _summaries(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.getMessage() == "audit"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- the realm boundary, driven on all five ------------------------------------------


async def test_a_client_owner_cannot_record_any_of_these_telecom_facts() -> None:
    """The owner of the tenant named in the path, with a valid session, refused on all
    five — and the control proves the token is not simply broken.

    KYC is the one that matters most: `admin/routes.py:1444` says there is deliberately
    no client-facing twin, and this is what makes that true at the wire rather than in
    a docstring.
    """
    tenant_id, slug = await _tenant()
    token = await _make_member(tenant_id, role="owner")
    headers = {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
    async with _client() as http:
        control = await http.get("/v1/agents", headers=headers)
        refusals = {
            "numbers": await http.post(
                NUMBERS.format(tenant_id=tenant_id),
                headers=headers,
                json={"e164": _e164(), "series": "160"},
            ),
            "number_status": await http.post(
                NUMBER_DLT.format(tenant_id=tenant_id, number_id=uuid.uuid4()),
                headers=headers,
                json={"dlt_status": "registered"},
            ),
            "templates": await http.post(
                TEMPLATES.format(tenant_id=tenant_id),
                headers=headers,
                json={"classification": "service", "body": TEMPLATE_BODY},
            ),
            "template_status": await http.post(
                TEMPLATE_STATUS.format(tenant_id=tenant_id, template_id=uuid.uuid4()),
                headers=headers,
                json={"status": "approved"},
            ),
            "kyc": await http.post(
                KYC.format(tenant_id=tenant_id),
                headers=headers,
                json={"status": "verified", "document_kind": "cin", "document_ref": "U85110"},
            ),
        }
    assert control.status_code == 200, "the control: this token works on its own realm"
    for name, response in refusals.items():
        assert response.status_code == 401, f"{name}: {response.text}"
        assert response.json()["kind"] == "auth", f"{name}: {response.text}"

    # Nothing was written by any of them.
    async with tenant_session(tenant_id) as session:
        counts = (
            await session.execute(
                text(
                    "SELECT (SELECT count(*) FROM phone_numbers WHERE tenant_id = :t), "
                    "(SELECT count(*) FROM dlt_templates WHERE tenant_id = :t), "
                    "(SELECT count(*) FROM kyc_records WHERE tenant_id = :t)"
                ),
                {"t": tenant_id},
            )
        ).one()
    assert tuple(counts) == (0, 0, 0)


# --- numbers -------------------------------------------------------------------------


async def test_provisioning_a_number_returns_it_pending_and_audits_the_series_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`dlt_status` is `pending` on creation and NOT `registered`: a number is not
    registered because an operator typed it in (`agents/service.py:670`).

    The audit assertion is the one this route's own comment asks for and nothing held
    it to — the SERIES reaches the ledger, the NUMBER never does (hard rule 6). The
    audit log is read cross-tenant, so a phone number in it is a phone number leaked to
    every reader of the ledger.
    """
    tenant_id, _slug = await _tenant()
    token = await _make_admin()
    e164 = _e164()
    with caplog.at_level(logging.INFO, logger="apps.api.compliance.audit"):
        async with _client() as http:
            response = await http.post(
                NUMBERS.format(tenant_id=tenant_id),
                headers=_auth(token),
                json={"e164": e164, "series": "160", "provider": "exotel", "purpose": "reception"},
            )
    assert response.status_code == 201, response.text
    body = response.json()
    number_id = body["id"]
    assert body["e164"] == e164
    assert body["series"] == "160"
    assert body["dlt_status"] == "pending", "a typed-in number is not a registered one"

    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(
                text(
                    "SELECT e164, series, dlt_status, provider, purpose FROM phone_numbers "
                    "WHERE id = :i"
                ),
                {"i": number_id},
            )
        ).one()
    assert tuple(stored) == (e164, "160", "pending", "exotel", "reception")

    assert await _audit(tenant_id, "number.provisioned") == [
        ("phone_number", str(number_id), "127.0.0.1")
    ]
    summary = _summaries(caplog)[-1]
    assert summary.series == "160"  # type: ignore[attr-defined]
    assert e164 not in str(summary.__dict__), "the audit ledger must never carry the number"


async def test_recording_the_registrars_verdict_moves_the_number_and_audits_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    tenant_id, _slug = await _tenant()
    token = await _make_admin()
    async with _client() as http:
        created = await http.post(
            NUMBERS.format(tenant_id=tenant_id),
            headers=_auth(token),
            json={"e164": _e164(), "series": "140"},
        )
        number_id = created.json()["id"]
        with caplog.at_level(logging.INFO, logger="apps.api.compliance.audit"):
            recorded = await http.post(
                NUMBER_DLT.format(tenant_id=tenant_id, number_id=number_id),
                headers=_auth(token),
                json={"dlt_status": "registered"},
            )
    assert recorded.status_code == 200, recorded.text
    assert recorded.json() == {"dlt_status": "registered"}

    async with tenant_session(tenant_id) as session:
        status = (
            await session.execute(
                text("SELECT dlt_status FROM phone_numbers WHERE id = :i"), {"i": number_id}
            )
        ).scalar_one()
    assert status == "registered"
    assert await _audit(tenant_id, "number.dlt_status_set") == [
        ("phone_number", str(number_id), "127.0.0.1")
    ]
    assert _summaries(caplog)[-1].dlt_status == "registered"  # type: ignore[attr-defined]


async def test_another_tenants_number_is_a_404_and_is_not_moved() -> None:
    """The UPDATE runs inside `tenant_session(tenant_id)`, so RLS makes a neighbour's
    row invisible and the answer is the one an unknown id gets. Worth driving rather
    than reasoning about: this is the shape of route where the path carries BOTH the
    tenant and the object, and nothing but RLS makes them agree."""
    tenant_id, _slug = await _tenant()
    other_id, _other_slug = await _tenant()
    token = await _make_admin()
    async with _client() as http:
        created = await http.post(
            NUMBERS.format(tenant_id=other_id),
            headers=_auth(token),
            json={"e164": _e164(), "series": "160"},
        )
        stranger = created.json()["id"]
        crossed = await http.post(
            NUMBER_DLT.format(tenant_id=tenant_id, number_id=stranger),
            headers=_auth(token),
            json={"dlt_status": "blocked"},
        )
    assert crossed.status_code == 404, crossed.text
    async with tenant_session(other_id) as session:
        status = (
            await session.execute(
                text("SELECT dlt_status FROM phone_numbers WHERE id = :i"), {"i": stranger}
            )
        ).scalar_one()
    assert status == "pending", "the neighbour's number was not touched"
    assert await _audit(tenant_id, "number.dlt_status_set") == []


# --- templates -----------------------------------------------------------------------


async def test_a_registered_template_is_created_submitted_never_approved(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Approval happens at the registrar. A template we mark approved because we typed
    it in is how a campaign launches under a template nobody registered
    (`campaigns/service.py:956`)."""
    tenant_id, _slug = await _tenant()
    token = await _make_admin()
    with caplog.at_level(logging.INFO, logger="apps.api.compliance.audit"):
        async with _client() as http:
            response = await http.post(
                TEMPLATES.format(tenant_id=tenant_id),
                headers=_auth(token),
                json={
                    "classification": "service",
                    "body": TEMPLATE_BODY,
                    "dlt_ref": "1007123456789012345",
                },
            )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "submitted"
    template_id = uuid.UUID(body["id"])

    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(
                text(
                    "SELECT kind, classification, status, dlt_ref FROM dlt_templates WHERE id = :i"
                ),
                {"i": template_id},
            )
        ).one()
    assert tuple(stored) == ("voice", "service", "submitted", "1007123456789012345")
    assert await _audit(tenant_id, "dlt_template.registered") == [
        ("dlt_template", str(template_id), "127.0.0.1")
    ]
    assert _summaries(caplog)[-1].classification == "service"  # type: ignore[attr-defined]


async def test_a_withdrawal_is_recordable_and_re_recording_still_audits() -> None:
    """`set_template_status` is deliberately NOT a `transition_status` state machine,
    and its docstring gives two consequences no test held it to:

    * `approved -> rejected` is a WITHDRAWAL, not a conflict. Constraining this to a
      `from_statuses` set would leave `launch_blockers` reading `approved` for a
      template the registrar has pulled.
    * Re-recording the SAME status is a 200 AND a real audit row, because there is no
      state machine here to be already-satisfied — the row is the record of the
      re-verification, and `dlt_templates` has no `verified_at` to hold it.
    """
    tenant_id, _slug = await _tenant()
    token = await _make_admin()
    async with _client() as http:
        created = await http.post(
            TEMPLATES.format(tenant_id=tenant_id),
            headers=_auth(token),
            json={"classification": "promotional", "body": TEMPLATE_BODY},
        )
        template_id = created.json()["id"]
        path = TEMPLATE_STATUS.format(tenant_id=tenant_id, template_id=template_id)
        approved = await http.post(path, headers=_auth(token), json={"status": "approved"})
        withdrawn = await http.post(path, headers=_auth(token), json={"status": "rejected"})
        again = await http.post(path, headers=_auth(token), json={"status": "rejected"})

    for response in (approved, withdrawn, again):
        assert response.status_code == 200, response.text
    assert approved.json() == {"status": "approved"}
    assert withdrawn.json() == {"status": "rejected"}

    async with tenant_session(tenant_id) as session:
        status = (
            await session.execute(
                text("SELECT status FROM dlt_templates WHERE id = :i"), {"i": template_id}
            )
        ).scalar_one()
    assert status == "rejected"
    # Three verdicts recorded, in order — including the repeat.
    assert len(await _audit(tenant_id, "dlt_template.status_set")) == 3


async def test_an_unknown_template_id_is_a_404_not_a_silent_success() -> None:
    tenant_id, _slug = await _tenant()
    token = await _make_admin()
    async with _client() as http:
        response = await http.post(
            TEMPLATE_STATUS.format(tenant_id=tenant_id, template_id=uuid.uuid4()),
            headers=_auth(token),
            json={"status": "approved"},
        )
    assert response.status_code == 404, response.text
    assert await _audit(tenant_id, "dlt_template.status_set") == []


# --- kyc -----------------------------------------------------------------------------


async def test_recording_kyc_returns_the_record_and_audits_the_registry_reference(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The registry identifier IS the audited fact — it is what a regulator asks us to
    evidence — and `signatory_name` is deliberately absent from the ledger, because the
    audit log is read cross-tenant and a natural person's name adds nothing an auditor
    needs (`admin/routes.py:1517`)."""
    tenant_id, _slug = await _tenant()
    token = await _make_admin()
    with caplog.at_level(logging.INFO, logger="apps.api.compliance.audit"):
        async with _client() as http:
            response = await http.post(
                KYC.format(tenant_id=tenant_id),
                headers=_auth(token),
                json={
                    "status": "verified",
                    "entity_type": "private_limited",
                    "document_kind": "cin",
                    "document_ref": "U85110KA2019PTC123456",
                    "signatory_name": "Lakshmi Rao",
                    "evidence_ref": "caf/2026/0042",
                },
            )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["tenant_id"] == str(tenant_id)
    assert body["status"] == "verified"
    assert body["document_kind"] == "cin"
    assert body["document_ref"] == "U85110KA2019PTC123456"

    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(
                text(
                    "SELECT status, entity_type, document_ref, signatory_name, "
                    "verified_at IS NOT NULL FROM kyc_records WHERE tenant_id = :t"
                ),
                {"t": tenant_id},
            )
        ).one()
    assert tuple(stored) == (
        "verified",
        "private_limited",
        "U85110KA2019PTC123456",
        "Lakshmi Rao",
        True,
    ), "verified_at is stamped by the database, not typed by an operator"

    assert await _audit(tenant_id, "kyc.recorded") == [("kyc_record", str(tenant_id), "127.0.0.1")]
    summary = _summaries(caplog)[-1]
    assert summary.document_ref == "U85110KA2019PTC123456"  # type: ignore[attr-defined]
    assert "Lakshmi Rao" not in str(summary.__dict__), (
        "the signatory's name is a natural person's name and the ledger is read cross-tenant"
    )


async def test_a_verified_record_with_no_document_is_refused_before_anything_is_written() -> None:
    """The pre-emptive validation exists so an operator gets a problem+json naming the
    missing field instead of a 500 out of an IntegrityError — and the refusal must be
    the ROUTE's, which is only observable here."""
    tenant_id, _slug = await _tenant()
    token = await _make_admin()
    async with _client() as http:
        response = await http.post(
            KYC.format(tenant_id=tenant_id),
            headers=_auth(token),
            json={"status": "verified", "entity_type": "sole_proprietorship"},
        )
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["type"].endswith("/kyc_document_required"), body
    assert body["remediation"], "a refusal an operator meets must say what to do"

    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT count(*) FROM kyc_records WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar_one()
    assert rows == 0
    assert await _audit(tenant_id, "kyc.recorded") == []


async def test_the_kyc_record_this_route_writes_is_the_one_the_client_reads() -> None:
    """The two halves of SURFACES §2b's gate, joined at the wire: ops records, and the
    client's own `GET /v1/compliance/kyc` reports `is_verified` off the same row. A
    computed field the console must not answer for itself
    (`compliance/kyc_routes.py:77`) is worth proving end to end once."""
    tenant_id, slug = await _tenant()
    admin_token = await _make_admin()
    member = await _make_member(tenant_id, role="owner")
    async with _client() as http:
        before = await http.get(
            "/v1/compliance/kyc",
            headers={"Authorization": f"Bearer {member}", "X-Org-Slug": slug},
        )
        await http.post(
            KYC.format(tenant_id=tenant_id),
            headers=_auth(admin_token),
            json={
                "status": "verified",
                "entity_type": "llp",
                "document_kind": "llpin",
                "document_ref": "AAB-1234",
            },
        )
        after = await http.get(
            "/v1/compliance/kyc",
            headers={"Authorization": f"Bearer {member}", "X-Org-Slug": slug},
        )
    assert before.status_code == 200 and after.status_code == 200, after.text
    assert before.json()["recorded"] is False
    assert before.json()["is_verified"] is False
    body = after.json()
    assert body["recorded"] is True
    assert body["is_verified"] is True
    assert body["document_ref"] == "AAB-1234"


async def test_a_mistyped_tenant_id_is_a_404_on_every_one_of_these_routes() -> None:
    """THE SECOND DEFECT THIS FILE FOUND, and it was three routes wearing one shape.

    Every one of these names its tenant in the PATH — an operator copies the id off a
    console URL — and three of the five had nothing between that id and an INSERT
    carrying it as a foreign key:

    * `POST …/dlt-templates` answered **500 `internal_error`**: "Something went wrong.
      The team has been alerted." The team WAS alerted, for a typo.
    * `POST …/kyc` answered the same 500, from `kyc_records.tenant_id`.
    * `POST …/numbers` answered **409 `number_taken`** — "This number is already
      provisioned; it may belong to another account — check before reassigning it."
      `agents_service.provision_number` maps every `IntegrityError` to that code, which
      is right for the UNIQUE index it was written for and wrong for the tenant FK. It
      sent an operator looking for the holder of a number nobody holds.

    The fix is the predicate that already existed for exactly this: `tenant_exists`,
    whose own docstring says callers turn a False into a 404 "rather than an FK
    violation rendered as a 500, or worse a cheerful 200". `set_tenant_status` and
    `record_commercial_terms` already asked it; these three now do too.

    Driven for all five, so the two that were already right stay right.
    """
    absent = uuid.uuid4()
    token = await _make_admin()
    async with _client() as http:
        answers = {
            "numbers": await http.post(
                NUMBERS.format(tenant_id=absent),
                headers=_auth(token),
                json={"e164": _e164(), "series": "160"},
            ),
            "number_status": await http.post(
                NUMBER_DLT.format(tenant_id=absent, number_id=uuid.uuid4()),
                headers=_auth(token),
                json={"dlt_status": "registered"},
            ),
            "templates": await http.post(
                TEMPLATES.format(tenant_id=absent),
                headers=_auth(token),
                json={"classification": "service", "body": TEMPLATE_BODY},
            ),
            "template_status": await http.post(
                TEMPLATE_STATUS.format(tenant_id=absent, template_id=uuid.uuid4()),
                headers=_auth(token),
                json={"status": "approved"},
            ),
            "kyc": await http.post(
                KYC.format(tenant_id=absent),
                headers=_auth(token),
                json={"status": "in_review"},
            ),
        }
    for name, response in answers.items():
        assert response.status_code == 404, f"{name}: {response.text}"
        body = response.json()
        assert body["type"].endswith("/not_found"), f"{name}: {body}"
        assert body["kind"] == "not_found", f"{name}: {body}"

    # Nothing was written for a tenant that does not exist.
    async with admin_session() as session:
        counts = (
            await session.execute(
                text(
                    "SELECT (SELECT count(*) FROM phone_numbers WHERE tenant_id = :t), "
                    "(SELECT count(*) FROM dlt_templates WHERE tenant_id = :t), "
                    "(SELECT count(*) FROM kyc_records WHERE tenant_id = :t)"
                ),
                {"t": absent},
            )
        ).one()
    assert tuple(counts) == (0, 0, 0)


async def test_a_genuinely_taken_number_still_says_so() -> None:
    """The other half of the `number_taken` fix: the 409 that was over-applied is still
    the answer to the case it was written for. Two tenants, one number — the UNIQUE
    index on `phone_numbers.e164` is global, which is why the collision is caught from
    the constraint rather than by probing under RLS (`agents/service.py:673`)."""
    tenant_id, _slug = await _tenant()
    other_id, _other_slug = await _tenant()
    token = await _make_admin()
    e164 = _e164()
    async with _client() as http:
        first = await http.post(
            NUMBERS.format(tenant_id=tenant_id),
            headers=_auth(token),
            json={"e164": e164, "series": "160"},
        )
        second = await http.post(
            NUMBERS.format(tenant_id=other_id),
            headers=_auth(token),
            json={"e164": e164, "series": "160"},
        )
    assert first.status_code == 201, first.text
    assert second.status_code == 409, second.text
    body = second.json()
    assert body["type"].endswith("/number_taken"), body
    assert body["remediation"], "a refusal an operator meets must say what to do"


async def test_the_admin_session_never_sees_the_tenant_row_it_writes() -> None:
    """Hard rule 1, from the direction that is easy to get wrong on this family of
    routes: the handler holds an `AdminSession` for the audit chain AND opens
    `tenant_session(tenant_id)` for the work. If the work ever moved onto the admin
    session it would still pass every test above — and would be writing outside RLS."""
    tenant_id, _slug = await _tenant()
    token = await _make_admin()
    async with _client() as http:
        await http.post(
            TEMPLATES.format(tenant_id=tenant_id),
            headers=_auth(token),
            json={"classification": "service", "body": TEMPLATE_BODY},
        )
    async with admin_session() as session:
        visible = (
            await session.execute(
                text("SELECT count(*) FROM dlt_templates WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar_one()
    assert visible == 0, (
        "the admin DB role can see a tenant's DLT templates — `admin_session` is for "
        "the directory and the audit chain, never for tenant data (hard rule 1)"
    )
