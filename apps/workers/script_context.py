"""Everything a holder's script is written and checked from, read by one loader (DESIGN §3.3).

Every writing path reads its context here: the campaign and line writer, the repair of a
saved script's faulted lines (`workers/script_heal`), the call-mistake fix's re-check
(`workers/mistake_fix`), and the practice-test fixes. Before this, a repair rebuilt its brief
from the agent alone (`script_proposal._repair_draft`): no call direction, no grounding, no
owner plan, no fields to collect and the agent's language instead of the campaign's, so a
campaign's repair was written and judged as an inbound script with no sources.

Read when the job runs, not when it was asked for (D-1031), so a draft asked for as the holder
is made reads the same main task, sources, settings and details as one asked for later.
Tenant-authored configuration only (D-127 G-2); nothing here is logged but ids (hard rule 6).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from calevate_shared.call_script import CallScript, CollectField
from sqlalchemy import text

from apps.api.agents import script_proposals
from apps.api.agents.assist_leg import account_assist_leg
from apps.api.agents.capability_manifest import lint_context_for
from apps.api.agents.languages import LANGUAGE_LABELS
from apps.api.agents.owner_plan import OwnerPlan, owner_plan
from apps.api.agents.script_lint import LintContext
from apps.api.agents.script_plan import EXAMPLE_LIMITS, ExampleLimits
from apps.api.billing.ai_quota import read_ai_quota
from apps.api.campaigns import workspace
from apps.api.campaigns.script_history import pip_owns
from apps.api.core.logging import get_logger
from apps.api.db.session import tenant_session
from apps.api.first_run.models import KNOWLEDGE_DOCUMENT_CHARS
from apps.workers.campaign_script_ask import TONES, budget_of, situation_block
from apps.workers.first_run import documents_block
from apps.workers.script_assist import ScriptBrief

if TYPE_CHECKING:
    from apps.api.agents.prompt_size import PromptSize
    from apps.api.agents.script_builder import JobDetails
    from apps.workers.extraction import TenantModelLeg

log = get_logger(__name__)

HolderKind = Literal["campaign", "line"]


@dataclass(frozen=True, slots=True)
class ScriptContext:
    """What one holder's script is written and checked from."""

    tenant_id: UUID
    kind: HolderKind
    holder_id: UUID
    agent_id: UUID
    #: The business, the call's direction and language, collect labels, facts and notices.
    brief: ScriptBrief
    main_task: str
    #: The holder's saved script, or None.
    saved: CallScript | None
    #: The script an open draft was asked from (`proposal.base_script`), else `saved`.
    asked_from: CallScript | None
    words: tuple[tuple[str, str], ...] = ()
    situation: str = ""
    details: JobDetails | None = None
    #: The owner's tone (`campaign_script_ask.TONES` key) and typed request for this draft.
    tone: str | None = None
    instruction: str = ""
    #: A request to rewrite every line under the current rules (`script_heal._ask_rewrite`).
    rewrite: bool = False
    #: The saved script is still the one Pip wrote (`script_history.pip_owns`): a line
    #: carried over from it is Pip's to repair, not the owner's to keep.
    pip_owned: bool = False
    #: A one-part ask from the Script section (`focus.part`) and its language.
    part: str | None = None
    part_language: str | None = None
    #: What of the part is written: "examples" writes only a step's example turns.
    want: str | None = None
    #: The call's other languages (`languages_extra`: the campaign's, else the agent's), in
    #: which every step's examples are written too.
    extra_languages: tuple[str, ...] = ()
    tenant_leg: TenantModelLeg | None = None
    quota_exhausted: bool = False
    #: The agent's AI and recording sentences, said outside the script.
    spoken_elsewhere: tuple[str, ...] = ()
    #: The characters the script may take in the engine's box, or None when unmeasured.
    budget: int | None = None
    #: The main task's numbered list read as steps by the writer, when that was asked.
    task_plan: OwnerPlan | None = None

    @property
    def placed(self) -> bool:
        """A campaign's calls are placed whatever the agent's direction; a line's answered."""
        return self.kind == "campaign"

    @property
    def language(self) -> str:
        return self.brief.language

    @property
    def languages(self) -> tuple[str, ...]:
        """The call languages each step's examples are written in: the main one first, then
        the call's others; a one-part ask writes only the language it names."""
        if self.part is not None:
            return (self.brief.language,)
        return tuple(dict.fromkeys((self.brief.language, *self.extra_languages)))

    @property
    def limits(self) -> ExampleLimits:
        return EXAMPLE_LIMITS

    @property
    def documents(self) -> str:
        return documents_block(list(self.words), budget=KNOWLEDGE_DOCUMENT_CHARS)

    @property
    def owners_words(self) -> str:
        """The holder in the owner's own words: a line taken from them word for word is
        theirs, and a figure in them may be spoken."""
        return "\n".join(p for p in (self.main_task.strip(), self.instruction.strip()) if p)

    @property
    def grounding(self) -> str:
        """Every text a figure or a claim in a line may come from."""
        return "\n".join(
            p for p in (self.owners_words, self.situation, self.documents) if p.strip()
        )

    @property
    def owner_plan(self) -> OwnerPlan | None:
        """The steps the owner laid out: in the request, else (written whole) in the main
        task or as Pip read the main task's numbered list."""
        asked = owner_plan(self.instruction)
        if asked is not None:
            return asked
        if self.asked_from is not None and not self.rewrite:
            return None
        return owner_plan(self.main_task) or self.task_plan

    @property
    def replans(self) -> bool:
        """The request lays out the call's steps itself, so it is written whole."""
        return owner_plan(self.instruction) is not None

    @property
    def whole(self) -> bool:
        return self.asked_from is None or self.replans or self.rewrite

    def written_brief(self) -> ScriptBrief:
        """The brief with the grounding, call direction and plan this holder's script is
        written against."""
        return replace(
            self.brief,
            grounding=self.grounding,
            placed_calls=self.placed,
            owner_plan=self.owner_plan,
        )

    def lint(self) -> LintContext:
        """The one lint context every path checks this holder's script against: the agent's
        manifest and names, the holder's language, facts and sources, what its calls ask and
        which of those are judged after the call, and whether its calls are placed."""
        brief = self.written_brief()
        lint = brief.lint_context()
        details = self.details
        return replace(
            lint,
            promo=False,
            language=self.language,
            collect=details.labels() if details is not None else (),
            call_back=details.call_back if details is not None else (),
            judged=details.judged if details is not None else (),
            spoken_elsewhere=self.spoken_elsewhere,
        )


