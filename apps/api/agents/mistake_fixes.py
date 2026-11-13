"""The healer's fixes of real-call mistakes in an agent's own script (D-985).

A mistake on a real call (`call_mistakes`) that a line of the agent's script causes is fixed
in that script, put live with no person in the loop, and watched on the next calls; the
owner reads what happened on the Training tab and can undo it. The founder's decision of
12 Nov 2026 amends D-949 ("the agent never edits itself") and D-701 clause 6: the fix is
still not the agent editing itself from its own reading of its calls (the arXiv papers
`call_mistakes` cites), because the finding is a deterministic script check
(`mistake_lints`), the change may touch only the lines that check named
(`script_proposals.kept_to_paths`), it is verified by the same check before it goes live,
and it is undone automatically when the mistake comes back or other mistakes rise.

This module owns `agent_mistake_fixes`: opening a fix when a call shows a kind (in the
pipeline's own transaction, so a recorded mistake and its fix cannot part) or when the sweep
of live scripts finds a kind's cause before any call (D-989, `found_by = 'script_check'`,
`checks_due`/`mark_checked`), the per-agent state the owner reads, and the owner's Undo. The
fix's steps run as the healer playbook `call_mistake_fix` (`workers/mistake_fix`).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.models import MistakeFixFoundBy, MistakeFixState
from apps.api.agents.prompts import rollback_prompt
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.healer import incidents
from apps.api.healer.playbooks import CALL_MISTAKE_FIX, CALL_MISTAKE_SEEN, SCRIPT_CHECK_FOUND

#: The healer playbook that does the fix (`healer/playbooks.PLAYBOOKS`).
PLAYBOOK: Final = CALL_MISTAKE_FIX
#: The alarm code a fix's incident is opened with: raised once per opened fix, `record`.
TRIGGER: Final = CALL_MISTAKE_SEEN
#: The alarm code of a fix the sweep of live scripts opened (D-989), raised the same way.
CHECK_TRIGGER: Final = SCRIPT_CHECK_FOUND

#: Script parts a fix may never change, whatever a check names: the opening lines carry the
#: AI and recording notices in their own words (D-971), and the notice records say which
#: words those are. A notice is changed only by its own writer (`workers/opening_notices`).
PROTECTED_PARTS: Final = frozenset(
    {"opening_line", "outbound_opening_line", "opening_notices", "outbound_opening_notices"}
)

_COLUMNS = (
    "id, tenant_id, agent_id, kind, state, ended_because, attempts, waits, incident_id, "
    "proposal_id, version_before, version_base, version_after, live_at, settled_at, created_at, "
    "found_by"
)


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
    #: A real call showed the kind, or the sweep found its cause before any call (D-989).
    found_by: MistakeFixFoundBy = "call"


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


async def _opens_again(session: AsyncSession, fix: MistakeFix | None) -> bool:
    """Whether a call showing this kind starts a new fix, given the agent's newest one."""
    if fix is None or fix.state == "fixed":
        return True
    if fix.ended_because == "owner":
        # The owner put their script back: the healer does not redo what they undid.
        return False
    if not await _incident_resolved(session, fix.incident_id):
        return False
    if fix.state in ("fixing", "live"):
        await _settle_orphan(session, fix)
    return True


def _check_opens(fix: MistakeFix | None) -> bool:
    """Whether the sweep's finding starts a new fix, given the agent's newest one (D-989).
    Stricter than a call: a fix that was put back, undone or handed to our team stays so
    until a real call shows the kind again, or the sweep would redo it on the very version
    its rollback wrote."""
    return fix is None or fix.state == "fixed"


