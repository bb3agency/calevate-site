"""The wizard's intake step — FLOWS §1 step 3, and only what §1 asks for.

    3. **Intake (the real work)**: guided form collecting business hours,
       address/branches, services + prices, top FAQs, staff names/pronunciations,
       booking rules, escalation contacts, languages. Output feeds T0 compiled
       context + KB seed + prompt generation.

§1 NAMES the fields, so this module builds those eight and invents none. That matters,
because the step was deferred on the grounds that it "needs client #1 in the room" —
a real argument against inventing a field list, and no argument at all for a step that
does not exist when the doc already says what it collects. What genuinely needs client
#1 is the CONTENT of a clinic's answers, not the question list; PROMPT-GUIDE §2's
[T0 FACTS] block independently names the same six prose facts ("hours, address,
services+prices, top FAQs, staff, booking rules"), which is the second half of the
same specification.

**Where the answers go — all three of §1's outputs, no fourth one invented:**

1. **T0 compiled context.** The six prose facts compile into a `[T0 FACTS]` block that
   is written into the agent's prompt AND stored in `prompt_versions.compiled_t0_context`
   — the column D-39 reserves for exactly this artifact, previously written by nothing.
2. **Prompt generation.** The block is spliced into the current prompt body, replacing
   any earlier block and leaving every hand-written section alone: PROMPT-GUIDE §2 says
   [T0 FACTS] is auto-generated and regenerated, never hand-edited. The prompt is what
   `agents.service.publish_agent` sends to the engine, so this is the path by which an
   intake answer becomes something the agent can say to a caller.
3. **KB seed.** The same facts are submitted as a `text` source through the ordinary
   `kb.submit_source` path — `pending_approval`, never auto-approved. Our approval gate
   (FLOWS §7, D-28) exists so a human sees what reaches the engine; the one upload that
   skipped it would be ours.

Two of the eight fields are NOT prose and do not belong in a prompt: escalation contacts
and languages. They land in `agents.escalation_config` and `agents.languages_extra`,
which is where DATA-MODEL §3 already puts them — a staff mobile number compiled into a
system prompt is a number the agent can read out to whoever asks. Business hours land in
`agents.business_hours` for the same reason (FLOWS §3's after-hours flag is specified to
read that column) AND in the block, because a caller does ask what time you open.

**Where the raw answers go (migration c1f3a7d92b46).** All three outputs above are
DERIVATIVES: a compiled sentence, a KB body, three typed columns. None of them is the
form. FLOWS §1 promises "draft state saved at every step (resume anytime)", so the
answer sheet itself is stored verbatim on `organizations.intake` — the business's own
facts on the row that IS the business (DATA-MODEL §2), inheriting that table's existing
FORCEd policy rather than minting a new one. The migration argues the choice against a
`client_intake` table in full; the two rules that follow from it here are:

- **A draft save is partial by definition.** `save_intake_draft` writes the sheet and
  nothing else — no compile, no prompt version, no KB source, no publish. Half a step
  is what a wizard mid-flow looks like, and every field on `IntakeFacts` is optional
  for that reason.
- **A submit is not.** `record_intake` runs `submission_blockers` first and refuses an
  intake too thin to compile into an agent that can answer a caller. Draft freely,
  publish deliberately.

**Which lane a submit is on (SURFACES §2b).** Intake is TRAINING: it applies
immediately, so a live agent is re-published in the same transaction. The one exception
is the one `agents/t0.py` already carries and for the same reason — a hand-written
script edit waiting behind "Apply to live calls" shares the same body column, so
applying the facts would drag that unapproved script onto a phone line. When that is
the case the facts stage with it and the result says so (`staged_behind_script`), rather
than the step reporting a version number an operator reads as "live".

`read_intake` returns what a resume needs: the sheet's own fields plus the structured
columns, with the compiled block for display.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import t0
from apps.api.agents.prompts import insert_prompt_version
from apps.api.agents.service import publish_agent
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.result import rowcount_of
from apps.api.db.session import tenant_session
from apps.api.kb import service as kb_service

log = get_logger(__name__)

# The section marker and the splice both live in `agents/t0.py`, which OWNS the block
# format (PROMPT-GUIDE §2). This module used to carry byte-identical copies of both,
# with `tests/t0_recompile_test.py` pinning them to the same output — a test whose whole
# job was to stop two copies drifting. The reason given for the copy was a cycle,
# `admin.intake → kb.service → agents.t0 → admin.intake`, which the arrow at the top of
# this file already disproves: intake imports `agents.t0` directly, and `t0` imports
# nothing from `admin`. One definition; the pinning test now asserts there is only one.
_KB_SOURCE_NAME = "Business facts (intake)"

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_HHMM = r"^(?:[01]\d|2[0-3]):[0-5]\d$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DayHours(_Strict):
    """One day of the week. `closed` is explicit rather than implied by an absent day:
    "we do not open on Sunday" and "nobody filled Sunday in" are different answers, and
    the agent says different things about them."""

    day: Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    opens: str | None = Field(default=None, pattern=_HHMM)
    closes: str | None = Field(default=None, pattern=_HHMM)
    closed: bool = False


class Branch(_Strict):
    label: str = Field(min_length=1, max_length=80)
    address: str = Field(min_length=1, max_length=400)


class ServiceItem(_Strict):
    """`price_inr` is a STRING (hard rule 7): a price read aloud to a caller must be
    the digits the client typed, and a JSON float cannot promise that. It is also
    optional — "consultation: ask at reception" is a real answer."""

    name: str = Field(min_length=1, max_length=120)
    price_inr: str | None = Field(default=None, max_length=20, pattern=r"^\d+(\.\d{1,2})?$")
    notes: str | None = Field(default=None, max_length=200)


class Faq(_Strict):
    question: str = Field(min_length=1, max_length=300)
    answer: str = Field(min_length=1, max_length=1000)


class StaffMember(_Strict):
    """`pronunciation` is not decoration — PROMPT-GUIDE §3 requires proper nouns to be
    spelled phonetically in [T0 FACTS], because a mispronounced doctor's name is the
    first thing a caller notices."""

    name: str = Field(min_length=1, max_length=120)
    pronunciation: str | None = Field(default=None, max_length=120)
    role: str | None = Field(default=None, max_length=80)


class EscalationContact(_Strict):
    name: str = Field(min_length=1, max_length=120)
    phone_e164: str = Field(pattern=r"^\+[1-9]\d{7,18}$")
    hours: str | None = Field(default=None, max_length=60)


class IntakeFacts(_Strict):
    """Exactly FLOWS §1 step 3's list, in its order. Every field is optional-by-default
    because the step is resumable and an operator fills it over days — the gate that
    decides an agent is ready to publish is step 7's test call, not this form."""

    business_hours: list[DayHours] = Field(default_factory=list, max_length=7)
    branches: list[Branch] = Field(default_factory=list, max_length=20)
    services: list[ServiceItem] = Field(default_factory=list, max_length=100)
    faqs: list[Faq] = Field(default_factory=list, max_length=50)
    staff: list[StaffMember] = Field(default_factory=list, max_length=50)
    booking_rules: str | None = Field(default=None, max_length=2000)
    escalation_contacts: list[EscalationContact] = Field(default_factory=list, max_length=10)
    # BCP-47 tags; the agent's own `language_primary` is dropped when this is stored,
    # since `languages_extra` means the OTHERS (DATA-MODEL §3).
    languages: list[str] = Field(default_factory=list, max_length=6)


