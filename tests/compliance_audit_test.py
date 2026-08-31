"""Audit of the outbound gate: every dial path, every rule, every ceiling.

`campaigns_test.py` proves the happy shapes of the campaign machine. This file is the
adversarial pass over the same ground, written the way hard rule 5 reads:

- **No outbound path may skip the gate.** Proved structurally, not by sampling: every
  function in `apps/` that calls `dispatch_call` must also name `check_dispatch` or
  `assert_dispatch_allowed`. A new "call this number" surface that forgets the gate
  fails this test on the day it is written, not on the day TRAI notices.
- **The launch gate and the dial gate must agree.** SEC-COMP §3 lists per-tenant caps
  among the launch blockers, and `check_dispatch` refuses agents that cannot place
  calls. A campaign that launches "ready" and is then refused on every single dial is
  a campaign the client is watching do nothing, forever.
- **The ceilings are per tenant, not per campaign.** FLOWS §5 rule 3 bounds a TENANT
  at its plan's `concurrency_ceiling`; rule 4 bounds each campaign slider under it.
  Two campaigns under one tenant may not add up to twice the ceiling — those lines
  are the ones another tenant's receptionist is waiting for.
- **Stopping is immediate.** Pause carries FLOWS §5's mid-campaign safeties (complaint
  spike, cap breach), so a tick that has already chosen a campaign must still notice
  it was paused a moment ago.

There is no bypass flag anywhere in here; blocked states are produced by writing the
same rows production writes (a `spend_state` cap, a `dnc_list` entry, an inbound-only
agent).
"""

from __future__ import annotations

import ast
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing.service import current_billing_month
from apps.api.campaigns import service as campaigns
from apps.api.compliance.service import add_to_dnc, check_dispatch
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import reset_engine_cache
from apps.workers import campaign_dispatch
from apps.workers.campaign_dispatch import dispatch_campaign_tick
from sqlalchemy import text
from tests.conftest import accept_agreements
from tests.national_dnd_test import record_test_scrub

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    """11:00 IST — inside the platform window, so a refusal here is never the clock."""
    fixed = datetime(2026, 8, 11, 5, 30, tzinfo=UTC) + timedelta(hours=5, minutes=30)
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: fixed)


