"""Round three of the schema-hardening work: one constraint still refused, one hole closed.

Two unrelated things share this file because they share a discipline — measure the
database before believing a docstring, and write the property down in the words the
person who has to defend it would use.

1. **The credit-ledger unique index is STILL not here**, and this file records the
   measurement that says why, naming the one fixture that now stands in the way.
2. **The retention sweep's leads hole is closed at the ingest end**, and the tests below
   are the compliance sentence — no personal data enters the platform that the retention
   sweep cannot later expire — expressed as things that either happen or do not.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing.service import record_entry
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import reset_engine_cache
from apps.api.ingest.routes import SECRET_HEADER
from apps.api.main import app
from apps.workers.retention import _due_tenants, sweep_tenant
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

SECRET = "ingest-secret-for-tests"


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the compliance gate's clock to 11:00 IST, as `lead_ingest_test` does.

    Outside calling hours the gate refuses every dial, which is the gate working — and
    which would make the tests below pass for the wrong reason.
    """
    fixed = datetime(2026, 8, 11, 5, 30, tzinfo=UTC) + timedelta(hours=5, minutes=30)
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: fixed)


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _tenant_with_source(
    *, published: bool, consent_field: bool
) -> tuple[uuid.UUID, uuid.UUID]:
    """(tenant_id, webhook_id).

    `published` is the whole variable under test: it decides whether `publish_agent`'s
    two writes — `agents.engine_agent_ref` and the `engine_agent_routes` row — exist.
    They are made together here because production makes them together, in one
    transaction; a fixture that wrote one without the other would be testing a state the
    platform cannot reach.
    """
    reset_engine_cache()
    created = await admin_service.create_organization(
        name="Hardening Homes",
        slug=f"sh3-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    webhook_id = uuid.uuid4()
    ref = f"fakeagent_sh3_{uuid.uuid4().hex[:8]}"

    mapping: dict[str, str] = {"phone": "phone_number", "name": "full_name"}
    if consent_field:
        mapping["consent_field"] = "consent"

    async with tenant_session(tenant_id) as session:
        if published:
            await session.execute(
                text(
                    "UPDATE agents SET status = 'live', direction = 'outbound', "
                    "engine_agent_ref = :r WHERE id = :a"
                ),
                {"r": ref, "a": agent_id},
            )
        await session.execute(
            text(
                "INSERT INTO inbound_webhooks (id, tenant_id, source, secret_ref, agent_id, "
                "mapping, active, created_at, updated_at) VALUES (:i, :t, 'website_form', :s, "
                ":a, CAST(:m AS jsonb), true, now(), now())"
            ),
            {
                "i": webhook_id,
                "t": tenant_id,
                "s": SECRET,
                "a": agent_id,
                "m": json.dumps(mapping),
            },
        )
    if published:
        async with untenanted_session() as session:
            await session.execute(
                text(
                    "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, "
                    "agent_id, active, created_at, updated_at) VALUES ('fake', :r, :t, :a, true, "
                    "now(), now())"
                ),
                {"r": ref, "t": tenant_id, "a": agent_id},
            )
    return tenant_id, webhook_id


async def _leads(tenant_id: uuid.UUID) -> list[dict[str, object]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT id, phone_e164, name, data FROM leads WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
        ).mappings()
        return [dict(row) for row in rows]


# ============================================================ 1. the retention leads hole
#
# THE PROPERTY, in a compliance reviewer's words:
#
#   Every retention policy this platform sells is enforced by one nightly job. That job
#   can only sweep a tenant it can find, and it finds tenants through `engine_agent_routes`
#   — the global routing table — because a cross-tenant lookup must not need the admin
#   database role (hard rule 1). So the promise "leads are erased after N days" is only
#   true of tenants that appear in that table.
#
#   NO PERSONAL DATA MAY ENTER THE PLATFORM THAT THE SWEEP CANNOT LATER EXPIRE.
#
# Calls satisfy this by construction: a call row only exists for a published agent, and
# publishing is what writes the route. Leads did not — the webhook ingest path wrote the
# lead BEFORE the dial, so a tenant that had never published an agent could keep one and
# be invisible to the sweep forever. The three tests below are that sentence: the door is
# shut, the door is shut for the right reason, and what comes through the open door is
# reachable.


async def test_a_lead_is_refused_when_no_sweep_could_ever_reach_it() -> None:
    """An unpublished agent means no route, no route means no sweep, no sweep means a
    phone number kept past its TTL with nothing able to remove it. So the lead is
    refused at the door instead — and NOTHING is left behind.

    This is not a new rule: `dispatch_call` has always refused an unpublished agent with
    this exact code. It used to refuse AFTER the lead row was written, which is why the
    outcome depended on which exit the request took.
    """
    tenant_id, webhook_id = await _tenant_with_source(published=False, consent_field=False)

    async with _client() as http:
        response = await http.post(
            f"/hooks/v1/ingest/{webhook_id}",
            json={"phone_number": "9876540001", "full_name": "Anand"},
            headers={SECRET_HEADER: SECRET},
        )

    assert response.status_code == 422, response.text
    assert response.json()["type"].endswith("/agent_not_published")
    assert await _leads(tenant_id) == [], "a refused ingest must leave no personal data behind"


async def test_the_blocked_path_leaves_nothing_behind_either() -> None:
    """The exit that actually produced the orphans.

    A lead that fails the consent-provenance check returns 202 and COMMITS — that is the
    "data first" promise and it is correct. It was also the only way an unsweepable lead
    could survive: the dial path's refusal rolled the transaction back, this path never
    reached the refusal at all. One misconfiguration, two opposite outcomes, and the
    surviving one was the one nothing could delete.
    """
    tenant_id, webhook_id = await _tenant_with_source(published=False, consent_field=True)

    async with _client() as http:
        response = await http.post(
            f"/hooks/v1/ingest/{webhook_id}",
            # No `consent` key: without the published-agent refusal this request would
            # have returned 202 with `blocked: no_form_consent` and a committed lead.
            json={"phone_number": "9876540002", "full_name": "Bhavana"},
            headers={SECRET_HEADER: SECRET},
        )

    assert response.status_code == 422, response.text
    assert response.json()["type"].endswith("/agent_not_published")
    assert await _leads(tenant_id) == []


async def test_a_blocked_lead_that_does_land_is_inside_the_sweeps_reach() -> None:
    """The other half, and the one that would catch an over-eager fix.

    Refusing everything would satisfy the invariant and destroy the product. A PUBLISHED
    tenant's lead must still land when the gate blocks the dial — and that tenant must be
    in the sweep's worklist, and the sweep must actually anonymize the lead once its TTL
    passes. End to end, because each link has been true on its own before while the chain
    was not.
    """
    tenant_id, webhook_id = await _tenant_with_source(published=True, consent_field=True)

    async with _client() as http:
        response = await http.post(
            f"/hooks/v1/ingest/{webhook_id}",
            json={"phone_number": "9876540003", "full_name": "Charan"},
            headers={SECRET_HEADER: SECRET},
        )

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["dispatched"] is False
    assert body["blocked"] == "no_form_consent", "the lead lands, the call does not"

    landed = await _leads(tenant_id)
    assert len(landed) == 1
    assert landed[0]["phone_e164"] == "+919876540003"

    assert tenant_id in await _due_tenants(), (
        "a tenant holding a lead must be in the sweep's worklist — this is the invariant "
        "the retention job's cost shape depends on"
    )

    # Age the lead past the seeded 1095-day `lead` policy and sweep. `leads` is not an
    # append-only ledger, so backdating it is an ordinary UPDATE (hard rule 4 governs
    # usage_events, consent_ledger, audit_log and credit_ledger — not this table).
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE leads SET updated_at = :w WHERE tenant_id = :t"),
            {"w": datetime.now(UTC) - timedelta(days=1200), "t": tenant_id},
        )

    counts = await sweep_tenant(tenant_id)
    assert counts["leads"] == 1, "the TTL ran"

    after = await _leads(tenant_id)
    assert len(after) == 1, "anonymized, never deleted — the funnel stays countable"
    assert str(after[0]["phone_e164"]).startswith("+91000"), "the number is gone"
    assert after[0]["name"] is None
    assert after[0]["data"] == {}


