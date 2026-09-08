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

import ast
import pathlib
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
    """`MigrationContext`'s two members these helpers touch. `as_sql` IS the mode."""

    def __init__(self) -> None:
        self.impl = _Impl()
        self.as_sql = False


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


def _mode(op_double: _Op, offline: bool) -> None:
    op_double.context.as_sql = offline


@pytest.mark.parametrize("offline", [True, False])
def test_is_offline_reports_the_mode_alembic_is_in(op_double: _Op, offline: bool) -> None:
    _mode(op_double, offline)
    assert migration_offline.is_offline() is offline


def test_the_mode_comes_off_the_migration_context_not_the_environment_proxy() -> None:
    """`alembic.context` would raise where migrations are driven by `Operations.context`.

    That is not a corner: `tests/disclosure_toggle_test.py` and
    `tests/migration_reversibility_test.py` run real `upgrade()`/`downgrade()` bodies that
    way, against a live connection and no `env.py`. Asking the ENVIRONMENT proxy there
    raises `NameError: the proxy object has not yet been established` — a green migration
    failing in a test that has nothing to do with offline mode. So the source of the answer
    is pinned in code, not left to the next reader reaching for the obvious call.
    """
    tree = ast.parse(pathlib.Path(migration_offline.__file__).read_text(encoding="utf-8"))
    attributes = [node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)]
    assert "as_sql" in attributes
    assert "is_offline_mode" not in attributes, (
        "apps/api/db/migration_offline reads the mode off alembic's ENVIRONMENT proxy "
        "again. That proxy exists only under `env.py`; every migration driven by "
        "`Operations.context(...)` over a live connection would raise NameError instead of "
        "running. Read `op.get_context().as_sql`."
    )


def test_a_note_becomes_sql_comment_lines_when_rendering(
    monkeypatch: pytest.MonkeyPatch, op_double: _Op
) -> None:
    """Every line prefixed — a bare second line would be prose inside a file `psql` reads."""
    _mode(op_double, True)
    migration_offline.emit_note("first\n\nthird")
    assert op_double.context.impl.output == ["-- first\n--\n-- third"]


def test_a_note_is_silent_online_because_stdout_is_the_deploy_log(
    monkeypatch: pytest.MonkeyPatch, op_double: _Op
) -> None:
    _mode(op_double, False)
    migration_offline.emit_note("nothing to say here")
    assert op_double.context.impl.output == []


def test_a_probe_is_skipped_and_recorded_when_there_is_no_connection(
    monkeypatch: pytest.MonkeyPatch, op_double: _Op
) -> None:
    _mode(op_double, True)
    assert migration_offline.probe_skipped_offline("the catalog read did not happen") is True
    assert op_double.context.impl.output == ["-- the catalog read did not happen"]


def test_a_probe_runs_normally_online_and_records_nothing(
    monkeypatch: pytest.MonkeyPatch, op_double: _Op
) -> None:
    _mode(op_double, False)
    assert migration_offline.probe_skipped_offline("would be noise in a deploy log") is False
    assert op_double.context.impl.output == []


def test_a_data_statement_is_emitted_offline_and_only_its_count_is_lost(
    monkeypatch: pytest.MonkeyPatch, op_double: _Op
) -> None:
    """The statement goes into the script; `None` says the count could not be taken.

    This is the asymmetry the whole module exists for: skipping a backfill in a reviewed
    SQL script is silent and wrong, while skipping a row count costs a log line.
    """
    _mode(op_double, True)
    statement = sa.text("UPDATE organizations SET plan_tier = 'prepaid'")

    assert migration_offline.execute_data_statement(statement, note="emitted in full") is None
    assert op_double.emitted == [statement]
    assert op_double.bind.executed == []
    assert op_double.context.impl.output == ["-- emitted in full"]


def test_a_data_statement_runs_on_the_connection_online_and_returns_its_count(
    monkeypatch: pytest.MonkeyPatch, op_double: _Op
) -> None:
    _mode(op_double, False)
    statement = sa.text("UPDATE organizations SET plan_tier = 'prepaid'")

    assert migration_offline.execute_data_statement(statement, note="unused online") == 7
    assert op_double.bind.executed == [statement]
    assert op_double.emitted == []
    assert op_double.context.impl.output == []


def test_the_helper_never_reaches_alembics_offline_only_output_buffer_online(
    monkeypatch: pytest.MonkeyPatch, op_double: _Op
) -> None:
    """`static_output` is established ONLY while rendering; touching it on a deploy raises.

    Asserted as "that member is never touched" rather than as "no output appeared", because
    the failure being prevented is an exception on a real migration run — the reason
    `a8d3f61c04e7` used `print` in the first place — not a stray line in a log.
    """

    def _refuse(text: str) -> Any:
        raise AssertionError("static_output reached on the online path")

    monkeypatch.setattr(op_double.context.impl, "static_output", _refuse)
    _mode(op_double, False)

    migration_offline.emit_note("quiet")
    assert migration_offline.probe_skipped_offline("quiet") is False
    assert migration_offline.execute_data_statement(sa.text("SELECT 1"), note="quiet") == 7
