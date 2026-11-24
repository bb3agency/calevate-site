"""The operator's list of everything one agent's engine agents hold on the voice platform (D-868).

Since D-1019 an agent holds no engine agent of its own: its Inbound lines, campaigns, test copy
and script test arms do, and the client's knowledge is fanned out to each of them
(`kb/service.vendor_targets`). So the list is read per holder, one row per item per holder,
from two sides read together: what our claim rows say we attached to that holder
(`engine_kb_routes`, through `kb_sources` so the read is the tenant's own), and what the
platform lists for it (`VoiceEngine.list_kb`, in the client's own workspace, which the
holder's handle names). The verdicts:

* `held` — ours, and the platform lists it.
* `missing` — ours on record, and the platform does not list it: the holder knows less than
  the client approved (the drift sweep's `stranded`, `kb/reconciliation.py`).
* `not_sent` — a live source of the client's with no copy on this holder, and why: a PDF
  with no words, a page the platform refused, or one the catch-up has not reached yet.
* `not_ours` — the platform lists it and no row of ours names it: added in the platform's
  console, or left by a failure. The one kind an operator may remove here
  (`remove_unrecorded`); ours are removed from the client's page, so that our rows and the
  platform never disagree about a client's knowledge.

Reading only the agent's own engine agent, as this did before D-1019, listed every source
as `not_sent` to "the sweep" for an agent whose lines and campaigns already held them.

Admin realm: vendor ids appear. Reads only, except `remove_unrecorded`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Literal
from uuid import UUID

from calevate_shared.engine import VoiceEngine
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.kb import service as kb_service
from apps.api.kb.service import KbTarget

log = get_logger(__name__)

Verdict = Literal["held", "missing", "not_sent", "not_ours"]
HolderKind = Literal["agent", "arm", "test_copy", "line", "campaign"]

#: The most rows one agent's list returns, each query read with this LIMIT. A client's
#: knowledge is a few dozen items; past this the list is cut, never unbounded.
MAX_ITEMS: Final = 500
#: The most holders read, each one a vendor round trip.
MAX_HOLDERS: Final = 20


@dataclass(frozen=True, slots=True)
class KnowledgeHolder:
    """One engine agent carrying this agent's work, as the operator's list names it."""

    kind: HolderKind
    #: The arm's, line's or campaign's id; None for the agent's own and its test copy.
    id: UUID | None
    name: str
    target: KbTarget


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
    #: Which engine agent the row is about; None when nothing holds the agent's work.
    holder: KnowledgeHolder | None = None


@dataclass(frozen=True, slots=True)
class AgentKnowledge:
    agent_id: UUID
    #: False when nothing holds the agent's work yet, or a holder's listing could not be
    #: read: those verdicts are then from our rows alone, and `held`/`missing` are not told
    #: apart.
    listed: bool
    items: list[AgentKnowledgeItem]


#: One holder's claims, keyed as `kb/service._HOLDER` keys them.
_HOLDER_SQL: Final = (
    "r.agent_id = :aid AND r.variant_id IS NOT DISTINCT FROM CAST(:vid AS uuid) "
    "AND r.test_copy = :copy AND r.inbound_line_id IS NOT DISTINCT FROM CAST(:lid AS uuid) "
    "AND r.campaign_id IS NOT DISTINCT FROM CAST(:camp AS uuid)"
)

_RECORDED_SQL: Final = (
    "SELECT r.source_id, r.engine_kb_ref, s.name, s.is_active, "
    "coalesce(u.source_kind, s.kind), u.ingest_status, u.ingest_detail "
    "FROM engine_kb_routes r JOIN kb_sources s ON s.id = r.source_id "
    "LEFT JOIN kb_uploads u ON u.source_id = s.id "
    f"WHERE s.tenant_id = :tid AND {_HOLDER_SQL} ORDER BY s.name, r.source_id LIMIT :cap"
)

_UNSENT_SQL: Final = (
    "SELECT s.id, s.name, coalesce(u.source_kind, s.kind), u.ingest_status, u.ingest_detail, "
    "u.read_state, u.read_detail FROM kb_sources s "
    "LEFT JOIN kb_uploads u ON u.source_id = s.id "
    "WHERE s.tenant_id = :tid AND s.is_active = true AND NOT EXISTS ("
    f"SELECT 1 FROM engine_kb_routes r WHERE r.source_id = s.id AND {_HOLDER_SQL}) "
    "ORDER BY s.name, s.id LIMIT :cap"
)

_NAMES_SQL: Final = (
    "SELECT id, name FROM inbound_lines WHERE id = ANY(:ids) "
    "UNION ALL SELECT id, name FROM campaigns WHERE id = ANY(:ids)"
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
        "aid": target.agent_id,
        "vid": target.variant_id,
        "copy": target.test_copy,
        "lid": target.inbound_line_id,
        "camp": target.campaign_id,
        "cap": MAX_ITEMS,
    }


async def _assert_agent(session: AsyncSession, *, tenant_id: UUID, agent_id: UUID) -> None:
    found = (
        await session.execute(
            text(
                "SELECT 1 FROM agents WHERE id = :aid AND tenant_id = :tid AND deleted_at IS NULL"
            ),
            {"aid": agent_id, "tid": tenant_id},
        )
    ).first()
    if found is None:
        raise ProblemError.not_found("Agent")


async def knowledge_holders(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID
) -> list[KnowledgeHolder]:
    """The engine agents the client's knowledge is fanned out to for this agent, in the
    fan-out's own order (`kb/service.vendor_targets`), at most `MAX_HOLDERS`."""
    targets = [
        t
        for t in await kb_service.vendor_targets(session, tenant_id=tenant_id)
        if t.agent_id == agent_id
    ][:MAX_HOLDERS]
    job_ids = [t.inbound_line_id or t.campaign_id for t in targets]
    ids = [i for i in job_ids if i is not None]
    names: dict[UUID, str] = {}
    if ids:
        rows = (await session.execute(text(_NAMES_SQL), {"ids": ids})).all()
        names = {UUID(str(row[0])): str(row[1]) for row in rows}
    out: list[KnowledgeHolder] = []
    for target in targets:
        if target.inbound_line_id is not None:
            out.append(
                KnowledgeHolder(
                    "line",
                    target.inbound_line_id,
                    names.get(target.inbound_line_id, "Inbound line"),
                    target,
                )
            )
        elif target.campaign_id is not None:
            out.append(
                KnowledgeHolder(
                    "campaign",
                    target.campaign_id,
                    names.get(target.campaign_id, "Campaign"),
                    target,
                )
            )
        elif target.variant_id is not None:
            out.append(KnowledgeHolder("arm", target.variant_id, "Script test arm", target))
        elif target.test_copy:
            out.append(KnowledgeHolder("test_copy", None, "Test copy", target))
        else:
            out.append(KnowledgeHolder("agent", None, "The agent's own", target))
    return out


