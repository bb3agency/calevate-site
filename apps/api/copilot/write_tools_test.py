"""The write surface: proposing changes nothing, and confirming changes it exactly once.

WHAT IS PROVED HERE, and each one is a property whose absence is a security bug rather
than a bug:

1. **A proposal is a read.** Every tool is driven and the row it names is re-read
   afterwards. A tool that mutated would pass every other test in this file.
2. **Confirm executes ONCE.** The same token twice is refused, and the world moved once.
3. **A proposal is unforgeable and non-transferable.** Tampered, expired, minted for
   another tenant, minted for another person — four refusals, one shape.
4. **Cross-tenant is refused twice over** (hard rule 1): by the `sub` claim before the
   work starts, and by RLS behind it.
5. **The permission is re-checked at CONFIRM**, against the role the session actually has
   rather than the one it had when the model was talking.
6. **The gate underneath still bites.** A campaign that is not running is refused through
   this door exactly as through the button, and a confirmed DNC add still enqueues D-428(b)'s
   recall — because the executor calls the same function, not a copy of it.
7. **The act is on the ledger**, naming the person who agreed to it, with no value in it.

CONCURRENCY AND SHARED STATE: every test mints its own tenant, and the one shared store —
Redis, for the replay guard — is keyed on a per-proposal `jti`, so two runs of this file
cannot see each other's markers.
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from typing import Any
from uuid import UUID

import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.api_security_test import _make_tenant

from apps.api.billing import ai_quota
from apps.api.compliance import dnc_recall
from apps.api.copilot import service, write_tools
from apps.api.copilot.schemas import CopilotAskIn, CopilotProposalEvent
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from apps.workers import chat

CONFIRM = "/v1/copilot/confirm"


# --- fixtures a tenant needs before any of this means anything --------------------------


def _principal(tenant_id: UUID, user_id: UUID, *, role: str = "owner") -> Principal:
    return Principal(realm="client", user_id=user_id, tenant_id=tenant_id, role=role)


def _actor(tenant_id: UUID, user_id: UUID, *, role: str = "owner") -> write_tools.ToolActor:
    resolved = write_tools.actor_for(_principal(tenant_id, user_id, role=role))
    assert resolved is not None
    return resolved


def _user_of(token: str) -> UUID:
    """`_make_tenant` hands back `dev:client:<uuid>`; the uuid is the member."""
    return UUID(token.rsplit(":", 1)[1])


async def _lead_of(tenant_id: UUID) -> UUID:
    async with tenant_session(tenant_id) as session:
        row = (await session.execute(text("SELECT id FROM leads LIMIT 1"))).first()
    assert row is not None
    return UUID(str(row[0]))


async def _lead_status(tenant_id: UUID, lead_id: UUID) -> str:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(text("SELECT status FROM leads WHERE id = :i"), {"i": lead_id})
        ).first()
    assert row is not None
    return str(row[0])


async def _make_campaign(tenant_id: UUID, *, status: str = "running") -> UUID:
    campaign_id = uuid7()
    async with tenant_session(tenant_id) as session:
        agent = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).first()
        assert agent is not None
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, status, "
                "classification, created_at, updated_at) VALUES (:id, :tid, :aid, "
                "'Winter checkup', :st, 'service', now(), now())"
            ),
            {"id": campaign_id, "tid": tenant_id, "aid": agent[0], "st": status},
        )
    return campaign_id


async def _campaign_status(tenant_id: UUID, campaign_id: UUID) -> str:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT status FROM campaigns WHERE id = :i"), {"i": campaign_id}
            )
        ).first()
    assert row is not None
    return str(row[0])


async def _dnc_count(tenant_id: UUID) -> int:
    """THIS TENANT'S OWN entries. `dnc_list` under RLS also hands back the GLOBAL rows
    (`tenant_id IS NULL`), which is correct for the product — a number a client cannot
    un-suppress is still one they should see — and wrong for a count that is asserting what
    THIS test wrote."""
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT count(*) FROM dnc_list WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).first()
    assert row is not None
    return int(row[0])


async def _audit(tenant_id: UUID) -> list[tuple[str, str | None, str | None]]:
    """`(action, object_type, object_id)`, oldest first.

    NO `summary` COLUMN IS SELECTED BECAUSE `audit_log` HAS NONE — `write_audit`'s summary
    goes to the log stream through `redact_mapping` (`compliance/audit.py`), and a test
    that selected it would assert against a column this repo deliberately does not have.
    """
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT action, object_type, object_id FROM audit_log "
                    "WHERE tenant_id = :t ORDER BY at"
                ),
                {"t": str(tenant_id)},
            )
        ).all()
    return [(str(r[0]), r[1], r[2]) for r in rows]


async def _outbox_jobs(tenant_id: UUID) -> list[str]:
    """The side effects this tenant's confirm enqueued. `outbox_messages` is a GLOBAL table
    (`core/deps.global_db` lists it), so the tenant is a payload predicate rather than an
    RLS one — and the filter is what keeps this assertion about our own row on a shared
    database."""
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text("SELECT job FROM outbox_messages WHERE payload->>'tenant_id' = :t"),
                {"t": str(tenant_id)},
            )
        ).all()
    return [str(r[0]) for r in rows]


async def _confirm(tenant_id: UUID, user_id: UUID, token: str, *, role: str = "owner") -> Any:
    """One confirm in its own transaction, the way the route's `Depends(db)` gives it."""
    async with tenant_session(tenant_id) as session:
        return await write_tools.confirm(
            session, token, principal=_principal(tenant_id, user_id, role=role), ip="203.0.113.7"
        )


