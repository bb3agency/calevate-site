"""What the agent says and does when the conversation stalls: a quiet caller or a failing vendor.

Two failure shapes end a phone call in dead air unless something outside the model acts:

* **The caller goes quiet.** Nothing in the pipeline ends a call nobody is speaking on
  (`assemble_call` sets `idle_timeout_secs=None`, because Pipecat's idle timeout CANCELS the
  worker and the runner with it). The established practice is one reminder after about ten
  seconds of silence following the agent's speech, then a polite end: Retell's agent API
  defaults `reminder_trigger_ms` to 10000 and `reminder_max_count` to 1
  (docs.retellai.com/api-references/create-agent, read 6 Oct 2026). Pipecat ships the timer:
  `LLMUserAggregatorParams.user_idle_timeout` and the aggregator's `on_user_turn_idle` event,
  armed on `BotStoppedSpeakingFrame` and suppressed while the caller is mid-turn or a tool
  call is running (`pipecat/turns/user_idle_controller.py`). `CallerIdleHandler` is what
  answers that event.
* **A vendor leg fails.** A transient LLM, STT or TTS error ends the turn with nothing said,
  and a permanent one ends the call (`ProcessorUnusablePolicy.END`) with a click.
  `VendorFaultResponder` makes both audible: a short apology and a request to repeat on the
  first transient failure, and an apology and a clean end on a second consecutive one or on
  any permanent failure of a leg other than the voice. When the voice itself is the dead leg
  nothing can be said, and the existing END policy hangs up.

WHY THE WORDS ARE FIXED AND NOT THE MODEL'S. Every sentence here is spoken when the model
cannot be trusted to produce one: it may be the leg that failed, or the call is ending on our
clock rather than the conversation's. So they are spoken with `TTSSpeakFrame`, in the agent's
PRIMARY language because that is the language its voice is configured for
(`pipeline._build_tts`), with English where no row exists, the same rule
`output_guard.DECLINES` follows. `append_to_context=True` so the model, if the call goes on,
knows what was said, and so the transcript records it.

Everything here changes the running pipeline by queueing frames on the worker
(`AGENTS.md:151`). Hard rule 6: log lines carry ids, a leg name, a category word and counts.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal, Protocol

from loguru import logger
from pipecat.frames.frames import EndWorkerFrame, ErrorFrame, Frame, TTSSpeakFrame
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.utils.errors import ErrorCategory

PhraseKind = Literal["idle_reprompt", "idle_goodbye", "cap_goodbye", "fault_retry", "fault_goodbye"]

#: The fixed sentences, by primary-language subtag. Neutral in register and grammatical
#: gender (the Hindi rows use passive or imperative forms for that reason). The Telugu and
#: Hindi rows want a native speaker's read before client traffic, as `DECLINES` does.
PHRASES: Final[Mapping[PhraseKind, Mapping[str, str]]] = {
    "idle_reprompt": {
        "en": "Hello, are you still there?",
        "te": "హలో, మీరు లైన్‌లో ఉన్నారా?",
        "hi": "हैलो, क्या आप लाइन पर हैं?",
    },
    "idle_goodbye": {
        "en": "I can't hear anything, so I'll end the call now. Please call again. Thank you.",
        "te": ("మీ నుండి ఏమీ వినిపించడం లేదు, కాబట్టి ఇప్పుడు కాల్ ముగిస్తున్నాను. దయచేసి మళ్ళీ కాల్ చేయండి. ధన్యవాదాలు."),
        "hi": (
            "आपकी आवाज़ नहीं आ रही है, इसलिए यह कॉल अब समाप्त की जा रही है। कृपया दोबारा कॉल करें। धन्यवाद।"
        ),
    },
    "cap_goodbye": {
        "en": (
            "We've reached the time limit for this call, so I'll end it here. "
            "Please call again if you need anything else. Thank you."
        ),
        "te": (
            "ఈ కాల్ సమయ పరిమితి పూర్తయింది, కాబట్టి ఇప్పుడు కాల్ ముగిస్తున్నాను. "
            "ఇంకేమైనా అవసరమైతే దయచేసి మళ్ళీ కాల్ చేయండి. ధన్యవాదాలు."
        ),
        "hi": (
            "इस कॉल की समय सीमा पूरी हो गई है, इसलिए यह कॉल अब समाप्त की जा रही है। "
            "कुछ और चाहिए तो कृपया दोबारा कॉल करें। धन्यवाद।"
        ),
    },
    "fault_retry": {
        "en": "Sorry, I didn't catch that. Could you say it again?",
        "te": "క్షమించండి, నాకు సరిగ్గా వినిపించలేదు. దయచేసి మళ్ళీ చెప్పగలరా?",
        "hi": "माफ़ कीजिए, ठीक से सुनाई नहीं दिया। कृपया फिर से बताइए।",
    },
    "fault_goodbye": {
        "en": (
            "Sorry, we're having a technical problem. "
            "Please call again in a little while. Thank you."
        ),
        "te": ("క్షమించండి, మాకు సాంకేతిక సమస్య వస్తోంది. దయచేసి కొద్దిసేపటి తర్వాత మళ్ళీ కాల్ చేయండి. ధన్యవాదాలు."),
        "hi": ("माफ़ कीजिए, अभी तकनीकी समस्या आ रही है। कृपया थोड़ी देर बाद दोबारा कॉल करें। धन्यवाद।"),
    },
}

#: Every fixed sentence, in every language. A turn whose text is one of these is ours, not
#: evidence that the model answered.
_CANNED: Final[frozenset[str]] = frozenset(
    text for by_language in PHRASES.values() for text in by_language.values()
)


def phrase_for(kind: PhraseKind, language: str | None) -> str:
    """The sentence in the agent's primary language, English when there is no row for it."""
    subtag = (language or "en").split("-")[0].lower()
    rows = PHRASES[kind]
    return rows.get(subtag, rows["en"])


