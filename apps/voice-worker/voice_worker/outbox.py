"""The transactional outbox, written from the container that cannot import the one that
owns it.

**THIS IS NOT A SECOND OUTBOX AND MUST NEVER BECOME ONE.** There is exactly one outbox in
this repository — `outbox_messages`, written by `apps/api/reliability/service.py` and
drained by `apps/workers/dispatcher.py::dispatch_outbox`. This module writes a row into
THAT table, with THAT table's columns, under THAT function's idempotency contract, and
adds no queue, no dispatcher and no second status vocabulary. Nothing here reads a row,
claims one, retries one or marks one published: the existing dispatcher does all of that
and is the only thing that may (hard rule 4 — `outbox_messages` is not append-only, but
its UPDATE path has one author and this is not it).

**WHY IT IS RESTATED RATHER THAN IMPORTED.** `apps.api.reliability.service` imports
`apps.api.core.settings`, `apps.api.core.alerting` and `apps.api.db.result`, i.e. the
monolith — which is precisely what `pyproject.toml`, `db.py` and `storage.py` each refuse
to carry into a latency-critical voice container. `sink.py`'s module docstring already
took this trade for `calls`, `transcript_turns` and `usage_events`: the statements are the
SAME shape against the same columns with the same idempotency key, so the two writers
converge on one row rather than producing two readings of it. This is the fourth table on
that list and the reasoning is unchanged.

⚠ **THE FUNCTION'S NAME IS `enqueue_outbox_once` DELIBERATELY, AND RENAMING IT BREAKS A
GUARDRAIL.** `scripts/check_job_wiring.py` finds every place a job name reaches the queue
by scanning `apps/**` for calls to four SEAM NAMES — `enqueue`, `job_id_for`,
`enqueue_outbox`, `enqueue_outbox_once` — resolving the `job` argument through
module-level string constants in the same file. Its one standing exemption
(`DYNAMIC_ENQUEUE_SITES`, `apps/workers/dispatcher.py::message.job`) is granted on the
stated ground that *"every writer of that column goes through `enqueue_outbox`/
`enqueue_outbox_once`, which this scan reads, so the name is covered at the producer where
it is actually chosen."* A writer of `outbox_messages.job` under any other name would
falsify that sentence and silently open the hole the exemption claims is closed — a job
enqueued by a name no worker answers to, which arq accepts, logs once at WARNING and drops
(shape 3 in that file's docstring). So the seam keeps the seam's name, `job` is
keyword-only as it is there, and the name is a module constant this scan can resolve.
"""

from __future__ import annotations

import json
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from uuid_utils.compat import uuid7

#: `apps/api/reliability/service.py::enqueue_outbox_once`'s statement, to the column.
#:
#: **THE CONFLICT TARGET IS SPELLED AS THE PARTIAL INDEX'S OWN PREDICATE** and that is not
#: style: `dedupe_key` is UNIQUE only `WHERE dedupe_key IS NOT NULL` (migration
#: `e83b5d1a4c07`), and naming the column alone does not match a partial index — Postgres
#: answers "no unique or exclusion constraint matching the ON CONFLICT specification"
#: (postgresql.org/docs/16/sql-insert.html#SQL-ON-CONFLICT).
#:
#: `queue` is not named: the column carries one constant, the database defaults it, and
#: `apps/api/reliability/service.OUTBOX_FLEET` is the one home for that value until the
#: column is dropped (migration `b7e4c1a90d38`, step 2).
_INSERT_OUTBOX_SQL: Final = """
INSERT INTO outbox_messages (id, job, payload, dedupe_key, status, attempt_count,
                             created_at, updated_at)
VALUES (:id, :job, CAST(:payload AS jsonb), :dedupe_key, 'pending', 0, now(), now())
ON CONFLICT (dedupe_key) WHERE dedupe_key IS NOT NULL DO NOTHING
RETURNING id
"""


async def enqueue_outbox_once(
    connection: AsyncConnection,
    *,
    job: str,
    payload: dict[str, Any],
    dedupe_key: str,
) -> UUID | None:
    """Promise one side effect, at most once ever. Returns the new id, or `None` if it was
    already on the books.

    **IN THE CALLER'S TRANSACTION, WHICH IS THE ENTIRE POINT.** Nothing here commits. The
    row and the domain write it describes share one fate, so "the call settled but the
    pipeline was never triggered" cannot happen and neither can its mirror image
    (BACKEND-PATTERNS §4).

    `AsyncConnection` rather than the monolith's `AsyncSession`, for `db.py`'s reason:
    this container owns no ORM models and every statement it issues is `text()`.

    **`ON CONFLICT DO NOTHING` AND NOT A READ-THEN-WRITE**, which is the same discipline
    the `calls` upsert next door converged on: the database decides, so two settlements of
    one call racing in two containers cannot both win, with no lock to remember to take.
    """
    message_id = uuid7()
    row = (
        await connection.execute(
            text(_INSERT_OUTBOX_SQL),
            {
                "id": message_id,
                "job": job,
                "payload": json.dumps(payload),
                "dedupe_key": dedupe_key,
            },
        )
    ).first()
    return message_id if row is not None else None


__all__ = ["enqueue_outbox_once"]
