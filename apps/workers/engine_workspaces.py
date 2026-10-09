"""Each client's own ThinnestAI customer workspace: provision, keep, offboard (D-693).

Every job here is reached through the outbox or a cron, and every one is idempotent.

* `provision_engine_workspace` finds the customer carrying our reference before it creates
  one (`GET /customers?externalId=`, then `POST /customers` with an `Idempotency-Key`,
  `thinnest-findings/mirror/snapshots/2026-10-08/pages/api-reference/customers.md:18-102`),
  so a retry, a lost response or a second worker never makes a second workspace. A
  workspace the vendor still holds after a deletion is restored rather than replaced
  (`:136-161`). At the plan's customer cap (3 on pay-as-you-go, 100 on Pro, 1,000 on Scale,
  `:191-200`) the vendor answers 402 (`plan_limit` / `plan_required`, `errors.md:156-157`):
  the tenant is left in `plan_limit`, an operator is alarmed, and the client is told its
  account is being set up.
* `retry_engine_workspaces` is the daily sweep: every live tenant without a workspace row
  (the backfill of tenants made before D-693) and every tenant whose provisioning is still
  owed is queued through the same job.
* `submit_engine_business_details` sends the client's verified details to its workspace.
* `sweep_engine_workspaces` walks every client workspace each day, bounded and resumable:
  its business-details application read back (an expired one sent again), whether it still
  runs on our voice key while Studio voices are on (`using: developer`), and whether the
  clone copies we recorded for it are still there.
* `offboard_engine_workspace` runs when an account closes: numbers released
  (`?confirm=release`), agents deleted, the customer deleted (refused by the vendor while it
  still holds a rented number, so the numbers go first).
* `retire_moved_engine_agent` deletes the vendor agent an agent was recreated FROM, after the
  publish that recreated it in the client's workspace committed: never before, so a live
  agent is never stranded.

Ids and counts in every log line and alarm (hard rule 6).
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

from arq import Retry
from calevate_shared.engine_scope import scope_of
from sqlalchemy import text

from apps.api.agents.service import retire_in_call_actions
from apps.api.campaigns.engine_business_details import (
    refresh_business_details,
    submit_business_details,
)
from apps.api.campaigns.engine_numbers import (
    LAPSED_BUSINESS_STATUSES,
    alarm_lapsed_business_details,
    engine_number_provider,
)
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.core.settings import get_settings
from apps.api.db.session import admin_session, tenant_session
from apps.api.engine import get_engine
from apps.api.engine.catalogue import HostsVoices
from apps.api.engine.thinnest_actions import thinnest_actions
from apps.api.engine.thinnest_customers import PLAN_CUSTOMER_CAPS, thinnest_customers
from apps.api.engine.thinnest_numbers import thinnest_numbers
from apps.api.engine.thinnest_workspace import in_workspace
from apps.api.engine.vendor_http import EngineRejectedError
from apps.api.reliability.engine_webhooks import retire_agent_webhook
from apps.api.reliability.service import enqueue_outbox
from apps.api.tenancy.engine_workspace import (
    OWED_STATES,
    engine_has_workspaces,
    external_ref_for,
    is_own_workspace,
    queue_workspace_provisioning,
    read_workspace_state,
    workspace_directory,
)
from apps.workers.workspace_walk import WalkReport, walk_workspaces

log = get_logger(__name__)

SUBMIT_JOB: Final = "submit_engine_business_details"
RETIRE_JOB: Final = "retire_moved_engine_agent"
#: `compliance/engine_dnc.ENGINE_DNC_PUSH_JOB`, spelled here so the enqueue below is checkable.
DNC_PUSH_JOB: Final = "push_engine_dnc"

#: The customer's time zone (customers.md:57). Every client is in India.
CUSTOMER_TIMEZONE: Final = "Asia/Kolkata"

#: The vendor's codes for "your plan does not allow another customer" (errors.md:156-158).
PLAN_CODES: Final = frozenset({"plan_limit", "plan_required", "payment_required"})

#: Tenants queued per sweep tick, so a backfill of a long tenant list is spread over days
#: rather than spent against the vendor's rate limit in one minute.
PROVISION_SWEEP_BUDGET: Final = 50

#: Suppressions per do-not-call push job when a new workspace is filled from our list.
DNC_BACKFILL_CHUNK: Final = 200

_RETRY_AFTER_S: Final = (60.0, 600.0)
_LIVE_CALL_RETRY_S: Final = 300.0


def _retry_or_give_up(exc: Exception, attempt: int) -> None:
    permanent = isinstance(exc, ProblemError) and exc.kind in ("validation", "business_rule")
    if not permanent and attempt < WORKER_MAX_TRIES:
        raise Retry(defer=_RETRY_AFTER_S[min(attempt, len(_RETRY_AFTER_S)) - 1]) from exc


def _is_plan_refusal(exc: EngineRejectedError) -> bool:
    return exc.vendor_status == 402 or (exc.vendor_code or "") in PLAN_CODES


async def _set_state(tenant_id: UUID, *, status: str, code: str | None, attempt: bool) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE tenant_engine_workspaces SET status = :status, last_error_code = :code, "
                "attempts = attempts + :inc, updated_at = now() WHERE tenant_id = :tid"
            ),
            {"status": status, "code": code, "inc": 1 if attempt else 0, "tid": tenant_id},
        )


def _plan_cap() -> int:
    return PLAN_CUSTOMER_CAPS[get_settings().thinnest_customer_plan]


# --- provisioning ---------------------------------------------------------------------


async def _org(tenant_id: UUID) -> tuple[str, bool] | None:
    """`(name, open)` for the tenant, or None when it does not exist."""
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT name, status, deleted_at FROM organizations WHERE id = :tid"),
                {"tid": tenant_id},
            )
        ).first()
    if row is None:
        return None
    return str(row[0]), row[2] is None and row[1] != "churned"


async def _activate(tenant_id: UUID, workspace: str) -> None:
    """Record the workspace as the tenant's, and owe it the follow-ups, in one transaction:
    the business details (sent once the KYC record is verified) and the tenant's existing
    do-not-call list, pushed in chunks."""
    from apps.api.campaigns.engine_business_details import queue_business_details_submission

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE tenant_engine_workspaces SET status = 'active', workspace_id = :ws, "
                "provisioned_at = COALESCE(provisioned_at, now()), last_error_code = NULL, "
                "deleted_at = NULL, updated_at = now() WHERE tenant_id = :tid"
            ),
            {"ws": workspace, "tid": tenant_id},
        )
        await queue_business_details_submission(session, tenant_id=tenant_id)
        ids = [
            str(row)
            for row in (
                await session.execute(
                    text("SELECT id FROM dnc_list WHERE tenant_id = :tid ORDER BY id"),
                    {"tid": tenant_id},
                )
            ).scalars()
        ]
        for start in range(0, len(ids), DNC_BACKFILL_CHUNK):
            await enqueue_outbox(
                session,
                job=DNC_PUSH_JOB,
                payload={
                    "tenant_id": str(tenant_id),
                    "dnc_ids": ids[start : start + DNC_BACKFILL_CHUNK],
                },
            )
    log.info("engine_workspace_active", extra={"tenant_id": str(tenant_id)})


async def provision_engine_workspace(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Find or create the tenant's customer workspace; never two."""
    tenant_id = UUID(str(payload["tenant_id"]))
    if not engine_has_workspaces():
        return "not_applicable"
    org = await _org(tenant_id)
    if org is None:
        return "no_tenant"
    name, is_open = org
    async with tenant_session(tenant_id) as session:
        state = await read_workspace_state(session, tenant_id)
    if state.active:
        return "already_active"
    if not is_open or state.status in ("offboarding", "deleted"):
        return "not_owed"
    ref = external_ref_for(tenant_id)
    customers = thinnest_customers()
    try:
        # Our own id first, so it can never be recorded as this client's: both are `org_…`.
        developer = await customers.developer_workspace_id()
        found = await customers.find(ref)
        if found is None:
            archived = await customers.find(ref, archived=True)
            if archived is not None:
                found = await customers.restore(archived.workspace_id)
        if found is None:
            try:
                found = await customers.create(
                    name=name, external_id=ref, timezone=CUSTOMER_TIMEZONE
                )
            except EngineRejectedError as exc:
                if exc.vendor_status != 409:
                    raise
                # Our reference is taken: a create that raced this one, or one whose answer
                # was lost. Either way the workspace exists; read it.
                found = await customers.find(ref)
                if found is None:
                    raise
    except EngineRejectedError as exc:
        if _is_plan_refusal(exc):
            await _set_state(
                tenant_id, status="plan_limit", code=exc.vendor_code or "plan_limit", attempt=True
            )
            alert(
                "CORE_LOGIC",
                "engine_workspace_plan_limit",
                detail=(
                    "a client could not be given its own voice workspace because the voice "
                    "platform plan's customer limit is reached (the plan is set as "
                    f"{get_settings().thinnest_customer_plan}, which allows {_plan_cap()}; a "
                    "deleted workspace counts until it is erased). Until it has one, the client "
                    "cannot publish an agent or buy a number. Upgrade the plan in the voice "
                    "platform's console and update the ThinnestAI plan setting; the daily sweep "
                    "then provisions it, or use Retry on the client's admin page."
                ),
                tenant_id=str(tenant_id),
            )
            return "plan_limit"
        await _provision_failed(ctx, tenant_id, exc)
        raise
    except Exception as exc:
        await _provision_failed(ctx, tenant_id, exc)
        raise
    if found.workspace_id == developer or not is_own_workspace(found.workspace_id):
        await _set_state(
            tenant_id, status="failed", code="engine_workspace_is_developer", attempt=True
        )
        alert(
            "WORKER_TERMINAL",
            "engine_workspace_provisioning_failed",
            detail=(
                "the voice platform answered a client's own workspace with our developer "
                "workspace's id; it was not recorded, because a client's writes there would "
                "reach every legacy client. Check the customer list in the voice platform."
            ),
            tenant_id=str(tenant_id),
        )
        return "refused_developer_workspace"
    await _activate(tenant_id, found.workspace_id)
    return "active"


