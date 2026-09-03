"""TENANT erasure — the writer `organizations.deleted_at` never had (FLOWS §9, D-120).

`tests/tenant_birth_known_gaps_test.py` recorded the gap: nine readers, no writer, so
"erase this whole client" had no execution path and a column of load-bearing behaviour
was unreachable. That entry is deleted in this change, which is what these tests are for.

What is asserted here, in the order it matters:

1. **The seam is finished, end to end.** A real admin token, over HTTP, with the two keys
   the route demands, produces a request row, an outbox job, an audit entry and — once
   the worker runs — a stripped tenant, a set `deleted_at` and a certificate that is
   still readable AFTERWARDS.
2. **The state model holds.** `deleted_at` is a strict refinement of `churned`: an open
   account cannot be erased, and the DATABASE refuses the combination outright.
3. **All nine readers agree afterwards.** The dial gate refuses `account_closed`, the
   membership resolution refuses, `tenant_exists` is False, the invitation gate is 409,
   the admin directory omits the client. Asserted through the real predicates rather
   than by re-reading the column.
4. **Two keys, and the right refusal for each.** An operator without `ops:manage` is
   refused for the reason they cannot fix by typing a header; a superadmin without the
   header is told the header; a header bound to another tenant does not work here.
5. **Hard rule 4.** Every append-only ledger row the tenant had survives the erasure
   byte for byte. If tenant erasure needed to touch one, that would be a design problem
   to solve — retention, anonymisation, a compensating entry — not a rule to bend.
6. **Hard rule 1.** `tenant_erasure_requests` is RLS'd: a neighbour's session reads zero
   rows, and the policy is what does it.

CONCURRENCY: every case mints its own tenant and asserts only on rows it created, so
this file runs beside the other suites on the shared Postgres. Every phone number is
randomised.
"""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.compliance import tenant_erasure
from apps.api.compliance.service import account_stopped_blocker
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from apps.workers.pipeline import _resolve_agent, _withdrawn_route_tenant
from apps.workers.retention import ANONYMIZED_PHONE, REDACTED_MARK, execute_tenant_erasure
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

BASE = "/v1/admin/tenants/{tenant_id}/erasure"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _phone() -> str:
    return f"+9198761{uuid.uuid4().int % 100000:05d}"


async def _admin(role: str = "superadmin") -> str:
    """A real `admin_users` row plus the dev-token spelling of its realm."""
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


async def _tenant() -> tuple[UUID, UUID, str]:
    """(tenant_id, agent_id, slug) for a fresh client."""
    created = await admin_service.create_organization(
        name="Offboarding Clinic",
        slug=f"erase-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return UUID(str(created["id"])), UUID(str(created["agent_id"])), str(created["slug"])


async def _churn(tenant_id: UUID) -> None:
    """The precondition, written directly: the lifecycle route has its own tests."""
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET status = 'churned' WHERE id = :tid"),
            {"tid": tenant_id},
        )


async def _seed(tenant_id: UUID, agent_id: UUID, *, phone: str) -> tuple[UUID, UUID]:
    """One call with a turn, an extraction and a lead — every category the worker erases."""
    call_id, lead_id = uuid.uuid4(), uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status, "
                "data, created_at, updated_at) VALUES (:i, :t, :a, :phone, 'Ravi', "
                "'inbound_call', "
                "'new', '{\"city\": \"Hyderabad\"}'::jsonb, now(), now())"
            ),
            {"i": lead_id, "t": tenant_id, "a": agent_id, "phone": phone},
        )
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, lead_id, engine_call_id, direction, "
                "status, from_e164, to_e164, started_at, ended_at, duration_s, summary, "
                "created_at, updated_at) VALUES (:id, :t, :a, :l, :e, 'inbound', 'completed', "
                ":phone, '+911140000000', now(), now(), 61, 'Booked an appointment', "
                "now(), now())"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "a": agent_id,
                "l": lead_id,
                "e": f"exec_{call_id.hex[:10]}",
                "phone": phone,
            },
        )
        await session.execute(
            text(
                "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, text, "
                "text_redacted, created_at, updated_at) VALUES (:i, :t, :c, 0, 'caller', "
                "'naaku appointment kavali', 'naaku appointment kavali', now(), now())"
            ),
            {"i": uuid.uuid4(), "t": tenant_id, "c": call_id},
        )
        await session.execute(
            text(
                "INSERT INTO call_extractions (id, tenant_id, call_id, schema_version, data, "
                "created_at, updated_at) VALUES (:i, :t, :c, 1, "
                '\'{"name": "Ravi", "callback": "+919876500000"}\'::jsonb, now(), now())'
            ),
            {"i": uuid.uuid4(), "t": tenant_id, "c": call_id},
        )
    return call_id, lead_id


