"""From "a founder signs a client" to "that client's agent is live" — the whole path,
over HTTP, as an operator walks it.

Every case here drives the real routes with real bearer tokens, because the three
defects it pins were invisible to a service-level test:

1. **The wizard's intake left `live_prompt_id` NULL.** `admin/intake.py` had its own
   copy of the `prompt_versions` INSERT and moved only `system_prompt_id`, so the
   invariant `agents/service.py` depends on — "`live_prompt_id IS NULL` can only mean
   the two pointers agree" — was false for every agent the wizard produced. Two
   consequences, in opposite directions: a freshly onboarded, freshly published agent
   told the CLIENT "Script v1 is waiting to go live" forever, about the very script the
   engine was running; and re-submitting the intake over a staged script edit published
   the OLD applied version while answering with the NEW version number.

2. **Publishing an agent with no script shipped a hardcoded English placeholder.** The
   wizard mints the receptionist row at step 1, before any prompt exists, and
   `_to_config` read `agent["prompt"] or "You are a helpful receptionist."`. Publish
   answered 200 `status: live`, wrote the routing row, and put a nine-word English
   sentence on a Telugu clinic's phone line.

3. **The admin invite path enforced neither of the client realm's two refusals**, so
   the wizard's Create-invite button, pressed twice, minted two live owner credentials
   for one account.

Concurrency: every case mints its own run-unique tenant and asserts only on rows it
created. Nothing here counts global rows.
"""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

from apps.api.admin import intake
from apps.api.admin import service as admin_service
from apps.api.agents import prompts
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine, reset_engine_cache
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

PUBLISH = "/v1/admin/tenants/{tenant_id}/agents/{agent_id}/publish"
INTAKE = "/v1/admin/tenants/{tenant_id}/agents/{agent_id}/intake"
PROMPT = "/v1/admin/tenants/{tenant_id}/agents/{agent_id}/prompt"
PENDING = "/v1/agents/{agent_id}/pending"
INVITE = "/v1/admin/tenants/{tenant_id}/invitations"
ACCEPT = "/v1/invitations/accept"

#: A clinic's answers, complete enough for `submission_blockers` to pass. Mundane on
#: purpose: every assertion looks for one of these strings arriving somewhere it could
#: only have reached through the intake.
FACTS: dict[str, Any] = {
    "business_hours": [
        {"day": "mon", "opens": "09:30", "closes": "18:00"},
        {"day": "sun", "closed": True},
    ],
    "branches": [{"label": "Main", "address": "14 Necklace Road, Hyderabad 500080"}],
    "services": [{"name": "Root canal", "price_inr": "8000"}],
    "faqs": [{"question": "Do you take insurance?", "answer": "Cashless with four insurers."}],
    "staff": [{"name": "Dr. Sowmya", "pronunciation": "సౌమ్య"}],
    "booking_rules": "Same-day slots close at 17:00.",
    "escalation_contacts": [{"name": "Reception", "phone_e164": "+919000000123"}],
    "languages": ["en-IN"],
}


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


async def _user(email: str) -> tuple[str, UUID]:
    """A provisioned client-realm identity with NO membership — what an invitee is."""
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:id, :email, now(), now())"
            ),
            {"id": user_id, "email": email},
        )
    return f"dev:client:{user_id}", user_id


async def _new_client(token: str) -> tuple[UUID, UUID, str]:
    """Wizard step 1, over HTTP. Returns (tenant_id, agent_id, slug)."""
    reset_engine_cache()
    slug = f"live-{uuid.uuid4().hex[:8]}"
    async with _client() as http:
        response = await http.post(
            "/v1/admin/tenants",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "name": "Necklace Road Dental",
                "slug": slug,
                "vertical_template": "clinic",
                "language": "te-IN",
            },
        )
    assert response.status_code == 201, response.text
    body = response.json()
    return UUID(body["id"]), UUID(body["agent_id"]), slug


