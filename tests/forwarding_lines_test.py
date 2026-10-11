"""Forwarded lines (D-746): tenancy, the client's choices, and the loop guard on every writer
of a phone a call is passed to."""

from __future__ import annotations

import uuid
from uuid import UUID

import pytest
from apps.api.agents import live_apply
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.forwarding import codes, service
from apps.api.main import app
from apps.api.tenancy import profile_service
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.forwarding_fixtures import add_line, give_calevate_number, make_client, owner

pytestmark = [pytest.mark.rls]

TABLES = ("forwarded_lines", "forwarding_tests", "save_number_messages")


async def _ready(prefix: str = "fwd") -> tuple[UUID, UUID, str, str]:
    tenant_id, agent_id, slug = await make_client(prefix)
    _, e164 = await give_calevate_number(tenant_id, agent_id)
    return tenant_id, agent_id, slug, e164


async def test_each_forwarding_table_shows_a_tenant_only_its_own_rows() -> None:
    first, *_ = await _ready("rls-a")
    second, *_ = await _ready("rls-b")
    line = await add_line(first)
    async with tenant_session(first) as session:
        await session.execute(
            text(
                "INSERT INTO forwarding_tests (id, tenant_id, line_id, status, settled_at) "
                "VALUES (:i, :t, :l, 'settled', now())"
            ),
            {"i": uuid.uuid4(), "t": first, "l": line.id},
        )
        await session.execute(
            text(
                "INSERT INTO save_number_messages (id, tenant_id, caller_ref) "
                "VALUES (:i, :t, 'ref')"
            ),
            {"i": uuid.uuid4(), "t": first},
        )
    async with tenant_session(second) as session:
        for table in TABLES:
            seen = (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
            assert seen == 0, table
    async with tenant_session(first) as session:
        for table in TABLES:
            seen = (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
            assert seen == 1, table


async def test_a_line_records_the_choice_and_the_attestation() -> None:
    tenant_id, *_ = await _ready()
    line = await add_line(tenant_id, number="98123 45670", ring_seconds=25)
    assert line.e164 == "+919812345670"
    assert (line.mode, line.ring_seconds, line.status) == ("conditional", 25, "untested")
    assert line.calevate_number_e164 is not None
    async with tenant_session(tenant_id) as session:
        row = (await session.execute(text("SELECT attested_by FROM forwarded_lines"))).scalar_one()
        audited = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE action = 'forwarding.line_added' "
                    "AND tenant_id = :t"
                ),
                {"t": tenant_id},
            )
        ).scalar_one()
    assert row is not None and audited == 1


@pytest.mark.parametrize(
    ("mode", "seconds"), [("conditional", 0), ("conditional", 7), ("all_calls", 20)]
)
async def test_the_ring_time_must_fit_the_mode(mode: str, seconds: int) -> None:
    tenant_id, *_ = await _ready()
    with pytest.raises(ProblemError) as refused:
        await add_line(tenant_id, mode=mode, ring_seconds=seconds)
    assert refused.value.code == "forwarding_ring_time_invalid"


async def test_all_calls_is_a_ring_time_of_zero() -> None:
    tenant_id, *_ = await _ready()
    line = await add_line(tenant_id, mode="all_calls", ring_seconds=0)
    assert (line.mode, line.ring_seconds) == ("all_calls", 0)


async def test_no_line_without_attestation_or_a_calevate_number() -> None:
    tenant_id, _, _, _ = await _ready()
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as unattested:
            await service.create_line(
                session,
                principal=owner(tenant_id),
                tenant_id=tenant_id,
                number="9812345671",
                line_kind="mobile",
                carrier="vi",
                mode="all_calls",
                ring_seconds=0,
                calevate_number_id=None,
                attest=False,
                ip=None,
            )
    assert unattested.value.code == "forwarding_attestation_required"
    bare, _, _ = await make_client("bare")
    with pytest.raises(ProblemError) as no_number:
        await add_line(bare)
    assert no_number.value.code == "forwarding_needs_calevate_number"


