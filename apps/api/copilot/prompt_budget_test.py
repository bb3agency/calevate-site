"""What one Pip request carries, part by part, and which part a provider can cache (D-816).

Run with `-s` to print the breakdown. Sizes are the characters of the JSON the leg posts and
the tokens `own_model_prompt.prompt_tokens_of` estimates for them (four characters a token —
no tokenizer for either answering model is available offline, so the token column is an
ESTIMATE; production read 15,866 prompt tokens for one admin question on 18 Oct 2026). The
assertions are the properties the cost depends on: the system prompt and the tool array are
the same bytes on every request of a surface and come before everything per-request.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from apps.api.billing.own_model_prompt import prompt_tokens_of
from apps.api.copilot import admin_actions, admin_screens, write_tools
from apps.api.copilot import service as copilot_service
from apps.api.copilot.context import LiveAccount, LiveCounts, LiveState, Viewer, render_live
from apps.api.copilot.schemas import (
    CopilotAskIn,
    CopilotFact,
    CopilotRealm,
    CopilotScreen,
    CopilotTurn,
)

#: The largest cacheable prefix each surface may carry, in estimated tokens. A change that
#: grows one past its budget fails here and has to argue for the room. The client prefix is
#: the system prompt plus the area tools (D-893), every lane's actions included; the tool
#: array alone has its own budget below. The admin account surface offers the client's
#: reads as flat tools, so it carries the leads and calls lens (~520 tokens) on
#: `leads_search` and `calls_recent` and the D-893 lanes' reads in full, plus
#: `agent_known_facts` (D-896, ~100 tokens: measured 10,343 before, 10,449 with it), and the
#: leads lens's `campaign_id` (D-905, 15 tokens: 10,465).
PREFIX_BUDGET_TOKENS = {"client": 17_500, "admin_account": 10_475, "admin_console": 6_500}

#: The client tool array alone (PIP-AGENT-PLAN §2a): every read and action of every area.
TOOL_ARRAY_BUDGET_TOKENS = 12_000


def _compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _payload(*, question: str, route: str, realm: CopilotRealm, history: int = 0) -> CopilotAskIn:
    return CopilotAskIn(
        question=question,
        screen=CopilotScreen(route=route, title="Overview", realm=realm),
        facts=[CopilotFact(key="page", label="Page", value="Overview")],
        history=[
            CopilotTurn(role="user" if i % 2 == 0 else "assistant", content="x" * 400)
            for i in range(history)
        ],
    )


def _live(viewer: Viewer | None) -> str:
    return render_live(
        LiveState(
            now_ist=datetime(2026, 10, 18, 11, 30, tzinfo=UTC),
            counts=LiveCounts(
                calls_today=3,
                calls_last_7_days=40,
                leads_waiting={"hot": 1, "interested": 2, "new": 4},
                campaigns={"running": 1, "paused": 0, "scheduled": 0, "draft": 1},
                leads_total=120,
                leads_last_7_days=9,
                agents={"live": 1, "paused": 0, "draft": 1},
            ),
            blocker_rules=(),
            viewer=viewer,
            account=LiveAccount(
                lifecycle="active",
                kyc="verified",
                kyc_path="manual",
                pledge="accepted",
                trial="converted",
                paid=True,
                workspace="active",
                owner_joined=True,
                profile_missing=(),
            ),
        )
    )


def _admin_tools_before() -> list[dict[str, Any]]:
    """The admin array as composed at bdc20490: every read tool, every client write tool."""
    return [
        copilot_service.tool_array("admin")[0],
        *[copilot_service._read_schema(tool) for tool in copilot_service.realm_read_tools("admin")],
        *write_tools.write_tool_schemas(),
        *admin_actions.admin_action_schemas(),
        admin_screens.admin_open_screen_tool(),
    ]


def _surfaces() -> dict[str, tuple[CopilotRealm, list[dict[str, Any]], str]]:
    owner = _live(Viewer(role="owner", on_screen="Overview", closed=()))
    return {
        "client": ("client", copilot_service.tool_array("client"), owner),
        "admin_account": ("admin", copilot_service.tool_array("admin"), _live(None)),
        "admin_console": ("admin", copilot_service.tool_array("admin", account_open=False), ""),
        "admin_before (bdc20490)": ("admin", _admin_tools_before(), ""),
    }


def _parts(realm: CopilotRealm, tools: list[dict[str, Any]], live: str) -> list[tuple[str, str]]:
    payload = _payload(question="How many leads came in this week?", route="/c/x", realm=realm)
    messages = copilot_service.build_messages(payload, live, realm)
    return [
        ("system prompt", _compact(messages[0])),
        *[(f"tool {tool['function']['name']}", _compact(tool)) for tool in tools],
        ("user message (screen, live, rules, question)", _compact(messages[-1])),
    ]


def _prefix_tokens(realm: CopilotRealm, tools: list[dict[str, Any]]) -> int:
    payload = _payload(question="q", route="/", realm=realm)
    system = _compact(copilot_service.build_messages(payload, "", realm)[0])
    return prompt_tokens_of(system + _compact(tools))


def test_print_the_request_breakdown_for_each_surface() -> None:
    for name, (realm, tools, live) in _surfaces().items():
        parts = _parts(realm, tools, live)
        chars = sum(len(text) for _, text in parts)
        tokens = sum(prompt_tokens_of(text) for _, text in parts)
        tool_tokens = sum(prompt_tokens_of(text) for label, text in parts if label[:5] == "tool ")
        print(
            f"\n== {name}: {len(tools)} tools, {chars:,} chars, ~{tokens:,} tokens "
            f"(tools ~{tool_tokens:,}, cacheable prefix ~{_prefix_tokens(realm, tools):,})"
        )
        for label, text in sorted(parts, key=lambda part: -len(part[1]))[:8]:
            print(f"  {len(text):>7,}  ~{prompt_tokens_of(text):>6,}  {label}")


def test_every_surface_prefix_is_inside_its_budget() -> None:
    for name, budget in PREFIX_BUDGET_TOKENS.items():
        realm, tools, _live_block = _surfaces()[name]
        assert _prefix_tokens(realm, tools) <= budget, name


def test_the_client_tool_array_is_inside_its_budget() -> None:
    assert prompt_tokens_of(_compact(copilot_service.tool_array("client"))) <= (
        TOOL_ARRAY_BUDGET_TOKENS
    )


def test_the_prefix_is_identical_across_users_tenants_times_and_screens() -> None:
    """System prompt and tool array are the same bytes whoever asks, wherever and whenever;
    everything per-request lands after them, in the last message."""
    for realm in ("client", "admin"):
        first = _payload(question="How many leads?", route="/c/acme/overview", realm=realm)
        second = _payload(
            question="Pause my campaign", route="/c/zeta/campaigns", realm=realm, history=4
        )
        owner = _live(Viewer(role="owner", on_screen="Overview", closed=()))
        staff = _live(Viewer(role="staff", on_screen="Campaigns", closed=("Invoices",)))
        a = copilot_service.build_messages(first, owner, realm)
        b = copilot_service.build_messages(second, staff, realm)
        assert a[0] == b[0]
        assert a[0]["role"] == "system"
        for per_request in ("acme", "zeta", "Pause my campaign"):
            assert per_request not in a[0]["content"]
        assert "acme" in a[-1]["content"] and "zeta" in b[-1]["content"]
