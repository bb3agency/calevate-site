"""Our Google key in every workspace that answers on our model, kept on (D-764, D-834).

Agents on our own model answer on our Google key, installed in each paying client's own
ThinnestAI workspace by `agents/own_model.ensure_own_model_in`, and in our developer workspace,
where free-trial agents live, by `ensure_developer_own_model`. There is no backup model on
our own keys: "if your key fails, the caller hears our apology and the call is flagged, and
we do not answer on our model" (`thinnest-findings/mirror/snapshots/2026-10-13/pages/
api-reference/bring-your-own-keys.md:171-178`). So, as `studio_voice_key.py` does for our
Cartesia key:

* `push_own_model_key` — a rotation, enqueued through the outbox by
  `ops/secret_routes.set_secret_route` in the transaction that stores the new version. It
  replaces the key in the developer workspace (when a Google key is held there) and fans
  out one `push_own_model_key_to_workspace` per own-model workspace, each with its own retries
  and alarm. Replacing a key of the same provider keeps its model (:239), and the key is read
  from the store, never logged.
* `sweep_own_model_workspaces` — hourly. The developer workspace (`check_developer_own_model`,
  once it was set up) and every own-model client workspace must answer `GET /byok`
  with our checked Google key in use (`own_model_key_ready`); one that does not is REPAIRED by
  the steps a publish runs and alarmed either way, because an agent whose `byok` scope names
  a key the workspace no longer serves falls back to the workspace's scope at its next call
  (:99-103) and runs, and bills, on a stack we did not choose. It then refreshes the prompt
  size the own-model cost floor is struck at (`billing/own_model_prompt`).
"""

from __future__ import annotations

from typing import Any, Final, cast
from uuid import UUID

from arq import Retry
from calevate_shared.backoff import ladder_delay_s

from apps.api.agents.own_model import (
    OWN_MODEL_PROVIDER,
    align_key_model,
    ensure_developer_own_model,
    ensure_own_model_workspace,
    forget_own_model_failure,
    own_model_key_ready,
)
from apps.api.billing.own_model_prompt import refresh_prompt_basis
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine
from apps.api.engine.catalogue import HostsVoices, RunsOwnModel
from apps.api.engine.thinnest_workspace import in_workspace
from apps.api.ops.own_model_cache import refresh_fleet_cache_share
from apps.api.ops.secret_service import resolve_secrets
from apps.api.reliability.service import enqueue_outbox
from apps.api.tenancy.engine_workspace import (
    own_model_workspaces,
    read_developer_own_model,
    record_developer_own_model_check,
    record_own_model_check,
    workspace_for_tenant,
)

log = get_logger(__name__)

#: The secret whose rotation this follows.
GOOGLE_KEY: Final = "gemini_api_key"
#: The per-workspace child of a rotation.
PUSH_TO_WORKSPACE_JOB: Final = "push_own_model_key_to_workspace"
_RETRY_AFTER_S: Final = (30, 120, 600)


async def _current_key() -> str | None:
    """The newest stored version, or the environment's value when it shadows the store."""
    async with untenanted_session() as session:
        resolved = await resolve_secrets(session)
    return resolved.values.get(GOOGLE_KEY) or get_settings().gemini_api_key


def _runs_own_model() -> RunsOwnModel | None:
    engine = get_engine()
    if not isinstance(engine, RunsOwnModel) or not isinstance(engine, HostsVoices):
        return None
    return engine


def _push_failed(code: str, *, where: str, tenant_id: str | None = None) -> None:
    log.warning("own_model_key_push_failed", extra={"reason": code, "tenant_id": tenant_id})
    alert(
        "CORE_LOGIC",
        "own_model_key_push_failed",
        detail=(
            f"The rotated Google key could not be installed in {where} ({code}), so calls "
            "there still answer on the previous key and the caller hears an apology once it "
            "is revoked. Test the key from the ops console Secrets panel, then save it again, "
            "which retries every push."
        ),
        reason=code,
        tenant_id=tenant_id or "",
    )


async def _push_to_developer(engine: RunsOwnModel, key: str) -> str:
    """Replace the developer workspace's Google key, keeping its model, when one is held
    there: `pushed`, `failed` or `not_held`. A workspace never set up is not set up here;
    the operator's act and the hourly repair do that."""
    try:
        state = await engine.own_key_state()
        if state.llm_provider != OWN_MODEL_PROVIDER:
            return "not_held"
        await engine.install_own_model_key(
            provider=OWN_MODEL_PROVIDER,
            api_key=key,
            model=state.llm_model or get_settings().thinnest_own_model_default,
        )
    except ProblemError as exc:
        _push_failed(exc.code, where="our developer workspace")
        return "failed"
    return "pushed"


async def push_own_model_key(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Replace the developer workspace's key and fan out one push per own-model client
    workspace. Returns what it did."""
    del ctx, payload  # the store holds the key; the payload only names the version
    engine = _runs_own_model()
    if engine is None:
        return "not_hosted"
    key = await _current_key()
    if not key:
        return "no_key"
    developer = await _push_to_developer(engine, key)
    workspaces = await own_model_workspaces()
    async with untenanted_session() as session:
        for row in workspaces:
            await enqueue_outbox(
                session, job=PUSH_TO_WORKSPACE_JOB, payload={"tenant_id": str(row.tenant_id)}
            )
    log.info(
        "own_model_key_fanned_out",
        extra={"developer": developer, "workspaces": len(workspaces)},
    )
    return f"developer={developer} workspaces={len(workspaces)}"


async def push_own_model_key_to_workspace(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Replace our Google key in ONE client's workspace, keeping its model. Retried with
    backoff on a transient failure; alarmed when it gives up or the provider refuses it."""
    engine = _runs_own_model()
    if engine is None:
        return "not_hosted"
    tenant_id = UUID(str(payload["tenant_id"]))
    workspace = await workspace_for_tenant(tenant_id)
    if workspace is None:
        return "no_workspace"
    key = await _current_key()
    if not key:
        return "no_key"
    attempt = int(ctx.get("job_try", 1))
    try:
        with in_workspace(workspace):
            state = await engine.own_key_state()
            await engine.install_own_model_key(
                provider=OWN_MODEL_PROVIDER,
                api_key=key,
                model=state.llm_model or get_settings().thinnest_own_model_default,
            )
    except ProblemError as exc:
        permanent = exc.kind in ("validation", "business_rule")
        if not permanent and attempt < WORKER_MAX_TRIES:
            raise Retry(defer=ladder_delay_s(_RETRY_AFTER_S, attempt)) from exc
        _push_failed(exc.code, where="a client's voice workspace", tenant_id=str(tenant_id))
        return "failed"
    log.info("own_model_key_pushed", extra={"tenant_id": str(tenant_id)})
    return "pushed"


async def sweep_own_model_workspaces(ctx: dict[str, Any]) -> str:
    """Hourly: our developer workspace and every own-model client workspace verified on our
    Google key, repaired when not."""
    del ctx
    engine = _runs_own_model()
    if engine is None:
        return "not_hosted"
    developer = await check_developer_own_model(engine)
    tally = dict.fromkeys(("ok", "repaired", "failed"), 0)
    for row in await own_model_workspaces():
        try:
            outcome = await _check_workspace(engine, row.tenant_id, row.workspace_id)
        except Exception as exc:
            # `_check_workspace` answers the platform's refusals; anything else (a database
            # error, a timeout) is this workspace's alone and must not skip the ones after it.
            log.error(
                "own_model_workspace_check_crashed",
                extra={"tenant_id": str(row.tenant_id), "error": type(exc).__name__},
            )
            outcome = "failed"
        tally[outcome] += 1
    alarm_own_model_tally(tally)
    basis = await refresh_prompt_basis(get_engine())
    fleet = await refresh_fleet_cache_share()
    summary = " ".join(f"{k}={v}" for k, v in tally.items())
    cache = f"cache_calls={fleet.totals.calls}"
    return f"developer={developer} {summary} {cache} prompt={basis.source}"


async def check_developer_own_model(engine: RunsOwnModel) -> str:
    """The developer workspace's half of the hourly check: `ok`, `repaired`, `failed`, or
    `not_set_up` while it was never confirmed on our key. Free-trial agents on our model
    answer there (D-834), so a workspace once set up and found off is repaired by
    `ensure_developer_own_model` and alarmed either way; an unreadable one changes nothing."""
    try:
        state = await engine.own_key_state()
    except ProblemError as exc:
        log.warning("engine_byok_state_unreadable", extra={"code": exc.code})
        return "failed"
    if own_model_key_ready(state):
        try:
            # A changed console default reaches the key here as well as at the next trial
            # publish, so the agents already live answer on it from their next call.
            await align_key_model(engine, state)
        except ProblemError as exc:
            log.warning("own_model_developer_key_model_not_aligned", extra={"code": exc.code})
            return "failed"
    async with untenanted_session() as session:
        if own_model_key_ready(state):
            await record_developer_own_model_check(session, error_code=None)
            return "ok"
        if (await read_developer_own_model(session)).enabled_at is None:
            return "not_set_up"
    log.warning(
        "own_model_developer_drift",
        extra={
            "enabled": state.enabled,
            "scope": state.scope,
            "using": state.using,
            "llm_provider": state.llm_provider,
        },
    )
    try:
        async with untenanted_session() as session:
            await ensure_developer_own_model(session, cast(HostsVoices, engine))
    except ProblemError as exc:
        log.warning("own_model_developer_repair_failed", extra={"reason": exc.code})
        alert(
            "CORE_LOGIC",
            "own_model_developer_drift",
            detail=(
                "Our developer workspace is not on our Google key and could not be switched "
                f"back on ({exc.code}), so free-trial agents on our model are refused at "
                "publish and fall back to the workspace's own scope at their next call. Run "
                "Set up developer workspace from Voices, Our own model; "
                "runbooks/thinnest-own-model.md says what each code means."
            ),
            reason=exc.code,
        )
        return "failed"
    alert(
        "CORE_LOGIC",
        "own_model_developer_repaired",
        detail=(
            "Our developer workspace was no longer on our Google key and was switched back "
            "on, every agent that would follow its keys confirmed off first. Find out who "
            "changed it on the voice platform."
        ),
    )
    return "repaired"


async def check_own_model_workspace(engine: RunsOwnModel, tenant_id: UUID, workspace: str) -> str:
    """One own-model client workspace verified on our Google key, repaired when not, and
    alarmed as the hourly sweep alarms: `ok`, `repaired` or `failed`. Read first and written
    only on drift, so asking again after our own write finds it `ok` and writes nothing."""
    outcome = await _check_workspace(engine, tenant_id, workspace)
    alarm_own_model_tally({outcome: 1})
    return outcome


async def _check_workspace(engine: RunsOwnModel, tenant_id: UUID, workspace: str) -> str:
    try:
        with in_workspace(workspace):
            state = await engine.own_key_state()
        if own_model_key_ready(state):
            async with tenant_session(tenant_id) as session:
                await record_own_model_check(session, tenant_id, error_code=None)
            await forget_own_model_failure(tenant_id)
            return "ok"
        log.warning(
            "own_model_workspace_drift",
            extra={
                "tenant_id": str(tenant_id),
                "enabled": state.enabled,
                "scope": state.scope,
                "using": state.using,
                "llm_provider": state.llm_provider,
            },
        )
        await ensure_own_model_workspace(
            cast(HostsVoices, engine), tenant_id=tenant_id, workspace=workspace, audience="operator"
        )
        return "repaired"
    except ProblemError as exc:
        log.warning(
            "own_model_workspace_repair_failed",
            extra={"tenant_id": str(tenant_id), "reason": exc.code},
        )
        return "failed"


def alarm_own_model_tally(tally: dict[str, int]) -> None:
    """The two alarms, for whatever a sweep or one check counted."""
    if tally.get("repaired"):
        alert(
            "CORE_LOGIC",
            "own_model_workspace_repaired",
            detail=(
                f"{tally['repaired']} client voice workspace(s) were no longer on our Google "
                "key and were switched back on, Clear agents that follow the workspace kept "
                "off first. Find out who changed them on the voice platform."
            ),
            count=str(tally["repaired"]),
        )
    if tally.get("failed"):
        alert(
            "CORE_LOGIC",
            "own_model_workspace_drift",
            detail=(
                f"{tally['failed']} client voice workspace(s) are not on our Google key and "
                "could not be switched back on, so their agents on our model fall back to the "
                "workspace's own scope at their next call. Ops Voices, Our own model shows "
                "each client's last error code."
            ),
            count=str(tally["failed"]),
        )


__all__ = [
    "GOOGLE_KEY",
    "PUSH_TO_WORKSPACE_JOB",
    "alarm_own_model_tally",
    "check_developer_own_model",
    "check_own_model_workspace",
    "push_own_model_key",
    "push_own_model_key_to_workspace",
    "sweep_own_model_workspaces",
]