async def _pointers(agent_id: UUID, tenant_id: UUID) -> tuple[int | None, int | None]:
    """(draft version, applied version) straight off the row."""
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT d.version, l.version FROM agents a "
                    "LEFT JOIN prompt_versions d ON d.id = a.system_prompt_id "
                    "LEFT JOIN prompt_versions l ON l.id = a.live_prompt_id "
                    "WHERE a.id = :aid"
                ),
                {"aid": agent_id},
            )
        ).first()
    assert row is not None
    return (row[0], row[1])


# =====================================================================================
# 1. The wizard produces an agent whose two pointers tell the truth
# =====================================================================================


async def test_a_freshly_onboarded_published_agent_reports_nothing_pending() -> None:
    """THE PHANTOM PENDING STATE, asserted where the client meets it.

    Wizard: create the client, submit the intake, publish. `publish_agent` sends
    `COALESCE(live_prompt_id, system_prompt_id)`, so the engine is running v1 — and the
    client's own agents screen must not tell them a script is waiting to go live.
    """
    token = await _admin()
    tenant_id, agent_id, slug = await _new_client(token)
    admin_headers = {"Authorization": f"Bearer {token}"}

    async with _client() as http:
        recorded = await http.post(
            INTAKE.format(tenant_id=tenant_id, agent_id=agent_id),
            headers=admin_headers,
            json=FACTS,
        )
        assert recorded.status_code == 200, recorded.text
        assert recorded.json()["prompt_version"] == 1
        assert recorded.json()["staged_behind_script"] is False, (
            "nothing was staged, so the facts apply immediately (SURFACES §2b training lane)"
        )

        published = await http.post(
            PUBLISH.format(tenant_id=tenant_id, agent_id=agent_id), headers=admin_headers
        )
        assert published.status_code == 200, published.text

    assert await _pointers(agent_id, tenant_id) == (1, 1), (
        "the applied pointer must name the version the engine was actually sent"
    )

    # The read the CLIENT makes, in the client realm, through their own membership.
    owner_token, owner_id = await _user(f"owner-{uuid.uuid4().hex[:8]}@example.com")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, 'owner', now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": owner_id},
        )
    async with _client() as http:
        state = await http.get(
            PENDING.format(agent_id=agent_id),
            headers={"Authorization": f"Bearer {owner_token}", "X-Org": slug},
        )
    assert state.status_code == 200, state.text
    assert state.json()["has_pending"] is False, (
        "the client was told a script was waiting to go live for the script the engine runs"
    )
    assert state.json()["pending"] == []


async def test_an_intake_over_a_staged_script_stages_with_it_and_says_so() -> None:
    """The second direction of the same defect, and the expensive one.

    A hand-written script edit on a LIVE agent is staged behind Apply. Re-submitting the
    intake used to mint a new DRAFT version and then publish — sending the version the
    APPLIED pointer still named, i.e. the old script — while answering with the new
    number. So an operator updating a client's prices saw `prompt_version: 3` and the
    engine got v1.
    """
    token = await _admin()
    tenant_id, agent_id, _slug = await _new_client(token)
    headers = {"Authorization": f"Bearer {token}"}

    async with _client() as http:
        await http.post(
            INTAKE.format(tenant_id=tenant_id, agent_id=agent_id), headers=headers, json=FACTS
        )
        ref = (
            await http.post(PUBLISH.format(tenant_id=tenant_id, agent_id=agent_id), headers=headers)
        ).json()["engine_agent_ref"]

        # A hand-written edit: staged, because the agent is live.
        staged = await http.post(
            PROMPT.format(tenant_id=tenant_id, agent_id=agent_id),
            headers=headers,
            json={
                "body": (
                    "[IDENTITY]\nYou are the receptionist.\n"
                    "[T0 FACTS]\nHours: mon 09:30-18:00\n"
                    "[TASK FLOW]\nAWAITING-REVIEW-SENTENCE\n"
                ),
            },
        )
        assert staged.status_code in (200, 201), staged.text
        assert await _pointers(agent_id, tenant_id) == (2, 1)

        # Now the facts change — a new price the client rang up about.
        moved = dict(FACTS, services=[{"name": "Root canal", "price_inr": "9500"}])
        again = await http.post(
            INTAKE.format(tenant_id=tenant_id, agent_id=agent_id), headers=headers, json=moved
        )

    assert again.status_code == 200, again.text
    assert again.json()["prompt_version"] == 3
    assert again.json()["staged_behind_script"] is True, (
        "the step must say the facts are held behind Apply rather than report a bare version"
    )
    assert await _pointers(agent_id, tenant_id) == (3, 1), "the applied pointer must not move"

    running = get_engine()._agents[ref].system_prompt  # type: ignore[attr-defined]
    assert "AWAITING-REVIEW-SENTENCE" not in running, (
        "the unapproved script must not have been dragged live by a facts submit"
    )
    assert "9500" not in running, "the new price is staged with the script, not published"
    assert "8000" in running, "callers still hear the applied version, unchanged"


