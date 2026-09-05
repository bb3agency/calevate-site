"""The copilot conversation ends when its owner's LAST session does — this is what notices.

D-540. The founder's two decisions about the conversation pull against each other — it
dies when the session ends, and the same user sees the same thread on their phone and
their desktop — and the resolution is that it belongs to the USER and is cleared when
their LAST session goes. `copilot/session_run.py` derives when a person's current
unbroken run of sign-ins began, and every turn is stamped with it.

**EXPIRY IS A TIMESTAMP PASSING, NOT AN EVENT**, so it has to be OBSERVED somewhere real
rather than assumed to fire. Two places do, and they cover different halves:

* `copilot/transcript.load` and `.append_exchange` drop every turn from an older run
  before they read or write, so the person who signed out of their last session and back
  in gets a fresh thread on their next request whatever this job has or has not done. That
  is the LAZY observer, and it is what closes this job's window.
* **This job**, which is the only thing that ever notices the person who signed out — or
  let their last session lapse — and never came back. Without it their conversation would
  sit on disk until the retention clock reached it 365 days later, which is not what the
  founder decided and is not what the client is told.

**THE DIRECTION IS LIVE-SUBJECTS-FIRST, and it is the one design decision here.** The
obvious shape is a join: for each stored conversation, ask whether its owner still has a
session. It cannot be written. `auth_sessions` is FORCE-RLS'd behind `app.auth`, which
only `db.session.credential_session` sets, and `copilot_conversation_turns` is FORCE-RLS'd
behind `app.tenant_id`, which only `tenant_session` sets — so the join exists only in a
transaction holding BOTH, and a transaction that can read the credential store while it
reads client data is precisely what D-165's policy exists to prevent. So the live set is
materialised once, in its own credential transaction, and carried into the tenant
statements as a plain array of ids: no session ever holds both authorities.

The set is bounded by CONCURRENTLY SIGNED-IN PEOPLE, not by rows in any table — a subject
with ten rotated sessions appears once and a signed-out subject not at all — which is why
it is safe to hold in memory. The client realm's absolute session bound is 14 days, so
that is also the longest a dead conversation can survive a total outage of this job.

Every deletion here is a DELETE and not an anonymisation, for `retention._COPILOT_MEMORY_SQL`'s
reason: there is no anonymised form of a sentence, and a blanked turn is a bubble that
still renders and still says nothing.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from arq import Retry
from sqlalchemy import text

from apps.api.copilot import session_run, transcript
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.result import rowcount_of
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.db.transition import _identifier

log = get_logger(__name__)

#: The minute of the hour the cron fires on. Offset from every other copilot job so a
#: deployment's :00 is not four jobs deep.
TRANSCRIPT_SWEEP_MINUTE = 17

#: The worklist reason migration `c7e0b2a94f13`'s trigger registers. Same bridge
#: `copilot_memory` uses (D-368) and for the same reason: this job runs untenanted, the
#: turns table is FORCE-RLS'd and would return it zero rows, and `retention_worklist`
#: already grants an untenanted session the tenant IDS and nothing else.
WORKLIST_REASON = "copilot_transcript"

_TENANTS_SQL = "SELECT tenant_id FROM retention_worklist WHERE reason = :reason ORDER BY tenant_id"


def _sweep_sql(realm: transcript.Realm) -> str:
    """Every turn belonging to a subject of this realm with no live session.

    THE TABLE AND THE OWNER COLUMN GO THROUGH `db/transition._identifier` — the one way
    this repo interpolates an identifier, and what `scripts/check_raw_sql` reads. Neither
    is reachable from a request: `transcript.CLIENT` and `transcript.ADMIN` are the only
    two `Realm` values that exist, both built from literals, and this module names them
    directly. `copilot/transcript.Realm` carries the full trace.

    `<> ALL(:live)` and not `NOT IN`, because `NOT IN` against an EMPTY array is `true`
    for every row — which is the correct answer here (nobody is signed in, so every
    conversation is over) but is the wrong reflex to leave in a statement that deletes.
    `<> ALL` says the same thing and says it the same way when the array is empty.
    """
    table = _identifier(realm.table, "table")
    owner = _identifier(realm.owner, "owner column")
    return f"DELETE FROM {table} WHERE {owner} <> ALL(:live)"


async def sweep_ended_conversations(ctx: dict[str, Any]) -> str:
    """Hourly. Delete the copilot conversation of everyone whose last session has gone.

    ISOLATED PER TENANT, for `copilot_memory.distil_copilot_memories`' reason: one
    account's lock timeout must not end the tick for everyone behind it. What DOES reach
    the retry ladder is a tick-wide failure — the credential read or the worklist read —
    because retrying that is the only thing that could help.

    NOTHING IS LOGGED BUT COUNTS (hard rule 6). Not a user id, not a tenant's name and
    certainly not a turn: this job's whole subject matter is prose a client's staff typed.
    """
    try:
        live_clients = await session_run.subjects_with_live_sessions(realm="client")
        live_operators = await session_run.subjects_with_live_sessions(realm="admin")
        async with untenanted_session() as session:
            tenants = [
                UUID(str(row))
                for row in (await session.execute(text(_TENANTS_SQL), {"reason": WORKLIST_REASON}))
                .scalars()
                .all()
            ]
    except Exception as failure:
        attempt = int(ctx.get("job_try", 1))
        if attempt < WORKER_MAX_TRIES:
            raise Retry(defer=attempt * 30) from failure
        alert(
            "WORKER_TERMINAL",
            "copilot_transcript_sweep_failed",
            detail="the copilot conversation sweep could not read its inputs",
            error=type(failure).__name__,
        )
        raise

    swept = 0
    for tenant_id in tenants:
        try:
            async with tenant_session(tenant_id) as session:
                result = await session.execute(
                    text(_sweep_sql(transcript.CLIENT)), {"live": list(live_clients)}
                )
                swept += int(rowcount_of(result) or 0)
        except Exception as failure:
            # A count and an exception TYPE. One tenant's failure is a line an operator can
            # act on; it is not a reason to leave every other account's dead conversation
            # on disk, and the next tick retries this one for free.
            log.warning(
                "copilot_transcript_sweep_tenant_failed",
                extra={"error": type(failure).__name__},
            )

    # THE ADMIN REALM, in its own untenanted transaction because its table carries no
    # tenant and no policy (`db/registry.py` holds the standing justification). It is not
    # in the worklist and cannot be: `retention_worklist` is keyed on a tenant, and these
    # rows belong to the platform.
    admin_swept = 0
    try:
        async with untenanted_session() as session:
            result = await session.execute(
                text(_sweep_sql(transcript.ADMIN)), {"live": list(live_operators)}
            )
            admin_swept = int(rowcount_of(result) or 0)
    except Exception as failure:
        log.warning(
            "copilot_transcript_sweep_admin_failed",
            extra={"error": type(failure).__name__},
        )

    return f"swept {swept} client turn(s), {admin_swept} operator turn(s)"


__all__ = ["TRANSCRIPT_SWEEP_MINUTE", "WORKLIST_REASON", "sweep_ended_conversations"]
