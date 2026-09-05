"""When did this person's CURRENT run of sign-ins begin, and is it still running.

D-540. The founder made two decisions about the copilot conversation that pull against
each other — *it dies when the session ends*, and *the same user sees the same thread on
their phone and their desktop* — and resolved them: the conversation belongs to the USER,
and it is cleared when their **LAST** session ends. Signing out on a phone must not wipe
the thread open on a desktop.

So "the session ended" is not a question about one `auth_sessions` row. It is a question
about a RUN: the maximal stretch of wall-clock time over which the subject had at least
one live session at every instant. A run begins with a sign-in taken while nothing was
live, and ends when the last live session in it goes. `copilot_conversation_turns
.run_started_at` stamps every turn with the run it belongs to, and a turn from an older
run is deleted before it is read.

═══ WHY THIS IS COMPUTED AND NOT SIGNALLED ═══

**Expiry is not an event.** A session ends because `idle_expires_at` or
`absolute_expires_at` passed, and nothing runs at that instant — no trigger, no callback,
no last request. A design that hooked sign-out would therefore be correct for the sign-out
half and silently wrong for the half that actually happens most (a person closes the tab).
So the run start is DERIVED from the rows, which carry every instant needed to derive it,
and it is observed in two real places rather than assumed to fire in one:

1. **Lazily, on the next request** — `copilot/transcript.py` compares the stored
   `run_started_at` against this function on every load and every append, so a person who
   signed out of their last session and back in gets a fresh thread even if no sweep has
   run in between. This is what closes the sweep's window.
2. **By the cron** — `apps/workers/copilot_transcript.py` deletes the turns of every
   subject with no live session, which is what notices the person who never came back.

═══ THE COMPUTATION ═══

One interval per session row: `[created_at, ended_at)` where

    ended_at = LEAST(revoked_at, superseded_at, idle_expires_at, absolute_expires_at)

with the two nullable columns coalesced to `infinity`. Then this is the textbook
islands-and-gaps problem: a row starts an island when no EARLIER row's interval reaches
it, and the current run's start is the latest island start — which is the current one
precisely because at least one interval covers `now`, which is asserted rather than
assumed.

`>=` RATHER THAN `>` IN THE COVER TEST IS LOAD-BEARING, and it is what makes ROTATION
continuous. `authn/sessions.rotate_session` supersedes a row and inserts its successor at
the same instant, so `successor.created_at == predecessor.superseded_at` exactly; under
`>` the two intervals would abut without touching, every second factor proved would read
as a new run, and proving MFA would wipe the conversation the person was having.

═══ WHERE THIS OUGHT TO LIVE ═══

⚠ In `apps/api/authn/sessions.py`, beside `verify_session` and `revoke_family`, which is
where every other statement against `auth_sessions` is written and where D-165's doctrine
puts them ("apps/api/authn is the one package that says otherwise"). It is here because a
session-persistence lane held that package while this was written. **The move is a
relocation of two SQL strings and two functions with no caller change** — this module
imports nothing from `authn` and exports nothing back — and it is recorded so the next
person to open that package does it rather than adding a third reader.

What it reads is deliberately the narrowest thing that answers the question: timestamps
and subject ids. `token_hash` is never selected, and nothing here returns a session id, so
a mistake in this module cannot leak a credential.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import text

from apps.api.db.session import credential_session

#: One session's interval, as a CTE both queries share. Spelled once so the two cannot
#: disagree about what "ended" means — a divergence would make the lazy check and the
#: sweep clear conversations on different clocks.
_INTERVALS = """
SELECT id, subject_id, created_at,
       LEAST(
         COALESCE(revoked_at, 'infinity'::timestamptz),
         COALESCE(superseded_at, 'infinity'::timestamptz),
         idle_expires_at,
         absolute_expires_at
       ) AS ended_at
FROM auth_sessions
WHERE realm = :realm
"""

_RUN_START_SQL = f"""
WITH s AS ({_INTERVALS} AND subject_id = :subject_id)
SELECT max(s.created_at)
FROM s
WHERE EXISTS (SELECT 1 FROM s live WHERE live.ended_at > :now)
  AND NOT EXISTS (
    SELECT 1 FROM s p
    WHERE (p.created_at, p.id) < (s.created_at, s.id)
      AND p.ended_at >= s.created_at)
"""

_LIVE_SUBJECTS_SQL = f"""
WITH s AS ({_INTERVALS})
SELECT DISTINCT s.subject_id FROM s WHERE s.ended_at > :now
"""


def _instant(now: datetime | None) -> datetime:
    return now if now is not None else datetime.now(UTC)


async def current_run_start(
    *, realm: str, subject_id: UUID, now: datetime | None = None
) -> datetime | None:
    """When this subject's current unbroken run of sessions began, or None.

    `None` means "no live session right now", which is the same answer as "the run this
    caller is holding has ended" — a caller must treat it as a clearance, never as an
    error. It is unreachable from a request path (the request authenticated), and it is
    the ordinary answer for the sweep.
    """
    async with credential_session() as session:
        started = (
            await session.execute(
                text(_RUN_START_SQL),
                {"realm": realm, "subject_id": subject_id, "now": _instant(now)},
            )
        ).scalar()
    return started if isinstance(started, datetime) else None


async def subjects_with_live_sessions(
    *, realm: str, now: datetime | None = None
) -> frozenset[UUID]:
    """Every subject of this realm holding at least one live session.

    THE SWEEP'S DIRECTION IS THIS WAY ROUND ON PURPOSE. The alternative — one query per
    conversation asking "is this person still signed in" — is a credential-store round
    trip per user per tick, and it is the shape that tempts somebody to set `app.auth` on
    a tenant session so the two tables can be joined. Nothing outside `authn` may read
    the credential store in the same transaction as client data, so the answer is
    materialised here, once, and carried to the tenant statements as a plain array of ids.

    Bounded by CONCURRENTLY SIGNED-IN PEOPLE rather than by rows in any table: a subject
    with ten rotated sessions appears once, and a subject signed out appears not at all.
    """
    async with credential_session() as session:
        rows = (
            await session.execute(text(_LIVE_SUBJECTS_SQL), {"realm": realm, "now": _instant(now)})
        ).scalars()
        return frozenset(rows)


__all__ = ["current_run_start", "subjects_with_live_sessions"]
