"""An account's business type: chosen by a person, never by a default (D-722).

The business type decides the lead details an agent captures, the examples an owner reads,
the ready-made scripts, and whether cross-call memory is refused. Until 11 Oct 2026 the
operator wizard pre-selected `clinic`, so a chilli shop captured "Preferred doctor". Now:

* Every create path requires a type (`CreateOrgIn`, `SignupIn`); there is no default.
* An account created before that with `clinic` is UNCONFIRMED (migration `d7a3c91e5b20`):
  `vertical_template` is empty, `unconfirmed_business_type` keeps `clinic`, and the account
  runs on the neutral core lead fields until an operator confirms a type.
* The dashboard AI suggests a type once per unconfirmed account
  (`apps/workers/business_type.py`); an operator confirms it or picks another
  (`confirm`). A suggestion alone changes nothing.

Confirming queues `APPLY_JOB`, which writes the type's lead details onto agents that have
none, swaps an untouched ready-made starter for the new type's, recompiles each agent's
script so "what to collect" matches, and republishes live agents through the one publish
path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from scripts.seed import BUSINESS_TYPE_LABELS, VERTICAL_TEMPLATES
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.ai_quota import platform_brake_tripped
from apps.api.core.errors import ProblemError
from apps.api.db.result import rowcount_of
from apps.api.reliability.service import enqueue_outbox

#: The worker job (`apps/workers/business_type.apply_business_type`).
APPLY_JOB: Final = "apply_business_type"

#: The keys the clinic type seeds. An agent whose business fields are a subset of these on
#: an account that is not a clinic is carrying the old default, not a choice.
CLINIC: Final = "clinic"
CLINIC_DEFAULT_KEYS: Final = frozenset(str(f["key"]) for f in VERTICAL_TEMPLATES[CLINIC])


@dataclass(frozen=True, slots=True)
class Unconfirmed:
    """An account whose type was given by a default and is waiting for a person."""

    #: The type it was given (`clinic`), shown so the operator knows what it ran as.
    given: str
    suggested: str | None
    reason: str | None
    suggested_at: datetime | None


@dataclass(frozen=True, slots=True)
class BusinessTypeState:
    business_type: str | None
    unconfirmed: Unconfirmed | None


_STATE_SQL: Final = (
    "SELECT vertical_template, unconfirmed_business_type, suggested_business_type, "
    "suggested_business_type_reason, business_type_suggested_at FROM organizations "
    "WHERE id = :tid AND deleted_at IS NULL"
)


async def read_state(session: AsyncSession, *, tenant_id: UUID) -> BusinessTypeState:
    row = (await session.execute(text(_STATE_SQL), {"tid": tenant_id})).first()
    if row is None:
        raise ProblemError.not_found("Client")
    unconfirmed = (
        None
        if row[1] is None
        else Unconfirmed(
            given=str(row[1]),
            suggested=None if row[2] is None else str(row[2]),
            reason=None if row[3] is None else str(row[3]),
            suggested_at=row[4],
        )
    )
    return BusinessTypeState(
        business_type=None if row[0] is None else str(row[0]), unconfirmed=unconfirmed
    )


async def queue_apply(
    session: AsyncSession, *, tenant_id: UUID, replace_clinic_default: bool = False
) -> None:
    """Bring the account's agents to its business type, after the caller's commit."""
    await enqueue_outbox(
        session,
        job=APPLY_JOB,
        payload={"tenant_id": str(tenant_id), "replace_clinic_default": replace_clinic_default},
    )


async def queue_suggestion(session: AsyncSession, *, tenant_id: UUID) -> None:
    """Ask the AI for a business type again ("Suggest again"), after the caller's commit.

    Only an unconfirmed account has anything to suggest for. The worker runs the suggestion
    step alone (`suggest_only`) and replaces any suggestion on file. The cost is ours
    (`ASSIST_FEATURE_BUSINESS_TYPE` is absorbed), so the client's AI allowance is not
    consulted; the platform-wide AI brake is, and refuses while it is tripped.
    """
    state = await read_state(session, tenant_id=tenant_id)
    if state.unconfirmed is None:
        raise ProblemError.business_rule(
            "business_type_already_chosen",
            "This client's business type is already chosen, so there is nothing to suggest.",
        )
    if await platform_brake_tripped(session):
        raise ProblemError(
            kind="transient",
            code="ai_paused_platform_wide",
            title="AI help is paused",
            detail="AI help is paused across Calevate while usage is checked.",
            remediation="Choose the type yourself, or try again once the AI brake is released.",
        )
    await enqueue_outbox(
        session,
        job=APPLY_JOB,
        payload={"tenant_id": str(tenant_id), "suggest_only": True},
    )


async def confirm(session: AsyncSession, *, tenant_id: UUID, business_type: str) -> str | None:
    """Set the account's business type as a person's choice. Returns the type it replaced
    (the unconfirmed one when there was one).

    Clears the unconfirmed type and the suggestion in the same statement, and queues the
    apply job in the caller's transaction. Re-confirming the type already on file is
    allowed and re-queues the apply, which is idempotent.
    """
    if business_type not in BUSINESS_TYPE_LABELS:
        raise ProblemError.business_rule(
            "unknown_business_type", "That business type is not one we offer."
        )
    row = (
        await session.execute(
            text(
                "UPDATE organizations o SET vertical_template = :bt, "
                "unconfirmed_business_type = NULL, suggested_business_type = NULL, "
                "suggested_business_type_reason = NULL, business_type_suggested_at = NULL, "
                "updated_at = now() FROM organizations old "
                "WHERE o.id = old.id AND o.id = :tid AND o.deleted_at IS NULL "
                "RETURNING COALESCE(old.unconfirmed_business_type, old.vertical_template)"
            ),
            {"bt": business_type, "tid": tenant_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Client")
    await queue_apply(session, tenant_id=tenant_id)
    return None if row[0] is None else str(row[0])


async def record_suggestion(
    session: AsyncSession, *, tenant_id: UUID, business_type: str, reason: str
) -> bool:
    """Store the AI's suggestion on an account that is still unconfirmed. Returns whether
    it was stored (an operator may have confirmed a type while the model was thinking)."""
    result = await session.execute(
        text(
            "UPDATE organizations SET suggested_business_type = :bt, "
            "suggested_business_type_reason = :reason, business_type_suggested_at = now(), "
            "updated_at = now() WHERE id = :tid AND unconfirmed_business_type IS NOT NULL"
        ),
        {"bt": business_type, "reason": reason, "tid": tenant_id},
    )
    return rowcount_of(result) > 0


__all__ = [
    "APPLY_JOB",
    "CLINIC",
    "CLINIC_DEFAULT_KEYS",
    "BusinessTypeState",
    "Unconfirmed",
    "confirm",
    "queue_apply",
    "queue_suggestion",
    "read_state",
    "record_suggestion",
]
