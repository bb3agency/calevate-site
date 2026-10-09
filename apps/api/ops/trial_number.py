"""The shared free-trial number: which numbers may be it, and the ops read (D-697).

The trial number is a PLATFORM-HELD number: held in our developer workspace and recorded
against no client. Choosing it in the ops console (`trial_caller_number`) is what records it
as the platform's; there is no client row for it, and the number sweep leaves it alone.

`trial_number_candidates` lists what the console may offer, read live from the voice
platform (`GET /phone-numbers` with no workspace header, i.e. the developer workspace;
`thinnest-findings/mirror/snapshots/2026-10-08/pages/api-reference/phone-numbers/
list-phone-numbers.md`) minus every number recorded against a client.
`assert_trial_number_selectable` is the same test applied to one number, and
`ops.config_service.set_value` asks it on every write of the setting, so the generic config
write cannot store a number the platform does not hold.

Phone numbers are returned to the operator (they must pick one) and never logged.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Final

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.rbac import permission_meta
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session

log = get_logger(__name__)

TRIAL_NUMBER_KEY: Final = "trial_caller_number"


@dataclass(frozen=True, slots=True)
class TrialNumberCandidate:
    e164: str
    #: Rented from the platform (charged to us monthly), or brought on a carrier account.
    rented: bool
    #: An agent answers it today. A trial call sets nothing to answer it.
    answered: bool


def _digits(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


async def _recorded_digits() -> set[str]:
    """The digits of every number recorded against a client, across every tenant, each read
    in that tenant's own session (the directory read is the only wider one)."""
    from apps.api.campaigns.engine_numbers import live_tenants

    recorded: set[str] = set()
    for tenant_id in await live_tenants():
        async with tenant_session(tenant_id) as scoped:
            rows = (
                await scoped.execute(
                    text("SELECT e164 FROM phone_numbers WHERE released_at IS NULL")
                )
            ).scalars()
            recorded.update(_digits(str(row)) for row in rows)
    return recorded


async def trial_number_candidates() -> list[TrialNumberCandidate]:
    """Numbers the developer workspace holds that no client has recorded."""
    from apps.api.campaigns.engine_numbers import vendor_numbers

    held = await vendor_numbers(None)
    recorded = await _recorded_digits()
    return [
        TrialNumberCandidate(
            e164=number.e164,
            rented=bool(number.engine_owned),
            answered=number.answering_agent_ref is not None,
        )
        for number in held
        if _digits(number.e164) not in recorded
    ]


async def assert_trial_number_selectable(e164: str | None) -> None:
    """Refuse a trial number the developer workspace does not hold, or that a client has
    recorded. Clearing the setting (None) is always allowed."""
    if e164 is None:
        return
    if get_settings().engine != "thinnest":
        raise ProblemError.business_rule(
            "trial_number_engine_not_thinnest",
            "The shared trial number is used only when the voice engine is ThinnestAI.",
            remediation="Switch the engine first, or leave this setting empty.",
        )
    wanted = _digits(e164)
    candidates = await trial_number_candidates()
    if any(_digits(candidate.e164) == wanted for candidate in candidates):
        return
    raise ProblemError.business_rule(
        "trial_number_not_platform_held",
        "That number is not one our developer workspace holds unrecorded on the voice "
        "platform, so it cannot be the shared trial number.",
        remediation=(
            "Pick one of the numbers listed under Shared trial number. A number recorded "
            "against a client must be released from that client first."
        ),
    )


# --- the ops read ----------------------------------------------------------------------

router = APIRouter(prefix="/v1/ops/trial-number", tags=["ops"])
TrialNumberReader = Annotated[Principal, Depends(requires("platform:config", realm="admin"))]


class TrialNumberCandidateOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    e164: str
    rented: bool
    answered: bool


class TrialNumberOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The number set now, or null.
    current: str | None
    #: Whether the developer workspace still holds the current number unrecorded. Null
    #: when nothing is set.
    current_held: bool | None
    #: What may be chosen: platform-held numbers no client has recorded.
    candidates: list[TrialNumberCandidateOut]


@router.get(
    "",
    response_model=TrialNumberOut,
    openapi_extra=permission_meta("platform:config"),
    summary="The shared free-trial number, and the platform-held numbers that may be it",
)
async def read_trial_number(principal: TrialNumberReader) -> TrialNumberOut:
    del principal
    current = get_settings().trial_caller_number
    candidates = await trial_number_candidates() if get_settings().engine == "thinnest" else []
    held = None if current is None else any(_digits(c.e164) == _digits(current) for c in candidates)
    return TrialNumberOut(
        current=current,
        current_held=held,
        candidates=[
            TrialNumberCandidateOut(e164=c.e164, rented=c.rented, answered=c.answered)
            for c in candidates
        ],
    )


__all__ = [
    "TRIAL_NUMBER_KEY",
    "TrialNumberCandidate",
    "assert_trial_number_selectable",
    "router",
    "trial_number_candidates",
]