class IntakeProse(_Strict):
    """The five answers with no typed column anywhere else — the half of the form that
    used to survive only as a compiled sentence.

    Deliberately NOT the other three: hours, escalation contacts and languages round
    trip from `agents` (DATA-MODEL §3), and a second copy of an escalation contact in
    a second shape is how the two start disagreeing. It also keeps phone numbers out
    of this model, which is what the read path returns to a browser.
    """

    branches: list[Branch] = Field(default_factory=list)
    services: list[ServiceItem] = Field(default_factory=list)
    faqs: list[Faq] = Field(default_factory=list)
    staff: list[StaffMember] = Field(default_factory=list)
    booking_rules: str | None = None

    @classmethod
    def from_facts(cls, facts: IntakeFacts) -> IntakeProse:
        return cls(
            branches=facts.branches,
            services=facts.services,
            faqs=facts.faqs,
            staff=facts.staff,
            booking_rules=facts.booking_rules,
        )


# ------------------------------------------------------- the durable answer sheet

# Bump when the envelope (not the answers) changes shape. The CHECK in migration
# c1f3a7d92b46 pins `version` + `answers`; a reader that finds a version it does not
# know falls back to the derived columns rather than guessing.
SHEET_VERSION = 1

# `COALESCE(... ) || :doc` rather than a plain assignment: the merge keeps envelope keys
# an earlier save wrote (notably `submitted_at`), so saving a draft after a submit does
# not silently un-submit the step. `answers` is a top-level key and is REPLACED whole —
# a deep merge would resurrect a service the operator deleted.
_SAVE_SHEET = (
    "UPDATE organizations SET intake = COALESCE(intake, '{}'::jsonb) || CAST(:doc AS jsonb) "
    "|| jsonb_build_object('saved_at', to_jsonb(now())), updated_at = now() WHERE id = :tid"
)
_SUBMIT_SHEET = (
    "UPDATE organizations SET intake = COALESCE(intake, '{}'::jsonb) || CAST(:doc AS jsonb) "
    "|| jsonb_build_object('saved_at', to_jsonb(now()), 'submitted_at', to_jsonb(now())), "
    "updated_at = now() WHERE id = :tid"
)


