"""Behaviour changes the healer will only ever PROPOSE (D-701, founder decision 1).

A struggling agent's cause is sometimes its own behaviour rather than our plumbing: a new
script that confuses callers, knowledge with gaps, callers speaking a language it is not
set up for. The healer never edits a prompt, voice, model, knowledge or disclosure line on
its own. It drafts one of three proposals and a person decides:

* `rollback_prompt`: the agent started struggling within `ROLLBACK_LOOKBACK` of a script
  change; one click restores the previous version (`agents/prompts.rollback_prompt`, a
  copy-forward that is itself versioned and audited).
* `review_knowledge` / `review_languages`: there is no safe one-click change, so the
  proposal opens the screen that fixes it and can be dismissed.

The copy is written here from ids and counts, never from transcript text, so a proposal
cannot carry a caller's words (hard rule 6). The assistant reads pending proposals through
`pending_for_tenant` to surface them in its approvals view.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.prompts import rollback_prompt
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7

ProposalKind = Literal["rollback_prompt", "review_knowledge", "review_languages"]

#: A script change this close before the trouble started is the first suspect.
ROLLBACK_LOOKBACK: Final = timedelta(hours=48)
#: A pending proposal nobody decided expires, so the list never shows a stale suggestion.
PROPOSAL_TTL: Final = timedelta(days=7)

#: What each proposal says, from the client's side. `screen` is the dashboard path that
#: fixes a review proposal, relative to the client's own space.
COPY: Final[dict[str, dict[str, str]]] = {
    "rollback_prompt": {
        "title": "Go back to the previous script",
        "body": "Calls started going worse soon after the script was last changed. Going "
        "back to the version before it usually fixes this straight away. You can change "
        "the script again afterwards.",
        "action": "Restore previous script",
    },
    "review_knowledge": {
        "title": "Fill the gaps in your business information",
        "body": "Callers keep asking things your agent cannot find an answer to. Adding "
        "those answers is the quickest fix.",
        "action": "See the questions",
        "screen": "knowledge",
    },
    "review_languages": {
        "title": "Check the languages your agent speaks",
        "body": "Many callers speak a language your agent is not set up to use. Adding it "
        "lets your agent reply in the caller's language.",
        "action": "Open the agent",
        "screen": "agents",
    },
}

_SIGNAL_TO_KIND: Final[dict[str, ProposalKind]] = {
    "knowledge": "review_knowledge",
    "language": "review_languages",
}


@dataclass(frozen=True, slots=True)
class Proposal:
    id: UUID
    agent_id: UUID
    agent_name: str | None
    kind: str
    status: str
    detail: dict[str, Any]
    created_at: datetime
    decided_at: datetime | None


async def _recent_prompt_change(
    session: AsyncSession, *, agent_id: UUID, before: datetime
) -> dict[str, int] | None:
    """The live version and the one before it, if the live one is recent enough."""
    rows = (
        await session.execute(
            text(
                "SELECT pv.version, pv.created_at FROM prompt_versions pv JOIN agents a ON "
                "a.id = pv.agent_id WHERE pv.agent_id = :aid AND pv.version <= (SELECT "
                "version FROM prompt_versions WHERE id = a.system_prompt_id) "
                "ORDER BY pv.version DESC LIMIT 2"
            ),
            {"aid": agent_id},
        )
    ).all()
    if len(rows) < 2 or rows[0][1] < before - ROLLBACK_LOOKBACK:
        return None
    return {"from_version": int(rows[0][0]), "to_version": int(rows[1][0])}


async def propose_for(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    incident_id: UUID | None,
    worst_signal: str | None,
    since: datetime,
) -> list[ProposalKind]:
    """Draft what fits the evidence. At most one pending proposal per agent and kind."""
    drafts: list[tuple[ProposalKind, dict[str, Any]]] = []
    change = await _recent_prompt_change(session, agent_id=agent_id, before=since)
    if change is not None:
        drafts.append(("rollback_prompt", change))
    kind = _SIGNAL_TO_KIND.get(worst_signal or "")
    if kind is not None:
        drafts.append((kind, {"signal": worst_signal}))
    made: list[ProposalKind] = []
    for draft_kind, detail in drafts:
        row = (
            await session.execute(
                text(
                    "INSERT INTO heal_proposals (id, tenant_id, agent_id, incident_id, kind, "
                    "status, detail, created_at, updated_at) VALUES (:id, :tid, :aid, :iid, "
                    ":kind, 'pending', CAST(:detail AS jsonb), now(), now()) ON CONFLICT "
                    "(agent_id, kind) WHERE status = 'pending' DO NOTHING RETURNING id"
                ),
                {
                    "id": uuid7(),
                    "tid": tenant_id,
                    "aid": agent_id,
                    "iid": incident_id,
                    "kind": draft_kind,
                    "detail": _json(detail),
                },
            )
        ).first()
        if row is not None:
            made.append(draft_kind)
    return made


def _json(value: dict[str, Any]) -> str:
    import json

    return json.dumps(value, sort_keys=True)


_LIST = (
    "SELECT p.id, p.agent_id, a.name, p.kind, p.status, p.detail, p.created_at, p.decided_at "
    "FROM heal_proposals p LEFT JOIN agents a ON a.id = p.agent_id"
)


def _proposal(row: Any) -> Proposal:
    return Proposal(
        id=row[0],
        agent_id=row[1],
        agent_name=row[2],
        kind=str(row[3]),
        status=str(row[4]),
        detail=dict(row[5] or {}),
        created_at=row[6],
        decided_at=row[7],
    )


async def expire_stale(session: AsyncSession) -> int:
    result = await session.execute(
        text(
            "UPDATE heal_proposals SET status = 'expired', decided_at = now(), updated_at = "
            "now() WHERE status = 'pending' AND created_at < now() - make_interval(days => :d)"
        ),
        {"d": PROPOSAL_TTL.days},
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def pending_for_tenant(session: AsyncSession, *, limit: int = 20) -> list[Proposal]:
    """Pending proposals of the session's tenant, newest first (RLS scopes it)."""
    rows = (
        await session.execute(
            text(_LIST + " WHERE p.status = 'pending' ORDER BY p.created_at DESC LIMIT :limit"),
            {"limit": limit},
        )
    ).all()
    return [_proposal(r) for r in rows]


