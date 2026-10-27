"""D-893 lane L2: lead-source fields, opt-out restore, saved views and exports, through Pip
and through the console's own routes, held to `docs/COPILOT-CONTRACT.md` §5.

Each action calls the service its button's route calls: the same refusals, the same audit
action, the emailed code where the button asks for one, and Undo where an exact inverse
exists. Every test mints its own tenant.
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.api_security_test import _make_tenant

from apps.api.compliance.optout import DETECTED_BY_ENGINE, OptOutSignal, record_call_optout
from apps.api.copilot import areas, write_tools
from apps.api.copilot.lead_actions import LEAD_ACTIONS
from apps.api.copilot.write_tools_test import _audit, _confirm, _principal, _user_of
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.main import app


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _headers(token: str, slug: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}


async def _one(tenant_id: UUID, sql: str, **params: Any) -> Any:
    async with tenant_session(tenant_id) as session:
        return (await session.execute(text(sql), params)).first()


async def _propose(tenant_id: UUID, token: str, name: str, args: dict[str, Any]) -> Any:
    return await write_tools.plan_write(
        name, json.dumps(args), actor=write_tools.actor_for(_principal(tenant_id, _user_of(token)))
    )


async def _confirm_with_code(
    tenant_id: UUID, token: str, proposal_token: str
) -> tuple[Any, list[str]]:
    checked: list[str] = []

    async def check(action: str) -> None:
        checked.append(action)

    async with tenant_session(tenant_id) as session:
        done = await write_tools.confirm(
            session,
            proposal_token,
            principal=_principal(tenant_id, _user_of(token)),
            ip=None,
            code_check=check,
        )
    return done, checked


async def _run(tenant_id: UUID, token: str, name: str, args: dict[str, Any]) -> Any:
    return await write_tools.run_immediate(
        name,
        json.dumps(args),
        principal=_principal(tenant_id, _user_of(token)),
        seed=f"l2-{uuid.uuid4()}",
        ip=None,
    )


async def _undo(token: str, slug: str, action_id: str) -> Any:
    async with _client() as http:
        return await http.post(
            f"/v1/copilot/actions/{action_id}/undo", headers=_headers(token, slug)
        )


async def _lead(tenant_id: UUID) -> tuple[UUID, str]:
    row = await _one(tenant_id, "SELECT id, phone_e164 FROM leads LIMIT 1")
    return UUID(str(row[0])), str(row[1])


def test_every_l2_action_has_its_area_and_tier() -> None:
    assert {tool.name: areas.AREA_OF[tool.name] for tool in LEAD_ACTIONS} == {
        "lead_source_mapping": "integrations",
        "dnc_restore": "leads",
        "lead_view_save": "leads",
        "leads_export": "leads",
        "calls_export": "calls",
    }
    assert {tool.name for tool in LEAD_ACTIONS if tool.tier == "immediate"} == {"lead_view_save"}
    codes = {tool.name: tool.action_code({}) for tool in LEAD_ACTIONS if tool.action_code}
    assert codes == {"leads_export": "export_leads:{org}", "calls_export": "export_calls:{org}"}


@pytest.mark.parametrize("name", ["dnc_restore", "leads_export", "calls_export"])
async def test_staff_are_refused_what_their_buttons_refuse(name: str) -> None:
    tenant_id, _slug, token = await _make_tenant()
    lead_id, _phone = await _lead(tenant_id)
    cases: dict[str, dict[str, Any]] = {
        "dnc_restore": {"lead_id": str(lead_id), "ground": "never_asked", "note": None},
        "leads_export": {"lens": None},
        "calls_export": {"call_lens": None},
    }
    args = cases[name]
    principal = _principal(tenant_id, _user_of(token), role="staff")
    with pytest.raises(write_tools.WriteRefusedError):
        await write_tools.plan_write(name, json.dumps(args), actor=write_tools.actor_for(principal))


# --- lead-source fields ---------------------------------------------------------------------


async def _source(tenant_id: UUID, slug: str, token: str, mapping: dict[str, str]) -> str:
    async with _client() as http:
        made = await http.post(
            "/v1/lead-sources",
            json={"source": "custom", "mapping": mapping},
            headers=_headers(token, slug),
        )
    assert made.status_code == 201, made.text
    return str(made.json()["id"])


async def test_the_route_changes_a_sources_fields_and_audits_the_keys() -> None:
    tenant_id, slug, token = await _make_tenant()
    source_id = await _source(tenant_id, slug, token, {"phone": "Mobile"})
    async with _client() as http:
        changed = await http.put(
            f"/v1/lead-sources/{source_id}/mapping",
            json={"mapping": {"phone": " Phone ", "name": "Full name", "consent_field": "ok"}},
            headers=_headers(token, slug),
        )
        no_phone = await http.put(
            f"/v1/lead-sources/{source_id}/mapping",
            json={"mapping": {"name": "Full name"}},
            headers=_headers(token, slug),
        )
        missing = await http.put(
            f"/v1/lead-sources/{uuid.uuid4()}/mapping",
            json={"mapping": {}},
            headers=_headers(token, slug),
        )
        listed = await http.get("/v1/lead-sources", headers=_headers(token, slug))

    assert changed.status_code == 200, changed.text
    assert changed.json()["mapping"] == {
        "phone": "Phone",
        "name": "Full name",
        "consent_field": "ok",
    }
    assert no_phone.status_code == 422
    assert no_phone.json()["type"].endswith("/mapping_has_no_phone")
    assert missing.status_code == 404
    [source] = listed.json()["items"]
    assert source["mapping"]["phone"] == "Phone"
    assert ("lead_source.mapping_changed", "inbound_webhook", source_id) in await _audit(tenant_id)


async def test_staff_cannot_change_a_sources_fields() -> None:
    tenant_id, slug, token = await _make_tenant()
    source_id = await _source(tenant_id, slug, token, {})
    async with tenant_session(tenant_id) as session:
        await session.execute(text("UPDATE memberships SET role = 'staff'"))
    async with _client() as http:
        refused = await http.put(
            f"/v1/lead-sources/{source_id}/mapping",
            json={"mapping": {"phone": "Mobile"}},
            headers=_headers(token, slug),
        )
    assert refused.status_code == 403


async def test_pip_changes_a_sources_fields_and_undo_puts_them_back() -> None:
    tenant_id, slug, token = await _make_tenant()
    source_id = await _source(tenant_id, slug, token, {"phone": "Mobile"})
    fields = [{"field": "phone", "form_field": "Phone"}, {"field": "name", "form_field": "Name"}]
    proposal = await _propose(
        tenant_id, token, "lead_source_mapping", {"lead_source_id": source_id, "fields": fields}
    )
    assert "phone ← Mobile" in json.dumps(proposal.model_dump(mode="json"), ensure_ascii=False)
    done = await _confirm(tenant_id, _user_of(token), proposal.token)
    assert done.applied is True
    stored = (await _one(tenant_id, "SELECT mapping FROM inbound_webhooks"))[0]
    assert stored == {"phone": "Phone", "name": "Name"}

    action = await _one(
        tenant_id, "SELECT id FROM copilot_actions WHERE tool = 'lead_source_mapping'"
    )
    assert (await _undo(token, slug, str(action[0]))).status_code == 200
    assert (await _one(tenant_id, "SELECT mapping FROM inbound_webhooks"))[0] == {"phone": "Mobile"}

    with pytest.raises(write_tools.WriteRefusedError):
        await _propose(
            tenant_id,
            token,
            "lead_source_mapping",
            {"lead_source_id": source_id, "fields": [{"field": "name", "form_field": "N"}]},
        )


# --- do-not-call restore --------------------------------------------------------------------


async def _opt_out(tenant_id: UUID, phone: str) -> None:
    """An opt-out heard on its own call, filed as the engine signal files it."""
    agent_id = (await _one(tenant_id, "SELECT id FROM agents LIMIT 1"))[0]
    call_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
                "status, created_at, updated_at) VALUES (:id, :tid, :aid, :ecid, 'outbound', "
                ":to, 'completed', now(), now())"
            ),
            {
                "id": call_id,
                "tid": tenant_id,
                "aid": agent_id,
                "ecid": f"out_{uuid.uuid4()}",
                "to": phone,
            },
        )
        await record_call_optout(
            session,
            tenant_id=tenant_id,
            raw_phone=phone,
            call_id=call_id,
            detected_by=DETECTED_BY_ENGINE,
            signal=OptOutSignal(
                rule="engine_contact_opted_out", language="unknown", turn_idx=None, matched=""
            ),
        )


async def test_pip_restores_an_opt_out_on_the_restore_routes_audit_action() -> None:
    tenant_id, _slug, token = await _make_tenant()
    lead_id, phone = await _lead(tenant_id)
    await _opt_out(tenant_id, phone)
    args = {"lead_id": str(lead_id), "ground": "never_asked", "note": None}
    proposal = await _propose(tenant_id, token, "dnc_restore", args)
    assert "1 opt-out(s) on record" in json.dumps(proposal.model_dump(mode="json"))
    done = await _confirm(tenant_id, _user_of(token), proposal.token)

    assert done.applied is True
    assert (await _one(tenant_id, "SELECT count(*) FROM dnc_list WHERE tenant_id IS NOT NULL"))[
        0
    ] == 0
    actions = [action for action, _type, _id in await _audit(tenant_id)]
    assert "dnc.optout_restored.never_asked" in actions


async def test_a_newer_opt_out_than_the_card_showed_is_not_undone_unseen() -> None:
    tenant_id, _slug, token = await _make_tenant()
    lead_id, phone = await _lead(tenant_id)
    await _opt_out(tenant_id, phone)
    proposal = await _propose(
        tenant_id, token, "dnc_restore", {"lead_id": str(lead_id), "ground": "never_asked"}
    )
    await _opt_out(tenant_id, phone)
    with pytest.raises(ProblemError) as stale:
        await _confirm(tenant_id, _user_of(token), proposal.token)
    assert stale.value.code == "dnc_restore_stale"


async def test_a_restore_needs_a_note_hand_added_entries_and_view_as_are_refused() -> None:
    tenant_id, _slug, token = await _make_tenant()
    lead_id, phone = await _lead(tenant_id)
    await _opt_out(tenant_id, phone)
    with pytest.raises(write_tools.WriteRefusedError, match="note"):
        await _propose(
            tenant_id,
            token,
            "dnc_restore",
            {"lead_id": str(lead_id), "ground": "asked_to_be_called"},
        )
    operator = Principal(
        realm="client",
        user_id=_user_of(token),
        tenant_id=tenant_id,
        role="owner",
        impersonating=True,
    )
    with pytest.raises(write_tools.WriteRefusedError, match="view-as"):
        await write_tools.plan_write(
            "dnc_restore",
            json.dumps({"lead_id": str(lead_id), "ground": "never_asked"}),
            actor=write_tools.actor_for(operator),
        )

    # The same number, now on the list by hand rather than by its own opt-out.
    async with tenant_session(tenant_id) as session:
        await session.execute(text("DELETE FROM dnc_list WHERE phone_e164 = :p"), {"p": phone})
        await session.execute(
            text(
                "INSERT INTO dnc_list (id, tenant_id, phone_e164, scope, source, added_at, "
                "created_at) "
                "VALUES (:id, :t, :p, 'tenant', 'manual', now(), now())"
            ),
            {"id": uuid.uuid4(), "t": tenant_id, "p": phone},
        )
    with pytest.raises(write_tools.WriteRefusedError, match="dnc_remove"):
        await _propose(
            tenant_id, token, "dnc_restore", {"lead_id": str(lead_id), "ground": "never_asked"}
        )


# --- saved views ----------------------------------------------------------------------------


async def test_pip_saves_a_rolling_view_and_undo_removes_it() -> None:
    tenant_id, slug, token = await _make_tenant()
    from apps.api.copilot.lead_actions import _today

    today = _today()
    lens = {
        "status": "hot",
        "created_from": str(today.replace(day=1) if today.day > 1 else today),
        "created_to": str(today),
        "follow_up": "not_done",
        "assigned_to": str(_user_of(token)),
    }
    ran = await _run(tenant_id, token, "lead_view_save", {"name": "Hot", "lens": lens})
    async with _client() as http:
        views = (await http.get("/v1/leads/views", headers=_headers(token, slug))).json()["items"]
    [view] = views
    assert view["name"] == "Hot"
    assert view["filters"]["created"]["last_days"] == today.day
    assert view["filters"]["assigned_to_me"] is True
    assert view["filters"]["follow_up"] == "not_done"

    assert (await _undo(token, slug, ran.action_id)).status_code == 200
    async with _client() as http:
        after = (await http.get("/v1/leads/views", headers=_headers(token, slug))).json()["items"]
    assert after == []


async def test_saving_over_a_view_updates_it_and_undo_puts_its_filters_back() -> None:
    tenant_id, slug, token = await _make_tenant()
    await _run(tenant_id, token, "lead_view_save", {"name": "Mine", "lens": {"status": "new"}})
    second = await _run(
        tenant_id, token, "lead_view_save", {"name": " mine ", "lens": {"status": "won"}}
    )
    status = (await _one(tenant_id, "SELECT filters ->> 'status' FROM lead_saved_views"))[0]
    assert status == "won"
    assert (await _undo(token, slug, second.action_id)).status_code == 200
    status = (await _one(tenant_id, "SELECT filters ->> 'status' FROM lead_saved_views"))[0]
    assert status == "new"


@pytest.mark.parametrize(
    ("lens", "why"),
    [({"search": "98765"}, "search"), ({"assigned_to": str(uuid.uuid4())}, "assigned to me")],
)
async def test_a_view_refuses_a_search_or_someone_elses_leads(
    lens: dict[str, Any], why: str
) -> None:
    tenant_id, _slug, token = await _make_tenant()
    with pytest.raises(write_tools.WriteRefusedError, match=why):
        await _run(tenant_id, token, "lead_view_save", {"name": "X", "lens": lens})


# --- exports --------------------------------------------------------------------------------


async def test_a_leads_export_asks_for_the_code_and_downloads_once() -> None:
    tenant_id, slug, token = await _make_tenant()
    proposal = await _propose(tenant_id, token, "leads_export", {"lens": {"status": "new"}})
    assert proposal.confirm_action == "export_leads:{org}"
    assert "1 lead" in json.dumps(proposal.model_dump(mode="json"))
    done, checked = await _confirm_with_code(tenant_id, token, proposal.token)
    assert checked == ["export_leads:{org}"]
    assert done.download_ticket

    async with _client() as http:
        first = await http.post(
            "/v1/exports/download",
            json={"ticket": done.download_ticket},
            headers=_headers(token, slug),
        )
        again = await http.post(
            "/v1/exports/download",
            json={"ticket": done.download_ticket},
            headers=_headers(token, slug),
        )
    assert first.status_code == 200, first.text
    assert first.headers["content-type"].startswith("text/csv")
    assert first.text.count("\n") >= 2, "a header and the one lead"
    assert again.status_code == 404
    assert again.json()["type"].endswith("/export_ticket_gone")
    actions = [action for action, _type, _id in await _audit(tenant_id)]
    assert "leads.export_prepared" in actions and "leads.export" in actions


async def test_a_calls_export_downloads_the_calls_its_lens_matches() -> None:
    tenant_id, slug, token = await _make_tenant()
    _lead_id, phone = await _lead(tenant_id)
    agent_id = (await _one(tenant_id, "SELECT id FROM agents LIMIT 1"))[0]
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, from_e164, "
                "status, created_at, updated_at) VALUES (:id, :tid, :aid, :ecid, 'inbound', "
                ":phone, 'completed', now(), now())"
            ),
            {
                "id": uuid.uuid4(),
                "tid": tenant_id,
                "aid": agent_id,
                "ecid": f"in_{uuid.uuid4()}",
                "phone": phone,
            },
        )
    proposal = await _propose(
        tenant_id, token, "calls_export", {"call_lens": {"direction": "inbound"}}
    )
    assert proposal.confirm_action == "export_calls:{org}"
    done, checked = await _confirm_with_code(tenant_id, token, proposal.token)
    assert checked == ["export_calls:{org}"]
    async with _client() as http:
        got = await http.post(
            "/v1/exports/download",
            json={"ticket": done.download_ticket},
            headers=_headers(token, slug),
        )
    assert got.status_code == 200, got.text
    assert phone in got.text
    assert "calls.export" in [action for action, _type, _id in await _audit(tenant_id)]


async def test_an_empty_calls_export_is_refused_on_the_card() -> None:
    tenant_id, _slug, token = await _make_tenant()
    with pytest.raises(write_tools.WriteRefusedError, match="no call"):
        await _propose(tenant_id, token, "calls_export", {"call_lens": {"direction": "inbound"}})


async def test_a_ticket_opens_nothing_for_another_account() -> None:
    from apps.api.crm import export_tickets

    tenant_id, _slug, token = await _make_tenant()
    _other_id, other_slug, other_token = await _make_tenant()
    ticket = await export_tickets.issue(
        tenant_id=tenant_id, user_id=_user_of(token), kind="leads", lens={}
    )
    async with _client() as http:
        stolen = await http.post(
            "/v1/exports/download",
            json={"ticket": ticket},
            headers=_headers(other_token, other_slug),
        )
    assert stolen.status_code == 404
