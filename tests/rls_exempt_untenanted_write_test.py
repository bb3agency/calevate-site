"""An RLS exemption buys a READ. `check_rls_coverage` used to let it buy every verb.

D-575. `scripts/check_rls_coverage.evaluate` skipped rules 1-3 wholesale for any table
in `RLS_EXEMPT_TENANT_COLUMNS`, so `PolicyFacts.opens_when_guc_unset` — the rule written
for exactly one policy shape after the measured `kb_uploads` incident (7 Sep 2026) —
never ran on the one set of tables whose entries ARGUE for cross-tenant access.
Measured against the live catalogue on 10 Sep 2026, before migration b8e2d47f0c19
narrowed them: `engine_agent_routes` and `engine_kb_routes` each carried
`tenant_isolation` FOR ALL with both `USING` and `WITH CHECK` equal to
`tenant_id = <guc> OR <guc> IS NULL`, and an untenanted `calevate_app` session
re-tenanted and deleted another tenant's row at rowcount 1 on each table, while its
INSERT of a row naming an arbitrary tenant got PAST the policy (the minimal probe row
was stopped by a NOT NULL, sqlstate 23502, which is the policy having admitted it;
b8e2d47f0c19's own entry records a complete row landing as `INSERT 0 1`). The gate
printed OK throughout.

WHY THIS FILE IS FIXTURE-DRIVEN AND NOT A LIVE-DATABASE TEST. The behaviour under test
is `evaluate`'s LOGIC, and the live catalogue was being narrowed by a parallel migration
while this was written: a test pointed at the live schema would have reported the state
of that migration rather than the state of this rule, in whichever direction — and it
goes quiet the moment the schema is clean, which is precisely when a regression in the
rule stops being visible. So both policy shapes — the open one measured above and the
narrowed one that replaced it — are constructed here by hand from the stored expressions
Postgres actually prints, and the rule is asserted to fire on the first and stay silent
on the second. `rls_sweep_test` carries the behavioural twin against real sessions;
`guardrail_audit_test`'s `test_live_schema_is_clean` is what asserts the live database
agrees.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from apps.api.db.registry import RLS_EXEMPT_TENANT_COLUMNS
from scripts import check_rls_coverage
from scripts.check_rls_coverage import PolicyFacts, SchemaState

# Reused rather than re-typed: the same baseline state and the same two stored
# expressions the sibling guardrail suite already pins, so a change to the policy shape
# this repo writes moves both files at once. `OPEN_WHEN_UNSET` is `kb_uploads`'s escape
# arm as Postgres normalises it; `GUC` is the strict predicate on its own.
from tests.guardrail_audit_test import GUC, OPEN_WHEN_UNSET, _patched, _tenant_state

#: Every exemption, parametrised from the registry rather than listed here: an exemption
#: added tomorrow is swept by these tests with nothing to remember. The baseline below
#: gives each of them a tenant_id column and a policy, which is STRICTER than the live
#: schema (`platform_*` and `outbox_messages` carry neither) and is the right direction
#: for a logic test — the rule must hold for any exempt table that has a policy at all.
EXEMPT_TABLES = sorted(RLS_EXEMPT_TENANT_COLUMNS)

#: The table the incident was measured on (live catalogue, 10 Sep 2026), used wherever a
#: single named target reads clearer than a parametrisation.
TARGET = "engine_agent_routes"
#: The exemption that argues for having NO policy at all, which is the half of the
#: exemption that must keep working untouched.
UNPOLICIED = "audit_log"


def _require(table: str) -> str:
    assert table in RLS_EXEMPT_TENANT_COLUMNS, (
        f"{table} is no longer RLS-exempt — re-point this test at whatever replaced it "
        "rather than deleting the case; it must not pass by naming nothing"
    )
    return table


def _open_state(table: str) -> SchemaState:
    """The shape measured on the live catalogue: FOR ALL, both clauses open when unset."""
    return _patched(
        _tenant_state(), table, using=OPEN_WHEN_UNSET, with_check=OPEN_WHEN_UNSET, cmd="*"
    )


def _narrowed_state(table: str) -> SchemaState:
    """What the narrowing lands: a strict FOR ALL policy beside a FOR SELECT global read.

    This is `engine_agent_routes`'s documented intent — the cross-tenant READ an inbound
    webhook needs, bought with a separate read-only policy, which is `retention_worklist`
    and `dnc_list`'s shape and the one the rule is meant to push people towards.
    """
    state = _patched(_tenant_state(), table, using=GUC, with_check=GUC, cmd="*")
    global_read = PolicyFacts(
        table=table,
        name=f"{table}_global_read",
        rls_enabled=True,
        rls_forced=True,
        using="true",
        with_check=None,
        cmd="r",
        permissive=True,
    )
    return replace(state, policies=(*state.policies, global_read))


class TestAnExemptionDoesNotBuyTheUntenantedWrite:
    @pytest.mark.parametrize("table", EXEMPT_TABLES)
    def test_the_open_arm_is_reported_on_every_exempt_table(self, table: str) -> None:
        """Parametrised over the real registry so no exempt table is quietly outside it."""
        failures = check_rls_coverage.evaluate(_open_state(table))
        assert any(table in f and "unset" in f for f in failures), failures

    def test_it_names_both_clauses(self) -> None:
        """USING decides UPDATE/DELETE reach, WITH CHECK decides what an INSERT may
        claim. They are two holes and the operator has to be told about both."""
        table = _require(TARGET)
        failures = [f for f in check_rls_coverage.evaluate(_open_state(table)) if table in f]
        assert any("USING" in f for f in failures), failures
        assert any("WITH CHECK" in f for f in failures), failures

    def test_the_narrowed_shape_is_accepted(self) -> None:
        """The mirror image, and the assertion that keeps this rule from being a
        nuisance: strict FOR ALL + FOR SELECT USING (true) must pass clean, or the
        migration that fixes the hole would be unable to land."""
        assert check_rls_coverage.evaluate(_narrowed_state(_require(TARGET))) == []

    def test_a_select_only_open_arm_is_still_allowed_on_an_exempt_table(self) -> None:
        """The narrower version of the same point: the escape arm itself is not the
        defect — riding it on a write command is. `FOR SELECT` is how a platform sweep
        legitimately reads across tenants."""
        table = _require(TARGET)
        state = _patched(_tenant_state(), table, using=OPEN_WHEN_UNSET, with_check=None, cmd="r")
        assert check_rls_coverage.evaluate(state) == []

    def test_the_exemption_still_waives_the_rules_it_is_actually_for(self) -> None:
        """The half that must NOT change. `audit_log` carries a tenant_id and no policy
        at all — that is the whole content of its exemption (a per-tenant policy would
        fork the global hash chain). Widening the guard must not start demanding a
        `tenant_isolation` policy from a table whose entry argues against having one.
        """
        table = _require(UNPOLICIED)
        state = _tenant_state()
        state = replace(state, policies=tuple(p for p in state.policies if p.table != table))
        assert check_rls_coverage.evaluate(state) == []

    def test_the_reason_prose_cannot_waive_it(self) -> None:
        """THE HATCH THAT WAS DELIBERATELY NOT BUILT, pinned so nobody builds it later.

        `engine_agent_routes`'s reason said "That arm is deliberate" about the exact
        policy migration b8e2d47f0c19 then deleted — the sweeps it cited turned out never
        to have needed it. A guard that read a waiver out of that prose would have excused
        the finding this rule exists for, on the authority of a sentence that was wrong,
        and gone on excusing it after the policy changed. A legitimate untenanted writer
        needs a second, machine-readable registry entry — not a sentence inside the read
        exemption.
        """
        table = _require(TARGET)
        reason = (
            "the untenanted write arm here is DELIBERATE and intended: background sweeps "
            "run from untenanted_session by design and this is approved, on purpose."
        )
        failures = check_rls_coverage.evaluate(
            _open_state(table),
            exemptions={**RLS_EXEMPT_TENANT_COLUMNS, table: reason},
        )
        assert any(table in f and "unset" in f for f in failures), failures

    def test_a_non_exempt_table_is_unaffected(self) -> None:
        """Regression guard on the refactor: moving the two arms into their own function
        must not have dropped them from the ordinary path."""
        failures = check_rls_coverage.evaluate(
            _patched(_tenant_state(), "leads", using=OPEN_WHEN_UNSET, cmd="*")
        )
        assert any("leads" in f and "unset" in f for f in failures), failures
