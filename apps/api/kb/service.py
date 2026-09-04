"""KB ingestion, approval and publish (FLOWS §7).

    client submits TEXT → chunk → PREVIEW → admin approves → version bump →
    engine KB sync → T0 recompilation → live.   Rollback = reactivate the prior version.

"TEXT", and only text: `SUPPORTED_SUBMISSION_KINDS` below refuses a document or a URL by
name rather than accepting one and quietly chunking whatever was pasted beside it. There
is no verification step after `live` either, and FLOWS §7 now says why — we cannot ask the
engine's knowledge base a question, so "3 canned questions answered from new content" is a
live PSTN call (pilot gate 8), never a step this function could run.

The approval gate is the point. A client editing what their agent says is a client
editing a legal instrument — the agent speaks on their behalf under their PE
registration — so a human sees the chunks before they reach the engine. D-28 keeps
that gate ours no matter which vector provider wins the bake-off.

Chunking is paragraph-aware with a size cap rather than a fixed window: KB answers are
read aloud, and a chunk cut mid-sentence becomes a sentence the agent says badly.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any
from uuid import UUID

from calevate_shared.engine import AgentConfig, KBSourceRef, VoiceEngine
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.t0 import KnowledgeFact, recompile_t0
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.db.ownership import assert_visible
from apps.api.db.result import rowcount_of
from apps.api.db.transition import transition_status
from apps.api.engine import get_engine, require_capability
from apps.api.kb.models import KB_STATUSES
from apps.api.kb.pdf_render import (
    ApprovedChunk,
    KnowledgePdfError,
    RenderedKnowledgePdf,
    render_knowledge_pdf,
)

log = get_logger(__name__)

# ~700 characters is roughly 15-20 seconds of spoken Telugu — long enough to answer a
# question, short enough that retrieval returns one idea rather than a page.
MAX_CHUNK_CHARS = 700
MIN_CHUNK_CHARS = 80

#: The submission kinds this module can actually turn into chunks.
#:
#: `kb_sources.kind` allows four (`models.KB_KINDS`) and the API advertised three, but
#: `submit_source` has only ever chunked `body`. A submission naming `kind="url"` with a
#: `uri` was accepted, stored, chunked from whatever text the caller ALSO pasted, and the
#: uri was written to a column nothing reads — so the caller got a 201 for a fetch that
#: never happened. TRD §6 puts parsing in an offline worker ("parse (LlamaParse for messy
#: PDFs) → chunk preview"), and neither half of that exists: no fetcher, no parser.
#:
#: Refusing by name is the honest half and it is one line. The rejected alternative was
#: narrowing `SubmitIn.kind` to `Literal["text"]`, which is stricter — the generated TS
#: client could not even spell the request — but it changes the OpenAPI schema, and a
#: schema regeneration mid-wave sweeps up every other slice's in-flight route changes.
#: A named 422 with a remediation closes the LIE, which is the part that hurts a caller;
#: the narrowing is what the parser slice does when it deletes this set.
#:
#: What closes it: a URL fetcher (its own SSRF design — an unauthenticated-by-proxy GET
#: from our network to a caller-chosen host) and a document parser. LlamaParse is the
#: named candidate and is an EXTERNAL blocker: a vendor account nobody has opened.
SUPPORTED_SUBMISSION_KINDS: frozenset[str] = frozenset({"text"})


#: Characters a reviewer cannot see and a downstream reader still acts on.
#:
#: **THE APPROVAL GATE IS A HUMAN READING A PREVIEW, so a character that makes the preview
#: and the published text say different things is a bypass of it — not a formatting
#: nuisance.** The named attack is Trojan Source (Boucher & Anderson, 2021, CVE-2021-42574):
#: `U+202E RIGHT-TO-LEFT OVERRIDE` and its relatives reorder a run VISUALLY while leaving
#: the stored order untouched, so "Refunds are ‮never‬ given" is read one way by the admin
#: who approves it and spoken the other way by the agent. Every other consumer of this text
#: — the [T0 FACTS] block the agent actually speaks from, the engine document, the dashboard
#: copilot's quotation — takes the logical order.
#:
#: THE THREE GROUPS, AND WHY EACH IS IN:
#:
#: * **Bidi formatting, overrides and isolates** (U+202A-U+202E, U+2066-U+2069, U+200E,
#:   U+200F, U+061C) — the attack above. Our market writes Telugu, English and Hindi, none
#:   of which needs an explicit direction mark in a knowledge sentence.
#: * **C0 and C1 controls except tab, LF and CR** — a vertical tab or a form feed is
#:   invisible in a text box, and `\x00` is not merely invisible: a Postgres text column
#:   REFUSES it, so a submission carrying one used to die on the INSERT as a
#:   `psycopg.DataError`, reach the generic handler, and answer a client 500 with a crash
#:   alert behind it. A named 422 is the honest answer to text we will not store.
#: * **Zero-width and invisible spacing** — U+200B, U+2060, U+FEFF. They split a word for
#:   the tokeniser (and therefore for the sparse arm) while looking like nothing at all.
#:
#: AND THE TWO THAT ARE DELIBERATELY NOT HERE. `U+200C ZERO WIDTH NON-JOINER` and
#: `U+200D ZERO WIDTH JOINER` are ORTHOGRAPHY in Telugu and every other Indic script — they
#: decide whether a conjunct forms — so refusing them would refuse correctly spelled Telugu,
#: which is the language this product is built for. `U+00AD SOFT HYPHEN` stays allowed too:
#: it arrives in honest pastes out of word processors and cannot reorder anything.
_FORBIDDEN_CODEPOINTS: frozenset[int] = frozenset(
    {0x061C, 0x200B, 0x200E, 0x200F, 0x2060, 0xFEFF}
    | set(range(0x00, 0x20))
    | set(range(0x7F, 0xA0))
    | set(range(0x202A, 0x202F))
    | set(range(0x2066, 0x206A))
) - {0x09, 0x0A, 0x0D}


def _reject_invisible_characters(value: str, *, field: str) -> None:
    """Refuse text carrying a character the reviewer cannot see. See `_FORBIDDEN_CODEPOINTS`.

    REFUSED RATHER THAN STRIPPED, which is this repository's doctrine for a guard on
    something that matters (`sanitize.assert_redacted`: a guard that silently repairs its
    input teaches the caller nothing). Stripping would be worse than usual here — the client
    would have approved wording they never see us change, and a bidi run that survives one
    stripping pass and not another is exactly the ambiguity the gate exists to remove.

    THE CODEPOINTS ARE NAMED AND THE TEXT IS NOT (hard rule 6, and it is also the only
    actionable half): "there is an invisible character at U+202E" is something a person can
    search for in their own document; an echo of their prose is not.

    It is checked at `submit_source` — the ONE door into `kb_sources` — so the property
    holds for the form, the copilot's propose-knowledge tool, the knowledge-gap teaching
    path and the intake seeder without any of them knowing about it. `kb/pdf_render.py`
    refuses most of these a second time as a side effect of the font's cmap, which is a
    real backstop and a WRONG diagnosis ("the font cannot render this") for a reviewer who
    was shown one sentence and asked to approve another.
    """
    found = sorted({ord(ch) for ch in value} & _FORBIDDEN_CODEPOINTS)
    if not found:
        return
    named = ", ".join(f"U+{cp:04X}" for cp in found[:8])
    log.warning("kb_invisible_characters", extra={"field": field, "codepoints": named})
    raise ProblemError(
        kind="validation",
        code="kb_invisible_characters",
        title="That wording contains characters we cannot show a reviewer",
        detail=(
            f"The {field} carries {len(found)} invisible or direction-changing character "
            f"type(s) ({named}). Knowledge is read by a person before it goes live and "
            "spoken to callers afterwards, so it may only contain characters both of them "
            "can see."
        ),
        remediation=(
            "Retype the wording in a plain text box, or paste it into a plain-text editor "
            "first — these characters usually arrive invisibly from a formatted document."
        ),
        status=422,
    )


def chunk_text(body: str) -> list[str]:
    """Split on paragraph boundaries, packing up to the cap; only split a paragraph
    that exceeds the cap on its own, and then on sentence ends.

    **LOSSLESS, and that is a property this function is tested on rather than a hope.**
    Every non-whitespace character of `body` appears in exactly one chunk, in order
    (`tests/kb_workflow_test.py::test_chunking_never_drops_a_character_of_the_submission`).
    It was not: a sentence longer than the cap used to be assigned as `sentence[:MAX]`
    and the remainder dropped on the floor, so a 2,000-character run-on paragraph
    reached the agent as its first 700 characters with nothing anywhere saying so. The
    approval gate cannot catch that — a reviewer reads the preview to judge the WORDING,
    not to diff it against the paste buffer — and the client's 201 said `chunks: 1`,
    which was true and useless.
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    chunks: list[str] = []
    buffer = ""
    for paragraph in paragraphs:
        if len(paragraph) > MAX_CHUNK_CHARS:
            if buffer:
                chunks.append(buffer)
                buffer = ""
            chunks.extend(_split_sentences(paragraph))
            continue
        # The candidate carries its own joiner, so the two-character cost of `\n\n` is
        # counted when there IS a joiner and not when there is not. Charging for it
        # unconditionally is what used to append `buffer` while `buffer` was the empty
        # string: a paragraph of 699 or 700 characters arriving on an empty buffer took
        # the else branch and wrote a zero-length chunk into `kb_documents`, which the
        # preview then showed the reviewer as an empty box and the publish pushed to the
        # engine as a blank document.
        candidate = f"{buffer}\n\n{paragraph}" if buffer else paragraph
        if len(candidate) <= MAX_CHUNK_CHARS:
            buffer = candidate
        else:
            if buffer:
                chunks.append(buffer)
            buffer = paragraph
    if buffer:
        chunks.append(buffer)
    # Fold a stub tail into its predecessor: a two-word chunk retrieves noisily. This is
    # the ONE place a chunk may exceed the cap, by at most MIN_CHUNK_CHARS + 2.
    if len(chunks) > 1 and len(chunks[-1]) < MIN_CHUNK_CHARS:
        chunks[-2] = f"{chunks[-2]}\n\n{chunks[-1]}"
        chunks.pop()
    return chunks


def _split_sentences(paragraph: str) -> list[str]:
    sentences = re.split(r"(?<=[.!?।])\s+", paragraph)
    out: list[str] = []
    buffer = ""
    for sentence in sentences:
        if len(buffer) + len(sentence) + 1 <= MAX_CHUNK_CHARS:
            buffer = f"{buffer} {sentence}".strip()
            continue
        if buffer:
            out.append(buffer)
            buffer = ""
        if len(sentence) <= MAX_CHUNK_CHARS:
            buffer = sentence
            continue
        # A single sentence longer than the cap. There is no boundary left to respect,
        # so it is WRAPPED rather than cut short — see `chunk_text` on why dropping the
        # tail is the worst of the three options. The last piece stays in the buffer so
        # a following short sentence can pack onto it.
        *complete, buffer = _wrap_long_sentence(sentence)
        out.extend(complete)
    if buffer:
        out.append(buffer)
    return out


