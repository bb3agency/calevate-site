"""The CLIENT's WhatsApp alert opt-in — the ledger, the constraints and the surfaces.

Migration `e6b2d94f31a7` gives the hot-lead alert somewhere to read an opt-in from, which
is what turns `notify_hot_lead_whatsapp` from "refuses 100% of the time" into a feature:
`resolve_destination` hardcoded `opt_in_at=None` because no column existed, so FLOWS §6's
"WhatsApp+email to owner within 2 min" has only ever delivered the email half.

This file pins the properties that keep the row worth trusting, as behaviour rather than
as a description of the code:

1. **Tenancy (hard rule 1).** Another tenant reads zero rows and can write none.
2. **Never assumed.** A grant names the wording it rests on; a self-serve grant was
   recorded BY its own subject; an operator's grant names the operator and the document;
   every row names exactly one recorder. Asserted against the DATABASE as well as the
   service, because the CHECK is what binds a writer who never read the service.
3. **Append-only (hard rule 4).** A withdrawal is a new row, the grant it supersedes
   survives, the read takes the latest, and UPDATE/DELETE are refused by the trigger.
4. **The expiry is STRUCTURAL, not clocked.** This ledger deliberately carries no
   validity window (unlike `consent_ledger`), so the tests that would have proved
   staleness instead prove the three things that replace it: a different person, a
   different number, and a deactivated owner each read as no opt-in.
5. **The gate actually turns.** `resolve_destination` refuses without a live grant and
   resolves with one, and `notify_hot_lead_whatsapp` records `recipient_not_opted_in`
   in the first case — through the production read, with nothing patched.
6. **The surface.** Only the owner may record; a staff member may not; an impersonating
   admin may not; no phone number is accepted or returned anywhere.
7. **Hard rule 6.** No number reaches a log line.

CONCURRENCY: every test builds its own run-unique tenant and asserts only on rows it
created, so this file runs beside the other suites on the shared Postgres.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, get_args
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.compliance import whatsapp_optin, whatsapp_optin_routes
from apps.api.compliance.models import (
    ALERT_OPTIN_CHANNELS,
    ALERT_OPTIN_OPERATOR,
    ALERT_OPTIN_SELF_SERVE,
    ALERT_OPTIN_STATUSES,
)
from apps.api.compliance.whatsapp_optin_routes import AlertOptInStatus
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.logging import JsonFormatter
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from apps.workers import whatsapp
from fastapi import Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

# A documented test-range number, so the "no number anywhere" assertions have something
# to search FOR.
OWNER_E164 = "+919000000055"
OTHER_E164 = "+919000000056"

ENDPOINT = "/v1/compliance/whatsapp-alerts"

EVIDENCE = {"onboarding_pack": "ONB-2026-0042", "agreed_on": "2026-08-01"}


@pytest.fixture(autouse=True)
def _channel_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """The alert channel switched on, so a refusal in this file is never the flag.

    `whatsapp_enabled` defaults False and `notify_hot_lead_whatsapp` returns `disabled`
    before it reaches the opt-in gate — which would make every assertion below pass for
    the wrong reason.
    """
    monkeypatch.setattr(whatsapp, "get_settings", _settings_with(whatsapp_enabled=True))


def _settings_with(**overrides: Any) -> Any:
    from apps.api.core.settings import get_settings as real

    def _get() -> Any:
        settings = real()
        return settings.model_copy(update=overrides)

    return _get


async def _tenant(prefix: str, *, role: str = "owner", phone: str | None = OWNER_E164) -> Any:
    """(tenant_id, slug, dev bearer token, user_id) for a fresh org with one member."""
    created = await admin_service.create_organization(
        name="Alert Motors",
        slug=f"wa-{prefix}-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, slug = UUID(str(created["id"])), str(created["slug"])
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, phone, created_at, updated_at) "
                "VALUES (:id, :email, :phone, now(), now())"
            ),
            {"id": user_id, "email": f"{user_id}@example.com", "phone": phone},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, :role, now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id, "role": role},
        )
    return tenant_id, slug, f"dev:client:{user_id}", user_id


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _headers(token: str, slug: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}


def _code(response: Any) -> str:
    """RFC-9457 has no `code` key: the machine identifier is the last segment of `type`."""
    return str(response.json()["type"]).rsplit("/", 1)[-1]


async def _grant(
    tenant_id: UUID, user_id: UUID, *, phone: str = OWNER_E164
) -> whatsapp_optin.AlertOptIn:
    """A self-serve grant, written the way the client-facing surface writes one."""
    async with tenant_session(tenant_id) as session:
        return await whatsapp_optin.record_alert_optin(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            phone_e164=phone,
            status="granted",
            channel="self_serve_console",
            recorded_by_user_id=user_id,
        )


async def _rows(tenant_id: UUID) -> list[tuple[Any, ...]]:
    async with tenant_session(tenant_id) as session:
        return [
            tuple(row)
            for row in (
                await session.execute(
                    text(
                        "SELECT status, channel, notice_version, captured_at "
                        "FROM whatsapp_alert_optin_ledger WHERE tenant_id = :t "
                        "ORDER BY captured_at, created_at"
                    ),
                    {"t": tenant_id},
                )
            ).all()
        ]


# --------------------------------------------------------------------------------
# 1. Tenancy (hard rule 1)


async def test_another_tenant_can_neither_read_nor_write_an_alert_optin_row() -> None:
    """A new tenant table ships with its FORCEd policy in the same migration, and this
    is what says so out loud rather than assuming it.

    Both directions: tenant B reads zero rows for the same number, and a write B
    attributes to A is refused by the policy's WITH CHECK rather than silently accepted.
    An opt-in is one named person's agreement to be messaged by us about ONE business;
    another tenant's row can never spend it.
    """
    alice, _, _, alice_user = await _tenant("rls-a")
    bob, _, _, bob_user = await _tenant("rls-b")
    await _grant(alice, alice_user)

    async with tenant_session(bob) as session:
        leaked = (
            await session.execute(
                text("SELECT count(*) FROM whatsapp_alert_optin_ledger WHERE phone_e164 = :p"),
                {"p": OWNER_E164},
            )
        ).scalar()
        assert leaked == 0, "another tenant's opt-in row must not be visible"
        state = await whatsapp_optin.read_alert_optin(
            session, tenant_id=bob, user_id=alice_user, phone_e164=OWNER_E164
        )
    assert state.status == "none" and state.messageable is False

    async with tenant_session(bob) as session:
        with pytest.raises(Exception):  # noqa: B017 — psycopg raises the RLS violation
            await session.execute(
                text(
                    "INSERT INTO whatsapp_alert_optin_ledger (id, tenant_id, user_id, "
                    "phone_e164, status, channel, notice_version, captured_at, "
                    "recorded_by_user_id, created_at) VALUES (:id, :t, :u, :p, 'granted', "
                    "'self_serve_console', 'whatsapp-alerts-v1', now(), :u, now())"
                ),
                {"id": uuid7(), "t": alice, "u": alice_user, "p": OWNER_E164},
            )

    assert len(await _rows(alice)) == 1, "alice's own row is untouched"
    assert bob_user is not None


# --------------------------------------------------------------------------------
# 2. Never assumed — enforced by the DATABASE, not only by the service


async def test_the_database_refuses_a_grant_that_cannot_evidence_itself() -> None:
    """Four ways to write an unevidenced opt-in, all refused by CHECK constraints.

    Asserted at the database rather than through the service on purpose: the service's
    raises are the interface (a 422 a caller can act on), the CHECKs are the guarantee,
    and only the second one binds a writer who never read `whatsapp_optin.py`.
    """
    tenant_id, _, _, user_id = await _tenant("checks")
    admin_id = uuid.uuid4()

    async def _insert(**columns: Any) -> None:
        row: dict[str, Any] = {
            "id": uuid7(),
            "t": tenant_id,
            "u": user_id,
            "p": OWNER_E164,
            "status": "granted",
            "channel": "self_serve_console",
            "notice": whatsapp_optin.ALERT_NOTICE_VERSION,
            "by_user": user_id,
            "by_admin": None,
            "evidence": None,
        }
        row.update(columns)
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "INSERT INTO whatsapp_alert_optin_ledger (id, tenant_id, user_id, "
                    "phone_e164, status, channel, notice_version, captured_at, "
                    "recorded_by_user_id, recorded_by_admin_id, evidence, created_at) "
                    "VALUES (:id, :t, :u, :p, :status, :channel, :notice, now(), "
                    ":by_user, :by_admin, CAST(:evidence AS jsonb), now())"
                ),
                row,
            )

    # (a) a grant with no wording behind it — "informed" (DPDP §6) made checkable.
    with pytest.raises(IntegrityError):
        await _insert(notice=None)

    # (b) a self-serve grant recorded by SOMEBODY ELSE. This is the asymmetry that
    # matters: an operator quietly writing a "the client ticked the box" row is
    # unrepresentable, not merely discouraged.
    with pytest.raises(IntegrityError):
        await _insert(by_user=uuid.uuid4())

    # (c) an operator grant with no document reference.
    with pytest.raises(IntegrityError):
        await _insert(channel="operator_recorded", by_user=None, by_admin=admin_id)

    # (d) a row that names no recorder at all — an anonymous consent record.
    with pytest.raises(IntegrityError):
        await _insert(by_user=None)

    assert await _rows(tenant_id) == [], "no unevidenced grant survived"


async def test_a_withdrawal_needs_no_evidence_at_all() -> None:
    """Consent must be evidenced; a refusal must never be obstructed (DPDP §6(6)).

    The same asymmetry `consent_ledger` encodes, and the reason `notice_version` is
    nullable: a person taking permission back is not asked to produce paperwork for it.
    """
    tenant_id, _, _, user_id = await _tenant("withdraw-free")
    async with tenant_session(tenant_id) as session:
        state = await whatsapp_optin.record_alert_optin(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            phone_e164=OWNER_E164,
            status="withdrawn",
            channel="self_serve_console",
            recorded_by_user_id=user_id,
        )
    assert state.messageable is False
    assert (await _rows(tenant_id))[0][2] is None, "a withdrawal records no notice version"


async def test_the_service_refuses_an_operator_grant_with_no_document() -> None:
    """The interface half of the same rule: a 422 naming what is missing, not an
    IntegrityError nobody can read."""
    tenant_id, _, _, user_id = await _tenant("op-evidence")
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as refused:
            await whatsapp_optin.record_alert_optin(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                phone_e164=OWNER_E164,
                status="granted",
                channel="operator_recorded",
                recorded_by_admin_id=uuid.uuid4(),
            )
    assert refused.value.code == "alert_optin_operator_grant_needs_evidence"


async def test_the_status_and_channel_literals_cannot_drift_from_the_tuples() -> None:
    """The route spells its union as a `Literal` so the generated TypeScript can switch
    on it; `compliance/models.py` is still the source of truth. Two spellings of one
    vocabulary is where the drift starts."""
    assert set(get_args(AlertOptInStatus)) == set(ALERT_OPTIN_STATUSES)
    assert set(ALERT_OPTIN_CHANNELS) == {"self_serve_console", "operator_recorded"}


# --------------------------------------------------------------------------------
# 3. Append-only (hard rule 4)


async def test_a_withdrawal_is_a_new_row_and_the_grant_survives() -> None:
    """Latest row wins, and the superseded grant stays readable.

    That is the whole reason this is a ledger and not three columns on `organizations`:
    "were we allowed to send that alert in March?" is a question asked in April, and a
    state column answers it by having been overwritten.
    """
    tenant_id, _, _, user_id = await _tenant("supersede")
    await _grant(tenant_id, user_id)
    async with tenant_session(tenant_id) as session:
        await whatsapp_optin.record_alert_optin(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            phone_e164=OWNER_E164,
            status="withdrawn",
            channel="self_serve_console",
            recorded_by_user_id=user_id,
        )

    rows = await _rows(tenant_id)
    assert [row[0] for row in rows] == ["granted", "withdrawn"], "both statements survive"

    async with tenant_session(tenant_id) as session:
        state = await whatsapp_optin.read_alert_optin(
            session, tenant_id=tenant_id, user_id=user_id, phone_e164=OWNER_E164
        )
    assert state.status == "withdrawn" and state.messageable is False

    # ...and a later re-grant supersedes the withdrawal, so this is not a one-way door.
    await _grant(tenant_id, user_id)
    async with tenant_session(tenant_id) as session:
        again = await whatsapp_optin.read_alert_optin(
            session, tenant_id=tenant_id, user_id=user_id, phone_e164=OWNER_E164
        )
    assert again.messageable is True


async def test_the_ledger_refuses_update_and_delete() -> None:
    """Hard rule 4 at the database. The trigger is the guarantee; a code review is not."""
    tenant_id, _, _, user_id = await _tenant("immutable")
    await _grant(tenant_id, user_id)

    for statement in (
        "UPDATE whatsapp_alert_optin_ledger SET status = 'withdrawn' WHERE tenant_id = :t",
        "DELETE FROM whatsapp_alert_optin_ledger WHERE tenant_id = :t",
    ):
        async with tenant_session(tenant_id) as session:
            with pytest.raises(Exception):  # noqa: B017 — the trigger raises
                await session.execute(text(statement), {"t": tenant_id})

    assert len(await _rows(tenant_id)) == 1


# --------------------------------------------------------------------------------
# 4. The expiry is STRUCTURAL, not clocked


async def test_an_opt_in_does_not_carry_to_another_number_or_another_person() -> None:
    """The two legs that replace `consent_ledger`'s validity window.

    This ledger has no expiry column on purpose (see the migration): a clock would
    switch a client's hot-lead alerts off on a day nobody is watching. What stands in
    for it is that the row names the PERSON and the NUMBER, and the read is asked about
    a specific pair — so an owner handover and a changed number both fail closed on a
    fact observed at send time.
    """
    tenant_id, _, _, user_id = await _tenant("keys")
    await _grant(tenant_id, user_id)

    async with tenant_session(tenant_id) as session:
        # Same person, number changed on their profile: no opt-in for the new number.
        moved = await whatsapp_optin.read_alert_optin(
            session, tenant_id=tenant_id, user_id=user_id, phone_e164=OTHER_E164
        )
        # Same number, different person (an owner handover): not the new owner's consent.
        handover = await whatsapp_optin.read_alert_optin(
            session, tenant_id=tenant_id, user_id=uuid.uuid4(), phone_e164=OWNER_E164
        )
    assert moved.status == "none" and moved.messageable is False
    assert handover.status == "none" and handover.messageable is False


async def test_an_old_grant_is_still_a_grant() -> None:
    """The deliberate DIFFERENCE from `consent_ledger`, pinned so nobody "fixes" it.

    A year-old messaging consent is stale by `MESSAGING_CONSENT_VALIDITY_DAYS`. A
    year-old ALERT opt-in is not, because the relationship it rests on is checked
    structurally on every send rather than assumed to have decayed. If someone adds a
    validity window here, this test fails and they have to argue with the migration.
    """
    tenant_id, _, _, user_id = await _tenant("no-expiry")
    await _grant(tenant_id, user_id)
    async with tenant_session(tenant_id) as session:
        # Backdating is not an UPDATE — the trigger forbids that. A second, older row
        # cannot supersede a newer one either, so the grant is aged by inserting it as
        # the ONLY row with an ancient `captured_at`.
        await session.execute(
            text("DELETE FROM whatsapp_alert_optin_ledger WHERE 1 = 0"),
        )
    async with untenanted_session() as session:
        # Written through the owner role (no RLS GUC needed for a global session) with
        # the trigger disabled is NOT an option — so this test instead builds a fresh
        # tenant whose only row is inserted directly with an old timestamp.
        pass

    aged, _, _, aged_user = await _tenant("aged")
    long_ago = datetime.now(UTC) - timedelta(days=900)
    async with tenant_session(aged) as session:
        await session.execute(
            text(
                "INSERT INTO whatsapp_alert_optin_ledger (id, tenant_id, user_id, phone_e164, "
                "status, channel, notice_version, captured_at, recorded_by_user_id, created_at) "
                "VALUES (:id, :t, :u, :p, 'granted', 'self_serve_console', :notice, :when, "
                ":u, :when)"
            ),
            {
                "id": uuid7(),
                "t": aged,
                "u": aged_user,
                "p": OWNER_E164,
                "notice": whatsapp_optin.ALERT_NOTICE_VERSION,
                "when": long_ago,
            },
        )
        state = await whatsapp_optin.read_alert_optin(
            session, tenant_id=aged, user_id=aged_user, phone_e164=OWNER_E164
        )
    assert state.messageable is True, "this ledger has no clock — see the migration"


# --------------------------------------------------------------------------------
# 5. The gate actually turns


async def test_resolve_destination_refuses_without_a_grant_and_resolves_with_one() -> None:
    """The one function `notify_hot_lead_whatsapp` asks, through the production read.

    Nothing is patched: the "before" is the real absence of a row, and the "after" is a
    row written by the same service the settings screen calls.
    """
    tenant_id, _, _, user_id = await _tenant("resolve")

    async with tenant_session(tenant_id) as session:
        before = await whatsapp.resolve_destination(session, tenant_id)
    assert before is not None and before.to_e164 == OWNER_E164
    assert before.opt_in_at is None, "no row means no opt-in, which is a refusal"

    granted = await _grant(tenant_id, user_id)
    async with tenant_session(tenant_id) as session:
        after = await whatsapp.resolve_destination(session, tenant_id)
    assert after is not None and after.opt_in_at is not None
    assert after.opt_in_at == granted.captured_at

    # ...and a withdrawal closes it again.
    async with tenant_session(tenant_id) as session:
        await whatsapp_optin.record_alert_optin(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            phone_e164=OWNER_E164,
            status="withdrawn",
            channel="self_serve_console",
            recorded_by_user_id=user_id,
        )
        withdrawn = await whatsapp.resolve_destination(session, tenant_id)
    assert withdrawn is not None and withdrawn.opt_in_at is None


async def test_a_deactivated_owner_has_no_destination_at_all() -> None:
    """The third structural leg. A removed owner must not keep receiving the business's
    leads, and their standing opt-in must not keep it alive."""
    tenant_id, _, _, user_id = await _tenant("deactivated")
    await _grant(tenant_id, user_id)
    async with untenanted_session() as session:
        await session.execute(
            text("UPDATE users SET deactivated_at = now() WHERE id = :u"), {"u": user_id}
        )
    async with tenant_session(tenant_id) as session:
        assert await whatsapp.resolve_destination(session, tenant_id) is None


async def test_the_hot_lead_job_refuses_by_name_when_nobody_opted_in() -> None:
    """The refusal is recorded on the lead timeline with OUR reason code, so "we never
    told you" is answerable from the timeline — including when the answer is "you are
    right, and here is why"."""
    tenant_id, _, _, _ = await _tenant("job-refusal")
    lead_id, call_id = uuid7(), uuid7()
    await _seed_lead(tenant_id, lead_id)

    outcome = await whatsapp.notify_hot_lead_whatsapp(
        {"job_try": 1},
        {
            "tenant_id": str(tenant_id),
            "lead_id": str(lead_id),
            "call_id": str(call_id),
            "triggers": ["budget"],
        },
    )
    assert outcome == "rejected recipient_not_opted_in"

    async with tenant_session(tenant_id) as session:
        payload = (
            await session.execute(
                text(
                    "SELECT payload FROM lead_events WHERE lead_id = :l AND type = 'notification'"
                ),
                {"l": lead_id},
            )
        ).scalar_one()
    assert payload["reason"] == "recipient_not_opted_in"
    assert payload["delivered"] is False
    assert OWNER_E164 not in str(payload), "hard rule 6: no number in the timeline payload"


