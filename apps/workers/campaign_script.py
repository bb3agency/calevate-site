"""Pip writes a campaign's script (D-992) and an inbound line's (D-997) from the holder's
main task and the sources it picked from What your agents know, by the same steps: one
writer for both holders, so a line and a campaign are written and checked alike.

Queued by `campaigns/workspace.request_proposal` and `inbound/lines.request_proposal`. The
script is written by the one script writer (`workers/script_assist.draft_script`) in the
holder's agent's language and business context (`agents/script_proposals.brief_for`). A first
script is written whole, from the trade's step plan like any new script, then edited once
with the same ask (D-1031), so a script written as its campaign or line is made is as good
as one asked for later, which edits the script there; one that already exists gets an edit
of it, so the owner's own wording survives wherever the sources do not change it, unless the
owner's request lays out the steps itself (`agents/owner_plan`): that is written whole, from
those steps instead of the trade's, and every draft is checked against them. The
inputs are read when the job runs (`campaign_inputs`, `line_inputs`), whoever asked and
when, and include the holder's own "What it notes". Documents are read
the way onboarding reads them (`first_run.documents_block`: redacted, fenced, one word budget).

A draft built wrong in ways only a whole rewrite mends (details piled into one step, a case
after the close, an item of the main task with no step; `script_shape.structure_problems`)
gets one whole-script pass naming them (`_restructured`). What Pip wrote is shortened once
when it would not fit the engine's box, then read by one review pass (D-1004): a "why" note
per part, and a rubric (each claim quoted from the sources, anything about the person asked
rather than told, each part serving the main task, no stock line, nothing repeated, the first
step saying why the call is made). Then it goes through what every Pip script does before an owner
reviews it (`script_proposal.finish_written`): the call-mistake checks and their repair
(D-989), the review's findings on steps, goal and ending repaired in the same rounds, then the
opening rule and its repair (D-957). Every pass is metered with the draft. Every write back
is a compare-and-set on the proposal id, so a draft the owner stopped or replaced is never
resurrected. What Pip is told lives in `workers/campaign_script_ask`.
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING, Any, Final, Literal
from uuid import UUID

from calevate_shared.call_script import (
    MAX_SCRIPT_STAGES,
    CallScript,
    CollectField,
    ScriptPolicies,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import script_proposals
from apps.api.agents.assist_leg import account_assist_leg
from apps.api.agents.languages import LANGUAGE_LABELS
from apps.api.agents.owner_plan import OwnerPlan, numbered_items, owner_plan, plan_problems
from apps.api.agents.prompt_size import PromptSize
from apps.api.agents.script_shape import structure_problems
from apps.api.agents.script_structure import collected, policies_for_job, without_judged_asks
from apps.api.billing.ai_quota import new_assist_ref, read_ai_quota
from apps.api.campaigns import script_history, workspace
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_JOB_TIMEOUT_S
from apps.api.core.settings import get_settings
from apps.api.crm import assist as crm_assist
from apps.api.db.session import tenant_session
from apps.api.first_run.models import KNOWLEDGE_DOCUMENT_CHARS
from apps.workers.campaign_script_ask import (
    CAMPAIGN_ASK,
    FLOW_ASK,
    FLOW_PART,
    LINE_ASK,
    PART_ASK,
    RESTRUCTURE_TAIL,
    REVIEW_FORMAT,
    REVIEW_INSTRUCTION,
    REVIEW_MAX_TOKENS,
    SHORTEN_ASK,
    TASK_STEPS_FORMAT,
    TASK_STEPS_INSTRUCTION,
    TASK_STEPS_MAX_TOKENS,
    TONES,
    TOO_LONG_RULE,
    Review,
    budget_of,
    campaign_change,
    owners_words,
    parsed_review,
    review_request,
    review_sources,
    reviewed_parts,
    situation_block,
    task_steps_note,
    task_steps_request,
    task_steps_text,
)
from apps.workers.extraction import ASSIST_LADDER_LEGS
from apps.workers.first_run import documents_block
from apps.workers.opening_line import WrittenOpening
from apps.workers.script_assist import (
    ANSWER_UNUSABLE_CODE,
    AskTrace,
    JsonAnswer,
    LeftOut,
    ScriptBrief,
    ScriptDraft,
    ask_json,
    draft_script,
)
from apps.workers.script_proposal import (
    PROPOSAL_MAX_TOKENS,
    PROPOSAL_REQUEST_TIMEOUT_S,
    Noted,
    finish_written,
    refusal_note,
    text_at,
)

if TYPE_CHECKING:
    from apps.api.agents.script_builder import JobDetails

log = get_logger(__name__)

UNUSABLE_NOTE: Final = (
    "Pip could not write a clean script this time. Your script is unchanged. "
    "Try again, or add a note saying what the calls should say."
)
#: The review pass and the shortening pass run only with this much of the job left, so a job
#: killed by the queue's timeout never leaves a paid answer unmetered.
_LATE_PASS_MIN_S: Final = 20.0
_JOB_MARGIN_S: Final = 30.0


def _left_s(started: float) -> float:
    return WORKER_JOB_TIMEOUT_S - _JOB_MARGIN_S - (time.monotonic() - started)


def _proposal(
    proposal_id: UUID, base: CallScript | None, request: str, *, whole: bool = False
) -> script_proposals.ScriptProposal:
    """The campaign's request in the agent proposal's shape, which `finish_written` reads: a
    `change` of the campaign's script, or a `whole` script, so a finding the owner's own
    script already had stays theirs to fix only where Pip edited that script. A whole rewrite
    keeps the base for the openings a blank line falls back to."""
    return script_proposals.ScriptProposal(
        id=proposal_id,
        mode="change" if base is not None and not whole else "whole",
        status="drafting",
        request=request,
        answers={},
        base_script=base or CallScript(),
        requested_by=None,
        requested_at=datetime.now(UTC),
    )


#: Answers a job asks for before the owner is told it could not write the script.
WRITE_ATTEMPTS: Final = 3
#: What a fresh answer and its repairs need of the job: a Telugu campaign script took 25 s
#: on 25 Nov 2026, and its repairs can take as long again.
_RETRY_MIN_S: Final = 120.0


def _writes_again(refused: ProblemError, trace: AskTrace, attempt: int, started: float) -> bool:
    """An answer that still broke a rule after its repairs is asked for again while the job
    has time: a new answer often keeps the rules the last one broke, and the owner should
    not be the retry button. A cut-off answer, a spent quota or a silent model is not."""
    return (
        refused.code == ANSWER_UNUSABLE_CODE
        and not trace.truncated
        and attempt < WRITE_ATTEMPTS
        and _left_s(started) >= _RETRY_MIN_S
    )


def retry_change(change: str, unwritten: Sequence[LeftOut], problems: str = "") -> str:
    """The owner's change, told which rules the last answer broke and where: the parts an
    edit could not write, else the problems a whole draft's last repair was sent (`AskTrace.
    problems`), which name a departure from the owner's steps as well as a broken line."""
    if not unwritten and problems:
        return (
            f"{change}\nThe last answer broke these rules. Write the script again and keep to "
            f"them: {problems}."
        )
    if not unwritten:
        return (
            f"{change}\nThe last answer broke the call rules. Write every line again in plain "
            "everyday spoken words, keeping to the rules."
        )
    broken = "; ".join(
        f"{p.part}{f' ({p.name})' if p.name else ''}: {p.rule}" for p in unwritten[:6]
    )
    return (
        f"{change}\nThe last answer broke these rules. Write those parts again and keep to "
        f"them: {broken}."
    )


def _failed_note(refused: ProblemError, trace: AskTrace) -> str:
    """The agent page's note, except for an answer that broke a rule on every try with no
    part named: its words speak of a change, and a campaign script is written whole."""
    if refused.code == ANSWER_UNUSABLE_CODE and not trace.unwritten:
        return UNUSABLE_NOTE
    return refusal_note(refused, trace)


@dataclass(frozen=True)
class _Holder:
    """Where a draft lives: the table whose `script_proposal` it is written into, and the
    row. `table` is one of our two constants, never input."""

    table: str
    holder_id: UUID
    tenant_id: UUID
    proposal_id: UUID
    log_key: str


def _table_of(holder: _Holder) -> str:
    """The holder's table as a literal, so the SQL it is spliced into is built only from text
    written here (`scripts/check_raw_sql.py`)."""
    return "inbound_lines" if holder.table == "inbound_lines" else "campaigns"


def _campaign(tenant_id: UUID, campaign_id: UUID, proposal_id: UUID) -> _Holder:
    return _Holder("campaigns", campaign_id, tenant_id, proposal_id, "campaign_id")


def _line(tenant_id: UUID, line_id: UUID, proposal_id: UUID) -> _Holder:
    return _Holder("inbound_lines", line_id, tenant_id, proposal_id, "line_id")


async def _claim(holder: _Holder) -> bool:
    """Take the request once: the outbox delivers at least once."""
    async with tenant_session(holder.tenant_id) as session:
        claimed = (
            await session.execute(
                text(
                    f"UPDATE {_table_of(holder)} SET script_proposal = script_proposal || "
                    "jsonb_build_object('claimed', true, 'phase', 'reading') WHERE id = :hid "
                    "AND script_proposal->>'id' = :pid "
                    "AND script_proposal->>'status' = 'drafting' "
                    "AND script_proposal->>'claimed' IS NULL RETURNING id"
                ),
                {"hid": holder.holder_id, "pid": str(holder.proposal_id)},
            )
        ).first()
    return claimed is not None


async def _store(session: AsyncSession, holder: _Holder, update: dict[str, Any]) -> bool:
    """Write into the draft by compare-and-set on its id: a stopped draft stays stopped."""
    stored = (
        await session.execute(
            text(
                f"UPDATE {_table_of(holder)} SET script_proposal = script_proposal || "
                "CAST(:u AS jsonb) WHERE id = :hid AND script_proposal->>'id' = :pid "
                "RETURNING id"
            ),
            {"hid": holder.holder_id, "pid": str(holder.proposal_id), "u": json.dumps(update)},
        )
    ).first()
    return stored is not None


class _DraftStoppedError(Exception):
    """The draft was stopped or replaced while this job wrote it (`script_draft.cancel_draft`,
    the page's Stop): the job ends at the next phase instead of spending on further passes."""


async def _phase(holder: _Holder, phase: str) -> None:
    """Tell the draft stream where the writer is, and stop if the draft is gone.

    The cancel is cooperative, checked here between the writer's passes, rather than an arq
    `Job.abort()`: an abort raises `CancelledError` inside a model request whose answer is
    then never metered (hard rule 7), and the worker runs with `allow_abort_jobs` off. A pass
    already under way finishes and is metered; nothing after it runs or is stored."""
    async with tenant_session(holder.tenant_id) as session:
        if not await _store(session, holder, {"phase": phase}):
            raise _DraftStoppedError


async def _meter(session: AsyncSession, tenant_id: UUID, spends: Sequence[Spent]) -> None:
    """Meter every pass a draft spent, refusals included."""
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


async def _save_if_asked(session: AsyncSession, holder: _Holder, script: CallScript) -> None:
    """A draft asked for with `auto_save` (the first run's, Phase 3b) becomes the holder's
    script at once, with no review, while the holder still has none: a script the owner
    saved meanwhile is never replaced. Saved through the holder's own save, so its length is
    held to the agent's limits; a draft refused there stays for the owner to review."""
    from apps.api.inbound import lines

    row = (
        await session.execute(
            text(
                f"SELECT script IS NULL AS empty, script_proposal->>'auto_save' AS auto "
                # Locked, so an owner's save in flight is waited for and then seen.
                f"FROM {_table_of(holder)} WHERE id = :hid AND script_proposal->>'id' = :pid "
                "FOR UPDATE"
            ),
            {"hid": holder.holder_id, "pid": str(holder.proposal_id)},
        )
    ).first()
    if row is None or row.auto != "true" or not row.empty:
        return
    try:
        async with session.begin_nested():
            if holder.table == "inbound_lines":
                await lines.save_script(session, holder.holder_id, script, author="pip_draft")
            else:
                await workspace.save_script(session, holder.holder_id, script, author="pip_draft")
            await session.execute(
                text(f"UPDATE {_table_of(holder)} SET script_proposal = NULL WHERE id = :hid"),
                {"hid": holder.holder_id},
            )
    except ProblemError as refused:
        log.info("holder_script_kept_for_review", extra={"reason": refused.code})
        # The draft waits for the owner's review; the first run still needs something to
        # ring, so the ready-made script stands in until they keep the draft.
        await _ready_made(session, holder)


async def _dropped_if_rewrite(session: AsyncSession, holder: _Holder) -> bool:
    """Clear a rewrite's draft (`workers/script_heal._ask_rewrite`), by compare-and-set on its
    id: nobody asked for it, so a rewrite that cannot be saved leaves no draft or failure on
    the owner's page. True when the draft was a rewrite and is gone."""
    return (
        await session.execute(
            text(
                f"UPDATE {_table_of(holder)} SET script_proposal = NULL WHERE id = :hid "
                "AND script_proposal->>'id' = :pid "
                "AND script_proposal->'ask'->>'rewrite' IS NOT NULL RETURNING id"
            ),
            {"hid": holder.holder_id, "pid": str(holder.proposal_id)},
        )
    ).first() is not None


async def _save_if_rewrite(
    session: AsyncSession, holder: _Holder, script: CallScript, *, clean: bool
) -> None:
    """A rewrite under the current rules (founder, 25 Nov 2026) becomes the holder's script
    at once, through the holder's own Save, which keeps it as a `pip_draft` version (so the
    Versions list and Put back reach the script before it), and is then put on the calls of a
    holder that takes them (`notes_live.queue_put_live`, as the heal pass's repairs are).
    Nobody reviews it (founder, 26 Nov 2026: a non-technical owner should not have to), so
    only a CLEAN draft is saved: one the writer left warnings on (`clean` False) is dropped
    and the script keeps its line repairs, rather than saved with its warnings thrown away.
    Only while the script is still the one the rewrite was written from and still Pip's
    (`script_history.pip_owns`): an owner's save meanwhile wins, and the draft is dropped.
    A save refused for its length drops it too."""
    from apps.api.campaigns.notes_live import queue_put_live
    from apps.api.inbound import lines

    if not clean:
        if await _dropped_if_rewrite(session, holder):
            log.info("holder_script_rewrite_dropped", extra={"reason": "warnings"})
        return

    kind: script_history.HolderKind = "line" if holder.table == "inbound_lines" else "campaign"
    row = (
        await session.execute(
            text(
                f"SELECT script, script_proposal->'base_script' AS base, "
                f"script_proposal->'ask'->>'rewrite' AS rewrite FROM {_table_of(holder)} "
                # Locked, so an owner's save in flight is waited for and then seen.
                "WHERE id = :hid AND script_proposal->>'id' = :pid FOR UPDATE"
            ),
            {"hid": holder.holder_id, "pid": str(holder.proposal_id)},
        )
    ).first()
    if row is None or row.rewrite is None:
        return
    if row.script != row.base or not await script_history.pip_owns(session, kind, holder.holder_id):
        log.info("holder_script_rewrite_dropped", extra={"reason": "changed"})
        await _dropped_if_rewrite(session, holder)
        return
    try:
        async with session.begin_nested():
            if kind == "line":
                await lines.save_script(
                    session,
                    holder.holder_id,
                    script,
                    author="pip_draft",
                    reason=script_history.REWRITE_REASON,
                )
            else:
                await workspace.save_script(
                    session,
                    holder.holder_id,
                    script,
                    author="pip_draft",
                    reason=script_history.REWRITE_REASON,
                )
            await _dropped_if_rewrite(session, holder)
            await queue_put_live(
                session,
                tenant_id=holder.tenant_id,
                jobs=[("line" if kind == "line" else "campaign", holder.holder_id)],
            )
    except ProblemError as refused:
        log.info("holder_script_rewrite_dropped", extra={"reason": refused.code})
        await _dropped_if_rewrite(session, holder)


async def _ready_made(session: AsyncSession, holder: _Holder) -> None:
    """The first run's work (`auto_save`) gets the ready-made script when Pip's own cannot
    be saved, so the owner still reaches the test call (`first_run.work.save_ready_made`).
    A refusal leaves the holder as it was: the screen then offers to write it by hand."""
    from apps.api.first_run.work import save_ready_made

    ids = (
        {"line_id": holder.holder_id}
        if holder.table == "inbound_lines"
        else {"campaign_id": holder.holder_id}
    )
    try:
        async with session.begin_nested():
            await save_ready_made(session, tenant_id=holder.tenant_id, **ids)
    except ProblemError as refused:
        log.info("holder_ready_made_refused", extra={"reason": refused.code})


async def _ready_made_if_asked(holder: _Holder) -> None:
    """After a failed draft: the ready-made script for a first-run holder still without one.
    The failed draft is cleared with it, since the holder now has a script to change."""
    async with tenant_session(holder.tenant_id) as session:
        auto = (
            await session.execute(
                text(
                    f"SELECT script_proposal->>'auto_save' FROM {_table_of(holder)} "
                    "WHERE id = :hid AND script_proposal->>'id' = :pid AND script IS NULL "
                    "FOR UPDATE"
                ),
                {"hid": holder.holder_id, "pid": str(holder.proposal_id)},
            )
        ).scalar_one_or_none()
        if auto != "true":
            return
        await _ready_made(session, holder)
        await session.execute(
            text(
                f"UPDATE {_table_of(holder)} SET script_proposal = NULL WHERE id = :hid "
                "AND script_proposal->>'id' = :pid AND script IS NOT NULL"
            ),
            {"hid": holder.holder_id, "pid": str(holder.proposal_id)},
        )


async def _fail(
    holder: _Holder,
    note: str,
    left_out: list[LeftOut] | None = None,
    *,
    reason: str,
) -> None:
    update = {
        "status": "failed",
        "note": note[:400],
        "reason": reason,
        "left_out": script_proposals.left_out_record(left_out or []),
    }
    async with tenant_session(holder.tenant_id) as session:
        if not await _dropped_if_rewrite(session, holder):
            await _store(session, holder, update)


#: A holder by its kind and id, as `script_builder.job_size` measures it.
_Job = tuple[Literal["campaign", "line"], UUID]


@dataclass(frozen=True)
class _Inputs:
    """What a holder's script is written from, read in one tenant session."""

    agent_id: UUID
    main_task: str
    base: CallScript | None
    notes: str
    words: list[tuple[str, str]]
    context: ScriptBrief
    tenant_leg: Any
    quota_exhausted: bool
    #: The owner's choices for this draft (D-1004): a tone from `TONES`, and what they typed.
    tone: str | None = None
    instruction: str = ""
    #: The holder the script is for, which its length is measured on; None: unmeasured.
    job: _Job | None = None
    #: The characters the script may take in the engine's box, or None when unmeasured.
    budget: int | None = None
    #: The holder's own settings (`campaign_script_ask.situation_block`), or "".
    situation: str = ""
    #: What the holder's calls ask (`script_builder.job_details`); each needs a step.
    details: JobDetails | None = None

    @property
    def replans(self) -> bool:
        """Whether the owner's request lays out the call's steps itself. Such a script is
        written whole rather than as an edit of the one it replaces: an edit keeps whatever
        the request does not change and puts back a step whose new version broke a rule, which
        is how the old install steps survived beside the owner's on 25 Nov 2026."""
        return owner_plan(self.instruction) is not None

    @property
    def whole(self) -> bool:
        return self.base is None or self.replans

    @property
    def plan(self) -> OwnerPlan | None:
        """The steps the script is written and checked against: the request's, else the main
        task's when the script is written whole. An edit of the owner's script with no plan in
        the request keeps whatever shape the owner gave it."""
        return owner_plan(self.instruction) or (
            (owner_plan(self.main_task) or self.task_plan) if self.base is None else None
        )

    #: The main task's numbered list read as steps by `_task_plan`, for a first script whose
    #: main task gives no plan of its own; None when it was not read or did not hold.
    task_plan: OwnerPlan | None = None


def _asked(raw: Any) -> tuple[str | None, str]:
    """The tone and instruction a request stored (`workspace.request_proposal`'s `ask`)."""
    if not isinstance(raw, dict):
        return None, ""
    tone = raw.get("tone")
    instruction = raw.get("instruction")
    return (
        tone if isinstance(tone, str) and tone in TONES else None,
        instruction if isinstance(instruction, str) else "",
    )


def _rewrite(raw: Any) -> bool:
    """Whether a request is Pip's rewrite under the current rules (`workers/script_heal.
    _ask_rewrite`). It is written whole, as a first script is, rather than as an edit of the
    script it replaces, whose shape the new rules exist to change."""
    return isinstance(raw, dict) and bool(raw.get("rewrite"))


async def _size(tenant_id: UUID, job: _Job | None, script: CallScript) -> PromptSize | None:
    """The engine instructions `script` would make on the holder's own engine agent, by the
    measure the save refuses on (`script_builder.job_size`), in a session of its own so a
    failure here never touches the draft's. None when it cannot be measured: the save still
    refuses."""
    from apps.api.agents import script_builder

    if job is None:
        return None
    kind, job_id = job
    try:
        async with tenant_session(tenant_id) as session:
            return await script_builder.job_size(
                session, kind=kind, tenant_id=tenant_id, job_id=job_id, script=script
            )
    except Exception:
        log.exception("holder_script_unmeasured", extra={"holder_id": str(job_id)})
        return None


async def _budget(tenant_id: UUID, job: _Job, base: CallScript | None) -> int | None:
    """What the script may take: the box less what is composed around the script."""
    size = await _size(tenant_id, job, base or CallScript(schema_version=2))
    if size is None:
        return None
    script_chars = next((p.chars for p in size.layers if p.key == "client_script"), 0)
    return budget_of(size.limit, size.total, script_chars)


def _collect_labels(fields: Sequence[CollectField]) -> tuple[str, ...]:
    """What the holder's calls ask as the writer reads them (`ScriptBrief.collect`), each
    with why or when it is asked where that is known, so the steps ask for them where the
    call reaches them (`call_rules.SCRIPT_FLOW_RULE`)."""
    return tuple(
        f"{f.label}: {f.reason}" if f.reason.strip() else f.label for f in fields if f.label
    )


async def draft_campaign_script(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """A campaign's script, from its main task and the sources it picked from What your
    agents know: typed notes and documents alike are read as documents."""
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    campaign_id = UUID(str(payload["campaign_id"]))
    holder = _campaign(tenant_id, campaign_id, UUID(str(payload["proposal_id"])))
    if not await _claim(holder):
        return "not_pending"
    started = time.monotonic()
    inputs, part_ask = await campaign_inputs(tenant_id, campaign_id)
    return await _write(holder, inputs, CAMPAIGN_ASK, started, part_ask=part_ask)


async def campaign_inputs(tenant_id: UUID, campaign_id: UUID) -> tuple[_Inputs, str | None]:
    """Everything a campaign's draft is written from, read when the job runs rather than when
    it was asked for, so a draft asked for as the campaign is made (the first run) reads the
    same main task, sources, settings and details as one asked for later from its page
    (D-1031). The one-part ask is returned beside it."""
    from apps.api.agents.script_builder import campaign_details
    from apps.workers.company_training_draft import knowledge_words

    async with tenant_session(tenant_id) as session:
        space = await workspace.read_workspace(session, campaign_id)
        # No sources picked means everything the agents know, as on the call itself (D-689):
        # an empty list wrote the script from no knowledge at all (founder, 24 Nov 2026).
        words = await knowledge_words(session, only=space.sources or None)
        # Written in the campaign's main language when it sets one over the agent's.
        main_language, focus, asked, name, purpose, goal, consent_source = (
            await session.execute(
                text(
                    "SELECT settings_overrides->>'language_primary', script_proposal->'focus', "
                    "script_proposal->'ask', name, purpose, goal, consent_source "
                    "FROM campaigns WHERE id = :c"
                ),
                {"c": campaign_id},
            )
        ).one()
        part_language = focus.get("language") if isinstance(focus, dict) else None
        # A campaign only places calls, whatever its agent answers
        # (`agents.service.campaign_agent_row`), so its opening_line is a placed call's, and
        # its steps never ask the name of the contact it dialled (`JobDetails.placed`).
        details = (await campaign_details(session, campaign_id)).placed()
        context = replace(
            await script_proposals.brief_for(
                session, tenant_id, space.agent_id, language=part_language or main_language
            ),
            direction="outbound",
            collect=_collect_labels(details.asked),
        )
        tenant_leg = await account_assist_leg(session)
        quota = await read_ai_quota(session, tenant_id=tenant_id)
    # Written from the script the request was made from, as the review lists its changes
    # against it: a script saved since would otherwise be shown as Pip's change.
    base = space.proposal.base_script if space.proposal is not None else space.script
    base = None if _rewrite(asked) else base
    tone, instruction = _asked(asked)
    inputs = _Inputs(
        agent_id=space.agent_id,
        main_task=space.main_task,
        base=base,
        notes="",
        words=words,
        context=context,
        tenant_leg=tenant_leg,
        quota_exhausted=quota.at_ceiling or quota.platform_paused,
        tone=tone,
        instruction=instruction,
        job=("campaign", campaign_id),
        budget=await _budget(tenant_id, ("campaign", campaign_id), base),
        situation=situation_block(
            agent_name=context.agent_name,
            holder_name=str(name or ""),
            purpose=str(purpose or ""),
            goal=str(goal or ""),
            consent_source=consent_source,
        ),
        details=details,
    )
    language_name = LANGUAGE_LABELS.get(str(part_language), str(part_language))
    is_flow = isinstance(focus, dict) and focus.get("part") == FLOW_PART
    part_ask = (
        FLOW_ASK.format(language=language_name)
        if is_flow and part_language
        else PART_ASK.format(
            part=str(focus.get("part")),
            language=language_name,
        )
        if isinstance(focus, dict) and part_language
        else None
    )
    return inputs, part_ask


async def draft_line_script(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """An inbound line's script (D-997), from its main task and the sources it picked from
    What your agents know: typed notes and documents alike are read as documents."""
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    line_id = UUID(str(payload["line_id"]))
    holder = _line(tenant_id, line_id, UUID(str(payload["proposal_id"])))
    if not await _claim(holder):
        return "not_pending"
    started = time.monotonic()
    return await _write(holder, await line_inputs(tenant_id, line_id), LINE_ASK, started)


async def line_inputs(tenant_id: UUID, line_id: UUID) -> _Inputs:
    """Everything a line's draft is written from, read when the job runs (`campaign_inputs`)."""
    from apps.api.agents.script_builder import line_details
    from apps.api.inbound import lines
    from apps.workers.company_training_draft import knowledge_words

    async with tenant_session(tenant_id) as session:
        line = await lines.read_line(session, line_id)
        words = await knowledge_words(session, only=line.sources or None)
        details = await line_details(session, line_id)
        context = replace(
            await script_proposals.brief_for(session, tenant_id, line.agent_id),
            collect=_collect_labels(details.asked),
        )
        # A line answers its calls; only a "both" voice also places its call-backs.
        if context.direction != "both":
            context = replace(context, direction="inbound")
        tenant_leg = await account_assist_leg(session)
        quota = await read_ai_quota(session, tenant_id=tenant_id)
        asked = (
            await session.execute(
                text("SELECT script_proposal->'ask' FROM inbound_lines WHERE id = :l"),
                {"l": line_id},
            )
        ).scalar()
    base = line.proposal.base_script if line.proposal is not None else line.script
    base = None if _rewrite(asked) else base
    tone, instruction = _asked(asked)
    return _Inputs(
        agent_id=line.agent_id,
        main_task=line.main_task,
        base=base,
        notes="",
        words=words,
        context=context,
        tenant_leg=tenant_leg,
        quota_exhausted=quota.at_ceiling or quota.platform_paused,
        tone=tone,
        instruction=instruction,
        job=("line", line_id),
        budget=await _budget(tenant_id, ("line", line_id), base),
        situation=situation_block(
            agent_name=context.agent_name, holder_name=line.name, inbound=True
        ),
        details=details,
    )


def _late_timeout(started: float) -> float | None:
    """One request's budget for a pass after the draft, or None when the job is too short of
    time for one (each ladder may spend `ASSIST_LADDER_LEGS` of them)."""
    per_request = min(PROPOSAL_REQUEST_TIMEOUT_S, _left_s(started) / ASSIST_LADDER_LEGS)
    return per_request if per_request >= _LATE_PASS_MIN_S else None


def _openings_of(script: CallScript, kept_from: CallScript) -> CallScript:
    """`script` with the opening lines and their notice records exactly as `kept_from` has
    them: a pass that only shortens never touches what the call opens with (hard rule 5)."""
    return script.model_copy(
        update={
            "opening_line": kept_from.opening_line,
            "outbound_opening_line": kept_from.outbound_opening_line,
            "opening_notices": kept_from.opening_notices,
            "outbound_opening_notices": kept_from.outbound_opening_notices,
        }
    )


async def _refined(
    inputs: _Inputs,
    context: ScriptBrief,
    script: CallScript,
    started: float,
    *,
    ask: str,
    documents: str,
    owners: str,
) -> tuple[CallScript, list[ScriptDraft | ProblemError]]:
    """A first draft edited once with the same ask, as a press of Generate on it would edit
    it (D-1031), and what that cost. Skipped when the job is short of time, and a refusal
    keeps the first draft: it is already paid for and still goes through every check."""
    timeout_s = _late_timeout(started)
    if timeout_s is None:
        log.info("holder_script_refine_skipped", extra={"reason": "time"})
        return script, []
    change = campaign_change(
        inputs.main_task,
        inputs.notes,
        documents,
        edit=True,
        refine=True,
        ask=ask,
        tone=inputs.tone,
        instruction=inputs.instruction,
        budget=inputs.budget,
        situation=inputs.situation,
        plan=context.owner_plan,
    )
    try:
        draft = await draft_script(
            context,
            tenant_leg=inputs.tenant_leg,
            quota_exhausted=inputs.quota_exhausted,
            edit_of=script,
            change=change,
            timeout_s=timeout_s,
            max_tokens=PROPOSAL_MAX_TOKENS,
            repair_rounds=get_settings().campaign_script_repair_rounds,
            standby_after_answer=False,
            owners_words=owners,
        )
    except ProblemError as refused:
        log.info("holder_script_refine_refused", extra={"reason": refused.code})
        return script, [refused]
    except Exception:
        # The first draft is paid for; a crash here must not lose it.
        log.exception("holder_script_refine_crashed", extra={"agent_id": str(inputs.agent_id)})
        return script, []
    return draft.script, [draft]


def built_wrong(inputs: _Inputs, script: CallScript) -> list[str]:
    """What only a rewrite of the whole `script` mends (`script_shape.structure_problems`),
    read as the steps will stand once code has mended them (`script_structure.collected`): a
    detail the job does not ask, judges from the call or takes on the call-back path is not a
    second ask of its step. With the owner's own steps (`_Inputs.plan`), each departure from
    them, and the main task's items are not read: the owner's steps replace them."""
    ids = {stage.id for stage in script.stages}
    details = inputs.details
    probe = without_judged_asks(script, ids)
    if details is not None:
        probe = collected(probe, details.labels(), ids, details.call_back)
    plan = inputs.plan
    return plan_problems(probe, plan) + structure_problems(
        probe,
        main_task="" if plan is not None else inputs.main_task,
        call_back=details.call_back if details is not None else (),
    )


def _pips_built_wrong(inputs: _Inputs, script: CallScript) -> list[str]:
    """`built_wrong`, less what the owner's script already had: theirs to fix. A script
    written whole owes nothing to the one it replaces."""
    found = built_wrong(inputs, script)
    if inputs.base is None or inputs.whole:
        return found
    had = set(built_wrong(inputs, inputs.base))
    return [problem for problem in found if problem not in had]


def built_wrong_left(inputs: _Inputs, script: CallScript) -> list[LeftOut]:
    """What is still built wrong once every pass is spent, as warnings the owner reads, and
    each of the owner's steps the step limit could not hold."""
    plan = inputs.plan
    over = [
        LeftOut(
            "stages",
            "",
            f'Only {MAX_SCRIPT_STAGES} steps fit a script, so "{step.name}" is not in it; '
            "merge two steps or take one out to make room.",
            unfixed=True,
        )
        for step in (plan.over if plan is not None else ())
    ]
    return [*script_proposals.fix_left(_pips_built_wrong(inputs, script), script), *over]


async def _restructured(
    inputs: _Inputs,
    context: ScriptBrief,
    script: CallScript,
    started: float,
    *,
    ask: str,
    documents: str,
    owners: str,
) -> tuple[CallScript, list[ScriptDraft | ProblemError]]:
    """`script` rewritten once as a whole when it is built wrong (`built_wrong`): details
    piled into one step, a case placed after the close, an item of the main task with no
    step. The targeted repair after it rewrites lines and cannot move a step or add one, so
    these get one edit of the whole script naming them, only when there are any. In an edit
    of the owner's script, only what the owner's script did not already have. A refusal or a
    crash keeps `script`, which is paid for and still goes through every check."""
    found = _pips_built_wrong(inputs, script)
    timeout_s = _late_timeout(started)
    if not found or timeout_s is None:
        return script, []
    change = campaign_change(
        inputs.main_task,
        inputs.notes,
        documents,
        edit=True,
        ask=f"{ask}{RESTRUCTURE_TAIL}" + "".join(f"\n- {problem}" for problem in found),
        tone=inputs.tone,
        instruction=inputs.instruction,
        budget=inputs.budget,
        situation=inputs.situation,
        plan=context.owner_plan,
    )
    try:
        draft = await draft_script(
            context,
            tenant_leg=inputs.tenant_leg,
            quota_exhausted=inputs.quota_exhausted,
            edit_of=script,
            change=change,
            timeout_s=timeout_s,
            max_tokens=PROPOSAL_MAX_TOKENS,
            repair_rounds=get_settings().campaign_script_repair_rounds,
            standby_after_answer=False,
            owners_words=owners,
        )
    except ProblemError as refused:
        log.info("holder_script_restructure_refused", extra={"reason": refused.code})
        return script, [refused]
    except Exception:
        log.exception("holder_script_restructure_crashed", extra={"agent_id": str(inputs.agent_id)})
        return script, []
    log.info(
        "holder_script_restructured",
        extra={"found": len(found), "left": len(built_wrong(inputs, draft.script))},
    )
    return draft.script, [draft]


async def _shortened(
    tenant_id: UUID,
    inputs: _Inputs,
    context: ScriptBrief,
    script: CallScript,
    started: float,
    owners: str,
) -> tuple[CallScript, list[ScriptDraft | ProblemError]]:
    """`script`, shortened once when it would not fit the engine's box, and what that cost.
    A draft that does not fit would be refused when the owner keeps it, after they reviewed
    every part of it."""
    size = await _size(tenant_id, inputs.job, script)
    timeout_s = _late_timeout(started)
    if size is None or size.fits or timeout_s is None:
        return script, []
    parts = ", ".join(part.label for part in size.longest_script_parts()) or "the steps"
    try:
        draft = await draft_script(
            context,
            tenant_leg=inputs.tenant_leg,
            quota_exhausted=inputs.quota_exhausted,
            edit_of=script,
            change=SHORTEN_ASK.format(over=size.over, parts=parts),
            timeout_s=timeout_s,
            max_tokens=PROPOSAL_MAX_TOKENS,
            repair_rounds=1,
            standby_after_answer=False,
            owners_words=owners,
        )
    except ProblemError as refused:
        log.info("holder_script_shorten_refused", extra={"reason": refused.code})
        return script, [refused]
    log.info("holder_script_shortened", extra={"over": size.over})
    return _openings_of(draft.script, script), [draft]


async def _reviewed(
    inputs: _Inputs, tenant_id: UUID, script: CallScript, documents: str, started: float
) -> tuple[Review, JsonAnswer[Review] | ProblemError | None]:
    """The "why" notes and the rubric's findings for the parts Pip wrote (D-1004), and what
    the pass cost. Its failure only leaves them out: the script is already paid for."""
    parts = reviewed_parts(script, inputs.base)
    timeout_s = _late_timeout(started)
    if not parts or timeout_s is None:
        return Review(), None
    owners = owners_words(inputs.main_task, inputs.notes, inputs.instruction)
    sources = review_sources(
        inputs.main_task,
        documents,
        inputs.context.facts,
        situation=inputs.situation,
        instruction=inputs.instruction,
        business_name=inputs.context.business_name,
    )
    try:
        answer = await ask_json(
            review_request(parts, sources, script.outbound_opening_line or script.opening_line),
            REVIEW_INSTRUCTION,
            parse=partial(
                parsed_review,
                keys=[part.key for part in parts],
                allowed=owners,
                sources=sources,
            ),
            azure_format=REVIEW_FORMAT,
            tenant_leg=inputs.tenant_leg,
            quota_exhausted=inputs.quota_exhausted,
            max_tokens=REVIEW_MAX_TOKENS,
            temperature=0.2,
            timeout_s=timeout_s,
        )
    except ProblemError as refused:
        log.info("holder_script_review_refused", extra={"reason": refused.code})
        return Review(), refused
    except Exception:
        # Notes are an aid to the review, never a reason to lose a paid draft.
        log.exception("holder_script_review_crashed", extra={"tenant_id": str(tenant_id)})
        return Review(), None
    return answer.value, answer


#: The parts outside the steps a repair may rewrite. The openings never (hard rule 5,
#: `mistake_fixes.PROTECTED_PARTS`); the step outcomes are read as one list, so a missing task
#: cannot name the line to write and stays a warning the owner reads.
_REPAIRABLE_FIELDS: Final = frozenset({"goal", "ending"})


def _repair_paths(key: str, script: CallScript, kinds: frozenset[str] = frozenset()) -> list[str]:
    """The script check paths a review part covers that the repair may rewrite: a step's
    instruction, lines in each language, small steps and answers (and its ways out for a
    dead end), each quick fact's and objection's answer, the example call's agent lines, the
    goal or the ending; [] for any other part."""
    if key in _REPAIRABLE_FIELDS:
        return [key]
    if key == "faqs":
        return [f"faqs.{i}.answer" for i in range(len(script.faqs))]
    if key == "objections":
        return [f"objections.{i}.response" for i in range(len(script.objections))]
    if key == "example_exchange":
        return [
            f"example_exchange.{i}.text"
            for i, line in enumerate(script.example_exchange)
            if line.speaker == "agent"
        ]
    head, _, stage_id = key.partition(".")
    if head != "stages":
        return []
    for index, stage in enumerate(script.stages):
        if stage.id == stage_id:
            paths = [
                f"stages.{index}.{name}"
                for name in ("instruction", "sounds_like")
                if getattr(stage, name).strip()
            ]
            paths += [f"stages.{index}.scripts.{tag}" for tag in stage.scripts]
            paths += [f"stages.{index}.procedure.{j}.action" for j in range(len(stage.procedure))]
            paths += [f"stages.{index}.qa.{j}.answer" for j in range(len(stage.qa))]
            if "dead_end" in kinds:
                paths.append(f"stages.{index}.branches")
            return paths
    return []


@dataclass(frozen=True, slots=True)
class ReviewFindings:
    #: Findings on lines the repair may rewrite, for `finish_written`'s repair rounds.
    noted: list[Noted]
    #: Findings on the other parts, each a warning with the text it was made on.
    warned: list[tuple[LeftOut, str]]


def review_findings(review: Review, script: CallScript) -> ReviewFindings:
    """The review's findings on `script` (the draft it read): each repairable one at every
    line of its part, the rest as warnings."""
    names = {f"stages.{stage.id}": stage.name for stage in script.stages}
    said = {part.key: part.text for part in reviewed_parts(script, None)}
    noted: list[Noted] = []
    warned: list[tuple[LeftOut, str]] = []
    for key in review.flagged():
        paths = _repair_paths(key, script, review.weak_kinds.get(key, frozenset()))
        for problem in review.problems(key):
            if paths:
                part = tuple((path, text_at(script, path) or "") for path in paths)
                noted += [Noted(f"{path}: {problem}", part) for path in paths]
            else:
                warned.append(
                    (LeftOut(key, names.get(key, ""), problem, unfixed=True), said.get(key, ""))
                )
    return ReviewFindings(noted, warned)


def still_warned(findings: ReviewFindings, script: CallScript) -> list[LeftOut]:
    """The warnings on parts `script` still says as the review read them: an opening the
    opening repair rewrote afterwards is no longer the line the warning was about."""
    said = {part.key: part.text for part in reviewed_parts(script, None)}
    return [left for left, text in findings.warned if said.get(left.part) == text]


def too_long_left(size: PromptSize | None) -> list[LeftOut]:
    """The warning for a script still too long once its shortening pass is spent."""
    if size is None or size.fits:
        return []
    parts = ", ".join(part.label for part in size.longest_script_parts(2)) or "the steps"
    return [LeftOut("script", "", TOO_LONG_RULE.format(over=size.over, parts=parts), unfixed=True)]


def _job_policies(inputs: _Inputs, script: CallScript, documents: str) -> CallScript:
    """`script` with what the job cannot back switched off (`script_structure.policies_for_job`):
    prices nothing it was written from gives, bookings with no calendar. Only while the
    policies are not the owner's: a first script, or one whose base still has the defaults."""
    if inputs.base is not None and inputs.base.policies != ScriptPolicies():
        return script
    sources = review_sources(
        inputs.main_task,
        documents,
        inputs.context.facts,
        situation=inputs.situation,
        instruction=inputs.instruction,
    )
    policies = policies_for_job(
        script.policies, sources=sources, manifest=inputs.context.capabilities
    )
    return (
        script if policies == script.policies else script.model_copy(update={"policies": policies})
    )


Spent = (
    ScriptDraft | JsonAnswer[WrittenOpening] | JsonAnswer[Review] | JsonAnswer[str] | ProblemError
)


async def _task_plan(
    inputs: _Inputs, started: float, log_ids: dict[str, str]
) -> tuple[_Inputs, JsonAnswer[str] | ProblemError | None]:
    """`inputs` with its main task's numbered list read as the call's steps (`task_plan`), and
    what the reading cost; `inputs` as they were when the main task lists nothing, the job is
    short of time, or the answer does not keep one step per item, which leaves the writer
    with the main task's items as it had before. Read once per job, so a retry of the draft
    reuses it. The main task itself is never changed."""
    items = numbered_items(inputs.main_task)
    timeout_s = _late_timeout(started)
    if not items or timeout_s is None:
        return inputs, None
    try:
        answer = await ask_json(
            task_steps_request(inputs.main_task, items),
            TASK_STEPS_INSTRUCTION,
            parse=task_steps_text,
            azure_format=TASK_STEPS_FORMAT,
            tenant_leg=inputs.tenant_leg,
            quota_exhausted=inputs.quota_exhausted,
            max_tokens=TASK_STEPS_MAX_TOKENS,
            temperature=0.2,
            timeout_s=timeout_s,
        )
    except ProblemError as refused:
        log.info("holder_script_task_plan_refused", extra={**log_ids, "reason": refused.code})
        return inputs, refused
    except Exception:
        # The draft is written from the items as before; a failed reading never stops it.
        log.exception("holder_script_task_plan_crashed", extra=log_ids)
        return inputs, None
    plan = owner_plan(answer.value)
    steps = sum(step.number is not None for step in plan.steps) if plan is not None else 0
    used = plan is not None and steps == len(items)
    log.info(
        "holder_script_task_plan",
        extra={**log_ids, "items": len(items), "steps": steps, "used": used},
    )
    return (replace(inputs, task_plan=plan) if used else inputs), answer


def _with_read_steps(notes: dict[str, str], plan: OwnerPlan | None) -> dict[str, str]:
    """The review's notes with, on the steps' outcomes, how Pip read the main task's list
    (`task_steps_note`), so the owner sees the plan their first script was held to beside the
    outcomes it gave each step."""
    if plan is None:
        return notes
    said = notes.get("step_outcomes", "").strip()
    note = task_steps_note(plan)
    return {**notes, "step_outcomes": f"{note} {said}" if said else note}


async def _write(
    holder: _Holder, inputs: _Inputs, ask: str, started: float, *, part_ask: str | None = None
) -> str:
    """Write, check, store and meter one holder's draft."""
    tenant_id = holder.tenant_id
    base = inputs.base
    notes = inputs.notes
    documents = documents_block(inputs.words, budget=KNOWLEDGE_DOCUMENT_CHARS)
    log_ids = {holder.log_key: str(holder.holder_id)}
    reading: JsonAnswer[str] | ProblemError | None = None
    if part_ask is None and base is None and inputs.plan is None:
        inputs, reading = await _task_plan(inputs, started, log_ids)
        if reading is not None:
            # Metered at once: every way this job ends after it has already paid for it.
            async with tenant_session(tenant_id) as session:
                await _meter(session, tenant_id, [reading])
    read_plan = inputs.task_plan if part_ask is None and inputs.plan is inputs.task_plan else None
    # A one-part rewrite is always an edit of the part; otherwise a request that lays out the
    # steps is written whole, like a first script (`_Inputs.replans`).
    whole = inputs.whole and part_ask is None
    plan = inputs.plan if part_ask is None else None
    change = campaign_change(
        inputs.main_task,
        notes,
        documents,
        edit=not whole,
        ask=ask,
        part_ask=part_ask,
        tone=inputs.tone,
        instruction=inputs.instruction,
        budget=inputs.budget,
        situation=inputs.situation,
        plan=plan,
    )
    owners = owners_words(inputs.main_task, notes, inputs.instruction)
    # The proposal keeps the script the request was made from, so the review still shows what
    # a whole rewrite changes against it.
    proposal = _proposal(holder.proposal_id, base, owners, whole=whole)
    feature = crm_assist.ASSIST_FEATURE_SCRIPT_DRAFT
    # The holder's own words are what a spoken figure may come from, an edit's included.
    # A campaign's calls are placed whatever the agent's direction; a line's are answered.
    context = replace(
        inputs.context,
        grounding=change,
        placed_calls=holder.table == "campaigns",
        owner_plan=plan,
    )
    try:
        await _phase(holder, "writing")
    except _DraftStoppedError:
        log.info("holder_script_cancelled", extra={**log_ids, "spends": 0})
        return "cancelled"
    attempt = 0
    asked = change
    while True:
        attempt += 1
        trace = AskTrace()
        write = partial(
            draft_script,
            tenant_leg=inputs.tenant_leg,
            quota_exhausted=inputs.quota_exhausted,
            timeout_s=PROPOSAL_REQUEST_TIMEOUT_S,
            max_tokens=PROPOSAL_MAX_TOKENS,
            trace=trace,
            repair_rounds=get_settings().campaign_script_repair_rounds,
            # The standby's 4,096-token ceiling cuts a whole Telugu script off, so an answer
            # that broke a rule is repaired by the account's model, never handed to it.
            standby_after_answer=False,
            owners_words=owners,
            # The last try keeps a draft that still broke a rule, its lines as warnings:
            # three clean tries first, then a script to review rather than none.
            keep_with_warnings=attempt >= WRITE_ATTEMPTS or _left_s(started) < 2 * _RETRY_MIN_S,
        )
        try:
            if whole or base is None:
                # Written whole, from the owner's steps or else the trade's step plan, the
                # holder's words as the owner's description, so every figure in them may be
                # spoken.
                draft: ScriptDraft = await write(replace(context, description=asked))
            else:
                draft = await write(context, edit_of=base, change=asked)
            break
        except ProblemError as refused:
            log.info(
                "holder_script_refused",
                extra={
                    **log_ids,
                    "reason": refused.code,
                    "repairs": trace.repairs,
                    "truncated": trace.truncated,
                    "attempt": attempt,
                },
            )
            async with tenant_session(tenant_id) as session:
                await crm_assist.meter_refusal(
                    session, tenant_id=tenant_id, refusal=refused, feature=feature
                )
            if _writes_again(refused, trace, attempt, started):
                # A fresh answer told what the last one broke, before the owner hears of it.
                asked = retry_change(change, trace.unwritten, trace.problems)
                continue
            await _fail(holder, _failed_note(refused, trace), trace.unwritten, reason=refused.code)
            await _ready_made_if_asked(holder)
            return "refused"
        except Exception:
            log.exception("holder_script_crashed", extra=log_ids)
            await _fail(holder, workspace.FAILED_NOTE, reason="crashed")
            await _ready_made_if_asked(holder)
            return "failed"

    refining: list[ScriptDraft | ProblemError] = []
    restructuring: list[ScriptDraft | ProblemError] = []
    first = draft.script
    # What a stopped draft has already spent, metered when the job ends early.
    spent_so_far: list[Spent] = [draft]
    try:
        if base is None or whole:
            first, refining = await _refined(
                inputs, context, draft.script, started, ask=ask, documents=documents, owners=owners
            )
            spent_so_far += refining
        if part_ask is None:
            first, restructuring = await _restructured(
                inputs, context, first, started, ask=ask, documents=documents, owners=owners
            )
            spent_so_far += restructuring
        await _phase(holder, "checking")
        # Shortened before the checks, so the review and the repairs read what is offered. The
        # review runs before the call-mistake repair so its findings join those rounds: one
        # repair loop, not a second one after the review.
        written, shortening = await _shortened(tenant_id, inputs, context, first, started, owners)
        spent_so_far += shortening
        review, reviewing = await _reviewed(inputs, tenant_id, written, documents, started)
        spent_so_far += [reviewing] if reviewing is not None else []
        found = review_findings(review, written)
        # Repair rounds are certain only when the review flagged a line; the call-mistake
        # checks inside `finish_written` may add rounds the stream still calls checking.
        await _phase(holder, "repairing" if found.noted else "checking")
    except _DraftStoppedError:
        async with tenant_session(tenant_id) as session:
            await _meter(session, tenant_id, spent_so_far)
        log.info("holder_script_cancelled", extra={**log_ids, "spends": len(spent_so_far)})
        return "cancelled"
    finished = await finish_written(
        tenant_id,
        inputs.agent_id,
        proposal,
        written,
        started,
        noted=found.noted,
        direction=context.direction,
        purpose=inputs.main_task,
        details=inputs.details,
    )
    finished = replace(finished, script=_job_policies(inputs, finished.script, documents))
    spends: list[Spent] = [
        draft,
        *refining,
        *restructuring,
        *shortening,
        *finished.repairs,
        *finished.opening_spends,
        *([reviewing] if reviewing is not None else []),
    ]
    # The reading of the main task is metered already; it is disclosed like any other pass.
    shown = [*spends, *([reading] if reading is not None else [])]
    left_out = [
        *trace.left_out,
        *finished.left_out,
        *too_long_left(await _size(tenant_id, inputs.job, finished.script)),
        *built_wrong_left(inputs, finished.script),
        *still_warned(found, finished.script),
    ]
    update = {
        "status": "ready",
        "script": finished.script.model_dump(mode="json"),
        # A draft, repair or note the standby answered is disclosed with it (D-127 G-6).
        "disclosure": next(
            (
                spent.capability.disclosure
                for spent in shown
                if not isinstance(spent, ProblemError) and spent.capability.disclosure
            ),
            None,
        ),
        "left_out": script_proposals.left_out_record(left_out),
        "why": _with_read_steps(review.notes, read_plan),
    }
    # A completed run is money spent: metered in the same transaction that stores the draft.
    async with tenant_session(tenant_id) as session:
        stored = await _store(session, holder, update)
        if stored:
            await _save_if_asked(session, holder, finished.script)
            await _save_if_rewrite(session, holder, finished.script, clean=not left_out)
        await _meter(session, tenant_id, spends)
    log.info(
        "holder_script_written",
        extra={
            **log_ids,
            "stored": stored,
            "repairs": trace.repairs,
            "checked_repairs": len(finished.repairs),
            "refined": any(isinstance(spent, ScriptDraft) for spent in refining),
            "shortened": bool(shortening),
            "notes": len(review.notes),
            "unsourced": len(review.unsourced),
            "asserted": len(review.asserted),
            "weak": len(review.weak),
        },
    )
    return "ready" if stored else "not_pending"


__all__ = [
    "CAMPAIGN_ASK",
    "LINE_ASK",
    "UNUSABLE_NOTE",
    "campaign_change",
    "campaign_inputs",
    "draft_campaign_script",
    "draft_line_script",
    "line_inputs",
    "owners_words",
    "review_findings",
    "still_warned",
    "too_long_left",
]
