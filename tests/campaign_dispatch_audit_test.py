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
from apps.api.agents.models import CALL_CAP_MAX_S
from apps.api.agents.service import UNCONFIRMED_ENGINE_CALL_PREFIX
from apps.api.campaigns import service as campaigns
from apps.api.compliance.service import add_to_dnc, check_dispatch
from apps.api.core import loadshed
from apps.api.core.errors import ProblemError
from apps.api.core.loadshed import set_platform_status
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import reset_engine_cache
from apps.api.engine.fake import FakeEngine
from apps.workers import campaign_dispatch
from apps.workers.campaign_dispatch import ACTIVE_STATUSES, dispatch_campaign_tick
from calevate_shared.engine import CallContext
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
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
    # The four agreements, accepted (migration a9d4e70c31b8) — supplied, never assumed
    # away, exactly like the DLT registration above. Since that release every dial gate
    # refuses an organisation that has not accepted them, and a fixture without them makes
    # this file report `agreements_not_accepted` in place of the refusal it is about.
    await accept_agreements(uuid.UUID(str(tenant_id)))
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
                "INSERT INTO phone_numbers (id, tenant_id, agent_id, e164, series, dlt_status, "
                "created_at, updated_at) "
                "VALUES (:id, :tid, :aid, :e, '140', 'registered', now(), now())"
            ),
            {
                "id": number_id,
                "tid": tenant_id,
                # BOUND TO THE CAMPAIGN'S AGENT (D-424): the launch gate refuses a campaign
                # whose approved number is not the number its agent dials from.
                "aid": agent_id,
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
        # The national DND scrub SEC-COMP §3 asks for (migration a1c8e40f27b9).
        # A promotional campaign is launch-ready only once an access provider has
        # preference-scrubbed its list, so this fixture supplies the fact through the
        # production writer — `tests/national_dnd_test.py` proves the refusal is real.
        await record_test_scrub(session, campaign_id)
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
    """Hard rule 5's dial-time refusal, ON THE COLUMN THE GATE NOW READS (D-163).

    The finding this test was written for: `agents.disclosure_line NOT NULL` plus
    `length(disclosure_line) > 0` admits WHITESPACE, so an agent could open a call
    disclosing nothing and only a dial-time check would catch it. D-163 splits the
    column, and the AI sentence — the one the gate asks about — carries
    `length(btrim(ai_disclosure_line)) > 0`, so the whitespace shape is now refused by
    the SCHEMA and the state cannot be written at all
    (`tests/disclosure_toggle_test.py` pins that direction).

    **This test therefore now asserts a STRONGER property than the one it was written
    for**, and says so rather than quietly weakening: the mid-run blanking is refused by
    the database, so there is no window in which a dial-time check is the only thing
    standing between a blank agent and a caller. `check_dispatch`'s `disclosure_missing`
    branch is kept as belt-and-braces, and the test BELOW drives it — the constraint
    turns out to be narrower than this docstring assumed, so no dropped constraint is
    needed to construct the row.
    """
    tenant_id, agent_id, campaign_id, _, _ = await _launched()

    with pytest.raises(IntegrityError):
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE agents SET ai_disclosure_line = '   ' WHERE id = :a"),
                {"a": agent_id},
            )

    async with tenant_session(tenant_id) as session:
        decision = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164="+919876600001"
        )

    assert decision.rule != "disclosure_missing", (
        "the blanking was refused, so the agent still has its AI sentence and the gate "
        "must not be reporting one missing"
    )
    result = await _tick_one_campaign(tenant_id, campaign_id)
    assert result["dialled"] > 0, result


