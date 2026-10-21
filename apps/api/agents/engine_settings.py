"""A live hosted agent's call settings, compared with what a publish would send and repaired.

The drift sweep (`workers/engine_reconciliation.py`) reads the script back through
`agents/publishing.engine_drift_for`, which reports and never repairs: a script edited in the
vendor's console may be somebody's emergency fix. The settings here are different. Each is a
value OUR row decides and nobody edits for a good reason — the voice and model chosen,
recording, the call cap, caller memory, escalation, call-backs, collected fields, the call
language, the built-in tools and the hand-over number — and several are compliance or money
(a built-in tool that dials outside our dial gate, a hand-over to a number nobody chose). So
they are put back, the way the own-voice-key switch already is, and the sweep alarms naming
which ones moved.

The config compared against is the one a publish RIGHT NOW would send, built by the same
`service._to_config` and `handoff.spec_for` the publish uses, for `engine_drift_for`'s reason:
a second rendering would drift on the field nobody looks at. An experiment arm differs from
its agent only in its script, so the agent's own config is the arm's settings too.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Protocol, runtime_checkable
from uuid import UUID

from calevate_shared.engine import AgentConfig, EngineAgentRef
from calevate_shared.engine_scope import is_customer_workspace, scope_of
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine

log = get_logger(__name__)

#: Our name for each setting an adapter may report as drifted. The sweep and its alarm
#: carry these labels and never a vendor field name (hard rule 2).
AGENT_SETTING_LABELS: Final[frozenset[str]] = frozenset(
    {
        "voice",
        "model",
        "language",
        "call_language",
        "record_calls",
        "max_call_seconds",
        "caller_memory",
        "machine_detection",
        # The line is released when the agent ends the call (D-749), unless the client
        # switched it off (D-751).
        "end_call_on_finish",
        # The silence that ends the caller's turn (D-751), and the turn mode that makes it so.
        "turn_silence",
        # The platform's own do-not-call tool, kept on beside our opt-out action.
        "do_not_call_tool",
        # How a Studio voice sounds: speed, volume, emotion, model, pronunciation dictionary.
        "voice_tuning",
        # Fixed at 30 seconds on every agent (D-716).
        "ring_seconds",
        "call_summaries",
        "escalation",
        "scheduled_callbacks",
        "lead_capture",
        "collected_fields",
        # The script's stages on an engine with its own step list (D-714).
        "script_steps",
        "built_in_tools",
        "hand_over",
        # Phone only: never the website call button or WhatsApp (founder decision F1,
        # 12 Oct 2026, superseding D-720).
        "surfaces",
        # The client's call settings (founder decisions F3, F9): the "are you still there?"
        # prompt, hanging up after silence, filler lines and the background office sound.
        "silence_prompt",
        "end_after_silence",
        "filler_lines",
        "background_sound",
        # Values the same on every agent (F3, F4, F10): filler timing, how a caller
        # interrupts, and no end phrases.
        "filler_timing",
        "interruptions",
        "end_phrases",
        # Asking an unanswered question again after 5 s (founder, 20 Oct 2026, D-835).
        "reask_wait",
        # The longest reply, in tokens: the agent's own or the console's (D-769).
        "reply_length",
        # Whether the engine's own lead and hand-over sentences are left out (D-847).
        "own_rules",
    }
)


@runtime_checkable
class ReportsAnswerSurfaces(Protocol):
    """An adapter that can say where else a live agent answers besides the phone, for the
    admin drift panel (`engine/thinnest.ThinnestEngine`). Agents answer the phone only
    (founder decision F1, 12 Oct 2026, superseding D-720), so anything listed here is the
    `surfaces` drift the settings sweep repairs."""

    async def answer_surfaces(self, ref: EngineAgentRef) -> list[str]:
        """Plain names of the places besides the phone it answers, e.g. "WhatsApp"."""
        ...


@runtime_checkable
class ReconcilesAgentSettings(Protocol):
    """An adapter that can compare a live agent's call settings with a config and repair
    them (`engine/thinnest.ThinnestEngine`)."""

    async def settings_drift(self, ref: EngineAgentRef, cfg: AgentConfig) -> list[str]:
        """The labels (`AGENT_SETTING_LABELS`) whose live value differs from `cfg`'s."""
        ...

    async def repair_settings(
        self, ref: EngineAgentRef, cfg: AgentConfig, drifted: Sequence[str]
    ) -> None:
        """Rewrite exactly the drifted settings from `cfg`, leaving the script alone."""
        ...


