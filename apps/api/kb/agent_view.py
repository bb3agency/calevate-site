"""The operator's list of everything one agent holds on the voice platform (D-868).

One row per item, from two sides read together: what our claim rows say we attached to this
agent (`engine_kb_routes`, through `kb_sources` so the read is the tenant's own), and what
the platform lists for it (`VoiceEngine.list_kb`, in the client's own workspace, which the
agent's handle names). The verdicts:

* `held` — ours, and the platform lists it.
* `missing` — ours on record, and the platform does not list it: the agent knows less than
  the client approved (the drift sweep's `stranded`, `kb/reconciliation.py`).
* `not_sent` — a live source of the client's with no copy on this agent, and why: a PDF
  with no words, a page the platform refused, or one the catch-up has not reached yet.
* `not_ours` — the platform lists it and no row of ours names it: added in the platform's
  console, or left by a failure. The one kind an operator may remove here
  (`remove_unrecorded`); ours are removed from the client's page, so that our rows and the
  platform never disagree about a client's knowledge.

Admin realm: vendor ids appear. Reads only, except `remove_unrecorded`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal
from uuid import UUID

from calevate_shared.engine import VoiceEngine
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.kb import service as kb_service

log = get_logger(__name__)

Verdict = Literal["held", "missing", "not_sent", "not_ours"]

#: The most rows one agent's list returns, each query read with this LIMIT. A client's
#: knowledge is a few dozen items; past this the list is cut, never unbounded.
MAX_ITEMS: Final = 500


@dataclass(frozen=True, slots=True)
class AgentKnowledgeItem:
    verdict: Verdict
    #: The platform's id for the copy; None for a source not sent.
    handle: str | None = None
    source_id: UUID | None = None
    name: str | None = None
    #: `kb_uploads.source_kind`, `text` for typed knowledge, `facts` for the business-facts
    #: document, None for a copy not ours.
    kind: str | None = None
    #: Why it is not on the agent, for `not_sent`; the item's own refusal otherwise.
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class AgentKnowledge:
    agent_id: UUID
    #: False when the agent has no vendor agent yet, or the listing could not be read: the
    #: verdicts are then from our rows alone, and `held`/`missing` are not told apart.
    listed: bool
    items: list[AgentKnowledgeItem]


_RECORDED_SQL = """
SELECT r.source_id, r.engine_kb_ref, s.name, s.is_active, coalesce(u.source_kind, s.kind),
       u.ingest_status, u.ingest_detail
FROM engine_kb_routes r
JOIN kb_sources s ON s.id = r.source_id
LEFT JOIN kb_uploads u ON u.source_id = s.id
WHERE s.tenant_id = :tid AND r.agent_id = :aid AND r.variant_id IS NULL
ORDER BY s.name, r.source_id
LIMIT :cap
"""

_UNSENT_SQL = """
SELECT s.id, s.name, coalesce(u.source_kind, s.kind), u.ingest_status, u.ingest_detail,
       u.read_state, u.read_detail
FROM kb_sources s
LEFT JOIN kb_uploads u ON u.source_id = s.id
WHERE s.tenant_id = :tid AND s.is_active = true
  AND NOT EXISTS (
    SELECT 1 FROM engine_kb_routes r
    WHERE r.source_id = s.id AND r.agent_id = :aid AND r.variant_id IS NULL
  )
