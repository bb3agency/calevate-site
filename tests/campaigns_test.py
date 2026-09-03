"""Campaigns: the launch gate, the DNC scrub, the dispatch ceilings, the retry ladder.

This suite exists because hard rule 5 names campaigns specifically — "campaign launch
path must call the compliance gate — never add a bypass 'for testing'". So the tests
are written the way a regulator would read them:

- a campaign with an unapproved template, a mismatched number series, or a draft agent
  does not launch, and says WHY for each failure at once;
- a number on the DNC list at launch is scrubbed, and a number that joins the list
  AFTER launch is still never dialled;
- one tenant's campaign cannot consume the lines another tenant's receptionist needs;
- an unanswered dial comes back later instead of hammering the same number.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import service as agents_service
from apps.api.campaigns import service
from apps.api.compliance.preference_scrub import PREFERENCE_SCRUBBED_CLASSIFICATIONS
from apps.api.compliance.service import add_to_dnc
from apps.api.core import loadshed
from apps.api.core.errors import InvalidStatusTransitionError, ProblemError
from apps.api.core.loadshed import set_platform_status
from apps.api.db.base import uuid7
from apps.api.db.session import admin_session, tenant_session, untenanted_session
from apps.api.engine import reset_engine_cache
from apps.workers import campaign_dispatch
from apps.workers.campaign_dispatch import (
    ACTIVE_STATUSES,
    dispatch_campaign_tick,
    resolve_campaign_contact,
)
from pydantic import ValidationError
from sqlalchemy import text
from tests.conftest import accept_agreements, fund_wallet
from tests.national_dnd_test import record_test_scrub


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the gate's clock to 11:00 IST — see lead_ingest_test for the story. The
    calling-hours rule is exercised deliberately in its own test below."""
    fixed = datetime(2026, 8, 11, 5, 30, tzinfo=UTC) + timedelta(hours=5, minutes=30)
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: fixed)


