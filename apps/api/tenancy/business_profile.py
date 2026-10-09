"""The business profile: what a client's agents know about the business (D-695).

One profile per client, read by every agent. This module is the READ side and the pure
rules — the shapes, the [T0 FACTS] lines compiled from a profile, and what is still
missing before an agent may go live. It imports nothing from `agents/` or `kb/`, so both
can import it; the write path and the fan-out to agents live in `profile_service.py`.

Hours are a map from weekday to `{"opens", "closes"}` or null. Null is CLOSED; an absent
day is NOT ANSWERED YET. The agent says "we are closed on Sunday" for the first and says
nothing about Sunday for the second.

Escalation contacts are rows (`business_contacts`), never prompt text: a mobile number in
a prompt is a number the agent can read out to whoever asks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any, Final, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.handoff import india_handoff_number
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.tenancy.models import PROFILE_STEPS

log = get_logger(__name__)

DAYS: Final = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_HHMM = r"^(?:[01]\d|2[0-3]):[0-5]\d$"

StepId = Literal[
    "hours", "branches", "services", "faqs", "staff", "booking", "contacts", "languages"
]
StepState = Literal["done", "skipped"]

#: Caps on each list. They bound the prompt, the screen and the request.
MAX_BRANCHES: Final = 20
MAX_SERVICES: Final = 100
MAX_FAQS: Final = 50
MAX_STAFF: Final = 50
MAX_CONTACTS: Final = 10
MAX_LANGUAGES: Final = 6


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DayHours(_Strict):
    """One day of the week. `closed` is explicit: "closed on Sunday" and "Sunday not
    answered yet" are different answers, and a day that is not closed needs both times."""

    day: Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    opens: str | None = Field(default=None, pattern=_HHMM)
    closes: str | None = Field(default=None, pattern=_HHMM)
    closed: bool = False


class Branch(_Strict):
    label: str = Field(min_length=1, max_length=80)
    address: str = Field(min_length=1, max_length=400)


class ServiceItem(_Strict):
    """`price_inr` is a digit STRING (hard rule 7): the price read aloud must be exactly
    what the client typed, which a float cannot promise. Optional, because "ask at
    reception" is a real answer."""

    name: str = Field(min_length=1, max_length=120)
    price_inr: str | None = Field(default=None, max_length=20, pattern=r"^\d+(\.\d{1,2})?$")
    notes: str | None = Field(default=None, max_length=200)


class Faq(_Strict):
    question: str = Field(min_length=1, max_length=300)
    answer: str = Field(min_length=1, max_length=1000)


class StaffMember(_Strict):
    """`pronunciation` is how the agent should SAY the name (PROMPT-GUIDE §3): a
    mispronounced doctor's name is the first thing a caller notices."""

    name: str = Field(min_length=1, max_length=120)
    pronunciation: str | None = Field(default=None, max_length=120)
    role: str | None = Field(default=None, max_length=80)


class BusinessContactIn(_Strict):
    """One escalation contact as the client writes it. `id` keeps an existing contact
    (and its place in every agent's handover list); omit it to add a new one."""

    id: UUID | None = None
    label: str = Field(min_length=1, max_length=120)
    phone_e164: Annotated[
        str, Field(pattern=r"^\+[1-9]\d{7,18}$"), AfterValidator(india_handoff_number)
    ]
    note: str | None = Field(default=None, max_length=200)


class BusinessContactOut(_Strict):
    id: UUID
    label: str
    phone_e164: str
    note: str | None


@dataclass(frozen=True, slots=True)
class Contact:
    id: UUID
    position: int
    label: str
    phone_e164: str
    note: str | None


@dataclass(frozen=True, slots=True)
class Profile:
    """The stored profile, parsed. An absent row is an empty profile, never an error."""

    tenant_id: UUID
    hours: dict[str, dict[str, str] | None] = field(default_factory=dict)
    branches: list[Branch] = field(default_factory=list)
    services: list[ServiceItem] = field(default_factory=list)
    faqs: list[Faq] = field(default_factory=list)
    staff: list[StaffMember] = field(default_factory=list)
    booking_rules: str | None = None
    languages: list[str] = field(default_factory=list)
    contacts: list[Contact] = field(default_factory=list)
    setup_steps: dict[str, str] = field(default_factory=dict)
    setup_started_at: datetime | None = None
    setup_dismissed_at: datetime | None = None
    merge_notes: list[Any] = field(default_factory=list)
    updated_at: datetime | None = None
    exists: bool = False