def is_canned(text: str) -> bool:
    """Whether `text` is one of this module's fixed sentences."""
    return text.strip() in _CANNED


#: Seconds of caller silence after the agent stops speaking before the reminder (Retell's
#: default, cited above). Ten rather than less because a caller looking for a booking
#: reference or asking someone in the room is not gone.
CALLER_IDLE_TIMEOUT_S: Final[float] = 10.0

#: Reminders before the polite end. One, as Retell's default: a second "are you there"
#: to an empty line costs the client another ten seconds of every leg.
CALLER_IDLE_REPROMPTS: Final[int] = 1

#: Consecutive failed turns before the call is ended with an apology. The first gets a
#: "could you say that again", which also retries the turn through the caller; a second in a
#: row means the leg is down, and a third apology would be dead air with words in it.
FAULT_APOLOGY_LIMIT: Final[int] = 2

#: Errors closer together than this count once. A websocket that dies mid-sentence reports
#: from its receive loop and its reconnect in the same instant, and that is one failed turn.
FAULT_DEBOUNCE_S: Final[float] = 2.0


@dataclass(frozen=True, slots=True)
class IdleCallerPolicy:
    """How long a silence is, and how many reminders before the goodbye. 0 disables."""

    timeout_s: float = CALLER_IDLE_TIMEOUT_S
    reprompts: int = CALLER_IDLE_REPROMPTS

    @property
    def enabled(self) -> bool:
        return self.timeout_s > 0


class FrameQueue(Protocol):
    """The one `PipelineWorker` method this module uses."""

    async def queue_frames(self, frames: Any) -> None: ...


class EventSource(Protocol):
    """Anything that takes Pipecat event handlers: an aggregator or a processor."""

    def add_event_handler(self, event_name: str, handler: Any) -> None: ...


class CallerIdleHandler:
    """Answers the user aggregator's `on_user_turn_idle`: remind, then end politely."""

    def __init__(
        self,
        *,
        worker: FrameQueue,
        policy: IdleCallerPolicy,
        language: str | None,
        call_id: str,
    ) -> None:
        self._worker = worker
        self._policy = policy
        self._language = language
        self._call_id = call_id
        self._idle_count = 0
        self._ending = False

    @property
    def reminders_given(self) -> int:
        return min(self._idle_count, self._policy.reprompts)

    @property
    def ended_call(self) -> bool:
        return self._ending

    def attach(self, user_aggregator: EventSource) -> None:
        user_aggregator.add_event_handler("on_user_turn_idle", self._on_idle)
        user_aggregator.add_event_handler("on_user_turn_started", self._on_caller_spoke)

    async def _on_caller_spoke(self, *_args: Any) -> None:
        self._idle_count = 0

    async def _on_idle(self, *_args: Any) -> None:
        if self._ending:
            return
        self._idle_count += 1
        if self._idle_count <= self._policy.reprompts:
            logger.info(
                "caller silent; reminding", call_id=self._call_id, reminder=self._idle_count
            )
            await self._worker.queue_frames(
                [TTSSpeakFrame(text=phrase_for("idle_reprompt", self._language))]
            )
            return
        self._ending = True
        logger.info("caller silent after reminder; ending the call", call_id=self._call_id)
        await self._worker.queue_frames(
            [
                TTSSpeakFrame(text=phrase_for("idle_goodbye", self._language)),
                EndWorkerFrame(reason="the caller stayed silent"),
            ]
        )


