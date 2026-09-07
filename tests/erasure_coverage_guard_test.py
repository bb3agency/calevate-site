"""Negative controls for `scripts/check_erasure_coverage.py`.

A guardrail that has stopped seeing violations is worse than none, and this one's whole
claim is that it would have caught `handoff_attempts` and `outbox_messages` — two tables
that held a caller's words, were reached by no erasure arm, and were found by a person
months apart. So the controls here are not "does it run": they are the doctored states it
must FAIL on, plus the states it must NOT fail on, plus the blind spot that would make
every other answer worthless.

The evaluation is pure (`evaluate(state, reach)`), so all but two of these need no
database: the synthetic `SchemaState` is the whole input. The two that read the live tree
are the ones whose subject IS the tree — the erasure walk and the register's honesty
against the real schema.
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest
from scripts.check_erasure_coverage import (
    COVERAGE_ANCHORS,
    ERASURE_EXEMPT,
    ERASURE_SOURCES,
    MIN_EXEMPTION_REASON,
    ErasureReach,
    SchemaState,
    _executable_nodes,
    _literal_of,
    _tables_in,
    erasure_reach,
    evaluate,
    read_state,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _reach(*tables: str) -> ErasureReach:
    return ErasureReach(tables=frozenset(tables), visited=frozenset({"execute_deletion_request"}))


class TestTheRuleItself:
    def test_a_table_holding_a_subject_handle_with_no_arm_fails(self) -> None:
        """THE FINDING THIS GUARD EXISTS FOR, in miniature: a table lands carrying a
        caller's number and no erasure statement names it."""
        state = SchemaState(
            subject_handle_tables=frozenset({"whispered_numbers"}),
            all_tables=frozenset({"whispered_numbers"}),
        )
        failures = evaluate(state, _reach(), exemptions={})
        assert len(failures) == 1
        assert "whispered_numbers" in failures[0]
        assert "NO erasure arm" in failures[0]

    def test_a_child_of_calls_with_no_arm_fails(self) -> None:
        """`handoff_attempts`' shape: no number of its own, a foreign key to `calls`, and
        prose about the conversation. The `ON DELETE CASCADE` never fires because an
        erasure EMPTIES a call rather than deleting it."""
        state = SchemaState(
            subject_linked_tables=frozenset({"handover_notes"}),
            all_tables=frozenset({"handover_notes"}),
        )
        failures = evaluate(state, _reach(), exemptions={})
        assert "link to a call/lead" in failures[0]

    def test_a_table_holding_an_inline_payload_with_no_arm_fails(self) -> None:
        """`outbox_messages`' shape: no tenant_id, no call, a jsonb body with a lead's
        name and number in it."""
        state = SchemaState(
            prose_tables=frozenset({"queued_bodies"}), all_tables=frozenset({"queued_bodies"})
        )
        failures = evaluate(state, _reach(), exemptions={})
        assert "free-text or jsonb payload" in failures[0]

    def test_an_arm_that_names_the_table_passes(self) -> None:
        state = SchemaState(
            subject_handle_tables=frozenset({"whispered_numbers"}),
            all_tables=frozenset({"whispered_numbers"}),
        )
        assert evaluate(state, _reach("whispered_numbers"), exemptions={}) == []

    def test_an_exemption_with_a_reason_passes(self) -> None:
        state = SchemaState(
            subject_handle_tables=frozenset({"staff_mobiles"}),
            all_tables=frozenset({"staff_mobiles"}),
        )
        reason = "The client's own staff, a different data principal on a different basis."
        assert len(reason) >= MIN_EXEMPTION_REASON
        assert evaluate(state, _reach(), exemptions={"staff_mobiles": reason}) == []


class TestTheRegisterStaysHonest:
    """The other direction. `check_rls_coverage`'s rule 4, one obligation along: a dead
    exemption reads as a considered decision and hides the next real gap behind a name
    nobody rechecks."""

    def test_an_exemption_for_a_table_that_no_longer_exists_fails(self) -> None:
        failures = evaluate(
            SchemaState(all_tables=frozenset({"calls"})),
            _reach("calls"),
            exemptions={"deleted_last_year": "A table that was dropped three migrations ago."},
        )
        assert any("STALE erasure exemption" in failure for failure in failures)

    def test_an_exemption_for_a_table_nothing_would_have_asked_about_fails(self) -> None:
        failures = evaluate(
            SchemaState(all_tables=frozenset({"alembic_version"})),
            _reach(),
            exemptions={
                "alembic_version": "Migration bookkeeping, which holds nobody's personal data."
            },
        )
        assert any("carries no subject-linked column" in failure for failure in failures)

    def test_a_table_both_exempt_and_erased_fails(self) -> None:
        """One of the two is wrong and a reviewer cannot tell which, so the guard refuses
        to let the ambiguity stand."""
        state = SchemaState(
            subject_handle_tables=frozenset({"calls"}), all_tables=frozenset({"calls"})
        )
        failures = evaluate(
            state,
            _reach("calls"),
            exemptions={"calls": "Something a maintainer believed while the arm existed."},
        )
        assert any("also reached by an erasure arm" in failure for failure in failures)

    def test_a_thin_reason_fails(self) -> None:
        state = SchemaState(
            subject_handle_tables=frozenset({"staff_mobiles"}),
            all_tables=frozenset({"staff_mobiles"}),
        )
        failures = evaluate(state, _reach(), exemptions={"staff_mobiles": "n/a"})
        assert any("too thin to review" in failure for failure in failures)


