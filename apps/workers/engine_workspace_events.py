"""Events about a whole voice-platform workspace: an erased contact, a change to its own keys.

ThinnestAI sends two events that belong to no call and no agent (VERIFIED-VENDOR-DOCS,
`thinnest-findings/mirror/snapshots/2026-10-15/pages/api-reference/webhooks.md:536-597`):

* `contact.erased` `{contactId, erasedAt}` — sent once, when a contact deleted with
  `DELETE /contacts/{id}` is gone with its last recording. It closes the contact half of the
  erasure that asked for it (`processor_erasure.record_contact_erased`), which until then
  waited on recordings the platform was still retrying.
* `byok.changed` `{change, kind, provider, byokEnabled, scope}` — a key added, replaced,
  removed or refused at save, or the own-keys switch or scope changed. It never carries key
  material; only the enums and ids are logged. The workspace's own-key checks run at once:
  our Cartesia key for Studio (`studio_voice_key`) and our Google key for our own model
  (`own_model_key`). The hourly sweeps stay: the event is not sent for a model change, and
  saved keys are never re-checked by the platform, so a key that stops working shows up only
  as `call.problem` `byok_failed` (webhooks.md:589-592).

WHICH CLIENT. The delivery reaches us on one agent's endpoint, whose handle names the
workspace (D-693). A developer-wide endpoint would name it in `data.workspaceId` instead,
which voice-runtime already refused when it disagreed with the endpoint's
(`signed_intake.keyed_event`). The tenant is the one whose workspace row holds that id
(`tenancy/engine_workspace.tenant_for_workspace`), cross-checked against the endpoint's own
route, and only that tenant's session is opened, so a delivery for one client's workspace
cannot reach another client's rows.

OUR OWN WRITES ECHO BACK. Every key we install and every switch we flip is reported too. The
checks are read-first: a workspace already as we want it is recorded `ok` and nothing is
written, so our own write's echo ends there instead of starting a repair loop. A lease per
workspace runs one check at a time, so the burst one change of ours produces (a key and a
switch, each its own event) is checked in turn rather than concurrently.
"""

from __future__ import annotations

import json
import secrets
from typing import Any, Final, NoReturn, Protocol, runtime_checkable
from uuid import UUID

from arq import Retry
from calevate_shared.backoff import jittered_delay_s, ladder_delay_s
from calevate_shared.engine_scope import scope_of
from calevate_shared.events import EngineByokChanged, EngineContactErased
from sqlalchemy import text

from apps.api.compliance.processor_erasure import record_contact_erased
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.core.redis import get_redis, release_lease
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine
from apps.api.engine.catalogue import RunsOwnModel
from apps.api.reliability.engine_intake_keys import open_delivery
from apps.api.reliability.service import mark_inbox_failed, mark_inbox_processed
from apps.api.tenancy.engine_workspace import (
    is_own_workspace,
    own_model_enabled,
    read_workspace_state,
    studio_enabled,
    tenant_for_workspace,
)
from apps.workers.own_model_key import check_developer_own_model, check_own_model_workspace
from apps.workers.studio_voice_key import (
    check_developer_studio,
    check_studio_workspace,
    hosting_engine,
)

log = get_logger(__name__)

#: Enqueued by voice-runtime (`signed_intake.ENGINE_WORKSPACE_EVENT_JOB`); equal by test.
ENGINE_WORKSPACE_EVENT_JOB: Final = "ingest_engine_workspace_event"

#: One own-key check per workspace at a time. A repair walks every published agent with two
#: vendor requests each, so no fixed estimate bounds it; arq's `job_timeout` (300 s) does,
#: and the lease outlives it so a running check is never overlapped. A crashed holder still
#: frees it on its own.
BYOK_LEASE_S: Final = 330
_BYOK_LEASE_KEY: Final = "calevate:byok-check:{workspace}"
#: How long an event waits for the lease before it is tried again.
_LEASE_RETRY_S: Final = 30.0
_RETRY_AFTER_S: Final = (30.0, 120.0)

_ROUTE_SQL: Final = (
    "SELECT tenant_id FROM engine_agent_routes WHERE engine = :engine AND engine_agent_ref = :ref"
)


