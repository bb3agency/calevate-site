"""Adversarial audit of the outbound campaign path — the dial-time half.

`campaigns_test.py` proves the launch gate. `compliance_audit_test.py` proves no dial
site skips `check_dispatch`, and that the launch gate and the dial gate agree about the
AGENT and the TENANT. This file attacks the seam neither of them covers: **the facts
SEC-COMP §3 checks at launch that can stop being true while the campaign is running.**

The launch gate is a photograph. A campaign runs for days. Between the click and the
ring, all of these are ordinary events:

- a DLT voice template is rejected or withdrawn by the registrar (`set_template_status`);
- a calling number's header registration is pulled (`set_number_dlt_status`), or the
  number row is deleted outright — `campaigns.number_id` is `ON DELETE SET NULL`, so the
  campaign keeps running with no number at all;
- the client's Principal Entity registration is suspended, or their TM authorisation of
  Calevate is withdrawn (`record_dlt_registration`);
- **Calevate's own telemarketer registration lapses** — one row, every tenant at once,
  and SEC-COMP §3 is explicit that dialling then "is not a client with a paperwork gap,
  it is US dialling as an unregistered telemarketer";
- a campaign that was already `running` when the provenance columns landed answers
  §3's consent question with NULL, forever, because `declare_consent_provenance` is
  draft-only.

`check_dispatch` — the per-dial gate — knows none of these. It checks the platform halt,
the agent, the tenant's caps and wallet, the hour, and the DNC list. Every rule in the
list above is a CAMPAIGN fact, and until `campaigns.service.dispatch_blockers` existed
nothing re-asked them after launch.

The other three properties this file pins:

- **the big red switch beats work already claimed** — a batch claimed one second before
  the halt must not dial the rest of itself;
- **DNC is read live, per contact** — an opt-out landing between two dials of the SAME
  tick blocks the second one;
- **a tick that dies mid-batch must not re-ring the people it already called.** arq
  0.28 retries a job for `arq.Retry`, `RetryJob` and `CancelledError` — and a cron tick
  that overruns `job_timeout`, or a worker that is redeployed, is a `CancelledError`
  through the middle of the dial loop.

No bypass flag, no test-only branch, no environment check appears anywhere here.
Blocked states are produced by writing the rows production writes, and launchable ones
by supplying the facts (`dlt_registrations`, `phone_numbers`, `dlt_templates`, consent
provenance) exactly as `campaigns_test.py` does.
"""

from __future__ import annotations

import ast
import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import service as agents_service
from apps.api.campaigns import service as campaigns
from apps.api.compliance.service import add_to_dnc, check_dispatch
from apps.api.core.loadshed import set_platform_status
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import reset_engine_cache
from apps.api.engine.fake import FakeEngine
from apps.workers import campaign_dispatch
from apps.workers.campaign_dispatch import ACTIVE_STATUSES, dispatch_campaign_tick
from calevate_shared.engine import CallContext
from sqlalchemy import text

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    """11:00 IST — inside the platform window, so a refusal here is never the clock."""
    fixed = datetime(2026, 8, 11, 5, 30, tzinfo=UTC) + timedelta(hours=5, minutes=30)
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: fixed)