async def _store_sheet(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    facts: IntakeFacts,
    submitted: bool,
) -> None:
    """Persist the answers as typed, on the tenant's own `organizations` row.

    No RLS exemption and no tenant_id parameter smuggled past a policy: under
    `tenant_session` the organizations policy matches on `id`, so a wrong tenant is
    zero rows and a clean 404 — the same failure `_agent_state` gives for an agent.
    """
    doc = {
        "version": SHEET_VERSION,
        # Which agent the answers were last compiled into. Provenance, not ownership:
        # the facts belong to the business (one sheet per org), and this says whose
        # prompt currently carries them.
        "agent_id": str(agent_id),
        "answers": facts.model_dump(mode="json"),
    }
    result = await session.execute(
        text(_SUBMIT_SHEET if submitted else _SAVE_SHEET),
        {"doc": json.dumps(doc), "tid": tenant_id},
    )
    if rowcount_of(result) == 0:
        raise ProblemError.not_found("Organization")


def submission_blockers(facts: IntakeFacts) -> list[str]:
    """What is still missing before this intake can BE an agent, as stable codes.

    A draft may be missing anything; a submit may not be missing the facts without
    which the three outputs are hollow. Each entry earns its place by naming something
    downstream that cannot work without it — this is not a completeness score:

    - hours: FLOWS §3's after-hours branch is specified to read `agents.business_hours`,
      and an empty map is a branch that can never fire. A day that is neither `closed`
      nor has both times is worse than an absent one: it compiles to nothing while
      looking answered.
    - branches: "where are you?" is the second question every caller asks.
    - services: the price list is the KB seed and the most-asked question both.
    - escalation contacts: `transfer_call` (FLOWS §3) has nowhere to transfer to.

    FAQs, staff and booking rules are NOT blockers, and the omission is deliberate: a
    single-practitioner shop with no FAQ list and no named staff is a real client, and
    a gate that refuses it would be this module inventing policy FLOWS §1 does not
    state. Step 7's test call is the gate on whether the agent is any good.
    """
    blockers: list[str] = []
    if not facts.business_hours:
        blockers.append("business_hours_missing")
    elif any(not (day.closed or (day.opens and day.closes)) for day in facts.business_hours):
        blockers.append("business_hours_incomplete")
    if not facts.branches:
        blockers.append("branch_missing")
    if not facts.services:
        blockers.append("service_missing")
    if not facts.escalation_contacts:
        blockers.append("escalation_contact_missing")
    return blockers


# --------------------------------------------------------------- the T0 compiler


def _hours_map(facts: IntakeFacts) -> dict[str, dict[str, str] | None]:
    """`{"mon": {"opens": .., "closes": ..}, "sun": None}` — None IS the closed day."""
    out: dict[str, dict[str, str] | None] = {}
    for day in facts.business_hours:
        if day.closed or not (day.opens and day.closes):
            out[day.day] = None
        else:
            out[day.day] = {"opens": day.opens, "closes": day.closes}
    return out


def _hours_line(hours: dict[str, dict[str, str] | None]) -> str | None:
    if not hours:
        return None
    parts = [
        f"{day} {h['opens']}-{h['closes']}" if (h := hours[day]) else f"{day} closed"
        for day in DAYS
        if day in hours
    ]
    return "Hours: " + "; ".join(parts)


