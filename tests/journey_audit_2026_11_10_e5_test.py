"""Journey audit E5 (10 Nov 2026): an operator's day, followed through the runbooks.

Each test names the failure it guards against and failed on the tree before its fix.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "apps" / "web" / "src" / "app"
RUNBOOKS = ROOT / "runbooks"

# A console path written as code in a runbook: `/admin/...`, `/c/<slug>/...`, `/auth/...`.
_CONSOLE_PATH = re.compile(r"`(/(?:admin|c|auth)(?:/[^`\s?#]*)?)(?:[?#][^`]*)?`")
# How a runbook writes a path parameter: `<tenantId>`, `{tenant_id}`, `[id]`.
_PLACEHOLDER = re.compile(r"^(<[^>]+>|\{[^}]+\}|\[[^\]]+\])$")


def _page_patterns() -> set[tuple[str, ...]]:
    """Every page the App Router serves, as segments; a dynamic segment is `*`.

    Route groups (`(auth)`) contribute no URL segment."""
    patterns = set()
    for page in APP_DIR.rglob("page.tsx"):
        segments = []
        for part in page.relative_to(APP_DIR).parent.parts:
            if part.startswith("(") and part.endswith(")"):
                continue
            segments.append("*" if part.startswith("[") else part)
        patterns.add(tuple(segments))
    return patterns


def _served(path: str, patterns: set[tuple[str, ...]]) -> bool:
    wanted = [segment for segment in path.strip("/").split("/") if segment]
    for pattern in patterns:
        if len(pattern) != len(wanted):
            continue
        # A placeholder only matches a dynamic segment, and a literal only a literal, so a
        # wrong literal cannot pass by landing on `[tenantId]`.
        if all(
            (have == "*") == bool(_PLACEHOLDER.match(want)) and (have == "*" or have == want)
            for have, want in zip(pattern, wanted, strict=True)
        ):
            return True
    return False


def test_every_console_path_a_runbook_names_is_a_page() -> None:
    """E5-01. `alarm-index.md` is quoted into every alarm email at send time
    (`core/alarm_guide`). Three money pages (`payment_dispute_opened`,
    `platform_fee_payment_disputed`, `payment_dispute_action_required`) told the operator to
    open `/admin/payments/disputes`, which no page serves; disputes live on `/admin/payments`.
    """
    patterns = _page_patterns()
    missing = sorted(
        f"{book.name}: {path}"
        for book in RUNBOOKS.glob("*.md")
        for path in _CONSOLE_PATH.findall(book.read_text(encoding="utf-8"))
        if not _served(path.rstrip(".,;:"), patterns)
    )
    assert not missing, f"runbooks name console paths no page serves: {missing}"


def test_the_resolver_refuses_a_wrong_literal_and_accepts_a_placeholder() -> None:
    patterns = _page_patterns()
    assert _served("/admin/tenants/<tenantId>/credits", patterns)
    assert _served("/admin/payments", patterns)
    assert not _served("/admin/payments/disputes", patterns)
    assert not _served("/admin/tenants/credits", patterns)
