"""The healer's fixes of real-call mistakes (D-985, D-1005).

A mistake on a real call (`call_mistakes`) that a line of a script causes is fixed in the
script the call was spoken from: the Inbound line or campaign the call was on (D-1005). An
agent has no script of its own (D-997, D-1000), so a call on neither has no script to fix,
and the fix says so (`no_job`). The fix is Pip's, written as a draft on that line or
campaign (`script_proposal`), which the owner reviews there like any Pip draft; nothing
reaches a caller until they keep it and put it live. The finding is a deterministic script
check (`mistake_lints`) and the change may touch only the lines that check named
(`script_proposals.kept_to_paths`), so this is still not the agent editing itself from its
own reading of its calls (D-949, the arXiv papers `call_mistakes` cites).

Before D-1005 the healer put a fix into the agent's own script itself, watched the next
calls and put the old script back when they went worse. Fixes made that way (`live`,
`fixed` with versions) are still listed and still undone by the owner's Undo
(`undo_by_owner`); nothing new is made that way.

This module owns `agent_mistake_fixes`: opening a fix when a call shows a kind (in the
pipeline's own transaction, so a recorded mistake and its fix cannot part), where its draft
goes (`holder_of_latest_call`, `request_holder_fix`), the per-agent state the owner reads,
and the owner's Undo. The fix's steps run as the healer playbook `call_mistake_fix`
(`workers/mistake_fix`).
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Literal
from uuid import UUID

from calevate_shared.call_script import CallScript
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.models import MistakeFixFoundBy, MistakeFixState
from apps.api.agents.prompts import rollback_prompt
from apps.api.campaigns.workspace import CampaignProposal, read_script_proposal
from apps.api.copilot.consent import account_content_may_reach_models
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.healer import incidents
from apps.api.healer.playbooks import CALL_MISTAKE_FIX, CALL_MISTAKE_SEEN
from apps.api.reliability.service import enqueue_outbox

#: The healer playbook that does the fix (`healer/playbooks.PLAYBOOKS`).
PLAYBOOK: Final = CALL_MISTAKE_FIX
#: The alarm code a fix's incident is opened with: raised once per opened fix, `record`.
TRIGGER: Final = CALL_MISTAKE_SEEN
#: The job that writes a fix's draft on its line or campaign (`workers/script_proposal`).
MISTAKE_FIX_JOB: Final = "draft_mistake_fix"

#: Script parts a fix may never change, whatever a check names: the opening lines carry the
#: AI and recording notices in their own words (D-971), and the notice records say which
#: words those are. A notice is changed only by its own writer (`workers/opening_notices`).
PROTECTED_PARTS: Final = frozenset(
    {"opening_line", "outbound_opening_line", "opening_notices", "outbound_opening_notices"}
)

_COLUMNS = (
    "id, tenant_id, agent_id, kind, state, ended_because, attempts, waits, incident_id, "
    "proposal_id, version_before, version_base, version_after, live_at, settled_at, created_at, "
    "found_by, inbound_line_id, campaign_id"
)

HolderKind = Literal["inbound_line", "campaign"]


@dataclass(frozen=True, slots=True)
class Holder:
    """The Inbound line or campaign a call was spoken from, which holds the script a fix of
    that call's mistake is written into."""

    kind: HolderKind
    id: UUID


def _change_word(kind: HolderKind) -> str:
    return "Inbound line" if kind == "inbound_line" else "Campaign"


def holder_table(kind: HolderKind) -> str:
    """The holder's table as a literal, so SQL spliced with it is built only from text
    written here (`scripts/check_raw_sql.py`)."""
    return "inbound_lines" if kind == "inbound_line" else "campaigns"


@dataclass(frozen=True, slots=True)
class MistakeFix:
    id: UUID
    tenant_id: UUID
    agent_id: UUID
    kind: str
    state: MistakeFixState
    ended_because: str | None
    attempts: int
    waits: int
    incident_id: UUID | None
    proposal_id: UUID | None
    version_before: int | None
    version_base: int | None
    version_after: int | None
    live_at: datetime | None
    settled_at: datetime | None
    created_at: datetime
    #: A real call showed the kind, or (before D-1005) the sweep of live agent scripts found
    #: its cause before any call (D-989).
    found_by: MistakeFixFoundBy = "call"
    #: Where the fix's draft was written (D-1005).
    inbound_line_id: UUID | None = None
    campaign_id: UUID | None = None

    @property
    def holder(self) -> Holder | None:
        if self.inbound_line_id is not None:
            return Holder("inbound_line", self.inbound_line_id)
        if self.campaign_id is not None:
            return Holder("campaign", self.campaign_id)
        return None


def _fix(row: Any) -> MistakeFix:
    return MistakeFix(
        id=row[0],
        tenant_id=row[1],
        agent_id=row[2],
        kind=str(row[3]),
        state=row[4],
        ended_because=row[5],
        attempts=int(row[6]),
        waits=int(row[7]),
        incident_id=row[8],
        proposal_id=row[9],
        version_before=row[10],
        version_base=row[11],
        version_after=row[12],
        live_at=row[13],
        settled_at=row[14],
        created_at=row[15],
        found_by=row[16],
        inbound_line_id=row[17],
        campaign_id=row[18],
    )


def fix_paths(findings: Iterable[str]) -> list[str]:
    """The paths a fix of `findings` may change: each finding's path, never a protected
    part (`PROTECTED_PARTS`), in a stable order."""
    paths = {finding.partition(": ")[0] for finding in findings}
    return sorted(p for p in paths if p.split(".")[0] not in PROTECTED_PARTS)


async def latest_fixes(
    session: AsyncSession, agent_id: UUID, kinds: Iterable[str]
) -> dict[str, MistakeFix]:
    """This agent's newest fix of each kind."""
    wanted = sorted(set(kinds))
    if not wanted:
        return {}
    rows = (
        await session.execute(
            text(
                f"SELECT DISTINCT ON (kind) {_COLUMNS} FROM agent_mistake_fixes "
                "WHERE agent_id = :a AND kind = ANY(:k) ORDER BY kind, created_at DESC, id DESC"
            ),
            {"a": agent_id, "k": wanted},
        )
    ).all()
    return {str(row[3]): _fix(row) for row in rows}


async def fix_for_incident(session: AsyncSession, incident_id: UUID) -> MistakeFix | None:
    row = (
        await session.execute(
            text(
                f"SELECT {_COLUMNS} FROM agent_mistake_fixes WHERE incident_id = :i "
                "ORDER BY created_at DESC, id DESC LIMIT 1"
            ),
            {"i": incident_id},
        )
    ).first()
    return _fix(row) if row else None


async def _incident_resolved(session: AsyncSession, incident_id: UUID | None) -> bool:
    if incident_id is None:
        return True
    row = (
        await session.execute(
            text("SELECT resolved_at IS NOT NULL FROM heal_incidents WHERE id = :i"),
            {"i": incident_id},
        )
    ).first()
    return row is None or bool(row[0])


async def _settle_orphan(session: AsyncSession, fix: MistakeFix) -> None:
    """A fix in progress whose incident a person closed: a live one they accepted, one not
    yet live they took over."""
    state = "fixed" if fix.state == "live" else "needs_person"
    await session.execute(
        text(
            "UPDATE agent_mistake_fixes SET state = :s, settled_at = now(), updated_at = now(), "
            "ended_because = CASE WHEN :s = 'fixed' THEN ended_because ELSE 'waited_too_long' "
            "END WHERE id = :id AND state = :was"
        ),
        {"s": state, "id": fix.id, "was": fix.state},
    )


async def draft_waiting(session: AsyncSession, fix: MistakeFix) -> bool:
    """Whether the fix's own draft still waits on its line or campaign for the owner."""
    holder = fix.holder
    if holder is None or fix.proposal_id is None:
        return False
    found = (
        await session.execute(
            text(
                f"SELECT 1 FROM {holder_table(holder.kind)} WHERE id = :h "
                "AND script_proposal->>'id' = :p"
            ),
            {"h": holder.id, "p": str(fix.proposal_id)},
        )
    ).first()
    return found is not None


