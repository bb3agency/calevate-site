"""Agreements & readiness — the ledger, the gates and the surface.

Migration `a9d4e70c31b8` gives this product the thing it had never had: a record that a
client agreed to the documents the rest of the platform enforces against them. Four
modules cite this file BY NAME for a promise they make in prose, and each of those
promises is a test below rather than a comment:

* `alembic/versions/a9d4e70c31b8_*.py` — "the cross-tenant zero-rows test in
  `tests/legal_agreements_test.py`" (§1).
* `apps/api/legal/routes.py` — "`tests/legal_agreements_test.py` asserts that equality so
  the gate cannot widen by somebody adding a permission to `staff`" (§5).
* `apps/api/legal/readiness.py` — "asserts every key is a rule the code really emits (it
  reads `scripts.check_docs_drift.emitted_rule_names`)" (§6).
* `apps/api/legal/models.py` / the migration — append-only, no withdrawal row (§2).

WHAT THIS FILE PINS, as behaviour rather than as a description of the code:

1. **Tenancy (hard rule 1).** Another tenant reads zero rows and can write none.
2. **Append-only (hard rule 4).** UPDATE, DELETE and TRUNCATE are refused by the
   database, not by a convention; a re-acceptance is a NEW row and the one it supersedes
   survives, because "which terms were they operating under in March?" is asked in April.
3. **The versioning rule.** `reacceptance_required` is the ONE predicate the gate, the
   screen and these tests share, and the review-state flip re-demands the whole set
   without a special case — which is the property the whole `+pre-review` suffix exists
   for and the one nobody can test by hand.
4. **The gates actually turn.** Publishing raises, the dial gate refuses, and both
   campaign gates name the condition — under ONE rule name from ONE implementation —
   and all four clear on the same four acceptances.
5. **The surface.** Only the owner accepts; a staff member cannot; an impersonating
   operator cannot; a stale document version or a stale acceptance wording is refused
   rather than recorded; an unacceptable slug never reaches the table.
6. **The screen's copy explains rules that exist.**
7. **Hard rule 6.** No email address and no person's name reaches a log line.

CONCURRENCY: every test builds its own run-unique tenant and asserts only on rows it
created, so this file runs beside the other suites on the shared Postgres. The one
exception is §2's TRUNCATE test, which cannot be scoped to a tenant by definition — it
runs inside a transaction that is always rolled back, and asserts the refusal rather than
the effect.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import prompts
from apps.api.agents import service as agents_service
from apps.api.campaigns import service as campaigns_service
from apps.api.compliance import service as compliance_service
from apps.api.core.errors import ProblemError
from apps.api.core.logging import JsonFormatter
from apps.api.core.rbac import MUTATING_PERMISSIONS, ROLE_PERMISSIONS
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.legal import catalogue, readiness, statements
from apps.api.legal import routes as legal_routes
from apps.api.legal import service as legal_service
from apps.api.main import app
from apps.api.tenancy.models import MEMBER_ROLES
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from tests.conftest import accept_agreements, arm_agent_for_outbound
from tests.impersonation_grant_test import view_as_headers

READINESS = "/v1/legal/readiness"
ACCEPTANCES = "/v1/legal/acceptances"

#: The person's details the "nothing personal in a log line" test searches FOR.
OWNER_NAME = "Padmavathi Rao"


async def _async(value: Any) -> Any:
    """A coroutine returning `value`, so a `monkeypatch.setattr` can stand in for an
    `await`ed dependency without each call site writing its own inline async def."""
    return value


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _headers(token: str, slug: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}


def _code(response: Any) -> str:
    """RFC-9457 has no `code` key: the machine identifier is the last segment of `type`."""
    return str(response.json()["type"]).rsplit("/", 1)[-1]


async def _org(prefix: str) -> dict[str, Any]:
    created = await admin_service.create_organization(
        name="Agreements Clinic",
        slug=f"lg-{prefix}-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return {
        "tenant_id": UUID(str(created["id"])),
        "slug": str(created["slug"]),
        "agent_id": UUID(str(created["agent_id"])),
    }


async def _member(
    tenant_id: UUID, *, role: str = "owner", name: str = OWNER_NAME
) -> tuple[UUID, str]:
    """A user with a membership in `tenant_id`. Returns (user_id, dev bearer token)."""
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, name, created_at, updated_at) "
                "VALUES (:id, :email, :name, now(), now())"
            ),
            {"id": user_id, "email": f"{user_id}@example.com", "name": name},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, :role, now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id, "role": role},
        )
    return user_id, f"dev:client:{user_id}"


async def _rows(tenant_id: UUID) -> list[tuple[Any, ...]]:
    async with tenant_session(tenant_id) as session:
        return [
            tuple(row)
            for row in (
                await session.execute(
                    text(
                        "SELECT document_slug, document_version, statement_version "
                        "FROM legal_acceptances WHERE tenant_id = :t "
                        "ORDER BY accepted_at, created_at"
                    ),
                    {"t": tenant_id},
                )
            ).all()
        ]


def _spec(slug: str) -> catalogue.LegalDocumentSpec:
    spec = catalogue.document(slug)
    assert spec is not None, slug
    return spec


# --------------------------------------------------------------------------------
# 1. Tenancy (hard rule 1)


async def test_another_tenant_can_neither_read_nor_write_an_acceptance_row() -> None:
    """The cross-tenant zero-rows test migration a9d4e70c31b8 promises.

    Both directions, because the policy is one expression doing two jobs: `FOR ALL` with
    no `WITH CHECK` reuses `USING` as the write check, so a tenant that cannot READ
    another's acceptance must also be unable to WRITE one for them. An acceptance names a
    business's owner and what that business agreed to; a neighbour's row can never speak
    for it.
    """
    alice = await _org("rls-a")
    bob = await _org("rls-b")
    alice_user, _ = await _member(alice["tenant_id"])
    await accept_agreements(alice["tenant_id"], alice_user)

    async with tenant_session(bob["tenant_id"]) as session:
        leaked = (await session.execute(text("SELECT count(*) FROM legal_acceptances"))).scalar()
        assert leaked == 0, "another tenant's acceptance rows must not be visible"
        accepted = await legal_service.latest_acceptances(session, tenant_id=alice["tenant_id"])
    assert accepted == {}, "a cross-tenant read through the service must also see nothing"

    with pytest.raises(DBAPIError):
        async with tenant_session(bob["tenant_id"]) as session:
            await legal_service.record_acceptance(
                session,
                tenant_id=alice["tenant_id"],
                slug="terms",
                version=_spec("terms").current_version,
                statement_version=statements.statement_version(),
                user_id=alice_user,
            )

    assert len(await _rows(alice["tenant_id"])) == len(catalogue.BLOCKING_SLUGS), (
        "the refused cross-tenant write must have added nothing"
    )


# --------------------------------------------------------------------------------
# 2. Append-only (hard rule 4)


async def test_an_acceptance_can_never_be_updated_or_deleted() -> None:
    """The trigger, not the convention. An UPDATE could only ever rewrite which version
    somebody agreed to — the one fact the row exists to fix in place — and a DELETE erases
    the evidence for the period it covers."""
    org = await _org("append")
    user_id, _ = await _member(org["tenant_id"])
    await accept_agreements(org["tenant_id"], user_id)

    for statement in (
        "UPDATE legal_acceptances SET document_version = 'tampered' WHERE tenant_id = :t",
        "DELETE FROM legal_acceptances WHERE tenant_id = :t",
    ):
        with pytest.raises(DBAPIError) as raised:
            async with tenant_session(org["tenant_id"]) as session:
                await session.execute(text(statement), {"t": org["tenant_id"]})
        assert "append-only" in str(raised.value).lower(), str(raised.value)

    assert len(await _rows(org["tenant_id"])) == len(catalogue.BLOCKING_SLUGS)


def test_truncate_is_refused_twice_over_and_the_trigger_is_the_half_that_matters() -> None:
    """The verb a `FOR EACH ROW` trigger cannot see.

    TRUNCATE removes rows without producing any, so the row-level append-only trigger
    never fires on it and a ledger carrying only that trigger is emptiable by one word.
    Migration a2e9f31c605d gave the other nine ledgers a statement-level twin; a ledger
    added afterwards needs both.

    TWO REFUSALS, AND THE ORDER THEY ARRIVE IN IS THE POINT. The app role (`calevate_app`,
    NOSUPERUSER NOBYPASSRLS) holds no TRUNCATE privilege, so a compromised application
    never gets as far as the trigger — asserted first, because it is the layer that
    actually stands in front of production. But privilege is a GRANT and grants are edited;
    the trigger is what refuses the role that owns the table, which is the role a restore,
    a migration or an operator's psql session runs as. Executed as that role, not read out
    of `pg_trigger`: `check_ledger_immutability` already reads the catalog, and a second
    reading of the same metadata would be a second spelling of one check rather than
    evidence that it blocks.

    Cannot be scoped to a tenant (TRUNCATE takes the whole table), so it asserts the
    REFUSAL inside a transaction that is rolled back either way.
    """
    from apps.api.core.settings import get_settings
    from sqlalchemy import create_engine

    async def _as_the_app_role() -> str:
        with pytest.raises(DBAPIError) as raised:
            async with untenanted_session() as session:
                await session.execute(text("TRUNCATE legal_acceptances"))
        return str(raised.value)

    assert "permission denied" in asyncio.run(_as_the_app_role()).lower()

    settings = get_settings()
    url = (settings.alembic_database_url or settings.database_url).replace("+asyncpg", "+psycopg")
    owner = create_engine(url)
    try:
        with owner.connect() as connection, pytest.raises(DBAPIError) as raised:
            connection.execute(text("TRUNCATE legal_acceptances"))
    finally:
        owner.dispose()
    assert "append-only" in str(raised.value).lower(), str(raised.value)


async def test_reaccepting_appends_and_the_superseded_row_survives() -> None:
    """A second click is a second row, and that is correct rather than tolerated: the
    ledger is append-only, `latest_acceptances` takes the newest, and a duplicate changes
    no answer any gate gives. It is also why this route carries no `Idempotency-Key`."""
    org = await _org("append2")
    user_id, _ = await _member(org["tenant_id"])
    terms = _spec("terms")

    async with tenant_session(org["tenant_id"]) as session:
        for _ in range(2):
            await legal_service.record_acceptance(
                session,
                tenant_id=org["tenant_id"],
                slug="terms",
                version=terms.current_version,
                statement_version=statements.statement_version(),
                user_id=user_id,
            )

    rows = await _rows(org["tenant_id"])
    assert len(rows) == 2, rows
    async with tenant_session(org["tenant_id"]) as session:
        latest = await legal_service.latest_acceptances(session, tenant_id=org["tenant_id"])
    assert latest["terms"].document_version == terms.current_version
    assert latest["terms"].accepted_by_name == OWNER_NAME, (
        "the screen has to be able to show whose signature this is"
    )


# --------------------------------------------------------------------------------
# 3. The versioning rule


def test_a_document_never_accepted_must_be_accepted() -> None:
    assert catalogue.reacceptance_required(_spec("dpa"), None) is True


def test_the_current_version_needs_no_reacceptance() -> None:
    spec = _spec("dpa")
    assert catalogue.reacceptance_required(spec, spec.current_version) is False
    assert catalogue.changed_since(spec, spec.current_version) is False


def test_the_legal_review_flip_re_demands_every_acceptance() -> None:
    """The property the `+pre-review` suffix exists for, and the one nobody can test by
    hand: nothing special-cases the transition, so it has to fall out of the version
    string. A provisional acceptance of an unreviewed draft is not an acceptance of the
    lawyer-reviewed document that replaced it — the client agreed to something whose
    blanks were visible on the page.

    Driven through the pure predicate with the version the OTHER review state produces,
    rather than by monkeypatching the constant: `current_version` is computed from it, so
    patching would move both sides of the comparison and prove nothing.
    """
    spec = _spec("terms")
    revision = spec.current.revision
    other_state = (
        revision if catalogue.PENDING_LEGAL_REVIEW else f"{revision}{catalogue.PRE_REVIEW_SUFFIX}"
    )
    assert other_state != spec.current_version
    assert catalogue.reacceptance_required(spec, other_state) is True


def test_a_revision_the_history_does_not_know_is_re_asked() -> None:
    """Reachable: a revision deleted by a later edit, or a database restored across a
    rollback. The safe answer to "we cannot tell whether this was superseded by anything
    material" is to ask again."""
    assert catalogue.reacceptance_required(_spec("terms"), catalogue.version_of("99")) is True


