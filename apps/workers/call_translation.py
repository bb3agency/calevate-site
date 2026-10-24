"""English for a call after the post-call pipeline: the owner's "Try again" and the one-time
backfill of calls that were never translated (founder decisions 2 and 3, 11 Oct 2026).

The pipeline translates every call as it settles it (`pipeline._record_reading`). Two kinds
of call are left without English: calls settled before 10 Oct 2026 23:13 IST, when the
worker could not see the ops console's keys (`translation_state` `unavailable` or
`failed`), and calls whose language pass failed at the provider. This module re-runs only
the language pass for one call, on the same terms as the pipeline: REDACTED text in, one
Sarvam round trip per forty turns, nothing logged but ids (hard rules 5 and 6).

WHO PAYS is the one difference between the two entry points, and the job carries it:

* `client` — an owner pressed "Try again". That is dashboard AI a person asked for, so it is
  metered as `ASSIST_FEATURE_CALL_TRANSLATION`, which counts against the monthly AI
  allowance like any other assist; the route gated it with `require_ai_assist` first.
* `platform` — the backfill. The call should have been translated when it ended and was
  not because of our fault, so it is metered as `ASSIST_FEATURE_CALL_LANGUAGE`, absorbed
  exactly like the pipeline's own pass.

`translation_state = 'pending'` is the claim in both paths: the route sets it before it
queues the job, and the backfill sets it with a compare-and-swap from `failed`/`unavailable`
before it spends anything, so the screen shows "English is being prepared" for as long as
the work is outstanding and two deliveries of one job cannot both translate.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any, Final, Literal
from uuid import UUID

from arq import Retry
from calevate_shared.engine import SARVAM_DEFAULT_LLM
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.ai_quota import new_assist_ref, record_ai_assist_usage
from apps.api.billing.models import (
    ASSIST_FEATURE_CALL_LANGUAGE,
    ASSIST_FEATURE_CALL_TRANSLATION,
)
from apps.api.billing.rates import llm_price_is_billable
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES, enqueue, job_id_for
from apps.api.core.redis import get_redis
from apps.api.core.settings import get_settings
from apps.api.db.session import admin_session, tenant_session
from apps.workers import call_language
from apps.workers.chat import TokenUsage
from apps.workers.fleet_walk import WalkBudget
from apps.workers.redaction import redact

log = get_logger(__name__)

#: The ARQ name of `translate_call_job`; `crm/translation.TRANSLATE_CALL_JOB` is the outbox's
#: spelling of the same name, and `tests/call_translation_test.py` holds the two together.
JOB_NAME: Final = "translate_call_job"
Payer = Literal["client", "platform"]
_FEATURE_OF_PAYER: Final[dict[str, str]] = {
    "client": ASSIST_FEATURE_CALL_TRANSLATION,
    "platform": ASSIST_FEATURE_CALL_LANGUAGE,
}

#: The backfill reaches back this far, newest first (founder decision 3).
BACKFILL_WINDOW: Final = timedelta(days=30)
#: Calls queued per backfill tick. Each is one model round trip in its own job, so a tick
#: costs at most this many enqueues.
BACKFILL_BATCH: Final = 20
#: Candidates read per page while walking a client's window back past calls already tried:
#: a client with nothing left to try is still one read, and a window full of tried calls a
#: few pages rather than one page per `BACKFILL_BATCH`.
_CANDIDATE_PAGE: Final = 500
#: Hourly, at a minute no other fleet-wide walk uses (`tests/job_registration_test.py`).
BACKFILL_MINUTE: Final = 37
#: The backfill tries each call ONCE. A call whose second attempt also fails keeps its
#: "Try again" for the owner rather than being retried at our cost every hour; the marker
#: outlives the window, so a call cannot age back into the batch.
_ATTEMPTED_KEY: Final = "call_translation:backfilled:{call_id}"
_ATTEMPTED_TTL_S: Final = int((BACKFILL_WINDOW + timedelta(days=1)).total_seconds())

_LIVE_TENANTS_SQL: Final = "SELECT id FROM organizations WHERE deleted_at IS NULL ORDER BY id"
#: One page of a tenant's candidates, newest first, after the (`at`, `id`) keyset of the
#: previous page. Paged because a call the backfill has tried keeps `failed` (its marker is
#: in Redis, not here): a single capped read was filled by tried calls and never reached
#: the older ones nobody had tried.
_CANDIDATES_SQL: Final = (
    "SELECT c.id, COALESCE(c.started_at, c.created_at) AS at FROM calls c "
    "WHERE c.status = 'completed' "
    "AND c.translation_state IN ('unavailable', 'failed') "
    "AND COALESCE(c.started_at, c.created_at) >= now() - :window "
    "AND (CAST(:before_at AS timestamptz) IS NULL "
    "     OR (COALESCE(c.started_at, c.created_at), c.id) "
    "        < (CAST(:before_at AS timestamptz), CAST(:before_id AS uuid))) "
    "AND EXISTS (SELECT 1 FROM transcript_turns t "
    "            WHERE t.call_id = c.id AND t.tenant_id = c.tenant_id) "
    "ORDER BY at DESC, c.id DESC LIMIT :batch"
)


async def meter_language_pass(
    session: AsyncSession,
    tenant_id: UUID,
    call_id: UUID,
    usage: TokenUsage,
    *,
    feature: str,
    source: str,
) -> None:
    """One language pass on the AI ledger (hard rule 7): the attested Sarvam price or
    nothing, never a zero row. `feature` decides who pays (`billing/models`); `source` names
    the step that ran it (`call_reading` for the pipeline and the re-read, `translate_call`
    for "Try again" and the backfill), so a second pass on one call says where it came from.

    The call is `meta.call_id`, not `usage_events.call_id`: an AI row keeps that column NULL
    so its `ref` stays inside `ux_usage_events_tenant_unit_ref`, the index that makes a
    replayed write meter nothing (`billing/models.UsageEvent`).

    In the caller's transaction, the one that writes the pass's English. The ref is fresh
    per pass, so a meter committed apart from its result would be charged again when a
    failed result write sends the job round to re-run the pass."""
    if not llm_price_is_billable(SARVAM_DEFAULT_LLM):
        log.info(
            "call_language_cost_unpriced",
            extra={"call_id": str(call_id), "model": SARVAM_DEFAULT_LLM},
        )
        return
    await record_ai_assist_usage(
        session,
        tenant_id=tenant_id,
        ref=new_assist_ref(),
        tokens_in=usage.prompt_tokens,
        tokens_out=usage.output_tokens,
        cached_tokens_in=usage.cached_tokens_in,
        model=SARVAM_DEFAULT_LLM,
        feature=feature,
        usage_incomplete=usage.incomplete,
        extra_meta={
            "call_id": str(call_id),
            "cached_prompt_tokens": str(usage.cached_prompt_tokens),
            "source": source,
            "reasoning_effort": call_language.REASONING_EFFORT,
        },
    )


async def translate_call(tenant_id: UUID, call_id: UUID, *, feature: str) -> str:
    """Write English for every untranslated turn and the missing summary, and settle
    `translation_state`. Returns the state written. Never raises on a provider failure
    (`run_language_pass` reports it as `failed`); a database error does raise."""
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT a.language_primary, c.summary, c.summary_local "
                    "FROM calls c JOIN agents a ON a.id = c.agent_id "
                    "WHERE c.id = :cid AND c.tenant_id = :tid"
                ),
                {"cid": call_id, "tid": tenant_id},
            )
        ).first()
        turns = (
            await session.execute(
                text(
                    "SELECT idx, COALESCE(text_redacted, ''), text_en FROM transcript_turns "
                    "WHERE call_id = :cid AND tenant_id = :tid ORDER BY idx"
                ),
                {"cid": call_id, "tid": tenant_id},
            )
        ).all()
    if row is None:
        return "missing"
    language = call_language.call_language(
        [str(t[1]) for t in turns], agent_language=str(row[0] or "te-IN")
    )
    pending = call_language.untranslated_turns(
        [(int(t[0]), str(t[1]), t[2]) for t in turns], language=language
    )
    english = str(row[1] or "")
    local = "" if call_language.is_english(language) else str(row[2] or "")
    want_local = bool(english) and not local and not call_language.is_english(language)
    want_english = not english and bool(local)
    already_english = any(t[2] for t in turns)

    turns_en: dict[int, str] = {}
    new_local = new_english = ""
    usage: TokenUsage | None = None
    if not (pending or want_local or want_english):
        state = "ready" if already_english else "not_needed"
    elif not (api_key := get_settings().sarvam_api_key):
        log.warning("call_translation_no_provider", extra={"call_id": str(call_id)})
        state = "failed" if pending else ("ready" if already_english else "not_needed")
    else:
        done = await call_language.run_language_pass(
            api_key=api_key,
            language=language,
            turns=pending,
            summary_en=redact(english).text if english else "",
            summary_local=redact(local).text if local else "",
        )
        usage = done.usage
        turns_en = call_language.english_lines(pending, done)
        new_local = done.summary_local if want_local else ""
        new_english = done.summary_en if want_english else ""
        if pending and done.failed:
            state = "failed"
        else:
            state = "ready" if (pending or already_english) else "not_needed"

    async with tenant_session(tenant_id) as session:
        # COALESCE: a summary written between the read above and this write (a pipeline
        # re-drive) is kept rather than overwritten by ours.
        await session.execute(
            text(
                "UPDATE calls SET translation_state = :state, "
                "summary_language = CASE WHEN summary_local IS NULL "
                "  AND CAST(:local AS text) IS NOT NULL THEN :language "
                "  ELSE summary_language END, "
                "summary_local = COALESCE(summary_local, CAST(:local AS text)), "
                "summary = COALESCE(summary, CAST(:english AS text)), updated_at = now() "
                "WHERE id = :cid AND tenant_id = :tid"
            ),
            {
                "state": state,
                "local": new_local or None,
                "english": new_english or None,
                "language": language,
                "cid": call_id,
                "tid": tenant_id,
            },
        )
        for idx, english_text in turns_en.items():
            await session.execute(
                text(
                    "UPDATE transcript_turns SET text_en = :en, updated_at = now() "
                    "WHERE call_id = :cid AND tenant_id = :tid AND idx = :idx "
                    "AND text_en IS NULL"
                ),
                {"en": english_text, "cid": call_id, "tid": tenant_id, "idx": idx},
            )
        if usage is not None:
            await meter_language_pass(
                session, tenant_id, call_id, usage, feature=feature, source="translate_call"
            )
    log.info(
        "call_translation_settled",
        extra={"call_id": str(call_id), "state": state, "turns": len(turns_en)},
    )
    return state


async def _claim_for_backfill(tenant_id: UUID, call_id: UUID) -> bool:
    """`failed`/`unavailable` -> `pending`, once. False when somebody else got there."""
    async with tenant_session(tenant_id) as session:
        claimed = (
            await session.execute(
                text(
                    "UPDATE calls SET translation_state = 'pending', updated_at = now() "
                    "WHERE id = :cid AND tenant_id = :tid "
                    "AND translation_state IN ('unavailable', 'failed') RETURNING id"
                ),
                {"cid": call_id, "tid": tenant_id},
            )
        ).first()
    return claimed is not None


async def _still_pending(tenant_id: UUID, call_id: UUID) -> bool:
    async with tenant_session(tenant_id) as session:
        state = (
            await session.execute(
                text("SELECT translation_state FROM calls WHERE id = :cid AND tenant_id = :tid"),
                {"cid": call_id, "tid": tenant_id},
            )
        ).scalar()
    return state == "pending"


async def _give_up(tenant_id: UUID, call_id: UUID) -> None:
    """The last attempt failed: say so, so the screen offers "Try again" instead of a
    skeleton that never resolves."""
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE calls SET translation_state = 'failed', updated_at = now() "
                "WHERE id = :cid AND tenant_id = :tid AND translation_state = 'pending'"
            ),
            {"cid": call_id, "tid": tenant_id},
        )


async def translate_call_job(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """THE JOB, for both payers. `payload` is `{tenant_id, call_id, payer}`: from the outbox
    for "Try again" (`crm/translation.request_translation`), from `backfill_call_translations`
    otherwise."""
    tenant_id = UUID(str(payload["tenant_id"]))
    call_id = UUID(str(payload["call_id"]))
    payer = str(payload.get("payer") or "client")
    feature = _FEATURE_OF_PAYER.get(payer)
    if feature is None:
        log.warning("call_translation_unknown_payer", extra={"call_id": str(call_id)})
        return "refused"

    attempt = int(ctx.get("job_try", 1) or 1)
    if payer == "platform" and attempt == 1:
        claimed = await get_redis().set(
            _ATTEMPTED_KEY.format(call_id=call_id), "1", nx=True, ex=_ATTEMPTED_TTL_S
        )
        if not claimed or not await _claim_for_backfill(tenant_id, call_id):
            return "skipped"
    elif not await _still_pending(tenant_id, call_id):
        # Already translated, or a second delivery of a job that has finished.
        return "skipped"

    try:
        state = await translate_call(tenant_id, call_id, feature=feature)
    except Exception as exc:
        log.warning(
            "call_translation_failed",
            extra={"call_id": str(call_id), "reason": type(exc).__name__, "attempt": attempt},
        )
        if attempt < WORKER_MAX_TRIES:
            raise Retry(defer=30 * attempt) from exc
        await _give_up(tenant_id, call_id)
        return "failed"
    return state


async def _untried_candidates(tenant_id: UUID, budget: WalkBudget) -> list[tuple[Any, UUID]]:
    """Up to `BACKFILL_BATCH` of this tenant's newest candidates the backfill has not tried,
    as (`at`, call id), reading back through the window a page at a time past the ones it
    has. The window bounds the walk; the tick's budget stops it early."""
    redis = get_redis()
    untried: list[tuple[Any, UUID]] = []
    before_at: Any = None
    before_id: UUID | None = None
    page_size = _CANDIDATE_PAGE
    while len(untried) < BACKFILL_BATCH:
        async with tenant_session(tenant_id) as session:
            rows = (
                await session.execute(
                    text(_CANDIDATES_SQL),
                    {
                        "window": BACKFILL_WINDOW,
                        "batch": page_size,
                        "before_at": before_at,
                        "before_id": before_id,
                    },
                )
            ).all()
        if not rows:
            break
        ids = [UUID(str(row[0])) for row in rows]
        tried = await redis.mget([_ATTEMPTED_KEY.format(call_id=call_id) for call_id in ids])
        untried.extend(
            (row[1], call_id)
            for row, call_id, marker in zip(rows, ids, tried, strict=True)
            if marker is None
        )
        if len(rows) < page_size or budget.spent():
            break
        before_at, before_id = rows[-1][1], ids[-1]
    return untried[:BACKFILL_BATCH]