async def list_for_tenant(session: AsyncSession, *, days: int, limit: int) -> list[Proposal]:
    rows = (
        await session.execute(
            text(
                _LIST + " WHERE p.status = 'pending' OR p.created_at >= now() - "
                "make_interval(days => :days) ORDER BY (p.status = 'pending') DESC, "
                "p.created_at DESC LIMIT :limit"
            ),
            {"days": days, "limit": limit},
        )
    ).all()
    return [_proposal(r) for r in rows]


async def _claim(session: AsyncSession, proposal_id: UUID) -> Proposal:
    row = (
        await session.execute(
            text(_LIST + " WHERE p.id = :id FOR UPDATE OF p"), {"id": proposal_id}
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Suggestion")
    proposal = _proposal(row)
    if proposal.status != "pending":
        raise ProblemError.conflict(
            "suggestion_already_decided",
            "This suggestion has already been dealt with.",
            remediation="Refresh the page to see where it stands.",
        )
    return proposal


async def _decide(
    session: AsyncSession, proposal_id: UUID, *, status: str, by: UUID | None
) -> None:
    await session.execute(
        text(
            "UPDATE heal_proposals SET status = :status, decided_by = :by, decided_at = now(), "
            "updated_at = now() WHERE id = :id AND status = 'pending'"
        ),
        {"id": proposal_id, "status": status, "by": by},
    )


async def apply(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    proposal_id: UUID,
    by: UUID | None,
    author: UUID | None,
) -> Proposal:
    """Carry out a proposal a person approved. Only `rollback_prompt` changes anything.
    `by` is whoever decided (an operator in view-as included); `author` is the client user
    the new script version is credited to, None for an operator."""
    proposal = await _claim(session, proposal_id)
    if proposal.kind != "rollback_prompt":
        raise ProblemError.business_rule(
            "suggestion_needs_your_edit",
            "This suggestion is a change only you can make.",
            remediation="Open the screen it points to, or dismiss the suggestion.",
        )
    version = int(proposal.detail.get("to_version", 0))
    await rollback_prompt(
        session,
        tenant_id=tenant_id,
        agent_id=proposal.agent_id,
        version=version,
        created_by=author,
    )
    await _decide(session, proposal_id, status="applied", by=by)
    return proposal


async def dismiss(session: AsyncSession, *, proposal_id: UUID, by: UUID | None) -> Proposal:
    proposal = await _claim(session, proposal_id)
    await _decide(session, proposal_id, status="dismissed", by=by)
    return proposal


__all__ = [
    "COPY",
    "PROPOSAL_TTL",
    "ROLLBACK_LOOKBACK",
    "Proposal",
    "ProposalKind",
    "apply",
    "dismiss",
    "expire_stale",
    "list_for_tenant",
    "pending_for_tenant",
    "propose_for",
]