async def _post(
    token: str, tenant_id: UUID, *, confirm: str | None = None, reason: str = "Contract ended"
) -> Any:
    headers = {"Authorization": f"Bearer {token}"}
    if confirm is not None:
        headers["X-Confirm-Action"] = confirm
    async with _client() as http:
        return await http.post(
            BASE.format(tenant_id=tenant_id), json={"reason": reason}, headers=headers
        )


def _code(response: Any) -> str:
    """The problem's code. RFC-9457 carries it as the tail of `type`, not as a field."""
    return str(response.json()["type"]).rsplit("/", 1)[-1]


def _confirm(tenant_id: UUID) -> str:
    return tenant_erasure.tenant_erasure_confirmation(tenant_id)


async def _run_worker(tenant_id: UUID, request_id: str) -> str:
    return await execute_tenant_erasure({}, {"tenant_id": str(tenant_id), "request_id": request_id})


# --- 1. the whole seam --------------------------------------------------------------


@pytest.mark.anyio
async def test_the_erasure_runs_end_to_end_and_leaves_a_readable_certificate() -> None:
    """File it over HTTP, run the worker, read the certificate back afterwards.

    The last clause is the one that would be easy to lose: every other admin route
    filters `deleted_at IS NULL`, so a status read built the ordinary way would 404 at
    exactly the moment the erasure it certifies succeeded.
    """
    tenant_id, agent_id, _ = await _tenant()
    phone = _phone()
    call_id, lead_id = await _seed(tenant_id, agent_id, phone=phone)
    await _churn(tenant_id)
    token = await _admin()

    filed = await _post(token, tenant_id, confirm=_confirm(tenant_id))
    assert filed.status_code == 201, filed.text
    body = filed.json()
    assert body["status"] == "pending"
    assert body["already_open"] is False
    assert body["proof"] is None
    assert body["limitations"], "the register rides every response on this surface"

    assert "tenant erased" in await _run_worker(tenant_id, body["request_id"])

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT o.deleted_at, o.status, c.from_e164, c.to_e164, c.summary, "
                    "t.text, e.data, l.name, l.phone_e164 "
                    "FROM organizations o, calls c, transcript_turns t, call_extractions e, "
                    "leads l WHERE o.id = :tid AND c.id = :cid AND t.call_id = :cid "
                    "AND e.call_id = :cid AND l.id = :lid"
                ),
                {"tid": tenant_id, "cid": call_id, "lid": lead_id},
            )
        ).first()
    assert row is not None
    deleted_at, status, from_e164, to_e164, summary, turn_text, data, name, lead_phone = row
    assert deleted_at is not None, "the column this whole slice exists to write"
    assert status == "churned", "deleted_at is a refinement of churned, never a fourth state"
    assert (from_e164, to_e164, summary) == (None, None, None)
    assert turn_text == REDACTED_MARK
    assert data == {}
    assert name is None
    assert lead_phone.startswith(ANONYMIZED_PHONE[:9])
    assert phone not in str(row), "no copy of the number survives on any erased row"

    # READABLE AFTER. The tenant is gone from every other admin surface by now.
    async with _client() as http:
        read = await http.get(
            f"{BASE.format(tenant_id=tenant_id)}/{body['request_id']}",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert read.status_code == 200, read.text
    proof = read.json()["proof"]
    assert proof is not None
    assert proof["tenant_id"] == str(tenant_id)
    assert proof["scope"]["calls_erased"] == 1
    assert proof["scope"]["transcript_turns_erased"] == 1
    assert proof["scope"]["call_extractions_erased"] == 1
    assert proof["scope"]["leads_erased"] == 1
    assert proof["engine_deletion"] == "unconfirmed_pending_vendor_api"
    # The certificate states its own limits — the overclaim SEC-COMP §4 exists to stop.
    outcomes = {entry["outcome"] for entry in proof["not_erased"]}
    assert "retained_as_evidence" in outcomes
    assert "retained_under_legal_floor" in outcomes
    assert proof["limitations_version"].startswith("sha256:")


@pytest.mark.anyio
async def test_filing_the_audit_row_happens_in_the_same_transaction_as_the_request() -> None:
    """ "Who set the most destructive operation in the product in motion, and why."""
    tenant_id, _, _ = await _tenant()
    await _churn(tenant_id)
    token = await _admin()

    filed = await _post(token, tenant_id, confirm=_confirm(tenant_id), reason="Client offboarded")
    assert filed.status_code == 201, filed.text

    async with untenanted_session() as session:
        actions = (
            (
                await session.execute(
                    text("SELECT action FROM audit_log WHERE tenant_id = :tid"),
                    {"tid": tenant_id},
                )
            )
            .scalars()
            .all()
        )
        queued = (
            (
                await session.execute(
                    text(
                        "SELECT job FROM outbox_messages "
                        "WHERE payload->>'tenant_id' = :tid AND status = 'pending'"
                    ),
                    {"tid": str(tenant_id)},
                )
            )
            .scalars()
            .all()
        )
    assert "tenant.erasure_requested" in actions
    assert queued == [tenant_erasure.TENANT_ERASURE_JOB], (
        "the row and the job share one transaction — a row with no job is an offboarding "
        "that silently never runs"
    )


# --- 2 & 3. the state model, and the nine readers -----------------------------------


@pytest.mark.anyio
async def test_an_open_account_cannot_be_erased_and_nothing_is_touched() -> None:
    """`deleted_at` only ever refines `churned`. An `active` client is a 409, by name."""
    tenant_id, agent_id, _ = await _tenant()
    phone = _phone()
    call_id, _ = await _seed(tenant_id, agent_id, phone=phone)
    token = await _admin()

    refused = await _post(token, tenant_id, confirm=_confirm(tenant_id))
    assert refused.status_code == 409, refused.text
    assert _code(refused) == "tenant_not_closed"
    assert refused.json()["remediation"], "a refusal an operator can act on"

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT o.deleted_at, c.from_e164 FROM organizations o, calls c "
                    "WHERE o.id = :tid AND c.id = :cid"
                ),
                {"tid": tenant_id, "cid": call_id},
            )
        ).first()
    assert row == (None, phone), "a refused erasure erases nothing"