async def _listing(engine: VoiceEngine, ref: str | None) -> list[str] | None:
    if ref is None or not engine.capabilities.has("knowledge_base"):
        return None
    try:
        return list(await engine.list_kb(ref))
    except ProblemError as exc:
        log.warning("kb_agent_view_unlisted", extra={"code": exc.code})
        return None


def _unsent_item(row: Any, holder: KnowledgeHolder | None) -> AgentKnowledgeItem:
    return AgentKnowledgeItem(
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
        holder=holder,
    )


async def _holder_items(
    session: AsyncSession, engine: VoiceEngine, *, tenant_id: UUID, holder: KnowledgeHolder
) -> tuple[bool, list[AgentKnowledgeItem]]:
    """(listed, rows) for one holder."""
    target = holder.target
    params = _params(tenant_id, target)
    listing = await _listing(engine, target.engine_ref)
    listed = set(listing or ())
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
                holder=holder,
            )
        )
    every_recorded = await kb_service.recorded_handles_of_agent(
        session,
        target.agent_id,
        target.variant_id,
        test_copy=target.test_copy,
        inbound_line_id=target.inbound_line_id,
        campaign_id=target.campaign_id,
    )
    for handle in sorted(every_recorded - recorded):
        recorded.add(handle)
        items.append(
            AgentKnowledgeItem(
                verdict="held" if listing is None or handle in listed else "missing",
                handle=handle,
                name="Business facts",
                kind="facts",
                holder=holder,
            )
        )
    items.extend(
        _unsent_item(row, holder) for row in (await session.execute(text(_UNSENT_SQL), params))
    )
    items.extend(
        AgentKnowledgeItem(verdict="not_ours", handle=handle, holder=holder)
        for handle in (listing or [])
        if handle not in recorded
    )
    return listing is not None, items