async def test_publishing_writes_both_halves_of_the_fact_the_refusal_reads() -> None:
    """The refusal reads `agents.engine_agent_ref`; the sweep reads `engine_agent_routes`.

    They are the same fact only because `publish_agent` writes them in ONE transaction.
    If that ever stops being true, the door check and the worklist drift apart and the
    hole reopens silently — so the linkage is asserted here rather than assumed in a
    comment two modules away.
    """
    tenant_id, _ = await _tenant_with_source(published=True, consent_field=False)

    async with tenant_session(tenant_id) as session:
        refs = (
            (
                await session.execute(
                    text(
                        "SELECT engine_agent_ref FROM agents WHERE tenant_id = :t "
                        "AND engine_agent_ref IS NOT NULL"
                    ),
                    {"t": tenant_id},
                )
            )
            .scalars()
            .all()
        )
    assert refs, "fixture published an agent"

    async with untenanted_session() as session:
        routed = (
            (
                await session.execute(
                    text("SELECT engine_agent_ref FROM engine_agent_routes WHERE tenant_id = :t"),
                    {"t": tenant_id},
                )
            )
            .scalars()
            .all()
        )
    assert set(refs) <= set(routed), (
        "every published agent ref must have its routing row: the ingest refusal checks "
        "the column, the retention sweep resolves the table, and they are only the same "
        "guarantee while publish_agent writes both"
    )


