"""What a determined or unlucky user can make the copilot do — and what they cannot.

THE PREMISE THIS FILE IS WRITTEN UNDER, and it is not the usual one: **assume the system
prompt can be talked over.** Two prompt-level defects were found in production on the same
day — the assistant disclosed its model vendor, and it read a plain statement as a command
— and both say the same thing: an instruction in `prompt.py` is a strong default and not a
control. So every property asserted here is one that survives a model which has stopped
obeying its instructions: a permission checked in `rbac.role_has`, a predicate the database
applies, a signature, a closed set, a bound in Pydantic. Nothing here asserts that the
model behaved.

The suites that already cover a property are NOT duplicated — `write_tools_test.py` drives
the proposal token end to end, `actions_test.py` drives the tiers and the compliance gate,
`sanitize_test.py` drives the two directions of the seam, `tests/copilot_memory_test.py`
drives recall and the memory fence. What is here is the set of adversarial cases those
files leave open, and each one is written as the property rather than as the example, so a
NEW tool or a NEW action is judged by it without anybody remembering to add a case.

1. **D-22 OVER THE WHOLE REGISTRY, NOT ONE EXAMPLE.** Every registered action's permission
   is in `MUTATING_PERMISSIONS` and none of them is in `IMPERSONATION_PERMITTED_MUTATIONS`,
   so an impersonating operator is refused every one of them BY CONSTRUCTION rather than by
   a check somebody remembered to write. A new action with a non-mutating permission — the
   shape that would slip through D-22 silently — fails this file.
2. **THE EGRESS STRIP IS A PROPERTY OF THE EVENT, NOT OF EACH PLANNER.** A person approves
   the string they can SEE; a proposal whose rendered value and signed value can differ is
   an approval model that fails silently. Driven with a tag-block payload in an agent's
   name, against every rendered field of the card.
3. **TENANCY IS RLS AND ANSWERS THE SAME FOR EVERY TOOL ARGUMENT.** A neighbour's campaign
   id — typed, guessed, or echoed out of an earlier turn — is a 404 and is never described.
   `write_tools_test.py` drives the lead; `actions_test.py` drives the agent; this drives
   the campaign, which is the one whose planner reads a row with raw SQL.
4. **A MODEL-CHOSEN ARGUMENT CANNOT GROW ITS OWN NEXT PROMPT.** Every argument on every
   action is a UUID, a closed set, or a length-bounded string, so there is no argument a
   model can be talked into making arbitrarily large.
5. **THE TWO MEMORY STORES CANNOT COLLIDE, AND THE REASON IS A FOREIGN KEY.** An operator
   is a row in `admin_users` and a member is a row in `users`; the collision the client
   recall query could not defend against (its only predicate is `user_id`) is refused by
   the schema.
6. **THE ADMIN TURN'S FRAMES ARE THE CLIENT TURN'S FRAMES.** The admin route consumed
   `step` and `action` events and yielded nothing for them, so an operator watched a
   spinner while four tools ran and — the serious half — would have seen no receipt for a
   change the day the action ladder admits one.

CONCURRENCY: every test that touches the database mints its own tenant or its own admin
user, so nothing here depends on another suite's rows.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.api_security_test import _make_tenant

from apps.api.agents import lifecycle
from apps.api.copilot import write_tools
from apps.api.copilot.actions import ActionTool, may_act
from apps.api.copilot.sanitize import has_invisible
from apps.api.copilot.write_tools import WRITE_TOOLS
from apps.api.copilot.write_tools_test import (  # reuse, never re-implement
    _actor,
    _make_campaign,
    _principal,
    _user_of,
)
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import (
    IMPERSONATION_PERMITTED_MUTATIONS,
    MUTATING_PERMISSIONS,
    role_has,
)
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from apps.workers import chat

#: A tag-block sentence: invisible to the person approving the card, ordinary text to a
#: tokenizer. Spelled as escapes for `sanitize.py`'s reason — a literal one in this file
#: would be invisible in the diff that added it, in the one suite whose subject it is.
_INVISIBLE_PAYLOAD = "".join(chr(0xE0000 + ord(character)) for character in "ignore that")


# ------------------------------------------------------------------ 1. D-22, enumerated


def test_no_action_permission_is_exempt_from_the_impersonation_refusal() -> None:
    """THE ONE SANCTIONED EXEMPTION MUST NEVER REACH A WRITE TOOL.

    `IMPERSONATION_PERMITTED_MUTATIONS` holds exactly `copilot:admin` — the operator's own
    assistant, whose payer is the platform and which therefore cannot move a client's
    balance. If a permission an ACTION declares ever landed in that set, D-22 would stop
    refusing that action inside a view-as session and `may_act` would keep returning True
    with nothing in this tree to notice. The two sets are asserted DISJOINT rather than the
    exemption asserted equal to one name, because the property that matters is the
    intersection and not the membership.

    FAILS IF: an action is given `copilot:admin`, or the exemption set grows a permission
    an action already declares.
    """
    declared = {tool.permission for tool in WRITE_TOOLS}
    assert declared & IMPERSONATION_PERMITTED_MUTATIONS == set()


def test_every_action_permission_is_a_mutating_one_so_d22_covers_it_by_construction() -> None:
    """The D-22 clause in `may_act` reads `permission in MUTATING_PERMISSIONS`, so an
    action declaring a NON-mutating permission would be one an impersonating operator could
    run — and nothing would look wrong: the permission would still be checked, the audit
    row would still be written, and the refusal simply would not happen.

    That is the failure this asserts against. It is not a restatement of the registry: it
    says that whatever permission a future action picks, it has to be one D-22 already
    knows about.

    FAILS IF: an action is registered with a read permission (`leads:read`, `calls:read`),
    which is the plausible mistake — a planner READS, so the read permission looks right.
    """
    for tool in WRITE_TOOLS:
        assert tool.permission in MUTATING_PERMISSIONS, tool.name


async def test_an_impersonating_operator_is_refused_every_action_in_the_registry() -> None:
    """The property above, driven through the code that answers it rather than inferred
    from the two sets.

    `may_act` is `requires()`'s ladder asked by a non-route caller, and it has one arm that
    is NOT the role table — `kb:write` delegates to `kb/curation.may_curate_knowledge`,
    which reads an owner-controlled column. That arm is the one a set comparison cannot
    reach, and it is why this drives a session: an account whose owner switched staff
    curation ON must still refuse an impersonating operator.

    The same actor with `impersonating=False` is asserted to be ALLOWED, so this cannot
    pass by refusing everybody — the vacuous version of this test.

    FAILS IF: D-22's clause is dropped from `may_act`, or the curation predicate stops
    restating it.
    """
    tenant_id, _slug, token = await _make_tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(text("UPDATE organizations SET staff_may_curate_knowledge = true"))
    user_id = _user_of(token)
    viewing = _actor(tenant_id, user_id, role="superadmin")
    viewing = write_tools.ToolActor(
        tenant_id=viewing.tenant_id,
        user_id=viewing.user_id,
        role=viewing.role,
        impersonating=True,
    )
    signed_in = _actor(tenant_id, user_id, role="owner")
    async with tenant_session(tenant_id) as session:
        for tool in WRITE_TOOLS:
            assert not await may_act(session, viewing, tool.permission), tool.name
            # NOT VACUOUS: the same permission, held by an ordinary owner, is granted.
            if role_has("owner", tool.permission):
                assert await may_act(session, signed_in, tool.permission), tool.name


async def test_an_impersonating_operator_cannot_even_be_offered_a_proposal() -> None:
    """`confirm` is the gate and `plan_write`'s check is advisory — but "advisory" must not
    mean "absent". A card drawn for a change the door will refuse teaches a person that the
    assistant's suggestions are unreliable, and it is also the surface a jailbroken model
    would reach for: a proposal it can show is a proposal it can claim to have applied.

    FAILS IF: `plan_write` stops asking `may_act`, or asks it after planning.
    """
    tenant_id, _slug, token = await _make_tenant()
    campaign_id = await _make_campaign(tenant_id)
    actor = _actor(tenant_id, _user_of(token), role="superadmin")
    impersonating = write_tools.ToolActor(
        tenant_id=actor.tenant_id,
        user_id=actor.user_id,
        role=actor.role,
        impersonating=True,
    )
    with pytest.raises(write_tools.WriteRefusedError) as refusal:
        await write_tools.plan_write(
            "campaign_pause",
            json.dumps({"campaign_id": str(campaign_id)}),
            actor=impersonating,
        )
    # The sentence names the tool and the role, never the campaign and never a value.
    assert "campaign_pause" in str(refusal.value)


# ------------------------------------------------------- 2. the egress strip on the card


async def test_a_proposal_card_carries_no_invisible_characters_in_any_rendered_field() -> None:
    """THE APPROVAL MODEL IS "THE PERSON AUTHORISES THE STRING THEY CAN SEE", and it fails
    silently the moment a rendered value and a stored one can differ.

    An agent named with a tag-block sentence renders as its visible half on the card and
    carries the invisible half into whatever the browser does with it. `plan_write` strips
    EVERY rendered field for that reason; it used to strip three of six and rely on each
    planner stripping its own, which is a convention rather than a property and is the kind
    a seventh tool forgets.

    Driven through `agent_rename`, whose planner quotes the agent's CURRENT name back —
    i.e. a string this platform did not author and did not review.

    FAILS IF: a rendered field is added to `CopilotProposalEvent` without joining the strip,
    or the central strip is removed on the argument that the planners do it.
    """
    tenant_id, _slug, token = await _make_tenant()
    # THE AGENT IS CREATED BY `lifecycle.create_agent` — the one function that writes an
    # `agents` row (`AGENT_STATE_WRITERS`) — and only then given the payload in its NAME.
    # A hand-written INSERT would have to reproduce the compliance floor (hard rule 5) and
    # would go stale the day a column joins it.
    async with tenant_session(tenant_id) as session:
        agent_id = await lifecycle.create_agent(
            session,
            tenant_id=tenant_id,
            name="Reception",
            direction="inbound",
            language_primary="te-IN",
        )
        await session.execute(
            text("UPDATE agents SET name = :name WHERE id = :id"),
            {"id": agent_id, "name": f"Reception{_INVISIBLE_PAYLOAD}"},
        )
    # `agent_rename` is Tier 1, so the CARD comes from the planner rather than from
    # `plan_write`. Both surfaces are asserted: the plan the tool composed, and the receipt
    # `run_immediate` renders from it.
    actor = _actor(tenant_id, _user_of(token))
    async with tenant_session(tenant_id) as session:
        plan = await write_tools._BY_NAME["agent_rename"].plan(
            session, actor, {"agent_id": str(agent_id), "name": "Front desk"}
        )
    for rendered in (plan.title, plan.summary, plan.proposed, plan.reversal, plan.current or ""):
        assert not has_invisible(rendered)
    # And the CANONICAL arguments — what actually executes — carry none either, which is
    # the half a rendering strip cannot supply.
    assert not has_invisible(str(plan.args["name"]))


async def test_a_confirmable_card_is_stripped_by_the_event_and_not_by_its_planner() -> None:
    """The central strip, isolated: a planner that forgot its own is still rendered safely.

    A fake `Plan` carrying the payload in every field goes through `plan_write`'s event
    construction. This is the only way to assert the property WITHOUT relying on the seven
    planners that currently do it themselves — which is the whole point of moving it.

    FAILS IF: `plan_write` narrows the strip back to `summary`/`cost`/`reversal`.
    """
    tenant_id, _slug, token = await _make_tenant()
    campaign_id = await _make_campaign(tenant_id)
    actor = _actor(tenant_id, _user_of(token))
    tool = write_tools._BY_NAME["campaign_pause"]
    original = tool.plan

    async def _sloppy(session: Any, who: Any, args: Any) -> Any:
        plan = await original(session, who, args)
        return type(plan)(
            object_id=plan.object_id,
            title=plan.title + _INVISIBLE_PAYLOAD,
            summary=plan.summary + _INVISIBLE_PAYLOAD,
            current=(plan.current or "") + _INVISIBLE_PAYLOAD,
            proposed=plan.proposed + _INVISIBLE_PAYLOAD,
            cost=_INVISIBLE_PAYLOAD,
            reversal=plan.reversal + _INVISIBLE_PAYLOAD,
            args=plan.args,
        )

    patched = ActionTool(
        name=tool.name,
        tier=tool.tier,
        permission=tool.permission,
        object_type=tool.object_type,
        audit_action=tool.audit_action,
        schema=tool.schema,
        plan=_sloppy,
        execute=tool.execute,
        where=tool.where,
    )
    write_tools._BY_NAME[tool.name] = patched
    try:
        event = await write_tools.plan_write(
            tool.name, json.dumps({"campaign_id": str(campaign_id)}), actor=actor
        )
    finally:
        write_tools._BY_NAME[tool.name] = tool
    for rendered in (
        event.title,
        event.summary,
        event.proposed,
        event.reversal,
        event.current or "",
        event.cost or "",
    ):
        assert not has_invisible(rendered)


# ---------------------------------------------------------------------- 3. tenancy (RLS)


async def test_a_neighbours_campaign_is_a_404_and_is_never_described() -> None:
    """A campaign id is the one action argument a person can read off a URL, so it is the
    one most likely to be typed, guessed or echoed out of an earlier turn in another
    account's tab. RLS answers, and the refusal must not distinguish "not yours" from "does
    not exist" — the two together are an existence oracle over another tenant's ids.

    Both directions are driven, so this cannot pass by refusing everybody.

    FAILS IF: a planner grows a `WHERE tenant_id = :tid` and starts answering 403, or the
    session stops being tenant-scoped.
    """
    mine, _slug, my_token = await _make_tenant()
    theirs, _their_slug, _their_token = await _make_tenant()
    their_campaign = await _make_campaign(theirs)
    actor = _actor(mine, _user_of(my_token))
    with pytest.raises(ProblemError) as refused:
        await write_tools.plan_write(
            "campaign_pause", json.dumps({"campaign_id": str(their_campaign)}), actor=actor
        )
    assert refused.value.status == 404
    # NOT VACUOUS: my own campaign plans fine through the identical call.
    my_campaign = await _make_campaign(mine)
    event = await write_tools.plan_write(
        "campaign_pause", json.dumps({"campaign_id": str(my_campaign)}), actor=actor
    )
    assert event.object_id == str(my_campaign)


async def test_a_proposal_token_is_not_a_way_to_carry_an_id_across_accounts() -> None:
    """The token carries `sub` (the tenant) and `args` (the ids) together, so a token minted
    in one account and replayed in another is refused on the tenant BEFORE its arguments are
    ever read. `write_tools_test` asserts that refusal; what is asserted here is the thing
    behind it — that the executor never sees a session belonging to a tenant other than the
    one the token names, because `confirm` runs on the CALLER's session and the caller's
    tenant is what was compared.

    FAILS IF: `_verify` stops comparing `sub`, or `confirm` starts opening a session from
    the token instead of using the request's.
    """
    mine, _slug, my_token = await _make_tenant()
    actor = _actor(mine, _user_of(my_token))
    campaign_id = await _make_campaign(mine)
    event = await write_tools.plan_write(
        "campaign_pause", json.dumps({"campaign_id": str(campaign_id)}), actor=actor
    )
    theirs, _their_slug, their_token = await _make_tenant()
    other = _principal(theirs, _user_of(their_token))
    async with tenant_session(theirs) as session:
        with pytest.raises(ProblemError) as refused:
            await write_tools.confirm(session, event.token, principal=other, ip=None)
    assert refused.value.status == 403
    # The campaign in the ORIGINAL account is untouched: the refusal happened before the
    # burn, so the person it was minted for can still use it.
    async with tenant_session(mine) as session:
        status = (
            await session.execute(
                text("SELECT status FROM campaigns WHERE id = :cid"), {"cid": campaign_id}
            )
        ).scalar_one()
    assert status != "paused"


# ------------------------------------------- 4. a model-chosen argument cannot grow itself


def test_every_action_argument_is_a_uuid_a_closed_set_or_a_bounded_string() -> None:
    """WHAT A USER CAN TALK A MODEL INTO PUTTING IN A TOOL CALL IS UNBOUNDED TEXT, and a
    refusal that quotes the offending value puts that text into the next turn's prompt
    (`service._with_tool_result`). So every string argument has to be bounded in the schema
    that parses it, not merely validated later.

    `topic_key` was the one that was not: `kb.proposals.gap_refusal` answers an unrecognised
    key by quoting it, so an arbitrarily long attacker-chosen slug came straight back into
    the prompt. It is now bounded by the longest key that could ever be legitimate, derived
    from the closed set itself.

    FAILS IF: a new action takes a free-text argument with no `max_length`.
    """
    for tool in WRITE_TOOLS:
        properties = tool.schema["function"]["parameters"]["properties"]
        assert properties, tool.name
    parsed = write_tools._ProposeKnowledgeArgs.model_fields["topic_key"]
    assert parsed is not None
    with pytest.raises(write_tools.WriteRefusedError) as refusal:
        write_tools.parse_args(
            write_tools._ProposeKnowledgeArgs,
            {
                "agent_id": str(uuid.uuid4()),
                "name": "Opening hours",
                "body": "x" * 200,
                "origin": "gap_digest",
                "topic_key": "q_" + "a" * 5_000,
            },
        )
    said = str(refusal.value)
    assert "topic_key" in said
    # THE VALUE IS NEVER ECHOED — that is the whole reason this goes through Pydantic
    # rather than through the refusal that quotes it.
    assert "aaaa" not in said


# -------------------------------------------------------------- 5. the two memory stores


async def test_the_two_memory_stores_cannot_collide_because_each_keys_a_different_table() -> None:
    """`copilot/memory.recall`'s ONLY predicate is `user_id` — RLS answers "which tenant"
    and never "which person" — so if an operator's memory could ever land in
    `copilot_memories` under an id that collided with a member's, a client asking their own
    assistant a question would get an operator's notes about their account read back into
    the answer.

    `tests/admin_copilot_billing_test.py` asserts the two tables do not share rows. What is
    asserted here is WHY that cannot change by accident: each table's user column is a
    foreign key to a DIFFERENT table, so the collision has no way to be written at all. An
    admin id inserted into the client table is a constraint violation, which is the
    strongest form this defence can take.

    FAILS IF: somebody drops either foreign key to "make the memory stores symmetrical".
    """
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT c.conrelid::regclass::text, c.confrelid::regclass::text "
                    "FROM pg_constraint c "
                    "WHERE c.contype = 'f' "
                    "  AND c.conrelid::regclass::text IN "
                    "      ('copilot_memories', 'admin_copilot_memories') "
                    "  AND (SELECT a.attname FROM pg_attribute a "
                    "       WHERE a.attrelid = c.conrelid "
                    "         AND a.attnum = c.conkey[1]) "
                    "      IN ('user_id', 'admin_user_id')"
                )
            )
        ).all()
        references = {str(child): str(parent) for child, parent in rows}
    assert references["copilot_memories"] == "users"
    assert references["admin_copilot_memories"] == "admin_users"


# --------------------------------------------------------- 6. the admin turn's own frames


async def test_an_admin_turn_that_calls_a_tool_shows_the_operator_what_it_ran(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE ADMIN ROUTE CONSUMED `step` AND `action` EVENTS AND YIELDED NOTHING FOR THEM.

    The observational half is a real cost on its own — an operator asking about an incident
    watched a spinner while four platform lookups ran — but the reason this is a test rather
    than a polish item is the OTHER frame. `run_immediate` writes the change and its
    `audit_log` row before the route's loop ever sees the event, so dropping `action` would
    have meant a change applied with no receipt on the screen of the person who caused it.
    It is unreachable today (an admin principal carries no tenant outside a view-as session,
    and inside one every action permission is refused by D-22) — which is exactly why it
    would have gone unnoticed until the ladder changed.

    A `step` frame is the reachable half, so that is what this drives.

    FAILS IF: the admin route stops forwarding a frame the client route forwards.
    """
    from apps.api.billing import ai_quota

    async def _not_tripped(*args: Any, **kwargs: Any) -> bool:
        return False

    monkeypatch.setattr(ai_quota, "platform_brake_tripped", _not_tripped)
    settings_patched = __import__(
        "apps.api.core.settings", fromlist=["get_settings"]
    ).get_settings()
    monkeypatch.setattr(settings_patched, "azure_openai_resource", "calevate-test", raising=False)
    monkeypatch.setattr(settings_patched, "azure_openai_api_key", "k", raising=False)
    monkeypatch.setattr(settings_patched, "azure_openai_deployment", "dep", raising=False)
    monkeypatch.setattr(settings_patched, "sarvam_api_key", None, raising=False)

    turns = [
        (chat.ToolCall(id="c1", name="platform_tenants", arguments="{}"),),
        (),
    ]

    def _stream(leg: Any, messages: Any, **kwargs: Any) -> Any:
        calls = turns.pop(0) if turns else ()

        async def _iterate() -> Any:
            if not calls:
                yield chat.StreamEvent(text="Nine accounts.")
            yield chat.StreamEvent(
                outcome=chat.ChatOutcome(
                    content="" if calls else "Nine accounts.",
                    tool_calls=calls,
                    finish_reason="tool_calls" if calls else "stop",
                    usage=chat.TokenUsage(prompt_tokens=10, output_tokens=10),
                )
            )

        return _iterate()

    monkeypatch.setattr(chat, "stream", _stream)

    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    body: dict[str, Any] = {
        "screen": {"route": "/admin/tenants", "title": "Accounts", "realm": "admin"},
        "question": "how many accounts are live",
        "fields": [],
        "facts": [],
        "history": [],
        "tenant_id": None,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as client:
        response = await client.post(
            "/v1/admin/copilot/ask",
            json=body,
            headers={"Authorization": f"Bearer dev:admin:{admin_id}"},
        )
    assert response.status_code == 200
    assert "event: step" in response.text
    # And nothing about the tool's ARGUMENTS or its result is in the audit-bearing frames —
    # a step is observational and is the one frame that must never be logged or stored.
    assert "event: done" in response.text