@pytest.fixture(autouse=True)
def _roomy_platform_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the PLATFORM line pool (FLOWS §5 rule 1) above anything this module dials.

    `_quiesce` settles the calls and campaigns this module created; it cannot settle
    the ones a SECOND pytest process is creating right now against the same Postgres,
    and the outbound pool is deliberately platform-wide. At the pilot default of 10
    lines (6 after the inbound reserve), five in-flight calls belonging to somebody
    else's run leave a budget of ONE — the tick then claims one contact instead of two,
    and the DNC-after-launch test below fails on the contact it never reached. That is
    the dispatcher obeying rule 1 correctly; the test was the thing assuming it had the
    platform to itself.

    Nothing under test is weakened: rule 1 is asserted nowhere in this module, and the
    ceilings these tests DO measure — the per-tenant `concurrency_ceiling` (rule 3) and
    the per-campaign slider (rule 4) — are per tenant and untouched by the pool size.
    """
    monkeypatch.setattr(campaign_dispatch, "PLATFORM_LINES_TOTAL", 10_000)


# Tenants this module created, and whether the one-time sweep of earlier runs has run.
# Both exist so `_quiesce` stays O(this suite) instead of O(every org ever seeded).
_TENANTS: list[uuid.UUID] = []
_swept = False
# When this process started. Anything created after it belongs to a test that is
# running right now — possibly in another pytest process — and is not ours to cancel.
_RUN_STARTED_AT = datetime.now(UTC)


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    """A tenant whose agent is live and published — the campaign-ready baseline."""
    reset_engine_cache()
    created = await admin_service.create_organization(
        name="Camp Motors",
        slug=f"camp-{uuid.uuid4().hex[:8]}",
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
    # And credit, for the same reason and in the same shape (D-521): `prepaid` is the
    # default motion now, so an unfunded tenant is refused `no_credits` on every
    # outbound dial and this file would report that in place of what it is about.
    await fund_wallet(uuid.UUID(str(created["id"])))
    tenant_id, agent_id = created["id"], created["agent_id"]
    ref = f"fakeagent_camp_{uuid.uuid4().hex[:8]}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agents SET status = 'live', direction = 'outbound', "
                "engine_agent_ref = :r WHERE id = :a"
            ),
            {"r": ref, "a": agent_id},
        )
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('fake', :r, :t, :a, true, now(), now())"
            ),
            {"r": ref, "t": tenant_id, "a": agent_id},
        )
    # A live PE registration and TM link. The launch gate now refuses a tenant without
    # one (SEC-COMP §3), which is correct — a campaign dialled from an unregistered
    # Principal Entity is the misclassification that gets the traffic filed as spam
    # against the CLIENT. These fixtures predate the requirement, so they have to supply
    # it rather than the gate being softened to accommodate them.
    async with tenant_session(tenant_id) as session:
        await service.record_dlt_registration(
            session,
            tenant_id=tenant_id,
            pe_id=f"1102{uuid.uuid4().int % 10**9:09d}",
            entity_name="Camp Motors Pvt Ltd",
            status="active",
            tm_link_status="active",
            registered_at=datetime.now(UTC) - timedelta(days=30),
        )
    _TENANTS.append(tenant_id)
    return tenant_id, agent_id


async def _create_campaign(session: Any, **kwargs: Any) -> uuid.UUID:
    """`create_campaign` with the consent provenance the launch gate now requires.

    A default here rather than at eight call sites, and a default in the TEST rather
    than in the service: the gate refusing a campaign that cannot say where its list
    came from is the behaviour we want (SEC-COMP §3), so the fixtures supply an answer
    instead of the requirement being softened to fit them. Any test that wants the
    missing-provenance case passes `consent_source=None` explicitly.
    """
    kwargs.setdefault("consent_source", "existing_customer")
    kwargs.setdefault("consent_collected_at", datetime.now(UTC) - timedelta(days=7))
    return await service.create_campaign(session, **kwargs)


async def _number(
    session: Any, tenant_id: uuid.UUID, series: str, *, agent_id: uuid.UUID
) -> uuid.UUID:
    """A registered header BOUND TO `agent_id`, because an unbound one is not launchable.

    `agent_id` is keyword-only and has no default on purpose (D-424). A campaign's number
    must be the number its agent dials from — `_channel_blockers` refuses the campaign
    otherwise, since a number bound to nobody resolves to no caller ID and the engine
    answers from its own pool. A fixture with a default would let the next launch-ready
    fixture be silently un-launchable, which is exactly the state this helper produced
    before the gate closed.
    """
    number_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO phone_numbers (id, tenant_id, agent_id, e164, series, dlt_status, "
            "created_at, updated_at) VALUES (:id, :tid, :aid, :e, :s, 'registered', now(), now())"
        ),
        {
            "id": number_id,
            "tid": tenant_id,
            "aid": agent_id,
            "e": f"+9180{uuid.uuid4().int % 100000000:08d}",
            "s": series,
        },
    )
    return number_id


async def _template(
    session: Any, tenant_id: uuid.UUID, classification: str, status: str = "approved"
) -> uuid.UUID:
    template_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO dlt_templates (id, tenant_id, kind, classification, body, status, "
            "created_at, updated_at) VALUES (:id, :tid, 'voice', :cls, :body, :st, now(), now())"
        ),
        {
            "id": template_id,
            "tid": tenant_id,
            "cls": classification,
            "body": "Hello from {#var#}, this is an AI assistant calling about your enquiry.",
            "st": status,
        },
    )
    return template_id


async def _ready_campaign(
    *,
    classification: str = "promotional",
    series: str = "140",
    template_status: str = "approved",
    template_classification: str | None = None,
    phones: tuple[str, ...] = ("9876500001", "9876500002", "9876500003"),
    concurrency: int = 3,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """(tenant_id, agent_id, campaign_id) — launch-ready unless a knob says otherwise."""
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        number_id = await _number(session, tenant_id, series, agent_id=agent_id)
        template_id = await _template(
            session, tenant_id, template_classification or classification, template_status
        )
        campaign_id = await _create_campaign(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Diwali offers",
            classification=classification,
            number_id=number_id,
            dlt_template_id=template_id,
            concurrency=concurrency,
            # Where this list came from. The gate refuses a campaign that cannot say,
            # and "existing_customer" is the honest answer for a fixture whose contacts
            # are invented — not the most permissive value, but the one that matches
            # what the test is pretending to be.
            consent_source="existing_customer",
            consent_collected_at=datetime.now(UTC) - timedelta(days=7),
        )
        if phones:
            await service.add_contacts(
                session,
                tenant_id=tenant_id,
                campaign_id=campaign_id,
                contacts=[{"phone": p, "name": f"Lead {p[-4:]}"} for p in phones],
            )
        # The national DND scrub (SEC-COMP §3, migration a1c8e40f27b9). A promotional
        # campaign is launch-ready only once an access provider's DLT platform has
        # scrubbed its list, so a fixture that claims to build one has to say so —
        # recorded AFTER the contacts, because the run covers the list that existed when
        # it ran. Supplied through the production writer and softening nothing:
        # `tests/national_dnd_test.py` proves the refusal by leaving it out.
        if classification in PREFERENCE_SCRUBBED_CLASSIFICATIONS:
            await record_test_scrub(session, campaign_id)
    return tenant_id, agent_id, campaign_id


async def _sweep(tenants: list[uuid.UUID], keep: tuple[uuid.UUID, ...]) -> None:
    for tenant_id in tenants:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "UPDATE campaigns SET status = 'cancelled', updated_at = now() "
                    "WHERE status = 'running' AND NOT (id = ANY(CAST(:keep AS uuid[])))"
                ),
                {"keep": [str(k) for k in keep] or [str(uuid7())]},
            )
            await session.execute(
                text(
                    "UPDATE calls SET status = 'completed', updated_at = now() "
                    f"WHERE status IN {ACTIVE_STATUSES!r}"
                )
            )


async def _quiesce(*keep: uuid.UUID) -> None:
    """Give the dispatcher a quiet platform to be measured on.

    Each dispatcher test first settles the campaigns and calls its predecessors in THIS
    module left running, keeping only its own, so a tick is measured on the state the
    test staged rather than on the leftovers of the test before it.

    The first call additionally sweeps what EARLIER RUNS of this module left behind: a
    persistent dev/CI Postgres still holds their `running` campaigns. That sweep is
    scoped two ways, and both are load-bearing:

    - `slug LIKE 'camp-%'` — only tenants this module created. It used to cancel every
      running campaign in the database, which on a shared Postgres means cancelling
      whatever ANOTHER pytest process launched a second ago, in the middle of its test.
    - `created_at < _RUN_STARTED_AT` — only rows that predate this process, so a
      concurrent run of this same file sweeps its own leftovers and not ours.

    What made the wide sweep unnecessary is `_roomy_platform_pool`: the reason to quiet
    the whole platform was the shared outbound pool, and pinning that above anything
    this module dials removes the coupling far more cheaply than cancelling other
    people's work. (It is also ~14,000 fewer sessions per run.)
    """
    global _swept
    if not _swept:
        async with admin_session() as directory:
            earlier_runs = (
                (
                    await directory.execute(
                        text(
                            "SELECT id FROM organizations WHERE deleted_at IS NULL "
                            "AND slug LIKE 'camp-%' AND created_at < :started"
                        ),
                        {"started": _RUN_STARTED_AT},
                    )
                )
                .scalars()
                .all()
            )
        await _sweep([uuid.UUID(str(t)) for t in earlier_runs], keep)
        _swept = True
    await _sweep(_TENANTS, keep)


# --------------------------------------------------------------------------- contacts


async def test_contact_upload_dedupes_and_counts_malformed_without_guessing() -> None:
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        campaign_id = await _create_campaign(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="CSV import",
            classification="service",
            number_id=None,
            dlt_template_id=None,
            concurrency=3,
        )
        first = await service.add_contacts(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            contacts=[
                {"phone": "9876511111", "name": "Ravi"},
                {"phone": "+91 98765 11111", "name": "Ravi again"},  # same number, other format
                {"phone": "12345"},  # too short to dial
                {"phone": "5551234567"},  # not an Indian mobile shape
                {"phone": "+15551234567"},  # well-formed but non-India: dropped under freeze
                {"phone": "9876522222", "name": "Sita", "city": "Hyderabad"},
            ],
        )
        # A re-uploaded CSV must not re-queue the same people.
        second = await service.add_contacts(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            contacts=[{"phone": "9876511111"}, {"phone": "9876533333"}],
        )
        rows = (
            await session.execute(
                text(
                    "SELECT phone_e164, custom FROM campaign_contacts WHERE campaign_id = :c "
                    "ORDER BY phone_e164"
                ),
                {"c": campaign_id},
            )
        ).all()

    assert first == {"added": 2, "malformed": 2, "duplicate": 1, "foreign": 1}
    assert second == {"added": 1, "duplicate": 1, "malformed": 0, "foreign": 0}
    assert [r[0] for r in rows] == ["+919876511111", "+919876522222", "+919876533333"]
    assert rows[1][1] == {"city": "Hyderabad"}, "extra CSV columns ride along for the prompt"


async def test_a_contact_upload_stores_no_hash_of_the_number() -> None:
    """`campaign_contacts.dedupe_hash` is not written any more, and this is why.

    It held `sha256(phone)[:16]`, unsalted, in the table whose erasure story is that the
    number goes — and Indian mobile E.164 is a ~10^9 space, so a truncated unsalted digest
    of one is the number back in a few seconds of enumeration. Nothing read it: the batch
    dedupes on `seen` and cross-batch on `ON CONFLICT (campaign_id, phone_e164)`, both on
    the number itself. Kept as a live assertion rather than a comment because the tempting
    "fix" for the guard that flags it is to put the write back with a reader bolted on.
    """
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        campaign_id = await _create_campaign(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="no hash",
            classification="service",
            number_id=None,
            dlt_template_id=None,
            concurrency=1,
        )
        await service.add_contacts(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            contacts=[{"phone": "9876544444"}],
        )
        hashes = (
            (
                await session.execute(
                    text("SELECT dedupe_hash FROM campaign_contacts WHERE campaign_id = :c"),
                    {"c": campaign_id},
                )
            )
            .scalars()
            .all()
        )

    assert hashes == [None], "the upload must leave no derivative of the phone number"


async def test_contacts_cannot_be_added_to_a_running_campaign() -> None:
    tenant_id, _, campaign_id = await _ready_campaign()
    async with tenant_session(tenant_id) as session:
        await service.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
        with pytest.raises(ProblemError) as excinfo:
            await service.add_contacts(
                session,
                tenant_id=tenant_id,
                campaign_id=campaign_id,
                contacts=[{"phone": "9876544444"}],
            )
    assert excinfo.value.code == "campaign_not_draft"


# ----------------------------------------------------------------------- launch gate


async def test_the_launch_gate_names_every_blocker_at_once() -> None:
    """SURFACES §2b: a disabled button with reasons. Fail-fast would make the client
    fix one thing, click, and be refused again — four times."""
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET status = 'draft' WHERE id = :a"), {"a": agent_id}
        )
        campaign_id = await _create_campaign(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Nothing is ready",
            classification="promotional",
            number_id=None,
            dlt_template_id=None,
            concurrency=3,
        )
        blockers = await service.launch_blockers(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
        rules = {b.rule for b in blockers}

    assert rules == {
        "agent_not_live",
        "dlt_template_missing",
        "number_missing",
        "no_contacts",
        # SEC-COMP §3's DNC bullet, national half (migration a1c8e40f27b9): a promotional
        # campaign whose list no access provider has preference-scrubbed is refused by
        # name, alongside everything else that is not ready.
        "national_dnd_scrub_missing",
    }
    assert all(b.reason.strip() for b in blockers), "every blocker tells the client what to do"


async def test_a_promotional_campaign_cannot_dial_from_a_160_number() -> None:
    """140 ⇔ promotional, 160/standard ⇔ service & transactional (DATA-MODEL §6). A
    mismatch is a DLT violation, so it blocks launch rather than warning."""
    tenant_id, _, campaign_id = await _ready_campaign(classification="promotional", series="160")
    async with tenant_session(tenant_id) as session:
        blockers = await service.launch_blockers(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
    mismatch = [b for b in blockers if b.rule == "number_series_mismatch"]
    assert mismatch, [b.rule for b in blockers]
    assert "140" in mismatch[0].reason and "160" in mismatch[0].reason


async def test_a_service_campaign_may_use_either_160_or_standard() -> None:
    for series in ("160", "standard"):
        tenant_id, _, campaign_id = await _ready_campaign(classification="service", series=series)
        async with tenant_session(tenant_id) as session:
            blockers = await service.launch_blockers(
                session, tenant_id=tenant_id, campaign_id=campaign_id
            )
        assert blockers == [], f"{series} should serve a service campaign: {blockers}"


async def test_an_unapproved_or_mismatched_dlt_template_blocks_launch() -> None:
    tenant_id, _, pending = await _ready_campaign(template_status="submitted")
    other_tenant, _, mismatched = await _ready_campaign(
        classification="promotional", template_classification="service"
    )
    async with tenant_session(tenant_id) as session:
        pending_blockers = await service.launch_blockers(
            session, tenant_id=tenant_id, campaign_id=pending
        )
    async with tenant_session(other_tenant) as session:
        mismatch_blockers = await service.launch_blockers(
            session, tenant_id=other_tenant, campaign_id=mismatched
        )
    assert [b.rule for b in pending_blockers] == ["dlt_template_not_approved"]
    assert [b.rule for b in mismatch_blockers] == ["dlt_template_mismatch"]


async def test_an_unapproved_and_mismatched_template_reports_both_blockers_at_once() -> None:
    """Approval and classification are independent properties of the attached template,
    so a template failing both is reported as a LIST (SEC-COMP §3's "deliberately
    exhaustive rather than fail-fast"). This used to be an `elif`, and a client who
    chased the registrar's approval on a wrongly-classified template learnt about the
    second blocker only after clearing the first."""
    tenant_id, _, campaign_id = await _ready_campaign(
        classification="promotional",
        template_status="submitted",
        template_classification="service",
    )
    async with tenant_session(tenant_id) as session:
        blockers = await service.launch_blockers(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
    rules = [b.rule for b in blockers]
    assert rules == ["dlt_template_not_approved", "dlt_template_mismatch"], rules


async def test_template_and_number_refusals_name_the_next_action_per_state() -> None:
    """The error ladder: every failure a client can reach says what to do next, so a
    reason may never be just a status ("The DLT template is submitted." was one). Each
    non-approved state ends differently, so the sentences must differ — and each must
    carry its own next action, pinned by the words that name it."""
    draft = service._template_not_approved_reason("draft")
    submitted = service._template_not_approved_reason("submitted")
    rejected = service._template_not_approved_reason("rejected")
    assert len({draft, submitted, rejected}) == 3, "three states, three next actions"
    assert "File it" in draft
    assert "approval is recorded" in submitted
    assert "Revise" in rejected
    # A state the map has never met still fails closed with an instruction, not a status.
    assert "Attach an approved one" in service._template_not_approved_reason("suspended")

    pending = service._number_not_registered_reason("pending")
    blocked = service._number_not_registered_reason("blocked")
    assert pending != blocked
    assert "registrar approves" in pending
    assert "Pick a different" in blocked
    assert "Pick a registered number" in service._number_not_registered_reason("withdrawn")


async def test_a_template_status_outside_the_enum_is_refused_by_name() -> None:
    """A status the enum does not hold is a validation refusal naming the members, not
    an IntegrityError 500 off the DB CHECK — the same guard `record_dlt_registration`
    keeps for the PE statuses."""
    tenant_id, _ = await _tenant()
    async with tenant_session(tenant_id) as session:
        template_id = await _template(session, tenant_id, "promotional", "submitted")
        with pytest.raises(ProblemError) as excinfo:
            await service.set_template_status(session, template_id=template_id, status="suspended")
    assert excinfo.value.code == "template_status_invalid"
    assert "approved" in (excinfo.value.detail or "")


async def test_launch_check_on_a_running_campaign_names_the_status_blocker() -> None:
    """`/launch-check` is also asked of campaigns that are past launching, and the
    answer has to name the state rather than list paperwork a running campaign cannot
    act on being told about."""
    tenant_id, _, campaign_id = await _ready_campaign(classification="service", series="160")
    async with tenant_session(tenant_id) as session:
        await service.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
        blockers = await service.launch_blockers(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
    status_blockers = [b for b in blockers if b.rule == "status"]
    assert status_blockers, [b.rule for b in blockers]
    assert "running" in status_blockers[0].reason


async def test_launch_is_refused_with_the_same_named_reasons_the_check_returned() -> None:
    """The check endpoint is a PREVIEW of the gate, never a substitute — so launching
    past a red check must fail with the identical rule names."""
    tenant_id, _, campaign_id = await _ready_campaign(series="160")
    async with tenant_session(tenant_id) as session:
        preview = await service.launch_blockers(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
        with pytest.raises(ProblemError) as excinfo:
            await service.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
        status = (
            await session.execute(
                text("SELECT status FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar()

    problem = excinfo.value
    assert problem.code == "campaign_launch_blocked"
    assert [f["rule"] for f in problem.fields or []] == [b.rule for b in preview]
    assert status == "draft", "a blocked launch leaves the campaign where it was"


async def test_launch_scrubs_the_dnc_list_before_reporting_a_dialable_count() -> None:
    tenant_id, _, campaign_id = await _ready_campaign(
        phones=("9876500001", "9876500002", "9876500003")
    )
    async with tenant_session(tenant_id) as session:
        await add_to_dnc(session, tenant_id=tenant_id, phone_e164="+919876500002", source="request")
        result = await service.launch_campaign(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
        blocked = (
            await session.execute(
                text(
                    "SELECT status FROM campaign_contacts WHERE campaign_id = :c "
                    "AND phone_e164 = '+919876500002'"
                ),
                {"c": campaign_id},
            )
        ).scalar()

    assert result == {"status": "running", "dialable": 2, "dnc_scrubbed": 1}
    assert blocked == "dnc_blocked", "opted-out is terminal, not retryable"


async def test_a_second_launch_of_a_running_campaign_is_an_invalid_transition() -> None:
    tenant_id, _, campaign_id = await _ready_campaign()
    async with tenant_session(tenant_id) as session:
        await service.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
        with pytest.raises(ProblemError) as excinfo:
            await service.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
    # The gate catches it first (status blocker) — either way it never re-dials.
    assert excinfo.value.code in ("campaign_launch_blocked", "invalid_status_transition")


async def test_pause_and_resume_are_compare_and_swap() -> None:
    tenant_id, _, campaign_id = await _ready_campaign()
    async with tenant_session(tenant_id) as session:
        await service.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
        assert await service.set_campaign_status(
            session, campaign_id=campaign_id, to_status="paused", from_statuses=("running",)
        )
        # Already paused: the caller's intent holds, so this is a success that made no
        # change — NOT a 409. It used to raise, which meant the second click of Pause
        # (and the retry of a request whose response was lost) told an operator watching
        # calls go out that pausing had failed.
        assert (
            await service.set_campaign_status(
                session, campaign_id=campaign_id, to_status="paused", from_statuses=("running",)
            )
            is False
        )
        assert await service.set_campaign_status(
            session, campaign_id=campaign_id, to_status="running", from_statuses=("paused",)
        )
        progress = await service.campaign_progress(session, campaign_id)
    assert progress["status"] == "running"
    assert progress["total"] == 3


async def test_pausing_a_campaign_in_another_state_names_that_state() -> None:
    """The 409 branch. A draft is not a paused campaign and not an absent one, and the
    message has to say which — "cannot move from draft to paused" is a sentence an
    operator can act on; "conflict" is not."""
    tenant_id, _, campaign_id = await _ready_campaign()
    async with tenant_session(tenant_id) as session:
        with pytest.raises(InvalidStatusTransitionError) as raised:
            await service.set_campaign_status(
                session, campaign_id=campaign_id, to_status="paused", from_statuses=("running",)
            )
    assert raised.value.status == 409
    assert raised.value.code == "invalid_status_transition"
    assert "draft" in raised.value.detail


async def test_pausing_a_campaign_that_does_not_exist_is_a_404() -> None:
    """The third branch, and the one the old code got most wrong: an unknown id was
    reported as a conflict, which asserts a row exists. Under RLS this is also the
    cross-tenant answer — a neighbour's campaign id must be indistinguishable from an
    invented one."""
    tenant_a, _, campaign_id = await _ready_campaign()
    tenant_b, _, _ = await _ready_campaign()
    async with tenant_session(tenant_a) as session:
        await service.launch_campaign(session, tenant_id=tenant_a, campaign_id=campaign_id)

    for name, target in (("invented", uuid.uuid4()), ("neighbour's", campaign_id)):
        async with tenant_session(tenant_b) as session:
            with pytest.raises(ProblemError) as raised:
                await service.set_campaign_status(
                    session, campaign_id=target, to_status="paused", from_statuses=("running",)
                )
        assert raised.value.status == 404, f"{name} id was not a 404"
        assert raised.value.code == "not_found"

    # And tenant B's attempt moved nothing: A's campaign is still running.
    async with tenant_session(tenant_a) as session:
        assert (await service.campaign_progress(session, campaign_id))["status"] == "running"


async def test_two_concurrent_pauses_produce_exactly_one_transition() -> None:
    """The race the CAS exists for, run for real on two connections.

    Both callers reach the database; the state predicate in the WHERE clause is what
    makes exactly one of them the writer. A read-then-write would let both read
    `running`, both write `paused`, and both report themselves as the pause — which is
    a lie in the audit trail the moment pause starts writing one.
    """
    tenant_id, _, campaign_id = await _ready_campaign()
    async with tenant_session(tenant_id) as session:
        await service.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)

    # The barrier is what makes this test deterministic rather than lucky: both sessions
    # are open and both callers are inside the service before either statement runs, so
    # a read-then-write really does interleave its read with the other's. Without it the
    # first caller can finish before the second starts, and a broken CAS passes.
    both_ready = asyncio.Barrier(2)

    async def pause() -> bool:
        async with tenant_session(tenant_id) as session:
            await both_ready.wait()
            return await service.set_campaign_status(
                session, campaign_id=campaign_id, to_status="paused", from_statuses=("running",)
            )

    outcomes = await asyncio.gather(pause(), pause())

    assert sorted(outcomes) == [False, True], f"two writers both won: {outcomes}"
    async with tenant_session(tenant_id) as session:
        assert (await service.campaign_progress(session, campaign_id))["status"] == "paused"


# ------------------------------------------------------------------------ dispatcher


async def test_a_paused_campaign_dials_nobody() -> None:
    tenant_id, _, campaign_id = await _ready_campaign()
    async with tenant_session(tenant_id) as session:
        await service.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
        await service.set_campaign_status(
            session, campaign_id=campaign_id, to_status="paused", from_statuses=("running",)
        )
    await _quiesce(campaign_id)
    await dispatch_campaign_tick({})
    async with tenant_session(tenant_id) as session:
        calls = (await session.execute(text("SELECT count(*) FROM calls"))).scalar()
    assert calls == 0


async def test_the_tick_dials_up_to_the_campaign_slider_and_no_further() -> None:
    """Regression: the claim used to OVER-claim.

    A whole CSV is inserted in one transaction, so every contact shares a `created_at`
    to the microsecond. With the claim written as `WHERE id IN (SELECT ... LIMIT n FOR
    UPDATE SKIP LOCKED)`, Postgres was free to rescan that subquery per candidate row,
    break the tie differently each time, and update far more than n rows — a campaign
    dialling past its slider and into the lines reserved for inbound. Five contacts
    against a slider of two is the smallest case that catches it.
    """
    tenant_id, _, campaign_id = await _ready_campaign(
        phones=("9876500001", "9876500002", "9876500003", "9876500004", "9876500005"),
        concurrency=2,
    )
    async with tenant_session(tenant_id) as session:
        await service.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)

    await _quiesce(campaign_id)
    await dispatch_campaign_tick({})

    async with tenant_session(tenant_id) as session:
        dialing = (
            await session.execute(
                text(
                    "SELECT count(*) FROM campaign_contacts WHERE campaign_id = :c "
                    "AND status = 'dialing'"
                ),
                {"c": campaign_id},
            )
        ).scalar()
        calls = (
            await session.execute(text("SELECT count(*) FROM calls WHERE direction = 'outbound'"))
        ).scalar()
    assert dialing == 2, "the slider is a ceiling, not a suggestion"
    assert calls == 2


async def test_the_big_red_switch_halts_every_tenants_campaign() -> None:
    tenant_id, _, campaign_id = await _ready_campaign()
    async with tenant_session(tenant_id) as session:
        await service.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)

    await set_platform_status(outbound_halted=True, actor_id=None)
    try:
        await _quiesce(campaign_id)
        result = await dispatch_campaign_tick({})
    finally:
        await set_platform_status(outbound_halted=False, actor_id=None)

    assert result == "halted_by_big_red_switch"
    async with tenant_session(tenant_id) as session:
        assert (await session.execute(text("SELECT count(*) FROM calls"))).scalar() == 0


async def test_a_halt_thrown_mid_batch_stops_the_contacts_behind_the_one_in_flight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The switch has to reach a batch the tick has ALREADY CLAIMED, from another process.

    The halt is written by `ops.routes.set_platform` in the API process. That clears the
    API process's `loadshed._memo` and writes the new value through Redis — and leaves the
    WORKER's memo alone, where it answers "running" for up to `_MEMO_TTL_S` (5s) more. The
    tick primes exactly that memo at `_run_tick`, so before this test the claimed batch
    went on dialling: every contact's `check_dispatch` read the stale memo and allowed the
    dial. Those dials are the ones nothing recalls — `dial_recall` is enqueued on the
    halt's `false -> true` edge and scans ONCE, before they existed.

    So the staleness is reconstructed rather than described: `set_platform_status` runs
    (durable row + Redis, as the API process does), and this process's memo is then put
    back to the pre-halt answer with a fresh timestamp — which is the worker's state, to
    the second. A test that simply called `set_platform_status` would prove nothing, since
    that call refreshes the memo of whatever process makes it.
    """
    tenant_id, _, campaign_id = await _ready_campaign(
        phones=("9876500001", "9876500002", "9876500003"), concurrency=3
    )
    async with tenant_session(tenant_id) as session:
        await service.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
    await _quiesce(campaign_id)

    real_dial = campaign_dispatch.dispatch_call
    dialled: list[str] = []

    async def halt_after_the_first_dial(*args: Any, **kwargs: Any) -> Any:
        handle = await real_dial(*args, **kwargs)
        dialled.append(str(kwargs["phone_e164"]))
        if len(dialled) == 1:
            await set_platform_status(outbound_halted=True, halt_reason="mid-batch", actor_id=None)
            # ...and this worker has not noticed yet. Its memo is 5 seconds young and
            # says the platform is running, which is the whole state under test.
            loadshed._memo = (
                time.monotonic(),
                loadshed.PlatformStatus(mode="normal", outbound_halted=False),
            )
        return handle

    monkeypatch.setattr(campaign_dispatch, "dispatch_call", halt_after_the_first_dial)
    try:
        await dispatch_campaign_tick({})
    finally:
        await set_platform_status(outbound_halted=False, actor_id=None)

    assert dialled == ["+919876500001"], f"the halt did not stop the batch: {dialled}"
    async with tenant_session(tenant_id) as session:
        statuses = dict(
            (
                await session.execute(
                    text("SELECT phone_e164, status FROM campaign_contacts WHERE campaign_id = :c"),
                    {"c": campaign_id},
                )
            ).all()
        )
        placed = (
            (await session.execute(text("SELECT to_e164 FROM calls WHERE direction = 'outbound'")))
            .scalars()
            .all()
        )
    assert sorted(placed) == ["+919876500001"], "a dial was placed after the switch"
    # Back on the ladder with the attempt refunded, not settled: a halt is a condition
    # that clears, and `big_red_switch` is deliberately not a `PERSON_LEVEL_REFUSALS`.
    assert statuses["+919876500002"] == "pending"
    assert statuses["+919876500003"] == "pending"


async def test_a_number_that_joins_the_dnc_list_after_launch_is_never_dialled() -> None:
    """The property the module was written for: launch scrubs, dispatch enforces. Hard
    rule 5 — DNC additions propagate before the next dispatch tick, and this IS the
    tick."""
    tenant_id, _, campaign_id = await _ready_campaign(phones=("9876500001", "9876500002"))
    async with tenant_session(tenant_id) as session:
        launched = await service.launch_campaign(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
        assert launched["dnc_scrubbed"] == 0, "clean at launch"
        # Between launch and dial, this person opts out on another call.
        await add_to_dnc(
            session, tenant_id=tenant_id, phone_e164="+919876500002", source="in_call_optout"
        )

    await _quiesce(campaign_id)
    await dispatch_campaign_tick({})

    async with tenant_session(tenant_id) as session:
        statuses = dict(
            (
                await session.execute(
                    text("SELECT phone_e164, status FROM campaign_contacts WHERE campaign_id = :c"),
                    {"c": campaign_id},
                )
            ).all()
        )
        dialled = (
            (await session.execute(text("SELECT to_e164 FROM calls WHERE direction = 'outbound'")))
            .scalars()
            .all()
        )

    assert statuses["+919876500002"] == "dnc_blocked"
    assert "+919876500002" not in dialled, "the opt-out beat the dial"
    assert statuses["+919876500001"] == "dialing"


async def test_a_contact_outside_india_is_settled_rather_than_retried_for_ever() -> None:
    """A refusal that can never become true must not keep a campaign alive.

    `add_contacts` drops well-formed foreign numbers at upload (D-464) — the INGRESS is
    closed — but every row uploaded before that guard is still `pending`, and the gate
    refuses it `destination_not_india` on every tick. Treated as transient, that contact
    was re-claimed, refunded and rescheduled every thirty minutes for ever, the campaign
    never reached "nothing pending" and `campaign.completed` never fired. So the row is
    inserted the way a pre-D-464 upload left it, which is the only way it can now exist.
    """
    tenant_id, _, campaign_id = await _ready_campaign(phones=("9876500001",))
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO campaign_contacts (id, tenant_id, campaign_id, phone_e164, "
                "status, attempts, created_at, updated_at) VALUES "
                "(:id, :tid, :cid, '+14155552671', 'pending', 0, now(), now())"
            ),
            {"id": uuid7(), "tid": tenant_id, "cid": campaign_id},
        )
        # The scrub covers the list that existed when it ran, and the row above joined
        # it afterwards — so it is re-run, exactly as a client adding a contact would
        # have to. (`_ready_campaign` records the first one after ITS upload.)
        await record_test_scrub(session, campaign_id)
        await service.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
    await _quiesce(campaign_id)
    await dispatch_campaign_tick({})

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT status, attempts, next_attempt_at FROM campaign_contacts "
                    "WHERE campaign_id = :c AND phone_e164 = '+14155552671'"
                ),
                {"c": campaign_id},
            )
        ).one()
    assert row[0] == "dnc_blocked", "a number we can never dial went back on the ladder"
    assert row[2] is None, "a settled contact must not be scheduled for another attempt"


