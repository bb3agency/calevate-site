"""THE SSE CONTRACT, PINNED — because the OpenAPI snapshot cannot pin it.

**THE GAP THIS FILE FILLS.** Every other route in this API publishes its response model:
`scripts/check_openapi_fresh.py` regenerates `apps/web/src/lib/api/openapi.json`, compares
each property's type signature, and fails the build when a field changes type or name
without the frontend being regenerated. `POST /v1/copilot/ask` publishes NOTHING — it
answers with `fastapi.sse.EventSourceResponse`, whose only declared 200 body is the generic
SSE frame (`{event, data: string, id, retry}`) — so the seven payload shapes the browser
parses out of `data:` are written down twice, once in `copilot/schemas.py` and once by hand
in `apps/web/src/lib/copilot/stream.ts`, with nothing comparing them. A renamed field is
then a silent `undefined` in somebody's panel.

So this file is the guard, and it is deliberately a LITERAL: the expected shapes below are
typed out rather than derived from the same models they check, because a test that read the
models back would agree with any change they made. Changing a frame therefore has to change
this file, and the diff is the notice the browser half needs.

**WHAT THE BROWSER MUST MATCH.** The `event:` name selects the payload; `STREAM_FRAMES` is
that mapping. `event: error` is the only frame not declared here: its payload is the
platform's RFC-9457 `problem+json` body, which every non-streamed refusal in this API
already uses.
"""

from __future__ import annotations

import json
from typing import Any

from apps.api.copilot.schemas import MAX_HISTORY, STREAM_FRAMES, CopilotAskIn
from apps.api.core.ratelimit import profile_for
from apps.api.core.rbac import IMPERSONATION_PERMITTED_MUTATIONS, MUTATING_PERMISSIONS
from apps.api.main import app

#: Every frame, by `event:` name, as `{field: type signature}` plus the fields that are
#: always present. Hand-written. See the module docstring for why.
EXPECTED: dict[str, dict[str, Any]] = {
    "text": {
        "fields": {"delta": '{"type": "string"}'},
        "required": ["delta"],
    },
    "fill": {
        "fields": {"items": '{"items": {"$ref": "#/$defs/CopilotFillItem"}, "type": "array"}'},
        "required": ["items"],
    },
    "proposal": {
        "fields": {
            "token": '{"type": "string"}',
            "tool": '{"type": "string"}',
            "title": '{"type": "string"}',
            "summary": '{"type": "string"}',
            "object_type": '{"type": "string"}',
            "object_id": '{"type": "string"}',
            "current": '{"anyOf": [{"type": "string"}, {"type": "null"}]}',
            "proposed": '{"type": "string"}',
            "cost": '{"anyOf": [{"type": "string"}, {"type": "null"}]}',
            "reversal": '{"type": "string"}',
            "expires_at": '{"format": "date-time", "type": "string"}',
        },
        "required": [
            "cost",
            "current",
            "expires_at",
            "object_id",
            "object_type",
            "proposed",
            "reversal",
            "summary",
            "title",
            "token",
            "tool",
        ],
    },
    "action": {
        "fields": {
            "tool": '{"type": "string"}',
            "title": '{"type": "string"}',
            "detail": '{"type": "string"}',
            "object_type": '{"type": "string"}',
            "object_id": '{"type": "string"}',
            "applied": '{"type": "boolean"}',
            "reversal": '{"type": "string"}',
            "where": '{"type": "string"}',
        },
        "required": [
            "applied",
            "detail",
            "object_id",
            "object_type",
            "reversal",
            "title",
            "tool",
            "where",
        ],
    },
    "navigate": {
        "fields": {
            "tool": '{"type": "string"}',
            "screen": '{"type": "string"}',
            "route": '{"type": "string"}',
            "where": '{"type": "string"}',
            "detail": '{"type": "string"}',
            "reversal": '{"type": "string"}',
        },
        "required": ["detail", "reversal", "route", "screen", "tool", "where"],
    },
    "step": {
        "fields": {
            "id": '{"type": "string"}',
            "tool": '{"type": "string"}',
            "status": '{"enum": ["running", "done", "refused", "failed"], "type": "string"}',
            "args": '{"type": "string"}',
            "detail": '{"anyOf": [{"type": "string"}, {"type": "null"}]}',
            # `None` while the step is running AND when nothing was timed at all — a
            # refusal that ran nothing reports no duration rather than "0 ms".
            "elapsed_ms": '{"anyOf": [{"type": "integer"}, {"type": "null"}]}',
        },
        "required": ["args", "id", "status", "tool"],
    },
    "done": {
        "fields": {
            "disclosure": '{"anyOf": [{"type": "string"}, {"type": "null"}]}',
            "metered": '{"type": "boolean"}',
        },
        # BOTH OPTIONAL ON THE WIRE, and the browser must default them rather than assume:
        # a missing `disclosure` means "no substitution occurred", never "unknown".
        "required": [],
    },
}

#: The keys of a JSON-Schema property that decide what the TypeScript has to be. The rest
#: (title, description, default) churn and break nothing — the same split
#: `scripts/check_openapi_fresh.py` makes for every published model.
_SIGNIFICANT = ("type", "format", "enum", "$ref", "anyOf", "items")


