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
    ENTRYPOINT_EXEMPT,
    ERASURE_ENTRYPOINTS,
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


#: The one entrypoint most of these controls use. Reach is PER ENTRYPOINT since 18 Sep
#: 2026, so a synthetic reach has to name which erasure it is about; a helper that quietly
#: filled in both would re-create the union the correction removed, inside the tests that
#: are supposed to police it.
_SUBJECT = "execute_deletion_request"
_TENANT = "execute_tenant_erasure"


def _reach(*tables: str, entrypoint: str = _SUBJECT) -> ErasureReach:
    return ErasureReach(
        by_entrypoint={entrypoint: frozenset(tables)},
        visited=frozenset({entrypoint}),
    )


def _both(subject: tuple[str, ...], tenant: tuple[str, ...]) -> ErasureReach:
    """Two entrypoints with DIFFERENT reach — the shape the union used to flatten."""
    return ErasureReach(
        by_entrypoint={_SUBJECT: frozenset(subject), _TENANT: frozenset(tenant)},
        visited=frozenset({_SUBJECT, _TENANT}),
    )


class TestTheRuleItself:
    def test_a_table_holding_a_subject_handle_with_no_arm_fails(self) -> None:
        """THE FINDING THIS GUARD EXISTS FOR, in miniature: a table lands carrying a
        caller's number and no erasure statement names it."""
        state = SchemaState(
            subject_handle_tables=frozenset({"whispered_numbers"}),
            all_tables=frozenset({"whispered_numbers"}),
        )
        failures = evaluate(state, _reach(), exemptions={}, entrypoint_exemptions={})
        assert len(failures) == 1
        assert "whispered_numbers" in failures[0]
        assert "NO arm of `execute_deletion_request`" in failures[0]

    def test_a_child_of_calls_with_no_arm_fails(self) -> None:
        """`handoff_attempts`' shape: no number of its own, a foreign key to `calls`, and
        prose about the conversation. The `ON DELETE CASCADE` never fires because an
        erasure EMPTIES a call rather than deleting it."""
        state = SchemaState(
            subject_linked_tables=frozenset({"handover_notes"}),
            all_tables=frozenset({"handover_notes"}),
        )
        failures = evaluate(state, _reach(), exemptions={}, entrypoint_exemptions={})
        assert "link to a call/lead" in failures[0]

    def test_a_table_holding_an_inline_payload_with_no_arm_fails(self) -> None:
        """`outbox_messages`' shape: no tenant_id, no call, a jsonb body with a lead's
        name and number in it."""
        state = SchemaState(
            prose_tables=frozenset({"queued_bodies"}), all_tables=frozenset({"queued_bodies"})
        )
        failures = evaluate(state, _reach(), exemptions={}, entrypoint_exemptions={})
        assert "free-text or jsonb payload" in failures[0]

    def test_an_arm_that_names_the_table_passes(self) -> None:
        state = SchemaState(
            subject_handle_tables=frozenset({"whispered_numbers"}),
            all_tables=frozenset({"whispered_numbers"}),
        )
        reach = _reach("whispered_numbers")
        assert evaluate(state, reach, exemptions={}, entrypoint_exemptions={}) == []

    def test_an_exemption_with_a_reason_passes(self) -> None:
        state = SchemaState(
            subject_handle_tables=frozenset({"staff_mobiles"}),
            all_tables=frozenset({"staff_mobiles"}),
        )
        reason = "The client's own staff, a different data principal on a different basis."
        assert len(reason) >= MIN_EXEMPTION_REASON
        exempt = {"staff_mobiles": reason}
        assert evaluate(state, _reach(), exemptions=exempt, entrypoint_exemptions={}) == []


class TestTheRegisterStaysHonest:
    """The other direction. `check_rls_coverage`'s rule 4, one obligation along: a dead
    exemption reads as a considered decision and hides the next real gap behind a name
    nobody rechecks."""

    def test_an_exemption_for_a_table_that_no_longer_exists_fails(self) -> None:
        failures = evaluate(
            SchemaState(all_tables=frozenset({"calls"})),
            _reach("calls"),
            exemptions={"deleted_last_year": "A table that was dropped three migrations ago."},
            entrypoint_exemptions={},
        )
        assert any("STALE erasure exemption" in failure for failure in failures)

    def test_an_exemption_for_a_table_nothing_would_have_asked_about_fails(self) -> None:
        failures = evaluate(
            SchemaState(all_tables=frozenset({"alembic_version"})),
            _reach(),
            exemptions={
                "alembic_version": "Migration bookkeeping, which holds nobody's personal data."
            },
            entrypoint_exemptions={},
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
            entrypoint_exemptions={},
        )
        assert any("also reached by an erasure arm" in failure for failure in failures)

    def test_a_thin_reason_fails(self) -> None:
        state = SchemaState(
            subject_handle_tables=frozenset({"staff_mobiles"}),
            all_tables=frozenset({"staff_mobiles"}),
        )
        failures = evaluate(
            state, _reach(), exemptions={"staff_mobiles": "n/a"}, entrypoint_exemptions={}
        )
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


