"""`campaign_complaint_spike` — FLOWS §5's mid-campaign safety, which did not exist.

WHAT THESE TESTS WOULD HAVE CAUGHT. FLOWS §5 promised "complaint-spike alarm (pause +
notify)", OPERATIONS §4 listed it as a trigger, and D-149's dispatcher comment named the
auto-pause as a thing the per-dial re-read exists to honour — while nothing anywhere
counted an opt-out. A campaign could dial a bad list all afternoon and the only trace was
`consent_ledger` rows nobody read.

THE TWO NEGATIVE TESTS ARE THE POINT. An alarm that fires on a healthy campaign is one
somebody mutes, and this one does not merely page — it STOPS a paying client's campaign.
So both halves of the rule are pinned: four opt-outs out of four is not a spike (below the
count), and five out of two hundred is not a spike (below the rate).

They drive the REAL opt-out writer (`compliance.optout.record_call_optout`), not a
hand-built `consent_ledger` INSERT, because the detector's whole claim is that it reads
what the product actually writes — and the two detectors, the ARQ job and the transcript
pass all converge on that function.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.campaigns import complaint_spike
from apps.api.campaigns import service as campaigns
from apps.api.compliance.optout import DETECTED_IN_CALL, OptOutSignal, record_call_optout
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.workers import campaign_dispatch
from sqlalchemy import text
from tests.national_dnd_test import record_test_scrub


class _Alerts:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, dict[str, str]]] = []

    def __call__(self, stage: str, code: str, *, detail: str = "", **ids: str) -> None:
        self.calls.append((stage, code, detail, dict(ids)))

    def codes(self) -> list[str]:
        return [code for _, code, _, _ in self.calls]


@pytest.fixture
def alerts(monkeypatch: pytest.MonkeyPatch) -> _Alerts:
    captured = _Alerts()
    monkeypatch.setattr(complaint_spike, "alert", captured)
    return captured


async def _running_campaign(*, contacts: int = 0) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """(tenant, agent, campaign) with the campaign `running`.

    `contacts` are added while the campaign is still a DRAFT, because `add_contacts`
    refuses a launched one — the list is fixed at launch by design. Only the test that
    drives the dispatcher needs them; the detector reads `calls`, not `campaign_contacts`.

    Moved to `running` through `set_campaign_status`, the same CAS the pause/resume
    buttons use, rather than through `launch_campaign`: the launch gate needs a number, a
    DLT template and a national-DND scrub, none of which this detector reads. What is NOT
    faked is the status transition itself, because the detector's pause is a CAS against
    exactly that value.
    """
    created = await admin_service.create_organization(
        name="Spike Motors",
        slug=f"spike-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    async with tenant_session(tenant_id) as session:
        campaign_id = await campaigns.create_campaign(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Spike test",
            classification="promotional",
            number_id=None,
            dlt_template_id=None,
            concurrency=3,
            consent_source="existing_customer",
            consent_collected_at=datetime.now(UTC) - timedelta(days=7),
        )
        if contacts:
            await campaigns.add_contacts(
                session,
                tenant_id=tenant_id,
                campaign_id=campaign_id,
                contacts=[{"phone": f"98765{n:05d}", "name": f"Lead {n}"} for n in range(contacts)],
            )
        await campaigns.set_campaign_status(
            session, campaign_id=campaign_id, to_status="running", from_statuses=("draft",)
        )
    return tenant_id, agent_id, campaign_id


async def _launched_campaign(*, contacts: int) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A campaign that passes the DISPATCHER's standing gate, not just the detector's.

    `_running_campaign` above is deliberately minimal — the detector reads `calls` and
    nothing else, so a campaign with no number and no DLT template is all it needs. The
    DISPATCHER is a different question: `dispatch_blockers` runs first and returns
    `{0, 0, 0}` for a campaign missing its paperwork, which is the SAME return value the
    complaint-spike path produces. The first draft of the test below passed against
    `_running_campaign` and proved nothing, because it never reached the line it was
    written for.

    So this one carries the whole launch: a registered 140-series number, an approved
    promotional voice template, the client's PE/TM registration, the national-DND scrub,
    and a published outbound agent — then goes through `launch_campaign`, the real gate.
    """
    created = await admin_service.create_organization(
        name="Spike Dispatch",
        slug=f"spiked-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    number_id, template_id = uuid7(), uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agents SET status = 'live', direction = 'outbound', "
                "engine_agent_ref = :ref WHERE id = :a"
            ),
            {"ref": f"fakeagent_spike_{uuid.uuid4().hex[:8]}", "a": agent_id},
        )
        await campaigns.record_dlt_registration(
            session,
            tenant_id=tenant_id,
            pe_id=f"1102{uuid.uuid4().int % 10**9:09d}",
            entity_name="Spike Dispatch Pvt Ltd",
            status="active",
            tm_link_status="active",
            registered_at=datetime.now(UTC) - timedelta(days=30),
        )
        await session.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, e164, series, dlt_status, "
                "created_at, updated_at) VALUES (:id, :tid, :e, '140', 'registered', now(), now())"
            ),
            {"id": number_id, "tid": tenant_id, "e": f"+9180{uuid.uuid4().int % 10**8:08d}"},
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
            name="Spike dispatch",
            classification="promotional",
            number_id=number_id,
            dlt_template_id=template_id,
            concurrency=3,
            consent_source="existing_customer",
            consent_collected_at=datetime.now(UTC) - timedelta(days=7),
        )
        await campaigns.add_contacts(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            contacts=[{"phone": f"98765{n:05d}", "name": f"Lead {n}"} for n in range(contacts)],
        )
        await record_test_scrub(session, campaign_id)
        await campaigns.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
    return tenant_id, agent_id, campaign_id


