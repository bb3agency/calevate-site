"""The two CSV exports render their file on a worker thread, not on the event loop.

Each export reads up to `MAX_EXPORT_ROWS` rows and builds the whole file in the request.
Redacting 20k call summaries alone is ~0.45 s of CPU (measured in the test container), and
on the event loop that stalls every other request the API process is serving.
"""

from __future__ import annotations

import csv
import io
import threading
from typing import Any

import pytest
from apps.api.crm import service
from tests.api_security_test import _make_tenant
from tests.calls_filters_export_test import _client as calls_client
from tests.calls_filters_export_test import _headers as calls_headers
from tests.calls_filters_export_test import _seed_calls
from tests.lead_columns_test import _client as leads_client
from tests.lead_columns_test import _lead
from tests.lead_columns_test import _tenant as leads_tenant

pytestmark = [pytest.mark.rls]


def _recording(original: Any, threads: list[int]) -> Any:
    def wrapped(*args: Any) -> str:
        threads.append(threading.get_ident())
        return str(original(*args))

    return wrapped


async def test_the_calls_file_is_rendered_off_the_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, slug, token = await _make_tenant()
    await _seed_calls(tenant_id)
    threads: list[int] = []
    monkeypatch.setattr(service, "_calls_csv", _recording(service._calls_csv, threads))
    async with calls_client() as http:
        exported = await http.get("/v1/calls/export.csv", headers=calls_headers(slug, token))
    assert exported.status_code == 200, exported.text
    assert len(list(csv.reader(io.StringIO(exported.text)))) == 4  # header + three calls
    assert threads and threads[0] != threading.get_ident()


async def test_the_leads_file_is_rendered_off_the_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    t = await leads_tenant()
    await _lead(t, name="Ramesh")
    threads: list[int] = []
    monkeypatch.setattr(service, "_leads_csv", _recording(service._leads_csv, threads))
    async with leads_client() as http:
        exported = await http.get("/v1/leads/export.csv", headers=t.headers)
    assert exported.status_code == 200, exported.text
    rows = list(csv.reader(io.StringIO(exported.text)))
    assert len(rows) == 2 and "Ramesh" in rows[1][0]
    assert threads and threads[0] != threading.get_ident()
