"""Where a practice test's script fix goes (D-1017, following D-1005).

An agent has no script of its own to edit (D-997, D-1000, D-1005): what a call says is the
script of the Inbound line or campaign it is on. So a script fix "Improve my agent" works out
from a failed practice test is written exactly as the healer writes a fix of a real call's
mistake (`agents/mistake_fixes.request_holder_fix`): as a Pip draft on one of that agent's
lines or campaigns (`script_proposal`, the shape `campaigns.workspace.read_script_proposal`
reads), which the owner keeps or discards on that line's or campaign's page. Nothing here
puts a script live. Facts the same round proposes still go to the business's knowledge from
the Training tab, unchanged.

Which holder: the agent's lines and open campaigns that have a script (`fix_holders`). One
of them is used without asking; with several the owner picks one in the Training tab (or
tells Pip); with none there is nowhere to write a script fix, and the owner is offered a line.

The draft is written whole and ready in the transaction that stores the round, rather than
queued like the healer's (`draft_mistake_fix`): the improver's answer is already the edit
list, each validated by `script_edits.apply_edit`, so a second model leg would only spend
the allowance again. An edit of an opening line is left out: a line's opening says the AI
and recording notices in its own words (D-971), which only their own writer changes
(`mistake_fixes.PROTECTED_PARTS`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Literal
from uuid import UUID

from calevate_shared.call_script import CallScript, upgrade_to_v2
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.jobs import MAX_JOBS_LISTED, OPEN_CAMPAIGN_STATUSES
from apps.api.agents.mistake_fixes import (
    DRAFT_OPEN_CODE,
    PROTECTED_PARTS,
    Holder,
    HolderKind,
    holder_table,
    read_holder,
)
from apps.api.agents.script_edits import ScriptEdit, apply_edits
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7

#: Refused when the agent has several lines or campaigns with a script and none was named.
CHOOSE_HOLDER_CODE: Final = "agent_tests_choose_holder"
#: Refused when the named line or campaign is not one of this agent's with a script.
UNKNOWN_HOLDER_CODE: Final = "agent_tests_unknown_holder"

#: What the holder's draft says it fixes, after "Written to fix a mistake on calls:" on the
#: line's and campaign's review.
_ONE_TEST: Final = "the practice test “{title}”"
_SOME_TESTS: Final = "{n} practice tests this agent failed"

_HOLDERS_SQL: Final = (
    "SELECT 'inbound_line' AS kind, id, name, created_at FROM inbound_lines "
    "WHERE agent_id = :aid AND archived_at IS NULL AND script IS NOT NULL "
    "UNION ALL SELECT 'campaign', id, name, created_at FROM campaigns "
    "WHERE agent_id = :aid AND archived_at IS NULL AND script IS NOT NULL "
    "AND status = ANY(:open) ORDER BY kind DESC, created_at, id LIMIT :limit"
)
#: The most holders offered: an agent's lines and campaigns as its jobs list shows them.
MAX_FIX_HOLDERS: Final = 2 * MAX_JOBS_LISTED

#: How a round's script fixes ended up, for the Training tab:
#: `drafted` on the holder; `draft_open`, not written because a Pip draft already waits
#: there; `no_holder`, the agent has no line or campaign with a script; `choose`, it has
#: several and none was picked; `none`, the round had no script fix to write.
ScriptFixes = Literal["drafted", "draft_open", "no_holder", "choose", "none"]


@dataclass(frozen=True, slots=True)
class FixHolder:
    """One of the agent's lines or open campaigns that has a script."""

    kind: HolderKind
    id: UUID
    name: str

    @property
    def holder(self) -> Holder:
        return Holder(self.kind, self.id)

    def as_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "id": str(self.id), "name": self.name}


async def fix_holders(session: AsyncSession, agent_id: UUID) -> list[FixHolder]:
    """The agent's Inbound lines (oldest first), then its open campaigns, that have a script.
    Under the caller's tenant session: both tables are FORCE-RLS'd."""
    rows = (
        await session.execute(
            text(_HOLDERS_SQL),
            {"aid": agent_id, "open": list(OPEN_CAMPAIGN_STATUSES), "limit": MAX_FIX_HOLDERS},
        )
    ).all()
    return [FixHolder(kind=row[0], id=row[1], name=str(row[2] or "")) for row in rows]


@dataclass(frozen=True, slots=True)
class Choice:
    """Where this round's script fixes go: `holder`, or why there is none."""

    holder: FixHolder | None
    outcome: ScriptFixes
    holders: tuple[FixHolder, ...]


