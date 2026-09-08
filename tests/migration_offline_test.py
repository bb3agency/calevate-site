"""The offline-mode idioms migrations use, exercised in both modes.

These four functions are the only thing standing between `alembic upgrade head --sql` and
the `AttributeError` it used to die with, and they are exercised in production only by
alembic itself — so the branch that matters (offline) never runs during a deploy and the
branch that runs during a deploy (online) never renders. Both are pinned here against
doubles, because the property is about WHICH call is made, not about what a database says.

`tests/migration_offline_guard_test.py` is the other half: it keeps new migrations using
them. This file keeps them doing what that guard promises.
"""

from __future__ import annotations

from typing import Any

import pytest
import sqlalchemy as sa
from apps.api.db import migration_offline


class _Result:
    rowcount = 7


class _Bind:
    def __init__(self) -> None:
        self.executed: list[sa.TextClause] = []

    def execute(self, statement: sa.TextClause) -> _Result:
        self.executed.append(statement)
        return _Result()


class _Impl:
    def __init__(self) -> None:
        self.output: list[str] = []

    def static_output(self, text: str) -> None:
        self.output.append(text)


class _Context:
    def __init__(self) -> None:
        self.impl = _Impl()


class _Op:
    """Stands in for the `op` proxy: only the three entry points the helper uses."""

    def __init__(self) -> None:
        self.context = _Context()
        self.bind = _Bind()
        self.emitted: list[sa.TextClause] = []

    def get_context(self) -> _Context:
        return self.context

    def get_bind(self) -> _Bind:
        return self.bind

    def execute(self, statement: sa.TextClause) -> None:
        self.emitted.append(statement)


@pytest.fixture
def op_double(monkeypatch: pytest.MonkeyPatch) -> _Op:
    double = _Op()
    monkeypatch.setattr(migration_offline, "op", double)
    return double


def _mode(monkeypatch: pytest.MonkeyPatch, offline: bool) -> None:
    class _Mode:
        @staticmethod
        def is_offline_mode() -> bool:
            return offline

    monkeypatch.setattr(migration_offline, "context", _Mode)


@pytest.mark.parametrize("offline", [True, False])
def test_is_offline_reports_the_mode_alembic_is_in(
    monkeypatch: pytest.MonkeyPatch, offline: bool
) -> None:
    _mode(monkeypatch, offline)
    assert migration_offline.is_offline() is offline


def test_a_note_becomes_sql_comment_lines_when_rendering(
    monkeypatch: pytest.MonkeyPatch, op_double: _Op
) -> None:
    """Every line prefixed — a bare second line would be prose inside a file `psql` reads."""
    _mode(monkeypatch, True)
    migration_offline.emit_note("first\n\nthird")
    assert op_double.context.impl.output == ["-- first\n--\n-- third"]


def test_a_note_is_silent_online_because_stdout_is_the_deploy_log(
    monkeypatch: pytest.MonkeyPatch, op_double: _Op
) -> None:
    _mode(monkeypatch, False)
    migration_offline.emit_note("nothing to say here")
    assert op_double.context.impl.output == []


def test_a_probe_is_skipped_and_recorded_when_there_is_no_connection(
    monkeypatch: pytest.MonkeyPatch, op_double: _Op
) -> None:
    _mode(monkeypatch, True)
    assert migration_offline.probe_skipped_offline("the catalog read did not happen") is True
    assert op_double.context.impl.output == ["-- the catalog read did not happen"]


def test_a_probe_runs_normally_online_and_records_nothing(
    monkeypatch: pytest.MonkeyPatch, op_double: _Op
) -> None:
    _mode(monkeypatch, False)
    assert migration_offline.probe_skipped_offline("would be noise in a deploy log") is False
    assert op_double.context.impl.output == []


def test_a_data_statement_is_emitted_offline_and_only_its_count_is_lost(
    monkeypatch: pytest.MonkeyPatch, op_double: _Op
) -> None:
    """The statement goes into the script; `None` says the count could not be taken.

    This is the asymmetry the whole module exists for: skipping a backfill in a reviewed
    SQL script is silent and wrong, while skipping a row count costs a log line.
    """
    _mode(monkeypatch, True)
    statement = sa.text("UPDATE organizations SET plan_tier = 'prepaid'")

    assert migration_offline.execute_data_statement(statement, note="emitted in full") is None
    assert op_double.emitted == [statement]
    assert op_double.bind.executed == []
    assert op_double.context.impl.output == ["-- emitted in full"]


def test_a_data_statement_runs_on_the_connection_online_and_returns_its_count(
    monkeypatch: pytest.MonkeyPatch, op_double: _Op
) -> None:
    _mode(monkeypatch, False)
    statement = sa.text("UPDATE organizations SET plan_tier = 'prepaid'")

    assert migration_offline.execute_data_statement(statement, note="unused online") == 7
    assert op_double.bind.executed == [statement]
    assert op_double.emitted == []
    assert op_double.context.impl.output == []


def test_the_helper_never_reaches_alembics_offline_only_output_buffer_online(
    monkeypatch: pytest.MonkeyPatch, op_double: _Op
) -> None:
    """`static_output` exists only while rendering; touching it on a deploy would raise.

    Asserted as "the context is never asked for" rather than as "no output appeared",
    because the failure being prevented is an AttributeError on a real migration run, not
    a stray line.
    """

    def _refuse() -> Any:
        raise AssertionError("get_context() reached on the online path")

    monkeypatch.setattr(op_double, "get_context", _refuse)
    _mode(monkeypatch, False)

    migration_offline.emit_note("quiet")
    assert migration_offline.probe_skipped_offline("quiet") is False
    assert migration_offline.execute_data_statement(sa.text("SELECT 1"), note="quiet") == 7