@pytest.fixture(autouse=True)
def _roomy_platform_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the platform-wide line pool (FLOWS §5 rule 1) above anything here dials.

    That pool is global by design and this repo's tests run against a shared Postgres:
    another process's in-flight `calls` rows spend the same budget. Nothing measured in
    this file is about rule 1 — see `compliance_audit_test` for the same fixture and the
    same reasoning.
    """
    monkeypatch.setattr(campaign_dispatch, "PLATFORM_LINES_TOTAL", 10_000)


# Every tenant this module made, so the teardown below can settle exactly those and
# nothing else.
_TENANTS: list[uuid.UUID] = []


@pytest.fixture(scope="module", autouse=True)
async def _settle_what_this_module_started() -> AsyncIterator[None]:
    """Leave the shared platform as quiet as we found it.

    The outbound line pool (FLOWS §5 rule 1) is platform-wide and this repo's tests run
    against a persistent Postgres that other suites — and other pytest processes — share.
    A `running` campaign left behind is dialled by every later platform-wide tick; a
    `queued` call row left behind spends a line out of that shared pool for a full
    `ACTIVE_CALL_HORIZON` (an hour). Both would land on somebody else's assertions.

    Scoped to the tenants in `_TENANTS` — the ones this module created — and never a
    `LIKE` sweep, which is how a cleanup ends up cancelling a campaign another process
    launched one second ago.
    """
    yield
    for tenant_id in _TENANTS:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "UPDATE campaigns SET status = 'cancelled', updated_at = now() "
                    "WHERE status IN ('running', 'paused')"
                )
            )
            await session.execute(
                text(
                    "UPDATE calls SET status = 'completed', updated_at = now() "
                    f"WHERE status IN {ACTIVE_STATUSES!r}"
                )
            )


# ------------------------------------------------------------------ fixtures (rows)


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    """A tenant whose agent is live, published and routable — the dialable baseline."""
    reset_engine_cache()
    created = await admin_service.create_organization(
        name="Standing Motors",
        slug=f"stand-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    ref = f"fakeagent_stand_{uuid.uuid4().hex[:8]}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agents SET status = 'live', direction = 'outbound', "
                "engine_agent_ref = :ref WHERE id = :a"
            ),
            {"ref": ref, "a": agent_id},
        )
        # The client's own DLT paperwork, live — supplied, never assumed away.
        await campaigns.record_dlt_registration(
            session,
            tenant_id=tenant_id,
            pe_id=f"1102{uuid.uuid4().int % 10**9:09d}",
            entity_name="Standing Motors Pvt Ltd",
            status="active",
            tm_link_status="active",
            registered_at=datetime.now(UTC) - timedelta(days=30),
        )
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('fake', :r, :t, :a, true, now(), now())"
            ),
            {"r": ref, "t": tenant_id, "a": agent_id},
        )
    _TENANTS.append(tenant_id)
    return tenant_id, agent_id


async def _launched(
    *,
    phones: tuple[str, ...] = ("9876600001", "9876600002"),
    slider: int = 3,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """(tenant, agent, campaign, number, template) — launched through the real gate.

    Everything this returns is a handle the tests then take AWAY, one at a time, to ask
    whether the dispatcher notices.
    """
    tenant_id, agent_id = await _tenant()
    number_id, template_id = uuid7(), uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, e164, series, dlt_status, created_at, "
                "updated_at) VALUES (:id, :tid, :e, '140', 'registered', now(), now())"
            ),
            {
                "id": number_id,
                "tid": tenant_id,
                "e": f"+9180{uuid.uuid4().int % 100000000:08d}",
            },
        )
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
            name="Standing offers",
            classification="promotional",
            number_id=number_id,
            dlt_template_id=template_id,
            concurrency=slider,
            consent_source="existing_customer",
            consent_collected_at=datetime.now(UTC) - timedelta(days=7),
        )
        await campaigns.add_contacts(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            contacts=[{"phone": p, "name": f"Lead {p[-4:]}"} for p in phones],
        )
        # The real gate, unmodified: if any fixture above were missing this raises.
        await campaigns.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
    return tenant_id, agent_id, campaign_id, number_id, template_id


async def _contacts(tenant_id: uuid.UUID, campaign_id: uuid.UUID) -> list[tuple[str, int]]:
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
    return [(str(r[0]), int(r[1])) for r in rows]


async def _calls_placed(tenant_id: uuid.UUID) -> int:
    async with tenant_session(tenant_id) as session:
        return int(
            (
                await session.execute(
                    text("SELECT count(*) FROM calls WHERE direction = 'outbound'")
                )
            ).scalar()
            or 0
        )


async def _tick_one_campaign(
    tenant_id: uuid.UUID, campaign_id: uuid.UUID, slots: int = 3
) -> dict[str, int]:
    """One campaign's slice of a tick.

    `_dispatch_for_campaign` is where the claim and the per-dial gate live, and calling
    it directly keeps these assertions independent of what another pytest process is
    dialling against the same Postgres right now. The tick reaches it for every running
    campaign — `campaigns_test` and `compliance_audit_test` both prove that wiring, so
    it is not re-proved here.
    """
    return await campaign_dispatch._dispatch_for_campaign(
        tenant_id, campaign_id, slots, campaigns.DEFAULT_RETRY_POLICY
    )


# --------------------------- the launch-time facts that can stop being true (§3)


async def test_a_revoked_dlt_template_stops_the_campaign_before_the_next_dial() -> None:
    """`set_template_status` is how the registrar's verdict is recorded, and it moves
    both ways. A template withdrawn after launch means every remaining dial speaks under
    a registration that no longer exists — the misclassification SEC-COMP §1 calls the
    most common registration failure."""
    tenant_id, _, campaign_id, _, template_id = await _launched()

    async with tenant_session(tenant_id) as session:
        await campaigns.set_template_status(session, template_id=template_id, status="rejected")

    result = await _tick_one_campaign(tenant_id, campaign_id)

    assert result == {"dialled": 0, "blocked": 0, "exhausted": 0}, result
    assert await _calls_placed(tenant_id) == 0, "a withdrawn template dials nobody"
    assert await _contacts(tenant_id, campaign_id) == [("pending", 0), ("pending", 0)], (
        "refused before the claim: no attempt burned, nothing to refund"
    )


async def test_a_number_whose_header_registration_is_pulled_stops_the_campaign() -> None:
    """`phone_numbers.dlt_status` is the number-side twin of the template check.
    Dialling from a de-registered header gets the traffic dropped as spam and the
    complaints filed against the CLIENT's Principal Entity."""
    tenant_id, _, campaign_id, number_id, _ = await _launched()

    async with tenant_session(tenant_id) as session:
        await agents_service.set_number_dlt_status(
            session, number_id=number_id, dlt_status="blocked"
        )

    await _tick_one_campaign(tenant_id, campaign_id)

    assert await _calls_placed(tenant_id) == 0
    assert await _contacts(tenant_id, campaign_id) == [("pending", 0), ("pending", 0)]


