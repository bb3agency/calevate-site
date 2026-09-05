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


async def _tenant(vertical: str = "real_estate") -> tuple[uuid.UUID, uuid.UUID, str, str]:
    """A tenant, its first agent, its slug and an owner token.

    `real_estate` and no longer `clinic` (D-507(b)): a clinic may not remember its callers
    at all, so every cross-call-memory test in this file would have been asserting against
    a tenant whose agents can never remember anybody — passing for the wrong reason. The
    refusal tests ask for the clinic by name.
    """
    created = await admin_service.create_organization(
        name="Notice Estates",
        slug=f"ntc-{uuid.uuid4().hex[:8]}",
        vertical_template=vertical,
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
                "disclosure_line, ai_disclosure_line, recording_notice_line, "
                "caller_memory_notice_line, status, engine, created_at, updated_at) VALUES (:i, "
                ":t, 'Follow-up', 'outbound', 'te-IN', 'This is an AI assistant.', 'This is an "
                "AI assistant.', 'This call is recorded.', 'I keep a short note of what you ask "
                "about.', 'draft', 'fake', now(), now())"
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
            # Spelled out rather than omitted: `_collected` reads it with `[]` and not
            # `.get(..., False)` on purpose, because a KeyError is a loud bug and a
            # defaulted False is a notice that silently omits a real collection — the
            # under-disclosure direction Rule 3 is about (D-506).
            "caller_memory_enabled": False,
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
            {"id": uuid.uuid4(), "caller_memory_enabled": False, "fields": [FIELDS[1]]},
            {"id": uuid.uuid4(), "caller_memory_enabled": False, "fields": [restated]},
        ]
    )

    matches = [
        item for item in items if item.why and item.what in {FIELDS[1]["label"], "When suits you"}
    ]
    assert len(matches) == 1, "one key, one line"
    assert matches[0].what == FIELDS[1]["label"], "first spelling wins"


# ─────────────────── cross-call caller memory (D-506) ───────────────────
#
# The notice question this whole feature turns on: a caller who is REMEMBERED ACROSS CALLS
# is a materially different privacy proposition from one who is not, and DPDP §5 with
# Rule 3 wants the itemised list BEFORE the processing. The draft is the only channel this
# product has that can say it — the two spoken sentences are about being an AI and being
# recorded — so the draft has to say it exactly when it is true and never when it is not.


async def _remember_callers(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET caller_memory_enabled = true WHERE id = :a"), {"a": agent_id}
        )


async def test_a_client_who_does_not_remember_callers_says_nothing_about_it() -> None:
    """THE DEFAULT, and the one every client is on today. A notice that mentioned memory
    where there is none would over-disclose, which is its own defect: a caller reading it
    would decline something that is not happening."""
    tenant_id, agent_id, _, _ = await _tenant()
    await _publish(tenant_id, agent_id)

    draft = await _draft(tenant_id)

    assert draft.caller_memory_on == []  # type: ignore[attr-defined]
    markdown = draft.markdown  # type: ignore[attr-defined]
    assert "If you have called us before" not in markdown
    assert "keeps a short note" not in markdown
    # And nothing in the account of what the caller HEARS, either: the third spoken
    # sentence (D-507) exists only where memory does, so a draft that described it here
    # would be telling a client their agents say something they do not say.
    assert "keep notes about you between calls" not in markdown
    # NOR A PERIOD FOR IT. `scripts/seed.py` writes a `caller_memory` retention row for
    # every organisation, so the row exists on this account and says nothing about this
    # account: printing "The short note of what you asked about: 180 days" here would
    # tell a caller how long notes are kept about them by a business that keeps none.
    assert "The short note of what you asked about" not in markdown
    assert draft.memory_retention_days is None  # type: ignore[attr-defined]
    assert not [
        line
        for line in draft.retention  # type: ignore[attr-defined]
        if "short note" in line.what
    ]


async def test_remembering_callers_is_itemised_and_named() -> None:
    """Rule 3 asks for an ITEMISED list, so the note joins the list — and the agent is
    NAMED, like a switched-off disclosure is, because a business running a receptionist
    that remembers and a campaign that does not is telling its callers two different
    things."""
    tenant_id, agent_id, _, _ = await _tenant()
    await _publish(tenant_id, agent_id)
    await _remember_callers(tenant_id, agent_id)

    draft = await _draft(tenant_id)

    assert len(draft.caller_memory_on) == 1  # type: ignore[attr-defined]
    labels = [item.what for item in draft.collected]  # type: ignore[attr-defined]
    assert any("kept after the call ends" in label for label in labels)
    markdown = draft.markdown  # type: ignore[attr-defined]
    assert "If you have called us before" in markdown
    assert draft.caller_memory_on[0] in markdown  # type: ignore[attr-defined]
    # THE ITEM AND ITS PERIOD TRAVEL TOGETHER. An itemised collection with no period
    # against it is the half of Rule 3 a generated draft is most likely to drop, because
    # nothing raises when a category label is missing from a filtered map — the list just
    # comes back one line shorter and reads as complete.
    days = draft.memory_retention_days  # type: ignore[attr-defined]
    assert days is not None
    assert f"The short note of what you asked about: {days} days" in markdown


