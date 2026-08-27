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
        "reason": "the reason you are calling the clinic",
        "required": True,
    },
    {
        "key": "preferred_time",
        "label": "Preferred appointment time",
        "type": "text",
        "reason": "when you would like to come in",
        "required": False,
    },
]


async def _member(tenant_id: uuid.UUID, role: str = "owner") -> str:
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:id, :email, now(), now())"
            ),
            {"id": user_id, "email": f"notice-{user_id.hex[:12]}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, :role, now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id, "role": role},
        )
    return f"dev:client:{user_id}"


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


async def test_the_notice_does_not_promise_the_law_requires_the_ninety_days() -> None:
    """The floor is CALEVATE'S, and the notice a client publishes must say so.

    It read "Some records are kept longer where the law requires it: call recordings are
    kept for at least 90 days." No primary source for such a requirement exists —
    SEC-COMP §4 records that TRAI's 90-day figure is the opt-out cooling period and that
    the two-year commercial-records archive is Unified Licence clause 39.20, binding
    LICENSEES rather than a telemarketer — and the citation that justified it
    (LEGAL-SURFACE, "the playbook's 90-day minimum recording retention") pointed at a
    sentence the playbook does not contain. Retaining personal data on a legal basis that
    does not exist is itself the DPDP §8(7) breach, so the false attribution was the
    exposure, not the safeguard.

    Asserted in BOTH directions: the true statement present, the false one gone.
    """
    tenant_id, agent_id, _, _ = await _tenant()
    await _publish(tenant_id, agent_id)

    markdown = (await _draft(tenant_id)).markdown  # type: ignore[attr-defined]

    assert "kept longer where the law requires it" not in markdown
    assert "90 days" in markdown, "the floor itself is unchanged and still published"
    assert "Calevate applies to every account as a matter of its own policy" in markdown


async def test_the_notice_prints_no_period_for_the_record_nothing_expires() -> None:
    """`consent_log` has no timer, so the notice may not print one for it.

    The seed ships a `consent_log` retention row (2555 days) and the generator labelled
    it, so the draft said "The record of what you agreed to: 2555 days" — while
    `apps.workers.retention._apply_one` returns immediately for that category, and the
    same document says three lines later that the record "is kept as evidence". One
    notice, two answers, and the timed one was the false one.
    """
    tenant_id, agent_id, _, _ = await _tenant()
    await _publish(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        seeded = (
            await session.execute(
                text("SELECT ttl_days FROM retention_policies WHERE data_category = 'consent_log'")
            )
        ).scalar()
    assert seeded is not None, "the fixture must actually have the row that produced the defect"

    draft = await _draft(tenant_id)

    assert not [
        line
        for line in draft.retention  # type: ignore[attr-defined]
        if "agreed to" in line.what.lower()
    ]
    assert f"{int(seeded)} days" not in draft.markdown  # type: ignore[attr-defined]
    # The evidence sentence carries it instead, exactly as `/legal/privacy` §9 does.
    assert "kept as evidence" in draft.markdown  # type: ignore[attr-defined]


async def test_the_notice_offers_no_in_call_mechanism_it_does_not_have() -> None:
    """LEGAL-SURFACE DP-6: there is no correction path for a transcript or a recording,
    and voice-runtime has exactly ONE in-call tool — opt-out. The notice told callers
    "You can tell the assistant during a call" about all four rights, correction included.
    """
    tenant_id, agent_id, _, _ = await _tenant()
    await _publish(tenant_id, agent_id)

    markdown = (await _draft(tenant_id)).markdown  # type: ignore[attr-defined]

    assert "ask us to correct it" in markdown, "the RIGHT is statutory and stays stated"
    assert "including a correction, reaches us\nby contacting a person" in markdown.replace(
        "\r\n", "\n"
    )
    assert "Asking to stop being called is the one you can do on the call itself" in markdown


async def test_the_notice_does_not_condition_recording_on_a_switch_that_does_not_exist() -> None:
    """LEGAL-SURFACE F-14's exact sentence, corrected on `/legal/privacy` §4.1 and left
    alive in the generator. `agents` carries `ai_disclosure_enabled` and
    `recording_notice_enabled` and NO recording switch; what those toggle is the
    ANNOUNCEMENT. `calevate_shared.engine.TRUTHFUL_ANSWER_DIRECTIVE` records that nothing
    in this repository can turn a call's recording off.
    """
    tenant_id, agent_id, _, _ = await _tenant()
    await _publish(tenant_id, agent_id)

    markdown = (await _draft(tenant_id)).markdown  # type: ignore[attr-defined]

    assert "where recording is switched on for the agent" not in markdown
    assert "every call on this service is recorded" in markdown


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
                "reason": "the policy you are calling about",
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


def test_a_schema_row_this_version_cannot_read_is_skipped_rather_than_crashing() -> None:
    """The two skip branches in `_collected`, driven from both sides.

    They exist because `agents.extraction_schema` is JSON written by whatever version of
    this API stored it, and a Rule 3 notice generated by a `TypeError` is not a notice at
    all — the client's screen would fail instead of listing what they collect. So the
    module skips a row it cannot parse and logs it.

    **What must NOT happen is a silent omission**, and that is the half a test can pin:
    the readable siblings of an unreadable row still reach the list, so one bad row costs
    one line rather than the whole agent's schema. Both malformed shapes are asserted
    because they take different branches — a non-dict never reaches the model at all,
    while a dict missing a required field reaches it and is rejected by validation.
    """
    from apps.api.compliance.caller_notice import _INHERENT, _collected

    agents = [
        {
            "id": uuid.uuid4(),
            "fields": [
                "a bare string where a field object belongs",  # 201->202: not a dict
                {"label": "No key at all", "type": "text"},  # ExtractionField rejects it
                {"key": "nested", "label": "Also not a field", "type": ["not", "a", "type"]},
                FIELDS[0],
            ],
        }
    ]
    items = _collected(agents)

    labels = [item.what for item in items]
    assert labels[: len(_INHERENT)] == [what for what, _ in _INHERENT], (
        "the inherent lines are what a call produces regardless of schema and must survive"
    )
    assert labels[len(_INHERENT) :] == [FIELDS[0]["label"]], (
        "exactly the readable row is listed — three unreadable siblings cost three lines, "
        "not the agent's whole schema"
    )


def test_the_same_field_asked_for_by_two_agents_is_listed_once() -> None:
    """The dedupe is on the KEY, and first spelling wins — a receptionist and a follow-up
    campaign both asking "preferred time" is the ordinary case, and a notice listing it
    twice reads as two different collections of the same thing."""
    from apps.api.compliance.caller_notice import _collected

    restated = dict(FIELDS[1], label="When suits you", reason="a different sentence")
    items = _collected(
        [
            {"id": uuid.uuid4(), "fields": [FIELDS[1]]},
            {"id": uuid.uuid4(), "fields": [restated]},
        ]
    )

    matches = [
        item for item in items if item.why and item.what in {FIELDS[1]["label"], "When suits you"}
    ]
    assert len(matches) == 1, "one key, one line"
    assert matches[0].what == FIELDS[1]["label"], "first spelling wins"