def _wrap_long_sentence(sentence: str) -> list[str]:
    """A sentence past the cap, cut into cap-sized pieces on the last space that fits.

    Never on a character boundary if a word boundary is available, because a chunk is
    read aloud: "the consultation fee is five hu / ndred rupees" is what a mid-word cut
    sounds like when retrieval returns only the first piece. A run with no space in the
    whole window (a pasted id, a URL, a script that does not space its words) falls back
    to the character cut — progress has to be guaranteed or this loops forever.

    Returns at least one piece; the caller relies on that to unpack the tail.
    """
    pieces: list[str] = []
    rest = sentence
    while len(rest) > MAX_CHUNK_CHARS:
        # +1 so a space sitting exactly at the cap is a legal cut point.
        cut = rest[: MAX_CHUNK_CHARS + 1].rfind(" ")
        if cut < MIN_CHUNK_CHARS:
            cut = MAX_CHUNK_CHARS
        pieces.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    if rest:
        pieces.append(rest)
    return pieces


async def insert_source_version(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    name: str,
    kind: str,
    uri: str | None,
    submitted_by: UUID | None,
    auto_approve: bool = False,
) -> tuple[UUID, int, str]:
    """Mint the next VERSION row of a named source. Answers `(id, version, status)`.

    **EXTRACTED FROM `submit_source` RATHER THAN COPIED INTO THE UPLOAD PATH (D-532).** An
    uploaded document is a knowledge source version in every respect that matters — it is
    reviewed, versioned, published, superseded and expired by this module's machinery — and
    the two things that must not be re-derived beside it are the authorisation read and the
    version numbering. A second copy of either is how one lane gets `assert_visible` and the
    other does not, or how two paths compute the same `MAX(version) + 1`.

    ═══ AUTO-APPROVAL, AND WHY IT IS A PARAMETER RATHER THAN A ROLE READ ═══

    The founder's decision is that an OWNER's submission is auto-approved and a STAFF
    member's is reviewed. WHO is asking is a question about a request — realm, role,
    impersonation, and the account's own staff-curation switch — and `kb/curation.py`
    already answers it in exactly one place. This function takes the ANSWER, so the ladder
    is not re-implemented here and a service-level caller (a worker re-ingesting a changed
    link, a test) gets the safe default: review.

    An auto-approval records `approved_by = submitted_by`, so the audit question "who
    cleared this" has the same shape as an admin approval and never answers NULL. It is a
    real approval by the person who is accountable for the account, not an absence of one.
    """
    # Hard rule 1 does not reach this INSERT on its own: PostgreSQL runs
    # referential-integrity checks with row security bypassed, so `kb_sources.agent_id`
    # would accept another tenant's agent (`db/ownership.py` carries the mechanism).
    # The consequence is worse HERE than elsewhere because of the unique index below:
    # `(agent_id, name, version)` is evaluated over every row rather than the visible
    # ones, so an unauthorised row takes a slot the owning tenant can no longer use —
    # their own submission then fails on a constraint violation caused by a row they
    # cannot see, list or delete, and the error is an existence oracle besides.
    await assert_visible(session, "agent", agent_id)

    # `MAX(version) + 1` under an advisory lock on the named source, not a read-then-write.
    # Two people submitting under the same name at the same instant — the shape a client's
    # owner and manager reach by both pasting an updated price list — otherwise computed
    # the SAME next version, and the second INSERT died on
    # `uq_kb_sources_agent_id_name_version`. That IntegrityError escaped to the generic
    # handler: a 500 and a crash alert, where the honest outcome is that both submissions
    # are recorded as consecutive versions and both are reviewable.
    #
    # Same primitive, same argument and the same key shape as `ops/secret_service.install`
    # (BACKEND-PATTERNS §5) — one way per problem. It is taken AFTER the authorisation
    # read, so naming another tenant's agent cannot make us hold a lock on their name.
    # The key is deliberately distinct from `_lock_agent_publishes`': submitting a draft
    # and publishing a live version share no state and must not block each other.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"kb:submit:{agent_id}:{name}"},
    )
    current = (
        await session.execute(
            text(
                "SELECT COALESCE(max(version), 0) FROM kb_sources "
                "WHERE agent_id = :aid AND name = :name"
            ),
            {"aid": agent_id, "name": name},
        )
    ).scalar()
    version = int(current or 0) + 1

    status = "approved" if auto_approve else "pending_approval"
    source_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO kb_sources (id, tenant_id, agent_id, kind, name, uri, status, "
            "version, submitted_by, approved_by, approved_at, is_active, created_at, "
            "updated_at) VALUES (:id, :tid, :aid, :kind, :name, :uri, :status, :version, "
            ":by, :approved_by, CASE WHEN CAST(:auto AS boolean) THEN now() END, "
            "false, now(), now())"
        ),
        {
            "id": source_id,
            "tid": tenant_id,
            "aid": agent_id,
            "kind": kind,
            "name": name,
            "uri": uri,
            "status": status,
            "version": version,
            "by": submitted_by,
            "approved_by": submitted_by if auto_approve else None,
            "auto": auto_approve,
        },
    )
    return source_id, version, status


async def submit_source(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    name: str,
    body: str,
    kind: str = "text",
    uri: str | None = None,
    submitted_by: UUID | None = None,
    auto_approve: bool = False,
) -> dict[str, Any]:
    """Create the next VERSION of a named source, chunked and awaiting approval.

    Nothing here touches the engine. A submission is a proposal; only `publish_source`
    changes what the agent knows.

    A kind we cannot ingest is refused BEFORE anything is written — see
    `SUPPORTED_SUBMISSION_KINDS` for why the alternative (accept it, chunk the pasted
    body, drop the uri on the floor) is worse than a refusal.
    """
    if kind not in SUPPORTED_SUBMISSION_KINDS:
        raise ProblemError(
            kind="validation",
            code="kb_kind_unsupported",
            title="We cannot read that yet",
            detail=(
                "Knowledge can only be submitted as text at the moment; documents and "
                "web pages are not read for you."
            ),
            remediation=(
                "Paste the wording you want the agent to use into the text box. Write it "
                "the way you would tell a new receptionist."
            ),
            status=422,
        )

    # BEFORE anything is written and before the lock, because it is a property of the
    # SUBMISSION rather than of a version: nothing here needs a database to decide it.
    _reject_invisible_characters(name, field="source name")
    _reject_invisible_characters(body, field="wording")

    chunks = chunk_text(body)
    if not chunks:
        raise ProblemError(
            kind="validation",
            code="kb_empty",
            title="Nothing to add",
            detail="The submitted content is empty.",
        )

    source_id, version, status = await insert_source_version(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        name=name,
        kind=kind,
        uri=uri,
        submitted_by=submitted_by,
        auto_approve=auto_approve,
    )
    for idx, chunk in enumerate(chunks):
        await session.execute(
            text(
                "INSERT INTO kb_documents (id, tenant_id, source_id, idx, title, content, "
                "created_at, updated_at) VALUES (:id, :tid, :sid, :idx, :title, :content, "
                "now(), now())"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "sid": source_id,
                "idx": idx,
                "title": name,
                "content": chunk,
            },
        )
    return {
        "id": source_id,
        "version": version,
        "chunks": len(chunks),
        "status": status,
    }


async def preview(session: AsyncSession, source_id: UUID) -> list[dict[str, Any]]:
    """The chunks a reviewer reads, or a 404 — never an empty list standing in for one.

    THE SOURCE ROW IS LOOKED UP FIRST, and it is the only reason this is not a one-line
    read of `kb_documents`. Both tables are RLS'd on `tenant_id`, so a neighbour's id and
    a uuid nobody minted were both `200 []` — and so was a real source of this tenant's
    whose chunking produced nothing. Three different facts, one answer, none of them
    distinguishable on the screen this endpoint exists to draw.

    404 for the first two is this repo's discriminator doctrine ("absent or invisible =
    404"), and `approve_source` below already states it about this very table: answering
    otherwise "told an operator a source EXISTS when the id was another tenant's". The
    two cases stay ONE answer deliberately — an invisible source that 404'd differently
    from an absent one would be an oracle for which source ids exist.

    It is not an existence oracle in the other direction either: reaching this function
    at all requires `agents:read` in a tenant, and the lookup runs under that tenant's
    session, so the only ids it can confirm are ids the caller may already list.
    """
    exists = (
        await session.execute(text("SELECT 1 FROM kb_sources WHERE id = :sid"), {"sid": source_id})
    ).first()
    if exists is None:
        raise ProblemError.not_found("Knowledge source")
    rows = (
        await session.execute(
            text(
                "SELECT idx, content, gloss, gloss_model FROM kb_documents "
                "WHERE source_id = :sid ORDER BY idx"
            ),
            {"sid": source_id},
        )
    ).all()
    # THE GLOSS IS SHOWN AND IT IS SHOWN AS A MACHINE'S WORK. `gloss_model` travels with it
    # so the screen can say WHICH model wrote it rather than asserting "machine-generated"
    # as a convention the API merely hopes the client honours. A reviewer who can see it can
    # report a bad one; a reviewer who cannot would be approving text they never read.
    return [
        {
            "idx": r[0],
            "content": r[1],
            "chars": len(r[1]),
            "gloss": r[2],
            "gloss_model": r[3],
        }
        for r in rows
    ]


async def approve_source(
    session: AsyncSession, *, source_id: UUID, approved_by: UUID | None
) -> bool:
    """CAS on `pending_approval` (BACKEND-PATTERNS §5). True when THIS call approved it.

    The three answers are `db.transition.transition_status`'s: a source already
    `approved` is a success with no second write (the approver and the timestamp stay
    the FIRST reviewer's — an approval is attributable, and a double-clicked button
    must not rewrite who signed off), a source someone rejected in the meantime is a
    409 that names `rejected`, and an id no visible source has is a 404.

    This used to answer `kb_not_pending` 409 to all three, which told an operator
    reviewing a queue that an already-approved source "is not awaiting approval" when
    the outcome they wanted had happened, and told them a source EXISTS when the id was
    another tenant's — RLS makes those rows invisible, so the honest answer is 404.
    """
    return await transition_status(
        session,
        table="kb_sources",
        entity="Knowledge source",
        row_id=source_id,
        to_status="approved",
        from_statuses=("pending_approval",),
        extra_set="approved_by = :by, approved_at = now()",
        params={"by": approved_by},
    )