async def test_an_operator_cannot_attest_for_the_business() -> None:
    from apps.api.core.context import Principal

    tenant_id, *_ = await _ready()
    operator = Principal(
        realm="admin",
        user_id=uuid.uuid4(),
        tenant_id=tenant_id,
        role="superadmin",
        impersonating=True,
    )
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as refused:
            await service.create_line(
                session,
                principal=operator,
                tenant_id=tenant_id,
                number="9812345672",
                line_kind="mobile",
                carrier="vi",
                mode="all_calls",
                ring_seconds=0,
                calevate_number_id=None,
                attest=True,
                ip=None,
            )
    assert refused.value.code == "forwarding_attestation_personal"


async def test_the_calevate_number_itself_is_not_a_published_number() -> None:
    tenant_id, _, _, calevate = await _ready()
    with pytest.raises(ProblemError) as refused:
        await add_line(tenant_id, number=calevate)
    assert refused.value.code == "forwarding_number_is_calevate"


async def test_the_first_line_and_the_last_removal_republish_the_agents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reasons: list[str] = []

    async def _queue(session: object, **kwargs: object) -> uuid.UUID:
        reasons.append(str(kwargs["reason"]))
        return uuid.uuid4()

    monkeypatch.setattr(live_apply, "queue_live_apply", _queue)
    tenant_id, *_ = await _ready()
    first = await add_line(tenant_id)
    await add_line(tenant_id)
    assert reasons == ["forwarded_line"]
    async with tenant_session(tenant_id) as session:
        for line in await service.list_lines(session):
            await service.delete_line(
                session, principal=owner(tenant_id), tenant_id=tenant_id, line_id=line.id, ip=None
            )
    assert reasons == ["forwarded_line", "forwarded_line"]
    assert first.id


# --- the loop guard ------------------------------------------------------------------------


async def test_a_contact_may_not_be_a_published_number() -> None:
    tenant_id, *_ = await _ready()
    line = await add_line(tenant_id)
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as refused:
            await profile_service.save_contacts(
                session,
                tenant_id=tenant_id,
                contacts=[
                    profile_service.BusinessContactIn(label="Front desk", phone_e164=line.e164)
                ],
            )
    assert refused.value.code == service.LOOP_CODE
    assert refused.value.remediation == service.LOOP_MESSAGE


async def test_a_published_number_may_not_be_a_contact_or_the_fallback_phone() -> None:
    tenant_id, *_ = await _ready()
    async with tenant_session(tenant_id) as session:
        await profile_service.save_contacts(
            session,
            tenant_id=tenant_id,
            contacts=[profile_service.BusinessContactIn(label="Owner", phone_e164="+919812300001")],
        )
    with pytest.raises(ProblemError) as as_contact:
        await add_line(tenant_id, number="+919812300001")
    assert as_contact.value.code == service.LOOP_CODE

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO heal_fallback_phones (id, tenant_id, phone_e164) "
                "VALUES (:i, :t, '+919812300002')"
            ),
            {"i": uuid.uuid4(), "t": tenant_id},
        )
    with pytest.raises(ProblemError) as as_fallback:
        await add_line(tenant_id, number="+919812300002")
    assert as_fallback.value.code == service.LOOP_CODE


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _owner_token(tenant_id: UUID) -> str:
    from tests.healer_flow_test import _owner

    return await _owner(tenant_id)


async def test_the_fallback_phone_may_not_be_a_published_number() -> None:
    tenant_id, _, slug, _ = await _ready()
    line = await add_line(tenant_id, number="+919812300003")
    headers = {"Authorization": f"Bearer {await _owner_token(tenant_id)}", "X-Org-Slug": slug}
    async with _client() as http:
        refused = await http.put(
            "/v1/healer/fallback-phone", json={"phone_e164": line.e164}, headers=headers
        )
    assert refused.status_code == 422, refused.text
    assert refused.json()["type"].endswith(f"/{service.LOOP_CODE}")
    assert service.LOOP_MESSAGE in refused.text


