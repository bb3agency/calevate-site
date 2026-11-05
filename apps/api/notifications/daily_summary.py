"""The owner's daily summary (D-944): what one IST day brought, in one short message.

The owner opts in (`organizations.owner_digest_enabled`, off for every account until they
turn it on); `workers/owner_digest` sends it once a day by email to the account's owners and
billing address, and by WhatsApp to the owner where their WhatsApp opt-in is on file.

WHAT EACH CHANNEL CARRIES, AND WHY THEY DIFFER. The WhatsApp template carries counts and
rupees only: Calevate's WhatsApp account goes through a foreign processor, and the platform's
templates carry no caller's details (`workers/whatsapp.py`, the hot-lead reasoning). The email
also names the top three people who reached a goal and are waiting, each by the business's
own outcome for their call, the name whole and the number masked to its last two
digits, the hot-lead email's rule (`workers/notifications._compose`): a name is what makes the
lead recognisable and nobody can ring it; the full number stays behind the dashboard login.

Figures: answered calls by `crm/performance.CONNECTED_SQL`; missed = inbound calls that did not
connect; the owner's own test calls left out; leads are the people who became a lead that day
(`crm/lead_definition`), not everyone called; spend is what left the wallet that day
(`billing/history.spend_series`); follow-ups waiting are open call-backs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.analytics.proof import per_unit
from apps.api.billing.display import display_inr
from apps.api.billing.history import spend_series
from apps.api.billing.plans import IST
from apps.api.core.console_links import CONSOLE_BASE
from apps.api.core.errors import ProblemError
from apps.api.crm.attention import goal_outcome_labels
from apps.api.crm.lead_definition import BECAME_LEADS_SQL, GOAL_BAND, GOAL_STAGE_NAME
from apps.api.crm.performance import CONNECTED_SQL
from apps.api.tenancy.caller_words import CallerWords, caller_words_for
from apps.workers.redaction import redact

#: People who reached a goal and are waiting, named in the email.
TOP_HOT_LEADS: Final = 3
#: A name is cut to this many characters in the email.
NAME_MAX: Final = 40


@dataclass(frozen=True, slots=True)
class HotLead:
    #: The lead's name on one line, or None when none was captured.
    name: str | None
    #: The number masked to its last two digits (`redaction.PHONE_MASK`).
    phone_masked: str
    #: The business's own outcome their latest goal call ended on, or None.
    goal: str | None = None


@dataclass(frozen=True, slots=True)
class DailySummary:
    day: date
    business_name: str
    slug: str
    answered: int
    missed: int
    leads: int
    #: Of `leads`, those that reached the business's goal (`GOAL_BAND`).
    hot_leads: int
    top_hot: tuple[HotLead, ...]
    spent_inr: Decimal
    per_lead_inr: Decimal | None
    follow_ups_waiting: int
    #: What this business calls a lead; the platform's words until it is judged.
    words: CallerWords = field(default_factory=CallerWords)

    @property
    def dashboard_url(self) -> str:
        return f"{CONSOLE_BASE}/c/{self.slug}"

    @property
    def settings_url(self) -> str:
        return f"{CONSOLE_BASE}/c/{self.slug}/settings/alerts"

    @property
    def quiet(self) -> bool:
        """Nothing happened: no call, no lead, nothing waiting, nothing spent."""
        return (
            not (self.answered or self.missed or self.leads or self.follow_ups_waiting)
            and self.spent_inr == 0
        )


def _one_line(value: str | None) -> str | None:
    line = " ".join((value or "").split())[:NAME_MAX]
    return line or None


def _bounds(day: date) -> dict[str, datetime]:
    start = datetime.combine(day, time.min, tzinfo=IST)
    return {"start": start, "end": start + timedelta(days=1)}


_CALLS_SQL: Final = text(
    f"SELECT count(*) FILTER (WHERE {CONNECTED_SQL}), "
    f"count(*) FILTER (WHERE direction = 'inbound' AND NOT {CONNECTED_SQL}) "
    "FROM calls WHERE started_at >= :start AND started_at < :end "
    "AND NOT (trial_call OR paid_test_call)"
)
#: People who became a lead that day (`crm/lead_definition`) and how many of them reached a
#: goal (`GOAL_BAND`, the definition the stats band and campaign results count too).
_LEADS_SQL: Final = text(
    "SELECT count(*), count(*) FILTER (WHERE bl.status = ANY(:goal)) "
    f"FROM {BECAME_LEADS_SQL} AS bl "
    "WHERE bl.became_lead_at >= :start AND bl.became_lead_at < :end"
)
#: The day's people still waiting at the goal stage (`hot`; a `won` one needs no follow-up).
_TOP_HOT_SQL: Final = text(
    f"SELECT l.name, l.phone_e164, l.id FROM {BECAME_LEADS_SQL} AS bl "
    "JOIN leads l ON l.id = bl.id "
    "WHERE bl.status = 'hot' AND bl.became_lead_at >= :start AND bl.became_lead_at < :end "
    "ORDER BY l.status_set_at DESC NULLS LAST, bl.became_lead_at DESC LIMIT :n"
)
_FOLLOW_UPS_SQL: Final = text("SELECT count(*) FROM scheduled_callbacks WHERE status = 'scheduled'")
_ORG_SQL: Final = text(
    "SELECT name, slug, owner_digest_enabled FROM organizations WHERE deleted_at IS NULL"
)


async def build_summary(session: AsyncSession, *, tenant_id: UUID, day: date) -> DailySummary:
    """The day's figures, under the client's own RLS session."""
    org = (await session.execute(_ORG_SQL)).first()
    if org is None:
        raise ProblemError.not_found("Organization")
    binds = _bounds(day)
    answered, missed = (await session.execute(_CALLS_SQL, binds)).one()
    leads, hot = (await session.execute(_LEADS_SQL, {**binds, "goal": list(GOAL_BAND)})).one()
    top = (await session.execute(_TOP_HOT_SQL, {**binds, "n": TOP_HOT_LEADS})).all()
    goals = await goal_outcome_labels(session, [row[2] for row in top])
    follow_ups = int((await session.execute(_FOLLOW_UPS_SQL)).scalar_one())
    spent = (await spend_series(session, tenant_id=tenant_id, start=day, end=day)).spent_inr
    return DailySummary(
        day=day,
        business_name=str(org[0]),
        slug=str(org[1]),
        answered=int(answered),
        missed=int(missed),
        leads=int(leads),
        hot_leads=int(hot),
        top_hot=tuple(
            HotLead(
                name=_one_line(row[0]),
                phone_masked=redact(str(row[1])).text,
                goal=goals.get(row[2]),
            )
            for row in top
        ),
        spent_inr=spent,
        per_lead_inr=per_unit(spent, int(leads)),
        follow_ups_waiting=follow_ups,
        words=await caller_words_for(session, tenant_id),
    )


def whatsapp_variables(summary: DailySummary) -> tuple[str, ...]:
    """The template's seven variables, in order. Counts and rupees only."""
    return (
        summary.business_name,
        str(summary.answered),
        str(summary.missed),
        str(summary.leads),
        str(summary.hot_leads),
        display_inr(summary.spent_inr),
        str(summary.follow_ups_waiting),
    )


