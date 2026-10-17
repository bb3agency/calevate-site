"""Each voice-platform workspace keeps calls no longer than the client's own policy (D-798).

`tenancy/engine_retention.py` says what each workspace's `callRetentionDays` should be and
why. Here:

* `sync_engine_retention` — from the outbox, when a client's workspace is provisioned: the
  number set and read back.
* `sweep_engine_retention` — hourly: our developer workspace and every client workspace read
  back (`GET /workspace`) and set again where it differs, alarmed either way. A value changed
  in the platform's console is the drift this exists for; a plan change moves the cap, and
  the next tick follows it.

OUR DEVELOPER WORKSPACE holds free-trial calls and every client's calls from before its own
workspace (D-693). No retention setting exists for that data as a whole, so it gets the
platform defaults of every new tenant (`scripts/seed.DEFAULT_RETENTION_POLICIES`): the
shortest promise any tenant there was made at sign-up. What it confirms, the period and the
plan's window, is recorded on `platform_state` (D-809), where `workers/recording_watch`
reads when the platform deletes a call held there.

Ids and day counts only in logs and alarms (hard rule 6).
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

from arq import Retry
from scripts.seed import DEFAULT_RETENTION_POLICIES

from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine.thinnest_customer_data import thinnest_customer_data
from apps.api.tenancy.engine_retention import (
    call_content_days,
    retention_to_send,
    wanted_retention_days,
)
from apps.api.tenancy.engine_workspace import (
    engine_has_workspaces,
    is_own_workspace,
    read_workspace_state,
    record_developer_retention,
    record_retention_check,
)
from apps.workers.workspace_walk import WalkReport, walk_workspaces

log = get_logger(__name__)

_RETRY_AFTER_S: Final = (60.0, 600.0)

#: The developer workspace's period: the defaults every tenant is created with.
DEVELOPER_RETENTION_DAYS: Final = call_content_days(
    (str(policy["data_category"]), int(policy["ttl_days"])) for policy in DEFAULT_RETENTION_POLICIES
)


async def _apply(
    workspace: str | None, wanted: int | None, *, repair: bool
) -> tuple[str, int, int]:
    """Read the workspace's retention, set it where it differs, read the answer back.
    Returns `(outcome, days now set, plan window)`; outcome is `in_step`, `set` or
    `repaired`. An answer naming another number is refused rather than taken as done."""
    client = thinnest_customer_data()
    held = await client.read_retention(workspace)
    target = retention_to_send(wanted, held.plan_retention_days)
    if wanted is not None and wanted > held.plan_retention_days:
        # The platform keeps less than we do: stricter than the client's policy, and fine.
        log.info(
            "engine_retention_capped_by_plan",
            extra={"wanted": wanted, "plan_days": held.plan_retention_days},
        )
    if held.call_retention_days == target:
        return "in_step", target, held.plan_retention_days
    if repair:
        log.warning(
            "engine_retention_drift",
            extra={"held": held.call_retention_days, "wanted": target},
        )
    after = await client.set_retention(workspace, target)
    if after.call_retention_days != target:
        # `engine_bad_response`: the answer is not one we can use, whatever its status.
        raise ProblemError(
            kind="dependency",
            code="engine_bad_response",
            title="The voice platform did not keep the retention period",
            detail="The voice platform answered with another retention period.",
            failure_stage="CORE_LOGIC",
        )
    return ("repaired" if repair else "set"), target, after.plan_retention_days


async def _client_leg(tenant_id: UUID, workspace: str, *, repair: bool) -> str:
    async with tenant_session(tenant_id) as session:
        wanted = await wanted_retention_days(session, tenant_id)
    try:
        outcome, days, plan = await _apply(workspace, wanted, repair=repair)
    except ProblemError as exc:
        async with tenant_session(tenant_id) as session:
            await record_retention_check(session, tenant_id, error_code=exc.code)
        raise
    async with tenant_session(tenant_id) as session:
        await record_retention_check(session, tenant_id, days=days, plan_days=plan)
    return outcome


async def _developer_leg() -> str:
    """Our developer workspace held at `DEVELOPER_RETENTION_DAYS`, and what it confirmed
    recorded (D-809): `workers/recording_watch` dates the platform's deletion of a trial or
    pre-D-693 call from it. A failure leaves the last confirmed answer in place."""
    outcome, days, plan = await _apply(None, DEVELOPER_RETENTION_DAYS, repair=True)
    async with untenanted_session() as session:
        await record_developer_retention(session, days=days, plan_days=plan)
    return outcome


def _alarm(repaired: int, failed: int) -> None:
    if repaired:
        alert(
            "CORE_LOGIC",
            "engine_workspace_retention_repaired",
            detail=(
                f"{repaired} voice platform workspace(s) kept calls for a different number of "
                "days than our retention policy and were set back. Find out who changed them "
                "on the voice platform."
            ),
            count=str(repaired),
        )
    if failed:
        alert(
            "CORE_LOGIC",
            "engine_workspace_retention_drift",
            detail=(
                f"{failed} voice platform workspace(s) could not be set to keep calls for our "
                "retention period, so the platform may keep recordings and transcripts longer "
                "than the client's policy. The ops page shows each client's last error code; "
                "runbooks/processor-erasure.md §6 says what to do."
            ),
            count=str(failed),
        )


async def sync_engine_retention(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """From the outbox: the client's call retention set on its own workspace."""
    tenant_id = UUID(str(payload["tenant_id"]))
    if not engine_has_workspaces():
        return "not_applicable"
    async with tenant_session(tenant_id) as session:
        state = await read_workspace_state(session, tenant_id)
    if not state.active or state.workspace_id is None or not is_own_workspace(state.workspace_id):
        return "no_workspace"
    attempt = int(ctx.get("job_try", 1))
    try:
        return await _client_leg(tenant_id, state.workspace_id, repair=False)
    except Exception as exc:
        if attempt < WORKER_MAX_TRIES:
            raise Retry(defer=_RETRY_AFTER_S[min(attempt, len(_RETRY_AFTER_S)) - 1]) from exc
        _alarm(0, 1)
        raise


async def sweep_engine_retention(ctx: dict[str, Any]) -> str:
    """Hourly: every workspace's call retention read back and repaired, bounded and resumed
    from a cursor like every workspace walk. One workspace's failure is counted and the walk
    goes on."""
    del ctx
    if not engine_has_workspaces():
        return "not_applicable"
    tally = dict.fromkeys(("in_step", "repaired", "failed"), 0)
    report = WalkReport()
    async for visit in walk_workspaces("engine_retention", report=report):
        try:
            if visit.tenant_id is None or visit.workspace is None:
                outcome = await _developer_leg()
            else:
                outcome = await _client_leg(visit.tenant_id, visit.workspace, repair=True)
        except ProblemError as exc:
            tally["failed"] += 1
            log.warning(
                "engine_retention_check_failed",
                extra={
                    "tenant_id": str(visit.tenant_id) if visit.tenant_id else None,
                    "code": exc.code,
                },
            )
            continue
        tally[outcome] += 1
    _alarm(tally["repaired"], tally["failed"])
    summary = " ".join(f"{key}={value}" for key, value in tally.items())
    return f"visited={report.visited} deferred={report.deferred} {summary}"


__all__ = [
    "DEVELOPER_RETENTION_DAYS",
    "sweep_engine_retention",
    "sync_engine_retention",
]
