"""The operator's list of everything one agent's engine agents hold on the voice platform
(D-868).

Since D-1019 an agent need not hold an engine agent of its own: its published inbound lines,
the campaigns holding one, its test copy and each arm of a running script test hold their own
copies of the client's knowledge. So the list is per HOLDER, through the one definition the
knowledge fan-out uses (`kb_service.vendor_targets`), and each holder's rows come from two
sides read together: what our claim rows say we attached to it (`engine_kb_routes`, through
`kb_sources` so the read is the tenant's own), and what the platform lists for it
(`VoiceEngine.list_kb`, in the client's own workspace, which the holder's handle names). The
verdicts:

* `held` — ours, and the platform lists it.
* `missing` — ours on record, and the platform does not list it: the holder knows less than
  the client approved (the drift sweep's `stranded`, `kb/reconciliation.py`).
* `not_sent` — a live source of the client's with no copy on this holder, and why: a PDF
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
from apps.api.kb.service import _HOLDER, KbTarget, _holder

log = get_logger(__name__)

Verdict = Literal["held", "missing", "not_sent", "not_ours"]
HolderKind = Literal["agent", "line", "campaign", "test_copy", "arm"]

#: The most rows one holder's list returns, each query read with this LIMIT. A client's
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
    #: Why it is not on the holder, for `not_sent`; the item's own refusal otherwise.
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class HolderKnowledge:
    """What one engine agent carrying this agent's work holds."""

    kind: HolderKind
    #: The line's or campaign's name, or the arm's letter; None for the agent's own engine
    #: agent and its test copy.
    name: str | None
    engine_agent_ref: str
    #: False when the platform's list for this holder could not be read: the verdicts are
    #: then from our rows alone, and `held`/`missing` are not told apart.
    listed: bool
    items: list[AgentKnowledgeItem]


@dataclass(frozen=True, slots=True)
class AgentKnowledge:
    agent_id: UUID
    #: Empty when nothing carries the agent to callers yet.
    holders: list[HolderKnowledge]


_RECORDED_SQL = f"""
SELECT r.source_id, r.engine_kb_ref, s.name, s.is_active, coalesce(u.source_kind, s.kind),
       u.ingest_status, u.ingest_detail
FROM engine_kb_routes r
JOIN kb_sources s ON s.id = r.source_id
LEFT JOIN kb_uploads u ON u.source_id = s.id
WHERE s.tenant_id = :tid AND {_HOLDER}
ORDER BY s.name, r.source_id
LIMIT :cap
"""

_UNSENT_SQL = f"""
SELECT s.id, s.name, coalesce(u.source_kind, s.kind), u.ingest_status, u.ingest_detail,
       u.read_state, u.read_detail
FROM kb_sources s
LEFT JOIN kb_uploads u ON u.source_id = s.id
WHERE s.tenant_id = :tid AND s.is_active = true
  AND NOT EXISTS (SELECT 1 FROM engine_kb_routes r WHERE r.source_id = s.id AND {_HOLDER})
ORDER BY s.name, s.id
LIMIT :cap
"""

_AGENT_EXISTS_SQL = (
    "SELECT 1 FROM agents WHERE id = :aid AND tenant_id = :tid AND deleted_at IS NULL"
)

#: The names a holder is shown by: a line's, a campaign's, an arm's letter.
_HOLDER_NAMES_SQL = (
    "SELECT id, name FROM inbound_lines WHERE agent_id = :aid "
    "UNION ALL SELECT id, name FROM campaigns WHERE agent_id = :aid "
    "UNION ALL SELECT v.id, v.label FROM prompt_experiment_variants v "
    "JOIN prompt_experiments e ON e.id = v.experiment_id WHERE e.agent_id = :aid"
)


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


def _params(tenant_id: UUID, target: KbTarget) -> dict[str, object]:
    return {
        "tid": tenant_id,
        "cap": MAX_ITEMS,
        **_holder(
            target.agent_id,
            target.variant_id,
            target.test_copy,
            target.inbound_line_id,
            target.campaign_id,
        ),
    }


def _kind_of(target: KbTarget) -> HolderKind:
    if target.inbound_line_id is not None:
        return "line"
    if target.campaign_id is not None:
        return "campaign"
    if target.variant_id is not None:
        return "arm"
    return "test_copy" if target.test_copy else "agent"


async def _holders(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID
) -> list[tuple[KbTarget, HolderKind, str | None]]:
    """The engine agents carrying this agent's work, each with its kind and name."""
    found = await session.execute(text(_AGENT_EXISTS_SQL), {"aid": agent_id, "tid": tenant_id})
    if found.first() is None:
        raise ProblemError.not_found("Agent")
    named = (await session.execute(text(_HOLDER_NAMES_SQL), {"aid": agent_id})).all()
    names = {UUID(str(row[0])): str(row[1]) for row in named}
    out: list[tuple[KbTarget, HolderKind, str | None]] = []
    for target in await kb_service.vendor_targets(session, tenant_id=tenant_id):
        if target.agent_id != agent_id:
            continue
        own_id = target.inbound_line_id or target.campaign_id or target.variant_id
        out.append((target, _kind_of(target), names.get(own_id) if own_id else None))
    return out