# --- 1. the schema is a constant --------------------------------------------------------


def test_the_tool_schemas_are_the_same_bytes_for_every_caller() -> None:
    """The prompt-cache property, asserted rather than asserted-in-a-comment.

    Two calls, byte-identical JSON, and the same tools in the same order. A future
    "only offer what this role can do" would fail here, which is the point:
    `write_tool_schemas` is part of the cacheable prefix and the refusal belongs in the
    tool, not in the list."""
    first = json.dumps(write_tools.write_tool_schemas(), sort_keys=False)
    second = json.dumps(write_tools.write_tool_schemas(), sort_keys=False)
    assert first == second
    names = [schema["function"]["name"] for schema in write_tools.write_tool_schemas()]
    assert names == ["lead_set_status", "dnc_add", "campaign_pause"]
    for schema in write_tools.write_tool_schemas():
        function = schema["function"]
        assert function["strict"] is True
        parameters = function["parameters"]
        # Every property required and no extras — openai-python's strict subset.
        assert parameters["additionalProperties"] is False
        assert set(parameters["required"]) == set(parameters["properties"])


def test_the_schema_list_is_a_copy_so_one_request_cannot_edit_the_next_ones() -> None:
    """`prompt.set_fields_tool` is a function for this reason; so is this."""
    mutated = write_tools.write_tool_schemas()
    mutated[0]["function"] = "tampered"
    assert write_tools.write_tool_schemas()[0]["function"]["name"] == "lead_set_status"


# --- 2. proposing changes nothing -------------------------------------------------------


async def test_every_tool_proposes_a_readable_change_and_writes_nothing() -> None:
    """The central claim of the design, driven once per tool.

    Each proposal is checked for the pair a person decides on — the CURRENT value and the
    proposed one — and then the row is re-read. A tool that performed its action would
    still return a plausible proposal; the re-read is what would catch it.
    """
    tenant_id, _slug, token = await _make_tenant()
    user_id = _user_of(token)
    lead_id = await _lead_of(tenant_id)
    campaign_id = await _make_campaign(tenant_id)
    actor = _actor(tenant_id, user_id)

    lead_proposal = await write_tools.plan_write(
        "lead_set_status", json.dumps({"lead_id": str(lead_id), "status": "hot"}), actor=actor
    )
    assert lead_proposal.tool == "lead_set_status"
    assert lead_proposal.object_id == str(lead_id)
    assert (lead_proposal.current, lead_proposal.proposed) == ("New", "Hot")
    assert "Hot" in lead_proposal.summary

    dnc_proposal = await write_tools.plan_write(
        "dnc_add", json.dumps({"lead_id": str(lead_id), "reason": "customer_request"}), actor=actor
    )
    assert dnc_proposal.current == "Not suppressed"

    pause_proposal = await write_tools.plan_write(
        "campaign_pause", json.dumps({"campaign_id": str(campaign_id)}), actor=actor
    )
    assert (pause_proposal.current, pause_proposal.proposed) == ("running", "paused")
    assert "Winter checkup" in pause_proposal.summary

    # AND NOTHING MOVED.
    assert await _lead_status(tenant_id, lead_id) == "new"
    assert await _dnc_count(tenant_id) == 0
    assert await _campaign_status(tenant_id, campaign_id) == "running"
    assert await _audit(tenant_id) == []