async def agent_knowledge(
    session: AsyncSession, engine: VoiceEngine, *, tenant_id: UUID, agent_id: UUID
) -> AgentKnowledge:
    """Everything this agent's engine agents hold or should hold, in the caller's tenant
    session. With none holding its work, every live source is listed `not_sent`."""
    await _assert_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    holders = await knowledge_holders(session, tenant_id=tenant_id, agent_id=agent_id)
    if not holders:
        nobody = KbTarget(agent_id=agent_id, engine_ref="")
        rows = (await session.execute(text(_UNSENT_SQL), _params(tenant_id, nobody))).all()
        return AgentKnowledge(
            agent_id=agent_id, listed=False, items=[_unsent_item(row, None) for row in rows]
        )
    listed_all = True
    items: list[AgentKnowledgeItem] = []
    for holder in holders:
        listed, held = await _holder_items(session, engine, tenant_id=tenant_id, holder=holder)
        listed_all = listed_all and listed
        items.extend(held)
    return AgentKnowledge(agent_id=agent_id, listed=listed_all, items=items[:MAX_ITEMS])


async def remove_unrecorded(
    session: AsyncSession, engine: VoiceEngine, *, tenant_id: UUID, agent_id: UUID, handle: str
) -> None:
    """Delete, on the platform, a document one of this agent's engine agents holds that no row
    of ours names.

    Under the tenant's knowledge lock, so a publish that is attaching this very copy and has
    not yet recorded it cannot be undercut: once the lock is ours, a handle still unrecorded
    is one no publish of ours made. A handle we record on that holder is refused, because
    removing it here would leave our rows promising the client knowledge it no longer has.
    """
    await kb_service.lock_tenant_knowledge(session, tenant_id=tenant_id)
    await _assert_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    for holder in await knowledge_holders(session, tenant_id=tenant_id, agent_id=agent_id):
        target = holder.target
        listing = await _listing(engine, target.engine_ref)
        if listing is None or handle not in listing:
            continue
        recorded = await kb_service.recorded_handles_of_agent(
            session,
            target.agent_id,
            target.variant_id,
            test_copy=target.test_copy,
            inbound_line_id=target.inbound_line_id,
            campaign_id=target.campaign_id,
        )
        if handle in recorded:
            raise ProblemError.conflict(
                "kb_document_is_ours",
                "That document is the client's own knowledge.",
                remediation="Remove it from the client's What your agents know page instead.",
            )
        await engine.detach_kb(target.engine_ref, handle)
        log.info(
            "kb_unrecorded_document_removed",
            extra={"agent_id": str(agent_id), "holder": holder.kind},
        )
        return
    raise ProblemError.not_found("Agent document")


__all__ = [
    "AgentKnowledge",
    "AgentKnowledgeItem",
    "HolderKind",
    "KnowledgeHolder",
    "Verdict",
    "agent_knowledge",
    "knowledge_holders",
    "remove_unrecorded",
]
