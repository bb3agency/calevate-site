"""What a publish of one config sends the engine, in our terms, for the admin console.

The adapter's own body builders render it (`ThinnestEngine._agent_body`, `_steps_body`,
`built_in_tools_body`), so the screen cannot drift from the wire; this module turns their
vendor shapes into a normalized view (hard rule 2: nothing outside `engine/` sees them). An
engine with no builders here gets the view our config itself states.

`publish_digest` is the digest the publish path stores on the engine agent's route
(`engine_agent_routes.published_digest`) and the screen compares with a digest of what it
would send now. It covers every request a publish makes from the config: the agent body, the
built-in tools, the own-key voice and model, and the during-call actions.

Admin only. The view carries the client's greeting, steps and filler lines; never the
hand-over phone number, which the tools body holds and this view leaves out (hard rule 6).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from calevate_shared.engine import (
    AgentConfig,
    VoiceEngine,
    call_instructions,
    compose_engine_prompt,
    compose_first_utterance,
    sends_our_call_rules,
)

from apps.api.engine.thinnest import (
    CALL_INSTRUCTIONS_FIELD,
    KNOWLEDGE_ON_CALLS_FIELD,
    ThinnestEngine,
    _steps_body,
)


@dataclass(frozen=True, slots=True)
class SentStep:
    title: str
    detail: str
    #: (when, what the agent does) pairs.
    branches: tuple[tuple[str, str], ...]
    collect: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SentSetting:
    key: str
    label: str
    value: str


@dataclass(frozen=True, slots=True)
class SentTool:
    key: str
    label: str
    on: bool


@dataclass(frozen=True, slots=True)
class PublishDigest:
    """sha256 of the canonical publish payload (lower-case hex) and its sizes."""

    sha256: str
    instructions_chars: int
    greeting_chars: int
    payload_bytes: int


@dataclass(frozen=True, slots=True)
class PublishView:
    greeting: str
    steps: tuple[SentStep, ...]
    settings: tuple[SentSetting, ...]
    thinking_lines: tuple[str, ...]
    built_in_tools: tuple[SentTool, ...]
    #: The client's during-call actions by name (`AgentConfig.action_tools`).
    custom_actions: tuple[str, ...]
    digest: PublishDigest


#: Owner-readable names for ThinnestAI's built-in tools (`built_in_tools_body`).
_TOOL_LABELS: Final[dict[str, str]] = {
    "call_them_now": "Call the person back now",
    "send_sms": "Send an SMS",
    "send_whatsapp": "Send a WhatsApp message",
    "reply_by_email": "Reply by email",
    "capture_lead": "The platform's own lead capture",
    "schedule_callback": "The platform's own call-back",
    "escalate_to_human": "Hand over to a person",
    KNOWLEDGE_ON_CALLS_FIELD: "Search knowledge during calls",
}


def _text(value: Any) -> str:
    if value is None:
        return "not sent (the platform's default)"
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _seconds(ms: int | None) -> str:
    return "never" if ms is None else f"{ms / 1000:g} s"


def _canonical(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    ).encode()


def _digest(payload: Mapping[str, Any], *, instructions: str, greeting: str) -> PublishDigest:
    raw = _canonical(payload)
    return PublishDigest(
        sha256=hashlib.sha256(raw).hexdigest(),
        instructions_chars=len(instructions),
        greeting_chars=len(greeting),
        payload_bytes=len(raw),
    )


def _steps(rendered: Sequence[Mapping[str, Any]]) -> tuple[SentStep, ...]:
    return tuple(
        SentStep(
            title=str(step.get("title") or ""),
            detail=str(step.get("detail") or ""),
            branches=tuple(
                (str(b.get("when") or ""), str(b.get("action") or ""))
                for b in step.get("branches") or ()
            ),
            collect=tuple(str(c) for c in step.get("collect") or ()),
        )
        for step in rendered
    )


def _actions(cfg: AgentConfig) -> tuple[str, ...]:
    return tuple(tool.name for tool in cfg.action_tools)


def _own_key_payload(cfg: AgentConfig) -> dict[str, Any]:
    """The own-key voice and model requests a publish makes after the agent write."""
    tuning = cfg.engine_byok_voice_tuning
    return {
        "byokVoice": cfg.engine_byok_voice_id,
        "byokVoiceTuning": tuning.model_dump(mode="json") if tuning is not None else None,
        "ownModel": cfg.engine_own_model,
        "actions": [tool.model_dump(mode="json") for tool in cfg.action_tools],
    }


def _thinnest_view(engine: ThinnestEngine, cfg: AgentConfig) -> PublishView:
    body = engine._agent_body(cfg)
    tools = ThinnestEngine.built_in_tools_body(cfg)
    voice: dict[str, Any] = body["voice"]
    turn = str(voice.get("turnDetection"))
    if "turnSilenceSeconds" in voice:
        turn = f"{turn}, turn ends after {_text(voice['turnSilenceSeconds'])} s of quiet"
    rules = voice.get(CALL_INSTRUCTIONS_FIELD)
    spoken_voice = (
        f"platform voice {voice['voice']}"
        if voice.get("voice")
        else f"our own voice key, voice {cfg.engine_byok_voice_id}"
        if cfg.engine_byok_voice_id
        else "none chosen"
    )
    settings = (
        SentSetting("languages", "Languages", ", ".join(body["languages"]) or "auto"),
        SentSetting("voice", "Voice", spoken_voice),
        SentSetting("byok", "Whose keys it runs on", str(body["byok"])),
        SentSetting(
            "model",
            "Language model",
            f"our model {cfg.engine_own_model}"
            if cfg.engine_own_model
            else _text(body.get("model")),
        ),
        SentSetting("temperature", "Temperature", _text(body["temperature"])),
        SentSetting("max_reply_tokens", "Longest reply", f"{body['maxReplyTokens']} tokens"),
        SentSetting("turn_detection", "Turn detection", turn),
        SentSetting(
            "acknowledgements",
            "Acknowledgements",
            _text(voice["acknowledgements"])
            if "acknowledgements" in voice
            else "not sent (only read under ear)",
        ),
        SentSetting("interrupt_words", "Words to interrupt", _text(voice["interruptWords"])),
        SentSetting("early_answers", "Starts answering early", _text(voice["earlyAnswers"])),
        SentSetting(
            "thinking",
            "Thinking filler lines",
            f"{len(voice['thinkingLines'])} lines, after {_seconds(voice['thinkingDelayMs'])}, "
            f"again every {_seconds(voice['thinkingRepeatMs'])}",
        ),
        SentSetting(
            "silence",
            "Silence",
            f"asks after {_text(voice['nudgeAfterSeconds'])} s, {voice['nudges']} time(s); "
            f"ends after {_text(voice['endAfterSilenceSeconds'])} s",
        ),
        SentSetting(
            "reask",
            "Asks an unanswered question again",
            "never"
            if not voice["reaskAfterSeconds"]
            else f"after {voice['reaskAfterSeconds']:g} s",
        ),
        SentSetting("max_call_seconds", "Longest call", f"{voice['maxCallSeconds']} s"),
        SentSetting(
            "call_instructions",
            "Call rules",
            f"ours, {len(rules):,} characters"
            if isinstance(rules, str)
            else "the platform's defaults",
        ),
        SentSetting(
            "caller_memory", "Earlier calls with the caller", str(voice["pastConversations"])
        ),
    )
    built_in = [
        SentTool(key, _TOOL_LABELS.get(key, key.replace("_", " ")), bool(on))
        for key, on in tools["tools"].items()
    ]
    built_in.append(
        SentTool(
            KNOWLEDGE_ON_CALLS_FIELD,
            _TOOL_LABELS[KNOWLEDGE_ON_CALLS_FIELD],
            bool(tools[KNOWLEDGE_ON_CALLS_FIELD]),
        )
    )
    payload = {"agent": body, "tools": tools, **_own_key_payload(cfg)}
    return PublishView(
        greeting=str(body["greeting"]),
        steps=_steps(_steps_body(cfg)),
        settings=settings,
        thinking_lines=tuple(str(line) for line in voice["thinkingLines"]),
        built_in_tools=tuple(built_in),
        custom_actions=_actions(cfg),
        digest=_digest(payload, instructions=body["instructions"], greeting=body["greeting"]),
    )


def _config_view(cfg: AgentConfig) -> PublishView:
    """The view an engine with no body builders here gets: what our config states."""
    instructions = compose_engine_prompt(cfg)
    greeting = compose_first_utterance(cfg)
    steps = [
        {
            "title": step.title,
            "detail": step.detail,
            "branches": [{"when": w, "action": a} for w, a in step.branches],
            "collect": list(step.collect),
        }
        for step in cfg.script_steps
    ]
    settings = (
        SentSetting(
            "languages", "Languages", ", ".join([cfg.language_primary, *cfg.languages_extra])
        ),
        SentSetting("model", "Language model", cfg.models.llm_model or "the engine's default"),
        SentSetting("temperature", "Temperature", _text(cfg.temperature)),
        SentSetting("turn_detection", "Turn detection", cfg.turn_detection),
        SentSetting("interrupt_words", "Words to interrupt", str(cfg.interrupt_words)),
        SentSetting("max_call_seconds", "Longest call", f"{cfg.max_call_duration_s} s"),
        SentSetting(
            "call_instructions",
            "Call rules",
            f"ours, {len(call_instructions(cfg)):,} characters"
            if sends_our_call_rules(cfg)
            else "the engine's defaults",
        ),
    )
    payload = {
        "instructions": instructions,
        "greeting": greeting,
        "steps": steps,
        "settings": [(s.key, s.value) for s in settings],
        "filler": list(cfg.filler_lines),
        **_own_key_payload(cfg),
    }
    return PublishView(
        greeting=greeting,
        steps=_steps(steps),
        settings=settings,
        thinking_lines=tuple(cfg.filler_lines),
        built_in_tools=(),
        custom_actions=_actions(cfg),
        digest=_digest(payload, instructions=instructions, greeting=greeting),
    )


def publish_view(engine: VoiceEngine, cfg: AgentConfig) -> PublishView:
    """What a publish of `cfg` on `engine` sends. Raises the adapter's own refusal
    (`ProblemError`) for a config it would refuse to send."""
    if isinstance(engine, ThinnestEngine):
        return _thinnest_view(engine, cfg)
    return _config_view(cfg)


def publish_digest(engine: VoiceEngine, cfg: AgentConfig) -> PublishDigest:
    return publish_view(engine, cfg).digest


__all__ = [
    "PublishDigest",
    "PublishView",
    "SentSetting",
    "SentStep",
    "SentTool",
    "publish_digest",
    "publish_view",
]
