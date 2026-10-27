"""Everything a client gave us to know, as ONE store Pip and the reader can find, open and
search (D-893 L8).

What it is made of is not new: facts and pinned facts (`kb_facts`), typed notes
(`kb_sources` kind `text`), files, photos and links (`kb_uploads`, with the words read into
`kb_documents`), the business profile (`organizations.intake`) and rules waiting for a script
(`agent_rule_proposals`). This module reads them through their own owners' readers where one
exists (`teach.facts`, `kb.uploads`, `tenancy.business_profile`) and gives each a readable
reference — `file:<id>`, `note:<id>`, `fact:<id>` — so a model can name one item without
holding a list of ids.

`agents_use` is the honest half: whether this item's words reach the agents today. A PDF or
a link does only while `kb_send_extracted_files` is on; anything waiting for review, still
being read, or a rule not yet in a script does not.

Reads only, except `rename_source`, which the page's Rename and Pip's `knowledge_rename` both
call. Every query runs in the caller's tenant session (RLS is the tenancy control).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.kb import uploads
from apps.api.kb.models import READ_COPY_KINDS, READ_FAILED, READ_READING
from apps.api.kb.service import (
    _reject_invisible_characters,
    publish_source,
    upload_reaches_agents,
    withdraw_source,
)
from apps.api.teach import facts as fact_store
from apps.api.teach.facts import FACTS_SOURCE_NAME

ItemKind = Literal["pinned_fact", "fact", "note", "file", "photo", "link", "profile", "rule"]
ItemState = Literal[
    "in_use", "not_used_yet", "being_read", "getting_ready", "in_review", "needs_attention",
    "waiting",
]  # fmt: skip

ITEM_KINDS: Final[tuple[str, ...]] = (
    "pinned_fact", "fact", "note", "file", "photo", "link", "profile", "rule",
)  # fmt: skip
ITEM_STATES: Final[tuple[str, ...]] = (
    "in_use", "not_used_yet", "being_read", "getting_ready", "in_review", "needs_attention",
    "waiting",
)  # fmt: skip

#: Items one find returns at most; the store itself is bounded by its sources' ceilings
#: (300 facts, 200 notes, `MAX_UPLOADS_PAGE` uploads, 200 waiting rules).
MAX_FIND: Final = 25
#: Chunks shown per reading page of a document with no page numbers (a link, a note).
CHUNKS_PER_PART: Final = 4
#: Profile lines per reading page.
PROFILE_LINES_PER_PART: Final = 40
#: Hits one search returns at most.
MAX_HITS: Final = 8

_UPLOAD_KINDS_SHOWN: Final[dict[str, ItemKind]] = {"url": "link", "image": "photo"}
_STUCK: Final = ("conversion_unavailable", "conversion_failed", "error")
_REF = re.compile(r"^(pinned_fact|fact|note|file|photo|link|profile|rule)(?::([0-9a-fA-F-]{36}))?$")


@dataclass(frozen=True, slots=True)
class StoreItem:
    ref: str
    kind: ItemKind
    name: str
    state: ItemState
    agents_use: bool
    changed_at: datetime | None
    #: A short fact about the item a person would want: "12 pages", a reading's problem.
    note: str | None = None


@dataclass(frozen=True, slots=True)
class ItemText:
    ref: str
    kind: ItemKind
    name: str
    state: ItemState
    agents_use: bool
    #: Where it came from: the file's name, the page's address, or "typed".
    origin: str
    version: int | None
    #: 1-based reading page and how many there are.
    page: int
    pages: int
    #: The page's sections, each `(label, text)`: "Page 7", "Part 2", or "".
    sections: list[tuple[str, str]]
    note: str | None = None


@dataclass(frozen=True, slots=True)
class StoreHit:
    ref: str | None
    kind: ItemKind
    name: str
    agents_use: bool
    text: str


def item_ref(kind: ItemKind, item_id: UUID | None = None) -> str:
    return kind if item_id is None else f"{kind}:{item_id}"


def is_ref(value: str) -> bool:
    """Is this an item reference (`file:<uuid>`, `profile`) rather than words to look for?"""
    return _REF.match(value.strip()) is not None


def parse_ref(ref: str) -> tuple[ItemKind, UUID | None]:
    """`file:<uuid>` → `("file", UUID)`. A malformed reference is a 404, the answer an id
    nobody minted gets everywhere else."""
    match = _REF.match(ref.strip())
    if match is None or (match.group(1) != "profile" and match.group(2) is None):
        raise ProblemError.not_found("Knowledge item")
    kind: ItemKind = match.group(1)  # type: ignore[assignment]
    return kind, UUID(match.group(2)) if match.group(2) else None


def upload_kind(source_kind: str) -> ItemKind:
    return _UPLOAD_KINDS_SHOWN.get(source_kind, "file")


def _upload_state(row: dict[str, object], *, reaches: bool) -> ItemState:
    if row["ingest_status"] in _STUCK or row["review_state"] == "rejected":
        return "needs_attention"
    if row.get("read_state") == READ_READING:
        return "being_read"
    if row["is_live"]:
        return "in_use" if reaches else "not_used_yet"
    if row["review_state"] == "pending_approval":
        return "in_review"
    return "getting_ready"


def _upload_note(row: dict[str, object]) -> str | None:
    parts: list[str] = []
    if row.get("page_count"):
        parts.append(f"{row['page_count']} pages")
    if row.get("read_state") == READ_FAILED:
        parts.append(f"could not be read: {row.get('read_detail') or 'no words found'}")
    elif row.get("read_detail"):
        parts.append(str(row["read_detail"]))
    return "; ".join(parts) or None


async def _uploads(session: AsyncSession) -> list[StoreItem]:
    items: list[StoreItem] = []
    for row in await uploads.list_uploads(session):
        if row["review_state"] == "archived":
            continue
        reaches = upload_reaches_agents(
            source_kind=str(row["source_kind"]), read_state=row.get("read_state")
        )
        state = _upload_state(row, reaches=reaches)
        kind = upload_kind(str(row["source_kind"]))
        items.append(
            StoreItem(
                ref=item_ref(kind, row["id"]),
                kind=kind,
                name=str(row["name"]),
                state=state,
                agents_use=state == "in_use",
                changed_at=row["updated_at"],
                note=_upload_note(row),
            )
        )
    return items


#: The newest version of every typed note that is not history. A typed note is a `text`
#: source with no upload behind it; the taught facts' own source is listed fact by fact.
#: The newest version of each typed note, one row per name. A note whose newest version is
#: archived and not live was removed (`remove_note`); it stays listed so it can be put back.
_NOTES_SQL = """
SELECT DISTINCT ON (s.name) s.id, s.name, s.status, s.is_active, s.updated_at, s.version,
       (SELECT count(*) FROM kb_documents d WHERE d.source_id = s.id) AS chunks,
       EXISTS (SELECT 1 FROM kb_sources a WHERE a.tenant_id = s.tenant_id AND a.name = s.name
               AND a.approved_at IS NOT NULL) AS restorable
