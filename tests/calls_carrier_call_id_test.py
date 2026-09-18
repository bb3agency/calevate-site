"""`calls.carrier_call_id` exists, in the database and on the model, and is nullable.

**WHY A COLUMN NOBODY WRITES GETS A TEST.** The value already exists at runtime:
`voice_worker/carrier.py` reads the carrier's own id for the call out of the telephony
handshake and uses it to hang the call up, and then the process ends and it is gone. What
needs it afterwards is the erasure: a DPDP §12 certificate is honest that a sub-processor
keeps its own records and that they are asked for in writing, and a written request to a
telephony vendor has to name the calls — in THEIR id, because that is what their CDR is
keyed on. A request that can only say "this number, these dates" is both slower to answer
and wider than the request should be.

The writer is the voice-worker seam and is another change's to make. That is exactly why
this file exists: a column added for a producer that lands later is the classic half-wired
artefact, and the two ways it goes wrong are a migration that was never applied and an ORM
declaration that drifts from it — after which `alembic revision --autogenerate` proposes
DROPPING the column, and CLAUDE.md's "autogenerate + hand-review" makes an unreviewed
accept a data-loss event (`campaigns.dnc_scrubbed_at` is this repository's worked example
of exactly that).

**NULLABLE IS ASSERTED, not incidental.** Every call already in this table has no such id
and never will, and the value only exists on the carrier-attached leg. NOT NULL would make
the producer's arrival a backfill of identifiers we do not have — which hard rule 11 does
not allow anybody to invent.
"""

from __future__ import annotations

import pytest
from apps.api.crm.models import Call
from apps.api.db.session import untenanted_session
from sqlalchemy import text

pytestmark = pytest.mark.anyio

COLUMN = "carrier_call_id"


async def test_the_column_is_on_the_calls_table_and_is_nullable() -> None:
    """Read off the live database, because the migration is history and the column is the
    fact — the same reason the erasure guards probe `pg_constraint` rather than a file."""
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT data_type, is_nullable FROM information_schema.columns "
                    "WHERE table_name = 'calls' AND column_name = :c"
                ),
                {"c": COLUMN},
            )
        ).first()
    assert row is not None, (
        "calls.carrier_call_id is missing: migration c7f1a9d4e620 has not been applied to "
        "this database"
    )
    assert str(row[0]) == "text"
    assert str(row[1]) == "YES", (
        "the column is NOT NULL, which makes every call that predates the carrier leg "
        "unwritable and its arrival a backfill of identifiers nobody holds"
    )


def test_the_model_declares_it_optional_text() -> None:
    """The ORM half. A live column absent from the model is what autogenerate offers to
    drop; an optional column declared required is what fails the first INSERT."""
    column = Call.__table__.columns[COLUMN]
    assert column.nullable is True
    assert column.type.python_type is str
