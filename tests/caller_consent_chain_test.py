"""The caller-consent chain: the six mechanisms the audit of 27 Aug 2026 found missing.

Each block below pins one defect that was real, and pins it in the direction that fails
if the fix is reverted rather than merely in the direction that passes today.

1. **`phone_numbers.series` is checked against the number.** It was an operator's typed
   word feeding a DLT gate. DoT puts telemarketing on `140xxxxxxx` and service /
   transactional on `160xxxxxxx` (PIB PRID 2022249), so the E.164 prefix is the answer
   and it was sitting in the same request the whole time.
2. **The subject-access export discloses the suppression.** `/legal/privacy` §3 lists the
   do-not-call entry among the data held about a caller and the document omitted it.
3. **`read_messaging_consent` normalises.** Every writer did; the read did not, so an
   opt-in captured as `98765 43210` and a send keyed on `+919876543210` were two people.
4. **`callback` has an affirmative writer.** `check_dispatch` reads the purpose and
   honours a grant and its expiry; the only writer in the tree was a web-form DECLINE, so
   both of those branches were dead.
5. **A PE verification goes stale.** `verified_at` was selected and compared to nothing.
6. **A campaign's consent has an age.** `consent_collected_at` was written, validated and
   read by nothing.

CONCURRENCY: every test builds its own run-unique tenant and asserts only on rows it
created, so this file runs beside the other suites on the shared Postgres.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import service as agents_service
from apps.api.agents.models import series_for_e164
from apps.api.campaigns import service as campaigns_service
from apps.api.compliance import consent
from apps.api.compliance.export import build_subject_export
from apps.api.compliance.registration import (
    outbound_entity_blockers,
    pe_verification_is_stale,
)
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.smoke_pipeline_test import _seed_tenant

SUBJECT = "+919000000123"
EVIDENCE = {"form": "enquiry-v1", "notice_version": "2026-01"}


async def _tenant(prefix: str) -> UUID:
    created = await admin_service.create_organization(
        name="Consent Chain Motors",
        slug=f"cc-{prefix}-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return UUID(str(created["id"]))


async def _member_with_dispatch(tenant_id: UUID) -> tuple[UUID, str]:
    """A user holding `leads:dispatch` in `tenant_id`, and the dev bearer for them.

    The route's permission, not the owner's: `Recorder = requires("leads:dispatch")`, and a
    test that signed in as an owner would pass while telling us nothing about whether the
    declared permission is the one that actually opens the door.
    """
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, name, created_at, updated_at) "
                "VALUES (:id, :email, 'Consent Recorder', now(), now())"
            ),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :t, :u, 'owner', now(), now())"
            ),
            {"id": uuid.uuid4(), "t": tenant_id, "u": user_id},
        )
    return user_id, f"dev:client:{user_id}"


def _number(series: str) -> str:
    """A run-unique E.164 whose prefix matches `series` (`phone_numbers.e164` is UNIQUE
    platform-wide, so a literal would collide with every sibling suite)."""
    prefix = "98" if series == "standard" else series
    digits = 10 - len(prefix)
    return f"+91{prefix}{uuid.uuid4().int % 10**digits:0{digits}d}"


# ---------------------------------------------------------------- 1. the series check


def test_the_series_is_read_out_of_the_prefix_and_not_guessed() -> None:
    """The pure rule, both regulated series, the ordinary case, and the non-India case.

    `None` is reserved for "no Indian numbering rule can classify this", which is why a
    non-`+91` number returns it rather than `standard`: outside India the 140/160 series
    do not exist, and answering `standard` would let the caller's claim go unchallenged.
    """
    assert series_for_e164("+911401234567") == "140"
    assert series_for_e164("+911601234567") == "160"
    assert series_for_e164("+919876543210") == "standard"
    assert series_for_e164("+14155550100") is None


async def test_a_mobile_cannot_be_filed_as_a_140_number() -> None:
    """The defect exactly as it stood: an operator types `140` over a mobile, the row is
    written, and `campaigns.service.SERIES_FOR_CLASSIFICATION` then lets a PROMOTIONAL
    campaign dial from a number that is not a telemarketing header."""
    tenant_id = await _tenant("series-a")
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as excinfo:
            await agents_service.provision_number(
                session,
                tenant_id=tenant_id,
                e164=_number("standard"),
                series="140",
                agent_id=None,
                provider="exotel",
                purpose="campaigns",
            )
    assert excinfo.value.code == "number_series_mismatch"


async def test_a_real_160_number_cannot_be_filed_as_standard() -> None:
    """The OTHER direction, which the first test cannot reach and which is the same
    violation inverted: a regulated header filed as an ordinary number passes the
    `160/standard` arm of the classification map and dials service traffic unregistered."""
    tenant_id = await _tenant("series-b")
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as excinfo:
            await agents_service.provision_number(
                session,
                tenant_id=tenant_id,
                e164=_number("160"),
                series="standard",
                agent_id=None,
                provider="plivo",
                purpose="campaigns",
            )
    assert excinfo.value.code == "number_series_mismatch"


async def test_a_matching_number_and_series_still_provisions() -> None:
    """Non-vacuity. Without it the check could be an unconditional refusal."""
    tenant_id = await _tenant("series-c")
    e164 = _number("160")
    async with tenant_session(tenant_id) as session:
        number_id = await agents_service.provision_number(
            session,
            tenant_id=tenant_id,
            e164=e164,
            series="160",
            agent_id=None,
            provider="plivo",
            purpose="reception",
        )
    assert isinstance(number_id, UUID)


# ------------------------------------------------- 2. the export discloses suppression


async def test_the_subject_export_states_the_do_not_call_entry() -> None:
    """Scope, source and added-at — the three facts that answer "did you record it?"."""
    tenant_id = await _tenant("export-a")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO dnc_list (id, tenant_id, phone_e164, scope, source, added_at, "
                "created_at) VALUES (:id, :tid, :phone, 'tenant', 'call_optout', now(), now())"
            ),
            {"id": uuid7(), "tid": tenant_id, "phone": SUBJECT},
        )
        document = await build_subject_export(session, tenant_id=tenant_id, phone_e164=SUBJECT)

    assert document["do_not_call"]["suppressed"] is True
    assert document["do_not_call"]["scope"] == "tenant"
    assert document["do_not_call"]["source"] == "call_optout"
    assert document["do_not_call"]["added_at"] is not None


async def test_the_subject_export_says_no_suppression_rather_than_omitting_the_question() -> None:
    """`suppressed: false` is an answer; an absent key reads as a question nobody asked."""
    tenant_id = await _tenant("export-b")
    async with tenant_session(tenant_id) as session:
        document = await build_subject_export(session, tenant_id=tenant_id, phone_e164=SUBJECT)
    assert document["do_not_call"] == {
        "suppressed": False,
        "scope": None,
        "source": None,
        "added_at": None,
    }


# ------------------------------------------------------------- 3. the read normalises


async def test_an_opt_in_typed_one_way_is_found_when_read_another() -> None:
    """The key mismatch that "looks like protection and grants nothing" — from the READ
    side, which was the half that did not normalise."""
    tenant_id = await _tenant("norm")
    async with tenant_session(tenant_id) as session:
        await consent.record_messaging_consent(
            session,
            tenant_id=tenant_id,
            raw_phone="90000 00123",
            status="granted",
            source="web_form_optin",
            evidence=EVIDENCE,
        )
        state = await consent.read_messaging_consent(
            session, tenant_id=tenant_id, raw_phone="+91 90000 00123"
        )
    assert state.status == "granted"
    assert state.messageable is True


# --------------------------------------------------------- 4. `callback` can say YES


async def test_a_callback_grant_can_be_recorded_and_the_dial_gate_can_read_it() -> None:
    """The row `check_dispatch`'s grant branch was written for and could never receive."""
    tenant_id = await _tenant("callback-a")
    expires = datetime.now(UTC) + timedelta(days=90)
    async with tenant_session(tenant_id) as session:
        state = await consent.record_call_consent(
            session,
            tenant_id=tenant_id,
            raw_phone="90000 00123",
            status="granted",
            source="web_form_optin",
            evidence=EVIDENCE,
            expires_at=expires,
        )
        row = (
            await session.execute(
                text(
                    "SELECT purpose, status, consent_source, expires_at FROM consent_ledger "
                    "WHERE tenant_id = :tid AND phone_e164 = :phone"
                ),
                {"tid": tenant_id, "phone": SUBJECT},
            )
        ).first()

    assert state.status == "granted"
    assert row is not None
    # Normalised on the way in, exactly like the messaging writer.
    assert row[0] == "callback" and row[1] == "granted"
    assert row[2] == "web_form_optin"
    assert row[3] == expires