def compile_t0_facts(facts: IntakeFacts) -> str:
    """The [T0 FACTS] block, in PROMPT-GUIDE §2's order: hours, address, services +
    prices, top FAQs, staff, booking rules.

    Deterministic, so re-running the step with unchanged answers produces a
    byte-identical block — which is what makes `record_intake` idempotent instead of
    minting a prompt version per save.

    No escalation numbers and no language list: neither is a fact the agent says, and
    the size budget (§2: ~2,500 tokens total) is spent on what a caller asks about.
    """
    lines: list[str] = [t0.T0_HEADER]
    hours = _hours_line(_hours_map(facts))
    if hours:
        lines.append(hours)
    for branch in facts.branches:
        lines.append(f"Address ({branch.label}): {branch.address}")
    for item in facts.services:
        price = f" — ₹{item.price_inr}" if item.price_inr else " — price on request"
        notes = f" ({item.notes})" if item.notes else ""
        lines.append(f"Service: {item.name}{price}{notes}")
    for faq in facts.faqs:
        lines.append(f"FAQ: {faq.question} — {faq.answer}")
    for person in facts.staff:
        said = f" (said: {person.pronunciation})" if person.pronunciation else ""
        role = f", {person.role}" if person.role else ""
        lines.append(f"Staff: {person.name}{said}{role}")
    if facts.booking_rules:
        lines.append(f"Booking: {facts.booking_rules}")
    return "\n".join(lines)


def kb_seed_text(facts: IntakeFacts) -> str:
    """The same facts as a KB source body — paragraph-separated, because `chunk_text`
    splits on paragraphs and a chunk is what gets read aloud."""
    block = compile_t0_facts(facts)
    return "\n\n".join(line for line in block.splitlines() if line != t0.T0_HEADER)


# ------------------------------------------------------------------- the step


class _AgentState(BaseModel):
    """The four facts this module needs about the agent it is writing to."""

    status: str
    engine_agent_ref: str | None
    language_primary: str
    active_version: int | None
    # SURFACES §2b: is a hand-written script edit already waiting behind "Apply to live
    # calls"? Same question, same expression and same consequence as `agents/t0.py`.
    script_staged: bool


