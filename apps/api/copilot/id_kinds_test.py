"""An id in the wrong argument is something Pip fixes, not a dead end (founder, 24 Nov 2026).

The replay is the production run: the owner asked Pip to rewrite the Rytu Khata campaign's
script, the campaign was cancelled, and the model passed the campaign's id as `agent_id`.
`script_draft` answered "Agent not found", the run gave up, and the owner read "(Agent not
found)" and "Try asking for one thing at a time".
"""

from __future__ import annotations

import inspect
import json
import re
import uuid
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from tests.api_security_test import _make_tenant

from apps.api.copilot import id_kinds, script_actions, service, write_tools
from apps.api.copilot import tools as tools_module
from apps.api.copilot.actions import WriteRefusedError
from apps.api.copilot.schemas import CopilotAskIn
from apps.api.copilot.write_tools_test import _principal, _user_of
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.registry import TENANT_TABLES
from apps.api.db.session import tenant_session
from apps.workers import chat

ASKED = (
    "Rewrite the Rytu Khata campaign's script from scratch using our knowledge sources. "
    "Don't ask whether it's a good time again."
)


@pytest.fixture
def azure_only(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "azure_openai_resource", "calevate-test", raising=False)
    monkeypatch.setattr(settings, "azure_openai_api_key", "k", raising=False)
    monkeypatch.setattr(settings, "azure_openai_deployment", "dep", raising=False)
    monkeypatch.setattr(settings, "sarvam_api_key", None, raising=False)


@pytest.fixture(autouse=True)
def _allowance_open(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _open(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(script_actions, "require_ai_assist", _open)


async def _agent_of(tenant_id: UUID) -> UUID:
    async with tenant_session(tenant_id) as session:
        row = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).first()
    assert row is not None
    return UUID(str(row[0]))


async def _campaign(
    tenant_id: UUID, agent_id: UUID, *, status: str = "cancelled", archived: bool = False
) -> UUID:
    campaign_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, classification, "
                "main_task, status, archived_at) VALUES (:id, :t, :a, "
                "'RytuKhata - Existing Customers app usage', 'service', "
                "'Get existing customers using the app.', :s, "
                "CASE WHEN :arch THEN now() ELSE NULL END)"
            ),
            {"id": campaign_id, "t": tenant_id, "a": agent_id, "s": status, "arch": archived},
        )
    return campaign_id


def _turn(*, content: str = "", calls: tuple[chat.ToolCall, ...] = ()) -> list[Any]:
    return [
        *([chat.StreamEvent(text=content)] if content else []),
        chat.StreamEvent(
            outcome=chat.ChatOutcome(
                content=content,
                tool_calls=calls,
                finish_reason="tool_calls" if calls else "stop",
                usage=chat.TokenUsage(prompt_tokens=10, output_tokens=10),
            )
        ),
    ]


def _draft_call(index: int, **args: Any) -> list[Any]:
    body = {"agent_id": None, "holder_id": None, "instruction": ASKED, "tone": None, **args}
    return _turn(
        calls=(chat.ToolCall(id=f"c{index}", name="script_draft", arguments=json.dumps(body)),)
    )


def _scripted(monkeypatch: pytest.MonkeyPatch, turns: list[list[Any]]) -> list[list[Any]]:
    sent: list[list[Any]] = []
    remaining = list(turns)

    def _stream(leg: Any, messages: Any, **kwargs: Any) -> Any:
        sent.append([dict(message) for message in messages])
        events = remaining.pop(0) if remaining else _turn(content="Done.")

        async def _iterate() -> Any:
            for event in events:
                yield event

        return _iterate()

    monkeypatch.setattr(chat, "stream", _stream)
    return sent


def _ask() -> CopilotAskIn:
    return CopilotAskIn.model_validate(
        {
            "screen": {"route": "/c/x/campaigns", "title": "Campaigns", "realm": "client"},
            "question": ASKED,
            "fields": [],
        }
    )