async def test_a_proposal_never_carries_the_phone_number_it_is_about() -> None:
    """`dnc_add` names the number by LEAD ID because `sanitize.assert_redacted` refuses a
    payload that still looks like a phone number — so the number must not travel back out
    either, in the token or in the sentence (hard rule 6)."""
    tenant_id, _slug, token = await _make_tenant()
    lead_id = await _lead_of(tenant_id)
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT phone_e164 FROM leads WHERE id = :i"), {"i": lead_id}
            )
        ).first()
    assert row is not None
    phone = str(row[0])

    proposal = await write_tools.plan_write(
        "dnc_add", json.dumps({"lead_id": str(lead_id)}), actor=_actor(tenant_id, _user_of(token))
    )
    assert phone not in proposal.summary
    assert phone not in proposal.token
    claims = jwt.decode(proposal.token, options={"verify_signature": False})
    assert phone not in json.dumps(claims)


async def test_a_lead_from_another_tenant_is_not_found_rather_than_described() -> None:
    """RLS's answer, and it is the same answer as "no such lead" — deliberately."""
    tenant_a, _slug_a, token_a = await _make_tenant()
    tenant_b, _slug_b, _token_b = await _make_tenant()
    foreign_lead = await _lead_of(tenant_b)

    with pytest.raises(ProblemError) as refused:
        await write_tools.plan_write(
            "lead_set_status",
            json.dumps({"lead_id": str(foreign_lead), "status": "hot"}),
            actor=_actor(tenant_a, _user_of(token_a)),
        )
    assert refused.value.status == 404


async def test_a_malformed_tool_call_is_a_refusal_the_model_can_fix() -> None:
    """`WriteRefusedError`, not a `ProblemError`: it goes back to the model as a tool
    result, and it names the FIELD and never the value."""
    tenant_id, _slug, token = await _make_tenant()
    actor = _actor(tenant_id, _user_of(token))

    with pytest.raises(write_tools.WriteRefusedError) as bad_json:
        await write_tools.plan_write("lead_set_status", "{not json", actor=actor)
    assert "JSON" in bad_json.value.reason

    with pytest.raises(write_tools.WriteRefusedError) as bad_status:
        await write_tools.plan_write(
            "lead_set_status",
            json.dumps({"lead_id": str(uuid.uuid4()), "status": "sizzling"}),
            actor=actor,
        )
    assert "`status`" in bad_status.value.reason

    with pytest.raises(write_tools.WriteRefusedError) as no_actor:
        await write_tools.plan_write("campaign_pause", json.dumps({}), actor=None)
    assert "signed-in account" in no_actor.value.reason


# --- 3. permission, at both ends --------------------------------------------------------


async def test_a_role_without_the_permission_is_offered_nothing_to_confirm() -> None:
    """`staff` holds `leads:write` and NOT `leads:dispatch` (core/rbac.py), which is why
    this asserts both directions on one role: the tool a staff member may drive is
    proposed, and the two they may not are refused inside the tool rather than by a
    missing schema."""
    tenant_id, _slug, token = await _make_tenant(role="staff")
    user_id = _user_of(token)
    staff = _actor(tenant_id, user_id, role="staff")
    lead_id = await _lead_of(tenant_id)
    campaign_id = await _make_campaign(tenant_id)

    allowed = await write_tools.plan_write(
        "lead_set_status", json.dumps({"lead_id": str(lead_id), "status": "hot"}), actor=staff
    )
    assert allowed.tool == "lead_set_status"

    for name, args in (
        ("dnc_add", {"lead_id": str(lead_id)}),
        ("campaign_pause", {"campaign_id": str(campaign_id)}),
    ):
        with pytest.raises(write_tools.WriteRefusedError) as refused:
            await write_tools.plan_write(name, json.dumps(args), actor=staff)
        assert "role may not" in refused.value.reason


async def test_a_person_demoted_between_proposing_and_confirming_is_refused() -> None:
    """THE PROPOSE-TIME CHECK IS ADVISORY AND THIS IS THE ONE THAT COUNTS.

    Same person, same tenant, same token — a role that no longer holds the permission. The
    token is a description of an intent, never a grant of authority, and this is the test
    that says so.
    """
    tenant_id, _slug, token = await _make_tenant()
    user_id = _user_of(token)
    campaign_id = await _make_campaign(tenant_id)
    proposal = await write_tools.plan_write(
        "campaign_pause",
        json.dumps({"campaign_id": str(campaign_id)}),
        actor=_actor(tenant_id, user_id),
    )

    with pytest.raises(ProblemError) as refused:
        await _confirm(tenant_id, user_id, proposal.token, role="staff")
    assert refused.value.status == 403
    # AND IT SAYS WHAT TO DO NEXT. This refusal reaches a person looking at a confirmation
    # card, so a bare "you do not have permission" would leave them with a dead button and
    # no next step — BACKEND-PATTERNS §3's ladder, which `ProblemError.forbidden`'s default
    # cannot satisfy because it carries no remediation at all.
    assert refused.value.remediation == (
        "Ask an owner or manager on this account to confirm it instead."
    )
    assert await _campaign_status(tenant_id, campaign_id) == "running"


