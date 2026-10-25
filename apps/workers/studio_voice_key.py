"""Our Cartesia key in every workspace that holds it, and every Studio workspace kept on.

Studio voices speak on our Cartesia key, switched on (voice-only BYOK) in our developer
workspace, where trial agents live (D-727), and in the ThinnestAI customer workspace of each
paying client that uses Studio (D-717) (`agents/studio_voices.py`). There is no fallback when
the key fails:
"the voice does not speak" (`thinnest-findings/mirror/snapshots/2026-10-08/pages/
api-reference/bring-your-own-keys.md:122-127`). So:

* `push_studio_voice_key` — a rotation. Enqueued through the outbox by
  `ops/secret_routes.set_secret_route` in the transaction that stores the new version. It
  replaces the key in the developer workspace (when one is held there) and FANS OUT one
  `push_studio_voice_key_to_workspace` per Studio client workspace, each through the outbox
  with its own retries and its own alarm, so one client's failure neither blocks nor hides
  another's. Replacing a key for the same provider keeps its model (`bring-your-own-keys.
  md:188`), so nothing but the key is sent. The key is read from the store, not this
  process's settings, which may not have re-read it yet, and is never logged.
* `sweep_studio_workspaces` — hourly. Our developer workspace and every Studio client
  workspace must answer `GET /byok` with
  `enabled`, `scope: voice`, `complete`, `using: own` and a Cartesia voice key
  (`bring-your-own-keys/get-byok-status.md:7`). One that does not is REPAIRED by the same
  idempotent steps a publish runs (its Clear agents kept off and read back first, then the
  key and the switch) and alarmed either way. Repair rather than only alarm because the
  failure is silent and priced wrong: a Studio agent in a workspace that is off follows the
  workspace onto ThinnestAI's own voices and their rate while we meter `byok_voice`, and the
  repair cannot move a Clear agent, which it confirms `off` before switching anything on. The
  developer workspace is repaired the same way (`ensure_developer_studio`), but only once
  Studio ready has held our key there: a deployment that never set Studio up is not drift.
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

from arq import Retry
from calevate_shared.backoff import ladder_delay_s

from apps.api.agents.hosted_voices import STUDIO_VOICE_PROVIDER, own_voice_key_ready
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine
from apps.api.engine.catalogue import HostsVoices
from apps.api.engine.thinnest_workspace import in_workspace
from apps.api.ops.secret_service import resolve_secrets
from apps.api.reliability.service import enqueue_outbox
from apps.api.tenancy.engine_workspace import (
    record_developer_studio_check,
    record_studio_check,
    studio_workspaces,
    workspace_for_tenant,
)

log = get_logger(__name__)

#: The secret whose rotation this follows.
CARTESIA_KEY: Final = "cartesia_api_key"
#: The per-workspace child of a rotation.
PUSH_TO_WORKSPACE_JOB: Final = "push_studio_voice_key_to_workspace"
_RETRY_AFTER_S: Final = (30, 120, 600)


async def _current_key() -> str | None:
    """The newest stored version, or the environment's value when the environment declares
    it (the store skips a key the environment shadows)."""
    async with untenanted_session() as session:
        resolved = await resolve_secrets(session)
    return resolved.values.get(CARTESIA_KEY) or get_settings().cartesia_api_key


def hosting_engine() -> HostsVoices | None:
    engine = get_engine()
    if not isinstance(engine, HostsVoices) or engine.capabilities.is_ours("tts"):
        return None
    return engine


def _push_failed(code: str, *, where: str, tenant_id: str | None = None) -> None:
    log.warning("studio_voice_key_push_failed", extra={"reason": code, "tenant_id": tenant_id})
    alert(
        "CORE_LOGIC",
        "studio_voice_key_push_failed",
        detail=(
            f"The rotated Cartesia key could not be installed in {where} ({code}), so Studio "
            "calls there still speak on the previous key and stop speaking when it is "
            "revoked. Test the key from the ops console Secrets panel, then save it again, "
            "which retries every push."
        ),
        reason=code,
        tenant_id=tenant_id or "",
    )


async def push_studio_voice_key(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Replace the developer workspace's held key and fan out one push per Studio client
    workspace. Returns what it did."""
    del ctx, payload  # the store holds the key; the payload only names the version
    engine = hosting_engine()
    if engine is None:
        return "not_hosted"
    key = await _current_key()
    if not key:
        return "no_key"
    developer = "not_held"
    if (await engine.own_key_state()).voice_provider == STUDIO_VOICE_PROVIDER:
        try:
            await engine.install_own_voice_key(
                provider=STUDIO_VOICE_PROVIDER, api_key=key, model=None
            )
            developer = "pushed"
        except ProblemError as exc:
            _push_failed(exc.code, where="our developer workspace")
            developer = "failed"
    workspaces = await studio_workspaces()
    async with untenanted_session() as session:
        for row in workspaces:
            await enqueue_outbox(
                session, job=PUSH_TO_WORKSPACE_JOB, payload={"tenant_id": str(row.tenant_id)}
            )
    log.info(
        "studio_voice_key_fanned_out",
        extra={"developer": developer, "workspaces": len(workspaces)},
    )
    return f"developer={developer} workspaces={len(workspaces)}"