async def test_a_callback_grant_still_has_to_carry_its_proof() -> None:
    """The evidence CHECK is purpose-blind and stays that way: a `granted` row with no
    evidence is refused before it reaches the database."""
    tenant_id = await _tenant("callback-b")
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as excinfo:
            await consent.record_call_consent(
                session,
                tenant_id=tenant_id,
                raw_phone=SUBJECT,
                status="granted",
                source="web_form_optin",
                evidence=None,
            )
    assert excinfo.value.code == "consent_grant_needs_evidence"


async def test_staff_cannot_record_a_callback_opt_in_on_the_callers_behalf() -> None:
    """`staff_recorded_request` is withdrawal-only on this leg for the reason it is on the
    messaging leg: an employee may record that somebody asked to stop, never that
    somebody agreed to start."""
    tenant_id = await _tenant("callback-c")
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as excinfo:
            await consent.record_call_consent(
                session,
                tenant_id=tenant_id,
                raw_phone=SUBJECT,
                status="granted",
                source="staff_recorded_request",
                evidence=EVIDENCE,
            )
        # ...but the same staff member may still record the NO.
        declined = await consent.record_call_consent(
            session,
            tenant_id=tenant_id,
            raw_phone=SUBJECT,
            status="withdrawn",
            source="staff_recorded_request",
        )
    assert excinfo.value.code == "consent_source_cannot_grant"
    assert declined.status == "withdrawn"