async def test_the_dial_gate_catches_a_blank_the_check_constraint_let_through() -> None:
    """The belt-and-braces branch, driven for real — and the reason it is not redundant.

    **`btrim()` TRIMS SPACES AND NOTHING ELSE.** Called with one argument, Postgres
    strips only U+0020, so `length(btrim(E'\t')) > 0` is TRUE and
    `ck_agents_ai_disclosure_nonempty` accepts a tab, a newline or a non-breaking space
    as an AI disclosure line. Python's `str.strip()` strips all of them, so
    `check_dispatch` reads the same value as blank and refuses to dial.

    The two disagree, and the disagreement is why the dial-time check earns its place:
    the schema believes the sentence is present, and the only thing that stops a caller
    hearing nothing is the gate. The test above documents the space-only case, which the
    constraint DOES catch; this one covers the whitespace the constraint misses.

    NOT reachable through the product — `ai_disclosure_line` is only ever written from
    `AI_DISCLOSURE_TEMPLATES[language]`, a server-side constant, and no route accepts it
    from a client. That is why this is left as a gate rather than closed with a tighter
    CHECK and a migration: the state is constructible only by direct SQL, which is
    precisely the "something bypassed the schema" case the branch names. If a
    client-writable path is ever added, the constraint must be tightened in the same
    change and this test becomes the regression that proves it.
    """
    tenant_id, agent_id, _, _, _ = await _launched()

    async with tenant_session(tenant_id) as session:
        # E'' is the escape-string syntax: a real tab, not a backslash and a 't'.
        await session.execute(
            text("UPDATE agents SET ai_disclosure_line = E'\\t' WHERE id = :a"),
            {"a": agent_id},
        )

    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(
                text("SELECT ai_disclosure_line FROM agents WHERE id = :a"), {"a": agent_id}
            )
        ).scalar_one()
        # The premise, asserted rather than assumed: the database really did accept it.
        assert stored == "\t", f"expected the tab to be stored verbatim, got {stored!r}"

        decision = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164="+919876600001"
        )

    assert decision.allowed is False, "a whitespace-only AI sentence must not dial"
    assert decision.rule == "disclosure_missing", decision


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

    # COUNTED PER NUMBER, not "is there a row". D-181 writes the call row BEFORE the
    # dial, so the person who was already rung has exactly one row from the attempt that
    # rang them — the fact this test wants on record. What must never appear is a
    # SECOND row for that number, which is what a re-dial would leave.
    async with tenant_session(tenant_id) as session:
        rings = (
            await session.execute(
                text("SELECT count(*) FROM calls WHERE direction = 'outbound' AND to_e164 = :p"),
                {"p": "+919876640001"},
            )
        ).scalar()
    assert int(rings or 0) == 1, (
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


# --------------------------------------- the CAMPAIGN's own switches, live, mid-batch


def _ist(hour: int, minute: int) -> datetime:
    """An instant whose IST wall clock is `hour:minute`.

    Built the way `compliance.service.ist_now` builds it — `now(UTC) + 5:30`, so the
    `.time()` of the returned value IS the IST clock. Spelled once here because two
    tests below judge the same campaign against two different hours.
    """
    return datetime(2026, 8, 11, hour, minute, tzinfo=UTC)


async def test_a_pause_landing_mid_batch_stops_the_contacts_behind_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pause button's twin of the big red switch test above, and it did not hold.

    The campaign's status IS re-read on the dispatch path — but inside the CLAIMING
    statement, which is the wrong side of the commit. The claim then commits and the
    batch dials one contact at a time with an engine round trip between each, so a pause
    pressed while the batch is in flight rang every remaining contact anyway. FLOWS §5's
    mid-campaign safeties (a complaint spike, a cap breach) auto-pause for precisely the
    moment when stopping fast is the point, and a stop that dials two more people is not
    a stop.

    The pause is committed from ANOTHER connection from inside the first dial, so the
    contacts under test are ones this tick has already claimed.
    """
    tenant_id, _, campaign_id, _, _ = await _launched(
        phones=("9876660001", "9876660002", "9876660003"), slider=3
    )
    original = FakeEngine.start_outbound_call
    dialled: list[str] = []

    async def pause_after_first(self: FakeEngine, ref: str, to: str, ctx: CallContext) -> str:
        handle = await original(self, ref, to, ctx)
        dialled.append(to)
        if len(dialled) == 1:
            async with tenant_session(tenant_id) as other:
                await campaigns.set_campaign_status(
                    other, campaign_id=campaign_id, to_status="paused", from_statuses=("running",)
                )
        return handle

    monkeypatch.setattr(FakeEngine, "start_outbound_call", pause_after_first)
    result = await _tick_one_campaign(tenant_id, campaign_id)

    # The POSITIVE half: contact one WAS dialable and rang. Without it, a pass here
    # would be indistinguishable from a fixture that could never have dialled anybody.
    assert dialled == ["+919876660001"], f"the pause did not beat the rest of the batch: {dialled}"
    assert result["dialled"] == 1 and result["blocked"] == 2, result
    assert await _calls_placed(tenant_id) == 1
    assert await _contacts(tenant_id, campaign_id) == [
        ("dialing", 1),
        ("pending", 0),
        ("pending", 0),
    ], "the two behind it wait, unpenalised — a pause is not a failed attempt"


async def test_a_campaign_window_that_closed_before_the_dial_stops_the_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`calling_hours` may only NARROW the platform's 09:00-21:00 IST window
    (`_validated_window`), so `check_dispatch` refusing outside the PLATFORM window
    cannot honour it. The narrowed window was read once, in `_run_tick`, before any
    tenant dialled — and the dial itself is a whole dial phase later, bounded only by
    the 300s job timeout.

    Both halves are asserted against the SAME campaign and the SAME two contacts: at
    12:05 IST — five minutes past a window the client closed at 12:00, and still well
    inside the platform's, so nothing else can be doing the refusing — nothing is
    dialled; at 11:00 IST both are.
    """
    tenant_id, _, campaign_id, _, _ = await _launched(phones=("9876670001", "9876670002"))
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaigns SET calling_hours = CAST(:w AS jsonb) WHERE id = :c"),
            {"w": '{"start": "09:00", "end": "12:00"}', "c": campaign_id},
        )

    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: _ist(12, 5))
    after_hours = await _tick_one_campaign(tenant_id, campaign_id)
    assert after_hours == {"dialled": 0, "blocked": 2, "exhausted": 0}, (
        "the campaign's own narrowed window was not re-asked at dial time and the batch "
        f"rang five minutes past the hour the client set: {after_hours}"
    )
    assert await _calls_placed(tenant_id) == 0
    assert await _contacts(tenant_id, campaign_id) == [("pending", 0), ("pending", 0)]

    # THE POSITIVE CONTROL: the identical two contacts, inside the window, ring.
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaign_contacts SET next_attempt_at = NULL WHERE campaign_id = :c"),
            {"c": campaign_id},
        )
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: _ist(11, 0))
    in_hours = await _tick_one_campaign(tenant_id, campaign_id)
    assert in_hours["dialled"] == 2, in_hours
    assert await _calls_placed(tenant_id) == 2


