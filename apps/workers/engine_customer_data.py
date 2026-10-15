"""Person-level writes in a client's OWN ThinnestAI workspace: do-not-call and erasure (D-691).

Both are queued through the outbox in the transaction that made them owed —
`compliance/engine_dnc.queue_engine_dnc_push` for a suppression, `retention.
execute_deletion_request` for an erasure — and both ask `tenancy/engine_workspace.
own_workspace` AGAIN here, before anything is sent: a tenant whose workspace is not its own
is never written to, because the developer workspace holds every client's data.

`erase_engine_contact` finds the contact by the person's number in the client's workspace
and erases it (`DELETE /contacts/{id}`, recordings included; `api-reference/contacts/
delete-contact.md:7`). Each contact's queued recording count is recorded on the erasure's
`voice_engine` task (`compliance/processor_erasure`); the platform's `contact.erased`
delivery sets it to 0 when the last recording is gone (`workers/engine_workspace_events`).

`delete_engine_call_content` deletes each call's content at the platform (D-798,
`DELETE /calls/{id}/content`), in whichever workspace holds the call, and records the answer
on the call. A `voice_engine` task is confirmed by whichever of these finishes last
(`processor_erasure.settle_voice_engine_task`).

The person's number reaches this job sealed under the platform key, never in clear.
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

from arq import Retry
from calevate_shared.engine import tenant_of_pipecat_ref
from calevate_shared.engine_scope import raw_of, scope_of
from sqlalchemy import text

from apps.api.compliance.engine_dnc import (
    ENGINE_DNC_REMOVE_JOB,
    removal_context,
)
from apps.api.compliance.processor_erasure import (
    mark_task_requested,
    record_engine_contact_progress,
    settle_voice_engine_task,
)
from apps.api.core.alerting import alert
from apps.api.core.envelope import open_fields, seal_to_fields
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.session import tenant_session
from apps.api.engine.thinnest_customer_data import CallContentDeletion, thinnest_customer_data
from apps.api.engine.thinnest_workspace import is_developer_workspace
from apps.api.tenancy.engine_workspace import own_workspace

log = get_logger(__name__)

ENGINE_DNC_PUSH_JOB: Final = "push_engine_dnc"
ENGINE_CONTACT_ERASURE_JOB: Final = "erase_engine_contact"
#: `compliance/engine_content.ENGINE_CONTENT_DELETE_JOB`; equal by test.
ENGINE_CONTENT_DELETE_JOB: Final = "delete_engine_call_content"

#: How long a call that is still live, or booked and not yet rung, waits before it is asked
#: again (the platform answers 409 for it, delete-call-content.md:443-533).
_BUSY_RETRY_S: Final = 1800.0

_RETRY_AFTER_S: Final = (60.0, 600.0)


def _context(request_id: UUID) -> str:
    return f"engine_contact_erasure:{request_id}"


def seal_subject(phone_e164: str, *, request_id: UUID) -> dict[str, Any]:
    """The erasure subject's number, sealed and bound to its request, for the outbox."""
    return seal_to_fields(phone_e164, context=_context(request_id))


def _open_subject(sealed: Any, *, request_id: UUID) -> str:
    try:
        return open_fields(sealed, context=_context(request_id))
    except ValueError as exc:
        raise ProblemError(
            kind="validation",
            code="engine_erasure_subject_unreadable",
            title="A queued erasure could not be read",
            detail="The job carried an erasure subject with fields missing or unreadable.",
        ) from exc


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


_STILL_SUPPRESSED: Final = (
    "SELECT 1 FROM dnc_list WHERE phone_e164 = :phone "
    "AND (tenant_id = :tid OR tenant_id IS NULL) LIMIT 1"
)


