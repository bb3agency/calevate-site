"""The SHORT caller notice, in English and each language its lines are written in (D-943).

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

The wording lives in `calevate_shared/spoken_lines.json` (G4-2), entries `privacy_notice.*`,
keyed by the language's base code ("te", not "te-IN"). The languages offered are exactly
those every one of those entries has lines for, so a language gains a notice by gaining its
lines, never by a code change, and a staged agent language without them is held back by its
readiness record (`agents/languages.StagedLanguageReadiness.missing`). Every language but
English is MACHINE-DRAFTED and says so in its disclaimer: a native speaker and the client's
advocate read it before it reaches a caller. A client's own field labels are quoted as the
client wrote them, never translated by us.
"""

from __future__ import annotations

from typing import Final, cast
from uuid import UUID

from calevate_shared import spoken_lines
from calevate_shared.languages import built_languages
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.caller_notice import (
    BUSINESS_CONTACT,
    BUSINESS_NAME,
    STANDARD_ITEMS,
    build_caller_notice,
    retention_category,
)
from apps.api.compliance.models import RIGHTS_RESPONSE_DAYS

#: The `privacy_notice.*` entries a notice is assembled from; a language needs all of them.
NOTICE_ENTRIES: Final = (
    "privacy_notice.items",
    "privacy_notice.memory_line",
    "privacy_notice.retention",
    "privacy_notice.days",
    "privacy_notice.template",
)

#: The standard collected items, per language. A client's own fields are quoted as written.
_ITEMS: Final = cast("dict[str, tuple[str, ...]]", spoken_lines.by_language("privacy_notice.items"))

_MEMORY_LINE: Final = spoken_lines.lines("privacy_notice.memory_line")

#: Retention categories (`caller_notice._CATEGORY_LABELS` keys), per language.
_RETENTION: Final = cast(
    "dict[str, dict[str, str]]", spoken_lines.by_language("privacy_notice.retention")
)

_DAYS: Final = spoken_lines.lines("privacy_notice.days")

_TEMPLATE: Final = spoken_lines.lines("privacy_notice.template")


def _languages_with_lines() -> tuple[str, ...]:
    """The base codes every notice entry has lines for, English first, then in the file's
    order."""
    keyed = [set(spoken_lines.by_language(entry)) for entry in NOTICE_ENTRIES]
    complete = set.intersection(*keyed)
    ordered = [code for code in spoken_lines.by_language(NOTICE_ENTRIES[-1]) if code in complete]
    return tuple(sorted(ordered, key=lambda code: code != "en"))


#: The languages the short notice can be read in.
NOTICE_LANGUAGES: Final[tuple[str, ...]] = _languages_with_lines()


def notice_language_name(code: str) -> str:
    """The English name of a notice language ("te" is "Telugu"), or the code itself."""
    for row in built_languages():
        if row.bcp47.split("-")[0] == code:
            return row.english_name.split(" (")[0]
    return code


def has_notice_lines(tag: str) -> bool:
    """Whether a language (any BCP-47 tag, e.g. "ta-IN") has a short notice."""
    return tag.split("-")[0].lower() in NOTICE_LANGUAGES


def disclaimer(code: str) -> str:
    """The note shown above the notice: English is generated, every other language was
    machine-drafted and must be checked by a native speaker."""
    tail = "check it before you use it. Anything in double braces is a blank only you can fill."
    if code == "en":
        return (
            "DRAFT — not legal advice. Generated from your own settings. Have your advocate " + tail
        )
    return (
        f"DRAFT — not legal advice. This {notice_language_name(code)} wording was "
        "machine-drafted: have a native speaker and your advocate " + tail
    )


async def build_short_notice(session: AsyncSession, *, tenant_id: UUID, language: str) -> str:
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


__all__ = [
    "NOTICE_ENTRIES",
    "NOTICE_LANGUAGES",
    "build_short_notice",
    "disclaimer",
    "has_notice_lines",
    "notice_language_name",
]