@runtime_checkable
class ReadsWorkspaceEvents(Protocol):
    """An adapter that turns a verified workspace delivery into OUR event."""

    def parse_contact_erased(self, payload: dict[str, Any]) -> EngineContactErased | None: ...

    def parse_byok_changed(self, payload: dict[str, Any]) -> EngineByokChanged | None: ...


def _unreadable(detail: str) -> ProblemError:
    return ProblemError(
        kind="validation",
        code="engine_delivery_unreadable",
        title="A queued engine delivery could not be read",
        detail=detail,
    )


def _event_of(payload: dict[str, Any]) -> EngineContactErased | EngineByokChanged:
    engine_name = str(payload["engine"])
    delivery = payload.get("delivery")
    if not isinstance(delivery, dict):
        raise _unreadable("the job carried no delivery")
    document = open_delivery(
        delivery, engine=engine_name, execution_id=str(payload["execution_id"])
    )
    try:
        body = json.loads(document)
    except ValueError as exc:
        raise _unreadable("the delivered document is not JSON") from exc
    engine = get_engine()
    if not isinstance(engine, ReadsWorkspaceEvents) or not isinstance(body, dict):
        raise _unreadable(f"the {engine.name} adapter cannot read a workspace event")
    event = engine.parse_contact_erased(body) or engine.parse_byok_changed(body)
    if event is None:
        raise _unreadable("the delivered document is not a workspace event")
    return event


async def _route_tenant(engine: str, ref: str) -> UUID | None:
    async with untenanted_session() as session:
        tenant = (await session.execute(text(_ROUTE_SQL), {"engine": engine, "ref": ref})).scalar()
    return UUID(str(tenant)) if tenant is not None else None


async def _whose(
    payload: dict[str, Any], event: EngineContactErased | EngineByokChanged
) -> tuple[str | None, UUID | None] | None:
    """`(workspace, tenant)` the event is about: `(None, None)` for our developer workspace,
    `(workspace, None)` for a workspace no tenant holds, and None when the delivery and the
    endpoint it came through disagree about the client."""
    ref = str(payload["engine_agent_ref"])
    endpoint_workspace = scope_of(ref)
    if endpoint_workspace is not None and event.workspace not in (None, endpoint_workspace):
        return None
    workspace = endpoint_workspace or event.workspace
    if workspace is None:
        return None, None
    tenant = await tenant_for_workspace(workspace)
    if endpoint_workspace is not None and tenant is not None:
        route_tenant = await _route_tenant(str(payload["engine"]), ref)
        if route_tenant is not None and route_tenant != tenant:
            return None
    return workspace, tenant


async def _contact_erased(
    event: EngineContactErased, workspace: str | None, tenant: UUID | None
) -> str:
    if workspace is None:
        # We never erase a contact in our developer workspace (D-691), so nothing waits on it.
        log.info("engine_contact_erased_unowned", extra={"workspace": "developer"})
        return "developer_workspace"
    if tenant is None:
        log.warning("engine_contact_erased_unattributable", extra={"workspace": workspace})
        return "unattributable"
    async with tenant_session(tenant) as session:
        touched = await record_contact_erased(session, contact_id=event.contact_id)
    log.info(
        "engine_contact_erased_recorded",
        extra={"tenant_id": str(tenant), "contact_id": event.contact_id, "tasks": len(touched)},
    )
    return f"tasks={len(touched)}"