async def test_a_handover_list_may_not_name_a_published_number() -> None:
    tenant_id, agent_id, slug, _ = await _ready()
    async with tenant_session(tenant_id) as session:
        await profile_service.save_contacts(
            session,
            tenant_id=tenant_id,
            contacts=[profile_service.BusinessContactIn(label="Desk", phone_e164="+919812300004")],
        )
        contact_id = (await session.execute(text("SELECT id FROM business_contacts"))).scalar_one()
        # A contact saved BEFORE the number was published, written past the guard to model a
        # row that predates it: the hand-over write must still refuse it.
        await session.execute(
            text(
                "INSERT INTO forwarded_lines (id, tenant_id, e164, line_kind, carrier, mode, "
                "ring_seconds, attested_at) VALUES (:i, :t, '+919812300004', 'mobile', "
                "'airtel', 'all_calls', 0, now())"
            ),
            {"i": uuid.uuid4(), "t": tenant_id},
        )
    headers = {"Authorization": f"Bearer {await _owner_token(tenant_id)}", "X-Org-Slug": slug}
    async with _client() as http:
        refused = await http.put(
            f"/v1/agents/{agent_id}/handoff",
            json={"enabled": True, "members": [{"contact_id": str(contact_id), "active": True}]},
            headers=headers,
        )
    assert refused.status_code == 422, refused.text
    assert service.LOOP_MESSAGE in refused.text


# --- the routes ----------------------------------------------------------------------------


async def test_the_routes_add_change_and_list_a_line() -> None:
    tenant_id, _, slug, _ = await _ready()
    headers = {"Authorization": f"Bearer {await _owner_token(tenant_id)}", "X-Org-Slug": slug}
    async with _client() as http:
        unconfirmed = await http.post(
            "/v1/forwarding/lines",
            json={
                "number": "98123 00005",
                "line_kind": "mobile",
                "carrier": "jio",
                "mode": "conditional",
                "ring_seconds": 15,
                "attest": True,
            },
            headers=headers,
        )
        assert unconfirmed.status_code == 403, unconfirmed.text
        added = await http.post(
            "/v1/forwarding/lines",
            json={
                "number": "98123 00005",
                "line_kind": "mobile",
                "carrier": "jio",
                "mode": "conditional",
                "ring_seconds": 15,
                "attest": True,
            },
            headers={**headers, "X-Confirm-Action": f"add_forwarded_number:{slug}"},
        )
        assert added.status_code == 201, added.text
        line_id = added.json()["id"]
        changed = await http.patch(
            f"/v1/forwarding/lines/{line_id}",
            json={"line_kind": "mobile", "carrier": "jio", "mode": "all_calls", "ring_seconds": 0},
            headers=headers,
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["mode"] == "all_calls"
        listed = await http.get("/v1/forwarding", headers=headers)
        assert listed.status_code == 200
        assert [line["e164"] for line in listed.json()["lines"]] == ["+919812300005"]
        catalogue = await http.get("/v1/forwarding/codes", headers=headers)
        jio = next(g for g in catalogue.json()["carriers"] if g["carrier"] == "jio")
        assert jio["method"] == "app" and jio["codes"] == [] and jio["unconfirmed"]


def test_every_code_carries_its_evidence_and_the_timer_is_the_standards() -> None:
    for guide in codes.GUIDES.values():
        for code in guide.codes:
            assert code.evidence in ("carrier_own", "standards_body", "web_secondary")
            assert code.source.startswith("https://")
    no_answer = next(c for c in codes.GUIDES["vi"].codes if c.condition == "no_answer")
    assert no_answer.activate == "*61*{number}**{seconds}#"
    assert codes.render(no_answer.activate, number_e164="+918012345678", seconds=20) == (
        "*61*08012345678**20#"
    )
    assert codes.dialled_form("+919812345678") == "09812345678"
