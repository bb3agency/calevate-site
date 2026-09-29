"""An operator's write and its audit row commit together, or neither does.

`write_audit` appends IN THE CALLER'S TRANSACTION so that "the audit row and the thing it
describes commit together". The admin handlers used to run the mutation inside
`tenant_session(tenant_id)` — which commits on exit — and write the audit afterwards on
the request's admin session, a second transaction. An audit write that failed there (the
chain lock's statement timeout, a dropped connection) left a committed mutation with no
row: a suspended business, a recorded KYC verdict, a bought number, none attributable.

Two shapes, pinned separately:

* **A pure database write** puts the audit row in the mutation's own transaction. A failing
  audit rolls the mutation back; a succeeding one commits both.
* **A vendor purchase cannot be rolled back**, so the request is audited and committed
  BEFORE the vendor is called, and the outcome row is written under a savepoint in the
  purchase's transaction (BACKEND-PATTERNS §4). A failed intent row buys nothing; a failed
  outcome row still keeps the purchase record.

Run: uv run pytest -q tests/admin_audit_atomicity_test.py
"""

from __future__ import annotations

import uuid
from typing import Any, ClassVar
from uuid import UUID

import pytest
from apps.api.admin import number_routes
from apps.api.compliance import audit as audit_module
from apps.api.core.context import Principal
from apps.api.db.session import tenant_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.commercial_terms_test import _make_admin, _tenant
from tests.number_supply_test import _offer, authorized  # noqa: F401 - pytest fixture
from tests.number_supply_test import _tenant as _buyable_tenant

pytestmark = [pytest.mark.rls]


class _AuditRefusedError(Exception):
    """What the chain lock's statement timeout looks like to a caller: an exception."""


def _refuse_audit(monkeypatch: pytest.MonkeyPatch, module: Any, *, only: str | None = None) -> None:
    real = audit_module.write_audit

    async def _write(session: Any, **kwargs: Any) -> None:
        if only is None or kwargs.get("action") == only:
            raise _AuditRefusedError(kwargs.get("action"))
        await real(session, **kwargs)

    monkeypatch.setattr(module, "write_audit", _write)


async def _status_of(tenant_id: UUID) -> str:
    async with tenant_session(tenant_id) as session:
        return str(
            (
                await session.execute(
                    text("SELECT status FROM organizations WHERE id = :t"), {"t": tenant_id}
                )
            ).scalar()
        )


async def _audit_actions(tenant_id: UUID, prefix: str) -> list[str]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT action FROM audit_log WHERE tenant_id = :t AND action LIKE :p "
                    "ORDER BY at, id"
                ),
                {"t": tenant_id, "p": f"{prefix}%"},
            )
        ).all()
    return [str(row[0]) for row in rows]


async def _suspend(token: str, tenant_id: UUID) -> Any:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://api") as http:
        return await http.post(
            f"/v1/admin/tenants/{tenant_id}/status",
            headers={"Authorization": f"Bearer {token}"},
            json={"status": "suspended", "reason": "complaints under review"},
        )


# ------------------------------------------------------------ a pure database write


async def test_a_suspension_and_its_audit_row_commit_together() -> None:
    tenant_id = await _tenant()
    token = await _make_admin("operator")

    response = await _suspend(token, tenant_id)

    assert response.status_code == 200, response.text
    assert await _status_of(tenant_id) == "suspended"
    assert await _audit_actions(tenant_id, "tenant.") == ["tenant.suspended"]


async def test_a_suspension_whose_audit_row_fails_does_not_happen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.admin import routes as admin_routes

    tenant_id = await _tenant()
    token = await _make_admin("operator")
    before = await _status_of(tenant_id)
    _refuse_audit(monkeypatch, admin_routes)

    response = await _suspend(token, tenant_id)

    assert response.status_code >= 500, response.text
    assert await _status_of(tenant_id) == before, (
        "the business was suspended and nothing on the audit ledger says who did it"
    )
    assert await _audit_actions(tenant_id, "tenant.") == []


# ------------------------------------------------------------ a vendor purchase


class _Req:
    client = None
    headers: ClassVar[dict[str, str]] = {}