async def test_a_deleted_calling_number_stops_the_campaign_rather_than_dialling_headerless() -> (
    None
):
    """`campaigns.number_id` is `ON DELETE SET NULL`, so removing the number leaves a
    RUNNING campaign whose calling number is NULL — the state `number_missing` blocks at
    launch, reached from the other side."""
    tenant_id, _, campaign_id, number_id, _ = await _launched()

    async with tenant_session(tenant_id) as session:
        await session.execute(text("DELETE FROM phone_numbers WHERE id = :n"), {"n": number_id})
        assert (
            await session.execute(
                text("SELECT number_id FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar() is None, "SET NULL fired — this is the state under test"

    await _tick_one_campaign(tenant_id, campaign_id)

    assert await _calls_placed(tenant_id) == 0
    assert await _contacts(tenant_id, campaign_id) == [("pending", 0), ("pending", 0)]


async def test_a_suspended_principal_entity_registration_stops_the_campaign() -> None:
    """SEC-COMP §3's first bullet, client half. A PE registration is suspended by the
    registrar, not by us, and it happens to live campaigns."""
    tenant_id, _, campaign_id, _, _ = await _launched()

    async with tenant_session(tenant_id) as session:
        await campaigns.record_dlt_registration(
            session,
            tenant_id=tenant_id,
            pe_id=f"1102{uuid.uuid4().int % 10**9:09d}",
            entity_name="Standing Motors Pvt Ltd",
            status="suspended",
            tm_link_status="active",
        )

    await _tick_one_campaign(tenant_id, campaign_id)

    assert await _calls_placed(tenant_id) == 0
    assert await _contacts(tenant_id, campaign_id) == [("pending", 0), ("pending", 0)]


async def test_a_campaign_resumed_after_its_tm_link_lapsed_still_refuses_to_dial() -> None:
    """RESUME is the path with no gate on it at all: `set_campaign_status` is a bare CAS
    from `paused` back to `running`. A campaign can therefore sit paused for a week —
    long enough for the client to withdraw Calevate's telemarketer authorisation — and
    come back `running` with nothing having re-read the paperwork. The dial-time check is
    what has to catch it, because the resume route never will."""
    tenant_id, _, campaign_id, _, _ = await _launched()

    async with tenant_session(tenant_id) as session:
        await campaigns.set_campaign_status(
            session, campaign_id=campaign_id, to_status="paused", from_statuses=("running",)
        )
        await campaigns.record_dlt_registration(
            session,
            tenant_id=tenant_id,
            pe_id=f"1102{uuid.uuid4().int % 10**9:09d}",
            entity_name="Standing Motors Pvt Ltd",
            status="active",
            tm_link_status="revoked",
        )
        await campaigns.set_campaign_status(
            session, campaign_id=campaign_id, to_status="running", from_statuses=("paused",)
        )

    await _tick_one_campaign(tenant_id, campaign_id)

    assert await _calls_placed(tenant_id) == 0, "resume is not a way around the gate"
    assert await _contacts(tenant_id, campaign_id) == [("pending", 0), ("pending", 0)]


async def test_a_running_campaign_that_never_answered_the_provenance_question_stops() -> None:
    """`consent_source IS NULL` is the honest state of every campaign that predates the
    provenance columns, and `declare_consent_provenance` is DRAFT-ONLY — so a campaign
    that was already `running` when the migration landed can never answer §3's question
    and, until the dial-time check existed, never had to.

    Staged by nulling the columns on a launched campaign, which is exactly the row shape
    that migration produced. Nothing here weakens the gate: the campaign went through
    `launch_campaign` with a real answer first.
    """
    tenant_id, _, campaign_id, _, _ = await _launched()

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE campaigns SET consent_source = NULL, consent_collected_at = NULL "
                "WHERE id = :c"
            ),
            {"c": campaign_id},
        )

    await _tick_one_campaign(tenant_id, campaign_id)

    assert await _calls_placed(tenant_id) == 0, "a list we cannot trace to a consent is not dialled"
    assert await _contacts(tenant_id, campaign_id) == [("pending", 0), ("pending", 0)]


async def test_a_purchased_list_is_refused_at_dispatch_by_its_own_name() -> None:
    """SEC-COMP §3 distinguishes two provenance states with different remedies, and the
    dispatch gate has to keep them apart for the same reason the launch gate does:
    `consent_provenance_missing` is a question the client can still answer,
    `consent_source_refused` is a policy refusal no form can clear. Collapsing them into
    one "no consent" refusal would send half the clients to a form that cannot help.

    A purchased list cannot reach `running` through the launch gate — which is the
    point — so this asserts the DISPATCH gate names it independently, on the campaign
    still in draft, alongside the launched-then-nulled case above.
    """
    tenant_id, _, campaign_id, _, _ = await _launched()

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaigns SET consent_source = 'purchased_list' WHERE id = :c"),
            {"c": campaign_id},
        )
        blockers = await campaigns.dispatch_blockers(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )

    await _tick_one_campaign(tenant_id, campaign_id)

    assert [b.rule for b in blockers] == ["consent_source_refused"], [b.rule for b in blockers]
    assert await _calls_placed(tenant_id) == 0


