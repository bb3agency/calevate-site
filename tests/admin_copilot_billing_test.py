"""The admin copilot's PAYER, and the three properties that make it safe (D-499).

Every test here was written against the behaviour it asserts and fails against the code
that existed before this change — the ones that matter most, and what they would have done
on the old tree:

1. `test_the_admin_realm_was_refused_outright_and_is_not_any_more` — `copilot/routes.py`
   had `assert principal.tenant_id is not None` and there was no admin route at all, so
   `/v1/admin/copilot/ask` was a 404.
2. `test_an_operators_question_never_touches_a_clients_ledger` — there was no
   `platform_ai_usage` table to land in, and the only meter available wrote `usage_events`
   under a tenant.
3. `test_the_two_realms_offer_different_tools` — `tool_array()` took no realm.
4. `test_an_admin_memory_cannot_be_recalled_into_a_clients_conversation` — an admin
   memory could not be written at all (`copilot_memories.user_id` is a FK to `users`), so
   the leak was prevented by a foreign key rather than by a design.

CONCURRENCY: every test mints its own admin user and its own tenant, so nothing here
depends on another suite's rows. `platform_ai_spend` is shared — the same caveat
`ai_quota_test.py` documents — so nothing here asserts a platform TOTAL, only deltas
computed from a read taken in the same test.
"""

from __future__ import annotations

import json
import re
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing import platform_ai
from apps.api.billing.ai_quota import (
    ASSIST_REF_PREFIX,
    PLATFORM_AI_BRAKE_INR,
    current_billing_month,
    is_assist_ref,
    new_assist_ref,
    read_platform_ai_spend,
)
from apps.api.billing.rates import llm_inr_per_ktok
from apps.api.copilot import admin_memory, admin_tools
from apps.api.copilot import service as copilot_service
from apps.api.copilot import tools as copilot_tools
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import (
    IMPERSONATION_PERMITTED_MUTATIONS,
    MUTATING_PERMISSIONS,
    ROLE_PERMISSIONS,
    role_has,
)
from apps.api.crm.assist import ASSIST_FEATURE_ADMIN_COPILOT, ASSIST_FEATURE_COPILOT
from apps.api.db.registry import APPEND_ONLY_TABLES, RLS_EXEMPT_TENANT_COLUMNS
from apps.api.db.session import untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

pytestmark = pytest.mark.anyio


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _make_admin(role: str = "operator") -> uuid.UUID:
    """One operator account. `admin_security_test._make_admin`'s idiom."""
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', :role, now(), now())"
            ),
            {"id": admin_id, "role": role},
        )
    return admin_id


# --------------------------------------------------------------- the payer


async def test_an_operators_question_never_touches_a_clients_ledger() -> None:
    """THE FOUNDER'S SENTENCE, AS AN ASSERTION: *"You never charge a client for your own
    support work."*

    An operator's metered answer writes `platform_ai_usage` and NOTHING in `usage_events`,
    even when the operator was looking at a client (`viewing_tenant_id` is set on the row).
    That column is context and no reader prices it — this test is what says so.

    FAILS IF: somebody makes `viewing_tenant_id` a payer, or routes the admin meter through
    `record_ai_assist_usage`.
    """
    admin_id = await _make_admin()
    ref = new_assist_ref()
    model = "gpt-4o-mini"
    async with untenanted_session() as session:
        before = (
            await session.execute(
                text("SELECT count(*) FROM usage_events WHERE ref = :r"), {"r": ref}
            )
        ).scalar_one()
        metered = await platform_ai.record_platform_ai_usage(
            session,
            admin_user_id=admin_id,
            viewing_tenant_id=None,
            ref=ref,
            tokens_in=2000,
            tokens_out=500,
            model=model,
            feature=ASSIST_FEATURE_ADMIN_COPILOT,
        )
        rows = (
            await session.execute(
                text(
                    "SELECT unit_type, qty, unit_cost_paid, admin_user_id, meta "
                    "FROM platform_ai_usage WHERE ref = :r ORDER BY unit_type"
                ),
                {"r": ref},
            )
        ).all()
        after = (
            await session.execute(
                text("SELECT count(*) FROM usage_events WHERE ref = :r"), {"r": ref}
            )
        ).scalar_one()

    assert metered.recorded is True
    assert before == after == 0, "an operator's question wrote a row on a client's ledger"
    assert [row[0] for row in rows] == ["ai_assist_ktok_in", "ai_assist_ktok_out"]
    price = llm_inr_per_ktok(model)
    # NUMERIC end to end (hard rule 7): the money that came back is exactly the money the
    # price list publishes, computed in Decimal, with no float anywhere.
    assert metered.cost_inr == Decimal(2) * price["in"] + Decimal("0.5") * price["out"]
    assert all(isinstance(row[1], Decimal) and isinstance(row[2], Decimal) for row in rows)
    assert all(uuid.UUID(str(row[3])) == admin_id for row in rows)
    # psycopg hands `jsonb` back already decoded; the guard is against a driver change,
    # not a style preference.
    meta = rows[0][4] if isinstance(rows[0][4], dict) else json.loads(rows[0][4])
    assert meta["feature"] == ASSIST_FEATURE_ADMIN_COPILOT
    assert meta["admin_user_id"] == str(admin_id)


