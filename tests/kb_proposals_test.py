"""Agent-proposed knowledge: the token contract, the content wall, and the gate it must
not be able to skip.

Four claims, in the order a reviewer would want them proved:

1. **The token is a proposal, not a credential.** It is signed, it expires, it is bound to
   one tenant and one person, and it can be spent exactly once. Every one of those is a
   separate test, because a mechanism that has four properties and three tests has three
   properties.
2. **Confirming lands in the review queue and nowhere else.** The row a confirmed proposal
   creates is `pending_approval`, `is_active = false`, with preview chunks — identical to
   a pasted submission, which is what makes every downstream guard apply unchanged.
3. **Proposing writes nothing.** Asserted by counting rows before and after, including the
   failed paths, because "it only reads" is the sort of claim that stops being true in a
   diff nobody reads twice.
4. **Nothing caller-derived can ride along.** A source inventory over the module (the
   `tests/kb_aggregate_guard_test.py` technique) plus the closed topic set, because the
   `knowledge_gaps` row this lane reads has two redacted-quote columns sitting right
   beside the counts.
"""

from __future__ import annotations

import ast
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from apps.api.admin import service as admin_service
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.redis import get_redis
from apps.api.db.session import tenant_session
from apps.api.kb import proposals
from sqlalchemy import text

REPO_ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.rls


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name="KB Proposals",
        slug=f"kbprop-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return created["id"], created["agent_id"]


def _principal(tenant_id: uuid.UUID, user_id: uuid.UUID | None = None) -> Principal:
    return Principal(
        realm="client",
        user_id=user_id or uuid.uuid4(),
        tenant_id=tenant_id,
        role="owner",
    )


BODY = "We are open until 9pm on Saturdays, and closed on public holidays."


# --- 1. the token contract ----------------------------------------------------


def test_a_token_round_trips_every_claim_it_carries() -> None:
    """Every field is inside the signature. A claim outside it is a field an attacker may
    edit, and `origin` is the one a reviewer reads to decide how much to trust the text."""
    proposal = proposals.KbProposal(
        nonce=uuid.uuid4().hex,
        tenant_id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        name="Saturday hours",
        body=BODY,
        origin="gap_digest",
        topic_key="timings",
        expires_at=datetime.now(UTC) + timedelta(seconds=60),
    )
    assert proposals.verify_token(proposals.issue_token(proposal)) == proposal


@pytest.mark.parametrize(
    "mangle",
    [
        pytest.param(lambda t: t[:-1] + ("A" if t[-1] != "A" else "B"), id="signature-edited"),
        pytest.param(lambda t: t.split(".")[0], id="signature-stripped"),
        pytest.param(lambda t: "not-a-token", id="not-a-token"),
        pytest.param(lambda t: "!!!." + t.split(".")[1], id="payload-not-base64"),
    ],
)
def test_a_token_that_is_not_ours_is_refused(mangle) -> None:  # type: ignore[no-untyped-def]
    """All four fail with the SAME detail and the same code: a caller who can tell a
    forged signature from a mangled payload has an oracle for which half they got right."""
    proposal = proposals.KbProposal(
        nonce=uuid.uuid4().hex,
        tenant_id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        name="Saturday hours",
        body=BODY,
        origin="copilot",
        topic_key=None,
        expires_at=datetime.now(UTC) + timedelta(seconds=60),
    )
    with pytest.raises(ProblemError) as excinfo:
        proposals.verify_token(mangle(proposals.issue_token(proposal)))
    assert excinfo.value.code == "kb_proposal_invalid"


def test_an_expired_token_is_refused_even_though_it_verifies() -> None:
    """The signature is valid and the token is dead. The expiry is a claim we check, not a
    property the signature has."""
    proposal = proposals.KbProposal(
        nonce=uuid.uuid4().hex,
        tenant_id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        name="Saturday hours",
        body=BODY,
        origin="copilot",
        topic_key=None,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    with pytest.raises(ProblemError) as excinfo:
        proposals.verify_token(proposals.issue_token(proposal))
    assert excinfo.value.code == "kb_proposal_invalid"


# --- 2. the content wall ------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "body", "code"),
    [
        ("", BODY, "kb_proposal_name_invalid"),
        ("x" * (proposals.MAX_NAME_CHARS + 1), BODY, "kb_proposal_name_invalid"),
        ("Hours", "short", "kb_proposal_body_invalid"),
        ("Hours", "x" * (proposals.MAX_BODY_CHARS + 1), "kb_proposal_body_invalid"),
        (
            "Hours",
            "Call the clinic on 9876543210 for Saturday appointments.",
            "kb_proposal_contains_contact_details",
        ),
        (
            "Hours",
            "Email us at reception@example.com to book a Saturday slot.",
            "kb_proposal_contains_contact_details",
        ),
    ],
)
def test_the_content_wall_refuses_and_never_quotes_what_it_refused(
    name: str, body: str, code: str
) -> None:
    """The refusal must not name the offending value: putting the personal string into a
    problem body is the thing the guard exists to prevent (hard rule 6)."""
    with pytest.raises(ProblemError) as excinfo:
        proposals.assert_proposable(name, body)
    problem = excinfo.value
    assert problem.code == code
    rendered = f"{problem.title} {problem.detail} {problem.remediation}"
    assert "9876543210" not in rendered
    assert "reception@example.com" not in rendered