def _signature(model: Any) -> dict[str, str]:
    schema = model.model_json_schema()
    return {
        name: json.dumps(
            {key: value for key, value in prop.items() if key in _SIGNIFICANT}, sort_keys=True
        )
        for name, prop in schema["properties"].items()
    }


def test_the_seven_frame_names_are_the_ones_the_route_documents() -> None:
    """The `event:` names are half the contract, and the description is where the browser
    author reads them. A frame added to `STREAM_FRAMES` and not to the description is one
    nobody is told about; one in the description with no model is one nobody can parse."""
    described = app.openapi()["paths"]["/v1/copilot/ask"]["post"]["description"]
    for name in STREAM_FRAMES:
        assert f"event: {name}" in described, f"the `{name}` frame is undocumented"
    assert set(STREAM_FRAMES) == set(EXPECTED)
    # The refusal frame is documented and deliberately has no model here — its payload is
    # the platform's problem+json body.
    assert "event: error" in described


def test_every_frame_payload_is_the_shape_the_browser_parses() -> None:
    """FAILS IF: any of the seven payload models changes a field name, a type, an enum or
    whether a field is always present.

    That is the point. `EventSourceResponse` publishes no response schema, so
    `pnpm gen:api` emits none of these and `check_openapi_fresh` compares none of them —
    this assertion is the ONLY thing between a renamed field and a browser panel that
    renders `undefined`. When it fails, the fix is to change BOTH sides in one change:
    this file and `apps/web/src/lib/copilot/stream.ts`.
    """
    for name, model in STREAM_FRAMES.items():
        expected = EXPECTED[name]
        assert _signature(model) == expected["fields"], f"the `{name}` frame changed shape"
        required = sorted(model.model_json_schema().get("required", []))
        assert required == expected["required"], f"the `{name}` frame changed what is optional"


def test_no_frame_tolerates_a_field_the_browser_does_not_know_about() -> None:
    """`extra="forbid"` on every frame is what makes the pin above total: without it a new
    field could be added to a payload without touching the model's declared properties."""
    for name, model in STREAM_FRAMES.items():
        assert model.model_config.get("extra") == "forbid", f"the `{name}` frame is open"


def test_the_history_ceiling_is_published_so_the_browser_need_not_retype_it() -> None:
    """`MAX_HISTORY` is a number the browser also holds — it trims the replayed turns before
    posting them — and a browser that trims to MORE than the server accepts turns a
    conversation into a 422 at the length nobody tests.

    It IS in the schema (`maxItems` on `CopilotAskIn.history`), which is where the frontend
    must read it from rather than retyping the literal. Pinned here because
    `check_openapi_fresh` deliberately IGNORES validation bounds: `maxItems` moving from 10
    to 6 produces byte-identical TypeScript and no snapshot diff at all, so nothing else in
    CI can see this change.
    """
    published = CopilotAskIn.model_json_schema()["properties"]["history"]
    assert published["maxItems"] == MAX_HISTORY
    assert (
        app.openapi()["components"]["schemas"]["CopilotAskIn"]["properties"]["history"]["maxItems"]
        == MAX_HISTORY
    )


def test_an_operator_can_never_spend_a_clients_ai_allowance() -> None:
    """**THE D-22 ANSWER, ASSERTED WHERE THE COPILOT LIVES.**

    Asking the client assistant is metered against the ACCOUNT's allowance
    (`billing/ai_quota`), so it is a mutation of that account's balance however read-only an
    answer looks. `copilot:use` is therefore in `MUTATING_PERMISSIONS` and NOT in
    `IMPERSONATION_PERMITTED_MUTATIONS`, which means `core/auth.requires` refuses
    `POST /v1/copilot/ask` and `POST /v1/copilot/confirm` outright inside a view-as session
    — the request never reaches the meter at all, rather than being re-pointed at the
    platform's ledger.

    The ADMIN assistant is the exemption, and it is the opposite case: `copilot:admin` IS in
    `IMPERSONATION_PERMITTED_MUTATIONS` precisely because its spend can only ever land on
    the PLATFORM's ledger (`billing/platform_ai`), so there is no client balance for a view-as
    session to move.
    """
    assert "copilot:use" in MUTATING_PERMISSIONS
    assert "copilot:use" not in IMPERSONATION_PERMITTED_MUTATIONS
    assert "copilot:admin" in IMPERSONATION_PERMITTED_MUTATIONS


def test_both_assistant_routes_are_cost_weighted() -> None:
    """A CLICK ON EITHER PANEL IS UP TO `MAX_TURNS` MODEL CALLS, so neither may sit on a
    general API rate limit.

    `/v1/copilot/ask` always was `costly`; `/v1/admin/copilot/ask` fell through to the
    `/v1/admin/**` family, and it is the one that spends the PLATFORM's money
    (`billing/platform_ai`) — the stronger claim on a weight, and the one that lacked it.
    Asserted from the copilot's own suite because it is a fact about these two routes, not
    about the limiter.
    """
    assert profile_for("/v1/copilot/ask", "POST") is profile_for("/v1/admin/copilot/ask", "POST")
    assert profile_for("/v1/admin/copilot/ask", "POST").name == "costly"
