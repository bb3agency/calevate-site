"""What an agent remembers about a REPEAT CALLER — the one door in, and the two doors out.

"A caller rings back and the agent knows they asked about IVF pricing last month." This
module owns the `caller_memories` source table: what may be written to it, what may be read
back, and — the half that decides whether the feature is shippable at all — how a row is
destroyed by both erasure paths and by the retention clock.

═══ 1. THE WRITE IS GATED, AND THE GATE IS ON THE WRITE ═══

`agents.caller_memory_enabled` defaults FALSE — the OPPOSITE of `ai_disclosure_enabled`
and `recording_notice_enabled`, which default TRUE because an omission there must produce
the safe posture. Here the safe posture is not remembering, so the same principle flips
the default.

**IT GATES `remember()` AND NOT ONLY `recall()`, AND THAT IS THE WHOLE POINT.** A toggle
that stops recall while rows keep accumulating is the worst version of this feature: it
looks off, it is off to the client, and it is quietly building a durable profile of every
caller that a DPDP request will one day be answered about. So the gate is on the door that
creates data. `recall()` checks too — belt and braces, and it is the arm that matters if a
client switches the feature OFF after rows already exist, since the rows then stop being
used the moment the switch moves and are destroyed by the clock rather than by a sweep
nobody wrote.

⚠ **AND THE GATE IS NOT THE WHOLE PERMISSION.** Being switched on is a client's
CONFIGURATION decision. Whether their CALLERS were told is a NOTICE question, and this
product currently has no notice that says an agent remembers: the two spoken sentences
(SEC-COMP §2.1/§2.2, D-163) are about being an AI and being recorded, and
`compliance/caller_notice._INHERENT` itemises the number, the recording, the transcript,
the summary and the call times. D-506 records what the founder has to decide before this
switch may be offered to anyone. The code does not decide it and must not read the
existence of the switch as an answer to it.

═══ 2. A DISTILLED FACT, NEVER A QUOTE ═══

`fact` holds "asked about IVF pricing", not "do you do IVF, my wife and I have been trying
for six years". Three reasons, in the order they bind:

* **Recall replays it.** A memory is put in front of a model on a LATER call, and a
  paragraph recalled is a paragraph of somebody's conversation read back to whoever rings
  next. `MAX_FACT_CHARS` is the bound, and it is small on purpose — anything approaching a
  paragraph is a transcript excerpt wearing a different column name.
* **Redaction is not erasure and the column name must not suggest it is.**
  `insights/service.scrub_quotes_for_calls` says it plainly: redaction removes
  IDENTIFIERS from a sentence, it does not remove the sentence, and
  "`question_redacted`" invited exactly that confusion. So this column is not called
  anything ending in `_redacted`. `redact()` still runs on the way in — it is the guard
  against the model inventing a phone-shaped number, which is `copilot/memory.
  redacted_content`'s argument — but the reason a fact is safe to keep is that it is a
  SUMMARY, not that it was scanned.
* **A fact is correctable and a quote is not.** "Asked about IVF pricing" that is wrong is
  replaced by the next distillation; a misheard sentence attributed to a caller is a
  record of something they did not say.

**GAP (1 Sep 2026): NOTHING CALLS `remember()` YET, AND THAT IS DELIBERATE RATHER THAN
UNFINISHED.** The store, both erasure arms, the retention clock and the guard
(`tests/caller_memory_erasure_guard_test.py`) are built and tested; the PRODUCER — a
distillation pass over a finished call — is not, and wiring it is the change that makes
the switch offerable to a client. Offering the switch is what creates processing no notice
names, so the producer waits on the decision D-506 records, not on engineering time.
Recorded here in `kb/models.KbRetrievalLog`'s shape, because the module is what outlives
the discussion.

WHAT CLOSES IT, in order: (1) the founder's answer on the caller notice; (2) a distillation
pass in the shape of `workers/copilot_memory.py` — bounded facts per call, `redact()` on
the way in, metered through `record_ai_assist_usage` (hard rule 7), and running ONLY for
agents whose switch is on, so the default costs nothing; (3) a per-call idempotency marker,
because a retry must not re-buy the same facts and `source_call_id` alone cannot say
"looked at, nothing owed" — `kb_documents.gloss_state` is the worked example of why that
third state has to exist. `recall()` is reachable the day (1) and (2) land.

**WHAT IS NOT DECIDED HERE.** How a fact is produced from a call is the distillation
worker's business (`workers/copilot_memory.py` is the shape: a cron, bounded spend,
`distilled_at` as the idempotency key), and this module takes finished sentences. That
separation is deliberate — the durable-data seam has to be reviewable without reading a
prompt.

═══ 3. THE ERASURE IS NOT HERE, AND THAT IS THE DESIGN ═══

**THE FEATURE'S PURPOSE IS THAT THE ROW OUTLIVES THE CALL**, so every mechanism that
protects a call's data by being attached to the call fails here by construction:
`source_call_id` is `ON DELETE SET NULL` provenance and could not be an erasure path (a
DPDP erasure SCRUBS a call in place and keeps the row as billing evidence, so a cascade
never fires — the lesson `insights/service.scrub_quotes_for_calls` was written to record),
and the transcript clock reaches nothing that is not in `retention.DERIVED_COPIES`.

Both doors out are therefore written by hand, and they are written ONCE, in
`apps/api/retrieval/caller_erasure.py` — `erase_subject_vectors` (DPDP §12, keyed on
`caller_ref.caller_refs()` so it still resolves after `calls.from_e164` is NULL, and
walking every KEK generation so a rotation cannot hide a row), `erase_tenant_vectors`, and
`EXPIRE_MEMORIES_SQL` on the tenant's own `transcript` policy.

**THIS MODULE DELIBERATELY DOES NOT HAVE ITS OWN COPY OF THEM**, and the reason is that
module's own: `caller_chunks` holds the derived keys and `caller_memories` holds the fact
they were built from, so splitting their erasure across two modules is exactly the seam
that goes missing — one gets a new caller and the other does not, silently, for as long as
nobody looks. One module, one pair of statements, one count on the certificate. An earlier
draft of this file had a second implementation; it was removed rather than kept beside it,
because two ways of doing one thing is a defect even when both work.

What remains here is the WRITE and the READ. `tests/caller_memory_test.py` exercises the
forgetting through the real arms rather than through a local copy, which is also the only
version of that test that can fail when the real path breaks.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.caller_ref import active_caller_ref, caller_refs
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.workers.redaction import redact

log = get_logger(__name__)

#: One fact, in characters. `copilot_memory.MAX_FACT_CHARS`' number and its argument: "the
#: clinic shuts Sunday" is the target shape, and anything approaching a paragraph is a
#: summary of the conversation rather than a fact learned from it. Here it does a second
#: job the copilot's does not — it is the bound between a distilled fact and a transcript
#: excerpt, which is the distinction the whole privacy argument rests on.
MAX_FACT_CHARS: Final = 240

#: How many facts one caller's recall may put in front of a model. Small, because this text
#: rides an IN-CALL prompt: every item is paid input tokens on a latency-critical path, and
#: a caller who rang eleven times must not produce an eleven-line preamble.
RECALL_LIMIT: Final = 5

#: How many facts one call may contribute. The distiller is asked for at most this many AND
#: the list is truncated to it — a token ceiling bounds a REQUEST's cost, never the number
#: of ROWS a compliant answer creates, and rows are what retention and erasure pay for.
MAX_FACTS_PER_CALL: Final = 3


def clean_fact(raw: str) -> str:
    """One distilled sentence, redacted and capped — the ONE way text becomes a fact row.

    Returns `""` when nothing worth storing survives, so a caller's `if not fact` is the
    whole of its error handling (`copilot/memory.redacted_content`'s contract, and its
    reason: losing a memory is strictly better than turning a delivered call into an
    error).

    `redact()` catches the case the distiller cannot be trusted on — a model writing a
    phone-shaped number into its own summary — and it is a BACKSTOP, not the reason a fact
    is safe to keep. See the module header: what makes it safe is that it is a summary.

    Capped BEFORE the database sees it so an over-long fact is a short row rather than a
    constraint violation in a stack trace, and the ellipsis is visible on purpose: a model
    reading a memory should be able to tell it is reading a fragment.
    """
    body = raw.strip()
    if not body:
        return ""
    result = redact(body)
    if result.changed:
        # KINDS, never the text and never the value (hard rule 6). This is how an operator
        # learns the distiller is emitting identifiers, which is the one direction no
        # request-side check can see.
        log.warning("caller_memory_redacted_on_write", extra={"kinds": len(result.kinds)})
    cleaned = result.text.strip()
    if len(cleaned) > MAX_FACT_CHARS:
        cleaned = cleaned[: MAX_FACT_CHARS - 1].rstrip() + "…"
    return cleaned


#: Verticals where a distilled fact is SENSITIVE PERSONAL DATA by construction, and where
#: cross-call memory is therefore refused however the agent's switch is set (D-507(b)).
#:
#: THE QUESTION WAS "IS 'ASKED ABOUT IVF PRICING' HEALTH DATA?" and the honest answer is
#: that it depends on who the business is, which no classifier over free text can be
#: trusted to decide — and being wrong is not recoverable. The SPDI Rules 2011 list is
#: EXHAUSTIVE and includes "physical, physiological and mental health condition" and
#: "medical records and history" (Rule 3), so a memory that a caller enquired about a
#: treatment is, on a clinic, an inference about exactly that.
#:
#: SPDI Rule 5(1) wants consent IN WRITING for collecting sensitive personal data. A phone
#: call cannot give one. So the refusal is not "until we word the notice better" — it is
#: until an instrument exists that a phone call can produce, which is not a code change.
#:
#: ⚠ REPORTED, NOT VERIFIED HERE: the SPDI Rules stand repealed by DPDP §44(2) on a date
#: reported as 13 May 2027 (18 months from the 13 Nov 2025 commencement gazette), which
#: would ALSO be when DPDP §§5-6 (notice and consent) first bind. `meity.gov.in` is
#: egress-blocked from this container, so that schedule comes from the search index of the
#: gazette PDF and from law-firm summaries, not from reading the notification. Whichever
#: regime governs on the day, this list is the conservative side of both, and re-reading
#: the gazette is what would let it shrink.
#:
#: A PROXY AND KNOWN TO BE ONE. `vertical_template` is the extraction schema a tenant
#: STARTED from, so a fertility clinic onboarded as `real_estate` is not caught. It is
#: kept because it is the only structured signal that exists and it errs toward refusing;
#: it is not represented as sufficient, and the enable path — when one is built — is where
#: a per-tenant attestation belongs.
SPDI_REFUSED_VERTICALS: Final[frozenset[str]] = frozenset({"clinic"})


async def memory_enabled(session: AsyncSession, *, agent_id: UUID) -> bool:
    """Is this agent allowed to remember its callers across calls?

    Reads the column rather than caching it: the switch is a compliance-adjacent setting a
    client can move at any time, and a stale `True` is a row written for a caller whose
    client had just decided otherwise. One indexed primary-key read on a path that is
    already doing a model call is not the place to save a round trip.

    A missing agent is `False`, not an exception. This is called from a worker whose
    subject may have been deleted since the job was queued, and "we did not remember
    anything" is the right outcome there — refusing loudly would retry a job that can
    never succeed.
    """
    row = (
        await session.execute(
            text(
                "SELECT a.caller_memory_enabled, o.vertical_template FROM agents a "
                "JOIN organizations o ON o.id = a.tenant_id WHERE a.id = :aid"
            ),
            {"aid": agent_id},
        )
    ).first()
    if row is None or not bool(row[0]):
        return False
    if str(row[1]) in SPDI_REFUSED_VERTICALS:
        # D-507(b). Not an exception, for the same reason a missing agent is not: this is
        # a worker's question and "nothing was remembered" is the right outcome. It IS
        # logged, because a switch that is on and a store that stays empty is otherwise an
        # operator mystery — and the ground is a decision they can look up, not a bug.
        log.warning(
            "caller_memory_refused_spdi_vertical",
            extra={"agent_id": str(agent_id), "vertical": str(row[1])},
        )
        return False
    return True


async def remember(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    agent_id: UUID,
    phone_e164: str,
    occurred_at: datetime,
    source_call_id: UUID | None,
    facts: Sequence[str],
) -> int:
    """Record what this call taught us about this caller. Returns rows written.

    THE ONE DOOR IN, and the gate is here rather than at any caller, because a second
    writer that forgot to check `caller_memory_enabled` would accumulate a durable profile
    for a client who had switched the feature off — the failure this design is most
    concerned about and the one that is invisible until somebody asks.

    IN THE CALLER'S TRANSACTION (`copilot/memory.remember_exchange`'s contract): the rows
    and whatever else that job did commit together, so a memory of a call whose metering
    rolled back does not exist.

    `occurred_at` is the SOURCE CALL's clock and never `now()`. A backfill that stamped
    tonight would restart every caller's retention period because a background job read
    their data — `caller_chunks.subject_at` carries the same rule for the same reason.

    NO UPSERT AND NO DEDUPE ACROSS CALLS. A fact learned again on a later call is a NEW
    row, deliberately: it is a fact still being observed, and it gets a fresh clock for
    the reason `retention.py`'s `copilot_memory` arm gives — "a fact still being observed
    is a fact still true". The recall limit, not the row count, is what bounds what a
    model sees.
    """
    if not facts:
        return 0
    if not await memory_enabled(session, agent_id=agent_id):
        # NOT an error and not an alarm: a client who never switched this on is the
        # DEFAULT, so this branch is the common case and must be silent and cheap.
        return 0
    handle_ref, handle_kek = _active_handle(tenant_id, phone_e164)
    written = 0
    for raw in list(facts)[:MAX_FACTS_PER_CALL]:
        fact = clean_fact(raw)
        if not fact:
            continue
        await session.execute(
            text(
                "INSERT INTO caller_memories (id, tenant_id, agent_id, subject_ref, "
                "subject_ref_kek_id, fact, source_call_id, occurred_at, created_at, "
                "updated_at) VALUES (:id, :tid, :aid, :ref, :kek, :fact, :call, :at, "
                "now(), now())"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "aid": agent_id,
                "ref": handle_ref,
                "kek": handle_kek,
                "fact": fact,
                "call": source_call_id,
                "at": occurred_at,
            },
        )
        written += 1
    return written


async def recall(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    agent_id: UUID,
    phone_e164: str,
    limit: int = RECALL_LIMIT,
) -> tuple[str, ...]:
    """What this agent knows about this caller, newest first. At most `limit` facts.

    GATED AGAIN, and this is the arm that matters when a client switches the feature OFF
    with rows already on file: recall stops the same instant the switch moves, and the
    rows are destroyed by the transcript clock rather than by a sweep nobody wrote. A
    read-side check is not redundant with the write-side one — they answer at different
    times about different rows.

    RECENCY ONLY, with no relevance channel, and the omission is argued rather than
    deferred. `copilot/memory.recall` blends recency and relevance because it is answering
    a QUESTION a person just typed; here there is no question yet — this is what the agent
    knows as the call OPENS. A relevance channel would need the caller's first utterance,
    which is a turn we do not have at the moment the prompt is built, and inventing one
    from the last call's topic would rank the past above the present. Newest first is the
    honest ordering for "what do I know about this person".

    Scrubbed rows are excluded by `fact <> ''` rather than by `scrubbed_at IS NULL`: both
    are true together (the CHECK pairs them) and the empty test is the one that also
    excludes a row whose distillation produced nothing.
    """
    if not await memory_enabled(session, agent_id=agent_id):
        return ()
    refs = list(caller_refs(tenant_id, phone_e164))
    rows = (
        await session.execute(
            text(
                "SELECT fact FROM caller_memories WHERE subject_ref = ANY(:refs) "
                "AND fact <> '' ORDER BY occurred_at DESC, created_at DESC LIMIT :lim"
            ),
            {"refs": refs, "lim": limit},
        )
    ).scalars()
    return tuple(str(row) for row in rows)


def _active_handle(tenant_id: UUID, phone_e164: str) -> tuple[str, int]:
    """The ref a new row is filed under, and the KEK generation that minted it.

    Imported through `caller_ref` rather than re-derived, so `caller_memories.subject_ref`
    and `caller_chunks.subject_ref` are the same value by construction and one erasure
    predicate reaches both.
    """
    handle = active_caller_ref(tenant_id, phone_e164)
    return handle.ref, handle.kek_id


__all__ = [
    "MAX_FACTS_PER_CALL",
    "MAX_FACT_CHARS",
    "RECALL_LIMIT",
    "clean_fact",
    "memory_enabled",
    "recall",
    "remember",
]
