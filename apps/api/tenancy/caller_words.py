"""What one business calls the people on its calls, for owner-facing text a server writes.

The lead ladder (`new … hot … won`, D-21) is the same for every business, but its sales
words are not: "a hot lead" is right for a shop and wrong for a free app that calls its
registered users to help them (Rytu Khata, 5 Nov 2026). Emails, summaries and screens
therefore say "lead" only for a business judged to sell, and otherwise name the caller as the
business does (`GeneratedCopy.caller_noun`: user, farmer, member…), or "caller" until its
copy names one.

UNKNOWN IS NEUTRAL (audit of 5 Nov 2026, G1-1): until the copy run has judged the business,
`sells` is None and the words are the neutral ones ("interested caller"), true of every
business. Only `sells is True` brings the sales words, and not for an account whose agents
are all support agents (`agents.purpose`, founder 21 Nov 2026).

The web twin is `callersWord` / `leadWords` in `apps/web/src/lib/businessCapabilities.ts`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.tenancy.business_copy import Capabilities, copy_for

#: The noun for a business whose copy names none: neutral, true of every call.
DEFAULT_CALLER: Final = "caller"


def plural(noun: str) -> str:
    """A plural for a singular caller noun: "user" → "users", "family" → "families"."""
    if noun.endswith("y") and noun[-2:-1] not in ("a", "e", "i", "o", "u"):
        return f"{noun[:-1]}ies"
    if noun.endswith(("s", "x", "z", "ch", "sh")):
        return f"{noun}es"
    return f"{noun}s"


@dataclass(frozen=True, slots=True)
class CallerWords:
    """The words for one business. Build it with `caller_words_for`; `CallerWords()` is the
    unknown business, which reads neutrally."""

    #: Whether the business sells anything; None until judged.
    sells: bool | None = None
    #: What the business calls its callers ("customer", "user"), or None when not written.
    caller_noun: str | None = None
    #: Every working agent of the account is a support agent (`agents.purpose`): its callers
    #: are helped, not sold to, whatever the business sells elsewhere.
    all_support: bool = False

    @property
    def sales_words(self) -> bool:
        """Whether "lead" is the word: a business judged to sell, with a sales agent."""
        return self.sells is True and not self.all_support

    @property
    def caller(self) -> str:
        return self.caller_noun or DEFAULT_CALLER

    @property
    def callers(self) -> str:
        return plural(self.caller)

    @property
    def lead(self) -> str:
        """One lead, as a noun phrase: "lead" for a business judged to sell, else "interested
        caller" (a lead is a person who showed interest, `crm/lead_definition`)."""
        return "lead" if self.sales_words else f"interested {self.caller}"

    @property
    def leads(self) -> str:
        return "leads" if self.sales_words else f"interested {self.callers}"

    @property
    def new_lead(self) -> str:
        return "new lead" if self.sales_words else f"interested {self.caller}"

    @property
    def new_leads(self) -> str:
        return "new leads" if self.sales_words else f"interested {self.callers}"

    @property
    def hot_lead(self) -> str:
        """The top of the ladder: "hot lead", or "most interested caller"."""
        return "hot lead" if self.sales_words else f"most interested {self.caller}"

    @property
    def hot_leads(self) -> str:
        return "hot leads" if self.sales_words else f"most interested {self.callers}"


#: True when the account has working agents and every one is a support agent. Archived and
#: erased agents take no calls, so they do not count either way. The web twin is
#: `allSupport` in `apps/web/src/lib/businessCapabilities.ts`, read off the same roster.
ALL_SUPPORT_SQL: Final = (
    "SELECT coalesce(bool_and(purpose = 'support'), false) FROM agents "
    "WHERE tenant_id = :tid AND deleted_at IS NULL AND status <> 'archived'"
)


async def all_support(session: AsyncSession, tenant_id: UUID) -> bool:
    return bool((await session.execute(text(ALL_SUPPORT_SQL), {"tid": tenant_id})).scalar())


async def caller_words_for(session: AsyncSession, tenant_id: UUID) -> CallerWords:
    copy = await copy_for(session, tenant_id)
    if copy is None:
        return CallerWords()
    caps = copy.capabilities or Capabilities.unknown()
    return CallerWords(
        sells=caps.sells.applies,
        caller_noun=copy.caller_noun,
        all_support=await all_support(session, tenant_id),
    )


__all__ = ["DEFAULT_CALLER", "CallerWords", "all_support", "caller_words_for", "plural"]
