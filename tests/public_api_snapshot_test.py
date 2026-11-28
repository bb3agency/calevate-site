"""The public API snapshot gate (D-1047): additions pass, anything breaking is refused."""

from __future__ import annotations

import copy
from typing import Any

from scripts import check_public_api_snapshot as gate


def _doc() -> dict[str, Any]:
    return {
        "paths": {
            "/api/v1/leads": {
                "post": {
                    "x-calevate-permission": "leads:dispatch",
                    "parameters": [],
                    "requestBody": {"$ref": "#/components/schemas/In"},
                    "responses": {"202": {}},
                }
            }
        },
        "components": {
            "schemas": {
                "In": {"properties": {"phone": {"type": "string"}}, "required": ["phone"]},
                "Out": {
                    "properties": {"status": {"enum": ["accepted"], "type": "string"}},
                    "required": ["status"],
                },
            }
        },
        "x-request-schemas": ["In"],
    }


def test_an_addition_is_not_breaking() -> None:
    new = copy.deepcopy(_doc())
    new["components"]["schemas"]["Out"]["properties"]["lead_id"] = {"type": "string"}
    new["components"]["schemas"]["Out"]["properties"]["status"]["enum"].append("duplicate")
    new["paths"]["/api/v1/me"] = {"get": {"responses": {"200": {}}}}
    assert gate.breaking_changes(_doc(), new) == []


def test_a_removal_a_retype_and_a_new_required_request_field_are_breaking() -> None:
    new = copy.deepcopy(_doc())
    del new["components"]["schemas"]["Out"]["properties"]["status"]
    new["components"]["schemas"]["In"]["properties"]["phone"] = {"type": "integer"}
    new["components"]["schemas"]["In"]["required"].append("name")
    new["paths"]["/api/v1/leads"]["post"]["x-calevate-permission"] = "leads:write"
    problems = gate.breaking_changes(_doc(), new)
    assert any("Out.status: removed" in p for p in problems)
    assert any("In.phone: changed type" in p for p in problems)
    assert any("In.name: request field became required" in p for p in problems)
    assert any("permission changed" in p for p in problems)


def test_the_committed_snapshot_is_the_live_surface() -> None:
    assert gate.main([]) == 0
