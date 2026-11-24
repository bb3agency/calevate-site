"""The structured call-script builder: load, save (staged), and preview a `CallScript`.

This is the API-side seam between the client-realm builder UI and the two things that
already existed one call apart and never met: `calevate_shared.call_script` (the pure
structured model + compiler) and `agents/prompts.py` (immutable versioned storage with the
two-speed draft/live pointers). The builder authors a `CallScript`; this module COMPILES it
to a `prompt_versions.body` and writes it through the existing slow lane, so a structured
edit stages exactly like a freeform one and never reaches a live call by accident (SURFACES
§2b, the same guarantee `write_prompt_version` gives every script edit).

WHY THE STRUCTURED FORM AND THE COMPILED BODY BOTH GET STORED. `body` is the source of
truth for what the engine runs — `agents/service._load_agent` joins it into the
`AgentConfig`, `compose_engine_prompt` wraps it. `structured_script` is the authored form
the builder reloads so an author sees the steps/FAQ they last wrote rather than the
compiled prose. They are written together at INSERT (`insert_prompt_version`), never apart,
so they cannot drift: the body is always the compile of the structure beside it, plus the
platform's [T0 FACTS] block, which a knowledge recompile (`agents/t0.py`) splices in and
carries the structure forward.

WHY LOADING A LEGACY AGENT STILL WORKS. A prompt version written before the structured
model existed carries a `body` and a NULL `structured_script`. `CallScript.from_freeform`
represents that as a single raw-mode script, so the builder opens on it losslessly and
"save without editing" is a no-op on the engine prompt. This is the migration path from
hard rule 8's two-step angle: nothing is rewritten, the NULL sentinel IS the old data.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal
from uuid import UUID

from calevate_shared.call_script import (
    CallScript,
    Capabilities,
    CollectField,
    call_backs_withheld,
    compile_call_script,
    native_steps,
    render_steps,
    splice_quick_facts,
    without_outline,
)
from calevate_shared.engine import (
    AgentConfig,
    DisclosurePosture,
    compose_engine_prompt,
    notice_fields,
)
from calevate_shared.extraction import ExtractionField, whole_call_detail
from calevate_shared.lead_fields import CORE_KEYS, core_fields
from calevate_shared.opening_notices import OpeningNotices, said_in
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import caller_help, prompt_size
from apps.api.agents.engine_limits import PromptTooLongError, refuse_opening_over_limit
from apps.api.agents.field_suggestions import queue_agent as queue_lead_suggestions
from apps.api.agents.models import is_published
from apps.api.agents.prompts import insert_prompt_version, write_prompt_version
from apps.api.agents.t0_block import block_of, splice_t0_block
from apps.api.agents.write_guard import archived_refusal
from apps.api.compliance.call_notices import AI_NOTICE_SQL, RECORDING_NOTICE_SQL
from apps.api.compliance.trial_access import restricting_trial
from apps.api.core.errors import ProblemError
from apps.api.engine import engine_capabilities, get_engine
from apps.api.engine.hosted_platform import hosted_agent_limits
from apps.api.teach import pinned as pinned_facts
from apps.api.tenancy.core_labels import core_labels


@dataclass(frozen=True, slots=True)
class LoadedScript:
    """A script as the builder needs it: the structured form, plus where it stands.

    `is_freeform` says the loaded version was authored as raw text (NULL
    `structured_script`) and is represented as a raw-mode `CallScript` — the UI opens such
    an agent in the raw-edit escape hatch rather than pretending it has structured steps.
    `version` is None when the agent has no script at all yet (a brand-new agent), which the
    builder renders as an empty structured script ready to author.
    """

    script: CallScript
    version: int | None
    is_freeform: bool
    has_pending: bool


@dataclass(frozen=True, slots=True)
class SavedScript:
    """The result of staging a structured script: which version, and whether it is waiting.

    `staged` True means the agent is live and the edit sits in the draft pointer awaiting
    an explicit Apply (SURFACES §2b); False means a draft/paused agent whose edit is
    applied as written. Mirrors `write_prompt_version`'s own two-speed decision so the UI
    can tell the author "waiting to apply" vs "saved".
    """

    version: int
    staged: bool


# The columns the builder reads about an agent: which prompt version is the DRAFT
# (`system_prompt_id`), whether a change is pending, and the two sentences and the account's
# two switches (D-1021) that compose the opening line the preview shows above the script.
_AGENT_SQL = (
    "SELECT a.system_prompt_id, a.live_prompt_id, a.name, a.direction, a.language_primary, "
    f"a.status, a.ai_disclosure_line, {AI_NOTICE_SQL} AS ai_notice_on, "
    f"a.recording_notice_line, {RECORDING_NOTICE_SQL} AS recording_notice_on, "
    # Sentence three (D-507): the preview must show the opening the caller actually hears,
    # and an agent that remembers says so as part of it.
    "a.caller_memory_notice_line, a.caller_memory_enabled "
    "FROM agents a WHERE a.id = :aid AND a.deleted_at IS NULL"
)


async def _agent_or_404(session: AsyncSession, agent_id: UUID) -> Any:
    row = (await session.execute(text(_AGENT_SQL), {"aid": agent_id})).first()
    if row is None:
        # RLS makes a neighbour's agent and a missing one one answer, deliberately.
        raise ProblemError.not_found("Agent")
    return row


async def assert_agent_visible(session: AsyncSession, agent_id: UUID) -> None:
    """404 unless `agent_id` names an agent visible to the session's tenant (RLS).

    The ownership check the builder's read/write/preview paths get for free from
    `_agent_or_404`, exposed for the paths that act on an agent WITHOUT first loading its
    script (versions, the teach routes, discarding a script suggestion), which must refuse a
    neighbour's id before they write (hard rule 1). One predicate, so every `{agent_id}`
    script path answers a stranger's id the same way.
    """
    await _agent_or_404(session, agent_id)


def _posture(row: Any) -> DisclosurePosture:
    return DisclosurePosture(
        ai_disclosure_line=str(row.ai_disclosure_line),
        ai_disclosure_enabled=bool(row.ai_notice_on),
        recording_notice_line=str(row.recording_notice_line),
        recording_notice_enabled=bool(row.recording_notice_on),
        caller_memory_notice_line=str(row.caller_memory_notice_line),
        caller_memory_enabled=bool(row.caller_memory_enabled),
    )


#: The core details a call ASKS, each with the one case it is asked in (founder, 23 Nov 2026:
#: on the Rytu Khata call of that night the name, the call-back time and another number were
#: never asked). A placed call usually knows the name, so it is asked only when it does not;
#: the time and another number belong to the path where the person wants a call later. The
#: other core details are heard, not asked: what they want, their language and the notes.
#: Short, because each is a line of every job's compiled instructions.
CORE_ASKED_WHEN: Final[dict[str, str]] = {
    "name": "only if not known",
    "preferred_time": "only if they want a call later",
    "other_number": "only if a call back is agreed",
}
#: The core details a call back takes, asked on that path (`script_structure.time_taken`).
CALL_BACK_KEYS: Final = ("preferred_time", "other_number")


@dataclass(frozen=True, slots=True)
class JobDetails:
    """What a job's calls ask, from its "What it notes" (D-1028) and the core every lead
    carries (`calevate_shared.lead_fields`): the details asked, in call order (the name, the
    business's own, then the call-back ones), and the labels of the call-back ones."""

    asked: tuple[CollectField, ...]
    call_back: tuple[str, ...] = ()
    #: The client's label for the core name, when the job asks it.
    name: str = ""

    def labels(self) -> tuple[str, ...]:
        return tuple(f.label for f in self.asked)

    def placed(self) -> JobDetails:
        """What a placed call's script places in its steps: everything but the name. A placed
        call dials a contact from its list and greets them by `{{lead_name}}`, so a step that
        asks the name asks what the call already has (the Rytu Khata call of 25 Nov 2026
        asked an existing customer's name in step 1). The compiled call still lists the name
        "only if not known" (`campaign_collect_fields`), for a contact with no name."""
        if not self.name:
            return self
        return JobDetails(
            asked=tuple(f for f in self.asked if f.label != self.name), call_back=self.call_back
        )


#: A business detail that is the person's own name under another label ("Caller Name",
#: "Customer name"), which the core name already is: asked twice otherwise. A name of
#: something else ("Shop name", "Crop name", "Spouse name") is the business's own detail.
_PERSON_NAME: Final = re.compile(
    r"^(?:(?:caller|customer|client|contact|lead|person|user|member|full|your)\s+)?name$",
    re.IGNORECASE,
)
#: A business detail that is a phone number: the call is on one, and another is the core's
#: "other number", asked on the call-back path. "Phone type" or "mobile model" is not one.
_PHONE_NUMBER: Final = re.compile(
    r"\b(?:phone|mobile|cell|contact|whatsapp|alternate|alternative|other|another|second|"
    r"callback|call back|landline)\s+(?:number|no)\b",
    re.IGNORECASE,
)


def _known_already(key: str, label: str) -> bool:
    """Whether a business detail is one every call already has or asks as a core detail: the
    person's name or a phone number."""
    spellings = [" ".join(text.replace("_", " ").split()) for text in (key, label)]
    return any(_PERSON_NAME.match(text) or _PHONE_NUMBER.search(text) for text in spellings)


def _business_details(stored: Any) -> list[CollectField]:
    """The stored list's business details that are asked, read leniently as the compile
    always has: a row is a dict with a label or key, and a core key's row is the core's. A
    detail judged from the call (`whole_call_detail`) or one the call already has
    (`_known_already`) is noted after the call and never asked."""
    out: list[CollectField] = []
    for raw in stored if isinstance(stored, list) else []:
        if not isinstance(raw, dict):
            continue
        key, label = str(raw.get("key") or ""), str(raw.get("label") or raw.get("key") or "")
        if not label or key in CORE_KEYS or whole_call_detail(key, label):
            continue
        if _known_already(key, label):
            continue
        out.append(
            CollectField(
                label=label, reason=str(raw.get("reason") or ""), required=bool(raw.get("required"))
            )
        )
    return out


def job_details(stored: Any, core: Sequence[ExtractionField]) -> JobDetails:
    """The details a job's calls ask (`JobDetails`): each core detail of `CORE_ASKED_WHEN`
    under the client's own name for it, and each business detail of `stored` that is not
    `whole_call_detail` (read from the call, never asked), with the reason the owner gave."""
    by_key = {f.key: f for f in core}

    def asked_core(key: str) -> CollectField | None:
        field = by_key.get(key)
        return CollectField(label=field.label, reason=CORE_ASKED_WHEN[key]) if field else None

    business = _business_details(stored)
    first = [field for field in (asked_core("name"),) if field is not None]
    last = [field for key in CALL_BACK_KEYS if (field := asked_core(key)) is not None]
    return JobDetails(
        asked=(*first, *business, *last),
        call_back=tuple(field.label for field in last),
        name=first[0].label if first else "",
    )


async def _job_details(session: AsyncSession, stored: Any) -> JobDetails:
    return job_details(stored, core_fields(await core_labels(session)))


async def campaign_details(session: AsyncSession, campaign_id: UUID) -> JobDetails:
    """What a campaign's calls ask (`job_details`), from its "What it notes" (D-1028), the
    list the post-call pipeline notes, so what the call asks and what is written down agree.
    An agent's own script asks for none."""
    own = (
        await session.execute(
            text("SELECT extraction_fields FROM campaigns WHERE id = :cid"), {"cid": campaign_id}
        )
    ).scalar_one_or_none()
    return await _job_details(session, own)


async def line_details(session: AsyncSession, line_id: UUID) -> JobDetails:
    """What an inbound line's calls ask (`job_details`), from its "What it notes"."""
    own = (
        await session.execute(
            text("SELECT extraction_fields FROM inbound_lines WHERE id = :lid"), {"lid": line_id}
        )
    ).scalar_one_or_none()
    return await _job_details(session, own)


async def campaign_collect_fields(session: AsyncSession, campaign_id: UUID) -> list[CollectField]:
    """The details a campaign's compiled script tells the agent to ask (`campaign_details`)."""
    return list((await campaign_details(session, campaign_id)).asked)


async def line_collect_fields(session: AsyncSession, line_id: UUID) -> list[CollectField]:
    """The details an inbound line's compiled script tells the agent to ask (`line_details`)."""
    return list((await line_details(session, line_id)).asked)


async def call_backs_available(session: AsyncSession, tenant_id: UUID) -> bool:
    """Can this account keep a call back right now? Not while it is a restricted trial."""
    return await restricting_trial(session, tenant_id=tenant_id) is None


async def _version_row(session: AsyncSession, version_id: UUID | None) -> Any | None:
    if version_id is None:
        return None
    return (
        await session.execute(
            text("SELECT version, body, structured_script FROM prompt_versions WHERE id = :vid"),
            {"vid": version_id},
        )
    ).first()


def _script_of(version_row: Any | None) -> tuple[CallScript, bool]:
    """The stored version as a `CallScript`, and whether it was freeform.

    A structured version carries JSON we validate back into a `CallScript`; a freeform one
    (NULL `structured_script`) becomes a raw-mode script over its `body`; no version at all
    is an empty structured script ready to author.
    """
    if version_row is None:
        return CallScript(), False
    structured = version_row.structured_script
    if structured is None:
        return CallScript.from_freeform(str(version_row.body)), True
    # Validated rather than trusted: a stored blob is a claim, and a shape the current model
    # rejects should surface as a clean error, not a half-populated editor.
    return CallScript.model_validate(structured), False


async def load_agent_script(
    session: AsyncSession, agent_id: UUID, *, applied: bool = False
) -> LoadedScript:
    """The agent's DRAFT script (or its APPLIED one), as a `CallScript` for the builder.

    `applied=False` (default) loads the draft pointer — what the client is editing.
    `applied=True` loads `live_prompt_id` — what callers currently hear — which the "Undo
    changes" affordance and a "compare to live" view read.
    """
    row = await _agent_or_404(session, agent_id)
    pointer = row.live_prompt_id if applied else row.system_prompt_id
    version_row = await _version_row(session, pointer)
    script, is_freeform = _script_of(version_row)
    return LoadedScript(
        script=script,
        version=int(version_row.version) if version_row is not None else None,
        is_freeform=is_freeform,
        has_pending=row.system_prompt_id != row.live_prompt_id,
    )


async def _same_authored(
    session: AsyncSession, agent_id: UUID, loaded: int | None, on_file: int | None
) -> bool:
    """Did only the platform write versions between the one the editor loaded and the one
    on file? Then the save rebases onto it instead of refusing (D-838).

    The platform rewrites the draft for the owner when pinned facts, lead details or the
    business's facts change (`teach.pinned.recompile_agent`, `recompile_collect`,
    `t0.recompile_t0`). Those versions carry the authored structure unchanged, and this save
    recompiles from the structure with the current facts, so nothing they did is lost.
    Comparing whole versions refused every save made while a fact was being added. Quick
    facts are left out of the comparison: they move to the business at every save.
    A freeform version has no structure to compare and keeps the refusal.
    """
    if loaded is None or on_file is None:
        return False
    rows = (
        await session.execute(
            text(
                "SELECT version, structured_script FROM prompt_versions "
                "WHERE agent_id = :aid AND version IN (:loaded, :on_file)"
            ),
            {"aid": agent_id, "loaded": loaded, "on_file": on_file},
        )
    ).all()
    structures = {int(r[0]): r[1] for r in rows}
    before, after = structures.get(loaded), structures.get(on_file)
    if not isinstance(before, dict) or not isinstance(after, dict):
        return False
    return {**before, "faqs": []} == {**after, "faqs": []}


async def save_agent_script(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    script: CallScript,
    notes: str | None,
    created_by: UUID | None,
    check_version: bool = False,
    expected_version: int | None = None,
) -> SavedScript:
    """Compile `script` and write it as the next immutable version (staged on a live agent).

    The compile happens HERE, once, so the stored `body` is always the compile of the
    stored structure plus the platform's [T0 FACTS] block — there is no path that writes
    one without the other. Staging vs apply is `write_prompt_version`'s decision (it reads
    the agent's live status), so a structured edit and a freeform edit reach a live
    client's callers by the exact same gate.

    `check_version` makes the save conditional on the draft still being `expected_version`
    (None = the agent had no script). The builder edits a copy it loaded earlier; without
    this, a copy loaded before another writer moved the draft (a knowledge recompile, a
    rollback, a second tab) was saved over that newer version and the agent page and the
    builder then showed two different opening lines. The agent row is locked first so the
    check and the write see one draft.

    The [T0 FACTS] block is the platform's, compiled from the business profile and the
    published knowledge (`agents/t0.py`), and the builder never shows it. It is carried
    from the current draft into the new body, because a save that dropped it would take
    the business's facts out of the agent until the next recompile.
    """
    current = (
        await session.execute(
            text(
                "SELECT a.name, pv.version, pv.body FROM agents a "
                "LEFT JOIN prompt_versions pv ON pv.id = a.system_prompt_id "
                "WHERE a.id = :aid AND a.deleted_at IS NULL FOR UPDATE OF a"
            ),
            {"aid": agent_id},
        )
    ).first()
    if current is None:
        raise ProblemError.not_found("Agent")
    on_file = int(current.version) if current.version is not None else None
    if (
        check_version
        and on_file != expected_version
        and not await _same_authored(session, agent_id, expected_version, on_file)
    ):
        raise ProblemError.conflict(
            "script_changed_elsewhere",
            "This script was changed somewhere else after you opened it.",
            remediation=(
                f"Version {on_file} is now saved. Load it to see what changed, then make "
                "your edit again."
                if on_file is not None
                else "Load the script again, then make your edit again."
            ),
        )
    # Quick facts are the business's pinned facts now (founder decision 9): any the script
    # still carries move there, and the body takes the business's list, not the script's.
    if script.faqs:
        await pinned_facts.absorb_script_facts(
            session, tenant_id=tenant_id, faqs=script.faqs, created_by=created_by
        )
        script = script.model_copy(update={"faqs": []})
    body = compile_call_script(script)
    body = await pinned_facts.spliced_body(session, body)
    facts = block_of(current.body)
    if facts is not None:
        body = splice_t0_block(body, facts, identity=f"{current.name}.")
    # `mode="json"` so the stored blob is JSON-native (str/int/list/dict), which is what the
    # `CAST(... AS jsonb)` in `insert_prompt_version` expects and what `model_validate`
    # reads back — no datetimes or enums to smuggle a Python type into the column.
    version = await write_prompt_version(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        body=body,
        notes=notes,
        created_by=created_by,
        structured_script=script.model_dump(mode="json"),
    )
    row = await _agent_or_404(session, agent_id)
    staged = row.status == "live" and row.system_prompt_id != row.live_prompt_id
    # What the script says the business sells may no longer match the lead details (D-889).
    await queue_lead_suggestions(session, tenant_id=tenant_id, agent_id=agent_id)
    # What the agent does may now walk callers through their phone, or no longer.
    await caller_help.queue_pass(session, tenant_id=tenant_id, agent_id=agent_id)
    return SavedScript(version=version, staged=staged)


@dataclass(frozen=True, slots=True)
class Preview:
    """The compiled script as the engine will hold it, and how much of its box it fills."""

    compiled: str
    #: The length of the instructions text alone (steps sent separately are not in it).
    instructions_chars: int
    #: The engine's ceiling on that text, or None where there is none.
    instructions_limit: int | None
    #: How many stages go as the engine's own step list (0 where they stay in the text).
    native_steps: int
    #: The same count by layer and script section, and how far over the box it is.
    size: prompt_size.PromptSize


async def compiled_preview(session: AsyncSession, agent_id: UUID, script: CallScript) -> Preview:
    """The EXACT engine prompt this script would produce — opening, body, platform rules.

    "View compiled prompt" in the builder. It runs the real composer
    (`compose_engine_prompt`) over the real disclosure posture, so what the author sees is
    what the engine holds, INCLUDING the non-removable `TRUTHFUL_ANSWER_DIRECTIVE` appended
    last — which is the point of showing it: a client can watch the platform rules ride
    underneath their own script and cannot make them disappear from the preview.

    The config is the publish's own (`prompt_size.publish_config`, over `service._to_config`)
    with this unsaved script standing in for the applied one, so the length meter and the
    publish refusal count the same text (D-752). A minimal config built from the agent row
    serves only an agent a publish would refuse anyway, such as one with no script yet.
    """
    row = await _agent_or_404(session, agent_id)
    body = compile_call_script(script.model_copy(update={"faqs": []}))
    # The business's pinned facts, plus any quick facts this unsaved script still carries,
    # which a save would move into them (`save_agent_script`).
    pairs = pinned_facts.pairs_of(await pinned_facts.list_pinned(session))
    known = {(q.casefold(), a.casefold()) for q, a in pairs}
    pairs += [
        (f.question.strip(), f.answer.strip())
        for f in script.faqs
        if (f.question.strip().casefold(), f.answer.strip().casefold()) not in known
    ]
    body = splice_quick_facts(body, pairs)
    limits = hosted_agent_limits(get_engine())
    tenant_id = (
        await session.execute(
            text("SELECT tenant_id FROM agents WHERE id = :aid"), {"aid": agent_id}
        )
    ).scalar_one()
    can_call_back = await call_backs_available(session, tenant_id) and not call_backs_withheld(body)
    steps = (
        native_steps(script, can=Capabilities(call_backs=can_call_back))
        if limits.native_steps
        else ()
    )
    instructions = without_outline(body) if steps else body
    # THE PREVIEW SHOWS WHAT THIS DEPLOYMENT'S ENGINE WILL ACTUALLY HOLD — the opening's
    # recording sentence and clause 2 of the truthful-answer floor both follow this fact. A
    # preview that showed the recorded wording on a leg that records nothing would be the
    # one screen a reviewer trusts, lying in the same direction as the bug it guards.
    call_is_recorded = engine_capabilities().records_audio
    fallback = AgentConfig(
        tenant_id="preview",
        agent_id=str(agent_id),
        name=str(row.name),
        direction=row.direction,
        language_primary=str(row.language_primary),
        system_prompt=instructions,
        **notice_fields(_posture(row), call_is_recorded=call_is_recorded),
        call_is_recorded=call_is_recorded,
        facts_in_knowledge=limits.facts_in_knowledge,
        knowledge_tool=limits.knowledge_tool,
        callbacks_offered=can_call_back,
        # The hand-over destination is decided at publish from who is on duty then, so the
        # preview shows the wording for nobody on duty.
        script_steps=steps,
    )
    # The meter counts what a publish sends, built the way a publish builds it (languages,
    # caller memory, a forwarded line, who is on duty); `fallback` serves only an agent a
    # publish would refuse for another reason, such as an empty script.
    engine = get_engine()
    try:
        config = await prompt_size.publish_config(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            engine=engine,
            body=body,
            structured_script=script.model_dump(mode="json"),
        )
    except ProblemError:
        config = fallback
    prompt = compose_engine_prompt(config)
    size = prompt_size.measure_config(config, engine)
    # On an engine with its own step list the stages are sent there, not in the prompt.
    sent_steps = config.script_steps
    compiled = f"{prompt}\n\n{render_steps(sent_steps)}" if sent_steps else prompt
    return Preview(
        compiled=compiled,
        instructions_chars=len(prompt),
        instructions_limit=limits.prompt_chars,
        native_steps=len(sent_steps),
        size=size,
    )


async def refuse_if_too_long(session: AsyncSession, agent_id: UUID, script: CallScript) -> None:
    """Refuse a save or a "Put it live" whose instructions would not fit the engine's box,
    before anything is stored or sent (`engine_limits.PromptTooLongError`, the publish
    refusal's own sentence). The autosaved draft is never refused: it reaches no call."""
    size = (await compiled_preview(session, agent_id, script)).size
    if not size.fits:
        raise PromptTooLongError(size)


#: What `line_config` / `campaign_config` refuse with when a job has no script to measure.
_NOTHING_TO_MEASURE: Final = frozenset({"line_has_no_script", "agent_has_no_script"})


async def refuse_job_if_too_long(
    session: AsyncSession,
    *,
    kind: Literal["campaign", "line"],
    tenant_id: UUID,
    job_id: UUID,
    script: CallScript | None = None,
    for_notes: bool = False,
) -> None:
    """`refuse_if_too_long` for a campaign or an inbound line, measured on the job's own
    engine agent as Start or put-live builds it (`service.campaign_config`,
    `service.line_config`): the job's script with its "What it notes", and for a line the
    placed opening and its call-back rules, none of which the agent's own config carries, so
    measuring the agent would pass a job its publish then refuses. `script` is the one being
    saved, else the stored one; a job with neither has nothing to measure.

    `for_notes` words the refusal for a notes save, whose fix is fewer details as much as a
    shorter script."""
    from apps.api.agents.service import campaign_config, line_config

    try:
        if kind == "campaign":
            config = await campaign_config(
                session, tenant_id=tenant_id, campaign_id=job_id, script=script
            )
        else:
            config = await line_config(session, tenant_id=tenant_id, line_id=job_id, script=script)
    except ProblemError as exc:
        if exc.code in _NOTHING_TO_MEASURE:
            return
        raise
    size = prompt_size.measure_config(config, get_engine())
    if size.fits:
        return
    if for_notes:
        raise PromptTooLongError(
            size,
            title=f"These details make the {kind}'s script too long for the calling system",
            remediation=(
                f"Note fewer details, or shorten the {kind}'s script, then save again. Each "
                "detail a call notes adds a question to the script."
            ),
        )
    raise PromptTooLongError(size)


async def recompile_collect(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID
) -> int | None:
    """Recompile the agent's own script after its starting lead details changed (D-722).

    Since D-1028 an agent's own script asks for no details (what a call notes is its job's
    list), so this only takes out a "what to collect" list an older version still carries.
    Same doctrine as `teach.pinned.recompile_agent`: a new immutable version, applied (and
    republished on a live agent) unless a script edit is staged, in which case it rides with
    that edit. A freeform script is left alone. Returns the new version, or None when nothing
    changed.
    """
    return await rewrite_script(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        script=None,
        notes="Lead details changed: what the agent collects was updated",
    )


@dataclass(frozen=True, slots=True)
class ClearedLines:
    #: The script version written, or None when the current script held none of the lines.
    version: int | None
    #: How many steps lost their line in the current script and in the autosaved draft.
    script_steps: int
    draft_steps: int


def _cleared(script: CallScript, lines: frozenset[str]) -> tuple[CallScript, int]:
    stages = [
        stage.model_copy(update={"sounds_like": ""})
        if stage.sounds_like.strip() in lines
        else stage
        for stage in script.stages
    ]
    count = sum(1 for old, new in zip(script.stages, stages, strict=True) if old is not new)
    return script.model_copy(update={"stages": stages}), count


async def clear_example_lines(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    lines: frozenset[str],
    notes: str,
) -> ClearedLines:
    """Empty the example line of every step still holding one of `lines` word for word, in
    the current script and in the autosaved draft (D-962). A line anybody changed is not one
    of `lines` and is left alone; the rest of the script is kept. The script goes through
    `rewrite_script`, so a live agent is republished and a staged edit carries the change; the
    draft is a compare-and-set autosave, so an owner typing in it at that moment keeps theirs."""
    row = (
        await session.execute(
            text(
                "SELECT pv.structured_script FROM agents a "
                "JOIN prompt_versions pv ON pv.id = a.system_prompt_id "
                "WHERE a.id = :aid AND a.deleted_at IS NULL FOR UPDATE OF a"
            ),
            {"aid": agent_id},
        )
    ).first()
    if row is None or not isinstance(row[0], dict):
        return ClearedLines(version=None, script_steps=0, draft_steps=0)
    script, script_steps = _cleared(CallScript.model_validate(row[0]), lines)
    version = (
        await rewrite_script(
            session, tenant_id=tenant_id, agent_id=agent_id, script=script, notes=notes
        )
        if script_steps
        else None
    )
    draft_steps = 0
    draft = await read_draft(session, agent_id)
    if draft is not None:
        cleared, draft_steps = _cleared(draft.script, lines)
        if draft_steps:
            try:
                await save_draft(session, agent_id, cleared, base_saved_at=draft.saved_at)
            except ProblemError:
                draft_steps = 0
    return ClearedLines(version=version, script_steps=script_steps, draft_steps=draft_steps)


async def rewrite_script(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    script: CallScript | None,
    notes: str,
    created_by: UUID | None = None,
) -> int | None:
    """Write `script` (None: the draft's own structure, recompiled) as a platform-made version.

    Unlike `save_agent_script`, which is the owner's save and stages on a live agent, this is
    for changes the platform makes on the owner's behalf: the version is applied, and a live
    or ready agent republished, unless the owner has a script edit staged, in which case it rides
    with that edit. A freeform draft is left alone. Returns the new version, or None when
    the compiled body would not change. `created_by` names the owner when they asked for it.
    """
    # Local import: `agents/service` imports this module.
    from apps.api.agents.service import publish_agent

    row = (
        await session.execute(
            text(
                "SELECT a.name, a.status, a.engine_agent_ref, pv.body, pv.structured_script, "
                "pv.compiled_t0_context, (a.system_prompt_id IS DISTINCT FROM a.live_prompt_id) "
                "FROM agents a JOIN prompt_versions pv ON pv.id = a.system_prompt_id "
                "WHERE a.id = :aid AND a.deleted_at IS NULL FOR UPDATE OF a"
            ),
            {"aid": agent_id},
        )
    ).first()
    if row is None or not isinstance(row[4], dict):
        return None
    if script is None:
        script = CallScript.model_validate(row[4])
    script = script.model_copy(update={"faqs": []})
    body = compile_call_script(script)
    body = await pinned_facts.spliced_body(session, body)
    facts = block_of(str(row[3]))
    if facts is not None:
        body = splice_t0_block(body, facts, identity=f"{row[0]}.")
    if body == row[3]:
        return None
    staged = bool(row[6])
    version = await insert_prompt_version(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        body=body,
        notes=notes,
        created_by=created_by,
        compiled_t0_context=row[5],
        structured_script=script.model_dump(mode="json"),
        apply_live=not staged,
    )
    if is_published(row[1]) and not staged:
        await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id, take_calls=False)
    return version


