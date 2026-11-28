"""Find, for the client console (W7.4): people, their calls and the screens, from one box.

People are leads matched by name, by the last digits of their number (a suffix, the way
`db.like.phone_suffix_pattern` matches the Leads search), and, for a name written in Telugu
script, by a Latin spelling of it. Erased and retention-expired leads carry `deleted_at` and
are never matched; RLS scopes every read to the account. A number is answered with its last
four digits only, and nothing here logs the term (hard rule 6).

TELUGU TYPED IN ENGLISH LETTERS. No transliteration library is installed (see
`admin.service.slug_from_name`), and a full romanisation is not needed to FIND a name: both
spellings are reduced to a consonant skeleton and compared. Vowels are where romanisations
disagree ("Sreenivas", "Srinivas", "Shrinivaas" all read శ్రీనివాస్), so they are dropped;
aspiration is dropped (`h`, ఖ = క); the sibilants శ ష స are one `s`; retroflex and dental
pairs fold together (ట త, డ ద, ణ న, ళ ల); `y` is dropped, because "Naidu" spells నాయుడు's
య as a vowel; an anusvara is `n`, and `m` before `p`/`b` is `n` on both sides ("Sampath" for
సంపత్). The Telugu half runs in SQL as one `translate()` plus three regex passes over the
name, so the match happens in the database under RLS and its LIMIT; the Latin half is
`latin_skeleton` below, and `tests/find_test.py` pins that the two agree on real names.

The rejected alternative was matching in Python over every lead: an account's whole list
read into memory for every keystroke, which is the unbounded read `check_list_bounds` exists
to stop.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Final, cast
from uuid import UUID

from calevate_shared.extraction import OutcomeTag
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.copilot.screens import CLIENT_SCREENS, Screen
from apps.api.core.rbac import ROLE_PERMISSIONS
from apps.api.crm.outcomes import normalise as normalise_outcome
from apps.api.crm.schemas import LeadStatus
from apps.api.db.like import contains_pattern, escape_like

#: Each Telugu letter and the skeleton letter it reads as. Every other Telugu character
#: (vowels, vowel signs, the virama, the visarga, length marks, digits) is deleted.
_TELUGU_TO_LATIN: Final[dict[str, str]] = {
    "క": "k", "ఖ": "k", "గ": "g", "ఘ": "g", "ఙ": "n",
    "చ": "c", "ఛ": "c", "జ": "j", "ఝ": "j", "ఞ": "n",
    "ట": "t", "ఠ": "t", "డ": "d", "ఢ": "d", "ణ": "n",
    "త": "t", "థ": "t", "ద": "d", "ధ": "d", "న": "n",
    "ప": "p", "ఫ": "p", "బ": "b", "భ": "b", "మ": "m",
    "ర": "r", "ఱ": "r", "ల": "l", "ళ": "l", "ఴ": "l", "వ": "v",
    "శ": "s", "ష": "s", "స": "s",
    "\u0c01": "n", "\u0c02": "n",  # candrabindu, anusvara
    "ఋ": "r", "ౠ": "r", "ృ": "r", "ౄ": "r",
    "ఌ": "l", "ౡ": "l", "ౢ": "l", "ౣ": "l",
}  # fmt: skip
_TELUGU_BLOCK: Final = range(0x0C00, 0x0C80)
_DELETED: Final = "".join(chr(cp) for cp in _TELUGU_BLOCK if chr(cp) not in _TELUGU_TO_LATIN)
#: `translate(name, FROM, TO)`: the mapped letters first, then the deleted ones, which have
#: no counterpart in TO and are therefore removed (postgresql.org/docs/16/functions-string).
TRANSLATE_FROM: Final = "".join(_TELUGU_TO_LATIN) + _DELETED
TRANSLATE_TO: Final = "".join(_TELUGU_TO_LATIN.values())

#: The letters a skeleton is made of.
_SKELETON_KEEP: Final = "bcdgjklmnprstv"

#: The name's skeleton, in SQL. Mirrors `_skeleton` below step for step.
NAME_SKELETON_SQL: Final = (
    "regexp_replace(regexp_replace(regexp_replace("
    "lower(translate(l.name, :tel_from, :tel_to)), "
    f"'[^{_SKELETON_KEEP}]', '', 'g'), "
    r"'m([pb])', 'n\1', 'g'), "
    r"'(.)\1+', '\1', 'g')"
)

_LATIN_ONLY: Final = re.compile(r"\A[a-z\s.'\-]+\Z")
_TELUGU_SQL: Final = "l.name ~ '[ఀ-౿]'"

#: Fewer letters than this match too many names to be worth a skeleton search.
MIN_SKELETON_LETTERS: Final = 3
#: A number is matched on its last digits from this many on; one digit matches a tenth of
#: every list.
MIN_PHONE_DIGITS: Final = 4


def _skeleton(latin: str) -> str:
    kept = re.sub(f"[^{_SKELETON_KEEP}]", "", latin)
    nasal = re.sub(r"m([pb])", r"n\1", kept)
    return re.sub(r"(.)\1+", r"\1", nasal)


def latin_skeleton(term: str) -> str | None:
    """The skeleton of a name typed in English letters, or None when it is not one."""
    lowered = term.strip().lower()
    if not _LATIN_ONLY.match(lowered) or sum(ch.isalpha() for ch in lowered) < MIN_SKELETON_LETTERS:
        return None
    spelled = (
        lowered.replace("ch", "C")
        .replace("c", "k")
        .replace("q", "k")
        .replace("x", "ks")
        .replace("z", "j")
        .replace("w", "v")
        .replace("f", "p")
        .replace("C", "c")
    )
    skeleton = _skeleton(spelled)
    return skeleton if len(skeleton) >= 2 else None


def telugu_skeleton(name: str) -> str:
    """`NAME_SKELETON_SQL` in Python, for tests that compare the two halves."""
    table: dict[int, str | None] = {ord(ch): to for ch, to in _TELUGU_TO_LATIN.items()}
    table.update(dict.fromkeys(map(ord, _DELETED)))
    return _skeleton(name.translate(table).lower())


def _digits(term: str) -> str:
    return "".join(ch for ch in term if ch.isdigit() and ch.isascii())


@dataclass(frozen=True, slots=True)
class FoundPerson:
    lead_id: UUID
    name: str | None
    phone_last4: str
    status: LeadStatus


@dataclass(frozen=True, slots=True)
class FoundCall:
    call_id: UUID
    lead_id: UUID
    name: str | None
    phone_last4: str
    direction: str
    at: datetime
    outcome_tag: OutcomeTag | None
    business_outcome_label: str | None
    headline: str | None


async def find_people(session: AsyncSession, term: str, *, limit: int) -> list[FoundPerson]:
    """Leads matching `term` by name, last digits, or a Latin spelling of a Telugu name."""
    clauses: list[str] = []
    params: dict[str, object] = {"limit": limit, "prefix": f"{escape_like(term)}%"}
    stripped = term.strip()
    digits = _digits(stripped)
    phone_shaped = bool(re.fullmatch(r"[\d\s()+.\-]+", stripped))
    if phone_shaped:
        if len(digits) < MIN_PHONE_DIGITS:
            return []
        clauses.append("l.phone_e164 LIKE :phone_suffix")
        params["phone_suffix"] = f"%{digits[-10:]}"
    else:
        clauses.append("l.name ILIKE :contains")
        params["contains"] = contains_pattern(stripped)
        skeleton = latin_skeleton(stripped)
        if skeleton is not None:
            clauses.append(f"({_TELUGU_SQL} AND {NAME_SKELETON_SQL} LIKE :skeleton)")
            params.update(skeleton=f"%{skeleton}%", tel_from=TRANSLATE_FROM, tel_to=TRANSLATE_TO)
    rows = (
        await session.execute(
            text(
                "SELECT l.id, l.name, right(l.phone_e164, 4) AS last4, l.status FROM leads l "
                f"WHERE l.deleted_at IS NULL AND ({' OR '.join(clauses)}) "
                # A name that starts with what was typed first, then the freshest.
                "ORDER BY (l.name ILIKE :prefix) DESC NULLS LAST, l.updated_at DESC, l.id DESC "
                "LIMIT :limit"
            ),
            params,
        )
    ).all()
    return [
        FoundPerson(
            lead_id=row.id,
            name=row.name,
            phone_last4=row.last4,
            status=cast(LeadStatus, row.status),
        )
        for row in rows
    ]


async def calls_of(session: AsyncSession, lead_ids: list[UUID], *, limit: int) -> list[FoundCall]:
    """The latest calls with the people found, newest first. Erased calls are left out."""
    if not lead_ids:
        return []
    rows = (
        await session.execute(
            text(
                "SELECT c.id, c.lead_id, l.name, right(l.phone_e164, 4) AS last4, c.direction, "
                "COALESCE(c.started_at, c.created_at) AS at, c.outcome_tag, "
                "c.business_outcome_label, c.headline FROM calls c "
                "JOIN leads l ON l.id = c.lead_id "
                "WHERE c.lead_id = ANY(:ids) AND c.erased_subject_ref IS NULL "
                "AND l.deleted_at IS NULL "
                "ORDER BY COALESCE(c.started_at, c.created_at) DESC, c.id DESC LIMIT :limit"
            ),
            {"ids": lead_ids, "limit": limit},
        )
    ).all()
    return [
        FoundCall(
            call_id=row.id,
            lead_id=row.lead_id,
            name=row.name,
            phone_last4=row.last4,
            direction=row.direction,
            at=row.at,
            outcome_tag=normalise_outcome(row.outcome_tag),
            business_outcome_label=row.business_outcome_label,
            headline=row.headline,
        )
        for row in rows
    ]


def find_screens(term: str, *, role: str | None, limit: int) -> list[Screen]:
    """The console screens this role may open whose name or a client word for it matches."""
    words = term.strip().lower()
    if not words:
        return []
    held = ROLE_PERMISSIONS.get(role or "", frozenset())
    open_to_role = [s for s in CLIENT_SCREENS if s.permission is None or s.permission in held]
    named = [s for s in open_to_role if words in s.name.lower()]
    aliased = [
        s for s in open_to_role if s not in named and any(words in alias for alias in s.aliases)
    ]
    return [*named, *aliased][:limit]