async def test_outside_calling_hours_the_contact_waits_instead_of_burning_an_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 3am tick must not consume the retry budget: 9-21 IST is a *when*, not a *no*."""
    tenant_id, _, campaign_id = await _ready_campaign(phones=("9876500001",))
    async with tenant_session(tenant_id) as session:
        await service.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)

    night = datetime(2026, 8, 11, 3, 0, tzinfo=UTC) + timedelta(hours=5, minutes=30)
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: night)
    await _quiesce(campaign_id)
    await dispatch_campaign_tick({})

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT status, attempts, next_attempt_at FROM campaign_contacts "
                    "WHERE campaign_id = :c"
                ),
                {"c": campaign_id},
            )
        ).first()
        calls = (await session.execute(text("SELECT count(*) FROM calls"))).scalar()

    assert row is not None
    assert row[0] == "pending", "back in the queue, not failed"
    assert row[1] == 0, "the attempt was refunded — the hour blocked it, not the customer"
    assert row[2] is not None, "and it is scheduled for later"
    assert calls == 0


async def test_a_tenant_ceiling_of_zero_free_lines_dials_nothing() -> None:
    """Rule 3 of FLOWS §5: the plan's concurrency ceiling bounds the campaign slider."""
    tenant_id, _, campaign_id = await _ready_campaign(concurrency=5)
    async with tenant_session(tenant_id) as session:
        await service.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)

    # Quiesce BEFORE staging the busy line — the sweep settles in-flight calls, which
    # is exactly the state this test needs to survive into the tick.
    await _quiesce(campaign_id)

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO plans (id, tenant_id, concurrency_ceiling, created_at, updated_at) "
                "VALUES (:id, :tid, 1, now(), now())"
            ),
            {"id": uuid7(), "tid": tenant_id},
        )
        # One outbound call already in flight consumes the whole ceiling.
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
                "status, created_at, updated_at) SELECT :id, :tid, agent_id, :ecid, 'outbound', "
                "'+919999900000', 'in_progress', now(), now() FROM campaigns WHERE id = :c"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "ecid": f"busy_{uuid.uuid4().hex[:8]}",
                "c": campaign_id,
            },
        )

    await dispatch_campaign_tick({})

    async with tenant_session(tenant_id) as session:
        dialing = (
            await session.execute(
                text("SELECT count(*) FROM campaign_contacts WHERE status = 'dialing'")
            )
        ).scalar()
    assert dialing == 0, "a full ceiling starves the campaign, not the receptionist"


