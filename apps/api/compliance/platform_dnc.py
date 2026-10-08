"""A dial the voice platform refused for ITS do-not-call list, not ours (D-691).

ThinnestAI keeps one do-not-call list per WORKSPACE and every client shares our workspace, so
a person who opted out on one client's call is refused on every client's (`403` with code
`do_not_call` or `opted_out`, VERIFIED-VENDOR-DOCS `thinnest-findings/mirror/snapshots/
2026-10-08/pages/api-reference/errors.md:113-114`). The founder's decision (8 Oct 2026) is
that OUR per-client list decides who is dialled, so such a refusal is recorded plainly as
what it is — "blocked by the voice platform's do-not-call list" — and the number is NOT
added to the refused client's own list: that client was never asked.

The adapter reports the refusal as `engine_recipient_opted_out`; this module decides which
of the two it is by asking our list, with the dispatch gate's own predicate. A number on the
client's list (or the global one) that still reached the vendor raced a suppression written
after the gate read it, and keeps the adapter's code.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError

#: The refusal code a dial gets when only the voice platform's shared list blocks it.
PLATFORM_DNC_BLOCK_CODE: Final = "engine_platform_dnc_block"

#: The adapter's code for a person the platform will not call (`engine/vendor_http.py`).
#: Spelled here rather than imported: business code does not read the adapter ladder's
#: module for a constant it only compares against, and `tests/platform_dnc_test.py` holds
#: the two equal.
RECIPIENT_OPTED_OUT: Final = "engine_recipient_opted_out"

#: Both engine refusals that are facts about the person rather than the account: a batch
#: dialler settles the contact for either instead of re-asking every tick.
ENGINE_PERSON_REFUSALS: Final = frozenset({RECIPIENT_OPTED_OUT, PLATFORM_DNC_BLOCK_CODE})

_ON_OUR_LIST: Final = (
    "SELECT 1 FROM dnc_list WHERE phone_e164 = :phone "
    "AND (tenant_id = :tid OR tenant_id IS NULL) LIMIT 1"
)


def platform_dnc_block_error() -> ProblemError:
    """`engine_platform_dnc_block`: refused before anything rang, about one person."""
    return ProblemError(
        kind="business_rule",
        code=PLATFORM_DNC_BLOCK_CODE,
        title="Blocked by the voice platform's do-not-call list",
        detail=(
            "This number is on the voice platform's do-not-call list, so the call was not "
            "placed. It is not on this account's own do-not-call list."
        ),
        remediation=(
            "Remove the number from the campaign or lead list. Ask us if this person has "
            "asked this business to call them."
        ),
    )


async def platform_dnc_refusal(
    session: AsyncSession, exc: BaseException, *, tenant_id: UUID, phone_e164: str
) -> ProblemError | None:
    """The refusal to raise instead of `exc`, or None to keep `exc` as it is."""
    if not isinstance(exc, ProblemError) or exc.code != RECIPIENT_OPTED_OUT:
        return None
    ours = (
        await session.execute(text(_ON_OUR_LIST), {"phone": phone_e164, "tid": tenant_id})
    ).first()
    return None if ours is not None else platform_dnc_block_error()


__all__ = [
    "ENGINE_PERSON_REFUSALS",
    "PLATFORM_DNC_BLOCK_CODE",
    "RECIPIENT_OPTED_OUT",
    "platform_dnc_block_error",
    "platform_dnc_refusal",
]