async def _provision_failed(job_ctx: dict[str, Any], tenant_id: UUID, exc: Exception) -> None:
    code = exc.code if isinstance(exc, ProblemError) else type(exc).__name__
    await _set_state(tenant_id, status="failed", code=str(code)[:64], attempt=True)
    _retry_or_give_up(exc, int(job_ctx.get("job_try", 1)))
    alert(
        "WORKER_TERMINAL",
        "engine_workspace_provisioning_failed",
        detail=(
            "a client's own voice workspace could not be created or found, so it cannot "
            f"publish an agent or buy a number ({code}). The daily sweep tries again; use "
            "Retry on the client's admin page once the cause is fixed."
        ),
        tenant_id=str(tenant_id),
    )


_LIVE_TENANTS: Final = (
    "SELECT id FROM organizations WHERE deleted_at IS NULL AND status <> 'churned' ORDER BY id"
)


async def retry_engine_workspaces(ctx: dict[str, Any]) -> str:
    """Daily. Queue provisioning for every live tenant that has no workspace yet — the
    backfill of tenants made before D-693 runs through here — and for every tenant whose
    provisioning is still owed. Bounded per tick; the rows it writes are its progress."""
    if not engine_has_workspaces():
        return "not_applicable"
    async with admin_session() as directory:
        tenants = [UUID(str(t)) for t in (await directory.execute(text(_LIVE_TENANTS))).scalars()]
    rows = {row.tenant_id: row for row in await workspace_directory()}
    owed = [
        tenant_id
        for tenant_id in tenants
        if tenant_id not in rows or rows[tenant_id].status in OWED_STATES
    ]
    queued = 0
    for tenant_id in owed[:PROVISION_SWEEP_BUDGET]:
        async with tenant_session(tenant_id) as session:
            queued += await queue_workspace_provisioning(session, tenant_id=tenant_id)
    deferred = max(len(owed) - PROVISION_SWEEP_BUDGET, 0)
    log.info(
        "engine_workspace_sweep",
        extra={"tenants": len(tenants), "owed": len(owed), "queued": queued, "deferred": deferred},
    )
    return f"owed={len(owed)} queued={queued} deferred={deferred}"