# ------------------------------------------------------------------------- reading


_PROFILE_SQL: Final = (
    "SELECT hours, branches, services, faqs, staff, booking_rules, languages, setup_steps, "
    "setup_started_at, setup_dismissed_at, merge_notes, updated_at "
    "FROM business_profiles WHERE tenant_id = :tid"
)
_CONTACTS_SQL: Final = (
    "SELECT id, position, label, phone_e164, note FROM business_contacts "
    "WHERE tenant_id = :tid ORDER BY position, id"
)


def _parsed(model: type[BaseModel], rows: Any, *, tenant_id: UUID, name: str) -> list[Any]:
    """Each stored item through its model; an item that no longer parses is skipped and
    logged (by id and field name only) rather than failing the whole read."""
    out: list[Any] = []
    for row in rows if isinstance(rows, list) else []:
        try:
            out.append(model.model_validate(row))
        except ValidationError:
            log.warning(
                "business_profile_item_unreadable",
                extra={"tenant_id": str(tenant_id), "field": name},
            )
    return out


def _hours(raw: Any) -> dict[str, dict[str, str] | None]:
    hours: dict[str, dict[str, str] | None] = {}
    if not isinstance(raw, dict):
        return hours
    for day in DAYS:
        if day not in raw:
            continue
        value = raw[day]
        if value is None:
            hours[day] = None
        elif (
            isinstance(value, dict)
            and isinstance(value.get("opens"), str)
            and isinstance(value.get("closes"), str)
        ):
            hours[day] = {"opens": value["opens"], "closes": value["closes"]}
    return hours


async def load_profile(session: AsyncSession, *, tenant_id: UUID) -> Profile:
    """The tenant's profile under the caller's tenant session. RLS scopes both reads;
    `tenant_id` is restated as a narrowing, never as the isolation."""
    row = (await session.execute(text(_PROFILE_SQL), {"tid": tenant_id})).first()
    contacts = [
        Contact(id=r[0], position=int(r[1]), label=str(r[2]), phone_e164=str(r[3]), note=r[4])
        for r in (await session.execute(text(_CONTACTS_SQL), {"tid": tenant_id})).all()
    ]
    if row is None:
        return Profile(tenant_id=tenant_id, contacts=contacts)
    return Profile(
        tenant_id=tenant_id,
        hours=_hours(row[0]),
        branches=_parsed(Branch, row[1], tenant_id=tenant_id, name="branches"),
        services=_parsed(ServiceItem, row[2], tenant_id=tenant_id, name="services"),
        faqs=_parsed(Faq, row[3], tenant_id=tenant_id, name="faqs"),
        staff=_parsed(StaffMember, row[4], tenant_id=tenant_id, name="staff"),
        booking_rules=row[5],
        languages=list(row[6] or []),
        contacts=contacts,
        setup_steps={k: v for k, v in (row[7] or {}).items() if k in PROFILE_STEPS},
        setup_started_at=row[8],
        setup_dismissed_at=row[9],
        merge_notes=list(row[10] or []),
        updated_at=row[11],
        exists=True,
    )


# ----------------------------------------------------------------- the compiled facts


def hours_line(hours: dict[str, dict[str, str] | None]) -> str | None:
    if not hours:
        return None
    parts = [
        f"{day} {h['opens']}-{h['closes']}" if (h := hours[day]) else f"{day} closed"
        for day in DAYS
        if day in hours
    ]
    return "Hours: " + "; ".join(parts)


def fact_lines(profile: Profile) -> list[str]:
    """The business half of [T0 FACTS], header excluded, in PROMPT-GUIDE §2's order:
    hours, address, services and prices, FAQs, staff, booking rules.

    Deterministic, so an unchanged profile compiles to the same bytes and the recompile
    mints nothing. No contacts and no languages: neither is something the agent says, and
    contact numbers must never reach a prompt.
    """
    lines: list[str] = []
    hours = hours_line(profile.hours)
    if hours:
        lines.append(hours)
    for branch in profile.branches:
        lines.append(f"Address ({_one_line(branch.label)}): {_one_line(branch.address)}")
    for item in profile.services:
        price = f" — ₹{item.price_inr}" if item.price_inr else " — price on request"
        notes = f" ({_one_line(item.notes)})" if item.notes else ""
        lines.append(f"Service: {_one_line(item.name)}{price}{notes}")
    for faq in profile.faqs:
        lines.append(f"FAQ: {_one_line(faq.question)} — {_one_line(faq.answer)}")
    for person in profile.staff:
        said = f" (said: {_one_line(person.pronunciation)})" if person.pronunciation else ""
        role = f", {_one_line(person.role)}" if person.role else ""
        lines.append(f"Staff: {_one_line(person.name)}{said}{role}")
    if profile.booking_rules and profile.booking_rules.strip():
        lines.append(f"Booking: {_one_line(profile.booking_rules)}")
    return lines


