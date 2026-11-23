"""What every script Pip writes goes through before an owner reviews it, and the healer's fix
of a mistake on real calls as a draft on the line or campaign the call was on (D-1005).

`finish_written` is the shared tail of every writer (`workers/campaign_script` for lines and
campaigns, `draft_mistake_fix` here): the call-mistake checks and their targeted repair
(D-989, `_mistakes_checked` → `_fixed_further`), then the opening rule and its repair by the
opening writer (`opening_line`, D-957).

`draft_mistake_fix` writes the fix the healer asked for (`agents/mistake_fixes.
request_holder_fix`): an edit of the holder's script that may change only the lines the
mistake's own check named (`script_proposals.kept_to_paths`), checked again and repaired
while that check still finds them. It is stored as the holder's Pip draft, which the owner
keeps or discards on the line's or campaign's page like any other; nothing here puts a script
live. An agent has no script of its own (D-997, D-1000), so the agent's own suggestion this
module wrote before (`draft_script_proposal`) is retired.

SUBJECT → GATE → RUN → METER, `crm/resummarise.second_reading`'s order: the request is the
subject; the healer read the allowance before asking (`workers/mistake_fix`), and the ceiling
is read again here and passed to the ladder; each completed or refused paid leg is metered
in the transaction that stores the draft, under `ASSIST_FEATURE_SCRIPT_DRAFT`.
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

from calevate_shared.call_script import CallScript
from sqlalchemy import text

from apps.api.agents import mistake_fixes, script_proposals
from apps.api.agents.assist_leg import account_assist_leg
from apps.api.agents.capability_manifest import lint_context_for
from apps.api.agents.mistake_fixes import Holder, holder_table
from apps.api.agents.mistake_lints import mistake_findings, script_mistakes
from apps.api.agents.script_lint import LintContext, empty_title_problems, unasked_details
from apps.api.agents.script_structure import settled
from apps.api.billing.ai_quota import new_assist_ref, read_ai_quota
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_JOB_TIMEOUT_S
from apps.api.core.settings import get_settings
from apps.api.crm import assist as crm_assist
from apps.api.db.session import tenant_session
from apps.workers import mistake_fix
from apps.workers.extraction import ASSIST_LADDER_LEGS, ASSIST_TIMEOUT_S
from apps.workers.opening_line import WrittenOpening, opening_problems, write_opening
from apps.workers.script_assist import (
    ANSWER_UNUSABLE_CODE,
    AskTrace,
    JsonAnswer,
    LeftOut,
    ScriptDraft,
    draft_script,
)

log = get_logger(__name__)

JOB_NAME: Final = mistake_fixes.MISTAKE_FIX_JOB

#: One model request's budget in these jobs, in place of the route's `ASSIST_TIMEOUT_S`:
#: nobody waits on an HTTP response here, and a large script written whole (the edit returns
#: every part) ran past 15 s and was thrown away. The ladder spends at most
#: `ASSIST_LADDER_LEGS` of these, and the opening repairs after it their own route-sized
#: budgets, all inside the worker's `job_timeout`.
PROPOSAL_REQUEST_TIMEOUT_S: Final = 50.0

#: One answer's token ceiling in these jobs. A ceiling, not a target: billing follows the
#: tokens used. Gemini counts thinking tokens inside it, and a whole Telugu script with its
#: example call ran into the route's 4,096; gemini-3.1-flash-lite's output limit is 65,536
#: (aistudio.google.com/docs/models/gemini-3.1-flash-lite, May 2026), Azure's gpt-4o-mini
#: 16,384, so this is the most both paid legs take. The Sarvam standby keeps its own 4,096.
PROPOSAL_MAX_TOKENS: Final = 16_384

#: The passes a fix may spend after its first on the findings it still leaves: generate,
#: check with the same check, repair what is left. The edit's own repairs cannot do this,
#: since they skip a problem the owner's script already had.
FIX_REPAIR_PASSES: Final = 2

#: The opening repairs' share of the job, kept free for them after any fix repair.
_OPENINGS_BUDGET_S: Final = 2 * ASSIST_LADDER_LEGS * ASSIST_TIMEOUT_S
#: Room left at the end of the job for storing and metering.
_JOB_MARGIN_S: Final = 30.0
#: A fix repair is started only with at least this long left for each model request: less
#: and a whole script written again would time out, a paid request thrown away.
FIX_REPAIR_MIN_TIMEOUT_S: Final = 20.0


def with_opening(script: CallScript, written: WrittenOpening, *, placed: bool) -> CallScript:
    """`script` with `written` as its opening line (`placed`: the one for calls it places)
    and the words in it that say each notice kept beside it (D-971)."""
    field, notices = (
        ("outbound_opening_line", "outbound_opening_notices")
        if placed
        else ("opening_line", "opening_notices")
    )
    return script.model_copy(update={field: written.line, notices: written.notices()})


#: The lines the engine speaks first, each with whether it opens the calls a "both" agent
#: places (D-920). Both are held to one rule and repaired the same way (D-957, D-959).
_OPENINGS: Final = (("opening_line", False), ("outbound_opening_line", True))


def openings_kept(script: CallScript, base: CallScript) -> CallScript:
    """`script` with any opening line the model left blank put back from `base`.

    A blank opening is never a fix: the agent would open the call with nothing, and the
    judging below skips a blank line, so without this a draft that dropped the opening
    replaced the owner's line with nothing."""
    restored = {
        field: kept
        for field, _placed in _OPENINGS
        if not str(getattr(script, field)).strip() and (kept := str(getattr(base, field)).strip())
    }
    return script.model_copy(update=restored) if restored else script


