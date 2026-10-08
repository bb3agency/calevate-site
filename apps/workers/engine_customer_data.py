"""Person-level writes in a client's OWN ThinnestAI workspace: do-not-call and erasure (D-691).

Both are queued through the outbox in the transaction that made them owed —
`compliance/engine_dnc.queue_engine_dnc_push` for a suppression, `retention.
execute_deletion_request` for an erasure — and both ask `tenancy/engine_workspace.
own_workspace` AGAIN here, before anything is sent: a tenant whose workspace is not its own
is never written to, because the developer workspace holds every client's data.

`erase_engine_contact` finds the contact by the person's number in the client's workspace
and erases it (`DELETE /contacts/{id}`, recordings included; `api-reference/contacts/
delete-contact.md:7`). The outcome is recorded on the erasure's `voice_engine` task
(`compliance/processor_erasure`): `confirmed` when every recording was gone, otherwise left
`requested` with the queued count. ThinnestAI retries a queued recording nightly and
publishes no way to ask when the last one went (`workspace/data-and-erasure.md:37-56`), so a
task left `requested` is closed by an operator, and the 30-day overdue alarm says so.

The person's number reaches this job sealed under the platform key, never in clear.
"""

from __future__ import annotations

import base64
import binascii
from typing import Any, Final
from uuid import UUID

from arq import Retry
from sqlalchemy import text

from apps.api.compliance.processor_erasure import record_answer, record_request_sent
from apps.api.core.alerting import alert
from apps.api.core.envelope import Envelope, seal, unseal
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.session import tenant_session
from apps.api.engine.thinnest_customer_data import thinnest_customer_data
from apps.api.tenancy.engine_workspace import own_workspace

log = get_logger(__name__)

ENGINE_DNC_PUSH_JOB: Final = "push_engine_dnc"
ENGINE_CONTACT_ERASURE_JOB: Final = "erase_engine_contact"

_RETRY_AFTER_S: Final = (60.0, 600.0)
_FIELDS: Final = ("ciphertext", "nonce", "dek_wrapped", "dek_nonce")


def _context(request_id: UUID) -> str:
    return f"engine_contact_erasure:{request_id}"


def seal_subject(phone_e164: str, *, request_id: UUID) -> dict[str, Any]:
    """The erasure subject's number, sealed and bound to its request, for the outbox."""
    envelope = seal(phone_e164, context=_context(request_id))
    sealed: dict[str, Any] = {
        name: base64.b64encode(getattr(envelope, name)).decode() for name in _FIELDS
    }
    sealed["kek_id"] = envelope.kek_id
    return sealed


def _open_subject(sealed: Any, *, request_id: UUID) -> str:
    try:
        envelope = Envelope(
            ciphertext=base64.b64decode(sealed["ciphertext"], validate=True),
            nonce=base64.b64decode(sealed["nonce"], validate=True),
            dek_wrapped=base64.b64decode(sealed["dek_wrapped"], validate=True),
            dek_nonce=base64.b64decode(sealed["dek_nonce"], validate=True),
            kek_id=int(sealed["kek_id"]),
        )
    except (KeyError, TypeError, ValueError, binascii.Error) as exc:
        raise ProblemError(
            kind="validation",
            code="engine_erasure_subject_unreadable",
            title="A queued erasure could not be read",
            detail="The job carried an erasure subject with fields missing or unreadable.",
        ) from exc
    return unseal(envelope, context=_context(request_id))


def _retry_if_worth_it(exc: Exception, attempt: int) -> None:
    """Ask arq for another attempt unless the failure is permanent or the budget is spent;
    the caller alarms and re-raises when this returns."""
    permanent = isinstance(exc, ProblemError) and exc.kind == "validation"
    if not permanent and attempt < WORKER_MAX_TRIES:
        raise Retry(defer=_RETRY_AFTER_S[min(attempt, len(_RETRY_AFTER_S)) - 1]) from exc


# --- do-not-call --------------------------------------------------------------------------


