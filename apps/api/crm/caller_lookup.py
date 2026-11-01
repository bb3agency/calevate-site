"""What an agent may know about an inbound caller before it answers (D-716).

The answer to the voice platform's caller lookup (`worker/engine_lookups.py`): a handful of
short values that fill `{{name}}` and the like in the agent's greeting and instructions.
Read from THIS tenant's records only, with reads only and no network calls, because the
platform waits two seconds and the caller hears ringing meanwhile.

WHAT IS SENT: `name`, `first_name` and `lead_name` (letters and spaces only), when the
number belongs to a lead. The platform uses a value only where a `{{key}}` names it in the
greeting or the instructions (`channels/voice.md:455-460`, 29 Oct 2026 snapshot); `name` and
`first_name` are the platform's own placeholders (same page, :407) and `lead_name` is the
script's merge field (`calevate_shared.call_script.STANDARD_VARIABLES`). Founder decision 15
(10 Oct 2026) also sent `product_interest`, `caller_known`, `callback_allowed`,
`last_call_topic`, `open_callback` and `preferred_language`; no prompt, script or greeting
ever named them, so they filled nothing and are no longer read. One comes back as a key here
together with the `{{key}}` that uses it.

NEVER SENT: the number, email, address, amounts, notes, transcript text or any other field
of the lead. The lookup is answered on the number the call CLAIMS to come from (the vendor's
own warning: "treat what it is sent like caller ID"), so nothing here is anything a caller
spoofing a number should be able to learn beyond a name.

Limits are the vendor's: at most 20 values, each at most 150 characters, scalars only
(update-agent `callStartUrl`, read 10 Oct 2026).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

MAX_VALUES: Final = 20
MAX_VALUE_CHARS: Final = 150
NAME_MAX: Final = 40

_SPACES = re.compile(r"\s+")


def clean_name(raw: Any) -> str | None:
    """Letters and spaces only, any script, at most `NAME_MAX` characters."""
    if not isinstance(raw, str):
        return None
    kept = "".join(ch if unicodedata.category(ch)[0] in ("L", "M") else " " for ch in raw)
    name = _SPACES.sub(" ", kept).strip()[:NAME_MAX].strip()
    return name or None


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
    session: AsyncSession, *, agent_id: UUID, phone_e164: str
) -> dict[str, str]:
    """The lookup answer for `phone_e164` calling `agent_id`, from the records of the
    session's tenant (RLS scopes the read)."""
    lead = (
        await session.execute(
            text(
                "SELECT name FROM leads WHERE phone_e164 = :p AND deleted_at IS NULL "
                # The lead this agent holds first, then the newest of any other agent's.
                "ORDER BY (agent_id = :aid) DESC, updated_at DESC LIMIT 1"
            ),
            {"p": phone_e164, "aid": agent_id},
        )
    ).scalar()
    name = clean_name(lead)
    if not name:
        return {}
    return bounded({"name": name, "lead_name": name, "first_name": name.split(" ")[0]})


__all__ = [
    "MAX_VALUES",
    "MAX_VALUE_CHARS",
    "bounded",
    "caller_variables",
    "clean_name",
]
