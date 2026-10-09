"""Numbers in a client's own ThinnestAI workspace: business details, buy, release (D-693).

The vendor is `tests/thinnest_fake_account.py`, built from `thinnest-findings/mirror/
snapshots/2026-10-08/pages/api-reference/phone-numbers/` (`rent-phone-number.md`,
`release-phone-number.md`, `search-available-phone-numbers.md`, `list-available-cities.md`,
`send-business-details.md`, `get-business-details.md`).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing.service import get_balance, record_entry
from apps.api.campaigns import engine_business_details as details_module
from apps.api.campaigns import engine_numbers
from apps.api.campaigns.engine_number_purchase import (
    forget_engine_number,
    purchase_engine_number,
    purchase_readiness,
    release_engine_number,
)
from apps.api.campaigns.number_pricing import record_attested_price_inr
from apps.api.compliance.kyc import NumberingSubmission
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine.thinnest import _charged_inr
from apps.workers import engine_workspaces as jobs
from sqlalchemy import text
from tests.conftest import accept_agreements
from tests.thinnest_fake_account import FakeAccount
from tests.workspace_support import give_own_workspace

pytestmark = [pytest.mark.rls]


async def _attested() -> Decimal:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
        price = await record_attested_price_inr(
            session, inr_per_month=Decimal("499.00"), source="D-693 test", attested_by=admin_id
        )
    return price.inr_per_month


async def _client(
    account: FakeAccount, *, approved: bool = True, verified: bool = True
) -> tuple[UUID, str]:
    created = await admin_service.create_organization(
        name="Own Numbers Clinic",
        slug=f"own-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = UUID(str(created["id"]))
    await accept_agreements(tenant_id, kyc_and_pledge=verified)
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("5000.00"),
            reason="topup",
            ref=f"UTR-{uuid.uuid4().hex[:10]}",
        )
    workspace = account.add_customer(f"calevate-{tenant_id}")
    await give_own_workspace(
        tenant_id,
        workspace=workspace,
        business_status="accepted" if approved else "submitted",
        can_rent=approved,
    )
    account.ws(workspace).business = {
        "status": "accepted" if approved else "submitted",
        "canRent": approved,
    }
    return tenant_id, workspace


async def _live_agent(tenant_id: UUID, workspace: str | None) -> tuple[UUID, str]:
    ref = f"ag_{uuid.uuid4().hex[:10]}" + (f"@{workspace}" if workspace else "")
    async with tenant_session(tenant_id) as session:
        agent_id = (
            await session.execute(
                text("SELECT id FROM agents WHERE tenant_id = :tid ORDER BY created_at LIMIT 1"),
                {"tid": tenant_id},
            )
        ).scalar_one()
        await session.execute(
            text(
                "UPDATE agents SET engine_agent_ref = :ref, engine = 'thinnest', status = 'live' "
                "WHERE id = :aid"
            ),
            {"ref": ref, "aid": agent_id},
        )
    return UUID(str(agent_id)), ref


async def _balance(tenant_id: UUID) -> Decimal:
    async with tenant_session(tenant_id) as session:
        return (await get_balance(session, tenant_id=tenant_id)).amount_inr


async def _row(tenant_id: UUID, number_id: UUID) -> Any:
    async with tenant_session(tenant_id) as session:
        return (
            await session.execute(
                text(
                    "SELECT engine_number_ref, client_inr_per_month, agent_id, released_at "
                    "FROM phone_numbers WHERE id = :id"
                ),
                {"id": number_id},
            )
        ).one()


# --- the gates ----------------------------------------------------------------------------


async def test_the_purchase_steps_walk_workspace_kyc_details_then_ready(
    account: FakeAccount,
) -> None:
    price = await _attested()
    tenant_id, _ws = await _client(account, approved=False)
    async with tenant_session(tenant_id) as session:
        readiness = await purchase_readiness(session, tenant_id=tenant_id)
    assert (readiness.step, readiness.blocker) == (
        "business_details",
        "business_details_not_approved",
    )
    await give_own_workspace(tenant_id, business_status="accepted", can_rent=True, workspace=_ws)
    async with tenant_session(tenant_id) as session:
        readiness = await purchase_readiness(session, tenant_id=tenant_id)
    assert (readiness.step, readiness.client_inr_per_month) == ("ready", price)
    await give_own_workspace(tenant_id, status="pending")
    async with tenant_session(tenant_id) as session:
        readiness = await purchase_readiness(session, tenant_id=tenant_id)
    assert readiness.step == "workspace"


async def test_an_unverified_business_is_told_to_verify_first(account: FakeAccount) -> None:
    await _attested()
    tenant_id, _ws = await _client(account, verified=False)
    async with tenant_session(tenant_id) as session:
        readiness = await purchase_readiness(session, tenant_id=tenant_id)
    assert readiness.step == "verify_business"
    with pytest.raises(ProblemError) as refused:
        await purchase_engine_number(
            tenant_id=tenant_id,
            number=account.available[0],
            agent_id=None,
            direction="both",
            idempotency_key=f"key-{uuid.uuid4().hex}",
            requested_by="client",
        )
    assert refused.value.code == "kyc_not_verified"
    assert not [s for s in account.sent if s.method == "POST" and s.path == "/phone-numbers"]


# --- buying -------------------------------------------------------------------------------


async def test_a_purchase_rents_in_the_clients_name_charges_our_price_and_attaches(
    account: FakeAccount,
) -> None:
    price = await _attested()
    tenant_id, workspace = await _client(account)
    agent_id, agent_ref = await _live_agent(tenant_id, workspace)
    before = await _balance(tenant_id)
    number = account.available[0]
    key = f"key-{uuid.uuid4().hex}"

    bought = await purchase_engine_number(
        tenant_id=tenant_id,
        number=number,
        agent_id=agent_id,
        direction="both",
        idempotency_key=key,
        requested_by="client",
    )

    rent = [s for s in account.sent if s.method == "POST" and s.path == "/phone-numbers"]
    assert [s.workspace for s in rent] == [workspace]
    ref, client_inr, bound, released = await _row(tenant_id, bought.number_id)
    assert ref == f"{number}@{workspace}" and client_inr == price and released is None
    assert bound == agent_id
    assert bought.first_period == "charged"
    assert await _balance(tenant_id) == before - price
    assert account.ws(workspace).numbers[number]["agent"] == agent_ref.split("@")[0]

    again = await purchase_engine_number(
        tenant_id=tenant_id,
        number=number,
        agent_id=agent_id,
        direction="both",
        idempotency_key=key,
        requested_by="client",
    )
    assert again.replayed and again.number_id == bought.number_id
    assert again.first_period == "replayed"
    assert len([s for s in account.sent if s.method == "POST" and s.path == "/phone-numbers"]) == 1
    assert await _balance(tenant_id) == before - price


async def test_a_number_somebody_else_holds_is_refused_and_nothing_is_charged(
    account: FakeAccount,
) -> None:
    await _attested()
    tenant_id, _workspace = await _client(account)
    number = account.available[1]
    account.hold("org_elsewhere", number)
    before = await _balance(tenant_id)
    key = f"key-{uuid.uuid4().hex}"
    for _ in range(2):
        with pytest.raises(ProblemError) as refused:
            await purchase_engine_number(
                tenant_id=tenant_id,
                number=number,
                agent_id=None,
                direction="both",
                idempotency_key=key,
                requested_by="client",
            )
        assert refused.value.code == "engine_number_unavailable"
    assert await _balance(tenant_id) == before
    async with tenant_session(tenant_id) as session:
        held = (
            await session.execute(
                text("SELECT count(*) FROM phone_numbers WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar_one()
    assert held == 0


async def test_an_agent_still_in_the_platform_account_is_refused_before_renting(
    account: FakeAccount,
) -> None:
    await _attested()
    tenant_id, _workspace = await _client(account)
    agent_id, _ref = await _live_agent(tenant_id, None)
    with pytest.raises(ProblemError) as refused:
        await purchase_engine_number(
            tenant_id=tenant_id,
            number=account.available[2],
            agent_id=agent_id,
            direction="both",
            idempotency_key=f"key-{uuid.uuid4().hex}",
            requested_by="client",
        )
    assert refused.value.code == "engine_number_agent_not_moved"
    assert not [s for s in account.sent if s.method == "POST" and s.path == "/phone-numbers"]


async def test_search_and_cities_are_read_in_the_clients_workspace_with_our_price(
    account: FakeAccount,
) -> None:
    await _attested()
    tenant_id, workspace = await _client(account)
    async with tenant_session(tenant_id) as session:
        cities = await engine_numbers.available_cities(session, tenant_id)
        page = await engine_numbers.search_available(
            session, tenant_id, city="Bangalore", pattern=None, cursor=None
        )
        second = await engine_numbers.search_available(
            session, tenant_id, city="Bangalore", pattern=None, cursor=page.next_cursor
        )
    assert [c.name for c in cities] == ["Bangalore"]
    assert len(page.numbers) == 20 and page.next_cursor == "20"
    assert len(second.numbers) == 5 and second.next_cursor is None
    assert page.numbers[0].vendor_monthly_inr == Decimal("349")
    assert {s.workspace for s in account.sent if "/available" in s.path} == {workspace}


# --- releasing ------------------------------------------------------------------------------


async def test_a_release_is_confirmed_at_the_vendor_and_stops_our_charge(
    account: FakeAccount,
) -> None:
    """Audit fix 1: an engine-held number can be released, and its billing stops."""
    await _attested()
    tenant_id, workspace = await _client(account)
    bought = await purchase_engine_number(
        tenant_id=tenant_id,
        number=account.available[3],
        agent_id=None,
        direction="both",
        idempotency_key=f"key-{uuid.uuid4().hex}",
        requested_by="client",
    )
    async with tenant_session(tenant_id) as session:
        assert await release_engine_number(
            session, tenant_id=tenant_id, number_id=bought.number_id, by_admin=False
        )
    release = [s for s in account.sent if s.method == "DELETE" and "/phone-numbers/" in s.path]
    assert [(s.workspace, s.query.get("confirm")) for s in release] == [(workspace, "release")]
    assert account.available[3] not in account.ws(workspace).numbers
    _ref, _inr, bound, released = await _row(tenant_id, bought.number_id)
    assert released is not None and bound is None
    async with tenant_session(tenant_id) as session:
        renewing = (
            await session.execute(
                text(
                    "SELECT count(*) FROM phone_numbers WHERE id = :id "
                    "AND client_inr_per_month IS NOT NULL AND released_at IS NULL"
                ),
                {"id": bought.number_id},
            )
        ).scalar_one()
        assert renewing == 0
        assert not await release_engine_number(
            session, tenant_id=tenant_id, number_id=bought.number_id, by_admin=False
        )


async def _recorded(tenant_id: UUID, ref: str, *, priced: bool = True) -> UUID:
    number_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, e164, series, provider, "
                "engine_number_ref, engine_owned, direction, client_inr_per_month, created_at, "
                "updated_at) VALUES (:id, :tid, :e164, 'standard', 'thinnest', :ref, true, "
                "'both', :inr, now(), now())"
            ),
            {
                "id": number_id,
                "tid": tenant_id,
                "e164": "+" + ref.split("@")[0],
                "ref": ref,
                "inr": Decimal("499.00") if priced else None,
            },
        )
    return number_id


async def test_our_record_of_a_number_the_vendor_lost_can_be_released(
    account: FakeAccount,
) -> None:
    """Audit fix 1: the route `engine_number_missing_at_vendor` asks for."""
    tenant_id, workspace = await _client(account)
    gone = await _recorded(tenant_id, f"{account.available[4]}@{workspace}")
    held_digits = account.available[5]
    account.hold(workspace, held_digits)
    still = await _recorded(tenant_id, f"{held_digits}@{workspace}")
    test_digits = account.available[6]
    account.hold(None, test_digits, agent="ag_legacy")
    platform = await _recorded(tenant_id, test_digits)
    async with tenant_session(tenant_id) as session:
        assert await forget_engine_number(session, tenant_id=tenant_id, number_id=gone)
        with pytest.raises(ProblemError) as refused:
            await forget_engine_number(session, tenant_id=tenant_id, number_id=still)
        assert refused.value.code == "engine_number_still_held"
        assert await forget_engine_number(session, tenant_id=tenant_id, number_id=platform)
    assert (await _row(tenant_id, gone))[3] is not None
    assert account.ws(None).numbers[test_digits]["agent"] is None


async def test_a_client_cannot_release_a_number_held_in_the_platform_account(
    account: FakeAccount,
) -> None:
    tenant_id, _workspace = await _client(account)
    digits = account.available[7]
    account.hold(None, digits)
    number_id = await _recorded(tenant_id, digits)
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as refused:
            await release_engine_number(
                session, tenant_id=tenant_id, number_id=number_id, by_admin=False
            )
        assert refused.value.kind == "not_found"
        assert await release_engine_number(
            session, tenant_id=tenant_id, number_id=number_id, by_admin=True
        )


# --- recording (audit fixes 2 and 3) --------------------------------------------------------


async def test_a_number_lent_to_another_clients_agent_is_refused(account: FakeAccount) -> None:
    """Audit fix 2: `callingAgent` counts as much as `agent` does."""
    await _attested()
    tenant_id, workspace = await _client(account)
    digits = account.available[8]
    account.hold(workspace, digits, calling="ag_someone_else")
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as refused:
            await engine_numbers.record_engine_number(
                session,
                tenant_id=tenant_id,
                e164=f"+{digits}",
                direction="both",
                agent_id=None,
                purpose=None,
            )
    assert refused.value.code == "engine_number_lent_to_other_client"


async def test_the_first_month_is_reported_as_what_actually_happened(
    account: FakeAccount, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Audit fix 3: a trial, a closed account or a replay charges nothing, and the result
    says so rather than "charged"."""
    await _attested()
    tenant_id, workspace = await _client(account)
    digits = account.available[9]
    account.hold(workspace, digits)

    async def _trial(*_a: Any, **_k: Any) -> str:
        return "trial"

    monkeypatch.setattr(engine_numbers, "collect_number_rental", _trial)
    async with tenant_session(tenant_id) as session:
        recorded = await engine_numbers.record_engine_number(
            session,
            tenant_id=tenant_id,
            e164=f"+{digits}",
            direction="both",
            agent_id=None,
            purpose=None,
        )
    assert recorded.first_period == "trial"


