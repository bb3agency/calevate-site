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

`read_intake` returns what a resume needs: the sheet's own fields plus the structured
columns, with the compiled block for display.
"""

from __future__ import annotations

import json
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import t0
from apps.api.agents.service import publish_agent
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of
from apps.api.kb import service as kb_service

log = get_logger(__name__)

# The section marker PROMPT-GUIDE §2 uses. Sections start at column 0 with `[NAME]`,
# which is what makes a block replaceable without a parser.
T0_HEADER = "[T0 FACTS]"
# Where a freshly compiled block is inserted when the prompt has no block yet: before
# the task flow, i.e. the position PROMPT-GUIDE §2's template order puts it in.
_INSERT_BEFORE = ("[TASK FLOW]", "[TOOLS]", "[GUARDRAILS]", "[WRAP]")
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
    lines: list[str] = [T0_HEADER]
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


def splice_t0_block(body: str | None, block: str, *, identity: str) -> str:
    """Put `block` where the prompt's [T0 FACTS] section is, or where it should be.

    Replacing rather than appending is the whole rule: PROMPT-GUIDE §2 says the block is
    auto-generated and regenerated, so a second copy of stale hours sitting above the
    fresh ones is not a merge, it is an agent that quotes two opening times. Everything
    outside the block — guardrails an operator wrote by hand, the task flow, the wrap —
    is not this compiler's to touch.
    """
    if not body or not body.strip():
        # Nothing to splice into: the agent has no prompt yet, which is the ordinary
        # state of a wizard that has not reached step 4. The identity line is derived
        # from rows we already hold (business name, agent role) — the drafted prompt
        # itself, with its style, task flow and guardrails, is step 4's work.
        return f"[IDENTITY] {identity}\n{block}\n"

    lines = body.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith(T0_HEADER)), None)
    if start is None:
        anchor = next(
            (
                i
                for i, line in enumerate(lines)
                if any(line.startswith(marker) for marker in _INSERT_BEFORE)
            ),
            len(lines),
        )
        return "\n".join([*lines[:anchor], block, *lines[anchor:]]).rstrip() + "\n"

    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("[")),
        len(lines),
    )
    return "\n".join([*lines[:start], block, *lines[end:]]).rstrip() + "\n"


def kb_seed_text(facts: IntakeFacts) -> str:
    """The same facts as a KB source body — paragraph-separated, because `chunk_text`
    splits on paragraphs and a chunk is what gets read aloud."""
    block = compile_t0_facts(facts)
    return "\n\n".join(line for line in block.splitlines() if line != T0_HEADER)


# ------------------------------------------------------------------- the step


class _AgentState(BaseModel):
    """The four facts this module needs about the agent it is writing to."""

    status: str
    engine_agent_ref: str | None
    language_primary: str
    active_version: int | None


async def _agent_state(session: AsyncSession, agent_id: UUID) -> _AgentState:
    """Load it, and prove it exists.

    Under a tenant-scoped session RLS is what makes another tenant's agent invisible, so
    this doubles as the isolation: a wrong-tenant id is a clean 404, not a write that
    silently lands nowhere.
    """
    row = (
        await session.execute(
            text(
                "SELECT a.status, a.engine_agent_ref, a.language_primary, pv.version "
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


async def _write_prompt_version(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    body: str,
    compiled: str,
    created_by: UUID | None,
) -> int:
    """A NEW version carrying the block AND its build artifact, then the pointer.

    The insert sets `compiled_t0_context` at creation rather than updating a row later,
    because `prompt_versions` is immutable history (agents/prompts.py) — an artifact
    stamped onto an existing version would rewrite what an earlier publish said.
    """
    current = (
        await session.execute(
            text("SELECT COALESCE(max(version), 0) FROM prompt_versions WHERE agent_id = :aid"),
            {"aid": agent_id},
        )
    ).scalar()
    version = int(current or 0) + 1
    version_id = uuid7()
    try:
        await session.execute(
            text(
                "INSERT INTO prompt_versions (id, tenant_id, agent_id, version, body, "
                "compiled_t0_context, notes, created_by, published_at, created_at, updated_at) "
                "VALUES (:id, :tid, :aid, :version, :body, :compiled, :notes, :by, now(), "
                "now(), now())"
            ),
            {
                "id": version_id,
                "tid": tenant_id,
                "aid": agent_id,
                "version": version,
                "body": body,
                "compiled": compiled,
                "notes": "regenerated from intake (FLOWS §1 step 3)",
                "by": created_by,
            },
        )
    except IntegrityError as exc:
        # UNIQUE(agent_id, version): two operators saved the step at once and this one
        # lost. A lost race is a conflict, not a silent retry (BACKEND-PATTERNS §5).
        raise ProblemError.conflict(
            "prompt_version_conflict",
            "Another prompt version was written for this agent at the same time.",
            remediation="Reload the wizard and save the intake again.",
        ) from exc
    result = await session.execute(
        text(
            "UPDATE agents SET system_prompt_id = :vid, updated_at = now() "
            "WHERE id = :aid AND deleted_at IS NULL"
        ),
        {"vid": version_id, "aid": agent_id},
    )
    if rowcount_of(result) == 0:
        raise ProblemError.not_found("Agent")
    return version


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
        }

    version = await _write_prompt_version(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        body=splice_t0_block(body, block, identity=f"{business_name} receptionist."),
        compiled=block,
        created_by=recorded_by,
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

    if agent.status == "live" and agent.engine_agent_ref:
        await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)

    # ids and counts only: services, FAQs and escalation numbers are client business
    # detail and, in the last case, phone numbers (hard rule 6).
    log.info(
        "intake_recorded",
        extra={
            "agent_id": str(agent_id),
            "prompt_version": version,
            "facts": len(block.splitlines()) - 1,
        },
    )
    return {
        "agent_id": agent_id,
        "prompt_version": version,
        "regenerated": True,
        "kb_source_id": kb_source_id,
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
    facts = _sheet_answers(sheet, agent_id=agent_id)
    if facts is None:
        escalation = row[1] or {}
        return {
            "business_hours": row[0] or {},
            "escalation_contacts": escalation.get("contacts", []),
            "languages": list(row[2] or []),
            "prose_answers": None,
            "compiled_t0_context": row[3],
            "submitted_at": None,
        }
    primary = str(row[5])
    return {
        "business_hours": _hours_map(facts),
        "escalation_contacts": [c.model_dump() for c in facts.escalation_contacts],
        "languages": [lang for lang in facts.languages if lang and lang != primary],
        "prose_answers": IntakeProse.from_facts(facts).model_dump(),
        "compiled_t0_context": row[3],
        "submitted_at": (sheet or {}).get("submitted_at"),
    }


__all__ = [
    "DAYS",
    "SHEET_VERSION",
    "T0_HEADER",
    "Branch",
    "DayHours",
    "EscalationContact",
    "Faq",
    "IntakeFacts",
    "IntakeProse",
    "ServiceItem",
    "StaffMember",
    "compile_t0_facts",
    "kb_seed_text",
    "read_intake",
    "record_intake",
    "save_intake_draft",
    "splice_t0_block",
    "submission_blockers",
]