# --- business details -----------------------------------------------------------------


async def submit_engine_business_details(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Send the client's verified business details to its own workspace. A no-op until both
    the workspace is active and the KYC record is verified; whichever comes second queues
    this again."""
    tenant_id = UUID(str(payload["tenant_id"]))
    if not engine_has_workspaces():
        return "not_applicable"
    try:
        details = await submit_business_details(tenant_id)
    except ProblemError as exc:
        if exc.code in (
            "engine_workspace_not_provisioned",
            "business_details_kyc_not_verified",
        ):
            log.info(
                "engine_business_details_not_ready",
                extra={"tenant_id": str(tenant_id), "reason": exc.code},
            )
            return exc.code
        _retry_or_give_up(exc, int(ctx.get("job_try", 1)))
        _submit_failed(tenant_id, exc.code)
        raise
    except Exception as exc:
        _retry_or_give_up(exc, int(ctx.get("job_try", 1)))
        _submit_failed(tenant_id, type(exc).__name__)
        raise
    return details.status


def _submit_failed(tenant_id: UUID, code: str) -> None:
    alert(
        "WORKER_TERMINAL",
        "engine_business_details_submit_failed",
        detail=(
            "a verified client's business details could not be sent to its own voice "
            f"workspace ({code}), so it cannot buy a number yet. Check the business "
            "certificate on its KYC page, then use Send again on its admin page."
        ),
        tenant_id=str(tenant_id),
    )


async def _business_details_leg(tenant_id: UUID, tally: dict[str, int]) -> None:
    """Read one workspace's application back; send an expired one again; alarm when one
    becomes rejected or suspended (an alarm per change, not per day)."""
    async with tenant_session(tenant_id) as session:
        before = (await read_workspace_state(session, tenant_id)).business_status
    details = await refresh_business_details(tenant_id)
    if details.status != before:
        tally["changed"] += 1
        if details.status in LAPSED_BUSINESS_STATUSES - {"expired"}:
            alarm_lapsed_business_details(details, tenant_id=tenant_id)
    if details.status == "expired":
        async with tenant_session(tenant_id) as session:
            await enqueue_outbox(session, job=SUBMIT_JOB, payload={"tenant_id": str(tenant_id)})
        tally["resent"] += 1


async def _byok_leg(engine: object, workspace: str, tally: dict[str, int]) -> None:
    """A client's workspace runs on the developer workspace's voice key while it brings none
    of its own: `GET /byok` there answers `using: developer` (`api-reference/bring-your-own-
    keys/get-byok-status.md:465-473`). Anything else means its Studio agents would not speak."""
    if not isinstance(engine, HostsVoices):
        return
    with in_workspace(workspace):
        state = await engine.own_key_state()
    if state.using not in ("developer", "own"):
        tally["byok_not_inherited"] += 1


async def _clone_leg(
    engine: object, tenant_id: UUID, workspace: str, tally: dict[str, int]
) -> None:
    """Every clone copy we recorded for this workspace is still there; a copy the vendor no
    longer holds is forgotten, so the next publish on that voice makes it again."""
    if not isinstance(engine, HostsVoices):
        return
    async with tenant_session(tenant_id) as session:
        copies = (
            await session.execute(
                text(
                    "SELECT id, vendor_voice_id FROM engine_voice_clone_copies "
                    "WHERE tenant_id = :tid AND workspace_id = :ws ORDER BY id"
                ),
                {"tid": tenant_id, "ws": workspace},
            )
        ).all()
    for copy_id, vendor_voice_id in copies:
        with in_workspace(workspace):
            held = await engine.find_voice_clone(str(vendor_voice_id))
        if held is None:
            async with tenant_session(tenant_id) as session:
                await session.execute(
                    text("DELETE FROM engine_voice_clone_copies WHERE id = :id"), {"id": copy_id}
                )
            tally["clones_forgotten"] += 1


async def sweep_engine_workspaces(ctx: dict[str, Any]) -> str:
    """Daily. For each active client workspace, bounded and resumable: its business-details
    application, whether it still runs on our voice key while Studio voices are on, and
    whether the clone copies we recorded for it are still there. One workspace's failure is
    logged and the walk goes on."""
    if not engine_has_workspaces():
        return "not_applicable"
    engine = get_engine()
    studio_on = False
    if isinstance(engine, HostsVoices):
        try:
            studio_on = (await engine.own_key_state()).using != "none"
        except ProblemError as exc:
            log.warning("engine_byok_state_unreadable", extra={"code": exc.code})
    tally = dict.fromkeys(
        ("changed", "resent", "unreadable", "byok_not_inherited", "clones_forgotten"), 0
    )
    report = WalkReport()
    async for visit in walk_workspaces("engine_workspaces", include_developer=False, report=report):
        assert visit.tenant_id is not None and visit.workspace is not None
        try:
            if engine_number_provider() is not None:
                await _business_details_leg(visit.tenant_id, tally)
            if studio_on:
                await _byok_leg(engine, visit.workspace, tally)
            await _clone_leg(engine, visit.tenant_id, visit.workspace, tally)
        except ProblemError as exc:
            tally["unreadable"] += 1
            log.warning(
                "engine_workspace_sweep_leg_failed",
                extra={"tenant_id": str(visit.tenant_id), "code": exc.code},
            )
    if tally["byok_not_inherited"]:
        alert(
            "CORE_LOGIC",
            "engine_workspace_byok_not_inherited",
            detail=(
                f"{tally['byok_not_inherited']} client voice workspace(s) do not run on our "
                "voice key although Studio voices are switched on, so their Studio agents "
                "would not speak. Check those workspaces' own-keys switch in the voice "
                "platform's console: a client workspace must bring no keys of its own."
            ),
            count=str(tally["byok_not_inherited"]),
        )
    summary = " ".join(f"{key}={value}" for key, value in tally.items())
    return f"visited={report.visited} deferred={report.deferred} {summary}"


# --- offboarding ----------------------------------------------------------------------


_NUMBERS_SQL: Final = (
    "SELECT id, engine_number_ref FROM phone_numbers WHERE provider = :provider "
    "AND released_at IS NULL AND engine_number_ref IS NOT NULL ORDER BY created_at, id"
)
_ROUTES_SQL: Final = (
    "SELECT r.engine_agent_ref, r.agent_id FROM engine_agent_routes r "
    "WHERE r.tenant_id = :tid AND r.engine = :engine AND r.active ORDER BY r.engine_agent_ref"
)


async def offboard_engine_workspace(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Release the closed account's numbers, delete its agents, delete its customer."""
    tenant_id = UUID(str(payload["tenant_id"]))
    if not engine_has_workspaces():
        return "not_applicable"
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT status, workspace_id FROM tenant_engine_workspaces "
                    "WHERE tenant_id = :tid"
                ),
                {"tid": tenant_id},
            )
        ).first()
    if row is None or row[0] != "offboarding" or not row[1]:
        return "not_owed"
    workspace = str(row[1])
    engine = get_engine()
    released = deleted = 0
    try:
        provider = engine_number_provider()
        async with tenant_session(tenant_id) as session:
            numbers = (
                (await session.execute(text(_NUMBERS_SQL), {"provider": provider})).all()
                if provider
                else []
            )
        for number_id, ref in numbers:
            if scope_of(str(ref)) != workspace:
                continue
            # No refund of the current month (release-phone-number.md:7); the account is
            # closed, so ours stopped with it.
            await thinnest_numbers().release(str(ref))
            async with tenant_session(tenant_id) as session:
                await session.execute(
                    text(
                        "UPDATE phone_numbers SET released_at = now(), agent_id = NULL, "
                        "updated_at = now() WHERE id = :id AND released_at IS NULL"
                    ),
                    {"id": number_id},
                )
            released += 1
        async with tenant_session(tenant_id) as session:
            routes = (
                await session.execute(text(_ROUTES_SQL), {"tid": tenant_id, "engine": engine.name})
            ).all()
        for ref, agent_id in routes:
            if scope_of(str(ref)) != workspace:
                continue
            await retire_in_call_actions(agent_id=UUID(str(agent_id)), ref=str(ref))
            await engine.delete_agent(str(ref))
            async with tenant_session(tenant_id) as session:
                await session.execute(
                    text(
                        "UPDATE engine_agent_routes SET active = false, updated_at = now() "
                        "WHERE engine = :engine AND engine_agent_ref = :ref"
                    ),
                    {"engine": engine.name, "ref": str(ref)},
                )
            deleted += 1
        await thinnest_customers().delete(workspace)
    except Exception as exc:
        _retry_or_give_up(exc, int(ctx.get("job_try", 1)))
        alert(
            "WORKER_TERMINAL",
            "engine_workspace_offboarding_failed",
            detail=(
                "a closed client's own voice workspace could not be fully offboarded "
                f"({type(exc).__name__}; {released} number(s) released, {deleted} agent(s) "
                "deleted so far). A rented number left there is still charged to us monthly. "
                "Use Offboard again on the client's admin page, or release it in the voice "
                "platform's console."
            ),
            tenant_id=str(tenant_id),
        )
        raise
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE tenant_engine_workspaces SET status = 'deleted', deleted_at = now(), "
                "updated_at = now() WHERE tenant_id = :tid AND status = 'offboarding'"
            ),
            {"tid": tenant_id},
        )
    log.info(
        "engine_workspace_offboarded",
        extra={"tenant_id": str(tenant_id), "released": released, "agents_deleted": deleted},
    )
    return f"released={released} agents_deleted={deleted}"