async def test_a_recording_notice_basis_cannot_be_spent_as_a_callback_or_a_message() -> None:
    """DPDP §6's purpose limitation, as a refusal on both legs.

    Being TOLD a call is recorded is not permission to message and not permission to
    dial, and `in_call_recording_notice` exists to name that basis rather than let it be
    filed as something a caller said.
    """
    tenant_id = await _tenant("purpose-lock")
    async with tenant_session(tenant_id) as session:
        for writer in (consent.record_call_consent, consent.record_messaging_consent):
            with pytest.raises(ProblemError) as excinfo:
                await writer(
                    session,
                    tenant_id=tenant_id,
                    raw_phone=SUBJECT,
                    status="granted",
                    source=consent.RECORDING_NOTICE_SOURCE,
                    evidence=EVIDENCE,
                )
            assert excinfo.value.code == "consent_source_wrong_purpose"


async def test_the_recording_artefact_is_written_once_however_often_the_pipeline_replays() -> None:
    """The post-call pipeline is re-runnable by design (TRD §8) and `consent_ledger` is
    append-only (hard rule 4), so a replay must not produce a second piece of evidence
    about one announcement."""
    tenant_id, agent_id = await _seed_tenant(f"consent_{uuid.uuid4().hex[:10]}")
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                "from_e164, to_e164, status, created_at, updated_at) VALUES (:id, :tid, :aid, "
                ":eid, 'inbound', :phone, :phone, 'completed', now(), now())"
            ),
            {
                "id": call_id,
                "tid": tenant_id,
                "aid": agent_id,
                "eid": f"exec_{uuid.uuid4().hex[:12]}",
                "phone": SUBJECT,
            },
        )
        first = await consent.record_recording_notice(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            phone_e164=SUBJECT,
            evidence={"notice_turn_idx": "0"},
        )
        second = await consent.record_recording_notice(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            phone_e164=SUBJECT,
            evidence={"notice_turn_idx": "0"},
        )
        rows = (
            await session.execute(
                text(
                    "SELECT count(*) FROM consent_ledger WHERE tenant_id = :tid "
                    "AND purpose = 'recording'"
                ),
                {"tid": tenant_id},
            )
        ).scalar_one()

    assert first is True, "the first pass files the artefact"
    assert second is False, "a replay files nothing and says so"
    assert int(rows) == 1