async def _seed_lead(tenant_id: UUID, lead_id: UUID) -> None:
    async with tenant_session(tenant_id) as session:
        agent_id = uuid7()
        await session.execute(
            text(
                "INSERT INTO agents (id, tenant_id, name, direction, language_primary, "
                "disclosure_line, ai_disclosure_line, recording_notice_line, "
                "caller_memory_notice_line, status, created_at, updated_at) VALUES (:id, :t, "
                "'Alerts', 'inbound', 'te-IN', 'This is an AI assistant.', 'This is an AI "
                "assistant.', 'This call is being recorded.', 'I keep a short note of what you "
                "ask about.', 'draft', now(), now())"
            ),
            {"id": agent_id, "t": tenant_id},
        )
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, source, status, "
                "created_at, updated_at) "
                "VALUES (:id, :t, :a, :p, 'inbound_call', 'hot', now(), now())"
            ),
            {"id": lead_id, "t": tenant_id, "a": agent_id, "p": OTHER_E164},
        )


# --------------------------------------------------------------------------------
# 6. The surface


async def test_only_the_owner_can_record_their_own_opt_in() -> None:
    """`org:manage`, which only the `owner` role holds. A staff member cannot opt the
    business's owner in — the subject of an opt-in is the only person who can give it."""
    _, slug, staff_token, _ = await _tenant("staff", role="staff")
    async with _client() as client:
        response = await client.post(
            ENDPOINT,
            json={"status": "granted", "notice_version": whatsapp_optin.ALERT_NOTICE_VERSION},
            headers=_headers(staff_token, slug),
        )
    assert response.status_code == 403