FROM kb_sources s
WHERE s.kind = 'text' AND s.name <> :facts
  AND NOT EXISTS (SELECT 1 FROM kb_uploads u WHERE u.source_id = s.id)
  AND (CAST(:only AS uuid) IS NULL OR s.name = (SELECT n.name FROM kb_sources n WHERE n.id = :only))
ORDER BY s.name, s.version DESC
LIMIT 200
"""

NoteState = Literal["in_use", "in_review", "needs_attention", "getting_ready", "removed"]


@dataclass(frozen=True, slots=True)
class Note:
    """One typed note as the page lists it: its newest version."""

    id: UUID
    name: str
    state: NoteState
    version: int
    chunks: int
    changed_at: datetime
    #: A removed note with an approved version can be put back (`restore_note`).
    restorable: bool


def _note_state(status: str, is_active: bool) -> NoteState:
    if is_active:
        return "in_use"
    if status == "archived":
        return "removed"
    if status == "rejected":
        return "needs_attention"
    if status == "pending_approval":
        return "in_review"
    return "getting_ready"


async def list_notes(session: AsyncSession, *, only: UUID | None = None) -> list[Note]:
    """Every typed note, newest change first, removed ones included; `only` narrows to the
    note any version id belongs to. The taught facts' own source is not a note."""
    rows = (
        await session.execute(text(_NOTES_SQL), {"facts": FACTS_SOURCE_NAME, "only": only})
    ).all()
    notes = [
        Note(
            id=UUID(str(r.id)),
            name=str(r.name),
            state=_note_state(str(r.status), bool(r.is_active)),
            version=int(r.version),
            chunks=int(r.chunks),
            changed_at=r.updated_at,
            restorable=bool(r.restorable),
        )
        for r in rows
    ]
    notes.sort(key=lambda note: note.changed_at, reverse=True)
    return notes


