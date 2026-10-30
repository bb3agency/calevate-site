"""Calevate's filing of the calling numbers clients authorise (D-941 amended 30 Oct 2026).

The client confirms and authorises; we file and record it. Pinned here: only a current
authorisation gives us numbers to file, the record is append-only, audited, tenant-isolated
and admin-only, the client's calls never wait for our filing, the health board raises the
alarm from seven days before the enforcement date, and the migration goes down and up.
"""

from __future__ import annotations

import importlib.util
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from types import ModuleType

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from apps.api.admin.health import _filing_signal
from apps.api.compliance import a2p_filing
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.session import admin_session, tenant_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from tests.a2p_declaration_test import (
    BEFORE,
    ENFORCED,
    _agent_numbers,
    _declare,
    _gate,
    _org_headers,
    _today,
    _version_1_row,
)
from tests.outbound_consent_policy_test import _tenant

pytestmark = pytest.mark.rls

BOARD = "/v1/admin/calling-number-filings"
#: 11:00 IST, so the calling-hours rule is never what refuses.
_PINNED_IST = datetime(2026, 8, 11, 11, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: _PINNED_IST)


def _mark(tenant_id: uuid.UUID) -> str:
    return f"/v1/admin/tenants/{tenant_id}/calling-number-filings"


async def _operator() -> tuple[uuid.UUID, dict[str, str]]:
    admin_id = uuid.uuid4()
    async with admin_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops Filing', 'operator', now(), now())"
            ),
            {"id": admin_id},
        )
    return admin_id, {"Authorization": f"Bearer dev:admin:{admin_id}"}


async def _authorised(name: str) -> tuple[uuid.UUID, uuid.UUID, list[str]]:
    tenant_id, agent_id = await _tenant(name)
    numbers = await _agent_numbers(tenant_id, agent_id)
    await _declare(tenant_id, numbers)
    return tenant_id, agent_id, numbers


async def _file(
    tenant_id: uuid.UUID, filed: list[str], admin_id: uuid.UUID, **over: object
) -> uuid.UUID:
    kwargs: dict[str, object] = {
        "numbers": filed,
        "filed_on": date(2026, 11, 1),
        "filing_reference": "OAP-ACK-1",
        "recorded_by_admin_id": admin_id,
        **over,
    }
    async with tenant_session(tenant_id) as session:
        row_id, _filed = await a2p_filing.record_filing(
            session,
            tenant_id=tenant_id,
            **kwargs,  # type: ignore[arg-type]
        )
    return row_id


async def _status(tenant_id: uuid.UUID) -> a2p_filing.FilingStatus:
    async with tenant_session(tenant_id) as session:
        return await a2p_filing.filing_status(session, tenant_id=tenant_id)


# --- what there is to file -----------------------------------------------------------------


async def test_only_a_current_authorisation_gives_numbers_to_file() -> None:
    tenant_id, agent_id = await _tenant("a2p-file-v1")
    numbers = await _agent_numbers(tenant_id, agent_id)
    await _version_1_row(tenant_id, numbers)
    assert (await _status(tenant_id)).numbers == ()

    await _declare(tenant_id, numbers)
    status = await _status(tenant_id)
    assert status.unfiled == tuple(numbers)

    await _declare(tenant_id, [], withdraw=True)
    assert (await _status(tenant_id)).numbers == ()


async def test_a_filing_is_refused_for_a_number_not_authorised_or_badly_recorded() -> None:
    tenant_id, _agent, numbers = await _authorised("a2p-file-refused")
    admin_id, _headers = await _operator()
    cases = [
        ({"numbers": ["+919848022338"]}, "a2p_filing_number_not_authorised"),
        ({"numbers": [" "]}, "a2p_filing_number_not_authorised"),
        ({"numbers": []}, "a2p_filing_numbers_missing"),
        ({"filing_reference": "  "}, "a2p_filing_reference_invalid"),
        ({"filing_reference": "x" * 201}, "a2p_filing_reference_invalid"),
        ({"filed_on": date(2026, 12, 1)}, "a2p_filing_date_in_future"),
    ]
    for over, code in cases:
        with pytest.raises(ProblemError) as refused:
            await _file(tenant_id, numbers, admin_id, **over)
        assert refused.value.code == code, over


async def test_the_latest_filing_of_a_number_is_the_one_shown() -> None:
    tenant_id, _agent, numbers = await _authorised("a2p-file-latest")
    admin_id, _headers = await _operator()
    await _file(tenant_id, numbers, admin_id, filing_reference="WRONG-1")
    await _file(tenant_id, numbers, admin_id, filing_reference="RIGHT-2")
    status = await _status(tenant_id)
    assert status.unfiled == ()
    assert {n.filing_reference for n in status.numbers} == {"RIGHT-2"}


# --- the record ----------------------------------------------------------------------------


async def test_the_filing_is_append_only_and_tenant_isolated() -> None:
    tenant_id, _agent, numbers = await _authorised("a2p-file-append")
    other_id, _other = await _tenant("a2p-file-other")
    admin_id, _headers = await _operator()
    row_id = await _file(tenant_id, numbers, admin_id)
    with pytest.raises(DBAPIError):
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE a2p_number_filings SET filing_reference = 'x' WHERE id = :i"),
                {"i": row_id},
            )
    with pytest.raises(DBAPIError):
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("DELETE FROM a2p_number_filings WHERE id = :i"), {"i": row_id}
            )
    async with tenant_session(other_id) as session:
        seen = (await session.execute(text("SELECT count(*) FROM a2p_number_filings"))).scalar_one()
    assert seen == 0