async def test_the_admin_cost_name_is_its_own_and_not_the_clients() -> None:
    """The founder asked for "a special cost name". It is a SIBLING of the five in
    `crm/assist.py` and it is not the client copilot's.

    FAILS IF: somebody reuses `copilot`, which would make "what did the admin console cost
    us this month" unanswerable — the query an operator runs against the ledger.
    """
    assert ASSIST_FEATURE_ADMIN_COPILOT == "admin_copilot"
    assert ASSIST_FEATURE_ADMIN_COPILOT != ASSIST_FEATURE_COPILOT


async def test_the_ref_shape_is_enforced_by_the_database_and_not_only_by_python() -> None:
    """`ref` IS THE METER'S OFF SWITCH, so the rule is written twice on purpose — once as
    `_ASSIST_REF_RE` and once as `ck_platform_ai_usage_ref_shape`.

    Two spellings of one rule is normally the drift this repo calls a defect; here the
    database's copy is the one that holds when a future writer forgets the Python guard, so
    this test pins the two to agree rather than trusting them to.

    FAILS IF: the CHECK is relaxed, or the Python regex is widened without it.
    """
    admin_id = await _make_admin()
    assert is_assist_ref(f"{ASSIST_REF_PREFIX}:{uuid.uuid4()}")
    assert not is_assist_ref("1")

    with pytest.raises(ValueError, match="new_assist_ref"):
        async with untenanted_session() as session:
            await platform_ai.record_platform_ai_usage(
                session,
                admin_user_id=admin_id,
                viewing_tenant_id=None,
                ref="1",
                tokens_in=1,
                tokens_out=1,
                model="gpt-4o-mini",
                feature=ASSIST_FEATURE_ADMIN_COPILOT,
            )

    # And the database refuses it too, with the Python guard bypassed entirely.
    with pytest.raises(Exception, match="ref_shape"):
        async with untenanted_session() as session:
            await session.execute(
                text(
                    "INSERT INTO platform_ai_usage "
                    "(id, admin_user_id, unit_type, qty, unit_cost_paid, ref, meta) "
                    "VALUES (:id, :aid, 'ai_assist_ktok_in', 1, 1, 'whatever', '{}'::jsonb)"
                ),
                {"id": uuid.uuid4(), "aid": admin_id},
            )