async def test_an_agent_whose_disclosure_line_is_blanked_mid_run_stops_dialling() -> None:
    """ "Agents always have a non-null disclosure line" (hard rule 5) is enforced by
    `agents.disclosure_line NOT NULL` plus the `length(disclosure_line) > 0` CHECK, and
    no code path updates the column after creation — so the schema is the real
    guarantee. Whitespace is the one shape that CHECK still admits, and it produces an
    agent that opens a call by disclosing nothing.

    The gate must refuse at DIAL time, not merely at agent-create time: this is the
    "agent republished without one" case, and republishing (`publish_agent`) rewrites
    status and the engine ref while leaving whatever is in that column alone.
    """
    tenant_id, agent_id, campaign_id, _, _ = await _launched()

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET disclosure_line = '   ' WHERE id = :a"), {"a": agent_id}
        )
        decision = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164="+919876600001"
        )

    result = await _tick_one_campaign(tenant_id, campaign_id)

    assert decision.rule == "disclosure_missing", decision
    assert result["dialled"] == 0 and result["blocked"] == 2, result
    assert await _calls_placed(tenant_id) == 0, "no disclosure, no call"


async def test_a_number_series_that_stops_matching_the_classification_stops_the_campaign() -> None:
    """140 ⇔ promotional, 160/standard ⇔ service & transactional. The launch gate checks
    it once; this asserts the dispatcher re-checks it, so a number re-classified under a
    running promotional campaign cannot keep dialling from a service header.

    NOTE what this does NOT prove, because nothing in the codebase can: `campaigns.
    number_id` is read by the two gates and by nothing else. `dispatch_call` takes no
    calling number, and neither `VoiceEngine.start_outbound_call` nor `AgentConfig`
    carries one — the engine dials from whatever the vendor has attached to the agent.
    So the series rule is enforced as a REFUSAL TO LAUNCH OR DISPATCH, never as a choice
    of outgoing header. Fixing that is an engine-contract change, not a gate change.
    """
    tenant_id, _, campaign_id, number_id, _ = await _launched()

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE phone_numbers SET series = '160' WHERE id = :n"), {"n": number_id}
        )
        blockers = await campaigns.dispatch_blockers(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )

    await _tick_one_campaign(tenant_id, campaign_id)

    assert [b.rule for b in blockers] == ["number_series_mismatch"], [b.rule for b in blockers]
    assert await _calls_placed(tenant_id) == 0


