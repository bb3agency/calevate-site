"""The name an agent greets a person by is the newest name the owner gave for them.

The 26 Nov 2026 campaign call opened "నమస్కారం Srinivas J గారు" to a person the owner's
leads call Umesh. Three doors let a name other than the owner's newest reach the dial: a
number added again with a new name kept the first upload's name; a lead renamed by the
owner left the campaign list's name as it was; and a campaign dial never reads the lead,
so a list row with no name fell straight to the client's caller lookup, which may hold
somebody else on that number.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.actions import pre_dial
from apps.api.actions.pre_dial import CallerPrefill, for_person
from apps.api.callbacks import service as callbacks
from apps.api.campaigns import service as campaigns
from apps.api.campaigns.contact_details import known_name
from apps.api.crm import service as crm
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine, reset_engine_cache
from apps.workers.callbacks import dispatch_due_callbacks
from calevate_shared.engine import CallContext
from sqlalchemy import text
from tests.callback_dispatch_test import _dialable_tenant
from tests.conftest import create_org_with_receptionist

pytestmark = pytest.mark.anyio

PHONE = "+918019857559"
OTHER = "+919876512345"


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    """11:00 IST, inside the dial gate's calling hours (as `callback_dispatch_test`)."""
    fixed = datetime(2026, 8, 11, 5, 30, tzinfo=UTC) + timedelta(hours=5, minutes=30)
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: fixed)


@pytest.fixture(autouse=True)
def _fake_engine() -> None:
    reset_engine_cache()


# --- the lookup never names somebody else --------------------------------------------------


def test_a_lookup_naming_the_same_person_is_kept_whole() -> None:
    found = CallerPrefill(name="umesh  kumar", variables={"caller_details": "Plan: Gold"})
    assert for_person(found, "Umesh Kumar") == found
    assert for_person(found, None) == found


def test_a_lookup_naming_somebody_else_is_not_used() -> None:
    found = CallerPrefill(name="Srinivas J", variables={"caller_name": "Srinivas J"})
    assert for_person(found, "Umesh") == CallerPrefill()


# --- the database --------------------------------------------------------------------------


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    created = await create_org_with_receptionist(
        name="Rytu Khata",
        slug=f"names-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return uuid.UUID(str(created["id"])), uuid.UUID(str(created["agent_id"]))


async def _campaign(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        campaign_id = await campaigns.create_campaign(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name=f"Names {uuid.uuid4().hex[:4]}",
            classification="service",
            number_id=None,
            dlt_template_id=None,
            concurrency=1,
            consent_source="existing_customer",
            consent_collected_at=datetime.now(UTC) - timedelta(days=7),
        )
        await session.commit()
    return campaign_id


async def _add(
    tenant_id: uuid.UUID, campaign_id: uuid.UUID, rows: list[dict[str, str]]
) -> dict[str, int]:
    async with tenant_session(tenant_id) as session:
        result = await campaigns.add_contacts(
            session, tenant_id=tenant_id, campaign_id=campaign_id, contacts=rows
        )
        await session.commit()
    return result


async def _names(tenant_id: uuid.UUID, campaign_id: uuid.UUID) -> dict[str, str | None]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT phone_e164, name FROM campaign_contacts WHERE campaign_id = :c"),
                {"c": campaign_id},
            )
        ).all()
    return {str(r[0]): r[1] for r in rows}


async def _lead(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, *, phone: str, name: str | None
) -> uuid.UUID:
    lead_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status, "
                "created_at, updated_at) VALUES (:id, :t, :a, :p, :n, 'inbound_call', 'new', "
                "now(), now())"
            ),
            {"id": lead_id, "t": tenant_id, "a": agent_id, "p": phone, "n": name},
        )
        await session.commit()
    return lead_id


async def test_a_number_added_again_with_a_name_takes_the_new_name() -> None:
    tenant_id, agent_id = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id)
    assert (await _add(tenant_id, campaign_id, [{"phone": PHONE, "name": "Srinivas J"}]))[
        "added"
    ] == 1

    again = await _add(
        tenant_id, campaign_id, [{"phone": "80198 57559", "name": "Umesh"}, {"phone": OTHER}]
    )
    assert (again["added"], again["duplicate"]) == (1, 1)
    assert await _names(tenant_id, campaign_id) == {PHONE: "Umesh", OTHER: None}

    # Added again with no name, the name the owner gave stays.
    await _add(tenant_id, campaign_id, [{"phone": PHONE}])
    assert (await _names(tenant_id, campaign_id))[PHONE] == "Umesh"