@pytest.mark.anyio
async def test_the_database_refuses_a_deleted_tenant_that_is_not_churned() -> None:
    """THE INVARIANT IS DATABASE-ENFORCED, and this test cannot be made red from Python.

    `ck_organizations_deleted_implies_churned` is what actually holds
    `deleted_at IS NOT NULL => status = 'churned'` — the rule that lets nine readers
    filter on different columns and still agree. The application checks it twice as well
    (`tenant_erasure.assert_erasable`, and the worker's `AND status = 'churned'`), but
    those are there so the failure is a clear refusal rather than an integrity error.

    THE REAL SABOTAGE FOR THIS ASSERTION IS:

        ALTER TABLE organizations DROP CONSTRAINT ck_organizations_deleted_implies_churned;

    after which this test goes green on a broken invariant, and the two application
    checks are all that is left. No `.py` edit can make it red, so it is written to say
    so rather than dropped.
    """
    tenant_id, _, _ = await _tenant()
    with pytest.raises(IntegrityError) as raised:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE organizations SET deleted_at = now() WHERE id = :tid"),
                {"tid": tenant_id},
            )
    assert "ck_organizations_deleted_implies_churned" in str(raised.value)


@pytest.mark.anyio
async def test_after_the_erasure_every_reader_of_the_column_refuses_the_tenant() -> None:
    """The consequence, asserted through the real predicates rather than the column.

    These are the readers D-120 listed as correct-but-unreachable. Reaching them is the
    whole point of building the writer.
    """
    tenant_id, _, slug = await _tenant()
    await _churn(tenant_id)
    token = await _admin()
    filed = await _post(token, tenant_id, confirm=_confirm(tenant_id))
    await _run_worker(tenant_id, filed.json()["request_id"])

    async with tenant_session(tenant_id) as session:
        # The dial gate (hard rule 5's outbound path).
        assert await account_stopped_blocker(session, tenant_id=tenant_id) == (
            "account_closed",
            "This account is closed.",
        )
        # The one definition of "is this a live organization".
        assert await admin_service.tenant_exists(session, tenant_id) is False
        # The invitation gate, at the mint and the burn.
        with pytest.raises(ProblemError) as invite:
            await admin_service.assert_account_open(session, tenant_id=tenant_id)
        assert invite.value.code == "account_closed"

    async with untenanted_session() as session:
        # `core/auth.py`'s membership resolution and its impersonation slug lookup.
        memberships = (
            await session.execute(
                text(
                    "SELECT 1 FROM memberships m JOIN organizations o ON o.id = m.tenant_id "
                    "WHERE m.tenant_id = :tid AND o.deleted_at IS NULL "
                    "AND o.status <> 'churned'"
                ),
                {"tid": tenant_id},
            )
        ).first()
        by_slug = (
            await session.execute(
                text("SELECT 1 FROM organizations WHERE slug = :slug AND deleted_at IS NULL"),
                {"slug": slug},
            )
        ).first()
    assert memberships is None
    assert by_slug is None

    # And the admin directory, over HTTP.
    async with _client() as http:
        directory = await http.get(
            "/v1/admin/tenants", headers={"Authorization": f"Bearer {token}"}
        )
    assert directory.status_code == 200, directory.text
    assert slug not in directory.text