async def test_a_read_only_view_as_session_may_not_confirm() -> None:
    """D-22 through `_may`: `leads:dispatch` is in `MUTATING_PERMISSIONS`, so an
    impersonating principal is refused even though its role grants it. Asserted here as
    well as at the route because `confirm` is the function a future caller would reach
    for."""
    tenant_id, _slug, token = await _make_tenant()
    user_id = _user_of(token)
    campaign_id = await _make_campaign(tenant_id)
    proposal = await write_tools.plan_write(
        "campaign_pause",
        json.dumps({"campaign_id": str(campaign_id)}),
        actor=_actor(tenant_id, user_id),
    )
    viewing = Principal(
        realm="client", user_id=user_id, tenant_id=tenant_id, role="owner", impersonating=True
    )
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as refused:
            await write_tools.confirm(session, proposal.token, principal=viewing, ip=None)
    assert refused.value.status == 403
    assert await _campaign_status(tenant_id, campaign_id) == "running"


# --- 4. the token: once, and only where it was minted -----------------------------------


async def test_confirm_executes_exactly_once_and_the_replay_is_refused() -> None:
    """The whole replay argument in one test: a signature is valid until it expires, so
    the `jti` burn is what makes a proposal a single decision."""
    tenant_id, _slug, token = await _make_tenant()
    user_id = _user_of(token)
    lead_id = await _lead_of(tenant_id)
    proposal = await write_tools.plan_write(
        "lead_set_status",
        json.dumps({"lead_id": str(lead_id), "status": "hot"}),
        actor=_actor(tenant_id, user_id),
    )

    first = await _confirm(tenant_id, user_id, proposal.token)
    assert first.applied is True
    assert await _lead_status(tenant_id, lead_id) == "hot"

    with pytest.raises(ProblemError) as replay:
        await _confirm(tenant_id, user_id, proposal.token)
    assert replay.value.code == "copilot_proposal_already_used"

    # ONE act, one row — the replay added neither a change nor a ledger entry.
    assert [row[0] for row in await _audit(tenant_id)] == ["lead.status_set"]


async def test_a_second_proposal_for_an_unchanged_lead_reports_that_it_changed_nothing() -> None:
    """`applied: false` on a 200 is a real answer (D-65). A path that reported success for
    a no-op would put a second act in an append-only ledger claiming a change that did not
    happen — so the ROW is still written (a person did decide) and `moved` is False."""
    tenant_id, _slug, token = await _make_tenant()
    user_id = _user_of(token)
    lead_id = await _lead_of(tenant_id)
    actor = _actor(tenant_id, user_id)
    args = json.dumps({"lead_id": str(lead_id), "status": "hot"})

    first = await write_tools.plan_write("lead_set_status", args, actor=actor)
    await _confirm(tenant_id, user_id, first.token)
    # A SECOND PROPOSAL, not a replay of the first: the burn would refuse that, and the
    # question here is what the EXECUTOR says when there is nothing left to do.
    again = await write_tools.plan_write("lead_set_status", args, actor=actor)
    second = await _confirm(tenant_id, user_id, again.token)
    assert second.applied is False
    assert "already" in second.detail


async def test_a_tampered_or_foreign_signature_is_refused() -> None:
    """Two forgeries, one refusal shape: a flipped byte, and a token signed with a key
    this deployment does not use. Nothing distinguishes them for the caller — this
    endpoint must not be an oracle."""
    tenant_id, _slug, token = await _make_tenant()
    user_id = _user_of(token)
    lead_id = await _lead_of(tenant_id)
    proposal = await write_tools.plan_write(
        "lead_set_status",
        json.dumps({"lead_id": str(lead_id), "status": "hot"}),
        actor=_actor(tenant_id, user_id),
    )

    head, _payload, signature = proposal.token.split(".")
    flipped = f"{head}.{_payload}.{'A' if signature[0] != 'A' else 'B'}{signature[1:]}"
    with pytest.raises(ProblemError) as tampered:
        await _confirm(tenant_id, user_id, flipped)
    assert tampered.value.code == "copilot_proposal_invalid"

    forged = jwt.encode(
        {
            "aud": write_tools.PROPOSAL_AUDIENCE,
            "sub": str(tenant_id),
            write_tools.ACTOR_CLAIM: {"sub": str(user_id)},
            "jti": str(uuid7()),
            "iat": 1,
            "exp": 4_102_444_800,
            "tool": "lead_set_status",
            "args": {"lead_id": str(lead_id), "status": "won"},
            "obj": str(lead_id),
        },
        "an-attackers-own-thirty-two-byte-key!!",
        algorithm="HS256",
    )
    with pytest.raises(ProblemError) as forgery:
        await _confirm(tenant_id, user_id, forged)
    assert forgery.value.code == "copilot_proposal_invalid"
    assert await _lead_status(tenant_id, lead_id) == "new"


