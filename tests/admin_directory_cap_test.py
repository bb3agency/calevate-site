"""The client directory's `capped` badge, and the month it was not reading.

`spend_state.capped` is armed by exactly one writer — the post-call meter — and cleared
by the two recomputes. Its month is part of the QUESTION, not decoration:
`compliance.spend_capped` reads `capped` AND `month` because a capped outbound-only
tenant meters nothing, so the flag cannot clear itself and a tenant capped in July would
otherwise be refused every dial in August, forever (`tests/spend_cap_staleness_test.py`
holds that argument for the gate).

The directory did not ask that question. `admin.service.tenant_overview` read
`(SELECT capped FROM spend_state LIMIT 1)` — the same COLUMN, a different PREDICATE — so
the operator's roster could show a red "capped" badge beside a client the dial gate was
happily dialling for, with nothing on the screen to say which of the two was right. The
console's most-read admin surface disagreeing with the refusal a client is (not) seeing
is worse than either answer alone, because it is the screen an operator uses to decide
whether to believe a client's complaint.

The fix is not a patched predicate: the directory now ASKS `spend_capped`, the same
function `admin/health.py` already asks, so there is ONE definition of "capped this
month" across every admin surface. These tests pin the property from both ends —

1. a closed month's flag is not a badge, in the directory and at the gate alike;
2. a live cap still IS one, so the fix cannot be satisfied by never reporting a cap;
3. and the two are asserted TOGETHER in one test, because "the directory agrees with the
   gate" is the property, and two separate assertions can both drift and still pass.

CONCURRENCY: every case mints its own tenant and asserts only on that tenant's row, so
this file runs beside the other suites on the shared Postgres.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing.service import current_billing_month
from apps.api.compliance.service import spend_capped
from apps.api.db.session import admin_session, tenant_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text


def _last_month() -> str:
    """The IST billing month before this one, rolled across the year boundary."""
    year, month = (int(part) for part in current_billing_month().split("-"))
    return f"{year - 1}-12" if month == 1 else f"{year}-{month - 1:02d}"


async def _tenant_capped_in(month: str | None) -> UUID:
    """A live tenant whose `spend_state` row is stamped with `month` and capped.

    `None` seeds no row at all — a client who has never metered anything, which is what
    every freshly onboarded account looks like.
    """
    created = await admin_service.create_organization(
        name="Cap Directory Motors",
        slug=f"capdir-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = UUID(str(created["id"]))
    if month is not None:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "INSERT INTO spend_state (tenant_id, month, minutes_used, spend_used, "
                    "capped, created_at, updated_at) VALUES (:t, :m, 500, "
                    "CAST(:s AS numeric), true, now(), now())"
                ),
                {"t": tenant_id, "m": month, "s": Decimal("5000.0000")},
            )
    return tenant_id


async def _directory_row(tenant_id: UUID) -> dict[str, Any]:
    """The client's row as the console reads it — through the same narrowing the detail
    screen uses, on the admin-realm session the route holds."""
    async with admin_session() as session:
        rows = await admin_service.tenant_overview(session, tenant_id=tenant_id)
    assert len(rows) == 1, f"expected one directory row, got {len(rows)}"
    return rows[0]


async def _gate_says_capped(tenant_id: UUID) -> bool:
    async with tenant_session(tenant_id) as session:
        return await spend_capped(session, tenant_id=tenant_id)


# ============================================================================
# The property: the directory asks the gate's question
# ============================================================================


@pytest.mark.parametrize(
    ("month_label", "month", "capped"),
    [
        # The defect. Before the fix this row read `capped: True` while the gate dialled.
        ("a closed month", "last", False),
        # The control. Without it, "never report a cap" would pass the case above.
        ("the current month", "this", True),
        # A client who has metered nothing has no row, and no row is not a cap.
        ("no spend_state row at all", None, False),
    ],
)
async def test_the_directory_reports_exactly_what_the_dial_gate_decides(
    month_label: str, month: str | None, capped: bool
) -> None:
    """One test for both halves on purpose: the badge and the refusal are the same fact,
    and asserting them apart is how they drifted in the first place."""
    stamp = {"last": _last_month(), "this": current_billing_month()}.get(month or "")
    tenant_id = await _tenant_capped_in(stamp if month else None)

    row = await _directory_row(tenant_id)
    gate = await _gate_says_capped(tenant_id)

    assert gate is capped, f"the gate's own answer changed for {month_label}"
    assert row["capped"] is capped, (
        f"the directory says capped={row['capped']} for {month_label} while the dial gate "
        f"says {gate} — an operator reading this screen has no way to tell which is true"
    )


async def test_the_badge_on_the_wire_is_the_same_answer() -> None:
    """End to end, because the defect was visible on a SCREEN.

    `TenantSummary.capped` is what the console paints red, so the property is asserted
    through `GET /v1/admin/tenants/{id}` and not only through the service — a response
    model that stopped carrying this field, or a route that recomputed it, would pass the
    tests above and still show the badge.
    """
    stale = await _tenant_capped_in(_last_month())
    live = await _tenant_capped_in(current_billing_month())
    clerk_id = f"admin_{uuid.uuid4().hex[:12]}"
    async with admin_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, clerk_user_id, name, role, created_at, updated_at) "
                "VALUES (:id, :cid, 'Ops', 'operator', now(), now())"
            ),
            {"id": uuid.uuid4(), "cid": clerk_id},
        )

    headers = {"Authorization": f"Bearer dev:admin:{clerk_id}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        stale_response = await http.get(f"/v1/admin/tenants/{stale}", headers=headers)
        live_response = await http.get(f"/v1/admin/tenants/{live}", headers=headers)

    assert stale_response.status_code == 200, stale_response.text
    assert live_response.status_code == 200, live_response.text
    assert stale_response.json()["capped"] is False, (
        "a client capped in a closed month is not capped now, and the badge said they were"
    )
    assert live_response.json()["capped"] is True