async def read_note(session: AsyncSession, source_id: UUID) -> Note:
    found = await list_notes(session, only=source_id)
    if not found:
        raise ProblemError.not_found("Knowledge note")
    return found[0]


async def _notes(session: AsyncSession) -> list[StoreItem]:
    items: list[StoreItem] = []
    for note in await list_notes(session):
        if note.state == "removed":
            continue  # its versions are kept for a restore, but it is not knowledge
        items.append(
            StoreItem(
                ref=item_ref("note", note.id),
                kind="note",
                name=note.name,
                state=cast(ItemState, note.state),
                agents_use=note.state == "in_use",
                changed_at=note.changed_at,
            )
        )
    return items


def _fact_name(value: str) -> str:
    return value if len(value) <= 80 else f"{value[:77]}…"


async def _facts(session: AsyncSession) -> list[StoreItem]:
    facts_state = await fact_store.facts_state(session)
    items: list[StoreItem] = []
    for fact in await fact_store.list_facts(session):
        if fact.pinned:
            state: ItemState = "in_use"
        else:
            state = {
                "live": "in_use",
                "in_review": "in_review",
                "publishing": "getting_ready",
            }.get(facts_state, "getting_ready")  # type: ignore[assignment]
        kind: ItemKind = "pinned_fact" if fact.pinned else "fact"
        label = f"{fact.question} — {fact.text}" if fact.question else fact.text
        items.append(
            StoreItem(
                ref=item_ref(kind, fact.id),
                kind=kind,
                name=_fact_name(label),
                state=state,
                agents_use=state == "in_use",
                changed_at=fact.created_at,
            )
        )
    return items


async def _profile_lines(session: AsyncSession, tenant_id: UUID) -> list[str]:
    from apps.api.tenancy.business_profile import profile_fact_lines

    return await profile_fact_lines(session, tenant_id=tenant_id)


_RULES_SQL = """
SELECT r.id, r.text, r.created_at, a.name
FROM agent_rule_proposals r JOIN agents a ON a.id = r.agent_id
WHERE r.status = 'pending'
ORDER BY r.created_at DESC
LIMIT 200
"""


async def _rules(session: AsyncSession) -> list[StoreItem]:
    rows = (await session.execute(text(_RULES_SQL))).all()
    return [
        StoreItem(
            ref=item_ref("rule", rule_id),
            kind="rule",
            name=_fact_name(str(rule_text)),
            state="waiting",
            agents_use=False,
            changed_at=created_at,
            note=f"waiting to be added to {agent_name}'s script",
        )
        for rule_id, rule_text, created_at, agent_name in rows
    ]