async def _opening_repaired(
    tenant_id: UUID,
    agent_id: UUID,
    proposal: script_proposals.ScriptProposal,
    script: CallScript,
    *,
    direction: str | None = None,
    purpose: str = "",
) -> tuple[CallScript, list[JsonAnswer[WrittenOpening] | ProblemError]]:
    """The draft's script with each opening line the model wrote that breaks the opening
    rule repaired by the opening writer (`opening_line.write_opening`), and what the repairs
    spent. A line the owner already had or asked for in their own words is theirs and is not
    judged. A repair that gives no line leaves the draft as written, for the owner to
    review."""
    script = openings_kept(script, proposal.base_script)
    owners = " ".join([proposal.request or "", *proposal.answers.values()])
    judged = [
        (field, placed, line)
        for field, placed in _OPENINGS
        if (line := str(getattr(script, field)).strip())
        and line != str(getattr(proposal.base_script, field)).strip()
        and line not in owners
    ]
    if not judged:
        return script, []
    async with tenant_session(tenant_id) as session:
        context = await script_proposals.brief_for(session, tenant_id, agent_id)
        tenant_leg = await account_assist_leg(session)
        quota = await read_ai_quota(session, tenant_id=tenant_id)
    if direction is not None:
        context = replace(context, direction=direction)
    if purpose.strip():
        # The reason a placed call's opening gives (`call_rules.PLACED_OPENING_RULE`).
        context = replace(context, description=purpose)
    spends: list[JsonAnswer[WrittenOpening] | ProblemError] = []
    for field, placed, line in judged:
        dialled = placed or context.direction == "outbound"
        problems = opening_problems(
            line,
            context.language,
            names=(context.business_name, context.agent_name),
            introduced=context.introduced,
            woven=context.woven,
            placed=dialled,
            agent_name=context.agent_name,
            business_name=context.business_name,
        )
        if not problems:
            continue
        try:
            answer = await write_opening(
                replace(context, answers=tuple(proposal.answers.items())),
                line=line,
                problems=problems,
                tenant_leg=tenant_leg,
                quota_exhausted=quota.at_ceiling or quota.platform_paused,
                placed=placed,
                placed_rules=dialled,
            )
        except ProblemError as refused:
            log.info(
                "script_proposal_opening_unrepaired",
                extra={"reason": refused.code, "field": field},
            )
            spends.append(refused)
            continue
        spends.append(answer)
        script = with_opening(script, answer.value, placed=placed)
    return script, spends


