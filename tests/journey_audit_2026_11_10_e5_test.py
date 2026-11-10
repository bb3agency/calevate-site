"""Journey audit E5 (10 Nov 2026): an operator's day, followed through the runbooks.

Each test names the failure it guards against and failed on the tree before its fix.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from uuid import UUID

import pytest
from apps.api.compliance.processor_erasure import OVERDUE_AFTER_DAYS, open_tasks_for_request
from apps.api.db.session import tenant_session
from sqlalchemy import text
from tests.processor_erasure_test import _REAL_EXECUTION_ID
from tests.processor_erasure_test import _tenant as _erasure_tenant

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


@pytest.mark.rls
async def test_the_vendor_erasure_page_names_the_tenants_its_command_needs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """E5-04. `processor_erasure_overdue` sends the operator to `scripts.processor_erasure`,
    which refuses to run without `--tenant` (the tasks are FORCE-RLS'd), while the page said
    only "across N tenant(s)" and the runbook printed the command without `--tenant`. The
    operator could not run the step the page pointed at."""
    from apps.workers import dispatcher

    raised: list[tuple[str, dict[str, object]]] = []

    def _capture(stage: str, code: str, detail: str = "", **ids: object) -> None:
        del stage, detail
        raised.append((code, ids))

    tenant_id = await _erasure_tenant()

    async def _one() -> list[UUID]:
        return [tenant_id]

    monkeypatch.setattr(dispatcher, "alert", _capture)
    monkeypatch.setattr(dispatcher, "_all_tenants", _one)
    async with tenant_session(tenant_id) as session:
        await open_tasks_for_request(
            session,
            tenant_id=tenant_id,
            request_ref=uuid.uuid4(),
            request_kind="subject",
            subject_ref="e5",
            vendor_refs=[_REAL_EXECUTION_ID],
            processors=("voice_engine",),
        )
        await session.execute(
            text(
                "UPDATE processor_erasure_tasks SET opened_at = now() - "
                "make_interval(days => :d) WHERE tenant_id = :t"
            ),
            {"d": OVERDUE_AFTER_DAYS + 1, "t": tenant_id},
        )

    await dispatcher.report_overdue_erasures({})

    pages = [ids for code, ids in raised if code == "processor_erasure_overdue"]
    assert pages, "an unanswered vendor erasure obligation must page"
    assert pages[0].get("tenant_1") == str(tenant_id)


def test_the_runbooks_run_the_vendor_erasure_script_with_its_tenant() -> None:
    from scripts import processor_erasure

    commands = [
        line.split("scripts.processor_erasure", 1)[1].split()
        for book in ("processor-erasure.md", "alarm-index.md")
        for line in (RUNBOOKS / book).read_text(encoding="utf-8").splitlines()
        if "python -m scripts.processor_erasure " in line
    ]
    assert commands
    for argv in commands:
        assert argv[:1] == ["--tenant"], f"runbook runs the script without --tenant: {argv}"
    with pytest.raises(SystemExit) as refused:
        processor_erasure.main(["list"])
    assert refused.value.code == 2
