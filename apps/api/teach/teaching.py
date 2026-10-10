"""The teach box: one input for text, a photo or file, or a voice note, sorted by AI into
facts and rules for the owner to review (founder decision 9, 10 Oct 2026).

The flow, one `kb_teachings` row per use:

    text   -> queued -> sorting -> ready -> saved | discarded
    photo  -> queued -> reading -> sorting -> ready -> ...
    voice  -> queued -> reading -> heard (the owner checks the words) -> queued -> sorting ...

Reading and sorting happen in a worker (`apps/workers/kb_teach.py`), never in a request
handler. Saving is the owner's act: facts go into the business's knowledge at once
(`teach/facts.py`, every agent), rules go to the chosen agent's script as pending
'anytime' rules (`teach/rules.py`).

Nothing is refused for lack of AI: when the AI allowance is used up or no model can answer,
the worker returns the owner's words unsorted, line by line, for them to mark as facts or
rules themselves.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.reliability.service import enqueue_outbox
from apps.api.teach import facts as fact_store
from apps.api.teach import pinned as pinned_store
from apps.api.teach import rules as rule_store
from apps.api.teach.models import MAX_TEACH_WORDS

#: The worker job (`apps/workers/kb_teach.JOB_NAME`).
TEACH_JOB: Final = "run_kb_teaching"

#: `usage_events.meta.feature` for sorting a teaching. Counted against the client's AI
#: allowance: the owner pressed the button.
ASSIST_FEATURE_KB_TEACH: Final = "kb_teach"

#: The REST speech-to-text endpoint takes clips under 30 seconds (sarvamai 0.1.28,
#: `speech_to_text/raw_client.py:50`), so the recorder stops at 30 s and this bounds a clip
#: of that length in any of the browser codecs with room to spare.
MAX_VOICE_BYTES: Final = 3 * 1024 * 1024
VOICE_CONTENT_TYPES: Final = frozenset(
    {"audio/webm", "audio/ogg", "audio/mpeg", "audio/mp4", "audio/wav", "audio/x-wav", "audio/aac"}
)
MIN_TEACH_CHARS: Final = 3

ItemKind = Literal["fact", "rule"]
InputKind = Literal["text", "photo", "file", "voice"]


@dataclass(frozen=True, slots=True)
class TeachItem:
    kind: ItemKind
    text: str
    #: A fact the owner pinned in review: it goes into every agent's instructions.
    pinned: bool = False


@dataclass(frozen=True, slots=True)
class Teaching:
    id: UUID
    status: str
    input_kind: str
    words: str | None
    items: list[TeachItem]
    agent_id: UUID | None
    gap_id: UUID | None
    disclosure: str | None
    error_code: str | None
    created_at: datetime


_COLUMNS = (
    "id, status, input_kind, words, items, agent_id, gap_id, disclosure, error_code, created_at"
)


def _items_of(raw: Any) -> list[TeachItem]:
    out: list[TeachItem] = []
    for item in raw or []:
        if isinstance(item, dict) and item.get("kind") in ("fact", "rule"):
            value = str(item.get("text") or "").strip()
            if value:
                out.append(
                    TeachItem(kind=item["kind"], text=value, pinned=bool(item.get("pinned")))
                )
    return out


def _teaching_of(row: Any) -> Teaching:
    return Teaching(
        id=row.id,
        status=str(row.status),
        input_kind=str(row.input_kind),
        words=row.words,
        items=_items_of(row.items),
        agent_id=row.agent_id,
        gap_id=row.gap_id,
        disclosure=row.disclosure,
        error_code=row.error_code,
        created_at=row.created_at,
    )


async def get_teaching(session: AsyncSession, teaching_id: UUID) -> Teaching:
    row = (
        await session.execute(
            text(f"SELECT {_COLUMNS} FROM kb_teachings WHERE id = :id"), {"id": teaching_id}
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Teaching")
    return _teaching_of(row)


def clean_words(words: str) -> str:
    cleaned = words.strip()
    if len(cleaned) < MIN_TEACH_CHARS:
        raise ProblemError.business_rule(
            "teach_too_little", "Write, say or photograph what you want your agents to know."
        )
    if len(cleaned) > MAX_TEACH_WORDS:
        raise ProblemError.business_rule(
            "teach_too_long",
            f"Teach at most {MAX_TEACH_WORDS:,} characters at a time.",
            remediation="Split it into smaller pieces, or add it as a document under Files.",
        )
    return cleaned


async def _gap_of(session: AsyncSession, gap_id: UUID | None) -> UUID | None:
    if gap_id is None:
        return None
    found = (
        await session.execute(text("SELECT id FROM knowledge_gaps WHERE id = :id"), {"id": gap_id})
    ).scalar()
    if found is None:
        raise ProblemError.not_found("Question to answer")
    return gap_id


async def start_teaching(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    input_kind: InputKind,
    words: str | None,
    object_key: str | None = None,
    content_type: str | None = None,
    filename: str | None = None,
    gap_id: UUID | None = None,
    teaching_id: UUID | None = None,
    requested_by: UUID | None,
) -> Teaching:
    """Record a teaching and queue the worker, in the caller's transaction."""
    gap = await _gap_of(session, gap_id)
    row = (
        await session.execute(
            text(
                "INSERT INTO kb_teachings (id, tenant_id, gap_id, input_kind, status, words, "
                "object_key, content_type, filename, requested_by, created_at, updated_at) "
                "VALUES (:id, :tid, :gap, :kind, 'queued', :words, :key, :ctype, :fname, :by, "
                f"now(), now()) RETURNING {_COLUMNS}"
            ),
            {
                "id": teaching_id or uuid7(),
                "tid": tenant_id,
                "gap": gap,
                "kind": input_kind,
                "words": words,
                "key": object_key,
                "ctype": content_type,
                "fname": filename,
                "by": requested_by,
            },
        )
    ).one()
    await enqueue_outbox(
        session, job=TEACH_JOB, payload={"tenant_id": str(tenant_id), "teaching_id": str(row.id)}
    )
    return _teaching_of(row)


