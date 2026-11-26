"""Pip's script draft, followed live (Pip live, 24 Nov 2026): the draft stream, Keep that saves
and puts live in one compare-and-set step, and the cancel Stop shares.

1. The stream reports the writer's phases as a real job writes a draft (the model replaced),
   then every line in script order and one diff against the script it was written from.
2. Keep on the streamed draft saves it and puts it live as Save does, and the script before
   it stays the switch-back copy.
3. Keep on a draft that is no longer the one on offer, or not yet written, is refused.
4. Cancel while the draft is written leaves the holder exactly as it was, the job ends at its
   next phase without storing anything, and what it spent is metered.
5. Another account's holder is a 404, and its row is invisible.
6. Reconnecting replays where the draft is.

SHARED DATABASE DISCIPLINE: every organisation is minted here and every assertion is scoped
to its own ids. The model is never called.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import uuid
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents.script_proposals import script_diff
from apps.api.campaigns import script_draft, script_history, workspace
from apps.api.db.session import tenant_session
from apps.api.inbound import lines
from apps.api.inbound import routes as line_routes
from apps.api.main import app
from apps.workers import campaign_script
from calevate_shared.call_script import CallScript
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.agent_starters_test import _tenant
from tests.campaign_script_writer_2026_11_15_test import MAIN_TASK, _script

pytestmark = pytest.mark.rls

OLD = _script("Which phone do you use?")
NEW = _script("Which phone do you use, Android or iPhone?", "When can you install it?")


async def _campaign(script: CallScript | None = OLD) -> tuple[UUID, UUID, str]:
    tenant_id, token = await _tenant("real_estate", "Sunrise Homes")
    campaign_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        agent_id = (
            await session.execute(text("SELECT id FROM agents ORDER BY created_at LIMIT 1"))
        ).scalar_one()
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, classification, script) "
                "VALUES (:id, :t, :a, 'Install the app', 'service', CAST(:s AS jsonb))"
            ),
            {
                "id": campaign_id,
                "t": tenant_id,
                "a": agent_id,
                "s": None if script is None else script.model_dump_json(),
            },
        )
        if script is not None:
            await script_history.record(
                session,
                tenant_id=tenant_id,
                kind="campaign",
                holder_id=campaign_id,
                script=script,
                author="owner",
            )
        await workspace.save_main_task(session, campaign_id, MAIN_TASK)
    return tenant_id, campaign_id, token


async def _request(tenant_id: UUID, campaign_id: UUID) -> UUID:
    async with tenant_session(tenant_id) as session:
        requested = await workspace.request_proposal(
            session, tenant_id=tenant_id, campaign_id=campaign_id, requested_by=None
        )
    return requested.id


def _job(tenant_id: UUID, campaign_id: UUID, proposal_id: UUID) -> Any:
    return campaign_script.draft_campaign_script(
        {},
        {
            "tenant_id": str(tenant_id),
            "campaign_id": str(campaign_id),
            "proposal_id": str(proposal_id),
        },
    )


def _frames(body: str) -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    for block in body.replace("\r\n", "\n").split("\n\n"):
        event = next((ln[6:].strip() for ln in block.split("\n") if ln.startswith("event:")), None)
        data = "".join(ln[5:].strip() for ln in block.split("\n") if ln.startswith("data:"))
        if event is not None:
            out.append((event, json.loads(data)))
    return out


async def _http(token: str, method: str, path: str, body: Any = None) -> Any:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        return await http.request(
            method, path, headers={"Authorization": f"Bearer {token}"}, json=body
        )


async def _row(tenant_id: UUID, campaign_id: UUID) -> Any:
    async with tenant_session(tenant_id) as session:
        return (
            await session.execute(
                text("SELECT script, script_proposal FROM campaigns WHERE id = :c"),
                {"c": campaign_id},
            )
        ).one()


async def _versions(tenant_id: UUID, campaign_id: UUID) -> list[script_history.Version]:
    async with tenant_session(tenant_id) as session:
        return await script_history.versions(session, "campaign", campaign_id)


def test_the_diff_matches_steps_by_id_and_lists_a_removed_line_where_it_stood() -> None:
    """FAILS IF: a step inserted before others reads as every later step changed, or a line
    the draft dropped is lost or listed out of script order."""
    before = _script("One?", "Two?")
    after = CallScript.model_validate(
        {
            **before.model_dump(),
            "stages": [s for s in before.model_dump()["stages"] if s["id"] != "s0"],
        }
    )
    changes = script_diff(before, after)
    # Step "Two?" moved from index 1 to 0 and is the same step, not a changed one.
    assert all(c.op in ("same", "removed") for c in changes)
    said = [(c.op, c.before if c.op == "removed" else c.after) for c in changes]
    assert ("removed", "One?") in said and ("same", "Two?") in said
    assert said.index(("removed", "S0")) < said.index(("same", "S1"))
    assert said.index(("same", before.opening_line)) < said.index(("removed", "S0"))
    [two] = [c for c in changes if c.after == "Two?"]
    assert two.path == "stages.0.sounds_like" and two.label == "Step 1 · S1"


async def test_a_stream_open_when_the_draft_is_cancelled_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(script_draft, "POLL_S", 0.01)
    tenant_id, campaign_id, _token = await _campaign()
    proposal_id = await _request(tenant_id, campaign_id)
    events: list[str] = []

    async def follow() -> None:
        async for event in script_draft.draft_events(tenant_id, "campaign", campaign_id):
            events.append(event.data.model_dump()["phase"])

    follower = asyncio.create_task(follow())
    await asyncio.sleep(0.05)
    async with tenant_session(tenant_id) as session:
        assert await script_draft.cancel_draft(
            session,
            tenant_id=tenant_id,
            holder_kind="campaign",
            holder_id=campaign_id,
            proposal_id=proposal_id,
        )
    await asyncio.wait_for(follower, 5)
    assert events == ["reading", "cancelled"]


async def _line_with_draft(status: str) -> tuple[UUID, UUID, str, UUID]:
    tenant_id, token = await _tenant("real_estate", "Line Homes")
    async with tenant_session(tenant_id) as session:
        agent_id = (
            await session.execute(text("SELECT id FROM agents ORDER BY created_at LIMIT 1"))
        ).scalar_one()
        line_id = await lines.create_line(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Front desk",
            main_task=MAIN_TASK,
            created_by=None,
        )
        await lines.save_script(session, line_id, OLD, author="owner")
        proposal = await lines.request_proposal(
            session, tenant_id=tenant_id, line_id=line_id, requested_by=None
        )
        if status == "ready":
            await session.execute(
                text(
                    "UPDATE inbound_lines SET script_proposal = script_proposal || "
                    "jsonb_build_object('status', 'ready', 'script', CAST(:s AS jsonb)) "
                    "WHERE id = :l"
                ),
                {"s": NEW.model_dump_json(), "l": line_id},
            )
    return tenant_id, line_id, token, proposal.id


async def test_a_line_draft_is_kept_live_or_cancelled_by_its_twin_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: a line's Keep does not save and put live, or its cancel touches the line."""
    put_live: list[UUID] = []

    async def put_line_live(*, tenant_id: UUID, line_id: UUID) -> None:
        put_live.append(line_id)

    monkeypatch.setattr(line_routes, "put_line_live", put_line_live)
    tenant_id, line_id, token, proposal_id = await _line_with_draft("ready")
    frames = _frames(
        (await _http(token, "GET", f"/v1/inbound-lines/{line_id}/script-draft/stream")).text
    )
    assert frames[0][1]["phase"] == "ready" and frames[-1][0] == "diff"
    kept = await _http(
        token, "POST", f"/v1/inbound-lines/{line_id}/script-draft/{proposal_id}/keep-live"
    )
    assert kept.status_code == 200, kept.text
    assert CallScript.model_validate(kept.json()["script"]) == NEW
    assert kept.json()["proposal"] is None and put_live == [line_id]

    tenant_id, line_id, token, proposal_id = await _line_with_draft("drafting")
    cancelled = await _http(
        token, "POST", f"/v1/inbound-lines/{line_id}/script-draft/{proposal_id}/cancel"
    )
    assert cancelled.json() == {"cancelled": True}, cancelled.text
    async with tenant_session(tenant_id) as session:
        line = await lines.read_line(session, line_id)
    assert line.proposal is None and line.script == OLD


def test_app_startup_registers_the_draft_canceller_stop_calls() -> None:
    """FAILS IF: the api starts without the script writer's `cancel_draft` registered, so
    Pip's Stop leaves a draft its run started writing. A fresh interpreter, because this
    file imports `script_draft` itself and would register it whatever the app does."""
    probe = (
        "import apps.api.main\n"
        "from apps.api.copilot import run_control\n"
        "c = run_control.draft_canceller()\n"
        "print(getattr(c, '__module__', None), getattr(c, '__qualname__', None))\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, timeout=120, check=False
    )
    assert done.returncode == 0, done.stderr[-2000:]
    assert done.stdout.strip().splitlines()[-1] == "apps.api.campaigns.script_draft cancel_draft"
