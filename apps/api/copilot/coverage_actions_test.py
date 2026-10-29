"""D-938: Pip's coverage actions and reads, held to `docs/COPILOT-CONTRACT.md` §5.

Per tool: its tier and permission, the plan's current and proposed values, the change through
`confirm` and its audit row, the refusal of another account's object (RLS), and for the
reads the role filter. Every test mints its own tenant.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from tests.api_security_test import _make_tenant

from apps.api.copilot import areas, service, tools, write_tools
from apps.api.copilot.coverage_actions import COVERAGE_ACTIONS, COVERAGE_READS
from apps.api.copilot.follow_up_actions import FOLLOW_UP_ACTIONS
from apps.api.copilot.help import GLOSSARY
from apps.api.copilot.pin_actions import PIN_ACTIONS
from apps.api.copilot.write_tools_test import _audit, _confirm, _principal, _user_of
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session

_REPO = Path(__file__).resolve().parents[3]


async def _propose(tenant_id: UUID, token: str, name: str, args: dict[str, Any]) -> Any:
    principal = _principal(tenant_id, _user_of(token))
    return await write_tools.plan_write(
        name, json.dumps(args), actor=write_tools.actor_for(principal)
    )


async def _do(tenant_id: UUID, token: str, name: str, args: dict[str, Any]) -> Any:
    proposal = await _propose(tenant_id, token, name, args)
    return await _confirm(tenant_id, _user_of(token), proposal.token)


async def _one(tenant_id: UUID, sql: str, **params: Any) -> Any:
    async with tenant_session(tenant_id) as session:
        return (await session.execute(text(sql), params)).first()


async def _read(name: str, tenant_id: UUID, args: dict[str, Any], role: str = "owner") -> str:
    return await tools.run_read_tool(
        name,
        json.dumps(args),
        context=tools.ToolContext(tenant_id=tenant_id, role=role, user_id=uuid.uuid4()),
        registry=service._read_tool_registry("client"),
    )


async def _agent_of(tenant_id: UUID) -> UUID:
    return UUID(str((await _one(tenant_id, "SELECT id FROM agents LIMIT 1"))[0]))


# --- the registry ----------------------------------------------------------------------------


def test_the_coverage_actions_are_appended_last_and_each_has_an_area() -> None:
    names = [tool.name for tool in write_tools.WRITE_TOOLS]
    mine = [tool.name for tool in COVERAGE_ACTIONS]
    # D-934's pin actions, then D-940's Follow-up actions, are appended after these.
    after = [tool.name for tool in (*PIN_ACTIONS, *FOLLOW_UP_ACTIONS)]
    later = len(after)
    assert names[-len(mine) - later : -later] == mine
    assert names[-later:] == after
    assert {areas.AREA_OF[n] for n in mine} == {
        "settings",
        "agents",
        "team",
        "knowledge",
        "integrations",
    }
    assert {areas.AREA_OF[r.name] for r in COVERAGE_READS} == {"settings", "integrations"}


def test_every_coverage_action_needs_a_click_and_the_owners_permission() -> None:
    # Each moves cost, who is told about callers, what agents say, who may be called, or
    # who may write: none is reversible-without-consequence, so none is immediate.
    for tool in COVERAGE_ACTIONS:
        assert tool.tier == "confirm", tool.name
        assert tool.undo is None, tool.name
    owner_only = {t.name for t in COVERAGE_ACTIONS if t.permission == "org:manage"}
    assert owner_only == {t.name for t in COVERAGE_ACTIONS} - {"knowledge_refresh"}


def test_nothing_here_accepts_a_document_pays_or_types_a_code() -> None:
    for tool in COVERAGE_ACTIONS:
        for word in ("legal", "pledge", "kyc", "pay", "topup", "verify", "accept"):
            assert word not in tool.name, tool.name


def test_only_the_save_number_switch_asks_for_its_buttons_code() -> None:
    tool = write_tools.tool_named("account_switch_set")
    assert tool is not None and tool.action_code is not None
    assert tool.action_code({"switch": "save_number_whatsapp", "on": True}) == (
        "save_number_message:{org}"
    )
    assert tool.action_code({"switch": "staff_knowledge", "on": True}) is None
    gated = {t.name for t in COVERAGE_ACTIONS if t.action_code is not None}
    assert gated == {"account_switch_set"}


def test_the_reads_are_client_only() -> None:
    admin = {tool.name for tool in service.realm_read_tools("admin")}
    client = {tool.name for tool in service.realm_read_tools("client")}
    for read in COVERAGE_READS:
        assert read.name in client
        assert read.name not in admin


@pytest.mark.parametrize("tool", COVERAGE_ACTIONS, ids=lambda tool: tool.name)
async def test_staff_are_refused_inside_every_coverage_tool(tool: Any) -> None:
    tenant_id, _slug, token = await _make_tenant()
    principal = _principal(tenant_id, _user_of(token), role="staff")
    with pytest.raises(write_tools.WriteRefusedError) as refused:
        await write_tools.plan_write(tool.name, "{}", actor=write_tools.actor_for(principal))
    assert "role may not" in refused.value.reason


# --- help ------------------------------------------------------------------------------------


def test_the_help_glossary_is_the_consoles_own() -> None:
    """`help.GLOSSARY` mirrors `lib/glossary.tsx`'s client wording, key for key."""
    source = (_REPO / "apps/web/src/lib/glossary.tsx").read_text(encoding="utf-8")
    body = source.split("export const GLOSSARY = {", 1)[1].split("} as const", 1)[0]
    found: dict[str, tuple[str, str]] = {}
    for key, block in re.findall(r"\n  (\w+): \{(.*?)\n  \},", body, flags=re.S):
        term = re.search(r'term: "([^"]*)"', block)
        gloss = re.search(r'gloss:\s*"([^"]*)"', block)
        assert term and gloss, key
        found[key] = (term.group(1), gloss.group(1))
    assert found == {key: (e.term, e.gloss) for key, e in GLOSSARY.items()}


