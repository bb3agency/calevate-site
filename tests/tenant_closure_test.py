"""Closing a client business, and taking it back (D-538).

The founder's delete button, built as *close now, erase after a grace period, undo during
it*. What is asserted here, in the order it matters:

1. **The seam is finished, end to end.** A real admin token, over HTTP, with the header the
   route demands, closes the account, sets the deadline, queues the client's notice and
   writes the audit row — all in one transaction, so none of them can exist without the
   others.
2. **The window is real and the undo works inside it.** The sweep does nothing before the
   date, files exactly one erasure after it, and a restore in between cancels the deadline
   and makes the sweep a no-op — asserted by RUNNING the sweep, not by reading a column.
3. **The undo's one refusal is a fact about the data, not a clock.** A deadline that has
   passed while the sweep was behind is still reversible; an account that has actually been
   erased is not.
4. **The database holds the nesting.** `deleted_at` refines `closed_at` refines `churned`,
   and the CHECKs refuse every combination that would let the nine readers of those columns
   disagree about whether a business exists.
5. **What the close switches off** — the dial gate, membership resolution, the invitation
   gate — through the real predicates rather than by re-reading `status`.
6. **The resend rotates rather than mints.** The previous link stops working in the same
   statement, one account never holds two live keys, the rate limit is the database's own
   clock, and a corrected address is recorded as an OPERATOR ATTESTATION.

CONCURRENCY: every case mints its own tenant and asserts only on rows it created, so this
file runs beside the other suites on the shared Postgres.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.admin.closure_routes import close_account_confirmation
from apps.api.compliance.service import account_stopped_blocker
from apps.api.core.errors import ProblemError
from apps.api.db.session import admin_session, tenant_session, untenanted_session
from apps.api.main import app
from apps.api.tenancy import closure
from apps.api.tenancy.lifecycle import assert_account_open
from apps.workers.account_closure import NOTICE_JOB, sweep_due_erasures
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

BASE = "/v1/admin/tenants/{tenant_id}/closure"
INVITES = "/v1/admin/tenants/{tenant_id}/invitations"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _admin(role: str = "superadmin") -> str:
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


async def _tenant() -> UUID:
    created = await admin_service.create_organization(
        name="Closing Clinic",
        slug=f"close-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email="owner@clinic.example",
        language="te-IN",
        created_by=None,
    )
    return UUID(str(created["id"]))


def _code(response: Any) -> str:
    """The problem's code. RFC-9457 carries it as the tail of `type`, not as a field."""
    return str(response.json()["type"]).rsplit("/", 1)[-1]


async def _close(
    token: str,
    tenant_id: UUID,
    *,
    confirm: str | None = None,
    reason: str = "Client asked us to stop",
    grace_days: int | None = None,
) -> Any:
    headers = {"Authorization": f"Bearer {token}"}
    if confirm is not None:
        headers["X-Confirm-Action"] = confirm
    body: dict[str, Any] = {"reason": reason}
    if grace_days is not None:
        body["grace_days"] = grace_days
    async with _client() as http:
        return await http.post(BASE.format(tenant_id=tenant_id), json=body, headers=headers)


async def _outbox_jobs(tenant_id: UUID) -> list[dict[str, Any]]:
    """Every closure notice queued for this tenant, oldest first.

    Read from `outbox_messages`, which is not tenant-policied, so the filter is on the
    payload rather than on RLS.
    """
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT payload FROM outbox_messages WHERE job = :job "
                    "AND payload->>'tenant_id' = :tid ORDER BY created_at, id"
                ),
                {"job": NOTICE_JOB, "tid": str(tenant_id)},
            )
        ).all()
    return [row[0] for row in rows]


async def _audit_actions(tenant_id: UUID) -> list[str]:
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text("SELECT action FROM audit_log WHERE tenant_id = :tid ORDER BY created_at, id"),
                {"tid": tenant_id},
            )
        ).all()
    return [str(row[0]) for row in rows]


