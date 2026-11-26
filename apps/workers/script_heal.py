"""Pip's repair of an existing script's faulted lines (`agents/script_heal`), and the hourly
sweep that reaches every script no save has.

`repair_holder_script` is one pass over one campaign's or inbound line's script: the script
checks (`script_heal.heal_findings`) run on the saved script; with nothing found it asks no
model and records the script as checked. Otherwise Pip's writer is asked for an edit naming
those findings (`script_proposals.fix_change`), the answer is kept to the faulted lines
(`kept_to_paths`), checked again and repaired at most `script_mistake_repair_passes` rounds
more (`script_proposal._fixed_further`, the same targeted repair every Pip draft goes
through), then saved by compare-and-set on the script it read, with what was spent metered in
the same transaction, and put on the calls as the owner's Save is (`campaigns/notes_live.
queue_put_live`). The repair is kept as a `pip_repair` version (`campaigns/script_history`),
so "put back" still reaches the owner's own script and the Versions list can undo it.

SUBJECT -> GATE -> RUN -> METER (`crm/resummarise.second_reading`'s order): the holder is the
subject; Pip must be on for the account and its AI allowance not used up, or the pass is
`skipped` and the sweep asks again next hour; each paid or refused leg is metered under
`ASSIST_FEATURE_SCRIPT_DRAFT`, like every other Pip background write of a script.

A pass waits rather than write under a Pip draft that is being written or waits for review
on the same holder: keeping that draft would put back what the repair changed. Its keep is a
save, which asks for a pass again.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

from calevate_shared.call_script import CallScript
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import agent_pass, script_builder, script_proposals
from apps.api.agents.assist_leg import account_assist_leg
from apps.api.agents.mistake_fixes import fix_paths
from apps.api.agents.script_heal import (
    CHECKS_VERSION,
    DEBOUNCE_S,
    JOB,
    REWRITE_KEY,
    SLOTS,
    HolderKind,
    heal_findings,
    holder_lint_context,
    mistake_kinds,
    table_of,
    wired_ways_out,
)
from apps.api.billing.ai_quota import new_assist_ref, read_ai_quota
from apps.api.campaigns import script_history
from apps.api.campaigns.notes_live import queue_put_live
from apps.api.campaigns.workspace import read_script_proposal
from apps.api.campaigns.workspace import request_proposal as request_campaign_proposal
from apps.api.copilot.consent import account_content_may_reach_models
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.queue import enqueue, job_id_for
from apps.api.core.settings import get_settings
from apps.api.crm import assist as crm_assist
from apps.api.db.session import admin_session, tenant_session
from apps.workers.fleet_walk import WalkBudget, resumed_walk
from apps.workers.script_assist import ScriptDraft, draft_script
from apps.workers.script_proposal import (
    PROPOSAL_MAX_TOKENS,
    PROPOSAL_REQUEST_TIMEOUT_S,
    _Fix,
    _fixed_further,
)

log = get_logger(__name__)

#: `script_heal.JOB`, spelled here so the job-wiring guard can read the deferred enqueue.
JOB_NAME: Final = "repair_holder_script"
assert JOB_NAME == JOB
SWEEP_JOB: Final = "sweep_script_heal"
#: Raised when a repair pass crashes (`runbooks/alarm-index.md`).
CRASHED_CODE: Final = "script_heal_crashed"
#: The sweep's minute of the hour, apart from every other fleet-wide walk
#: (`tests/job_registration_test.py`).
SWEEP_MINUTE: Final = 23
#: The most passes one sweep queues. A pass over a script with no fault asks no model, so
#: this bounds the worker's load, not the spend.
HOLDERS_PER_TICK: Final = 50
#: A failed pass is asked again by the sweep after this long.
RETRY_MINUTES: Final = 6 * 60
#: The sweep's own wall-clock budget, well under the worker's job timeout.
SWEEP_BUDGET: Final = timedelta(seconds=120)

_SCAN_SQL: Final = (
    "SELECT scanned_tenant_id, kind, holder_id FROM script_heal_scan(:stale, :retry, :checks)"
)


def _holder_of(payload: dict[str, Any]) -> tuple[HolderKind, UUID]:
    if payload.get("campaign_id"):
        return "campaign", UUID(str(payload["campaign_id"]))
    return "line", UUID(str(payload["line_id"]))


@dataclass(frozen=True, slots=True)
class _Holder:
    kind: HolderKind
    id: UUID
    agent_id: UUID
    script: CallScript | None
    #: What the script is compared with when saving: a line's version; a campaign has none,
    #: so its saved script itself.
    version: int | None
    raw_script: Any
    #: md5 of the saved script and `CHECKS_VERSION`, as the sweep computes it.
    digest: str
    #: A campaign's own main language, when it sets one over the agent's.
    language: str | None
    draft_open: bool


async def _read(tenant_id: UUID, kind: HolderKind, holder_id: UUID) -> _Holder | None:
    async with tenant_session(tenant_id) as session:
        if kind == "campaign":
            sql = (
                "SELECT agent_id, script, script_proposal, NULL AS version, "
                "md5(script::text || :checks) AS digest, "
                "settings_overrides->>'language_primary' AS language "
                "FROM campaigns WHERE id = :h AND archived_at IS NULL"
            )
        else:
            sql = (
                "SELECT agent_id, script, script_proposal, version, "
                "md5(script::text || :checks) AS digest, NULL AS language "
                "FROM inbound_lines WHERE id = :h AND archived_at IS NULL"
            )
        row = (await session.execute(text(sql), {"h": holder_id, "checks": CHECKS_VERSION})).first()
    if row is None:
        return None
    proposal = read_script_proposal(row.script_proposal, now=datetime.now(UTC))
    return _Holder(
        kind=kind,
        id=holder_id,
        agent_id=row.agent_id,
        script=CallScript.model_validate(row.script) if row.script else None,
        version=None if row.version is None else int(row.version),
        raw_script=row.script,
        digest=str(row.digest or ""),
        language=row.language,
        draft_open=proposal is not None and proposal.status in ("drafting", "ready"),
    )


async def _finish(
    tenant_id: UUID,
    kind: HolderKind,
    holder_id: UUID,
    state: str,
    *,
    checked: str | None = None,
) -> None:
    """Close the pass; `checked` records the digest of the script it checked, so neither the
    sweep nor a save of the same script asks again."""
    async with tenant_session(tenant_id) as session:
        if checked is not None:
            await session.execute(
                text(f"UPDATE {table_of(kind)} SET script_heal_inputs = :d WHERE id = :h"),
                {"d": checked, "h": holder_id},
            )
        await agent_pass.finish(
            session, SLOTS[kind], tenant_id=tenant_id, row_id=holder_id, state=state
        )


async def _due(tenant_id: UUID, kind: HolderKind, holder_id: UUID) -> datetime | None:
    """When a waiting pass may start, if that is still ahead: `DEBOUNCE_S` after the last
    save that asked for it."""
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    f"SELECT script_heal_state, script_heal_at FROM {table_of(kind)} WHERE id = :h"
                ),
                {"h": holder_id},
            )
        ).first()
    if row is None or row[0] != "queued" or row[1] is None:
        return None
    due: datetime = row[1] + timedelta(seconds=DEBOUNCE_S)
    return due if due > datetime.now(UTC) else None


async def _defer(payload: dict[str, Any], holder_id: UUID, due: datetime) -> None:
    """Run again once the burst of saves is over; keyed by the due instant, so each push-back
    is its own delivery and a repeated one is deduped by arq."""
    await enqueue(
        JOB_NAME,
        payload,
        job_id=job_id_for(JOB_NAME, str(holder_id), due.isoformat()),
        _defer_until=due,
    )


async def repair_holder_script(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """One repair pass over one holder's script."""
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    kind, holder_id = _holder_of(payload)
    due = await _due(tenant_id, kind, holder_id)
    if due is not None:
        await _defer(payload, holder_id, due)
        return "deferred"
    async with tenant_session(tenant_id) as session:
        claimed, previous = await agent_pass.claim(session, SLOTS[kind], row_id=holder_id)
    if not claimed:
        return "not_queued"
    try:
        outcome = await _run(tenant_id, kind, holder_id, previous)
    except Exception as exc:
        log.exception("script_heal_crashed", extra={"kind": kind, "holder_id": str(holder_id)})
        alert(
            "CORE_LOGIC",
            CRASHED_CODE,
            detail=(
                "Pip's repair of a line's or campaign's faulted script lines crashed; the "
                "script is unchanged and the sweep tries again in a few hours."
            ),
            tenant_id=str(tenant_id),
            holder_id=str(holder_id),
            reason=type(exc).__name__,
        )
        await _finish(tenant_id, kind, holder_id, "failed")
        outcome = "failed"
    log.info(
        "script_heal_run", extra={"kind": kind, "holder_id": str(holder_id), "outcome": outcome}
    )
    return outcome