async def test_the_owner_records_and_reads_back_without_a_number_anywhere() -> None:
    """The happy path, and the hard-rule-6 property that shapes both routes: no phone
    number is accepted, and none is echoed back."""
    _, slug, token, _ = await _tenant("surface")
    async with _client() as client:
        created = await client.post(
            ENDPOINT,
            json={"status": "granted", "notice_version": whatsapp_optin.ALERT_NOTICE_VERSION},
            headers=_headers(token, slug),
        )
        read_back = await client.get(ENDPOINT, headers=_headers(token, slug))

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "granted" and body["messageable"] is True
    assert body["current_notice_version"] == whatsapp_optin.ALERT_NOTICE_VERSION
    assert body["current_notice_text"] == whatsapp_optin.ALERT_NOTICE_TEXT
    assert OWNER_E164 not in created.text, "the response must never carry the number"

    assert read_back.status_code == 200
    assert read_back.json()["messageable"] is True
    assert OWNER_E164 not in read_back.text


async def test_a_stale_notice_version_is_refused_rather_than_recorded() -> None:
    """A client running a cached build agrees to wording we are no longer showing. The
    row would evidence something that did not happen, which is worse than no row."""
    _, slug, token, _ = await _tenant("stale-notice")
    async with _client() as client:
        response = await client.post(
            ENDPOINT,
            json={"status": "granted", "notice_version": "whatsapp-alerts-v0"},
            headers=_headers(token, slug),
        )
    assert response.status_code == 422
    assert _code(response) == "alert_optin_notice_out_of_date"


