"""Delete an erased account's data at the voice platform (D-922, founder 28 Oct 2026).

Queued by `compliance/engine_tenant_erasure.queue_engine_tenant_erasure` in the erasure's
transaction, with the `voice_engine` task it settles; the nightly retention sweep queues it
again while that task is owed (`retention._release_tenant_engine_erasures`). Each run:

1. On its first run, looks up the contacts the account's calls created in our developer
   workspace, by the numbers the erasure read before clearing them, leaving out any number
   another client's call in that workspace reached. The contacts found are recorded on the
   task as held, so a later run (which carries no numbers) can delete them.
2. Waits, deleting nothing, while one of the account's calls inside the 90-day floor has no
   recording copy of ours: every deletion below takes the platform's recordings with it,
   the rule `engine_content.calls_awaiting_our_copy` applies to a person's erasure (D-810).
3. Deletes every agent of the account, in whichever workspace its handle names.
4. Erases each contact recorded in step 1.
5. Deletes the account's own customer workspace. Refused with 409 while it still rents a
   number (a number hold, D-860, keeps one until it ends); the task then stays open and the
   nightly run asks again.
6. Confirms the task once 3-5 are done.

A 404 is the deletion's postcondition throughout, and a 410 means the workspace holding the
object is already deleted. Never the developer workspace itself, and in it only objects this
account owns: its own agents (by its route rows) and its own callers' contacts.
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

from arq import Retry
from calevate_shared.backoff import ladder_delay_s
from calevate_shared.engine import PIPECAT_REF_PREFIX
from calevate_shared.engine_scope import scope_of
from sqlalchemy import text

from apps.api.compliance.deletion import RECORDING_FLOOR_DAYS
from apps.api.compliance.engine_content import deletes_call_content
from apps.api.compliance.engine_tenant_erasure import (
    CONTACTS_UNREACHED,
    ENGINE_ERASURE_OWED,
    subject_context,
)
from apps.api.compliance.processor_erasure import (
    CALL_READY_SQL,
    held_contacts,
    mark_task_requested,
    record_answer,
    record_engine_contact_progress,
)
from apps.api.core.alerting import alert
from apps.api.core.envelope import open_fields
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine
from apps.api.engine.thinnest_customer_data import thinnest_customer_data
from apps.api.engine.thinnest_customers import thinnest_customers
from apps.api.engine.thinnest_workspace import tenant_erasure_in_developer_workspace
from apps.api.engine.vendor_http import EngineRejectedError
from apps.api.tenancy.engine_workspace import is_own_workspace

log = get_logger(__name__)

#: `compliance/engine_tenant_erasure.TENANT_ENGINE_ERASURE_JOB`; equal by test.
TENANT_ENGINE_ERASURE_JOB: Final = "erase_tenant_at_engine"

_RETRY_AFTER_S: Final = (60.0, 600.0)

_TASK_SQL: Final = (
    "SELECT id, status, vendor_reference FROM processor_erasure_tasks "
    "WHERE request_ref = :rid AND processor = 'voice_engine' AND request_kind = 'tenant'"
)
#: The account's calls whose platform recording may not go yet (`CALL_READY_SQL`).
_AWAITING_COPY_SQL: Final = (
    "SELECT count(*) FROM calls c WHERE c.engine_call_id IS NOT NULL "
    f"AND c.engine_call_id NOT LIKE :own AND NOT {CALL_READY_SQL}"
)
#: Every agent this account ever published at this engine, active or withdrawn, and only one
#: no other account's route names (routes are globally readable).
_AGENTS_SQL: Final = (
    "SELECT DISTINCT r.engine_agent_ref FROM engine_agent_routes r "
    "WHERE r.tenant_id = :tid AND r.engine = :engine AND r.engine_agent_ref IS NOT NULL "
    "AND NOT EXISTS (SELECT 1 FROM engine_agent_routes o WHERE o.engine = r.engine "
    "AND o.engine_agent_ref = r.engine_agent_ref AND o.tenant_id <> r.tenant_id) ORDER BY 1"
)
_WORKSPACE_SQL: Final = (
    "SELECT status, workspace_id FROM tenant_engine_workspaces WHERE tenant_id = :tid"
)
_WORKSPACE_DELETED_SQL: Final = (
    "UPDATE tenant_engine_workspaces SET status = 'deleted', deleted_at = now(), "
    "updated_at = now() WHERE tenant_id = :tid AND status <> 'deleted'"
)
#: The other accounts that ever ran an agent at this engine: the only ones whose calls can be
#: in our developer workspace.
_OTHER_TENANTS_SQL: Final = (
    "SELECT DISTINCT tenant_id FROM engine_agent_routes "
    "WHERE engine = :engine AND tenant_id <> :tid ORDER BY 1"
)
#: Which of these numbers one of the session tenant's developer-workspace calls reached.
_SHARED_SQL: Final = (
    "SELECT from_e164, to_e164 FROM calls WHERE engine_call_id IS NOT NULL "
    "AND strpos(engine_call_id, '@') = 0 "
    "AND (from_e164 = ANY(:phones) OR to_e164 = ANY(:phones))"
)

#: What the workspace step came to.
_WORKSPACE_DONE: Final = frozenset({"none", "already_deleted", "deleted"})


def _retry_if_worth_it(exc: Exception, attempt: int) -> None:
    permanent = isinstance(exc, ProblemError) and exc.kind in ("validation", "business_rule")
    if not permanent and attempt < WORKER_MAX_TRIES:
        raise Retry(defer=ladder_delay_s(_RETRY_AFTER_S, attempt)) from exc


def _gone(exc: Exception) -> bool:
    """A 410: the customer workspace holding the object is deleted, and the platform erases
    everything in it 30 days later (`customers/delete-customer.md:7`)."""
    return isinstance(exc, EngineRejectedError) and exc.vendor_status == 410


async def _shared_elsewhere(tenant_id: UUID, phones: list[str]) -> set[str]:
    """The numbers a call of ANOTHER account in the developer workspace also reached. Each
    account is read in its own tenant session, so no RLS is bypassed; a contact on one of
    these numbers holds that account's calls too and is not ours to erase."""
    if not phones:
        return set()
    async with untenanted_session() as session:
        others = [
            UUID(str(t))
            for t in (
                await session.execute(
                    text(_OTHER_TENANTS_SQL), {"engine": get_settings().engine, "tid": tenant_id}
                )
            ).scalars()
        ]
    shared: set[str] = set()
    for other in others:
        remaining = [phone for phone in phones if phone not in shared]
        if not remaining:
            break
        async with tenant_session(other) as session:
            rows = (await session.execute(text(_SHARED_SQL), {"phones": remaining})).all()
        shared.update(value for row in rows for value in row if value in remaining)
    return shared


