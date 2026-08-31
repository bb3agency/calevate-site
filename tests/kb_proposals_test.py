"""Agent-proposed knowledge: the tool, the content wall, and the gate it must not skip.

THE PROPOSE→CONFIRM MACHINERY IS NOT TESTED HERE AND MUST NOT BE. Signature, expiry,
tenant and actor binding, the `jti` burn and the permission re-check all belong to
`copilot/write_tools.py` and are proved once in `copilot/write_tools_test.py`, for every
tool at once. This lane shipped its own copy of all of it and the copy is deleted; a test
file that kept asserting the copy's properties would be the second implementation growing
back as an assertion. What is asserted here is what is THIS TOOL'S:

1. **It is registered for real** — in `WRITE_TOOLS`, in `service.tool_array()`, under
   `kb:write`. A tool nobody offers is a half-wired feature.
2. **Proposing writes nothing, and confirming lands in the review queue and nowhere else.**
   The row a confirmed proposal creates is `pending_approval`, `is_active = false`, with
   preview chunks — identical to a pasted submission, which is what makes every downstream
   guard apply unchanged.
3. **The content wall**, including the redaction guard, refusing without ever quoting what
   it refused.
4. **Nothing caller-derived can ride along.** A source inventory over this lane (the
   `tests/kb_aggregate_guard_test.py` technique) plus the closed topic set, because the
   `knowledge_gaps` row this lane reads has two redacted-quote columns sitting right beside
   the counts.

Plus the two properties that ARE shared machinery but whose absence would be a bug in THIS
tool's wiring rather than in the machinery: the cross-tenant refusal and the permission
check at both ends are re-proved through `propose_knowledge` specifically, because
`permission=` and `object_type=` on a registry entry are one line each and a wrong line
there is invisible everywhere else.
"""

from __future__ import annotations

import ast
import json
import logging
import uuid
from pathlib import Path

import pytest
from apps.api.admin import service as admin_service
from apps.api.copilot import service as copilot_service
from apps.api.copilot import write_tools
from apps.api.copilot.schemas import CopilotConfirmOut
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.kb import proposals
from sqlalchemy import text

REPO_ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.rls

TOOL = "propose_knowledge"
BODY = "We are open until 9pm on Saturdays, and closed on public holidays."


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


def _principal(
    tenant_id: uuid.UUID, user_id: uuid.UUID | None = None, *, role: str = "owner"
) -> Principal:
    return Principal(
        realm="client", user_id=user_id or uuid.uuid4(), tenant_id=tenant_id, role=role
    )


def _actor(principal: Principal) -> write_tools.ToolActor:
    resolved = write_tools.actor_for(principal)
    assert resolved is not None
    return resolved


def _args(agent_id: uuid.UUID, **overrides: object) -> str:
    payload: dict[str, object] = {
        "agent_id": str(agent_id),
        "name": "Saturday hours",
        "body": BODY,
        "origin": "copilot",
        "topic_key": None,
    }
    payload.update(overrides)
    return json.dumps(payload)


async def _confirm(tenant_id: uuid.UUID, token: str, principal: Principal) -> CopilotConfirmOut:
    """One confirm in its own transaction, the way the route's `Depends(db)` gives it."""
    async with tenant_session(tenant_id) as session:
        return await write_tools.confirm(session, token, principal=principal, ip="203.0.113.7")


async def _kb_source_count(tenant_id: uuid.UUID) -> int:
    async with tenant_session(tenant_id) as session:
        return int((await session.execute(text("SELECT count(*) FROM kb_sources"))).scalar() or 0)


async def _open_gap(tenant_id: uuid.UUID, agent_id: uuid.UUID, topic_key: str) -> None:
    """One open roll-up row, written the way `insights/service.py` writes it — including
    the two redacted-quote columns, so the inventory test is guarding a lane where the
    tempting values really are present rather than a table where they happen to be NULL."""
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO knowledge_gaps (id, tenant_id, agent_id, topic_key, topic_label, "
                "status, occurrence_count, call_count, example_question_redacted, "
                "example_answer_redacted, top_signal, first_seen_at, last_seen_at, "
                "created_at, updated_at) VALUES (:id, :tid, :aid, :key, :key, 'open', 3, 3, "
                "'is there a walk-in queue on tuesdays', 'i do not know', 'dont_know', "
                "now(), now(), now(), now())"
            ),
            {"id": uuid7(), "tid": tenant_id, "aid": agent_id, "key": topic_key},
        )


