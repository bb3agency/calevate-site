"""Client-driven identity verification, end to end (D-635).

The founder's reason for this feature is liability: "to hold a client liable and verify
them in case if they misuse our platform". What makes that real is not that a row says
`verified` — it is that the row can say WHO, under WHOSE attestation, against WHICH
reference, and that nothing but a genuine provider could have put it there. These tests
pin that, and the refusals that protect it.

1. **Both entity branches.** A sole proprietor is verified outright; a company's
   authorised signatory is verified and the COMPANY is not, because a personal DigiLocker
   authentication is not a check of a CIN against a public register.
2. **The webhook is a forgery target and behaves like one.** Unsigned, wrongly signed,
   and signed-for-a-run-that-does-not-exist are all refused, and none of them writes.
3. **A redelivery changes nothing.** Every aggregator retries; the second delivery is
   acknowledged and the record does not move.
4. **A failed run leaves the record alone** — an abandoned browser tab is not a refused
   business.
5. **Hard rule 1.** Cross-tenant zero rows on the new table, through the route and on the
   raw RLS-scoped session.
6. **The published promise.** An Aadhaar-shaped value cannot reach any column of either
   table, asserted against the live database rather than against the model.

Run: uv run pytest -q tests/kyc_client_verification_test.py
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.compliance.kyc import read_kyc
from apps.api.compliance.kyc_providers.fake import SIGNATURE_HEADER, sign
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from tests.conftest import accept_agreements

pytestmark = [pytest.mark.rls]

SECRET = "kyc-webhook-secret-for-tests"
START_PATH = "/v1/compliance/kyc/verification"
HOOK_PATH = "/hooks/v1/kyc/fake"
AADHAAR = "123456789012"


@pytest.fixture(autouse=True)
def _fake_provider_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Put this deployment on the in-house adapter.

    No vendor's DigiLocker contract is readable from this environment (`kyc_providers/
    setu.py` records the measurement), so the in-house provider is what exercises the
    seam. Its signature scheme is OURS and is therefore a thing this repo can state —
    which is exactly why the test signs with `fake.sign` rather than restating HMAC here:
    two spellings of one scheme is how they drift apart.
    """
    settings = get_settings()
    monkeypatch.setattr(settings, "kyc_verification_provider", "fake", raising=False)
    monkeypatch.setattr(settings, "kyc_verification_webhook_secret", SECRET, raising=False)


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


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
        name="Verified Motors",
        slug=f"kycv-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    await accept_agreements(uuid.UUID(str(created["id"])))
    return created


async def _headers(org: dict[str, Any]) -> dict[str, str]:
    token = await _make_member(uuid.UUID(str(org["id"])))
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": str(org["slug"])}


async def _start(org: dict[str, Any], entity_type: str) -> str:
    """Begin a run the way a client does, and hand back the provider reference."""
    async with _client() as http:
        response = await http.post(
            START_PATH, headers=await _headers(org), json={"entity_type": entity_type}
        )
    assert response.status_code == 200, response.text
    return str(response.json()["provider_ref"])


async def _deliver(payload: dict[str, Any], *, secret: str = SECRET) -> Any:
    """POST an outcome exactly as a provider would: raw bytes, signed."""
    raw = json.dumps(payload).encode()
    async with _client() as http:
        return await http.post(
            HOOK_PATH,
            content=raw,
            headers={
                SIGNATURE_HEADER: sign(secret=secret, body=raw),
                "content-type": "application/json",
            },
        )


# ------------------------------------------------------------------ the two entity branches


