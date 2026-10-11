"""Moving a client's number into its own voice workspace, tried again until it can be.

ThinnestAI refuses a move while the number is on a call, while another move of it is under
way, and when the phone network does not take it (docs.thinnest.ai
api-reference/phone-numbers/move-phone-number, read 11 Oct 2026). Each clears by itself, so
`campaigns/engine_numbers.move_into_client_workspace` is run again every `MOVE_RETRY_EVERY` up
to `MOVE_ATTEMPTS` times, longer than the longest call on this engine (20 minutes). A repeat of a
move that already succeeded answers the same, so a retry after a lost answer is safe.
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

from apps.api.campaigns.engine_numbers import (
    MOVE_ATTEMPTS,
    move_into_client_workspace,
    queue_number_move,
)
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.session import tenant_session

log = get_logger(__name__)

#: Our refusal for a vendor refusal that clears by itself (`engine_numbers._move_refusal`).
_LATER: Final = "engine_number_move_later"


def _failed(tenant_id: UUID, number_id: UUID, *, code: str) -> None:
    alert(
        "WORKER_TERMINAL",
        "engine_number_move_failed",
        detail=(
            f"a number could not be moved into its client's own voice workspace ({code}). It "
            "keeps its digits and stays where it was. Fix the cause the code names, then "
            "press Move to client workspace on the client's admin Numbers page."
        ),
        tenant_id=str(tenant_id),
        number_id=str(number_id),
    )


async def move_engine_number(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    tenant_id = UUID(str(payload["tenant_id"]))
    number_id = UUID(str(payload["number_id"]))
    attempt = int(payload.get("attempt") or 1)
    try:
        async with tenant_session(tenant_id) as session:
            await move_into_client_workspace(session, tenant_id=tenant_id, number_id=number_id)
    except ProblemError as exc:
        if exc.code == _LATER and attempt < MOVE_ATTEMPTS:
            await queue_number_move(tenant_id, number_id, attempt=attempt + 1)
            log.info(
                "engine_number_move_deferred",
                extra={"number_id": str(number_id), "attempt": attempt},
            )
            return "deferred"
        _failed(tenant_id, number_id, code=exc.code)
        return "failed"
    return "moved"


__all__ = ["move_engine_number"]
