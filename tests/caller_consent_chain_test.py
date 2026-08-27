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
from apps.api.compliance.registration import pe_verification_is_stale
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
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
