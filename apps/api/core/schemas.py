"""The base model every api request and response model extends (BACKEND-PATTERNS §3)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Final

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict

#: The largest `offset` a list route accepts: Postgres types `OFFSET` as `bigint`, so a
#: larger number is refused by the database as `NumericValueOutOfRange`, a 500, rather
#: than by us as a 422 naming the parameter. Every `offset` query parameter carries
#: `le=MAX_OFFSET`.
MAX_OFFSET: Final = 2**63 - 1


def _has_a_utc_instant(value: datetime) -> datetime:
    try:
        value.astimezone(UTC)
    except OverflowError:
        raise ValueError("that date is out of range") from None
    return value


#: A request time: aware, and with a UTC twin. `AwareDatetime` alone admits
#: `9999-12-31T23:59:59-12:00` and `0001-01-01T00:00:00+14:00`, whose UTC instants fall
#: outside what `datetime` holds: the first raises `OverflowError` in any `astimezone`
#: (a 500), and the second is stored by Postgres as a year-1-BC `timestamptz` that psycopg
#: cannot read back, so every later read of that row is a 500 too.
#: The same check for a `datetime` field whose own validator refuses a naive value with
#: its own wording: `Annotated[datetime, HAS_UTC_INSTANT]`.
HAS_UTC_INSTANT: Final = AfterValidator(_has_a_utc_instant)
Instant = Annotated[AwareDatetime, HAS_UTC_INSTANT]


class Strict(BaseModel):
    """`extra="forbid"`: a response model IS the output whitelist, so an undeclared field
    cannot be serialized, and a request with a misspelt field is a refusal rather than a
    silently ignored intention. `tests/route_models_forbid_extra_test.py` holds every route
    model to it.

    It carries no other config. A module that needs more (`frozen`, aliases) subclasses
    this and adds only that, so the forbid stays in one place.
    """

    model_config = ConfigDict(extra="forbid")