def collect_labels(fields: Sequence[CollectField]) -> tuple[str, ...]:
    """What the holder's calls ask as the writer reads them, each with why or when it is
    asked where that is known."""
    return tuple(
        f"{f.label}: {f.reason}" if f.reason.strip() else f.label for f in fields if f.label
    )


def _asked(raw: Any) -> tuple[str | None, str, bool]:
    """The tone, instruction and rewrite flag a request stored (`request_proposal`'s `ask`)."""
    if not isinstance(raw, dict):
        return None, "", False
    tone = raw.get("tone")
    instruction = raw.get("instruction")
    return (
        tone if isinstance(tone, str) and tone in TONES else None,
        instruction if isinstance(instruction, str) else "",
        bool(raw.get("rewrite")),
    )


async def _size(
    tenant_id: UUID, kind: HolderKind, holder_id: UUID, script: CallScript
) -> PromptSize | None:
    """The engine instructions `script` would make on the holder's own engine agent, by the
    one length measure the save refuses on (`script_builder.job_size`); None when it cannot
    be measured (the save still refuses)."""
    from apps.api.agents import script_builder

    try:
        async with tenant_session(tenant_id) as session:
            return await script_builder.job_size(
                session, kind=kind, tenant_id=tenant_id, job_id=holder_id, script=script
            )
    except Exception:
        log.exception("holder_script_unmeasured", extra={"holder_id": str(holder_id)})
        return None