# --- the client's calls never wait for us --------------------------------------------------


async def test_the_gate_does_not_wait_for_our_filing(monkeypatch: pytest.MonkeyPatch) -> None:
    _today(monkeypatch, ENFORCED)
    tenant_id, agent_id, _numbers = await _authorised("a2p-file-gate")
    assert (await _status(tenant_id)).unfiled
    assert (await _gate(tenant_id, agent_id)).allowed is True


# --- the alarm -----------------------------------------------------------------------------


async def test_the_board_raises_unfiled_numbers_from_seven_days_before_the_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _agent, numbers = await _authorised("a2p-file-alarm")

    _today(monkeypatch, date(2026, 11, 9))
    async with tenant_session(tenant_id) as session:
        assert await _filing_signal(session, tenant_id=tenant_id) is None

    _today(monkeypatch, date(2026, 11, 10))
    async with tenant_session(tenant_id) as session:
        warned = await _filing_signal(session, tenant_id=tenant_id)
    assert warned is not None
    assert (warned.rule, warned.severity, warned.waiting_on) == (
        "calling_numbers_unfiled",
        "warn",
        "calevate",
    )
    assert warned.count == len(numbers)

    _today(monkeypatch, ENFORCED)
    async with tenant_session(tenant_id) as session:
        stopped = await _filing_signal(session, tenant_id=tenant_id)
    assert stopped is not None and stopped.severity == "stop"

    admin_id, _headers = await _operator()
    await _file(tenant_id, numbers, admin_id)
    async with tenant_session(tenant_id) as session:
        assert await _filing_signal(session, tenant_id=tenant_id) is None


# --- the routes ----------------------------------------------------------------------------


async def test_an_operator_sees_the_board_marks_filed_and_it_is_audited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _today(monkeypatch, BEFORE)
    tenant_id, _agent, numbers = await _authorised("a2p-file-route")
    _admin_id, headers = await _operator()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        board = (await http.get(BOARD, headers=headers)).json()
        assert board["enforced_from"] == "2026-11-17"
        assert board["alarm_from"] == "2026-11-10"
        assert board["alarm"] is True
        row = next(c for c in board["clients"] if c["tenant_id"] == str(tenant_id))
        assert row["unfiled"] == len(numbers)
        assert [n["number"] for n in row["numbers"]] == numbers
        assert all(n["filed_on"] is None for n in row["numbers"])

        marked = await http.post(
            _mark(tenant_id),
            headers=headers,
            json={"numbers": numbers, "filed_on": "2026-11-12", "filing_reference": "ACK-77"},
        )
        assert marked.status_code == 201, marked.text
        body = marked.json()
    assert body["unfiled"] == 0
    assert {n["filing_reference"] for n in body["numbers"]} == {"ACK-77"}
    async with tenant_session(tenant_id) as session:
        audit = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE action = 'a2p_filing.recorded' "
                    "AND tenant_id = :t AND object_type = 'a2p_number_filing'"
                ),
                {"t": tenant_id},
            )
        ).scalar_one()
    assert audit == 1


async def test_a_client_session_cannot_reach_the_board_or_mark_filed() -> None:
    tenant_id, _agent, numbers = await _authorised("a2p-file-client")
    headers = await _org_headers(tenant_id)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        board = await http.get(BOARD, headers=headers)
        marked = await http.post(
            _mark(tenant_id),
            headers=headers,
            json={"numbers": numbers, "filed_on": "2026-11-01", "filing_reference": "X"},
        )
    assert board.status_code in {401, 403}, board.text
    assert marked.status_code in {401, 403}, marked.text
    assert (await _status(tenant_id)).unfiled == tuple(numbers)


# --- the migration -------------------------------------------------------------------------

STEM = "c4e1a9b7d305_calling_number_authorisation_and_filings"
_ANNOUNCEMENT = text(
    "SELECT message, link_label FROM platform_announcements "
    "WHERE id = '019a33c0-d941-7000-8000-0000000d0941'"
)


def _revision() -> ModuleType:
    path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / f"{STEM}.py"
    spec = importlib.util.spec_from_file_location(f"_revision_{STEM}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_migration_goes_down_and_up() -> None:
    """In one transaction that is rolled back. Rows other tests filed are set aside inside
    it, because the downgrade rightly refuses to drop recorded filings."""
    revision = _revision()
    url = (get_settings().alembic_database_url or get_settings().database_url).replace(
        "+asyncpg", "+psycopg"
    )
    sync = create_engine(url)
    try:
        with sync.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(
                    text(
                        "ALTER TABLE a2p_number_filings "
                        "DISABLE TRIGGER a2p_number_filings_forbid_truncate"
                    )
                )
                connection.execute(text("TRUNCATE a2p_number_filings"))
                with Operations.context(MigrationContext.configure(connection)):
                    revision.downgrade()
                    message, label = connection.execute(_ANNOUNCEMENT).one()
                    assert label == "Declare numbers"
                    assert message.startswith("From 17 Nov, automated calls may only come")
                    assert (
                        connection.execute(
                            text("SELECT to_regclass('a2p_number_filings')")
                        ).scalar_one()
                        is None
                    )
                    revision.upgrade()
                    message, label = connection.execute(_ANNOUNCEMENT).one()
                    assert label == "Confirm numbers"
                    assert message == revision.NEW_MESSAGE
                    forced = connection.execute(
                        text(
                            "SELECT relforcerowsecurity FROM pg_class "
                            "WHERE relname = 'a2p_number_filings'"
                        )
                    ).scalar_one()
                    assert forced is True
            finally:
                transaction.rollback()
    finally:
        sync.dispose()