async def _find_contacts(tenant_id: UUID, request_id: UUID, sealed: list[Any]) -> list[str]:
    """Step 1: the developer workspace's contacts on this account's own numbers."""
    context = subject_context(request_id)
    try:
        phones = sorted({open_fields(item, context=context) for item in sealed})
    except ValueError as exc:
        raise ProblemError(
            kind="validation",
            code="engine_tenant_erasure_subject_unreadable",
            title="A queued erasure could not be read",
            detail="The job carried a number with fields missing or unreadable.",
        ) from exc
    shared = await _shared_elsewhere(tenant_id, phones)
    client = thinnest_customer_data()
    found: set[str] = set()
    with tenant_erasure_in_developer_workspace():
        for phone in phones:
            if phone not in shared:
                found.update(await client.contact_ids(None, phone))
    if shared:
        log.info(
            "engine_tenant_erasure_contacts_shared",
            extra={"request_id": str(request_id), "shared": len(shared)},
        )
    return sorted(found)


async def _delete_agents(tenant_id: UUID, deleted_workspace: str | None) -> int:
    """Step 3. An agent in a workspace already deleted is skipped: that delete took it."""
    engine = get_engine()
    async with tenant_session(tenant_id) as session:
        handles = [
            str(ref)
            for ref in (
                await session.execute(text(_AGENTS_SQL), {"tid": tenant_id, "engine": engine.name})
            ).scalars()
        ]
    deleted = 0
    for handle in handles:
        if deleted_workspace is not None and scope_of(handle) == deleted_workspace:
            continue
        try:
            await engine.delete_agent(handle)
        except EngineRejectedError as exc:
            if not _gone(exc):
                raise
        deleted += 1
    return deleted


async def _delete_contacts(tenant_id: UUID, task_id: UUID, reference: str | None) -> int:
    """Step 4: erase each contact the task holds back. Returns those erased this run."""
    contacts = held_contacts(reference)
    client = thinnest_customer_data()
    for contact_id in contacts:
        with tenant_erasure_in_developer_workspace():
            pending = await client.delete_contact(None, contact_id)
        async with tenant_session(tenant_id) as session:
            await record_engine_contact_progress(
                session, task_id=task_id, progress={contact_id: pending}
            )
    return len(contacts)


async def _delete_workspace(tenant_id: UUID) -> str:
    """Step 5: `none`, `already_deleted`, `deleted`, `holds_numbers` or `refused`."""
    async with tenant_session(tenant_id) as session:
        row = (await session.execute(text(_WORKSPACE_SQL), {"tid": tenant_id})).first()
    if row is None or not row[1]:
        return "none"
    if row[0] == "deleted":
        return "already_deleted"
    workspace = str(row[1])
    if not is_own_workspace(workspace):
        # A row naming our developer workspace is a provisioning defect; deleting it would
        # erase every trial account's agents and callers.
        log.error("engine_tenant_erasure_workspace_refused", extra={"tenant_id": str(tenant_id)})
        return "refused"
    try:
        await thinnest_customers().delete(workspace)
    except EngineRejectedError as exc:
        if exc.vendor_status == 409:
            return "holds_numbers"
        if not _gone(exc):
            raise
    async with tenant_session(tenant_id) as session:
        await session.execute(text(_WORKSPACE_DELETED_SQL), {"tid": tenant_id})
    return "deleted"