async def choose_holder(
    session: AsyncSession, agent_id: UUID, requested: Holder | None, *, must_choose: bool
) -> Choice:
    """The holder a round's script fixes go to. A named one must be one of the agent's with a
    script. With several and none named, `must_choose` refuses (the owner or Pip is asked to
    pick); otherwise the round writes no script fix and says why (`choose`)."""
    holders = tuple(await fix_holders(session, agent_id))
    if requested is not None:
        found = next((h for h in holders if h.holder == requested), None)
        if found is None:
            raise ProblemError.business_rule(
                UNKNOWN_HOLDER_CODE,
                "That Inbound line or campaign does not use this agent, or has no script yet.",
                remediation="Pick one of this agent's Inbound lines or campaigns.",
            )
        return Choice(found, "drafted", holders)
    if len(holders) == 1:
        return Choice(holders[0], "drafted", holders)
    if not holders:
        return Choice(None, "no_holder", holders)
    if must_choose:
        raise ProblemError.business_rule(
            CHOOSE_HOLDER_CODE,
            "This agent works on more than one Inbound line or campaign.",
            remediation="Choose which one the script fixes go to.",
        )
    return Choice(None, "choose", holders)


def holder_base(script: CallScript | None) -> CallScript:
    """The script a round's edits are made against: the holder's, in the v2 steps the
    review opens it in."""
    return upgrade_to_v2(script if script is not None else CallScript())


def writable_edits(edits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The edits a holder's draft may carry: every one but an opening-line edit."""
    return [
        e for e in edits if not (e.get("op") == "set_part" and e.get("part") in PROTECTED_PARTS)
    ]


def _fixes_label(titles: list[str]) -> str:
    named = [t for t in titles if t]
    if len(named) == 1:
        return _ONE_TEST.format(title=named[0])
    return _SOME_TESTS.format(n=max(len(titles), 1))


def _why(edits: list[ScriptEdit]) -> dict[str, str]:
    """Pip's reason per part it wrote, keyed as the review keys parts (D-1004)."""
    out: dict[str, str] = {}
    for edit in edits:
        if not edit.why:
            continue
        if edit.op == "set_step" and edit.step_id:
            out[f"stages.{edit.step_id}"] = edit.why
        elif edit.op == "set_part" and edit.part:
            out[edit.part] = edit.why
    return out


async def write_holder_draft(
    session: AsyncSession,
    *,
    holder: Holder,
    edits: list[dict[str, Any]],
    titles: list[str],
    disclosure: str | None,
    requested_by: UUID | None,
) -> UUID | None:
    """Write the edits onto the holder's current script as its Pip draft, ready for review,
    in the caller's transaction; the draft's id, or None when no edit still fits. Refused
    (`mistake_fix_draft_open`, 409) while a draft from Pip is being written or waits there:
    a fix never replaces a draft the owner has not seen."""
    current = await read_holder(session, holder, lock=True)
    if current is None:
        raise ProblemError.not_found(
            "Inbound line" if holder.kind == "inbound_line" else "Campaign"
        )
    if current.proposal is not None and current.proposal.status in ("drafting", "ready"):
        raise ProblemError.conflict(
            DRAFT_OPEN_CODE,
            f"A draft from Pip is already waiting on “{current.name}”.",
            remediation="Keep or discard it there, then ask for the fixes again.",
        )
    base = holder_base(current.script)
    kept = [ScriptEdit.of(e) for e in writable_edits(edits)]
    script, applied, _rejected = apply_edits(base, kept)
    if not applied:
        return None
    proposal_id = uuid7()
    now = datetime.now(UTC).isoformat()
    record: dict[str, Any] = {
        "id": str(proposal_id),
        "status": "ready",
        "requested_at": now,
        "requested_by": None if requested_by is None else str(requested_by),
        "base_script": base.model_dump(mode="json"),
        "script": script.model_dump(mode="json"),
        "fix_label": _fixes_label(titles),
        "why": _why([e for e in kept if e.id in applied]),
        "disclosure": disclosure,
        "left_out": [],
        "from_tests": True,
    }
    await session.execute(
        text(
            f"UPDATE {holder_table(holder.kind)} SET script_proposal = "
            "CAST(:p AS jsonb) WHERE id = :h"
        ),
        {"p": json.dumps(record), "h": holder.id},
    )
    return proposal_id


__all__ = [
    "CHOOSE_HOLDER_CODE",
    "MAX_FIX_HOLDERS",
    "UNKNOWN_HOLDER_CODE",
    "Choice",
    "FixHolder",
    "ScriptFixes",
    "choose_holder",
    "fix_holders",
    "holder_base",
    "writable_edits",
    "write_holder_draft",
]
