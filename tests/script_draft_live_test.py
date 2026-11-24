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
from apps.api.agents.script_lint import LintContext
from apps.api.agents.script_proposals import script_diff
from apps.api.campaigns import script_draft, script_history, workspace, workspace_routes
from apps.api.core.settings import get_settings
from apps.api.crm import assist as crm_assist
from apps.api.db.session import tenant_session
from apps.api.inbound import lines
from apps.api.inbound import routes as line_routes
from apps.api.main import app
from apps.workers import campaign_script
from apps.workers import script_proposal as proposal_worker
from calevate_shared.call_script import CallScript
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.agent_starters_test import _tenant
from tests.campaign_script_writer_2026_11_15_test import MAIN_TASK, _answer, _script
from tests.campaign_script_writer_2026_11_16_test import _review

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


def _fake_model(monkeypatch: pytest.MonkeyPatch, write: Any) -> list[str]:
    """The writer's model and checks replaced; returns what was metered."""
    metered: list[str] = []

    async def review_pass(*_args: Any, **_kwargs: Any) -> Any:
        return _review({})

    async def size(*_args: Any) -> None:
        return None

    async def lint_context(*_args: Any, **_kwargs: Any) -> LintContext:
        return LintContext(promo=False)

    async def openings(_t: UUID, _a: UUID, _p: Any, script: CallScript, **_kw: Any) -> Any:
        return script, []

    async def meter_assist(_session: Any, **kwargs: Any) -> None:
        metered.append(kwargs["model"])

    async def meter_earlier(_session: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(get_settings(), "script_mistake_repair_passes", 0)
    monkeypatch.setattr(campaign_script, "draft_script", write)
    monkeypatch.setattr(campaign_script, "ask_json", review_pass)
    monkeypatch.setattr(campaign_script, "_size", size)
    monkeypatch.setattr(proposal_worker, "draft_script", write)
    monkeypatch.setattr(proposal_worker, "lint_context_for", lint_context)
    monkeypatch.setattr(proposal_worker, "_opening_repaired", openings)
    monkeypatch.setattr(crm_assist, "meter_assist", meter_assist)
    monkeypatch.setattr(crm_assist, "meter_earlier", meter_earlier)
    return metered


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


async def _written(monkeypatch: pytest.MonkeyPatch) -> tuple[UUID, UUID, str, UUID]:
    """A campaign with a ready draft of NEW over its saved OLD."""
    tenant_id, campaign_id, token = await _campaign()

    async def write(_brief: Any, **_kwargs: Any) -> Any:
        return _answer(NEW)

    _fake_model(monkeypatch, write)
    proposal_id = await _request(tenant_id, campaign_id)
    assert await _job(tenant_id, campaign_id, proposal_id) == "ready"
    return tenant_id, campaign_id, token, proposal_id


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


async def test_the_stream_reports_the_phases_then_every_line_and_the_diff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: the writer publishes no phase, the stream does not follow it, or the written
    draft does not arrive as its lines in script order and one diff by script path."""
    monkeypatch.setattr(script_draft, "POLL_S", 0.01)
    tenant_id, campaign_id, _token = await _campaign()
    writing, release = asyncio.Event(), asyncio.Event()

    async def write(_brief: Any, **_kwargs: Any) -> Any:
        writing.set()
        await release.wait()
        return _answer(NEW)

    _fake_model(monkeypatch, write)
    proposal_id = await _request(tenant_id, campaign_id)
    events: list[tuple[str, Any]] = []

    async def follow() -> None:
        async for event in script_draft.draft_events(tenant_id, "campaign", campaign_id):
            events.append((str(event.event), event.data.model_dump(mode="json")))

    follower = asyncio.create_task(follow())
    job = asyncio.create_task(_job(tenant_id, campaign_id, proposal_id))
    await asyncio.wait_for(writing.wait(), 5)
    for _ in range(200):
        if ("phase", {"phase": "writing", "detail": None}) in events:
            break
        await asyncio.sleep(0.01)
    release.set()
    assert await job == "ready"
    await asyncio.wait_for(follower, 5)

    phases = [data["phase"] for name, data in events if name == "phase"]
    assert phases[0] == "reading" and "writing" in phases and phases[-1] == "ready"
    assert phases.index("writing") < phases.index("ready")
    lines = [data for name, data in events if name == "line"]
    [diff] = [data for name, data in events if name == "diff"]
    assert events[-1][0] == "diff" and diff["proposal_id"] == str(proposal_id)
    # Every line of the draft, in script order, each with the owner's name for its place.
    expected = [c for c in script_diff(OLD, NEW) if c.op != "removed"]
    assert [ln["path"] for ln in lines] == [c.path for c in expected]
    assert lines[0] == {
        "path": "opening_line",
        "label": "The opening line",
        "text": NEW.opening_line,
    }
    changed = {c["path"]: c for c in diff["changes"] if c["op"] != "same"}
    assert changed["stages.0.sounds_like"]["op"] == "changed"
    assert changed["stages.0.sounds_like"]["label"] == "Step 1 · S0"
    assert changed["stages.1.name"]["op"] == "added"
    assert {c["op"] for c in diff["changes"]} >= {"same", "changed", "added"}


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


async def test_keep_puts_the_draft_live_and_keeps_the_switch_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: Keep does not save the draft as written, does not put it live as Save
    does, leaves the draft standing, or loses the script before it for the switch-back."""
    tenant_id, campaign_id, token, proposal_id = await _written(monkeypatch)
    written = (await _row(tenant_id, campaign_id)).script_proposal["script"]
    put_live: list[UUID] = []

    async def holds(*_args: Any) -> bool:
        return True

    async def put_campaign_live(*, tenant_id: UUID, campaign_id: UUID, **_kwargs: Any) -> None:
        put_live.append(campaign_id)

    monkeypatch.setattr(workspace_routes, "_holds_engine_agent", holds)
    monkeypatch.setattr(workspace_routes, "put_campaign_live", put_campaign_live)
    kept = await _http(
        token, "POST", f"/v1/campaigns/{campaign_id}/script-draft/{proposal_id}/keep-live"
    )
    assert kept.status_code == 200, kept.text
    assert kept.json()["proposal"] is None
    assert put_live == [campaign_id]
    row = await _row(tenant_id, campaign_id)
    assert CallScript.model_validate(row.script) == CallScript.model_validate(written)
    listed = (await _http(token, "GET", f"/v1/campaigns/{campaign_id}/script/versions")).json()
    assert [v["author"] for v in listed["versions"]] == ["pip_draft", "owner"]
    assert listed["put_back"]["version"]["id"] == listed["versions"][1]["id"]
    back = await _http(
        token,
        "POST",
        f"/v1/campaigns/{campaign_id}/script/restore-before-pip",
        {"expected_version_id": listed["current_version_id"]},
    )
    assert back.status_code == 200, back.text
    assert CallScript.model_validate((await _row(tenant_id, campaign_id)).script) == OLD


async def test_keep_on_a_stale_or_unwritten_draft_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: an old screen's Keep saves a draft that is no longer the one on offer, or
    Keep saves a draft Pip is still writing."""
    tenant_id, campaign_id, token, proposal_id = await _written(monkeypatch)
    stale = await _http(
        token, "POST", f"/v1/campaigns/{campaign_id}/script-draft/{uuid.uuid4()}/keep-live"
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["type"].endswith("/script_draft_stale")
    # A new request replaces the ready draft: the one the screen showed is now stale.
    newer = await _request(tenant_id, campaign_id)
    replaced = await _http(
        token, "POST", f"/v1/campaigns/{campaign_id}/script-draft/{proposal_id}/keep-live"
    )
    assert replaced.status_code == 409 and replaced.json()["type"].endswith("/script_draft_stale")
    drafting = await _http(
        token, "POST", f"/v1/campaigns/{campaign_id}/script-draft/{newer}/keep-live"
    )
    assert drafting.status_code == 409 and drafting.json()["type"].endswith(
        "/script_draft_not_ready"
    )
    assert CallScript.model_validate((await _row(tenant_id, campaign_id)).script) == OLD


async def test_cancel_while_writing_leaves_the_campaign_as_it_was_and_ends_the_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: a draft cancelled mid-write is stored, the job runs its later passes, the
    request or the cancel adds a script version, or the pass it had already paid for goes
    unmetered."""
    tenant_id, campaign_id, token = await _campaign()
    before = await _row(tenant_id, campaign_id)
    versions_before = await _versions(tenant_id, campaign_id)
    calls: list[str] = []
    answers: list[Any] = []

    async def write(_brief: Any, **_kwargs: Any) -> Any:
        calls.append("write")
        answers.append(
            await _http(
                token, "POST", f"/v1/campaigns/{campaign_id}/script-draft/{proposal_id}/cancel"
            )
        )
        return _answer(NEW)

    metered = _fake_model(monkeypatch, write)
    proposal_id = await _request(tenant_id, campaign_id)
    assert await _job(tenant_id, campaign_id, proposal_id) == "cancelled"
    [answer] = answers
    assert answer.status_code == 200 and answer.json() == {"cancelled": True}, answer.text
    # The first pass ran and is metered; its edit pass (a first script's) never did.
    assert calls == ["write"] and len(metered) == 1
    after = await _row(tenant_id, campaign_id)
    assert after.script_proposal is None
    assert after.script == before.script
    assert await _versions(tenant_id, campaign_id) == versions_before
    # Nothing left to cancel: idempotent, and the stream now has no draft to follow.
    again = await _http(
        token, "POST", f"/v1/campaigns/{campaign_id}/script-draft/{proposal_id}/cancel"
    )
    assert again.json() == {"cancelled": False}
    gone = await _http(token, "GET", f"/v1/campaigns/{campaign_id}/script-draft/stream")
    assert gone.status_code == 404


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


async def test_another_account_cannot_follow_keep_or_cancel_a_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: a neighbour's session reaches a draft by its ids (hard rule 1)."""
    tenant_id, campaign_id, _token, proposal_id = await _written(monkeypatch)
    other_tenant, other = await _tenant("real_estate", "Other Homes")
    for method, path in (
        ("GET", f"/v1/campaigns/{campaign_id}/script-draft/stream"),
        ("POST", f"/v1/campaigns/{campaign_id}/script-draft/{proposal_id}/keep-live"),
        ("POST", f"/v1/campaigns/{campaign_id}/script-draft/{proposal_id}/cancel"),
    ):
        response = await _http(other, method, path)
        assert response.status_code == 404, f"{method} {path}: {response.text}"
    async with tenant_session(other_tenant) as session:
        seen = (
            await session.execute(
                text("SELECT count(*) FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar_one()
    assert seen == 0
    row = await _row(tenant_id, campaign_id)
    assert row.script_proposal["status"] == "ready"


async def test_reconnecting_replays_where_the_draft_is(monkeypatch: pytest.MonkeyPatch) -> None:
    """FAILS IF: a browser that reconnects mid-write waits for the next move to learn the
    phase, or one that reconnects after ready gets no lines or diff."""
    tenant_id, campaign_id, token, proposal_id = await _written(monkeypatch)
    for _ in range(2):
        response = await _http(token, "GET", f"/v1/campaigns/{campaign_id}/script-draft/stream")
        assert response.status_code == 200, response.text
        frames = _frames(response.text)
        assert frames[0] == ("phase", {"phase": "ready", "detail": None})
        assert frames[-1][0] == "diff" and frames[-1][1]["proposal_id"] == str(proposal_id)
        assert any(name == "line" for name, _ in frames)
    # Mid-write: the stored phase is the first thing a new stream says.
    newer = await _request(tenant_id, campaign_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE campaigns SET script_proposal = script_proposal || "
                '\'{"phase": "checking"}\'::jsonb WHERE id = :c'
            ),
            {"c": campaign_id},
        )
    monkeypatch.setattr(script_draft, "MAX_S", 0.0)
    response = await _http(token, "GET", f"/v1/campaigns/{campaign_id}/script-draft/stream")
    assert _frames(response.text) == [("phase", {"phase": "checking", "detail": None})]
    assert newer != proposal_id


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