async def _run(tenant_id: UUID, kind: HolderKind, holder_id: UUID, previous: str | None) -> str:
    holder = await _read(tenant_id, kind, holder_id)
    if holder is None or holder.script is None or holder.script.raw_override:
        await _finish(tenant_id, kind, holder_id, "done")
        return "nothing_to_check"
    if holder.draft_open:
        # Left unchecked, so the sweep looks again once the draft is kept or discarded.
        await _finish(tenant_id, kind, holder_id, "done")
        return "draft_open"
    if previous == holder.digest:
        await _finish(tenant_id, kind, holder_id, "done")
        return "unchanged"
    async with tenant_session(tenant_id) as session:
        lint = await holder_lint_context(session, kind, holder_id, holder.agent_id)
    # Structure first, by code: a way out stated only in words becomes a branch (no model, so
    # no gate), then the model is asked only about the lines.
    wired = wired_ways_out(holder.script, lint)
    findings = heal_findings(wired, lint)
    rewrite = await _rewrite_wanted(tenant_id, kind, holder_id)
    if not findings and not rewrite:
        if wired != holder.script:
            return await _save(tenant_id, holder, lint, wired, [])
        await _finish(tenant_id, kind, holder_id, "done", checked=holder.digest)
        return "clean"
    async with tenant_session(tenant_id) as session:
        allowed = await account_content_may_reach_models(session, tenant_id=tenant_id)
        quota = await read_ai_quota(session, tenant_id=tenant_id)
    if not allowed or quota.at_ceiling or quota.platform_paused:
        await _finish(tenant_id, kind, holder_id, "skipped")
        return "skipped"
    if rewrite and await _ask_rewrite(tenant_id, kind, holder_id):
        return "rewriting"
    if not findings:
        await _finish(tenant_id, kind, holder_id, "done", checked=holder.digest)
        return "clean"
    return await _repair(tenant_id, holder, lint, findings, wired)


