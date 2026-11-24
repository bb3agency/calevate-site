"""The Improve tab's one-press moves and Pip's automatic ones (D-992 item 8).

* Best hours: narrow the calling hours to the block people answer in, inside the platform
  window, with Undo; Pip does it on its own once enough is measured when the owner has
  turned `best_hours_auto` on.
* Smarter retries: the `spread` switch of `retry_policy` (`call_timing.spread_retry_at`).
* The opening test: decided by `learning.opening_verdict`; the stronger opening becomes the
  campaign's opening through the ordinary save (`workspace.save_script`), so the notices are
  said as with any opening the owner saves (hard rule 5), and Undo puts the old one back.
* Practice comparison: for a list too small to test on calls, both openings through the
  practice checks (`agents/turn_checks.turn_problems`), as the first thing said on a call.

Pip's moves run from `workers/campaign_improve`, queued after a campaign's calls end.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from typing import Any, Final, Literal
from uuid import UUID

from calevate_shared.call_script import CallScript
from calevate_shared.calling_window import DEFAULT_WINDOW
from calevate_shared.opening_notices import OpeningNotices
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.turn_checks import TurnProblem, turn_problems
from apps.api.campaigns import learning, workspace
from apps.api.campaigns.call_timing import Block
from apps.api.campaigns.service import validated_window
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.reliability.service import enqueue_outbox_once

log = get_logger(__name__)

IMPROVE_JOB: Final = "campaign_improve"
#: One automatic check per campaign per this many seconds of calls ending.
IMPROVE_BUCKET_S: Final = 600
#: How long an automatic change stays on the bell.
NOTICE_DAYS: Final = 14

AppliedBy = Literal["owner", "pip"]


async def _row(session: AsyncSession, campaign_id: UUID, *, lock: bool = False) -> Any:
    row = (
        await session.execute(
            text(
                "SELECT c.id, c.tenant_id, c.agent_id, c.status, c.calling_hours, c.retry_policy, "
                "c.best_hours_auto, c.best_hours_applied, c.opening_b, c.opening_test_result, "
                "c.script, COALESCE(c.settings_overrides->>'language_primary', "
                "a.language_primary) AS language FROM campaigns c "
                "JOIN agents a ON a.id = c.agent_id WHERE c.id = :cid AND c.archived_at IS NULL"
                + (" FOR UPDATE OF c" if lock else "")
            ),
            {"cid": campaign_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Campaign")
    return row


def _object(value: object) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


# --- Best hours ---------------------------------------------------------------------------


def clamped_window(block: Block, calling_hours: dict[str, Any] | None) -> dict[str, str] | None:
    """The block as calling hours, cut to the platform window and to the campaign's own
    hours, so applying it can only ever narrow when the campaign calls. None when nothing
    of it is left."""
    low, high = DEFAULT_WINDOW
    start, end = max(block.start, low), min(block.end, high)
    own = _object(calling_hours)
    if own is not None:
        try:
            start = max(start, datetime.strptime(str(own["start"]), "%H:%M").time())
            end = min(end, datetime.strptime(str(own["end"]), "%H:%M").time())
        except (KeyError, TypeError, ValueError):
            return None
    if start >= end:
        return None
    return validated_window({"start": _hhmm(start), "end": _hhmm(end)})


def _hhmm(moment: time) -> str:
    return moment.strftime("%H:%M")


async def read_best_hours(session: AsyncSession, campaign_id: UUID) -> learning.BestHours:
    row = await _row(session, campaign_id)
    rates = await learning.answer_rate_by_hour(session, campaign_id)
    return learning.best_block(rates, _object(row.calling_hours))


def applied_now(row: Any) -> dict[str, Any] | None:
    """The applied block while the calling hours still are it; a later edit of the hours
    ends it (nothing to undo any more)."""
    applied = _object(row.best_hours_applied)
    if applied is None or _object(row.calling_hours) != applied.get("block"):
        return None
    return applied


async def apply_best_hours(
    session: AsyncSession, campaign_id: UUID, *, by: AppliedBy
) -> dict[str, Any]:
    """Narrow the calling hours to the best block. Refused until it is measured."""
    row = await _row(session, campaign_id, lock=True)
    rates = await learning.answer_rate_by_hour(session, campaign_id)
    verdict = learning.best_block(rates, _object(row.calling_hours))
    window = (
        clamped_window(verdict.best.block, _object(row.calling_hours))
        if verdict.best is not None
        else None
    )
    if window is None:
        raise ProblemError.business_rule(
            "campaign_best_hours_not_ready",
            "Not enough calls yet to say which hours are best.",
        )
    current = applied_now(row)
    if current is not None and current.get("block") == window:
        return current
    applied = {
        "block": window,
        "before": _object(row.calling_hours),
        "by": by,
        "at": datetime.now(UTC).isoformat(),
    }
    await session.execute(
        text(
            "UPDATE campaigns SET calling_hours = CAST(:w AS jsonb), "
            "best_hours_applied = CAST(:a AS jsonb), updated_at = now() WHERE id = :cid"
        ),
        {"w": _json(window), "a": _json(applied), "cid": campaign_id},
    )
    log.info("campaign_best_hours_applied", extra={"campaign_id": str(campaign_id), "by": by})
    return applied


async def undo_best_hours(session: AsyncSession, campaign_id: UUID) -> None:
    """Put the calling hours back. Pip's own change undone also turns Pip's switch off, or
    the next check would make it again."""
    row = await _row(session, campaign_id, lock=True)
    applied = applied_now(row)
    if applied is None:
        raise ProblemError.business_rule(
            "campaign_best_hours_nothing_to_undo",
            "The calling hours have changed since, so there is nothing to put back here.",
            remediation="Change the hours in How it calls.",
        )
    await session.execute(
        text(
            "UPDATE campaigns SET calling_hours = CAST(:before AS jsonb), "
            "best_hours_applied = NULL, "
            "best_hours_auto = best_hours_auto AND CAST(:keep AS boolean), "
            "updated_at = now() WHERE id = :cid"
        ),
        {
            "before": None if applied.get("before") is None else _json(applied["before"]),
            "keep": applied.get("by") != "pip",
            "cid": campaign_id,
        },
    )


async def set_best_hours_auto(session: AsyncSession, campaign_id: UUID, *, on: bool) -> None:
    await _row(session, campaign_id, lock=True)
    await session.execute(
        text("UPDATE campaigns SET best_hours_auto = :on, updated_at = now() WHERE id = :cid"),
        {"on": on, "cid": campaign_id},
    )


async def set_retry_spread(session: AsyncSession, campaign_id: UUID, *, on: bool) -> None:
    """Switch the time-of-day spreading of retries. The tries and gaps stay as they are."""
    await _row(session, campaign_id, lock=True)
    await session.execute(
        text(
            "UPDATE campaigns SET retry_policy = COALESCE(retry_policy, '{}'::jsonb) "
            "|| jsonb_build_object('spread', CAST(:on AS boolean)), updated_at = now() "
            "WHERE id = :cid"
        ),
        {"on": on, "cid": campaign_id},
    )


# --- The opening test ---------------------------------------------------------------------


def _counts(result: learning.OpeningResult) -> dict[str, int]:
    return {
        "people": result.people,
        "answered": result.answered,
        "stayed": result.stayed,
        "goal_reached": result.goal_reached,
    }


async def decide_opening(session: AsyncSession, campaign_id: UUID) -> bool:
    """Settle a running opening test once `learning.opening_verdict` names a winner. True
    when the campaign's script changed, so the caller puts it live."""
    row = await _row(session, campaign_id, lock=True)
    second = str(row.opening_b or "").strip()
    if not second:
        return False
    results = await learning.opening_results(session, campaign_id)
    verdict = learning.opening_verdict(results)
    if verdict.winner is None:
        return False
    outcome: dict[str, Any] = {
        "winner": verdict.winner,
        "chance_b_better": round(verdict.chance_b_better, 4),
        "a": _counts(results[0]),
        "b": _counts(results[1]),
        "opening_b": second,
        "at": datetime.now(UTC).isoformat(),
        "applied": False,
    }
    script = CallScript.model_validate(row.script) if isinstance(row.script, dict) else None
    if verdict.winner == "b" and script is not None:
        outcome["before"] = {
            "opening_line": script.opening_line,
            "opening_notices": script.opening_notices.model_dump(),
        }
        # The notices the writer wove belong to the old line; the new one is said with the
        # stored sentences beside it until it says them itself (`engine.join_first_words`).
        await workspace.save_script(
            session,
            campaign_id,
            script.model_copy(update={"opening_line": second, "opening_notices": OpeningNotices()}),
            author="system",
            reason="The second opening line won the test, so it is now the opening.",
        )
        outcome["applied"] = True
    await session.execute(
        text(
            "UPDATE campaigns SET opening_b = NULL, opening_test_result = CAST(:r AS jsonb), "
            "updated_at = now() WHERE id = :cid"
        ),
        {"r": _json(outcome), "cid": campaign_id},
    )
    log.info(
        "campaign_opening_test_decided",
        extra={"campaign_id": str(campaign_id), "winner": verdict.winner},
    )
    return bool(outcome["applied"])