async def test_an_owner_with_no_number_is_told_rather_than_500ing() -> None:
    """Errors are part of the interface: a person with no mobile on their profile gets a
    sentence they can act on, not a NOT NULL violation."""
    _, slug, token, _ = await _tenant("no-phone", phone=None)
    async with _client() as client:
        response = await client.post(
            ENDPOINT,
            json={"status": "granted", "notice_version": whatsapp_optin.ALERT_NOTICE_VERSION},
            headers=_headers(token, slug),
        )
    assert response.status_code == 422
    assert _code(response) == "alert_optin_needs_a_number"


async def test_the_surface_reports_whether_this_deployment_can_deliver_at_all() -> None:
    """A screen that offers an opt-in for a channel nothing can send on is the "looks
    finished" failure this whole seam exists to avoid. The reason is a code that names
    which thing is missing, not a bare "unavailable"."""
    _, slug, token, _ = await _tenant("capability")
    async with _client() as client:
        response = await client.get(ENDPOINT, headers=_headers(token, slug))
    body = response.json()
    # The test environment names no provider and is not `local`, or names the dev sink
    # under `local`; either way the field is present and the two agree.
    assert isinstance(body["delivery_available"], bool)
    if not body["delivery_available"]:
        assert body["delivery_unavailable_reason"], "an unavailable channel must say why"