async def reject_source(session: AsyncSession, *, source_id: UUID, reason: str) -> bool:
    """The other half of the gate; True when THIS call rejected it.

    Same discriminator as `approve_source`, and the same reason the reason text is not
    rewritten on a repeat: the recorded rejection is the one the reviewer who first said
    no wrote, and a retry must not quietly replace it with a later note.
    """
    return await transition_status(
        session,
        table="kb_sources",
        entity="Knowledge source",
        row_id=source_id,
        to_status="rejected",
        from_statuses=("pending_approval",),
        extra_set="rejection_reason = :reason",
        params={"reason": reason[:500]},
    )


async def _chunks_of(session: AsyncSession, source_id: UUID) -> list[str]:
    """The approved chunks of one source, in reading order — one engine document."""
    rows = (
        await session.execute(
            text("SELECT content FROM kb_documents WHERE source_id = :sid ORDER BY idx"),
            {"sid": source_id},
        )
    ).scalars()
    return [str(chunk) for chunk in rows]


def _engine_name() -> str:
    """WHICH vendor account holds the object this claim names — recorded, never keyed on.

    The PROCESS-WIDE selection (`get_engine()`), not `agents.engine`: `get_engine` does
    not consult that column, so the adapter that actually performed an attach is this one.
    `engine_agent_routes` is written from the same value (`agents/service.py`).

    IT IS DELIBERATELY NOT PART OF ANY LOOKUP, and that is a decision rather than an
    omission. The reads below ask "what is this source filed as", never "what is it filed
    as on engine X" — one source holds at most one vendor object, which is what
    `uq_engine_kb_routes_source` states — and a lookup keyed on this string would strand
    every existing claim the day an adapter is renamed or the setting moves, silently, in
    the direction that loses a client's knowledge. What the column is FOR is the orphan
    sweep, which must know which account's listing to compare a claim against.
    """
    return get_engine().name


#: Every per-source read of the claim table JOINs `kb_sources`, and that join is the
#: TENANCY, not decoration.
#:
#: `engine_kb_routes` is globally readable on purpose — the orphan question ("which
#: objects on this account does no tenant of ours claim?") cannot be asked any other way
#: (migration `f1c9e0a73b46`). But possession of a handle IS possession of another
#: client's knowledge: the vendor's namespace is flat, one account holds every tenant's
#: documents, and the handle is what deletes one. So the reads that answer "what is MY
#: source filed as" go through `kb_sources`, which is FORCE-RLS'd — a session scoped to
#: another tenant, or to none, sees no source row and therefore no handle, which is
#: exactly the visibility the JSONB key had. `tests/kb_isolation_test.py` and
#: `tests/kb_drift_reconciliation_test.py` pin both halves; the drift sweep DEPENDS on
#: the untenanted read answering empty rather than the platform's whole handle set.
_ROUTE_JOIN = "FROM engine_kb_routes r JOIN kb_sources s ON s.id = r.source_id WHERE "


async def _engine_kb_ref(session: AsyncSession, source_id: UUID) -> str | None:
    """The engine's handle for this source's attached copy, or None if nothing of ours
    is attached. See `_remember_engine_kb_ref` for why it lives where it lives."""
    value = (
        await session.execute(
            text(f"SELECT r.engine_kb_ref {_ROUTE_JOIN} r.source_id = :sid"),
            {"sid": source_id},
        )
    ).scalar()
    return str(value) if value else None


async def _engine_kb_digest(session: AsyncSession, source_id: UUID) -> str | None:
    """The content digest of the document we last uploaded for this source.

    THE IDEMPOTENCY KEY (D-488), and it is stored rather than recomputed because the two
    questions are different: recomputing tells us what the CURRENT chunks render to,
    while this tells us what the engine was actually HANDED. A publish is a no-op at the
    vendor only when those two agree AND the handle they produced is still attached.

    Why it is needed at all: `attach_kb` is a CREATE on every engine this port
    describes — none of them offers an update — so each call mints a new object and
    de-duplicates nothing (the vendor evidence for the one we run on is cited in
    `apps/api/engine/`, which is the only place it may be named). A double-clicked
    Publish, a retry after a timeout, or FLOWS §7's rollback onto the version already
    live would each upload a second identical document, bill for it, and overwrite the
    only handle that could have removed the first.
    """
    value = (
        await session.execute(
            text(f"SELECT r.digest {_ROUTE_JOIN} r.source_id = :sid"),
            {"sid": source_id},
        )
    ).scalar()
    return str(value) if value else None


async def _remember_engine_kb_ref(
    session: AsyncSession,
    source_id: UUID,
    engine_kb_ref: str | None,
    *,
    digest: str | None = None,
) -> None:
    """Record (or clear) the engine's handle for a source.

    **IT USED TO LIVE IN `kb_documents.meta ->> 'engine_kb_ref'` AND NOW HAS A TABLE
    (D-519, migration `f1c9e0a73b46`).** The old home was the one the KB migration
    designated for provider-side ids and it cost no migration, which is why it was
    chosen; three properties it cannot have are what moved it, and the third is the one
    that matters:

    * it was UNINDEXED — every read walked `kb_documents`, one row per chunk per version,
      for at most one string;
    * nothing enforced UNIQUENESS, so two sources could record one handle and a detach
      would delete a vendor object another source still pointed at;
    * `kb_documents` is FORCE-RLS'd, so "which objects on this account does no tenant of
      ours claim" — the question that decides whether a client's document is reachable by
      any erasure path at all — could not be asked of it from anywhere. We run ONE engine
      account for every tenant and the vendor's knowledge base is an ACCOUNT-level object
      with no owner field, so that question is the whole safety story, and it needed a
      globally readable claim. `engine_agent_routes` is the same shape for the same
      reason.

    The digest travels with the handle rather than staying behind: it is a fact about the
    VENDOR's copy — the bytes that handle was minted from — not about our chunks.

    Clearing on detach is not tidiness: a handle left behind after the engine copy is
    gone is a handle a later publish would try to delete, and that publish would then
    refuse for a reason that is no longer true. The whole row goes, because a claim on a
    vendor object we no longer believe exists is exactly what the orphan sweep must not
    see (`kb/orphans.py`).

    `tenant_id` and `agent_id` are SELECTed from `kb_sources` rather than passed in, so
    the claim can only ever name the tenant that owns the source — under RLS a session
    scoped elsewhere selects no row and writes nothing, rather than writing a row
    attributing a vendor object to the wrong client.
    """
    if engine_kb_ref is None:
        await session.execute(
            text("DELETE FROM engine_kb_routes WHERE source_id = :sid"),
            {"sid": source_id},
        )
        return
    await session.execute(
        text(
            "INSERT INTO engine_kb_routes (engine, engine_kb_ref, tenant_id, agent_id, "
            "source_id, digest, created_at, updated_at) "
            "SELECT :engine, :ref, s.tenant_id, s.agent_id, s.id, :digest, now(), now() "
            "FROM kb_sources s WHERE s.id = :sid "
            # The source keeps its claim and re-points it: a republish of the same source
            # mints a new vendor object, and the row that named the old one is the row
            # that must now name the new one. A DIFFERENT source claiming a handle this
            # one already holds is NOT reconciled here — it violates the primary key and
            # raises, which is the point of the constraint.
            "ON CONFLICT (source_id) DO UPDATE SET engine = EXCLUDED.engine, "
            "engine_kb_ref = EXCLUDED.engine_kb_ref, digest = EXCLUDED.digest, "
            "updated_at = now()"
        ),
        {"sid": source_id, "ref": engine_kb_ref, "digest": digest, "engine": _engine_name()},
    )


async def _approved_chunks_of(
    session: AsyncSession, source_id: UUID, *, source_name: str
) -> list[ApprovedChunk]:
    """The rows `render_knowledge_pdf` renders, in reading order.

    Separate from `_chunks_of`, which answers a different question: that one returns the
    TEXT for the engines whose knowledge base ingests prose, and this one returns the
    renderer's row type, which carries `idx` (so a retrieved marker points back at a
    chunk) and the approval flags the renderer re-asserts for itself.
    """
    rows = (
        await session.execute(
            text("SELECT idx, content FROM kb_documents WHERE source_id = :sid ORDER BY idx"),
            {"sid": source_id},
        )
    ).all()
    return [
        ApprovedChunk(
            source_id=source_id,
            source_name=source_name,
            idx=int(idx),
            content=str(content),
            # BOTH TRUE, AND STATED RATHER THAN READ, because at this point in a publish
            # the row's own `is_active` is still FALSE on every first publish — line
            # 1340 sets it, and that is AFTER the attach this document is being rendered
            # for. Passing the column would refuse every first publish of every source.
            # What these two flags mean to the renderer is "this content is cleared to go
            # to a vendor", and `publish_source` has already proved exactly that above
            # (`approved_at IS NOT NULL AND status IN ('approved','archived')`) and
            # refused with `kb_not_approved` if not. The renderer's own re-assertion is
            # therefore vacuous FROM THIS CALLER and deliberately kept anyway: it guards
            # the next caller, which will not have this function's gate above it.
            approved=True,
            is_active=True,
        )
        for idx, content in rows
    ]


def _render_document(
    *, title: str, chunks: list[ApprovedChunk], language: str
) -> RenderedKnowledgePdf:
    """The approved chunks as the document an engine will ingest.

    **THIS USED TO BE A `importlib` SEAM RESOLVING `apps.api.kb.render` BY NAME, AND IT
    IS NOW A PLAIN IMPORT.** The indirection existed for one reason, written into the
    comment it replaced: the renderer was a sibling agent's module and was not in this
    tree yet, so a static import would not type-check. It landed (`kb/pdf_render.py`),
    so the reason is spent — and a dynamic lookup that outlives its reason is strictly
    worse than an import: mypy cannot see the signature, the arity is unchecked, and the
    two halves drifted apart exactly as you would expect. They HAD drifted: the seam
    declared `render_knowledge_pdf(*, title, chunks: list[str], language) -> bytes`
    against a module named `render.py`, and what shipped was
    `render_knowledge_pdf(chunks: Sequence[ApprovedChunk]) -> RenderedKnowledgePdf` in
    `pdf_render.py`. Nothing failed: `import_module` raised `ImportError`, the seam
    logged `kb_renderer_unavailable`, returned `None`, and the adapter refused with
    `engine_kb_document_missing` — so publishing knowledge to the engine was DEAD, and
    every test passed, because the fake adapter accepts `document=None`.

    `title` and `language` are accepted and not passed on, and that is not an oversight.
    The renderer puts each chunk's own source name above it (a retrieved passage has to
    carry its provenance INSIDE the text, since the vendor re-chunks what we upload), so
    a document-level title would be a second, weaker copy of the same thing; and the
    script is decided by the font, which covers Telugu and Latin, rather than by a
    declared language. They stay in the signature because the caller has them and the
    next renderer may need them — dropping them would make re-adding them a change at
    both ends.

    Raises `ProblemError` for every refusal the renderer can produce. All four are the
    same class of event — a document that would upload cleanly and then under-serve a
    live call — so they share a remediation shape: say which chunk, and what to do.
    """
    try:
        return render_knowledge_pdf(chunks)
    except KnowledgePdfError as exc:
        # AT ERROR AND WITH NO CHUNK TEXT. `str(exc)` names markers and codepoints, never
        # content (hard rule 6), which is why the message is safe to log and to show.
        log.error(
            "kb_render_refused",
            extra={"reason": type(exc).__name__, "chunks": len(chunks)},
        )
        raise ProblemError(
            kind="business_rule",
            code="kb_render_refused",
            title="This knowledge cannot be published as it stands",
            detail=str(exc),
            remediation="Edit the knowledge source and approve it again.",
        ) from exc


