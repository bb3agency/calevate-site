"""The raw-SQL guardrail, proved against the states it exists to catch (D-172).

`scripts/check_raw_sql.py` claims that every string reaching `text()` in `apps/` and
`packages/` was assembled from text typed in this repository — literals, constants,
fragments returned by our own helpers, or an identifier that went through `_identifier()`.
A check making that claim while blind to a real splice would be worse than none: it would
put a green tick beside the one defect class that turns an RLS session into a
cross-tenant read.

Three kinds of test, the shape `tests/web_env_parity_guard_test.py` and
`tests/docs_drift_guard_test.py` established:

- **wiring** — the check is pointed at the REAL tree. A check that has drifted away from
  what it claims to read fails here rather than in six months.
- **detection** — take a REAL module, apply ONE minimal mutation that IS the violation,
  and assert the real `audit()` names that file and line. Mutating reality rather than
  inventing a fixture is what keeps the mutation meaningful: if `_identifier` moves, or
  `transition_status` stops interpolating, these fail and somebody re-reads them.
- **calibration** — the shapes that are safe and look dynamic (a module constant built by
  a comprehension, a fragment threaded through two call layers, an `enumerate` index).
  They are pinned as tests that must report NOTHING, because the first false positive is
  what teaches people to add an allowance.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from scripts import check_raw_sql as guard

REPO_ROOT = Path(__file__).resolve().parent.parent


# --- helpers ------------------------------------------------------------------


@pytest.fixture(scope="module")
def modules() -> list[guard.Module]:
    """The real tree, parsed once. Every test below starts from this and swaps in at most
    one doctored module, so a mutation is exactly one file different from production."""
    return guard.load_modules()


def _doctored(modules: list[guard.Module], rel: str, old: str, new: str) -> list[guard.Module]:
    """`modules` with `rel` replaced by a copy whose source has `old` rewritten to `new`."""
    return _doctored_many(modules, {rel: [(old, new)]})


def _doctored_many(
    modules: list[guard.Module], edits: dict[str, list[tuple[str, str]]]
) -> list[guard.Module]:
    """The same, for mutations that need to land in two files at once."""
    replaced: dict[str, guard.Module] = {}
    for rel, substitutions in edits.items():
        original = next(m for m in modules if m.rel == rel)
        source = original.path.read_text(encoding="utf-8")
        for old, new in substitutions:
            assert old in source, f"the mutation no longer matches {rel} — update this test"
            source = source.replace(old, new, 1)
        module = guard.Module(path=original.path, rel=rel, tree=ast.parse(source, filename=rel))
        _index(module)
        replaced[rel] = module
    return [replaced.get(m.rel, m) for m in modules]


def _index(module: guard.Module) -> None:
    """Repeat `load_modules`' per-module indexing for a module we parsed ourselves.

    Deliberately calls the guardrail's own helpers rather than restating the rules: a test
    that re-implemented the indexing would keep passing while the real one broke.
    """
    for stmt in module.tree.body:
        guard._collect_assignments(stmt, module.assignments)
    for node in ast.walk(module.tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            module.functions.setdefault(node.name, node)
            for child in ast.walk(node):
                module.owner.setdefault(id(child), node)
        elif isinstance(node, ast.ImportFrom):
            origin = guard._absolute_import(module.rel, node)
            if origin is None:
                continue
            for alias in node.names:
                local = alias.asname or alias.name
                module.imported_from[local] = origin
                module.imported_as[local] = alias.name
        elif isinstance(node, ast.Import):
            for alias in node.names:
                module.imported_from[alias.asname or alias.name] = alias.name
                module.imported_as[alias.asname or alias.name] = ""
    for node in ast.walk(module.tree):
        if isinstance(node, ast.comprehension) and id(node) not in module.owner:
            for name, value in guard._destructure_iteration(node.target, node.iter):
                module.assignments.setdefault(name, []).append(value)


def _sites(findings: list[guard.Finding]) -> set[str]:
    return {finding.site for finding in findings}


# --- wiring -------------------------------------------------------------------


class TestWiring:
    def test_the_real_tree_is_clean(self, modules: list[guard.Module]) -> None:
        """The state this guardrail exists to hold. If this fails, read the finding —
        it is naming a statement whose text nobody can trace to a literal."""
        assert guard.audit(modules) == []

    def test_it_is_actually_looking_at_statements(self, modules: list[guard.Module]) -> None:
        """A clean report from a check that found nothing to check is not a clean report.
        `main()` refuses that case; this pins the number well below today's so a real
        collapse in discovery (a renamed import, a changed sink) fails here first."""
        total = sum(len(guard.sql_sites(module)) for module in modules)
        assert total > 300, f"only {total} `text()` statements found — discovery is broken"

    def test_the_only_raw_sql_door_is_still_the_one_we_watch(
        self, modules: list[guard.Module]
    ) -> None:
        """`exec_driver_sql` and `literal_column` would each be a second door. The check
        reports them; this proves the tree has none, so the verdict above is total."""
        assert guard.forbidden_sink_uses(modules) == []

    def test_every_declared_validator_exists(self, modules: list[guard.Module]) -> None:
        """`SAFE_IDENTIFIER_CALLS` is a trust anchor: a call to one of these is waved
        through. A name in it that no longer exists is a hole nobody would notice, because
        the check would simply stop applying it."""
        defined = {name for module in modules for name in module.functions}
        assert defined >= guard.SAFE_IDENTIFIER_CALLS

    def test_the_allowlist_is_empty_and_its_entries_would_be_checked(self) -> None:
        """Kept empty deliberately. The two clauses that police it are proved below; this
        is the standing statement that nothing is currently excused."""
        assert guard.SPLICE_ALLOWANCES == {}


# --- detection ----------------------------------------------------------------


class TestDetection:
    #: `crm/service.py` moves a lead by calling `transition_status(table="leads", ...)`.
    #: Rewrite that literal to `status` — a value that arrives on the request — and the
    #: table name becomes runtime data. It is the pair of mutations below that pins what
    #: `_identifier()` is FOR: with it, a runtime identifier is acceptable; without it,
    #: the same call is an injection. One mutation alone proves neither, because every
    #: caller in the tree passes a literal today and the check would say so, correctly.
    _RUNTIME_TABLE = ('table="leads",', "table=status,")
    _NO_VALIDATOR = ('table = _identifier(table, "table")', "table = table")

    def test_a_runtime_identifier_is_accepted_only_because_it_is_validated(
        self, modules: list[guard.Module]
    ) -> None:
        doctored = _doctored(modules, "apps/api/crm/service.py", *self._RUNTIME_TABLE)
        assert guard.audit(doctored) == [], "the validator should still cover this"

    def test_the_same_identifier_without_the_validator_is_reported(
        self, modules: list[guard.Module]
    ) -> None:
        doctored = _doctored_many(
            modules,
            {
                "apps/api/crm/service.py": [self._RUNTIME_TABLE],
                "apps/api/db/transition.py": [self._NO_VALIDATOR],
            },
        )
        sites = _sites(guard.audit(doctored))
        assert any(site.startswith("apps/api/db/transition.py:") for site in sites), sites

    def test_a_caller_passing_a_runtime_value_is_reported(
        self, modules: list[guard.Module]
    ) -> None:
        """The interprocedural half, and the one a linter cannot do. `reject_source` hands
        `transition_status` a LITERAL `extra_set` fragment today. Hand it the caller's
        `reason` string instead — a genuine request value — and the splice is unsafe at a
        site three files away from the `text()` that performs it."""
        doctored = _doctored(
            modules,
            "apps/api/kb/service.py",
            'extra_set="rejection_reason = :reason",',
            "extra_set=f\"rejection_reason = '{reason}'\",",
        )
        sites = _sites(guard.audit(doctored))
        assert any(site.startswith("apps/api/db/transition.py:") for site in sites), sites

    def test_a_value_read_off_an_object_is_reported(self, modules: list[guard.Module]) -> None:
        """The commonest real shape: an attribute of something that arrived over the wire
        spliced into a WHERE clause. `crm/service.py` already binds `:status`; make it an
        f-string of a request field instead."""
        doctored = _doctored(
            modules,
            "apps/api/crm/service.py",
            'row_clauses.append("l.status = :status")',
            "row_clauses.append(f\"l.status = '{params.status}'\")",
        )
        sites = _sites(guard.audit(doctored))
        assert any(site.startswith("apps/api/crm/service.py:") for site in sites), sites

    def test_a_second_raw_sql_door_is_reported(self, modules: list[guard.Module]) -> None:
        """`exec_driver_sql` takes a string and executes it with no bind parameters at
        all. It would make every verdict this check gives partial, so it is refused by
        name rather than left to review."""
        doctored = _doctored(
            modules,
            "apps/api/crm/service.py",
            "await session.execute(",
            "await session.exec_driver_sql(",
        )
        reported = guard.forbidden_sink_uses(doctored)
        assert reported and "exec_driver_sql" in reported[0], reported

    def test_an_allowance_for_a_clean_site_is_reported(
        self, monkeypatch: pytest.MonkeyPatch, modules: list[guard.Module]
    ) -> None:
        """The registry may only shrink. An allowance that outlives the code it excused
        goes on excusing whatever moves onto that line, which is how an exemption file
        becomes a blind spot."""
        monkeypatch.setattr(
            guard,
            "SPLICE_ALLOWANCES",
            {"apps/api/crm/service.py:1": "a reason long enough to clear the length floor"},
        )
        assert guard.stale_allowances(guard.audit(modules)) == ["apps/api/crm/service.py:1"]

    def test_an_allowance_without_a_real_reason_is_reported(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ "legacy" is not a reason. The floor is crude on purpose — it cannot judge an
        argument, only refuse the absence of one."""
        monkeypatch.setattr(guard, "SPLICE_ALLOWANCES", {"apps/api/crm/service.py:1": "legacy"})
        assert guard.thin_reasons() == [
            f"apps/api/crm/service.py:1: reason is 6 characters; {guard._MIN_REASON} is the floor"
        ]

    def test_broken_discovery_refuses_rather_than_passing(self, tmp_path: Path) -> None:
        """A scan root that resolves to nothing must raise, not report a clean tree."""
        (tmp_path / "apps").mkdir()
        (tmp_path / "packages").mkdir()
        with pytest.raises(guard.RawSqlError):
            guard.load_modules(root=tmp_path)