def test_a_business_fact_with_no_contact_details_passes() -> None:
    proposals.assert_proposable("Saturday hours", BODY)


# --- 3. propose reads, confirm writes, and the queue is the same one ----------


async def test_proposing_writes_nothing_and_confirming_lands_in_the_review_queue() -> None:
    tenant, agent = await _tenant()
    principal = _principal(tenant)

    async with tenant_session(tenant) as session:
        before = (await session.execute(text("SELECT count(*) FROM kb_sources"))).scalar()
        proposal, token = await proposals.build_proposal(
            session,
            principal=principal,
            agent_id=agent,
            name="Saturday hours",
            body=BODY,
            origin="copilot",
        )
        after = (await session.execute(text("SELECT count(*) FROM kb_sources"))).scalar()
    assert before == after == 0, "proposing must not create a row"
    assert proposal.origin == "copilot"

    async with tenant_session(tenant) as session:
        created = await proposals.confirm_proposal(session, token=token, principal=principal)

    # THE STATE IS THE FORM'S STATE. `pending_approval`, not active, with preview chunks —
    # which is what makes approve/publish and every downstream guard apply unchanged.
    assert created["status"] == "pending_approval"
    async with tenant_session(tenant) as session:
        row = (
            await session.execute(
                text("SELECT status, is_active, kind, version FROM kb_sources WHERE id = :i"),
                {"i": created["id"]},
            )
        ).one()
        chunks = (
            await session.execute(
                text("SELECT count(*) FROM kb_documents WHERE source_id = :i"),
                {"i": created["id"]},
            )
        ).scalar()
    assert row.status == "pending_approval"
    assert row.is_active is False
    assert row.kind == "text"
    assert row.version == 1
    assert chunks == created["chunks"] >= 1


async def test_a_confirmed_proposal_writes_an_audit_row_of_ids_only() -> None:
    """Hard rule 4: the execution is recorded. Hard rule 6: the record holds no text —
    a body written into an append-only ledger is a body erasure cannot reach."""
    tenant, agent = await _tenant()
    principal = _principal(tenant)
    async with tenant_session(tenant) as session:
        _, token = await proposals.build_proposal(
            session,
            principal=principal,
            agent_id=agent,
            name="Saturday hours",
            body=BODY,
            origin="copilot",
        )
    async with tenant_session(tenant) as session:
        created = await proposals.confirm_proposal(session, token=token, principal=principal)

    async with tenant_session(tenant) as session:
        entry = (
            await session.execute(
                text(
                    "SELECT action, object_type, object_id, summary FROM audit_log "
                    "WHERE object_id = :oid AND action = 'kb.proposal.confirm'"
                ),
                {"oid": str(created["id"])},
            )
        ).one()
    assert entry.object_type == "kb_source"
    assert entry.summary["origin"] == "copilot"
    assert entry.summary["actor_realm"] == "client"
    serialized = str(entry.summary)
    assert "Saturday" not in serialized
    assert "9pm" not in serialized


async def test_a_token_can_be_spent_only_once() -> None:
    tenant, agent = await _tenant()
    principal = _principal(tenant)
    async with tenant_session(tenant) as session:
        _, token = await proposals.build_proposal(
            session,
            principal=principal,
            agent_id=agent,
            name="Saturday hours",
            body=BODY,
            origin="copilot",
        )
    async with tenant_session(tenant) as session:
        await proposals.confirm_proposal(session, token=token, principal=principal)
    async with tenant_session(tenant) as session:
        with pytest.raises(ProblemError) as excinfo:
            await proposals.confirm_proposal(session, token=token, principal=principal)
    assert excinfo.value.code == "kb_proposal_already_used"

    # And the replay created nothing: exactly one source exists.
    async with tenant_session(tenant) as session:
        count = (await session.execute(text("SELECT count(*) FROM kb_sources"))).scalar()
    assert count == 1


