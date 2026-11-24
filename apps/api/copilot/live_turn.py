"""One streamed model turn as the live view needs it: the plan line split out as a thought,
and the stream raced against Stop.

THE "THINKING" LINE IS PIP'S OWN ONE-LINE PLAN, NOT GEMINI'S THOUGHT SUMMARY, and the
reason is what Google publishes, not a preference:

* Pip answers on Gemini's OpenAI-compatible surface (`chat.ChatLeg`, dialect `google`).
  Google's compatibility page (ai.google.dev/gemini-api/docs/openai, now served from
  aistudio.google.com/docs/openai, read 24 Nov 2026) documents turning thought summaries on
  (`extra_body.google.thinking_config.include_thoughts`) but not how they come back: it
  names no field and no tag for them, streamed or not. The only account of the shape is a
  user's forum report (`<thought>` tags inside `content`, Gemini 2.5), REPORTED. Asking
  for thoughts in an unpublished shape risks them arriving as answer text.
* Pip's models are `gemini-3.1-flash-lite` and `gemini-3.5-flash-lite`
  (`engine.COPILOT_*_MODEL_DEFAULT`), whose thinking default is `minimal`
  (aistudio.google.com/docs/thinking, read 24 Nov 2026), and Google's own guide says a
  thought may carry a signature and no summary on simple requests. A developer reports
  `includeThoughts: true` returning no summary at all from `gemini-3.5-flash-lite` on
  `streamGenerateContent` (discuss.ai.google.dev topic 187725, 9 Oct 2026, unanswered).

So the founder's fallback (24 Nov 2026): the model states a one-line plan inside
`<plan>…</plan>` at the start of a turn (`prompt.PLAN_LINE_RULE`), and this module streams it
as `thought` frames and removes it from the answer. Only a plan at the START of a turn is a
plan; a stray tag elsewhere is dropped from the text. A plan ends at its closing tag, at a
line break, or at `MAX_PLAN_CHARS`, so a model that forgets to close it cannot pour its
answer into the Thinking line.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Final, Literal

from apps.api.copilot import run_control
from apps.api.copilot.sanitize import strip_invisible
from apps.workers import chat

OPEN_TAG: Final = "<plan>"
CLOSE_TAG: Final = "</plan>"
#: A plan is one short line. Past this it is not a plan, and the rest is answer text.
MAX_PLAN_CHARS: Final = 240
_STRAY_TAG: Final = re.compile(r"</?plan>", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class LiveFrame:
    """One piece of a turn: answer text, plan (thought) text, or the finished turn."""

    text: str | None = None
    thought: str | None = None
    outcome: chat.ChatOutcome | None = None


class PlanSplitter:
    """Splits a turn's streamed text into the leading plan and the answer."""

    def __init__(self) -> None:
        self._state: Literal["start", "plan", "text"] = "start"
        self._buffer = ""
        self._plan_chars = 0
        self._text: list[str] = []

    @property
    def text(self) -> str:
        """The answer text so far, plan removed."""
        return "".join(self._text)

    def feed(self, fragment: str) -> list[LiveFrame]:
        out: list[LiveFrame] = []
        self._buffer += fragment
        while self._buffer:
            if self._state == "start":
                head = self._buffer.lstrip()
                if not head:
                    return out
                if head.lower().startswith(OPEN_TAG):
                    self._buffer = head[len(OPEN_TAG) :]
                    self._state = "plan"
                    continue
                if OPEN_TAG.startswith(head.lower()):
                    return out  # could still become the opening tag
                self._state = "text"
                continue
            if self._state == "plan":
                frames, ended = self._plan_step()
                out.extend(frames)
                if not ended:
                    return out
                continue
            out.extend(self._emit_text(self._buffer))
            self._buffer = ""
        return out

    def finish(self) -> list[LiveFrame]:
        """End of the turn: whatever is held goes where it belongs."""
        held, self._buffer = self._buffer, ""
        if self._state == "plan":
            return self._emit_thought(held)
        if self._state == "start":
            return self._emit_text(held)
        return []

    def _plan_step(self) -> tuple[list[LiveFrame], bool]:
        """The plan's next piece, and whether the plan has ended."""
        lowered = self._buffer.lower()
        room = MAX_PLAN_CHARS - self._plan_chars
        ends = [i for i in (lowered.find(CLOSE_TAG), self._buffer.find("\n")) if i >= 0]
        if ends:
            cut = min(ends)
            rest = self._buffer[cut:]
            rest = rest[len(CLOSE_TAG) :] if rest.lower().startswith(CLOSE_TAG) else rest
            # A closed plan past the bound loses its tail: it is still plan, not answer.
            plan, self._buffer = self._buffer[: min(cut, room)], rest.lstrip()
            self._state = "text"
            return self._emit_thought(plan), True
        # Hold back what could be the start of the closing tag.
        keep = next(
            (n for n in range(len(CLOSE_TAG) - 1, 0, -1) if CLOSE_TAG.startswith(lowered[-n:])),
            0,
        )
        sendable = self._buffer[: len(self._buffer) - keep]
        if len(sendable) >= room:
            plan, self._buffer = self._buffer[:room], self._buffer[room:]
            self._state = "text"
            return self._emit_thought(plan), True
        self._buffer = self._buffer[len(sendable) :]
        return self._emit_thought(sendable), False

    def _emit_thought(self, piece: str) -> list[LiveFrame]:
        if self._plan_chars == 0:
            piece = piece.lstrip()
        cleaned = strip_invisible(piece)
        if not cleaned:
            return []
        self._plan_chars += len(cleaned)
        return [LiveFrame(thought=cleaned)]

    def _emit_text(self, piece: str) -> list[LiveFrame]:
        cleaned = _STRAY_TAG.sub("", piece)
        if not cleaned:
            return []
        self._text.append(cleaned)
        return [LiveFrame(text=cleaned)]