# --------------------------------------------------------------------------------
# 7. Hard rule 6


async def test_no_number_reaches_a_log_line(caplog: pytest.LogCaptureFixture) -> None:
    """The service logs the tenant, the status and the channel. Never the number, not
    masked and not fingerprinted."""
    tenant_id, _, _, user_id = await _tenant("logs")
    formatter = JsonFormatter()
    with caplog.at_level(logging.INFO):
        await _grant(tenant_id, user_id)
    rendered = "\n".join(formatter.format(record) for record in caplog.records)
    assert OWNER_E164 not in rendered
    assert OWNER_E164.lstrip("+") not in rendered
    assert "whatsapp_alert_optin_recorded" in rendered


# --------------------------------------------------------------------------------
# 8. Every refusal the writer makes, as a code a caller can act on
#
# The happy path above is what a demo exercises. These are the branches that decide
# whether an unevidenced, misattributed or ownerless row can enter an append-only
# consent ledger — and a row in that ledger is the whole of what we could produce if
# Meta or a Data Principal challenged a message we sent.


async def _make_admin(role: str = "operator") -> str:
    """A dev bearer token for an admin-realm operator, the way ops signs in."""
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', :role, now(), now())"
            ),
            {"id": admin_id, "role": role},
        )
    return f"dev:admin:{admin_id}"


