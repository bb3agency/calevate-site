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

import re
from typing import Any
from uuid import UUID

from calevate_shared.engine import KBSourceRef, VoiceEngine
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.t0 import KnowledgeFact, recompile_t0
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.db.transition import transition_status
from apps.api.engine import get_engine, require_capability

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
    that exceeds the cap on its own, and then on sentence ends."""
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
        if len(buffer) + len(paragraph) + 2 <= MAX_CHUNK_CHARS:
            buffer = f"{buffer}\n\n{paragraph}" if buffer else paragraph
        else:
            chunks.append(buffer)
            buffer = paragraph
    if buffer:
        chunks.append(buffer)
    # Fold a stub tail into its predecessor: a two-word chunk retrieves noisily.
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
        else:
            if buffer:
                out.append(buffer)
            buffer = sentence[:MAX_CHUNK_CHARS]
    if buffer:
        out.append(buffer)
    return out


async def _assert_agent_is_ours(session: AsyncSession, agent_id: UUID) -> None:
    """Refuse an agent this session's tenant cannot see.

    Row-level security does not cover this on its own, and the two places it does not
    reach are both on this INSERT.

    `kb_sources.agent_id` is a FOREIGN KEY, and PostgreSQL runs referential-integrity
    checks with row security bypassed — that is deliberate on their side, so integrity
    cannot be defeated by visibility. The consequence here is that a row carrying tenant
    B's `tenant_id` (which the policy's WITH CHECK does enforce) may name tenant A's
    agent, and the insert succeeds.

    `(agent_id, name, version)` is a UNIQUE INDEX, and unique indexes are likewise
    evaluated over every row in the table rather than the visible ones. So that
    unauthorised row takes a slot tenant A can no longer use: A's own submission then
    fails on a constraint violation caused by a row A cannot see, cannot list and cannot
    delete — a cross-tenant denial of service, plus an existence oracle for B, who
    learns from the error whether A already holds a source of that name.

    The read below is the fix and it must stay a READ, executed on the caller's own
    session: `agents` is FORCE-RLS'd, so "visible here" is exactly "this tenant's".
    Comparing the caller-supplied `tenant_id` against something else the caller supplied
    would prove nothing about the database.
    """
    visible = (
        await session.execute(text("SELECT 1 FROM agents WHERE id = :aid"), {"aid": agent_id})
    ).scalar()
    if visible is None:
        raise ProblemError.not_found("Agent")


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

    await _assert_agent_is_ours(session, agent_id)

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


async def _remember_engine_kb_ref(
    session: AsyncSession, source_id: UUID, engine_kb_ref: str | None
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
        await session.execute(
            text(
                "UPDATE kb_documents SET meta = coalesce(meta, '{}'::jsonb) - 'engine_kb_ref', "
                "updated_at = now() WHERE source_id = :sid AND idx = 0"
            ),
            {"sid": source_id},
        )
        return
    await session.execute(
        text(
            "UPDATE kb_documents SET meta = coalesce(meta, '{}'::jsonb) || "
            "jsonb_build_object('engine_kb_ref', to_jsonb(cast(:ref as text))), "
            "updated_at = now() WHERE source_id = :sid AND idx = 0"
        ),
        {"sid": source_id, "ref": engine_kb_ref},
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


async def _recorded_handles_of_agent(session: AsyncSession, agent_id: UUID) -> set[str]:
    """Every engine handle we believe is attached to this agent, across all its sources.

    Agent-wide rather than per-name: an agent's KB is several named sources, and the
    question the reconciliation asks is "can we account for everything the engine is
    holding", which no single name can answer.
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
) -> None:
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
    way, and `list_kb` is the adapter method whose response shape stays a hand-maintained
    claim until pilot gate 8 — the adapter filters strictly by agent and so degrades to
    an empty list if the engine's rows turn out not to carry that linkage. Refusing on
    "we did not manage to look" would turn one flaky vendor read into an outage of the
    approval workflow, so a failed listing is logged and stepped over. It can prove a
    divergence; it can never prove the absence of one.
    """
    try:
        attached = await engine.list_kb(engine_ref)
    except Exception as exc:
        log.warning(
            "kb_reconcile_unavailable",
            extra={"agent_id": str(agent_id), "engine_error": type(exc).__name__},
        )
        return
    unaccounted = [handle for handle in attached if handle not in accounted]
    if not unaccounted:
        return
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
    approved. What they lose is the UPDATE, and they are told so, with a retry that
    costs nothing — the engine is idempotent from our side here because we have not
    attached anything yet. `kind` is inherited from the adapter's own error so a rate
    limit stays retryable and a rejection stays not.

    A version we have no handle for is the same refusal for the same reason, raised one
    step earlier by `_require_addressable`: we cannot remove what we cannot address, so
    we must not publish over it.
    """
    try:
        await engine.detach_kb(engine_ref, engine_kb_ref)
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