async def _byok_changed(
    event: EngineByokChanged, workspace: str | None, tenant: UUID | None, *, attempt: int
) -> str:
    log.info(
        "engine_byok_changed",
        extra={
            "tenant_id": str(tenant) if tenant else None,
            "change": event.change,
            "kind": event.kind,
            "provider": event.provider,
            "byok_enabled": event.byok_enabled,
            "scope": event.scope,
        },
    )
    engine = hosting_engine()
    if engine is None:
        return "not_hosted"
    if workspace is not None and tenant is None:
        log.warning("engine_byok_changed_unattributable", extra={"workspace": workspace})
        return "unattributable"
    redis = get_redis()
    lease = _BYOK_LEASE_KEY.format(workspace=workspace or "developer")
    token = secrets.token_hex(16)
    if not await redis.set(lease, token, nx=True, ex=BYOK_LEASE_S):
        if attempt < WORKER_MAX_TRIES:
            raise Retry(defer=jittered_delay_s(_LEASE_RETRY_S, floor_s=_LEASE_RETRY_S))
        # The check holding the lease reads the state after this change too, and the hourly
        # sweep reads it again: nothing is lost by not running a second one now.
        return "coalesced"
    try:
        if tenant is None:
            return await _check_developer(engine)
        return await _check_client(engine, tenant)
    finally:
        await release_lease(redis, lease, token)


async def _check_developer(engine: Any) -> str:
    """Our developer workspace holds our Cartesia key (D-727) and our Google key (D-834)."""
    studio = f"developer={await check_developer_studio(engine)}"
    if not isinstance(engine, RunsOwnModel):
        return studio
    return f"{studio} own_model={await check_developer_own_model(engine)}"


async def _check_client(engine: Any, tenant: UUID) -> str:
    async with tenant_session(tenant) as session:
        state = await read_workspace_state(session, tenant)
        studio = await studio_enabled(session, tenant)
        own_model = await own_model_enabled(session, tenant)
    if not state.active or state.workspace_id is None or not is_own_workspace(state.workspace_id):
        return "not_active"
    checks: list[str] = []
    if studio:
        checks.append(f"studio={await check_studio_workspace(engine, tenant, state.workspace_id)}")
    if own_model and isinstance(engine, RunsOwnModel):
        checks.append(
            f"own_model={await check_own_model_workspace(engine, tenant, state.workspace_id)}"
        )
    # A workspace where we hold no key of ours: every agent there states `byok` itself and
    # Clear agents state `off`, so a key someone else added changes no call of ours.
    return " ".join(checks) or "no_keys_of_ours"


async def _settle_inbox(inbox_row_id: Any, *, error: str | None) -> None:
    if not inbox_row_id:
        return
    async with untenanted_session() as session:
        if error is None:
            await mark_inbox_processed(session, row_id=UUID(str(inbox_row_id)))
        else:
            await mark_inbox_failed(session, row_id=UUID(str(inbox_row_id)), error=error)


async def _abandon(payload: dict[str, Any], exc: Exception, attempt: int) -> NoReturn:
    """Mark the inbox row failed (re-claimable), then retry or stop. A stop is logged, not
    alarmed: what each event drives is also done by a sweep (the hourly key checks) or by a
    person (the overdue erasure task already pages)."""
    await _settle_inbox(payload.get("inbox_row_id"), error=type(exc).__name__)
    permanent = isinstance(exc, ProblemError) and exc.kind == "validation"
    if not permanent and attempt < WORKER_MAX_TRIES:
        raise Retry(defer=ladder_delay_s(_RETRY_AFTER_S, attempt)) from exc
    log.warning(
        "engine_workspace_event_abandoned",
        extra={"reason": type(exc).__name__, "attempt": attempt},
    )
    raise exc


async def ingest_engine_workspace_event(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Attribute one `contact.erased` or `byok.changed` to its client and act on it."""
    attempt = int(ctx.get("job_try", 1))
    try:
        event = _event_of(payload)
        whose = await _whose(payload, event)
        if whose is None:
            log.warning("engine_workspace_event_mismatch", extra={"engine": payload.get("engine")})
            outcome = "workspace_mismatch"
        elif isinstance(event, EngineContactErased):
            outcome = await _contact_erased(event, *whose)
        else:
            outcome = await _byok_changed(event, *whose, attempt=attempt)
    except Retry:
        raise
    except Exception as exc:
        await _abandon(payload, exc, attempt)
    # Closed last: `processed` is what makes the event permanently deduped.
    await _settle_inbox(payload.get("inbox_row_id"), error=None)
    return outcome


__all__ = [
    "BYOK_LEASE_S",
    "ENGINE_WORKSPACE_EVENT_JOB",
    "ReadsWorkspaceEvents",
    "ingest_engine_workspace_event",
]