@pytest.fixture(autouse=True)
def _roomy_platform_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the PLATFORM line pool (FLOWS §5 rule 1) far above anything this suite dials.

    That pool is deliberately global, and this repo's tests run against a persistent
    Postgres that other test processes share: their in-flight `calls` rows and their
    running campaigns consume the very same budget. Leaving it at the pilot default
    makes every assertion below a function of what someone else's run happened to be
    doing. The rules this file actually measures — the per-tenant ceiling and the
    per-campaign slider — are per tenant and untouched by this.
    """
    monkeypatch.setattr(campaign_dispatch, "PLATFORM_LINES_TOTAL", 10_000)


# ------------------------------------------------------------------ fixtures (rows)


async def _tenant(*, direction: str = "outbound") -> tuple[uuid.UUID, uuid.UUID]:
    """A tenant whose agent is live and published — the campaign-ready baseline."""
    reset_engine_cache()
    created = await admin_service.create_organization(
        name="Audit Motors",
        slug=f"audit-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    # The four agreements, accepted (migration a9d4e70c31b8) — supplied, never assumed
    # away, in the shape `arm_agent_for_outbound` established. Every dial, launch and
    # publish gate now refuses an organisation that has not accepted them, so a fixture
    # without this reports `agreements_not_accepted` in place of the answer under test.
    await accept_agreements(uuid.UUID(str(created["id"])))
    tenant_id, agent_id = created["id"], created["agent_id"]
    ref = f"fakeagent_audit_{uuid.uuid4().hex[:8]}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agents SET status = 'live', direction = :dir, "
                "engine_agent_ref = :ref WHERE id = :a"
            ),
            {"dir": direction, "ref": ref, "a": agent_id},
        )
        # The launch gate now requires a live DLT Principal Entity registration and TM
        # link (SEC-COMP §3). These fixtures predate it, so they supply one — the gate
        # is not softened to fit a fixture that was written before the rule existed.
        await campaigns.record_dlt_registration(
            session,
            tenant_id=tenant_id,
            pe_id=f"1102{uuid.uuid4().int % 10**9:09d}",
            entity_name="Audit Motors Pvt Ltd",
            status="active",
            tm_link_status="active",
            registered_at=datetime.now(UTC) - timedelta(days=30),
        )
    # The engine route row. `publish_agent` writes this in the SAME transaction that
    # sets `agents.status = 'live'`, so a live agent without one is a shape production
    # cannot produce — and the dispatcher now resolves its tenant worklist from this
    # table rather than walking every organization, so a fixture that skips it is
    # simply invisible to the tick.
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('fake', :r, :t, :a, true, now(), now())"
            ),
            {"r": ref, "t": tenant_id, "a": agent_id},
        )
    return tenant_id, agent_id


async def _campaign(
    session: Any,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    phones: tuple[str, ...],
    slider: int = 3,
    dlt_status: str = "registered",
) -> uuid.UUID:
    """A launch-ready promotional campaign: 140 number, approved matching template.

    THE NUMBER IS BOUND TO `agent_id` AND REUSED ACROSS THIS AGENT'S CAMPAIGNS (D-424).
    Both halves matter. Bound, because the launch gate refuses a campaign whose approved
    number is not the number its agent dials from — an unbound number resolves to no
    caller ID and the engine answers from its own pool. Reused, because
    `agents.service.resolve_caller_id` REFUSES an agent carrying two registered headers
    (it cannot tell which class of traffic is dialling), so a fixture that minted a second
    one per campaign would model a state production rejects — and these tests would then
    measure a dispatcher that placed no calls at all while still satisfying their
    `<= ceiling` assertions.
    """
    number_id = (
        await session.execute(
            text(
                "SELECT id FROM phone_numbers WHERE agent_id = :aid AND dlt_status = :dlt "
                "ORDER BY created_at, id LIMIT 1"
            ),
            {"aid": agent_id, "dlt": dlt_status},
        )
    ).scalar()
    if number_id is None:
        number_id = uuid7()
        await session.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, agent_id, e164, series, dlt_status, "
                "created_at, updated_at) VALUES (:id, :tid, :aid, :e, '140', :dlt, now(), now())"
            ),
            {
                "id": number_id,
                "tid": tenant_id,
                "aid": agent_id,
                "e": f"+9180{uuid.uuid4().int % 100000000:08d}",
                "dlt": dlt_status,
            },
        )
    template_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO dlt_templates (id, tenant_id, kind, classification, body, status, "
            "created_at, updated_at) VALUES (:id, :tid, 'voice', 'promotional', :body, "
            "'approved', now(), now())"
        ),
        {"id": template_id, "tid": tenant_id, "body": "Hello from {#var#}, an AI assistant."},
    )
    campaign_id = await campaigns.create_campaign(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        name="Audit offers",
        classification="promotional",
        number_id=number_id,
        dlt_template_id=template_id,
        concurrency=slider,
        # Where the contact list came from — the gate refuses a campaign that cannot
        # say. "existing_customer" is the honest answer for invented fixture contacts.
        consent_source="existing_customer",
        consent_collected_at=datetime.now(UTC) - timedelta(days=7),
    )
    await campaigns.add_contacts(
        session,
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        contacts=[{"phone": p, "name": f"Lead {p[-4:]}"} for p in phones],
    )
    # The national DND scrub SEC-COMP §3 asks for (migration a1c8e40f27b9).
    # A promotional campaign is launch-ready only once an access provider has
    # preference-scrubbed its list, so this fixture supplies the fact through the
    # production writer — `tests/national_dnd_test.py` proves the refusal is real.
    await record_test_scrub(session, campaign_id)
    return campaign_id


async def _plan(session: Any, tenant_id: uuid.UUID, *, ceiling: int, **cols: Any) -> None:
    extra_names = "".join(f", {k}" for k in cols)
    extra_binds = "".join(f", :{k}" for k in cols)
    await session.execute(
        text(
            f"INSERT INTO plans (id, tenant_id, concurrency_ceiling{extra_names}, created_at, "
            f"updated_at) VALUES (:id, :tid, :ceiling{extra_binds}, now(), now())"
        ),
        {"id": uuid7(), "tid": tenant_id, "ceiling": ceiling, **cols},
    )


async def _dialing(session: Any, campaign_id: uuid.UUID | None = None) -> int:
    sql = "SELECT count(*) FROM campaign_contacts WHERE status = 'dialing'"
    params: dict[str, Any] = {}
    if campaign_id is not None:
        sql += " AND campaign_id = :cid"
        params["cid"] = campaign_id
    return int((await session.execute(text(sql), params)).scalar() or 0)


# ------------------------------------------------------- every dial path is gated


def test_every_outbound_dial_site_passes_the_compliance_gate() -> None:
    """Hard rule 5, checked structurally rather than by memory.

    `apps/api/agents/service.py::dispatch_call` is the single outbound entry point, so
    the property is: every function that calls it also names the gate. Grepping for
    "the paths I know about" is how a fourth path gets added without one; this walks
    the AST of everything under `apps/`.
    """
    gate_names = {"check_dispatch", "assert_dispatch_allowed"}
    dial_names = {"dispatch_call", "start_outbound_call"}
    # Exactly two exemptions, both narrow on purpose: the chokepoint itself, and the
    # vendor adapters that IMPLEMENT `start_outbound_call` (hard rule 2 keeps vendor
    # shapes in there and nothing else). Anything wider — a whole app, a filename
    # pattern — would let a future dial site hide behind the exemption.
    exempt = {
        REPO_ROOT / "apps" / "api" / "agents" / "service.py",
        *(REPO_ROOT / "apps" / "api" / "engine").glob("*.py"),
    }

    ungated: list[str] = []
    for path in (REPO_ROOT / "apps").rglob("*.py"):
        if path in exempt or "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)} | {
                n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)
            }
            calls = {
                (c.func.id if isinstance(c.func, ast.Name) else c.func.attr)
                for c in ast.walk(node)
                if isinstance(c, ast.Call) and isinstance(c.func, ast.Name | ast.Attribute)
            }
            if calls & dial_names and not (names & gate_names):
                ungated.append(f"{path.relative_to(REPO_ROOT)}::{node.name}")

    assert ungated == [], (
        f"these functions place an outbound call without naming the compliance gate: {ungated}"
    )


# --------------------------------------------------------------- dispatcher ceilings


async def test_two_campaigns_in_one_tenant_share_the_plan_concurrency_ceiling() -> None:
    """FLOWS §5 rule 3: the ceiling is the TENANT's, and rule 4's sliders live under it.

    Two campaigns, each with a slider equal to the whole ceiling, must not add up to
    twice the ceiling — the surplus comes out of the shared pool that keeps another
    tenant's receptionist answering.
    """
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await _plan(session, tenant_id, ceiling=2)
        first = await _campaign(
            session, tenant_id, agent_id, phones=("9876510001", "9876510002"), slider=2
        )
        second = await _campaign(
            session, tenant_id, agent_id, phones=("9876510011", "9876510012"), slider=2
        )
        for campaign_id in (first, second):
            await campaigns.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)

    await dispatch_campaign_tick({})

    async with tenant_session(tenant_id) as session:
        dialing = await _dialing(session)
        calls = int(
            (
                await session.execute(
                    text("SELECT count(*) FROM calls WHERE direction = 'outbound'")
                )
            ).scalar()
            or 0
        )
    assert dialing <= 2, f"the plan ceiling is 2 lines for the tenant, not per campaign: {dialing}"
    assert calls <= 2, f"and that is how many calls may be in flight: {calls}"


async def test_a_superseded_plan_row_does_not_double_claim_the_campaign() -> None:
    """`plans` carries `effective_from`/`effective_to`, so a tenant legitimately has
    more than one row once its plan changes. Joining campaigns to plans on `tenant_id`
    alone multiplies the campaign by its plan history and dispatches it once per row —
    a campaign dialling twice its slider because the client upgraded last month."""
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await _plan(
            session,
            tenant_id,
            ceiling=10,
            effective_from=datetime.now(UTC) - timedelta(days=365),
            effective_to=datetime.now(UTC) - timedelta(days=30),
        )
        await _plan(
            session, tenant_id, ceiling=10, effective_from=datetime.now(UTC) - timedelta(days=30)
        )
        campaign_id = await _campaign(
            session,
            tenant_id,
            agent_id,
            phones=("9876520001", "9876520002", "9876520003", "9876520004", "9876520005"),
            slider=2,
        )
        await campaigns.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)

    await dispatch_campaign_tick({})

    async with tenant_session(tenant_id) as session:
        dialing = await _dialing(session, campaign_id)
    assert dialing == 2, f"the slider is 2 regardless of how many plan rows exist: {dialing}"


async def test_a_campaign_paused_after_the_tick_picked_it_up_dials_nobody() -> None:
    """Pause is a SAFETY, not a preference — FLOWS §5 hangs the complaint-spike alarm
    and the cap-breach auto-pause off it, and both fire because something is going
    wrong right now.

    The tick chooses campaigns in one transaction and claims contacts in another, so
    `_dispatch_for_campaign` is called here directly with a campaign that was paused in
    between: that IS the race, expressed without a sleep. The claim has to re-read the
    campaign's status rather than trust the decision the tick made a moment ago.
    """
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        campaign_id = await _campaign(
            session, tenant_id, agent_id, phones=("9876580001", "9876580002")
        )
        await campaigns.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
        await campaigns.set_campaign_status(
            session, campaign_id=campaign_id, to_status="paused", from_statuses=("running",)
        )

    result = await campaign_dispatch._dispatch_for_campaign(tenant_id, campaign_id, 2, {})

    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT status, attempts FROM campaign_contacts WHERE campaign_id = :c "
                    "ORDER BY created_at, id"
                ),
                {"c": campaign_id},
            )
        ).all()
        calls = int(
            (
                await session.execute(
                    text("SELECT count(*) FROM calls WHERE direction = 'outbound'")
                )
            ).scalar()
            or 0
        )
    assert result["dialled"] == 0, result
    assert all(row == ("pending", 0) for row in rows), rows
    assert calls == 0, "a paused campaign places no calls, not even the ones already queued up"


# ------------------------------------------------- launch gate vs the dial-time gate


async def test_a_capped_tenant_cannot_launch_a_campaign() -> None:
    """SEC-COMP §3 names per-tenant caps among the launch blockers, and `check_dispatch`
    refuses a capped tenant at dial time. If launch does not check it, the client gets
    a `running` campaign whose every contact is refused, refunded and rescheduled
    forever — a campaign that looks alive and dials nobody."""
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        campaign_id = await _campaign(session, tenant_id, agent_id, phones=("9876530001",))
        await session.execute(
            text(
                "INSERT INTO spend_state (tenant_id, month, minutes_used, spend_used, "
                "billed_inr, capped, created_at, updated_at) "
                "VALUES (:tid, :month, 0, 0, 0, true, now(), now()) "
                "ON CONFLICT (tenant_id) DO UPDATE SET capped = true"
            ),
            # THE MONTH IS ASKED THE WAY PRODUCTION ASKS IT, not re-spelled here.
            # `compliance.spend_capped` compares the stored month against
            # `billing.service.current_billing_month()`, which is **IST**
            # (`plans.ist_billing_month`). Spelling it as a UTC month instead made this
            # test write a cap for the wrong month for the 5.5 hours between 18:30 UTC —
            # when the IST month rolls — and 00:00 UTC on the last day of every month.
            # In that window the cap did not match, `spend_capped` correctly returned
            # False, launch was correctly allowed, and this test failed looking exactly
            # like a broken compliance gate. It caught a full release gate at 20:10 UTC
            # on 31 Aug 2026; the sibling defect in the quota suites is pinned by
            # `conftest._ist_month_boundary_is_pinned`.
            {"tid": tenant_id, "month": current_billing_month()},
        )
        blockers = await campaigns.launch_blockers(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
        with pytest.raises(ProblemError) as excinfo:
            await campaigns.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
        decision = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164="+919876530001"
        )
        status = (
            await session.execute(
                text("SELECT status FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar()

    assert "spend_cap" in {b.rule for b in blockers}, [b.rule for b in blockers]
    assert excinfo.value.code == "campaign_launch_blocked"
    assert "spend_cap" in {f["rule"] for f in excinfo.value.fields or []}
    assert decision.rule == "spend_cap", "the two gates must name the same rule"
    assert status == "draft"


async def test_an_agent_that_may_not_place_calls_blocks_launch_not_just_the_dial() -> None:
    """`check_dispatch` refuses an inbound-only agent (`agent_inbound_only`) and a
    deleted one (`agent_missing`). The launch preview knew neither, so the button was
    green on a campaign that could never dial a single contact."""
    inbound_tenant, inbound_agent = await _tenant(direction="inbound")
    deleted_tenant, deleted_agent = await _tenant()

    async with tenant_session(inbound_tenant) as session:
        inbound_campaign = await _campaign(
            session, inbound_tenant, inbound_agent, phones=("9876540001",)
        )
        inbound_blockers = await campaigns.launch_blockers(
            session, tenant_id=inbound_tenant, campaign_id=inbound_campaign
        )
        inbound_decision = await check_dispatch(
            session,
            tenant_id=inbound_tenant,
            agent_id=inbound_agent,
            phone_e164="+919876540001",
        )

    async with tenant_session(deleted_tenant) as session:
        deleted_campaign = await _campaign(
            session, deleted_tenant, deleted_agent, phones=("9876540002",)
        )
        await session.execute(
            text("UPDATE agents SET deleted_at = now() WHERE id = :a"), {"a": deleted_agent}
        )
        deleted_blockers = await campaigns.launch_blockers(
            session, tenant_id=deleted_tenant, campaign_id=deleted_campaign
        )
        deleted_decision = await check_dispatch(
            session,
            tenant_id=deleted_tenant,
            agent_id=deleted_agent,
            phone_e164="+919876540002",
        )

    assert inbound_decision.rule == "agent_inbound_only"
    assert "agent_inbound_only" in {b.rule for b in inbound_blockers}, [
        b.rule for b in inbound_blockers
    ]
    assert deleted_decision.rule == "agent_missing"
    assert "agent_missing" in {b.rule for b in deleted_blockers}, [b.rule for b in deleted_blockers]


async def test_a_campaign_whose_every_contact_opted_out_cannot_launch() -> None:
    """The preview counted `pending` rows BEFORE the DNC scrub launch is about to run.
    A list that is entirely on the do-not-call list therefore showed a green button,
    launched, and reported `dialable: 0` — the client confirming a number that was
    never true. The blocker gets its own rule name rather than reusing `no_contacts`,
    because "upload a contact list" is the wrong instruction here: the list is there
    and every number on it opted out."""
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        campaign_id = await _campaign(
            session, tenant_id, agent_id, phones=("9876550001", "9876550002")
        )
        for phone in ("+919876550001", "+919876550002"):
            await add_to_dnc(session, tenant_id=tenant_id, phone_e164=phone, source="request")
        blockers = await campaigns.launch_blockers(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
        with pytest.raises(ProblemError) as excinfo:
            await campaigns.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
        status = (
            await session.execute(
                text("SELECT status FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar()

    assert [b.rule for b in blockers] == ["all_contacts_dnc"], [b.rule for b in blockers]
    assert excinfo.value.code == "campaign_launch_blocked"
    assert status == "draft", "a campaign with nothing lawful to dial never starts"


async def test_a_number_whose_dlt_registration_is_not_done_cannot_launch() -> None:
    """`phone_numbers.dlt_status` is the number-side twin of the template check, and
    `set_number_dlt_status` exists as a deliberate, audited admin step for exactly the
    reason `set_template_status` does. Dialling from a `pending` or `blocked` number is
    the misclassification failure SEC-COMP §1 calls the most common one — the network
    treats it as spam and the complaints land on the client's PE registration."""
    for dlt_status in ("pending", "blocked"):
        tenant_id, agent_id = await _tenant()
        async with tenant_session(tenant_id) as session:
            campaign_id = await _campaign(
                session,
                tenant_id,
                agent_id,
                phones=("9876570001",),
                dlt_status=dlt_status,
            )
            blockers = await campaigns.launch_blockers(
                session, tenant_id=tenant_id, campaign_id=campaign_id
            )
            with pytest.raises(ProblemError) as excinfo:
                await campaigns.launch_campaign(
                    session, tenant_id=tenant_id, campaign_id=campaign_id
                )
        assert [b.rule for b in blockers] == ["number_not_registered"], (
            dlt_status,
            [b.rule for b in blockers],
        )
        assert excinfo.value.code == "campaign_launch_blocked"


async def test_a_partly_scrubbed_list_still_launches() -> None:
    """The mirror of the test above: one opted-out number among three is a scrub, not a
    blocker — the gate must not become a way to fail a campaign that has real work."""
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        campaign_id = await _campaign(
            session, tenant_id, agent_id, phones=("9876560001", "9876560002", "9876560003")
        )
        await add_to_dnc(session, tenant_id=tenant_id, phone_e164="+919876560002", source="request")
        blockers = await campaigns.launch_blockers(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
        result = await campaigns.launch_campaign(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
    assert blockers == []
    assert result == {"status": "running", "dialable": 2, "dnc_scrubbed": 1}
