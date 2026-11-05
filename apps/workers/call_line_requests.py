"""Email every operator that a client asked for more calls at once.

Promised by `tenancy/call_line_requests.ask_for_more` through the outbox, in the transaction
that opened the request, keyed on the request. Every live super admin and admin is told, the
way Slack sends an app request to every owner and app manager: whoever is free answers it.
The email's button opens the client's Numbers page with the calls-at-once control open.

A request answered before the job runs is not announced: there is nothing left to do. A
failed send raises `arq.Retry`; a retry may email an operator who already received it, which
is noise, never a missed request. Logs carry ids and counts only (hard rule 6).
"""

from __future__ import annotations

import asyncio
from typing import Any, Final, NoReturn
from uuid import UUID

from arq import Retry
from sqlalchemy import text

from apps.api.core.alerting import alert
from apps.api.core.brand import PRODUCT
from apps.api.core.console_links import admin_call_lines_link
from apps.api.core.logging import get_logger
from apps.api.core.queue import job_try
from apps.api.core.rbac import ADMIN_ROLES
from apps.api.core.transport import EmailPurpose, get_transport
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.tenancy.call_line_requests import (
    OPERATOR_NOTICE_JOB,
    LineRequest,
    open_request_for,
    requester_name,
    wanted_phrase,
)
from apps.workers.email_render import from_text

log = get_logger(__name__)

JOB_NAME: Final = OPERATOR_NOTICE_JOB

#: Seconds before each retry, indexed by the attempt that just failed (`comp_notices`).
RETRY_BACKOFF_S: Final[tuple[float, ...]] = (60.0, 300.0)


def operator_email(
    *, business: str, slug: str, request: LineRequest, asked_by: str | None, tenant_id: UUID
) -> tuple[str, str]:
    """(subject, body). The link on its own paragraph is rendered as the button."""
    wanted = wanted_phrase(request)
    lines = request.lines_at_request
    subject = f"{PRODUCT}: {business} asks for more calls at once ({lines} → {wanted})"
    body = (
        f"{business} (/{slug}) has {lines} {'call' if lines == 1 else 'calls'} at once and "
        f"asks for {wanted}."
        + (f" Asked by {asked_by}." if asked_by else "")
        + (f"\n\nTheir note: {request.note}" if request.note else "")
        + f"\n\nRaise {business}'s call lines, or decline with a reason they will read:"
        + f"\n\n{admin_call_lines_link(tenant_id)}"
    )
    return subject, body


async def _send(address: str, subject: str, body: str) -> bool:
    message = from_text(subject=subject, preheader=subject, heading=subject, text=body)
    transport = get_transport(EmailPurpose.OPERATOR)
    # Off the event loop: the SMTP transport is synchronous.
    return await asyncio.to_thread(
        lambda: transport.send(to=address, subject=subject, body=message.text, html=message.html)
    )


def _retry(attempt: int, *, tenant_id: UUID) -> NoReturn:
    """arq 0.28 re-runs a job only for `Retry` (`comp_notices._retry` argues it)."""
    log.warning(
        "call_lines_request_notice_send_failed",
        extra={"tenant_id": str(tenant_id), "attempt": attempt},
    )
    raise Retry(defer=RETRY_BACKOFF_S[max(min(attempt, len(RETRY_BACKOFF_S)) - 1, 0)])


async def notify_call_lines_request(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    attempt = job_try(ctx)
    tenant_id = UUID(str(payload["tenant_id"]))
    request_id = UUID(str(payload["request_id"]))
    async with tenant_session(tenant_id) as session:
        org = (
            await session.execute(
                text("SELECT name, slug FROM organizations WHERE id = :tid"), {"tid": tenant_id}
            )
        ).first()
        request = await open_request_for(session, tenant_id=tenant_id)
        asked_by = (
            await requester_name(session, user_id=request.requested_by)
            if request is not None
            else None
        )
    if org is None:
        return "no_account"
    if request is None or request.id != request_id:
        return "answered"
    async with untenanted_session() as session:
        operators = [
            str(r[0])
            for r in (
                await session.execute(
                    text(
                        "SELECT email FROM admin_users WHERE role = ANY(:roles) "
                        "AND deactivated_at IS NULL AND email IS NOT NULL"
                    ),
                    {"roles": list(ADMIN_ROLES)},
                )
            ).all()
        ]
    if not operators:
        alert("WORKER_DELIVERY", "call_lines_request_no_operator_email", tenant_id=str(tenant_id))
        return "no_operator"
    subject, body = operator_email(
        business=str(org[0]),
        slug=str(org[1]),
        request=request,
        asked_by=asked_by,
        tenant_id=tenant_id,
    )
    for address in operators:
        if not await _send(address, subject, body):
            _retry(attempt, tenant_id=tenant_id)
    log.info(
        "call_lines_request_notice_sent",
        extra={
            "tenant_id": str(tenant_id),
            "request_id": str(request_id),
            "operators": len(operators),
        },
    )
    return "sent"


__all__ = ["JOB_NAME", "notify_call_lines_request", "operator_email"]
