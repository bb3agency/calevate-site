"""Writing the business profile, and carrying every change to the client's agents (D-695).

A save replaces the sections it names, marks those setup steps done, and then brings
every agent of the client up to date IN THE SAME TRANSACTION, through the same fan-out a
knowledge publish uses (`kb/service._refresh_agents`' shape):

* the tenant's knowledge lock is taken FIRST, before any agent row (the D-689 deadlock
  fix: a knowledge publish holds this lock while it writes every agent row);
* each agent's [T0 FACTS] block is recompiled from the profile (`agents/t0.recompile_t0`),
  which mints a prompt version only when the block changed and re-publishes a live agent
  only when no hand-written script edit is staged;
* hours, contacts and languages are agent CONFIGURATION too (the handover rota, the
  after-hours flag, the languages the agent answers in), so a live agent whose block did
  not change is re-published when one of them did;
* a live agent whose block changed behind a staged script edit still gets its new facts
  on an engine that keeps facts in its knowledge base (`agents/engine_facts`), because
  there the facts are not part of the script.

The client never republishes anything by hand. An engine refusal fails the save whole,
exactly as a refused knowledge publish does, so our tables never claim facts the voice
platform does not hold.
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Final, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.languages import OfferedLanguage
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.tenancy.business_profile import (
    DAYS,
    MAX_BRANCHES,
    MAX_CONTACTS,
    MAX_FAQS,
    MAX_LANGUAGES,
    MAX_SERVICES,
    MAX_STAFF,
    Branch,
    BusinessContactIn,
    DayHours,
    Faq,
    Profile,
    ServiceItem,
    StaffMember,
    StepId,
    load_profile,
)

log = get_logger(__name__)

#: Sections whose answers are compiled into [T0 FACTS].
FACT_STEPS: Final = frozenset({"hours", "branches", "services", "faqs", "staff", "booking"})
#: Sections that are also agent configuration, so a live agent is re-published for them.
CONFIG_STEPS: Final = frozenset({"hours", "contacts", "languages"})


def _whole_week(rows: list[DayHours]) -> list[DayHours]:
    seen: set[str] = set()
    for row in rows:
        if row.day in seen:
            raise ValueError(f"{row.day} appears twice.")
        seen.add(row.day)
        if not row.closed and not (row.opens and row.closes):
            raise ValueError(f"Give {row.day} an opening and a closing time, or mark it closed.")
    return rows


class ProfilePatch(BaseModel):
    """The sections to replace. A section left out is untouched; a section sent is
    replaced whole (a deep merge would bring back a service the client deleted)."""

    model_config = ConfigDict(extra="forbid")

    hours: Annotated[list[DayHours], AfterValidator(_whole_week)] | None = Field(
        default=None, max_length=7
    )
    branches: list[Branch] | None = Field(default=None, max_length=MAX_BRANCHES)
    services: list[ServiceItem] | None = Field(default=None, max_length=MAX_SERVICES)
    faqs: list[Faq] | None = Field(default=None, max_length=MAX_FAQS)
    staff: list[StaffMember] | None = Field(default=None, max_length=MAX_STAFF)
    booking_rules: str | None = Field(default=None, max_length=2000)
    contacts: list[BusinessContactIn] | None = Field(default=None, max_length=MAX_CONTACTS)
    languages: list[OfferedLanguage] | None = Field(default=None, max_length=MAX_LANGUAGES)

    def sections(self) -> set[str]:
        """The setup steps this patch answers."""
        sent = self.model_fields_set
        names = {
            "hours": "hours",
            "branches": "branches",
            "services": "services",
            "faqs": "faqs",
            "staff": "staff",
            "booking_rules": "booking",
            "contacts": "contacts",
            "languages": "languages",
        }
        return {step for key, step in names.items() if key in sent}


_ENSURE_ROW: Final = (
    "INSERT INTO business_profiles (id, tenant_id) VALUES (:id, :tid) "
    "ON CONFLICT (tenant_id) DO NOTHING"
)


async def ensure_profile_row(session: AsyncSession, *, tenant_id: UUID) -> None:
    """Create the client's profile row on first write. Reads treat an absent row as an
    empty profile, so nothing creates one before the client answers something."""
    await session.execute(text(_ENSURE_ROW), {"id": uuid7(), "tid": tenant_id})


def hours_map(rows: list[DayHours]) -> dict[str, dict[str, str] | None]:
    by_day = {row.day: row for row in rows}
    out: dict[str, dict[str, str] | None] = {}
    for day in DAYS:
        row = by_day.get(day)
        if row is None:
            continue
        out[day] = None if row.closed else {"opens": str(row.opens), "closes": str(row.closes)}
    return out


def _dump(items: list[Any]) -> str:
    return json.dumps([item.model_dump(mode="json") for item in items])


#: One statement per column, spelled out: the column is never taken from a request.
_SET_SQL: Final[dict[str, str]] = {
    "hours": "UPDATE business_profiles SET hours = CAST(:v AS jsonb) WHERE tenant_id = :tid",
    "branches": "UPDATE business_profiles SET branches = CAST(:v AS jsonb) WHERE tenant_id = :tid",
    "services": "UPDATE business_profiles SET services = CAST(:v AS jsonb) WHERE tenant_id = :tid",
    "faqs": "UPDATE business_profiles SET faqs = CAST(:v AS jsonb) WHERE tenant_id = :tid",
    "staff": "UPDATE business_profiles SET staff = CAST(:v AS jsonb) WHERE tenant_id = :tid",
    "booking_rules": "UPDATE business_profiles SET booking_rules = :v WHERE tenant_id = :tid",
    "languages": "UPDATE business_profiles SET languages = :v WHERE tenant_id = :tid",
}


async def _set(session: AsyncSession, tenant_id: UUID, column: str, value: Any) -> None:
    await session.execute(text(_SET_SQL[column]), {"v": value, "tid": tenant_id})


async def save_contacts(
    session: AsyncSession, *, tenant_id: UUID, contacts: list[BusinessContactIn]
) -> None:
    """Replace the client's escalation roster, keeping the identity of every contact sent
    back with its `id`, so each agent's handover list keeps pointing at the same people.

    A contact left out is deleted, and with it its place on every agent's list
    (`agent_handoff_members.contact_id` cascades). The agents' copies of each contact's
    name and number are refreshed in the same transaction: the dialling path reads them.
    """
    numbers = [c.phone_e164 for c in contacts]
    if len(set(numbers)) != len(numbers):
        raise ProblemError.business_rule(
            "contact_duplicate_number",
            "The same phone number is listed twice.",
            remediation="Give each person their own number.",
        )
    by_phone = {
        str(row[1]): UUID(str(row[0]))
        for row in (
            await session.execute(
                text("SELECT id, phone_e164 FROM business_contacts WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            )
        ).all()
    }
    existing = set(by_phone.values())
    explicit = {c.id for c in contacts if c.id is not None}
    if explicit - existing:
        raise ProblemError.not_found("Contact")
    # A contact sent without an id but with a number already on file IS that contact:
    # matching it keeps its place on every agent's list instead of silently dropping it.
    contacts = [
        c.model_copy(update={"id": by_phone[c.phone_e164]})
        if c.id is None and by_phone.get(c.phone_e164) not in (None, *explicit)
        else c
        for c in contacts
    ]
    kept = {c.id for c in contacts if c.id is not None}
    removed = existing - kept
    if removed:
        await session.execute(
            text("DELETE FROM business_contacts WHERE tenant_id = :tid AND id = ANY(:ids)"),
            {"tid": tenant_id, "ids": list(removed)},
        )
    for position, contact in enumerate(contacts):
        params = {
            "tid": tenant_id,
            "pos": position,
            "label": contact.label.strip(),
            "phone": contact.phone_e164,
            "note": (contact.note or "").strip() or None,
        }
        if contact.id is None:
            await session.execute(
                text(
                    "INSERT INTO business_contacts "
                    "(id, tenant_id, position, label, phone_e164, note) "
                    "VALUES (:id, :tid, :pos, :label, :phone, :note)"
                ),
                {**params, "id": uuid7()},
            )
        else:
            await session.execute(
                text(
                    "UPDATE business_contacts SET position = :pos, label = :label, "
                    "phone_e164 = :phone, note = :note, updated_at = now() "
                    "WHERE tenant_id = :tid AND id = :id"
                ),
                {**params, "id": contact.id},
            )
    await session.execute(
        text(
            "UPDATE agent_handoff_members m SET label = c.label, phone_e164 = c.phone_e164, "
            "updated_at = now() FROM business_contacts c "
            "WHERE c.id = m.contact_id AND m.tenant_id = :tid "
            "AND (m.label <> c.label OR m.phone_e164 <> c.phone_e164)"
        ),
        {"tid": tenant_id},
    )


def _fingerprint(profile: Profile) -> dict[str, Any]:
    """Each setup step's stored value, comparable before and after a save."""
    return {
        "hours": profile.hours,
        "branches": [b.model_dump() for b in profile.branches],
        "services": [s.model_dump() for s in profile.services],
        "faqs": [f.model_dump() for f in profile.faqs],
        "staff": [s.model_dump() for s in profile.staff],
        "booking": profile.booking_rules,
        "contacts": [(c.id, c.label, c.phone_e164, c.note) for c in profile.contacts],
        "languages": profile.languages,
    }