async def test_one_attempt_metered_twice_charges_once() -> None:
    """Idempotency is `ux_platform_ai_usage_unit_ref`, not a reader's `if`.

    With a server-minted key a conflict can only be a RETRIED TRANSACTION, so the second
    call must add nothing to the ledger and nothing to the platform counter.

    FAILS IF: the unique index is dropped, or the writer stops using `ON CONFLICT DO
    NOTHING` (which on an append-only table would instead raise from the mutation trigger).
    """
    admin_id = await _make_admin()
    ref = new_assist_ref()
    async with untenanted_session() as session:
        first = await platform_ai.record_platform_ai_usage(
            session,
            admin_user_id=admin_id,
            viewing_tenant_id=None,
            ref=ref,
            tokens_in=1000,
            tokens_out=100,
            model="gpt-4o-mini",
            feature=ASSIST_FEATURE_ADMIN_COPILOT,
        )
        second = await platform_ai.record_platform_ai_usage(
            session,
            admin_user_id=admin_id,
            viewing_tenant_id=None,
            ref=ref,
            tokens_in=1000,
            tokens_out=100,
            model="gpt-4o-mini",
            feature=ASSIST_FEATURE_ADMIN_COPILOT,
        )
        count = (
            await session.execute(
                text("SELECT count(*) FROM platform_ai_usage WHERE ref = :r"), {"r": ref}
            )
        ).scalar_one()
    assert first.recorded is True
    assert second.recorded is False and second.cost_inr == Decimal("0")
    assert count == 2, "two rows for one attempt — one per direction, and no more"


async def test_the_platform_ledger_is_append_only_in_the_database() -> None:
    """Hard rule 4, verified against the trigger rather than against the registry entry.

    FAILS IF: the trigger is dropped, or is created without `ENABLE ALWAYS` (which would
    let `SET session_replication_role = replica` switch immutability off with no DDL and no
    schema diff).
    """
    assert "platform_ai_usage" in APPEND_ONLY_TABLES
    # RLS rule 7a: a `platform_*` table must declare why it has no tenant column.
    assert "platform_ai_usage" in RLS_EXEMPT_TENANT_COLUMNS
    assert "admin_copilot_memories" in RLS_EXEMPT_TENANT_COLUMNS

    admin_id = await _make_admin()
    ref = new_assist_ref()
    async with untenanted_session() as session:
        await platform_ai.record_platform_ai_usage(
            session,
            admin_user_id=admin_id,
            viewing_tenant_id=None,
            ref=ref,
            tokens_in=10,
            tokens_out=10,
            model="gpt-4o-mini",
            feature=ASSIST_FEATURE_ADMIN_COPILOT,
        )
    for statement in (
        "UPDATE platform_ai_usage SET qty = 0 WHERE ref = :r",
        "DELETE FROM platform_ai_usage WHERE ref = :r",
    ):
        with pytest.raises(Exception):  # noqa: B017 - the trigger's own error, any class
            async with untenanted_session() as session:
                await session.execute(text(statement), {"r": ref})

    async with untenanted_session() as session:
        enabled = (
            await session.execute(
                text(
                    "SELECT tgname, tgenabled FROM pg_trigger "
                    "WHERE tgrelid = 'platform_ai_usage'::regclass AND NOT tgisinternal "
                    "ORDER BY tgname"
                )
            )
        ).all()
    assert [row[0] for row in enabled] == [
        "platform_ai_usage_append_only",
        "platform_ai_usage_forbid_truncate",
    ]
    # 'A' is ENABLE ALWAYS; 'O' (the default) would be switched off by replica mode.
    assert {row[1] for row in enabled} == {"A"}


# --------------------------------------------------------------- the door


async def test_the_admin_realm_was_refused_outright_and_is_not_any_more() -> None:
    """The route exists, declares `copilot:admin`, and is admin-realm.

    FAILS IF: the route is unmounted, loses its realm (which would open a console surface
    to every tenant owner whose role happens to hold the permission string —
    `rbac.ADMIN_REALM_PREFIXES` argues this at length), or declares a permission a client
    role holds.
    """
    from apps.api.core.rbac import iter_api_routes

    routes = {route.path: route for route in iter_api_routes(app)}
    assert "/v1/admin/copilot/ask" in routes
    declared = (routes["/v1/admin/copilot/ask"].openapi_extra or {}).get("x-calevate-permission")
    assert declared == "copilot:admin"
    # An admin-realm-only permission: no client role holds it.
    assert not role_has("owner", "copilot:admin")
    assert not role_has("staff", "copilot:admin")
    assert role_has("operator", "copilot:admin")
    assert role_has("superadmin", "copilot:admin")