async def live_turn(frames: AsyncIterator[chat.StreamEvent]) -> AsyncIterator[LiveFrame]:
    """`frames` with the plan split out, and — inside a run that can be stopped — raced
    against Stop, so a model that is still thinking is cut off rather than waited for."""
    control = run_control.current()
    source = frames if control is None else _raced(frames, control)
    splitter = PlanSplitter()
    async for event in source:
        if event.text is not None:
            for frame in splitter.feed(event.text):
                yield frame
        if event.outcome is not None:
            for frame in splitter.finish():
                yield frame
            # The plan is not part of the answer: the claim check, the empty-answer check
            # and the replayed history all read `content`.
            yield LiveFrame(outcome=dataclasses.replace(event.outcome, content=splitter.text))


async def _raced(
    frames: AsyncIterator[chat.StreamEvent], control: run_control.RunControl
) -> AsyncIterator[chat.StreamEvent]:
    """Each frame, or `RunStoppedError` the moment Stop is pressed.

    ONE PUMP TASK READS THE WHOLE STREAM, rather than a task per frame, because the HTTP
    stream is a context manager entered by whichever task first reads it, and it must be
    left by that same task: cancelling the pump closes the connection to the model from the
    task that opened it, which stops the generation we would otherwise keep paying for."""
    control.check()
    queue: asyncio.Queue[tuple[Literal["frame", "end", "error"], object]] = asyncio.Queue()

    async def pump() -> None:
        try:
            async with contextlib.aclosing(frames):  # type: ignore[type-var]
                async for event in frames:
                    await queue.put(("frame", event))
            await queue.put(("end", None))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await queue.put(("error", exc))

    pumping = asyncio.create_task(pump())
    stopping = asyncio.create_task(control.wait())
    try:
        while True:
            getting = asyncio.create_task(queue.get())
            done, _ = await asyncio.wait({getting, stopping}, return_when=asyncio.FIRST_COMPLETED)
            if getting not in done:
                getting.cancel()
                raise run_control.RunStoppedError()
            kind, value = getting.result()
            if kind == "end":
                return
            if kind == "error":
                assert isinstance(value, BaseException)
                raise value
            control.check()
            assert isinstance(value, chat.StreamEvent)
            yield value
    finally:
        for task in (pumping, stopping):
            task.cancel()
        await asyncio.gather(pumping, stopping, return_exceptions=True)


__all__ = ["CLOSE_TAG", "MAX_PLAN_CHARS", "OPEN_TAG", "LiveFrame", "PlanSplitter", "live_turn"]