async def _opens_again(session: AsyncSession, fix: MistakeFix | None) -> bool:
    """Whether a call showing this kind starts a new fix, given the agent's newest one."""
    if fix is None or fix.state == "fixed":
        return True
    if fix.ended_because == "owner":
        # The owner put their script back: the healer does not redo what they undid.
        return False
    if fix.state == "proposed":
        # One draft at a time: the next is written once the owner has looked at this one.
        return not await draft_waiting(session, fix)
    if not await _incident_resolved(session, fix.incident_id):
        return False
    if fix.state in ("fixing", "live"):
        await _settle_orphan(session, fix)
    return True


async def open_fixes(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    kinds: Iterable[str],
) -> list[str]:
    """Start a fix for each kind that has none under way, each with its healer incident, in
    the pipeline's transaction for the kinds a call showed. Returns the kinds opened.

    The partial unique index on (agent, kind) for a fix in progress is the guard against two
    calls of one agent finishing together; the loser's insert is a no-op.

    None opens while the owner has Pip off: the fix is Pip's draft, written by a model from
    the line's or campaign's script, and nobody asked for it. The mistake still shows on the
    Training tab, and the first call showing it after Pip is on opens the fix."""
    if not await account_content_may_reach_models(session, tenant_id=tenant_id):
        return []
    latest = await latest_fixes(session, agent_id, kinds)
    opened: list[str] = []
    for kind in sorted(set(kinds)):
        if not await _opens_again(session, latest.get(kind)):
            continue
        fix_id = (
            await session.execute(
                text(
                    "INSERT INTO agent_mistake_fixes (id, tenant_id, agent_id, kind, found_by, "
                    "state, created_at, updated_at) VALUES (:id, :t, :a, :k, 'call', 'fixing', "
                    "now(), now()) ON CONFLICT (agent_id, kind) WHERE state IN ('fixing', "
                    "'live') DO NOTHING RETURNING id"
                ),
                {"id": uuid7(), "t": tenant_id, "a": agent_id, "k": kind},
            )
        ).scalar_one_or_none()
        if fix_id is None:
            continue
        incident_id, _ = await incidents.open_incident(
            session,
            key=incidents.dedupe_key(PLAYBOOK, agent_id, kind),
            playbook=PLAYBOOK,
            trigger_code=TRIGGER,
            scope="agent",
            tenant_id=tenant_id,
            agent_id=agent_id,
        )
        await session.execute(
            text("UPDATE agent_mistake_fixes SET incident_id = :i WHERE id = :id"),
            {"i": incident_id, "id": fix_id},
        )
        opened.append(kind)
    return opened


# --- where the fix goes (D-1005) ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LatestCall:
    """The newest call of the agent that showed a kind, and what it was spoken from."""

    call_id: UUID
    holder: Holder | None


async def holder_of_latest_call(
    session: AsyncSession, *, agent_id: UUID, kind: str
) -> LatestCall | None:
    """The newest call of this agent that showed `kind`, and the line or campaign it was on
    (`calls.inbound_line_id` / `calls.campaign_id`), or None when no call showed it."""
    row = (
        await session.execute(
            text(
                "SELECT c.id, c.inbound_line_id, c.campaign_id FROM call_mistakes m "
                "JOIN calls c ON c.id = m.call_id WHERE m.agent_id = :a AND m.kind = :k "
                "ORDER BY m.call_started_at DESC, m.id DESC LIMIT 1"
            ),
            {"a": agent_id, "k": kind},
        )
    ).first()
    if row is None:
        return None
    if row[1] is not None:
        return LatestCall(row[0], Holder("inbound_line", row[1]))
    if row[2] is not None:
        return LatestCall(row[0], Holder("campaign", row[2]))
    return LatestCall(row[0], None)


@dataclass(frozen=True, slots=True)
class HolderScript:
    """A line's or campaign's script, its Pip draft, and its name, as a fix reads them."""

    holder: Holder
    agent_id: UUID
    name: str
    script: CallScript | None
    proposal: CampaignProposal | None