async def remove_engine_dnc(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Take a number the client restored off its own workspace's do-not-call list.

    Asked against OUR list first: if the number went back on it after the restore (the
    person opted out again, or someone re-added it), the platform's entry is now the right
    one and is left in place.
    """
    tenant_id = UUID(str(payload["tenant_id"]))
    entry_id = UUID(str(payload["entry_id"]))
    workspace = await own_workspace(tenant_id)
    if workspace is None:
        log.info("engine_dnc_remove_skipped", extra={"tenant_id": str(tenant_id)})
        return "not_provisioned"
    try:
        try:
            phone = open_fields(payload.get("subject"), context=removal_context(entry_id))
        except ValueError as exc:
            raise ProblemError(
                kind="validation",
                code="engine_dnc_removal_unreadable",
                title="A queued do-not-call removal could not be read",
                detail="The job carried a number with fields missing or unreadable.",
            ) from exc
        async with tenant_session(tenant_id) as session:
            again = (
                await session.execute(text(_STILL_SUPPRESSED), {"phone": phone, "tid": tenant_id})
            ).first()
        if again is not None:
            log.info("engine_dnc_remove_superseded", extra={"tenant_id": str(tenant_id)})
            return "suppressed_again"
        await thinnest_customer_data().remove_do_not_call(workspace, phone)
    except Exception as exc:
        _retry_if_worth_it(exc, int(ctx.get("job_try", 1)))
        alert(
            "WORKER_TERMINAL",
            "engine_dnc_remove_failed",
            detail=(
                "a number the client took off its do-not-call list is still on its own voice "
                "platform workspace list, so the platform's agent and campaigns still refuse "
                "it. Our list no longer does; remove it in the client's workspace by hand"
                f" ({type(exc).__name__})"
            ),
            tenant_id=str(tenant_id),
            entry_id=str(entry_id),
        )
        raise
    log.info("engine_dnc_removed", extra={"tenant_id": str(tenant_id), "entry_id": str(entry_id)})
    return "removed"


# --- erasure --------------------------------------------------------------------------------


_TASK_SQL: Final = (
    "SELECT id FROM processor_erasure_tasks WHERE request_ref = :rid "
    "AND processor = 'voice_engine' ORDER BY id LIMIT 1"
)

#: A contact found and not yet confirmed gone, in the task's progress record.
_UNSETTLED: Final = 1


async def erase_engine_contact(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Erase the subject's contact in the client's own workspace; record the outcome.

    Every contact found is first recorded as unsettled (1), then its `recordingsPending`
    the moment its DELETE answers, because a retry finds the contact gone and learns nothing
    more (`processor_erasure.record_engine_contact_progress`). So a contact that vanished
    between attempts without our DELETE answering stays unsettled until the platform's
    `contact.erased` says it is gone, or an operator closes the task.
    """
    tenant_id = UUID(str(payload["tenant_id"]))
    request_id = UUID(str(payload["request_id"]))
    workspace = await own_workspace(tenant_id)
    if workspace is None:
        # Provisioned when the erasure ran, not now: the task stays open for a human, and
        # nothing is sent to a workspace that is not this client's.
        log.warning("engine_contact_erasure_skipped", extra={"request_id": str(request_id)})
        return "not_provisioned"
    async with tenant_session(tenant_id) as session:
        task_id = (await session.execute(text(_TASK_SQL), {"rid": request_id})).scalar()
    try:
        phone = _open_subject(payload.get("subject"), request_id=request_id)
        client = thinnest_customer_data()
        contacts = await client.contact_ids(workspace, phone)
        if task_id is not None and contacts:
            async with tenant_session(tenant_id) as session:
                await record_engine_contact_progress(
                    session, task_id=task_id, progress=dict.fromkeys(contacts, _UNSETTLED)
                )
        for contact_id in contacts:
            pending = await client.delete_contact(workspace, contact_id)
            if task_id is not None:
                async with tenant_session(tenant_id) as session:
                    await record_engine_contact_progress(
                        session, task_id=task_id, progress={contact_id: pending}
                    )
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
    known: dict[str, int] = {}
    if task_id is not None:
        async with tenant_session(tenant_id) as session:
            known = await record_engine_contact_progress(session, task_id=task_id, progress={})
            await settle_voice_engine_task(session, task_id=task_id)
    log.info(
        "engine_contact_erased",
        extra={
            "request_id": str(request_id),
            "contacts": len(contacts),
            "recordings_pending": sum(known.values()),
        },
    )
    return f"contacts={len(contacts)} recordings_pending={sum(known.values())}"


# --- call content -------------------------------------------------------------------------


_CALLS_SQL: Final = (
    "SELECT id, engine_call_id, engine_content_deleted_at, engine_content_recordings_pending "
    "FROM calls WHERE id = ANY(:ids) ORDER BY id"
)
_RECORD_SQL: Final = (
    "UPDATE calls SET engine_content_deleted_at = COALESCE(:at, engine_content_deleted_at, "
    "now()), engine_content_recordings_pending = :pending, updated_at = now() WHERE id = :id"
)
#: The `voice_engine` tasks naming any of these calls (their raw vendor ids), still awaiting
#: an answer; RLS keeps it to the tenant.
_TASKS_FOR_CALLS_SQL: Final = (
    "SELECT id FROM processor_erasure_tasks WHERE processor = 'voice_engine' "
    "AND status IN ('open', 'requested') AND jsonb_exists_any(vendor_refs, :refs) ORDER BY id"
)


def _workspace_of_call(handle: str) -> str | None:
    """The workspace a call lives in: its handle's scope (D-693), or None for a call in our
    developer workspace. A scope naming our developer workspace is refused rather than sent
    as a client header."""
    workspace = scope_of(handle)
    if workspace is not None and is_developer_workspace(workspace):
        raise ProblemError(
            kind="validation",
            code="engine_call_scope_invalid",
            title="A call is filed under the wrong workspace",
            detail="A call's handle names our own workspace as a client's.",
        )
    return workspace


async def _record_deletion(tenant_id: UUID, call_id: UUID, answer: CallContentDeletion) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(_RECORD_SQL),
            {"id": call_id, "at": answer.deleted_at, "pending": answer.recordings_pending},
        )