@pytest.mark.anyio
async def test_erasing_twice_is_refused_by_name() -> None:
    """`deleted_at` is set once and never cleared, so a second ask is not a retry."""
    tenant_id, _, _ = await _tenant()
    await _churn(tenant_id)
    token = await _admin()
    filed = await _post(token, tenant_id, confirm=_confirm(tenant_id))
    await _run_worker(tenant_id, filed.json()["request_id"])

    again = await _post(token, tenant_id, confirm=_confirm(tenant_id))
    assert again.status_code == 409, again.text
    assert _code(again) == "tenant_already_erased"


@pytest.mark.anyio
async def test_the_worker_is_idempotent_on_a_completed_request() -> None:
    """arq WILL re-run this job. A re-run must not produce a second, weaker proof."""
    tenant_id, _, _ = await _tenant()
    await _churn(tenant_id)
    token = await _admin()
    filed = await _post(token, tenant_id, confirm=_confirm(tenant_id))
    request_id = filed.json()["request_id"]
    await _run_worker(tenant_id, request_id)
    assert await _run_worker(tenant_id, request_id) == "already_completed"


@pytest.mark.anyio
async def test_filing_twice_before_execution_returns_the_request_in_flight() -> None:
    """A double-click must converge on ONE certificate, not two."""
    tenant_id, _, _ = await _tenant()
    await _churn(tenant_id)
    token = await _admin()

    first = await _post(token, tenant_id, confirm=_confirm(tenant_id))
    second = await _post(token, tenant_id, confirm=_confirm(tenant_id))
    assert first.status_code == 201
    assert second.status_code == 200, second.text
    assert second.json()["already_open"] is True
    assert second.json()["request_id"] == first.json()["request_id"]

    async with tenant_session(tenant_id) as session:
        count = (
            await session.execute(text("SELECT count(*) FROM tenant_erasure_requests"))
        ).scalar_one()
    assert count == 1


