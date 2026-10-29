"""How each Pip answer went, and the asker's thumbs (D-937, migration `c9e4a7d2f15b`).

Three jobs, all small:

* `AnswerCapture` watches the events of one run as the ask route streams them and keeps the
  few facts the live success scores need: tool NAMES and their outcomes, the ids of the
  immediate actions executed, the confirm card proposed, whether a screen was opened or a
  job started, the leg that answered, and two timings. It never keeps text.
* `record_answer` / `record_refusal` write that as one row per answer, keyed by the ANSWER
  turn id the asking device minted, beside the transcript row in the same transaction.
* `record_vote` stores the asker's thumbs on that row, and `votes_for` reads them back for
  the conversation page.

Timings come from this process's monotonic clock, started when the route begins the run
(after the gate), so "time to first token" is what the person waited after the question was
admitted, and "total" ends at the last event of the run.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Final, Literal, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.copilot.memory import redacted_content
from apps.api.copilot.models import MAX_VOTE_NOTE
from apps.api.copilot.schemas import CopilotVote, CopilotVoteReason
from apps.api.copilot.service import CopilotEvent, CopilotSpend
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7

QualityRealm = Literal["client", "admin"]
GateRefusal = Literal["fair_use", "consent", "paused"]

#: Problem codes the ask routes' gates raise, and the refusal each is scored as. Any other
#: gate refusal (a malformed screen, a missing file) is about the request, not about Pip.
GATE_REFUSAL_CODES: Final[Mapping[str, GateRefusal]] = {
    "copilot_daily_limit_reached": "fair_use",
    "copilot_consent_required": "consent",
    "ai_paused_platform_wide": "paused",
    "admin_ai_paused_platform_wide": "paused",
}


@dataclass(slots=True)
class AnswerCapture:
    """The scoring facts of one run, collected from its events. Never text."""

    started: float = field(default_factory=time.monotonic)
    first_token_ms: int | None = None
    total_ms: int | None = None
    tools: list[str] = field(default_factory=list)
    failed_tools: list[str] = field(default_factory=list)
    refused_tools: list[str] = field(default_factory=list)
    action_ids: list[UUID] = field(default_factory=list)
    proposed_tool: str | None = None
    navigated: bool = False
    job_started: bool = False
    spends: list[CopilotSpend] = field(default_factory=list)

    def _elapsed_ms(self) -> int:
        return max(0, int((time.monotonic() - self.started) * 1000))

    def observe(self, event: CopilotEvent) -> None:
        """Note one streamed event. Cheap and never raises: it sits inside the stream."""
        if event.text is not None and self.first_token_ms is None and event.text.strip():
            self.first_token_ms = self._elapsed_ms()
        if event.step is not None and event.step.status != "running":
            name = event.step.tool[:80]
            if name not in self.tools:
                self.tools.append(name)
            if event.step.status == "failed" and name not in self.failed_tools:
                self.failed_tools.append(name)
            if event.step.status == "refused" and name not in self.refused_tools:
                self.refused_tools.append(name)
        if event.action is not None and event.action.action_id:
            with contextlib.suppress(ValueError):
                self.action_ids.append(UUID(event.action.action_id))
        if event.proposal is not None:
            self.proposed_tool = event.proposal.tool[:80]
            if self.first_token_ms is None:
                self.first_token_ms = self._elapsed_ms()
        if event.navigate is not None:
            self.navigated = True
        if event.job is not None:
            self.job_started = True
        if event.spend is not None:
            self.spends.append(event.spend)

    def finish(self) -> None:
        """Stop the total clock. Idempotent: the first call wins."""
        if self.total_ms is None:
            self.total_ms = self._elapsed_ms()

    @property
    def provider(self) -> str | None:
        return self.spends[-1].capability.provider if self.spends else None

    @property
    def fell_back(self) -> bool:
        """Another leg than the account's own answered: a disclosed fallback, or a first leg
        that died and was replaced within the run."""
        if not self.spends:
            return False
        return len(self.spends) > 1 or self.spends[-1].capability.fallback_reason is not None


_CLIENT_INSERT: Final = """
INSERT INTO copilot_answer_outcomes (
    id, tenant_id, user_id, turn_id, tools, failed_tools, refused_tools, action_ids,
    proposed_tool, navigated, job_started, provider, fell_back, first_token_ms, total_ms,
    completed, refusal
) VALUES (
    :id, :tenant_id, :owner, :turn_id, :tools, :failed_tools, :refused_tools, :action_ids,
    :proposed_tool, :navigated, :job_started, :provider, :fell_back, :first_token_ms,
    :total_ms, :completed, :refusal
) ON CONFLICT (turn_id) DO NOTHING
"""

_ADMIN_INSERT: Final = """
INSERT INTO admin_copilot_answer_outcomes (
    id, admin_user_id, viewing_tenant_id, turn_id, tools, failed_tools, refused_tools,
    action_ids, proposed_tool, navigated, job_started, provider, fell_back, first_token_ms,
    total_ms, completed, refusal
) VALUES (
    :id, :owner, :tenant_id, :turn_id, :tools, :failed_tools, :refused_tools, :action_ids,
    :proposed_tool, :navigated, :job_started, :provider, :fell_back, :first_token_ms,
    :total_ms, :completed, :refusal
) ON CONFLICT (turn_id) DO NOTHING
"""


def _insert_sql(realm: QualityRealm) -> str:
    return _CLIENT_INSERT if realm == "client" else _ADMIN_INSERT


async def record_answer(
    session: AsyncSession,
    *,
    realm: QualityRealm,
    turn_id: UUID,
    owner_id: UUID,
    tenant_id: UUID | None,
    capture: AnswerCapture,
    completed: bool,
) -> None:
    """One row for one answered question. A repeat for the same turn writes nothing."""
    capture.finish()
    await session.execute(
        text(_insert_sql(realm)),
        {
            "id": uuid7(),
            "tenant_id": tenant_id,
            "owner": owner_id,
            "turn_id": turn_id,
            "tools": capture.tools,
            "failed_tools": capture.failed_tools,
            "refused_tools": capture.refused_tools,
            "action_ids": capture.action_ids,
            "proposed_tool": capture.proposed_tool,
            "navigated": capture.navigated,
            "job_started": capture.job_started,
            "provider": (capture.provider or "")[:40] or None,
            "fell_back": capture.fell_back,
            "first_token_ms": capture.first_token_ms,
            "total_ms": capture.total_ms,
            "completed": completed,
            "refusal": None,
        },
    )


async def record_refusal(
    session: AsyncSession,
    *,
    realm: QualityRealm,
    turn_id: UUID,
    owner_id: UUID,
    tenant_id: UUID | None,
    refusal: GateRefusal,
) -> None:
    """One row for a question the gate refused: no tools, no timings, never votable."""
    await session.execute(
        text(_insert_sql(realm)),
        {
            "id": uuid7(),
            "tenant_id": tenant_id,
            "owner": owner_id,
            "turn_id": turn_id,
            "tools": [],
            "failed_tools": [],
            "refused_tools": [],
            "action_ids": [],
            "proposed_tool": None,
            "navigated": False,
            "job_started": False,
            "provider": None,
            "fell_back": False,
            "first_token_ms": None,
            "total_ms": None,
            "completed": False,
            "refusal": refusal,
        },
    )


def gate_refusal_of(problem: ProblemError) -> GateRefusal | None:
    """The scored refusal a gate's problem stands for, or None when it is not one."""
    return GATE_REFUSAL_CODES.get(problem.code)


