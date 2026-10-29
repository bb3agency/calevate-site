"""Jobs for clients' own WhatsApp accounts (D-784).

* `ingest_whatsapp_event` applies one normalized Meta webhook event (`api/whatsapp/
  webhooks.py`) to the client it belongs to: a template's review verdict, an account or
  number event, a failed delivery. The WABA names the client through
  `whatsapp_waba_session`, then everything runs under that client's `tenant_session`.
* `seed_whatsapp_templates` submits Calevate's standard templates to a newly connected
  account (enqueued through the outbox by `api/whatsapp/signup.queue_templates`).

Alarms an operator acts on: a rejected or paused template, an account Meta restricted or a
partner removal, a number whose quality dropped, and repeated delivery failures.
Ids and codes only in every log line (hard rule 6).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

from arq import Retry
from calevate_shared.backoff import ladder_delay_s
from sqlalchemy import text

from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES, enqueue
from apps.api.db.session import tenant_session, untenanted_session, whatsapp_waba_session
from apps.api.reliability.service import mark_inbox_failed, mark_inbox_processed
from apps.api.whatsapp import accounts, graph, templates
from apps.api.whatsapp.webhooks import WabaEvent, event_from_payload

log = get_logger(__name__)

#: Account-level events that mean sending is stopped or at risk.
ACCOUNT_STOPPING: Final = frozenset(
    {
        "PARTNER_REMOVED",
        "DISABLED_UPDATE",
        "ACCOUNT_VIOLATION",
        "ACCOUNT_RESTRICTION",
        "ACCOUNT_DELETED",
        "BUSINESS_VERIFICATION_REJECTED",
    }
)
#: Number quality events that lower what the number may send.
QUALITY_DROPS: Final = frozenset({"FLAGGED", "DOWNGRADE"})
#: Seconds before each retry of an event that failed to apply.
_RETRY_AFTER_S: Final = (30.0, 120.0)


async def _resolve(waba_id: str) -> tuple[UUID, UUID] | None:
    async with whatsapp_waba_session(waba_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT id, tenant_id FROM whatsapp_accounts WHERE waba_id = :w "
                    "AND status <> 'disconnected' ORDER BY created_at DESC LIMIT 1"
                ),
                {"w": waba_id},
            )
        ).first()
    return (UUID(str(row[0])), UUID(str(row[1]))) if row is not None else None


async def _close_inbox(inbox_id: str | None) -> None:
    if not inbox_id:
        return
    async with untenanted_session() as session:
        await mark_inbox_processed(session, row_id=UUID(inbox_id))


async def _fail_inbox(inbox_id: str | None, *, error: str) -> None:
    if not inbox_id:
        return
    try:
        async with untenanted_session() as session:
            await mark_inbox_failed(session, row_id=UUID(inbox_id), error=error)
    except Exception:
        log.exception("whatsapp_event_inbox_unmarked")


async def _apply(account_id: UUID, tenant_id: UUID, event: WabaEvent) -> str:
    ids = {"tenant_id": str(tenant_id), "account_id": str(account_id), "kind": event.kind}
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE whatsapp_accounts SET last_event_at = now() WHERE id = :id"),
            {"id": account_id},
        )
        if event.kind in ("template_status", "template_category"):
            update = templates.StatusUpdate(
                meta_template_id=event.detail.get("template_id"),
                name=event.detail.get("name"),
                language=event.detail.get("language"),
                event=(event.code or "") if event.kind == "template_status" else "",
                reason=event.detail.get("reason"),
                new_category=event.code if event.kind == "template_category" else None,
            )
            status = await templates.apply_status_update(
                session, account_id=account_id, update=update
            )
            if status in ("rejected", "paused", "disabled"):
                alert("WORKER_DELIVERY", "whatsapp_template_not_usable", status=status or "", **ids)
            if event.kind == "template_category":
                alert("WORKER_DELIVERY", "whatsapp_template_recategorised", **ids)
            return status or "template_unknown"
        if event.kind == "template_quality":
            if (event.code or "").upper() == "RED":
                alert("WORKER_DELIVERY", "whatsapp_template_quality_low", **ids)
            return "quality_recorded"
        if event.kind == "account":
            stopping = (event.code or "").upper() in ACCOUNT_STOPPING
            await session.execute(
                text(
                    "UPDATE whatsapp_accounts SET account_alert = :code, account_alert_at = now(), "
                    "status = CASE WHEN :stop THEN 'needs_attention' ELSE status END "
                    "WHERE id = :id AND status <> 'disconnected'"
                ),
                {"id": account_id, "code": (event.code or event.change)[:64], "stop": stopping},
            )
            if stopping:
                alert(
                    "WORKER_DELIVERY",
                    "whatsapp_account_restricted",
                    meta_event=event.code or "",
                    **ids,
                )
            return "account_recorded"
        if event.kind == "phone_quality":
            await session.execute(
                text(
                    "UPDATE whatsapp_accounts SET "
                    "messaging_limit = COALESCE(CAST(:lim AS text), messaging_limit), "
                    "account_alert = :code, account_alert_at = now() WHERE id = :id"
                ),
                {"id": account_id, "lim": event.detail.get("limit"), "code": event.code},
            )
            if (event.code or "").upper() in QUALITY_DROPS:
                alert("WORKER_DELIVERY", "whatsapp_number_quality_dropped", **ids)
            return "quality_recorded"
        if event.kind == "reply":
            from apps.api.follow_ups.runner import stop_for_reply

            sender = event.detail.get("from_e164")
            stopped = await stop_for_reply(session, phone_e164=sender) if sender else 0
            return f"reply_stopped_{stopped}"
        if event.kind == "phone_name":
            await session.execute(
                text("UPDATE whatsapp_accounts SET name_status = :ns WHERE id = :id"),
                {"id": account_id, "ns": (event.code or "")[:32] or None},
            )
            return "name_recorded"
        if event.kind == "send_failed":
            await session.execute(
                text(
                    "UPDATE whatsapp_accounts SET last_send_error = :code, "
                    "last_send_error_at = now() WHERE id = :id"
                ),
                {"id": account_id, "code": (event.code or "unknown")[:64]},
            )
            alert(
                "WORKER_DELIVERY",
                "whatsapp_message_not_delivered",
                episode=str(account_id),
                meta_code=event.code or "unknown",
                **ids,
            )
            return "send_failure_recorded"
    return "activity"


async def ingest_whatsapp_event(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    raw = payload.get("event")
    if not isinstance(raw, dict):
        return "malformed"
    event = event_from_payload(raw)
    inbox_id = payload.get("inbox_id")
    attempt = int(ctx.get("job_try", 1) or 1)
    try:
        resolved = await _resolve(event.waba_id)
        if resolved is None:
            # A WABA no client has live with us (disconnected, or never ours). Nothing to do.
            log.info("whatsapp_event_unclaimed", extra={"kind": event.kind})
            outcome = "unclaimed"
        else:
            outcome = await _apply(resolved[0], resolved[1], event)
    except Exception as exc:
        # The webhook already answered Meta 200, so Meta will not redeliver: this job's
        # retries are the only ones, and arq treats a plain raise as terminal, hence
        # `Retry`. The inbox row stays open across retries so the one that succeeds can
        # close it (`mark_inbox_processed` only closes an open row), and is marked 'failed'
        # when the last attempt gives up rather than sitting at 'enqueued'.
        if attempt < WORKER_MAX_TRIES:
            raise Retry(defer=ladder_delay_s(_RETRY_AFTER_S, attempt)) from exc
        await _fail_inbox(inbox_id, error=type(exc).__name__)
        alert(
            "WORKER_TERMINAL",
            "whatsapp_event_not_applied",
            detail=(
                f"a {event.kind} event from Meta for a client's WhatsApp account failed "
                f"{attempt} time(s) ({type(exc).__name__}) and was dropped"
            ),
            kind=event.kind,
        )
        return "abandoned"
    await _close_inbox(inbox_id)
    return outcome


#: When the first direct check runs, counted from submission: Meta says review "can take up
#: to 24 hours" (`whatsapp/graph.py`), plus an hour for the webhook to land first.
TEMPLATE_FIRST_CHECK_AFTER: Final = timedelta(hours=25)
#: Spacing of later checks, and how many checks run before a still-pending template alarms.
TEMPLATE_RECHECK_EVERY: Final = timedelta(hours=24)
TEMPLATE_CHECKS: Final = 3
_NOT_USABLE: Final = frozenset({"rejected", "paused", "disabled"})
#: `templates.TEMPLATE_CHECK_JOB`, spelled here because `scripts/check_job_wiring` resolves
#: an enqueued job name only through the calling file's own constants.
_CHECK_JOB: Final = "check_whatsapp_template"


async def _schedule_check(payload: dict[str, Any], *, check: int, due: datetime) -> None:
    template_id = str(payload["template_id"])
    await enqueue(
        _CHECK_JOB,
        {**payload, "check": check},
        job_id=f"wa-template-check:{template_id}:{check}",
        _defer_until=due,
    )


async def check_whatsapp_template(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Ask Meta for a submitted template's verdict when its webhook has not brought one.

    Queued by `templates.submit` for every template Meta accepted as pending. It waits until
    review should be over, asks `GET /<template id>`, and records the answer exactly as the
    webhook would. A template still pending after `TEMPLATE_CHECKS` checks alarms
    `whatsapp_templates_stuck_pending`: the client cannot send it and nothing else will move it.
    """
    tenant_id = UUID(str(payload["tenant_id"]))
    template_id = UUID(str(payload["template_id"]))
    check = int(payload.get("check") or 0)
    ids = {"tenant_id": str(tenant_id), "template_id": str(template_id)}
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT status, meta_template_id, name, language, submitted_at, account_id "
                    "FROM whatsapp_templates WHERE id = :id"
                ),
                {"id": template_id},
            )
        ).first()
        if row is None or row[0] != "pending" or row[1] is None or row[4] is None:
            return "settled"
        due = row[4] + TEMPLATE_FIRST_CHECK_AFTER + TEMPLATE_RECHECK_EVERY * check
        if datetime.now(UTC) < due:
            await _schedule_check(payload, check=check, due=due)
            return "scheduled"
        account_id = UUID(str(row[5]))
        account = await accounts.get_account(session, account_id)
        if account.status == "disconnected":
            return "disconnected"
        try:
            token = await accounts.account_token(session, tenant_id=tenant_id, account=account)
        except ProblemError:
            log.warning("whatsapp_template_check_no_token", extra=ids)
            return "no_token"
    meta_id, name, language = str(row[1]), str(row[2]), str(row[3])
    try:
        word, reason = await graph.template_status(template_id=meta_id, token=token)
    except graph.GraphError:
        word, reason = None, None
    status: str | None = "pending"
    if word is not None:
        async with tenant_session(tenant_id) as session:
            status = await templates.apply_status_update(
                session,
                account_id=account_id,
                update=templates.StatusUpdate(
                    meta_template_id=meta_id,
                    name=name,
                    language=language,
                    event=word,
                    reason=reason,
                ),
            )
    if status in _NOT_USABLE:
        alert("WORKER_DELIVERY", "whatsapp_template_not_usable", status=status or "", **ids)
    if status != "pending":
        return status or "unknown"
    if check + 1 < TEMPLATE_CHECKS:
        await _schedule_check(
            payload, check=check + 1, due=datetime.now(UTC) + TEMPLATE_RECHECK_EVERY
        )
        return "still_pending"
    alert(
        "WORKER_DELIVERY",
        "whatsapp_templates_stuck_pending",
        detail=(
            f"a client's WhatsApp template is still pending at Meta after {TEMPLATE_CHECKS} "
            "daily checks (or Meta could not be read); the client cannot send it"
        ),
        **ids,
    )
    return "stuck_pending"


async def seed_whatsapp_templates(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    tenant_id = UUID(str(payload["tenant_id"]))
    account_id = UUID(str(payload["account_id"]))
    ids = {"tenant_id": str(tenant_id), "account_id": str(account_id)}
    async with tenant_session(tenant_id) as session:
        account = await accounts.get_account(session, account_id)
        if account.status == "disconnected":
            return "disconnected"
        try:
            token = await accounts.account_token(session, tenant_id=tenant_id, account=account)
        except Exception:
            log.warning("whatsapp_templates_no_token", extra=ids)
            return "no_token"
        counts = await templates.seed_standard(
            session,
            tenant_id=tenant_id,
            account_id=account_id,
            waba_id=account.waba_id,
            token=token,
        )
    if counts["failed"]:
        alert(
            "WORKER_DELIVERY",
            "whatsapp_templates_not_submitted",
            failed=str(counts["failed"]),
            **ids,
        )
    log.info("whatsapp_templates_seeded", extra={**ids, **counts})
    return "seeded"


__all__ = [
    "ACCOUNT_STOPPING",
    "TEMPLATE_CHECKS",
    "check_whatsapp_template",
    "ingest_whatsapp_event",
    "seed_whatsapp_templates",
]
