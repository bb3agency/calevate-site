"""The half-wiring guard, proved against the states it exists to catch.

`scripts/check_wiring.py` is the gate; this file is the evidence that the gate can go
red. A check nobody has watched fail is a check nobody knows is connected — the same
argument `check_redaction_exposure.check_allowlist` makes when it refuses to pass on a
route table with no permissions in it at all.

Each test here reconstructs a state that actually shipped in this repo:

* `publishing_routes.router` — written, tested, mounted by nobody, and therefore
  invisible to `assert_policy_registry_complete`, `impersonation_reads_test` and
  `authz_audit_test`. An unmounted router does not fail; it silently opts out of every
  sweep that would have found a D-22 violation in it.
* `prompt_versions.compiled_t0_context` — a column with no writer for weeks.
* an alembic branch nobody can reach from head.

The last two tests are blind-spot guards, in the shape of
`job_registration_test.test_a_job_name_is_declared_as_a_constant_rather_than_a_literal`:
they assert the properties the scans DEPEND on, because a scan that has quietly stopped
seeing anything reads exactly like a clean tree.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from apps.api.core.rbac import iter_api_routes
from apps.api.main import app
from apps.workers.settings import CRON_JOBS, FUNCTIONS, WorkerSettings
from scripts import check_wiring

REPO_ROOT = Path(__file__).resolve().parent.parent


# --- routers ------------------------------------------------------------------


def _endpoints_of(module_suffix: str) -> set[object]:
    return {
        route.endpoint
        for route in iter_api_routes(app)
        if route.endpoint.__module__.endswith(module_suffix)
    }


def test_the_live_app_mounts_every_router_it_declares() -> None:
    """The standing assertion. `make guardrails` runs the same function."""
    declared = check_wiring.declared_routers()
    assert len(declared) >= 20, f"the router scan found only {len(declared)} — it is blind"
    assert not check_wiring.unmounted_routers(declared), check_wiring.unmounted_routers(declared)


def test_a_scan_that_finds_no_routers_refuses_instead_of_passing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """D-176: the shape the audit of our own guardrails found here.

    `declared_routers()` walks two directories with `rglob`, which yields nothing — and
    raises nothing — when a directory is renamed or moved. Section 1 then finds no
    declaration to compare against the route table and reports no offenders, so the whole
    router half of this guard prints `OK (0 routers all mounted)`. Pointing both roots at
    an empty tree is exactly that state, and it must now be a failure that says so.
    """
    monkeypatch.setattr(check_wiring, "API_ROOT", tmp_path)
    monkeypatch.setattr(check_wiring, "VOICE_RUNTIME_ROOT", tmp_path)

    assert check_wiring.declared_routers() == []
    assert check_wiring.unmounted_routers() == [], "the vacuous pass this test exists for"
    assert any("looking at the wrong place" in failure for failure in check_wiring.blind_spots())


def test_a_column_scan_that_finds_almost_nothing_refuses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The same property for section 3, whose left side is the declared-column set."""
    monkeypatch.setattr(check_wiring, "SCAN_ROOTS", (tmp_path,))

    assert any("fraction of the schema" in failure for failure in check_wiring.blind_spots())


def test_an_unmounted_router_is_caught() -> None:
    """`apps/api/agents/publishing_routes.py` as it actually shipped: complete, and
    absent from `_mount_routers`."""
    declared = check_wiring.declared_routers()
    mounted = check_wiring.mounted_endpoints()
    publishing = _endpoints_of("agents.publishing_routes")
    assert publishing, "the two-speed publishing routes moved — this test names a dead module"

    offenders = check_wiring.unmounted_routers(declared, mounted=mounted - publishing)
    assert any("publishing_routes" in offender for offender in offenders), offenders
    assert all("mounts none" in offender for offender in offenders if "publishing" in offender)


def test_a_router_mounted_before_its_last_route_was_added_is_caught() -> None:
    """The subtler half of the same bug. `include_router` COPIES the routes it finds at
    the moment it is called, so a route decorated after the mount call exists on the
    router object and on no app. Nothing raises; the endpoint is simply not there."""
    declared = check_wiring.declared_routers()
    mounted = check_wiring.mounted_endpoints()
    one = next(iter(_endpoints_of("agents.routes")))

    offenders = check_wiring.unmounted_routers(declared, mounted=mounted - {one})
    assert any("partially mounted" in offender for offender in offenders), offenders


def test_every_mounted_route_comes_from_a_module_the_scan_can_see() -> None:
    """The router scan's own blind spot, asserted rather than trusted.

    `declared_routers()` reads MODULE-LEVEL `APIRouter()` assignments. A router built
    inside a function or by a factory is invisible to it — and an invisible router can
    never be reported as unmounted, so the guard would stay green while the exact bug
    shipped. Every module that puts routes into the live app must therefore either
    declare its router at module level or be acknowledged here by name.
    """
    seen = {module for module, _ in check_wiring.declared_routers()}
    live = {route.endpoint.__module__ for route in iter_api_routes(app)}
    unseen = sorted(live - seen - check_wiring.DYNAMIC_ROUTER_MODULES.keys())
    assert not unseen, (
        f"these modules put routes into the app but declare no module-level APIRouter: "
        f"{unseen}. The scan cannot see their router, so it can never report it "
        "unmounted. Declare the router at module level, or acknowledge the module in "
        "check_wiring.DYNAMIC_ROUTER_MODULES with the reason."
    )


