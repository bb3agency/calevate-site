"""The business types live in one data file, and every reader takes them from it.

`calevate_shared/verticals.json` is the list; the admin and signup validation, the type
suggestion, the starting lead fields, the ready-made agents' words, the cross-call memory
refusal and `GET /v1/public/business-types` (which the web pickers read) all go through
`calevate_shared.verticals`.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest
from apps.api.agents import starters
from apps.api.compliance import caller_memory
from apps.api.main import app
from apps.api.tenancy.signup_routes import (
    BUSINESS_TYPES_CACHE_CONTROL,
    BusinessTypeExamplesOut,
    BusinessTypeOptionOut,
)
from apps.workers import business_type as suggest
from calevate_shared import verticals
from httpx import ASGITransport, AsyncClient
from pydantic import TypeAdapter, ValidationError
from scripts.check_public_routes import UNAUTHENTICATED_ROUTES

ROOT = Path(__file__).resolve().parent.parent


def test_custom_is_the_fallback_and_no_type_is_first_by_default() -> None:
    assert verticals.CUSTOM in verticals.all_keys()
    assert verticals.all_keys()[0] != "clinic"
    assert verticals.of(None).key == verticals.CUSTOM
    assert verticals.of("a-type-nobody-wrote").key == verticals.CUSTOM
    assert starters.vertical_of("a-type-nobody-wrote") == verticals.CUSTOM


def test_every_reader_takes_the_one_list() -> None:
    assert list(starters.TRADES) == list(verticals.all_keys())
    assert verticals.health_keys() == caller_memory.SPDI_REFUSED_VERTICALS
    assert "clinic" in caller_memory.SPDI_REFUSED_VERTICALS
    schema: dict = suggest._SUGGEST_SCHEMA["json_schema"]  # type: ignore[assignment]
    assert schema["schema"]["properties"]["business_type"]["enum"] == list(verticals.all_keys())
    for key, label in verticals.labels().items():
        assert f"{key}: {label}" in suggest.SUGGEST_INSTRUCTION


def test_a_request_names_only_a_type_in_the_file() -> None:
    adapter = TypeAdapter(verticals.BusinessTypeKey)
    for key in verticals.all_keys():
        assert adapter.validate_python(key) == key
    with pytest.raises(ValidationError):
        adapter.validate_python("bakery")


def test_the_examples_endpoint_shape_is_the_files() -> None:
    assert set(BusinessTypeExamplesOut.model_fields) == set(verticals.EXAMPLE_KEYS)


def test_runtime_code_imports_no_script() -> None:
    """FAILS IF: a module the api or a worker runs imports from `scripts/`, which is not part
    of what those processes are built to need."""
    offenders = [
        str(path.relative_to(ROOT))
        for path in (ROOT / "apps").rglob("*.py")
        if not path.name.endswith("_test.py")
        and re.search(r"^\s*(?:from scripts[ .]|import scripts\b)", path.read_text("utf-8"), re.M)
    ]
    assert offenders == []


async def test_the_pickers_read_the_list_without_signing_in() -> None:
    assert "GET /v1/public/business-types" in UNAUTHENTICATED_ROUTES
    address = f"203.0.113.{uuid.uuid4().int % 250 + 1}"
    async with AsyncClient(
        transport=ASGITransport(app=app, client=(address, 4321)), base_url="http://api"
    ) as http:
        response = await http.get("/v1/public/business-types")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == BUSINESS_TYPES_CACHE_CONTROL
    body = response.json()
    assert body["custom"] == verticals.CUSTOM
    assert [row["value"] for row in body["choices"]] == list(verticals.all_keys())
    for row in body["choices"]:
        assert set(row) == set(BusinessTypeOptionOut.model_fields)
        shipped = verticals.of(row["value"])
        assert (row["label"], row["hint"]) == (shipped.label, shipped.hint)
    by_key = {row["value"]: row for row in body["choices"]}
    assert by_key["real_estate"]["examples"]["org_name"]
    assert by_key[verticals.CUSTOM]["examples"] is None