async def _publish_config(session: AsyncSession, tenant_id: UUID, agent_id: UUID) -> AgentConfig:
    """The agent's configuration, exactly as a publish would send it.

    WHY THIS FUNCTION EXISTS (D-488). On an engine that keeps the knowledge linkage as
    AGENT state, attaching a document is a WRITE to the agent — and on the engine this
    product runs, the only route that performs that write REPLACES the agent's whole
    configuration, while the partial-update route cannot reach the field at all. An
    adapter cannot assemble a full body from a read-back either, because the read-back
    omits the agent's spoken notice and its event webhook: a publish that rebuilt the
    agent from what it could read would silently drop the AI disclosure, the recording
    notice and the only channel by which we learn a call happened. So the publisher
    supplies the configuration and the adapter writes a body it was given. The vendor
    citations for every clause of that are in `apps/api/engine/`, where hard rule 2 lets
    them live.

    `service._to_config` RATHER THAN A SECOND RENDERING, for `publishing.engine_drift_for`'s
    reason: a config built here would drift from the one a real publish sends on the field
    nobody looks at, and the drift would show up as a knowledge attach that quietly
    rewrote an agent.
    """
    # Deferred, exactly as `agents/publishing.py` does it: `agents/service` sits inside an
    # import cycle with the publish chain, and a module-level import here closes it.
    from apps.api.agents.service import _load_agent, _to_config

    return _to_config(
        tenant_id, await _load_agent(session, tenant_id, agent_id), engine=get_engine()
    )


def publish_lock_key(agent_id: UUID) -> str:
    """The advisory-lock key one agent's KB publishes serialize on.

    A function rather than an f-string written twice, because there is now a SECOND
    holder: the periodic drift sweep takes the same lock with `pg_try_advisory_xact_lock`
    so it never observes an agent mid-publish (`kb/reconciliation.py`). Two modules
    spelling the same key is one typo away from a sweep that locks nothing and reports
    the detach-then-attach window as a divergence — a lock whose key can drift is not a
    lock, so the string has one home.
    """
    return f"kb:publish:{agent_id}"


async def _lock_agent_publishes(session: AsyncSession, *, agent_id: UUID) -> None:
    """Serialize KB publishes for ONE agent, for the length of the caller's transaction.

    `publish_source` is a read-decide-write whose middle is a sequence of network calls:
    it reads which versions are live, withdraws them from the engine, attaches the new
    one, and only then flips `is_active`. Nothing in that made two concurrent publishes
    of the same name exclusive, and the failure it produced is the exact divergence
    D-41's detach-then-attach ordering exists to prevent — TWO live versions, both
    attached, the agent free to answer from either, our tables reporting both as live.

    It needed no vendor weirdness to reach. Two approved versions of one name with
    nothing live yet (an admin working a queue, two admins, a double-click on two rows)
    both read `superseded = []`, both find no own handle to withdraw, both attach, and
    both `UPDATE ... SET is_active = true` on rows the other's WHERE clause never named.
    Under READ COMMITTED there is no conflict to detect. Where a predecessor DID exist
    the second detach 404'd and the publish refused, which is why this only ever showed
    up on the first publish of a name — the case a client hits once per source.

    `pg_advisory_xact_lock(hashtextextended(key, 0))` is the house primitive for
    exactly this shape (BACKEND-PATTERNS §5, `compliance/audit.py`, `billing/service.py`,
    `ops/secret_service.py`): the critical section IS a database transaction, so the lock
    is released by COMMIT *or* ROLLBACK — the two events that decide whether the flip
    happened — and there is no TTL to outlive an engine call of unknown length.

    **THE KEY IS THE AGENT, NOT `(agent, name)`, AND THE NARROWER KEY WAS TRIED FIRST.**
    Different named sources on one agent supersede independently
    (`test_publishing_one_source_does_not_withdraw_the_others`), so a name-scoped lock
    looks like the tighter, better one. It is not, because every publish ALSO ends in
    `recompile_t0`, and a prompt version is numbered per AGENT under
    `UNIQUE (agent_id, version)`. Two publishes of DIFFERENT names therefore raced into
    `insert_prompt_version`, and the loser got `prompt_version_conflict` — a clean 409,
    but one whose remediation ("reload the version history and submit again") describes
    an action the operator never took, and whose rollback discards a `kb_documents` row
    for a copy already ATTACHED to the engine. The next publish then finds that copy
    unaccounted for and refuses with `kb_engine_out_of_sync`, which needs support. A
    409 that bricks the workflow it interrupted is worse than a queue: the prompt
    sequence is per agent, so publishes for one agent have to serialize anyway, and the
    only choice is whether they do it by waiting or by failing.

    Rejected: a partial unique index on `(agent_id, name) WHERE is_active`. It states the
    invariant more durably, and it is the wrong tool alone — the loser would learn it had
    lost only AFTER attaching its copy to the engine, leaving a document our rolled-back
    rows can no longer address. The lock stops the second publish before it spends a
    vendor call. (Adding both would be two mechanisms for one problem, and the index is
    the one that cannot prevent, only detect.)

    What it costs, stated plainly: publishes for one agent queue, each for the length of
    its engine round trips. That sentence used to price a round trip at the adapter's
    request timeout alone — 10s — and the adapter's own THROTTLE ladder makes the worst
    case per call roughly five times that: `THROTTLE_MAX_ATTEMPTS = 3` attempts of
    `REQUEST_TIMEOUT_S = 10s`, with a jittered wait between them capped at
    `THROTTLE_MAX_SLEEP_S = 8s`. A publish is a listing plus one detach per superseded
    version plus one attach, so an agent whose vendor is rate-limiting can hold this lock
    for a couple of minutes rather than a handful of seconds. THE CHOICE IS UNCHANGED AND
    THE NUMBER IS NOW THE REAL ONE: this is an admin-console path, not the audio path, it
    is per agent — no other agent, tenant or surface waits — and the KB drift sweep takes
    the same key with `pg_try_advisory_xact_lock`, so a long publish costs it one skipped
    tick and never a wait.
    """
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": publish_lock_key(agent_id)},
    )


async def _superseded_versions(
    session: AsyncSession, *, agent_id: UUID, name: str, keep: UUID
) -> list[tuple[UUID, str | None]]:
    """The live versions of this named source that publishing `keep` replaces, each with
    the engine handle we recorded for it. Normally exactly one; a list because "exactly
    one" is an invariant we enforce, not one we may assume while enforcing it."""
    rows = (
        await session.execute(
            text(
                "SELECT id FROM kb_sources WHERE agent_id = :aid AND name = :name "
                "AND is_active = true AND id <> :sid"
            ),
            {"aid": agent_id, "name": name, "sid": keep},
        )
    ).scalars()
    live = [UUID(str(row)) for row in rows]
    return [(source_id, await _engine_kb_ref(session, source_id)) for source_id in live]


def _require_addressable(superseded: list[tuple[UUID, str | None]]) -> None:
    """Refuse to publish over a live version we have no handle for.

    We cannot remove what we cannot address, and attaching anyway is the original
    defect: two copies live, the agent free to answer from either. (Only versions
    published before the handle was recorded can be in this state; the remediation is
    one manual withdrawal on the engine side, not a code path that guesses.)

    Hoisted out of the detach loop so it runs BEFORE the reconciliation below. Both
    refusals describe the same disease — our records and the engine disagree — and when
    both are true this is the more specific diagnosis, so it is the one an operator
    should be handed.
    """
    for source_id, engine_kb_ref in superseded:
        if engine_kb_ref is not None:
            continue
        log.warning("kb_engine_ref_unknown", extra={"source_id": str(source_id)})
        raise ProblemError(
            kind="business_rule",
            code="kb_engine_ref_unknown",
            title="The live version cannot be withdrawn",
            detail=(
                "We have no record of how the currently live version is filed on the "
                "voice platform, so it cannot be removed before publishing this one."
            ),
            remediation=(
                "Nothing changed — the live version is still the approved one. "
                "Ask support to withdraw the stale copy on the voice platform first."
            ),
        )


async def recorded_handles_of_agent(session: AsyncSession, agent_id: UUID) -> set[str]:
    """Every engine handle we believe is attached to this agent, across all its sources.

    Agent-wide rather than per-name: an agent's KB is several named sources, and the
    question the reconciliation asks is "can we account for everything the engine is
    holding", which no single name can answer.

    PUBLIC because the periodic sweep (D-158, `kb/reconciliation.py`) asks the identical
    question on a schedule, and "what do we believe is attached" must have exactly one
    definition — a sweep with its own copy of this query would eventually disagree with
    the publish gate about which handles are accounted for, and the two would then reach
    opposite verdicts about the same agent with nothing able to see it. It stays a plain
    read on the caller's session so RLS decides what is visible.

    Deliberately NOT filtered to `is_active` sources. A superseded version has its handle
    CLEARED on detach (`_detach_superseded`), so a handle still recorded against an
    archived source means a detach that never completed — a divergence, not noise, and
    exactly the residue `_undo_attach` documents itself as leaving.

    Since D-519 the handle lives in `engine_kb_routes` and this reads it THROUGH
    `kb_sources` (see `_ROUTE_JOIN`), which is what keeps the answer tenant-scoped: the
    claim table is globally readable so the orphan sweep can ask an account-wide question,
    and this is not that question. The sweep's caller depends on it — an untenanted read
    must answer the empty set, not the platform's every handle.
    """
    rows = (
        await session.execute(
            text(f"SELECT r.engine_kb_ref {_ROUTE_JOIN} s.agent_id = :aid"),
            {"aid": agent_id},
        )
    ).scalars()
    return {str(row) for row in rows}