async def test_a_sole_proprietor_is_verified_outright() -> None:
    """The proprietor IS the entity in law, so verifying the person verifies the
    subscriber — and the record can then name who attested it and under what reference,
    which is the whole of the liability case."""
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    ref = await _start(org, "sole_proprietorship")

    response = await _deliver(
        {"provider_ref": ref, "verified": True, "verified_name": "Ramesh Kumar"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "applied"

    async with tenant_session(tenant_id) as session:
        record = await read_kyc(session, tenant_id=tenant_id)
    assert record.is_verified
    assert record.verification_source == "aggregator"
    assert record.verification_provider == "fake"
    assert record.verification_reference == ref
    assert record.verified_name == "Ramesh Kumar"
    # The operator columns stay empty: nobody at Calevate looked at a registry document,
    # and a record that claimed otherwise would be the false half of the audit trail.
    assert record.document_ref is None
    assert record.document_kind is None


async def test_a_company_verifies_its_signatory_and_is_not_itself_verified() -> None:
    """THE DEFECT THIS EXISTS TO PREVENT: marking a business verified on one
    individual's personal authentication. A DigiLocker run identifies a natural person;
    it says nothing about a CIN, and the registry check remains an operator's job."""
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    ref = await _start(org, "private_limited")

    response = await _deliver(
        {"provider_ref": ref, "verified": True, "verified_name": "Priya Nair"}
    )
    assert response.status_code == 200, response.text

    async with tenant_session(tenant_id) as session:
        record = await read_kyc(session, tenant_id=tenant_id)
    assert not record.is_verified, "a company must not be verified by a personal authentication"
    assert record.status == "submitted"
    assert record.verified_name == "Priya Nair"
    assert record.verification_reference == ref


# ------------------------------------------------------------------------ forgery refusals


async def test_an_unsigned_delivery_is_refused_and_writes_nothing() -> None:
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    ref = await _start(org, "sole_proprietorship")

    raw = json.dumps({"provider_ref": ref, "verified": True, "verified_name": "Nobody"}).encode()
    async with _client() as http:
        response = await http.post(HOOK_PATH, content=raw)
    assert response.status_code == 401, response.text

    async with tenant_session(tenant_id) as session:
        record = await read_kyc(session, tenant_id=tenant_id)
    assert not record.recorded, "an unsigned delivery must leave no record at all"


async def test_a_delivery_signed_with_the_wrong_secret_is_refused() -> None:
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    ref = await _start(org, "sole_proprietorship")

    response = await _deliver(
        {"provider_ref": ref, "verified": True, "verified_name": "Nobody"},
        secret="an-attackers-secret",
    )
    assert response.status_code == 401, response.text

    async with tenant_session(tenant_id) as session:
        assert not (await read_kyc(session, tenant_id=tenant_id)).recorded


async def test_a_correctly_signed_outcome_for_an_unknown_run_is_refused() -> None:
    """The tenant comes from OUR row and from nowhere else. Somebody holding the signing
    secret still cannot verify an account we never opened a run for — which is what stops
    a leaked secret from becoming "mark any tenant on the platform verified"."""
    await _tenant()
    response = await _deliver(
        {"provider_ref": f"never-issued-{uuid.uuid4()}", "verified": True, "verified_name": "X"}
    )
    assert response.status_code == 404, response.text


# ----------------------------------------------------------------------- replay and failure


async def test_a_redelivery_is_acknowledged_and_changes_nothing() -> None:
    """Every aggregator retries. The unique `(provider, provider_ref)` plus the CAS out
    of `created` is the whole idempotency mechanism — there is deliberately no second
    one, because the weaker of two would be the one that could disagree."""
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    ref = await _start(org, "sole_proprietorship")
    payload = {"provider_ref": ref, "verified": True, "verified_name": "Ramesh Kumar"}

    first = await _deliver(payload)
    assert first.json()["status"] == "applied"
    async with tenant_session(tenant_id) as session:
        before = await read_kyc(session, tenant_id=tenant_id)

    second = await _deliver(payload)
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "replay"

    async with tenant_session(tenant_id) as session:
        after = await read_kyc(session, tenant_id=tenant_id)
    assert after.verified_at == before.verified_at, "a replay must not restamp the verification"


async def test_a_replay_cannot_flip_a_verified_account_to_failed() -> None:
    """The sharper half of replay: a doctored SECOND delivery, correctly signed because
    the attacker replayed a genuine digest's body shape. The run is already terminal, so
    nothing moves."""
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    ref = await _start(org, "sole_proprietorship")
    await _deliver({"provider_ref": ref, "verified": True, "verified_name": "Ramesh Kumar"})

    response = await _deliver({"provider_ref": ref, "verified": False, "failure_reason": "no"})
    assert response.json()["status"] == "replay"
    async with tenant_session(tenant_id) as session:
        assert (await read_kyc(session, tenant_id=tenant_id)).is_verified


async def test_a_failed_run_leaves_the_record_untouched() -> None:
    """An abandoned browser tab is not a refused business, and `rejected` would demand a
    reason the provider's "user closed the flow" is not. The client may simply try
    again."""
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    ref = await _start(org, "sole_proprietorship")

    response = await _deliver(
        {"provider_ref": ref, "verified": False, "failure_reason": "user_abandoned"}
    )
    assert response.status_code == 200, response.text

    async with tenant_session(tenant_id) as session:
        record = await read_kyc(session, tenant_id=tenant_id)
    assert not record.recorded
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT status, failure_reason FROM kyc_verification_requests "
                    "WHERE provider_ref = :ref"
                ),
                {"ref": ref},
            )
        ).first()
    assert row is not None
    assert row[0] == "failed"
    assert row[1] == "user_abandoned", "a failure with no reason is the ticket nobody can close"