@pytest.mark.anyio
async def test_the_list_answers_after_the_erasure_and_is_ordered_newest_first() -> None:
    """The GET the lifecycle screen reads, which had no test at any layer.

    Two properties, and the second is the one with a consequence. **Newest first**, so a
    screen taking `[0]` gets the erasure that is actually in flight rather than an older
    one. And **still answerable once the tenant is erased** — every other admin route
    filters `deleted_at IS NULL`, so a status read built the ordinary way would 404 at
    exactly the instant the erasure it certifies succeeds. `list_tenant_erasures` says so
    in its docstring; nothing until now made it fail if a later edit routed it through
    `tenant_exists`.
    """
    tenant_id, _, _ = await _tenant()
    await _churn(tenant_id)
    token = await _admin()
    filed = await _post(token, tenant_id, confirm=_confirm(tenant_id))
    request_id = filed.json()["request_id"]
    await _run_worker(tenant_id, request_id)

    async with _client() as http:
        listed = await http.get(
            BASE.format(tenant_id=tenant_id), headers={"Authorization": f"Bearer {token}"}
        )
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert [row["request_id"] for row in body] == [request_id], (
        "the erasure certificate became unreachable at the moment it was produced"
    )
    assert body[0]["completed_at"] is not None

    # The service half, on its own session, so a route that filtered in Python would
    # still leave this assertion standing.
    async with tenant_session(tenant_id) as session:
        records = await tenant_erasure.list_tenant_erasures(session, limit=50)
    # `record.id` here, `request_id` on the wire — the rename happens in `_out`.
    assert [str(r.id) for r in records] == [request_id]


@pytest.mark.anyio
async def test_filing_against_a_tenant_that_does_not_exist_is_a_404() -> None:
    """A 404, not a 500 and not a spurious 409.

    The id is a well-formed uuid naming nothing — the shape an operator produces by
    pasting a tenant id from a system that has since been erased. RLS makes a neighbour's
    tenant indistinguishable from an absent one here, which is the correct answer and the
    reason this is a 404 rather than a 403.
    """
    token = await _admin()
    missing = uuid.uuid4()
    response = await _post(token, missing, confirm=_confirm(missing))
    assert response.status_code == 404, response.text
    assert "not_found" in _code(response) or _code(response) == "not_found"


# --- 4. the two keys ----------------------------------------------------------------


@pytest.mark.anyio
async def test_an_operator_is_refused_for_a_reason_a_header_cannot_fix() -> None:
    """The ROLE check runs FIRST: a step-up is a confirmation, not an authorisation."""
    tenant_id, _, _ = await _tenant()
    await _churn(tenant_id)
    token = await _admin("operator")

    refused = await _post(token, tenant_id, confirm=_confirm(tenant_id))
    assert refused.status_code == 403, refused.text
    assert "superadmin" in refused.json()["detail"]


@pytest.mark.anyio
async def test_a_superadmin_without_the_confirmation_is_told_the_exact_header() -> None:
    """A confirmation that exists only in the browser is not a guard — it is absent
    from curl. The refusal prints the string so a runbook does not have to."""
    tenant_id, _, _ = await _tenant()
    await _churn(tenant_id)
    token = await _admin()

    refused = await _post(token, tenant_id)
    assert refused.status_code == 403, refused.text
    assert _code(refused) == "step_up_required"
    assert _confirm(tenant_id) in refused.json()["remediation"]