_CLIENT_VOTE: Final = """
UPDATE copilot_answer_outcomes
   SET vote = CAST(:vote AS varchar), vote_reason = :reason, vote_note = :note,
       voted_at = CASE WHEN CAST(:vote AS varchar) IS NULL THEN NULL ELSE now() END,
       updated_at = now()
 WHERE turn_id = :turn_id AND user_id = :owner AND refusal IS NULL
RETURNING vote, vote_reason
"""

_ADMIN_VOTE: Final = """
UPDATE admin_copilot_answer_outcomes
   SET vote = CAST(:vote AS varchar), vote_reason = :reason, vote_note = :note,
       voted_at = CASE WHEN CAST(:vote AS varchar) IS NULL THEN NULL ELSE now() END,
       updated_at = now()
 WHERE turn_id = :turn_id AND admin_user_id = :owner AND refusal IS NULL
RETURNING vote, vote_reason
"""


@dataclass(frozen=True, slots=True)
class StoredVote:
    vote: CopilotVote | None
    reason: CopilotVoteReason | None


async def record_vote(
    session: AsyncSession,
    *,
    realm: QualityRealm,
    turn_id: UUID,
    owner_id: UUID,
    vote: str | None,
    reason: str | None,
    note: str | None,
) -> StoredVote:
    """Set, change or take back the asker's thumbs on one answer.

    Only the person who asked can rate an answer: the row is matched on its owner, so
    another person's turn id, a question's id and a refused question all read as not found.
    `reason` and `note` are dropped with the vote they explained.
    """
    stored_reason = reason if vote == "down" else None
    stored_note = None
    if stored_reason == "other" and note:
        stored_note = redacted_content(note)[:MAX_VOTE_NOTE] or None
    row = (
        await session.execute(
            text(_CLIENT_VOTE if realm == "client" else _ADMIN_VOTE),
            {
                "vote": vote,
                "reason": stored_reason,
                "note": stored_note,
                "turn_id": turn_id,
                "owner": owner_id,
            },
        )
    ).first()
    if row is None:
        raise ProblemError(
            kind="not_found",
            code="copilot_answer_not_found",
            title="That answer can't be rated",
            detail="It is not one of your answers, or it was a question that was not answered.",
            remediation="Rate an answer from your own conversation.",
        )
    return StoredVote(
        vote=cast("CopilotVote | None", row[0]), reason=cast("CopilotVoteReason | None", row[1])
    )


_CLIENT_VOTES_FOR: Final = """
SELECT turn_id, vote, vote_reason FROM copilot_answer_outcomes
 WHERE user_id = :owner AND turn_id = ANY(:ids) AND vote IS NOT NULL
"""

_ADMIN_VOTES_FOR: Final = """
SELECT turn_id, vote, vote_reason FROM admin_copilot_answer_outcomes
 WHERE admin_user_id = :owner AND turn_id = ANY(:ids) AND vote IS NOT NULL
"""


async def votes_for(
    session: AsyncSession, *, realm: QualityRealm, owner_id: UUID, turn_ids: Iterable[UUID]
) -> dict[UUID, StoredVote]:
    """The asker's votes on these turns (a page of their conversation), by turn id."""
    ids = list(turn_ids)
    if not ids:
        return {}
    rows = (
        await session.execute(
            text(_CLIENT_VOTES_FOR if realm == "client" else _ADMIN_VOTES_FOR),
            {"owner": owner_id, "ids": ids},
        )
    ).all()
    return {
        UUID(str(row[0])): StoredVote(
            vote=cast("CopilotVote | None", row[1]),
            reason=cast("CopilotVoteReason | None", row[2]),
        )
        for row in rows
    }


__all__ = [
    "GATE_REFUSAL_CODES",
    "AnswerCapture",
    "GateRefusal",
    "QualityRealm",
    "StoredVote",
    "gate_refusal_of",
    "record_answer",
    "record_refusal",
    "record_vote",
    "votes_for",
]