def test_only_a_material_revision_after_the_accepted_one_re_asks() -> None:
    """The whole rule in one assertion pair, on a synthetic history — the real catalogue
    has one revision per document, so the chain cannot be exercised against it without
    inventing revisions, which `material` is the only thing under test here anyway."""
    chain = catalogue.LegalDocumentSpec(
        slug="terms",
        title="Terms of Service",
        blocking=True,
        revisions=(
            catalogue.Revision("1", True, "first"),
            catalogue.Revision("2", False, "typo"),
            catalogue.Revision("3", False, "broken cross-reference"),
        ),
    )
    assert catalogue.reacceptance_required(chain, catalogue.version_of("1")) is False
    assert catalogue.changed_since(chain, catalogue.version_of("1")) is True, (
        "cosmetic movement still shows a banner, it just blocks nothing"
    )

    material = catalogue.LegalDocumentSpec(
        slug="terms",
        title="Terms of Service",
        blocking=True,
        revisions=(
            catalogue.Revision("1", True, "first"),
            catalogue.Revision("2", True, "a changed obligation"),
            catalogue.Revision("3", False, "typo"),
        ),
    )
    assert catalogue.reacceptance_required(material, catalogue.version_of("1")) is True, (
        "one material revision anywhere in the chain re-asks, even under a cosmetic head"
    )