@pytest.mark.anyio
async def test_a_confirmation_bound_to_another_tenant_does_not_work_here() -> None:
    """The whole point of binding the string: a confirmation captured for one client
    must not be replayable against the next one in the list."""
    victim, _, _ = await _tenant()
    other, _, _ = await _tenant()
    await _churn(victim)
    token = await _admin()

    refused = await _post(token, victim, confirm=_confirm(other))
    assert refused.status_code == 403
    assert _code(refused) == "step_up_required"

    async with tenant_session(victim) as session:
        deleted_at = (
            await session.execute(
                text("SELECT deleted_at FROM organizations WHERE id = :tid"), {"tid": victim}
            )
        ).scalar_one()
    assert deleted_at is None


# --- 5. hard rule 4 -----------------------------------------------------------------


@pytest.mark.anyio
async def test_the_append_only_ledgers_survive_the_erasure_untouched() -> None:
    """Hard rule 4 is a CONSTRAINT this had to design around, not a rule to bend.

    A tenant erasure cannot reduce a ledger. `consent_ledger` even carries the caller's
    number, and the certificate says so in words a client can read rather than quietly
    leaving the number there under a document claiming everything was erased.
    """
    tenant_id, agent_id, _ = await _tenant()
    phone = _phone()
    call_id, _ = await _seed(tenant_id, agent_id, phone=phone)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO consent_ledger (id, tenant_id, phone_e164, purpose, status, "
                "captured_at, created_at) VALUES (:i, :t, :p, 'recording', 'granted', "
                "now(), now())"
            ),
            {"i": uuid.uuid4(), "t": tenant_id, "p": phone},
        )
        await session.execute(
            text(
                "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                "unit_cost_paid, occurred_at, created_at) VALUES (:i, :t, :c, "
                "'platform_min', 1.0, 4.2000, now(), now())"
            ),
            {"i": uuid.uuid4(), "t": tenant_id, "c": call_id},
        )
    await _churn(tenant_id)
    token = await _admin()
    filed = await _post(token, tenant_id, confirm=_confirm(tenant_id))
    await _run_worker(tenant_id, filed.json()["request_id"])

    async with tenant_session(tenant_id) as session:
        consent = (
            await session.execute(text("SELECT phone_e164 FROM consent_ledger"))
        ).scalar_one()
        usage = (
            await session.execute(text("SELECT unit_cost_paid FROM usage_events"))
        ).scalar_one()
    assert consent == phone, "the consent ledger is the proof the calls were lawful"
    assert str(usage).startswith("4.2"), "a closed billing period is not rewritten"

    read = tenant_erasure.certificate(None)
    assert read is None
    assert any("append-only" in line for line in tenant_erasure.TENANT_ERASURE_LIMITATIONS)


# --- 6. hard rule 1 -----------------------------------------------------------------