async def _settle_tasks(tenant_id: UUID, raw_ids: list[str]) -> int:
    """Move each erasure task naming these calls to `requested` (the platform has been asked
    by code) and confirm those now complete. Returns how many were confirmed."""
    if not raw_ids:
        return 0
    confirmed = 0
    async with tenant_session(tenant_id) as session:
        tasks = (
            (await session.execute(text(_TASKS_FOR_CALLS_SQL), {"refs": raw_ids})).scalars().all()
        )
        for task_id in tasks:
            await mark_task_requested(session, task_id=task_id)
            confirmed += int(await settle_voice_engine_task(session, task_id=task_id))
    return confirmed


async def delete_engine_call_content(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Delete these calls' content at the voice platform and record each answer (D-798).

    Idempotent: a call already confirmed deleted with nothing queued is skipped, and the
    platform answers a repeat with the first deletion's time. Each vendor request runs with
    no transaction open; each answer is written in a short one of its own, so a failure
    part-way keeps what was learned. A call still live or booked (409) is asked again later;
    a transient failure retries the job and, when the budget is spent, alarms, and the
    retention sweep's backstop queues the call again a day later.
    """
    tenant_id = UUID(str(payload["tenant_id"]))
    call_ids = [UUID(str(call)) for call in payload.get("call_ids", [])]
    async with tenant_session(tenant_id) as session:
        rows = (await session.execute(text(_CALLS_SQL), {"ids": call_ids})).all()
    client = thinnest_customer_data()
    tally = dict.fromkeys(("deleted", "gone", "busy", "skipped"), 0)
    asked: list[str] = []
    failure: Exception | None = None
    for call_id, handle, deleted_at, pending in rows:
        ref = str(handle or "")
        if not ref or tenant_of_pipecat_ref(ref) is not None:
            tally["skipped"] += 1
            continue
        if deleted_at is not None and not pending:
            tally["skipped"] += 1
            asked.append(raw_of(ref))
            continue
        try:
            answer = await client.delete_call_content(_workspace_of_call(ref), raw_of(ref))
        except Exception as exc:
            failure = failure or exc
            continue
        asked.append(raw_of(ref))
        if answer.outcome == "busy":
            tally["busy"] += 1
            continue
        # 404 and 410 hold nothing of the call to delete (a deleted customer workspace is
        # erased by the platform 30 days after its deletion, customers.md:104-161), so they
        # are recorded as deleted, at our clock.
        tally["deleted" if answer.outcome == "deleted" else "gone"] += 1
        await _record_deletion(tenant_id, UUID(str(call_id)), answer)
    confirmed = await _settle_tasks(tenant_id, asked)
    attempt = int(ctx.get("job_try", 1))
    if failure is not None:
        # A refusal of ours to fix (a key that is not a full key) is not retried.
        if not (isinstance(failure, ProblemError) and failure.kind == "business_rule"):
            _retry_if_worth_it(failure, attempt)
        alert(
            "WORKER_TERMINAL",
            "engine_call_content_delete_failed",
            detail=(
                "the voice platform could not delete the recording and transcript of one or "
                "more calls (a retention period ended or an erasure asked for it). Their "
                "content is still held there; the nightly retention sweep asks again in a day"
                f" ({type(failure).__name__})"
            ),
            tenant_id=str(tenant_id),
        )
        raise failure
    if tally["busy"] and attempt < WORKER_MAX_TRIES:
        raise Retry(defer=_BUSY_RETRY_S)
    summary = " ".join(f"{key}={value}" for key, value in tally.items())
    log.info(
        "engine_call_content_deleted",
        extra={"tenant_id": str(tenant_id), **tally, "tasks_confirmed": confirmed},
    )
    return f"{summary} tasks_confirmed={confirmed}"


__all__ = [
    "ENGINE_CONTACT_ERASURE_JOB",
    "ENGINE_CONTENT_DELETE_JOB",
    "ENGINE_DNC_PUSH_JOB",
    "ENGINE_DNC_REMOVE_JOB",
    "delete_engine_call_content",
    "erase_engine_contact",
    "push_engine_dnc",
    "remove_engine_dnc",
    "seal_subject",
]