async def _principal() -> Principal:
    token = await _make_admin("superadmin")
    return Principal(
        realm="admin",
        user_id=UUID(token.rsplit(":", 1)[1]),
        tenant_id=None,
        role="superadmin",
        impersonating=False,
    )


async def _buy(tenant_id: UUID, offer: Any) -> Any:
    return await number_routes.buy_number(
        tenant_id,
        number_routes.BuyNumberIn(
            e164=offer.e164,
            country="IN",
            provider=offer.provider,
            monthly_price_usd=offer.monthly_price_usd,
            purpose="reception",
        ),
        None,  # type: ignore[arg-type] - the admin session is not what this writes through
        _Req(),  # type: ignore[arg-type]
        await _principal(),
    )


async def _numbers(tenant_id: UUID) -> int:
    async with tenant_session(tenant_id) as session:
        return int(
            (await session.execute(text("SELECT count(*) FROM phone_numbers"))).scalar() or 0
        )


async def test_a_purchase_is_audited_before_and_after(authorized: None) -> None:  # noqa: F811
    tenant_id = await _buyable_tenant()
    offer = await _offer(uuid.uuid4().hex[:6])

    await _buy(tenant_id, offer)

    assert await _numbers(tenant_id) == 1
    assert await _audit_actions(tenant_id, "number.") == [
        "number.buy_requested",
        "number.bought",
    ]


async def test_nothing_is_bought_when_the_request_cannot_be_audited(
    authorized: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = await _buyable_tenant()
    offer = await _offer(uuid.uuid4().hex[:6])
    _refuse_audit(monkeypatch, number_routes, only="number.buy_requested")

    with pytest.raises(_AuditRefusedError):
        await _buy(tenant_id, offer)

    assert await _numbers(tenant_id) == 0, "a number was bought with no audit row at all"


async def test_a_failed_outcome_row_keeps_the_purchase_record(
    authorized: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The money is spent by the time the outcome row is written, so losing that row must
    not lose the record of the number we now rent — and the request row already names who
    asked for it."""
    tenant_id = await _buyable_tenant()
    offer = await _offer(uuid.uuid4().hex[:6])
    _refuse_audit(monkeypatch, number_routes, only="number.bought")

    await _buy(tenant_id, offer)

    assert await _numbers(tenant_id) == 1
    assert await _audit_actions(tenant_id, "number.") == ["number.buy_requested"]


# ------------------------------------------------------------ the census


def _audits_written_after_the_mutation_committed() -> list[str]:
    """Every handler that closes a `tenant_session` block and THEN writes an audit row on
    some other session — the shape both tests above exist for, found by reading the code
    rather than by remembering which handlers to test."""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    found: list[str] = []
    for path in sorted((root / "apps" / "api").rglob("*.py")):
        if path.name.endswith("_test.py"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.AsyncFunctionDef):
                continue
            blocks = [
                (node.lineno, node.end_lineno or node.lineno, item.optional_vars.id)
                for node in ast.walk(fn)
                if isinstance(node, ast.AsyncWith)
                for item in node.items
                if isinstance(item.context_expr, ast.Call)
                and getattr(item.context_expr.func, "id", "") == "tenant_session"
                and isinstance(item.optional_vars, ast.Name)
            ]
            if not blocks:
                continue
            scoped = {name for _, _, name in blocks}
            for node in ast.walk(fn):
                if not (
                    isinstance(node, ast.Call)
                    and getattr(node.func, "id", "") == "write_audit"
                    and node.args
                    and isinstance(node.args[0], ast.Name)
                ):
                    continue
                if node.args[0].id in scoped:
                    continue
                if any(end < node.lineno for _, end, _ in blocks):
                    rel = path.relative_to(root).as_posix()
                    found.append(f"{rel}::{fn.name}")
    return found


def test_no_handler_audits_a_mutation_after_committing_it() -> None:
    offenders = _audits_written_after_the_mutation_committed()
    assert offenders == [], (
        f"{offenders} commit a `tenant_session` block and then write the audit row on "
        "another session, so a failing audit leaves the change unattributed. Write it on "
        "the block's own session, inside the block, as its last statement."
    )