# --- 1. it is registered, and under the right permission ----------------------


def test_the_tool_is_registered_in_the_one_registry_and_the_one_composer() -> None:
    """A tool the model is never offered proposes nothing. `tool_array()` is the ONE
    composer (`copilot/service.py`), and appearing in `WRITE_TOOLS` is what puts it there —
    so this asserts both ends rather than trusting that the second follows from the first.
    """
    assert [tool.name for tool in write_tools.WRITE_TOOLS][-1] == TOOL, (
        "registration order is wire order and part of the cacheable prompt prefix: new tools APPEND"
    )
    offered = [schema["function"]["name"] for schema in copilot_service.tool_array()]
    assert TOOL in offered


def test_the_tool_declares_the_permission_the_knowledge_form_declares() -> None:
    """`kb:write` — what `POST /v1/kb/sources` already requires. Deciding what the agent
    knows is ONE permission (D-21), and the gate is the PERMISSION and not a role name, so
    widening who may curate is a line in `rbac.py` and never a line in the tool."""
    assert write_tools.PROPOSE_KNOWLEDGE.permission == proposals.CURATE_PERMISSION == "kb:write"
    # And that permission is mutating, which is what refuses an impersonating admin (D-22)
    # at both ends without this lane carrying a check of its own.
    from apps.api.core.rbac import MUTATING_PERMISSIONS

    assert write_tools.PROPOSE_KNOWLEDGE.permission in MUTATING_PERMISSIONS


def test_the_tool_schema_is_the_strict_subset_and_offers_only_citable_topics() -> None:
    """openai-python's `to_strict_json_schema` subset: every property in `required`,
    `additionalProperties: false`. `topic_key` is genuinely optional and says so as
    `anyOf: [string, null]` — strict mode has no way to spell "may be absent"."""
    function = write_tools.PROPOSE_KNOWLEDGE.schema["function"]
    parameters = function["parameters"]
    assert function["strict"] is True
    assert parameters["additionalProperties"] is False
    assert set(parameters["required"]) == set(parameters["properties"])
    assert parameters["properties"]["topic_key"]["anyOf"] == [
        {"type": "string"},
        {"type": "null"},
    ]
    described = parameters["properties"]["topic_key"]["description"]
    for key in proposals.CITABLE_TOPIC_KEYS:
        assert key in described
    # The description carries the anti-invention instruction. It is the only lever that
    # reaches the model before `proposable_refusal` gets to refuse anything.
    lowered = function["description"].lower()
    assert "never invent" in lowered
    assert "never repeat something a caller said" in lowered


# --- 2. propose reads, confirm writes, and the queue is the same one ----------


async def test_proposing_writes_nothing_and_confirming_lands_in_the_review_queue() -> None:
    tenant, agent = await _tenant()
    principal = _principal(tenant)

    assert await _kb_source_count(tenant) == 0
    proposal = await write_tools.plan_write(TOOL, _args(agent), actor=_actor(principal))
    assert await _kb_source_count(tenant) == 0, "proposing must not create a row"

    assert proposal.tool == TOOL
    assert proposal.object_type == "agent"
    assert proposal.object_id == str(agent)
    assert proposal.proposed == "Saturday hours"
    assert proposal.current is None
    assert "review" in proposal.summary

    confirmed = await _confirm(tenant, proposal.token, principal)
    assert confirmed.applied is True

    # THE STATE IS THE FORM'S STATE. `pending_approval`, not active, with preview chunks —
    # which is what makes approve/publish and every downstream guard apply unchanged.
    async with tenant_session(tenant) as session:
        row = (
            await session.execute(
                text(
                    "SELECT id, status, is_active, kind, version, submitted_by "
                    "FROM kb_sources WHERE agent_id = :a"
                ),
                {"a": agent},
            )
        ).one()
        chunks = (
            await session.execute(
                text("SELECT count(*) FROM kb_documents WHERE source_id = :i"), {"i": row.id}
            )
        ).scalar()
    assert row.status == "pending_approval"
    assert row.is_active is False
    assert row.kind == "text"
    assert row.version == 1
    assert row.submitted_by == principal.user_id, "the queue must name who CONFIRMED it"
    assert chunks and chunks >= 1