async def _rewrite_wanted(tenant_id: UUID, kind: HolderKind, holder_id: UUID) -> bool:
    """Whether Pip rewrites this holder's whole script under the current rules rather than
    repairing its lines (founder, 25 Nov 2026): the script is still the one Pip wrote
    (`script_history.pip_owns`), the holder has a main task to write it from, and no rewrite
    under these rules was asked for it before, so a rewrite that failed is never retried and
    the script gets the line repairs instead."""
    table = table_of(kind)
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    f"SELECT script_heal_fixed ? :key AS tried, "
                    f"btrim(coalesce(main_task, '')) <> '' AS tasked FROM {table} WHERE id = :h"
                ),
                {"key": REWRITE_KEY, "h": holder_id},
            )
        ).first()
        if row is None or row.tried or not row.tasked:
            return False
        return await script_history.pip_owns(session, kind, holder_id)


async def _ask_rewrite(tenant_id: UUID, kind: HolderKind, holder_id: UUID) -> bool:
    """Ask the holder's script writer for a whole new script, which it saves as the holder's
    script once written when the script is still the one it was written from
    (`workers/campaign_script._save_if_rewrite`), and record the ask so it is made once.
    The draft job is metered as every Pip draft is. False when the writer refused the ask (a
    draft already being written): the pass then repairs lines as before."""
    from apps.api.inbound import lines

    ask = {"rewrite": script_history.REWRITE_RULES}
    async with tenant_session(tenant_id) as session:
        try:
            async with session.begin_nested():
                if kind == "campaign":
                    await request_campaign_proposal(
                        session, tenant_id=tenant_id, campaign_id=holder_id, requested_by=None,
                        ask=ask,
                    )  # fmt: skip
                else:
                    await lines.request_proposal(
                        session, tenant_id=tenant_id, line_id=holder_id, requested_by=None, ask=ask
                    )
        except ProblemError as refused:
            log.info("script_rewrite_not_asked", extra={"reason": refused.code})
            return False
        await session.execute(
            text(
                f"UPDATE {table_of(kind)} SET script_heal_fixed = script_heal_fixed || "
                "jsonb_build_object(CAST(:key AS text), now()::text) WHERE id = :h"
            ),
            {"key": REWRITE_KEY, "h": holder_id},
        )
        await agent_pass.finish(
            session, SLOTS[kind], tenant_id=tenant_id, row_id=holder_id, state="done"
        )
    log.info("script_rewrite_asked", extra={"kind": kind, "holder_id": str(holder_id)})
    return True