async def test_the_dispatch_gate_names_the_launch_gate_s_own_rules() -> None:
    """Two gates, one vocabulary. A dispatch-time refusal a client cannot look up in the
    launch-check screen is a campaign that has silently stopped, and SURFACES §2b exists
    to stop exactly that."""
    tenant_id, _, campaign_id, number_id, template_id = await _launched()

    async with tenant_session(tenant_id) as session:
        await campaigns.set_template_status(session, template_id=template_id, status="rejected")
        await agents_service.set_number_dlt_status(
            session, number_id=number_id, dlt_status="pending"
        )
        standing = await campaigns.dispatch_blockers(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
        launch = await campaigns.launch_blockers(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )

    standing_rules = [b.rule for b in standing]
    assert standing_rules == ["dlt_template_not_approved", "number_not_registered"], standing_rules
    assert {b.rule for b in standing} <= {b.rule for b in launch}, (
        "every dispatch-time rule must be one the launch screen can also explain"
    )
    assert all(b.reason.strip() for b in standing), "and each one says what is wrong"


# ----------------------------------------------------- structural, over the call graph


def _dispatcher_functions() -> dict[str, ast.AsyncFunctionDef | ast.FunctionDef]:
    source = (REPO_ROOT / "apps" / "workers" / "campaign_dispatch.py").read_text(encoding="utf-8")
    tree = ast.parse(source, filename="campaign_dispatch.py")
    return {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def _called_names(node: ast.AST) -> set[str]:
    return {
        (call.func.id if isinstance(call.func, ast.Name) else call.func.attr)
        for call in ast.walk(node)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name | ast.Attribute)
    }


def test_the_claiming_function_calls_both_gates() -> None:
    """`compliance_audit_test` proves no dial site skips `check_dispatch`. That test
    cannot see the OTHER gate, because `dispatch_blockers` is not on the path of the
    three non-campaign dial surfaces at all — it is a campaign fact, asked once per
    campaign rather than once per number.

    So the property is pinned here, on the one function that claims campaign contacts:
    it must name both. Deleting the standing check to "simplify the tick" is the exact
    regression this catches, and it fails on the day the line is removed rather than on
    the day a registrar notices.
    """
    claim = _dispatcher_functions()["_dispatch_for_campaign"]
    called = _called_names(claim)
    assert "dispatch_blockers" in called, (
        "_dispatch_for_campaign must re-read the campaign's DLT paperwork before claiming"
    )
    assert "check_dispatch" in called, "and run the per-contact gate for everything it claims"


def test_the_dispatcher_offers_no_way_to_switch_a_gate_off() -> None:
    """Hard rule 5: "never add a bypass 'for testing' (use staging fixtures instead)".

    A bypass arrives as a parameter, not as a comment — `skip_gate`, `force`,
    `for_testing`, `dry_run` — so the check is over the dispatcher's argument names and
    keywords, which is where one would have to appear to be reachable.
    """
    banned = {
        "skip_gate",
        "skip_compliance",
        "bypass",
        "bypass_gate",
        "force",
        "for_testing",
        "no_gate",
        "dry_run",
        "unsafe",
    }
    offenders: list[str] = []
    for name, node in _dispatcher_functions().items():
        args = node.args
        parameters = {a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)}
        keywords = {
            kw.arg
            for call in ast.walk(node)
            if isinstance(call, ast.Call)
            for kw in call.keywords
            if kw.arg is not None
        }
        for offender in sorted((parameters | keywords) & banned):
            offenders.append(f"{name}({offender}=...)")
    assert offenders == [], f"the dispatch path grew a gate bypass: {offenders}"


