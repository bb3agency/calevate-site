"""The client directory stops asking the hold gates about accounts they never apply to.

`admin.service.tenant_overview` is N+1 by construction and says so: the directory comes
from an `app.admin` session, the counters from a per-tenant RLS session, because
`app.admin` does not unlock `calls` or `leads` and should not. That trade is recorded and
is not what this file is about.

What this file is about is the CONSTANT. Measured on a 312-account directory, an account
cost 3.3 ms and the largest single term — 0.95 ms, larger than the four counts together —
was `read_tenant_holds`. Each blocker opens with `plan_tier_of(...) not in
SELF_SERVE_TIERS -> None`, so for a `managed` account the WHOLE call is two `SELECT
plan_tier FROM organizations` round trips that cannot change the answer — re-reading, per
account, a column this loop already holds on the directory row.

`admin/holds.py::held_tenants` — the WORK QUEUE built from the same predicate — has
always pre-filtered its candidate set by exactly this tier line, and argues at length why
that is a filter on the candidates and not a second copy of the rule. The directory did
not, so the two surfaces disagreed about which accounts can even be held. That older
defect is the one underneath the slow one, and it is what these tests pin.

Both properties matter and they pull against each other, so both are here:

1. a self-serve account still gets its holds ASKED, from the gates themselves;
2. a managed account is not asked, and answers the same empty tuple it always did.

CONCURRENCY: every case mints its own tenant and narrows the directory to it.
"""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

from apps.api.admin import service as admin_service
from apps.api.admin.holds import NO_HOLDS, read_tenant_holds
from apps.api.compliance.service import SELF_SERVE_TIERS
from apps.api.db.session import admin_session, get_engine, tenant_session
from sqlalchemy import event, text


async def _tenant(plan_tier: str) -> UUID:
    created = await admin_service.create_organization(
        name="Holds Prefilter Motors",
        slug=f"holdpf-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = UUID(str(created["id"]))
    if plan_tier != "managed":
        # The tier is a property of the organization row, and `create_organization`
        # writes `managed`. Changed through the tenant's own session, which is the only
        # one whose policy admits an UPDATE of its own row.
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE organizations SET plan_tier = :tier WHERE id = :id"),
                {"tier": plan_tier, "id": tenant_id},
            )
    return tenant_id


async def _directory_row(tenant_id: UUID) -> dict[str, Any]:
    async with admin_session() as session:
        rows = await admin_service.tenant_overview(session, tenant_id=tenant_id)
    assert len(rows) == 1, f"expected one directory row, got {len(rows)}"
    return rows[0]


async def test_a_self_serve_account_is_still_asked_and_still_reports_its_holds() -> None:
    """The half a pre-filter is most likely to break, so it is asserted first.

    A brand-new self-serve account is held by BOTH gates — `kyc_blocker` fails closed to
    held when no record exists, and `first_campaign_hold_blocker` answers "nobody has
    looked yet". A pre-filter that excluded one tier too many would drop exactly this
    account off the operator's roster, which is the failure the hold queue exists to
    prevent.

    The expected value is read from `read_tenant_holds` itself rather than written out
    here, because the claim is "the directory says what the gates say" and a hardcoded
    rule list would be a third copy of the predicate.
    """
    tenant_id = await _tenant(SELF_SERVE_TIERS[0])

    async with tenant_session(tenant_id) as session:
        expected = await read_tenant_holds(session, tenant_id=tenant_id)

    assert expected.held, "fixture is not held; the assertion below would prove nothing"
    row = await _directory_row(tenant_id)
    assert tuple(row["holds"]) == expected.rules, (
        "the directory disagrees with the gates about a self-serve account — the "
        "pre-filter excluded a tier that can be held"
    )


async def test_a_managed_account_is_not_asked_and_answers_the_same_empty_holds() -> None:
    """RED WITHOUT THE FIX, and red for the right reason.

    The observable behaviour is unchanged by design — both blockers already answer `None`
    for a managed tier — so an assertion on `row["holds"]` alone would pass either way.
    What changed is the WORK, so the work is what is counted.

    **The statement to count is `plan_tier_of`'s, not the compliance tables'.** A managed
    account never reaches `kyc_records` or `first_campaign_reviews`: each blocker returns
    on its first line, having spent one `SELECT plan_tier FROM organizations` to learn
    something the directory row already carried. An earlier version of this test counted
    the compliance tables and stayed green under sabotage for exactly that reason — a
    probe aimed one layer past the work.

    Counted at the driver, over every statement the call makes, because the blockers are
    two functions deep and a probe that patched them would be asserting on its own patch.
    """
    tenant_id = await _tenant("managed")

    engine = get_engine().sync_engine
    seen: list[str] = []

    def _capture(
        _conn: Any, _cursor: Any, statement: str, *_args: Any, **_kwargs: Any
    ) -> None:  # pragma: no cover - trivial
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", _capture)
    try:
        row = await _directory_row(tenant_id)
    finally:
        event.remove(engine, "before_cursor_execute", _capture)

    assert tuple(row["holds"]) == NO_HOLDS.rules, "a managed account reported a hold"

    assert seen, "no statements were captured — the probe is watching the wrong engine"
    tier_reads = [s for s in seen if "SELECT plan_tier FROM organizations" in s]
    assert not tier_reads, (
        "the directory still asks the blockers for a managed account, whose tier no "
        "blocker applies to — and each of them re-reads `plan_tier`, the column the "
        f"directory row already carries. {len(tier_reads)} statement(s): {tier_reads}"
    )
    # The tables the blockers would have gone on to read. Unreachable for a managed tier
    # either way, asserted so the claim above cannot be satisfied by a change that skips
    # the tier read and reads the records anyway.
    assert not [s for s in seen if "kyc_records" in s or "first_campaign_reviews" in s]


def test_the_tier_line_is_imported_and_not_re_spelled() -> None:
    """One place decides which tiers can be held, and it is not this surface.

    `held_tenants` makes the same argument about its own use of the constant: a
    pre-filter on the CANDIDATE SET is not a second copy of the RULE, and stays true only
    while both surfaces read the line from `compliance/service.py`. A literal
    `("self_serve", "trial")` in `admin/service.py` would be the drift the gates are
    written to prevent, and it would be invisible until the day the line moves.
    """
    import inspect

    source = inspect.getsource(admin_service.tenant_overview)
    assert "SELF_SERVE_TIERS" in source, "the directory no longer names the shared constant"
    assert "self_serve" not in source, (
        "the tier line is spelled out in the directory as well as in compliance/service.py"
    )
