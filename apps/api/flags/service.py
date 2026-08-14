"""Resolving a per-tenant feature flag, and moving one.

RESOLUTION ORDER — platform default, then the tenant's override
---------------------------------------------------------------
`FLAGS[name].default` is what every tenant gets. A row in `tenant_feature_flags`
replaces it for exactly one tenant and one flag. **NO ROW IS REQUIRED FOR ANY TENANT**:
the absence of a row is not "unconfigured", it is the default, so declaring a flag costs
zero writes and a tenant nobody has ever touched resolves every flag correctly.

A stored row whose flag is not DECLARED is ignored, with a log line. That is the two-step
retirement hard rule 8 asks for, applied to rows: a release stops declaring the flag, the
rows stop being read the moment it deploys, and clearing them is a separate, unhurried
act (the console lists them as "no longer used by this build").

READING IS ONE QUERY PER REQUEST, AND THE CACHE IS THE REQUEST
--------------------------------------------------------------
Flags get read on hot paths by definition, so the cost is worth stating exactly: one
indexed read of `(tenant_id)` on a connection the caller already holds, inside the
transaction they are already in, memoised on the session for every later read in the same
request. It fetches ALL of the tenant's overrides at once, so a request that consults ten
flags pays for one query, not ten.

**There is deliberately no cross-request cache, and no Redis.** That is a product
decision as much as an engineering one, so it is written down rather than implied:

* **A flag flip takes effect on the NEXT REQUEST, everywhere, with no window.** That is a
  different product from one that takes thirty minutes — or fifteen seconds — to turn off,
  and this is the one built. `core/loadshed.py` is the counter-example that earns its
  cache: it is consulted on EVERY request including ones that touch nothing else, so a
  Postgres read per request would be pure overhead, and it pays for that cache with a
  three-layer invalidation, a TTL tuned under a dispatch tick, and a docstring about the
  time an immortal Redis key made a stale "open" permanent. A flag read happens inside a
  handler that is already talking to Postgres; there is no equivalent saving to buy.
* **Staleness here would be a safety question, not a performance one.** These flags may
  not gate a compliance control (`registry.py` states that limit and why), but the reason
  that limit is safe to rely on is that there is no window in which a flag says one thing
  and the database says another. A cache would introduce exactly that window, and the
  first thing to arrive in it would be a support call that says "we turned it off ten
  minutes ago".
* **No invalidation to get wrong.** The memo dies with the session, which dies with the
  request. The one case where it could be wrong within a single request is a write
  followed by a read on the same session, and the writer clears the memo (see
  `_forget_memo`) rather than leaving that to the caller.

If a measurement ever shows the query mattering, the honest next step is a shared
read-through cache with the invalidation designed WITH it and its staleness stated on the
console beside the switch — not a TTL added quietly.

WRITING IS COMPARE-AND-SWAP, AND AUDIT FOLLOWS A REAL CHANGE
-------------------------------------------------------------
BACKEND-PATTERNS §5: the guard goes in the WHERE clause and `rowcount == 0` is "lost the
race". Two operators moving the same flag from different reads is rare and its silent
outcome is bad — the loser's audit entry describes a transition that never happened — so
the second one gets a 409 naming what changed underneath them.

And per `admin.record_commercial_terms`, `approve_kb` and `integrations.deactivate_endpoint`:
a request that changes nothing returns `changed=False` and writes NO audit row. The log
answers "who changed this client's behaviour"; a row per button press makes that question
harder to answer, not easier.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of
from apps.api.flags.registry import FLAGS, FlagName, FlagSpec, spec_for

log = get_logger(__name__)

#: Where the per-request memo lives. `Session.info` is SQLAlchemy's own user-modifiable
#: per-session dict, and in this repo a session's life IS a request's transaction
#: (`db/session.tenant_session` opens one per `async with`), so the memo cannot outlive
#: the transaction that read it. A module-level dict keyed by tenant would outlive both.
_MEMO_KEY = "calevate.feature_flag_overrides"

FlagSource = Literal["platform_default", "tenant_override"]


@dataclass(frozen=True, slots=True)
class FlagResolution:
    """One flag's answer for one tenant, and WHERE the answer came from.

    `source` is carried rather than left to be inferred by comparing `enabled` against
    the default: a tenant explicitly overridden to the same value as the platform default
    is NOT the same fact as a tenant with no row, because the next change to the default
    reaches one and not the other. The console has to be able to tell them apart.
    """

    flag: str
    enabled: bool
    source: FlagSource


@dataclass(frozen=True, slots=True)
class StoredOverride:
    """A row as it stands, for the surface that shows who set it and why."""

    flag: str
    enabled: bool
    reason: str
    set_by_admin_id: UUID
    updated_at: datetime


_SELECT_OVERRIDES = (
    "SELECT flag, enabled, reason, set_by_admin_id, updated_at "
    "FROM tenant_feature_flags WHERE tenant_id = :tid ORDER BY flag"
)


async def read_overrides(session: AsyncSession, *, tenant_id: UUID) -> list[StoredOverride]:
    """Every stored override for this tenant — declared or not — ordered by flag name.

    Uncached and unfiltered on purpose: this is the ADMIN read, and its whole job is to
    show what is actually in the table, including rows for flags this build no longer
    declares. `resolve_flags` is the hot-path read and is the one that memoises.

    Hard rule 1: the session is RLS-scoped AND `tenant_id` is a predicate. The predicate
    is not the isolation — the GUC is — but a session scoped elsewhere returns zero rows
    twice over, and zero rows here resolves to the platform defaults, which is the SAFE
    direction: a tenant whose overrides we cannot see behaves like every other tenant.
    """
    rows = (await session.execute(text(_SELECT_OVERRIDES), {"tid": tenant_id})).all()
    return [
        StoredOverride(
            flag=str(row[0]),
            enabled=bool(row[1]),
            reason=str(row[2]),
            set_by_admin_id=row[3],
            updated_at=row[4],
        )
        for row in rows
    ]


async def _overrides(session: AsyncSession, *, tenant_id: UUID) -> dict[str, bool]:
    """This tenant's stored overrides, read once per session.

    The memo is keyed by tenant id as well as held on the session. A session is
    single-tenant by construction (the GUC is set once, transaction-locally), so the key
    is not what isolates anything — RLS is. It is here so that a caller which passes a
    DIFFERENT tenant than the session is scoped to can never be served the first tenant's
    answer out of memory: it re-reads, and the re-read returns zero rows because RLS
    refuses it. Without the key, a mismatched call would silently inherit whatever the
    first call cached, which is the shape of a cross-tenant leak even though no policy
    was involved.
    """
    memo = session.info.get(_MEMO_KEY)
    if isinstance(memo, tuple) and memo[0] == tenant_id:
        cached: dict[str, bool] = memo[1]
        return cached
    rows = await read_overrides(session, tenant_id=tenant_id)
    overrides = {row.flag: row.enabled for row in rows}
    session.info[_MEMO_KEY] = (tenant_id, overrides)
    return overrides


def _forget_memo(session: AsyncSession) -> None:
    """Drop the memo after a write, so a read-back in the same request is not stale."""
    session.info.pop(_MEMO_KEY, None)


async def resolve_flags(session: AsyncSession, *, tenant_id: UUID) -> dict[str, FlagResolution]:
    """Every DECLARED flag, resolved for this tenant. One query, memoised per session.

    The order is the whole contract: start from `FLAGS[name].default`, then let a stored
    row replace it. A flag with no row for this tenant comes back at its default with
    `source="platform_default"` — no row is required to exist for any tenant, ever.

    Keyed by `str` and NOT by `FlagName`, deliberately: the callers of THIS function
    iterate the whole mapping (the console), and the caller that names a single flag is
    `flag_enabled`, whose parameter is `FlagName` and which is therefore where a typo is
    caught. See `registry.FLAGS` for the same argument about the registry itself.
    """
    overrides = await _overrides(session, tenant_id=tenant_id)
    for stored in overrides:
        if spec_for(stored) is None:
            # A row for a flag this build no longer declares. Ignored rather than
            # obeyed — the code that read it is gone, so there is nothing for it to
            # change — and logged once per read so a forgotten row is discoverable
            # without opening psql. No tenant id in the line beyond the flag name: ids
            # are what we log (hard rule 6) and the flag name is a code identifier.
            log.info("feature_flag_row_undeclared", extra={"flag": stored})
    resolved: dict[str, FlagResolution] = {}
    for name, spec in FLAGS.items():
        if name in overrides:
            resolved[name] = FlagResolution(
                flag=name, enabled=overrides[name], source="tenant_override"
            )
        else:
            resolved[name] = FlagResolution(
                flag=name, enabled=spec.default, source="platform_default"
            )
    return resolved


async def flag_enabled(session: AsyncSession, *, tenant_id: UUID, flag: FlagName) -> bool:
    """Is this flag on for this tenant? THE call site a future gate uses.

    `flag` is typed `FlagName`, so a name that is not declared is a `mypy` failure here
    rather than a `False` that looks like a decision. Costs the same one memoised query
    as `resolve_flags` — they share it — so consulting three flags in one handler is
    still one round trip.
    """
    return (await resolve_flags(session, tenant_id=tenant_id))[flag].enabled


@dataclass(frozen=True, slots=True)
class FlagChange:
    """What a write did — including doing nothing, which is a legitimate outcome.

    `changed` is what the route audits on. `before` / `after` are EFFECTIVE values (the
    resolution, not the row), because that is what an operator and an auditor mean by
    "what did this do": clearing an override that happened to agree with the default
    changes the row and not the behaviour, and both halves of that are worth recording.
    """

    flag: str
    changed: bool
    before: FlagResolution
    after: FlagResolution


def _resolution(flag: str, spec: FlagSpec, override: bool | None) -> FlagResolution:
    if override is None:
        return FlagResolution(flag=flag, enabled=spec.default, source="platform_default")
    return FlagResolution(flag=flag, enabled=override, source="tenant_override")


def _lost_the_race(flag: str) -> ProblemError:
    return ProblemError.conflict(
        code="feature_flag_changed_concurrently",
        detail=(
            f"The {flag} flag was changed by someone else while this request was being "
            "prepared, so it was not applied."
        ),
        remediation="Re-read the flag, check what it says now, and send the change again.",
    )


async def set_flag(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    flag: str,
    enabled: bool,
    reason: str,
    set_by_admin_id: UUID,
) -> FlagChange:
    """Give this tenant an explicit position on one flag. Upsert, CAS, idempotent.

    `flag` is `str` rather than `FlagName` because every value that reaches this function
    arrives from a URL path segment, and it is REFUSED at runtime if the registry does not
    declare it. `flag_enabled` is where the `FlagName` type earns its keep — a typo on a
    READ silently answers "off", which looks like a decision, while a typo here raises.

    Three outcomes and each is a different statement:

    * **no row → insert.** `ON CONFLICT DO NOTHING` with `rowcount == 0` meaning another
      writer inserted between our read and our write — a 409, not a silent overwrite.
    * **row differs → update, guarded on the value we read.** The old value is in the
      WHERE clause, so a concurrent change loses the race loudly instead of producing an
      audit entry describing a transition that did not happen.
    * **row identical → nothing.** No write, no `updated_at` bump, `changed=False`, and
      the route writes no audit row.

    `reason` counts as part of the row: re-sending the same value with a corrected reason
    IS a change, and it updates the row and audits. The alternative — dropping a reason-
    only edit because the boolean matched — silently discards the operator's correction,
    which is worse than an extra audit entry.
    """
    spec = spec_for(flag)
    if spec is None:
        # Reachable only from inside the process: the route validates against the
        # registry at the boundary and returns a problem naming the flag. Kept because a
        # worker or a future caller could reach this directly, and an undeclared write
        # would create a row nothing will ever read.
        raise ProblemError(
            kind="validation",
            code="feature_flag_unknown",
            title="Unknown feature flag",
            detail=f"{flag!r} is not a flag this build declares.",
            remediation=f"Use one of: {', '.join(sorted(FLAGS))}.",
        )

    current = await _read_one(session, tenant_id=tenant_id, flag=flag)
    before = _resolution(flag, spec, None if current is None else current.enabled)

    if current is not None and current.enabled == enabled and current.reason == reason.strip():
        return FlagChange(flag=flag, changed=False, before=before, after=before)

    if current is None:
        inserted = (
            await session.execute(
                text(
                    "INSERT INTO tenant_feature_flags (id, tenant_id, flag, enabled, reason, "
                    "  set_by_admin_id, created_at, updated_at) "
                    "VALUES (:id, :tid, :flag, :enabled, :reason, :admin, now(), now()) "
                    "ON CONFLICT (tenant_id, flag) DO NOTHING RETURNING id"
                ),
                {
                    "id": uuid7(),
                    "tid": tenant_id,
                    "flag": flag,
                    "enabled": enabled,
                    "reason": reason.strip(),
                    "admin": set_by_admin_id,
                },
            )
        ).first()
        if inserted is None:
            raise _lost_the_race(flag)
    else:
        # CAS: the value we read is the guard. `rowcount == 0` = somebody else moved it.
        result = await session.execute(
            text(
                "UPDATE tenant_feature_flags SET enabled = :enabled, reason = :reason, "
                "  set_by_admin_id = :admin, updated_at = now() "
                "WHERE tenant_id = :tid AND flag = :flag AND enabled = :was"
            ),
            {
                "tid": tenant_id,
                "flag": flag,
                "enabled": enabled,
                "reason": reason.strip(),
                "admin": set_by_admin_id,
                "was": current.enabled,
            },
        )
        if rowcount_of(result) == 0:
            raise _lost_the_race(flag)

    _forget_memo(session)
    return FlagChange(
        flag=flag, changed=True, before=before, after=_resolution(flag, spec, enabled)
    )


async def clear_flag(session: AsyncSession, *, tenant_id: UUID, flag: str) -> FlagChange:
    """Drop this tenant's override so the flag follows the platform default again.

    `flag` is a plain `str`, NOT `FlagName`, and that asymmetry with `set_flag` is
    deliberate: setting an undeclared flag creates a row nothing will read (a typo made
    permanent), while CLEARING one is how a retired flag's rows are removed. Refusing to
    clear what this build no longer declares would make the retirement path unreachable
    from the product and leave psql as the only way out.

    Idempotent by construction: `RETURNING` on the DELETE tells us in one statement
    whether a row was there and what it said, so an operator clearing an override that is
    already absent gets `changed=False` and writes no audit row.
    """
    removed = (
        await session.execute(
            text(
                "DELETE FROM tenant_feature_flags WHERE tenant_id = :tid AND flag = :flag "
                "RETURNING enabled"
            ),
            {"tid": tenant_id, "flag": flag},
        )
    ).first()
    spec = spec_for(flag)
    after = (
        _resolution(flag, spec, None)
        if spec is not None
        # A retired flag resolves to nothing at all: no code reads it, so there is no
        # behaviour for it to have. Reported as the platform default `False` would be a
        # claim about a switch that no longer exists.
        else FlagResolution(flag=flag, enabled=False, source="platform_default")
    )
    if removed is None:
        return FlagChange(flag=flag, changed=False, before=after, after=after)
    before = (
        _resolution(flag, spec, bool(removed[0]))
        if spec is not None
        else FlagResolution(flag=flag, enabled=bool(removed[0]), source="tenant_override")
    )
    _forget_memo(session)
    return FlagChange(flag=flag, changed=True, before=before, after=after)


async def _read_one(session: AsyncSession, *, tenant_id: UUID, flag: str) -> StoredOverride | None:
    row = (
        await session.execute(
            text(
                "SELECT flag, enabled, reason, set_by_admin_id, updated_at "
                "FROM tenant_feature_flags WHERE tenant_id = :tid AND flag = :flag"
            ),
            {"tid": tenant_id, "flag": flag},
        )
    ).first()
    if row is None:
        return None
    return StoredOverride(
        flag=str(row[0]),
        enabled=bool(row[1]),
        reason=str(row[2]),
        set_by_admin_id=row[3],
        updated_at=row[4],
    )


__all__ = [
    "FlagChange",
    "FlagResolution",
    "FlagSource",
    "StoredOverride",
    "clear_flag",
    "flag_enabled",
    "read_overrides",
    "resolve_flags",
    "set_flag",
]
