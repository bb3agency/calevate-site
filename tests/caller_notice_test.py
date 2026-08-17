"""The draft notice a client owes their own callers (LEGAL-SURFACE F-8, D-179).

DPDP Rule 3 requires an ITEMISED description of the personal data a Data Fiduciary
collects. For a Calevate client that list is their extraction schema, their retention
settings and their announcement settings — every one of which lives in our database and
nowhere else. Before this, a client who had to give their callers a notice reconstructed
it by hand off screens never designed to be read that way, and the itemisation is exactly
the part a hand-written reconstruction gets wrong.

These tests hold the draft to the two properties that make it worth generating at all:

1. **It is accurate about THIS tenant** — their fields, their periods, their switches —
   because a generated notice that is merely plausible is worse than none: the client
   publishes it believing it was derived from their configuration.
2. **It never becomes our legal advice, and it never over-claims.** The disclaimer travels
   with the text, the blanks only the client can fill are visible as blanks, and an agent
   whose AI announcement is switched OFF changes what the draft says rather than being
   quietly absorbed.
"""

from __future__ import annotations

import json
import uuid

from apps.api.admin import service as admin_service
from apps.api.compliance.caller_notice import DRAFT_WARNING, build_caller_notice
from apps.api.compliance.caller_notice_routes import router as caller_notice_router
from apps.api.core.errors import install_error_handlers
from apps.api.db.session import tenant_session, untenanted_session
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

BASE = "/v1/compliance/caller-notice"

FIELDS = [
    {
        "key": "symptom",
        "label": "What is wrong",
        "type": "text",
        "description": "the reason you are calling the clinic",
        "required": True,
    },
    {
        "key": "preferred_time",
        "label": "Preferred appointment time",
        "type": "text",
        "description": "when you would like to come in",
        "required": False,
    },
]


async def _member(tenant_id: uuid.UUID, role: str = "owner") -> str:
    user_id = uuid.uuid4()
    clerk_id = f"user_{uuid.uuid4().hex[:12]}"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, clerk_user_id, email, created_at, updated_at) "
                "VALUES (:id, :cid, :email, now(), now())"
            ),
            {"id": user_id, "cid": clerk_id, "email": f"{clerk_id}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, :role, now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id, "role": role},
        )
    return f"dev:client:{clerk_id}"


async def _tenant() -> tuple[uuid.UUID, uuid.UUID, str, str]:
    created = await admin_service.create_organization(
        name="Notice Clinic",
        slug=f"ntc-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id, slug = created["id"], created["agent_id"], created["slug"]
    return tenant_id, agent_id, str(slug), await _member(tenant_id)


async def _publish(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    fields: list[dict[str, object]] | None = None,
    ai_disclosure: bool = True,
    recording_notice: bool = True,
    direction: str = "inbound",
) -> None:
    """Put the agent in the state a caller can actually reach, with a schema attached."""
    schema_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO extraction_schemas (id, tenant_id, agent_id, version, fields, "
                "published_at, created_at, updated_at) VALUES (:i, :t, :a, "
                "(SELECT coalesce(max(version), 0) + 1 FROM extraction_schemas WHERE "
                "agent_id = :a), CAST(:f AS jsonb), now(), now(), now())"
            ),
            {"i": schema_id, "t": tenant_id, "a": agent_id, "f": json.dumps(fields or FIELDS)},
        )
        await session.execute(
            text(
                "UPDATE agents SET status = 'live', extraction_schema_id = :s, "
                "ai_disclosure_enabled = :ai, recording_notice_enabled = :rec, "
                "direction = :dir, updated_at = now() WHERE id = :a"
            ),
            {
                "s": schema_id,
                "ai": ai_disclosure,
                "rec": recording_notice,
                "dir": direction,
                "a": agent_id,
            },
        )


async def _draft(tenant_id: uuid.UUID) -> object:
    async with tenant_session(tenant_id) as session:
        return await build_caller_notice(session, tenant_id=tenant_id)


def _app() -> FastAPI:
    application = FastAPI()
    install_error_handlers(application)
    application.include_router(caller_notice_router)
    return application


# ------------------------------------------------------------------ 1. it is accurate