async def test_asking_is_still_a_mutation_and_the_impersonation_exemption_is_narrow() -> None:
    """D-22's line, and the ONE hole in it, both pinned.

    `copilot:admin` is mutating (it spends real money on an append-only ledger) and is
    exempted from the impersonation refusal — because its spend can only land on the
    PLATFORM's ledger, so there is no client balance a view-as session could move.
    `copilot:use` is NOT exempted and must never be: that permission spends the client's own
    included allowance, which is the exact hazard the listing exists for.

    FAILS IF: somebody widens the exemption set, or drops either permission from
    `MUTATING_PERMISSIONS` (which would silently unguard `POST /v1/copilot/confirm`).
    """
    assert "copilot:admin" in MUTATING_PERMISSIONS
    assert "copilot:use" in MUTATING_PERMISSIONS
    assert frozenset({"copilot:admin"}) == IMPERSONATION_PERMITTED_MUTATIONS
    assert "copilot:use" not in IMPERSONATION_PERMITTED_MUTATIONS
    # Every write tool's permission stays refused under impersonation, which is what keeps
    # a view-as operator unable to CHANGE anything through the assistant.
    for permission in ("leads:write", "leads:dispatch", "org:manage", "kb:write"):
        assert permission in MUTATING_PERMISSIONS
        assert permission not in IMPERSONATION_PERMITTED_MUTATIONS


async def test_the_operator_tier_holds_the_admin_copilot_and_the_client_tiers_do_not() -> None:
    """The tier boundary is `SUPERADMIN_ONLY_PERMISSIONS` and nothing else (rbac docstring).
    Asking an assistant about platform state is not one of the four vital authorities."""
    assert "copilot:admin" in ROLE_PERMISSIONS["operator"]
    assert "copilot:admin" in ROLE_PERMISSIONS["superadmin"]
    assert "copilot:admin" not in ROLE_PERMISSIONS["owner"]
    assert "copilot:admin" not in ROLE_PERMISSIONS["staff"]


# --------------------------------------------------------------- the tools


async def test_the_two_realms_offer_different_tools_and_each_is_stable() -> None:
    """Two realms, two cache prefixes; per-request variation within a realm is still zero.

    Prompt caching keys on a leading run of identical tokens over *"both the messages array
    and tool definitions"* (MicrosoftDocs/azure-ai-docs,
    `articles/foundry/openai/includes/how-to-prompt-caching-content.md` @ main, read
    1 Sep 2026), so a realm is a partition that keeps two caches warm and a screen or a role
    is a partition that keeps none.
    """
    assert copilot_service.tool_array("admin") != copilot_service.tool_array("client")
    assert copilot_service.tool_array("admin") == copilot_service.tool_array("admin")
    admin_names = {schema["function"]["name"] for schema in copilot_service.tool_array("admin")}
    assert admin_names >= admin_tools.ADMIN_READ_TOOL_NAMES
    assert admin_names >= copilot_tools.READ_TOOL_NAMES


async def test_an_account_tool_with_no_account_open_refuses_and_names_no_default() -> None:
    """`ToolContext.tenant_id` became Optional so the platform tools could exist, and the
    one failure mode that Optional could have had is a tenant-scoped tool silently falling
    back to some default account.

    FAILS IF: the scope guard is removed — the tool would then raise inside
    `tenant_session(None)` and the operator would get "could not be read just now" for a
    question that has a real answer.
    """
    answer = await copilot_tools.run_read_tool(
        "leads_search",
        "{}",
        context=copilot_tools.ToolContext(tenant_id=None, role="operator"),
        registry=copilot_service._read_tool_registry("admin"),
    )
    assert "no account is open" in answer
    assert "Refused" in answer


async def test_a_client_cannot_name_a_platform_tool_at_all() -> None:
    """Two registries, not one namespace with a permission in front of it."""
    answer = await copilot_tools.run_read_tool(
        "platform_tenants",
        "{}",
        context=copilot_tools.ToolContext(tenant_id=uuid.uuid4(), role="owner"),
        registry=copilot_service._read_tool_registry("client"),
    )
    assert "There is no tool called" in answer