async def save_profile(
    session: AsyncSession, *, tenant_id: UUID, patch: ProfilePatch, user_id: UUID | None
) -> tuple[set[str], int]:
    """Replace the sections in `patch` and bring every agent up to date.

    Returns (the steps answered, the number of agents that were updated).
    """
    from apps.api.kb.service import lock_tenant_knowledge

    await lock_tenant_knowledge(session, tenant_id=tenant_id)
    await ensure_profile_row(session, tenant_id=tenant_id)
    before = _fingerprint(await load_profile(session, tenant_id=tenant_id))
    sent = patch.model_fields_set
    if "hours" in sent:
        await _set(session, tenant_id, "hours", json.dumps(hours_map(patch.hours or [])))
    if "branches" in sent:
        await _set(session, tenant_id, "branches", _dump(patch.branches or []))
    if "services" in sent:
        await _set(session, tenant_id, "services", _dump(patch.services or []))
    if "faqs" in sent:
        await _set(session, tenant_id, "faqs", _dump(patch.faqs or []))
    if "staff" in sent:
        await _set(session, tenant_id, "staff", _dump(patch.staff or []))
    if "booking_rules" in sent:
        rules = (patch.booking_rules or "").strip() or None
        await _set(session, tenant_id, "booking_rules", rules)
    if "languages" in sent:
        languages: list[str] = []
        for tag in patch.languages or []:
            if tag not in languages:
                languages.append(tag)
        await _set(session, tenant_id, "languages", languages)
    if "contacts" in sent:
        await save_contacts(session, tenant_id=tenant_id, contacts=patch.contacts or [])
    steps = patch.sections()
    await session.execute(
        text(
            "UPDATE business_profiles SET setup_steps = setup_steps || CAST(:steps AS jsonb), "
            "setup_started_at = coalesce(setup_started_at, now()), "
            "updated_by = :uid, updated_at = now() WHERE tenant_id = :tid"
        ),
        {"steps": json.dumps(dict.fromkeys(steps, "done")), "uid": user_id, "tid": tenant_id},
    )
    after = _fingerprint(await load_profile(session, tenant_id=tenant_id))
    # Only what actually changed reaches the agents: re-saving a step unchanged mints no
    # prompt version and re-publishes nothing.
    changed = {step for step in after if after[step] != before[step]}
    updated = await apply_to_agents(session, tenant_id=tenant_id, changed=changed)
    # Section names and a count only: the answers are the client's business detail and
    # the contacts are phone numbers (hard rule 6).
    log.info(
        "business_profile_saved",
        extra={"tenant_id": str(tenant_id), "sections": sorted(steps), "agents": updated},
    )
    return steps, updated