async def test_an_expired_proposal_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """The TTL, exercised by minting one that is already past — not by sleeping."""
    tenant_id, _slug, token = await _make_tenant()
    user_id = _user_of(token)
    lead_id = await _lead_of(tenant_id)
    monkeypatch.setattr(write_tools, "PROPOSAL_TTL", timedelta(minutes=-30))
    proposal = await write_tools.plan_write(
        "lead_set_status",
        json.dumps({"lead_id": str(lead_id), "status": "hot"}),
        actor=_actor(tenant_id, user_id),
    )
    monkeypatch.undo()

    with pytest.raises(ProblemError) as expired:
        await _confirm(tenant_id, user_id, proposal.token)
    assert expired.value.code == "copilot_proposal_invalid"
    assert await _lead_status(tenant_id, lead_id) == "new"


async def test_a_proposal_minted_for_tenant_a_cannot_be_confirmed_against_tenant_b() -> None:
    """HARD RULE 1, on the surface where a signed token would otherwise be a way around it.

    Tenant B's own member confirms tenant A's token. The `sub` claim refuses it before any
    work starts; if it did not, RLS would still find nothing — but "refused" and "found
    nothing" are different answers and the first one is the one this design owes.
    """
    tenant_a, _slug_a, token_a = await _make_tenant()
    tenant_b, _slug_b, token_b = await _make_tenant()
    lead_a = await _lead_of(tenant_a)
    proposal = await write_tools.plan_write(
        "lead_set_status",
        json.dumps({"lead_id": str(lead_a), "status": "hot"}),
        actor=_actor(tenant_a, _user_of(token_a)),
    )

    with pytest.raises(ProblemError) as crossed:
        await _confirm(tenant_b, _user_of(token_b), proposal.token)
    assert crossed.value.status == 403
    assert await _lead_status(tenant_a, lead_a) == "new"
    assert await _audit(tenant_b) == []


async def test_a_colleagues_proposal_cannot_be_confirmed_by_someone_else() -> None:
    """Same tenant, different person. The audit row has to name somebody who actually
    decided, and `act.sub` is what makes that true."""
    tenant_id, _slug, token = await _make_tenant()
    lead_id = await _lead_of(tenant_id)
    proposal = await write_tools.plan_write(
        "lead_set_status",
        json.dumps({"lead_id": str(lead_id), "status": "hot"}),
        actor=_actor(tenant_id, _user_of(token)),
    )

    with pytest.raises(ProblemError) as wrong_person:
        await _confirm(tenant_id, uuid.uuid4(), proposal.token)
    assert wrong_person.value.status == 403
    assert await _lead_status(tenant_id, lead_id) == "new"


async def test_the_confirm_body_cannot_widen_what_was_proposed() -> None:
    """The arguments are inside the signature, so editing them invalidates the token
    rather than changing the act. This is the reason `CopilotConfirmIn` has ONE field."""
    tenant_id, _slug, token = await _make_tenant()
    user_id = _user_of(token)
    lead_id = await _lead_of(tenant_id)
    proposal = await write_tools.plan_write(
        "lead_set_status",
        json.dumps({"lead_id": str(lead_id), "status": "contacted"}),
        actor=_actor(tenant_id, user_id),
    )
    claims = jwt.decode(proposal.token, options={"verify_signature": False})
    claims["args"]["status"] = "won"
    rewritten = jwt.encode(claims, "not-the-servers-key-but-thirty-two-plus", algorithm="HS256")

    with pytest.raises(ProblemError):
        await _confirm(tenant_id, user_id, rewritten)
    assert await _lead_status(tenant_id, lead_id) == "new"


# --- 5. the gate underneath is untouched ------------------------------------------------