async def test_every_platform_tool_is_gated_on_a_permission_no_client_role_holds() -> None:
    """A tool that judged itself by a looser permission than its own SCREEN would be a way
    around that screen (`tools.py`'s rule, applied to the console's own reads)."""
    for tool in admin_tools.ADMIN_READ_TOOLS:
        assert tool.scope == "platform"
        assert not role_has("owner", tool.permission)
        assert not role_has("staff", tool.permission)
        assert role_has("operator", tool.permission)


async def test_the_runbooks_are_indexed_and_an_alarm_code_finds_its_procedure() -> None:
    """The founder's own example question, asked of the mechanism that answers it.

    NO VECTOR STORE AND NO EMBEDDINGS (D-28 is the founder's open decision): the index is
    our own text scored by `retrieval/compiled_facts`' own ranker.

    FAILS IF: `runbooks/` stops being readable from the process, or the section splitter
    stops producing headed sections.
    """
    from apps.api.copilot import runbooks

    assert runbooks.index(), "the runbook corpus did not load"
    found = runbooks.search("engine_error_spike")
    assert found, "an alarm code in runbooks/alarm-index.md found no section"
    assert any(
        "engine_error_spike" in section.body or "engine_error_spike" in section.heading
        for section in found
    )
    # The path is repo-relative and never absolute: it reaches an operator's screen.
    assert all(section.path.startswith("runbooks/") for section in found)


def test_the_runbooks_are_shipped_in_the_image() -> None:
    """The half-wired shape this test exists to prevent: a tool that works in every test and
    returns nothing in production because the corpus was never copied into the image.

    FAILS IF: the `COPY runbooks runbooks` line is removed from the Dockerfile.
    """
    dockerfile = Path(__file__).resolve().parents[1] / "Dockerfile"
    assert re.search(r"^COPY runbooks runbooks$", dockerfile.read_text(), re.M)


# --------------------------------------------------------------- the memory


async def test_an_admin_memory_cannot_be_recalled_into_a_clients_conversation() -> None:
    """TWO TABLES, TWO POPULATIONS, NO SHARED PREDICATE.

    `copilot_memories.user_id` is a foreign key to `users` and an operator is a row in
    `admin_users`, so one table would have been a constraint violation when the ids differ
    and a cross-realm leak when they collide. This asserts the separation at the level that
    matters: an admin memory is not visible to the client recall query.

    FAILS IF: somebody merges the tables, or drops `admin_copilot_memories`' own writer.
    """
    admin_id = await _make_admin()
    async with untenanted_session() as session:
        written = await admin_memory.remember_exchange(
            session,
            admin_user_id=admin_id,
            viewing_tenant_id=None,
            screen_route="/admin/ops",
            question="is dialling halted",
            answer="no, outbound is running",
        )
        assert written is not None
        recalled = await admin_memory.recall(
            session, admin_user_id=admin_id, viewing_tenant_id=None, question="dialling halted"
        )
        # The client table cannot see it: no row of it carries this id.
        leaked = (
            await session.execute(
                text("SELECT count(*) FROM copilot_memories WHERE id = :id"), {"id": written}
            )
        ).scalar_one()
    assert [item.id for item in recalled] == [written]
    assert leaked == 0