async def open_fixes(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    kinds: Iterable[str],
    found_by: MistakeFixFoundBy = "call",
) -> list[str]:
    """Start a fix for each kind that has none under way, each with its healer incident, in
    the caller's transaction: the pipeline's for the kinds a call showed, the sweep's for
    the kinds whose cause it found in a live script. Returns the kinds opened.

    The partial unique index on (agent, kind) for a fix in progress is the guard against two
    calls of one agent finishing together, or a call and the sweep; the loser's insert is a
    no-op."""
    latest = await latest_fixes(session, agent_id, kinds)
    opened: list[str] = []
    for kind in sorted(set(kinds)):
        if found_by == "script_check":
            if not _check_opens(latest.get(kind)):
                continue
        elif not await _opens_again(session, latest.get(kind)):
            continue
        fix_id = (
            await session.execute(
                text(
                    "INSERT INTO agent_mistake_fixes (id, tenant_id, agent_id, kind, found_by, "
                    "state, created_at, updated_at) VALUES (:id, :t, :a, :k, :by, 'fixing', "
                    "now(), now()) ON CONFLICT (agent_id, kind) WHERE state IN ('fixing', "
                    "'live') DO NOTHING RETURNING id"
                ),
                {"id": uuid7(), "t": tenant_id, "a": agent_id, "k": kind, "by": found_by},
            )
        ).scalar_one_or_none()
        if fix_id is None:
            continue
        incident_id, _ = await incidents.open_incident(
            session,
            key=incidents.dedupe_key(PLAYBOOK, agent_id, kind),
            playbook=PLAYBOOK,
            trigger_code=CHECK_TRIGGER if found_by == "script_check" else TRIGGER,
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


@dataclass(frozen=True, slots=True)
class DueCheck:
    """A live or paused agent whose live script the sweep has not checked yet (D-989)."""

    tenant_id: UUID
    agent_id: UUID
    live_version: int


async def checks_due(session: AsyncSession, *, limit: int) -> list[DueCheck]:
    """Up to `limit` agents whose live script version is not the one the sweep last checked,
    across every client. Called from an `admin_session()`: `agent_script_check_due` enters
    each client under its own tenant id (migration a9e4c7d2f5b1). A checked agent drops out
    until its live script changes, so a short batch never starves the clients after it."""
    rows = (
        await session.execute(
            text(
                "SELECT scanned_tenant_id, agent_id, live_version FROM agent_script_check_due(:n)"
            ),
            {"n": limit},
        )
    ).all()
    return [DueCheck(tenant_id=r[0], agent_id=r[1], live_version=int(r[2])) for r in rows]


async def checked_version(session: AsyncSession, agent_id: UUID) -> int | None:
    """The live script version the sweep last checked for this agent."""
    value = (
        await session.execute(
            text("SELECT script_checked_version FROM agents WHERE id = :a"), {"a": agent_id}
        )
    ).scalar_one_or_none()
    return None if value is None else int(value)


async def never_fixed_kinds(
    session: AsyncSession, *, agent_id: UUID, kinds: Iterable[str], days: int
) -> list[str]:
    """The kinds of `kinds` real calls of this agent showed in the last `days` that have no
    fix at all, in any state: the ones calls showed before fixes existed (D-985), which the
    pipeline never opened one for."""
    rows = (
        await session.execute(
            text(
                "SELECT DISTINCT m.kind FROM call_mistakes m WHERE m.agent_id = :a "
                "AND m.kind = ANY(:k) AND m.call_started_at > now() - make_interval(days => :d) "
                "AND NOT EXISTS (SELECT 1 FROM agent_mistake_fixes f WHERE f.agent_id = m.agent_id "
                "AND f.kind = m.kind) ORDER BY m.kind"
            ),
            {"a": agent_id, "k": sorted(set(kinds)), "d": days},
        )
    ).all()
    return [str(r[0]) for r in rows]


async def mark_checked(session: AsyncSession, *, agent_id: UUID, version: int) -> None:
    """The sweep checked this live version. Kept only while it is still the live one: a
    version put live during the check is checked on the next sweep."""
    await session.execute(
        text(
            "UPDATE agents a SET script_checked_version = :v WHERE a.id = :a AND "
            "(SELECT version FROM prompt_versions WHERE id = COALESCE(a.live_prompt_id, "
            "a.system_prompt_id)) = :v"
        ),
        {"a": agent_id, "v": version},
    )


#: Refused when the script changed after the fix went live, so putting back the version
#: from before it would also throw away that change.
SCRIPT_CHANGED_CODE: Final = "mistake_fix_script_changed"


async def undo_by_owner(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID, kind: str, by: UUID | None
) -> tuple[MistakeFix, int]:
    """Put back the script from before this kind's fix, for the owner, and stop the healer
    fixing it again. Returns the fix and the new (rolled-back) version."""
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
            remediation="Open the Script tab's history to put back the version you want.",
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
    "CHECK_TRIGGER",
    "PLAYBOOK",
    "PROTECTED_PARTS",
    "SCRIPT_CHANGED_CODE",
    "TRIGGER",
    "DueCheck",
    "FleetFix",
    "MistakeFix",
    "checked_version",
    "checks_due",
    "fix_for_incident",
    "fix_paths",
    "fleet_fixes",
    "latest_fixes",
    "live_version",
    "mark_checked",
    "never_fixed_kinds",
    "open_fixes",
    "undo_by_owner",
]
