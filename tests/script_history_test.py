"""Script versions and "Put back the flow from before Pip" (D-1039).

The founder's report (Rytu Khata, 24 Nov 2026): "Put back the flow from before Pip" said
"Flow put back" and nothing visibly changed. The one switch-back copy was overwritten by every
automatic pass with the script as it stood just before its own small edit, so put-back
restored a near-identical script. These tests pin the replacement: every save is a version,
put-back restores the owner's own last one, and it never claims a change it did not make.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from apps.api.campaigns import script_history, workspace, workspace_routes
from apps.api.db.session import tenant_session
from apps.api.inbound import lines
from apps.api.inbound import routes as line_routes
from apps.api.main import app
from apps.workers import script_heal as heal_job
from calevate_shared.call_script import CallScript
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.a2p_declaration_test import _org_headers
from tests.script_heal_2026_11_24_test import (
    BRACKETED,
    PLAIN,
    _account,
    _campaign,
    _line,
    _payload,
    _queue,
    _script,
    _writer,
)

OWNERS_LINE = "Open the app store, search for Rytu Khata and press Install."


async def _http(tenant_id: UUID, method: str, path: str, body: Any = None) -> Any:
    headers = await _org_headers(tenant_id)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        return await http.request(method, path, headers=headers, json=body)


async def _stored(tenant_id: UUID, table: str, holder_id: UUID) -> CallScript:
    async with tenant_session(tenant_id) as session:
        raw = (
            await session.execute(
                text(f"SELECT script FROM {table} WHERE id = :h"), {"h": holder_id}
            )
        ).scalar_one()
    return CallScript.model_validate(raw)


async def _owner_then_pip(tenant_id: UUID, campaign_id: UUID) -> None:
    """The owner's own flow, then Pip's draft they kept (with a fault the repair clears)."""
    async with tenant_session(tenant_id) as session:
        await workspace.save_script(session, campaign_id, _script(OWNERS_LINE), author="owner")
    async with tenant_session(tenant_id) as session:
        await workspace.save_script(session, campaign_id, _script(BRACKETED), author="pip_draft")


async def test_put_back_after_an_automatic_repair_restores_the_owners_pre_pip_script(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: the automatic repair's own save becomes what put-back restores (the
    founder's "nothing visibly changed"), or put-back reaches anything but the owner's own
    script."""
    tenant_id, agent_id = await _account("putback")
    campaign_id = await _campaign(tenant_id, agent_id, _script(OWNERS_LINE))
    await _owner_then_pip(tenant_id, campaign_id)
    _writer(monkeypatch, _script(PLAIN))
    await _queue(tenant_id, "campaign", campaign_id)
    assert (
        await heal_job.repair_holder_script({}, _payload(tenant_id, "campaign", campaign_id))
        == "repaired"
    )
    path = f"/v1/campaigns/{campaign_id}/script"

    listed = (await _http(tenant_id, "GET", f"{path}/versions")).json()

    assert [v["author"] for v in listed["versions"]] == ["pip_repair", "pip_draft", "owner"]
    assert listed["put_back"]["version"]["author"] == "owner"
    back = await _http(
        tenant_id,
        "POST",
        f"{path}/restore-before-pip",
        {"expected_version_id": listed["current_version_id"]},
    )
    assert back.status_code == 200, back.text
    assert (await _stored(tenant_id, "campaigns", campaign_id)).stages[0].sounds_like == (
        OWNERS_LINE
    )
    # The restore is a version too, the owner's own, so the button now says why it waits.
    after = (await _http(tenant_id, "GET", f"{path}/versions")).json()
    assert after["versions"][0]["author"] == "restored"
    assert after["put_back"] == {"version": None, "unavailable": "already_current"}


async def test_put_back_with_nothing_to_restore_never_claims_success() -> None:
    """FAILS IF: put-back answers 200 when no owner version exists or the owner's last
    version is already the script."""
    tenant_id, agent_id = await _account("nothing")
    campaign_id = await _campaign(tenant_id, agent_id, _script(OWNERS_LINE))
    async with tenant_session(tenant_id) as session:
        await workspace.save_script(session, campaign_id, _script(BRACKETED), author="pip_draft")
    path = f"/v1/campaigns/{campaign_id}/script"
    listed = (await _http(tenant_id, "GET", f"{path}/versions")).json()
    assert listed["put_back"] == {"version": None, "unavailable": "no_owner_version"}

    refused = await _http(
        tenant_id,
        "POST",
        f"{path}/restore-before-pip",
        {"expected_version_id": listed["current_version_id"]},
    )

    assert refused.status_code == 409, refused.text
    assert refused.json()["type"].endswith("/nothing_to_put_back")
    async with tenant_session(tenant_id) as session:
        await workspace.save_script(session, campaign_id, _script(OWNERS_LINE), author="owner")
    listed = (await _http(tenant_id, "GET", f"{path}/versions")).json()
    assert listed["put_back"]["unavailable"] == "already_current"
    same = await _http(
        tenant_id,
        "POST",
        f"{path}/restore-before-pip",
        {"expected_version_id": listed["current_version_id"]},
    )
    assert same.status_code == 409 and same.json()["type"].endswith("/nothing_to_put_back")