async def test_the_itemised_list_is_this_tenants_own_extraction_schema() -> None:
    """The whole reason the product has to generate this: the itemisation Rule 3 asks for
    IS the client's field list, and the client cannot see it as a list anywhere else."""
    tenant_id, agent_id, _, _ = await _tenant()
    await _publish(tenant_id, agent_id)

    draft = await _draft(tenant_id)

    labels = [item.what for item in draft.collected]  # type: ignore[attr-defined]
    assert "What is wrong" in labels
    assert "Preferred appointment time" in labels
    # And the things a phone call collects whatever the schema says — a client whose
    # schema is empty still records the number, the audio and the transcript.
    assert "Your phone number" in labels
    assert "A recording of the call" in labels
    assert "A transcript of the call" in labels


async def test_a_field_two_agents_both_capture_is_listed_once() -> None:
    """A receptionist and a follow-up campaign both ask for a callback time. Listing it
    twice would read as two different collections of the same thing."""
    tenant_id, agent_id, _, _ = await _tenant()
    await _publish(tenant_id, agent_id)
    second = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO agents (id, tenant_id, name, direction, language_primary, "
                "disclosure_line, ai_disclosure_line, recording_notice_line, status, engine, "
                "created_at, updated_at) VALUES (:i, :t, 'Follow-up', 'outbound', 'te-IN', "
                "'This is an AI assistant.', 'This is an AI assistant.', "
                "'This call is recorded.', 'draft', 'fake', now(), now())"
            ),
            {"i": second, "t": tenant_id},
        )
    await _publish(tenant_id, second, direction="outbound")

    draft = await _draft(tenant_id)

    labels = [item.what for item in draft.collected]  # type: ignore[attr-defined]
    assert labels.count("Preferred appointment time") == 1


async def test_the_periods_are_the_tenants_own_retention_rows() -> None:
    """A notice that printed our defaults at a client who has negotiated their own would
    be telling that client's callers something false about their own data."""
    tenant_id, agent_id, _, _ = await _tenant()
    await _publish(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE retention_policies SET ttl_days = 200 WHERE data_category = 'recording'")
        )

    draft = await _draft(tenant_id)

    recording = [line for line in draft.retention if "recording" in line.what.lower()]  # type: ignore[attr-defined]
    assert len(recording) == 1
    assert recording[0].days == 200
    assert "200 days" in draft.markdown  # type: ignore[attr-defined]


async def test_a_draft_ignores_another_tenants_configuration() -> None:
    """Hard rule 1. The generator carries no `tenant_id` predicate — RLS is the isolation
    — and a leak here would publish one business's field list on another's website."""
    mine, my_agent, _, _ = await _tenant()
    theirs, their_agent, _, _ = await _tenant()
    await _publish(mine, my_agent)
    await _publish(
        theirs,
        their_agent,
        fields=[
            {
                "key": "policy_number",
                "label": "Your insurance policy number",
                "type": "text",
                "description": "the policy you are calling about",
                "required": True,
            }
        ],
    )

    draft = await _draft(mine)

    assert "Your insurance policy number" not in draft.markdown  # type: ignore[attr-defined]


async def test_an_unpublished_agent_contributes_nothing() -> None:
    """A draft agent takes no calls, so its fields are collected from nobody. Listing them
    would make the notice claim more than the business does."""
    tenant_id, agent_id, _, _ = await _tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET status = 'draft' WHERE id = :a"), {"a": agent_id}
        )

    draft = await _draft(tenant_id)

    labels = [item.what for item in draft.collected]  # type: ignore[attr-defined]
    assert "What is wrong" not in labels
    # But the account still gets a usable draft: "you have not launched yet" is not an
    # answer to "what will I be collecting?", which is the question the wizard asks.
    assert "Your phone number" in labels
    assert draft.markdown  # type: ignore[attr-defined]


# ------------------------------------------------- 2. it does not over-claim, ever


async def test_the_draft_says_the_announcement_is_made_when_it_is() -> None:
    tenant_id, agent_id, _, _ = await _tenant()
    await _publish(tenant_id, agent_id, ai_disclosure=True, recording_notice=True)

    draft = await _draft(tenant_id)

    assert draft.ai_disclosure_off == []  # type: ignore[attr-defined]
    assert "says at the start of the call that it is an AI assistant" in draft.markdown  # type: ignore[attr-defined]