class _RollbackError(Exception):
    """Sentinel: leaving the transaction by raising rolls it back. The platform TM
    registration is ONE global row shared with every other pytest process on this
    database, so this suite may only make it un-live inside a transaction it abandons
    (the pattern `tests/tm_registration_test.py` established)."""


async def test_the_platform_tm_registration_is_a_dispatch_time_blocker_too() -> None:
    """SEC-COMP §3: ours is the company-level blocker, "false for every tenant at once".
    It is read at launch. A registration suspended by a spam-complaint run — §1's 5-in-10
    rule, which is precisely when dialling must stop — lands on campaigns that are
    already running, and `check_dispatch` never looks at it.

    Asserted against `dispatch_blockers` on the caller's session rather than through a
    tick, because the un-registration is uncommitted: MVCC keeps every other connection
    (and every other pytest process) seeing the committed `active` row throughout.
    """
    tenant_id, _, campaign_id, _, _ = await _launched()

    captured: dict[str, Any] = {}
    try:
        async with tenant_session(tenant_id) as session:
            await session.execute(text("SET LOCAL lock_timeout = '5s'"))
            await session.execute(
                text(
                    "UPDATE platform_state SET tm_registration_status = 'suspended', "
                    "tm_registered_at = NULL WHERE id = 1"
                )
            )
            captured["blockers"] = await campaigns.dispatch_blockers(
                session, tenant_id=tenant_id, campaign_id=campaign_id
            )
            raise _RollbackError
    except _RollbackError:
        pass

    rules = [b.rule for b in captured["blockers"]]
    assert rules == ["tm_registration_missing"], rules


async def test_paperwork_that_is_still_good_dials_normally() -> None:
    """The mirror of the six tests above: the standing check must not become a way to
    stop a campaign that is entirely in order."""
    tenant_id, _, campaign_id, _, _ = await _launched()

    result = await _tick_one_campaign(tenant_id, campaign_id)

    assert result["dialled"] == 2, result
    assert await _calls_placed(tenant_id) == 2
    assert await _contacts(tenant_id, campaign_id) == [("dialing", 1), ("dialing", 1)]


# ------------------------------------------------------- the switch, live, mid-batch