async def test_a_row_being_dialled_keeps_the_name_its_call_is_using() -> None:
    tenant_id, agent_id = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id)
    await _add(tenant_id, campaign_id, [{"phone": PHONE, "name": "Srinivas J"}])
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaign_contacts SET status = 'dialing' WHERE campaign_id = :c"),
            {"c": campaign_id},
        )
        await session.commit()
    again = await _add(tenant_id, campaign_id, [{"phone": PHONE, "name": "Umesh"}])
    assert (again["added"], again["duplicate"]) == (0, 1)
    assert (await _names(tenant_id, campaign_id))[PHONE] == "Srinivas J"


async def test_renaming_a_lead_renames_the_person_on_every_list() -> None:
    tenant_id, agent_id = await _tenant()
    first, second = await _campaign(tenant_id, agent_id), await _campaign(tenant_id, agent_id)
    await _add(
        tenant_id, first, [{"phone": PHONE, "name": "Srinivas J"}, {"phone": OTHER, "name": "Ravi"}]
    )
    await _add(tenant_id, second, [{"phone": PHONE}])
    lead_id = await _lead(tenant_id, agent_id, phone=PHONE, name="Srinivas J")

    async with tenant_session(tenant_id) as session:
        assert await crm.set_lead_name(session, lead_id, name="Umesh")
        await session.commit()

    assert await _names(tenant_id, first) == {PHONE: "Umesh", OTHER: "Ravi"}
    assert await _names(tenant_id, second) == {PHONE: "Umesh"}


async def test_another_accounts_list_is_never_renamed() -> None:
    tenant_id, agent_id = await _tenant()
    elsewhere, elsewhere_agent = await _tenant()
    theirs = await _campaign(elsewhere, elsewhere_agent)
    await _add(elsewhere, theirs, [{"phone": PHONE, "name": "Their name"}])
    lead_id = await _lead(tenant_id, agent_id, phone=PHONE, name="Srinivas J")

    async with tenant_session(tenant_id) as session:
        await crm.set_lead_name(session, lead_id, name="Umesh")
        await session.commit()

    assert await _names(elsewhere, theirs) == {PHONE: "Their name"}


async def test_the_dial_reads_the_owners_lead_for_the_number() -> None:
    tenant_id, agent_id = await _tenant()
    _, other_agent = await _tenant()
    named = await _lead(tenant_id, agent_id, phone=PHONE, name=" Umesh ")
    await _lead(tenant_id, agent_id, phone=OTHER, name="  ")
    async with tenant_session(tenant_id) as session:
        by_number = await known_name(session, phone_e164=PHONE, agent_id=agent_id, lead_id=None)
        by_lead = await known_name(session, phone_e164=OTHER, agent_id=agent_id, lead_id=named)
        blank = await known_name(session, phone_e164=OTHER, agent_id=agent_id, lead_id=None)
        any_agent = await known_name(session, phone_e164=PHONE, agent_id=other_agent, lead_id=None)
    assert (by_number, by_lead, blank, any_agent) == ("Umesh", "Umesh", None, "Umesh")


async def test_a_dial_with_no_name_greets_by_the_owners_lead_not_the_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """At the engine: a call-back that brings no name is placed under the lead's name, and
    a caller lookup naming somebody else on that number reaches neither the name nor the
    call's variables."""
    tenant_id, agent_id = await _dialable_tenant()
    await _lead(tenant_id, agent_id, phone=PHONE, name="Umesh")

    async def _other_person(*_args: object, **_kwargs: object) -> CallerPrefill:
        return CallerPrefill(name="Srinivas J", variables={"caller_name": "Srinivas J"})

    monkeypatch.setattr(pre_dial, "pre_dial_lookup", _other_person)
    monkeypatch.setattr("apps.api.agents.service.ACTION_ENGINES", frozenset({get_engine().name}))
    seen: list[CallContext] = []
    engine = get_engine()
    original = engine.start_outbound_call

    async def _spy(ref: str, to: str, ctx: CallContext):  # type: ignore[no-untyped-def]
        seen.append(ctx)
        return await original(ref, to, ctx)

    monkeypatch.setattr(engine, "start_outbound_call", _spy)
    async with tenant_session(tenant_id) as session:
        await callbacks.book(
            session,
            callback_id=uuid7(),
            tenant_id=tenant_id,
            agent_id=agent_id,
            source_call_id=None,
            source_execution_id=f"exec_{uuid.uuid4().hex[:10]}",
            lead_id=None,
            phone_e164=PHONE,
            requested_at=datetime.now(UTC) - timedelta(minutes=1),
            booked_at=datetime.now(UTC),
            note="asked to be called back",
            language="te",
        )
        await session.commit()

    outcome = await dispatch_due_callbacks(tenant_id, slots=5)
    assert outcome["dialled"] == 1, outcome
    assert seen[0].lead_name == "Umesh"
    assert "caller_name" not in seen[0].fields
