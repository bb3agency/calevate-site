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

**WHAT IS NOT DECIDED HERE.** How a fact is produced from a call is the distillation
worker's business (`workers/copilot_memory.py` is the shape: a cron, bounded spend,
`distilled_at` as the idempotency key), and this module takes finished sentences. That
separation is deliberate — the durable-data seam has to be reviewable without reading a
prompt.

═══ 3. THE ERASURE, WHICH IS WHY THIS MODULE EXISTS AT ALL ═══

**THE FEATURE'S PURPOSE IS THAT THE ROW OUTLIVES THE CALL**, so every mechanism that
protects a call's data by being attached to the call fails here by construction:

* `source_call_id` is `ON DELETE SET NULL` PROVENANCE. It is not an erasure path and could
  not be one — a DPDP erasure SCRUBS a call in place and keeps the row as billing
  evidence, so a cascade never fires. `caller_chunks`' migration says the same thing about
  its own `call_id`, and `scrub_quotes_for_calls` exists because the lesson was learned
  the expensive way.
* the transcript clock does not reach it either, unless somebody puts it in
  `retention.DERIVED_COPIES` — "a category nobody sets is a category that never expires".

So there are exactly three doors out, and all three are in this file:

* `scrub_memories_for_subject` — the per-subject DPDP §12 arm, keyed on
  `caller_ref.caller_refs()`, which is derived from the NUMBER and therefore still works
  after `calls.from_e164` has been NULLed. It walks every KEK generation, so a key
  rotation cannot hide a row from an erasure.
* `scrub_all_memories` — the tenant-erasure arm. Unconditional, for
  `execute_tenant_erasure`'s reason on `copilot_memories`: there is no subject to match on
  when the whole account goes.
* `expire_memories` — the clock, on the tenant's own `transcript` policy, because a
  memory is distilled from what the caller said.

**SCRUBBED, NOT DELETED**, matching `call_extractions` and the gap tables: `fact` is
emptied to `''` and `scrubbed_at` is stamped, enforced by
`ck_caller_memories_scrubbed_is_empty`. The tombstone is what makes the forgetting
DURABLE — without it the distillation worker would re-learn the same fact from a
transcript the erasure had not yet reached and re-create the row, spending money to undo a
legal obligation. Every one of the three is idempotent on `fact <> ''` so a re-run cannot
report a second, larger count for work the first one did.
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
from apps.api.db.result import rowcount_of
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

#: The retention clock this scope rides, and it is deliberately NOT a category of its own.
#: A memory is DISTILLED from what the caller said, so it belongs on the clock of the words
#: it was distilled from — `calls.summary` and the knowledge-gap quotes are already filed
#: exactly that way. Kept in step with `retrieval/models.SUBJECT_RETENTION` by
#: `tests/caller_memory_test.py`, not by hope.
RETENTION_CATEGORY: Final = "transcript"

#: What `scrub`/`expire` write into `fact`. EMPTY STRING and never NULL: the column is NOT
#: NULL and the CHECK pairs `scrubbed_at IS NOT NULL` with `fact = ''`, so every reader has
#: ONE empty value to test rather than two. Deliberately NOT `retention.REDACTED_MARK` — a
#: marker is what you leave where a turn USED to be and a reader needs to know one existed;
#: here the row's own `scrubbed_at` says that, and a marker would be a string recalled into
#: a prompt.
SCRUBBED_FACT: Final = ""


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
    enabled = (
        await session.execute(
            text("SELECT caller_memory_enabled FROM agents WHERE id = :aid"),
            {"aid": agent_id},
        )
    ).scalar()
    return bool(enabled)


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


# ─────────────────────────────── the three doors out ───────────────────────────────
#
# One statement, three callers. The alternative is three statements that drift and a
# certificate that is right about one erasure and wrong about another — `_erase_campaign_
# contacts`' argument, which is why that function also takes its predicate as a parameter.
#
# `fact <> ''` is the ALREADY-DONE guard on every arm and it is what makes all three
# idempotent: an erasure re-run must not report a second, larger count for work the first
# one did, and a retention tick must not re-count rows a §12 request already scrubbed.
_SCRUB_SQL = """
UPDATE caller_memories
SET fact = :empty, scrubbed_at = now(), updated_at = now()
WHERE {predicate} AND fact <> ''
"""


async def _scrub(session: AsyncSession, predicate: str, params: dict[str, object]) -> int:
    result = await session.execute(
        text(_SCRUB_SQL.format(predicate=predicate)), {**params, "empty": SCRUBBED_FACT}
    )
    return int(rowcount_of(result) or 0)


async def scrub_memories_for_subject(
    session: AsyncSession, tenant_id: UUID, *, phone_e164: str
) -> int:
    """DPDP §12: forget everything this agent's callers' memories hold about ONE person.

    THE ARM `execute_deletion_request` CANNOT INHERIT. That function resolves a phone
    number to a set of CALL ids and a set of LEAD ids; a caller memory is keyed to neither,
    because its subject is a person ACROSS calls. `caller_refs()` is derived from the
    NUMBER, so it still resolves after `calls.from_e164` has been NULLed — and it returns
    EVERY KEK generation, so a key rotation between the write and the request cannot hide
    a row.

    Returns the count for the proof certificate. A count and never a fact: the certificate
    is handed to the requester and kept indefinitely, so it must not become another copy of
    what it attests was removed (hard rule 6).
    """
    return await _scrub(
        session,
        "subject_ref = ANY(:refs)",
        {"refs": list(caller_refs(tenant_id, phone_e164))},
    )


async def scrub_all_memories(session: AsyncSession) -> int:
    """Tenant erasure: every memory this account holds, unconditionally.

    UNCONDITIONAL — no predicate, no match — for `execute_tenant_erasure`'s reason on
    `copilot_memories`: when the whole account goes there is no subject to match on, and a
    per-subject arm would leave behind exactly the rows whose subject nobody remembered to
    enumerate. RLS scopes it to the tenant (hard rule 1); the caller is already inside
    `tenant_session`.
    """
    return await _scrub(session, "TRUE", {})


async def expire_memories(session: AsyncSession, *, cutoff: datetime) -> int:
    """The clock: facts older than the tenant's own `transcript` retention period.

    `occurred_at`, never `created_at` — the clock of the CALL the fact was learned on, so
    a distillation that ran late does not buy the row extra life and a backfill does not
    reset it.

    SCRUBBED RATHER THAN DELETED, unlike `retention.py`'s `copilot_memory` arm, and the
    difference is the re-learning loop: the distiller discovers its own work from calls,
    so a deleted row would be re-created from a transcript that has not yet reached its
    own cutoff — the row would come back, with a fresh clock, for ever. The tombstone is
    what makes the forgetting converge. It costs one empty row per expired fact, which is
    the same price `call_extractions` and the gap tables already pay.
    """
    return await _scrub(session, "occurred_at < :cutoff", {"cutoff": cutoff})


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
    "RETENTION_CATEGORY",
    "SCRUBBED_FACT",
    "clean_fact",
    "expire_memories",
    "memory_enabled",
    "recall",
    "remember",
    "scrub_all_memories",
    "scrub_memories_for_subject",
]
