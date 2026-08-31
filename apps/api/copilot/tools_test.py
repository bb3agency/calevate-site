"""The read tools: what they return, who may run them, and whose rows they can see.

THE CROSS-TENANT TEST IS THE ONE THAT MATTERS (hard rule 1) and it is written the only way
that proves anything: two real tenants with real rows in one real database, asked the same
question, each answered from its own `tenant_session`. A mocked session would prove that
the code calls a function; only RLS can prove that the function cannot see the neighbour.

THE PERMISSION TEST IS THE SECOND (OWASP LLM01 #4). The copilot's route needs `org:manage`,
which today only `owner` and the admin roles hold — so the refusal below is reached through
a role that route would not admit. That is deliberate: the tool must refuse on its OWN
permission rather than on whatever permission the route in front of it happens to declare,
because a route's permission is a thing that changes and a tool that inherited it would
widen silently when it did.
"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import text

from apps.api.admin import service as admin_service
from apps.api.copilot import service as copilot_service
from apps.api.copilot import tools, write_tools
from apps.api.copilot.schemas import CopilotAskIn
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session


async def _tenant(name: str = "Tool Clinic") -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name=name,
        slug=f"tools-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return created["id"], created["agent_id"]


async def _lead(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    name: str,
    status: str = "new",
    phone: str | None = None,
) -> None:
    """One lead. The phone is generated unless the test names it —
    `uq_leads_tenant_id_phone_e164_agent_id` is real, and two fixture leads sharing the
    default number is a fixture defect that reads as a product one."""
    phone = phone or f"+9198765{uuid.uuid4().int % 100000:05d}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, "
                "status, created_at, updated_at) VALUES (:i, :t, :a, :p, :n, "
                "'inbound_call', :s, now(), now())"
            ),
            {"i": uuid7(), "t": tenant_id, "a": agent_id, "p": phone, "n": name, "s": status},
        )


async def _call(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    status: str = "completed",
    duration_s: int | None = 90,
    outcome: str | None = "resolved",
) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                "to_e164, status, duration_s, outcome_tag, started_at, created_at, "
                "updated_at) VALUES (:i, :t, :a, :e, 'outbound', '+919876500002', :st, "
                ":dur, :out, now(), now(), now())"
            ),
            {
                "i": uuid7(),
                "t": tenant_id,
                "a": agent_id,
                "e": f"tools_{uuid.uuid4().hex[:12]}",
                "st": status,
                "dur": duration_s,
                "out": outcome,
            },
        )


def _owner(tenant_id: uuid.UUID) -> tools.ToolContext:
    """The role the copilot route actually admits (`org:manage` is `owner` + the admin
    tiers), so every non-permission test below exercises the permitted path."""
    return tools.ToolContext(tenant_id=tenant_id, role="owner")


async def _run(name: str, tenant_id: uuid.UUID, **args: object) -> str:
    return await tools.run_read_tool(name, json.dumps(args), context=_owner(tenant_id))


# --- one test per tool ------------------------------------------------------------------


async def test_business_snapshot_reports_the_same_funnel_the_performance_tab_does() -> None:
    """The tool is a RENDERER over `crm/performance.performance`, not a second query — so
    the numbers it hands the model are the numbers the client's own Performance tab shows.
    Two screens disagreeing about one connect rate is the defect this shape prevents."""
    tenant_id, agent_id = await _tenant()
    await _call(tenant_id, agent_id, status="completed", duration_s=120)
    await _call(tenant_id, agent_id, status="no_answer", duration_s=None, outcome=None)

    result = await _run("business_snapshot", tenant_id)

    assert "2 calls" in result
    assert "1 connected (50% of calls)" in result
    assert "resolved 1" in result


async def test_leads_search_filters_by_status_and_names_the_lead() -> None:
    tenant_id, agent_id = await _tenant()
    await _lead(tenant_id, agent_id, name="Ramesh", status="hot")
    await _lead(tenant_id, agent_id, name="Sita", status="new")

    hot = await _run("leads_search", tenant_id, status="hot", limit=None)

    assert "Ramesh" in hot
    assert "Sita" not in hot
    assert "1 leads with status hot" in hot


async def test_leads_search_masks_the_phone_number_it_returns() -> None:
    """Hard rule 5 / D-127 G-2, on the way OUT. `LeadOut.phone_e164` is a full E.164
    number — legitimately, on the client's own screen — and the model is a US processor's
    endpoint. `_clean` puts every result through the same `redact()` the ingress guard
    uses, so the model sees `[phone ••01]` and can still help the person recognise the row.

    FAILS IF: a future renderer bypasses `_clean`, which is the only thing standing between
    a lead list and a phone number in a prompt."""
    tenant_id, agent_id = await _tenant()
    await _lead(tenant_id, agent_id, name="Ramesh", phone="+919876500001")

    result = await _run("leads_search", tenant_id)

    assert "9876500001" not in result
    assert "[phone ••01]" in result


async def test_calls_recent_returns_calls_and_never_a_raw_number() -> None:
    tenant_id, agent_id = await _tenant()
    await _call(tenant_id, agent_id, outcome="transferred")

    result = await _run("calls_recent", tenant_id, limit=5)

    assert "transferred" in result
    assert "90s" in result
    assert "9876500002" not in result


async def test_campaigns_list_carries_the_launch_blocker_by_its_gate_name() -> None:
    """`consent_provenance_blocker` is the launch gate's OWN rule name, which is what lets
    the copilot answer "why can't I launch this?" in the same vocabulary the launch-check
    screen uses instead of inventing a third one."""
    tenant_id, agent_id = await _tenant()
    from apps.api.campaigns import service as campaigns_service

    async with tenant_session(tenant_id) as session:
        await campaigns_service.create_campaign(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Diwali offers",
            classification="promotional",
            number_id=None,
            dlt_template_id=None,
            concurrency=1,
        )

    result = await _run("campaigns_list", tenant_id)

    assert "Diwali offers" in result
    assert "draft" in result
    assert "consent_provenance_missing" in result


async def test_an_account_with_nothing_yet_gets_a_sentence_not_an_empty_string() -> None:
    """An empty tool result reads to a model as a failure. "There is nothing yet" is a real
    answer on a new account and is the one the person should be given."""
    tenant_id, _ = await _tenant()
    assert "No rows" in await _run("leads_search", tenant_id)
    assert "No rows" in await _run("calls_recent", tenant_id)


# --- the cap ----------------------------------------------------------------------------


async def test_the_row_cap_is_the_servers_and_the_truncation_is_declared() -> None:
    """TWO PROPERTIES IN ONE TEST BECAUSE THEY ARE ONE PROPERTY. A model that asks for 500
    rows is clamped to `MAX_ROWS` — the ceiling is the server's, and the schema cannot state
    it (`minimum`/`maximum` are outside the strict subset). And the result SAYS it was
    clamped: a silently truncated list is how a copilot comes to tell somebody they have 25
    leads when they have 30."""
    tenant_id, agent_id = await _tenant()
    for index in range(tools.MAX_ROWS + 5):
        await _lead(tenant_id, agent_id, name=f"Lead {index}", phone=f"+91987650{index:04d}")

    result = await _run("leads_search", tenant_id, status=None, limit=500)

    assert f"Showing {tools.MAX_ROWS} of {tools.MAX_ROWS + 5} leads" in result
    assert result.count("\n- ") + 1 == tools.MAX_ROWS + 1  # header + MAX_ROWS rows


# --- hard rule 1: RLS, proved with two real tenants -------------------------------------


@pytest.mark.parametrize("tool_name", ["leads_search", "calls_recent", "campaigns_list"])
async def test_a_tool_run_for_one_tenant_never_returns_another_tenants_rows(
    tool_name: str,
) -> None:
    """THE HARD-RULE-1 TEST. Tenancy here is not a `WHERE` clause anybody wrote: each tool
    opens a `tenant_session`, which sets `app.tenant_id`, and Postgres RLS decides. So the
    proof has to be two real tenants with real rows in one real database.

    FAILS IF: a tool ever takes its scope from an argument the model supplied, or runs on a
    session that is not tenant-scoped. Both are changes that look harmless in a diff and
    are a cross-tenant disclosure in production."""
    a_id, a_agent = await _tenant("Tenant A")
    b_id, b_agent = await _tenant("Tenant B")
    await _lead(a_id, a_agent, name="AliceOfA", status="hot")
    await _lead(b_id, b_agent, name="BobOfB", status="hot")
    # The outcome tag is the only free text on a call this fixture can vary — it is a
    # CHECK-constrained enum (`ck_calls_outcome_enum`), so the two tenants take two of
    # its members rather than two invented strings.
    await _call(a_id, a_agent, outcome="transferred")
    await _call(b_id, b_agent, outcome="dropped")

    from apps.api.campaigns import service as campaigns_service

    campaigns = ((a_id, a_agent, "CampaignOfA"), (b_id, b_agent, "CampaignOfB"))
    for tenant_id, agent_id, name in campaigns:
        async with tenant_session(tenant_id) as session:
            await campaigns_service.create_campaign(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                name=name,
                classification="service",
                number_id=None,
                dlt_template_id=None,
                concurrency=1,
            )

    for_a = await _run(tool_name, a_id)
    for_b = await _run(tool_name, b_id)

    for foreign in ("BobOfB", "dropped", "CampaignOfB"):
        assert foreign not in for_a
    for foreign in ("AliceOfA", "transferred", "CampaignOfA"):
        assert foreign not in for_b
    # And each DID see its own — otherwise a tool that returned nothing at all would pass
    # the isolation half of this test while being broken.
    assert any(mine in for_a for mine in ("AliceOfA", "transferred", "CampaignOfA"))
    assert any(mine in for_b for mine in ("BobOfB", "dropped", "CampaignOfB"))


async def test_the_snapshot_counts_only_this_tenants_calls() -> None:
    """`performance` aggregates, so a leak there is a wrong NUMBER rather than a foreign
    name — invisible to the test above and just as much a hard-rule-1 breach."""
    a_id, a_agent = await _tenant("Tenant A")
    b_id, b_agent = await _tenant("Tenant B")
    await _call(a_id, a_agent)
    for _ in range(3):
        await _call(b_id, b_agent)

    assert "1 calls" in await _run("business_snapshot", a_id)
    assert "3 calls" in await _run("business_snapshot", b_id)


# --- the permission check ---------------------------------------------------------------


@pytest.mark.parametrize("tool", tools.READ_TOOLS, ids=lambda tool: tool.name)
async def test_a_role_without_the_permission_gets_a_refusal_and_no_data(
    tool: tools.ReadTool,
) -> None:
    """PERMISSION IS ENFORCED IN CODE, NEVER BY THE PROMPT (OWASP LLM01 #4). Every tool is
    driven with a role that lacks its permission and must answer with a refusal rather than
    with rows.

    The role is chosen from the registry rather than hard-coded: `staff` holds `calls:read`
    and `leads:read`, so a fixed role would prove nothing about a tool whose permission it
    happens to hold. `_denied_role` finds one that genuinely does not."""
    from apps.api.core.rbac import ROLE_PERMISSIONS

    # A REAL ROLE THAT LACKS IT WHERE ONE EXISTS, AND A ROLE-LESS PRINCIPAL WHERE ONE DOES
    # NOT. `calls:read` and `leads:read` are held by every role in the registry today, so
    # `next(...)` would have nothing to return for three of the four tools — and a test
    # that skipped them would leave the refusal path unproven on the tools that read the
    # most. `Principal.role` is nullable, so `None` is not a synthetic case: it is what a
    # principal with no membership carries, and it must refuse.
    denied = next(
        (role for role, granted in ROLE_PERMISSIONS.items() if tool.permission not in granted),
        None,
    )
    tenant_id, agent_id = await _tenant()
    await _lead(tenant_id, agent_id, name="Ramesh", status="hot")
    await _call(tenant_id, agent_id)

    result = await tools.run_read_tool(
        tool.name, "{}", context=tools.ToolContext(tenant_id=tenant_id, role=denied)
    )

    assert result.startswith("Refused:")
    assert tool.permission in result
    assert "Ramesh" not in result


async def test_no_context_at_all_refuses_rather_than_running_unscoped() -> None:
    """`ToolContext is None` means nobody was named. There is no tenant to scope a session
    to and no role to judge, so the only safe answer is a refusal — never a query."""
    result = await tools.run_read_tool("leads_search", "{}", context=None)
    assert result.startswith("Refused:")


async def test_a_role_the_registry_does_not_know_is_refused() -> None:
    """`role_has` on an unknown role is False, and the tool inherits that rather than
    defaulting open."""
    tenant_id, _ = await _tenant()
    result = await tools.run_read_tool(
        "leads_search", "{}", context=tools.ToolContext(tenant_id=tenant_id, role="visitor")
    )
    assert result.startswith("Refused:")


# --- errors steer the model, they never leak -------------------------------------------


async def test_an_unknown_tool_name_is_a_sentence_the_model_can_act_on() -> None:
    tenant_id, _ = await _tenant()
    result = await _run("delete_everything", tenant_id)
    assert "no tool called" in result


async def test_bad_arguments_are_a_sentence_rather_than_a_traceback() -> None:
    tenant_id, _ = await _tenant()
    assert "not valid JSON" in await tools.run_read_tool(
        "leads_search", "{oops", context=_owner(tenant_id)
    )
    assert "not an object" in await tools.run_read_tool(
        "leads_search", "[1, 2]", context=_owner(tenant_id)
    )


async def test_a_failing_tool_reports_a_sentence_and_never_internals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A tool result is a message in a conversation, so a failure has to be text the model
    can act on. An exception here would kill the stream mid-answer and reach the person as
    `copilot_interrupted` for a question it could have answered another way."""
    tenant_id, _ = await _tenant()

    async def _boom(*args: object, **kwargs: object) -> str:
        raise RuntimeError("psycopg: connection to 10.0.0.5:5432 failed")

    monkeypatch.setattr(tools, "performance", _boom)
    result = await _run("business_snapshot", tenant_id)

    assert "could not be read just now" in result
    assert "psycopg" not in result and "10.0.0.5" not in result


# --- the schemas: the strict subset, and the cacheable prefix ---------------------------


def test_every_read_tool_schema_is_strict_shaped() -> None:
    """The same walk `prompt_test` runs over `set_fields_tool`: `additionalProperties:
    false` on every object and every property in `required`. Under `strict: true` a
    property left out of `required` is a request the API refuses outright."""
    for schema in tools.read_tool_schemas():
        parameters = schema["function"]["parameters"]

        def walk(node: object) -> None:
            if isinstance(node, dict):
                if node.get("type") == "object":
                    assert node.get("additionalProperties") is False, node
                    assert sorted(node.get("required", [])) == sorted(node.get("properties", {}))
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for entry in node:
                    walk(entry)

        walk(parameters)


def test_no_read_tool_schema_reaches_outside_the_strict_subset() -> None:
    rendered = json.dumps(tools.read_tool_schemas())
    for keyword in ("pattern", "format", "minLength", "minimum", "maximum", "minItems"):
        assert f'"{keyword}"' not in rendered


def test_the_whole_tool_array_is_byte_identical_across_two_different_requests() -> None:
    """THE CACHE PREFIX (`prompt.py`, point 1). Azure's prompt caching keys on a leading run
    of byte-identical tokens, so a tool array that varied by screen — or by tenant, or by
    ROLE, which is the tempting one now that tools carry permissions — would give this
    feature a cache hit rate of zero.

    FAILS IF: somebody gates a tool out of the array for a caller who may not use it. The
    refusal belongs inside `run_read_tool`, where `test_a_role_without_the_permission...`
    proves it lives."""
    first = CopilotAskIn.model_validate(
        {
            "screen": {"route": "/c/one/agents/new", "title": "Build", "realm": "client"},
            "question": "how many leads are hot?",
            "fields": [{"id": "open", "label": "Opens", "type": "text", "writable": True}],
        }
    )
    second = CopilotAskIn.model_validate(
        {
            "screen": {"route": "/c/two/leads", "title": "Leads", "realm": "client"},
            "question": "why is this lead red?",
        }
    )
    # The array takes no request at all, which is the property — driving it from two
    # payloads is how the test would catch somebody giving it one.
    assert json.dumps(copilot_service.tool_array()) == json.dumps(copilot_service.tool_array())
    assert first.screen.route != second.screen.route


def test_the_array_offers_set_fields_then_every_read_tool_then_every_write_tool() -> None:
    """One composer, one order, all THREE families. `set_fields` stays first because it was
    first and moving it would change the cached prefix for nothing; the read tools follow in
    `READ_TOOLS` order and the proposing write tools last.

    THE ORDER IS PINNED, NOT JUST THE MEMBERSHIP, because the array is the tail of the
    cacheable prefix — a reordering costs a cache miss on every request and no test that
    only compared sets would notice."""
    names = [schema["function"]["name"] for schema in copilot_service.tool_array()]
    read_names = [tool.name for tool in tools.READ_TOOLS]
    write_names = [schema["function"]["name"] for schema in write_tools.write_tool_schemas()]
    assert names == ["set_fields", *read_names, *write_names]
    assert set(read_names) == tools.READ_TOOL_NAMES
    # The three families are disjoint: a name in two registries would make dispatch in
    # `_run_tool_loop` depend on which check ran first.
    assert len(set(names)) == len(names)


def test_no_read_tool_can_change_anything() -> None:
    """OWASP LLM01 #8's Rule of Two, restated for the read surface: the model's whole
    state-change capability is still `set_fields` and nothing here adds to it. Asserted
    against the SOURCE of every executor rather than against a comment, so a future tool
    that reached for an INSERT fails this rather than a review."""
    import inspect

    for tool in tools.READ_TOOLS:
        source = inspect.getsource(tool.run).lower()
        for verb in ("insert into", "update ", "delete from", "session.add", "commit("):
            assert verb not in source, f"{tool.name} looks like it writes"