# --- a recreated agent's old vendor agent -----------------------------------------------


async def retire_moved_engine_agent(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Delete the vendor agent an agent was recreated FROM (D-693). Queued by the publish
    that recreated it, so it runs only once the new agent is verified and committed. Waits
    while the old agent still has a call connected."""
    tenant_id = UUID(str(payload["tenant_id"]))
    agent_id = UUID(str(payload["agent_id"]))
    old_ref = str(payload["old_ref"])
    engine = get_engine()
    attempt = int(ctx.get("job_try", 1))
    try:
        if await thinnest_actions().has_live_call(old_ref):
            if attempt < WORKER_MAX_TRIES:
                raise Retry(defer=_LIVE_CALL_RETRY_S)
            alert(
                "WORKER_TERMINAL",
                "engine_agent_retire_failed",
                detail=(
                    "an agent recreated in its client's own voice workspace still had a call "
                    "on its old copy after every retry, so the old copy was left standing. It "
                    "answers nothing new; delete it in the voice platform's console once the "
                    "call ends."
                ),
                agent_id=str(agent_id),
            )
            return "left_live"
        await retire_in_call_actions(agent_id=agent_id, ref=old_ref)
        async with tenant_session(tenant_id) as session:
            await retire_agent_webhook(session, engine=engine.name, engine_agent_ref=old_ref)
        await engine.delete_agent(old_ref)
    except Retry:
        raise
    except Exception as exc:
        _retry_or_give_up(exc, attempt)
        alert(
            "WORKER_TERMINAL",
            "engine_agent_retire_failed",
            detail=(
                "the old copy of an agent recreated in its client's own voice workspace could "
                f"not be deleted ({type(exc).__name__}). It answers nothing new; delete it in "
                "the voice platform's console."
            ),
            agent_id=str(agent_id),
        )
        raise
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE engine_agent_routes SET active = false, updated_at = now() "
                "WHERE engine = :engine AND engine_agent_ref = :ref"
            ),
            {"engine": engine.name, "ref": old_ref},
        )
    log.info("engine_agent_retired_after_move", extra={"agent_id": str(agent_id)})
    return "retired"


__all__ = [
    "PLAN_CODES",
    "RETIRE_JOB",
    "SUBMIT_JOB",
    "offboard_engine_workspace",
    "provision_engine_workspace",
    "retire_moved_engine_agent",
    "retry_engine_workspaces",
    "submit_engine_business_details",
    "sweep_engine_workspaces",
]
