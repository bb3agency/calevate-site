"""One state-transition primitive: CAS the row, then name the zero-row fact.

A state-transition endpoint has THREE answers to give and a bare CAS only knows two
of them. `UPDATE ... WHERE id = :id AND status IN (...)` affecting zero rows means any
of:

  1. the row is already in the state the caller asked for — pausing a paused campaign,
     approving an approved source, the second click of a button or the retry of a
     request whose response was lost;
  2. the row moved to some OTHER state — someone cancelled it, someone rejected it;
  3. the row is not there at all (or, under RLS, belongs to another tenant, which is
     deliberately the same answer — see `ProblemError.not_found`).

Collapsing all three into one 409 tells an operator "conflict" when nothing conflicts,
and tells them a row exists when it does not. The discriminator this module implements
is the repo's established one:

    the intent already holds  -> SUCCESS (idempotent; RFC 9110 §9.2.2 — the effect of
                                 N > 1 identical requests is the effect of one)
    a DIFFERENT state         -> 409 `invalid_status_transition`, naming the state found
    genuinely absent          -> 404

It is the same shape `ingest.service.set_active` and `integrations.service.
deactivate_endpoint` already use for their two-state flags, generalised to a status
column so the multi-state machines (campaign pause/resume, KB approve/reject) stop
having a second, worse one. The ordering matters and is the reason those two docstrings
give: **the CAS runs FIRST and unconditionally**, so two concurrent callers both reach
the database and exactly one of them reports the transition. The SELECT below only ever
runs on the losing path, writes nothing, and exists solely to say which of the two
zero-row facts it was — it cannot reintroduce a read-then-write race.

Consequences worth knowing before calling it:

- The return value is what keeps ledgers honest: an audit row belongs to a real
  transition, not to a button press (`integrations/routes.py::deactivate_endpoint`
  makes the same call for the same reason).
- Under RLS a neighbour's id updates nothing and then reads no row, so it 404s exactly
  like an id that never existed. Callers must run inside `tenant_session`.
- `visible_where` extends that last sentence to the OTHER ways a row can fail to exist
  for a caller — today, `leads.deleted_at IS NULL`. It is applied to the CAS **and** to
  the discriminating SELECT, never one of them: applied to the UPDATE alone, a
  soft-deleted row would fall through to a SELECT that finds it and answer 409 naming a
  status the caller is not entitled to know it has; applied to the SELECT alone, the
  CAS would resurrect it. The two together are what make "invisible" and "absent" one
  answer, which is the same claim the paragraph above makes about RLS.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import InvalidStatusTransitionError, ProblemError
from apps.api.db.result import rowcount_of

# Bind names this module reserves. Callers pass their own extra params for `extra_set`;
# the prefix keeps the two sets from colliding silently.
_RESERVED = "__t_"


def _identifier(value: str, what: str) -> str:
    """Refuse anything that is not a bare SQL identifier.

    `table` and `status_column` are interpolated, so they may only ever be literals
    written in our own source. This asserts that at the boundary rather than trusting
    every future caller to have read the docstring.
    """
    if not value.isidentifier():
        raise ValueError(f"{what} must be a plain identifier, got {value!r}")
    return value


async def transition_status(
    session: AsyncSession,
    *,
    table: str,
    entity: str,
    row_id: UUID,
    to_status: str,
    from_statuses: Sequence[str],
    extra_set: str = "",
    visible_where: str = "",
    params: Mapping[str, Any] | None = None,
    status_column: str = "status",
) -> bool:
    """Move `row_id` into `to_status`; True when THIS call is what moved it.

    Returns False when the row already held `to_status` — the caller's intent, already
    satisfied. Raises `InvalidStatusTransitionError` (409) when the row is in some other
    state, and `ProblemError.not_found` (404) when no visible row has that id.

    `entity` is the display name used in both errors ("Campaign", "Knowledge source").
    `extra_set` is extra assignments for the transition (`"approved_by = :by"`), whose
    binds come in `params`; `updated_at = now()` is always appended, because a status
    change that does not move `updated_at` is invisible to every "what changed" query.

    `visible_where` is the caller's row-visibility predicate (`"deleted_at IS NULL"`),
    interpolated like `extra_set` and therefore, like `extra_set`, only ever written as
    a literal in our own source. Its binds also come in `params`. It reaches BOTH
    statements — see the module docstring for why splitting it is a disclosure bug and
    not merely untidy.
    """
    table = _identifier(table, "table")
    status_column = _identifier(status_column, "status_column")
    if not from_statuses:
        raise ValueError("from_statuses must name at least one state")
    supplied = dict(params or {})
    if any(key.startswith(_RESERVED) for key in supplied):
        raise ValueError(f"caller params may not start with {_RESERVED!r}")

    from_binds = {f"{_RESERVED}from{i}": state for i, state in enumerate(from_statuses)}
    assignments = [f"{status_column} = :{_RESERVED}to"]
    if extra_set:
        assignments.append(extra_set)
    assignments.append("updated_at = now()")
    # Parenthesised: a caller writing `"a IS NULL OR b IS NULL"` must not have the OR
    # bind looser than the AND that joins it to the id predicate.
    visible = f" AND ({visible_where})" if visible_where else ""

    result = await session.execute(
        text(
            f"UPDATE {table} SET {', '.join(assignments)} "
            f"WHERE id = :{_RESERVED}id "
            f"AND {status_column} IN ({', '.join(f':{k}' for k in from_binds)})"
            f"{visible}"
        ),
        {
            f"{_RESERVED}to": to_status,
            f"{_RESERVED}id": row_id,
            **from_binds,
            **supplied,
        },
    )
    if rowcount_of(result) == 1:
        return True

    # `.first()`, not `.scalar()`: a NULL status and an absent row are different facts
    # and `.scalar()` returns None for both — the 404 must mean "no row".
    #
    # `supplied` rides along because `visible_where` may carry binds of its own.
    # SQLAlchemy's `text()` compiles only the `:names` it finds in the string, so the
    # `extra_set` binds that this SELECT does not mention are dropped rather than
    # rejected — which is what lets one params dict serve both statements.
    row = (
        await session.execute(
            text(f"SELECT {status_column} FROM {table} WHERE id = :{_RESERVED}id{visible}"),
            {f"{_RESERVED}id": row_id, **supplied},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found(entity)
    current = str(row[0])
    if current == to_status:
        return False
    raise InvalidStatusTransitionError(entity.lower(), current, to_status)


__all__ = ["transition_status"]