async def all_items(session: AsyncSession, *, tenant_id: UUID) -> list[StoreItem]:
    """Every item, newest change first."""
    items = [
        *await _facts(session),
        *await _notes(session),
        *await _uploads(session),
        *await _rules(session),
    ]
    if await _profile_lines(session, tenant_id):
        items.append(
            StoreItem(
                ref="profile",
                kind="profile",
                name="Business profile",
                state="in_use",
                agents_use=True,
                changed_at=None,
                note="hours, branches, services, staff and answers from setup",
            )
        )
    items.sort(key=lambda i: i.changed_at.timestamp() if i.changed_at else 0.0, reverse=True)
    return items


async def find_items(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    kinds: list[str] | None = None,
    states: list[str] | None = None,
    contains: str | None = None,
    offset: int = 0,
    limit: int = 10,
) -> tuple[list[StoreItem], int]:
    """A page of items matching every filter, and how many match in all. `contains` is
    matched against the item's name (a fact's words are its name); search the words of a
    document with `search_store`."""
    needle = (contains or "").strip().casefold()
    found = [
        item
        for item in await all_items(session, tenant_id=tenant_id)
        if (not kinds or item.kind in kinds)
        and (not states or item.state in states)
        and (not needle or needle in item.name.casefold())
    ]
    start = max(0, offset)
    return found[start : start + max(1, min(limit, MAX_FIND))], len(found)


# --- open one item -------------------------------------------------------------------


_UPLOAD_SQL = """
SELECT u.id, u.source_id, s.name, u.source_kind, u.ingest_status, s.status, s.is_active,
       s.version, u.original_filename, u.source_url, u.read_state, u.read_detail,
       u.page_count, u.updated_at
FROM kb_uploads u JOIN kb_sources s ON s.id = u.source_id
WHERE u.id = :uid
"""


async def _chunks(session: AsyncSession, source_id: UUID) -> list[tuple[int | None, str]]:
    rows = (
        await session.execute(
            text(
                "SELECT (meta->>'page')::int, content FROM kb_documents "
                "WHERE source_id = :sid ORDER BY idx"
            ),
            {"sid": source_id},
        )
    ).all()
    return [(None if r[0] is None else int(r[0]), str(r[1])) for r in rows]