async def undo_opening(
    session: AsyncSession, campaign_id: UUID, *, made_by: UUID | None = None
) -> None:
    """Put back the opening the test's winner replaced, through the same save. The test is
    not started again: it would decide the same way on the same calls."""
    row = await _row(session, campaign_id, lock=True)
    outcome = _object(row.opening_test_result)
    before = _object(outcome.get("before")) if outcome else None
    script = CallScript.model_validate(row.script) if isinstance(row.script, dict) else None
    if (
        outcome is None
        or before is None
        or outcome.get("undone_at")
        or script is None
        or script.opening_line != outcome.get("opening_b")
    ):
        raise ProblemError.business_rule(
            "campaign_opening_nothing_to_undo",
            "The opening has changed since, so there is nothing to put back here.",
            remediation="Change the opening in the script.",
        )
    await workspace.save_script(
        session,
        campaign_id,
        script.model_copy(
            update={
                "opening_line": str(before.get("opening_line") or ""),
                "opening_notices": OpeningNotices.model_validate(
                    before.get("opening_notices") or {}
                ),
            }
        ),
        author="owner",
        made_by=made_by,
        reason="You put back the opening from before the test.",
    )
    outcome["undone_at"] = datetime.now(UTC).isoformat()
    await session.execute(
        text(
            "UPDATE campaigns SET opening_test_result = CAST(:r AS jsonb), updated_at = now() "
            "WHERE id = :cid"
        ),
        {"r": _json(outcome), "cid": campaign_id},
    )