async def test_the_campaign_state_machine_refuses_a_draft_through_the_confirm_path() -> None:
    """PROOF THAT THIS IS NOT A BYPASS (hard rule 5).

    `set_campaign_status` answers a campaign that is not `running` with a 409 naming the
    state, and it answers this door the same way it answers the button — because it IS the
    same call. The transaction rolls back, so the refusal also leaves no audit row.
    """
    tenant_id, _slug, token = await _make_tenant()
    user_id = _user_of(token)
    campaign_id = await _make_campaign(tenant_id, status="draft")
    proposal = await write_tools.plan_write(
        "campaign_pause",
        json.dumps({"campaign_id": str(campaign_id)}),
        actor=_actor(tenant_id, user_id),
    )

    with pytest.raises(ProblemError) as blocked:
        await _confirm(tenant_id, user_id, proposal.token)
    assert blocked.value.status == 409
    assert blocked.value.code == "invalid_status_transition"
    assert await _campaign_status(tenant_id, campaign_id) == "draft"
    assert await _audit(tenant_id) == []


async def test_a_confirmed_dnc_add_still_pulls_back_the_dials_the_vendor_is_holding() -> None:
    """THE SECOND PROOF, and the more important one: a compliance obligation that lives
    INSIDE the service function still runs on this path.

    D-428(b) — a suppression is not honoured until queued dials are recalled — is
    implemented in `dnc.add_numbers`, not in its route. A hand-written INSERT here would
    have suppressed the number and left the recall unqueued, and every other assertion in
    this file would still have passed.
    """
    tenant_id, _slug, token = await _make_tenant()
    user_id = _user_of(token)
    lead_id = await _lead_of(tenant_id)
    proposal = await write_tools.plan_write(
        "dnc_add",
        json.dumps({"lead_id": str(lead_id), "reason": "customer_request"}),
        actor=_actor(tenant_id, user_id),
    )

    outcome = await _confirm(tenant_id, user_id, proposal.token)
    assert outcome.applied is True
    assert await _dnc_count(tenant_id) == 1
    assert await _outbox_jobs(tenant_id) == [dnc_recall.DNC_RECALL_JOB]