async def read_holder(
    session: AsyncSession, holder: Holder, *, lock: bool = False
) -> HolderScript | None:
    """The holder, or None once it is archived or gone."""
    row = (
        await session.execute(
            text(
                "SELECT agent_id, name, script, script_proposal FROM "
                f"{holder_table(holder.kind)} WHERE id = :h AND archived_at IS NULL"
                + (" FOR UPDATE" if lock else "")
            ),
            {"h": holder.id},
        )
    ).first()
    if row is None:
        return None
    return HolderScript(
        holder=holder,
        agent_id=row[0],
        name=str(row[1] or ""),
        script=CallScript.model_validate(row[2]) if row[2] else None,
        proposal=read_script_proposal(row[3], now=datetime.now(UTC)),
    )


#: Refused when the holder already has a Pip draft being written or waiting for review: a
#: fix never replaces one the owner has not seen.
DRAFT_OPEN_CODE: Final = "mistake_fix_draft_open"


async def request_holder_fix(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    holder: Holder,
    kind: str,
    label: str,
    paths: list[str],
    base: CallScript,
) -> UUID:
    """Record the fix's draft on the holder, in the shape its own Pip draft has
    (`campaigns.workspace.read_script_proposal`), and queue the job that writes it, in the
    caller's transaction. A failed draft is replaced; one drafting or ready is refused."""
    current = await read_holder(session, holder, lock=True)
    if current is None:
        raise ProblemError.not_found(_change_word(holder.kind))
    if current.proposal is not None and current.proposal.status in ("drafting", "ready"):
        raise ProblemError.conflict(
            DRAFT_OPEN_CODE,
            "A draft from Pip is already waiting here.",
            remediation="Keep or discard it first.",
        )
    proposal_id = uuid7()
    record = {
        "id": str(proposal_id),
        "status": "drafting",
        "requested_at": datetime.now(UTC).isoformat(),
        "requested_by": None,
        "base_script": base.model_dump(mode="json"),
        "paths": paths,
        "fix_kind": kind,
        "fix_label": label,
    }
    await session.execute(
        text(
            f"UPDATE {holder_table(holder.kind)} SET script_proposal = "
            "CAST(:p AS jsonb) WHERE id = :h"
        ),
        {"p": json.dumps(record), "h": holder.id},
    )
    await enqueue_outbox(
        session,
        job=MISTAKE_FIX_JOB,
        payload={
            "tenant_id": str(tenant_id),
            "holder_kind": holder.kind,
            "holder_id": str(holder.id),
            "proposal_id": str(proposal_id),
        },
    )
    return proposal_id


# --- the fixes made before D-1005, which the owner may still undo --------------------------