async def test_the_draft_says_it_is_a_note_of_the_subject_and_not_a_transcript() -> None:
    """The distinction the whole privacy argument rests on. A caller told "we keep notes"
    imagines a recording; the honest sentence says which of the two it is, and the store
    is built so the sentence stays true (`caller_memories.fact` is capped at a short
    sentence and holds a distilled subject, never a quote)."""
    tenant_id, agent_id, _, _ = await _tenant()
    await _publish(tenant_id, agent_id)
    await _remember_callers(tenant_id, agent_id)

    markdown = (await _draft(tenant_id)).markdown  # type: ignore[attr-defined]

    assert "not a recording or a transcript of what you said" in markdown


async def test_remembering_callers_puts_a_question_in_front_of_counsel_first() -> None:
    """The one open question on this list that is not "fill in a fact about yourself" — it
    asks whether the client may lawfully do a thing they have already switched on, which is
    why it goes FIRST. It names the two sub-questions the founder's own decision (D-506)
    turns on: whether writing it down is enough for an inbound caller who never saw the
    page, and whether a note could be sensitive information."""
    tenant_id, agent_id, _, _ = await _tenant()
    await _publish(tenant_id, agent_id)
    await _remember_callers(tenant_id, agent_id)

    questions = (await _draft(tenant_id)).open_questions  # type: ignore[attr-defined]

    assert "BETWEEN calls" in questions[0]
    assert "never sees this page" in questions[0]
    assert "sensitive" in questions[0]


async def test_the_spoken_account_includes_the_memory_sentence_and_no_third_toggle() -> None:
    """D-507(a): the agent SAYS it, so the draft's account of what is spoken must say so.

    The draft's "Being told what you are speaking to" section is what a caller reads to
    know what they will hear. Until D-507 there was nothing to hear about memory — the
    draft was the only channel, which is precisely why an INBOUND caller (who has visited
    no website and agreed to no page) was the hole in it. Now `compose_opening_line`
    appends `agents.caller_memory_notice_line` third.

    AND IT MUST NOT READ AS A THIRD SWITCH. `ai_disclosure_enabled` and
    `recording_notice_enabled` are per-agent toggles because both obligations hold whatever
    this product does; the memory sentence has NO flag of its own, because memory exists
    only where `caller_memory_enabled` is on. A draft implying a third control would send a
    client looking for one in a screen that has none — and support would eventually invent
    an answer.
    """
    tenant_id, agent_id, _, _ = await _tenant()
    await _publish(tenant_id, agent_id)
    await _remember_callers(tenant_id, agent_id)

    draft = await _draft(tenant_id)
    markdown = draft.markdown  # type: ignore[attr-defined]
    spoken = markdown.split("## What we collect")[0]

    assert "keep notes about you between calls also say so at the start of the call" in spoken
    assert draft.caller_memory_on[0] in spoken  # type: ignore[attr-defined]
    assert "there is no separate setting for it" in spoken
    # The floor is untouched by the new sentence and still stated unconditionally.
    assert "it will tell you the truth" in markdown


async def test_the_notes_are_given_their_own_period_and_not_the_transcripts() -> None:
    """D-507(c) moved caller memory off the transcript clock onto its own 180-day one, and
    this draft said "kept for the same period as the transcript above" until it did. For a
    tenant on the 365-day transcript default that sentence over-stated the period by half a
    year — in a document the client publishes as their own statement of fact.

    The period is read from the tenant's OWN `caller_memory` retention row, like every
    other period in this document, and asserted against a value this test moves so it
    cannot pass off a hard-coded 180.
    """
    tenant_id, agent_id, _, _ = await _tenant()
    await _publish(tenant_id, agent_id)
    await _remember_callers(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE retention_policies SET ttl_days = 120 WHERE data_category = 'caller_memory'"
            )
        )

    draft = await _draft(tenant_id)

    assert draft.memory_retention_days == 120  # type: ignore[attr-defined]
    markdown = draft.markdown  # type: ignore[attr-defined]
    assert "kept for 120 days after the call it was taken on" in markdown
    assert "the same period as the transcript" not in markdown
    # And it is on the itemised "How long we keep it" list too, from the same row: a
    # caller reading the periods should not find every category but the one collection
    # the business chose to make. Both statements come from one read, so they cannot
    # disagree.
    notes = [line for line in draft.retention if line.days == 120]  # type: ignore[attr-defined]
    assert [line.what for line in notes] == ["The short note of what you asked about"]
    assert "The short note of what you asked about: 120 days" in markdown