async def _repair(
    tenant_id: UUID, holder: _Holder, lint: Any, findings: list[str], base: CallScript
) -> str:
    """`base` is the script as read with its structure already mended; the save compares
    with the script as read."""
    assert holder.script is not None
    started = time.monotonic()
    paths = fix_paths(findings)
    fix = _Fix(
        lint,
        findings,
        frozenset(script_proposals.finding_key(p, base) for p in findings),
        check=lambda script: heal_findings(script, lint),
    )
    async with tenant_session(tenant_id) as session:
        context = await script_proposals.brief_for(
            session, tenant_id, holder.agent_id, language=holder.language
        )
        tenant_leg = await account_assist_leg(session)
        quota = await read_ai_quota(session, tenant_id=tenant_id)
    try:
        draft = await draft_script(
            context,
            tenant_leg=tenant_leg,
            quota_exhausted=quota.at_ceiling or quota.platform_paused,
            edit_of=base,
            change=script_proposals.fix_change(findings, base),
            timeout_s=PROPOSAL_REQUEST_TIMEOUT_S,
            max_tokens=PROPOSAL_MAX_TOKENS,
        )
    except ProblemError as refused:
        log.info("script_heal_refused", extra={"holder_id": str(holder.id), "reason": refused.code})
        await _meter_and_finish(tenant_id, holder, [refused], state="failed")
        return "refused"
    spends: list[ScriptDraft | ProblemError] = [draft]
    repaired = base
    try:
        kept = script_proposals.kept_to_paths(draft.script, base, paths)
        further = await _fixed_further(
            tenant_id,
            holder.agent_id,
            fix,
            kept,
            started,
            passes=get_settings().script_mistake_repair_passes,
            language=holder.language,
        )
        repaired = further.script
        spends += further.spends
    except Exception:
        # The first answer is paid for and must reach the meter (hard rule 7).
        log.exception("script_heal_check_crashed", extra={"holder_id": str(holder.id)})
    if repaired == holder.script:
        # Nothing the model wrote cleared a fault, and code mended nothing either. Recorded
        # as checked so the sweep does not pay for the same answer every hour; a call showing
        # the mistake asks again.
        await _meter_and_finish(tenant_id, holder, spends, state="done", checked=holder.digest)
        return "unchanged_by_model"
    return await _save(tenant_id, holder, lint, repaired, spends)


async def _meter(session: AsyncSession, tenant_id: UUID, spends: list[Any]) -> None:
    feature = crm_assist.ASSIST_FEATURE_SCRIPT_DRAFT
    for spent in spends:
        if isinstance(spent, ProblemError):
            await crm_assist.meter_refusal(
                session, tenant_id=tenant_id, refusal=spent, feature=feature
            )
            continue
        await crm_assist.meter_earlier(
            session, tenant_id=tenant_id, earlier=spent.earlier, feature=feature
        )
        await crm_assist.meter_assist(
            session,
            tenant_id=tenant_id,
            ref=new_assist_ref(),
            result=spent,
            model=spent.model,
            feature=feature,
        )


async def _meter_and_finish(
    tenant_id: UUID,
    holder: _Holder,
    spends: list[Any],
    *,
    state: str,
    checked: str | None = None,
) -> None:
    async with tenant_session(tenant_id) as session:
        await _meter(session, tenant_id, spends)
        if checked is not None:
            await session.execute(
                text(f"UPDATE {table_of(holder.kind)} SET script_heal_inputs = :d WHERE id = :h"),
                {"d": checked, "h": holder.id},
            )
        await agent_pass.finish(
            session, SLOTS[holder.kind], tenant_id=tenant_id, row_id=holder.id, state=state
        )


async def _write(
    session: AsyncSession,
    tenant_id: UUID,
    holder: _Holder,
    script: CallScript,
    fixed: dict[str, str],
) -> bool:
    """The compare-and-set save: a line's version, a campaign's script as read. The inputs
    record the saved script as checked, so the sweep does not read it again until it moves.
    Kept as a `pip_repair` version, which "put back" passes over to the owner's own."""
    values = {
        "s": script.model_dump_json(),
        "h": holder.id,
        "checks": CHECKS_VERSION,
        "fixed": json.dumps(fixed),
    }
    if holder.kind == "campaign":
        sql = (
            "UPDATE campaigns SET script = CAST(:s AS jsonb), "
            "script_heal_fixed = script_heal_fixed || "
            "CAST(:fixed AS jsonb), script_heal_inputs = md5(CAST(:s AS jsonb)::text || :checks), "
            "updated_at = now() WHERE id = :h AND script = CAST(:old AS jsonb) RETURNING id"
        )
        values["old"] = json.dumps(holder.raw_script)
    else:
        sql = (
            "UPDATE inbound_lines SET script = CAST(:s AS jsonb), version = version + 1, "
            "script_heal_fixed = script_heal_fixed || CAST(:fixed AS jsonb), "
            "script_heal_inputs = md5(CAST(:s AS jsonb)::text || :checks), updated_at = now() "
            "WHERE id = :h AND version = :v RETURNING id"
        )
        values["v"] = holder.version
    if (await session.execute(text(sql), values)).first() is None:
        return False
    await script_history.record(
        session,
        tenant_id=tenant_id,
        kind=holder.kind,
        holder_id=holder.id,
        script=script,
        author="pip_repair",
    )
    return True


