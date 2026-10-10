"""Our Cartesia key in every workspace that holds it, and every Studio workspace kept on (D-717).

Studio voices speak on our Cartesia key, switched on (voice-only BYOK) in the ThinnestAI
customer workspace of each client that uses Studio, and HELD with its switch off in our
developer workspace (`agents/studio_voices.py`). There is no fallback when the key fails:
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
* `sweep_studio_workspaces` — hourly. Every Studio workspace must answer `GET /byok` with
  `enabled`, `scope: voice`, `complete`, `using: own` and a Cartesia voice key
  (`bring-your-own-keys/get-byok-status.md:7`). One that does not is REPAIRED by the same
  idempotent steps a publish runs (its Clear agents kept off and read back first, then the
  key and the switch) and alarmed either way. Repair rather than only alarm because the
  failure is silent and priced wrong: a Studio agent in a workspace that is off follows the
  workspace onto ThinnestAI's own voices and their rate while we meter `byok_voice`, and the
  repair cannot move a Clear agent, which it confirms `off` before switching anything on. Our
  developer workspace found switched ON is alarmed and NOT switched off here: under the old
  design it carried every Studio client, and turning it off is the runbook's last step
  (`runbooks/thinnest-studio-voices.md`).
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

from arq import Retry

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


def _hosting() -> HostsVoices | None:
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
    engine = _hosting()
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
    engine = _hosting()
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
            raise Retry(defer=_RETRY_AFTER_S[min(attempt, len(_RETRY_AFTER_S)) - 1]) from exc
        _push_failed(exc.code, where="a client's voice workspace", tenant_id=str(tenant_id))
        return "failed"
    log.info("studio_voice_key_pushed", extra={"tenant_id": str(tenant_id)})
    return "pushed"


async def sweep_studio_workspaces(ctx: dict[str, Any]) -> str:
    """Hourly: every Studio client workspace verified on our key, and repaired when not; our
    developer workspace's switch alarmed if found on."""
    del ctx
    engine = _hosting()
    if engine is None:
        return "not_hosted"
    from apps.api.agents.studio_voices import ensure_studio_workspace

    tally = dict.fromkeys(("ok", "repaired", "failed"), 0)
    try:
        developer_on = (await engine.own_key_state()).enabled
    except ProblemError as exc:
        log.warning("engine_byok_state_unreadable", extra={"code": exc.code})
        developer_on = False
    if developer_on:
        alert(
            "CORE_LOGIC",
            "studio_developer_switch_on",
            detail=(
                "Our developer workspace's own-keys switch is ON, so every client workspace "
                "without a key of its own runs on it and any agent not set to stay off speaks "
                "Cartesia at the Studio rate. Follow runbooks/thinnest-studio-voices.md to "
                "move each Studio client onto its own key, then switch it off from Voices."
            ),
        )
    for row in await studio_workspaces():
        try:
            with in_workspace(row.workspace_id):
                state = await engine.own_key_state()
            if own_voice_key_ready(state):
                async with tenant_session(row.tenant_id) as session:
                    await record_studio_check(session, row.tenant_id, error_code=None)
                tally["ok"] += 1
                continue
            log.warning(
                "studio_workspace_drift",
                extra={
                    "tenant_id": str(row.tenant_id),
                    "enabled": state.enabled,
                    "scope": state.scope,
                    "using": state.using,
                    "voice_provider": state.voice_provider,
                },
            )
            await ensure_studio_workspace(
                engine, tenant_id=row.tenant_id, workspace=row.workspace_id, audience="operator"
            )
            tally["repaired"] += 1
        except ProblemError as exc:
            tally["failed"] += 1
            log.warning(
                "studio_workspace_repair_failed",
                extra={"tenant_id": str(row.tenant_id), "reason": exc.code},
            )
    if tally["repaired"]:
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
    if tally["failed"]:
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
    summary = " ".join(f"{k}={v}" for k, v in tally.items())
    return f"developer_on={developer_on} {summary}"


__all__ = [
    "CARTESIA_KEY",
    "PUSH_TO_WORKSPACE_JOB",
    "push_studio_voice_key",
    "push_studio_voice_key_to_workspace",
    "sweep_studio_workspaces",
]
