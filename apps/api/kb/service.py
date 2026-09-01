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
from importlib import import_module
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

    chunks = chunk_text(body)
    if not chunks:
        raise ProblemError(
            kind="validation",
            code="kb_empty",
            title="Nothing to add",
            detail="The submitted content is empty.",
        )

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

    source_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO kb_sources (id, tenant_id, agent_id, kind, name, uri, status, "
            "version, submitted_by, is_active, created_at, updated_at) VALUES (:id, :tid, "
            ":aid, :kind, :name, :uri, 'pending_approval', :version, :by, false, now(), now())"
        ),
        {
            "id": source_id,
            "tid": tenant_id,
            "aid": agent_id,
            "kind": kind,
            "name": name,
            "uri": uri,
            "version": version,
            "by": submitted_by,
        },
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
        "status": "pending_approval",
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
            text("SELECT idx, content FROM kb_documents WHERE source_id = :sid ORDER BY idx"),
            {"sid": source_id},
        )
    ).all()
    return [{"idx": r[0], "content": r[1], "chars": len(r[1])} for r in rows]


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


async def _engine_kb_ref(session: AsyncSession, source_id: UUID) -> str | None:
    """The engine's handle for this source's attached copy, or None if nothing of ours
    is attached. See `_remember_engine_kb_ref` for why it lives where it lives."""
    value = (
        await session.execute(
            text(
                "SELECT meta ->> 'engine_kb_ref' FROM kb_documents "
                "WHERE source_id = :sid AND idx = 0"
            ),
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
            text(
                "SELECT meta ->> 'engine_kb_digest' FROM kb_documents "
                "WHERE source_id = :sid AND idx = 0"
            ),
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

    It lives in `kb_documents.meta` because that is where the migration that created
    these tables put it: "Provider-side document and namespace ids land in
    `kb_documents.meta`, which is also what lets a DPDP erasure prove it removed both
    copies." A source is pushed to the engine as ONE document, so the handle hangs off
    its first chunk. No column is added for it — a new column is a migration, and this
    fix is not worth coupling to one when the designed home already exists.

    Clearing on detach is not tidiness: a handle left behind after the engine copy is
    gone is a handle a later publish would try to delete, and that publish would then
    refuse for a reason that is no longer true.
    """
    if engine_kb_ref is None:
        # THE DIGEST GOES WITH IT, and that is not tidiness either: a digest left behind
        # after the handle is cleared is a claim that the engine holds this exact document
        # under a handle we no longer have, which is precisely the state the re-upload
        # guard reads as "nothing to do".
        await session.execute(
            text(
                "UPDATE kb_documents SET meta = coalesce(meta, '{}'::jsonb) "
                "- 'engine_kb_ref' - 'engine_kb_digest', "
                "updated_at = now() WHERE source_id = :sid AND idx = 0"
            ),
            {"sid": source_id},
        )
        return
    await session.execute(
        text(
            "UPDATE kb_documents SET meta = coalesce(meta, '{}'::jsonb) || "
            "jsonb_build_object('engine_kb_ref', to_jsonb(cast(:ref as text)), "
            "'engine_kb_digest', to_jsonb(cast(:digest as text))), "
            "updated_at = now() WHERE source_id = :sid AND idx = 0"
        ),
        {"sid": source_id, "ref": engine_kb_ref, "digest": digest},
    )


#: What the publisher hands an engine whose knowledge base ingests FILES rather than
#: text, and the one place this module knows a document format exists at all.
#:
#: **THE MODULE IS A SIBLING'S AND THIS IS ONLY THE SEAM.** The contract it must satisfy,
#: stated here because two changes have to agree and only one of them is in this file:
#:
#:     apps/api/kb/render.py
#:     def render_knowledge_pdf(*, title: str, chunks: list[str], language: str) -> bytes
#:
#: DETERMINISTIC, and that word is load-bearing rather than decorative: the re-upload
#: guard below keys on the SHA-256 of these bytes, so a renderer that stamps a timestamp,
#: a uuid or a hash-seeded font subset into the file makes every republish look like new
#: content and uploads a duplicate every time. It must also render exactly the approved
#: chunks in reading order and add nothing a human did not approve.
#:
#: RESOLVED BY NAME AT CALL TIME. A missing renderer is a deployment fact, not a client's
#: mistake, and it surfaces BEFORE anything is uploaded or withdrawn — which is where this
#: is called from. `importlib` rather than a
#: deferred `from ... import`, because the module is a SIBLING's and is not in this tree
#: yet: a static import of a module that does not exist fails type checking, and silencing
#: that with an ignore leaves a lie behind on the day it lands.
_RENDERER_MODULE = "apps.api.kb.render"
_RENDERER_FUNCTION = "render_knowledge_pdf"


def _render_document(*, title: str, chunks: list[str], language: str) -> bytes | None:
    """The approved chunks as the document an engine will ingest, or `None`.

    **`None` IS NOT A SHRUG AND IT IS NOT A SILENT DEGRADATION — read where it goes.** Not
    every engine's knowledge base ingests files: the port carries both, `KBSourceRef.text`
    for the ones that take prose and `.document` for the ones that take a document, and an
    adapter that NEEDS a document and is handed `None` refuses by NAME
    (`engine_kb_document_missing`) before a byte reaches the vendor. So the loud failure
    happens where the requirement actually lives, and the publisher does not have to know
    which kind of engine it is talking to.

    RAISING HERE INSTEAD WOULD BE THE WRONG PLACE, and it is worth saying why, because
    that was the first shape of this function: a deployment whose engine ingests text
    would then be unable to publish knowledge at all because a renderer it never needed
    was missing. The refusal belongs to the adapter that cannot proceed, not to every
    caller of this module.

    It is logged at ERROR either way. A missing renderer is a deployment fault and
    somebody has to be told, whether or not this particular engine minds.
    """
    try:
        renderer = getattr(import_module(_RENDERER_MODULE), _RENDERER_FUNCTION)
    except (ImportError, AttributeError):
        log.error("kb_renderer_unavailable", extra={"renderer": _RENDERER_MODULE})
        return None
    document = renderer(title=title, chunks=chunks, language=language)
    # CHECKED, because a dynamically resolved callable is unchecked by construction and
    # this one's output goes straight into a multipart upload. `str` is the likely wrong
    # answer and would be encoded to plausible-looking bytes by httpx without a word.
    if not isinstance(document, bytes) or not document:
        log.error("kb_renderer_returned_no_document", extra={"renderer": _RENDERER_MODULE})
        raise ProblemError(
            kind="dependency",
            code="kb_renderer_unavailable",
            title="Knowledge cannot be published right now",
            detail="The approved wording could not be turned into a document.",
            remediation="Nothing changed. Support has been alerted.",
        )
    return document


def _digest_of(document: bytes) -> str:
    """The idempotency key: hex SHA-256 over the rendered bytes.

    OVER THE DOCUMENT AND NOT OVER THE CHUNKS, because the document is what the vendor
    was handed. Two chunk lists that render identically SHOULD be treated as one upload,
    and a renderer change that alters the bytes SHOULD force a fresh one — hashing the
    input would get both of those backwards.

    SHA-256 rather than anything cheaper: this decides whether a client's newly approved
    text reaches their agent, so a collision is a silently unpublished approval.
    """
    return hashlib.sha256(document).hexdigest()


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
    """
    rows = (
        await session.execute(
            text(
                "SELECT d.meta ->> 'engine_kb_ref' FROM kb_documents d "
                "JOIN kb_sources s ON s.id = d.source_id "
                "WHERE s.agent_id = :aid AND d.idx = 0 "
                "AND d.meta ->> 'engine_kb_ref' IS NOT NULL"
            ),
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
    # a deployment with no renderer must refuse while the client's knowledge is still
    # whole rather than half way through a rollover.
    document = _render_document(
        title=str(name), chunks=chunks, language=agent_config.language_primary
    )
    # `None` when this deployment has no renderer — see `_render_document`. The engine that
    # needs one then refuses by name; the engine that ingests text carries on as it always
    # has, and its re-upload guard has nothing to key on, which is the state it was in
    # before D-488 rather than a regression.
    digest = _digest_of(document) if document is not None else None

    # THE RE-UPLOAD GUARD. Three conditions, and all three are load-bearing: we hold a
    # handle, the bytes are the ones that handle was minted from, and the engine still
    # reports it attached. Any one of them missing and a fresh upload is the safe answer —
    # the vendor has no update route, so an attach is a CREATE that mints a new object and
    # de-duplicates nothing — no engine this port describes offers an update. This is
    # double-clicked Publish, a retry after a timeout, and FLOWS §7's rollback onto the
    # version already live cost nothing instead of stacking a second billed copy the first
    # handle could never name again.
    unchanged = (
        digest is not None
        and own_handle is not None
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
    "publish_lock_key",
    "publish_source",
    "recorded_handles_of_agent",
    "reject_source",
    "submit_source",
]
