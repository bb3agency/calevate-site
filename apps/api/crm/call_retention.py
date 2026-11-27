"""How long this account keeps call recordings and transcripts, for the Call logs line (W12.9).

Read from the account's own `retention_policies` rows, never from
`compliance/retention_defaults`: an account's periods may differ from the defaults, and the
line must say what `workers/retention` will actually do to these calls. A category with no
row reads as None and the screen says nothing about it rather than guess.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class CallRetention:
    recording_days: int | None
    transcript_days: int | None


async def call_retention(session: AsyncSession) -> CallRetention:
    rows = (
        await session.execute(
            text(
                "SELECT data_category, ttl_days FROM retention_policies "
                "WHERE data_category IN ('recording', 'transcript')"
            )
        )
    ).all()
    days = {str(r[0]): int(r[1]) for r in rows}
    return CallRetention(
        recording_days=days.get("recording"), transcript_days=days.get("transcript")
    )


__all__ = ["CallRetention", "call_retention"]