# =====================================================================================
# 2. An agent with no script is not publishable
# =====================================================================================


async def test_publishing_an_agent_with_no_script_is_refused_not_placeholdered() -> None:
    """Wizard step 1 then Publish, skipping the intake.

    The refusal has to be visible at the ROUTE and total at the row: no engine ref, no
    routing row, still `draft`. A 200 here put "You are a helpful receptionist." — in
    English, with no hours, prices or business name — on a Telugu clinic's line, and
    every screen downstream then read `live`.
    """
    token = await _admin()
    tenant_id, agent_id, _slug = await _new_client(token)

    async with _client() as http:
        response = await http.post(
            PUBLISH.format(tenant_id=tenant_id, agent_id=agent_id),
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["type"].endswith("/agent_has_no_script")
    assert "intake" in body["remediation"], "the refusal names the step that fixes it"

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT status, engine_agent_ref FROM agents WHERE id = :aid"),
                {"aid": agent_id},
            )
        ).first()
        routes = (
            await session.execute(
                text("SELECT count(*) FROM engine_agent_routes WHERE agent_id = :aid"),
                {"aid": agent_id},
            )
        ).scalar()
    assert row == ("draft", None), "a refused publish must leave no trace of a live agent"
    assert routes == 0, "no routing row may exist for an agent that was never published"


async def test_the_same_agent_publishes_once_the_intake_has_given_it_a_script() -> None:
    """The refusal is a precondition, not a wall — the very next step clears it, and
    what reaches the engine is the CLIENT's script rather than any default of ours."""
    token = await _admin()
    tenant_id, agent_id, _slug = await _new_client(token)
    headers = {"Authorization": f"Bearer {token}"}

    async with _client() as http:
        await http.post(
            INTAKE.format(tenant_id=tenant_id, agent_id=agent_id), headers=headers, json=FACTS
        )
        response = await http.post(
            PUBLISH.format(tenant_id=tenant_id, agent_id=agent_id), headers=headers
        )

    assert response.status_code == 200, response.text
    ref = response.json()["engine_agent_ref"]
    running = get_engine()._agents[ref].system_prompt  # type: ignore[attr-defined]
    assert "14 Necklace Road, Hyderabad 500080" in running
    assert "You are a helpful receptionist." not in running, (
        "no placeholder may survive anywhere on the publish path"
    )