# --- the close ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_closing_stops_the_account_sets_the_deadline_and_tells_the_client() -> None:
    """One request; four things that must all be true or none of them.

    The route, the deadline, the queued notice and the audit row share one transaction, so
    this asserts them together rather than in four cases — the failure this guards is
    exactly a closure committing with one of them missing.
    """
    token, tenant_id = await _admin(), await _tenant()

    response = await _close(token, tenant_id, confirm=close_account_confirmation(tenant_id))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "churned"
    assert body["closed_at"] is not None
    assert body["erase_after"] is not None
    assert body["restorable"] is True
    assert body["erased_at"] is None
    # 30 days out, computed from the DATABASE's clock — one day of slack rather than an
    # equality, because the countdown floors and the test does not own the clock.
    assert body["days_remaining"] in (29, 30)

    queued = await _outbox_jobs(tenant_id)
    assert [job["event"] for job in queued] == ["closed"]
    # The client is told the DATE, not a timestamp: it is a deadline a person acts on.
    assert queued[0]["erase_on"] == body["erase_after"][:10]
    assert queued[0]["reason"] == "Client asked us to stop"

    assert "tenant.closed" in await _audit_actions(tenant_id)


@pytest.mark.asyncio
async def test_a_closed_account_stops_dialling_and_stops_letting_anyone_in() -> None:
    """What "close" switches off, through the real predicates rather than the column.

    Re-reading `status` would assert that this test knows what closing writes; asking the
    two gates asserts what the rest of the system does about it, which is the property the
    founder actually bought.
    """
    token, tenant_id = await _admin(), await _tenant()
    await _close(token, tenant_id, confirm=close_account_confirmation(tenant_id))

    async with tenant_session(tenant_id) as session:
        assert await account_stopped_blocker(session, tenant_id=tenant_id) == (
            "account_closed",
            "This account is closed.",
        )
        with pytest.raises(ProblemError) as invite_refusal:
            await assert_account_open(session, tenant_id=tenant_id)
    assert invite_refusal.value.code == "account_closed"


@pytest.mark.asyncio
async def test_closing_twice_returns_the_first_closure_and_does_not_restart_the_clock() -> None:
    """A refreshed screen must not silently give a client thirty more days."""
    token, tenant_id = await _admin(), await _tenant()
    confirm = close_account_confirmation(tenant_id)

    first = (await _close(token, tenant_id, confirm=confirm)).json()
    second = (await _close(token, tenant_id, confirm=confirm, reason="Different words")).json()

    assert second["erase_after"] == first["erase_after"]
    assert second["closed_at"] == first["closed_at"]
    assert second["reason"] == first["reason"] == "Client asked us to stop"
    # One transition, one notice, one audit row: the second call changed nothing, so it
    # must not have told the client anything either.
    assert len(await _outbox_jobs(tenant_id)) == 1
    assert (await _audit_actions(tenant_id)).count("tenant.closed") == 1


@pytest.mark.asyncio
async def test_the_close_needs_the_header_and_the_header_is_bound_to_this_client() -> None:
    """A confirm dialog in the browser is not a guard; it is absent from curl.

    And a confirmation captured while closing one client must not be replayable against
    another — which is what binding the string to the tenant id buys.
    """
    token, tenant_id, neighbour = await _admin(), await _tenant(), await _tenant()

    bare = await _close(token, tenant_id)
    assert bare.status_code == 403
    assert _code(bare) == "step_up_required"

    borrowed = await _close(token, tenant_id, confirm=close_account_confirmation(neighbour))
    assert borrowed.status_code == 403

    # Neither refusal may have moved anything.
    async with tenant_session(tenant_id) as session:
        assert (await closure.read_closure(session, tenant_id=tenant_id)).is_closed is False


@pytest.mark.asyncio
async def test_the_status_route_s_confirmation_does_not_open_this_door() -> None:
    """The two closes are different acts and must not share one confirmation.

    `admin/routes.close_account_confirmation` guards ending a relationship; this route
    additionally sets a date after which the business's records are destroyed. A
    confirmation captured for the first must not authorise the second.
    """
    from apps.api.admin.routes import close_account_confirmation as status_confirmation

    token, tenant_id = await _admin(), await _tenant()
    assert status_confirmation(tenant_id) != close_account_confirmation(tenant_id)

    response = await _close(token, tenant_id, confirm=status_confirmation(tenant_id))
    assert response.status_code == 403


