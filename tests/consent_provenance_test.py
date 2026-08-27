"""Two SEC-COMP §3 launch blockers the code could not previously express.

§3 names five conditions a campaign must satisfy before it may dial. Two of them had
nowhere to live:

1. **Consent provenance for the list** — "Consent provenance recorded for the list
   (source + date) — a purchased list with no consent artefacts is refused, in
   writing, as policy." `campaigns` had no such column, and `consent_ledger` records
   consent per call/phone AFTER a conversation, which is the wrong side of the dial:
   the question here is asked BEFORE the first ring, about the list as a whole.
2. **DLT Principal Entity registration** — "Calevate TM registration exists AND this
   client's PE registration + TM-link are active (inbound-only operation is the
   interim mode while pending)." Nothing anywhere recorded whether a client's PE
   registration was live, so the gate could not ask. `phone_numbers.dlt_status` and
   `dlt_templates.status` are the header and template registrations — different
   registrations, at the same registrar, that do not imply the entity one.

The tests are written the way the gate is read: every refusal has its OWN rule name,
because "campaign cannot launch" is a support ticket and `pe_registration_missing` is
a to-do item.

Scoped deliberately to tenants this file creates (slug `prov-…`) — other suites run
against the same Postgres concurrently.

Run: uv run pytest -q tests/consent_provenance_test.py
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.campaigns import service
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from sqlalchemy import text
from tests.conftest import accept_agreements
from tests.national_dnd_test import record_test_scrub

pytestmark = [pytest.mark.rls]

COLLECTED_AT = datetime(2026, 5, 1, 9, 0, tzinfo=UTC)


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name="Provenance Motors",
        slug=f"prov-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    # The four agreements, accepted (migration a9d4e70c31b8) — supplied, never assumed
    # away, in the shape `arm_agent_for_outbound` established. Every dial, launch and
    # publish gate now refuses an organisation that has not accepted them, so a fixture
    # without this reports `agreements_not_accepted` in place of the answer under test.
    await accept_agreements(uuid.UUID(str(created["id"])))
    tenant_id, agent_id = created["id"], created["agent_id"]
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET status = 'live', direction = 'outbound' WHERE id = :a"),
            {"a": agent_id},
        )
    return tenant_id, agent_id


async def _number(session: Any, tenant_id: uuid.UUID, agent_id: uuid.UUID) -> uuid.UUID:
    """A registered 140 header BOUND TO `agent_id` (D-424) — the launch gate refuses a
    campaign whose approved number is not the number its agent dials from, and every
    campaign here is meant to be green on everything except the provenance under test."""
    number_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO phone_numbers (id, tenant_id, agent_id, e164, series, dlt_status, "
            "created_at, updated_at) "
            "VALUES (:id, :tid, :aid, :e, '140', 'registered', now(), now())"
        ),
        {
            "id": number_id,
            "tid": tenant_id,
            "aid": agent_id,
            "e": f"+9180{uuid.uuid4().int % 100000000:08d}",
        },
    )
    return number_id


async def _template(session: Any, tenant_id: uuid.UUID) -> uuid.UUID:
    template_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO dlt_templates (id, tenant_id, kind, classification, body, status, "
            "created_at, updated_at) VALUES (:id, :tid, 'voice', 'promotional', :body, "
            "'approved', now(), now())"
        ),
        {"id": template_id, "tid": tenant_id, "body": "Hello from {#var#}, an AI assistant."},
    )
    return template_id


async def _campaign(
    session: Any,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    consent_source: str | None = "existing_customer",
    consent_collected_at: datetime | None = COLLECTED_AT,
) -> uuid.UUID:
    """Everything the OLD gate wanted: live outbound agent, registered 140 number,
    approved matching template, one dialable contact. What remains between it and a
    green button is exactly what this module is about."""
    campaign_id = await service.create_campaign(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        name="Diwali offers",
        classification="promotional",
        number_id=await _number(session, tenant_id, agent_id),
        dlt_template_id=await _template(session, tenant_id),
        concurrency=3,
        consent_source=consent_source,
        consent_collected_at=consent_collected_at,
    )
    await service.add_contacts(
        session,
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        contacts=[{"phone": "9876590001", "name": "Ravi"}],
    )
    # The national DND scrub SEC-COMP §3 asks for (migration a1c8e40f27b9), supplied
    # through the production writer so this module keeps measuring what it is about —
    # a promotional campaign that is ready except for its consent provenance.
    await record_test_scrub(session, campaign_id)
    return campaign_id


async def _register_pe(
    session: Any,
    tenant_id: uuid.UUID,
    *,
    status: str = "active",
    tm_link_status: str = "active",
) -> None:
    await service.record_dlt_registration(
        session,
        tenant_id=tenant_id,
        pe_id="110200001234567890",
        entity_name="Provenance Motors Pvt Ltd",
        status=status,
        tm_link_status=tm_link_status,
    )


async def _rules(session: Any, tenant_id: uuid.UUID, campaign_id: uuid.UUID) -> set[str]:
    blockers = await service.launch_blockers(session, tenant_id=tenant_id, campaign_id=campaign_id)
    return {b.rule for b in blockers}


# ------------------------------------------------------------ consent provenance


async def test_a_campaign_that_cannot_say_where_its_list_came_from_does_not_launch() -> None:
    """The named blocker, and the refusal that follows it.

    A list with no recorded provenance is the purchased-list case we cannot rule out:
    the whole point of §3's bullet is that "we do not know" and "they consented" must
    not look the same to the gate.
    """
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await _register_pe(session, tenant_id)
        campaign_id = await _campaign(
            session, tenant_id, agent_id, consent_source=None, consent_collected_at=None
        )
        blockers = await service.launch_blockers(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
        with pytest.raises(ProblemError) as excinfo:
            await service.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
        status = (
            await session.execute(
                text("SELECT status FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar()

    assert [b.rule for b in blockers] == ["consent_provenance_missing"], [b.rule for b in blockers]
    assert excinfo.value.code == "campaign_launch_blocked"
    assert "consent_provenance_missing" in {f["rule"] for f in excinfo.value.fields or []}
    assert status == "draft", "a blocked launch leaves the campaign where it was"


async def test_a_purchased_list_is_refused_under_its_own_name() -> None:
    """`purchased_list` is IN the enum on purpose. An enum without the wrong answer in
    it teaches clients to pick the nearest right-sounding one, and then the refusal
    §3 promises "in writing" can never happen because nobody ever says the word."""
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await _register_pe(session, tenant_id)
        campaign_id = await _campaign(session, tenant_id, agent_id, consent_source="purchased_list")
        blockers = await service.launch_blockers(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
        with pytest.raises(ProblemError) as excinfo:
            await service.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)

    assert [b.rule for b in blockers] == ["consent_source_refused"], [b.rule for b in blockers]
    assert "purchas" in blockers[0].reason.lower(), blockers[0].reason
    assert excinfo.value.code == "campaign_launch_blocked"


async def test_recorded_provenance_is_stored_verbatim_and_clears_the_blocker() -> None:
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await _register_pe(session, tenant_id)
        campaign_id = await _campaign(session, tenant_id, agent_id, consent_source="web_form_optin")
        row = (
            await session.execute(
                text("SELECT consent_source, consent_collected_at FROM campaigns WHERE id = :c"),
                {"c": campaign_id},
            )
        ).first()
        rules = await _rules(session, tenant_id, campaign_id)

    assert row is not None
    assert row[0] == "web_form_optin"
    assert row[1] == COLLECTED_AT
    assert not {"consent_provenance_missing", "consent_source_refused"} & rules, rules


async def test_provenance_that_is_not_checkable_is_refused_at_create() -> None:
    """Free text is a box someone types "yes" into, so the source is an enum and the
    date is a date. Both are refused at the only write path, which is why the column
    can never hold an answer the gate would have to interpret."""
    tenant_id, agent_id = await _tenant()
    bad: tuple[tuple[str | None, datetime | None, str], ...] = (
        ("yes they agreed", COLLECTED_AT, "consent_source_invalid"),
        ("existing_customer", None, "consent_provenance_incomplete"),
        (None, COLLECTED_AT, "consent_provenance_incomplete"),
        ("existing_customer", datetime.now(UTC) + timedelta(days=1), "consent_collected_in_future"),
    )
    async with tenant_session(tenant_id) as session:
        for source, collected_at, code in bad:
            with pytest.raises(ProblemError) as excinfo:
                await service.create_campaign(
                    session,
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    name="Unfounded",
                    classification="promotional",
                    number_id=None,
                    dlt_template_id=None,
                    concurrency=3,
                    consent_source=source,
                    consent_collected_at=collected_at,
                )
            assert excinfo.value.code == code, (source, collected_at)
            assert excinfo.value.kind == "validation"

        stored = (
            await session.execute(text("SELECT count(*) FROM campaigns WHERE name = 'Unfounded'"))
        ).scalar()
    assert stored == 0, "a refusal at create must leave nothing behind to launch later"


async def test_a_campaign_predating_the_columns_is_blocked_not_silently_consented() -> None:
    """The migration's central choice, asserted.

    Every campaign that existed before this release has NULL provenance, because the
    alternative — a server default naming some source — is the system asserting a
    consent nobody gave. A NULL says "we do not know", the gate refuses it by name,
    and `declare_consent_provenance` is how a client answers without recreating the
    campaign. Simulated by inserting a row the pre-migration writer would have written.
    """
    tenant_id, agent_id = await _tenant()
    legacy_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await _register_pe(session, tenant_id)
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, classification, "
                "number_id, dlt_template_id, status, concurrency, created_at, updated_at) "
                "VALUES (:id, :tid, :aid, 'Legacy list', 'promotional', :nid, :did, 'draft', "
                "3, now(), now())"
            ),
            {
                "id": legacy_id,
                "tid": tenant_id,
                "aid": agent_id,
                "nid": await _number(session, tenant_id, agent_id),
                "did": await _template(session, tenant_id),
            },
        )
        await service.add_contacts(
            session,
            tenant_id=tenant_id,
            campaign_id=legacy_id,
            contacts=[{"phone": "9876590009"}],
        )
        # As in `_campaign`: everything §3 asks for except the provenance under test.
        await record_test_scrub(session, legacy_id)
        source = (
            await session.execute(
                text("SELECT consent_source FROM campaigns WHERE id = :c"), {"c": legacy_id}
            )
        ).scalar()
        before = await _rules(session, tenant_id, legacy_id)

        # The client answers the question; nothing is recreated, nothing is lost.
        await service.declare_consent_provenance(
            session,
            tenant_id=tenant_id,
            campaign_id=legacy_id,
            consent_source="existing_customer",
            consent_collected_at=COLLECTED_AT,
        )
        after = await _rules(session, tenant_id, legacy_id)
        result = await service.launch_campaign(session, tenant_id=tenant_id, campaign_id=legacy_id)

    assert source is None, "no default may assert a consent nobody gave"
    assert before == {"consent_provenance_missing"}, before
    assert after == set(), after
    assert result["status"] == "running"


async def test_provenance_cannot_be_rewritten_once_the_campaign_is_running() -> None:
    """Otherwise the declaration is worth nothing: dial first, pick a lawful-sounding
    source afterwards."""
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await _register_pe(session, tenant_id)
        campaign_id = await _campaign(session, tenant_id, agent_id)
        await service.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
        with pytest.raises(ProblemError) as excinfo:
            await service.declare_consent_provenance(
                session,
                tenant_id=tenant_id,
                campaign_id=campaign_id,
                consent_source="purchased_list",
                consent_collected_at=COLLECTED_AT,
            )
        source = (
            await session.execute(
                text("SELECT consent_source FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar()
    assert excinfo.value.code == "campaign_not_draft"
    assert source == "existing_customer"


# ------------------------------------------------------ DLT PE / TM registration


async def test_a_client_with_no_pe_registration_cannot_launch_an_outbound_campaign() -> None:
    """§3, first bullet. Unregistered traffic is dropped at the network as spam and the
    complaints land on the client's entity, so "we never asked" is the one answer the
    gate may not give. Inbound answering is unaffected — that IS the interim mode."""
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        campaign_id = await _campaign(session, tenant_id, agent_id)
        blockers = await service.launch_blockers(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
        with pytest.raises(ProblemError) as excinfo:
            await service.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
        status = (
            await session.execute(
                text("SELECT status FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar()

    assert [b.rule for b in blockers] == ["pe_registration_missing"], [b.rule for b in blockers]
    assert excinfo.value.code == "campaign_launch_blocked"
    assert status == "draft"


@pytest.mark.parametrize("pe_status", ["not_started", "submitted", "suspended", "rejected"])
async def test_a_pe_registration_that_is_not_live_blocks_by_its_own_name(pe_status: str) -> None:
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await _register_pe(session, tenant_id, status=pe_status)
        campaign_id = await _campaign(session, tenant_id, agent_id)
        blockers = await service.launch_blockers(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
    assert [b.rule for b in blockers] == ["pe_registration_not_active"], (
        pe_status,
        [b.rule for b in blockers],
    )
    assert pe_status.replace("_", " ") in blockers[0].reason


@pytest.mark.parametrize("tm_link", ["not_linked", "pending", "revoked"])
async def test_a_pe_without_a_live_tm_link_blocks_separately(tm_link: str) -> None:
    """The PE and the TM-link are two facts, not one: a client can be a registered
    Principal Entity and still not have authorised Calevate to dial on their behalf.
    Collapsing them into one blocker sends the client to re-register something that is
    already done."""
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await _register_pe(session, tenant_id, tm_link_status=tm_link)
        campaign_id = await _campaign(session, tenant_id, agent_id)
        blockers = await service.launch_blockers(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
    assert [b.rule for b in blockers] == ["tm_link_not_active"], [b.rule for b in blockers]


async def test_an_active_pe_with_a_live_tm_link_and_recorded_provenance_launches() -> None:
    """The mirror image of every test above: the gate must not become a way to refuse
    a campaign that has done everything §3 asks."""
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await _register_pe(session, tenant_id)
        campaign_id = await _campaign(session, tenant_id, agent_id)
        blockers = await service.launch_blockers(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
        result = await service.launch_campaign(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
    assert blockers == []
    assert result == {"status": "running", "dialable": 1, "dnc_scrubbed": 0}


async def test_the_gate_names_both_new_blockers_at_once() -> None:
    """SURFACES §2b: a disabled button with reasons, not one 422 at a time."""
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        campaign_id = await _campaign(
            session, tenant_id, agent_id, consent_source=None, consent_collected_at=None
        )
        rules = await _rules(session, tenant_id, campaign_id)
    assert rules == {"pe_registration_missing", "consent_provenance_missing"}, rules


# ------------------------------------------------------------------- hard rule 1


async def test_dlt_registrations_are_invisible_across_tenants() -> None:
    """A PE id and entity name are the client's own registration identifiers; another
    tenant reading them is the classic cross-tenant leak (hard rule 1). Ground truth
    is asserted from the owning tenant's own session, so a policy that hid a tenant's
    OWN row would fail here too."""
    tenant_a, _ = await _tenant()
    tenant_b, _ = await _tenant()
    async with tenant_session(tenant_a) as session:
        await _register_pe(session, tenant_a)

    async with tenant_session(tenant_a) as session:
        mine = (
            (
                await session.execute(
                    text("SELECT pe_id FROM dlt_registrations WHERE tenant_id = :t"),
                    {"t": tenant_a},
                )
            )
            .scalars()
            .all()
        )
    assert mine == ["110200001234567890"], "a tenant must see its own registration"

    async with tenant_session(tenant_b) as session:
        leaked = (
            await session.execute(
                text("SELECT count(*) FROM dlt_registrations WHERE tenant_id = :t"),
                {"t": tenant_a},
            )
        ).scalar()
        hijack = await session.execute(
            text("UPDATE dlt_registrations SET status = 'active' WHERE tenant_id = :t"),
            {"t": tenant_a},
        )
    assert leaked == 0, "cross-tenant read of a DLT registration must return zero rows"
    assert hijack.rowcount == 0, "and a cross-tenant write must reach zero rows"

    async with untenanted_session() as session:
        blind = (
            await session.execute(
                text("SELECT count(*) FROM dlt_registrations WHERE tenant_id = :t"),
                {"t": tenant_a},
            )
        ).scalar()
    assert blind == 0, "no GUC ⇒ zero rows (fail closed)"


async def test_a_tenant_cannot_forge_another_tenants_pe_registration() -> None:
    """WITH CHECK is derived from USING under FORCE RLS, so the insert is rejected
    outright rather than silently landing where nobody can see it."""
    tenant_a, _ = await _tenant()
    tenant_b, _ = await _tenant()
    with pytest.raises(Exception) as excinfo:
        async with tenant_session(tenant_b) as session:
            await session.execute(
                text(
                    "INSERT INTO dlt_registrations (id, tenant_id, pe_id, status, "
                    "tm_link_status, created_at, updated_at) VALUES (:id, :tid, 'forged', "
                    "'active', 'active', now(), now())"
                ),
                {"id": uuid7(), "tid": tenant_a},
            )
    assert "row-level security" in str(excinfo.value).lower(), str(excinfo.value)