async def test_help_names_the_screen_and_the_action_for_an_owner() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    answer = await _read("help_lookup", tenant_id, {"question": "how do I invite a colleague?"})
    assert "Team, under Settings & account" in answer
    assert "team_do team_invite" in answer
    assert "never add steps" in answer


async def test_help_names_the_follow_ups_screen_and_pips_follow_up_actions() -> None:
    """D-940: "how do I…" about a lead journey lands on Follow-ups and what Pip can do."""
    tenant_id, _slug, _token = await _make_tenant()
    answer = await _read("help_lookup", tenant_id, {"question": "how do I set up a follow-up?"})
    assert "Follow-ups" in answer
    assert "leads_do follow_up_draft" in answer


async def test_help_offers_staff_no_action_their_role_would_refuse() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    answer = await _read("help_lookup", tenant_id, {"question": "invite a colleague"}, role="staff")
    assert "Team, under Settings & account" in answer
    assert "team_invite" not in answer


async def test_help_explains_a_term_from_the_glossary() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    answer = await _read("help_lookup", tenant_id, {"question": "what is DND?"})
    assert "India's national Do Not Disturb registry" in answer


async def test_help_says_when_nothing_matches() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    answer = await _read("help_lookup", tenant_id, {"question": "zzqx flurb"})
    assert answer.startswith("No help entry matches")


# --- the owner's switches --------------------------------------------------------------------