async def push_engine_dnc(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Put the client's new suppressions on its own workspace's do-not-call list."""
    tenant_id = UUID(str(payload["tenant_id"]))
    workspace = await own_workspace(tenant_id)
    if workspace is None:
        log.info("engine_dnc_push_skipped", extra={"tenant_id": str(tenant_id)})
        return "not_provisioned"
    async with tenant_session(tenant_id) as session:
        phones = [
            str(phone)
            for phone in (
                await session.execute(
                    text("SELECT phone_e164 FROM dnc_list WHERE id = ANY(:ids)"),
                    {"ids": [UUID(str(i)) for i in payload.get("dnc_ids", [])]},
                )
            ).scalars()
        ]
    try:
        client = thinnest_customer_data()
        for phone in phones:
            await client.add_do_not_call(workspace, phone)
    except Exception as exc:
        _retry_if_worth_it(exc, int(ctx.get("job_try", 1)))
        alert(
            "WORKER_TERMINAL",
            "engine_dnc_push_failed",
            detail=(
                "a client's do-not-call addition could not be put on its own voice platform "
                "workspace list. Our list still refuses the number on every dial; add it in "
                "the client's workspace by hand"
                f" ({type(exc).__name__})"
            ),
            tenant_id=str(tenant_id),
        )
        raise
    log.info("engine_dnc_pushed", extra={"tenant_id": str(tenant_id), "count": len(phones)})
    return f"pushed={len(phones)}"


# --- erasure --------------------------------------------------------------------------------


_TASK_SQL: Final = (
    "SELECT id FROM processor_erasure_tasks WHERE request_ref = :rid "
    "AND processor = 'voice_engine' ORDER BY id LIMIT 1"
)


async def erase_engine_contact(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Erase the subject's contact in the client's own workspace; record the outcome."""
    tenant_id = UUID(str(payload["tenant_id"]))
    request_id = UUID(str(payload["request_id"]))
    workspace = await own_workspace(tenant_id)
    if workspace is None:
        # Provisioned when the erasure ran, not now: the task stays open for a human, and
        # nothing is sent to a workspace that is not this client's.
        log.warning("engine_contact_erasure_skipped", extra={"request_id": str(request_id)})
        return "not_provisioned"
    try:
        phone = _open_subject(payload.get("subject"), request_id=request_id)
        client = thinnest_customer_data()
        contacts = await client.contact_ids(workspace, phone)
        pending = 0
        for contact_id in contacts:
            pending += await client.delete_contact(workspace, contact_id)
    except Exception as exc:
        _retry_if_worth_it(exc, int(ctx.get("job_try", 1)))
        alert(
            "WORKER_TERMINAL",
            "engine_contact_erasure_failed",
            detail=(
                "a DPDP erasure could not erase the person's contact in the client's own "
                "voice platform workspace. The erasure task stays open; erase the contact in "
                "that workspace by hand and record the answer"
                f" ({type(exc).__name__})"
            ),
            tenant_id=str(tenant_id),
            request_id=str(request_id),
        )
        raise
    async with tenant_session(tenant_id) as session:
        task_id = (await session.execute(text(_TASK_SQL), {"rid": request_id})).scalar()
        if task_id is not None:
            await record_request_sent(
                session, task_id=task_id, vendor_reference=",".join(contacts) or "no-contact"
            )
            if pending == 0:
                await record_answer(
                    session,
                    task_id=task_id,
                    outcome="confirmed",
                    note=(
                        f"{len(contacts)} contact(s) erased in the client's workspace, "
                        "recordings included"
                        if contacts
                        else "the client's workspace holds no contact on this number"
                    ),
                )
    log.info(
        "engine_contact_erased",
        extra={
            "request_id": str(request_id),
            "contacts": len(contacts),
            "recordings_pending": pending,
        },
    )
    return f"contacts={len(contacts)} recordings_pending={pending}"


__all__ = [
    "ENGINE_CONTACT_ERASURE_JOB",
    "ENGINE_DNC_PUSH_JOB",
    "erase_engine_contact",
    "push_engine_dnc",
    "seal_subject",
]
