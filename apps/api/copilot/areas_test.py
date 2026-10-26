"""The client realm's area tools (D-893 F1): every registered tool has an area, an area call
resolves to exactly the registry call it names, and a wrong one is refused with the shape
the model should have used."""

from __future__ import annotations

import dataclasses
import json
from typing import Any

import pytest

from apps.api.copilot import areas, write_tools
from apps.api.copilot import service as copilot_service
from apps.api.copilot.step_labels import STEP_LABELS
from apps.workers import chat


def _call(name: str, body: Any, call_id: str = "c1") -> chat.ToolCall:
    return chat.ToolCall(id=call_id, name=name, arguments=json.dumps(body))


def test_every_registered_tool_has_an_area() -> None:
    registered = [tool.name for tool in copilot_service.realm_read_tools("client")] + [
        tool.name for tool in write_tools.WRITE_TOOLS
    ]
    assert sorted(set(registered) - set(areas.AREA_OF)) == []
    assert sorted(set(areas.AREA_OF) - set(registered)) == []


def test_a_tool_without_an_area_refuses_to_build() -> None:
    reads = copilot_service.realm_read_tools("client")
    stray = write_tools.WRITE_TOOLS[0]
    renamed = dataclasses.replace(stray, name="x_y")
    with pytest.raises(ValueError, match="no area for x_y"):
        areas.build_surface(reads, (*write_tools.WRITE_TOOLS, renamed))


def test_reads_are_finds_and_actions_are_dos_with_the_tier_marked() -> None:
    surface = copilot_service.area_surface()
    for wire, acts in surface.actions.items():
        for name, action in acts.items():
            assert wire.endswith(areas.FIND if action.kind == "find" else areas.DO), name
            tier = write_tools.tier_of(name)
            assert action.marker == (
                "read" if tier is None else {"immediate": "now"}.get(tier, "confirm")
            )
    description = next(
        tool["function"]["description"]
        for tool in surface.tools
        if tool["function"]["name"] == "leads_do"
    )
    assert "- lead_set_status(lead_id, status) now:" in description
    assert "- dnc_add(lead_id, reason) confirm:" in description


def test_an_area_call_resolves_to_the_registry_call_and_keeps_the_wire_call() -> None:
    surface = copilot_service.area_surface()
    wire = _call(
        "leads_do",
        {"action": "lead_set_status", "args": {"lead_id": "L1", "status": "hot"}},
    )
    resolved = surface.resolve(wire)
    assert resolved.name == "lead_set_status"
    assert json.loads(resolved.arguments) == {"lead_id": "L1", "status": "hot"}
    assert resolved.wire is wire
    assert resolved.id == wire.id
    # History replays what the model sent, never the registry name it was not offered.
    assert chat.replayed_tool_call(resolved)["function"]["name"] == "leads_do"


def test_an_omitted_nullable_argument_is_sent_as_null() -> None:
    resolved = copilot_service.area_surface().resolve(
        _call("leads_find", {"action": "leads_search", "args": {}})
    )
    assert json.loads(resolved.arguments) == {"status": None, "search": None, "limit": None}


def test_a_non_area_call_passes_through_unchanged() -> None:
    call = _call("set_fields", {"because": "x", "items": []})
    assert copilot_service.area_surface().resolve(call) is call


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"action": "nope", "args": {}}, "has no action of that name; its actions are: "),
        ({"action": "lead_set_status", "args": {"lead_id": "L1"}}, "`status` is required"),
        (
            {"action": "lead_set_status", "args": {"lead_id": "L1", "status": "warm"}},
            "`status` must be one of: new, contacted",
        ),
        (
            {"action": "lead_set_status", "args": {"lead_id": 4, "status": "hot"}},
            "`lead_id` should be a string",
        ),
        (
            {"action": "lead_set_status", "args": {"lead_id": "L1", "status": "hot", "x": 1}},
            "`x` is not an argument",
        ),
        ({"action": "lead_set_status", "args": []}, "must be an object"),
        ([1], "was not an object"),
    ],
)
def test_a_wrong_call_is_refused_with_how_to_fix_it(body: Any, expected: str) -> None:
    with pytest.raises(areas.AreaCallError) as refused:
        copilot_service.area_surface().resolve(_call("leads_do", body))
    assert expected in refused.value.reason


def test_an_argument_refusal_carries_the_actions_full_schema() -> None:
    with pytest.raises(areas.AreaCallError) as refused:
        copilot_service.area_surface().resolve(
            _call("leads_do", {"action": "dnc_add", "args": {"lead_id": "L1"}})
        )
    schema = write_tools.tool_named("dnc_add").schema["function"]["parameters"]  # type: ignore[union-attr]
    assert json.dumps(schema, separators=(",", ":"), ensure_ascii=False) in refused.value.reason


def test_invalid_json_is_refused() -> None:
    bad = chat.ToolCall(id="c1", name="calls_find", arguments="{nope")
    with pytest.raises(areas.AreaCallError, match="not valid JSON"):
        copilot_service.area_surface().resolve(bad)


def test_the_area_tools_are_the_same_bytes_every_time() -> None:
    first = json.dumps(copilot_service.tool_array("client"))
    copilot_service.area_surface.cache_clear()
    assert json.dumps(copilot_service.tool_array("client")) == first


def test_every_area_tool_and_action_has_panel_words() -> None:
    surface = copilot_service.area_surface()
    names = set(surface.actions) | {n for acts in surface.actions.values() for n in acts}
    assert sorted(names - set(STEP_LABELS)) == []


def test_the_dispatch_refuses_the_first_misnamed_call_and_passes_the_admin_realm() -> None:
    good = _call("calls_find", {"action": "calls_live", "args": {}}, "a")
    bad = _call("calls_find", {"action": "x", "args": {}}, "b")
    resolved, misnamed = copilot_service._dispatch_calls("client", [good, bad])
    assert [call.name for call in resolved] == ["calls_live"]
    assert misnamed is not None and misnamed[0] is bad
    same, none = copilot_service._dispatch_calls("admin", [bad])
    assert same == [bad] and none is None


def test_args_is_not_strict_because_its_shape_follows_the_action() -> None:
    for tool in copilot_service.area_surface().tools:
        assert tool["function"]["strict"] is False
        assert tool["function"]["parameters"]["required"] == ["action", "args"]
