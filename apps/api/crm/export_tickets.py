"""A one-time download of an export Pip prepared (D-893 L2).

Pip confirms an export the way the Export button does — same permission, same emailed code
(`ActionTool.action_code`) — but a confirm answers JSON, not a file. So the confirm issues a
TICKET and the browser downloads with it from `POST /v1/exports/download`, which builds the
file through the same service the Export button's route uses and writes the same audit row.

The ticket holds the LENS, never the file: nothing with a phone number in it is stored
anywhere between the confirm and the download, and the file is exactly what the lens
matches at the moment it leaves. A ticket is bound to the account and the person who
confirmed, lives `TICKET_TTL_S`, and is spent by the first download (`GETDEL`), so a ticket
read out of a log after use opens nothing. It rides in a request body, never a URL.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from typing import Any, Final, Literal
from uuid import UUID

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger

log = get_logger(__name__)

ExportKind = Literal["leads", "calls"]

#: How long a prepared export may wait for its download.
TICKET_TTL_S: Final = 600
_PREFIX: Final = "export-ticket:"


@dataclass(frozen=True, slots=True)
class Ticket:
    kind: ExportKind
    #: `LeadLensIn` or `CallLensIn` as JSON.
    lens: dict[str, Any]


async def issue(*, tenant_id: UUID, user_id: UUID, kind: ExportKind, lens: dict[str, Any]) -> str:
    from apps.api.core.redis import get_redis

    token = secrets.token_urlsafe(24)
    body = {"tenant_id": str(tenant_id), "user_id": str(user_id), "kind": kind, "lens": lens}
    await get_redis().set(_PREFIX + token, json.dumps(body), ex=TICKET_TTL_S)
    return token


def _gone() -> ProblemError:
    return ProblemError(
        kind="not_found",
        code="export_ticket_gone",
        title="This download has expired",
        detail="The file Pip prepared can be downloaded once, within ten minutes.",
        remediation="Ask Pip for the export again, or use Export on the screen.",
    )


async def redeem(*, token: str, tenant_id: UUID, user_id: UUID) -> Ticket:
    """Spend the ticket. Another account's or another person's ticket reads as expired
    (and stays spent): neither is a fact this caller is entitled to."""
    from apps.api.core.redis import get_redis

    raw = await get_redis().getdel(_PREFIX + token)
    if raw is None:
        raise _gone()
    body = json.loads(raw)
    if body.get("tenant_id") != str(tenant_id) or body.get("user_id") != str(user_id):
        log.warning("export_ticket_wrong_holder", extra={"tenant_id": str(tenant_id)})
        raise _gone()
    kind = body.get("kind")
    if kind not in ("leads", "calls"):
        raise _gone()
    return Ticket(kind=kind, lens=dict(body.get("lens") or {}))


__all__ = ["TICKET_TTL_S", "ExportKind", "Ticket", "issue", "redeem"]