async def measured(context: ScriptContext, script: CallScript) -> PromptSize | None:
    return await _size(context.tenant_id, context.kind, context.holder_id, script)


async def _budget(
    tenant_id: UUID, kind: HolderKind, holder_id: UUID, base: CallScript | None
) -> int | None:
    size = await _size(tenant_id, kind, holder_id, base or CallScript(schema_version=2))
    if size is None:
        return None
    script_chars = next((p.chars for p in size.layers if p.key == "client_script"), 0)
    return budget_of(size.limit, size.total, script_chars)


async def holder_context(
    tenant_id: UUID, kind: HolderKind, holder_id: UUID, *, asked: bool = True
) -> ScriptContext:
    """The context of a campaign's or a line's script. `asked`: read the owner's request on
    the holder's open draft (its tone, words, one-part focus, the script it was asked
    from); False for a pass that writes the SAVED script for a reason of its own (a repair,
    the outcomes, a practice-test fix), which an old draft's request must not steer."""
    if kind == "campaign":
        context = await _campaign_context(tenant_id, holder_id, asked=asked)
    else:
        context = await _line_context(tenant_id, holder_id, asked=asked)
    if asked:
        return context
    return replace(
        context,
        tone=None,
        instruction="",
        rewrite=False,
        part=None,
        part_language=None,
        want=None,
        asked_from=context.saved,
    )


async def _campaign_context(tenant_id: UUID, campaign_id: UUID, *, asked: bool) -> ScriptContext:
    from apps.api.agents.script_builder import campaign_details
    from apps.workers.company_training_draft import knowledge_words

    async with tenant_session(tenant_id) as session:
        space = await workspace.read_workspace(session, campaign_id)
        # No sources picked means everything the agents know, as on the call itself (D-689).
        words = await knowledge_words(session, only=space.sources or None)
        row = (
            await session.execute(
                text(
                    "SELECT c.settings_overrides->>'language_primary' AS main_language, "
                    "c.settings_overrides->'languages_extra' AS own_extra, "
                    "a.languages_extra AS agent_extra, c.script_proposal->'focus' AS focus, "
                    "c.script_proposal->'ask' AS ask, c.name, c.purpose, c.goal, "
                    "c.consent_source FROM campaigns c JOIN agents a ON a.id = c.agent_id "
                    "WHERE c.id = :c"
                ),
                {"c": campaign_id},
            )
        ).one()
        focus = row.focus if asked and isinstance(row.focus, dict) else None
        part_language = focus.get("language") if focus is not None else None
        extra = row.own_extra if isinstance(row.own_extra, list) else row.agent_extra or []
        # A campaign only places calls, so its steps never ask the name of the contact it
        # dialled (`JobDetails.placed`).
        details = (await campaign_details(session, campaign_id)).placed()
        brief = replace(
            await script_proposals.brief_for(
                session, tenant_id, space.agent_id, language=part_language or row.main_language
            ),
            direction="outbound",
            collect=collect_labels(details.asked),
        )
        lint = await lint_context_for(session, tenant_id=tenant_id, agent_id=space.agent_id)
        tenant_leg = await account_assist_leg(session)
        quota = await read_ai_quota(session, tenant_id=tenant_id)
        owned = await pip_owns(session, "campaign", campaign_id)
    tone, instruction, rewrite = _asked(row.ask)
    asked_from = space.proposal.base_script if space.proposal is not None else space.script
    return ScriptContext(
        tenant_id=tenant_id,
        kind="campaign",
        holder_id=campaign_id,
        agent_id=space.agent_id,
        brief=brief,
        main_task=space.main_task,
        saved=space.script,
        asked_from=asked_from,
        words=tuple(words),
        situation=situation_block(
            agent_name=brief.agent_name,
            holder_name=str(row.name or ""),
            purpose=str(row.purpose or ""),
            goal=str(row.goal or ""),
            consent_source=row.consent_source,
        ),
        details=details,
        tone=tone,
        instruction=instruction,
        rewrite=rewrite,
        pip_owned=owned,
        part=str(focus.get("part")) if focus is not None and part_language else None,
        want=str(focus.get("want")) if focus is not None and focus.get("want") else None,
        extra_languages=tuple(str(tag) for tag in extra),
        part_language=(
            LANGUAGE_LABELS.get(str(part_language), str(part_language)) if part_language else None
        ),
        tenant_leg=tenant_leg,
        quota_exhausted=quota.at_ceiling or quota.platform_paused,
        spoken_elsewhere=lint.spoken_elsewhere,
        budget=await _budget(tenant_id, "campaign", campaign_id, asked_from),
    )


