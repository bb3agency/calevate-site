"""Server-side re-validation of every tool call. THE security argument of this feature.

OWASP GenAI LLM Top 10 2026 LLM01 #4: hold state-change capability in application code,
not in the model. The vendor says the same thing about the payload itself — "the model
does not always generate valid JSON, and may hallucinate parameters not defined by your
function schema. Validate the arguments in your code before calling your function"
(openai/openai-openapi `openapi.yaml` @ master, `ChatCompletionMessageToolCallChunk`, read
27 Aug 2026).

Every test here drives `validate_fill` DIRECTLY rather than through a fake model, because
the property is "this function refuses X" and a fake model that never emits X would make
every one of them pass for the wrong reason.
"""

from __future__ import annotations

import json

import pytest

from apps.api.copilot.schemas import CopilotAskIn, CopilotFillItem
from apps.api.copilot.service import FillRefusedError, validate_fill

PAYLOAD = CopilotAskIn.model_validate(
    {
        "screen": {"route": "/c/x/agents/new", "title": "Build", "realm": "client"},
        "question": "fill it in",
        "fields": [
            {"id": "open", "label": "Opens", "type": "text", "writable": True},
            {"id": "seats", "label": "Seats", "type": "number", "writable": True},
            {"id": "sms", "label": "Send SMS", "type": "bool", "writable": True},
            {
                "id": "lang",
                "label": "Language",
                "type": "select",
                "writable": True,
                "options": [{"value": "te-IN", "label": "Telugu"}],
            },
            {"id": "empty-select", "label": "Voice", "type": "select", "writable": True},
            {"id": "status", "label": "Status", "type": "text", "writable": False},
        ],
    }
)


def _call(*items: dict[str, object]) -> str:
    return json.dumps({"items": list(items)})


def _reasons(arguments: str) -> tuple[str, ...]:
    with pytest.raises(FillRefusedError) as raised:
        validate_fill(PAYLOAD, arguments)
    return raised.value.reasons


# --- the happy path -------------------------------------------------------------------


def test_a_legal_fill_comes_back_as_typed_items() -> None:
    items = validate_fill(
        PAYLOAD,
        _call(
            {"field_id": "open", "value": "09:00"},
            {"field_id": "seats", "value": 12},
            {"field_id": "sms", "value": True},
            {"field_id": "lang", "value": "te-IN"},
        ),
    )
    assert items == (
        CopilotFillItem(field_id="open", value="09:00"),
        CopilotFillItem(field_id="seats", value=12),
        CopilotFillItem(field_id="sms", value=True),
        CopilotFillItem(field_id="lang", value="te-IN"),
    )


def test_null_clears_a_field_of_any_type() -> None:
    """ "The caller never said" has to be expressible. A copilot that could set a field but
    never unset one leaves a person with a wrong value and no way to ask for its removal."""
    items = validate_fill(PAYLOAD, _call({"field_id": "sms", "value": None}))
    assert items == (CopilotFillItem(field_id="sms", value=None),)


# --- the refusals ---------------------------------------------------------------------


def test_a_field_the_request_did_not_mark_writable_is_refused() -> None:
    """The model's claim about what is writable is worthless. `status` is on the screen and
    is read-only, which is the commonest shape of this mistake."""
    assert _reasons(_call({"field_id": "status", "value": "live"})) == ("`status` is not writable",)


def test_a_field_that_is_not_on_this_screen_at_all_is_refused() -> None:
    """A hallucinated id, or one from a different screen the model saw in `history`."""
    assert _reasons(_call({"field_id": "agents.status", "value": "live"})) == (
        "`agents.status` is not a field on this screen",
    )


def test_a_select_value_outside_its_declared_options_is_refused() -> None:
    assert _reasons(_call({"field_id": "lang", "value": "hi-IN"})) == (
        "`lang` is not one of that dropdown's options",
    )


def test_a_select_with_no_options_declared_refuses_every_value() -> None:
    """No value this server can PROVE is legal. Passing the model's word through would be
    exactly the trust LLM01 #4 says not to place in it, and the browser can fix it by
    declaring the options."""
    assert _reasons(_call({"field_id": "empty-select", "value": "anything"})) == (
        "`empty-select` is a dropdown with no options declared, so no value can be checked",
    )


def test_a_bool_field_refuses_the_string_true() -> None:
    """A model that has been told "true or false" will sometimes send `"true"`, and a form
    that writes the string into a checkbox is a form that saves the wrong thing."""
    assert _reasons(_call({"field_id": "sms", "value": "true"})) == ("`sms` expects true or false",)


def test_a_number_field_refuses_a_bool_because_python_says_true_is_one() -> None:
    """`isinstance(True, int)` is True. Without the explicit bool arm above the numeric
    check, `True` would be written into a seat count as 1."""
    assert _reasons(_call({"field_id": "seats", "value": True})) == (
        "`seats` expects a value, not true/false",
    )


def test_a_number_field_refuses_text_and_a_text_field_refuses_a_number() -> None:
    assert _reasons(_call({"field_id": "seats", "value": "twelve"})) == (
        "`seats` expects a number",
    )
    assert _reasons(_call({"field_id": "open", "value": 9})) == ("`open` expects text",)


def test_the_same_field_set_twice_in_one_call_is_refused() -> None:
    """The second silently wins, and which one that is depends on iteration order. There is
    no correct answer and a person cannot see the collision."""
    assert _reasons(
        _call({"field_id": "open", "value": "09:00"}, {"field_id": "open", "value": "10:00"})
    ) == ("`open` was set twice in one call",)


# --- all-or-nothing --------------------------------------------------------------------


def test_one_bad_item_refuses_the_whole_fill_and_every_reason_is_named() -> None:
    """A partial apply gives the person a form in a state neither they nor the copilot
    described, and one Undo that only undoes part of it.

    FAILS IF: somebody makes this best-effort. Both reasons are asserted, because a
    refusal that stops at the first one cannot be acted on in one more turn — and one more
    turn is exactly what `MAX_TURNS` budgets for.
    """
    assert _reasons(
        _call(
            {"field_id": "open", "value": "09:00"},
            {"field_id": "status", "value": "live"},
            {"field_id": "lang", "value": "hi-IN"},
        )
    ) == (
        "`status` is not writable",
        "`lang` is not one of that dropdown's options",
    )


def test_no_reason_ever_contains_the_value_that_was_refused() -> None:
    """A reason string reaches a log line and a person's screen. A value may be the very
    thing `sanitize` exists to keep off both (hard rule 6)."""
    for reason in _reasons(_call({"field_id": "status", "value": "9876500123"})):
        assert "9876500123" not in reason


# --- malformed arguments ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("arguments", "reason"),
    [
        ("not json at all", "the tool call was not valid JSON"),
        ("", "the tool call was not valid JSON"),
        ("[1, 2]", "the tool call was not an object"),
        ('{"item": []}', "`items` was missing or was not an array"),
        ('{"items": {}}', "`items` was missing or was not an array"),
        ('{"items": []}', "`items` was empty — nothing to fill"),
    ],
)
def test_a_malformed_tool_call_is_a_named_refusal_and_never_an_exception(
    arguments: str, reason: str
) -> None:
    """The vendor's own warning is that the model does not always generate valid JSON. A
    `json.JSONDecodeError` escaping into a streaming route would end the stream with no
    message at all."""
    assert _reasons(arguments) == (reason,)


def test_an_item_that_is_not_an_object_or_names_no_field_is_refused() -> None:
    assert _reasons(_call({"value": "09:00"})) == ("one item named no field",)
    assert _reasons(json.dumps({"items": ["open"]})) == ("one item was not an object",)
