"""How long an agent's instructions are, layer by layer, against the engine's box (D-752).

One measurement for every reader: the publish refusal (`agents/engine_limits.py`), the Script
page meter (`agents/script_builder.compiled_preview`), the live-apply failure record
(`apps/workers/live_apply.py`) and the diagnosis tool (`scripts/prompt_size.py`). It counts
`calevate_shared.engine.engine_prompt_layers`, the rendering `compose_engine_prompt` joins, so
the total is the length the engine receives and no reader can count a different prompt from
the one publish sends.

It returns character counts and labels, never text: a script embeds the client's business
details and the platform layers are confidential (hard rules 6 and D-674).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from calevate_shared.call_script import STYLE_HEADER
from calevate_shared.engine import (
    CLIENT_SCRIPT_CLOSE,
    CLIENT_SCRIPT_OPEN,
    LAYER_SEPARATOR,
    AgentConfig,
    PromptLayer,
    VoiceEngine,
    engine_prompt_layers,
)
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.engine.hosted_platform import hosted_agent_limits

#: Owner-facing names for the layers, in prompt order.
LAYER_LABELS: Final[dict[PromptLayer, str]] = {
    "preamble": "Calevate's opening rules",
    "how_to_speak": "How to speak",
    "languages": "Languages",
    "spoken_register": "Spoken register",
    "business_facts": "Where the business facts are",
    "notices": "Notices said at the start",
    "caller_memory": "Caller memory",
    "client_script": "Your script",
    "what_you_can_do": "What the agent can do",
    "confidentiality": "Confidentiality",
    "truthful_answers": "Truthful answers (AI and recording)",
    "this_call": "Details filled in for each call",
}

#: The client script's sections as an owner knows them. A header not listed (a v1 or raw
#: script's own) is reported under its bracketed name.
SCRIPT_SECTION_LABELS: Final[dict[str, str]] = {
    "[BUSINESS]": "Business line",
    "[IDENTITY]": "Who the agent is",
    "[GOAL]": "Goal",
    "[OPENING]": "Opening line",
    "[SPEAKING STYLE]": "Speaking style",
    "[CONVERSATION]": "Steps",
    "[TASK FLOW]": "Steps",
    "[WHAT TO COLLECT]": "Details to collect",
    "[OBJECTIONS]": "Objections",
    "[POLICIES]": "Policies",
    "[ENDING]": "Ending",
    "[QUICK FACTS]": "Pinned facts",
    "[FAQ]": "Questions and answers",
    "[EXAMPLE CALL]": "Example call",
    "[T0 FACTS]": "Business facts",
    "[END CALL]": "Ending the call",
}

#: The line `call_script._compile_v2` writes for "Names and how to say them".
NAMES_LINE_PREFIX: Final = "Say these names exactly like this:"
NAMES_LABEL: Final = "Names and how to say them"
FENCE_LABEL: Final = "Script start and end markers"
OTHER_SCRIPT_LABEL: Final = "Other script text"
SEPARATOR_LABEL: Final = "Line breaks between parts"


@dataclass(frozen=True, slots=True)
class SizePart:
    key: str
    label: str
    chars: int


@dataclass(frozen=True, slots=True)
class PromptSize:
    """The composed instructions' length against `limit` (None: the engine has no box)."""

    total: int
    limit: int | None
    layers: tuple[SizePart, ...]
    #: The client script's own sections, which add up to the `client_script` layer.
    script_parts: tuple[SizePart, ...]
    #: Sections sent as the engine's own step list, outside the box.
    native_steps: int = 0
    #: About how much the engine adds around this on every turn, outside the box
    #: (`HostedAgentLimits.added_prompt_chars`); None where nothing is known.
    engine_added: int | None = None

    @property
    def per_turn(self) -> int | None:
        """About what the model reads as instructions each turn, before the history and the
        tool schemas: ours plus the engine's own."""
        return self.total + self.engine_added if self.engine_added is not None else None

    @property
    def over(self) -> int:
        return max(self.total - self.limit, 0) if self.limit is not None else 0

    @property
    def headroom(self) -> int | None:
        return self.limit - self.total if self.limit is not None else None

    @property
    def fits(self) -> bool:
        return self.over == 0

    def longest_script_parts(self, count: int = 3) -> tuple[SizePart, ...]:
        """The owner's longest sections, the ones worth shortening first."""
        parts = [p for p in self.script_parts if p.key not in {"fence", "separator"}]
        return tuple(sorted(parts, key=lambda p: p.chars, reverse=True)[:count])