# --- the undo ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_undo_reopens_the_account_cancels_the_deadline_and_says_so() -> None:
    token, tenant_id = await _admin(), await _tenant()
    await _close(token, tenant_id, confirm=close_account_confirmation(tenant_id))

    async with _client() as http:
        response = await http.delete(
            BASE.format(tenant_id=tenant_id), headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "active"
    assert body["closed_at"] is None
    assert body["erase_after"] is None
    assert body["days_remaining"] is None

    # The account really is open again — asked of the gate, not of the column.
    async with tenant_session(tenant_id) as session:
        assert await account_stopped_blocker(session, tenant_id=tenant_id) is None

    assert [job["event"] for job in await _outbox_jobs(tenant_id)] == ["closed", "restored"]
    assert "tenant.closure_reversed" in await _audit_actions(tenant_id)


@pytest.mark.asyncio
async def test_the_undo_carries_no_step_up_because_it_is_the_recovery_path() -> None:
    """Deliberate asymmetry: the operator who closed the wrong client at a coffee shop has
    to be able to fix it from the same coffee shop."""
    token, tenant_id = await _admin(), await _tenant()
    await _close(token, tenant_id, confirm=close_account_confirmation(tenant_id))

    async with _client() as http:
        # No `X-Confirm-Action` at all.
        response = await http.delete(
            BASE.format(tenant_id=tenant_id), headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_reopening_an_account_that_is_not_closed_changes_nothing_and_tells_nobody() -> None:
    """A satisfied intent is a success, not a 409 — and it must not mail the client about
    a reversal that did not happen."""
    token, tenant_id = await _admin(), await _tenant()

    async with _client() as http:
        response = await http.delete(
            BASE.format(tenant_id=tenant_id), headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 200
    assert response.json()["closed_at"] is None
    assert await _outbox_jobs(tenant_id) == []


@pytest.mark.asyncio
async def test_the_undo_is_refused_once_the_erasure_has_actually_run() -> None:
    """The ONE refusal, and it reads `deleted_at` rather than a clock."""
    token, tenant_id = await _admin(), await _tenant()
    await _close(token, tenant_id, confirm=close_account_confirmation(tenant_id))
    async with tenant_session(tenant_id) as session:
        # What the erasure worker writes when it completes.
        await session.execute(
            text("UPDATE organizations SET erase_after = NULL, deleted_at = now() WHERE id = :t"),
            {"t": tenant_id},
        )

    async with _client() as http:
        response = await http.delete(
            BASE.format(tenant_id=tenant_id), headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 409
    assert _code(response) == "tenant_already_erased"


@pytest.mark.asyncio
async def test_a_deadline_that_has_passed_is_still_reversible_while_nothing_is_erased() -> None:
    """The sweep can be an hour behind or stopped. Telling an operator "too late" about
    data that still exists would cost a client their account for a cron's tardiness."""
    token, tenant_id = await _admin(), await _tenant()
    await _close(token, tenant_id, confirm=close_account_confirmation(tenant_id))
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET erase_after = now() - interval '2 days' WHERE id = :t"),
            {"t": tenant_id},
        )
        record = await closure.restore_account(session, tenant_id=tenant_id)

    assert record.is_closed is False
    assert record.erase_after is None


# --- the deadline the database holds -------------------------------------------------


@pytest.mark.asyncio
async def test_the_database_refuses_a_deadline_on_an_account_nobody_closed() -> None:
    """`ck_organizations_erase_after_implies_closed`. A timer that erases a LIVE client's
    data is the state this CHECK exists to make unrepresentable."""
    tenant_id = await _tenant()
    with pytest.raises(IntegrityError):
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE organizations SET erase_after = now() WHERE id = :t"),
                {"t": tenant_id},
            )


@pytest.mark.asyncio
async def test_the_database_refuses_a_closure_on_an_account_that_is_not_churned() -> None:
    """`ck_organizations_closed_implies_churned` — the nesting the nine readers rely on."""
    tenant_id = await _tenant()
    with pytest.raises(IntegrityError):
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE organizations SET closed_at = now() WHERE id = :t"),
                {"t": tenant_id},
            )


@pytest.mark.asyncio
async def test_the_database_refuses_a_pending_deadline_on_an_erased_account() -> None:
    """`ck_organizations_deleted_implies_no_deadline`. Otherwise the sweep would file a
    second erasure against an account whose subject is already gone — a 409 raised from a
    cron, hourly, for ever."""
    token, tenant_id = await _admin(), await _tenant()
    await _close(token, tenant_id, confirm=close_account_confirmation(tenant_id))
    with pytest.raises(IntegrityError):
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE organizations SET deleted_at = now() WHERE id = :t"),
                {"t": tenant_id},
            )


