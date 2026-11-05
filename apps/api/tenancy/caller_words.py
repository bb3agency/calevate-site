"""What one business calls the people on its calls, for owner-facing text a server writes.

The lead ladder (`new … hot … won`, D-21) is the same for every business, but its sales
words are not: "a hot lead" is right for a shop and wrong for a free app that calls its
registered users to help them (Rytu Khata, 5 Nov 2026). Emails and summaries therefore say
"lead" only while the business is not known to sell nothing, and otherwise name the caller
as the business does (`GeneratedCopy.caller_noun`: user, farmer, member…).

THE UNKNOWN RULE (`business_copy.Capabilities`): until the copy run has judged the business,
`sells` is None and every word here is today's ("lead", "hot lead"). Only `sells is False`
changes them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.tenancy.business_copy import Capabilities, copy_for

#: The noun for a business whose copy names none: neutral, true of every call.
DEFAULT_CALLER: Final = "caller"


@dataclass(frozen=True, slots=True)
class CallerWords:
    """The words for one business. Build it with `caller_words_for`; `CallerWords()` is the
    unknown business, which reads exactly as the platform read before."""

    #: Whether the business sells anything; None until judged.
    sells: bool | None = None
    #: What the business calls its callers ("customer", "user"), or None when not written.
    caller_noun: str | None = None

    @property
    def caller(self) -> str:
        return self.caller_noun or DEFAULT_CALLER

    @property
    def lead(self) -> str:
        """One lead, as a noun phrase: "lead", or "interested user" for a business that
        sells nothing (a lead is a person who showed interest, `crm/lead_definition`)."""
        return f"interested {self.caller}" if self.sells is False else "lead"

    @property
    def new_lead(self) -> str:
        return f"interested {self.caller}" if self.sells is False else "new lead"

    @property
    def hot_lead(self) -> str:
        """The top of the ladder: "hot lead", or "most interested user"."""
        return f"most interested {self.caller}" if self.sells is False else "hot lead"


async def caller_words_for(session: AsyncSession, tenant_id: UUID) -> CallerWords:
    copy = await copy_for(session, tenant_id)
    if copy is None:
        return CallerWords()
    caps = copy.capabilities or Capabilities.unknown()
    return CallerWords(sells=caps.sells.applies, caller_noun=copy.caller_noun)


__all__ = ["DEFAULT_CALLER", "CallerWords", "caller_words_for"]