@dataclass(frozen=True)
class PracticeSide:
    line: str
    mistakes: list[TurnProblem] = field(default_factory=list)


@dataclass(frozen=True)
class PracticeComparison:
    own: PracticeSide
    second: PracticeSide
    #: Which has fewer mistakes, or None when they have as many.
    fewer: Literal["a", "b"] | None


def practice_compare(own: str, second: str, *, language: str) -> PracticeComparison:
    """Both openings through the checks the practice conversations run on every reply,
    each read as the first thing said on a call (`caller_said` empty)."""
    a = PracticeSide(own, turn_problems(own, language=language))
    b = PracticeSide(second, turn_problems(second, language=language))
    fewer: Literal["a", "b"] | None = None
    if len(a.mistakes) != len(b.mistakes):
        fewer = "a" if len(a.mistakes) < len(b.mistakes) else "b"
    return PracticeComparison(own=a, second=b, fewer=fewer)


# --- What a re-call draft carries ---------------------------------------------------------


async def redo_hours(
    session: AsyncSession, source_id: UUID, calling_hours: dict[str, Any] | None
) -> dict[str, Any] | None:
    """The source's best block when it is measured, else the source's own hours."""
    verdict = learning.best_block(
        await learning.answer_rate_by_hour(session, source_id), calling_hours
    )
    if verdict.best is None:
        return calling_hours
    return clamped_window(verdict.best.block, calling_hours) or calling_hours


async def redo_opening(session: AsyncSession, *, source_id: UUID, target_id: UUID) -> None:
    """A re-call draft opens with the stronger opening when the source's test has named one.
    A test the source already settled is in the copied script; one still undecided carries
    on in the draft, among people it has not tried."""
    second = (
        await session.execute(
            text("SELECT opening_b FROM campaigns WHERE id = :cid"), {"cid": source_id}
        )
    ).scalar_one_or_none()
    if not str(second or "").strip():
        return
    verdict = learning.opening_verdict(await learning.opening_results(session, source_id))
    if verdict.winner is None:
        return
    target = await _row(session, target_id, lock=True)
    if verdict.winner == "b" and isinstance(target.script, dict):
        script = CallScript.model_validate(target.script)
        await workspace.save_script(
            session,
            target_id,
            script.model_copy(
                update={"opening_line": str(second).strip(), "opening_notices": OpeningNotices()}
            ),
            author="system",
            reason="This draft opens with the opening line that won the test.",
        )
    await session.execute(
        text("UPDATE campaigns SET opening_b = NULL WHERE id = :cid"), {"cid": target_id}
    )


# --- Pip's automatic moves ----------------------------------------------------------------


@dataclass(frozen=True)
class ImproveRun:
    opening_applied: bool
    hours_applied: bool


async def run_improve(session: AsyncSession, campaign_id: UUID) -> ImproveRun:
    """Decide the opening test, and narrow the hours when Pip may. Each is skipped, never
    refused, while it is not ready."""
    opening = await decide_opening(session, campaign_id)
    row = await _row(session, campaign_id, lock=True)
    hours = False
    if row.best_hours_auto:
        verdict = learning.best_block(
            await learning.answer_rate_by_hour(session, campaign_id), _object(row.calling_hours)
        )
        window = (
            clamped_window(verdict.best.block, _object(row.calling_hours))
            if verdict.best is not None
            else None
        )
        before = applied_now(row)
        if window is not None and (before is None or before.get("block") != window):
            await apply_best_hours(session, campaign_id, by="pip")
            hours = True
    return ImproveRun(opening_applied=opening, hours_applied=hours)


