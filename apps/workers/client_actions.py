"""Finish a client's slow in-call write after the agent has already moved on (D-700).

`actions/in_call.run_in_call_action` acknowledges a CRM push or a sheet row at once — the
caller does not need to hear the result — and enqueues this. It runs the SAME executor the
in-call door runs (`actions/execution.execute_action`, source `background`), so the action
behaves the same however it is reached.

THE CALLER'S NUMBER is not in the payload: it is read back from our `calls` row by the
engine's call id (`execution.caller_of_call`), which the in-call door made sure exists.

RETRIES. A transient failure (the vendor rate-limited us, timed out, or answered 5xx) is
retried with `arq.Retry` — a plain raise is terminal under arq — and a last failure alarms.
Both writes are safe to repeat: a sheet row is keyed by the call, a CRM record by the phone.
A refusal (no credential, the sheet is not shared) is not retried: it is the client's to fix
and their Needs-attention queue shows it.

HARD RULE 6: ids, kinds and outcome codes only.
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

from arq import Retry
from sqlalchemy import text

from apps.api.actions.execution import CallFacts, caller_of_call, execute_action
from apps.api.actions.service import actions_enabled, get_tool, list_tools
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.session import tenant_session

log = get_logger(__name__)

#: Seconds before each retry, indexed by the attempt that just failed.
RETRY_BACKOFF_S: Final[tuple[float, ...]] = (10.0, 60.0)
#: Outcomes worth another attempt: the vendor was slow, busy or broken, not refusing us.
_TRANSIENT_PREFIXES: Final = (
    "http_5",
    "timeout",
    "unreachable",
    "ReadTimeout",
    "ConnectTimeout",
    "ConnectError",
)
_TRANSIENT_CODES: Final = frozenset({"crm_error", "sheet_error"})


def _transient(status: str, payload: dict[str, Any]) -> bool:
    if status.startswith(_TRANSIENT_PREFIXES):
        return True
    code = payload.get("status_code")
    return status in _TRANSIENT_CODES and (code == 429 or (isinstance(code, int) and code >= 500))


async def run_client_action(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    tenant_id = UUID(str(payload["tenant_id"]))
    tool_id = UUID(str(payload["tool_id"]))
    call_ref = str(payload.get("call_ref") or "")
    raw_args = payload.get("args")
    args: dict[str, Any] = dict(raw_args) if isinstance(raw_args, dict) else {}
    attempt = int(ctx.get("job_try", 1) or 1)
    ids = {"tenant_id": str(tenant_id), "tool_id": str(tool_id)}
    async with tenant_session(tenant_id) as session:
        tool = await get_tool(session, tool_id=tool_id)
        if tool is None:
            log.info("client_action_background_tool_gone", extra=ids)
            return "tool_gone"
        facts = await caller_of_call(session, engine_call_id=call_ref) or CallFacts(
            call_ref=call_ref, caller_e164=None
        )
        result = await execute_action(
            session, tool=tool, received=args, source="background", call=facts
        )
    if result.ok:
        return result.status
    if _transient(result.status, result.payload):
        if attempt < WORKER_MAX_TRIES:
            raise Retry(defer=RETRY_BACKOFF_S[min(attempt, len(RETRY_BACKOFF_S)) - 1])
        alert(
            "WORKER_TERMINAL",
            "client_action_not_completed",
            detail=(
                f"a client's in-call {tool.kind} write failed {attempt} time(s) "
                f"(last outcome {result.status}); the caller was told it was noted. Check the "
                "client's connection on their Connections screen."
            ),
            **ids,
        )
    log.info("client_action_background_refused", extra={**ids, "status": result.status})
    return result.status


#: The ARQ job that runs an agent's after-call actions for one finished call.
AFTER_CALL_ACTIONS_JOB: Final = "run_after_call_actions"


async def run_after_call_actions(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Every switched-on AFTER-call action of the call's agent, once, when the post-call
    pipeline has finished (a thank-you WhatsApp with a booking link, a CRM record, a sheet
    row). The values an action collects are read from the call's extraction by name, so an
    action asking for `name` gets the extracted `name`; the caller's number is the call
    row's. Queued through the outbox, once per call (`pipeline._post_call_stages`)."""
    tenant_id = UUID(str(payload["tenant_id"]))
    call_id = UUID(str(payload["call_id"]))
    ran: list[str] = []
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT c.agent_id, c.engine_call_id, c.direction, c.from_e164, c.to_e164, "
                    "e.data FROM calls c LEFT JOIN call_extractions e ON e.call_id = c.id "
                    "WHERE c.id = :cid"
                ),
                {"cid": call_id},
            )
        ).first()
        if row is None or not await actions_enabled(session, agent_id=UUID(str(row[0]))):
            return "none"
        caller = row[4] if row[2] == "outbound" else row[3]
        facts = CallFacts(call_ref=row[1] or str(call_id), caller_e164=caller, direction=row[2])
        extracted = row[5] if isinstance(row[5], dict) else {}
        received = {k: v for k, v in extracted.items() if isinstance(v, str | int | float | bool)}
        for tool in await list_tools(session, agent_id=UUID(str(row[0]))):
            if not tool.enabled or tool.trigger != "after_call":
                continue
            result = await execute_action(
                session, tool=tool, received=received, source="after_call", call=facts
            )
            ran.append(result.status)
    log.info(
        "after_call_actions_ran",
        extra={"tenant_id": str(tenant_id), "call_id": str(call_id), "count": len(ran)},
    )
    return ",".join(ran) or "none"


__all__ = [
    "AFTER_CALL_ACTIONS_JOB",
    "RETRY_BACKOFF_S",
    "run_after_call_actions",
    "run_client_action",
]
