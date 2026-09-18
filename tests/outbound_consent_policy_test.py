"""D-624: on a service/transactional account, a MISSING opt-in refuses the dial.

**WHY THIS EXISTS, AND IT IS A REPLACEMENT RATHER THAN AN ADDITION.**
`compliance/service.check_dispatch` is deliberately permissive about consent — *"ABSENCE IS
NOT A REFUSAL, and that asymmetry is the whole design"* — because most dialable leads have
no `consent_ledger` row (a number typed in by staff, a CSV import, a caller who rang US) and
refusing all of them would be met as an outage rather than a rule.

That default was right while the client's DLT Principal-Entity registration stood behind the
dial: the REGISTRATION, not the ledger, separated a relationship call from a cold list. An
account sold on a SERVICE/TRANSACTIONAL footing has no such registration, and its entire
position is that it calls the client's own existing consenting customers about those
customers' own bookings — the classification TRAI's promotional/transactional line turns on.

Under the permissive default that position is an INTENTION. The failure it leaves open is
not the founder's: it is a client who signed up for appointment reminders, has a quiet month,
and uploads a prospect list because the tool is right there. Nothing refuses, nothing marks
the calls as different, and the first anyone knows is a complaint — under TCCCPR Reg 25(6),
which disconnects *"all telecom resources of the sender"* and blacklists for up to two years.

So these clauses pin the switch in both positions. The one that matters most is
`test_the_permissive_default_is_unchanged_for_every_other_account`: this must not become a
behaviour change for accounts nobody turned it on for.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import lifecycle as agent_lifecycle
from apps.api.compliance import consent
from apps.api.compliance.consent_policy import read_policy, write_policy
from apps.api.compliance.service import (
    NO_CONSENT_RECORD_RULE,
    PERSON_LEVEL_REFUSALS,
    DispatchDecision,
    check_dispatch,
)
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.conftest import (
    accept_agreements,
    accept_carrier_application,
    arm_agent_for_outbound,
    fund_wallet,
)

POLICY = "/v1/compliance/call-consent/policy"


async def _tenant(prefix: str = "d624") -> tuple[UUID, UUID]:
    """An account AND an agent, because the gate refuses `agent_missing` before it ever
    reaches the consent clause — so a fixture without one would pass this suite while
    proving nothing about consent."""
    created = await admin_service.create_organization(
        name="Consent Posture Co",
        slug=f"{prefix}-{uuid.uuid4().hex[:8]}",
        vertical_template="salon",
        billing_email="owner@example.test",
        language="te-IN",
        created_by=None,
    )
    tenant_id = UUID(str(created["id"]))
    async with tenant_session(tenant_id) as session:
        agent_id = await agent_lifecycle.create_agent(
            session,
            tenant_id=tenant_id,
            name="Reminders",
            direction="outbound",
            language_primary="te-IN",
        )
        # LIVE BY STATEMENT, NOT BY PUBLISHING. `check_dispatch` refuses `agent_not_live`
        # long before it reaches the consent clause, so a fixture that skipped this would
        # pass every assertion below while proving nothing about consent. Running the real
        # publish flow here would couple this suite to prompt composition, disclosure lines
        # and an engine round trip — each of which has its own suite, none of which this
        # one is about.
        await session.execute(
            text("UPDATE agents SET status = 'live' WHERE id = :a"), {"a": agent_id}
        )
        await session.commit()

    # THE REST OF THE GATE, SUPPLIED RATHER THAN SOFTENED. `check_dispatch` asks the
    # paperwork, money and carrier questions BEFORE it reaches consent, so a tenant missing
    # any of them is refused for a reason this suite is not about — and would then pass
    # `assert rule != NO_CONSENT_RECORD_RULE` while proving nothing. These are conftest's
    # own arming helpers, each of which records the same facts production records.
    await accept_agreements(tenant_id)
    await accept_carrier_application(tenant_id)
    await arm_agent_for_outbound(tenant_id, agent_id)
    await fund_wallet(tenant_id)
    return tenant_id, agent_id


def _fresh_phone() -> str:
    """A number no other suite has a DNC or consent row for, so only this clause's fact
    can be what refuses us."""
    return f"+9199{uuid.uuid4().int % 100000000:08d}"


async def _set_policy(tenant_id: UUID, *, enabled: bool) -> bool:
    async with tenant_session(tenant_id) as session:
        changed = await write_policy(session, enabled=enabled)
        await session.commit()
    return changed


async def _gate(tenant_id: UUID, agent_id: UUID, phone: str) -> DispatchDecision:
    """The dial gate, asked at a FIXED hour.

    ⚠ **THESE CLAUSES USED TO READ THE WALL CLOCK AND WERE THEREFORE TIME BOMBS.** Without
    the pin they passed inside Indian calling hours and failed outside them, with every
    assertion reporting `calling_hours` instead of the consent rule it was written for —
    which is not a flake, it is a suite that only tests anything for part of the day. It
    duly failed the moment a container restart moved the run into the evening.

    11:00 IST is the middle of the permitted window, and `lead_consent_carryover_test`
    pins the same instant for the same reason. What this suite measures is the CONSENT
    clause; the hours are a different rule with its own tests.
    """
    monkey = pytest.MonkeyPatch()
    monkey.setattr(
        "apps.api.compliance.service.ist_now",
        lambda: datetime(2026, 8, 11, 11, 0, tzinfo=UTC),
    )
    try:
        async with tenant_session(tenant_id) as session:
            return await check_dispatch(
                session, tenant_id=tenant_id, agent_id=agent_id, phone_e164=phone
            )
    finally:
        monkey.undo()


async def test_the_permissive_default_is_unchanged_for_every_other_account() -> None:
    """**THE CLAUSE THAT MATTERS MOST.** A new column that silently refused dials on every
    existing account would be the "outage rather than a rule" the permissive comment warns
    about — delivered by the very change that quotes it. Off by default, and absence of a
    consent row still dials."""
    tenant_id, agent_id = await _tenant()

    async with tenant_session(tenant_id) as session:
        assert await read_policy(session) is False

    decision = await _gate(tenant_id, agent_id, _fresh_phone())
    assert decision.rule != NO_CONSENT_RECORD_RULE


async def test_a_number_with_no_opt_in_is_refused_once_the_policy_is_on() -> None:
    """The whole point: consent stops being a thing the account intends and becomes a thing
    the gate checks."""
    tenant_id, agent_id = await _tenant()
    await _set_policy(tenant_id, enabled=True)

    decision = await _gate(tenant_id, agent_id, _fresh_phone())

    assert decision.allowed is False
    assert decision.rule == NO_CONSENT_RECORD_RULE
    assert decision.reason is not None
    # The message has to tell a client what to DO. "No consent" names the state; naming the
    # acts that create one is what makes the refusal actionable rather than a wall.
    assert "opt-in" in decision.reason


async def test_an_affirmative_opt_in_dials_on_the_same_account() -> None:
    """The refusal is about the RECORD, not about the account. An account with the policy on
    is not an account that cannot make calls — it is one that calls people who said yes."""
    tenant_id, agent_id = await _tenant()
    await _set_policy(tenant_id, enabled=True)
    phone = _fresh_phone()

    async with tenant_session(tenant_id) as session:
        await consent.record_call_consent(
            session,
            tenant_id=tenant_id,
            raw_phone=phone,
            status="granted",
            source="web_form_optin",
            evidence={"form_id": "booking-v3", "notice_version": "2026-09-01"},
            expires_at=None,
        )
        await session.commit()

    decision = await _gate(tenant_id, agent_id, phone)
    assert decision.rule != NO_CONSENT_RECORD_RULE


async def test_a_withdrawn_opt_in_still_refuses_with_its_own_rule() -> None:
    """⚠ **TWO REFUSALS, NOT ONE, AND AN OPERATOR NEEDS THE DIFFERENCE.** `no_consent` means
    a record EXISTS and says no — never call this person again. `no_consent_record` means
    there is nothing on file — capture consent and you may. Collapsing them would tell a
    client to go and ask someone who has already refused."""
    tenant_id, agent_id = await _tenant()
    await _set_policy(tenant_id, enabled=True)
    phone = _fresh_phone()

    async with tenant_session(tenant_id) as session:
        await consent.record_call_consent(
            session,
            tenant_id=tenant_id,
            raw_phone=phone,
            status="withdrawn",
            source="web_form_optin",
            expires_at=None,
        )
        await session.commit()

    decision = await _gate(tenant_id, agent_id, phone)
    assert decision.allowed is False
    assert decision.rule == "no_consent"


async def test_the_refusal_is_person_level_so_a_dialler_settles_rather_than_retries() -> None:
    """A missing opt-in does not become present by waiting thirty minutes. Outside
    `PERSON_LEVEL_REFUSALS` a batch dialler re-claims the contact every tick for ever — the
    livelock that set exists for, and which this repository has now hit three times."""
    assert NO_CONSENT_RECORD_RULE in PERSON_LEVEL_REFUSALS


async def test_the_switch_reports_whether_it_moved() -> None:
    """A PUT is idempotent, so the audit row needs to distinguish the request that changed
    the account from the four that repeated it."""
    tenant_id, _agent_id = await _tenant()

    assert await _set_policy(tenant_id, enabled=True) is True
    assert await _set_policy(tenant_id, enabled=True) is False
    assert await _set_policy(tenant_id, enabled=False) is True


async def test_one_account_s_posture_does_not_reach_another() -> None:
    """RLS, asserted rather than assumed — the column is read with no tenant predicate
    because `organizations`' policy matches on `id`, and that reliance is exactly what hard
    rule 1 says to prove rather than trust."""
    strict, strict_agent = await _tenant("d624-strict")
    relaxed, relaxed_agent = await _tenant("d624-relaxed")
    await _set_policy(strict, enabled=True)

    async with tenant_session(relaxed) as session:
        assert await read_policy(session) is False

    assert (await _gate(strict, strict_agent, _fresh_phone())).rule == NO_CONSENT_RECORD_RULE
    assert (await _gate(relaxed, relaxed_agent, _fresh_phone())).rule != NO_CONSENT_RECORD_RULE


async def test_an_expired_grant_is_refused_before_the_missing_record_clause() -> None:
    """An expired grant is a record, so it takes `consent_expired` and not the new rule.
    Ordering matters to the operator: "their permission lapsed, get a fresh one" is a
    different instruction from "you never had one"."""
    tenant_id, agent_id = await _tenant()
    await _set_policy(tenant_id, enabled=True)
    phone = _fresh_phone()

    # INSERTED DIRECTLY, AND THAT IS THE ONLY WAY TO REACH THIS STATE. `record_call_consent`
    # refuses an `expires_at` already in the past (`consent_expiry_in_past`) — correctly: an
    # already-expired grant is not a record of anything. Production reaches this row the only
    # other way, by a live grant getting older, which a test cannot wait for.
    # `tests/lead_consent_carryover_test._insert_callback_consent` does the same for the same
    # reason; the shape is copied from there rather than re-derived.
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO consent_ledger (id, tenant_id, phone_e164, purpose, status, "
                "consent_source, evidence, captured_at, expires_at, created_at) VALUES "
                "(:id, :tid, :p, 'callback', 'granted', 'web_form_optin', "
                "CAST(:ev AS jsonb), now(), :exp, now())"
            ),
            {
                "id": uuid.uuid4(),
                "tid": tenant_id,
                "p": phone,
                "ev": '{"form_id": "booking-v3", "notice_version": "2026-09-01"}',
                "exp": datetime.now(UTC) - timedelta(days=1),
            },
        )
        await session.commit()

    decision = await _gate(tenant_id, agent_id, phone)
    assert decision.allowed is False
    assert decision.rule == "consent_expired"


async def test_the_column_defaults_false_in_the_database_itself() -> None:
    """Not just in the model. A row inserted by anything that does not go through SQLAlchemy
    — a migration backfill, a fixture, a psql session — must also be permissive, because the
    stricter default is the one that turns into an outage."""
    tenant_id, _agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(
                text("SELECT outbound_requires_consent FROM organizations WHERE id = :t"),
                {"t": tenant_id},
            )
        ).scalar_one()
    assert stored is False


# ---------------------------------------------------------------------------------------
# THE ROUTES, OVER HTTP. The clauses above drive the service functions directly, which
# proves the RULE but not the SEAM: the permission each route declares, the shape it
# answers with, and the audit row the write leaves are all things a caller depends on and
# none of them is exercised by an in-process call. `check_coverage_ratchet` counts this
# surface under hard rule 5 and was right to refuse the first version of this file.
# ---------------------------------------------------------------------------------------


async def _member(prefix: str, role: str = "owner") -> tuple[UUID, UUID, str, str]:
    """(tenant_id, agent_id, org slug, dev bearer token) — the arming fixture above plus a
    member to send the request as. `role` is a parameter because the whole point of the
    write's permission is that not every role holds it."""
    tenant_id, agent_id = await _tenant(prefix)
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:id, :email, now(), now())"
            ),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, :role, now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id, "role": role},
        )
        slug = (
            await session.execute(
                text("SELECT slug FROM organizations WHERE id = :t"), {"t": tenant_id}
            )
        ).scalar_one()
    return tenant_id, agent_id, str(slug), f"dev:client:{user_id}"