async def backfill_call_translations(ctx: dict[str, Any]) -> str:
    """THE BACKFILL TICK. Finds the newest untranslated calls of the last 30 days across
    every client and queues one `translate_call` job each, at our cost. Idempotent: a call
    is queued at most once (`_ATTEMPTED_KEY`), and once nothing is left a tick is one read
    per client and returns. Ids only in the log (hard rule 6)."""
    del ctx
    async with admin_session() as directory:
        tenant_ids = [
            UUID(str(r)) for r in (await directory.execute(text(_LIVE_TENANTS_SQL))).scalars()
        ]

    budget = WalkBudget()
    found: list[tuple[Any, UUID, UUID]] = []
    reached = 0
    for tenant_id in tenant_ids:
        if budget.spent():
            break
        reached += 1
        found.extend(
            (at, tenant_id, call_id) for at, call_id in await _untried_candidates(tenant_id, budget)
        )

    found.sort(key=lambda item: item[0], reverse=True)
    queued = 0
    for _at, tenant_id, call_id in found:
        if queued >= BACKFILL_BATCH:
            break
        await enqueue(
            JOB_NAME,
            {"tenant_id": str(tenant_id), "call_id": str(call_id), "payer": "platform"},
            job_id=job_id_for(JOB_NAME, "backfill", str(call_id)),
        )
        queued += 1
    log.info(
        "call_translation_backfill",
        extra={"tenants": len(tenant_ids), "reached": reached, "queued": queued},
    )
    return json.dumps({"reached": reached, "queued": queued, "truncated": budget.exhausted})


__all__ = [
    "BACKFILL_BATCH",
    "BACKFILL_MINUTE",
    "BACKFILL_WINDOW",
    "JOB_NAME",
    "Payer",
    "backfill_call_translations",
    "meter_language_pass",
    "translate_call",
    "translate_call_job",
]