async def live_version(session: AsyncSession, agent_id: UUID) -> tuple[int | None, int | None]:
    """(live version, draft-pointer version) of the agent's script. The live pointer is NULL
    when the two agree (`prompts.insert_prompt_version`)."""
    row = (
        await session.execute(
            text(
                "SELECT lv.version, dv.version FROM agents a "
                "LEFT JOIN prompt_versions dv ON dv.id = a.system_prompt_id "
                "LEFT JOIN prompt_versions lv ON lv.id = COALESCE(a.live_prompt_id, "
                "a.system_prompt_id) WHERE a.id = :a AND a.deleted_at IS NULL"
            ),
            {"a": agent_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    return row[0], row[1]


#: Refused when the script changed after the fix went live, so putting back the version
#: from before it would also throw away that change.
SCRIPT_CHANGED_CODE: Final = "mistake_fix_script_changed"


async def undo_by_owner(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID, kind: str, by: UUID | None
) -> tuple[MistakeFix, int]:
    """Put back the script from before this kind's fix, for the owner, and stop the healer
    fixing it again. Returns the fix and the new (rolled-back) version. Only a fix the healer
    put live itself, before D-1005, has a version to put back."""
    row = (
        await session.execute(
            text(
                f"SELECT {_COLUMNS} FROM agent_mistake_fixes WHERE agent_id = :a AND kind = :k "
                "ORDER BY created_at DESC, id DESC LIMIT 1 FOR UPDATE"
            ),
            {"a": agent_id, "k": kind},
        )
    ).first()
    fix = _fix(row) if row else None
    if (
        fix is None
        or fix.state not in ("live", "fixed")
        or fix.version_before is None
        or fix.version_after is None
    ):
        raise ProblemError.not_found("Script fix")
    live, draft = await live_version(session, agent_id)
    if live != fix.version_after or draft != fix.version_after:
        raise ProblemError.conflict(
            SCRIPT_CHANGED_CODE,
            "Your script changed after this fix, so it cannot be undone on its own.",
            remediation="Ask Pip to put back the version you want.",
        )
    version = await rollback_prompt(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        version=fix.version_before,
        created_by=by,
    )
    await session.execute(
        text(
            "UPDATE agent_mistake_fixes SET state = 'rolled_back', ended_because = 'owner', "
            "settled_at = now(), undone_by = :by, updated_at = now() WHERE id = :id"
        ),
        {"by": by, "id": fix.id},
    )
    if fix.incident_id is not None:
        await session.execute(
            text(
                "UPDATE heal_incidents SET state = 'resolved', resolved_at = now(), "
                "last_outcome = 'undone', updated_at = now() WHERE id = :i "
                "AND resolved_at IS NULL"
            ),
            {"i": fix.incident_id},
        )
        await session.execute(
            text(
                "UPDATE heal_client_incidents SET state = 'resolved', resolved_at = now(), "
                "restored_notified_at = now(), updated_at = now() "
                "WHERE incident_id = :i AND state = 'open'"
            ),
            {"i": fix.incident_id},
        )
    return fix, version


@dataclass(frozen=True, slots=True)
class FleetFix:
    """One agent's script fix on the operator's board."""

    id: UUID
    client_slug: str
    agent_id: UUID
    agent_name: str
    kind: str
    state: MistakeFixState
    ended_because: str | None
    attempts: int
    version_before: int | None
    version_after: int | None
    live_at: datetime | None
    settled_at: datetime | None
    created_at: datetime
    found_by: MistakeFixFoundBy


async def fleet_fixes(session: AsyncSession, *, since: datetime, limit: int) -> list[FleetFix]:
    """Every client's script fixes opened since `since` or still in progress, newest first.
    Called from an `admin_session()`: `agent_mistake_fix_scan` enters each client under its
    own tenant id (migrations c4e8a2f6d1b9, a9e4c7d2f5b1)."""
    rows = (
        await session.execute(
            text(
                "SELECT s.fix_id, o.slug, s.agent_id, s.agent_name, s.kind, s.state, "
                "s.ended_because, s.attempts, s.version_before, s.version_after, s.live_at, "
                "s.settled_at, s.created_at, s.found_by FROM agent_mistake_fix_scan(:since) s "
                "JOIN organizations o ON o.id = s.scanned_tenant_id "
                "ORDER BY (s.state IN ('fixing', 'live')) DESC, s.created_at DESC LIMIT :n"
            ),
            {"since": since, "n": limit},
        )
    ).all()
    return [
        FleetFix(
            id=r[0],
            client_slug=str(r[1]),
            agent_id=r[2],
            agent_name=str(r[3] or ""),
            kind=str(r[4]),
            state=r[5],
            ended_because=r[6],
            attempts=int(r[7]),
            version_before=r[8],
            version_after=r[9],
            live_at=r[10],
            settled_at=r[11],
            created_at=r[12],
            found_by=r[13],
        )
        for r in rows
    ]


__all__ = [
    "DRAFT_OPEN_CODE",
    "MISTAKE_FIX_JOB",
    "PLAYBOOK",
    "PROTECTED_PARTS",
    "SCRIPT_CHANGED_CODE",
    "TRIGGER",
    "FleetFix",
    "Holder",
    "HolderKind",
    "HolderScript",
    "LatestCall",
    "MistakeFix",
    "draft_waiting",
    "fix_for_incident",
    "fix_paths",
    "fleet_fixes",
    "holder_of_latest_call",
    "holder_table",
    "latest_fixes",
    "live_version",
    "open_fixes",
    "read_holder",
    "request_holder_fix",
    "undo_by_owner",
]