@pytest.mark.anyio
async def test_a_neighbour_reads_zero_erasure_rows() -> None:
    """Hard rule 1's cross-tenant zero-rows test, over the real policy.

    `calevate_app` is NOBYPASSRLS and cannot `SET ROLE`, so what makes this red is
    dropping the policy — `DROP POLICY tenant_isolation ON tenant_erasure_requests;` —
    rather than any application edit. The row is created through the real route so the
    test cannot pass because nothing was written.
    """
    mine, _, _ = await _tenant()
    theirs, _, _ = await _tenant()
    await _churn(mine)
    token = await _admin()
    filed = await _post(token, mine, confirm=_confirm(mine))
    assert filed.status_code == 201

    async with tenant_session(mine) as session:
        assert (
            await session.execute(text("SELECT count(*) FROM tenant_erasure_requests"))
        ).scalar_one() == 1
    async with tenant_session(theirs) as session:
        assert (
            await session.execute(text("SELECT count(*) FROM tenant_erasure_requests"))
        ).scalar_one() == 0

    # And through the surface: the neighbour's admin read of MY request id finds nothing.
    async with _client() as http:
        cross = await http.get(
            f"{BASE.format(tenant_id=theirs)}/{filed.json()['request_id']}",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert cross.status_code == 404, cross.text


# --- the recording arm --------------------------------------------------------------


@pytest.mark.anyio
async def test_audio_inside_the_trai_floor_is_scheduled_rather_than_orphaned() -> None:
    """The failure `recording_erasure_holds` was built for, on the OTHER erasure path.

    Clearing `calls.recording_url` destroys the only handle anything has on the object,
    and the nightly sweep selects `WHERE recording_url IS NOT NULL` — so a tenant erasure
    that cleared the pointer without recording a hold would make the audio permanently
    undeletable, exactly as `execute_deletion_request` once did (migration 9c1d3e7a05f4).
    The hold is owned by `tenant_erasure_id`, not `request_id`: a §12 certificate must
    not appear in a client's register for a request nobody made, and
    `ck_recording_hold_one_owner` makes "exactly one owner" a database fact.
    """
    tenant_id, agent_id, _ = await _tenant()
    call_id, _ = await _seed(tenant_id, agent_id, phone=_phone())
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET recording_url = :key, ended_at = now() WHERE id = :cid"),
            {"cid": call_id, "key": f"recordings/{tenant_id}/2026/08/{call_id}.wav"},
        )
    await _churn(tenant_id)
    token = await _admin()
    filed = await _post(token, tenant_id, confirm=_confirm(tenant_id))
    request_id = filed.json()["request_id"]
    await _run_worker(tenant_id, request_id)

    async with tenant_session(tenant_id) as session:
        hold = (
            await session.execute(
                text(
                    "SELECT tenant_erasure_id, request_id, call_id, erase_after, erased_at "
                    "FROM recording_erasure_holds"
                )
            )
        ).first()
        pointer = (
            await session.execute(
                text("SELECT recording_url FROM calls WHERE id = :cid"), {"cid": call_id}
            )
        ).scalar_one()
    assert hold is not None, "the erasure owed a destruction and recorded nothing"
    assert str(hold[0]) == request_id, "owned by the TENANT erasure"
    assert hold[1] is None, "and by nothing on the per-subject path"
    assert hold[4] is None, "not yet destroyed — that is the sweep's job, on its date"
    assert pointer is None, "the pointer is cleared at every age, as SEC-COMP §4 requires"

    async with _client() as http:
        read = await http.get(
            f"{BASE.format(tenant_id=tenant_id)}/{request_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
    proof = read.json()["proof"]
    assert proof["scope"]["recordings_within_trai_floor"] == 1
    assert proof["scope"]["recordings_destroyed"] == 0
    assert proof["recording_hold_until"], "the certificate gives a date, not 'indefinitely'"


# --- 8. an erased account stops COLLECTING, not just holding (D-189) ------------------


@pytest.mark.anyio
async def test_an_erased_tenant_records_no_further_inbound_call() -> None:
    """Erasing the account withdraws its voice-platform routing, in the same transaction.

    Every other assertion in this file is about what the tenant HAD. This one is about
    what it can still ACQUIRE, which nothing stopped: `engine_agent_routes` is the one
    bridge from the engine's id space into ours (`workers/pipeline._resolve_agent`), the
    vendor's agent is still configured and the client's number still points at it, so
    the first inbound call after the certificate was issued re-created a `calls` row and
    everything hanging off it — full caller records under a tenant_id whose certificate
    says the account is erased, and which the client's own people are locked out of
    (`core/auth.py` refuses a churned org).

    Asserted through the real resolver rather than by reading the column, because the
    resolver is what decides whether a record gets written at all.
    """
    tenant_id, agent_id, _ = await _tenant()
    ref = f"withdrawn_{uuid.uuid4().hex[:10]}"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, "
                "agent_id, active, created_at, updated_at) "
                "VALUES ('fake', :r, :t, :a, true, now(), now())"
            ),
            {"r": ref, "t": tenant_id, "a": agent_id},
        )
    await _churn(tenant_id)
    token = await _admin()

    filed = await _post(token, tenant_id, confirm=_confirm(tenant_id))
    assert filed.status_code == 201, filed.text
    request_id = filed.json()["request_id"]

    async with untenanted_session() as session:
        assert await _resolve_agent(session, "fake", ref) is not None, "live before the erasure"

    await _run_worker(tenant_id, request_id)

    async with untenanted_session() as session:
        assert await _resolve_agent(session, "fake", ref) is None, (
            "an erased account is still routing inbound calls into itself"
        )
        # The row survives, inactive: it is what tells an operator WHOSE number is still
        # live when the next stranger rings it, which no other record can answer.
        assert await _withdrawn_route_tenant(session, "fake", ref) == tenant_id

    async with _client() as http:
        read = await http.get(
            f"{BASE.format(tenant_id=tenant_id)}/{request_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
    proof = read.json()["proof"]
    routes = proof["actions"]["engine_agent_routes"]
    assert routes.startswith("1 voice-platform routing"), routes
    # And the certificate must not let a reader infer the vendor-side agent went with it.
    engine_clause = next(
        line for line in proof["limitations"] if "voice platform" in line and "manual" in line
    )
    assert "still reaches an answering agent" in engine_clause


@pytest.mark.anyio
async def test_the_written_request_names_the_clients_knowledge_bases_too() -> None:
    """D-519. The vendor-side deletion request quoted agent ids and nothing else.

    A knowledge base on that platform is an ACCOUNT-level object with no owner field
    (`bolna-findings/mirror/pages/api-reference/knowledgebase/get_knowledgebases.md
    :63-121`), so a client's uploaded document is NOT covered by an agent id unless
    deleting an agent also deletes the knowledge bases it referenced — and the vendor's
    delete page enumerates batches, executions and configurations and never says
    (`.../agent/v2/delete.md:7,10`; OPERATIONS §2 gate 43f). Quoting the handles is right
    under either answer: already-deleted objects make the request a no-op the vendor
    confirms, and orphaned ones are findable by nothing else — one account holds every
    tenant's documents and the platform records whose none of them are.

    The claim is read from `engine_kb_routes`, which is why it survives a tenant whose
    `kb_sources` rows a retention sweep has already taken.
    """
    tenant_id, agent_id, _ = await _tenant()
    handle = f"vec-erasure-{uuid.uuid4().hex[:12]}"
    source_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO kb_sources (id, tenant_id, agent_id, kind, name) "
                "VALUES (:id, :t, :a, 'text', 'Fees')"
            ),
            {"id": source_id, "t": tenant_id, "a": agent_id},
        )
        await session.execute(
            text(
                "INSERT INTO engine_kb_routes (engine, engine_kb_ref, tenant_id, agent_id, "
                "source_id) VALUES ('fake', :ref, :t, :a, :s)"
            ),
            {"ref": handle, "t": tenant_id, "a": agent_id, "s": source_id},
        )
    await _churn(tenant_id)
    token = await _admin()
    filed = await _post(token, tenant_id, confirm=_confirm(tenant_id))
    assert filed.status_code == 201, filed.text

    await _run_worker(tenant_id, filed.json()["request_id"])

    # A TENANT session, not an untenanted one: `processor_erasure_tasks` is FORCE-RLS'd
    # and fail-closed on an unset GUC, so an untenanted read answers None for a task that
    # is really there — which reads exactly like the defect under test.
    async with tenant_session(tenant_id) as session:
        refs = (
            await session.execute(
                text(
                    "SELECT vendor_refs FROM processor_erasure_tasks "
                    "WHERE tenant_id = :t AND processor = 'voice_engine'"
                ),
                {"t": tenant_id},
            )
        ).scalar()
    assert refs is not None, "no vendor-side erasure obligation was opened at all"
    assert handle in refs, (
        "the written deletion request does not name this client's knowledge bases, so "
        "their uploaded documents can never be found again on a shared vendor account"
    )
