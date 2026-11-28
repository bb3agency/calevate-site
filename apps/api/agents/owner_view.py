"""What the agent is told, the owner's part only (W3.15): the read-only "What it is told" view
of a campaign's or an inbound line's Script tab.

It is the text inside the client fence of the composed prompt (`calevate_shared.engine.
fenced_script` over the config Start or put-live builds, `service.campaign_config`,
`service.line_config`), so the owner reads exactly what their script becomes and nothing the
platform adds: never the confidentiality rule (D-674), the truthful answers (hard rule 5),
the notices or the call rules. Reading it changes nothing, and the publish read-back is
untouched (`agents/verification`).

The fence's own text is neutralised (`neutralise_markers`); a script that copies a platform
sentence word for word has it left out of the view (`owner_part`).
"""

from __future__ import annotations

from typing import Final, Literal
from uuid import UUID

from calevate_shared.engine import (
    CLIENT_SCRIPT_CLOSE,
    CLIENT_SCRIPT_OPEN,
    CONFIDENTIALITY_MARKER,
    AgentConfig,
    fenced_script,
    truthful_answer_directive,
)
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger

log = get_logger(__name__)

#: A holder with no script yet has nothing to show (`script_builder._NOTHING_TO_MEASURE`).
_NO_SCRIPT: Final = frozenset({"line_has_no_script", "agent_has_no_script"})


def _platform_text(cfg: AgentConfig) -> tuple[str, ...]:
    return (
        CONFIDENTIALITY_MARKER,
        CLIENT_SCRIPT_OPEN,
        CLIENT_SCRIPT_CLOSE,
        truthful_answer_directive(call_is_recorded=cfg.call_is_recorded).strip(),
    )


def owner_part(cfg: AgentConfig) -> str:
    """The client's part of the prompt `cfg` composes, as the engine holds it."""
    told = fenced_script(cfg.system_prompt or "")
    for part in _platform_text(cfg):
        # Only a script that copies a platform sentence holds one; it is left out of the
        # view rather than shown, so the view never prints the platform's words.
        if part and part in told:
            log.info("owner_view_platform_text_left_out")
            told = told.replace(part, "")
    return told.strip()


async def holder_told(
    session: AsyncSession,
    *,
    kind: Literal["campaign", "line"],
    tenant_id: UUID,
    holder_id: UUID,
) -> str | None:
    """The owner's part of what the holder's engine agent is told, from its saved script;
    None while it has no script."""
    from apps.api.agents.service import campaign_config, line_config

    try:
        if kind == "campaign":
            cfg = await campaign_config(session, tenant_id=tenant_id, campaign_id=holder_id)
        else:
            cfg = await line_config(session, tenant_id=tenant_id, line_id=holder_id)
    except ProblemError as exc:
        if exc.code in _NO_SCRIPT:
            return None
        raise
    return owner_part(cfg) or None


__all__ = ["holder_told", "owner_part"]