class TestTheWalkReadsCodeAndNotProse:
    """The half that decides what "covered" means. If it read prose, every table
    `retention.py`'s docstrings name would be covered and the guard would manufacture its
    own green — which is the one failure mode a guardrail must not have."""

    def test_a_docstring_that_quotes_sql_is_not_coverage(self) -> None:
        module = ast.parse(
            textwrap.dedent(
                '''
                def erase() -> None:
                    """We do not DELETE FROM handoff_attempts here; see the other arm."""
                    run("DELETE FROM calls WHERE id = ANY(:ids)")
                '''
            )
        )
        function = module.body[0]
        assert isinstance(function, ast.FunctionDef)
        tables: set[str] = set()
        for node in _executable_nodes(function):
            literal = _literal_of(node)
            if literal is not None:
                tables |= _tables_in(literal)
        assert tables == {"calls"}

    def test_an_f_string_statement_is_read(self) -> None:
        """F-STRINGS ARE HALF THE SQL IN THIS TREE, and missing them is not theoretical:
        the guard's first run reported `caller_chunks` as an uncovered gap because
        `_SCRUB_CHUNKS_SQL` is an f-string and an f-string is an `ast.JoinedStr`."""
        node = ast.parse('f"UPDATE caller_chunks SET tsv = {marker} WHERE id = ANY(:ids)"')
        expression = node.body[0]
        assert isinstance(expression, ast.Expr)
        literal = _literal_of(expression.value)
        assert literal is not None
        assert _tables_in(literal) == {"caller_chunks"}

    def test_an_interpolation_cannot_fuse_into_a_table_name(self) -> None:
        """`FROM {table}` must yield nothing, not the identifier that follows it."""
        node = ast.parse('f"SELECT id FROM {table} lead_events WHERE x"')
        expression = node.body[0]
        assert isinstance(expression, ast.Expr)
        literal = _literal_of(expression.value)
        assert literal is not None
        assert "from lead_events" not in literal.lower()


class TestItCanStillSeeItsOwnSubject:
    """`check_wiring`'s `blind_spots()`. Three of the questions above compare a live schema
    against a set extracted from source, and an extraction that silently stopped working
    would report every table as uncovered — which reads as noise and gets exempted away."""

    def test_the_live_walk_finds_every_anchor(self) -> None:
        reach = erasure_reach()
        assert reach.blind_spots == []
        assert reach.tables >= COVERAGE_ANCHORS, sorted(COVERAGE_ANCHORS - reach.tables)

    def test_a_moved_source_is_reported_rather_than_passed_over(self) -> None:
        reach = erasure_reach(sources=(REPO_ROOT / "apps" / "workers" / "gone.py",))
        assert reach.blind_spots
        assert not reach.tables >= COVERAGE_ANCHORS

    def test_every_erasure_source_exists(self) -> None:
        """The list is enumerated because "which code is an erasure" is a judgement; a
        name in it that has moved is exactly the state the blind-spot arm reports."""
        missing = [path for path in ERASURE_SOURCES if not path.exists()]
        assert missing == []


@pytest.mark.parametrize("table", sorted(ERASURE_EXEMPT))
def test_every_registered_exemption_argues_its_case(table: str) -> None:
    """An exemption is an argument, not a checkbox. Parametrized so a thin entry names
    itself rather than hiding in a list comprehension's failure message."""
    reason = ERASURE_EXEMPT[table].strip().lstrip("\u26a0 ")
    assert len(reason) >= MIN_EXEMPTION_REASON
    assert reason[0].isupper() and reason.endswith(".")


def test_the_live_arm_sees_a_new_un_erased_table() -> None:
    """THE WHOLE CLAIM, exercised against the REAL schema rather than a synthetic state.

    A table lands carrying a caller's number, a link to their call and a free-text note,
    and no erasure arm names it — the shape `handoff_attempts` and `outbox_messages` both
    had. It is created inside a transaction and rolled back, so a database four other
    lanes are using never sees it; the alternative (a migration for a fixture table) would
    leave the doctored table in everyone's `check_rls_coverage` run too.
    """
    import os

    from sqlalchemy import create_engine, text

    url = os.environ.get("ALEMBIC_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("no database URL; this control needs the live schema")
    engine = create_engine(url.replace("+asyncpg", "+psycopg"))
    reach = erasure_reach()
    try:
        with engine.connect() as conn:
            transaction = conn.begin()
            try:
                conn.execute(
                    text(
                        "CREATE TABLE call_whisper_notes (id uuid PRIMARY KEY, "
                        "call_id uuid REFERENCES calls(id), phone_e164 text, note text)"
                    )
                )
                failures = evaluate(read_state(conn), reach)
            finally:
                transaction.rollback()
            assert any("call_whisper_notes" in failure for failure in failures)
            # ...and the same guard is clean the moment the table is gone, so the failure
            # above is about the table and not about the tree it was created in.
            assert evaluate(read_state(conn), reach) == []
    finally:
        engine.dispose()
