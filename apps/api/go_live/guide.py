"""The owner's go-live guide after the first payment (D-859, founder 23 Oct 2026).

Three steps for the owner, each read from the state the rest of the product already keeps, so
the guide can never say something the screens it links to disagree with:

1. **Verify your business**: the KYC record (`compliance/kyc.read_kyc`), the agreements
   (`legal/service.agreements_blocker`, which refuses a publish) and the no-cold-calls pledge
   (`compliance/outbound_pledge`, which refuses outbound only, so it never holds the step).
2. **Get your number**: the account's numbers and the purchase gates
   (`campaigns/engine_number_purchase.purchase_readiness`), each gate its own state so the
   screen names the real reason a number cannot be bought yet.
3. **Switch it on**: whether any agent is live; switching one on is the agent's own switch,
   with its own gate reasons.

The agents' move into the account's own calling set-up (`go_live.moves`) is published beside
the steps but is never one of them: it is our work, and the owner carries on while it runs.

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

from apps.api.campaigns.engine_business_details import RESUBMITTABLE
from apps.api.campaigns.engine_number_purchase import PurchaseReadiness, purchase_readiness
from apps.api.compliance.kyc import read_kyc
from apps.api.compliance.outbound_pledge import pledge_blocker
from apps.api.go_live.moves import MoveProgress, read_move_progress
from apps.api.legal.service import agreements_blocker
from apps.api.tenancy.engine_workspace import read_workspace_state

VerifyState = Literal["todo", "in_review", "needs_attention", "done"]
#: Why a number cannot be bought yet, one state per purchase gate (`PurchaseStep`):
#: `locked` the business is not verified; `add_credit` the free trial; `setting_up` the
#: account's own calling set-up is not active; `send_details` the business details were never
#: sent; `waiting_approval` they are being checked; `needs_attention` they were rejected, have
#: expired or were withdrawn; `not_on_sale` no monthly price is set yet.
NumberState = Literal[
    "locked",
    "add_credit",
    "setting_up",
    "send_details",
    "waiting_approval",
    "needs_attention",
    "not_on_sale",
    "todo",
    "done",
]
SwitchState = Literal["todo", "done"]
AcceptState = Literal["todo", "done"]
#: `move` stays on the wire for readers built before the move left the steps; `current` no
#: longer answers it.
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
    #: The agreements every publish needs (`assert_agreements_accepted`).
    agreements: AcceptState
    #: The no-cold-calls pledge every outbound call needs; inbound never waits on it.
    pledge: AcceptState
    number: NumberState
    #: On a rejected application, what to correct; otherwise None.
    business_review_note: str | None
    numbers: int
    switch_on: SwitchState
    live_agents: int

    @property
    def current(self) -> GuideStep:
        """The first owner step not done. Switching an agent on needs the agreements as well
        as the business check, so both close the first step; the pledge does not, because an
        agent that only answers calls never needs it."""
        if self.verify != "done" or self.agreements != "done":
            return "verify"
        if self.number != "done":
            return "number"
        if self.switch_on != "done":
            return "switch_on"
        return "done"


def number_state(readiness: PurchaseReadiness, *, numbers: int) -> NumberState:
    """Where the number step stands, from the purchase gate that stops it first."""
    if numbers > 0:
        return "done"
    match readiness.step:
        case "ready":
            return "todo"
        case "add_credit":
            return "add_credit"
        case "workspace":
            return "setting_up"
        case "verify_business":
            return "locked"
        case "price":
            return "not_on_sale"
        case "business_details":
            return _details_state(readiness.business_status)


def _details_state(status: str | None) -> NumberState:
    """The business-details application, as the owner can act on it. `accepted` without
    `canRent` is still the vendor's to finish, so it waits like a submission."""
    if status is None or status in ("none", "draft"):
        return "send_details"
    if status in RESUBMITTABLE or status == "suspended":
        return "needs_attention"
    return "waiting_approval"


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
    agreements: AcceptState = (
        "done" if await agreements_blocker(session, tenant_id=tenant_id) is None else "todo"
    )
    pledge: AcceptState = (
        "done" if await pledge_blocker(session, tenant_id=tenant_id) is None else "todo"
    )
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
    readiness = None if numbers > 0 else await purchase_readiness(session, tenant_id=tenant_id)
    number: NumberState = "done" if readiness is None else number_state(readiness, numbers=numbers)
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
        agreements=agreements,
        pledge=pledge,
        number=number,
        business_review_note=(
            readiness.business_review_note
            if readiness is not None and number == "needs_attention"
            else None
        ),
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
    "AcceptState",
    "GoLive",
    "GuideMarker",
    "GuideStep",
    "Marker",
    "NumberState",
    "SwitchState",
    "VerifyState",
    "mark",
    "number_state",
    "read_go_live",
    "read_marker",
]