async def test_staff_knowledge_switch_is_confirmed_and_audited_in_this_account_only() -> None:
    tenant_id, _slug, token = await _make_tenant()
    other_id, _o, _ot = await _make_tenant()
    args = {"switch": "staff_knowledge", "on": True}
    proposal = await _propose(tenant_id, token, "account_switch_set", args)
    assert (proposal.current, proposal.proposed) == ("off", "on")
    done = await _confirm(tenant_id, _user_of(token), proposal.token)
    assert done.applied is True
    row = await _one(tenant_id, "SELECT staff_may_curate_knowledge FROM organizations")
    assert row[0] is True
    other = await _one(other_id, "SELECT staff_may_curate_knowledge FROM organizations")
    assert other[0] is False
    assert "organization.staff_kb_curation_set" in [
        action for action, _t, _i in await _audit(tenant_id)
    ]
    assert "organization.staff_kb_curation_set" not in [a for a, _t, _i in await _audit(other_id)]
    again = await _do(tenant_id, token, "account_switch_set", args)
    assert again.applied is False


async def test_opt_in_before_calling_is_switched_on() -> None:
    tenant_id, _slug, token = await _make_tenant()
    done = await _do(
        tenant_id, token, "account_switch_set", {"switch": "opt_in_before_calling", "on": True}
    )
    assert done.applied is True
    row = await _one(tenant_id, "SELECT outbound_requires_consent FROM organizations")
    assert row[0] is True


async def test_the_save_number_switch_demands_the_emailed_code() -> None:
    tenant_id, _slug, token = await _make_tenant()
    proposal = await _propose(
        tenant_id, token, "account_switch_set", {"switch": "save_number_whatsapp", "on": True}
    )
    assert proposal.confirm_action == "save_number_message:{org}"
    with pytest.raises(ProblemError) as refused:
        await _confirm(tenant_id, _user_of(token), proposal.token)
    assert refused.value.code == "step_up_required"


# --- the account's AI model tier ------------------------------------------------------------


async def test_the_default_tier_is_already_in_force_on_a_new_account() -> None:
    tenant_id, _slug, token = await _make_tenant()
    proposal = await _propose(tenant_id, token, "account_model_tier_set", {"tier": "default"})
    assert proposal.current == "Calevate's default"
    done = await _confirm(tenant_id, _user_of(token), proposal.token)
    assert done.applied is False


# --- tell my team ----------------------------------------------------------------------------


async def test_a_team_address_is_added_made_default_and_removed() -> None:
    tenant_id, _slug, token = await _make_tenant()
    other_id, _o, other_token = await _make_tenant()
    added = await _do(
        tenant_id,
        token,
        "team_alert_contact",
        {"act": "add", "team_contact_id": None, "address": " Desk@Example.com "},
    )
    assert added.applied is True
    row = await _one(tenant_id, "SELECT id, address, is_default FROM team_alert_contacts")
    contact_id = str(row[0])
    assert (row[1], row[2]) == ("desk@example.com", True)
    # Another account's id is not found: RLS, not a WHERE clause.
    with pytest.raises(ProblemError):
        await _propose(
            other_id,
            other_token,
            "team_alert_contact",
            {"act": "remove", "team_contact_id": contact_id, "address": None},
        )
    await _do(
        tenant_id,
        token,
        "team_alert_contact",
        {"act": "make_default", "team_contact_id": contact_id, "address": None},
    )
    await _do(
        tenant_id,
        token,
        "team_alert_contact",
        {"act": "remove", "team_contact_id": contact_id, "address": None},
    )
    gone = await _one(
        tenant_id,
        "SELECT removed_at IS NOT NULL FROM team_alert_contacts WHERE id = :i",
        i=contact_id,
    )
    assert gone[0] is True


async def test_a_whatsapp_address_is_sent_to_the_screen() -> None:
    tenant_id, _slug, token = await _make_tenant()
    with pytest.raises(write_tools.WriteRefusedError) as refused:
        await _propose(
            tenant_id,
            token,
            "team_alert_contact",
            {"act": "add", "team_contact_id": None, "address": "9876"},
        )
    assert "Alerts screen" in refused.value.reason


