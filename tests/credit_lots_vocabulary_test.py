"""One spelling of a lot's vocabulary in three places (D-547).

`billing/lots.LotSource` types it for mypy, `billing/models.LOT_SOURCES` builds the ORM
CHECK, and migration `c9f3a71e58d2` froze its own copy into the database. Three copies is
the shape D-103/D-105 exist for, and they are kept honest by comparing them rather than by
remembering — the migration's copy is deliberately frozen (a migration is a snapshot of the
schema on the day it ran), so what must hold is that the LIVE constraint and the LIVE
constants still agree.
"""

from __future__ import annotations

from typing import get_args

import pytest
from apps.api.billing.lots import LotSource
from apps.api.billing.models import LOT_SOURCES
from apps.api.db.session import tenant_session
from sqlalchemy import text
from tests.credit_lots_helpers import make_tenant

pytestmark = [pytest.mark.rls]


def test_the_typed_vocabulary_and_the_orm_constant_agree() -> None:
    assert set(get_args(LotSource)) == set(LOT_SOURCES)


async def test_the_database_check_admits_exactly_those_sources() -> None:
    """Read from `pg_constraint`, so it asserts what is INSTALLED. A source the type
    allows and the CHECK refuses is an insert that fails at runtime on a money path."""
    async with tenant_session(await make_tenant()) as session:
        definition = (
            await session.execute(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conname = 'ck_credit_lots_source_enum'"
                )
            )
        ).scalar_one()

    for source in LOT_SOURCES:
        assert f"'{source}'" in definition
    # And NOTHING else: the count pins the arm that would otherwise pass by adding a
    # sixth value nobody typed into the constant.
    assert definition.count("::text") == len(LOT_SOURCES)


def test_the_voice_tiers_are_the_two_the_card_prices() -> None:
    """`VoiceTier` is spelled in `lots.py` rather than imported from `agents/voices.py`,
    which Phase C owns — pricing a minute must not depend on the voice catalogue loading.
    This is the pin that the two do not drift apart while they are apart."""
    from apps.api.billing.lots import VoiceTier

    assert get_args(VoiceTier) == ("sarvam", "cartesia")
