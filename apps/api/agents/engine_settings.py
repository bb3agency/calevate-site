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

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Protocol, runtime_checkable
from uuid import UUID

from calevate_shared.engine import AgentConfig, EngineAgentRef

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
        "call_summaries",
        "escalation",
        "scheduled_callbacks",
        "lead_capture",
        "collected_fields",
        "built_in_tools",
        "hand_over",
    }
)


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
    "SettingsCheck",
    "check_agent_settings",
]
