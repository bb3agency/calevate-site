"""What an agent may know about an inbound caller before it answers (D-716).

The answer to the voice platform's caller lookup (`worker/engine_lookups.py`): a handful of
short values that fill `{{name}}` and the like in the agent's greeting and instructions.
Read from THIS tenant's records only, with reads only and no network calls, because the
platform waits two seconds and the caller hears ringing meanwhile.

WHAT IS SENT (founder decision 15, 10 Oct 2026):

* always, when known: `name`, `first_name`, `lead_name` (letters and spaces only),
  `product_interest` (what the lead said they want), `caller_known` and `callback_allowed`
  (`no` when the number is on the do-not-call list, so the agent does not offer one);
* only when the agent remembers callers (`agents.caller_memory_enabled`, whose notice the
  agent speaks, D-507): `last_call_topic` (the last call's one-line headline, already
  redacted when stored), `open_callback` (the next booked call back, Indian time) and
  `preferred_language`.

NEVER SENT: the number, email, address, amounts, notes, transcript text or any other field
of the lead. The lookup is answered on the number the call CLAIMS to come from (the vendor's
own warning: "treat what it is sent like caller ID"), so nothing here is anything a caller
spoofing a number should be able to learn beyond a first name and a product.

Limits are the vendor's: at most 20 values, each at most 150 characters, scalars only
(update-agent `callStartUrl`, read 10 Oct 2026).
"""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

from calevate_shared.calling_window import IST
from calevate_shared.lead_fields import NEED_KEY
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.dnc import check_number

MAX_VALUES: Final = 20
MAX_VALUE_CHARS: Final = 150
NAME_MAX: Final = 40
INTEREST_MAX: Final = 80
HEADLINE_MAX: Final = 90
LANGUAGE_MAX: Final = 20

#: Variables sent whatever the memory switch says.
ALWAYS_KEYS: Final = frozenset(
    {"name", "first_name", "lead_name", "product_interest", "caller_known", "callback_allowed"}
)
#: Variables sent only to an agent that remembers callers.
MEMORY_KEYS: Final = frozenset({"last_call_topic", "open_callback", "preferred_language"})

# Anything that could carry a number or an address out of a free-text field.
_DIGIT_RUN = re.compile(r"\d[\d\s\-()+]{3,}\d")
_EMAIL = re.compile(r"\S+@\S+")
_SPACES = re.compile(r"\s+")


def clean_name(raw: Any) -> str | None:
    """Letters and spaces only, any script, at most `NAME_MAX` characters."""
    if not isinstance(raw, str):
        return None
    kept = "".join(ch if unicodedata.category(ch)[0] in ("L", "M") else " " for ch in raw)
    name = _SPACES.sub(" ", kept).strip()[:NAME_MAX].strip()
    return name or None


def clean_text(raw: Any, limit: int) -> str | None:
    """A short free-text value with number runs and emails taken out."""
    if not isinstance(raw, str):
        return None
    tidy = _EMAIL.sub(" ", raw)
    tidy = _DIGIT_RUN.sub(" ", tidy)
    tidy = "".join(ch for ch in tidy if unicodedata.category(ch)[0] != "C")
    tidy = _SPACES.sub(" ", tidy).strip()
    if len(tidy) > limit:
        tidy = tidy[: limit - 1].rstrip() + "…"
    return tidy or None


def spoken_when(at: datetime) -> str:
    """`Sat 11 Oct, 4:00 PM`, Indian time: what an agent can read to a caller."""
    ist = at.astimezone(UTC) + IST
    hour = ist.strftime("%I").lstrip("0") or "12"
    return f"{ist.strftime('%a')} {ist.day} {ist.strftime('%b')}, {hour}:{ist.strftime('%M %p')}"


def bounded(values: dict[str, str]) -> dict[str, str]:
    """The vendor's limits, applied here so nothing is cut where we cannot see it."""
    out: dict[str, str] = {}
    for key, value in values.items():
        if len(out) >= MAX_VALUES:
            break
        if value:
            out[key] = value[:MAX_VALUE_CHARS]
    return out


async def caller_variables(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID, phone_e164: str
) -> dict[str, str]:
    """The lookup answer for `phone_e164` calling `agent_id`, from this tenant's records."""
    memory = bool(
        (
            await session.execute(
                text(
                    "SELECT caller_memory_enabled FROM agents "
                    "WHERE id = :aid AND deleted_at IS NULL"
                ),
                {"aid": agent_id},
            )
        ).scalar()
    )
    lead = (
        await session.execute(
            text(
                "SELECT name, data FROM leads WHERE phone_e164 = :p AND deleted_at IS NULL "
                # The lead this agent holds first, then the newest of any other agent's.
                "ORDER BY (agent_id = :aid) DESC, updated_at DESC LIMIT 1"
            ),
            {"p": phone_e164, "aid": agent_id},
        )
    ).first()
    called_before = bool(
        (
            await session.execute(
                text("SELECT EXISTS (SELECT 1 FROM calls WHERE from_e164 = :p OR to_e164 = :p)"),
                {"p": phone_e164},
            )
        ).scalar()
    )
    suppressed = (await check_number(session, tenant_id=tenant_id, raw=phone_e164)).suppressed

    values: dict[str, str] = {
        "caller_known": "yes" if lead is not None or called_before else "no",
        "callback_allowed": "no" if suppressed else "yes",
    }
    data: dict[str, Any] = lead[1] if lead is not None and isinstance(lead[1], dict) else {}
    name = clean_name(lead[0]) if lead is not None else None
    if name:
        values["name"] = name
        values["lead_name"] = name
        values["first_name"] = name.split(" ")[0]
    interest = clean_text(data.get(NEED_KEY), INTEREST_MAX)
    if interest:
        values["product_interest"] = interest

    if memory:
        headline = (
            await session.execute(
                text(
                    "SELECT headline FROM calls WHERE (from_e164 = :p OR to_e164 = :p) "
                    "AND headline IS NOT NULL ORDER BY created_at DESC LIMIT 1"
                ),
                {"p": phone_e164},
            )
        ).scalar()
        topic = clean_text(headline, HEADLINE_MAX)
        if topic:
            values["last_call_topic"] = topic
        due = (
            await session.execute(
                text(
                    "SELECT requested_at FROM scheduled_callbacks WHERE phone_e164 = :p "
                    "AND status = 'scheduled' ORDER BY requested_at LIMIT 1"
                ),
                {"p": phone_e164},
            )
        ).scalar()
        if isinstance(due, datetime):
            values["open_callback"] = spoken_when(due)
        language = clean_name(data.get("language"))
        if language:
            values["preferred_language"] = language[:LANGUAGE_MAX]
    return bounded(values)


__all__ = [
    "ALWAYS_KEYS",
    "MAX_VALUES",
    "MAX_VALUE_CHARS",
    "MEMORY_KEYS",
    "bounded",
    "caller_variables",
    "clean_name",
    "clean_text",
    "spoken_when",
]