async def _reconcile_engine_state(
    engine: VoiceEngine, engine_ref: str, *, agent_id: UUID, accounted: set[str]
) -> list[str] | None:
    """Refuse to publish onto an agent holding a copy no row of ours mentions.

    This is the only check that can see the failure our transaction cannot: the engine
    calls in `publish_source` are not part of it, so a COMMIT that fails after a
    successful attach discards every row while the engine keeps the document. What that
    leaves is a client whose agent answers from a version our tables say is not live,
    a superseded version our tables say IS live under a handle the engine already
    deleted, and a document nobody can address again — billed for as long as the account
    exists.

    Without this, the next publish attempt read the superseded version's stale handle,
    asked the engine to delete it, took the 404 and refused with `kb_detach_failed`,
    whose remediation reads "the previously approved version is still live. Try
    publishing again." Every clause of that is false, and it is worse than no message
    because it looks handled.

    **Evidence, not a dependency.** A listing we could not obtain proves nothing either
    way, so a failed listing is logged and stepped over rather than turning one flaky
    vendor read into an outage of the approval workflow. It can prove a divergence; it can
    never prove the absence of one.

    **THE `list_kb` CAVEAT THIS DOCSTRING CARRIED IS RETIRED (D-488).** It read that the
    method "filters strictly by agent and so degrades to an empty list if the engine's
    rows turn out not to carry that linkage". The rows never carried it — the linkage was
    always a property of the AGENT, and `list_kb` reads it there now. So an empty answer
    means the agent references nothing, which is a fact rather than a filter artefact.
    The adapter's own docstring carries the vendor evidence; naming the field here would
    put a vendor payload shape above the boundary.

    RETURNS the handles the engine reports, or `None` when the read failed — a third
    state the caller must not flatten into "none attached".
    """
    try:
        attached = await engine.list_kb(engine_ref)
    except Exception as exc:
        log.warning(
            "kb_reconcile_unavailable",
            extra={"agent_id": str(agent_id), "engine_error": type(exc).__name__},
        )
        # `None`, NOT `[]`. The caller uses this listing to decide whether a handle it
        # already holds is still attached, and an empty list would answer "it is gone" on
        # the strength of a read that did not happen — re-uploading a document that is
        # attached and leaving the first copy unaddressable. Three states, and the third
        # one is "we did not manage to look".
        return None
    unaccounted = [handle for handle in attached if handle not in accounted]
    if not unaccounted:
        return list(attached)
    log.error(
        "kb_engine_out_of_sync",
        extra={"agent_id": str(agent_id), "unaccounted": len(unaccounted)},
    )
    raise ProblemError(
        kind="business_rule",
        code="kb_engine_out_of_sync",
        title="The voice platform holds knowledge we cannot account for",
        detail=(
            "The voice platform is serving this agent a knowledge base that does not "
            "match our records, so publishing would add a second copy rather than "
            "replace it."
        ),
        remediation=(
            "Nothing changed. Ask support to reconcile this agent's knowledge on the "
            "voice platform — a previous update may have reached the platform without "
            "being recorded here. Retrying on its own will not clear it."
        ),
    )


async def _detach_superseded(
    session: AsyncSession,
    engine: VoiceEngine,
    engine_ref: str,
    source_id: UUID,
    engine_kb_ref: str,
    *,
    agent: AgentConfig,
    attached: list[str] | None,
) -> None:
    """Withdraw one attached copy from the engine, or refuse to publish.

    "One attached copy" is usually the superseded version and is sometimes this same
    source's own earlier copy — see `publish_source` on why a re-publish has one to
    withdraw. The decision below is identical in both cases, which is why they share
    this function.

    **The decision this function encodes: a detach that fails ABORTS the publish, and
    the previously approved version stays live.** The two alternatives are both worse.
    Continuing anyway is the defect being fixed — two versions attached, the agent free
    to answer from the older one, our tables reporting success. Detaching-and-carrying-on
    in the other direction (drop the old, publish nothing) would leave the client with no
    knowledge at all, which is an outage we caused to avoid an inconsistency.

    Refusing keeps the client whole: their agent still answers, from text a human
    approved. What they lose is the UPDATE, and they are told so. `kind` is inherited from
    the adapter's own error so a rate limit stays retryable and a rejection stays not.
    Since D-488 the retry is no longer free — the new version is attached by the time this
    runs — so `publish_source` compensates by removing it before it re-raises.

    A version we have no handle for is the same refusal for the same reason, raised one
    step earlier by `_require_addressable`: we cannot remove what we cannot address, so
    we must not publish over it.

    **A HANDLE THE ENGINE NO LONGER HOLDS IS A SUCCESS, NOT A FAILURE (D-488), and that
    is what makes a crashed publish self-heal.** This function's postcondition is "the
    engine is not serving that copy". `publish_source`'s engine calls are outside the
    transaction, so a process that dies between a successful detach and the COMMIT leaves
    our row naming a handle the engine has already dropped — and every later publish then
    refused with `kb_detach_failed`, whose remediation ("try publishing again") could
    never work. `attached` is the listing read moments earlier: a handle absent from it
    has reached the postcondition by another route and only our record needs clearing.
    `None` means the listing could not be read, and then the detach is attempted for real
    — never skipped on an assumption.
    """
    if attached is not None and engine_kb_ref not in attached:
        log.info(
            "kb_detach_already_done",
            extra={"source_id": str(source_id)},
        )
        await _remember_engine_kb_ref(session, source_id, None)
        return
    try:
        await engine.detach_kb(engine_ref, engine_kb_ref, agent=agent)
    except ProblemError as exc:
        log.warning(
            "kb_detach_failed", extra={"source_id": str(source_id), "engine_code": exc.code}
        )
        raise ProblemError(
            kind=exc.kind,
            code="kb_detach_failed",
            title="The previous version could not be withdrawn",
            detail=(
                "The voice platform did not confirm removal of the version this one "
                "replaces, so publishing would leave both live."
            ),
            remediation=(
                "Nothing changed — the previously approved version is still live. "
                "Try publishing again."
            ),
        ) from exc
    await _remember_engine_kb_ref(session, source_id, None)


async def _restore_withdrawn(
    engine: VoiceEngine,
    engine_ref: str,
    *,
    agent: AgentConfig,
    withdrawn: list[tuple[UUID, list[str]]],
    name: str,
) -> None:
    """Put back versions this publish withdrew, when a LATER step then failed.

    **THERE IS EXACTLY ONE CALLER AND THAT IS THE POINT (D-488).** Under attach-first,
    almost every failure happens before anything is withdrawn — a failed attach leaves the
    previous version untouched, and a failed detach is undone by removing the copy we
    added. The one failure that lands AFTER the withdrawals is the source vanishing from
    under us (`kb_source_vanished`): the retention sweep DELETEs superseded versions on the
    tenant's own clock, from its own transaction, taking no part in our lock, and FLOWS §7's
    rollback republishes exactly the population it expires. By then the superseded copies
    are gone from the engine, and walking away would leave the client with no knowledge at
    all — an outage we caused to report that somebody else deleted a row.

    WHAT IS DELIBERATELY NOT DONE HERE: recording the new handles. The caller re-raises,
    the transaction rolls back, and any write here would roll back with it — so our tables
    keep pointing at handles that were just deleted. That is the intended residue and it is
    caught twice over: the next publish either finds a handle the engine no longer holds
    (which `_detach_superseded` now treats as already withdrawn) or a copy it cannot
    account for (`kb_engine_out_of_sync`). Neither quietly stacks two versions.
    """
    for source_id, chunks in withdrawn:
        try:
            await engine.attach_kb(
                engine_ref,
                KBSourceRef(kb_id=str(source_id), title=name, text="\n\n".join(chunks)),
                agent=agent,
            )
        except Exception:
            # Nothing left to try: the engine is refusing both directions. ERROR, because
            # this agent now has NO knowledge for this source and only an operator can put
            # it back.
            log.error("kb_left_detached", extra={"source_id": str(source_id)})
        else:
            log.info("kb_restored_after_failed_publish", extra={"source_id": str(source_id)})


async def _undo_attach(
    engine: VoiceEngine,
    engine_ref: str,
    *,
    agent: AgentConfig,
    attached_ref: str | None,
    source_id: UUID,
) -> None:
    """Remove the copy this publish just attached, restoring the state it found.

    **THIS REPLACED `_reattach_after_failed_publish`, AND THE REPLACEMENT IS A CONSEQUENCE
    OF REVERSING THE ORDER (D-488), not a change of mind about compensation.** While the
    publish detached first, a failed attach left the agent with NOTHING and the old
    function put the superseded versions back. Now the attach happens first, so the only
    thing a failure can have added is the new copy, and the only compensation is to take
    it away — after which the agent is exactly as it was: the previously approved version,
    still attached, still the one a human signed off.

    `attached_ref is None` means the re-upload guard matched and no new copy was made; the
    handle then belongs to the version that was ALREADY live, and removing it would turn a
    failed update into an outage.

    IT SWALLOWS AND LOGS, for the reason every compensator does: it runs on a path that is
    already failing, and the caller's error is the one worth reporting. What it must never
    do is fail silently — an unremovable extra copy is a document a client's agent can
    still answer from, and only an operator can clear it now.
    """
    if attached_ref is None:
        return
    try:
        await engine.detach_kb(engine_ref, attached_ref, agent=agent)
    except Exception:
        log.error("kb_left_attached", extra={"source_id": str(source_id)})
    else:
        log.info("kb_attach_rolled_back", extra={"source_id": str(source_id)})


async def active_knowledge(session: AsyncSession, *, agent_id: UUID) -> list[KnowledgeFact]:
    """Everything this agent currently knows because a human approved and published it.

    The live version of each named source, whole and in reading order, ordered by name
    so the T0 compiler produces a stable block: ordering by `published_at` would
    reshuffle every fact each time one unrelated source was updated, minting a prompt
    version that changed nothing but line order.

    This is the half of the recompile that belongs to the KB — "what is live" is a
    question about `kb_sources.is_active`, which only `publish_source` ever sets — and
    it is the whole coupling. The block's FORMAT belongs to `agents/t0.py`, so nothing
    here knows what a prompt looks like and nothing there queries these tables.
    """
    rows = (
        await session.execute(
            text(
                "SELECT s.name, string_agg(d.content, ' ' ORDER BY d.idx) "
                "FROM kb_sources s JOIN kb_documents d ON d.source_id = s.id "
                "WHERE s.agent_id = :aid AND s.is_active = true "
                "GROUP BY s.id, s.name ORDER BY s.name"
            ),
            {"aid": agent_id},
        )
    ).all()
    return [KnowledgeFact(name=str(row[0]), text=str(row[1] or "")) for row in rows]


