"""No email writes the product name or the domain itself; each comes from one place (D-933).

The rename (docs/REBRAND-MAP.md) changes the name in `core/brand.PRODUCT` and the domain in
`core/console_links.DOMAIN`. A literal "Calevate" or "calevate.tech" in an email module
would survive that change and go out under the old name, so this reads every string an
email module holds (docstrings and comments aside) and refuses both.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from apps.api.core import brand, console_links

REPO = Path(__file__).resolve().parents[1]

#: Modules that compose an email's words but do not call the transport themselves.
COMPOSERS: tuple[str, ...] = (
    "apps/api/core/alert_email.py",
    "apps/api/core/email_layout.py",
    "apps/api/healer/notices.py",
    "apps/workers/email_render.py",
)

_NAME = re.compile(r"Calevate")
_DOMAIN = re.compile(r"calevate\.tech", re.IGNORECASE)


def _email_modules() -> list[str]:
    found = set(COMPOSERS)
    for root in ("apps/api", "apps/workers"):
        for path in (REPO / root).rglob("*.py"):
            rel = path.relative_to(REPO).as_posix()
            if rel.endswith("_test.py") or rel == "apps/api/core/transport.py":
                continue
            source = path.read_text(encoding="utf-8")
            if "get_transport(" in source and _sends(ast.parse(source)):
                found.add(rel)
    return sorted(found)


def _sends(tree: ast.AST) -> bool:
    """A real call, not a module that only mentions the transport in a comment."""
    return any(
        isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == "get_transport")
            or (isinstance(node.func, ast.Attribute) and node.func.attr == "get_transport")
        )
        for node in ast.walk(tree)
    )


def _docstrings(tree: ast.AST) -> set[int]:
    """Every bare string statement: docstrings, and the attribute-doc strings this repo puts
    under an assignment. Neither is ever sent."""
    return {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
    }


def _offending_strings(source: str) -> list[tuple[int, str]]:
    tree = ast.parse(source)
    skip = _docstrings(tree)
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in skip
        and (_NAME.search(node.value) or _DOMAIN.search(node.value))
    ]


def test_the_guard_sees_the_email_modules() -> None:
    """The premise: an empty module list would pass every check below vacuously."""
    modules = _email_modules()
    assert "apps/workers/notifications.py" in modules
    assert "apps/workers/auth_email.py" in modules
    assert len(modules) >= 15


def test_the_guard_catches_a_literal() -> None:
    """FAILS IF: the detector stops seeing the shapes it exists for."""
    sample = 'A = "Your Calevate code"\nB = f"https://app.calevate.tech/{x}"\n"""Calevate."""\n'
    assert [line for line, _ in _offending_strings(sample)] == [1, 2]


@pytest.mark.parametrize("rel", _email_modules())
def test_no_email_module_writes_the_name_or_the_domain(rel: str) -> None:
    found = _offending_strings((REPO / rel).read_text(encoding="utf-8"))
    assert not found, (
        f"{rel} writes the brand or the domain itself: {found}. Use `brand.PRODUCT`, "
        "`brand.DOMAIN` or a `console_links` host."
    )


def test_the_hosts_are_built_from_the_one_domain() -> None:
    assert f"https://app.{console_links.DOMAIN}" == console_links.CONSOLE_BASE
    assert f"https://admin.{console_links.DOMAIN}" == console_links.ADMIN_CONSOLE_BASE
    assert brand.DOMAIN == console_links.DOMAIN
    assert brand.LOGO_URL.startswith(f"https://app.{brand.DOMAIN}/")


def test_the_logo_the_mail_links_to_is_a_file_the_web_app_serves() -> None:
    path = brand.LOGO_URL.removeprefix(f"https://app.{brand.DOMAIN}/")
    assert (REPO / "apps/web/public" / path).is_file(), path


def test_the_default_sender_is_on_the_one_domain() -> None:
    """`notifications_from` is defaulted in `calevate_shared`, which cannot import
    `console_links`; this keeps the two from naming different domains."""
    from calevate_shared.config import Settings

    default = Settings.model_fields["notifications_from"].default
    assert isinstance(default, str) and default.endswith(f"@{console_links.DOMAIN}")
