"""Our Google key in every client workspace that answers on our model, kept on (D-764).

Agents on our own model answer on our Google key, installed in each paying client's own
ThinnestAI workspace by `agents/own_model.ensure_own_model_in`. There is no backup model on
our own keys: "if your key fails, the caller hears our apology and the call is flagged, and
we do not answer on our model" (`thinnest-findings/mirror/snapshots/2026-10-13/pages/
api-reference/bring-your-own-keys.md:171-178`). So, as `studio_voice_key.py` does for our
Cartesia key:

* `push_own_model_key` — a rotation, enqueued through the outbox by
  `ops/secret_routes.set_secret_route` in the transaction that stores the new version. It fans
  out one `push_own_model_key_to_workspace` per own-model workspace, each with its own retries
  and alarm. Replacing a key of the same provider keeps its model (:239), and the key is read
  from the store, never logged.
* `sweep_own_model_workspaces` — hourly. Every own-model workspace must answer `GET /byok`
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

from apps.api.agents.own_model import (
    OWN_MODEL_PROVIDER,
    ensure_own_model_workspace,
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
from apps.api.ops.secret_service import resolve_secrets
from apps.api.reliability.service import enqueue_outbox
from apps.api.tenancy.engine_workspace import (
    own_model_workspaces,
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


def _push_failed(code: str, *, tenant_id: str) -> None:
    log.warning("own_model_key_push_failed", extra={"reason": code, "tenant_id": tenant_id})
    alert(
        "CORE_LOGIC",
        "own_model_key_push_failed",
        detail=(
            f"The rotated Google key could not be installed in a client's voice workspace "
            f"({code}), so calls there still answer on the previous key and the caller hears "
            "an apology once it is revoked. Test the key from the ops console Secrets panel, "
            "then save it again, which retries every push."
        ),
        reason=code,
        tenant_id=tenant_id,
    )


async def push_own_model_key(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Fan out one push per own-model client workspace. Returns what it did."""
    del ctx, payload  # the store holds the key; the payload only names the version
    if _runs_own_model() is None:
        return "not_hosted"
    if not await _current_key():
        return "no_key"
    workspaces = await own_model_workspaces()
    async with untenanted_session() as session:
        for row in workspaces:
            await enqueue_outbox(
                session, job=PUSH_TO_WORKSPACE_JOB, payload={"tenant_id": str(row.tenant_id)}
            )
    log.info("own_model_key_fanned_out", extra={"workspaces": len(workspaces)})
    return f"workspaces={len(workspaces)}"


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
            raise Retry(defer=_RETRY_AFTER_S[min(attempt, len(_RETRY_AFTER_S)) - 1]) from exc
        _push_failed(exc.code, tenant_id=str(tenant_id))
        return "failed"
    log.info("own_model_key_pushed", extra={"tenant_id": str(tenant_id)})
    return "pushed"


async def sweep_own_model_workspaces(ctx: dict[str, Any]) -> str:
    """Hourly: every own-model client workspace verified on our Google key, repaired when
    not."""
    del ctx
    engine = _runs_own_model()
    if engine is None:
        return "not_hosted"
    tally = dict.fromkeys(("ok", "repaired", "failed"), 0)
    for row in await own_model_workspaces():
        try:
            with in_workspace(row.workspace_id):
                state = await engine.own_key_state()
            if own_model_key_ready(state):
                async with tenant_session(row.tenant_id) as session:
                    await record_own_model_check(session, row.tenant_id, error_code=None)
                tally["ok"] += 1
                continue
            log.warning(
                "own_model_workspace_drift",
                extra={
                    "tenant_id": str(row.tenant_id),
                    "enabled": state.enabled,
                    "scope": state.scope,
                    "using": state.using,
                    "llm_provider": state.llm_provider,
                },
            )
            await ensure_own_model_workspace(
                cast(HostsVoices, engine),
                tenant_id=row.tenant_id,
                workspace=row.workspace_id,
                audience="operator",
            )
            tally["repaired"] += 1
        except ProblemError as exc:
            tally["failed"] += 1
            log.warning(
                "own_model_workspace_repair_failed",
                extra={"tenant_id": str(row.tenant_id), "reason": exc.code},
            )
    if tally["repaired"]:
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
    if tally["failed"]:
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
    basis = await refresh_prompt_basis(get_engine())
    return " ".join(f"{k}={v}" for k, v in tally.items()) + f" prompt={basis.source}"


__all__ = [
    "GOOGLE_KEY",
    "PUSH_TO_WORKSPACE_JOB",
    "push_own_model_key",
    "push_own_model_key_to_workspace",
    "sweep_own_model_workspaces",
]