async def test_a_withdrawn_consent_settles_the_contact_rather_than_re_claiming_it_forever() -> None:
    """D-117 gave the gate a per-PERSON refusal and the dispatcher never learned it.

    `no_consent` says this person never agreed to be called, or withdrew the permission
    — a fact about them, not about our account, our agent or the clock. The dispatcher's
    only terminal rule was the literal `"dnc"`, so such a contact went back to `pending`
    with its attempt REFUNDED every thirty minutes, forever: the ladder can never
    exhaust it, `_reap_stuck_dialing` never sees it, and because a `pending` row
    survives, `complete_or_rearm` never completes the campaign — so the
    `campaign.completed` event a client subscribed to never fires either.

    Asserted as the whole loop: the contact is settled terminally, AND the campaign it
    was holding open finishes once the dialable contact resolves.
    """
    tenant_id, _, campaign_id, _, _ = await _launched(phones=("9876680001", "9876680002"))
    async with tenant_session(tenant_id) as session:
        # Written the way the front door writes it: `ingest.service` records exactly this
        # row for a lead-ad fill whose form carried no opt-in question (D-117).
        await session.execute(
            text(
                "INSERT INTO consent_ledger (id, tenant_id, phone_e164, purpose, status, "
                "consent_source, captured_at, created_at) VALUES (:id, :tid, :p, 'callback', "
                "'withdrawn', 'web_form_optin', now(), now())"
            ),
            {"id": uuid7(), "tid": tenant_id, "p": "+919876680002"},
        )

    result = await _tick_one_campaign(tenant_id, campaign_id)

    # POSITIVE half: the other contact on the same list was dialable and rang, so the
    # refusal below is about the consent row rather than about the fixture.
    assert result["dialled"] == 1 and result["blocked"] == 1, result
    async with tenant_session(tenant_id) as session:
        statuses = dict(
            (
                await session.execute(
                    text("SELECT phone_e164, status FROM campaign_contacts WHERE campaign_id = :c"),
                    {"c": campaign_id},
                )
            ).all()
        )
    assert statuses["+919876680002"] == "dnc_blocked", (
        "a person who withdrew permission is settled, not put back on the ladder"
    )

    # …and the campaign can now finish. Resolve the one real dial the way the post-call
    # pipeline does, then let the next tick close the campaign out.
    async with tenant_session(tenant_id) as session:
        call_id = (
            await session.execute(
                text("SELECT id FROM calls WHERE to_e164 = :p"), {"p": "+919876680001"}
            )
        ).scalar()
        await campaign_dispatch.resolve_campaign_contact(
            session, tenant_id=tenant_id, call_id=uuid.UUID(str(call_id)), call_status="completed"
        )
    await _tick_one_campaign(tenant_id, campaign_id)
    async with tenant_session(tenant_id) as session:
        final = (
            await session.execute(
                text("SELECT status FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar()
    assert final == "completed", "the consent-refused contact was holding the campaign open forever"


async def test_every_blocked_dial_records_the_rule_the_runbook_sends_operators_to(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """`runbooks/campaign-stall.md` §8 tells an operator that "a blocked dial increments
    the tick's `blocked=` count and the `compliance_blocks` metric (labelled by rule)".
    Only the first half was true: `record_compliance_block` fired for the once-per-
    campaign `dispatch_blockers` refusal and never for the per-DIAL one, so the metric
    was silent for the commonest stall there is and `blocked=2` named no desk.

    Both refusal shapes are driven through the real dispatcher, in the order the
    dispatcher asks them and therefore in two ticks: the per-contact one (DNC) on a
    campaign that is dialling normally, and the campaign-level one (a pause landing
    mid-batch) — which OUTRANKS the per-number question, so nothing refused by it is
    ever also refused by DNC. They settle through one helper and must stay labelled
    together.
    """
    tenant_id, _, campaign_id, _, _ = await _launched(
        phones=("9876690001", "9876690002", "9876690003"), slider=3
    )
    async with tenant_session(tenant_id) as session:
        await add_to_dnc(
            session, tenant_id=tenant_id, phone_e164="+919876690002", source="call_optout"
        )

    def _rules() -> list[str]:
        return [
            str(record.rule)
            for record in caplog.records
            if record.name == "calevate.metric"
            and getattr(record, "metric", None) == "compliance_blocks"
        ]

    with caplog.at_level(logging.INFO, logger="calevate.metric"):
        # Tick one: two dialable, one suppressed. The dials are the positive control.
        first = await _tick_one_campaign(tenant_id, campaign_id)
        assert first == {"dialled": 2, "blocked": 1, "exhausted": 0}, first
        assert _rules() == ["dnc"], _rules()

        # Tick two: the same campaign, paused from another connection mid-batch.
        caplog.clear()
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "UPDATE campaign_contacts SET status = 'pending', attempts = 0, "
                    "next_attempt_at = NULL WHERE campaign_id = :c AND status = 'dialing'"
                ),
                {"c": campaign_id},
            )
        original = FakeEngine.start_outbound_call
        dialled: list[str] = []

        async def pause_after_first(self: FakeEngine, ref: str, to: str, ctx: CallContext) -> str:
            handle = await original(self, ref, to, ctx)
            dialled.append(to)
            if len(dialled) == 1:
                async with tenant_session(tenant_id) as other:
                    await campaigns.set_campaign_status(
                        other,
                        campaign_id=campaign_id,
                        to_status="paused",
                        from_statuses=("running",),
                    )
            return handle

        monkeypatch.setattr(FakeEngine, "start_outbound_call", pause_after_first)
        second = await _tick_one_campaign(tenant_id, campaign_id)

    assert second == {"dialled": 1, "blocked": 1, "exhausted": 0}, second
    assert _rules() == [campaigns.CAMPAIGN_STOPPED_RULE], _rules()


async def test_the_halt_still_stops_the_dial_when_redis_is_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The big red switch's fast path is a Redis hash. A gate that fails OPEN when that
    hash is unreachable is not a gate — it is a switch that stops working during exactly
    the kind of afternoon somebody reaches for it.

    Failing open here is a natural thing to write, and this repo does it deliberately one
    layer up: `_tick_lease` yields True on a Redis error, because a tick that refuses to
    run is a campaign that stops dialling and the claim CAS still prevents a double dial.
    The halt is the opposite trade and the reason is the direction of the mistake — a
    lease that fails open costs a shared line, a halt that fails open dials a stranger
    during an incident. `loadshed.get_platform_status` therefore treats an unreachable
    cache as a MISS and reads `platform_state`; nothing pinned that, and nothing would
    have noticed it being "simplified" into a swallowed exception returning `normal`.

    Nothing global is written: the durable read is STUBBED and the cache key is private,
    so a halt cannot leak into another suite sharing this Postgres.
    """
    tenant_id, _, campaign_id, _, _ = await _launched(phones=("9876700001", "9876700002"))

    class _DeadRedis:
        """Every path `get_platform_status` can take to Redis, refused."""

        def pipeline(self, *args: Any, **kwargs: Any) -> Any:
            raise ConnectionError("redis is unreachable")

        async def delete(self, *args: Any, **kwargs: Any) -> int:
            raise ConnectionError("redis is unreachable")

    halted = True

    async def _durable() -> loadshed.PlatformStatus:
        return loadshed.PlatformStatus(mode="normal", outbound_halted=halted)

    monkeypatch.setattr(loadshed, "_REDIS_KEY", f"calevate:test:{uuid.uuid4().hex}")
    monkeypatch.setattr(loadshed, "_memo", None)
    monkeypatch.setattr(loadshed, "_read_durable", _durable)
    monkeypatch.setattr(loadshed, "get_redis", _DeadRedis)

    blocked = await _tick_one_campaign(tenant_id, campaign_id)
    assert blocked == {"dialled": 0, "blocked": 2, "exhausted": 0}, (
        f"the halt failed OPEN while Redis was unreachable and the tick dialled: {blocked}"
    )
    assert await _calls_placed(tenant_id) == 0, "a dial went out through the halt"
    assert await _contacts(tenant_id, campaign_id) == [("pending", 0), ("pending", 0)], (
        "a halt is not a failed attempt — the ladder must not be spent on it"
    )

    # THE POSITIVE CONTROL: the same unreachable Redis, the same two contacts, the switch
    # released. Without it, a gate that refused everything for any reason would pass.
    halted = False
    monkeypatch.setattr(loadshed, "_memo", None)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaign_contacts SET next_attempt_at = NULL WHERE campaign_id = :c"),
            {"c": campaign_id},
        )
    released = await _tick_one_campaign(tenant_id, campaign_id)
    assert released["dialled"] == 2, released


# ------------------------------- the dial whose answer never came back (R-1, D-181)


async def _engine_call_ids(tenant_id: uuid.UUID) -> list[str]:
    async with tenant_session(tenant_id) as session:
        return [
            str(r[0])
            for r in (
                await session.execute(
                    text(
                        "SELECT engine_call_id FROM calls WHERE direction = 'outbound' "
                        "ORDER BY created_at"
                    )
                )
            ).all()
        ]


async def test_a_dial_whose_response_is_lost_leaves_a_call_row_and_is_never_re_rung(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The vendor accepted and the answer never arrived — a read timeout, a reset, a
    proxy 502 after the engine had committed. The phone is ringing and the HTTP call
    raised.

    Two properties, and the platform had neither. **A call row exists**, so the charge is
    not invisible and the contact is linked to it; and **the person is not dialled
    again**, which used to happen twice over — `_record_failure` returned the contact to
    `pending` with a rung left, and `_reap_stuck_dialing` would have done it again for a
    contact stuck in `dialing` with no `last_call_id`.

    Written against the shape of the defect rather than its symptom: the engine raises
    AFTER it has been asked, which is exactly the window the old ordering could not
    write a row in, because the row's key was the answer that never came.
    """
    tenant_id, _, campaign_id, _, _ = await _launched(phones=("9876810001",), slider=1)

    async def lost_response(self: FakeEngine, ref: str, to: str, ctx: CallContext) -> str:
        raise ProblemError(
            kind="dependency",
            code="engine_unreachable",
            title="Voice engine unreachable",
            detail="The voice platform did not respond.",
        )

    monkeypatch.setattr(FakeEngine, "start_outbound_call", lost_response)
    outcome = await _tick_one_campaign(tenant_id, campaign_id, slots=1)
    assert outcome == {"dialled": 0, "blocked": 0, "exhausted": 1}, outcome

    ids = await _engine_call_ids(tenant_id)
    assert len(ids) == 1, f"the possible charge has to be on record: {ids}"
    assert ids[0].startswith(UNCONFIRMED_ENGINE_CALL_PREFIX), (
        "the row exists but the vendor never named it — that is the state to be able to find"
    )

    async with tenant_session(tenant_id) as session:
        linked = (
            await session.execute(
                text(
                    "SELECT cc.status, c.id IS NOT NULL FROM campaign_contacts cc "
                    "LEFT JOIN calls c ON c.id = cc.last_call_id WHERE cc.campaign_id = :c"
                ),
                {"c": campaign_id},
            )
        ).all()
    assert [(str(r[0]), bool(r[1])) for r in linked] == [("failed", True)], (
        "the contact points at the call we may have placed, and is finished with — "
        "anything that returns it to `pending` rings a real person a second time"
    )

    # The next tick is the second ring, if there is going to be one. The engine works
    # again, so nothing but the contact's own state can stop it.
    monkeypatch.undo()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaign_contacts SET next_attempt_at = NULL WHERE campaign_id = :c"),
            {"c": campaign_id},
        )
    again = await _tick_one_campaign(tenant_id, campaign_id, slots=1)
    assert again["dialled"] == 0, f"the same person was dialled again: {again}"
    assert len(await _engine_call_ids(tenant_id)) == 1


async def test_a_dial_the_vendor_refused_outright_keeps_its_place_on_the_ladder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other side of the same branch, and the reason it is a branch at all.

    A 429 with the throttle ladder exhausted says nothing about the request and seizes no
    line, so the contact goes back on the ladder like any other failed attempt — treating
    it as "may have rung" would burn a reachable lead for a reason that was ours. The
    call row is closed as `failed` rather than left `queued`: nothing rang, so it must
    not sit in the in-flight bucket forever.
    """
    tenant_id, _, campaign_id, _, _ = await _launched(phones=("9876820001",), slider=1)

    async def rate_limited(self: FakeEngine, ref: str, to: str, ctx: CallContext) -> str:
        raise ProblemError(
            kind="transient",
            code="engine_rate_limited",
            title="Voice engine is rate limiting us",
            detail="The voice platform is temporarily refusing new requests.",
        )

    monkeypatch.setattr(FakeEngine, "start_outbound_call", rate_limited)
    outcome = await _tick_one_campaign(tenant_id, campaign_id, slots=1)
    assert outcome == {"dialled": 0, "blocked": 0, "exhausted": 0}, outcome
    assert await _contacts(tenant_id, campaign_id) == [("pending", 1)], (
        "a refusal that reached no line leaves the contact on the ladder"
    )
    async with tenant_session(tenant_id) as session:
        statuses = (
            (
                await session.execute(
                    text("SELECT status FROM calls WHERE direction = 'outbound'"),
                )
            )
            .scalars()
            .all()
        )
    assert [str(s) for s in statuses] == ["failed"], statuses


async def test_the_retry_ladder_is_measured_by_the_database_clock() -> None:
    """`_record_failure` used to schedule the next rung from the WORKER's clock while the
    claim reads it back against the DATABASE's (`next_attempt_at <= now()`). A worker
    running behind the database made every rung early by the skew, and an early rung on a
    retry ladder is a second call to a person sooner than the policy allows.

    Read back against the database's own `now()`: with the interval computed in SQL the
    two can only agree, and any app-side arithmetic shows up as the skew between the
    hosts (which on one host is zero, so the assertion is about WHERE the value came
    from, not about how far apart two clocks happen to be today).
    """
    tenant_id, _, campaign_id, _, _ = await _launched(phones=("9876830001",), slider=1)
    async with tenant_session(tenant_id) as session:
        contact_id = (
            await session.execute(
                text("SELECT id FROM campaign_contacts WHERE campaign_id = :c"),
                {"c": campaign_id},
            )
        ).scalar()
        spent = await campaign_dispatch._record_failure(
            session,
            uuid.UUID(str(contact_id)),
            1,
            3,
            {"backoff_minutes": [30]},
            tenant_id=tenant_id,
            campaign_id=campaign_id,
        )
        assert spent is False
        drift_s = (
            await session.execute(
                text(
                    "SELECT EXTRACT(EPOCH FROM (next_attempt_at - (now() + interval '30 minutes')))"
                    " FROM campaign_contacts WHERE id = :id"
                ),
                {"id": contact_id},
            )
        ).scalar()
    assert abs(float(drift_s or 0)) < 1.0, (
        f"the rung is {drift_s}s away from the database's own idea of +30 minutes"
    )


async def test_the_reaper_does_not_return_an_unconfirmed_dial_to_the_ladder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The case that outruns an `except` clause, and the reason `_reap_stuck_dialing`
    grew a second branch.

    A `CancelledError` through the dial — a worker caught mid-tick by a deploy, or a
    cron tick overrunning `job_timeout` — is a `BaseException`, so the dispatcher's
    `except DialUnconfirmedError` never sees it and the contact is left `dialing`
    pointing at a call the vendor never named. Thirty minutes later the reaper used to
    return exactly that contact to `pending`, with its attempts intact, and the next tick
    rang a phone that may already have rung.
    """
    tenant_id, _, campaign_id, _, _ = await _launched(phones=("9876840001",), slider=1)
    original = FakeEngine.start_outbound_call

    async def killed_mid_dial(self: FakeEngine, ref: str, to: str, ctx: CallContext) -> str:
        await original(self, ref, to, ctx)
        raise asyncio.CancelledError

    monkeypatch.setattr(FakeEngine, "start_outbound_call", killed_mid_dial)
    with pytest.raises(asyncio.CancelledError):
        await _tick_one_campaign(tenant_id, campaign_id, slots=1)
    monkeypatch.undo()

    assert await _contacts(tenant_id, campaign_id) == [("dialing", 1)], (
        "the committed claim is what keeps the contact out of the next tick's reach"
    )

    # Past `STUCK_DIALING_AFTER`. The reaper runs at the top of every tick, and the
    # horizon is derived from `CALL_CAP_MAX_S` rather than fixed at 30 minutes (D-365),
    # so this ages by the constant instead of restating a number it no longer matches.
    await _age_dialing(tenant_id, campaign_id, campaign_dispatch.STUCK_DIALING_AFTER + MINUTE)
    swept = await _tick_one_campaign(tenant_id, campaign_id, slots=1)

    assert swept["dialled"] == 0, f"the reaper handed the contact back to the dialler: {swept}"
    assert await _contacts(tenant_id, campaign_id) == [("failed", 1)], (
        "a dial we cannot prove did not ring is terminal, not a rung on the ladder"
    )
    ids = await _engine_call_ids(tenant_id)
    assert len(ids) == 1 and ids[0].startswith(UNCONFIRMED_ENGINE_CALL_PREFIX), ids


# ------------------------------- the reaper's horizon versus a call still in progress


MINUTE = timedelta(minutes=1)


async def _age_dialing(tenant_id: uuid.UUID, campaign_id: uuid.UUID, elapsed: timedelta) -> None:
    """Push a claimed contact's `last_attempt_at` back by `elapsed`.

    That column is stamped by the CLAIM, before the dial, so it is the call's own clock —
    which is exactly why the reaper's horizon has to outlive the call.
    """
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE campaign_contacts SET last_attempt_at = now() - "
                "make_interval(secs => :secs) WHERE campaign_id = :c"
            ),
            {"c": campaign_id, "secs": elapsed.total_seconds()},
        )