def script_parts(script: str) -> tuple[SizePart, ...]:
    """The fenced client script as its sections. A section runs from a line starting with
    `[` to the next such line (the rule `splice_quick_facts` and the T0 splicer follow); the
    names line is split out of the speaking style so an owner can see it."""
    sections: list[tuple[str, list[str]]] = []
    for line in script.splitlines():
        if line.startswith("[") and "]" in line:
            sections.append((line[: line.index("]") + 1], [line]))
        elif sections:
            sections[-1][1].append(line)
        else:
            sections.append(("", [line]))
    merged: dict[str, int] = {}
    labels: dict[str, str] = {}

    def add(key: str, label: str, chars: int) -> None:
        merged[key] = merged.get(key, 0) + chars
        labels[key] = label

    for header, lines in sections:
        if header == STYLE_HEADER:
            names = sum(len(x) + 1 for x in lines if x.startswith(NAMES_LINE_PREFIX))
            if names:
                add("names", NAMES_LABEL, names)
            lines = [x for x in lines if not x.startswith(NAMES_LINE_PREFIX)]
        chars = len("\n".join(lines)) + 1
        if not header:
            add("other", OTHER_SCRIPT_LABEL, chars)
        else:
            label = SCRIPT_SECTION_LABELS.get(header, header)
            add(label.casefold().replace(" ", "_"), label, chars)
    fence = len(CLIENT_SCRIPT_OPEN) + len(CLIENT_SCRIPT_CLOSE) + 1
    out = [SizePart(key, labels[key], chars) for key, chars in merged.items() if chars > 0]
    return (*out, SizePart("fence", FENCE_LABEL, fence))


def measure(
    cfg: AgentConfig,
    limit: int | None,
    *,
    native_steps: int = 0,
    engine_added: int | None = None,
) -> PromptSize:
    """The size of `compose_engine_prompt(cfg)` by layer. Counts only."""
    layers = engine_prompt_layers(cfg)
    parts = [SizePart(key, LAYER_LABELS[key], len(text)) for key, text in layers]
    separators = len(LAYER_SEPARATOR) * max(len(layers) - 1, 0)
    total = sum(p.chars for p in parts) + separators
    if separators:
        parts.append(SizePart("separator", SEPARATOR_LABEL, separators))
    script = (cfg.system_prompt or "").strip()
    return PromptSize(
        total=total,
        limit=limit,
        layers=tuple(parts),
        script_parts=script_parts(script) if script else (),
        native_steps=native_steps,
        engine_added=engine_added,
    )


async def publish_config(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    engine: VoiceEngine,
    body: str | None = None,
    structured_script: dict[str, Any] | None = None,
) -> AgentConfig:
    """The config a publish of this agent would send right now.

    Built by `service._to_config` over `service._load_agent` and the on-duty hand-over, the
    three steps `publish_agent` takes, so it carries everything the agent's settings add
    (languages, caller memory, a forwarded line, the account's call-back rule). `body` and
    `structured_script` stand in for the applied script, for a script not yet saved. Raises
    what `_to_config` raises (an agent with no script).
    """
    from apps.api.agents.handoff import spec_for
    from apps.api.agents.service import _load_agent, _to_config

    row = await _load_agent(session, tenant_id, agent_id)
    if body is not None:
        row = {**row, "prompt": body, "structured_script": structured_script}
    handoff, _duty = await spec_for(session, dict(row))
    return _to_config(tenant_id, row, engine=engine, handoff=handoff)


def measure_config(cfg: AgentConfig, engine: VoiceEngine) -> PromptSize:
    limits = hosted_agent_limits(engine)
    return measure(
        cfg,
        limits.prompt_chars,
        native_steps=len(cfg.script_steps),
        engine_added=limits.added_prompt_chars,
    )


async def measure_agent(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID, engine: VoiceEngine
) -> PromptSize:
    """What a publish of this agent's applied script would send right now, measured."""
    cfg = await publish_config(session, tenant_id=tenant_id, agent_id=agent_id, engine=engine)
    return measure_config(cfg, engine)


def as_dict(size: PromptSize) -> dict[str, Any]:
    """JSON-safe counts, for a failure record or a response."""
    return {
        "total_chars": size.total,
        "limit_chars": size.limit,
        "over_chars": size.over,
        "longest": [{"label": p.label, "chars": p.chars} for p in size.longest_script_parts()],
    }


def lines(size: PromptSize) -> Sequence[str]:
    """The report `scripts/prompt_size.py` prints: one line per layer and script section,
    then the total. Labels and counts only."""
    out = [f"{p.label:<44} {p.chars:>6,}" for p in size.layers]
    if size.script_parts:
        out.append("  of which, your script:")
        out += [f"    {p.label:<40} {p.chars:>6,}" for p in size.script_parts]
    if size.native_steps:
        out.append(f"Steps sent separately (outside the box)       {size.native_steps:>6}")
    if size.limit is None:
        out.append(f"{'TOTAL':<44} {size.total:>6,}  (this engine has no limit)")
    else:
        verdict = f"OVER by {size.over:,}" if size.over else f"{size.headroom:,} to spare"
        out.append(f"{'TOTAL':<44} {size.total:>6,} of {size.limit:,}  {verdict}")
    if size.per_turn is not None and size.engine_added is not None:
        out.append(f"{'Added by the calling system (its estimate)':<44} {size.engine_added:>6,}")
        out.append(f"{'Read by the model each turn, before history':<44} {size.per_turn:>6,}")
    return out


__all__ = [
    "LAYER_LABELS",
    "PromptSize",
    "SizePart",
    "as_dict",
    "lines",
    "measure",
    "measure_agent",
    "measure_config",
    "publish_config",
    "script_parts",
]