def test_only_the_blocking_documents_are_acceptable() -> None:
    """A sub-processor list is a notice we owe the client, not a promise they make us —
    demanding a signature on it would make every vendor change a consent event for every
    tenant."""
    assert frozenset(catalogue.BLOCKING_SLUGS) == catalogue.ACCEPTABLE_SLUGS
    assert set(catalogue.BLOCKING_SLUGS) == {"terms", "privacy", "dpa", "acceptable-use"}
    assert "subprocessors" not in catalogue.ACCEPTABLE_SLUGS


# --------------------------------------------------------------------------------
# 4. The gates


async def test_publishing_an_agent_is_refused_until_the_agreements_are_accepted() -> None:
    """Putting an agent on the phone under a Data Processing Addendum nobody has agreed
    to is us processing a client's callers' personal data with no instrument covering it.

    `conflict`, not `permission`: the caller may hold every permission there is.
    """
    org = await _org("publish")
    user_id, _ = await _member(org["tenant_id"])

    async with tenant_session(org["tenant_id"]) as session:
        with pytest.raises(ProblemError) as raised:
            await legal_service.assert_agreements_accepted(session, tenant_id=org["tenant_id"])
    assert raised.value.code == legal_service.AGREEMENTS_RULE
    assert raised.value.kind == "conflict", raised.value.kind

    await accept_agreements(org["tenant_id"], user_id)
    async with tenant_session(org["tenant_id"]) as session:
        await legal_service.assert_agreements_accepted(session, tenant_id=org["tenant_id"])


