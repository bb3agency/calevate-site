"""API contract (audit 8 Nov 2026, lane T4): reachable input that answered a 500.

- An `offset` past Postgres' `bigint` reached `OFFSET` and the database refused it
  (`NumericValueOutOfRange`), on every offset-paged list.
- A time whose UTC instant `datetime` cannot hold (`9999-12-31T23:59:59-12:00`,
  `0001-01-01T00:00:00+14:00`) raised `OverflowError` in `astimezone`, or was stored as a
  year-1-BC `timestamptz` that every later read of the row then failed on.
"""

from __future__ import annotations

import typing
import uuid

import pytest
from apps.api.admin.routes import DltRegistrationIn
from apps.api.callbacks.routes import CallbackMoveIn
from apps.api.core.rbac import iter_api_routes
from apps.api.core.schemas import MAX_OFFSET, Instant
from apps.api.crm.one_call import OneCallIn
from apps.api.crm.swipe import ScheduleCallbackIn
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, TypeAdapter, ValidationError
from tests.api_security_test import _make_tenant

TOO_FAR = "9999-12-31T23:59:59-12:00"
TOO_EARLY = "0001-01-01T00:00:00+14:00"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _offset_params() -> list[tuple[str, typing.Any]]:
    found = []
    for route in iter_api_routes(app):

        def walk(dep: typing.Any) -> typing.Iterator[typing.Any]:
            yield from dep.query_params
            for sub in dep.dependencies:
                yield from walk(sub)

        found += [(route.path, p) for p in walk(route.dependant) if p.name == "offset"]
    return found


def test_every_offset_parameter_stops_at_the_bigint_postgres_takes() -> None:
    params = _offset_params()
    assert params, "no offset-paged route found; the census is looking at the wrong app"
    unbounded = [
        path
        for path, p in params
        if not any(getattr(m, "le", None) is not None for m in p.field_info.metadata)
        or min(m.le for m in p.field_info.metadata if getattr(m, "le", None) is not None)
        > MAX_OFFSET
    ]
    assert unbounded == []


async def test_an_offset_past_bigint_is_a_422_not_a_500() -> None:
    _tenant_id, _slug, token = await _make_tenant("owner")
    headers = {"Authorization": f"Bearer {token}"}
    async with _client() as http:
        for path in ("/v1/calls", "/v1/leads", "/v1/campaigns/page", "/v1/knowledge-gaps"):
            response = await http.get(path, params={"offset": str(MAX_OFFSET + 1)}, headers=headers)
            assert response.status_code == 422, (path, response.text)
            assert response.headers["content-type"].startswith("application/problem+json")
            ok = await http.get(path, params={"offset": "0"}, headers=headers)
            assert ok.status_code == 200, (path, ok.text)


@pytest.mark.parametrize("moment", [TOO_FAR, TOO_EARLY])
def test_an_instant_with_no_utc_twin_is_refused(moment: str) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(Instant).validate_python(moment)


def test_an_ordinary_instant_still_passes() -> None:
    parsed = TypeAdapter(Instant).validate_python("2026-11-20T10:00:00+05:30")
    assert parsed.utcoffset() is not None


@pytest.mark.parametrize(
    ("model", "body"),
    [
        (CallbackMoveIn, {"at": TOO_FAR}),
        (CallbackMoveIn, {"at": TOO_EARLY}),
        (ScheduleCallbackIn, {"at": TOO_FAR}),
        (OneCallIn, {"agent_id": str(uuid.uuid4()), "phone": "+919000000001", "at": TOO_FAR}),
        (
            DltRegistrationIn,
            {"status": "submitted", "tm_link_status": "pending", "registered_at": TOO_EARLY},
        ),
    ],
)
def test_route_models_refuse_an_out_of_range_time(model: type[BaseModel], body: dict) -> None:
    with pytest.raises(ValidationError) as excinfo:
        model.model_validate(body)
    time_field = next(k for k in body if k in ("at", "registered_at"))
    assert [e["loc"][0] for e in excinfo.value.errors()] == [time_field]


async def test_moving_a_call_back_to_the_end_of_time_is_a_422_not_a_500() -> None:
    _tenant_id, _slug, token = await _make_tenant("owner")
    async with _client() as http:
        response = await http.patch(
            f"/v1/callbacks/{uuid.uuid4()}",
            json={"at": TOO_FAR},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 422, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