async def test_a_promptless_agent_of_another_tenant_is_absent_rather_than_refused() -> None:
    """D-65's discriminator on the publish path: an agent that is invisible answers
    404, not the business-rule refusal, which would confirm the id exists."""
    token = await _admin()
    tenant_id, _agent_id, _slug = await _new_client(token)
    _other_tenant, other_agent, _other_slug = await _new_client(token)

    async with _client() as http:
        response = await http.post(
            PUBLISH.format(tenant_id=tenant_id, agent_id=other_agent),
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 404, response.text
    assert "agent_has_no_script" not in response.text


# =====================================================================================
# 3. One rulebook for minting an invitation, whichever realm asks
# =====================================================================================


async def test_the_wizard_refuses_a_second_live_invitation_for_one_address() -> None:
    """Two presses of Create invite used to mean two live owner credentials for one
    client account, in one inbox, with only one of them revocable from the team list."""
    token = await _admin()
    tenant_id, _agent_id, _slug = await _new_client(token)
    headers = {"Authorization": f"Bearer {token}"}
    email = f"owner-{uuid.uuid4().hex[:8]}@example.com"

    async with _client() as http:
        first = await http.post(
            INVITE.format(tenant_id=tenant_id),
            headers=headers,
            json={"email": email, "role": "owner"},
        )
        second = await http.post(
            INVITE.format(tenant_id=tenant_id),
            headers=headers,
            json={"email": email, "role": "owner"},
        )

    assert first.status_code == 201, first.text
    assert second.status_code == 409, second.text
    assert second.json()["type"].endswith("/invitation_already_pending")

    async with tenant_session(tenant_id) as session:
        live = (
            await session.execute(
                text(
                    "SELECT count(*) FROM invitations WHERE lower(email) = lower(:e) "
                    "AND used_at IS NULL AND expires_at > now()"
                ),
                {"e": email},
            )
        ).scalar()
    assert live == 1, "exactly one key to this account may exist at a time"


async def test_the_wizard_refuses_inviting_somebody_already_on_the_account() -> None:
    """The other refusal the admin path did not have. Re-inviting a member mints a live
    credential that grants nothing new and revokes nothing old."""
    token = await _admin()
    tenant_id, _agent_id, _slug = await _new_client(token)
    email = f"owner-{uuid.uuid4().hex[:8]}@example.com"
    _owner_token, owner_id = await _user(email)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, 'owner', now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": owner_id},
        )

    async with _client() as http:
        response = await http.post(
            INVITE.format(tenant_id=tenant_id),
            headers={"Authorization": f"Bearer {token}"},
            json={"email": email, "role": "owner"},
        )

    assert response.status_code == 422, response.text
    assert response.json()["type"].endswith("/member_already_on_team")


async def test_a_members_email_on_another_account_does_not_block_this_ones_invite() -> None:
    """The refusals must be scoped to THIS tenant by RLS, not by an accident of the
    query. Otherwise "is this address already here" becomes a way to learn that an
    address exists on the platform at all."""
    token = await _admin()
    elsewhere, _a1, _s1 = await _new_client(token)
    here, _a2, _s2 = await _new_client(token)
    email = f"shared-{uuid.uuid4().hex[:8]}@example.com"
    _other_token, other_user = await _user(email)
    async with tenant_session(elsewhere) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, 'owner', now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": elsewhere, "uid": other_user},
        )

    async with _client() as http:
        response = await http.post(
            INVITE.format(tenant_id=here),
            headers={"Authorization": f"Bearer {token}"},
            json={"email": email, "role": "staff"},
        )

    assert response.status_code == 201, response.text


async def test_the_wizards_invitation_is_redeemable_and_lands_the_right_role() -> None:
    """FLOWS §1 step 8 end to end, across the realm boundary: an admin mints the token,
    the invitee redeems it in the CLIENT realm, and the membership that appears carries
    the role the operator chose."""
    token = await _admin()
    tenant_id, _agent_id, slug = await _new_client(token)
    email = f"owner-{uuid.uuid4().hex[:8]}@example.com"

    async with _client() as http:
        minted = await http.post(
            INVITE.format(tenant_id=tenant_id),
            headers={"Authorization": f"Bearer {token}"},
            json={"email": email, "role": "owner"},
        )
        assert minted.status_code == 201, minted.text
        owner_token, owner_id = await _user(email)
        accepted = await http.post(
            ACCEPT,
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"token": minted.json()["token"]},
        )

    assert accepted.status_code == 200, accepted.text
    assert accepted.json() == {"tenant_id": str(tenant_id), "slug": slug, "role": "owner"}

    async with tenant_session(tenant_id) as session:
        role = (
            await session.execute(
                text("SELECT role FROM memberships WHERE user_id = :u"), {"u": owner_id}
            )
        ).scalar()
    assert role == "owner"