# --- the sweep ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_sweep_ignores_a_deadline_that_has_not_arrived() -> None:
    token, tenant_id = await _admin(), await _tenant()
    await _close(token, tenant_id, confirm=close_account_confirmation(tenant_id))

    async with admin_session() as directory:
        due = await closure.due_erasures(directory)

    assert tenant_id not in {row[0] for row in due}


@pytest.mark.asyncio
async def test_the_sweep_files_exactly_one_erasure_once_the_date_has_passed() -> None:
    """It FILES; it does not erase. The row it produces is the one the console's own
    button produces, and running the sweep twice converges on it rather than minting a
    second."""
    token, tenant_id = await _admin(), await _tenant()
    await _close(token, tenant_id, confirm=close_account_confirmation(tenant_id), grace_days=0)

    await sweep_due_erasures({})
    await sweep_due_erasures({})

    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT reason FROM tenant_erasure_requests WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
        ).all()
    assert len(rows) == 1
    # The operator's own words reach the certificate rather than the word "scheduled".
    assert str(rows[0][0]) == "Client asked us to stop"


@pytest.mark.asyncio
async def test_a_restore_makes_the_sweep_a_no_op_even_after_the_date() -> None:
    """The undo and the sweep race on one column, and the undo wins by clearing it."""
    token, tenant_id = await _admin(), await _tenant()
    await _close(token, tenant_id, confirm=close_account_confirmation(tenant_id), grace_days=0)
    async with _client() as http:
        await http.delete(
            BASE.format(tenant_id=tenant_id), headers={"Authorization": f"Bearer {token}"}
        )

    await sweep_due_erasures({})

    async with tenant_session(tenant_id) as session:
        filed = (
            await session.execute(
                text("SELECT count(*) FROM tenant_erasure_requests WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
        ).scalar()
    assert filed == 0


@pytest.mark.asyncio
async def test_due_erasures_sees_across_tenants_and_only_on_the_directory_session() -> None:
    """The sweep's query MUST run on `admin_session()` — the one session that may
    enumerate `organizations`. A tenant-scoped session returns at most that one tenant,
    which is a silently under-swept hour; this pins the difference rather than trusting a
    comment."""
    token = await _admin()
    first, second = await _tenant(), await _tenant()
    for tenant_id in (first, second):
        await _close(token, tenant_id, confirm=close_account_confirmation(tenant_id), grace_days=0)

    async with admin_session() as directory:
        across = {row[0] for row in await closure.due_erasures(directory, limit=1000)}
    async with tenant_session(first) as scoped:
        scoped_only = {row[0] for row in await closure.due_erasures(scoped, limit=1000)}

    assert {first, second} <= across
    assert scoped_only == {first}


@pytest.mark.asyncio
async def test_the_erasure_date_can_only_be_brought_forward() -> None:
    """A client may ask us to erase sooner. Nobody may push the date out — a longer hold is
    retention we would have to justify under DPDP §8(7) and have no basis for."""
    token, tenant_id = await _admin(), await _tenant()
    await _close(token, tenant_id, confirm=close_account_confirmation(tenant_id))

    async with tenant_session(tenant_id) as session:
        original = (await closure.read_closure(session, tenant_id=tenant_id)).erase_after
        assert original is not None
        later = await closure.bring_erasure_forward(
            session, tenant_id=tenant_id, erase_after=original + timedelta(days=5)
        )
        assert later.erase_after == original

        sooner_at = datetime.now(UTC) + timedelta(days=1)
        sooner = await closure.bring_erasure_forward(
            session, tenant_id=tenant_id, erase_after=sooner_at
        )
    assert sooner.erase_after is not None
    assert sooner.erase_after < original


# --- another tenant's closure is not visible ------------------------------------------


@pytest.mark.asyncio
async def test_a_closure_read_cannot_reach_another_tenant() -> None:
    """Hard rule 1. `organizations`' policy matches on `id`, so a neighbour's row is
    invisible rather than merely filtered — and the surface that talks about a deletion
    answers 404 for it, the same answer a nonexistent id gets (D-65)."""
    neighbour = await _tenant()
    async with tenant_session(await _tenant()) as session:
        with pytest.raises(ProblemError) as refusal:
            await closure.read_closure(session, tenant_id=neighbour)
    assert refusal.value.status == 404


# --- re-sending an invitation ----------------------------------------------------------


async def _invite(token: str, tenant_id: UUID, email: str) -> UUID:
    async with _client() as http:
        response = await http.post(
            INVITES.format(tenant_id=tenant_id),
            json={"email": email, "role": "owner"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 201, response.text
    return UUID(str(response.json()["id"]))


async def _token_hash(invitation_id: UUID, tenant_id: UUID) -> str:
    async with tenant_session(tenant_id) as session:
        return str(
            (
                await session.execute(
                    text("SELECT token_hash FROM invitations WHERE id = :i"), {"i": invitation_id}
                )
            ).scalar()
        )


async def _age_last_send(invitation_id: UUID, tenant_id: UUID) -> None:
    """Move this row's last send back past the rate limit, so a test can exercise the NEXT
    send without sleeping through a two-minute floor."""
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE invitations SET last_sent_at = now() - interval '1 hour' WHERE id = :i"),
            {"i": invitation_id},
        )


@pytest.mark.asyncio
async def test_a_resend_rotates_the_token_so_the_previous_link_is_dead() -> None:
    """The security property is structural: one row, so two live keys to one account
    cannot exist, and the old link stops working in the statement that mints the new one."""
    token, tenant_id = await _admin(), await _tenant()
    invitation_id = await _invite(token, tenant_id, f"owner-{uuid.uuid4().hex[:8]}@clinic.example")
    before = await _token_hash(invitation_id, tenant_id)
    await _age_last_send(invitation_id, tenant_id)

    async with _client() as http:
        response = await http.post(
            f"{INVITES.format(tenant_id=tenant_id)}/{invitation_id}/resend",
            json={},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200, response.text
    assert response.json()["send_count"] == 2
    # The RAW token is never handed back to the sender (D-198) — only the mailbox has it.
    assert "token" not in response.json()

    after = await _token_hash(invitation_id, tenant_id)
    assert after != before
    # One row, still. A second live key for this account was never created.
    async with tenant_session(tenant_id) as session:
        live = (
            await session.execute(
                text(
                    "SELECT count(*) FROM invitations WHERE used_at IS NULL AND expires_at > now()"
                )
            )
        ).scalar()
    assert live == 1
    assert "admin.invitation_resent" in await _audit_actions(tenant_id)


@pytest.mark.asyncio
async def test_a_resend_is_rate_limited_on_the_database_s_own_clock() -> None:
    """Two clicks in a second is the motion this stops — and the check and the write are
    one statement, so the second click cannot walk through the gap."""
    token, tenant_id = await _admin(), await _tenant()
    invitation_id = await _invite(token, tenant_id, f"owner-{uuid.uuid4().hex[:8]}@clinic.example")

    async with _client() as http:
        response = await http.post(
            f"{INVITES.format(tenant_id=tenant_id)}/{invitation_id}/resend",
            json={},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 422
    assert _code(response) == "invitation_resend_too_soon"


@pytest.mark.asyncio
async def test_a_corrected_address_is_recorded_as_an_operator_attestation() -> None:
    """The founder's actual case: a client mistyped their address at signup and can receive
    NOTHING, so every self-service recovery is unreachable. An operator may re-point the
    invitation — and what goes in the audit row is that a PERSON vouched for the address,
    distinguishable from an address anybody verified."""
    token, tenant_id = await _admin(), await _tenant()
    invitation_id = await _invite(token, tenant_id, "typo@clinc.example")
    await _age_last_send(invitation_id, tenant_id)
    corrected = f"owner-{uuid.uuid4().hex[:8]}@clinic.example"

    async with _client() as http:
        response = await http.post(
            f"{INVITES.format(tenant_id=tenant_id)}/{invitation_id}/resend",
            json={"email": corrected, "attestation": "Confirmed by telephone with the owner"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200, response.text
    assert response.json()["email"] == corrected

    # THE ATTESTATION IS IN THE ACTION, WHICH IS THE HASH-CHAINED COLUMN. `audit_log` has
    # no `summary` column — a summary goes to the log stream — so a flag inside one would
    # not be in the record anybody later queries. `readdressed` says a person re-pointed
    # this invitation on their own word; a plain resend says nothing of the kind.
    assert "admin.invitation_readdressed" in await _audit_actions(tenant_id)
    assert "admin.invitation_resent" not in await _audit_actions(tenant_id)

    # AND IT IS NOT A VERIFICATION. Nothing about this marks the mailbox proved; that is
    # still one `email_verify` round trip the person completes themselves (D-185).
    async with untenanted_session() as session:
        verified = (
            await session.execute(
                text("SELECT count(*) FROM users WHERE lower(email) = lower(:e)"),
                {"e": corrected},
            )
        ).scalar()
    assert verified == 0


@pytest.mark.asyncio
async def test_a_corrected_address_must_say_how_it_was_established() -> None:
    """An attestation with no stated ground is a claim, not a record."""
    token, tenant_id = await _admin(), await _tenant()
    invitation_id = await _invite(token, tenant_id, "typo@clinc.example")
    await _age_last_send(invitation_id, tenant_id)

    async with _client() as http:
        response = await http.post(
            f"{INVITES.format(tenant_id=tenant_id)}/{invitation_id}/resend",
            json={"email": "right@clinic.example"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_a_redeemed_invitation_cannot_be_resent_or_re_addressed() -> None:
    """The moment somebody has redeemed it, the address is a LOGIN IDENTITY and changing
    it is a different act on a different surface. This route stops being reachable."""
    token, tenant_id = await _admin(), await _tenant()
    invitation_id = await _invite(token, tenant_id, f"owner-{uuid.uuid4().hex[:8]}@clinic.example")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE invitations SET used_at = now() WHERE id = :i"), {"i": invitation_id}
        )

    async with _client() as http:
        response = await http.post(
            f"{INVITES.format(tenant_id=tenant_id)}/{invitation_id}/resend",
            json={"email": "attacker@example.com", "attestation": "they asked me to"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_a_resend_is_refused_for_a_closed_account() -> None:
    """A resend is a MINT, and `assert_account_open` is the predicate at both ends of an
    invitation. Re-cutting a key to an account on a retention clock is what it stops."""
    token, tenant_id = await _admin(), await _tenant()
    invitation_id = await _invite(token, tenant_id, f"owner-{uuid.uuid4().hex[:8]}@clinic.example")
    await _age_last_send(invitation_id, tenant_id)
    await _close(token, tenant_id, confirm=close_account_confirmation(tenant_id))

    async with _client() as http:
        response = await http.post(
            f"{INVITES.format(tenant_id=tenant_id)}/{invitation_id}/resend",
            json={},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 409
    assert _code(response) == "account_closed"


@pytest.mark.asyncio
async def test_the_send_count_stops_the_button_being_used_as_a_relay() -> None:
    """Ten sends is evidence about the ADDRESS, not about the link. Past it the honest
    motion is a telephone call and a fresh invitation, so this refuses rather than
    throttling for ever."""
    token, tenant_id = await _admin(), await _tenant()
    invitation_id = await _invite(token, tenant_id, f"owner-{uuid.uuid4().hex[:8]}@clinic.example")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE invitations SET send_count = :n, "
                "last_sent_at = now() - interval '1 hour' WHERE id = :i"
            ),
            {"i": invitation_id, "n": admin_service.RESEND_MAX_SENDS},
        )

    async with _client() as http:
        response = await http.post(
            f"{INVITES.format(tenant_id=tenant_id)}/{invitation_id}/resend",
            json={},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 422
    assert _code(response) == "invitation_resend_exhausted"


@pytest.mark.asyncio
async def test_the_pending_list_says_when_the_link_was_last_sent_and_how_many_times() -> None:
    """The founder asked for both on screen. `invited_at` is the MINT and `last_sent_at`
    the SEND; after a resend they differ, and reading the wrong one tells an operator to
    wait when they need not."""
    token, tenant_id = await _admin(), await _tenant()
    invitation_id = await _invite(token, tenant_id, f"owner-{uuid.uuid4().hex[:8]}@clinic.example")
    await _age_last_send(invitation_id, tenant_id)
    async with _client() as http:
        await http.post(
            f"{INVITES.format(tenant_id=tenant_id)}/{invitation_id}/resend",
            json={},
            headers={"Authorization": f"Bearer {token}"},
        )
        listing = await http.get(
            INVITES.format(tenant_id=tenant_id), headers={"Authorization": f"Bearer {token}"}
        )

    assert listing.status_code == 200, listing.text
    row = next(item for item in listing.json() if item["id"] == str(invitation_id))
    assert row["send_count"] == 2
    assert row["last_sent_at"] > row["invited_at"]


# --- editing the client's own details --------------------------------------------------


async def _patch(token: str, tenant_id: UUID, body: dict[str, Any]) -> Any:
    async with _client() as http:
        return await http.patch(
            f"/v1/admin/tenants/{tenant_id}",
            json=body,
            headers={"Authorization": f"Bearer {token}"},
        )


@pytest.mark.asyncio
async def test_editing_a_client_s_name_audits_the_field_under_its_own_action() -> None:
    """One audit row PER FIELD, naming the field in the ACTION. `audit_log` has no payload
    column, so a single `organization.updated` row carrying the change inside a summary
    would put "who changed this client's details" outside the hash-chained record."""
    token, tenant_id = await _admin(), await _tenant()

    response = await _patch(token, tenant_id, {"name": "Renamed Clinic"})

    assert response.status_code == 200, response.text
    assert response.json()["changed"] == ["name"]
    assert "organization.name_changed" in await _audit_actions(tenant_id)

    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(
                text("SELECT name FROM organizations WHERE id = :t"), {"t": tenant_id}
            )
        ).scalar()
    assert stored == "Renamed Clinic"


@pytest.mark.asyncio
async def test_saving_an_unchanged_value_changes_nothing_and_writes_no_audit_row() -> None:
    """An operator opening a form and saving it must not grow the chain a row per click —
    the same rule `LifecycleOut.changed` states for the status switch."""
    token, tenant_id = await _admin(), await _tenant()

    response = await _patch(token, tenant_id, {"name": "Closing Clinic"})

    assert response.status_code == 200
    assert response.json()["changed"] == []
    assert "organization.name_changed" not in await _audit_actions(tenant_id)


@pytest.mark.asyncio
async def test_changing_the_notice_address_tells_the_address_being_replaced() -> None:
    """Re-pointing where an account's notices go is the shape of a channel takeover even
    though it grants nobody access — the credential is `users.email`, not this column. The
    OLD address is told and given a way to object, and the message goes THERE rather than
    to the new one, which is the only place it has no value."""
    token, tenant_id = await _admin(), await _tenant()

    response = await _patch(token, tenant_id, {"billing_email": "new-owner@clinic.example"})

    assert response.status_code == 200
    assert response.json()["changed"] == ["billing_email"]
    queued = await _outbox_jobs(tenant_id)
    assert [job["event"] for job in queued] == ["notice_address_changed"]
    # The REPLACED address, not the new one.
    assert queued[0]["to"] == "owner@clinic.example"
    assert "organization.billing_email_changed" in await _audit_actions(tenant_id)


@pytest.mark.asyncio
async def test_the_edit_cannot_reach_a_field_with_its_own_screen() -> None:
    """`extra="forbid"` and a two-field whitelist. A general-purpose PATCH over
    `organizations` would quietly become a second door to the lifecycle switch, the plan
    tier and the closure columns — each of which has its own permission and, for three of
    them, its own step-up."""
    token, tenant_id = await _admin(), await _tenant()

    for body in ({"status": "churned"}, {"plan_tier": "managed"}, {"slug": "hijacked"}):
        response = await _patch(token, tenant_id, body)
        assert response.status_code == 422, body

    async with tenant_session(tenant_id) as session:
        assert await account_stopped_blocker(session, tenant_id=tenant_id) is None


@pytest.mark.asyncio
async def test_an_empty_edit_is_refused_rather_than_silently_succeeding() -> None:
    token, tenant_id = await _admin(), await _tenant()
    assert (await _patch(token, tenant_id, {})).status_code == 422


@pytest.mark.asyncio
async def test_an_erased_client_s_details_cannot_be_edited() -> None:
    """Editing the contact details of a record that no longer describes anything — the
    certificate says the data is gone — is a change nobody can act on."""
    token, tenant_id = await _admin(), await _tenant()
    await _close(token, tenant_id, confirm=close_account_confirmation(tenant_id))
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET erase_after = NULL, deleted_at = now() WHERE id = :t"),
            {"t": tenant_id},
        )

    response = await _patch(token, tenant_id, {"name": "Ghost Clinic"})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_a_closed_client_s_details_can_still_be_corrected() -> None:
    """Deliberately allowed: an operator on the telephone with a departing client,
    correcting the address their closure notice goes to, is exactly the case."""
    token, tenant_id = await _admin(), await _tenant()
    await _close(token, tenant_id, confirm=close_account_confirmation(tenant_id))

    response = await _patch(token, tenant_id, {"billing_email": "accounts@clinic.example"})
    assert response.status_code == 200
    assert response.json()["changed"] == ["billing_email"]
