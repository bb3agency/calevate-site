"""The owner's go-live guide after the first payment (D-859, founder 23 Oct 2026).

Four steps, each read from the state the rest of the product already keeps, so the guide can
never say something the screens it links to disagree with:

1. **Moving your agents**: `go_live.moves.read_move_progress`.
2. **Verify your business**: the KYC record (`compliance/kyc.read_kyc`).
3. **Get your number**: the account's numbers and the purchase gates
   (`campaigns/engine_number_purchase.purchase_readiness`).
4. **Switch it on**: whether any agent is live; switching one on is the agent's own switch,
   with its own gate reasons.

The guide is owed from the first payment (`go_live_guides`, written by
`billing/first_payment`) until the owner finishes it or puts it aside. Plain words only: no
vendor name (D-679), no money, no personal data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.campaigns.engine_number_purchase import purchase_readiness
from apps.api.compliance.kyc import read_kyc
from apps.api.go_live.moves import MoveProgress, read_move_progress
from apps.api.tenancy.engine_workspace import read_workspace_state

VerifyState = Literal["todo", "in_review", "needs_attention", "done"]
NumberState = Literal["locked", "waiting_approval", "todo", "done"]
SwitchState = Literal["todo", "done"]
GuideStep = Literal["move", "verify", "number", "switch_on", "done"]

_VERIFY_OF_KYC: Final[dict[str, VerifyState]] = {
    "verified": "done",
    "submitted": "in_review",
    "in_review": "in_review",
    "rejected": "needs_attention",
    "expired": "needs_attention",
}


@dataclass(frozen=True, slots=True)
class GuideMarker:
    owed_at: datetime
    finished_at: datetime | None
    dismissed_at: datetime | None

    @property
    def due(self) -> bool:
        return self.finished_at is None and self.dismissed_at is None


@dataclass(frozen=True, slots=True)
class GoLive:
    marker: GuideMarker | None
    move: MoveProgress
    verify: VerifyState
    number: NumberState
    numbers: int
    switch_on: SwitchState
    live_agents: int

    @property
    def current(self) -> GuideStep:
        """The first step not done. The move counts as done once nothing is left to move by
        the owner: a held agent is ours to finish, not theirs."""
        if self.move.state in ("waiting_for_account", "moving"):
            return "move"
        if self.verify != "done":
            return "verify"
        if self.number != "done":
            return "number"
        if self.switch_on != "done":
            return "switch_on"
        return "done"


async def read_marker(session: AsyncSession, *, tenant_id: UUID) -> GuideMarker | None:
    row = (
        await session.execute(
            text(
                "SELECT owed_at, finished_at, dismissed_at FROM go_live_guides "
                "WHERE tenant_id = :tid"
            ),
            {"tid": tenant_id},
        )
    ).first()
    return (
        None
        if row is None
        else GuideMarker(owed_at=row[0], finished_at=row[1], dismissed_at=row[2])
    )


async def read_go_live(session: AsyncSession, *, tenant_id: UUID) -> GoLive:
    """The guide's state, in the caller's tenant session."""
    marker = await read_marker(session, tenant_id=tenant_id)
    workspace = await read_workspace_state(session, tenant_id)
    move = await read_move_progress(
        session,
        tenant_id=tenant_id,
        workspace=workspace.workspace_id if workspace.active else None,
    )
    kyc = await read_kyc(session, tenant_id=tenant_id)
    verify = _VERIFY_OF_KYC.get(kyc.status or "", "todo")
    numbers = int(
        (
            await session.execute(
                text(
                    "SELECT count(*) FROM phone_numbers WHERE tenant_id = :tid "
                    "AND released_at IS NULL"
                ),
                {"tid": tenant_id},
            )
        ).scalar_one()
    )
    number: NumberState
    if numbers > 0:
        number = "done"
    else:
        readiness = await purchase_readiness(session, tenant_id=tenant_id)
        number = (
            "todo"
            if readiness.step == "ready"
            else "waiting_approval"
            if readiness.step == "business_details"
            else "locked"
        )
    live = int(
        (
            await session.execute(
                text(
                    "SELECT count(*) FROM agents WHERE tenant_id = :tid AND deleted_at IS NULL "
                    "AND status = 'live'"
                ),
                {"tid": tenant_id},
            )
        ).scalar_one()
    )
    return GoLive(
        marker=marker,
        move=move,
        verify=verify,
        number=number,
        numbers=numbers,
        switch_on="done" if live > 0 else "todo",
        live_agents=live,
    )


Marker = Literal["finished", "dismissed"]


async def mark(session: AsyncSession, *, tenant_id: UUID, marker: Marker) -> bool:
    """The owner finished the guide or put it aside. True when a row changed; an account
    owed no guide (it has not paid) changes nothing."""
    result = await session.execute(
        text(_FINISH_SQL if marker == "finished" else _DISMISS_SQL),
        {"tid": tenant_id, "at": datetime.now(UTC)},
    )
    return result.first() is not None


_FINISH_SQL: Final = (
    "UPDATE go_live_guides SET finished_at = COALESCE(finished_at, :at), updated_at = now() "
    "WHERE tenant_id = :tid RETURNING id"
)
_DISMISS_SQL: Final = (
    "UPDATE go_live_guides SET dismissed_at = COALESCE(dismissed_at, :at), updated_at = now() "
    "WHERE tenant_id = :tid RETURNING id"
)


__all__ = [
    "GoLive",
    "GuideMarker",
    "GuideStep",
    "Marker",
    "NumberState",
    "SwitchState",
    "VerifyState",
    "mark",
    "read_go_live",
    "read_marker",
]
