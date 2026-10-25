"""Give an account's agents a standard field's improved wording (D-881).

A field's reason is the extraction model's instruction for that field (TRD §7) and is also
compiled into the agent's script under "what to collect", so an agent made from a standard
set keeps the wording it was made with until something rewrites it. Queued through the
outbox, one message per account, by the migration that ships a new wording (first:
`b3d7e2a9c461`, the real-estate budget); the payload carries the old and new text as that
migration froze them. A payload may also carry `old_enum_values` and `new_enum_values`
(D-887, `c8e2f4a6b913`, the BHK sizes): the choices must then match exactly too, and are
replaced along with the reason.

Per agent, in one transaction: if the field still has the old reason (and choices) word
for word, a new schema version with the new ones (`agents/lead_fields.
refresh_field_reason`), then the script recompiled and a live agent republished through the
one publish path (`script_builder.recompile_collect`). A field anybody edited is left
alone. One agent the voice platform refuses rolls back its own schema write, so it keeps
the old wording, the run ends `partial`, and re-queueing the same payload picks it up; the
others are not held back. A redelivery finds nothing left to change.
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

from sqlalchemy import text

from apps.api.agents.lead_fields import refresh_field_reason as refresh_agent_field_reason
from apps.api.agents.script_builder import recompile_collect
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.session import tenant_session

log = get_logger(__name__)

JOB_NAME: Final = "refresh_field_reason"


async def _agent_ids(tenant_id: UUID) -> list[UUID]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT id FROM agents WHERE deleted_at IS NULL ORDER BY created_at, id")
            )
        ).all()
    return [UUID(str(r[0])) for r in rows]


def _choices(payload: dict[str, Any], name: str) -> list[str] | None:
    """A frozen choice list from the payload; None when this refresh leaves choices alone."""
    raw = payload.get(name)
    return None if raw is None else [str(v) for v in raw]


async def refresh_field_reason(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    key, old_reason, new_reason = (
        str(payload["key"]),
        str(payload["old_reason"]),
        str(payload["new_reason"]),
    )
    old_choices = _choices(payload, "old_enum_values")
    new_choices = _choices(payload, "new_enum_values")
    written = refused = 0
    for agent_id in await _agent_ids(tenant_id):
        try:
            async with tenant_session(tenant_id) as session:
                if await refresh_agent_field_reason(
                    session,
                    agent_id=agent_id,
                    key=key,
                    old_reason=old_reason,
                    new_reason=new_reason,
                    old_enum_values=old_choices,
                    new_enum_values=new_choices,
                ):
                    await recompile_collect(session, tenant_id=tenant_id, agent_id=agent_id)
                    written += 1
        except ProblemError as exc:
            refused += 1
            log.warning(
                "field_reason_refresh_refused",
                extra={"agent_id": str(agent_id), "field_key": key, "reason": exc.code},
            )
    log.info(
        "field_reason_refreshed",
        extra={
            "tenant_id": str(tenant_id),
            "field_key": key,
            "agents_written": written,
            "agents_refused": refused,
        },
    )
    return "done" if not refused else "partial"


__all__ = ["JOB_NAME", "refresh_field_reason"]