# --- business details ---------------------------------------------------------------------


def _bundle(tenant_id: UUID) -> NumberingSubmission:
    return NumberingSubmission(
        tenant_id=tenant_id,
        legal_business_name="Own Numbers Clinic Pvt Ltd",
        gst_registered=True,
        document_kind="gst",
        document_id=uuid.uuid4(),
        object_key="kyc-documents/x/y",
        filename="gst.pdf",
        content_type="application/pdf",
        size_bytes=10,
    )


@pytest.fixture
def kyc_bundle(monkeypatch: pytest.MonkeyPatch) -> dict[UUID, NumberingSubmission]:
    """The KYC lane's bundle and its sealed file, without object storage."""
    bundles: dict[UUID, NumberingSubmission] = {}

    class _Doc:
        def __init__(self, doc_id: UUID) -> None:
            self.id = doc_id

        def envelope(self, ciphertext: bytes) -> bytes:
            return ciphertext

    async def _bundle_of(_session: Any, *, tenant_id: UUID) -> NumberingSubmission | None:
        return bundles.get(tenant_id)

    async def _docs(_session: Any, *, tenant_id: UUID) -> dict[str, Any]:
        bundle = bundles.get(tenant_id)
        return {"business": _Doc(bundle.document_id)} if bundle else {}

    async def _read(_key: str) -> bytes:
        return b"%PDF-1.7 certificate"

    import apps.workers.storage as storage

    monkeypatch.setattr(details_module, "numbering_submission_bundle", _bundle_of)
    monkeypatch.setattr(details_module, "current_documents", _docs)
    monkeypatch.setattr(details_module, "open_document", lambda **kw: kw["envelope"])
    monkeypatch.setattr(storage, "read_kb_object", _read)
    return bundles