async def test_a_memory_formed_on_one_account_is_not_recalled_on_another() -> None:
    """The one thing the admin memory adds to its client twin.

    A fact learned while looking at one client is a fact about THAT client, and recalling it
    into a question asked on a different account's page is how an assistant comes to answer
    about the wrong client with total confidence. Platform-level memories (no viewing
    tenant) stay eligible everywhere, because they are about the platform.

    FAILS IF: the `viewing_tenant_id` predicate is dropped from either recall channel.
    """
    admin_id = await _make_admin()
    # ITS OWN ACCOUNT, so nothing here depends on another suite's rows (`ai_quota_test.py`'s
    # concurrency discipline) and the foreign key on `viewing_tenant_id` is satisfied.
    created = await admin_service.create_organization(
        name="Copilot Clinic",
        slug=f"adc-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email="books@example.com",
        language="te-IN",
        created_by=None,
    )
    tenant_a: uuid.UUID = created["id"]
    other_created = await admin_service.create_organization(
        name="Other Clinic",
        slug=f"adc-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email="books@example.com",
        language="te-IN",
        created_by=None,
    )
    other: uuid.UUID = other_created["id"]

    async with untenanted_session() as session:
        scoped = await admin_memory.remember_exchange(
            session,
            admin_user_id=admin_id,
            viewing_tenant_id=tenant_a,
            screen_route="/admin/tenants/x",
            question="what is blocking their kyc",
            answer="the founder is holding it",
        )
        platform_wide = await admin_memory.remember_exchange(
            session,
            admin_user_id=admin_id,
            viewing_tenant_id=None,
            screen_route="/admin/ops",
            question="what is blocking dialling",
            answer="nothing, it is running",
        )
        on_the_same_account = await admin_memory.recall(
            session, admin_user_id=admin_id, viewing_tenant_id=tenant_a, question="blocking"
        )
        on_another_account = await admin_memory.recall(
            session, admin_user_id=admin_id, viewing_tenant_id=other, question="blocking"
        )
    assert scoped in {item.id for item in on_the_same_account}
    assert scoped not in {item.id for item in on_another_account}
    assert platform_wide in {item.id for item in on_another_account}


async def test_the_platform_brake_refuses_an_operator_and_does_not_offer_a_wallet() -> None:
    """The ₹25,000 brake, driven rather than described — it had never been exercised.

    `require_platform_ai` is the only ceiling this surface has: an operator has no
    allowance to sell, so there is no per-caller quota behind it and nothing else stops
    admin-copilot spend running away on OUR key. The arm that raises was uncovered, which
    means the one control on that spend had never been shown to fire.

    **The refusal must NOT be the client-facing code, and that is the real assertion.**
    `ai_paused_platform_wide` is what opens the client's "buy more AI" wallet dialog. An
    operator cannot buy any, so reusing it would put a purchase modal in front of somebody
    with nothing to purchase — which is why the admin code is deliberately different.
    """
    month = current_billing_month()
    async with untenanted_session() as session:
        # At the brake exactly: `tripped` is `>=`, so the boundary is the interesting
        # value — one paisa under would prove nothing about the comparison.
        await session.execute(
            text(
                "INSERT INTO platform_ai_spend (month, spend_inr, requests) "
                "VALUES (:m, :s, 1) ON CONFLICT (month) DO UPDATE SET spend_inr = :s"
            ),
            {"m": month, "s": PLATFORM_AI_BRAKE_INR},
        )

    async with untenanted_session() as session:
        assert (await read_platform_ai_spend(session)).tripped, "premise: the brake is at its limit"
        with pytest.raises(ProblemError) as exc:
            await platform_ai.require_platform_ai(session)

    assert exc.value.code == "admin_ai_paused_platform_wide", (
        "an operator was refused with the CLIENT's code, which is what opens a wallet "
        "dialog — and an operator has no wallet"
    )
    assert exc.value.kind == "transient"

    # Clean up: the brake is global, so leaving it tripped would refuse every later test.
    async with untenanted_session() as session:
        await session.execute(text("DELETE FROM platform_ai_spend WHERE month = :m"), {"m": month})


async def test_below_the_brake_an_operator_is_served() -> None:
    """The other arm. Without this the clause above passes against a `require_platform_ai`
    that refuses unconditionally."""
    month = current_billing_month()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO platform_ai_spend (month, spend_inr, requests) "
                "VALUES (:m, :s, 1) ON CONFLICT (month) DO UPDATE SET spend_inr = :s"
            ),
            {"m": month, "s": PLATFORM_AI_BRAKE_INR - Decimal("0.0001")},
        )
    async with untenanted_session() as session:
        await platform_ai.require_platform_ai(session)  # must not raise
        await session.execute(text("DELETE FROM platform_ai_spend WHERE month = :m"), {"m": month})
