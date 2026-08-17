"""Negative controls for `scripts/check_session_nesting.py`, and the pair it is half of.

A guardrail that has never been seen to go RED is a claim, not a control — the same
argument `tests/wiring_guard_test.py` and `tests/model_residency_guard_test.py` make for
their scripts. Every case here builds a small doctored tree and asserts which way the
check falls, so the failure mode this guard exists for is exercised without waiting for
somebody to commit it.

The last test is the one that matters most and is the shortest: the number in the script
and the number in `db/session.py` are ONE decision. If a future change raises
`max_overflow` without raising the ceiling — or, worse, drops it back to 0 while fifty
functions in this tree hold two connections — the pool and the code disagree again, which
is exactly the state D-182 found.
"""

from __future__ import annotations

from pathlib import Path

from apps.api.db.session import MAX_NESTED_CONNECTIONS, get_engine
from scripts import check_session_nesting as guard

# A dependency that keeps its session open for the whole endpoint — `deps.db`'s shape.
DEPS = """
from apps.api.db.session import tenant_session

async def db():
    async with tenant_session(TENANT) as session:
        yield session

async def whoami():
    async with tenant_session(TENANT) as session:
        return session
"""

# The legitimate depth-2 chain: a global read behind two calls, opened inside a caller's
# session. `check_dispatch` -> `get_platform_status` -> `_read_durable`.
GLOBALS = """
from apps.api.db.session import untenanted_session

async def read_durable():
    async with untenanted_session() as session:
        return session

async def platform_status():
    return await read_durable()
"""


def _tree(root: Path, files: dict[str, str]) -> Path:
    package = root / "pkg"
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    for name, body in files.items():
        (package / name).write_text(body, encoding="utf-8")
    return package


def _depth(root: Path, files: dict[str, str], function: str) -> int:
    package = _tree(root, files)
    analyzer = guard.analyze(package, base=root)
    module = f"pkg.{function.split('.')[0]}"
    return analyzer.cost((module, function.split(".")[1]))[0]


def test_a_global_read_inside_a_tenant_session_is_two(tmp_path: Path) -> None:
    """The chain the audit found, in miniature: nobody in `caller.py` can see that
    `platform_status` reaches Postgres, which is why this is a tree walk and not a
    reviewer's job."""
    caller = """
from apps.api.db.session import tenant_session
from pkg.globals import platform_status

async def dial():
    async with tenant_session(TENANT) as session:
        await platform_status()
        return session
"""
    assert _depth(tmp_path, {"globals.py": GLOBALS, "caller.py": caller}, "caller.dial") == 2


def test_a_third_nesting_fails_the_check(tmp_path: Path) -> None:
    """THE DEFECT THE SCRIPT EXISTS FOR. One more level than the pool's overflow can
    absorb, and every task at this depth waits for a connection only another task at this
    depth can release."""
    caller = """
from apps.api.db.session import tenant_session, untenanted_session
from pkg.globals import platform_status

async def dial():
    async with tenant_session(TENANT) as session:
        async with untenanted_session() as audit:
            await platform_status()
        return session, audit
"""
    package = _tree(tmp_path, {"globals.py": GLOBALS, "caller.py": caller})
    assert guard.main(package, base=tmp_path) == 1


def test_the_session_a_dependency_holds_counts(tmp_path: Path) -> None:
    """A route handler opens no session in its body and holds one for every line of it.

    Written in the spelling this repo actually uses — a module-level
    `Session = Annotated[AsyncSession, Depends(db)]` — because the first draft of the
    script only understood `= Depends(db)` defaults and therefore scored every route in
    `crm/routes.py` at 1.
    """
    routes = """
from typing import Annotated
from fastapi import Depends
from apps.api.db.session import untenanted_session
from pkg.deps import db
from pkg.globals import platform_status

Session = Annotated[object, Depends(db)]

async def call_lead(session: Session):
    await platform_status()

async def audited_call(session: Session):
    async with untenanted_session() as ledger:
        await platform_status()
        return ledger
"""
    files = {"deps.py": DEPS, "globals.py": GLOBALS, "routes.py": routes}
    assert _depth(tmp_path, files, "routes.call_lead") == 2
    # The same handler with one more level is the failure: request session + its own
    # ledger session + the global read inside that.
    assert _depth(tmp_path, files, "routes.audited_call") == 3


def test_a_dependency_that_does_not_yield_is_not_charged(tmp_path: Path) -> None:
    """`Depends(whoami)` opens and closes before the handler starts. Charging the handler
    for it would over-report every route in the tree, and an over-reporting guard is one
    that gets switched off."""
    routes = """
from typing import Annotated
from fastapi import Depends
from pkg.deps import whoami
from pkg.globals import platform_status

Who = Annotated[object, Depends(whoami)]

async def profile(who: Who):
    await platform_status()
"""
    files = {"deps.py": DEPS, "globals.py": GLOBALS, "routes.py": routes}
    assert _depth(tmp_path, files, "routes.profile") == 1


def test_closing_before_the_vendor_call_reads_as_one(tmp_path: Path) -> None:
    """The shape `outbound_webhooks.deliver_outbound_webhook` was restructured into: read
    in one short session, call the third party with none open, write in a second. Three
    session blocks, never two at once — the guard must not confuse sequence with nesting,
    or the fix it is meant to protect would look like the defect."""
    worker = """
from apps.api.db.session import tenant_session
from pkg.globals import platform_status

async def deliver():
    async with tenant_session(TENANT) as session:
        endpoint = session
    await platform_status()
    async with tenant_session(TENANT) as session:
        return session
"""
    assert _depth(tmp_path, {"globals.py": GLOBALS, "worker.py": worker}, "worker.deliver") == 1


def test_an_unresolvable_call_is_not_guessed(tmp_path: Path) -> None:
    """`match.start()` is not `agents.experiments.start`. Resolution goes through the
    imports precisely so a method call on an unrelated object cannot invent a chain — the
    first draft did, and reported the whole tree as three-deep."""
    worker = """
from apps.api.db.session import tenant_session

async def scan(pattern, text):
    async with tenant_session(TENANT) as session:
        match = pattern.search(text)
        return match.start(), session
"""
    other = """
from apps.api.db.session import untenanted_session

async def start():
    async with untenanted_session() as session:
        return session
"""
    assert _depth(tmp_path, {"other.py": other, "worker.py": worker}, "worker.scan") == 1


def test_the_real_tree_is_inside_the_ceiling() -> None:
    assert guard.main() == 0


def test_the_pool_holds_exactly_one_more_than_the_deepest_task() -> None:
    """THE PAIR. `max_overflow` is what makes depth 2 survivable and depth 3 a deadlock,
    so the pool's number and the guard's number are one decision written twice."""
    assert guard.MAX_DEPTH == MAX_NESTED_CONNECTIONS
    pool = get_engine().pool
    assert getattr(pool, "_max_overflow", None) == MAX_NESTED_CONNECTIONS - 1, (
        "the engine's overflow no longer matches the nesting the guard permits: with less, "
        "a pool at its ceiling full of depth-2 tasks deadlocks against itself; with more, "
        "the single-use-connection storm `get_engine` measured comes back"
    )