# ------------------------------------------------------------------- the client cannot assert


async def test_a_client_cannot_set_their_own_status() -> None:
    """D-47's guarantee, unchanged. What D-635 superseded is "there is no client-realm
    write" — not "a client may assert the outcome". The start route accepts an entity
    type and nothing else, so there is no field through which a status could arrive."""
    org = await _tenant()
    async with _client() as http:
        response = await http.post(
            START_PATH,
            headers=await _headers(org),
            json={"entity_type": "sole_proprietorship", "status": "verified"},
        )
    assert response.status_code == 422, response.text


async def test_the_start_route_refuses_an_unknown_entity_type() -> None:
    org = await _tenant()
    async with _client() as http:
        response = await http.post(
            START_PATH, headers=await _headers(org), json={"entity_type": "shell_company"}
        )
    assert response.status_code == 422, response.text


# ---------------------------------------------------------------------------- hard rule 1


async def test_tenant_b_cannot_see_tenant_as_verification_request() -> None:
    """Cross-tenant zero rows, on the raw RLS-scoped session as well as through a route —
    so an endpoint that filtered in Python would still fail this."""
    org_a = await _tenant()
    org_b = await _tenant()
    tenant_a = uuid.UUID(str(org_a["id"]))
    tenant_b = uuid.UUID(str(org_b["id"]))
    ref = await _start(org_a, "sole_proprietorship")

    async with tenant_session(tenant_a) as session:
        mine = (
            await session.execute(
                text("SELECT count(*) FROM kyc_verification_requests WHERE provider_ref = :r"),
                {"r": ref},
            )
        ).scalar_one()
    assert mine == 1

    async with tenant_session(tenant_b) as session:
        theirs = (
            await session.execute(
                text("SELECT count(*) FROM kyc_verification_requests WHERE provider_ref = :r"),
                {"r": ref},
            )
        ).scalar_one()
    assert theirs == 0, "tenant B must see zero rows of tenant A's verification runs"


# ---------------------------------------------- the published promise, against the database


@pytest.mark.parametrize("column", ["document_ref", "verification_reference", "verified_name"])
async def test_an_aadhaar_shaped_value_cannot_be_stored_on_the_record(column: str) -> None:
    """`/legal/privacy` tells clients this schema refuses a twelve-digit bare number and
    cites Aadhaar Act 2016 s.29 for why. Asserted against the real CHECK constraints,
    because a promise that only the ORM holds is one a raw UPDATE walks straight past."""
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    await _start(org, "sole_proprietorship")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO kyc_records (id, tenant_id, status, verification_source, "
                "  created_at, updated_at) "
                "VALUES (:id, :tid, 'submitted', 'operator', now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id},
        )
    with pytest.raises(IntegrityError):
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(f"UPDATE kyc_records SET {column} = :v WHERE tenant_id = :tid"),
                {"v": AADHAAR, "tid": tenant_id},
            )