async def _run(tenant_id: UUID, token: str) -> list[service.CopilotEvent]:
    principal = _principal(tenant_id, _user_of(token))
    return [event async for event in service.run_copilot(_ask(), principal=principal)]


def _said(events: list[service.CopilotEvent]) -> str:
    return "".join(event.text or "" for event in events)


def _shown(events: list[service.CopilotEvent]) -> list[str]:
    """Every string a person can read: the answer and each step's line."""
    return [_said(events)] + [e.step.detail or "" for e in events if e.step is not None]


# --- the replay -----------------------------------------------------------------------------


async def test_the_campaign_id_passed_as_agent_id_drafts_on_the_cancelled_campaign(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FAILS IF: a campaign's id in `agent_id` is refused as "Agent not found", or a
    cancelled campaign cannot take a draft."""
    tenant_id, _slug, token = await _make_tenant()
    campaign_id = await _campaign(tenant_id, await _agent_of(tenant_id))
    _scripted(monkeypatch, [_draft_call(1, agent_id=str(campaign_id))])

    events = await _run(tenant_id, token)

    (proposal,) = [e.proposal for e in events if e.proposal is not None]
    assert proposal.tool == "script_draft"
    assert "the campaign “RytuKhata - Existing Customers app usage”" in proposal.summary
    assert not [e.step for e in events if e.step and e.step.status in ("refused", "failed")]
    assert all(id_kinds.person_safe(line) for line in _shown(events))


async def test_a_not_found_the_model_caused_is_corrected_and_the_retry_proposes(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The generic half, for every action: a service's not-found for an id that names
    another kind of object goes back as what that id is, and the model's retry lands.

    FAILS IF: the loop reports such a not-found as final, the model is not told what the id
    names, or the person reads the raw title."""
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    campaign_id = await _campaign(tenant_id, agent_id)
    real_plan = write_tools.plan_write

    async def _plan(name: str, raw: str, **kwargs: Any) -> Any:
        # The production shape before `script_draft` resolved it itself: the service
        # under the tool raised a bare not-found for the campaign id in `agent_id`.
        if json.loads(raw).get("agent_id") == str(campaign_id):
            raise ProblemError.not_found("Agent")
        return await real_plan(name, raw, **kwargs)

    monkeypatch.setattr(write_tools, "plan_write", _plan)
    sent = _scripted(
        monkeypatch,
        [
            _draft_call(1, agent_id=str(campaign_id)),
            _draft_call(2, holder_id=str(campaign_id)),
        ],
    )

    events = await _run(tenant_id, token)

    told = [m for m in sent[1] if m.get("role") == "tool"][-1]["content"]
    assert "is the campaign “RytuKhata - Existing Customers app usage”" in told
    assert str(agent_id) in told
    assert "Do NOT call the tool again" not in told
    (proposal,) = [e.proposal for e in events if e.proposal is not None]
    assert proposal.tool == "script_draft"
    refused = [e.step for e in events if e.step and e.step.status == "refused"]
    assert [s.detail for s in refused] == [id_kinds.WRONG_ITEM_PLAIN]
    assert all(id_kinds.person_safe(line) for line in _shown(events))


async def test_a_not_found_that_never_gets_fixed_ends_in_plain_words(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FAILS IF: running out of turns shows "(Agent not found)", "one thing at a time", or
    says "Nothing was changed" twice (prod 0.5.32, 24 Nov 2026)."""
    tenant_id, _slug, token = await _make_tenant()
    campaign_id = await _campaign(tenant_id, await _agent_of(tenant_id))

    async def _plan(name: str, raw: str, **kwargs: Any) -> Any:
        raise ProblemError.not_found("Agent")

    monkeypatch.setattr(write_tools, "plan_write", _plan)
    _scripted(
        monkeypatch,
        [_draft_call(i, agent_id=str(campaign_id)) for i in range(service.MAX_TURNS + 1)],
    )

    events = await _run(tenant_id, token)

    said = _said(events)
    assert said == service.exhausted_text((id_kinds.WRONG_ITEM_PLAIN,), changed=False)
    assert "not found" not in said.lower() and "one thing at a time" not in said
    assert said.count("nothing was changed") + said.count("Nothing was changed") == 1
    assert all(id_kinds.person_safe(line) for line in _shown(events))


# --- script_draft reaches every holder the person can see ---------------------------------


async def _propose(tenant_id: UUID, token: str, args: dict[str, Any]) -> Any:
    return await write_tools.plan_write(
        "script_draft",
        json.dumps(args),
        actor=write_tools.actor_for(_principal(tenant_id, _user_of(token))),
    )


@pytest.mark.parametrize("status", ["draft", "paused", "completed", "cancelled"])
async def test_an_agents_only_campaign_takes_a_draft_whatever_its_status(status: str) -> None:
    """FAILS IF: the agent-only path lists only campaigns that can still run, so an agent
    whose one campaign is cancelled or completed is told it has none."""
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    campaign_id = await _campaign(tenant_id, agent_id, status=status)
    proposal = await _propose(tenant_id, token, {"agent_id": str(agent_id)})
    assert "RytuKhata" in proposal.summary
    assert proposal.object_id == str(agent_id)
    assert _signed_holder(proposal) == str(campaign_id)


def _signed_holder(proposal: Any) -> str:
    """The holder signed into the proposal's canonical arguments."""
    import jwt

    claims = jwt.decode(proposal.token, options={"verify_signature": False})
    return str(claims["args"]["holder_id"])


async def test_an_agent_id_as_holder_id_and_odd_ids_are_handled() -> None:
    """An agent's id in `holder_id` finds the agent's campaign; an archived campaign is
    refused in plain words; an id naming nothing is refused with what to do."""
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    await _campaign(tenant_id, agent_id)
    proposal = await _propose(tenant_id, token, {"holder_id": str(agent_id)})
    assert "RytuKhata" in proposal.summary

    archived = await _campaign(tenant_id, agent_id, archived=True)
    with pytest.raises(WriteRefusedError) as refused:
        await _propose(tenant_id, token, {"holder_id": str(archived)})
    assert "restore it first" in refused.value.reason
    assert refused.value.plain == "That campaign is archived. Restore it first."

    with pytest.raises(WriteRefusedError) as nothing:
        await _propose(tenant_id, token, {"agent_id": str(uuid.uuid4())})
    assert "names nothing in this account" in nothing.value.reason
    assert nothing.value.plain == id_kinds.WRONG_ITEM_PLAIN


# --- the resolver -------------------------------------------------------------------------


def test_every_kind_is_read_under_forced_rls() -> None:
    """FAILS IF: a kind is added on a table RLS does not scope, which would let an id from
    another account be described here."""
    assert {kind.table for kind in id_kinds.KINDS} <= set(TENANT_TABLES)
    # The statement reads exactly the catalogue's tables, under the catalogue's keys.
    sql = id_kinds._IDENTIFY_SQL
    assert set(re.findall(r"FROM (\w+)", sql)) == {kind.table for kind in id_kinds.KINDS}
    assert set(re.findall(r"SELECT '(\w+)'", sql)) == {kind.key for kind in id_kinds.KINDS}


async def test_the_resolver_names_what_an_id_is_and_never_a_neighbours() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    neighbour, _, _ = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    campaign_id = await _campaign(tenant_id, agent_id)
    theirs = await _campaign(neighbour, await _agent_of(neighbour))
    missing_agent = ProblemError.not_found("Agent")
    async with tenant_session(tenant_id) as session:
        found = await id_kinds.identify(session, campaign_id)
        assert found is not None and found.kind.key == "campaign"
        assert found.agent_id == agent_id
        assert await id_kinds.identify(session, theirs) is None

        fix = await id_kinds.correction_in(
            session, "script_draft", {"agent_id": str(campaign_id)}, missing_agent
        )
        assert fix is not None and "is the campaign" in fix and str(agent_id) in fix
        # A neighbour's campaign is "nothing" here, exactly as it is to the tool.
        fix = await id_kinds.correction_in(
            session, "script_draft", {"agent_id": str(theirs)}, missing_agent
        )
        assert fix is not None and "names nothing" in fix and "RytuKhata" not in fix
        # The agent is real, so the not-found is about something else: reported, not fixed.
        assert (
            await id_kinds.correction_in(session, "x", {"agent_id": str(agent_id)}, missing_agent)
            is None
        )
        # A kind this module cannot look up is never judged.
        assert (
            await id_kinds.correction_in(
                session, "x", {"line_id": str(campaign_id)}, ProblemError.not_found("Saved view")
            )
            is None
        )


async def test_a_read_tools_not_found_is_a_correction_too() -> None:
    """FAILS IF: a read tool's not-found for a misplaced id reaches the model as "could not
    be read just now", which reads as an outage and ends the run."""
    tenant_id, _slug, _token = await _make_tenant()
    campaign_id = await _campaign(tenant_id, await _agent_of(tenant_id))

    async def _raise(*_: Any) -> str:
        raise ProblemError.not_found("Agent")

    tool = tools_module.ReadTool(
        name="agent_settings",
        description="x",
        parameters={},
        permission="agents:read",
        run=_raise,
    )

    async def _read(agent_id: UUID) -> str:
        return await tools_module.run_read_tool(
            tool.name,
            json.dumps({"agent_id": str(agent_id)}),
            context=tools_module.ToolContext(tenant_id=tenant_id, role="owner"),
            registry={tool.name: tool},
        )

    told = await _read(campaign_id)
    assert "is the campaign" in told
    told = await _read(await _agent_of(tenant_id))
    assert told.startswith("Not read: Agent not found.")


# --- the guard: nothing raw reaches a person ----------------------------------------------

_PROBLEMS = [
    ProblemError.not_found("Agent"),
    ProblemError.not_found("Campaign"),
    ProblemError.not_found("Connect Google Sheets first."),
    ProblemError.not_found("phone_number"),
    ProblemError.conflict(
        "campaign_script_in_progress", "Pip is still writing this campaign's script."
    ),
    ProblemError.forbidden(),
    ProblemError(
        kind="validation",
        code="script_part_request_invalid",
        title="Bad",
        detail="`agent_id` is required",
    ),
    ProblemError(
        kind="dependency",
        code="copilot_interrupted",
        title="Oops",
        detail=f"row {uuid.uuid4()} broke",
    ),
]


@pytest.mark.parametrize("problem", _PROBLEMS, ids=lambda p: p.title)
def test_no_platform_refusal_reaches_a_person_raw(problem: ProblemError) -> None:
    """FAILS IF: what a person reads of a tool's `ProblemError` (the step's line, and the
    closing sentence when the run gives up) is its raw title, names an id or our
    machinery, or is the generic advice that fits no cause."""
    plain = id_kinds.problem_plain(problem)
    assert plain != problem.title
    assert id_kinds.person_safe(plain), plain
    closing = service.exhausted_text((plain,), changed=False)
    assert id_kinds.person_safe(closing) and "one thing at a time" not in closing


def test_the_loop_never_shows_a_problem_title() -> None:
    """FAILS IF: an arm of the loop that catches a tool's `ProblemError` puts its title (or
    its unvetted detail) on a step or in the closing reason instead of going through
    `_tool_problem`, which corrects a model-caused not-found and words the rest plainly."""
    source = inspect.getsource(service._run_tool_loop)
    arms = re.split(r"except ProblemError as problem:", source)[1:]
    assert arms, "the loop no longer catches a tool's ProblemError"
    for arm in arms:
        body = arm.split("continue", 1)[0]
        assert "_tool_problem(" in body
        assert "refusal_reasons = (problem." not in body
        assert "detail=problem." not in body