# =====================================================================================
# 4. The invariant itself, stated once
# =====================================================================================


async def test_no_writer_of_a_prompt_version_can_leave_the_applied_pointer_null() -> None:
    """`agents/service.py` reads `COALESCE(live_prompt_id, system_prompt_id)` and says
    in as many words that NULL "can only mean the two pointers agree". That is a claim
    about every writer, so it is asserted against every writer there is — the wizard's
    intake, a hand-written version, and a T0 recompile — rather than about the one this
    change happened to touch.
    """
    token = await _admin()
    tenant_id, agent_id, _slug = await _new_client(token)

    async with tenant_session(tenant_id) as session:
        await intake.record_intake(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            facts=intake.IntakeFacts.model_validate(FACTS),
            recorded_by=None,
        )
        after_intake = (
            await session.execute(
                text("SELECT live_prompt_id IS NULL FROM agents WHERE id = :a"), {"a": agent_id}
            )
        ).scalar()
        assert after_intake is False, "the wizard's own writer must materialize it"

        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="[IDENTITY]\nA hand-written script.\n",
            notes=None,
            created_by=None,
        )
        still_set = (
            await session.execute(
                text("SELECT live_prompt_id IS NULL FROM agents WHERE id = :a"), {"a": agent_id}
            )
        ).scalar()
    assert still_set is False


def test_the_intake_mints_no_second_prompt_version_writer() -> None:
    """One statement may create a `prompt_versions` row (agents/prompts.py says so).

    The wizard's copy of that INSERT is what dropped the applied pointer, so its absence
    is the property — a future edit that reintroduces a local INSERT fails here rather
    than at a client's phone line six weeks later.
    """
    from pathlib import Path

    source = Path(intake.__file__).read_text(encoding="utf-8")
    assert "INSERT INTO prompt_versions" not in source, (
        "prompt versions are minted by agents/prompts.py::insert_prompt_version only"
    )
    assert "insert_prompt_version" in source


async def test_reopening_a_submitted_intake_and_saving_it_unchanged_mints_nothing() -> None:
    """FLOWS §1's "every step idempotent", and the unchanged branch's own report.

    An operator reopens step 3, reads it and presses submit. Nothing may be minted, the
    pointers may not move, and the answer must still carry `staged_behind_script` — the
    branch returns a different dict from the regenerated one, so a field added to only
    the busy half is a 500 on the wizard the first time somebody re-saves a form.
    """
    token = await _admin()
    tenant_id, agent_id, _slug = await _new_client(token)
    headers = {"Authorization": f"Bearer {token}"}

    async with _client() as http:
        await http.post(
            INTAKE.format(tenant_id=tenant_id, agent_id=agent_id), headers=headers, json=FACTS
        )
        await http.post(PUBLISH.format(tenant_id=tenant_id, agent_id=agent_id), headers=headers)
        again = await http.post(
            INTAKE.format(tenant_id=tenant_id, agent_id=agent_id), headers=headers, json=FACTS
        )

    assert again.status_code == 200, again.text
    body = again.json()
    assert body["regenerated"] is False, "the unchanged branch is the one under test here"
    assert body["prompt_version"] == 1
    assert body["kb_source_id"] is None
    assert body["staged_behind_script"] is False, (
        "the applied version carries these facts, so callers have them"
    )
    assert await _pointers(agent_id, tenant_id) == (1, 1), "nothing minted, nothing moved"