def _one_line(value: str) -> str:
    """One line of single spaces. A newline in client text could start a line with `[`,
    which ends the [T0 FACTS] section for every splicer."""
    return " ".join(value.split())


async def profile_fact_lines(session: AsyncSession, *, tenant_id: UUID) -> list[str]:
    return fact_lines(await load_profile(session, tenant_id=tenant_id))


# ------------------------------------------------------------- what an agent needs


#: What must exist before an agent of this client can go live, as stable codes, each
#: with the setup step that fixes it. Every one names something downstream that cannot
#: work without it:
#:
#: * hours: the after-hours branch and the handover rota are judged against them;
#: * an address: "where are you?" is the second question every caller asks;
#: * a service: the price list is the most-asked question;
#: * an escalation contact: a handover has nowhere to go without one.
#:
#: FAQs, staff, booking rules and languages are not blockers: a one-person shop with none
#: of them is a real client.
BLOCKER_STEPS: Final[dict[str, StepId]] = {
    "business_hours_missing": "hours",
    "branch_missing": "branches",
    "service_missing": "services",
    "escalation_contact_missing": "contacts",
}


def go_live_blockers(profile: Profile) -> list[str]:
    blockers: list[str] = []
    if not profile.hours:
        blockers.append("business_hours_missing")
    if not profile.branches:
        blockers.append("branch_missing")
    if not profile.services:
        blockers.append("service_missing")
    if not profile.contacts:
        blockers.append("escalation_contact_missing")
    return blockers


#: What each blocker means to the client, in their words.
BLOCKER_COPY: Final[dict[str, str]] = {
    "business_hours_missing": "Add your opening hours.",
    "branch_missing": "Add your address.",
    "service_missing": "Add at least one service.",
    "escalation_contact_missing": "Add someone who can take calls.",
}


async def assert_ready_to_go_live(session: AsyncSession, *, tenant_id: UUID) -> None:
    """Refuse to put an agent on the phone while the business profile lacks what every
    agent needs. Called when an agent goes LIVE, never on a re-publish of one already
    live: a client editing their profile must not knock a working agent off the phone.

    Each missing item comes back as a field (`setup.<step>`), so the screen can link
    straight to the setup step that fixes it.
    """
    blockers = go_live_blockers(await load_profile(session, tenant_id=tenant_id))
    if not blockers:
        return
    raise ProblemError(
        kind="business_rule",
        code="business_profile_incomplete",
        title="Finish your business profile first",
        detail="Your agent needs a few facts about your business before it can take calls: "
        + " ".join(BLOCKER_COPY[code] for code in blockers),
        status=409,
        remediation="Open Business setup, fill in these steps, then try again.",
        fields=[
            {"field": f"setup.{BLOCKER_STEPS[code]}", "rule": code, "message": BLOCKER_COPY[code]}
            for code in blockers
        ],
    )


def step_state(profile: Profile, step: str) -> Literal["done", "skipped", "todo"]:
    value = profile.setup_steps.get(step)
    if value == "done":
        return "done"
    if value == "skipped":
        return "skipped"
    return "todo"


def setup_complete(profile: Profile) -> bool:
    """Every step answered or skipped."""
    return all(step_state(profile, step) != "todo" for step in PROFILE_STEPS)


__all__ = [
    "BLOCKER_COPY",
    "BLOCKER_STEPS",
    "DAYS",
    "MAX_BRANCHES",
    "MAX_CONTACTS",
    "MAX_FAQS",
    "MAX_LANGUAGES",
    "MAX_SERVICES",
    "MAX_STAFF",
    "Branch",
    "BusinessContactIn",
    "BusinessContactOut",
    "Contact",
    "DayHours",
    "Faq",
    "Profile",
    "ServiceItem",
    "StaffMember",
    "StepId",
    "StepState",
    "assert_ready_to_go_live",
    "fact_lines",
    "go_live_blockers",
    "hours_line",
    "load_profile",
    "profile_fact_lines",
    "setup_complete",
    "step_state",
]