async def confirm_words(
    session: AsyncSession, *, tenant_id: UUID, teaching_id: UUID, words: str
) -> Teaching:
    """The owner checked (and may have corrected) the words heard in a voice note; sort them."""
    cleaned = clean_words(words)
    row = (
        await session.execute(
            text(
                "UPDATE kb_teachings SET words = :words, status = 'queued', updated_at = now() "
                f"WHERE id = :id AND status = 'heard' RETURNING {_COLUMNS}"
            ),
            {"id": teaching_id, "words": cleaned},
        )
    ).first()
    if row is None:
        await get_teaching(session, teaching_id)  # 404 when it is not ours
        raise ProblemError.conflict(
            "teaching_not_waiting_for_words", "These words were already confirmed."
        )
    await enqueue_outbox(
        session, job=TEACH_JOB, payload={"tenant_id": str(tenant_id), "teaching_id": str(row.id)}
    )
    return _teaching_of(row)


async def discard(session: AsyncSession, teaching_id: UUID) -> Teaching:
    row = (
        await session.execute(
            text(
                "UPDATE kb_teachings SET status = 'discarded', updated_at = now() "
                "WHERE id = :id AND status NOT IN ('saved', 'discarded') "
                f"RETURNING {_COLUMNS}"
            ),
            {"id": teaching_id},
        )
    ).first()
    if row is None:
        return await get_teaching(session, teaching_id)
    return _teaching_of(row)


@dataclass(frozen=True, slots=True)
class Saved:
    facts_added: int
    rules_added: int
    agent_id: UUID | None


async def _agent_exists(session: AsyncSession, agent_id: UUID) -> None:
    found = (
        await session.execute(
            text("SELECT 1 FROM agents WHERE id = :id AND deleted_at IS NULL"), {"id": agent_id}
        )
    ).scalar()
    if found is None:
        raise ProblemError.not_found("Agent")