async def test_an_agents_team_alert_is_saved_and_shown_in_its_handover_part() -> None:
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    args: dict[str, Any] = {
        "agent_id": str(agent_id),
        "team_contact_id": None,
        "on_outcomes": [],
        "on_answers": [],
        "in_call": False,
    }
    proposal = await _propose(tenant_id, token, "agent_team_alert_set", args)
    assert proposal.current == "never"
    done = await _confirm(tenant_id, _user_of(token), proposal.token)
    assert done.applied is True
    assert "no confirmed team address" in done.detail or "Nothing is sent" in done.detail
    saved = await _one(
        tenant_id, "SELECT count(*) FROM team_alert_rules WHERE agent_id = :a", a=agent_id
    )
    assert saved[0] == 1
    part = await _read("agent_settings", tenant_id, {"agent_id": str(agent_id), "part": "handover"})
    assert "Tells the team:" in part
    assert "Outcomes it can watch:" in part


async def test_a_team_alert_refuses_an_outcome_the_agent_does_not_have() -> None:
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    with pytest.raises(write_tools.WriteRefusedError) as refused:
        await _propose(
            tenant_id,
            token,
            "agent_team_alert_set",
            {
                "agent_id": str(agent_id),
                "team_contact_id": None,
                "on_outcomes": ["no_such_outcome"],
                "on_answers": [],
                "in_call": False,
            },
        )
    assert "handover" in refused.value.reason


async def test_a_team_alert_answer_must_be_key_equals_value() -> None:
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    with pytest.raises(write_tools.WriteRefusedError) as refused:
        await _propose(
            tenant_id,
            token,
            "agent_team_alert_set",
            {
                "agent_id": str(agent_id),
                "team_contact_id": None,
                "on_outcomes": [],
                "on_answers": ["no equals sign"],
                "in_call": False,
            },
        )
    assert "key=value" in refused.value.reason


async def test_a_team_alert_for_another_accounts_agent_is_refused() -> None:
    tenant_id, _slug, token = await _make_tenant()
    other_id, _o, _ot = await _make_tenant()
    foreign = await _agent_of(other_id)
    with pytest.raises((ProblemError, write_tools.WriteRefusedError)):
        await _propose(
            tenant_id,
            token,
            "agent_team_alert_set",
            {
                "agent_id": str(foreign),
                "team_contact_id": None,
                "on_outcomes": [],
                "on_answers": [],
                "in_call": False,
            },
        )


# --- knowledge and connections ---------------------------------------------------------------


async def test_knowledge_refresh_takes_only_a_file_or_link() -> None:
    tenant_id, _slug, token = await _make_tenant()
    with pytest.raises(write_tools.WriteRefusedError) as refused:
        await _propose(
            tenant_id, token, "knowledge_refresh", {"item": "nonsense", "act": "read_again"}
        )
    assert "knowledge_sources" in refused.value.reason


async def test_a_connection_from_nowhere_is_not_found() -> None:
    tenant_id, _slug, token = await _make_tenant()
    missing = str(uuid.uuid4())
    with pytest.raises(ProblemError):
        await _propose(tenant_id, token, "connection_disconnect", {"connection_id": missing})
    checked = await _read("connection_check", tenant_id, {"connection_id": missing})
    assert checked == "No connection with that id in this account."


async def test_integrations_status_lists_the_connected_accounts() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    status = await _read("integrations_status", tenant_id, {})
    assert "Connected accounts: none." in status


# --- admin: the rate card --------------------------------------------------------------------


async def _admin_read(name: str, role: str) -> str:
    return await tools.run_read_tool(
        name,
        "{}",
        context=tools.ToolContext(tenant_id=None, role=role),
        registry=service._read_tool_registry("admin"),
    )


async def test_a_superadmin_reads_the_rate_card_the_panel_shows() -> None:
    card = await _admin_read("admin_rate_card", role="superadmin")
    assert card.startswith("Rate card in force")
    assert "/min, cost ₹" in card


async def test_an_operator_without_config_is_refused_the_rate_card() -> None:
    assert (await _admin_read("admin_rate_card", role="operator")).startswith("Refused")


def test_the_rate_card_is_an_admin_read_only() -> None:
    client = {tool.name for tool in service.realm_read_tools("client")}
    assert "admin_rate_card" not in client