async def push_studio_voice_key_to_workspace(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Replace our key in ONE Studio client's workspace. Retried with backoff on a transient
    failure; alarmed when it gives up or the provider refuses the key."""
    engine = hosting_engine()
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
            await engine.install_own_voice_key(
                provider=STUDIO_VOICE_PROVIDER, api_key=key, model=None
            )
    except ProblemError as exc:
        permanent = exc.kind in ("validation", "business_rule")
        if not permanent and attempt < WORKER_MAX_TRIES:
            raise Retry(defer=ladder_delay_s(_RETRY_AFTER_S, attempt)) from exc
        _push_failed(exc.code, where="a client's voice workspace", tenant_id=str(tenant_id))
        return "failed"
    log.info("studio_voice_key_pushed", extra={"tenant_id": str(tenant_id)})
    return "pushed"


async def sweep_studio_workspaces(ctx: dict[str, Any]) -> str:
    """Hourly: our developer workspace and every Studio client workspace verified on our key,
    and repaired when not."""
    del ctx
    engine = hosting_engine()
    if engine is None:
        return "not_hosted"
    tally = dict.fromkeys(("ok", "repaired", "failed"), 0)
    developer = await check_developer_studio(engine)
    for row in await studio_workspaces():
        try:
            outcome = await _check_workspace(engine, row.tenant_id, row.workspace_id)
        except Exception as exc:
            # `_check_workspace` answers the platform's refusals; anything else (a database
            # error, a timeout) is this workspace's alone and must not skip the ones after it.
            log.error(
                "studio_workspace_check_crashed",
                extra={"tenant_id": str(row.tenant_id), "error": type(exc).__name__},
            )
            outcome = "failed"
        tally[outcome] += 1
    alarm_studio_tally(tally)
    summary = " ".join(f"{k}={v}" for k, v in tally.items())
    return f"developer={developer} {summary}"


async def check_studio_workspace(engine: HostsVoices, tenant_id: UUID, workspace: str) -> str:
    """One Studio client workspace verified on our key, repaired when not, and alarmed as the
    hourly sweep alarms: `ok`, `repaired` or `failed`. Read first and written only on drift,
    so asking again after our own write finds it `ok` and writes nothing."""
    outcome = await _check_workspace(engine, tenant_id, workspace)
    alarm_studio_tally({outcome: 1})
    return outcome


async def _check_workspace(engine: HostsVoices, tenant_id: UUID, workspace: str) -> str:
    from apps.api.agents.studio_voices import ensure_studio_workspace

    try:
        with in_workspace(workspace):
            state = await engine.own_key_state()
        if own_voice_key_ready(state):
            async with tenant_session(tenant_id) as session:
                await record_studio_check(session, tenant_id, error_code=None)
            return "ok"
        log.warning(
            "studio_workspace_drift",
            extra={
                "tenant_id": str(tenant_id),
                "enabled": state.enabled,
                "scope": state.scope,
                "using": state.using,
                "voice_provider": state.voice_provider,
            },
        )
        await ensure_studio_workspace(
            engine, tenant_id=tenant_id, workspace=workspace, audience="operator"
        )
        return "repaired"
    except ProblemError as exc:
        log.warning(
            "studio_workspace_repair_failed",
            extra={"tenant_id": str(tenant_id), "reason": exc.code},
        )
        return "failed"


def alarm_studio_tally(tally: dict[str, int]) -> None:
    """The two client-workspace alarms, for whatever a sweep or one check counted."""
    if tally.get("repaired"):
        alert(
            "CORE_LOGIC",
            "studio_workspace_repaired",
            detail=(
                f"{tally['repaired']} client voice workspace(s) were no longer on our "
                "Cartesia key for Studio and were switched back on, Clear agents kept off "
                "first. Find out who changed them on the voice platform."
            ),
            count=str(tally["repaired"]),
        )
    if tally.get("failed"):
        alert(
            "CORE_LOGIC",
            "studio_workspace_drift",
            detail=(
                f"{tally['failed']} client voice workspace(s) are not on our Cartesia key "
                "for Studio and could not be switched back on, so their Studio agents speak "
                "the platform's default voice or not at all. The admin page shows each "
                "client's last error code."
            ),
            count=str(tally["failed"]),
        )


async def check_developer_studio(engine: HostsVoices) -> str:
    """The developer workspace's half of the hourly check: `ok`, `repaired`, `failed`,
    or `not_set_up` while Studio ready has never held our key there. Each definite answer is
    recorded, since a free-trial account is offered Studio by it (`studio_open_to`, D-806);
    an unreadable workspace changes nothing."""
    from apps.api.agents.studio_voices import ensure_developer_studio

    try:
        state = await engine.own_key_state()
    except ProblemError as exc:
        log.warning("engine_byok_state_unreadable", extra={"code": exc.code})
        return "failed"
    if own_voice_key_ready(state):
        await _record_developer(ready=True)
        return "ok"
    if state.voice_provider != STUDIO_VOICE_PROVIDER:
        await _record_developer(ready=False)
        return "not_set_up"
    log.warning(
        "studio_developer_drift",
        extra={"enabled": state.enabled, "scope": state.scope, "using": state.using},
    )
    try:
        async with untenanted_session() as session:
            await ensure_developer_studio(session, engine)
    except ProblemError as exc:
        log.warning("studio_developer_repair_failed", extra={"reason": exc.code})
        await _record_developer(ready=False)
        alert(
            "CORE_LOGIC",
            "studio_developer_drift",
            detail=(
                "Our developer workspace is not on our Cartesia key for Studio and could not "
                f"be switched back on ({exc.code}), so free-trial agents on a Studio voice "
                "speak the platform's default voice or not at all. Run Studio ready from "
                "Voices; runbooks/thinnest-studio-voices.md says what each code means."
            ),
            reason=exc.code,
        )
        return "failed"
    alert(
        "CORE_LOGIC",
        "studio_developer_repaired",
        detail=(
            "Our developer workspace was no longer on our Cartesia key for Studio and was "
            "switched back on, every agent not on a Studio voice confirmed off first. Find "
            "out who changed it on the voice platform."
        ),
    )
    return "repaired"


async def _record_developer(*, ready: bool) -> None:
    async with untenanted_session() as session:
        await record_developer_studio_check(session, ready=ready)


__all__ = [
    "CARTESIA_KEY",
    "PUSH_TO_WORKSPACE_JOB",
    "alarm_studio_tally",
    "check_developer_studio",
    "check_studio_workspace",
    "hosting_engine",
    "push_studio_voice_key",
    "push_studio_voice_key_to_workspace",
    "sweep_studio_workspaces",
]
