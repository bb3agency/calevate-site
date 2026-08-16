"""Negative controls for `scripts/check_audit_ip`.

A guard that has never been seen to fail is a comment with an exit code. These drive the
checker over doctored trees, in the manner of `tests/wiring_guard_test.py` and
`tests/model_residency_guard_test.py`, so the two ways the property can be lost are both
demonstrated rather than asserted.

The real tree is exercised too — and FIRST — because a checker that passes everything
also passes the real tree, and a suite that only proves it rejects bad input has not shown
it accepts good input.

Run: uv run pytest -q tests/audit_ip_guard_test.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECKER = REPO_ROOT / "scripts" / "check_audit_ip.py"

#: What a handler used to look like, and what the sweep replaced 80 times.
OFFENDING_HANDLER = """
from fastapi import Request


async def record_something(request: Request) -> None:
    await write_audit(
        action="thing.done",
        ip=request.client.host if request.client else None,
    )
"""

#: The predicate the allowance names. Copied in shape, not imported, because the doctored
#: tree must stand alone — importing the real one would test the real one.
PERMITTED_RESOLVER = '''
from fastapi import Request


def client_request_ip(request: Request) -> str | None:
    """The ONE permitted read: the peer is an ARGUMENT to the trusted-proxy predicate."""
    return client_ip(
        request.client.host if request.client else None,
        request.headers,
        app_env="prod",
    )
'''

CLEAN_HANDLER = """
from fastapi import Request

from apps.api.core.auth import client_request_ip


async def record_something(request: Request) -> None:
    await write_audit(action="thing.done", ip=client_request_ip(request))
"""


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    """Run a COPY of the checker rooted at `root` — it locates its scope from `__file__`."""
    scripts = root / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "check_audit_ip.py").write_text(CHECKER.read_text(encoding="utf-8"))
    return subprocess.run(
        [sys.executable, str(scripts / "check_audit_ip.py")],
        capture_output=True,
        text=True,
        check=False,
    )


def _tree(root: Path, *, resolver: str, extra: dict[str, str] | None = None) -> None:
    core = root / "apps" / "api" / "core"
    core.mkdir(parents=True, exist_ok=True)
    (core / "auth.py").write_text(resolver)
    for relative, body in (extra or {}).items():
        path = root / "apps" / "api" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)


def test_the_real_tree_passes() -> None:
    """First, because a checker that rejects everything also rejects the defect."""
    result = subprocess.run(
        [sys.executable, "-m", "scripts.check_audit_ip"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "AUDIT IP: OK" in result.stdout


def test_a_faithful_copy_of_a_clean_tree_passes(tmp_path: Path) -> None:
    """Proves the doctored trees below differ from a clean one only in the defect, and
    not in some accident of how they are assembled."""
    _tree(tmp_path, resolver=PERMITTED_RESOLVER, extra={"admin/routes.py": CLEAN_HANDLER})
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout


def test_a_handler_reading_the_socket_peer_is_refused(tmp_path: Path) -> None:
    """The defect returning: one route, one inline peer read, eighty of which is what
    this guard exists because of."""
    _tree(tmp_path, resolver=PERMITTED_RESOLVER, extra={"admin/routes.py": OFFENDING_HANDLER})
    result = _run(tmp_path)
    assert result.returncode == 1, result.stdout
    assert "AUDIT IP: FAIL" in result.stdout
    assert "apps/api/admin/routes.py" in result.stdout
    assert "record_something" in result.stdout, "the message must name the function"
    assert "client_request_ip" in result.stdout, "and the remedy"


def test_the_allowance_dies_with_the_function_it_was_granted_for(tmp_path: Path) -> None:
    """The subtler loss. If `client_request_ip` stops resolving the caller, the guard
    would otherwise pass a tree in which NOTHING decides the audit ip — a green check
    over an absent guarantee, which is worse than a red one.
    """
    simplified = "def client_request_ip(request):\n    return None\n"
    _tree(tmp_path, resolver=simplified, extra={"admin/routes.py": CLEAN_HANDLER})
    result = _run(tmp_path)
    assert result.returncode == 1, result.stdout
    assert "no longer reads" in result.stdout
    assert "outlives its reason" in result.stdout


def test_the_permitted_read_is_bound_to_its_function_not_its_file(tmp_path: Path) -> None:
    """Moving the peer read one function down in the same file is not the exception that
    was granted. Without this, `core/auth.py` would be a file-wide hole."""
    smuggled = (
        PERMITTED_RESOLVER
        + """

async def some_other_handler(request):
    await write_audit(action="x", ip=request.client.host if request.client else None)
"""
    )
    _tree(tmp_path, resolver=smuggled)
    result = _run(tmp_path)
    assert result.returncode == 1, result.stdout
    assert "some_other_handler" in result.stdout


@pytest.mark.parametrize("mention", ["docstring", "comment"])
def test_prose_naming_the_pattern_is_not_a_finding(tmp_path: Path, mention: str) -> None:
    """`core/auth.py` explains this rule in prose that contains the banned expression,
    and `check_model_residency` had to learn the same lesson about its own docstring. AST
    rather than grep is what makes that free."""
    body = (
        '"""Handlers must not write ip=request.client.host if request.client else None."""\n'
        if mention == "docstring"
        else "# never write ip=request.client.host if request.client else None here\n"
    )
    _tree(tmp_path, resolver=PERMITTED_RESOLVER, extra={"admin/routes.py": body + CLEAN_HANDLER})
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout
