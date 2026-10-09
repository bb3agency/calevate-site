"""A ThinnestAI account in memory: our developer workspace and its customer workspaces (D-693).

Built from `thinnest-findings/mirror/snapshots/2026-10-08/pages/api-reference/`: customers
(`customers.md`, `customers/*.md`), phone numbers (`phone-numbers/*.md`), business details
(`phone-numbers/get-business-details.md`, `send-business-details.md`), `GET /workspace`.
Every request is recorded with the workspace header it carried, so a test can assert which
workspace each call acted in.
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from apps.api.core.settings import get_settings
from apps.api.engine.thinnest import BASE_URL, ThinnestEngine
from apps.api.engine.thinnest_customer_data import (
    ThinnestCustomerData,
    set_thinnest_customer_data,
)
from apps.api.engine.thinnest_customers import ThinnestCustomers, set_thinnest_customers
from apps.api.engine.thinnest_numbers import ThinnestNumbers, set_thinnest_numbers
from apps.api.engine.thinnest_workspace import WORKSPACE_HEADER, remember_developer_workspace

DEVELOPER = "org_developer-ours"


def _err(status: int, code: str, message: str = "x") -> httpx.Response:
    return httpx.Response(status, json={"error": message, "code": code})


@dataclass
class Workspace:
    numbers: dict[str, dict[str, Any]] = field(default_factory=dict)
    business: dict[str, Any] = field(default_factory=lambda: {"status": "none"})
    agents: set[str] = field(default_factory=set)
    live_calls: dict[str, int] = field(default_factory=dict)


@dataclass
class Sent:
    method: str
    path: str
    workspace: str | None
    query: dict[str, str]
    body: bytes


class FakeAccount:
    def __init__(self, *, cap: int = 3) -> None:
        self.cap = cap
        self.customers: dict[str, dict[str, Any]] = {}
        self.workspaces: dict[str | None, Workspace] = {None: Workspace()}
        self.sent: list[Sent] = []
        self.available: list[str] = [f"9180{secrets.randbelow(10**8):08d}" for _ in range(25)]
        self.balance_ok = True
        self.business_on_send = "submitted"

    # --- helpers for tests -------------------------------------------------------------

    def ws(self, workspace: str | None) -> Workspace:
        return self.workspaces.setdefault(workspace, Workspace())

    def add_customer(self, external_id: str, *, archived: bool = False) -> str:
        workspace = f"org_{secrets.token_hex(6)}"
        self.customers[workspace] = {
            "id": workspace,
            "externalId": external_id,
            "archivedAt": "2026-10-01T00:00:00Z" if archived else None,
            "eraseAfter": None,
        }
        self.ws(workspace)
        return workspace

    def hold(
        self,
        workspace: str | None,
        number: str,
        *,
        rented: bool = True,
        agent: str | None = None,
        calling: str | None = None,
    ) -> None:
        self.ws(workspace).numbers[number] = {
            "number": number,
            "label": None,
            "source": "rented" if rented else "brought",
            "agent": agent,
            "callingAgent": calling,
            "since": "2026-10-08T07:15:40Z",
            "provider": None,
        }

    def calls_in(self, workspace: str | None) -> list[Sent]:
        return [s for s in self.sent if s.workspace == workspace]

    # --- the wire ----------------------------------------------------------------------

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v1")
        workspace = request.headers.get(WORKSPACE_HEADER)
        self.sent.append(
            Sent(request.method, path, workspace, dict(request.url.params), request.content)
        )
        if workspace is not None and workspace not in self.customers:
            return _err(404, "workspace_not_found", "Workspace not found.")
        if path == "/workspace" and request.method == "GET":
            return httpx.Response(200, json={"id": DEVELOPER, "name": "Calevate"})
        if path.startswith("/customers"):
            return self._customers(request, path)
        if path.startswith("/phone-numbers"):
            return self._numbers(request, path, workspace)
        if path == "/calls" and request.method == "GET":
            agent = request.url.params.get("agent") or ""
            n = self.ws(workspace).live_calls.get(agent, 0)
            return httpx.Response(
                200, json={"items": [{"id": f"c{i}"} for i in range(n)], "nextCursor": None}
            )
        if path.startswith("/agents/") and request.method == "DELETE":
            self.ws(workspace).agents.discard(path.split("/")[2])
            return httpx.Response(204)
        return _err(404, "not_found")

    def _customers(self, request: httpx.Request, path: str) -> httpx.Response:
        if path == "/customers" and request.method == "GET":
            ext = request.url.params.get("externalId")
            archived = request.url.params.get("archived") == "true"
            items = [
                c
                for c in self.customers.values()
                if c["externalId"] == ext and (c["archivedAt"] is not None) == archived
            ]
            return httpx.Response(200, json={"items": items, "nextCursor": None})
        if path == "/customers" and request.method == "POST":
            body = json.loads(request.content)
            if any(c["externalId"] == body["externalId"] for c in self.customers.values()):
                return _err(409, "conflict", "externalId taken")
            if len(self.customers) >= self.cap:
                return _err(402, "plan_limit", "This plan includes 3 customers.")
            workspace = self.add_customer(body["externalId"])
            return httpx.Response(201, json=self.customers[workspace])
        workspace = path.split("/")[2]
        row = self.customers.get(workspace)
        if row is None:
            return _err(404, "not_found")
        if path.endswith("/restore"):
            row["archivedAt"] = None
            return httpx.Response(200, json=row)
        if request.method == "DELETE":
            if any(n["source"] == "rented" for n in self.ws(workspace).numbers.values()):
                return _err(409, "conflict", "Release its numbers first.")
            row["archivedAt"] = "2026-10-09T00:00:00Z"
            return httpx.Response(200, json=row)
        return httpx.Response(200, json=row)

    def _numbers(self, request: httpx.Request, path: str, workspace: str | None) -> httpx.Response:
        place = self.ws(workspace)
        if path == "/phone-numbers/business-details":
            if request.method == "PUT":
                place.business = {
                    "status": self.business_on_send,
                    "businessName": "Acme",
                    "canRent": self.business_on_send == "accepted",
                    "submittedAt": "2026-10-09T09:00:00Z",
                }
                return httpx.Response(201, json=place.business)
            return httpx.Response(200, json=place.business)
        if path == "/phone-numbers/available/cities":
            return httpx.Response(
                200, json={"items": [{"name": "Bangalore", "available": 25}], "nextCursor": None}
            )
        if path == "/phone-numbers/available":
            start = int(request.url.params.get("cursor") or 0)
            page = self.available[start : start + 20]
            following = str(start + 20) if start + 20 < len(self.available) else None
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "number": n,
                            "city": "Bangalore",
                            "monthlyPrice": {"amountMinor": 34900, "currency": "INR"},
                        }
                        for n in page
                    ],
                    "nextCursor": following,
                },
            )
        if path == "/phone-numbers" and request.method == "GET":
            return httpx.Response(
                200, json={"items": list(place.numbers.values()), "nextCursor": None}
            )
        if path == "/phone-numbers" and request.method == "POST":
            number = json.loads(request.content)["number"]
            if not place.business.get("canRent"):
                return _err(409, "conflict", "Your business details are still being checked.")
            if not self.balance_ok:
                return _err(402, "insufficient_balance", "Top up first.")
            if any(number in w.numbers for w in self.workspaces.values()):
                return _err(409, "conflict", "Somebody already holds that number.")
            self.hold(workspace, number)
            return httpx.Response(201, json=place.numbers[number])
        number = path.removeprefix("/phone-numbers/")
        row = place.numbers.get(number)
        if row is None:
            return _err(404, "not_found", "That number was not found.")
        if request.method == "GET":
            return httpx.Response(200, json=row)
        if request.method == "DELETE":
            if row["source"] == "rented" and request.url.params.get("confirm") != "release":
                return _err(409, "conflict", "Repeat with ?confirm=release.")
            del place.numbers[number]
            return httpx.Response(204)
        body = json.loads(request.content)
        row.update({k: v for k, v in body.items() if k in ("agent", "callingAgent", "label")})
        return httpx.Response(200, json=row)


def _client(account: FakeAccount) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(account.handler),
        base_url=BASE_URL,
        headers={"Authorization": "Bearer ta_live_test"},
    )


@pytest.fixture
def account(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeAccount]:
    """The fake account installed behind every ThinnestAI client, on `ENGINE=thinnest`."""
    import apps.api.engine as engine_module

    fake = FakeAccount()
    set_thinnest_customers(ThinnestCustomers(api_key="ta_live_test", client=_client(fake)))
    set_thinnest_numbers(ThinnestNumbers(api_key="ta_live_test", client=_client(fake)))
    set_thinnest_customer_data(ThinnestCustomerData(api_key="ta_live_test", client=_client(fake)))
    from apps.api.engine.thinnest_actions import ThinnestActions, set_thinnest_actions

    set_thinnest_actions(ThinnestActions(api_key="ta_live_test", client=_client(fake)))
    previous = dict(engine_module._instances)
    engine_module._instances["thinnest"] = ThinnestEngine(
        api_key="ta_live_test", client=_client(fake)
    )
    monkeypatch.setattr(get_settings(), "engine", "thinnest")
    try:
        yield fake
    finally:
        set_thinnest_customers(None)
        set_thinnest_numbers(None)
        set_thinnest_customer_data(None)
        set_thinnest_actions(None)
        remember_developer_workspace(None)
        engine_module._instances.clear()
        engine_module._instances.update(previous)


__all__ = ["DEVELOPER", "FakeAccount", "Sent", "Workspace", "account"]
