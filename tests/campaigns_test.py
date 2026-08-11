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

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import service as agents_service
from apps.api.campaigns import service
from apps.api.compliance.service import add_to_dnc
from apps.api.core.errors import InvalidStatusTransitionError, ProblemError
from apps.api.core.loadshed import set_platform_status
from apps.api.db.base import uuid7
from apps.api.db.session import admin_session, tenant_session, untenanted_session
from apps.api.engine import reset_engine_cache
from apps.workers.campaign_dispatch import (
    ACTIVE_STATUSES,
    dispatch_campaign_tick,
    resolve_campaign_contact,
)
from sqlalchemy import text


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the gate's clock to 11:00 IST — see lead_ingest_test for the story. The
    calling-hours rule is exercised deliberately in its own test below."""
    fixed = datetime(2026, 8, 11, 5, 30, tzinfo=UTC) + timedelta(hours=5, minutes=30)
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: fixed)


# Tenants this module created, and whether the one-time database-wide sweep has run.
# Both exist so `_quiesce` stays O(this suite) instead of O(every org ever seeded).
_TENANTS: list[uuid.UUID] = []
_swept = False


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
    _TENANTS.append(tenant_id)
    return tenant_id, agent_id


async def _number(session: Any, tenant_id: uuid.UUID, series: str) -> uuid.UUID:
    number_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO phone_numbers (id, tenant_id, e164, series, dlt_status, created_at, "
            "updated_at) VALUES (:id, :tid, :e, :s, 'registered', now(), now())"
        ),
        {
            "id": number_id,
            "tid": tenant_id,
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
        number_id = await _number(session, tenant_id, series)
        template_id = await _template(
            session, tenant_id, template_classification or classification, template_status
        )
        campaign_id = await service.create_campaign(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Diwali offers",
            classification=classification,
            number_id=number_id,
            dlt_template_id=template_id,
            concurrency=concurrency,
        )
        if phones:
            await service.add_contacts(
                session,
                tenant_id=tenant_id,
                campaign_id=campaign_id,
                contacts=[{"phone": p, "name": f"Lead {p[-4:]}"} for p in phones],
            )
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

    The outbound pool and the active-call count are deliberately GLOBAL (FLOWS §5 rule
    1) — one tenant's campaign must not eat the lines another tenant's receptionist
    needs. That is the behaviour under test, and it also means every dispatcher test is
    sensitive to campaigns and calls its predecessors left running. So each one first
    cancels the others' campaigns and settles their calls, keeping only its own.

    The first call also sweeps the whole database once, because this suite runs against
    a persistent dev/CI Postgres that still holds `running` campaigns from earlier runs.
    """
    global _swept
    if not _swept:
        async with admin_session() as directory:
            everyone = (
                await directory.execute(
                    text("SELECT id FROM organizations WHERE deleted_at IS NULL")
                )
            ).scalars()
            await _sweep([uuid.UUID(str(t)) for t in everyone.all()], keep)
        _swept = True
        return
    await _sweep(_TENANTS, keep)


# --------------------------------------------------------------------------- contacts


async def test_contact_upload_dedupes_and_counts_malformed_without_guessing() -> None:
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        campaign_id = await service.create_campaign(
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

    assert first == {"added": 2, "malformed": 2, "duplicate": 1}
    assert second == {"added": 1, "duplicate": 1, "malformed": 0}
    assert [r[0] for r in rows] == ["+919876511111", "+919876522222", "+919876533333"]
    assert rows[1][1] == {"city": "Hyderabad"}, "extra CSV columns ride along for the prompt"


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
        campaign_id = await service.create_campaign(
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

    assert rules == {"agent_not_live", "dlt_template_missing", "number_missing", "no_contacts"}
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
        await service.set_campaign_status(
            session, campaign_id=campaign_id, to_status="paused", from_statuses=("running",)
        )
        with pytest.raises(InvalidStatusTransitionError):
            # Already paused: a second pause is a lost race, not a no-op to swallow.
            await service.set_campaign_status(
                session, campaign_id=campaign_id, to_status="paused", from_statuses=("running",)
            )
        await service.set_campaign_status(
            session, campaign_id=campaign_id, to_status="running", from_statuses=("paused",)
        )
        progress = await service.campaign_progress(session, campaign_id)
    assert progress["status"] == "running"
    assert progress["total"] == 3


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
    number = f"+9180{uuid.uuid4().int % 100000000:08d}"

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
        number_id = await _number(session, tenant_id, "140")
        template_id = await service.register_dlt_template(
            session,
            tenant_id=tenant_id,
            classification="promotional",
            body="Hello from {#var#}, calling about your enquiry with us.",
            dlt_ref=None,
        )
        campaign_id = await service.create_campaign(
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
        number_id = await _number(session, tenant_id, "140")
        template_id = await _template(session, tenant_id, "promotional", "approved")
        campaign_id = await service.create_campaign(
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
    return tenant_id, agent_id, campaign_id


async def test_a_window_outside_platform_hours_is_rejected_and_inside_is_stored() -> None:
    """Narrowing-only: a client may shrink when their campaign dials, never widen
    past 09:00-21:00 IST. That window is TRAI law (hard rule 5), so 06:00-10:00 is
    refused at CREATE — an unlawful window must never even reach the column."""
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as excinfo:
            await service.create_campaign(
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
        campaign_id = await service.create_campaign(
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
                await service.create_campaign(
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