# --- calibration --------------------------------------------------------------


class TestCalibration:
    """Safe shapes that LOOK dynamic. Each was a false positive during development, and
    each is here so the narrowing that removed it cannot be undone silently."""

    def test_a_constant_assembled_by_a_comprehension_is_accepted(
        self, modules: list[guard.Module]
    ) -> None:
        """`billing/service.py::_NOT_AI_UNITS` is `"…ARRAY[" + ", ".join(f"'{u}'" for u in
        AI_ASSIST_UNIT_TYPES) + "]"` — a module constant whose text comes through a loop
        variable. Refusing it would push people to hand-write the array, which is the
        drift the constant exists to prevent."""
        billing = next(m for m in modules if m.rel == "apps/api/billing/service.py")
        resolver = guard.Resolver(modules)
        constant = billing.assignments["_NOT_AI_UNITS"][0]
        assert resolver.safe(constant, billing)

    def test_a_dict_is_judged_by_the_half_that_is_used(self, modules: list[guard.Module]) -> None:
        """`transition_status` builds `{":__t_from0": state}`: the KEYS are bind names it
        wrote and the VALUES are the caller's statuses, bound as parameters. It splices
        the keys. A single verdict for the whole dict is wrong either way — values-only
        would pass a splice of the keys unread, keys-and-values would refuse this correct
        statement — so iteration and indexing ask different questions."""
        transition = next(m for m in modules if m.rel == "apps/api/db/transition.py")
        resolver = guard.Resolver(modules)
        update = next(
            call for call in guard.sql_sites(transition) if "UPDATE" in ast.unparse(call.args[0])
        )
        assert resolver.safe(update.args[0], transition)

    def test_an_enumerate_index_is_not_data(self, modules: list[guard.Module]) -> None:
        """`crm/service.py::_lead_scope` writes `f"l.data ->> :ff_k{i} = ANY(:ff_v{i})"`
        while binding the key and the values as parameters. `i` comes from `enumerate`, so
        it is an integer this loop produced — the facet key never reaches the SQL text."""
        crm = next(m for m in modules if m.rel == "apps/api/crm/service.py")
        resolver = guard.Resolver(modules)
        scope = crm.functions["_lead_scope"]
        assert resolver._returns_safe(crm, scope)