async def test_a_restore_is_compare_and_set_and_puts_the_script_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: a restore lands over a save made after the page read the history, or a
    restore that lands is not put on the campaign's calls."""
    tenant_id, agent_id = await _account("cas")
    campaign_id = await _campaign(tenant_id, agent_id, _script(OWNERS_LINE))
    await _owner_then_pip(tenant_id, campaign_id)
    put_live: list[UUID] = []

    async def holds(*_args: Any) -> bool:
        return True

    async def put_campaign_live(*, tenant_id: UUID, campaign_id: UUID, **_kwargs: Any) -> None:
        put_live.append(campaign_id)

    monkeypatch.setattr(workspace_routes, "_holds_engine_agent", holds)
    monkeypatch.setattr(workspace_routes, "put_campaign_live", put_campaign_live)
    path = f"/v1/campaigns/{campaign_id}/script"
    seen = (await _http(tenant_id, "GET", f"{path}/versions")).json()
    async with tenant_session(tenant_id) as session:
        await workspace.save_script(session, campaign_id, _script(PLAIN), author="pip_outcomes")

    stale = await _http(
        tenant_id,
        "POST",
        f"{path}/restore-before-pip",
        {"expected_version_id": seen["current_version_id"]},
    )

    assert stale.status_code == 409 and stale.json()["type"].endswith("/script_changed")
    assert (await _stored(tenant_id, "campaigns", campaign_id)).stages[0].sounds_like == PLAIN
    assert put_live == []
    fresh = (await _http(tenant_id, "GET", f"{path}/versions")).json()
    pip_draft = next(v for v in fresh["versions"] if v["author"] == "pip_draft")
    back = await _http(
        tenant_id,
        "POST",
        f"{path}/versions/{pip_draft['id']}/restore",
        {"expected_version_id": fresh["current_version_id"]},
    )
    assert back.status_code == 200, back.text
    assert (await _stored(tenant_id, "campaigns", campaign_id)).stages[0].sounds_like == (BRACKETED)
    assert put_live == [campaign_id]
    # Pip's version brought back is not the owner's: put-back still reaches theirs.
    after = (await _http(tenant_id, "GET", f"{path}/versions")).json()
    assert after["put_back"]["version"]["author"] == "owner"


async def test_an_inbound_lines_put_back_restores_the_owners_script(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: a line has no put-back, or it is not put live after a restore."""
    tenant_id, agent_id = await _account("line")
    line_id = await _line(tenant_id, agent_id, _script(OWNERS_LINE))
    async with tenant_session(tenant_id) as session:
        await lines.save_script(session, line_id, _script(BRACKETED), author="pip_draft")
        await lines.save_script(session, line_id, _script(PLAIN), author="pip_repair")
    put_live: list[UUID] = []

    async def put_line_live(*, tenant_id: UUID, line_id: UUID, **_kwargs: Any) -> None:
        put_live.append(line_id)

    monkeypatch.setattr(line_routes, "put_line_live", put_line_live)
    path = f"/v1/inbound-lines/{line_id}/script"
    listed = (await _http(tenant_id, "GET", f"{path}/versions")).json()
    assert listed["put_back"]["version"]["author"] == "owner"

    back = await _http(
        tenant_id,
        "POST",
        f"{path}/restore-before-pip",
        {"expected_version_id": listed["current_version_id"]},
    )

    assert back.status_code == 200, back.text
    assert (await _stored(tenant_id, "inbound_lines", line_id)).stages[0].sounds_like == (
        OWNERS_LINE
    )
    assert put_live == [line_id]


async def test_the_history_is_bounded_and_keeps_the_owners_last_version() -> None:
    """FAILS IF: the history grows without bound, or a long run of automatic edits prunes
    the owner's own version out of put-back's reach."""
    tenant_id, agent_id = await _account("bound")
    campaign_id = await _campaign(tenant_id, agent_id, _script(OWNERS_LINE))
    async with tenant_session(tenant_id) as session:
        await workspace.save_script(session, campaign_id, _script(OWNERS_LINE), author="owner")
        for n in range(script_history.KEEP + 5):
            await workspace.save_script(
                session, campaign_id, _script(f"{PLAIN} Round {n}."), author="pip_repair"
            )
        kept = await script_history.versions(session, "campaign", campaign_id)
        target = await script_history.put_back(
            session, "campaign", campaign_id, await _current(session, campaign_id)
        )
        count = (
            await session.execute(
                text("SELECT count(*) FROM script_versions WHERE campaign_id = :c"),
                {"c": campaign_id},
            )
        ).scalar_one()
    assert count == script_history.KEEP + 1
    assert len(kept) == script_history.KEEP + 1
    assert kept[-1].author == "owner"
    assert target.version is not None and target.version.author == "owner"


async def _current(session: Any, campaign_id: UUID) -> CallScript:
    return (await workspace.read_workspace(session, campaign_id)).script or CallScript()


async def test_another_account_reads_no_versions_and_restores_none() -> None:
    """FAILS IF: one account sees or restores another account's script versions."""
    tenant_id, agent_id = await _account("rls-a")
    other_id, _ = await _account("rls-b")
    campaign_id = await _campaign(tenant_id, agent_id, _script(OWNERS_LINE))
    await _owner_then_pip(tenant_id, campaign_id)
    async with tenant_session(other_id) as session:
        rows = (await session.execute(text("SELECT count(*) FROM script_versions"))).scalar_one()
        assert rows == 0
        assert await script_history.versions(session, "campaign", campaign_id) == []
    path = f"/v1/campaigns/{campaign_id}/script"
    assert (await _http(other_id, "GET", f"{path}/versions")).status_code == 404
    refused = await _http(
        other_id, "POST", f"{path}/restore-before-pip", {"expected_version_id": None}
    )
    assert refused.status_code == 404