async def test_an_agent_of_another_tenant_is_absent_rather_than_refused() -> None:
    """The agreements gate must not answer before the object is resolved and OWNED.

    It originally ran beside `assert_account_open`, first thing in `publish_agent`, on the
    reasoning that an account-level fact is cheapest to ask early. That put it in front of
    `_load_agent`, which is where existence and ownership are decided — so a caller naming
    an agent that belongs to a tenant they cannot see stopped getting the 404 that reveals
    nothing and started getting `agreements_not_accepted`, which confirms the tenant exists
    AND reports the state of its paperwork. `tests/onboarding_to_live_test.py` caught it as
    a broken assertion; this pins the property, because that one now accepts in its fixture
    and would pass under the wrong ordering again.

    The tenant here deliberately has NOT accepted, so the 409 is available to leak: if the
    gate moves back in front of the ownership check, this test is what turns red.
    """
    owner = await _org("owned")
    stranger = await _org("stranger")

    with pytest.raises(ProblemError) as raised:
        async with tenant_session(stranger["tenant_id"]) as session:
            await agents_service.publish_agent(
                session, tenant_id=stranger["tenant_id"], agent_id=owner["agent_id"]
            )
    assert raised.value.kind == "not_found", raised.value.kind
    assert raised.value.code != legal_service.AGREEMENTS_RULE, (
        "the refusal named the agreements of a tenant this caller cannot see"
    )
    assert await _rows(owner["tenant_id"]) == []


async def test_the_dial_gate_refuses_a_client_who_has_agreed_to_nothing() -> None:
    """`check_dispatch` is the gate the campaign gates cannot reach: the D-21 "call this
    lead" button, the instant requested-callback webhook and the WhatsApp escalation all
    pass through here and never through `launch_blockers`."""
    org = await _org("dispatch")
    user_id, _ = await _member(org["tenant_id"])
    await arm_agent_for_outbound(org["tenant_id"], org["agent_id"])
    # The gate refuses in a fixed order and `agent_not_live` comes BEFORE the account-level
    # conditions, so an unpublished agent would make this test pass for the wrong reason —
    # green today, and still green on the day the agreements arm is deleted. Set directly
    # rather than published: publishing calls the vendor, and this test is about the
    # account, not about the engine. (`billing_audit_test` does the same, for the same
    # reason.)
    async with tenant_session(org["tenant_id"]) as session:
        await session.execute(
            text("UPDATE agents SET status = 'live', direction = 'outbound' WHERE id = :a"),
            {"a": org["agent_id"]},
        )

    async with tenant_session(org["tenant_id"]) as session:
        refused = await compliance_service.check_dispatch(
            session,
            tenant_id=org["tenant_id"],
            agent_id=org["agent_id"],
            phone_e164="+919000000101",
        )
    assert refused.allowed is False
    assert refused.rule == legal_service.AGREEMENTS_RULE, refused.rule

    await accept_agreements(org["tenant_id"], user_id)
    async with tenant_session(org["tenant_id"]) as session:
        after = await compliance_service.check_dispatch(
            session,
            tenant_id=org["tenant_id"],
            agent_id=org["agent_id"],
            phone_e164="+919000000101",
        )
    assert after.rule != legal_service.AGREEMENTS_RULE, (
        "the same four acceptances that cleared publish must clear the dial gate"
    )


async def test_both_campaign_gates_name_the_agreements_under_one_rule() -> None:
    """Launch is a photograph; a campaign runs for days. A MATERIAL new version falling
    due mid-flight must stop the dispatch tick as well as the launch button, which is why
    `agreements_blocker` is asked in both and why they must agree on the name."""
    org = await _org("campaign")
    user_id, _ = await _member(org["tenant_id"])
    async with tenant_session(org["tenant_id"]) as session:
        await prompts.write_prompt_version(
            session,
            tenant_id=org["tenant_id"],
            agent_id=org["agent_id"],
            body="[IDENTITY]\nYou are the receptionist for Agreements Clinic.\n",
            notes=None,
            created_by=None,
        )
        campaign_id = await campaigns_service.create_campaign(
            session,
            tenant_id=org["tenant_id"],
            agent_id=org["agent_id"],
            name="Reminders",
            classification="service",
            number_id=None,
            dlt_template_id=None,
            concurrency=1,
        )

    async def _rules() -> tuple[set[str], set[str]]:
        async with tenant_session(org["tenant_id"]) as session:
            launch = {
                blocker.rule
                for blocker in await campaigns_service.launch_blockers(
                    session, tenant_id=org["tenant_id"], campaign_id=campaign_id
                )
            }
            dispatch = {
                blocker.rule
                for blocker in await campaigns_service.dispatch_blockers(
                    session, tenant_id=org["tenant_id"], campaign_id=campaign_id
                )
            }
        return launch, dispatch

    launch, dispatch = await _rules()
    assert legal_service.AGREEMENTS_RULE in launch, launch
    assert legal_service.AGREEMENTS_RULE in dispatch, dispatch

    await accept_agreements(org["tenant_id"], user_id)
    launch, dispatch = await _rules()
    assert legal_service.AGREEMENTS_RULE not in launch, launch
    assert legal_service.AGREEMENTS_RULE not in dispatch, dispatch