async def test_an_agent_with_the_ai_announcement_off_changes_what_the_draft_says() -> None:
    """The dangerous case, and the reason this is generated rather than templated.

    D-163 made the AI disclosure a per-agent toggle. With it off the agent does not
    VOLUNTEER that it is an AI, so the obligation moves into the client's own written
    notice — and a draft that assumed the announcement is made would hand them a document
    asserting something their agent does not do.
    """
    tenant_id, agent_id, _, _ = await _tenant()
    await _publish(tenant_id, agent_id, ai_disclosure=False)

    draft = await _draft(tenant_id)

    assert draft.ai_disclosure_off, "the agent with the announcement off was not named"  # type: ignore[attr-defined]
    assert "says at the start of the call that it is an AI assistant" not in draft.markdown  # type: ignore[attr-defined]
    assert "you may be speaking to an AI assistant rather than a person" in draft.markdown  # type: ignore[attr-defined]
    # And the client is told this notice now carries the weight, as a task.
    assert any("only place your callers are told" in q for q in draft.open_questions)  # type: ignore[attr-defined]


async def test_the_draft_states_the_truthful_answer_floor_whatever_the_switches_say() -> None:
    """Hard rule 5: the ANSWER is not a toggle. It is enforced server-side above the
    tenant prompt, so it is a property of the platform the client may rely on in writing —
    and with both announcements off it is the only thing left that is unconditional."""
    tenant_id, agent_id, _, _ = await _tenant()
    await _publish(tenant_id, agent_id, ai_disclosure=False, recording_notice=False)

    draft = await _draft(tenant_id)

    assert "it will tell you the truth" in draft.markdown  # type: ignore[attr-defined]
    assert "cannot be switched off" in draft.markdown  # type: ignore[attr-defined]


async def test_the_disclaimer_travels_with_the_text_and_the_blanks_are_visible() -> None:
    """A disclaimer only in the API envelope does not survive the copy-paste that is the
    entire point of the feature, and a blank that reads like prose gets published."""
    tenant_id, agent_id, _, _ = await _tenant()
    await _publish(tenant_id, agent_id)

    draft = await _draft(tenant_id)

    assert DRAFT_WARNING in draft.markdown  # type: ignore[attr-defined]
    assert "not legal advice" in draft.markdown  # type: ignore[attr-defined]
    assert "{{YOUR REGISTERED BUSINESS NAME}}" in draft.markdown  # type: ignore[attr-defined]
    assert "{{YOUR CONTACT FOR DATA QUESTIONS" in draft.markdown  # type: ignore[attr-defined]
    assert any("advocate" in question for question in draft.open_questions)  # type: ignore[attr-defined]


async def test_the_draft_contains_no_callers_data() -> None:
    """Hard rule 6 at the artifact. The draft is a document about what is collected, and
    a client pastes it on a public website: a single caller's number or a sample value in
    it would be a disclosure, not an example."""
    tenant_id, agent_id, _, _ = await _tenant()
    await _publish(tenant_id, agent_id)
    phone = f"+9198765{uuid.uuid4().int % 100000:05d}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status, "
                "data, created_at, updated_at) VALUES (:i, :t, :a, :p, 'Ravi', 'inbound_call', "
                "'new', CAST(:d AS jsonb), now(), now())"
            ),
            {
                "i": uuid.uuid4(),
                "t": tenant_id,
                "a": agent_id,
                "p": phone,
                "d": json.dumps({"symptom": "chest pain"}),
            },
        )

    draft = await _draft(tenant_id)

    assert phone not in draft.markdown  # type: ignore[attr-defined]
    assert "chest pain" not in draft.markdown  # type: ignore[attr-defined]
    assert "Ravi" not in draft.markdown  # type: ignore[attr-defined]


# ------------------------------------------------------------------ 3. the surface


async def test_the_route_serves_the_draft_to_a_member_of_the_account() -> None:
    tenant_id, agent_id, slug, token = await _tenant()
    await _publish(tenant_id, agent_id)

    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://api") as http:
        response = await http.get(
            BASE, headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["disclaimer"] == DRAFT_WARNING
    assert any(item["what"] == "What is wrong" for item in body["collected"])
    assert body["retention"], "the account's own periods are missing from the response"
    assert "not legal advice" in body["notice_markdown"]


async def test_the_route_refuses_an_anonymous_caller() -> None:
    """It discloses the account's whole collection surface, which is a client-realm read
    even though nothing in it is a caller's data."""
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://api") as http:
        response = await http.get(BASE)

    assert response.status_code in (401, 403), response.text