def test_the_reaper_outlives_the_longest_call_an_agent_may_be_configured_for() -> None:
    """The arithmetic behind D-365, asserted rather than left in a comment.

    `STUCK_DIALING_AFTER` used to be a 30-minute SQL literal described as "far longer
    than any call we bill for". `CALL_CAP_MAX_S` lets a client configure an hour.
    """
    assert timedelta(seconds=CALL_CAP_MAX_S) < campaign_dispatch.STUCK_DIALING_AFTER, (
        "a contact is reaped while its own call is still legally in progress, and the "
        "reap puts that person back on the dialling ladder"
    )


async def test_a_contact_whose_call_is_still_in_progress_is_not_returned_to_the_ladder() -> None:
    """THE DEFECT D-365 CLOSES: the reaper redialling somebody who is still on the phone.

    A contact is claimed at T and stamped `last_attempt_at = T` BEFORE the dial. On an
    agent with a long `max_call_duration_s` — the platform permits `CALL_CAP_MAX_S`, an
    hour — the conversation is still running at T+31m. With the horizon at 30 minutes the
    tick at T+31m swept that contact back to `pending` with a rung 30 minutes out, and
    the tick after that DIALLED THE SAME PERSON AGAIN while the first call was live or
    barely finished.

    The second casualty is the accounting: `resolve_campaign_contact` matches on
    `last_call_id` AND `status = 'dialing'`, so once the reaper moved the row the
    conversation that actually happened could never be recorded as `connected` — the
    campaign's `reached` count under-reported it and the contact could still be exhausted
    into `failed` having been reached.

    Driven end to end: dial, age past the OLD horizon, tick, and assert nothing moved.
    """
    tenant_id, _, campaign_id, _, _ = await _launched(phones=("9876850001",), slider=1)
    assert (await _tick_one_campaign(tenant_id, campaign_id, slots=1))["dialled"] == 1
    assert await _contacts(tenant_id, campaign_id) == [("dialing", 1)]
    placed = await _calls_placed(tenant_id)

    # T+31 minutes: past the old literal, well inside a call the platform permits.
    await _age_dialing(tenant_id, campaign_id, timedelta(minutes=31))
    swept = await _tick_one_campaign(tenant_id, campaign_id, slots=1)

    assert swept["dialled"] == 0, (
        f"the reaper handed a contact whose call is still in progress back to the "
        f"dialler, and the dialler rang them a second time: {swept}"
    )
    assert await _contacts(tenant_id, campaign_id) == [("dialing", 1)], (
        "the contact left `dialing`, so the finished call can no longer be matched to it "
        "by `resolve_campaign_contact` — the conversation is lost to the campaign's books"
    )
    assert await _calls_placed(tenant_id) == placed, "a second call was placed to one person"

    # And the backstop still works once the call cannot possibly still be running.
    await _age_dialing(tenant_id, campaign_id, campaign_dispatch.STUCK_DIALING_AFTER + MINUTE)
    await _tick_one_campaign(tenant_id, campaign_id, slots=0)
    assert [status for status, _ in await _contacts(tenant_id, campaign_id)] == ["pending"], (
        "a genuinely stranded contact must still come back to the ladder eventually"
    )