async def live_glosses(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID | None = None
) -> list[tuple[UUID, str, str]]:
    """(agent_id, source name, English gloss) for every LIVE source that has one.

    THE TWIN OF `active_knowledge`, AND THAT IS THE WHOLE POINT OF IT LIVING HERE. This
    module owns what "live" means — `s.is_active = true`, set by `publish_source` and by
    nothing else — and `retrieval/compiled_facts.py` must not re-derive it. Its own
    docstring already refuses to read `kb_documents` directly for exactly this reason
    ("re-deriving what is approved and live in a second place"), so the gloss is handed
    over the same way the knowledge itself is, by the module that decides it.

    ONLY GLOSSES OF LIVE SOURCES, SO THE APPROVAL GATE IS INHERITED RATHER THAN
    RE-ARGUED. A gloss of a rejected or superseded source is unreachable here for the same
    reason its original text is unreachable from the compiled block.

    `d.gloss IS NOT NULL` inside the aggregate rather than around it: a source whose Telugu
    chunks are glossed and whose one English chunk is `not_needed` should contribute the
    Telugu glosses, not vanish. `string_agg` skips NULLs anyway; the predicate is what keeps
    a source with NO glossed chunk out of the result entirely instead of returning an empty
    string that would score against every question.

    `s.tenant_id = :tid` is REDUNDANT WITH RLS AND IS STILL THERE, for the reason
    `compiled_facts._live_blocks` gives about its own copy: it defends a caller passing
    tenant A's id on a session opened for tenant B, which RLS cannot see as a mistake.
    """
    rows = (
        await session.execute(
            text(
                "SELECT s.agent_id, s.name, string_agg(d.gloss, ' ' ORDER BY d.idx) "
                "FROM kb_sources s JOIN kb_documents d ON d.source_id = s.id "
                "WHERE s.tenant_id = :tid AND s.is_active = true AND d.gloss IS NOT NULL "
                # Cast for `_live_blocks`' reason: an untyped placeholder inside `IS NULL`
                # gives Postgres nothing to infer from and it refuses the statement with
                # `AmbiguousParameter`. `CAST(... AS uuid)` and not `::`, which SQLAlchemy's
                # `text()` consumes as a bound-parameter marker.
                "AND (CAST(:aid AS uuid) IS NULL OR s.agent_id = CAST(:aid AS uuid)) "
                "GROUP BY s.agent_id, s.id, s.name"
            ),
            {"tid": tenant_id, "aid": agent_id},
        )
    ).all()
    return [(UUID(str(r[0])), str(r[1]), str(r[2])) for r in rows if r[2]]



async def _upload_row(session: AsyncSession, source_id: UUID) -> dict[str, Any] | None:
    """The `kb_uploads` row behind this source version, or None for pasted text.

    ONE READ, ONE MEANING: a source is either something a client TYPED (chunks in
    `kb_documents`, rendered to a PDF at publish) or something they UPLOADED (a document
    in object storage, or a link the engine scrapes). The `uq_kb_uploads_source` constraint
    is what lets this answer be a single row rather than a list.
    """
    row = (
        await session.execute(
            text(
                "SELECT source_kind, document_key, document_sha256, source_url, "
                "content_digest, ingest_status FROM kb_uploads WHERE source_id = :sid"
            ),
            {"sid": source_id},
        )
    ).first()
    if row is None:
        return None
    return {
        "source_kind": str(row[0]),
        "document_key": row[1],
        "document_sha256": row[2],
        "source_url": row[3],
        "content_digest": row[4],
        "ingest_status": str(row[5]),
    }


def _link_digest(*, url: str, content_digest: str | None) -> str:
    """The re-upload guard's key for a LINK, where there are no bytes of ours to hash.

    IT COVERS THE URL **AND** WHAT WE LAST READ AT IT, and both halves are load-bearing.
    The URL alone would make every re-ingest of a changed page look unchanged, so the
    publisher would keep the vendor's old scrape and the client's approval of the NEW text
    would change nothing an agent says — the exact silent failure the guard exists to
    prevent, inverted. `content_digest` alone would not distinguish two links that happen
    to serve the same text.

    It is not a claim about what the VENDOR scraped. Nothing can be: the engine fetches the
    page itself, on its own clock, and reports no digest. This is our own reading, and its
    only job is to tell "the same link, unchanged since we last published it" from
    everything else.
    """
    return hashlib.sha256(f"url:{url}:{content_digest or ''}".encode()).hexdigest()


async def _publish_payload(
    session: AsyncSession,
    source_id: UUID,
    *,
    name: str,
    language: str,
) -> tuple[bytes | None, str | None, str]:
    """What this publish hands the engine: `(document, source_url, digest)`.

    THE ONE BRANCH BETWEEN TYPED KNOWLEDGE AND AN UPLOAD, and it is deliberately the only
    one in the whole publish path. Everything downstream — the lock, the reconciliation,
    the attach-then-detach ordering, the digest guard, the claim row, the archive-and-
    activate flip, the T0 recompile — is identical for a pasted price list, a scanned menu
    and a link, because all three are `kb_sources` versions and this function is where they
    stop differing.

    * **Typed text** renders the approved chunks to a PDF, exactly as before.
    * **An uploaded document** is sent as the client's own bytes: the PDF they uploaded, or
      the PDF a `DocumentConverter` made from their Word file or photograph. NOT re-rendered
      — the artefact a human reviewed IS the document, and rendering a second one would
      publish something nobody read.
    * **A link** sends no bytes at all; the engine scrapes the page itself.

    THE DIGEST IS RECOMPUTED OVER THE BYTES WE ACTUALLY READ rather than trusted from the
    row. `kb_uploads.document_sha256` is written when the object is stored, and the object
    store is a different system with its own lifecycle: an object replaced, truncated or
    restored from a backup would otherwise keep a digest that says "already published" and
    the client's correction would never reach the engine. Hashing 20 MB costs milliseconds
    on a path that is about to spend minutes.
    """
    upload = await _upload_row(session, source_id)
    if upload is None:
        rendered = _render_document(
            title=name,
            chunks=await _approved_chunks_of(session, source_id, source_name=name),
            language=language,
        )
        return rendered.content, None, rendered.sha256

    if upload["source_kind"] == "url":
        url = str(upload["source_url"])
        return None, url, _link_digest(url=url, content_digest=upload["content_digest"])

    key = upload["document_key"]
    if not key:
        # The conversion has not finished (or could not). This is a REFUSAL rather than a
        # wait: publishing is a human's decision taken now, and "the document is not ready"
        # is a fact they can act on — the row's own status says which of the two it is.
        raise ProblemError.business_rule(
            "kb_document_not_ready",
            "That document is still being prepared for the voice platform.",
            remediation=(
                "Wait for the upload to finish processing, then publish it. If it says it "
                "failed, upload it again as a PDF."
            ),
        )
    # Deferred, as every other `apps/api` caller of the object store does it: boto3 is a
    # heavy import and this module is imported by the API's request path.
    from apps.workers.storage import read_kb_object

    document = await read_kb_object(str(key))
    if not document:
        log.error("kb_upload_object_missing", extra={"source_id": str(source_id)})
        raise ProblemError.business_rule(
            "kb_document_missing",
            "The uploaded file for this knowledge source is no longer available.",
            remediation="Upload the document again.",
        )
    digest = hashlib.sha256(document).hexdigest()
    if upload["document_sha256"] and upload["document_sha256"] != digest:
        # Not a refusal: the bytes in front of us are the bytes the client's agent will be
        # answering from, and they are what we hash. It IS worth an operator's attention,
        # because it means the object changed under a row that recorded it.
        log.warning("kb_upload_digest_moved", extra={"source_id": str(source_id)})
    return document, None, digest