def refusal_note(refused: ProblemError, trace: AskTrace) -> str:
    """What the owner reads when nothing could be written, as exact as what we know: the
    parts that broke a rule and which rule, an answer too long to finish, else the refusal's
    own sentences."""
    if refused.code == ANSWER_UNUSABLE_CODE and trace.unwritten:
        return script_proposals.unwritten_note(trace.unwritten)
    if trace.truncated:
        return script_proposals.TOO_BIG_NOTE
    note = " ".join(p for p in (refused.detail, refused.remediation) if p)
    return note or script_proposals.FAILED_NOTE


@dataclass(frozen=True, slots=True)
class Noted:
    """A finding the review pass made (`campaign_script.review_findings`), as a script check
    finding ("<path>: <problem>"), with the text of every line of its part when it was made
    (a step's instruction and its line). Code cannot check it again, and a second paid review
    is not run, so it stands while the part is unchanged and counts as cleared once a repair
    rewrote any line of it."""

    finding: str
    said: tuple[tuple[str, str], ...]

    def stands(self, script: CallScript) -> bool:
        return all(text_at(script, path) == text for path, text in self.said)


def text_at(script: CallScript, path: str) -> str | None:
    """The string at a script check path (`stages.3.sounds_like`, `ending`), or None. A path
    to a list or an object (`stages.3.branches`) reads as its JSON, so a finding on a step's
    ways out stands while they are unchanged, as one on a line does."""
    node: Any = script.model_dump(mode="json")
    for part in path.split("."):
        if isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        elif isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return None
    if isinstance(node, list | dict):
        return json.dumps(node, sort_keys=True, ensure_ascii=False)
    return node if isinstance(node, str) else None


@dataclass(frozen=True, slots=True)
class _Fix:
    """What a fix is checked against, and the findings it was asked to clear, found on the
    script it was made from."""

    #: The agent's lint context, promo off.
    lint: LintContext
    #: The base script's findings at the fix's paths.
    findings: list[str]
    #: Those findings' places by step id (`script_proposals.finding_key`), so they are still
    #: recognised after a pass moved or removed a step.
    keys: frozenset[str]
    #: A healer fix (D-985): the call mistake whose own script check names the findings.
    #: None: every call-mistake check, the check of Pip's own writing (D-989), whose other
    #: rules the writer's refusals already hold it to.
    mistake_kind: str | None = None
    #: The review's findings on Pip's own writing, repaired in the same rounds as the
    #: call-mistake findings rather than by a loop of their own.
    noted: tuple[Noted, ...] = ()

    def problems(self, script: CallScript) -> list[str]:
        """What the check this fix answers finds on `script`."""
        if self.mistake_kind is not None:
            found = mistake_findings(script, self.lint, self.mistake_kind)
        else:
            # A title left with no name in a line `script_structure.settled` could not mend
            # (one of the owner's own steps in an edit is not Pip's to mend).
            found = [*script_mistakes(script, self.lint), *empty_title_problems(script)]
        return [*found, *(n.finding for n in self.noted if n.stands(script))]

    def targeted(self, script: CallScript) -> list[str]:
        """The findings on `script` at a place the fix was asked to clear."""
        return [
            problem
            for problem in self.problems(script)
            if script_proposals.finding_key(problem, script) in self.keys
        ]

    def unasked(self, script: CallScript, paths: list[str]) -> tuple[str, ...]:
        """The details no step of `script` asks for, when the fix may add them to a step."""
        return tuple(unasked_details(script, self.lint.collect)) if "script" in paths else ()