class TestReachIsPerEntrypointAndNotAUnion:
    """THE CORRECTION OF 18 SEP 2026, controlled from both sides.

    `execute_deletion_request` answers one data principal under DPDP §12 and
    `execute_tenant_erasure` closes a whole account. They produce different certificates,
    handed to different people, and the guard used to union their reach before asking its
    question — so a table only the tenant erasure touched satisfied the per-subject rule
    and the per-subject certificate could enumerate an erasure that never ran.
    `copilot_memories` passed exactly that way.
    """

    def test_a_table_only_the_tenant_erasure_reaches_fails_the_subject_erasure(self) -> None:
        """The union bug itself. Under the old rule this returned no failures."""
        state = SchemaState(
            prose_tables=frozenset({"assistant_notes"}),
            all_tables=frozenset({"assistant_notes"}),
        )
        failures = evaluate(
            state,
            _both(subject=(), tenant=("assistant_notes",)),
            exemptions={},
            entrypoint_exemptions={},
        )
        assert len(failures) == 1
        assert "NO arm of `execute_deletion_request`" in failures[0]
        # And it says WHERE it is reached, so the reader is not left to discover that the
        # other erasure covers it and conclude the guard is confused.
        assert "It IS reached by execute_tenant_erasure" in failures[0]

    def test_the_same_gap_passes_once_it_is_a_registered_argument(self) -> None:
        state = SchemaState(
            prose_tables=frozenset({"assistant_notes"}),
            all_tables=frozenset({"assistant_notes"}),
        )
        reason = (
            "Written with identifiers already redacted, so an erasure keyed on a phone "
            "number has no predicate; the tenant erasure deletes every row."
        )
        assert len(reason) >= MIN_EXEMPTION_REASON
        assert (
            evaluate(
                state,
                _both(subject=(), tenant=("assistant_notes",)),
                exemptions={},
                entrypoint_exemptions={"execute_deletion_request": {"assistant_notes": reason}},
            )
            == []
        )

    def test_an_entrypoint_exemption_for_a_table_that_entrypoint_does_reach_fails(self) -> None:
        """The other direction, `check_rls_coverage`'s rule 4 at this scope: a registered
        argument that the arm does not reach a table it demonstrably does is a sentence a
        reviewer would believe instead of reading the code."""
        state = SchemaState(
            prose_tables=frozenset({"assistant_notes"}),
            all_tables=frozenset({"assistant_notes"}),
        )
        failures = evaluate(
            state,
            _both(subject=("assistant_notes",), tenant=("assistant_notes",)),
            exemptions={},
            entrypoint_exemptions={
                "execute_deletion_request": {
                    "assistant_notes": "A reason somebody wrote while the arm already existed."
                }
            },
        )
        assert any("and also reached by it" in failure for failure in failures)

    def test_registering_a_table_in_both_registers_fails(self) -> None:
        """They say different things — "nothing reaches it" and "this one does not, the
        other does" — and a table cannot be both."""
        state = SchemaState(
            prose_tables=frozenset({"assistant_notes"}),
            all_tables=frozenset({"assistant_notes"}),
        )
        reason = "A reason long enough to clear the minimum this register imposes."
        failures = evaluate(
            state,
            _both(subject=(), tenant=("assistant_notes",)),
            exemptions={"assistant_notes": reason},
            entrypoint_exemptions={"execute_deletion_request": {"assistant_notes": reason}},
        )
        assert any("registered BOTH" in failure for failure in failures)

    def test_an_exemption_against_an_entrypoint_nobody_walks_fails(self) -> None:
        failures = evaluate(
            SchemaState(all_tables=frozenset({"calls"})),
            _reach("calls"),
            exemptions={},
            entrypoint_exemptions={
                "execute_some_erasure_we_deleted": {"calls": "A reason about an arm that is gone."}
            },
        )
        assert any("an entrypoint this scan does not walk" in failure for failure in failures)

    def test_an_entrypoint_whose_walk_sees_no_sql_is_a_blind_spot(self) -> None:
        """`check_wiring`'s rule 5, per entrypoint. If ONE of the two walks stops finding
        SQL — renamed, refactored into a class, moved out of the scanned sources — the
        union's anchors could still be satisfied by the other one, and every verdict about
        the broken half would be about the scan."""
        reach = erasure_reach(sources=(REPO_ROOT / "apps" / "api" / "compliance" / "deletion.py",))
        assert any(
            "reaches no table at all" in blind or "defined in none" in blind
            for blind in reach.blind_spots
        )

    def test_the_live_walk_reaches_something_from_each_entrypoint(self) -> None:
        reach = erasure_reach()
        assert set(reach.by_entrypoint) == set(ERASURE_ENTRYPOINTS)
        for entrypoint, tables in reach.by_entrypoint.items():
            assert tables, f"{entrypoint} reaches no table"

    def test_every_registered_entrypoint_argument_names_a_walked_entrypoint(self) -> None:
        """The register is read by a human before it is read by `evaluate`, so a typo in a
        key would silently exempt nothing at all."""
        assert set(ENTRYPOINT_EXEMPT) <= set(ERASURE_ENTRYPOINTS)
        for entrypoint, tables in ENTRYPOINT_EXEMPT.items():
            for table, reason in tables.items():
                assert len(reason.strip()) >= MIN_EXEMPTION_REASON, (entrypoint, table)
                assert table not in ERASURE_EXEMPT, table