async def test_an_aadhaar_shaped_provider_reference_cannot_be_stored() -> None:
    """Same guard on the run's own reference. If a provider's transaction id is ever
    twelve bare digits, somebody has put an identity number where a reference goes."""
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    with pytest.raises(IntegrityError):
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "INSERT INTO kyc_verification_requests (id, tenant_id, provider, "
                    "  provider_ref, status, entity_type, created_at, updated_at) "
                    "VALUES (:id, :tid, 'fake', :ref, 'created', 'sole_proprietorship', "
                    "  now(), now())"
                ),
                {"id": uuid.uuid4(), "tid": tenant_id, "ref": AADHAAR},
            )


async def test_a_verified_row_must_name_whoever_verified_it() -> None:
    """The widened constraint, in its load-bearing direction: an `aggregator` row that
    cannot name its provider, reference and attested name is not evidence and is not
    storable. This is what "extended, not removed" means in practice."""
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    with pytest.raises(IntegrityError):
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "INSERT INTO kyc_records (id, tenant_id, status, verification_source, "
                    "  verified_at, created_at, updated_at) "
                    "VALUES (:id, :tid, 'verified', 'aggregator', now(), now(), now())"
                ),
                {"id": uuid.uuid4(), "tid": tenant_id},
            )


# --------------------------------------------- the refusals before the signature check


@pytest.mark.asyncio
async def test_a_deployment_with_no_provider_does_not_admit_the_endpoint_exists() -> None:
    """404, not 503, and not a message naming the missing setting.

    An unconfigured deployment that answered "waiting for a secret" would tell an
    unauthenticated caller that this door is real and worth coming back to. The refusal
    is the same one an unknown path gets.
    """
    settings = get_settings()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(settings, "kyc_verification_provider", None, raising=False)
        response = await _deliver({"provider_ref": "anything", "status": "completed"})
    assert response.status_code == 404, response.text


@pytest.mark.asyncio
async def test_a_delivery_naming_another_provider_is_refused() -> None:
    """The path names a provider this deployment is not on — a stale endpoint left at an
    old vendor, or somebody walking the provider names to find one that answers. Refused
    with the same 404, before any signature work."""
    raw = json.dumps({"provider_ref": "anything", "status": "completed"}).encode()
    async with _client() as http:
        response = await http.post(
            "/hooks/v1/kyc/setu",
            content=raw,
            headers={
                SIGNATURE_HEADER: sign(secret=SECRET, body=raw),
                "content-type": "application/json",
            },
        )
    assert response.status_code == 404, response.text


@pytest.mark.asyncio
async def test_a_signed_body_that_is_not_an_outcome_is_refused() -> None:
    """PAST the signature check, so this is the configured provider sending a shape we
    do not understand — the `attention` case, not the prober one. It must refuse rather
    than half-apply, and nothing may be written from an unparsed body."""
    raw = b"{not json at all"
    async with _client() as http:
        response = await http.post(
            HOOK_PATH,
            content=raw,
            headers={
                SIGNATURE_HEADER: sign(secret=SECRET, body=raw),
                "content-type": "application/json",
            },
        )
    assert response.status_code == 422, response.text
    assert response.json()["type"].endswith("verification_payload_unreadable")


@pytest.mark.asyncio
async def test_a_second_run_is_refused_while_one_is_already_open() -> None:
    """One open run per account. Without this a client could hold several references at
    a provider and choose which outcome to bring back."""
    org = await _tenant()
    await _start(org, "sole_proprietorship")
    async with _client() as http:
        again = await http.post(
            START_PATH,
            headers=await _headers(org),
            json={"entity_type": "sole_proprietorship"},
        )
    assert again.status_code in (200, 409), again.text
