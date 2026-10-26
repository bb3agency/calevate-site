"""Put it live: the autosaved draft (or a script sent with the request) becomes a version
with the owner's change summary and is applied to live calls (D-714).

One function behind two doors, the Script page's `POST /v1/agents/{id}/script/publish` and
Pip's `agent_script_put_live`, so both meet the same length refusal, version check and
"saved, but not live yet" wording.

The version is committed in its own transaction BEFORE `publishing.apply_to_live`, which
opens a session of its own and must see the new version; holding the save open across the
engine push would make the apply read the old pointer.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from calevate_shared.call_script import CallScript
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import publishing, script_builder
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session

#: Called inside the saving transaction with the version just written: the route's audit row.
OnSaved = Callable[[AsyncSession, int], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class PutLive:
    version: int
    #: True when callers now hear it; False while the agent is not switched on, or when the
    #: push to the calling system did not complete.
    live: bool


def nothing_to_publish() -> ProblemError:
    return ProblemError.business_rule(
        "script_nothing_to_publish", "There are no unpublished changes to put live."
    )


def draft_moved() -> ProblemError:
    return ProblemError.conflict(
        "script_changed_elsewhere",
        "The draft was changed after it was reviewed, so it was not put live.",
        remediation="Look at the draft again on the Script tab, then put it live.",
    )


async def put_draft_live(
    *,
    tenant_id: UUID,
    agent_id: UUID,
    summary: str,
    created_by: UUID | None,
    script: CallScript | None = None,
    check_version: bool = False,
    expected_version: int | None = None,
    draft_saved_at: datetime | None = None,
    on_saved: OnSaved | None = None,
) -> PutLive:
    """Save the draft as a version and apply it. `draft_saved_at`, when given, is the draft
    the person reviewed: a later autosave is refused rather than put live under their click."""
    async with tenant_session(tenant_id) as session:
        if script is None:
            draft = await script_builder.read_draft(session, agent_id)
            if draft is None:
                raise nothing_to_publish()
            if draft_saved_at is not None and draft.saved_at != draft_saved_at:
                raise draft_moved()
            script = draft.script
        # Before the version is stored or anything reaches the calling system: a script that
        # cannot fit is refused here with its length, and the draft is kept.
        await script_builder.refuse_if_too_long(session, agent_id, script)
        saved = await script_builder.save_agent_script(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            script=script,
            notes=summary,
            created_by=created_by,
            check_version=check_version,
            expected_version=expected_version,
        )
        await script_builder.clear_draft(session, agent_id)
        if on_saved is not None:
            await on_saved(session, saved.version)
    try:
        applied = await publishing.apply_to_live(
            tenant_id=tenant_id, agent_id=agent_id, expected_version=saved.version
        )
    except ProblemError as exc:
        # The version above is committed and the draft cleared, so a refusal from here on
        # must not read as "nothing happened": it says what is saved and how to finish. The
        # refusal itself is re-raised, so its code, status and alarm stay the raise site's.
        exc.title = "Saved, but not live yet"
        exc.detail = (
            f"Your changes are saved as version {saved.version}, and callers still hear the "
            f"previous script. Putting it live did not finish: {exc.detail}"
        )
        exc.remediation = (
            "Press Put it live again to finish; your changes are kept. " + (exc.remediation or "")
        ).strip()
        raise
    return PutLive(version=saved.version, live=applied.applied and applied.engine_synced)


__all__ = ["OnSaved", "PutLive", "draft_moved", "nothing_to_publish", "put_draft_live"]
