"""Writes the AI and recording notices into an agent's opening line, from the outbox (D-971).

Queued by `agents/opening_notices.queue_opening_notices` when an opening line put live, or a
notice switch moved, leaves the line not saying exactly the notices switched on. The opening
writer (`opening_line.write_opening`) is asked to repair the line with those problems named,
from the same brief every script writer reads, and the line is put live through
`script_builder.replace_opening_line`, which measures it against the engine's greeting
ceiling and refuses while other script changes wait to go live.

Every answer or refusal from a paid leg is metered under `ASSIST_FEATURE_SCRIPT_DRAFT`, as
Pip's other script writing is (hard rule 7).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Final
from uuid import UUID

from arq import Retry
from calevate_shared.backoff import ladder_delay_s
from sqlalchemy import text

from apps.api.agents import script_builder, script_proposals
from apps.api.agents.assist_leg import account_assist_leg
from apps.api.agents.opening_notices import (
    HOLDER_LOCK_SQL,
    WEAVE_JOB,
    WEAVE_NOTE,
    HolderKind,
    OpeningToWeave,
    holder_weave_state,
    weave_state,
)
from apps.api.billing.ai_quota import new_assist_ref, read_ai_quota
from apps.api.campaigns import workspace as campaign_workspace
from apps.api.compliance.audit import write_audit
from apps.api.compliance.call_notices import read_account_notices
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES, job_try
from apps.api.crm import assist as crm_assist
from apps.api.db.session import tenant_session
from apps.api.inbound import lines as inbound_lines
from apps.workers.extraction import PROVIDER_UNAVAILABLE_REASON
from apps.workers.opening_line import WrittenOpening, opening_problems, write_opening
from apps.workers.script_assist import JsonAnswer

log = get_logger(__name__)

JOB_NAME: Final = WEAVE_JOB

#: The job `alembic/versions/f2477c8d623d` queues for each account whose notice switch it
#: turned back on (D-1021).
REFRESH_JOB: Final = "refresh_account_notices"

#: The wait before asking again when every line went unwritten because no writer answered.
RETRY_BACKOFF_S: Final[tuple[float, ...]] = (60.0, 300.0)
#: The refusal a later attempt may not meet: the model was asked and did not answer. Not a
#: missing credential or an exhausted quota, which a retry minutes later meets again.
_NO_ANSWER_CODE: Final = f"assist_{PROVIDER_UNAVAILABLE_REASON}"


def _retry_when_no_writer_answered(
    ctx: dict[str, Any],
    spends: Sequence[JsonAnswer[WrittenOpening] | ProblemError],
    *,
    quota_exhausted: bool,
) -> None:
    """Raise arq's `Retry` when nothing was written and a writer refused for a reason that
    can pass (`_NO_ANSWER_CODE`): the notices are still said beside the old line meanwhile,
    and without a retry the line would wait for the owner's next change. An account out of
    AI quota, a refusal of the answer itself, or the last attempt is left as it is."""
    refusals = [spent for spent in spends if isinstance(spent, ProblemError)]
    if quota_exhausted or not refusals:
        return
    if not any(
        refused.kind == "transient" or refused.code == _NO_ANSWER_CODE for refused in refusals
    ):
        return
    attempt = job_try(ctx)
    if attempt >= WORKER_MAX_TRIES:
        log.warning("opening_notices_retries_spent", extra={"attempts": attempt})
        return
    raise Retry(defer=ladder_delay_s(RETRY_BACKOFF_S, attempt))


async def _meter(tenant_id: UUID, spends: list[JsonAnswer[WrittenOpening] | ProblemError]) -> None:
    feature = crm_assist.ASSIST_FEATURE_SCRIPT_DRAFT
    async with tenant_session(tenant_id) as session:
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


async def weave_opening_notices(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    tenant_id = UUID(str(payload["tenant_id"]))
    agent_id = UUID(str(payload["agent_id"]))
    prompt_id = str(payload["prompt_id"])
    async with tenant_session(tenant_id) as session:
        state = await weave_state(session, agent_id)
        if state is None:
            return "gone"
        # A later version or a staged change: the publish of whatever is live next asks again.
        if str(state.prompt_id) != prompt_id or state.staged:
            return "stale"
        if not state.todo:
            return "already_said"
        brief = await script_proposals.brief_for(session, tenant_id, agent_id)
        tenant_leg = await account_assist_leg(session)
        quota = await read_ai_quota(session, tenant_id=tenant_id)
    names = (brief.business_name, brief.agent_name)
    spends: list[JsonAnswer[WrittenOpening] | ProblemError] = []
    written: list[tuple[OpeningToWeave, WrittenOpening]] = []
    for line in state.todo:
        problems = opening_problems(
            line.line,
            brief.language,
            names=names,
            introduced=brief.introduced,
            where=line.field,
            woven=brief.woven,
            said=line.said,
        )
        try:
            answer = await write_opening(
                brief,
                line=line.line,
                problems=problems,
                tenant_leg=tenant_leg,
                quota_exhausted=quota.at_ceiling or quota.platform_paused,
                placed=line.placed,
            )
        except ProblemError as refused:
            log.info(
                "opening_notices_unwritten", extra={"reason": refused.code, "field": line.field}
            )
            spends.append(refused)
            continue
        spends.append(answer)
        written.append((line, answer.value))
    if not written:
        await _meter(tenant_id, spends)
        _retry_when_no_writer_answered(
            ctx, spends, quota_exhausted=quota.at_ceiling or quota.platform_paused
        )
        return "unwritten"
    applied = 0
    stale = False
    async with tenant_session(tenant_id) as session:
        # Read again under the agent's row lock: the lines were written from the script read
        # before the model calls, and a version saved since then is the owner's, whose own
        # publish asks for its own weave. The lock is held to commit, so the only versions
        # written after this check are the ones below.
        current = (
            await session.execute(
                text("SELECT system_prompt_id FROM agents WHERE id = :aid FOR UPDATE"),
                {"aid": agent_id},
            )
        ).scalar_one_or_none()
        stale = str(current) != prompt_id
        for line, value in written if not stale else ():
            try:
                async with session.begin_nested():
                    # The replaced line travels with the new one, so the Script tab can show
                    # what changed and put it back (founder, 5 Nov 2026).
                    await script_builder.replace_opening_line(
                        session,
                        tenant_id=tenant_id,
                        agent_id=agent_id,
                        opening_line=value.line,
                        created_by=None,
                        placed=line.placed,
                        notes=WEAVE_NOTE,
                        notices=value.notices(before=line.line),
                    )
                applied += 1
            except ProblemError as refused:
                # The stored sentences are still said beside the old line; the owner's next
                # change to the opening or a switch asks again.
                log.info(
                    "opening_notices_not_applied",
                    extra={"reason": refused.code, "field": line.field},
                )
    # Metered in its own transaction: a line refused at apply was still paid for.
    await _meter(tenant_id, spends)
    log.info(
        "opening_notices_woven",
        extra={
            "agent_id": str(agent_id),
            "written": len(written),
            "applied": applied,
            "stale": stale,
        },
    )
    if stale:
        return "stale"
    return "woven" if applied else "unwritten"


async def weave_holder_opening_notices(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """The same rewrite for an Inbound line's or a campaign's own script (D-1021), queued by
    `agents/opening_notices.queue_account_holder_notices` when the account's switch moves.

    Saved through the holder's own save (`inbound/lines.save_script`,
    `campaigns/workspace.save_script`, which hold it to its agent's limits), then put on its
    calls as an owner's save is: a live line and a campaign holding its engine agent are
    republished; a draft's reaches its calls when it goes live."""
    tenant_id = UUID(str(payload["tenant_id"]))
    kind: HolderKind = "line" if payload["kind"] == "line" else "campaign"
    holder_id = UUID(str(payload["holder_id"]))
    stamp = str(payload["stamp"])
    async with tenant_session(tenant_id) as session:
        state = await holder_weave_state(session, kind, holder_id)
        if state is None:
            return "gone"
        if state.stamp != stamp:
            return "stale"
        if not state.todo:
            return "already_said"
        # A campaign written in its own main language is woven in that language, as its
        # script was written (`workers/campaign_script`).
        brief = await script_proposals.brief_for(
            session, tenant_id, state.agent_id, language=state.language
        )
        tenant_leg = await account_assist_leg(session)
        quota = await read_ai_quota(session, tenant_id=tenant_id)
    names = (brief.business_name, brief.agent_name)
    spends: list[JsonAnswer[WrittenOpening] | ProblemError] = []
    written: list[tuple[OpeningToWeave, WrittenOpening]] = []
    for line in state.todo:
        problems = opening_problems(
            line.line,
            brief.language,
            names=names,
            introduced=brief.introduced,
            where=line.field,
            woven=brief.woven,
            said=line.said,
        )
        try:
            answer = await write_opening(
                brief,
                line=line.line,
                problems=problems,
                tenant_leg=tenant_leg,
                quota_exhausted=quota.at_ceiling or quota.platform_paused,
                placed=line.placed,
            )
        except ProblemError as refused:
            log.info(
                "opening_notices_unwritten", extra={"reason": refused.code, "field": line.field}
            )
            spends.append(refused)
            continue
        spends.append(answer)
        written.append((line, answer.value))
    if not written:
        await _meter(tenant_id, spends)
        _retry_when_no_writer_answered(
            ctx, spends, quota_exhausted=quota.at_ceiling or quota.platform_paused
        )
        return "unwritten"
    saved = False
    async with tenant_session(tenant_id) as session:
        # Read again under the holder's lock, taken BEFORE the read and held to commit, as
        # its save takes it: a script the owner saved since is theirs (the stamp moved), and
        # one they save now waits for this commit rather than being written over.
        await session.execute(text(HOLDER_LOCK_SQL[kind]), {"hid": holder_id})
        current = await holder_weave_state(session, kind, holder_id)
        stale = current is None or current.stamp != stamp
        if written and not stale:
            update: dict[str, Any] = {}
            for line, value in written:
                record = (
                    "outbound_opening_notices"
                    if line.field != "opening_line"
                    else ("opening_notices")
                )
                update[line.field] = value.line
                update[record] = value.notices(before=line.line)
            script = state.script.model_copy(update=update)
            try:
                async with session.begin_nested():
                    if kind == "line":
                        await inbound_lines.save_script(session, holder_id, script)
                    else:
                        await campaign_workspace.save_script(session, holder_id, script)
                saved = True
            except ProblemError as refused:
                # The stored sentences are still said beside the old line.
                log.info("opening_notices_not_applied", extra={"reason": refused.code})
    await _meter(tenant_id, spends)
    if saved:
        await put_holder_live(tenant_id, kind, holder_id, event="holder_opening_notices_not_live")
    log.info(
        "holder_opening_notices_woven",
        extra={
            "kind": kind,
            "holder_id": str(holder_id),
            "written": len(written),
            "saved": saved,
            "stale": stale,
        },
    )
    if stale:
        return "stale"
    return "woven" if saved else "unwritten"