def test_admin_service_is_the_only_place_an_invitation_row_is_born() -> None:
    """The refusals moved to the INSERT precisely so no caller can skip them; a second
    INSERT anywhere would be a second rulebook again."""
    from pathlib import Path

    from apps.api.tenancy import members

    minting = [
        path
        for path in Path("apps/api").rglob("*.py")
        if "INSERT INTO invitations" in path.read_text(encoding="utf-8")
    ]
    assert [p.as_posix() for p in minting] == ["apps/api/admin/service.py"], minting
    assert "INSERT INTO invitations" not in Path(members.__file__).read_text(encoding="utf-8")
    assert admin_service.create_invitation.__module__ == "apps.api.admin.service"


async def test_the_console_can_cancel_the_invitation_it_just_issued() -> None:
    """The exit from the refusal above, which the refusal made necessary.

    "One live token per address" is right, and on its own it locks an operator whose
    first token was lost out of that address for 72 hours: the revoke that existed is
    client-realm, and the wizard's owner invite is minted before anybody can sign in, so
    nobody could press it. The admin-realm revoke is that control, and the property that
    matters is not that a row disappeared — it is that a FRESH invitation for the same
    address is then accepted.
    """
    token = await _admin()
    tenant_id, _agent_id, _slug = await _new_client(token)
    headers = {"Authorization": f"Bearer {token}"}
    email = f"owner-{uuid.uuid4().hex[:8]}@example.com"

    async with _client() as http:
        first = await http.post(
            INVITE.format(tenant_id=tenant_id),
            headers=headers,
            json={"email": email, "role": "owner"},
        )
        assert first.status_code == 201, first.text
        blocked = await http.post(
            INVITE.format(tenant_id=tenant_id),
            headers=headers,
            json={"email": email, "role": "owner"},
        )
        assert blocked.status_code == 409, blocked.text

        cancelled = await http.delete(
            f"{INVITE.format(tenant_id=tenant_id)}/{first.json()['id']}", headers=headers
        )
        assert cancelled.status_code == 204, cancelled.text

        reissued = await http.post(
            INVITE.format(tenant_id=tenant_id),
            headers=headers,
            json={"email": email, "role": "owner"},
        )

    assert reissued.status_code == 201, reissued.text
    assert reissued.json()["token"] != first.json()["token"]
    # And the cancelled one is dead, not merely superseded.
    owner_token, _owner_id = await _user(email)
    async with _client() as http:
        replay = await http.post(
            ACCEPT,
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"token": first.json()["token"]},
        )
    assert replay.status_code == 422, replay.text
    assert replay.json()["type"].endswith("/invitation_invalid")


async def test_an_accepted_invitation_cannot_be_cancelled_out_from_under_its_member() -> None:
    """`revoke_invitation`'s CAS is on `used_at IS NULL`, so a revoke that races an
    acceptance answers 404 and leaves the membership alone. Removing somebody who has
    joined is a different act on a different surface, and it must not be reachable by
    pressing Cancel on a link they already used."""
    token = await _admin()
    tenant_id, _agent_id, _slug = await _new_client(token)
    headers = {"Authorization": f"Bearer {token}"}
    email = f"owner-{uuid.uuid4().hex[:8]}@example.com"

    async with _client() as http:
        minted = await http.post(
            INVITE.format(tenant_id=tenant_id),
            headers=headers,
            json={"email": email, "role": "owner"},
        )
        owner_token, owner_id = await _user(email)
        await http.post(
            ACCEPT,
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"token": minted.json()["token"]},
        )
        late = await http.delete(
            f"{INVITE.format(tenant_id=tenant_id)}/{minted.json()['id']}", headers=headers
        )

    assert late.status_code == 404, late.text
    async with tenant_session(tenant_id) as session:
        still = (
            await session.execute(
                text("SELECT count(*) FROM memberships WHERE user_id = :u"), {"u": owner_id}
            )
        ).scalar()
    assert still == 1, "a late cancel must not remove a member"