@dataclass(frozen=True, slots=True)
class _Repaired:
    script: CallScript
    #: Each repair pass, paid or refused, for the meter (hard rule 7).
    spends: list[ScriptDraft | ProblemError]
    #: The findings still there once the passes are spent.
    left: list[str]


def _repair_timeout(started: float) -> float | None:
    """One model request's budget for a fix repair starting now, or None when the job has
    too little left: the repairs share the job with the opening repairs after them, inside
    `WORKER_JOB_TIMEOUT_S`, so a killed job never leaves a paid answer unmetered."""
    left = WORKER_JOB_TIMEOUT_S - _JOB_MARGIN_S - _OPENINGS_BUDGET_S - (time.monotonic() - started)
    per_request = min(PROPOSAL_REQUEST_TIMEOUT_S, left / ASSIST_LADDER_LEGS)
    return per_request if per_request >= FIX_REPAIR_MIN_TIMEOUT_S else None


async def _repair_draft(
    tenant_id: UUID,
    agent_id: UUID,
    script: CallScript,
    change: str,
    timeout_s: float,
    *,
    language: str | None = None,
) -> ScriptDraft:
    """One fix repair, written as the first pass was: the same brief, model and allowance,
    read again since the pass before it spent some."""
    async with tenant_session(tenant_id) as session:
        context = await script_proposals.brief_for(session, tenant_id, agent_id, language=language)
        tenant_leg = await account_assist_leg(session)
        quota = await read_ai_quota(session, tenant_id=tenant_id)
    return await draft_script(
        context,
        tenant_leg=tenant_leg,
        quota_exhausted=quota.at_ceiling or quota.platform_paused,
        edit_of=script,
        change=change,
        timeout_s=timeout_s,
        max_tokens=PROPOSAL_MAX_TOKENS,
    )


async def _fixed_further(
    tenant_id: UUID,
    agent_id: UUID,
    fix: _Fix,
    script: CallScript,
    started: float,
    *,
    passes: int = FIX_REPAIR_PASSES,
    language: str | None = None,
) -> _Repaired:
    """`script` (the first pass, kept to its paths) checked again with the fix's check, and
    up to `passes` repairs naming only the findings still there. Stops when none is left, a
    pass changes nothing, a pass is refused or the job runs short of time; what is still
    there is returned for the owner to read (`script_proposals.fix_left`)."""
    spends: list[ScriptDraft | ProblemError] = []
    left = fix.targeted(script)
    for _ in range(passes):
        if not left:
            break
        timeout_s = _repair_timeout(started)
        if timeout_s is None:
            log.info("script_fix_repair_out_of_time", extra={"left": len(left)})
            break
        paths = sorted({problem.partition(": ")[0] for problem in left})
        try:
            draft = await _repair_draft(
                tenant_id,
                agent_id,
                script,
                script_proposals.fix_change(left, script),
                timeout_s,
                language=language,
            )
        except ProblemError as refused:
            log.info("script_fix_repair_refused", extra={"reason": refused.code})
            spends.append(refused)
            break
        except Exception:
            # The fix already written is paid for and stored; a failed repair only means
            # the owner reads which warnings are left.
            log.exception("script_fix_repair_crashed", extra={"agent_id": str(agent_id)})
            break
        spends.append(draft)
        try:
            repaired = script_proposals.kept_to_paths(
                draft.script, script, paths, unasked=fix.unasked(script, paths)
            )
            repaired_left = fix.targeted(repaired)
        except Exception:
            # Inside the loop rather than the caller's guard, which would drop `spends`:
            # the repairs answered are paid for and must reach the meter (hard rule 7).
            log.exception("script_fix_repair_unusable", extra={"agent_id": str(agent_id)})
            break
        if repaired == script:
            break
        script, left = repaired, repaired_left
    log.info("script_fix_checked", extra={"passes": len(spends), "left": len(left)})
    return _Repaired(script, spends, left)