async def put_holder_live(
    tenant_id: UUID, kind: HolderKind, holder_id: UUID, *, event: str
) -> None:
    """Put a script Pip rewrote on the holder's calls, as its owner's save would: a live line
    and a campaign holding its engine agent at once, a draft at its own Start or publish. A
    refusal is logged as `event` and left: the drift sweep reads the engine against our rows
    (for the notices, the stored sentences are said beside the old line meanwhile)."""
    from apps.api.agents.service import CAMPAIGN_HOLDING_STATUSES
    from apps.api.campaigns.engine_agent import put_campaign_live
    from apps.api.inbound.publish import put_line_live

    async with tenant_session(tenant_id) as session:
        if kind == "line":
            goes = (await inbound_lines.read_line(session, holder_id)).live
        else:
            goes = bool(
                (
                    await session.execute(
                        text(
                            "SELECT engine_agent_ref IS NOT NULL AND status = ANY(:holding) "
                            "FROM campaigns WHERE id = :c"
                        ),
                        {"c": holder_id, "holding": list(CAMPAIGN_HOLDING_STATUSES)},
                    )
                ).scalar_one_or_none()
            )
    if not goes:
        return
    try:
        if kind == "line":
            await put_line_live(tenant_id=tenant_id, line_id=holder_id)
        else:
            await put_campaign_live(
                tenant_id=tenant_id, campaign_id=holder_id, require_holding=True
            )
    except ProblemError as refused:
        log.warning(
            event,
            extra={"kind": kind, "holder_id": str(holder_id), "reason": refused.code},
        )