async def test_one_tenants_invitation_is_not_cancellable_from_another_tenants_path() -> None:
    """RLS is the isolation and 404 is the answer (D-65): the revoke runs inside the
    named tenant's scope, so an id belonging to somebody else is invisible rather than
    confirmed to exist."""
    token = await _admin()
    owner_tenant, _a1, _s1 = await _new_client(token)
    other_tenant, _a2, _s2 = await _new_client(token)
    headers = {"Authorization": f"Bearer {token}"}
    email = f"owner-{uuid.uuid4().hex[:8]}@example.com"

    async with _client() as http:
        minted = await http.post(
            INVITE.format(tenant_id=owner_tenant),
            headers=headers,
            json={"email": email, "role": "owner"},
        )
        crossed = await http.delete(
            f"{INVITE.format(tenant_id=other_tenant)}/{minted.json()['id']}", headers=headers
        )

    assert crossed.status_code == 404, crossed.text
    async with tenant_session(owner_tenant) as session:
        alive = (
            await session.execute(
                text("SELECT count(*) FROM invitations WHERE id = :i"), {"i": minted.json()["id"]}
            )
        ).scalar()
    assert alive == 1, "the invitation must survive a cross-tenant cancel attempt"


async def test_the_console_lists_pending_invitations_masked_and_per_tenant() -> None:
    """What makes the duplicate refusal actionable when this session did not mint the
    first link. Two properties: the address is MASKED (it is `RAW_PII_FIELDS`, and an
    operator needs to recognise a row rather than read it), and the list is one tenant's.
    """
    token = await _admin()
    tenant_id, _agent_id, _slug = await _new_client(token)
    other_tenant, _a2, _s2 = await _new_client(token)
    headers = {"Authorization": f"Bearer {token}"}
    email = f"priya-{uuid.uuid4().hex[:8]}@clinic.example"

    async with _client() as http:
        minted = await http.post(
            INVITE.format(tenant_id=tenant_id),
            headers=headers,
            json={"email": email, "role": "owner"},
        )
        listed = await http.get(INVITE.format(tenant_id=tenant_id), headers=headers)
        elsewhere = await http.get(INVITE.format(tenant_id=other_tenant), headers=headers)

    assert listed.status_code == 200, listed.text
    rows = listed.json()
    assert [row["id"] for row in rows] == [minted.json()["id"]]
    assert rows[0]["role"] == "owner"
    assert email not in listed.text, "a raw address must never reach this response"
    assert rows[0]["email_masked"].startswith(email[0])
    assert rows[0]["email_masked"].endswith("@clinic.example")
    assert elsewhere.json() == [], "another account's keys are not this account's list"


async def test_the_pending_list_drops_an_invitation_once_it_is_redeemed() -> None:
    """ "Still redeemable" is the whole meaning of the list. A used invitation left on it
    is an operator cancelling a link that already became a membership — which the CAS
    refuses, so the row would sit there forever with a button that always fails."""
    token = await _admin()
    tenant_id, _agent_id, _slug = await _new_client(token)
    headers = {"Authorization": f"Bearer {token}"}
    email = f"owner-{uuid.uuid4().hex[:8]}@example.com"

    async with _client() as http:
        minted = await http.post(
            INVITE.format(tenant_id=tenant_id),
            headers=headers,
            json={"email": email, "role": "owner"},
        )
        assert (
            len((await http.get(INVITE.format(tenant_id=tenant_id), headers=headers)).json()) == 1
        )
        owner_token, _owner_id = await _user(email)
        await http.post(
            ACCEPT,
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"token": minted.json()["token"]},
        )
        after = await http.get(INVITE.format(tenant_id=tenant_id), headers=headers)

    assert after.json() == []