class VendorFaultResponder:
    """Turns a vendor error into words the caller hears, then a clean end if it persists.

    REGISTERED ON EACH LEG'S OWN `on_error`, NOT ON THE WORKER'S `on_pipeline_error`, and the
    ordering is the reason. The worker's event runs its handlers as tasks and applies the
    unusable-processor policy in the same breath (`pipecat/pipeline/worker.py`, the
    `ErrorFrame` branch of the upstream handler), so an apology queued from there lands
    after the policy's `EndFrame` and is dropped. A processor's `on_error` is registered
    `sync=True` and runs inside `push_error_frame` after the usable verdict is set and before
    the `ErrorFrame` travels (`pipecat/processors/frame_processor.py`), so frames queued here
    precede the policy's `EndFrame` and are spoken before the line closes.
    """

    def __init__(
        self,
        *,
        worker: FrameQueue,
        voice: FrameProcessor,
        language: str | None,
        call_id: str,
        mark_failed: Callable[[], None],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._worker = worker
        self._voice = voice
        self._language = language
        self._call_id = call_id
        self._mark_failed = mark_failed
        self._clock = clock
        self._consecutive = 0
        self._last_counted: float | None = None
        self._ending = False

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive

    @property
    def ended_call(self) -> bool:
        return self._ending

    def attach(self, legs: Mapping[str, EventSource], assistant_aggregator: EventSource) -> None:
        """`legs` by name (`stt`, `llm`, `tts`); the name is what the log line carries."""
        for name, processor in legs.items():
            processor.add_event_handler("on_error", self._handler_for(name))
        assistant_aggregator.add_event_handler("on_assistant_turn_stopped", self._on_assistant)

    def _handler_for(self, leg: str) -> Callable[[Any, ErrorFrame], Any]:
        async def _on_error(processor: Any, error: ErrorFrame) -> None:
            await self.on_leg_error(leg, processor, error)

        return _on_error

    async def _on_assistant(self, _aggregator: Any, message: Any) -> None:
        content = getattr(message, "content", None)
        if content and not is_canned(content):
            self._consecutive = 0

    async def on_leg_error(self, leg: str, processor: Any, error: ErrorFrame) -> None:
        if self._ending:
            return
        # A tool handler's failure says nothing about the vendor (`ErrorCategory.APPLICATION`),
        # and the model already gets "the function failed" to talk around.
        if error.category is ErrorCategory.APPLICATION:
            return
        permanent = bool(getattr(error, "fatal", False)) or not getattr(
            processor, "is_usable", True
        )
        category = error.category.value if error.category is not None else "unknown"
        if permanent:
            await self._end(leg, category, permanent=True)
            return
        now = self._clock()
        if self._last_counted is not None and now - self._last_counted < FAULT_DEBOUNCE_S:
            return
        self._last_counted = now
        self._consecutive += 1
        if self._consecutive >= FAULT_APOLOGY_LIMIT:
            await self._end(leg, category, permanent=False)
            return
        logger.warning(
            "vendor leg failed a turn; apologising",
            call_id=self._call_id,
            leg=leg,
            category=category,
            consecutive=self._consecutive,
        )
        if self._voice_usable():
            await self._worker.queue_frames(
                [TTSSpeakFrame(text=phrase_for("fault_retry", self._language))]
            )

    def _voice_usable(self) -> bool:
        return bool(getattr(self._voice, "is_usable", True))

    async def _end(self, leg: str, category: str, *, permanent: bool) -> None:
        self._ending = True
        self._mark_failed()
        logger.error(
            "vendor leg failed; ending the call",
            call_id=self._call_id,
            leg=leg,
            category=category,
            permanent=permanent,
            consecutive=self._consecutive,
        )
        frames: list[Frame] = []
        if self._voice_usable():
            frames.append(TTSSpeakFrame(text=phrase_for("fault_goodbye", self._language)))
        # A permanent failure is ended by the worker's END policy right behind these frames;
        # a run of transient ones has nobody else to end it.
        if not permanent:
            frames.append(EndWorkerFrame(reason=f"the {leg} leg kept failing"))
        if frames:
            await self._worker.queue_frames(frames)


__all__ = [
    "CALLER_IDLE_REPROMPTS",
    "CALLER_IDLE_TIMEOUT_S",
    "FAULT_APOLOGY_LIMIT",
    "FAULT_DEBOUNCE_S",
    "PHRASES",
    "CallerIdleHandler",
    "IdleCallerPolicy",
    "PhraseKind",
    "VendorFaultResponder",
    "is_canned",
    "phrase_for",
]