async def _reattach_after_failed_publish(
    engine: VoiceEngine,
    engine_ref: str,
    name: str,
    detached: list[UUID],
    chunks_of: dict[UUID, list[str]],
) -> None:
    """Close the gap the detach-first ordering opens when the ATTACH then fails.

    At this point the agent holds no copy of this source. The previous version's text is
    still in our tables and is still approved, so putting it back restores a state a
    human signed off on — the client keeps a working knowledge base and loses only the
    update.

    What deliberately is NOT done here: recording the new handle. The caller re-raises,
    the transaction rolls back, and any write here would roll back with it — so our
    tables keep pointing at the handle that was just deleted. That is the intended
    residue, and it is now caught twice over: the next publish either fails to detach a
    handle the engine no longer has (`kb_detach_failed`) or, where the re-attach minted
    a new handle, finds a copy it cannot account for (`kb_engine_out_of_sync`). Both
    stop; neither quietly stacks two versions.
    """
    for source_id in detached:
        try:
            await engine.attach_kb(
                engine_ref,
                KBSourceRef(
                    kb_id=str(source_id),
                    title=name,
                    text="\n\n".join(chunks_of.get(source_id, [])),
                ),
            )
        except Exception:
            # Nothing left to try: the engine is refusing both directions. Say so at
            # ERROR — this agent now has NO knowledge for this source and only an
            # operator can put it back.
            log.error("kb_left_detached", extra={"source_id": str(source_id)})
        else:
            log.info("kb_restored_after_failed_publish", extra={"source_id": str(source_id)})


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
    2. EVERY copy of this source the engine is holding is DETACHED before the new one is
       attached. Archiving a row only changes our tables; what the caller hears is what
       the engine holds. Push first and there is a window — or, when the detach never
       happens at all, a permanent state — in which the agent can answer from either
       version, and a rollback leaves every version live at once. A client approved v2;
       the agent quoting v1's prices is the divergence the approval gate exists to
       prevent.

       "Every copy" includes THIS source's own previously attached copy, which is not a
       subtlety. `attach_kb` is a CREATE: it mints a fresh handle on every call and
       de-duplicates nothing, because the engine has no idea two calls describe the same
       source of ours. So re-publishing a version that is already live — a double-clicked
       Publish button, a retry after a timeout, FLOWS §7's rollback onto the current
       version — attached a second document and overwrote the only handle that could
       have removed the first. That first copy is then unaddressable forever,
       retrievable by the agent forever, and billed forever. The fake adapter cannot
       show this: it keys its store on OUR `kb_id` and returns a stable handle, so it
       silently replaces where a real engine accumulates.

    That ordering costs a gap: between the detach and the attach the agent has no copy
    of this source and answers "I don't know" (T4 refuse-and-escalate). One request of
    silence is the cheaper failure — a stale price is a quote the client is then held to.

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

    What this function still cannot make atomic, stated so nobody assumes otherwise: the
    engine calls are not in the transaction, so a COMMIT that fails after a successful
    attach leaves the engine holding a document none of our rows mention.
    `_reconcile_engine_state` cannot prevent that — nothing here can — but it detects it
    on the next attempt and refuses, instead of attaching a second copy on top.
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
    superseded = await _superseded_versions(
        session, agent_id=agent_id, name=str(name), keep=source_id
    )
    _require_addressable(superseded)
    await _reconcile_engine_state(
        engine,
        engine_ref,
        agent_id=agent_id,
        accounted=await _recorded_handles_of_agent(session, agent_id),
    )

    # Everything to withdraw before the attach: the other live version(s) of this named
    # source, plus this source's own copy if one is already attached.
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
    if own_handle is not None:
        withdraw.append((source_id, own_handle))

    # Read the fallback text BEFORE anything is withdrawn: if the attach fails we have to
    # put these versions back, and a query issued after the failure is a query issued on
    # a session that may itself be the thing that failed.
    previous_chunks = {
        withdrawn_id: await _chunks_of(session, withdrawn_id) for withdrawn_id, _ in withdraw
    }

    for withdrawn_id, withdrawn_kb_ref in withdraw:
        await _detach_superseded(session, engine, engine_ref, withdrawn_id, withdrawn_kb_ref)

    try:
        attached_ref = await engine.attach_kb(
            engine_ref,
            KBSourceRef(kb_id=str(source_id), title=str(name), text="\n\n".join(chunks)),
        )
    except Exception:
        await _reattach_after_failed_publish(
            engine, engine_ref, str(name), [wid for wid, _ in withdraw], previous_chunks
        )
        raise

    await _remember_engine_kb_ref(session, source_id, attached_ref)

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
    await session.execute(
        text(
            "UPDATE kb_sources SET is_active = true, status = 'approved', "
            "published_at = now(), updated_at = now() WHERE id = :sid"
        ),
        {"sid": source_id},
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


async def list_sources(session: AsyncSession, *, status: str | None = None) -> list[dict[str, Any]]:
    clause = "WHERE status = :status" if status else ""
    rows = (
        await session.execute(
            text(
                "SELECT id, agent_id, name, kind, status, version, is_active, published_at, "
                "(SELECT count(*) FROM kb_documents d WHERE d.source_id = kb_sources.id) "
                f"FROM kb_sources {clause} ORDER BY updated_at DESC"
            ),
            {"status": status} if status else {},
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
    "publish_source",
    "reject_source",
    "submit_source",
]