# --- migrations ---------------------------------------------------------------


def test_an_unreachable_migration_branch_is_caught(tmp_path: Path) -> None:
    """A second head is a migration that `alembic upgrade head` will not apply — the
    table exists in the file, in review and in nobody's database."""
    scratch = tmp_path / "alembic"
    shutil.copytree(REPO_ROOT / "alembic", scratch, ignore=shutil.ignore_patterns("__pycache__"))
    assert not check_wiring.unreachable_migrations(scratch), "the copy is not a faithful one"

    # Parented on the FIRST revision, so the tree now has two heads: the real trunk and
    # this one. That is what an unnoticed rebase, or two agents generating migrations
    # in the same afternoon, actually leaves behind.
    base = check_wiring.migration_base(scratch)
    (scratch / "versions" / "zz_orphan_branch.py").write_text(
        '"""an orphan"""\n'
        'revision = "zzzz0rphan"\n'
        f'down_revision = "{base}"\n'
        "branch_labels = None\n"
        "depends_on = None\n"
        "def upgrade() -> None: ...\n"
        "def downgrade() -> None: ...\n"
    )
    # Two revisions now claim the same parent, which is what an unnoticed rebase or two
    # agents generating migrations in parallel produces.
    offenders = check_wiring.unreachable_migrations(scratch)
    assert any("zzzz0rphan" in offender for offender in offenders), offenders


# --- columns ------------------------------------------------------------------


def test_a_column_no_code_touches_is_caught(tmp_path: Path) -> None:
    """`prompt_versions.compiled_t0_context` before the intake step wrote it.

    Built as a tree rather than by monkeypatching the live one, because the thing under
    test is the scan over a tree.
    """
    models = tmp_path / "models.py"
    models.write_text(
        "from sqlalchemy.orm import Mapped, mapped_column\n"
        "class PromptVersion:\n"
        '    __tablename__ = "prompt_versions"\n'
        "    body: Mapped[str] = mapped_column()\n"
        "    compiled_t0_context: Mapped[str | None] = mapped_column()\n"
    )
    reader = tmp_path / "service.py"
    reader.write_text('SQL = "SELECT body FROM prompt_versions"\n')

    offenders = check_wiring.unwired_columns(roots=(tmp_path,), baseline={})
    assert offenders == ["PromptVersion.compiled_t0_context (models.py)"], offenders

    # The day a writer lands — even in a raw SQL string, which is how this repo writes
    # most of them — the guard goes quiet on its own.
    reader.write_text('SQL = "SELECT body, compiled_t0_context FROM prompt_versions"\n')
    assert check_wiring.unwired_columns(roots=(tmp_path,), baseline={}) == []


def test_a_mention_in_prose_does_not_count_as_wiring(tmp_path: Path) -> None:
    """Docstrings and comments are where a half-wired column is DESCRIBED, so a scan
    that counts them is at its blindest exactly where the bug lives. This is the
    difference between reading the AST and grepping the file."""
    (tmp_path / "models.py").write_text(
        "from sqlalchemy.orm import Mapped, mapped_column\n"
        "class Agent:\n"
        '    __tablename__ = "agents"\n'
        "    business_hours: Mapped[dict | None] = mapped_column()\n"
    )
    (tmp_path / "service.py").write_text(
        '"""FLOWS §3 reads agents.business_hours for the after-hours flag."""\n'
        "# business_hours is compiled into the prompt\n"
    )
    offenders = check_wiring.unwired_columns(roots=(tmp_path,), baseline={})
    assert offenders == ["Agent.business_hours (models.py)"], offenders


def test_the_live_tree_has_no_unwired_column_outside_the_baseline() -> None:
    assert check_wiring.unwired_columns() == []


def test_every_baseline_entry_still_names_a_column_that_is_still_unwired() -> None:
    """The anti-rubber-stamp half. An entry that no longer matches anything is a hole
    with a comment on it (`check_redaction_exposure.check_registry_freshness`), and an
    entry for a column somebody has since wired must be DELETED so the baseline can
    only ever shrink."""
    assert check_wiring.stale_baseline() == []


# --- the worker registry ------------------------------------------------------


def test_the_registry_the_guards_read_is_the_one_the_worker_boots() -> None:
    """`job_registration_test` asserts things about `FUNCTIONS` and `CRON_JOBS`. That is
    only a statement about the running worker while `WorkerSettings` is those same two
    objects — rebind either one and every job guard in the repo becomes an assertion
    about a list nobody executes."""
    assert WorkerSettings.functions is FUNCTIONS
    assert WorkerSettings.cron_jobs is CRON_JOBS