async def test_a_partial_acceptance_still_blocks() -> None:
    """Three of four is not accepted. There is ONE failure name because the client's next
    action does not vary by document, and the screen that lists them by name is one click
    away."""
    org = await _org("partial")
    user_id, _ = await _member(org["tenant_id"])
    async with tenant_session(org["tenant_id"]) as session:
        for slug in catalogue.BLOCKING_SLUGS[:-1]:
            await legal_service.record_acceptance(
                session,
                tenant_id=org["tenant_id"],
                slug=slug,
                version=_spec(slug).current_version,
                statement_version=statements.statement_version(),
                user_id=user_id,
            )
        blocker = await legal_service.agreements_blocker(session, tenant_id=org["tenant_id"])
        outstanding = legal_service.outstanding_slugs(
            await legal_service.latest_acceptances(session, tenant_id=org["tenant_id"])
        )
    assert blocker is not None and blocker[0] == legal_service.AGREEMENTS_RULE
    assert outstanding == [catalogue.BLOCKING_SLUGS[-1]], outstanding


# --------------------------------------------------------------------------------
# 5. The surface


def test_org_manage_is_the_owner_alone_and_is_a_mutating_permission() -> None:
    """The equality `legal/routes.py` names this file for.

    "Only the organisation owner" is stated in the vocabulary this repo already uses
    rather than by a hand-typed role check, and this holds it: a permission added to
    `staff` would silently widen who may sign for a business. `org:manage` being in
    `MUTATING_PERMISSIONS` is the second half — it is what stops an impersonating
    operator accepting a client's agreements while wearing their face.
    """
    holders = {
        role for role in MEMBER_ROLES if "org:manage" in ROLE_PERMISSIONS.get(role, frozenset())
    }
    assert holders == {"owner"}, holders
    # Scoped to `MEMBER_ROLES` on purpose: `ROLE_PERMISSIONS` also carries the ADMIN
    # realm's roles, which hold `org:manage` for their own console and reach this route
    # through neither door — the POST is `realm="client"`, so an operator's token is
    # refused before a permission is looked at. "Only the organisation owner" is a claim
    # about the roles a MEMBERSHIP can carry, and this is that set.
    assert set(MEMBER_ROLES) == {"owner", "staff"}, MEMBER_ROLES
    assert "org:manage" in MUTATING_PERMISSIONS
    assert "org:read" not in MUTATING_PERMISSIONS, (
        "the readiness READ must survive a D-22 view-as-client session"
    )


async def test_the_owner_accepts_and_gets_the_whole_screen_back() -> None:
    """The response IS the readiness screen: accepting the third of four agreements
    changes the verdict, the blocker list and the nav badge, and a console that had to
    re-read would show a stale verdict on the one screen whose subject is whether the
    account may operate."""
    org = await _org("owner")
    _, token = await _member(org["tenant_id"])

    async with _client() as http:
        before = await http.get(READINESS, headers=_headers(token, org["slug"]))
        assert before.status_code == 200, before.text
        screen = before.json()
        assert screen["outstanding_documents"] == len(catalogue.BLOCKING_SLUGS)
        assert screen["may_operate"] is False
        assert screen["can_accept"] is True and screen["can_accept_reason"] is None
        assert screen["pending_legal_review"] is catalogue.PENDING_LEGAL_REVIEW
        assert screen["provisional_notice"] == statements.PROVISIONAL_NOTICE
        assert screen["acceptance_statement"] == statements.statement_text()
        assert {doc["slug"] for doc in screen["documents"]} == {
            spec.slug for spec in catalogue.DOCUMENTS
        }
        assert legal_service.AGREEMENTS_RULE in {row["rule"] for row in screen["blockers"]}

        last = screen
        for slug in catalogue.BLOCKING_SLUGS:
            posted = await http.post(
                ACCEPTANCES,
                headers=_headers(token, org["slug"]),
                json={
                    "slug": slug,
                    "version": _spec(slug).current_version,
                    "statement_version": screen["acceptance_statement_version"],
                },
            )
            assert posted.status_code == 201, posted.text
            last = posted.json()

    assert last["outstanding_documents"] == 0
    assert legal_service.AGREEMENTS_RULE not in {row["rule"] for row in last["blockers"]}
    states = {doc["slug"]: doc for doc in last["documents"]}
    assert states["dpa"]["state"] == "accepted"
    assert states["dpa"]["accepted_by_name"] == OWNER_NAME
    assert states["dpa"]["provisional"] is catalogue.PENDING_LEGAL_REVIEW
    assert states["subprocessors"]["state"] == "not_required"
    assert states["terms"]["href"] == "/legal/terms"


async def test_a_staff_member_may_read_the_screen_and_may_not_accept() -> None:
    """A member who cannot accept can still see what is outstanding — and is told why,
    rather than shown a button that 403s."""
    org = await _org("staff")
    _, token = await _member(org["tenant_id"], role="staff", name="Staff Person")

    async with _client() as http:
        read = await http.get(READINESS, headers=_headers(token, org["slug"]))
        posted = await http.post(
            ACCEPTANCES,
            headers=_headers(token, org["slug"]),
            json={
                "slug": "terms",
                "version": _spec("terms").current_version,
                "statement_version": statements.statement_version(),
            },
        )
    assert read.status_code == 200, read.text
    assert read.json()["can_accept"] is False
    assert "owner" in str(read.json()["can_accept_reason"]).lower()
    assert posted.status_code == 403, posted.text
    assert await _rows(org["tenant_id"]) == []


