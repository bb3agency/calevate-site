"""Pip's campaign buttons (D-893 lane L3, `copilot/campaign_actions.py`): each plans,
runs the campaign screen's own function, writes the button's audit row, and refuses what
the button refuses."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.api_security_test import _make_tenant

from apps.api.copilot import areas, write_tools
from apps.api.copilot.campaign_actions import CAMPAIGN_ACTIONS
from apps.api.copilot.console_actions_test import _role_without
from apps.api.copilot.write_tools_test import (
    _actor,
    _audit,
    _confirm,
    _make_campaign,
    _principal,
    _user_of,
)
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.main import app


async def _run(tenant_id: UUID, token: str, name: str, args: dict[str, Any]) -> Any:
    return await write_tools.run_immediate(
        name,
        json.dumps(args),
        principal=_principal(tenant_id, _user_of(token)),
        seed=f"campaign-{name}",
        ip=None,
    )


async def _propose(tenant_id: UUID, token: str, name: str, args: dict[str, Any]) -> Any:
    return await write_tools.plan_write(
        name, json.dumps(args), actor=_actor(tenant_id, _user_of(token))
    )


async def _row(tenant_id: UUID, sql: str, **params: Any) -> Any:
    async with tenant_session(tenant_id) as session:
        return (await session.execute(text(sql), params)).first()


async def _contacts(tenant_id: UUID, campaign_id: UUID, *phones: str) -> None:
    async with tenant_session(tenant_id) as session:
        for index, phone in enumerate(phones):
            await session.execute(
                text(
                    "INSERT INTO campaign_contacts (id, tenant_id, campaign_id, phone_e164, name, "
                    "custom, status, attempts, created_at, updated_at) VALUES (gen_random_uuid(), "
                    ":t, :c, :p, :n, '{}'::jsonb, 'pending', 0, now(), now())"
                ),
                {"t": tenant_id, "c": campaign_id, "p": phone, "n": f"Person {index}"},
            )


# --- the registry -------------------------------------------------------------------------


def test_only_the_draft_edit_skips_the_click_and_every_tool_has_an_area() -> None:
    tiers = {tool.name: tool.tier for tool in CAMPAIGN_ACTIONS}
    assert tiers == {
        "campaign_edit": "immediate",
        "campaign_repeat": "confirm",
        "campaign_stop": "confirm",
        "campaign_delete": "confirm",
        "campaign_contacts_add": "confirm",
        "campaign_contacts_remove": "confirm",
    }
    for tool in CAMPAIGN_ACTIONS:
        assert tool.permission == "leads:dispatch", tool.name
        assert areas.AREA_OF[tool.name] == "campaigns", tool.name
        assert write_tools.tool_named(tool.name) is tool


@pytest.mark.parametrize("tool", CAMPAIGN_ACTIONS, ids=lambda tool: tool.name)
async def test_a_role_without_dispatch_is_refused_inside_the_tool(tool: Any) -> None:
    tenant_id, _slug, token = await _make_tenant()
    principal = _principal(tenant_id, _user_of(token), role=_role_without(tool.permission))
    args = json.dumps({"campaign_id": str(await _make_campaign(tenant_id, status="draft"))})
    with pytest.raises(write_tools.WriteRefusedError) as refused:
        if tool.tier == "immediate":
            await write_tools.run_immediate(tool.name, args, principal=principal, seed="s", ip=None)
        else:
            await write_tools.plan_write(tool.name, args, actor=write_tools.actor_for(principal))
    assert "role may not" in refused.value.reason


# --- campaign_edit ------------------------------------------------------------------------


async def test_edit_changes_a_draft_and_its_retry_policy_and_undo_puts_them_back() -> None:
    tenant_id, slug, token = await _make_tenant()
    campaign_id = await _make_campaign(tenant_id, status="draft")
    before = await _row(
        tenant_id, "SELECT name, retry_policy FROM campaigns WHERE id = :i", i=campaign_id
    )
    receipt = await _run(
        tenant_id,
        token,
        "campaign_edit",
        {
            "campaign_id": str(campaign_id),
            "name": "Spring recall",
            "hours": "10:00-18:00",
            "tries": 3,
            "gaps_minutes": [60, 1440],
        },
    )
    after = await _row(
        tenant_id,
        "SELECT name, calling_hours, retry_policy FROM campaigns WHERE id = :i",
        i=campaign_id,
    )
    assert after[0] == "Spring recall"
    assert after[1] == {"start": "10:00", "end": "18:00"}
    assert after[2] == {"max_attempts": 3, "backoff_minutes": [60, 1440]}
    assert ("campaign.updated", "campaign", str(campaign_id)) in await _audit(tenant_id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        undone = await http.post(
            f"/v1/copilot/actions/{receipt.action_id}/undo",
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug},
        )
    assert undone.status_code == 200, undone.text
    restored = await _row(
        tenant_id,
        "SELECT name, calling_hours, retry_policy FROM campaigns WHERE id = :i",
        i=campaign_id,
    )
    assert (restored[0], restored[1], restored[2]) == (before[0], None, before[1])


async def test_edit_keeps_the_chosen_gaps_when_only_the_tries_change() -> None:
    tenant_id, _slug, token = await _make_tenant()
    campaign_id = await _make_campaign(tenant_id, status="draft")
    await _run(tenant_id, token, "campaign_edit", {"campaign_id": str(campaign_id), "tries": 4})
    policy = (
        await _row(tenant_id, "SELECT retry_policy FROM campaigns WHERE id = :i", i=campaign_id)
    )[0]
    assert policy["max_attempts"] == 4
    assert len(policy["backoff_minutes"]) == 3


async def test_edit_undo_refuses_after_a_later_change_and_edit_refuses_a_launched_one() -> None:
    tenant_id, slug, token = await _make_tenant()
    campaign_id = await _make_campaign(tenant_id, status="draft")
    receipt = await _run(
        tenant_id, token, "campaign_edit", {"campaign_id": str(campaign_id), "concurrency": 5}
    )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaigns SET concurrency = 2 WHERE id = :i"), {"i": campaign_id}
        )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        refused = await http.post(
            f"/v1/copilot/actions/{receipt.action_id}/undo",
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug},
        )
    assert refused.status_code == 409

    running = await _make_campaign(tenant_id)
    with pytest.raises(write_tools.WriteRefusedError) as not_draft:
        await _run(tenant_id, token, "campaign_edit", {"campaign_id": str(running), "tries": 2})
    assert "only a draft" in not_draft.value.reason
    with pytest.raises(write_tools.WriteRefusedError):
        await _run(
            tenant_id, token, "campaign_edit", {"campaign_id": str(campaign_id), "hours": "late"}
        )


# --- campaign_repeat ----------------------------------------------------------------------


async def test_repeat_needs_a_click_and_sets_the_weekly_start() -> None:
    tenant_id, _slug, token = await _make_tenant()
    campaign_id = await _make_campaign(tenant_id, status="draft")
    proposal = await _propose(
        tenant_id,
        token,
        "campaign_repeat",
        {"campaign_id": str(campaign_id), "days": [2, 4], "at": "10:30", "until": None},
    )
    assert "every Tue, Thu at 10:30 IST" in proposal.summary
    assert (await _row(tenant_id, "SELECT status FROM campaigns WHERE id = :i", i=campaign_id))[
        0
    ] == "draft"
    await _confirm(tenant_id, _user_of(token), proposal.token)
    status, schedule = await _row(
        tenant_id, "SELECT status, schedule FROM campaigns WHERE id = :i", i=campaign_id
    )
    assert status == "scheduled"
    assert schedule["rule"] == {"days": [2, 4], "at": "10:30"}
    assert ("campaign.recurrence_set", "campaign", str(campaign_id)) in await _audit(tenant_id)

    running = await _make_campaign(tenant_id)
    with pytest.raises(write_tools.WriteRefusedError):
        await _propose(
            tenant_id,
            token,
            "campaign_repeat",
            {"campaign_id": str(running), "days": [1], "at": "10:00", "until": None},
        )


# --- campaign_stop and campaign_delete ----------------------------------------------------


async def test_stop_ends_a_running_campaign_and_sends_a_draft_to_delete() -> None:
    tenant_id, _slug, token = await _make_tenant()
    draft = await _make_campaign(tenant_id, status="draft")
    with pytest.raises(write_tools.WriteRefusedError) as refused:
        await _propose(tenant_id, token, "campaign_stop", {"campaign_id": str(draft)})
    assert "campaign_delete" in refused.value.reason

    running = await _make_campaign(tenant_id)
    await _contacts(tenant_id, running, "+919800000001")
    proposal = await _propose(tenant_id, token, "campaign_stop", {"campaign_id": str(running)})
    assert "the 1 people not yet called" in proposal.summary
    await _confirm(tenant_id, _user_of(token), proposal.token)
    assert (await _row(tenant_id, "SELECT status FROM campaigns WHERE id = :i", i=running))[
        0
    ] == "cancelled"
    assert ("campaign.stopped", "campaign", str(running)) in await _audit(tenant_id)


async def test_delete_removes_a_draft_and_refuses_a_launched_one() -> None:
    tenant_id, _slug, token = await _make_tenant()
    draft = await _make_campaign(tenant_id, status="draft")
    proposal = await _propose(tenant_id, token, "campaign_delete", {"campaign_id": str(draft)})
    await _confirm(tenant_id, _user_of(token), proposal.token)
    assert await _row(tenant_id, "SELECT 1 FROM campaigns WHERE id = :i", i=draft) is None
    assert ("campaign.deleted", "campaign", str(draft)) in await _audit(tenant_id)

    running = await _make_campaign(tenant_id)
    with pytest.raises(write_tools.WriteRefusedError) as refused:
        await _propose(tenant_id, token, "campaign_delete", {"campaign_id": str(running)})
    assert "campaign_stop" in refused.value.reason


# --- contacts -----------------------------------------------------------------------------


async def test_contacts_from_a_list_are_counted_on_the_card_and_added_on_confirm() -> None:
    tenant_id, _slug, token = await _make_tenant()
    campaign_id = await _make_campaign(tenant_id, status="draft")
    proposal = await _propose(
        tenant_id,
        token,
        "campaign_contacts_add",
        {
            "campaign_id": str(campaign_id),
            "contacts": [
                {"phone": "98000 00011", "name": "Asha"},
                {"phone": "+919800000012", "name": None},
                {"phone": "not a number", "name": "Ravi"},
            ],
        },
    )
    assert proposal.title.startswith("Add 2 people")
    assert "Ravi" not in proposal.summary
    await _confirm(tenant_id, _user_of(token), proposal.token)
    count = (
        await _row(
            tenant_id,
            "SELECT count(*) FROM campaign_contacts WHERE campaign_id = :i",
            i=campaign_id,
        )
    )[0]
    assert count == 2
    assert ("campaign.contacts_added", "campaign", str(campaign_id)) in await _audit(tenant_id)

    running = await _make_campaign(tenant_id)
    with pytest.raises(write_tools.WriteRefusedError):
        await _propose(
            tenant_id,
            token,
            "campaign_contacts_add",
            {"campaign_id": str(running), "contacts": [{"phone": "9800000013", "name": None}]},
        )


async def test_contacts_are_taken_off_by_name_or_number_exactly_as_the_card_listed() -> None:
    tenant_id, _slug, token = await _make_tenant()
    campaign_id = await _make_campaign(tenant_id, status="draft")
    await _contacts(tenant_id, campaign_id, "+919800000021", "+919800000022", "+919800000023")
    proposal = await _propose(
        tenant_id,
        token,
        "campaign_contacts_remove",
        {"campaign_id": str(campaign_id), "who": ["person 0", "98000 00022"]},
    )
    assert proposal.title.startswith("Take 2 people off")
    # Added after the card was drawn, with a name the card matched: not removed.
    await _contacts(tenant_id, campaign_id, "+919800000024")
    await _confirm(tenant_id, _user_of(token), proposal.token)
    left = await _row(
        tenant_id,
        "SELECT count(*) FROM campaign_contacts WHERE campaign_id = :i",
        i=campaign_id,
    )
    assert left[0] == 2
    assert ("campaign.contacts_removed", "campaign", str(campaign_id)) in await _audit(tenant_id)

    with pytest.raises(write_tools.WriteRefusedError):
        await _propose(
            tenant_id,
            token,
            "campaign_contacts_remove",
            {"campaign_id": str(campaign_id), "who": ["Nobody here"]},
        )


async def test_a_neighbours_campaign_is_a_404_for_every_campaign_action() -> None:
    tenant_a, _slug_a, token_a = await _make_tenant()
    tenant_b, _slug_b, _token_b = await _make_tenant()
    foreign = str(await _make_campaign(tenant_b, status="draft"))
    calls: dict[str, dict[str, Any]] = {
        "campaign_repeat": {"campaign_id": foreign, "days": [1], "at": "10:00", "until": None},
        "campaign_stop": {"campaign_id": foreign},
        "campaign_delete": {"campaign_id": foreign},
        "campaign_contacts_add": {
            "campaign_id": foreign,
            "contacts": [{"phone": "9800000031", "name": None}],
        },
        "campaign_contacts_remove": {"campaign_id": foreign, "who": ["x"]},
    }
    for name, args in calls.items():
        with pytest.raises(ProblemError) as missing:
            await _propose(tenant_a, token_a, name, args)
        assert missing.value.status == 404, name
    with pytest.raises(ProblemError) as missing_edit:
        await _run(tenant_a, token_a, "campaign_edit", {"campaign_id": foreign, "tries": 2})
    assert missing_edit.value.status == 404