# --- the autosaved draft, versions and restore (D-714) --------------------------------


@dataclass(frozen=True, slots=True)
class Draft:
    script: CallScript
    saved_at: datetime


async def read_draft(session: AsyncSession, agent_id: UUID) -> Draft | None:
    """The builder's autosaved working copy, or None when nothing is unpublished."""
    row = (
        await session.execute(
            text(
                "SELECT script_draft, script_draft_saved_at FROM agents "
                "WHERE id = :aid AND deleted_at IS NULL"
            ),
            {"aid": agent_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    if row[0] is None:
        return None
    return Draft(script=CallScript.model_validate(row[0]), saved_at=row[1])


#: "The editor did not say what it loaded": the autosave is unconditional.
UNCHECKED: Final = object()


async def save_draft(
    session: AsyncSession,
    agent_id: UUID,
    script: CallScript,
    *,
    base_saved_at: datetime | object | None = UNCHECKED,
) -> datetime:
    """Autosave: store the working copy on the agent, with no version and no compile, so a
    save per pause in typing costs one row update. Nothing here reaches a call.

    `base_saved_at` is the draft's `saved_at` the editor loaded (None: there was no draft).
    When given, the save is a compare-and-set: a second tab's newer autosave is refused with
    `script_changed_elsewhere` rather than silently overwritten.
    """
    checked = base_saved_at is not UNCHECKED
    saved = (
        await session.execute(
            text(
                "UPDATE agents SET script_draft = CAST(:draft AS jsonb), "
                "script_draft_saved_at = now() WHERE id = :aid AND deleted_at IS NULL "
                "AND (NOT :checked OR script_draft_saved_at IS NOT DISTINCT FROM :base) "
                "RETURNING script_draft_saved_at"
            ),
            {
                "aid": agent_id,
                "draft": script.model_dump_json(),
                "checked": checked,
                "base": base_saved_at if checked else None,
            },
        )
    ).scalar()
    if saved is None and checked:
        await read_draft(session, agent_id)  # 404 for an agent that is not there
        raise ProblemError.conflict(
            "script_changed_elsewhere",
            "This draft was changed somewhere else after you opened it.",
            remediation="Load the latest draft, then make your edit again.",
        )
    if not isinstance(saved, datetime):
        raise ProblemError.not_found("Agent")
    return saved


async def clear_draft(session: AsyncSession, agent_id: UUID) -> None:
    await session.execute(
        text("UPDATE agents SET script_draft = NULL, script_draft_saved_at = NULL WHERE id = :aid"),
        {"aid": agent_id},
    )


@dataclass(frozen=True, slots=True)
class VersionEntry:
    version: int
    #: The change summary given when it was put live (the version's notes).
    summary: str | None
    created_at: datetime
    #: What callers hear now.
    is_live: bool


#: `prompt_versions` is append-only, so an agent's history only grows; the list is a page.
MAX_VERSIONS_PAGE: Final = 100


async def list_versions(
    session: AsyncSession, agent_id: UUID, *, limit: int = MAX_VERSIONS_PAGE
) -> list[VersionEntry]:
    rows = (
        await session.execute(
            text(
                "SELECT pv.version, pv.notes, pv.created_at, (pv.id = a.live_prompt_id) "
                "FROM prompt_versions pv JOIN agents a ON a.id = pv.agent_id "
                "WHERE pv.agent_id = :aid AND a.deleted_at IS NULL "
                "ORDER BY pv.version DESC LIMIT :n"
            ),
            {"aid": agent_id, "n": min(limit, MAX_VERSIONS_PAGE)},
        )
    ).all()
    return [
        VersionEntry(version=int(r[0]), summary=r[1], created_at=r[2], is_live=bool(r[3]))
        for r in rows
    ]


@dataclass(frozen=True, slots=True)
class ReplacedOpening:
    opening_line: str
    #: The new version, or None when the script already had this line.
    version: int | None


async def replace_opening_line(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    opening_line: str,
    created_by: UUID | None,
    placed: bool = False,
    notes: str | None = None,
    notices: OpeningNotices | None = None,
) -> ReplacedOpening:
    """Put a new opening line into the script callers hear and keep the rest of it (D-846).

    `placed` replaces the opening a "both" agent says on the calls it places (D-920) instead
    of the one it answers with, under the same rules.

    The way back from a notice switch refused for want of room: the owner shortens the line
    where they were refused, and it goes live at once, which "Put it live" would also do but
    with the whole working copy. So it is refused while another script change is waiting to
    go live, since applying this would either carry that change with it or leave it behind.
    An autosaved working copy still holding the old line gets the new one too; one that the
    owner had already changed there is theirs and is left alone.

    `notices`: the notice writer's record for the new line (D-971), the words in it that say
    each notice; without it the line says none of them by woven words, and the stored
    sentences are said beside it.
    """
    line = opening_line.strip()
    record = notices if notices is not None else OpeningNotices()
    row = (
        await session.execute(
            text(
                "SELECT a.status, a.direction, pv.structured_script, "
                "(a.live_prompt_id IS NOT NULL "
                "AND a.system_prompt_id IS DISTINCT FROM a.live_prompt_id) AS staged, "
                f"a.ai_disclosure_line, {AI_NOTICE_SQL} AS ai_notice_on, "
                f"a.recording_notice_line, {RECORDING_NOTICE_SQL} AS recording_notice_on, "
                "a.caller_memory_notice_line, a.caller_memory_enabled, a.language_primary "
                "FROM agents a JOIN prompt_versions pv ON pv.id = a.system_prompt_id "
                "WHERE a.id = :aid AND a.deleted_at IS NULL FOR UPDATE OF a"
            ),
            {"aid": agent_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    if str(row.status) == "archived":
        raise archived_refusal("edited")
    if row.staged:
        raise ProblemError.conflict(
            "script_change_waiting",
            "This agent has script changes that are not live yet.",
            remediation=(
                "Open the script and put those changes live or discard them, then shorten "
                "the opening line there."
            ),
        )
    if not isinstance(row.structured_script, dict):
        raise ProblemError.business_rule(
            "opening_line_in_written_script",
            "This agent's script is written as one piece of text.",
            remediation=(
                "Open the script, shorten the line under the opening heading, then put it live."
            ),
        )
    if placed and str(row.direction) != "both":
        raise ProblemError.business_rule(
            "placed_opening_needs_both",
            "Only an agent that answers calls and also calls people has a second opening line.",
            remediation="Change the opening line it has, or give the agent both jobs first.",
        )
    engine = get_engine()
    refuse_opening_over_limit(
        engine,
        agent_id=str(agent_id),
        direction=str(row.direction),
        posture=_posture(row),
        opening=line,
        language=str(row.language_primary),
        placed=placed,
        said=said_in(record, line),
    )
    field = "outbound_opening_line" if placed else "opening_line"
    record_field = "outbound_opening_notices" if placed else "opening_notices"
    script = CallScript.model_validate(row.structured_script)
    old_line = str(getattr(script, field)).strip()
    update = {field: line, record_field: record}
    version = await rewrite_script(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        script=script.model_copy(update=update),
        notes=notes
        or ("Opening line for calls it places changed" if placed else "Opening line shortened"),
        created_by=created_by,
    )
    draft = await read_draft(session, agent_id)
    if draft is not None and str(getattr(draft.script, field)).strip() == old_line:
        await save_draft(session, agent_id, draft.script.model_copy(update=update))
    return ReplacedOpening(opening_line=line, version=version)


#: The history note when the owner puts their own opening back over the notice writer's.
PUT_BACK_NOTE: Final = "Your own opening line put back"


async def put_back_opening_line(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    created_by: UUID | None,
    placed: bool = False,
) -> ReplacedOpening:
    """Put back the opening line the notice writer replaced (D-971's Undo, founder 5 Nov
    2026) and put it live. The line is marked as the owner's choice (`kept_own`), so it is
    not rewritten on the next publish; the stored notice sentences are said beside it."""
    stored = (
        await session.execute(
            text(
                "SELECT pv.structured_script FROM agents a "
                "JOIN prompt_versions pv ON pv.id = a.system_prompt_id "
                "WHERE a.id = :aid AND a.deleted_at IS NULL"
            ),
            {"aid": agent_id},
        )
    ).scalar()
    if stored is None:
        raise ProblemError.not_found("Agent")
    record, line = OpeningNotices(), ""
    if isinstance(stored, dict):
        script = CallScript.model_validate(stored)
        record = script.outbound_opening_notices if placed else script.opening_notices
        line = script.outbound_opening_line if placed else script.opening_line
    before = record.before.strip()
    if not before or " ".join(record.line.split()) != " ".join(line.split()):
        raise ProblemError.conflict(
            "nothing_to_put_back",
            "The opening line has changed since Pip rewrote it.",
            remediation="Change the opening line by hand instead.",
        )
    return await replace_opening_line(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        opening_line=before,
        created_by=created_by,
        placed=placed,
        notes=PUT_BACK_NOTE,
        notices=OpeningNotices(kept_own=before),
    )


__all__ = [
    "CALL_BACK_KEYS",
    "CORE_ASKED_WHEN",
    "MAX_VERSIONS_PAGE",
    "ClearedLines",
    "Draft",
    "JobDetails",
    "LoadedScript",
    "Preview",
    "ReplacedOpening",
    "SavedScript",
    "VersionEntry",
    "assert_agent_visible",
    "call_backs_available",
    "campaign_collect_fields",
    "campaign_details",
    "clear_draft",
    "clear_example_lines",
    "compiled_preview",
    "job_details",
    "line_collect_fields",
    "line_details",
    "list_versions",
    "load_agent_script",
    "put_back_opening_line",
    "read_draft",
    "recompile_collect",
    "replace_opening_line",
    "rewrite_script",
    "save_agent_script",
    "save_draft",
]