async def _agent_state(session: AsyncSession, agent_id: UUID) -> _AgentState:
    """Load it, and prove it exists.

    Under a tenant-scoped session RLS is what makes another tenant's agent invisible, so
    this doubles as the isolation: a wrong-tenant id is a clean 404, not a write that
    silently lands nowhere.
    """
    row = (
        await session.execute(
            text(
                "SELECT a.status, a.engine_agent_ref, a.language_primary, pv.version, "
                "(a.system_prompt_id IS DISTINCT FROM a.live_prompt_id) "
                "FROM agents a LEFT JOIN prompt_versions pv ON pv.id = a.system_prompt_id "
                "WHERE a.id = :aid AND a.deleted_at IS NULL"
            ),
            {"aid": agent_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    return _AgentState(
        status=str(row[0]),
        engine_agent_ref=row[1],
        language_primary=str(row[2]),
        active_version=int(row[3]) if row[3] is not None else None,
        script_staged=bool(row[4]),
    )


async def _current_prompt(session: AsyncSession, agent_id: UUID) -> tuple[str | None, str | None]:
    """(body, compiled_t0_context) of the version the agent currently points at."""
    row = (
        await session.execute(
            text(
                "SELECT pv.body, pv.compiled_t0_context FROM agents a "
                "JOIN prompt_versions pv ON pv.id = a.system_prompt_id WHERE a.id = :aid"
            ),
            {"aid": agent_id},
        )
    ).first()
    return (row[0], row[1]) if row is not None else (None, None)


#: The note every intake-minted version carries, so the history says which step wrote it.
_PROMPT_NOTES = "regenerated from intake (FLOWS §1 step 3)"


async def save_intake_draft(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    facts: IntakeFacts,
) -> dict[str, Any]:
    """Save the step as it stands. A half-filled form is the normal case, not an error.

    This is FLOWS §1's "draft state saved at every step" and nothing more: no compiled
    block, no prompt version, no KB source, no publish. That restraint is the point —
    an operator who has typed three services and gone to lunch must not thereby have
    changed what a LIVE agent tells callers, and must not mint a prompt version per
    keystroke either. Everything downstream happens at submit, once.

    Returns the blockers that still stand between this draft and a submit, so the
    wizard can show them while they are still cheap to fix.
    """
    await _agent_state(session, agent_id)  # 404 for another tenant's agent, before writing
    await _store_sheet(
        session, tenant_id=tenant_id, agent_id=agent_id, facts=facts, submitted=False
    )
    # Counts and codes only. The answers are the client's business detail and the
    # escalation contacts are phone numbers (hard rule 6).
    blockers = submission_blockers(facts)
    log.info(
        "intake_draft_saved",
        extra={"agent_id": str(agent_id), "blockers": len(blockers)},
    )
    return {"agent_id": agent_id, "blockers": blockers}


async def record_intake(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    facts: IntakeFacts,
    recorded_by: UUID | None,
) -> dict[str, Any]:
    """Capture the client's business facts and push them at everything that uses them.

    Idempotent by comparison, not by luck: if the compiled block is byte-identical to
    the one the agent's active version already carries, no prompt version is minted and
    no KB source is seeded. An operator who reopens the step, reads it and saves has
    changed nothing, and FLOWS §1 requires every step to survive exactly that.

    A LIVE agent is re-published in the SAME transaction, for the reason
    agents/prompts.py gives: a fact change that only lands in our database is a lie on
    the admin screen, and an engine failure must roll the version back with it.

    This is the SUBMIT path, so unlike `save_intake_draft` it validates the whole set:
    what gets compiled here is what an agent says to a caller, and half an answer sheet
    compiles into an agent that cannot say where the clinic is.
    """
    business_name = (
        await session.execute(
            text("SELECT name FROM organizations WHERE id = :tid"), {"tid": tenant_id}
        )
    ).scalar()
    if business_name is None:
        raise ProblemError.not_found("Organization")

    agent = await _agent_state(session, agent_id)

    blockers = submission_blockers(facts)
    if blockers:
        # The codes, never the answers: a problem+json body is a user-safe message
        # (RFC-9457 house rule) and the wizard already holds the values it typed.
        raise ProblemError.business_rule(
            "intake_incomplete",
            "The intake is missing answers the agent needs: " + ", ".join(blockers) + ".",
            remediation="Save the step as a draft, finish these answers, then submit.",
        )

    # The answer sheet first, so a submit that later fails a downstream check has still
    # persisted what was typed — and so the sheet is written even on the unchanged path
    # below, where an edit to escalation contacts changes no compiled byte.
    await _store_sheet(session, tenant_id=tenant_id, agent_id=agent_id, facts=facts, submitted=True)

    hours = _hours_map(facts)
    # `languages_extra` is the OTHER languages (DATA-MODEL §3), so the agent's primary
    # is dropped rather than stored twice under two names.
    extra = [lang for lang in facts.languages if lang and lang != agent.language_primary]
    await session.execute(
        text(
            "UPDATE agents SET business_hours = CAST(:hours AS jsonb), "
            "escalation_config = CAST(:escalation AS jsonb), languages_extra = :langs, "
            "updated_at = now() WHERE id = :aid AND deleted_at IS NULL"
        ),
        {
            "hours": json.dumps(hours) if hours else None,
            "escalation": (
                json.dumps({"contacts": [c.model_dump() for c in facts.escalation_contacts]})
                if facts.escalation_contacts
                else None
            ),
            "langs": extra or None,
            "aid": agent_id,
        },
    )

    # The intake half is ours; the published-knowledge half is not. Compiling only our
    # own half and writing it as the whole block dropped every fact a client had already
    # approved — [T0 FACTS] would lose "Published knowledge:" until the next KB publish
    # happened to restore it. So the block is composed through the module that OWNS the
    # format (`agents.t0`), with "what is live" answered by the module that owns that
    # question (`kb.service.active_knowledge`). Passing our freshly compiled half as
    # `previous` is exactly right: `compile_block` keeps the non-knowledge lines of what
    # it is given, so the intake step still decides its own half completely and only
    # stops deciding the other one.
    block = t0.compile_block(
        previous=compile_t0_facts(facts),
        knowledge=await kb_service.active_knowledge(session, agent_id=agent_id),
    ).block
    body, current_block = await _current_prompt(session, agent_id)
    if current_block == block and body is not None and block in body:
        log.info("intake_unchanged", extra={"agent_id": str(agent_id)})
        return {
            "agent_id": agent_id,
            "prompt_version": agent.active_version,
            "regenerated": False,
            "kb_source_id": None,
            "staged_behind_script": agent.script_staged,
        }

    # THE FACTS RIDE THE SAME LANE `agents/t0.py` PUTS A RECOMPILE ON, and for the same
    # reason: the block is spliced into the DRAFT body, so applying it would publish
    # whatever hand-written script is waiting behind Apply — the blast-radius accident
    # SURFACES §2b:101 exists to prevent. With nothing staged the two pointers agree and
    # the facts apply immediately, which is what "training applies immediately" means.
    #
    # Written through `prompts.insert_prompt_version` rather than by a second INSERT of
    # this module's own. The copy that used to live here set `system_prompt_id` and left
    # `live_prompt_id` untouched, which broke the invariant `agents/service.py` depends
    # on ("NULL can only mean the two pointers agree") in both directions: a freshly
    # onboarded, freshly published agent reported a phantom "Script v1 is waiting to go
    # live" on the client's own screen forever, and re-submitting the intake over a
    # staged edit published the OLD applied script while answering with the new version
    # number. One statement may mint a `prompt_versions` row; this module is a caller.
    applies_now = not agent.script_staged
    version = await insert_prompt_version(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        body=t0.splice_t0_block(body, block, identity=f"{business_name} receptionist."),
        notes=_PROMPT_NOTES,
        created_by=recorded_by,
        compiled_t0_context=block,
        apply_live=applies_now,
    )

    seed = kb_seed_text(facts)
    kb_source_id: UUID | None = None
    if seed.strip():
        seeded = await kb_service.submit_source(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name=_KB_SOURCE_NAME,
            body=seed,
            kind="text",
            submitted_by=recorded_by,
        )
        kb_source_id = UUID(str(seeded["id"]))

    # `and applies_now`: publishing while the facts are staged would push the version
    # the applied pointer still names — the old script — under the banner of a submit
    # that just reported a new one.
    if agent.status == "live" and agent.engine_agent_ref and applies_now:
        await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)

    # ids and counts only: services, FAQs and escalation numbers are client business
    # detail and, in the last case, phone numbers (hard rule 6).
    log.info(
        "intake_recorded",
        extra={
            "agent_id": str(agent_id),
            "prompt_version": version,
            "facts": len(block.splitlines()) - 1,
            "staged_behind_script": not applies_now,
        },
    )
    return {
        "agent_id": agent_id,
        "prompt_version": version,
        "regenerated": True,
        "kb_source_id": kb_source_id,
        "staged_behind_script": not applies_now,
    }


def _sheet_answers(sheet: dict[str, Any] | None, *, agent_id: UUID) -> IntakeFacts | None:
    """The stored sheet as the model that wrote it, or None if there is nothing usable.

    Defensive on purpose. The sheet is written only by this module, but it outlives the
    code that wrote it: an org that last saved under an older `SHEET_VERSION`, or a row
    hand-patched during an incident, must degrade to "prefill from the derived columns"
    rather than 500 a wizard that is only trying to reopen a step.
    """
    if not sheet or sheet.get("version") != SHEET_VERSION:
        return None
    try:
        return IntakeFacts.model_validate(sheet.get("answers") or {})
    except ValidationError:
        # ids only — the payload that failed is the client's answers (hard rule 6).
        log.warning("intake_sheet_unreadable", extra={"agent_id": str(agent_id)})
        return None


async def read_intake(session: AsyncSession, *, agent_id: UUID) -> dict[str, Any]:
    """Everything reopening the step needs, from the sheet that stores it.

    The answer sheet on `organizations.intake` is the source of truth when it exists:
    it is what the operator typed, including a draft that was never submitted and so
    never reached `agents` at all. The derived columns are the fallback for an org that
    last submitted before migration c1f3a7d92b46 — for those, hours, escalation
    contacts and languages still round-trip, and the prose comes back only as the
    compiled block, which is the honest answer for a row saved before there was
    anywhere to save it.

    The shape, and why each key comes from where it does:

    - `business_hours`, `escalation_contacts`, `languages` — the same shapes the agent
      columns hold (`languages` is the EXTRA languages, DATA-MODEL §3, so the agent's
      primary is not repeated), rendered from the sheet when there is one.
    - `prose_answers` — branches, services, FAQs, staff, booking rules: the fields, not
      the sentence compiled out of them. `None` for a pre-migration org.
    - `compiled_t0_context` — the block currently in the agent's prompt, for display:
      it is what the agent actually says today, which is not always what the sheet says
      if a submit has not happened since the last draft.
    - `submitted_at` — whether this sheet has ever been compiled into the agent, so the
      wizard can tell "saved" from "live" instead of guessing.
    - `saved_at` — when the sheet was last written by either path. With `submitted_at`
      it is the whole of "is there a draft newer than the last submit", which is the
      question a resume asks and the reason a draft route exists.
    - `language_primary` — the agent's own primary language. `languages` above is the
      EXTRAS by construction, so a caller that does not already hold the primary cannot
      render the language set at all: it would show "Hindi" for an agent that answers in
      Telugu and Hindi. The wizard got away without it only because it had just chosen
      the value one step earlier; a resume from a list has chosen nothing, so the
      omission stopped being survivable the moment resuming existed.
    - `sheet_agent_id` — which agent the stored answers were last written THROUGH
      (`_store_sheet` stamps it on every save). Provenance, not ownership: the sheet
      belongs to the ORG, one per business, while the compile targets one agent. So a
      second agent reading this endpoint is told, honestly, that the answers it is
      being prefilled with were entered against a different agent — a fact only this
      key carries, and one a caller cannot derive from the path it used. `None` for a
      pre-migration org, where there is no sheet to have stamped anything.
    """
    row = (
        await session.execute(
            text(
                "SELECT a.business_hours, a.escalation_config, a.languages_extra, "
                "  pv.compiled_t0_context, o.intake, a.language_primary "
                "FROM agents a JOIN organizations o ON o.id = a.tenant_id "
                "LEFT JOIN prompt_versions pv ON pv.id = a.system_prompt_id "
                "WHERE a.id = :aid AND a.deleted_at IS NULL"
            ),
            {"aid": agent_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    sheet: dict[str, Any] | None = row[4]
    primary = str(row[5])
    facts = _sheet_answers(sheet, agent_id=agent_id)
    if facts is None:
        escalation = row[1] or {}
        return {
            "business_hours": row[0] or {},
            "escalation_contacts": escalation.get("contacts", []),
            "languages": list(row[2] or []),
            "prose_answers": None,
            "compiled_t0_context": row[3],
            # An unreadable or absent sheet has no timestamps to report. Both stay None
            # rather than being guessed from `agents.updated_at`: "when were these
            # answers last saved" and "when was this row last touched" are different
            # questions, and the second one is answered by every unrelated publish.
            "submitted_at": None,
            "saved_at": None,
            "language_primary": primary,
            "sheet_agent_id": None,
        }
    return {
        "business_hours": _hours_map(facts),
        "escalation_contacts": [c.model_dump() for c in facts.escalation_contacts],
        "languages": [lang for lang in facts.languages if lang and lang != primary],
        "prose_answers": IntakeProse.from_facts(facts).model_dump(),
        "compiled_t0_context": row[3],
        "submitted_at": (sheet or {}).get("submitted_at"),
        "saved_at": (sheet or {}).get("saved_at"),
        "language_primary": primary,
        "sheet_agent_id": (sheet or {}).get("agent_id"),
    }


# --------------------------------------------------- resuming an unfinished onboarding


@dataclass(frozen=True, slots=True)
class UnfinishedOnboarding:
    """One account whose FLOWS §1 wizard was started and never finished."""

    tenant_id: UUID
    name: str
    slug: str
    # The agent the wizard resumes AT — the sheet's own `agent_id` when that agent is
    # still there, otherwise the account's oldest live agent (the draft receptionist
    # `create_organization` makes). Without it a "resume" link would have to guess, and
    # a guess here writes a client's answers onto the wrong agent's prompt.
    agent_id: UUID
    created_at: datetime
    # When the sheet was last written, or None for an account whose intake step was
    # never opened at all. The two are DIFFERENT states — "started and abandoned" and
    # "created and forgotten" — and they need different actions from the operator, so
    # the row says which rather than reporting a zero.
    draft_saved_at: datetime | None
    # `submission_blockers`' own codes, computed from what IS stored. This is the whole
    # point of the list: "unfinished" is a claim, and the codes are the evidence.
    blockers: tuple[str, ...]


# Candidates, cheaply. The predicate is `submitted_at IS NULL` on the sheet — the ONE
# stamp `_store_sheet` writes only on the submit path, so it means "step 3 has never
# been completed" and nothing else. `status = 'onboarding'` is the second half: a
# suspended or churned account is not an onboarding somebody is half-way through.
#
# Only the two envelope stamps are read here, never `answers`. This session is the
# cross-tenant one (b57e2f9c4a13 widens `organizations` for `app.admin`), and the
# answers include the client's escalation phone numbers; they are read one tenant at a
# time under that tenant's own RLS below, the way `admin/holds.py` argues for.
_UNFINISHED_DIRECTORY = (
    "SELECT id, name, slug, created_at, intake->>'saved_at' "
    "FROM organizations "
    "WHERE deleted_at IS NULL AND status = 'onboarding' "
    "  AND intake->>'submitted_at' IS NULL "
    "ORDER BY created_at DESC"
)

# Inside the tenant: its own sheet, its live agents oldest-first, and whether any of
# them already carries a compiled block.
_TENANT_INTAKE_STATE = (
    "SELECT o.intake, a.id, pv.compiled_t0_context IS NOT NULL "
    "FROM organizations o "
    "JOIN agents a ON a.tenant_id = o.id AND a.deleted_at IS NULL "
    "LEFT JOIN prompt_versions pv ON pv.id = a.system_prompt_id "
    "WHERE o.id = :tid ORDER BY a.created_at"
)


def _parse_stamp(value: Any) -> datetime | None:
    """A `to_jsonb(now())` timestamp back as an instant, or None if it is not one.

    `datetime.fromisoformat` accepts Postgres's rendering (`2026-08-13T12:00:00+05:30`)
    on 3.12. It is parsed in PYTHON rather than cast in SQL on purpose: a
    `(intake->>'saved_at')::timestamptz` in the ORDER BY turns one hand-patched row into
    a 500 for the whole list, and this list is read precisely when something has gone
    sideways.
    """
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


async def unfinished_onboardings(directory: AsyncSession) -> list[UnfinishedOnboarding]:
    """Every account whose onboarding is half-done, most recently worked on first.

    `directory` must be an `admin_session()` — the only session that can enumerate
    tenants. Each candidate is then ENTERED with its own GUC, so the answers, the agents
    and the prompt are all read under ordinary RLS; nothing is widened, and this
    function holds no cross-tenant view of any table but `organizations`.

    Ordered by "when did somebody last touch this", falling back to when the account was
    created. That is the order an operator resumes in — the client they were talking to
    an hour ago, not the one that has been sitting unfinished since March — and it is the
    opposite of `admin/holds.py`'s oldest-first, which is a TRIAGE queue for work nobody
    has started.

    Two exclusions that are not `submitted_at`, both of which would otherwise put a
    finished client on a list titled unfinished:

    - an account with no live agent at all is skipped: the wizard has nowhere to resume
      TO, and a row whose link cannot work is worse than an absent one;
    - an account whose agent already carries a compiled `[T0 FACTS]` block has had its
      intake submitted — before migration c1f3a7d92b46 there was no sheet to stamp, so
      for those orgs the compiled block IS the record of the submit.

    N+1 by construction, the same trade `tenant_overview` and `held_tenants` document
    and bounded far more tightly than either: the candidate set is accounts that are
    still in onboarding AND have never submitted step 3.
    """
    rows = (await directory.execute(text(_UNFINISHED_DIRECTORY))).all()

    unfinished: list[UnfinishedOnboarding] = []
    for org in rows:
        tenant_id = UUID(str(org[0]))
        async with tenant_session(tenant_id) as scoped:
            agents = (await scoped.execute(text(_TENANT_INTAKE_STATE), {"tid": tenant_id})).all()
        if not agents or any(bool(agent[2]) for agent in agents):
            continue
        sheet: dict[str, Any] | None = agents[0][0]
        agent_ids = [UUID(str(agent[1])) for agent in agents]
        stamped = _parse_uuid((sheet or {}).get("agent_id"))
        agent_id = stamped if stamped in agent_ids else agent_ids[0]
        # `_sheet_answers` is the same defensive reader the GET uses, so a sheet this
        # build cannot parse degrades to "nothing answered" here exactly as it degrades
        # to "prefill from the derived columns" there — and never to a 500.
        facts = _sheet_answers(sheet, agent_id=agent_id) or IntakeFacts()
        unfinished.append(
            UnfinishedOnboarding(
                tenant_id=tenant_id,
                name=str(org[1]),
                slug=str(org[2]),
                agent_id=agent_id,
                created_at=org[3],
                draft_saved_at=_parse_stamp(org[4]),
                blockers=tuple(submission_blockers(facts)),
            )
        )
    unfinished.sort(key=lambda row: row.draft_saved_at or row.created_at, reverse=True)
    return unfinished


def _parse_uuid(value: Any) -> UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


__all__ = [
    "DAYS",
    "SHEET_VERSION",
    "Branch",
    "DayHours",
    "EscalationContact",
    "Faq",
    "IntakeFacts",
    "IntakeProse",
    "ServiceItem",
    "StaffMember",
    "UnfinishedOnboarding",
    "compile_t0_facts",
    "kb_seed_text",
    "read_intake",
    "record_intake",
    "save_intake_draft",
    "submission_blockers",
    "unfinished_onboardings",
]