async def _connected_calls(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, campaign_id: uuid.UUID, *, count: int
) -> list[tuple[uuid.UUID, str]]:
    """`count` completed outbound calls on this campaign, each with its own number."""
    made: list[tuple[uuid.UUID, str]] = []
    async with tenant_session(tenant_id) as session:
        for _ in range(count):
            call_id = uuid7()
            phone = f"+9198{uuid.uuid4().int % 10**8:08d}"
            await session.execute(
                text(
                    "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                    "status, campaign_id, to_e164, started_at, ended_at, created_at, "
                    "updated_at) VALUES (:id, :tid, :aid, :ref, 'outbound', 'completed', "
                    ":cid, :to, now(), now(), now(), now())"
                ),
                {
                    "id": call_id,
                    "tid": tenant_id,
                    "aid": agent_id,
                    "ref": f"exec_{uuid.uuid4().hex}",
                    "cid": campaign_id,
                    "to": phone,
                },
            )
            made.append((call_id, phone))
    return made


async def _opt_out(tenant_id: uuid.UUID, calls: list[tuple[uuid.UUID, str]]) -> None:
    async with tenant_session(tenant_id) as session:
        for call_id, phone in calls:
            await record_call_optout(
                session,
                tenant_id=tenant_id,
                raw_phone=phone,
                call_id=call_id,
                detected_by=DETECTED_IN_CALL,
                signal=OptOutSignal(
                    rule="engine_tool_call", language="en", turn_idx=None, matched="stop calling"
                ),
            )


async def _status(tenant_id: uuid.UUID, campaign_id: uuid.UUID) -> str:
    async with tenant_session(tenant_id) as session:
        return str(
            (
                await session.execute(
                    text("SELECT status FROM campaigns WHERE id = :c"), {"c": campaign_id}
                )
            ).scalar()
        )


async def _check(tenant_id: uuid.UUID, campaign_id: uuid.UUID) -> Any:
    async with tenant_session(tenant_id) as session:
        return await complaint_spike.check_complaint_spike(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )


async def test_a_spike_pauses_the_campaign_and_pages(alerts: _Alerts) -> None:
    tenant_id, agent_id, campaign_id = await _running_campaign()
    calls = await _connected_calls(tenant_id, agent_id, campaign_id, count=10)
    await _opt_out(tenant_id, calls[: complaint_spike.MIN_OPTOUTS])

    verdict = await _check(tenant_id, campaign_id)

    assert verdict is not None
    assert verdict.optouts == complaint_spike.MIN_OPTOUTS
    assert verdict.connected == 10
    assert verdict.paused is True
    assert await _status(tenant_id, campaign_id) == "paused"
    assert "campaign_complaint_spike" in alerts.codes()


async def test_the_alert_carries_ids_and_counts_and_never_a_number(alerts: _Alerts) -> None:
    """Hard rule 6 on the alerting path: an alert body leaves the building."""
    tenant_id, agent_id, campaign_id = await _running_campaign()
    calls = await _connected_calls(tenant_id, agent_id, campaign_id, count=10)
    await _opt_out(tenant_id, calls[: complaint_spike.MIN_OPTOUTS])
    await _check(tenant_id, campaign_id)

    _, _, detail, ids = next(c for c in alerts.calls if c[1] == "campaign_complaint_spike")
    assert set(ids) == {"tenant_id", "campaign_id"}
    numbers = {phone for _, phone in calls}
    assert not any(phone in detail for phone in numbers)
    assert not any(phone in value for phone in numbers for value in ids.values())


async def test_four_opt_outs_out_of_four_is_not_a_spike(alerts: _Alerts) -> None:
    """Below the COUNT. Four people on a four-contact campaign is 100% and still not the
    order of magnitude TCCCPR's suspension threshold sits at — and pausing there would
    stop campaigns for a reason nobody could defend to a client."""
    tenant_id, agent_id, campaign_id = await _running_campaign()
    calls = await _connected_calls(tenant_id, agent_id, campaign_id, count=4)
    await _opt_out(tenant_id, calls)

    assert await _check(tenant_id, campaign_id) is None
    assert alerts.codes() == []
    assert await _status(tenant_id, campaign_id) == "running"


async def test_five_opt_outs_in_two_hundred_calls_is_not_a_spike(alerts: _Alerts) -> None:
    """Below the RATE. Five opt-outs in two hundred conversations is 2.5% — under the
    4.1% a measured cold-calling study reports, on lists that are supposed to be
    consented. A count-only rule would page on every large healthy campaign."""
    tenant_id, agent_id, campaign_id = await _running_campaign()
    calls = await _connected_calls(tenant_id, agent_id, campaign_id, count=200)
    await _opt_out(tenant_id, calls[:5])

    assert await _check(tenant_id, campaign_id) is None
    assert alerts.codes() == []
    assert await _status(tenant_id, campaign_id) == "running"


async def test_opt_outs_older_than_the_window_do_not_count(alerts: _Alerts) -> None:
    """The window is one calling day, so a campaign that had a bad Tuesday can dial on
    Wednesday. Without it a single bad morning would pause a campaign forever."""
    tenant_id, agent_id, campaign_id = await _running_campaign()
    calls = await _connected_calls(tenant_id, agent_id, campaign_id, count=10)
    await _opt_out(tenant_id, calls[: complaint_spike.MIN_OPTOUTS])
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE calls SET started_at = now() - make_interval(hours => :h), "
                "created_at = now() - make_interval(hours => :h) WHERE campaign_id = :c"
            ),
            {"h": complaint_spike.WINDOW_HOURS + 1, "c": campaign_id},
        )

    assert await _check(tenant_id, campaign_id) is None
    assert alerts.codes() == []
    assert await _status(tenant_id, campaign_id) == "running"