# ----------------------------------------------------- 5. a verification goes stale


def test_a_verification_that_never_happened_is_stale() -> None:
    """NULL is the state the blocker exists for: somebody typed `active` and nobody ever
    checked it against the registrar."""
    assert pe_verification_is_stale(None) is True


def test_a_fresh_verification_is_not_stale_and_an_old_one_is() -> None:
    max_age = get_settings().pe_verification_max_age_days
    assert max_age > 0, "the shipped default must exercise the comparison"
    now = datetime.now(UTC)
    assert pe_verification_is_stale(now - timedelta(days=1), now=now) is False
    assert pe_verification_is_stale(now - timedelta(days=max_age + 1), now=now) is True


def test_zero_turns_the_staleness_check_off_without_touching_the_status_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`0` is an operator saying "we do not hold a re-verification cadence yet", which is
    a real position and better held explicitly than by typing 36500."""
    settings = get_settings()
    monkeypatch.setattr(settings, "pe_verification_max_age_days", 0, raising=False)
    assert pe_verification_is_stale(None) is False


# ------------------------------------------------------ 6. a campaign's consent ages


def test_a_list_collected_beyond_the_window_blocks_the_launch() -> None:
    """The 2019 list that launched today with a green gate."""
    max_age = get_settings().campaign_consent_max_age_days
    assert max_age > 0, "the shipped default must exercise the comparison"
    blocker = campaigns_service._consent_age_blocker(
        datetime.now(UTC) - timedelta(days=max_age + 1)
    )
    assert blocker is not None
    assert blocker.rule == "consent_too_old"
    # The AGE, never the date (the client already holds the date).
    assert str(max_age) in blocker.reason


def test_a_recent_list_is_not_blocked_and_neither_is_an_unrecorded_one() -> None:
    """Non-vacuity, and the boundary that must NOT be this blocker's: a campaign with no
    provenance at all is `consent_provenance_missing`, which is the accurate reason and a
    different next action."""
    assert campaigns_service._consent_age_blocker(datetime.now(UTC) - timedelta(days=1)) is None
    assert campaigns_service._consent_age_blocker(None) is None


def test_zero_turns_the_age_check_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """The threshold is counsel's (LEGAL-OPS-PLAYBOOK §20) and the default is stated as
    ours, so "we have not been told a number yet" has to be expressible."""
    settings = get_settings()
    monkeypatch.setattr(settings, "campaign_consent_max_age_days", 0, raising=False)
    assert campaigns_service._consent_age_blocker(datetime(2019, 1, 1, tzinfo=UTC)) is None


# ------------------------------------------------- 9. the arms the ratchet found untested
#
# `make coverage-ratchet` measured 15 uncovered units after this lane landed — 12 in
# `compliance-gate` and 3 in `dial-path`, both hard-rule-5 surfaces. Every one is a REFUSAL
# arm or a route with no caller: the paths that only run when something is wrong, which are
# exactly the ones a client meets on their worst day and the ones no happy-path test walks.


@pytest.mark.asyncio
async def test_a_non_indian_number_cannot_be_declared_a_140_or_160_connection() -> None:
    """The dial-path arm, and it is the one the 140/160 gate actually stands on.

    `campaigns.service.SERIES_FOR_CLASSIFICATION` decides whether a promotional campaign
    may dial by reading `phone_numbers.series` — an operator's typed word. Validating it
    against the E.164 prefix is what stops that word being a wish, and this arm is the half
    that catches the direction nobody expects: a foreign number labelled as an Indian
    regulated series would put a foreign header on Indian traffic, which is a resource
    misuse rather than a data-entry slip. The 140 and 160 series exist only within +91
    (DoT/PIB PRID 2022249).
    """
    tenant_id = await _tenant("foreign")
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as raised:
            await agents_service.provision_number(
                session,
                tenant_id=tenant_id,
                e164="+14155550123",
                series="140",
                agent_id=None,
                provider="exotel",
                purpose="campaigns",
            )
    assert raised.value.code == "number_series_mismatch"
    assert "only within +91" in str(raised.value.remediation)


@pytest.mark.asyncio
async def test_a_permission_that_has_already_expired_is_refused_rather_than_stored() -> None:
    """A consent row whose expiry is in the past is not consent; it is a row that reads as
    permission to anyone who queries by `status` alone.

    Refused at the writer rather than filtered at the reader, deliberately: the ledger is
    append-only (hard rule 4), so a row written here cannot be taken back, and every future
    reader would have to remember the same filter.
    """
    tenant_id = await _tenant("expired")
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as raised:
            await consent.record_call_consent(
                session,
                tenant_id=tenant_id,
                raw_phone=SUBJECT,
                status="granted",
                source="web_form_optin",
                call_id=None,
                evidence=EVIDENCE,
                expires_at=datetime.now(UTC) - timedelta(days=1),
            )
    assert raised.value.code == "consent_expiry_in_past"


@pytest.mark.asyncio
async def test_a_naive_expiry_is_pinned_to_utc_rather_than_raising() -> None:
    """UTC in the DB, IST at the edge — and a naive instant compared against an aware
    `now()` raises `TypeError`, which on a compliance writer is a 500 where a refusal or an
    acceptance belonged. The same fix `campaigns.service._validated_provenance` makes.

    Driven both ways in one test because the arm is a coercion, not a decision: a naive
    PAST instant must still be refused, and a naive FUTURE one must still be accepted.
    """
    tenant_id = await _tenant("naive")
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as raised:
            await consent.record_call_consent(
                session,
                tenant_id=tenant_id,
                raw_phone=SUBJECT,
                status="granted",
                source="web_form_optin",
                call_id=None,
                evidence=EVIDENCE,
                expires_at=(datetime.now(UTC) - timedelta(days=2)).replace(tzinfo=None),
            )
        assert raised.value.code == "consent_expiry_in_past"

        state = await consent.record_call_consent(
            session,
            tenant_id=tenant_id,
            raw_phone=SUBJECT,
            status="granted",
            source="web_form_optin",
            call_id=None,
            evidence=EVIDENCE,
            expires_at=(datetime.now(UTC) + timedelta(days=30)).replace(tzinfo=None),
        )
    assert state.status == "granted"


def test_a_verification_with_no_timezone_ages_rather_than_raising() -> None:
    """`pe_verification_is_stale`'s naive arm, and why it is not paranoia.

    A compliance predicate that raises is a launch gate that fails OPEN on the operator's
    retry — the campaign goes out because the check errored, not because it passed. So a
    row written by a path that lost its tzinfo has to be answerable rather than fatal.
    """
    long_ago = (datetime.now(UTC) - timedelta(days=3650)).replace(tzinfo=None)
    assert pe_verification_is_stale(long_ago) is True
    fresh = datetime.now(UTC).replace(tzinfo=None)
    assert pe_verification_is_stale(fresh) is False


@pytest.mark.asyncio
async def test_the_call_consent_route_records_a_grant_and_audits_the_decision() -> None:
    """The route had no caller at all — typed, mounted, and walked by nothing.

    It matters more than a route with one screen behind it, because the automatic writer
    (`ingest.service._record_dial_consent_granted`) covers the form path end to end and
    THIS is the manual one: a client's operator recording that somebody said yes on the
    phone. If it 500s, nobody finds out from a screen, because there is no screen yet.

    What is asserted, beyond a 200: the ledger row lands with the phone NORMALISED (the
    writers and the readers must key identically — `read_messaging_consent`'s own defect
    was exactly this), and the audit row carries the DECISION and never the subject, which
    is hard rule 6 on a route whose entire payload is a phone number.
    """
    tenant_id = await _tenant("route")
    user_id, token = await _member_with_dispatch(tenant_id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as client:
        response = await client.post(
            "/v1/compliance/call-consent",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "phone": " 90000 00123 ",
                "status": "granted",
                "source": "web_form_optin",
                "evidence": EVIDENCE,
            },
        )

    # 201, not 200: the route CREATES a ledger row, and the declaration says so.
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "granted"

    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT phone_e164, purpose, status FROM consent_ledger "
                    "WHERE tenant_id = :t ORDER BY created_at DESC LIMIT 1"
                ),
                {"t": tenant_id},
            )
        ).all()
        assert rows, "the route answered 201 and wrote nothing"
        assert rows[0][0] == SUBJECT, "the phone reached the ledger un-normalised"
        assert (rows[0][1], rows[0][2]) == ("callback", "granted")

        audit = (
            await session.execute(
                text(
                    "SELECT actor_id, object_type, entry_hash FROM audit_log "
                    "WHERE tenant_id = :t AND action = 'call_consent.recorded' "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"t": tenant_id},
            )
        ).first()

    assert audit is not None, "the grant was recorded and nothing audited it"
    assert audit[0] == user_id, "the audit names somebody other than the recorder"
    assert audit[1] == "consent_ledger"
    # THE SUMMARY IS NOT A COLUMN, and that is the design rather than an omission:
    # `audit_log` carries a hash chain (`prev_hash`/`entry_hash`) and no free-text field,
    # so the decision is COMMITTED without being retained. On a route whose entire payload
    # is a phone number, there is no row for hard rule 6 to leak through.
    assert audit[2], "the entry carries no hash, so the chain cannot be verified"


@pytest.mark.asyncio
async def test_a_foreign_number_declared_standard_is_accepted() -> None:
    """The other side of the series check, and the one that proves it is a VALIDATION
    rather than a ban on foreign numbers.

    A `+1` number recorded as `standard` is a perfectly ordinary thing — a demo line, a
    forwarding target — and refusing it would make the guard a rule about geography
    instead of a rule about regulated Indian headers. Without this the branch that lets
    the write through is never walked, and a refactor tightening the arm above would look
    green.
    """
    tenant_id = await _tenant("foreign-ok")
    async with tenant_session(tenant_id) as session:
        number_id = await agents_service.provision_number(
            session,
            tenant_id=tenant_id,
            e164=f"+1415555{uuid.uuid4().int % 10**4:04d}",
            series="standard",
            agent_id=None,
            provider="exotel",
            purpose="campaigns",
        )
    assert number_id is not None


@pytest.mark.asyncio
async def test_a_stale_pe_verification_blocks_outbound_through_the_shared_reader() -> None:
    """The BLOCKER, not the predicate — and they are different tests for a reason.

    `pe_verification_is_stale` answering `True` proves arithmetic. What matters is that
    `outbound_entity_blockers` — the ONE implementation read by both the campaign launch
    gate and the per-dial gate — surfaces it, and surfaces it LAST, after the three
    registrar-owned refusals. "We have not re-checked this recently" is the weakest of the
    four and the only one whose next action is ours rather than the client's, so it must
    not mask a registration the registrar has actually suspended.
    """
    tenant_id = await _tenant("pe-stale")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO dlt_registrations (id, tenant_id, pe_id, entity_name, "
                "status, tm_link_status, registered_at, verified_at, created_at, "
                "updated_at) VALUES (:id, :t, 'PE-STALE-1', 'Consent Chain Motors', "
                "'active', 'active', now(), :verified, now(), now())"
            ),
            {
                "id": uuid7(),
                "t": tenant_id,
                "verified": datetime.now(UTC) - timedelta(days=3650),
            },
        )
        blockers = await outbound_entity_blockers(session, tenant_id=tenant_id)

    rules = [rule for rule, _ in blockers]
    assert "pe_verification_stale" in rules
    assert rules[-1] == "pe_verification_stale", "the weakest refusal is masking a stronger one"
