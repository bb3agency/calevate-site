"""A contact's own values reach the call (D-905): the shared rendering, the THIS CALL lines,
the script builder's offer of the list's columns, and the leads lens by campaign."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.campaigns import service as campaigns
from apps.api.campaigns.contact_details import call_origin, contact_details_of, list_columns
from apps.api.crm import service as crm
from apps.api.crm.lens import LeadRowFilters
from apps.api.crm.schemas import LeadLensIn
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from calevate_shared.engine import (
    CALL_VARIABLE_VALUE_MAX,
    CALLER_MEMORY_VARIABLE,
    DETAILS_LINE,
    NAME_LINE,
    PHONE_LINE,
    PLATFORM_CALL_VARIABLES,
    REASON_LINE,
    THIS_CALL_HEADER,
    TODAY_LINE,
    AgentConfig,
    call_details_value,
    call_reason_value,
    call_variable_key,
    compose_engine_prompt,
    contact_call_variables,
    phone_value,
)
from sqlalchemy import text
from tests.conftest import create_org_with_receptionist

# --- the shared rendering -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("header", "key"),
    [
        ("Village", "village"),
        ("Village Name", "village_name"),
        ("  land-acres (approx) ", "land_acres_approx"),
        ("ఊరు", None),
        ("2nd crop", None),
    ],
)
def test_a_header_folds_to_one_variable_name(header: str, key: str | None) -> None:
    assert call_variable_key(header) == key


def test_columns_become_variables_without_the_platforms_names_or_blank_cells() -> None:
    assert contact_call_variables(
        {"Village": " Kondapur\n", "phone": "999", "Today": "x", "Crop": "", "ఊరు": "x"}
    ) == {"village": "Kondapur"}
    assert CALLER_MEMORY_VARIABLE in PLATFORM_CALL_VARIABLES


def test_the_details_line_keeps_whole_items_within_the_vendors_cut() -> None:
    custom = {"ఊరు": "కొండాపూర్", "Crop": "cotton", "Notes": "x" * 200}
    value = call_details_value(custom)
    assert value == "ఊరు: కొండాపూర్; Crop: cotton"
    assert len(call_details_value({f"c{i}": "y" * 30 for i in range(10)})) <= (
        CALL_VARIABLE_VALUE_MAX
    )
    assert call_details_value({}) == ""


def test_the_reason_is_one_line_cut_on_a_word() -> None:
    note = "They asked to be called back " + "about the subsidy form " * 10
    value = call_reason_value(note)
    assert len(value) <= CALL_VARIABLE_VALUE_MAX and not value.endswith(" ")
    assert note.startswith(value)
    assert call_reason_value("one\ntwo") == "one two"
    assert call_reason_value(None) == ""


def test_the_number_is_said_as_its_owner_says_it() -> None:
    assert phone_value("+919876543210") == "9876543210"
    assert phone_value("+14155550100") == "14155550100"


def test_a_stored_row_becomes_text_values_only() -> None:
    assert contact_details_of({"Acres": 3, "Crop": None, "Blank": " "}) == {"Acres": "3"}
    assert contact_details_of(None) == {}


# --- THIS CALL --------------------------------------------------------------------------


def _cfg(direction: str, *, callbacks: bool) -> AgentConfig:
    return AgentConfig(
        tenant_id="t",
        agent_id="a",
        name="Rytu desk",
        direction=direction,  # type: ignore[arg-type]
        system_prompt="Help the farmer register.",
        opening_line="",
        callbacks_offered=callbacks,
    )


def test_an_agent_that_places_calls_reads_the_number_details_and_reason() -> None:
    prompt = compose_engine_prompt(_cfg("outbound", callbacks=False))
    section = prompt[prompt.index(THIS_CALL_HEADER) :]
    assert section == "\n".join(
        [THIS_CALL_HEADER, TODAY_LINE, NAME_LINE, PHONE_LINE, DETAILS_LINE, REASON_LINE]
    )


def test_an_answering_agent_carries_none_of_them() -> None:
    for callbacks in (False, True):
        prompt = compose_engine_prompt(_cfg("inbound", callbacks=callbacks))
        assert PHONE_LINE not in prompt
        assert DETAILS_LINE not in prompt and REASON_LINE not in prompt
    assert PHONE_LINE in compose_engine_prompt(_cfg("both", callbacks=False))


# --- the database -------------------------------------------------------------------------


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    created = await create_org_with_receptionist(
        name="Rytu Khata",
        slug=f"rytu-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return uuid.UUID(str(created["id"])), uuid.UUID(str(created["agent_id"]))


async def _campaign_with(tenant_id: uuid.UUID, agent_id: uuid.UUID, rows: list[dict]) -> uuid.UUID:  # type: ignore[type-arg]
    async with tenant_session(tenant_id) as session:
        campaign_id = await campaigns.create_campaign(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name=f"Onboarding {uuid.uuid4().hex[:4]}",
            classification="service",
            number_id=None,
            dlt_template_id=None,
            concurrency=1,
            consent_source="existing_customer",
            consent_collected_at=datetime.now(UTC) - timedelta(days=7),
        )
        await campaigns.add_contacts(
            session, tenant_id=tenant_id, campaign_id=campaign_id, contacts=rows
        )
    return campaign_id


async def test_a_name_in_any_script_is_stored_as_written() -> None:
    tenant_id, agent_id = await _tenant()
    campaign_id = await _campaign_with(
        tenant_id, agent_id, [{"phone": "9876512345", "name": " రామారావు ", "Village": "Kondapur"}]
    )
    async with tenant_session(tenant_id) as session:
        name, custom = (
            await session.execute(
                text("SELECT name, custom FROM campaign_contacts WHERE campaign_id = :c"),
                {"c": campaign_id},
            )
        ).one()
    assert name == "రామారావు"
    assert custom == {"Village": "Kondapur"}


async def test_the_script_builder_is_offered_the_lists_columns() -> None:
    tenant_id, agent_id = await _tenant()
    await _campaign_with(
        tenant_id,
        agent_id,
        [{"phone": "9876512345", "Village Name": "Kondapur", "ఊరు": "x", "phone_2": "1"}],
    )
    async with tenant_session(tenant_id) as session:
        offered = await list_columns(session, agent_id=agent_id)
    assert ("village_name", "Village Name") in offered
    assert all(key != "" for key, _ in offered)
    assert not any(header == "ఊరు" for _, header in offered)


async def test_a_call_back_finds_its_campaign_row_and_falls_back_to_the_lead_name() -> None:
    tenant_id, agent_id = await _tenant()
    campaign_id = await _campaign_with(
        tenant_id, agent_id, [{"phone": "9876512345", "Village": "Kondapur"}]
    )
    call_id, lead_id = uuid7(), uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status, "
                "created_at, updated_at) VALUES (:id, :t, :a, '+919876512345', 'Ramu', "
                "'inbound_call', 'new', now(), now())"
            ),
            {"id": lead_id, "t": tenant_id, "a": agent_id},
        )
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "campaign_id, to_e164, created_at, updated_at) VALUES (:id, :t, :a, :e, "
                "'outbound', 'completed', :c, '+919876512345', now(), now())"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": f"local:{call_id}",
                "c": campaign_id,
            },
        )
        origin = await call_origin(
            session, source_call_id=call_id, lead_id=lead_id, phone_e164="+919876512345"
        )
        outside = await call_origin(
            session, source_call_id=None, lead_id=None, phone_e164="+919876512345"
        )
    assert origin.campaign_id == campaign_id
    assert origin.name == "Ramu"
    assert origin.details == {"Village": "Kondapur"}
    assert outside.campaign_id is None and outside.name is None and outside.details == {}


async def test_the_leads_lens_narrows_to_the_people_a_campaign_reached() -> None:
    tenant_id, agent_id = await _tenant()
    campaign_id = await _campaign_with(tenant_id, agent_id, [{"phone": "9876512345"}])
    reached, other = uuid7(), uuid7()
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        for lead_id, phone in ((reached, "+919876512345"), (other, "+919876512399")):
            await session.execute(
                text(
                    "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, "
                    "status, created_at, updated_at) VALUES (:id, :t, :a, :p, 'L', "
                    "'inbound_call', 'new', now(), now())"
                ),
                {"id": lead_id, "t": tenant_id, "a": agent_id, "p": phone},
            )
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "campaign_id, lead_id, to_e164, created_at, updated_at) VALUES (:id, :t, :a, "
                ":e, 'outbound', 'completed', :c, :l, '+919876512345', now(), now())"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": f"local:{call_id}",
                "c": campaign_id,
                "l": reached,
            },
        )
        lens = LeadLensIn(campaign_id=campaign_id)
        found = await crm.lead_ids_matching(
            session,
            status=None,
            search=None,
            agent_id=None,
            assigned_to=None,
            field_filters={},
            more=LeadRowFilters.of(lens),
        )
    assert found == [reached]