async def test_a_batch_claimed_before_the_halt_does_not_dial_after_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The big red switch is checked once at the top of the tick — which is correct and
    is not enough. A batch claimed a second before the operator pulls it is already
    inside the loop, and the contacts behind the first one must not ring.

    The halt is thrown from inside the first dial, so the second contact of the SAME
    claimed batch is the one under test.
    """
    tenant_id, _, campaign_id, _, _ = await _launched(phones=("9876610001", "9876610002"))
    original = FakeEngine.start_outbound_call
    halted_after: list[str] = []

    async def halt_after_first(self: FakeEngine, ref: str, to: str, ctx: CallContext) -> str:
        handle = await original(self, ref, to, ctx)
        if not halted_after:
            halted_after.append(handle)
            await set_platform_status(outbound_halted=True, actor_id=None)
        return handle

    monkeypatch.setattr(FakeEngine, "start_outbound_call", halt_after_first)
    try:
        result = await _tick_one_campaign(tenant_id, campaign_id)
    finally:
        await set_platform_status(outbound_halted=False, actor_id=None)

    assert len(halted_after) == 1, "the switch was pulled exactly once, mid-batch"
    assert result["dialled"] == 1, result
    assert await _calls_placed(tenant_id) == 1, "the halt caught the rest of the batch"
    statuses = await _contacts(tenant_id, campaign_id)
    assert ("pending", 0) in statuses, f"the un-dialled contact waits, unpenalised: {statuses}"


async def test_the_tick_itself_refuses_while_the_switch_is_pulled() -> None:
    """And the cheap check at the top still short-circuits the whole platform."""
    tenant_id, _, _campaign_id, _, _ = await _launched(phones=("9876620001",))
    await set_platform_status(outbound_halted=True, actor_id=None)
    try:
        result = await dispatch_campaign_tick({})
    finally:
        await set_platform_status(outbound_halted=False, actor_id=None)

    assert result == "halted_by_big_red_switch"
    assert await _calls_placed(tenant_id) == 0


# ------------------------------------------------------------------ DNC propagation


async def test_an_opt_out_landing_between_two_dials_blocks_the_second_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hard rule 5's propagation deadline is "before the next dispatch tick". That is
    the number `campaigns_test.py` already measures. This measures something stricter,
    and cheaper to get wrong: an opt-out committed by ANOTHER connection while a tick is
    already mid-batch, against a contact the tick has ALREADY CLAIMED.

    `check_dispatch` documents its DNC read as live and never cached, and this is what
    that sentence has to mean in practice. Any snapshot — a per-tick scrub, a set of
    numbers read once at claim time, a memoised `dnc_list` — would still pass the
    published test and fail this one, because the opt-out lands after the claim.
    """
    tenant_id, _, campaign_id, _, _ = await _launched(phones=("9876630001", "9876630002"))
    original = FakeEngine.start_outbound_call
    dialled: list[str] = []

    async def opt_out_after_first(self: FakeEngine, ref: str, to: str, ctx: CallContext) -> str:
        handle = await original(self, ref, to, ctx)
        dialled.append(to)
        if len(dialled) == 1:
            # A separate transaction, committed: the person who was about to be
            # contact #2 hangs up on contact #1's call and says "don't call me again".
            async with tenant_session(tenant_id) as other:
                await add_to_dnc(
                    other,
                    tenant_id=tenant_id,
                    phone_e164="+919876630002",
                    source="call_optout",
                )
        return handle

    monkeypatch.setattr(FakeEngine, "start_outbound_call", opt_out_after_first)
    await _tick_one_campaign(tenant_id, campaign_id)

    assert dialled == ["+919876630001"], f"the opt-out beat the dial within one tick: {dialled}"
    async with tenant_session(tenant_id) as session:
        statuses = dict(
            (
                await session.execute(
                    text("SELECT phone_e164, status FROM campaign_contacts WHERE campaign_id = :c"),
                    {"c": campaign_id},
                )
            ).all()
        )
    assert statuses["+919876630002"] == "dnc_blocked", "and terminally, not on the retry ladder"


# ------------------------------------------------------- idempotency / double-dialling