def _count(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def email_subject(summary: DailySummary) -> str:
    new_lead = summary.words.new_lead
    return f"Today: {_count(summary.answered, 'call')} answered, {_count(summary.leads, new_lead)}"


def email_lines(summary: DailySummary) -> list[str]:
    return [
        f"{_count(summary.answered, 'call')} answered and {summary.missed} missed today.",
        f"{_count(summary.leads, summary.words.new_lead)}, "
        f"{summary.hot_leads} of them reached a goal.",
        f"{_count(summary.follow_ups_waiting, 'call-back')} waiting for you.",
    ]


def email_facts(summary: DailySummary) -> list[tuple[str, str]]:
    words = summary.words
    facts = [
        ("Spent today", display_inr(summary.spent_inr)),
        (
            f"Cost per {words.lead} today",
            display_inr(summary.per_lead_inr)
            if summary.per_lead_inr is not None
            else f"No {words.lead}s",
        ),
    ]
    facts += [
        (
            lead.goal or GOAL_STAGE_NAME,
            f"{lead.name or 'Name not captured'} ({lead.phone_masked})",
        )
        for lead in summary.top_hot
    ]
    return facts


# --- the switch ---------------------------------------------------------------------------


async def read_switch(session: AsyncSession) -> bool:
    row = (await session.execute(_ORG_SQL)).first()
    if row is None:
        raise ProblemError.not_found("Organization")
    return bool(row[2])


async def write_switch(session: AsyncSession, *, enabled: bool) -> bool:
    """Set the switch; True when it changed. RLS confines the UPDATE to this account's row
    (`kb/curation.write_switch` argues why no tenant predicate is added)."""
    current = (
        await session.execute(
            text(
                "SELECT owner_digest_enabled FROM organizations WHERE deleted_at IS NULL FOR UPDATE"
            )
        )
    ).first()
    if current is None:
        raise ProblemError.not_found("Organization")
    if bool(current[0]) is enabled:
        return False
    await session.execute(
        text(
            "UPDATE organizations SET owner_digest_enabled = :on, updated_at = now() "
            "WHERE deleted_at IS NULL"
        ),
        {"on": enabled},
    )
    return True


__all__ = [
    "NAME_MAX",
    "TOP_HOT_LEADS",
    "DailySummary",
    "HotLead",
    "build_summary",
    "email_facts",
    "email_lines",
    "email_subject",
    "read_switch",
    "whatsapp_variables",
    "write_switch",
]