async def test_every_confirmed_change_lands_on_the_ledger_with_ids_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Hard rule 4 and hard rule 6 together: the row exists, it names the target by id, and
    the summary that reaches the log stream carries counts and names and no value.

    The assertion is on the SANITIZED LOG EXTRAS rather than on a column, because
    `audit_log` has no summary column (see `_audit`)."""
    import logging

    tenant_id, _slug, token = await _make_tenant()
    user_id = _user_of(token)
    campaign_id = await _make_campaign(tenant_id)
    proposal = await write_tools.plan_write(
        "campaign_pause",
        json.dumps({"campaign_id": str(campaign_id)}),
        actor=_actor(tenant_id, user_id),
    )

    with caplog.at_level(logging.INFO, logger="apps.api.compliance.audit"):
        await _confirm(tenant_id, user_id, proposal.token)

    assert await _audit(tenant_id) == [("campaign.paused", "campaign", str(campaign_id))]
    entries = [r for r in caplog.records if r.getMessage() == "audit"]
    assert entries, "the audit write produced no log line"
    extras = vars(entries[-1])
    assert extras["via"] == "copilot"
    assert extras["tool"] == "campaign_pause"
    assert extras["moved"] is True
    # The campaign's NAME is tenant content and has no business in a log line.
    assert "Winter checkup" not in json.dumps({k: str(v) for k, v in extras.items()})


# --- 6. over real HTTP ------------------------------------------------------------------


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _headers(token: str, slug: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}


async def test_the_confirm_route_carries_out_the_change_and_answers_what_it_did() -> None:
    """The seam over the wire: the status code, the body shape and the permission
    dependency, none of which a direct call to `confirm` proves."""
    tenant_id, slug, token = await _make_tenant()
    lead_id = await _lead_of(tenant_id)
    proposal = await write_tools.plan_write(
        "lead_set_status",
        json.dumps({"lead_id": str(lead_id), "status": "interested"}),
        actor=_actor(tenant_id, _user_of(token)),
    )

    async with _client() as http:
        response = await http.post(
            CONFIRM, headers=_headers(token, slug), json={"token": proposal.token}
        )
    assert response.status_code == 200, response.text
    assert response.json() == {
        "tool": "lead_set_status",
        "object_type": "lead",
        "object_id": str(lead_id),
        "applied": True,
        "detail": "The lead is now marked Interested.",
    }
    assert await _lead_status(tenant_id, lead_id) == "interested"


async def test_the_confirm_route_refuses_a_caller_who_cannot_open_the_assistant() -> None:
    """`staff` does not hold `org:manage`, which is `POST /v1/copilot/ask`'s permission —
    so somebody who cannot ask the assistant cannot complete one of its sentences either.
    The refusal is problem+json, before the body is even read."""
    tenant_id, slug, token = await _make_tenant(role="staff")
    lead_id = await _lead_of(tenant_id)
    proposal = await write_tools.plan_write(
        "lead_set_status",
        json.dumps({"lead_id": str(lead_id), "status": "hot"}),
        actor=_actor(tenant_id, _user_of(token), role="staff"),
    )

    async with _client() as http:
        response = await http.post(
            CONFIRM, headers=_headers(token, slug), json={"token": proposal.token}
        )
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")
    assert await _lead_status(tenant_id, lead_id) == "new"


async def test_the_confirm_route_takes_the_token_and_nothing_else() -> None:
    """`extra="forbid"`: a body that also named a lead would be a body that could disagree
    with the description the person read."""
    _tenant_id, slug, token = await _make_tenant()
    async with _client() as http:
        response = await http.post(
            CONFIRM,
            headers=_headers(token, slug),
            json={"token": "x", "lead_id": str(uuid.uuid4())},
        )
    assert response.status_code == 422


def test_the_proposal_event_model_is_the_shape_the_browser_is_told_about() -> None:
    """The SSE contract in `routes.py`'s description, pinned. A field added or renamed here
    is a browser change, and this is what makes it visible in review."""
    fields = set(CopilotProposalEvent.model_fields)
    assert fields == {
        "token",
        "tool",
        "title",
        "summary",
        "object_type",
        "object_id",
        "current",
        "proposed",
        "expires_at",
    }


# --- 7. the loop seam: a write tool call becomes a proposal event ------------------------
#
# The provider is replaced at `chat.stream`, one layer BELOW the loop, for `loop_test.py`'s
# reason: everything except "what the model said" stays real.


def _turn(*, content: str = "", calls: tuple[chat.ToolCall, ...] = ()) -> list[Any]:
    return [
        *([chat.StreamEvent(text=content)] if content else []),
        chat.StreamEvent(
            outcome=chat.ChatOutcome(
                content=content,
                tool_calls=calls,
                finish_reason="tool_calls" if calls else "stop",
                usage=chat.TokenUsage(prompt_tokens=10, output_tokens=10),
            )
        ),
    ]


def _scripted(
    monkeypatch: pytest.MonkeyPatch, turns: list[list[Any]]
) -> list[list[dict[str, Any]]]:
    """Replace `chat.stream` with a script, recording what each turn was sent."""
    sent: list[list[dict[str, Any]]] = []
    remaining = list(turns)

    def _stream(leg: Any, messages: Any, **kwargs: Any) -> Any:
        sent.append([dict(message) for message in messages])
        events = remaining.pop(0) if remaining else _turn(content="Nothing more to do.")

        async def _iterate() -> Any:
            for event in events:
                yield event

        return _iterate()

    monkeypatch.setattr(chat, "stream", _stream)
    return sent


def _ask() -> CopilotAskIn:
    return CopilotAskIn.model_validate(
        {
            "screen": {"route": "/c/x/campaigns", "title": "Campaigns", "realm": "client"},
            "question": "stop this campaign",
            "fields": [{"id": "note", "label": "Note", "type": "text", "writable": True}],
        }
    )


@pytest.fixture
def azure_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """A deployment holding an Azure credential and no Sarvam key — `loop_test.py`'s
    fixture, so the tool-capable leg is the one that answers."""
    settings = get_settings()
    monkeypatch.setattr(settings, "azure_openai_resource", "calevate-test", raising=False)
    monkeypatch.setattr(settings, "azure_openai_api_key", "k", raising=False)
    monkeypatch.setattr(settings, "azure_openai_deployment", "dep", raising=False)
    monkeypatch.setattr(settings, "sarvam_api_key", None, raising=False)


async def test_a_write_tool_call_becomes_a_proposal_event_and_ends_the_turn(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The seam, end to end through the loop: the tool schemas are offered, the call is
    routed to `plan_write`, and what comes back is a `proposal` event — with the world
    untouched and the run still metered, because a completed model turn is money spent
    whatever it said."""
    tenant_id, _slug, token = await _make_tenant()
    campaign_id = await _make_campaign(tenant_id)
    sent = _scripted(
        monkeypatch,
        [
            _turn(
                content="I can stop that for you.",
                calls=(
                    chat.ToolCall(
                        id="c1",
                        name="campaign_pause",
                        arguments=json.dumps({"campaign_id": str(campaign_id)}),
                    ),
                ),
            )
        ],
    )

    events = [
        event
        async for event in service.run_copilot(_ask(), actor=_actor(tenant_id, _user_of(token)))
    ]

    assert sent, "the provider was never called"
    proposals = [event.proposal for event in events if event.proposal is not None]
    assert len(proposals) == 1
    assert proposals[0].tool == "campaign_pause"
    assert proposals[0].current == "running"
    assert [event for event in events if event.spend is not None]
    assert await _campaign_status(tenant_id, campaign_id) == "running"