async def _record(tenant_id: UUID, **overrides: Any) -> whatsapp_optin.AlertOptIn:
    """`record_alert_optin` with a valid self-serve grant as the baseline, so each test
    below changes exactly ONE thing and the refusal it gets names that one thing."""
    user_id = overrides.pop("user_id", uuid7())
    kwargs: dict[str, Any] = {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "phone_e164": OWNER_E164,
        "status": "granted",
        "channel": ALERT_OPTIN_SELF_SERVE,
        "recorded_by_user_id": user_id,
    }
    kwargs.update(overrides)
    async with tenant_session(tenant_id) as session:
        return await whatsapp_optin.record_alert_optin(session, **kwargs)


async def test_a_status_nobody_can_say_is_refused_by_name_and_lists_the_ones_that_exist() -> None:
    """A status outside `("granted", "withdrawn")` must be refused with a code and a
    remediation, not written and not turned into an IntegrityError.

    The ledger has no `declined` and no `pending`: absence IS the "never asked" state.
    A caller that invents one is a bug, and a 500 from a CHECK tells whoever hit it
    nothing about which value to send instead.
    """
    tenant_id, _, _, _ = await _tenant("bad-status")
    with pytest.raises(ProblemError) as caught:
        await _record(tenant_id, status="declined")

    assert caught.value.code == "alert_optin_unknown_status"
    assert caught.value.status == 422
    # The remediation has to name the admissible values, or the caller guesses again.
    assert "granted" in str(caught.value.remediation)
    assert "withdrawn" in str(caught.value.remediation)
    assert await _rows(tenant_id) == [], "a refused status must leave no row behind"


async def test_a_channel_nobody_captured_it_on_is_refused_rather_than_recorded() -> None:
    """`channel` is one of the three things Meta expects a business to produce when a
    number is challenged (the source). A row whose channel is a string nobody defined
    evidences nothing, so the writer refuses it by name before the CHECK does.
    """
    tenant_id, _, _, _ = await _tenant("bad-channel")
    with pytest.raises(ProblemError) as caught:
        await _record(tenant_id, channel="sms_reply")

    assert caught.value.code == "alert_optin_unknown_channel"
    assert caught.value.status == 422
    assert "self_serve_console" in str(caught.value.remediation)
    assert await _rows(tenant_id) == []


async def test_an_opt_in_with_no_number_behind_it_is_refused_before_it_is_written() -> None:
    """An opt-in is permission to message A NUMBER. With no number there is nothing the
    permission attaches to, so the row would look like protection and grant nothing.

    Reachable for real: an owner whose Clerk profile carries no mobile. The person gets
    a sentence they can act on rather than a NOT NULL violation nobody can read.
    """
    tenant_id, _, _, _ = await _tenant("service-no-phone", phone=None)
    with pytest.raises(ProblemError) as caught:
        await _record(tenant_id, phone_e164="")

    assert caught.value.code == "alert_optin_needs_a_number"
    assert caught.value.status == 422
    assert "number" in caught.value.detail.lower()
    assert await _rows(tenant_id) == []


@pytest.mark.parametrize(
    ("recorders", "why"),
    [
        ({"recorded_by_user_id": None, "recorded_by_admin_id": None}, "nobody"),
        ({"recorded_by_admin_id": uuid7()}, "both a client user and an operator"),
    ],
    ids=["neither", "both"],
)
async def test_a_row_that_names_no_single_recorder_is_refused(
    recorders: dict[str, Any], why: str
) -> None:
    """Exactly one recorder, always. A consent row whose author is unknown — or is two
    people at once — cannot answer "who took this down and on whose authority", which
    is the question an audit of a challenged message opens with.

    The database CHECK (`ck_..._names_one_recorder`) says the same thing to a writer who
    never came through this function; this refusal is the half a caller can act on.
    """
    tenant_id, _, _, user_id = await _tenant(f"recorder-{len(recorders)}")
    with pytest.raises(ProblemError) as caught:
        await _record(tenant_id, user_id=user_id, status="withdrawn", **recorders)

    assert caught.value.code == "alert_optin_needs_one_recorder", why
    assert caught.value.status == 422
    assert await _rows(tenant_id) == []


async def test_a_self_serve_grant_recorded_by_anyone_but_its_subject_is_refused() -> None:
    """A `self_serve_console` grant claims "the account holder authenticated and ticked
    the box". Recorded by a different user it claims that about somebody who did not,
    which is precisely the "assumed opt-in" Meta's policy forbids and DPDP §6 calls
    neither free nor unambiguous.

    The remediation has to offer the legitimate route (record it as an operator, with
    the document), or the person who hit this wall has nowhere to go.
    """
    tenant_id, _, _, subject_id = await _tenant("self-serve-third-party")
    with pytest.raises(ProblemError) as caught:
        await _record(tenant_id, user_id=subject_id, recorded_by_user_id=uuid7())

    assert caught.value.code == "alert_optin_self_serve_is_first_person"
    assert caught.value.status == 422
    assert "operator" in str(caught.value.remediation)
    assert await _rows(tenant_id) == []


