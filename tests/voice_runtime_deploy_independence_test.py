"""Hard rule 3's last clause, as a property rather than a promise.

    "Never couple its deploy to `api` changes."

`apps/voice-runtime` is a separate deployable so that a dashboard release cannot touch
live calls. Every reading of that rule so far has been about IMPORTS —
`tests/voice_runtime_import_surface_test.py` pins the module graph, and `main.py` argues
that borrowing `apps/api/core` as a LIBRARY is not coupling. That covers the Python.

**The database is the other half, and nothing was checking it.** A staged deploy is
exactly the situation where the two halves disagree: `alembic upgrade head` runs from the
`api` release, so for the length of a rollout — and for as long as a rollback lasts —
voice-runtime is a process built against one schema talking to another. Two directions,
and only one of them is the dangerous one:

* **Database NEWER than this service.** The forensic INSERT enumerates its columns, so a
  migration that adds a NOT NULL column with no default to `webhook_deliveries` breaks
  every delivery on a service nobody redeployed. The receiver would 500, and the vendor
  delivers at most once (D-31), so the loss is real until the 10-minute poller. §1 is the
  guard: it reads the live schema and the SQL the receiver actually issues, and fails in
  the `api` author's own test run rather than in production at 2am.
* **Database OLDER than this service.** Only dangerous if this service reads something new
  — and §2 pins that its entire schema surface is two infra tables, both of which predate
  everything else it touches, with no SELECT anywhere on the path.

Both sections measure the RUNNING service rather than reading its source: the statements
are captured off the SQLAlchemy engine while a real delivery goes through, so a claim that
moves into a helper, an ORM call or another module is still counted.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from apps.api.db.session import get_engine, untenanted_session
from httpx import ASGITransport, AsyncClient
from main import app as voice_app
from sqlalchemy import event, text

ENGINE_EGRESS_IP = "198.51.100.7"
EDGE_PROXY_IP = "127.0.0.1"
HOOK = "/hooks/v1/engine/bolna"
TOOL = "/tools/v1/bolna/opt-out"
HEADERS = {"CF-Connecting-IP": ENGINE_EGRESS_IP}

#: The whole schema surface of this deployable. Both are infra tables (no `tenant_id`, no
#: RLS policy, no tenant resolved here — see the receiver's docstring item 4), and both
#: exist for the reliability triad rather than for any product feature, which is what makes
#: them the two least likely rows in the repo to move under a dashboard release.
SCHEMA_SURFACE: frozenset[str] = frozenset({"webhook_deliveries", "webhook_inbox_events"})


@pytest.fixture(autouse=True)
def _allowlist(source_ip_allowlist: Callable[..., None]) -> None:
    source_ip_allowlist(ENGINE_EGRESS_IP)


def _client(peer_ip: str = EDGE_PROXY_IP) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=voice_app, client=(peer_ip, 44444), raise_app_exceptions=False),
        base_url="http://runtime",
    )


async def _statements_of_a_full_drive() -> list[str]:
    """Every SQL statement this service issues, over every branch it has.

    Captured on the ENGINE rather than around a call, so it counts what psycopg actually
    executed — including anything a future dependency slips onto the path.
    """
    captured: list[str] = []
    engine = get_engine().sync_engine

    def _on_execute(_conn: Any, _cursor: Any, statement: str, *_rest: Any) -> None:
        captured.append(" ".join(statement.split()))

    tag = uuid.uuid4().hex[:12]
    body = {"execution_id": f"exec_{tag}", "status": f"completed-{tag}"}
    event.listen(engine, "before_cursor_execute", _on_execute)
    try:
        async with _client() as http:
            await http.post(HOOK, json=body)  # 401
            await http.post(HOOK, content=b"x" * 2_000_000, headers=HEADERS)  # 413
            await http.post(HOOK, content=b"{not json", headers=HEADERS)  # unreadable
            await http.post(HOOK, json={"status": "done"}, headers=HEADERS)  # unkeyable
            await http.post(HOOK, json=body, headers=HEADERS)  # accepted
            await http.post(HOOK, json=body, headers=HEADERS)  # duplicate
            await http.post(TOOL, json={"execution_id": f"exec_{tag}"}, headers=HEADERS)
    finally:
        event.remove(engine, "before_cursor_execute", _on_execute)
    return captured


# --- 1. the database may run AHEAD of this service ----------------------------


async def _required_columns(table: str) -> set[str]:
    """Columns an INSERT into `table` must name: NOT NULL and no default.

    Read from the live catalogue rather than from a model, because the model registry is
    the one import this service is forbidden to hold (`apps.api.db.registry`) — and because
    the catalogue is what the running database will actually enforce.
    """
    async with untenanted_session() as session:
        rows = await session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = :t "
                "AND is_nullable = 'NO' AND column_default IS NULL "
                "AND is_generated = 'NEVER' AND identity_generation IS NULL"
            ),
            {"t": table},
        )
        return {str(row[0]) for row in rows}


def _inserted_columns(statements: list[str]) -> dict[str, set[str]]:
    """`{table: {column, ...}}` for every INSERT in `statements`."""
    found: dict[str, set[str]] = {}
    for statement in statements:
        match = re.match(r"INSERT INTO (\w+) \(([^)]*)\)", statement, re.IGNORECASE)
        if match is None:
            continue
        table, columns = match.group(1), match.group(2)
        found.setdefault(table, set()).update(part.strip() for part in columns.split(","))
    return found


async def test_the_rows_this_service_writes_name_every_column_the_schema_requires() -> None:
    """The staged-deploy break, caught in the `api` author's own test run.

    `webhook_deliveries` is written from `apps/voice-runtime` with a literal column list
    and from nowhere else on this path. A migration in the `api` release that adds a NOT
    NULL column with no default to it makes every one of those INSERTs fail — on a service
    that was not rebuilt, was not redeployed, and has no idea. Because the vendor delivers
    at most once and never retries (D-31), the failures are lost calls until the 10-minute
    reconciliation poller notices, and the alert an operator sees says nothing about a
    migration.

    Two-step deprecation (hard rule 8) is the same story in reverse: a column this service
    still writes must not be dropped in the release that stops reading it. That direction
    fails here too — the INSERT names a column the catalogue no longer has, the statement
    errors, and this test says which column and which table.

    Asserted as a SUBSET, not an equality: writing more columns than the schema strictly
    requires is exactly what `signature_valid` and the forensic timestamps are for.
    """
    statements = await _statements_of_a_full_drive()
    inserted = _inserted_columns(statements)
    assert set(inserted) == SCHEMA_SURFACE, (
        f"this service now inserts into {sorted(inserted)}; SCHEMA_SURFACE says "
        f"{sorted(SCHEMA_SURFACE)}"
    )

    for table, supplied in sorted(inserted.items()):
        required = await _required_columns(table)
        missing = required - supplied
        assert not missing, (
            f"`{table}` requires {sorted(missing)} and voice-runtime's INSERT does not "
            f"supply {'it' if len(missing) == 1 else 'them'}. A NOT NULL column with no "
            "default is a deploy coupling: the migration ships with `api` and breaks a "
            "service nobody rebuilt. Either give the column a default in the same "
            "migration, or update this service's INSERT in the same release — hard rule "
            "3's last clause, and hard rule 8's two-step deprecation."
        )


# --- 2. the database may also run BEHIND it -----------------------------------


async def test_the_whole_schema_surface_of_this_deployable_is_two_infra_tables() -> None:
    """What an OLDER database can and cannot break.

    Every branch this service has is driven above, and the statements it produced must name
    nothing outside `SCHEMA_SURFACE`. That is the property that makes a rollback safe: a
    database at an earlier head is missing tables and columns that `api` grew LATER, and
    none of them is reachable from here — the receiver resolves no tenant, prices nothing
    and reads no configuration row (its settings come from an in-memory snapshot).

    It also pins the negative that makes the positive meaningful: **no SELECT and no
    `alembic_version`**. A service that checked the migration head would have made itself
    fail on precisely the window this test exists to keep working, and a service that reads
    a product table would inherit that table's release schedule.
    """
    statements = await _statements_of_a_full_drive()
    assert statements, "the drive produced no SQL at all — this measured nothing"

    joined = " ".join(statements).lower()
    named = set(re.findall(r"(?:into|from|update)\s+(\w+)", joined))
    assert named <= SCHEMA_SURFACE, (
        f"voice-runtime touched {sorted(named - SCHEMA_SURFACE)}. Every table beyond the "
        "two infra ones is a schedule this deployable does not control."
    )
    assert "alembic_version" not in joined, (
        "a service that verifies the migration head cannot survive a staged deploy, which "
        "is the exact window it would refuse to serve in"
    )
    assert " select " not in f" {joined} ", (
        "the ack path reads nothing; a read is a column whose shape `api` owns"
    )
