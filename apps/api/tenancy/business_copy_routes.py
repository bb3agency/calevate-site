"""The account's AI-written examples and suggestions, as the screens read them (D-827).

    GET  /v1/business-copy   the copy in use, when it was written, and why the last run
                             wrote nothing, if it did not

Every screen falls back to the per-trade examples until the first copy lands. Asking for a
refresh is Pip's (`business_copy_refresh`, `copilot/assist_actions.py`), the one way a
person asks for AI work (D-820).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, cast

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.rbac import permission_meta
from apps.api.tenancy import business_copy as service

router = APIRouter(prefix="/v1/business-copy", tags=["account"])

Session = Annotated[AsyncSession, Depends(db)]
Reader = Annotated[Principal, Depends(requires("org:read"))]


class BusinessCopyOut(BaseModel):
    """What the screens show. Lists are capped by `GeneratedCopy`'s own bounds."""

    model_config = ConfigDict(extra="forbid")

    #: None until the first run wrote copy, or when the stored copy no longer reads.
    placeholders: service.Placeholders | None
    steps: list[service.StepSuggestion] = Field(max_length=service.MAX_STEPS)
    caller_details: list[str] = Field(max_length=service.MAX_CHIPS)
    example_questions: list[str] = Field(max_length=service.MAX_QUESTIONS)
    #: The language the example lines are written in (BCP-47).
    language: str | None
    generated_at: datetime | None
    #: A run is in progress.
    refreshing: bool
    #: Why the last run wrote nothing, and the sentence a person reads about it. None when
    #: the last run wrote the copy in use.
    stop_reason: service.StopReason | None
    stop_message: str | None


def render(state: service.CopyState | None) -> BusinessCopyOut:
    copy = state.copy if state is not None else None
    reason = state.stop_reason if state is not None else None
    return BusinessCopyOut(
        placeholders=copy.placeholders if copy is not None else None,
        steps=list(copy.steps) if copy is not None else [],
        caller_details=list(copy.caller_details) if copy is not None else [],
        example_questions=list(copy.example_questions) if copy is not None else [],
        language=state.language if state is not None and copy is not None else None,
        generated_at=state.generated_at if state is not None and copy is not None else None,
        refreshing=state.running if state is not None else False,
        stop_reason=cast("service.StopReason | None", reason),
        stop_message=service.STOP_MESSAGES.get(reason) if reason is not None else None,
    )


@router.get(
    "",
    response_model=BusinessCopyOut,
    openapi_extra=permission_meta("org:read"),
    summary="This account's own examples and suggestions",
)
async def get_business_copy(session: Session, principal: Reader) -> BusinessCopyOut:
    del principal
    return render(await service.read_state(session))