async def test_a_vertical_where_the_write_is_refused_is_never_told_its_agents_remember() -> None:
    """D-507(b) AT THE NOTICE, and the reason this module cannot read the column alone.

    On a refused vertical `caller_memory.memory_enabled` returns False however the switch
    is set, so nothing is ever written. A draft generated from the raw column would tell
    that client's callers that notes are kept about them between calls — processing that
    cannot happen — and the client would publish it as their own statement. Over-disclosure
    is not the safe direction: it is a false notice, and it invites a caller to decline
    something nobody is doing.

    Everything the memory switch drives is asserted absent together, because they are four
    separate readers of the same fact and a fix that missed one would leave the false
    sentence in the document a client actually pastes.
    """
    tenant_id, agent_id, _, _ = await _tenant("clinic")
    await _publish(tenant_id, agent_id)
    await _remember_callers(tenant_id, agent_id)

    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(
                text("SELECT caller_memory_enabled FROM agents WHERE id = :a"), {"a": agent_id}
            )
        ).scalar()
    assert stored is True, "the fixture must have the switch on or this proves nothing"

    draft = await _draft(tenant_id)

    assert draft.caller_memory_on == []  # type: ignore[attr-defined]
    labels = [item.what for item in draft.collected]  # type: ignore[attr-defined]
    assert not [label for label in labels if "kept after the call ends" in label]
    markdown = draft.markdown  # type: ignore[attr-defined]
    assert "If you have called us before" not in markdown
    assert "keep notes about you between calls" not in markdown
    assert "The short note of what you asked about" not in markdown
    assert draft.memory_retention_days is None  # type: ignore[attr-defined]
    assert not [q for q in draft.open_questions if "BETWEEN calls" in q]  # type: ignore[attr-defined]


# THE OTHER HALF OF THE CALL. `_handoff_paragraph` was written with D-533 and had no test
# at all — which is the shape that matters here, because the paragraph's whole job is to
# describe the ONE part of the call where the caller stops talking to a machine. An
# untested section that renders empty is indistinguishable, in a passing suite, from one
# that renders correctly: both leave a green run and a notice that under-discloses.


async def _hand_callers_to_a_person(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET handoff_enabled = true WHERE id = :a"), {"a": agent_id}
        )


async def test_a_client_whose_agents_never_hand_over_says_nothing_about_it() -> None:
    """`_memory_paragraph`'s argument applied to the transfer: a notice describing a
    handover that cannot happen tells a caller they may be put through to a person by a
    business that has configured nobody to put them through to."""
    tenant_id, agent_id, _, _ = await _tenant()
    await _publish(tenant_id, agent_id)

    draft = await _draft(tenant_id)

    assert draft.handoff_agents == []  # type: ignore[attr-defined]
    markdown = draft.markdown  # type: ignore[attr-defined]
    assert "When we put you through to a person" not in markdown
    assert "The recording does not stop when you are put through" not in markdown


async def test_handing_a_caller_to_a_person_is_disclosed_and_the_agent_named() -> None:
    """The section appears exactly when an agent can hand over, and NAMES it — a business
    running a receptionist that transfers and a campaign that does not is making two
    different promises to two sets of callers."""
    tenant_id, agent_id, _, _ = await _tenant()
    await _publish(tenant_id, agent_id)
    await _hand_callers_to_a_person(tenant_id, agent_id)

    draft = await _draft(tenant_id)

    assert len(draft.handoff_agents) == 1  # type: ignore[attr-defined]
    markdown = draft.markdown  # type: ignore[attr-defined]
    assert "## When we put you through to a person" in markdown
    assert draft.handoff_agents[0] in markdown  # type: ignore[attr-defined]


async def test_the_transferred_leg_is_disclosed_as_recorded_on_the_same_clock() -> None:
    """THE SENTENCE THE SECTION EXISTS FOR. The voice platform records the transferred leg
    as a SEPARATE object, so a handed-over call produces two recordings of one caller. The
    paragraph must say the recording continues, and must point at the retention list rather
    than restating a number — a second sentence carrying its own figure is the thing that
    goes stale when a tenant shortens their policy.
    """
    tenant_id, agent_id, _, _ = await _tenant()
    await _publish(tenant_id, agent_id)
    await _hand_callers_to_a_person(tenant_id, agent_id)

    draft = await _draft(tenant_id)
    markdown = draft.markdown  # type: ignore[attr-defined]
    # Read against a whitespace-collapsed copy: the paragraph is hard-wrapped, so the
    # pointer at the retention list straddles a newline in the source. Asserting on the
    # wrapped form would pin the column width rather than the sentence.
    flowed = " ".join(markdown.split())

    assert "The recording does not stop when you are put through" in flowed
    assert 'see "How long we keep it" below' in flowed
    # The blank THIS paragraph used to carry is GONE, not filled in: the founder's 5 Sep
    # 2026 decision made the transferred leg ours, on the tenant's own retention clock.
    # Scoped to the section rather than the whole draft, because the draft legitimately
    # carries blanks the client fills in ({{YOUR REGISTERED BUSINESS NAME}} and its
    # address) — a document-wide assertion here would fail on those and say nothing about
    # the one that was removed.
    section = markdown.split("## When we put you through to a person", 1)[1].split("\n## ", 1)[0]
    assert "{{" not in section
    assert "NOT BY US" not in section