async def test_a_refused_write_goes_back_to_the_model_and_not_to_the_person(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The turn cap is FOR this: a model that names a campaign this person may not pause is
    told so as a tool result and answers in words, rather than the person seeing a dead
    end."""
    tenant_id, _slug, token = await _make_tenant(role="staff")
    campaign_id = await _make_campaign(tenant_id)
    sent = _scripted(
        monkeypatch,
        [
            _turn(
                calls=(
                    chat.ToolCall(
                        id="c1",
                        name="campaign_pause",
                        arguments=json.dumps({"campaign_id": str(campaign_id)}),
                    ),
                )
            ),
            _turn(content="I can't pause campaigns from here."),
        ],
    )

    events = [
        event
        async for event in service.run_copilot(
            _ask(), actor=_actor(tenant_id, _user_of(token), role="staff")
        )
    ]

    assert [event.proposal for event in events if event.proposal is not None] == []
    assert any("can't pause" in (event.text or "") for event in events)
    tool_messages = [m for m in sent[-1] if m.get("role") == "tool"]
    assert tool_messages and "NOTHING was proposed" in str(tool_messages[-1]["content"])


async def test_a_turn_that_fills_and_proposes_at_once_is_refused_back_to_the_model(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One act per turn. Honouring half of a mixed turn would either lose the person's fill
    or leave a model that said it was suggesting something having suggested nothing; both
    go back as one refusal instead."""
    tenant_id, _slug, token = await _make_tenant()
    campaign_id = await _make_campaign(tenant_id)
    sent = _scripted(
        monkeypatch,
        [
            _turn(
                calls=(
                    chat.ToolCall(
                        id="c1",
                        name="set_fields",
                        arguments=json.dumps({"items": [{"field_id": "note", "value": "x"}]}),
                    ),
                    chat.ToolCall(
                        id="c2",
                        name="campaign_pause",
                        arguments=json.dumps({"campaign_id": str(campaign_id)}),
                    ),
                )
            ),
            _turn(content="One at a time, then."),
        ],
    )

    events = [
        event
        async for event in service.run_copilot(_ask(), actor=_actor(tenant_id, _user_of(token)))
    ]

    assert [event.fill for event in events if event.fill is not None] == []
    assert [event.proposal for event in events if event.proposal is not None] == []
    tool_messages = [m for m in sent[-1] if m.get("role") == "tool"]
    assert tool_messages and "same turn" in str(tool_messages[-1]["content"])


async def test_the_proposal_reaches_the_browser_as_its_own_sse_event(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Read off the WIRE, because the event NAME and the frame encoding are half the
    contract the browser is built against."""

    async def _not_tripped(*args: Any, **kwargs: Any) -> bool:
        return False

    tenant_id, slug, token = await _make_tenant()
    campaign_id = await _make_campaign(tenant_id)
    monkeypatch.setattr(ai_quota, "platform_brake_tripped", _not_tripped)
    _scripted(
        monkeypatch,
        [
            _turn(
                calls=(
                    chat.ToolCall(
                        id="c1",
                        name="campaign_pause",
                        arguments=json.dumps({"campaign_id": str(campaign_id)}),
                    ),
                )
            )
        ],
    )

    frames: list[tuple[str, Any]] = []
    async with (
        _client() as http,
        http.stream(
            "POST",
            "/v1/copilot/ask",
            headers=_headers(token, slug),
            json=_ask().model_dump(mode="json"),
        ) as response,
    ):
        assert response.status_code == 200, await response.aread()
        name: str | None = None
        async for line in response.aiter_lines():
            if line.startswith("event:"):
                name = line[len("event:") :].strip()
            elif line.startswith("data:") and name is not None:
                frames.append((name, json.loads(line[len("data:") :].strip())))
                name = None

    assert [frame for frame, _ in frames] == ["proposal", "done"]
    proposal = frames[0][1]
    assert proposal["tool"] == "campaign_pause"
    assert proposal["object_id"] == str(campaign_id)
    assert proposal["token"]
    # AND STILL NOTHING HAS HAPPENED. The proposal is an offer, not an act.
    assert await _campaign_status(tenant_id, campaign_id) == "running"
    assert [row[0] for row in await _audit(tenant_id)] == ["copilot.ask"]