SetupAction = Literal["start", "skip", "dismiss", "reopen"]


_SETUP_SQL: Final[dict[str, str]] = {
    "start": (
        "UPDATE business_profiles SET setup_started_at = coalesce(setup_started_at, now()), "
        "updated_at = now() WHERE tenant_id = :tid"
    ),
    "dismiss": (
        "UPDATE business_profiles SET setup_dismissed_at = coalesce(setup_dismissed_at, now()), "
        "updated_at = now() WHERE tenant_id = :tid"
    ),
    "reopen": (
        "UPDATE business_profiles SET setup_dismissed_at = NULL, updated_at = now() "
        "WHERE tenant_id = :tid"
    ),
    # A step already answered stays answered: skipping it later changes nothing.
    "skip": (
        "UPDATE business_profiles SET setup_steps = CASE WHEN setup_steps ? :step "
        "THEN setup_steps ELSE setup_steps || jsonb_build_object(CAST(:step AS text), "
        "'skipped') END, setup_started_at = coalesce(setup_started_at, now()), "
        "updated_at = now() WHERE tenant_id = :tid"
    ),
}


async def record_setup(
    session: AsyncSession, *, tenant_id: UUID, action: SetupAction, step: StepId | None
) -> None:
    """Move the setup wizard's server-side progress. `skip` needs a step."""
    if action == "skip" and step is None:
        raise ProblemError.business_rule(
            "setup_step_required",
            "Pick the step you want to skip.",
            remediation="Choose a step, then press Skip again.",
        )
    await ensure_profile_row(session, tenant_id=tenant_id)
    params: dict[str, Any] = {"tid": tenant_id}
    if action == "skip":
        params["step"] = step
    await session.execute(text(_SETUP_SQL[action]), params)


