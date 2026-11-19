"""The account's two call-notice switches, as every reader takes them (D-1021).

Founder, 19 Nov 2026: "AI notice is per client account because all the calls inbound and
outbound made from the client numbers or to the client numbers should actually have a single
switch of ai and recording notices but the sentences spoken based on the call is inbound or
outbound". So whether a call opens by saying it is an AI, and that it is recorded, is
`organizations.notice_ai_enabled` / `notice_recording_enabled`, one pair for the account; the
words are each opening's own (inbound opening, placed-call opening, a campaign's opening).

The fragments below are correlated on an `agents` row aliased `a`, so every statement that
builds an agent's posture (publish, read-back, drift sweep, dial gate, opening weaving) reads
the switch in the same statement as the rest of the row. An organization row RLS hides reads
as ON: a posture built without its account must not be the one that stays silent.

The truthful answer to a caller who asks is not here and no switch reaches it (hard rule 5).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

#: The account's AI-notice switch, for the agent row `a`.
AI_NOTICE_SQL: Final = (
    "COALESCE((SELECT o_n.notice_ai_enabled FROM organizations o_n "
    "WHERE o_n.id = a.tenant_id), true)"
)
#: The account's recording-notice switch, for the agent row `a`.
RECORDING_NOTICE_SQL: Final = (
    "COALESCE((SELECT o_n.notice_recording_enabled FROM organizations o_n "
    "WHERE o_n.id = a.tenant_id), true)"
)


@dataclass(frozen=True, slots=True)
class AccountNotices:
    ai: bool
    recording: bool


async def read_account_notices(
    session: AsyncSession, *, tenant_id: UUID | None = None, for_update: bool = False
) -> AccountNotices:
    """The account's two switches. `tenant_id` None reads the session's own account, the one
    organization row RLS shows it. `for_update` takes the row lock a writer holds to commit."""
    row = (
        await session.execute(
            text(
                "SELECT notice_ai_enabled, notice_recording_enabled FROM organizations "
                "WHERE (CAST(:tid AS uuid) IS NULL OR id = CAST(:tid AS uuid))"
                + (" FOR UPDATE" if for_update else "")
            ),
            {"tid": tenant_id},
        )
    ).first()
    if row is None:
        return AccountNotices(ai=True, recording=True)
    return AccountNotices(ai=bool(row[0]), recording=bool(row[1]))


__all__ = ["AI_NOTICE_SQL", "RECORDING_NOTICE_SQL", "AccountNotices", "read_account_notices"]