ORDER BY s.name, s.id
LIMIT :cap
"""


def _why_not_sent(
    *,
    kind: str,
    ingest_status: str | None,
    ingest_detail: str | None,
    read_state: str | None,
    read_detail: str | None,
) -> str:
    if ingest_status == "error":
        return ingest_detail or "The platform refused it."
    if kind == "pdf" and read_state != "ready":
        return read_detail or "Its words have not been read."
    return "Not attached yet; the knowledge sweep attaches it."


def _params(tenant_id: UUID, agent_id: UUID) -> dict[str, object]:
    return {"tid": tenant_id, "aid": agent_id, "cap": MAX_ITEMS}


async def _agent_ref(session: AsyncSession, *, tenant_id: UUID, agent_id: UUID) -> str | None:
    row = (
        await session.execute(
            text(
                "SELECT engine_agent_ref FROM agents WHERE id = :aid AND tenant_id = :tid "
                "AND deleted_at IS NULL"
            ),
            {"aid": agent_id, "tid": tenant_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    return str(row[0]) if row[0] else None


async def _listing(engine: VoiceEngine, ref: str | None) -> list[str] | None:
    if ref is None or not engine.capabilities.has("knowledge_base"):
        return None
    try:
        return list(await engine.list_kb(ref))
    except ProblemError as exc:
        log.warning("kb_agent_view_unlisted", extra={"code": exc.code})
        return None


async def agent_knowledge(
    session: AsyncSession, engine: VoiceEngine, *, tenant_id: UUID, agent_id: UUID
) -> AgentKnowledge:
    """Everything this agent holds or should hold, in the caller's tenant session."""
    ref = await _agent_ref(session, tenant_id=tenant_id, agent_id=agent_id)
    listing = await _listing(engine, ref)
    listed = set(listing or ())
    items: list[AgentKnowledgeItem] = []
    recorded: set[str] = set()
    recorded_rows = (await session.execute(text(_RECORDED_SQL), _params(tenant_id, agent_id))).all()
    for row in recorded_rows:
        handle = str(row[1])
        recorded.add(handle)
        verdict: Verdict = "held" if listing is None or handle in listed else "missing"
        items.append(
            AgentKnowledgeItem(
                verdict=verdict,
                handle=handle,
                source_id=UUID(str(row[0])),
                name=str(row[2]),
                kind=str(row[4]),
                detail=row[6] if row[5] == "error" else None,
            )
        )
    for handle in sorted(await kb_service.recorded_handles_of_agent(session, agent_id) - recorded):
        recorded.add(handle)
        items.append(
            AgentKnowledgeItem(
                verdict="held" if listing is None or handle in listed else "missing",
                handle=handle,
                name="Business facts",
                kind="facts",
            )
        )
    for row in (await session.execute(text(_UNSENT_SQL), _params(tenant_id, agent_id))).all():
        items.append(
            AgentKnowledgeItem(
                verdict="not_sent",
                source_id=UUID(str(row[0])),
                name=str(row[1]),
                kind=str(row[2]),
                detail=_why_not_sent(
                    kind=str(row[2]),
                    ingest_status=row[3],
                    ingest_detail=row[4],
                    read_state=row[5],
                    read_detail=row[6],
                ),
            )
        )
    items.extend(
        AgentKnowledgeItem(verdict="not_ours", handle=handle)
        for handle in (listing or [])
        if handle not in recorded
    )
    return AgentKnowledge(agent_id=agent_id, listed=listing is not None, items=items[:MAX_ITEMS])


async def remove_unrecorded(
    session: AsyncSession, engine: VoiceEngine, *, tenant_id: UUID, agent_id: UUID, handle: str
) -> None:
    """Delete, on the platform, a document this agent holds that no row of ours names.

    Under the tenant's knowledge lock, so a publish that is attaching this very copy and has
    not yet recorded it cannot be undercut: once the lock is ours, a handle still unrecorded
    is one no publish of ours made. A handle we record is refused, because removing it here
    would leave our rows promising the client knowledge the agent no longer has.
    """
    await kb_service.lock_tenant_knowledge(session, tenant_id=tenant_id)
    ref = await _agent_ref(session, tenant_id=tenant_id, agent_id=agent_id)
    if ref is None:
        raise ProblemError.not_found("Agent document")
    if handle in await kb_service.recorded_handles_of_agent(session, agent_id):
        raise ProblemError.conflict(
            "kb_document_is_ours",
            "That document is the client's own knowledge.",
            remediation="Remove it from the client's What your agents know page instead.",
        )
    listing = await _listing(engine, ref)
    if listing is None or handle not in listing:
        raise ProblemError.not_found("Agent document")
    await engine.detach_kb(ref, handle)
    log.info("kb_unrecorded_document_removed", extra={"agent_id": str(agent_id)})


__all__ = [
    "AgentKnowledge",
    "AgentKnowledgeItem",
    "Verdict",
    "agent_knowledge",
    "remove_unrecorded",
]
