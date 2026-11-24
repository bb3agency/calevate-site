"""The Pip loop's half of the live working view: the Thinking line, step results, Stop.

The provider is replaced at `chat.stream` (`loop_test`'s seam), so the loop, the plan
splitter, the race against Stop and the step frames are the real ones.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator, Sequence
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.copilot import live_turn, run_control, service, step_results
from apps.api.copilot import tools as tools_module
from apps.api.copilot.live_turn import MAX_PLAN_CHARS, PlanSplitter
from apps.api.copilot.loop_test import PAYLOAD, TOOL_CONTEXT, _scripted, _tool_turn, _turn
from apps.api.copilot.prompt import PLAN_LINE_RULE
from apps.api.copilot.sanitize import has_invisible
from apps.api.core.settings import get_settings
from apps.workers import chat

SENTINEL = "Checking the zebra-quartz campaigns"


@pytest.fixture
def azure_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """`loop_test.azure_only`: the top rung of the ladder and no standby."""
    settings = get_settings()
    monkeypatch.setattr(settings, "azure_openai_resource", "calevate-test", raising=False)
    monkeypatch.setattr(settings, "azure_openai_api_key", "k", raising=False)
    monkeypatch.setattr(settings, "azure_openai_deployment", "dep", raising=False)
    monkeypatch.setattr(settings, "sarvam_api_key", None, raising=False)


def _control(owner: str = "client:t:u") -> run_control.RunControl:
    return run_control.RunControl(owner=owner, run_id=uuid.uuid4(), tenant_id=uuid.uuid4())


def _kind(event: service.CopilotEvent) -> str:
    for name in ("thought", "step", "text", "draft", "spend", "fill", "action", "chart"):
        if getattr(event, name) is not None:
            return name
    return "other"


def _split(fragments: Sequence[str]) -> tuple[str, str]:
    splitter = PlanSplitter()
    frames = [frame for fragment in fragments for frame in splitter.feed(fragment)]
    frames += splitter.finish()
    thought = "".join(frame.thought or "" for frame in frames)
    text = "".join(frame.text or "" for frame in frames)
    assert text == splitter.text
    return thought, text


# --- the plan line ---------------------------------------------------------------------


def test_the_plan_is_split_out_even_when_its_tags_arrive_in_pieces() -> None:
    thought, text = _split(["<pl", "an>Reading your ", "campaigns.</pl", "an> You have two."])
    assert thought == "Reading your campaigns."
    assert text == "You have two."


def test_a_turn_without_a_plan_is_all_answer_and_stray_tags_are_dropped() -> None:
    thought, text = _split(["Hello <plan>there", "</plan> again."])
    assert thought == ""
    assert text == "Hello there again."


def test_an_unclosed_plan_ends_at_the_line_break() -> None:
    thought, text = _split(["<plan>Looking it up\nThe answer is nine."])
    assert thought == "Looking it up"
    assert text == "The answer is nine."


def test_a_plan_that_never_ends_cannot_swallow_the_answer() -> None:
    thought, text = _split(["<plan>", "a" * 1000])
    assert len(thought) == MAX_PLAN_CHARS
    assert text == "a" * (1000 - MAX_PLAN_CHARS)


def test_the_plan_is_stripped_of_invisible_characters() -> None:
    thought, _ = _split(["<plan>Read​ing\U000e0041</plan>"])
    assert thought == "Reading"


def test_the_prompt_asks_for_the_tags_the_splitter_reads() -> None:
    assert live_turn.OPEN_TAG in PLAN_LINE_RULE
    assert live_turn.CLOSE_TAG in PLAN_LINE_RULE


# --- events, in order --------------------------------------------------------------------


async def test_a_lookup_answer_streams_thought_then_steps_then_text_then_spend(
    azure_only: None, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    sent = _scripted(
        monkeypatch,
        [
            _tool_turn(("campaigns_list", "{}"), content=f"<plan>{SENTINEL}.</plan>"),
            _turn(content="You have twelve."),
        ],
    )

    async def _run(name: str, arguments: str, *, context: Any, registry: Any = None) -> str:
        step_results.offer(
            [
                step_results.ResultRow(
                    title=f"Camp​aign {n} " + "x" * 300,
                    subtitle="paused\U000e0041",
                    href=f"/c/{{slug}}/campaigns/{uuid.uuid4()}" if n else "https://evil.test/x",
                )
                for n in range(12)
            ],
            total=12,
        )
        return "Twelve campaigns."

    monkeypatch.setattr(tools_module, "run_read_tool", _run)
    caplog.set_level(logging.DEBUG)

    events = [e async for e in service.run_copilot(PAYLOAD, tool_context=TOOL_CONTEXT)]

    kinds = [_kind(e) for e in events]
    assert kinds == ["thought", "step", "step", "text", "spend"]
    assert events[0].thought is not None
    assert (events[0].thought.delta, events[0].thought.turn) == (f"{SENTINEL}.", 0)
    running, done = events[1].step, events[2].step
    assert running is not None and running.status == "running" and running.results is None
    assert done is not None and done.status == "done"
    results = done.results
    assert results is not None and results.kind == "list" and results.total == 12
    assert len(results.items) == step_results.MAX_ITEMS
    for item in results.items:
        assert not has_invisible(item.title) and len(item.title) <= step_results.MAX_TITLE_CHARS
        assert item.subtitle == "paused"
    # Only a client route template survives as a link.
    assert results.items[0].href is None
    assert all(item.href and item.href.startswith("/c/{slug}/") for item in results.items[1:])
    # The plan is not the answer, and never reaches the model's history or a log line.
    assert "".join(e.text or "" for e in events) == "You have twelve."
    assert all(SENTINEL not in json.dumps(message) for message in sent[1])
    assert SENTINEL not in caplog.text


async def test_the_admin_realm_gets_the_rows_without_client_links(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _scripted(monkeypatch, [_tool_turn(("agents_list", "{}")), _turn(content="Two.")])

    async def _run(name: str, arguments: str, *, context: Any, registry: Any = None) -> str:
        step_results.offer(
            [step_results.ResultRow(title="Reception", href="/c/{slug}/agents/a")], total=1
        )
        return "One agent."

    monkeypatch.setattr(tools_module, "run_read_tool", _run)
    events = [
        e async for e in service.run_copilot(PAYLOAD, tool_context=TOOL_CONTEXT, realm="admin")
    ]
    done = [e.step for e in events if e.step is not None and e.step.status == "done"]
    assert done and done[0].results is not None
    assert [item.href for item in done[0].results.items] == [None]


async def test_a_plan_that_names_a_vendor_never_reaches_the_thinking_line(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _scripted(
        monkeypatch,
        [
            _tool_turn(("leads_search", "{}"), content="<plan>I am OpenAI's GPT, checking.</plan>"),
            _turn(content="Done."),
        ],
    )

    async def _run(name: str, arguments: str, *, context: Any, registry: Any = None) -> str:
        return "No leads."

    monkeypatch.setattr(tools_module, "run_read_tool", _run)
    events = [e async for e in service.run_copilot(PAYLOAD, tool_context=TOOL_CONTEXT)]
    assert all(e.thought is None for e in events)


async def test_a_draft_the_run_started_is_announced_after_the_event_that_started_it(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    holder, proposal = uuid.uuid4(), uuid.uuid4()
    _scripted(monkeypatch, [_tool_turn(("campaigns_list", "{}")), _turn(content="Writing.")])

    async def _run(name: str, arguments: str, *, context: Any, registry: Any = None) -> str:
        # Stands in for the writer's own call when it queues a draft inside a run.
        run_control.note_draft_started(
            holder_kind="campaign", holder_id=holder, proposal_id=proposal
        )
        return "ok"

    monkeypatch.setattr(tools_module, "run_read_tool", _run)
    control = _control()
    events = [
        e async for e in service.run_copilot(PAYLOAD, tool_context=TOOL_CONTEXT, control=control)
    ]
    kinds = [_kind(e) for e in events]
    assert kinds == ["step", "step", "draft", "text", "spend"]
    draft = events[2].draft
    assert draft is not None
    assert (draft.holder_kind, draft.holder_id, draft.proposal_id) == (
        "campaign",
        holder,
        proposal,
    )
    assert control.drafts == (run_control.StartedDraft("campaign", holder, proposal),)
    # Outside a run the seam does nothing.
    run_control.note_draft_started(holder_kind="campaign", holder_id=holder, proposal_id=proposal)
    assert len(control.drafts) == 1


# --- Stop --------------------------------------------------------------------------------


async def test_stop_during_a_lookup_halts_the_loop_and_nothing_after_it_runs(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    control = _control()
    sent = _scripted(
        monkeypatch,
        [
            _tool_turn(("calls_recent", "{}")),
            _tool_turn(("leads_search", "{}")),
            _turn(content="Never said."),
        ],
    )
    ran: list[str] = []

    async def _run(name: str, arguments: str, *, context: Any, registry: Any = None) -> str:
        ran.append(name)
        control.stop()  # the person presses Stop while this lookup runs
        return "Three calls."

    monkeypatch.setattr(tools_module, "run_read_tool", _run)
    events: list[service.CopilotEvent] = []
    with pytest.raises(service.RunStoppedError):
        async for event in service.run_copilot(PAYLOAD, tool_context=TOOL_CONTEXT, control=control):
            events.append(event)

    assert ran == ["calls_recent"]
    assert len(sent) == 1, "no model turn may start after Stop"
    assert [_kind(e) for e in events] == ["step", "step"]
    assert all(e.text is None and e.spend is None for e in events)


async def test_stop_cuts_off_a_model_that_is_still_thinking(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    control = _control()
    closed = asyncio.Event()

    def _stream(leg: chat.ChatLeg, messages: Sequence[Any], **kwargs: Any) -> Any:
        async def _iterate() -> AsyncIterator[chat.StreamEvent]:
            try:
                yield chat.StreamEvent(text="<plan>Thinking hard.</plan>")
                await asyncio.sleep(3600)  # a silent model
                yield chat.StreamEvent(text="never")
            finally:
                closed.set()

        return _iterate()

    monkeypatch.setattr(chat, "stream", _stream)
    events: list[service.CopilotEvent] = []

    async def _consume() -> None:
        async for event in service.run_copilot(PAYLOAD, control=control):
            events.append(event)
            control.stop()

    async with asyncio.timeout(5):
        with pytest.raises(service.RunStoppedError):
            await _consume()
        # The connection to the model was closed, not left generating.
        await closed.wait()
    assert [_kind(e) for e in events] == ["thought"]


async def test_a_run_without_a_control_cannot_be_stopped_and_is_unchanged(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _scripted(monkeypatch, [_turn(content="Nine.")])
    events = [e async for e in service.run_copilot(PAYLOAD)]
    assert [_kind(e) for e in events] == ["text", "spend"]
    assert run_control.current() is None


# --- who may stop a run ------------------------------------------------------------------


async def test_another_persons_stop_does_nothing_and_the_owners_stops_it() -> None:
    control = _control(owner="client:acct:alice")
    async with control:
        # Through Redis, as from another api process.
        run_control._LOCAL.pop(control.run_id)
        await run_control.request_stop(control.run_id, owner="client:acct:mallory")
        await asyncio.sleep(run_control.STOP_POLL_S * 3)
        assert not control.stopped
        await run_control.request_stop(control.run_id, owner="client:acct:alice")
        async with asyncio.timeout(run_control.STOP_POLL_S * 8):
            await control.wait()
    assert control.stopped


async def test_a_stop_in_the_same_process_lands_at_once_and_only_for_the_owner() -> None:
    control = _control(owner="admin:-:op1")
    async with control:
        await run_control.request_stop(control.run_id, owner="admin:-:op2")
        assert not control.stopped
        await run_control.request_stop(control.run_id, owner="admin:-:op1")
        assert control.stopped


async def test_a_finished_run_cannot_be_stopped() -> None:
    control = _control()
    async with control:
        pass
    await run_control.request_stop(control.run_id, owner=control.owner)
    assert not control.stopped


async def test_stop_cancels_every_draft_the_run_started_even_when_one_fails() -> None:
    cancelled: list[uuid.UUID] = []
    scoped: list[str] = []
    first, second = uuid.uuid4(), uuid.uuid4()

    # The shape of the script writer's `cancel_draft(session, *, tenant_id, holder_kind,
    # holder_id, proposal_id) -> bool`: handed a session already scoped to the run's tenant.
    async def _cancel(
        session: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        holder_kind: run_control.HolderKind,
        holder_id: uuid.UUID,
        proposal_id: uuid.UUID,
    ) -> bool:
        guc = await session.execute(text("SELECT current_setting('app.tenant_id', true)"))
        scoped.append(guc.scalar_one())
        cancelled.append(proposal_id)
        if proposal_id == first:
            raise RuntimeError("already gone")
        return True

    control = _control()
    control.note_draft(run_control.StartedDraft("campaign", uuid.uuid4(), first))
    control.note_draft(run_control.StartedDraft("inbound_line", uuid.uuid4(), second))
    registered = run_control.draft_canceller()
    run_control.register_draft_canceller(_cancel)
    try:
        await control.cancel_drafts()
    finally:
        run_control.register_draft_canceller(registered)
    assert cancelled == [first, second]
    assert scoped == [str(control.tenant_id)] * 2


def test_the_stop_keys_outlive_the_whole_run() -> None:
    assert run_control.RUN_TTL_S > service.TOTAL_BUDGET_S + 30