async def _read_task(request_id: UUID, tenant_id: UUID) -> Any:
    async with tenant_session(tenant_id) as session:
        return (await session.execute(text(_TASK_SQL), {"rid": request_id})).first()


async def erase_tenant_at_engine(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Delete an erased account's agents, developer-workspace contacts and own workspace at
    the voice platform, and confirm its `voice_engine` task. Idempotent: every step is a
    delete whose repeat answers 404 or 410, and the task records what is done."""
    tenant_id = UUID(str(payload["tenant_id"]))
    request_id = UUID(str(payload["request_id"]))
    if not deletes_call_content():
        return "not_applicable"
    task = await _read_task(request_id, tenant_id)
    if task is None:
        return "no_task"
    if task.status not in ("open", "requested"):
        return "already_settled"
    task_id = UUID(str(task.id))
    attempt = int(ctx.get("job_try", 1))

    if task.vendor_reference == ENGINE_ERASURE_OWED and "subjects" in payload:
        try:
            found = await _find_contacts(tenant_id, request_id, list(payload["subjects"]))
        except Exception as exc:
            _retry_if_worth_it(exc, attempt)
            async with tenant_session(tenant_id) as session:
                await session.execute(
                    text(
                        "UPDATE processor_erasure_tasks SET vendor_reference = :vref, "
                        "updated_at = now() WHERE id = :tid"
                    ),
                    {"tid": task_id, "vref": CONTACTS_UNREACHED},
                )
            alert(
                "WORKER_TERMINAL",
                "engine_tenant_erasure_failed",
                detail=(
                    "an erased account's contacts in our shared voice platform workspace could "
                    "not be looked up, and the numbers they were found by are now erased here, "
                    "so code cannot try again. Its agents and own workspace are still deleted; "
                    f"the erasure task stays open for an operator ({type(exc).__name__})"
                ),
                tenant_id=str(tenant_id),
                request_id=str(request_id),
            )
        else:
            async with tenant_session(tenant_id) as session:
                await record_engine_contact_progress(
                    session, task_id=task_id, progress={}, held=found
                )
        task = await _read_task(request_id, tenant_id)

    async with tenant_session(tenant_id) as session:
        waiting = int(
            (
                await session.execute(
                    text(_AWAITING_COPY_SQL),
                    {"own": f"{PIPECAT_REF_PREFIX}:%", "floor": RECORDING_FLOOR_DAYS},
                )
            ).scalar_one()
        )
    if waiting:
        log.info(
            "engine_tenant_erasure_held",
            extra={"request_id": str(request_id), "calls_waiting": waiting},
        )
        return f"held calls_waiting={waiting}"

    try:
        async with tenant_session(tenant_id) as session:
            row = (await session.execute(text(_WORKSPACE_SQL), {"tid": tenant_id})).first()
        deleted_workspace = str(row[1]) if row is not None and row[0] == "deleted" else None
        agents = await _delete_agents(tenant_id, deleted_workspace)
        contacts = await _delete_contacts(tenant_id, task_id, task.vendor_reference)
        workspace = await _delete_workspace(tenant_id)
    except Exception as exc:
        _retry_if_worth_it(exc, attempt)
        alert(
            "WORKER_TERMINAL",
            "engine_tenant_erasure_failed",
            detail=(
                "an erased account's data at the voice platform could not be fully deleted "
                f"({type(exc).__name__}). The erasure task stays open and the nightly "
                "retention sweep asks again; read the engine_error log lines for the tenant"
            ),
            tenant_id=str(tenant_id),
            request_id=str(request_id),
        )
        raise

    task = await _read_task(request_id, tenant_id)
    reference = task.vendor_reference if task is not None else None
    contacts_known = reference not in (ENGINE_ERASURE_OWED, CONTACTS_UNREACHED) and not (
        held_contacts(reference)
    )
    confirmed = False
    if workspace in _WORKSPACE_DONE and contacts_known and task is not None:
        async with tenant_session(tenant_id) as session:
            await mark_task_requested(session, task_id=task_id)
            confirmed = await record_answer(
                session,
                task_id=task_id,
                outcome="confirmed",
                note=(
                    "deleted at the voice platform by code (D-922): the account's agents, "
                    "its contacts in the shared workspace, and its own workspace "
                    f"({workspace.replace('_', ' ')})"
                ),
            )
    elif workspace == "holds_numbers":
        log.warning(
            "engine_tenant_erasure_workspace_holds_numbers",
            extra={"tenant_id": str(tenant_id), "request_id": str(request_id)},
        )
    log.info(
        "engine_tenant_erased",
        extra={
            "request_id": str(request_id),
            "agents": agents,
            "contacts": contacts,
            "workspace": workspace,
            "confirmed": confirmed,
        },
    )
    return f"agents={agents} contacts={contacts} workspace={workspace} confirmed={confirmed}"


__all__ = ["TENANT_ENGINE_ERASURE_JOB", "erase_tenant_at_engine"]