def _paged(
    chunks: list[tuple[int | None, str]], page: int
) -> tuple[int, int, list[tuple[str, str]]]:
    """Reading pages over a source's chunks: one per PDF page where the chunks carry one,
    else `CHUNKS_PER_PART` chunks a part. Returns (page, pages, sections)."""
    numbered = sorted({p for p, _ in chunks if p is not None})
    if numbered:
        pages = len(numbered)
        page = min(max(1, page), pages)
        wanted = numbered[page - 1]
        body = "\n\n".join(t for p, t in chunks if p == wanted)
        return page, pages, [(f"Page {wanted}", body)]
    pages = max(1, -(-len(chunks) // CHUNKS_PER_PART))
    page = min(max(1, page), pages)
    part = chunks[(page - 1) * CHUNKS_PER_PART : page * CHUNKS_PER_PART]
    label = f"Part {page}" if pages > 1 else ""
    return page, pages, [(label, "\n\n".join(t for _, t in part))] if part else []


async def read_upload_text(session: AsyncSession, upload_id: UUID, *, page: int = 1) -> ItemText:
    """One file, photo or link: the words we hold for it, one reading page at a time."""
    row = (await session.execute(text(_UPLOAD_SQL), {"uid": upload_id})).first()
    if row is None:
        raise ProblemError.not_found("Knowledge upload")
    shaped = {
        "ingest_status": row[4],
        "review_state": row[5],
        "is_live": row[6],
        "read_state": row[10],
        "read_detail": row[11],
        "page_count": row[12],
    }
    reaches = upload_reaches_agents(source_kind=str(row[3]), read_state=row[10])
    state = _upload_state(shaped, reaches=reaches)
    shown_page, pages, sections = _paged(await _chunks(session, UUID(str(row[1]))), page)
    kind = upload_kind(str(row[3]))
    return ItemText(
        ref=item_ref(kind, UUID(str(row[0]))),
        kind=kind,
        name=str(row[2]),
        state=state,
        agents_use=state == "in_use",
        origin=str(row[9] if kind == "link" else (row[8] or "file")),
        version=int(row[7]),
        page=shown_page,
        pages=pages,
        sections=sections,
        note=_upload_note(shaped),
    )


async def _note_text(session: AsyncSession, source_id: UUID, page: int) -> ItemText:
    row = (
        await session.execute(
            text(
                "SELECT id, name, status, is_active, version FROM kb_sources "
                "WHERE id = :sid AND kind = 'text' "
                "AND NOT EXISTS (SELECT 1 FROM kb_uploads u WHERE u.source_id = kb_sources.id)"
            ),
            {"sid": source_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Knowledge note")
    found = _note_state(str(row[2]), bool(row[3]))
    # `ItemState` has no "removed": a removed version opened by its ref reads as not live.
    state: ItemState = "getting_ready" if found == "removed" else found
    shown_page, pages, sections = _paged(await _chunks(session, source_id), page)
    return ItemText(
        ref=item_ref("note", source_id),
        kind="note",
        name=str(row[1]),
        state=state,
        agents_use=state == "in_use",
        origin="typed",
        version=int(row[4]),
        page=shown_page,
        pages=pages,
        sections=sections,
    )


async def read_item(session: AsyncSession, *, tenant_id: UUID, ref: str, page: int = 1) -> ItemText:
    """Open one item by its reference. A 404 for anything this tenant does not hold."""
    kind, item_id = parse_ref(ref)
    if kind in ("file", "photo", "link"):
        assert item_id is not None
        return await read_upload_text(session, item_id, page=page)
    if kind == "note":
        assert item_id is not None
        return await _note_text(session, item_id, page)
    if kind == "profile":
        lines = await _profile_lines(session, tenant_id)
        if not lines:
            raise ProblemError.not_found("Business profile")
        pages = max(1, -(-len(lines) // PROFILE_LINES_PER_PART))
        page = min(max(1, page), pages)
        part = lines[(page - 1) * PROFILE_LINES_PER_PART : page * PROFILE_LINES_PER_PART]
        return ItemText(
            ref="profile",
            kind="profile",
            name="Business profile",
            state="in_use",
            agents_use=True,
            origin="setup",
            version=None,
            page=page,
            pages=pages,
            sections=[("", "\n".join(part))],
        )
    assert item_id is not None
    for item in await (_rules(session) if kind == "rule" else _facts(session)):
        if item.ref == item_ref(kind, item_id):
            body = await _single_text(session, kind, item_id)
            return ItemText(
                ref=item.ref,
                kind=item.kind,
                name=item.name,
                state=item.state,
                agents_use=item.agents_use,
                origin="typed",
                version=None,
                page=1,
                pages=1,
                sections=[("", body)],
                note=item.note,
            )
    raise ProblemError.not_found("Knowledge item")


async def _single_text(session: AsyncSession, kind: ItemKind, item_id: UUID) -> str:
    if kind == "rule":
        sql = "SELECT text, NULL FROM agent_rule_proposals WHERE id = :id"
    else:
        sql = "SELECT text, question FROM kb_facts WHERE id = :id AND removed_at IS NULL"
    row = (await session.execute(text(sql), {"id": item_id})).first()
    if row is None:
        raise ProblemError.not_found("Knowledge item")
    return f"{row[1]}\n{row[0]}" if row[1] else str(row[0])


# --- search inside the stored words ------------------------------------------------


#: Not-yet-live versions (and, when no search store serves this deployment, every current
#: version) matched by Postgres full-text search on the words themselves. A query, not an
#: index: the retrieval projection (`kb_chunks`) holds only what is published, by design.
#: ANY of the question's words matches (`&` turned into `|`) and the rank orders by how many:
#: an owner asks "thali price" of a menu that says "thali costs", and AND would find nothing.
_TEXT_SEARCH_SQL = """
SELECT d.source_id, s.name, d.content,
       ts_rank_cd(to_tsvector('english', d.content), q) AS rank
FROM kb_documents d JOIN kb_sources s ON s.id = d.source_id,
     CAST(NULLIF(replace(CAST(plainto_tsquery('english', :q) AS text), '&', '|'), '')
          AS tsquery) q
WHERE s.status NOT IN ('archived', 'rejected') AND s.name <> :facts
  AND (CAST(:all_current AS boolean) OR NOT s.is_active)
  AND to_tsvector('english', d.content) @@ q
ORDER BY rank DESC, d.id
LIMIT :k
"""

_SOURCE_ITEM_SQL = """
SELECT s.id, s.is_active, u.id, u.source_kind, u.read_state
FROM kb_sources s LEFT JOIN kb_uploads u ON u.source_id = s.id
WHERE s.id = ANY(:ids)
"""


async def _source_items(
    session: AsyncSession, source_ids: list[UUID]
) -> dict[UUID, tuple[str | None, ItemKind, bool]]:
    """source id → (item ref, kind, agents use it) for the sources a search hit."""
    rows = (await session.execute(text(_SOURCE_ITEM_SQL), {"ids": source_ids})).all()
    found: dict[UUID, tuple[str | None, ItemKind, bool]] = {}
    for source_id, is_active, upload_id, source_kind, read_state in rows:
        if upload_id is None:
            found[UUID(str(source_id))] = (
                item_ref("note", UUID(str(source_id))),
                "note",
                bool(is_active),
            )
            continue
        kind = upload_kind(str(source_kind))
        reaches = upload_reaches_agents(source_kind=str(source_kind), read_state=read_state)
        found[UUID(str(source_id))] = (
            item_ref(kind, UUID(str(upload_id))),
            kind,
            bool(is_active) and reaches,
        )
    return found


def _words(value: str) -> set[str]:
    return {w for w in re.findall(r"\w+", value.casefold()) if len(w) > 2}


async def search_store(
    session: AsyncSession, *, tenant_id: UUID, question: str, limit: int = MAX_HITS
) -> list[StoreHit]:
    """Search the words of everything the client gave us, each hit naming its item and
    whether the agents use it.

    Published documents and notes through the retrieval port at t3 (`retrieval.service.
    look_up`, pgvector over `kb_chunks` — no second index); not-yet-live versions, and
    everything when no search store serves this deployment, by full-text search over
    `kb_documents`; facts, the profile and waiting rules, which are short, by shared words.
    """
    from apps.api.retrieval.service import look_up

    limit = max(1, min(limit, MAX_HITS))
    hits: list[StoreHit] = []
    searched_live = False
    if get_settings().retrieval_provider != "compiled-facts":
        _, result = await look_up(
            session, tenant_id=tenant_id, question=question, k=limit, tier="t3"
        )
        searched_live = result.served_tier == "t3"
        if searched_live:
            ids = [p.provenance.source_id for p in result.passages if p.provenance.source_id]
            items = await _source_items(session, [i for i in ids if i is not None])
            for passage in result.passages:
                sid = passage.provenance.source_id
                ref, kind, used = (
                    items.get(sid, (None, "fact", True)) if sid else (None, "fact", True)
                )
                if passage.provenance.label == FACTS_SOURCE_NAME:
                    ref, kind = None, "fact"
                hits.append(
                    StoreHit(
                        ref=ref,
                        kind=kind,
                        name=passage.provenance.label,
                        agents_use=used,
                        text=passage.text,
                    )
                )
    rows = (
        await session.execute(
            text(_TEXT_SEARCH_SQL),
            {
                "q": question,
                "facts": FACTS_SOURCE_NAME,
                "all_current": not searched_live,
                "k": limit,
            },
        )
    ).all()
    items = await _source_items(session, [UUID(str(r[0])) for r in rows])
    for source_id, name, content, _rank in rows:
        ref, kind, used = items.get(UUID(str(source_id)), (None, "note", False))
        if any(h.ref == ref and h.text == content for h in hits):
            continue
        hits.append(
            StoreHit(ref=ref, kind=kind, name=str(name), agents_use=used, text=str(content))
        )

    asked = _words(question)
    if asked:
        for item in [*await _facts(session), *await _rules(session)]:
            item_id = parse_ref(item.ref)[1]
            if item_id is not None and asked & _words(item.name):
                body = await _single_text(session, item.kind, item_id)
                hits.append(
                    StoreHit(
                        ref=item.ref,
                        kind=item.kind,
                        name=item.name,
                        agents_use=item.agents_use,
                        text=body,
                    )
                )
        for line in await _profile_lines(session, tenant_id):
            if asked & _words(line):
                hits.append(
                    StoreHit(
                        ref="profile",
                        kind="profile",
                        name="Business profile",
                        agents_use=True,
                        text=line,
                    )
                )
    return hits[:limit]


async def undelivered_source_ids(session: AsyncSession) -> set[UUID]:
    """Live sources whose words the agents do not get: PDFs and links while the switch is
    off, or whose reading did not finish. `search_knowledge` leaves their passages out of
    "what my agents tell callers"."""
    rows = (
        await session.execute(
            text(
                "SELECT s.id, u.source_kind, u.read_state FROM kb_sources s "
                "JOIN kb_uploads u ON u.source_id = s.id "
                "WHERE s.is_active AND u.source_kind = ANY(:kinds)"
            ),
            {"kinds": list(READ_COPY_KINDS)},
        )
    ).all()
    return {
        UUID(str(r[0]))
        for r in rows
        if not upload_reaches_agents(source_kind=str(r[1]), read_state=r[2])
    }


# --- rename --------------------------------------------------------------------------


MAX_NAME_CHARS: Final = 120


async def rename_source(
    session: AsyncSession, *, tenant_id: UUID, source_id: UUID, name: str
) -> tuple[str, str]:
    """Rename a file, photo, link or note: every version of it, so its history stays one
    item. Returns `(old name, new name)`.

    The name is the version sequence's key (`insert_source_version` numbers versions per
    name), so a name another item already uses is refused rather than merging two items'
    histories, and the taught facts' own source keeps its name. It changes a heading, not
    an answer: the agents' copies keep the old title until their next publish.
    """
    cleaned = " ".join(name.split())
    if len(cleaned) < 2 or len(cleaned) > MAX_NAME_CHARS:
        raise ProblemError.business_rule(
            "kb_name_length", f"A name is 2 to {MAX_NAME_CHARS} characters."
        )
    _reject_invisible_characters(cleaned, field="name")
    current = (
        await session.execute(
            text("SELECT name FROM kb_sources WHERE id = :sid"), {"sid": source_id}
        )
    ).scalar()
    if current is None:
        raise ProblemError.not_found("Knowledge source")
    old = str(current)
    if old == FACTS_SOURCE_NAME:
        raise ProblemError.business_rule(
            "kb_facts_source_fixed", "Your taught facts keep their own name."
        )
    if cleaned == old:
        return old, old
    # The same lock a new version takes, on both names, so a submission cannot mint a
    # version under either name while the rename moves the history.
    for key in sorted({old, cleaned}):
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"kb:submit:{tenant_id}:{key}"},
        )
    # The name was read before the locks: a rename that committed while we waited would
    # leave the UPDATE below matching no row and this one reporting a rename it never made.
    still = (
        await session.execute(
            text("SELECT name FROM kb_sources WHERE id = :sid"), {"sid": source_id}
        )
    ).scalar()
    if still != old:
        raise ProblemError.conflict(
            "kb_renamed_meanwhile",
            "This item was renamed by someone else just now.",
            remediation="Reload it and choose the name again.",
        )
    taken = (
        await session.execute(
            text("SELECT 1 FROM kb_sources WHERE tenant_id = :tid AND name = :name LIMIT 1"),
            {"tid": tenant_id, "name": cleaned},
        )
    ).first()
    if taken is not None or cleaned == FACTS_SOURCE_NAME:
        raise ProblemError.conflict(
            "kb_name_taken",
            "Something else in your knowledge already has that name.",
            remediation="Choose a different name.",
        )
    await session.execute(
        text(
            "UPDATE kb_sources SET name = :new, updated_at = now() "
            "WHERE tenant_id = :tid AND name = :old"
        ),
        {"new": cleaned, "old": old, "tid": tenant_id},
    )
    await session.execute(
        text(
            "UPDATE kb_documents SET title = :new WHERE source_id IN "
            "(SELECT id FROM kb_sources WHERE tenant_id = :tid AND name = :new)"
        ),
        {"new": cleaned, "tid": tenant_id},
    )
    return old, cleaned


# --- remove and restore a typed note -------------------------------------------------


async def _note_name(session: AsyncSession, source_id: UUID) -> str:
    name = (
        await session.execute(
            text(
                "SELECT name FROM kb_sources WHERE id = :sid AND kind = 'text' "
                "AND NOT EXISTS (SELECT 1 FROM kb_uploads u WHERE u.source_id = kb_sources.id)"
            ),
            {"sid": source_id},
        )
    ).scalar()
    if name is None:
        raise ProblemError.not_found("Knowledge note")
    if name == FACTS_SOURCE_NAME:
        raise ProblemError.business_rule(
            "kb_facts_source_fixed", "Your taught facts are removed one by one."
        )
    return str(name)


async def remove_note(session: AsyncSession, *, tenant_id: UUID, source_id: UUID) -> int:
    """Take a typed note off every agent and out of the list, KEEPING its versions.

    `withdraw_source` on every version that is not history yet: the live one comes off the
    agents (vendor copies withdrawn, facts block recompiled), one waiting for review stops
    waiting. Nothing is deleted, so `restore_note` can put the newest approved version
    back; the retention sweep removes archived versions on its own clock. Returns the
    versions archived.
    """
    name = await _note_name(session, source_id)
    versions = (
        await session.execute(
            text(
                "SELECT id FROM kb_sources WHERE tenant_id = :tid AND name = :name "
                "AND status <> 'archived' ORDER BY version"
            ),
            {"tid": tenant_id, "name": name},
        )
    ).scalars()
    archived = 0
    for version_id in list(versions):
        await withdraw_source(session, tenant_id=tenant_id, source_id=UUID(str(version_id)))
        archived += 1
    return archived


async def restore_note(session: AsyncSession, *, tenant_id: UUID, source_id: UUID) -> int:
    """Put a removed note back: publish its newest approved version (FLOWS §7's rollback,
    `publish_source` on an archived row). Returns the version made live."""
    name = await _note_name(session, source_id)
    newest = (
        await session.execute(
            text(
                "SELECT id, status FROM kb_sources WHERE tenant_id = :tid AND name = :name "
                "AND approved_at IS NOT NULL ORDER BY version DESC LIMIT 1"
            ),
            {"tid": tenant_id, "name": name},
        )
    ).first()
    if newest is None:
        raise ProblemError.business_rule(
            "kb_note_not_restorable",
            "There is no approved version of that note to put back.",
            remediation="Write the note again.",
        )
    return await publish_source(session, tenant_id=tenant_id, source_id=UUID(str(newest[0])))


__all__ = [
    "ITEM_KINDS",
    "ITEM_STATES",
    "MAX_FIND",
    "MAX_HITS",
    "ItemKind",
    "ItemState",
    "ItemText",
    "Note",
    "NoteState",
    "StoreHit",
    "StoreItem",
    "all_items",
    "find_items",
    "item_ref",
    "list_notes",
    "parse_ref",
    "read_item",
    "read_note",
    "read_upload_text",
    "remove_note",
    "rename_source",
    "restore_note",
    "search_store",
    "undelivered_source_ids",
    "upload_kind",
    "upload_reaches_agents",
]