async def test_an_operator_grant_that_names_no_operator_is_refused() -> None:
    """An operator's grant is a claim ABOUT SOMEBODY ELSE, so it is only worth anything
    if it says who made the claim. Unattributed, it is indistinguishable from a row
    somebody added to make an alert start working.
    """
    tenant_id, _, _, subject_id = await _tenant("operator-anon")
    with pytest.raises(ProblemError) as caught:
        await _record(
            tenant_id,
            user_id=subject_id,
            channel=ALERT_OPTIN_OPERATOR,
            recorded_by_user_id=subject_id,
            recorded_by_admin_id=None,
            evidence=EVIDENCE,
        )

    assert caught.value.code == "alert_optin_operator_grant_needs_operator"
    assert caught.value.status == 422
    assert await _rows(tenant_id) == []


# --------------------------------------------------------------------------------
# 9. The operator surface: onboarding opt-ins reach the person the worker sends to


ADMIN_ENDPOINT = "/v1/admin/tenants/{tenant_id}/whatsapp-alerts"


async def test_an_operator_records_the_owners_opt_in_against_the_owner_not_themselves() -> None:
    """The row an operator writes must name the CLIENT'S OWNER as its subject and the
    operator as its recorder — never the operator as both.

    If the subject were the operator, `resolve_destination` (which asks about the owner)
    would still find no opt-in, and the alert would stay silently refused while the
    console showed a green tick. If the recorder were the owner, the row would claim a
    self-serve act that never happened.
    """
    tenant_id, _, _, owner_id = await _tenant("operator-records")
    admin_token = await _make_admin()

    async with _client() as client:
        response = await client.post(
            ADMIN_ENDPOINT.format(tenant_id=tenant_id),
            json={"status": "granted", "evidence": EVIDENCE},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert response.status_code == 201, response.text
    assert response.json()["messageable"] is True
    assert OWNER_E164 not in response.text, "the operator surface must not echo the number"

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT user_id, phone_e164, channel, recorded_by_admin_id, "
                    "recorded_by_user_id, evidence FROM whatsapp_alert_optin_ledger "
                    "WHERE tenant_id = :t"
                ),
                {"t": tenant_id},
            )
        ).all()
    assert len(row) == 1, row
    subject, phone, channel, by_admin, by_user, evidence = row[0]
    assert UUID(str(subject)) == owner_id, "the subject is the owner, not the operator"
    assert str(phone) == OWNER_E164, "recorded against the number the alert is sent to"
    assert str(channel) == ALERT_OPTIN_OPERATOR
    assert by_admin is not None and by_user is None, "one recorder, and it is the operator"
    assert evidence == EVIDENCE, "the document the client agreed in is what makes it evidence"