def _finding_at(problem: str, script: CallScript) -> tuple[str, str]:
    """A finding by where it is (`finding_key`) and what it says, so the same warning on the
    same line is recognised across two versions of a script."""
    return script_proposals.finding_key(problem, script), problem.partition(": ")[2]


async def _mistakes_checked(
    tenant_id: UUID,
    agent_id: UUID,
    proposal: script_proposals.ScriptProposal,
    script: CallScript,
    started: float,
    noted: Sequence[Noted] = (),
) -> _Repaired:
    """Pip's script checked with every call-mistake check before it is offered (D-989), and
    the lines they find rewritten by the same targeted repair a fix uses, at most
    `script_mistake_repair_passes` rounds. Only what Pip wrote is judged: in an edit a
    finding the owner's script already had is theirs, and a fix may change only the lines
    it was asked for. Never the openings or their notices (`mistake_lints.fixable_findings`).
    `noted`, the review's findings on lines Pip wrote, join the same rounds.
    What is still found after the rounds is returned for the owner to read."""
    async with tenant_session(tenant_id) as session:
        context = await lint_context_for(session, tenant_id=tenant_id, agent_id=agent_id)
    check = _Fix(replace(context, promo=False), [], frozenset())
    base = proposal.base_script
    # Code mends what it can before any paid repair is spent on it.
    edit = bool(proposal.paths) or proposal.mode == "change"
    script = settled(script, context, base=base if edit else None)
    had = (
        {_finding_at(p, base) for p in check.problems(base)}
        if proposal.paths or proposal.mode == "change"
        else set()
    )
    repairable = tuple(
        n for n in noted if mistake_fixes.fix_paths([n.finding]) and n.stands(script)
    )
    check = replace(check, noted=repairable)
    written = [p for p in check.problems(script) if _finding_at(p, script) not in had]
    if proposal.paths:
        allowed = set(proposal.paths)
        written = [p for p in written if p.partition(": ")[0] in allowed]
    if not written:
        return _Repaired(script, [], [])
    check = replace(
        check,
        findings=written,
        keys=frozenset(script_proposals.finding_key(p, script) for p in written),
    )
    return await _fixed_further(
        tenant_id,
        agent_id,
        check,
        script,
        started,
        passes=get_settings().script_mistake_repair_passes,
    )


@dataclass(frozen=True, slots=True)
class Finished:
    """A written script once the checks every Pip script passes have run on it."""

    script: CallScript
    #: The call-mistake repairs, paid or refused, for the meter (hard rule 7).
    repairs: list[ScriptDraft | ProblemError]
    #: The opening repairs, paid or refused, for the meter.
    opening_spends: list[JsonAnswer[WrittenOpening] | ProblemError]
    #: The warnings the repairs could not clear, for the owner to read.
    left_out: list[LeftOut]


async def finish_written(
    tenant_id: UUID,
    agent_id: UUID,
    proposal: script_proposals.ScriptProposal,
    drafted: CallScript,
    started: float,
    *,
    noted: Sequence[Noted] = (),
    direction: str | None = None,
    purpose: str = "",
) -> Finished:
    """What every script Pip writes goes through before an owner reviews it, a line's, a
    campaign's and a fix alike: the call-mistake checks and their repair (D-989), with the
    review's findings on repairable lines (`noted`) in the same rounds, then the opening rule
    and its repair (D-957). Each step's failure keeps what is already written, since it is
    paid for and must be stored and metered. `direction` and `purpose`: how the holder's
    calls go when that is not the agent's own (a campaign only places calls, for the reason
    its main task gives), for the opening repair."""
    repairs: list[ScriptDraft | ProblemError] = []
    left_out: list[LeftOut] = []
    if not drafted.raw_override:
        try:
            checked = await _mistakes_checked(
                tenant_id, agent_id, proposal, drafted, started, noted
            )
        except Exception:
            log.exception("script_mistake_check_crashed", extra={"agent_id": str(agent_id)})
            checked = _Repaired(drafted, [], [n.finding for n in noted])
        drafted, repairs = checked.script, checked.spends
        # One warning per part and rule: a step's finding names its line and its instruction.
        left_out = list(
            {(p.part, p.rule): p for p in script_proposals.fix_left(checked.left, drafted)}.values()
        )
    try:
        script, opening_spends = await _opening_repaired(
            tenant_id, agent_id, proposal, drafted, direction=direction, purpose=purpose
        )
    except Exception:
        # Not left `drafting` until it goes stale: stored as drafted, for the owner to review.
        log.exception("script_proposal_opening_crashed", extra={"agent_id": str(agent_id)})
        script, opening_spends = drafted, []
    return Finished(script, repairs, opening_spends, left_out)