async def test_an_impersonating_operator_cannot_sign_for_a_client() -> None:
    """Nobody signs for the client but the client. D-22 refuses every mutating permission
    to an impersonating principal, and the screen says so BEFORE the click."""
    org = await _org("viewas")
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    admin_token = f"dev:admin:{admin_id}"

    async with _client() as http:
        headers = await view_as_headers(http, admin_token, org["slug"])
        read = await http.get(READINESS, headers=headers)
        posted = await http.post(
            ACCEPTANCES,
            headers=headers,
            json={
                "slug": "terms",
                "version": _spec("terms").current_version,
                "statement_version": statements.statement_version(),
            },
        )
    assert read.status_code == 200, read.text
    assert read.json()["can_accept"] is False
    assert "read-only" in str(read.json()["can_accept_reason"]).lower()
    assert posted.status_code == 403, posted.text
    assert await _rows(org["tenant_id"]) == []


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"slug": "subprocessors"}, "legal_document_not_acceptable"),
        ({"slug": "not-a-document"}, "legal_document_not_acceptable"),
        ({"version": "1+stale"}, "legal_version_not_current"),
        ({"statement_version": "0+stale"}, "legal_statement_not_current"),
    ],
)
async def test_a_stale_or_unacceptable_acceptance_is_refused_rather_than_recorded(
    payload: dict[str, str], expected: str
) -> None:
    """A row that evidences something that did not happen is worse than no row.

    A console left open across a publication would otherwise record an agreement to text
    nobody is showing any more; the wording the person ticked is half the evidence.
    """
    org = await _org("stale")
    _, token = await _member(org["tenant_id"])
    body = {
        "slug": "terms",
        "version": _spec("terms").current_version,
        "statement_version": statements.statement_version(),
        **payload,
    }

    async with _client() as http:
        posted = await http.post(ACCEPTANCES, headers=_headers(token, org["slug"]), json=body)
    assert posted.status_code in (409, 422), posted.text
    assert _code(posted) == expected, posted.text
    assert await _rows(org["tenant_id"]) == []


async def test_an_acceptance_writes_one_audit_entry_naming_the_document() -> None:
    """The caller's address is recorded HERE and nowhere else: the ledger row carries no
    `ip` column on purpose, and this entry is written in the same transaction, names the
    same act, and lives in the hash-chained log."""
    org = await _org("audit")
    _, token = await _member(org["tenant_id"])

    async with _client() as http:
        posted = await http.post(
            ACCEPTANCES,
            headers=_headers(token, org["slug"]),
            json={
                "slug": "dpa",
                "version": _spec("dpa").current_version,
                "statement_version": statements.statement_version(),
            },
        )
    assert posted.status_code == 201, posted.text

    async with untenanted_session() as session:
        entries = (
            await session.execute(
                text(
                    "SELECT object_id, ip FROM audit_log WHERE tenant_id = :t "
                    "AND action = 'legal.agreement_accepted'"
                ),
                {"t": org["tenant_id"]},
            )
        ).all()
    assert [str(row[0]) for row in entries] == ["dpa"], entries
    assert entries[0][1] is not None, "the clickwrap's IP evidence must be in the audit row"


# --------------------------------------------------------------------------------
# 6. The screen's copy explains rules that exist


def test_every_readiness_row_explains_a_rule_the_code_really_emits() -> None:
    """The promise `legal/readiness.py` names this file for.

    A rename cannot leave a screen explaining a rule that no longer exists — the copy
    table is keyed by rule name, and the vocabulary comes from the same extractor SEC-COMP
    §3 is checked against rather than from a second hand-typed list.
    """
    from scripts.check_docs_drift import emitted_rule_names

    emitted = emitted_rule_names()
    assert emitted, "the extractor found no rule names at all — it is reading nothing"
    unknown = sorted(set(readiness.ROW_COPY) - emitted)
    assert unknown == [], unknown


def test_an_unknown_rule_still_renders_and_is_ours_to_explain() -> None:
    """A screen that silently dropped a live blocker would tell a client they are ready
    when they are not. If the platform cannot say whose move a refusal is, telling the
    client to go and do something is worse than admitting we owe them the answer."""
    row = readiness._row("a_rule_from_the_future", "Something stopped the calls.")
    assert row.actor == "calevate"
    assert row.reason == "Something stopped the calls."
    assert row.title and row.next_step


# --------------------------------------------------------------------------------
# 7. Hard rule 6 — no person in a log line