# ------------------------------------------------------------------ the fan-out


_AGENT_STATE: Final = (
    "SELECT a.status, a.engine_agent_ref, a.system_prompt_id IS NOT NULL, "
    "(a.system_prompt_id IS DISTINCT FROM a.live_prompt_id), pv.compiled_t0_context "
    "FROM agents a LEFT JOIN prompt_versions pv ON pv.id = a.system_prompt_id "
    "WHERE a.id = :aid AND a.deleted_at IS NULL"
)


async def apply_to_agents(session: AsyncSession, *, tenant_id: UUID, changed: set[str]) -> int:
    """Bring every agent of the client up to the profile. Returns how many were touched.

    The caller holds the tenant's knowledge lock (`save_profile` takes it first).
    """
    if not changed:
        return 0
    from apps.api.agents.engine_facts import sync_business_facts
    from apps.api.agents.service import publish_agent
    from apps.api.agents.t0 import recompile_t0
    from apps.api.engine import get_engine
    from apps.api.engine.hosted_platform import hosted_agent_limits
    from apps.api.kb.service import active_knowledge, knowledge_agents
    from apps.api.tenancy.business_profile import profile_fact_lines

    facts_changed = bool(changed & FACT_STEPS)
    config_changed = bool(changed & CONFIG_STEPS)
    knowledge = await active_knowledge(session, tenant_id=tenant_id)
    has_facts = bool(await profile_fact_lines(session, tenant_id=tenant_id)) or bool(knowledge)
    engine = get_engine()
    touched = 0
    for agent_id in await knowledge_agents(session, tenant_id=tenant_id):
        row = (await session.execute(text(_AGENT_STATE), {"aid": agent_id})).first()
        if row is None:
            continue
        status, ref, has_script, staged = str(row[0]), row[1], bool(row[2]), bool(row[3])
        live = status == "live" and bool(ref)
        version: int | None = None
        # A scriptless agent gets its first prompt from the profile, as the old admin intake
        # did for the draft receptionist; an empty profile mints nothing.
        if facts_changed and (has_script or has_facts):
            version = await recompile_t0(
                session, tenant_id=tenant_id, agent_id=agent_id, knowledge=knowledge
            )
        if version is not None:
            touched += 1
        if not live or (version is not None and not staged):
            continue  # not on the phone, or `recompile_t0` already re-published it
        if config_changed:
            await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
            if version is None:
                touched += 1
        elif version is not None and hosted_agent_limits(engine).facts_in_knowledge:
            block = (await session.execute(text(_AGENT_STATE), {"aid": agent_id})).first()
            await sync_business_facts(
                session, engine, agent_id=agent_id, ref=str(ref), facts=block[4] if block else None
            )
    return touched


__all__ = [
    "CONFIG_STEPS",
    "FACT_STEPS",
    "ProfilePatch",
    "SetupAction",
    "apply_to_agents",
    "ensure_profile_row",
    "hours_map",
    "record_setup",
    "save_contacts",
    "save_profile",
]