async def _recorded(session: AsyncSession, target: KbTarget) -> set[str]:
    return await kb_service.recorded_handles_of_agent(
        session,
        target.agent_id,
        target.variant_id,
        test_copy=target.test_copy,
        inbound_line_id=target.inbound_line_id,
        campaign_id=target.campaign_id,
    )


async def _listing(engine: VoiceEngine, ref: str) -> list[str] | None:
    if not engine.capabilities.has("knowledge_base"):
        return None
    try:
        return list(await engine.list_kb(ref))
    except ProblemError as exc:
        log.warning("kb_agent_view_unlisted", extra={"code": exc.code})
        return None


async def _holder_knowledge(
    session: AsyncSession,
    engine: VoiceEngine,
    *,
    tenant_id: UUID,
    target: KbTarget,
    kind: HolderKind,
    name: str | None,
) -> HolderKnowledge:
    listing = await _listing(engine, target.engine_ref)
    listed = set(listing or ())
    params = _params(tenant_id, target)
    items: list[AgentKnowledgeItem] = []
    recorded: set[str] = set()
    for row in (await session.execute(text(_RECORDED_SQL), params)).all():
        handle = str(row[1])
        recorded.add(handle)
        items.append(
            AgentKnowledgeItem(
                verdict="held" if listing is None or handle in listed else "missing",
                handle=handle,
                source_id=UUID(str(row[0])),
                name=str(row[2]),
                kind=str(row[4]),
                detail=row[6] if row[5] == "error" else None,
            )
        )
    for handle in sorted(await _recorded(session, target) - recorded):
        recorded.add(handle)
        items.append(
            AgentKnowledgeItem(
                verdict="held" if listing is None or handle in listed else "missing",
                handle=handle,
                name="Business facts",
                kind="facts",
            )
        )
    for row in (await session.execute(text(_UNSENT_SQL), params)).all():
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
    return HolderKnowledge(
        kind=kind,
        name=name,
        engine_agent_ref=target.engine_ref,
        listed=listing is not None,
        items=items[:MAX_ITEMS],
    )


async def agent_knowledge(
    session: AsyncSession, engine: VoiceEngine, *, tenant_id: UUID, agent_id: UUID
) -> AgentKnowledge:
    """Everything each engine agent carrying this agent holds or should hold, in the caller's
    tenant session. Read per holder: read off the agent's own engine agent alone, an agent
    that holds none (D-1019) showed every live item as not sent while its lines and
    campaigns answered callers from their own copies."""
    holders = await _holders(session, tenant_id=tenant_id, agent_id=agent_id)
    return AgentKnowledge(
        agent_id=agent_id,
        holders=[
            await _holder_knowledge(
                session, engine, tenant_id=tenant_id, target=target, kind=kind, name=name
            )
            for target, kind, name in holders
        ],
    )


async def remove_unrecorded(
    session: AsyncSession,
    engine: VoiceEngine,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    holder_ref: str,
    handle: str,
) -> None:
    """Delete, on the platform, a document one of this agent's engine agents holds that no
    row of ours names.

    Under the tenant's knowledge lock, so a publish that is attaching this very copy and has
    not yet recorded it cannot be undercut: once the lock is ours, a handle still unrecorded
    is one no publish of ours made. A handle we record is refused, because removing it here
    would leave our rows promising the client knowledge the holder no longer has. A
    `holder_ref` that is not one of this agent's engine agents is not found, so the route
    cannot reach another agent's or another client's.
    """
    await kb_service.lock_tenant_knowledge(session, tenant_id=tenant_id)
    holders = await _holders(session, tenant_id=tenant_id, agent_id=agent_id)
    target = next((t for t, _kind, _name in holders if t.engine_ref == holder_ref), None)
    if target is None:
        raise ProblemError.not_found("Agent document")
    if handle in await _recorded(session, target):
        raise ProblemError.conflict(
            "kb_document_is_ours",
            "That document is the client's own knowledge.",
            remediation="Remove it from the client's What your agents know page instead.",
        )
    listing = await _listing(engine, target.engine_ref)
    if listing is None or handle not in listing:
        raise ProblemError.not_found("Agent document")
    await engine.detach_kb(target.engine_ref, handle)
    log.info("kb_unrecorded_document_removed", extra={"agent_id": str(agent_id)})


__all__ = [
    "AgentKnowledge",
    "AgentKnowledgeItem",
    "HolderKind",
    "HolderKnowledge",
    "Verdict",
    "agent_knowledge",
    "remove_unrecorded",
]