async def test_verified_details_are_sent_to_the_clients_own_workspace(
    account: FakeAccount, kyc_bundle: dict[UUID, NumberingSubmission]
) -> None:
    tenant_id, workspace = await _client(account, approved=False)
    account.ws(workspace).business = {"status": "none"}
    assert (
        await jobs.submit_engine_business_details({}, {"tenant_id": str(tenant_id)})
        == "business_details_kyc_not_verified"
    )
    assert not [s for s in account.sent if s.method == "PUT"]
    kyc_bundle[tenant_id] = _bundle(tenant_id)

    assert (
        await jobs.submit_engine_business_details({}, {"tenant_id": str(tenant_id)}) == "submitted"
    )

    [sent] = [s for s in account.sent if s.method == "PUT"]
    assert sent.workspace == workspace and sent.path == "/phone-numbers/business-details"
    assert b'name="businessName"' in sent.body and b"Own Numbers Clinic Pvt Ltd" in sent.body
    assert b'name="documentKind"' in sent.body and b"gst" in sent.body
    async with tenant_session(tenant_id) as session:
        status = (
            await session.execute(
                text("SELECT business_status FROM tenant_engine_workspaces WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
        ).scalar_one()
    assert status == "submitted"


async def test_the_sweep_resends_an_expired_application_and_alarms_a_rejection_once(
    account: FakeAccount,
    kyc_bundle: dict[UUID, NumberingSubmission],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expired, ws_expired = await _client(account)
    rejected, ws_rejected = await _client(account)
    account.ws(ws_expired).business = {"status": "expired"}
    account.ws(ws_rejected).business = {"status": "rejected", "reviewNote": "Name mismatch."}
    alarms: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(engine_numbers, "alert", lambda _k, code, **kw: alarms.append((code, kw)))

    async def _only_ours(**_kw: Any) -> list[Any]:
        from apps.api.tenancy.engine_workspace import WorkspaceRow

        return [
            WorkspaceRow(tenant_id=expired, status="active", workspace_id=ws_expired),
            WorkspaceRow(tenant_id=rejected, status="active", workspace_id=ws_rejected),
        ]

    import apps.workers.workspace_walk as walk

    monkeypatch.setattr(walk, "active_workspaces", _only_ours)
    await jobs.sweep_engine_workspaces({})
    await jobs.sweep_engine_workspaces({})

    async with untenanted_session() as session:
        queued = (
            await session.execute(
                text(
                    "SELECT payload->>'tenant_id' FROM outbox_messages "
                    "WHERE job = 'submit_engine_business_details' "
                    "AND payload->>'tenant_id' IN (:a, :b)"
                ),
                {"a": str(expired), "b": str(rejected)},
            )
        ).scalars()
        resent = list(queued)
    assert str(expired) in resent and resent.count(str(expired)) >= 2
    assert [kw["tenant_id"] for code, kw in alarms if code == "engine_business_details_lapsed"] == [
        str(rejected)
    ]
    async with tenant_session(rejected) as session:
        note = (
            await session.execute(
                text(
                    "SELECT business_review_note FROM tenant_engine_workspaces WHERE tenant_id = :t"
                ),
                {"t": rejected},
            )
        ).scalar_one()
    assert note == "Name mismatch."


# --- one charge parser (audit fix 4) --------------------------------------------------------


@pytest.mark.parametrize(
    ("row", "inr"),
    [
        ({"costMicro": 6_370_000, "currency": "INR"}, Decimal("6.37")),
        ({"costMicro": 6_370_000}, Decimal("6.37")),
        ({"costMicro": 6_370_000, "currency": "USD"}, None),
        ({"costMicro": -5, "currency": "INR"}, None),
        ({"costMicro": True, "currency": "INR"}, None),
        ({"costMicro": None, "currency": "INR"}, None),
    ],
)
def test_one_reading_of_a_charge_for_the_call_and_the_usage_log(
    row: dict[str, Any], inr: Decimal | None
) -> None:
    assert _charged_inr(row) == inr
