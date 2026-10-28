"""Owe the voice platform's copy of an erased account its deletion (D-922).

A tenant erasure (`workers/retention.execute_tenant_erasure`) erases our own records in one
transaction. What ThinnestAI holds for the account is removed after that commits, by
`workers/engine_tenant_erasure.erase_tenant_at_engine`, so a slow vendor can never roll an
erasure back. This module is the half that runs INSIDE the erasure's transaction: it reads
what the job will need before the erasure arms clear it, opens the `voice_engine` task the
job settles, and puts the job on the outbox.

What the job removes, VERIFIED-VENDOR-DOCS `thinnest-findings/mirror/snapshots/2026-10-28/
pages/api-reference/`:

* every agent of the account, in whichever workspace its handle names; an agent is deleted
  with its conversations, knowledge, actions and channels (`agents/delete-agent.md:7`);
* the contacts the account's own calls created in our shared developer workspace (a free
  trial's test calls), found by the number on each call (`contacts/list-contacts.md:7`) and
  erased with their calls, transcripts and recordings (`contacts/delete-contact.md:7`), but
  only a number no other client's call in that workspace reached;
* the account's own customer workspace (`customers/delete-customer.md:7`): refused with 409
  while it still rents a number, and erased by the platform 30 days after the delete.

The numbers reach the job sealed and bound to the request (hard rule 6), never in clear.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Final
from uuid import UUID

from calevate_shared.engine import tenant_of_pipecat_ref
from calevate_shared.engine_scope import raw_of
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.processor_erasure import (
    OWN_RUNTIME_ENGINES,
    open_tasks_for_request,
)
from apps.api.core.envelope import seal_to_fields
from apps.api.reliability.service import enqueue_outbox

#: `workers/engine_tenant_erasure.TENANT_ENGINE_ERASURE_JOB`; equal by test.
TENANT_ENGINE_ERASURE_JOB: Final = "erase_tenant_at_engine"

#: The task's `vendor_reference` until the job has looked the developer workspace's contacts
#: up. It also marks the task as one this job settles: tasks opened before D-922 carry NULL
#: and stay with the operator.
ENGINE_ERASURE_OWED: Final = "engine-erasure-owed"
#: The lookup failed for good. The numbers are erased here, so it cannot be repeated; the task
#: is never confirmed by code and waits for an operator.
CONTACTS_UNREACHED: Final = "contacts-not-looked-up"

#: The proof's `engine_deletion` for a tenant erasure whose voice-platform account data was
#: queued for deletion. A durable wire token (hard rule 4): never renamed once written.
VOICE_PLATFORM_ACCOUNT_DELETION: Final = "agents_contacts_and_workspace_deletion_requested"
VOICE_PLATFORM_ACCOUNT_SENTENCE: Final = (
    "this account's agents at the voice platform, its own workspace there and the contacts "
    "its calls created in the platform workspace it shared with other accounts are deleted "
    "automatically after this erasure; the platform erases a deleted workspace's contents "
    "30 days later; the outcome is recorded on the erasure task"
)

#: The other party on each of this tenant's calls held in our developer workspace (a handle
#: with no `@org_…` scope, D-693). Read before the erasure clears the numbers.
_PARTIES_SQL: Final = (
    "SELECT engine_call_id, CASE WHEN direction = 'inbound' THEN from_e164 ELSE to_e164 END "
    "FROM calls WHERE engine_call_id IS NOT NULL AND strpos(engine_call_id, '@') = 0"
)
_AGENT_REFS_SQL: Final = (
    "SELECT DISTINCT engine_agent_ref FROM engine_agent_routes WHERE tenant_id = :tid "
    "AND engine_agent_ref IS NOT NULL AND engine <> ALL(:own) ORDER BY 1"
)
_WORKSPACE_SQL: Final = (
    "SELECT 1 FROM tenant_engine_workspaces WHERE tenant_id = :tid "
    "AND workspace_id IS NOT NULL AND status <> 'deleted'"
)


def subject_context(request_id: UUID) -> str:
    """What a number is sealed to: this one erasure's job."""
    return f"engine_tenant_erasure:{request_id}"


async def developer_workspace_parties(session: AsyncSession) -> list[str]:
    """The numbers this tenant's calls in our developer workspace reached, sorted. Call it
    before the erasure arms clear `from_e164`/`to_e164`; RLS keeps it to the tenant."""
    rows = (await session.execute(text(_PARTIES_SQL))).all()
    return sorted(
        {
            str(party)
            for handle, party in rows
            if party and str(party).startswith("+") and tenant_of_pipecat_ref(str(handle)) is None
        }
    )


async def queue_engine_tenant_erasure(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    request_id: UUID,
    parties: Sequence[str],
) -> bool:
    """Open the `voice_engine` task and queue the job, in the erasure's transaction. False,
    and nothing written, when the platform holds nothing of this account to delete: no
    agent, no workspace of its own and no call in the developer workspace.

    The task quotes each agent's raw vendor id, the form `vendor_refs` accepts; the job reads
    the full handles, which name the workspace, from `engine_agent_routes` itself."""
    handles = [
        str(ref)
        for ref in (
            await session.execute(
                text(_AGENT_REFS_SQL), {"tid": tenant_id, "own": sorted(OWN_RUNTIME_ENGINES)}
            )
        ).scalars()
    ]
    has_workspace = (
        await session.execute(text(_WORKSPACE_SQL), {"tid": tenant_id})
    ).first() is not None
    if not handles and not has_workspace and not parties:
        return False
    await open_tasks_for_request(
        session,
        tenant_id=tenant_id,
        request_ref=request_id,
        request_kind="tenant",
        subject_ref=None,
        vendor_refs=sorted({raw_of(handle) for handle in handles}),
        processors=("voice_engine",),
        vendor_reference=ENGINE_ERASURE_OWED,
    )
    context = subject_context(request_id)
    payload: dict[str, Any] = {
        "tenant_id": str(tenant_id),
        "request_id": str(request_id),
        "subjects": [seal_to_fields(party, context=context) for party in parties],
    }
    # The literal, so `scripts/check_job_wiring` reads the job name at its enqueue site.
    await enqueue_outbox(session, job="erase_tenant_at_engine", payload=payload)
    return True


#: The tenant erasures of the session's tenant whose platform deletion this job still owes.
_OWED_SQL: Final = (
    "SELECT request_ref FROM processor_erasure_tasks WHERE processor = 'voice_engine' "
    "AND request_kind = 'tenant' AND status IN ('open', 'requested') "
    "AND vendor_reference IS NOT NULL ORDER BY opened_at"
)


async def owed_tenant_engine_erasures(session: AsyncSession) -> list[UUID]:
    """For the nightly backstop (`retention._release_tenant_engine_erasures`): a job that
    waited on our recording copy or on a rented number, or ran out of retries, runs again."""
    return [UUID(str(ref)) for ref in (await session.execute(text(_OWED_SQL))).scalars()]


__all__ = [
    "CONTACTS_UNREACHED",
    "ENGINE_ERASURE_OWED",
    "TENANT_ENGINE_ERASURE_JOB",
    "VOICE_PLATFORM_ACCOUNT_DELETION",
    "VOICE_PLATFORM_ACCOUNT_SENTENCE",
    "developer_workspace_parties",
    "owed_tenant_engine_erasures",
    "queue_engine_tenant_erasure",
    "subject_context",
]