async def _line_context(tenant_id: UUID, line_id: UUID, *, asked: bool) -> ScriptContext:
    from apps.api.agents.script_builder import line_details
    from apps.api.inbound import lines
    from apps.workers.company_training_draft import knowledge_words

    async with tenant_session(tenant_id) as session:
        line = await lines.read_line(session, line_id)
        words = await knowledge_words(session, only=line.sources or None)
        details = await line_details(session, line_id)
        row = (
            await session.execute(
                text(
                    "SELECT l.script_proposal->'ask' AS ask, l.script_proposal->'focus' AS focus, "
                    "a.languages_extra AS agent_extra FROM inbound_lines l "
                    "JOIN agents a ON a.id = l.agent_id WHERE l.id = :l"
                ),
                {"l": line_id},
            )
        ).one()
        focus = row.focus if asked and isinstance(row.focus, dict) else None
        part_language = focus.get("language") if focus is not None else None
        brief = replace(
            await script_proposals.brief_for(
                session, tenant_id, line.agent_id, language=part_language
            ),
            collect=collect_labels(details.asked),
        )
        # A line answers its calls; only a "both" voice also places its call-backs.
        if brief.direction != "both":
            brief = replace(brief, direction="inbound")
        lint = await lint_context_for(session, tenant_id=tenant_id, agent_id=line.agent_id)
        tenant_leg = await account_assist_leg(session)
        quota = await read_ai_quota(session, tenant_id=tenant_id)
        owned = await pip_owns(session, "line", line_id)
    tone, instruction, rewrite = _asked(row.ask)
    asked_from = line.proposal.base_script if line.proposal is not None else line.script
    return ScriptContext(
        tenant_id=tenant_id,
        kind="line",
        holder_id=line_id,
        agent_id=line.agent_id,
        brief=brief,
        main_task=line.main_task,
        saved=line.script,
        asked_from=asked_from,
        words=tuple(words),
        situation=situation_block(agent_name=brief.agent_name, holder_name=line.name, inbound=True),
        details=details,
        tone=tone,
        instruction=instruction,
        rewrite=rewrite,
        pip_owned=owned,
        part=str(focus.get("part")) if focus is not None and part_language else None,
        part_language=(
            LANGUAGE_LABELS.get(str(part_language), str(part_language)) if part_language else None
        ),
        want=str(focus.get("want")) if focus is not None and focus.get("want") else None,
        extra_languages=tuple(str(tag) for tag in row.agent_extra or ()),
        tenant_leg=tenant_leg,
        quota_exhausted=quota.at_ceiling or quota.platform_paused,
        spoken_elsewhere=lint.spoken_elsewhere,
        budget=await _budget(tenant_id, "line", line_id, asked_from),
    )


__all__ = [
    "HolderKind",
    "ScriptContext",
    "collect_labels",
    "holder_context",
    "measured",
]