async def test_the_pause_is_audited_as_a_system_act(alerts: _Alerts) -> None:
    """ "Who stopped the calls, and when" must have one answer whether the answer is a
    person or us — the client's own pause button writes `campaign.paused` and so does
    this."""
    tenant_id, agent_id, campaign_id = await _running_campaign()
    calls = await _connected_calls(tenant_id, agent_id, campaign_id, count=10)
    await _opt_out(tenant_id, calls[: complaint_spike.MIN_OPTOUTS])
    await _check(tenant_id, campaign_id)

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT actor_type, object_type FROM audit_log "
                    "WHERE action = 'campaign.paused' AND object_id = :oid "
                    "ORDER BY at DESC LIMIT 1"
                ),
                {"oid": str(campaign_id)},
            )
        ).first()
    assert row is not None
    assert row == ("system", "campaign")
    # The counts ride the LOG stream rather than the row: `audit_log` has no `summary`
    # column, and `write_audit` says why — hashing a field the row does not carry would
    # make the tamper-evident chain unverifiable.


async def test_a_campaign_already_stopped_still_pages(alerts: _Alerts) -> None:
    """The CAS loses when the client pauses a second before us, or cancels. There is
    nothing to stop — and the operator still needs to know this list produced a spike."""
    tenant_id, agent_id, campaign_id = await _running_campaign()
    calls = await _connected_calls(tenant_id, agent_id, campaign_id, count=10)
    await _opt_out(tenant_id, calls[: complaint_spike.MIN_OPTOUTS])
    async with tenant_session(tenant_id) as session:
        await campaigns.set_campaign_status(
            session, campaign_id=campaign_id, to_status="paused", from_statuses=("running",)
        )

    verdict = await _check(tenant_id, campaign_id)
    assert verdict is not None
    assert verdict.paused is False
    assert "campaign_complaint_spike" in alerts.codes()


# --------------------------------------------------- the safety is wired into the tick
#
# Everything above tests the DETECTOR. This tests that the dispatcher obeys it, which is
# a different claim and the one the client is actually buying.


async def test_a_spike_stops_the_tick_before_a_single_contact_is_claimed() -> None:
    """The wiring, and the ORDER of it.

    `check_complaint_spike` is asked in `_dispatch_for_campaign` beside the standing
    compliance gate — before the claim, not inside the per-contact loop — and the module
    argues that placement: a spike is a fact about the CAMPAIGN, so it blocks every
    contact alike and costs no attempts if it is asked first.

    Both halves are asserted here because only one of them is visible in the return
    value. That the tick dialled nothing is the obvious half. That the contacts are still
    `pending` with `attempts = 0` is the half that proves the check ran BEFORE the CAS
    claim — asked one line later, the batch would already have been claimed and each
    contact would carry a spent attempt for a call that never happened, walking real
    people down a retry ladder because somebody else complained.
    """
    tenant_id, agent_id, campaign_id = await _launched_campaign(contacts=3)
    calls = await _connected_calls(tenant_id, agent_id, campaign_id, count=10)
    await _opt_out(tenant_id, calls[: complaint_spike.MIN_OPTOUTS])

    result = await campaign_dispatch._dispatch_for_campaign(
        tenant_id, campaign_id, 3, campaigns.DEFAULT_RETRY_POLICY
    )

    assert result == {"dialled": 0, "blocked": 0, "exhausted": 0}, result
    assert await _status(tenant_id, campaign_id) == "paused"
    async with tenant_session(tenant_id) as session:
        contacts = (
            await session.execute(
                text(
                    "SELECT status, attempts FROM campaign_contacts WHERE campaign_id = :c "
                    "ORDER BY created_at, id"
                ),
                {"c": campaign_id},
            )
        ).all()
        dialled = (
            await session.execute(
                text("SELECT count(*) FROM calls WHERE campaign_id = :c AND status = 'queued'"),
                {"c": campaign_id},
            )
        ).scalar()
    assert [(str(s), int(a)) for s, a in contacts] == [("pending", 0)] * 3, (
        "the spike was asked after the claim — three people are now one attempt down the "
        "retry ladder for a call nobody placed"
    )
    assert int(dialled or 0) == 0, "a campaign paused for a complaint spike still dialled"