async def test_an_operator_cannot_record_an_opt_in_for_an_account_with_no_reachable_owner() -> None:
    """No active owner with a mobile number means there is nobody to have agreed.

    Defaulting to "some member" here would file one human's consent against another
    human's phone — the exact drift between the consent key and the delivery key that
    makes a consent record worse than none. The refusal names the missing thing so an
    operator knows to fix the profile rather than retry.
    """
    tenant_id, _, _, _ = await _tenant("no-owner-number", phone=None)
    admin_token = await _make_admin()

    async with _client() as client:
        response = await client.post(
            ADMIN_ENDPOINT.format(tenant_id=tenant_id),
            json={"status": "granted", "evidence": EVIDENCE},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert response.status_code == 422, response.text
    assert _code(response) == "alert_optin_no_owner_with_a_number"
    assert await _rows(tenant_id) == [], "a refused operator grant leaves no row"


# --------------------------------------------------------------------------------
# 10. A session with no person in it


async def test_a_session_with_no_user_of_its_own_reads_no_subject_state() -> None:
    """An admin viewing a client dashboard has no `users` row, so there is no subject
    whose opt-in could be read.

    Both other answers are wrong and one of them is a breach: reporting `none` asserts
    something about a person who does not exist in this session, and reporting the
    OWNER's state hands one human's consent record to another. The route must report
    the channel's readiness and no subject state.
    """
    tenant_id, _, _, owner_id = await _tenant("no-subject")
    await _grant(tenant_id, owner_id)  # the owner HAS opted in — it must not leak.

    viewer = Principal(
        realm="admin",
        user_id=None,
        tenant_id=tenant_id,
        role="operator",
        impersonating=True,
    )
    async with tenant_session(tenant_id) as session:
        answer = await whatsapp_optin_routes.read(session, viewer)

    assert answer.status == "none", "no subject in this session, so no subject state"
    assert answer.messageable is False
    assert answer.channel is None and answer.captured_at is None
    # The part that is still true and still useful: what the deployment can deliver.
    assert answer.current_notice_version == whatsapp_optin.ALERT_NOTICE_VERSION


async def test_an_opt_in_that_cannot_name_the_person_giving_it_is_forbidden() -> None:
    """A subject-less principal reaching the write path is refused, not written.

    `requires(..., realm="client")` resolves a membership, so this should be
    unreachable over HTTP — which is exactly why it is asserted here instead. The type
    still says `UUID | None`, and a row in this ledger attributed to nobody is the one
    thing it must never contain: it would evidence an agreement with no human on the
    other end of it.
    """
    tenant_id, _, _, _ = await _tenant("no-recorder")
    nobody = Principal(
        realm="client",
        user_id=None,
        tenant_id=tenant_id,
        role="owner",
    )
    payload = whatsapp_optin_routes.RecordAlertOptInIn(
        status="granted", notice_version=whatsapp_optin.ALERT_NOTICE_VERSION
    )
    request = Request({"type": "http", "headers": [], "client": None})

    with pytest.raises(ProblemError) as caught:
        async with tenant_session(tenant_id) as session:
            await whatsapp_optin_routes.record(payload, session, request, nobody)

    assert caught.value.status == 403
    assert "person giving it" in caught.value.detail
    assert await _rows(tenant_id) == []


# --------------------------------------------------------------------------------
# 11. The operator's READ — what makes the operator's write safe to offer


async def test_an_operator_reads_the_owners_state_before_recording_one() -> None:
    """The read that stops `record_for_client` being a write-only control.

    An operator holding a month-old onboarding form must be able to see that the owner
    withdrew last week. Without this route the console could only write and then look at
    what came back, which is the one order in which the mistake is unrecoverable: the
    ledger is append-only, so the correction is another row, and the alerts resumed in
    between.
    """
    tenant_id, _, _, owner_id = await _tenant("admin-reads")
    admin_token = await _make_admin()

    async with _client() as client:
        before = await client.get(
            ADMIN_ENDPOINT.format(tenant_id=tenant_id),
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert before.status_code == 200, before.text
        # The default of the world: nobody has asked this owner anything.
        assert before.json()["status"] == "none"
        assert before.json()["messageable"] is False

        await _grant(tenant_id, owner_id)

        after = await client.get(
            ADMIN_ENDPOINT.format(tenant_id=tenant_id),
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert after.status_code == 200, after.text
    body = after.json()
    # The OWNER's own self-serve grant, seen from the admin realm — the operator must not
    # have to write a row to find out one already exists.
    assert body["status"] == "granted"
    assert body["channel"] == ALERT_OPTIN_SELF_SERVE
    assert body["messageable"] is True
    # Hard rule 6: the subject is resolved server-side and the number never comes back.
    assert OWNER_E164 not in after.text


async def test_the_operator_read_refuses_an_account_with_no_reachable_owner() -> None:
    """The SAME refusal the write gives, by name.

    Answering `none` here would be a different sentence — "this person has never been
    asked" — about an account where there is no person to ask, and it would offer the
    operator a control whose only outcome is the 422 the write raises for exactly this
    reason. One subject, resolved one way, and both verbs refuse together.
    """
    tenant_id, _, _, _ = await _tenant("admin-reads-no-owner", phone=None)
    admin_token = await _make_admin()

    async with _client() as client:
        response = await client.get(
            ADMIN_ENDPOINT.format(tenant_id=tenant_id),
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert response.status_code == 422, response.text
    assert _code(response) == "alert_optin_no_owner_with_a_number"


async def test_the_operator_read_is_refused_to_a_client_session() -> None:
    """`admin:tenants`, realm admin. A client token is not a support session, and one
    owner reading another tenant's consent state through this path would be a breach of
    the boundary the two routers exist to keep."""
    tenant_id, slug, token, _ = await _tenant("admin-read-realm")

    async with _client() as client:
        response = await client.get(
            ADMIN_ENDPOINT.format(tenant_id=tenant_id), headers=_headers(token, slug)
        )

    assert response.status_code in (401, 403), response.text


async def test_the_operator_read_is_not_gated_on_the_permission_to_write() -> None:
    """The READ declares a non-mutating permission and the WRITE does not — read off the
    route table, so a flip back fails here as well as in the global sweep.

    D-22 hides every route declaring a `MUTATING_PERMISSIONS` member from a read-only
    "view as client" session, and this route first shipped with `admin:tenants` on both
    verbs. That made the one question support is asked about this feature — "why am I not
    getting WhatsApp alerts?" — unanswerable from inside the session support is in, since
    the client-realm read deliberately reports no subject state there either.
    `tests/impersonation_reads_test.py` asserts the RULE over the whole table; this
    asserts the SPLIT on this pair, where the argument for it lives.
    """
    from apps.api.core.rbac import MUTATING_PERMISSIONS, iter_api_routes

    declared = {
        (route.path, frozenset(route.methods)): (route.openapi_extra or {}).get(
            "x-calevate-permission"
        )
        for route in iter_api_routes(app)
        if route.path == ADMIN_ENDPOINT.replace("{tenant_id}", "{tenant_id}")
    }
    read = next(p for (_, methods), p in declared.items() if "GET" in methods)
    write = next(p for (_, methods), p in declared.items() if "POST" in methods)

    assert read == "org:read"
    assert read not in MUTATING_PERMISSIONS, "a read hidden from view-as is the D-22 bug"
    # The write keeps the permission that names one tenant's support work, and it is
    # mutating on purpose: an impersonating admin must not manufacture a client's consent.
    assert write == "admin:tenants"
    assert write in MUTATING_PERMISSIONS
