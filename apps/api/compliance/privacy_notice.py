"""The SHORT caller notice, in English, Telugu and Hindi (D-943).

`caller_notice.py` drafts the full notice a client's counsel works from. This is the short
one a business can actually put in front of a caller: on its website, in a WhatsApp
message, read out at the counter. DPDP §5(3) lets a person read a notice in English or
any Eighth Schedule language; Telugu and Hindi are the two this client base speaks.

SAME FACTS, FEWER WORDS. Everything here is derived from the same draft
(`build_caller_notice`): the items collected, the retention periods, the switches. It
says nothing the long notice does not, and its rights paragraph matches `/legal/privacy`
and the DPA: access, correction, erasure, nomination, a grievance, the Data Protection
Board, and an answer within 90 days (DPDP Rules 2025, official per the PIB backgrounder of
17 Nov 2025, `docs/research/research_notes/Calevate market and technology edge/
india_regulation.md` §3). Its blanks are the long notice's blanks, spelled the same, so a
value the client fills once fills both.

The wording lives in `calevate_shared/spoken_lines.json` (G4-2), entries `privacy_notice.*`.
THE TELUGU AND HINDI ARE MACHINE-DRAFTED and say so in their own disclaimer: a native
speaker and the client's advocate read them before they reach a caller. A client's own
field labels are quoted as the client wrote them, never translated by us.
"""

from __future__ import annotations

from typing import Final, Literal, cast
from uuid import UUID

from calevate_shared import spoken_lines
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.caller_notice import (
    BUSINESS_CONTACT,
    BUSINESS_NAME,
    STANDARD_ITEMS,
    build_caller_notice,
    retention_category,
)
from apps.api.compliance.models import RIGHTS_RESPONSE_DAYS

NoticeLanguage = Literal["en", "te", "hi"]
NOTICE_LANGUAGES: Final[tuple[NoticeLanguage, ...]] = ("en", "te", "hi")

DISCLAIMER: Final[dict[NoticeLanguage, str]] = {
    "en": (
        "DRAFT — not legal advice. Generated from your own settings. Have your advocate check "
        "it before you use it. Anything in double braces is a blank only you can fill."
    ),
    "te": (
        "DRAFT — not legal advice. This Telugu wording was machine-drafted: have a native "
        "speaker and your advocate check it before you use it. Anything in double braces is "
        "a blank only you can fill."
    ),
    "hi": (
        "DRAFT — not legal advice. This Hindi wording was machine-drafted: have a native "
        "speaker and your advocate check it before you use it. Anything in double braces is "
        "a blank only you can fill."
    ),
}

#: The standard collected items, per language. A client's own fields are quoted as written.
_ITEMS: Final = cast(
    "dict[NoticeLanguage, tuple[str, ...]]", spoken_lines.by_language("privacy_notice.items")
)

_MEMORY_LINE: Final = cast(
    "dict[NoticeLanguage, str]", spoken_lines.lines("privacy_notice.memory_line")
)

#: Retention categories (`caller_notice._CATEGORY_LABELS` keys), per language.
_RETENTION: Final = cast(
    "dict[NoticeLanguage, dict[str, str]]",
    spoken_lines.by_language("privacy_notice.retention"),
)

_DAYS: Final = cast("dict[NoticeLanguage, str]", spoken_lines.lines("privacy_notice.days"))

_TEMPLATE: Final = cast("dict[NoticeLanguage, str]", spoken_lines.lines("privacy_notice.template"))


async def build_short_notice(
    session: AsyncSession, *, tenant_id: UUID, language: NoticeLanguage
) -> str:
    """The short notice, in `language`, from this account's own settings."""
    draft = await build_caller_notice(session, tenant_id=tenant_id)
    items = list(_ITEMS[language])
    if draft.caller_memory_on:
        items.append(_MEMORY_LINE[language])
    # The client's own field labels, quoted as written: a label is the client's word for
    # what they ask, and a translation of it would be ours.
    items.extend(item.what for item in draft.collected if item.what not in STANDARD_ITEMS)
    labels = _RETENTION[language]
    retention = [
        f"- {labels.get(retention_category(line.what), line.what)}: "
        + _DAYS[language].format(n=line.days)
        for line in draft.retention
    ]
    return _TEMPLATE[language].format(
        business=BUSINESS_NAME,
        contact=BUSINESS_CONTACT,
        days=RIGHTS_RESPONSE_DAYS,
        items="\n".join(f"- {item}" for item in items),
        retention="\n".join(retention) or "- {{HOW LONG YOU KEEP CALL RECORDS}}",
    )


__all__ = ["DISCLAIMER", "NOTICE_LANGUAGES", "NoticeLanguage", "build_short_notice"]