# --- the healer's fix, as a draft on the line or campaign (D-1005) -------------------------


@dataclass(frozen=True, slots=True)
class _Claimed:
    agent_id: UUID
    base: CallScript
    paths: list[str]
    kind: str
    #: A campaign's own main language, when it sets one over the agent's.
    language: str | None


async def _claim(tenant_id: UUID, holder: Holder, proposal_id: UUID) -> _Claimed | None:
    """Take the request once: the outbox delivers at least once, and a second delivery must
    not spend the allowance on a second draft of the same fix."""
    language = "settings_overrides->>'language_primary'" if holder.kind == "campaign" else "NULL"
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    f"UPDATE {holder_table(holder.kind)} SET script_proposal = script_proposal "
                    "|| jsonb_build_object('claimed', true) WHERE id = :h "
                    "AND script_proposal->>'id' = :pid "
                    "AND script_proposal->>'status' = 'drafting' "
                    "AND script_proposal->>'claimed' IS NULL "
                    "AND script_proposal->>'fix_kind' IS NOT NULL "
                    f"RETURNING agent_id, script_proposal, {language}"
                ),
                {"h": holder.id, "pid": str(proposal_id)},
            )
        ).first()
    if row is None:
        return None
    record = row[1]
    return _Claimed(
        agent_id=row[0],
        base=CallScript.model_validate(record["base_script"]),
        paths=[str(p) for p in record.get("paths") or []],
        kind=str(record["fix_kind"]),
        language=row[2],
    )


async def _store(
    tenant_id: UUID, holder: Holder, proposal_id: UUID, update: dict[str, Any], spends: list[Any]
) -> bool:
    """Write the draft's outcome by compare-and-set on its id, so a draft the owner discarded
    meanwhile is never written back, and meter what was spent in the same transaction."""
    feature = crm_assist.ASSIST_FEATURE_SCRIPT_DRAFT
    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(
                text(
                    f"UPDATE {holder_table(holder.kind)} SET script_proposal = script_proposal "
                    "|| CAST(:u AS jsonb) WHERE id = :h AND script_proposal->>'id' = :pid "
                    "AND script_proposal->>'status' = 'drafting' RETURNING id"
                ),
                {"h": holder.id, "pid": str(proposal_id), "u": json.dumps(update)},
            )
        ).first() is not None
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
    return stored