async def test_a_tick_killed_mid_batch_does_not_re_ring_the_people_it_already_called(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """arq 0.28 retries a job for `arq.Retry`, `RetryJob` and `CancelledError` only — and
    a cron tick that overruns `job_timeout` (300s), or a worker caught mid-tick by a
    deploy, IS a `CancelledError` through the middle of the dial loop. `CancelledError`
    is a `BaseException`, so the `except Exception` around the engine call does not see
    it, and it is not the engine failing anyway: the dials that already happened
    happened.

    If the claim and the dials share one transaction, that rollback un-claims contacts
    whose phones have already rung. Thirty seconds later the next tick claims them again
    and rings the same people a second time.
    """
    tenant_id, _, campaign_id, _, _ = await _launched(
        phones=("9876640001", "9876640002", "9876640003"), slider=3
    )
    original = FakeEngine.start_outbound_call
    rung: list[str] = []

    async def die_after_first(self: FakeEngine, ref: str, to: str, ctx: CallContext) -> str:
        handle = await original(self, ref, to, ctx)
        rung.append(to)
        if len(rung) == 1:
            # The worker is being shut down / the job has overrun its timeout.
            raise asyncio.CancelledError
        return handle

    monkeypatch.setattr(FakeEngine, "start_outbound_call", die_after_first)
    with pytest.raises(asyncio.CancelledError):
        await _tick_one_campaign(tenant_id, campaign_id)

    assert rung == ["+919876640001"], rung

    # The retry: arq re-runs the job, or the 30s cron fires again. Same thing.
    monkeypatch.setattr(FakeEngine, "start_outbound_call", original)
    await _tick_one_campaign(tenant_id, campaign_id)

    async with tenant_session(tenant_id) as session:
        second_round = (
            (
                await session.execute(
                    text("SELECT to_e164 FROM calls WHERE direction = 'outbound' ORDER BY to_e164")
                )
            )
            .scalars()
            .all()
        )
    assert "+919876640001" not in second_round, (
        "the person who already answered must not be rung a second time by the retry"
    )


# ----------------------------------------------------------------- hard rule 6 (PII)


async def test_no_phone_number_reaches_the_logs_on_the_dispatch_path(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Hard rule 6: log ids, never numbers. Exercised over a tick that does all four
    things at once — dials, is refused by DNC, is refused by the standing gate, and has
    the engine reject a dial — because the failure paths are where a number gets logged
    "just this once, for debugging"."""
    tenant_id, _, campaign_id, _, _ = await _launched(
        phones=("9876650001", "9876650002", "9876650003"), slider=3
    )
    async with tenant_session(tenant_id) as session:
        await add_to_dnc(
            session, tenant_id=tenant_id, phone_e164="+919876650002", source="call_optout"
        )

    original = FakeEngine.start_outbound_call
    seen: list[str] = []

    async def refuse_the_second(self: FakeEngine, ref: str, to: str, ctx: CallContext) -> str:
        seen.append(to)
        if len(seen) == 2:
            # The engine's own error text quotes the number back at us — the most
            # natural way for one to end up in a log line.
            raise RuntimeError(f"engine refused {to}")
        return await original(self, ref, to, ctx)

    monkeypatch.setattr(FakeEngine, "start_outbound_call", refuse_the_second)

    with caplog.at_level(logging.DEBUG):
        # Dials one, is refused on one by DNC, and has the engine reject one.
        await _tick_one_campaign(tenant_id, campaign_id)
        # …and then the standing gate refuses the whole campaign, which logs its own
        # line (`campaign_dispatch_blocked`) with the campaign and the rule names.
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "UPDATE campaigns SET consent_source = NULL, consent_collected_at = NULL "
                    "WHERE id = :c"
                ),
                {"c": campaign_id},
            )
            await session.execute(
                text(
                    "UPDATE campaign_contacts SET status = 'pending', next_attempt_at = NULL "
                    "WHERE campaign_id = :c"
                ),
                {"c": campaign_id},
            )
        await _tick_one_campaign(tenant_id, campaign_id)

    assert any(r.getMessage() == "campaign_dispatch_blocked" for r in caplog.records), (
        "the standing-gate refusal must actually have been logged for this to prove anything"
    )
    digits = ("9876650001", "9876650002", "9876650003", "919876650001")
    for record in caplog.records:
        rendered = " ".join([str(record.getMessage()), *(str(v) for v in record.__dict__.values())])
        for digit in digits:
            assert digit not in rendered, (
                f"{record.name}/{record.levelname} logged a phone number: {record.getMessage()}"
            )