async def publish_source(session: AsyncSession, *, tenant_id: UUID, source_id: UUID) -> int:
    """Push an APPROVED source to the engine KB and make it the active version.

    Order matters, in two directions:

    1. The engine work happens BEFORE the local activation flip. If the engine rejects
       it, nothing in our state claims the agent knows something it does not — the
       opposite order would leave a client's dashboard confidently wrong.
    2. **THE NEW COPY IS ATTACHED FIRST AND THE SUPERSEDED ONES ARE WITHDRAWN AFTER, AND
       THIS IS THE REVERSE OF WHAT THIS FUNCTION SHIPPED WITH (D-488).** The old order
       withdrew first and priced the gap at "one request of silence", which was true while
       `attach_kb` was a single call the engine either took or refused. It is not one call
       any more: on a real engine it is a document upload plus an indexing wait no vendor
       publishes a bound for, and the adapter's own budget for it is minutes rather than
       seconds. Detaching first would take a client's knowledge away for the whole of
       that, on every republish — the agent answering "I don't know" (T4
       refuse-and-escalate) to every caller for minutes because somebody corrected a
       price.

       The vendor references knowledge by a LIST of vector ids, so an overlap is
       expressible and a gap is not avoidable any other way. So the window MOVED rather
       than closed, and here is the honest statement of it: for the length of one detach
       round trip the agent can retrieve from either version. A stale price for one round
       trip is worse than nothing for one round trip; it is much better than nothing for
       three minutes.

       "Every superseded copy" includes THIS source's own previously attached one, which
       is not a subtlety. `attach_kb` is a CREATE — there is no update route on the
       vendor's knowledge base — so it mints a fresh handle on every call and
       de-duplicates nothing. Re-publishing a version that is already live would attach a
       second document and overwrite the only handle that could have removed the first,
       leaving it unaddressable, retrievable and billed forever. Two things stop that now:
       the re-upload guard (`_engine_kb_digest`), which skips the upload entirely when the
       rendered bytes and the attached handle both match, and the withdrawal below when
       they do not. The fake adapter cannot show either defect — it keys its store on OUR
       `kb_id` and returns a stable handle, so it silently replaces where a real engine
       accumulates.

    Eligibility is `approved_at IS NOT NULL`, not `status = 'approved'`, because
    FLOWS §7's rollback is republishing a version this same function ARCHIVED when its
    successor went live. Gating on the current status made that impossible: the archive
    step rewrites `status`, so the recovery path refused the only rows it exists for.
    Approval is a fact about a version that a later publish cannot erase; rejection
    never sets `approved_at`, so a rejected source still cannot reach an agent.

    3. T0 is RECOMPILED at the end, once the activation flip has decided what is live.
       FLOWS §7 used to list "T0 recompilation → engine KB sync" in that order and this
       function runs them the other way round: D-41 made the withdrawal a precondition of
       publishing at all, so the two steps are ordered by what each one READS — the
       recompile reads the activation flip, and the flip must not happen until the engine
       has accepted the new copy. The doc now lists them in this order. Without this step
       the whole publish changed only what the agent could
       RETRIEVE: `agents/t0.py` compiles the newly approved facts into the prompt's
       [T0 FACTS] block as a NEW prompt version, which is the tier TRD §6 says answers
       ~80% of questions at zero latency. It re-publishes the agent only if the agent
       is already live — a client publishing an FAQ must not promote an agent past
       FLOWS §1 step 7's human sign-off.

    WHAT HAPPENS IF THE PROCESS DIES MID-ROLLOVER, per step, because the engine calls are
    not in the transaction and no amount of ordering makes them so:

    * **Before the attach.** Nothing happened. The old version is live and addressable.
    * **Between the upload and the agent write** (inside `attach_kb`). The adapter deletes
      the document it just created and re-raises; nothing is attached and nothing is
      billed. A death inside THAT window leaves an unreferenced knowledge base, which
      costs money and is invisible to `list_kb` — the account-level sweep (OPERATIONS §2
      gate 43e) is what finds it.
    * **Between the attach and the detach.** Both versions are attached and no row of ours
      changed. The agent can answer from either — the overlap window, made permanent. The
      next publish reads the engine, cannot account for the new handle, and REFUSES with
      `kb_engine_out_of_sync` rather than stacking a third copy; an operator clears it.
    * **Between the detach and the COMMIT.** The old copy is gone and our rows still name
      its handle. This used to poison every later publish with `kb_detach_failed` and a
      remediation that could not work; since D-488 `_detach_superseded` treats a handle
      the engine no longer holds as its own postcondition, so the next publish clears the
      record and proceeds. Self-healing, and the only cost is the update that was lost.
    * **After the COMMIT.** Done. The T0 recompile below is the only step left and it is
      idempotent.

    The one thing that is genuinely not recoverable inside this function is a COMMIT that
    fails after a successful attach: the engine holds a document none of our rows mention.
    `_reconcile_engine_state` cannot prevent it — nothing here can — but it detects it on
    the next attempt and refuses instead of attaching a second copy on top.
    """
    row = (
        await session.execute(
            text(
                "SELECT s.agent_id, s.name, s.status, s.version, s.approved_at, "
                "a.engine_agent_ref FROM kb_sources s JOIN agents a ON a.id = s.agent_id "
                "WHERE s.id = :sid"
            ),
            {"sid": source_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Knowledge source")
    agent_id, name, status, version, approved_at, engine_ref = row
    if approved_at is None or status not in ("approved", "archived"):
        raise ProblemError.business_rule(
            "kb_not_approved",
            "A knowledge source must be approved before it can go live.",
            remediation="Approve it from the admin console first.",
        )
    if not engine_ref:
        raise ProblemError.business_rule(
            "agent_not_published",
            "Publish the agent to the voice platform before adding knowledge.",
        )

    # BEFORE the first read of `is_active` and before the first engine call: everything
    # from here to COMMIT is one publisher's, per agent. `agent_id` is read above rather
    # than under the lock because nothing in this repository ever rewrites it on an
    # existing row — the columns that move (`status`, `is_active`, `approved_at`) are all
    # read after it.
    await _lock_agent_publishes(session, agent_id=agent_id)

    chunks = await _chunks_of(session, source_id)

    engine = get_engine()
    # BEFORE anything is withdrawn (D-93). This whole function is built around an engine
    # with a built-in knowledge base: it detaches the superseded version, attaches the new
    # one, and records the engine's handle. On an engine that has none, every one of those
    # calls refuses — and finding that out THREE calls in would mean discovering it after
    # `_detach_superseded` had already withdrawn the live version, i.e. taking a client's
    # knowledge down in order to report that we could not replace it.
    #
    # Refusing here is the cheap, correct half. The expensive half is NOT done and is not
    # pretended: an engine with no knowledge base does not mean this client loses their
    # knowledge, it means T3 retrieval has to come from our own in-call RAG tool endpoint
    # while T0 keeps working (the [T0 FACTS] recompile below is engine-independent and
    # would still carry the ~80% of questions TRD §6 assigns it). Building that fallback
    # is a decision-log entry and a milestone, not a line in this function.
    require_capability("knowledge_base", engine=engine)
    # The configuration a publish of THIS agent would send. Resolved before any vendor
    # call because attaching is an agent write on a control-plane engine (see
    # `_publish_config`), and an agent we cannot describe is one we must not rewrite.
    agent_config = await _publish_config(session, tenant_id, agent_id)
    superseded = await _superseded_versions(
        session, agent_id=agent_id, name=str(name), keep=source_id
    )
    _require_addressable(superseded)
    attached_now = await _reconcile_engine_state(
        engine,
        engine_ref,
        agent_id=agent_id,
        accounted=await recorded_handles_of_agent(session, agent_id),
    )

    # Everything to withdraw once the new copy is up: the other live version(s) of this
    # named source, plus this source's own earlier copy when the content has moved.
    #
    # `engine_kb_ref IS NULL` means two different things depending on whose row it is,
    # which is why the own-handle case is appended here rather than folded into
    # `_superseded_versions`. On a DIFFERENT version that is still live it means the
    # engine is serving something we cannot name — a refusal (`_require_addressable`).
    # On the version being published it means we have attached nothing yet, which is
    # every first publish and must proceed silently.
    withdraw: list[tuple[UUID, str]] = [
        (previous_id, str(handle)) for previous_id, handle in superseded
    ]
    own_handle = await _engine_kb_ref(session, source_id)

    # THE DOCUMENT, AND ITS DIGEST (D-488). Rendered before anything is touched, because
    # a renderer that refuses must do so while the client's knowledge is still whole
    # rather than half way through a rollover.
    #
    # NO LONGER OPTIONAL, AND THAT IS THE SEAM BEING FINISHED RATHER THAN A NEW RULE:
    # `_render_document` used to return `None` when the renderer module was missing, and
    # it was ALWAYS missing, because the seam named `apps.api.kb.render` and the module
    # that shipped is `apps.api.kb.pdf_render` with a different signature. Every engine
    # that ingests files therefore refused every publish. The renderer is now imported
    # directly and `fpdf2` is a declared runtime dependency of `apps/api`, so "there is
    # no renderer" is not a state this deployment can be in; a refusal now comes from
    # the CONTENT and says which chunk.
    document, source_url, digest = await _publish_payload(
        session,
        source_id,
        name=str(name),
        language=agent_config.language_primary,
    )

    # THE RE-UPLOAD GUARD. Three conditions, and all three are load-bearing: we hold a
    # handle, the bytes are the ones that handle was minted from, and the engine still
    # reports it attached. Any one of them missing and a fresh upload is the safe answer —
    # the vendor has no update route, so an attach is a CREATE that mints a new object and
    # de-duplicates nothing — no engine this port describes offers an update. This is
    # double-clicked Publish, a retry after a timeout, and FLOWS §7's rollback onto the
    # version already live cost nothing instead of stacking a second billed copy the first
    # handle could never name again.
    # `digest` is no longer part of this conjunction: it was `str | None` while the
    # renderer was optional, and it is now always a digest. An arm that cannot be false
    # is an uncovered branch the ratchet counts and a reader has to reason about twice.
    unchanged = (
        own_handle is not None
        and await _engine_kb_digest(session, source_id) == digest
        and (attached_now is None or own_handle in attached_now)
    )
    attached_ref: str
    minted: str | None = None
    if unchanged and own_handle is not None:
        log.info("kb_upload_skipped_unchanged", extra={"source_id": str(source_id)})
        attached_ref = own_handle
    else:
        if own_handle is not None:
            withdraw.append((source_id, own_handle))
        # ATTACH FIRST, DETACH SECOND — THE OPPOSITE OF THE ORDER THIS FUNCTION SHIPPED
        # WITH, and the reversal is forced by what an attach became (D-488). It used to be
        # a single call, so detaching first cost "one request of silence". A real attach is
        # an upload plus an indexing wait the vendor gives no bound for — up to
        # `KB_READY_TIMEOUT_S`, three minutes — and detaching first would take the client's
        # knowledge away for ALL of it, on every republish. The engine references knowledge
        # by a LIST of vector ids, so holding both for the length of one detach round trip
        # is expressible; holding neither for three minutes is what the old order buys.
        #
        # SO THE WINDOW MOVED RATHER THAN CLOSED, and the honest statement of it is: for
        # one detach round trip the agent can retrieve from either version. That is the
        # cheaper failure than a blank agent, and much cheaper than a blank one for
        # minutes. A crash inside that window leaves both attached and our rows unchanged,
        # which the next publish REFUSES on (`kb_engine_out_of_sync`) rather than silently
        # stacking a third — see this function's closing note.
        minted = await engine.attach_kb(
            engine_ref,
            KBSourceRef(
                kb_id=str(source_id),
                title=str(name),
                text="\n\n".join(chunks),
                document=document,
                content_sha256=digest,
                source_url=source_url,
            ),
            agent=agent_config,
        )
        attached_ref = minted

    # NEVER WITHDRAW THE HANDLE WE JUST ATTACHED, and this is a consequence of the order
    # rather than defensive noise (D-488). Under detach-first the two sets could not
    # overlap; under attach-first they can, on any engine that de-duplicates — hand it two
    # uploads it considers the same document and it may hand back one id, and the
    # withdrawal of "the old copy" would then delete the new one. The fake adapter does
    # exactly that (its handle is derived from OUR `kb_id`), which is how this was found;
    # a real engine that ever behaved the same way would take a client's knowledge down
    # silently, because every one of our records would still look right.
    withdraw = [(wid, handle) for wid, handle in withdraw if handle != attached_ref]

    # Read the fallback text BEFORE anything is withdrawn, for `_restore_withdrawn`'s one
    # caller: a query issued after the failure is a query issued on a session that may
    # itself be the thing that failed.
    withdrawn_chunks: list[tuple[UUID, list[str]]] = [
        (withdrawn_id, await _chunks_of(session, withdrawn_id)) for withdrawn_id, _ in withdraw
    ]

    for withdrawn_id, withdrawn_kb_ref in withdraw:
        try:
            await _detach_superseded(
                session,
                engine,
                engine_ref,
                withdrawn_id,
                withdrawn_kb_ref,
                agent=agent_config,
                attached=attached_now,
            )
        except Exception:
            # The new copy is up and a superseded one would not come down, so the agent is
            # holding both. Put it back the way it was — remove what we just added — and
            # re-raise the refusal `_detach_superseded` composed. The client keeps the
            # version a human approved and loses only the update.
            await _undo_attach(
                engine,
                engine_ref,
                agent=agent_config,
                attached_ref=minted,
                source_id=source_id,
            )
            raise

    await _remember_engine_kb_ref(session, source_id, attached_ref, digest=digest)

    # Archive the previous active version of this named source, then activate this one.
    # Rollback (FLOWS §7) is re-running publish on the archived row, which is why the
    # activation restores `status` as well as `is_active` — a live version left marked
    # `archived` is a row that contradicts itself on every screen that reads it.
    await session.execute(
        text(
            "UPDATE kb_sources SET is_active = false, status = 'archived', updated_at = now() "
            "WHERE agent_id = :aid AND name = :name AND is_active = true AND id <> :sid"
        ),
        {"aid": agent_id, "name": name, "sid": source_id},
    )
    activated = await session.execute(
        text(
            "UPDATE kb_sources SET is_active = true, status = 'approved', "
            "published_at = now(), updated_at = now() WHERE id = :sid"
        ),
        {"sid": source_id},
    )
    if rowcount_of(activated) == 0:
        # THE SOURCE VANISHED UNDER US, and this used to be silent (D-380). The row is
        # read at the top of this function without a row lock, and the retention sweep's
        # knowledge arm (`workers/retention._KB_EXPIRE_SQL`, D-179) DELETEs superseded and
        # rejected versions on the tenant's own clock — from its own transaction, taking
        # no part in `_lock_agent_publishes`. FLOWS §7's rollback is a publish of an
        # ARCHIVED row, which is exactly the population that arm expires (and the row
        # qualifies: `_KB_EXPIRABLE` skips versions that still hold an `engine_kb_ref`,
        # and an archived one does not). So a rollback racing the nightly sweep is not a
        # contrived interleaving: the DELETE commits, this UPDATE matches nothing, and the
        # function used to carry on and RETURN THE VERSION NUMBER — a reported success for
        # a publish that changed no row of ours while the engine had already been handed
        # the document.
        #
        # Everything downstream inherited that lie: `_remember_engine_kb_ref` wrote to
        # `kb_documents` rows the FK CASCADE had taken with the source, `active_knowledge`
        # recompiled T0 without the source, and the engine was left holding a copy nothing
        # of ours could name, bill against or ever detach.
        #
        # SO IT IS COMPENSATED, NOT ONLY REFUSED. The attach is undone and the versions
        # withdrawn for it are put back — the same restoration a failed attach performs,
        # for the same reason: the client keeps a working knowledge base and loses only
        # the update. The raise then rolls our side back.
        log.error("kb_publish_source_vanished", extra={"source_id": str(source_id)})
        # BOTH HALVES, because this is the ONE failure that lands after the withdrawals.
        # The copy this publish added comes down (`minted`; `None` when the re-upload
        # guard matched, in which case the handle belongs to the version that was already
        # live and removing it would turn a lost race into an outage), and the versions
        # withdrawn for it go back — otherwise the client is left with no knowledge at all
        # because somebody else's transaction deleted a row.
        await _undo_attach(
            engine,
            engine_ref,
            agent=agent_config,
            attached_ref=minted,
            source_id=source_id,
        )
        await _restore_withdrawn(
            engine,
            engine_ref,
            agent=agent_config,
            withdrawn=withdrawn_chunks,
            name=str(name),
        )
        raise ProblemError.conflict(
            "kb_source_vanished",
            "That knowledge version was removed while it was being published.",
            remediation=(
                "Nothing changed — the previously approved version is still live. "
                "Submit the wording again if it is still needed."
            ),
        )

    # THE RETRIEVAL PROJECTION (D-502), between the activation flip and the T0 recompile
    # and for the flip's own reason: it reads what the flip just decided. Same transaction
    # as the publish, which is the property `docs/evidence/kb-retrieval-bakeoff.md` §5.2
    # picked pgvector for — with a store across a network boundary, "our tables say
    # published" and "the store says otherwise" are two commits and D-41 is the record of
    # what that divergence costs.
    await project_chunks(session, tenant_id=tenant_id, agent_id=agent_id, source_id=source_id)

    # T0 recompilation (FLOWS §7, TRD §6). LAST, and after the activation flip, because
    # `active_knowledge` reads exactly what the flip just decided — computing it earlier
    # would compile the set this publish is replacing. `recompile_t0` mints a NEW prompt
    # version (never edits the live one) and returns None when the block is unchanged,
    # so a rollback onto the version already live stays free.
    prompt_version = await recompile_t0(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        knowledge=await active_knowledge(session, agent_id=agent_id),
    )
    log.info(
        "kb_published",
        extra={
            "source_id": str(source_id),
            "version": version,
            "prompt_version": prompt_version,
        },
    )
    return int(version)


#: The sparse retrieval key, built from the chunk's own text AND its English gloss. It MUST
#: spell the same text-search configuration as migration `dc1aaeeeff02.TS_CONFIG` and
#: `retrieval/pgvector.TS_CONFIG`: lexemes stored under one configuration do not match a
#: `tsquery` built under another, and the symptom is an empty sparse arm rather than an
#: error. `coalesce` because most chunks have no gloss and `||` with NULL erases the vector.
_TSV_SQL = "to_tsvector('english', d.content) || to_tsvector('english', coalesce(d.gloss, ''))"

#: Insert or refresh one source's projection. `ON CONFLICT (document_id)` is what makes a
#: republish idempotent in the DATABASE rather than in a read-then-write, and it is also
#: what makes a rollback correct: reactivating an archived version finds its rows already
#: there and flips them back rather than minting duplicates that would each take a slot in
#: the top-k.
#:
#: **`tsv` IS RECOMPUTED ON CONFLICT AND `embedding` IS NOT TOUCHED.** The text a chunk
#: holds cannot change under it (`kb_documents.content` is written once at submission), but
#: its GLOSS can arrive hours later on the sweep's clock, and a projection written before
#: the gloss would carry only half its sparse key for ever. The vector is left alone because
#: re-embedding costs money and nothing about the text moved — the sweep re-reaches a row
#: only when `embed_state` says so.
_PROJECT_SQL = f"""
INSERT INTO kb_chunks (id, tenant_id, agent_id, source_id, document_id, tsv, version, is_active)
SELECT gen_random_uuid(), d.tenant_id, s.agent_id, s.id, d.id, {_TSV_SQL}, s.version, s.is_active
FROM kb_documents d JOIN kb_sources s ON s.id = d.source_id
WHERE s.id = :sid AND s.tenant_id = :tid
ON CONFLICT (document_id) DO UPDATE
SET tsv = EXCLUDED.tsv, version = EXCLUDED.version, is_active = EXCLUDED.is_active,
    agent_id = EXCLUDED.agent_id, updated_at = now()
"""

#: Every OTHER version of this agent's knowledge goes inactive in the projection, mirroring
#: the `kb_sources` flip immediately above. Written as its own statement over the AGENT
#: rather than as a join from the archived source, so a version archived by any path — this
#: publish, a rollback, an operator — converges on the next publish instead of leaving a
#: superseded price list answering questions.
_DEACTIVATE_SQL = """
UPDATE kb_chunks c SET is_active = s.is_active, updated_at = now()
FROM kb_sources s
WHERE s.id = c.source_id AND c.tenant_id = :tid AND c.agent_id = :aid
  AND c.is_active <> s.is_active
"""


async def project_chunks(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID, source_id: UUID
) -> int:
    """Mirror this agent's published knowledge into `kb_chunks`. Returns rows projected.

    THE ONE WRITER of the projection's SHAPE (the sweep writes only vectors and states), and
    it lives in `kb/service.py` rather than in `retrieval/` on purpose: what is retrievable
    is defined by what was APPROVED and PUBLISHED, and that is this module's subject. A
    projection written from the retrieval side would be a second answer to "what is live",
    which is the drift CLAUDE.md calls a defect even while both copies agree.

    IT RUNS IN THE CALLER'S TRANSACTION and takes no lock of its own: `publish_source` is
    already inside `_lock_agent_publishes`, so two publishes of one agent cannot interleave
    here, and the unique index on `document_id` is what makes it safe against everything
    else.

    `tenant_id` is re-stated on both statements on top of RLS — belt over braces, defending
    the one mistake RLS cannot see: a caller passing tenant A's id on tenant B's session.
    """
    projected = await session.execute(text(_PROJECT_SQL), {"sid": source_id, "tid": tenant_id})
    await session.execute(text(_DEACTIVATE_SQL), {"tid": tenant_id, "aid": agent_id})
    count = rowcount_of(projected)
    # Ids and counts (hard rule 6). Never a chunk, never a source name.
    log.info(
        "kb_chunks_projected",
        extra={"source_id": str(source_id), "agent_id": str(agent_id), "chunks": count},
    )
    return count


async def list_sources(
    session: AsyncSession, *, status: str | None = None, limit: int = 200
) -> list[dict[str, Any]]:
    """The tenant's sources, newest activity first; `status` filters, RLS scopes.

    A status this column cannot hold is REFUSED rather than answered with `[]`. The
    filter feeds the admin console's approval queue, and an empty list is a positive
    claim — "nobody is waiting for you" — which is the one answer a reviewer acts on by
    doing nothing. A typo or a renamed status returning that claim is how a queue goes
    unread. `KB_STATUSES` is the same tuple the column's CHECK constraint is built from,
    so the API and the database cannot disagree about what a status is.
    """
    if status is not None and status not in KB_STATUSES:
        raise ProblemError(
            kind="validation",
            code="kb_status_unknown",
            title="Unknown status filter",
            # The caller's own value, echoed so a typo is obvious, TRUNCATED so an
            # unbounded query string cannot be reflected back through the error shape
            # (the `RequestValidationError` handler drops `input` for the same reason).
            detail=f"There is no knowledge-source status called {status[:40]!r}.",
            remediation=f"Use one of: {', '.join(KB_STATUSES)}.",
            status=422,
        )
    clause = "WHERE status = :status" if status else ""
    rows = (
        await session.execute(
            text(
                "SELECT id, agent_id, name, kind, status, version, is_active, published_at, "
                "(SELECT count(*) FROM kb_documents d WHERE d.source_id = kb_sources.id) "
                f"FROM kb_sources {clause} ORDER BY updated_at DESC LIMIT :limit"
            ),
            {"status": status, "limit": limit} if status else {"limit": limit},
        )
    ).all()
    return [
        {
            "id": r[0],
            "agent_id": r[1],
            "name": r[2],
            "kind": r[3],
            "status": r[4],
            "version": r[5],
            "is_active": r[6],
            "published_at": r[7],
            "chunks": int(r[8] or 0),
        }
        for r in rows
    ]


__all__ = [
    "MAX_CHUNK_CHARS",
    "SUPPORTED_SUBMISSION_KINDS",
    "active_knowledge",
    "approve_source",
    "chunk_text",
    "list_sources",
    "preview",
    "project_chunks",
    "publish_lock_key",
    "publish_source",
    "recorded_handles_of_agent",
    "reject_source",
    "submit_source",
]