async def test_no_log_line_carries_the_accepting_person(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Ids, slugs and versions. A name and an email address are exactly what a contract
    ledger is tempted to log and exactly what hard rule 6 refuses."""
    org = await _org("logs")
    user_id, token = await _member(org["tenant_id"])

    with caplog.at_level(logging.DEBUG):
        async with _client() as http:
            posted = await http.post(
                ACCEPTANCES,
                headers=_headers(token, org["slug"]),
                json={
                    "slug": "privacy",
                    "version": _spec("privacy").current_version,
                    "statement_version": statements.statement_version(),
                },
            )
    assert posted.status_code == 201, posted.text

    formatter = JsonFormatter()
    rendered = "\n".join(formatter.format(record) for record in caplog.records)
    assert OWNER_NAME not in rendered
    assert f"{user_id}@example.com" not in rendered
    assert "legal_acceptance_recorded" in rendered, (
        "the write must still be observable — this test must not pass by logging nothing"
    )


# --------------------------------------------------------------------------------
# 8. The arms the first ratchet run found untested
#
# `make coverage-ratchet` measured 22 uncovered units in the `compliance-gate` surface
# after this feature landed — every one of them a branch that only fires when something
# is actually WRONG with the account. That is the worst class to leave untested on a
# hard-rule-5 surface: the clean path is exercised by every other test in this file, and
# the arms that refuse are the ones a client only meets on their worst day.
#
# The forbidden response, stated in CLAUDE.md hard rule 10 and repeated here because the
# temptation is real at 22 units: not `RAISED_BUDGETS`, and never the baseline.


def _acceptance(slug: str, version: str) -> legal_service.Acceptance:
    """An acceptance row as `_headline` reads one. Constructed rather than inserted: these
    three tests are about the WORDING function, and a database round trip would make them
    slower without making them truer."""
    return legal_service.Acceptance(
        document_slug=slug,
        document_version=version,
        statement_version="1",
        accepted_at=datetime(2026, 1, 1, tzinfo=UTC),
        accepted_by_user_id=uuid.uuid4(),
        accepted_by_name="Raghava",
    )


def test_a_blocking_document_never_accepted_says_so_and_is_not_the_generic_state() -> None:
    """`never_accepted` and `not_required` are different words for different facts.

    The screen decides what to offer from the STATE, so collapsing these two would put an
    accept control on a document that has nothing to accept, or withhold it from one that
    does.
    """
    spec = _spec("terms")
    assert spec.blocking
    sentence, state = legal_routes._headline(spec, None)
    assert state == "never_accepted"
    assert sentence == "Not accepted yet."


def test_a_document_whose_version_moved_materially_reads_as_needing_reacceptance() -> None:
    """The MATERIAL arm, which is the one that blocks dialling.

    Distinct from `changed` below: the founder's rule is that a material version re-blocks
    and a minor one only notifies, so a screen that reported both as "changed" would tell
    a client nothing was wrong while `agreements_blocker` refused every call.
    """
    spec = replace(
        _spec("terms"),
        revisions=(
            catalogue.Revision("1", True, "First published draft."),
            catalogue.Revision("2", True, "A clause that changes what was agreed."),
        ),
    )
    # `version_of` and NOT a bare "1": the wire version carries the review-state suffix
    # while `PENDING_LEGAL_REVIEW` stands, and a bare revision trips the REVIEW-STATE arm
    # of `reacceptance_required` instead of the material one. This test passed on that
    # accident before the sibling test below exposed it — it was green for a reason that
    # had nothing to do with materiality.
    _, state = legal_routes._headline(spec, _acceptance("terms", catalogue.version_of("1")))
    assert state == "reacceptance_required"
    assert catalogue.reacceptance_required(spec, catalogue.version_of("1"))


def test_a_non_material_revision_notifies_and_does_not_block() -> None:
    """The `changed` arm — the half of the founder's versioning rule that must NOT block.

    A material revision re-demands acceptance; a minor one (a typo, a subprocessor of a
    kind already disclosed) shows a banner and blocks nothing. Every document in the
    catalogue is at its first revision today, so this state is unreachable from real data
    and would have stayed untested until the first correction we publish — which is
    exactly when getting it wrong would halt every client's calls over a typo.

    The spec is built here rather than added to the catalogue: a fixture revision in
    `DOCUMENTS` would ship in the product and appear on `/legal`.
    """
    spec = replace(
        _spec("terms"),
        revisions=(
            catalogue.Revision("1", True, "First published draft."),
            catalogue.Revision(
                "2", False, "Corrected a spelling. Nothing anybody agreed to moved."
            ),
        ),
    )
    accepted = catalogue.version_of("1")
    sentence, state = legal_routes._headline(spec, _acceptance("terms", accepted))
    assert state == "changed"
    assert "does not affect what you agreed" in sentence
    assert not catalogue.reacceptance_required(spec, accepted), (
        "a cosmetic revision must not re-demand acceptance — that is what blocks dialling"
    )


def test_the_verdict_for_outstanding_agreements_is_its_own_sentence() -> None:
    """Because it is the only item on the screen a reader can clear without leaving it.

    The generic sentence sends somebody to a list of things that are mostly other
    people's; this one says the thing they can do in the next thirty seconds.
    """
    assert "have not been accepted" in legal_routes._verdict(False, 2)
    assert legal_routes._verdict(True, 0) == "Nothing is holding up your outgoing calls."
    generic = legal_routes._verdict(False, 0)
    assert "whose move each one is" in generic
    assert "Calls coming in are unaffected" in generic


@pytest.mark.asyncio
async def test_an_acceptance_attributed_to_nobody_is_refused_at_the_handler() -> None:
    """The defensive arm on `accept`, driven at the function rather than through the router.

    It is unreachable through `requires(..., realm="client")`, which resolves a membership
    — so a route-level test cannot reach it and it would stay uncovered forever. But the
    type is `UUID | None`, and hard rule 4 makes this ledger the evidence of who bound the
    business: a row attributed to nobody is the one thing it must never hold. The branch
    is kept and covered rather than deleted, because what makes it unreachable today is a
    dependency's behaviour, not this function's signature.
    """
    org = await _org("nouser")
    principal = SimpleNamespace(tenant_id=org["tenant_id"], user_id=None)
    async with tenant_session(org["tenant_id"]) as session:
        with pytest.raises(ProblemError) as raised:
            await legal_routes.accept(
                payload=SimpleNamespace(slug="terms", version="1", statement_version="1"),
                session=session,
                request=SimpleNamespace(headers={}, client=None),
                principal=principal,
            )
    assert raised.value.status == 403
    assert "named person" in str(raised.value.detail)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("attribute", "value", "expected_rule"),
    [
        (
            "account_stopped_blocker",
            ("account_stopped", "The account is stopped."),
            "account_stopped",
        ),
        ("kyc_blocker", ("kyc_missing", "No verification on file."), "kyc_missing"),
        (
            "first_campaign_hold_blocker",
            ("first_campaign_hold", "Held for review."),
            "first_campaign_hold",
        ),
    ],
)
async def test_every_composed_blocker_reaches_the_screen(
    monkeypatch: pytest.MonkeyPatch, attribute: str, value: tuple[str, str], expected_rule: str
) -> None:
    """THE PROPERTY: a gate that refuses a dial is a row a client can read.

    Each of these was already tested where it is DECIDED. What was untested is the
    composition — that `readiness_rows` asks it and turns its answer into a row — and the
    composition is the half that breaks silently: somebody adds a blocker to
    `check_dispatch`, forgets this function, and a client is refused for a reason no
    screen in the product will name.

    Stubbed rather than driven through real account state, deliberately and with the
    limit stated: each blocker's own conditions have their own suites, and reproducing
    seven of them here would test those suites a second time while leaving THIS function's
    wiring just as unproven. What this pins is that the answer is asked for and is
    rendered — which is exactly what the ratchet found nothing was pinning.
    """
    org = await _org(f"blk-{expected_rule.replace('_', '-')[:8]}")
    monkeypatch.setattr(readiness, attribute, lambda *a, **k: _async(value))
    async with tenant_session(org["tenant_id"]) as session:
        rows = await readiness.readiness_rows(session, tenant_id=org["tenant_id"])
    assert expected_rule in {row.rule for row in rows}


@pytest.mark.asyncio
async def test_the_spend_cap_and_an_empty_wallet_each_reach_the_screen() -> None:
    """The two boolean gates, which return `True` rather than a pair.

    They are worth their own test because their arms build the row from a CONSTANT the
    compliance layer owns (`SPEND_CAP_REASON`, `NO_CREDITS_REASON`) rather than from the
    gate's return value — so a reworded constant has to travel here, and nothing else
    would notice if it stopped.
    """
    org = await _org("wallet")
    async with tenant_session(org["tenant_id"]) as session:
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(readiness, "spend_capped", lambda *a, **k: _async(True))
            patch.setattr(readiness, "credits_exhausted", lambda *a, **k: _async(True))
            rows = await readiness.readiness_rows(session, tenant_id=org["tenant_id"])

    by_rule = {row.rule: row for row in rows}
    assert by_rule["spend_cap"].reason == readiness.SPEND_CAP_REASON
    assert by_rule["no_credits"].reason == readiness.NO_CREDITS_REASON


@pytest.mark.asyncio
async def test_a_platform_wide_halt_is_named_as_ours_rather_than_the_client_s() -> None:
    """The big red switch, and the reason it earns a row at all.

    A client whose calls stopped because an operator pulled the switch would otherwise
    read a screen listing only THEIR outstanding items, all of them green, with the calls
    still not going out. The row exists so the screen never implies the fault is theirs.
    """
    org = await _org("brs")
    async with tenant_session(org["tenant_id"]) as session:
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(
                readiness,
                "get_platform_status",
                lambda *a, **k: _async(SimpleNamespace(outbound_halted=True)),
            )
            rows = await readiness.readiness_rows(session, tenant_id=org["tenant_id"])

    halted = next(row for row in rows if row.rule == "big_red_switch")
    assert halted.actor == "calevate", "a platform halt must never be the client's move"


@pytest.mark.asyncio
async def test_campaigns_with_no_current_scrub_are_counted_and_pluralised() -> None:
    """The scrub arm builds its sentence with arithmetic, which is where a screen lies.

    One campaign must read "1 promotional campaign ... has", not "1 campaigns ... have".
    It is a small thing and it is on the screen a client cites back to us when a caller
    complains about being called.
    """
    org = await _org("scrub")
    for count, noun, verb in ((1, "campaign ", "has"), (3, "campaigns", "have")):
        async with tenant_session(org["tenant_id"]) as session:
            with pytest.MonkeyPatch.context() as patch:
                patch.setattr(
                    readiness,
                    "campaigns_awaiting_scrub",
                    lambda *a, _n=count, **k: _async(_n),
                )
                rows = await readiness.readiness_rows(session, tenant_id=org["tenant_id"])
        row = next(r for r in rows if r.rule == "national_dnd_scrub_missing")
        assert noun.strip() in row.reason and verb in row.reason
