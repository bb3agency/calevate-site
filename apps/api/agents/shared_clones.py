"""Our cloned voices, spoken by client agents in their own ThinnestAI workspaces (D-797).

An operator clones in our developer workspace, and every such clone can be used by every
customer workspace's agents, automatically: inside a customer it is listed by `GET /voices`
with `sharedFromDeveloper: true`, only we can rename or delete it, and it counts against our
clone limit only (snapshots/2026-10-15/pages/channels/voice-clone.md:114-126;
api-reference/customers.md:236-241; api-reference/voices/list-voices.md:579-589). So a client
agent speaks the shared clone itself; nothing is cloned again in the client's workspace.

The shared clone keeps its id: a customer's `GET /voices` lists it under the developer's
clone id (ThinnestAI's email of 18 Oct 2026; the docs name only the `sharedFromDeveloper`
mark, snapshots/2026-10-18/pages/api-reference/voices/list-voices.md:579-589). The client
workspace's own listing is still read before the id is sent, because a clone is listed there
only on Pro and above and not after we delete it; when ours is not listed the publish is
refused by name (`shared_clone_not_listed`), never sent to a copy or to our developer
workspace (D-693).

Before D-797 each client workspace got its own copy of the clone (`engine_voice_clone_copies`).
Nothing writes that table any more; `forget_clone` still deletes the copies it records when
the clone itself is deleted, and an agent still on a copy is moved to the shared clone by its
next publish or by the drift sweep's voice repair.
"""

from __future__ import annotations

from typing import Final

from calevate_shared.engine import AgentConfig
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.engine.catalogue import HostsVoices
from apps.api.engine.thinnest_workspace import in_workspace

log = get_logger(__name__)

SHARED_CLONE_NOT_LISTED: Final = "shared_clone_not_listed"

_CLONE_ROW: Final = (
    "SELECT engine_voice_id, engine_clone_id FROM platform_voice_catalog WHERE voice_id = :vid"
)


def shared_clone_not_listed() -> ProblemError:
    # Clients read this (it is a publish refusal), so it names no provider (D-679); the
    # operator's half is the `engine_shared_clone_not_listed` log line.
    return ProblemError.business_rule(
        SHARED_CLONE_NOT_LISTED,
        "This cloned voice is not available to this account's agents yet, so the agent was "
        "not published.",
        remediation="Choose another voice, or contact us.",
    )


async def client_voice_id(
    session: AsyncSession,
    engine: object,
    *,
    voice_id: str,
    workspace: str,
) -> str | None:
    """The vendor `voiceId` an agent in the customer `workspace` speaks for our catalogue
    voice `voice_id`, or None when the voice is not one of our clones (it is then the same
    id in every workspace). Refuses `shared_clone_not_listed` when the workspace does not
    list our clone as shared under the id we hold."""
    row = (await session.execute(text(_CLONE_ROW), {"vid": voice_id})).first()
    if row is None or not row[1] or not isinstance(engine, HostsVoices):
        return None
    developer_id = str(row[0])
    with in_workspace(workspace):
        listing = await engine.list_hosted_voices()
    shared = [voice for voice in listing.voices if voice.shared_from_developer]
    if any(voice.voice_id == developer_id for voice in shared):
        return developer_id
    # Studio voices, shared clones among them, are listed on Pro and above only
    # (list-voices.md:450-453), so an empty `shared` can also be the plan.
    log.error(
        "engine_shared_clone_not_listed",
        extra={
            "voice_id": voice_id,
            "workspace": workspace,
            "shared_listed": len(shared),
        },
    )
    raise shared_clone_not_listed()


async def voice_in_workspace(
    session: AsyncSession,
    engine: object,
    *,
    catalogue_voice: object,
    config: AgentConfig,
    workspace: str,
) -> AgentConfig:
    """`config` with its engine voice as the customer `workspace` names it. The one door for
    both the publish and the drift sweep's read-back, so the sweep compares the id the
    publish sent and never flags or "repairs" it back to another."""
    if not config.engine_voice_id or not isinstance(catalogue_voice, str):
        return config
    held = await client_voice_id(session, engine, voice_id=catalogue_voice, workspace=workspace)
    if held is None:
        return config
    return config.model_copy(update={"engine_voice_id": held})


async def forget_clone(engine: object, *, voice_id: str, sample_key: str | None) -> int:
    """Our clone was deleted: delete every pre-D-797 copy of it recorded in a client's
    workspace, and the recording kept to make them. Best effort per copy: one that would not
    go is logged and left recorded, so a second delete retries it. Returns how many agents
    the vendor moved off the deleted copies to a standard voice."""
    from apps.api.db.session import tenant_session
    from apps.api.tenancy.engine_workspace import active_workspaces
    from apps.workers.storage import delete_objects

    moved = 0
    if isinstance(engine, HostsVoices):
        for row in await active_workspaces():
            async with tenant_session(row.tenant_id) as session:
                copies = (
                    await session.execute(
                        text(
                            "SELECT id, workspace_id, vendor_clone_id FROM "
                            "engine_voice_clone_copies WHERE voice_id = :vid ORDER BY id"
                        ),
                        {"vid": voice_id},
                    )
                ).all()
            for copy_id, workspace, vendor_clone_id in copies:
                try:
                    with in_workspace(str(workspace)):
                        moved += await engine.delete_voice_clone(str(vendor_clone_id))
                except ProblemError as exc:
                    log.warning("engine_voice_clone_copy_not_deleted", extra={"code": exc.code})
                    continue
                async with tenant_session(row.tenant_id) as session:
                    await session.execute(
                        text("DELETE FROM engine_voice_clone_copies WHERE id = :id"),
                        {"id": copy_id},
                    )
    if sample_key:
        await delete_objects([sample_key])
    return moved


__all__ = [
    "SHARED_CLONE_NOT_LISTED",
    "client_voice_id",
    "forget_clone",
    "shared_clone_not_listed",
    "voice_in_workspace",
]