async def test_a_token_is_bound_to_the_person_it_was_minted_for() -> None:
    """A colleague with the same permission, in the same tenant, cannot spend somebody
    else's proposal — a token is addressed, not bearer."""
    tenant, agent = await _tenant()
    author = _principal(tenant)
    colleague = _principal(tenant)
    async with tenant_session(tenant) as session:
        _, token = await proposals.build_proposal(
            session,
            principal=author,
            agent_id=agent,
            name="Saturday hours",
            body=BODY,
            origin="copilot",
        )
    async with tenant_session(tenant) as session:
        with pytest.raises(ProblemError) as excinfo:
            await proposals.confirm_proposal(session, token=token, principal=colleague)
    assert excinfo.value.code == "kb_proposal_invalid"


# --- 4. tenancy (hard rule 1) -------------------------------------------------


async def test_a_tenants_proposal_cannot_be_confirmed_or_seen_by_another_tenant() -> None:
    """The mandatory cross-tenant test, in both directions: tenant B cannot spend A's
    token, and cannot see the row A's confirmation created."""
    tenant_a, agent_a = await _tenant()
    tenant_b, _agent_b = await _tenant()
    principal_a = _principal(tenant_a)
    principal_b = _principal(tenant_b)

    async with tenant_session(tenant_a) as session:
        _, token = await proposals.build_proposal(
            session,
            principal=principal_a,
            agent_id=agent_a,
            name="Saturday hours",
            body=BODY,
            origin="copilot",
        )

    # B holds the token and the permission, and is refused on the tenant claim.
    async with tenant_session(tenant_b) as session:
        with pytest.raises(ProblemError) as excinfo:
            await proposals.confirm_proposal(session, token=token, principal=principal_b)
    assert excinfo.value.code == "kb_proposal_invalid"

    # B cannot propose against A's agent either: RLS makes the agent invisible, and
    # `assert_visible` refuses before a token exists.
    async with tenant_session(tenant_b) as session:
        with pytest.raises(ProblemError):
            await proposals.build_proposal(
                session,
                principal=principal_b,
                agent_id=agent_a,
                name="Saturday hours",
                body=BODY,
                origin="copilot",
            )

    # A confirms its own, and B sees zero rows — through a raw select, because the
    # guarantee is the FORCEd policy and not the query.
    async with tenant_session(tenant_a) as session:
        await proposals.confirm_proposal(session, token=token, principal=principal_a)
    async with tenant_session(tenant_b) as session:
        assert (await session.execute(text("SELECT count(*) FROM kb_sources"))).scalar() == 0
        assert (await session.execute(text("SELECT count(*) FROM kb_documents"))).scalar() == 0


# --- 5. the gap citation, and what it may not carry ---------------------------


async def test_a_gap_origin_must_name_the_gap_it_answers() -> None:
    """ "Your agent noticed this" with nothing to point at is a provenance claim the system
    cannot support, so it is refused structurally rather than trusted."""
    tenant, agent = await _tenant()
    async with tenant_session(tenant) as session:
        with pytest.raises(ProblemError) as excinfo:
            await proposals.build_proposal(
                session,
                principal=_principal(tenant),
                agent_id=agent,
                name="Saturday hours",
                body=BODY,
                origin="gap_digest",
            )
    assert excinfo.value.code == "kb_proposal_origin_needs_gap"


async def test_a_phrase_derived_topic_cannot_be_cited() -> None:
    """`insights/detection._topic` slugs three content words out of the CALLER'S question
    when no canonical keyword matches. Those `q_*` keys are caller-derived text, so citing
    one would carry a caller's words into a proposal — refused before the row is even
    looked for."""
    tenant, agent = await _tenant()
    async with tenant_session(tenant) as session:
        with pytest.raises(ProblemError) as excinfo:
            await proposals.build_proposal(
                session,
                principal=_principal(tenant),
                agent_id=agent,
                name="Saturday hours",
                body=BODY,
                origin="gap_digest",
                topic_key="q_saturday_dental_cleaning",
            )
    assert excinfo.value.code == "kb_proposal_gap_not_citable"


async def test_a_canonical_topic_with_no_open_gap_is_refused() -> None:
    tenant, agent = await _tenant()
    async with tenant_session(tenant) as session:
        with pytest.raises(ProblemError) as excinfo:
            await proposals.build_proposal(
                session,
                principal=_principal(tenant),
                agent_id=agent,
                name="Saturday hours",
                body=BODY,
                origin="gap_digest",
                topic_key="timings",
            )
    assert excinfo.value.code == "kb_proposal_gap_unknown"


def test_the_citable_topic_set_still_matches_the_detector() -> None:
    """The module keeps its own copy of the canonical topic keys, for the reason
    `insights/models.GAP_SIGNALS` does: a private name in another package is not an
    interface. This is the check that stops the copy drifting — a new canonical topic
    fails the build here rather than silently becoming uncitable."""
    from apps.api.insights import detection

    canonical = {key for key, _label, _triggers in detection._TOPICS}
    canonical.add("general")  # `_topic`'s honest fallback bucket, not caller-derived.
    assert canonical == proposals.CITABLE_TOPIC_KEYS