async def test_a_confirmed_proposal_writes_an_audit_row_of_ids_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Hard rule 4: the execution is recorded, in the same transaction as the row it
    describes. Hard rule 6: neither half carries the drafted text.

    THE SUMMARY IS NOT A COLUMN. `write_audit` hashes actor/tenant/action/object/ip into the
    chain and sends `summary` to the LOG STREAM instead, keyed by the entry id
    (`compliance/audit.py`: hashing a field the row does not carry would make the chain
    unverifiable). So this asserts the ROW through SQL and the SUMMARY through the log
    record — which is also the half where a leaked body would actually end up.
    """
    tenant, agent = await _tenant()
    principal = _principal(tenant)
    await _open_gap(tenant, agent, "timings")
    proposal = await write_tools.plan_write(
        TOOL, _args(agent, origin="gap_digest", topic_key="timings"), actor=_actor(principal)
    )
    with caplog.at_level(logging.INFO, logger="apps.api.compliance.audit"):
        await _confirm(tenant, proposal.token, principal)

    async with untenanted_session() as session:
        entry = (
            await session.execute(
                text(
                    "SELECT action, object_type, object_id, actor_id, entry_hash "
                    "FROM audit_log WHERE tenant_id = :t"
                ),
                {"t": str(tenant)},
            )
        ).one()
    assert entry.action == "kb.source_proposed"
    # THE AGENT, not the source: `obj` is signed at plan time and the source does not exist
    # then. The created id rides in the summary instead, which the log record proves.
    assert (entry.object_type, entry.object_id) == ("agent", str(agent))
    assert entry.actor_id == principal.user_id
    assert entry.entry_hash, "the row must be linked into the tamper-evident chain"

    record = next(r for r in caplog.records if r.getMessage() == "audit")
    assert record.origin == "gap_digest", "provenance is what a reviewer reads first"
    assert record.topic_key == "timings"
    assert record.via == "copilot"
    assert record.status == "pending_approval"
    assert record.source_id
    # The drafted words are in `kb_sources`, where deletion reaches them — never in a
    # ledger row and never in a log line.
    emitted = " ".join(f"{k}={v}" for k, v in vars(record).items())
    assert "Saturday" not in emitted
    assert "9pm" not in emitted


async def test_a_second_submission_is_a_second_version_rather_than_a_no_op() -> None:
    """`applied` is unconditionally True for this tool and that is the honest answer: the
    other three ask the world to reach a state it may already be in, this one APPENDS a
    version a reviewer sees. Proved rather than asserted in a comment."""
    tenant, agent = await _tenant()
    principal = _principal(tenant)
    for _ in range(2):
        proposal = await write_tools.plan_write(TOOL, _args(agent), actor=_actor(principal))
        assert (await _confirm(tenant, proposal.token, principal)).applied is True
    async with tenant_session(tenant) as session:
        versions = (
            await session.execute(
                text("SELECT version FROM kb_sources WHERE agent_id = :a ORDER BY version"),
                {"a": agent},
            )
        ).scalars()
    assert list(versions) == [1, 2]


# --- 3. the permission, at both ends ------------------------------------------


async def test_the_permission_is_checked_when_proposing_and_again_when_confirming() -> None:
    """The propose-time check is advisory UX; the confirm-time one is the gate. A role that
    lost `kb:write` between the two must not be able to spend the old role, so the same
    token is minted as an owner and refused as a `staff` member — which is exactly the
    shape of a demotion mid-conversation.

    `staff` is the real role and it really does not hold `kb:write` (`core/rbac.py`), which
    is a live product blocker rather than a test fixture: an owner can curate knowledge and
    a staff member cannot, whatever the copilot offers.
    """
    tenant, agent = await _tenant()
    owner = _principal(tenant)
    demoted = _principal(tenant, owner.user_id, role="staff")

    with pytest.raises(write_tools.WriteRefusedError) as refused:
        await write_tools.plan_write(TOOL, _args(agent), actor=_actor(demoted))
    assert TOOL in refused.value.reason

    proposal = await write_tools.plan_write(TOOL, _args(agent), actor=_actor(owner))
    with pytest.raises(ProblemError) as forbidden:
        await _confirm(tenant, proposal.token, demoted)
    assert forbidden.value.status == 403
    assert await _kb_source_count(tenant) == 0


async def test_an_impersonating_admin_cannot_propose_or_confirm() -> None:
    """D-22, through `write_tools._may` and not through a check of this lane's own.
    `kb:write` is in `MUTATING_PERMISSIONS`, so a read-only view-as session is refused at
    both ends — an operator may not put words into a client's agent's mouth."""
    tenant, agent = await _tenant()
    owner = _principal(tenant)
    viewing = Principal(
        realm="client",
        user_id=owner.user_id,
        tenant_id=tenant,
        role="admin",
        impersonating=True,
    )

    with pytest.raises(write_tools.WriteRefusedError):
        await write_tools.plan_write(TOOL, _args(agent), actor=_actor(viewing))

    proposal = await write_tools.plan_write(TOOL, _args(agent), actor=_actor(owner))
    with pytest.raises(ProblemError) as forbidden:
        await _confirm(tenant, proposal.token, viewing)
    assert forbidden.value.status == 403


# --- 4. tenancy (hard rule 1) -------------------------------------------------


async def test_a_tenants_proposal_cannot_be_confirmed_or_seen_by_another_tenant() -> None:
    """The mandatory cross-tenant test, in three directions: B cannot spend A's token, B
    cannot propose against A's agent, and B cannot see what A's confirmation created."""
    tenant_a, agent_a = await _tenant()
    tenant_b, _agent_b = await _tenant()
    principal_a = _principal(tenant_a)
    principal_b = _principal(tenant_b)

    proposal = await write_tools.plan_write(TOOL, _args(agent_a), actor=_actor(principal_a))

    # B holds the token and the permission, and is refused on the `sub` claim — ahead of
    # RLS, which is still behind it.
    with pytest.raises(ProblemError) as refused:
        await _confirm(tenant_b, proposal.token, principal_b)
    assert refused.value.status == 403

    # B cannot propose against A's agent either: RLS makes it invisible and
    # `assert_visible` answers 404, before a token exists.
    with pytest.raises(ProblemError) as not_found:
        await write_tools.plan_write(TOOL, _args(agent_a), actor=_actor(principal_b))
    assert not_found.value.status == 404

    # A confirms its own, and B sees zero rows — through a raw select, because the
    # guarantee is the FORCEd policy and not the query.
    await _confirm(tenant_a, proposal.token, principal_a)
    assert await _kb_source_count(tenant_b) == 0
    async with tenant_session(tenant_b) as session:
        assert (await session.execute(text("SELECT count(*) FROM kb_documents"))).scalar() == 0


# --- 5. the content wall ------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "body"),
    [
        pytest.param("", BODY, id="no-title"),
        pytest.param("x" * (proposals.MAX_NAME_CHARS + 1), BODY, id="title-too-long"),
        pytest.param("Hours", "short", id="body-too-short"),
        pytest.param("Hours", "x" * (proposals.MAX_BODY_CHARS + 1), id="body-too-long"),
        pytest.param(
            "Hours",
            "Call the clinic on 9876543210 for Saturday appointments.",
            id="phone-number",
        ),
        pytest.param(
            "Hours",
            "Email us at reception@example.com to book a Saturday slot.",
            id="email-address",
        ),
    ],
)
def test_the_content_wall_refuses_and_never_quotes_what_it_refused(name: str, body: str) -> None:
    """The refusal must not name the offending value: it becomes a log line AND the model's
    next prompt, so putting the personal string into it is the thing the guard exists to
    prevent (hard rule 6)."""
    reason = proposals.proposable_refusal(name, body)
    assert reason is not None
    assert "9876543210" not in reason
    assert "reception@example.com" not in reason


def test_a_business_fact_with_no_contact_details_passes() -> None:
    assert proposals.proposable_refusal("Saturday hours", BODY) is None


async def test_a_drafted_contact_detail_is_refused_before_anything_is_signed() -> None:
    """The wall reached through the tool, not just as a unit — and it is a
    `WriteRefusedError`, handed back to the model so it can tell the person to type the
    number in themselves, rather than a dead end."""
    tenant, agent = await _tenant()
    with pytest.raises(write_tools.WriteRefusedError) as refused:
        await write_tools.plan_write(
            TOOL,
            _args(agent, body="Call the clinic on 9876543210 for Saturday appointments."),
            actor=_actor(_principal(tenant)),
        )
    assert "9876543210" not in refused.value.reason
    assert await _kb_source_count(tenant) == 0


# --- 6. the gap citation, and what it may not carry ---------------------------


async def test_a_gap_origin_must_name_the_gap_it_answers() -> None:
    """ "Your agent noticed this" with nothing to point at is a provenance claim the system
    cannot support, so it is refused structurally rather than trusted."""
    tenant, agent = await _tenant()
    with pytest.raises(write_tools.WriteRefusedError) as refused:
        await write_tools.plan_write(
            TOOL, _args(agent, origin="gap_digest"), actor=_actor(_principal(tenant))
        )
    assert "topic_key" in refused.value.reason


async def test_a_phrase_derived_topic_cannot_be_cited() -> None:
    """`insights/detection._topic` slugs three content words out of the CALLER'S question
    when no canonical keyword matches. Those `q_*` keys are caller-derived text, so citing
    one would carry a caller's words into a proposal and an audit summary — refused before
    the row is even looked for."""
    tenant, agent = await _tenant()
    with pytest.raises(write_tools.WriteRefusedError) as refused:
        await write_tools.plan_write(
            TOOL,
            _args(agent, origin="gap_digest", topic_key="q_saturday_dental_cleaning"),
            actor=_actor(_principal(tenant)),
        )
    assert "recognised" in refused.value.reason


async def test_a_canonical_topic_with_no_open_gap_is_refused() -> None:
    tenant, agent = await _tenant()
    with pytest.raises(write_tools.WriteRefusedError) as refused:
        await write_tools.plan_write(
            TOOL,
            _args(agent, origin="gap_digest", topic_key="timings"),
            actor=_actor(_principal(tenant)),
        )
    assert "no `timings` knowledge gap is open" in refused.value.reason


async def test_a_cited_gap_is_this_agents_and_still_open() -> None:
    tenant, agent = await _tenant()
    await _open_gap(tenant, agent, "pricing")
    proposal = await write_tools.plan_write(
        TOOL,
        _args(agent, origin="gap_digest", topic_key="pricing"),
        actor=_actor(_principal(tenant)),
    )
    assert proposal.tool == TOOL
    # The origin and the topic are inside the SIGNATURE, so the browser cannot relabel a
    # conversation as a detection between the proposal and the confirm.
    import jwt

    claims = jwt.decode(proposal.token, options={"verify_signature": False})
    assert claims["args"]["origin"] == "gap_digest"
    assert claims["args"]["topic_key"] == "pricing"
    # And the caller's own words, which sit in the row that citation matched, are not in it.
    # `_open_gap` writes a question deliberately unlike the drafted body, so this assertion
    # is about the leak and not about a word the two happen to share.
    assert "walk-in queue" not in json.dumps(claims).lower()


def test_the_citable_topic_set_still_matches_the_detector() -> None:
    """The module keeps its own copy of the canonical topic keys, for the reason
    `insights/models.GAP_SIGNALS` does: a private name in another package is not an
    interface. This is the check that stops the copy drifting — a new canonical topic fails
    the build here rather than silently becoming uncitable. It has already earned its keep:
    it is how `warranty` was found missing from the first draft of the set."""
    from apps.api.insights import detection

    canonical = {key for key, _label, _triggers in detection._TOPICS}
    canonical.add("general")  # `_topic`'s honest fallback bucket, not caller-derived.
    assert canonical == proposals.CITABLE_TOPIC_KEYS


# --- 7. the source inventory --------------------------------------------------

#: Columns that hold what a caller said. The first two are the near miss and the reason
#: this net exists: they sit in the very `knowledge_gaps` row `gap_refusal` matches, and
#: they are exactly what somebody enriching a proposal ("show them what the caller asked")
#: would reach for. A leak added to that existing SELECT changes no route, raises no
#: exception and passes every behavioural test in this file.
FORBIDDEN_SOURCES = (
    "example_question_redacted",
    "example_answer_redacted",
    "question_redacted",
    "answer_redacted",
    "transcript_turns",
    "text_redacted",
    "from_e164",
    "to_e164",
    "moments",
    "erased_subject_ref",
)

#: The lane, both halves. `kb/proposals.py` holds the gap read and the content wall;
#: `copilot/write_tools.py` holds the plan that composes the sentence a person approves,
#: which is the other place a caller's words could be made to appear. Scanning only the
#: first would leave the second unguarded the moment the lane was split in two, which is
#: precisely what this reconciliation did.
INVENTORIED = (
    Path("apps") / "api" / "kb" / "proposals.py",
    Path("apps") / "api" / "copilot" / "write_tools.py",
)

#: `summary` cannot be forbidden outright: `calls.summary` is the per-call AI summary this
#: lane must never read, and `write_audit(..., summary=...)` is the record it must always
#: write. Same spelling, opposite obligations. So it is allowed in EXACTLY one form — the
#: keyword argument — and every other occurrence fails, which still catches
#: `SELECT c.summary`, `summary FROM calls` and `c.summary AS ...`.
#:
#: SCOPED TO `kb/proposals.py`. `write_tools.py` spells `summary` as a `Plan` field and an
#: `Executed` field for all four tools, so the count equality cannot hold there and forcing
#: it would mean renaming the registry's own vocabulary to satisfy a test. The forbidden
#: list above still applies to that file in full, and `calls` is not a table it touches.
EXCLUSION_ONLY_SOURCE = "summary"
EXCLUSION_ONLY_SPELLING = "summary="
EXCLUSION_ONLY_SCOPE = Path("apps") / "api" / "kb" / "proposals.py"


def _executable_source(path: Path) -> str:
    """The module with its prose removed — comments and docstrings gone, every SQL string
    and identifier kept. A plain substring scan would make WRITING THE EXPLANATION a test
    failure, which trains people to delete the explanation; the same argument, and the same
    implementation, as `tests/kb_aggregate_guard_test.py`."""
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


@pytest.mark.parametrize("relative", INVENTORIED, ids=lambda p: p.name)
def test_the_proposal_lane_never_names_a_caller_derived_column(relative: Path) -> None:
    source = _executable_source(REPO_ROOT / relative)
    for token in FORBIDDEN_SOURCES:
        assert token not in source, (
            f"{relative.name} names {token!r} in code. A proposal may name a GAP from "
            "aggregate signals; it may never carry what a caller said (hard rule 6). If "
            "this is a deliberate widening, the argument in apps/api/kb/proposals.py has "
            "to be answered first."
        )
    if relative == EXCLUSION_ONLY_SCOPE:
        assert source.count(EXCLUSION_ONLY_SOURCE) == source.count(EXCLUSION_ONLY_SPELLING), (
            f"{relative.name} names {EXCLUSION_ONLY_SOURCE!r} outside "
            f"{EXCLUSION_ONLY_SPELLING!r}. The only legitimate use in this lane is the "
            "audit record's keyword argument; `calls.summary` is the per-call AI summary "
            "this lane must never read."
        )


def test_the_confirm_path_has_exactly_one_door_into_kb_sources() -> None:
    """The gate is only unskippable while `submit_source` is the only way in. An INSERT
    written here — for a 'pre-approved' proposal, say — would produce a row the review
    queue never sees, and no other test in this repo would notice."""
    source = _executable_source(REPO_ROOT / "apps" / "api" / "kb" / "proposals.py")
    assert "INSERT" not in source.upper()
    assert "submit_source" in source


def test_the_lane_mints_no_token_and_burns_no_nonce_of_its_own() -> None:
    """The reconciliation, as a standing assertion rather than a commit message. This lane
    shipped its own HMAC, its own nonce and its own confirm route; `copilot/write_tools.py`
    is the one propose→confirm machine and a second one growing back here is the defect
    that held this work. If a KB-specific proposal really does need something the registry
    cannot give, the registry is what changes."""
    source = _executable_source(REPO_ROOT / "apps" / "api" / "kb" / "proposals.py")
    for banned in ("hmac", "derived_ring", "get_redis", "jwt", "write_audit"):
        assert banned not in source, (
            f"kb/proposals.py names {banned!r}: the propose→confirm machinery belongs to "
            "copilot/write_tools.py, and a second copy of it is what 811d681 reverted."
        )


def test_the_kb_router_offers_no_second_confirm_route() -> None:
    """`POST /v1/kb/proposals` and `POST /v1/kb/proposals/confirm` are deleted. The KB tool
    rides `POST /v1/copilot/confirm` like every other write tool, which is why there is one
    signature format, one replay guard and one audit path instead of two."""
    from apps.api.copilot import routes as copilot_routes
    from apps.api.kb import routes as kb_routes

    def _paths(router: object) -> set[str]:
        return {r.path for r in getattr(router, "routes", []) if hasattr(r, "path")}

    assert not {p for p in _paths(kb_routes.router) if "proposal" in p}
    assert "/v1/copilot/confirm" in _paths(copilot_routes.router)
