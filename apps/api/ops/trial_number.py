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
from typing import TYPE_CHECKING, Annotated, Final, Literal

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import global_db
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.rbac import permission_meta
from apps.api.core.settings import get_settings
from apps.api.core.stepup import StepUpGate
from apps.api.db.session import tenant_session

if TYPE_CHECKING:
    from apps.api.campaigns.engine_numbers import TrialLineState

log = get_logger(__name__)

TRIAL_NUMBER_KEY: Final = "trial_caller_number"


@dataclass(frozen=True, slots=True)
class TrialNumberCandidate:
    e164: str
    #: Rented from the platform (charged to us monthly), or brought on a carrier account.
    rented: bool
    #: An agent answers it today. A trial call sets nothing to answer it.
    answered: bool
    #: The name the voice platform's console gives the number, or None.
    label: str | None = None
    #: The name of the Calevate agent that answers it, or that it is lent to for calling
    #: out; None when nobody does, or the agent is not one of ours.
    answering_agent: str | None = None
    calling_agent: str | None = None


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


async def _agent_names(refs: set[str]) -> dict[str, str]:
    """Our agents' names for these engine handles, across every tenant, each read in that
    tenant's own session. A handle no tenant knows is simply absent."""
    from apps.api.campaigns.engine_numbers import live_tenants

    names: dict[str, str] = {}
    if not refs:
        return names
    for tenant_id in await live_tenants():
        async with tenant_session(tenant_id) as scoped:
            rows = await scoped.execute(
                text(
                    "SELECT engine_agent_ref, name FROM agents WHERE engine_agent_ref = ANY(:refs)"
                ),
                {"refs": sorted(refs)},
            )
            names.update({str(ref): str(name) for ref, name in rows})
    return names


async def trial_number_candidates(*, with_names: bool = False) -> list[TrialNumberCandidate]:
    """Numbers the developer workspace holds that no client has recorded. `with_names`
    also reads each number's agents' names, for the operator choosing among them."""
    from apps.api.campaigns.engine_numbers import vendor_numbers

    held = await vendor_numbers(None)
    recorded = await _recorded_digits()
    free = [number for number in held if _digits(number.e164) not in recorded]
    refs = {
        ref
        for number in free
        for ref in (number.answering_agent_ref, number.calling_agent_ref)
        if ref is not None
    }
    names = await _agent_names(refs) if with_names else {}
    return [
        TrialNumberCandidate(
            e164=number.e164,
            rented=bool(number.engine_owned),
            answered=number.answering_agent_ref is not None,
            label=number.label,
            answering_agent=names.get(number.answering_agent_ref or ""),
            calling_agent=names.get(number.calling_agent_ref or ""),
        )
        for number in free
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
    #: The name ThinnestAI's console gives the number, or null.
    label: str | None
    #: Our agent that answers it, or that it is lent to for calling out, by name; null when
    #: nobody is, or the agent is not one of ours.
    answering_agent: str | None
    calling_agent: str | None


class TrialLineOut(BaseModel):
    """The shared number's own line: a never-answering agent that speaks our message."""

    model_config = ConfigDict(extra="forbid")

    #: `ready`, `no_number`, `no_agent`, `not_attached`, `drifted` or `unavailable`.
    state: Literal["ready", "no_number", "no_agent", "not_attached", "drifted", "unavailable"]
    #: The message the platform holds, or null.
    message: str | None
    #: The platform's note when the message will not be spoken as written, or null.
    message_note: str | None
    #: The message we want callers to hear.
    wanted_message: str


def _line_out(state: TrialLineState) -> TrialLineOut:
    from apps.api.campaigns.engine_numbers import TRIAL_LINE_MESSAGE

    return TrialLineOut(
        state=state.state,
        message=state.message,
        message_note=state.message_note,
        wanted_message=TRIAL_LINE_MESSAGE,
    )


class TrialNumberOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The number set now, or null.
    current: str | None
    #: Whether the developer workspace still holds the current number unrecorded. Null
    #: when nothing is set.
    current_held: bool | None
    #: False when the engine in force is not ThinnestAI: no number is read, and none may be
    #: chosen (`assert_trial_number_selectable`).
    engine_uses_it: bool
    #: What may be chosen: platform-held numbers no client has recorded.
    candidates: list[TrialNumberCandidateOut]
    #: What a caller ringing the number back hears (D-742); null when no number is set or
    #: the engine is not ThinnestAI.
    line: TrialLineOut | None


@router.get(
    "",
    response_model=TrialNumberOut,
    openapi_extra=permission_meta("platform:config"),
    summary="The shared free-trial number, and the platform-held numbers that may be it",
)
async def read_trial_number(principal: TrialNumberReader) -> TrialNumberOut:
    del principal
    current = get_settings().trial_caller_number
    engine_uses_it = get_settings().engine == "thinnest"
    candidates = await trial_number_candidates(with_names=True) if engine_uses_it else []
    held = None if current is None else any(_digits(c.e164) == _digits(current) for c in candidates)
    return TrialNumberOut(
        current=current,
        current_held=held,
        engine_uses_it=engine_uses_it,
        candidates=[
            TrialNumberCandidateOut(
                e164=c.e164,
                rented=c.rented,
                answered=c.answered,
                label=c.label,
                answering_agent=c.answering_agent,
                calling_agent=c.calling_agent,
            )
            for c in candidates
        ],
        line=await _current_line() if engine_uses_it and current else None,
    )


async def _current_line() -> TrialLineOut:
    from apps.api.campaigns.engine_numbers import read_trial_line

    return _line_out(await read_trial_line())


TrialLineWriter = Annotated[Principal, Depends(requires("platform:config", realm="admin"))]

#: The step-up string for setting up the shared trial number's line (D-731): it creates or
#: repairs an agent in our developer workspace and points a live number at it.
TRIAL_LINE_CONFIRMATION: Final = "set_up_trial_line"


@router.post(
    "/line",
    response_model=TrialLineOut,
    openapi_extra=permission_meta("platform:config"),
    summary="Set up what a caller ringing the shared trial number back hears",
    description=(
        "Makes (or repairs) the one agent in our developer workspace that never answers and "
        "speaks the trial line's message, and makes it the shared number's line. Idempotent; "
        "the daily number sweep does the same."
    ),
)
async def set_up_trial_line(
    principal: TrialLineWriter,
    session: Annotated[AsyncSession, Depends(global_db)],
    request: Request,
    step_up: StepUpGate,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> TrialLineOut:
    step_up.require(x_confirm_action, TRIAL_LINE_CONFIRMATION)
    if get_settings().engine != "thinnest" or get_settings().trial_caller_number is None:
        raise ProblemError.business_rule(
            "trial_line_no_number",
            "There is no shared trial number to set up.",
            remediation="Choose the shared trial number first.",
        )
    from apps.api.campaigns.engine_numbers import converge_trial_line

    out = _line_out(await converge_trial_line())
    await write_audit(
        session,
        action="platform.trial_line_set_up",
        actor=principal,
        object_type="trial_line",
        object_id=TRIAL_NUMBER_KEY,
        ip=client_request_ip(request),
        summary={"state": out.state},
    )
    return out


__all__ = [
    "TRIAL_NUMBER_KEY",
    "TrialNumberCandidate",
    "assert_trial_number_selectable",
    "router",
    "trial_number_candidates",
]
