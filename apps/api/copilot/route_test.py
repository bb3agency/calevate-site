"""The seam: `POST /v1/copilot/ask` — subject, gate, run, meter, over real HTTP.

WHAT IS PROVED HERE, and each one is a property somebody could break silently:

1. **Tenancy.** The route is tenant-scoped and the ledger row it writes belongs to the
   tenant that asked, and to no other. A cross-tenant read returns zero rows (hard rule 1).
2. **A refusal costs nothing.** The ceiling refuses BEFORE a token is spent — checked by
   asserting that the provider was never reached at all, not merely that no ledger row
   landed, because a ledger assertion alone passes on a path that paid Microsoft and failed
   to record it.
3. **Metering at the published price.** `unit_cost_paid` is `rates.llm_inr_per_ktok`'s
   figure for the model the setting names, never a literal in this file.
4. **Nothing is persisted.** No table gains a row that holds the question, the answer or a
   field value.
5. **The refusals are events, not silence.** A stream that stops is indistinguishable from
   a network failure, and a person cannot act on either.

CONCURRENCY AND SHARED STATE: every test mints its own tenant. `platform_ai_spend` is the
one row that is not per-tenant, and the autouse fixture severs this file's dependency on it
for the reason `ai_quota_test` records at length — a suite whose result depends on how many
times it has been run is not measuring the code.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx
import pytest
from calevate_shared.engine import AZURE_OPENAI_DEFAULT_MODEL
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.api_security_test import _make_tenant

from apps.api.billing import ai_quota, rates
from apps.api.copilot import service
from apps.api.copilot.sanitize import has_invisible
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.db.transition import _identifier
from apps.api.main import app
from apps.workers import chat
from apps.workers.extraction import assist_capability

ASK = "/v1/copilot/ask"

BODY: dict[str, Any] = {
    "screen": {"route": "/c/x/agents/new", "title": "Build an agent", "realm": "client"},
    "question": "set the opening time to nine",
    "fields": [
        {"id": "open", "label": "Opens", "type": "text", "value": None, "writable": True},
        {"id": "status", "label": "Status", "type": "text", "value": "draft"},
    ],
    "facts": [{"key": "vertical", "label": "Vertical template", "value": "clinic"}],
    "history": [],
}


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _headers(token: str, slug: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}


@pytest.fixture(autouse=True)
def _the_platform_brake_is_not_this_suites_business(monkeypatch: pytest.MonkeyPatch) -> None:
    async def not_tripped(*args: Any, **kwargs: Any) -> bool:
        return False

    monkeypatch.setattr(ai_quota, "platform_brake_tripped", not_tripped)


@pytest.fixture
def azure_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """A deployment whose ONLY assistant leg is Azure.

    ⚠ `platform_llm_model` is pinned here and that is new (D-530). An Azure credential no
    longer decides the leg: the platform default is `gemini-2.5-flash-lite`, so an account
    that chose no model resolves to GOOGLE, holds no Google credential, and the assistant
    correctly substitutes with a disclosure. Right behaviour, wrong test — these assert
    Azure's own token count reaching the ledger, which needs the answer to come from Azure.
    """
    settings = get_settings()
    monkeypatch.setattr(settings, "azure_openai_resource", "calevate-test", raising=False)
    monkeypatch.setattr(settings, "azure_openai_api_key", "k", raising=False)
    monkeypatch.setattr(settings, "azure_openai_deployment", "dep", raising=False)
    monkeypatch.setattr(settings, "sarvam_api_key", None, raising=False)
    monkeypatch.setattr(settings, "platform_llm_model", AZURE_OPENAI_DEFAULT_MODEL, raising=False)


def _fake_provider(
    monkeypatch: pytest.MonkeyPatch,
    *,
    content: str = "Done.",
    arguments: str | None = None,
    usage: chat.TokenUsage | None = None,
) -> list[str]:
    """Replace `chat.stream` and record that it was reached. The list is the instrument for
    "a refusal costs nothing": it stays empty when the gate did its job."""
    reached: list[str] = []

    def _stream(leg: chat.ChatLeg, messages: Any, **kwargs: Any) -> AsyncIterator[chat.StreamEvent]:
        reached.append(leg.wire_model)
        calls = (
            (chat.ToolCall(id="c1", name="set_fields", arguments=arguments),)
            if arguments is not None
            else ()
        )

        async def _iterate() -> AsyncIterator[chat.StreamEvent]:
            if content:
                yield chat.StreamEvent(text=content)
            yield chat.StreamEvent(
                outcome=chat.ChatOutcome(
                    content=content,
                    tool_calls=calls,
                    finish_reason="tool_calls" if calls else "stop",
                    usage=usage,
                )
            )

        return _iterate()

    monkeypatch.setattr(chat, "stream", _stream)
    return reached


async def _events(
    http: AsyncClient, token: str, slug: str, body: dict[str, Any] | None = None
) -> list[tuple[str, Any]]:
    """The SSE stream as `(event, parsed data)` pairs.

    Read off the WIRE rather than off the generator: the frame encoding, the event names
    and the content type are half the contract the browser agent is building against, and a
    test that called the handler directly would prove none of them.
    """
    out: list[tuple[str, Any]] = []
    async with http.stream("POST", ASK, headers=_headers(token, slug), json=body or BODY) as r:
        assert r.status_code == 200, await r.aread()
        assert r.headers["content-type"].startswith("text/event-stream")
        name: str | None = None
        async for line in r.aiter_lines():
            if line.startswith("event:"):
                name = line[len("event:") :].strip()
            elif line.startswith("data:") and name is not None:
                out.append((name, json.loads(line[len("data:") :].strip())))
                name = None
    return out


async def _usage_rows(tenant_id: UUID) -> list[tuple[str, Decimal, Decimal, dict[str, Any]]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT unit_type, qty, unit_cost_paid, meta FROM usage_events "
                    "WHERE tenant_id = :tid AND unit_type LIKE 'ai_assist%' ORDER BY unit_type"
                ),
                {"tid": tenant_id},
            )
        ).all()
    return [(str(r[0]), Decimal(str(r[1])), Decimal(str(r[2])), dict(r[3] or {})) for r in rows]


async def _audit(tenant_id: UUID) -> list[tuple[str, str, str]]:
    """`(action, object_type, object_id)` for this tenant's copilot rows.

    NO `summary` COLUMN IS SELECTED BECAUSE `audit_log` HAS NONE. `write_audit`'s summary
    goes to the LOG STREAM, sanitized by `core/logging.redact_mapping`, and hashing a field
    the row does not carry would make the audit chain unverifiable
    (`compliance/audit.py:360-366`). A test that selected it would be asserting against a
    column this repo deliberately does not have.
    """
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT action, object_type, object_id FROM audit_log "
                    "WHERE tenant_id = :tid AND action = 'copilot.ask' ORDER BY at"
                ),
                {"tid": str(tenant_id)},
            )
        ).all()
    return [(str(r[0]), str(r[1]), str(r[2])) for r in rows]


# --- 1. the happy path, end to end ----------------------------------------------------


async def test_a_fill_reaches_the_browser_and_is_metered_at_the_published_price(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole seam. The price is READ from `rates.llm_inr_per_ktok` rather than written
    here: a literal would still pass after somebody changed the rate card, which is the
    class of defect D-410 made `record_ai_assist_usage` derive the price to remove."""
    tenant_id, slug, token = await _make_tenant()
    _fake_provider(
        monkeypatch,
        content="Nine in the morning.",
        arguments=json.dumps({"items": [{"field_id": "open", "value": "09:00"}]}),
        usage=chat.TokenUsage(prompt_tokens=1200, output_tokens=800),
    )

    async with _client() as http:
        events = await _events(http, token, slug)

    assert [name for name, _ in events] == ["text", "fill", "done"]
    assert events[0][1] == {"delta": "Nine in the morning."}
    assert events[1][1] == {"items": [{"field_id": "open", "value": "09:00"}]}
    assert events[2][1] == {"disclosure": None, "metered": True}

    model = get_settings().azure_openai_model
    price = rates.llm_inr_per_ktok(model)
    rows = await _usage_rows(tenant_id)
    assert [(unit, qty, cost) for unit, qty, cost, _ in rows] == [
        ("ai_assist_ktok_in", Decimal("1.2"), price["in"]),
        ("ai_assist_ktok_out", Decimal("0.8"), price["out"]),
    ]
    # The ledger names the surface, so "which screen spent this" is a query.
    assert {meta.get("feature") for _, _, _, meta in rows} == {"copilot"}