#: (payload key the migration writes, the switch's field name).
_RESTORED: Final = (("ai", "ai_disclosure_enabled"), ("recording", "recording_notice_enabled"))


async def refresh_account_notices(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Put a notice switch that `f2477c8d623d` turned back on onto the account's calls: the
    openings' rewrites and the tenant live apply a flip queues
    (`publishing.queue_notices_reach_calls`), and the audit row recording that the switch is
    on, for each restored switch still on. One transaction under the organization row's lock,
    so a flip by the owner meanwhile is read rather than overwritten, and a retry repeats
    nothing that committed."""
    from apps.api.agents.publishing import audit_action_for, queue_notices_reach_calls

    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    async with tenant_session(tenant_id) as session:
        now = await read_account_notices(session, tenant_id=tenant_id, for_update=True)
        on = {"ai_disclosure_enabled": now.ai, "recording_notice_enabled": now.recording}
        restored = [field for key, field in _RESTORED if payload.get(key) and on[field]]
        if not restored:
            return "switched_off_since"
        run_id = await queue_notices_reach_calls(
            session, tenant_id=tenant_id, reason="call_notices_repair"
        )
        for field in restored:
            await write_audit(
                session,
                action=audit_action_for(field, enabled=True),
                tenant_id=tenant_id,
                object_type="organization",
                object_id=str(tenant_id),
                summary={"migration": "f2477c8d623d", "live_apply_run_id": str(run_id)},
            )
    log.info(
        "account_call_notices_restored",
        extra={"tenant_id": str(tenant_id), "restored": restored, "run_id": str(run_id)},
    )
    return "queued"


__all__ = [
    "JOB_NAME",
    "REFRESH_JOB",
    "put_holder_live",
    "refresh_account_notices",
    "weave_holder_opening_notices",
    "weave_opening_notices",
]