async def save(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    teaching_id: UUID,
    items: list[TeachItem],
    agent_id: UUID | None,
    saved_by: UUID | None,
    client_user_id: UUID | None,
    auto_approve: bool,
) -> Saved:
    """Keep the reviewed items: facts into knowledge now, rules to one agent's script."""
    claimed = (
        await session.execute(
            text(
                "UPDATE kb_teachings SET status = 'saved', agent_id = :agent, "
                "items = CAST(:items AS jsonb), completed_at = now(), updated_at = now() "
                "WHERE id = :id AND status = 'ready' RETURNING gap_id"
            ),
            {
                "id": teaching_id,
                "agent": agent_id,
                "items": _items_json(items),
            },
        )
    ).first()
    if claimed is None:
        current = await get_teaching(session, teaching_id)
        raise ProblemError.conflict(
            "teaching_not_ready",
            "This was already saved."
            if current.status == "saved"
            else "This is not ready to save yet.",
        )
    gap_id: UUID | None = claimed[0]
    fact_texts = [item.text for item in items if item.kind == "fact" and not item.pinned]
    pinned_texts = [item.text for item in items if item.kind == "fact" and item.pinned]
    rule_texts = [item.text for item in items if item.kind == "rule"]
    if not fact_texts and not pinned_texts and not rule_texts:
        raise ProblemError.business_rule("teaching_empty", "Keep at least one fact or rule.")
    if rule_texts:
        if agent_id is None:
            raise ProblemError.business_rule(
                "teaching_rule_needs_agent", "Choose which agent the rules are for."
            )
        await _agent_exists(session, agent_id)
    added = await fact_store.add_facts(
        session,
        tenant_id=tenant_id,
        texts=fact_texts,
        origin="call_gap" if gap_id else "taught",
        teaching_id=teaching_id,
        created_by=saved_by,
        auto_approve=auto_approve,
    )
    for value in pinned_texts:
        await pinned_store.add_pinned(
            session,
            tenant_id=tenant_id,
            question=None,
            answer=value,
            origin="call_gap" if gap_id else "taught",
            created_by=saved_by,
            teaching_id=teaching_id,
        )
    rules = (
        await rule_store.propose_rules(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            texts=rule_texts,
            teaching_id=teaching_id,
            created_by=saved_by,
        )
        if agent_id is not None and rule_texts
        else []
    )
    if gap_id is not None:
        await _mark_gap_taught(
            session,
            gap_id,
            answer="\n".join(fact_texts + pinned_texts + rule_texts),
            by=client_user_id,
        )
    return Saved(
        facts_added=len(added) + len(pinned_texts), rules_added=len(rules), agent_id=agent_id
    )


async def _mark_gap_taught(
    session: AsyncSession, gap_id: UUID, *, answer: str, by: UUID | None
) -> None:
    # Only an open gap moves; one dismissed or taught meanwhile keeps its own resolution.
    await session.execute(
        text(
            "UPDATE knowledge_gaps SET status = 'taught', resolution = :answer, "
            "resolved_by = :by, resolved_at = now(), updated_at = now() "
            "WHERE id = :id AND status = 'open'"
        ),
        {"id": gap_id, "answer": answer[:8000], "by": by},
    )


def _items_json(items: list[TeachItem]) -> str:
    import json

    return json.dumps(
        [{"kind": item.kind, "text": item.text, "pinned": item.pinned} for item in items]
    )


__all__ = [
    "ASSIST_FEATURE_KB_TEACH",
    "MAX_VOICE_BYTES",
    "TEACH_JOB",
    "VOICE_CONTENT_TYPES",
    "Saved",
    "TeachItem",
    "Teaching",
    "clean_words",
    "confirm_words",
    "discard",
    "get_teaching",
    "save",
    "start_teaching",
]