# --- 6. the source inventory --------------------------------------------------

#: Columns that hold what a caller said. The first two are the near miss and the reason
#: this net exists: they sit in the very `knowledge_gaps` row `_assert_citable_gap`
#: matches, and they are exactly what somebody enriching a proposal ("show them what the
#: caller asked") would reach for. A leak added to that existing SELECT changes no route,
#: raises no exception and passes every behavioural test in this file.
FORBIDDEN_SOURCES = (
    "example_question_redacted",
    "example_answer_redacted",
    "question_redacted",
    "answer_redacted",
    "transcript_turns",
    "text_redacted",
    "summary",
    "from_e164",
    "to_e164",
    "moments",
    "erased_subject_ref",
)


def _executable_source(path: Path) -> str:
    """The module with its prose removed — comments and docstrings gone, every SQL string
    and identifier kept. A plain substring scan would make WRITING THE EXPLANATION a test
    failure, which trains people to delete the explanation; the same argument, and the
    same implementation, as `tests/kb_aggregate_guard_test.py`."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        body = node.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def test_the_proposal_lane_never_names_a_caller_derived_column() -> None:
    for module in (
        REPO_ROOT / "apps" / "api" / "kb" / "proposals.py",
        REPO_ROOT / "apps" / "api" / "kb" / "routes.py",
    ):
        source = _executable_source(module)
        for token in FORBIDDEN_SOURCES:
            assert token not in source, (
                f"{module.name} names {token!r} in code. A proposal may name a GAP from "
                "aggregate signals; it may never carry what a caller said (hard rule 6). "
                "If this is a deliberate widening, the argument in "
                "apps/api/kb/proposals.py has to be answered first."
            )


def test_the_confirm_path_has_exactly_one_door_into_kb_sources() -> None:
    """The gate is only unskippable while `submit_source` is the only way in. An INSERT
    written here — for a 'pre-approved' proposal, say — would produce a row the review
    queue never sees, and no other test in this repo would notice."""
    source = _executable_source(REPO_ROOT / "apps" / "api" / "kb" / "proposals.py")
    assert "INSERT" not in source.upper()
    assert "submit_source" in source


# --- 7. the tool definition ---------------------------------------------------


def test_the_tool_definition_is_the_strict_subset_and_offers_only_citable_topics() -> None:
    """Same shape discipline as `copilot/prompt.set_fields_tool`: `required` names every
    property and `additionalProperties` is false on every object, which is what
    openai-python's `to_strict_json_schema` enforces."""
    tool = proposals.propose_knowledge_tool()
    params = tool["function"]["parameters"]
    assert tool["function"]["name"] == proposals.PROPOSE_KNOWLEDGE_TOOL_NAME
    assert params["additionalProperties"] is False
    assert set(params["required"]) == set(params["properties"])
    described = params["properties"]["topic_key"]["description"]
    for key in proposals.CITABLE_TOPIC_KEYS:
        assert key in described
    # The description carries the anti-invention instruction. It is the only lever that
    # reaches the model before `assert_proposable` gets to refuse anything.
    lowered = tool["function"]["description"].lower()
    assert "never invent" in lowered
    assert "never repeat something a caller said" in lowered


def test_the_registration_seam_exposes_one_tool_and_mutates_nothing() -> None:
    tools = proposals.kb_write_tools()
    assert [t.name for t in tools] == [proposals.PROPOSE_KNOWLEDGE_TOOL_NAME]
    assert tools[0].handler is proposals.build_proposal
    assert tools[0].definition == proposals.propose_knowledge_tool()


# --- 8. the burn record is a real one ----------------------------------------


async def test_the_nonce_is_burned_in_redis_and_not_merely_in_memory() -> None:
    """Replay protection that lived in a process would evaporate on the next deploy and on
    every second worker. This asserts the record is where a second process can see it."""
    tenant, agent = await _tenant()
    principal = _principal(tenant)
    async with tenant_session(tenant) as session:
        proposal, token = await proposals.build_proposal(
            session,
            principal=principal,
            agent_id=agent,
            name="Saturday hours",
            body=BODY,
            origin="copilot",
        )
    key = f"{proposals._BURN_PREFIX}{proposal.nonce}"
    assert await get_redis().get(key) is None
    async with tenant_session(tenant) as session:
        await proposals.confirm_proposal(session, token=token, principal=principal)
    assert await get_redis().get(key) == "1"
    await get_redis().delete(key)