async def queue_improve(session: AsyncSession, *, tenant_id: UUID, campaign_id: UUID) -> bool:
    """Ask for Pip's check after a call ends, at most once per campaign per
    `IMPROVE_BUCKET_S`, and only for a campaign that has something for it to decide."""
    due = (
        await session.execute(
            text(
                "SELECT (opening_b IS NOT NULL AND btrim(opening_b) <> '') OR best_hours_auto "
                "FROM campaigns WHERE id = :cid"
            ),
            {"cid": campaign_id},
        )
    ).scalar_one_or_none()
    if not due:
        return False
    bucket = int(datetime.now(UTC).timestamp()) // IMPROVE_BUCKET_S
    queued = await enqueue_outbox_once(
        session,
        job=IMPROVE_JOB,
        payload={"tenant_id": str(tenant_id), "campaign_id": str(campaign_id)},
        dedupe_key=f"campaign-improve:{campaign_id}:{bucket}",
    )
    return queued is not None


@dataclass(frozen=True)
class ImproveNotice:
    """An automatic change the owner is told about on the bell."""

    id: str
    campaign_id: UUID
    title: str
    detail: str
    occurred_at: datetime


async def recent_notices(session: AsyncSession, *, limit: int) -> list[ImproveNotice]:
    """Opening tests decided, and hours Pip narrowed, in the last `NOTICE_DAYS`."""
    since = datetime.now(UTC) - timedelta(days=NOTICE_DAYS)
    rows = (
        await session.execute(
            text(
                "SELECT id, name, opening_test_result, best_hours_applied FROM campaigns "
                "WHERE archived_at IS NULL AND ("
                "(opening_test_result IS NOT NULL "
                "AND CAST(opening_test_result->>'at' AS timestamptz) >= :since) OR "
                "(best_hours_applied->>'by' = 'pip' "
                "AND CAST(best_hours_applied->>'at' AS timestamptz) >= :since)) "
                "ORDER BY updated_at DESC LIMIT :limit"
            ),
            {"since": since, "limit": limit},
        )
    ).all()
    out: list[ImproveNotice] = []
    for row in rows:
        result = _object(row.opening_test_result)
        if result is not None and datetime.fromisoformat(str(result["at"])) >= since:
            out.append(_opening_notice(row.id, str(row.name), result))
        hours = _object(row.best_hours_applied)
        if hours is not None and hours.get("by") == "pip":
            at = datetime.fromisoformat(str(hours["at"]))
            if at >= since:
                block = hours["block"]
                out.append(
                    ImproveNotice(
                        id=f"hours:{row.id}:{hours['at']}",
                        campaign_id=row.id,
                        title=(
                            f"{row.name}: now calls only {_said(block['start'])} to "
                            f"{_said(block['end'])}"
                        ),
                        detail="Pip narrowed the calling hours to when people answer most. "
                        "Undo it on the Improve tab.",
                        occurred_at=at,
                    )
                )
    return out


def _opening_notice(campaign_id: UUID, name: str, result: dict[str, Any]) -> ImproveNotice:
    if result.get("winner") == "b" and result.get("applied"):
        title = f"{name}: the second opening won"
        detail = "It is now the campaign's opening. Undo it on the Improve tab."
    elif result.get("winner") == "b":
        title = f"{name}: the second opening won"
        detail = "Put it in the script to use it on every call."
    else:
        title = f"{name}: the script's own opening won"
        detail = "The test has ended and every call uses the script's own opening."
    return ImproveNotice(
        id=f"opening:{campaign_id}:{result['at']}",
        campaign_id=campaign_id,
        title=title,
        detail=detail,
        occurred_at=datetime.fromisoformat(str(result["at"])),
    )


def _said(hhmm: str) -> str:
    """An HH:MM time as an owner says it ("6pm"), as the web's `clockWords` does."""
    moment = datetime.strptime(hhmm, "%H:%M").time()
    hour = moment.hour % 12 or 12
    suffix = "am" if moment.hour < 12 else "pm"
    return f"{hour}{suffix}" if moment.minute == 0 else f"{hour}:{moment.minute:02d}{suffix}"


def _json(value: object) -> str:
    return json.dumps(value)


__all__ = [
    "IMPROVE_JOB",
    "ImproveNotice",
    "ImproveRun",
    "PracticeComparison",
    "applied_now",
    "apply_best_hours",
    "clamped_window",
    "decide_opening",
    "practice_compare",
    "queue_improve",
    "read_best_hours",
    "recent_notices",
    "run_improve",
    "set_best_hours_auto",
    "set_retry_spread",
    "undo_best_hours",
    "undo_opening",
]
