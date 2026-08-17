"""Messaging consent — the ledger, the constraints and the capture surface.

Migration `c2f7a91b4e63` makes `consent_ledger.purpose = 'messaging'` expressible, which
is what turns `escalate_campaign_contact` from "refuses 100% of the time" into a feature.
That the escalation actually turns on is proved next door, in
`tests/campaign_escalation_test.py::test_a_recorded_opt_in_is_what_turns_the_escalation_on`;
this file pins the properties that keep the row worth trusting:

1. **Tenancy.** Another tenant reads zero rows and writes none (hard rule 1).
2. **Never assumed.** Every messaging row names a SOURCE, a grant carries evidence, a
   spoken grant names its call, and a client's own staff can record an opt-OUT but never
   an opt-IN. Asserted against the DATABASE, not just the service, because the CHECK is
   what binds a writer who never read the service.
3. **Append-only (hard rule 4).** A withdrawal is a new row; the grant it supersedes
   survives, and the read takes the latest.
4. **Consent goes stale.** A grant older than `MESSAGING_CONSENT_VALIDITY_DAYS` reads as
   not-messageable while remaining in the ledger.
5. **The surface never puts a number in a URL**, never echoes one back, and refuses with
   an RFC-9457 code a client can switch on.

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
from apps.api.compliance import consent
from apps.api.compliance.consent_routes import ConsentSource, ConsentStatus
from apps.api.compliance.models import CONSENT_SOURCES
from apps.api.core.errors import ProblemError
from apps.api.core.logging import JsonFormatter
from apps.api.core.rbac import iter_api_routes
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

# A documented test-range number, so the "no number in the response" assertions have
# something to search FOR.
SUBJECT = "+919000000077"

RECORD = "/v1/compliance/messaging-consent"
LOOKUP = "/v1/compliance/messaging-consent/lookup"

EVIDENCE = {"form": "enquiry-v1", "notice_version": "2026-01"}


async def _tenant(prefix: str, role: str = "owner") -> tuple[UUID, str, str]:
    """(tenant_id, org slug, dev bearer token) for a fresh org with one member."""
    created = await admin_service.create_organization(
        name="Consent Motors",
        slug=f"mc-{prefix}-{uuid.uuid4().hex[:8]}",
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
    return tenant_id, slug, f"dev:client:{user_id}"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _headers(token: str, slug: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}


def _code(response: Any) -> str:
    """RFC-9457 has no `code` key: the machine identifier is the last segment of
    `type` (the rule `dnc_test` states for the same reason)."""
    return str(response.json()["type"]).rsplit("/", 1)[-1]


async def _grant(tenant_id: UUID, *, phone: str = SUBJECT) -> None:
    async with tenant_session(tenant_id) as session:
        await consent.record_messaging_consent(
            session,
            tenant_id=tenant_id,
            raw_phone=phone,
            status="granted",
            source="web_form_optin",
            evidence=EVIDENCE,
        )


async def _rows(tenant_id: UUID) -> list[tuple[Any, ...]]:
    async with tenant_session(tenant_id) as session:
        return [
            tuple(row)
            for row in (
                await session.execute(
                    text(
                        "SELECT status, consent_source, captured_at FROM consent_ledger "
                        "WHERE tenant_id = :t AND purpose = 'messaging' "
                        "ORDER BY captured_at, created_at"
                    ),
                    {"t": tenant_id},
                )
            ).all()
        ]


# --------------------------------------------------------------------------------
# 1. Tenancy (hard rule 1)
# --------------------------------------------------------------------------------


async def test_another_tenant_can_neither_read_nor_write_a_messaging_consent_row() -> None:
    """The migration adds a column and an index to a table that already carries its
    FORCEd `tenant_isolation` policy — a column is not a separate security object, and
    this is what says so out loud rather than assuming it.

    Both directions: tenant B reads zero rows for the same number, and tenant B's own
    grant is invisible to tenant A. Consent is per (tenant, phone) because it is consent
    to be messaged BY A NAMED BUSINESS, which is exactly what Meta requires an opt-in to
    state — one client's opt-in cannot spend another's.
    """
    alice, _, _ = await _tenant("rls-a")
    bob, _, _ = await _tenant("rls-b")
    await _grant(alice)

    async with tenant_session(bob) as session:
        leaked = (
            await session.execute(
                text(
                    "SELECT count(*) FROM consent_ledger WHERE phone_e164 = :p "
                    "AND purpose = 'messaging'"
                ),
                {"p": SUBJECT},
            )
        ).scalar()
        assert leaked == 0, "another tenant's consent row must not be visible"
        state = await consent.read_messaging_consent(session, tenant_id=bob, phone_e164=SUBJECT)
    assert state.status == "none" and state.messageable is False

    # ...and a write attributed to somebody else's tenant is refused by the policy's
    # WITH CHECK, not silently accepted.
    async with tenant_session(bob) as session:
        with pytest.raises(Exception):  # noqa: B017 — psycopg raises the RLS violation
            await session.execute(
                text(
                    "INSERT INTO consent_ledger (id, tenant_id, phone_e164, purpose, status, "
                    "consent_source, evidence, captured_at, created_at) VALUES (:id, :t, :p, "
                    "'messaging', 'granted', 'web_form_optin', '{}'::jsonb, now(), now())"
                ),
                {"id": uuid7(), "t": alice, "p": SUBJECT},
            )

    assert len(await _rows(alice)) == 1, "alice's own row is untouched"


# --------------------------------------------------------------------------------
# 2. Never assumed — enforced by the database, not only by the service
# --------------------------------------------------------------------------------


async def _insert_messaging_row(tenant_id: UUID, **overrides: Any) -> None:
    row: dict[str, Any] = {
        "id": uuid7(),
        "t": tenant_id,
        "call": None,
        "p": SUBJECT,
        "status": "granted",
        "source": "web_form_optin",
        "evidence": '{"form": "enquiry-v1"}',
    }
    row.update(overrides)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO consent_ledger (id, tenant_id, call_id, phone_e164, purpose, "
                "status, consent_source, evidence, captured_at, created_at) VALUES (:id, :t, "
                ":call, :p, 'messaging', :status, :source, CAST(:evidence AS jsonb), now(), now())"
            ),
            row,
        )


async def test_the_purpose_exists_at_all() -> None:
    """The bug this slice fixes, stated as a test: before `c2f7a91b4e63` this INSERT
    was refused by `ck_consent_ledger_purpose_enum`, which is why every campaign
    escalation ever attempted recorded `recipient_not_opted_in`."""
    tenant_id, _, _ = await _tenant("purpose")
    await _insert_messaging_row(tenant_id)
    assert [row[0] for row in await _rows(tenant_id)] == ["granted"]


async def test_a_messaging_row_with_no_source_is_refused_by_the_database() -> None:
    """ "Captured with a SOURCE, never assumed" as a constraint. A convention would be
    a comment; this is a refusal that binds a writer who never read one."""
    tenant_id, _, _ = await _tenant("nosource")
    with pytest.raises(IntegrityError, match="messaging_names_its_source"):
        await _insert_messaging_row(tenant_id, source=None)


async def test_an_unevidenced_grant_is_refused_by_the_database() -> None:
    tenant_id, _, _ = await _tenant("noev")
    with pytest.raises(IntegrityError, match="granted_consent_carries_evidence"):
        await _insert_messaging_row(tenant_id, evidence=None)


async def test_a_spoken_grant_that_names_no_call_is_refused_by_the_database() -> None:
    """A verbal opt-in's evidence IS the call: without a `call_id` there is no recording,
    no transcript span and nothing to produce when the number is challenged."""
    tenant_id, _, _ = await _tenant("nocall")
    with pytest.raises(IntegrityError, match="granted_consent_carries_evidence"):
        await _insert_messaging_row(tenant_id, source="inbound_call_verbal", call=None)


async def test_staff_may_record_an_opt_out_but_never_an_opt_in() -> None:
    """The asymmetry that makes "implied consent" unrepresentable under another name.
    Consent must be evidenced; a refusal must never be obstructed."""
    tenant_id, _, _ = await _tenant("staff")
    with pytest.raises(IntegrityError, match="granted_consent_carries_evidence"):
        await _insert_messaging_row(tenant_id, source="staff_recorded_request")

    async with tenant_session(tenant_id) as session:
        state = await consent.record_messaging_consent(
            session,
            tenant_id=tenant_id,
            raw_phone=SUBJECT,
            status="withdrawn",
            source="staff_recorded_request",
        )
    assert state.status == "withdrawn" and state.messageable is False


async def test_an_invented_source_is_refused_by_the_database() -> None:
    """There is no `assumed`, no `implied`, no `campaign_list`. The enum is the point:
    a free-text column is a box somebody types "yes" into."""
    tenant_id, _, _ = await _tenant("invented")
    with pytest.raises(IntegrityError, match="source_enum"):
        await _insert_messaging_row(tenant_id, source="assumed")


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"source": "staff_recorded_request"}, "consent_source_cannot_grant"),
        ({"evidence": None}, "consent_grant_needs_evidence"),
        ({"source": "inbound_call_verbal"}, "consent_verbal_grant_needs_call"),
        ({"source": "telepathy"}, "consent_unknown_source"),
        ({"status": "maybe"}, "consent_unknown_status"),
        ({"raw_phone": "not-a-number"}, "consent_phone_invalid"),
    ],
)
async def test_the_service_explains_every_refusal_the_check_would_have_made(
    kwargs: dict[str, Any], code: str
) -> None:
    """The CHECKs are the guarantee; these are the interface. An IntegrityError is a 500
    nobody can act on — a 422 naming the missing evidence is something a client can."""
    tenant_id, _, _ = await _tenant("refusals")
    call: dict[str, Any] = {
        "tenant_id": tenant_id,
        "raw_phone": SUBJECT,
        "status": "granted",
        "source": "web_form_optin",
        "evidence": EVIDENCE,
    }
    call.update(kwargs)
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as caught:
            await consent.record_messaging_consent(session, **call)
    assert caught.value.code == code


# --------------------------------------------------------------------------------
# 3. Append-only, latest row wins (hard rule 4)
# --------------------------------------------------------------------------------


async def test_a_withdrawal_appends_and_a_later_regrant_appends_again() -> None:
    """Three statements, three rows, and the answer is always the last one. Nothing is
    ever UPDATEd — the `consent_ledger_append_only` trigger would refuse it, and the
    history is what answers "were you allowed to message me in March?"."""
    tenant_id, _, _ = await _tenant("append")
    await _grant(tenant_id)
    async with tenant_session(tenant_id) as session:
        await consent.record_messaging_consent(
            session,
            tenant_id=tenant_id,
            raw_phone=SUBJECT,
            status="withdrawn",
            source="whatsapp_inbound_message",
        )
        assert (
            await consent.read_messaging_consent(session, tenant_id=tenant_id, phone_e164=SUBJECT)
        ).messageable is False

        await consent.record_messaging_consent(
            session,
            tenant_id=tenant_id,
            raw_phone=SUBJECT,
            status="granted",
            source="whatsapp_inbound_message",
            evidence={"message_id": "wamid.TEST"},
        )
        final = await consent.read_messaging_consent(
            session, tenant_id=tenant_id, phone_e164=SUBJECT
        )

    assert final.messageable is True and final.source == "whatsapp_inbound_message"
    assert [row[0] for row in await _rows(tenant_id)] == ["granted", "withdrawn", "granted"]


async def test_the_ledger_refuses_to_be_edited() -> None:
    """Hard rule 4 is enforced by a trigger, not by convention — including against a
    test that would find it convenient."""
    tenant_id, _, _ = await _tenant("immutable")
    await _grant(tenant_id)
    async with tenant_session(tenant_id) as session:
        with pytest.raises(Exception, match="append-only"):
            await session.execute(
                text("UPDATE consent_ledger SET status = 'withdrawn' WHERE tenant_id = :t"),
                {"t": tenant_id},
            )


# --------------------------------------------------------------------------------
# 4. Consent goes stale
# --------------------------------------------------------------------------------


async def test_a_grant_expires_without_being_deleted() -> None:
    """The row is evidence that consent WAS given; `messageable` is the question of
    whether it still is. Both matter, and they are not the same field."""
    tenant_id, _, _ = await _tenant("stale")
    stale_at = datetime.now(UTC) - timedelta(days=consent.MESSAGING_CONSENT_VALIDITY_DAYS + 1)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO consent_ledger (id, tenant_id, phone_e164, purpose, status, "
                "consent_source, evidence, captured_at, created_at) VALUES (:id, :t, :p, "
                "'messaging', 'granted', 'offline_form_optin', CAST(:ev AS jsonb), :at, :at)"
            ),
            {
                "id": uuid7(),
                "t": tenant_id,
                "p": SUBJECT,
                "ev": '{"document": "in-store form 2025-07"}',
                "at": stale_at,
            },
        )
        state = await consent.read_messaging_consent(
            session, tenant_id=tenant_id, phone_e164=SUBJECT
        )

    assert state.status == "granted", "the record survives; it is proof of what happened"
    assert state.messageable is False, "and it no longer authorises a message"
    assert state.expires_at is not None and state.expires_at < datetime.now(UTC)


async def test_a_fresh_grant_is_current_and_says_when_it_lapses() -> None:
    tenant_id, _, _ = await _tenant("fresh")
    await _grant(tenant_id)
    async with tenant_session(tenant_id) as session:
        state = await consent.read_messaging_consent(
            session, tenant_id=tenant_id, phone_e164=SUBJECT
        )
    assert state.messageable is True
    assert state.expires_at is not None
    assert state.captured_at is not None
    assert (state.expires_at - state.captured_at).days == consent.MESSAGING_CONSENT_VALIDITY_DAYS


async def test_a_number_typed_any_way_reaches_the_same_ledger_key() -> None:
    """A consent record whose key does not match the dispatch key is worse than none:
    it looks like protection and grants nothing. Both go through `normalize_phone`."""
    tenant_id, _, _ = await _tenant("normalise")
    async with tenant_session(tenant_id) as session:
        await consent.record_messaging_consent(
            session,
            tenant_id=tenant_id,
            raw_phone="90000 00077",
            status="granted",
            source="web_form_optin",
            evidence=EVIDENCE,
        )
        state = await consent.read_messaging_consent(
            session, tenant_id=tenant_id, phone_e164=SUBJECT
        )
    assert state.messageable is True


# --------------------------------------------------------------------------------
# 5. The surface
# --------------------------------------------------------------------------------


async def test_the_router_is_mounted_and_no_route_carries_a_number_in_its_path() -> None:
    """An unmounted router is not a surface. And the identifier IS the personal data:
    a GET would write it into access logs, proxy logs, referrers and browser history —
    the rule `dnc_routes.py` states and the subject-access export follows."""
    # `iter_api_routes`, not `app.routes`: FastAPI 0.140 stopped flattening
    # `include_router` at mount time, so a naive loop sees only the doc routes and any
    # assertion built on it passes for a router nobody mounted (the exact trap
    # `core/rbac.py` documents).
    paths = {
        route.path: route.methods for route in iter_api_routes(app) if route.path.startswith(RECORD)
    }
    assert set(paths) == {RECORD, LOOKUP}, "both endpoints are mounted on the live app"
    for path, methods in paths.items():
        assert methods == {"POST"}, f"{path} must be POST-only"
        assert "{" not in path, "no path parameter may carry a phone number"


async def test_recording_and_looking_up_never_echo_the_number() -> None:
    tenant_id, slug, token = await _tenant("route")
    async with _client() as client:
        created = await client.post(
            RECORD,
            headers=_headers(token, slug),
            json={
                "phone": SUBJECT,
                "status": "granted",
                "source": "web_form_optin",
                "evidence": EVIDENCE,
            },
        )
        assert created.status_code == 201, created.text
        assert created.json()["messageable"] is True
        assert SUBJECT not in created.text and SUBJECT.lstrip("+") not in created.text

        looked_up = await client.post(
            LOOKUP, headers=_headers(token, slug), json={"phone": SUBJECT}
        )
    assert looked_up.status_code == 200
    body = looked_up.json()
    assert body["status"] == "granted" and body["messageable"] is True
    assert body["source"] == "web_form_optin"
    assert SUBJECT not in looked_up.text and SUBJECT.lstrip("+") not in looked_up.text
    assert len(await _rows(tenant_id)) == 1


async def test_the_surface_records_a_withdrawal_as_a_new_row() -> None:
    tenant_id, slug, token = await _tenant("route-wd")
    async with _client() as client:
        headers = _headers(token, slug)
        await client.post(
            RECORD,
            headers=headers,
            json={
                "phone": SUBJECT,
                "status": "granted",
                "source": "web_form_optin",
                "evidence": EVIDENCE,
            },
        )
        withdrawn = await client.post(
            RECORD,
            headers=headers,
            json={
                "phone": SUBJECT,
                "status": "withdrawn",
                "source": "staff_recorded_request",
            },
        )
        assert withdrawn.status_code == 201, withdrawn.text
        assert withdrawn.json()["messageable"] is False
        after = await client.post(LOOKUP, headers=headers, json={"phone": SUBJECT})

    assert after.json()["status"] == "withdrawn"
    assert [row[0] for row in await _rows(tenant_id)] == ["granted", "withdrawn"]


async def test_the_surface_refuses_an_unevidenced_grant_with_an_actionable_code() -> None:
    _, slug, token = await _tenant("route-refuse")
    async with _client() as client:
        response = await client.post(
            RECORD,
            headers=_headers(token, slug),
            json={"phone": SUBJECT, "status": "granted", "source": "web_form_optin"},
        )
    assert response.status_code == 422
    assert _code(response) == "consent_grant_needs_evidence"
    assert response.json()["remediation"]


async def test_a_lookup_of_a_number_nobody_asked_is_a_200_saying_none() -> None:
    """Absence is data. A 404 arrives at the fetch layer indistinguishable from a moved
    route, and every caller would special-case it before showing the one thing the panel
    exists to show (the argument `registration_routes.py` makes for the same shape)."""
    _, slug, token = await _tenant("route-none")
    async with _client() as client:
        response = await client.post(LOOKUP, headers=_headers(token, slug), json={"phone": SUBJECT})
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "status": "none",
        "source": None,
        "captured_at": None,
        "expires_at": None,
        "messageable": False,
    }


async def test_recording_consent_writes_an_audit_row_without_the_number(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """ "Who did we newly permit ourselves to message" is a question an operator asks,
    and it does not need numbers in it to be answerable (hard rule 6).

    Both halves are checked where they land: `audit_log` has no summary column — the
    detail goes to the log stream keyed by the entry id (`compliance/audit.py`) — so the
    row proves the action was recorded and the rendered log proves what travelled with
    it. Rendered through the real `JsonFormatter`, because a record whose extras look
    clean can still stringify a number into `msg`.
    """
    tenant_id, slug, token = await _tenant("route-audit")
    formatter = JsonFormatter()
    with caplog.at_level(logging.INFO):
        async with _client() as client:
            await client.post(
                RECORD,
                headers=_headers(token, slug),
                json={
                    "phone": SUBJECT,
                    "status": "granted",
                    "source": "web_form_optin",
                    "evidence": EVIDENCE,
                },
            )
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text("SELECT action, object_type FROM audit_log WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
        ).all()
    assert [(str(row[0]), str(row[1])) for row in rows] == [
        ("messaging_consent.recorded", "consent_ledger")
    ]
    rendered = "\n".join(formatter.format(record) for record in caplog.records)
    assert '"msg": "audit"' in rendered, "the audit detail reaches the log stream"
    assert SUBJECT not in rendered and SUBJECT.lstrip("+") not in rendered


async def test_a_staff_member_cannot_record_consent_but_can_read_it() -> None:
    """`leads:dispatch` is the permission that already governs who may cause a person to
    be contacted, and an opt-in is exactly that decision. Reading is `leads:read`, which
    `staff` holds — and which an impersonating admin can also exercise (D-22)."""
    tenant_id, slug, token = await _tenant("route-rbac", role="staff")
    await _grant(tenant_id)
    async with _client() as client:
        headers = _headers(token, slug)
        refused = await client.post(
            RECORD,
            headers=headers,
            json={
                "phone": SUBJECT,
                "status": "granted",
                "source": "web_form_optin",
                "evidence": EVIDENCE,
            },
        )
        allowed = await client.post(LOOKUP, headers=headers, json={"phone": SUBJECT})
    assert refused.status_code == 403
    assert allowed.status_code == 200 and allowed.json()["messageable"] is True


# --------------------------------------------------------------------------------
# 6. The tuple and the wire type cannot drift
# --------------------------------------------------------------------------------


def test_the_wire_enums_match_the_constants_the_check_mirrors() -> None:
    """`CONSENT_SOURCES` is the tuple the CHECK mirrors and the Literal is what the
    generated TypeScript client switches on. A member added to one and not the other is
    a source the API advertises and the database refuses, or the reverse."""
    assert set(get_args(ConsentSource)) == set(CONSENT_SOURCES)
    assert set(get_args(ConsentStatus)) == set(consent.RECORDABLE_STATUSES)


async def test_a_number_the_normaliser_rejects_answers_no_consent_rather_than_erroring() -> None:
    """A number that has no ledger key gets the answer of a number nobody ever asked:
    `none`, and `messageable: false`.

    Fail-CLOSED is the property. This lookup is what a caller consults before sending,
    so the two wrong answers are both expensive: a 5xx makes the caller's error handler
    decide whether to send (and the handler nobody wrote sends), while any `messageable:
    true` on an unrecognisable identifier is a message to a stranger. The status must
    also be 200 — a 4xx here reads as "our call was malformed, retry it differently"
    rather than "you have no permission for this person".
    """
    _, slug, token = await _tenant("route-unnormalisable")
    async with _client() as client:
        response = await client.post(
            LOOKUP, headers=_headers(token, slug), json={"phone": "not a phone"}
        )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "status": "none",
        "source": None,
        "captured_at": None,
        "expires_at": None,
        "messageable": False,
    }
