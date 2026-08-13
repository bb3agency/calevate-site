"""The half of FLOWS §1 the wizard promised and could not do: draft, and resume.

    Trigger: Sri opens Admin → New Client. Draft state saved at every step
    (resume anytime).

`admin.intake.save_intake_draft` existed with no route in front of it, so the only
reachable write ran `submission_blockers` first and REFUSED anything partial. An
operator halfway through a client's answers who closed the tab lost all of them, and
because nothing partial could be stored there was nothing partial to resume either.

What each test here pins, and why it is the weak point rather than the happy path:

1. **A partial intake persists and comes back.** The whole feature in one assertion:
   answers that would fail the submission gate go in, and the resume read returns them.
2. **A STRUCTURALLY invalid one is refused even as a draft.** This is the line the
   route is designed around. `read_intake` parses the stored sheet back through
   `IntakeFacts`, so a sheet accepted without validation returns `None` on the way out
   and the resume degrades to a BLANK FORM over stored answers — BUILD-LOG §52's defect
   with the operator's own retyping as the payload.
3. **A draft never satisfies the submission gate.** A save that quietly made an agent
   look ready would be worse than no draft at all: the next screen would offer to
   publish an agent that cannot say where the clinic is.
4. **The permission matches the rest of the wizard** — `agents:write`, read off the
   live route table rather than from the source.
5. **The resume list finds the account, and lets it go when it is finished.** A draft
   that can be written and not FOUND is resumable only from a tab that is still open.

CONCURRENCY: every case mints its own tenant and every assertion is filtered to it;
nothing here counts global rows, so this file runs beside the other suites on the
shared Postgres. D-22's rule about read permissions is asserted over the whole route
table by `tests/impersonation_reads_test.py`, which covers the new GET without an
exemption.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.admin import intake
from apps.api.admin import service as admin_service
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import iter_api_routes
from apps.api.db.session import admin_session, tenant_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

DRAFT_PATH = "/v1/admin/tenants/{tenant_id}/agents/{agent_id}/intake/draft"
INTAKE_PATH = "/v1/admin/tenants/{tenant_id}/agents/{agent_id}/intake"
UNFINISHED_PATH = "/v1/admin/onboarding/unfinished"

# What a wizard looks like ten minutes in: an address and one service, typed while the
# client was on the phone. Two of `submission_blockers`' four conditions are unanswered,
# which is the point — this body is exactly what the submit refuses.
PARTIAL: dict[str, Any] = {
    "branches": [{"label": "Main", "address": "12 MG Road, Ameerpet, Hyderabad 500016"}],
    "services": [{"name": "Root canal", "price_inr": "8000"}],
    "faqs": [],
    "staff": [],
    "booking_rules": "Same-day slots close at 17:00.",
    "business_hours": [],
    "escalation_contacts": [],
    "languages": ["te-IN", "en-IN"],
}


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name="Sunrise Dental",
        slug=f"draft-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return uuid.UUID(str(created["id"])), uuid.UUID(str(created["agent_id"]))


async def _operator_headers() -> dict[str, str]:
    """An admin-realm operator, which is the role the console runs as."""
    clerk_id = f"admin_{uuid.uuid4().hex[:12]}"
    async with admin_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, clerk_user_id, name, role, created_at, updated_at) "
                "VALUES (:id, :cid, 'Ops', 'operator', now(), now())"
            ),
            {"id": uuid.uuid4(), "cid": clerk_id},
        )
    return {"Authorization": f"Bearer dev:admin:{clerk_id}"}


# --------------------------------------------------------------- the draft write


@pytest.mark.asyncio
async def test_a_half_filled_intake_is_stored_and_comes_back_out() -> None:
    """The feature, end to end and through the routes an operator's browser uses."""
    tenant_id, agent_id = await _tenant()
    headers = await _operator_headers()
    path = {"tenant_id": tenant_id, "agent_id": agent_id}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        saved = await http.post(DRAFT_PATH.format(**path), json=PARTIAL, headers=headers)
        reopened = await http.get(INTAKE_PATH.format(**path), headers=headers)

    assert saved.status_code == 200, saved.text
    # The response says what is still missing, in the SERVER's codes — the same ones
    # `intake_incomplete` names later, so one condition is never explained twice.
    assert set(saved.json()["blockers"]) == {"business_hours_missing", "escalation_contact_missing"}

    assert reopened.status_code == 200, reopened.text
    state = reopened.json()
    assert state["prose_answers"]["branches"] == PARTIAL["branches"]
    assert state["prose_answers"]["services"] == [
        {"name": "Root canal", "price_inr": "8000", "notes": None}
    ]
    assert state["prose_answers"]["booking_rules"] == "Same-day slots close at 17:00."
    # Saved, and emphatically not submitted: the wizard tells "stored" from "live" by
    # exactly this pair, and a draft that reported a submit time would claim a compile
    # that never happened.
    assert state["saved_at"] is not None
    assert state["submitted_at"] is None
    # The two contract gaps this slice closed. Without `language_primary` the extras
    # list is unrenderable by any caller that did not just pick the primary itself;
    # `sheet_agent_id` is the provenance of the answers, which the path cannot tell you.
    assert state["language_primary"] == "te-IN"
    assert state["languages"] == ["en-IN"], "the primary is the EXTRAS' complement, not a member"
    assert state["sheet_agent_id"] == str(agent_id)


@pytest.mark.asyncio
async def test_a_structurally_invalid_draft_is_refused_and_stores_nothing() -> None:
    """The line: incompleteness is what a draft is FOR, malformation is not.

    A price of "₹8,000" and a phone number that is not E.164 are refused with the same
    422 the submit gives, because the sheet is read back through `IntakeFacts` on the
    way out — an unvalidated sheet returns `None` from `_sheet_answers` and the resume
    silently shows a blank form over stored answers.
    """
    tenant_id, agent_id = await _tenant()
    headers = await _operator_headers()
    path = {"tenant_id": tenant_id, "agent_id": agent_id}
    malformed = {
        **PARTIAL,
        "services": [{"name": "Root canal", "price_inr": "₹8,000"}],
        "escalation_contacts": [{"name": "Reception", "phone_e164": "9000000123"}],
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        refused = await http.post(DRAFT_PATH.format(**path), json=malformed, headers=headers)
        reopened = await http.get(INTAKE_PATH.format(**path), headers=headers)

    assert refused.status_code == 422, refused.text
    fields = {field["field"] for field in refused.json()["fields"]}
    assert "services.0.price_inr" in fields
    assert "escalation_contacts.0.phone_e164" in fields

    # Nothing was written — a partially-accepted malformed body is the same defect with
    # a nicer error message on top.
    assert reopened.json()["saved_at"] is None
    assert reopened.json()["prose_answers"] is None


@pytest.mark.asyncio
async def test_a_draft_never_makes_the_agent_look_ready() -> None:
    """Saving a draft must not move the submission gate, the prompt, or the KB.

    Three assertions because a draft could fake readiness three ways: by passing the
    gate, by leaving a compiled block behind, or by looking submitted to the screen that
    reads `submitted_at`.
    """
    tenant_id, agent_id = await _tenant()
    headers = await _operator_headers()
    path = {"tenant_id": tenant_id, "agent_id": agent_id}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        saved = await http.post(DRAFT_PATH.format(**path), json=PARTIAL, headers=headers)
        submitted = await http.post(INTAKE_PATH.format(**path), json=PARTIAL, headers=headers)
    assert saved.status_code == 200, saved.text

    assert submitted.status_code == 422, submitted.text
    # The code is the last segment of `type` (`core/errors.py`), which is what the
    # console switches on.
    assert submitted.json()["type"].endswith("/intake_incomplete"), submitted.text

    async with tenant_session(tenant_id) as session:
        state = await intake.read_intake(session, agent_id=agent_id)
        versions = (
            await session.execute(
                text("SELECT count(*) FROM prompt_versions WHERE agent_id = :aid"),
                {"aid": agent_id},
            )
        ).scalar()
        sources = (
            await session.execute(
                text("SELECT count(*) FROM kb_sources WHERE agent_id = :aid"), {"aid": agent_id}
            )
        ).scalar()
    assert state["submitted_at"] is None, "a draft is not a submit"
    assert state["compiled_t0_context"] is None, "a draft compiles nothing into the prompt"
    assert int(versions or 0) == 0, "a draft mints no prompt version"
    assert int(sources or 0) == 0, "a draft seeds no knowledge base"


@pytest.mark.asyncio
async def test_the_draft_write_carries_the_same_permission_as_the_rest_of_the_step() -> None:
    """Read off the LIVE route table: a permission asserted from the source is a
    restatement, and the thing that breaks is the declaration."""
    declared = {
        (route.path, method): (route.openapi_extra or {}).get("x-calevate-permission")
        for route in iter_api_routes(app)
        for method in route.methods
    }
    assert declared[(DRAFT_PATH, "POST")] == "agents:write"
    assert declared[(DRAFT_PATH, "POST")] == declared[(INTAKE_PATH, "POST")]
    # And the resume list is a READ, so it must not demand the authority to write —
    # `tests/impersonation_reads_test.py` asserts the rule over every GET; this names
    # the one this slice added.
    assert declared[(UNFINISHED_PATH, "GET")] == "org:read"


@pytest.mark.asyncio
async def test_the_draft_is_refused_on_another_tenants_agent() -> None:
    """The tenant is in the path and the work happens inside `tenant_session`, so an
    agent belonging to somebody else is invisible rather than writable."""
    _, other_agent = await _tenant()
    tenant_id, _ = await _tenant()
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as refused:
            await intake.save_intake_draft(
                session,
                tenant_id=tenant_id,
                agent_id=other_agent,
                facts=intake.IntakeFacts(booking_rules="not yours"),
            )
    assert refused.value.status == 404


# ------------------------------------------------------------------ resuming it


@pytest.mark.asyncio
async def test_an_unfinished_onboarding_is_findable_and_says_where_to_resume() -> None:
    tenant_id, agent_id = await _tenant()
    headers = await _operator_headers()
    path = {"tenant_id": tenant_id, "agent_id": agent_id}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        await http.post(DRAFT_PATH.format(**path), json=PARTIAL, headers=headers)
        listed = await http.get(UNFINISHED_PATH, headers=headers)

    assert listed.status_code == 200, listed.text
    mine = [row for row in listed.json() if row["tenant_id"] == str(tenant_id)]
    assert len(mine) == 1, "the account whose draft was just saved is not on the resume list"
    row = mine[0]
    # The ids the wizard resumes WITH, and the evidence for the word "unfinished".
    assert row["agent_id"] == str(agent_id)
    assert row["draft_saved_at"] is not None
    assert set(row["blockers"]) == {"business_hours_missing", "escalation_contact_missing"}
    # The account, never anyone at it: no phone number, no answers, no billing email.
    assert set(row) == {
        "tenant_id",
        "name",
        "slug",
        "agent_id",
        "created_at",
        "draft_saved_at",
        "blockers",
    }


@pytest.mark.asyncio
async def test_an_account_created_and_never_opened_is_unfinished_too() -> None:
    """`draft_saved_at: null` is a state, not a missing value.

    An account created at the end of a call and never returned to is the most easily
    lost onboarding there is, and it has no sheet to be found by. It is listed with
    every blocker standing, because that is true.
    """
    tenant_id, agent_id = await _tenant()
    headers = await _operator_headers()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        listed = await http.get(UNFINISHED_PATH, headers=headers)

    row = next(row for row in listed.json() if row["tenant_id"] == str(tenant_id))
    assert row["draft_saved_at"] is None
    assert row["agent_id"] == str(agent_id), "the draft receptionist is where it resumes"
    assert set(row["blockers"]) == {
        "business_hours_missing",
        "branch_missing",
        "service_missing",
        "escalation_contact_missing",
    }


@pytest.mark.asyncio
async def test_a_submitted_intake_leaves_the_list() -> None:
    """The other half of the property: a list that never lets go is a list nobody
    trusts, and "unfinished" would slowly come to mean "exists"."""
    tenant_id, agent_id = await _tenant()
    headers = await _operator_headers()
    path = {"tenant_id": tenant_id, "agent_id": agent_id}
    complete = {
        **PARTIAL,
        "business_hours": [{"day": "mon", "opens": "09:30", "closes": "18:00"}],
        "escalation_contacts": [{"name": "Reception", "phone_e164": "+919000000123"}],
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        await http.post(DRAFT_PATH.format(**path), json=PARTIAL, headers=headers)
        before = await http.get(UNFINISHED_PATH, headers=headers)
        submitted = await http.post(INTAKE_PATH.format(**path), json=complete, headers=headers)
        after = await http.get(UNFINISHED_PATH, headers=headers)

    assert submitted.status_code == 200, submitted.text
    assert any(row["tenant_id"] == str(tenant_id) for row in before.json())
    assert not any(row["tenant_id"] == str(tenant_id) for row in after.json())