async def test_the_audit_row_records_the_act_and_the_log_line_carries_no_content(
    azure_only: None, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A record of a processing act: ids, names and counts, and nothing a person typed.

    THE ASSERTION IS ON THE SANITIZED LOG EXTRAS, not on a column — `audit_log` carries no
    summary column (see `_audit`). What reaches the stream has already been through
    `redact_mapping`, and this is what proves the summary we compose survives it as
    something an operator can read AND carries no question, answer or field value
    (hard rule 6).
    """
    tenant_id, slug, token = await _make_tenant()
    _fake_provider(
        monkeypatch,
        content="Done.",
        arguments=json.dumps({"items": [{"field_id": "open", "value": "09:00"}]}),
        usage=chat.TokenUsage(prompt_tokens=10, output_tokens=10),
    )
    with caplog.at_level(logging.INFO, logger="apps.api.compliance.audit"):
        async with _client() as http:
            await _events(http, token, slug)

    assert await _audit(tenant_id) == [("copilot.ask", "screen", BODY["screen"]["route"])]

    entries = [r for r in caplog.records if r.getMessage() == "audit"]
    assert entries, "the audit write produced no log line"
    extras = {
        key: value
        for key, value in vars(entries[-1]).items()
        if key in {"provider", "metered", "filled_field_count", "realm", "ref"}
    }
    assert extras["provider"] == "azure"
    assert extras["metered"] is True
    assert extras["filled_field_count"] == 1
    blob = json.dumps({k: str(v) for k, v in vars(entries[-1]).items()})
    assert "09:00" not in blob
    assert BODY["question"] not in blob
    assert "Done." not in blob


async def test_a_number_reaches_the_browser_as_an_integer_and_a_bool_as_a_bool(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`CopilotValue`'s union order, asserted on the WIRE.

    FAILS IF: `int` leaves the union — a seat count of twelve then arrives as `12.0` and is
    written into a number input as "12.0" — or if `bool` moves ahead of the numerics, at
    which point a JSON `true` arrives as `1` and a checkbox is set from an integer.
    """
    _, slug, token = await _make_tenant()
    body = {
        **BODY,
        "fields": [
            {"id": "seats", "label": "Seats", "type": "number", "value": None, "writable": True},
            {"id": "sms", "label": "SMS", "type": "bool", "value": None, "writable": True},
        ],
    }
    _fake_provider(
        monkeypatch,
        content="",
        arguments=json.dumps(
            {
                "items": [
                    {"field_id": "seats", "value": 12},
                    {"field_id": "sms", "value": True},
                ]
            }
        ),
        usage=chat.TokenUsage(prompt_tokens=10, output_tokens=10),
    )
    async with _client() as http:
        events = await _events(http, token, slug, body)

    fill = next(data for name, data in events if name == "fill")
    assert fill == {
        "items": [{"field_id": "seats", "value": 12}, {"field_id": "sms", "value": True}]
    }


# --- 2. tenancy -------------------------------------------------------------------------


@pytest.mark.rls
async def test_one_tenants_copilot_spend_is_invisible_to_another(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hard rule 1: the ledger row is tenant-scoped and RLS is what isolates it, not a
    WHERE clause somebody might forget."""
    spender, spender_slug, spender_token = await _make_tenant()
    neighbour, _, _ = await _make_tenant()
    _fake_provider(monkeypatch, usage=chat.TokenUsage(prompt_tokens=10, output_tokens=10))

    async with _client() as http:
        await _events(http, spender_token, spender_slug)

    assert await _usage_rows(spender)
    assert await _usage_rows(neighbour) == []
    assert await _audit(neighbour) == []


async def test_the_route_is_refused_without_a_session() -> None:
    async with _client() as http:
        response = await http.post(ASK, json=BODY)
    assert response.status_code == 401


async def test_staff_may_open_the_assistant(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**THIS TEST USED TO ASSERT THE OPPOSITE, AND THE FOUNDER REVERSED IT:** staff must
    be able to use the assistant.

    It is re-pointed rather than deleted, because the question it asks — "which roles reach
    the thing that spends the allowance?" — is still exactly the right question and is now
    answered by `copilot:use` instead of `org:manage`. Read the old name before reading
    this as a relaxation: `org:manage` was never picked because opening a chat panel is an
    owner's business, it was picked because this route SPENDS and therefore needed a
    MUTATING permission, and it dragged billing, members and every org setting along.
    `copilot:use` is in `MUTATING_PERMISSIONS` too, so the property that mattered is intact
    and is pinned one test down.
    """
    _, slug, token = await _make_tenant(role="staff")
    reached = _fake_provider(monkeypatch)

    async with _client() as http:
        response = await http.post(ASK, headers=_headers(token, slug), json=BODY)

    assert response.status_code == 200, response.text
    assert reached, "a staff member's question must actually reach the provider"


async def test_the_assistant_still_costs_a_mutating_permission(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE PROPERTY THAT HAD TO SURVIVE WIDENING THE POPULATION.

    A role holding none of the client permissions reaches nothing, and — the half that
    matters — `copilot:use` is in `MUTATING_PERMISSIONS`, so a D-22 read-only view-as
    session cannot burn a client's included allowance from the client's own screen. The
    view-as half is driven end to end by `realm_boundary_test::test_no_route_declaring_a_
    mutating_permission_is_reachable_while_impersonating`, which walks the live route table
    and therefore picked this route up automatically the moment its permission changed;
    what is asserted HERE is the registry fact that sweep depends on, because a future
    edit that quietly dropped `copilot:use` from the list would make that sweep stop
    covering this route rather than fail.
    """
    from apps.api.core.rbac import MUTATING_PERMISSIONS, role_has

    assert "copilot:use" in MUTATING_PERMISSIONS
    assert role_has("staff", "copilot:use") and role_has("owner", "copilot:use")
    assert not role_has("staff", "org:manage"), (
        "staff got the assistant, and must NOT have got billing, members and org settings with it"
    )

    _, slug, token = await _make_tenant(role="staff")
    reached = _fake_provider(monkeypatch)
    async with _client() as http:
        blocked = await http.put(
            "/v1/organization/llm-defaults",
            headers=_headers(token, slug),
            # READ, NOT SPELLED. The request body only has to be a well-formed one this
            # surface would accept — the assertion is the 403, not the model. A literal
            # here is a second spelling of the default that the live `gpt-4.1-mini`
            # switch would not reach, and `sarvam_model_identifier_test` refuses it.
            json={"default_llm_model": get_settings().azure_openai_model},
        )
    assert blocked.status_code == 403, (
        "an `org:manage` surface must still refuse the staff member who can now chat"
    )
    assert reached == []


# --- 3. the gate refuses before a token is spent -----------------------------------------


async def _at_the_ceiling(tenant_id: UUID, monkeypatch: pytest.MonkeyPatch) -> None:
    """Past the included allowance with NO usage rows. The tier constant goes to zero
    rather than the tenant being charged into the ceiling: writing hundreds of rupees of
    usage would move `platform_ai_spend`, the one counter this file shares with every other
    suite.

    **AND THE CLOCK IS PINNED, BECAUSE THIS TEST FAILED FOR ONE HOUR A MONTH AND NOBODY
    WOULD HAVE BELIEVED WHY.** `require_ai_assist` asks `month_is_ending` before it raises
    `ai_quota_exceeded`, and inside the last `LAST_SALEABLE_MINUTES` of an IST month it
    correctly raises `ai_extra_month_ending` instead — a different code, a different
    sentence, and a red suite for anyone who ran it after 23:00 IST on the last day
    (observed 31 Aug 2026, 17:38 UTC). That is right behaviour and the wrong dependency for
    a test about a ceiling: the assertion here is which refusal a tenant at its ceiling
    gets, not what time it is.

    Pinned FALSE, and pinned in the fixture rather than per test, so every ceiling test in
    this file asserts the same state whatever hour it runs in. The month-ending refusal has
    its own coverage in `tests/ai_quota_test.py`, which pins the boundary from both sides
    with an explicit `now=` — this is the same `patch.setattr(ai_quota, "month_is_ending",
    ...)` that file already uses, pointed the other way.
    """
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = 'self_serve' WHERE id = :i"),
            {"i": tenant_id},
        )
    monkeypatch.setitem(ai_quota.AI_QUOTA_INR, "self_serve", Decimal("0.00"))
    # AND THE CLOCK IS PINNED AWAY FROM THE MONTH BOUNDARY, which is not decoration.
    # `read_ai_quota` answers a tenant past its allowance with the MORE SPECIFIC refusal
    # when one applies, and in the last `LAST_SALEABLE_MINUTES` of an IST month that is
    # `ai_extra_month_ending` ("the allowance comes back within the hour") rather than
    # `ai_quota_exceeded`. Both are correct product behaviour and the specific one is the
    # better sentence — but a test about the CEILING must not be answered by the calendar.
    # Without this the file goes red for one hour every month, which reads to the next
    # person like a regression in whatever they happened to be holding. Found twice
    # independently on 31 Aug 2026 — once 51 minutes before the IST roll and once 50
    # minutes after — which is the whole argument for pinning it rather than re-running.
    # The lambda mirrors the real signature (`month_is_ending(month, *, now=None)`) so a
    # signature drift surfaces here instead of being swallowed by a permissive `*args`;
    # `tests/ai_quota_test.py` still covers the boundary itself with an explicit `now=`.
    monkeypatch.setattr(ai_quota, "month_is_ending", lambda month, **kwargs: False)


async def test_a_tenant_at_its_ceiling_is_refused_before_the_provider_is_reached(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G-4: a refused request costs nothing, which is the only reading under which a
    ceiling is a ceiling.

    THE PROVIDER LIST IS THE ASSERTION, not the empty ledger. A ledger assertion alone
    passes on a path that paid Microsoft and failed to record it.
    """
    tenant_id, slug, token = await _make_tenant()
    await _at_the_ceiling(tenant_id, monkeypatch)
    reached = _fake_provider(monkeypatch)

    async with _client() as http:
        events = await _events(http, token, slug)

    assert reached == []
    assert [name for name, _ in events] == ["error"]
    problem = events[0][1]
    assert problem["type"].endswith("/ai_quota_exceeded")
    # The screen switches on `code`; the body is the same problem+json shape the error
    # handler would have written on a non-streamed route (BACKEND-PATTERNS §3).
    assert problem["remediation"]
    assert await _usage_rows(tenant_id) == []


async def test_an_unredacted_payload_is_refused_before_the_gate_and_before_the_provider(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SUBJECT before GATE. A payload that still carries personal values cannot be sent at
    any price, and finding that out after the ceiling check would answer a client at their
    limit with "add ₹500" for a request the money would not have helped with."""
    tenant_id, slug, token = await _make_tenant()
    await _at_the_ceiling(tenant_id, monkeypatch)
    reached = _fake_provider(monkeypatch)
    body = {**BODY, "question": "call them back on 9876500123"}

    async with _client() as http:
        events = await _events(http, token, slug, body)

    assert reached == []
    assert [name for name, _ in events] == ["error"]
    # The SUBJECT refusal, not the ceiling one — which is what proves the order.
    assert events[0][1]["type"].endswith("/copilot_input_not_redacted")


# --- 4. what the model asked for is re-checked here --------------------------------------


async def test_a_tool_call_naming_a_non_writable_field_reaches_the_browser_as_no_fill(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end, over the wire: the refusal is not a `fill` event with the value in it.

    The loop spends its remaining turns asking the model to correct itself (proved in
    `loop_test.py`); here the script refuses every time, so what the browser sees is the
    exhaustion message and NO fill at all.
    """
    tenant_id, slug, token = await _make_tenant()
    _fake_provider(
        monkeypatch,
        content="",
        arguments=json.dumps({"items": [{"field_id": "status", "value": "live"}]}),
        usage=chat.TokenUsage(prompt_tokens=10, output_tokens=10),
    )
    async with _client() as http:
        events = await _events(http, token, slug)

    assert "fill" not in [name for name, _ in events]
    # THE FRAMES ARE JOINED, because what a person reads is the concatenation of the SSE
    # deltas and not any one of them. `service.run_copilot`'s identity egress guard
    # (`copilot/identity.py`) holds the sentence in flight, so the authored detail after
    # the full stop arrives as its own frame — the browser appends it either way.
    said = "".join(data["delta"] for name, data in events if name == "text")
    assert said.startswith(service.EXHAUSTED_MESSAGE)
    assert "`status` is not writable" in said
    # Still metered: every one of those turns was paid for.
    assert await _usage_rows(tenant_id)


async def test_a_select_value_outside_its_options_never_reaches_the_browser(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, slug, token = await _make_tenant()
    body = {
        **BODY,
        "fields": [
            {
                "id": "lang",
                "label": "Language",
                "type": "select",
                "value": None,
                "options": [{"value": "te-IN", "label": "Telugu"}],
                "writable": True,
            }
        ],
    }
    _fake_provider(
        monkeypatch,
        content="",
        arguments=json.dumps({"items": [{"field_id": "lang", "value": "hi-IN"}]}),
        usage=chat.TokenUsage(prompt_tokens=10, output_tokens=10),
    )
    async with _client() as http:
        events = await _events(http, token, slug, body)

    assert "fill" not in [name for name, _ in events]
    assert "hi-IN" not in json.dumps(events)


# --- 5. the money, when the provider does not count it -----------------------------------


async def test_an_answer_the_provider_did_not_count_is_unmetered_and_never_zero(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "We do not know what this cost" and "it was free" must not meter the same. No row is
    written, `metered` is False on the wire, and `meter_assist` fires
    `ai_assist_unmeterable` so an operator learns the meter stopped (D-140)."""
    tenant_id, slug, token = await _make_tenant()
    _fake_provider(monkeypatch, content="Nine.", usage=None)
    alerts: list[str] = []
    monkeypatch.setattr(
        "apps.api.crm.assist.alert",
        lambda category, name, **kwargs: alerts.append(name),
    )

    async with _client() as http:
        events = await _events(http, token, slug)

    assert events[-1] == ("done", {"disclosure": None, "metered": False})
    assert await _usage_rows(tenant_id) == []
    assert alerts == ["ai_assist_unmeterable"]


# --- 6. exactly ONE table is persisted to ---------------------------------------------------


async def test_the_conversation_lands_in_copilot_memories_and_nowhere_else(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**THIS TEST USED TO ASSERT THAT NOTHING WAS PERSISTED AT ALL, AND THAT INVARIANT IS
    GONE ON PURPOSE (migration d4a9c17e6b02).** Its ground was `crm/assist.py:10-31` —
    which declines to store transcript-derived prose so DPDP erasure and retention gain no
    new surface to enumerate. That was never a prohibition; it was a PRICE, and
    `copilot/memory.py` pays it: a FORCEd `tenant_isolation` policy, a `copilot_memory`
    retention category swept nightly, an unconditional DELETE in the tenant-erasure path,
    and `redact()` on every string before it reaches a column
    (`tests/copilot_memory_test.py`, `tests/copilot_memory_lifecycle_test.py`).

    What survives is the half that was doing the work, and it is now SHARPER rather than
    weaker: the copilot's content may land in `copilot_memories` and in NO OTHER TABLE.
    Scanned across every text-ish column in the schema rather than by naming the tables
    this feature was expected to leave alone — the latter cannot see a table that did not
    exist when the test was written, which is the whole reason the scan is written this
    way.

    FAILS IF: somebody writes the question into a second table, or into an existing one —
    each of which would be a surface the erasure arm and the retention clock do not cover.
    """
    tenant_id, slug, token = await _make_tenant()
    marker = f"marker-{uuid.uuid4().hex[:12]}"
    _fake_provider(
        monkeypatch,
        content=f"answer-{marker}",
        arguments=json.dumps({"items": [{"field_id": "open", "value": f"value-{marker}"}]}),
        usage=chat.TokenUsage(prompt_tokens=10, output_tokens=10),
    )
    body = {**BODY, "question": f"question-{marker}"}

    async with _client() as http:
        await _events(http, token, slug, body)

    async with tenant_session(tenant_id) as session:
        columns = (
            await session.execute(
                text(
                    "SELECT table_name, column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND data_type IN "
                    "('text', 'character varying', 'json', 'jsonb')"
                )
            )
        ).all()
        for table, column in columns:
            # THROUGH `_identifier()`, which is what `scripts/check_raw_sql` requires of an
            # interpolated identifier. The names come from `information_schema` rather than
            # from a caller, so this cannot fail in practice — and that is exactly why the
            # guard insists: "it comes from a trusted place" is the sentence every SQL
            # injection was written under.
            safe_table = _identifier(str(table), "table")
            safe_column = _identifier(str(column), "column")
            found = (
                await session.execute(
                    text(
                        f'SELECT count(*) FROM "{safe_table}" WHERE "{safe_column}"::text LIKE :m'
                    ),
                    {"m": f"%{marker}%"},
                )
            ).scalar()
            if (table, column) == ("copilot_memories", "content"):
                # THE ONE PLACE IT IS ALLOWED TO BE, and asserted POSITIVELY rather than
                # skipped: a `continue` here would also pass on the day the write silently
                # stopped happening, which is a memory feature that remembers nothing.
                assert found == 1, "the exchange must be remembered exactly once"
                continue
            assert found == 0, f"{table}.{column} kept copilot content"


# --- 6b. egress, proved on the BYTES ----------------------------------------------------
#
# `scripts/check_redaction_exposure` CANNOT SEE THIS SURFACE, and that is a property of the
# route rather than an omission: the guard walks the OpenAPI schema, and an SSE route
# declares no response model, so its `components.schemas` holds this feature's REQUEST
# models and none of its event payloads. A `KNOWN_SAFE_FIELDS` entry naming one would be
# refused by that file's own `check_registry_freshness` as an exemption for a field the
# schema does not have.
#
# The repo already has the answer for a surface in exactly this position — the CSV export's
# bytes, the D-23 webhook body, the Sheets row — and it is a RUNTIME egress test
# (`tests/crm_egress_redaction_test.py`; the guard's docstring says to treat the two as one
# guardrail). This is that test for the copilot: assert the property against the bytes that
# actually leave.


async def test_no_invisible_character_survives_into_the_bytes_that_leave(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OWASP GenAI LLM Top 10 2026 LLM01 #5, egress half, on the wire.

    The model emits a tag-block character in BOTH channels it controls — the prose and a
    field value. The browser highlights a preview of the value and then writes it, so a
    surviving invisible character makes the preview and the written value different strings
    and a person approves the one they can see.

    FAILS IF: the stripping moves to a place that covers only one of the two channels.
    """
    _, slug, token = await _make_tenant()
    tag = "\U000e0041"
    _fake_provider(
        monkeypatch,
        content=f"Nine{tag} in the morning.",
        arguments=json.dumps({"items": [{"field_id": "open", "value": f"09{tag}:00"}]}),
        usage=chat.TokenUsage(prompt_tokens=10, output_tokens=10),
    )

    async with (
        _client() as http,
        http.stream("POST", ASK, headers=_headers(token, slug), json=BODY) as response,
    ):
        raw = (await response.aread()).decode("utf-8")

    assert not has_invisible(raw), "an invisible character reached the browser"
    # And the surrounding text is still there, so "no invisible character" is not satisfied
    # by the answer being empty.
    assert "Nine in the morning." in raw
    assert "09:00" in raw


# --- 7. failures are events, not silence ---------------------------------------------------


async def test_a_provider_dying_mid_answer_ends_with_a_problem_body(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stream that simply stops is indistinguishable from a dropped connection, and a
    person cannot act on either. The authored refusal says nothing on their screen was
    changed, which is the fact they need."""
    _, slug, token = await _make_tenant()

    def _stream(*args: Any, **kwargs: Any) -> AsyncIterator[chat.StreamEvent]:
        async def _iterate() -> AsyncIterator[chat.StreamEvent]:
            yield chat.StreamEvent(text="Nine in the ")
            raise httpx.ReadError("cut")

        return _iterate()

    monkeypatch.setattr(chat, "stream", _stream)

    async with _client() as http:
        events = await _events(http, token, slug)

    assert [name for name, _ in events] == ["text", "error"]
    assert events[-1][1]["type"].endswith("/copilot_interrupted")
    assert events[-1][1]["remediation"]


async def test_a_body_the_contract_does_not_admit_is_a_422_and_not_a_stream(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Request validation happens BEFORE the generator, so it keeps a real status line. A
    caller who is not allowed in never reaches the stream at all."""
    _, slug, token = await _make_tenant()
    reached = _fake_provider(monkeypatch)

    async with _client() as http:
        response = await http.post(
            ASK,
            headers=_headers(token, slug),
            json={**BODY, "surprise": "an undeclared key"},
        )

    assert response.status_code == 422
    assert reached == []


async def test_an_operator_is_refused_at_the_door_before_any_of_this_runs(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WHERE THE ADMIN REALM IS ACTUALLY STOPPED — checked over HTTP because the route's own
    docstring made a claim about it and a claim is not a check (D-501).

    `NORMAL_ADMIN_ROLE` holds `copilot:use` deliberately (`core/rbac.py` argues it), so the
    permission list is NOT what refuses an operator. `current_any` is: it resolves the admin
    realm only when the impersonation header is present, so an operator's token is checked
    against the CLIENT realm and gets a 401 before the response generator starts. That is
    what makes `assert principal.tenant_id is not None` a statement rather than a branch.

    IT MATTERS NOW BECAUSE THE DOCK RENDERS ON EVERY ADMIN SCREEN (D-501), not only the
    declared ones, so more operators can press the launcher. The refusal must stay free —
    the provider is asserted unreached — and the console must not put a person in front of
    it at all, which `CopilotPanel` handles by not sending the request.

    FAILS IF: someone widens `current_any` or points this route at `realm="any"` with an
    admin fallback, which would put an operator's typing on a client's ledger or on none.
    """
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'operator', now(), now())"
            ),
            {"id": admin_id},
        )
    reached = _fake_provider(monkeypatch)

    async with _client() as http:
        response = await http.post(
            ASK,
            headers={"Authorization": f"Bearer dev:admin:{admin_id}"},
            json={
                "screen": {"route": "/admin/tenants", "title": "Tenants", "realm": "admin"},
                "question": "how many accounts are live?",
                "fields": [],
                "facts": [],
                "history": [],
            },
        )

    assert response.status_code == 401, response.text
    assert reached == [], "a refusal must cost nothing"


# ------------------------------------------------ spend that a failed run still owes for


async def test_a_provider_that_dies_after_spending_is_still_metered(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HARD RULE 7, ON THE PATH THAT USED TO DROP IT.

    A run that really did send tokens to Azure and then failed part-way is money paid to a
    provider. The route's `except` arm returned BEFORE the metering block, so that spend
    reached no `usage_events` row, moved no `ai_assist` quantity, and was invisible to both
    the account's rupee ceiling and the platform brake — a metering outage with no alert,
    because nothing knew there was anything to meter.

    `run_copilot` is replaced here rather than a provider being made to fail, and that is
    deliberate: what is under test is the ROUTE's contract with the run — "every spend you
    emit, I record, however you end" — and a test that reached for a real failure would be
    asserting `service.py`'s control flow from the wrong file.

    FAILS IF: the failure arm stops calling `_record`, or `_record` skips a run that did
    not complete.
    """
    tenant_id, slug, token = await _make_tenant()

    async def _dies(payload: Any, **kwargs: Any) -> AsyncIterator[service.CopilotEvent]:
        yield service.CopilotEvent(text="Looking...")
        yield service.CopilotEvent(
            spend=service.CopilotSpend(
                usage=chat.TokenUsage(prompt_tokens=1_000, output_tokens=500),
                capability=assist_capability(),
            )
        )
        raise RuntimeError("the provider hung up")

    monkeypatch.setattr(service, "run_copilot", _dies)
    async with _client() as http:
        frames = await _events(http, token, slug)

    assert [name for name, _ in frames] == ["text", "error"]
    rows = await _usage_rows(tenant_id)
    # THE TOKENS ARE ON THE LEDGER even though the person got an error instead of an answer.
    assert rows, "a failed run that spent tokens must still reach usage_events"
    assert sum(quantity for _unit, quantity, _price, _meta in rows) > 0
    # And exactly one `copilot.ask` row, so the ledger and the audit trail agree about how
    # many questions were asked.
    assert len(await _audit(tenant_id)) == 1


async def test_two_legs_in_one_run_are_two_ledger_entries_and_not_one(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A RUN CAN SPEND TWICE, AND THE ROUTE KEPT ONLY THE SECOND.

    `run_copilot` re-selects the capability with `provider_unavailable=True` when a leg
    fails before it streams anything, and finishes the answer on the disclosed Sarvam leg.
    The first leg's tokens were paid for regardless. A single `spend` slot overwrote them,
    so the fallback — the case where MORE was spent, not less — was the case that recorded
    least.

    Each spend gets its own `ref` because `record_ai_assist_usage`'s idempotency is keyed on
    it; sharing one would discard the second in the name of not double-charging the first.

    FAILS IF: the route goes back to a single spend, or reuses one ref across legs.
    """
    tenant_id, slug, token = await _make_tenant()

    async def _twice(payload: Any, **kwargs: Any) -> AsyncIterator[service.CopilotEvent]:
        yield service.CopilotEvent(
            spend=service.CopilotSpend(
                usage=chat.TokenUsage(prompt_tokens=1_000, output_tokens=500),
                capability=assist_capability(),
            )
        )
        yield service.CopilotEvent(text="Here is the answer.")
        yield service.CopilotEvent(
            spend=service.CopilotSpend(
                usage=chat.TokenUsage(prompt_tokens=2_000, output_tokens=100),
                capability=assist_capability(),
            )
        )

    monkeypatch.setattr(service, "run_copilot", _twice)
    async with _client() as http:
        frames = await _events(http, token, slug)

    assert [name for name, _ in frames] == ["text", "done"]
    async with tenant_session(tenant_id) as session:
        refs = (
            await session.execute(
                text(
                    "SELECT count(DISTINCT ref) FROM usage_events "
                    "WHERE tenant_id = :tid AND unit_type LIKE 'ai_assist%'"
                ),
                {"tid": tenant_id},
            )
        ).scalar_one()
    # TWO REFS: two legs, two records, one question.
    assert refs == 2
    assert len(await _audit(tenant_id)) == 1