@dataclass(frozen=True, slots=True)
class SettingsCheck:
    #: Our labels (`agents/engine_settings.AGENT_SETTING_LABELS`) that differed.
    drifted: tuple[str, ...]
    #: Every drifted setting was written back.
    repaired: bool


async def _voice_as_workspace_holds(
    session: AsyncSession,
    engine: object,
    *,
    row: Mapping[str, object],
    config: AgentConfig,
    workspace: str,
) -> AgentConfig:
    """`config` with its voice as the customer `workspace` names it. When that workspace
    does not list our clone (`shared_clone_not_listed`: the clone was deleted, or the plan
    lists no shared clones) the voice is left out of the comparison rather than the whole
    check skipped, so recording, the call cap, the hand-over and every other setting are
    still compared and repaired, and no repair sends a voice id the workspace cannot hold.
    The voice itself is the withdrawn-voice alarm's (`workers/engine_reconciliation`)."""
    from apps.api.agents.shared_clones import SHARED_CLONE_NOT_LISTED, voice_in_workspace

    try:
        return await voice_in_workspace(
            session,
            engine,
            catalogue_voice=row.get("engine_voice_id"),
            config=config,
            workspace=workspace,
        )
    except ProblemError as exc:
        if exc.code != SHARED_CLONE_NOT_LISTED:
            raise
        return config.model_copy(update={"engine_voice_id": None})


async def check_agent_settings(
    *, tenant_id: UUID, agent_id: UUID, engine_agent_ref: str
) -> SettingsCheck | None:
    """Compare one live vendor agent's settings with ours and repair any that moved.

    None when the engine has no such settings, or the agent or the vendor could not be read
    (not evidence of drift; the next tick asks again)."""
    from apps.api.agents.handoff import spec_for
    from apps.api.agents.service import _load_agent, _to_config
    from apps.api.healer.protection import healer_holds_line

    engine = get_engine()
    settings = engine if isinstance(engine, ReconcilesAgentSettings) else None
    if settings is None:
        return None
    try:
        async with tenant_session(tenant_id) as session:
            if await healer_holds_line(session, agent_id=agent_id):
                # The healer changed the hand-over and the line state on purpose (D-701);
                # a repair here would undo its hold. Its restoring publish rewrites both.
                return None
            row = await _load_agent(session, tenant_id, agent_id)
            handoff, _duty = await spec_for(session, dict(row))
            config = _to_config(tenant_id, row, engine=engine, handoff=handoff)
            # In a client's workspace one of our clones is spoken under the id that
            # workspace lists for it, as the publish sent it (`shared_clones`). An agent
            # still on a pre-D-797 copy reads as voice drift and is repaired onto it.
            workspace = scope_of(engine_agent_ref)
            if is_customer_workspace(workspace):
                config = await _voice_as_workspace_holds(
                    session, engine, row=row, config=config, workspace=str(workspace)
                )
        drifted = await settings.settings_drift(engine_agent_ref, config)
    except ProblemError as exc:
        log.info(
            "engine_settings_check_skipped",
            extra={"agent_id": str(agent_id), "reason": exc.code},
        )
        return None
    if not drifted:
        return SettingsCheck(drifted=(), repaired=False)
    try:
        await settings.repair_settings(engine_agent_ref, config, drifted)
    except ProblemError as exc:
        log.warning(
            "engine_settings_repair_failed",
            extra={"agent_id": str(agent_id), "reason": exc.code},
        )
        return SettingsCheck(drifted=tuple(drifted), repaired=False)
    return SettingsCheck(drifted=tuple(drifted), repaired=True)


__all__ = [
    "AGENT_SETTING_LABELS",
    "ReconcilesAgentSettings",
    "ReportsAnswerSurfaces",
    "SettingsCheck",
    "check_agent_settings",
]