# ==================================== 2. the credit-ledger unique index, still refused
#
# Measured on 2026-08-11 against this database, before writing any migration:
#
#   SELECT tenant_id, ref, reason, count(*) FROM credit_ledger
#    WHERE reason IN ('topup','usage') AND ref IS NOT NULL
#    GROUP BY 1,2,3 HAVING count(*) > 1;            -- 202 pairs, newest seconds old
#
# 202, not the 21 the first attempt saw, and the newest of them minted by the suite that
# had just run. The candidate shape —
#
#   UNIQUE (tenant_id, ref) WHERE reason IN ('topup','usage') AND ref IS NOT NULL
#     AND occurred_at >= '<literal>'::timestamptz
#
# — grandfathers the history behind a literal cutoff and therefore builds. It still
# cannot LIVE, because a cutoff only fences the past and the suite keeps writing to the
# future. `tests/credit_reconciliation_test.py::_double_credit` was fixed (it now seeds
# its residue backdated, by direct INSERT), which is what unblocked the first objection.
# It was not the only minter.


async def test_the_reconcilers_over_charge_fixture_still_mints_a_post_cutoff_violation() -> None:
    """The ONE remaining blocker, reproduced in isolation and named.

    `credit_reconciliation_test.py::test_an_over_charged_call_is_compensated_upward` sets
    up its `usage` group by calling `record_entry` twice with one call id — inline, not
    through the backdating helper its sibling test uses. `record_entry` stamps
    `clock_timestamp()`, so the pair lands NOW, after any cutoff anyone could choose, and
    the candidate index would turn that test into an IntegrityError.

    This test reproduces exactly that write and asserts BOTH rows survive with a
    present-tense timestamp. It is a tripwire, like the one in `schema_hardening_2_test`,
    and it is more specific: when it fails, the remaining fixture has been fixed and the
    index can finally be built. Delete it in the same commit as the migration that adds
    the index.
    """
    tenant_id, _ = await _tenant_with_source(published=True, consent_field=False)
    call_ref = str(uuid.uuid4())
    before = datetime.now(UTC)

    async with tenant_session(tenant_id) as session:
        await record_entry(
            session, tenant_id=tenant_id, delta=Decimal("1000"), reason="topup", ref="UTR-SH3-1"
        )
        # The exact double-charge shape the reconciler's fixture writes.
        for _ in range(2):
            await record_entry(
                session, tenant_id=tenant_id, delta=Decimal("-30"), reason="usage", ref=call_ref
            )

    async with tenant_session(tenant_id) as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT occurred_at FROM credit_ledger WHERE tenant_id = :t "
                        "AND ref = :r AND reason = 'usage' ORDER BY occurred_at"
                    ),
                    {"t": tenant_id, "r": call_ref},
                )
            )
            .scalars()
            .all()
        )

    assert len(rows) == 2, (
        "if this now fails, the (tenant_id, ref) partial unique index has landed — good; "
        "delete this tripwire, and the note in billing/models.CreditLedgerEntry"
    )
    assert all(stamp >= before for stamp in rows), (
        "and this is why a cutoff predicate does not save it: the fixture's rows are "
        "stamped by clock_timestamp(), so they fall AFTER every cutoff a migration could "
        "freeze into a literal"
    )