async def _save(
    tenant_id: UUID, holder: _Holder, lint: Any, script: CallScript, spends: list[Any]
) -> str:
    assert holder.script is not None
    now = datetime.now(UTC).isoformat()
    cleared = mistake_kinds(holder.script, lint) - mistake_kinds(script, lint)
    fixed = dict.fromkeys(sorted(cleared), now)
    async with tenant_session(tenant_id) as session:
        await _meter(session, tenant_id, spends)
        try:
            await script_builder.refuse_job_if_too_long(
                session, kind=holder.kind, tenant_id=tenant_id, job_id=holder.id, script=script
            )
        except ProblemError as refused:
            log.info(
                "script_heal_too_long", extra={"holder_id": str(holder.id), "reason": refused.code}
            )
            await session.execute(
                text(f"UPDATE {table_of(holder.kind)} SET script_heal_inputs = :d WHERE id = :h"),
                {"d": holder.digest, "h": holder.id},
            )
            await agent_pass.finish(
                session, SLOTS[holder.kind], tenant_id=tenant_id, row_id=holder.id, state="failed"
            )
            return "too_long"
        saved = await _write(session, tenant_id, holder, script, fixed)
        await agent_pass.finish(
            session, SLOTS[holder.kind], tenant_id=tenant_id, row_id=holder.id, state="done"
        )
        if not saved:
            # The script moved under the pass (the owner, or the step-outcomes pass): read
            # it again rather than write over it.
            await agent_pass.queue(
                session, SLOTS[holder.kind], tenant_id=tenant_id, row_id=holder.id
            )
            return "moved"
        await queue_put_live(session, tenant_id=tenant_id, jobs=[(holder.kind, holder.id)])
    log.info(
        "script_heal_saved",
        extra={"holder_id": str(holder.id), "kinds": sorted(cleared), "passes": len(spends)},
    )
    return "repaired"


async def sweep_script_heal(ctx: dict[str, Any]) -> str:
    """Queue a pass for each open structured script not checked in its current form: scripts
    saved before a check existed, a pass that died, accounts that since turned Pip on. One
    admin read of the worklist (`script_heal_scan`, a per-tenant loop inside Postgres under
    each tenant's own policy), then one tenant session per account with work, at most
    `HOLDERS_PER_TICK` holders, resuming after the last account reached."""
    del ctx
    async with admin_session() as directory:
        rows = (
            await directory.execute(
                text(_SCAN_SQL),
                {
                    "stale": agent_pass.STALE_MINUTES,
                    "retry": RETRY_MINUTES,
                    "checks": CHECKS_VERSION,
                },
            )
        ).all()
    holders: dict[UUID, list[tuple[HolderKind, UUID]]] = defaultdict(list)
    for tenant, kind, holder in rows:
        holders[UUID(str(tenant))].append(("campaign" if kind == "campaign" else "line", holder))
    queued = 0
    budget = WalkBudget(SWEEP_BUDGET)
    async for tenant_id in resumed_walk(SWEEP_JOB, list(holders), budget):
        if queued >= HOLDERS_PER_TICK:
            break
        async with tenant_session(tenant_id) as session:
            for kind, holder_id in holders[tenant_id][: HOLDERS_PER_TICK - queued]:
                queued += await agent_pass.queue(
                    session, SLOTS[kind], tenant_id=tenant_id, row_id=UUID(str(holder_id))
                )
    log.info(
        "script_heal_sweep",
        extra={"holders": len(rows), "tenants": len(holders), "queued": queued},
    )
    return f"holders={len(rows)} queued={queued}"


__all__ = [
    "HOLDERS_PER_TICK",
    "JOB_NAME",
    "SWEEP_JOB",
    "SWEEP_MINUTE",
    "repair_holder_script",
    "sweep_script_heal",
]
