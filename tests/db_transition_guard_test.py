"""The three refusals `db.transition.transition_status` makes before it touches the database.

These are PROGRAMMER-ERROR guards, not user-reachable paths, and they are tested for a
reason that is specific rather than dutiful: `table` and `status_column` are the only two
values this function INTERPOLATES into SQL. Everything else is a bound parameter. So
`_identifier` is the whole of the defence between a future caller passing a name it
computed and a status-transition helper that concatenates it — and an untested guard is
indistinguishable from a guard someone deleted.

They are unit tests with no session because all three raise BEFORE the first `execute`.
Passing `None` as the session is the assertion: if any of these guards ever moves below
the query, this file fails with `AttributeError` instead of `ValueError`, which is the
regression worth catching.

They also close the ratchet gap the CI run on 6081722 found: this function landed in the
`tenancy-session` guarded surface with its six defensive branches uncovered.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import uuid4

import pytest
from apps.api.db.transition import transition_status
from sqlalchemy.ext.asyncio import AsyncSession

NO_SESSION = cast(AsyncSession, None)


async def _call(**overrides: Any) -> bool:
    kwargs: dict[str, Any] = {
        "table": "campaigns",
        "entity": "Campaign",
        "row_id": uuid4(),
        "to_status": "paused",
        "from_statuses": ("running",),
    }
    kwargs.update(overrides)
    return await transition_status(NO_SESSION, **kwargs)


@pytest.mark.parametrize(
    "table",
    [
        "campaigns; DROP TABLE campaigns",  # the injection this guard exists for
        "public.campaigns",  # a qualified name is not a bare identifier either
        "",
        "2fast",
    ],
)
async def test_a_table_name_that_is_not_a_bare_identifier_is_refused(table):
    with pytest.raises(ValueError, match="table must be a plain identifier"):
        await _call(table=table)


async def test_a_status_column_that_is_not_a_bare_identifier_is_refused():
    # Checked separately from `table` because they are two interpolations, and a guard
    # that covers only the first is the shape this test is here to prevent.
    with pytest.raises(ValueError, match="status_column must be a plain identifier"):
        await _call(status_column="status = 'x' --")


async def test_an_empty_from_statuses_is_refused():
    """Without this, the CAS would carry `WHERE status IN ()` — a syntax error at best,
    and at worst a predicate a future edit turns into 'match any row'."""
    with pytest.raises(ValueError, match="at least one state"):
        await _call(from_statuses=())


async def test_a_caller_param_may_not_collide_with_the_reserved_prefix():
    """The from-state binds are generated as `__t_from0`, `__t_from1`, …, so a caller
    param under the same prefix would silently overwrite one and change WHICH states the
    transition accepts — the failure would look like a lost race, not a bug."""
    with pytest.raises(ValueError, match="may not start with"):
        await _call(extra_set="approved_by = :__t_from0", params={"__t_from0": "sneaky"})


async def test_the_reserved_check_reads_every_supplied_key_not_just_the_first():
    with pytest.raises(ValueError, match="may not start with"):
        await _call(
            extra_set="approved_by = :by",
            params={"by": uuid4(), "__t_to": "approved"},
        )