# ----------------------------------------------------------------------- retry ladder


async def test_an_unanswered_dial_comes_back_later_and_then_gives_up() -> None:
    """FLOWS §5's ladder: retry with spaced backoff, then stop. Three attempts against
    a number that never answers, and no fourth."""
    tenant_id, _, campaign_id = await _ready_campaign(phones=("9876500001",))
    async with tenant_session(tenant_id) as session:
        await service.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)

    for attempt in (1, 2, 3):
        await _quiesce(campaign_id)
        await dispatch_campaign_tick({})
        async with tenant_session(tenant_id) as session:
            contact = (
                await session.execute(
                    text(
                        "SELECT id, status, attempts, last_call_id FROM campaign_contacts "
                        "WHERE campaign_id = :c"
                    ),
                    {"c": campaign_id},
                )
            ).first()
            assert contact is not None
            assert contact[1] == "dialing" and contact[2] == attempt, contact
            # The call ends unanswered; the pipeline hands the outcome back.
            status = await resolve_campaign_contact(
                session,
                tenant_id=tenant_id,
                call_id=contact[3],
                call_status="no_answer",
            )
            row = (
                await session.execute(
                    text(
                        "SELECT status, attempts, next_attempt_at FROM campaign_contacts "
                        "WHERE id = :id"
                    ),
                    {"id": contact[0]},
                )
            ).first()
            assert row is not None
            if attempt < 3:
                assert status == "pending" and row[0] == "pending"
                assert row[2] is not None, "spaced, not immediate"
                # Fast-forward past the backoff so the next tick can claim it.
                await session.execute(
                    text(
                        "UPDATE campaign_contacts SET next_attempt_at = now() - "
                        "interval '1 minute', last_attempt_at = now() - interval '1 hour' "
                        "WHERE id = :id"
                    ),
                    {"id": contact[0]},
                )
            else:
                assert row[0] == "failed", "the ladder ends; we do not hound the number"

    await dispatch_campaign_tick({})
    async with tenant_session(tenant_id) as session:
        final = (
            await session.execute(
                text("SELECT status, attempts FROM campaign_contacts WHERE campaign_id = :c"),
                {"c": campaign_id},
            )
        ).first()
        campaign_status = (
            await session.execute(
                text("SELECT status FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar()
    assert final == ("failed", 3), "no fourth attempt"
    assert campaign_status == "completed", "nothing left to dial closes the campaign"


async def test_a_connected_call_closes_the_contact_and_completes_the_campaign() -> None:
    tenant_id, _, campaign_id = await _ready_campaign(phones=("9876500001", "9876500002"))
    async with tenant_session(tenant_id) as session:
        await service.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)

    await _quiesce(campaign_id)
    await dispatch_campaign_tick({})

    async with tenant_session(tenant_id) as session:
        call_ids = (
            (
                await session.execute(
                    text(
                        "SELECT last_call_id FROM campaign_contacts WHERE campaign_id = :c "
                        "AND last_call_id IS NOT NULL"
                    ),
                    {"c": campaign_id},
                )
            )
            .scalars()
            .all()
        )
        for call_id in call_ids:
            assert (
                await resolve_campaign_contact(
                    session, tenant_id=tenant_id, call_id=call_id, call_status="completed"
                )
                == "connected"
            )

    await dispatch_campaign_tick({})
    async with tenant_session(tenant_id) as session:
        progress = await service.campaign_progress(session, campaign_id)
    assert progress["contacts"] == {"connected": 2}
    assert progress["status"] == "completed"


async def test_a_non_campaign_call_resolves_to_nothing() -> None:
    """Every post-call run calls the resolver; the ordinary inbound call must sail
    past it without touching a campaign row."""
    tenant_id, _ = await _tenant()
    async with tenant_session(tenant_id) as session:
        assert (
            await resolve_campaign_contact(
                session, tenant_id=tenant_id, call_id=uuid7(), call_status="completed"
            )
            is None
        )


async def test_a_number_already_owned_by_another_tenant_is_a_conflict_not_a_500() -> None:
    """RLS hides the other tenant's row, so a "is this taken?" probe would answer
    "available" for exactly the number that is not. The unique index is the authority
    and its violation has to surface as a clean 409."""
    tenant_a, _ = await _tenant()
    tenant_b, _ = await _tenant()
    # A REAL 140-series number, because `provision_number` now checks the prefix against
    # the series (DoT/PIB PRID 2022249): `+9180…` filed as `"140"` is refused by name.
    number = f"+91140{uuid.uuid4().int % 10000000:07d}"

    async with tenant_session(tenant_a) as session:
        await agents_service.provision_number(
            session,
            tenant_id=tenant_a,
            e164=number,
            series="140",
            agent_id=None,
            provider="exotel",
            purpose="campaigns",
        )
    async with tenant_session(tenant_b) as session:
        # From B's side the number is invisible — and still unavailable.
        assert (
            await session.execute(
                text("SELECT count(*) FROM phone_numbers WHERE e164 = :e"), {"e": number}
            )
        ).scalar() == 0
        with pytest.raises(ProblemError) as excinfo:
            await agents_service.provision_number(
                session,
                tenant_id=tenant_b,
                e164=number,
                series="140",
                agent_id=None,
                provider="exotel",
                purpose="campaigns",
            )
    assert excinfo.value.code == "number_taken"
    assert excinfo.value.kind == "conflict"


async def test_a_registered_template_starts_submitted_and_only_admin_approval_moves_it() -> None:
    """A template we mark approved because we typed it in is how a campaign launches
    under a registration that does not exist."""
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        number_id = await _number(session, tenant_id, "140", agent_id=agent_id)
        template_id = await service.register_dlt_template(
            session,
            tenant_id=tenant_id,
            classification="promotional",
            body="Hello from {#var#}, calling about your enquiry with us.",
            dlt_ref=None,
        )
        campaign_id = await _create_campaign(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Diwali offers",
            classification="promotional",
            number_id=number_id,
            dlt_template_id=template_id,
            concurrency=3,
        )
        await service.add_contacts(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            contacts=[{"phone": "9876500001"}],
        )
        # Everything §3 asks for EXCEPT the approval under test, so `before` isolates it
        # and `after == []` still means "the registrar's word was the last thing owed".
        await record_test_scrub(session, campaign_id)
        before = await service.launch_blockers(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
        await service.set_template_status(
            session, template_id=template_id, status="approved", dlt_ref="1207161234567890123"
        )
        after = await service.launch_blockers(session, tenant_id=tenant_id, campaign_id=campaign_id)
        ref = (
            await session.execute(
                text("SELECT dlt_ref FROM dlt_templates WHERE id = :id"), {"id": template_id}
            )
        ).scalar()

    assert [b.rule for b in before] == ["dlt_template_not_approved"]
    assert after == [], "the registrar's approval is what unlocks the gate"
    assert ref == "1207161234567890123", "and the registrar's id is kept with it"


async def test_the_setup_lists_the_ui_needs_are_tenant_scoped_and_ordered() -> None:
    """The create form can only offer what these three endpoints return, so a leak here
    is a client seeing another business's numbers in a dropdown."""
    tenant_id, _, campaign_id = await _ready_campaign(classification="service", series="160")
    other_tenant, _, _ = await _ready_campaign(classification="promotional", series="140")

    async with tenant_session(tenant_id) as session:
        campaigns = await service.list_campaigns(session)
        numbers = (await session.execute(text("SELECT series FROM phone_numbers"))).scalars().all()
        templates = (
            (await session.execute(text("SELECT classification FROM dlt_templates")))
            .scalars()
            .all()
        )

    assert [c["id"] for c in campaigns] == [campaign_id], "one tenant, one campaign"
    assert campaigns[0]["contacts"] == 3 and campaigns[0]["connected"] == 0
    assert campaigns[0]["status"] == "draft"
    assert numbers == ["160"], "the other tenant's 140 number is not visible here"
    assert templates == ["service"]

    async with tenant_session(other_tenant) as session:
        assert [c["name"] for c in await service.list_campaigns(session)] == ["Diwali offers"]


async def test_a_dial_stuck_in_flight_is_reclaimed_not_orphaned() -> None:
    """If a call never reports a terminal status, the contact would pin the campaign
    open forever. After 30 minutes it returns to the ladder."""
    tenant_id, _, campaign_id = await _ready_campaign(phones=("9876500001",))
    async with tenant_session(tenant_id) as session:
        await service.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
    await _quiesce(campaign_id)
    await dispatch_campaign_tick({})

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE campaign_contacts SET last_attempt_at = now() - interval '2 hours' "
                "WHERE campaign_id = :c AND status = 'dialing'"
            ),
            {"c": campaign_id},
        )

    await dispatch_campaign_tick({})

    async with tenant_session(tenant_id) as session:
        status = (
            await session.execute(
                text("SELECT status FROM campaign_contacts WHERE campaign_id = :c"),
                {"c": campaign_id},
            )
        ).scalar()
        campaign_status = (
            await session.execute(
                text("SELECT status FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar()
    assert status == "pending", "reclaimed onto the retry ladder"
    assert campaign_status == "running", "and the campaign is not falsely completed"


async def test_engine_dispatch_is_isolated_from_other_tenants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two tenants, two campaigns, one tick: each tenant's contacts get their own
    tenant's calls and nothing crosses."""
    a_tenant, _, a_campaign = await _ready_campaign(phones=("9876500011", "9876500012"))
    b_tenant, _, b_campaign = await _ready_campaign(phones=("9876500021",))
    for tenant_id, campaign_id in ((a_tenant, a_campaign), (b_tenant, b_campaign)):
        async with tenant_session(tenant_id) as session:
            await service.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)

    await _quiesce(a_campaign, b_campaign)
    await dispatch_campaign_tick({})

    async with tenant_session(a_tenant) as session:
        a_numbers = set((await session.execute(text("SELECT to_e164 FROM calls"))).scalars().all())
    async with tenant_session(b_tenant) as session:
        b_numbers = set((await session.execute(text("SELECT to_e164 FROM calls"))).scalars().all())
    assert a_numbers == {"+919876500011", "+919876500012"}
    assert b_numbers == {"+919876500021"}


# ------------------------------------------------------------- per-campaign windows


async def _windowed_campaign(
    calling_hours: dict[str, str] | None,
    phones: tuple[str, ...] = ("9876500001", "9876500002"),
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """`_ready_campaign` with a per-campaign window, appended rather than threading
    a knob through the shared fixture (the existing tests stay untouched). The
    window goes through `create_campaign` so these tests exercise the validated
    write path, not a raw UPDATE."""
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        number_id = await _number(session, tenant_id, "140", agent_id=agent_id)
        template_id = await _template(session, tenant_id, "promotional", "approved")
        campaign_id = await _create_campaign(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Lunch-hour offers",
            classification="promotional",
            number_id=number_id,
            dlt_template_id=template_id,
            concurrency=3,
            calling_hours=calling_hours,
        )
        await service.add_contacts(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            contacts=[{"phone": p, "name": f"Lead {p[-4:]}"} for p in phones],
        )
        # Promotional, so the national DND scrub applies here exactly as it does in
        # `_ready_campaign` — see the note there.
        await record_test_scrub(session, campaign_id)
    return tenant_id, agent_id, campaign_id


async def test_a_window_outside_platform_hours_is_rejected_and_inside_is_stored() -> None:
    """Narrowing-only: a client may shrink when their campaign dials, never widen
    past 09:00-21:00 IST. That window is TRAI law (hard rule 5), so 06:00-10:00 is
    refused at CREATE — an unlawful window must never even reach the column."""
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as excinfo:
            await _create_campaign(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                name="Early birds",
                classification="promotional",
                number_id=None,
                dlt_template_id=None,
                concurrency=3,
                calling_hours={"start": "06:00", "end": "10:00"},
            )
        assert excinfo.value.code == "campaign_window_outside_platform_hours"
        assert excinfo.value.kind == "validation"

        # Entirely inside the platform window: accepted and stored verbatim.
        campaign_id = await _create_campaign(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Lunch only",
            classification="promotional",
            number_id=None,
            dlt_template_id=None,
            concurrency=3,
            calling_hours={"start": "12:00", "end": "14:00"},
        )
        stored = (
            await session.execute(
                text("SELECT calling_hours FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar()
    assert stored == {"start": "12:00", "end": "14:00"}


async def test_a_closed_campaign_window_skips_the_campaign_without_burning_attempts() -> None:
    """The autouse fixture pins the clock to 11:00 IST, so a 12:00-14:00 window is
    closed RIGHT NOW. The dispatcher must skip the campaign BEFORE claiming — no
    attempts consumed, nothing to refund — while an unwindowed campaign dials
    normally in the very same tick. The contrast is the test: the skip is the
    window's doing, not a dead dispatcher."""
    w_tenant, _, windowed = await _windowed_campaign({"start": "12:00", "end": "14:00"})
    o_tenant, _, unwindowed = await _ready_campaign(phones=("9876500021",))
    for tenant_id, campaign_id in ((w_tenant, windowed), (o_tenant, unwindowed)):
        async with tenant_session(tenant_id) as session:
            await service.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)

    await _quiesce(windowed, unwindowed)
    await dispatch_campaign_tick({})

    async with tenant_session(w_tenant) as session:
        rows = (
            await session.execute(
                text("SELECT status, attempts FROM campaign_contacts WHERE campaign_id = :c"),
                {"c": windowed},
            )
        ).all()
        w_calls = (await session.execute(text("SELECT count(*) FROM calls"))).scalar()
    async with tenant_session(o_tenant) as session:
        o_dialing = (
            await session.execute(
                text(
                    "SELECT count(*) FROM campaign_contacts WHERE campaign_id = :c "
                    "AND status = 'dialing'"
                ),
                {"c": unwindowed},
            )
        ).scalar()

    assert all(row == ("pending", 0) for row in rows), rows
    assert w_calls == 0, "skipped before claiming: no dial, no attempt, no refund needed"
    assert o_dialing == 1, "the same tick dialled the campaign with no window"


async def test_the_windowed_campaign_dials_once_its_window_opens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _, campaign_id = await _windowed_campaign(
        {"start": "12:00", "end": "14:00"}, phones=("9876500001",)
    )
    async with tenant_session(tenant_id) as session:
        await service.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)

    # 13:00 IST: inside the campaign's own window AND the platform window, so both
    # the tick-level skip and the per-dial gate let it through.
    lunch = datetime(2026, 8, 11, 7, 30, tzinfo=UTC) + timedelta(hours=5, minutes=30)
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: lunch)
    await _quiesce(campaign_id)
    await dispatch_campaign_tick({})

    async with tenant_session(tenant_id) as session:
        status = (
            await session.execute(
                text("SELECT status FROM campaign_contacts WHERE campaign_id = :c"),
                {"c": campaign_id},
            )
        ).scalar()
        calls = (
            await session.execute(text("SELECT count(*) FROM calls WHERE direction = 'outbound'"))
        ).scalar()
    assert status == "dialing", "the open window lets the same campaign dial"
    assert calls == 1


async def test_a_backwards_or_malformed_window_is_rejected() -> None:
    tenant_id, agent_id = await _tenant()
    bad_windows: tuple[dict[str, str], ...] = (
        {"start": "14:00", "end": "12:00"},  # backwards
        {"start": "12:00", "end": "12:00"},  # empty: start must be strictly before end
        {"start": "noon", "end": "14:00"},  # not a time
        {"start": "12:00:00", "end": "14:00"},  # seconds are not HH:MM
        {"start": "12:00"},  # missing end
    )
    async with tenant_session(tenant_id) as session:
        for window in bad_windows:
            with pytest.raises(ProblemError) as excinfo:
                await _create_campaign(
                    session,
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    name="Bad window",
                    classification="promotional",
                    number_id=None,
                    dlt_template_id=None,
                    concurrency=3,
                    calling_hours=window,
                )
            assert excinfo.value.code == "campaign_window_invalid", window
            assert excinfo.value.kind == "validation"


# --- per-contact variables are bounded in all three dimensions (D-302) -----------------


def test_a_campaign_contacts_custom_variables_are_bounded() -> None:
    """`custom` is stored as jsonb AND spoken by the agent as engine `user_data`.

    Both halves were bounded only by the 2 MiB body cap, so one POST of 5,000 contacts
    could durably store — and later speak from — megabytes of caller-authored text.
    Storage a caller decides the size of is the write-side twin of an unbounded list; text
    that reaches a PROMPT is the worse half, because an unbounded value is the most useful
    shape an injection can take.

    Asserted at the MODEL, which is where the ceiling is declared, so the same refusal
    reaches the OpenAPI schema and the generated client rather than only the server.
    """
    from apps.api.campaigns.routes import (
        MAX_CONTACT_CUSTOM_FIELDS,
        MAX_CONTACT_CUSTOM_KEY_LEN,
        MAX_CONTACT_CUSTOM_VALUE_LEN,
        ContactIn,
    )

    # The control: a realistic contact still validates, so the bounds refuse abuse rather
    # than the product.
    ok = ContactIn(
        phone="+919876500000",
        name="Radhika",
        custom={"appointment_time": "10:30", "doctor_name": "Dr Rao"},
    )
    assert ok.custom["doctor_name"] == "Dr Rao"

    with pytest.raises(ValidationError):
        ContactIn(
            phone="+919876500000",
            custom={f"k{i}": "v" for i in range(MAX_CONTACT_CUSTOM_FIELDS + 1)},
        )
    with pytest.raises(ValidationError):
        ContactIn(phone="+919876500000", custom={"k": "v" * (MAX_CONTACT_CUSTOM_VALUE_LEN + 1)})
    with pytest.raises(ValidationError):
        ContactIn(phone="+919876500000", custom={"k" * (MAX_CONTACT_CUSTOM_KEY_LEN + 1): "v"})