async def draft_mistake_fix(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """The healer's fix of one mistake kind, written as the holder's Pip draft."""
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    holder = Holder(payload["holder_kind"], UUID(str(payload["holder_id"])))
    proposal_id = UUID(str(payload["proposal_id"]))
    claimed = await _claim(tenant_id, holder, proposal_id)
    if claimed is None:
        # Discarded, replaced, or already taken by an earlier delivery.
        return "not_pending"
    started = time.monotonic()
    trace = AskTrace()
    log_ids = {"holder_id": str(holder.id), "kind": claimed.kind}
    try:
        async with tenant_session(tenant_id) as session:
            lint = replace(
                await lint_context_for(session, tenant_id=tenant_id, agent_id=claimed.agent_id),
                promo=False,
            )
            context = await script_proposals.brief_for(
                session, tenant_id, claimed.agent_id, language=claimed.language
            )
            tenant_leg = await account_assist_leg(session)
            quota = await read_ai_quota(session, tenant_id=tenant_id)
        named = set(claimed.paths)
        findings = [
            p
            for p in mistake_findings(claimed.base, lint, claimed.kind)
            if p.partition(": ")[0] in named
        ]
        fix = _Fix(
            lint,
            findings,
            frozenset(script_proposals.finding_key(p, claimed.base) for p in findings),
            mistake_kind=claimed.kind,
        )
        draft = await draft_script(
            context,
            tenant_leg=tenant_leg,
            quota_exhausted=quota.at_ceiling or quota.platform_paused,
            edit_of=claimed.base,
            change=script_proposals.fix_change(findings, claimed.base),
            timeout_s=PROPOSAL_REQUEST_TIMEOUT_S,
            max_tokens=PROPOSAL_MAX_TOKENS,
            trace=trace,
        )
    except ProblemError as refused:
        log.info("mistake_fix_draft_refused", extra={**log_ids, "reason": refused.code})
        await _store(
            tenant_id,
            holder,
            proposal_id,
            {
                "status": "failed",
                "note": refusal_note(refused, trace)[:400],
                "reason": refused.code,
                "left_out": script_proposals.left_out_record(trace.unwritten),
            },
            [refused],
        )
        await mistake_fix.proposal_written(tenant_id, proposal_id)
        return "refused"
    except Exception:
        log.exception("mistake_fix_draft_crashed", extra=log_ids)
        await _store(
            tenant_id,
            holder,
            proposal_id,
            {"status": "failed", "note": script_proposals.FAILED_NOTE, "reason": "crashed"},
            [],
        )
        await mistake_fix.proposal_written(tenant_id, proposal_id)
        return "failed"

    # A fix changes the lines the check named and nothing else (A-02).
    kept = script_proposals.kept_to_paths(
        draft.script, claimed.base, claimed.paths, unasked=fix.unasked(claimed.base, claimed.paths)
    )
    try:
        repaired = await _fixed_further(
            tenant_id, claimed.agent_id, fix, kept, started, language=claimed.language
        )
    except Exception:
        # The first pass is paid for and is stored.
        log.exception("mistake_fix_check_crashed", extra=log_ids)
        repaired = _Repaired(kept, [], [])
    request = script_proposals.ScriptProposal(
        id=proposal_id,
        mode="change",
        status="drafting",
        request=None,
        answers={},
        base_script=claimed.base,
        requested_by=None,
        requested_at=datetime.now(UTC),
        paths=claimed.paths,
    )
    finished = await finish_written(tenant_id, claimed.agent_id, request, repaired.script, started)
    repairs = [*repaired.spends, *finished.repairs]
    stored = await _store(
        tenant_id,
        holder,
        proposal_id,
        {
            "status": "ready",
            "script": finished.script.model_dump(mode="json"),
            # A draft or repair the standby answered is disclosed with it (D-127 G-6).
            "disclosure": next(
                (
                    spent.capability.disclosure
                    for spent in (draft, *repairs)
                    if not isinstance(spent, ProblemError) and spent.capability.disclosure
                ),
                None,
            ),
            "left_out": script_proposals.left_out_record(
                [
                    *trace.left_out,
                    *script_proposals.fix_left(repaired.left, repaired.script),
                    *finished.left_out,
                ]
            ),
        },
        [draft, *repairs, *finished.opening_spends],
    )
    log.info("mistake_fix_draft_written", extra={**log_ids, "stored": stored})
    await mistake_fix.proposal_written(tenant_id, proposal_id)
    return "ready" if stored else "not_pending"


__all__ = [
    "JOB_NAME",
    "PROPOSAL_MAX_TOKENS",
    "PROPOSAL_REQUEST_TIMEOUT_S",
    "Finished",
    "Noted",
    "draft_mistake_fix",
    "finish_written",
    "refusal_note",
    "text_at",
]
