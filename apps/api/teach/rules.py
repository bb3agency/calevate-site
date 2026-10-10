"""Rules an owner taught for one agent, waiting to be written into its script.

The script (`calevate_shared.call_script.CallScript`) is owned by the script builder, and
it has no 'anytime rules' section yet, so a taught rule is stored here as PENDING and the
builder shows it, writes it where it belongs and marks it applied (or the owner dismisses
it). Keeping the proposal out of the script until then means a taught rule never changes
what a live agent says without the owner putting the script live.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.teach.models import MAX_RULE_CHARS

#: The most pending rules one agent holds; an owner past this should put them live first.
MAX_PENDING_RULES: Final = 50

RuleStatus = Literal["pending", "applied", "dismissed"]


@dataclass(frozen=True, slots=True)
class RuleProposal:
    id: UUID
    agent_id: UUID
    text: str
    status: str
    created_at: datetime


def clean_rule(value: str) -> str:
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ProblemError.business_rule("rule_empty", "Write the rule before saving it.")
    if len(cleaned) > MAX_RULE_CHARS:
        raise ProblemError.business_rule(
            "rule_too_long", f"A rule is at most {MAX_RULE_CHARS} characters."
        )
    return cleaned


async def propose_rules(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    texts: list[str],
    teaching_id: UUID | None,
    created_by: UUID | None,
) -> list[UUID]:
    cleaned = [clean_rule(t) for t in texts]
    # Serialise per agent so the cap below holds under two saves at once.
    await session.execute(text("SELECT 1 FROM agents WHERE id = :id FOR UPDATE"), {"id": agent_id})
    pending = int(
        (
            await session.execute(
                text(
                    "SELECT count(*) FROM agent_rule_proposals "
                    "WHERE agent_id = :aid AND status = 'pending'"
                ),
                {"aid": agent_id},
            )
        ).scalar()
        or 0
    )
    if pending + len(cleaned) > MAX_PENDING_RULES:
        raise ProblemError.business_rule(
            "rules_full",
            f"This agent already has {pending} rules waiting for its script.",
            remediation="Open the agent's script and add or dismiss the waiting rules first.",
        )
    ids: list[UUID] = []
    for value in cleaned:
        rule_id = uuid7()
        await session.execute(
            text(
                "INSERT INTO agent_rule_proposals (id, tenant_id, agent_id, text, teaching_id, "
                "status, created_by, created_at, updated_at) VALUES (:id, :tid, :aid, :text, "
                ":teaching, 'pending', :by, now(), now())"
            ),
            {
                "id": rule_id,
                "tid": tenant_id,
                "aid": agent_id,
                "text": value,
                "teaching": teaching_id,
                "by": created_by,
            },
        )
        ids.append(rule_id)
    return ids


async def list_rules(
    session: AsyncSession, *, agent_id: UUID, status: RuleStatus | None = "pending"
) -> list[RuleProposal]:
    clause = "AND status = :status" if status else ""
    params: dict[str, object] = {"aid": agent_id}
    if status:
        params["status"] = status
    rows = (
        await session.execute(
            text(
                "SELECT id, agent_id, text, status, created_at FROM agent_rule_proposals "
                f"WHERE agent_id = :aid {clause} ORDER BY created_at, id LIMIT 100"
            ),
            params,
        )
    ).all()
    return [
        RuleProposal(id=r[0], agent_id=r[1], text=r[2], status=r[3], created_at=r[4]) for r in rows
    ]


async def resolve_rule(
    session: AsyncSession,
    *,
    agent_id: UUID,
    rule_id: UUID,
    status: Literal["applied", "dismissed"],
    resolved_by: UUID | None,
) -> RuleProposal:
    row = (
        await session.execute(
            text(
                "UPDATE agent_rule_proposals SET status = :status, resolved_by = :by, "
                "resolved_at = now(), updated_at = now() "
                "WHERE id = :id AND agent_id = :aid AND status = 'pending' "
                "RETURNING id, agent_id, text, status, created_at"
            ),
            {"id": rule_id, "aid": agent_id, "status": status, "by": resolved_by},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Waiting rule")
    return RuleProposal(id=row[0], agent_id=row[1], text=row[2], status=row[3], created_at=row[4])


__all__ = [
    "MAX_PENDING_RULES",
    "RuleProposal",
    "clean_rule",
    "list_rules",
    "propose_rules",
    "resolve_rule",
]