def _http() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _headers(token: str, slug: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}


async def test_the_owner_reads_and_moves_the_switch_over_http() -> None:
    """The whole seam in one pass: the default comes back, the PUT answers with the value
    it stored, and a second read agrees with the write rather than with the default."""
    _tid, _agent, slug, token = await _member("d624-http")
    async with _http() as client:
        headers = _headers(token, slug)

        before = await client.get(POLICY, headers=headers)
        assert before.status_code == 200
        assert before.json() == {"outbound_requires_consent": False}

        put = await client.put(POLICY, headers=headers, json={"outbound_requires_consent": True})
        assert put.status_code == 200
        assert put.json() == {"outbound_requires_consent": True}

        after = await client.get(POLICY, headers=headers)
        assert after.json() == {"outbound_requires_consent": True}


async def test_the_write_leaves_an_audit_record_carrying_the_direction(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An investigator asking "when did this account start dialling people with no opt-in"
    needs the VALUE, not just that somebody touched the setting.

    THE VALUE IS IN THE LOG STREAM AND NOT IN `audit_log`, which is a property of the audit
    chain rather than of this route: `audit_log` carries no `summary` column, because
    hashing a field the row does not hold would make the chain unverifiable
    (`compliance/audit.py:383-389`). The row proves WHO and WHEN; the JSONL record keyed by
    the same entry id carries WHAT. This clause asserts both halves, because either alone
    would let the other rot.
    """
    tenant_id, _agent, slug, token = await _member("d624-audit")
    with caplog.at_level(logging.INFO, logger="apps.api.compliance.audit"):
        async with _http() as client:
            await client.put(
                POLICY, headers=_headers(token, slug), json={"outbound_requires_consent": True}
            )

    async with tenant_session(tenant_id) as session:
        entry_id = (
            await session.execute(
                text(
                    "SELECT id FROM audit_log WHERE tenant_id = :t "
                    "AND action = 'organization.outbound_consent_policy_set'"
                ),
                {"t": tenant_id},
            )
        ).scalar_one()

    summaries = [
        r
        for r in caplog.records
        if r.getMessage() == "audit" and getattr(r, "entry_id", None) == str(entry_id)
    ]
    assert len(summaries) == 1
    assert summaries[0].outbound_requires_consent is True
    assert summaries[0].changed is True


async def test_a_staff_member_may_read_the_posture_but_not_move_it() -> None:
    """`org:read` / `org:manage`, asserted rather than assumed. Seeing why a dial was
    refused is not the authority to widen who the account may call — and a staff member who
    could flip it would be deciding that about their own employer."""
    _tid, _agent, slug, token = await _member("d624-staff", role="staff")
    async with _http() as client:
        headers = _headers(token, slug)
        assert (await client.get(POLICY, headers=headers)).status_code == 200
        refused = await client.put(
            POLICY, headers=headers, json={"outbound_requires_consent": True}
        )
    assert refused.status_code == 403


async def test_an_account_this_session_cannot_see_is_a_404_and_not_a_permissive_answer() -> None:
    """⚠ **THE ONE FAILURE MODE THAT WOULD BE WORSE THAN AN ERROR.** Under RLS an account
    that is not this session's is indistinguishable from one that does not exist, so a
    reader that treated "no row" as `false` would report "this account calls anyone" about
    an account it knows nothing about — and a writer that did would report a change it did
    not make. Both raise."""
    absent = uuid7()
    async with tenant_session(absent) as session:
        with pytest.raises(ProblemError) as read_refusal:
            await read_policy(session)
        with pytest.raises(ProblemError) as write_refusal:
            await write_policy(session, enabled=True)
    assert read_refusal.value.status == 404
    assert write_refusal.value.status == 404
